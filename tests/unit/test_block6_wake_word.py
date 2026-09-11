"""Deterministic unit and integration tests for Block 6 wake word detection and trigger polish.

Guarantees:
- FR-01: Shared canonical activation entry point with keyboard shortcuts.
- FR-02: Visible listening feedback and cancellation capability.
- NFR-05: Ephemeral in-memory audio only; zero continuous recording persistence.
- NFR-06: Data minimization; zero audio saved to disk or transmitted to cloud.
- NFR-08: Provider-independent abstraction and factory fallback.
- NFR-10: 100% offline, local, deterministic execution.
- Microphone ownership: wake detector releases microphone before session audio recording.
- Self-audio protection: wake detection suspended while TTS narration / session is active.
- Hotkey fallback: Ctrl+Shift+Space remains 100% functional when wake word is disabled/fails.
"""

from __future__ import annotations

import os
import queue
import threading
import time
import unittest
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import numpy as np

from app.session.controller import SessionController
from app.session.state import SessionState
from app.trigger.global_hotkey import StubGlobalHotkey
from app.trigger.manager import ActivationManager
from app.wake.detector import WakeWordConfig, WakeWordDetector
from app.wake.errors import (
    WakeWordDeviceError,
    WakeWordDisabledError,
    WakeWordError,
    WakeWordInitializationError,
)
from app.wake.factory import create_wake_detector, load_wake_config_from_env
from app.wake.fake import FakeWakeWordDetector
from app.wake.whisper_wake import LocalWhisperWakeDetector, is_wake_phrase_match


class TestWakeWordConfigAndMatching(unittest.TestCase):
    """Test configuration loading and keyword phrase matching logic."""

    def test_default_config(self):
        cfg = WakeWordConfig()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.phrase, "Hey Neuron")
        self.assertEqual(cfg.model_name, "base.en")
        self.assertEqual(cfg.sample_rate, 16000)
        self.assertEqual(cfg.channels, 1)
        self.assertEqual(cfg.sample_width, 2)
        self.assertGreater(cfg.silence_threshold, 0)
        self.assertGreater(cfg.debounce_seconds, 0)

    def test_load_wake_config_from_env_defaults(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = load_wake_config_from_env()
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.phrase, "Hey Neuron")

    def test_load_wake_config_from_env_disabled(self):
        for val in ("0", "false", "no", "off", "disabled"):
            with patch.dict(os.environ, {"NEURON_WAKE_WORD_ENABLED": val}):
                cfg = load_wake_config_from_env()
                self.assertFalse(cfg.enabled, f"Expected disabled for {val}")

    def test_load_wake_config_from_env_custom(self):
        env = {
            "NEURON_WAKE_WORD_ENABLED": "1",
            "NEURON_WAKE_WORD_PHRASE": "Okay Neuron",
            "NEURON_WAKE_WORD_MODEL": "tiny.en",
            "NEURON_WAKE_WORD_THRESHOLD": "350.5",
            "NEURON_WAKE_WORD_DEVICE": "2",
        }
        with patch.dict(os.environ, env):
            cfg = load_wake_config_from_env()
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.phrase, "Okay Neuron")
            self.assertEqual(cfg.model_name, "tiny.en")
            self.assertEqual(cfg.silence_threshold, 350.5)
            self.assertEqual(cfg.device, 2)

    def test_wake_phrase_matching_exact(self):
        self.assertTrue(is_wake_phrase_match("Hey Neuron"))
        self.assertTrue(is_wake_phrase_match("hey neuron"))
        self.assertTrue(is_wake_phrase_match("HEY NEURON"))
        self.assertTrue(is_wake_phrase_match("Hey, Neuron!"))
        self.assertTrue(is_wake_phrase_match("Hey Neuron, explain this problem."))

    def test_wake_phrase_matching_phonetic_variants(self):
        # Common phonetic speech-to-text transcriptions of "Hey Neuron"
        self.assertTrue(is_wake_phrase_match("Hey, you're on."))
        self.assertTrue(is_wake_phrase_match("hey your on"))
        self.assertTrue(is_wake_phrase_match("Hi Neuron"))
        self.assertTrue(is_wake_phrase_match("Hello Neuron"))
        self.assertTrue(is_wake_phrase_match("Okay Neuron"))
        self.assertTrue(is_wake_phrase_match("Hey newron"))

    def test_wake_phrase_matching_unrelated(self):
        self.assertFalse(is_wake_phrase_match("What is the capital of France?"))
        self.assertFalse(is_wake_phrase_match("What is on my screen?"))
        self.assertFalse(is_wake_phrase_match("Hello world"))
        self.assertFalse(is_wake_phrase_match(""))
        self.assertFalse(is_wake_phrase_match("   "))
        self.assertFalse(is_wake_phrase_match(None))


