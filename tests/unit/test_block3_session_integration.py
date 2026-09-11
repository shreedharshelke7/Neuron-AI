"""Unit tests for Block 3 session controller integration and state machine transitions."""

import time
import pytest

from app.audio.model import AudioCaptureResult
from app.capture.model import CapturedScreen, DisplayGeometry
from app.capture.service import CaptureService
from app.overlay.host import StubOverlayHost
from app.session.controller import SessionController
from app.session.state import SessionState
from app.stt.adapter import STTAdapter
from app.stt.model import TranscriptResult
from app.tutor.adapter import FakeTutorAdapter
from app.tutor.engine import TutorEngine
from app.tutor.errors import TutorUnavailableError
from app.tutor.model import OverlayAction, OverlayActionType, TutorResponse


class FakeCaptureService(CaptureService):
    def capture_current_screen(self):
        geom = DisplayGeometry(x=0, y=0, width=1920, height=1080)
        return CapturedScreen(image_data=b"fake_pixels", geometry=geom)


class ImmediateSTTAdapter(STTAdapter):
    def __init__(self, text="What is gravity?"):
        self.text = text

    def transcribe(self, audio: AudioCaptureResult) -> TranscriptResult:
        return TranscriptResult(transcript=self.text, audio_duration=2.0)


class FakeAudioService:
    def __init__(self):
        self.is_recording = False

    def start_recording(self):
        self.is_recording = True

    def stop_recording(self):
        self.is_recording = False
        return AudioCaptureResult(
            raw_bytes=b"\x00" * 3200,
            sample_rate=16000,
            channels=1,
            sample_width=2,
            duration_seconds=0.1,
        )

    def cancel_recording(self):
        self.is_recording = False


class TestBlock3SessionLifecycle:
    def test_full_flow_to_responded(self):
        audio_service = FakeAudioService()
        stt_adapter = ImmediateSTTAdapter("Explain Newton's law")
        fake_tutor = FakeTutorAdapter(
            default_response=TutorResponse(
                intent="explanation",
                summary="F equals m times a.",
                narration="Force is proportional to acceleration.",
                overlay_actions=[
                    OverlayAction(
                        action_type=OverlayActionType.FOCUS_BOX,
                        target_normalized=(0.2, 0.2, 0.4, 0.4),
                    )
                ],
            )
        )
        engine = TutorEngine(adapter=fake_tutor)

        controller = SessionController(
            audio_service=audio_service,
            stt_adapter=stt_adapter,
            tutor_engine=engine,
            auto_capture=False,
        )

        assert controller.state == SessionState.IDLE

        # 1. Activate & start listening
        controller.request_activation()
        assert controller.state == SessionState.LISTENING

        # 2. Stop listening -> triggers transcription and subsequent tutor flow
        controller.stop_listening()

        # Wait briefly for background threads to complete
        deadline = time.time() + 2.0
        while controller.state != SessionState.RESPONDED and time.time() < deadline:
            time.sleep(0.02)

        assert controller.state == SessionState.RESPONDED
        assert controller.current_tutor_response is not None
        assert controller.current_tutor_response.summary == "F equals m times a."
        assert len(controller.current_tutor_response.overlay_actions) == 1

    def test_dismiss_while_thinking_aborts_cleanly(self):
        audio_service = FakeAudioService()
        stt_adapter = ImmediateSTTAdapter("Test")

        # Fake adapter that blocks until we check
        def slow_handler(req):
            time.sleep(0.2)
            return TutorResponse(intent="hint", summary="Slow summary", narration="Slow narration")

        fake_tutor = FakeTutorAdapter(custom_handler=slow_handler)
        engine = TutorEngine(adapter=fake_tutor)

        controller = SessionController(
            audio_service=audio_service,
            stt_adapter=stt_adapter,
            tutor_engine=engine,
        )

        controller.request_activation()
        controller.stop_listening()

        # Wait until state is THINKING
        deadline = time.time() + 1.0
        while controller.state != SessionState.THINKING and time.time() < deadline:
            time.sleep(0.01)

        assert controller.state == SessionState.THINKING

        # Cancel / Escape during THINKING
        controller.dismiss()
        assert controller.state == SessionState.IDLE
        assert controller.current_tutor_response is None

        # Wait past the worker sleep time to ensure late response is ignored
        time.sleep(0.3)
        assert controller.state == SessionState.IDLE
        assert controller.current_tutor_response is None

    def test_tutor_error_transitions_to_error_state(self):
        audio_service = FakeAudioService()
        stt_adapter = ImmediateSTTAdapter("Test Error")

        fake_tutor = FakeTutorAdapter(exception_to_raise=TutorUnavailableError("Service down"))
        engine = TutorEngine(adapter=fake_tutor)

        controller = SessionController(
            audio_service=audio_service,
            stt_adapter=stt_adapter,
            tutor_engine=engine,
        )

        controller.request_activation()
        controller.stop_listening()

        deadline = time.time() + 2.0
        while controller.state != SessionState.ERROR and time.time() < deadline:
            time.sleep(0.02)

        assert controller.state == SessionState.ERROR
        assert "Service down" in (controller.last_error_message or "")
        assert controller.current_tutor_response is None

    def test_no_tutor_engine_preserves_transcribed_state(self):
        # Block 2 backward compatibility
        audio_service = FakeAudioService()
        stt_adapter = ImmediateSTTAdapter("Block 2 Standalone")

        controller = SessionController(
            audio_service=audio_service,
            stt_adapter=stt_adapter,
            tutor_engine=None,  # No tutor engine
        )

        controller.request_activation()
        controller.stop_listening()

        deadline = time.time() + 2.0
        while controller.state != SessionState.TRANSCRIBED and time.time() < deadline:
            time.sleep(0.02)

        assert controller.state == SessionState.TRANSCRIBED
        assert controller.current_tutor_response is None

    def test_empty_transcript_does_not_trigger_tutor(self):
        audio_service = FakeAudioService()
        stt_adapter = ImmediateSTTAdapter("")  # Empty speech

        fake_tutor = FakeTutorAdapter()
        engine = TutorEngine(adapter=fake_tutor)

        controller = SessionController(
            audio_service=audio_service,
            stt_adapter=stt_adapter,
            tutor_engine=engine,
        )

        controller.request_activation()
        controller.stop_listening()

        deadline = time.time() + 2.0
        while controller.state != SessionState.TRANSCRIBED and time.time() < deadline:
            time.sleep(0.02)

        assert controller.state == SessionState.TRANSCRIBED
        assert len(fake_tutor.recorded_requests) == 0

    def test_reactivation_from_responded_resets_first(self):
        audio_service = FakeAudioService()
        stt_adapter = ImmediateSTTAdapter("Question 1")
        fake_tutor = FakeTutorAdapter()
        engine = TutorEngine(adapter=fake_tutor)

        controller = SessionController(
            audio_service=audio_service,
            stt_adapter=stt_adapter,
            tutor_engine=engine,
        )

        controller.request_activation()
        controller.stop_listening()

        deadline = time.time() + 2.0
        while controller.state != SessionState.RESPONDED and time.time() < deadline:
            time.sleep(0.02)

        assert controller.state == SessionState.RESPONDED

        # Triggering activation again clears old response and starts fresh session
        controller.request_activation()
        assert controller.state == SessionState.LISTENING
        assert controller.current_tutor_response is None


