"""Neuron AI Text-to-Speech (TTS) module for Block 5."""

from app.tts.adapter import FakeTTSAdapter, TTSAdapter
from app.tts.elevenlabs import ElevenLabsTTSAdapter
from app.tts.errors import (
    TTSAuthenticationError,
    TTSConfigurationError,
    TTSError,
    TTSNetworkError,
    TTSPaidPlanRequiredError,
    TTSPlaybackError,
    TTSQuotaExceededError,
    TTSTimeoutError,
    is_terminal_tts_error,
)
from app.tts.model import NarrationPlan, NarrationSegment, TTSAudioClip
from app.tts.playback import (
    AudioPlaybackService,
    FakeAudioPlaybackService,
    SoundDevicePlaybackService,
)

__all__ = [
    "AudioPlaybackService",
    "ElevenLabsTTSAdapter",
    "FakeAudioPlaybackService",
    "FakeTTSAdapter",
    "NarrationPlan",
    "NarrationSegment",
    "SoundDevicePlaybackService",
    "TTSAdapter",
    "TTSAudioClip",
    "TTSAuthenticationError",
    "TTSConfigurationError",
    "TTSError",
    "TTSNetworkError",
    "TTSPaidPlanRequiredError",
    "TTSPlaybackError",
    "TTSQuotaExceededError",
    "TTSTimeoutError",
    "is_terminal_tts_error",
]
