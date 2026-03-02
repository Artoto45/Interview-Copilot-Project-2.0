"""
Smart Teleprompter — PyQt5 Overlay
=====================================
Frameless, always-on-top, semi-transparent window that displays
interview responses streaming token-by-token.

Features:
    - Adjustable opacity (70–85% for camera visibility)
    - WPM speed control (80–150 WPM, default 130)
    - Auto-scroll following new text
    - Visual parsing of [PAUSE] and **emphasis** markers
    - Font size adjustable (default 28px)
    - Keyboard shortcuts for quick control
    - Draggable/resizable transparent overlay

Keyboard shortcuts:
    Ctrl+↑ / Ctrl+↓  — Increase / decrease font size
    Ctrl+← / Ctrl+→  — Slower / faster WPM
    Ctrl+O            — Cycle opacity (70% → 80% → 90% → 70%)
    Ctrl+C / Escape    — Clear text and reset
    Ctrl+Q             — Quit teleprompter
"""

import logging
import sys
from typing import Optional

from PyQt5.QtWidgets import (
    QApplication,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QPushButton,
)
from PyQt5.QtCore import (
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
    QPoint,
)
from PyQt5.QtGui import QFont, QKeySequence

from src.teleprompter.progress_tracker import estimate_char_progress

logger = logging.getLogger("teleprompter.display")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_WPM = 130
DEFAULT_OPACITY = 0.80
DEFAULT_FONT_SIZE = 28
MIN_FONT_SIZE = 16
MAX_FONT_SIZE = 48
OPACITY_LEVELS = [0.70, 0.80, 0.90]


