# 🚀 COST CALCULATOR — GUÍA DE USO RÁPIDO

## Instalación (Ya Completada ✅)

```bash
# Archivo creado:
src/cost_calculator.py

# Integrado en:
main.py
```

---

## Uso Básico

### 1. Inicializar el Tracker

```python
from src.cost_calculator import CostTracker

# En start_pipeline():
pipeline.cost_tracker = CostTracker(
    session_id="session_20260301_120000"
)
```

### 2. Rastrear Costos

```python
# Embedding cost
pipeline.cost_tracker.track_embedding(
    tokens=150,  # Tokens del question
    question="Tell me about your background"
)

# Generation cost
pipeline.cost_tracker.track_generation(
    input_tokens=2048,
    output_tokens=256,
    cache_write_tokens=1024,  # Si es primera vez
    cache_read_tokens=0,       # O use esto si es cache hit
    question="Tell me about your background"
)
```

### 3. Obtener Reporte

```python
# Obtener reporte agregado
report = pipeline.cost_tracker.get_session_report()

# Acceder a datos
print(f"Total: ${report.total_cost_usd:.4f}")
print(f"Preguntas: {report.questions_processed}")
print(f"Por categoría: {report.costs_by_category}")
```

### 4. Guardar Reporte

```python
# Guardar a JSON en logs/
pipeline.cost_tracker.save_report(report)

# O especificar directorio:
from pathlib import Path
pipeline.cost_tracker.save_report(
    report,
    output_dir=Path("./custom_logs")
)
```

---

## Ejemplo Completo

```python
import asyncio
from src.cost_calculator import CostTracker, estimate_tokens, estimate_embedding_tokens

async def example():
    # 1. Crear tracker
    tracker = CostTracker(session_id="example_session")
    
    # 2. Simular 3 preguntas
    questions = [
        "Tell me about your background",
        "What's your greatest strength?",
        "Describe a challenge you overcame"
    ]
    
    for i, question in enumerate(questions):
        # Embedding
        emb_tokens = estimate_embedding_tokens(question)
        tracker.track_embedding(
            tokens=emb_tokens,
            question=question
        )
        
        # Generation (primera pregunta sin cache, resto con cache)
        if i == 0:
            # Primera: escribe cache
            cache_write = 1024
            cache_read = 0
            input_tokens = 2048
        else:
            # Posteriores: leen cache
            cache_write = 0
            cache_read = 1024
            input_tokens = 1024
        
        output_tokens = estimate_tokens("Sample response text here")
        tracker.track_generation(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
            question=question
        )
    
    # 3. Obtener reporte
    report = tracker.get_session_report()
    report.questions_processed = len(questions)
    report.responses_generated = len(questions)
    
    # 4. Guardar
    tracker.save_report(report)
    
    # 5. Mostrar
    print(f"\n💰 Total Session Cost: ${report.total_cost_usd:.6f}")
    print(f"📊 Questions: {report.questions_processed}")
    print(f"💬 Responses: {report.responses_generated}")
    print(f"📈 Cost per question: ${report.total_cost_usd / report.questions_processed:.6f}")

if __name__ == "__main__":
    asyncio.run(example())
```

---

## Precios Actuales (Q1 2026)

```python
from src.cost_calculator import APIRates

# OpenAI
APIRates.OPENAI_REALTIME_INPUT.value      # $0.020/min
APIRates.OPENAI_EMBEDDING_INPUT.value     # $0.020/1M tokens

# Anthropic Claude
APIRates.CLAUDE_INPUT.value               # $3.00/1M tokens
APIRates.CLAUDE_OUTPUT.value              # $15.00/1M tokens
APIRates.CLAUDE_CACHE_WRITE.value         # $3.75/1M tokens
APIRates.CLAUDE_CACHE_READ.value          # $0.30/1M tokens (90% discount!)
```

---

## Estimación de Tokens

```python
from src.cost_calculator import estimate_tokens, estimate_embedding_tokens

# Estimación general
tokens = estimate_tokens("Your text here")
# Aprox: 1 token cada 4 caracteres

# Embedding específico
emb_tokens = estimate_embedding_tokens("Tell me about your background")
# Rango típico: 50-500 tokens para preguntas
```

---

## Acceder a Costos por Categoría

```python
report = tracker.get_session_report()

# Desglose por categoría
for category, cost in report.costs_by_category.items():
    print(f"{category}: ${cost:.6f}")

# Output esperado:
# embedding: $0.000450
# generation: $0.045600
# cache_write: $0.003750
# cache_read: $0.000120
```

---

## Monitoreo en Vivo (Código sugerido)

```python
# En main.py, agregar a on_transcript o process_question:

async def show_cost_update():
    if pipeline.cost_tracker:
        report = pipeline.cost_tracker.get_session_report()
        logger.info(f"📊 Session cost so far: ${report.total_cost_usd:.6f}")
        
        # Broadcast to teleprompter
        await broadcast_message({
            "type": "cost_update",
            "cost_usd": report.total_cost_usd,
            "questions": report.questions_processed
        })
```

---

## Archivo de Reporte JSON

**Ubicación:** `logs/costs_session_20260301_120000.json`

```json
{
  "session_id": "session_20260301_120000",
  "start_time": "2026-03-01T12:00:00.000000",
  "end_time": "2026-03-01T12:15:30.000000",
  "costs_by_category": {
    "embedding": 0.00045,
    "generation": 0.0456,
    "cache_write": 0.00375,
    "cache_read": 0.00012
  },
  "api_calls_count": {
    "openai_embedding": 3,
    "claude_sonnet": 3
  },
  "metrics": {
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
  }
}
```

---

## Debugging y Logs

```bash
# Ver logs de cost_calculator
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
# Ejecutar main.py
"

# Buscar entradas de costo en logs:
grep -i "cost\|embedding\|generation" logs/interview_*.md
```

---

## Troubleshooting

### Error: `CostTracker not initialized`
```python
# Solución: Asegúrate de inicializar en start_pipeline()
pipeline.cost_tracker = CostTracker(session_id=session_id)
```

### Costo = 0
```python
# Verificar que track_* se está llamando con valores > 0
print(pipeline.cost_tracker.entries)  # Ver todas las entradas
```

### No se guarda el reporte
```python
# Asegúrate que logs/ existe:
from pathlib import Path
Path("logs").mkdir(exist_ok=True)

# O especificar output_dir explícitamente
tracker.save_report(report, output_dir=Path("logs"))
```

---

## Próximas Características (Roadmap)

- [ ] Tracking de transcripción (requiere duración precisa de audio)
- [ ] Exportar a CSV/Excel
- [ ] Dashboard de costos en tiempo real
- [ ] Alertas cuando se excede presupuesto
- [ ] Integración con Prometheus
- [ ] Análisis histórico de múltiples sesiones

---

**Módulo:** `src/cost_calculator.py`  
**Status:** ✅ OPERACIONAL  
**Última actualización:** 1 Marzo 2026

