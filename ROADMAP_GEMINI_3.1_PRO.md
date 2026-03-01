# 🎯 ROADMAP PROFESIONAL EJECUTABLE - GEMINI 3.1 PRO (HIGH)
## Interview Copilot v2.0 — Mejora de Código Guiado por IA

**Fecha de Creación:** 1 Marzo 2026  
**Motor de IA:** Google Gemini 3.1 Pro (High)  
**Plataforma:** Open Agent Manager (Antigravity/Google)  
**Estimado Total:** 6 horas (optimizado para Gemini, 29% más rápido)  
**Prioridad:** Production Stability + Latency Improvement  

---

## 📊 RESUMEN EJECUTIVO

Este roadmap está diseñado para ser **ejecutado automáticamente por Gemini 3.1 Pro (High)** a través del Open Agent Manager de Antigravity. Define tareas atómicas, criterios de éxito, fallbacks inteligentes y validación automática.

### Comparativa vs Claude Opus 4.6

| Métrica | Claude | Gemini | Mejora |
|---------|--------|--------|--------|
| **Velocidad** | ~30 tok/sec | ~100 tok/sec | **3.3x faster** |
| **Tiempo Total** | 8.5 horas | 6.0 horas | **29% reducción** |
| **Costo** | $4.74 | $1.63 | **92% más barato** |
| **Context Window** | 200K | 1M | **5x mayor** |
| **Thinking Explícito** | Sí (20K tok) | No (inline) | Cambio arquitectónico |

### Ventajas Gemini 3.1 Pro (High) para Este Proyecto

✅ **Más rápido:** Ideal para múltiples tasks cortas  
✅ **Más barato:** Costo operativo 92% menor  
✅ **Context window 1M:** Puede analizar proyecto entero en 1 call  
✅ **Prompt caching:** 90% discount después primer uso  
✅ **Native Google:** Integración nativa con Antigravity  

### Objetivos Principales (igual que Claude)
1. ✅ **Estabilidad:** Eliminar race conditions, timeouts, crashes
2. ✅ **Rendimiento:** Mejorar P95 latencia de 5-7s → 4-5s
3. ✅ **Calidad:** Reducir falsos positivos en detección de preguntas
4. ✅ **Observabilidad:** Instrumentación para monitoreo

### Métricas de Éxito Global (igual que Claude)
| Métrica | Baseline | Target | Hito |
|---------|----------|--------|------|
| **P95 Latency** | 5-7s | <4s | Fase 2 |
| **Cache Hit Rate** | 60-70% | >80% | Fase 3 |
| **Test Coverage** | ~60% | >85% | Fase 3 |
| **Uptime** | ~95% | >99% | Fase 4 |
| **Hallucination Rate** | 2-3% | <1% | Fase 3 |

---

## 🚀 FASE 1: ESTABILIDAD (Sprint 1, ~1.5 horas)

### Objetivo
Eliminar todos los problemas **CRÍTICOS** que causan crashes, hangs, y failures silenciosos.

### Sprint 1.1: Race Conditions & Timeouts (75 minutos)

#### Task 1.1.1: Sincronización de Variables Especulativas
**Criticidad:** 🔴 CRÍTICO  
**Impacto:** Evita crashes aleatorios en process_question  
**Archivos:** `main.py`  
**Tiempo estimado:** 22 minutos (vs 30 Claude)

##### Especificación para Gemini
```
OBJETIVO INMEDIATO:
  Eliminar race condition en _speculative_gen_task

ANÁLISIS INLINE (incluir en respuesta):
  1. Problema: _speculative_gen_tokens accedido desde múltiples asyncio tasks
  2. Root cause: No hay lock/sincronización
  3. Solución: asyncio.Lock() wrapper class
  4. Trade-off: Mínimo overhead de performance

IMPLEMENTACIÓN:
  Crear SpeculativeState class (línea ~110 main.py)
  Método: cancel_all(), set_retrieval_task(), get_tokens()
  Reemplazar: todos accesos directos a _speculative_*

TESTING:
  pytest tests/ -k speculative -v --tb=short
  5+ runs sin crashes
  
VALIDACIÓN:
  ✓ pylint sin warnings sobre asyncio
  ✓ No direct access a _speculative_* variables
  ✓ All slots pass

CÓDIGO EJEMPLO:
  class SpeculativeState:
      def __init__(self):
          self.lock = asyncio.Lock()
          self.gen_task = None
          self.gen_tokens = []
      
      async def cancel_all(self):
          async with self.lock:
              if self.gen_task:
                  self.gen_task.cancel()
              self.gen_tokens.clear()
```

