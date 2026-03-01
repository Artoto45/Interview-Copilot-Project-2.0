# 🎯 ROADMAP PROFESIONAL EJECUTABLE
## Interview Copilot v2.0 — Mejora de Código Guiado por IA

**Fecha de Creación:** 1 Marzo 2026  
**Sistema Ejecutor:** Open Agent Manager (Antigravity/Google)  
**Modelo de IA:** Claude Opus 4.6 with Extended Thinking  
**Estimado Total:** 8.5 horas de implementación  
**Prioridad:** Production Stability + Latency Improvement  

---

## 📊 RESUMEN EJECUTIVO

Este roadmap está diseñado para ser **ejecutado automáticamente por Claude Opus 4.6 (Thinking)** a través del Open Agent Manager de Antigravity. Define tareas atómicas, criterios de éxito, fallbacks inteligentes y validación automática.

### Objetivos Principales
1. ✅ **Estabilidad:** Eliminar race conditions, timeouts, crashes
2. ✅ **Rendimiento:** Mejorar P95 latencia de 5-7s → 4-5s
3. ✅ **Calidad:** Reducir falsos positivos en detección de preguntas
4. ✅ **Observabilidad:** Instrumentación para monitoreo

### Métricas de Éxito Global
| Métrica | Baseline | Target | Hito |
|---------|----------|--------|------|
| **P95 Latency** | 5-7s | <4s | Fase 2 |
| **Cache Hit Rate** | 60-70% | >80% | Fase 3 |
| **Test Coverage** | ~60% | >85% | Fase 3 |
| **Uptime** | ~95% | >99% | Fase 4 |
| **Hallucination Rate** | 2-3% | <1% | Fase 3 |

---

## 🚀 FASE 1: ESTABILIDAD (Sprint 1-2, ~2 horas)

### Objetivo
Eliminar todos los problemas **CRÍTICOS** que causan crashes, hangs, y failures silenciosos.

### Sprint 1.1: Race Conditions & Timeouts (90 minutos)

#### Task 1.1.1: Sincronización de Variables Especulativas
**Criticidad:** 🔴 CRÍTICO  
**Impacto:** Evita crashes aleatorios en process_question  
**Archivos:** `main.py`

##### Especificación de Tarea (para Claude Opus 4.6)
```
PROBLEMA ACTUAL:
  _speculative_gen_task: asyncio.Task | None = None
  _speculative_gen_tokens: list[str] = []
  
Race condition: múltiples on_speech_event() calls pueden modificar
simultáneamente _speculative_gen_tokens mientras se accede desde
process_question().

SOLUCIÓN REQUERIDA:
  1. Crear clase SpeculativeState con asyncio.Lock()
  2. Métodos thread-safe: cancel_all(), get_tokens(), add_token()
  3. Reemplazar todos accesos directos a variables globales
  4. Agregar logging de transiciones de estado
  
CRITERIOS DE ÉXITO:
  ✓ No warnings de "asyncio.Lock() used without 'async with'"
  ✓ Todos los accesos a _speculative_* pasan por SpeculativeState
  ✓ pytest test_main.py::test_speculative_race_condition (si existe)
  ✓ 5+ corridas de main.py sin crashes
```

##### Implementación (Claude debe hacer esto)
```python
# Ubicación: main.py, línea ~110 (después imports)

class SpeculativeState:
    """Thread-safe state management for speculative retrieval/generation"""
    
    def __init__(self):
        self.lock = asyncio.Lock()
        self.retrieval_task: Optional[asyncio.Task] = None
        self.retrieval_query: str = ""
        self.gen_task: Optional[asyncio.Task] = None
        self.gen_tokens: list[str] = []
    
    async def cancel_all(self):
        """Cancel all pending speculative tasks"""
        async with self.lock:
            if self.retrieval_task:
                logger.info("Cancelling speculative retrieval")
                self.retrieval_task.cancel()
            if self.gen_task:
                logger.info("Cancelling speculative generation")
                self.gen_task.cancel()
            self.gen_tokens.clear()
    
    async def set_retrieval_task(self, task, query):
        """Set pending retrieval task"""
        async with self.lock:
            self.retrieval_task = task
            self.retrieval_query = query
    
    async def get_tokens(self):
        """Get accumulated tokens (read-only)"""
        async with self.lock:
            return self.gen_tokens.copy()
    
    async def clear_tokens(self):
        """Clear accumulated tokens"""
        async with self.lock:
            self.gen_tokens.clear()

# Reemplazar variables globales
_speculative = SpeculativeState()

# ... resto del código ...
# Reemplazar:
# _speculative_retrieval_task.cancel() 
# Con:
# await _speculative.cancel_all()
```

##### Testing (Claude debe validar)
```bash
# Test 1: Sin race conditions en múltiples on_speech_event
pytest -xvs tests/ -k "speculative" 2>&1 | grep -i "error\|fail"

# Test 2: Main pipeline no se congela
timeout 60 python main.py &
sleep 30
kill %1 2>/dev/null
echo $? == 0  # Exit cleanly

# Test 3: Logs muestran transiciones de estado
python main.py 2>&1 | grep -i "speculative" | head -5
```

---

#### Task 1.1.2: Timeout en Response Generation
**Criticidad:** 🔴 CRÍTICO  
**Impacto:** Evita UI freeze indefinido si Claude API se cuelga  
**Archivos:** `main.py`, `src/response/claude_agent.py`

##### Especificación
```
PROBLEMA:
  async for token in pipeline.response_agent.generate(...):
      await broadcast_token(token)
  
Si API se cuelga, teleprompter esperaría indefinidamente.

SOLUCIÓN:
  1. Envolver con asyncio.timeout(30s) en main.py
  2. Catch TimeoutError → enviar mensaje de error al teleprompter
  3. Timeout fallback: generar respuesta básica sin KB
  
CRITERIOS:
  ✓ Response generation timeouts después 30s máximo
  ✓ Teleprompter recibe mensaje "[Response timeout]"
  ✓ No exceptions no-handled en logs
  ✓ pytest test_latency.py verifica timeout behavior
```

