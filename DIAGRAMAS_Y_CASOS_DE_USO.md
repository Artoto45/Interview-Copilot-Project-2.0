# 📊 DIAGRAMAS TÉCNICOS Y CASOS DE USO — Interview Copilot v4.0

**Documento Complementario con Visualizaciones**
- **Fecha:** 1 de Marzo de 2026
- **Objetivo:** Entender visualmente el flujo del sistema

---

## 📈 DIAGRAMAS DE FLUJO

### 1. FLUJO GENERAL DEL SISTEMA

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         INTERVIEW SESSION                               │
└─────────────────────────────────────────────────────────────────────────┘

TIEMPO REAL →

[00:00] Candidato y entrevistador en llamada (Zoom)
         ├─ Candidato: "Hello, nice to meet you"
         └─ Entrevistador: "Tell me about yourself"
              │
              ▼
[00:02] AudioCaptureAgent captura
         ├─ User Queue: candidato microfono
         └─ Int Queue: audio del sistema (entrevistador)
              │
              ▼
[00:05] Transcriptores procesan
         ├─ OpenAI Realtime: candidato transcription
         └─ Deepgram: entrevistador transcription
              │
              ▼ (entrevistador termina de hablar)
[00:10] on_speech_event("interviewer", "stopped")
         ├─ Especulative retrieval starts
         └─ Especulative generation starts
              │ (background, durante transcripción final)
              ▼
[00:15] Transcripción finaliza: "Tell me about yourself"
         ├─ Filtro de preguntas: ACCEPT
         ├─ Clasificación: type=personal, budget=512
         ├─ Check especulative: ¿KB + tokens ready?
         └─ SI → Flush buffered tokens
             NO → Start fresh retrieval
              │
              ▼
[00:16] Retrieve KB chunks
         ├─ Embedding: "Tell me about yourself"
         ├─ Cosine search: top 3 chunks
         └─ Format para prompt
              │
              ▼
[00:18] Generate response (Claude/OpenAI/Gemini)
         ├─ System prompt
         ├─ KB context
         ├─ Question
         └─ Stream tokens
              │
              ▼ SIMULTÁNEAMENTE:
         ├─ Broadcast tokens → Teleprompter
         └─ Log conversation → file
              │
              ▼
[00:22] Teleprompter display
         ├─ Show instant opener (0ms)
         ├─ Stream response tokens
         ├─ Format [PAUSE] + **bold**
         └─ Auto-scroll
              │
              ▼
[00:27] Candidato lee respuesta
         ├─ "So basically, in my experience at Webhelp..."
         └─ Completa respuesta sugerida
              │
              ▼
