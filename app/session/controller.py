"""Session Controller coordinating Block 1 interfaces and interaction lifecycle."""

from __future__ import annotations

import logging
from typing import Callable, List, Optional

from app.capture.indicator import CaptureIndicator, StubCaptureIndicator
from app.capture.model import CapturedScreen, SelectedRegion
from app.capture.service import CaptureService, StubCaptureService
from app.overlay.host import OverlayHost, StubOverlayHost
from app.session.state import SessionState
from app.trigger.activation import ActivationTrigger, StubActivationTrigger

logger = logging.getLogger(__name__)


class SessionController:
    """Central session controller for coordinating Block 1 components.

    Maintains lifecycle state (starting at IDLE) and coordinates activation,
    capture, and overlay host interfaces without coupling to GUI window classes.
    """

    def __init__(
        self,
        activation_trigger: Optional[ActivationTrigger] = None,
        capture_service: Optional[CaptureService] = None,
        overlay_host: Optional[OverlayHost] = None,
        capture_indicator: Optional[CaptureIndicator] = None,
        auto_capture: bool = False,
    ) -> None:
        self._state: SessionState = SessionState.IDLE
        self._auto_capture: bool = auto_capture
        self._dismissing: bool = False
        self._state_listeners: List[Callable[[SessionState], None]] = []
        self._region_listeners: List[Callable[[SelectedRegion], None]] = []

        self._current_capture: Optional[CapturedScreen] = None
        self._selected_region: Optional[SelectedRegion] = None

        self.capture_service: CaptureService = (
            capture_service or StubCaptureService()
        )
        self.overlay_host: OverlayHost = overlay_host or StubOverlayHost()
        self.capture_indicator: CaptureIndicator = (
            capture_indicator or StubCaptureIndicator()
        )
        self.activation_trigger: ActivationTrigger = (
            activation_trigger
            or StubActivationTrigger(on_activate=self.request_activation)
        )

        # Connect overlay callbacks
        self.overlay_host.set_on_region_selected(self.on_region_selected)
        self.overlay_host.set_on_dismissed(self.dismiss)

    @property
    def state(self) -> SessionState:
        """Current session lifecycle state."""
        return self._state

    @property
    def current_capture(self) -> Optional[CapturedScreen]:
        """Ephemeral captured screen data for the active session."""
        return self._current_capture

    @property
    def selected_region(self) -> Optional[SelectedRegion]:
        """Currently selected region geometry."""
        return self._selected_region

    def add_state_listener(self, listener: Callable[[SessionState], None]) -> None:
        """Register a callback invoked when the session state changes."""
        self._state_listeners.append(listener)

    def remove_state_listener(self, listener: Callable[[SessionState], None]) -> None:
        """Unregister a state listener callback."""
        if listener in self._state_listeners:
            self._state_listeners.remove(listener)

    def add_region_listener(
        self, listener: Callable[[SelectedRegion], None]
    ) -> None:
        """Register a callback invoked when a region is selected by the user."""
        self._region_listeners.append(listener)

    def remove_region_listener(
        self, listener: Callable[[SelectedRegion], None]
    ) -> None:
        """Unregister a region listener callback."""
        if listener in self._region_listeners:
            self._region_listeners.remove(listener)

    def _set_state(self, new_state: SessionState) -> None:
        if self._state != new_state:
            self._state = new_state
            for listener in list(self._state_listeners):
                try:
                    listener(self._state)
                except Exception as ex:
                    logger.exception("Error in state listener: %s", ex)

    def request_activation(self) -> None:
        """Handle an activation request from an activation trigger."""
        if self._state != SessionState.IDLE:
            logger.debug("Activation request ignored (current state: %s).", self._state)
            return

        self._set_state(SessionState.ACTIVATED)

        if self._auto_capture:
            self.begin_capture_flow()

    def begin_capture_flow(self) -> None:
        """Orchestrate the capture, indicator, and overlay display sequence."""
        # 1. Show capture indicator
        self.capture_indicator.show()
        self._set_state(SessionState.CAPTURING)

        try:
            # 2. Capture current screen
            captured = self.capture_service.capture_current_screen()
        except Exception as e:
            logger.exception("Screen capture failed: %s", e)
            self.capture_indicator.hide()
            self._set_state(SessionState.ERROR)
            self.reset_to_idle()
            return

        # 3. Dismiss capture indicator
        self.capture_indicator.hide()

        if captured is not None and captured.geometry is not None:
            self._current_capture = captured
            self._set_state(SessionState.SELECTING)
            # 4. Show transparent overlay
            self.overlay_host.show(geometry=captured.geometry)
        else:
            logger.warning("Screen capture produced invalid or empty result.")
            self.reset_to_idle()

    def on_region_selected(self, region: SelectedRegion) -> None:
        """Handle region selection from the overlay host."""
        self._selected_region = region
        self._set_state(SessionState.SELECTED)
        for listener in list(self._region_listeners):
            try:
                listener(region)
            except Exception as ex:
                logger.exception("Error in region listener: %s", ex)

    def dismiss(self) -> None:
        """Dismiss overlay, clear active session state, and return to IDLE."""
        if self._dismissing:
            return

        self._dismissing = True
        try:
            if self.overlay_host.is_visible():
                self.overlay_host.dismiss()
            self.capture_indicator.hide()
            self._current_capture = None
            self._selected_region = None
            self._set_state(SessionState.IDLE)
        finally:
            self._dismissing = False

    def reset_to_idle(self) -> None:
        """Alias for dismiss to cleanly return the session to IDLE."""
        self.dismiss()
