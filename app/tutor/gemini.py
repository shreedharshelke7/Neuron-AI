"""Google Gemini multimodal adapter for Block 3 Tutor Engine."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, List, Optional

from app.tutor.adapter import TutorAdapter
from app.tutor.errors import (
    InvalidTutorResponseError,
    TutorAuthenticationError,
    TutorError,
    TutorRateLimitError,
    TutorTimeoutError,
    TutorUnavailableError,
)
from app.tutor.model import (
    OverlayAction,
    OverlayActionType,
    TutorRequest,
    TutorResponse,
)
from app.tutor.prompt import (
    SYSTEM_INSTRUCTION,
    build_user_prompt,
    extract_image_bytes,
)
from app.tutor.schema import TutorResponseSchema

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiTutorAdapter(TutorAdapter):
    """Multimodal tutor adapter powered by Google Gemini Developer API (Free Tier).

    Guarantees:
    - Side-effect-free instantiation (no client created, no credentials resolved during init).
    - In-memory multimodal processing with zero temporary files written to disk.
    - Uses official google-genai SDK.
    - Strongly typed structured output validation.
    - Comprehensive error mapping to Block 3 domain exceptions.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        client_factory: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._api_key = api_key
        self._model_param = model
        self._client_factory = client_factory
        self._client: Optional[Any] = None

    def _resolve_model(self) -> str:
        """Resolve model from constructor, environment, or .env file, defaulting to DEFAULT_MODEL."""
        if self._model_param and self._model_param.strip():
            return self._model_param.strip()
        env_model = os.environ.get("GEMINI_MODEL")
        if env_model and env_model.strip():
            return env_model.strip()
        env_path = os.path.join(os.getcwd(), ".env")
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GEMINI_MODEL="):
                            candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if candidate:
                                return candidate
            except Exception:
                pass
        return DEFAULT_MODEL

    @property
    def model(self) -> str:
        """The active Gemini model identifier."""
        return self._resolve_model()

    def _resolve_api_key(self) -> str:
        """Resolve API key from instance configuration, environment, or .env file."""
        key = self._api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            env_path = os.path.join(os.getcwd(), ".env")
            if os.path.exists(env_path):
                try:
                    with open(env_path, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if line.startswith("GEMINI_API_KEY="):
                                candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                                if candidate:
                                    key = candidate
                                    break
                except Exception:
                    pass

        if not key or not key.strip():
            raise TutorAuthenticationError(
                "GEMINI_API_KEY is not set or empty. "
                "Set GEMINI_API_KEY in your environment or .env file to enable Gemini multimodal tutoring."
            )
        return key.strip()

    def _get_client(self) -> Any:
        """Lazily initialize and return the Gemini Client."""
        if self._client is not None:
            return self._client

        api_key = self._resolve_api_key()

        if self._client_factory is not None:
            self._client = self._client_factory(api_key=api_key)
            return self._client

        try:
            from google import genai

            self._client = genai.Client(api_key=api_key)
            return self._client
        except Exception as exc:
            logger.exception("Failed to initialize Google GenAI client: %s", exc)
            raise TutorUnavailableError(f"Failed to initialize GenAI client: {exc}") from exc

    def generate_response(self, request: TutorRequest) -> TutorResponse:
        """Process multimodal request using Gemini Developer API with structured outputs."""
        request.validate()

        client = self._get_client()

        # Build textual prompt
        user_text = build_user_prompt(
            transcript=request.question.transcript,
            selected_region=request.selected_region,
            capture=request.capture,
        )

        contents: List[Any] = [user_text]

        # Extract image bytes in-memory if screen capture is available
        image_bytes = extract_image_bytes(request.capture)
        if image_bytes:
            try:
                from google.genai import types

                part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
                contents.append(part)
            except Exception as exc:
                logger.warning("Could not convert capture to GenAI Part: %s", exc)

        max_retries = 3
        raw_response = None
        for attempt in range(1, max_retries + 1):
            try:
                from google.genai import types

                config = types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=TutorResponseSchema,
                    temperature=0.3,
                )

                raw_response = client.models.generate_content(
                    model=self._resolve_model(),
                    contents=contents,
                    config=config,
                )
                break
            except Exception as exc:
                err_str = str(exc).lower()
                err_code = getattr(exc, "code", None)
                if (err_code == 503 or "503" in err_str or "unavailable" in err_str or "high demand" in err_str) and attempt < max_retries:
                    logger.warning("Gemini 503 high demand spike, retrying (attempt %d/%d)...", attempt, max_retries)
                    import time
                    time.sleep(2.0 * attempt)
                    continue
                self._handle_api_exception(exc)

        return self._parse_response(raw_response)

    def _parse_response(self, raw_response: Any) -> TutorResponse:
        """Parse, validate, and convert structured Gemini output into TutorResponse."""
        if raw_response is None:
            raise InvalidTutorResponseError("Received empty response from Gemini API.")

        # Extract text content
        response_text: Optional[str] = getattr(raw_response, "text", None)

        if not response_text:
            # Check if parsed attribute exists
            parsed_data = getattr(raw_response, "parsed", None)
            if parsed_data is not None:
                if isinstance(parsed_data, TutorResponseSchema):
                    data_dict = parsed_data.model_dump()
                elif isinstance(parsed_data, dict):
                    data_dict = parsed_data
                else:
                    try:
                        data_dict = dict(parsed_data)
                    except Exception:
                        data_dict = None
                if data_dict:
                    return self._dict_to_tutor_response(data_dict)

            raise InvalidTutorResponseError("Gemini response did not contain text or structured payload.")

        try:
            data = json.loads(response_text)
            validated = TutorResponseSchema.model_validate(data)
            return self._dict_to_tutor_response(validated.model_dump())
        except Exception as exc:
            raise InvalidTutorResponseError(f"Failed to parse or validate Gemini response JSON: {exc}") from exc

    def _dict_to_tutor_response(self, data: dict) -> TutorResponse:
        """Convert validated schema dict into domain TutorResponse."""
        intent = str(data.get("intent", "explanation"))
        summary = str(data.get("summary", "")).strip()
        narration = str(data.get("narration", "")).strip()
        follow_up = data.get("follow_up")
        if follow_up is not None:
            follow_up = str(follow_up).strip()

        raw_actions = data.get("overlay_actions") or []
        parsed_actions: List[OverlayAction] = []

        for action_data in raw_actions:
            if not isinstance(action_data, dict):
                continue

            raw_type = action_data.get("action_type")
            action_type = OverlayActionType.from_string(raw_type)

            raw_target = action_data.get("target_normalized")
            target_normalized = None
            if raw_target is not None and isinstance(raw_target, (list, tuple)) and len(raw_target) == 4:
                clamped = OverlayAction.clamp_coordinates(tuple(raw_target))  # type: ignore
                if clamped is not None:
                    target_normalized = clamped

            label = action_data.get("label")
            text = action_data.get("text")
            title = action_data.get("title")
            color = action_data.get("color")

            # Fallback for text/label
            if action_type in (OverlayActionType.TEXT, OverlayActionType.EQUATION) and not text and label:
                text = label

            try:
                parsed_actions.append(
                    OverlayAction(
                        action_type=action_type,
                        target_normalized=target_normalized,
                        label=str(label) if label else None,
                        text=str(text) if text else None,
                        title=str(title) if title else None,
                        color=str(color) if color else None,
                    )
                )
            except Exception as exc:
                logger.warning("Dropping invalid overlay action from LLM response: %s", exc)

        return TutorResponse(
            intent=intent,
            summary=summary,
            narration=narration,
            overlay_actions=parsed_actions,
            follow_up=follow_up if follow_up else None,
        )

    def _handle_api_exception(self, exc: Exception) -> None:
        """Map SDK/HTTP exceptions into Block 3 domain exceptions."""
        err_str = str(exc).lower()
        err_code = getattr(exc, "code", None)

        # 1. Authentication
        if err_code in (401, 403) or "api_key" in err_str or "permission_denied" in err_str or "unauthenticated" in err_str:
            raise TutorAuthenticationError(f"Gemini API authentication failed: {exc}") from exc

        # 2. Rate Limit / Quota
        if err_code == 429 or "resource_exhausted" in err_str or "quota" in err_str or "rate limit" in err_str:
            raise TutorRateLimitError(f"Gemini API rate limit or quota exceeded: {exc}") from exc

        # 3. Timeout
        if err_code == 408 or "timeout" in err_str or "deadline_exceeded" in err_str:
            raise TutorTimeoutError(f"Gemini API request timed out: {exc}") from exc

        # 4. Service Unavailable / Network
        if err_code in (500, 502, 503, 504) or "unavailable" in err_str or "connection" in err_str or "network" in err_str:
            raise TutorUnavailableError(f"Gemini service unavailable: {exc}") from exc

        # 5. Fallback generic
        raise TutorError(f"Gemini API request failed: {exc}") from exc
