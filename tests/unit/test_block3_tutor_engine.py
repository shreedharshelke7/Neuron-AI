"""Unit tests for TutorEngine orchestration."""

import pytest

from app.stt.model import UserQuestion
from app.tutor.adapter import FakeTutorAdapter
from app.tutor.engine import TutorEngine
from app.tutor.errors import (
    InvalidTutorResponseError,
    TutorAuthenticationError,
    TutorError,
    TutorRateLimitError,
)
from app.tutor.model import (
    OverlayAction,
    OverlayActionType,
    TutorRequest,
    TutorResponse,
)


class TestTutorEngine:
    def test_process_valid_request(self):
        adapter = FakeTutorAdapter()
        engine = TutorEngine(adapter=adapter)

        question = UserQuestion(transcript="How does recursion work?", audio_duration=3.0)
        request = TutorRequest(question=question)

        response = engine.process_request(request)
        assert response is not None
        assert response.summary == "This is a test explanation."
        assert len(adapter.recorded_requests) == 1
        assert adapter.recorded_requests[0].question.transcript == "How does recursion work?"

    def test_rejects_none_request(self):
        engine = TutorEngine(adapter=FakeTutorAdapter())
        with pytest.raises(ValueError, match="cannot be None"):
            engine.process_request(None)  # type: ignore

    def test_rejects_empty_transcript(self):
        engine = TutorEngine(adapter=FakeTutorAdapter())
        request = TutorRequest(question=UserQuestion(transcript="", audio_duration=0.0))
        with pytest.raises(ValueError, match="transcript must not be empty"):
            engine.process_request(request)

    def test_rejects_empty_summary_response(self):
        bad_response = TutorResponse(
            intent="explanation",
            summary="",
            narration="Valid narration",
        )
        adapter = FakeTutorAdapter(default_response=bad_response)
        engine = TutorEngine(adapter=adapter)

        request = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        with pytest.raises(InvalidTutorResponseError, match="summary cannot be empty"):
            engine.process_request(request)

    def test_rejects_empty_narration_response(self):
        bad_response = TutorResponse(
            intent="explanation",
            summary="Valid summary",
            narration="",
        )
        adapter = FakeTutorAdapter(default_response=bad_response)
        engine = TutorEngine(adapter=adapter)

        request = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        with pytest.raises(InvalidTutorResponseError, match="narration cannot be empty"):
            engine.process_request(request)

    def test_propagates_tutor_errors(self):
        adapter = FakeTutorAdapter(exception_to_raise=TutorAuthenticationError("Bad Key"))
        engine = TutorEngine(adapter=adapter)

        request = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        with pytest.raises(TutorAuthenticationError, match="Bad Key"):
            engine.process_request(request)

        adapter2 = FakeTutorAdapter(exception_to_raise=TutorRateLimitError("Rate limit exceeded"))
        engine2 = TutorEngine(adapter=adapter2)
        with pytest.raises(TutorRateLimitError, match="Rate limit exceeded"):
            engine2.process_request(request)

    def test_wraps_unexpected_exceptions_in_tutor_error(self):
        adapter = FakeTutorAdapter(exception_to_raise=RuntimeError("Unexpected crash"))
        engine = TutorEngine(adapter=adapter)

        request = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        with pytest.raises(TutorError, match="Unexpected tutor generation error"):
            engine.process_request(request)
