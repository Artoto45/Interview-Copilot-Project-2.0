"""
Run a robust regression battery for the interview copilot.

Usage:
    python tests/run_robust_battery.py --mode core
    python tests/run_robust_battery.py --mode robust
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


CORE_TESTS = [
    "tests/test_question_filter.py",
    "tests/test_knowledge.py",
    "tests/test_fragment_gate.py",
    "tests/test_response_validation.py",
    "tests/test_response_fallback_manager.py",
    "tests/test_main_pipeline_regression.py",
    "tests/test_interview_memory.py",
]

ROBUST_EXTRA_TESTS = [
    "tests/test_mitigation_package.py",
    "tests/test_stress_orchestrator.py",
    "tests/test_progress_tracker.py",
    "tests/test_progress_tracker_strict.py",
    "tests/test_ws_bridge_lifecycle.py",
    "tests/test_saldo.py",
]


def _select_tests(mode: str) -> list[str]:
    if mode == "core":
        return CORE_TESTS
    if mode == "robust":
        return CORE_TESTS + ROBUST_EXTRA_TESTS
    raise ValueError(f"Unsupported mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run robust regression battery."
    )
    parser.add_argument(
        "--mode",
        choices=("core", "robust"),
        default="robust",
        help="core=fast critical checks, robust=core + stress regressions",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    tests = _select_tests(args.mode)
    cmd = [sys.executable, "-m", "pytest", "-q", *tests]

    print(f"[battery] mode={args.mode} tests={len(tests)}")
    print(f"[battery] cmd={' '.join(cmd)}")
    completed = subprocess.run(cmd, cwd=str(repo_root))
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
