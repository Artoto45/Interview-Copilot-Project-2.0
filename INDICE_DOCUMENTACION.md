# 📑 ÍNDICE DE DOCUMENTACIÓN — Interview Copilot v4.0

**Bienvenido.** Este proyecto incluye documentación completa para entender, usar y mantener el Interview Copilot.

---

## 🎯 COMIENZA AQUÍ

### Para Usuarios Nuevos:
1. **[README_GITHUB.md](README_GITHUB.md)** — Overview del proyecto (5 min read)
2. **[INSTRUCCIONES_PUSH_GITHUB.md](INSTRUCCIONES_PUSH_GITHUB.md)** — Cómo descargar y ejecutar (10 min)

### Para Desarrolladores:
1. **[DOCUMENTACION_TECNICA_COMPLETA.md](DOCUMENTACION_TECNICA_COMPLETA.md)** — Deep dive técnico (30-60 min)
2. **[GUIA_SEGURIDAD_GITHUB.md](GUIA_SEGURIDAD_GITHUB.md)** — Seguridad y privacidad

---

## 📚 DOCUMENTACIÓN COMPLETA

### 1. README_GITHUB.md
**¿Qué es?** Descripción de alto nivel del proyecto  
**Para quién?** Todos (usuarios, desarrolladores, interesados)  
**Contiene:**
- Overview del proyecto
- Quick start guide (instalación en 5 min)
- Setup de Knowledge Base
- Architecture diagram
- Cost tracking
- Troubleshooting
- Logging examples
- Contributing guidelines

**Leer si:** Quieres saber qué es Interview Copilot y cómo usarlo

---

### 2. DOCUMENTACION_TECNICA_COMPLETA.md
**¿Qué es?** Referencia técnica exhaustiva (4,500+ líneas)  
**Para quién?** Desarrolladores, arquitectos  
**Contiene:**
- Descripción general completa
- Arquitectura del sistema (diagrama detallado)
- Diagrama de flujo (pregunta a respuesta)
- 11 módulos individuales:
  - Audio Capture Agent
  - OpenAI Realtime Transcriber
  - Deepgram Nova-3 Transcriber
  - Question Filter
  - Question Classifier
  - Knowledge Retrieval (RAG)
  - Response Generation (GPT-4o-mini)
  - Cost Tracker & Calculator
  - Session Metrics & Prometheus
  - Alert Manager
  - Teleprompter (PyQt5)
- Requisitos y dependencias
- Desglose de latencias (ms)
- Flujo de información con timings
- Optimizaciones implementadas
- Instrucciones de ejecución
- Logs y reportes de ejemplo

**Cada módulo incluye:**
- Archivo source
- Propósito
- Entradas y salidas
- Latencia actual
- Código comentado (key functions)
- Ejemplo de uso
- Costos API
- Requisitos

**Leer si:** Quieres entender cómo funciona internamente cada componente

---

### 3. GUIA_SEGURIDAD_GITHUB.md
**¿Qué es?** Checklist de seguridad y privacidad  
**Para quién?** Antes de hacer push a GitHub  
**Contiene:**
- Qué información NUNCA debe estar en GitHub
  - Credenciales (.env)
  - Información personal
  - Datos de negocio
  - Información sensible de empresas
- Qué información SÍ puede estar
- Instrucciones de .gitignore
- Template de .env.example
- Checklist pre-push (7 items)
- Instrucciones para clonar seguro
- Medidas de seguridad en código
- Qué incluir en README
- Procedimiento de emergencia si se expone un secret
- Referencias de mejores prácticas

**Leer si:** Vas a subir el proyecto a GitHub (CRÍTICO)

---

### 4. INSTRUCCIONES_PUSH_GITHUB.md
**¿Qué es?** Guía paso a paso para push seguro  
**Para quién?** Antes de hacer push a GitHub  
**Contiene:**
- Checklist pre-push (obligatorio)
- Verificación de .gitignore
- Verificación de archivos sensibles
- Búsqueda de secrets
- 2 métodos de push:
  - Automatizado (script)
  - Manual (control total)
