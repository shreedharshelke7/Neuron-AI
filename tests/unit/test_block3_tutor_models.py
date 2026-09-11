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
    def test_parse_valid_srs_types(self):
        assert OverlayActionType.from_string("HIGHLIGHT") == OverlayActionType.HIGHLIGHT
        assert OverlayActionType.from_string("arrow") == OverlayActionType.ARROW
        assert OverlayActionType.from_string("TEXT") == OverlayActionType.TEXT
        assert OverlayActionType.from_string("card") == OverlayActionType.CARD
        assert OverlayActionType.from_string("EQUATION") == OverlayActionType.EQUATION
        assert OverlayActionType.from_string("none") == OverlayActionType.NONE

    def test_parse_compatibility_aliases(self):
        assert OverlayActionType.from_string("FOCUS_BOX") == OverlayActionType.HIGHLIGHT
        assert OverlayActionType.from_string("PIN") == OverlayActionType.TEXT
        assert OverlayActionType.from_string("underline") == OverlayActionType.HIGHLIGHT

    def test_parse_invalid_defaults_to_none(self):
        assert OverlayActionType.from_string("UNKNOWN_ACTION") == OverlayActionType.NONE
        assert OverlayActionType.from_string("") == OverlayActionType.NONE
        assert OverlayActionType.from_string(None) == OverlayActionType.NONE


class TestOverlayAction:
    def test_valid_highlight_creation(self):
        action = OverlayAction(
            action_type=OverlayActionType.HIGHLIGHT,
            target_normalized=(0.1, 0.2, 0.3, 0.4),
            label="Key Formula",
            color="#4285F4",
        )
        assert action.action_type == OverlayActionType.HIGHLIGHT
        assert action.target_normalized == (0.1, 0.2, 0.3, 0.4)
        assert action.label == "Key Formula"
        assert action.color == "#4285F4"

        data = action.to_dict()
        assert data["action_type"] == "HIGHLIGHT"
        assert data["target_normalized"] == [0.1, 0.2, 0.3, 0.4]

    def test_valid_card_creation(self):
        action = OverlayAction(
            action_type=OverlayActionType.CARD,
            target_normalized=(0.6, 0.1, 0.35, 0.25),
            title="Derivative Rule",
            text="d/dx [x^n] = n * x^(n-1)",
            color="#34A853",
        )
        assert action.action_type == OverlayActionType.CARD
        assert action.title == "Derivative Rule"
        assert action.text == "d/dx [x^n] = n * x^(n-1)"

        data = action.to_dict()
        assert data["action_type"] == "CARD"
        assert data["title"] == "Derivative Rule"

    def test_valid_equation_creation(self):
        action = OverlayAction(
            action_type=OverlayActionType.EQUATION,
            target_normalized=(0.4, 0.4, 0.2, 0.1),
            text=r"\frac{d}{dx} x^2 = 2x",
        )
        assert action.action_type == OverlayActionType.EQUATION
        assert action.text == r"\frac{d}{dx} x^2 = 2x"

    def test_valid_text_creation(self):
        action = OverlayAction(
            action_type=OverlayActionType.TEXT,
            target_normalized=(0.1, 0.1, 0.2, 0.05),
            text="Notice the exponent here.",
        )
        assert action.action_type == OverlayActionType.TEXT
        assert action.text == "Notice the exponent here."

    def test_rejects_missing_required_payload(self):
        # HIGHLIGHT requires target_normalized
        with pytest.raises(ValueError, match="requires target_normalized"):
            OverlayAction(action_type=OverlayActionType.HIGHLIGHT, target_normalized=None)

        # TEXT requires text or label
        with pytest.raises(ValueError, match="requires text or label"):
            OverlayAction(action_type=OverlayActionType.TEXT, target_normalized=(0.1, 0.1, 0.1, 0.1))

        # CARD requires title or text
        with pytest.raises(ValueError, match="requires title or text"):
            OverlayAction(action_type=OverlayActionType.CARD, target_normalized=(0.1, 0.1, 0.1, 0.1))

        # EQUATION requires formula expression in text
        with pytest.raises(ValueError, match="requires formula expression"):
            OverlayAction(action_type=OverlayActionType.EQUATION, target_normalized=(0.1, 0.1, 0.1, 0.1))

    def test_rejects_unsafe_executable_content(self):
        with pytest.raises(ValueError, match="disallowed executable content"):
            OverlayAction(
                action_type=OverlayActionType.CARD,
                title="Exploit",
                text="<script>alert('xss')</script>",
            )

        with pytest.raises(ValueError, match="disallowed executable content"):
            OverlayAction(
                action_type=OverlayActionType.TEXT,
                text="javascript:void(0)",
            )

    def test_rejects_invalid_coordinate_length(self):
        with pytest.raises(ValueError, match="must contain exactly 4 values"):
            OverlayAction(
                action_type=OverlayActionType.HIGHLIGHT,
                target_normalized=(0.1, 0.2),  # type: ignore
            )

    def test_rejects_nan_or_inf_coordinates(self):
        with pytest.raises(ValueError, match="not a finite number"):
            OverlayAction(
                action_type=OverlayActionType.HIGHLIGHT,
                target_normalized=(0.1, float("nan"), 0.3, 0.4),
            )

        with pytest.raises(ValueError, match="not a finite number"):
            OverlayAction(
                action_type=OverlayActionType.HIGHLIGHT,
                target_normalized=(0.1, 0.2, float("inf"), 0.4),
            )

    def test_rejects_out_of_range_coordinates_during_construction(self):
        with pytest.raises(ValueError, match="out of normalized"):
            OverlayAction(
                action_type=OverlayActionType.HIGHLIGHT,
                target_normalized=(-0.5, 0.2, 0.3, 0.4),
            )

        with pytest.raises(ValueError, match="out of normalized"):
            OverlayAction(
                action_type=OverlayActionType.HIGHLIGHT,
                target_normalized=(0.1, 1.5, 0.3, 0.4),
            )

    def test_clamp_coordinates(self):
        # Valid bounds
        coords = OverlayAction.clamp_coordinates((0.2, 0.3, 0.4, 0.5))
        assert coords == (0.2, 0.3, 0.4, 0.5)

        # Negative and oversized
        coords = OverlayAction.clamp_coordinates((-0.5, -0.1, 1.5, 2.0))
        assert coords is not None
        c0, c1, c2, c3 = coords
        assert c0 == 0.0
        assert c1 == 0.0
        assert c2 == 1.0
        assert c3 == 1.0

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
