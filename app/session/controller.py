"""Session Controller coordinating Block 1 interfaces and interaction lifecycle."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, List, Optional

from app.audio.errors import AudioError
from app.audio.model import AudioCaptureResult
from app.audio.service import AudioCaptureService
from app.capture.indicator import CaptureIndicator, StubCaptureIndicator
from app.capture.model import CapturedScreen, SelectedRegion
from app.capture.service import CaptureService, StubCaptureService
from app.overlay.host import OverlayHost, StubOverlayHost
from app.session.state import SessionState
from app.stt.adapter import STTAdapter
from app.stt.model import TranscriptResult, UserQuestion
from app.trigger.activation import ActivationTrigger, StubActivationTrigger
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
        auto_capture: bool = False,
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

        self.audio_service: Optional[AudioCaptureService] = audio_service
        self.stt_adapter: Optional[STTAdapter] = stt_adapter
        self._stt_bridge: Optional[Any] = stt_bridge
        self.tutor_engine: Optional[TutorEngine] = tutor_engine
        self._tutor_bridge: Optional[Any] = tutor_bridge
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

    def set_stt_bridge(self, bridge: Any) -> None:
        """Set or update the bridge object used to marshal worker events."""
        self._stt_bridge = bridge

    def set_tutor_bridge(self, bridge: Any) -> None:
        """Set or update the bridge object used to marshal tutor worker events."""
        self._tutor_bridge = bridge

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

        if self._state != SessionState.IDLE:
            logger.debug("Activation request ignored (current state: %s).", self._state)
            return

        self._last_error_message = None
        self._current_audio = None
        self._current_transcript = None
        self._current_tutor_response = None
        self._session_token += 1
        self._set_state(SessionState.ACTIVATED)

        if self._auto_capture:
            self.begin_capture_flow()
        else:
            if self.audio_service is not None:
                self.start_listening()

    def begin_capture_flow(self) -> None:
        """Orchestrate the capture, indicator, and overlay display sequence."""
        # 1. Show capture indicator
        self.capture_indicator.show()
        self._set_state(SessionState.CAPTURING)

        try:
            # 2. Capture current screen
            captured = self.capture_service.capture_current_screen()
        except Exception as e:
            logger.exception("Screen capture failed: %s", e)
            self.capture_indicator.hide()
            self._set_state(SessionState.ERROR)
            self.reset_to_idle()
            return

        # 3. Dismiss capture indicator
        self.capture_indicator.hide()

        if captured is not None and captured.geometry is not None:
            self._current_capture = captured
            # 4. Show transparent overlay
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
        if self._state != SessionState.LISTENING:
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
            # Invalidate any in-flight transcription worker
            self._session_token += 1

            if self.audio_service is not None:
                try:
                    self.audio_service.cancel_recording()
                except Exception as err:
                    logger.warning("Error cancelling audio recording during dismiss: %s", err)

            self._current_audio = None
            self._current_transcript = None
            self._current_tutor_response = None

            if self.overlay_host.is_visible():
                self.overlay_host.dismiss()
            self.capture_indicator.hide()
            self._current_capture = None
            self._selected_region = None
            self._set_state(SessionState.IDLE)
        finally:
            self._dismissing = False

    def reset_to_idle(self) -> None:
        """Alias for dismiss to cleanly return the session to IDLE."""
        self.dismiss()
