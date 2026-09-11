"""Capture module interfaces and data representations."""

from app.capture.indicator import CaptureIndicator, StubCaptureIndicator
from app.capture.model import CapturedScreen, DisplayGeometry, SelectedRegion
from app.capture.service import CaptureService, StubCaptureService

__all__ = [
    "CaptureIndicator",
    "CaptureService",
    "CapturedScreen",
    "DisplayGeometry",
    "SelectedRegion",
    "StubCaptureIndicator",
    "StubCaptureService",
]
