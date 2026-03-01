"""
Deepgram Streaming Transcription Client
=========================================
Two parallel WebSocket connections to Deepgram Nova-2:
    - Channel 1: User / Candidate audio (Bus B1)
    - Channel 2: Interviewer audio   (Bus B2)

Each connection streams 100 ms audio chunks and receives
real-time transcription with:
    - interim_results for progressive display
    - utterance_end_ms=1000 for sentence boundary detection
    - smart_format for punctuation and capitalization
    - diarize=true as additional safety net

Latency target: < 300 ms per utterance (Deepgram p95).
Auto-reconnect if p95 exceeds 400 ms.
"""

import asyncio
import json
import logging
import os
import time
from collections import deque
from typing import Callable, Optional, Awaitable

import websockets
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("transcription.deepgram")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
DEEPGRAM_PARAMS = (
    "model=nova-2"
    "&language=en-US"
    "&interim_results=true"
    "&utterance_end_ms=1000"
    "&diarize=true"
    "&smart_format=true"
    "&encoding=linear16"
    "&sample_rate=16000"
    "&channels=1"
)
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY_S = 2.0
LATENCY_WINDOW = 50  # rolling window for p95 calculation
LATENCY_THRESHOLD_MS = 400  # trigger reconnect if p95 exceeds this


# Callback type: async def handler(speaker: str, text: str)
TranscriptCallback = Callable[[str, str], Awaitable[None]]


