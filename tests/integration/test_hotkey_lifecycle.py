"""Integration test for local and global hotkey lifecycle and UI state sync."""

import sys
import unittest

from PySide6.QtCore import QTimer

from app.desktop.shell import NeuronDesktopApp
from app.session.controller import SessionController
from app.session.state import SessionState


class TestHotkeyIntegration(unittest.TestCase):
    """End-to-end integration test verifying hotkey and desktop shell state flow."""

    def test_hotkey_and_ui_state_lifecycle(self):
        controller = SessionController(auto_capture=False)
        app = NeuronDesktopApp(session_controller=controller, argv=[sys.argv[0]])
        qapp = app.initialize_qapplication()

        test_log = []

        def run_sequence():
            # 1. Verify initial IDLE state
            test_log.append(("initial", app.session_controller.state))

            # 2. Simulate global hotkey reception via message queue
            if app.activation_manager._global_backend is not None:
                thread_id = app.activation_manager._global_backend._thread_id
                if thread_id and sys.platform == "win32":
                    import ctypes

                    ctypes.windll.user32.PostThreadMessageW(
                        thread_id, 0x0312, 1, 0
                    )

            # Wait 100ms for hotkey processing
            QTimer.singleShot(100, step2_verify_hotkey_activated)

        def step2_verify_hotkey_activated():
            # 2. Verify ACTIVATED state from global hotkey
            test_log.append(("after_hotkey", app.session_controller.state))

            # 3. Test Reset button
            app._window.reset_button.click()
            test_log.append(("after_reset", app.session_controller.state))

            # Wait past debounce window (300ms) before triggering local shortcut
            QTimer.singleShot(350, step3_test_local_shortcut)

        def step3_test_local_shortcut():
            # 4. Test local shortcut
            app._window._local_activation_shortcut.activated.emit()
            test_log.append(
                ("after_local_shortcut", app.session_controller.state)
            )

            # 5. Test local Escape shortcut
            app._window._local_reset_shortcut.activated.emit()
            test_log.append(("after_escape", app.session_controller.state))

            # Clean quit
            qapp.quit()

        QTimer.singleShot(100, run_sequence)
        exit_code = app.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            test_log,
            [
                ("initial", SessionState.IDLE),
                ("after_hotkey", SessionState.ACTIVATED),
                ("after_reset", SessionState.IDLE),
                ("after_local_shortcut", SessionState.ACTIVATED),
                ("after_escape", SessionState.IDLE),
            ],
        )


if __name__ == "__main__":
    unittest.main()
