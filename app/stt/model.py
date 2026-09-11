"""Data representations for Block 2 Speech-to-Text conversion."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class TranscriptResult:
    """Provider-independent result representing a converted spoken question.

    Held ephemerally in memory for the active interaction session.
    """

    transcript: str
    audio_duration: float
    language: str = "en"
    confidence: Optional[float] = None
    is_final: bool = True
    error_code: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    @property
    def is_empty(self) -> bool:
        """Return whether the transcript text is empty or whitespace-only."""
        return not bool(self.transcript and self.transcript.strip())


@dataclass(frozen=True)
class UserQuestion:
    """SRS-aligned question contract consumed by Block 3 (Tutor Engine).

    Completely decouples subsequent blocks from microphone hardware and
    STT provider implementations.
    """

    transcript: str
    audio_duration: float
    language: str = "en"
    confidence: Optional[float] = None

    @classmethod
    def from_transcript_result(cls, result: TranscriptResult) -> "UserQuestion":
        """Construct a UserQuestion from a TranscriptResult."""
        return cls(
            transcript=result.transcript.strip(),
            audio_duration=result.audio_duration,
            language=result.language,
            confidence=result.confidence,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize user question to a dictionary."""
        return {
            "transcript": self.transcript,
            "audio_duration": self.audio_duration,
            "language": self.language,
            "confidence": self.confidence,
        }
