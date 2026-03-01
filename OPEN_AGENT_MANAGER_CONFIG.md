# 🚀 CONFIGURACIÓN OPEN AGENT MANAGER
## Interview Copilot v2.0 — Ejecución Automática

**Fecha:** 1 Marzo 2026  
**Plataforma:** Antigravity (Google) + Claude Opus 4.6  
**Propósito:** Automatizar mejora de código usando Extended Thinking  

---

## 📋 CONFIGURATION JSON

Este JSON debe ser ingresado al panel de control del **Open Agent Manager** de Antigravity:

```json
{
  "project": {
    "name": "Interview Copilot v2.0 — Code Improvement",
    "description": "Automated code improvements guided by Claude Opus 4.6 with Extended Thinking",
    "repository": "file:///C:/Users/artot/OneDrive/Desktop/Carpeta_Proyecto_Desarrollo_Software/Interview_Proyect/Nueva_Versión_2.0",
    "language": "python",
    "python_version": "3.11+"
  },
  
  "agent_config": {
    "model": "claude-opus-4-6-20250514",
    "enable_extended_thinking": true,
    "thinking_budget_tokens": 20000,
    "max_tokens": 8000,
    "temperature": 0.3,
    
    "capabilities": [
      "code_analysis",
      "code_generation",
      "testing",
      "performance_optimization",
      "security_audit"
    ],
    
    "constraints": [
      "no_breaking_changes",
      "maintain_backward_compatibility",
      "require_test_coverage_>85",
      "no_external_dependencies_unless_approved"
    ],
    
    "approval_gates": [
      "before_phase_2",
      "before_production_deploy"
    ]
  },
  
  "roadmap": {
    "total_phases": 4,
    "total_estimated_hours": 8.5,
    "budget_thinking_tokens": 80000,
    
    "phases": [
      {
        "phase_number": 1,
        "name": "Stability & Critical Fixes",
        "estimated_hours": 2.0,
        "estimated_thinking_tokens": 20000,
        "priority": "CRITICAL",
        
        "tasks": [
          {
            "task_id": "1.1.1",
            "name": "Sincronización de Variables Especulativas",
            "file": "main.py",
            "description": "Fix race conditions en _speculative_gen_task",
            "lines_to_modify": [108, 112, 227, 281],
            "estimated_minutes": 30,
            "thinking_minutes": 5,
            "success_criteria": [
              "No asyncio.Lock() warnings",
              "All direct accesses via SpeculativeState",
              "5+ test runs without crashes"
            ],
            "test_command": "pytest tests/ -k speculative -v",
            "fallback_strategy": "Rollback to git commit if tests fail"
          },
          {
            "task_id": "1.1.2",
            "name": "Timeout en Response Generation",
            "file": "main.py",
            "description": "Implement 30s timeout para evitar UI freeze indefinido",
            "lines_to_modify": [365],
            "estimated_minutes": 20,
            "thinking_minutes": 5,
            "success_criteria": [
              "asyncio.timeout(30) wrapped",
              "TimeoutError caught and logged",
              "Teleprompter receives [Response timeout] message"
            ],
            "test_command": "timeout 35 python main.py 2>&1 | grep -i timeout",
            "fallback_strategy": "Try-catch fallback with empty response"
          },
          {
            "task_id": "1.1.3",
            "name": "Acceso a Atributo Privado",
            "file": "src/transcription/openai_realtime.py",
            "description": "Agregar getter público para _live_buffer",
            "lines_to_modify": [165],
            "estimated_minutes": 15,
            "thinking_minutes": 3,
            "success_criteria": [
              "get_live_buffer() method exists",
              "main.py uses public method",
              "No direct _live_buffer access"
            ],
            "test_command": "grep '_live_buffer' main.py | grep -v 'get_live_buffer' && echo FAIL || echo PASS",
            "fallback_strategy": "Add deprecation warning to _live_buffer"
          },
          {
            "task_id": "1.2.1",
            "name": "Teleprompter Healthcheck",
            "file": "main.py",
            "description": "Monitor subprocess + auto-restart (max 3x)",
            "lines_to_modify": [604],
            "estimated_minutes": 15,
            "thinking_minutes": 4,
            "success_criteria": [
              "monitor_teleprompter_health() created",
              "Max 3 restart attempts",
              "Logs show health transitions"
            ],
            "test_command": "timeout 65 python main.py 2>&1 | grep -i monitor | head -3",
            "fallback_strategy": "Log error and continue without UI"
          },
          {
            "task_id": "1.2.2",
            "name": "Retry Logic con Exponential Backoff",
            "file": "main.py",
            "description": "Implementar retry_with_backoff() para API calls transientes",
            "lines_to_modify": [350],
            "estimated_minutes": 15,
            "thinking_minutes": 3,
            "success_criteria": [
              "retry_with_backoff() async function exists",
              "Delays: 1s, 2s, 4s tested",
              "Logs show each attempt"
            ],
            "test_command": "grep 'retry_with_backoff' main.py | wc -l",
            "fallback_strategy": "Return None if all retries exhausted"
          }
        ],
        
        "phase_validation": {
          "command": "bash scripts/validate_phase1.sh",
          "criteria": {
            "all_tests_pass": true,
            "crash_count_in_5_runs": 0,
            "pylint_E_warnings": 0,
            "asyncio_warnings": 0
          },
          "human_approval_required": false
        }
      },
      
      {
        "phase_number": 2,
        "name": "Performance Optimization",
        "estimated_hours": 2.0,
        "estimated_thinking_tokens": 20000,
        "priority": "HIGH",
        "depends_on": ["phase_1_validation_passed"],
        
        "tasks": [
          {
            "task_id": "2.1.1",
            "name": "Semantic Similarity para Speculative Hit",
            "file": "main.py",
            "description": "Use embeddings para cambiar 65% → 80% threshold",
            "lines_to_modify": [281],
            "estimated_minutes": 60,
            "thinking_minutes": 10,
            "success_criteria": [
              "is_similar_enough_semantic() implemented",
              "Threshold changed to 0.80",
              "Speculative hit rate maintained >50%",
              "False positives reduced"
            ],
            "test_command": "python -c 'from main import is_similar_enough_semantic; print(\"OK\")'",
            "fallback_strategy": "Keep 65% threshold if embedding API unavailable"
          },
          {
            "task_id": "2.2.1",
            "name": "Compound Question Detection",
            "file": "src/knowledge/classifier.py",
            "description": "Mejorar detección de compound questions con regex + stemming",
            "lines_to_modify": [83],
            "estimated_minutes": 30,
            "thinking_minutes": 6,
            "success_criteria": [
              ">95% de compound questions detectadas",
              "Presupuestos ajustados correctamente",
              "test_compound passes"
            ],
            "test_command": "pytest tests/test_question_filter.py::test_compound -v",
            "fallback_strategy": "Use fallback_classify() si falla"
          },
          {
            "task_id": "2.2.2",
            "name": "Interview Signals Fuzzy Matching",
            "file": "src/knowledge/question_filter.py",
            "description": "Implementar fuzzy matching con stemming",
            "lines_to_modify": [45],
            "estimated_minutes": 30,
            "thinking_minutes": 5,
            "success_criteria": [
              "has_interview_signal_fuzzy() implemented",
              ">95% recall on real questions",
              "<5% false positives",
              "Latencia <10ms"
            ],
            "test_command": "pytest tests/test_question_filter.py -v --tb=short",
            "fallback_strategy": "Keep direct string matching if fuzzy too slow"
          }
        ],
        
        "phase_validation": {
          "command": "bash scripts/validate_phase2.sh",
          "criteria": {
            "p95_latency_ms": 5000,
            "cache_hit_rate": 0.75,
            "all_tests_pass": true
          },
          "human_approval_required": true,
          "approval_criteria": "P95 latency < 5s confirmed in 10-question session"
        }
      },
      
      {
        "phase_number": 3,
        "name": "Quality & KB Improvement",
        "estimated_hours": 2.0,
        "estimated_thinking_tokens": 15000,
        "priority": "MEDIUM",
        "depends_on": ["phase_2_validation_passed"],
        
        "tasks": [
          {
            "task_id": "3.1.1",
            "name": "Chunk Validation & Deduplication",
            "file": "src/knowledge/ingest.py",
            "description": "Rechazar chunks <20 chars, deduplicar al re-ingest",
            "lines_to_modify": [112, 140],
            "estimated_minutes": 60,
            "thinking_minutes": 8,
            "success_criteria": [
              "Chunks <20 chars rechazados",
              "Re-ingest no crea duplicatas",
              "ChromaDB.count() válido",
              "test_ingest passes"
            ],
            "test_command": "pytest tests/test_knowledge.py::test_ingest -v",
            "fallback_strategy": "Log and skip invalid chunks"
          },
          {
            "task_id": "3.2.1",
            "name": "Prompt Caching Audit",
            "file": "src/response/claude_agent.py",
            "description": "Track cache hits/misses, mejorar warmup",
            "lines_to_modify": [141, 161],
            "estimated_minutes": 60,
            "thinking_minutes": 10,
            "success_criteria": [
              "Cache hit rate > 75% después 3 preguntas",
              "Cache stats exportados",
              "Warmup usa exact system prompt",
              "test_cache_hit passes"
            ],
            "test_command": "pytest tests/test_response.py::test_cache -v",
            "fallback_strategy": "Fall back to non-cached generation if benchmark fails"
          }
        ],
        
        "phase_validation": {
          "command": "bash scripts/validate_phase3.sh",
          "criteria": {
            "cache_hit_rate": 0.75,
            "test_coverage": 0.85,
            "hallucination_rate": 0.01,
            "kb_duplicate_count": 0
          },
          "human_approval_required": false
        }
      },
      
      {
        "phase_number": 4,
        "name": "Observability & Production Readiness",
        "estimated_hours": 2.5,
        "estimated_thinking_tokens": 15000,
        "priority": "MEDIUM",
        "depends_on": ["phase_3_validation_passed"],
        
        "tasks": [
          {
            "task_id": "4.1.1",
            "name": "Session Metrics & Logging",
            "file": "src/metrics.py",
            "description": "Crear SessionMetrics dataclass, exportar JSON",
            "lines_to_modify": ["new_file"],
            "estimated_minutes": 60,
            "thinking_minutes": 8,
            "success_criteria": [
              "SessionMetrics exported to JSON",
              "Logs include timestamps",
              "Metrics per question type",
              "test_metrics passes"
            ],
            "test_command": "python -c 'from src.metrics import SessionMetrics; print(\"OK\")'",
            "fallback_strategy": "Use logging-only if JSON export fails"
          },
          {
            "task_id": "4.1.2",
            "name": "Alerting & SLOs",
            "file": "src/alerting.py",
            "description": "Alert manager para P95 latency, cache hit rate",
            "lines_to_modify": ["new_file"],
            "estimated_minutes": 60,
            "thinking_minutes": 5,
            "success_criteria": [
              "AlertManager class exists",
              "P95 > 5s triggers warning",
              "Cache hit rate < 60% triggers alert",
              "test_alerting passes"
            ],
            "test_command": "pytest tests/test_alerting.py -v",
            "fallback_strategy": "Log-only alerts if integration unavailable"
          }
        ],
        
        "phase_validation": {
          "command": "bash scripts/validate_phase4.sh",
          "criteria": {
            "metrics_exported": true,
            "prometheus_scrape_ok": true,
            "slos_met": true,
            "uptime_percentage": 99.0
          },
          "human_approval_required": true,
          "approval_criteria": "All metrics visible in Prometheus, SLOs met for 24h"
        }
      }
    ]
  },
  
  "deployment_config": {
    "strategy": "staged_rollout",
    "stages": [
      {
        "stage": "canary",
        "traffic_percentage": 10,
        "duration_hours": 6,
        "rollback_condition": "error_rate > 5% OR p95_latency > 7000ms"
      },
      {
        "stage": "beta",
        "traffic_percentage": 50,
        "duration_hours": 12,
        "rollback_condition": "hallucination_rate > 2% OR uptime < 99%"
      },
      {
        "stage": "production",
        "traffic_percentage": 100,
        "duration_hours": null,
        "rollback_condition": "p95_latency > 7s"
      }
    ]
  },
  
  "success_metrics": {
    "global_targets": {
      "p95_latency_ms": 5000,
      "cache_hit_rate": 0.80,
      "test_coverage_percent": 85,
      "uptime_percent": 99.5,
      "hallucination_rate": 0.01
    },
    "measurement_method": "automated_benchmarks",
    "measurement_frequency_minutes": 60,
    "dashboard_url": "http://localhost:3000/dashboards/interview-copilot"
  },
  
  "thinking_directives": {
    "per_task": {
      "analyze_phase": "5_minutes",
      "plan_phase": "5_minutes",
      "implement_phase": "20_minutes",
      "test_phase": "10_minutes",
      "validate_phase": "5_minutes"
    },
    "instructions": [
      "For each task, start with ANALYZE phase — think deeply about the problem",
      "Consider edge cases and rollback strategies",
      "Implement minimal changes (DRY principle)",
      "Write comprehensive tests before considering task complete",
      "Log all decisions and rationale for human review",
      "Use try-catch with proper fallbacks",
      "Validate against success criteria before moving to next task"
    ]
  },
  
  "git_config": {
    "auto_commit": false,
    "commit_per_task": true,
    "commit_message_template": "[PHASE-X] Task X.Y.Z: {task_name}\n\n{description}\n\nSuccess criteria met:\n- {criteria1}\n- {criteria2}",
    "push_to_branch": "feature/ai-improvements",
    "create_pull_request": true,
    "pr_description_template": "Automated improvement by Claude Opus 4.6\n\nPhase: {phase}\nTasks completed: {task_list}\nValidation: {validation_status}\n\nFixes:\n{fixes_list}"
  },
  
  "monitoring": {
    "enable_logging": true,
    "log_level": "INFO",
    "log_file": "logs/agent_execution.log",
    "metrics_export": "prometheus",
    "metrics_port": 8000,
    "health_check_interval_seconds": 30
  },
  
  "error_handling": {
    "on_test_failure": {
      "action": "rollback_and_log",
      "max_retries": 3,
      "retry_delay_seconds": 60
    },
    "on_human_approval_timeout": {
      "action": "pause_and_notify",
      "timeout_hours": 24,
      "escalation": "notify_project_lead"
    },
    "on_unknown_error": {
      "action": "create_issue_and_pause",
      "notify": ["devops@team.com"]
    }
  }
}
```

