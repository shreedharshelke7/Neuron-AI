"""Unit tests for GeminiTutorAdapter with mocked GenAI client."""

import json
import os
from unittest.mock import MagicMock, patch
import pytest

from PySide6.QtGui import QPixmap

from app.capture.model import CapturedScreen, DisplayGeometry, SelectedRegion
from app.stt.model import UserQuestion
from app.tutor.errors import (
    InvalidTutorResponseError,
    TutorAuthenticationError,
    TutorRateLimitError,
    TutorTimeoutError,
    TutorUnavailableError,
)
from app.tutor.gemini import GeminiTutorAdapter
from app.tutor.model import OverlayActionType, TutorRequest
from app.tutor.prompt import build_user_prompt, extract_image_bytes


class TestGeminiTutorAdapterConstruction:
    def test_construction_is_side_effect_free(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        monkeypatch.chdir(tmp_path)

        adapter = GeminiTutorAdapter()
        assert adapter.model == "gemini-2.5-flash"
        assert adapter._client is None

    def test_custom_model_configuration(self, monkeypatch):
        monkeypatch.setenv("GEMINI_MODEL", "gemini-custom-flash")
        adapter = GeminiTutorAdapter()
        assert adapter.model == "gemini-custom-flash"

        adapter_explicit = GeminiTutorAdapter(model="gemini-explicit")
        assert adapter_explicit.model == "gemini-explicit"

    def test_resolves_model_from_dotenv(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text('GEMINI_MODEL="gemini-dotenv-test"\n', encoding="utf-8")
        adapter = GeminiTutorAdapter()
        assert adapter.model == "gemini-dotenv-test"


class TestGeminiApiKeyResolution:
    def test_missing_api_key_raises_authentication_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)
        adapter = GeminiTutorAdapter()
        req = TutorRequest(question=UserQuestion(transcript="Hello", audio_duration=1.0))

        with pytest.raises(TutorAuthenticationError, match="GEMINI_API_KEY is not set"):
            adapter.generate_response(req)

    def test_resolves_key_from_dotenv(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".env").write_text('GEMINI_API_KEY="test_dotenv_key"\n', encoding="utf-8")
        mock_client = MagicMock()
        factory = MagicMock(return_value=mock_client)
        adapter = GeminiTutorAdapter(client_factory=factory)
        client = adapter._get_client()
        assert client is mock_client
        factory.assert_called_once_with(api_key="test_dotenv_key")

    def test_resolves_key_from_constructor(self):
        mock_client = MagicMock()
        factory = MagicMock(return_value=mock_client)
        adapter = GeminiTutorAdapter(api_key="explicit_test_key", client_factory=factory)

        # Trigger client creation
        client = adapter._get_client()
        assert client is mock_client
        factory.assert_called_once_with(api_key="explicit_test_key")

    def test_resolves_key_from_environment(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "env_test_key")
        mock_client = MagicMock()
        factory = MagicMock(return_value=mock_client)
        adapter = GeminiTutorAdapter(client_factory=factory)

        client = adapter._get_client()
        assert client is mock_client
        factory.assert_called_once_with(api_key="env_test_key")


class TestMultimodalPromptAndImageExtraction:
    def test_extract_image_bytes_none(self):
        assert extract_image_bytes(None) is None
        assert extract_image_bytes(CapturedScreen(image_data=None)) is None

    def test_extract_image_bytes_raw_bytes(self):
        raw = b"\xff\xd8\xff\xe0test_jpeg"
        cap = CapturedScreen(image_data=raw)
        assert extract_image_bytes(cap) == raw

    def test_extract_image_bytes_from_qpixmap(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        pixmap = QPixmap(32, 32)
        pixmap.fill()
        cap = CapturedScreen(image_data=pixmap)

        image_bytes = extract_image_bytes(cap)
        assert image_bytes is not None
        assert len(image_bytes) > 0
        # Standard JPEG SOI marker
        assert image_bytes[:2] == b"\xff\xd8"

    def test_build_user_prompt(self):
        prompt = build_user_prompt("What is this variable?")
        assert "What is this variable?" in prompt

        geom = DisplayGeometry(x=0, y=0, width=1000, height=800)
        region = SelectedRegion(x=100, y=100, width=200, height=200, display_geometry=geom)
        prompt_with_region = build_user_prompt("Explain", selected_region=region)
        assert "Region of Interest" in prompt_with_region
        assert "[0.1000, 0.1250, 0.2000, 0.2500]" in prompt_with_region


class TestGeminiGenerationAndParsing:
    def test_successful_structured_generation(self):
        mock_client = MagicMock()
        fake_json = json.dumps({
            "intent": "hint",
            "summary": "Focus on the recursive base case.",
            "narration": "In line 4, notice that the function does not check if n equals zero.",
            "overlay_actions": [
                {
                    "action_type": "FOCUS_BOX",
                    "target_normalized": [0.1, 0.2, 0.3, 0.4],
                    "label": "Base Case",
                    "color": "#FF9900",
                }
            ],
            "follow_up": "What happens when n=0 is passed?",
        })

        mock_raw_response = MagicMock()
        mock_raw_response.text = fake_json
        mock_client.models.generate_content.return_value = mock_raw_response

        adapter = GeminiTutorAdapter(
            api_key="dummy_key",
            client_factory=lambda **kw: mock_client,
        )

        req = TutorRequest(question=UserQuestion(transcript="Why does this loop forever?", audio_duration=2.0))
        resp = adapter.generate_response(req)

        assert resp.intent == "hint"
        assert resp.summary == "Focus on the recursive base case."
        assert len(resp.overlay_actions) == 1
        action = resp.overlay_actions[0]
        assert action.action_type == OverlayActionType.HIGHLIGHT
        assert action.target_normalized == (0.1, 0.2, 0.3, 0.4)
        assert action.label == "Base Case"
        assert resp.follow_up == "What happens when n=0 is passed?"

    def test_invalid_json_response_raises_error(self):
        mock_client = MagicMock()
        mock_raw_response = MagicMock()
        mock_raw_response.text = "NOT JSON"
        mock_client.models.generate_content.return_value = mock_raw_response

        adapter = GeminiTutorAdapter(
            api_key="dummy_key",
            client_factory=lambda **kw: mock_client,
        )
        req = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        with pytest.raises(InvalidTutorResponseError, match="Failed to parse or validate Gemini response"):
            adapter.generate_response(req)

    def test_empty_response_raises_error(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = None

        adapter = GeminiTutorAdapter(
            api_key="dummy_key",
            client_factory=lambda **kw: mock_client,
        )
        req = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        with pytest.raises(InvalidTutorResponseError, match="Received empty response"):
            adapter.generate_response(req)

    def test_coordinate_clamping_and_unknown_action_handling(self):
        mock_client = MagicMock()
        fake_json = json.dumps({
            "intent": "solution_step",
            "summary": "Look here",
            "narration": "Full narration",
            "overlay_actions": [
                {
                    "action_type": "UNKNOWN_CUSTOM_TYPE",
                    "target_normalized": [-0.5, 0.2, 1.5, 2.0],  # Out of range
                    "label": "Clamped Box",
                    "color": "blue",
                },
                {
                    "action_type": "arrow",  # lowercase
                    "target_normalized": [0.1, 0.2, 0.5, 0.6],
                    "label": "To Result",
                    "color": None,
                },
                {
                    "action_type": "HIGHLIGHT",
                    "target_normalized": None,  # Invalid: HIGHLIGHT missing target_normalized -> dropped
                    "label": "Missing Coords",
                },
            ],
            "follow_up": None,
        })

        mock_raw_response = MagicMock()
        mock_raw_response.text = fake_json
        mock_client.models.generate_content.return_value = mock_raw_response

        adapter = GeminiTutorAdapter(api_key="dummy_key", client_factory=lambda **kw: mock_client)
        req = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        resp = adapter.generate_response(req)

        # Invalid 3rd action was safely dropped
        assert len(resp.overlay_actions) == 2
        # Action 1: Unknown type becomes NONE, coords clamped
        a1 = resp.overlay_actions[0]
        assert a1.action_type == OverlayActionType.NONE
        assert a1.target_normalized == (0.0, 0.2, 1.0, 1.0)
        assert a1.label == "Clamped Box"

        # Action 2: Lowercase 'arrow' becomes ARROW with valid coordinates
        a2 = resp.overlay_actions[1]
        assert a2.action_type == OverlayActionType.ARROW
        assert a2.target_normalized == (0.1, 0.2, 0.5, 0.6)

    def test_fallback_to_parsed_attribute(self):
        mock_client = MagicMock()
        mock_raw_response = MagicMock()
        mock_raw_response.text = None
        mock_raw_response.parsed = {
            "intent": "hint",
            "summary": "Parsed attribute summary",
            "narration": "Parsed narration",
            "overlay_actions": [],
            "follow_up": None,
        }
        mock_client.models.generate_content.return_value = mock_raw_response

        adapter = GeminiTutorAdapter(api_key="dummy_key", client_factory=lambda **kw: mock_client)
        req = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))
        resp = adapter.generate_response(req)

        assert resp.summary == "Parsed attribute summary"


class TestGeminiExceptionMapping:
    def test_maps_authentication_error(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("403 Forbidden: API_KEY_INVALID")

        adapter = GeminiTutorAdapter(api_key="bad_key", client_factory=lambda **kw: mock_client)
        req = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))

        with pytest.raises(TutorAuthenticationError):
            adapter.generate_response(req)

    def test_maps_rate_limit_error(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded")

        adapter = GeminiTutorAdapter(api_key="test_key", client_factory=lambda **kw: mock_client)
        req = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))

        with pytest.raises(TutorRateLimitError):
            adapter.generate_response(req)

    def test_maps_timeout_error(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Deadline exceeded / timeout waiting for response")

        adapter = GeminiTutorAdapter(api_key="test_key", client_factory=lambda **kw: mock_client)
        req = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))

        with pytest.raises(TutorTimeoutError):
            adapter.generate_response(req)

    def test_maps_service_unavailable_error(self):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("503 Service Unavailable: Connection failed")

        adapter = GeminiTutorAdapter(api_key="test_key", client_factory=lambda **kw: mock_client)
        req = TutorRequest(question=UserQuestion(transcript="Test", audio_duration=1.0))

        with pytest.raises(TutorUnavailableError):
            adapter.generate_response(req)