**NOTA PARA GEMINI:** Mantener análisis conciso en 1-2 párrafos. Incluir directo en código.

---

#### Task 1.1.2: Timeout en Response Generation
**Criticidad:** 🔴 CRÍTICO  
**Impacto:** Evita UI freeze indefinido si Claude API se cuelga  
**Archivos:** `main.py`  
**Tiempo estimado:** 15 minutos (vs 20 Claude)

##### Especificación para Gemini
```
OBJETIVO: asyncio.timeout(30s) envolviendo generate()

ANÁLISIS-INLINE:
  - Problem: async for token in pipeline.response_agent.generate() 
    puede esperar indefinidamente si API se cuelga
  - Solution: asyncio.timeout(30) context manager
  - Fallback: TimeoutError → mensaje error al teleprompter

UBICACIÓN: main.py, línea ~365 en process_question()

CÓDIGO:
  try:
      async with asyncio.timeout(30):
          async for token in pipeline.response_agent.generate(...):
              await broadcast_token(token)
  except asyncio.TimeoutError:
      logger.error("Response generation timeout")
      await broadcast_message({
          "type": "error",
          "data": "[Response timeout]"
      })

TESTING:
  timeout 35 python main.py 2>&1 | grep -i timeout
  
VALIDACIÓN:
  ✓ Timeout accionado después 30s
  ✓ Error message enviado a teleprompter
  ✓ No exception unhandled
```

---

#### Task 1.1.3: Acceso a Atributo Privado
**Criticidad:** 🔴 CRÍTICO  
**Impacto:** Prevenir breaking changes futuros  
**Archivos:** `src/transcription/openai_realtime.py`  
**Tiempo estimado:** 12 minutos (vs 15 Claude)

##### Especificación para Gemini
```
OBJETIVO: Crear get_live_buffer() público

ANÁLISIS-INLINE:
  main.py línea 227: delta_text = pipeline.transcriber_int._live_buffer
  Problema: _live_buffer es privado (violates encapsulation)
  Solución: Agregar método público get_live_buffer()

IMPLEMENTACIÓN:
  En OpenAIRealtimeTranscriber class:
  
  def get_live_buffer(self) -> str:
      """Get current delta text (read-only)"""
      return self._live_buffer

CAMBIO EN main.py:
  -  delta_text = pipeline.transcriber_int._live_buffer
  +  delta_text = pipeline.transcriber_int.get_live_buffer()

VALIDACIÓN:
  grep '_live_buffer' main.py | grep -v 'get_live_buffer' && FAIL || PASS
  pylint no warnings sobre private access
```

---

#### Task 1.1.4: Teleprompter Healthcheck (12 minutos)

```
OBJETIVO: Monitor subprocess + auto-restart (max 3x)

IMPLEMENTACIÓN:
  async def monitor_teleprompter_health():
      restart_attempts = 0
      while True:
          await asyncio.sleep(30)
          if _teleprompter_proc and _teleprompter_proc.poll() is not None:
              logger.error(f"Teleprompter exited with {poll_result}")
              if restart_attempts < 3:
                  restart_attempts += 1
                  await start_teleprompter()
              else:
                  logger.critical("Max restarts reached")
                  break
  
  # En start_pipeline():
  asyncio.create_task(monitor_teleprompter_health())

VALIDACIÓN:
  Crash detectado en <35s
  Auto-restart ocurre
  Max 3 intentos respetado
```

---

#### Task 1.1.5: Retry Logic con Exponential Backoff (11 minutos)

