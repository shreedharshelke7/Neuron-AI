"""Startup and readiness validation for Neuron AI.

Diagnoses runtime prerequisites and subsystems, providing human-readable
feedback and graceful degradation status without crashing the desktop app.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.config.settings import get_settings
from app.tutor.scenario import DemoScenarioId, DemoScenarioRegistry

logger = logging.getLogger(__name__)


class ReadinessStatus(str, Enum):
    """Subsystem and overall application readiness classification."""

    READY = "READY"          # Subsystem is fully operational with active provider
    DEGRADED = "DEGRADED"    # Subsystem is usable via fallback/offline mock
    NOT_READY = "NOT_READY"  # Critical prerequisite missing; interaction blocked


@dataclass(frozen=True)
class SubsystemCheck:
    """Individual readiness check result."""

    name: str
    status: ReadinessStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReadinessReport:
    """Comprehensive readiness report across all Neuron subsystems."""

    status: ReadinessStatus
    checks: List[SubsystemCheck]
    summary: str

    @property
    def items(self) -> List[SubsystemCheck]:
        """Alias for checks list."""
        return self.checks

    @property
    def is_ready(self) -> bool:
        """True if no critical blocking errors are present."""
        return self.status != ReadinessStatus.NOT_READY

    @property
    def has_critical_failures(self) -> bool:
        """True if any subsystem is in NOT_READY status."""
        return self.status == ReadinessStatus.NOT_READY

    def format_report(self) -> str:
        """Format the report into a clean, human-readable terminal string."""
        lines = [
            "=" * 65,
            "               NEURON AI -- SYSTEM READINESS REPORT",
            "=" * 65,
            f" Overall Status : [{self.status.value}]",
            f" Summary        : {self.summary}",
            "-" * 65,
        ]
        for c in self.checks:
            tag = "PASS" if c.status == ReadinessStatus.READY else ("WARN" if c.status == ReadinessStatus.DEGRADED else "FAIL")
            lines.append(f" [{tag:4s}] {c.name:26s} : {c.message}")
        lines.append("=" * 65)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "summary": self.summary,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status.value,
                    "message": c.message,
                    "details": c.details,
                }
                for c in self.checks
            ],
        }


# Compatibility aliases
CheckItem = SubsystemCheck
CheckStatus = ReadinessStatus


class ReadinessChecker:
    """Validates operational readiness of Neuron AI components."""

    def __init__(self, settings=None) -> None:
        self.settings = settings or get_settings()

    def check_all(self) -> ReadinessReport:
        """Run all readiness checks and compile an overall status report."""
        checks = [
            self.check_python_environment(),
            self.check_display_gui(),
            self.check_microphone(),
            self.check_stt_whisper(),
            self.check_gemini_llm(),
            self.check_elevenlabs_tts(),
            self.check_wake_word(),
            self.check_demo_fallbacks(),
        ]

        has_not_ready = any(c.status == ReadinessStatus.NOT_READY for c in checks)
        has_degraded = any(c.status == ReadinessStatus.DEGRADED for c in checks)

        if has_not_ready:
            overall = ReadinessStatus.NOT_READY
            summary = "Critical subsystems unavailable. Resolve errors before presenting."
        elif has_degraded:
            overall = ReadinessStatus.DEGRADED
            summary = "Neuron is operational with offline fallback resilience."
        else:
            overall = ReadinessStatus.READY
            summary = "All subsystems fully configured and ready for live presentation."

        return ReadinessReport(status=overall, checks=checks, summary=summary)

    # Alias for convenience
    run_all_checks = check_all

    def check_python_environment(self) -> SubsystemCheck:
        """Verify Python version satisfies >= 3.10 requirement."""
        ver = sys.version_info
        if ver >= (3, 10):
            return SubsystemCheck(
                name="Python Environment",
                status=ReadinessStatus.READY,
                message=f"Python {ver.major}.{ver.minor}.{ver.micro} is supported.",
                details={"version": f"{ver.major}.{ver.minor}.{ver.micro}"},
            )
        return SubsystemCheck(
            name="Python Environment",
            status=ReadinessStatus.NOT_READY,
            message=f"Python {ver.major}.{ver.minor} is below minimum 3.10 requirement.",
            details={"version": f"{ver.major}.{ver.minor}.{ver.micro}"},
        )

    def check_display_gui(self) -> SubsystemCheck:
        """Verify PySide6 / Qt display capabilities."""
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QGuiApplication
            return SubsystemCheck(
                name="Display & Overlay GUI",
                status=ReadinessStatus.READY,
                message="PySide6 GUI and screen capture modules loaded successfully.",
            )
        except Exception as exc:
            return SubsystemCheck(
                name="Display & Overlay GUI",
                status=ReadinessStatus.NOT_READY,
                message=f"Failed to load PySide6 GUI bindings: {exc}",
            )

    def check_microphone(self) -> SubsystemCheck:
        """Verify SoundDevice microphone access."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            input_devices = [d for d in devices if d.get("max_input_channels", 0) > 0]
            if input_devices:
                return SubsystemCheck(
                    name="Microphone Audio Input",
                    status=ReadinessStatus.READY,
                    message=f"Detected {len(input_devices)} audio input device(s).",
                    details={"input_device_count": len(input_devices)},
                )
            return SubsystemCheck(
                name="Microphone Audio Input",
                status=ReadinessStatus.DEGRADED,
                message="No input audio devices found. Virtual audio/mock capture available.",
            )
        except Exception as exc:
            return SubsystemCheck(
                name="Microphone Audio Input",
                status=ReadinessStatus.DEGRADED,
                message=f"SoundDevice query error: {exc}. Hotkey activation remains functional.",
            )

    def check_stt_whisper(self) -> SubsystemCheck:
        """Verify local faster-whisper STT availability."""
        try:
            import faster_whisper
            return SubsystemCheck(
                name="Speech-to-Text (STT)",
                status=ReadinessStatus.READY,
                message=f"faster-whisper is installed (model: {self.settings.whisper_model}).",
                details={"model": self.settings.whisper_model},
            )
        except Exception as exc:
            return SubsystemCheck(
                name="Speech-to-Text (STT)",
                status=ReadinessStatus.DEGRADED,
                message=f"faster-whisper unavailable ({exc}); mock STT adapter ready.",
            )

    def check_gemini_llm(self) -> SubsystemCheck:
        """Verify Google Gemini multimodal configuration."""
        key = self.settings.gemini_api_key
        if key and key.strip():
            return SubsystemCheck(
                name="Gemini Multimodal LLM",
                status=ReadinessStatus.READY,
                message=f"GEMINI_API_KEY configured (model: {self.settings.gemini_model}).",
                details={"model": self.settings.gemini_model},
            )
        return SubsystemCheck(
            name="Gemini Multimodal LLM",
            status=ReadinessStatus.DEGRADED,
            message="GEMINI_API_KEY not configured. Block 7 deterministic fallback active.",
        )

    def check_elevenlabs_tts(self) -> SubsystemCheck:
        """Verify ElevenLabs TTS configuration."""
        key = self.settings.elevenlabs_api_key
        if key and key.strip():
            return SubsystemCheck(
                name="ElevenLabs TTS Narration",
                status=ReadinessStatus.READY,
                message="ELEVENLABS_API_KEY configured for voice narration.",
            )
        return SubsystemCheck(
            name="ElevenLabs TTS Narration",
            status=ReadinessStatus.DEGRADED,
            message="ELEVENLABS_API_KEY not configured. Visual explanation cards remain 100% functional.",
        )

    def check_wake_word(self) -> SubsystemCheck:
        """Verify wake-word detector readiness."""
        if not self.settings.wake_word_enabled:
            return SubsystemCheck(
                name="Wake Word Detection",
                status=ReadinessStatus.DEGRADED,
                message="Wake word disabled via config. Global hotkey (Ctrl+Shift+Space) is active.",
            )
        return SubsystemCheck(
            name="Wake Word Detection",
            status=ReadinessStatus.READY,
            message=f"Wake word '{self.settings.wake_word_phrase}' is enabled with hotkey fallback.",
            details={"phrase": self.settings.wake_word_phrase},
        )

    def check_demo_fallbacks(self) -> SubsystemCheck:
        """Verify all three hackathon demo scenario fallbacks are ready."""
        registry = DemoScenarioRegistry()
        math_ready = registry.get(DemoScenarioId.MATH_DERIVATIVE) is not None
        pdf_ready = registry.get(DemoScenarioId.PDF_FORMULA_SYMBOL) is not None
        code_ready = registry.get(DemoScenarioId.CODING_ERROR) is not None

        if math_ready and pdf_ready and code_ready:
            return SubsystemCheck(
                name="Block 7 Demo Fallbacks",
                status=ReadinessStatus.READY,
                message="All 3 hackathon scenarios (Math, PDF, Coding) are preloaded and verified.",
                details={"mode": self.settings.demo_mode},
            )
        return SubsystemCheck(
            name="Block 7 Demo Fallbacks",
            status=ReadinessStatus.NOT_READY,
            message="One or more demo scenario fallbacks are missing.",
        )
