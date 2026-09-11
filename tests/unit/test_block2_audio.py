"""Unit tests for Block 2 audio capture contracts and data models."""

import importlib
import os
import unittest

from app.audio.errors import (
    AudioCancellationError,
    AudioCaptureError,
    AudioError,
    EmptyAudioError,
    MicrophoneAccessDeniedError,
    MicrophoneUnavailableError,
)
from app.audio.model import AudioCaptureResult
from app.audio.service import AudioCaptureService, FakeAudioCaptureService


class TestBlock2AudioContracts(unittest.TestCase):
    """Test suite for Block 2 audio capture interfaces, lifecycle, and memory guarantees."""

    def test_audio_capture_result_in_memory(self):
        """Requirement A: Audio result remains entirely in memory."""
        raw_pcm = b"\x01\x00\x02\x00" * 8000  # 1 second of 16kHz 16-bit mono
        result = AudioCaptureResult(
            raw_bytes=raw_pcm,
            duration_seconds=1.0,
            sample_rate=16000,
            channels=1,
            sample_width=2,
            encoding="pcm_s16le",
        )

        self.assertEqual(result.byte_count, 32000)
        self.assertEqual(result.duration_seconds, 1.0)
        self.assertEqual(result.sample_rate, 16000)
        self.assertEqual(result.channels, 1)
        self.assertEqual(result.sample_width, 2)
        self.assertEqual(result.encoding, "pcm_s16le")
        self.assertFalse(result.is_empty)

        # Confirm no temporary files created on disk
        self.assertFalse(os.path.exists("audio_temp"))
        self.assertFalse(os.path.exists("temp_audio.wav"))

    def test_audio_capture_result_empty_check(self):
        """Verify is_empty property on empty audio buffer."""
        empty = AudioCaptureResult(raw_bytes=b"", duration_seconds=0.0)
        self.assertTrue(empty.is_empty)
        self.assertEqual(empty.byte_count, 0)

    def test_audio_capture_service_lifecycle(self):
        """Requirement B: Audio capture contract lifecycle (init, start, stop)."""
        service = FakeAudioCaptureService(fake_duration_seconds=2.0)
        self.assertIsInstance(service, AudioCaptureService)

        # Initially not recording
        self.assertFalse(service.is_recording)

        # Start -> recording
        service.start_recording()
        self.assertTrue(service.is_recording)

        # Stop -> not recording + returns valid AudioCaptureResult
        result = service.stop_recording()
        self.assertFalse(service.is_recording)
        self.assertIsInstance(result, AudioCaptureResult)
        self.assertEqual(result.duration_seconds, 2.0)
        self.assertFalse(result.is_empty)

    def test_audio_capture_cancel_lifecycle(self):
        """Requirement B: Cancel stops recording and is safe/idempotent."""
        service = FakeAudioCaptureService()

        # Cancel when not recording is a safe no-op
        service.cancel_recording()
        self.assertFalse(service.is_recording)

        # Start then cancel
        service.start_recording()
        self.assertTrue(service.is_recording)

        service.cancel_recording()
        self.assertFalse(service.is_recording)

        # Repeated cancel does not crash
        service.cancel_recording()
        service.cancel_recording()
        self.assertFalse(service.is_recording)

    def test_audio_capture_invalid_transitions_raise(self):
        """Requirement B: Invalid start/stop transitions raise deterministic errors."""
        service = FakeAudioCaptureService()

        # Stopping while not recording raises AudioCaptureError
        with self.assertRaises(AudioCaptureError):
            service.stop_recording()

        # Starting while already recording raises AudioCaptureError
        service.start_recording()
        with self.assertRaises(AudioCaptureError):
            service.start_recording()

        # Clean up
        service.cancel_recording()

    def test_audio_error_hierarchy(self):
        """Verify audio error contract inheritance."""
        self.assertTrue(issubclass(MicrophoneUnavailableError, AudioError))
        self.assertTrue(issubclass(MicrophoneAccessDeniedError, AudioError))
        self.assertTrue(issubclass(AudioCaptureError, AudioError))
        self.assertTrue(issubclass(EmptyAudioError, AudioError))
        self.assertTrue(issubclass(AudioCancellationError, AudioError))

    def test_audio_modules_do_not_import_pyside6(self):
        """Verify architectural boundary: pure audio modules do not depend on PySide6."""
        audio_modules = [
            "app.audio.errors",
            "app.audio.model",
            "app.audio.recorder",
            "app.audio.service",
        ]

        for mod_name in audio_modules:
            mod = importlib.import_module(mod_name)
            for attr_name, attr_val in vars(mod).items():
                if hasattr(attr_val, "__module__") and attr_val.__module__:
                    self.assertFalse(
                        attr_val.__module__.startswith("PySide6"),
                        f"Module {mod_name} imports PySide6 class {attr_val}!",
                    )


if __name__ == "__main__":
    unittest.main()
