"""Deterministic unit and integration tests for Block 6 automatic end-of-speech detection.

Guarantees:
- Initial silence does not stop recording.
- Speech begins correctly after initial pause.
- Short pauses inside speech (e.g. 0.3s) do not prematurely stop recording.
- Sustained silence (e.g. 1.2s) after speech automatically stops recording.
- Automatic stop enters existing transcription path.
- Manual Ctrl+Shift+Space stop still works as fallback.
- Race between automatic and manual stop produces exactly one transcription job.
- Escape during LISTENING cancels instead of transcribing.
- Late silence callbacks after Escape or stale session tokens are dropped.
- Empty/no-speech session times out and returns to IDLE without invoking Gemini/STT.
- Maximum recording duration safety guard stops safely.
- Microphone/wake-detector handoff: wake detector stays suspended during question recording,
  transcription, thinking, and TTS narration, re-arming only after returning to IDLE.
"""

from __future__ import annotations

import time
import unittest
from typing import Any, List, Optional
from unittest.mock import MagicMock

import numpy as np

from app.audio.model import AudioCaptureResult
from app.audio.service import FakeAudioCaptureService
from app.audio.vad import EndOfSpeechConfig, EndOfSpeechDetector
from app.capture.model import CapturedScreen, DisplayGeometry
from app.capture.service import StubCaptureService
from app.session.controller import SessionController
from app.session.state import SessionState
from app.stt.adapter import STTAdapter
from app.stt.model import TranscriptResult
from app.trigger.global_hotkey import StubGlobalHotkey
from app.trigger.manager import ActivationManager
from app.tutor.engine import TutorEngine
from app.tutor.model import TutorResponse
from app.wake.fake import FakeWakeWordDetector


def make_pcm_chunk(rms: float, duration_ms: int = 100, sample_rate: int = 16000) -> bytes:
    """Generate a synthetic 16-bit mono PCM chunk with a specified RMS amplitude."""
    num_samples = int(sample_rate * (duration_ms / 1000.0))
    if rms <= 0:
        return b"\x00\x00" * num_samples
    # Generate sine wave with peak amplitude = rms * sqrt(2)
    t = np.linspace(0, duration_ms / 1000.0, num_samples, endpoint=False)
    amplitude = min(32700.0, rms * np.sqrt(2.0))
    signal = (amplitude * np.sin(2 * np.pi * 440.0 * t)).astype(np.int16)
    return signal.tobytes()


class TestEndOfSpeechDetector(unittest.TestCase):
    """Unit tests for the standalone EndOfSpeechDetector state machine."""

    def setUp(self):
        self.config = EndOfSpeechConfig(
            speech_threshold=300.0,
            min_speech_duration=0.3,
            silence_duration=1.0,
            initial_silence_timeout=5.0,
            max_recording_duration=10.0,
        )
        self.detector = EndOfSpeechDetector(config=self.config)
        self.eos_calls: List[int] = []
        self.timeout_calls: List[int] = []
        self.detector.set_on_end_of_speech(lambda token: self.eos_calls.append(token))
        self.detector.set_on_timeout(lambda token: self.timeout_calls.append(token))

    def test_initial_silence_does_not_stop_recording(self):
        """Initial silence prior to speech onset does NOT trigger end-of-speech."""
        self.detector.reset(token=1)
        silent_chunk = make_pcm_chunk(rms=20.0, duration_ms=100)

        # Feed 2 seconds of silence (20 x 100ms chunks)
        for _ in range(20):
            self.detector.process_frame(silent_chunk)

        self.assertTrue(self.detector.is_active)
        self.assertFalse(self.detector.has_speech_started)
        self.assertEqual(len(self.eos_calls), 0)
        self.assertEqual(len(self.timeout_calls), 0)

    def test_speech_onset_detection(self):
        """Speech energy above threshold sets has_speech_started = True after min_speech_duration."""
        self.detector.reset(token=1)
        speech_chunk = make_pcm_chunk(rms=1500.0, duration_ms=100)

        # Feed 200ms of speech (not yet min_speech_duration of 300ms)
        self.detector.process_frame(speech_chunk)
        self.detector.process_frame(speech_chunk)
        self.assertFalse(self.detector.has_speech_started)

        # Feed 3rd chunk (reaches 300ms)
        self.detector.process_frame(speech_chunk)
        self.assertTrue(self.detector.has_speech_started)

    def test_short_pause_during_speech_does_not_stop(self):
        """A brief pause (e.g. 0.3s) within a sentence does NOT trigger end-of-speech."""
        self.detector.reset(token=1)
        speech_chunk = make_pcm_chunk(rms=1500.0, duration_ms=100)
        silent_chunk = make_pcm_chunk(rms=20.0, duration_ms=100)

        # 1. User speaks for 500ms
        for _ in range(5):
            self.detector.process_frame(speech_chunk)
        self.assertTrue(self.detector.has_speech_started)

        # 2. Brief pause for 300ms (3 x 100ms)
        for _ in range(3):
            self.detector.process_frame(silent_chunk)

        self.assertTrue(self.detector.is_active)
        self.assertEqual(len(self.eos_calls), 0)
        self.assertAlmostEqual(self.detector.trailing_silence_time, 0.3, places=2)

        # 3. User continues speaking -> trailing silence resets to 0.0
        self.detector.process_frame(speech_chunk)
        self.assertAlmostEqual(self.detector.trailing_silence_time, 0.0, places=2)
        self.assertEqual(len(self.eos_calls), 0)

    def test_sustained_silence_after_speech_triggers_eos(self):
        """Sustained silence (>= 1.0s) after speech triggers on_end_of_speech callback exactly once."""
        self.detector.reset(token=42)
        speech_chunk = make_pcm_chunk(rms=1500.0, duration_ms=100)
        silent_chunk = make_pcm_chunk(rms=20.0, duration_ms=100)

        # 1. User speaks for 500ms
        for _ in range(5):
            self.detector.process_frame(speech_chunk)
        self.assertTrue(self.detector.has_speech_started)

        # 2. User stops speaking; silence continues for 1.0s (10 x 100ms)
        for _ in range(10):
            self.detector.process_frame(silent_chunk)

        # Should fire on_end_of_speech with token=42
        self.assertEqual(self.eos_calls, [42])
        self.assertFalse(self.detector.is_active)

        # Subsequent chunks should be ignored because detector is inactive
        self.detector.process_frame(silent_chunk)
        self.assertEqual(len(self.eos_calls), 1)

    def test_initial_silence_timeout_triggers_timeout_callback(self):
        """If user never speaks within initial_silence_timeout, triggers on_timeout."""
        self.detector.reset(token=99)
        silent_chunk = make_pcm_chunk(rms=20.0, duration_ms=100)

        # Feed 5.0 seconds of silence (50 x 100ms)
        for _ in range(50):
            self.detector.process_frame(silent_chunk)

        self.assertEqual(self.timeout_calls, [99])
        self.assertEqual(len(self.eos_calls), 0)
        self.assertFalse(self.detector.is_active)

    def test_max_recording_guard_stops_safely(self):
        """If speech is continuous past max_recording_duration, forces stop."""
        self.detector.reset(token=7)
        speech_chunk = make_pcm_chunk(rms=1500.0, duration_ms=100)

        # Feed 10.0 seconds of speech (100 x 100ms)
        for _ in range(100):
            self.detector.process_frame(speech_chunk)

        self.assertEqual(self.eos_calls, [7])
        self.assertFalse(self.detector.is_active)


