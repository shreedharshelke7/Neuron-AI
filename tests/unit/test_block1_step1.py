"""Unit tests for Block 1 Step 1 interfaces, models, and boundaries.

Compatible with both standard library unittest and pytest.
"""

import importlib
import unittest

from app.capture.model import CapturedScreen, DisplayGeometry, SelectedRegion
from app.capture.service import CaptureService, StubCaptureService
from app.overlay.host import OverlayHost, StubOverlayHost
from app.session.controller import SessionController
from app.session.state import SessionState
from app.trigger.activation import ActivationTrigger, StubActivationTrigger


class TestBlock1Step1(unittest.TestCase):
    """Test suite for Block 1 Step 1 data representations and interfaces."""

    # ========================================================================
    # Requirement 4.C: Selected region and Display Geometry
    # ========================================================================

    def test_display_geometry_defaults(self):
        geom = DisplayGeometry(x=0, y=0, width=1920, height=1080)
        self.assertEqual(geom.width, 1920)
        self.assertEqual(geom.height, 1080)
        self.assertEqual(geom.device_pixel_ratio, 1.0)

    def test_selected_region_normalized_coordinates(self):
        geom = DisplayGeometry(x=0, y=0, width=1000, height=800)
        region = SelectedRegion(x=100, y=200, width=300, height=400, display_geometry=geom)

        nx, ny, nw, nh = region.to_normalized()
        self.assertAlmostEqual(nx, 0.1)
        self.assertAlmostEqual(ny, 0.25)
        self.assertAlmostEqual(nw, 0.3)
        self.assertAlmostEqual(nh, 0.5)

    def test_selected_region_with_explicit_geometry(self):
        geom = DisplayGeometry(x=0, y=0, width=1920, height=1080)
        region = SelectedRegion(x=0, y=0, width=1920, height=1080)

        nx, ny, nw, nh = region.to_normalized(geometry=geom)
        self.assertEqual((nx, ny, nw, nh), (0.0, 0.0, 1.0, 1.0))

    def test_selected_region_missing_geometry_raises(self):
        region = SelectedRegion(x=10, y=10, width=100, height=100)
        with self.assertRaises(ValueError):
            region.to_normalized()

    def test_selected_region_invalid_geometry_raises(self):
        invalid_geom = DisplayGeometry(x=0, y=0, width=0, height=1080)
        region = SelectedRegion(x=0, y=0, width=100, height=100, display_geometry=invalid_geom)
        with self.assertRaises(ValueError):
            region.to_normalized()

    # ========================================================================
    # Requirement 4.B: CapturedScreen and CaptureService Interface
    # ========================================================================

    def test_captured_screen_metadata(self):
        geom = DisplayGeometry(x=0, y=0, width=2560, height=1440, device_pixel_ratio=1.5)
        captured = CapturedScreen(
            image_data=b"test_image_bytes",
            geometry=geom,
            display_id="display_1",
            dpi=144.0,
            device_pixel_ratio=1.5,
        )
        self.assertEqual(captured.image_data, b"test_image_bytes")
        self.assertEqual(captured.geometry, geom)
        self.assertEqual(captured.display_id, "display_1")
        self.assertEqual(captured.dpi, 144.0)
        self.assertEqual(captured.device_pixel_ratio, 1.5)

    def test_capture_service_stub(self):
        geom = DisplayGeometry(width=1920, height=1080)
        sample = CapturedScreen(geometry=geom)
        service = StubCaptureService(stub_result=sample)

        self.assertIsInstance(service, CaptureService)
        result = service.capture_current_screen()
        self.assertEqual(result, sample)

    # ========================================================================
    # Requirement 4.D: OverlayHost Interface
    # ========================================================================

    def test_overlay_host_stub(self):
        host = StubOverlayHost()
        self.assertIsInstance(host, OverlayHost)
        self.assertFalse(host.is_visible())

        host.show()
        self.assertTrue(host.is_visible())

        host.dismiss()
        self.assertFalse(host.is_visible())

    # ========================================================================
    # Requirement 4.A: ActivationTrigger Interface
    # ========================================================================

    def test_activation_trigger_stub(self):
        called = []
        trigger = StubActivationTrigger(on_activate=lambda: called.append(True))
        self.assertIsInstance(trigger, ActivationTrigger)
        self.assertEqual(trigger.activated_count, 0)

        trigger.request_activation()
        self.assertEqual(trigger.activated_count, 1)
        self.assertEqual(len(called), 1)

    # ========================================================================
    # Requirement 5: Session Controller and State
    # ========================================================================

    def test_session_controller_idle_state(self):
        controller = SessionController()
        self.assertEqual(controller.state, SessionState.IDLE)

    def test_session_controller_activation_flow(self):
        controller = SessionController()
        recorded_states = []

        controller.add_state_listener(lambda s: recorded_states.append(s))
        controller.request_activation()

        self.assertEqual(controller.state, SessionState.ACTIVATED)
        self.assertEqual(recorded_states, [SessionState.ACTIVATED])

        controller.reset_to_idle()
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertEqual(recorded_states, [SessionState.ACTIVATED, SessionState.IDLE])

    # ========================================================================
    # Requirement 5 & Acceptance Criteria 5: Architecture Isolation
    # ========================================================================

    def test_public_interfaces_do_not_import_pyside6(self):
        """Verify that domain interfaces do not import PySide6 GUI classes."""
        pure_modules = [
            "app.capture.model",
            "app.capture.service",
            "app.overlay.host",
            "app.trigger.activation",
            "app.session.state",
            "app.session.controller",
        ]

        for mod_name in pure_modules:
            mod = importlib.import_module(mod_name)
            for attr_name, attr_val in vars(mod).items():
                if hasattr(attr_val, "__module__") and attr_val.__module__:
                    self.assertFalse(
                        attr_val.__module__.startswith("PySide6"),
                        f"Module {mod_name} imports PySide6 class {attr_val}!",
                    )

    # ========================================================================
    # Requirement 3: Desktop Shell Window and App
    # ========================================================================

    def test_desktop_shell_window_idle_display(self):
        """Verify DesktopShellWindow creates properly and confirms IDLE state."""
        from PySide6.QtWidgets import QApplication
        from app.desktop.shell import NeuronDesktopApp
        from app.desktop.window import DesktopShellWindow

        desktop_app = NeuronDesktopApp()
        qapp = desktop_app.initialize_qapplication()
        self.assertIsInstance(qapp, QApplication)

        controller = SessionController()
        window = DesktopShellWindow(session_controller=controller)

        self.assertEqual(window.windowTitle(), "Neuron AI")
        self.assertIn("IDLE", window.state_label.text())

        # Test state change reflected in UI
        controller.request_activation()
        self.assertIn("ACTIVATED", window.state_label.text())

        controller.reset_to_idle()
        self.assertIn("IDLE", window.state_label.text())

        window.close()


if __name__ == "__main__":
    unittest.main()