- Verificación final (crítica)
- Scripts bash para automatizar
- Qué debe verse en GitHub (estructura)
- Verificación en GitHub UI
- Procedimientos de emergencia
- Test post-push
- Comando final

**Leer si:** Estás a punto de hacer push a GitHub

---

### 5. push_safe_to_github.py
**¿Qué es?** Script automatizado de verificación  
**Para quién?** Antes de push  
**Hace:**
```bash
python push_safe_to_github.py --check    # Solo verificar
python push_safe_to_github.py --push     # Verificar + push
python push_safe_to_github.py --force    # Push sin verificación (⚠️)
```

**Verifica:**
- ✅ .gitignore completo
- ✅ .env NO en staging
- ✅ No hay secrets en código
- ✅ logs/ no está en staging
- ✅ Cambios en staging

---

## 🗂️ ESTRUCTURA DE ARCHIVOS

```
Interview-Copilot-Project/
│
├── main.py
│   └── Entry point — Orquestador async principal
│
├── src/
│   ├── audio/capture.py
│   │   └── Captura dual de audio (Voicemeeter)
│   ├── transcription/
│   │   ├── openai_realtime.py
│   │   │   └── Transcripción OpenAI (usuario)
│   │   ├── deepgram_transcriber.py
│   │   │   └── Transcripción Deepgram (entrevistador)
│   │   └── deepgram_client.py
│   ├── knowledge/
│   │   ├── retrieval.py
│   │   │   └── Búsqueda semántica (ChromaDB)
│   │   ├── classifier.py
│   │   │   └── Clasificación de preguntas
│   │   ├── question_filter.py
│   │   │   └── Filtro de ruido (rule-based)
│   │   └── ingest.py
│   │       └── Ingestión de KB
│   ├── response/
│   │   ├── openai_agent.py
│   │   │   └── Generación GPT-4o-mini
│   │   ├── claude_agent.py
│   │   │   └── Generación Claude (opcional)
│   │   └── gemini_agent.py
│   │       └── Generación Gemini (opcional)
│   ├── teleprompter/
│   │   ├── qt_display.py
│   │   │   └── PyQt5 UI
│   │   ├── ws_bridge.py
│   │   │   └── WebSocket bridge
│   │   └── progress_tracker.py
│   │       └── Tracking de progreso
│   ├── metrics.py
│   │   └── SessionMetrics, QuestionMetrics
│   ├── cost_calculator.py
│   │   └── CostTracker, CostReport
│   ├── alerting.py
│   │   └── AlertManager (SLOs)
│   ├── prometheus.py
│   │   └── Prometheus export
│   └── __init__.py
│
├── tests/
│   ├── test_*.py
│   └── conftest.py
│
├── kb/  (git-ignored)
│   ├── personal/  (tu contenido personal)
│   │   ├── about_you.md
│   │   ├── strengths.md
│   │   └── experience.md
│   └── company/
│       └── company_research.md
│
├── logs/  (git-ignored)
│   ├── interview_*.md
│   ├── costs_*.json
│   └── metrics_*.json
│
├── chroma_data/  (git-ignored)
│   ├── chroma.sqlite3
│   └── [embeddings]
│
├── requirements.txt
│   └── Todas las dependencias
│
├── .env.example
│   └── Template (COPIAR a .env local)
│
├── .gitignore
│   └── Archivos excluidos de git
│
├── README_GITHUB.md
│   └── README principal (para GitHub)
│
├── DOCUMENTACION_TECNICA_COMPLETA.md
│   └── Guía técnica exhaustiva
│
├── GUIA_SEGURIDAD_GITHUB.md
│   └── Checklist de seguridad
│
├── INSTRUCCIONES_PUSH_GITHUB.md
│   └── Guía de push seguro
│
├── push_safe_to_github.py
│   └── Script de verificación automatizada
│
└── INDICE_DOCUMENTACION.md
    └── Este archivo
```

