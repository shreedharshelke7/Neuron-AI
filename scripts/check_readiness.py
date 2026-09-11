"""CLI readiness diagnostic script for Neuron AI (Block 8).

Validates:
- Environment variables and API keys (.env)
- Audio input recording device (sounddevice)
- Audio output playback device (sounddevice)
- PySide6 display backend and graphics context
- STT transcription engine availability
- Demo scenario fixtures and deterministic fallbacks

Usage:
    python scripts/check_readiness.py
"""

from __future__ import annotations

import os
import sys

# Ensure repository root is on sys.path when invoked directly
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.diagnostics.readiness import ReadinessChecker


def main() -> int:
    """Run all readiness checks and output a human-readable diagnostic report."""
    checker = ReadinessChecker()
    report = checker.run_all_checks()
    print(report.format_report())
    return 0 if report.is_ready else 1


if __name__ == "__main__":
    sys.exit(main())
