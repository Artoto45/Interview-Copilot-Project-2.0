# Stress Test Package Results (March 2026)

## Scope
This package adds a strict interview stress simulator with:
- full interview lifecycle (opening small-talk -> transitions -> main questions -> micro follow-ups -> candidate questions -> closing)
- synthetic offline mode (no external API calls)
- API mode for pseudo-real end-to-end runs
- metrics for filter precision/recall, transition over-reactivity, classifier accuracy, response repetition, and fuel gauge impact

## New Components
- `tests/stress_test_orchestrator.py`
  - `InterviewScenarioGenerator`
  - `StrictInterviewSimulator`
  - `SyntheticKnowledgeRetriever`
  - `SyntheticResponseAgent`
- `tests/test_stress_orchestrator.py`
  - regression thresholds for strict synthetic mode

## Improvement Package Applied
1. `src/knowledge/question_filter.py`
- Added stronger intent handling to reject keyword-only statements without question intent.
- Added missing intent cues (`are you`, `give me`, etc.) to avoid false negatives.

2. `src/knowledge/classifier.py`
- Reworked fallback classification to use signal-family flags.
- Added robust compound detection by clause intent.
- Added logistics/simple signals (start date, notice, compensation, schedule).
- Added situational micro-follow-up signals.
- Added company/personal signal coverage to reduce default-personal drift.

3. `src/response/openai_agent.py`
- Added explicit anti-repetition section `[RECENT OPENERS TO AVOID]` in prompt payload.

## Synthetic Stress Results (Hours of Interviews)
### Baseline run before this package
- Command:
  - `python tests/stress_test_orchestrator.py --mode synthetic --interviews 6 --minutes-per-interview 75 --seed 19`
- Result snapshot:
  - Filter precision: `0.9436`
  - Filter recall: `0.9647`
  - Classifier accuracy: `0.5349`
  - Opener repeat rate: `0.0000`

### After package improvements
- Command:
  - `python tests/stress_test_orchestrator.py --mode synthetic --interviews 10 --minutes-per-interview 90 --seed 23`
- Result snapshot:
  - Virtual duration: `900.0 minutes` (15.0 hours)
  - Filter precision: `1.0000`
  - Filter recall: `1.0000`
  - Transition FP rate: `0.0000`
  - Classifier accuracy: `0.9606`
  - Opener repeat rate: `0.0000`
  - Avg consecutive 3-gram similarity: `0.0262`

## 30-minute Pseudo-Real API Simulation
- Command:
  - `python tests/stress_test_orchestrator.py --mode api --interviews 1 --minutes-per-interview 30 --seed 31`
- Result snapshot:
  - Filter precision/recall/F1: `1.0000 / 1.0000 / 1.0000`
  - Classifier accuracy: `0.9500` (`19/20`)
  - Responses generated: `20`
  - Opener repeat rate: `0.0000`
  - Avg consecutive 3-gram similarity: `0.0080`
- Estimated tracked session cost: `$0.007205`

## Double-Difficulty Re-Run
### Synthetic x2
- Command:
  - `python tests/stress_test_orchestrator.py --mode synthetic --interviews 20 --minutes-per-interview 90 --seed 47`
- Result snapshot:
  - Virtual duration: `1800.0 minutes` (30.0 hours)
  - Responses: `1268` (vs `635` in previous strict run)
  - Filter precision/recall/F1: `1.0000 / 1.0000 / 1.0000`
  - Classifier accuracy: `0.9495`
  - Opener repeat rate: `0.0000`
  - Avg 3-gram similarity: `0.0283`
  - P95 3-gram similarity: `0.2079`

### API x2 (60 min)
- Command:
  - `python tests/stress_test_orchestrator.py --mode api --interviews 1 --minutes-per-interview 60 --seed 47`
- Result snapshot:
  - Responses: `42` (vs `20` in previous 30-min run)
  - Filter precision/recall/F1: `1.0000 / 1.0000 / 1.0000`
  - Classifier accuracy: `0.9524`
  - Opener repeat rate: `0.0000`
  - Avg 3-gram similarity: `0.0036`
  - P95 3-gram similarity: `0.0133`
  - Estimated tracked session cost: `$0.014624`

## Test Status
- `python -m pytest tests/test_mitigation_package.py tests/test_stress_orchestrator.py -q` -> pass
- `python -m pytest tests -q` -> pass (`86 passed`)

## Notes
- In API mode, generation + embeddings are real OpenAI calls.
- Transcription costs in this orchestrator are simulated from synthetic durations (tracked via `CostTracker`) to estimate fuel behavior under realistic timelines.
