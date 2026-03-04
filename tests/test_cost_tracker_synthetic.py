import pytest

from src.cost_calculator import (
    CostCategory,
    CostTracker,
    EMBEDDING_RATE_TABLE,
    GENERATION_RATE_TABLE,
)


def test_synthetic_generation_pricing_key_registered():
    assert "synthetic_openai_gpt_4o_mini" in GENERATION_RATE_TABLE
    rates = GENERATION_RATE_TABLE["synthetic_openai_gpt_4o_mini"]
    assert rates[0] > 0
    assert rates[1] > 0


def test_track_embedding_uses_synthetic_default_api_name():
    tracker = CostTracker(
        session_id="test_synthetic_embed",
        default_embedding_api_name="synthetic_openai_embedding",
    )
    tracker.track_embedding(tokens=2000, question="sample")

    entry = tracker.entries[-1]
    assert entry.category == CostCategory.EMBEDDING
    assert entry.api_name == "synthetic_openai_embedding"
    assert entry.cost_usd == pytest.approx(
        2000 * EMBEDDING_RATE_TABLE["synthetic_openai_embedding"]
    )


def test_track_generation_uses_synthetic_pricing_model():
    tracker = CostTracker(session_id="test_synthetic_generation")
    tracker.track_generation(
        input_tokens=1500,
        output_tokens=250,
        api_name="synthetic_openai_gpt_4o_mini",
    )

    generation_entry = next(
        entry for entry in tracker.entries if entry.category == CostCategory.GENERATION
    )
    in_rate, out_rate, _, _ = GENERATION_RATE_TABLE["synthetic_openai_gpt_4o_mini"]
    expected = (1500 * in_rate) + (250 * out_rate)
    assert generation_entry.cost_usd == pytest.approx(expected)