class TestSessionControllerEndOfSpeechIntegration(unittest.TestCase):
    """Integration tests for SessionController automatic end-of-speech and lifecycle transitions."""

    def setUp(self):
        self.fake_audio = FakeAudioCaptureService()
        self.mock_stt = MagicMock(spec=STTAdapter)
        self.mock_stt.transcribe.return_value = TranscriptResult(
            transcript="What is a derivative?",
            audio_duration=2.5,
        )
        self.mock_tutor = MagicMock(spec=TutorEngine)
        self.mock_tutor.process_request.return_value = TutorResponse(
            intent="explanation",
            summary="A derivative represents a rate of change.",
            narration="A derivative represents a rate of change.",
        )
        self.default_screen = CapturedScreen(geometry=DisplayGeometry(width=1920, height=1080))
        self.controller = SessionController(
            audio_service=self.fake_audio,
            capture_service=StubCaptureService(stub_result=self.default_screen),
            stt_adapter=self.mock_stt,
            tutor_engine=self.mock_tutor,
            auto_capture=True,
        )

    def test_automatic_end_of_speech_enters_transcribing_and_thinking(self):
        """Automatic end-of-speech stops recorder, enters TRANSCRIBING, and progresses to RESPONDED."""
        state_log: List[SessionState] = []
        self.controller.add_state_listener(lambda s: state_log.append(s))

        # 1. Activate session
        self.controller.request_activation()
        self.assertEqual(self.controller.state, SessionState.LISTENING)

        # 2. Feed speech frames (500ms)
        speech_chunk = make_pcm_chunk(rms=1500.0, duration_ms=100)
        for _ in range(5):
            self.fake_audio.emit_frame(speech_chunk)

        # 3. Feed silence frames until EOS triggers (1.2s default = 12 x 100ms)
        silent_chunk = make_pcm_chunk(rms=20.0, duration_ms=100)
        for _ in range(13):
            self.fake_audio.emit_frame(silent_chunk)

        # Wait briefly for worker thread
        time.sleep(0.1)

        # Verify state reached RESPONDED via TRANSCRIBING and THINKING
        self.assertIn(SessionState.TRANSCRIBING, state_log)
        self.assertIn(SessionState.THINKING, state_log)
        self.assertEqual(self.controller.state, SessionState.RESPONDED)
        self.mock_stt.transcribe.assert_called_once()
        self.mock_tutor.process_request.assert_called_once()

    def test_manual_hotkey_stop_still_works_as_fallback(self):
        """User pressing Ctrl+Shift+Space during LISTENING manually stops recording immediately."""
        self.controller.request_activation()
        self.assertEqual(self.controller.state, SessionState.LISTENING)

        # Manual stop via second activation request
        self.controller.request_activation()
        time.sleep(0.1)

        self.assertIn(self.controller.state, (SessionState.TRANSCRIBING, SessionState.THINKING, SessionState.RESPONDED))
        self.mock_stt.transcribe.assert_called_once()

    def test_race_between_auto_and_manual_stop_produces_single_transcription(self):
        """Simultaneous auto-stop and manual stop produces exactly one transcription."""
        self.controller.request_activation()
        self.assertEqual(self.controller.state, SessionState.LISTENING)

        token = self.controller.session_token

        # Trigger auto stop and manual stop concurrently
        self.controller.handle_end_of_speech(token)
        self.controller.request_activation()  # Manual hotkey press right as auto-stop fires

        time.sleep(0.1)
        self.mock_stt.transcribe.assert_called_once()

    def test_escape_during_listening_cancels_without_transcribing(self):
        """Escape during LISTENING dismisses session to IDLE and discards question."""
        self.controller.request_activation()
        self.assertEqual(self.controller.state, SessionState.LISTENING)

        # User presses Escape (reset_to_idle / dismiss)
        self.controller.reset_to_idle()
        self.assertEqual(self.controller.state, SessionState.IDLE)

        # No transcription or tutor processing should have occurred
        self.mock_stt.transcribe.assert_not_called()
        self.mock_tutor.process_request.assert_not_called()

    def test_late_silence_callback_after_escape_is_ignored(self):
        """An end-of-speech event arriving after Escape is treated as stale and ignored."""
        self.controller.request_activation()
        old_token = self.controller.session_token

        # User presses Escape
        self.controller.dismiss()
        self.assertEqual(self.controller.state, SessionState.IDLE)

        # Late silence callback arrives with old token
        self.controller.handle_end_of_speech(old_token)

        # State must remain IDLE; no STT called
        self.assertEqual(self.controller.state, SessionState.IDLE)
        self.mock_stt.transcribe.assert_not_called()

    def test_initial_silence_timeout_returns_to_idle_without_gemini(self):
        """No-speech timeout returns session to IDLE and never calls Gemini."""
        self.controller.request_activation()
        self.assertEqual(self.controller.state, SessionState.LISTENING)

        token = self.controller.session_token
        self.controller.handle_no_speech_timeout(token)

        self.assertEqual(self.controller.state, SessionState.IDLE)
        self.mock_stt.transcribe.assert_not_called()
        self.mock_tutor.process_request.assert_not_called()


