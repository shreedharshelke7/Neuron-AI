"""TutorEngine orchestrating pedagogical reasoning and LLM interactions."""

from __future__ import annotations

import logging
from typing import Optional, Union

from app.tutor.adapter import TutorAdapter
from app.tutor.errors import InvalidTutorResponseError, TutorError
from app.tutor.fallback import DemoMode, FallbackTutorAdapter, resolve_demo_mode
from app.tutor.gemini import GeminiTutorAdapter
from app.tutor.model import TutorRequest, TutorResponse

logger = logging.getLogger(__name__)


class TutorEngine:
    """Orchestrates educational reasoning over multimodal inputs in Neuron AI.

    Block 7 enhancements:
    - Supports live-first, auto-fallback, and deterministic fallback demo execution.
    - Preserves primary adapter (Gemini) as authoritative in LIVE and successful AUTO modes.
    - Seamlessly recovers with prevalidated deterministic demo scenarios on network/provider failures in AUTO mode.
    - Produces identical, strongly typed TutorResponse instances consumed by Block 4 Overlay and Block 5 TTS.
    """

    def __init__(
        self,
        adapter: Optional[TutorAdapter] = None,
        fallback_adapter: Optional[TutorAdapter] = None,
        demo_mode: Optional[Union[DemoMode, str]] = None,
    ) -> None:
        if adapter is None and fallback_adapter is None:
            # Default instantiation (production / shell): configure both Gemini and Fallback with auto mode
            self._adapter: TutorAdapter = GeminiTutorAdapter()
            self._fallback_adapter: Optional[TutorAdapter] = FallbackTutorAdapter()
            self._demo_mode: DemoMode = (
                DemoMode.from_string(demo_mode)
                if demo_mode is not None
                else resolve_demo_mode()
            )
        elif adapter is not None and fallback_adapter is None:
            # Explicit primary adapter provided without fallback (e.g. legacy/isolated unit tests):
            # preserve pure adapter behavior without fallback unless explicitly configured
            self._adapter = adapter
            self._fallback_adapter = None
            self._demo_mode = (
                DemoMode.from_string(demo_mode)
                if demo_mode is not None
                else DemoMode.LIVE
            )
        else:
            # Explicit configuration of both or fallback
            self._adapter = adapter if adapter is not None else GeminiTutorAdapter()
            self._fallback_adapter = fallback_adapter
            self._demo_mode = (
                DemoMode.from_string(demo_mode)
                if demo_mode is not None
                else resolve_demo_mode()
            )

    @property
    def adapter(self) -> TutorAdapter:
        """The active primary tutor adapter."""
        return self._adapter

    @property
    def fallback_adapter(self) -> Optional[TutorAdapter]:
        """The active fallback tutor adapter, if configured."""
        return self._fallback_adapter

    @property
    def demo_mode(self) -> DemoMode:
        """The current demo/fallback mode (LIVE, FALLBACK, or AUTO)."""
        return self._demo_mode

    def set_demo_mode(self, mode: Union[DemoMode, str]) -> None:
        """Dynamically update the demo mode."""
        self._demo_mode = DemoMode.from_string(mode) if isinstance(mode, str) else mode
        logger.info("TutorEngine demo mode updated to: %s", self._demo_mode.value)

    def set_fallback_adapter(self, fallback_adapter: Optional[TutorAdapter]) -> None:
        """Configure or swap the active fallback tutor adapter."""
        self._fallback_adapter = fallback_adapter

    def process_request(self, request: TutorRequest) -> TutorResponse:
        """Process a validated multimodal student request and return educational guidance.

        Raises:
            ValueError: if the request payload is invalid.
            TutorError: or subclasses if the LLM invocation or parsing fails and fallback is unavailable.
        """
        if request is None:
            raise ValueError("TutorRequest cannot be None.")

        request.validate()

        logger.info(
            "TutorEngine processing request (token=%d, mode=%s, has_capture=%s, has_region=%s, transcript_length=%d)",
            request.session_token,
            self._demo_mode.value,
            request.capture is not None,
            request.selected_region is not None,
            len(request.question.transcript),
        )

        # 1. Deterministic FALLBACK mode: bypass primary provider entirely (0 Gemini calls)
        if self._demo_mode == DemoMode.FALLBACK and self._fallback_adapter is not None:
            logger.info("DemoMode.FALLBACK active: generating deterministic scenario response.")
            response = self._fallback_adapter.generate_response(request)
            self._validate_response(response)
            return response

        # 2. LIVE or AUTO mode: Attempt primary provider first (Live-First Rule)
        try:
            response = self._adapter.generate_response(request)
            self._validate_response(response)
            logger.info(
                "TutorEngine primary adapter generated response (intent=%s, actions_count=%d, summary_len=%d)",
                response.intent,
                len(response.overlay_actions),
                len(response.summary),
            )
            return response
        except Exception as exc:
            # If AUTO mode and fallback adapter is available, recover with deterministic fallback
            if self._demo_mode == DemoMode.AUTO and self._fallback_adapter is not None:
                logger.warning(
                    "Primary TutorAdapter failed (%s: %s). Recovering via deterministic fallback.",
                    type(exc).__name__,
                    exc,
                )
                try:
                    fallback_response = self._fallback_adapter.generate_response(request)
                    self._validate_response(fallback_response)
                    logger.info(
                        "TutorEngine fallback recovered response (intent=%s, actions_count=%d, summary_len=%d)",
                        fallback_response.intent,
                        len(fallback_response.overlay_actions),
                        len(fallback_response.summary),
                    )
                    return fallback_response
                except Exception as fb_exc:
                    logger.exception("Fallback adapter also failed: %s", fb_exc)
                    raise TutorError(f"Both primary and fallback tutor failed: {fb_exc}") from fb_exc

            # In LIVE mode or when no fallback adapter is configured, propagate the failure
            if isinstance(exc, (TutorError, ValueError)):
                raise
            logger.exception("Unexpected error in TutorAdapter: %s", exc)
            raise TutorError(f"Unexpected tutor generation error: {exc}") from exc

    def _validate_response(self, response: TutorResponse) -> None:
        """Ensure the produced response adheres to minimal pedagogical standards."""
        if response is None:
            raise InvalidTutorResponseError("TutorAdapter returned None response.")

        if not response.summary or not response.summary.strip():
            raise InvalidTutorResponseError("TutorResponse summary cannot be empty.")

        if not response.narration or not response.narration.strip():
            raise InvalidTutorResponseError("TutorResponse narration cannot be empty.")
