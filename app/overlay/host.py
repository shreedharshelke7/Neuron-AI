"""Overlay host interface for Block 1.

Provides an abstraction boundary between the desktop shell and future Block 4
visual-rendering components.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Optional

from app.capture.model import DisplayGeometry, SelectedRegion

if TYPE_CHECKING:
    from app.tutor.model import TutorResponse


class OverlayHost(ABC):
    """Abstract interface for managing overlay presentation and region selection.

    Visual rendering and overlay primitives interact through this interface
    without direct dependency on PySide6 window implementations.
    """

    @abstractmethod
    def show(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Display the overlay surface over the target screen."""
        ...

    @abstractmethod
    def dismiss(self) -> None:
        """Dismiss/hide the overlay surface."""
        ...

    @abstractmethod
    def is_visible(self) -> bool:
        """Return whether the overlay surface is currently visible."""
        ...

    @abstractmethod
    def set_on_region_selected(
        self, callback: Optional[Callable[[SelectedRegion], None]]
    ) -> None:
        """Set callback invoked when a region is selected."""
        ...

    @abstractmethod
    def set_on_dismissed(
        self, callback: Optional[Callable[[], None]]
    ) -> None:
        """Set callback invoked when the overlay is dismissed."""
        ...

    def hide(self) -> None:
        """Programmatically hide the overlay without triggering user-dismissal callbacks."""
        pass

    def render_tutor_response(
        self,
        response: Any,
        geometry: Optional[DisplayGeometry] = None,
        selected_region: Optional[SelectedRegion] = None,
        relative_to_region: bool = False,
    ) -> None:
        """Render visual explanation primitives from a TutorResponse."""
        pass

    def clear_explanation(self) -> None:
        """Clear all rendered visual explanation primitives."""
        pass


class StubOverlayHost(OverlayHost):
    """Placeholder overlay host maintaining state without rendering."""

    def __init__(self) -> None:
        self._visible: bool = False
        self._on_region_selected: Optional[Callable[[SelectedRegion], None]] = None
        self._on_dismissed: Optional[Callable[[], None]] = None
        self._last_geometry: Optional[DisplayGeometry] = None
        self._last_rendered_response: Optional[Any] = None
        self._last_rendered_region: Optional[SelectedRegion] = None
        self._has_explanation: bool = False

    @property
    def last_geometry(self) -> Optional[DisplayGeometry]:
        return self._last_geometry

    @property
    def last_rendered_response(self) -> Optional[Any]:
        return self._last_rendered_response

    @property
    def has_explanation(self) -> bool:
        return self._has_explanation

    def show(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Mark overlay as visible."""
        self._visible = True
        self._last_geometry = geometry

    def hide(self) -> None:
        """Programmatically hide overlay without triggering user-dismissal callback."""
        self._visible = False
        self.clear_explanation()

    def dismiss(self) -> None:
        """Mark overlay as dismissed without recursion."""
        if not self._visible:
            self.clear_explanation()
            return
        self._visible = False
        self.clear_explanation()
        if self._on_dismissed is not None:
            self._on_dismissed()

    def is_visible(self) -> bool:
        """Check overlay visibility."""
        return self._visible

    def set_on_region_selected(
        self, callback: Optional[Callable[[SelectedRegion], None]]
    ) -> None:
        self._on_region_selected = callback

    def set_on_dismissed(
        self, callback: Optional[Callable[[], None]]
    ) -> None:
        self._on_dismissed = callback

    def simulate_selection(self, region: SelectedRegion) -> None:
        """Simulate a user selection for testing."""
        if self._on_region_selected is not None:
            self._on_region_selected(region)

    def render_tutor_response(
        self,
        response: Any,
        geometry: Optional[DisplayGeometry] = None,
        selected_region: Optional[SelectedRegion] = None,
        relative_to_region: bool = False,
    ) -> None:
        self._last_rendered_response = response
        self._last_rendered_region = selected_region
        if geometry is not None:
            self._last_geometry = geometry
        self._has_explanation = True

    def clear_explanation(self) -> None:
        self._last_rendered_response = None
        self._last_rendered_region = None
        self._has_explanation = False
