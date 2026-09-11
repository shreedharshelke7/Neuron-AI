"""Audio playback service interface and implementations for Block 5."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional

from app.tts.errors import TTSPlaybackError
from app.tts.model import TTSAudioClip

logger = logging.getLogger(__name__)


class AudioPlaybackService(ABC):
    """Abstract interface for audio playback services.

    Handles in-memory PCM audio playback with immediate cancellation support.
    """

    @abstractmethod
    def play(
        self, clip: TTSAudioClip, on_finished: Optional[Callable[[], None]] = None
    ) -> None:
        """Begin non-blocking playback of an in-memory audio clip."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Immediately stop all active audio playback and cancel completion callbacks."""
        ...

    @property
    @abstractmethod
    def is_playing(self) -> bool:
        """Return whether audio is currently playing."""
        ...


class SoundDevicePlaybackService(AudioPlaybackService):
    """Production audio playback service utilizing sounddevice and numpy.

    Zero disk persistence; completely in-memory PCM output.
    """

    def __init__(self) -> None:
        self._is_playing: bool = False
        self._current_session: int = 0
        self._lock = threading.Lock()
        self._waiter_thread: Optional[threading.Thread] = None

    @property
    def is_playing(self) -> bool:
        with self._lock:
            return self._is_playing

    def play(
        self, clip: TTSAudioClip, on_finished: Optional[Callable[[], None]] = None
    ) -> None:
        """Play in-memory PCM audio clip non-blockingly."""
        if clip.is_empty:
            logger.debug("Empty audio clip passed to playback; invoking callback immediately.")
            if on_finished:
                on_finished()
            return

        import numpy as np
        import sounddevice as sd

        with self._lock:
            # Increment session token to invalidate any previous waiter
            self._current_session += 1
            session_id = self._current_session
            self._is_playing = True

            try:
                # Stop any existing device playback
                sd.stop()
            except Exception as ex:
                logger.debug("sd.stop during new playback: %s", ex)

        try:
            # Parse raw 16-bit PCM bytes into numpy array
            audio_array = np.frombuffer(clip.raw_bytes, dtype=np.int16)
            if clip.channels > 1:
                audio_array = audio_array.reshape(-1, clip.channels)

            sd.play(audio_array, samplerate=clip.sample_rate)
            logger.debug(
                "Started sounddevice playback: %d samples at %dHz",
                len(audio_array),
                clip.sample_rate,
            )
        except Exception as ex:
            with self._lock:
                self._is_playing = False
            logger.error("Failed to start sounddevice playback: %s", ex)
            raise TTSPlaybackError(f"SoundDevice playback error: {ex}") from ex

        def _waiter():
            try:
                sd.wait()
            except Exception as wait_err:
                logger.debug("sd.wait exception: %s", wait_err)

            should_callback = False
            with self._lock:
                if self._current_session == session_id and self._is_playing:
                    self._is_playing = False
                    should_callback = True

            if should_callback and on_finished:
                try:
                    on_finished()
                except Exception as cb_err:
                    logger.exception("Error in playback on_finished callback: %s", cb_err)

        self._waiter_thread = threading.Thread(
            target=_waiter, name=f"sd-playback-{session_id}", daemon=True
        )
        self._waiter_thread.start()

    def stop(self) -> None:
        """Immediately halt audio output and cancel in-flight callbacks."""
        with self._lock:
            if not self._is_playing:
                return
            self._current_session += 1
            self._is_playing = False

        try:
            import sounddevice as sd
            sd.stop()
            logger.debug("SoundDevice playback stopped successfully.")
        except Exception as ex:
            logger.warning("Error stopping sounddevice playback: %s", ex)


class FakeAudioPlaybackService(AudioPlaybackService):
    """Deterministic in-memory fake playback service for testing."""

    def __init__(self, auto_complete: bool = True) -> None:
        self.auto_complete: bool = auto_complete
        self._is_playing: bool = False
        self.play_count: int = 0
        self.stop_count: int = 0
        self.last_played_clip: Optional[TTSAudioClip] = None
        self._pending_callback: Optional[Callable[[], None]] = None

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def play(
        self, clip: TTSAudioClip, on_finished: Optional[Callable[[], None]] = None
    ) -> None:
        self.play_count += 1
        self.last_played_clip = clip
        self._is_playing = True
        self._pending_callback = on_finished

        if self.auto_complete:
            self._is_playing = False
            if on_finished:
                on_finished()

    def finish_pending(self) -> None:
        """Simulate completion of currently playing audio."""
        if self._is_playing and self._pending_callback:
            self._is_playing = False
            cb = self._pending_callback
            self._pending_callback = None
            cb()

    def stop(self) -> None:
        self.stop_count += 1
        self._is_playing = False
        self._pending_callback = None