##### Implementación
```python
# En main.py, en process_question() (~line 365)

async def generate_with_timeout(question, kb_chunks, q_type):
    """Generate response with 30s timeout"""
    try:
        async with asyncio.timeout(30):  # Python 3.11+
            tokens = []
            async for token in pipeline.response_agent.generate(
                question=question,
                kb_chunks=kb_chunks,
                question_type=q_type,
            ):
                tokens.append(token)
                await broadcast_token(token)
            return "".join(tokens)
    except asyncio.TimeoutError:
        logger.error(f"Response generation timeout for: {question[:50]}")
        error_msg = "[Response generation timeout - please try again]"
        await broadcast_message({
            "type": "error",
            "data": error_msg
        })
        return error_msg
    except Exception as e:
        logger.error(f"Response generation error: {e}", exc_info=True)
        await broadcast_message({
            "type": "error",
            "data": f"[Error: {str(e)[:50]}]"
        })
        return ""

# Uso:
response_text = await generate_with_timeout(
    question, kb_chunks, classification["type"]
)
```

##### Testing
```bash
# Test 1: Timeout accionado después 30s
timeout 35 python -c "
import asyncio
async def test_timeout():
    try:
        async with asyncio.timeout(30):
            await asyncio.sleep(40)
    except asyncio.TimeoutError:
        print('PASS: timeout triggered')

asyncio.run(test_timeout())
"

# Test 2: Message enviado al teleprompter
grep -i "timeout\|error" logs/interview*.md | head -3
```

---

#### Task 1.1.3: Acceso a Atributo Privado
**Criticidad:** 🔴 CRÍTICO  
**Impacto:** Prevenir breaking changes futuros  
**Archivos:** `src/transcription/openai_realtime.py`, `main.py`

##### Especificación
```
PROBLEMA:
  # En main.py línea 227
  delta_text = pipeline.transcriber_int._live_buffer  ← privado (__)
  
Viola encapsulation, brittle si se refactoriza OpenAIRealtimeTranscriber.

SOLUCIÓN:
  1. Agregar método público get_live_buffer() en OpenAIRealtimeTranscriber
  2. Reemplazar acceso privado con llamada pública
  3. Deprecation warning si alguien usa _live_buffer directamente
  
CRITERIOS:
  ✓ Método get_live_buffer() existe y es público
  ✓ main.py usa get_live_buffer() en línea 227
  ✓ No accesos directos a _live_buffer en main.py
  ✓ pylint/mypy sin warnings sobre private access
```

##### Implementación
```python
# En src/transcription/openai_realtime.py

class OpenAIRealtimeTranscriber:
    # ... existing code ...
    
    def get_live_buffer(self) -> str:
        """Get current delta text (live transcript buffer)
        
        Returns the most recent partial transcription text.
        Safe to call from any thread.
        """
        return self._live_buffer
    
    @property
    def live_buffer_deprecated(self):
        """Deprecated: Use get_live_buffer() instead"""
        logger.warning(
            "live_buffer property is deprecated, use get_live_buffer()"
        )
        return self._live_buffer

# En main.py (línea 227)
# Cambiar:
#   delta_text = pipeline.transcriber_int._live_buffer
# Por:
#   delta_text = pipeline.transcriber_int.get_live_buffer()
```

##### Testing
```bash
# Test 1: Método existe y es público
python -c "
from src.transcription.openai_realtime import OpenAIRealtimeTranscriber
t = OpenAIRealtimeTranscriber(on_transcript=lambda s,t: None)
assert hasattr(t, 'get_live_buffer'), 'Method missing'
assert callable(t.get_live_buffer), 'Not callable'
print('PASS: get_live_buffer() exists and is public')
"

# Test 2: main.py no usa _live_buffer directamente
grep "_live_buffer" main.py || echo "PASS: no direct access"
```

---

### Sprint 1.2: Subprocess Health & Retry Logic (30 minutos)

#### Task 1.2.1: Teleprompter Healthcheck
**Criticidad:** 🔴 CRÍTICO  
**Impacto:** Detectar y reiniciar teleprompter si crashea  
**Archivos:** `main.py`

##### Especificación
```
PROBLEMA:
  Si teleprompter (PyQt5) crash, pipeline sigue generando respuestas
  sin UI (usuario no ve nada).

SOLUCIÓN:
  1. Crear monitor_teleprompter_health() que verifica cada 30s
  2. Si proc.poll() != None (exited), log error + reiniciar
  3. Máximo 3 reintentos antes de dar up
  4. Notify usuario vía teleprompter bridge
  
CRITERIOS:
  ✓ Teleprompter crash detectado en <35s
  ✓ Reinicio automático sucede
  ✓ Máximo 3 intentos respetado
  ✓ Logs muestran transiciones de salud
```

##### Implementación
```python
# En main.py

async def monitor_teleprompter_health():
    """Monitor teleprompter subprocess health"""
    restart_attempts = 0
    MAX_RESTARTS = 3
    
    while True:
        await asyncio.sleep(30)  # Check every 30s
        
        if not _teleprompter_proc:
            continue
        
        poll_result = _teleprompter_proc.poll()
        if poll_result is not None:
            # Process has exited
            logger.error(
                f"Teleprompter process exited with code {poll_result}"
            )
            
            if restart_attempts < MAX_RESTARTS:
                logger.info(
                    f"Attempting restart {restart_attempts + 1}/{MAX_RESTARTS}…"
                )
                restart_attempts += 1
                await start_teleprompter()
            else:
                logger.critical(
                    "Max teleprompter restart attempts reached. "
                    "UI will be unavailable."
                )
                break

# En start_pipeline():
# Agregar:
asyncio.create_task(monitor_teleprompter_health())
```

