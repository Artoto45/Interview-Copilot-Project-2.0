# 📊 Cost Calculator Module — Documentación Completa

**Archivo:** `src/cost_calculator.py`  
**Versión:** 1.0  
**Fecha:** 1 Marzo 2026  
**Estado:** ✅ Implementado e Integrado

---

## 🎯 Propósito

Calcular con precisión los costos asociados a cada sesión de entrevista, rastreando:

1. **OpenAI Realtime API** → Transcripción de audio (usuario e interviewer)
2. **OpenAI Embeddings API** → Vectorización de preguntas para KB
3. **Anthropic Claude API** → Generación de respuestas con prompt caching
4. **Monitoreo de memoria/storage** → Opcional

---

## 💰 Precios Configurados (Q1 2026)

### OpenAI Realtime (gpt-4o-mini-transcribe)
```python
OPENAI_REALTIME_INPUT = $0.020 / minuto    # Audio user → text
OPENAI_REALTIME_OUTPUT = $0.020 / minuto   # Audio interviewer → text
```

### OpenAI Embeddings (text-embedding-3-small)
```python
OPENAI_EMBEDDING_INPUT = $0.020 / 1M tokens
```

### Anthropic Claude (claude-3-5-sonnet-20250514)
```python
CLAUDE_INPUT = $3.00 / 1M tokens
CLAUDE_OUTPUT = $15.00 / 1M tokens
CLAUDE_CACHE_WRITE = $3.75 / 1M tokens   # Prompt cache (first call)
CLAUDE_CACHE_READ = $0.30 / 1M tokens    # Cache hit (90% discount)
```

---

## 📋 Clases Principales

### 1. `CostTracker`

**Uso principal:** Rastrear todos los costos durante una sesión.

```python
# En main.py:
pipeline.cost_tracker = CostTracker(session_id="session_20260301_120000")

# Durante transcripción:
pipeline.cost_tracker.track_transcription(
    speaker="user",
    duration_seconds=5.2,
    api_name="openai_realtime_user"
)

# Durante embedding:
pipeline.cost_tracker.track_embedding(
    tokens=150,
    question="Tell me about your background"
)

# Durante generación:
pipeline.cost_tracker.track_generation(
    input_tokens=2048,
    output_tokens=256,
    cache_write_tokens=1024,
    cache_read_tokens=0,
    question="..."
)

# Al final:
report = pipeline.cost_tracker.get_session_report()
pipeline.cost_tracker.save_report(report)
```

#### Métodos

| Método | Parámetros | Descripción |
|--------|-----------|-------------|
| `track_transcription()` | speaker, duration_seconds | Track audio transcription cost |
| `track_embedding()` | tokens, question | Track embedding API cost |
| `track_generation()` | input_tokens, output_tokens, cache_* | Track Claude generation |
| `get_session_report()` | - | Get aggregated SessionCostBreakdown |
| `save_report()` | report, output_dir | Save report to JSON file |

### 2. `SessionCostBreakdown`

**Propósito:** Almacenar y agregar costos de una sesión completa.

```python
breakdown.costs_by_category  # Dict[str, float]
breakdown.api_calls_count    # Dict[str, int]
breakdown.total_cost_usd     # float
breakdown.questions_processed # int
breakdown.responses_generated # int

# Métricas detalladas:
breakdown.transcription_user_minutes
breakdown.transcription_interviewer_minutes
breakdown.embedding_input_tokens
breakdown.claude_input_tokens
breakdown.claude_output_tokens
breakdown.claude_cache_write_tokens
breakdown.claude_cache_read_tokens
```

### 3. `CostEntry`

**Propósito:** Registro individual de cada llamada a API.

```python
entry = CostEntry(
    timestamp="2026-03-01T12:00:00",
    category=CostCategory.GENERATION,
    api_name="claude_sonnet",
    input_amount=2048,
    input_unit="tokens",
    output_amount=256,
    output_unit="tokens",
    cache_write_tokens=1024,
    cost_usd=0.0567
)
```

---

## 🔄 Flujo de Integración en `main.py`

### 1. Inicialización (en `start_pipeline()`)
```python
pipeline.cost_tracker = CostTracker(session_id=session_id)
```

### 2. Tracking de Transcripción (automático)
```
En on_transcript():
    - Cada segmento de audio se duración se rastrearía
    - NOTA: Actualmente no implementado (requiere duración exacta)
```

### 3. Tracking de Embedding (en `process_question()`)
```python
if pipeline.cost_tracker:
    emb_tokens = estimate_embedding_tokens(question)
    pipeline.cost_tracker.track_embedding(
        tokens=emb_tokens,
        question=question,
    )
```

### 4. Tracking de Generación (en `process_question()`)
```python
if pipeline.cost_tracker:
    total_input_tokens = system_prompt + kb_tokens + question_tokens
    output_tokens = estimate_tokens(response_text)
    
    pipeline.cost_tracker.track_generation(
        input_tokens=total_input_tokens,
        output_tokens=output_tokens,
        question=question,
        cache_write_tokens=cache_write_tokens,
        cache_read_tokens=cache_read_tokens,
    )
```

### 5. Finalización (en `stop_pipeline()`)
```python
if pipeline.cost_tracker:
    cost_report = pipeline.cost_tracker.get_session_report()
    cost_report.questions_processed = pipeline.total_questions
    cost_report.responses_generated = pipeline.total_responses
    pipeline.cost_tracker.save_report(cost_report)
```