[00:32] Ciclo repite para siguiente pregunta
```

---

### 2. ARQUITECTURA DE DATOS (Data Flow Diagram)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           AUDIO LAYER                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  User Microphone          Voicemeeter B2          System Audio          │
│  (PCM WAV)                (Virtual)               (Zoom/Teams)          │
│      │                        │                        │                │
│      └────────────────────────┴────────────────────────┘                │
│                               │                                          │
│                  sounddevice.RawInputStream                             │
│              16kHz, 16-bit, mono, 100ms chunks                          │
│                               │                                          │
└───────────────────────────────┼──────────────────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                │                               │
                ▼                               ▼
        ┌───────────────┐              ┌───────────────┐
        │  User Queue   │              │   Int Queue   │
        │ (asyncio)     │              │ (asyncio)     │
        │ maxsize=100   │              │ maxsize=100   │
        └───────┬───────┘              └───────┬───────┘
                │                              │
┌───────────────┴────────────────────────────────┴──────────────────────────┐
│                    TRANSCRIPTION LAYER                                    │
├───────────────────────────────────────────────────────────────────────────┤
│                                                                           │
│  OpenAIRealtimeTranscriber              DeepgramTranscriber             │
│  (User Channel)                         (Interviewer Channel)            │
│                                                                           │
│  ├─ WebSocket → OpenAI Realtime        ├─ WebSocket → Deepgram        │
│  ├─ Resample: 16kHz → 24kHz            ├─ Smart formatting              │
│  ├─ VAD + Speech detection              ├─ Endpointing: 200ms            │
│  │                                      ├─ Real-time transcription       │
│  └─ Callbacks:                          │                                │
│     ├─ on_transcript(speaker, text)    └─ Callbacks:                   │
│     ├─ on_delta(speaker, partial)         ├─ on_transcript(...)         │
│     └─ on_speech_event(speaker, event)    ├─ on_delta(...)              │
│                                           └─ on_speech_event(...)        │
│                                                                           │
└────────────────────────┬────────────────────────────────────────────────┘
                         │
                         ▼
            ┌─────────────────────────────┐
            │  on_transcript() Callback   │
            │  (speaker, full_text)       │
            └────────────┬────────────────┘
                         │
        ┌────────────────┴────────────────┐
        │                                 │
        ▼                                 ▼
   ┌─────────────┐               ┌──────────────────┐
   │ speaker ==  │               │ speaker ==       │
   │ "user"      │               │ "interviewer"    │
   └──────┬──────┘               └────────┬─────────┘
          │                               │
          ▼                               ▼
   ┌──────────────────┐         ┌────────────────────┐
   │ Save to          │         │ QuestionFilter     │
   │ conversation     │         │ .is_interview...() │
   │ history          │         └─────────┬──────────┘
   │ (context)        │                   │
   └──────────────────┘        ┌──────────┴───────────┐
                               │                      │
                          ACCEPT                   REJECT
                          (boolean)                (boolean)
                               │                      │
                               ▼                      ▼
                    ┌──────────────────┐      ┌─────────────┐
                    │ process_question │      │ Log + skip  │
                    │ (question_text)  │      └─────────────┘
                    └────────┬─────────┘
                             │
┌────────────────────────────┴──────────────────────────────────────────────┐
│                     PROCESSING LAYER                                      │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  1. CLASSIFY                  2. RETRIEVE KB              3. GENERATE     │
│                                                                            │
│  ┌──────────────────┐        ┌──────────────────┐     ┌────────────────┐ │
│  │QuestionClassif   │        │KnowledgeRetriever│     │ResponseAgent   │ │
│  │ier               │        │                  │     │(Claude/OpenAI/ │ │
│  ├─ _fallback_      │        ├─ _embed_query()  │     │ Gemini)        │ │
│  │  classify()      │        ├─ ChromaDB query  │     ├─ generate()    │ │
│  ├─ Type detection  │        ├─ Top-k retrieval │     ├─ System prompt │ │
│  ├─ Compound check  │        ├─ Where filter    │     ├─ KB context    │ │
│  ├─ Budget assign   │        ├─ Format for      │     ├─ Streaming     │ │
│  │                  │        │  prompt          │     ├─ Tokens        │ │
│  └────────┬─────────┘        └────────┬─────────┘     └────────┬───────┘ │
│           │                          │                        │          │
│        OUPUT:                      OUTPUT:                  OUTPUT:       │
│    {type, compound,           list[str] (chunks)         AsyncIterator   │
│     budget}                                                [str] (tokens)  │
│                                                                            │
└────────────────┬─────────────────────┬─────────────────────┬─────────────┘
                 │                     │                     │
                 └─────────────────────┴─────────────────────┘
                                       │
                   ┌───────────────────┴───────────────────┐
                   │                                       │
                   ▼                                       ▼
         ┌──────────────────────┐           ┌──────────────────────┐
         │ broadcast_token()    │           │ Conversation Log     │
         │                      │           │ (Markdown file)      │
         │ WebSocket → all      │           │                      │
         │ teleprompter clients │           │ - Question           │
         │                      │           │ - Response           │
         └──────────┬───────────┘           │ - Type               │
                    │                       │ - Timestamp          │
                    ▼                       └──────────────────────┘
┌──────────────────────────────────────────────────────────────────────────┐
│                       DISPLAY LAYER                                      │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  TeleprompterBridge         SmartTeleprompter (PyQt5)                   │
│  (WebSocket Client)         (Overlay Window)                            │
│                                                                          │
│  ├─ Connect to ws://        ├─ Receive tokens                          │
│  │  127.0.0.1:8765          ├─ Append to text                          │
│  ├─ Listen for messages     ├─ Format [PAUSE], **bold**               │
│  ├─ Dispatch to PyQt5       ├─ Auto-scroll                             │
│  │                          ├─ Control WPM/font/opacity                │
│  └─ Reconnect auto          ├─ Always-on-top overlay                   │
│                             └─ Display to candidate                    │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

### 3. SECUENCIA DETALLADA: PREGUNTA COMPLETA

```
Timeline: Desde que el entrevistador termina de hablar

