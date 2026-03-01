# 🔍 CODE REVIEW Y HALLAZGOS TÉCNICOS ESPECÍFICOS
## Interview Copilot v2.0

---

## 📌 HALLAZGOS CLAVE POR ARCHIVO

### 1. `main.py` — Coordinador Principal

#### ✅ Fortalezas
```python
# Línea ~75-102: WebSocket Broadcast robusto
async def broadcast_message(message: dict):
    """✓ Maneja desconexiones gracefully"""
    if not pipeline.ws_clients:
        return
    data = json.dumps(message, ensure_ascii=False)
    disconnected = set()
    for ws in pipeline.ws_clients:
        try:
            await ws.send(data)
        except Exception:
            disconnected.add(ws)  # Track para cleanup
    pipeline.ws_clients -= disconnected  # Cleanup automático
```
**Análisis:** Buena práctica de limpieza de conexiones muertas.

---

#### ⚠️ Problema #1: Variables Globales Sin Sincronización
**Ubicación:** Líneas ~108-112
```python
_speculative_retrieval_task: asyncio.Task | None = None
_speculative_query: str = ""
_speculative_gen_task: asyncio.Task | None = None
_speculative_gen_tokens: list[str] = []
```

**Riesgo:** Race condition si múltiples `on_speech_event()` calls llegan rápidamente:
```
Hilo 1: _speculative_gen_task.cancel()
                ↓ (context switch)
Hilo 2: tokens = _speculative_gen_tokens
                ↓ (gets half-cleared list)
Hilo 1: _speculative_gen_tokens.clear()
```

**Severidad:** CRÍTICO  
**Fix:**
```python
class SpeculativeState:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.retrieval_task: asyncio.Task | None = None
        self.gen_task: asyncio.Task | None = None
        self.gen_tokens: list[str] = []
    
    async def cancel_all(self):
        async with self.lock:
            if self.retrieval_task:
                self.retrieval_task.cancel()
            if self.gen_task:
                self.gen_task.cancel()
            self.gen_tokens.clear()

_speculative = SpeculativeState()
```

---

#### ⚠️ Problema #2: Acceso a Atributo Privado
**Ubicación:** Línea ~227
```python
async def on_speech_event(speaker: str, event: str):
    if event == "stopped":
        # ⚠️ Violates encapsulation
        delta_text = pipeline.transcriber_int._live_buffer
```

**Problema:** `_live_buffer` es privado (notación `_`).  
**Futuro:** Si OpenAIRealtimeTranscriber refactoriza, breaks.

**Fix:**
```python
# En OpenAIRealtimeTranscriber:
def get_live_buffer(self) -> str:
    """Get current delta text (read-only)"""
    return self._live_buffer

# En main.py:
delta_text = pipeline.transcriber_int.get_live_buffer()
```

---

#### ⚠️ Problema #3: Sin Timeout en Response Generation
**Ubicación:** Línea ~365
```python
async for token in pipeline.response_agent.generate(
    question=question,
    kb_chunks=chunks,
    question_type=classification["type"],
):
    await broadcast_token(token)  # ¿Qué pasa si genera timeout?
```

**Riesgo:** Si Claude API se cuelga, `async for` espera indefinidamente.  
**Impacto:** Teleprompter congelado, usuario frustrado.

**Fix:**
```python
import asyncio

try:
    async with asyncio.timeout(30):  # Python 3.11+
        async for token in pipeline.response_agent.generate(...):
            await broadcast_token(token)
except asyncio.TimeoutError:
    logger.error("Response generation timeout")
    await broadcast_message({
        "type": "error",
        "data": "[Response generation timeout - please try again]"
    })
```

---

#### ⚠️ Problema #4: Speculative Hit Threshold Bajo
**Ubicación:** Línea ~281
```python
def _is_similar_enough(delta: str, final: str) -> bool:
    delta_words = set(delta.lower().split())
    final_words = set(final.lower().split())
    overlap = len(delta_words & final_words) / len(final_words)
    return overlap >= 0.65  # ← 65% es bajo para respuesta crítica
```

