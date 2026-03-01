"""
OpenAI Realtime Transcription Client
======================================
WebSocket connection to OpenAI's Realtime API using
gpt-4o-mini-transcribe for streaming speech-to-text.

Session type: "transcription" (ASR-only, no model responses)
VAD: semantic_vad (better turn segmentation than silence-based)
Audio: PCM 16-bit 24 kHz mono (base64 encoded over WebSocket)

Three-buffer architecture:
    - Live buffer:     delta text (partial, for subtitles)
    - Turn buffer:     completed text (full utterance)
    - Question buffer: turns detected as real interview questions

Cost: ~$0.003/minute (vs conversational Realtime at $10+/1M audio tokens)
"""

import asyncio
import base64
import json
import logging
import os
from collections import deque
from typing import Callable, Optional, Awaitable

import numpy as np
from dotenv import load_dotenv

try:
    import websockets
except ImportError:
    websockets = None

load_dotenv()
logger = logging.getLogger("transcription.openai_realtime")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REALTIME_URL = "wss://api.openai.com/v1/realtime"
TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"
INPUT_SAMPLE_RATE = 16000   # Our audio capture rate
TARGET_SAMPLE_RATE = 24000  # OpenAI Realtime expects 24 kHz
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_DELAY_S = 3.0

# Callback types
TranscriptCallback = Callable[[str, str], Awaitable[None]]  # (speaker, text)
DeltaCallback = Callable[[str, str], Awaitable[None]]       # (speaker, partial)
SpeechEventCallback = Callable[[str, str], Awaitable[None]] # (speaker, event)


