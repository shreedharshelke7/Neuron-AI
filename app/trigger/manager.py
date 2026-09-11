"""Activation Manager coordinating activation triggers for Block 1."""

from __future__ import annotations

import logging
import sys
import time
from typing import Callable, Optional

from app.trigger.activation import ActivationTrigger
from app.trigger.global_hotkey import GlobalHotkeyBackend, WindowsGlobalHotkey
from app.wake.detector import WakeWordDetector

logger = logging.getLogger(__name__)


class ActivationManager(ActivationTrigger):
    """Coordinates local and global activation requests for Neuron AI.

    Hides Windows-specific global hotkey implementation details behind
    the abstract ActivationTrigger interface, and coordinates hands-free
    wake-word activation seamlessly through the same debounced path.
    """

    def __init__(
        self,
        on_activate: Optional[Callable[[], None]] = None,
        global_backend: Optional[GlobalHotkeyBackend] = None,
        wake_detector: Optional[WakeWordDetector] = None,
        debounce_seconds: float = 0.3,
    ) -> None:
        self._on_activate = on_activate
        self._debounce_seconds = debounce_seconds
        self._last_activation_time: float = 0.0
        self._activation_count: int = 0
        self._wake_detector: Optional[WakeWordDetector] = wake_detector

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
    def wake_detector(self) -> Optional[WakeWordDetector]:
        """Registered wake word detector if any."""
        return self._wake_detector

    @property
    def is_wake_listening(self) -> bool:
        """Whether wake word detection is currently listening."""
        return self._wake_detector.is_listening if self._wake_detector is not None else False

    @property
    def is_wake_paused(self) -> bool:
        """Whether wake word detection is currently paused."""
        return self._wake_detector.is_paused if self._wake_detector is not None else False

    def set_wake_detector(self, detector: Optional[WakeWordDetector]) -> None:
        """Configure or swap the active wake word detector."""
        if self._wake_detector is not None and self._wake_detector.is_listening:
            self._wake_detector.stop()
        self._wake_detector = detector
        if self._wake_detector is not None:
            self._wake_detector.set_on_detected(self.request_activation)

    @property
    def activation_count(self) -> int:
        """Total number of successful activation requests handled."""
        return self._activation_count

    def start(self) -> bool:
        """Start the global hotkey listener and wake word detector.

        Returns True if registration succeeded, False otherwise.
        Registration failure does not crash the application.
        """
        hotkey_success = False
        if self._global_backend is not None:
            hotkey_success = self._global_backend.start()
            if not hotkey_success:
                logger.warning(
                    "Global hotkey could not be registered. "
                    "Local shortcuts remain functional."
                )

        if self._wake_detector is not None:
            try:
                self._wake_detector.set_on_detected(self.request_activation)
                wake_success = self._wake_detector.start()
                if not wake_success:
                    logger.warning(
                        "Wake word detector could not be started. "
                        "Hotkey activation remains functional."
                    )
            except Exception as exc:
                logger.warning("Error starting wake word detector: %s", exc)

        return hotkey_success

    def stop(self) -> None:
        """Stop and unregister the global hotkey listener and wake detector cleanly."""
        if self._global_backend is not None:
            self._global_backend.stop()

        if self._wake_detector is not None:
            try:
                self._wake_detector.stop()
            except Exception as exc:
                logger.warning("Error stopping wake detector: %s", exc)

    def pause_wake_detection(self) -> None:
        """Pause wake word detection to release the microphone for session recording."""
        if self._wake_detector is not None:
            try:
                self._wake_detector.pause()
            except Exception as exc:
                logger.debug("Error pausing wake detector: %s", exc)

    def resume_wake_detection(self) -> None:
        """Resume wake word detection when session returns to IDLE."""
        if self._wake_detector is not None:
            try:
                self._wake_detector.resume()
            except Exception as exc:
                logger.debug("Error resuming wake detector: %s", exc)

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
