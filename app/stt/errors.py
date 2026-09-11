"""Error hierarchy for Block 2 Speech-to-Text conversion."""

from __future__ import annotations


class STTError(Exception):
    """Base exception for all Block 2 speech-to-text conversion errors."""


class STTUnavailableError(STTError):
    """Raised when STT backend/service is unreachable or not configured."""


class STTAuthenticationError(STTError):
    """Raised when STT authentication, credentials, or API tokens fail."""


class STTTimeoutError(STTError):
    """Raised when STT conversion operation exceeds configured timeout."""


class TranscriptionError(STTError):
    """Raised when transcription processing fails on the provider backend."""


class EmptyTranscriptError(STTError):
    """Raised when speech recognition yields no recognizable text."""


class STTCancellationError(STTError):
    """Raised when an ongoing STT request is cancelled."""
