"""Tutor package for Neuron AI Block 3 Multimodal LLM reasoning."""

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
from app.tutor.gemini import GeminiTutorAdapter
from app.tutor.model import (
    OverlayAction,
    OverlayActionType,
    TutorRequest,
    TutorResponse,
)

__all__ = [
    "TutorEngine",
    "TutorAdapter",
    "GeminiTutorAdapter",
    "FakeTutorAdapter",
    "TutorRequest",
    "TutorResponse",
    "OverlayAction",
    "OverlayActionType",
    "TutorError",
    "TutorUnavailableError",
    "TutorAuthenticationError",
    "TutorRateLimitError",
    "TutorTimeoutError",
    "InvalidTutorResponseError",
]
