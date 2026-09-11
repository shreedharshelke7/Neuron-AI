"""Data representations for screen capture and regions in Block 1."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class DisplayGeometry:
    """Represents display dimensions, origin offsets, and device scale factors."""

    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0
    device_pixel_ratio: float = 1.0

    @property
    def pixel_width(self) -> int:
        """Physical pixel width under display scaling."""
        return int(round(self.width * self.device_pixel_ratio))

    @property
    def pixel_height(self) -> int:
        """Physical pixel height under display scaling."""
        return int(round(self.height * self.device_pixel_ratio))


@dataclass(frozen=True)
class SelectedRegion:
    """Represents a selected screen region in global desktop pixel coordinates.

    Allows derivation of normalized 0.0-1.0 coordinates conforming to Neuron's
    overlay contract as well as local logical and physical pixel coordinates.
    """

    x: int
    y: int
    width: int
    height: int
    display_geometry: Optional[DisplayGeometry] = None

    def to_normalized(
        self, geometry: Optional[DisplayGeometry] = None
    ) -> Tuple[float, float, float, float]:
        """Derive normalized (0.0 - 1.0) coordinates (nx, ny, nw, nh).

        Uses provided geometry, or falls back to self.display_geometry.
        Coordinates are safely clamped to the captured screen bounds.
        Raises ValueError if no geometry is provided or dimensions are invalid.
        """
        geom = geometry or self.display_geometry
        if geom is None:
            raise ValueError(
                "Display geometry is required to derive normalized coordinates."
            )
        if geom.width <= 0 or geom.height <= 0:
            raise ValueError("Display geometry width and height must be positive.")

        # Calculate coordinates relative to the display origin
        rel_x = self.x - geom.x
        rel_y = self.y - geom.y

        nx = max(0.0, min(1.0, rel_x / geom.width))
        ny = max(0.0, min(1.0, rel_y / geom.height))
        nw = max(0.0, min(1.0 - nx, self.width / geom.width))
        nh = max(0.0, min(1.0 - ny, self.height / geom.height))

        return (nx, ny, nw, nh)

    def to_local_coordinates(
        self, geometry: Optional[DisplayGeometry] = None
    ) -> Tuple[int, int, int, int]:
        """Derive screen-local logical coordinates (lx, ly, lw, lh)."""
        geom = geometry or self.display_geometry
        if geom is None:
            return (self.x, self.y, self.width, self.height)
        return (self.x - geom.x, self.y - geom.y, self.width, self.height)

    def to_pixel_coordinates(
        self, geometry: Optional[DisplayGeometry] = None
    ) -> Tuple[int, int, int, int]:
        """Derive physical pixel coordinates on the captured image."""
        geom = geometry or self.display_geometry
        dpr = geom.device_pixel_ratio if geom else 1.0
        lx, ly, lw, lh = self.to_local_coordinates(geom)
        return (
            int(round(lx * dpr)),
            int(round(ly * dpr)),
            int(round(lw * dpr)),
            int(round(lh * dpr)),
        )


@dataclass
class CapturedScreen:
    """Container for screen capture data and metadata.

    Populates image reference, display geometry, display identifier,
    DPI, device pixel ratio, and capture timestamp.
    """

    image_data: Optional[Any] = None
    geometry: Optional[DisplayGeometry] = None
    display_id: Optional[str] = None
    dpi: Optional[float] = None
    device_pixel_ratio: float = 1.0
    pixel_width: int = 0
    pixel_height: int = 0
    timestamp: float = field(default_factory=time.time)
