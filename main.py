"""
Interview Copilot — Main Coordinator (Direct Pipeline)
========================================================
Direct Python pipeline that orchestrates the interview flow:
    Audio Capture → OpenAI Realtime Transcription → Question Filter
    → KB/RAG → Response → Teleprompter

No web server — communicates with the Qt teleprompter via a
lightweight local WebSocket server (websockets library only).
"""

import asyncio
import json
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import websockets
from websockets.asyncio.server import ServerConnection
from dotenv import load_dotenv

from src.audio.capture import AudioCaptureAgent
from src.transcription.openai_realtime import OpenAIRealtimeTranscriber
from src.transcription.deepgram_transcriber import DeepgramTranscriber
from src.knowledge.retrieval import KnowledgeRetriever
from src.knowledge.classifier import QuestionClassifier
from src.knowledge.question_filter import QuestionFilter
from src.response.openai_agent import OpenAIAgent
from src.metrics import SessionMetrics, QuestionMetrics
from src.alerting import AlertManager
from src.prometheus import start_metrics_server, response_latency, cache_hit_rate, question_count
from src.cost_calculator import CostTracker, format_cost_for_display

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-22s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("coordinator")

WS_HOST = "127.0.0.1"
WS_PORT = 8765  # Local-only WebSocket for teleprompter bridge


# ---------------------------------------------------------------------------
# Pipeline State
# ---------------------------------------------------------------------------
class PipelineState:
    """Holds the runtime state of the interview pipeline."""

    def __init__(self):
        self.total_questions = 0
        self.total_responses = 0
        self.last_activity: Optional[str] = None

        # Agent instances
        self.audio_agent: Optional[AudioCaptureAgent] = None
        self.transcriber_user: Optional[OpenAIRealtimeTranscriber] = None
        self.transcriber_int: Optional[DeepgramTranscriber] = None
        self.retriever: Optional[KnowledgeRetriever] = None
        self.classifier: Optional[QuestionClassifier] = None
        self.question_filter: Optional[QuestionFilter] = None
        self.response_agent: Optional[OpenAIAgent] = None

        # Connected teleprompter clients
        self.ws_clients: set = set()

        # Conversation history for context
        self.conversation_history: list[dict] = []
        
        # Observability
        self.session_metrics: Optional[SessionMetrics] = None
        self.alert_manager: Optional[AlertManager] = None
        self.cost_tracker: Optional[CostTracker] = None


pipeline = PipelineState()


# ---------------------------------------------------------------------------
# WebSocket Broadcast (lightweight, no FastAPI)
# ---------------------------------------------------------------------------
async def broadcast_message(message: dict):
    """Send a JSON message to all connected teleprompter clients."""
    try:
        if not pipeline.ws_clients:
            return
        data = json.dumps(message, ensure_ascii=False)
        disconnected = set()
        for ws in list(pipeline.ws_clients):
            try:
                await ws.send(data)
            except Exception:
                disconnected.add(ws)
        pipeline.ws_clients -= disconnected
    except Exception as e:
        logger.warning(f"WebSocket broadcast error suppressed: {e}")


async def broadcast_token(token: str):
    """Send a streaming token to teleprompter clients."""
    await broadcast_message({"type": "token", "data": token})


async def ws_handler(websocket: ServerConnection):
    """Handle a teleprompter WebSocket connection."""
    pipeline.ws_clients.add(websocket)
    logger.info(
        f"Teleprompter connected (total: {len(pipeline.ws_clients)})"
    )
    try:
        async for msg in websocket:
            # Teleprompter may send commands in the future
            pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        pipeline.ws_clients.discard(websocket)
        logger.info(
            f"Teleprompter disconnected "
            f"(remaining: {len(pipeline.ws_clients)})"
        )


# ---------------------------------------------------------------------------
# Pipeline Callbacks
# ---------------------------------------------------------------------------

