"""Desktop shell application lifecycle and entry point runner."""

from __future__ import annotations

import logging
import sys
from typing import List, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app.capture.qt_service import QtScreenCaptureService
from app.desktop.indicator import CaptureIndicatorWidget
from app.desktop.window import DesktopShellWindow
from app.overlay.qt_overlay import QtOverlayHost
from app.session.controller import SessionController
from app.trigger.manager import ActivationManager

logger = logging.getLogger(__name__)


class HotkeySignalBridge(QObject):
    """Qt signal bridge ensuring cross-thread hotkey events execute on GUI thread."""

    activated = Signal()


class NeuronDesktopApp:
    """Manages the lifecycle of the Neuron desktop shell application."""

    def __init__(
        self,
        session_controller: Optional[SessionController] = None,
        activation_manager: Optional[ActivationManager] = None,
        argv: Optional[List[str]] = None,
    ) -> None:
        self._argv = argv if argv is not None else sys.argv
        self._app: Optional[QApplication] = None
        self._window: Optional[DesktopShellWindow] = None

        # Ensure single QApplication exists prior to widget creation
        self.initialize_qapplication()

        # Signal bridge for thread-safe cross-thread activation
        self._bridge = HotkeySignalBridge()

        # Instantiate concrete desktop services if not injected
        if session_controller is None:
            capture_service = QtScreenCaptureService()
            overlay_host = QtOverlayHost()
            capture_indicator = CaptureIndicatorWidget()
            self._session_controller = SessionController(
                capture_service=capture_service,
                overlay_host=overlay_host,
                capture_indicator=capture_indicator,
                auto_capture=True,
            )
        else:
            self._session_controller = session_controller

        self._bridge.activated.connect(self._session_controller.request_activation)

        self._activation_manager = activation_manager or ActivationManager(
            on_activate=self._bridge.activated.emit
        )

    @property
    def session_controller(self) -> SessionController:
        """Access the session controller."""
        return self._session_controller

    @property
    def activation_manager(self) -> ActivationManager:
        """Access the activation manager."""
        return self._activation_manager

    def initialize_qapplication(self) -> QApplication:
        """Create or return the single QApplication instance."""
        app = QApplication.instance()
        if app is None:
            app = QApplication(self._argv)
        self._app = app
        return app

    def shutdown(self) -> None:
        """Cleanly unregister global hotkeys, dismiss overlays, and release resources."""
        if self._session_controller is not None:
            self._session_controller.dismiss()

        if self._activation_manager is not None:
            self._activation_manager.stop()

    def run(self) -> int:
        """Launch the desktop shell application and enter the event loop."""
        app = self.initialize_qapplication()
        app.setQuitOnLastWindowClosed(True)
        app.aboutToQuit.connect(self.shutdown)

        # Start global hotkey listener
        self._activation_manager.start()

        self._window = DesktopShellWindow(
            session_controller=self._session_controller,
            activation_trigger=self._activation_manager,
        )
        self._window.show()

        try:
            return app.exec()
        finally:
            self.shutdown()


def run_desktop_shell(argv: Optional[List[str]] = None) -> int:
    """Convenience entry point function to launch the desktop shell."""
    app = NeuronDesktopApp(argv=argv)
    return app.run()