class TestBlock3UIAndAppWiring:
    def test_window_thinking_and_responded_rendering(self):
        from PySide6.QtWidgets import QApplication
        from app.desktop.window import DesktopShellWindow

        app = QApplication.instance() or QApplication([])

        fake_tutor = FakeTutorAdapter()
        engine = TutorEngine(adapter=fake_tutor)
        controller = SessionController(tutor_engine=engine)
        window = DesktopShellWindow(session_controller=controller)
        window.show()

        # Test THINKING state
        controller._set_state(SessionState.THINKING)
        assert "THINKING" in window.state_label.text()
        assert "thinking" in window.audio_info_label.text().lower()
        assert not window.audio_info_label.isHidden()

        # Test RESPONDED state
        tutor_response = TutorResponse(
            intent="explanation",
            summary="Quantum superposition allows simultaneous states.",
            narration="When a quantum system is in superposition...",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.FOCUS_BOX,
                    target_normalized=(0.1, 0.2, 0.3, 0.4),
                )
            ],
        )
        controller._current_tutor_response = tutor_response
        controller._set_state(SessionState.RESPONDED)

        assert "RESPONDED" in window.state_label.text()
        assert "EXPLANATION" in window.audio_info_label.text()
        assert "Quantum superposition" in window.audio_info_label.text()
        assert "FOCUS_BOX" in window.audio_info_label.text()
        assert not window.audio_info_label.isHidden()

        # Test reset button resets to IDLE
        window.reset_button.click()
        assert controller.state == SessionState.IDLE
        assert window.audio_info_label.isHidden()

        window.close()

    def test_desktop_app_signal_bridge_wiring(self):
        from PySide6.QtWidgets import QApplication
        from app.desktop.shell import NeuronDesktopApp

        app = QApplication.instance() or QApplication([])

        fake_tutor = FakeTutorAdapter()
        engine = TutorEngine(adapter=fake_tutor)

        desktop_app = NeuronDesktopApp(tutor_engine=engine)
        controller = desktop_app.session_controller

        assert desktop_app.tutor_bridge is not None
        assert controller.tutor_engine is engine

        # Test bridge emit success
        controller._session_token = 42
        controller._set_state(SessionState.THINKING)

        resp = TutorResponse(intent="hint", summary="Test Hint", narration="Test Narration")
        desktop_app.tutor_bridge.emit_result(resp, 42)

        assert controller.state == SessionState.RESPONDED
        assert controller.current_tutor_response == resp

        # Test bridge emit error
        controller._session_token = 43
        controller._set_state(SessionState.THINKING)
        desktop_app.tutor_bridge.emit_error("API Quota Reached", 43)

        assert controller.state == SessionState.ERROR
        assert controller.last_error_message == "API Quota Reached"

