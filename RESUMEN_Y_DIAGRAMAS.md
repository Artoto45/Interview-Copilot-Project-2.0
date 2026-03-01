# 📊 RESUMEN EJECUTIVO Y DIAGRAMAS
## Interview Copilot v2.0

---

## 🎯 RESUMEN EJECUTIVO

### ¿Qué es?
Sistema en tiempo real que **asiste a candidatos no-anglohablantes durante entrevistas telefónicas en inglés**. Usa transcripción dual-channel, búsqueda inteligente en base de conocimiento (RAG), y un overlay de teleprompter para mostrar respuestas sugeridas.

### ¿Cómo funciona?
1. **Captura audio** dual (candidato + entrevistador)
2. **Transcribe en tiempo real** (OpenAI Realtime API)
3. **Filtra preguntas reales** (rule-based, sin latencia)
4. **Clasifica tipo** (personal/company/situational/etc)
5. **Busca en KB** (embedding + ChromaDB)
6. **Genera respuesta** (Claude Sonnet 4 + prompt caching)
7. **Muestra en teleprompter** (PyQt5 overlay semitransparente)

### Stack Técnico
| Componente | Tecnología |
|-----------|-----------|
| **Backend** | Python 3.11+, asyncio |
| **Transcripción** | OpenAI Realtime API (gpt-4o-mini-transcribe) |
| **Clasificación** | Claude Haiku 4.5 |
| **Generación** | Claude Sonnet 4 + Prompt Caching |
| **KB** | ChromaDB + OpenAI text-embedding-3-small |
| **Audio** | sounddevice + Voicemeeter Banana |
| **UI** | PyQt5 (overlay frameless, always-on-top) |
| **Comunicación** | WebSocket local (127.0.0.1:8765) |

### Métricas Clave
| Métrica | Valor |
|---------|-------|
| **P50 Latency** | ~3-4s desde end-of-speech |
| **P95 Latency** | ~5-7s (cache miss) |
| **Cache Hit Rate** | ~60-70% después warmup |
| **Cost per Q&A** | ~$0.02-0.05 (OpenAI + Anthropic) |
| **Throughput** | 1 question per ~4s |

---

## 📊 DIAGRAMAS ARQUITECTÓNICOS

### Diagrama 1: Pipeline de Datos (Flujo End-to-End)
```
┌─────────────────────────────────────────────────────────────────────┐
│                      ENTRADA DUAL DE AUDIO                         │
│  ┌──────────────────────────────────┬──────────────────────────────┐
│  │ Micrófono Candidato (Yo)         │ Audio Sistema (Entrevistador)│
│  │ (Voicemeeter Bus B1)             │ (Voicemeeter Bus B2 ó Mix)   │
│  └──────────────────────────────────┴──────────────────────────────┘
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│         AudioCaptureAgent (sounddevice)                             │
│  • Dos streams en paralelo: user_queue + int_queue                 │
│  • Sample rate: 16 kHz, 100ms chunks (1,600 samples)              │
│  • Fallback: Stereo Mix si Voicemeeter no disponible               │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────┬───────────────────────────────┐
│   OpenAIRealtimeTranscriber (User)   │ OpenAIRealtimeTranscriber (Int)│
│   WSS → OpenAI Realtime              │ WSS → OpenAI Realtime         │
│   • gpt-4o-mini-transcribe           │ • gpt-4o-mini-transcribe      │
│   • ~1-1.5s latencia                 │ • ~1-1.5s latencia            │
│   • Callbacks: on_delta, on_transcript, on_speech_event           │
└──────────────────────────────────────┴───────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
            ┌───────▼────────┐       ┌────────▼────────┐
            │ speaker="user" │       │ speaker="int"   │
            │ (Candidato)    │       │ (Preguntador)   │
            ├────────────────┤       ├─────────────────┤
            │ on_transcript()│       │ on_transcript() │
            │ ├─ Save to     │       │ ├─ QuestionFilter
            │ │  history     │       │ │  (is_real_q?)
            │ └─ NO generate │       │ ├─ QuestionClassifier
            │                │       │ │  (type, budget)
            └────────────────┘       │ ├─ KnowledgeRetriever
                                     │ │  (RAG chunks)
                                     │ ├─ ResponseAgent
                                     │ │  (generate response)
                                     │ └─ WebSocket broadcast
                                     └─────────────────┘
                                             │
                                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│              TeleprompterBridge (WebSocket Client)                  │
│              127.0.0.1:8765 (Local-only)                           │
│              Receives: {"type": "token", "data": "..."}            │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│           SmartTeleprompter (PyQt5 Overlay)                         │
│  ┌────────────────────────────────────────────────────────────────┐
│  │ ● LISTENING                              WPM: 130            │ ← Status
│  ├────────────────────────────────────────────────────────────────┤
│  │                                                               │
│  │ So basically, in my experience at Webhelp, [PAUSE] I've      │
│  │ worked with **3+ years** of distributed systems… [PAUSE]    │
│  │                                                               │
│  │ I'm really excited about your company because you're a      │
│  │ BPO leader with **50K+ employees** globally.                │
│  │                                                               │
│  └────────────────────────────────────────────────────────────────┘
│  Ctrl+↑/↓: Size | Ctrl+←/→: WPM | Ctrl+O: Opacity | Ctrl+C: Clear │
└─────────────────────────────────────────────────────────────────────┘
```

