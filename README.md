# 🎙️ Interview Copilot v2.0

> **Copiloto de Entrevistas Bilingüe** — Real-time AI assistant for English job interviews, powered by Claude Opus 4.6 with Extended Thinking.

## 🏗️ Architecture

```
[ MIC USER ] → Bus B1 → AudioCaptureAgent → DeepgramAgent →
[ INTERVIEWER ] → Bus B2 → AudioCaptureAgent → DeepgramAgent → KnowledgeAgent (RAG)
                                                                      ↓
                                                        ResponseAgent (Claude Opus 4.6)
                                                                      ↓
                                                         TeleprompterAgent → [ DISPLAY ]
```

## ✨ Features

- **Dual Audio Capture** — Separate streams for candidate and interviewer via Voicemeeter Banana
- **Real-time Transcription** — Deepgram Nova-2 with < 300ms latency
- **RAG Knowledge Base** — Personal & company docs vectorized with ChromaDB + OpenAI embeddings
- **Adaptive AI Responses** — Claude Opus 4.6 with thinking budget adapted to question complexity
- **Smart Teleprompter** — PyQt5 overlay with streaming text, emphasis markers, and speed control
- **Question Classifier** — Auto-detects question type (personal/company/hybrid/situational/simple)

## 📁 Project Structure

```
interview-copilot/
├── .env.example               # API keys template
├── requirements.txt            # Python dependencies
├── main.py                     # FastAPI coordinator + WebSocket hub
├── antigravity.config.json     # Workspace config
├── src/
│   ├── audio/
│   │   ├── capture.py          # Dual audio stream capture
│   │   └── voicemeeter.py      # Voicemeeter config helper
│   ├── transcription/
│   │   └── deepgram_client.py  # Deepgram WebSocket streaming
│   ├── knowledge/
│   │   ├── ingest.py           # Document ingestion & vectorization
│   │   ├── retrieval.py        # RAG semantic search
│   │   └── classifier.py       # Question type classifier
│   ├── response/
│   │   └── claude_agent.py     # Claude Opus 4.6 response generator
│   └── teleprompter/
│       ├── qt_display.py       # PyQt5 overlay window
│       └── ws_bridge.py        # WebSocket bridge
├── kb/
│   ├── personal/               # Your personal KB docs (.txt)
│   └── company/                # Company research docs (.txt)
└── tests/
    ├── test_audio.py
    ├── test_knowledge.py
    └── test_latency.py
```

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure API Keys
```bash
cp .env.example .env
# Edit .env with your actual API keys
```

Required keys:
- `ANTHROPIC_API_KEY` — Claude Opus 4.6 + Haiku 4.5
- `DEEPGRAM_API_KEY` — Real-time transcription
- `OPENAI_API_KEY` — Embeddings (text-embedding-3-small)

### 3. Setup Knowledge Base
Place your documents in:
- `kb/personal/` — Your resume, experience, skills (`.txt` files)
- `kb/company/` — Company info, job description, values (`.txt` files)

### 4. Ingest KB
```python
from src.knowledge.ingest import KnowledgeIngestor
ingestor = KnowledgeIngestor()
stats = ingestor.ingest_all()
print(f"Ingested {stats['total_chunks']} chunks")
```

### 5. Start the Server
```bash
python main.py
# Server runs at http://localhost:8000
```

### 6. Launch Teleprompter
```bash
python -m src.teleprompter.ws_bridge
```

## ⌨️ Teleprompter Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+↑/↓` | Font size ±2px |
| `Ctrl+←/→` | WPM speed ±10 |
| `Ctrl+O` | Cycle opacity (70/80/90%) |
| `Escape` | Clear text |
| `Ctrl+Q` | Quit |

## 📊 Latency Targets

| Stage | Target p50 | Target p95 |
|-------|-----------|-----------|
| Audio → Deepgram | < 50ms | < 100ms |
| Transcription | < 250ms | < 350ms |
| RAG Retrieval | < 80ms | < 150ms |
| Claude Response | < 800ms | < 1500ms |
| → Teleprompter | < 50ms | < 80ms |
| **End-to-end** | **< 1.2s** | **< 2.2s** |

## 🧪 Run Tests
```bash
python -m pytest tests/ -v
```

## 📋 Pre-Interview Checklist

1. ✅ Voicemeeter Banana active (B1=mic, B2=system audio)
2. ✅ Close unnecessary apps (free up RAM)
3. ✅ Run `python -m pytest tests/test_latency.py -v`
4. ✅ Test KB with 3-4 practice questions
5. ✅ Calibrate teleprompter speed (5 min)
6. ✅ Practice 5 frequent questions in live mode

## 🔧 Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python FastAPI + asyncio |
| LLM (Primary) | Claude Opus 4.6 (Extended Thinking) |
| LLM (Classifier) | Claude Haiku 4.5 |
| Transcription | Deepgram Nova-2 (WebSocket) |
| Audio | Voicemeeter Banana + sounddevice |
| Vector Store | ChromaDB |
| Embeddings | OpenAI text-embedding-3-small |
| Teleprompter | PyQt5 |

---

*Built with Google Antigravity + Claude Opus 4.6 · February 2026*
