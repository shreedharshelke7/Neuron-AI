"""PySide6 desktop screen capture service implementation for Block 1."""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor, QGuiApplication, QScreen

from app.capture.model import CapturedScreen, DisplayGeometry
from app.capture.service import CaptureService

logger = logging.getLogger(__name__)


class QtScreenCaptureService(CaptureService):
    """Captures the active screen or display containing user context using PySide6.

    Captures occur strictly on-demand after explicit activation.
    Screenshots are held ephemerally in memory by default.
    """

    def __init__(self) -> None:
        pass

    def _determine_target_screen(self) -> QScreen:
        """Deterministically select the screen containing active user context."""
        # 1. Prefer screen of the active/foreground application window on Windows
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes

                user32 = ctypes.windll.user32
                hwnd = user32.GetForegroundWindow()
                if hwnd:
                    rect = wintypes.RECT()
                    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                        center_x = (rect.left + rect.right) // 2
                        center_y = (rect.top + rect.bottom) // 2
                        screen = QGuiApplication.screenAt(
                            QPoint(center_x, center_y)
                        )
                        if screen is not None:
                            return screen
            except Exception as ex:
                logger.debug("Foreground window query failed: %s", ex)

        # 2. Fallback: Display containing the mouse cursor
        cursor_pos = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor_pos)
        if screen is not None:
            return screen

        # 3. Fallback: Primary display
        primary = QGuiApplication.primaryScreen()
        if primary is not None:
            return primary

        raise RuntimeError("No active screen found for capture.")

    def capture_current_screen(self) -> CapturedScreen:
        """Capture the screen containing the active user context."""
        screen = self._determine_target_screen()
        geom = screen.geometry()
        dpr = screen.devicePixelRatio()
        dpi = screen.logicalDotsPerInch()
        screen_name = screen.name()

        # Capture target screen contents
        pixmap = screen.grabWindow(0, geom.x(), geom.y(), geom.width(), geom.height())
        if pixmap.isNull():
            raise RuntimeError(
                f"Screen capture returned null pixmap for display {screen_name}."
            )

        display_geom = DisplayGeometry(
            x=geom.x(),
            y=geom.y(),
            width=geom.width(),
            height=geom.height(),
            device_pixel_ratio=dpr,
        )

        capture_timestamp = time.time()
        captured = CapturedScreen(
            image_data=pixmap,
            geometry=display_geom,
            display_id=screen_name,
            dpi=dpi,
            device_pixel_ratio=dpr,
            pixel_width=pixmap.width(),
            pixel_height=pixmap.height(),
            timestamp=capture_timestamp,
        )

        # Optional debug persistence strictly behind NEURON_DEBUG_SAVE_CAPTURE=1
        if os.environ.get("NEURON_DEBUG_SAVE_CAPTURE") == "1":
            try:
                captures_dir = Path("captures")
                captures_dir.mkdir(exist_ok=True)
                file_name = (
                    f"debug_capture_{int(capture_timestamp * 1000)}.png"
                )
                file_path = captures_dir / file_name
                pixmap.save(str(file_path))
                logger.info("Debug screenshot saved to %s", file_path)
            except Exception as e:
                logger.warning("Failed to save debug screenshot: %s", e)

        return captured