---

### Diagrama 2: Flujo de Procesamiento de Pregunta (Timing)
```
ENTREVISTADOR COMIENZA A HABLAR (T=0ms)
│
├─ on_delta() → subtítulos en vivo (cada 100-200ms)
│
├─ on_speech_event("stopped") [T~500ms, fin de habla]
│  └─ Inicia ESPECULACIÓN:
│     ├─ Pre-fetch KB (async task)
│     └─ Pre-generate respuesta (async task)
│
├─ OpenAI Realtime procesa audio [T~1-1.5s]
│
├─ on_transcript("interviewer", "Tell me about yourself?") [T~1.5s]
│
├─ QuestionFilter.is_interview_question() [T~1.5s + 5ms]
│  └─ True → continue, False → skip
│
├─ process_question() inicia [T~1.5s]
│  │
│  ├─ 1. QuestionClassifier (Haiku)
│  │     type="personal", budget=512 [T+0-200ms]
│  │
│  ├─ 2. Check Speculative Hit ✓
│  │     Si respuesta está lista Y similar → FLUSH TOKENS
│  │     Ahorro: 3-5s (SALTAR steps 3-5)
│  │
│  ├─ 3. Instant Opener (NO API)
│  │     "So basically, in my experience…" [T+<1ms]
│  │     → broadcast a teleprompter
│  │
│  ├─ 4. KnowledgeRetriever (RAG)
│  │     Embed query + ChromaDB search [T+500-1000ms]
│  │     Chunks: [personal_profile, star_stories]
│  │
│  ├─ 5. ResponseAgent.generate() (Streaming)
│  │     Claude Sonnet 4 streaming [T+2-4s con cache, T+4-6s sin]
│  │     ├─ "So" → broadcast
│  │     ├─ " basically" → broadcast
│  │     ├─ "," → broadcast
│  │     └─ (100+ tokens más…)
│  │
│  ├─ 6. Teleprompter Receives y Muestra
│  │     ├─ Scroll auto
│  │     ├─ Parse [PAUSE] → espacio vertical
│  │     └─ Parse **bold** → styling
│  │
│  └─ 7. Log a archivo sesión [T+end]
│
└─ Usuario RESPONDE (Mientras teleprompter muestra respuesta)
   on_transcript("user", "So basically, I've worked at Webhelp...")
   → Guardado en history, NO desencadena RAG

─────────────────────────────────────────────────────────────────────
TIMELINE TOTAL:
  T=0ms       ├─ Start speaking
  T=100ms     ├─ on_delta() (subtítulos)
  T=500ms     ├─ on_speech_event("stopped") — especulación inicia
  T=1500ms    ├─ on_transcript() — pregunta final
  T=1505ms    ├─ process_question() inicia
  T=1700ms    ├─ Clasificación (Haiku): "personal"
  T=2200ms    ├─ Retrieval: chunks listos
  T=4000ms    ├─ Respuesta 50% streamed
  T=5000ms    ├─ Respuesta completa
              │
  P50: ~3-4 segundos desde end-of-speech
  P95: ~5-7 segundos (sin cache)
─────────────────────────────────────────────────────────────────────
```

---

