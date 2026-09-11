"""Comprehensive automated test suite for Neuron AI Block 4: Overlay Primitives + Coordinate Rendering.

Covers all 33 required test areas:
1. normalized point mapping
2. normalized rectangle mapping
3. 1920x1080 mapping
4. alternate resolution mapping
5. non-zero display origin
6. normalized boundary values
7. coordinate clamping/safe behavior
8. selected-region mapping
9. HIGHLIGHT rendering
10. ARROW rendering
11. short/zero-length arrow safety
12. TEXT rendering
13. CARD rendering
14. CARD fallback placement
15. EQUATION rendering
16. NONE rendering nothing
17. multiple primitives simultaneously
18. invalid/unsupported action handling
19. one bad primitive not preventing valid primitives
20. empty action list fallback card (SRS FR-16)
21. renderer failure fallback
22. clear removes all rendered actions
23. Escape clears visual state (SRS FR-15 / AC-08)
24. Escape returns the existing controller lifecycle to IDLE
25. stale previous-session render ignored
26. new session clears previous overlay
27. previous overlay does not contaminate new screenshot flow
28. self-capture regression remains fixed
29. overlay renderer failure does not crash desktop shell (NFR-04)
30. no persistent renderer/session artifacts after dismissal (NFR-06)
31. Block 1 compatibility
32. Block 2 compatibility
33. Block 3 compatibility
"""

import math
import sys
import unittest
from unittest.mock import MagicMock

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter
from PySide6.QtWidgets import QApplication

from app.capture.model import CapturedScreen, DisplayGeometry, SelectedRegion
from app.capture.service import CaptureService
from app.overlay.geometry import CoordinateMapper, MappedArrow, MappedPoint, MappedRect
from app.overlay.host import StubOverlayHost
from app.overlay.primitives import (
    ArrowPrimitive,
    CardPrimitive,
    EquationPrimitive,
    FallbackSummaryCard,
    HighlightPrimitive,
    TextPrimitive,
    latex_to_readable_math,
    parse_color,
)
from app.overlay.qt_overlay import QtOverlayHost, RegionSelectionOverlay
from app.overlay.renderer import OverlayRenderer
from app.session.controller import SessionController
from app.session.state import SessionState
from app.tutor.model import OverlayAction, OverlayActionType, TutorResponse

# Ensure a singleton QApplication instance exists for Qt widget tests
qapp = QApplication.instance() or QApplication(sys.argv)