class SmartTeleprompter(QWidget):
    """
    Smart Teleprompter overlay window.

    Receives streaming text tokens and displays them with
    auto-scroll, emphasis highlighting, and pause markers.

    Signals:
        text_received(str): Emitted when a token is appended.
        response_cleared(): Emitted when the display is cleared.
    """

    text_received = pyqtSignal(str)
    clear_requested = pyqtSignal()
    candidate_progress_received = pyqtSignal(str)
    response_cleared = pyqtSignal()

    def __init__(
        self,
        wpm: int = DEFAULT_WPM,
        opacity: float = DEFAULT_OPACITY,
        font_size: int = DEFAULT_FONT_SIZE,
    ):
        super().__init__()

        self.wpm = wpm
        self.opacity_level = opacity
        self.current_font_size = font_size
        self._opacity_index = OPACITY_LEVELS.index(
            min(OPACITY_LEVELS, key=lambda x: abs(x - opacity))
        )
        self._current_text = ""
        self._candidate_spoken_buffer = ""
        self._read_char_index = 0
        self._drag_position: Optional[QPoint] = None
        self._waiting = True  # True while showing the waiting message

        self._setup_window()
        self._setup_ui()
        self._setup_shortcuts()

        # Connect signal for thread-safe text updates
        self.text_received.connect(self._on_text_received)
        self.clear_requested.connect(self._on_clear_requested)
        self.candidate_progress_received.connect(
            self._on_candidate_progress_received
        )

        # Show initial waiting message
        self._show_waiting_message()

    # ------------------------------------------------------------------
    # Window Setup
    # ------------------------------------------------------------------
    def _setup_window(self):
        """Configure window flags for overlay behavior."""
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool  # Don't show in taskbar
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle("Interview Copilot — Teleprompter")
        self.setMinimumSize(500, 200)
        self.resize(700, 300)

        # Position at bottom-center of screen
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - self.width()) // 2
            y = geo.height() - self.height() - 50
            self.move(x, y)

        self.setWindowOpacity(self.opacity_level)

    def _setup_ui(self):
        """Build the teleprompter UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main container with styled background
        self.container = QWidget()
        self.container.setStyleSheet(
            f"""
            QWidget {{
                background: rgba(15, 15, 25, {int(self.opacity_level * 255)});
                border-radius: 12px;
                border: 1px solid rgba(100, 100, 255, 0.3);
            }}
            """
        )
        container_layout = QVBoxLayout(self.container)
        container_layout.setContentsMargins(20, 15, 20, 15)

        # Status bar (top)
        status_bar = QHBoxLayout()
        self.status_label = QLabel("● READY")
        self.status_label.setStyleSheet(
            "color: rgba(100, 255, 150, 0.9); "
            "font-size: 11px; "
            "font-weight: bold; "
            "background: transparent; "
            "border: none;"
        )
        self.wpm_label = QLabel(f"WPM: {self.wpm}")
        self.wpm_label.setStyleSheet(
            "color: rgba(180, 180, 220, 0.8); "
            "font-size: 11px; "
            "background: transparent; "
            "border: none;"
        )
        status_bar.addWidget(self.status_label)
        status_bar.addStretch()
        status_bar.addWidget(self.wpm_label)
        container_layout.addLayout(status_bar)

        # Scroll area for text
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff
        )
        self.scroll_area.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )

        # Text label
        self.text_label = QLabel("")
        self.text_label.setWordWrap(True)
        self.text_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.text_label.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(255, 255, 255, 0.95);
                font-size: {self.current_font_size}px;
                font-family: 'Segoe UI', 'Inter', 'Roboto', sans-serif;
                line-height: 1.5;
                padding: 8px;
                background: transparent;
                border: none;
            }}
            """
        )
        self.text_label.setTextFormat(Qt.RichText)

        self.scroll_area.setWidget(self.text_label)
        container_layout.addWidget(self.scroll_area)

        layout.addWidget(self.container)

    def _setup_shortcuts(self):
        """Configure keyboard shortcuts."""
        # Handled in keyPressEvent for simplicity
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def append_text(self, token: str):
        """
        Thread-safe method to append a streaming token.
        Can be called from any thread — uses Qt signals internally.
        """
        self.text_received.emit(token)

    def clear_text(self):
        """Thread-safe clear request (can be called from any thread)."""
        self.clear_requested.emit()

    def update_candidate_progress(self, spoken_text: str):
        """Thread-safe progress update (can be called from any thread)."""
        self.candidate_progress_received.emit(spoken_text)

    @pyqtSlot()
    def _on_clear_requested(self):
        """Clear display in the Qt GUI thread."""
        self._current_text = ""
        self._candidate_spoken_buffer = ""
        self._read_char_index = 0
        self._show_waiting_message()
        self.response_cleared.emit()

    @pyqtSlot(str)
    def _on_candidate_progress_received(self, spoken_text: str):
        """Advance teleprompter according to what candidate has spoken."""
        if not spoken_text.strip() or self._waiting:
            return

        self._candidate_spoken_buffer = spoken_text
        progress = estimate_char_progress(
            script_text=self._current_text,
            spoken_text=self._candidate_spoken_buffer,
        )

        # Monotonic cursor: never move backwards on noisy transcript updates.
        self._read_char_index = max(self._read_char_index, progress)
        self._render_text()
        self._scroll_to_progress()

    def _show_waiting_message(self):
        """Show an initial waiting/listening message on startup."""
        self.status_label.setText("● LISTENING")
        self.status_label.setStyleSheet(
            "color: rgba(100, 180, 255, 0.9); "
            "font-size: 11px; font-weight: bold; "
            "background: transparent; border: none;"
        )
        waiting_html = (
            '<div style="text-align: center; padding: 30px 10px;">'
            '<span style="font-size: 36px;">🎧</span><br><br>'
            '<span style="color: rgba(150, 200, 255, 0.9); '
            'font-size: 22px; font-weight: bold;">'
            'Escuchando y esperando interacción…</span><br><br>'
            '<span style="color: rgba(180, 180, 220, 0.6); '
            'font-size: 14px;">'
            'El copiloto se activará cuando detecte una pregunta'
            '</span></div>'
        )
        self.text_label.setText(waiting_html)
        self._waiting = True

    def set_wpm(self, wpm: int):
        """Adjust words-per-minute reading speed."""
        self.wpm = max(60, min(200, wpm))
        self.wpm_label.setText(f"WPM: {self.wpm}")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------
    @pyqtSlot(str)
    def _on_text_received(self, token: str):
        """Process a received text token."""
        # Clear the waiting message on first real token
        if self._waiting:
            self._current_text = ""
            self._waiting = False

        self.status_label.setText("● SPEAKING")
        self.status_label.setStyleSheet(
            "color: rgba(255, 200, 50, 0.9); "
            "font-size: 11px; font-weight: bold; "
            "background: transparent; border: none;"
        )

        self._current_text += token
        self._render_text()

        # If we don't have live speaker alignment yet, default to bottom.
        if self._read_char_index <= 0:
            QTimer.singleShot(10, self._scroll_to_bottom)

    def _render_text(self):
        """Render formatted text with read/unread visual guidance."""
        read_chunk = self._current_text[: self._read_char_index]
        unread_chunk = self._current_text[self._read_char_index :]

        read_html = self._format_display_text(read_chunk)
        unread_html = self._format_display_text(unread_chunk)

        if self._read_char_index > 0:
            self.status_label.setText("● FOLLOW")
            self.status_label.setStyleSheet(
                "color: rgba(120, 255, 180, 0.95); "
                "font-size: 11px; font-weight: bold; "
                "background: transparent; border: none;"
            )

        self.text_label.setText(
            '<span style="color: rgba(140, 220, 160, 0.55);">'
            f"{read_html}"
            "</span>"
            '<span style="color: rgba(255, 255, 255, 0.98);">'
            f"{unread_html}"
            "</span>"
        )

    def _scroll_to_progress(self):
        """Scroll to keep current reading point in the middle of the window."""
        scrollbar = self.scroll_area.verticalScrollBar()
        if scrollbar.maximum() <= 0 or not self._current_text:
            return

        ratio = self._read_char_index / max(1, len(self._current_text))
        target = int(scrollbar.maximum() * min(1.0, max(0.0, ratio)))
        target = max(0, target - int(self.scroll_area.height() * 0.35))
        scrollbar.setValue(target)

    def _scroll_to_bottom(self):
        """Scroll to the latest text."""
        scrollbar = self.scroll_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    # ------------------------------------------------------------------
    # Text Formatting
    # ------------------------------------------------------------------
    @staticmethod
    def _format_display_text(text: str) -> str:
        """
        Format raw text for rich display:
            - [PAUSE] → visual breathing indicator
            - **bold** → emphasized words
            - [EMPHASIZE] → highlighted
        """
        import re

        # Replace [PAUSE] with visual breathing indicator
        text = text.replace(
            "[PAUSE]",
            '<span style="color: rgba(100, 200, 255, 0.7); '
            'font-size: 14px;"> ▸▸ breathe ◂◂ </span><br>'
        )

        # Replace **bold** with emphasized styling
        text = re.sub(
            r"\*\*(.+?)\*\*",
            r'<span style="color: rgba(255, 220, 100, 1.0); '
            r'font-weight: bold;">\1</span>',
            text,
        )

        # Replace [EMPHASIZE] markers
        text = text.replace(
            "[EMPHASIZE]",
            '<span style="color: rgba(255, 150, 100, 0.8); '
            'font-size: 12px;">⬆ EMPHASIZE</span>'
        )

        # Convert newlines to <br>
        text = text.replace("\n", "<br>")

        return text

    # ------------------------------------------------------------------
    # Mouse Events (Draggable Window)
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_position = (
                event.globalPos() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_position:
            self.move(event.globalPos() - self._drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_position = None

    # ------------------------------------------------------------------
    # Keyboard Events
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):
        modifiers = event.modifiers()
        key = event.key()

        if modifiers == Qt.ControlModifier:
            if key == Qt.Key_Up:
                # Increase font size
                self.current_font_size = min(
                    self.current_font_size + 2, MAX_FONT_SIZE
                )
                self._update_font_size()
            elif key == Qt.Key_Down:
                # Decrease font size
                self.current_font_size = max(
                    self.current_font_size - 2, MIN_FONT_SIZE
                )
                self._update_font_size()
            elif key == Qt.Key_Right:
                # Faster WPM
                self.set_wpm(self.wpm + 10)
            elif key == Qt.Key_Left:
                # Slower WPM
                self.set_wpm(self.wpm - 10)
            elif key == Qt.Key_O:
                # Cycle opacity
                self._opacity_index = (
                    (self._opacity_index + 1) % len(OPACITY_LEVELS)
                )
                self.opacity_level = OPACITY_LEVELS[self._opacity_index]
                self.setWindowOpacity(self.opacity_level)
            elif key == Qt.Key_Q:
                self.close()

        elif key in (Qt.Key_Escape, Qt.Key_C):
            self.clear_text()

    def _update_font_size(self):
        """Update the text label font size."""
        self.text_label.setStyleSheet(
            f"""
            QLabel {{
                color: rgba(255, 255, 255, 0.95);
                font-size: {self.current_font_size}px;
                font-family: 'Segoe UI', 'Inter', 'Roboto', sans-serif;
                line-height: 1.5;
                padding: 8px;
                background: transparent;
                border: none;
            }}
            """
        )


# ---------------------------------------------------------------------------
# Standalone Launch
# ---------------------------------------------------------------------------
def launch_teleprompter(
    wpm: int = DEFAULT_WPM,
    opacity: float = DEFAULT_OPACITY,
    font_size: int = DEFAULT_FONT_SIZE,
) -> tuple[QApplication, SmartTeleprompter]:
    """
    Launch the teleprompter as a standalone window.

    Returns (app, teleprompter) tuple for external control.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    tp = SmartTeleprompter(wpm=wpm, opacity=opacity, font_size=font_size)
    tp.show()
    return app, tp


if __name__ == "__main__":
    app, teleprompter = launch_teleprompter()

    # Demo: simulate streaming tokens
    demo_tokens = [
        "So, ", "basically, ", "I've ", "been ", "working ",
        "in ", "**software engineering** ", "for ", "about ",
        "five ", "years ", "now. ",
        "[PAUSE] ",
        "What ", "I ", "really ", "enjoy ", "is ",
        "building ", "**scalable** ", "systems ", "that ",
        "make ", "a ", "real ", "difference. ",
    ]

    def feed_token():
        if demo_tokens:
            token = demo_tokens.pop(0)
            teleprompter.append_text(token)

    timer = QTimer()
    timer.timeout.connect(feed_token)
    timer.start(150)  # ~150ms per token

    sys.exit(app.exec_())
