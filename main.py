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
import os
import random
import re
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
from src.response.fallback_manager import FallbackResponseManager
from src.response.interview_memory import InterviewMemory
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
FRAGMENT_HOLD_MIN_S = max(0.4, float(os.getenv("FRAGMENT_HOLD_MIN_S", "0.8")))
FRAGMENT_HOLD_MAX_S = max(
    FRAGMENT_HOLD_MIN_S,
    float(os.getenv("FRAGMENT_HOLD_MAX_S", "1.2")),
)


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
        self.interview_memory: Optional[InterviewMemory] = None

        # Connected teleprompter clients
        self.ws_clients: set = set()

        # Conversation history for context
        self.conversation_history: list[dict] = []
        
        # Observability
        self.session_metrics: Optional[SessionMetrics] = None
        self.alert_manager: Optional[AlertManager] = None
        self.cost_tracker: Optional[CostTracker] = None

        # Concurrency control
        self.active_generation_task: Optional[asyncio.Task] = None

        # Fragment gate for potentially truncated interviewer questions
        self.pending_fragment_task: Optional[asyncio.Task] = None
        self.pending_fragment_payload: Optional[dict] = None
        self.pending_fragment_nonce: int = 0


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


async def publish_saldo_update():
    """Broadcast real-time balance + fuel gauge to UI clients."""
    if not pipeline.cost_tracker:
        return
    try:
        snapshot = pipeline.cost_tracker.get_saldo_snapshot()
        await broadcast_message({"type": "saldo_update", "data": snapshot})

        fuel = snapshot.get("fuel_gauge", {})
        providers = snapshot.get("providers", {})
        openai = providers.get("openai", {})
        deepgram = providers.get("deepgram", {})
        anthropic = providers.get("anthropic", {})
        logger.info(
            "SALDO | "
            f"OpenAI=${openai.get('remaining_usd', 0):.4f} | "
            f"Deepgram=${deepgram.get('remaining_usd', 0):.4f} | "
            f"Anthropic=${anthropic.get('remaining_usd', 0):.4f} | "
            f"fuel={fuel.get('human_readable_until_any_depletion')}"
        )
    except Exception as e:
        logger.warning(f"Could not publish saldo update: {e}")


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


def _next_fragment_hold_seconds() -> float:
    if abs(FRAGMENT_HOLD_MAX_S - FRAGMENT_HOLD_MIN_S) < 1e-6:
        return FRAGMENT_HOLD_MIN_S
    return random.uniform(FRAGMENT_HOLD_MIN_S, FRAGMENT_HOLD_MAX_S)


async def _cancel_pending_fragment():
    """Cancel pending fragment hold task and clear payload."""
    task = pipeline.pending_fragment_task
    pipeline.pending_fragment_task = None
    pipeline.pending_fragment_payload = None
    if task and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


async def _emit_fragment_clarification(payload: dict):
    """
    Provide a safe clarification response when only a partial question
    was captured after hold timeout.
    """
    raw_question = str(payload.get("raw_question", "")).strip()
    response_text = (
        "I want to answer that precisely, but I only caught part of the question. "
        "Could you repeat it from the start?"
    )

    logger.info(
        "Fragment gate fallback triggered "
        f"(reason={payload.get('fragment_reason', 'unknown')}, "
        f"hold={payload.get('hold_seconds', 0):.2f}s)"
    )

    pipeline.total_questions += 1
    pipeline.total_responses += 1

    await broadcast_message({"type": "new_question"})
    for token in re.findall(r"\S+\s*", response_text):
        await broadcast_token(token)

    pipeline.conversation_history.append({
        "question": raw_question,
        "type": "fragment_clarification",
        "provider": "system_fragment_gate",
        "response": response_text,
        "raw_question": raw_question,
        "normalized_question": payload.get("normalized_question", raw_question),
        "fragment_reason": payload.get("fragment_reason", "unknown"),
        "timestamp": datetime.now().isoformat(),
    })
    _log_conversation(
        raw_question,
        response_text,
        "fragment_clarification",
        metadata={
            "raw_question": raw_question,
            "normalized_question": payload.get(
                "normalized_question",
                raw_question,
            ),
            "classification_reason": payload.get("analysis_reason", "fragment_gate"),
            "fragment_risk": True,
            "fragment_reason": payload.get("fragment_reason", "unknown"),
            "speculative_used": False,
            "validation": {
                "is_valid": True,
                "attempts": 0,
                "reasons": [],
            },
            "kb_evidence": [],
        },
    )
    await broadcast_message({"type": "response_end"})


