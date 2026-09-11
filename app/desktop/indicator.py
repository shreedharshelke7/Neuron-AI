"""Visible capture / privacy indicator widget for Block 1."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app.capture.indicator import CaptureIndicator
from app.capture.model import DisplayGeometry

logger = logging.getLogger(__name__)


class CaptureIndicatorWidget(QWidget, CaptureIndicator):
    """Frameless always-on-top indicator shown during screen capture.

    Provides clear privacy feedback ('Neuron • Capturing screen…')
    without stealing focus or contaminating screenshots (via Win32
    WDA_EXCLUDEFROMCAPTURE affinity).
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        # Tool window without taskbar entry, non-focusable, always on top
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(8)

        # Red recording dot
        dot_label = QLabel("●", self)
        dot_label.setStyleSheet("color: #ea4335; font-size: 14px;")
        layout.addWidget(dot_label)

        # Status text
        text_label = QLabel("Neuron • Capturing screen…", self)
        font = QFont()
        font.setPointSize(10)
        font.setBold(True)
        text_label.setFont(font)
        text_label.setStyleSheet("color: #ffffff;")
        layout.addWidget(text_label)

        # Pill background styling
        self.setStyleSheet(
            "background-color: rgba(32, 33, 36, 230); "
            "border: 1px solid rgba(255, 255, 255, 40); "
            "border-radius: 18px;"
        )
        self.adjustSize()

    def show(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Position and show the indicator on the target display."""
        super().show()

        # Exclude from screen capture using Windows 10/11 Display Affinity
        if sys.platform == "win32":
            try:
                import ctypes

                # WDA_EXCLUDEFROMCAPTURE = 0x00000011 (17)
                res = ctypes.windll.user32.SetWindowDisplayAffinity(
                    int(self.winId()), 0x00000011
                )
                if not res:
                    logger.debug("SetWindowDisplayAffinity returned 0.")
            except Exception as e:
                logger.debug("Error setting window display affinity: %s", e)

        # Position at top-center of the specified display (or default screen)
        if geometry:
            x = geometry.x + (geometry.width - self.width()) // 2
            y = geometry.y + 40
            self.move(x, y)

    def hide(self) -> None:
        """Hide the indicator widget."""
        super().hide()

    def is_visible(self) -> bool:
        """Return whether the indicator widget is currently visible."""
        return self.isVisible()
