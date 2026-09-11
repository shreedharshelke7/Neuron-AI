"""Audio capture contracts and models for Block 2."""

from app.audio.errors import (
    AudioCancellationError,
    AudioCaptureError,
    AudioError,
    EmptyAudioError,
    MicrophoneAccessDeniedError,
    MicrophoneUnavailableError,
)
from app.audio.model import AudioCaptureResult
from app.audio.recorder import SoundDeviceAudioCaptureService
from app.audio.service import AudioCaptureService, FakeAudioCaptureService
from app.audio.vad import EndOfSpeechConfig, EndOfSpeechDetector

__all__ = [
    "AudioCancellationError",
    "AudioCaptureError",
    "AudioCaptureResult",
    "AudioCaptureService",
    "AudioError",
    "EmptyAudioError",
    "EndOfSpeechConfig",
    "EndOfSpeechDetector",
    "FakeAudioCaptureService",
    "MicrophoneAccessDeniedError",
    "MicrophoneUnavailableError",
    "SoundDeviceAudioCaptureService",
]
