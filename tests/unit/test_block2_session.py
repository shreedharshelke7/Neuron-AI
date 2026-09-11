"""Unit tests for Block 2 Step 4: Session + LISTENING UI Integration."""

from __future__ import annotations

import sys
import unittest
from typing import Any
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from app.audio.errors import AudioCaptureError, EmptyAudioError, MicrophoneUnavailableError
from app.audio.model import AudioCaptureResult
from app.audio.service import AudioCaptureService, FakeAudioCaptureService
from app.capture.model import CapturedScreen, DisplayGeometry, SelectedRegion
from app.capture.service import StubCaptureService
from app.desktop.shell import NeuronDesktopApp
from app.desktop.window import DesktopShellWindow
from app.session.controller import SessionController
from app.session.state import SessionState


class TestBlock2SessionIntegration(unittest.TestCase):
    """Test suite covering Block 2 Step 4 session lifecycle and listening integration."""

    @classmethod
    def setUpClass(cls) -> None:
        # Ensure single QApplication exists for GUI component tests
        cls.qapp = QApplication.instance() or QApplication([sys.argv[0]])

    def setUp(self) -> None:
        self.fake_audio = FakeAudioCaptureService(fake_duration_seconds=2.0)
        self.default_geom = DisplayGeometry(width=1920, height=1080)
        self.default_screen = CapturedScreen(geometry=self.default_geom)

    def _create_controller(self, **kwargs: Any) -> SessionController:
        """Create a session controller with valid screen geometry by default."""
        defaults = {
            "audio_service": self.fake_audio,
            "capture_service": StubCaptureService(stub_result=self.default_screen),
            "auto_capture": True,
        }
        defaults.update(kwargs)
        return SessionController(**defaults)

    def test_initialization_does_not_start_microphone(self) -> None:
        """Requirement A: Controller initialization must NOT start microphone."""
        controller = self._create_controller()

        self.assertFalse(self.fake_audio.is_recording)
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_audio)

    def test_activation_reaches_listening_and_starts_recording_once(self) -> None:
        """Requirement B: Explicit activation enters LISTENING and calls start exactly once."""
        mock_audio = MagicMock(spec=AudioCaptureService)
        mock_audio.is_recording = False

        def fake_start() -> None:
            mock_audio.is_recording = True

        mock_audio.start_recording.side_effect = fake_start

        controller = self._create_controller(audio_service=mock_audio)

        controller.request_activation()

        mock_audio.start_recording.assert_called_once()
        self.assertEqual(controller.state, SessionState.LISTENING)

        # Cleanup
        controller.dismiss()

    def test_listening_feedback_becomes_visible_in_window(self) -> None:
        """Requirement C: LISTENING feedback becomes visible in the desktop shell window."""
        controller = self._create_controller(auto_capture=False)
        window = DesktopShellWindow(session_controller=controller)

        # Initially IDLE: label should be hidden
        self.assertTrue(window.audio_info_label.isHidden())
        self.assertFalse(window.finish_button.isEnabled())

        # Activate
        controller.request_activation()

        self.assertEqual(controller.state, SessionState.LISTENING)
        self.assertFalse(window.audio_info_label.isHidden())
        self.assertIn("listening", window.audio_info_label.text().lower())
        self.assertTrue(window.finish_button.isEnabled())

        # Cleanup
        controller.dismiss()
        window.close()

    def test_deterministic_stop_via_second_hotkey(self) -> None:
        """Requirement D: Second activation hotkey while LISTENING stops recording."""
        controller = self._create_controller()

        # 1st activation: start listening
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.LISTENING)
        self.assertTrue(self.fake_audio.is_recording)

        # 2nd activation: stop listening
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.VOICE_CAPTURED)
        self.assertFalse(self.fake_audio.is_recording)

        self.assertIsNotNone(controller.current_audio)
        self.assertIsInstance(controller.current_audio, AudioCaptureResult)
        self.assertEqual(controller.current_audio.duration_seconds, 2.0)

    def test_deterministic_stop_via_finish_recording_button(self) -> None:
        """Requirement D2: UI finish button stops recording and presents safe metadata."""
        controller = self._create_controller(auto_capture=False)
        window = DesktopShellWindow(session_controller=controller)

        controller.request_activation()
        self.assertTrue(window.finish_button.isEnabled())

        # Click finish button
        window.finish_button.click()

        self.assertEqual(controller.state, SessionState.VOICE_CAPTURED)
        self.assertFalse(window.finish_button.isEnabled())
        self.assertFalse(window.audio_info_label.isHidden())
        self.assertIn("Voice captured: 2.00s", window.audio_info_label.text())

        # Cleanup
        controller.dismiss()
        window.close()

    def test_escape_while_listening_cancels_and_restores_idle(self) -> None:
        """Requirement E: Escape calls cancel(), does NOT call stop(), clears audio, and restores IDLE."""
        mock_audio = MagicMock(spec=AudioCaptureService)
        mock_audio.is_recording = False

        def fake_start() -> None:
            mock_audio.is_recording = True

        def fake_cancel() -> None:
            mock_audio.is_recording = False

        mock_audio.start_recording.side_effect = fake_start
        mock_audio.cancel_recording.side_effect = fake_cancel

        controller = self._create_controller(audio_service=mock_audio)

        controller.request_activation()
        self.assertEqual(controller.state, SessionState.LISTENING)

        # Escape triggers dismiss()
        controller.dismiss()

        mock_audio.cancel_recording.assert_called_once()
        mock_audio.stop_recording.assert_not_called()
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_audio)

    def test_repeated_escape_is_safe(self) -> None:
        """Requirement F: Repeated Escape calls do not crash or corrupt state."""
        controller = self._create_controller()

        controller.request_activation()
        self.assertEqual(controller.state, SessionState.LISTENING)

        controller.dismiss()
        controller.dismiss()
        controller.dismiss()

        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertFalse(self.fake_audio.is_recording)

    def test_microphone_start_failure_handles_gracefully(self) -> None:
        """Requirement G: Microphone start failure does not crash; shows error, resets to usable IDLE."""
        failing_audio = MagicMock(spec=AudioCaptureService)
        failing_audio.start_recording.side_effect = MicrophoneUnavailableError(
            "Microphone device busy or unplugged"
        )
        failing_audio.is_recording = False

        controller = self._create_controller(audio_service=failing_audio)

        # Must not raise unhandled exception
        controller.request_activation()

        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNotNone(controller.last_error_message)
        self.assertIn("busy or unplugged", controller.last_error_message)

    def test_microphone_stop_failure_handles_gracefully(self) -> None:
        """Requirement H: Stop failure (e.g. EmptyAudioError) does not crash and cleans resources."""
        failing_audio = MagicMock(spec=AudioCaptureService)
        failing_audio.is_recording = True
        failing_audio.stop_recording.side_effect = EmptyAudioError("No audio captured")

        controller = self._create_controller(audio_service=failing_audio, auto_capture=False)
        controller._state = SessionState.LISTENING

        result = controller.stop_listening()

        self.assertIsNone(result)
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_audio)
        self.assertIsNotNone(controller.last_error_message)
        self.assertIn("No audio captured", controller.last_error_message)

    def test_application_shutdown_during_listening_cancels_audio(self) -> None:
        """Requirement I: Application shutdown while LISTENING cancels the audio stream."""
        mock_audio = MagicMock(spec=AudioCaptureService)
        mock_audio.is_recording = False

        def fake_start() -> None:
            mock_audio.is_recording = True

        def fake_cancel() -> None:
            mock_audio.is_recording = False

        mock_audio.start_recording.side_effect = fake_start
        mock_audio.cancel_recording.side_effect = fake_cancel

        controller = self._create_controller(audio_service=mock_audio, auto_capture=False)
        app = NeuronDesktopApp(session_controller=controller, argv=[sys.argv[0]])

        controller.request_activation()
        self.assertEqual(controller.state, SessionState.LISTENING)

        # Trigger application shutdown
        app.shutdown()

        mock_audio.cancel_recording.assert_called_once()
        self.assertEqual(controller.state, SessionState.IDLE)

    def test_new_session_does_not_reuse_previous_audio(self) -> None:
        """Requirement J: Starting a new session clears previous session audio."""
        controller = self._create_controller(auto_capture=False)

        # Session 1
        controller.request_activation()
        res1 = controller.stop_listening()
        self.assertEqual(controller.current_audio, res1)

        # Session 2 activation begins (auto-dismisses prior session)
        controller.request_activation()
        self.assertIsNone(controller.current_audio)
        self.assertEqual(controller.state, SessionState.LISTENING)

        # Cleanup
        controller.dismiss()

    def test_region_selection_during_listening_preserves_recording(self) -> None:
        """User dragging a region while LISTENING stores geometry without interrupting recording."""
        controller = self._create_controller(auto_capture=False)
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.LISTENING)

        geom = DisplayGeometry(width=1920, height=1080)
        region = SelectedRegion(x=50, y=50, width=200, height=100, display_geometry=geom)

        controller.on_region_selected(region)

        self.assertEqual(controller.selected_region, region)
        # State remains LISTENING because voice recording is ongoing
        self.assertEqual(controller.state, SessionState.LISTENING)
        self.assertTrue(self.fake_audio.is_recording)

        # Finish recording
        res = controller.stop_listening()
        self.assertEqual(controller.state, SessionState.VOICE_CAPTURED)
        self.assertIsNotNone(res)
        self.assertEqual(controller.selected_region, region)


if __name__ == "__main__":
    unittest.main()