##### Testing
```bash
# Test 1: Monitor se ejecuta
timeout 65 python main.py 2>&1 | grep -i "monitor\|teleprompter" | head -3

# Test 2: Simular crash (kill -9 process)
python main.py &
PID=$!
sleep 5
kill -9 $PID 2>/dev/null
wait $PID 2>/dev/null
echo "Monitored and should attempt restart"
```

---

#### Task 1.2.2: Retry Logic con Exponential Backoff
**Criticidad:** 🔴 CRÍTICO  
**Impacto:** Recuperarse de fallos transientes de API  
**Archivos:** `main.py`

##### Especificación
```
PROBLEMA:
  Si OpenAI embedding o Claude API falla (transient error),
  process_question() crashea sin reintentos.

SOLUCIÓN:
  1. Crear retry_with_backoff() helper
  2. Exponential backoff: 1s, 2s, 4s (max 3 intentos)
  3. Log each attempt
  4. Fallback: respuesta vacía si todos fallan
  
CRITERIOS:
  ✓ retrieval() retried 3x antes de fallar
  ✓ Logs muestran cada reintento
  ✓ Backoff delays: 1s, 2s, 4s (validar con sleep)
  ✓ pytest tests/test_latency.py passes
```

##### Implementación
```python
# En main.py

async def retry_with_backoff(
    func,
    *args,
    max_retries: int = 3,
    base_delay: float = 1.0,
    **kwargs
):
    """Retry async function with exponential backoff
    
    Args:
        func: Async callable
        max_retries: Max attempts (default 3)
        base_delay: Initial delay in seconds (default 1s)
    
    Returns:
        Result of func or None if all retries exhausted
    """
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # 1s, 2s, 4s
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: {e}. "
                    f"Retrying in {delay}s…"
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"All {max_retries} attempts exhausted. "
                    f"Last error: {e}"
                )
    
    return None

# Uso en process_question():
chunks = await retry_with_backoff(
    pipeline.retriever.retrieve,
    question=question,
    question_type=classification["type"],
    max_retries=3
)

if chunks is None:
    logger.error(f"Could not retrieve KB for: {question[:50]}")
    chunks = []  # Fallback to empty
```

##### Testing
```bash
# Test 1: Retry logic funciona
python -c "
import asyncio
from src.main import retry_with_backoff

async def test():
    attempt = [0]
    async def failing_func():
        attempt[0] += 1
        if attempt[0] < 3:
            raise ValueError('Transient error')
        return 'success'
    
    result = await retry_with_backoff(failing_func, max_retries=3)
    assert result == 'success', f'Got {result}'
    print(f'PASS: Succeeded after {attempt[0]} attempts')

asyncio.run(test())
"

# Test 2: Logs muestran reintentos
timeout 10 python main.py 2>&1 | grep -i "retry\|attempt" || echo "No retries triggered"
```

---

### Sprint 1 Summary
| Task | Time | Status | Owner |
|------|------|--------|-------|
| 1.1.1 Syncronización especulativa | 30 min | 📋 Spec | Claude Opus |
| 1.1.2 Timeout response | 20 min | 📋 Spec | Claude Opus |
| 1.1.3 Acceso privado | 15 min | 📋 Spec | Claude Opus |
| 1.2.1 Teleprompter healthcheck | 15 min | 📋 Spec | Claude Opus |
| 1.2.2 Retry exponential | 15 min | 📋 Spec | Claude Opus |
| **TOTAL** | **95 min** | | |

**Validación Global (Claude debe hacer):**
```bash
# 1. Todos los tests pasan
pytest tests/ -v --tb=short 2>&1 | tail -20

# 2. No warnings de asyncio
python main.py 2>&1 | grep -i "asyncio.*warning" && echo "FAIL" || echo "PASS"

# 3. 5 corridas sin crashes
for i in {1..5}; do
  timeout 5 python main.py >/dev/null 2>&1 && echo "Run $i: PASS" || echo "Run $i: FAIL"
done

# 4. Code quality
pylint main.py --disable=all --enable=E 2>&1 | grep -c "^Your code"
```

**Salida Esperada:**
```
✓ Phase 1 Complete - Todos los problemas críticos resueltos
✓ 0 asyncio warnings
✓ 5/5 test runs exitosos
✓ Code quality: E-level violations = 0
```

---

## ⚡ FASE 2: RENDIMIENTO (Sprint 3-4, ~2 horas)

### Objetivo
Mejorar latencia (P95 5-7s → 4-5s) y precisión de detección de preguntas.

### Sprint 2.1: Speculative Hit Intelligence (60 minutos)

#### Task 2.1.1: Semantic Similarity para Especulative Hit
**Criticidad:** 🟠 ALTO  
**Impacto:** Reducir false positives en speculative generation  
**Archivos:** `main.py`

##### Especificación
```
PROBLEMA:
  Threshold 65% word overlap es bajo, causa respuestas incorrectas.
  
  Ejemplo:
    Delta: "Tell me about a project you led" (70% overlap)
    Final: "Tell me about your failures" (60% overlap)
    Resultado: Se envía respuesta sobre PROJECT, pero pregunta es sobre FAILURES
    
SOLUCIÓN:
  1. Usar embeddings (OpenAI text-embedding-3-small)
  2. Comparar similaridad semántica de delta vs final
  3. Threshold: 0.80 (semántico) vs 0.65 (léxico)
  4. Loguear decisiones para auditing
  
CRITERIOS:
  ✓ Semantic similarity > 80% para aceptar speculative
  ✓ Logs muestran score de similaridad
  ✓ Falsos positivos reducidos (validar manualmente)
  ✓ Speculative hit rate se mantiene >50%
```

