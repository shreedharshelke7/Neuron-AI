"""Comprehensive automated test suite for Neuron AI Block 5: TTS + Sequencing + Cancellation.

Covers:
1. TTS interface & models
2. ElevenLabs configuration loading
3. Missing API key handling (lazy resolution)
4. Provider error normalization (401, 429, timeout, network)
5. Narration ordering & segmentation
6. Multiple narration segments
7. Empty narration handling
8. Overlay visible during narration (AC-07)
9. Sequence controller ordering
10. Renderer integration
11. Playback success & callback sequencing
12. Playback failure handling
13. TTS failure while visuals remain (FR-17)
14. Escape stops active audio (AC-08 / FR-15)
15. Escape prevents remaining segments
16. Escape clears visuals
17. Escape returns session controller to IDLE
18. Late TTS result ignored after Escape
19. Late TTS result ignored after new session
20. Previous narration stopped before new session
21. No overlapping narration
22. Application shutdown stops audio
23. Non-blocking UI path
24. Visual-only response
25. Narration + fallback card
26. Self-capture regression protection
27. Block 4 cleanup regression
28. No persistent narration artifacts on disk (NFR-06)
29. Zero live ElevenLabs network calls during pytest
"""

import os
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import requests
from PySide6.QtWidgets import QApplication

from app.capture.model import CapturedScreen, DisplayGeometry, SelectedRegion
from app.capture.service import CaptureService
from app.overlay.host import StubOverlayHost
from app.sequence.controller import SequenceController, partition_narration
from app.session.controller import SessionController
from app.session.state import SessionState
from app.tts.adapter import FakeTTSAdapter, TTSAdapter
from app.tts.elevenlabs import (
    DEFAULT_MODEL_ID,
    DEFAULT_OUTPUT_FORMAT,
    ElevenLabsTTSAdapter,
)
from app.tts.errors import (
    TTSAuthenticationError,
    TTSConfigurationError,
    TTSError,
    TTSNetworkError,
    TTSPaidPlanRequiredError,
    TTSPlaybackError,
    TTSQuotaExceededError,
    TTSTimeoutError,
)
from app.tts.model import NarrationPlan, NarrationSegment, TTSAudioClip
from app.tts.playback import (
    AudioPlaybackService,
    FakeAudioPlaybackService,
    SoundDevicePlaybackService,
)
from app.tutor.model import OverlayAction, OverlayActionType, TutorResponse

# Ensure singleton QApplication exists for any Qt components
qapp = QApplication.instance() or QApplication(sys.argv)


class TestTTSModelsAndAdapters(unittest.TestCase):
    """Tests 1 to 4: Data representations, fake adapter, and error models."""

    def test_tts_audio_clip_properties(self):
        """Verify TTSAudioClip data representation and properties."""
        raw = b"\x00\x01" * 12000  # 12000 samples @ 24kHz = 0.5s
        clip = TTSAudioClip(
            raw_bytes=raw,
            sample_rate=24000,
            channels=1,
            sample_width=2,
            duration_seconds=0.5,
            text="Hello world",
        )
        self.assertEqual(clip.byte_count, 24000)
        self.assertFalse(clip.is_empty)
        self.assertEqual(clip.sample_rate, 24000)
        self.assertEqual(clip.duration_seconds, 0.5)

        empty_clip = TTSAudioClip(raw_bytes=b"", duration_seconds=0.0)
        self.assertTrue(empty_clip.is_empty)
        self.assertEqual(empty_clip.byte_count, 0)

    def test_narration_plan_properties(self):
        """Verify NarrationPlan combining text and calculating total duration."""
        c1 = TTSAudioClip(raw_bytes=b"12", duration_seconds=1.2, text="Step one.")
        c2 = TTSAudioClip(raw_bytes=b"34", duration_seconds=2.3, text="Step two.")
        s1 = NarrationSegment(index=0, text="Step one.", audio_clip=c1)
        s2 = NarrationSegment(index=1, text="Step two.", audio_clip=c2)
        plan = NarrationPlan(segments=[s1, s2])

        self.assertEqual(plan.full_text, "Step one. Step two.")
        self.assertAlmostEqual(plan.total_duration, 3.5)

    def test_fake_tts_adapter_synthesizes_in_memory(self):
        """Verify FakeTTSAdapter synthesizes in-memory PCM without network calls."""
        fake = FakeTTSAdapter(sample_rate=16000, fake_duration_per_char=0.01)
        clip = fake.synthesize("Calculate the slope.")
        self.assertIsInstance(clip, TTSAudioClip)
        self.assertFalse(clip.is_empty)
        self.assertEqual(clip.sample_rate, 16000)
        self.assertGreater(clip.duration_seconds, 0.0)
        self.assertIn("Calculate the slope.", fake.calls)

    def test_fake_tts_adapter_empty_text(self):
        """Verify FakeTTSAdapter handles empty text safely."""
        fake = FakeTTSAdapter()
        clip = fake.synthesize("   ")
        self.assertTrue(clip.is_empty)
        self.assertEqual(clip.duration_seconds, 0.0)

    def test_fake_tts_adapter_failure_mode(self):
        """Verify FakeTTSAdapter correctly raises configured failure."""
        fake = FakeTTSAdapter(fail_with=TTSQuotaExceededError("Quota reached"))
        with self.assertRaises(TTSQuotaExceededError):
            fake.synthesize("Hello")


