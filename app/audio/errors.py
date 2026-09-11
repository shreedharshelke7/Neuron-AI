"""Error hierarchy for Block 2 audio capture."""

from __future__ import annotations


class AudioError(Exception):
    """Base exception for all Block 2 audio capture errors."""


class MicrophoneUnavailableError(AudioError):
    """Raised when no audio input device is available."""


class MicrophoneAccessDeniedError(AudioError):
    """Raised when microphone access is denied by OS permissions."""


class AudioCaptureError(AudioError):
    """Raised when audio capture encounters a hardware or stream failure."""


class EmptyAudioError(AudioError):
    """Raised when recording completes but yielded no audio data."""


class AudioCancellationError(AudioError):
    """Raised when an active audio recording is cancelled."""
