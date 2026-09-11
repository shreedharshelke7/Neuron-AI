"""Session Controller coordinating Block 1 interfaces and interaction lifecycle."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, List, Optional

from app.audio.errors import AudioError
from app.audio.model import AudioCaptureResult
from app.audio.service import AudioCaptureService
from app.audio.vad import EndOfSpeechConfig, EndOfSpeechDetector
from app.capture.indicator import CaptureIndicator, StubCaptureIndicator
from app.capture.model import CapturedScreen, SelectedRegion
from app.capture.service import CaptureService, StubCaptureService
from app.overlay.host import OverlayHost, StubOverlayHost
from app.sequence.controller import SequenceController
from app.session.state import SessionState
from app.stt.adapter import STTAdapter
from app.stt.model import TranscriptResult, UserQuestion
from app.trigger.activation import ActivationTrigger, StubActivationTrigger
from app.tts.adapter import TTSAdapter
from app.tts.playback import AudioPlaybackService
from app.tutor.engine import TutorEngine
from app.tutor.model import TutorRequest, TutorResponse

logger = logging.getLogger(__name__)


class SessionController:
    """Central session controller for coordinating Block 1 and Block 2 components.

    Maintains lifecycle state (starting at IDLE) and coordinates activation,
    screen capture, audio recording, speech transcription, and overlay host interfaces
    without coupling to GUI window classes.
    """

    def __init__(
        self,
        activation_trigger: Optional[ActivationTrigger] = None,
        capture_service: Optional[CaptureService] = None,
        overlay_host: Optional[OverlayHost] = None,
        capture_indicator: Optional[CaptureIndicator] = None,
        audio_service: Optional[AudioCaptureService] = None,
        stt_adapter: Optional[STTAdapter] = None,
        stt_bridge: Optional[Any] = None,
        tutor_engine: Optional[TutorEngine] = None,
        tutor_bridge: Optional[Any] = None,
        tts_adapter: Optional[TTSAdapter] = None,
        playback_service: Optional[AudioPlaybackService] = None,
        sequence_controller: Optional[SequenceController] = None,
        sequence_bridge: Optional[Any] = None,
        eos_detector: Optional[EndOfSpeechDetector] = None,
        audio_bridge: Optional[Any] = None,
        auto_capture: bool = False,
        desktop_window: Optional[Any] = None,
        capture_delay_ms: int = 80,
    ) -> None:
        self._state: SessionState = SessionState.IDLE
        self._auto_capture: bool = auto_capture
        self._dismissing: bool = False
        self._state_listeners: List[Callable[[SessionState], None]] = []
        self._region_listeners: List[Callable[[SelectedRegion], None]] = []

        self._current_capture: Optional[CapturedScreen] = None
        self._selected_region: Optional[SelectedRegion] = None
        self._current_audio: Optional[AudioCaptureResult] = None
        self._current_transcript: Optional[TranscriptResult] = None
        self._current_tutor_response: Optional[TutorResponse] = None
        self._last_error_message: Optional[str] = None
        self._session_token: int = 0
        self._active_worker_thread: Optional[threading.Thread] = None

        self._desktop_window: Optional[Any] = desktop_window
        self._capture_delay_ms: int = capture_delay_ms
        self._window_was_visible: bool = False
        self._window_was_maximized: bool = False
        self._capture_pending: bool = False

        self.audio_service: Optional[AudioCaptureService] = audio_service
        self.stt_adapter: Optional[STTAdapter] = stt_adapter
        self._stt_bridge: Optional[Any] = stt_bridge
        self.tutor_engine: Optional[TutorEngine] = tutor_engine
        self._tutor_bridge: Optional[Any] = tutor_bridge
        self.tts_adapter: Optional[TTSAdapter] = tts_adapter
        self.playback_service: Optional[AudioPlaybackService] = playback_service
        self._sequence_bridge: Optional[Any] = sequence_bridge

        self.eos_detector: Optional[EndOfSpeechDetector] = (
            eos_detector if eos_detector is not None else EndOfSpeechDetector()
        )
        self._audio_bridge: Optional[Any] = audio_bridge
        if self.eos_detector is not None:
            self.eos_detector.set_on_end_of_speech(self._dispatch_end_of_speech)
            self.eos_detector.set_on_timeout(self._dispatch_no_speech_timeout)

        if self.audio_service is not None and hasattr(self.audio_service, "add_frame_listener"):
            try:
                self.audio_service.add_frame_listener(self._on_audio_frame)
            except Exception:
                pass

        self.capture_service: CaptureService = (
            capture_service or StubCaptureService()
        )
        self.overlay_host: OverlayHost = overlay_host or StubOverlayHost()
        self.capture_indicator: CaptureIndicator = (
            capture_indicator or StubCaptureIndicator()
        )
        self.activation_trigger: ActivationTrigger = (
            activation_trigger
            or StubActivationTrigger(on_activate=self.request_activation)
        )

        self.sequence_controller: Optional[SequenceController] = sequence_controller
        if self.sequence_controller is None and (self.tts_adapter is not None or self.playback_service is not None):
            self.sequence_controller = SequenceController(
                tts_adapter=self.tts_adapter,
                playback_service=self.playback_service,
                overlay_host=self.overlay_host,
                on_error=self.handle_tts_error,
            )

        # Connect overlay callbacks
        self.overlay_host.set_on_region_selected(self.on_region_selected)
        self.overlay_host.set_on_dismissed(self.dismiss)

    @property
    def state(self) -> SessionState:
        """Current session lifecycle state."""
        return self._state

    @property
    def current_capture(self) -> Optional[CapturedScreen]:
        """Ephemeral captured screen data for the active session."""
        return self._current_capture

    @property
    def selected_region(self) -> Optional[SelectedRegion]:
        """Currently selected region geometry."""
        return self._selected_region

    @property
    def current_audio(self) -> Optional[AudioCaptureResult]:
        """Ephemeral captured audio data for the active session."""
        return self._current_audio

    @property
    def current_transcript(self) -> Optional[TranscriptResult]:
        """Ephemeral transcript result for the active session."""
        return self._current_transcript

    @property
    def current_tutor_response(self) -> Optional[TutorResponse]:
        """Ephemeral tutor response result for the active session."""
        return self._current_tutor_response

    @property
    def last_error_message(self) -> Optional[str]:
        """Human-readable message for the last encountered error."""
        return self._last_error_message

    @property
    def session_token(self) -> int:
        """Monotonic generation counter for race and cancellation protection."""
        return self._session_token

    @property
    def desktop_window(self) -> Optional[Any]:
        """Registered desktop window if any."""
        return self._desktop_window

    def set_desktop_window(self, window: Optional[Any]) -> None:
        """Register or unregister the desktop shell window for pre-capture hide/restore."""
        self._desktop_window = window

    @property
    def capture_delay_ms(self) -> int:
        """Delay in milliseconds before screen capture to allow desktop repainting."""
        return self._capture_delay_ms

    @capture_delay_ms.setter
    def capture_delay_ms(self, delay_ms: int) -> None:
        self._capture_delay_ms = max(0, int(delay_ms))

    def _restore_desktop_window(self) -> None:
        """Safely restore desktop window visibility and layout."""
        self._capture_pending = False
        win = self._desktop_window
        if win is None or not self._window_was_visible:
            return

        try:
            if self._window_was_maximized and hasattr(win, "showMaximized"):
                win.showMaximized()
            elif hasattr(win, "showNormal"):
                win.showNormal()
            elif hasattr(win, "show"):
                win.show()
        except Exception as exc:
            logger.warning("Error restoring desktop window: %s", exc)

    def set_stt_bridge(self, bridge: Any) -> None:
        """Set or update the bridge object used to marshal worker events."""
        self._stt_bridge = bridge

    def set_tutor_bridge(self, bridge: Any) -> None:
        """Set or update the bridge object used to marshal tutor worker events."""
        self._tutor_bridge = bridge

    def set_audio_bridge(self, bridge: Any) -> None:
        """Set or update the bridge object used to marshal audio events."""
        self._audio_bridge = bridge

    def set_eos_detector(self, detector: Optional[EndOfSpeechDetector]) -> None:
        """Configure or swap the active end-of-speech detector."""
        if self.eos_detector is not None:
            self.eos_detector.stop()
        self.eos_detector = detector
        if self.eos_detector is not None:
            self.eos_detector.set_on_end_of_speech(self._dispatch_end_of_speech)
            self.eos_detector.set_on_timeout(self._dispatch_no_speech_timeout)

    def set_audio_service(self, audio_service: Optional[AudioCaptureService]) -> None:
        """Configure or swap the audio capture service and wire frame listeners."""
        if self.audio_service is not None and hasattr(self.audio_service, "remove_frame_listener"):
            try:
                self.audio_service.remove_frame_listener(self._on_audio_frame)
            except Exception:
                pass
        self.audio_service = audio_service
        if self.audio_service is not None and hasattr(self.audio_service, "add_frame_listener"):
            try:
                self.audio_service.add_frame_listener(self._on_audio_frame)
            except Exception:
                pass

    def _on_audio_frame(self, chunk: bytes) -> None:
        """Receive raw audio frames during LISTENING and route to EndOfSpeechDetector."""
        if self._state == SessionState.LISTENING and self.eos_detector is not None:
            self.eos_detector.process_frame(chunk)

    def _dispatch_end_of_speech(self, token: int) -> None:
        """Dispatch end-of-speech event via Qt bridge or directly."""
        bridge = self._audio_bridge
        if bridge is not None and hasattr(bridge, "emit_end_of_speech"):
            bridge.emit_end_of_speech(token)
        elif bridge is not None and hasattr(bridge, "end_of_speech_detected"):
            bridge.end_of_speech_detected.emit(token)
        else:
            self.handle_end_of_speech(token)

    def _dispatch_no_speech_timeout(self, token: int) -> None:
        """Dispatch no-speech timeout event via Qt bridge or directly."""
        bridge = self._audio_bridge
        if bridge is not None and hasattr(bridge, "emit_timeout"):
            bridge.emit_timeout(token)
        elif bridge is not None and hasattr(bridge, "no_speech_timeout"):
            bridge.no_speech_timeout.emit(token)
        else:
            self.handle_no_speech_timeout(token)

    def handle_end_of_speech(self, token: int) -> None:
        """Handle automatic end-of-speech detection."""
        if token != self._session_token or self._state != SessionState.LISTENING:
            logger.debug(
                "Dropping stale or late end-of-speech event (token=%d, current=%d, state=%s).",
                token,
                self._session_token,
                self._state,
            )
            return

        logger.info("Automatic end-of-speech detected. Stopping microphone recording.")
        self.stop_listening()

    def handle_no_speech_timeout(self, token: int) -> None:
        """Handle timeout when no speech was detected after activation."""
        if token != self._session_token or self._state != SessionState.LISTENING:
            logger.debug(
                "Dropping stale or late no-speech timeout (token=%d, current=%d, state=%s).",
                token,
                self._session_token,
                self._state,
            )
            return

        logger.info("Listening timed out with no speech detected. Returning to IDLE.")
        self._last_error_message = "No speech detected"
        self.dismiss()

    def add_state_listener(self, listener: Callable[[SessionState], None]) -> None:
        """Register a callback invoked when the session state changes."""
        self._state_listeners.append(listener)

    def remove_state_listener(self, listener: Callable[[SessionState], None]) -> None:
        """Unregister a state listener callback."""
        if listener in self._state_listeners:
            self._state_listeners.remove(listener)

    def add_region_listener(
        self, listener: Callable[[SelectedRegion], None]
    ) -> None:
        """Register a callback invoked when a region is selected by the user."""
        self._region_listeners.append(listener)

    def remove_region_listener(
        self, listener: Callable[[SelectedRegion], None]
    ) -> None:
        """Unregister a region listener callback."""
        if listener in self._region_listeners:
            self._region_listeners.remove(listener)

    def _set_state(self, new_state: SessionState) -> None:
        if self._state != new_state:
            self._state = new_state
            for listener in list(self._state_listeners):
                try:
                    listener(self._state)
                except Exception as ex:
                    logger.exception("Error in state listener: %s", ex)

    def start_listening(self) -> None:
        """Begin audio capture and transition state to LISTENING."""
        if self.audio_service is None:
            return

        try:
            self.audio_service.start_recording()
            self._set_state(SessionState.LISTENING)
            if self.eos_detector is not None:
                self.eos_detector.reset(token=self._session_token)
        except AudioError as err:
            logger.warning("Microphone start failed: %s", err)
            self._last_error_message = str(err)
            self._set_state(SessionState.ERROR)
            self.dismiss()
        except Exception as exc:
            logger.exception("Unexpected error starting microphone: %s", exc)
            self._last_error_message = "Microphone unavailable"
            self._set_state(SessionState.ERROR)
            self.dismiss()

    def stop_listening(self) -> Optional[AudioCaptureResult]:
        """Stop audio capture, store session audio, and transition to TRANSCRIBING or VOICE_CAPTURED."""
        if self.eos_detector is not None:
            self.eos_detector.stop()

        if self.audio_service is None or not self.audio_service.is_recording:
            return None

        try:
            result = self.audio_service.stop_recording()
        except AudioError as err:
            logger.warning("Microphone stop failed: %s", err)
            self._last_error_message = str(err)
            self._current_audio = None
            self._set_state(SessionState.ERROR)
            self.dismiss()
            return None
        except Exception as exc:
            logger.exception("Unexpected error stopping microphone: %s", exc)
            self._last_error_message = "Audio capture failed"
            self._current_audio = None
            self._set_state(SessionState.ERROR)
            self.dismiss()
            return None

        self._current_audio = result

        if self.stt_adapter is None:
            self._set_state(SessionState.VOICE_CAPTURED)
            return result

        self._session_token += 1
        current_token = self._session_token
        self._set_state(SessionState.TRANSCRIBING)
        self._start_transcription_worker(result, current_token)
        return result

    def _start_transcription_worker(
        self, audio: AudioCaptureResult, token: int
    ) -> None:
        """Spawn a background daemon thread to run STT transcription."""
        bridge = self._stt_bridge
        adapter = self.stt_adapter

        def _worker() -> None:
            try:
                assert adapter is not None
                transcript_res = adapter.transcribe(audio)
                if bridge is not None and hasattr(bridge, "emit_result"):
                    bridge.emit_result(transcript_res, token)
                elif bridge is not None and hasattr(bridge, "result_ready"):
                    bridge.result_ready.emit(transcript_res, token)
                else:
                    self.handle_transcription_success(transcript_res, token)
            except Exception as exc:
                err_msg = str(exc)
                if bridge is not None and hasattr(bridge, "emit_error"):
                    bridge.emit_error(err_msg, token)
                elif bridge is not None and hasattr(bridge, "error_occurred"):
                    bridge.error_occurred.emit(err_msg, token)
                else:
                    self.handle_transcription_error(err_msg, token)

        worker_thread = threading.Thread(
            target=_worker,
            name=f"Neuron-STT-Worker-{token}",
            daemon=True,
        )
        self._active_worker_thread = worker_thread
        worker_thread.start()

    def handle_transcription_success(
        self, result: TranscriptResult, token: int
    ) -> None:
        """Handle successful transcription result from background worker."""
        if token != self._session_token or self._state != SessionState.TRANSCRIBING:
            logger.debug(
                "Dropping late or stale transcription result (token=%d, current_token=%d, state=%s).",
                token,
                self._session_token,
                self._state,
            )
            return

        self._current_transcript = result
        self._current_audio = None  # Ephemeral raw audio released immediately on success
        self._set_state(SessionState.TRANSCRIBED)

        if self.tutor_engine is not None and not result.is_empty:
            self._start_tutor_flow(result, token)

    def handle_transcription_error(
        self, error_message: str, token: int
    ) -> None:
        """Handle transcription failure from background worker."""
        if token != self._session_token or self._state != SessionState.TRANSCRIBING:
            logger.debug(
                "Dropping late or stale transcription error (token=%d, current_token=%d, state=%s).",
                token,
                self._session_token,
                self._state,
            )
            return

        self._last_error_message = error_message
        self._current_audio = None  # Ephemeral raw audio released on failure
        self._current_transcript = None
        self._set_state(SessionState.ERROR)

    def _start_tutor_flow(self, transcript_result: TranscriptResult, token: int) -> None:
        """Construct TutorRequest and transition to THINKING."""
        if token != self._session_token or self._state != SessionState.TRANSCRIBED:
            return
        user_question = UserQuestion.from_transcript_result(transcript_result)
        request = TutorRequest(
            question=user_question,
            capture=self._current_capture,
            selected_region=self._selected_region,
            session_token=token,
        )
        self._set_state(SessionState.THINKING)
        self._start_tutor_worker(request, token)

    def _start_tutor_worker(
        self, request: TutorRequest, token: int
    ) -> None:
        """Spawn a background daemon thread to run Tutor reasoning."""
        bridge = self._tutor_bridge
        engine = self.tutor_engine

        def _worker() -> None:
            try:
                assert engine is not None
                tutor_res = engine.process_request(request)
                if bridge is not None and hasattr(bridge, "emit_result"):
                    bridge.emit_result(tutor_res, token)
                elif bridge is not None and hasattr(bridge, "result_ready"):
                    bridge.result_ready.emit(tutor_res, token)
                else:
                    self.handle_tutor_success(tutor_res, token)
            except Exception as exc:
                err_msg = str(exc)
                if bridge is not None and hasattr(bridge, "emit_error"):
                    bridge.emit_error(err_msg, token)
                elif bridge is not None and hasattr(bridge, "error_occurred"):
                    bridge.error_occurred.emit(err_msg, token)
                else:
                    self.handle_tutor_error(err_msg, token)

        worker_thread = threading.Thread(
            target=_worker,
            name=f"Neuron-Tutor-Worker-{token}",
            daemon=True,
        )
        self._active_worker_thread = worker_thread
        worker_thread.start()

    def handle_tutor_success(
        self, result: TutorResponse, token: int
    ) -> None:
        """Handle successful tutor response from background worker."""
        if token != self._session_token or self._state != SessionState.THINKING:
            logger.debug(
                "Dropping late or stale tutor response (token=%d, current_token=%d, state=%s).",
                token,
                self._session_token,
                self._state,
            )
            return

        self._current_tutor_response = result
        self._set_state(SessionState.RESPONDED)

        # Render visual explanation on overlay surface
        try:
            geom = self._current_capture.geometry if self._current_capture else None
            self.overlay_host.render_tutor_response(
                response=result,
                geometry=geom,
                selected_region=self._selected_region,
            )
        except Exception as ex:
            logger.exception("Error rendering tutor response on overlay: %s", ex)

        # Start narration sequencing if configured
        if self.sequence_controller is not None and result.narration:
            geom = self._current_capture.geometry if self._current_capture else None
            try:
                self.sequence_controller.start_sequence(
                    response=result,
                    token=token,
                    geometry=geom,
                    selected_region=self._selected_region,
                )
            except Exception as ex:
                logger.exception("Error starting narration sequence: %s", ex)

    def handle_tts_error(self, error_message: str, token: int) -> None:
        """Handle recoverable TTS failure during narration sequencing."""
        if token != self._session_token:
            logger.debug(
                "Dropping late or stale TTS error (token=%d, current_token=%d).",
                token,
                self._session_token,
            )
            return
        logger.warning("TTS error occurred during narration: %s", error_message)
        self._last_error_message = error_message

    def set_sequence_controller(self, sequence_controller: SequenceController) -> None:
        """Configure or swap the active sequence controller."""
        self.sequence_controller = sequence_controller
        self.sequence_controller.overlay_host = self.overlay_host

    def handle_tutor_error(
        self, error_message: str, token: int
    ) -> None:
        """Handle tutor failure from background worker."""
        if token != self._session_token or self._state != SessionState.THINKING:
            logger.debug(
                "Dropping late or stale tutor error (token=%d, current_token=%d, state=%s).",
                token,
                self._session_token,
                self._state,
            )
            return

        self._last_error_message = error_message
        self._current_tutor_response = None
        self._set_state(SessionState.ERROR)

    def request_tutor(self) -> None:
        """Manually trigger tutor reasoning for the current transcript and capture."""
        if self._current_transcript is None or self._current_transcript.is_empty:
            logger.warning("Cannot request tutor: no transcript available.")
            return
        if self.tutor_engine is None:
            logger.warning("Cannot request tutor: no tutor_engine configured.")
            return
        self._start_tutor_flow(self._current_transcript, self._session_token)

    def request_activation(self) -> None:
        """Handle an activation request from an activation trigger."""
        if self._state == SessionState.LISTENING:
            logger.debug("Activation hotkey received while LISTENING: stopping recording.")
            self.stop_listening()
            return

        if self._state in (
            SessionState.VOICE_CAPTURED,
            SessionState.TRANSCRIBED,
            SessionState.THINKING,
            SessionState.RESPONDED,
            SessionState.ERROR,
        ):
            self.dismiss()

        # Stop active narration playback if any sequence is running
        if self.sequence_controller is not None:
            try:
                self.sequence_controller.cancel()
            except Exception as ex:
                logger.warning("Error cancelling sequence controller on activation: %s", ex)

        if self._state != SessionState.IDLE:
            logger.debug("Activation request ignored (current state: %s).", self._state)
            return

        self._last_error_message = None
        self._current_audio = None
        self._current_transcript = None
        self._current_tutor_response = None
        if self.tts_adapter is not None and hasattr(self.tts_adapter, "reset_terminal_error"):
            try:
                self.tts_adapter.reset_terminal_error()
            except Exception:
                pass
        self._session_token += 1
        self._set_state(SessionState.ACTIVATED)

        if self._auto_capture:
            self.begin_capture_flow()
        else:
            if self.audio_service is not None:
                self.start_listening()

    def begin_capture_flow(self, delay_ms: Optional[int] = None) -> None:
        """Orchestrate pre-capture window hiding, compositor repaint, and capture sequence."""
        token = self._session_token
        self._set_state(SessionState.CAPTURING)

        win = self._desktop_window
        has_win_to_hide = False

        # Stop any active narration playback from previous session before capture
        if self.sequence_controller is not None:
            try:
                self.sequence_controller.cancel()
            except Exception as ex:
                logger.warning("Error cancelling sequence controller before capture: %s", ex)

        # Clear and hide any previous visual overlay before capturing so it does not contaminate screenshot
        if self.overlay_host is not None:
            try:
                self.overlay_host.clear_explanation()
                if self.overlay_host.is_visible():
                    has_win_to_hide = True
                    self.overlay_host.hide()
            except Exception as ex:
                logger.warning("Error clearing overlay before capture: %s", ex)

        if win is not None:
            self._window_was_visible = win.isVisible() if hasattr(win, "isVisible") else True
            self._window_was_maximized = win.isMaximized() if hasattr(win, "isMaximized") else False
            if self._window_was_visible and hasattr(win, "hide"):
                has_win_to_hide = True
                self._capture_pending = True
                win.hide()

            # Process pending Qt events so Windows/DWM registers the hide
            try:
                from PySide6.QtWidgets import QApplication

                qapp = QApplication.instance()
                if qapp is not None:
                    qapp.processEvents()
            except Exception:
                pass

        effective_delay = (
            delay_ms
            if delay_ms is not None
            else (self._capture_delay_ms if has_win_to_hide else 0)
        )

        if effective_delay > 0:
            try:
                from PySide6.QtCore import QTimer

                QTimer.singleShot(
                    effective_delay, lambda: self._execute_capture(token)
                )
                return
            except Exception as ex:
                logger.warning("Failed to schedule delayed capture: %s", ex)

        # Immediate capture (no window or delay_ms <= 0)
        self._execute_capture(token)

    def _execute_capture(self, token: int) -> None:
        """Execute screen capture while window is hidden, then restore window and continue."""
        if token != self._session_token or self._state != SessionState.CAPTURING:
            logger.debug(
                "Dropping stale capture execution (token=%d, current=%d, state=%s).",
                token,
                self._session_token,
                self._state,
            )
            self._restore_desktop_window()
            return

        captured = None
        try:
            self.capture_indicator.show()
            try:
                captured = self.capture_service.capture_current_screen()
            finally:
                self.capture_indicator.hide()
        except Exception as e:
            logger.exception("Screen capture failed: %s", e)
            self._set_state(SessionState.ERROR)
            self.reset_to_idle()
            return
        finally:
            self._restore_desktop_window()

        if token != self._session_token or self._state != SessionState.CAPTURING:
            logger.debug(
                "Dropping capture result after completion (token=%d, current=%d, state=%s).",
                token,
                self._session_token,
                self._state,
            )
            return

        if captured is not None and captured.geometry is not None:
            self._current_capture = captured
            self.overlay_host.show(geometry=captured.geometry)
            if self.audio_service is not None:
                self.start_listening()
            else:
                self._set_state(SessionState.SELECTING)
        else:
            logger.warning("Screen capture produced invalid or empty result.")
            self.reset_to_idle()

    def on_region_selected(self, region: SelectedRegion) -> None:
        """Handle region selection from the overlay host."""
        self._selected_region = region
        if self._state in (SessionState.CAPTURING, SessionState.SELECTING):
            self._set_state(SessionState.SELECTED)
        for listener in list(self._region_listeners):
            try:
                listener(region)
            except Exception as ex:
                logger.exception("Error in region listener: %s", ex)

    def dismiss(self) -> None:
        """Dismiss overlay, cancel active recording, clear active session state, and return to IDLE."""
        if self._dismissing:
            return

        self._dismissing = True
        try:
            # Invalidate any in-flight transcription worker or pending capture
            self._session_token += 1

            if self.eos_detector is not None:
                self.eos_detector.stop()

            if self._capture_pending:
                self._restore_desktop_window()

            if self.audio_service is not None:
                try:
                    self.audio_service.cancel_recording()
                except Exception as err:
                    logger.warning(
                        "Error cancelling audio recording during dismiss: %s", err
                    )

            self._current_audio = None
            self._current_transcript = None
            self._current_tutor_response = None

            if self.sequence_controller is not None:
                try:
                    self.sequence_controller.cancel()
                except Exception as ex:
                    logger.warning("Error cancelling sequence controller during dismiss: %s", ex)

            if self.overlay_host is not None:
                try:
                    self.overlay_host.clear_explanation()
                    if self.overlay_host.is_visible():
                        self.overlay_host.dismiss()
                except Exception as ex:
                    logger.warning("Error clearing overlay host during dismiss: %s", ex)
            self.capture_indicator.hide()
            self._current_capture = None
            self._selected_region = None
            self._set_state(SessionState.IDLE)
        finally:
            self._dismissing = False

    def reset_to_idle(self) -> None:
        """Alias for dismiss to cleanly return the session to IDLE."""
        self.dismiss()
