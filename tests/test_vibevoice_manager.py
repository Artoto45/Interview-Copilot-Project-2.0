from pathlib import Path

import pytest

from src.voice.vibevoice_manager import (
    DEFAULT_SAMPLE_RATE,
    VibeVoiceConfig,
    VibeVoiceInstaller,
    VibeVoiceRuntime,
)


def test_vibevoice_config_from_env(monkeypatch):
    monkeypatch.setenv("VIBEVOICE_ENABLED", "true")
    monkeypatch.setenv("VIBEVOICE_REPO_PATH", "vendor/VibeVoice")
    monkeypatch.setenv("VIBEVOICE_MODEL_PATH", "microsoft/VibeVoice-Realtime-0.5B")
    monkeypatch.setenv("VIBEVOICE_DEVICE", "cpu")
    monkeypatch.setenv("VIBEVOICE_PORT", "3011")
    cfg = VibeVoiceConfig.from_env()

    assert cfg.enabled is True
    assert cfg.repo_path == "vendor/VibeVoice"
    assert cfg.model_path == "microsoft/VibeVoice-Realtime-0.5B"
    assert cfg.device == "cpu"
    assert cfg.port == 3011


def test_install_plan_includes_clone_and_pip_install(tmp_path: Path):
    cfg = VibeVoiceConfig(
        enabled=True,
        repo_path="external/VibeVoice",
        python_executable="python",
    )
    installer = VibeVoiceInstaller(config=cfg, project_root=tmp_path)
    plan = installer.build_install_plan(update_existing=False)

    assert len(plan) == 2
    assert plan[0].command[:2] == ["git", "clone"]
    assert plan[1].command[:5] == ["python", "-m", "pip", "install", "-e"]
    assert plan[1].cwd == (tmp_path / "external" / "VibeVoice").resolve()


def test_runtime_validation_fails_without_repo(tmp_path: Path):
    cfg = VibeVoiceConfig(
        enabled=True,
        repo_path="missing/VibeVoice",
    )
    runtime = VibeVoiceRuntime(config=cfg, project_root=tmp_path)

    with pytest.raises(FileNotFoundError):
        runtime.validate_runtime_files()


def test_runtime_build_stream_url_encodes_query(tmp_path: Path):
    repo = tmp_path / "external" / "VibeVoice" / "demo"
    repo.mkdir(parents=True)
    (repo / "vibevoice_realtime_demo.py").write_text("print('ok')", encoding="utf-8")

    cfg = VibeVoiceConfig(
        enabled=True,
        repo_path="external/VibeVoice",
        host="127.0.0.1",
        port=3000,
    )
    runtime = VibeVoiceRuntime(config=cfg, project_root=tmp_path)
    url = runtime.build_stream_url(
        text="Hello world",
        cfg_scale=1.7,
        steps=6,
        voice="carter",
    )

    assert url.startswith("ws://127.0.0.1:3000/stream?")
    assert "text=Hello+world" in url
    assert "cfg=1.7" in url
    assert "steps=6" in url
    assert "voice=carter" in url


def test_pcm16_to_wav_bytes_has_valid_riff_header():
    # 4 mono samples = 8 bytes in PCM16
    pcm = b"\x00\x00\x01\x00\xff\x7f\x00\x80"
    wav = VibeVoiceRuntime.pcm16_to_wav_bytes(
        pcm16_bytes=pcm,
        sample_rate=DEFAULT_SAMPLE_RATE,
        channels=1,
    )

    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert len(wav) > len(pcm)

