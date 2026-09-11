"""Unit tests for Block 2 Speech-to-Text contracts, adapters, and data models."""

import importlib
import os
import unittest

from app.audio.errors import EmptyAudioError
from app.audio.model import AudioCaptureResult
from app.stt.adapter import FakeSTTAdapter, STTAdapter
from app.stt.errors import (
    STTCancellationError,
    STTError,
    STTTimeoutError,
    STTUnavailableError,
    TranscriptionError,
)
from app.stt.model import TranscriptResult, UserQuestion


class TestBlock2STTContracts(unittest.TestCase):
    """Test suite for Block 2 STT interfaces, UserQuestion contracts, and adapter behavior."""

    def test_transcript_result_fields(self):
        """Requirement C: Transcript contract stores text, duration, language, and confidence."""
        result = TranscriptResult(
            transcript="Find the integral of this function.",
            audio_duration=3.2,
            language="en",
            confidence=0.98,
            is_final=True,
        )

        self.assertEqual(result.transcript, "Find the integral of this function.")
        self.assertEqual(result.audio_duration, 3.2)
        self.assertEqual(result.language, "en")
        self.assertEqual(result.confidence, 0.98)
        self.assertTrue(result.is_final)
        self.assertFalse(result.is_empty)
        self.assertGreater(result.timestamp, 0)

    def test_transcript_result_empty_check(self):
        """Verify is_empty property on empty or whitespace transcript."""
        empty_res = TranscriptResult(transcript="   ", audio_duration=1.0)
        self.assertTrue(empty_res.is_empty)

    def test_user_question_contract_conversion(self):
        """Requirement C: UserQuestion contract aligns with SRS Block 3 input specification."""
        result = TranscriptResult(
            transcript="  Explain this equation.  ",
            audio_duration=2.5,
            language="en",
            confidence=0.92,
        )

        question = UserQuestion.from_transcript_result(result)
        self.assertIsInstance(question, UserQuestion)
        self.assertEqual(question.transcript, "Explain this equation.")
        self.assertEqual(question.audio_duration, 2.5)
        self.assertEqual(question.language, "en")
        self.assertEqual(question.confidence, 0.92)

        data_dict = question.to_dict()
        self.assertEqual(data_dict["transcript"], "Explain this equation.")
        self.assertEqual(data_dict["audio_duration"], 2.5)
        self.assertEqual(data_dict["language"], "en")
        self.assertEqual(data_dict["confidence"], 0.92)

    def test_fake_stt_adapter_transcription(self):
        """Requirement D: STT adapter converts audio capture into deterministic transcript."""
        adapter = FakeSTTAdapter(
            fake_transcript="How do I solve step 2?",
            confidence=0.96,
            language="en",
        )
        self.assertIsInstance(adapter, STTAdapter)

        audio = AudioCaptureResult(
            raw_bytes=b"\x00\x01" * 16000,
            duration_seconds=2.0,
            sample_rate=16000,
        )

        result = adapter.transcribe(audio)
        self.assertIsInstance(result, TranscriptResult)
        self.assertEqual(result.transcript, "How do I solve step 2?")
        self.assertEqual(result.audio_duration, 2.0)
        self.assertEqual(result.confidence, 0.96)
        self.assertEqual(result.language, "en")
        self.assertEqual(adapter.call_count, 1)

    def test_fake_stt_adapter_rejects_empty_audio(self):
        """Requirement D: STT adapter rejects empty audio buffers."""
        adapter = FakeSTTAdapter()
        empty_audio = AudioCaptureResult(raw_bytes=b"", duration_seconds=0.0)

        with self.assertRaises(EmptyAudioError):
            adapter.transcribe(empty_audio)

    def test_fake_stt_adapter_simulated_failure(self):
        """Requirement D: Adapter failures map into Block 2 errors without crashing."""
        adapter = FakeSTTAdapter(
            should_fail=True,
            error_to_raise=STTUnavailableError("STT service unavailable."),
        )
        audio = AudioCaptureResult(raw_bytes=b"\x01\x02" * 100, duration_seconds=1.0)

        with self.assertRaises(STTUnavailableError) as ctx:
            adapter.transcribe(audio)

        self.assertIn("STT service unavailable", str(ctx.exception))

    def test_stt_error_hierarchy(self):
        """Verify STT error hierarchy."""
        self.assertTrue(issubclass(STTUnavailableError, STTError))
        self.assertTrue(issubclass(STTTimeoutError, STTError))
        self.assertTrue(issubclass(TranscriptionError, STTError))
        self.assertTrue(issubclass(STTCancellationError, STTError))

    def test_session_privacy_no_disk_writes(self):
        """Requirement E: Session privacy: no audio or transcripts written to disk."""
        adapter = FakeSTTAdapter(fake_transcript="Ephemeral test question.")
        audio = AudioCaptureResult(
            raw_bytes=b"\x00\x02" * 8000, duration_seconds=1.0
        )
        result = adapter.transcribe(audio)

        self.assertEqual(result.transcript, "Ephemeral test question.")
        self.assertFalse(os.path.exists("captures/test_audio.wav"))
        self.assertFalse(os.path.exists("audio_temp"))

    def test_stt_modules_do_not_import_pyside6(self):
        """Verify architectural boundary: pure STT modules do not depend on PySide6."""
        stt_modules = [
            "app.stt.errors",
            "app.stt.model",
            "app.stt.adapter",
        ]

        for mod_name in stt_modules:
            mod = importlib.import_module(mod_name)
            for attr_name, attr_val in vars(mod).items():
                if hasattr(attr_val, "__module__") and attr_val.__module__:
                    self.assertFalse(
                        attr_val.__module__.startswith("PySide6"),
                        f"Module {mod_name} imports PySide6 class {attr_val}!",
                    )


if __name__ == "__main__":
    unittest.main()