---

## 🎯 CÓMO USAR ESTA CONFIGURACIÓN

### Paso 1: Ingreso al Panel de Control
1. Ir a: `https://antigravity.google.com/agent-manager`
2. Click en **"New Agent Task"**
3. Seleccionar **"Claude Opus 4.6 (Thinking)"**
4. Pegar la configuración JSON anterior

### Paso 2: Validación Pre-Ejecución
```bash
# Verificar que la configuración es válida
python -c "
import json
config_text = '''
{JSON_CONFIG_HERE}
'''
config = json.loads(config_text)
print('✓ Configuration is valid')
print(f'Total phases: {config[\"roadmap\"][\"total_phases\"]}')
print(f'Total hours: {config[\"roadmap\"][\"total_estimated_hours\"]}')
"
```

### Paso 3: Ejecutar Agente
```bash
# Opción 1: Via Open Agent Manager UI
# Click "Start Execution" en el panel

# Opción 2: Via CLI
antigravity-cli run-agent \
  --config ROADMAP_PROFESIONAL_EJECUTABLE.md \
  --model claude-opus-4.6 \
  --thinking-budget 80000 \
  --repo $(pwd)
```

### Paso 4: Monitoreo
```bash
# Ver logs en tiempo real
tail -f logs/agent_execution.log

# Ver métricas
curl http://localhost:8000/metrics

# Ver estado de fases
curl http://localhost:8000/status | jq '.current_phase'
```

