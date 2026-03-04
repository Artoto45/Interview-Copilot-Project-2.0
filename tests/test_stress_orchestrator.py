"""
Regression thresholds for strict synthetic stress simulation.
"""

from pathlib import Path

import pytest

from tests.stress_test_orchestrator import (
    InterviewScenarioGenerator,
    SimulationConfig,
    StrictInterviewSimulator,
)


@pytest.mark.asyncio
async def test_strict_stress_synthetic_thresholds():
    config = SimulationConfig(
        mode="synthetic",
        interviews=3,
        minutes_per_interview=60.0,
        seed=19,
        output_json=Path("tests/logs/_stress_thresholds.json"),
        output_md=Path("tests/logs/_stress_thresholds.md"),
    )
    events = InterviewScenarioGenerator(seed=config.seed).generate_batch(
        interviews=config.interviews,
        minutes_per_interview=config.minutes_per_interview,
    )
    simulator = StrictInterviewSimulator(config=config)
    report = await simulator.run(events)
    summary = report["summary"]

    qf = summary["question_filter"]
    cls = summary["classification"]
    rsp = summary["responses"]
    cov = summary["coverage"]

    assert qf["precision"] >= 0.99
    assert qf["recall"] >= 0.95
    assert qf["transition_false_positive_rate"] <= 0.01
    assert cls["accuracy"] >= 0.93
    assert rsp["immediate_opener_repeat_rate"] == 0.0
    assert rsp["avg_consecutive_jaccard_3gram"] <= 0.08
    assert cov["candidate_questions"] >= 10
    assert cov["micro_questions"] >= 15


@pytest.mark.asyncio
async def test_redteam_mode_adds_attacks_and_keeps_robustness():
    config = SimulationConfig(
        mode="synthetic",
        interviews=2,
        minutes_per_interview=40.0,
        seed=31,
        output_json=Path("tests/logs/_stress_redteam.json"),
        output_md=Path("tests/logs/_stress_redteam.md"),
        redteam_level="extreme",
    )
    events = InterviewScenarioGenerator(seed=config.seed).generate_batch(
        interviews=config.interviews,
        minutes_per_interview=config.minutes_per_interview,
        redteam_level=config.redteam_level,
    )
    simulator = StrictInterviewSimulator(config=config)
    report = await simulator.run(events)
    red = report["summary"]["redteam"]

    assert red["questions_total"] >= 8
    assert red["robustness_score"] >= 0.80


def test_generator_has_realistic_event_mix():
    gen = InterviewScenarioGenerator(seed=19)
    events = gen.generate_batch(interviews=2, minutes_per_interview=45.0)
    kinds = {event.event_kind for event in events}
    speakers = {event.speaker for event in events}

    assert "small_talk" in kinds
    assert "transition" in kinds
    assert "main_question" in kinds
    assert "micro_question" in kinds
    assert "candidate_question" in kinds
    assert "closing" in kinds
    assert speakers == {"interviewer", "candidate"}
