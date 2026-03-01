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
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
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
            logger.info("Connected to pipeline WebSocket ✓")

            async for raw_msg in ws:
                try:
                    msg = json.loads(raw_msg)
                    self._handle_message(msg)
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON: {raw_msg[:100]}")

    # ------------------------------------------------------------------
    # Message Handling
    # ------------------------------------------------------------------
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
            if self.teleprompter:
                self.teleprompter.clear_text()

        elif msg_type == "transcript":
            speaker = msg.get("speaker", "unknown")
            text = msg.get("text", "")
            logger.info(f"Transcript [{speaker}]: {text}")

        elif msg_type == "error":
            error_msg = msg.get("message", "Unknown error")
            logger.error(f"Pipeline error: {error_msg}")
            if self.teleprompter:
                self.teleprompter.append_text(
                    f"\n⚠ Error: {error_msg}\n"
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
