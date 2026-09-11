"""Activation Manager coordinating activation triggers for Block 1."""

from __future__ import annotations

import logging
import sys
import time
from typing import Callable, Optional

from app.trigger.activation import ActivationTrigger
from app.trigger.global_hotkey import GlobalHotkeyBackend, WindowsGlobalHotkey

logger = logging.getLogger(__name__)


class ActivationManager(ActivationTrigger):
    """Coordinates local and global activation requests for Neuron AI.

    Hides Windows-specific global hotkey implementation details behind
    the abstract ActivationTrigger interface.
    """

    def __init__(
        self,
        on_activate: Optional[Callable[[], None]] = None,
        global_backend: Optional[GlobalHotkeyBackend] = None,
        debounce_seconds: float = 0.3,
    ) -> None:
        self._on_activate = on_activate
        self._debounce_seconds = debounce_seconds
        self._last_activation_time: float = 0.0
        self._activation_count: int = 0

        if global_backend is not None:
            self._global_backend: Optional[GlobalHotkeyBackend] = global_backend
        elif sys.platform == "win32":
            self._global_backend = WindowsGlobalHotkey(
                on_activate=self.request_activation
            )
        else:
            self._global_backend = None

    @property
    def is_global_registered(self) -> bool:
        """Whether the global hotkey is currently registered."""
        return (
            self._global_backend.is_registered
            if self._global_backend is not None
            else False
        )

    @property
    def activation_count(self) -> int:
        """Total number of successful activation requests handled."""
        return self._activation_count

    def start(self) -> bool:
        """Start the global hotkey listener.

        Returns True if registration succeeded, False otherwise.
        Registration failure does not crash the application.
        """
        if self._global_backend is not None:
            success = self._global_backend.start()
            if not success:
                logger.warning(
                    "Global hotkey could not be registered. "
                    "Local shortcuts remain functional."
                )
            return success
        return False

    def stop(self) -> None:
        """Stop and unregister the global hotkey listener cleanly."""
        if self._global_backend is not None:
            self._global_backend.stop()

    def request_activation(self) -> None:
        """Handle an activation request with debouncing.

        Ensures rapid repeated key events or held keys do not generate
        duplicate interaction sessions.
        """
        now = time.monotonic()
        if (now - self._last_activation_time) < self._debounce_seconds:
            logger.debug("Activation request debounced.")
            return

        self._last_activation_time = now
        self._activation_count += 1

        if self._on_activate is not None:
            self._on_activate()