### Diagrama 3: Componentes y Responsabilidades
```
┌──────────────────────────────────────────────────────────────────────┐
│                        INTERVIEW COPILOT SYSTEM                     │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ AUDIO LAYER                                                 │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │ • AudioCaptureAgent ← sounddevice, Voicemeeter            │   │
│  │   └─ Dual streams: user_queue, int_queue (16kHz, 100ms)   │   │
│  │ • OpenAIRealtimeTranscriber (2 instancias)                │   │
│  │   └─ WebSocket ↔ OpenAI, VAD semántico, 3 buffers        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ FILTERING & CLASSIFICATION LAYER                            │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │ • QuestionFilter (30+ regex patterns)                      │   │
│  │   └─ Rule-based, 0 latencia, rejects noise/filler/meta    │   │
│  │ • QuestionClassifier (Haiku 4.5)                          │   │
│  │   └─ Types: personal|company|hybrid|situational|simple    │   │
│  │   └─ Presupuestos: 512-2048 tokens                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ KNOWLEDGE LAYER (RAG)                                       │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │ • KnowledgeIngestor                                         │   │
│  │   └─ kb/ → chunks (300 chars) → embeddings → ChromaDB      │   │
│  │ • KnowledgeRetriever                                        │   │
│  │   └─ Query embed → similarity search → top-K chunks        │   │
│  │ • ChromaDB (persistent, HNSW index)                        │   │
│  │   └─ Collections: interview_kb (personal + company docs)   │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ GENERATION LAYER                                            │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │ • ResponseAgent (Claude Sonnet 4)                          │   │
│  │   ├─ Prompt caching (ephemeral, 85% TTFT reduction)       │   │
│  │   ├─ Streaming token-by-token                              │   │
│  │   ├─ Temperature: 0.3-0.5 según tipo                       │   │
│  │   └─ KB grounding: min 2 hechos por respuesta             │   │
│  │ • Optimizations:                                           │   │
│  │   ├─ Instant opener (~1ms, no API)                         │   │
│  │   ├─ Speculative retrieval (durante transcripción)        │   │
│  │   └─ Speculative generation (65% similarity threshold)    │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ UI LAYER                                                    │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │ • SmartTeleprompter (PyQt5)                                │   │
│  │   ├─ Overlay frameless, always-on-top, semitransparente   │   │
│  │   ├─ Token-by-token streaming                              │   │
│  │   ├─ [PAUSE] + **emphasis** parsing                        │   │
│  │   └─ Ctrl shortcuts: size, WPM, opacity, clear             │   │
│  │ • TeleprompterBridge (WebSocket client)                    │   │
│  │   └─ Receive → forward tokens to Qt display                │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │ COORDINATION LAYER (main.py)                               │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │ • PipelineState: global state + agent instances            │   │
│  │ • WebSocket Server (127.0.0.1:8765)                        │   │
│  │   └─ Broadcast tokens → SmartTeleprompter                  │   │
│  │ • Async callbacks:                                         │   │
│  │   ├─ on_transcript() → main entry point                    │   │
│  │   ├─ on_delta() → subtítulos en vivo                       │   │
│  │   └─ on_speech_event() → especulación                      │   │
│  │ • Conversation history: Q&A logging                        │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

### Diagrama 4: Matriz de Decisiones (Question → Response)
```
┌─────────────────────────────────────────────────────────────────┐
│                  PREGUNTA LLEGA (on_transcript)                 │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
        ┌────────────────────────┐
        │ Speaker = "user" ?     │
        └───┬────────────────────┘
            │
       NO   │   SÍ
        ┌───▼─────────────────┐
        ▼                     ▼
    PROCESS              GUARDAR EN
    QUESTION             HISTORY
    (→ RAG)              (→ CONTEXTO)
                         (✗ NO RAG)

                     ┌────────────────┐
                     │ is_interview_  │
                     │ question(text)?│
                     └───┬────────────┘
                        NO│  │SÍ
        ┌──────────────────┘  └──────────────────┐
        │                                        │
        ▼                                        ▼
      LOG                                CLASSIFY
      REJECT                             (Haiku 4.5)
      (SKIP)                             ↓
                                    ┌────┴────────┐
                                    │   TYPE?     │
                                    └────┬───┬───┬┴───┬────┐
                       ┌────────────────┼───┼───┼───┼────┼────────────┐
                       │                │   │   │   │    │            │
                       ▼                ▼   ▼   ▼   ▼    ▼            ▼
                    SIMPLE         PERSONAL COMPANY HYBRID SITUATION UNKNOWN
                    Budget:512     Budget:512 Budget:1024 Budget:1024 Budget:2048
                     Top-K:2       Top-K:3    Top-K:3    Top-K:5    Top-K:4
                                    │          │         │          │
                                    └──────────┴────┬────┴──────────┘
                                                    │
                                    ┌───────────────▼───────────────┐
                                    │   RETRIEVE KB (RAG)           │
                                    │  (Embed + ChromaDB similarity) │
                                    └───────────────┬───────────────┘
                                                    │
                    ┌───────────────────────────────▼──────────────────┐
                    │ GENERATE RESPONSE (Claude Sonnet 4)              │
                    │  • System prompt + KB chunks + question          │
                    │  • Streaming token-by-token                      │
                    │  • Temperature: 0.3-0.5                          │
                    │  • Cache hit: ~400ms | Miss: ~2-4s               │
                    │  • KB grounding: min 2 hechos                    │
                    └───────────────┬──────────────────────────────────┘
                                    │
                    ┌───────────────▼──────────────────────────────────┐
                    │ BROADCAST TO TELEPROMPTER                        │
                    │  {"type": "token", "data": "So"}                │
                    │  {"type": "token", "data": " basically"}        │
                    │  ... (streaming)                                │
                    └───────────────┬──────────────────────────────────┘
                                    │
                    ┌───────────────▼──────────────────────────────────┐
                    │ LOG TO SESSION FILE                             │
                    │  logs/interview_YYYY-MM-DD_HH-MM.md             │
                    │  [Q] Tell me about yourself?                    │
                    │  [A] So basically, in my experience...          │
                    └──────────────────────────────────────────────────┘
