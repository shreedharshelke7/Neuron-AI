"""Custom exceptions for Block 6 wake word detection."""

from __future__ import annotations


class WakeWordError(Exception):
    """Base exception for wake word detection errors."""

    pass


class WakeWordInitializationError(WakeWordError):
    """Raised when the wake word detector fails to initialize."""

    pass


class WakeWordDeviceError(WakeWordError):
    """Raised when the audio input device cannot be accessed for wake word detection."""

    pass


class WakeWordDisabledError(WakeWordError):
    """Raised when an operation is requested on a disabled wake word detector."""

    pass
