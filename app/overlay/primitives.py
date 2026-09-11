"""Visual overlay primitives for Block 4.

Renders lightweight, high-contrast pedagogical visual elements directly on top
of the user's screen using PySide6 QPainter.
Supported primitives:
- HIGHLIGHT: focus bounding box with rounded corners and translucent fill
- ARROW: directed vector pointer with arrowhead and zero-division protection
- TEXT: annotation callout chip
- CARD: structured callout card with title, body, and safe fallback placement
- EQUATION: math formula card with clean Unicode conversion
- FallbackSummaryCard: concise summary card when visual plan is empty or fails
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from typing import Optional

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QPolygon,
)

from app.capture.model import DisplayGeometry
from app.overlay.geometry import MappedArrow, MappedPoint, MappedRect


def parse_color(color_str: Optional[str], default: QColor) -> QColor:
    """Safely parse a color string into a QColor, returning default on failure."""
    if not color_str:
        return default
    s = color_str.strip()
    if not s:
        return default

    # Named color mapping
    named = {
        "blue": QColor(66, 133, 244),
        "red": QColor(234, 67, 53),
        "green": QColor(52, 168, 83),
        "yellow": QColor(251, 188, 4),
        "gold": QColor(255, 215, 0),
        "orange": QColor(255, 112, 67),
        "purple": QColor(161, 66, 244),
        "cyan": QColor(0, 229, 255),
        "magenta": QColor(233, 30, 99),
        "white": QColor(255, 255, 255),
    }
    if s.lower() in named:
        return named[s.lower()]

    try:
        c = QColor(s)
        if c.isValid():
            return c
    except Exception:
        pass
    return default


def latex_to_readable_math(latex: Optional[str]) -> str:
    """Convert common LaTeX math expressions into clean readable Unicode math."""
    if not latex:
        return ""
    text = latex.strip()
    # Strip enclosing $ or $$ delimiters
    if text.startswith("$$") and text.endswith("$$"):
        text = text[2:-2].strip()
    elif text.startswith("$") and text.endswith("$"):
        text = text[1:-1].strip()

    # Common replacements
    replacements = [
        (r"\\frac\{([^}]+)\}\{([^}]+)\}", r"(\1)/(\2)"),
        (r"\\sqrt\{([^}]+)\}", r"√(\1)"),
        (r"\\times", "×"),
        (r"\\cdot", "·"),
        (r"\\approx", "≈"),
        (r"\\leq", "≤"),
        (r"\\le", "≤"),
        (r"\\geq", "≥"),
        (r"\\ge", "≥"),
        (r"\\neq", "≠"),
        (r"\\pm", "±"),
        (r"\\infty", "∞"),
        (r"\\partial", "∂"),
        (r"\\int", "∫"),
        (r"\\sum", "∑"),
        (r"\\alpha", "α"),
        (r"\\beta", "β"),
        (r"\\gamma", "γ"),
        (r"\\delta", "δ"),
        (r"\\Delta", "Δ"),
        (r"\\theta", "θ"),
        (r"\\lambda", "λ"),
        (r"\\mu", "μ"),
        (r"\\pi", "π"),
        (r"\\sigma", "σ"),
        (r"\\to", "→"),
        (r"\\rightarrow", "→"),
        (r"\\lim_\{([^}]+)\}", r"lim(\1)"),
        (r"\^2", "²"),
        (r"\^3", "³"),
        (r"\^4", "⁴"),
        (r"\^n", "ⁿ"),
        (r"\^x", "ˣ"),
        (r"_0", "₀"),
        (r"_1", "₁"),
        (r"_2", "₂"),
        (r"_n", "ₙ"),
        (r"_x", "ₓ"),
        (r"_i", "ᵢ"),
        (r"\\left\(", "("),
        (r"\\right\)", ")"),
        (r"\\left\[", "["),
        (r"\\right\]", "]"),
        (r"\\text\{([^}]+)\}", r"\1"),
        (r"\\mathrm\{([^}]+)\}", r"\1"),
        (r"\\mathbf\{([^}]+)\}", r"\1"),
    ]

    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text)

    return text


class OverlayPrimitive(ABC):
    """Abstract base class for all Block 4 visual overlay primitives."""

    @abstractmethod
    def paint(self, painter: QPainter) -> None:
        """Render primitive using Qt QPainter."""
        ...


class HighlightPrimitive(OverlayPrimitive):
    """HIGHLIGHT primitive: bounding focus box with translucent fill and crisp border."""

    def __init__(
        self,
        rect: MappedRect,
        label: Optional[str] = None,
        color: Optional[str] = None,
    ) -> None:
        self.rect: MappedRect = rect
        self.label: Optional[str] = label
        self.color_str: Optional[str] = color

    def paint(self, painter: QPainter) -> None:
        if self.rect.width <= 0 or self.rect.height <= 0:
            return

        base_color = parse_color(self.color_str, QColor(66, 133, 244))
        fill_color = QColor(base_color.red(), base_color.green(), base_color.blue(), 38)

        # Translucent focus fill
        painter.fillRect(self.rect.qrect, fill_color)

        # Crisp rounded border
        pen = QPen(base_color, 2.5, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(self.rect.qrect, 6, 6)

        # Optional label tag
        if self.label and self.label.strip():
            self._draw_label(painter, base_color)

    def _draw_label(self, painter: QPainter, accent_color: QColor) -> None:
        text = self.label.strip()
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        painter.setFont(font)

        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(text)
        badge_w = text_w + 16
        badge_h = fm.height() + 8

        # Place label badge directly above the top-left of the highlight
        bx = self.rect.local_x
        by = self.rect.local_y - badge_h - 4
        if by < 8:
            by = self.rect.local_y + 4  # Place inside if near screen top

        badge_rect = QRect(bx, by, badge_w, badge_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(32, 33, 36, 225))
        painter.drawRoundedRect(badge_rect, 4, 4)

        # Accent border indicator
        painter.setPen(QPen(accent_color, 1.5))
        painter.drawRoundedRect(badge_rect, 4, 4)

        # Label text
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)


class ArrowPrimitive(OverlayPrimitive):
    """ARROW primitive: directed vector pointer with arrowhead and zero-division protection."""

    def __init__(
        self,
        arrow: MappedArrow,
        label: Optional[str] = None,
        color: Optional[str] = None,
    ) -> None:
        self.arrow: MappedArrow = arrow
        self.label: Optional[str] = label
        self.color_str: Optional[str] = color

    def paint(self, painter: QPainter) -> None:
        color = parse_color(self.color_str, QColor(234, 67, 53))  # Vibrant coral red / accent
        length = self.arrow.length

        # Safe zero-division and short-arrow protection
        if length < 6.0 or not math.isfinite(length):
            # Render a neat target dot at destination
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(
                QPoint(self.arrow.end.local_x, self.arrow.end.local_y), 5, 5
            )
            return

        # Vector normalization
        dx = (self.arrow.end.local_x - self.arrow.start.local_x) / length
        dy = (self.arrow.end.local_y - self.arrow.start.local_y) / length

        # Arrowhead dimensions
        head_len = min(18.0, max(8.0, length * 0.35))
        head_width = min(9.0, max(5.0, length * 0.2))

        # Shaft line: pull back end point slightly so it doesn't poke out of arrowhead
        shaft_end_x = self.arrow.end.local_x - dx * (head_len * 0.5)
        shaft_end_y = self.arrow.end.local_y - dy * (head_len * 0.5)

        pen = QPen(color, 2.5, Qt.PenStyle.SolidLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(
            self.arrow.start.local_x,
            self.arrow.start.local_y,
            int(round(shaft_end_x)),
            int(round(shaft_end_y)),
        )

        # Arrowhead polygon
        tip_x = float(self.arrow.end.local_x)
        tip_y = float(self.arrow.end.local_y)
        base_x = tip_x - dx * head_len
        base_y = tip_y - dy * head_len
        nx = -dy
        ny = dx

        w1_x = base_x + nx * head_width
        w1_y = base_y + ny * head_width
        w2_x = base_x - nx * head_width
        w2_y = base_y - ny * head_width

        arrow_head = QPolygon([
            QPoint(int(round(tip_x)), int(round(tip_y))),
            QPoint(int(round(w1_x)), int(round(w1_y))),
            QPoint(int(round(w2_x)), int(round(w2_y))),
        ])

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(color))
        painter.drawPolygon(arrow_head)

        # Optional label chip near arrow midpoint
        if self.label and self.label.strip():
            self._draw_label(painter, color)

    def _draw_label(self, painter: QPainter, accent_color: QColor) -> None:
        text = self.label.strip()
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        painter.setFont(font)

        fm = QFontMetrics(font)
        text_w = fm.horizontalAdvance(text)
        badge_w = text_w + 14
        badge_h = fm.height() + 6

        # Position label near midpoint of the arrow
        mid_x = (self.arrow.start.local_x + self.arrow.end.local_x) // 2
        mid_y = (self.arrow.start.local_y + self.arrow.end.local_y) // 2
        bx = mid_x - badge_w // 2
        by = mid_y - badge_h - 6

        badge_rect = QRect(bx, by, badge_w, badge_h)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(32, 33, 36, 220))
        painter.drawRoundedRect(badge_rect, 4, 4)

        painter.setPen(QPen(accent_color, 1))
        painter.drawRoundedRect(badge_rect, 4, 4)

        painter.setPen(QColor(255, 255, 255))
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, text)


class TextPrimitive(OverlayPrimitive):
    """TEXT primitive: educational annotation callout note."""

    def __init__(
        self,
        rect: Optional[MappedRect] = None,
        point: Optional[MappedPoint] = None,
        text: str = "",
        color: Optional[str] = None,
    ) -> None:
        self.rect: Optional[MappedRect] = rect
        self.point: Optional[MappedPoint] = point
        self.text: str = text or ""
        self.color_str: Optional[str] = color

    def paint(self, painter: QPainter) -> None:
        clean_text = self.text.strip()
        if not clean_text:
            return

        accent_color = parse_color(self.color_str, QColor(66, 133, 244))
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        fm = QFontMetrics(font)

        padding_x = 12
        padding_y = 8

        if self.rect and self.rect.width > 30 and self.rect.height > 20:
            box = self.rect.qrect
        elif self.point:
            text_w = min(400, max(120, fm.horizontalAdvance(clean_text) + padding_x * 2))
            text_h = fm.height() + padding_y * 2
            box = QRect(self.point.local_x, self.point.local_y, text_w, text_h)
        elif self.rect:
            text_w = min(400, max(120, fm.horizontalAdvance(clean_text) + padding_x * 2))
            text_h = fm.height() + padding_y * 2
            box = QRect(self.rect.local_x, self.rect.local_y, text_w, text_h)
        else:
            return

        # Background bubble
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(32, 33, 36, 230))
        painter.drawRoundedRect(box, 6, 6)

        # Accent indicator border
        painter.setPen(QPen(accent_color, 1.5))
        painter.drawRoundedRect(box, 6, 6)

        # Text inside
        text_rect = box.adjusted(padding_x, padding_y, -padding_x, -padding_y)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap,
            clean_text,
        )


class CardPrimitive(OverlayPrimitive):
    """CARD primitive: structured pedagogical callout card with title, body, and safe fallback."""

    def __init__(
        self,
        rect: Optional[MappedRect] = None,
        title: Optional[str] = None,
        text: Optional[str] = None,
        color: Optional[str] = None,
        display_geometry: Optional[DisplayGeometry] = None,
    ) -> None:
        self.rect: Optional[MappedRect] = rect
        self.title: Optional[str] = title
        self.text: Optional[str] = text or ""
        self.color_str: Optional[str] = color
        self.display_geometry: Optional[DisplayGeometry] = display_geometry

    def paint(self, painter: QPainter) -> None:
        accent_color = parse_color(self.color_str, QColor(66, 133, 244))
        geom = self.display_geometry or DisplayGeometry(width=1920, height=1080)

        card_width = 380
        card_min_height = 140

        # Safe placement: use rect if specified and large enough, else fallback
        if self.rect and self.rect.width >= 120 and self.rect.height >= 80:
            box = self.rect.qrect
        else:
            # Fallback placement: top-right with safe margins
            bx = max(24, geom.width - card_width - 32)
            by = 64
            box = QRect(bx, by, card_width, card_min_height)

        # Card container background: dark acrylic
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(30, 31, 34, 240))
        painter.drawRoundedRect(box, 10, 10)

        # Subtle card border
        painter.setPen(QPen(accent_color, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 10, 10)

        inner_rect = box.adjusted(16, 14, -16, -14)
        current_y = inner_rect.top()

        # Title section
        if self.title and self.title.strip():
            title_font = QFont("Segoe UI", 11)
            title_font.setBold(True)
            painter.setFont(title_font)
            painter.setPen(QColor(138, 180, 248))  # Light Google blue

            fm_title = QFontMetrics(title_font)
            title_h = fm_title.height()
            title_rect = QRect(inner_rect.left(), current_y, inner_rect.width(), title_h)
            painter.drawText(title_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.title.strip())

            current_y += title_h + 8

            # Divider line
            painter.setPen(QPen(QColor(60, 64, 67), 1))
            painter.drawLine(inner_rect.left(), current_y, inner_rect.right(), current_y)
            current_y += 8

        # Body section
        if self.text and self.text.strip():
            body_font = QFont("Segoe UI", 10)
            painter.setFont(body_font)
            painter.setPen(QColor(232, 234, 237))

            body_rect = QRect(inner_rect.left(), current_y, inner_rect.width(), inner_rect.bottom() - current_y)
            painter.drawText(
                body_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                self.text.strip(),
            )


class EquationPrimitive(OverlayPrimitive):
    """EQUATION primitive: formatted mathematical expression card."""

    def __init__(
        self,
        rect: Optional[MappedRect] = None,
        point: Optional[MappedPoint] = None,
        expression: str = "",
        label: Optional[str] = None,
        color: Optional[str] = None,
        display_geometry: Optional[DisplayGeometry] = None,
    ) -> None:
        self.rect: Optional[MappedRect] = rect
        self.point: Optional[MappedPoint] = point
        self.expression: str = expression or ""
        self.label: Optional[str] = label
        self.color_str: Optional[str] = color
        self.display_geometry: Optional[DisplayGeometry] = display_geometry

    def paint(self, painter: QPainter) -> None:
        clean_expr = latex_to_readable_math(self.expression)
        if not clean_expr:
            return

        accent_color = parse_color(self.color_str, QColor(52, 168, 83))  # Emerald green math accent
        geom = self.display_geometry or DisplayGeometry(width=1920, height=1080)

        math_font = QFont("Cambria Math", 13)
        math_font.setStyleHint(QFont.StyleHint.Serif)
        fm_math = QFontMetrics(math_font)

        padding_x = 18
        padding_y = 12

        math_w = max(180, fm_math.horizontalAdvance(clean_expr) + padding_x * 2)
        has_label = bool(self.label and self.label.strip())
        math_h = fm_math.height() + padding_y * 2 + (20 if has_label else 0)

        if self.rect and self.rect.width >= 100 and self.rect.height >= 40:
            box = self.rect.qrect
        elif self.point:
            box = QRect(self.point.local_x, self.point.local_y, math_w, math_h)
        else:
            # Fallback placement: center-top
            bx = max(24, (geom.width - math_w) // 2)
            by = 72
            box = QRect(bx, by, math_w, math_h)

        # Card container background
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(26, 27, 30, 245))
        painter.drawRoundedRect(box, 8, 8)

        # Border
        painter.setPen(QPen(accent_color, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 8, 8)

        inner = box.adjusted(padding_x, padding_y, -padding_x, -padding_y)
        current_y = inner.top()

        # Optional label
        if has_label:
            lbl_font = QFont("Segoe UI", 9)
            lbl_font.setBold(True)
            painter.setFont(lbl_font)
            painter.setPen(accent_color)
            lbl_h = QFontMetrics(lbl_font).height()
            lbl_rect = QRect(inner.left(), current_y, inner.width(), lbl_h)
            painter.drawText(lbl_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.label.strip())
            current_y += lbl_h + 4

        # Equation expression
        painter.setFont(math_font)
        painter.setPen(QColor(255, 255, 255))
        expr_rect = QRect(inner.left(), current_y, inner.width(), inner.bottom() - current_y)
        painter.drawText(
            expr_rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            clean_expr,
        )


class FallbackSummaryCard(OverlayPrimitive):
    """SRS FR-16 fallback card displaying concise summary and follow-up when visual plan is empty or fails."""

    def __init__(
        self,
        summary: str,
        follow_up: Optional[str] = None,
        display_geometry: Optional[DisplayGeometry] = None,
    ) -> None:
        self.summary: str = summary or ""
        self.follow_up: Optional[str] = follow_up
        self.display_geometry: Optional[DisplayGeometry] = display_geometry

    def paint(self, painter: QPainter) -> None:
        geom = self.display_geometry or DisplayGeometry(width=1920, height=1080)
        card_w = min(440, max(300, geom.width - 48))
        card_min_h = 130

        # Safe placement: top-right with 24px margin
        bx = max(24, geom.width - card_w - 24)
        by = 54
        box = QRect(bx, by, card_w, card_min_h)

        # Acrylic container
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(24, 25, 28, 245))
        painter.drawRoundedRect(box, 10, 10)

        # Blue accent border
        accent_color = QColor(66, 133, 244)
        painter.setPen(QPen(accent_color, 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(box, 10, 10)

        inner = box.adjusted(16, 14, -16, -14)

        # Header tag: "Neuron Tutor"
        badge_font = QFont("Segoe UI", 9)
        badge_font.setBold(True)
        painter.setFont(badge_font)
        painter.setPen(accent_color)
        painter.drawText(
            QRect(inner.left(), inner.top(), inner.width(), 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            "Neuron Tutor",
        )

        current_y = inner.top() + 24

        # Summary text
        summary_font = QFont("Segoe UI", 10)
        painter.setFont(summary_font)
        painter.setPen(QColor(241, 243, 244))

        has_followup = bool(self.follow_up and self.follow_up.strip())
        summary_h = 60 if has_followup else (inner.bottom() - current_y)
        summary_rect = QRect(inner.left(), current_y, inner.width(), summary_h)
        painter.drawText(
            summary_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
            self.summary.strip(),
        )

        # Optional follow-up question
        if has_followup:
            current_y += 66
            follow_font = QFont("Segoe UI", 9)
            follow_font.setItalic(True)
            painter.setFont(follow_font)
            painter.setPen(QColor(138, 180, 248))

            follow_rect = QRect(inner.left(), current_y, inner.width(), inner.bottom() - current_y)
            painter.drawText(
                follow_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                f"Next: {self.follow_up.strip()}",
            )
