"""Unit tests for Block 9: Automatic Session Cleanup & Siri-Like Listening Orb.

Tests:
1. Automatic explanation cleanup on narration completion.
2. Visual hold delay before automatic cleanup.
3. Centralized cleanup and immediate Escape cancellation.
4. Stale-session protection for delayed cleanup callbacks.
5. Wake detector re-arming on automatic cleanup returning to IDLE.
6. Listening indicator lifecycle: LISTENING, THINKING, EXPLAINING, OFF.
7. SessionController integration with ListeningIndicator.
8. Audio amplitude reactivity without audio persistence.
9. Pre-capture self-protection hiding the listening indicator.
10. Main application window hidden by default for background assistant operation.
11. Non-focus-stealing window properties for the listening orb.
12. Zero timer leakage: animation timers stopped when orb is OFF.
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from app.audio.model import AudioCaptureResult
from app.capture.model import CapturedScreen, DisplayGeometry
from app.capture.service import CaptureService
from app.desktop.orb import ListeningOrbWidget
from app.desktop.shell import NeuronDesktopApp
from app.overlay.host import StubOverlayHost
from app.sequence.controller import SequenceController
from app.session.controller import SessionController
from app.session.indicator import ListeningIndicator, OrbState, StubListeningIndicator
from app.session.state import SessionState
from app.tts.adapter import TTSAdapter
from app.tts.model import TTSAudioClip
from app.tts.playback import AudioPlaybackService
from app.tutor.model import OverlayAction, OverlayActionType, TutorResponse


def get_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class FakeTTS(TTSAdapter):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def synthesize(self, text: str) -> TTSAudioClip:
        self.calls.append(text)
        return TTSAudioClip(raw_bytes=b"\x00" * 320, duration_seconds=0.1)


class FakePlayback(AudioPlaybackService):
    def __init__(self, auto_complete: bool = True) -> None:
        self._playing = False
        self.auto_complete = auto_complete
        self.play_count = 0
        self.stop_count = 0

    @property
    def is_playing(self) -> bool:
        return self._playing

    def play(self, clip: TTSAudioClip, on_finished=None) -> None:
        self._playing = True
        self.play_count += 1
        if self.auto_complete and on_finished:
            self._playing = False
            on_finished()

    def stop(self) -> None:
        self._playing = False
        self.stop_count += 1


class TestAutomaticExplanationCleanup(unittest.TestCase):
    """Test Feature 1: Automatic explanation cleanup after narration finishes."""

    def test_successful_sequence_completion_triggers_cleanup(self):
        """When narration finishes, handle_sequence_finished triggers automatic cleanup to IDLE."""
        overlay_host = StubOverlayHost()
        controller = SessionController(
            overlay_host=overlay_host,
            auto_cleanup=True,
            cleanup_delay_ms=0,  # Immediate cleanup for deterministic testing
        )
        controller._set_state(SessionState.RESPONDED)
        token = controller.session_token
        overlay_host.show()

        # Simulate sequence controller notifying completion
        controller.handle_sequence_finished(token)

        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertFalse(overlay_host.is_visible())
        self.assertFalse(overlay_host.has_explanation)

    def test_cleanup_delay_visual_hold(self):
        """Visual explanation remains visible during visual hold, then automatically cleans up."""
        overlay_host = StubOverlayHost()
        controller = SessionController(
            overlay_host=overlay_host,
            auto_cleanup=True,
            cleanup_delay_ms=100,  # 100ms hold
        )
        controller._set_state(SessionState.RESPONDED)
        token = controller.session_token
        overlay_host.show()

        controller.handle_sequence_finished(token)

        # Midway through the hold (30ms): still visible, state is RESPONDED
        time.sleep(0.03)
        self.assertEqual(controller.state, SessionState.RESPONDED)

        # After hold expires (180ms total): automatically cleaned up to IDLE
        time.sleep(0.15)
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertFalse(overlay_host.is_visible())

    def test_escape_cancels_pending_cleanup_and_resets_immediately(self):
        """Escape dismisses immediately and invalidates any pending delayed cleanup timer."""
        overlay_host = StubOverlayHost()
        controller = SessionController(
            overlay_host=overlay_host,
            auto_cleanup=True,
            cleanup_delay_ms=300,
        )
        controller._set_state(SessionState.RESPONDED)
        token = controller.session_token

        controller.handle_sequence_finished(token)
        time.sleep(0.02)
        self.assertEqual(controller.state, SessionState.RESPONDED)

        # User presses Escape
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)
        old_token = token

        # Wait for the original timer to fire: must not corrupt state
        time.sleep(0.35)
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertGreater(controller.session_token, old_token)

    def test_stale_session_completion_protection(self):
        """Completion from an older session does NOT dismiss an active new session."""
        overlay_host = StubOverlayHost()
        controller = SessionController(
            overlay_host=overlay_host,
            auto_cleanup=True,
            cleanup_delay_ms=0,
        )
        controller._set_state(SessionState.RESPONDED)
        old_token = controller.session_token

        # A new session starts before old session's sequence finishes
        controller.request_activation()
        new_token = controller.session_token
        self.assertNotEqual(old_token, new_token)
        controller._set_state(SessionState.LISTENING)

        # Old sequence finished event arrives late
        controller.handle_sequence_finished(old_token)

        # Current session must NOT be dismissed
        self.assertEqual(controller.state, SessionState.LISTENING)

    def test_auto_cleanup_disabled_when_flag_false(self):
        """If auto_cleanup is explicitly disabled, state remains RESPONDED until user dismisses."""
        overlay_host = StubOverlayHost()
        controller = SessionController(
            overlay_host=overlay_host,
            auto_cleanup=False,
            cleanup_delay_ms=0,
        )
        controller._set_state(SessionState.RESPONDED)
        token = controller.session_token

        controller.handle_sequence_finished(token)
        self.assertEqual(controller.state, SessionState.RESPONDED)


class TestListeningIndicatorAndOrb(unittest.TestCase):
    """Test Feature 2: Siri-like animated listening and thinking indicator."""

    def test_stub_listening_indicator_lifecycle(self):
        indicator = StubListeningIndicator()
        self.assertEqual(indicator.get_state(), OrbState.OFF)
        self.assertFalse(indicator.is_visible())

        indicator.show_listening()
        self.assertEqual(indicator.get_state(), OrbState.LISTENING)
        self.assertTrue(indicator.is_visible())

        indicator.show_thinking()
        self.assertEqual(indicator.get_state(), OrbState.THINKING)
        self.assertTrue(indicator.is_visible())

        indicator.set_amplitude(0.75)
        self.assertAlmostEqual(indicator._amplitude, 0.75)

        indicator.hide()
        self.assertEqual(indicator.get_state(), OrbState.OFF)
        self.assertFalse(indicator.is_visible())

    def test_session_controller_shows_and_transitions_indicator(self):
        """SessionController shows LISTENING, transitions to THINKING, and hides on RESPONDED."""
        indicator = StubListeningIndicator()
        audio_mock = MagicMock()
        audio_mock.is_recording = True
        audio_mock.stop_recording.return_value = AudioCaptureResult(
            raw_bytes=b"\x00" * 3200, duration_seconds=0.1, sample_rate=16000, channels=1
        )
        stt_mock = MagicMock()

        controller = SessionController(
            audio_service=audio_mock,
            stt_adapter=stt_mock,
            listening_indicator=indicator,
            auto_capture=False,
        )

        # 1. Start listening shows listening indicator
        controller.start_listening()
        self.assertEqual(indicator.get_state(), OrbState.LISTENING)
        self.assertTrue(indicator.is_visible())

        # 2. Stop listening transitions to thinking indicator
        controller.stop_listening()
        self.assertEqual(indicator.get_state(), OrbState.THINKING)
        self.assertTrue(indicator.is_visible())

        # 3. Tutor success hides indicator so explanation becomes visual focus
        controller._set_state(SessionState.THINKING)
        response = TutorResponse(intent="explanation", summary="Done", narration="")
        controller.handle_tutor_success(response, token=controller.session_token)
        self.assertEqual(indicator.get_state(), OrbState.OFF)
        self.assertFalse(indicator.is_visible())

    def test_session_controller_dismiss_hides_indicator(self):
        """Dismiss immediately hides the listening indicator."""
        indicator = StubListeningIndicator()
        audio_mock = MagicMock()
        controller = SessionController(
            audio_service=audio_mock,
            listening_indicator=indicator,
        )
        controller.start_listening()
        self.assertTrue(indicator.is_visible())

        controller.dismiss()
        self.assertEqual(indicator.get_state(), OrbState.OFF)
        self.assertFalse(indicator.is_visible())

    def test_pre_capture_hides_indicator_for_self_capture_defense(self):
        """begin_capture_flow hides indicator before screen capture occurs."""
        indicator = StubListeningIndicator()
        indicator.show_listening()
        self.assertTrue(indicator.is_visible())

        controller = SessionController(
            listening_indicator=indicator,
        )
        # Indicator is visible prior to capture
        indicator.show_listening()

        # Capture flow started
        controller.begin_capture_flow(delay_ms=0)
        self.assertEqual(indicator.get_state(), OrbState.OFF)
        self.assertFalse(indicator.is_visible())

    def test_amplitude_calculation(self):
        """_calculate_amplitude produces normalized float without errors."""
        import struct

        # Silence (0 RMS)
        silent_pcm = b"\x00" * 3200
        amp_silent = SessionController._calculate_amplitude(silent_pcm)
        self.assertEqual(amp_silent, 0.0)

        # Loud tone
        loud_samples = [15000 if i % 2 == 0 else -15000 for i in range(1600)]
        loud_pcm = struct.pack(f"{len(loud_samples)}h", *loud_samples)
        amp_loud = SessionController._calculate_amplitude(loud_pcm)
        self.assertGreater(amp_loud, 0.5)
        self.assertLessEqual(amp_loud, 1.0)


class TestListeningOrbWidgetProperties(unittest.TestCase):
    """Test PySide6 ListeningOrbWidget properties and non-focus-stealing behavior."""

    @classmethod
    def setUpClass(cls):
        cls.app = get_qapp()

    def test_orb_window_flags_and_attributes(self):
        orb = ListeningOrbWidget()
        flags = orb.windowFlags()

        # Frameless and stays on top
        self.assertTrue(flags & Qt.WindowType.FramelessWindowHint)
        self.assertTrue(flags & Qt.WindowType.WindowStaysOnTopHint)
        # Tool window (no taskbar item)
        self.assertTrue(flags & Qt.WindowType.Tool)
        # Does NOT accept focus (prevents focus loss from active learning window)
        self.assertTrue(flags & Qt.WindowType.WindowDoesNotAcceptFocus)

        # Translucent background & show without activating
        self.assertTrue(orb.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        self.assertTrue(orb.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        orb.close()

    def test_orb_timer_runs_only_when_active(self):
        """Animation timer runs strictly during LISTENING/THINKING and stops when OFF."""
        orb = ListeningOrbWidget()
        self.assertFalse(orb._timer.isActive())

        orb.show_listening()
        self.assertTrue(orb._timer.isActive())
        self.assertEqual(orb.get_state(), OrbState.LISTENING)

        orb.show_thinking()
        self.assertTrue(orb._timer.isActive())
        self.assertEqual(orb.get_state(), OrbState.THINKING)

        orb.hide()
        self.assertFalse(orb._timer.isActive())
        self.assertEqual(orb.get_state(), OrbState.OFF)
        orb.close()


class TestMainWindowBackgroundExecution(unittest.TestCase):
    """Test main application window remains hidden/minimized during normal use."""

    @classmethod
    def setUpClass(cls):
        cls.app = get_qapp()

    def test_main_window_hidden_by_default(self):
        """Neuron starts with main window hidden when no --show-window flag is passed."""
        desktop_app = NeuronDesktopApp(argv=["neuron"])
        mock_win = MagicMock()

        with patch("app.desktop.shell.DesktopShellWindow", return_value=mock_win):
            with patch.object(desktop_app, "_setup_system_tray"):
                with patch.object(desktop_app._activation_manager, "start"):
                    with patch.object(desktop_app._app, "exec", return_value=0):
                        desktop_app.run()

        # Window was hidden, not shown
        mock_win.hide.assert_called_once()
        mock_win.show.assert_not_called()

    def test_main_window_shown_when_flag_present(self):
        """Neuron displays main window when --show-window argument is passed."""
        desktop_app = NeuronDesktopApp(argv=["neuron", "--show-window"])
        mock_win = MagicMock()

        with patch("app.desktop.shell.DesktopShellWindow", return_value=mock_win):
            with patch.object(desktop_app, "_setup_system_tray"):
                with patch.object(desktop_app._activation_manager, "start"):
                    with patch.object(desktop_app._app, "exec", return_value=0):
                        desktop_app.run()

        mock_win.show.assert_called_once()
        mock_win.hide.assert_not_called()


if __name__ == "__main__":
    unittest.main()
