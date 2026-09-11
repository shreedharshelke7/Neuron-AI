"""Per-user non-secret configuration manager for Neuron AI.

Manages user preferences at %LOCALAPPDATA%/NeuronAI/config.json.
Guarantees:
- NEVER writes API keys or secrets into config.json.
- Active validation prevents accidental secret persistence.
- Safe JSON load/store with fallback on missing or corrupt files.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional

from app.utils.paths import get_user_config_path

logger = logging.getLogger(__name__)

# Security guard: substrings that must NEVER be written to plain-text config.json
_FORBIDDEN_KEY_PATTERNS = (
    "api_key",
    "secret",
    "token",
    "password",
    "credential",
    "private_key",
)


def load_user_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """Load the non-secret configuration dictionary from disk."""
    path = config_path or get_user_config_path()
    if not os.path.exists(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            logger.warning("User config at '%s' is not a JSON object; resetting.", path)
            return {}
    except Exception as exc:
        logger.warning("Failed to parse user config at '%s': %s", path, exc)
        return {}


def save_user_config(config_dict: Dict[str, Any], config_path: Optional[str] = None) -> bool:
    """Save non-secret configuration to disk.

    Raises ValueError if any secret-like key is detected.
    """
    for key in config_dict.keys():
        key_lower = key.lower()
        if any(pattern in key_lower for pattern in _FORBIDDEN_KEY_PATTERNS):
            raise ValueError(
                f"Security violation: key '{key}' looks like an API key or secret. "
                "API keys must be stored in Windows Credential Manager via CredentialStore, "
                "never in plain-text config.json."
            )

    path = config_path or get_user_config_path()
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, indent=2)
        # Atomic replace on Windows
        os.replace(temp_path, path)
        return True
    except Exception as exc:
        logger.error("Failed to save user config to '%s': %s", path, exc)
        return False


def get_user_voice_id(config_path: Optional[str] = None) -> Optional[str]:
    """Retrieve ElevenLabs Voice ID from user configuration."""
    cfg = load_user_config(config_path)
    val = cfg.get("elevenlabs_voice_id")
    return str(val).strip() if val else None


def set_user_voice_id(voice_id: str, config_path: Optional[str] = None) -> bool:
    """Store ElevenLabs Voice ID in user configuration."""
    cfg = load_user_config(config_path)
    cfg["elevenlabs_voice_id"] = voice_id.strip()
    return save_user_config(cfg, config_path)
