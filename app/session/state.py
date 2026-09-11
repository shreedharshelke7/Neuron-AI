"""Session state representations for Neuron AI."""

from enum import Enum


class SessionState(str, Enum):
    """Enumeration of interaction lifecycle states."""

    IDLE = "IDLE"
    ACTIVATED = "ACTIVATED"
    CAPTURING = "CAPTURING"
    SELECTING = "SELECTING"
    SELECTED = "SELECTED"
    LISTENING = "LISTENING"
    VOICE_CAPTURED = "VOICE_CAPTURED"
    TRANSCRIBING = "TRANSCRIBING"
    TRANSCRIBED = "TRANSCRIBED"
    ERROR = "ERROR"
