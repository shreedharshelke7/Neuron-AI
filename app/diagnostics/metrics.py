"""Metrics and observability system for Neuron AI (SRS NFR-12 & DiagnosticEvent).

Guarantees:
- Strictly privacy-safe: logs and records stage, duration_ms, and error category.
- Zero raw screenshots, pixel buffers, or audio PCM streams stored or logged.
- Bounded in-memory circular buffer with thread safety.
- Real measured timing using high-resolution performance counters.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

# Disallowed keys in metadata to prevent sensitive screen or voice data leakage
SENSITIVE_KEYS = {"image", "screenshot", "raw_bytes", "pcm", "audio_data", "frame", "pixels"}


class DiagnosticStage(str, Enum):
    """Stages of the Neuron interaction and pedagogical lifecycle."""

    ACTIVATION = "ACTIVATION"
    CAPTURE = "CAPTURE"
    LISTENING = "LISTENING"
    STT = "STT"
    THINKING = "THINKING"
    OVERLAY = "OVERLAY"
    TTS = "TTS"
    SESSION = "SESSION"
    FALLBACK = "FALLBACK"
    DISMISSAL = "DISMISSAL"


@dataclass(frozen=True)
class DiagnosticEvent:
    """SRS-compliant diagnostic event capturing lifecycle stage, duration, and status."""

    stage: DiagnosticStage
    duration_ms: float
    success: bool = True
    error_code: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        """Validate and sanitize event metadata to prevent privacy leaks."""
        if not isinstance(self.stage, DiagnosticStage):
            try:
                object.__setattr__(self, "stage", DiagnosticStage(str(self.stage).upper()))
            except Exception:
                pass

        # Defensive sanitize against raw screen/audio data leakage
        if self.metadata:
            for k in list(self.metadata.keys()):
                if any(s in k.lower() for s in SENSITIVE_KEYS):
                    logger.warning("Sanitized sensitive key '%s' from DiagnosticEvent metadata.", k)
                    self.metadata.pop(k, None)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize event to a clean dictionary."""
        return {
            "stage": self.stage.value if hasattr(self.stage, "value") else str(self.stage),
            "duration_ms": round(float(self.duration_ms), 2),
            "success": self.success,
            "error_code": self.error_code,
            "metadata": dict(self.metadata),
            "timestamp": self.timestamp,
        }


class MetricsCollector:
    """Thread-safe collector for in-memory session diagnostics and timing."""

    def __init__(self, max_events: int = 200, enabled: bool = True) -> None:
        self._max_events = max_events
        self._enabled = enabled
        self._events: List[DiagnosticEvent] = []
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, val: bool) -> None:
        self._enabled = val

    def record_event(self, event: DiagnosticEvent) -> None:
        """Record a completed diagnostic event into the bounded buffer."""
        if not self._enabled or event is None:
            return

        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                self._events.pop(0)

        logger.debug(
            "DiagnosticEvent: stage=%s duration=%.1fms success=%s error=%s",
            event.stage.value if hasattr(event.stage, "value") else str(event.stage),
            event.duration_ms,
            event.success,
            event.error_code,
        )

    @contextmanager
    def time_stage(
        self,
        stage: DiagnosticStage,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Generator[Dict[str, Any], None, None]:
        """Context manager to measure and record the execution duration of a stage."""
        meta = dict(metadata) if metadata is not None else {}
        start_time = time.perf_counter()
        success = True
        error_code: Optional[str] = None
        try:
            yield meta
        except Exception as exc:
            success = False
            error_code = type(exc).__name__
            raise
        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            event = DiagnosticEvent(
                stage=stage,
                duration_ms=elapsed_ms,
                success=success,
                error_code=error_code,
                metadata=meta,
            )
            self.record_event(event)

    def get_events(self, stage: Optional[DiagnosticStage] = None) -> List[DiagnosticEvent]:
        """Return a snapshot of recorded events, optionally filtered by stage."""
        with self._lock:
            if stage is None:
                return list(self._events)
            return [e for e in self._events if e.stage == stage]

    def get_summary(self) -> Dict[str, Any]:
        """Compute aggregated statistics per diagnostic stage."""
        with self._lock:
            events = list(self._events)

        summary: Dict[str, Any] = {
            "total_events": len(events),
            "stages": {},
        }

        stage_groups: Dict[str, List[DiagnosticEvent]] = {}
        for ev in events:
            st = ev.stage.value if hasattr(ev.stage, "value") else str(ev.stage)
            stage_groups.setdefault(st, []).append(ev)

        for st, group in stage_groups.items():
            durations = [e.duration_ms for e in group]
            successes = [e for e in group if e.success]
            summary["stages"][st] = {
                "count": len(group),
                "success_count": len(successes),
                "failure_count": len(group) - len(successes),
                "avg_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0.0,
                "min_duration_ms": round(min(durations), 2) if durations else 0.0,
                "max_duration_ms": round(max(durations), 2) if durations else 0.0,
            }

        return summary

    def clear(self) -> None:
        """Clear all recorded diagnostic events."""
        with self._lock:
            self._events.clear()


_global_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Return the global singleton MetricsCollector instance."""
    global _global_metrics_collector
    if _global_metrics_collector is None:
        _global_metrics_collector = MetricsCollector()
    return _global_metrics_collector
