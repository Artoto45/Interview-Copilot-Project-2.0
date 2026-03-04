from src.response.openai_agent import OpenAIAgent


def test_validation_fails_when_missing_contractions():
    agent = OpenAIAgent(api_key="test-key")
    kb_chunks = [
        "At Webhelp I maintained an average QA of 92% over 3+ years.",
        "I handled process changes and escalations in a remote BPO environment.",
    ]
    response = (
        "I maintained strong quality under pressure. "
        "I handled escalations with clear communication."
    )
    report = agent.validate_generated_response(
        response_text=response,
        question_type="personal",
        kb_chunks=kb_chunks,
    )
    assert report["is_valid"] is False
    assert "missing_contractions" in report["reasons"]


def test_validation_fails_with_insufficient_kb_facts():
    agent = OpenAIAgent(api_key="test-key")
    kb_chunks = [
        "At Webhelp I maintained an average QA of 92% over 3+ years.",
    ]
    response = "I'd stay calm and I'd organize the work with clear priorities."
    report = agent.validate_generated_response(
        response_text=response,
        question_type="personal",
        kb_chunks=kb_chunks,
    )
    assert report["is_valid"] is False
    assert any(reason.startswith("kb_facts<") for reason in report["reasons"])


def test_validation_passes_for_grounded_star_response():
    agent = OpenAIAgent(api_key="test-key")
    kb_chunks = [
        "Situation: In October 2025, Webhelp had restructuring tied to AI automation.",
        "Result: I maintained 92% QA over 3+ years while adapting to process changes.",
    ]
    response = (
        "In that situation at Webhelp, I'd explain the context clearly. "
        "My task was to keep quality stable during restructuring. "
        "I'd document each case and I'd prioritize urgent tickets. "
        "As a result, I kept 92% QA and supported the team through changes."
    )
    report = agent.validate_generated_response(
        response_text=response,
        question_type="situational",
        kb_chunks=kb_chunks,
    )
    assert report["is_valid"] is True
    assert report["star_ok"] is True
    assert report["contraction_ok"] is True
    assert report["kb_hits"] >= 2
