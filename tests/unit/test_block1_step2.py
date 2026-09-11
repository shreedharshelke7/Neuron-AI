"""Unit tests for Block 1 Step 2: Local and Global Activation Hotkeys."""

import importlib
import time
import unittest

from app.session.controller import SessionController
from app.session.state import SessionState
from app.trigger.activation import ActivationTrigger
from app.trigger.global_hotkey import StubGlobalHotkey, WindowsGlobalHotkey
from app.trigger.manager import ActivationManager


class TestBlock1Step2(unittest.TestCase):
    """Test suite for Block 1 Step 2 activation mechanisms and lifecycles."""

    def test_activation_request_changes_state_correctly(self):
        """Requirement 1: activation request changes the session/application state."""
        controller = SessionController()
        manager = ActivationManager(
            on_activate=controller.request_activation,
            global_backend=StubGlobalHotkey(),
        )

        self.assertEqual(controller.state, SessionState.IDLE)
        manager.request_activation()
        self.assertEqual(controller.state, SessionState.ACTIVATED)

    def test_repeated_activation_does_not_create_invalid_state(self):
        """Requirement 2: repeated activation does not create invalid state or duplicate sessions."""
        controller = SessionController()
        activation_events = []

        def on_activate():
            activation_events.append(time.monotonic())
            controller.request_activation()

        manager = ActivationManager(
            on_activate=on_activate,
            global_backend=StubGlobalHotkey(),
            debounce_seconds=0.2,
        )

        # First activation
        manager.request_activation()
        self.assertEqual(controller.state, SessionState.ACTIVATED)
        self.assertEqual(len(activation_events), 1)

        # Immediate repeated activation (within debounce window)
        manager.request_activation()
        self.assertEqual(controller.state, SessionState.ACTIVATED)
        self.assertEqual(len(activation_events), 1)  # Suppressed by debouncing

        # Even if controller receives another request directly, state remains ACTIVATED
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.ACTIVATED)

        # Resetting brings it back to IDLE
        controller.reset_to_idle()
        self.assertEqual(controller.state, SessionState.IDLE)

    def test_registration_failure_does_not_crash_application(self):
        """Requirement 3: registration failure does not crash the application."""
        controller = SessionController()
        failing_backend = StubGlobalHotkey(should_succeed=False)
        manager = ActivationManager(
            on_activate=controller.request_activation,
            global_backend=failing_backend,
        )

        # Starting a failing backend should return False without raising exceptions
        started = manager.start()
        self.assertFalse(started)
        self.assertFalse(manager.is_global_registered)

        # Local activation request must still work seamlessly
        manager.request_activation()
        self.assertEqual(controller.state, SessionState.ACTIVATED)

        # Stopping should not raise
        manager.stop()

    def test_activation_manager_lifecycle(self):
        """Test ActivationManager start and stop lifecycle."""
        backend = StubGlobalHotkey(should_succeed=True)
        manager = ActivationManager(global_backend=backend)

        self.assertFalse(manager.is_global_registered)
        success = manager.start()
        self.assertTrue(success)
        self.assertTrue(manager.is_global_registered)

        manager.stop()
        self.assertFalse(manager.is_global_registered)

    def test_windows_global_hotkey_backend_lifecycle(self):
        """Test WindowsGlobalHotkey start and clean stop on Windows."""
        called = []
        hotkey = WindowsGlobalHotkey(
            on_activate=lambda: called.append(True),
            hotkey_id=9988,  # Use high ID to avoid conflicts
        )

        try:
            started = hotkey.start()
            if started:
                self.assertTrue(hotkey.is_registered)
        finally:
            hotkey.stop()
            self.assertFalse(hotkey.is_registered)

    def test_desktop_shell_window_local_shortcut_and_reset(self):
        """Verify DesktopShellWindow local shortcut and reset controls."""
        from app.desktop.shell import NeuronDesktopApp
        from app.desktop.window import DesktopShellWindow

        desktop_app = NeuronDesktopApp()
        desktop_app.initialize_qapplication()

        controller = SessionController()
        manager = ActivationManager(
            on_activate=controller.request_activation,
            global_backend=StubGlobalHotkey(),
        )
        window = DesktopShellWindow(
            session_controller=controller, activation_trigger=manager
        )

        self.assertEqual(window.state_label.text(), "State: IDLE")
        self.assertFalse(window.reset_button.isEnabled())

        # Trigger local activation
        window._on_activation_shortcut()
        self.assertEqual(window.state_label.text(), "State: ACTIVATED")
        self.assertTrue(window.reset_button.isEnabled())

        # Trigger reset to IDLE
        window._on_reset_clicked()
        self.assertEqual(window.state_label.text(), "State: IDLE")
        self.assertFalse(window.reset_button.isEnabled())

        window.close()

    def test_trigger_modules_do_not_import_pyside6(self):
        """Verify that trigger interfaces and managers remain decoupled from PySide6."""
        trigger_modules = [
            "app.trigger.activation",
            "app.trigger.global_hotkey",
            "app.trigger.manager",
        ]

        for mod_name in trigger_modules:
            mod = importlib.import_module(mod_name)
            for attr_name, attr_val in vars(mod).items():
                if hasattr(attr_val, "__module__") and attr_val.__module__:
                    self.assertFalse(
                        attr_val.__module__.startswith("PySide6"),
                        f"Module {mod_name} imports PySide6 class {attr_val}!",
                    )


if __name__ == "__main__":
    unittest.main()
