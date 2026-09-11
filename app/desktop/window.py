"""Desktop shell window for Neuron AI Block 1 Step 2 & Step 3."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.session.controller import SessionController
from app.session.state import SessionState
from app.trigger.activation import ActivationTrigger


class DesktopShellWindow(QMainWindow):
    """Temporary development shell window for Neuron AI.

    Visibly confirms that Neuron is running and displays the current session
    state (IDLE, ACTIVATED, CAPTURING, SELECTING, SELECTED). Displays
    non-sensitive region metadata when a rectangle is selected and supports
    local keyboard shortcut handling.
    """

    def __init__(
        self,
        session_controller: Optional[SessionController] = None,
        activation_trigger: Optional[ActivationTrigger] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._controller = session_controller or SessionController()
        self._trigger = activation_trigger

        self._init_ui()
        self._setup_local_shortcuts()
        self._controller.add_state_listener(self._on_state_changed)
        self._controller.add_region_listener(self._on_region_selected)
        if hasattr(self._controller, "set_desktop_window"):
            self._controller.set_desktop_window(self)

    def _init_ui(self) -> None:
        self.setWindowTitle("Neuron AI")
        self.resize(380, 260)
        self.setMinimumSize(340, 220)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Title: Neuron AI
        title_label = QLabel("Neuron AI", self)
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # Subtitle: Phase 0 — Desktop Shell
        phase_label = QLabel("Phase 0 — Desktop Shell", self)
        phase_font = QFont()
        phase_font.setPointSize(10)
        phase_label.setFont(phase_font)
        phase_label.setStyleSheet("color: #666666;")
        phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(phase_label)

        layout.addSpacing(4)

        # State label
        self.state_label = QLabel(f"State: {self._controller.state.value}", self)
        state_font = QFont()
        state_font.setPointSize(12)
        state_font.setBold(True)
        self.state_label.setFont(state_font)
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_state_style(self._controller.state)
        layout.addWidget(self.state_label)

        # Shortcut hint
        hint_label = QLabel("Shortcut: Ctrl + Shift + Space", self)
        hint_font = QFont()
        hint_font.setPointSize(9)
        hint_label.setFont(hint_font)
        hint_label.setStyleSheet("color: #888888;")
        hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint_label)

        # Region info display label (shown when a region is selected)
        self.region_info_label = QLabel("", self)
        region_font = QFont()
        region_font.setPointSize(8)
        self.region_info_label.setFont(region_font)
        self.region_info_label.setStyleSheet(
            "color: #444444; background: #f1f3f4; border-radius: 4px; padding: 4px;"
        )
        self.region_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.region_info_label.setVisible(False)
        layout.addWidget(self.region_info_label)

        # Audio info display label (shown during LISTENING / VOICE_CAPTURED / TRANSCRIBING / TRANSCRIBED / ERROR)
        self.audio_info_label = QLabel("", self)
        audio_font = QFont()
        audio_font.setPointSize(8)
        self.audio_info_label.setFont(audio_font)
        self.audio_info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.audio_info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.audio_info_label.setWordWrap(True)
        self.audio_info_label.setVisible(False)
        layout.addWidget(self.audio_info_label)

        layout.addSpacing(6)

        # Finish recording button (active during LISTENING)
        self.finish_button = QPushButton("Finish Recording (Ctrl+Shift+Space)", self)
        self.finish_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.finish_button.clicked.connect(self._on_finish_clicked)
        self.finish_button.setEnabled(False)
        layout.addWidget(self.finish_button)

        # Reset button
        self.reset_button = QPushButton("Reset to IDLE (Esc)", self)
        self.reset_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_button.clicked.connect(self._on_reset_clicked)
        self.reset_button.setEnabled(self._controller.state != SessionState.IDLE)
        layout.addWidget(self.reset_button)

    def _setup_local_shortcuts(self) -> None:
        """Register local Qt shortcuts when the window has focus."""
        # Local activation shortcut: Ctrl+Shift+Space
        self._local_activation_shortcut = QShortcut(
            QKeySequence("Ctrl+Shift+Space"), self
        )
        self._local_activation_shortcut.setContext(
            Qt.ShortcutContext.WindowShortcut
        )
        self._local_activation_shortcut.activated.connect(
            self._on_activation_shortcut
        )

        # Local reset shortcut: Escape
        self._local_reset_shortcut = QShortcut(QKeySequence("Escape"), self)
        self._local_reset_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._local_reset_shortcut.activated.connect(
            self._controller.reset_to_idle
        )

    def _on_activation_shortcut(self) -> None:
        """Handle local shortcut trigger."""
        if self._trigger is not None:
            self._trigger.request_activation()
        else:
            self._controller.request_activation()

    def _on_reset_clicked(self) -> None:
        """Handle reset button click."""
        self._controller.reset_to_idle()

    def _on_finish_clicked(self) -> None:
        """Handle finish recording button click."""
        self._controller.stop_listening()

    def _update_state_style(self, state: SessionState) -> None:
        """Update label styling based on the active state."""
        if state in (SessionState.ACTIVATED, SessionState.CAPTURING):
            self.state_label.setStyleSheet(
                "color: #ea8600; background-color: #fef7e0; "
                "padding: 4px 12px; border-radius: 4px;"
            )
        elif state == SessionState.LISTENING:
            self.state_label.setStyleSheet(
                "color: #b06000; background-color: #fef7e0; "
                "padding: 4px 12px; border-radius: 4px; font-weight: bold;"
            )
        elif state == SessionState.VOICE_CAPTURED:
            self.state_label.setStyleSheet(
                "color: #137333; background-color: #e6f4ea; "
                "padding: 4px 12px; border-radius: 4px; font-weight: bold;"
            )
        elif state == SessionState.TRANSCRIBING:
            self.state_label.setStyleSheet(
                "color: #5b21b6; background-color: #f3e8ff; "
                "padding: 4px 12px; border-radius: 4px; font-weight: bold;"
            )
        elif state == SessionState.TRANSCRIBED:
            self.state_label.setStyleSheet(
                "color: #065f46; background-color: #d1fae5; "
                "padding: 4px 12px; border-radius: 4px; font-weight: bold;"
            )
        elif state == SessionState.THINKING:
            self.state_label.setStyleSheet(
                "color: #1e40af; background-color: #dbeafe; "
                "padding: 4px 12px; border-radius: 4px; font-weight: bold;"
            )
        elif state == SessionState.RESPONDED:
            self.state_label.setStyleSheet(
                "color: #065f46; background-color: #d1fae5; "
                "padding: 4px 12px; border-radius: 4px; font-weight: bold;"
            )
        elif state in (SessionState.SELECTING, SessionState.SELECTED):
            self.state_label.setStyleSheet(
                "color: #0d904f; background-color: #e6f4ea; "
                "padding: 4px 12px; border-radius: 4px;"
            )
        elif state == SessionState.ERROR:
            self.state_label.setStyleSheet(
                "color: #d93025; background-color: #fce8e6; "
                "padding: 4px 12px; border-radius: 4px;"
            )
        else:  # IDLE
            self.state_label.setStyleSheet(
                "color: #1a73e8; background-color: #e8f0fe; "
                "padding: 4px 12px; border-radius: 4px;"
            )

    def _on_state_changed(self, state: SessionState) -> None:
        """Update the visible state label and controls when state changes."""
        self.state_label.setText(f"State: {state.value}")
        self._update_state_style(state)
        self.reset_button.setEnabled(state != SessionState.IDLE)
        self.finish_button.setEnabled(state == SessionState.LISTENING)

        if state == SessionState.LISTENING:
            self.audio_info_label.setText("Neuron is listening... Speak your question.")
            self.audio_info_label.setStyleSheet(
                "color: #b06000; background: #fef7e0; border-radius: 4px; padding: 6px;"
            )
            self.audio_info_label.setVisible(True)
        elif state == SessionState.VOICE_CAPTURED:
            res = self._controller.current_audio
            if res is not None:
                self.audio_info_label.setText(
                    f"Voice captured: {res.duration_seconds:.2f}s "
                    f"({res.sample_rate}Hz, {res.byte_count} bytes)"
                )
            else:
                self.audio_info_label.setText("Voice captured")
            self.audio_info_label.setStyleSheet(
                "color: #137333; background: #e6f4ea; border-radius: 4px; padding: 6px;"
            )
            self.audio_info_label.setVisible(True)
        elif state == SessionState.TRANSCRIBING:
            self.audio_info_label.setText("Transcribing question...")
            self.audio_info_label.setStyleSheet(
                "color: #5b21b6; background: #f3e8ff; border-radius: 4px; padding: 6px; font-weight: 500;"
            )
            self.audio_info_label.setVisible(True)
        elif state == SessionState.TRANSCRIBED:
            res = self._controller.current_transcript
            text = res.transcript if res is not None else ""
            self.audio_info_label.setText(f"Transcript:\n{text}")
            self.audio_info_label.setStyleSheet(
                "color: #065f46; background: #d1fae5; border-radius: 4px; padding: 6px; font-weight: 500;"
            )
            self.audio_info_label.setVisible(True)
        elif state == SessionState.THINKING:
            self.audio_info_label.setText("Neuron is thinking...")
            self.audio_info_label.setStyleSheet(
                "color: #1e40af; background: #dbeafe; border-radius: 4px; padding: 6px; font-weight: 500;"
            )
            self.audio_info_label.setVisible(True)
        elif state == SessionState.RESPONDED:
            tutor_res = self._controller.current_tutor_response
            if tutor_res is not None:
                display_text = f"[{tutor_res.intent.upper()}]\n{tutor_res.summary}"
                if tutor_res.overlay_actions:
                    actions_str = ", ".join(a.action_type.value for a in tutor_res.overlay_actions)
                    display_text += f"\n(Actions: {actions_str})"
            else:
                display_text = "Response ready"
            self.audio_info_label.setText(display_text)
            self.audio_info_label.setStyleSheet(
                "color: #065f46; background: #d1fae5; border-radius: 4px; padding: 6px; font-weight: 500;"
            )
            self.audio_info_label.setVisible(True)
        elif state == SessionState.ERROR:
            err_msg = self._controller.last_error_message or "Operation failed"
            self.audio_info_label.setText(f"Error: {err_msg}")
            self.audio_info_label.setStyleSheet(
                "color: #d93025; background: #fce8e6; border-radius: 4px; padding: 6px;"
            )
            self.audio_info_label.setVisible(True)
        elif state == SessionState.IDLE:
            self.region_info_label.setVisible(False)
            self.region_info_label.setText("")
            self.audio_info_label.setVisible(False)
            self.audio_info_label.setText("")

    def _on_region_selected(self, region) -> None:
        """Display non-sensitive metadata for the selected region."""
        try:
            nx, ny, nw, nh = region.to_normalized()
            self.region_info_label.setText(
                f"Region: ({region.x}, {region.y}, {region.width}×{region.height})\n"
                f"Normalized: ({nx:.3f}, {ny:.3f}, {nw:.3f}, {nh:.3f})"
            )
            self.region_info_label.setVisible(True)
        except Exception:
            pass

    def closeEvent(self, event: QCloseEvent) -> None:
        """Handle clean window close."""
        if hasattr(self._controller, "set_desktop_window"):
            self._controller.set_desktop_window(None)
        self._controller.dismiss()
        self._controller.remove_state_listener(self._on_state_changed)
        self._controller.remove_region_listener(self._on_region_selected)
        super().closeEvent(event)
