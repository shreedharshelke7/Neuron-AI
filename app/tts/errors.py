"""Exception hierarchy for Block 5 Text-to-Speech (TTS) and audio playback."""

from __future__ import annotations


class TTSError(Exception):
    """Base exception for all Block 5 TTS errors."""

    def __init__(self, message: str, details: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        return f"{self.message} ({self.details})" if self.details else self.message


class TTSConfigurationError(TTSError):
    """Raised when TTS provider configuration (e.g. ELEVENLABS_VOICE_ID) is missing or invalid."""
    pass


class TTSAuthenticationError(TTSError):
    """Raised when TTS provider credentials (e.g. ELEVENLABS_API_KEY) are missing or invalid."""
    pass


class TTSPaidPlanRequiredError(TTSError):
    """Raised when a TTS feature or voice requires a paid subscription (e.g. HTTP 402 paid_plan_required)."""
    pass


class TTSQuotaExceededError(TTSError):
    """Raised when TTS provider quota or rate limit is exceeded (e.g. HTTP 429)."""
    pass


class TTSTimeoutError(TTSError):
    """Raised when a TTS network synthesis request times out."""
    pass


class TTSNetworkError(TTSError):
    """Raised when a network or connection failure prevents TTS synthesis."""
    pass


class TTSPlaybackError(TTSError):
    """Raised when audio hardware or playback service fails to play audio."""
    pass


def is_terminal_tts_error(error: Exception) -> bool:
    """Determine whether a TTS error is non-recoverable / terminal for a narration sequence.

    Terminal errors indicate that subsequent segment synthesis requests within the same
    tutoring response will also fail or burn quota unnecessarily (e.g. invalid credentials,
    paid plan required, missing voice configuration, quota exhaustion).
    """
    return isinstance(
        error,
        (
            TTSConfigurationError,
            TTSAuthenticationError,
            TTSPaidPlanRequiredError,
            TTSQuotaExceededError,
        ),
    )
