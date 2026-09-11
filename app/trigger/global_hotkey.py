"""Windows global hotkey implementation using Win32 RegisterHotKey API."""

from __future__ import annotations

import logging
import sys
import threading
from abc import ABC, abstractmethod
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class GlobalHotkeyBackend(ABC):
    """Abstract backend for global hotkey registration."""

    @abstractmethod
    def start(self) -> bool:
        """Start listening for the global hotkey."""
        ...

    @abstractmethod
    def stop(self) -> None:
        """Stop listening and release the hotkey."""
        ...

    @property
    @abstractmethod
    def is_registered(self) -> bool:
        """Whether the hotkey is currently registered with the system."""
        ...


class WindowsGlobalHotkey(GlobalHotkeyBackend):
    """Windows global hotkey listener utilizing Win32 RegisterHotKey via ctypes.

    Does not require administrator privileges or low-level keyboard hooks.
    Runs a minimal message loop on a dedicated thread and unregisters cleanly.
    """

    # Win32 Constants
    MOD_ALT = 0x0001
    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    MOD_WIN = 0x0008
    MOD_NOREPEAT = 0x4000

    VK_SPACE = 0x20

    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012

    def __init__(
        self,
        on_activate: Callable[[], None],
        modifiers: int = MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT,
        vk: int = VK_SPACE,
        hotkey_id: int = 1,
    ) -> None:
        self._on_activate = on_activate
        self._modifiers = modifiers
        self._vk = vk
        self._hotkey_id = hotkey_id

        self._thread: Optional[threading.Thread] = None
        self._thread_id: Optional[int] = None
        self._is_registered: bool = False
        self._registration_event = threading.Event()
        self._stop_event = threading.Event()
        self._error_code: Optional[int] = None

    @property
    def is_registered(self) -> bool:
        """Return whether the global hotkey is successfully registered."""
        return self._is_registered

    @property
    def error_code(self) -> Optional[int]:
        """Return the Win32 error code if registration failed."""
        return self._error_code

    def start(self) -> bool:
        """Start the background thread and register the global hotkey."""
        if sys.platform != "win32":
            logger.info("Non-Windows platform detected; WindowsGlobalHotkey disabled.")
            return False

        if self._thread and self._thread.is_alive():
            return self._is_registered

        self._registration_event.clear()
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="NeuronWindowsGlobalHotkeyThread",
            daemon=True,
        )
        self._thread.start()

        # Wait up to 2 seconds for registration to complete
        self._registration_event.wait(timeout=2.0)
        return self._is_registered

    def stop(self) -> None:
        """Unregister the global hotkey and stop the worker thread."""
        self._stop_event.set()

        if self._thread_id and sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.user32.PostThreadMessageW(
                    self._thread_id, self.WM_QUIT, 0, 0
                )
            except Exception as e:
                logger.debug("PostThreadMessageW failed during hotkey shutdown: %s", e)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        self._thread = None
        self._thread_id = None
        self._is_registered = False

    def _run(self) -> None:
        """Worker thread executing Win32 message loop."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Configure ctypes prototypes
        user32.RegisterHotKey.argtypes = [
            wintypes.HWND,
            ctypes.c_int,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.RegisterHotKey.restype = wintypes.BOOL

        user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.UnregisterHotKey.restype = wintypes.BOOL

        user32.GetMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.GetMessageW.restype = wintypes.BOOL

        user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        user32.PeekMessageW.restype = wintypes.BOOL

        self._thread_id = kernel32.GetCurrentThreadId()

        # Force message queue allocation for this thread
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        # Register hotkey
        res = user32.RegisterHotKey(
            None, self._hotkey_id, self._modifiers, self._vk
        )
        if not res:
            self._error_code = kernel32.GetLastError()
            logger.warning(
                "Failed to register global hotkey Ctrl+Shift+Space (Win32 error %d). "
                "Another application may already be using it. "
                "Local window shortcuts remain available.",
                self._error_code,
            )
            self._is_registered = False
            self._registration_event.set()
            return

        self._is_registered = True
        self._registration_event.set()
        logger.info("Global hotkey (Ctrl+Shift+Space) registered successfully.")

        try:
            while not self._stop_event.is_set():
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                # ret == 0 indicates WM_QUIT; ret == -1 indicates error
                if ret <= 0:
                    break

                if msg.message == self.WM_HOTKEY and msg.wParam == self._hotkey_id:
                    try:
                        self._on_activate()
                    except Exception as ex:
                        logger.exception("Error in activation callback: %s", ex)
        finally:
            user32.UnregisterHotKey(None, self._hotkey_id)
            self._is_registered = False
            logger.info("Global hotkey unregistered.")


class StubGlobalHotkey(GlobalHotkeyBackend):
    """Stub global hotkey backend for testing and simulated environments."""

    def __init__(
        self,
        on_activate: Optional[Callable[[], None]] = None,
        should_succeed: bool = True,
    ) -> None:
        self._on_activate = on_activate
        self._should_succeed = should_succeed
        self._is_registered: bool = False

    @property
    def is_registered(self) -> bool:
        return self._is_registered

    def start(self) -> bool:
        if self._should_succeed:
            self._is_registered = True
            return True
        self._is_registered = False
        return False

    def stop(self) -> None:
        self._is_registered = False

    def simulate_hotkey_press(self) -> None:
        """Simulate a global hotkey press."""
        if self._is_registered and self._on_activate:
            self._on_activate()
