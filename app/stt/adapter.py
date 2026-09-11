"""Speech-to-Text adapter interface and fake implementation for Block 2."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.audio.errors import EmptyAudioError
from app.audio.model import AudioCaptureResult
from app.stt.errors import STTError, TranscriptionError
from app.stt.model import TranscriptResult


class STTAdapter(ABC):
    """Abstract interface for Speech-to-Text adapters.

    Provides a provider-agnostic boundary between audio recordings
    and transcript generation.
    """

    @abstractmethod
    def transcribe(self, audio: AudioCaptureResult) -> TranscriptResult:
        """Convert an in-memory audio capture result into a text transcript.

        Raises STTError subclasses on failure.
        """
        ...


class FakeSTTAdapter(STTAdapter):
    """Deterministic in-memory fake STT adapter for testing."""

    def __init__(
        self,
        fake_transcript: str = "Explain this concept.",
        confidence: float = 0.95,
        language: str = "en",
        should_fail: bool = False,
        error_to_raise: Optional[STTError] = None,
        reject_empty_audio: bool = True,
    ) -> None:
        self._fake_transcript = fake_transcript
        self._confidence = confidence
        self._language = language
        self._should_fail = should_fail
        self._error_to_raise = error_to_raise or TranscriptionError(
            "Simulated STT transcription failure."
        )
        self._reject_empty_audio = reject_empty_audio
        self._call_count: int = 0

    @property
    def call_count(self) -> int:
        return self._call_count

    def transcribe(self, audio: AudioCaptureResult) -> TranscriptResult:
        self._call_count += 1

        if self._reject_empty_audio and audio.is_empty:
            raise EmptyAudioError("Cannot transcribe empty audio buffer.")

        if self._should_fail:
            raise self._error_to_raise

        return TranscriptResult(
            transcript=self._fake_transcript,
            audio_duration=audio.duration_seconds,
            language=self._language,
            confidence=self._confidence,
            is_final=True,
        )
