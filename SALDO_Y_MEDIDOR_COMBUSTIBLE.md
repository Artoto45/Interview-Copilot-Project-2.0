# Saldo y Medidor de Combustible

## Objetivo
Este modulo agrega:
- Seguimiento de saldo por proveedor (`OpenAI`, `Deepgram`, `Anthropic`).
- Deduccion en tiempo real por costo real de la sesion.
- Estimacion de minutos restantes ("Fuel Gauge") usando:
  - consumo observado en la sesion,
  - baseline del perfil del sistema.

## Saldos iniciales por defecto
En `.env.example`:
- `SALDO_OPENAI_USD=9.92`
- `SALDO_DEEPGRAM_USD=188.69`
- `SALDO_ANTHROPIC_USD=4.74`

Si no hay override en `.env`, se usan esos valores.

## Como se calcula el combustible
Para cada proveedor:

1. `remaining_usd`
- Si hay balance live del proveedor: se usa ese valor.
- Si no: `remaining_usd = saldo_inicial - gasto_sesion`.

2. `observed_burn_usd_per_min`
- `gasto_sesion / minutos_transcurridos`.

3. `baseline_burn_usd_per_min`
- Se deriva de supuestos del sistema:
  - `candidate_speaking_ratio`
  - `interviewer_speaking_ratio`
  - `questions_per_minute`
  - `avg_generation_input_tokens`
  - `avg_generation_output_tokens`
  - `avg_embedding_tokens_per_question`
  - pricing por proveedor (`COST_*`).

4. `effective_burn_usd_per_min`
- Si hay observado y baseline: `0.8 * observado + 0.2 * baseline`.
- Si no hay observado: se usa baseline.

5. `minutes_remaining`
- `remaining_usd / effective_burn_usd_per_min` (si burn > 0).

Luego se calcula un "bottleneck" global:
- proveedor con menor `minutes_remaining`.
- `minutes_until_any_depletion`.

## Live balances por proveedor
### Deepgram
Implementado refresco live opcional con endpoint oficial:
- `GET /v1/projects/{project_id}/balances`
- Requiere `DEEPGRAM_PROJECT_ID` + `DEEPGRAM_API_KEY`.
- Variables:
  - `SALDO_ENABLE_LIVE_REFRESH=true|false`
  - `SALDO_REFRESH_INTERVAL_S=120`

### OpenAI
Implementado refresh live via endpoint oficial de costos:
- `GET /v1/organization/costs` (Admin API key requerida).
- Variables:
  - `OPENAI_ADMIN_KEY`
  - `SALDO_LIVE_OPENAI_ENABLED=true|false`
  - `SALDO_BASELINE_START_UTC=...` (RFC3339)

Nota: OpenAI expone costos, no credito restante directo. Este modulo calcula:
- `remaining = SALDO_OPENAI_USD - cost_since_baseline`.

### Anthropic
Implementado refresh live via endpoint oficial de costos:
- `GET /v1/organizations/cost_report` (Admin API key requerida).
- Variables:
  - `ANTHROPIC_ADMIN_KEY`
  - `SALDO_LIVE_ANTHROPIC_ENABLED=true|false`
  - `SALDO_BASELINE_START_UTC=...` (RFC3339)

Nota: Anthropic expone costos, no credito restante directo. Este modulo calcula:
- `remaining = SALDO_ANTHROPIC_USD - cost_since_baseline`.

## Eventos en tiempo real
El pipeline publica por WebSocket:
- `type: "saldo_update"`
- `data: { providers, fuel_gauge, settings }`

Se emite al cerrar cada respuesta y al finalizar sesion.

## Archivos clave
- `src/saldo.py`
- `src/cost_calculator.py`
- `main.py`
- `src/teleprompter/ws_bridge.py`
- `tests/test_saldo.py`

## Fuentes oficiales usadas
- OpenAI API pricing: https://openai.com/api/pricing/
- Deepgram Project Balances endpoint: https://developers.deepgram.com/reference/get-project-balances
- Anthropic Usage and Cost API: https://docs.anthropic.com/en/api/usage-cost-api
