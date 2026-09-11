"""Siri-like animated listening and thinking indicator widget (Block 9).

Provides:
- ListeningIndicator: Abstract protocol for listening/thinking visualization.
- StubListeningIndicator: In-memory headless implementation for hermetic tests.
- ListeningOrbWidget: High-polish, translucent, frameless PySide6 assistant orb
  providing glowing breathing pulses during LISTENING and a swirling morphing
  gradient during THINKING without stealing keyboard or window focus.
"""

from __future__ import annotations

import logging
import math
import sys
from enum import Enum
from typing import Any, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from app.capture.model import DisplayGeometry
from app.session.indicator import ListeningIndicator, OrbState, StubListeningIndicator

logger = logging.getLogger(__name__)


class ListeningOrbWidget(QWidget, ListeningIndicator):
    """Modern, subtle assistant orb visual indicator (Block 9).

    Guarantees:
    - Zero focus stealing: WA_ShowWithoutActivating + WindowDoesNotAcceptFocus.
    - Captures safe: Excluded via Win32 SetWindowDisplayAffinity.
    - Zero background timer CPU cost: Timer runs strictly during LISTENING/THINKING.
    - Multi-monitor positioning: Positioned at bottom-center of active display.
    """

    WIDTH = 140
    HEIGHT = 140

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._state: OrbState = OrbState.OFF
        self._phase: float = 0.0
        self._rotation_angle: float = 0.0
        self._amplitude: float = 0.0
        self._smooth_amplitude: float = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(25)  # 40 FPS
        self._timer.timeout.connect(self._on_animation_tick)

        self._init_window()

    def _init_window(self) -> None:
        """Configure non-focus-stealing, transparent, always-on-top window properties."""
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        # OS-level screenshot exclusion (Windows 10 2004+ / Windows 11)
        if sys.platform == "win32":
            try:
                import ctypes

                # WDA_EXCLUDEFROMCAPTURE = 0x00000011 (17)
                ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x00000011)
            except Exception as ex:
                logger.debug("SetWindowDisplayAffinity not available: %s", ex)

    def position_on_screen(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Position orb at the bottom-center of the active display with safe margins."""
        target_x: int
        target_y: int

        if geometry is not None and geometry.width > 0:
            target_x = geometry.x + (geometry.width - self.width()) // 2
            target_y = geometry.y + geometry.height - self.height() - 50
        else:
            # Detect screen under cursor or primary display
            screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                target_x = avail.x() + (avail.width() - self.width()) // 2
                target_y = avail.y() + avail.height() - self.height() - 50
            else:
                target_x = (1920 - self.width()) // 2
                target_y = 1080 - self.height() - 50

        self.move(target_x, target_y)

    def show_listening(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Display assistant orb in LISTENING mode with gentle breathing animation."""
        self._state = OrbState.LISTENING
        self.position_on_screen(geometry)
        super().show()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def show_thinking(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Transition assistant orb into THINKING mode with rotating reasoning gradient."""
        self._state = OrbState.THINKING
        if not self.isVisible():
            self.position_on_screen(geometry)
            super().show()
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def hide(self) -> None:
        """Hide the orb and stop animation timer completely."""
        self._state = OrbState.OFF
        self._amplitude = 0.0
        self._smooth_amplitude = 0.0
        if self._timer.isActive():
            self._timer.stop()
        super().hide()

    def is_visible(self) -> bool:
        """Return True if the orb is currently visible."""
        return self.isVisible()

    def set_amplitude(self, amp: float) -> None:
        """Supply transient microphone amplitude without saving audio data."""
        self._amplitude = max(0.0, min(1.0, float(amp)))

    def get_state(self) -> OrbState:
        """Return current visual state."""
        return self._state

    def _on_animation_tick(self) -> None:
        """Update animation phase parameters each frame."""
        self._phase += 0.08
        self._rotation_angle = (self._rotation_angle + 2.5) % 360.0

        # Smooth amplitude decay
        self._smooth_amplitude = (self._smooth_amplitude * 0.82) + (self._amplitude * 0.18)
        self._amplitude = max(0.0, self._amplitude * 0.70)

        self.update()

    def paintEvent(self, event: Any) -> None:
        """Render the Siri-inspired glowing sphere assistant orb."""
        if self._state == OrbState.OFF:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        if self._state == OrbState.LISTENING:
            self._draw_listening_orb(painter, cx, cy)
        elif self._state == OrbState.THINKING:
            self._draw_thinking_orb(painter, cx, cy)

        painter.end()

    def _draw_listening_orb(self, painter: QPainter, cx: float, cy: float) -> None:
        """Draw breathing glowing sphere with audio-reactive energy."""
        # Pulse calculation (subtle sine wave + smoothed voice amplitude)
        pulse = math.sin(self._phase)
        base_radius = 28.0
        effective_radius = base_radius + (3.0 * pulse) + (10.0 * self._smooth_amplitude)
        outer_glow_radius = effective_radius * 1.8

        # 1. Outer ambient radial glow
        glow_grad = QRadialGradient(QPointF(cx, cy), outer_glow_radius)
        glow_grad.setColorAt(0.0, QColor(0, 210, 255, 75))
        glow_grad.setColorAt(0.5, QColor(127, 0, 255, 25))
        glow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow_grad))
        painter.drawEllipse(QRectF(cx - outer_glow_radius, cy - outer_glow_radius, outer_glow_radius * 2, outer_glow_radius * 2))

        # 2. Main spherical volume (focal point offset for 3D sphere illusion)
        core_grad = QRadialGradient(QPointF(cx - (effective_radius * 0.35), cy - (effective_radius * 0.35)), effective_radius * 1.4)
        core_grad.setColorAt(0.0, QColor(210, 245, 255, 240))  # Bright top-left specular center
        core_grad.setColorAt(0.25, QColor(0, 210, 255, 220))   # Vibrant cyan
        core_grad.setColorAt(0.65, QColor(58, 123, 213, 210))  # Deep azure
        core_grad.setColorAt(0.95, QColor(127, 0, 255, 190))   # Electric violet
        core_grad.setColorAt(1.0, QColor(20, 10, 60, 160))     # Shadow rim

        painter.setBrush(QBrush(core_grad))
        painter.drawEllipse(QRectF(cx - effective_radius, cy - effective_radius, effective_radius * 2, effective_radius * 2))

        # 3. Translucent glass rim highlight
        rim_pen = QPen(QColor(255, 255, 255, 90))
        rim_pen.setWidthF(1.2)
        painter.setPen(rim_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - effective_radius, cy - effective_radius, effective_radius * 2, effective_radius * 2))

    def _draw_thinking_orb(self, painter: QPainter, cx: float, cy: float) -> None:
        """Draw rotating, morphing gradient sphere indicating active AI reasoning."""
        radius = 29.0 + (2.0 * math.sin(self._phase * 1.5))
        outer_glow_radius = radius * 1.7

        # 1. Swirling outer aura
        aura_grad = QRadialGradient(QPointF(cx, cy), outer_glow_radius)
        aura_grad.setColorAt(0.0, QColor(162, 155, 254, 80))
        aura_grad.setColorAt(0.6, QColor(108, 92, 231, 30))
        aura_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(aura_grad))
        painter.drawEllipse(QRectF(cx - outer_glow_radius, cy - outer_glow_radius, outer_glow_radius * 2, outer_glow_radius * 2))

        # 2. Rotating linear gradient across the core sphere
        rad = math.radians(self._rotation_angle)
        dx = radius * math.cos(rad)
        dy = radius * math.sin(rad)

        think_grad = QLinearGradient(QPointF(cx - dx, cy - dy), QPointF(cx + dx, cy + dy))
        think_grad.setColorAt(0.0, QColor(0, 206, 201, 230))   # Turquoise
        think_grad.setColorAt(0.35, QColor(108, 92, 231, 230)) # Purple
        think_grad.setColorAt(0.70, QColor(253, 121, 168, 220))# Soft rose
        think_grad.setColorAt(1.0, QColor(162, 155, 254, 230)) # Lavender

        painter.setBrush(QBrush(think_grad))
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        # 3. Inner pulsing core dot
        inner_core_r = radius * 0.45
        inner_grad = QRadialGradient(QPointF(cx, cy), inner_core_r)
        inner_grad.setColorAt(0.0, QColor(255, 255, 255, 220))
        inner_grad.setColorAt(0.7, QColor(255, 255, 255, 60))
        inner_grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(QBrush(inner_grad))
        painter.drawEllipse(QRectF(cx - inner_core_r, cy - inner_core_r, inner_core_r * 2, inner_core_r * 2))

        # 4. Thin glass rim
        rim_pen = QPen(QColor(255, 255, 255, 110))
        rim_pen.setWidthF(1.0)
        painter.setPen(rim_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
