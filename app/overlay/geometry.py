"""Coordinate mapping system for Block 4 overlay rendering.

Maps normalized [0.0, 1.0] coordinates to Qt overlay-local and global desktop coordinates.
Handles arbitrary display resolutions, non-zero monitor origins, coordinate clamping,
and selected-region relative offsets without hardcoding dimensions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from PySide6.QtCore import QPoint, QRect
from app.capture.model import DisplayGeometry, SelectedRegion
from app.tutor.model import OverlayAction


@dataclass(frozen=True)
class MappedPoint:
    """Represents a coordinate point mapped to both overlay-local and global coordinates."""

    local_x: int
    local_y: int
    global_x: int
    global_y: int

    @property
    def qpoint(self) -> QPoint:
        """Qt QPoint in overlay-local coordinates for QPainter."""
        return QPoint(self.local_x, self.local_y)

    @property
    def global_qpoint(self) -> QPoint:
        """Qt QPoint in global desktop coordinates."""
        return QPoint(self.global_x, self.global_y)


@dataclass(frozen=True)
class MappedRect:
    """Represents a rectangle mapped to both overlay-local and global coordinates."""

    local_x: int
    local_y: int
    width: int
    height: int
    global_x: int
    global_y: int

    @property
    def qrect(self) -> QRect:
        """Qt QRect in overlay-local coordinates for QPainter."""
        return QRect(self.local_x, self.local_y, self.width, self.height)

    @property
    def global_qrect(self) -> QRect:
        """Qt QRect in global desktop coordinates."""
        return QRect(self.global_x, self.global_y, self.width, self.height)


@dataclass(frozen=True)
class MappedArrow:
    """Represents a directed arrow vector mapped to overlay coordinates."""

    start: MappedPoint
    end: MappedPoint

    @property
    def start_point(self) -> QPoint:
        return self.start.qpoint

    @property
    def end_point(self) -> QPoint:
        return self.end.qpoint

    @property
    def length(self) -> float:
        """Euclidean pixel length of the arrow shaft."""
        dx = self.end.local_x - self.start.local_x
        dy = self.end.local_y - self.start.local_y
        return math.hypot(dx, dy)


class CoordinateMapper:
    """Maps normalized [0.0, 1.0] coordinates to screen pixel coordinates.

    Supports:
    - Non-zero monitor origins (e.g. secondary monitors at x=1920 or negative x)
    - Varying resolutions (1920x1080, 2560x1440, 3840x2160, 1366x768, etc.)
    - Clamping and safe bounding against NaN / Inf / negative / out-of-range values
    - Full-screen or SelectedRegion-relative coordinate contexts
    - Zero double-scaling (Qt handles devicePixelRatio internally)
    """

    def __init__(
        self,
        display_geometry: Optional[DisplayGeometry] = None,
        selected_region: Optional[SelectedRegion] = None,
    ) -> None:
        self._display: DisplayGeometry = (
            display_geometry or DisplayGeometry(x=0, y=0, width=1920, height=1080)
        )
        self._selected_region: Optional[SelectedRegion] = selected_region

    @property
    def display_geometry(self) -> DisplayGeometry:
        return self._display

    @property
    def selected_region(self) -> Optional[SelectedRegion]:
        return self._selected_region

    @staticmethod
    def clamp_val(val: Optional[float], min_val: float = 0.0, max_val: float = 1.0) -> float:
        """Safely clamp a float value within bounds, returning min_val on NaN/Inf/None."""
        if val is None:
            return min_val
        try:
            f = float(val)
            if not math.isfinite(f):
                return min_val
            return max(min_val, min(max_val, f))
        except (ValueError, TypeError):
            return min_val

    def map_point(
        self,
        nx: float,
        ny: float,
        relative_to_region: bool = False,
    ) -> MappedPoint:
        """Map normalized (nx, ny) point to overlay-local and global pixel coordinates."""
        cnx = self.clamp_val(nx, 0.0, 1.0)
        cny = self.clamp_val(ny, 0.0, 1.0)

        disp_x = self._display.x
        disp_y = self._display.y
        disp_w = max(1, self._display.width)
        disp_h = max(1, self._display.height)

        if relative_to_region and self._selected_region is not None:
            reg = self._selected_region
            reg_w = max(1, reg.width)
            reg_h = max(1, reg.height)
            reg_local_x = reg.x - disp_x
            reg_local_y = reg.y - disp_y

            local_x = int(round(reg_local_x + cnx * reg_w))
            local_y = int(round(reg_local_y + cny * reg_h))
            global_x = int(round(reg.x + cnx * reg_w))
            global_y = int(round(reg.y + cny * reg_h))
        else:
            local_x = int(round(cnx * disp_w))
            local_y = int(round(cny * disp_h))
            global_x = int(round(disp_x + cnx * disp_w))
            global_y = int(round(disp_y + cny * disp_h))

        return MappedPoint(
            local_x=local_x,
            local_y=local_y,
            global_x=global_x,
            global_y=global_y,
        )

    def map_rect(
        self,
        nx: float,
        ny: float,
        nw: float,
        nh: float,
        relative_to_region: bool = False,
    ) -> MappedRect:
        """Map normalized bounding box [nx, ny, nw, nh] to overlay-local and global coordinates.

        Safely clamps coordinates so the rectangle cannot exceed context boundaries.
        """
        cnx = self.clamp_val(nx, 0.0, 1.0)
        cny = self.clamp_val(ny, 0.0, 1.0)
        cnw = self.clamp_val(nw, 0.0, 1.0 - cnx)
        cnh = self.clamp_val(nh, 0.0, 1.0 - cny)

        disp_x = self._display.x
        disp_y = self._display.y
        disp_w = max(1, self._display.width)
        disp_h = max(1, self._display.height)

        if relative_to_region and self._selected_region is not None:
            reg = self._selected_region
            reg_w = max(1, reg.width)
            reg_h = max(1, reg.height)
            reg_local_x = reg.x - disp_x
            reg_local_y = reg.y - disp_y

            local_x = int(round(reg_local_x + cnx * reg_w))
            local_y = int(round(reg_local_y + cny * reg_h))
            w = max(0, int(round(cnw * reg_w)))
            h = max(0, int(round(cnh * reg_h)))
            global_x = int(round(reg.x + cnx * reg_w))
            global_y = int(round(reg.y + cny * reg_h))
        else:
            local_x = int(round(cnx * disp_w))
            local_y = int(round(cny * disp_h))
            w = max(0, int(round(cnw * disp_w)))
            h = max(0, int(round(cnh * disp_h)))
            global_x = int(round(disp_x + cnx * disp_w))
            global_y = int(round(disp_y + cny * disp_h))

        return MappedRect(
            local_x=local_x,
            local_y=local_y,
            width=w,
            height=h,
            global_x=global_x,
            global_y=global_y,
        )

    def map_arrow(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        relative_to_region: bool = False,
    ) -> MappedArrow:
        """Map arrow vector [x1, y1, x2, y2] to start and end MappedPoints."""
        start = self.map_point(x1, y1, relative_to_region=relative_to_region)
        end = self.map_point(x2, y2, relative_to_region=relative_to_region)
        return MappedArrow(start=start, end=end)

    def map_action_rect(
        self,
        action: OverlayAction,
        relative_to_region: bool = False,
    ) -> Optional[MappedRect]:
        """Map target_normalized of an action to MappedRect, or None if invalid/missing."""
        if not action.target_normalized or len(action.target_normalized) != 4:
            return None
        nx, ny, nw, nh = action.target_normalized
        return self.map_rect(nx, ny, nw, nh, relative_to_region=relative_to_region)

    def map_action_arrow(
        self,
        action: OverlayAction,
        relative_to_region: bool = False,
    ) -> Optional[MappedArrow]:
        """Map target_normalized of an ARROW action to MappedArrow, or None if invalid/missing."""
        if not action.target_normalized or len(action.target_normalized) != 4:
            return None
        x1, y1, x2, y2 = action.target_normalized
        return self.map_arrow(x1, y1, x2, y2, relative_to_region=relative_to_region)