```

---

### Diagrama 5: Latencia Descompuesta (P50 vs P95)
```
P50 LATENCY (Cache Hit + Speculative Success)
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│ Transcription:        ████ 1.0s                               │
│ Classification:       ▌ 0.15s                                │
│ Retrieval (pre-fetch): ██ 0.5s                               │
│ Generation (cache):    ███ 0.7s                              │
│ Broadcast:           ▌ <0.1s                                │
│ UI Rendering:        ▌ <0.1s                                │
│ ────────────────────────────────────────────────────────────── │
│ TOTAL:               ▓▓▓▓▓▓▓▓ ~3.0s                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

P95 LATENCY (Cache Miss, No Speculative Hit)
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│ Transcription:        ████ 1.5s                               │
│ Classification:       ▌ 0.2s                                 │
│ Retrieval (fresh):    ████ 1.0s                              │
│ Generation (no cache): ████████ 3.0s                         │
│ Broadcast:           ▌ <0.1s                                │
│ UI Rendering:        ▌ <0.1s                                │
│ ────────────────────────────────────────────────────────────── │
│ TOTAL:               ▓▓▓▓▓▓▓▓▓▓▓▓▓▓ ~6.0s                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

OPTIMIZATION IMPACT:
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│ Sin Optimizaciones:   ▓▓▓▓▓▓▓▓▓▓▓▓▓ 8-10s                   │
│ + Speculative Ret:    ▓▓▓▓▓▓▓▓▓ 6-7s (save 2s)              │
│ + Instant Opener:     ▓▓▓▓▓▓▓ 5-6s (feel 2-3s faster)       │
│ + Prompt Cache:       ▓▓▓▓▓ 3-5s (save 1-2s per hit)        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

