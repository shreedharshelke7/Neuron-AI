"""Data models and contracts for Block 3 Tutor / Multimodal LLM layer."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.capture.model import CapturedScreen, SelectedRegion
from app.stt.model import UserQuestion


class OverlayActionType(str, Enum):
    """Supported overlay action primitive types for visual guidance (DATA ONLY)."""

    FOCUS_BOX = "FOCUS_BOX"
    ARROW = "ARROW"
    PIN = "PIN"
    UNDERLINE = "UNDERLINE"
    NONE = "NONE"

    @classmethod
    def from_string(cls, value: Optional[str]) -> "OverlayActionType":
        """Safely parse a string into an OverlayActionType, defaulting to NONE."""
        if not value:
            return cls.NONE
        normalized = value.strip().upper()
        for member in cls:
            if member.value == normalized:
                return member
        return cls.NONE


@dataclass(frozen=True)
class OverlayAction:
    """Represents visual guidance metadata produced by the Tutor Engine.

    NOTE: Block 3 defines and validates this DATA ONLY. Block 3 must NOT draw
    or render visual primitives to the screen.
    """

    action_type: OverlayActionType
    target_normalized: Optional[Tuple[float, float, float, float]] = None
    label: Optional[str] = None
    color: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate coordinates upon instantiation."""
        if self.target_normalized is not None:
            if len(self.target_normalized) != 4:
                raise ValueError("target_normalized must contain exactly 4 values (nx, ny, nw, nh).")
            for val in self.target_normalized:
                if not isinstance(val, (int, float)) or not math.isfinite(val):
                    raise ValueError(f"Coordinate {val} is not a finite number.")

    @staticmethod
    def clamp_coordinates(
        coords: Tuple[float, float, float, float]
    ) -> Optional[Tuple[float, float, float, float]]:
        """Validate and clamp coordinates to normalized [0.0, 1.0] bounds.

        Returns None if coordinates contain NaN or Inf.
        """
        if len(coords) != 4:
            return None
        for val in coords:
            if not isinstance(val, (int, float)) or not math.isfinite(val):
                return None

        nx, ny, nw, nh = coords
        nx = max(0.0, min(1.0, float(nx)))
        ny = max(0.0, min(1.0, float(ny)))
        nw = max(0.0, min(1.0 - nx, float(nw)))
        nh = max(0.0, min(1.0 - ny, float(nh)))
        return (round(nx, 4), round(ny, 4), round(nw, 4), round(nh, 4))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize overlay action to a dictionary."""
        return {
            "action_type": self.action_type.value,
            "target_normalized": list(self.target_normalized) if self.target_normalized else None,
            "label": self.label,
            "color": self.color,
        }


@dataclass(frozen=True)
class TutorRequest:
    """Multimodal request payload submitted to the Tutor Engine."""

    question: UserQuestion
    capture: Optional[CapturedScreen] = None
    selected_region: Optional[SelectedRegion] = None
    session_token: int = 0

    def validate(self) -> None:
        """Validate request payload completeness."""
        if not self.question or not self.question.transcript or not self.question.transcript.strip():
            raise ValueError("TutorRequest question transcript must not be empty.")


@dataclass(frozen=True)
class TutorResponse:
    """Structured response produced by the Tutor Engine."""

    intent: str
    summary: str
    narration: str
    overlay_actions: List[OverlayAction] = field(default_factory=list)
    follow_up: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize response to a dictionary."""
        return {
            "intent": self.intent,
            "summary": self.summary,
            "narration": self.narration,
            "overlay_actions": [action.to_dict() for action in self.overlay_actions],
            "follow_up": self.follow_up,
            "timestamp": self.timestamp,
        }