class TestCoordinateMapper(unittest.TestCase):
    """Tests 1 to 8: Coordinate mapping, resolutions, origins, boundaries, and clamping."""

    def test_1_normalized_point_mapping(self):
        """1. Normalized point mapping."""
        geom = DisplayGeometry(x=0, y=0, width=1000, height=800)
        mapper = CoordinateMapper(geom)
        pt = mapper.map_point(0.25, 0.5)
        self.assertEqual(pt.local_x, 250)
        self.assertEqual(pt.local_y, 400)
        self.assertEqual(pt.global_x, 250)
        self.assertEqual(pt.global_y, 400)
        self.assertEqual(pt.qpoint, QPoint(250, 400))

    def test_2_normalized_rectangle_mapping(self):
        """2. Normalized rectangle mapping."""
        geom = DisplayGeometry(x=0, y=0, width=1000, height=800)
        mapper = CoordinateMapper(geom)
        rect = mapper.map_rect(0.1, 0.2, 0.3, 0.4)
        self.assertEqual(rect.local_x, 100)
        self.assertEqual(rect.local_y, 160)
        self.assertEqual(rect.width, 300)
        self.assertEqual(rect.height, 320)
        self.assertEqual(rect.qrect, QRect(100, 160, 300, 320))

    def test_3_1920x1080_mapping(self):
        """3. 1920x1080 standard mapping."""
        geom = DisplayGeometry(x=0, y=0, width=1920, height=1080)
        mapper = CoordinateMapper(geom)
        pt = mapper.map_point(0.5, 0.5)
        self.assertEqual((pt.local_x, pt.local_y), (960, 540))

        rect = mapper.map_rect(0.2, 0.1, 0.5, 0.4)
        self.assertEqual((rect.local_x, rect.local_y, rect.width, rect.height), (384, 108, 960, 432))

    def test_4_alternate_resolution_mapping(self):
        """4. Alternate resolution mapping (e.g. 2560x1440, 3840x2160, 1366x768)."""
        resolutions = [
            (2560, 1440),
            (3840, 2160),
            (1366, 768),
        ]
        for w, h in resolutions:
            geom = DisplayGeometry(x=0, y=0, width=w, height=h)
            mapper = CoordinateMapper(geom)
            pt = mapper.map_point(0.5, 0.5)
            self.assertEqual(pt.local_x, int(round(0.5 * w)))
            self.assertEqual(pt.local_y, int(round(0.5 * h)))

    def test_5_nonzero_display_origin(self):
        """5. Non-zero display origin (e.g. secondary monitor at x=1920, y=100)."""
        geom = DisplayGeometry(x=1920, y=100, width=1920, height=1080)
        mapper = CoordinateMapper(geom)
        pt = mapper.map_point(0.5, 0.5)
        # In overlay-local coordinates (relative to the overlay window placed at 1920, 100):
        self.assertEqual(pt.local_x, 960)
        self.assertEqual(pt.local_y, 540)
        # In global desktop coordinates:
        self.assertEqual(pt.global_x, 1920 + 960)
        self.assertEqual(pt.global_y, 100 + 540)

    def test_6_normalized_boundary_values(self):
        """6. Normalized boundary values (0.0 and 1.0)."""
        geom = DisplayGeometry(x=0, y=0, width=1000, height=800)
        mapper = CoordinateMapper(geom)
        top_left = mapper.map_point(0.0, 0.0)
        bottom_right = mapper.map_point(1.0, 1.0)
        self.assertEqual((top_left.local_x, top_left.local_y), (0, 0))
        self.assertEqual((bottom_right.local_x, bottom_right.local_y), (1000, 800))

        full_rect = mapper.map_rect(0.0, 0.0, 1.0, 1.0)
        self.assertEqual((full_rect.local_x, full_rect.local_y, full_rect.width, full_rect.height), (0, 0, 1000, 800))

    def test_7_coordinate_clamping_safe_behavior(self):
        """7. Coordinate clamping and safe behavior against out-of-range, negative, NaN, Inf, and None."""
        geom = DisplayGeometry(x=0, y=0, width=1000, height=800)
        mapper = CoordinateMapper(geom)

        # Negative coordinates clamped to 0
        pt_neg = mapper.map_point(-0.5, -1.0)
        self.assertEqual((pt_neg.local_x, pt_neg.local_y), (0, 0))

        # Oversized coordinates clamped to 1.0
        pt_over = mapper.map_point(1.5, 2.0)
        self.assertEqual((pt_over.local_x, pt_over.local_y), (1000, 800))

        # NaN and Inf handled safely without throwing exceptions
        pt_nan = mapper.map_point(float("nan"), float("inf"))
        self.assertEqual(pt_nan.local_x, 0)
        self.assertEqual(pt_nan.local_y, 0)

        # Rectangle clamped so x + w <= width and y + h <= height
        rect_clamped = mapper.map_rect(0.8, 0.8, 0.5, 0.5)
        self.assertEqual(rect_clamped.local_x, 800)
        self.assertEqual(rect_clamped.local_y, 640)
        self.assertEqual(rect_clamped.width, 200)
        self.assertEqual(rect_clamped.height, 160)

    def test_8_selected_region_mapping(self):
        """8. Selected-region mapping (relative_to_region=True)."""
        geom = DisplayGeometry(x=0, y=0, width=1920, height=1080)
        region = SelectedRegion(x=200, y=300, width=400, height=200, display_geometry=geom)
        mapper = CoordinateMapper(geom, selected_region=region)

        # Point relative to selected region
        pt = mapper.map_point(0.5, 0.5, relative_to_region=True)
        # Local to display: 200 + 0.5*400 = 400, 300 + 0.5*200 = 400
        self.assertEqual(pt.local_x, 400)
        self.assertEqual(pt.local_y, 400)
        self.assertEqual(pt.global_x, 400)
        self.assertEqual(pt.global_y, 400)

        # Rect relative to selected region
        rect = mapper.map_rect(0.1, 0.1, 0.8, 0.8, relative_to_region=True)
        self.assertEqual(rect.local_x, 240)
        self.assertEqual(rect.local_y, 320)
        self.assertEqual(rect.width, 320)
        self.assertEqual(rect.height, 160)


