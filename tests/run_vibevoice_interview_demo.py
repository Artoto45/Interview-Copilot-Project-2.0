"""
Realistic interview simulation + VibeVoice synthesis demo.

Flow:
1) run realistic interview simulation (synthetic or api)
2) collect generated Q/A responses from pipeline history
3) synthesize each response with VibeVoice realtime server
4) export WAV files + transcript + json report
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import wave
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import main as coordinator
from src.voice.vibevoice_manager import VibeVoiceConfig, VibeVoiceRuntime
from tests.run_full_pipeline_realistic_sim import run_mode


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run realistic interview simulation with VibeVoice audio synthesis."
    )
    parser.add_argument("--mode", choices=("synthetic", "api"), default="synthetic")
    parser.add_argument("--difficulty", choices=("standard", "hard", "extreme"), default="hard")
    parser.add_argument("--seed", type=int, default=20260304)
    parser.add_argument(
        "--max-turns",
        type=int,
        default=4,
        help="Maximum generated interviewer questions to synthesize.",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default="",
        help="Optional voice key for VibeVoice websocket query (e.g., Carter).",
    )
    parser.add_argument(
        "--cfg-scale",
        type=float,
        default=1.5,
        help="Classifier-free guidance scale used by VibeVoice server.",
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=5,
        help="Inference DDPM steps for VibeVoice server.",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=os.getenv("VIBEVOICE_DEVICE", "cuda"),
        choices=("cpu", "cuda", "mps", "mpx"),
        help="Device used by VibeVoice realtime server.",
    )
    parser.add_argument(
        "--startup-timeout",
        type=float,
        default=120.0,
        help="Max seconds to wait for VibeVoice websocket server readiness.",
    )
    return parser.parse_args()


def _collect_qa_entries(max_turns: int) -> list[dict]:
    qa = [
        entry for entry in coordinator.pipeline.conversation_history
        if isinstance(entry, dict)
        and str(entry.get("question", "")).strip()
        and str(entry.get("response", "")).strip()
    ]
    return qa[:max(1, max_turns)]


def _wav_duration_seconds(path: Path) -> float:
    with contextlib.closing(wave.open(str(path), "rb")) as wav_file:
        frames = wav_file.getnframes()
        rate = wav_file.getframerate()
        if rate <= 0:
            return 0.0
        return float(frames) / float(rate)


async def _run() -> int:
    args = _parse_args()
    summary = await run_mode(mode=args.mode, seed=args.seed, difficulty=args.difficulty)
    qa = _collect_qa_entries(args.max_turns)
    if not qa:
        print("No generated Q/A turns found in pipeline history.")
        return 2

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path("tests/logs") / f"vibevoice_interview_demo_{ts}"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = VibeVoiceConfig.from_env()
    config.enabled = True
    config.device = args.device
    runtime = VibeVoiceRuntime(config=config, project_root=Path.cwd())

    server_log = out_dir / "vibevoice_server.log"
    wav_rows: list[dict] = []
    try:
        await runtime.start_server(
            wait_seconds=args.startup_timeout,
            log_file=server_log,
        )
    except Exception as exc:
        print(f"Failed to start VibeVoice server: {exc}")
        print(f"Server log (if any): {server_log}")
        return 3

    try:
        for idx, row in enumerate(qa, start=1):
            question = str(row.get("question", "")).strip()
            response = str(row.get("response", "")).strip()
            wav_path = out_dir / f"turn_{idx:02d}.wav"
            try:
                await runtime.synthesize_to_wav_file(
                    text=response,
                    output_path=wav_path,
                    cfg_scale=args.cfg_scale,
                    steps=args.steps,
                    voice=(args.voice or None),
                )
            except Exception as exc:
                print(f"Failed synthesis for turn {idx}: {exc}")
                print(f"Server log: {server_log}")
                return 4
            wav_rows.append(
                {
                    "turn": idx,
                    "question": question,
                    "response": response,
                    "wav_path": str(wav_path),
                    "wav_duration_s": round(_wav_duration_seconds(wav_path), 3),
                    "response_chars": len(response),
                }
            )
    finally:
        await runtime.stop_server()

    transcript_md = out_dir / "transcript.md"
    lines = [
        "# VibeVoice Interview Demo",
        "",
        f"- mode: `{args.mode}`",
        f"- difficulty: `{args.difficulty}`",
        f"- seed: `{args.seed}`",
        f"- turns_synthesized: `{len(wav_rows)}`",
        "",
    ]
    for row in wav_rows:
        lines.append(f"## Turn {row['turn']}")
        lines.append(f"**Question:** {row['question']}")
        lines.append("")
        lines.append(f"**Response:** {row['response']}")
        lines.append("")
        lines.append(f"**Audio:** `{row['wav_path']}` ({row['wav_duration_s']}s)")
        lines.append("")
    transcript_md.write_text("\n".join(lines), encoding="utf-8")

    report = {
        "timestamp": datetime.now().isoformat(),
        "simulation_summary": summary,
        "vibevoice": {
            "device": args.device,
            "voice": args.voice or None,
            "cfg_scale": args.cfg_scale,
            "steps": args.steps,
            "host": config.host,
            "port": config.port,
            "server_log": str(server_log),
        },
        "turns": wav_rows,
        "output_dir": str(out_dir),
        "transcript": str(transcript_md),
    }

    report_path = out_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=" * 72)
    print("VIBEVOICE INTERVIEW DEMO")
    print("=" * 72)
    print(
        f"mode={args.mode} difficulty={args.difficulty} "
        f"turns={len(wav_rows)} device={args.device}"
    )
    for row in wav_rows:
        print(
            f"- turn={row['turn']} chars={row['response_chars']} "
            f"audio={row['wav_duration_s']}s file={Path(row['wav_path']).name}"
        )
    print(f"Transcript: {transcript_md}")
    print(f"Report: {report_path}")
    print("=" * 72)
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
