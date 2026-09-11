"""Data models for Block 5 TTS audio clips and narration plans."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class TTSAudioClip:
    """Represents synthesized in-memory PCM audio for spoken explanation."""

    raw_bytes: bytes
    sample_rate: int = 24000
    channels: int = 1
    sample_width: int = 2  # 16-bit signed PCM
    encoding: str = "pcm_s16le"
    duration_seconds: float = 0.0
    text: str = ""

    @property
    def is_empty(self) -> bool:
        """Whether the audio buffer contains no bytes."""
        return len(self.raw_bytes) == 0

    @property
    def byte_count(self) -> int:
        """Total size of audio buffer in bytes."""
        return len(self.raw_bytes)


@dataclass(frozen=True)
class NarrationSegment:
    """Represents one ordered segment of an explanation narration."""

    index: int
    text: str
    audio_clip: Optional[TTSAudioClip] = None


@dataclass(frozen=True)
class NarrationPlan:
    """Ordered collection of narration segments for sequential presentation."""

    segments: List[NarrationSegment] = field(default_factory=list)

    @property
    def full_text(self) -> str:
        """Combined text across all segments."""
        return " ".join(seg.text for seg in self.segments if seg.text)

    @property
    def total_duration(self) -> float:
        """Total duration of all synthesized segments in seconds."""
        return sum(
            seg.audio_clip.duration_seconds
            for seg in self.segments
            if seg.audio_clip is not None
        )