---

## 🚀 FLUJOS DE TRABAJO

### Flujo 1: "Quiero entender qué es esto"
1. Lee [README_GITHUB.md](README_GITHUB.md) (5 min)
2. Mira diagrama de arquitectura en README
3. Continuado: Lee [DOCUMENTACION_TECNICA_COMPLETA.md](DOCUMENTACION_TECNICA_COMPLETA.md) sección "Arquitectura"

### Flujo 2: "Quiero instalarlo y usarlo"
1. Lee [README_GITHUB.md](README_GITHUB.md) sección "Quick Start"
2. Sigue [INSTRUCCIONES_PUSH_GITHUB.md](INSTRUCCIONES_PUSH_GITHUB.md) para clonar
3. Crea tu .env local (copia .env.example)
4. Crea tu kb/ personal
5. Ejecuta: `python main.py`

### Flujo 3: "Quiero entender el código"
1. Lee [DOCUMENTACION_TECNICA_COMPLETA.md](DOCUMENTACION_TECNICA_COMPLETA.md)
2. Para cada módulo:
   - Abre el archivo source en `src/`
   - Lee la sección en documentación
   - Entiende entradas/salidas
   - Revisa latencia y costos

### Flujo 4: "Voy a hacer push a GitHub"
1. Abre [GUIA_SEGURIDAD_GITHUB.md](GUIA_SEGURIDAD_GITHUB.md)
2. Sigue el checklist de 7 items
3. Abre [INSTRUCCIONES_PUSH_GITHUB.md](INSTRUCCIONES_PUSH_GITHUB.md)
4. Ejecuta `python push_safe_to_github.py --check`
5. Si OK: ejecuta `python push_safe_to_github.py --push`

### Flujo 5: "Tengo un problema"
1. Busca en [README_GITHUB.md](README_GITHUB.md) sección "Troubleshooting"
2. Si no está: busca en [DOCUMENTACION_TECNICA_COMPLETA.md](DOCUMENTACION_TECNICA_COMPLETA.md)
3. Si aún no: abre un GitHub Issue con detalles

---

## 📊 ESTADÍSTICAS DE DOCUMENTACIÓN

| Documento | Líneas | Palabras | Lectura |
|-----------|--------|----------|---------|
| README_GITHUB.md | ~450 | ~3,200 | 10-15 min |
| DOCUMENTACION_TECNICA_COMPLETA.md | ~4,500 | ~25,000 | 60-90 min |
| GUIA_SEGURIDAD_GITHUB.md | ~550 | ~4,000 | 15-20 min |
| INSTRUCCIONES_PUSH_GITHUB.md | ~800 | ~5,500 | 20-30 min |
| **TOTAL** | **~6,300** | **~37,700** | **2-3 horas** |

---

## 🔍 BÚSQUEDA RÁPIDA

