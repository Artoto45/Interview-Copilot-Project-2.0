# Interview Copilot v4.0

**Advanced Real-Time Interview Preparation Assistant**

Dual-channel transcription + semantic knowledge retrieval + streaming response generation powered by OpenAI, Deepgram, and ChromaDB.

![GitHub Stars](https://img.shields.io/github/stars/artoto45-ship-it/Interview-Copilot-Project?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green)
![Python](https://img.shields.io/badge/python-3.10+-blue)

---

## 🎯 Overview

Interview Copilot is a production-ready intelligent interview assistant that:

- **📻 Captures dual audio streams** — your microphone + system audio (Zoom/Teams/Meet)
- **🎤 Real-time transcription** — OpenAI Realtime (user) + Deepgram Nova-3 (interviewer)
- **🧠 RAG-powered knowledge retrieval** — semantic search over your personal KB
- **⚡ Streams smart responses** — GPT-4o-mini with 3 latency optimizations
- **📺 Visual teleprompter** — PyQt5 overlay showing suggested answers
- **💰 Cost tracking** — detailed breakdown of API usage
- **📊 Observability** — Prometheus metrics + session logging

**Typical Performance:**
- Total latency: **3-8 seconds** (with optimizations enabled)
- Cost per 5-question session: **$0.20-0.50 USD**
- P95 latency SLO: **< 5 seconds**

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+**
- **Voicemeeter Banana** (free virtual audio mixer)
  - Download: https://vb-audio.com/Voicemeeter/
- **API Keys:**
  - OpenAI: https://platform.openai.com/api-keys
  - Deepgram: https://console.deepgram.com
  - (Optional) Anthropic: https://console.anthropic.com

### Installation

```bash
# 1. Clone repository
git clone https://github.com/artoto45-ship-it/Interview-Copilot-Project.git
cd Interview-Copilot-Project

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\activate  # Windows
# or: source venv/bin/activate  # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt
pip install deepgram-sdk  # Currently missing from requirements.txt

# 4. Configure environment
cp .env.example .env
nano .env  # Edit with your API keys and device names

# 5. Run
python main.py
```

### Configuration

Edit `.env` file:

```bash
# OpenAI (transcription + response generation)
OPENAI_API_KEY=sk-...

# Deepgram (interviewer transcription, optional)
DEEPGRAM_API_KEY=...

# Voicemeeter device names
VOICEMEETER_DEVICE_USER=VoiceMeeter Out B1
VOICEMEETER_DEVICE_INT=VoiceMeeter Out B2
```

---

## 📚 Knowledge Base Setup

Interview Copilot learns from your personal knowledge base. Create `kb/` directory:

```bash
kb/
├── personal/
│   ├── about_you.md          # "Tell me about yourself" answer
│   ├── strengths.md          # Your top 5 strengths
│   ├── experience.md         # Technical experience & projects
│   └── achievements.md       # Major accomplishments
└── company/
    ├── company_research.md   # Target company info
    └── role_research.md      # Specific role details
```

**Example `kb/personal/experience.md`:**

```markdown
# Professional Experience

I have 5+ years of experience in:
- **Python Development**: Built distributed systems, APIs, data pipelines
- **Cloud Infrastructure**: AWS, Docker, Kubernetes
- **Team Leadership**: Led team of 3 engineers, mentored junior devs
- **Remote Work**: Successfully worked remotely for 3+ years

Recent projects:
- Redesigned legacy system → 40% performance improvement
- Led migration from monolith to microservices
- Implemented CI/CD pipeline (Jenkins → GitHub Actions)
```

The system will automatically:
1. Index these documents in ChromaDB
2. Embed them using text-embedding-3-small
3. Retrieve relevant chunks when questions are asked

---

## 🏗️ Architecture

### High-Level Flow

```
Audio Input (dual-channel)
    ↓
Transcription (OpenAI Realtime + Deepgram)
    ↓
Question Filter (rule-based, <1ms)
    ↓
Question Classifier (personal/company/situational, etc.)
    ↓
RAG Pipeline
    ├─ Query Embedding (OpenAI text-embedding-3-small)
    ├─ Semantic Search (ChromaDB)
    └─ KB Context Retrieval
    ↓
Response Generation (GPT-4o-mini streaming)
    ↓
Teleprompter Display (PyQt5 + WebSocket)
    ↓
Output (visual suggestions + audio sync)
```

### Optimization Pipeline

**3 Speed Optimizations:**

1. **Instant Openers** — Send opening phrase (0ms latency) while API processes
2. **Speculative Generation** — Pre-fetch KB and pre-generate during transcription
3. **Semantic Caching** — Check if delta text is similar enough to use buffered tokens

Result: **45-60% latency reduction** on 40-50% of questions.

---

## 📊 Detailed Documentation

- **[DOCUMENTACION_TECNICA_COMPLETA.md](DOCUMENTACION_TECNICA_COMPLETA.md)** — Complete technical reference with module-by-module breakdown
- **[GUIA_SEGURIDAD_GITHUB.md](GUIA_SEGURIDAD_GITHUB.md)** — Security checklist before pushing to GitHub

---

## 🔐 Security & Privacy

**This repository does NOT contain:**
- ❌ `.env` files with API keys
- ❌ Personal KB documents (Interview answers)
- ❌ Session logs or chat history
- ❌ Audio recordings
- ❌ Sensitive company information

**This IS included:**
- ✅ Code source (fully open)
- ✅ `.env.example` template
- ✅ Empty KB directory structure
- ✅ All documentation & diagrams

**To use safely:**
```bash
# Create your OWN local secrets (never commit)
cp .env.example .env
# Fill in YOUR API keys (local machine only)

# Create your personal KB (git-ignored)
mkdir -p kb/{personal,company}
echo "My experience..." > kb/personal/experience.md
# These stay on your machine
```

See [GUIA_SEGURIDAD_GITHUB.md](GUIA_SEGURIDAD_GITHUB.md) for complete security guidelines.

---

## 💾 Cost Tracking

Interview Copilot tracks every API call and calculates costs:

```json
{
  "session_id": "session_20260301_120000",
  "costs_by_category": {
    "transcription_input": 0.012,        // OpenAI Realtime
    "transcription_interviewer": 0.008,  // Deepgram
    "embedding": 0.00024,                // KB retrieval
    "generation": 0.0825                 // GPT-4o-mini
  },
  "total_cost_usd": 0.103,
  "questions_processed": 5,
  "responses_generated": 5
}
```

**Typical Breakdown:**
| Component | Cost/5 Questions |
|-----------|-----------------|
| Transcription (user) | $0.01 |
| Transcription (interviewer) | $0.01 |
| Embeddings (KB search) | $0.0003 |
| Response Generation | $0.08 |
| **TOTAL** | **~$0.10** |

Full cost tracking in `logs/costs_*.json`.

---

## 📊 Monitoring & Metrics

### Prometheus Export

```bash
# Metrics available on http://127.0.0.1:8000/metrics
curl http://127.0.0.1:8000/metrics | grep response_latency
```

Tracked metrics:
- `response_latency_ms` — Histogram of total pipeline latency
- `cache_hit_rate` — Current session cache effectiveness
- `questions_total` — Counter of processed questions

### Session Reports

After each session:
```
logs/
├── interview_2026-03-01_10-24.md          # Q&A transcript
├── metrics_session_20260301_102400.json   # Latencies
└── costs_session_20260301_102400.json     # Cost breakdown
```

---

## 🛠️ Development

### Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=src  # With coverage
```

### Project Structure

```
Interview-Copilot-Project/
├── src/
│   ├── audio/              # Dual-channel audio capture
│   ├── transcription/      # OpenAI Realtime + Deepgram
│   ├── knowledge/          # RAG: retrieval, classification, filtering
│   ├── response/           # LLM response generation
│   ├── teleprompter/       # PyQt5 UI + WebSocket bridge
│   ├── metrics.py          # Session metrics tracking
│   ├── cost_calculator.py  # API cost accounting
│   ├── alerting.py         # SLO monitoring
│   └── prometheus.py       # Prometheus metrics export
├── kb/                     # Knowledge base (git-ignored)
│   ├── personal/           # Your responses
│   └── company/            # Company research
├── logs/                   # Session logs (git-ignored)
├── tests/                  # Unit tests
├── main.py                 # Entry point
├── requirements.txt        # Dependencies
├── .env.example           # Configuration template
└── push_safe_to_github.py # Safe push script
```

### Key Modules

- **`main.py`** — Async coordinator orchestrating the pipeline
- **`audio/capture.py`** — Dual-stream audio via sounddevice
- **`transcription/openai_realtime.py`** — User audio → text
- **`transcription/deepgram_transcriber.py`** — System audio → text
- **`knowledge/retrieval.py`** — Semantic search over KB
- **`knowledge/classifier.py`** — Question type detection
- **`response/openai_agent.py`** — GPT-4o-mini streaming
- **`teleprompter/qt_display.py`** — Visual display

---

## ⚠️ Troubleshooting

### "No interviewer audio device found"
**Solution:** Install Voicemeeter Banana and configure routes:
```
Voicemeeter → Menu → Macro Buttons (configure buses)
- B1 = System audio output (Zoom input)
- B2 = Mic input
```

### "OPENAI_API_KEY not set"
**Solution:**
```bash
cp .env.example .env
nano .env
# Add your actual API key
```

### "Low audio quality on Stereo Mix"
**Solution:** Adjust `LOOPBACK_GAIN` in `.env`:
```bash
LOOPBACK_GAIN=3.0  # Increase from default 2.0
```

### "Slow response generation"
**Check:**
1. KB might be empty — run ingestion first
2. Network latency — try a different location
3. API rate limits — check OpenAI usage dashboard

---

## 📝 Logging

Detailed logs written to stdout and `logs/interview_*.md`:

```
10:23:45 │ coordinator   │ INFO    │ Pipeline is RUNNING — ready for interview
10:24:05 │ coordinator   │ INFO    │ on_speech_event: interviewer started
10:24:08 │ coordinator   │ INFO    │ TRANSCRIPT [interviewer] Tell me about your experience

10:24:08 │ knowledge     │ INFO    │ Classified: type=personal, budget=512
10:24:08 │ coordinator   │ INFO    │ Instant opener: So basically, in my experience...

10:24:09 │ coordinator   │ INFO    │ SPECULATIVE GEN HIT ⚡⚡ Flushing 145 buffered tokens
10:24:11 │ coordinator   │ INFO    │ SPECULATIVE response: 1024 chars (total pipeline: 6123ms) ⚡⚡
```

---

## 🤝 Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

**Before submitting:** Run security check:
```bash
python push_safe_to_github.py --check
```

---

## 📄 License

This project is licensed under the MIT License — see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

Built with:
- **OpenAI** — Realtime API + GPT-4o-mini
- **Deepgram** — Nova-3 transcription
- **Anthropic** — Claude (optional classifier)
- **ChromaDB** — Vector embeddings
- **PyQt5** — UI framework
- **Prometheus** — Metrics export

---

## 📞 Support

For issues, questions, or feedback:
- GitHub Issues: [Interview-Copilot-Project/issues](https://github.com/artoto45-ship-it/Interview-Copilot-Project/issues)
- Documentation: See [DOCUMENTACION_TECNICA_COMPLETA.md](DOCUMENTACION_TECNICA_COMPLETA.md)
- Security concerns: See [GUIA_SEGURIDAD_GITHUB.md](GUIA_SEGURIDAD_GITHUB.md)

---

**Ready to ace your next interview? 🎤**

```bash
python main.py
```

Good luck! 🚀