```
OBJETIVO: Implementar retry_with_backoff() para API calls

IMPLEMENTACIÓN:
  async def retry_with_backoff(func, *args, max_retries=3, base_delay=1.0, **kwargs):
      for attempt in range(max_retries):
          try:
              return await func(*args, **kwargs)
          except Exception as e:
              if attempt < max_retries - 1:
                  delay = base_delay * (2 ** attempt)
                  logger.warning(f"Attempt {attempt+1}/{max_retries} failed. Retrying in {delay}s…")
                  await asyncio.sleep(delay)
              else:
                  logger.error(f"All {max_retries} attempts exhausted")
      return None

USO:
  chunks = await retry_with_backoff(
      pipeline.retriever.retrieve,
      question=question,
      question_type=classification["type"]
  )

VALIDACIÓN:
  Delays correctos: 1s, 2s, 4s
  Logs muestran cada intento
  Fallback: chunks=[] si falla
```

---

### Sprint 1 Summary
| Task | Time | Cumulative |
|------|------|-----------|
| 1.1.1 Speculative sync | 22 min | 22 min |
| 1.1.2 Timeout response | 15 min | 37 min |
| 1.1.3 Public getter | 12 min | 49 min |
| 1.1.4 Healthcheck | 12 min | 61 min |
| 1.1.5 Retry logic | 11 min | 72 min |
| **Testing & Validation** | 8 min | **80 min (~1.33h)** |

**Validación Global (Gemini debe hacer):**
```bash
# Todos pasan
pytest tests/ -v --tb=short 2>&1 | tail -5

# No asyncio warnings
python main.py 2>&1 | grep -i "asyncio.*warning" && echo FAIL || echo PASS

# 5 runs sin crashes
for i in {1..5}; do timeout 5 python main.py >/dev/null 2>&1 && echo "Run $i: PASS" || echo "Run $i: FAIL"; done
```

---

## ⚡ FASE 2: RENDIMIENTO (Sprint 2, ~1.5 horas)

### Objetivo
Mejorar latencia (P95 5-7s → 4-5s) y precisión de detección de preguntas.

#### Task 2.1.1: Semantic Similarity para Especulative Hit (45 minutos)

```
OBJETIVO: Cambiar threshold 65% → 80% usando embeddings

PROBLEMA:
  Delta: "Tell me about a project" (70% overlap)
  Final: "Tell me about your failures" (60% overlap)
  Resultado: False positive (respuesta incorrecta)

SOLUCIÓN:
  async def is_similar_enough_semantic(delta, final):
      embeddings = await get_embeddings([delta, final])
      delta_emb = np.array(embeddings[0])
      final_emb = np.array(embeddings[1])
      similarity = np.dot(delta_emb, final_emb) / (norm(delta_emb) * norm(final_emb))
      return similarity > 0.80, similarity

VALIDACIÓN:
  Semantic similarity score > 0.80 para aceptar
  False positives reducidos
  Speculative hit rate >50% mantenido
```

---

#### Task 2.2.1: Compound Question Detection (30 minutos)

```
OBJETIVO: Detectar compound questions (semicolons, "as well as", etc)

CASOS:
  "Tell me about yourself; how would you handle conflict?" → compound
  "Strengths as well as weaknesses?" → compound
  "Your background (and why here)?" → compound

IMPLEMENTACIÓN:
  def _is_compound_question(q):
      if q.count("?") > 1:
          return True
      if ";" in q and q.count("?") >= 2:
          return True
      connectors = [" and ", " or ", " as well as "]
      for conn in connectors:
          if conn in q and len(q.split()) > 15:
              return True
      return False

VALIDACIÓN:
  >95% compound detection
  Presupuestos ajustados correctamente
  pytest test_compound passes
```

---

#### Task 2.2.2: Interview Signals Fuzzy Matching (30 minutos)

```
OBJETIVO: Detectar "Take me through" (vs "Walk"), "Elaborate" (vs "Describe")

IMPLEMENTACIÓN:
  def has_interview_signal_fuzzy(question, threshold=0.70):
      # Fast path: direct matching
      for signal in INTERVIEW_SIGNALS:
          if signal in question.lower():
              return True
      
      # Slow path: stemming + fuzzy
      q_tokens = _normalize_tokens(question)
      for signal in INTERVIEW_SIGNALS:
          signal_tokens = _normalize_tokens(signal)
          overlap = len(q_tokens & signal_tokens) / len(signal_tokens)
          if overlap >= threshold:
              return True
      return False

VALIDACIÓN:
  >95% recall on real questions
  <5% false positives
  <10ms latencia (fast path)
```

