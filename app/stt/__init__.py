"""Speech-to-Text contracts and adapters for Block 2."""

from app.stt.adapter import FakeSTTAdapter, STTAdapter
from app.stt.errors import (
    EmptyTranscriptError,
    STTAuthenticationError,
    STTCancellationError,
    STTError,
    STTTimeoutError,
    STTUnavailableError,
    TranscriptionError,
)
from app.stt.model import TranscriptResult, UserQuestion
from app.stt.whisper_stt import LocalWhisperSTTAdapter

__all__ = [
    "EmptyTranscriptError",
    "FakeSTTAdapter",
    "LocalWhisperSTTAdapter",
    "STTAdapter",
    "STTAuthenticationError",
    "STTCancellationError",
    "STTError",
    "STTTimeoutError",
    "STTUnavailableError",
    "TranscriptResult",
    "TranscriptionError",
    "UserQuestion",
]
