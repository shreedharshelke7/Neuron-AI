"""PySide6 transparent always-on-top overlay and region selection implementation."""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QKeyEvent,
    QMouseEvent,
    QPaintEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import QWidget

from app.capture.model import DisplayGeometry, SelectedRegion
from app.overlay.host import OverlayHost
from app.overlay.renderer import OverlayRenderer

logger = logging.getLogger(__name__)


class RegionSelectionOverlay(QWidget):
    """Transparent always-on-top overlay widget for manual region selection and visual explanation.

    Allows the user to click-drag a rectangle in any direction. Releasing the
    mouse creates a SelectedRegion that remains visibly outlined.
    When a TutorResponse is received, renders visual primitives (HIGHLIGHT, ARROW,
    TEXT, CARD, EQUATION) directly above the source application.
    Pressing Escape immediately dismisses the overlay and clears all visual explanation state.
    """

    MIN_SELECTION_SIZE: int = 8  # Minimum pixel width/height to avoid accidental clicks

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._target_geometry: Optional[DisplayGeometry] = None
        self._start_pos: Optional[QPoint] = None
        self._current_pos: Optional[QPoint] = None
        self._is_dragging: bool = False
        self._final_region: Optional[SelectedRegion] = None
        self._renderer: OverlayRenderer = OverlayRenderer()

        self._on_region_selected: Optional[Callable[[SelectedRegion], None]] = None
        self._on_dismissed: Optional[Callable[[], None]] = None

        self._init_ui()

    def _init_ui(self) -> None:
        # Window flags: frameless, always on top, tool window (no taskbar item)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)

    def set_callbacks(
        self,
        on_selected: Optional[Callable[[SelectedRegion], None]] = None,
        on_dismissed: Optional[Callable[[], None]] = None,
    ) -> None:
        """Register callbacks for selection and dismissal."""
        self._on_region_selected = on_selected
        self._on_dismissed = on_dismissed

    def show_for_geometry(self, geometry: DisplayGeometry) -> None:
        """Align overlay to the target screen geometry and show."""
        self._target_geometry = geometry
        self._start_pos = None
        self._current_pos = None
        self._is_dragging = False
        self._final_region = None

        # Position and size overlay to cover the target display exactly
        self.setGeometry(
            geometry.x, geometry.y, geometry.width, geometry.height
        )
        self.show()
        self.raise_()
        self.activateWindow()

    @property
    def renderer(self) -> OverlayRenderer:
        """Active visual overlay renderer."""
        return self._renderer

    def render_tutor_response(
        self,
        response: Any,
        geometry: Optional[DisplayGeometry] = None,
        selected_region: Optional[SelectedRegion] = None,
        relative_to_region: bool = False,
    ) -> None:
        """Render visual explanation primitives from a TutorResponse."""
        geom = geometry or self._target_geometry
        reg = selected_region or self._final_region
        self._renderer.render_tutor_response(
            response=response,
            geometry=geom,
            selected_region=reg,
            relative_to_region=relative_to_region,
        )
        self.update()

    def clear_explanation(self) -> None:
        """Clear all active visual explanation primitives and repaint."""
        self._renderer.clear()
        self.update()

    def has_explanation(self) -> bool:
        """Return True if visual explanation primitives are currently rendered."""
        return self._renderer.has_visuals()

    def dismiss(self) -> None:
        """Hide overlay, clear active selection state, and clear visual primitives."""
        self._renderer.clear()
        if not self.isVisible():
            return

        self._is_dragging = False
        self._start_pos = None
        self._current_pos = None
        self._final_region = None
        self.hide()
        if self._on_dismissed is not None:
            self._on_dismissed()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle Escape key to immediately dismiss the overlay."""
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            event.accept()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Handle mouse press to start region selection."""
        if event.button() == Qt.MouseButton.LeftButton:
            self._start_pos = event.position().toPoint()
            self._current_pos = self._start_pos
            self._is_dragging = True
            self._final_region = None
            self.update()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Handle mouse move to update live rectangle preview."""
        if self._is_dragging:
            self._current_pos = event.position().toPoint()
            self.update()
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Handle mouse release to finalize the selected rectangle."""
        if event.button() == Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            self._current_pos = event.position().toPoint()

            if self._start_pos and self._target_geometry:
                # Compute normalized rectangle in overlay-local coordinates
                lx = min(self._start_pos.x(), self._current_pos.x())
                ly = min(self._start_pos.y(), self._current_pos.y())
                lw = abs(self._start_pos.x() - self._current_pos.x())
                lh = abs(self._start_pos.y() - self._current_pos.y())

                # Clamp to display bounds
                geom = self._target_geometry
                clamped_lx = max(0, min(geom.width, lx))
                clamped_ly = max(0, min(geom.height, ly))
                clamped_lw = max(0, min(geom.width - clamped_lx, lw))
                clamped_lh = max(0, min(geom.height - clamped_ly, lh))

                # Check minimum selection threshold
                if (
                    clamped_lw >= self.MIN_SELECTION_SIZE
                    and clamped_lh >= self.MIN_SELECTION_SIZE
                ):
                    # Convert to global desktop coordinates for SelectedRegion contract
                    global_x = geom.x + clamped_lx
                    global_y = geom.y + clamped_ly

                    region = SelectedRegion(
                        x=global_x,
                        y=global_y,
                        width=clamped_lw,
                        height=clamped_lh,
                        display_geometry=geom,
                    )
                    self._final_region = region
                    logger.info(
                        "Region selected: local=(%d, %d, %d, %d), global=(%d, %d), normalized=%s",
                        clamped_lx,
                        clamped_ly,
                        clamped_lw,
                        clamped_lh,
                        global_x,
                        global_y,
                        region.to_normalized(),
                    )
                    if self._on_region_selected is not None:
                        self._on_region_selected(region)
                else:
                    logger.debug(
                        "Selection ignored (smaller than %dpx minimum threshold).",
                        self.MIN_SELECTION_SIZE,
                    )
                    self._final_region = None

            self.update()
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:
        """Render the translucent overlay background and selection rectangle, or visual primitives."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # If visual explanation primitives are active, draw them directly above the source application
        if self._renderer.has_visuals():
            self._renderer.paint(painter)

            # If user selected a region, draw a subtle indicator outline
            if self._final_region and self._target_geometry:
                geom = self._target_geometry
                lx = self._final_region.x - geom.x
                ly = self._final_region.y - geom.y
                subtle_rect = QRect(
                    lx, ly, self._final_region.width, self._final_region.height
                )
                painter.setPen(QPen(QColor(66, 133, 244, 160), 1.5, Qt.PenStyle.DashLine))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(subtle_rect)
            return

        # Translucent backdrop tint confirming overlay active state
        painter.fillRect(self.rect(), QColor(0, 0, 0, 35))

        # Top-center hint badge: "Drag to select region • Press Esc to cancel"
        self._draw_hint_badge(painter)

        # Active dragging preview or completed selection rectangle
        rect_to_draw: Optional[QRect] = None
        if self._is_dragging and self._start_pos and self._current_pos:
            lx = min(self._start_pos.x(), self._current_pos.x())
            ly = min(self._start_pos.y(), self._current_pos.y())
            lw = abs(self._start_pos.x() - self._current_pos.x())
            lh = abs(self._start_pos.y() - self._current_pos.y())
            rect_to_draw = QRect(lx, ly, lw, lh)
        elif self._final_region and self._target_geometry:
            geom = self._target_geometry
            lx = self._final_region.x - geom.x
            ly = self._final_region.y - geom.y
            rect_to_draw = QRect(
                lx, ly, self._final_region.width, self._final_region.height
            )

        if rect_to_draw and rect_to_draw.isValid():
            # Semi-transparent accent fill
            painter.fillRect(rect_to_draw, QColor(26, 115, 232, 45))

            # Crisp accent border
            pen = QPen(QColor(66, 133, 244), 2, Qt.PenStyle.SolidLine)
            painter.setPen(pen)
            painter.drawRect(rect_to_draw)

            # Dimensions indicator tag
            tag_text = f"{rect_to_draw.width()} × {rect_to_draw.height()}"
            self._draw_dimension_tag(painter, rect_to_draw, tag_text)

    def _draw_hint_badge(self, painter: QPainter) -> None:
        """Draw a subtle instructions badge at top center."""
        badge_text = "Drag to select region • Press Esc to cancel"
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        painter.setFont(font)

        badge_width = 320
        badge_height = 32
        bx = (self.width() - badge_width) // 2
        by = 24
        badge_rect = QRect(bx, by, badge_width, badge_height)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(32, 33, 36, 210))
        painter.drawRoundedRect(badge_rect, 16, 16)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, badge_text)

    def _draw_dimension_tag(
        self, painter: QPainter, rect: QRect, text: str
    ) -> None:
        """Draw dimension label near the top-left of the selection."""
        font = QFont()
        font.setPointSize(9)
        painter.setFont(font)

        tag_w = 80
        tag_h = 22
        tag_x = rect.left()
        tag_y = rect.top() - tag_h - 4
        if tag_y < 10:
            tag_y = rect.top() + 4

        tag_rect = QRect(tag_x, tag_y, tag_w, tag_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(26, 115, 232, 220))
        painter.drawRoundedRect(tag_rect, 4, 4)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(tag_rect, Qt.AlignmentFlag.AlignCenter, text)


class QtOverlayHost(OverlayHost):
    """PySide6 concrete implementation of the OverlayHost interface."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        self._overlay = RegionSelectionOverlay(parent)
        self._on_region_selected: Optional[Callable[[SelectedRegion], None]] = None
        self._on_dismissed: Optional[Callable[[], None]] = None

        self._overlay.set_callbacks(
            on_selected=self._handle_region_selected,
            on_dismissed=self._handle_dismissed,
        )

    def show(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Show overlay on target display."""
        geom = geometry or DisplayGeometry(width=1920, height=1080)
        self._overlay.show_for_geometry(geom)

    def dismiss(self) -> None:
        """Dismiss overlay."""
        self._overlay.dismiss()

    def hide(self) -> None:
        """Programmatically hide overlay without triggering dismissal callback."""
        self._overlay.hide()

    def is_visible(self) -> bool:
        """Return whether overlay is currently visible."""
        return self._overlay.isVisible()

    def set_on_region_selected(
        self, callback: Optional[Callable[[SelectedRegion], None]]
    ) -> None:
        self._on_region_selected = callback

    def set_on_dismissed(
        self, callback: Optional[Callable[[], None]]
    ) -> None:
        self._on_dismissed = callback

    @property
    def overlay(self) -> RegionSelectionOverlay:
        """Underlying PySide6 overlay widget."""
        return self._overlay

    def render_tutor_response(
        self,
        response: Any,
        geometry: Optional[DisplayGeometry] = None,
        selected_region: Optional[SelectedRegion] = None,
        relative_to_region: bool = False,
    ) -> None:
        """Render visual explanation primitives from a TutorResponse."""
        if not self.is_visible():
            self.show(geometry)
        self._overlay.render_tutor_response(
            response=response,
            geometry=geometry,
            selected_region=selected_region,
            relative_to_region=relative_to_region,
        )

    def clear_explanation(self) -> None:
        """Clear all active visual explanation primitives."""
        self._overlay.clear_explanation()

    def has_explanation(self) -> bool:
        """Return True if visual explanation primitives are currently rendered."""
        return self._overlay.has_explanation()

    def _handle_region_selected(self, region: SelectedRegion) -> None:
        if self._on_region_selected is not None:
            self._on_region_selected(region)

    def _handle_dismissed(self) -> None:
        if self._on_dismissed is not None:
            self._on_dismissed()