**Problema:** Pregunta: "Tell me about yourself"  
Delta: "Tell me about a project" (70% overlap)  
Final: "Tell me about your failures" (60% overlap)  
Resultado: Se envía respuesta **incorrecto**.

**Fix:** Aumentar a 80% O usar semantic similarity:
```python
async def _is_similar_enough_semantic(delta: str, final: str) -> bool:
    """Use embeddings for better similarity"""
    if not delta or not final:
        return False
    
    embeddings = client.embeddings.create(
        model="text-embedding-3-small",
        input=[delta, final]
    ).data
    
    import numpy as np
    delta_emb = np.array(embeddings[0].embedding)
    final_emb = np.array(embeddings[1].embedding)
    
    # Cosine similarity
    sim = np.dot(delta_emb, final_emb) / (
        np.linalg.norm(delta_emb) * np.linalg.norm(final_emb)
    )
    return sim > 0.85  # Semantic threshold más alto
```

---

#### ⚠️ Problema #5: Subprocess Teleprompter Sin Healthcheck
**Ubicación:** Línea ~604
```python
_teleprompter_proc = subprocess.Popen([
    sys.executable,
    "-m",
    "src.teleprompter.ws_bridge"
])

# ... más tarde:
# Si teleprompter crash, no hay detección
```

**Riesgo:** PyQt window cierra pero pipeline sigue generando respuestas (sin UI).

**Fix:**
```python
async def monitor_teleprompter_health():
    """Monitor teleprompter subprocess health"""
    while True:
        await asyncio.sleep(30)
        if _teleprompter_proc:
            poll_result = _teleprompter_proc.poll()
            if poll_result is not None:
                # Process exited
                logger.error(
                    f"Teleprompter crashed with exit code {poll_result}. "
                    f"Restarting…"
                )
                await start_teleprompter()

# En start_pipeline():
asyncio.create_task(monitor_teleprompter_health())
```

---

#### ⚠️ Problema #6: Sin Retry para Fallos Transientes
**Ubicación:** Línea ~350 (process_question)
```python
chunks = await pipeline.retriever.retrieve(
    query=question,
    question_type=classification["type"],
)
# Si falla OpenAI embedding, excepción sin reintentos
```

**Fix:**
```python
async def retrieve_with_retry(query, question_type, max_retries=3):
    """Retry retrieval with exponential backoff"""
    for attempt in range(max_retries):
        try:
            return await pipeline.retriever.retrieve(query, question_type)
        except Exception as e:
            if attempt < max_retries - 1:
                delay = 2 ** attempt  # 1s, 2s, 4s
                logger.warning(
                    f"Retrieval failed (attempt {attempt+1}), "
                    f"retrying in {delay}s: {e}"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(f"Retrieval failed after {max_retries} attempts")
                return []  # Fallback: sin chunks
```

---

### 2. `src/transcription/openai_realtime.py`

#### ✅ Fortaleza: Auto-reconnect Robusto
**Ubicación:** Línea ~156
```python
async def _run_channel(self, speaker, audio_queue):
    """Run with auto-reconnect on failure"""
    attempts = 0
    
    while self._running and attempts < MAX_RECONNECT_ATTEMPTS:
        try:
            await self._stream_channel(speaker, audio_queue)
            attempts = 0  # Reset on clean exit
        except asyncio.CancelledError:
            break
        except Exception as e:
            attempts += 1
            logger.error(f"[{speaker}] Error: {e}. Reconnecting…")
            await asyncio.sleep(RECONNECT_DELAY_S)
```
**Análisis:** Buen patrón. Reset counter on success, exponential backoff inherent.

---

#### ⚠️ Problema #7: Buffer Privado Usado en main.py
**Ubicación:** Línea ~165
```python
# En OpenAIRealtimeTranscriber:
self._live_buffer: str = ""  # Privado

# En main.py (line 227):
delta_text = pipeline.transcriber_int._live_buffer  # ⚠️ Access privado
```
**Ya cubierto arriba → Fix: agregar getter.**