### Diagrama 6: Estado de Especulación (Speculative Trio)
```
┌─────────────────────────────────────────────────────────────────────┐
│            SPECULATIVE STATE MANAGEMENT                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  GLOBAL VARIABLES (en main.py):                                   │
│  ─────────────────────────────────                                │
│  _speculative_retrieval_task: asyncio.Task[list] | None          │
│  _speculative_query: str                                          │
│  _speculative_gen_task: asyncio.Task | None                      │
│  _speculative_gen_tokens: list[str]                              │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │ FLOW:                                                         │ │
│  ├──────────────────────────────────────────────────────────────┤ │
│  │                                                              │ │
│  │ 1. on_speech_event("interviewer", "stopped")               │ │
│  │    └─ Extrae: delta_text = _live_buffer (último buffer)   │ │
│  │       └─ Inicia dos async tasks:                          │ │
│  │          _run_speculative_retrieval(delta_text)           │ │
│  │          └─ _speculative_retrieval_task = task            │ │
│  │          _run_speculative_generation(delta_text)          │ │
│  │          └─ _speculative_gen_task = task                  │ │
│  │                                                              │ │
│  │ 2. (en paralelo) OpenAI realiza VAD + ASR (~1.5s)          │ │
│  │    └─ while: retrieval y generation corren en background   │ │
│  │                                                              │ │
│  │ 3. on_transcript("interviewer", final_text)               │ │
│  │    └─ Dispara process_question(final_text)               │ │
│  │       ├─ Check hit especulativo:                         │ │
│  │       │  if _speculative_gen_tokens ready:               │ │
│  │       │    similarity = _is_similar_enough(delta, final) │ │
│  │       │    if similarity >= 0.65:                         │ │
│  │       │      yield from _speculative_gen_tokens          │ │
│  │       │      log("Speculative generation HIT ✓")         │ │
│  │       │      return                                       │ │
│  │       │                                                    │ │
│  │       └─ Si no hit: generar respuesta normal             │ │
│  │                                                              │ │
│  │ 4. on_speech_event("interviewer", "started")              │ │
│  │    └─ Nueva pregunta comenzando                           │ │
│  │       └─ Cancelar especulaciones previas (obsoletas)      │ │
│  │          _speculative_gen_task.cancel()                   │ │
│  │          _speculative_retrieval_task.cancel()             │ │
│  │                                                              │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                     │
│  ⚠️ RACE CONDITIONS POSIBLES:                                     │
│     • Multiple on_speech_event() calls rápidamente                │
│     • on_transcript() while speculative tasks en progreso         │
│     • Acceso simultáneo a _speculative_gen_tokens                 │
│                                                                     │
│  ✅ MITIGATION (recomendado):                                      │
│     • Usar asyncio.Lock() para acceso sincronizado               │
│     • Usar SpeculativeState dataclass con métodos thread-safe    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

### Diagrama 7: Gestión de Prompts y Caching
```
┌─────────────────────────────────────────────────────────────────────┐
│            PROMPT CACHING ARCHITECTURE (Claude Sonnet 4)           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  SYSTEM PROMPT (~800 tokens):                                    │
│  ──────────────────────────────                                  │
│  • Instrucciones críticas (13 rules)                             │
│  • Formato esperado (contracciones, oraciones cortas)           │
│  • Ejemplos de output deseado                                   │
│  • [PAUSE], **emphasis**, no headers/bullets                    │
│  • KB grounding: mín 2 hechos                                   │
│                                                                     │
│  ┌─ Enviado con cache_control: {"type": "ephemeral"}            │
│  │  └─ Almacenado en cache por 5 minutos de inactividad        │
│  │     (si había otra conversación)                             │
│  │                                                                │
│  └─ Primera llamada: 800 tokens computados → cache creado       │
│     Siguientes N llamadas: 800 tokens REUTILIZADOS             │
│     └─ TTFT ~85% más rápido (400ms vs 2-3s)                   │
│                                                                     │
│  USER MESSAGE (variable, ~300-500 tokens):                       │
│  ──────────────────────────────────────────                     │
│  [QUESTION TYPE]: personal                                       │
│  [LENGTH]: 3-4 sentences                                         │
│  [KNOWLEDGE BASE]:                                               │
│    Luis Araujo, 3+ years at Webhelp, Python expertise...       │
│    Handled 92% QA score improvement...                          │
│  [INTERVIEWER QUESTION]:                                         │
│    Tell me about yourself                                        │
│                                                                     │
│  └─ NO cached (cambia por cada pregunta)                        │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ RESPONSE HEADERS (tracking cache):                          │ │
│  ├─────────────────────────────────────────────────────────────┤ │
│  │                                                             │ │
│  │ CACHE HIT (2da+ llamada):                                 │ │
│  │ usage: {                                                   │ │
│  │   "cache_read_input_tokens": 800,  ← From cache            │ │
│  │   "input_tokens": 300,              ← Fresh                │ │
│  │   "output_tokens": 150,             ← Generated            │ │
│  │ }                                                           │ │
│  │ Cost: 300 tokens @ $3/1M + 800 @ $0.30/1M (90% discount) │ │
│  │      = $0.00090 + $0.00024 = $0.00114                    │ │
│  │                                                             │ │
│  │ CACHE MISS (1era llamada):                               │ │
│  │ usage: {                                                   │ │
│  │   "cache_creation_input_tokens": 800,  ← Being cached      │ │
│  │   "input_tokens": 300,                 ← Fresh             │ │
│  │   "output_tokens": 150,                ← Generated          │ │
│  │ }                                                           │ │
│  │ Cost: 1100 tokens @ $3/1M = $0.0033                      │ │
│  │                                                             │ │
│  │ ✓ ROI: Cache se paga en 3-5 preguntas                     │ │
│  │                                                             │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 MATRIZ DE PROBLEMAS VS RECOMENDACIONES

