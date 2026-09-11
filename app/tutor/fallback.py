"""Fallback and Demo mode orchestration for Block 7.

Provides:
- DemoMode enum: LIVE, FALLBACK, AUTO.
- resolve_demo_mode: Resolves configuration from env or .env file, defaulting to AUTO.
- FallbackTutorAdapter: Deterministic local tutor adapter fulfilling the TutorAdapter contract
  with 0 external cloud calls and instant execution.
"""

from __future__ import annotations

import logging
import os
from enum import Enum
from typing import Optional

from app.tutor.adapter import TutorAdapter
from app.tutor.errors import InvalidTutorResponseError
from app.tutor.model import TutorRequest, TutorResponse
from app.tutor.scenario import (
    DemoScenario,
    DemoScenarioId,
    DemoScenarioMatcher,
    DemoScenarioRegistry,
)

logger = logging.getLogger(__name__)


class DemoMode(str, Enum):
    """Execution modes for Neuron AI tutor reasoning."""

    LIVE = "live"          # Live Gemini only; errors propagate per Block 3 contract
    FALLBACK = "fallback"  # Zero Gemini calls; deterministic local scenario responses only
    AUTO = "auto"          # Live-first: attempts Gemini; recovers with deterministic fallback on failure

    @classmethod
    def from_string(cls, value: Optional[str]) -> "DemoMode":
        """Safely parse a string into a DemoMode, defaulting to AUTO."""
        if not value:
            return cls.AUTO
        val = value.strip().lower()
        if val == "live":
            return cls.LIVE
        if val == "fallback":
            return cls.FALLBACK
        if val == "auto":
            return cls.AUTO
        logger.warning("Unrecognized NEURON_DEMO_MODE '%s'; defaulting to AUTO.", value)
        return cls.AUTO


def resolve_demo_mode() -> DemoMode:
    """Resolve demo mode from environment variable or workspace .env file, defaulting to AUTO."""
    env_mode = os.environ.get("NEURON_DEMO_MODE")
    if env_mode and env_mode.strip():
        return DemoMode.from_string(env_mode.strip())

    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or not line or "=" not in line:
                        continue
                    k, val = line.split("=", 1)
                    if k.strip() == "NEURON_DEMO_MODE":
                        candidate = val.strip().strip('"').strip("'")
                        if candidate:
                            return DemoMode.from_string(candidate)
        except Exception:
            pass

    return DemoMode.AUTO


class FallbackTutorAdapter(TutorAdapter):
    """Deterministic local adapter providing prevalidated scenario explanations for Block 7.

    Guarantees:
    - 0 cloud API calls (zero Gemini token usage, zero cloud credentials required).
    - Returns fully schema-valid TutorResponse instances using existing Block 4 primitives.
    - Ephemeral execution with immediate response (< 5ms).
    """

    def __init__(
        self,
        matcher: Optional[DemoScenarioMatcher] = None,
        registry: Optional[DemoScenarioRegistry] = None,
    ) -> None:
        self.registry = registry or DemoScenarioRegistry()
        self.matcher = matcher or DemoScenarioMatcher(self.registry)

    def generate_response(self, request: TutorRequest) -> TutorResponse:
        """Match the student request to a demo scenario and generate a deterministic response."""
        if request is None:
            raise ValueError("TutorRequest cannot be None.")

        scenario: DemoScenario = self.matcher.match(request)
        logger.info(
            "FallbackTutorAdapter generating response for scenario: %s (%s)",
            scenario.scenario_id.value,
            scenario.name,
        )

        response = scenario.builder(request)

        # Sanity check validation
        if not response.summary or not response.summary.strip():
            raise InvalidTutorResponseError("Fallback response summary must not be empty.")
        if not response.narration or not response.narration.strip():
            raise InvalidTutorResponseError("Fallback response narration must not be empty.")

        return response
