"""
VibeVoice integration helpers (Microsoft VibeVoice-Realtime).

This module keeps the dependency optional and external to the core pipeline.
It can:
1) prepare/install the official VibeVoice repository
2) launch/stop the realtime websocket demo server
3) stream synthesized PCM16 audio and export WAV files
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import logging
import os
import subprocess
import sys
import urllib.parse
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import websockets

logger = logging.getLogger("voice.vibevoice")

DEFAULT_REPO_URL = "https://github.com/microsoft/VibeVoice.git"
DEFAULT_MODEL_PATH = "microsoft/VibeVoice-Realtime-0.5B"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 3000
DEFAULT_SAMPLE_RATE = 24000


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass
class InstallStep:
    description: str
    command: list[str]
    cwd: Optional[Path] = None


@dataclass
class VibeVoiceConfig:
    enabled: bool = False
    repo_url: str = DEFAULT_REPO_URL
    repo_path: str = "external/VibeVoice"
    model_path: str = DEFAULT_MODEL_PATH
    device: str = "cuda"
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    python_executable: str = sys.executable
    auto_clone: bool = True
    auto_install: bool = False

    @classmethod
    def from_env(cls) -> "VibeVoiceConfig":
        return cls(
            enabled=_env_bool("VIBEVOICE_ENABLED", default=False),
            repo_url=os.getenv("VIBEVOICE_REPO_URL", DEFAULT_REPO_URL).strip(),
            repo_path=os.getenv("VIBEVOICE_REPO_PATH", "external/VibeVoice").strip(),
            model_path=os.getenv("VIBEVOICE_MODEL_PATH", DEFAULT_MODEL_PATH).strip(),
            device=os.getenv("VIBEVOICE_DEVICE", "cuda").strip().lower(),
            host=os.getenv("VIBEVOICE_HOST", DEFAULT_HOST).strip(),
            port=int(os.getenv("VIBEVOICE_PORT", str(DEFAULT_PORT))),
            python_executable=os.getenv("VIBEVOICE_PYTHON", sys.executable).strip(),
            auto_clone=_env_bool("VIBEVOICE_AUTO_CLONE", default=True),
            auto_install=_env_bool("VIBEVOICE_AUTO_INSTALL", default=False),
        )

    def resolve_repo_path(self, project_root: Path) -> Path:
        path = Path(self.repo_path).expanduser()
        if not path.is_absolute():
            path = project_root / path
        return path.resolve()


class VibeVoiceInstaller:
    """
    Build and execute installation steps for the official Microsoft repository.
    """

    def __init__(self, config: VibeVoiceConfig, project_root: Optional[Path] = None):
        self.config = config
        self.project_root = (project_root or Path.cwd()).resolve()

    @property
    def repo_path(self) -> Path:
        return self.config.resolve_repo_path(self.project_root)

    def build_install_plan(self, update_existing: bool = False) -> list[InstallStep]:
        plan: list[InstallStep] = []
        repo_path = self.repo_path

        if not repo_path.exists():
            if not self.config.auto_clone:
                raise FileNotFoundError(
                    f"VibeVoice repo not found and auto_clone disabled: {repo_path}"
                )
            plan.append(
                InstallStep(
                    description="Clone Microsoft VibeVoice repository",
                    command=["git", "clone", self.config.repo_url, str(repo_path)],
                )
            )
        elif update_existing:
            plan.append(
                InstallStep(
                    description="Update existing VibeVoice repository",
                    command=["git", "-C", str(repo_path), "pull", "--ff-only"],
                )
            )

        plan.append(
            InstallStep(
                description="Install VibeVoice with streaming TTS extras",
                command=[
                    self.config.python_executable,
                    "-m",
                    "pip",
                    "install",
                    "-e",
                    ".[streamingtts]",
                ],
                cwd=repo_path,
            )
        )
        return plan

    def install(
        self,
        update_existing: bool = False,
        dry_run: bool = False,
    ) -> dict:
        plan = self.build_install_plan(update_existing=update_existing)
        results = []

        for step in plan:
            row = {
                "description": step.description,
                "command": step.command,
                "cwd": str(step.cwd) if step.cwd else None,
                "ok": True,
                "stdout": "",
                "stderr": "",
            }
            if dry_run:
                results.append(row)
                continue
            try:
                completed = subprocess.run(
                    step.command,
                    cwd=str(step.cwd) if step.cwd else None,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                row["stdout"] = completed.stdout
                row["stderr"] = completed.stderr
            except subprocess.CalledProcessError as exc:
                row["ok"] = False
                row["stdout"] = exc.stdout or ""
                row["stderr"] = exc.stderr or ""
                results.append(row)
                return {"ok": False, "steps": results}
            results.append(row)

        return {"ok": True, "steps": results}


class VibeVoiceRuntime:
    """
    Control the official realtime websocket demo server and synthesize audio.
    """

    def __init__(self, config: VibeVoiceConfig, project_root: Optional[Path] = None):
        self.config = config
        self.project_root = (project_root or Path.cwd()).resolve()
        self._server_process: Optional[subprocess.Popen] = None
        self._log_file_handle = None

    @property
    def repo_path(self) -> Path:
        return self.config.resolve_repo_path(self.project_root)

    @property
    def demo_script_path(self) -> Path:
        return self.repo_path / "demo" / "vibevoice_realtime_demo.py"

    @property
    def websocket_url_base(self) -> str:
        return f"ws://{self.config.host}:{self.config.port}/stream"

    def validate_runtime_files(self) -> None:
        if not self.repo_path.exists():
            raise FileNotFoundError(
                f"VibeVoice repository not found at: {self.repo_path}"
            )
        if not self.demo_script_path.exists():
            raise FileNotFoundError(
                f"Realtime demo script not found at: {self.demo_script_path}"
            )

    def build_server_command(self) -> list[str]:
        return [
            self.config.python_executable,
            str(self.demo_script_path),
            "--port",
            str(self.config.port),
            "--model_path",
            self.config.model_path,
            "--device",
            self.config.device,
        ]

    async def start_server(
        self,
        wait_seconds: float = 3.0,
        log_file: Optional[Path] = None,
    ) -> int:
        if self._server_process and self._server_process.poll() is None:
            return int(self._server_process.pid)

        self.validate_runtime_files()
        cmd = self.build_server_command()

        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.STDOUT
        if log_file is not None:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_file_handle = open(log_file, "a", encoding="utf-8")
            stdout_target = self._log_file_handle
            stderr_target = self._log_file_handle

        creationflags = 0
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        self._server_process = subprocess.Popen(
            cmd,
            cwd=str(self.repo_path),
            stdout=stdout_target,
            stderr=stderr_target,
            text=True,
            creationflags=creationflags,
        )
        try:
            await self.wait_until_ready(timeout_seconds=max(1.0, wait_seconds))
        except Exception:
            await self.stop_server()
            raise

        return int(self._server_process.pid)

    async def wait_until_ready(
        self,
        timeout_seconds: float = 30.0,
        poll_seconds: float = 0.4,
    ) -> None:
        """
        Wait until the realtime server is accepting TCP connections.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(0.5, timeout_seconds)
        last_error: Optional[BaseException] = None

        while loop.time() < deadline:
            if self._server_process and self._server_process.poll() is not None:
                code = self._server_process.returncode
                raise RuntimeError(f"VibeVoice server exited early with code={code}")

            try:
                reader, writer = await asyncio.open_connection(
                    host=self.config.host,
                    port=self.config.port,
                )
                writer.close()
                await writer.wait_closed()
                return
            except OSError as exc:
                last_error = exc
                await asyncio.sleep(max(0.05, poll_seconds))

        error_hint = f": {last_error}" if last_error else ""
        raise TimeoutError(
            "Timed out waiting for VibeVoice server socket "
            f"{self.config.host}:{self.config.port}{error_hint}"
        )

    async def stop_server(self, timeout_seconds: float = 8.0) -> None:
        proc = self._server_process
        self._server_process = None
        if proc is None:
            return
        if proc.poll() is not None:
            return

        proc.terminate()
        try:
            await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            proc.kill()
            await asyncio.to_thread(proc.wait)
        finally:
            if self._log_file_handle:
                self._log_file_handle.close()
                self._log_file_handle = None

    def build_stream_url(
        self,
        text: str,
        cfg_scale: float = 1.5,
        steps: Optional[int] = None,
        voice: Optional[str] = None,
    ) -> str:
        query = {
            "text": text,
            "cfg": str(cfg_scale),
        }
        if steps is not None:
            query["steps"] = str(steps)
        if voice:
            query["voice"] = voice
        return f"{self.websocket_url_base}?{urllib.parse.urlencode(query)}"

    async def stream_pcm16(
        self,
        text: str,
        cfg_scale: float = 1.5,
        steps: Optional[int] = None,
        voice: Optional[str] = None,
        timeout_seconds: float = 90.0,
    ) -> bytes:
        """
        Return raw PCM16 bytes from the realtime websocket.
        """
        if not text.strip():
            return b""

        url = self.build_stream_url(
            text=text,
            cfg_scale=cfg_scale,
            steps=steps,
            voice=voice,
        )
        audio_chunks: list[bytes] = []

        async with websockets.connect(
            url,
            max_size=None,
            open_timeout=10.0,
            close_timeout=10.0,
            ping_interval=20.0,
            ping_timeout=20.0,
        ) as ws:
            while True:
                try:
                    message = await asyncio.wait_for(ws.recv(), timeout=timeout_seconds)
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"Timed out waiting VibeVoice audio chunk ({timeout_seconds}s)"
                    )
                except websockets.exceptions.ConnectionClosed:
                    break

                if isinstance(message, (bytes, bytearray)):
                    audio_chunks.append(bytes(message))
                    continue
                # Demo server can also send json log events as text frames.
                if isinstance(message, str):
                    try:
                        parsed = json.loads(message)
                        if parsed.get("type") == "log":
                            logger.debug("VibeVoice log: %s", parsed)
                    except Exception:
                        logger.debug("Unexpected VibeVoice text frame: %s", message[:120])

        return b"".join(audio_chunks)

    @staticmethod
    def pcm16_to_wav_bytes(
        pcm16_bytes: bytes,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = 1,
    ) -> bytes:
        with io.BytesIO() as buffer:
            with wave.open(buffer, "wb") as wav_file:
                wav_file.setnchannels(channels)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                wav_file.writeframes(pcm16_bytes or b"")
            return buffer.getvalue()

    async def synthesize_to_wav_file(
        self,
        text: str,
        output_path: Path,
        cfg_scale: float = 1.5,
        steps: Optional[int] = None,
        voice: Optional[str] = None,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> Path:
        pcm_data = await self.stream_pcm16(
            text=text,
            cfg_scale=cfg_scale,
            steps=steps,
            voice=voice,
        )
        wav_data = self.pcm16_to_wav_bytes(pcm_data, sample_rate=sample_rate)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(wav_data)
        return output_path


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="VibeVoice setup/runtime manager")
    parser.add_argument(
        "--action",
        choices=("plan", "install", "start", "synthesize"),
        default="plan",
        help="Operation to execute.",
    )
    parser.add_argument("--repo-path", default="external/VibeVoice")
    parser.add_argument("--repo-url", default=DEFAULT_REPO_URL)
    parser.add_argument("--model-path", default=DEFAULT_MODEL_PATH)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--text", default="Hello from VibeVoice.")
    parser.add_argument("--output", default="logs/vibevoice_demo.wav")
    parser.add_argument("--update-existing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def _config_from_args(args: argparse.Namespace) -> VibeVoiceConfig:
    return VibeVoiceConfig(
        enabled=True,
        repo_url=args.repo_url,
        repo_path=args.repo_path,
        model_path=args.model_path,
        device=args.device,
        host=args.host,
        port=args.port,
        python_executable=sys.executable,
    )


def main() -> int:
    parser = _build_cli_parser()
    args = parser.parse_args()
    config = _config_from_args(args)
    installer = VibeVoiceInstaller(config=config, project_root=Path.cwd())
    runtime = VibeVoiceRuntime(config=config, project_root=Path.cwd())

    if args.action == "plan":
        plan = installer.build_install_plan(update_existing=args.update_existing)
        for step in plan:
            prefix = f"(cwd={step.cwd}) " if step.cwd else ""
            print(f"- {step.description}: {prefix}{' '.join(step.command)}")
        return 0

    if args.action == "install":
        result = installer.install(
            update_existing=args.update_existing,
            dry_run=args.dry_run,
        )
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1

    if args.action == "start":
        async def _run_start():
            pid = await runtime.start_server()
            print(f"VibeVoice server running on pid={pid} @ {runtime.websocket_url_base}")
            print("Press Ctrl+C to stop...")
            try:
                while True:
                    await asyncio.sleep(1.0)
            except KeyboardInterrupt:
                pass
            finally:
                await runtime.stop_server()

        asyncio.run(_run_start())
        return 0

    if args.action == "synthesize":
        async def _run_synthesize():
            await runtime.start_server()
            try:
                out = await runtime.synthesize_to_wav_file(
                    text=args.text,
                    output_path=Path(args.output),
                )
                print(f"Generated: {out}")
            finally:
                await runtime.stop_server()

        asyncio.run(_run_synthesize())
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