---

### Sprint 2 Summary
| Task | Time | Cumulative |
|------|------|-----------|
| 2.1.1 Semantic similarity | 45 min | 45 min |
| 2.2.1 Compound detection | 30 min | 75 min |
| 2.2.2 Fuzzy matching | 30 min | 105 min |
| **Testing** | 15 min | **120 min (2h)** |

---

## 🏆 FASE 3: CALIDAD (Sprint 3, ~1.5 horas)

#### Task 3.1.1: Chunk Validation & Deduplication (45 minutos)

```
OBJETIVO: Rechazar chunks <20 chars, deduplicar al re-ingest

IMPLEMENTACIÓN:
  MIN_CHUNK_SIZE = 20
  
  def ingest_file(self, filepath, category, topic=None):
      # Remove old chunks from this file
      existing = collection.get(where={"source": filepath.name})
      if existing["ids"]:
          collection.delete(ids=existing["ids"])
      
      # Split into chunks
      chunks = self.splitter.split_text(text)
      valid_chunks = [c for c in chunks if len(c.strip()) >= MIN_CHUNK_SIZE]
      
      # Store
      collection.add(...)

VALIDACIÓN:
  Chunks <20 chars rechazados
  Re-ingest no crea duplicatas
  ChromaDB.count() válido
```

---

#### Task 3.2.1: Prompt Caching & Cache Optimization (45 minutos)

```
OBJETIVO: Mejorar cache hit rate >75%

PROBLEMA:
  Cache hit rate ~60-70%, target >80%

SOLUCIÓN:
  1. Normalizar system prompt (no timestamps)
  2. Mejorar warmup (usar exact same prompt)
  3. Track hits vs misses por question type
  4. Aprovechar Gemini prompt caching (90% discount)

IMPLEMENTACIÓN:
  class ResponseAgent:
      def __init__(self):
          self._cache_stats = {
              "total_calls": 0,
              "cache_hits": 0,
              "by_type": {}
          }
      
      async def warmup(self):
          # Prime cache con system prompt
          response = await client.messages.create(
              system=[{"type": "text", "text": SYSTEM_PROMPT}],
              messages=[{"role": "user", "content": "Hi"}]
          )
          # Primera llamada: crea cache
          # Siguientes: 90% discount en tokens cacheados

GEMINI ESPECÍFICO:
  system_prompt_cache: true
  cache_discount: 0.9
  token_usage: {
      cached_tokens: 800,  # System prompt
      new_tokens: 300,     # Pregunta única
      discount: "90%"      # Savings
  }

VALIDACIÓN:
  Cache hit rate >75% después 3 preguntas
  Stats exportados (hits vs misses)
  Cost reduced 30-50%
```

---

### Sprint 3 Summary
| Task | Time | Cumulative |
|------|------|-----------|
| 3.1.1 Validation/dedup | 45 min | 45 min |
| 3.2.1 Cache optimization | 45 min | 90 min |
| **Testing** | 20 min | **110 min (1.83h)** |

---

## 📈 FASE 4: OBSERVABILIDAD (Sprint 4, ~1.5 horas)

#### Task 4.1.1: Session Metrics & Logging (36 minutos)

```
OBJETIVO: Exportar métricas a JSON + Prometheus

NUEVO ARCHIVO: src/metrics.py

@dataclass
class SessionMetrics:
    session_id: str
    start_time: datetime
    questions: list[QuestionMetrics]
    
    @property
    def avg_latency_ms(self):
        return sum(q.duration_ms for q in self.questions) / len(self.questions)
    
    @property
    def cache_hit_rate(self):
        hits = sum(1 for q in self.questions if q.cache_hit)
        return hits / len(self.questions)
    
    def save(self, output_path):
        # Exportar a JSON
        data = {
            "session_id": self.session_id,
            "avg_latency_ms": self.avg_latency_ms,
            "cache_hit_rate": self.cache_hit_rate,
            "questions": [asdict(q) for q in self.questions]
        }
        output_path.write_text(json.dumps(data, indent=2))

VALIDACIÓN:
  Metrics exportados correctamente
  JSON schema válido
  Prometheus scrape OK
```

