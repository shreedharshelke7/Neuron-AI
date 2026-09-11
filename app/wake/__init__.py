"""Block 6 wake word detection package for hands-free activation."""

from app.wake.detector import WakeWordConfig, WakeWordDetector
from app.wake.errors import (
    WakeWordDeviceError,
    WakeWordDisabledError,
    WakeWordError,
    WakeWordInitializationError,
)
from app.wake.factory import create_wake_detector, load_wake_config_from_env
from app.wake.fake import FakeWakeWordDetector
from app.wake.whisper_wake import LocalWhisperWakeDetector, is_wake_phrase_match

__all__ = [
    "WakeWordConfig",
    "WakeWordDetector",
    "WakeWordError",
    "WakeWordInitializationError",
    "WakeWordDeviceError",
    "WakeWordDisabledError",
    "FakeWakeWordDetector",
    "LocalWhisperWakeDetector",
    "create_wake_detector",
    "load_wake_config_from_env",
    "is_wake_phrase_match",
]