T=0ms:      Entrevistador termina: "Tell me about yourself?"
            ├─ Deepgram VAD detecta fin de habla
            └─ on_speech_event("interviewer", "stopped")
                 │
                 ├─ Get delta text from live_buffer
                 ├─ Start speculative KB retrieval
                 └─ Start speculative generation
                      │
T=5ms:      Teleprompter visible: [● LISTENING]
            ├─ on_speech_event("user", "started") si candidato habla
            └─ on_speech_event("user", "stopped") si no

T=0-5000ms: Transcripción processando (background)
            ├─ Deepgram: "Tell me about yourself?"
            ├─ OpenAI: User transcription (if candidate speaks)
            ├─ Speculative KB retrieval running
            └─ Speculative generation running
                 │
                 ▼
T=5000ms:   Final transcript arrives:
            └─ on_transcript("interviewer", "Tell me about yourself")
                 │
                 ├─ QuestionFilter.is_interview_question()
                 │  ├─ Check 1: Noise patterns? NO
                 │  ├─ Check 2: Min words? YES (4 words)
                 │  ├─ Check 3: Interview signals? YES ("tell me")
                 │  └─ → ACCEPT
                 │
                 ▼
T=5050ms:   process_question("Tell me about yourself")
            ├─ Broadcast: {"type": "new_question"}
            ├─ Classify: type="personal", compound=False, budget=512
            ├─ Classify latency: 50ms
            │
            ├─ Check speculative generation ready?
            │  ├─ g_task.done()? Check...
            │  └─ If YES and similar:
            │     └─ Flush 50 buffered tokens immediately
            │        └─ Jump to T=6050ms (savings: 3-4s)
            │
            └─ If NO speculative hit:
                 │
                 ▼
T=5550ms:   Get instant opener
            └─ "So basically, in my experience at Webhelp… "
                 │
                 ├─ Broadcast immediately
                 └─ Teleprompter shows instantly
                      │
                      ▼
T=5555ms:   Check speculative KB
            ├─ r_task = _speculative.get_retrieval_task()
            ├─ If ready: use cached chunks
            └─ If not ready: fetch fresh
                 │
                 ▼ (fresh fetch path)
T=5560ms:   KnowledgeRetriever.retrieve()
            ├─ Generate embedding: "Tell me about yourself"
            │  └─ OpenAI API call (300-400ms)
            │
            ├─ ChromaDB search: cosine similarity
            │  ├─ Query embedding: [1536] floats
            │  ├─ Where filter: {"category": "personal"}
            │  ├─ Top-k: 3
            │  └─ Results in ~50-100ms
            │
            └─ Format chunks for prompt
                 │
T=6050ms:   KB retrieval complete (450ms elapsed)
            └─ Have: 3 chunks about personal experience
                 │
                 ▼
T=6055ms:   ResponseAgent.generate() starts
            ├─ Build user message:
            │  ├─ [QUESTION TYPE]: personal
            │  ├─ [LENGTH]: 3-4 sentences
            │  ├─ [KNOWLEDGE BASE]: {chunks}
            │  └─ [INTERVIEWER QUESTION]: Tell me about yourself
            │
            ├─ System prompt with cache_control
            ├─ Temperature: 0.3
            ├─ Max tokens: 1024
            └─ Stream: true
                 │
T=6500ms:   First token arrives
            │  └─ "So" (already shown "So basically…" from opener)
            │
T=6510ms:   Broadcast first token
            │  └─ WebSocket → Teleprompter
            │
T=6520ms:   Teleprompter displays: "So basically, in my experience at Webhelp… So"
            │
T=6530-T=10030ms:  Remaining tokens stream in
            ├─ ~80-100 tokens (for 3-4 sentence response)
            ├─ Broadcast at ~15-20 tokens/sec
            ├─ Display updates: every 5-10ms (1-2 tokens)
            ├─ Teleprompter auto-scrolls
            └─ Log accumulated response to file
                 │
                 ▼
T=10050ms:  Response complete (4995ms E2E from transcript)
            ├─ Broadcast: {"type": "response_end"}
            ├─ Teleprompter shows full response
            ├─ Save to conversation log
            ├─ Update metrics
            ├─ Track costs
            └─ Ready for next question
                 │
                 ▼
T=10100ms:  Entrevistador pregunta siguiente...
            └─ Ciclo repite