class SpeculativeState:
    """Thread-safe state management for speculative retrieval/generation"""
    
    def __init__(self):
        self.lock = asyncio.Lock()
        self.retrieval_task: asyncio.Task | None = None
        self.retrieval_query: str = ""
        self.gen_task: asyncio.Task | None = None
        self.gen_tokens: list[str] = []
    
    async def cancel_all(self):
        """Cancel all pending speculative tasks"""
        async with self.lock:
            if self.retrieval_task:
                logger.info("Cancelling speculative retrieval")
                self.retrieval_task.cancel()
            if self.gen_task:
                logger.info("Cancelling speculative generation")
                self.gen_task.cancel()
            self.gen_tokens.clear()
            self.retrieval_task = None
            self.gen_task = None
            self.retrieval_query = ""
            
    async def cancel_gen(self):
        """Cancel only the generation task"""
        async with self.lock:
            if self.gen_task:
                self.gen_task.cancel()
            self.gen_tokens.clear()
            self.gen_task = None
    
    async def set_retrieval_task(self, task, query: str):
        async with self.lock:
            self.retrieval_task = task
            self.retrieval_query = query
            
    async def get_retrieval_task(self) -> tuple[asyncio.Task | None, str]:
        async with self.lock:
            return self.retrieval_task, self.retrieval_query

    async def clear_retrieval(self):
        async with self.lock:
            self.retrieval_task = None
            self.retrieval_query = ""
            
    async def set_gen_task(self, task):
        async with self.lock:
            self.gen_task = task
            self.gen_tokens.clear()
            
    async def get_gen_task(self) -> asyncio.Task | None:
        async with self.lock:
            return self.gen_task
    
    async def get_tokens(self) -> list[str]:
        async with self.lock:
            return self.gen_tokens.copy()

    async def add_token(self, token: str):
        async with self.lock:
            self.gen_tokens.append(token)

_speculative = SpeculativeState()


async def on_transcript(speaker: str, text: str):
    """
    Callback: called when a complete utterance arrives.

    Role mapping:
        - "user" = candidate (YOU, the person using the copilot)
                   → mic input, saved as context, does NOT trigger RAG
        - "interviewer" = the person asking questions
                   → system audio, triggers question filter → RAG → teleprompter
    """
    if not text.strip():
        return

    logger.info(f"TRANSCRIPT [{speaker}] {text}")
    pipeline.last_activity = datetime.now().isoformat()

    # Broadcast transcript to teleprompter (both speakers shown)
    await broadcast_message({
        "type": "transcript",
        "speaker": speaker,
        "text": text,
    })

    if speaker == "interviewer":
        # --- INTERVIEWER: evaluate and potentially trigger RAG ---
        if pipeline.question_filter.is_interview_question(text):
            pipeline.total_questions += 1
            await process_question(text)
        else:
            logger.info(f"Interviewer noise skipped: {text[:60]}…")

    elif speaker == "user":
        # --- CANDIDATE: save as context (what YOU already said) ---
        pipeline.conversation_history.append({
            "speaker": "candidate",
            "text": text,
            "timestamp": datetime.now().isoformat(),
        })
        logger.info(f"Candidate speech saved as context ({len(text)} chars)")


async def on_delta(speaker: str, delta: str):
    """Callback: partial transcription text for live subtitles."""
    await broadcast_message({
        "type": "subtitle_delta",
        "speaker": speaker,
        "text": delta,
    })