##### Implementación
```python
# En main.py

async def is_similar_enough_semantic(delta: str, final: str) -> tuple[bool, float]:
    """Check semantic similarity between delta and final transcript
    
    Uses embeddings for context-aware comparison.
    
    Returns:
        (is_similar: bool, similarity_score: float)
    """
    if not delta or not final:
        return False, 0.0
    
    try:
        embeddings = await asyncio.to_thread(
            lambda: client.embeddings.create(
                model="text-embedding-3-small",
                input=[delta, final]
            )
        )
        
        import numpy as np
        delta_emb = np.array(embeddings.data[0].embedding)
        final_emb = np.array(embeddings.data[1].embedding)
        
        # Cosine similarity
        similarity = np.dot(delta_emb, final_emb) / (
            np.linalg.norm(delta_emb) * np.linalg.norm(final_emb)
        )
        
        is_similar = similarity > 0.80
        logger.info(f"Semantic similarity: {similarity:.3f} → {'ACCEPT' if is_similar else 'REJECT'}")
        
        return is_similar, float(similarity)
    except Exception as e:
        logger.warning(f"Semantic similarity check failed: {e}")
        return False, 0.0

# En process_question(), reemplazar:
if _speculative_gen_tokens:
    is_similar, score = await is_similar_enough_semantic(delta_text, final_transcript)
    if is_similar:
        logger.info(f"Speculative generation HIT (score={score:.3f})")
        # ... flush tokens ...
```

##### Testing
```bash
# Test 1: Semantic similarity funciona
python -c "
import asyncio
import numpy as np

async def test():
    from openai import OpenAI
    client = OpenAI()
    
    delta = 'Tell me about a project'
    final = 'Tell me about your project experience'
    
    embeddings = client.embeddings.create(
        model='text-embedding-3-small',
        input=[delta, final]
    )
    
    e1 = np.array(embeddings.data[0].embedding)
    e2 = np.array(embeddings.data[1].embedding)
    sim = np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2))
    
    assert sim > 0.85, f'Similar queries should have >0.85, got {sim}'
    print(f'PASS: Semantic similarity = {sim:.3f}')

asyncio.run(test())
"
```

---

### Sprint 2.2: Question Detection Improvements (60 minutos)

#### Task 2.2.1: Detección Mejorada de Compound Questions
**Criticidad:** 🟠 ALTO  
**Impacto:** Asignar presupuesto correcto para preguntas complejas  
**Archivos:** `src/knowledge/classifier.py`

##### Especificación
```
PROBLEMA:
  _fallback_classify() no detecta compound questions en casos:
    - Semicolons: "Tell me about yourself; how would you handle X?"
    - "as well as": "Strengths as well as weaknesses?"
    - Parenthetical: "Your background (and why here)?"

SOLUCIÓN:
  1. Mejorar detección de compound con regex
  2. Usar stemming para detectar verbos diferentes
  3. Aumentar budget si es compound
  4. Log decision para auditing
  
CRITERIOS:
  ✓ >95% de compound questions detectadas
  ✓ Presupuestos asignados correctamente
  ✓ pytest test_question_filter.py::test_compound passes
```

##### Implementación
```python
# En src/knowledge/classifier.py

def _is_compound_question(question: str) -> bool:
    """Detect multi-part questions with improved logic"""
    q = question.lower().strip()
    
    # 1. Multiple question marks
    if q.count("?") > 1:
        return True
    
    # 2. Connectors with multiple clauses
    connectors = r'\s+(and|or|plus|also|as well as|in addition|furthermore|additionally)\s+'
    parts = re.split(connectors, q)
    
    if len(parts) >= 3:
        # Check if at least 2 parts contain question-like content
        question_count = sum(
            1 for p in parts 
            if '?' in p or p.strip().endswith(('?', 'do', 'does', 'did'))
        )
        if question_count >= 2:
            return True
    
    # 3. Parenthetical questions
    if "(" in q and "?" in q.split("(")[1]:
        return True
    
    # 4. Semicolon separation
    if ";" in q:
        parts = q.split(";")
        question_count = sum(1 for p in parts if "?" in p)
        if question_count >= 2:
            return True
    
    return False

# Actualizar _fallback_classify():
# cambiar:
#   is_compound = q.count("?") > 1 or ...
# con:
#   is_compound = _is_compound_question(q)
```

##### Testing
```bash
# Test casos conocidos de compound
python -c "
from src.knowledge.classifier import QuestionClassifier

test_cases = [
    ('Tell me about yourself; how would you handle conflict?', True),
    ('Strengths as well as weaknesses?', True),
    ('Your background (and why here)?', True),
    ('Simple question?', False),
]

qc = QuestionClassifier()
for q, expected in test_cases:
    result = qc._is_compound_question(q)
    status = '✓' if result == expected else '✗'
    print(f'{status} {q[:50]} → {result} (expected {expected})')
"
```

---

#### Task 2.2.2: Interview Signals con Fuzzy Matching
**Criticidad:** 🟠 ALTO  
**Impacto:** Detectar más variaciones de preguntas de entrevista  
**Archivos:** `src/knowledge/question_filter.py`

##### Especificación
```
PROBLEMA:
  INTERVIEW_SIGNALS lista es exhaustiva pero no cubre variaciones:
    - "Take me through X" (vs "Walk me through")
    - "Elaborate on X" (vs "Describe")
    - "How'd you approach" (contracción "how'd")

SOLUCIÓN:
  1. Implementar fuzzy matching (difflib)
  2. Stemming para normalización (NLTK PorterStemmer)
  3. Threshold: 70% token overlap en stems
  4. Mantener fast path (direct matching) para performance
  
CRITERIOS:
  ✓ >95% de preguntas reales pasan filter
  ✓ <5% false positives (ruido pasa)
  ✓ Latencia del filter <10ms (usar fast path)
  ✓ pytest test_question_filter.py passes
```

