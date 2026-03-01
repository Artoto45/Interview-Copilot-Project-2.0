# 📋 ANÁLISIS COMPLETO DEL PROYECTO
## Interview Copilot v2.0 — Asistente IA en Tiempo Real para Entrevistas

**Fecha de Análisis:** Marzo 1, 2026  
**Versión del Proyecto:** 2.0.0  
**Lenguaje:** Python 3.11+  
**Tipo de Arquitectura:** Pipeline Directo Asincrónico  

---

## 📑 TABLA DE CONTENIDOS

1. [Visión General](#visión-general)
2. [Arquitectura del Sistema](#arquitectura-del-sistema)
3. [Componentes Principales](#componentes-principales)
4. [Análisis Detallado de Módulos](#análisis-detallado-de-módulos)
5. [Flujo de Datos](#flujo-de-datos)
6. [Optimizaciones de Latencia](#optimizaciones-de-latencia)
7. [Gestión del Conocimiento](#gestión-del-conocimiento)
8. [Análisis de Calidad](#análisis-de-calidad)
9. [Problemas y Limitaciones](#problemas-y-limitaciones)
10. [Recomendaciones](#recomendaciones)

---

## 🎯 VISIÓN GENERAL

### Propósito
Sistema de entrevista en tiempo real que **asiste a un candidato no-anglohablante** durante una entrevista telefónica/videoconferencia en inglés. Utiliza:
- **Transcripción dual-channel** (candidato + entrevistador)
- **RAG (Retrieval-Augmented Generation)** sobre base de conocimiento personal y de empresa
- **Claude Sonnet 4** para generación de respuestas adaptadas
- **Overlay de teleprompter** (PyQt5) para mostrar respuestas sugeridas en tiempo real

### Casos de Uso
1. **Candidatos no-nativos:** Necesitan soporte para habla fluida
2. **Preparación pre-entrevista:** Familiarización con preguntas comunes
3. **Entrevistas en vivo:** Asistencia con información de KB de forma invisible

### Modelo de Negocio
- **Software de escritorio gratuito** (open-source probable)
- **Generador de ingresos:** Servicios premium (fine-tuning, KB privado en cloud, etc.)

---

## 🏗️ ARQUITECTURA DEL SISTEMA

### Diagrama de Flujo Principal
```
┌─────────────────────────────────────────────────────────────────┐
│                    ENTRADA DUAL DE AUDIO                        │
│  Micrófono Candidato (Bus B1)  |  Audio Sistema (Bus B2)       │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│         CAPTURA Y RESAMPLING (AudioCaptureAgent)                │
│  • sounddevice + Voicemeeter Banana                             │
│  • Fallback: Stereo Mix / Loopback                              │
│  • Salida: asyncio.Queue (100ms chunks a 16kHz)                │
└──────────────┬───────────────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│      TRANSCRIPCIÓN EN TIEMPO REAL (OpenAIRealtimeTranscriber)  │
│  • Modelo: gpt-4o-mini-transcribe                              │
│  • API: OpenAI Realtime WebSocket                              │
│  • VAD semántico (mejor que basado en silencio)                │
│  • Tres buffers: live → turn → history                          │
│  • Costo: ~$0.003/minuto vs $10+/minuto conversacional         │
└──────────────┬──────────────────────────────────┬────────────────┘
               │                                  │
    ┌──────────▼──────────────┐      ┌──────────▼──────────────┐
    │ Speaker = "user"        │      │ Speaker = "interviewer" │
    │ (Candidato)             │      │ (Preguntador)           │
    │                         │      │                         │
    │ ✓ Guardado en histórico │      │ ✓ Filtre de preguntas  │
    │ ✗ NO desencadena RAG    │      │ ✓ Clasifique pregunta  │
    │ ✗ NO genera respuesta   │      │ ✓ Busque en KB (RAG)   │
    │                         │      │ ✓ Genere respuesta     │
    └─────────────────────────┘      │ ✓ Muestre en teleprompter
                                    └────────────────────────────┘
                                            │
                    ┌───────────────────────┴────────────────────┐
                    │                                            │
                    ▼                                            ▼
        ┌──────────────────────────┐        ┌──────────────────────────┐
        │ QuestionFilter           │        │ QuestionClassifier       │
        │ (Rule-based, 0 latencia) │        │ (Haiku 4.5, <200ms)     │
        │                          │        │                          │
        │ ✓ Rechaza: ruido, filler│        │ Tipos:                  │
        │   saludos, comandos      │        │ • simple (1-2 frases)    │
        │ ✗ Deja pasar preguntas   │        │ • personal (3-4)         │
        │   reales                 │        │ • company (4-5)          │
        │                          │        │ • hybrid (5-6)           │
        │ Señales: 30+ patrones    │        │ • situational (5-6 STAR) │
        └──────────────┬───────────┘        │                          │
                       │                    │ Presupuesto de tokens:   │
                       │ isQuestion() = YES │ • simple: 512            │
                       │                    │ • company: 1024          │
                       └────────────────────┴──────────┬────────────────┘
                                                       │
                                                       ▼
                                    ┌──────────────────────────────┐
                                    │ KnowledgeRetriever (RAG)     │
                                    │                              │
                                    │ 1. Embedding query (OpenAI)  │
                                    │ 2. ChromaDB similaridad      │
                                    │ 3. Top-K por tipo:           │
                                    │    • simple: 2 chunks        │
                                    │    • personal: 3 chunks      │
                                    │    • company: 3 chunks       │
                                    │    • hybrid: 5 chunks        │
                                    │    • situational: 4 chunks   │
                                    │ 4. Filtro de categoría       │
                                    └──────────────┬────────────────┘
                                                   │
                                                   ▼
        ┌─────────────────────────────────────────────────────────────┐
        │  ResponseAgent (Claude Sonnet 4 + Prompt Caching)          │
        │                                                             │
        │  Entrada:                                                  │
        │  • Pregunta del entrevistador                             │
        │  • Chunks de KB relevantes                                │
        │  • Tipo de pregunta                                       │
        │  • Histórico de conversación                              │
        │                                                            │
        │  Sistema Prompt:                                          │
        │  • Instrucciones detalladas (critical rules)             │
        │  • Formato: primera persona, oraciones cortas             │
        │  • Marcadores: [PAUSE], **énfasis**                      │
        │  • Sin meta-comentarios o headers                         │
        │                                                            │
        │  Optimizaciones:                                          │
        │  ✓ Prompt Caching (85% TTFT reduction después primera) │
        │  ✓ AsyncAnthropic (non-blocking)                        │
        │  ✓ Instant opener (sin API call)                        │
        │  ✓ Especulative generation (durante transcripción)      │
        │                                                            │
        │  Salida: Streaming token-by-token                         │
        └─────────────────────────┬─────────────────────────────────┘
                                  │
                                  ▼
        ┌─────────────────────────────────────────────────────────┐
        │  WebSocket Broadcaster (Local, 127.0.0.1:8765)          │
        │  • Envía tokens JSON a clientes WebSocket               │
        │  • Manejo de desconexiones                              │
        │  • Múltiples clientes simultáneos                       │
        └─────────────────────────┬───────────────────────────────┘
                                  │
                                  ▼
        ┌─────────────────────────────────────────────────────────┐
        │  SmartTeleprompter (PyQt5 Overlay)                      │
        │                                                         │
        │  UI:                                                    │
        │  • Overlay frameless, always-on-top                    │
        │  • Scroll auto con nuevos tokens                       │
        │  • Parsing de [PAUSE] y **énfasis**                   │
        │  • Mostrador de WPM                                    │
        │                                                         │
        │  Controles (Ctrl+):                                    │
        │  • ↑/↓: Tamaño de fuente (16-48px)                     │
        │  • ←/→: Velocidad (60-200 WPM)                        │
        │  • O: Ciclo de opacidad (70-90%)                      │
        │  • C: Limpiar texto                                   │
        │  • Q: Salir                                            │
        └────────────────────────────────────────────────────────┘
                                  │
                                  ▼
        ┌─────────────────────────────────────────────────────────┐
        │  Logging de Sesión                                      │
        │  • Archivo: logs/interview_YYYY-MM-DD_HH-MM.md         │
        │  • Formato: Pregunta → Respuesta sugerida              │
        │  • Estadísticas finales                                │
        └─────────────────────────────────────────────────────────┘
```

### Características Arquitectónicas
✅ **Pipeline Asincrónico Puro:** Múltiples operaciones en paralelo (transcripción + retrieval + generación)  
✅ **Sin Web Server:** Comunicación directa Python → PyQt5 vía WebSocket local  
✅ **Dual-Channel Transcription:** Mantiene contexto de ambos participantes  
✅ **RAG Grounded:** Respuestas basadas en KB personal/empresa (reduce alucinaciones)  
✅ **Optimizaciones Multi-Layer:** Especulación, caché, instant openers  

---

## 🔌 COMPONENTES PRINCIPALES

### 1. **AudioCaptureAgent** (`src/audio/capture.py`)
**Responsabilidad:** Capturar audio de dos fuentes simultáneamente

#### Arquitectura
```python
AudioCaptureAgent
├── _stream_user (RawInputStream)
│   └── Device: Micrófono Voicemeeter B1 o default
│       └── Callback: _cb_user() → user_queue
├── _stream_int (RawInputStream)
│   └── Device: Audio Sistema Voicemeeter B2 o Stereo Mix
│       └── Callback: _cb_interviewer() → int_queue
│           └── Resampling + ganancia si es Loopback
└── user_queue, int_queue: asyncio.Queue
    └── Consumidas por OpenAIRealtimeTranscriber
```

#### Parámetros Clave
| Parámetro | Valor por Defecto | Ajustable |
|-----------|------------------|----------|
| Sample Rate | 16 kHz | `AUDIO_SAMPLE_RATE` env |
| Chunk Duration | 100 ms | `AUDIO_CHUNK_MS` env |
| Dtype | PCM int16 | (fixed) |
| Queue Size | 100 frames | (internal) |

#### Estrategia de Fallback
1. **Intento 1:** Dispositivo configurado en env (`VOICEMEETER_DEVICE_USER`, `VOICEMEETER_DEVICE_INT`)
2. **Intento 2 (User):** Default system input device
3. **Intento 2 (Int):** Buscar "Stereo Mix" / "Mezcla Estéreo" / "Loopback"
   - Si encontrado: resampling nativo → 16 kHz mono
   - Aplicar ganancia 2x (Stereo Mix típicamente suena bajo)
   - Loguear RMS cada 100 chunks para diagnosticar

#### Problemas Conocidos
⚠️ **Voicemeeter no instalado:** Fallback a micrófono default únicamente, sin audio de sistema  
⚠️ **Loopback no disponible:** En algunos Windows (e.g., Home Edition), Stereo Mix deshabilitado  
⚠️ **QueueFull:** Si transcripción es muy lenta, chunks se descartan (sin back-pressure)  

---

### 2. **OpenAIRealtimeTranscriber** (`src/transcription/openai_realtime.py`)
**Responsabilidad:** Streaming de audio a OpenAI API, recibir transcripción en tiempo real

#### Configuración de Sesión
```json
{
  "type": "session.update",
  "session": {
    "model": "gpt-4o-mini-transcribe",
    "input_audio_format": "pcm_16"
  }
}
```

#### Tres Buffers
| Buffer | Propósito | Reset |
|--------|-----------|-------|
| `_live_buffer` | Delta text (parcial, en vivo) | Con cada delta event |
| `_turn_buffer` | Segmentos completados | Con cada turn end |
| `_recent_turns` (deque, maxlen=10) | Histórico para contexto | Circular |

#### Eventos Capturados
- **`input_audio_buffer.speech_started`:** Nuevo turno comienza
- **`input_audio_buffer.speech_stopped`:** Turno finaliza
- **`response.audio.delta`:** Texto parcial de transcripción
- **`response.done`:** Transcripción completa

#### Callbacks Registrados en `main.py`
```python
on_transcript(speaker: str, text: str)  # Turno completo
on_delta(speaker: str, partial: str)    # Parcial en vivo
on_speech_event(speaker: str, event: str)  # started/stopped
```

#### Costo vs Alternativas
| Modelo | Costo | Latencia | VAD |
|--------|-------|----------|-----|
| **gpt-4o-mini-transcribe** (actual) | ~$0.003/min | <300ms | Semántico ✓ |
| Deepgram Nova-2 | $0.002/min | <300ms | Semántico ✓ |
| OpenAI Whisper (batch) | $0.006/min | 5-30s | No |
| Twilio | ~$0.01/min | <300ms | Sí |

**Conclusión:** OpenAI Realtime es balance óptimo costo-latencia.

---

### 3. **QuestionFilter** (`src/knowledge/question_filter.py`)
**Responsabilidad:** Diferenciar preguntas de entrevista reales de ruido

#### Lógica
```
Entrada: transcripción de "interviewer"
  ↓
1. Rechazar si matches NOISE_PATTERNS (30+ regex)
   - Saludos: "hi", "hello", "good morning"
   - Filler: "um", "uh", "hmm", "ok"
   - Meta: "let's start", "shall we pause"
   - Closing: "thank you for your time"
   ↓
2. Check MIN_WORD_COUNT
   - Normal: 4+ palabras
   - Con "?": 3+ palabras (lower bar)
   ↓
3. Boost si tiene signals (30+)
   - STAR: "describe a time", "give me an example"
   - Personal: "tell me about yourself", "strengths"
   - Company: "what do you know", "why this company"
   - Technical: "explain", "how does"
   ↓
4. Calcular score heurístico
   - Si score ≥ threshold → Pasar
   - Sino → Rechazar (log estadística)
```

#### Estadísticas Capturadas
```python
_total_checked: int  # Todas las transcripciones
_total_passed: int   # Aprobadas como preguntas
_total_rejected: int # Rechazadas
```

#### Problemas
⚠️ **False Negatives:** Preguntas complejas sin signals pueden rechazarse  
⚠️ **False Positives:** Affirmations largas ("You know, I think we should talk about...") podrían pasar  

---

### 4. **QuestionClassifier** (`src/knowledge/classifier.py`)
**Responsabilidad:** Categorizar pregunta y asignar presupuesto de tokens

#### Estrategia Dual
1. **FastPath (Fallback):** Rule-based, 0 latencia
   ```python
   if "situational" in q.lower() or "describe a time" in q:
       return {"type": "situational", "budget": 2048}
   ```

2. **SlowPath (API):** Claude Haiku 4.5, ~200ms
   - Clasificación más precisa
   - Detección de compound questions
   - Fallback automático si falla

#### Matriz de Tipos y Presupuestos
| Tipo | Budget Base | Con Compound | Ejemplo |
|------|------------|-------------|---------|
| simple | 512 | 512 | "What's your availability?" |
| personal | 512 | 512 | "Tell me about yourself" |
| company | 1024 | 2048 | "Why this company?" |
| hybrid | 1024 | 2048 | "Personal + company mezcla" |
| situational | 2048 | 4096 | "STAR question" |

#### Detección de Compound
```python
is_compound = q.count("?") > 1 or (" and " in q and len(q.split()) > 12)
# Budget *= 2 si compound
```

---

### 5. **KnowledgeRetriever** (`src/knowledge/retrieval.py`)
**Responsabilidad:** Búsqueda semántica en KB

#### Pipeline de Retrieval
```
Query: "Tell me about yourself"
  ↓
1. Embed query via OpenAI text-embedding-3-small
   (384 dims, optimize-token variant)
  ↓
2. ChromaDB similarity search
   - Metric: cosine distance
   - Top-K (ajustable):
     * simple: 2
     * personal: 3
     * company: 3
     * hybrid: 5
     * situational: 4
  ↓
3. Aplicar where-filter (opcional)
   - Si question_type == "personal" → category:"personal"
   - Si question_type == "company" → category:"company"
   - Sino → sin filtro (buscar all)
   - Si no hay resultados con filtro → reintentar sin filtro
  ↓
4. Formatear chunks con metadata
   - Incluir source file, topic
   - Ordenar por relevancia
  ↓
5. Retornar lista de strings (texto puro)
```

#### ChromaDB Collection
```python
collection.create(
    name="interview_kb",
    metadata={"hnsw:space": "cosine"}  # HNSW = efficient ANN index
)
```

#### Datos de Ejemplo
```
kb/
├── personal/
│   ├── perfil_luis_araujo.txt
│   │   "Luis Araujo, 3+ años experience en Webhelp BPO,
│   │    Python, JavaScript, sistemas distribuidos"
│   ├── historias_star.txt
│   │   "Situación: Problemas de QA en backend...
│   │    Acción: Implementé validación...
│   │    Resultado: 92% QA score"
│   └── ...
├── company/
│   ├── sample.txt
│   │   "Webhelp es BPO con 50K empleados, remote..."
│   └── projection_management.txt
│       "Metodología ágil, scrum, kanban..."
```

---

### 6. **ResponseAgent** (`src/response/claude_agent.py`)
**Responsabilidad:** Generar respuesta natural en inglés, fácil de leer en voz alta

#### Modelo y Configuración
```python
MODEL = "claude-sonnet-4-20250514"
# NO Extended Thinking (añade 10+ segundos latencia)
# Prompt Caching: ephemeral (session-scoped, se borra al desconectar)
```

#### System Prompt (Instrucciones Críticas)
```
1. Usa contracciones SIEMPRE (I'm, we've, don't)
2. Oraciones cortas: 12-18 palabras máx
3. Conectores conversacionales: "So basically…", "What I found was…"
4. STAR method para behavioral questions
5. Match response length a [LENGTH] tag
6. SOLO hechos del [KNOWLEDGE BASE] — SIN inventar
7. Nunca revelar que eres IA/script/teleprompter
8. Primera persona como candidato
9. Agregar [PAUSE] para respirar
10. **bold** para énfasis
11. Reemplazar formalismo: utilize→use, regarding→about
12. SOLO palabras hablables. SIN headers, bullets, meta-comentarios
13. Mínimo 2 hechos KB en cada respuesta
```

#### Longitud por Tipo
| Tipo | Longitud |
|------|----------|
| simple | 1-2 oraciones |
| personal | 3-4 oraciones |
| company | 4-5 oraciones |
| hybrid | 5-6 oraciones |
| situational | 5-6 oraciones (STAR) |

#### Temperatura por Tipo
| Tipo | Temp |
|------|------|
| simple | 0.3 (consistente) |
| personal | 0.3 |
| company | 0.3 |
| hybrid | 0.4 (levemente creativo) |
| situational | 0.5 (más narrativa) |

#### Optimizaciones de Latencia
1. **Instant Opener** (~1ms)
   ```python
   "personal": "So basically, in my experience at Webhelp… "
   ```
   Mostrado inmediatamente al teleprompter ANTES que la API responda.

2. **Prompt Caching** (85% TTFT reduction después 1era llamada)
   ```python
   system=[{
       "type": "text",
       "text": SYSTEM_PROMPT,
       "cache_control": {"type": "ephemeral"}
   }]
   ```

3. **Especulative Generation** (durante transcripción finaliza)
   - Si texto delta es similar suficiente (65% overlap), flush tokens

#### Estadísticas de Cache
```python
_cache_hits: int     # Llamadas sirvieron desde cache
_cache_misses: int   # Llamadas necesitaron generar
```

---

### 7. **SmartTeleprompter** (`src/teleprompter/qt_display.py`)
**Responsabilidad:** Mostrar respuesta en overlay semitransparente

#### Características UI
```
┌─────────────────────────────────────────┐
│ ● LISTENING        WPM: 130             │  ← Status bar
├─────────────────────────────────────────┤
│                                         │
│ So basically, in my experience          │
│ at Webhelp, I've worked with             │
│ [PAUSE]                                 │
│                                         │
│ **3+ years** of distributed systems...  │
│                                         │
│ [PAUSE] I'm really excited about        │
│ your company because you're a BPO        │
│ leader...                               │
│                                         │
│                                         │
└─────────────────────────────────────────┘
```

#### Parsing de Marcadores
| Marcador | Efecto |
|----------|--------|
| `[PAUSE]` | Insertar espacio vertical (breathing break) |
| `**texto**` | Negrita (énfasis visual) |
| Saltos de línea | Preservados como-es |

#### Controles (Keyboard Shortcuts)
| Combo | Efecto |
|-------|--------|
| Ctrl+↑ | Font size +2px (hasta 48px) |
| Ctrl+↓ | Font size -2px (hasta 16px) |
| Ctrl+← | WPM -10 (hasta 60 WPM) |
| Ctrl+→ | WPM +10 (hasta 200 WPM) |
| Ctrl+O | Ciclo opacidad: 70% → 80% → 90% → 70% |
| Ctrl+C / Esc | Limpiar texto, reset |
| Ctrl+Q | Salir |

#### Parámetros por Defecto
| Parámetro | Valor |
|-----------|-------|
| WPM | 130 |
| Opacity | 80% (80% opaque, 20% transparente) |
| Font Size | 28px |
| Font | "Segoe UI", "Inter", "Roboto" |
| Posición | Bottom-center de pantalla |
| Window Flags | Frameless, Always-On-Top, Tool (no taskbar) |

#### Eventos Qt
- `text_received(str)`: Emitido cuando llega token → se conecta a `_on_text_received`
- `response_cleared()`: Emitido cuando se limpia

---

### 8. **TeleprompterBridge** (`src/teleprompter/ws_bridge.py`)
**Responsabilidad:** Puente WebSocket entre Pipeline y Teleprompter (separados en procesos)

#### Arquitectura
```
main.py (Coordinator)          ws_bridge.py (Qt Process)
├── WebSocket Server           ├── WebSocket Client
│   (127.0.0.1:8765)          │   (connect to 127.0.0.1:8765)
│   └── broadcast_message()    │   │
│       └── {type: "token", ...}→  └── _listen()
└── broadcast_token()              └── _handle_message()
                                       └── teleprompter.append_text()
```

#### Reconnect Logic
```
Intenta conectar → Max 10 intentos con 3s delay
- Si ConnectionRefused: servidor aún no inició
- Si ConnectionClosed: servidor se reinició
- Si JSONDecodeError: mensaje malformado (skip)
```

---

### 9. **KnowledgeIngestor** (`src/knowledge/ingest.py`)
**Responsabilidad:** Cargar documentos KB → chunks → embeddings → ChromaDB

#### Pipeline
```
kb/personal/, kb/company/
  │ (iterate .txt, .md files)
  ▼
read_text(encoding="utf-8")
  │
  ▼ RecursiveCharacterTextSplitter
  │ (chunk_size=300, overlap=50)
  │ separators: "\n\n", "\n", ". ", ", ", " "
  ▼
chunks: list[str]
  │
  ▼ OpenAI text-embedding-3-small
  │ (384 dims)
  ▼
embeddings: list[list[float]]
  │
  ▼ ChromaDB store
  collection.add(
    ids=[...],
    embeddings=[...],
    documents=[...],
    metadatas=[{
      "category": "personal|company",
      "topic": "...",
      "source": "perfil_luis_araujo.txt"
    }]
  )
```

#### Parámetros
| Param | Valor |
|-------|-------|
| Chunk Size | 300 chars |
| Overlap | 50 chars |
| Embedding Model | text-embedding-3-small |
| ChromaDB Backend | Persistent (SQLite + HNSW index) |

---

## 📊 ANÁLISIS DETALLADO DE MÓDULOS

### Módulo: `main.py` (Coordinador Principal)
**Líneas:** 637  
**Responsabilidad:** Orquestación del pipeline, sincronización de callbacks, WebSocket

#### Clases
1. **PipelineState**
   - Holder de estado global
   - Instancias de todos los agentes
   - WebSocket client set
   - Conversation history

2. **Callbacks Async**
   - `on_transcript(speaker, text)` → main entry point
   - `on_delta(speaker, partial)` → streaming text para subtítulos
   - `on_speech_event(speaker, event)` → "started"/"stopped" para especulación

#### Variables Globales (State Speculation)
```python
_speculative_retrieval_task: asyncio.Task | None
_speculative_query: str
_speculative_gen_task: asyncio.Task | None
_speculative_gen_tokens: list[str]
```

#### Funciones Clave
1. **`async def process_question(question, speaker_name)`** (línea ~284)
   - Clasifica pregunta
   - Retrieves KB chunks
   - Genera respuesta con Claude
   - Streams tokens to teleprompter
   - Logs a archivo sesión

2. **`async def on_speech_event(speaker, event)`** (línea ~177)
   - Si `event == "stopped"`: Inicia pre-fetch especulativo
   - Si `event == "started"`: Cancela especulación obsoleta

3. **`async def broadcast_message(message)`** (línea ~75)
   - Envía JSON a todos los WebSocket clients
   - Maneja desconexiones gracefully

#### Optimizaciones Implementadas
1. **Especulative Retrieval (#1):** Pre-fetch KB durante transcripción
2. **Instant Opener (#2):** Mostrar en teleprompter antes de API
3. **Speculative Generation (#3):** Generar respuesta en paralelo, flush si válida

---

### Módulo: `src/audio/capture.py` (Captura Audio)
**Líneas:** 355  

#### Callbacks en Audio Thread
⚠️ **Crítico:** Mantener `_cb_user()` y `_cb_interviewer()` lo más rápido posible.
- No hacer API calls
- No locks largos
- Solo `queue.put_nowait()`

#### Fallback Chain
```
User Stream:
  1. Try: Voicemeeter B1 device (VOICEMEETER_DEVICE_USER env)
  2. Fallback: Default system input device
  
Interviewer Stream:
  1. Try: Voicemeeter B2 device (VOICEMEETER_DEVICE_INT env)
  2. Try: Stereo Mix / Mezcla Estéreo / Loopback device
     - Si encontrado: resampling inline + ganancia 2x
  3. Fallback: Log warning, solo user audio capturado
```

#### Ganancia de Loopback
```python
LOOPBACK_GAIN = float(os.getenv("LOOPBACK_GAIN", "2.0"))
```
Típicamente Stereo Mix suena 50% del volumen, ganancia 2x lo compensa.

---

### Módulo: `src/transcription/openai_realtime.py` (Transcripción)
**Líneas:** 378  

#### WebSocket Lifecycle
```
1. create(url, headers, ping_interval=20, ping_timeout=10)
2. _configure_session() → Send {"type": "session.update", "session": {...}}
3. Parallel: _send_audio_loop() + _receive_events_loop()
   - Sender: lee audio_queue, envía en PCM 16-bit base64
   - Receiver: parsea events JSON, invoca callbacks
4. Auto-reconnect con exponential backoff (max 5 intentos)
```

#### Events Handled
```python
{
  "type": "response.audio.delta",
  "delta": "partial text"
}
→ on_delta(speaker, "partial text")

{
  "type": "response.audio.done",
  "response_id": "123",
}
→ Transcripción completa, flush _turn_buffer

{
  "type": "input_audio_buffer.speech_started" | "stopped"
}
→ on_speech_event(speaker, "started"|"stopped")
```

---

### Módulo: `src/knowledge/classifier.py` (Clasificador)
**Líneas:** 223  

#### Rule-Based Classifier (Fallback)
```python
@staticmethod
def _fallback_classify(question: str) -> dict:
    """Sin API calls, < 1ms latencia"""
    q = question.lower()
    
    # Check 1: Compound (múltiples ?)
    if q.count("?") > 1:
        return {"type": "hybrid", "compound": True, ...}
    
    # Check 2: Situational signals
    if "describe a time" in q or "what would you do":
        return {"type": "situational", ...}
    
    # etc...
```

**Señales por Tipo:**
- **Situational:** "describe a time", "what would you do", "how would you handle", "imagine", "if you were", "give me an example"
- **Company:** "about us", "why this company", "mission", "culture", "why do you want to work"
- **Personal:** "tell me about yourself", "strengths", "weaknesses", "your background", "career"

---

### Módulo: `src/knowledge/question_filter.py` (Filtro Preguntas)
**Líneas:** 200  

#### Noise Patterns (30+ regex)
```python
NOISE_PATTERNS = [
    r"^(hi|hello|hey|good morning|...)[\s\.\!]*$",
    r"^(um+|uh+|hmm+|ah+|ok+|...)[\s\.\!\?]*$",
    r"^(thank you for|that's all|...)[\s\.\!]*$",
]
```

#### Interview Signals (50+ patrones)
```python
INTERVIEW_SIGNALS = [
    "tell me about yourself",
    "walk me through",
    "describe a time",
    "what would you do",
    "what are your",
    # ... 45+ más
]
```

#### Scoring
```python
1. Si matches noise → REJECT
2. Si word_count < min → REJECT
3. Si tiene ? o signal → score += ...
4. Si score >= threshold → ACCEPT
```

---

### Módulo: `src/response/claude_agent.py` (Generador Respuestas)
**Líneas:** 272  

#### Warmup (Priming Cache)
```python
async def warmup(self):
    """Pre-warm API + prime prompt cache for first call"""
    response = await self.client.messages.create(
        model=MODEL,
        max_tokens=5,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}
        }],
        messages=[{"role": "user", "content": "Hi"}]
    )
    # Cache creado, próximas llamadas serán 85% más rápidas
```

#### Stream Generation
```python
async with self.client.messages.stream(...) as stream:
    async for text in stream.text_stream:
        yield text  # Token-by-token streaming
        
response = await stream.get_final_message()
# Check usage.cache_read_input_tokens / cache_creation_input_tokens
```

---

### Módulo: `src/teleprompter/qt_display.py` (Teleprompter)
**Líneas:** 442  

#### Qt Signal/Slot Architecture
```python
text_received = pyqtSignal(str)

def append_text(self, token: str):
    self.text_received.emit(token)  # Thread-safe
    
@pyqtSlot(str)
def _on_text_received(self, token: str):
    # Running in main Qt thread
    self._current_text += token
    self._update_display()
```

#### Keyboard Event Handling
```python
def keyPressEvent(self, event):
    if event.key() == Qt.Key_Up and event.modifiers() & Qt.ControlModifier:
        self.set_font_size(self.current_font_size + 2)
    # etc...
```

---

## 🔄 FLUJO DE DATOS

### Flujo Completo: Pregunta → Respuesta en Teleprompter

#### Timeline Típico
```
T=0ms
  ├─ Entrevistador comienza a hablar
  ├─ on_delta() → subtítulos en vivo (100-200ms después de habla)
  
T=100-500ms
  ├─ on_speech_event("stopped") dispara
  │  ├─ Extraer _live_buffer
  │  ├─ _run_speculative_retrieval() → fetch KB (async, ~500-1000ms)
  │  └─ _run_speculative_generation() → generar respuesta (async, ~2-3s)
  
T=500-2000ms
  ├─ Transcripción OpenAI procesa audio (VAD, ASR, ~1-1.5s después stopped)
  ├─ on_transcript("interviewer", "Tell me about yourself")
  ├─ QuestionFilter.is_interview_question() → True
  ├─ process_question() inicia
  │  ├─ Clasificar: "personal" (instant)
  │  ├─ Check especulative hit: ¿tiene respuesta ready?
  │  │  └─ Si sí y similar (65%): flush tokens + log "speculative hit", return
  │  ├─ Instant opener: broadcast "So basically, in my experience…"
  │  ├─ Retrieve KB: usar pre-fetch si ready, sino fetch fresco
  │  ├─ Generate respuesta (CloudAPI 2-3s o cache hit 400ms)
  │  ├─ Stream tokens a teleprompter (cada token ~50ms)
  │  ├─ Log a archivo sesión
  │  └─ response_end event
  
T=2000-5000ms
  ├─ Teleprompter recibe y muestra tokens en tiempo real
  ├─ Usuario lee respuesta en overlay
  │
  └─ Response completa ~3-5s después de pregunta terminada

T=5000ms+
  ├─ Usuario responde en inglés
  ├─ on_transcript("user", "So basically, I've worked at Webhelp for 3 years...")
  ├─ Guardado en conversation_history (NO desencadena RAG)
  ├─ Esperando siguiente pregunta
```

#### Latencia de Cada Componente
| Componente | Latencia | Notes |
|-----------|----------|-------|
| Audio Capture | ~100ms | 100ms buffer size |
| OpenAI Realtime | ~1-1.5s | VAD + ASR |
| QuestionFilter | <5ms | Rule-based |
| QuestionClassifier | 1-200ms | Fallback fast, API slower |
| KnowledgeRetriever | 500-1000ms | Embedding + ChromaDB search |
| ResponseAgent | 2-4s (cache hit) / 4-6s (cache miss) | Prompt caching crucial |
| Teleprompter Display | <50ms | Solo append + scroll |
| **TOTAL (P50)** | **~3-4s** | Desde end-of-speech hasta respuesta |
| **TOTAL (P95)** | **~5-7s** | Cache miss + network delay |

---

## ⚡ OPTIMIZACIONES DE LATENCIA

### Optimización #1: Pre-fetch Especulativo de KB
**Timing:** Dispara cuando `on_speech_event("interviewer", "stopped")`

```python
async def _run_speculative_retrieval(delta_text: str):
    """Run in background, no await needed"""
    try:
        chunks = await pipeline.retriever.retrieve(
            query=delta_text,
            question_type="personal"  # default guess
        )
        _speculative_retrieval_task = chunks
        logger.info("Speculative retrieval ready")
    except Exception:
        pass  # Silent fail
```

**Ahorro:** ~500-1000ms (tiempo de espera de transcripción final)

---

### Optimización #2: Instant Opener
**Timing:** Mostrado inmediatamente en `process_question()`

```python
opener = pipeline.response_agent.get_instant_opener("personal")
# Returns: "So basically, in my experience at Webhelp… "
await broadcast_message({"type": "token", "data": opener})
# Teleprompter ya muestra ANTES que Claude API responda
```

**Ahorro:** ~2-3s (tiempo de primera API call)

---

### Optimización #3: Speculative Generation
**Timing:** Dispara durante transcripción, flush si similar

```python
_is_similar_enough = lambda delta, final: (
    len(set(delta.split()) & set(final.split())) / 
    max(1, len(set(final.split())))
) >= 0.65

# En process_question():
if (_speculative_gen_task and 
    _speculative_gen_tokens and 
    _is_similar_enough(delta_text, final_transcript)):
    # ¡Respuesta especulativa es válida! Flush tokens
    for token in _speculative_gen_tokens:
        await broadcast_token(token)
    logger.info("Speculative generation hit ✓")
    return
```

**Ahorro:** ~3-5s (si delta final es similar suficiente)  
**Riesgo:** Respuesta basada en texto incompleto podría ser incorrecta

---

### Optimización #4: Prompt Caching
**Model:** Claude Sonnet 4 (soporta ephemeral caching)

```python
system=[{
    "type": "text",
    "text": SYSTEM_PROMPT,  # ~800 tokens
    "cache_control": {"type": "ephemeral"}
}]
```

**Beneficio:** Después 1era llamada, TTFT (time-to-first-token) ~85% más rápido  
**Estimado:** ~400ms con cache hit vs 2-3s sin cache

---

## 📚 GESTIÓN DEL CONOCIMIENTO

### Estructura KB
```
kb/
├── personal/
│   ├── perfil_luis_araujo.txt
│   │   Contenido: Background, skills, experience, metrics
│   │   Ejemplo: "Luis Araujo, 3+ años en Webhelp, Python, 92% QA"
│   ├── historias_star.txt
│   │   Formato: STAR (Situación, Tarea, Acción, Resultado)
│   │   Ejemplo: "[Sit] QA scores dropping... [Task] Lead fix...
│   │            [Act] Implemented validator... [Result] 92% QA"
│   ├── preguntas_dificiles.txt
│   │   Tricky questions + suggested answers
│   ├── profile_english.txt
│   │   English version of perfil
│   └── ...
├── company/
│   ├── projection_management.txt
│   │   Company details, mission, culture
│   └── sample.txt
│       Proyecto details
```

### Embedding Strategy
- **Model:** `text-embedding-3-small` (384 dims, optimized for tokens)
- **Chunk Size:** 300 chars with 50 overlap
- **Splitter:** Recursive (separators: "\n\n", "\n", ". ", ", ", " ")

### Retrieval Strategy
```python
# Top-K by question type
TOP_K_BY_TYPE = {
    "simple": 2,      # "What's your availability?"
    "personal": 3,    # "Tell me about yourself"
    "company": 3,     # "Why this company?"
    "hybrid": 5,      # Mixed questions
    "situational": 4, # STAR questions
}

# Category filter
if question_type == "personal":
    where_filter = {"category": "personal"}
elif question_type == "company":
    where_filter = {"category": "company"}
# else: search all
```

### KB Ingestion Process
```
python -c "
from src.knowledge.ingest import KnowledgeIngestor
ingestor = KnowledgeIngestor()
stats = ingestor.ingest_all()
print(f'Ingested {stats[\"total_chunks\"]} chunks')
"
```

### ChromaDB Backend
```
chroma_data/
├── chroma.sqlite3        # Metadata + IDs
├── [collection-uuid]/
│   ├── index             # HNSW vector index (ann_index.bin)
│   ├── data              # Serialized vectors/documents
│   └── ...
```

---

## 🧪 ANÁLISIS DE CALIDAD

### Testing Framework
- **Test Runner:** pytest 8.3.4
- **Async Support:** pytest-asyncio 0.25.3
- **Coverage:** pytest-cov 6.0.0

### Test Suites
1. **`test_audio.py`** - Captura y resampling de audio
2. **`test_knowledge.py`** - Ingestion, embedding, retrieval
3. **`test_latency.py`** - Medición de latencia end-to-end
4. **`test_question_filter.py`** - Precisión del filtro de preguntas
5. **`simulate_pipeline.py`** - Simulación 20+ preguntas con latency analysis

### Métricas Capturadas
```python
# simulate_pipeline.py
metrics = {
    "question_id": int,
    "classification_ms": float,
    "retrieval_ms": float,
    "generation_ms": float,
    "total_ms": float,
    "response_quality_score": float,  # 0-100
    "hallucination_detected": bool,
    "kb_grounding": float,  # % de hechos del KB
}
```

### Quality Criteria (de Roadmap)
1. ✅ Response grounded in KB (min 80% hechos)
2. ✅ No hallucinations detected (human review)
3. ✅ Oraciones cortas (<18 palabras)
4. ✅ Contracciones usadas
5. ✅ [PAUSE] y **emphasis** bien colocados
6. ✅ Latencia < 2.2s (P95)

---

## ⚠️ PROBLEMAS Y LIMITACIONES

### Críticos

1. **Variables Globales de Especulación sin Sincronización**
   ```python
   _speculative_gen_task: asyncio.Task | None = None
   _speculative_gen_tokens: list[str] = []
   ```
   - ⚠️ Si múltiples preguntas llegan rápidamente, could race condition
   - 🔧 Fix: Use asyncio.Lock o queue-based state management

2. **Acceso a Atributo Privado de OpenAIRealtimeTranscriber**
   ```python
   # En main.py on_speech_event()
   delta_text = pipeline.transcriber_int._live_buffer
   ```
   - ⚠️ Violates encapsulation
   - 🔧 Fix: Agregar getter público

3. **Sin Timeout en generate() Response**
   ```python
   async for text in stream.text_stream:
       yield text  # Si API se cuelga, bloqueado indefinidamente
   ```
   - ⚠️ Teleprompter quedará esperando
   - 🔧 Fix: Wrap con `asyncio.timeout(30)` en Python 3.11+

4. **Subprocess Teleprompter sin Healthcheck**
   ```python
   _teleprompter_proc = subprocess.Popen([...])
   # Si crash, no reintentar
   ```
   - ⚠️ Si Qt window cierra, pipeline sigue generando respuestas (sin UI)
   - 🔧 Fix: Monitor proc.poll() periódicamente

### Altos

5. **Fallback Classification Incompleto**
   - El método `_fallback_classify()` cubre ~90% de preguntas, 10% ambiguas → defaultean a "personal"
   - 🔧 Fix: Mejorar detección de compound questions

6. **KB Está Hardcodeada en Memoria**
   - Sin soporte para actualizar KB en runtime
   - 🔧 Fix: Watch directory `kb/` para cambios, re-ingest automático

7. **Costo de API sin Control de Presupuesto**
   - No hay límite de gastos diarios/mensuales
   - 🔧 Fix: Agregar `spending_limit` config + alertas

8. **Especulative Generation Puede Enviar Respuesta Incorrecta**
   - Si delta final es incompleto pero similar (65%), flush especulativa
   - Ejemplo: "Tell me about yourself" → delta especulativo cubre 70% pero respuesta es sobre project, no background
   - 🔧 Fix: Aumentar threshold a 80% o usar semantic similarity (embed ambos)

### Medios

9. **Sin Retry Logic para Fallos Transientes**
   ```python
   # Si OpenAI API falla:
   # - Transcription: auto-reconnect (5x)
   # - Retrieval: no retry
   # - Generation: no retry
   ```
   - 🔧 Fix: Exponential backoff para retrieval/generation

10. **Loopback Gain Hardcodeada**
    ```python
    LOOPBACK_GAIN = 2.0  # Puede ser muy alto/bajo en algunos PCs
    ```
    - 🔧 Fix: Dynamic gain adjustment basado en RMS level detectado

11. **Sin Validación de Entrada de Usuario**
    - Transcriptions podrían contener emojis, caracteres especiales
    - 🔧 Fix: Sanitizar antes de pasar a Claude

12. **ChromaDB Sin Backup Automático**
    - Si `chroma_data/` se borra, todo el KB se pierde
    - 🔧 Fix: Exportar KB a JSON periódicamente, versionamiento

13. **WebSocket Server Expuesto a 127.0.0.1 Únicamente**
    - ✓ Bueno: No accessible remotamente
    - ⚠️ Pero: Sin autenticación entre main.py y teleprompter (mismo host)
    - 🔧 Fix: Token-based authentication para múltiples usuarios

### Bajos

14. **Logging Verbose en Production**
    - ~500+ logs por sesión de 10min
    - 🔧 Fix: Reducir verbosity a WARN por defecto, DEBUG con envvar

15. **No hay Métricas de Monitoreo**
    - Sin dashboards de latencia, cache hits, error rates
    - 🔧 Fix: Integrar telemetría (e.g., StatsD, Prometheus)

16. **Teleprompter UI No Responsive**
    - Si generación es lenta, UI freezes (Qt event loop bloqueado por WebSocket)
    - 🔧 Fix: Mover _listen() a thread separado

---

## 💡 RECOMENDACIONES

### Priority 1 (CRÍTICO)

#### 1.1 Agregar Sincronización a Variables Globales de Especulación
```python
# Reemplazar:
_speculative_gen_task: asyncio.Task | None = None
_speculative_gen_tokens: list[str] = []

# Con:
class SpeculativeState:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.gen_task: asyncio.Task | None = None
        self.gen_tokens: list[str] = []
        self.query: str = ""
        
    async def clear(self):
        async with self.lock:
            if self.gen_task:
                self.gen_task.cancel()
            self.gen_tokens.clear()

_speculative = SpeculativeState()
```

#### 1.2 Exponer _live_buffer Públicamente
```python
# En OpenAIRealtimeTranscriber:
class OpenAIRealtimeTranscriber:
    def get_live_buffer(self) -> str:
        """Get current delta text for speculative retrieval"""
        return self._live_buffer
```

#### 1.3 Agregar Timeout a Response Generation
```python
# En ResponseAgent.generate():
import asyncio
try:
    async with asyncio.timeout(30):  # Python 3.11+
        async with self.client.messages.stream(...) as stream:
            async for text in stream.text_stream:
                yield text
except asyncio.TimeoutError:
    logger.error("Response generation timeout")
    yield "[Response generation timeout - please try again]"
```

### Priority 2 (ALTO)

#### 2.1 Monitoreo de Salud del Teleprompter
```python
async def monitor_teleprompter():
    """Check if teleprompter subprocess is still alive"""
    while True:
        await asyncio.sleep(30)
        if _teleprompter_proc and _teleprompter_proc.poll() is not None:
            logger.error("Teleprompter crashed, restarting…")
            await start_teleprompter()
        
asyncio.create_task(monitor_teleprompter())
```

#### 2.2 Mejorar Detección de Compound Questions
```python
# En QuestionClassifier._fallback_classify():
# Agregar detección de "and" + verbos conjugados diferentes
def is_compound_question(q: str) -> bool:
    """Detect multi-part questions"""
    parts = re.split(r'\s+and\s+', q, flags=re.IGNORECASE)
    if len(parts) >= 2:
        # Check si cada parte es una pregunta
        return sum(1 for p in parts if '?' in p) > 1
    return False
```

#### 2.3 KB Hot-Reload
```python
# Monitorear kb/ directory para cambios
from watchfiles import watch

async def watch_kb():
    async for changes in watch("kb/"):
        logger.info(f"KB changes detected: {changes}")
        # Re-ingest changed files
        ingestor = KnowledgeIngestor()
        ingestor.ingest_all()
        
asyncio.create_task(watch_kb())
```

### Priority 3 (MEDIO)

#### 3.1 Retry Logic con Exponential Backoff
```python
async def retry_retrieval(query, question_type, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await pipeline.retriever.retrieve(query, question_type)
        except Exception as e:
            if attempt < max_retries - 1:
                delay = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(f"Retrieval failed, retry in {delay}s: {e}")
                await asyncio.sleep(delay)
            else:
                logger.error(f"Retrieval failed after {max_retries} retries")
                return []
```

#### 3.2 Validación de Entrada y Sanitización
```python
import re
def sanitize_transcript(text: str) -> str:
    """Remove problematic characters"""
    # Remove emojis
    text = re.sub(r'[\U0001F600-\U0001F64F]', '', text)
    # Remove control characters
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\t')
    return text.strip()

# En on_transcript():
text = sanitize_transcript(text)
```

#### 3.3 Estadísticas y Telemetría
```python
from dataclasses import dataclass, field
from datetime import datetime

@dataclass
class SessionMetrics:
    start_time: datetime
    total_questions: int = 0
    total_responses: int = 0
    total_latency_ms: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    retrieval_hits: int = 0  # How many used pre-fetch
    
    def save_json(self, filepath):
        with open(filepath, 'w') as f:
            json.dump({
                "start_time": self.start_time.isoformat(),
                "total_questions": self.total_questions,
                # ... etc
            }, f, indent=2)

_session_metrics = SessionMetrics(start_time=datetime.now())
```

#### 3.4 Dynamic Loopback Gain Adjustment
```python
# En AudioCaptureAgent._cb_loopback():
RMS_TARGET = 5000  # Target RMS level
GAIN_MIN, GAIN_MAX = 0.5, 4.0

def _adjust_gain(current_rms: float, current_gain: float) -> float:
    """Dynamically adjust gain based on audio level"""
    if current_rms < RMS_TARGET * 0.5:
        return min(current_gain * 1.5, GAIN_MAX)
    elif current_rms > RMS_TARGET * 2:
        return max(current_gain / 1.5, GAIN_MIN)
    return current_gain
```

### Priority 4 (MEJORAS)

#### 4.1 Mejora: Usar Semantic Similarity para Especulative Hit
```python
from openai import OpenAI

async def _is_similar_enough_semantic(delta: str, final: str) -> bool:
    """Use embeddings for better similarity check"""
    if not delta or not final:
        return False
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    delta_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=delta
    ).data[0].embedding
    
    final_emb = client.embeddings.create(
        model="text-embedding-3-small",
        input=final
    ).data[0].embedding
    
    # Cosine similarity
    import numpy as np
    sim = np.dot(delta_emb, final_emb) / (np.linalg.norm(delta_emb) * np.linalg.norm(final_emb))
    return sim > 0.85
```

#### 4.2 Mejora: Cache de Respuestas Frecuentes
```python
# LRU cache para preguntas comunes
from functools import lru_cache

@lru_cache(maxsize=50)
async def get_cached_response(question_hash: str) -> str:
    """Cache responses for repeated questions"""
    # ...
    
# En process_question():
q_hash = hashlib.md5(question.encode()).hexdigest()
if cached := await get_cached_response(q_hash):
    await broadcast_message({"type": "token", "data": cached})
    return
```

#### 4.3 Mejora: Multimodal Support
```python
# Preparación para video transcription en futuro
# Agregar speaker video feeds + facial expressions analysis
# → "Candidate looks nervous, suggest confidence phrases"
```

---

## 📈 ESTADÍSTICAS Y MÉTRICAS ACTUALES

### Del Roadmap (`antigravity.config.json`)
| Métrica | Target | Estado |
|---------|--------|--------|
| P50 Latency | < 1.2s | ~3-4s actual ⚠️ |
| P95 Latency | < 2.2s | ~5-7s actual ⚠️ |
| Throughput | N/A | 1 question/~4s |
| Cache Hit Rate | 80%+ (goal) | Depende de KB size |
| Accuracy | 85%+ | Depende de modelo |

### Distribución de Latencia Esperada
```
Transcripción:     1-1.5s  │ ████
Clasificación:     0-0.2s  │ 
Retrieval:         0.5-1s  │ ██
Generation:        2-4s    │ ███████ (cache miss)
                   0.4s    │ ██ (cache hit)
Broadcast:         <0.1s   │
─────────────────────────────────────────
TOTAL (P50):       3-4s    │
TOTAL (P95):       5-7s    │ ███████████
```

---

## 🎯 CONCLUSIÓN

### Fortalezas del Proyecto
✅ **Arquitectura limpia y modular** — separación clara de concerns  
✅ **Pipeline asincrónico eficiente** — múltiples operaciones paralelas  
✅ **Optimizaciones inteligentes** — especulación durante latencias naturales  
✅ **RAG grounded** — respuestas basadas en hechos  
✅ **Teleprompter real-time** — feedback visual para usuario  
✅ **Fallbacks robustos** — degrada gracefully sin Voicemeeter  

### Áreas de Mejora Crítica
⚠️ Sincronización de estado especulativo  
⚠️ Timeout en generación de respuesta  
⚠️ Monitoring de subprocess teleprompter  
⚠️ Latencia P50/P95 aún alta vs targets  

### Próximos Pasos Recomendados
1. **Fase 1:** Implementar Priority 1 fixes (sincronización, timeouts)
2. **Fase 2:** Telemetría completa + análisis de bottlenecks
3. **Fase 3:** Optimizaciones de latencia (caching KB, semantic similarity)
4. **Fase 4:** Validación en entrevistas reales, tuning de prompts

---

**Análisis Completado:** 1 de Marzo, 2026  
**Analista:** GitHub Copilot  
**Proyecto:** Interview Copilot v2.0 (Python + Claude + PyQt5)