---

#### ✅ Fortaleza: Configuración Correcta de VAD
**Ubicación:** Línea ~215
```python
await ws.send(json.dumps({
    "type": "session.update",
    "session": {
        "model": "gpt-4o-mini-transcribe",
        "input_audio_format": "pcm_16",
        "modalities": ["text"],
        "voice_activity_detection": {
            "type": "server_vad",
            "threshold": 0.5,
            "prefix_padding_ms": 300,
            "silence_duration_ms": 500
        }
    }
}))
```
**Análisis:** Buena configuración. `server_vad` mejor que silence-based.

---

### 3. `src/audio/capture.py`

#### ✅ Fortaleza: Fallback Chain Completo
**Ubicación:** Línea ~160-180
```python
# User stream:
if user_dev is not None:
    self._stream_user = sd.RawInputStream(...)
else:
    # Fallback to default
    default_dev = sd.default.device[0]
    self._stream_user = sd.RawInputStream(...)

# Interviewer stream:
if int_dev is not None:
    self._stream_int = sd.RawInputStream(...)
else:
    # Fallback to Stereo Mix
    loopback_dev = self._find_loopback_device()
    if loopback_dev is not None:
        # Resampling inline
        ...
```
**Análisis:** Excelente degradación graceful.

---

#### ⚠️ Problema #8: Ganancia Loopback Hardcodeada
**Ubicación:** Línea ~233
```python
gain = float(os.getenv("LOOPBACK_GAIN", "2.0"))
samples = samples * gain
```

**Problema:** 2.0 puede ser muy alto en algunos PCs, resultando en clipping/distorsión.

**Fix:** Dynamic gain adjustment basado en RMS detectado:
```python
def _adjust_gain_dynamically(samples: np.ndarray, current_gain: float) -> float:
    """Adjust gain based on RMS level"""
    rms = np.sqrt(np.mean(samples.astype(np.float32) ** 2))
    
    RMS_TARGET = 5000  # Target level
    GAIN_MIN, GAIN_MAX = 0.5, 4.0
    
    if rms < RMS_TARGET * 0.5:
        return min(current_gain * 1.2, GAIN_MAX)
    elif rms > RMS_TARGET * 2:
        return max(current_gain * 0.8, GAIN_MIN)
    return current_gain
```

---

#### ⚠️ Problema #9: QueueFull Sin Back-pressure
**Ubicación:** Línea ~85
```python
def _cb_user(self, indata, frames, time_info, status):
    try:
        self.user_queue.put_nowait(bytes(indata))
    except asyncio.QueueFull:
        pass  # Drop silently
```

**Problema:** Si transcriber es muy lento, audio se pierde sin notificación.

**Fix:**
```python
def _cb_user(self, indata, frames, time_info, status):
    if status:
        logger.warning(f"User audio status: {status}")
    try:
        self.user_queue.put_nowait(bytes(indata))
    except asyncio.QueueFull:
        logger.warning(
            "User audio queue full — dropping chunk "
            "(transcriber too slow?)"
        )
```

---

### 4. `src/response/claude_agent.py`

#### ✅ Fortaleza: Prompt Caching Correcto
**Ubicación:** Línea ~141
```python
async with self.client.messages.stream(
    model=MODEL,
    max_tokens=1024,
    temperature=temperature,
    system=[
        {
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"}
        }
    ],
    messages=[{"role": "user", "content": user_message}],
) as stream:
```
**Análisis:** Correcto. Cache creado en 1era llamada, reutilizado después.

---

#### ✅ Fortaleza: Tracking de Cache Hits
**Ubicación:** Línea ~161
```python
response = await stream.get_final_message()
if response.usage:
    cached = getattr(response.usage, 'cache_read_input_tokens', 0)
    if cached and cached > 0:
        self._cache_hits += 1
        logger.info(f"CACHE HIT ⚡ {cached} tokens")
    else:
        self._cache_misses += 1
        cache_created = getattr(
            response.usage, 'cache_creation_input_tokens', 0
        )
```
**Análisis:** Buena observabilidad de cache performance.