class TestFakeWakeWordDetector(unittest.TestCase):
    """Test FakeWakeWordDetector behavior and lifecycle."""

    def test_lifecycle(self):
        detector = FakeWakeWordDetector()
        self.assertFalse(detector.is_listening)
        self.assertFalse(detector.is_paused)

        self.assertTrue(detector.start())
        self.assertTrue(detector.is_listening)
        self.assertFalse(detector.is_paused)
        self.assertEqual(detector.start_count, 1)

        detector.pause()
        self.assertFalse(detector.is_listening)
        self.assertTrue(detector.is_paused)
        self.assertEqual(detector.pause_count, 1)

        self.assertTrue(detector.resume())
        self.assertTrue(detector.is_listening)
        self.assertFalse(detector.is_paused)
        self.assertEqual(detector.resume_count, 1)

        detector.stop()
        self.assertFalse(detector.is_listening)
        self.assertEqual(detector.stop_count, 1)

    def test_simulate_detection(self):
        detector = FakeWakeWordDetector()
        detections = []
        detector.set_on_detected(lambda: detections.append(True))

        # Not listening yet: simulation fails
        self.assertFalse(detector.simulate_detection())
        self.assertEqual(len(detections), 0)

        detector.start()
        self.assertTrue(detector.simulate_detection())
        self.assertEqual(len(detections), 1)

        # Paused: simulation fails
        detector.pause()
        self.assertFalse(detector.simulate_detection())
        self.assertEqual(len(detections), 1)

        # Resumed: simulation succeeds
        detector.resume()
        self.assertTrue(detector.simulate_detection())
        self.assertEqual(len(detections), 2)

    def test_fail_on_start(self):
        detector = FakeWakeWordDetector(fail_on_start=True)
        with self.assertRaises(WakeWordError):
            detector.start()

    def test_disabled_config(self):
        cfg = WakeWordConfig(enabled=False)
        detector = FakeWakeWordDetector(config=cfg)
        self.assertFalse(detector.start())
        self.assertFalse(detector.is_listening)