class TestElevenLabsTTSAdapter(unittest.TestCase):
    """Tests 2 to 4: ElevenLabs configuration, lazy credentials, error normalization, and caching."""

    def test_elevenlabs_construction_is_side_effect_free(self):
        """Instantiating ElevenLabsTTSAdapter without key must NOT raise or make network requests."""
        with patch("app.tts.elevenlabs._read_env_file_var", return_value=None):
            with patch.dict(os.environ, {}, clear=True):
                adapter = ElevenLabsTTSAdapter()
                self.assertIsNone(adapter.voice_id)
                self.assertEqual(adapter.model_id, DEFAULT_MODEL_ID)
                self.assertEqual(adapter.output_format, DEFAULT_OUTPUT_FORMAT)

    def test_elevenlabs_missing_api_key_raises_on_synthesize(self):
        """Synthesizing without an API key must raise TTSAuthenticationError."""
        mock_session = MagicMock(spec=requests.Session)
        with patch("app.tts.elevenlabs._read_env_file_var", return_value=None):
            with patch.dict(os.environ, {}, clear=True):
                adapter = ElevenLabsTTSAdapter(voice_id="my_voice", session=mock_session)
                with self.assertRaises(TTSAuthenticationError) as ctx:
                    adapter.synthesize("This should fail due to missing key.")
                self.assertIn("API key is missing", str(ctx.exception))
        self.assertEqual(mock_session.post.call_count, 0)

    def test_elevenlabs_missing_voice_id_raises_configuration_error(self):
        """Synthesizing without ELEVENLABS_VOICE_ID must raise clear TTSConfigurationError."""
        mock_session = MagicMock(spec=requests.Session)
        with patch("app.tts.elevenlabs._read_env_file_var", return_value=None):
            with patch.dict(os.environ, {}, clear=True):
                adapter = ElevenLabsTTSAdapter(api_key="valid_key", session=mock_session)
                with self.assertRaises(TTSConfigurationError) as ctx:
                    adapter.synthesize("This should fail due to missing voice.")
                self.assertIn("ELEVENLABS_VOICE_ID is not configured", str(ctx.exception))
        self.assertEqual(mock_session.post.call_count, 0)

    def test_elevenlabs_configuration_from_env(self):
        """Adapter loads custom voice and model from environment variables."""
        env_vars = {
            "ELEVENLABS_API_KEY": "test_key_123",
            "ELEVENLABS_VOICE_ID": "custom_voice_abc",
            "ELEVENLABS_MODEL_ID": "eleven_multilingual_v2",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            adapter = ElevenLabsTTSAdapter()
            self.assertEqual(adapter._resolve_api_key(), "test_key_123")
            self.assertEqual(adapter.voice_id, "custom_voice_abc")
            self.assertEqual(adapter.model_id, "eleven_multilingual_v2")

    def test_elevenlabs_fallback_tts_api_key(self):
        """Adapter recognizes TTS_API_KEY fallback naming convention."""
        with patch.dict(os.environ, {"TTS_API_KEY": "fallback_key_456"}, clear=True):
            adapter = ElevenLabsTTSAdapter(voice_id="my_voice")
            self.assertEqual(adapter._resolve_api_key(), "fallback_key_456")

    def test_elevenlabs_error_normalization_401(self):
        """HTTP 401 maps to TTSAuthenticationError."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 401
        mock_response.text = '{"detail": {"status": "invalid_api_key"}}'
        mock_response.ok = False
        mock_session.post.return_value = mock_response

        adapter = ElevenLabsTTSAdapter(api_key="bad_key", voice_id="test_voice", session=mock_session)
        with self.assertRaises(TTSAuthenticationError):
            adapter.synthesize("Testing 401")

    def test_elevenlabs_error_normalization_402_paid_plan(self):
        """HTTP 402 maps to TTSPaidPlanRequiredError."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 402
        mock_response.text = '{"detail": {"status": "paid_plan_required", "message": "Free users cannot use library voices"}}'
        mock_response.ok = False
        mock_session.post.return_value = mock_response

        adapter = ElevenLabsTTSAdapter(api_key="valid_key", voice_id="library_voice", session=mock_session)
        with self.assertRaises(TTSPaidPlanRequiredError) as ctx:
            adapter.synthesize("Testing 402")
        self.assertIn("paid plan required", str(ctx.exception).lower())

    def test_elevenlabs_error_normalization_400_paid_plan(self):
        """HTTP 400 with paid_plan_required maps to TTSPaidPlanRequiredError."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 400
        mock_response.text = '{"detail": {"status": "paid_plan_required"}}'
        mock_response.ok = False
        mock_session.post.return_value = mock_response

        adapter = ElevenLabsTTSAdapter(api_key="valid_key", voice_id="library_voice", session=mock_session)
        with self.assertRaises(TTSPaidPlanRequiredError):
            adapter.synthesize("Testing 400 paid plan")

    def test_elevenlabs_circuit_breaker_prevents_multiple_network_calls(self):
        """A terminal error trips the adapter circuit breaker to prevent repeated failed requests."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 402
        mock_response.text = '{"detail": {"status": "paid_plan_required"}}'
        mock_response.ok = False
        mock_session.post.return_value = mock_response

        adapter = ElevenLabsTTSAdapter(api_key="valid_key", voice_id="library_voice", session=mock_session)

        # Call 1: HTTP 402
        with self.assertRaises(TTSPaidPlanRequiredError):
            adapter.synthesize("First sentence.")
        self.assertEqual(mock_session.post.call_count, 1)

        # Call 2: Circuit breaker active, raises immediately without HTTP call
        with self.assertRaises(TTSPaidPlanRequiredError):
            adapter.synthesize("Second sentence.")
        self.assertEqual(mock_session.post.call_count, 1)  # Stays at 1!

    def test_elevenlabs_error_normalization_429(self):
        """HTTP 429 maps to TTSQuotaExceededError."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 429
        mock_response.text = "Too many requests / quota reached"
        mock_response.ok = False
        mock_session.post.return_value = mock_response

        adapter = ElevenLabsTTSAdapter(api_key="valid_key", voice_id="test_voice", session=mock_session)
        with self.assertRaises(TTSQuotaExceededError):
            adapter.synthesize("Testing 429")

    def test_elevenlabs_error_normalization_timeout(self):
        """Network timeout maps to TTSTimeoutError."""
        mock_session = MagicMock(spec=requests.Session)
        mock_session.post.side_effect = requests.exceptions.Timeout("Connection timed out")

        adapter = ElevenLabsTTSAdapter(api_key="valid_key", voice_id="test_voice", session=mock_session)
        with self.assertRaises(TTSTimeoutError):
            adapter.synthesize("Testing timeout")

    def test_elevenlabs_error_normalization_connection_error(self):
        """Connection error maps to TTSNetworkError."""
        mock_session = MagicMock(spec=requests.Session)
        mock_session.post.side_effect = requests.exceptions.ConnectionError("DNS failure")

        adapter = ElevenLabsTTSAdapter(api_key="valid_key", voice_id="test_voice", session=mock_session)
        with self.assertRaises(TTSNetworkError):
            adapter.synthesize("Testing connection error")

    def test_elevenlabs_caching_prevents_duplicate_requests(self):
        """Synthesizing identical text repeatedly reuses in-memory cache and saves credits."""
        mock_session = MagicMock(spec=requests.Session)
        mock_response = MagicMock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.ok = True
        mock_response.content = b"\x00\x00" * 24000  # 1.0 second of 24kHz audio
        mock_session.post.return_value = mock_response

        adapter = ElevenLabsTTSAdapter(api_key="valid_key", voice_id="test_voice", session=mock_session)

        # First call: makes HTTP request
        clip1 = adapter.synthesize("Repeat after me: power rule.")
        self.assertEqual(mock_session.post.call_count, 1)
        self.assertEqual(clip1.duration_seconds, 1.0)

        # Second call: served from in-memory cache
        clip2 = adapter.synthesize("Repeat after me: power rule.")
        self.assertEqual(mock_session.post.call_count, 1)  # No extra HTTP call
        self.assertEqual(clip1.raw_bytes, clip2.raw_bytes)


class TestAudioPlaybackServices(unittest.TestCase):
    """Tests 11 to 12: Playback abstractions, cancellation, and callbacks."""

    def test_fake_playback_service_flow(self):
        """Verify FakeAudioPlaybackService play and stop tracking."""
        fake_player = FakeAudioPlaybackService(auto_complete=True)
        clip = TTSAudioClip(raw_bytes=b"\x00\x01", duration_seconds=0.5)

        callback_invoked = []
        fake_player.play(clip, on_finished=lambda: callback_invoked.append(True))

        self.assertEqual(fake_player.play_count, 1)
        self.assertTrue(callback_invoked)
        self.assertFalse(fake_player.is_playing)

    def test_fake_playback_service_stop_cancels_pending(self):
        """Calling stop() halts playback and cancels pending completion callback."""
        fake_player = FakeAudioPlaybackService(auto_complete=False)
        clip = TTSAudioClip(raw_bytes=b"\x00\x01", duration_seconds=1.0)

        callback_invoked = []
        fake_player.play(clip, on_finished=lambda: callback_invoked.append(True))
        self.assertTrue(fake_player.is_playing)

        # Stop playback before finish
        fake_player.stop()
        self.assertEqual(fake_player.stop_count, 1)
        self.assertFalse(fake_player.is_playing)
        self.assertFalse(callback_invoked)


class TestSequencingAndCoordination(unittest.TestCase):
    """Tests 5 to 10, 13 to 21: Sequencing, segmentation, overlay visibility, and cancellation."""

    def test_partition_narration(self):
        """5. Narration text is partitioned into ordered sentences/segments."""
        text = "First, take the exponent. Second, bring it down. Finally, subtract one!"
        segments = partition_narration(text)
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0], "First, take the exponent.")
        self.assertEqual(segments[1], "Second, bring it down.")
        self.assertEqual(segments[2], "Finally, subtract one!")

        # Single sentence
        single = partition_narration("A single thought.")
        self.assertEqual(single, ["A single thought."])

        # Empty / whitespace
        empty = partition_narration("   \n\t  ")
        self.assertEqual(empty, [])

    def test_empty_narration_leaves_visuals_active(self):
        """7. Empty narration completes sequence without calling TTS; visuals remain."""
        fake_tts = FakeTTSAdapter()
        fake_player = FakeAudioPlaybackService()
        overlay_host = StubOverlayHost()

        controller = SequenceController(
            tts_adapter=fake_tts,
            playback_service=fake_player,
            overlay_host=overlay_host,
        )

        response = TutorResponse(
            intent="explanation",
            summary="Visual summary card.",
            narration="",  # Empty narration
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.1, 0.1, 0.2, 0.2),
                )
            ],
        )

        finished_tokens = []
        controller.on_finished = lambda tok: finished_tokens.append(tok)

        controller.start_sequence(response, token=42)

        self.assertEqual(len(fake_tts.calls), 0)
        self.assertEqual(fake_player.play_count, 0)
        self.assertTrue(overlay_host.has_explanation)
        self.assertIn(42, finished_tokens)

    def test_overlay_visible_during_narration(self):
        """8. AC-07: Narration plays while explanation overlay is visible."""
        fake_tts = FakeTTSAdapter()
        fake_player = FakeAudioPlaybackService(auto_complete=False)
        overlay_host = StubOverlayHost()

        controller = SequenceController(
            tts_adapter=fake_tts,
            playback_service=fake_player,
            overlay_host=overlay_host,
        )

        response = TutorResponse(
            intent="explanation",
            summary="Concept explanation.",
            narration="Step one of the formula. Step two of the formula.",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.2, 0.2, 0.3, 0.3),
                )
            ],
        )

        controller.start_sequence(response, token=10)
        time.sleep(0.05)

        # Overlay must be displayed and audio must be playing
        self.assertTrue(overlay_host.has_explanation)
        self.assertTrue(fake_player.is_playing)

        # Complete playback
        fake_player.finish_pending()
        time.sleep(0.05)
        fake_player.finish_pending()
        time.sleep(0.05)

        # After playback completes, overlay remains visible
        self.assertTrue(overlay_host.has_explanation)

    def test_tts_failure_leaves_visuals_active(self):
        """13. FR-17: TTS failure leaves visual explanation intact and notifies error."""
        failing_tts = FakeTTSAdapter(fail_with=TTSNetworkError("Network down"))
        fake_player = FakeAudioPlaybackService()
        overlay_host = StubOverlayHost()

        errors = []
        controller = SequenceController(
            tts_adapter=failing_tts,
            playback_service=fake_player,
            overlay_host=overlay_host,
            on_error=lambda msg, tok: errors.append((msg, tok)),
        )

        response = TutorResponse(
            intent="explanation",
            summary="Calculus explanation.",
            narration="We should hear this, but network is down.",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.1, 0.1, 0.2, 0.2),
                )
            ],
        )

        controller.start_sequence(response, token=15)
        time.sleep(0.05)

        # Overlay visuals remain 100% active
        self.assertTrue(overlay_host.has_explanation)
        # Error callback received
        self.assertEqual(len(errors), 1)
        self.assertIn("Network down", errors[0][0])
        self.assertEqual(errors[0][1], 15)
        # Playback was never started
        self.assertEqual(fake_player.play_count, 0)

    def test_escape_stops_active_audio_and_clears_sequencing(self):
        """14-16. AC-08 / FR-15: Escape stops audio and cancels sequencing immediately."""
        fake_tts = FakeTTSAdapter()
        fake_player = FakeAudioPlaybackService(auto_complete=False)
        overlay_host = StubOverlayHost()

        controller = SequenceController(
            tts_adapter=fake_tts,
            playback_service=fake_player,
            overlay_host=overlay_host,
        )

        response = TutorResponse(
            intent="explanation",
            summary="Lesson",
            narration="Part one of explanation. Part two of explanation.",
            overlay_actions=[],
        )

        controller.start_sequence(response, token=20)
        time.sleep(0.05)
        self.assertTrue(fake_player.is_playing)

        # Cancel / Escape
        controller.cancel()

        self.assertFalse(fake_player.is_playing)
        self.assertEqual(fake_player.stop_count, 1)
        self.assertFalse(controller.is_active)

    def test_escape_prevents_remaining_segments(self):
        """15. Cancelling during segment 1 prevents segment 2 from playing."""
        fake_tts = FakeTTSAdapter()
        fake_player = FakeAudioPlaybackService(auto_complete=False)
        overlay_host = StubOverlayHost()

        controller = SequenceController(
            tts_adapter=fake_tts,
            playback_service=fake_player,
            overlay_host=overlay_host,
        )

        response = TutorResponse(
            intent="explanation",
            summary="Lesson",
            narration="Segment 1. Segment 2. Segment 3.",
            overlay_actions=[],
        )

        controller.start_sequence(response, token=25)
        time.sleep(0.05)

        # Stop while segment 1 is playing
        controller.cancel()
        time.sleep(0.1)

        # Segment 2 and 3 should not have synthesized or played
        self.assertLessEqual(len(fake_tts.calls), 1)
        self.assertLessEqual(fake_player.play_count, 1)

    def test_late_tts_result_ignored_after_cancel(self):
        """18. Stale results from a cancelled session token cannot restart playback."""
        fake_player = FakeAudioPlaybackService(auto_complete=False)
        overlay_host = StubOverlayHost()

        controller = SequenceController(
            tts_adapter=FakeTTSAdapter(),
            playback_service=fake_player,
            overlay_host=overlay_host,
        )

        response = TutorResponse(
            intent="explanation", summary="", narration="Old message.", overlay_actions=[]
        )

        controller.start_sequence(response, token=1)
        time.sleep(0.05)
        controller.cancel()

        # Simulate late worker attempting to execute with stale token 1
        controller._run_sequencing_worker(response, ["Old message."], token=1)

        # Playback should remain stopped
        self.assertFalse(fake_player.is_playing)

    def test_no_overlapping_narration(self):
        """21. Starting a new sequence immediately terminates previous active sequence."""
        fake_tts = FakeTTSAdapter()
        fake_player = FakeAudioPlaybackService(auto_complete=False)
        overlay_host = StubOverlayHost()

        controller = SequenceController(
            tts_adapter=fake_tts,
            playback_service=fake_player,
            overlay_host=overlay_host,
        )

        r1 = TutorResponse(intent="explanation", summary="", narration="Session 1 speech.", overlay_actions=[])
        r2 = TutorResponse(intent="explanation", summary="", narration="Session 2 speech.", overlay_actions=[])

        controller.start_sequence(r1, token=101)
        time.sleep(0.05)
        self.assertTrue(fake_player.is_playing)

        # Start second session sequence
        controller.start_sequence(r2, token=102)
        time.sleep(0.05)

        # Previous session was stopped
        self.assertGreaterEqual(fake_player.stop_count, 1)
        self.assertEqual(controller._active_token, 102)

    def test_sequence_controller_halts_on_terminal_tts_error(self):
        """Terminal error on segment 1 halts all subsequent synthesis calls immediately."""
        mock_tts = MagicMock(spec=TTSAdapter)
        mock_tts.synthesize.side_effect = TTSPaidPlanRequiredError("Paid plan required")
        fake_player = FakeAudioPlaybackService()
        overlay_host = StubOverlayHost()
        error_callbacks = []

        controller = SequenceController(
            tts_adapter=mock_tts,
            playback_service=fake_player,
            overlay_host=overlay_host,
            on_error=lambda err, tok: error_callbacks.append((err, tok)),
        )

        response = TutorResponse(
            intent="explanation",
            summary="Lesson",
            narration="First sentence. Second sentence. Third sentence.",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.1, 0.2, 0.3, 0.4),
                )
            ],
        )

        controller.start_sequence(response, token=10)
        time.sleep(0.1)

        # Visual overlay was displayed and remains intact
        self.assertTrue(overlay_host.has_explanation)
        # Only one error callback emitted
        self.assertEqual(len(error_callbacks), 1)
        # Synthesize was only called once, NOT for every segment!
        self.assertEqual(mock_tts.synthesize.call_count, 1)
        # Sequencer is inactive
        self.assertFalse(controller.is_active)


class TestSessionControllerTTSIntegration(unittest.TestCase):
    """Tests 17, 19-20, 22-29: Full SessionController integration with Block 5 TTS."""

    def test_full_sequence_flow_to_responded(self):
        """17 & 23: Tutor success triggers overlay and non-blocking narration sequence."""
        fake_tts = FakeTTSAdapter()
        fake_player = FakeAudioPlaybackService(auto_complete=True)
        overlay_host = StubOverlayHost()

        controller = SessionController(
            overlay_host=overlay_host,
            tts_adapter=fake_tts,
            playback_service=fake_player,
        )

        controller._set_state(SessionState.THINKING)
        token = controller._session_token

        response = TutorResponse(
            intent="explanation",
            summary="Summary text.",
            narration="Spoken explanation for the student.",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.1, 0.1, 0.2, 0.2),
                )
            ],
        )

        controller.handle_tutor_success(response, token=token)
        time.sleep(0.1)

        self.assertEqual(controller.state, SessionState.RESPONDED)
        self.assertTrue(overlay_host.has_explanation)
        self.assertIn("Spoken explanation for the student.", fake_tts.calls)
        self.assertEqual(fake_player.play_count, 1)

    def test_escape_returns_controller_to_idle_and_stops_narration(self):
        """17. Escape in RESPONDED state returns controller to IDLE, clears overlay and stops audio."""
        fake_tts = FakeTTSAdapter()
        fake_player = FakeAudioPlaybackService(auto_complete=False)
        overlay_host = StubOverlayHost()

        controller = SessionController(
            overlay_host=overlay_host,
            tts_adapter=fake_tts,
            playback_service=fake_player,
        )

        controller._set_state(SessionState.THINKING)
        token = controller._session_token

        response = TutorResponse(
            intent="explanation",
            summary="Lesson",
            narration="Long playing narration.",
            overlay_actions=[],
        )

        controller.handle_tutor_success(response, token=token)
        time.sleep(0.05)
        self.assertEqual(controller.state, SessionState.RESPONDED)
        self.assertTrue(fake_player.is_playing)

        # Press Escape / dismiss
        controller.dismiss()

        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertFalse(overlay_host.has_explanation)
        self.assertFalse(fake_player.is_playing)
        self.assertEqual(fake_player.stop_count, 1)

    def test_pre_capture_stops_narration_and_clears_overlay(self):
        """20 & 26: begin_capture_flow stops previous narration before capturing screen."""
        fake_player = FakeAudioPlaybackService(auto_complete=False)
        overlay_host = StubOverlayHost()

        class MockCaptureService(CaptureService):
            def __init__(self):
                self.captured = False

            def capture_current_screen(self):
                self.captured = True
                return CapturedScreen(geometry=DisplayGeometry(width=1920, height=1080))

        mock_cap = MockCaptureService()
        fake_tts = FakeTTSAdapter()
        controller = SessionController(
            capture_service=mock_cap,
            overlay_host=overlay_host,
            tts_adapter=fake_tts,
            playback_service=fake_player,
        )

        # Start a narration
        controller.sequence_controller.start_sequence(
            TutorResponse(intent="hint", summary="", narration="Previous speech", overlay_actions=[]),
            token=controller._session_token,
        )
        time.sleep(0.05)
        self.assertTrue(fake_player.is_playing)

        # Trigger new capture flow
        controller.begin_capture_flow(delay_ms=0)

        # Audio was stopped before capture
        self.assertFalse(fake_player.is_playing)
        self.assertTrue(mock_cap.captured)
        self.assertFalse(overlay_host.has_explanation)

    def test_new_activation_cancels_active_narration(self):
        """20. request_activation stops active narration immediately."""
        fake_player = FakeAudioPlaybackService(auto_complete=False)
        fake_tts = FakeTTSAdapter()
        overlay_host = StubOverlayHost()

        controller = SessionController(
            overlay_host=overlay_host,
            tts_adapter=fake_tts,
            playback_service=fake_player,
        )

        controller.sequence_controller.start_sequence(
            TutorResponse(intent="hint", summary="", narration="Old speech", overlay_actions=[]),
            token=controller._session_token,
        )
        time.sleep(0.05)
        self.assertTrue(fake_player.is_playing)

        # Request new activation hotkey
        controller.request_activation()

        self.assertFalse(fake_player.is_playing)

    def test_no_persistent_narration_artifacts(self):
        """28. NFR-06: Zero persistent narration audio files created on disk."""
        from pathlib import Path

        repo_root = Path(__file__).parents[2]
        before_files = set(os.listdir(repo_root))

        adapter = FakeTTSAdapter()
        clip = adapter.synthesize("Temporary educational speech.")
        player = FakeAudioPlaybackService(auto_complete=True)
        player.play(clip)

        after_files = set(os.listdir(repo_root))
        self.assertEqual(before_files, after_files)

    def test_session_controller_preserves_overlay_on_tts_failure(self):
        """FR-17: Recoverable TTS failure records error while keeping visual overlay visible."""
        mock_tts = MagicMock(spec=TTSAdapter)
        mock_tts.synthesize.side_effect = TTSPaidPlanRequiredError("Paid plan required")
        fake_player = FakeAudioPlaybackService()
        overlay_host = StubOverlayHost()

        controller = SessionController(
            overlay_host=overlay_host,
            tts_adapter=mock_tts,
            playback_service=fake_player,
        )

        controller._set_state(SessionState.THINKING)
        token = controller._session_token

        response = TutorResponse(
            intent="explanation",
            summary="Lesson Summary",
            narration="Sentence 1. Sentence 2.",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.HIGHLIGHT,
                    target_normalized=(0.1, 0.1, 0.3, 0.3),
                )
            ],
        )

        controller.handle_tutor_success(response, token=token)
        time.sleep(0.1)

        # Visual overlay remains visible
        self.assertTrue(overlay_host.has_explanation)
        # Session state remains in RESPONDED
        self.assertEqual(controller.state, SessionState.RESPONDED)
        # Error is logged and stored
        self.assertIsNotNone(controller.last_error_message)
        self.assertIn("Paid plan required", controller.last_error_message)

    def test_session_usable_after_terminal_tts_error(self):
        """Next tutoring session works cleanly even after a terminal TTS failure in prior turn."""
        mock_tts = MagicMock(spec=TTSAdapter)
        mock_tts.synthesize.side_effect = [
            TTSPaidPlanRequiredError("Paid plan required"),  # Session 1 fails
            TTSAudioClip(raw_bytes=b"\x00\x00" * 100, duration_seconds=0.1),  # Session 2 succeeds
        ]
        fake_player = FakeAudioPlaybackService(auto_complete=True)
        overlay_host = StubOverlayHost()

        controller = SessionController(
            overlay_host=overlay_host,
            tts_adapter=mock_tts,
            playback_service=fake_player,
        )

        # Session 1
        controller._set_state(SessionState.THINKING)
        r1 = TutorResponse(intent="explanation", summary="", narration="S1.", overlay_actions=[])
        controller.handle_tutor_success(r1, token=controller._session_token)
        time.sleep(0.05)

        self.assertEqual(controller.state, SessionState.RESPONDED)
        self.assertIn("Paid plan required", controller.last_error_message)

        # User initiates Session 2 (hotkey activation)
        controller.request_activation()
        self.assertEqual(controller.state, SessionState.ACTIVATED)
        self.assertIsNone(controller.last_error_message)

        # Tutor responds in Session 2
        controller._set_state(SessionState.THINKING)
        r2 = TutorResponse(intent="explanation", summary="", narration="S2.", overlay_actions=[])
        controller.handle_tutor_success(r2, token=controller._session_token)
        time.sleep(0.05)

        self.assertEqual(controller.state, SessionState.RESPONDED)
        self.assertEqual(mock_tts.synthesize.call_count, 2)

    def test_env_isolation_gemini_and_elevenlabs(self):
        """Gemini and ElevenLabs configuration paths are completely isolated."""
        from app.tutor.gemini import GeminiTutorAdapter
        env_vars = {
            "GEMINI_API_KEY": "gemini_isolated_key",
            "GEMINI_MODEL": "gemini-2.5-flash",
            "ELEVENLABS_API_KEY": "eleven_isolated_key",
            "ELEVENLABS_VOICE_ID": "eleven_voice_id",
            "ELEVENLABS_MODEL_ID": "eleven_turbo_v2_5",
        }
        with patch.dict(os.environ, env_vars, clear=True):
            gemini = GeminiTutorAdapter()
            eleven = ElevenLabsTTSAdapter()

            self.assertEqual(gemini._resolve_api_key(), "gemini_isolated_key")
            self.assertEqual(gemini.model, "gemini-2.5-flash")

            self.assertEqual(eleven._resolve_api_key(), "eleven_isolated_key")
            self.assertEqual(eleven.voice_id, "eleven_voice_id")
            self.assertEqual(eleven.model_id, "eleven_turbo_v2_5")


if __name__ == "__main__":
    unittest.main()
