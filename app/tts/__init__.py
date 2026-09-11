"""Neuron AI Text-to-Speech (TTS) module for Block 5."""

from app.tts.adapter import FakeTTSAdapter, TTSAdapter
from app.tts.elevenlabs import ElevenLabsTTSAdapter
from app.tts.errors import (
    TTSAuthenticationError,
    TTSError,
    TTSNetworkError,
    TTSPlaybackError,
    TTSQuotaExceededError,
    TTSTimeoutError,
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
    "TTSError",
    "TTSNetworkError",
    "TTSPlaybackError",
    "TTSQuotaExceededError",
    "TTSTimeoutError",
]
