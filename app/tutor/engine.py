"""TutorEngine orchestrating pedagogical reasoning and LLM interactions."""

from __future__ import annotations

import logging
from typing import Optional

from app.tutor.adapter import TutorAdapter
from app.tutor.errors import InvalidTutorResponseError, TutorError
from app.tutor.gemini import GeminiTutorAdapter
from app.tutor.model import TutorRequest, TutorResponse

logger = logging.getLogger(__name__)


class TutorEngine:
    """Orchestrates educational reasoning over multimodal inputs in Neuron AI."""

    def __init__(self, adapter: Optional[TutorAdapter] = None) -> None:
        self._adapter: TutorAdapter = adapter if adapter is not None else GeminiTutorAdapter()

    @property
    def adapter(self) -> TutorAdapter:
        """The active underlying tutor adapter."""
        return self._adapter

    def process_request(self, request: TutorRequest) -> TutorResponse:
        """Process a validated multimodal student request and return educational guidance.

        Raises:
            ValueError: if the request payload is invalid.
            TutorError: or subclasses if the LLM invocation or parsing fails.
        """
        if request is None:
            raise ValueError("TutorRequest cannot be None.")

        request.validate()

        logger.info(
            "TutorEngine processing request (token=%d, has_capture=%s, has_region=%s, transcript_length=%d)",
            request.session_token,
            request.capture is not None,
            request.selected_region is not None,
            len(request.question.transcript),
        )

        try:
            response = self._adapter.generate_response(request)
        except TutorError:
            raise
        except Exception as exc:
            logger.exception("Unexpected error in TutorAdapter: %s", exc)
            raise TutorError(f"Unexpected tutor generation error: {exc}") from exc

        self._validate_response(response)

        logger.info(
            "TutorEngine generated response (intent=%s, actions_count=%d, summary_len=%d)",
            response.intent,
            len(response.overlay_actions),
            len(response.summary),
        )

        return response

    def _validate_response(self, response: TutorResponse) -> None:
        """Ensure the produced response adheres to minimal pedagogical standards."""
        if response is None:
            raise InvalidTutorResponseError("TutorAdapter returned None response.")

        if not response.summary or not response.summary.strip():
            raise InvalidTutorResponseError("TutorResponse summary cannot be empty.")

        if not response.narration or not response.narration.strip():
            raise InvalidTutorResponseError("TutorResponse narration cannot be empty.")
