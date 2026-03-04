"""
Strict stress test for teleprompter progress tracking.

Focus:
- detect false jumps to the end on weak matches
- verify robust forward progress under noisy ASR-like chunks
- validate near-end completion when strong tail evidence exists
- reproduce the real conversation mismatch scenario without end jumps
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.teleprompter.progress_tracker import estimate_char_progress, normalize_for_match


@dataclass
class StrictMetrics:
    cases: int
    seed: int
    monotonic_failures: int
    jump_limit_failures: int
    full_recovery_failures: int
    weak_tail_attempts: int
    weak_tail_end_cross_failures: int
    near_end_completion_failures: int
    mismatch_end_jump_failures: int

    @property
    def full_recovery_success_rate(self) -> float:
        if self.cases <= 0:
            return 0.0
        return 1.0 - (self.full_recovery_failures / self.cases)

    @property
    def weak_tail_end_cross_rate(self) -> float:
        if self.weak_tail_attempts <= 0:
            return 0.0
        return self.weak_tail_end_cross_failures / self.weak_tail_attempts

    @property
    def near_end_completion_success_rate(self) -> float:
        if self.cases <= 0:
            return 0.0
        return 1.0 - (self.near_end_completion_failures / self.cases)


VOCAB = [
    "project", "team", "process", "quality", "support", "customer", "workflow",
    "update", "procedure", "metrics", "analysis", "priority", "coordination",
    "escalation", "review", "followup", "documentation", "clarity", "stability",
    "performance", "communication", "improvement", "ownership", "delivery",
    "timeline", "collaboration", "compliance", "strategy", "leadership",
    "impact", "result", "efficiency", "consistency", "training", "adaptation",
    "planning", "stakeholder", "alignment", "execution", "reliability",
]

TAIL_PHRASES = [
    "even when you're new to a project",
    "while maintaining quality under pressure",
    "with clear ownership across the team",
    "and keeping stakeholders fully informed",
]


def _words(text: str) -> list[str]:
    return normalize_for_match(text).split()


def _make_script(rng: random.Random, min_words: int = 120, max_words: int = 280) -> str:
    n = rng.randint(min_words, max_words)
    words = [rng.choice(VOCAB) for _ in range(n)]
    chunks = []
    for idx, word in enumerate(words, 1):
        chunks.append(word)
        if idx % 14 == 0:
            chunks[-1] += rng.choice([".", ".", ","])
    text = " ".join(chunks)
    text += (
        ". Overall, I learned that being open and supportive can drive great results, "
        f"{rng.choice(TAIL_PHRASES)}."
    )
    return text


def _chunk_words(rng: random.Random, seq: list[str], avg_step: int) -> list[list[str]]:
    out: list[list[str]] = []
    i = 0
    while i < len(seq):
        size = max(4, int(rng.gauss(avg_step, 2.3)))
        out.append(seq[i:i + size])
        i += size
    return out


def _asr_noise(rng: random.Random, seq: list[str]) -> list[str]:
    seq = list(seq)
    if len(seq) > 6:
        for _ in range(rng.randint(0, 2)):
            if not seq:
                break
            seq.pop(rng.randrange(len(seq)))
    for _ in range(rng.randint(0, 2)):
        if not seq:
            break
        idx = rng.randrange(len(seq))
        tok = seq[idx]
        if len(tok) > 6:
            seq[idx] = tok[:-1]
    if seq and rng.random() < 0.30:
        idx = rng.randrange(len(seq))
        seq.insert(idx, seq[idx])
    return seq


def _run_strict(cases: int, seed: int) -> StrictMetrics:
    rng = random.Random(seed)

    monotonic_failures = 0
    jump_limit_failures = 0
    full_recovery_failures = 0
    weak_tail_attempts = 0
    weak_tail_end_cross_failures = 0
    near_end_completion_failures = 0
    mismatch_end_jump_failures = 0

    # Real mismatch scenario from the user session.
    mismatch_script = (
        "In my previous role at Webhelp, I faced a project where I had no prior experience. "
        "The task was to implement a new procedure for our team. "
        "I started by researching best practices and gathering insights from colleagues. "
        "I shared my findings with the team, which helped build my credibility. "
        "Next, I proactively walked them through the updated procedures and answered their questions "
        "based on my experience. This collaboration led to a 92 percent QA score during our first "
        "review, showing that our efforts paid off. Overall, I learned that being open and supportive "
        "can drive great results, even when you're new to a project."
    )
    mismatch_chunks = [
        "When changes happened, I took the time to study them in detail.",
        "I made notes and if I found something unclear, I did not hesitate to ask my supervisor.",
        "This way, I avoided mistakes and ensured I understood the new procedures.",
        "I also shared my notes with the team, walking them through the updates.",
        "This informal support really helped everyone adapt.",
        "Overall, my proactive approach improved our team performance and transition smoother.",
    ]

    for _ in range(cases):
        script = _make_script(rng)
        script_words = _words(script)
        script_len = len(script)

        # A) Sequential noisy reading should mostly recover script progress.
        current = 0
        for part in _chunk_words(rng, script_words, avg_step=rng.randint(8, 14)):
            noisy = _asr_noise(rng, part)
            spoken = " ".join(noisy)
            nxt = estimate_char_progress(script, spoken, current_progress=current)
            if nxt < current:
                monotonic_failures += 1
            if nxt - current > max(230, int(len(spoken) * 3.6)):
                jump_limit_failures += 1
            current = max(current, nxt)

        if current < int(0.90 * script_len):
            full_recovery_failures += 1

        # B) Weak tail bait should not cross into end zone.
        current = int(script_len * rng.uniform(0.55, 0.82))
        for bait in ("project", "overall", "results", "team", "quality"):
            weak_tail_attempts += 1
            nxt = estimate_char_progress(script, bait, current_progress=current)
            if nxt > int(0.94 * script_len):
                weak_tail_end_cross_failures += 1

        # C) Strong tail evidence near end should complete correctly.
        tail = " ".join(_words(script)[-10:])
        nxt = estimate_char_progress(
            script,
            tail,
            current_progress=int(script_len * 0.90),
        )
        if nxt < int(0.96 * script_len):
            near_end_completion_failures += 1

        # D) Real mismatch conversation should not snap to script end.
        mismatch_current = int(len(mismatch_script) * 0.70)
        mismatch_accum = ""
        for chunk in mismatch_chunks:
            mismatch_accum = (mismatch_accum + " " + chunk).strip()
            mismatch_current = estimate_char_progress(
                mismatch_script,
                mismatch_accum,
                current_progress=mismatch_current,
            )
        if mismatch_current >= int(len(mismatch_script) * 0.94):
            mismatch_end_jump_failures += 1

    return StrictMetrics(
        cases=cases,
        seed=seed,
        monotonic_failures=monotonic_failures,
        jump_limit_failures=jump_limit_failures,
        full_recovery_failures=full_recovery_failures,
        weak_tail_attempts=weak_tail_attempts,
        weak_tail_end_cross_failures=weak_tail_end_cross_failures,
        near_end_completion_failures=near_end_completion_failures,
        mismatch_end_jump_failures=mismatch_end_jump_failures,
    )


def _build_verdict(metrics: StrictMetrics) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if metrics.monotonic_failures > 0:
        reasons.append(f"monotonic_failures={metrics.monotonic_failures}")
    if metrics.jump_limit_failures > 0:
        reasons.append(f"jump_limit_failures={metrics.jump_limit_failures}")
    if metrics.full_recovery_success_rate < 0.99:
        reasons.append(
            f"full_recovery_success_rate={metrics.full_recovery_success_rate:.4f}<0.99"
        )
    if metrics.weak_tail_end_cross_rate > 0.001:
        reasons.append(
            f"weak_tail_end_cross_rate={metrics.weak_tail_end_cross_rate:.4f}>0.001"
        )
    if metrics.near_end_completion_success_rate < 0.995:
        reasons.append(
            "near_end_completion_success_rate="
            f"{metrics.near_end_completion_success_rate:.4f}<0.995"
        )
    if metrics.mismatch_end_jump_failures > 0:
        reasons.append(f"mismatch_end_jump_failures={metrics.mismatch_end_jump_failures}")

    return len(reasons) == 0, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Strict stress for teleprompter progress tracker.")
    parser.add_argument("--cases", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20260303)
    args = parser.parse_args()

    metrics = _run_strict(cases=max(200, args.cases), seed=args.seed)
    passed, reasons = _build_verdict(metrics)

    payload = {
        "metrics": {
            "cases": metrics.cases,
            "seed": metrics.seed,
            "monotonic_failures": metrics.monotonic_failures,
            "jump_limit_failures": metrics.jump_limit_failures,
            "full_recovery_failures": metrics.full_recovery_failures,
            "full_recovery_success_rate": round(metrics.full_recovery_success_rate, 6),
            "weak_tail_attempts": metrics.weak_tail_attempts,
            "weak_tail_end_cross_failures": metrics.weak_tail_end_cross_failures,
            "weak_tail_end_cross_rate": round(metrics.weak_tail_end_cross_rate, 6),
            "near_end_completion_failures": metrics.near_end_completion_failures,
            "near_end_completion_success_rate": round(metrics.near_end_completion_success_rate, 6),
            "mismatch_end_jump_failures": metrics.mismatch_end_jump_failures,
        },
        "verdict": {
            "passed": passed,
            "reasons": reasons,
        },
    }

    out_dir = Path("tests/logs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"progress_strict_stress_{metrics.seed}_{metrics.cases}.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 72)
    print("TELEPROMPTER PROGRESS STRICT STRESS")
    print("=" * 72)
    print(json.dumps(payload["metrics"], indent=2, ensure_ascii=False))
    print(f"VERDICT: {'PASS' if passed else 'FAIL'}")
    if reasons:
        print("Reasons:")
        for reason in reasons:
            print(f"- {reason}")
    print(f"Report: {out_path}")
    print("=" * 72)

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