RESUMEN TIMELINE:
    T=0ms:      Fin de habla detectada
    T=5000ms:   Transcripción final llega (5s)
    T=5050ms:   Clasificación (50ms)
    T=5600ms:   KB retrieval finaliza (550ms from transcript)
    T=6050ms:   Generación comienza
    T=6500ms:   Primer token generado (TTFT ~950ms desde transcript)
    T=10050ms:  Respuesta completa (5000ms desde transcript)
    
    TOTAL E2E: ~10 segundos desde que entrevistador empieza a hablar
    PERO: Candidato ve respuesta en T=5550ms (instant opener)
```

---

### 4. ARQUITECTURA DE ESTADO

```
┌──────────────────────────────────────────────────────────────────────┐
│                        PipelineState                                 │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  STATE COUNTERS:                                                    │
│  ├─ total_questions: int (0, 1, 2, ...)                            │
│  ├─ total_responses: int (0, 1, 2, ...)                            │
│  └─ last_activity: datetime.isoformat()                            │
│                                                                      │
│  AGENT INSTANCES:                                                   │
│  ├─ audio_agent: AudioCaptureAgent                                 │
│  │  ├─ user_queue: asyncio.Queue[bytes]                           │
│  │  └─ int_queue: asyncio.Queue[bytes]                            │
│  │                                                                  │
│  ├─ transcriber_user: OpenAIRealtimeTranscriber                   │
│  │  ├─ _live_buffer: str (delta text)                            │
│  │  ├─ _turn_buffer: list[str] (segments)                        │
│  │  └─ _recent_turns: deque (history)                            │
│  │                                                                  │
│  ├─ transcriber_int: DeepgramTranscriber                          │
│  │  ├─ _live_buffer: str                                          │
│  │  ├─ _turn_buffer: list[str]                                   │
│  │  └─ _speech_active: bool                                       │
│  │                                                                  │
│  ├─ retriever: KnowledgeRetriever                                 │
│  │  └─ collection: ChromaDB collection                            │
│  │                                                                  │
│  ├─ classifier: QuestionClassifier                                │
│  │  └─ (stateless)                                                │
│  │                                                                  │
│  ├─ question_filter: QuestionFilter                               │
│  │  ├─ _total_checked: int                                        │
│  │  ├─ _total_passed: int                                         │
│  │  └─ _total_rejected: int                                       │
│  │                                                                  │
│  └─ response_agent: ResponseAgent / OpenAIAgent / GeminiAgent    │
│     ├─ _cache_stats: dict                                         │
│     └─ _warmed_up: bool                                           │
│                                                                      │
│  COMMUNICATION:                                                     │
│  ├─ ws_clients: set[websocket]                                    │
│  │  └─ Connected teleprompters                                    │
│  └─ conversation_history: list[dict]                              │
│     ├─ {"speaker": "candidate", "text": "...", "timestamp": "..."}
│     └─ {"question": "...", "type": "...", "response": "...", ...}
│                                                                      │
│  OBSERVABILITY:                                                     │
│  ├─ session_metrics: SessionMetrics                               │
│  │  └─ questions: list[QuestionMetrics]                           │
│  │                                                                  │
│  ├─ alert_manager: AlertManager                                   │
│  │  └─ slos: dict (p95_latency, cache_hit_rate, error_rate)     │
│  │                                                                  │
│  └─ cost_tracker: CostTracker                                     │
│     ├─ entries: list[CostEntry]                                   │
│     └─ breakdown: SessionCostBreakdown                            │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

### 5. MÁQUINA DE ESTADOS: PREGUNTA

