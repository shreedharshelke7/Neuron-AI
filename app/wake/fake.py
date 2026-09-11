"""Deterministic fake wake word detector for unit and integration testing."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from app.wake.detector import WakeWordConfig, WakeWordDetector
from app.wake.errors import WakeWordError

logger = logging.getLogger(__name__)


class FakeWakeWordDetector(WakeWordDetector):
    """Test fake implementing WakeWordDetector for deterministic offline testing.

    Requires zero audio hardware, sound cards, or ML models.
    Supports manual simulation of wake detections and error injection.
    """

    def __init__(
        self,
        config: Optional[WakeWordConfig] = None,
        is_available: bool = True,
        fail_on_start: bool = False,
    ) -> None:
        self._config = config or WakeWordConfig()
        self._is_available = is_available
        self._fail_on_start = fail_on_start
        self._on_detected: Optional[Callable[[], None]] = None

        self._is_listening: bool = False
        self._is_paused: bool = False
        self._start_count: int = 0
        self._stop_count: int = 0
        self._pause_count: int = 0
        self._resume_count: int = 0
        self._simulation_count: int = 0

    @property
    def config(self) -> WakeWordConfig:
        return self._config

    @property
    def is_listening(self) -> bool:
        return self._is_listening and not self._is_paused

    @property
    def is_paused(self) -> bool:
        return self._is_paused

    @property
    def is_available(self) -> bool:
        return self._is_available

    @property
    def start_count(self) -> int:
        return self._start_count

    @property
    def stop_count(self) -> int:
        return self._stop_count

    @property
    def pause_count(self) -> int:
        return self._pause_count

    @property
    def resume_count(self) -> int:
        return self._resume_count

    @property
    def simulation_count(self) -> int:
        return self._simulation_count

    def set_on_detected(self, callback: Callable[[], None]) -> None:
        self._on_detected = callback

    def start(self) -> bool:
        if not self._config.enabled or not self._is_available:
            return False
        if self._fail_on_start:
            raise WakeWordError("Simulated wake detector failure on start")
        self._start_count += 1
        self._is_listening = True
        self._is_paused = False
        return True

    def stop(self) -> None:
        self._stop_count += 1
        self._is_listening = False
        self._is_paused = False

    def pause(self) -> None:
        self._pause_count += 1
        if self._is_listening:
            self._is_paused = True

    def resume(self) -> bool:
        self._resume_count += 1
        if not self._config.enabled or not self._is_available:
            return False
        if self._is_listening and self._is_paused:
            self._is_paused = False
            return True
        return False

    def simulate_detection(self) -> bool:
        """Programmatically simulate a wake word detection event.

        Returns True if the callback was invoked, False if the detector
        was not listening or paused.
        """
        if not self.is_listening:
            logger.debug(
                "Simulated detection ignored: detector is not actively listening "
                "(listening=%s, paused=%s).",
                self._is_listening,
                self._is_paused,
            )
            return False

        self._simulation_count += 1
        if self._on_detected is not None:
            self._on_detected()
            return True
        return False