async def on_speech_event(speaker: str, event: str):
    """
    Callback: speech started/stopped events from VAD.

    SPECULATIVE OPTIMIZATION: When interviewer speech stops,
    immediately start KB retrieval using the accumulated delta text.
    This runs DURING the ~5s transcription processing time,
    so KB chunks are ready when the final transcript arrives.
    """
    await broadcast_message({
        "type": "speech_event",
        "speaker": speaker,
        "event": event,
    })

    if speaker == "interviewer" and event == "stopped":
        # Grab the delta text accumulated so far
        if pipeline.transcriber_int and hasattr(pipeline.transcriber_int, 'get_live_buffer'):
            delta_text = pipeline.transcriber_int.get_live_buffer().strip()
            if delta_text and len(delta_text.split()) >= 4:
                logger.info(
                    f"SPECULATIVE: Pre-fetching KB + starting generation "
                    f"for: {delta_text[:60]}…"
                )

                # Start KB retrieval speculatively
                r_task = asyncio.create_task(
                    pipeline.retriever.retrieve(
                        query=delta_text,
                        question_type="personal",
                    )
                )
                await _speculative.set_retrieval_task(r_task, delta_text)

                # Start speculative generation (Optimization #3)
                g_task = asyncio.create_task(
                    _run_speculative_generation(delta_text)
                )
                await _speculative.set_gen_task(g_task)

    elif speaker == "interviewer" and event == "started":
        # Cancel any stale speculative tasks
        await _speculative.cancel_all()


async def _run_speculative_generation(delta_text: str):
    """Run speculative generation using delta text during transcription."""
    try:
        # Wait for speculative KB retrieval first
        r_task, _ = await _speculative.get_retrieval_task()
        if r_task:
            kb_chunks = await r_task
        else:
            kb_chunks = []

        # Classify speculatively
        classification = pipeline.classifier._fallback_classify(delta_text)

        # Generate speculatively (tokens buffered, not broadcast yet)
        async for token in pipeline.response_agent.generate(
            question=delta_text,
            kb_chunks=kb_chunks,
            question_type=classification["type"],
        ):
            await _speculative.add_token(token)
    except asyncio.CancelledError:
        logger.info("Speculative generation cancelled")
    except Exception as e:
        logger.warning(f"Speculative generation error: {e}")


async def is_similar_enough_semantic(delta: str, final: str) -> tuple[bool, float]:
    """Check semantic similarity between delta and final transcript"""
    if not delta or not final:
        return False, 0.0
    
    try:
        from openai import AsyncOpenAI
        import numpy as np
        
        client = AsyncOpenAI()
        embeddings = await client.embeddings.create(
            model="text-embedding-3-small",
            input=[delta, final]
        )
        
        delta_emb = np.array(embeddings.data[0].embedding, dtype=np.float32)
        final_emb = np.array(embeddings.data[1].embedding, dtype=np.float32)

        # Cosine similarity
        dot_product = float(np.dot(delta_emb, final_emb))
        norm_product = float(np.linalg.norm(delta_emb)) * float(np.linalg.norm(final_emb))
        similarity = float(dot_product / norm_product)

        is_similar = similarity > 0.80
        logger.info(f"Semantic similarity: {similarity:.3f} → {'ACCEPT' if is_similar else 'REJECT'}")
        
        return is_similar, float(similarity)
    except Exception as e:
        logger.warning(f"Semantic similarity check failed: {e}")
        return False, 0.0