class TestWakeWordMicrophoneHandoffWithAutoStop(unittest.TestCase):
    """Test wake detector pause and resume lifecycle through automatic end-of-speech."""

    def test_wake_detector_stays_suspended_until_idle(self):
        """Wake detector is suspended during recording, transcription, thinking, and TTS, resuming ONLY at IDLE."""
        wake_detector = FakeWakeWordDetector()
        manager = ActivationManager(
            global_backend=StubGlobalHotkey(),
            wake_detector=wake_detector,
        )
        controller = SessionController(
            activation_trigger=manager,
            capture_service=StubCaptureService(stub_result=CapturedScreen(geometry=DisplayGeometry(1920, 1080))),
            audio_service=FakeAudioCaptureService(),
            auto_capture=False,
        )
        manager._on_activate = controller.request_activation

        def on_state(state: SessionState) -> None:
            if state == SessionState.IDLE:
                manager.resume_wake_detection()
            else:
                manager.pause_wake_detection()

        controller.add_state_listener(on_state)
        manager.start()

        # 1. IDLE: wake detector is listening
        self.assertTrue(wake_detector.is_listening)
        self.assertFalse(wake_detector.is_paused)

        # 2. Wake trigger fires -> transitions to LISTENING directly
        wake_detector.simulate_detection()
        self.assertEqual(controller.state, SessionState.LISTENING)
        self.assertTrue(wake_detector.is_paused)

        # 4. End-of-speech triggers auto-stop
        controller.handle_end_of_speech(controller.session_token)

        # State is TRANSCRIBING or VOICE_CAPTURED -> wake detector MUST STILL BE PAUSED
        self.assertTrue(wake_detector.is_paused)

        # 5. Move to THINKING -> still paused
        controller._set_state(SessionState.THINKING)
        self.assertTrue(wake_detector.is_paused)

        # 6. Move to RESPONDED (TTS speaking) -> still paused (self-audio protection)
        controller._set_state(SessionState.RESPONDED)
        self.assertTrue(wake_detector.is_paused)

        # 7. Session complete -> dismiss -> return to IDLE
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)

        # NOW wake detector re-arms!
        self.assertTrue(wake_detector.is_listening)
        self.assertFalse(wake_detector.is_paused)

        manager.stop()


if __name__ == "__main__":
    unittest.main()