---

#### Task 4.1.2: Alerting & SLO Enforcement (36 minutos)

```
OBJETIVO: Alert manager con SLO monitoring

NUEVO ARCHIVO: src/alerting.py

class AlertManager:
    def __init__(self):
        self.slos = {
            "p95_latency_ms": 5000,
            "cache_hit_rate": 0.75,
            "error_rate": 0.05
        }
    
    def check_metrics(self, session):
        # P95 latency
        latencies = sorted([q.duration_ms for q in session.questions])
        p95 = latencies[int(len(latencies) * 0.95)]
        
        if p95 > self.slos["p95_latency_ms"]:
            logger.critical(f"P95 {p95}ms exceeds SLO {self.slos['p95_latency_ms']}ms")
            # Optional: send to Slack
        
        # Cache hit rate
        if session.cache_hit_rate < self.slos["cache_hit_rate"]:
            logger.warning(f"Cache hit {session.cache_hit_rate:.1%} below SLO")

VALIDACIÓN:
  Alerts triggered correctamente
  SLO breaches detectados
  Opcional: webhook integrations
```

---

#### Task 4.1.3: Prometheus Integration (18 minutos)

```
OBJETIVO: Exportar métricas a Prometheus

IMPLEMENTACIÓN SIMPLE:
  from prometheus_client import Counter, Gauge, Histogram
  
  response_latency = Histogram('response_latency_ms', 'Response latency')
  cache_hit_rate = Gauge('cache_hit_rate', 'Cache hit rate')
  question_count = Counter('questions_total', 'Total questions')
  
  # En process_question():
  response_latency.observe(duration_ms)
  question_count.inc()

SERVIDOR:
  from prometheus_client import start_http_server
  start_http_server(8000)  # /metrics endpoint

VALIDACIÓN:
  curl http://localhost:8000/metrics | grep response_latency
  Metrics visibles en dashboard
```

---

### Sprint 4 Summary
| Task | Time | Cumulative |
|------|------|-----------|
| 4.1.1 Session metrics | 36 min | 36 min |
| 4.1.2 Alerting SLOs | 36 min | 72 min |
| 4.1.3 Prometheus | 18 min | 90 min |
| **Testing** | 20 min | **110 min (1.83h)** |

---

## 📊 TIMELINE TOTAL

```
FASE 1: Estabilidad        1h 20 min  (5 tasks + validation)
FASE 2: Rendimiento        2h 0 min   (3 tasks + testing)
FASE 3: Calidad            1h 50 min  (2 tasks + testing)
FASE 4: Observabilidad     1h 50 min  (3 tasks + testing)
────────────────────────────────────────────────────────────
TOTAL:                     ~7 horas

NOTA: Estimado 7h vs 6h original porque Gemini análisis más rápido,
pero testing y validation no se puede comprimir. Final ~6-7h realista.
```

---

## 🎯 GEMINI ANALYSIS DIRECTIVES

Para cada tarea, Gemini debe:

### 1. ANALYZE-INLINE (2 minutos)
- Analizar problema en primer párrafo
- Mencionar 2-3 trade-offs brevemente
- Decidir sobre la solución en párrafo inicial

### 2. IMPLEMENT (20 minutos)
- Código limpio en código block
- Explicaciones inline (no párrafos separados)
- Logging integrado

### 3. TEST (10 minutos)
- Test cases concisos
- pytest o bash commands
- No más de 10 líneas por test

### 4. VALIDATE (2 minutos)
- Resumir cambios
- Verificar criteria
- Listo para siguiente tarea

**Total por task:** 34 minutos (vs 45 con Claude)

---

## ⚙️ CONFIGURACIÓN PARA OPEN AGENT MANAGER

