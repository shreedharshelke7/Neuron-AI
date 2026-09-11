"""Pydantic schemas for Gemini structured JSON output in Block 3."""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class OverlayActionSchema(BaseModel):
    """Schema for structured visual guidance actions."""

    action_type: str = Field(
        description="Type of overlay action: HIGHLIGHT, ARROW, TEXT, CARD, EQUATION, or NONE"
    )
    target_normalized: Optional[List[float]] = Field(
        default=None,
        description="Normalized coordinates bounded strictly within 0.0 to 1.0. For HIGHLIGHT/CARD: [nx, ny, nw, nh]. For ARROW: [x1, y1, x2, y2]. For TEXT/EQUATION: [nx, ny, nw, nh] position.",
    )
    label: Optional[str] = Field(
        default=None,
        description="Concise annotation or label (e.g. for HIGHLIGHT or ARROW)",
    )
    text: Optional[str] = Field(
        default=None,
        description="Educational note (TEXT), formula/LaTeX expression (EQUATION), or body text (CARD)",
    )
    title: Optional[str] = Field(
        default=None,
        description="Title for callout card (CARD)",
    )
    color: Optional[str] = Field(
        default=None,
        description="Optional hex color or name (e.g. #4285F4 or blue)",
    )


class TutorResponseSchema(BaseModel):
    """Schema for structured educational response from Gemini."""

    intent: str = Field(
        description="Educational intent: explanation, hint, clarification, or solution_step"
    )
    summary: str = Field(
        description="Concise educational summary (1-3 sentences) suitable for quick reading in the desktop UI"
    )
    narration: str = Field(
        description="Detailed conversational explanation suitable for audio narration and complete understanding"
    )
    overlay_actions: List[OverlayActionSchema] = Field(
        default_factory=list,
        description="List of visual overlay guidance actions corresponding to elements on the user's screen",
    )
    follow_up: Optional[str] = Field(
        default=None,
        description="Optional Socratic follow-up question to prompt user reflection or next exploration step",
    )
