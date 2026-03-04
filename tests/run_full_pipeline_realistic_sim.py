"""
Full realistic pipeline simulation (synthetic + API).

Covers:
- interviewer/candidate transcript flow
- question filtering and classification
- retrieval + response generation
- speculative prefetch hook path
- WebSocket bridge + teleprompter token stream
- candidate "reading" directly from teleprompter text
- adversarial reading profiles and latency SLA metrics
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import websockets

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import (
    pipeline,
    ws_handler,
    on_delta,
    on_speech_event,
    on_transcript,
)
from src.cost_calculator import CostTracker
from src.knowledge.classifier import QuestionClassifier
from src.knowledge.question_filter import QuestionFilter
from src.knowledge.retrieval import KnowledgeRetriever
from src.response.openai_agent import OpenAIAgent
from src.teleprompter.progress_tracker import estimate_char_progress
from src.teleprompter.ws_bridge import TeleprompterBridge
from tests.stress_test_orchestrator import (
    SyntheticKnowledgeRetriever,
    SyntheticResponseAgent,
)


READING_PROFILES_BY_DIFFICULTY = {
    "standard": ["verbatim", "verbatim", "light_noise", "paraphrase"],
    "hard": ["light_noise", "paraphrase", "omission", "reorder", "paraphrase"],
    "extreme": ["paraphrase", "omission", "reorder", "adversarial_mix", "adversarial_mix"],
}

SYNONYM_MAP = {
    "manage": "handle",
    "managed": "handled",
    "quickly": "fast",
    "significant": "major",
    "difficult": "hard",
    "colleague": "coworker",
    "project": "initiative",
    "team": "group",
    "results": "outcomes",
    "pressure": "urgency",
    "influence": "persuade",
    "decision": "call",
    "leadership": "leaders",
    "experience": "background",
    "shared": "provided",
    "notes": "documentation",
    "process": "workflow",
    "improved": "increased",
    "understand": "grasp",
    "transition": "change",
}

FILLER_WORDS = ["well", "you know", "to be honest", "in practice"]


@dataclass
class ResponseReadMetrics:
    question: str
    profile: str
    response_len: int
    final_read_index: int
    final_read_ratio: float
    monotonic_ok: bool
    premature_end_jump: bool
    checkpoints: list[dict[str, float]]
    progress_update_latencies_ms: list[float]


class DummyTeleprompter:
    def __init__(self):
        self._current_text = ""
        self._read_char_index = 0
        self.progress_trace: list[int] = []
        self.progress_update_times: list[float] = []
        self.token_times: list[float] = []

    def append_text(self, token: str):
        self._current_text += token
        self.token_times.append(time.perf_counter())

    def clear_text(self):
        self._current_text = ""
        self._read_char_index = 0
        self.progress_trace = []
        self.progress_update_times = []
        self.token_times = []

    def update_candidate_progress(
        self,
        spoken_text: str,
        final_pass: bool = False,
    ):
        progress = estimate_char_progress(
            script_text=self._current_text,
            spoken_text=spoken_text,
            current_progress=self._read_char_index,
            final_pass=final_pass,
        )
        self._read_char_index = max(self._read_char_index, progress)
        self.progress_trace.append(self._read_char_index)
        self.progress_update_times.append(time.perf_counter())


class FakeInterviewerTranscriber:
    def __init__(self):
        self._buffer = ""

    def set_live_buffer(self, text: str):
        self._buffer = text

    def get_live_buffer(self) -> str:
        return self._buffer


class SyntheticResponseAgentAdapter(SyntheticResponseAgent):
    """
    Adapter to match the streaming interface expected by main.process_question.
    """

    def __init__(self):
        super().__init__()
        self._instant_agent = OpenAIAgent(api_key="synthetic")
        self._cache_stats = {"total_calls": 0, "cache_hits": 0, "by_type": {}}
        self.pricing_model = "synthetic_openai_gpt_4o_mini"

    async def warmup(self):
        return

    def get_instant_opener(self, question_type: str) -> str:
        return self._instant_agent.get_instant_opener(question_type)

    async def generate(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
        recent_questions: Optional[list[str]] = None,
        recent_responses: Optional[list[str]] = None,
        recent_question_types: Optional[list[str]] = None,
        memory_context: Optional[str] = None,
    ):
        if question_type not in self._cache_stats["by_type"]:
            self._cache_stats["by_type"][question_type] = {"calls": 0, "hits": 0}
        self._cache_stats["total_calls"] += 1
        self._cache_stats["by_type"][question_type]["calls"] += 1

        text = await self.generate_full(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
            thinking_budget=thinking_budget,
            recent_questions=recent_questions,
            recent_responses=recent_responses,
            recent_question_types=recent_question_types,
        )
        # Chunk by words to simulate token streaming.
        words = text.split()
        for idx, word in enumerate(words):
            suffix = " " if idx < len(words) - 1 else ""
            yield word + suffix


INTERACTION_SCRIPT = [
    {"speaker": "interviewer", "kind": "statement", "text": "Let's restart the interview process."},
    {"speaker": "interviewer", "kind": "question", "text": "Tell me about a time when you had to resolve a significant conflict with a colleague or team member. What steps did you take, and what was the outcome?"},
    {"speaker": "candidate", "kind": "statement", "text": "I'm ready for another question, please go ahead."},
    {"speaker": "interviewer", "kind": "question", "text": "Can you tell me about a time when you had to influence a decision at a higher level of leadership, without formal authority? How did you approach it?"},
    {"speaker": "candidate", "kind": "statement", "text": "We can continue with the interview. Please go ahead with the next question."},
    {"speaker": "interviewer", "kind": "question", "text": "Tell me about a time when you had to lead a project or initiative where you lacked prior experience. How did you build credibility and drive results?"},
    {"speaker": "candidate", "kind": "statement", "text": "Could you share how success is measured in the first 90 days for this role?"},
    {"speaker": "interviewer", "kind": "statement", "text": "Great question. We focus on ramp-up speed, quality consistency, and independent ownership in the first quarter."},
    {"speaker": "candidate", "kind": "statement", "text": "How is the compensation band structured for this role and location?"},
    {"speaker": "interviewer", "kind": "statement", "text": "Compensation depends on level and location, and includes base pay plus performance components."},
    {"speaker": "interviewer", "kind": "question", "text": "Before we close, what salary range are you targeting for this position?"},
    {"speaker": "interviewer", "kind": "closing", "text": "Thanks for your time today. We appreciate the conversation and will follow up with next steps."},
]


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return float(ordered[rank])


def _latency_stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "count": 0,
            "avg": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "max": 0.0,
        }
    return {
        "count": len(values),
        "avg": round(statistics.mean(values), 3),
        "p50": round(_percentile(values, 50), 3),
        "p95": round(_percentile(values, 95), 3),
        "max": round(max(values), 3),
    }


def _pick_profile(difficulty: str, rng: random.Random) -> str:
    candidates = READING_PROFILES_BY_DIFFICULTY.get(
        difficulty,
        READING_PROFILES_BY_DIFFICULTY["standard"],
    )
    return rng.choice(candidates)


def _split_token(token: str) -> tuple[str, str, str]:
    start = 0
    while start < len(token) and not token[start].isalpha():
        start += 1
    end = len(token)
    while end > start and not token[end - 1].isalpha():
        end -= 1
    return token[:start], token[start:end], token[end:]


def _replace_with_synonym(token: str) -> str:
    prefix, core, suffix = _split_token(token)
    if not core:
        return token

    replacement = SYNONYM_MAP.get(core.lower())
    if not replacement:
        return token

    if core[0].isupper():
        replacement = replacement.capitalize()
    return f"{prefix}{replacement}{suffix}"


def _mutate_words(words: list[str], profile: str, rng: random.Random) -> list[str]:
    if profile == "verbatim":
        return list(words)

    if profile == "light_noise":
        replace_prob = 0.08
        drop_prob = 0.03
        filler_prob = 0.03
        reorder_prob = 0.0
    elif profile == "paraphrase":
        replace_prob = 0.20
        drop_prob = 0.06
        filler_prob = 0.05
        reorder_prob = 0.0
    elif profile == "omission":
        replace_prob = 0.10
        drop_prob = 0.20
        filler_prob = 0.02
        reorder_prob = 0.0
    elif profile == "reorder":
        replace_prob = 0.08
        drop_prob = 0.08
        filler_prob = 0.03
        reorder_prob = 0.25
    else:  # adversarial_mix
        replace_prob = 0.30
        drop_prob = 0.24
        filler_prob = 0.08
        reorder_prob = 0.30

    mutated: list[str] = []
    for word in words:
        current = word
        if rng.random() < replace_prob:
            current = _replace_with_synonym(current)

        _, core, _ = _split_token(current)
        should_drop = (
            rng.random() < drop_prob
            and len(core) > 3
            and len(mutated) > 2
        )
        if should_drop:
            continue

        mutated.append(current)
        if rng.random() < filler_prob:
            mutated.append(rng.choice(FILLER_WORDS))

    if not mutated:
        return [words[0]] if words else []

    if reorder_prob > 0 and len(mutated) >= 4:
        idx = 0
        while idx < len(mutated) - 1:
            if rng.random() < reorder_prob:
                mutated[idx], mutated[idx + 1] = mutated[idx + 1], mutated[idx]
                idx += 2
            else:
                idx += 1

    return mutated


async def _wait_until(predicate, timeout_s: float = 40.0, poll_s: float = 0.05) -> bool:
    start = time.perf_counter()
    while (time.perf_counter() - start) < timeout_s:
        if predicate():
            return True
        await asyncio.sleep(poll_s)
    return False


async def _wait_for_response_completion(
    tp: DummyTeleprompter,
    previous_responses: int,
    timeout_s: float = 45.0,
) -> tuple[bool, Optional[float]]:
    ok = await _wait_until(
        lambda: pipeline.total_responses > previous_responses,
        timeout_s=timeout_s,
    )
    if not ok:
        return False, None

    # Ensure token stream settled.
    last_len = len(tp._current_text)
    stable_for = 0.0
    while stable_for < 0.60:
        await asyncio.sleep(0.10)
        curr = len(tp._current_text)
        if curr == last_len:
            stable_for += 0.10
        else:
            stable_for = 0.0
            last_len = curr
    return True, time.perf_counter()


def _make_partial(text: str) -> str:
    words = text.split()
    cut = max(5, int(len(words) * 0.60))
    return " ".join(words[:cut])


async def _capture_progress_latency(
    tp: DummyTeleprompter,
    before_count: int,
    sent_at: float,
    timeout_s: float = 0.8,
) -> Optional[float]:
    ok = await _wait_until(
        lambda: len(tp.progress_update_times) > before_count,
        timeout_s=timeout_s,
        poll_s=0.005,
    )
    if not ok:
        return None

    ts = tp.progress_update_times[before_count]
    return (ts - sent_at) * 1000.0


async def _simulate_candidate_reading(
    tp: DummyTeleprompter,
    rng: random.Random,
    profile: str,
) -> ResponseReadMetrics:
    script = tp._current_text.strip()
    if not script:
        return ResponseReadMetrics(
            question="",
            profile=profile,
            response_len=0,
            final_read_index=0,
            final_read_ratio=0.0,
            monotonic_ok=True,
            premature_end_jump=False,
            checkpoints=[],
            progress_update_latencies_ms=[],
        )

    words = script.split()
    read_history: list[int] = [tp._read_char_index]
    consumed_words = 0
    checkpoints: list[dict[str, float]] = []
    premature_end_jump = False
    progress_latencies: list[float] = []

    i = 0
    await on_speech_event("user", "started")
    while i < len(words):
        base_chunk_size = max(6, int(rng.gauss(10, 2)))
        if profile in {"reorder", "adversarial_mix"}:
            base_chunk_size = max(base_chunk_size, 8)

        original_chunk = words[i:i + base_chunk_size]
        i += base_chunk_size
        consumed_words += len(original_chunk)

        chunk_words = _mutate_words(original_chunk, profile=profile, rng=rng)
        chunk_text = " ".join(chunk_words).strip()
        if not chunk_text:
            continue

        before_count = len(tp.progress_update_times)
        sent_at = time.perf_counter()

        await on_delta("user", chunk_text)
        await on_transcript("user", chunk_text)

        latency_ms = await _capture_progress_latency(tp, before_count, sent_at)
        if latency_ms is not None:
            progress_latencies.append(latency_ms)

        await asyncio.sleep(rng.uniform(0.015, 0.045))

        read_idx = tp._read_char_index
        read_history.append(read_idx)
        consumed_ratio = consumed_words / max(1, len(words))
        read_ratio = read_idx / max(1, len(script))
        checkpoints.append(
            {
                "consumed_ratio": round(consumed_ratio, 4),
                "read_ratio": round(read_ratio, 4),
            }
        )
        if consumed_ratio < 0.70 and read_ratio > 0.95:
            premature_end_jump = True

    before_final = len(tp.progress_update_times)
    final_sent_at = time.perf_counter()
    await on_speech_event("user", "stopped")
    final_latency_ms = await _capture_progress_latency(
        tp,
        before_count=before_final,
        sent_at=final_sent_at,
        timeout_s=0.5,
    )
    if final_latency_ms is not None:
        progress_latencies.append(final_latency_ms)

    monotonic_ok = all(
        b >= a for a, b in zip(read_history, read_history[1:])
    )
    final_idx = tp._read_char_index
    final_ratio = final_idx / max(1, len(script))

    return ResponseReadMetrics(
        question="",
        profile=profile,
        response_len=len(script),
        final_read_index=final_idx,
        final_read_ratio=round(final_ratio, 6),
        monotonic_ok=monotonic_ok,
        premature_end_jump=premature_end_jump,
        checkpoints=checkpoints,
        progress_update_latencies_ms=[round(v, 3) for v in progress_latencies],
    )


def _reset_pipeline_state():
    pipeline.total_questions = 0
    pipeline.total_responses = 0
    pipeline.last_activity = None
    pipeline.conversation_history = []
    pipeline.ws_clients = set()
    pipeline.active_generation_task = None
    pipeline.transcriber_int = None


async def run_mode(mode: str, seed: int = 20260303, difficulty: str = "standard") -> dict[str, Any]:
    if mode not in {"synthetic", "api"}:
        raise ValueError(f"Unsupported mode: {mode}")

    rng = random.Random(seed + (1 if mode == "api" else 0))
    _reset_pipeline_state()

    pipeline.classifier = QuestionClassifier()
    pipeline.question_filter = QuestionFilter()

    default_embedding_api = (
        "synthetic_openai_embedding"
        if mode == "synthetic"
        else "openai_embedding"
    )
    pipeline.cost_tracker = CostTracker(
        session_id=f"fullsim_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
        default_embedding_api_name=default_embedding_api,
    )

    enable_speculative = mode == "api"
    pipeline.transcriber_int = FakeInterviewerTranscriber() if enable_speculative else None

    if mode == "api":
        pipeline.retriever = KnowledgeRetriever()
        pipeline.response_agent = OpenAIAgent()
        await pipeline.response_agent.warmup()
    else:
        pipeline.retriever = SyntheticKnowledgeRetriever()
        pipeline.response_agent = SyntheticResponseAgentAdapter()

    port = 8770 if mode == "synthetic" else 8771
    tp = DummyTeleprompter()
    bridge = TeleprompterBridge(
        teleprompter=tp,
        ws_url=f"ws://127.0.0.1:{port}",
    )

    server = await websockets.serve(ws_handler, "127.0.0.1", port)
    bridge.start()

    connected = await _wait_until(lambda: len(pipeline.ws_clients) > 0, timeout_s=8.0)
    if not connected:
        bridge.stop()
        server.close()
        await server.wait_closed()
        raise RuntimeError(f"Teleprompter bridge did not connect in mode={mode}")

    per_response_metrics: list[dict[str, Any]] = []
    questions_processed = 0
    question_failures: list[str] = []

    try:
        for turn in INTERACTION_SCRIPT:
            speaker = turn["speaker"]
            kind = turn["kind"]
            text = turn["text"]

            if speaker == "candidate":
                await on_delta("user", text)
                await on_transcript("user", text)
                await asyncio.sleep(0.05)
                continue

            if kind == "question":
                prev_responses = pipeline.total_responses
                question_start = time.perf_counter()

                if enable_speculative and pipeline.transcriber_int is not None:
                    partial = _make_partial(text)
                    pipeline.transcriber_int.set_live_buffer(partial)
                    await on_speech_event("interviewer", "started")
                    await on_delta("interviewer", partial)
                    await on_speech_event("interviewer", "stopped")
                    await asyncio.sleep(0.04)

                await on_transcript("interviewer", text)

                completed, completion_ts = await _wait_for_response_completion(tp, prev_responses)
                if not completed:
                    question_failures.append(text)
                    continue

                first_token_latency_ms = None
                if tp.token_times:
                    first_token_latency_ms = round((tp.token_times[0] - question_start) * 1000.0, 3)

                completion_latency_ms = None
                if completion_ts is not None:
                    completion_latency_ms = round((completion_ts - question_start) * 1000.0, 3)

                questions_processed += 1
                profile = _pick_profile(difficulty, rng)
                read_metrics = await _simulate_candidate_reading(tp, rng, profile=profile)
                read_metrics.question = text

                per_response_metrics.append(
                    {
                        "question": read_metrics.question,
                        "profile": read_metrics.profile,
                        "response_len": read_metrics.response_len,
                        "final_read_index": read_metrics.final_read_index,
                        "final_read_ratio": read_metrics.final_read_ratio,
                        "monotonic_ok": read_metrics.monotonic_ok,
                        "premature_end_jump": read_metrics.premature_end_jump,
                        "checkpoints": read_metrics.checkpoints,
                        "progress_update_latencies_ms": read_metrics.progress_update_latencies_ms,
                        "first_token_latency_ms": first_token_latency_ms,
                        "completion_latency_ms": completion_latency_ms,
                    }
                )
                await asyncio.sleep(0.05)
            else:
                await on_transcript("interviewer", text)
                await asyncio.sleep(0.05)
    finally:
        bridge.stop()
        server.close()
        await server.wait_closed()

    ratios = [row["final_read_ratio"] for row in per_response_metrics if row["response_len"] > 0]
    premature = sum(1 for row in per_response_metrics if row["premature_end_jump"])
    monotonic_breaks = sum(1 for row in per_response_metrics if not row["monotonic_ok"])

    first_token_latencies = [
        row["first_token_latency_ms"]
        for row in per_response_metrics
        if row.get("first_token_latency_ms") is not None
    ]
    completion_latencies = [
        row["completion_latency_ms"]
        for row in per_response_metrics
        if row.get("completion_latency_ms") is not None
    ]
    progress_latencies = [
        latency
        for row in per_response_metrics
        for latency in row.get("progress_update_latencies_ms", [])
    ]

    profile_counts: dict[str, int] = {}
    for row in per_response_metrics:
        profile = row.get("profile", "unknown")
        profile_counts[profile] = profile_counts.get(profile, 0) + 1

    summary = {
        "mode": mode,
        "difficulty": difficulty,
        "questions_processed": questions_processed,
        "responses_generated": pipeline.total_responses,
        "question_failures": question_failures,
        "teleprompter_reading": {
            "responses_checked": len(per_response_metrics),
            "avg_final_read_ratio": round(sum(ratios) / len(ratios), 6) if ratios else 0.0,
            "min_final_read_ratio": round(min(ratios), 6) if ratios else 0.0,
            "max_final_read_ratio": round(max(ratios), 6) if ratios else 0.0,
            "premature_end_jump_count": premature,
            "monotonic_break_count": monotonic_breaks,
            "profile_counts": profile_counts,
        },
        "latency_sla_ms": {
            "first_token": _latency_stats(first_token_latencies),
            "completion": _latency_stats(completion_latencies),
            "progress_update": _latency_stats(progress_latencies),
        },
        "costs": {
            "total_cost_usd": round(pipeline.cost_tracker.breakdown.total_cost_usd, 6),
            "by_category": {
                key: round(val, 6)
                for key, val in pipeline.cost_tracker.breakdown.costs_by_category.items()
            },
            "api_calls_count": pipeline.cost_tracker.breakdown.api_calls_count,
        },
        "saldo": pipeline.cost_tracker.get_saldo_snapshot(),
        "per_response": per_response_metrics,
    }

    return summary


async def run_all(seed: int, difficulty: str) -> dict[str, Any]:
    synthetic = await run_mode("synthetic", seed=seed, difficulty=difficulty)
    api = await run_mode("api", seed=seed, difficulty=difficulty)
    return {
        "timestamp": datetime.now().isoformat(),
        "seed": seed,
        "difficulty": difficulty,
        "synthetic": synthetic,
        "api": api,
    }


def _print_summary(payload: dict[str, Any]) -> None:
    for mode in ("synthetic", "api"):
        s = payload[mode]
        t = s["teleprompter_reading"]
        l = s["latency_sla_ms"]
        fuel = s["saldo"].get("fuel_gauge", {})
        print("=" * 72)
        print(f"FULL REALISTIC SIMULATION | MODE={mode.upper()} | DIFFICULTY={s['difficulty'].upper()}")
        print("=" * 72)
        print(
            f"questions_processed={s['questions_processed']} "
            f"responses_generated={s['responses_generated']} "
            f"failures={len(s['question_failures'])}"
        )
        print(
            f"read_avg={t['avg_final_read_ratio']:.4f} "
            f"read_min={t['min_final_read_ratio']:.4f} "
            f"premature_end_jumps={t['premature_end_jump_count']} "
            f"monotonic_breaks={t['monotonic_break_count']}"
        )
        print(
            "latency_ms "
            f"first_token(p50/p95)={l['first_token']['p50']:.1f}/{l['first_token']['p95']:.1f} "
            f"completion(p50/p95)={l['completion']['p50']:.1f}/{l['completion']['p95']:.1f} "
            f"progress_update(p50/p95)={l['progress_update']['p50']:.1f}/{l['progress_update']['p95']:.1f}"
        )
        print(
            f"cost=${s['costs']['total_cost_usd']:.6f} "
            f"fuel_bottleneck={fuel.get('bottleneck_provider')} "
            f"fuel={fuel.get('human_readable_until_any_depletion')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run full realistic pipeline simulation in synthetic + API modes."
    )
    parser.add_argument("--seed", type=int, default=20260303)
    parser.add_argument(
        "--difficulty",
        choices=sorted(READING_PROFILES_BY_DIFFICULTY.keys()),
        default="hard",
        help="Adversarial reading profile level.",
    )
    args = parser.parse_args()

    payload = asyncio.run(run_all(seed=args.seed, difficulty=args.difficulty))
    out_dir = Path("tests/logs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"full_realistic_sim_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    _print_summary(payload)
    print(f"Report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
