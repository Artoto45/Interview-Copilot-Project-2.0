"""
WebSocket Bridge — Teleprompter ↔ Pipeline
=============================================
Connects the teleprompter display to the main pipeline via
a local WebSocket client.

Responsibilities:
    - Connect to main.py's WebSocket at ws://localhost:8000/ws/pipeline
    - Receive streaming tokens and forward to SmartTeleprompter
    - Handle response_end signals to prepare for next question
    - Reconnect automatically if connection drops

This module bridges the FastAPI backend with the PyQt5
teleprompter running in its own process.
"""

import asyncio
import json
import logging
import sys
import threading
from typing import Optional

import websockets

logger = logging.getLogger("teleprompter.bridge")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_WS_URL = "ws://127.0.0.1:8765"
RECONNECT_DELAY_S = 3.0
MAX_RECONNECT_ATTEMPTS = 10


class TeleprompterBridge:
    """
    WebSocket client that connects the teleprompter to the pipeline.

    Receives streaming tokens from the ResponseAgent (via the
    Coordinator's WebSocket) and forwards them to the
    SmartTeleprompter widget.

    Usage::

        from src.teleprompter.qt_display import SmartTeleprompter

        teleprompter = SmartTeleprompter()
        bridge = TeleprompterBridge(teleprompter)
        bridge.start()  # runs in background thread
    """

    def __init__(
        self,
        teleprompter=None,
        ws_url: str = DEFAULT_WS_URL,
    ):
        self.teleprompter = teleprompter
        self.ws_url = ws_url
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ws = None
        self._candidate_committed_text = ""
        self._candidate_live_text = ""
        self._last_saldo_snapshot = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def start(self):
        """Start the bridge in a background thread."""
        if self._running:
            logger.warning("Bridge already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="teleprompter-bridge",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Bridge started → {self.ws_url}")

    def stop(self):
        """Stop the bridge."""
        self._running = False
        if self._loop and self._loop.is_running() and self._ws is not None:
            try:
                future = asyncio.run_coroutine_threadsafe(
                    self._ws.close(),
                    self._loop,
                )
                future.result(timeout=2.0)
            except Exception as e:
                logger.debug(f"WebSocket close during stop failed: {e}")
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Bridge stopped ✓")

    # ------------------------------------------------------------------
    # Background Loop
    # ------------------------------------------------------------------
    def _run_loop(self):
        """Run the asyncio event loop in the background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._connect_loop())
        except Exception as e:
            logger.error(f"Bridge loop error: {e}")
        finally:
            self._loop.close()

    async def _connect_loop(self):
        """Connect to WebSocket with auto-reconnect."""
        attempts = 0

        while self._running and attempts < MAX_RECONNECT_ATTEMPTS:
            try:
                await self._listen()
                attempts = 0  # reset on successful connection
            except websockets.exceptions.ConnectionClosed:
                attempts += 1
                logger.warning(
                    f"Connection closed. Reconnecting "
                    f"({attempts}/{MAX_RECONNECT_ATTEMPTS})…"
                )
                await asyncio.sleep(RECONNECT_DELAY_S)
            except ConnectionRefusedError:
                attempts += 1
                logger.warning(
                    f"Connection refused (server not running?). "
                    f"Retrying ({attempts}/{MAX_RECONNECT_ATTEMPTS})…"
                )
                await asyncio.sleep(RECONNECT_DELAY_S)
            except asyncio.CancelledError:
                break
            except Exception as e:
                attempts += 1
                logger.error(
                    f"Bridge error: {e}. "
                    f"Retrying ({attempts}/{MAX_RECONNECT_ATTEMPTS})…"
                )
                await asyncio.sleep(RECONNECT_DELAY_S)

        if attempts >= MAX_RECONNECT_ATTEMPTS:
            logger.error("Max reconnect attempts reached — bridge disabled")

    async def _listen(self):
        """Connect and listen for messages."""
        async with websockets.connect(self.ws_url) as ws:
            self._ws = ws
            logger.info("Connected to pipeline WebSocket ✓")
            try:
                async for raw_msg in ws:
                    try:
                        msg = json.loads(raw_msg)
                        self._handle_message(msg)
                    except json.JSONDecodeError:
                        logger.warning(f"Invalid JSON: {raw_msg[:100]}")
            finally:
                self._ws = None

    # ------------------------------------------------------------------
    # Message Handling
    # ------------------------------------------------------------------
    def _update_candidate_progress(self, text: str, final_pass: bool = False):
        """Call teleprompter progress update with backward-compatible signature."""
        if not self.teleprompter or not (text or "").strip():
            return
        try:
            self.teleprompter.update_candidate_progress(
                text,
                final_pass=final_pass,
            )
        except TypeError:
            self.teleprompter.update_candidate_progress(text)

    def _handle_message(self, msg: dict):
        """Process a message from the pipeline."""
        msg_type = msg.get("type", "")

        if msg_type == "token":
            token = msg.get("data", "")
            if token and self.teleprompter:
                self.teleprompter.append_text(token)

        elif msg_type == "response_end":
            logger.info("Response complete — ready for next question")
            # Don't clear immediately — let user read the answer.
            # It will auto-clear when the next response starts.

        elif msg_type == "new_question":
            # Clear previous response when a new question arrives
            self._candidate_committed_text = ""
            self._candidate_live_text = ""
            if self.teleprompter:
                self.teleprompter.clear_text()

        elif msg_type == "transcript":
            speaker = msg.get("speaker", "unknown")
            text = msg.get("text", "")
            logger.info(f"Transcript [{speaker}]: {text}")
            if self.teleprompter and speaker in {"user", "candidate"}:
                if self._candidate_committed_text:
                    self._candidate_committed_text += " " + text
                else:
                    self._candidate_committed_text = text
                self._candidate_live_text = ""
                self._update_candidate_progress(
                    self._candidate_committed_text,
                    final_pass=False,
                )

        elif msg_type == "subtitle_delta":
            speaker = msg.get("speaker", "unknown")
            delta = (msg.get("text", "") or "").strip()
            if self.teleprompter and speaker in {"user", "candidate"} and delta:
                # Keep only the latest partial transcript. Deltas are full
                # partial hypotheses, not append-only token streams.
                self._candidate_live_text = delta
                current_full = self._candidate_committed_text
                if current_full:
                    current_full += " " + self._candidate_live_text
                else:
                    current_full = self._candidate_live_text

                self._update_candidate_progress(
                    current_full,
                    final_pass=False,
                )

        elif msg_type == "speech_event":
            speaker = msg.get("speaker", "unknown")
            event = msg.get("event", "")
            if (
                self.teleprompter
                and speaker in {"user", "candidate"}
                and event == "stopped"
            ):
                current_full = self._candidate_committed_text
                if self._candidate_live_text:
                    if current_full:
                        current_full += " " + self._candidate_live_text
                    else:
                        current_full = self._candidate_live_text
                self._update_candidate_progress(
                    current_full,
                    final_pass=True,
                )

        elif msg_type == "error":
            error_msg = msg.get("message", "Unknown error")
            logger.error(f"Pipeline error: {error_msg}")
            if self.teleprompter:
                self.teleprompter.append_text(
                    f"\n⚠ Error: {error_msg}\n"
                )

        elif msg_type == "saldo_update":
            data = msg.get("data", {})
            self._last_saldo_snapshot = data
            fuel = data.get("fuel_gauge", {})
            providers = data.get("providers", {})
            openai = providers.get("openai", {})
            deepgram = providers.get("deepgram", {})
            anthropic = providers.get("anthropic", {})
            logger.info(
                "Saldo update | "
                f"OpenAI=${openai.get('remaining_usd', 0):.4f}, "
                f"Deepgram=${deepgram.get('remaining_usd', 0):.4f}, "
                f"Anthropic=${anthropic.get('remaining_usd', 0):.4f}, "
                f"fuel={fuel.get('human_readable_until_any_depletion')}"
            )

    @property
    def is_running(self) -> bool:
        return self._running


# ---------------------------------------------------------------------------
# Standalone: Launch teleprompter + bridge together
# ---------------------------------------------------------------------------
def launch_with_bridge(ws_url: str = DEFAULT_WS_URL):
    """
    Launch the teleprompter with automatic WebSocket bridge.
    This is the main entry point for the teleprompter display.
    """
    from src.teleprompter.qt_display import (
        launch_teleprompter,
    )

    app, teleprompter = launch_teleprompter()

    bridge = TeleprompterBridge(
        teleprompter=teleprompter,
        ws_url=ws_url,
    )
    bridge.start()

    exit_code = app.exec_()
    bridge.stop()
    sys.exit(exit_code)


if __name__ == "__main__":
    launch_with_bridge()