```
SEVERIDAD | PROBLEMA                    | IMPACTO      | RECOMENDACIÓN
──────────┼─────────────────────────────┼──────────────┼───────────────────────
CRÍTICO   │ Race conditions en especulación │ Crashes/data  │ Usar asyncio.Lock()
          │                             │ corruption   │
──────────┼─────────────────────────────┼──────────────┼───────────────────────
CRÍTICO   │ Sin timeout en generation   │ UI freeze    │ asyncio.timeout(30s)
          │                             │ indefinido   │
──────────┼─────────────────────────────┼──────────────┼───────────────────────
CRÍTICO   │ Teleprompter sin healthcheck│ Silent fail  │ Monitor proc.poll()
          │                             │ (sin UI)     │ + auto-restart
──────────┼─────────────────────────────┼──────────────┼───────────────────────
ALTO      │ Latencia P95 vs target      │ UX pobre     │ Semantic similarity
          │ 5-7s vs <2.2s target        │              │ para speculative hit
──────────┼─────────────────────────────┼──────────────┼───────────────────────
ALTO      │ KB sin hot-reload           │ Manual       │ watchfiles monitoring
          │                             │ restart      │ + re-ingest
──────────┼─────────────────────────────┼──────────────┼───────────────────────
ALTO      │ Sin retry para transientes  │ Fallos       │ exponential backoff
          │                             │ intermitentes│ (2^attempt seconds)
──────────┼─────────────────────────────┼──────────────┼───────────────────────
MEDIO     │ Acceso privado _live_buffer │ Brittle code │ Agregar getter público
          │                             │ (future-compat)
──────────┼─────────────────────────────┼──────────────┼───────────────────────
MEDIO     │ Sin límite gasto API        │ Surprise     │ Config + alertas
          │                             │ bills        │ (daily/monthly)
──────────┼─────────────────────────────┼──────────────┼───────────────────────
MEDIO     │ Especulative hit false pos  │ Respuestas   │ 80% threshold +
          │ (65% threshold bajo)        │ incorrectas  │ semantic similarity
──────────┼─────────────────────────────┼──────────────┼───────────────────────
BAJO      │ Logging verbose production  │ Disk spam    │ Log level config
          │                             │              │ (envvar DEBUG)
──────────┼─────────────────────────────┼──────────────┼───────────────────────
BAJO      │ Sin métricas de monitoreo   │ Blind ops    │ Telemetría (StatsD/
          │                             │              │ Prometheus)
──────────┼─────────────────────────────┼──────────────┼───────────────────────
BAJO      │ Teleprompter UI no responsive │ Occasional   │ Move WebSocket listen()
          │                             │ freezes      │ a thread separado
──────────┼─────────────────────────────┼──────────────┼───────────────────────
```

---

## 📈 ROADMAP DE MEJORAS (Fases)

### Fase 1: Estabilidad (Semana 1-2)
- [ ] Sincronización de especulación con asyncio.Lock()
- [ ] Timeout 30s en ResponseAgent.generate()
- [ ] Healthcheck subprocess teleprompter
- [ ] Logging configuration (DEBUG envvar)

### Fase 2: Rendimiento (Semana 3-4)
- [ ] Semantic similarity para speculative hits (80% threshold)
- [ ] Retry logic exponential backoff
- [ ] KB hot-reload con watchfiles
- [ ] Telemetría básica (latencia, cache hits)

### Fase 3: Operaciones (Semana 5-6)
- [ ] Presupuesto de API y alertas
- [ ] Métricas Prometheus + dashboards
- [ ] Validación de entrada (sanitización)
- [ ] ChromaDB backup automático

### Fase 4: Escalabilidad (Mes 2)
- [ ] Multimodal support (video, facial expressions)
- [ ] Cache distribuido (Redis) para múltiples sesiones
- [ ] A/B testing framework para prompts
- [ ] Fine-tuning personalizado

---

## 🏆 CONCLUSIÓN

**Interview Copilot v2.0** es un sistema bien arquitecturado con optimizaciones inteligentes. Los problemas identificados son **solucionables** y las recomendaciones priorizadas permitirán:

1. **Mejorar confiabilidad** (fixes críticos)
2. **Reducir latencia** (P95 < 2.5s)
3. **Habilitar escalabilidad** (múltiples usuarios)
4. **Automatizar operaciones** (CI/CD, monitoring)

**Estimado de desarrollo:** 4-6 semanas para production-ready con todas las fases completadas.

---

**Fin del Análisis**  
📅 Generado: 1 Marzo 2026

