# ⚡ QUICK REFERENCE — Interview Copilot v4.0

**Guía Rápida para Desarrolladores y Usuarios**
- **Función:** Búsqueda rápida de información
- **Formato:** Tablas, comandos, URLs, errores comunes

---

## 🔍 BÚSQUEDA RÁPIDA

### Módulos por Función

| Necesito... | Módulo | Clase | Archivo |
|-------------|--------|-------|---------|
| Capturar audio | Audio | `AudioCaptureAgent` | `src/audio/capture.py` |
| Transcribir usuario | Transcription | `OpenAIRealtimeTranscriber` | `src/transcription/openai_realtime.py` |
| Transcribir entrevistador | Transcription | `DeepgramTranscriber` | `src/transcription/deepgram_transcriber.py` |
| Filtrar preguntas fake | Knowledge | `QuestionFilter` | `src/knowledge/question_filter.py` |
| Clasificar tipo pregunta | Knowledge | `QuestionClassifier` | `src/knowledge/classifier.py` |
| Ingestar documentos KB | Knowledge | `KnowledgeIngestor` | `src/knowledge/ingest.py` |
| Buscar en KB | Knowledge | `KnowledgeRetriever` | `src/knowledge/retrieval.py` |
| Generar respuesta (Claude) | Response | `ResponseAgent` | `src/response/claude_agent.py` |
| Generar respuesta (OpenAI) | Response | `OpenAIAgent` | `src/response/openai_agent.py` |
| Generar respuesta (Gemini) | Response | `GeminiAgent` | `src/response/gemini_agent.py` |
| Mostrar teleprompter | Teleprompter | `SmartTeleprompter` | `src/teleprompter/qt_display.py` |
| Conectar teleprompter | Teleprompter | `TeleprompterBridge` | `src/teleprompter/ws_bridge.py` |
| Trackear costos | Utils | `CostTracker` | `src/cost_calculator.py` |
| Métricas | Utils | `SessionMetrics` | `src/metrics.py` |
| Alerts SLO | Utils | `AlertManager` | `src/alerting.py` |

---

## 📡 API ENDPOINTS

### WebSocket (Local)
```
ws://127.0.0.1:8765

Mensajes recibidos:
├─ {"type": "token", "data": "So"}
├─ {"type": "response_end"}
├─ {"type": "new_question"}
├─ {"type": "transcript", "speaker": "interviewer", "text": "..."}
├─ {"type": "subtitle_delta", "speaker": "...", "text": "..."}
├─ {"type": "speech_event", "speaker": "...", "event": "started"}
└─ {"type": "error", "message": "..."}
```

### Prometheus Metrics
```
http://localhost:8000/metrics

Métricas:
├─ response_latency_ms (histogram)
├─ cache_hit_rate (gauge)
└─ questions_total (counter)
```

### Archivos de Salida

| Archivo | Ubicación | Contenido |
|---------|-----------|----------|
| Conversation Log | `logs/interview_YYYY-MM-DD_HH-MM.md` | Q&A pairs |
| Session Metrics | `logs/metrics_session_YYYYMMDD_HHMMSS.json` | Latencies |
| Cost Report | `logs/costs_session_YYYYMMDD_HHMMSS.json` | API costs |
| ChromaDB | `chroma_data/` | Vectorstore |

---

## ⌨️ COMANDOS COMUNES

### Setup Inicial
```bash
# Clonar y setup
git clone https://github.com/... interview-copilot
cd interview-copilot
python -m venv venv
source venv/bin/activate  # or: venv\Scripts\activate (Windows)

# Instalar dependencias
pip install -r requirements.txt

# Configurar API keys
cp .env.example .env
# Editar .env con tus API keys

# Preparar Knowledge Base
mkdir -p kb/personal kb/company
# Copiar documentos (resume.txt, skills.txt, etc.)

# Ingestar KB (una sola vez)
python -c "from src.knowledge.ingest import KnowledgeIngestor; \
           KnowledgeIngestor().ingest_all()"
```

### Ejecución
```bash
# Ejecutar pipeline
python main.py

# Con logging verboso
LOGLEVEL=DEBUG python main.py

# Ver dispositivos audio disponibles
python -c "from src.audio.capture import AudioCaptureAgent; \
           devices = AudioCaptureAgent.list_available_devices(); \
           for d in devices: print(f'{d[\"index\"]}: {d[\"name\"]}')"
```

### Testing
```bash
# Correr tests
pytest tests/

# Con cobertura
pytest --cov=src tests/

# Test específico
pytest tests/test_question_filter.py -v
```