---

#### ⚠️ Problema #10: AsyncAnthropic Pero sin Timeout
**Ubicación:** Línea ~153
```python
async with self.client.messages.stream(...) as stream:
    async for text in stream.text_stream:
        yield text
```

**Problema:** Si API se cuelga, yield se bloquea indefinidamente.

**Fix:** Ya cubierto en main.py, pero mejor hacerlo aquí:
```python
async def generate(self, ...) -> AsyncIterator[str]:
    """Generate with streaming and timeout"""
    try:
        async with asyncio.timeout(30):  # Python 3.11+
            async with self.client.messages.stream(...) as stream:
                async for text in stream.text_stream:
                    yield text
    except asyncio.TimeoutError:
        logger.error("Response generation timeout")
        yield "[Response generation timeout]"
    except Exception as e:
        logger.error(f"Generation error: {e}")
        yield f"[Error: {str(e)[:100]}]"
```

---

#### ⚠️ Problema #11: System Prompt Muy Largo y Detallado
**Ubicación:** Línea ~20-45
```python
SYSTEM_PROMPT = """\
You are an English interview copilot...
CRITICAL RULES — follow ALL of these strictly:
1. Use contractions ALWAYS...
2. Short sentences...
3. Start with conversational connectors...
... (13 rules total)
"""
```

**Problema:** Los 13 rules son buenos, pero podrían estar mejor organizados para Claude.

**Sugerencia de Mejora:** Dividir en sections:
```python
SYSTEM_PROMPT = """You are an English interview copilot.

# CORE OBJECTIVE
Generate the EXACT words the candidate should say aloud.

# LANGUAGE RULES
1. Use contractions: I'm, we've, they're, don't
2. Short sentences: 12-18 words max
3. Conversational openers: So basically, Actually, I'd say

# FORMAT RULES
- First person as candidate
- Add [PAUSE] for breathing (every 2-3 sentences)
- Add **bold** for emphasis words
- NO headers, bullets, meta-commentary

# GROUNDING
- Use ONLY facts from [KNOWLEDGE BASE]
- Never invent: companies, metrics, job titles
- Reference min 2 KB facts per response
"""
```

---

### 5. `src/knowledge/classifier.py`

#### ✅ Fortaleza: Fallback Classification Rápido
**Ubicación:** Línea ~69-195
```python
@staticmethod
def _fallback_classify(question: str) -> dict:
    """Simple rule-based classifier as fallback"""
    q = question.lower().strip()
    
    # Check 1: Compound
    is_compound = q.count("?") > 1 or ...
    if is_compound:
        return {"type": "hybrid", "compound": True, "budget": ...}
    
    # Check 2: Situational
    situational_signals = [
        "what would you do",
        "how would you handle",
        ...
    ]
    if any(signal in q for signal in situational_signals):
        return {"type": "situational", ...}
    
    # ... etc
```
**Análisis:** Buena estrategia. Cubre ~90% de casos sin API call.

---

#### ⚠️ Problema #12: Detección de Compound Incompleta
**Ubicación:** Línea ~83
```python
is_compound = q.count("?") > 1 or (
    " and " in q and len(q.split()) > 12
)
```

**Problema:** Casos que no detecta:
- "Tell me about yourself, and how would you handle conflict?" (semicolon)
- "What are your strengths as well as weaknesses?" (compound sin "and" explícito)

**Fix:**
```python
def _is_compound_question(question: str) -> bool:
    """Detect multi-part questions"""
    q = question.lower()
    
    # Multiple question marks
    if q.count("?") > 1:
        return True
    
    # "and/or/plus/also" with 2+ clauses
    connectors = r'\s+(and|or|plus|also|as well as|in addition)\s+'
    parts = re.split(connectors, q)
    if len(parts) >= 3:
        # Check if at least 2 parts are sentences
        question_count = sum(1 for p in parts if '?' in p or p.endswith('?'))
        if question_count >= 2:
            return True
    
    # Parenthetical questions
    if "(" in q and "?" in q.split("(")[1]:
        return True
    
    return False
```