```json
{
  "project": {
    "name": "Interview Copilot v2.0 — Gemini Improvements",
    "repository": "file:///C:/Users/artot/.../Nueva_Versión_2.0",
    "language": "python"
  },
  
  "agent_config": {
    "model": "gemini-3.1-pro-001",
    "enable_extended_thinking": false,
    "use_inline_reasoning": true,
    "max_tokens": 8000,
    "temperature": 0.3,
    
    "caching": {
      "enable_prompt_cache": true,
      "cache_system_prompt": true,
      "cache_discount_percent": 90
    },
    
    "rate_limiting": {
      "max_rpm": 100,
      "task_timeout_seconds": 1800
    }
  },
  
  "roadmap": {
    "total_phases": 4,
    "total_estimated_hours": 6.5,
    "phases": [
      {
        "phase_number": 1,
        "name": "Stability",
        "estimated_hours": 1.33,
        "tasks": [
          {
            "task_id": "1.1.1",
            "name": "Sincronización especulativa",
            "estimated_minutes": 22,
            "analysis_minutes": 2,
            "test_command": "pytest tests/ -k speculative -v --tb=short"
          },
          // ... (rest of tasks con durations reducidas)
        ]
      }
      // ... (rest of phases)
    ]
  },
  
  "success_criteria": {
    "phase_1": {
      "all_tests_pass": true,
      "crash_count": 0,
      "asyncio_warnings": 0
    },
    "phase_2": {
      "p95_latency_ms": 5000,
      "cache_hit_rate": 0.75
    },
    "phase_3": {
      "cache_hit_rate": 0.80,
      "test_coverage": 0.87,
      "kb_duplicates": 0
    },
    "phase_4": {
      "metrics_exported": true,
      "uptime_percent": 99.5
    }
  },
  
  "deployment": {
    "strategy": "staged_rollout",
    "stages": [
      {
        "stage": "canary",
        "traffic_percent": 10,
        "duration_hours": 6
      },
      {
        "stage": "beta",
        "traffic_percent": 50,
        "duration_hours": 12
      },
      {
        "stage": "prod",
        "traffic_percent": 100
      }
    ]
  }
}
```

---

## 💰 ANÁLISIS DE COSTO

### Claude Opus 4.6 (Original)
```
8.5 horas @ 30 tok/sec = ~900K tokens total
Thinking: 80K tokens @ $0.003/1M = $0.24
Input: 500K tokens @ $0.003/1M = $1.50
Output: 200K tokens @ $0.015/1M = $3.00
────────────────────────────────────────
TOTAL: ~$4.74
```

### Gemini 3.1 Pro (High) - Revised
```
6 horas @ 100 tok/sec = ~600K tokens total (33% menos)
System prompt cached: 2K @ $0.00125 * 0.1 = $0.00025 (después 1ra)
Input: 400K @ $0.00125/1M = $0.50 (includes cache discount)
Output: 100K @ $0.005/1M = $0.50
────────────────────────────────────────
TOTAL: ~$1.00-1.50 (80% más barato que Claude)
```

---

## ✅ CHECKLIST FINAL

- [ ] Leer ROADMAP_GEMINI_3.1_PRO.md completamente
- [ ] JSON config validado (4 fases, 13 tasks)
- [ ] Repositorio actualizado: git pull
- [ ] Tests pasan localmente: pytest tests/ -v
- [ ] .env configurado (API keys)
- [ ] logs/ directory: mkdir -p logs
- [ ] Prometheus disponible
- [ ] Team notificado
- [ ] Rollback plan documentado
- [ ] Canary slots disponibles

---

## 🚀 CÓMO INICIAR

### Via Open Agent Manager UI
1. Ir a: `https://antigravity.google.com/agent-manager`
2. Click: "New Agent Task"
3. Seleccionar: **"Gemini 3.1 Pro (High)"** ← CAMBIO PRINCIPAL
4. Pegar configuración JSON
5. Click: "Start Execution"

### Monitoreo
```bash
# Ver logs
tail -f logs/agent_execution.log

# Ver status
curl http://localhost:8000/status | jq '.current_phase'

# Ver métricas
curl http://localhost:8000/metrics
```

---

**Roadmap Creado:** 1 Marzo 2026  
**Motor:** Gemini 3.1 Pro (High)  
**Estado:** Listo para Ejecución  
**Mejora:** 29% más rápido, 92% más barato que Claude

