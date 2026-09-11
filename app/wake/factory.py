"""Factory for instantiating the appropriate wake word detector based on environment and availability."""

from __future__ import annotations

import logging
import os
from typing import Optional

from app.wake.detector import WakeWordConfig, WakeWordDetector
from app.wake.fake import FakeWakeWordDetector
from app.wake.whisper_wake import LocalWhisperWakeDetector

logger = logging.getLogger(__name__)


def _read_env_var(var_name: str, default: Optional[str] = None) -> Optional[str]:
    """Read variable from process environment or workspace .env file."""
    if var_name in os.environ:
        return os.environ[var_name].strip()

    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("#") or not line or "=" not in line:
                        continue
                    k, val = line.split("=", 1)
                    if k.strip() == var_name:
                        return val.strip()
        except Exception:
            pass

    return default


def load_wake_config_from_env() -> WakeWordConfig:
    """Load wake word detector configuration from environment variables."""
    enabled_str = (_read_env_var("NEURON_WAKE_WORD_ENABLED", "true") or "true").lower()
    enabled = enabled_str not in ("0", "false", "no", "off", "disabled")

    phrase = _read_env_var("NEURON_WAKE_WORD_PHRASE", "Hey Neuron") or "Hey Neuron"
    model_name = _read_env_var("NEURON_WAKE_WORD_MODEL", "base.en") or "base.en"

    thresh_str = _read_env_var("NEURON_WAKE_WORD_THRESHOLD", "200.0") or "200.0"
    try:
        threshold = float(thresh_str)
    except ValueError:
        threshold = 200.0

    device_str = _read_env_var("NEURON_WAKE_WORD_DEVICE", "")
    device = None
    if device_str:
        try:
            device = int(device_str)
        except ValueError:
            device = device_str

    return WakeWordConfig(
        enabled=enabled,
        phrase=phrase,
        model_name=model_name,
        silence_threshold=threshold,
        device=device,
    )


def create_wake_detector(
    config: Optional[WakeWordConfig] = None,
    allow_fake: bool = True,
) -> WakeWordDetector:
    """Create and return a configured wake word detector with graceful fallback.

    If wake word is disabled or audio/model dependencies fail, returns a safe
    FakeWakeWordDetector so the desktop shell and hotkey trigger continue
    operating without error.
    """
    cfg = config or load_wake_config_from_env()

    if not cfg.enabled:
        logger.info("Wake word activation is disabled via configuration.")
        return FakeWakeWordDetector(config=cfg, is_available=False)

    try:
        detector = LocalWhisperWakeDetector(config=cfg)
        return detector
    except Exception as exc:
        logger.warning(
            "Wake word detector could not be initialized (%s). "
            "Continuing with hotkey activation only.",
            exc,
        )
        if allow_fake:
            return FakeWakeWordDetector(config=cfg, is_available=False)
        raise