async def _fragment_hold_worker(nonce: int, hold_seconds: float):
    """Wait briefly for continuation, otherwise emit clarification fallback."""
    try:
        await asyncio.sleep(hold_seconds)
        payload = pipeline.pending_fragment_payload
        if not payload:
            return
        if int(payload.get("nonce", -1)) != nonce:
            return
        pipeline.pending_fragment_payload = None
        pipeline.pending_fragment_task = None
        await _emit_fragment_clarification(payload)
    except asyncio.CancelledError:
        logger.debug("Fragment hold cancelled")


async def _schedule_fragment_gate(
    raw_question: str,
    normalized_question: str,
    analysis: dict,
):
    """
    Hold likely truncated questions briefly to allow a continuation turn
    to arrive before triggering RAG generation.
    """
    await _cancel_pending_fragment()
    hold_seconds = _next_fragment_hold_seconds()
    pipeline.pending_fragment_nonce += 1
    nonce = pipeline.pending_fragment_nonce
    pipeline.pending_fragment_payload = {
        "nonce": nonce,
        "raw_question": raw_question,
        "normalized_question": normalized_question,
        "analysis_reason": analysis.get("reason", "unknown"),
        "fragment_reason": analysis.get("fragment_reason", "unknown"),
        "hold_seconds": hold_seconds,
        "created_at": datetime.now().isoformat(),
    }
    pipeline.pending_fragment_task = asyncio.create_task(
        _fragment_hold_worker(nonce, hold_seconds)
    )
    logger.info(
        "Fragment gate armed "
        f"(hold={hold_seconds:.2f}s, reason={analysis.get('fragment_reason')}, "
        f"text='{normalized_question[:80]}')"
    )


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
        candidate_text = text
        if pipeline.pending_fragment_payload:
            pending = pipeline.pending_fragment_payload
            candidate_text = (
                f"{pending.get('raw_question', '').strip()} {text.strip()}"
            ).strip()
            logger.info(
                "Merging pending fragment with new interviewer turn "
                f"(nonce={pending.get('nonce')})"
            )
            await _cancel_pending_fragment()

        analysis = pipeline.question_filter.analyze_interview_turn(candidate_text)

        # --- INTERVIEWER: evaluate and potentially trigger RAG ---
        if analysis.get("is_question", False):
            normalized_question = str(
                analysis.get("normalized_text", candidate_text)
            ).strip() or candidate_text

            if analysis.get("fragment_risk", False):
                await _schedule_fragment_gate(
                    raw_question=candidate_text,
                    normalized_question=normalized_question,
                    analysis=analysis,
                )
                return

            pipeline.total_questions += 1

            # Cancel any previous question processing task
            if pipeline.active_generation_task and not pipeline.active_generation_task.done():
                logger.info("Interrupting previous generation for new question.")
                pipeline.active_generation_task.cancel()
                
            # Start answering the new question
            question_meta = {
                "filter_reason": analysis.get("reason", "unknown"),
                "fragment_risk": bool(analysis.get("fragment_risk", False)),
                "fragment_reason": analysis.get("fragment_reason", "none"),
                "normalized_question": normalized_question,
                "raw_question": candidate_text,
            }
            pipeline.active_generation_task = asyncio.create_task(
                process_question(
                    normalized_question,
                    raw_question=candidate_text,
                    question_meta=question_meta,
                )
            )
        else:
            logger.info(
                "Interviewer noise skipped "
                f"(reason={analysis.get('reason', 'unknown')}): "
                f"{candidate_text[:60]}…"
            )

    elif speaker == "user":
        # --- CANDIDATE: save as context (what YOU already said) ---
        pipeline.conversation_history.append({
            "speaker": "candidate",
            "text": text,
            "timestamp": datetime.now().isoformat(),
        })
        if pipeline.interview_memory:
            pipeline.interview_memory.ingest_candidate_utterance(text)
        logger.info(f"Candidate speech saved as context ({len(text)} chars)")


