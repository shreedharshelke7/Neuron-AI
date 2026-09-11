"""Activation and trigger interfaces and managers."""

from app.trigger.activation import ActivationTrigger, StubActivationTrigger
from app.trigger.global_hotkey import (
    GlobalHotkeyBackend,
    StubGlobalHotkey,
    WindowsGlobalHotkey,
)
from app.trigger.manager import ActivationManager

__all__ = [
    "ActivationManager",
    "ActivationTrigger",
    "GlobalHotkeyBackend",
    "StubActivationTrigger",
    "StubGlobalHotkey",
    "WindowsGlobalHotkey",
]
