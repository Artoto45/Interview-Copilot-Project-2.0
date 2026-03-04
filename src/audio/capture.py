"""
Audio Capture Agent
===================
Captures dual audio streams via Voicemeeter Banana:
    - Bus B1 → User/Candidate microphone
    - Bus B2 → Interviewer (system audio from Zoom/Teams/Meet)

Both streams are pushed to async queues for downstream processing
by the DeepgramTranscriber.

Fallback: if Voicemeeter is not available, captures from the
default system microphone only.
"""

import asyncio
import logging
import os
from typing import Optional

import numpy as np
import sounddevice as sd
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("audio.capture")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
DEFAULT_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
DEFAULT_CHUNK_MS = int(os.getenv("AUDIO_CHUNK_MS", "100"))
DTYPE = "int16"
CHANNELS = 1


class AudioCaptureAgent:
    """
    Dual-stream audio capture agent.

    Opens two ``sounddevice.RawInputStream`` instances — one for the
    user (candidate) microphone and one for the interviewer audio
    routed through Voicemeeter Banana.

    Each captured chunk (100 ms ≈ 1,600 samples at 16 kHz) is placed
    into the corresponding ``asyncio.Queue`` for the transcription
    agent to consume.
    """

    def __init__(
        self,
        device_user: Optional[str] = None,
        device_interviewer: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        chunk_ms: int = DEFAULT_CHUNK_MS,
    ):
        self.device_user = device_user or os.getenv(
            "VOICEMEETER_DEVICE_USER", None
        )
        self.device_interviewer = device_interviewer or os.getenv(
            "VOICEMEETER_DEVICE_INT", None
        )
        self.sample_rate = sample_rate
        self.chunk_ms = chunk_ms
        self.blocksize = int(sample_rate * chunk_ms / 1000)

        # Async queues consumed by the transcription agent
        self.user_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self.int_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)

        # Stream handles
        self._stream_user: Optional[sd.RawInputStream] = None
        self._stream_int: Optional[sd.RawInputStream] = None
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _enqueue_nowait_drop_oldest(
        self,
        queue: asyncio.Queue[bytes],
        chunk: bytes,
    ):
        """
        Enqueue on the asyncio loop thread.
        If queue is full, drop one stale chunk to keep recent audio.
        """
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

        try:
            queue.put_nowait(chunk)
        except asyncio.QueueFull:
            # If race conditions fill it again, drop this chunk.
            pass

    def _schedule_enqueue(self, queue: asyncio.Queue[bytes], chunk: bytes):
        """
        Thread-safe bridge from sounddevice callback thread to asyncio queue.
        """
        if self._loop and self._loop.is_running():
            try:
                self._loop.call_soon_threadsafe(
                    self._enqueue_nowait_drop_oldest,
                    queue,
                    chunk,
                )
                return
            except RuntimeError:
                # Loop may be shutting down; fallback to best-effort direct write.
                pass

        # Used in tests and fallback when loop is unavailable.
        self._enqueue_nowait_drop_oldest(queue, chunk)

    # ------------------------------------------------------------------
    # Callbacks (run in audio thread — keep minimal)
    # ------------------------------------------------------------------
    def _cb_user(self, indata: bytes, frames: int, time_info, status):
        """Callback for user microphone stream."""
        if status:
            logger.warning(f"User audio status: {status}")
        self._schedule_enqueue(self.user_queue, bytes(indata))

    def _cb_interviewer(self, indata: bytes, frames: int, time_info, status):
        """Callback for interviewer audio stream."""
        if status:
            logger.warning(f"Interviewer audio status: {status}")
        self._schedule_enqueue(self.int_queue, bytes(indata))

    # ------------------------------------------------------------------
    # Device Resolution
    # ------------------------------------------------------------------
    def _resolve_device(self, name: Optional[str]) -> Optional[int]:
        """
        Resolve a device name (e.g., 'VoiceMeeter Out B1') to its
        integer index in ``sounddevice``.  Returns ``None`` if not found.
        """
        if name is None:
            return None

        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if name.lower() in dev["name"].lower() and dev["max_input_channels"] > 0:
                logger.info(f"Resolved device '{name}' → index {idx}")
                return idx

        logger.warning(f"Device '{name}' not found — available devices:")
        for idx, dev in enumerate(devices):
            if dev["max_input_channels"] > 0:
                logger.warning(f"  [{idx}] {dev['name']}")
        return None

    def _find_loopback_device(self) -> Optional[int]:
        """
        Search for a Stereo Mix / Loopback device that captures system
        audio output.  This is the fallback when Voicemeeter B2 is not
        configured — it captures whatever the speakers are playing
        (e.g., ChatGPT voice, Zoom, Teams).

        Common names across locales:
            - English: "Stereo Mix", "What U Hear", "Loopback"
            - Spanish: "Mezcla estéreo"
        """
        keywords = ["stereo mix", "mezcla est", "what u hear", "loopback"]
        devices = sd.query_devices()

        for idx, dev in enumerate(devices):
            if dev["max_input_channels"] <= 0:
                continue
            name_lower = dev["name"].lower()
            if any(kw in name_lower for kw in keywords):
                logger.info(
                    f"Found loopback device: [{idx}] {dev['name']}"
                )
                return idx

        logger.warning("No Stereo Mix / Loopback device found")
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self):
        """Open audio streams and begin capture."""
        if self._running:
            logger.warning("AudioCaptureAgent already running")
            return

        self._loop = asyncio.get_running_loop()
        logger.info("Starting audio capture…")

        # Resolve devices
        user_dev = self._resolve_device(self.device_user)
        int_dev = self._resolve_device(self.device_interviewer)

        # --- User stream ---
        if user_dev is not None:
            self._stream_user = sd.RawInputStream(
                device=user_dev,
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=self.blocksize,
                callback=self._cb_user,
            )
            self._stream_user.start()
            logger.info(
                f"User stream opened: device={user_dev}, "
                f"rate={self.sample_rate}, blocksize={self.blocksize}"
            )
        else:
            # Fallback: use default input device
            try:
                default_dev = sd.default.device[0]
                self._stream_user = sd.RawInputStream(
                    device=default_dev,
                    samplerate=self.sample_rate,
                    channels=CHANNELS,
                    dtype=DTYPE,
                    blocksize=self.blocksize,
                    callback=self._cb_user,
                )
                self._stream_user.start()
                logger.info(
                    f"User stream (fallback): device={default_dev}, "
                    f"rate={self.sample_rate}"
                )
            except Exception as e:
                logger.error(f"Cannot open user audio stream: {e}")

        # --- Interviewer stream ---
        if int_dev is not None:
            self._stream_int = sd.RawInputStream(
                device=int_dev,
                samplerate=self.sample_rate,
                channels=CHANNELS,
                dtype=DTYPE,
                blocksize=self.blocksize,
                callback=self._cb_interviewer,
            )
            self._stream_int.start()
            logger.info(
                f"Interviewer stream opened: device={int_dev}, "
                f"rate={self.sample_rate}"
            )
        else:
            # Fallback: try Stereo Mix / Loopback for system audio
            loopback_dev = self._find_loopback_device()
            if loopback_dev is not None:
                dev_info = sd.query_devices(loopback_dev)
                native_rate = int(dev_info["default_samplerate"])
                native_ch = min(dev_info["max_input_channels"], 2)
                ratio = max(1, native_rate // self.sample_rate)
                native_blocksize = int(
                    native_rate * self.chunk_ms / 1000
                )

                _loopback_chunk_count = [0]  # mutable counter in closure

                def _cb_loopback(indata, frames, time_info, status):
                    """Resample loopback audio to 16 kHz mono."""
                    if status:
                        logger.warning(f"Loopback status: {status}")
                    try:
                        samples = np.frombuffer(
                            bytes(indata), dtype=np.int16
                        ).astype(np.float32)

                        # Stereo → mono: sum channels (preserves volume
                        # better than mean for typical stereo content)
                        if native_ch > 1:
                            samples = samples.reshape(-1, native_ch)
                            samples = samples.sum(axis=1)

                        # Downsample (simple decimation)
                        if ratio > 1:
                            samples = samples[::ratio]

                        # Apply gain boost — Stereo Mix levels are often
                        # too quiet for Deepgram to detect speech
                        gain = float(os.getenv("LOOPBACK_GAIN", "2.0"))
                        samples = samples * gain

                        # Clip to int16 range and convert
                        samples = np.clip(
                            samples, -32768, 32767
                        ).astype(np.int16)

                        # Log RMS level periodically for diagnostics
                        _loopback_chunk_count[0] += 1
                        if _loopback_chunk_count[0] % 100 == 0:
                            rms = np.sqrt(np.mean(
                                samples.astype(np.float32) ** 2
                            ))
                            logger.info(
                                f"Loopback audio RMS: {rms:.0f} "
                                f"(chunks: {_loopback_chunk_count[0]})"
                            )

                        self._schedule_enqueue(
                            self.int_queue,
                            samples.tobytes(),
                        )
                    except Exception as e:
                        logger.debug(f"Loopback callback error: {e}")

                self._stream_int = sd.RawInputStream(
                    device=loopback_dev,
                    samplerate=native_rate,
                    channels=native_ch,
                    dtype=DTYPE,
                    blocksize=native_blocksize,
                    callback=_cb_loopback,
                )
                self._stream_int.start()
                logger.info(
                    f"Interviewer stream (Stereo Mix): "
                    f"device={loopback_dev}, native={native_rate}Hz/"
                    f"{native_ch}ch → resampled to {self.sample_rate}Hz"
                )
            else:
                logger.warning(
                    "No interviewer audio device found — "
                    "tried Voicemeeter B2 and Stereo Mix. "
                    "Only user audio will be captured."
                )

        self._running = True
        logger.info("Audio capture started ✓")

    async def stop(self):
        """Stop and close all audio streams."""
        if not self._running:
            return

        logger.info("Stopping audio capture…")

        if self._stream_user and self._stream_user.active:
            self._stream_user.stop()
            self._stream_user.close()
            self._stream_user = None

        if self._stream_int and self._stream_int.active:
            self._stream_int.stop()
            self._stream_int.close()
            self._stream_int = None

        self._running = False
        self._loop = None
        logger.info("Audio capture stopped ✓")

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    def get_audio_levels(self) -> dict:
        """
        Sample current audio levels (RMS) for diagnostics.
        Useful for the pre-interview checklist artifact.
        """
        result = {"user_rms": 0.0, "interviewer_rms": 0.0}

        if not self.user_queue.empty():
            try:
                chunk = self.user_queue.get_nowait()
                samples = np.frombuffer(chunk, dtype=np.int16).astype(
                    np.float32
                )
                result["user_rms"] = float(np.sqrt(np.mean(samples ** 2)))
                # Put it back
                self.user_queue.put_nowait(chunk)
            except Exception:
                pass

        return result

    @staticmethod
    def list_available_devices() -> list[dict]:
        """List all available input audio devices."""
        devices = sd.query_devices()
        return [
            {
                "index": idx,
                "name": dev["name"],
                "channels": dev["max_input_channels"],
                "sample_rate": dev["default_samplerate"],
            }
            for idx, dev in enumerate(devices)
            if dev["max_input_channels"] > 0
        ]
