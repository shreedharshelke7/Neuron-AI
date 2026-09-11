"""Capture indicator interface for Block 1."""

from __future__ import annotations

from typing import Optional

from app.capture.model import DisplayGeometry


class CaptureIndicator:
    """Abstract interface for visible capture/privacy feedback."""

    def show(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Display the capture/privacy feedback indicator."""
        raise NotImplementedError

    def hide(self) -> None:
        """Dismiss/hide the capture/privacy feedback indicator."""
        raise NotImplementedError

    def is_visible(self) -> bool:
        """Return whether the indicator is currently visible."""
        raise NotImplementedError


class StubCaptureIndicator(CaptureIndicator):
    """Placeholder indicator for unit tests and headless environments."""

    def __init__(self) -> None:
        self._visible: bool = False

    def show(self, geometry: Optional[DisplayGeometry] = None) -> None:
        self._visible = True

    def hide(self) -> None:
        self._visible = False

    def is_visible(self) -> bool:
        return self._visible