```
                          START
                            │
                            ▼
                  ┌──────────────────┐
                  │  LISTENING       │
                  │                  │
                  │ status = "READY" │
                  └────────┬─────────┘
                           │ (interviewer starts speaking)
                           ▼
                  ┌──────────────────┐
                  │ SPEECH_ACTIVE    │
                  │                  │
                  │ Transcription    │
                  │ running          │
                  └────────┬─────────┘
                           │ (interviewer stops speaking)
                           │ (on_speech_event("stopped"))
                           ▼
                  ┌──────────────────┐
                  │ SPECULATING      │
                  │                  │
                  │ KB retrieval +   │
                  │ generation in    │
                  │ background       │
                  └────────┬─────────┘
                           │ (final transcript arrives)
                           │ (on_transcript("interviewer", text))
                           ▼
                  ┌──────────────────┐
                  │ QUESTION_FILTER  │
                  │                  │
                  │ is_real_question?│
                  └─────┬────────┬───┘
                        │ NO     │ YES
                        │        │
                   ┌────▼──┐    │
                   │ SKIP  │    │
                   │ (log) │    │
                   └───────┘    │
                                ▼
                       ┌──────────────────┐
                       │ CLASSIFYING      │
                       │                  │
                       │ Type + budget    │
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │ RETRIEVING_KB    │
                       │                  │
                       │ (or using cached)│
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │ GENERATING       │
                       │                  │
                       │ Streaming tokens │
                       │ to teleprompter  │
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │ COMPLETE         │
                       │                  │
                       │ Log + metrics    │
                       └────────┬─────────┘
                                │
                                ▼
                       ┌──────────────────┐
                       │ LISTENING        │
                       │ (ready for next) │
                       └──────────────────┘

Estados Transitorios:
- ERROR: cualquier punto → fall-back message + log
- TIMEOUT: generation tarda > 30s → abort + error message
```

---

### 6. DIAGRAMA DE DEPENDENCIAS

```
┌──────────────────────────────────────────────────────────────────────┐
│                         DEPENDENCY GRAPH                             │
└──────────────────────────────────────────────────────────────────────┘

main.py (Orchestrator)
│
├─────────────────────────────┬────────────────┬─────────────────────┐
│                             │                │                     │
▼                             ▼                ▼                     ▼
AudioCaptureAgent        QuestionClassifier  KnowledgeRetriever  ResponseAgent
│                        (Rule-based)        │                    (Claude/OpenAI/Gemini)
│                                            │                    │
├─ sounddevice                               ├─ ChromaDB          ├─ anthropic.AsyncAnthropic
├─ numpy                                     ├─ OpenAI embeddings ├─ openai.AsyncOpenAI
└─ (opcional: Voicemeeter)                   └─ (optional filter) └─ google-genai
                                                                    
OpenAIRealtimeTranscriber        DeepgramTranscriber
│                                │
├─ websockets                    ├─ deepgram SDK
├─ numpy (resampling)            └─ threading
└─ asyncio                            (for event loop)

QuestionFilter               Teleprompter
│                           │
├─ NLTK (Porter stemmer)    ├─ PyQt5
└─ re (regex patterns)      └─ websockets (client)

CostTracker                  AlertManager
│                           │
├─ dataclasses              ├─ logging
└─ json                     └─ (stat math)

SessionMetrics              Prometheus
│                           │
├─ dataclasses              ├─ prometheus_client
└─ json                     └─ (HTTP server)

KnowledgeIngestor
│
├─ langchain_text_splitters
├─ OpenAI embeddings
├─ ChromaDB
└─ pathlib
```

---

## 🎬 CASOS DE USO

### Caso 1: Usuario Exitoso (Happy Path)

```
ACTOR: Candidato nativo Spanish
OBJETIVO: Participar en entrevista en inglés con asistencia de IA

PRECONDICIONES:
✓ API keys configuradas en .env
✓ Voicemeeter instalado y configurado
✓ KB ingested (resume, skills, company info)
✓ Teleprompter ejecutándose

FLUJO:
1. Usuario ejecuta: python main.py
   → Pipeline inicia
   → Teleprompter overlay abre
   → Status: "● LISTENING"

2. Usuario entra a llamada Zoom
   → Entrevistador conectado
   → Small talk inicial

3. Entrevistador: "Tell me about yourself"
   → AudioCaptureAgent captura ambos
   → Transcriptores procesan
   → FilterQuestion: ACCEPT
   → Classifier: personal
   → KB retrieval: 3 chunks relevantes
   → Response genera

4. Teleprompter muestra respuesta
   → Instant opener: "So basically, in my experience at Webhelp…"
   → Full response: "So basically, in my experience at Webhelp, 
                    I've been working in customer support for 3+ years. 
                    I maintain 92% QA score and specialize in technical 
                    troubleshooting. I'm particularly skilled at..."

5. Usuario lee en voz alta
   → Respuesta 100% personalizada
   → Basada en su KB
   → Conversacional + confiante

6. Entrevistador: "What are your strengths?"
   → Ciclo repite
   → Cache hit: respuesta 20% más rápida

7. Entrevistador: "Tell me about a time..."
   → Situational question
   → Presupuesto aumentado: 2048
   → Respuesta más detallada con STAR format

RESULTADO:
✓ Entrevista completada
✓ Logs guardados en markdown
✓ Métricas exportadas
✓ Costos reportados
✓ User confiado, respuestas estructuradas

POST-CONDICIONES:
├─ logs/interview_2026-03-01_11-25.md (conversation log)
├─ logs/metrics_session_20260301_112500.json (latencies)
└─ logs/costs_session_20260301_112500.json (API costs)
```

