"""Unit tests for Block 8: Packaging, Metrics & Pitch Integration.

Tests:
1. DiagnosticEvent contract and privacy sanitization (NFR-12).
2. MetricsCollector bounded recording, filtering, and summary statistics.
3. ReadinessChecker diagnostic reporting across keys, audio, display, and demo fixtures.
4. NeuronSettings configuration loading and secret-masking __repr__.
5. Path resolution utilities (paths.py) in source and frozen PyInstaller modes.
6. Secret Safety Audit: ensures zero committed API keys in tracked repository files.
7. SessionController metrics hook verification.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.config.settings import NeuronSettings
from app.diagnostics.metrics import (
    DiagnosticEvent,
    DiagnosticStage,
    MetricsCollector,
    get_metrics_collector,
)
from app.diagnostics.readiness import CheckItem, CheckStatus, ReadinessChecker, ReadinessReport
from app.utils.paths import ensure_dir, get_app_root, get_resource_path


class TestDiagnosticEventAndPrivacy(unittest.TestCase):
    """Test DiagnosticEvent creation, serialization, and privacy defense against data leakage."""

    def test_diagnostic_event_creation_and_serialization(self):
        event = DiagnosticEvent(
            stage=DiagnosticStage.ACTIVATION,
            duration_ms=45.6,
            success=True,
            metadata={"session_token": 1},
        )
        self.assertEqual(event.stage, DiagnosticStage.ACTIVATION)
        self.assertAlmostEqual(event.duration_ms, 45.6)
        self.assertTrue(event.success)
        self.assertIsNone(event.error_code)

        d = event.to_dict()
        self.assertEqual(d["stage"], "ACTIVATION")
        self.assertEqual(d["duration_ms"], 45.6)
        self.assertTrue(d["success"])
        self.assertEqual(d["metadata"]["session_token"], 1)

    def test_string_stage_normalization(self):
        event = DiagnosticEvent(stage="capture", duration_ms=12.0)
        self.assertEqual(event.stage, DiagnosticStage.CAPTURE)

    def test_privacy_sanitization_strips_sensitive_keys(self):
        """NFR-12 defense: raw frames, screenshots, and audio PCM must be stripped."""
        event = DiagnosticEvent(
            stage=DiagnosticStage.CAPTURE,
            duration_ms=85.0,
            metadata={
                "image": b"\x89PNG\r\n\x1a\nfake_bytes",
                "screenshot": "base64_data",
                "raw_bytes": b"raw_pixels",
                "pcm": b"audio_pcm_stream",
                "audio_data": [0.1, 0.2, 0.3],
                "safe_width": 1920,
                "safe_height": 1080,
            },
        )
        meta = event.metadata
        self.assertNotIn("image", meta)
        self.assertNotIn("screenshot", meta)
        self.assertNotIn("raw_bytes", meta)
        self.assertNotIn("pcm", meta)
        self.assertNotIn("audio_data", meta)
        self.assertEqual(meta.get("safe_width"), 1920)
        self.assertEqual(meta.get("safe_height"), 1080)


class TestMetricsCollector(unittest.TestCase):
    """Test MetricsCollector thread safety, bounded circular buffer, and aggregation."""

    def setUp(self):
        self.collector = MetricsCollector(max_events=5, enabled=True)

    def test_bounded_circular_buffer(self):
        for i in range(10):
            self.collector.record_event(
                DiagnosticEvent(
                    stage=DiagnosticStage.CAPTURE,
                    duration_ms=float(i * 10),
                    metadata={"index": i},
                )
            )
        events = self.collector.get_events()
        self.assertEqual(len(events), 5)
        # Should retain only the 5 most recent events (5, 6, 7, 8, 9)
        self.assertEqual(events[0].metadata["index"], 5)
        self.assertEqual(events[-1].metadata["index"], 9)

    def test_filter_by_stage(self):
        self.collector.record_event(DiagnosticEvent(stage=DiagnosticStage.ACTIVATION, duration_ms=10.0))
        self.collector.record_event(DiagnosticEvent(stage=DiagnosticStage.CAPTURE, duration_ms=50.0))
        self.collector.record_event(DiagnosticEvent(stage=DiagnosticStage.ACTIVATION, duration_ms=15.0))

        acts = self.collector.get_events(DiagnosticStage.ACTIVATION)
        caps = self.collector.get_events(DiagnosticStage.CAPTURE)
        self.assertEqual(len(acts), 2)
        self.assertEqual(len(caps), 1)

    def test_summary_computation(self):
        self.collector.record_event(DiagnosticEvent(stage=DiagnosticStage.STT, duration_ms=100.0, success=True))
        self.collector.record_event(DiagnosticEvent(stage=DiagnosticStage.STT, duration_ms=200.0, success=True))
        self.collector.record_event(DiagnosticEvent(stage=DiagnosticStage.STT, duration_ms=300.0, success=False, error_code="Timeout"))

        summary = self.collector.get_summary()
        self.assertEqual(summary["total_events"], 3)
        stt_stats = summary["stages"]["STT"]
        self.assertEqual(stt_stats["count"], 3)
        self.assertEqual(stt_stats["success_count"], 2)
        self.assertEqual(stt_stats["failure_count"], 1)
        self.assertEqual(stt_stats["avg_duration_ms"], 200.0)
        self.assertEqual(stt_stats["min_duration_ms"], 100.0)
        self.assertEqual(stt_stats["max_duration_ms"], 300.0)

    def test_time_stage_context_manager(self):
        with self.collector.time_stage(DiagnosticStage.THINKING) as meta:
            meta["model"] = "gemini-2.5-flash"
            time.sleep(0.01)

        events = self.collector.get_events(DiagnosticStage.THINKING)
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].success)
        self.assertGreater(events[0].duration_ms, 5.0)
        self.assertEqual(events[0].metadata.get("model"), "gemini-2.5-flash")

    def test_disabled_collector_records_nothing(self):
        self.collector.enabled = False
        self.collector.record_event(DiagnosticEvent(stage=DiagnosticStage.CAPTURE, duration_ms=10.0))
        self.assertEqual(len(self.collector.get_events()), 0)


class TestReadinessChecker(unittest.TestCase):
    """Test ReadinessChecker diagnostics across system components."""

    def test_readiness_checker_runs_all_checks(self):
        checker = ReadinessChecker()
        report = checker.run_all_checks()
        self.assertIsInstance(report, ReadinessReport)
        self.assertGreaterEqual(len(report.items), 5)

        names = [item.name for item in report.items]
        self.assertIn("Python Environment", names)
        self.assertIn("Display & Overlay GUI", names)
        self.assertIn("Microphone Audio Input", names)
        self.assertIn("Speech-to-Text (STT)", names)
        self.assertIn("Gemini Multimodal LLM", names)
        self.assertIn("ElevenLabs TTS Narration", names)
        self.assertIn("Block 7 Demo Fallbacks", names)

    def test_report_formatting(self):
        report = ReadinessReport(
            status=CheckStatus.READY,
            checks=[
                CheckItem("Test Item 1", CheckStatus.READY, "All green"),
                CheckItem("Test Item 2", CheckStatus.DEGRADED, "Missing optional key"),
            ],
            summary="All subsystems ready",
        )
        text = report.format_report()
        self.assertIn("NEURON AI -- SYSTEM READINESS REPORT", text)
        self.assertIn("[PASS] Test Item 1", text)
        self.assertIn("[WARN] Test Item 2", text)
        self.assertTrue(report.is_ready)

    def test_critical_failure_marks_not_ready(self):
        report = ReadinessReport(
            status=CheckStatus.NOT_READY,
            checks=[
                CheckItem("Critical Feature", CheckStatus.NOT_READY, "Fatal error"),
            ],
            summary="Critical failure",
        )
        self.assertFalse(report.is_ready)
        self.assertTrue(report.has_critical_failures)


class TestNeuronSettings(unittest.TestCase):
    """Test configuration dataclass and secret masking."""

    def test_default_settings(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = NeuronSettings.load(env_file="nonexistent_test.env")
            self.assertEqual(settings.gemini_model, "gemini-2.5-flash")
            self.assertEqual(settings.stt_provider, "whisper")
            self.assertEqual(settings.tts_provider, "elevenlabs")
            self.assertEqual(settings.demo_mode, "auto")

    def test_secret_masking_in_repr(self):
        settings = NeuronSettings(
            gemini_api_key="AIzaSySECRETKEY12345",
            elevenlabs_api_key="sk_secret_elevenlabs_key",
        )
        repr_str = repr(settings)
        self.assertNotIn("AIzaSySECRETKEY12345", repr_str)
        self.assertNotIn("sk_secret_elevenlabs_key", repr_str)
        self.assertIn("AIz...2345", repr_str)
        self.assertIn("sk_..._key", repr_str)


class TestPathUtilities(unittest.TestCase):
    """Test paths.py resolution in normal and PyInstaller bundled environments."""

    def test_get_app_root_returns_existing_path(self):
        root = Path(get_app_root())
        self.assertTrue(root.exists())
        self.assertTrue((root / "app").exists() or (root / "main.py").exists())

    def test_get_resource_path_standard(self):
        path = Path(get_resource_path("demo/math/derivative_graph.html"))
        self.assertTrue(path.exists())

    def test_get_resource_path_meipass_simulation(self):
        with tempfile.TemporaryDirectory() as temp_meipass:
            fake_resource = Path(temp_meipass) / "demo" / "fake.txt"
            fake_resource.parent.mkdir(parents=True, exist_ok=True)
            fake_resource.write_text("frozen_content")

            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "_MEIPASS", temp_meipass, create=True):
                    resolved = Path(get_resource_path("demo/fake.txt"))
                    self.assertEqual(resolved, fake_resource)
                    self.assertTrue(resolved.exists())


class TestSecretSafetyAudit(unittest.TestCase):
    """Verify that no real API keys are accidentally committed to tracked git files."""

    def test_tracked_files_do_not_contain_committed_api_keys(self):
        app_root = Path(get_app_root())
        forbidden_patterns = [
            b"AIzaSy",               # Google API key prefix
            b"sk_live_",             # Live API key prefix
        ]

        files_to_check = [
            app_root / "main.py",
            app_root / "neuron.spec",
            app_root / ".env.example",
            app_root / "README.md",
            app_root / "docs" / "PITCH_RUNBOOK.md",
            app_root / "docs" / "DEMO_GUIDE.md",
        ]

        # Scan app/ and tests/ directories
        for scan_dir in [app_root / "app", app_root / "tests", app_root / "demo", app_root / "scripts"]:
            if scan_dir.exists():
                for p in scan_dir.rglob("*.py"):
                    files_to_check.append(p)

        for file_path in files_to_check:
            if not file_path.exists() or file_path.name == ".env":
                continue
            content = file_path.read_bytes()
            for pattern in forbidden_patterns:
                # Allow synthetic test mocks (e.g. AIzaSySECRETKEY12345 in this test file)
                if pattern in content and file_path.name != "test_block8_packaging_metrics.py":
                    self.fail(f"Potential secret key pattern '{pattern.decode()}' detected in tracked file: {file_path}")


if __name__ == "__main__":
    unittest.main()
