"""Production audio capture service using sounddevice for Block 2."""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, List, Optional, Union

import sounddevice as sd

from app.audio.errors import (
    AudioCaptureError,
    AudioError,
    EmptyAudioError,
    MicrophoneAccessDeniedError,
    MicrophoneUnavailableError,
)
from app.audio.model import AudioCaptureResult
from app.audio.service import AudioCaptureService

logger = logging.getLogger(__name__)


class SoundDeviceAudioCaptureService(AudioCaptureService):
    """Production audio capture service using sounddevice (PortAudio).

    Guarantees:
    - Microphone is completely inactive until start_recording() is explicitly called.
    - Captures raw PCM audio strictly into memory (no disk files written).
    - Lightweight audio callback performing no network, STT, or UI work.
    - Thread-safe buffer management and idempotent cancel_recording().
    """

    DEFAULT_SAMPLE_RATE: int = 16000
    DEFAULT_CHANNELS: int = 1
    DEFAULT_SAMPLE_WIDTH: int = 2  # 16-bit PCM (dtype='int16')
    DEFAULT_ENCODING: str = "pcm_s16le"

    def __init__(
        self,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = DEFAULT_CHANNELS,
        sample_width: int = DEFAULT_SAMPLE_WIDTH,
        device: Optional[Union[int, str]] = None,
        stream_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        """Initialize service configuration.

        Microphone is NOT opened during initialization.
        """
        self._sample_rate = sample_rate
        self._channels = channels
        self._sample_width = sample_width
        self._device = device
        self._encoding = self.DEFAULT_ENCODING
        self._stream_factory = stream_factory

        self._lock = threading.Lock()
        self._frames: List[bytes] = []
        self._stream: Optional[Any] = None
        self._is_recording: bool = False

    @property
    def is_recording(self) -> bool:
        """Return whether audio capture is currently active."""
        with self._lock:
            return self._is_recording

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def sample_width(self) -> int:
        return self._sample_width

    @property
    def encoding(self) -> str:
        return self._encoding

    def start_recording(self) -> None:
        """Begin audio capture from the microphone into memory.

        Must be called only on explicit activation.
        """
        with self._lock:
            if self._is_recording:
                raise AudioCaptureError("Cannot start recording: already recording.")
            self._frames.clear()

            try:
                factory = self._stream_factory or self._default_stream_factory
                stream = factory(
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype="int16",
                    device=self._device,
                    callback=self._audio_callback,
                )
                stream.start()
                self._stream = stream
                self._is_recording = True
                logger.debug(
                    "Audio recording started (rate=%d, channels=%d)",
                    self._sample_rate,
                    self._channels,
                )
            except (MicrophoneUnavailableError, MicrophoneAccessDeniedError, AudioCaptureError):
                self._cleanup_resources_under_lock()
                raise
            except Exception as exc:
                self._cleanup_resources_under_lock()
                mapped_err = self._map_backend_error(exc)
                raise mapped_err from exc

    def stop_recording(self) -> AudioCaptureResult:
        """Stop recording and return captured in-memory audio data."""
        with self._lock:
            if not self._is_recording:
                raise AudioCaptureError("Cannot stop recording: not currently recording.")
            self._is_recording = False
            stream = self._stream
            self._stream = None
            frames = list(self._frames)
            self._frames.clear()

        # Stop and release hardware stream outside lock
        if stream is not None:
            try:
                stream.stop()
            except Exception as exc:
                try:
                    stream.close()
                except Exception:
                    pass
                mapped_err = self._map_backend_error(exc)
                raise mapped_err from exc
            else:
                try:
                    stream.close()
                except Exception as exc:
                    mapped_err = self._map_backend_error(exc)
                    raise mapped_err from exc

        raw_bytes = b"".join(frames)
        if not raw_bytes:
            raise EmptyAudioError("Recording completed but yielded no audio data.")

        bytes_per_sample = self._channels * self._sample_width
        duration_seconds = len(raw_bytes) / (self._sample_rate * bytes_per_sample)

        logger.debug(
            "Audio recording stopped: captured %d bytes (%.3fs)",
            len(raw_bytes),
            duration_seconds,
        )

        return AudioCaptureResult(
            raw_bytes=raw_bytes,
            duration_seconds=duration_seconds,
            sample_rate=self._sample_rate,
            channels=self._channels,
            sample_width=self._sample_width,
            encoding=self._encoding,
        )

    def cancel_recording(self) -> None:
        """Immediately cancel recording and discard temporary audio buffers.

        Safe and idempotent if called repeatedly or when not recording.
        """
        with self._lock:
            if not self._is_recording and self._stream is None:
                return
            self._is_recording = False
            stream = self._stream
            self._stream = None
            self._frames.clear()

        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        logger.debug("Audio recording cancelled and temporary buffers cleared.")

    def _audio_callback(
        self,
        indata: Any,
        frames: int,
        time_info: Any,
        status: Any,
    ) -> None:
        """Lightweight PortAudio callback.

        Performs no heavy work, no network, no STT, and no UI interaction.
        Copies incoming raw bytes into memory under the lock if recording.
        """
        with self._lock:
            if self._is_recording:
                self._frames.append(bytes(indata))

    def _default_stream_factory(self, **kwargs: Any) -> Any:
        """Create a default sounddevice RawInputStream."""
        return sd.RawInputStream(**kwargs)

    def _cleanup_resources_under_lock(self) -> None:
        """Safely release stream and reset state under lock."""
        stream = self._stream
        self._stream = None
        self._is_recording = False
        self._frames.clear()
        if stream is not None:
            try:
                stream.stop()
            except Exception:
                pass
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

    @staticmethod
    def _map_backend_error(exc: Exception) -> AudioError:
        """Map backend exceptions to Block 2 audio error hierarchy."""
        if isinstance(exc, AudioError):
            return exc

        msg = str(exc).lower()
        if any(token in msg for token in ["permission", "access denied", "unauthorized"]):
            return MicrophoneAccessDeniedError(f"Microphone access denied: {exc}")
        if any(
            token in msg
            for token in [
                "no default input device",
                "invalid device",
                "device unavailable",
                "no input device",
                "device not found",
                "invalid number of channels",
            ]
        ):
            return MicrophoneUnavailableError(f"Microphone device unavailable: {exc}")

        return AudioCaptureError(f"Audio capture failed: {exc}")

    def __del__(self) -> None:
        """Ensure stream cleanup if service is garbage collected."""
        try:
            self.cancel_recording()
        except Exception:
            pass
