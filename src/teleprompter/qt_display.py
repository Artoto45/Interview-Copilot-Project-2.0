"""
Smart Teleprompter — PyQt5 Overlay
=====================================
Frameless, always-on-top, semi-transparent window that displays
interview responses streaming token-by-token.

Features:
    - Adaptive Auto-scroll based on candidate voice tracking
    - Adjustable background opacity (70–85% for camera visibility)
    - Visual parsing of [PAUSE] and **emphasis** markers
    - Font size adjustable (default 28px)
    - Keyboard shortcuts for quick control
    - Draggable/resizable transparent overlay

Keyboard shortcuts:
    Ctrl+↑ / Ctrl+↓  — Increase / decrease font size
    Ctrl+O            — Cycle background opacity
    Ctrl+C / Escape    — Clear text and reset
    Ctrl+Q             — Quit teleprompter
"""

import logging
import sys
import time
from typing import Optional

from PyQt5.QtWidgets import (
    QApplication,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QLabel,
    QGraphicsDropShadowEffect,
)
from PyQt5.QtCore import (
    Qt,
    QTimer,
    pyqtSignal,
    pyqtSlot,
    QPoint,
    QPropertyAnimation,
    QEasingCurve,
)
from PyQt5.QtGui import QFont, QKeySequence, QColor, QTextCursor, QTextCharFormat, QBrush

from src.teleprompter.progress_tracker import estimate_char_progress

