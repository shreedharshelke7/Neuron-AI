"""Sequence Controller coordinating visual overlay presentation and audio narration for Block 5.

Guarantees:
- FR-13: Speaks generated explanation using TTS.
- FR-14: Presents explanation actions in defined order so narration and visuals feel coherent.
- FR-15: Immediate dismissal and audio halt on Escape.
- FR-16: Works seamlessly with concise fallback cards and summaries.
- FR-17: Graceful recoverable failure handling if speech output fails (visuals remain).
- FR-18: Pure in-memory session isolation with stale-session token protection.
- AC-07: Narration plays while explanation overlay is visible.
- AC-08: Escape cancels session and stops audio immediately.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Callable, List, Optional

from app.capture.model import DisplayGeometry, SelectedRegion
from app.overlay.host import OverlayHost
from app.tts.adapter import TTSAdapter
from app.tts.model import TTSAudioClip
from app.tts.playback import AudioPlaybackService
from app.tutor.model import TutorResponse

logger = logging.getLogger(__name__)


def partition_narration(text: Optional[str]) -> List[str]:
    """Partition narration text into logical, ordered sentence segments for sequencing."""
    if not text or not text.strip():
        return []
    clean = text.strip()

    # Split on sentence boundaries (. ! ? or newlines) while preserving complete thoughts
    raw_segments = re.split(r"(?<=[.!?])\s+|\n+", clean)
    segments = [s.strip() for s in raw_segments if s and s.strip()]
    return segments if segments else [clean]


class SequenceController:
    """Orchestrates ordered narration playback and visual overlay presentation."""

    def __init__(
        self,
        tts_adapter: Optional[TTSAdapter] = None,
        playback_service: Optional[AudioPlaybackService] = None,
        overlay_host: Optional[OverlayHost] = None,
        on_started: Optional[Callable[[int], None]] = None,
        on_finished: Optional[Callable[[int], None]] = None,
        on_error: Optional[Callable[[str, int], None]] = None,
    ) -> None:
        self.tts_adapter: Optional[TTSAdapter] = tts_adapter
        self.playback_service: Optional[AudioPlaybackService] = playback_service
        self.overlay_host: Optional[OverlayHost] = overlay_host

        self.on_started: Optional[Callable[[int], None]] = on_started
        self.on_finished: Optional[Callable[[int], None]] = on_finished
        self.on_error: Optional[Callable[[str, int], None]] = on_error

        self._active_token: int = 0
        self._cancelled: bool = False
        self._is_active: bool = False
        self._worker_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    @property
    def is_active(self) -> bool:
        """Return True if sequencing or playback is actively running."""
        with self._lock:
            return self._is_active and not self._cancelled

    @property
    def is_playing(self) -> bool:
        """Return True if audio playback is actively outputting sound."""
        return self.playback_service.is_playing if self.playback_service else False

    def cancel(self) -> None:
        """Immediately stop audio playback, abort upcoming segments, and invalidate sequence."""
        with self._lock:
            if not self._is_active and not (self.playback_service and self.playback_service.is_playing):
                return
            self._cancelled = True
            self._is_active = False
            self._active_token += 1

        if self.playback_service is not None:
            try:
                self.playback_service.stop()
            except Exception as ex:
                logger.warning("Error stopping audio playback service during cancel: %s", ex)

        logger.debug("SequenceController cancelled and stopped active narration.")

    def start_sequence(
        self,
        response: TutorResponse,
        token: int,
        geometry: Optional[DisplayGeometry] = None,
        selected_region: Optional[SelectedRegion] = None,
    ) -> None:
        """Begin ordered visual explanation presentation and spoken narration."""
        # Cancel any previous active sequence immediately to prevent overlapping audio
        self.cancel()

        with self._lock:
            self._active_token = token
            self._cancelled = False
            self._is_active = True

        if hasattr(self.tts_adapter, "reset_terminal_error"):
            try:
                self.tts_adapter.reset_terminal_error()
            except Exception:
                pass

        # AC-07: Ensure visual overlay is rendered before or when narration starts
        if self.overlay_host is not None:
            try:
                self.overlay_host.render_tutor_response(
                    response=response,
                    geometry=geometry,
                    selected_region=selected_region,
                )
            except Exception as ex:
                logger.warning("Error displaying overlay visuals for sequence: %s", ex)

        # If narration is empty, visual explanation remains and sequence completes cleanly
        narration_text = response.narration.strip() if response.narration else ""
        if not narration_text:
            logger.info("TutorResponse contains no narration text; visual-only explanation.")
            with self._lock:
                self._is_active = False
            if self.on_finished:
                self.on_finished(token)
            return

        # If no TTS adapter or playback service configured, visual explanation remains
        if self.tts_adapter is None or self.playback_service is None:
            logger.info("No TTS adapter or playback service configured; visual-only mode.")
            with self._lock:
                self._is_active = False
            if self.on_finished:
                self.on_finished(token)
            return

        segments = partition_narration(narration_text)
        logger.info(
            "Starting narration sequence for token %d (%d segments, %d chars total)",
            token,
            len(segments),
            len(narration_text),
        )

        if self.on_started:
            try:
                self.on_started(token)
            except Exception as ex:
                logger.debug("Error in on_started callback: %s", ex)

        # Run synthesis and playback sequentially on a dedicated background worker thread
        self._worker_thread = threading.Thread(
            target=self._run_sequencing_worker,
            args=(response, segments, token),
            name=f"tts-sequence-{token}",
            daemon=True,
        )
        self._worker_thread.start()

    def _run_sequencing_worker(
        self, response: TutorResponse, segments: List[str], token: int
    ) -> None:
        """Background worker thread executing ordered narration synthesis and playback."""
        for seg_idx, segment_text in enumerate(segments):
            # Check for cancellation or stale token before synthesis
            with self._lock:
                if self._cancelled or self._active_token != token:
                    logger.debug("Sequence worker aborted before segment %d (stale or cancelled).", seg_idx)
                    return

            # Synthesize segment audio
            clip: Optional[TTSAudioClip] = None
            try:
                clip = self.tts_adapter.synthesize(segment_text)
            except Exception as ex:
                logger.error("TTS synthesis error on segment %d ('%s'): %s", seg_idx, segment_text[:30], ex)
                with self._lock:
                    self._cancelled = True
                    self._is_active = False
                if self.on_error:
                    try:
                        self.on_error(str(ex), token)
                    except Exception as cb_err:
                        logger.debug("Error invoking on_error callback: %s", cb_err)
                return

            # Check for cancellation or stale token before playback
            with self._lock:
                if self._cancelled or self._active_token != token:
                    logger.debug("Sequence worker aborted after synthesizing segment %d.", seg_idx)
                    return

            if clip is None or clip.is_empty:
                continue

            # Play segment and wait for it to finish (or be cancelled)
            playback_finished_event = threading.Event()

            def _on_clip_done():
                playback_finished_event.set()

            try:
                self.playback_service.play(clip, on_finished=_on_clip_done)
            except Exception as play_ex:
                logger.error("Audio playback error on segment %d: %s", seg_idx, play_ex)
                with self._lock:
                    self._cancelled = True
                    self._is_active = False
                if self.on_error:
                    try:
                        self.on_error(str(play_ex), token)
                    except Exception as cb_err:
                        logger.debug("Error invoking on_error callback: %s", cb_err)
                return

            # Wait for segment playback to complete or cancellation
            while not playback_finished_event.is_set():
                with self._lock:
                    if self._cancelled or self._active_token != token:
                        logger.debug("Playback interrupted during segment %d.", seg_idx)
                        return
                playback_finished_event.wait(timeout=0.05)

        # All segments finished successfully
        with self._lock:
            if not self._cancelled and self._active_token == token:
                self._is_active = False
                should_finish = True
            else:
                should_finish = False

        if should_finish and self.on_finished:
            try:
                self.on_finished(token)
            except Exception as ex:
                logger.debug("Error in on_finished callback: %s", ex)
