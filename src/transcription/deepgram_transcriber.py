"""
Deepgram Transcription Client
======================================
WebSocket connection to Deepgram's streaming API (Nova-3) for
fast and accurate speech-to-text.

Replaces the interviewer's OpenAI transcription channel to lower costs.
Maintains the exact same three-buffer structure and API signature as
OpenAIRealtimeTranscriber.
"""

import asyncio
import logging
import os
import threading
import time
from collections import deque
from typing import Callable, Optional, Awaitable

import numpy as np
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("transcription.deepgram")
TURN_FLUSH_GRACE_MS = max(
    80,
    int(os.getenv("DEEPGRAM_TURN_FLUSH_GRACE_MS", "240")),
)

# Callback types
TranscriptCallback = Callable[[str, str], Awaitable[None]]  # (speaker, text)
DeltaCallback = Callable[[str, str], Awaitable[None]]       # (speaker, partial)
SpeechEventCallback = Callable[[str, str], Awaitable[None]] # (speaker, event)


class DeepgramTranscriber:
    """
    Real-time transcription using Deepgram's Nova-3 model.
    Mirrors the exact API surface of OpenAIRealtimeTranscriber.
    """

    def __init__(
        self,
        on_transcript: TranscriptCallback,
        on_delta: Optional[DeltaCallback] = None,
        on_speech_event: Optional[SpeechEventCallback] = None,
        api_key: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("DEEPGRAM_API_KEY", "")
        self.on_transcript = on_transcript
        self.on_delta = on_delta
        self.on_speech_event = on_speech_event
        
        # Initialize Deepgram Client
        if self.api_key:
            config = DeepgramClientOptions(
                options={"keepalive": "true"}
            )
            self.dg_client = DeepgramClient(self.api_key, config)
        else:
            self.dg_client = None

        # Three-buffer architecture
        self._live_buffer: str = ""          # Current delta text
        self._turn_buffer: list[str] = []    # Completed segments
        self._recent_turns: deque = deque(maxlen=10)  # History

        # State
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._ws = None
        self._speaker = "interviewer"
        self._speech_active = False
        self._buffer_lock = threading.Lock()
        self._turn_metrics: deque = deque(maxlen=200)
        self._turn_started_ts: float = 0.0
        self._pending_flush_payload: Optional[dict] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def start(
        self,
        audio_queue: asyncio.Queue,
        speaker: str = "interviewer",
    ):
        """Start transcription for an audio channel."""
        if self._running:
            logger.warning("DeepgramTranscriber already running")
            return

        if not self.dg_client:
            logger.error(
                "DEEPGRAM_API_KEY not set — transcription disabled. "
                "Set it in your .env file."
            )
            return

        self._running = True
        self._speaker = speaker
        self._audio_queue = audio_queue
        
        # Capture the main asyncio loop so the Deepgram background thread
        # can safely dispatch events back to the main thread pipeline
        try:
            self._main_loop = asyncio.get_running_loop()
        except RuntimeError:
            self._main_loop = None

        task = asyncio.create_task(
            self._run_channel(),
            name=f"deepgram-realtime-{speaker}",
        )
        self._tasks.append(task)
        logger.info(f"Deepgram transcription started ({speaker})")

    def get_live_buffer(self) -> str:
        """Get current delta text (live transcript buffer)."""
        return self._live_buffer
        
    @property
    def live_buffer_deprecated(self):
        """Deprecated: Use get_live_buffer() instead"""
        return self._live_buffer

    async def clear_live_buffer(self):
        """Clear the current live buffer text."""
        self._live_buffer = ""

    async def get_turn_buffer(self) -> str:
        """Get the full text of the current completed turn."""
        return " ".join(self._turn_buffer).strip()

    async def clear_turn_buffer(self):
        """Clear the accumulated completed segments."""
        self._turn_buffer.clear()

    async def get_recent_history(self) -> str:
        """Get the last N completed turns."""
        return " | ".join(self._recent_turns)

    def get_turn_metrics_snapshot(self) -> list[dict]:
        """Return recent transcription turn metrics for diagnostics."""
        with self._buffer_lock:
            return list(self._turn_metrics)

    async def stop(self):
        """Stop transcription gracefully."""
        self._running = False
        if self._ws:
            try:
                self._ws.finish()
            except Exception as e:
                logger.error(f"Error closing Deepgram connection: {e}")

        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # Await cancelled tasks to prevent warnings
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        
        logger.info(f"Deepgram transcription stopped ✓")

    # ------------------------------------------------------------------
    # Internal Handlers
    # ------------------------------------------------------------------
    async def _run_channel(self):
        """Manage the Deepgram WebSocket connection and audio streaming."""
        try:
            logger.info(f"[{self._speaker}] Connecting to Deepgram API…")
            self._ws = self.dg_client.listen.websocket.v("1")

            # Link Deepgram event handlers to our callbacks
            self._ws.on(LiveTranscriptionEvents.Transcript, self._on_message)
            self._ws.on(LiveTranscriptionEvents.SpeechStarted, self._on_speech_started)

            # Nova-3 options for low latency conversational AI
            options = LiveOptions(
                model="nova-3",
                language="en",
                encoding="linear16",    # Raw PCM 16-bit
                channels=1,
                sample_rate=16000,      # Matching our capture rate
                endpointing=200,        # Faster turn detection
                smart_format=True,      # Punctuation/capitalization
                interim_results=True,   # Send partial streams
                vad_events=True,        # Needed for SpeechStarted
            )

            if not self._ws.start(options):
                logger.error(f"[{self._speaker}] Deepgram connection failed")
                return

            logger.info(f"[{self._speaker}] Connected ✓")

            # Stream audio from queue to Deepgram
            while self._running:
                try:
                    # Pull PCM bytes directly from the audio thread queue
                    audio_data = await asyncio.wait_for(self._audio_queue.get(), timeout=1.0)
                    if not self._running:
                        break
                        
                    # Queue holds np.ndarray (float32). Convert to int16 bytes for linear16
                    if isinstance(audio_data, np.ndarray):
                        int16_data = (audio_data * 32767).astype(np.int16).tobytes()
                    else:
                        int16_data = audio_data
                        
                    self._ws.send(int16_data)
                    
                except asyncio.TimeoutError:
                    continue  # Keep waiting loop alive
                    
        except asyncio.CancelledError:
            logger.info(f"[{self._speaker}] Task cancelled")
        except Exception as e:
            logger.error(f"[{self._speaker}] Deepgram stream error: {e}", exc_info=True)
        finally:
            self._running = False
            if self._ws:
                self._ws.finish()

    def _on_speech_started(self, *args, **kwargs):
        """Callback from Deepgram when speech is detected."""
        self._flush_pending_turn(flush_reason="interrupted_by_new_speech")
        if not self._speech_active:
            self._speech_active = True
            with self._buffer_lock:
                self._turn_started_ts = time.monotonic()
            logger.info(f"[{self._speaker}] Speech started")
            if self.on_speech_event and self._main_loop:
                # Deepgram invokes callbacks from a background thread.
                # Dispatch on the coordinator loop to preserve thread safety
                # and keep event names aligned with OpenAIRealtimeTranscriber.
                asyncio.run_coroutine_threadsafe(
                    self.on_speech_event(self._speaker, "started"),
                    self._main_loop,
                )

    def _on_message(self, *args, **kwargs):
        """Callback from Deepgram with transcript data."""
        # The python SDK passes the client as first arg, result as second
        result = kwargs.get("result")
        if result is None and len(args) >= 2:
            result = args[1]
        elif result is None and len(args) == 1:
            result = args[0]

        logger.debug(f"DEEPGRAM RAW RESULT: {type(result)}: {result}")
        
        if getattr(result, "type", None) != "Results":
            return

        try:
            sentence = ""
            if getattr(result, "channel", None):
                alts = getattr(result.channel, "alternatives", [])
                if alts and len(alts) > 0:
                    sentence = getattr(alts[0], "transcript", "") or ""
            
            sentence = sentence.strip()
            
            is_final = getattr(result, "is_final", False)
            speech_final = getattr(result, "speech_final", False)

            if sentence:
                if is_final:
                    with self._buffer_lock:
                        self._turn_buffer.append(sentence)
                        self._recent_turns.append(sentence)
                        self._live_buffer = ""
                    # Do NOT dispatch on_transcript here, wait for speech_final
                else:
                    self._live_buffer = sentence
                    if self.on_delta and self._main_loop:
                        asyncio.run_coroutine_threadsafe(
                            self.on_delta(self._speaker, sentence),
                            self._main_loop
                        )

            # When speech naturally concludes
            if speech_final:
                if self._speech_active:
                    logger.info(f"[{self._speaker}] Speech stopped")
                    if self.on_speech_event and self._main_loop:
                        asyncio.run_coroutine_threadsafe(
                            self.on_speech_event(self._speaker, "stopped"),
                            self._main_loop
                        )
                
                self._speech_active = False

                flush_token = time.monotonic()
                with self._buffer_lock:
                    self._pending_flush_payload = {
                        "token": flush_token,
                        "turn_started_ts": self._turn_started_ts,
                        "speech_final_ts": flush_token,
                    }
                    self._turn_started_ts = 0.0

                grace_seconds = TURN_FLUSH_GRACE_MS / 1000.0
                threading.Thread(
                    target=self._flush_turn_after_grace,
                    args=(flush_token, grace_seconds),
                    daemon=True,
                    name=f"deepgram-flush-{self._speaker}",
                ).start()

        except Exception as e:
            logger.error(f"Error processing Deepgram message: {e}", exc_info=True)

    def _flush_turn_after_grace(
        self,
        flush_token: float,
        grace_seconds: float,
    ):
        """Flush buffered final segments after a short grace period."""
        time.sleep(max(0.0, grace_seconds))
        self._flush_pending_turn(
            expected_token=flush_token,
            flush_reason="grace_timeout",
        )

    def _flush_pending_turn(
        self,
        expected_token: Optional[float] = None,
        flush_reason: str = "manual",
    ):
        """
        Flush pending turn segments into a single transcript payload.

        expected_token ensures stale flush workers cannot flush newer turns.
        """
        with self._buffer_lock:
            payload = self._pending_flush_payload
            if not payload:
                return
            if (
                expected_token is not None
                and float(payload.get("token", -1.0)) != float(expected_token)
            ):
                return

            segments = list(self._turn_buffer)
            self._turn_buffer.clear()
            self._live_buffer = ""
            self._pending_flush_payload = None
            turn_started_ts = float(payload.get("turn_started_ts", 0.0) or 0.0)
            speech_final_ts = float(payload.get("speech_final_ts", 0.0) or 0.0)

        full_text = " ".join(segments).strip()
        now = time.monotonic()
        turn_duration_ms = (
            int((now - turn_started_ts) * 1000)
            if turn_started_ts > 0
            else 0
        )
        flush_delay_ms = (
            int((now - speech_final_ts) * 1000)
            if speech_final_ts > 0
            else 0
        )

        metric = {
            "speaker": self._speaker,
            "segment_count": len(segments),
            "word_count": len(full_text.split()) if full_text else 0,
            "char_count": len(full_text),
            "turn_duration_ms": turn_duration_ms,
            "flush_delay_ms": flush_delay_ms,
            "flush_reason": flush_reason,
            "timestamp": time.time(),
        }
        with self._buffer_lock:
            self._turn_metrics.append(metric)

        logger.info(
            f"[{self._speaker}] TURN FLUSH "
            f"(segments={metric['segment_count']}, words={metric['word_count']}, "
            f"delay={metric['flush_delay_ms']}ms, reason={flush_reason})"
        )

        if full_text:
            logger.info(f"[{self._speaker}] COMPLETED: {full_text}")
            if self.on_transcript and self._main_loop:
                asyncio.run_coroutine_threadsafe(
                    self.on_transcript(self._speaker, full_text),
                    self._main_loop,
                )
