"""Integration tests for Block 2 Step 5: Session + STT Integration.

Deterministic in-memory tests using FakeAudioCaptureService and ControllableSTTAdapter.
Zero network access.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from typing import Optional
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from app.audio.service import FakeAudioCaptureService
from app.capture.model import CapturedScreen, DisplayGeometry
from app.capture.service import StubCaptureService
from app.desktop.shell import NeuronDesktopApp, STTSignalBridge
from app.desktop.window import DesktopShellWindow
from app.session.controller import SessionController
from app.session.state import SessionState
from app.stt.adapter import FakeSTTAdapter, STTAdapter
from app.stt.errors import EmptyTranscriptError, STTAuthenticationError, TranscriptionError
from app.stt.model import TranscriptResult


class ControllableSTTAdapter(STTAdapter):
    """Controllable fake STT adapter allowing deterministic thread synchronization and error injection."""

    def __init__(
        self,
        fake_transcript: str = "What is the derivative of x squared?",
        confidence: float = 0.96,
        language: str = "en-US",
        error_to_raise: Optional[Exception] = None,
        block_on_transcribe: bool = False,
    ) -> None:
        self.fake_transcript = fake_transcript
        self.confidence = confidence
        self.language = language
        self.error_to_raise = error_to_raise
        self.block_on_transcribe = block_on_transcribe
        self.transcribe_called = threading.Event()
        self.gate = threading.Event()
        if not block_on_transcribe:
            self.gate.set()
        self.worker_thread_id: Optional[int] = None
        self.call_count: int = 0

    def transcribe(self, audio) -> TranscriptResult:
        self.call_count += 1
        self.worker_thread_id = threading.get_ident()
        self.transcribe_called.set()

        # Wait on gate (for cancellation / race testing)
        self.gate.wait(timeout=5.0)

        if self.error_to_raise:
            raise self.error_to_raise

        return TranscriptResult(
            transcript=self.fake_transcript,
            audio_duration=audio.duration_seconds,
            language=self.language,
            confidence=self.confidence,
            is_final=True,
        )


class TestBlock2STTSessionIntegration(unittest.TestCase):
    """Test suite covering Block 2 Step 5 STT session lifecycle and UI integration."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.qapp = QApplication.instance() or QApplication([sys.argv[0]])

    def setUp(self) -> None:
        self.fake_audio = FakeAudioCaptureService(fake_duration_seconds=2.0)
        self.default_geom = DisplayGeometry(width=1920, height=1080)
        self.default_screen = CapturedScreen(geometry=self.default_geom)

    def _create_app(self, stt_adapter: STTAdapter) -> NeuronDesktopApp:
        """Create a complete NeuronDesktopApp with injected fake audio and STT adapter."""
        return NeuronDesktopApp(
            audio_service=self.fake_audio,
            stt_adapter=stt_adapter,
            argv=[sys.argv[0]],
        )

    def test_stopping_listening_initiates_transcription_and_enters_transcribing(self) -> None:
        """Requirement A & B: Stopping listening initiates STT and transitions state to TRANSCRIBING."""
        adapter = ControllableSTTAdapter(block_on_transcribe=True)
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        controller.request_activation()
        self.assertEqual(controller.state, SessionState.LISTENING)

        # Stop listening (second hotkey trigger)
        controller.request_activation()

        # Must transition immediately to TRANSCRIBING
        self.assertEqual(controller.state, SessionState.TRANSCRIBING)

        # Verify worker is executing
        self.assertTrue(adapter.transcribe_called.wait(timeout=2.0))

        # Cleanup
        adapter.gate.set()
        controller.dismiss()
        app.shutdown()

    def test_transcribe_executes_on_background_thread(self) -> None:
        """Requirement 3: Google transcribe() executes outside the Qt main thread."""
        main_thread_id = threading.get_ident()
        adapter = ControllableSTTAdapter(block_on_transcribe=False)
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        controller.request_activation()
        controller.stop_listening()

        self.assertTrue(adapter.transcribe_called.wait(timeout=2.0))
        self.assertIsNotNone(adapter.worker_thread_id)
        self.assertNotEqual(adapter.worker_thread_id, main_thread_id)

        # Allow Qt signal dispatching
        for _ in range(20):
            self.qapp.processEvents()
            if controller.state == SessionState.TRANSCRIBED:
                break
            time.sleep(0.01)

        self.assertEqual(controller.state, SessionState.TRANSCRIBED)

        # Cleanup
        controller.dismiss()
        app.shutdown()

    def test_successful_stt_populates_transcript_and_releases_raw_audio(self) -> None:
        """Requirement C, D, F: STT success populates TranscriptResult and releases raw audio."""
        adapter = ControllableSTTAdapter(
            fake_transcript="Explain the concept of limits.",
            confidence=0.97,
            block_on_transcribe=False,
        )
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        controller.request_activation()
        controller.stop_listening()

        for _ in range(20):
            self.qapp.processEvents()
            if controller.state == SessionState.TRANSCRIBED:
                break
            time.sleep(0.01)

        self.assertEqual(controller.state, SessionState.TRANSCRIBED)
        self.assertIsNotNone(controller.current_transcript)
        self.assertEqual(
            controller.current_transcript.transcript,
            "Explain the concept of limits.",
        )
        self.assertEqual(controller.current_transcript.language, "en-US")
        # Crucial Requirement F: raw audio reference is released!
        self.assertIsNone(controller.current_audio)

        # Cleanup
        controller.dismiss()
        app.shutdown()

    def test_transcript_is_visible_in_development_ui(self) -> None:
        """Requirement E: Transcript is visible in the desktop shell window."""
        adapter = ControllableSTTAdapter(
            fake_transcript="Why is the derivative zero at an extremum?",
            block_on_transcribe=False,
        )
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller
        window = DesktopShellWindow(session_controller=controller)

        controller.request_activation()
        controller.stop_listening()

        for _ in range(20):
            self.qapp.processEvents()
            if controller.state == SessionState.TRANSCRIBED:
                break
            time.sleep(0.01)

        self.assertEqual(controller.state, SessionState.TRANSCRIBED)
        self.assertFalse(window.audio_info_label.isHidden())
        self.assertIn("Why is the derivative zero", window.audio_info_label.text())
        self.assertIn("Transcript:", window.audio_info_label.text())

        # Cleanup
        controller.dismiss()
        window.close()
        app.shutdown()

    def test_escape_during_transcribing_returns_immediately_to_idle(self) -> None:
        """Requirement G: Escape during TRANSCRIBING cancels immediately to IDLE."""
        adapter = ControllableSTTAdapter(block_on_transcribe=True)
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        controller.request_activation()
        controller.stop_listening()

        self.assertEqual(controller.state, SessionState.TRANSCRIBING)
        self.assertTrue(adapter.transcribe_called.wait(timeout=2.0))

        # Press Escape -> dismiss()
        controller.dismiss()

        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_transcript)
        self.assertIsNone(controller.current_audio)

        # Unblock worker and let it finish
        adapter.gate.set()
        for _ in range(10):
            self.qapp.processEvents()
            time.sleep(0.01)

        # State must remain IDLE; late result was dropped
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_transcript)

        app.shutdown()

    def test_late_result_after_escape_is_ignored(self) -> None:
        """Requirement H: Late worker completion after Escape is completely dropped."""
        adapter = ControllableSTTAdapter(
            fake_transcript="Late question text",
            block_on_transcribe=True,
        )
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        controller.request_activation()
        token_a = controller.session_token
        controller.stop_listening()

        self.assertTrue(adapter.transcribe_called.wait(timeout=2.0))

        # Escape is pressed
        controller.dismiss()
        self.assertNotEqual(controller.session_token, token_a)
        self.assertEqual(controller.state, SessionState.IDLE)

        # Worker finishes late
        adapter.gate.set()
        for _ in range(10):
            self.qapp.processEvents()
            time.sleep(0.01)

        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_transcript)

        app.shutdown()

    def test_new_session_race_protection_against_late_result(self) -> None:
        """Requirement I / 14: Late result from Session A cannot disturb active Session B."""
        adapter = ControllableSTTAdapter(
            fake_transcript="Session A question",
            block_on_transcribe=True,
        )
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        # Session A begins
        controller.request_activation()
        controller.stop_listening()
        self.assertEqual(controller.state, SessionState.TRANSCRIBING)
        self.assertTrue(adapter.transcribe_called.wait(timeout=2.0))

        # User cancels Session A via Escape
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)

        # User begins Session B immediately
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.LISTENING)

        # Late result from Session A arrives while Session B is in LISTENING
        adapter.gate.set()
        for _ in range(10):
            self.qapp.processEvents()
            time.sleep(0.01)

        # Session B MUST remain untouched in LISTENING!
        self.assertEqual(controller.state, SessionState.LISTENING)
        self.assertIsNone(controller.current_transcript)

        # Cleanup
        controller.dismiss()
        app.shutdown()

    def test_stt_failure_shows_recoverable_error_and_remains_in_error_state(self) -> None:
        """Requirement J & 2: STT failure shows error, releases audio, and REMAINS in ERROR (not IDLE)."""
        adapter = ControllableSTTAdapter(
            error_to_raise=STTAuthenticationError("Application Default Credentials not found."),
            block_on_transcribe=False,
        )
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller
        window = DesktopShellWindow(session_controller=controller)

        controller.request_activation()
        controller.stop_listening()

        for _ in range(20):
            self.qapp.processEvents()
            if controller.state == SessionState.ERROR:
                break
            time.sleep(0.01)

        # Crucial Requirement 2: remains in ERROR, not immediately dismissed to IDLE
        self.assertEqual(controller.state, SessionState.ERROR)
        self.assertIsNotNone(controller.last_error_message)
        self.assertIn("Credentials not found", controller.last_error_message)
        self.assertIsNone(controller.current_audio)
        self.assertIsNone(controller.current_transcript)

        # UI shows error
        self.assertFalse(window.audio_info_label.isHidden())
        self.assertIn("Credentials not found", window.audio_info_label.text())

        # Escape recovers cleanly to IDLE
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)

        window.close()
        app.shutdown()

    def test_empty_transcript_shows_recoverable_error(self) -> None:
        """Requirement K: Empty transcript raises EmptyTranscriptError and shows error UI."""
        adapter = ControllableSTTAdapter(
            error_to_raise=EmptyTranscriptError("No recognizable speech was detected in the audio."),
            block_on_transcribe=False,
        )
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        controller.request_activation()
        controller.stop_listening()

        for _ in range(20):
            self.qapp.processEvents()
            if controller.state == SessionState.ERROR:
                break
            time.sleep(0.01)

        self.assertEqual(controller.state, SessionState.ERROR)
        self.assertIn("No recognizable speech", controller.last_error_message)

        # Cleanup
        controller.dismiss()
        app.shutdown()

    def test_new_session_clears_previous_transcript(self) -> None:
        """Requirement L: Starting a new session clears previous transcript."""
        adapter = ControllableSTTAdapter(
            fake_transcript="Previous question",
            block_on_transcribe=False,
        )
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        # Complete Session 1
        controller.request_activation()
        controller.stop_listening()

        for _ in range(20):
            self.qapp.processEvents()
            if controller.state == SessionState.TRANSCRIBED:
                break
            time.sleep(0.01)

        self.assertEqual(controller.state, SessionState.TRANSCRIBED)
        self.assertIsNotNone(controller.current_transcript)

        # Start Session 2 (auto-dismisses prior session)
        controller.request_activation()

        self.assertEqual(controller.state, SessionState.LISTENING)
        self.assertIsNone(controller.current_transcript)

        # Cleanup
        controller.dismiss()
        app.shutdown()

    def test_escape_from_transcribed_clears_transcript_and_returns_to_idle(self) -> None:
        """Requirement M: Escape from TRANSCRIBED state clears transcript and resets to IDLE."""
        adapter = ControllableSTTAdapter(fake_transcript="Some question", block_on_transcribe=False)
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        controller.request_activation()
        controller.stop_listening()

        for _ in range(20):
            self.qapp.processEvents()
            if controller.state == SessionState.TRANSCRIBED:
                break
            time.sleep(0.01)

        self.assertEqual(controller.state, SessionState.TRANSCRIBED)

        # Press Escape
        controller.dismiss()

        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_transcript)

        app.shutdown()

    def test_shutdown_during_transcription_is_safe_and_non_blocking(self) -> None:
        """Requirement N / 20: Application shutdown during TRANSCRIBING does not hang."""
        adapter = ControllableSTTAdapter(block_on_transcribe=True)
        app = self._create_app(stt_adapter=adapter)
        controller = app.session_controller

        controller.request_activation()
        controller.stop_listening()
        self.assertEqual(controller.state, SessionState.TRANSCRIBING)
        self.assertTrue(adapter.transcribe_called.wait(timeout=2.0))

        # Shutdown app while worker is still blocked in Google call
        shutdown_start = time.time()
        app.shutdown()
        shutdown_duration = time.time() - shutdown_start

        # Must return immediately without hanging
        self.assertLess(shutdown_duration, 1.0)
        self.assertEqual(controller.state, SessionState.IDLE)

        # Worker unblocks later
        adapter.gate.set()
        for _ in range(10):
            self.qapp.processEvents()
            time.sleep(0.01)

        # Controller remained cleanly in IDLE
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_transcript)


if __name__ == "__main__":
    unittest.main()
