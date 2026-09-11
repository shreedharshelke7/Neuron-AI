"""Screen capture service interface for Block 1."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.capture.model import CapturedScreen


class CaptureService(ABC):
    """Abstract interface for screen capture services.

    Other blocks and session controllers communicate via this interface
    without direct coupling to GUI or OS capture internals.
    """

    @abstractmethod
    def capture_current_screen(self) -> CapturedScreen:
        """Capture the current primary screen or active display area."""
        ...


class StubCaptureService(CaptureService):
    """Placeholder capture service for Step 1 before capture is implemented."""

    def __init__(self, stub_result: Optional[CapturedScreen] = None) -> None:
        self._stub_result = stub_result or CapturedScreen()

    def capture_current_screen(self) -> CapturedScreen:
        """Return stub captured screen data."""
        return self._stub_result
