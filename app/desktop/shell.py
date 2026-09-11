"""Desktop shell application lifecycle and entry point runner."""

from __future__ import annotations

import logging
import sys
from typing import Any, List, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.audio.recorder import SoundDeviceAudioCaptureService
from app.audio.service import AudioCaptureService
from app.capture.qt_service import QtScreenCaptureService
from app.desktop.indicator import CaptureIndicatorWidget
from app.desktop.window import DesktopShellWindow
from app.overlay.qt_overlay import QtOverlayHost
from app.sequence.controller import SequenceController
from app.session.controller import SessionController
from app.stt.adapter import STTAdapter
from app.stt.whisper_stt import LocalWhisperSTTAdapter
from app.trigger.manager import ActivationManager
from app.tts.adapter import TTSAdapter
from app.tts.elevenlabs import ElevenLabsTTSAdapter
from app.tts.playback import AudioPlaybackService, SoundDevicePlaybackService
from app.tutor.engine import TutorEngine
from app.tutor.gemini import GeminiTutorAdapter
from app.wake.detector import WakeWordDetector
from app.wake.factory import create_wake_detector

logger = logging.getLogger(__name__)


class HotkeySignalBridge(QObject):
    """Qt signal bridge ensuring cross-thread hotkey events execute on GUI thread."""

    activated = Signal()


class STTSignalBridge(QObject):
    """Qt signal bridge ensuring worker thread transcription events execute on Qt GUI thread."""

    result_ready = Signal(object, int)  # (TranscriptResult, token)
    error_occurred = Signal(str, int)   # (error_message, token)

    def emit_result(self, result: Any, token: int) -> None:
        """Emit result_ready signal safely from worker thread."""
        self.result_ready.emit(result, token)

    def emit_error(self, error_message: str, token: int) -> None:
        """Emit error_occurred signal safely from worker thread."""
        self.error_occurred.emit(error_message, token)


class TutorSignalBridge(QObject):
    """Qt signal bridge ensuring worker thread tutor events execute on Qt GUI thread."""

    result_ready = Signal(object, int)  # (TutorResponse, token)
    error_occurred = Signal(str, int)   # (error_message, token)

    def emit_result(self, result: Any, token: int) -> None:
        """Emit result_ready signal safely from worker thread."""
        self.result_ready.emit(result, token)

    def emit_error(self, error_message: str, token: int) -> None:
        """Emit error_occurred signal safely from worker thread."""
        self.error_occurred.emit(error_message, token)


class SequenceSignalBridge(QObject):
    """Qt signal bridge ensuring worker thread TTS/sequencing events execute on Qt GUI thread."""

    narration_started = Signal(int)       # token
    narration_finished = Signal(int)      # token
    tts_error = Signal(str, int)          # (error_message, token)

    def emit_started(self, token: int) -> None:
        self.narration_started.emit(token)

    def emit_finished(self, token: int) -> None:
        self.narration_finished.emit(token)

    def emit_error(self, error_message: str, token: int) -> None:
        self.tts_error.emit(error_message, token)


