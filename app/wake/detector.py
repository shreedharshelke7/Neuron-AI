"""Wake word detector abstraction and configuration for Block 6.

Guarantees:
- FR-01: Shared canonical activation entry point with keyboard shortcuts.
- FR-02: Visible listening feedback and cancellation capability.
- NFR-05: Zero continuous audio persistence; ephemeral in-memory frames only.
- NFR-06: Data minimization; no audio saved to disk or transmitted to cloud.
- NFR-08: Provider-independent abstraction interface.
- NFR-10: 100% local/offline execution using free-tier / local models.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable, Optional, Union


@dataclass
class WakeWordConfig:
    """Configuration settings for wake word detection."""

    enabled: bool = True
    phrase: str = "Hey Neuron"
    model_name: str = "base.en"
    silence_threshold: float = 200.0  # RMS energy gating threshold (16-bit int)
    sample_rate: int = 16000  # 16kHz standard for whisper
    channels: int = 1  # Mono
    sample_width: int = 2  # 16-bit PCM (int16)
    chunk_duration_ms: int = 100  # 100ms per audio chunk
    buffer_duration_seconds: float = 1.8  # Max speech buffer length
    debounce_seconds: float = 1.5  # Minimum interval between trigger detections
    device: Optional[Union[int, str]] = None


class WakeWordDetector(ABC):
    """Abstract interface for local/offline wake-word detectors."""

    @abstractmethod
    def start(self) -> bool:
        """Start background passive listening.
        
        Returns True if listening started, False if disabled or unavailable.
        """
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop background listening cleanly and release all audio/system resources."""
        ...

    @abstractmethod
    def pause(self) -> None:
        """Temporarily release the microphone stream so other audio services can record."""
        ...

    @abstractmethod
    def resume(self) -> bool:
        """Re-acquire the microphone and resume passive listening."""
        ...

    @property
    @abstractmethod
    def is_listening(self) -> bool:
        """Whether the detector is currently actively listening on the microphone."""
        ...

    @property
    @abstractmethod
    def is_paused(self) -> bool:
        """Whether the detector is currently paused with its microphone released."""
        ...

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the detector backend and dependencies are available on this system."""
        ...

    @abstractmethod
    def set_on_detected(self, callback: Callable[[], None]) -> None:
        """Register the callback to invoke when the wake phrase is detected."""
        ...

    @property
    @abstractmethod
    def config(self) -> WakeWordConfig:
        """Access active detector configuration."""
        ...
