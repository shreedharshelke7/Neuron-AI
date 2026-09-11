"""TTS provider adapter interface and fake implementation for Block 5."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from app.tts.model import TTSAudioClip


class TTSAdapter(ABC):
    """Abstract interface for speech synthesis adapters."""

    @abstractmethod
    def synthesize(self, text: str) -> TTSAudioClip:
        """Synthesize text into an in-memory TTSAudioClip.

        Must raise appropriate TTSError subclasses on failure.
        Must not write persistent audio files to disk.
        """
        ...


class FakeTTSAdapter(TTSAdapter):
    """Deterministic in-memory fake TTS adapter for unit and integration testing."""

    def __init__(
        self,
        sample_rate: int = 24000,
        fake_duration_per_char: float = 0.02,
        fail_with: Optional[Exception] = None,
    ) -> None:
        self.sample_rate: int = sample_rate
        self.fake_duration_per_char: float = fake_duration_per_char
        self.fail_with: Optional[Exception] = fail_with
        self.calls: List[str] = []

    def synthesize(self, text: str) -> TTSAudioClip:
        """Synthesize deterministic PCM bytes in-memory."""
        self.calls.append(text)

        if self.fail_with is not None:
            raise self.fail_with

        if not text or not text.strip():
            return TTSAudioClip(
                raw_bytes=b"",
                sample_rate=self.sample_rate,
                duration_seconds=0.0,
                text="",
            )

        duration = max(0.1, len(text) * self.fake_duration_per_char)
        num_samples = int(self.sample_rate * duration)
        # 16-bit mono PCM silence/buffer
        raw_bytes = b"\x00\x00" * num_samples

        return TTSAudioClip(
            raw_bytes=raw_bytes,
            sample_rate=self.sample_rate,
            channels=1,
            sample_width=2,
            encoding="pcm_s16le",
            duration_seconds=duration,
            text=text,
        )
