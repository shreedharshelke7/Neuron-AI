"""Path and resource resolution utilities for Neuron AI.

Supports portable path resolution across both development/source execution
and PyInstaller packaged standalone desktop distribution.
"""

from __future__ import annotations

import os
import sys


def get_app_root() -> str:
    """Return the absolute path to the Neuron AI application root directory.

    In PyInstaller packaged mode, returns sys._MEIPASS.
    In source execution mode, returns the repository root directory.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return getattr(sys, "_MEIPASS")

    # When running from source, calculate relative to this file:
    # app/utils/paths.py -> app/utils -> app -> root
    current_dir = os.path.dirname(os.path.abspath(__file__))
    app_dir = os.path.dirname(current_dir)
    root_dir = os.path.dirname(app_dir)
    return root_dir


def get_resource_path(relative_path: str) -> str:
    """Return the absolute path to a resource relative to the app root."""
    root = get_app_root()
    return os.path.normpath(os.path.join(root, relative_path))


def ensure_dir(dir_path: str) -> str:
    """Ensure a directory exists and return its normalized absolute path."""
    norm = os.path.normpath(dir_path)
    os.makedirs(norm, exist_ok=True)
    return norm