---

### Caso 2: Error: KB Vacía

```
ACTOR: Candidato (usuario)
OBJETIVO: Ejecutar pipeline sin KB preparada

PRECONDICIONES:
✓ API keys configuradas
✗ kb/personal/ y kb/company/ vacíos

FLUJO:
1. Usuario: python main.py
   → Pipeline inicia
   → Inicia KnowledgeRetriever

2. Entrevistador: "Tell me about yourself"
   → Llega transcript
   → Filtro: ACCEPT
   → Clasificación: personal

3. KB Retrieval:
   ├─ Embedding generada
   ├─ ChromaDB query
   └─ Resultado: 0 chunks (collection empty)

4. Fallback:
   ├─ Logger: "No KB results for query..."
   └─ Return: empty list []

5. Response Generation:
   ├─ System prompt OK
   ├─ KB section: "[No knowledge base context available]"
   ├─ Genera respuesta generic
   └─ "So basically, I'm a professional dedicated to delivering..."

6. Teleprompter muestra respuesta
   ├─ Funciona, pero:
   ├─ No es personalizada
   ├─ No menciona company/experiencia específica
   └─ Menos convincente

PROBLEMA IDENTIFICADO:
└─ Logger warnings durante session

SOLUCIÓN:
1. Stop pipeline (Ctrl+C)
2. Agregar documentos a kb/personal/ y kb/company/
3. Ejecutar: 
   python -c "from src.knowledge.ingest import KnowledgeIngestor; \
              KnowledgeIngestor().ingest_all()"
4. Restart: python main.py
5. Retry pregunta

MEJORA:
└─ Respuesta ahora incluye facts de KB personalizado
```

---

### Caso 3: Red Lenta / Latencia Alta

```
ACTOR: Candidato con conexión a internet lenta
OBJETIVO: Completar entrevista con latencia > esperada

PRECONDICIONES:
- Ancho de banda: 2 Mbps (limitado)
- Ping: 150-200ms (alto)

FLUJO:
1. Transcripción OpenAI:
   ├─ TTFT esperado: 500-800ms
   ├─ TTFT actual: 1200-1500ms (retardo de red)
   └─ Compensación: OK, sigue funcionando

2. KB Retrieval:
   ├─ Embedding API call: 500-600ms (vs. 300-400ms)
   ├─ ChromaDB search: 50-100ms (local, no afectado)
   └─ Total: 550-700ms

3. Response Generation:
   ├─ API call: +200ms overhead
   ├─ TTFT: 1000-1200ms
   └─ Total pipeline: 5500-6500ms

IMPACTO:
├─ E2E latencia: +50% vs. esperado
├─ Pero: aún funciona correctamente
├─ Candidate puede leer respuesta completa
└─ No hay fallo, solo más lento

MONITOREO:
├─ Logger: muestra latencias reales
├─ Prometheus: response_latency_ms = 5800
├─ Alert: check si > SLO (5000ms)
│  └─ SLO breach: P95 5800 > 5000
│  └─ Log: WARNING "SLO Alert: ..."

USUARIO PERCIBE:
└─ Respuesta tarda un poco más (5-6s vs. 4-5s)
   pero sigue siendo útil y coherente

MITIGACIÓN:
└─ Sistema continúa sin interrución
   (graceful degradation, no failure)
```

---

### Caso 4: Question Filter Rechaza Ruido