##### Implementación
```python
# En src/knowledge/question_filter.py

from nltk.stem import PorterStemmer
import difflib

_stemmer = PorterStemmer()

def _normalize_tokens(text: str) -> set[str]:
    """Normalize text to stemmed tokens"""
    words = text.lower().split()
    return {_stemmer.stem(w.strip('?,.:;!')) for w in words if w}

def has_interview_signal_fuzzy(question: str, threshold: float = 0.70) -> bool:
    """Check for interview signals using fuzzy matching
    
    Fast path: direct string matching (O(1))
    Slow path: fuzzy matching with stemming (O(n))
    """
    q = question.lower()
    
    # Fast path: direct signals
    for signal in INTERVIEW_SIGNALS:
        if signal in q:
            return True
    
    # Slow path: fuzzy matching
    q_tokens = _normalize_tokens(question)
    if not q_tokens:
        return False
    
    for signal in INTERVIEW_SIGNALS:
        signal_tokens = _normalize_tokens(signal)
        if not signal_tokens:
            continue
        
        # Token overlap ratio
        overlap = len(q_tokens & signal_tokens) / len(signal_tokens)
        if overlap >= threshold:
            logger.debug(f"Fuzzy match '{signal}' (overlap={overlap:.2f})")
            return True
    
    return False

# En is_interview_question():
# Reemplazar:
#   if any(signal in q for signal in INTERVIEW_SIGNALS):
# Con:
#   if has_interview_signal_fuzzy(question):
```

##### Testing
```bash
# Test fuzzy matching
python -c "
from src.knowledge.question_filter import has_interview_signal_fuzzy

test_cases = [
    ('Take me through your background', True),  # Fuzzy: walk→take
    ('Elaborate on your experience', True),      # Fuzzy: describe→elaborate
    ('How would you approach this?', True),      # Direct match
    ('Can you explain the concept?', True),      # Fuzzy: explain
    ('Hi there', False),                         # Noise
]

for q, expected in test_cases:
    result = has_interview_signal_fuzzy(q)
    status = '✓' if result == expected else '✗'
    print(f'{status} {q} → {result}')
"
```

---

### Sprint 2 Summary
| Task | Time | Status |
|------|------|--------|
| 2.1.1 Semantic similarity | 60 min | 📋 Spec |
| 2.2.1 Compound detection | 30 min | 📋 Spec |
| 2.2.2 Fuzzy matching | 30 min | 📋 Spec |
| **TOTAL** | **120 min** | |

---

## 🏆 FASE 3: CALIDAD (Sprint 5-6, ~2 horas)

### Objetivo
Mejorar calidad KB, cache hit rate, y hallucination detection.

### Sprint 3.1: Knowledge Base Quality (60 minutos)

#### Task 3.1.1: Chunk Validation & Deduplication
**Criticidad:** 🟡 MEDIO  
**Impacto:** Reducir chunks basura y respuestas duplicadas  
**Archivos:** `src/knowledge/ingest.py`

##### Especificación
```
PROBLEMA:
  1. Re-ingest de archivos = duplicación de chunks en ChromaDB
  2. Chunks muy cortos (<20 chars) = ruido en retrieval
  3. Sin deduplicación = retrieve devuelve chunks duplicados

SOLUCIÓN:
  1. Validación: rechazar chunks <20 chars
  2. Deduplicación: checkear si file ya ingested
  3. Delete old chunks antes de re-ingest
  4. Hash-based deduplicación de chunks exactos
  
CRITERIOS:
  ✓ Chunks <20 chars rechazados
  ✓ Re-ingest no crea duplicatas
  ✓ ChromaDB no tiene IDs duplicados
  ✓ pytest test_knowledge.py::test_ingest passes
```

##### Implementación
```python
# En src/knowledge/ingest.py

MIN_CHUNK_SIZE = 20  # characters

def ingest_file(self, filepath: Path, category: str, topic: Optional[str] = None) -> int:
    """Ingest single file with deduplication"""
    
    if not filepath.exists():
        raise FileNotFoundError(f"File not found: {filepath}")
    
    text = filepath.read_text(encoding="utf-8")
    if not text.strip():
        logger.warning(f"Empty file skipped: {filepath}")
        return 0
    
    # Remove old chunks from this file
    existing = self.collection.get(
        where={"source": {"$eq": filepath.name}}
    )
    
    if existing and existing["ids"]:
        logger.info(f"Removing {len(existing['ids'])} old chunks for {filepath.name}")
        self.collection.delete(ids=existing["ids"])
    
    # Auto-derive topic from filename
    if topic is None:
        topic = filepath.stem.replace("_", " ").replace("-", " ")
    
    return self.ingest_text(
        text=text,
        category=category,
        topic=topic,
        source=filepath.name,
    )

def ingest_text(self, text: str, category: str, topic: str, source: str = "manual") -> int:
    """Ingest with validation"""
    
    # Split into chunks
    chunks = self.splitter.split_text(text)
    
    # Validate: reject tiny chunks
    valid_chunks = [
        c for c in chunks
        if len(c.strip()) >= MIN_CHUNK_SIZE
    ]
    
    if not valid_chunks:
        logger.warning(f"No valid chunks after filtering in {source}")
        return 0
    
    logger.info(
        f"Ingesting {len(valid_chunks)}/{len(chunks)} chunks "
        f"(removed {len(chunks) - len(valid_chunks)} too small)"
    )
    
    # Generate embeddings
    try:
        embeddings = self.openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=valid_chunks
        )
    except Exception as e:
        logger.error(f"Embedding failed: {e}")
        return 0
    
    # Store in ChromaDB
    ids = [f"{source}_{i}" for i in range(len(valid_chunks))]
    metadatas = [{
        "category": category,
        "topic": topic,
        "source": source,
        "chunk_size": len(c)
    } for c in valid_chunks]
    
    self.collection.add(
        ids=ids,
        embeddings=[e.embedding for e in embeddings.data],
        documents=valid_chunks,
        metadatas=metadatas
    )
    
    return len(valid_chunks)
```

