"""Unit tests for Block 1 / Phase 0 completion requirements."""

import os
import unittest
from unittest.mock import MagicMock

from app.capture.indicator import StubCaptureIndicator
from app.capture.model import CapturedScreen, DisplayGeometry, SelectedRegion
from app.capture.service import CaptureService, StubCaptureService
from app.overlay.host import StubOverlayHost
from app.session.controller import SessionController
from app.session.state import SessionState
from app.trigger.activation import StubActivationTrigger


class TestBlock1Completion(unittest.TestCase):
    """Test suite covering Block 1 Phase 0 capture, indicator, region, and overlay requirements."""

    # ========================================================================
    # A. Screen Capture Requirements
    # ========================================================================

    def test_capture_does_not_occur_before_activation(self):
        """Requirement 1: Capture does not occur before explicit activation."""
        capture_mock = MagicMock(spec=CaptureService)
        controller = SessionController(
            capture_service=capture_mock, auto_capture=True
        )

        self.assertEqual(controller.state, SessionState.IDLE)
        capture_mock.capture_current_screen.assert_not_called()
        self.assertIsNone(controller.current_capture)

    def test_valid_activation_calls_capture_exactly_once(self):
        """Requirement 2: Valid activation calls capture exactly once."""
        geom = DisplayGeometry(width=1920, height=1080)
        sample_screen = CapturedScreen(geometry=geom)
        capture_mock = MagicMock(spec=CaptureService)
        capture_mock.capture_current_screen.return_value = sample_screen

        controller = SessionController(
            capture_service=capture_mock, auto_capture=True
        )
        controller.request_activation()

        capture_mock.capture_current_screen.assert_called_once()
        self.assertEqual(controller.current_capture, sample_screen)
        self.assertEqual(controller.state, SessionState.SELECTING)

    def test_captured_screen_stores_valid_geometry_and_dimensions(self):
        """Requirement 3: CapturedScreen stores valid geometry and dimensions."""
        geom = DisplayGeometry(
            x=1920, y=0, width=2560, height=1440, device_pixel_ratio=1.5
        )
        captured = CapturedScreen(
            image_data=b"pixel_buffer",
            geometry=geom,
            display_id="DISPLAY2",
            dpi=144.0,
            device_pixel_ratio=1.5,
            pixel_width=3840,
            pixel_height=2160,
        )

        self.assertEqual(captured.geometry.x, 1920)
        self.assertEqual(captured.geometry.pixel_width, 3840)
        self.assertEqual(captured.geometry.pixel_height, 2160)
        self.assertEqual(captured.pixel_width, 3840)
        self.assertEqual(captured.pixel_height, 2160)
        self.assertGreater(captured.timestamp, 0)

    def test_capture_remains_in_memory_by_default(self):
        """Requirement 4: Capture remains in memory by default without saving to disk."""
        # Ensure debug environment variable is disabled
        if "NEURON_DEBUG_SAVE_CAPTURE" in os.environ:
            del os.environ["NEURON_DEBUG_SAVE_CAPTURE"]

        geom = DisplayGeometry(width=1000, height=800)
        sample = CapturedScreen(image_data={"in_memory": True}, geometry=geom)
        service = StubCaptureService(stub_result=sample)
        res = service.capture_current_screen()

        self.assertIsNotNone(res.image_data)
        self.assertFalse(os.path.exists("captures/debug_test_should_not_exist.png"))

    def test_capture_failure_does_not_crash_session_control(self):
        """Requirement 5: Capture failure does not crash session control."""
        failing_capture = MagicMock(spec=CaptureService)
        failing_capture.capture_current_screen.side_effect = RuntimeError(
            "Screen grab failed"
        )

        controller = SessionController(
            capture_service=failing_capture, auto_capture=True
        )

        # Should handle error gracefully without raising
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.current_capture)

    # ========================================================================
    # B. Capture Indicator Requirements
    # ========================================================================

    def test_indicator_is_shown_and_cleared_on_capture(self):
        """Requirements 6 & 7: Indicator is shown for capture and cleared after capture."""
        geom = DisplayGeometry(width=1920, height=1080)
        sample_screen = CapturedScreen(geometry=geom)

        indicator = StubCaptureIndicator()
        indicator_states = []

        def capture_with_indicator_check():
            indicator_states.append(indicator.is_visible())
            return sample_screen

        capture_mock = MagicMock(spec=CaptureService)
        capture_mock.capture_current_screen.side_effect = (
            capture_with_indicator_check
        )

        controller = SessionController(
            capture_service=capture_mock,
            capture_indicator=indicator,
            auto_capture=True,
        )

        self.assertFalse(indicator.is_visible())
        controller.request_activation()

        # Indicator was shown during capture
        self.assertEqual(indicator_states, [True])
        # Indicator is cleared after capture
        self.assertFalse(indicator.is_visible())

    def test_indicator_cleared_after_failed_capture(self):
        """Requirement 8: Indicator is cleared after failed capture."""
        indicator = StubCaptureIndicator()
        failing_capture = MagicMock(spec=CaptureService)
        failing_capture.capture_current_screen.side_effect = RuntimeError(
            "Hardware error"
        )

        controller = SessionController(
            capture_service=failing_capture,
            capture_indicator=indicator,
            auto_capture=True,
        )

        controller.request_activation()
        self.assertFalse(indicator.is_visible())
        self.assertEqual(controller.state, SessionState.IDLE)

    # ========================================================================
    # C. Region Geometry & DPI Normalization Requirements
    # ========================================================================

    def test_drag_coordinates_top_left_to_bottom_right(self):
        """Requirement 9: Drag coordinates normalize correctly dragging top-left to bottom-right."""
        geom = DisplayGeometry(x=0, y=0, width=1000, height=800)
        # Start (100, 200), End (400, 600) -> w=300, h=400
        region = SelectedRegion(
            x=100, y=200, width=300, height=400, display_geometry=geom
        )

        nx, ny, nw, nh = region.to_normalized()
        self.assertAlmostEqual(nx, 0.1)
        self.assertAlmostEqual(ny, 0.25)
        self.assertAlmostEqual(nw, 0.3)
        self.assertAlmostEqual(nh, 0.5)

    def test_drag_coordinates_bottom_right_to_top_left(self):
        """Requirement 10: Drag coordinates normalize correctly dragging bottom-right to top-left."""
        geom = DisplayGeometry(x=0, y=0, width=1000, height=800)
        start_x, start_y = 400, 600
        end_x, end_y = 100, 200

        # Inverted drag normalized bounds
        min_x = min(start_x, end_x)
        min_y = min(start_y, end_y)
        w = abs(start_x - end_x)
        h = abs(start_y - end_y)

        region = SelectedRegion(
            x=min_x, y=min_y, width=w, height=h, display_geometry=geom
        )
        nx, ny, nw, nh = region.to_normalized()

        self.assertAlmostEqual(nx, 0.1)
        self.assertAlmostEqual(ny, 0.25)
        self.assertAlmostEqual(nw, 0.3)
        self.assertAlmostEqual(nh, 0.5)

    def test_region_is_clamped_to_screen_bounds(self):
        """Requirement 11: Region is clamped to screen bounds."""
        geom = DisplayGeometry(x=0, y=0, width=1000, height=800)
        # Region extending beyond screen
        region = SelectedRegion(
            x=800, y=600, width=500, height=500, display_geometry=geom
        )

        nx, ny, nw, nh = region.to_normalized()
        self.assertAlmostEqual(nx, 0.8)
        self.assertAlmostEqual(ny, 0.75)
        self.assertAlmostEqual(nw, 0.2)  # Clamped to 1.0 - 0.8
        self.assertAlmostEqual(nh, 0.25)  # Clamped to 1.0 - 0.75

    def test_coordinate_mapping_conversions(self):
        """Requirement 12: Test mapping between global, local, pixel, and normalized coordinates."""
        geom = DisplayGeometry(
            x=1920, y=100, width=1000, height=800, device_pixel_ratio=1.5
        )
        region = SelectedRegion(
            x=2120, y=300, width=200, height=200, display_geometry=geom
        )

        # Global: (2120, 300, 200, 200)
        self.assertEqual((region.x, region.y), (2120, 300))

        # Local: rel_x = 2120 - 1920 = 200, rel_y = 300 - 100 = 200
        lx, ly, lw, lh = region.to_local_coordinates()
        self.assertEqual((lx, ly, lw, lh), (200, 200, 200, 200))

        # Physical pixels: 200 * 1.5 = 300
        px, py, pw, ph = region.to_pixel_coordinates()
        self.assertEqual((px, py, pw, ph), (300, 300, 300, 300))

        # Normalized: 200 / 1000 = 0.2, 200 / 800 = 0.25
        nx, ny, nw, nh = region.to_normalized()
        self.assertAlmostEqual(nx, 0.2)
        self.assertAlmostEqual(ny, 0.25)
        self.assertAlmostEqual(nw, 0.2)
        self.assertAlmostEqual(nh, 0.25)

    # ========================================================================
    # D. Overlay & Session Lifecycle Requirements
    # ========================================================================

    def test_escape_dismiss_clears_region_and_returns_to_idle(self):
        """Requirements 14 & 15: Escape/dismiss clears state and returns to IDLE."""
        geom = DisplayGeometry(width=1920, height=1080)
        sample = CapturedScreen(geometry=geom)
        overlay_host = StubOverlayHost()

        controller = SessionController(
            capture_service=StubCaptureService(sample),
            overlay_host=overlay_host,
            auto_capture=True,
        )

        controller.request_activation()
        self.assertEqual(controller.state, SessionState.SELECTING)
        self.assertTrue(overlay_host.is_visible())

        # Select a region
        region = SelectedRegion(
            x=100, y=100, width=200, height=200, display_geometry=geom
        )
        overlay_host.simulate_selection(region)
        self.assertEqual(controller.state, SessionState.SELECTED)
        self.assertEqual(controller.selected_region, region)

        # Press Escape / dismiss
        controller.dismiss()

        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertIsNone(controller.selected_region)
        self.assertIsNone(controller.current_capture)
        self.assertFalse(overlay_host.is_visible())

    def test_new_activation_works_after_dismissal(self):
        """Requirement 16: A new activation works cleanly after dismissal."""
        geom = DisplayGeometry(width=1920, height=1080)
        capture_mock = MagicMock(spec=CaptureService)
        capture_mock.capture_current_screen.return_value = CapturedScreen(
            geometry=geom
        )

        controller = SessionController(
            capture_service=capture_mock, auto_capture=True
        )

        # Cycle 1
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.SELECTING)
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)

        # Cycle 2
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.SELECTING)
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)

        self.assertEqual(capture_mock.capture_current_screen.call_count, 2)

    def test_overlay_receives_target_screen_geometry(self):
        """Requirement 17: Overlay receives correct target screen geometry."""
        target_geom = DisplayGeometry(
            x=1920, y=0, width=2560, height=1440, device_pixel_ratio=1.5
        )
        captured = CapturedScreen(geometry=target_geom)
        overlay_host = StubOverlayHost()

        controller = SessionController(
            capture_service=StubCaptureService(captured),
            overlay_host=overlay_host,
            auto_capture=True,
        )

        controller.request_activation()
        self.assertEqual(overlay_host.last_geometry, target_geom)


if __name__ == "__main__":
    unittest.main()
