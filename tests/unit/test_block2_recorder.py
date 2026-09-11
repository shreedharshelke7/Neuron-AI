"""Automated unit tests for production SoundDeviceAudioCaptureService in Block 2."""

from __future__ import annotations

import importlib
import os
import unittest
from typing import Any, List, Optional

from app.audio.errors import (
    AudioCaptureError,
    AudioError,
    EmptyAudioError,
    MicrophoneAccessDeniedError,
    MicrophoneUnavailableError,
)
from app.audio.model import AudioCaptureResult
from app.audio.recorder import SoundDeviceAudioCaptureService


class MockRawInputStream:
    """Mock PortAudio stream simulating sounddevice.RawInputStream."""

    def __init__(
        self,
        samplerate: int = 16000,
        channels: int = 1,
        dtype: str = "int16",
        device: Optional[Any] = None,
        callback: Optional[Any] = None,
        fail_on_start: bool = False,
        fail_on_stop: bool = False,
    ) -> None:
        self.samplerate = samplerate
        self.channels = channels
        self.dtype = dtype
        self.device = device
        self.callback = callback
        self.fail_on_start = fail_on_start
        self.fail_on_stop = fail_on_stop

        self.is_started: bool = False
        self.is_stopped: bool = False
        self.is_closed: bool = False
        self.start_calls: int = 0
        self.stop_calls: int = 0
        self.close_calls: int = 0

    def start(self) -> None:
        self.start_calls += 1
        if self.fail_on_start:
            raise RuntimeError("PortAudio device unavailable or open stream failed")
        self.is_started = True

    def stop(self) -> None:
        self.stop_calls += 1
        if self.fail_on_stop:
            raise RuntimeError("PortAudio stream stop failed")
        self.is_stopped = True

    def close(self) -> None:
        self.close_calls += 1
        self.is_closed = True

    def push_audio(self, data: bytes) -> None:
        """Deliver raw audio frames to the service callback."""
        if self.callback:
            # signature: callback(indata, frames, time, status)
            frames = len(data) // (self.channels * 2)
            self.callback(data, frames, None, None)


