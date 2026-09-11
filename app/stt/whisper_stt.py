"""Local offline Speech-to-Text adapter implementation using faster-whisper."""

from __future__ import annotations

import logging
from typing import Any, Callable, List, Optional

import numpy as np

from app.audio.model import AudioCaptureResult
from app.stt.adapter import STTAdapter
from app.stt.errors import (
    EmptyTranscriptError,
    STTError,
    STTUnavailableError,
    TranscriptionError,
)
from app.stt.model import TranscriptResult

logger = logging.getLogger(__name__)


class LocalWhisperSTTAdapter(STTAdapter):
    """Local, offline Speech-to-Text adapter using faster-whisper (CTranslate2).

    Guarantees:
    - 100% local processing; zero billing, zero cloud APIs, zero network calls during transcription.
    - Lazy model loading: constructor is side-effect free, model loads on first transcription.
    - Uses in-memory NumPy float32 waveform directly from raw PCM bytes without temporary disk files.
    - English-optimized default model ('base.en') with CPU int8 quantization for responsive hackathon demo.
    - Provider-agnostic error mapping and clean TranscriptResult output.
    """

    DEFAULT_MODEL: str = "base.en"
    DEFAULT_DEVICE: str = "cpu"
    DEFAULT_COMPUTE_TYPE: str = "int8"
    DEFAULT_LANGUAGE: str = "en"

    def __init__(
        self,
        model_size_or_path: Optional[str] = None,
        device: str = DEFAULT_DEVICE,
        compute_type: str = DEFAULT_COMPUTE_TYPE,
        language: str = DEFAULT_LANGUAGE,
        model_factory: Optional[Callable[[], Any]] = None,
    ) -> None:
        """Initialize adapter configuration without loading the model or opening network."""
        from app.utils.paths import resolve_whisper_model_path

        if model_size_or_path is None or model_size_or_path == self.DEFAULT_MODEL:
            self._model_size_or_path = resolve_whisper_model_path(self.DEFAULT_MODEL)
        else:
            self._model_size_or_path = model_size_or_path

        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._model_factory = model_factory
        self._model: Optional[Any] = None

    @property
    def model_size_or_path(self) -> str:
        return self._model_size_or_path

    @property
    def device(self) -> str:
        return self._device

    @property
    def compute_type(self) -> str:
        return self._compute_type

    @property
    def language(self) -> str:
        return self._language

    def _get_model(self) -> Any:
        """Lazily load and cache the faster-whisper model."""
        if self._model is not None:
            return self._model

        try:
            if self._model_factory is not None:
                self._model = self._model_factory()
            else:
                import os
                from app.utils.paths import is_packaged

                # In packaged execution, verify bundled model presence before initializing WhisperModel
                if is_packaged():
                    if not os.path.exists(self._model_size_or_path) or not os.path.isdir(self._model_size_or_path):
                        raise STTUnavailableError(
                            f"Bundled faster-whisper model directory not found at '{self._model_size_or_path}'. "
                            "Please ensure the application bundle includes the 'models/faster-whisper-base.en' resource."
                        )

                from faster_whisper import WhisperModel

                logger.info(
                    "Loading local Whisper model '%s' (device=%s, compute_type=%s)...",
                    self._model_size_or_path,
                    self._device,
                    self._compute_type,
                )
                self._model = WhisperModel(
                    self._model_size_or_path,
                    device=self._device,
                    compute_type=self._compute_type,
                )
            return self._model
        except STTUnavailableError:
            raise
        except Exception as exc:
            logger.exception("Failed to load local Whisper model: %s", exc)
            raise STTUnavailableError(
                f"Failed to load local speech recognition model '{self._model_size_or_path}': {exc}"
            ) from exc

    def transcribe(self, audio: AudioCaptureResult) -> TranscriptResult:
        """Convert in-memory AudioCaptureResult to a TranscriptResult using local faster-whisper."""
        # 1. Enforce input validity before loading model or processing
        if audio.is_empty:
            raise EmptyTranscriptError("Cannot transcribe empty audio buffer.")

        # 2. Lazily obtain Whisper model
        model = self._get_model()

        # 3. Convert in-memory signed 16-bit PCM bytes to normalized float32 waveform (-1.0 to 1.0)
        try:
            waveform = (
                np.frombuffer(audio.raw_bytes, dtype=np.int16).astype(np.float32)
                / 32768.0
            )
        except Exception as exc:
            raise TranscriptionError(f"Failed to decode audio buffer into waveform: {exc}") from exc

        # 4. Perform local recognition
        try:
            segments, info = model.transcribe(
                waveform,
                language=self._language,
                beam_size=5,
            )

            transcript_parts: List[str] = []
            for seg in segments:
                text = seg.text.strip()
                if text:
                    transcript_parts.append(text)

            full_transcript = " ".join(transcript_parts).strip()
        except Exception as exc:
            logger.exception("Whisper transcription failed: %s", exc)
            raise TranscriptionError(f"Local speech recognition failed: {exc}") from exc

        # 5. Check for empty transcription result
        if not full_transcript:
            raise EmptyTranscriptError("No recognizable speech was detected in the audio.")

        detected_language = getattr(info, "language", self._language) if info else self._language

        logger.debug(
            "Local speech recognition completed: %d chars, language=%s",
            len(full_transcript),
            detected_language,
        )

        return TranscriptResult(
            transcript=full_transcript,
            audio_duration=audio.duration_seconds,
            language=detected_language,
            confidence=None,
            is_final=True,
        )
