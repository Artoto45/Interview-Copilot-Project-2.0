"""
Mega E2E extreme simulation with formal teleprompter SLO checks.

SLO:
- p99 compliance target for teleprompter completion:
  at least 99% of responses must have final_read_ratio >= threshold.
  Equivalent low-tail metric: p01_final_read_ratio >= threshold.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.run_full_pipeline_realistic_sim import run_mode


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int(round((pct / 100.0) * (len(ordered) - 1)))))
    return float(ordered[idx])


def _pass_rate(values: list[float], threshold: float) -> float:
    if not values:
        return 0.0
    passes = sum(1 for value in values if value >= threshold)
    return passes / len(values)


async def _run(
    mode: str,
    runs: int,
    seed_start: int,
    difficulty: str,
    slo_threshold: float,
) -> dict:
    seeds = [seed_start + idx for idx in range(runs)]
    run_rows = []
    all_ratios: list[float] = []

    for seed in seeds:
        result = await run_mode(
            mode=mode,
            seed=seed,
            difficulty=difficulty,
        )
        run_rows.append({"seed": seed, "result": result})
        for response in result.get("per_response", []):
            all_ratios.append(float(response.get("final_read_ratio", 0.0)))

    p01 = _percentile(all_ratios, 1.0)
    pass_rate = _pass_rate(all_ratios, slo_threshold)
    pass_rate_p99 = pass_rate >= 0.99
    low_tail_pass = p01 >= slo_threshold

    summary = {
        "mode": mode,
        "runs": runs,
        "seeds": seeds,
        "difficulty": difficulty,
        "responses_total": len(all_ratios),
        "questions_processed_total": sum(
            row["result"]["questions_processed"] for row in run_rows
        ),
        "teleprompter": {
            "avg_final_read_ratio": round(statistics.mean(all_ratios), 6) if all_ratios else 0.0,
            "min_final_read_ratio": round(min(all_ratios), 6) if all_ratios else 0.0,
            "p01_final_read_ratio": round(p01, 6),
            "threshold": slo_threshold,
            "pass_rate_ge_threshold": round(pass_rate, 6),
        },
        "slo": {
            "definition": (
                "p99 compliance: >=99% responses with final_read_ratio >= threshold; "
                "equivalent low-tail check p01_final_read_ratio >= threshold"
            ),
            "pass_rate_check_passed": pass_rate_p99,
            "low_tail_check_passed": low_tail_pass,
            "overall_passed": pass_rate_p99 and low_tail_pass,
        },
    }

    return {
        "timestamp": datetime.now().isoformat(),
        "summary": summary,
        "runs_detail": run_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run mega E2E extreme simulation with formal teleprompter SLO."
    )
    parser.add_argument(
        "--mode",
        choices=["synthetic", "api"],
        default="synthetic",
    )
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--seed-start", type=int, default=20260303)
    parser.add_argument("--difficulty", choices=["standard", "hard", "extreme"], default="extreme")
    parser.add_argument("--slo-threshold", type=float, default=0.92)
    args = parser.parse_args()

    if args.mode == "api" and not os.getenv("OPENAI_API_KEY"):
        print("Missing OPENAI_API_KEY for --mode api")
        return 2

    payload = asyncio.run(
        _run(
            mode=args.mode,
            runs=max(1, int(args.runs)),
            seed_start=int(args.seed_start),
            difficulty=args.difficulty,
            slo_threshold=float(args.slo_threshold),
        )
    )

    out_dir = Path("tests/logs")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / (
        f"mega_{args.mode}_e2e_extreme_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    s = payload["summary"]
    t = s["teleprompter"]
    slo = s["slo"]
    print("=" * 72)
    print(f"MEGA {args.mode.upper()} EXTREME + TELEPROMPTER SLO")
    print("=" * 72)
    print(
        f"runs={s['runs']} responses_total={s['responses_total']} "
        f"questions_total={s['questions_processed_total']}"
    )
    print(
        f"read_ratio avg={t['avg_final_read_ratio']:.4f} "
        f"min={t['min_final_read_ratio']:.4f} "
        f"p01={t['p01_final_read_ratio']:.4f} "
        f"threshold={t['threshold']:.4f} "
        f"pass_rate={t['pass_rate_ge_threshold']:.4f}"
    )
    print(
        f"SLO pass_rate_check={slo['pass_rate_check_passed']} "
        f"low_tail_check={slo['low_tail_check_passed']} "
        f"overall={slo['overall_passed']}"
    )
    print(f"Report: {out_path}")
    return 0 if slo["overall_passed"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
