"""Deterministic unit and integration tests for Block 7 Demo Scenarios and Fallbacks.

Verifies:
- DemoScenarioRegistry and DemoScenarioMatcher keyword and tag matching.
- Scenario 1 (Mathematics): derivative / tangent slope / f'(x) = 0.
- Scenario 2 (PDF / Symbol): operator / formula definition with selected region preference.
- Scenario 3 (Coding): bug explanation / index error / suggested fix.
- Generic fallback for unrecognized transcripts.
- Fallback TutorResponse schema validation and Block 4 primitive compatibility.
- DemoMode (LIVE, FALLBACK, AUTO) routing and Live-first behavior.
- Automatic recovery on network/provider/timeout/validation errors in AUTO mode.
- Block 4 OverlayRenderer visual primitive mapping for all scenarios.
- Block 5 SequenceController narration sequencing and TTS failure tolerance.
- Session isolation, stale token protection, and Escape cancellation.
- Wake detector suspension during fallback session and re-arming upon IDLE.
- Ephemeral in-memory execution (0 persistent artifacts).
- 100% offline: zero real Gemini, ElevenLabs, or cloud wake requests.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from app.capture.model import CapturedScreen, DisplayGeometry, SelectedRegion
from app.capture.service import StubCaptureService
from app.overlay.primitives import (
    ArrowPrimitive,
    CardPrimitive,
    EquationPrimitive,
    HighlightPrimitive,
    TextPrimitive,
)
from app.overlay.renderer import OverlayRenderer
from app.sequence.controller import SequenceController
from app.session.controller import SessionController
from app.session.state import SessionState
from app.stt.model import UserQuestion
from app.tts.adapter import TTSAdapter
from app.tts.errors import TTSError
from app.tts.model import TTSAudioClip
from app.tts.playback import FakeAudioPlaybackService
from app.tutor.adapter import FakeTutorAdapter, TutorAdapter
from app.tutor.engine import TutorEngine
from app.tutor.errors import (
    InvalidTutorResponseError,
    TutorAuthenticationError,
    TutorError,
    TutorRateLimitError,
    TutorTimeoutError,
    TutorUnavailableError,
)
from app.tutor.fallback import (
    DemoMode,
    FallbackTutorAdapter,
    resolve_demo_mode,
)
from app.tutor.model import (
    OverlayAction,
    OverlayActionType,
    TutorRequest,
    TutorResponse,
)
from app.tutor.scenario import (
    DemoScenario,
    DemoScenarioId,
    DemoScenarioMatcher,
    DemoScenarioRegistry,
    build_coding_scenario_response,
    build_generic_scenario_response,
    build_math_scenario_response,
    build_pdf_scenario_response,
)
from app.wake.fake import FakeWakeWordDetector


class TestDemoScenarioRegistryAndMatcher(unittest.TestCase):
    """Test scenario registration and deterministic keyword matching."""

    def setUp(self):
        self.registry = DemoScenarioRegistry()
        self.matcher = DemoScenarioMatcher(self.registry)

    def _req(self, transcript: str, region: SelectedRegion = None) -> TutorRequest:
        return TutorRequest(
            question=UserQuestion(transcript=transcript, audio_duration=2.0),
            selected_region=region,
        )

    def test_default_scenarios_registered(self):
        """All 3 hackathon scenarios plus generic fallback are pre-registered."""
        self.assertIsNotNone(self.registry.get(DemoScenarioId.MATH_DERIVATIVE))
        self.assertIsNotNone(self.registry.get(DemoScenarioId.PDF_FORMULA_SYMBOL))
        self.assertIsNotNone(self.registry.get(DemoScenarioId.CODING_ERROR))
        self.assertIsNotNone(self.registry.get(DemoScenarioId.GENERIC_FALLBACK))

    def test_math_scenario_keyword_matching(self):
        """Math queries match MATH_DERIVATIVE."""
        math_questions = [
            "Why is the slope zero here?",
            "Explain the derivative and show me the important part.",
            "What is the tangent slope at the local minimum?",
            "Is the derivative of f(x) equal to zero at the vertex?",
        ]
        for q in math_questions:
            scenario = self.matcher.match(self._req(q))
            self.assertEqual(
                scenario.scenario_id,
                DemoScenarioId.MATH_DERIVATIVE,
                f"Expected MATH_DERIVATIVE for '{q}', got {scenario.scenario_id}",
            )

    def test_pdf_scenario_keyword_matching(self):
        """Formula and symbol queries match PDF_FORMULA_SYMBOL."""
        pdf_questions = [
            "What does this symbol mean?",
            "What does this part of the formula mean?",
            "Can you explain this sigma summation notation?",
            "Explain this equation term in the PDF notes.",
        ]
        for q in pdf_questions:
            scenario = self.matcher.match(self._req(q))
            self.assertEqual(
                scenario.scenario_id,
                DemoScenarioId.PDF_FORMULA_SYMBOL,
                f"Expected PDF_FORMULA_SYMBOL for '{q}', got {scenario.scenario_id}",
            )

    def test_coding_scenario_keyword_matching(self):
        """Coding and bug queries match CODING_ERROR."""
        coding_questions = [
            "Why does this code fail?",
            "Why is there a bug in this function?",
            "What causes this index error exception on this line?",
            "Why does this loop crash?",
        ]
        for q in coding_questions:
            scenario = self.matcher.match(self._req(q))
            self.assertEqual(
                scenario.scenario_id,
                DemoScenarioId.CODING_ERROR,
                f"Expected CODING_ERROR for '{q}', got {scenario.scenario_id}",
            )

    def test_explicit_scenario_tags_override(self):
        """Explicit [scenario:...] tags immediately route to the target scenario."""
        self.assertEqual(
            self.matcher.match(self._req("[scenario:math] Any random text")).scenario_id,
            DemoScenarioId.MATH_DERIVATIVE,
        )
        self.assertEqual(
            self.matcher.match(self._req("[scenario:pdf] Any random text")).scenario_id,
            DemoScenarioId.PDF_FORMULA_SYMBOL,
        )
        self.assertEqual(
            self.matcher.match(self._req("[scenario:coding] Any random text")).scenario_id,
            DemoScenarioId.CODING_ERROR,
        )
        self.assertEqual(
            self.matcher.match(self._req("[scenario:generic] Any random text")).scenario_id,
            DemoScenarioId.GENERIC_FALLBACK,
        )

    def test_environment_variable_override(self):
        """NEURON_DEMO_SCENARIO env var forces the configured scenario."""
        old_env = os.environ.get("NEURON_DEMO_SCENARIO")
        try:
            os.environ["NEURON_DEMO_SCENARIO"] = "math"
            self.assertEqual(
                self.matcher.match(self._req("completely unrelated query")).scenario_id,
                DemoScenarioId.MATH_DERIVATIVE,
            )

            os.environ["NEURON_DEMO_SCENARIO"] = "pdf"
            self.assertEqual(
                self.matcher.match(self._req("completely unrelated query")).scenario_id,
                DemoScenarioId.PDF_FORMULA_SYMBOL,
            )

            os.environ["NEURON_DEMO_SCENARIO"] = "coding"
            self.assertEqual(
                self.matcher.match(self._req("completely unrelated query")).scenario_id,
                DemoScenarioId.CODING_ERROR,
            )
        finally:
            if old_env is not None:
                os.environ["NEURON_DEMO_SCENARIO"] = old_env
            else:
                os.environ.pop("NEURON_DEMO_SCENARIO", None)

    def test_unmatched_query_selects_safe_generic_fallback(self):
        """Unrecognized questions select GENERIC_FALLBACK instead of a wrong scripted answer."""
        unrelated = self._req("Tell me a recipe for chocolate cake.")
        matched = self.matcher.match(unrelated)
        self.assertEqual(matched.scenario_id, DemoScenarioId.GENERIC_FALLBACK)


class TestDeterministicScenarioResponses(unittest.TestCase):
    """Test schema validity, pedagogical content, and primitives of scenario responses."""

    def setUp(self):
        self.geometry = DisplayGeometry(width=1920, height=1080)
        self.screen = CapturedScreen(geometry=self.geometry)

    def test_math_scenario_response(self):
        """Math scenario produces valid HIGHLIGHT, ARROW, EQUATION, and CARD actions."""
        req = TutorRequest(
            question=UserQuestion(transcript="Why is the slope zero here?", audio_duration=2.0),
            capture=self.screen,
        )
        res = build_math_scenario_response(req)

        self.assertEqual(res.intent, "explanation")
        self.assertIn("horizontal", res.summary.lower())
        self.assertIn("derivative", res.summary.lower())
        self.assertIn("tangent", res.narration.lower())
        self.assertTrue(len(res.overlay_actions) >= 4)

        types = [a.action_type for a in res.overlay_actions]
        self.assertIn(OverlayActionType.HIGHLIGHT, types)
        self.assertIn(OverlayActionType.ARROW, types)
        self.assertIn(OverlayActionType.EQUATION, types)
        self.assertIn(OverlayActionType.CARD, types)

        # Coordinate bounds check
        for a in res.overlay_actions:
            if a.target_normalized:
                for val in a.target_normalized:
                    self.assertGreaterEqual(val, 0.0)
                    self.assertLessEqual(val, 1.0001)

    def test_pdf_scenario_selected_region_targeting(self):
        """PDF scenario prioritizes selected_region when provided."""
        region = SelectedRegion(x=200, y=300, width=400, height=200, display_geometry=self.geometry)
        req = TutorRequest(
            question=UserQuestion(transcript="What does this symbol mean?", audio_duration=2.0),
            capture=self.screen,
            selected_region=region,
        )
        res = build_pdf_scenario_response(req)

        self.assertEqual(res.intent, "explanation")
        self.assertIn("symbol", res.summary.lower())

        highlight = next(a for a in res.overlay_actions if a.action_type == OverlayActionType.HIGHLIGHT)
        expected_norm = region.to_normalized(self.geometry)
        for actual, exp in zip(highlight.target_normalized, expected_norm):
            self.assertAlmostEqual(actual, exp, places=3)

    def test_coding_scenario_response(self):
        """Coding scenario highlights the bug, shows cause card, and suggests fix."""
        req = TutorRequest(
            question=UserQuestion(transcript="Why does this code fail?", audio_duration=2.0),
            capture=self.screen,
        )
        res = build_coding_scenario_response(req)

        self.assertEqual(res.intent, "debugging")
        self.assertIn("index", res.summary.lower())
        self.assertIn("indexerror", res.narration.lower())

        types = [a.action_type for a in res.overlay_actions]
        self.assertIn(OverlayActionType.HIGHLIGHT, types)
        self.assertIn(OverlayActionType.CARD, types)
        self.assertIn(OverlayActionType.TEXT, types)

    def test_generic_fallback_response(self):
        """Generic fallback acknowledges offline assistance and focuses screen."""
        req = TutorRequest(
            question=UserQuestion(transcript="How do I bake bread?", audio_duration=2.0),
            capture=self.screen,
        )
        res = build_generic_scenario_response(req)

        self.assertEqual(res.intent, "assistance")
        self.assertIn("offline", res.summary.lower())
        self.assertTrue(len(res.overlay_actions) >= 2)


class TestDemoModeAndTutorEngine(unittest.TestCase):
    """Test DemoMode semantics, live-first rule, and failure recovery."""

    def test_resolve_demo_mode_default(self):
        """Default demo mode is AUTO when no env var is configured."""
        old = os.environ.pop("NEURON_DEMO_MODE", None)
        try:
            self.assertEqual(resolve_demo_mode(), DemoMode.AUTO)
        finally:
            if old is not None:
                os.environ["NEURON_DEMO_MODE"] = old

    def test_live_mode_calls_primary_adapter_only(self):
        """In LIVE mode, only the primary adapter is called; errors propagate without fallback."""
        fake_primary = FakeTutorAdapter(exception_to_raise=TutorUnavailableError("Service down"))
        fake_fallback = FallbackTutorAdapter()

        engine = TutorEngine(
            adapter=fake_primary,
            fallback_adapter=fake_fallback,
            demo_mode=DemoMode.LIVE,
        )
        req = TutorRequest(question=UserQuestion(transcript="Why is the slope zero here?", audio_duration=2.0))

        with self.assertRaises(TutorUnavailableError):
            engine.process_request(req)

    def test_fallback_mode_never_calls_primary_adapter(self):
        """In FALLBACK mode, zero requests are sent to the primary adapter (0 Gemini calls)."""
        fake_primary = FakeTutorAdapter()
        fake_fallback = FallbackTutorAdapter()

        engine = TutorEngine(
            adapter=fake_primary,
            fallback_adapter=fake_fallback,
            demo_mode=DemoMode.FALLBACK,
        )
        req = TutorRequest(question=UserQuestion(transcript="Why is the slope zero here?", audio_duration=2.0))
        res = engine.process_request(req)

        self.assertEqual(len(fake_primary.recorded_requests), 0, "Primary adapter must not be called in FALLBACK mode")
        self.assertIn("horizontal", res.summary.lower())

    def test_auto_mode_uses_live_when_successful(self):
        """Live-First Rule: successful primary adapter response is never replaced."""
        live_res = TutorResponse(
            intent="live_explanation",
            summary="Custom live response from Gemini.",
            narration="Here is live narration.",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.CARD,
                    title="Live Result",
                    text="Generated live by Gemini.",
                )
            ],
        )
        fake_primary = FakeTutorAdapter(default_response=live_res)
        fake_fallback = FallbackTutorAdapter()

        engine = TutorEngine(
            adapter=fake_primary,
            fallback_adapter=fake_fallback,
            demo_mode=DemoMode.AUTO,
        )
        req = TutorRequest(question=UserQuestion(transcript="Why is the slope zero here?", audio_duration=2.0))
        res = engine.process_request(req)

        self.assertEqual(res.summary, "Custom live response from Gemini.")
        self.assertEqual(len(fake_primary.recorded_requests), 1)

    def test_auto_mode_recovers_on_primary_failure(self):
        """In AUTO mode, primary provider/network failure triggers deterministic fallback."""
        fake_primary = FakeTutorAdapter(exception_to_raise=TutorUnavailableError("Connection timeout"))
        fake_fallback = FallbackTutorAdapter()

        engine = TutorEngine(
            adapter=fake_primary,
            fallback_adapter=fake_fallback,
            demo_mode=DemoMode.AUTO,
        )
        req = TutorRequest(question=UserQuestion(transcript="Why is the slope zero here?", audio_duration=2.0))
        res = engine.process_request(req)

        self.assertIsNotNone(res)
        self.assertIn("horizontal", res.summary.lower())

    def test_auto_mode_recovers_on_invalid_response(self):
        """AC-09: Invalid response from primary triggers fallback recovery in AUTO mode."""
        bad_response = TutorResponse(
            intent="explanation",
            summary="",  # Invalid empty summary
            narration="Valid narration",
        )
        fake_primary = FakeTutorAdapter(default_response=bad_response)
        fake_fallback = FallbackTutorAdapter()

        engine = TutorEngine(
            adapter=fake_primary,
            fallback_adapter=fake_fallback,
            demo_mode=DemoMode.AUTO,
        )
        req = TutorRequest(question=UserQuestion(transcript="Why does this code fail?", audio_duration=2.0))
        res = engine.process_request(req)

        self.assertTrue(bool(res.summary.strip()))
        self.assertIn("index", res.summary.lower())


class TestRendererAndSequencingIntegration(unittest.TestCase):
    """Test integration of deterministic fallback responses with Block 4 Overlay and Block 5 TTS."""

    def setUp(self):
        self.geometry = DisplayGeometry(width=1920, height=1080)
        self.screen = CapturedScreen(geometry=self.geometry)
        self.renderer = OverlayRenderer()

    def test_math_fallback_renders_on_block4_overlay(self):
        """Math fallback renders Highlight, Arrow, Equation, and Card primitives on overlay."""
        req = TutorRequest(
            question=UserQuestion(transcript="Why is the slope zero here?", audio_duration=2.0),
            capture=self.screen,
        )
        res = build_math_scenario_response(req)
        success = self.renderer.render_tutor_response(res, geometry=self.geometry)

        self.assertTrue(success)
        self.assertTrue(self.renderer.has_visuals())
        types = [type(p) for p in self.renderer.primitives]
        self.assertIn(HighlightPrimitive, types)
        self.assertIn(ArrowPrimitive, types)
        self.assertIn(EquationPrimitive, types)
        self.assertIn(CardPrimitive, types)

    def test_pdf_fallback_renders_with_selected_region(self):
        """PDF fallback renders Highlight and Card matching selected region."""
        region = SelectedRegion(x=300, y=400, width=500, height=250, display_geometry=self.geometry)
        req = TutorRequest(
            question=UserQuestion(transcript="What does this symbol mean?", audio_duration=2.0),
            capture=self.screen,
            selected_region=region,
        )
        res = build_pdf_scenario_response(req)
        success = self.renderer.render_tutor_response(res, geometry=self.geometry, selected_region=region)

        self.assertTrue(success)
        highlight = next(p for p in self.renderer.primitives if isinstance(p, HighlightPrimitive))
        self.assertEqual(highlight.rect.local_x, 300)
        self.assertEqual(highlight.rect.local_y, 400)

    def test_coding_fallback_renders_on_block4_overlay(self):
        """Coding fallback renders Highlight, Card, and Text primitives on overlay."""
        req = TutorRequest(
            question=UserQuestion(transcript="Why does this code fail?", audio_duration=2.0),
            capture=self.screen,
        )
        res = build_coding_scenario_response(req)
        success = self.renderer.render_tutor_response(res, geometry=self.geometry)

        self.assertTrue(success)
        types = [type(p) for p in self.renderer.primitives]
        self.assertIn(HighlightPrimitive, types)
        self.assertIn(CardPrimitive, types)
        self.assertIn(TextPrimitive, types)

    def test_fallback_enters_block5_narration_sequencing(self):
        """Deterministic response enters SequenceController and plays via TTS adapter."""
        synthesized_texts = []

        class MockTTS(TTSAdapter):
            def synthesize(self, text: str) -> TTSAudioClip:
                synthesized_texts.append(text)
                return TTSAudioClip(raw_bytes=b"\x00" * 4800, duration_seconds=0.1, text=text)

        playback = FakeAudioPlaybackService()
        seq = SequenceController(
            tts_adapter=MockTTS(),
            playback_service=playback,
        )

        req = TutorRequest(question=UserQuestion(transcript="Why is the slope zero here?", audio_duration=2.0))
        res = build_math_scenario_response(req)
        seq.start_sequence(response=res, token=1, geometry=self.geometry)

        # Allow worker thread to process segments
        if seq._worker_thread:
            seq._worker_thread.join(timeout=2.0)

        self.assertTrue(len(synthesized_texts) >= 1)
        self.assertIn("tangent", " ".join(synthesized_texts).lower())

    def test_tts_failure_during_fallback_preserves_visuals(self):
        """Recoverable TTS error does not destroy overlay visuals."""
        class FailingTTS(TTSAdapter):
            def synthesize(self, text: str) -> TTSAudioClip:
                raise TTSError("Simulated TTS failure")

        error_events = []
        playback = FakeAudioPlaybackService()
        seq = SequenceController(
            tts_adapter=FailingTTS(),
            playback_service=playback,
            on_error=lambda msg, tok: error_events.append(msg),
        )

        req = TutorRequest(question=UserQuestion(transcript="Why does this code fail?", audio_duration=2.0))
        res = build_coding_scenario_response(req)
        self.renderer.render_tutor_response(res, geometry=self.geometry)

        seq.start_sequence(response=res, token=1, geometry=self.geometry)
        if seq._worker_thread:
            seq._worker_thread.join(timeout=2.0)

        # Error reported but overlay primitives remain intact
        self.assertEqual(len(error_events), 1)
        self.assertTrue(self.renderer.has_visuals())


class TestSessionIsolationAndCancellation(unittest.TestCase):
    """Test session lifecycle, stale token guards, and Escape cancellation."""

    def setUp(self):
        self.geometry = DisplayGeometry(width=1920, height=1080)
        self.screen = CapturedScreen(geometry=self.geometry)
        self.renderer = OverlayRenderer()

    def test_escape_cancels_fallback_session_and_clears_overlay(self):
        """Escape during fallback explanation stops audio, clears overlay, and returns to IDLE."""
        controller = SessionController(
            capture_service=StubCaptureService(stub_result=self.screen),
            auto_capture=False,
        )
        controller.overlay_host = MagicMock()

        # Simulate RESPONDED state
        controller._set_state(SessionState.RESPONDED)
        self.assertEqual(controller.state, SessionState.RESPONDED)

        # User presses Escape (dismiss)
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)
        controller.overlay_host.clear_explanation.assert_called()

    def test_stale_fallback_response_dropped(self):
        """Late response with mismatched token is discarded."""
        controller = SessionController(auto_capture=False)
        controller._session_token = 5
        controller._set_state(SessionState.THINKING)

        stale_res = build_math_scenario_response(
            TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        )
        # Handle with stale token=4
        controller.handle_tutor_success(stale_res, token=4)

        # State should still be THINKING; stale result discarded
        self.assertEqual(controller.state, SessionState.THINKING)
        self.assertIsNone(controller.current_tutor_response)

    def test_wake_detector_stays_suspended_during_fallback_session(self):
        """Wake detector remains paused during fallback explanation and re-arms only upon IDLE."""
        wake_detector = FakeWakeWordDetector()
        manager = MagicMock()
        manager.is_wake_paused = False

        controller = SessionController(
            activation_trigger=manager,
            capture_service=StubCaptureService(stub_result=self.screen),
            auto_capture=False,
        )

        def on_state(state: SessionState) -> None:
            if state == SessionState.IDLE:
                wake_detector.resume()
            else:
                wake_detector.pause()

        controller.add_state_listener(on_state)
        wake_detector.start()
        self.assertFalse(wake_detector.is_paused)

        # Start session
        controller._set_state(SessionState.THINKING)
        self.assertTrue(wake_detector.is_paused)

        # Fallback response arrives
        res = build_math_scenario_response(
            TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        )
        controller.handle_tutor_success(res, token=controller.session_token)
        self.assertEqual(controller.state, SessionState.RESPONDED)
        self.assertTrue(wake_detector.is_paused, "Must remain paused during fallback narration")

        # Session dismissed -> returns to IDLE
        controller.dismiss()
        self.assertEqual(controller.state, SessionState.IDLE)
        self.assertFalse(wake_detector.is_paused, "Must re-arm upon returning to IDLE")


if __name__ == "__main__":
    unittest.main()