def _recent_response_context(
    max_items: int = 3
) -> tuple[list[str], list[str], list[str]]:
    """
    Return recent interviewer questions and generated answers for
    anti-repetition guidance in the response prompt.
    """
    qa_items = [
        entry for entry in pipeline.conversation_history
        if "question" in entry and "response" in entry
    ]
    if not qa_items:
        return [], [], []

    tail = qa_items[-max_items:]
    recent_questions = [str(item.get("question", "")) for item in tail]
    recent_responses = [str(item.get("response", "")) for item in tail]
    recent_types = [str(item.get("type", "")) for item in tail]
    return recent_questions, recent_responses, recent_types


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
        (
            recent_questions,
            recent_responses,
            recent_types,
        ) = _recent_response_context(
            max_items=2
        )
        memory_context = (
            pipeline.interview_memory.build_prompt_context(
                question=delta_text,
                question_type=classification["type"],
            )
            if pipeline.interview_memory
            else None
        )

        # Generate speculatively (tokens buffered, not broadcast yet)
        async for token in pipeline.response_agent.generate(
            question=delta_text,
            kb_chunks=kb_chunks,
            question_type=classification["type"],
            recent_questions=recent_questions,
            recent_responses=recent_responses,
            recent_question_types=recent_types,
            memory_context=memory_context,
        ):
            await _speculative.add_token(token)
    except asyncio.CancelledError:
        logger.info("Speculative generation cancelled")
    except Exception as e:
        logger.warning(f"Speculative generation error: {e}")


def _normalize_for_similarity(text: str) -> list[str]:
    cleaned = (text or "").lower()
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned.split()


def _lexical_similarity(delta: str, final: str) -> float:
    a = _normalize_for_similarity(delta)
    b = _normalize_for_similarity(final)
    if not a or not b:
        return 0.0

    # Blend overlap + ordered similarity to reduce embedding calls.
    set_a = set(a)
    set_b = set(b)
    jaccard = len(set_a & set_b) / max(1, len(set_a | set_b))
    ordered = sum(1 for x, y in zip(a, b) if x == y) / max(1, min(len(a), len(b)))
    return (jaccard * 0.70) + (ordered * 0.30)


async def is_similar_enough_semantic(delta: str, final: str) -> tuple[bool, float]:
    """Check semantic similarity between delta and final transcript"""
    if not delta or not final:
        return False, 0.0

    lexical_score = _lexical_similarity(delta, final)
    if lexical_score >= 0.68:
        logger.info(
            f"Similarity fast-path lexical={lexical_score:.3f} → ACCEPT"
        )
        return True, lexical_score
    if lexical_score <= 0.30:
        logger.info(
            f"Similarity fast-path lexical={lexical_score:.3f} → REJECT"
        )
        return False, lexical_score

    try:
        from openai import AsyncOpenAI
        import numpy as np

        client = AsyncOpenAI()
        embeddings = await asyncio.wait_for(
            client.embeddings.create(
                model="text-embedding-3-small",
                input=[delta, final]
            ),
            timeout=0.35,
        )
        
        delta_emb = np.array(embeddings.data[0].embedding, dtype=np.float32)
        final_emb = np.array(embeddings.data[1].embedding, dtype=np.float32)

        # Cosine similarity
        dot_product = float(np.dot(delta_emb, final_emb))
        norm_product = float(np.linalg.norm(delta_emb)) * float(np.linalg.norm(final_emb))
        similarity = float(dot_product / norm_product)

        is_similar = similarity > 0.80
        logger.info(
            f"Semantic similarity embedding={similarity:.3f} "
            f"(lexical={lexical_score:.3f}) → "
            f"{'ACCEPT' if is_similar else 'REJECT'}"
        )

        return is_similar, float(similarity)
    except asyncio.TimeoutError:
        logger.info(
            "Semantic similarity timeout â†’ fallback lexical REJECT "
            f"(lexical={lexical_score:.3f})"
        )
        return False, lexical_score
    except Exception as e:
        logger.warning(f"Semantic similarity check failed: {e}")
        return False, lexical_score


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

async def _broadcast_text_as_tokens(text: str):
    """Broadcast a full response in token-like chunks for teleprompter display."""
    for token in re.findall(r"\S+\s*|\n+", text):
        await broadcast_token(token)