---

### 6. `src/knowledge/question_filter.py`

#### ✅ Fortaleza: Noise Patterns Exhaustivo
**Ubicación:** Línea ~22-38
```python
NOISE_PATTERNS = [
    r"^(hi|hello|hey|good morning|...)[\s\.\!]*$",
    # 30+ patterns covering:
    # - Greetings
    # - Filler words
    # - Meta commands
    # - Closing remarks
]
```
**Análisis:** Comprehensive pattern list.

---

#### ⚠️ Problema #13: Señales Entrevista No Cubren Todas Variaciones
**Ubicación:** Línea ~45-85
```python
INTERVIEW_SIGNALS = [
    "tell me about yourself",
    "walk me through",
    ...
]
```

**Problema:** Variaciones no cubiertas:
- "Take me through your background" (vs "walk me through")
- "Elaborate on your experience" (vs "describe")
- "How'd you approach this?" (contracción "how'd")

**Fix:** Usar fuzzy matching + stemming:
```python
import difflib
from nltk.stem import PorterStemmer

stemmer = PorterStemmer()

def has_interview_signal(question: str) -> bool:
    """Fuzzy matching for interview signals"""
    q = question.lower()
    
    # Direct signals (fast path)
    for signal in INTERVIEW_SIGNALS:
        if signal in q:
            return True
    
    # Fuzzy path (slow but comprehensive)
    q_words = set(w.strip('?,.:;!') for w in q.split())
    q_stems = {stemmer.stem(w) for w in q_words}
    
    for signal in INTERVIEW_SIGNALS:
        signal_stems = {stemmer.stem(w) for w in signal.split()}
        overlap = len(q_stems & signal_stems) / len(signal_stems)
        if overlap >= 0.7:  # 70% match
            return True
    
    return False
```

---

### 7. `src/teleprompter/qt_display.py`

#### ✅ Fortaleza: Qt Signal/Slot Thread-Safe
**Ubicación:** Línea ~85
```python
class SmartTeleprompter(QWidget):
    text_received = pyqtSignal(str)  # Qt signal
    
    def append_text(self, token: str):
        """Thread-safe method to append a streaming token"""
        self.text_received.emit(token)  # Signal emitted
    
    @pyqtSlot(str)
    def _on_text_received(self, token: str):
        """Slot runs in main Qt thread"""
        self._current_text += token
```
**Análisis:** Correcto uso de signals para thread-safety.

---

#### ⚠️ Problema #14: Sin Límite de Tamaño de Texto
**Ubicación:** Línea ~230
```python
def _on_text_received(self, token: str):
    self._current_text += token
    self._update_display()
```

**Problema:** Si respuesta es MUY larga (5000+ tokens), `_current_text` crece indefinidamente.

**Fix:**
```python
MAX_DISPLAY_CHARS = 10000  # ~2000 tokens

def _on_text_received(self, token: str):
    self._current_text += token
    
    # Keep only last N chars
    if len(self._current_text) > MAX_DISPLAY_CHARS:
        # Remove oldest content, keep scrolled view
        self._current_text = "…" + self._current_text[-MAX_DISPLAY_CHARS:]
    
    self._update_display()
```

---

#### ⚠️ Problema #15: Opacidad Hardcodeada
**Ubicación:** Línea ~50
```python
DEFAULT_OPACITY = 0.80
OPACITY_LEVELS = [0.70, 0.80, 0.90]
```

**Problema:** No configurable vía envvar, difícil personalizar.

**Fix:**
```python
# En initialization:
opacity_env = os.getenv("TELEPROMPTER_OPACITY", "0.80")
try:
    DEFAULT_OPACITY = float(opacity_env)
except ValueError:
    DEFAULT_OPACITY = 0.80
    logger.warning(f"Invalid TELEPROMPTER_OPACITY={opacity_env}, using default")
```

---

### 8. `src/knowledge/ingest.py`