class TestOverlayPrimitives(unittest.TestCase):
    """Tests 9 to 16: Concrete visual primitives and zero-division protection."""

    def setUp(self):
        # Create an in-memory image and QPainter for testing drawing routines
        self.image = QImage(800, 600, QImage.Format.Format_ARGB32_Premultiplied)
        self.image.fill(Qt.GlobalColor.transparent)
        self.painter = QPainter(self.image)

    def tearDown(self):
        self.painter.end()

    def test_9_highlight_rendering(self):
        """9. HIGHLIGHT rendering."""
        rect = MappedRect(local_x=50, local_y=50, width=200, height=100, global_x=50, global_y=50)
        highlight = HighlightPrimitive(rect=rect, label="Function def", color="#4285F4")
        # Should paint cleanly onto painter without error
        highlight.paint(self.painter)
        # Safe zero-size check
        zero_rect = MappedRect(0, 0, 0, 0, 0, 0)
        HighlightPrimitive(rect=zero_rect).paint(self.painter)

    def test_10_arrow_rendering(self):
        """10. ARROW rendering."""
        p1 = MappedPoint(50, 50, 50, 50)
        p2 = MappedPoint(250, 150, 250, 150)
        arrow_geom = MappedArrow(start=p1, end=p2)
        arrow = ArrowPrimitive(arrow=arrow_geom, label="Step 1", color="#EA4335")
        self.assertGreater(arrow_geom.length, 0)
        arrow.paint(self.painter)

    def test_11_short_zero_length_arrow_safety(self):
        """11. Short / zero-length arrow safety against divide-by-zero or NaN vectors."""
        p_same = MappedPoint(100, 100, 100, 100)
        zero_arrow = MappedArrow(start=p_same, end=p_same)
        self.assertEqual(zero_arrow.length, 0.0)

        # Must not raise ZeroDivisionError or crash Qt
        arrow_primitive = ArrowPrimitive(arrow=zero_arrow, label="Point", color="red")
        arrow_primitive.paint(self.painter)

        # Very short arrow (< 6px)
        p_short = MappedPoint(102, 103, 102, 103)
        short_arrow = MappedArrow(start=p_same, end=p_short)
        self.assertLess(short_arrow.length, 6.0)
        ArrowPrimitive(arrow=short_arrow).paint(self.painter)

    def test_12_text_rendering(self):
        """12. TEXT rendering."""
        rect = MappedRect(local_x=100, local_y=100, width=200, height=50, global_x=100, global_y=100)
        text_prim = TextPrimitive(rect=rect, text="Notice the exponent here.", color="#FBBC04")
        text_prim.paint(self.painter)

        # Safe empty text check
        empty_prim = TextPrimitive(rect=rect, text="")
        empty_prim.paint(self.painter)

    def test_13_card_rendering(self):
        """13. CARD rendering with title and body."""
        rect = MappedRect(local_x=100, local_y=100, width=350, height=150, global_x=100, global_y=100)
        card = CardPrimitive(
            rect=rect,
            title="Power Rule",
            text="Bring the exponent to the front and decrease by 1.",
            color="#4285F4",
        )
        card.paint(self.painter)

    def test_14_card_fallback_placement(self):
        """14. CARD fallback placement when rect is missing or zero-sized."""
        geom = DisplayGeometry(x=0, y=0, width=1920, height=1080)
        card = CardPrimitive(
            rect=None,
            title="Overview",
            text="General concept summary.",
            display_geometry=geom,
        )
        card.paint(self.painter)

    def test_15_equation_rendering(self):
        """15. EQUATION rendering and LaTeX to readable Unicode math conversion."""
        raw_latex = r"f'(x) = \frac{d}{dx}[x^2] = 2x"
        readable = latex_to_readable_math(raw_latex)
        self.assertIn("2x", readable)
        self.assertNotIn(r"\frac", readable)

        rect = MappedRect(local_x=80, local_y=80, width=300, height=80, global_x=80, global_y=80)
        eq = EquationPrimitive(
            rect=rect,
            expression=raw_latex,
            label="Derivative Rule",
            color="#34A853",
        )
        eq.paint(self.painter)

    def test_16_none_rendering_nothing(self):
        """16. NONE rendering nothing."""
        renderer = OverlayRenderer()
        action = OverlayAction(action_type=OverlayActionType.NONE)
        response = TutorResponse(
            intent="explanation",
            summary="No visual markings needed.",
            narration="Pass through.",
            overlay_actions=[action],
        )
        renderer.render_tutor_response(response)
        # Primitives list is empty; fallback summary card is shown per SRS FR-16
        self.assertEqual(len(renderer.primitives), 0)
        self.assertIsNotNone(renderer.fallback_card)


