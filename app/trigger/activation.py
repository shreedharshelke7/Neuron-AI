"""Activation interface for Block 1."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, Optional


class ActivationTrigger(ABC):
    """Abstract interface for activation triggers (hotkeys, tray, etc.).

    Decouples trigger sources from session flow and GUI internals.
    """

    @abstractmethod
    def request_activation(self) -> None:
        """Request the Phase 0 interaction flow."""
        ...


class StubActivationTrigger(ActivationTrigger):
    """Placeholder activation trigger allowing programmatic activation requests."""

    def __init__(self, on_activate: Optional[Callable[[], None]] = None) -> None:
        self._on_activate = on_activate
        self._activated_count: int = 0

    @property
    def activated_count(self) -> int:
        """Number of times activation was requested."""
        return self._activated_count

    def request_activation(self) -> None:
        """Record and invoke the activation request callback."""
        self._activated_count += 1
        if self._on_activate is not None:
            self._on_activate()
