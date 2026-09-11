"""Deterministic scripted demo scenarios and matcher for Block 7.

Implements the three authoritative hackathon demonstration scenarios:
1. Online math lecture: graph/derivative/slope, e.g. "Why is the slope zero here?"
2. PDF / Notes: formula / symbol, e.g. "What does this symbol mean?"
3. Coding lesson: short function / error / bug, e.g. "Why does this code fail?"
plus a safe generic fallback when no scenario matches confidently.

Guarantees:
- Fully compliant with the existing TutorResponse and OverlayAction models.
- Uses existing Block 4 primitives: HIGHLIGHT, ARROW, TEXT, CARD, EQUATION.
- Uses normalized [0.0, 1.0] coordinates; prefers selected-region targeting when available.
- 100% offline and deterministic: zero external cloud calls, zero embeddings, zero OCR.
- Sentence-punctuated narration segments designed for Block 5 ElevenLabs TTS sequencing.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Tuple

from app.capture.model import DisplayGeometry, SelectedRegion
from app.tutor.model import (
    OverlayAction,
    OverlayActionType,
    TutorRequest,
    TutorResponse,
)

logger = logging.getLogger(__name__)


class DemoScenarioId(str, Enum):
    """Unique identifiers for the three required hackathon scenarios plus generic fallback."""

    MATH_DERIVATIVE = "MATH_DERIVATIVE"
    PDF_FORMULA_SYMBOL = "PDF_FORMULA_SYMBOL"
    CODING_ERROR = "CODING_ERROR"
    GENERIC_FALLBACK = "GENERIC_FALLBACK"


def resolve_normalized_target(
    request: TutorRequest,
    default_box: Tuple[float, float, float, float],
) -> Tuple[float, float, float, float]:
    """Derive normalized [0.0, 1.0] coordinates from selected_region if available, else default."""
    if request.selected_region is not None:
        try:
            geom = (
                request.capture.geometry
                if request.capture and request.capture.geometry
                else request.selected_region.display_geometry
            )
            if geom is not None and geom.width > 0 and geom.height > 0:
                norm = request.selected_region.to_normalized(geom)
                return (
                    round(max(0.0, min(1.0, norm[0])), 4),
                    round(max(0.0, min(1.0, norm[1])), 4),
                    round(max(0.001, min(1.0, norm[2])), 4),
                    round(max(0.001, min(1.0, norm[3])), 4),
                )
        except Exception as ex:
            logger.debug("Could not derive normalized coordinates from selected_region: %s", ex)
    return default_box


def build_math_scenario_response(request: TutorRequest) -> TutorResponse:
    """Build a deterministic response for Demo Scenario 1: Mathematics / Derivative / Graph.

    Context: Online math lecture with a graph/derivative visible.
    Question: 'Why is the slope zero here?' or 'Explain the derivative and show me the important part.'
    Concepts:
    - At a smooth local maximum or minimum, the tangent line is horizontal.
    - A horizontal line has slope 0.
    - The derivative represents the slope of the tangent line.
    - Therefore, the derivative equals zero at that stationary point.
    """
    box = resolve_normalized_target(request, (0.35, 0.45, 0.30, 0.25))

    actions = [
        OverlayAction(
            action_type=OverlayActionType.HIGHLIGHT,
            target_normalized=box,
            label="Stationary Point / Local Extremum",
            color="#4285F4",
        ),
        OverlayAction(
            action_type=OverlayActionType.ARROW,
            target_normalized=(
                box[0] + box[2] / 2,
                max(0.0, box[1] - 0.12),
                box[0] + box[2] / 2,
                box[1],
            ),
            label="Horizontal Tangent",
            color="#EA4335",
        ),
        OverlayAction(
            action_type=OverlayActionType.EQUATION,
            target_normalized=(box[0], min(0.88, box[1] + box[3] + 0.04), box[2], 0.08),
            text="f'(x) = 0",
            label="Derivative Zero Condition",
            color="#34A853",
        ),
        OverlayAction(
            action_type=OverlayActionType.CARD,
            target_normalized=(0.05, 0.08, 0.38, 0.24),
            title="Horizontal Tangent & Derivative",
            text="At a smooth local extremum, the curve flattens and the tangent line becomes completely horizontal. Since tangent slope equals the derivative, f'(x) = 0.",
            color="#1A73E8",
        ),
    ]

    return TutorResponse(
        intent="explanation",
        summary="At a smooth local extremum, the tangent line is horizontal (slope = 0). Because the derivative represents tangent slope, the derivative equals zero at this point.",
        narration="At this point on the graph, the curve reaches a smooth local minimum. Notice how the tangent line becomes completely horizontal. Because the derivative represents the instantaneous rate of change or slope of that tangent, and a horizontal line has zero steepness, the derivative here equals zero.",
        overlay_actions=actions,
        follow_up="Would you like to analyze another point on this curve or calculate the second derivative?",
    )


def build_pdf_scenario_response(request: TutorRequest) -> TutorResponse:
    """Build a deterministic response for Demo Scenario 2: PDF / Formula / Symbol.

    Context: PDF or lecture notes with mathematical or scientific notation visible.
    Question: 'What does this symbol mean?' or 'What does this part mean?'
    Concepts:
    - Breaks down the specific operator or component in the formula.
    - Directly targets the student's selected region if available.
    - Displays a concise concept card and points to the symbol.
    """
    box = resolve_normalized_target(request, (0.40, 0.32, 0.20, 0.16))

    actions = [
        OverlayAction(
            action_type=OverlayActionType.HIGHLIGHT,
            target_normalized=box,
            label="Selected Formula Component",
            color="#FBBC04",
        ),
        OverlayAction(
            action_type=OverlayActionType.ARROW,
            target_normalized=(
                box[0],
                max(0.0, box[1] - 0.10),
                box[0] + box[2] / 2,
                box[1],
            ),
            label="Operator Definition",
            color="#4285F4",
        ),
        OverlayAction(
            action_type=OverlayActionType.CARD,
            target_normalized=(0.05, 0.08, 0.38, 0.24),
            title="Symbol Definition",
            text="This symbol represents an aggregation operator. It specifies the mathematical operation applied to the terms across the indicated lower and upper index bounds.",
            color="#1A73E8",
        ),
    ]

    return TutorResponse(
        intent="explanation",
        summary="This symbol represents an operator denoting the summation of terms across the specified range.",
        narration="This part of the formula represents the operator symbol. In mathematical notation, it instructs us to aggregate or sum the expression for each step across the given indices, accumulating each term into a single total.",
        overlay_actions=actions,
        follow_up="Would you like to examine the index bounds or expand the first few terms?",
    )


def build_coding_scenario_response(request: TutorRequest) -> TutorResponse:
    """Build a deterministic response for Demo Scenario 3: Coding Lesson / Bug.

    Context: IDE or coding environment with a short function, error, or bug.
    Question: 'Why does this code fail?'
    Concepts:
    - Highlights the faulty line/region in the code.
    - Explains the conceptual root cause (e.g. off-by-one index out of bounds).
    - Shows the corrected concept/code on an overlay card without opening another window.
    """
    box = resolve_normalized_target(request, (0.18, 0.32, 0.64, 0.08))

    actions = [
        OverlayAction(
            action_type=OverlayActionType.HIGHLIGHT,
            target_normalized=box,
            label="Index Boundary Error",
            color="#EA4335",
        ),
        OverlayAction(
            action_type=OverlayActionType.CARD,
            target_normalized=(0.05, 0.08, 0.40, 0.26),
            title="Cause of Failure",
            text="IndexError: The loop condition attempts to access an index equal to len(items). Python collections are zero-indexed up to len-1. Use 'for item in items:' to iterate safely.",
            color="#D93025",
        ),
        OverlayAction(
            action_type=OverlayActionType.TEXT,
            target_normalized=(box[0], min(0.90, box[1] + box[3] + 0.04), box[2], 0.08),
            text="Suggested Fix: for item in items: ...",
            label="Corrected Idiom",
            color="#34A853",
        ),
    ]

    return TutorResponse(
        intent="debugging",
        summary="The code fails because an index lookup exceeds the collection bounds, causing an IndexError.",
        narration="This code fails because the loop index attempts to access an element past the end of the collection. In Python, list indices are zero-based, so accessing an index equal to the length raises an IndexError. You can fix this by iterating directly over the items instead of manually indexing.",
        overlay_actions=actions,
        follow_up="Would you like to see how to refactor this using list comprehension or enumerate?",
    )


def build_generic_scenario_response(request: TutorRequest) -> TutorResponse:
    """Build a safe generic fallback response when no specific scenario matches confidently.

    Context: Live model/network is unavailable and question does not match known demo fixtures.
    Concepts:
    - Acknowledges offline assistance mode.
    - Highlights current screen focus.
    - Displays guidance inviting specific questions or region selection.
    """
    box = resolve_normalized_target(request, (0.25, 0.25, 0.50, 0.50))

    actions = [
        OverlayAction(
            action_type=OverlayActionType.HIGHLIGHT,
            target_normalized=box,
            label="Active Screen Focus",
            color="#80868B",
        ),
        OverlayAction(
            action_type=OverlayActionType.CARD,
            target_normalized=(0.05, 0.08, 0.40, 0.24),
            title="Offline Demo Mode",
            text="Neuron is operating in offline demo mode. You can ask about graph derivatives, formula symbols, or coding errors for guided interactive explanations.",
            color="#5F6368",
        ),
    ]

    return TutorResponse(
        intent="assistance",
        summary="Neuron offline assistance active. Demonstrations available for math graphs, formula symbols, and coding lessons.",
        narration="Neuron is currently in offline assistance mode. I have focused your screen region. You can ask about the slope of a graph, a formula symbol, or a coding error for a complete interactive demonstration.",
        overlay_actions=actions,
        follow_up="Try asking: 'Why is the slope zero here?' or 'Why does this code fail?'",
    )


@dataclass(frozen=True)
class DemoScenario:
    """Definition and builder for a deterministic demo scenario."""

    scenario_id: DemoScenarioId
    name: str
    keywords: List[str]
    builder: Callable[[TutorRequest], TutorResponse]


class DemoScenarioRegistry:
    """Registry maintaining available deterministic demo scenarios."""

    def __init__(self) -> None:
        self._scenarios: Dict[DemoScenarioId, DemoScenario] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        self.register(
            DemoScenario(
                scenario_id=DemoScenarioId.MATH_DERIVATIVE,
                name="Mathematics: Derivative & Tangent Slope",
                keywords=[
                    "slope",
                    "derivative",
                    "graph",
                    "tangent",
                    "maximum",
                    "minimum",
                    "x²",
                    "x^2",
                    "zero",
                    "vertex",
                    "extremum",
                    "stationary",
                    "parabola",
                    "rate of change",
                    "rate",
                    "f(x)",
                ],
                builder=build_math_scenario_response,
            )
        )
        self.register(
            DemoScenario(
                scenario_id=DemoScenarioId.PDF_FORMULA_SYMBOL,
                name="PDF / Formula: Mathematical Symbol Meaning",
                keywords=[
                    "symbol",
                    "formula",
                    "part",
                    "notation",
                    "mean",
                    "equation",
                    "pdf",
                    "sigma",
                    "summation",
                    "integral",
                    "operator",
                    "term",
                    "expression",
                ],
                builder=build_pdf_scenario_response,
            )
        )
        self.register(
            DemoScenario(
                scenario_id=DemoScenarioId.CODING_ERROR,
                name="Coding: Debugging Function Error / Bug",
                keywords=[
                    "code",
                    "fail",
                    "error",
                    "function",
                    "bug",
                    "line",
                    "exception",
                    "variable",
                    "index",
                    "syntax",
                    "crash",
                    "loop",
                    "traceback",
                    "indentation",
                ],
                builder=build_coding_scenario_response,
            )
        )
        self.register(
            DemoScenario(
                scenario_id=DemoScenarioId.GENERIC_FALLBACK,
                name="Generic Offline Assistance Fallback",
                keywords=[],
                builder=build_generic_scenario_response,
            )
        )

    def register(self, scenario: DemoScenario) -> None:
        """Register or override a scenario in the registry."""
        self._scenarios[scenario.scenario_id] = scenario

    def get(self, scenario_id: DemoScenarioId) -> Optional[DemoScenario]:
        """Retrieve a scenario by ID."""
        return self._scenarios.get(scenario_id)

    def list_scenarios(self) -> List[DemoScenario]:
        """List all registered scenarios."""
        return list(self._scenarios.values())


class DemoScenarioMatcher:
    """Deterministic, lightweight keyword-based scenario matcher.

    Guarantees:
    - Pure local evaluation: 0 cloud/LLM requests.
    - Normalized text matching with tokenization.
    - Explicit tag support: `[scenario:math]`, `[scenario:pdf]`, `[scenario:coding]`.
    - Env override support: `NEURON_DEMO_SCENARIO` (math, pdf, coding, generic).
    - Falls back safely to GENERIC_FALLBACK when no keywords match.
    """

    def __init__(self, registry: Optional[DemoScenarioRegistry] = None) -> None:
        self.registry = registry or DemoScenarioRegistry()

    def match(self, request: TutorRequest) -> DemoScenario:
        """Match a student TutorRequest to the most appropriate demo scenario."""
        transcript = request.question.transcript.strip() if request.question else ""
        transcript_lower = transcript.lower()

        # 1. Check environment variable override
        env_scenario = os.environ.get("NEURON_DEMO_SCENARIO", "").strip().lower()
        if env_scenario:
            if env_scenario in ("math", "derivative", "slope"):
                return self.registry.get(DemoScenarioId.MATH_DERIVATIVE) or self._fallback()
            if env_scenario in ("pdf", "formula", "symbol"):
                return self.registry.get(DemoScenarioId.PDF_FORMULA_SYMBOL) or self._fallback()
            if env_scenario in ("code", "coding", "bug", "error"):
                return self.registry.get(DemoScenarioId.CODING_ERROR) or self._fallback()
            if env_scenario in ("generic", "fallback", "default"):
                return self._fallback()

        # 2. Check explicit scenario tags in question transcript
        if "[scenario:math]" in transcript_lower:
            return self.registry.get(DemoScenarioId.MATH_DERIVATIVE) or self._fallback()
        if "[scenario:pdf]" in transcript_lower:
            return self.registry.get(DemoScenarioId.PDF_FORMULA_SYMBOL) or self._fallback()
        if "[scenario:coding]" in transcript_lower or "[scenario:code]" in transcript_lower:
            return self.registry.get(DemoScenarioId.CODING_ERROR) or self._fallback()
        if "[scenario:generic]" in transcript_lower:
            return self._fallback()

        # 3. Keyword matching against registered scenarios
        cleaned = re.sub(r"[^\w\s\^²']", " ", transcript_lower)
        tokens = set(cleaned.split())

        scores: Dict[DemoScenarioId, int] = {}
        for scenario_id in (
            DemoScenarioId.MATH_DERIVATIVE,
            DemoScenarioId.PDF_FORMULA_SYMBOL,
            DemoScenarioId.CODING_ERROR,
        ):
            scenario = self.registry.get(scenario_id)
            if not scenario:
                continue

            score = 0
            for kw in scenario.keywords:
                kw_lower = kw.lower()
                if " " in kw_lower:
                    if kw_lower in transcript_lower:
                        score += 3
                elif kw_lower in tokens:
                    score += 2
                elif kw_lower in transcript_lower:
                    score += 1

            scores[scenario_id] = score

        best_id: Optional[DemoScenarioId] = None
        best_score = 0
        for s_id, score in scores.items():
            if score > best_score:
                best_score = score
                best_id = s_id

        if best_id is not None and best_score >= 1:
            matched = self.registry.get(best_id)
            if matched:
                logger.info(
                    "DemoScenarioMatcher matched scenario '%s' (score=%d) for transcript: '%s'",
                    best_id.value,
                    best_score,
                    transcript,
                )
                return matched

        logger.info(
            "DemoScenarioMatcher: no confident match for transcript '%s'; selecting generic fallback.",
            transcript,
        )
        return self._fallback()

    def _fallback(self) -> DemoScenario:
        generic = self.registry.get(DemoScenarioId.GENERIC_FALLBACK)
        if generic is not None:
            return generic
        return DemoScenario(
            scenario_id=DemoScenarioId.GENERIC_FALLBACK,
            name="Generic Offline Assistance Fallback",
            keywords=[],
            builder=build_generic_scenario_response,
        )