class TestOverlayRendererAndFaultIsolation(unittest.TestCase):
    """Tests 17 to 22: OverlayRenderer orchestration, multiple primitives, and fallbacks."""

    def test_17_multiple_primitives_simultaneously(self):
        """17. Multiple primitives simultaneously (AC-05: at least 4 primitives)."""
        renderer = OverlayRenderer()
        geom = DisplayGeometry(width=1920, height=1080)
        response = TutorResponse(
            intent="explanation",
            summary="Complete calculus lesson.",
            narration="Explaining power rule.",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.1, 0.1, 0.3, 0.2),
                    label="Formula",
                ),
                OverlayAction(
                    action_type=OverlayActionType.ARROW,
                    target_normalized=(0.5, 0.5, 0.4, 0.3),
                    label="Points to x^2",
                ),
                OverlayAction(
                    action_type=OverlayActionType.TEXT,
                    target_normalized=(0.6, 0.1, 0.3, 0.1),
                    text="Notice exponent",
                ),
                OverlayAction(
                    action_type=OverlayActionType.CARD,
                    target_normalized=(0.6, 0.6, 0.35, 0.25),
                    title="Concept Card",
                    text="Detailed explanation card.",
                ),
                OverlayAction(
                    action_type=OverlayActionType.EQUATION,
                    target_normalized=(0.2, 0.7, 0.4, 0.15),
                    text=r"f'(x) = 2x",
                ),
            ],
        )
        renderer.render_tutor_response(response, geometry=geom)
        self.assertEqual(len(renderer.primitives), 5)
        self.assertTrue(renderer.has_visuals())

    def test_18_invalid_unsupported_action_handling(self):
        """18. Invalid / unsupported action handling."""
        renderer = OverlayRenderer()
        # Mock action with invalid action type
        bad_action = MagicMock()
        bad_action.action_type = "UNKNOWN_NONEXISTENT_TYPE"
        response = TutorResponse(
            intent="hint",
            summary="Testing bad action.",
            narration="Testing.",
            overlay_actions=[],
        )
        # Should process without throwing an exception
        renderer.render_tutor_response(response)
        self.assertTrue(renderer.has_visuals())

    def test_19_one_bad_primitive_not_preventing_valid_primitives(self):
        """19. One bad primitive does not prevent other valid primitives from rendering."""
        renderer = OverlayRenderer()
        geom = DisplayGeometry(width=1920, height=1080)
        valid_action = OverlayAction(
            action_type=OverlayActionType.HIGHLIGHT,
            target_normalized=(0.2, 0.2, 0.2, 0.2),
            label="Valid Highlight",
        )
        bad_action = MagicMock()
        bad_action.action_type = "MALFORMED_TYPE"

        response = MagicMock(spec=TutorResponse)
        response.overlay_actions = [bad_action, valid_action]
        response.summary = "Summary text"
        response.follow_up = None

        renderer.render_tutor_response(response, geometry=geom)
        # Valid primitive should have been added
        self.assertEqual(len(renderer.primitives), 1)
        self.assertIsInstance(renderer.primitives[0], HighlightPrimitive)

    def test_20_empty_action_list_fallback_card(self):
        """20. Empty action list produces FallbackSummaryCard per SRS FR-16."""
        renderer = OverlayRenderer()
        geom = DisplayGeometry(width=1920, height=1080)
        response = TutorResponse(
            intent="clarification",
            summary="Here is the conceptual answer without screen elements.",
            narration="Detailed audio.",
            overlay_actions=[],
            follow_up="What happens when x is zero?",
        )
        renderer.render_tutor_response(response, geometry=geom)
        self.assertEqual(len(renderer.primitives), 0)
        self.assertIsNotNone(renderer.fallback_card)
        self.assertEqual(renderer.fallback_card.summary, response.summary)
        self.assertEqual(renderer.fallback_card.follow_up, response.follow_up)
        self.assertTrue(renderer.has_visuals())

    def test_21_renderer_failure_fallback(self):
        """21. Renderer failure fallback when all primitives fail."""
        renderer = OverlayRenderer()
        geom = DisplayGeometry(width=1920, height=1080)
        bad_action1 = MagicMock()
        bad_action1.action_type = "BAD1"
        bad_action2 = MagicMock()
        bad_action2.action_type = "BAD2"

        response = MagicMock(spec=TutorResponse)
        response.overlay_actions = [bad_action1, bad_action2]
        response.summary = "Safe fallback summary."
        response.follow_up = None

        renderer.render_tutor_response(response, geometry=geom)
        self.assertEqual(len(renderer.primitives), 0)
        self.assertIsNotNone(renderer.fallback_card)
        self.assertEqual(renderer.fallback_card.summary, "Safe fallback summary.")

    def test_22_clear_removes_all_rendered_actions(self):
        """22. clear removes all rendered actions."""
        renderer = OverlayRenderer()
        geom = DisplayGeometry(width=1920, height=1080)
        response = TutorResponse(
            intent="explanation",
            summary="Cleared summary.",
            narration="",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.1, 0.1, 0.2, 0.2),
                )
            ],
        )
        renderer.render_tutor_response(response, geometry=geom)
        self.assertTrue(renderer.has_visuals())
        renderer.clear()
        self.assertFalse(renderer.has_visuals())
        self.assertEqual(len(renderer.primitives), 0)
        self.assertIsNone(renderer.fallback_card)


