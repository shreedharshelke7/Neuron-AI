"""Local offline wake-word detector using faster-whisper and energy gating.

Guarantees:
- FR-01: Shared canonical activation entry point with keyboard shortcuts.
- NFR-05: Zero continuous audio persistence; ephemeral in-memory frames only.
- NFR-06: Data minimization; no audio saved to disk or transmitted to cloud.
- NFR-08: Provider-independent implementation of WakeWordDetector.
- NFR-10: 100% local/offline execution using free/cached local model.
- PortAudio / microphone ownership: releases microphone completely during pause().
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import time
from typing import Any, Callable, List, Optional

import numpy as np

from app.wake.detector import WakeWordConfig, WakeWordDetector
from app.wake.errors import WakeWordDeviceError, WakeWordInitializationError

logger = logging.getLogger(__name__)


def is_wake_phrase_match(text: str, target_phrase: str = "Hey Neuron") -> bool:
    """Determine whether the transcribed text contains the target wake phrase.
    
    Robust against punctuation variations, capitalization, and known phonetic
    mis-transcriptions of 'Neuron'.
    """
    if not text or not text.strip():
        return False

    clean = re.sub(r"[^\w\s]", "", text.lower()).strip()
    words = clean.split()
    target_clean = re.sub(r"[^\w\s]", "", target_phrase.lower()).strip()

    # 1. Exact phrase substring match
    if target_clean in clean:
        return True

    # 2. Known phonetic variants for "Hey Neuron"
    variants = [
        "hey neuron",
        "hi neuron",
        "hello neuron",
        "okay neuron",
        "hey youre on",
        "hey you re on",
        "hey your on",
        "hey you are on",
        "hey new ron",
        "hey newron",
        "hay neuron",
    ]
    for variant in variants:
        if variant in clean:
            return True

    # 3. Keyword presence if targeting single word "neuron"
    if target_clean == "neuron" and "neuron" in words:
        return True

    return False


class LocalWhisperWakeDetector(WakeWordDetector):
    """Local, offline wake-word detector powered by faster-whisper.

    Operates with speech-energy gating (RMS) to minimize CPU usage when silent,
    ephemeral in-memory audio buffers, and clean pause/resume stream lifecycle.
    """

    def __init__(
        self,
        config: Optional[WakeWordConfig] = None,
        model: Optional[Any] = None,
        stream_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._config = config or WakeWordConfig()
        self._model = model
        self._stream_factory = stream_factory

        self._on_detected: Optional[Callable[[], None]] = None
        self._is_running: bool = False
        self._is_paused: bool = False
        self._is_available: bool = True

        self._audio_queue: queue.Queue[bytes] = queue.Queue(maxsize=100)
        self._stream: Optional[Any] = None
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        self._last_detection_time: float = 0.0

    @property
    def config(self) -> WakeWordConfig:
        return self._config

    @property
    def is_listening(self) -> bool:
        with self._lock:
            return self._is_running and not self._is_paused

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._is_paused

    @property
    def is_available(self) -> bool:
        return self._is_available

    def set_on_detected(self, callback: Callable[[], None]) -> None:
        self._on_detected = callback

    def _ensure_model(self) -> Any:
        """Lazily initialize the faster-whisper model."""
        if self._model is not None:
            return self._model

        try:
            from faster_whisper import WhisperModel

            logger.info(
                "Initializing local faster-whisper model '%s' for wake word detection on CPU...",
                self._config.model_name,
            )
            self._model = WhisperModel(
                self._config.model_name,
                device="cpu",
                compute_type="int8",
            )
            return self._model
        except Exception as exc:
            self._is_available = False
            logger.warning(
                "Failed to initialize faster-whisper wake model: %s. Wake detection disabled.",
                exc,
            )
            raise WakeWordInitializationError(
                f"Failed to load wake word model: {exc}"
            ) from exc

    def _create_stream(self) -> Any:
        """Create and start the audio input stream."""
        if self._stream_factory is not None:
            return self._stream_factory(
                samplerate=self._config.sample_rate,
                channels=self._config.channels,
                dtype="int16",
                device=self._config.device,
                callback=self._audio_callback,
            )

        import sounddevice as sd

        chunk_samples = int(
            self._config.sample_rate * (self._config.chunk_duration_ms / 1000.0)
        )
        try:
            stream = sd.InputStream(
                samplerate=self._config.sample_rate,
                channels=self._config.channels,
                dtype="int16",
                device=self._config.device,
                blocksize=chunk_samples,
                callback=self._audio_callback,
            )
            stream.start()
            return stream
        except Exception as exc:
            logger.warning("Failed to open microphone for wake word: %s", exc)
            raise WakeWordDeviceError(f"Microphone stream error: {exc}") from exc

    def _audio_callback(
        self, indata: np.ndarray, frames: int, time_info: Any, status: Any
    ) -> None:
        """High-priority audio callback pushing raw PCM bytes to worker queue."""
        if not self._is_running or self._is_paused:
            return
        try:
            raw = indata.tobytes()
            self._audio_queue.put_nowait(raw)
        except queue.Full:
            # Drop frame under heavy load to prevent buffer bloat
            pass

    def start(self) -> bool:
        """Start background passive listening."""
        if not self._config.enabled:
            logger.info("Wake word detector is disabled by configuration.")
            return False

        with self._lock:
            if self._is_running:
                return True

            try:
                self._ensure_model()
            except Exception:
                return False

            try:
                self._stream = self._create_stream()
            except Exception:
                return False

            self._is_running = True
            self._is_paused = False

            # Clear queue
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break

            self._worker_thread = threading.Thread(
                target=self._worker_loop,
                name="Neuron-WakeWord-Worker",
                daemon=True,
            )
            self._worker_thread.start()
            logger.info("Wake word detector started listening for '%s'.", self._config.phrase)
            return True

    def stop(self) -> None:
        """Stop background listening cleanly and release resources."""
        with self._lock:
            self._is_running = False
            self._is_paused = False

            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as ex:
                    logger.debug("Error closing wake stream: %s", ex)
                self._stream = None

        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1.0)
            self._worker_thread = None

        logger.info("Wake word detector stopped.")

    def pause(self) -> None:
        """Temporarily release microphone stream for other audio consumers."""
        with self._lock:
            if not self._is_running or self._is_paused:
                return

            self._is_paused = True
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as ex:
                    logger.debug("Error stopping wake stream during pause: %s", ex)
                self._stream = None

            # Drain queue
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break

        logger.debug("Wake word detector paused; microphone released.")

    def resume(self) -> bool:
        """Re-acquire microphone and resume passive listening."""
        with self._lock:
            if not self._is_running or not self._is_paused:
                return False

            try:
                self._stream = self._create_stream()
                self._is_paused = False
                logger.debug("Wake word detector resumed; microphone re-acquired.")
                return True
            except Exception as exc:
                logger.warning("Failed to resume wake word detector: %s", exc)
                return False

    def _worker_loop(self) -> None:
        """Background thread handling energy gating and wake word verification."""
        speech_buffer: List[bytes] = []
        silence_chunks: int = 0
        min_speech_chunks = 5  # At least 500ms of speech
        max_chunks = int(self._config.buffer_duration_seconds * 10)  # e.g. 18 chunks

        while self._is_running:
            if self._is_paused:
                speech_buffer.clear()
                silence_chunks = 0
                time.sleep(0.05)
                continue

            try:
                raw_chunk = self._audio_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            # Compute RMS energy
            arr = np.frombuffer(raw_chunk, dtype=np.int16).astype(np.float32)
            rms = float(np.sqrt(np.mean(np.square(arr)))) if len(arr) > 0 else 0.0

            if rms >= self._config.silence_threshold:
                speech_buffer.append(raw_chunk)
                silence_chunks = 0
                if len(speech_buffer) >= max_chunks:
                    self._evaluate_buffer(speech_buffer)
                    speech_buffer.clear()
            else:
                if speech_buffer:
                    silence_chunks += 1
                    # If silence lasts 3 chunks (300ms) after speech, evaluate
                    if silence_chunks >= 3:
                        if len(speech_buffer) >= min_speech_chunks:
                            self._evaluate_buffer(speech_buffer)
                        speech_buffer.clear()
                        silence_chunks = 0

    def _evaluate_buffer(self, speech_buffer: List[bytes]) -> None:
        """Transcribe speech buffer with faster-whisper and check for wake phrase."""
        if not speech_buffer or self._model is None:
            return

        # Check debounce cooldown
        now = time.monotonic()
        if (now - self._last_detection_time) < self._config.debounce_seconds:
            logger.debug("Wake detection candidate dropped due to debounce cooldown.")
            return

        raw_all = b"".join(speech_buffer)
        audio_f32 = np.frombuffer(raw_all, dtype=np.int16).astype(np.float32) / 32768.0

        try:
            segments, _ = self._model.transcribe(
                audio_f32,
                language="en",
                initial_prompt="Hey Neuron, a desktop AI learning companion",
                vad_filter=False,
            )
            transcript = " ".join(s.text for s in segments).strip()
            logger.debug("Wake worker transcribed: '%s'", transcript)

            if is_wake_phrase_match(transcript, self._config.phrase):
                logger.info("Wake phrase '%s' detected! Triggering activation.", self._config.phrase)
                self._last_detection_time = time.monotonic()
                if self._on_detected is not None:
                    self._on_detected()
        except Exception as exc:
            logger.debug("Error during wake phrase evaluation: %s", exc)
