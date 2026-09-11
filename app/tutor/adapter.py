"""Abstract base contract and test adapter for Tutor Engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List, Optional

from app.tutor.model import (
    OverlayAction,
    OverlayActionType,
    TutorRequest,
    TutorResponse,
)


class TutorAdapter(ABC):
    """Abstract provider-independent contract for LLM Tutor operations.

    Block 3 decouples the core tutoring loop from Google Gemini, enabling
    deterministic testing and zero-lock-in architecture.
    """

    @abstractmethod
    def generate_response(self, request: TutorRequest) -> TutorResponse:
        """Process a multimodal TutorRequest and return a strongly typed TutorResponse.

        Raises:
            TutorError: or subclasses on authentication, rate limit, timeout, or network failures.
        """


class FakeTutorAdapter(TutorAdapter):
    """Deterministic, side-effect-free fake adapter for offline unit testing."""

    def __init__(
        self,
        default_response: Optional[TutorResponse] = None,
        exception_to_raise: Optional[Exception] = None,
        custom_handler: Optional[Callable[[TutorRequest], TutorResponse]] = None,
    ) -> None:
        self.default_response = default_response or TutorResponse(
            intent="explanation",
            summary="This is a test explanation.",
            narration="Here is a detailed explanation of the concept shown on your screen.",
            overlay_actions=[
                OverlayAction(
                    action_type=OverlayActionType.FOCUS_BOX,
                    target_normalized=(0.1, 0.2, 0.3, 0.4),
                    label="Test Element",
                    color="#4285F4",
                )
            ],
            follow_up="Would you like to try solving a similar problem?",
        )
        self.exception_to_raise = exception_to_raise
        self.custom_handler = custom_handler
        self.recorded_requests: List[TutorRequest] = []

    def generate_response(self, request: TutorRequest) -> TutorResponse:
        """Record the request and return the configured response or raise the exception."""
        self.recorded_requests.append(request)

        if self.exception_to_raise is not None:
            raise self.exception_to_raise

        if self.custom_handler is not None:
            return self.custom_handler(request)

        return self.default_response
