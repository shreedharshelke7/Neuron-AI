"""Unit tests for Block 3 Tutor data models and contracts."""

import math
import pytest

from app.capture.model import CapturedScreen, DisplayGeometry, SelectedRegion
from app.stt.model import UserQuestion
from app.tutor.model import (
    OverlayAction,
    OverlayActionType,
    TutorRequest,
    TutorResponse,
)


class TestOverlayActionType:
    def test_parse_valid_types(self):
        assert OverlayActionType.from_string("FOCUS_BOX") == OverlayActionType.FOCUS_BOX
        assert OverlayActionType.from_string("arrow") == OverlayActionType.ARROW
        assert OverlayActionType.from_string("PIN") == OverlayActionType.PIN
        assert OverlayActionType.from_string("underline") == OverlayActionType.UNDERLINE
        assert OverlayActionType.from_string("none") == OverlayActionType.NONE

    def test_parse_invalid_defaults_to_none(self):
        assert OverlayActionType.from_string("UNKNOWN_ACTION") == OverlayActionType.NONE
        assert OverlayActionType.from_string("") == OverlayActionType.NONE
        assert OverlayActionType.from_string(None) == OverlayActionType.NONE


class TestOverlayAction:
    def test_valid_action_creation(self):
        action = OverlayAction(
            action_type=OverlayActionType.FOCUS_BOX,
            target_normalized=(0.1, 0.2, 0.3, 0.4),
            label="Key Formula",
            color="#4285F4",
        )
        assert action.action_type == OverlayActionType.FOCUS_BOX
        assert action.target_normalized == (0.1, 0.2, 0.3, 0.4)
        assert action.label == "Key Formula"
        assert action.color == "#4285F4"

        data = action.to_dict()
        assert data["action_type"] == "FOCUS_BOX"
        assert data["target_normalized"] == [0.1, 0.2, 0.3, 0.4]

    def test_rejects_invalid_coordinate_length(self):
        with pytest.raises(ValueError, match="must contain exactly 4 values"):
            OverlayAction(
                action_type=OverlayActionType.FOCUS_BOX,
                target_normalized=(0.1, 0.2),  # type: ignore
            )

    def test_rejects_nan_or_inf_coordinates(self):
        with pytest.raises(ValueError, match="not a finite number"):
            OverlayAction(
                action_type=OverlayActionType.FOCUS_BOX,
                target_normalized=(0.1, float("nan"), 0.3, 0.4),
            )

        with pytest.raises(ValueError, match="not a finite number"):
            OverlayAction(
                action_type=OverlayActionType.FOCUS_BOX,
                target_normalized=(0.1, 0.2, float("inf"), 0.4),
            )

    def test_clamp_coordinates(self):
        # Valid bounds
        coords = OverlayAction.clamp_coordinates((0.2, 0.3, 0.4, 0.5))
        assert coords == (0.2, 0.3, 0.4, 0.5)

        # Negative and oversized
        coords = OverlayAction.clamp_coordinates((-0.5, -0.1, 1.5, 2.0))
        assert coords is not None
        nx, ny, nw, nh = coords
        assert nx == 0.0
        assert ny == 0.0
        assert nw == 1.0
        assert nh == 1.0

        # Partial clamp
        coords = OverlayAction.clamp_coordinates((0.8, 0.8, 0.5, 0.5))
        assert coords is not None
        assert coords[0] == 0.8
        assert coords[1] == 0.8
        assert coords[2] == pytest.approx(0.2, abs=0.001)
        assert coords[3] == pytest.approx(0.2, abs=0.001)

        # Non-finite / invalid length returns None
        assert OverlayAction.clamp_coordinates((0.1, float("nan"), 0.3, 0.4)) is None
        assert OverlayAction.clamp_coordinates((0.1, 0.2)) is None  # type: ignore


class TestTutorRequest:
    def test_valid_request(self):
        question = UserQuestion(transcript="Explain this graph", audio_duration=2.5)
        req = TutorRequest(question=question)
        req.validate()  # Should not raise
        assert req.question.transcript == "Explain this graph"

    def test_empty_transcript_raises_value_error(self):
        question = UserQuestion(transcript="   ", audio_duration=1.0)
        req = TutorRequest(question=question)
        with pytest.raises(ValueError, match="transcript must not be empty"):
            req.validate()


class TestTutorResponse:
    def test_tutor_response_to_dict(self):
        action = OverlayAction(
            action_type=OverlayActionType.ARROW,
            target_normalized=(0.2, 0.3, 0.1, 0.1),
            label="Peak",
        )
        res = TutorResponse(
            intent="explanation",
            summary="The graph shows exponential growth.",
            narration="As x increases, y grows rapidly as seen near the upper right.",
            overlay_actions=[action],
            follow_up="What happens when x is negative?",
        )
        data = res.to_dict()
        assert data["intent"] == "explanation"
        assert data["summary"] == "The graph shows exponential growth."
        assert len(data["overlay_actions"]) == 1
        assert data["overlay_actions"][0]["action_type"] == "ARROW"
        assert data["follow_up"] == "What happens when x is negative?"
