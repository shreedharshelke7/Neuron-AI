"""Error hierarchy for Block 3 Tutor / Multimodal LLM layer."""

from __future__ import annotations


class TutorError(Exception):
    """Base exception for all Tutor Engine and LLM adapter operations."""


class TutorUnavailableError(TutorError):
    """Raised when the LLM service or network connection is unavailable."""


class TutorAuthenticationError(TutorError):
    """Raised when authentication fails due to missing or invalid credentials."""


class TutorRateLimitError(TutorError):
    """Raised when the API rate limit or quota has been exceeded."""


class TutorTimeoutError(TutorError):
    """Raised when the LLM request exceeds the allotted timeout period."""


class InvalidTutorResponseError(TutorError):
    """Raised when the LLM response is malformed, unparseable, or fails validation."""