async def retry_with_backoff(
    func,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs
):
    """Retry async function with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {delay}s…"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"All {max_retries} attempts exhausted. Last error: {e}")
    return None

async def process_question(question: str):
    """
    Full RAG pipeline with 3 perceived speed optimizations:
    1. Prompt caching (in claude_agent.py)
    2. Instant opener (shown before API call)
    3. Speculative generation (started during transcription)
    """
    import time
    t_start = time.perf_counter()
    try:
        # Clear teleprompter for fresh response
        await broadcast_message({"type": "new_question"})

        # Classify (instant, rule-based)
        classification = pipeline.classifier._fallback_classify(question)

        t_classify = time.perf_counter()
        logger.info(
            f"Classified: type={classification['type']}, "
            f"budget={classification['budget']} "
            f"({(t_classify - t_start)*1000:.0f}ms)"
        )

        # ── Optimization #3: Check speculative generation ──
        g_task = await _speculative.get_gen_task()
        _, r_query = await _speculative.get_retrieval_task()
        g_tokens = await _speculative.get_tokens()
        
        is_similar, score = await is_similar_enough_semantic(r_query, question)
        
        if (
            g_task
            and g_task.done()
            and not g_task.cancelled()
            and g_tokens
            and is_similar
        ):
            # Speculative hit! Flush buffered tokens immediately
            logger.info(
                f"SPECULATIVE GEN HIT ⚡⚡ Flushing "
                f"{len(g_tokens)} buffered tokens"
            )
            full_response = list(g_tokens)
            for token in full_response:
                await broadcast_token(token)

            # Reset speculative state
            await _speculative.cancel_all()

            pipeline.total_responses += 1
            response_text = "".join(full_response)
            t_end = time.perf_counter()
            total_ms = (t_end - t_start) * 1000
            logger.info(
                f"SPECULATIVE response: {len(response_text)} chars "
                f"(total pipeline: {total_ms:.0f}ms) ⚡⚡"
            )

            # Save and log
            pipeline.conversation_history.append({
                "question": question,
                "type": classification["type"],
                "response": response_text,
                "timestamp": datetime.now().isoformat(),
            })
            _log_conversation(question, response_text, classification["type"])
            await broadcast_message({"type": "response_end"})
            return

        # Cancel any incomplete speculative generation
        await _speculative.cancel_gen()

        # ── Optimization #2: Instant opener ──
        opener = pipeline.response_agent.get_instant_opener(
            classification["type"]
        )
        logger.info(f"Instant opener: {opener.strip()}")

        # Check if we have speculative KB results ready
        kb_chunks = None
        r_task, _ = await _speculative.get_retrieval_task()
        if (
            r_task
            and r_task.done()
            and not r_task.cancelled()
        ):
            try:
                kb_chunks = r_task.result()
                logger.info(
                    f"SPECULATIVE HIT: Using pre-fetched "
                    f"{len(kb_chunks)} KB chunks ⚡"
                )
            except Exception:
                kb_chunks = None

        # If no speculative results, fetch now (with retry backoff)
        if kb_chunks is None:
            kb_chunks = await retry_with_backoff(
                pipeline.retriever.retrieve,
                query=question,
                question_type=classification["type"],
                max_retries=3
            )
            if kb_chunks is None:
                logger.error(f"Could not retrieve KB for: {question[:50]}")
                kb_chunks = []
            else:
                logger.info(f"Retrieved {len(kb_chunks)} KB chunks (fresh)")

                # Track embedding cost
                if pipeline.cost_tracker:
                    from src.cost_calculator import estimate_embedding_tokens
                    emb_tokens = estimate_embedding_tokens(question)
                    pipeline.cost_tracker.track_embedding(
                        tokens=emb_tokens,
                        question=question,
                    )

        # Reset speculative retrieval state
        await _speculative.clear_retrieval()

        t_retrieve = time.perf_counter()
        logger.info(
            f"KB ready ({(t_retrieve - t_start)*1000:.0f}ms from start)"
        )

        # Generate response with OpenAI GPT-4o-mini (streaming) + 30s timeout restriction
        full_response = []
        try:
            async with asyncio.timeout(30):
                async for token in pipeline.response_agent.generate(
                    question=question,
                    kb_chunks=kb_chunks,
                    question_type=classification["type"],
                    thinking_budget=classification["budget"],
                ):
                    full_response.append(token)
                    await broadcast_token(token)
        except asyncio.TimeoutError:
            logger.error(f"Response generation timeout for: {question[:50]}")
            error_msg = "[Response generation timeout - please try again]"
            await broadcast_message({
                "type": "error",
                "message": error_msg
            })
            return

        pipeline.total_responses += 1
        response_text = "".join(full_response)
        t_end = time.perf_counter()
        total_ms = (t_end - t_start) * 1000
        logger.info(
            f"Response generated: {len(response_text)} chars "
            f"(total pipeline: {total_ms:.0f}ms)"
        )

        # Track generation cost
        if pipeline.cost_tracker:
            from src.cost_calculator import estimate_tokens
            # Estimate tokens: system prompt + KB chunks + question + response
            system_prompt_tokens = 1024  # Average system prompt
            kb_tokens = sum(len(chunk) // 4 for chunk in kb_chunks) if kb_chunks else 0
            question_tokens = estimate_tokens(question)
            output_tokens = estimate_tokens(response_text)

            total_input_tokens = system_prompt_tokens + kb_tokens + question_tokens

            # Determine cache hits (simplified: check if this is a repeated type)
            cache_write_tokens = 0
            cache_read_tokens = 0
            # On first call of each type, write system prompt to cache
            # On subsequent calls, read from cache
            if hasattr(pipeline.response_agent, '_cache_stats'):
                type_calls = pipeline.response_agent._cache_stats.get("by_type", {}).get(classification["type"], {})
                if type_calls.get("calls", 0) > 1:
                    # Subsequent calls: use cache
                    cache_read_tokens = system_prompt_tokens
                    total_input_tokens -= system_prompt_tokens  # Cache read doesn't count as input
                elif type_calls.get("calls", 0) == 1:
                    # First call: write to cache
                    cache_write_tokens = system_prompt_tokens

            pipeline.cost_tracker.track_generation(
                input_tokens=total_input_tokens,
                output_tokens=output_tokens,
                question=question,
                cache_write_tokens=cache_write_tokens,
                cache_read_tokens=cache_read_tokens,
            )

        # Update Session Metrics & Prometheus
        try:
            prev_hits = getattr(pipeline.response_agent, '_last_cache_hits', 0)
            curr_hits = pipeline.response_agent._cache_stats.get("cache_hits", 0) if hasattr(pipeline.response_agent, '_cache_stats') else 0
            cache_hit = curr_hits > prev_hits
            if hasattr(pipeline.response_agent, '_cache_stats'):
                pipeline.response_agent._last_cache_hits = curr_hits

            qm = QuestionMetrics(
                question_text=question,
                question_type=classification["type"],
                duration_ms=total_ms,
                cache_hit=cache_hit,
                timestamp=datetime.now().isoformat()
            )
            if pipeline.session_metrics:
                pipeline.session_metrics.questions.append(qm)

            response_latency.observe(total_ms)
            question_count.inc()
            if pipeline.session_metrics:
                cache_hit_rate.set(pipeline.session_metrics.cache_hit_rate)
        except Exception as e:
            logger.warning(f"Failed to record Prometheus/Session metrics: {e}")

        # Save to conversation history
        pipeline.conversation_history.append({
            "question": question,
            "type": classification["type"],
            "response": response_text,
            "timestamp": datetime.now().isoformat(),
        })

        # Log conversation entry
        _log_conversation(question, response_text, classification["type"])

        # Send end-of-response marker
        await broadcast_message({"type": "response_end"})

    except Exception as e:
        logger.error(f"Pipeline error: {e}", exc_info=True)
        await broadcast_message({
            "type": "error",
            "message": str(e),
        })


# ---------------------------------------------------------------------------
# Conversation Logger
# ---------------------------------------------------------------------------
_session_log_path: Optional[Path] = None


def _log_conversation(question: str, response: str, q_type: str):
    """Append a Q&A pair to the session log file."""
    global _session_log_path
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)

    if _session_log_path is None:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
        _session_log_path = log_dir / f"interview_{ts}.md"
        with open(_session_log_path, "w", encoding="utf-8") as f:
            f.write(f"# Interview Log — {ts}\n\n")
        logger.info(f"Conversation log: {_session_log_path}")

    ts = datetime.now().strftime("%H:%M:%S")
    with open(_session_log_path, "a", encoding="utf-8") as f:
        f.write(f"## [{ts}] Question ({q_type})\n")
        f.write(f"> {question}\n\n")
        f.write(f"**Suggested Response:**\n{response}\n\n---\n\n")


# ---------------------------------------------------------------------------
# Teleprompter Subprocess
# ---------------------------------------------------------------------------
_teleprompter_proc: subprocess.Popen | None = None


def _launch_teleprompter() -> subprocess.Popen | None:
    """Launch the teleprompter overlay as a separate process."""
    try:
        bridge_path = (
            Path(__file__).parent / "src" / "teleprompter" / "ws_bridge.py"
        )
        proc = subprocess.Popen(
            [sys.executable, str(bridge_path)],
            cwd=str(Path(__file__).parent),
        )
        logger.info(f"Teleprompter launched (PID: {proc.pid})")
        return proc
    except Exception as e:
        logger.warning(f"Could not launch teleprompter: {e}")
        return None


def _stop_teleprompter():
    """Terminate the teleprompter subprocess."""
    global _teleprompter_proc
    if _teleprompter_proc and _teleprompter_proc.poll() is None:
        _teleprompter_proc.terminate()
        try:
            _teleprompter_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _teleprompter_proc.kill()
        logger.info("Teleprompter stopped")
    _teleprompter_proc = None


# ---------------------------------------------------------------------------
# Pipeline Lifecycle
# ---------------------------------------------------------------------------
async def start_pipeline():
    """Initialize and start all pipeline agents."""
    logger.info("=" * 60)
    logger.info("  INTERVIEW COPILOT v4.0 — Starting Pipeline")
    logger.info("  Architecture: OpenAI Realtime + gpt-4o-mini + Qt")
    logger.info("=" * 60)

    # Initialize Observability
    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    pipeline.session_metrics = SessionMetrics(
        session_id=session_id,
        start_time=datetime.now().isoformat(),
        questions=[]
    )
    pipeline.alert_manager = AlertManager()
    pipeline.cost_tracker = CostTracker(session_id=session_id)

    # Initialize agents
    pipeline.classifier = QuestionClassifier()
    pipeline.retriever = KnowledgeRetriever()
    pipeline.response_agent = OpenAIAgent()
    pipeline.question_filter = QuestionFilter()

    # Pre-warm API connections (TLS handshake, DNS, connection pool)
    # This eliminates cold-start latency on the first real question
    await pipeline.response_agent.warmup()

    # Initialize audio capture
    pipeline.audio_agent = AudioCaptureAgent()

    # Start audio capture
    await pipeline.audio_agent.start()

    # Start transcription for BOTH channels
    # Voicemeeter separates: mic → B2 (user/candidate), apps → B1 (interviewer)
    # Each channel gets its own OpenAI Realtime session

    # User channel (candidate — YOUR microphone via Voicemeeter B2)
    pipeline.transcriber_user = OpenAIRealtimeTranscriber(
        on_transcript=on_transcript,
        on_delta=on_delta,
        on_speech_event=on_speech_event,
    )
    await pipeline.transcriber_user.start(
        audio_queue=pipeline.audio_agent.user_queue,
        speaker="user",
    )

    # Interviewer channel (system audio via Voicemeeter B1)
    if pipeline.audio_agent._stream_int is not None:
        pipeline.transcriber_int = DeepgramTranscriber(
            on_transcript=on_transcript,
            on_delta=on_delta,
            on_speech_event=on_speech_event,
        )
        await pipeline.transcriber_int.start(
            audio_queue=pipeline.audio_agent.int_queue,
            speaker="interviewer",
        )
        logger.info("Dual-channel transcription active ✓")
        logger.info("  user (mic/B2) = candidate → saved as context")
        logger.info("  interviewer (B1) = questions → RAG → teleprompter")
    else:
        logger.warning(
            "No interviewer audio device found — "
            "only candidate mic will be transcribed. "
            "Configure Voicemeeter B1 for interviewer audio."
        )

    logger.info("Pipeline is RUNNING — ready for interview")
    logger.info(f"Question filter active: rejecting noise/fragments")
    logger.info(
        f"Teleprompter WebSocket at ws://{WS_HOST}:{WS_PORT}"
    )


async def stop_pipeline():
    """Gracefully stop all pipeline agents."""
    logger.info("Stopping pipeline…")

    if pipeline.transcriber_user:
        await pipeline.transcriber_user.stop()
    if pipeline.transcriber_int:
        await pipeline.transcriber_int.stop()
    if pipeline.audio_agent:
        await pipeline.audio_agent.stop()

    # Print stats
    if pipeline.question_filter:
        stats = pipeline.question_filter.stats
        logger.info(
            f"Question filter stats: "
            f"checked={stats['total_checked']}, "
            f"passed={stats['total_passed']}, "
            f"rejected={stats['total_rejected']}"
        )

    # Save metrics and check SLOs
    if pipeline.session_metrics and pipeline.session_metrics.questions:
        try:
            metrics_path = Path(__file__).parent / "logs" / f"metrics_{pipeline.session_metrics.session_id}.json"
            metrics_path.parent.mkdir(exist_ok=True)
            pipeline.session_metrics.save(metrics_path)
            logger.info(f"Session metrics saved to {metrics_path}")
            
            if pipeline.alert_manager:
                pipeline.alert_manager.check_metrics(pipeline.session_metrics)
        except Exception as e:
            logger.error(f"Error saving session metrics: {e}")

    # Save cost report
    if pipeline.cost_tracker:
        try:
            cost_report = pipeline.cost_tracker.get_session_report()
            cost_report.questions_processed = pipeline.total_questions
            cost_report.responses_generated = pipeline.total_responses
            pipeline.cost_tracker.save_report(cost_report)
            logger.info(f"Total Session Cost: {format_cost_for_display(cost_report.total_cost_usd)}")
        except Exception as e:
            logger.error(f"Error saving cost report: {e}")

    logger.info(
        f"Session totals: "
        f"questions={pipeline.total_questions}, "
        f"responses={pipeline.total_responses}"
    )
    logger.info("Pipeline stopped ✓")


async def monitor_teleprompter_health():
    """Monitor teleprompter subprocess health"""
    global _teleprompter_proc
    restart_attempts = 0
    MAX_RESTARTS = 3
    
    while True:
        await asyncio.sleep(30)  # Check every 30s
        
        if not _teleprompter_proc:
            continue
        
        poll_result = _teleprompter_proc.poll()
        if poll_result is not None:
            # Process has exited
            logger.error(
                f"Teleprompter process exited with code {poll_result}"
            )
            
            if restart_attempts < MAX_RESTARTS:
                logger.info(
                    f"Attempting restart {restart_attempts + 1}/{MAX_RESTARTS}…"
                )
                restart_attempts += 1
                _teleprompter_proc = _launch_teleprompter()
            else:
                logger.critical(
                    "Max teleprompter restart attempts reached. "
                    "UI will be unavailable."
                )
                break

# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
async def main():
    """Main entry point — run the interview copilot."""
    global _teleprompter_proc

    # Launch teleprompter UI
    _teleprompter_proc = _launch_teleprompter()

    # Start the local WebSocket server for teleprompter
    ws_server = await websockets.serve(
        ws_handler,
        WS_HOST,
        WS_PORT,
    )
    logger.info(f"WebSocket server ready on ws://{WS_HOST}:{WS_PORT}")

    # Brief delay for teleprompter to connect
    await asyncio.sleep(2)
    
    # Start Prometheus Metrics Server
    start_metrics_server(port=8000)

    # Start the pipeline
    await start_pipeline()
    
    # Start health monitor
    asyncio.create_task(monitor_teleprompter_health())

    # Run until interrupted
    try:
        logger.info(
            "\n" + "=" * 60 + "\n"
            "  Press Ctrl+C to stop the interview copilot\n"
            + "=" * 60
        )
        await asyncio.Future()  # Block forever
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("\nShutting down…")
    finally:
        await stop_pipeline()
        ws_server.close()
        await ws_server.wait_closed()
        _stop_teleprompter()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