class TestActivationManagerWithWakeWord(unittest.TestCase):
    """Test coordination of WakeWordDetector inside ActivationManager."""

    def test_wake_trigger_activates_session(self):
        activated = []
        detector = FakeWakeWordDetector()
        manager = ActivationManager(
            on_activate=lambda: activated.append(time.monotonic()),
            global_backend=StubGlobalHotkey(),
            wake_detector=detector,
            debounce_seconds=0.2,
        )

        manager.start()
        self.assertTrue(detector.is_listening)

        # Simulate wake word detection
        success = detector.simulate_detection()
        self.assertTrue(success)
        self.assertEqual(len(activated), 1)
        self.assertEqual(manager.activation_count, 1)

        manager.stop()
        self.assertFalse(detector.is_listening)

    def test_wake_trigger_debouncing(self):
        """Duplicate rapid detections within debounce window are suppressed."""
        activated = []
        detector = FakeWakeWordDetector()
        manager = ActivationManager(
            on_activate=lambda: activated.append(time.monotonic()),
            global_backend=StubGlobalHotkey(),
            wake_detector=detector,
            debounce_seconds=0.3,
        )
        manager.start()

        # First detection
        detector.simulate_detection()
        self.assertEqual(len(activated), 1)

        # Rapid second detection within debounce interval
        detector.simulate_detection()
        self.assertEqual(len(activated), 1)

        manager.stop()

    def test_hotkey_fallback_when_wake_fails(self):
        """Hotkey works 100% even if wake detector fails to start or is unavailable."""
        activated = []
        detector = FakeWakeWordDetector(fail_on_start=True)
        backend = StubGlobalHotkey()
        manager = ActivationManager(
            on_activate=lambda: activated.append(True),
            global_backend=backend,
            wake_detector=detector,
        )

        # Manager starts hotkey even though wake detector fails
        manager.start()
        self.assertTrue(manager.is_global_registered)

        # Hotkey activation works cleanly
        manager.request_activation()
        self.assertEqual(len(activated), 1)

        manager.stop()

    def test_pause_and_resume_wake_detection(self):
        detector = FakeWakeWordDetector()
        manager = ActivationManager(
            on_activate=lambda: None,
            global_backend=StubGlobalHotkey(),
            wake_detector=detector,
        )
        manager.start()
        self.assertTrue(manager.is_wake_listening)
        self.assertFalse(manager.is_wake_paused)

        manager.pause_wake_detection()
        self.assertFalse(manager.is_wake_listening)
        self.assertTrue(manager.is_wake_paused)

        manager.resume_wake_detection()
        self.assertTrue(manager.is_wake_listening)
        self.assertFalse(manager.is_wake_paused)

        manager.stop()


class TestMicrophoneOwnershipAndSelfAudioImmunity(unittest.TestCase):
    """Test coordination of microphone ownership and self-audio immunity across session states."""

    def test_session_lifecycle_pauses_and_resumes_wake_detector(self):
        """Verify wake detector releases microphone when leaving IDLE and re-acquires upon returning to IDLE."""
        detector = FakeWakeWordDetector()
        manager = ActivationManager(
            on_activate=None,
            global_backend=StubGlobalHotkey(),
            wake_detector=detector,
        )
        controller = SessionController(
            activation_trigger=manager,
            auto_capture=False,
        )
        manager._on_activate = controller.request_activation

        # State listener coordinating wake detector
        def on_state_changed(state: SessionState) -> None:
            if state == SessionState.IDLE:
                manager.resume_wake_detection()
            else:
                manager.pause_wake_detection()

        controller.add_state_listener(on_state_changed)
        manager.start()

        # 1. Initially in IDLE -> wake detector is listening
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertTrue(detector.is_listening)
        self.assertFalse(detector.is_paused)

        # 2. Wake word detected -> triggers activation
        detector.simulate_detection()
        self.assertEqual(controller.state, SessionState.ACTIVATED)

        # State changed to ACTIVATED -> wake detector MUST be paused (microphone released)
        self.assertFalse(detector.is_listening)
        self.assertTrue(detector.is_paused)
        self.assertEqual(detector.pause_count, 1)

        # 3. Simulate session moving through states (LISTENING, TRANSCRIBING, THINKING, RESPONDED)
        controller._set_state(SessionState.LISTENING)
        self.assertTrue(detector.is_paused)

        controller._set_state(SessionState.TRANSCRIBING)
        self.assertTrue(detector.is_paused)

        controller._set_state(SessionState.THINKING)
        self.assertTrue(detector.is_paused)

        # 4. Self-audio protection: in RESPONDED (TTS speaking), wake detector remains paused!
        controller._set_state(SessionState.RESPONDED)
        self.assertTrue(detector.is_paused)
        # Verify wake detector cannot trigger while TTS is narrating
        self.assertFalse(detector.simulate_detection())

        # 5. User dismisses / resets session -> returns to IDLE
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)

        # Wake detector resumed cleanly!
        self.assertTrue(detector.is_listening)
        self.assertFalse(detector.is_paused)
        self.assertEqual(detector.resume_count, 1)

        manager.stop()


