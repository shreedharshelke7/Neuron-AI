"""Unit tests for Block 2: Local Whisper Speech-to-Text Adapter.

100% offline, zero network requests, mock WhisperModel.
"""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from app.audio.model import AudioCaptureResult
from app.stt.errors import (
    EmptyTranscriptError,
    STTError,
    STTUnavailableError,
    TranscriptionError,
)
from app.stt.model import TranscriptResult
from app.stt.whisper_stt import LocalWhisperSTTAdapter


class TestLocalWhisperSTTAdapter(unittest.TestCase):
    """Offline unit test suite for LocalWhisperSTTAdapter."""

    def setUp(self) -> None:
        self.sample_rate = 16000
        self.channels = 1
        self.raw_pcm = b"\x00\x00" * 16000  # 1.0s 16kHz mono 16-bit PCM
        self.test_audio = AudioCaptureResult(
            raw_bytes=self.raw_pcm,
            duration_seconds=1.0,
            sample_rate=self.sample_rate,
            channels=self.channels,
            sample_width=2,
        )

    def _create_mock_model(self, segments_texts=None, language="en"):
        """Helper to create a mock faster-whisper model returning specified text segments."""
        model = MagicMock()
        segments = []
        if segments_texts is not None:
            for text in segments_texts:
                seg = MagicMock()
                seg.text = text
                segments.append(seg)

        info = MagicMock()
        info.language = language
        info.duration = 1.0

        model.transcribe.return_value = (iter(segments), info)
        return model

    def test_construction_is_lazy_and_side_effect_free(self) -> None:
        """Constructor must NOT load model or open network."""
        factory_called = False

        def mock_factory():
            nonlocal factory_called
            factory_called = True
            return MagicMock()

        adapter = LocalWhisperSTTAdapter(
            model_size_or_path="base.en",
            device="cpu",
            compute_type="int8",
            model_factory=mock_factory,
        )

        self.assertFalse(factory_called)
        self.assertIsNone(adapter._model)
        self.assertEqual(adapter.model_size_or_path, "base.en")
        self.assertEqual(adapter.device, "cpu")
        self.assertEqual(adapter.compute_type, "int8")

    def test_first_transcribe_lazily_loads_model(self) -> None:
        """Model must be loaded only upon first call to transcribe()."""
        factory_called = False
        mock_model = self._create_mock_model(segments_texts=["Test question."])

        def mock_factory():
            nonlocal factory_called
            factory_called = True
            return mock_model

        adapter = LocalWhisperSTTAdapter(model_factory=mock_factory)
        self.assertFalse(factory_called)

        result = adapter.transcribe(self.test_audio)

        self.assertTrue(factory_called)
        self.assertEqual(result.transcript, "Test question.")

    def test_raw_pcm_to_float32_waveform_conversion(self) -> None:
        """Raw 16-bit signed PCM is converted to normalized float32 waveform."""
        mock_model = self._create_mock_model(segments_texts=["Waveform test."])
        adapter = LocalWhisperSTTAdapter(model_factory=lambda: mock_model)

        # Non-zero PCM bytes: 16000 at maximum amplitude (32767)
        pcm_bytes = (np.array([16384, -16384], dtype=np.int16)).tobytes()
        audio = AudioCaptureResult(
            raw_bytes=pcm_bytes,
            duration_seconds=0.1,
            sample_rate=16000,
            channels=1,
            sample_width=2,
        )

        adapter.transcribe(audio)

        mock_model.transcribe.assert_called_once()
        waveform_arg = mock_model.transcribe.call_args[0][0]

        self.assertIsInstance(waveform_arg, np.ndarray)
        self.assertEqual(waveform_arg.dtype, np.float32)
        self.assertAlmostEqual(waveform_arg[0], 0.5, places=3)
        self.assertAlmostEqual(waveform_arg[1], -0.5, places=3)

    def test_single_and_multiple_segments_joined(self) -> None:
        """Sequential segments are concatenated cleanly with spaces."""
        mock_model = self._create_mock_model(
            segments_texts=["What is the derivative", "of x squared?"]
        )
        adapter = LocalWhisperSTTAdapter(model_factory=lambda: mock_model)

        result = adapter.transcribe(self.test_audio)

        self.assertEqual(result.transcript, "What is the derivative of x squared?")
        self.assertEqual(result.language, "en")
        self.assertEqual(result.audio_duration, 1.0)
        self.assertTrue(result.is_final)

    def test_empty_audio_buffer_raises_empty_transcript_error(self) -> None:
        """Empty audio buffer raises EmptyTranscriptError before model is invoked."""
        mock_factory = MagicMock()
        adapter = LocalWhisperSTTAdapter(model_factory=mock_factory)

        empty_audio = AudioCaptureResult(
            raw_bytes=b"",
            duration_seconds=0.0,
            sample_rate=16000,
            channels=1,
            sample_width=2,
        )

        with self.assertRaises(EmptyTranscriptError):
            adapter.transcribe(empty_audio)

        mock_factory.assert_not_called()

    def test_empty_results_raise_empty_transcript_error(self) -> None:
        """Model returning no speech segments raises EmptyTranscriptError."""
        mock_model = self._create_mock_model(segments_texts=[])
        adapter = LocalWhisperSTTAdapter(model_factory=lambda: mock_model)

        with self.assertRaises(EmptyTranscriptError):
            adapter.transcribe(self.test_audio)

    def test_whitespace_only_results_raise_empty_transcript_error(self) -> None:
        """Model returning only whitespace segments raises EmptyTranscriptError."""
        mock_model = self._create_mock_model(segments_texts=["   ", "\t \n"])
        adapter = LocalWhisperSTTAdapter(model_factory=lambda: mock_model)

        with self.assertRaises(EmptyTranscriptError):
            adapter.transcribe(self.test_audio)

    def test_model_load_failure_maps_to_stt_unavailable_error(self) -> None:
        """Failure to load or download model maps to STTUnavailableError."""
        def failing_factory():
            raise RuntimeError("HuggingFace model download connection failed.")

        adapter = LocalWhisperSTTAdapter(model_factory=failing_factory)

        with self.assertRaises(STTUnavailableError) as ctx:
            adapter.transcribe(self.test_audio)

        self.assertIn("Failed to load local speech recognition model", str(ctx.exception))

    def test_transcription_failure_maps_to_transcription_error(self) -> None:
        """Runtime decoding failure maps to TranscriptionError."""
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("CTranslate2 compute error")
        adapter = LocalWhisperSTTAdapter(model_factory=lambda: mock_model)

        with self.assertRaises(TranscriptionError) as ctx:
            adapter.transcribe(self.test_audio)

        self.assertIn("Local speech recognition failed", str(ctx.exception))

    def test_no_filesystem_audio_write(self) -> None:
        """Transcribing in-memory audio does not write any files to disk."""
        mock_model = self._create_mock_model(segments_texts=["Memory only."])
        adapter = LocalWhisperSTTAdapter(model_factory=lambda: mock_model)

        with patch("builtins.open") as mock_open:
            adapter.transcribe(self.test_audio)
            mock_open.assert_not_called()

    def test_provider_objects_do_not_leak_into_transcript_result(self) -> None:
        """TranscriptResult must be standard dataclass without faster-whisper types."""
        mock_model = self._create_mock_model(segments_texts=["Clean contract."])
        adapter = LocalWhisperSTTAdapter(model_factory=lambda: mock_model)

        result = adapter.transcribe(self.test_audio)

        self.assertIsInstance(result, TranscriptResult)
        self.assertIsInstance(result.transcript, str)
        self.assertIsInstance(result.language, str)
        self.assertIsInstance(result.audio_duration, float)
        self.assertIsInstance(result.is_final, bool)

    def test_whisper_stt_module_does_not_import_pyside6(self) -> None:
        """app.stt.whisper_stt must remain completely decoupled from PySide6."""
        import subprocess

        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import app.stt.whisper_stt; "
                "pyside_mods = [m for m in sys.modules if 'PySide6' in m]; "
                "assert len(pyside_mods) == 0, f'PySide6 imported: {pyside_mods}'",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"app.stt.whisper_stt imports PySide6: {proc.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
