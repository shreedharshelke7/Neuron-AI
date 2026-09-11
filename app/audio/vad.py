"""Voice Activity Detection and End-of-Speech Detection for Block 6.

Guarantees:
- Lightweight deterministic RMS energy-based voice activity detection.
- Distinguishes initial silence from post-speech silence.
- Sustained silence (1.0–1.5s) after speech starts triggers automatic completion.
- Natural pauses inside sentences (e.g. 0.3s) do NOT prematurely terminate recording.
- Initial silence timeout (e.g. 7.0s) prevents empty questions from invoking Gemini.
- Maximum recording safety guard (e.g. 15.0s) prevents unbounded microphone recording.
- Completely non-blocking with zero disk persistence and zero external API calls.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)


def _read_env_float(var_name: str, default: float) -> float:
    """Safely read float value from environment or workspace .env file."""
    val = os.environ.get(var_name)
    if val is not None:
        try:
            return float(val.strip())
        except ValueError:
            pass

    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or not line or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    if k.strip() == var_name:
                        return float(v.strip())
        except Exception:
            pass

    return default


@dataclass
class EndOfSpeechConfig:
    """Configuration settings for End-of-Speech and Silence Detection."""

    speech_threshold: float = 350.0  # RMS energy threshold in 16-bit PCM scale
    min_speech_duration: float = 0.3  # Min speech required before enabling end-of-speech
    silence_duration: float = 1.2  # Sustained post-speech silence to trigger completion
    initial_silence_timeout: float = 7.0  # Timeout if no speech is detected at all
    max_recording_duration: float = 15.0  # Maximum safety recording duration
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # 16-bit PCM

    @classmethod
    def from_env(cls) -> EndOfSpeechConfig:
        """Construct configuration with environment variable overrides."""
        return cls(
            speech_threshold=_read_env_float("NEURON_VAD_THRESHOLD", 350.0),
            silence_duration=_read_env_float("NEURON_VAD_SILENCE_SECONDS", 1.2),
            initial_silence_timeout=_read_env_float("NEURON_VAD_INITIAL_TIMEOUT", 7.0),
            max_recording_duration=_read_env_float("NEURON_VAD_MAX_DURATION", 15.0),
        )


class EndOfSpeechDetector:
    """Lightweight real-time speech activity and end-of-speech detector.

    Consumes raw PCM audio chunks, calculates RMS energy, and tracks speech/silence
    lifecycle transitions.
    """

    def __init__(self, config: Optional[EndOfSpeechConfig] = None) -> None:
        self._config = config or EndOfSpeechConfig.from_env()
        self._lock = threading.Lock()

        self._on_end_of_speech: Optional[Callable[[int], None]] = None
        self._on_timeout: Optional[Callable[[int], None]] = None

        self._token: int = 0
        self._is_active: bool = False
        self._has_speech_started: bool = False
        self._accumulated_speech_time: float = 0.0
        self._trailing_silence_time: float = 0.0
        self._total_elapsed_time: float = 0.0

    @property
    def config(self) -> EndOfSpeechConfig:
        return self._config

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._is_active

    @property
    def has_speech_started(self) -> bool:
        with self._lock:
            return self._has_speech_started

    @property
    def total_elapsed_time(self) -> float:
        with self._lock:
            return self._total_elapsed_time

    @property
    def trailing_silence_time(self) -> float:
        with self._lock:
            return self._trailing_silence_time

    @property
    def accumulated_speech_time(self) -> float:
        with self._lock:
            return self._accumulated_speech_time

    def set_on_end_of_speech(self, callback: Callable[[int], None]) -> None:
        """Register callback fired when utterance completion is detected."""
        self._on_end_of_speech = callback

    def set_on_timeout(self, callback: Callable[[int], None]) -> None:
        """Register callback fired when initial silence timeout is reached."""
        self._on_timeout = callback

    def reset(self, token: int = 0) -> None:
        """Reset detector state for a new listening session."""
        with self._lock:
            self._token = token
            self._is_active = True
            self._has_speech_started = False
            self._accumulated_speech_time = 0.0
            self._trailing_silence_time = 0.0
            self._total_elapsed_time = 0.0
        logger.debug("EndOfSpeechDetector reset for session token %d.", token)

    def stop(self) -> None:
        """Deactivate detector and stop tracking frames."""
        with self._lock:
            self._is_active = False
        logger.debug("EndOfSpeechDetector stopped.")

    def process_frame(self, pcm_bytes: bytes) -> None:
        """Analyze an incoming PCM chunk for voice energy and silence duration."""
        if not pcm_bytes:
            return

        bytes_per_second = (
            self._config.sample_rate
            * self._config.channels
            * self._config.sample_width
        )
        if bytes_per_second <= 0:
            return

        chunk_duration = len(pcm_bytes) / bytes_per_second

        # Calculate RMS energy of 16-bit PCM chunk
        arr = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32)
        rms = float(np.sqrt(np.mean(np.square(arr)))) if len(arr) > 0 else 0.0

        trigger_eos = False
        trigger_timeout = False
        token = 0

        with self._lock:
            if not self._is_active:
                return

            token = self._token
            self._total_elapsed_time += chunk_duration
            is_speech = rms >= self._config.speech_threshold

            if not self._has_speech_started:
                # Phase 1: Waiting for user to begin speaking
                if is_speech:
                    self._accumulated_speech_time += chunk_duration
                    if (
                        self._accumulated_speech_time
                        >= self._config.min_speech_duration
                    ):
                        self._has_speech_started = True
                        self._trailing_silence_time = 0.0
                        logger.debug(
                            "Speech onset detected (RMS=%.1f, duration=%.2fs).",
                            rms,
                            self._accumulated_speech_time,
                        )
                else:
                    # Decay transient energy spikes (< 0.15s)
                    if self._accumulated_speech_time > 0:
                        self._accumulated_speech_time = max(
                            0.0,
                            self._accumulated_speech_time - chunk_duration * 0.5,
                        )

                    # Check initial silence timeout (user never spoke)
                    if (
                        self._total_elapsed_time
                        >= self._config.initial_silence_timeout - 1e-4
                    ):
                        logger.info(
                            "Initial silence timeout reached (%.1fs). No speech detected.",
                            self._total_elapsed_time,
                        )
                        self._is_active = False
                        trigger_timeout = True

            else:
                # Phase 2: Speech has started; monitoring for sustained post-speech silence
                # Safety guard: maximum recording duration
                if (
                    self._total_elapsed_time
                    >= self._config.max_recording_duration - 1e-4
                ):
                    logger.info(
                        "Maximum recording duration reached (%.1fs). Forcing stop.",
                        self._total_elapsed_time,
                    )
                    self._is_active = False
                    trigger_eos = True

                elif is_speech:
                    # Speech continues; reset trailing silence timer
                    self._trailing_silence_time = 0.0
                else:
                    # Trailing silence accumulating
                    self._trailing_silence_time += chunk_duration
                    if (
                        self._trailing_silence_time
                        >= self._config.silence_duration - 1e-4
                    ):
                        logger.info(
                            "End-of-speech detected: %.2fs sustained silence after speech.",
                            self._trailing_silence_time,
                        )
                        self._is_active = False
                        trigger_eos = True

        # Dispatch callbacks outside lock to avoid deadlocks
        if trigger_eos and self._on_end_of_speech is not None:
            self._on_end_of_speech(token)
        elif trigger_timeout and self._on_timeout is not None:
            self._on_timeout(token)
