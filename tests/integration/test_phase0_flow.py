"""Integration test for complete Phase 0 runtime flow."""

import sys
import unittest

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtCore import Qt

from app.desktop.shell import NeuronDesktopApp
from app.session.state import SessionState


class TestPhase0Flow(unittest.TestCase):
    """End-to-end integration test of the Phase 0 desktop shell, capture, and overlay flow."""

    def test_full_phase0_flow_and_escape_dismissal(self):
        app = NeuronDesktopApp(argv=[sys.argv[0]])
        qapp = app.initialize_qapplication()

        flow_steps = []

        def step1_verify_initial():
            flow_steps.append(("initial", app.session_controller.state))
            # Trigger activation
            app.session_controller.request_activation()
            QTimer.singleShot(150, step2_verify_overlay_shown)

        def step2_verify_overlay_shown():
            flow_steps.append(("selecting", app.session_controller.state))
            # Verify overlay is active
            self.assertTrue(app.session_controller.overlay_host.is_visible())
            self.assertIsNotNone(app.session_controller.current_capture)

            # Simulate mouse drag on overlay: from (100, 100) to (400, 300)
            overlay = app.session_controller.overlay_host._overlay
            overlay._start_pos = QPoint(100, 100)
            overlay._current_pos = QPoint(400, 300)
            overlay._is_dragging = True

            # Trigger mouse release to finalize selection
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtCore import QEvent, QPointF

            release_event = QMouseEvent(
                QEvent.Type.MouseButtonRelease,
                QPointF(400, 300),
                QPointF(400, 300),
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )
            overlay.mouseReleaseEvent(release_event)

            QTimer.singleShot(100, step3_verify_region_selected)

        def step3_verify_region_selected():
            flow_steps.append(("selected", app.session_controller.state))
            selected = app.session_controller.selected_region
            self.assertIsNotNone(selected)
            self.assertEqual(selected.width, 300)
            self.assertEqual(selected.height, 200)

            # Test Escape dismissal on overlay
            overlay = app.session_controller.overlay_host._overlay
            esc_event = QKeyEvent(
                QKeyEvent.Type.KeyPress,
                Qt.Key.Key_Escape,
                Qt.KeyboardModifier.NoModifier,
            )
            overlay.keyPressEvent(esc_event)

            QTimer.singleShot(100, step4_verify_idle_after_escape)

        def step4_verify_idle_after_escape():
            flow_steps.append(("after_escape", app.session_controller.state))
            self.assertFalse(app.session_controller.overlay_host.is_visible())
            self.assertIsNone(app.session_controller.selected_region)
            self.assertIsNone(app.session_controller.current_capture)

            # Clean exit
            qapp.quit()

        QTimer.singleShot(100, step1_verify_initial)
        exit_code = app.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            flow_steps,
            [
                ("initial", SessionState.IDLE),
                ("selecting", SessionState.SELECTING),
                ("selected", SessionState.SELECTED),
                ("after_escape", SessionState.IDLE),
            ],
        )


if __name__ == "__main__":
    unittest.main()
