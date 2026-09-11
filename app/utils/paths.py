"""Path and resource resolution utilities for Neuron AI.

Supports portable path resolution across both development/source execution
and PyInstaller packaged standalone desktop distribution.
Guarantees:
- Runtime resource loading does not depend on current working directory.
- Single reusable abstraction for bundled models, assets, and user data.
"""

from __future__ import annotations

import os
import sys
from typing import Optional


def is_packaged() -> bool:
    """Return True if running within a PyInstaller frozen application bundle."""
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def get_app_root() -> str:
    """Return the absolute path to the Neuron AI application root directory.

    In PyInstaller packaged mode, returns sys._MEIPASS.
    In source execution mode, returns the repository root directory.
    """
    if is_packaged():
        return getattr(sys, "_MEIPASS")

    # When running from source, calculate relative to this file:
    # app/utils/paths.py -> app/utils -> app -> root
    current_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(current_dir)
    root_dir = os.path.dirname(app_dir)
    return root_dir


def get_resource_path(relative_path: str) -> str:
    """Return the absolute path to a resource relative to the app root.

    Does not depend on the current working directory.
    """
    root = get_app_root()
    return os.path.normpath(os.path.join(root, relative_path))


def ensure_dir(dir_path: str) -> str:
    """Ensure a directory exists and return its normalized absolute path."""
    norm = os.path.normpath(dir_path)
    os.makedirs(norm, exist_ok=True)
    return norm


def get_user_data_dir() -> str:
    """Return the per-user data directory for Neuron AI (%LOCALAPPDATA%/NeuronAI)."""
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata and os.path.isdir(local_appdata):
        base_dir = os.path.join(local_appdata, "NeuronAI")
    else:
        # Cross-platform fallback for headless testing
        base_dir = os.path.join(os.path.expanduser("~"), ".neuron_ai")
    return ensure_dir(base_dir)


def get_user_config_path() -> str:
    """Return the absolute path to the user config file (%LOCALAPPDATA%/NeuronAI/config.json)."""
    return os.path.join(get_user_data_dir(), "config.json")


def get_app_icon_path() -> Optional[str]:
    """Return the absolute path to the bundled brand icon if present, else None."""
    icon_path = get_resource_path(os.path.join("assets", "neuron.ico"))
    if os.path.exists(icon_path) and os.path.isfile(icon_path):
        return icon_path
    return None


def resolve_whisper_model_path(model_spec: str = "base.en") -> str:
    """Resolve the faster-whisper model path for bundled or source execution.

    Priority:
    1. If the bundled model directory exists (e.g. models/faster-whisper-base.en),
       return its absolute path.
    2. If running packaged, return the expected bundled model path so STT adapter
       can verify presence and raise a controlled error if missing.
    3. If running from source, return model_spec (default: 'base.en') for standard
       faster-whisper downloading or Hugging Face cache reuse.
    """
    bundled_dir = get_resource_path(os.path.join("models", "faster-whisper-base.en"))
    if os.path.exists(bundled_dir) and os.path.isdir(bundled_dir):
        return bundled_dir

    if is_packaged():
        return bundled_dir

    return model_spec