class TestSoundDeviceAudioCaptureService(unittest.TestCase):
    """Test suite verifying SoundDeviceAudioCaptureService lifecycle, safety, and contracts."""

    def setUp(self) -> None:
        self.created_streams: List[MockRawInputStream] = []

    def _mock_stream_factory(self, **kwargs: Any) -> MockRawInputStream:
        stream = MockRawInputStream(**kwargs)
        self.created_streams.append(stream)
        return stream

    def test_construction_does_not_open_microphone(self) -> None:
        """Requirement 1: Creating service must NOT open microphone or stream."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)

        self.assertEqual(len(self.created_streams), 0)
        self.assertFalse(service.is_recording)

    def test_start_opens_microphone_and_updates_state(self) -> None:
        """Requirements 2 & 3: start_recording opens stream and sets is_recording = True."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)

        service.start_recording()

        self.assertEqual(len(self.created_streams), 1)
        active_stream = self.created_streams[0]
        self.assertTrue(active_stream.is_started)
        self.assertTrue(service.is_recording)

        # Cleanup
        service.cancel_recording()

    def test_audio_chunks_accumulated_in_memory(self) -> None:
        """Requirement 4: Received audio chunks accumulate in memory."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)
        service.start_recording()
        stream = self.created_streams[0]

        # 16kHz, mono, 16-bit (2 bytes/sample) -> 32,000 bytes/sec
        chunk1 = b"\x01\x00" * 8000  # 0.5 sec
        chunk2 = b"\x02\x00" * 8000  # 0.5 sec

        stream.push_audio(chunk1)
        stream.push_audio(chunk2)

        result = service.stop_recording()

        self.assertEqual(result.byte_count, 32000)
        self.assertAlmostEqual(result.duration_seconds, 1.0, places=3)
        self.assertEqual(result.raw_bytes, chunk1 + chunk2)
        self.assertFalse(result.is_empty)

    def test_stop_recording_lifecycle_and_metadata(self) -> None:
        """Requirement 5: stop releases stream, returns result, leaves clean state."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)
        service.start_recording()
        stream = self.created_streams[0]

        stream.push_audio(b"\xaa\xbb" * 4000)

        result = service.stop_recording()

        self.assertTrue(stream.is_stopped)
        self.assertTrue(stream.is_closed)
        self.assertFalse(service.is_recording)

        self.assertIsInstance(result, AudioCaptureResult)
        self.assertEqual(result.sample_rate, 16000)
        self.assertEqual(result.channels, 1)
        self.assertEqual(result.sample_width, 2)
        self.assertEqual(result.encoding, "pcm_s16le")
        self.assertAlmostEqual(result.duration_seconds, 0.25, places=3)

    def test_cancel_recording_lifecycle_and_buffer_discard(self) -> None:
        """Requirement 6: cancel stops stream, clears buffer, resets state."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)
        service.start_recording()
        stream = self.created_streams[0]

        stream.push_audio(b"\x01\x02" * 8000)

        service.cancel_recording()

        self.assertTrue(stream.is_stopped)
        self.assertTrue(stream.is_closed)
        self.assertFalse(service.is_recording)

        # Calling stop now must raise AudioCaptureError because buffer was discarded
        with self.assertRaises(AudioCaptureError):
            service.stop_recording()

    def test_repeated_cancel_is_safe_and_idempotent(self) -> None:
        """Requirement 7: Repeated cancel calls do not throw."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)

        # Cancel when not recording
        service.cancel_recording()
        service.cancel_recording()
        self.assertFalse(service.is_recording)

        # Cancel after start
        service.start_recording()
        service.cancel_recording()
        service.cancel_recording()
        service.cancel_recording()
        self.assertFalse(service.is_recording)

    def test_backend_failure_during_start_maps_to_error(self) -> None:
        """Requirement 8: Backend failure during start maps to Block 2 error hierarchy."""
        def failing_factory(**kwargs: Any) -> MockRawInputStream:
            return MockRawInputStream(fail_on_start=True, **kwargs)

        service = SoundDeviceAudioCaptureService(stream_factory=failing_factory)

        with self.assertRaises(MicrophoneUnavailableError):
            service.start_recording()

        self.assertFalse(service.is_recording)

    def test_permission_denied_maps_to_access_denied_error(self) -> None:
        """Requirement 8b: Permission error maps to MicrophoneAccessDeniedError."""
        def permission_error_factory(**kwargs: Any) -> MockRawInputStream:
            raise PermissionError("Access denied by Windows Privacy Settings")

        service = SoundDeviceAudioCaptureService(stream_factory=permission_error_factory)

        with self.assertRaises(MicrophoneAccessDeniedError):
            service.start_recording()

        self.assertFalse(service.is_recording)

    def test_backend_failure_during_stop_resets_recording_state(self) -> None:
        """Requirement 9: Backend failure during stop does not leave service stuck recording."""
        def stop_failing_factory(**kwargs: Any) -> MockRawInputStream:
            stream = MockRawInputStream(fail_on_stop=True, **kwargs)
            self.created_streams.append(stream)
            return stream

        service = SoundDeviceAudioCaptureService(stream_factory=stop_failing_factory)
        service.start_recording()
        stream = self.created_streams[0]
        stream.push_audio(b"\x01\x00" * 4000)

        with self.assertRaises(AudioCaptureError):
            service.stop_recording()

        # Service must NOT remain stuck in recording state
        self.assertFalse(service.is_recording)
        self.assertTrue(stream.is_closed)

    def test_stop_with_no_usable_audio_raises_empty_audio_error(self) -> None:
        """Requirement 10: Stop with 0 audio frames raises EmptyAudioError."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)
        service.start_recording()
        # No audio pushed to callback
        with self.assertRaises(EmptyAudioError):
            service.stop_recording()

        self.assertFalse(service.is_recording)

    def test_service_reusability_start_cancel_start_stop(self) -> None:
        """Requirement 11: Service can be reused across multiple sessions."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)

        # 1. Start -> cancel
        service.start_recording()
        self.assertTrue(service.is_recording)
        self.created_streams[0].push_audio(b"\x01\x00" * 2000)
        service.cancel_recording()
        self.assertFalse(service.is_recording)

        # 2. Start -> stop
        service.start_recording()
        self.assertTrue(service.is_recording)
        self.created_streams[1].push_audio(b"\x02\x00" * 8000)
        result = service.stop_recording()
        self.assertFalse(service.is_recording)

        self.assertIsInstance(result, AudioCaptureResult)
        self.assertEqual(result.byte_count, 16000)
        self.assertAlmostEqual(result.duration_seconds, 0.5, places=3)

    def test_no_filesystem_audio_write(self) -> None:
        """Requirement 12: No permanent or temporary audio files created on disk."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)
        service.start_recording()
        self.created_streams[0].push_audio(b"\x03\x00" * 8000)
        result = service.stop_recording()

        self.assertFalse(result.is_empty)
        # Check standard potential leak paths
        self.assertFalse(os.path.exists("temp.wav"))
        self.assertFalse(os.path.exists("recording.wav"))
        self.assertFalse(os.path.exists("audio_buffer.pcm"))

    def test_late_callback_after_cancel_or_stop_is_discarded(self) -> None:
        """Callback data arriving after cancel or stop must not mutate idle buffer."""
        service = SoundDeviceAudioCaptureService(stream_factory=self._mock_stream_factory)
        service.start_recording()
        stream = self.created_streams[0]
        service.cancel_recording()

        # Simulate late PortAudio thread buffer flush
        stream.push_audio(b"\xff\xff" * 1000)

        # Starting a new recording must not contain the late chunk
        service.start_recording()
        stream2 = self.created_streams[1]
        fresh_chunk = b"\x10\x20" * 4000
        stream2.push_audio(fresh_chunk)
        result = service.stop_recording()

        self.assertEqual(result.raw_bytes, fresh_chunk)
        self.assertEqual(result.byte_count, 8000)

    def test_recorder_does_not_import_pyside6(self) -> None:
        """Architectural boundary: app.audio.recorder must have zero PySide6 dependencies."""
        mod = importlib.import_module("app.audio.recorder")
        for attr_name, attr_val in vars(mod).items():
            if hasattr(attr_val, "__module__") and attr_val.__module__:
                self.assertFalse(
                    attr_val.__module__.startswith("PySide6"),
                    f"app.audio.recorder imports PySide6 class {attr_val}!",
                )


if __name__ == "__main__":
    unittest.main()