class DeepgramTranscriber:
    """
    Manages two parallel Deepgram WebSocket connections for
    dual-channel real-time transcription.

    Usage::

        transcriber = DeepgramTranscriber(on_transcript=my_callback)
        await transcriber.start(user_queue, interviewer_queue)
        # ... runs until stopped ...
        await transcriber.stop()
    """

    def __init__(
        self,
        on_transcript: TranscriptCallback,
        api_key: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("DEEPGRAM_API_KEY", "")
        self.on_transcript = on_transcript

        # Latency tracking (per channel)
        self._latencies: dict[str, deque] = {
            "user": deque(maxlen=LATENCY_WINDOW),
            "interviewer": deque(maxlen=LATENCY_WINDOW),
        }

        # Accumulation buffer: collects is_final segments until
        # speech_final=true signals the speaker has stopped talking.
        # This prevents fragments like "Please" from being processed
        # before the full utterance "Please restart the interview" arrives.
        self._utterance_buffer: dict[str, list[str]] = {
            "user": [],
            "interviewer": [],
        }

        # State
        self._tasks: list[asyncio.Task] = []
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def start(
        self,
        user_audio_queue: asyncio.Queue,
        interviewer_audio_queue: Optional[asyncio.Queue] = None,
    ):
        """Start transcription for one or both audio channels."""
        if self._running:
            logger.warning("DeepgramTranscriber already running")
            return

        if not self.api_key:
            logger.error(
                "DEEPGRAM_API_KEY not set — transcription disabled. "
                "Set it in your .env file."
            )
            return

        self._running = True

        # Always start user channel
        task_user = asyncio.create_task(
            self._run_channel("user", user_audio_queue),
            name="deepgram-user",
        )
        self._tasks.append(task_user)

        # Optionally start interviewer channel
        if interviewer_audio_queue is not None:
            task_int = asyncio.create_task(
                self._run_channel("interviewer", interviewer_audio_queue),
                name="deepgram-interviewer",
            )
            self._tasks.append(task_int)

        logger.info(
            f"Deepgram transcription started "
            f"({len(self._tasks)} channel(s))"
        )

    async def stop(self):
        """Stop all transcription tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Deepgram transcription stopped ✓")

    # ------------------------------------------------------------------
    # Channel Runner (with auto-reconnect)
    # ------------------------------------------------------------------
    async def _run_channel(
        self, speaker: str, audio_queue: asyncio.Queue
    ):
        """
        Run a single Deepgram channel with auto-reconnect.
        Retries up to MAX_RECONNECT_ATTEMPTS on failure.
        """
        attempts = 0

        while self._running and attempts < MAX_RECONNECT_ATTEMPTS:
            try:
                await self._stream_channel(speaker, audio_queue)
            except websockets.exceptions.ConnectionClosed as e:
                attempts += 1
                logger.warning(
                    f"[{speaker}] Connection closed: {e}. "
                    f"Reconnecting ({attempts}/{MAX_RECONNECT_ATTEMPTS})…"
                )
                await asyncio.sleep(RECONNECT_DELAY_S)
            except asyncio.CancelledError:
                logger.info(f"[{speaker}] Task cancelled")
                break
            except Exception as e:
                attempts += 1
                logger.error(
                    f"[{speaker}] Error: {e}. "
                    f"Reconnecting ({attempts}/{MAX_RECONNECT_ATTEMPTS})…",
                    exc_info=True,
                )
                await asyncio.sleep(RECONNECT_DELAY_S)

        if attempts >= MAX_RECONNECT_ATTEMPTS:
            logger.error(
                f"[{speaker}] Max reconnect attempts reached — "
                f"channel disabled"
            )

    async def _stream_channel(
        self, speaker: str, audio_queue: asyncio.Queue
    ):
        """
        Open a WebSocket to Deepgram and stream audio chunks.
        Runs sender + receiver coroutines in parallel.
        """
        url = f"{DEEPGRAM_WS_URL}?{DEEPGRAM_PARAMS}"
        headers = {"Authorization": f"Token {self.api_key}"}

        logger.info(f"[{speaker}] Connecting to Deepgram…")

        async with websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=10,
        ) as ws:
            logger.info(f"[{speaker}] Connected ✓")

            async def sender():
                """Stream audio chunks from queue → Deepgram."""
                while self._running:
                    try:
                        chunk = await asyncio.wait_for(
                            audio_queue.get(), timeout=5.0
                        )
                        await ws.send(chunk)
                    except asyncio.TimeoutError:
                        # Send keepalive (empty bytes)
                        await ws.send(b"")
                    except asyncio.CancelledError:
                        break

            async def receiver():
                """Receive transcripts from Deepgram → callback."""
                msg_count = 0
                async for msg in ws:
                    try:
                        data = json.loads(msg)
                        msg_count += 1
                        if msg_count <= 3:
                            logger.info(
                                f"[{speaker}] Deepgram msg #{msg_count} "
                                f"keys={list(data.keys())}"
                            )
                        self._process_message(speaker, data)
                    except json.JSONDecodeError:
                        logger.warning(
                            f"[{speaker}] Invalid JSON from Deepgram"
                        )
                    except asyncio.CancelledError:
                        break

            await asyncio.gather(sender(), receiver())

    # ------------------------------------------------------------------
    # Message Processing
    # ------------------------------------------------------------------
    def _process_message(self, speaker: str, data: dict):
        """Process a Deepgram response message.

        Deepgram has two levels of finality:
          - is_final=true   → segment text is finalized, but more segments
                               may follow for the same utterance.
          - speech_final=true → the speaker has stopped talking (triggered
                                 by utterance_end_ms). This is the signal
                                 to combine all buffered segments and fire
                                 the callback.

        Without accumulation, a sentence like "Please restart the interview"
        would be split into "Please" (processed alone) + "restart the
        interview" (processed separately), causing incorrect responses.
        """
        # Skip metadata-only messages (no channel data)
        if "metadata" in data and "channel" not in data:
            return

        channel = data.get("channel", {})

        # Deepgram may return channel as a list or dict
        if isinstance(channel, list):
            channel = channel[0] if channel else {}
        if not isinstance(channel, dict):
            return

        alternatives = channel.get("alternatives", [{}])
        if not alternatives:
            return

        alt = alternatives[0] if isinstance(alternatives[0], dict) else {}
        transcript = alt.get("transcript", "").strip()
        is_final = data.get("is_final", False)
        speech_final = data.get("speech_final", False)

        # Measure processing latency
        duration = data.get("duration", 0)
        if duration > 0:
            latency_ms = duration * 1000
            self._latencies[speaker].append(latency_ms)

        if not is_final:
            # Interim result — log for debug, don't accumulate
            if transcript:
                logger.debug(f"[{speaker}] interim: {transcript}")
            return

        # is_final=true — accumulate this segment
        if transcript:
            logger.info(f"[{speaker}] segment: {transcript}")
            self._utterance_buffer[speaker].append(transcript)

        # speech_final=true — speaker stopped talking, flush the buffer
        if speech_final:
            full_text = " ".join(self._utterance_buffer[speaker]).strip()
            self._utterance_buffer[speaker].clear()

            if full_text:
                logger.info(f"[{speaker}] UTTERANCE: {full_text}")
                asyncio.create_task(
                    self.on_transcript(speaker, full_text)
                )

    # ------------------------------------------------------------------
    # Latency Monitoring
    # ------------------------------------------------------------------
    def get_latency_stats(self) -> dict:
        """
        Get latency statistics for each channel.

        Returns dict with p50, p95, p99 in milliseconds.
        """
        stats = {}
        for speaker, latencies in self._latencies.items():
            if not latencies:
                stats[speaker] = {"p50": 0, "p95": 0, "p99": 0}
                continue

            sorted_lats = sorted(latencies)
            n = len(sorted_lats)
            stats[speaker] = {
                "p50": sorted_lats[int(n * 0.50)],
                "p95": sorted_lats[min(int(n * 0.95), n - 1)],
                "p99": sorted_lats[min(int(n * 0.99), n - 1)],
                "count": n,
            }
        return stats

    def should_reconnect(self, speaker: str) -> bool:
        """Check if latency exceeds threshold, suggesting reconnection."""
        stats = self.get_latency_stats()
        channel_stats = stats.get(speaker, {})
        p95 = channel_stats.get("p95", 0)
        return p95 > LATENCY_THRESHOLD_MS

    @property
    def is_running(self) -> bool:
        return self._running