```
ACTOR: Entrevistador distraction / ruido
OBJETIVO: Verificar que filtro rechaza no-preguntas

PRECONDICIONES:
✓ Filtro activo

FLUJO:
1. Entrevistador: "Um, um, let me see..."
   → Transcript: "um um let me see"
   
2. QuestionFilter.is_interview_question("um um let me see"):
   ├─ Check 1: Noise patterns?
   │  └─ Regex match: r"^(um+|uh+|..."
   │  └─ MATCH → REJECT
   
3. Log: "QUESTION REJECTED (noise_pattern): um um let me see"

4. No llamar a RAG pipeline
   → Ahorro: ~500ms, ~$0.001 costo

---

2. Entrevistador: "Thank you for coming today"
   → Transcript: "Thank you for coming today"
   
3. QuestionFilter.is_interview_question("Thank you for coming today"):
   ├─ Check 1: Noise patterns?
   │  └─ Regex match: r"^(thank you for ...)"
   │  └─ MATCH → REJECT
   
4. Log: "QUESTION REJECTED (noise_pattern): Thank you for coming..."
   
5. Ahorro: pipeline no ejecuta

---

3. Entrevistador: "So, what makes you interested in our company?"
   → Transcript: "So, what makes you interested in our company?"
   
4. QuestionFilter.is_interview_question(...):
   ├─ Check 1: Noise? NO
   ├─ Check 2: Min words? YES (8 words > 4 required)
   ├─ Check 3: Signals? YES ("what makes you interested" ~= interview signal)
   └─ → ACCEPT
   
5. Log: "QUESTION ACCEPTED (interview_signal): So, what makes..."

6. Procede a RAG pipeline
   → Full latencia ~5s
   → Full cost

RESULTADO:
✓ Filtro funciona correctamente
✓ Evita ~50% de ruido
✓ Ahorro de recursos y tiempo
```

---

### Caso 5: Compound Question (Multi-parte)

```
ACTOR: Entrevistador
OBJETIVO: Hacer pregunta compuesta (multi-parte)

PRECONDICIONES:
✓ Classifier activo

FLUJO:
1. Entrevistador: "Tell me about your experience AND what would you do 
                   if you faced a difficult customer?"
   
2. Transcript llega: {pregunta compuesta}

3. QuestionFilter: ACCEPT

4. QuestionClassifier._fallback_classify():
   ├─ Check compound:
   │  ├─ count("?") = 2 → multiple questions
   │  ├─ connectors: "AND" found
   │  └─ compound = True
   │
   ├─ Result: {
   │    "type": "hybrid",
   │    "compound": True,
   │    "budget": 1024 * 2 = 2048  (doubled for complexity)
   │  }

5. KB Retrieval:
   ├─ Query: "Tell me about your experience AND..."
   ├─ TOP_K["hybrid"] = 5 (más chunks para compound)
   └─ Retorna: [chunk1, chunk2, chunk3, chunk4, chunk5]

6. Response Generation:
   ├─ Budget: 2048 (thinking budget doubled)
   ├─ Length guide: "5-6 sentences"
   ├─ Respuesta cubre:
   │  ├─ Part 1: Personal experience (3-4 sentences)
   │  └─ Part 2: Difficult customer scenario (2-3 sentences, STAR format)

RESULTADO:
✓ Classifier detecta compound
✓ Mayor presupuesto de pensamiento
✓ Más chunks de KB
✓ Respuesta más completa para pregunta multi-parte
```

---

### Caso 6: Especulative Generation Hit