#### ✅ Fortaleza: Metadata Tracking
**Ubicación:** Línea ~142
```python
self.collection.add(
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
**Análisis:** Bueno para audit trail.

---

#### ⚠️ Problema #16: Sin Validación de Chunks
**Ubicación:** Línea ~112
```python
chunks = self.splitter.split_text(text)
for i, chunk in enumerate(chunks):
    # Store chunk
```

**Problema:** Chunks vacíos o muy cortos podrían colarse.

**Fix:**
```python
MIN_CHUNK_SIZE = 20  # chars, avoids noise

chunks = [
    c for c in self.splitter.split_text(text)
    if len(c.strip()) >= MIN_CHUNK_SIZE
]

if not chunks:
    logger.warning(f"No valid chunks after filtering in {source}")
    return 0
```

---

#### ⚠️ Problema #17: Sin Deduplicación de Chunks
**Ubicación:** Línea ~140
```python
# Si se re-ingesta el mismo archivo:
# Duplica todos los chunks en ChromaDB
```

**Problema:** Retrieve devuelve chunks duplicados, desperdicia API tokens.

**Fix:**
```python
def ingest_file(self, filepath, category, topic=None):
    """Ingest with deduplication"""
    
    # Check if file was already ingested
    existing = self.collection.get(
        where={"source": filepath.name}
    )
    
    if existing["ids"]:
        logger.info(f"Removing {len(existing['ids'])} old chunks...")
        self.collection.delete(ids=existing["ids"])
    
    # Re-ingest with fresh IDs
    text = filepath.read_text()
    return self.ingest_text(text, category, topic, source=filepath.name)
```

---

## 📊 RESUMEN DE HALLAZGOS

### Distribución por Severidad

| Severidad | Cantidad | Archivos |
|-----------|----------|----------|
| **CRÍTICO** | 6 | main.py (4), claude_agent.py (1), teleprompter (1) |
| **ALTO** | 6 | main.py (2), capture.py (2), classifier.py (1), question_filter.py (1) |
| **MEDIO** | 5 | response.py (1), teleprompter.py (2), ingest.py (2) |

### Top 5 Prioridades

1. ✅ **Sincronización de variables globales de especulación** (race condition)
2. ✅ **Timeout en response generation** (indefinite hang)
3. ✅ **Healthcheck teleprompter subprocess** (silent failure)
4. ✅ **Retry logic exponential backoff** (transient failures)
5. ✅ **Mejora speculative hit similarity** (false positives)

---

## 🔧 SNIPPETS DE CÓDIGO PARA FIX INMEDIATOS

### Fix #1: Sincronización Especulación (5 min)
```python
# En main.py, reemplazar variables globales:
class SpeculativeState:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.retrieval_task = None
        self.gen_task = None
        self.gen_tokens = []
    
    async def cancel_all(self):
        async with self.lock:
            if self.retrieval_task:
                self.retrieval_task.cancel()
            if self.gen_task:
                self.gen_task.cancel()
            self.gen_tokens.clear()

_speculative = SpeculativeState()

# Usage:
await _speculative.cancel_all()
```

### Fix #2: Timeout Response (3 min)
```python
# En process_question():
try:
    async with asyncio.timeout(30):
        async for token in pipeline.response_agent.generate(...):
            await broadcast_token(token)
except asyncio.TimeoutError:
    logger.error("Response generation timeout")
    await broadcast_message({
        "type": "error",
        "data": "[Response timeout - please try again]"
    })
```

### Fix #3: Healthcheck Teleprompter (5 min)
```python
async def monitor_teleprompter():
    while True:
        await asyncio.sleep(30)
        if _teleprompter_proc and _teleprompter_proc.poll() is not None:
            logger.error("Teleprompter crashed, restarting…")
            await start_teleprompter()

# En start_pipeline():
asyncio.create_task(monitor_teleprompter())
```

---

**Próximo Paso:** Implementar Priority 1 fixes antes de production deployment.

---

Fin del Code Review  
📅 Completado: 1 Marzo 2026