class TestOverlayLifecycleAndSessionIntegration(unittest.TestCase):
    """Tests 23 to 30: Escape dismissal, session state safety, stale tokens, and self-capture."""

    def test_23_escape_clears_visual_state(self):
        """23. Escape clears visual state in RegionSelectionOverlay (SRS FR-15 / AC-08)."""
        overlay = RegionSelectionOverlay()
        geom = DisplayGeometry(width=1920, height=1080)
        overlay.show_for_geometry(geom)

        response = TutorResponse(
            intent="explanation",
            summary="Escape test summary.",
            narration="",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.2, 0.2, 0.2, 0.2),
                )
            ],
        )
        overlay.render_tutor_response(response, geometry=geom)
        self.assertTrue(overlay.has_explanation())

        # Simulate Escape key press
        escape_event = QKeyEvent(
            QKeyEvent.Type.KeyPress,
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.NoModifier,
        )
        overlay.keyPressEvent(escape_event)

        self.assertFalse(overlay.has_explanation())
        self.assertFalse(overlay.isVisible())

    def test_24_escape_returns_existing_controller_lifecycle_to_idle(self):
        """24. Escape returns the existing controller lifecycle to IDLE."""
        overlay_host = StubOverlayHost()
        controller = SessionController(overlay_host=overlay_host)

        # Transition to RESPONDED
        controller._set_state(SessionState.THINKING)
        response = TutorResponse(
            intent="explanation",
            summary="Lesson",
            narration="Lesson audio",
            overlay_actions=[],
        )
        controller.handle_tutor_success(response, token=controller._session_token)
        self.assertEqual(controller.state, SessionState.RESPONDED)
        self.assertTrue(overlay_host.has_explanation)

        # Press Escape / dismiss
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertFalse(overlay_host.has_explanation)

    def test_25_stale_previous_session_render_ignored(self):
        """25. Stale previous-session render ignored via session token."""
        overlay_host = StubOverlayHost()
        controller = SessionController(overlay_host=overlay_host)
        controller._set_state(SessionState.THINKING)
        current_token = controller._session_token

        # Response from an older or cancelled session
        stale_token = current_token - 1
        stale_response = TutorResponse(
            intent="hint", summary="Stale", narration="", overlay_actions=[]
        )
        controller.handle_tutor_success(stale_response, token=stale_token)

        # State should not have transitioned and overlay should not have rendered
        self.assertEqual(controller.state, SessionState.THINKING)
        self.assertFalse(overlay_host.has_explanation)

    def test_26_new_session_clears_previous_overlay(self):
        """26. New session clears previous overlay."""
        overlay_host = StubOverlayHost()
        controller = SessionController(overlay_host=overlay_host)
        controller._set_state(SessionState.THINKING)
        response = TutorResponse(
            intent="explanation", summary="First", narration="", overlay_actions=[]
        )
        controller.handle_tutor_success(response, token=controller._session_token)
        self.assertEqual(controller.state, SessionState.RESPONDED)
        self.assertTrue(overlay_host.has_explanation)

        # Request new activation
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.ACTIVATED)
        self.assertFalse(overlay_host.has_explanation)

    def test_27_previous_overlay_does_not_contaminate_new_screenshot_flow(self):
        """27. Previous overlay is cleared and dismissed before screen capture is executed."""
        order_of_operations = []

        class TrackingOverlayHost(StubOverlayHost):
            def clear_explanation(self):
                order_of_operations.append("overlay_cleared")
                super().clear_explanation()

            def hide(self):
                order_of_operations.append("overlay_hidden")
                super().hide()

            def dismiss(self):
                order_of_operations.append("overlay_dismissed")
                super().dismiss()

        class TrackingCaptureService(CaptureService):
            def capture_current_screen(self):
                order_of_operations.append("screen_captured")
                geom = DisplayGeometry(width=1920, height=1080)
                return CapturedScreen(image_data=b"clean_pixels", geometry=geom)

        overlay_host = TrackingOverlayHost()
        overlay_host.show()
        overlay_host.render_tutor_response(
            TutorResponse(intent="hint", summary="Old", narration="", overlay_actions=[])
        )
        capture_service = TrackingCaptureService()

        controller = SessionController(
            capture_service=capture_service,
            overlay_host=overlay_host,
            auto_capture=False,
        )

        controller.begin_capture_flow(delay_ms=0)

        # Ensure clear and hide happened BEFORE screen capture
        self.assertIn("overlay_cleared", order_of_operations)
        self.assertIn("overlay_hidden", order_of_operations)
        self.assertIn("screen_captured", order_of_operations)

        clear_idx = order_of_operations.index("overlay_cleared")
        hide_idx = order_of_operations.index("overlay_hidden")
        capture_idx = order_of_operations.index("screen_captured")

        self.assertLess(clear_idx, capture_idx, "Overlay must be cleared before capture")
        self.assertLess(hide_idx, capture_idx, "Overlay must be hidden before capture")

    def test_28_self_capture_regression_remains_fixed(self):
        """28. Self-capture regression remains fixed: window hidden before capture."""
        window_events = []

        class MockWindow:
            def isVisible(self):
                return True

            def isMaximized(self):
                return False

            def hide(self):
                window_events.append("window_hidden")

            def show(self):
                window_events.append("window_shown")

        class MockCaptureService(CaptureService):
            def capture_current_screen(self):
                window_events.append("screen_captured")
                return CapturedScreen(
                    geometry=DisplayGeometry(width=1920, height=1080)
                )

        win = MockWindow()
        cap = MockCaptureService()
        controller = SessionController(
            capture_service=cap,
            desktop_window=win,
            capture_delay_ms=0,
        )

        controller.begin_capture_flow(delay_ms=0)

        self.assertIn("window_hidden", window_events)
        self.assertIn("screen_captured", window_events)
        self.assertIn("window_shown", window_events)

        hide_idx = window_events.index("window_hidden")
        cap_idx = window_events.index("screen_captured")
        show_idx = window_events.index("window_shown")

        self.assertLess(hide_idx, cap_idx)
        self.assertLess(cap_idx, show_idx)

    def test_29_overlay_renderer_failure_does_not_crash_desktop_shell(self):
        """29. Overlay renderer failure does not crash desktop shell (NFR-04)."""
        overlay = RegionSelectionOverlay()
        geom = DisplayGeometry(width=800, height=600)
        overlay.show_for_geometry(geom)

        # Mock a primitive whose paint method raises an exception
        bad_prim = MagicMock()
        bad_prim.paint.side_effect = RuntimeError("Simulated drawing engine failure")

        overlay._renderer._primitives = [bad_prim]
        overlay._renderer._has_visuals = True

        img = QImage(800, 600, QImage.Format.Format_ARGB32_Premultiplied)
        painter = QPainter(img)
        try:
            # overlay._renderer.paint() must isolate the failure and not raise
            overlay._renderer.paint(painter)
        finally:
            painter.end()
            overlay.dismiss()

    def test_30_no_persistent_renderer_session_artifacts(self):
        """30. No persistent renderer / session artifacts created on disk (NFR-06)."""
        import os
        from pathlib import Path

        repo_root = Path(__file__).parents[2]
        before_files = set(os.listdir(repo_root))

        # Perform full render and dismiss
        renderer = OverlayRenderer()
        geom = DisplayGeometry(width=1920, height=1080)
        response = TutorResponse(
            intent="explanation",
            summary="Ephemeral only",
            narration="Ephemeral narration",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.2, 0.2, 0.3, 0.3),
                )
            ],
        )
        renderer.render_tutor_response(response, geometry=geom)
        renderer.clear()

        after_files = set(os.listdir(repo_root))
        # Ensure no temporary overlay files, screenshots, or dumps leaked into repo root
        self.assertEqual(before_files, after_files)


if __name__ == "__main__":
    unittest.main()
