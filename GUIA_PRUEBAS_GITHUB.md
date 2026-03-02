# Guía de Pruebas - Interview Copilot v4.0 desde GitHub
**Versión:** 1.0
**Fecha:** 01 de Marzo, 2026

---

## 📋 Checklist Pre-Pruebas

Antes de ejecutar el sistema, verifica estos puntos:

- [ ] Python 3.10+ instalado
- [ ] pip/conda funcional
- [ ] Conexión a Internet estable
- [ ] Acceso a APIs (OpenAI, Gemini)
- [ ] Micrófono funcional
- [ ] Voicemeeter instalado (para audio dual)
- [ ] Qt5+ instalado (para teleprompter)

---

## 🚀 Inicio Rápido

### Paso 1: Descarga la Versión Más Reciente
```bash
# Si aún no la tienes
git clone https://github.com/artoto45-ship-it/Interview-Copilot-Project.git
cd Interview-Copilot-Project
```

### Paso 2: Crea un Entorno Virtual
```bash
# Windows
python -m venv venv
.\venv\Scripts\Activate.ps1

# Linux/macOS
python3 -m venv venv
source venv/bin/activate
```

### Paso 3: Instala Dependencias
```bash
pip install -r requirements.txt
```

### Paso 4: Configura Variables de Entorno
Crea un archivo `.env` en la raíz del proyecto:
```env
# ============================================================
# OPENAI API
# ============================================================
OPENAI_API_KEY=sk-proj-...
OPENAI_MODEL=gpt-4o-mini

# ============================================================
# GEMINI API
# ============================================================
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-2.0-flash-exp

# ============================================================
# DEEPGRAM (para transcripción alternativa)
# ============================================================
DEEPGRAM_API_KEY=...

# ============================================================
# AUDIO SETTINGS
# ============================================================
AUDIO_DEVICE_USER=VB-Audio Virtual Cable B2
AUDIO_DEVICE_INT=VB-Audio Virtual Cable B1
SAMPLE_RATE=16000
CHUNK_SIZE=1024

# ============================================================
# KNOWLEDGE BASE
# ============================================================
KB_PATH=./kb
CHROMA_DB_PATH=./chroma_data

# ============================================================
# RESPONSE SETTINGS
# ============================================================
THINKING_BUDGET_BEHAVIORAL=3000
THINKING_BUDGET_TECHNICAL=5000
THINKING_BUDGET_SITUATIONAL=2000

# ============================================================
# PERFORMANCE
# ============================================================
CACHE_ENABLED=true
PROMETHEUS_ENABLED=true
METRICS_PORT=8000

# ============================================================
# LOGGING
# ============================================================
LOG_LEVEL=INFO
LOG_DIR=./logs
```

### Paso 5: Ejecuta el Sistema
```bash
python main.py
```

---

## 🧪 Modo de Prueba - Diferentes Escenarios

### Modo 1: Prueba Básica (Sin Audio)
```bash
# Para probar sin hardware de audio
python main.py --no-audio --test-questions
```

### Modo 2: Prueba con Preguntas Simuladas
Crea un archivo `test_questions.txt`:
```
What are your top 5 strengths?
Tell me about a challenging project you led.
How do you handle conflicts with team members?
What's your experience with cloud technologies?
Describe your leadership approach.
```

Luego:
```bash
python main.py --test-file test_questions.txt
```

### Modo 3: Prueba de Latencia
```bash
python main.py --benchmark
```
Esto ejecutará las preguntas y reportará tiempos de respuesta.

### Modo 4: Prueba de Costo
```bash
python main.py --cost-analysis
```
Mostrará estimación de costos por pregunta.

---

## 📊 Validación Post-Ejecución

### 1. Verifica Logs Generados
```bash
# Última sesión de entrevista
cat logs/interview_*.md

# Métricas de desempeño
cat logs/metrics_session_*.json

# Costos acumulados
cat logs/costs_session_*.json
```

### 2. Revisa Prometheus (si está activo)
Abre en navegador: `http://localhost:8000/metrics`

Métricas clave a revisar:
- `response_latency_seconds` - Tiempo de respuesta
- `cache_hit_rate` - Tasa de éxito del caché
- `question_count` - Número de preguntas procesadas
- `kb_retrieval_duration_seconds` - Tiempo de recuperación KB

### 3. Analiza Resultados
```bash
# Ver estadísticas de la sesión
python -c "from src.metrics import SessionMetrics; 
           m = SessionMetrics.load('logs/metrics_session_*.json'); 
           print(m.summary())"
```

---

## 🔍 Troubleshooting Común

