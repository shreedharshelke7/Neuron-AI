"""Overlay Renderer orchestrating visual primitives and coordinate mapping for Block 4.

Responsible for:
- Consuming validated TutorResponse and its OverlayActions
- Mapping coordinates safely via CoordinateMapper
- Instantiating appropriate visual primitives (HIGHLIGHT, ARROW, TEXT, CARD, EQUATION)
- Defensively isolating primitive failures so malformed actions do not crash the desktop shell
- Providing a concise text FallbackSummaryCard when the visual plan is empty or fails (SRS FR-16)
- Ephemeral in-memory visual presentation with immediate clearing on Escape or session reset
"""

from __future__ import annotations

import logging
from typing import List, Optional

from PySide6.QtGui import QPainter
from app.capture.model import DisplayGeometry, SelectedRegion
from app.overlay.geometry import CoordinateMapper
from app.overlay.primitives import (
    ArrowPrimitive,
    CardPrimitive,
    EquationPrimitive,
    FallbackSummaryCard,
    HighlightPrimitive,
    OverlayPrimitive,
    TextPrimitive,
)
from app.tutor.model import OverlayAction, OverlayActionType, TutorResponse

logger = logging.getLogger(__name__)


class OverlayRenderer:
    """Orchestrates visual guidance primitives and renders them onto the overlay surface."""

    def __init__(self) -> None:
        self._primitives: List[OverlayPrimitive] = []
        self._fallback_card: Optional[FallbackSummaryCard] = None
        self._has_visuals: bool = False
        self._last_geometry: Optional[DisplayGeometry] = None
        self._last_selected_region: Optional[SelectedRegion] = None

    @property
    def primitives(self) -> List[OverlayPrimitive]:
        """Active list of visual primitives (read-only snapshot)."""
        return list(self._primitives)

    @property
    def fallback_card(self) -> Optional[FallbackSummaryCard]:
        """Active fallback summary card, if any."""
        return self._fallback_card

    def has_visuals(self) -> bool:
        """Return True if any visual primitives or fallback card are active."""
        return self._has_visuals and (bool(self._primitives) or self._fallback_card is not None)

    def clear(self) -> None:
        """Clear all active visual primitives and fallback card immediately."""
        self._primitives.clear()
        self._fallback_card = None
        self._has_visuals = False
        self._last_geometry = None
        self._last_selected_region = None

    def render_tutor_response(
        self,
        response: TutorResponse,
        geometry: Optional[DisplayGeometry] = None,
        selected_region: Optional[SelectedRegion] = None,
        relative_to_region: bool = False,
    ) -> bool:
        """Process TutorResponse overlay actions into visual primitives.

        Returns True if visuals (primitives or fallback) were successfully prepared.
        """
        self.clear()
        self._last_geometry = geometry or DisplayGeometry(width=1920, height=1080)
        self._last_selected_region = selected_region
        self._relative_to_region: bool = relative_to_region

        mapper = CoordinateMapper(
            display_geometry=self._last_geometry,
            selected_region=selected_region,
        )

        # Process overlay actions
        for action in response.overlay_actions:
            try:
                self._process_action(action, mapper, relative_to_region=relative_to_region)
            except Exception as ex:
                logger.warning(
                    "Error processing overlay action '%s': %s (skipping this action)",
                    getattr(action, "action_type", "UNKNOWN"),
                    ex,
                )

        # If no visual primitives were produced (empty list, all NONE, or all failed),
        # render concise summary fallback card per SRS FR-16
        if not self._primitives:
            logger.info("No visual primitives generated; displaying fallback summary card.")
            self._fallback_card = FallbackSummaryCard(
                summary=response.summary,
                follow_up=response.follow_up,
                display_geometry=self._last_geometry,
            )

        self._has_visuals = True
        return True

    def _process_action(
        self,
        action: OverlayAction,
        mapper: CoordinateMapper,
        relative_to_region: bool = False,
    ) -> None:
        """Translate a single OverlayAction into a concrete OverlayPrimitive."""
        if not action or not hasattr(action, "action_type"):
            return

        action_type = action.action_type
        if isinstance(action_type, str):
            action_type = OverlayActionType.from_string(action_type)

        # NONE intentionally renders nothing
        if action_type == OverlayActionType.NONE:
            return

        # HIGHLIGHT / FOCUS_BOX / UNDERLINE
        if action_type in (
            OverlayActionType.HIGHLIGHT,
            OverlayActionType.FOCUS_BOX,
            OverlayActionType.UNDERLINE,
        ):
            mapped_rect = mapper.map_action_rect(action, relative_to_region=relative_to_region)
            if mapped_rect is not None and (mapped_rect.width > 0 or mapped_rect.height > 0):
                self._primitives.append(
                    HighlightPrimitive(
                        rect=mapped_rect,
                        label=action.label,
                        color=action.color,
                    )
                )
            return

        # ARROW
        if action_type == OverlayActionType.ARROW:
            mapped_arrow = mapper.map_action_arrow(action, relative_to_region=relative_to_region)
            if mapped_arrow is not None:
                self._primitives.append(
                    ArrowPrimitive(
                        arrow=mapped_arrow,
                        label=action.label,
                        color=action.color,
                    )
                )
            return

        # TEXT / PIN
        if action_type in (OverlayActionType.TEXT, OverlayActionType.PIN):
            mapped_rect = mapper.map_action_rect(action, relative_to_region=relative_to_region)
            text_content = action.text or action.label or ""
            if text_content.strip():
                self._primitives.append(
                    TextPrimitive(
                        rect=mapped_rect,
                        point=None,
                        text=text_content,
                        color=action.color,
                    )
                )
            return

        # CARD
        if action_type == OverlayActionType.CARD:
            mapped_rect = mapper.map_action_rect(action, relative_to_region=relative_to_region)
            self._primitives.append(
                CardPrimitive(
                    rect=mapped_rect,
                    title=action.title,
                    text=action.text or action.label,
                    color=action.color,
                    display_geometry=self._last_geometry,
                )
            )
            return

        # EQUATION
        if action_type == OverlayActionType.EQUATION:
            mapped_rect = mapper.map_action_rect(action, relative_to_region=relative_to_region)
            expr = action.text or action.label or ""
            if expr.strip():
                self._primitives.append(
                    EquationPrimitive(
                        rect=mapped_rect,
                        expression=expr,
                        label=action.label if action.text else None,
                        color=action.color,
                        display_geometry=self._last_geometry,
                    )
                )
            return

        # Unknown action type: safely ignore without failing other primitives
        logger.warning("Unrecognized overlay action type: %s", action_type)

    def paint(self, painter: QPainter) -> None:
        """Paint all active visual explanation elements onto the target QPainter."""
        if not self._has_visuals:
            return

        # Paint fallback card if active
        if self._fallback_card is not None:
            try:
                self._fallback_card.paint(painter)
            except Exception as ex:
                logger.warning("Error rendering fallback card: %s", ex)

        # Paint each primitive with defensive fault-isolation
        for primitive in self._primitives:
            try:
                primitive.paint(painter)
            except Exception as ex:
                logger.warning("Error rendering primitive %s: %s", primitive, ex)