### Mantenimiento
```bash
# Limpiar ChromaDB (reinicia vectorstore)
python -c "from src.knowledge.ingest import KnowledgeIngestor; \
           KnowledgeIngestor().clear(); \
           KnowledgeIngestor().ingest_all()"

# Ver estadísticas KB
python -c "from src.knowledge.ingest import KnowledgeIngestor; \
           print(KnowledgeIngestor().get_stats())"

# Listar logs
ls -lh logs/

# Eliminar logs viejos
rm logs/interview_2026-02-*.md  # Borrar febrero
```

---

## 🐛 ERRORES COMUNES Y SOLUCIONES

### Error: "OPENAI_API_KEY not set"
```
❌ Error Message:
   OpenAI: APIError: Error communicating with OpenAI
   logger: OPENAI_API_KEY not set

✅ Solución:
   1. Verificar .env existe
   2. .env contiene: OPENAI_API_KEY=sk_...
   3. No hay espacios: OPENAI_API_KEY = sk_... ❌
   4. Reiniciar terminal después de editar .env
   5. export OPENAI_API_KEY=sk_... (Linux/Mac)
```

### Error: "No interviewer audio device found"
```
❌ Error Message:
   No interviewer audio device found — tried Voicemeeter B2 and Stereo Mix.
   Only user audio will be captured.

✅ Solución:
   1. Instalar Voicemeeter Banana:
      https://vb-audio.com/Voicemeeter/banana.htm
   
   2. Configurar en Voicemeeter:
      ├─ Hardware In 1: Tu micrófono
      ├─ A1 (Main): Output a tus auriculares
      ├─ B1 (Bus): Input de aplicación (Zoom)
      └─ B2 (Bus): Tu micrófono
   
   3. En .env:
      VOICEMEETER_DEVICE_USER="VoiceMeeter Aux Output B2"
      VOICEMEETER_DEVICE_INT="VoiceMeeter Out Bus B1"
   
   4. Reiniciar python main.py

   Alternative (fallback):
   └─ Habilitar Stereo Mix en Windows:
      Sound settings → Recording → Stereo Mix → Enable
```

### Error: "ChromaDB collection is empty"
```
❌ Error Message:
   KB is empty — run ingestion first.
   Place documents in kb/personal/ or kb/company/.

✅ Solución:
   1. Copiar documentos a kb/personal/ y kb/company/
      ├─ kb/personal/resume.txt
      ├─ kb/personal/skills.txt
      └─ kb/company/job_description.txt
   
   2. Ingestar:
      python -c "from src.knowledge.ingest import KnowledgeIngestor; \
                 KnowledgeIngestor().ingest_all()"
   
   3. Verificar:
      python -c "from src.knowledge.ingest import KnowledgeIngestor; \
                 print(KnowledgeIngestor().get_stats())"
      
      Expected output:
      {'collection': 'interview_kb', 'total_chunks': 42, ...}
```

### Error: "Teleprompter connection refused"
```
❌ Error Message:
   Connection refused (server not running?).
   Retrying (1/10)...

✅ Solución:
   1. Verificar que main.py está ejecutándose
      └─ Debe estar en otra terminal
   
   2. Verificar puerto 8765 no está en uso:
      Windows:  netstat -ano | findstr 8765
      Linux:    lsof -i :8765
   
   3. Si puerto en uso:
      ├─ Cambiar puerto en main.py: WS_PORT = 8765 → 8766
      └─ Cambiar en ws_bridge.py: DEFAULT_WS_URL = "ws://127.0.0.1:8766"
   
   4. Firewall: Permitir localhost:8765 en Windows Defender
```

### Error: "DEEPGRAM_API_KEY not set"
```
❌ Error Message:
   DEEPGRAM_API_KEY not set — transcription disabled.

✅ Solución:
   1. Obtener API key desde https://console.deepgram.com/
   2. En .env: DEEPGRAM_API_KEY=...
   3. Si no quieres usar Deepgram:
      └─ Editar main.py: usar OpenAI para ambos canales
         pipeline.transcriber_int = OpenAIRealtimeTranscriber(...)
```

### Error: "Model not found: gpt-4o-mini-transcribe"
```
❌ Error Message:
   NotFoundError: The model `gpt-4o-mini-transcribe` does not exist

✅ Solución:
   1. API key de OpenAI no tiene acceso a Realtime API
      └─ Solicitar acceso: https://platform.openai.com/account/billing/limits
   
   2. Fallback a Deepgram para ambos canales:
      └─ Editar transcription logic en main.py
```

### Error: "TTFT > 30 segundos"
```
❌ Error Message:
   Response generation timeout for: Tell me about yourself

✅ Soluciones:
   1. Reducir tamaño KB (eliminar chunks innecesarios)
   2. Reducir TOP_K en retrieval.py: {"personal": 2} en lugar de 3
   3. Cambiar modelo: GPT-4o-mini (más rápido que Claude)
   4. Verificar latencia de red: ping api.openai.com
   5. Aumentar timeout en main.py: async with asyncio.timeout(60):
```