### Error: "No module named 'websockets'"
```bash
pip install websockets
```

### Error: "OPENAI_API_KEY not found"
Verifica que el archivo `.env` existe en la raíz del proyecto y contiene la clave.

### Error: "No audio devices found"
- Instala Voicemeeter Virtual Audio Cable
- Configura los dispositivos en `.env`
- Verifica que Voicemeeter está activo

### Error: "Connection timeout to Gemini API"
- Verifica tu conexión a Internet
- Valida que la API key de Gemini es correcta
- Revisa la cuota de uso en Google Cloud Console

### Error: "Qt application not found"
```bash
pip install PyQt5
```

### Desempeño lento
1. Reduce el `THINKING_BUDGET` en `.env`
2. Disminuye `SAMPLE_RATE` a 8000
3. Habilita el cache: `CACHE_ENABLED=true`
4. Usa `gpt-4o-mini` en lugar de `gpt-4`

---

## ⚙️ Configuración Avanzada

### Optimizaciones de Desempeño

```env
# Caché de Prompt
PROMPT_CACHING=true

# Especulación de Respuestas
SPECULATIVE_GENERATION=true

# Recuperación KB Paralela
PARALLEL_KB_RETRIEVAL=true

# Timeout máximo de respuesta (segundos)
RESPONSE_TIMEOUT=30

# Buffer de tokens para streaming
STREAM_BUFFER_SIZE=10
```

### Alertas y Monitoreo

```env
# Alertas si latencia > 5 segundos
ALERT_LATENCY_THRESHOLD=5000

# Alertas si costo > $10 por sesión
ALERT_COST_THRESHOLD=10

# Alertas si tasa de error > 10%
ALERT_ERROR_RATE=0.1

# Email para notificaciones (opcional)
ALERT_EMAIL=tu_email@example.com
```

---

## 📈 Métricas de Éxito

Después de ejecutar algunas pruebas, deberías ver:

| Métrica | Objetivo | Actual |
|---------|----------|--------|
| Latencia P50 (mediana) | < 2 segundos | - |
| Latencia P95 | < 5 segundos | - |
| Latencia P99 | < 10 segundos | - |
| Tasa de Cache Hit | > 30% | - |
| Precisión de Clasificación | > 95% | - |
| Disponibilidad del Sistema | > 99% | - |
| Costo por Pregunta | < $0.05 | - |

---

## 🐛 Modo Debug

Para debugging detallado:

```bash
# Debug máximo
LOG_LEVEL=DEBUG python main.py

# Con profiling de CPU
python -m cProfile -o profile_stats.prof main.py
python -m pstats profile_stats.prof

# Con Memory Profiling
pip install memory-profiler
python -m memory_profiler main.py

# Con tracing distribuido
TRACE_ENABLED=true python main.py
```

---

## 📝 Reportar Problemas

Si encuentras un problema:

1. **Recopila información:**
   ```bash
   # Versión de Python
   python --version
   
   # Versiones de dependencias
   pip list
   
   # Logs de error
   cat logs/interview_*.md
   cat logs/metrics_*.json
   ```

2. **Abre un Issue en GitHub:**
   - Descripción clara del problema
   - Pasos para reproducir
   - Logs relevantes (sin datos sensibles)
   - Entorno (Python version, OS, etc.)

3. **Contacta al equipo:**
   - GitHub Issues: https://github.com/artoto45-ship-it/Interview-Copilot-Project/issues
   - Email: artoto45@gmail.com

---

## 🎯 Próximos Pasos

Después de pruebas exitosas:

1. **Integración con sistemas reales**
   - Conecta a tu plataforma de entrevistas
   - Sincroniza con base de datos de candidatos

2. **Entrenamiento de modelos**
   - Personaliza el sistema para tu empresa
   - Entrena clasificadores específicos

3. **Deployment en producción**
   - Containeriza con Docker
   - Despliega en cloud (AWS, GCP, Azure)

4. **Monitoreo continuo**
   - Configura alertas en producción
   - Analiza métricas regularmente

---

## 📚 Documentación Adicional

- [README.md](./README.md) - Descripción general del proyecto
- [Arquitectura del Sistema](./ANALISIS_TECNICO_COMPLETO.md) - Detalles técnicos
- [Guía de RAG](./KB/CUESTIONARIO_KB.md) - Retrieval & Generation
- [Costos y Presupuesto](./COST_CALCULATOR_DOCS.md) - Análisis de costos

---

**Última actualización:** 01 de Marzo, 2026
**Versión:** Interview Copilot v4.0
**Status:** Listo para Pruebas