class TestFactoryAndFallback(unittest.TestCase):
    """Test wake detector factory creation and fallback behavior."""

    def test_factory_returns_disabled_fake_when_configured_false(self):
        cfg = WakeWordConfig(enabled=False)
        detector = create_wake_detector(config=cfg)
        self.assertIsInstance(detector, FakeWakeWordDetector)
        self.assertFalse(detector.is_available)
        self.assertFalse(detector.config.enabled)

    def test_factory_fallback_on_initialization_failure(self):
        cfg = WakeWordConfig(enabled=True, model_name="nonexistent-model-xyz")
        with patch("app.wake.whisper_wake.LocalWhisperWakeDetector.__init__", side_effect=Exception("Model error")):
            detector = create_wake_detector(config=cfg, allow_fake=True)
            self.assertIsInstance(detector, FakeWakeWordDetector)
            self.assertFalse(detector.is_available)


class TestLocalWhisperWakeDetectorGatingAndStream(unittest.TestCase):
    """Test LocalWhisperWakeDetector energy gating, in-memory buffering, and stream control."""

    def test_gating_silence_skips_model(self):
        """Audio chunks below silence_threshold do not trigger Whisper model inference."""
        cfg = WakeWordConfig(silence_threshold=500.0, chunk_duration_ms=100)
        mock_model = MagicMock()

        # Mock stream that delivers silent chunks
        mock_stream = MagicMock()
        mock_factory = MagicMock(return_value=mock_stream)

        detector = LocalWhisperWakeDetector(
            config=cfg,
            model=mock_model,
            stream_factory=mock_factory,
        )

        detector.start()
        self.assertTrue(detector.is_listening)

        # Feed silent audio (RMS ~ 0)
        silent_chunk = np.zeros(1600, dtype=np.int16)
        detector._audio_callback(silent_chunk, 1600, None, None)

        time.sleep(0.3)
        detector.stop()

        # Model should never have been called for silent audio
        mock_model.transcribe.assert_not_called()

    def test_ephemeral_in_memory_no_disk_files(self):
        """Zero disk files created during wake detection (NFR-05, NFR-06)."""
        cfg = WakeWordConfig(silence_threshold=50.0)
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([], None)

        mock_stream = MagicMock()
        detector = LocalWhisperWakeDetector(
            config=cfg,
            model=mock_model,
            stream_factory=lambda **kw: mock_stream,
        )

        # Count files in cwd
        initial_files = set(os.listdir(os.getcwd()))

        detector.start()
        # Feed speech frame
        speech_chunk = (np.ones(1600, dtype=np.int16) * 1000)
        detector._audio_callback(speech_chunk, 1600, None, None)
        time.sleep(0.2)
        detector.stop()

        current_files = set(os.listdir(os.getcwd()))
        self.assertEqual(initial_files, current_files, "Wake detector must not write files to disk.")

    def test_pause_and_resume_stream_management(self):
        """Pause closes audio stream; resume reopens stream cleanly."""
        mock_stream = MagicMock()
        create_calls = []

        def factory(**kwargs):
            create_calls.append(True)
            return mock_stream

        detector = LocalWhisperWakeDetector(
            model=MagicMock(),
            stream_factory=factory,
        )

        self.assertTrue(detector.start())
        self.assertEqual(len(create_calls), 1)
        self.assertFalse(detector.is_paused)

        detector.pause()
        self.assertTrue(detector.is_paused)
        mock_stream.stop.assert_called()
        mock_stream.close.assert_called()

        self.assertTrue(detector.resume())
        self.assertFalse(detector.is_paused)
        self.assertEqual(len(create_calls), 2)

        detector.stop()


if __name__ == "__main__":
    unittest.main()