class OpenAIRealtimeTranscriber:
    """
    Real-time transcription using OpenAI's Realtime API.

    Manages a WebSocket connection for streaming audio and
    receiving transcription events with semantic VAD.

    Usage::

        transcriber = OpenAIRealtimeTranscriber(
            on_transcript=my_callback,
            on_delta=my_delta_callback,      # optional
            on_speech_event=my_event_cb,     # optional
        )
        await transcriber.start(audio_queue)
        # ... runs until stopped ...
        await transcriber.stop()
    """

    def __init__(
        self,
        on_transcript: TranscriptCallback,
        on_delta: Optional[DeltaCallback] = None,
        on_speech_event: Optional[SpeechEventCallback] = None,
        api_key: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.on_transcript = on_transcript
        self.on_delta = on_delta
        self.on_speech_event = on_speech_event

        # Three-buffer architecture
        self._live_buffer: str = ""          # Current delta text
        self._turn_buffer: list[str] = []    # Completed segments
        self._recent_turns: deque = deque(maxlen=10)  # History

        # State
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._ws = None

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
            logger.warning("OpenAIRealtimeTranscriber already running")
            return

        if not self.api_key:
            logger.error(
                "OPENAI_API_KEY not set — transcription disabled. "
                "Set it in your .env file."
            )
            return

        self._running = True
        self._speaker = speaker

        task = asyncio.create_task(
            self._run_channel(speaker, audio_queue),
            name=f"openai-realtime-{speaker}",
        )
        self._tasks.append(task)
        logger.info(f"OpenAI Realtime transcription started ({speaker})")

    def get_live_buffer(self) -> str:
        """Get current delta text (live transcript buffer)
        
        Returns the most recent partial transcription text.
        Safe to call from any thread.
        """
        return self._live_buffer
        
    @property
    def live_buffer_deprecated(self):
        """Deprecated: Use get_live_buffer() instead"""
        logger.warning(
            "live_buffer property is deprecated, use get_live_buffer()"
        )
        return self._live_buffer

    async def stop(self):
        """Stop transcription."""
        self._running = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("OpenAI Realtime transcription stopped ✓")

    # ------------------------------------------------------------------
    # Channel Runner (with auto-reconnect)
    # ------------------------------------------------------------------
    async def _run_channel(
        self, speaker: str, audio_queue: asyncio.Queue
    ):
        """Run with auto-reconnect on failure."""
        attempts = 0

        while self._running and attempts < MAX_RECONNECT_ATTEMPTS:
            try:
                await self._stream_channel(speaker, audio_queue)
                attempts = 0  # Reset on clean exit
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
                f"[{speaker}] Max reconnect attempts — channel disabled"
            )

    async def _stream_channel(
        self, speaker: str, audio_queue: asyncio.Queue
    ):
        """
        Open WebSocket to OpenAI Realtime API and stream audio.
        """
        # Build URL — transcription sessions use intent=transcription
        # The model is specified in the session config, not the URL
        url = f"{REALTIME_URL}?intent=transcription"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        logger.info(f"[{speaker}] Connecting to OpenAI Realtime API…")

        async with websockets.connect(
            url,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=10,
            max_size=2**24,  # 16 MB max message
        ) as ws:
            self._ws = ws
            logger.info(f"[{speaker}] Connected ✓")

            # Configure the transcription session
            await self._configure_session(ws)

            # Run sender + receiver in parallel
            async def sender():
                """Stream audio chunks from queue → OpenAI."""
                chunk_count = 0
                while self._running:
                    try:
                        chunk = await asyncio.wait_for(
                            audio_queue.get(), timeout=5.0
                        )
                        # Resample 16kHz → 24kHz and encode as base64
                        resampled = self._resample_audio(chunk)
                        b64_audio = base64.b64encode(resampled).decode("utf-8")

                        await ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": b64_audio,
                        }))

                        chunk_count += 1
                        if chunk_count % 500 == 0:
                            logger.info(
                                f"[{speaker}] Sent {chunk_count} chunks"
                            )
                    except asyncio.TimeoutError:
                        # Send empty keepalive
                        pass
                    except asyncio.CancelledError:
                        break

            async def receiver():
                """Receive events from OpenAI → process."""
                msg_count = 0
                async for raw_msg in ws:
                    try:
                        event = json.loads(raw_msg)
                        msg_count += 1
                        if msg_count <= 3:
                            logger.info(
                                f"[{speaker}] Event #{msg_count}: "
                                f"type={event.get('type', 'unknown')}"
                            )
                        await self._process_event(speaker, event)
                    except json.JSONDecodeError:
                        logger.warning(
                            f"[{speaker}] Invalid JSON from OpenAI"
                        )
                    except asyncio.CancelledError:
                        break

            await asyncio.gather(sender(), receiver())

    # ------------------------------------------------------------------
    # Session Configuration
    # ------------------------------------------------------------------
    async def _configure_session(self, ws):
        """Send session configuration for transcription mode."""
        config = {
            "type": "transcription_session.update",
            "session": {
                "input_audio_format": "pcm16",
                "input_audio_transcription": {
                    "model": TRANSCRIPTION_MODEL,
                    "language": "en",
                    "prompt": "",
                },
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 200,
                    "silence_duration_ms": 500,
                },
            },
        }

        await ws.send(json.dumps(config))
        logger.info("Session configured: transcription + server_vad")

    # ------------------------------------------------------------------
    # Event Processing
    # ------------------------------------------------------------------
    async def _process_event(self, speaker: str, event: dict):
        """Process an event from the OpenAI Realtime API."""
        event_type = event.get("type", "")

        # --- Speech lifecycle events ---
        if event_type == "input_audio_buffer.speech_started":
            logger.info(f"[{speaker}] Speech started")
            self._live_buffer = ""
            if self.on_speech_event:
                await self.on_speech_event(speaker, "started")

        elif event_type == "input_audio_buffer.speech_stopped":
            logger.info(f"[{speaker}] Speech stopped")
            if self.on_speech_event:
                await self.on_speech_event(speaker, "stopped")

        # --- Transcription events ---
        elif event_type == "conversation.item.input_audio_transcription.delta":
            delta = event.get("delta", "")
            if delta:
                self._live_buffer += delta
                logger.debug(f"[{speaker}] delta: {delta}")
                if self.on_delta:
                    await self.on_delta(speaker, delta)

        elif event_type == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "").strip()
            if transcript:
                logger.info(f"[{speaker}] COMPLETED: {transcript}")
                self._turn_buffer.append(transcript)
                self._recent_turns.append(transcript)

                # Flush as complete utterance
                full_text = " ".join(self._turn_buffer).strip()
                self._turn_buffer.clear()
                self._live_buffer = ""

                if full_text:
                    await self.on_transcript(speaker, full_text)

        # --- Session events ---
        elif event_type == "transcription_session.created":
            logger.info(f"[{speaker}] Transcription session created")

        elif event_type == "transcription_session.updated":
            logger.info(f"[{speaker}] Transcription session updated")

        elif event_type == "input_audio_buffer.committed":
            logger.debug(f"[{speaker}] Audio buffer committed")

        elif event_type == "error":
            error = event.get("error", {})
            logger.error(
                f"[{speaker}] API error: "
                f"{error.get('message', 'unknown')}"
            )

        else:
            logger.debug(f"[{speaker}] Unhandled event: {event_type}")

    # ------------------------------------------------------------------
    # Audio Resampling
    # ------------------------------------------------------------------
    @staticmethod
    def _resample_audio(chunk: bytes) -> bytes:
        """
        Resample audio from 16 kHz to 24 kHz (PCM16 mono).

        OpenAI Realtime API expects 24 kHz input.
        Uses simple linear interpolation for quality resampling.
        """
        samples = np.frombuffer(chunk, dtype=np.int16).astype(np.float32)

        # Ratio: 24000 / 16000 = 1.5
        target_len = int(len(samples) * TARGET_SAMPLE_RATE / INPUT_SAMPLE_RATE)

        if target_len == len(samples):
            return chunk

        # Linear interpolation resampling
        x_old = np.linspace(0, 1, len(samples))
        x_new = np.linspace(0, 1, target_len)
        resampled = np.interp(x_new, x_old, samples)

        return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def recent_turns(self) -> list[str]:
        """Get recent conversation turns for context."""
        return list(self._recent_turns)

