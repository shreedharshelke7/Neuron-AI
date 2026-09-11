"""Data representations for Block 2 audio capture."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AudioCaptureResult:
    """Represents one temporary spoken-question recording held in memory.

    Audio is ephemeral and held strictly in memory by default.
    """

    raw_bytes: bytes
    duration_seconds: float
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # 16-bit PCM
    encoding: str = "pcm_s16le"

    @property
    def byte_count(self) -> int:
        """Total size of audio buffer in bytes."""
        return len(self.raw_bytes)

    @property
    def is_empty(self) -> bool:
        """Whether the captured audio buffer is empty."""
        return len(self.raw_bytes) == 0