### "¿Cómo instalo el proyecto?"
→ [README_GITHUB.md — Quick Start](README_GITHUB.md#-quick-start)

### "¿Cómo funciona internamente?"
→ [DOCUMENTACION_TECNICA_COMPLETA.md — Arquitectura](DOCUMENTACION_TECNICA_COMPLETA.md#arquitectura-del-sistema)

### "¿Qué datos sensibles no debo subir?"
→ [GUIA_SEGURIDAD_GITHUB.md — Información Sensible](GUIA_SEGURIDAD_GITHUB.md#-información-sensible-que-no-debe-estar-en-github)

### "¿Cómo hago push seguro?"
→ [INSTRUCCIONES_PUSH_GITHUB.md — Pasos de Push](INSTRUCCIONES_PUSH_GITHUB.md#-pasos-de-push-paso-a-paso)

### "¿Cuál es el costo?"
→ [README_GITHUB.md — Cost Tracking](README_GITHUB.md#-cost-tracking) O
→ [DOCUMENTACION_TECNICA_COMPLETA.md — Latencias y Rendimiento](DOCUMENTACION_TECNICA_COMPLETA.md#latencias-y-rendimiento)

### "¿Cómo configuro Voicemeeter?"
→ [README_GITHUB.md — Configuration](README_GITHUB.md#configuración) O
→ [DOCUMENTACION_TECNICA_COMPLETA.md — Audio Capture Agent](DOCUMENTACION_TECNICA_COMPLETA.md#1-audio-capture-agent)

### "¿Cómo creo la Knowledge Base?"
→ [README_GITHUB.md — Knowledge Base Setup](README_GITHUB.md#-knowledge-base-setup)

### "¿Cómo soluciono problemas?"
→ [README_GITHUB.md — Troubleshooting](README_GITHUB.md#️-troubleshooting)

### "¿Cuál es la latencia de cada módulo?"
→ [DOCUMENTACION_TECNICA_COMPLETA.md — Latencias por Componente](DOCUMENTACION_TECNICA_COMPLETA.md#desglose-de-latencias-por-componente)

### "¿Cómo funcionan las optimizaciones?"
→ [DOCUMENTACION_TECNICA_COMPLETA.md — Optimizaciones Especulativas](DOCUMENTACION_TECNICA_COMPLETA.md#optimization-3-speculative-generation-implementado)

---

## ✨ PRÓXIMOS PASOS

### Ahora Mismo:
- [ ] Lee README_GITHUB.md (10 min)
- [ ] Abre requirements.txt y revisa dependencias
- [ ] Abre .env.example y entiende las variables

### Antes de Usar:
- [ ] Instala Voicemeeter Banana
- [ ] Obtén API keys (OpenAI, Deepgram)
- [ ] Copia .env.example a .env
- [ ] Crea directorio kb/personal
- [ ] Instala dependencias: `pip install -r requirements.txt`

### Antes de Hacer Push:
- [ ] Lee GUIA_SEGURIDAD_GITHUB.md
- [ ] Lee INSTRUCCIONES_PUSH_GITHUB.md
- [ ] Ejecuta `python push_safe_to_github.py --check`
- [ ] Si OK, ejecuta `python push_safe_to_github.py --push`

### Para Desarrollo Futuro:
- [ ] Lee DOCUMENTACION_TECNICA_COMPLETA.md
- [ ] Abre cada archivo en src/ y estudia código
- [ ] Lee tests/ para entender patterns
- [ ] Identifica mejoras/optimizaciones

---

## 🆘 SOPORTE

**Si estás atascado:**

1. **Revisa la documentación** relevante (arriba ↑)
2. **Busca en GitHub Issues:** https://github.com/artoto45-ship-it/Interview-Copilot-Project/issues
3. **Crea un GitHub Issue** con:
   - Descripción clara del problema
   - Pasos para reproducir
   - Error messages (completos)
   - Tu setup (OS, Python version, etc.)

---

## 📝 CAMBIOS Y ACTUALIZACIONES

**Última actualización:** 1 de Marzo, 2026  
**Versión:** Interview Copilot v4.0

Mantén esta documentación actualizada cuando:
- Cambies un módulo
- Agregues dependencias
- Cambies arquitectura
- Descubras un bug importante

---

## 🎓 APRENDER MÁS

**Conceptos clave para entender el proyecto:**

- **Async/Await (Python)** — El pipeline es 100% async
- **WebSocket API** — Comunicación tiempo real
- **Vector Embeddings** — Búsqueda semántica
- **RAG (Retrieval-Augmented Generation)** — Combinación KB + LLM
- **Streaming APIs** — Respuestas en tiempo real
- **Cost Optimization** — Multi-API strategy

Recursos:
- Python asyncio: https://docs.python.org/3/library/asyncio.html
- ChromaDB docs: https://docs.trychroma.com/
- OpenAI Realtime: https://platform.openai.com/docs/guides/realtime
- Deepgram SDK: https://developers.deepgram.com/

---

**¡Bienvenido al Interview Copilot!** 🚀

Comienza por [README_GITHUB.md](README_GITHUB.md) y diviértete.

