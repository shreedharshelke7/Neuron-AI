"""Abstract listening indicator interfaces and stubs for session lifecycle (Block 9)."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from app.capture.model import DisplayGeometry


class OrbState(str, Enum):
    """Operational visualization states for the Neuron assistant orb."""

    OFF = "OFF"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    EXPLAINING = "EXPLAINING"


class ListeningIndicator:
    """Protocol / interface defining the listening indicator lifecycle."""

    def show_listening(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Display the indicator in LISTENING mode (glowing breathing pulse)."""
        raise NotImplementedError

    def show_thinking(self, geometry: Optional[DisplayGeometry] = None) -> None:
        """Transition the indicator to THINKING mode (rotating reasoning glow)."""
        raise NotImplementedError

    def hide(self) -> None:
        """Hide the indicator completely and stop all animation timers."""
        raise NotImplementedError

    def is_visible(self) -> bool:
        """Return whether the indicator is currently visible on screen."""
        raise NotImplementedError

    def set_amplitude(self, amp: float) -> None:
        """Supply normalized [0.0, 1.0] audio volume amplitude for dynamic reactivity."""
        raise NotImplementedError

    def get_state(self) -> OrbState:
        """Return the current visual orb state."""
        raise NotImplementedError


class StubListeningIndicator(ListeningIndicator):
    """In-memory stub implementation for headless testing and non-GUI runners."""

    def __init__(self) -> None:
        self._state: OrbState = OrbState.OFF
        self._visible: bool = False
        self._amplitude: float = 0.0
        self.call_log: list[str] = []

    def show_listening(self, geometry: Optional[DisplayGeometry] = None) -> None:
        self._state = OrbState.LISTENING
        self._visible = True
        self.call_log.append("show_listening")

    def show_thinking(self, geometry: Optional[DisplayGeometry] = None) -> None:
        self._state = OrbState.THINKING
        self._visible = True
        self.call_log.append("show_thinking")

    def hide(self) -> None:
        self._state = OrbState.OFF
        self._visible = False
        self._amplitude = 0.0
        self.call_log.append("hide")

    def is_visible(self) -> bool:
        return self._visible

    def set_amplitude(self, amp: float) -> None:
        self._amplitude = max(0.0, min(1.0, float(amp)))
        self.call_log.append(f"amplitude:{self._amplitude:.2f}")

    def get_state(self) -> OrbState:
        return self._state
