"""Unit regression tests for Neuron self-capture bug fix.

Verifies:
1. Activation hides/excludes Neuron window before capture
2. Capture happens while Neuron shell is hidden
3. Shell is restored after successful capture
4. Shell is restored after capture failure
5. LISTENING begins only after capture completes
6. Exactly one capture occurs per activation
7. Escape during pending/delayed capture cancels safely
8. Stale delayed capture from previous session is ignored
9. New session cannot receive previous session screenshot
10. Preserves window maximized/normal layout on restore
"""

import sys
import unittest
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication

from app.audio.model import AudioCaptureResult
from app.audio.service import AudioCaptureService
from app.capture.model import CapturedScreen, DisplayGeometry
from app.capture.service import CaptureService
from app.session.controller import SessionController
from app.session.state import SessionState


class TestPreCaptureWindowExclusion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qapp = QApplication.instance() or QApplication([sys.argv[0]])

    def setUp(self):
        self.geom = DisplayGeometry(x=0, y=0, width=1920, height=1080)
        self.sample_screen = CapturedScreen(image_data=b"pixels", geometry=self.geom)
        self.mock_capture = MagicMock(spec=CaptureService)
        self.mock_capture.capture_current_screen.return_value = self.sample_screen

        self.mock_window = MagicMock()
        self.mock_window.isVisible.return_value = True
        self.mock_window.isMaximized.return_value = False

    def test_1_activation_hides_window_before_capture(self):
        """1. Activation hides/excludes Neuron window before capture."""
        events = []
        self.mock_window.hide.side_effect = lambda: events.append("hide")
        self.mock_capture.capture_current_screen.side_effect = (
            lambda: (events.append("capture"), self.sample_screen)[1]
        )
        self.mock_window.showNormal.side_effect = lambda: events.append("restore")

        controller = SessionController(
            capture_service=self.mock_capture,
            desktop_window=self.mock_window,
            capture_delay_ms=0,
            auto_capture=True,
        )

        controller.request_activation()

        self.assertIn("hide", events)
        self.assertIn("capture", events)
        self.assertLess(events.index("hide"), events.index("capture"))

    def test_2_capture_happens_while_neuron_shell_is_hidden(self):
        """2. Capture happens while Neuron shell is hidden."""
        is_hidden_during_capture = []

        def capture_hook():
            # Verify window.hide() has been called and window.show* has NOT yet been called
            hidden = self.mock_window.hide.called and not self.mock_window.showNormal.called
            is_hidden_during_capture.append(hidden)
            return self.sample_screen

        self.mock_capture.capture_current_screen.side_effect = capture_hook

        controller = SessionController(
            capture_service=self.mock_capture,
            desktop_window=self.mock_window,
            capture_delay_ms=0,
            auto_capture=True,
        )

        controller.request_activation()
        self.assertEqual(is_hidden_during_capture, [True])

    def test_3_shell_is_restored_after_successful_capture(self):
        """3. Shell is restored after successful capture."""
        controller = SessionController(
            capture_service=self.mock_capture,
            desktop_window=self.mock_window,
            capture_delay_ms=0,
            auto_capture=True,
        )

        controller.request_activation()
        self.assertTrue(self.mock_window.showNormal.called)
        self.assertEqual(controller.current_capture, self.sample_screen)
        self.assertEqual(controller.state, SessionState.SELECTING)

    def test_4_shell_is_restored_after_capture_failure(self):
        """4. Shell is restored after capture failure."""
        self.mock_capture.capture_current_screen.side_effect = RuntimeError("Hardware capture fault")

        controller = SessionController(
            capture_service=self.mock_capture,
            desktop_window=self.mock_window,
            capture_delay_ms=0,
            auto_capture=True,
        )

        controller.request_activation()

        # Window MUST be restored despite exception
        self.assertTrue(self.mock_window.showNormal.called)
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_capture)

    def test_5_listening_begins_only_after_capture_completes(self):
        """5. LISTENING begins only after capture completes."""
        mock_audio = MagicMock(spec=AudioCaptureService)
        mock_audio.is_recording = False

        events = []
        self.mock_window.hide.side_effect = lambda: events.append("hide")
        self.mock_capture.capture_current_screen.side_effect = (
            lambda: (events.append("capture"), self.sample_screen)[1]
        )
        self.mock_window.showNormal.side_effect = lambda: events.append("restore")
        mock_audio.start_recording.side_effect = lambda: events.append("start_audio")

        controller = SessionController(
            capture_service=self.mock_capture,
            audio_service=mock_audio,
            desktop_window=self.mock_window,
            capture_delay_ms=0,
            auto_capture=True,
        )

        controller.request_activation()

        self.assertEqual(events, ["hide", "capture", "restore", "start_audio"])
        self.assertEqual(controller.state, SessionState.LISTENING)

    def test_6_exactly_one_capture_occurs_per_activation(self):
        """6. Exactly one capture occurs per activation."""
        mock_audio = MagicMock(spec=AudioCaptureService)
        mock_audio.is_recording = False

        def fake_start():
            mock_audio.is_recording = True

        def fake_stop():
            mock_audio.is_recording = False
            return AudioCaptureResult(
                raw_bytes=b"\x00" * 3200,
                sample_rate=16000,
                channels=1,
                sample_width=2,
                duration_seconds=0.1,
            )

        mock_audio.start_recording.side_effect = fake_start
        mock_audio.stop_recording.side_effect = fake_stop

        controller = SessionController(
            capture_service=self.mock_capture,
            audio_service=mock_audio,
            desktop_window=self.mock_window,
            capture_delay_ms=0,
            auto_capture=True,
        )

        # 1. First activation: captures screen once and enters LISTENING
        controller.request_activation()
        self.assertEqual(self.mock_capture.capture_current_screen.call_count, 1)
        self.assertEqual(controller.state, SessionState.LISTENING)

        # 2. Second activation while LISTENING: stops recording, does NOT capture again
        controller.request_activation()
        self.assertEqual(self.mock_capture.capture_current_screen.call_count, 1)
        self.assertEqual(controller.state, SessionState.VOICE_CAPTURED)

    def test_7_escape_during_pending_capture_cancels_safely(self):
        """7. Escape during pending/delayed capture cancels safely."""
        controller = SessionController(
            capture_service=self.mock_capture,
            desktop_window=self.mock_window,
            capture_delay_ms=10000,
            auto_capture=True,
        )

        controller.request_activation()
        old_token = controller.session_token
        self.assertEqual(controller.state, SessionState.CAPTURING)
        self.assertTrue(self.mock_window.hide.called)

        # User presses Escape (dismiss) while capture is pending
        controller.dismiss()

        # Immediately returns to IDLE and restores window
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertTrue(self.mock_window.showNormal.called)

        # Now simulate the delayed timer firing late for the old token
        controller._execute_capture(old_token)

        # Stale execution is dropped; no capture took place
        self.mock_capture.capture_current_screen.assert_not_called()
        self.assertEqual(controller.state, SessionState.IDLE)

    def test_8_stale_delayed_capture_from_previous_session_is_ignored(self):
        """8. Stale delayed capture from previous session is ignored."""
        controller = SessionController(
            capture_service=self.mock_capture,
            desktop_window=self.mock_window,
            capture_delay_ms=10000,
            auto_capture=True,
        )

        controller.request_activation()
        token_1 = controller.session_token

        # Session dismissed -> token increments
        controller.dismiss()
        self.assertNotEqual(token_1, controller.session_token)

        # Attempt to run capture for token_1
        controller._execute_capture(token_1)

        self.mock_capture.capture_current_screen.assert_not_called()
        self.assertIsNone(controller.current_capture)
        self.assertEqual(controller.state, SessionState.IDLE)

    def test_9_new_session_cannot_receive_previous_session_screenshot(self):
        """9. New session cannot receive previous session screenshot."""
        screen_1 = CapturedScreen(image_data=b"screen_1", geometry=self.geom)
        screen_2 = CapturedScreen(image_data=b"screen_2", geometry=self.geom)

        controller = SessionController(
            capture_service=self.mock_capture,
            desktop_window=self.mock_window,
            capture_delay_ms=0,
            auto_capture=True,
        )

        # Session 1 starts and gets cancelled
        controller.request_activation()
        token_1 = controller.session_token
        controller.dismiss()

        # Session 2 starts and captures screen_2
        self.mock_capture.capture_current_screen.return_value = screen_2
        controller.request_activation()
        token_2 = controller.session_token
        self.assertEqual(controller.current_capture, screen_2)

        # Stale capture 1 finishes late
        self.mock_capture.capture_current_screen.return_value = screen_1
        controller._execute_capture(token_1)

        # Must still have screen_2 from Session 2
        self.assertEqual(controller.current_capture, screen_2)
        self.assertEqual(controller.session_token, token_2)

    def test_10_preserves_maximized_window_state_on_restore(self):
        """Preserves maximized state when restoring the window."""
        self.mock_window.isMaximized.return_value = True

        controller = SessionController(
            capture_service=self.mock_capture,
            desktop_window=self.mock_window,
            capture_delay_ms=0,
            auto_capture=True,
        )

        controller.request_activation()

        self.assertTrue(self.mock_window.showMaximized.called)
        self.assertFalse(self.mock_window.showNormal.called)