```
ACTOR: Sistema optimizado
OBJETIVO: Demostrar especulative retrieval + generation

PRECONDICIONES:
✓ Especulative tasks ejecutándose

FLUJO:
Timeline:
T=0ms:      Entrevistador termina: "What are your weaknesses?"
            ├─ on_speech_event("stopped")
            └─ Start speculative tasks with delta: "what are your weaknesses"

T=200ms:    Especulative KB retrieval completa
            ├─ Chunks fetched y cacheados en memoria
            ├─ 3 chunks relevantes ready
            └─ r_task.done() = True

T=250ms:    Especulative generation completada
            ├─ 50 tokens buffered en memoria
            ├─ "So basically, I'd say my biggest weakness is..."
            ├─ Tokens: [So, basically, I'd, say, my, ...]
            └─ g_task.done() = True

T=5000ms:   Final transcript arrives:
            └─ Transcript: "What are your weaknesses?" (casi idéntico)

T=5050ms:   process_question() checks speculative
            ├─ g_task.done()? YES
            ├─ g_task.cancelled()? NO
            ├─ buffered_tokens? YES (50 tokens)
            ├─ Semantic similarity check:
            │  ├─ delta_emb = embed("what are your weaknesses")
            │  ├─ final_emb = embed("What are your weaknesses?")
            │  ├─ cosine_sim = 0.95 > 0.80 threshold
            │  └─ → ACCEPT speculative results
            │
            └─ ✓ SPECULATIVE HIT!

T=5055ms:   Flush buffered tokens
            └─ for token in [So, basically, I'd, say, ...]:
                   await broadcast_token(token)

T=5155ms:   50 tokens broadcasted (100ms to display 50)

T=5160ms:   Remaining tokens generated fresh
            ├─ Continue generation from token 51
            └─ "...that I sometimes overthink problems.
                 But I've learned to..."

T=6500ms:   Response completa

LATENCIA COMPARATIVA:
Sin especulative: ~5000ms + 3500ms generation = 8500ms total
Con especulative: ~5000ms + 0ms (pre-cached) = 5000ms total
AHORRO: -3500ms (-40%)

COSTOS COMPARATIVOS:
Sin especulative:
├─ 1x KB retrieval
├─ 1x generation full
└─ Total: $0.008

Con especulative:
├─ 1x KB retrieval (parallel, shared)
├─ 1x generation full (parallel, shared)
└─ Total: $0.008 (MISMO COSTO)

BENEFICIO:
└─ ✓ -40% latencia sin aumento de costo
   ✓ User percibe respuesta 3.5s más rápida
   ✓ Psicológicamente parece instantáneo
```

---

## 📋 MATRIZ DE DECISIÓN

### ¿Cuál Modelo de Response Usar?

```
┌────────────────┬──────────────┬─────────┬──────────┬──────────┐
│ Modelo         │ TTFT (P50)   │ Costo   │ Calidad  │ Cache    │
├────────────────┼──────────────┼─────────┼──────────┼──────────┤
│ GPT-4o-mini    │ 800ms        │ Low     │ Very Good│ No       │
│ Gemini 2.5 Flash│ 600ms       │ Very Low│ Good     │ No       │
│ Claude Sonnet  │ 1000ms       │ Medium  │ Excellent│ Yes (90%)│
├────────────────┼──────────────┼─────────┼──────────┼──────────┤
│ RECOMENDADO    │ Gemini Fast+ │ Lowest  │ Fastest  │ Para dev │
│ (For interview)│ OpenAI Cheap │ Cost OK │ Per $    │ Claude   │
│                │ Claude Best  │ Quality │ Best val │ for prod │
└────────────────┴──────────────┴─────────┴──────────┴──────────┘

SELECCIÓN:
- Desarrollo/Testing → Gemini 2.5 Flash (rápido, barato)
- Producción (costo) → OpenAI GPT-4o-mini (bajo costo, bueno)
- Producción (calidad) → Claude Sonnet (mejor respuestas + cache)
- Presupuesto ilimitado → Claude Opus (mejor razonamiento)
```

---

### ¿Cuándo Usar Prompt Caching?

```
┌──────────────────────────────────────────────┐
│ Prompt Caching Benefits (Claude only)        │
├──────────────────────────────────────────────┤
│                                              │
│ BENEFICIOS:                                  │
│ ✓ 85% descuento en tokens cached             │
│ ✓ Más rápido (20% TTFT reduction)           │
│ ✓ Bueno para system prompts (reutilizados)  │
│                                              │
│ COSTOS:                                      │
│ ✗ Cache write token: 25% más que input      │
│ ✗ Solo beneficioso si >> 1024 tokens        │
│ ✗ Latencia mínima de cold start              │
│                                              │
│ DECISIÓN:                                    │
│ USE IF:                                      │
│   - Sistema prompt > 1024 tokens             │
│   - Múltiples preguntas en sesión            │
│   - Presupuesto limitado                     │
│                                              │
│ DON'T USE IF:                                │
│   - Sistema prompt < 512 tokens              │
│   - Solo 1-2 preguntas                       │
│   - Latencia crítica (no esperar cache)      │
└──────────────────────────────────────────────┘
```

---

## 🎓 CONCLUSIÓN VISUAL

Este documento proporciona:

✅ **Flujos Visuales:** Entiende cómo se mueve la información
✅ **Casos de Uso:** Realistas y comunes en producción
✅ **Decisiones:** Cuándo usar qué componente
✅ **Timeline:** Comprende latencias exactas

Combinado con `ANALISIS_TECNICO_COMPLETO.md`, tienes documentación 
360° del sistema completo.