### Error: PyQt5 Import Error
```
❌ Error Message:
   ModuleNotFoundError: No module named 'PyQt5'

✅ Solución:
   1. Instalar:
      pip install PyQt5==5.15.11
   
   2. Si sigue fallando (Linux):
      sudo apt-get install python3-pyqt5
   
   3. Alternativa (headless mode):
      └─ Desactivar teleprompter:
         _teleprompter_proc = None  # En main.py
```

---

## 📊 INTERPRETACIÓN DE MÉTRICAS

### Session Metrics JSON
```json
{
  "avg_latency_ms": 4250.5,
  "cache_hit_rate": 0.8,
  "questions": [
    {"duration_ms": 3800, "cache_hit": false, ...}
  ]
}

Interpretación:
├─ avg_latency_ms = 4250ms → Bueno (< 5000ms SLO)
├─ cache_hit_rate = 80% → Excelente (> 75% objetivo)
└─ Primera pregunta sin cache (normal)
   Segunda pregunta con cache (esperado)
```

### Cost Report JSON
```json
{
  "total_cost_usd": 0.084,
  "questions_processed": 8,
  "costs_by_category": {
    "transcription_input": 0.0017,
    "generation": 0.0606
  }
}

Interpretación:
├─ total_cost_usd = $0.084 para 8 preguntas
├─ Costo promedio = $0.0105 por pregunta
└─ Generation (~72%) es mayor costo vs. transcription (~2%)
   → Optimizar: cache hits, modelo más barato
```

### Prometheus Metrics
```
response_latency_ms_bucket{le="5000.0"} 45.0

Interpretación:
├─ De 50 preguntas, 45 fueron < 5000ms
├─ 90% tasa de éxito en SLO
└─ 5 preguntas violaron SLO (outliers)
```

---

## 📚 REFERENCIA RÁPIDA DE CLASES

### AudioCaptureAgent
```python
from src.audio.capture import AudioCaptureAgent

agent = AudioCaptureAgent(
    device_user="Voicemeeter B2",
    device_interviewer="Voicemeeter B1",
    sample_rate=16000,
    chunk_ms=100
)

await agent.start()
# agent.user_queue → bytes stream
# agent.int_queue → bytes stream
await agent.stop()

agent.get_audio_levels()  # {"user_rms": 1234.0, ...}
AudioCaptureAgent.list_available_devices()  # [{"index": 0, "name": "...", ...}]
```

### QuestionFilter
```python
from src.knowledge.question_filter import QuestionFilter

qf = QuestionFilter()
is_real = qf.is_interview_question("Tell me about yourself")
# True

is_real = qf.is_interview_question("Um, um, let me see")
# False

qf.stats  # {"total_checked": 10, "total_passed": 8, "total_rejected": 2}
```

### QuestionClassifier
```python
from src.knowledge.classifier import QuestionClassifier

classifier = QuestionClassifier()
result = await classifier.classify("What would you do if...")
# {"type": "situational", "compound": False, "budget": 2048}

result = await classifier.classify("Tell me about yourself AND your weaknesses")
# {"type": "hybrid", "compound": True, "budget": 2048}
```

### KnowledgeRetriever
```python
from src.knowledge.retrieval import KnowledgeRetriever

retriever = KnowledgeRetriever()
chunks = await retriever.retrieve(
    query="Tell me about yourself",
    question_type="personal",
    top_k=3
)
# ["At Webhelp, I worked...", "My skills include...", ...]

formatted = retriever.format_for_prompt(chunks)
# "[KB Source 1]:\nAt Webhelp, I worked...\n\n[KB Source 2]:..."
```

### ResponseAgent (Claude)
```python
from src.response.claude_agent import ResponseAgent

agent = ResponseAgent()
await agent.warmup()  # Prime cache

async for token in agent.generate(
    question="Tell me about yourself",
    kb_chunks=["chunk1", "chunk2"],
    question_type="personal",
    thinking_budget=512
):
    print(token, end="", flush=True)

# Salida: "So basically, I'm a customer service specialist..."
```

### CostTracker
```python
from src.cost_calculator import CostTracker

tracker = CostTracker(session_id="session_2026...")

# Track transcription
tracker.track_transcription(
    speaker="interviewer",
    duration_seconds=5.2,
    api_name="deepgram"
)

# Track embedding
tracker.track_embedding(
    tokens=150,
    question="Tell me about yourself"
)

# Track generation
tracker.track_generation(
    input_tokens=2048,
    output_tokens=256,
    cache_write_tokens=1024,
    cache_read_tokens=1024
)

# Get report
report = tracker.get_session_report()
print(f"Total cost: ${report.total_cost_usd:.2f}")
```

---

## 🔌 VARIABLES DE ENTORNO