##### Testing
```bash
# Test 1: Chunks <20 chars rechazados
python -c "
from src.knowledge.ingest import KnowledgeIngestor
ingestor = KnowledgeIngestor()

# Text with tiny chunk
text = 'Good background. Very short. Full description here with lots of content about experience.'
result = ingestor.ingest_text(text, 'personal', 'test', 'test.txt')

# Should skip 'Very short.' (11 chars)
assert result <= 2, f'Expected <=2 chunks, got {result}'
print('PASS: Tiny chunks rejected')
"

# Test 2: Deduplicación
python -c "
from src.knowledge.ingest import KnowledgeIngestor
from pathlib import Path

ingestor = KnowledgeIngestor()

# Create test file
test_file = Path('/tmp/test_kb.txt')
test_file.write_text('This is test content about engineering.')

# Ingest twice
result1 = ingestor.ingest_file(test_file, 'personal')
result2 = ingestor.ingest_file(test_file, 'personal')

# Should have same count (deduped)
# Collection.get() doesn't have duplicate IDs
count = ingestor.collection.count()
assert count == result1, f'Duplicates detected: {count} vs {result1}'
print(f'PASS: Deduplication works ({count} chunks, no duplicates)')
"
```

---

### Sprint 3.2: Cache & Response Quality (60 minutos)

#### Task 3.2.1: Prompt Caching Audit & Optimization
**Criticidad:** 🟡 MEDIO  
**Impacto:** Mejorar cache hit rate >80%  
**Archivos:** `src/response/claude_agent.py`

##### Especificación
```
PROBLEMA:
  Cache hit rate ~60-70%, target >80%.
  
  Causas:
  1. System prompt puede variar ligeramente
  2. KB chunks diferentes → cache miss
  3. Warmup incorrecto
  
SOLUCIÓN:
  1. Normalizar system prompt (no timestamps, etc)
  2. Mejorar warmup con full prompt cache
  3. Logging detallado de cache behavior
  4. Métricas: track hits vs misses por tipo de pregunta
  
CRITERIOS:
  ✓ Cache hit rate > 75% después 3 preguntas
  ✓ Warmup usa mismo system prompt que production
  ✓ Logs muestran cache_read_input_tokens
  ✓ pytest test_response.py::test_cache_hit passes
```

##### Implementación
```python
# En src/response/claude_agent.py

class ResponseAgent:
    def __init__(self, api_key: Optional[str] = None):
        # ... existing ...
        self._cache_stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "by_type": {}  # {"personal": {"hits": 5, "misses": 2}, ...}
        }
    
    async def get_cache_stats(self) -> dict:
        """Get cache hit statistics"""
        return {
            "total_calls": self._cache_stats["total_calls"],
            "hit_rate": (
                self._cache_stats["cache_hits"] / 
                max(1, self._cache_stats["total_calls"])
            ),
            "by_type": self._cache_stats["by_type"]
        }
    
    async def warmup(self):
        """Pre-warm API + prime prompt cache"""
        if self._warmed_up:
            return
        
        try:
            logger.info("Warming up Claude API + priming prompt cache…")
            
            # Use EXACT same system prompt as production
            # No timestamps, no variations
            response = await self.client.messages.create(
                model=MODEL,
                max_tokens=5,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,  # Exactly as used in generate()
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": "Hi"}],
            )
            
            self._warmed_up = True
            
            if response.usage:
                cache_created = getattr(
                    response.usage, "cache_creation_input_tokens", 0
                )
                logger.info(
                    f"Claude API warmup complete ✓ "
                    f"(cache primed: {cache_created} tokens)"
                )
        except Exception as e:
            logger.warning(f"Warmup failed (non-critical): {e}")
    
    async def generate(self, question: str, kb_chunks: list[str], question_type: str = "personal", ...) -> AsyncIterator[str]:
        """Generate with cache tracking"""
        
        self._cache_stats["total_calls"] += 1
        
        user_message = self._build_user_message(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
        )
        
        temperature = TEMPERATURE_MAP.get(question_type, 0.3)
        
        try:
            async with self.client.messages.stream(
                model=MODEL,
                max_tokens=1024,
                temperature=temperature,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text
                
                # Track cache stats
                response = await stream.get_final_message()
                if response.usage:
                    cached = getattr(response.usage, "cache_read_input_tokens", 0)
                    created = getattr(response.usage, "cache_creation_input_tokens", 0)
                    
                    if cached > 0:
                        self._cache_stats["cache_hits"] += 1
                        logger.info(f"CACHE HIT ⚡ {cached} tokens from cache")
                    elif created > 0:
                        self._cache_stats["cache_misses"] += 1
                        logger.info(f"CACHE CREATED: {created} tokens cached")
                    else:
                        self._cache_stats["cache_misses"] += 1
                    
                    # Track by type
                    if question_type not in self._cache_stats["by_type"]:
                        self._cache_stats["by_type"][question_type] = {"hits": 0, "misses": 0}
                    
                    if cached > 0:
                        self._cache_stats["by_type"][question_type]["hits"] += 1
                    else:
                        self._cache_stats["by_type"][question_type]["misses"] += 1
        
        except Exception as e:
            logger.error(f"Response generation error: {e}")
            yield f"[Error: {str(e)[:100]}]"
```

##### Testing
```bash
# Test cache statistics
python -c "
import asyncio
from src.response.claude_agent import ResponseAgent

async def test():
    agent = ResponseAgent()
    await agent.warmup()
    
    # Generate 5 responses
    for i in range(5):
        text = await agent.generate_full(
            f'Question {i}?',
            ['Context'],
            'personal'
        )
        
        stats = await agent.get_cache_stats()
        hit_rate = stats['hit_rate']
        print(f'After Q{i+1}: hit_rate={hit_rate:.1%}')
    
    # After 5 questions, should have >50% hit rate
    stats = await agent.get_cache_stats()
    assert stats['hit_rate'] > 0.5, f'Hit rate too low: {stats[\"hit_rate\"]:.1%}'

asyncio.run(test())
"
```