class NeuronDesktopApp:
    """Manages the lifecycle of the Neuron desktop shell application."""

    def __init__(
        self,
        session_controller: Optional[SessionController] = None,
        activation_manager: Optional[ActivationManager] = None,
        audio_service: Optional[AudioCaptureService] = None,
        stt_adapter: Optional[STTAdapter] = None,
        tutor_engine: Optional[TutorEngine] = None,
        tts_adapter: Optional[TTSAdapter] = None,
        playback_service: Optional[AudioPlaybackService] = None,
        sequence_controller: Optional[SequenceController] = None,
        wake_detector: Optional[WakeWordDetector] = None,
        argv: Optional[List[str]] = None,
    ) -> None:
        self._argv = argv if argv is not None else sys.argv
        self._app: Optional[QApplication] = None
        self._window: Optional[DesktopShellWindow] = None

        # Ensure single QApplication exists prior to widget creation
        self.initialize_qapplication()

        # Signal bridges for thread-safe cross-thread execution
        self._bridge = HotkeySignalBridge()
        self._stt_bridge = STTSignalBridge()
        self._tutor_bridge = TutorSignalBridge()
        self._sequence_bridge = SequenceSignalBridge()

        # Instantiate concrete desktop services if not injected
        if session_controller is None:
            capture_service = QtScreenCaptureService()
            overlay_host = QtOverlayHost()
            capture_indicator = CaptureIndicatorWidget()
            final_tts_adapter = tts_adapter or ElevenLabsTTSAdapter()
            final_playback_service = playback_service or SoundDevicePlaybackService()
            final_sequence_controller = sequence_controller or SequenceController(
                tts_adapter=final_tts_adapter,
                playback_service=final_playback_service,
                overlay_host=overlay_host,
                on_started=self._sequence_bridge.emit_started,
                on_finished=self._sequence_bridge.emit_finished,
                on_error=self._sequence_bridge.emit_error,
            )
            self._session_controller = SessionController(
                capture_service=capture_service,
                overlay_host=overlay_host,
                capture_indicator=capture_indicator,
                audio_service=audio_service,
                stt_adapter=stt_adapter,
                stt_bridge=self._stt_bridge,
                tutor_engine=tutor_engine,
                tutor_bridge=self._tutor_bridge,
                tts_adapter=final_tts_adapter,
                playback_service=final_playback_service,
                sequence_controller=final_sequence_controller,
                sequence_bridge=self._sequence_bridge,
                auto_capture=True,
            )
        else:
            self._session_controller = session_controller
            self._session_controller.set_stt_bridge(self._stt_bridge)
            self._session_controller.set_tutor_bridge(self._tutor_bridge)

        self._bridge.activated.connect(self._session_controller.request_activation)
        self._stt_bridge.result_ready.connect(
            self._session_controller.handle_transcription_success
        )
        self._stt_bridge.error_occurred.connect(
            self._session_controller.handle_transcription_error
        )
        self._tutor_bridge.result_ready.connect(
            self._session_controller.handle_tutor_success
        )
        self._tutor_bridge.error_occurred.connect(
            self._session_controller.handle_tutor_error
        )
        self._sequence_bridge.tts_error.connect(
            self._session_controller.handle_tts_error
        )

        if activation_manager is None:
            final_wake_detector = (
                wake_detector if wake_detector is not None else create_wake_detector()
            )
            self._activation_manager = ActivationManager(
                on_activate=self._bridge.activated.emit,
                wake_detector=final_wake_detector,
            )
        else:
            self._activation_manager = activation_manager
            if wake_detector is not None and self._activation_manager.wake_detector is None:
                self._activation_manager.set_wake_detector(wake_detector)

        # Coordinate wake detector microphone ownership and self-audio immunity
        self._session_controller.add_state_listener(self._on_session_state_changed)

    def _on_session_state_changed(self, state: Any) -> None:
        """Coordinate wake detector microphone ownership and self-audio immunity based on state."""
        from app.session.state import SessionState

        if state == SessionState.IDLE:
            self._activation_manager.resume_wake_detection()
        else:
            self._activation_manager.pause_wake_detection()

    @property
    def session_controller(self) -> SessionController:
        """Access the session controller."""
        return self._session_controller

    @property
    def activation_manager(self) -> ActivationManager:
        """Access the activation manager."""
        return self._activation_manager

    @property
    def stt_bridge(self) -> STTSignalBridge:
        """Access the STT signal bridge."""
        return self._stt_bridge

    @property
    def tutor_bridge(self) -> TutorSignalBridge:
        """Access the Tutor signal bridge."""
        return self._tutor_bridge

    @property
    def sequence_bridge(self) -> SequenceSignalBridge:
        """Access the Sequence signal bridge."""
        return self._sequence_bridge

    def initialize_qapplication(self) -> QApplication:
        """Create or return the single QApplication instance."""
        app = QApplication.instance()
        if app is None:
            app = QApplication(self._argv)
        self._app = app
        return app

    def shutdown(self) -> None:
        """Cleanly unregister global hotkeys, dismiss overlays, and release resources."""
        logger.info("Initiating application shutdown.")
        if self._session_controller is not None:
            self._session_controller.dismiss()

        if self._activation_manager is not None:
            self._activation_manager.stop()

        if self._window is not None:
            self._window.close()

    def run(self) -> int:
        """Launch the desktop shell application and enter the event loop."""
        app = self.initialize_qapplication()
        app.setQuitOnLastWindowClosed(True)
        app.aboutToQuit.connect(self.shutdown)

        # Start global hotkey listener
        self._activation_manager.start()

        self._window = DesktopShellWindow(
            session_controller=self._session_controller,
            activation_trigger=self._activation_manager,
        )
        self._window.show()

        try:
            return app.exec()
        finally:
            self.shutdown()


def run_desktop_shell(
    argv: Optional[List[str]] = None,
    audio_service: Optional[AudioCaptureService] = None,
    stt_adapter: Optional[STTAdapter] = None,
    tutor_engine: Optional[TutorEngine] = None,
    tts_adapter: Optional[TTSAdapter] = None,
    playback_service: Optional[AudioPlaybackService] = None,
    wake_detector: Optional[WakeWordDetector] = None,
) -> int:
    """Convenience entry point function to launch the desktop shell."""
    service = (
        audio_service
        if audio_service is not None
        else SoundDeviceAudioCaptureService()
    )
    adapter = (
        stt_adapter
        if stt_adapter is not None
        else LocalWhisperSTTAdapter()
    )
    engine = (
        tutor_engine
        if tutor_engine is not None
        else TutorEngine(adapter=GeminiTutorAdapter())
    )
    app = NeuronDesktopApp(
        audio_service=service,
        stt_adapter=adapter,
        tutor_engine=engine,
        tts_adapter=tts_adapter,
        playback_service=playback_service,
        wake_detector=wake_detector,
        argv=argv,
    )
    return app.run()