| Variable | Valor Por Defecto | Tipo | Descripción |
|----------|-------------------|------|-------------|
| OPENAI_API_KEY | (requerido) | string | OpenAI API key |
| ANTHROPIC_API_KEY | (requerido) | string | Anthropic API key |
| DEEPGRAM_API_KEY | (requerido) | string | Deepgram API key |
| GOOGLE_API_KEY | (opcional) | string | Google Gemini key |
| AUDIO_SAMPLE_RATE | 16000 | int | Hz |
| AUDIO_CHUNK_MS | 100 | int | Milliseconds |
| VOICEMEETER_DEVICE_USER | None | string | Device name |
| VOICEMEETER_DEVICE_INT | None | string | Device name |
| LOOPBACK_GAIN | 2.0 | float | Gain factor |
| LOGLEVEL | INFO | string | DEBUG, INFO, WARNING, ERROR |

---

## 📈 LATENCY QUICK LOOKUP

| Operación | P50 | P99 | Notas |
|-----------|-----|-----|-------|
| Audio capture | 100ms | 150ms | Buffer time |
| OpenAI TTFT | 600ms | 1000ms | User transcription |
| Deepgram TTFT | 250ms | 400ms | Interviewer transcription |
| Question filter | 5ms | 20ms | Rule-based |
| Classifier | 30ms | 100ms | Rule-based |
| KB embedding | 300ms | 400ms | OpenAI API |
| ChromaDB search | 50ms | 100ms | Local |
| Response TTFT | 800ms | 1500ms | Model generation |
| Teleprompter | 10ms | 50ms | Token rendering |
| Full pipeline | 4500ms | 6000ms | Total E2E |

---

## 💰 COSTOS APROXIMADOS

| Operación | Costo Unitario | Nota |
|-----------|----------------|------|
| Transcripción 1 min | $0.0003 | OpenAI Realtime |
| Transcripción 1 min | $0.0001 | Deepgram |
| Embedding 1000 chars | $0.0000005 | OpenAI (negligible) |
| Response 200 tokens | $0.0002 | OpenAI GPT-4o-mini |
| Response 200 tokens | $0.005 | Claude Sonnet |
| Cache hit 200 tokens | $0.00006 | Claude (90% descuento) |

**Ejemplo: Entrevista 30 minutos, 8 preguntas**
```
Transcripción: 30min × $0.0002/min = $0.006
Embeddings: ~0.001 (negligible)
Responses: 8 × $0.003 = $0.024
Total: ~$0.031 (3 centavos)

Con prompt caching:
├─ Primera pregunta: $0.005 (cache write)
└─ Siguientes 7: $0.0003 c/u (cache read)
Total: ~$0.008 (menos de 1 centavo)
```

---

## 🎯 CHEATSHEET: RESOLVER PROBLEMA COMÚN

```
Symptom                          → Solution
────────────────────────────────────────────────────────
Respuesta tarda > 5s            → Reducir TOP_K, cambiar modelo
Cache hit rate baja             → Verificar prompt realmente igual
Teleprompter no se conecta      → netstat -ano | grep 8765
Audio solo del micrófono        → Instalar Voicemeeter Banana
Pregunta rechazada erróneamente → Verificar NOISE_PATTERNS regex
KB vacía                        → python -c "KnowledgeIngestor().ingest_all()"
Costo muy alto                  → Cambiar a GPT-4o-mini o Gemini
Especulative hit rate bajo      → Verificar similarity threshold (0.80)
```

---

## 🚀 DEPLOY A PRODUCCIÓN

```bash
# 1. Verificar tests
pytest tests/ --cov=src

# 2. Limpiar archivos
rm -rf __pycache__ .pytest_cache

# 3. Configurar .env production
OPENAI_API_KEY=sk_...
DEEPGRAM_API_KEY=...
LOGLEVEL=WARNING  # Menos verbose

# 4. Iniciar systemd service (Linux)
cat > /etc/systemd/system/interview-copilot.service << EOF
[Unit]
Description=Interview Copilot
After=network.target

[Service]
Type=simple
User=copilot
WorkingDirectory=/opt/interview-copilot
ExecStart=/usr/bin/python3 main.py
Restart=on-failure
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable interview-copilot
systemctl start interview-copilot

# 5. Monitorear
journalctl -u interview-copilot -f
curl http://localhost:8000/metrics
```

---

## 📖 DOCUMENTACIÓN COMPLETA

| Documento | Contenido |
|-----------|----------|
| `ANALISIS_TECNICO_COMPLETO.md` | Análisis exhaustivo, código completo, flujos detallados |
| `DIAGRAMAS_Y_CASOS_DE_USO.md` | Visualizaciones, secuencias, casos reales |
| `QUICK_REFERENCE.md` (este) | Búsqueda rápida, comandos, errores |
| `README.md` | Setup básico, quick start |

---

**Última actualización:** 1 de Marzo de 2026
**Versión:** 4.0

