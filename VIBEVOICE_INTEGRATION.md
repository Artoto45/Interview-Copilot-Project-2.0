# VibeVoice Integration (Microsoft)

This project now includes an optional integration module for Microsoft VibeVoice realtime TTS:

- Module: `src/voice/vibevoice_manager.py`
- Package exports: `src/voice/__init__.py`
- Tests: `tests/test_vibevoice_manager.py`

## What It Adds

1. Installation planner/executor for the official repo (`VibeVoiceInstaller`).
2. Runtime manager to launch/stop the realtime websocket demo (`VibeVoiceRuntime`).
3. PCM16 websocket synthesis + WAV export helpers.
4. CLI utility mode for planning/installing/synthesizing.

## Official Upstream References

- Repo: `https://github.com/microsoft/VibeVoice`
- Realtime docs: `docs/vibevoice-realtime-0.5b.md` in upstream repo
- Default model: `microsoft/VibeVoice-Realtime-0.5B`

## Environment Variables

Use these keys in `.env` (already added to `.env.example`):

- `VIBEVOICE_ENABLED`
- `VIBEVOICE_REPO_URL`
- `VIBEVOICE_REPO_PATH`
- `VIBEVOICE_MODEL_PATH`
- `VIBEVOICE_DEVICE`
- `VIBEVOICE_HOST`
- `VIBEVOICE_PORT`
- `VIBEVOICE_AUTO_CLONE`
- `VIBEVOICE_AUTO_INSTALL`
- `VIBEVOICE_PYTHON` (optional)

## Quick Commands

### 1) See install plan

```bash
python -m src.voice.vibevoice_manager --action plan
```

### 2) Install VibeVoice (editable + streaming extras)

```bash
python -m src.voice.vibevoice_manager --action install
```

### 3) Launch realtime server

```bash
python -m src.voice.vibevoice_manager --action start --device cuda
```

### 4) One-shot synthesis to WAV

```bash
python -m src.voice.vibevoice_manager --action synthesize --text "Hello from Interview Copilot." --output logs/vibevoice_demo.wav
```

## Notes

- The integration is optional and does not alter current interview pipeline behavior.
- For realtime performance, GPU and proper CUDA stack are strongly recommended by upstream.