async def process_question(
    question: str,
    raw_question: Optional[str] = None,
    question_meta: Optional[dict] = None,
):
    """
    Full RAG pipeline with fragment-safe metadata, validated generation,
    and RAG evidence tracing.
    """
    import time

    t_start = time.perf_counter()
    question_meta = question_meta or {}
    raw_question = (raw_question or question).strip()
    normalized_question = (
        pipeline.question_filter.normalize_question_text(question)
        if pipeline.question_filter
        else question
    ).strip() or question.strip()

    try:
        # Clear teleprompter for fresh response
        await broadcast_message({"type": "new_question"})

        # Classify (instant, rule-based)
        classification = pipeline.classifier._fallback_classify(normalized_question)
        t_classify = time.perf_counter()
        logger.info(
            f"Classified: type={classification['type']}, "
            f"budget={classification['budget']} "
            f"({(t_classify - t_start)*1000:.0f}ms)"
        )

        # ── Optimization #3: speculative generation gate ──
        g_task = await _speculative.get_gen_task()
        r_task, r_query = await _speculative.get_retrieval_task()
        g_tokens = await _speculative.get_tokens()

        response_text: Optional[str] = None
        validation_report: Optional[dict] = None
        kb_chunks: list[str] = []
        kb_evidence: list[dict] = []
        used_speculative = False

        is_similar = False
        if r_query and g_task:
            try:
                is_similar, _ = await asyncio.wait_for(
                    is_similar_enough_semantic(r_query, normalized_question),
                    timeout=0.28,
                )
            except asyncio.TimeoutError:
                logger.info(
                    "Similarity gate timeout → skip speculative hit "
                    f"for question='{normalized_question[:50]}...'"
                )
                is_similar = False

        if is_similar and g_task and not g_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(g_task), timeout=0.35)
            except asyncio.TimeoutError:
                pass
            g_tokens = await _speculative.get_tokens()

        if (
            g_task
            and g_task.done()
            and not g_task.cancelled()
            and g_tokens
            and is_similar
        ):
            spec_response = "".join(g_tokens)
            spec_kb_chunks = []
            if r_task and r_task.done() and not r_task.cancelled():
                try:
                    spec_kb_chunks = list(r_task.result() or [])
                except Exception:
                    spec_kb_chunks = []

            spec_validation = pipeline.response_agent.validate_generated_response(
                response_text=spec_response,
                question_type=classification["type"],
                kb_chunks=spec_kb_chunks,
            )
            if spec_validation["is_valid"]:
                logger.info(
                    "SPECULATIVE GEN HIT ⚡⚡ "
                    f"(tokens={len(g_tokens)}, kb={len(spec_kb_chunks)})"
                )
                response_text = spec_response
                validation_report = spec_validation
                kb_chunks = spec_kb_chunks
                used_speculative = True
            else:
                logger.info(
                    "Speculative response rejected by validator: "
                    f"{spec_validation['reasons']}"
                )

        # Cancel stale speculative generation if we need to generate fresh.
        if response_text is None:
            await _speculative.cancel_gen()

        # ── Retrieve KB chunks (or evidence for speculative chunks) ──
        if response_text is None:
            # Check if speculative retrieval is already ready.
            if (
                r_task
                and r_task.done()
                and not r_task.cancelled()
            ):
                try:
                    kb_chunks = list(r_task.result() or [])
                    logger.info(
                        f"SPECULATIVE HIT: Using pre-fetched {len(kb_chunks)} KB chunks ⚡"
                    )
                except Exception:
                    kb_chunks = []

            if not kb_chunks:
                retrieval_bundle = await retry_with_backoff(
                    pipeline.retriever.retrieve_with_evidence,
                    query=normalized_question,
                    question_type=classification["type"],
                    max_retries=3,
                )
                if retrieval_bundle is None:
                    logger.error(
                        f"Could not retrieve KB for: {normalized_question[:50]}"
                    )
                    kb_chunks = []
                    kb_evidence = []
                else:
                    kb_chunks = list(retrieval_bundle.get("chunks", []))
                    kb_evidence = list(retrieval_bundle.get("evidence", []))
                    logger.info(f"Retrieved {len(kb_chunks)} KB chunks (fresh)")

                    # Track embedding cost for fresh retrieval only.
                    if pipeline.cost_tracker:
                        from src.cost_calculator import estimate_embedding_tokens
                        emb_tokens = estimate_embedding_tokens(normalized_question)
                        pipeline.cost_tracker.track_embedding(
                            tokens=emb_tokens,
                            question=normalized_question,
                        )

            # Build evidence if chunks came from speculative cache path.
            if kb_chunks and not kb_evidence:
                metadata_rows = await pipeline.retriever.retrieve_with_metadata(
                    query=normalized_question,
                    question_type=classification["type"],
                    top_k=max(3, len(kb_chunks) * 3),
                )
                kb_evidence = pipeline.retriever._build_evidence_for_chunks(
                    kb_chunks,
                    metadata_rows,
                )

        else:
            if kb_chunks and not kb_evidence:
                metadata_rows = await pipeline.retriever.retrieve_with_metadata(
                    query=normalized_question,
                    question_type=classification["type"],
                    top_k=max(3, len(kb_chunks) * 3),
                )
                kb_evidence = pipeline.retriever._build_evidence_for_chunks(
                    kb_chunks,
                    metadata_rows,
                )

        await _speculative.clear_retrieval()
        t_retrieve = time.perf_counter()
        logger.info(f"KB ready ({(t_retrieve - t_start)*1000:.0f}ms from start)")

        # ── Generate validated response when speculative response isn't used ──
        if response_text is None:
            (
                recent_questions,
                recent_responses,
                recent_types,
            ) = _recent_response_context(max_items=3)
            memory_context = (
                pipeline.interview_memory.build_prompt_context(
                    question=normalized_question,
                    question_type=classification["type"],
                )
                if pipeline.interview_memory
                else None
            )

            try:
                async with asyncio.timeout(45):
                    response_text, validation_report = (
                        await pipeline.response_agent.generate_full_with_validation(
                            question=normalized_question,
                            kb_chunks=kb_chunks,
                            question_type=classification["type"],
                            thinking_budget=classification["budget"],
                            recent_questions=recent_questions,
                            recent_responses=recent_responses,
                            recent_question_types=recent_types,
                            memory_context=memory_context,
                        )
                    )
            except asyncio.TimeoutError:
                logger.error(
                    f"Response generation timeout for: {normalized_question[:50]}"
                )
                await broadcast_message({
                    "type": "error",
                    "message": "[Response generation timeout - please try again]",
                })
                return

        response_text = response_text or ""
        validation_report = validation_report or {
            "is_valid": True,
            "reasons": [],
            "attempts": 1,
            "retried": False,
        }

        # Send response to teleprompter once final text passes validation gate.
        await _broadcast_text_as_tokens(response_text)

        pipeline.total_responses += 1
        t_end = time.perf_counter()
        total_ms = (t_end - t_start) * 1000
        logger.info(
            f"Response generated: {len(response_text)} chars "
            f"(total pipeline: {total_ms:.0f}ms, "
            f"validated={validation_report.get('is_valid')}, "
            f"speculative={used_speculative})"
        )

        # Track generation cost
        if pipeline.cost_tracker:
            from src.cost_calculator import estimate_tokens

            system_prompt_tokens = getattr(
                pipeline.response_agent,
                "system_prompt_token_estimate",
                1024,
            )
            pricing_model = getattr(
                pipeline.response_agent,
                "pricing_model",
                "openai_gpt_4o_mini",
            )
            supports_prompt_cache = bool(
                getattr(pipeline.response_agent, "supports_prompt_cache", False)
            )

            kb_tokens = sum(len(chunk) // 4 for chunk in kb_chunks) if kb_chunks else 0
            question_tokens = estimate_tokens(normalized_question)
            output_tokens = estimate_tokens(response_text)
            total_input_tokens = system_prompt_tokens + kb_tokens + question_tokens

            cache_write_tokens = 0
            cache_read_tokens = 0
            if supports_prompt_cache and hasattr(pipeline.response_agent, "_cache_stats"):
                type_calls = pipeline.response_agent._cache_stats.get(
                    "by_type",
                    {},
                ).get(classification["type"], {})
                if type_calls.get("calls", 0) > 1:
                    cache_read_tokens = system_prompt_tokens
                    total_input_tokens -= system_prompt_tokens
                elif type_calls.get("calls", 0) == 1:
                    cache_write_tokens = system_prompt_tokens

            pipeline.cost_tracker.track_generation(
                input_tokens=total_input_tokens,
                output_tokens=output_tokens,
                question=normalized_question,
                api_name=pricing_model,
                cache_write_tokens=cache_write_tokens,
                cache_read_tokens=cache_read_tokens,
            )
            await publish_saldo_update()

        # Update Session Metrics & Prometheus
        try:
            prev_hits = getattr(pipeline.response_agent, "_last_cache_hits", 0)
            curr_hits = (
                pipeline.response_agent._cache_stats.get("cache_hits", 0)
                if hasattr(pipeline.response_agent, "_cache_stats")
                else 0
            )
            cache_hit = curr_hits > prev_hits
            if hasattr(pipeline.response_agent, "_cache_stats"):
                pipeline.response_agent._last_cache_hits = curr_hits

            qm = QuestionMetrics(
                question_text=normalized_question,
                question_type=classification["type"],
                duration_ms=total_ms,
                cache_hit=cache_hit,
                timestamp=datetime.now().isoformat(),
            )
            if pipeline.session_metrics:
                pipeline.session_metrics.questions.append(qm)

            response_latency.observe(total_ms)
            question_count.inc()
            if pipeline.session_metrics:
                cache_hit_rate.set(pipeline.session_metrics.cache_hit_rate)
        except Exception as e:
            logger.warning(f"Failed to record Prometheus/Session metrics: {e}")

        history_entry = {
            "question": normalized_question,
            "raw_question": raw_question,
            "normalized_question": normalized_question,
            "type": classification["type"],
            "classification_reason": question_meta.get("filter_reason", "unknown"),
            "fragment_risk": bool(question_meta.get("fragment_risk", False)),
            "fragment_reason": question_meta.get("fragment_reason", "none"),
            "provider": getattr(
                pipeline.response_agent,
                "last_provider_used",
                "openai",
            ),
            "response": response_text,
            "validation": validation_report,
            "kb_evidence": kb_evidence[:8],
            "speculative_used": used_speculative,
            "timestamp": datetime.now().isoformat(),
        }
        pipeline.conversation_history.append(history_entry)

        if pipeline.interview_memory:
            pipeline.interview_memory.ingest_generated_response(
                question=normalized_question,
                question_type=classification["type"],
                response=response_text,
                kb_chunks=kb_chunks,
            )

        _log_conversation(
            normalized_question,
            response_text,
            classification["type"],
            metadata={
                "raw_question": raw_question,
                "normalized_question": normalized_question,
                "classification_reason": question_meta.get("filter_reason", "unknown"),
                "fragment_risk": bool(question_meta.get("fragment_risk", False)),
                "fragment_reason": question_meta.get("fragment_reason", "none"),
                "validation": validation_report,
                "kb_evidence": kb_evidence[:8],
                "speculative_used": used_speculative,
            },
        )

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


def _log_conversation(
    question: str,
    response: str,
    q_type: str,
    metadata: Optional[dict] = None,
):
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
    metadata = metadata or {}
    with open(_session_log_path, "a", encoding="utf-8") as f:
        f.write(f"## [{ts}] Question ({q_type})\n")
        f.write(f"> {question}\n\n")
        raw_question = str(metadata.get("raw_question", "")).strip()
        if raw_question and raw_question != question:
            f.write(f"**Raw Question:** {raw_question}\n\n")

        if metadata:
            f.write("**Diagnostics:**\n")
            normalized_question = str(
                metadata.get("normalized_question", "")
            ).strip()
            if normalized_question:
                f.write(f"- normalized_question: {normalized_question}\n")
            if "classification_reason" in metadata:
                f.write(
                    f"- classification_reason: "
                    f"{metadata.get('classification_reason')}\n"
                )
            if "fragment_risk" in metadata:
                f.write(f"- fragment_risk: {metadata.get('fragment_risk')}\n")
            if "fragment_reason" in metadata:
                f.write(
                    f"- fragment_reason: "
                    f"{metadata.get('fragment_reason')}\n"
                )
            if "speculative_used" in metadata:
                f.write(
                    f"- speculative_used: "
                    f"{metadata.get('speculative_used')}\n"
                )
            validation = metadata.get("validation")
            if isinstance(validation, dict):
                f.write(
                    f"- validation_ok: {validation.get('is_valid')}\n"
                )
                if validation.get("reasons"):
                    f.write(
                        f"- validation_reasons: "
                        f"{', '.join(validation.get('reasons', []))}\n"
                    )
                f.write(
                    f"- generation_attempts: {validation.get('attempts', 1)}\n"
                )
            kb_evidence = metadata.get("kb_evidence", [])
            if kb_evidence:
                f.write("- kb_evidence:\n")
                for item in kb_evidence[:8]:
                    source = item.get("source", "unknown")
                    topic = item.get("topic", "unknown")
                    dist = item.get("distance", -1.0)
                    snippet = str(item.get("snippet", "")).strip()
                    f.write(
                        f"  - {source} | topic={topic} | dist={dist:.4f} | "
                        f"snippet={snippet}\n"
                    )
            f.write("\n")

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
    logger.info("  Architecture: OpenAI Realtime + Multi-Provider LLM + Qt")
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
    pipeline.response_agent = FallbackResponseManager()
    pipeline.question_filter = QuestionFilter()
    pipeline.interview_memory = InterviewMemory()

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
            await publish_saldo_update()
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