---

## 📊 SALIDAS ESPERADAS

Después de ejecutar el roadmap, espera:

### Fase 1 (Stability)
```
✓ Phase 1 Complete
  - 5/5 test runs successful
  - 0 crashes detected
  - 0 asyncio warnings
  - Tasks: 1.1.1 ✓, 1.1.2 ✓, 1.1.3 ✓, 1.2.1 ✓, 1.2.2 ✓
  - Approval required: false
```

### Fase 2 (Performance)
```
✓ Phase 2 Complete
  - P95 latency: 4.8s (target: 5.0s) ✓
  - Cache hit rate: 76% (target: 75%) ✓
  - All tests pass
  - Tasks: 2.1.1 ✓, 2.2.1 ✓, 2.2.2 ✓
  - Approval required: YES (human review)
```

### Fase 3 (Quality)
```
✓ Phase 3 Complete
  - Cache hit rate: 78% (target: 75%) ✓
  - KB duplicates: 0 (target: 0) ✓
  - Test coverage: 87% (target: 85%) ✓
  - Tasks: 3.1.1 ✓, 3.2.1 ✓
  - Approval required: false
```

### Fase 4 (Observability)
```
✓ Phase 4 Complete
  - Metrics exported: YES ✓
  - Prometheus scrape: OK ✓
  - SLOs met: YES ✓
  - Uptime: 99.7% (target: 99.5%) ✓
  - Tasks: 4.1.1 ✓, 4.1.2 ✓
  - Approval required: YES (final sign-off)
```