---

### Sprint 3 Summary
| Task | Time |
|------|------|
| 3.1.1 Chunk validation/dedup | 60 min |
| 3.2.1 Cache optimization | 60 min |
| **TOTAL** | **120 min** |

---

## 📈 FASE 4: OBSERVABILIDAD (Sprint 7-8, ~2.5 horas)

### Objetivo
Telemetría completa, dashboards, alerting para producción.

### Sprint 4.1: Instrumentación de Métricas (90 minutos)

#### Task 4.1.1: Session Metrics & Logging
**Criticidad:** 🟢 BAJO  
**Archivos:** `main.py`, nuevo archivo `src/metrics.py`

##### Especificación
```
SOLUCIÓN:
  1. Crear SessionMetrics dataclass
  2. Track: latencia, cache hits, hallucinations, tokens usados
  3. Exportar a JSON por sesión
  4. Integrar con Prometheus (opcional)
  
CRITERIOS:
  ✓ Metrics exportados a JSON
  ✓ Logs incluyen metrics timestamp
  ✓ Prometheus scrape si configured
```

##### Implementación
```python
# Nuevo archivo: src/metrics.py

from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
import json
import logging

logger = logging.getLogger("metrics")

@dataclass
class QuestionMetrics:
    question_id: int
    question_text: str
    question_type: str
    timestamp: str
    duration_ms: float
    classification_ms: float
    retrieval_ms: float
    generation_ms: float
    tokens_used: int
    cache_hit: bool
    speculative_hit: bool
    response_text: str = field(repr=False)

@dataclass
class SessionMetrics:
    session_id: str
    start_time: datetime
    questions: list[QuestionMetrics] = field(default_factory=list)
    
    @property
    def duration_sec(self) -> float:
        return (datetime.now() - self.start_time).total_seconds()
    
    @property
    def avg_latency_ms(self) -> float:
        if not self.questions:
            return 0.0
        return sum(q.duration_ms for q in self.questions) / len(self.questions)
    
    @property
    def cache_hit_rate(self) -> float:
        if not self.questions:
            return 0.0
        hits = sum(1 for q in self.questions if q.cache_hit)
        return hits / len(self.questions)
    
    def add_question(self, metrics: QuestionMetrics):
        self.questions.append(metrics)
        logger.info(
            f"Q{len(self.questions)}: {metrics.question_type} "
            f"({metrics.duration_ms:.0f}ms, cache={'HIT' if metrics.cache_hit else 'miss'})"
        )
    
    def save(self, output_path: Path):
        """Save metrics to JSON"""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "duration_sec": self.duration_sec,
            "total_questions": len(self.questions),
            "avg_latency_ms": self.avg_latency_ms,
            "cache_hit_rate": self.cache_hit_rate,
            "questions": [asdict(q) for q in self.questions],
        }
        
        output_path.write_text(json.dumps(data, indent=2))
        logger.info(f"Metrics saved to {output_path}")

# En main.py:
import uuid
from src.metrics import SessionMetrics, QuestionMetrics

_session_metrics = SessionMetrics(
    session_id=str(uuid.uuid4())[:8],
    start_time=datetime.now()
)

# En process_question():
metrics = QuestionMetrics(
    question_id=len(_session_metrics.questions) + 1,
    question_text=question,
    question_type=classification["type"],
    timestamp=datetime.now().isoformat(),
    duration_ms=time.time() - start_time,  # track timing
    classification_ms=...,  # track each component
    retrieval_ms=...,
    generation_ms=...,
    tokens_used=response_tokens,
    cache_hit=response_cache_hit,
    speculative_hit=speculative_hit,
    response_text=response_text
)
_session_metrics.add_question(metrics)

# En stop_pipeline():
_session_metrics.save(Path("logs") / f"metrics_{_session_metrics.session_id}.json")
```

---

#### Task 4.1.2: Alertas Basadas en SLOs
**Criticidad:** 🟢 BAJO  
**Archivos:** Nuevo archivo `src/alerting.py`

##### Especificación
```
ALERTAS:
  1. P95 Latency > 5s (warning), >7s (critical)
  2. Cache hit rate < 60% (warning)
  3. Hallucination detected (critical)
  4. API error rate > 5% (warning)
  
Integración: logging + opcional Slack/email
```

##### Implementación
```python
# Nuevo: src/alerting.py

class AlertManager:
    def __init__(self):
        self.slos = {
            "p95_latency_ms": 5000,
            "cache_hit_rate": 0.6,
            "error_rate": 0.05,
        }
        self.alerts = []
    
    def check_metrics(self, session: SessionMetrics):
        """Check session metrics against SLOs"""
        
        # P95 latency
        latencies = sorted([q.duration_ms for q in session.questions])
        if latencies:
            p95 = latencies[int(len(latencies) * 0.95)]
            if p95 > self.slos["p95_latency_ms"]:
                self.raise_alert(
                    "critical",
                    f"P95 latency {p95:.0f}ms exceeds SLO {self.slos['p95_latency_ms']}ms"
                )
        
        # Cache hit rate
        if session.cache_hit_rate < self.slos["cache_hit_rate"]:
            self.raise_alert(
                "warning",
                f"Cache hit rate {session.cache_hit_rate:.1%} below SLO {self.slos['cache_hit_rate']:.1%}"
            )
    
    def raise_alert(self, severity: str, message: str):
        """Raise alert with optional Slack integration"""
        logger.warning(f"[{severity.upper()}] {message}")
        
        # Optional: send to Slack
        # slack_client.post_message(channel="#alerts", text=message)
```

---

### Sprint 4 Summary
| Task | Time | Status |
|------|------|--------|
| 4.1.1 Session metrics | 60 min | 📋 Spec |
| 4.1.2 Alertas SLOs | 30 min | 📋 Spec |
| **TOTAL** | **90 min** | |

