"""Audio capture service interface and fake implementation for Block 2."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from app.audio.errors import AudioCaptureError
from app.audio.model import AudioCaptureResult


class AudioCaptureService(ABC):
    """Abstract interface for audio capture services.

    Defines the contract for microphone recording sessions without
    coupling consumers to specific audio hardware or recording libraries.
    """

    @abstractmethod
    def start_recording(self) -> None:
        """Begin audio capture from the microphone.

        Must be called only on explicit activation.
        """
        ...

    @abstractmethod
    def stop_recording(self) -> AudioCaptureResult:
        """Stop recording and return captured in-memory audio data."""
        ...

    @abstractmethod
    def cancel_recording(self) -> None:
        """Immediately cancel recording and discard temporary audio buffers.

        Must be safe and idempotent if called repeatedly or when not recording.
        """
        ...

    @property
    @abstractmethod
    def is_recording(self) -> bool:
        """Return whether audio capture is currently active."""
        ...

    def add_frame_listener(self, listener: Callable[[bytes], None]) -> None:
        """Register a callback invoked when an audio frame is captured."""
        pass

    def remove_frame_listener(self, listener: Callable[[bytes], None]) -> None:
        """Unregister a frame listener callback."""
        pass


class FakeAudioCaptureService(AudioCaptureService):
    """Deterministic in-memory fake audio capture service for testing."""

    def __init__(
        self,
        fake_audio_bytes: Optional[bytes] = None,
        fake_duration_seconds: float = 2.5,
        sample_rate: int = 16000,
        channels: int = 1,
        sample_width: int = 2,
    ) -> None:
        self._fake_audio_bytes = (
            fake_audio_bytes
            if fake_audio_bytes is not None
            else b"\x00\x00" * int(sample_rate * fake_duration_seconds)
        )
        self._fake_duration_seconds = fake_duration_seconds
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width

        self._is_recording: bool = False
        self._frame_listeners: List[Callable[[bytes], None]] = []

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    def add_frame_listener(self, listener: Callable[[bytes], None]) -> None:
        if listener not in self._frame_listeners:
            self._frame_listeners.append(listener)

    def remove_frame_listener(self, listener: Callable[[bytes], None]) -> None:
        if listener in self._frame_listeners:
            self._frame_listeners.remove(listener)

    def emit_frame(self, raw_chunk: bytes) -> None:
        """Simulate an incoming audio frame for registered listeners."""
        for listener in list(self._frame_listeners):
            listener(raw_chunk)

    def start_recording(self) -> None:
        if self._is_recording:
            raise AudioCaptureError("Cannot start recording: already recording.")
        self._is_recording = True

    def stop_recording(self) -> AudioCaptureResult:
        if not self._is_recording:
            raise AudioCaptureError("Cannot stop recording: not currently recording.")
        self._is_recording = False
        return AudioCaptureResult(
            raw_bytes=self._fake_audio_bytes,
            duration_seconds=self._fake_duration_seconds,
            sample_rate=self._sample_rate,
            channels=self._channels,
            sample_width=self._sample_width,
        )

    def cancel_recording(self) -> None:
        """Idempotently cancel recording and reset state."""
        self._is_recording = False