---

## 📊 Ejemplo de Reporte JSON

**Archivo:** `logs/costs_session_20260301_120000.json`

```json
{
  "session_id": "session_20260301_120000",
  "start_time": "2026-03-01T12:00:00.000000",
  "end_time": "2026-03-01T12:15:30.000000",
  "costs_by_category": {
    "embedding": 0.000450,
    "generation": 0.045600,
    "cache_write": 0.003750,
    "cache_read": 0.000120
  },
  "api_calls_count": {
    "openai_embedding": 3,
    "claude_sonnet": 3
  },
  "metrics": {
    "transcription_user_minutes": 0.0,
    "transcription_interviewer_minutes": 0.0,
    "embedding_input_tokens": 450,
    "claude_input_tokens": 2048,
    "claude_output_tokens": 768,
    "claude_cache_write_tokens": 1024,
    "claude_cache_read_tokens": 512
  },
  "totals": {
    "total_cost_usd": 0.049920,
    "questions_processed": 3,
    "responses_generated": 3
  },
  "cost_breakdown": {
    "embedding": 0.00045,
    "generation": 0.0456,
    "cache_write": 0.00375,
    "cache_read": 0.00012
  }
}
```

---

## 🔢 Algoritmo de Estimación de Tokens

### Para texto:
```python
estimated_tokens = len(text) // 4  # Aproximado (4 chars ≈ 1 token)
```

### Para embedding:
```python
embedding_tokens = estimate_embedding_tokens(question)
# Típicamente: 50-500 tokens para preguntas
```

### Para generación (desglosado):
```
input = system_prompt_tokens + kb_chunks_tokens + question_tokens
output = response_tokens
```

**Sistema de Prompt (típico):**
- Instrucciones base: ~200 tokens
- Contexto del candidato: ~400 tokens
- Indicaciones STAR: ~200 tokens
- Ejemplos: ~200 tokens
- **Total:** ~1024 tokens (constante por sesión)

---

## 🎯 Casos de Uso

### Caso 1: Monitoreo de costos en vivo
```python
# Mostrar costo actual durante la sesión
current_report = pipeline.cost_tracker.get_session_report()
logger.info(f"Current session cost: ${current_report.total_cost_usd:.4f}")
```

### Caso 2: Alertas de costo excesivo
```python
if current_report.total_cost_usd > 1.00:  # > $1
    logger.warning("Session cost exceeds $1 threshold!")
    await broadcast_message({
        "type": "cost_warning",
        "cost_usd": current_report.total_cost_usd
    })
```

### Caso 3: Análisis de rentabilidad
```python
# Costo por pregunta
cost_per_question = report.total_cost_usd / report.questions_processed
logger.info(f"Cost per question: ${cost_per_question:.4f}")

# Costo por respuesta
cost_per_response = report.total_cost_usd / report.responses_generated
logger.info(f"Cost per response: ${cost_per_response:.4f}")
```

### Caso 4: Identificar puntos de alto costo
```python
most_expensive = max(
    report.costs_by_category.items(),
    key=lambda x: x[1]
)
logger.info(f"Most expensive category: {most_expensive[0]} (${most_expensive[1]:.4f})")
```

---

## 📈 Ejemplo Numérico

### Escenario: Una sesión con 3 preguntas

**Transcripción:**
- Usuario: 5 min @ $0.020/min = $0.10
- Interviewer: 8 min @ $0.020/min = $0.16

**Embedding (3 preguntas):**
- Tokens por pregunta: ~150
- Costo: 3 × 150 tokens × $0.020/1M = $0.0009

**Generación (3 respuestas):**
- Pregunta 1: 2048 input (nuevo) + 256 output = $0.0616
- Pregunta 2: 1024 input (cache) + 256 output = $0.0046
- Pregunta 3: 1024 input (cache) + 256 output = $0.0046
- **Total:** $0.0708

**Caching:**
- Primera pregunta: 1024 cache write tokens = $0.00375
- Preguntas 2-3: 1024 × 2 cache read tokens = $0.000614

---

**Total Sesión:** $0.10 + $0.16 + $0.0009 + $0.0708 + $0.00375 + $0.000614 ≈ **$0.34**

---

## 🔧 Próximas Mejoras

| Mejora | Prioridad | Descripción |
|--------|-----------|-------------|
| Integrar tiktoken | Alta | Más precisión en token counting |
| Tracking transcripción | Alta | Implementar duración exacta de audio |
| Alertas de presupuesto | Media | Notificar si excede presupuesto |
| Dashboard de costos | Media | UI para monitoreo en vivo |
| Historial de sesiones | Baja | Análisis de tendencias |

---

## ✅ Estado de Implementación

- ✅ Core CostTracker class
- ✅ Integration en main.py
- ✅ Embedding tracking
- ✅ Generation tracking con prompt caching
- ✅ JSON report saving
- ✅ Logging de resumen
- ⏳ Transcription tracking (requiere duración precisa)
- ⏳ Prometheus metrics para costos
- ⏳ Dashboard de costos en vivo

---

**Módulo:** src/cost_calculator.py  
**Status:** ✅ LISTO PARA USAR  
**Última actualización:** 1 Marzo 2026