---

## ✅ VALIDACIÓN Y DEPLOYMENT

### Pre-Deployment Checklist (Claude debe validar)

```bash
# 1. Todos los tests pasan
pytest tests/ -v --tb=short --cov=src 2>&1 | grep -E "passed|failed|ERROR"

# 2. No breaking changes
git diff HEAD~4 --name-only | xargs grep -l "class \|def " | wc -l

# 3. Performance targets met
# P50: <4s, P95: <5s (measured from main.py logs)
grep "duration_ms" logs/metrics_*.json | head -10

# 4. Code quality
pylint src/ --exit-zero --rcfile=.pylintrc

# 5. Documentation updated
find . -name "*.md" -newer ANALISIS_PROYECTO_COMPLETO.md | wc -l

# 6. Backward compatibility
python -c "from src.response.claude_agent import ResponseAgent; print('✓ Imports OK')"

# 7. Security: no credentials in code
grep -r "sk-\|api_key=" src/ tests/ --include="*.py" && echo "⚠️ Found creds" || echo "✓ No creds"
```

### Deployment Strategy
```
Phase 1 (Stability) → Canary deploy 10% traffic
Phase 2 (Performance) → A/B test new speculative logic
Phase 3 (Quality) → Full rollout with monitoring
Phase 4 (Observability) → Production metrics live
```

---

## 📊 TIMELINE EJECUTABLE

```
SEMANA 1 (Phase 1: Estabilidad)
├─ Lunes-Martes: Tasks 1.1.1, 1.1.2, 1.1.3 (65 min)
├─ Miércoles-Jueves: Tasks 1.2.1, 1.2.2 (30 min)
├─ Viernes: Testing + bugfixes (30 min)
└─ Validación: 5/5 runs sin crashes ✓

SEMANA 2 (Phase 2: Rendimiento)
├─ Lunes-Martes: Tasks 2.1.1, 2.2.1 (90 min)
├─ Miércoles: Task 2.2.2 (30 min)
├─ Jueves-Viernes: A/B testing + tuning (60 min)
└─ Validación: P95 < 5s ✓

SEMANA 3 (Phase 3: Calidad)
├─ Lunes-Martes: Tasks 3.1.1, 3.2.1 (120 min)
├─ Miércoles-Jueves: Cache tuning (60 min)
├─ Viernes: Regression testing (30 min)
└─ Validación: Cache hit rate > 75% ✓

SEMANA 4 (Phase 4: Observabilidad)
├─ Lunes-Miércoles: Tasks 4.1.1, 4.1.2 (90 min)
├─ Jueves: Prometheus + Grafana setup (60 min)
├─ Viernes: Live monitoring validation (30 min)
└─ Validación: Metrics visible en dashboard ✓

PRODUCCIÓN (Semana 5)
├─ Canary deploy (10% traffic)
├─ Monitor SLOs (24h)
├─ Full rollout si cumple SLOs
└─ Maintenance oncall (2 semanas)
```

---

## 🤖 INSTRUCCIONES PARA CLAUDE OPUS 4.6 (THINKING)

### Activación del Agente (Open Agent Manager)

```json
{
  "agent_config": {
    "model": "claude-opus-4-6-20250514",
    "enable_thinking": true,
    "thinking_budget_tokens": 20000,
    "task_timeout_seconds": 3600,
    "max_retries": 3,
    "require_human_approval": ["deploy_to_prod"]
  },
  "task_pipeline": [
    {
      "phase": 1,
      "name": "Stability",
      "tasks": [
        "implement_speculative_sync",
        "implement_timeout_response",
        "implement_public_getter",
        "implement_teleprompter_health",
        "implement_retry_logic"
      ],
      "validation_required": true
    },
    {
      "phase": 2,
      "name": "Performance",
      "depends_on": ["phase_1_validation"],
      "tasks": [
        "implement_semantic_similarity",
        "implement_compound_detection",
        "implement_fuzzy_matching"
      ],
      "validation_required": true
    }
    // ... etc
  ],
  "success_criteria": {
    "phase_1": {
      "all_tests_pass": true,
      "crash_count": 0,
      "code_quality_warnings": 0
    },
    "phase_2": {
      "p95_latency_ms": 5000,
      "cache_hit_rate": 0.75
    }
    // ... etc
  }
}
```

### Thinking Directives (Claude debe usar para cada task)

Para cada tarea, Claude debe:

1. **ANALYZE** (5 min de thinking)
   - ¿Cuál es el problema exacto?
   - ¿Dónde ocurre en el código?
   - ¿Cuáles son las dependencias?

2. **PLAN** (5 min)
   - Estrategia de implementación
   - Posibles edge cases
   - Rollback plan si falla

3. **IMPLEMENT** (20 min)
   - Escribir código
   - Validar sintaxis
   - Agregar logging

4. **TEST** (10 min)
   - Test cases
   - Integration tests
   - Performance tests

5. **VALIDATE** (5 min)
   - Metrics meet criteria?
   - No regressions?
   - Ready for next phase?

---

## 🎯 CONCLUSIÓN

Este roadmap es **completamente automático y ejecutable** por Claude Opus 4.6 a través de Open Agent Manager:

✅ **Especificaciones claras** para cada task  
✅ **Código de ejemplo** ready-to-implement  
✅ **Test cases** para validación  
✅ **Fallback strategies** para errores  
✅ **Timeline realista** (8.5 horas total)  
✅ **Success metrics** cuantificables  
✅ **Thinking budget** asignado correctamente  

**Próximo paso:** Enviar este roadmap a Open Agent Manager de Antigravity con la configuración JSON anterior.

---

**Roadmap Creado:** 1 Marzo 2026  
**Versión:** 1.0  
**Estado:** Listo para Ejecución por Claude Opus 4.6 (Thinking)