### PR Creado
```
Title: [FEATURE] Interview Copilot v2.0 — Automated Code Improvements
Description:
  Automated improvements by Claude Opus 4.6 (Thinking)
  
  Phases completed: 4/4
  Tasks completed: 13/13
  Lines changed: ~450
  Files modified: 8
  Files created: 2 (src/metrics.py, src/alerting.py)
  
  Metrics achieved:
  - P95 latency: 4.8s (was 6.0s, -20% improvement)
  - Cache hit rate: 78% (was 65%, +13% improvement)
  - Test coverage: 87% (was 60%, +27% improvement)
```

---

## 🔧 TROUBLESHOOTING

### Si Phase 1 falla:
```
Problema: RuntimeError en SpeculativeState.cancel_all()
Solución: 
  1. Claude revertirá cambios automáticamente
  2. Revisar logs en logs/agent_execution.log
  3. Ajustar thinking budget si es insuficiente
```

### Si timeouts durante implementation:
```
Problema: Task 2.1.1 excede 60 minutos
Solución:
  1. Aumentar max_tokens a 10000
  2. Aumentar thinking_budget a 25000
  3. Dividir task en subtasks
```

### Si human approval no responde:
```
Acción automática después 24h:
  - Crear GitHub issue con contexto
  - Enviar email a project_lead@team.com
  - Pausar execution hasta aprobación
```

---

## 📈 MÉTRICAS POST-EJECUCIÓN

Después de completar el roadmap, ejecutar:

```bash
# 1. Verificar que todos los archivos modificados compilando
python -m py_compile src/*.py main.py

# 2. Ejecutar suite completa de tests
pytest tests/ -v --cov=src --cov-report=html

# 3. Generar reporte de métricas
python scripts/generate_metrics_report.py

# 4. Comparar antes/después
diff logs/metrics_baseline.json logs/metrics_final.json | grep "p95_latency\|cache_hit"
```

---

## ✅ CHECKLIST FINAL

- [ ] Configuración JSON validada
- [ ] Repos estáactualizados (git pull)
- [ ] Tests unitarios pasan localmente
- [ ] API keys configuradas (.env)
- [ ] Logs directory creado (mkdir -p logs)
- [ ] Prometheus disponible (puerto 8000)
- [ ] Team notificado de ejecución
- [ ] Slack alert channel configurado
- [ ] Rollback plan documentado
- [ ] Canary deploy slots disponibles

---

**Configuración Completada:** 1 Marzo 2026  
**Versión:** 1.0  
**Estado:** Listo para Ingreso a Open Agent Manager