logger = logging.getLogger("teleprompter.display")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
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
    candidate_progress_finalize_received = pyqtSignal(str)
    response_cleared = pyqtSignal()

    def __init__(
        self,
        opacity: float = DEFAULT_OPACITY,
        font_size: int = DEFAULT_FONT_SIZE,
    ):
        super().__init__()

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
        
        self._scroll_animation: Optional[QPropertyAnimation] = None
        self._smoothed_chars_per_second = 11.0
        self._last_progress_ts = 0.0
        self._last_scroll_ts = 0.0
        self._stability_hold_until = 0.0
        self._pending_visual_progress = 0

        self._setup_window()
        self._setup_ui()
        self._setup_shortcuts()

        # Connect signal for thread-safe text updates
        self.text_received.connect(self._on_text_received)
        self.clear_requested.connect(self._on_clear_requested)
        self.candidate_progress_received.connect(
            self._on_candidate_progress_received
        )
        self.candidate_progress_finalize_received.connect(
            self._on_candidate_progress_finalize_received
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

    def _update_opacity(self):
        """Update the background opacity of the main container."""
        self.container.setStyleSheet(
            f"""
            QWidget {{
                background: rgba(15, 15, 25, {int(self.opacity_level * 255)});
                border-radius: 12px;
                border: 1px solid rgba(100, 100, 255, 0.3);
            }}
            """
        )

    def _setup_ui(self):
        """Build the teleprompter UI."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Main container with styled background
        self.container = QWidget()
        self._update_opacity()

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
        self.sync_mode_label = QLabel("🎤 VOICE SYNC: ACTIVE")
        self.sync_mode_label.setStyleSheet(
            "color: rgba(180, 220, 255, 0.85); "
            "font-size: 11px; "
            "font-weight: bold; "
            "background: transparent; "
            "border: none;"
        )
        status_bar.addWidget(self.status_label)
        status_bar.addStretch()
        status_bar.addWidget(self.sync_mode_label)
        container_layout.addLayout(status_bar)

        # Text Editor (replaces QLabel + QScrollArea)
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setStyleSheet(
            f"""
            QTextEdit {{
                color: rgba(255, 255, 255, 0.95);
                font-size: {self.current_font_size}px;
                font-family: 'Segoe UI', 'Inter', 'Roboto', sans-serif;
                background: transparent;
                border: none;
            }}
            """
        )

        # Add subtle shadow for maximum contrast
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(8)
        shadow.setColor(QColor(0, 0, 0, 200))
        shadow.setOffset(2, 2)
        self.text_edit.setGraphicsEffect(shadow)

        container_layout.addWidget(self.text_edit)

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

    def update_candidate_progress(
        self,
        spoken_text: str,
        final_pass: bool = False,
    ):
        """Thread-safe progress update (can be called from any thread)."""
        if final_pass:
            self.candidate_progress_finalize_received.emit(spoken_text)
        else:
            self.candidate_progress_received.emit(spoken_text)

    @pyqtSlot()
    def _on_clear_requested(self):
        """Clear display in the Qt GUI thread."""
        self._current_text = ""
        self._candidate_spoken_buffer = ""
        self._read_char_index = 0
        self._pending_visual_progress = 0
        self._stability_hold_until = 0.0
        self._last_progress_ts = 0.0
        self._last_scroll_ts = 0.0
        self._smoothed_chars_per_second = 11.0
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
            current_progress=self._read_char_index
        )
        self._apply_progress_update(progress=progress, final_pass=False)

    @pyqtSlot(str)
    def _on_candidate_progress_finalize_received(self, spoken_text: str):
        """Final pass on speech stop to recover difficult tail alignments."""
        if not spoken_text.strip() or self._waiting:
            return

        self._candidate_spoken_buffer = spoken_text
        progress = estimate_char_progress(
            script_text=self._current_text,
            spoken_text=self._candidate_spoken_buffer,
            current_progress=self._read_char_index,
            final_pass=True,
        )
        self._apply_progress_update(progress=progress, final_pass=True)

    def _apply_progress_update(self, progress: int, final_pass: bool) -> None:
        """
        Apply a monotonic progress update with anti-jitter visual hold and
        speaking-rate tracking for adaptive focus windows.
        """
        new_progress = max(self._read_char_index, int(progress))
        step = new_progress - self._read_char_index
        if step <= 0:
            if final_pass and self._pending_visual_progress > self._read_char_index:
                self._read_char_index = self._pending_visual_progress
                self._pending_visual_progress = 0
                self._render_text()
                self._scroll_to_progress()
            return

        now = time.monotonic()
        if self._last_progress_ts > 0:
            dt = max(0.001, now - self._last_progress_ts)
            instant_cps = min(120.0, step / dt)
            # EWMA smoothing to avoid spikes from noisy ASR steps.
            self._smoothed_chars_per_second = (
                (self._smoothed_chars_per_second * 0.82)
                + (instant_cps * 0.18)
            )
        self._last_progress_ts = now
        self._read_char_index = new_progress

        if final_pass:
            self._pending_visual_progress = 0
            self._stability_hold_until = 0.0
            self._render_text()
            self._scroll_to_progress()
            return

        # Stability hold: if ASR sends tiny frequent fluctuations, avoid visual jitter.
        in_rapid_window = (now - self._last_scroll_ts) < 0.16
        tiny_step = step < 6
        if tiny_step and in_rapid_window:
            self._stability_hold_until = max(self._stability_hold_until, now + 0.22)
            self._pending_visual_progress = max(self._pending_visual_progress, new_progress)
            return

        if now < self._stability_hold_until and step < 10:
            self._pending_visual_progress = max(self._pending_visual_progress, new_progress)
            return

        if self._pending_visual_progress > self._read_char_index:
            self._read_char_index = self._pending_visual_progress
        self._pending_visual_progress = 0

        self._render_text()
        self._scroll_to_progress()
        self._last_scroll_ts = now

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
        self.text_edit.setHtml(waiting_html)
        self._waiting = True

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

        # If we don't have live speaker alignment yet, anchor to the top so user can start reading.
        if self._read_char_index <= 0:
            QTimer.singleShot(10, self._scroll_to_top)

    def _render_text(self):
        """Render formatted text with read/unread visual guidance using QTextCharFormat."""
        # Ensure plain text is set (preserves character indices exactly)
        # Qt normalizes line endings internally. We must normalize both sides to prevent an infinite setPlainText loop!
        editor_text = self.text_edit.toPlainText().replace('\u2029', '\n').replace('\r\n', '\n')
        script_text = self._current_text.replace('\r\n', '\n')
        
        if editor_text != script_text:
            self.text_edit.setPlainText(self._current_text)

        document = self.text_edit.document()
        cursor = QTextCursor(document)
        
        # Base format (Read text is faded 40%)
        read_fmt = QTextCharFormat()
        read_fmt.setForeground(QBrush(QColor(150, 160, 170, 100)))
        
        # Focus Window format (Active ~150 chars are bright)
        focus_fmt = QTextCharFormat()
        focus_fmt.setForeground(QBrush(QColor(255, 255, 255, 255)))
        
        # Distant Window format (Upcoming text is faded 60%)
        distant_fmt = QTextCharFormat()
        distant_fmt.setForeground(QBrush(QColor(200, 200, 210, 150)))

        # Define boundary indices
        focus_window_chars, end_grace_chars = self._compute_visibility_windows()
        anchor = min(self._read_char_index, len(self._current_text))
        focus_start = anchor
        if len(self._current_text) - anchor < end_grace_chars:
            # Near the end, keep extra context visible to avoid an abrupt
            # "only final words left" visual collapse.
            focus_start = max(0, anchor - end_grace_chars)
        distant_start = min(anchor + focus_window_chars, len(self._current_text))
        end_idx = len(self._current_text)

        # Apply Read formatting [0 to focus_start]
        if focus_start > 0:
            cursor.setPosition(0)
            cursor.setPosition(focus_start, QTextCursor.KeepAnchor)
            cursor.setCharFormat(read_fmt)

        # Apply Focus formatting [focus_start to distant_start]
        if distant_start > focus_start:
            cursor.setPosition(focus_start)
            cursor.setPosition(distant_start, QTextCursor.KeepAnchor)
            cursor.setCharFormat(focus_fmt)

        # Apply Distant formatting [distant_start to end]
        if end_idx > distant_start:
            cursor.setPosition(distant_start)
            cursor.setPosition(end_idx, QTextCursor.KeepAnchor)
            cursor.setCharFormat(distant_fmt)
            
        if self._read_char_index > 0:
            self.status_label.setText("● FOLLOW")
            self.status_label.setStyleSheet(
                "color: rgba(120, 255, 180, 0.95); "
                "font-size: 11px; font-weight: bold; "
                "background: transparent; border: none;"
            )

    def _compute_visibility_windows(self) -> tuple[int, int]:
        """
        Compute adaptive focus and end-grace windows from the visible viewport.

        This keeps enough upcoming context visible when font size or window size
        changes, and dynamically scales by speaking speed.
        """
        try:
            metrics = self.text_edit.fontMetrics()
            viewport_size = self.text_edit.viewport().size()

            line_height = max(1, metrics.lineSpacing())
            avg_char_width = max(1, metrics.averageCharWidth())
            visible_lines = max(3, int(viewport_size.height() / line_height))
            chars_per_line = max(20, int(viewport_size.width() / avg_char_width))
            visible_chars = max(120, visible_lines * chars_per_line)

            cps = max(4.0, min(40.0, float(self._smoothed_chars_per_second)))
            # ~11 chars/s approximates comfortable spoken pacing.
            pace_factor = max(0.78, min(1.8, cps / 11.0))

            focus_window_chars = max(140, int(visible_chars * 0.48 * pace_factor))
            end_grace_chars = max(
                180,
                int(visible_chars * (0.66 + (0.20 * pace_factor))),
            )
            return focus_window_chars, end_grace_chars
        except Exception:
            # Conservative fallback if metrics are temporarily unavailable.
            return 170, 180

    def _scroll_to_progress(self):
        """Smoothly scroll to keep current reading point at the top of the window."""
        try:
            scrollbar = self.text_edit.verticalScrollBar()
            if not self._current_text:
                return

            # Instantiate a logic cursor pointing exactly at the read index
            cursor = QTextCursor(self.text_edit.document())
            cursor.setPosition(min(self._read_char_index, len(self._current_text)))
            
            # Find the cursor's rectangle geometry relative to the viewport
            cursor_rect = self.text_edit.cursorRect(cursor)
            
            # Calculate absolute Y in the document
            current_scroll = scrollbar.value()
            absolute_y = current_scroll + cursor_rect.y()
            
            # Target scroll calculation (adding padding of 30px so it's not glued to the top edge)
            target = max(0, int(absolute_y) - 30)
            target = min(scrollbar.maximum(), target)
            
            logger.debug(
                "scroll max=%s rect_y=%s cur=%s abs=%s target=%s",
                scrollbar.maximum(),
                cursor_rect.y(),
                current_scroll,
                absolute_y,
                target,
            )
            
            # Animate the scrollbar
            self._animate_scroll(scrollbar, target, duration_ms=450)
            
        except Exception as e:
            logger.error(f"Error in _scroll_to_progress: {e}", exc_info=True)

    def _animate_scroll(self, scrollbar, target_value: int, duration_ms: int = 400):
        """Execute a smooth kinetic 'easing' animation on the scrollbar."""
        if self._scroll_animation and self._scroll_animation.state() == QPropertyAnimation.Running:
            self._scroll_animation.stop()
            
        self._scroll_animation = QPropertyAnimation(scrollbar, b"value")
        self._scroll_animation.setDuration(duration_ms)
        self._scroll_animation.setStartValue(scrollbar.value())
        self._scroll_animation.setEndValue(target_value)
        self._scroll_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll_animation.start()

    def _scroll_to_bottom(self):
        """Smooth scroll to the latest text."""
        scrollbar = self.text_edit.verticalScrollBar()
        self._animate_scroll(scrollbar, scrollbar.maximum(), duration_ms=300)

    def _scroll_to_top(self):
        """Smooth scroll to the beginning of the text."""
        scrollbar = self.text_edit.verticalScrollBar()
        self._animate_scroll(scrollbar, 0, duration_ms=400)

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
            elif key == Qt.Key_O:
                # Cycle opacity
                self._opacity_index = (
                    (self._opacity_index + 1) % len(OPACITY_LEVELS)
                )
                self.opacity_level = OPACITY_LEVELS[self._opacity_index]
                self._update_opacity()
            elif key == Qt.Key_Q:
                self.close()

        elif key in (Qt.Key_Escape, Qt.Key_C):
            self.clear_text()

    def _update_font_size(self):
        """Update the text editor font size."""
        self.text_edit.setStyleSheet(
            f"""
            QTextEdit {{
                color: rgba(255, 255, 255, 0.95);
                font-size: {self.current_font_size}px;
                font-family: 'Segoe UI', 'Inter', 'Roboto', sans-serif;
                background: transparent;
                border: none;
            }}
            """
        )


# ---------------------------------------------------------------------------
# Standalone Launch
# ---------------------------------------------------------------------------
def launch_teleprompter(
    opacity: float = DEFAULT_OPACITY,
    font_size: int = DEFAULT_FONT_SIZE,
) -> tuple[QApplication, SmartTeleprompter]:
    """
    Launch the teleprompter as a standalone window.

    Returns (app, teleprompter) tuple for external control.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    tp = SmartTeleprompter(opacity=opacity, font_size=font_size)
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
