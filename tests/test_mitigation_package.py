"""
Synthetic mitigation battery for:
1) transition over-reactivity,
2) repetitive openers,
3) repetitive RAG chunks from same source.
"""

from src.knowledge.question_filter import (
    QuestionFilter,
    has_explicit_question_mark,
    strip_transition_prefixes,
)
from src.knowledge.retrieval import KnowledgeRetriever
from src.response.openai_agent import OpenAIAgent
from src.knowledge.classifier import QuestionClassifier


def test_strip_transition_prefixes_keeps_real_question():
    raw = (
        "Perfect. Let's move forward. Could you tell me about a time "
        "when you had to deliver under pressure?"
    )
    cleaned = strip_transition_prefixes(raw)
    assert cleaned.lower().startswith("could you tell me")
    assert "pressure?" in cleaned.lower()


def test_question_filter_rejects_transition_only_statements():
    qf = QuestionFilter()
    transition_lines = [
        "If you'd like to continue, I'm ready for the next step.",
        "That's a strong demonstration of maintaining quality despite pressure.",
        "or wrap up whenever you feel complete.",
        "If you'd like to tackle another scenario or pivot to a different focus,",
        (
            "That's a solid example of balancing priorities while maintaining "
            "quality. If you'd like to continue, I'm ready for the next step!"
        ),
        (
            "That's a strong demonstration of maintaining quality despite "
            "pressure. If you'd like to tackle another scenario or pivot to "
            "a different focus, just let me know!"
        ),
    ]
    for line in transition_lines:
        assert not qf.is_interview_question(line), line


def test_question_filter_accepts_transition_plus_real_question():
    qf = QuestionFilter()
    text = (
        "Perfect! Let's continue. Can you describe a time when you had "
        "to manage multiple stakeholders with different priorities?"
    )
    assert qf.is_interview_question(text)


def test_question_filter_accepts_follow_up_how_did_you():
    qf = QuestionFilter()
    assert qf.is_interview_question(
        "How did you communicate it and handle the resistance?"
    )


def test_question_filter_accepts_imperative_give_me_example():
    qf = QuestionFilter()
    assert qf.is_interview_question(
        "Give me an example of a difficult customer escalation and how you resolved it."
    )


def test_question_filter_ignores_mojibake_question_marks():
    qf = QuestionFilter()
    broken = (
        "That?s a strong demonstration of quality. "
        "If you?d like to continue, I?m ready for the next step!"
    )
    assert has_explicit_question_mark(broken) is False
    assert not qf.is_interview_question(broken)


def test_question_filter_rejects_salary_statement_without_question_intent():
    qf = QuestionFilter()
    statement = (
        "Compensation depends on level and location, "
        "and includes performance bonuses."
    )
    assert not qf.is_interview_question(statement)


def test_classifier_detects_simple_logistics():
    clf = QuestionClassifier()
    result = clf._fallback_classify(
        "Are you comfortable with a hybrid schedule and occasional weekend support?"
    )
    assert result["type"] == "simple"


def test_classifier_detects_hybrid_mixed_intent():
    clf = QuestionClassifier()
    result = clf._fallback_classify(
        "Why should we hire you for this role, and how would you ramp up in your first month?"
    )
    assert result["type"] == "hybrid"


def test_classifier_detects_hybrid_collab_product_ops_pattern():
    clf = QuestionClassifier()
    result = clf._fallback_classify(
        "How would your experience help you collaborate with product and operations here?"
    )
    assert result["type"] == "hybrid"


def test_classifier_detects_situational_micro_followup():
    clf = QuestionClassifier()
    result = clf._fallback_classify("What changed after that?")
    assert result["type"] == "situational"


def test_openai_agent_rotates_openers():
    agent = OpenAIAgent(api_key="test")
    openers = [agent.get_instant_opener("situational") for _ in range(4)]
    # Ensure first two are not identical (no immediate repetition)
    assert openers[0] != openers[1]
    # Ensure there is diversity in a short window
    assert len(set(openers)) >= 2


def test_openai_user_message_includes_recent_context_and_anti_repetition():
    agent = OpenAIAgent(api_key="test")
    msg = agent._build_user_message(
        question="How did you handle time pressure?",
        kb_chunks=["I maintained 92% QA at Webhelp under high volume."],
        question_type="situational",
        recent_questions=[
            "Tell me about yourself",
            "Describe a challenge you faced",
        ],
        recent_responses=[
            "Honestly, from my experience ...",
            "One clear example ...",
        ],
        recent_question_types=["personal", "situational"],
    )
    assert "[ANTI-REPETITION]" in msg
    assert "[RECENT OPENERS TO AVOID]" in msg
    assert "[FORBIDDEN NGRAMS]" in msg
    assert "[RECENT QUESTIONS]" in msg
    assert "[RECENT ANSWERS]" in msg


def test_openai_user_message_hard_mode_section():
    agent = OpenAIAgent(api_key="test")
    msg = agent._build_user_message(
        question="How did you handle time pressure?",
        kb_chunks=["I maintained 92% QA at Webhelp under high volume."],
        question_type="situational",
        recent_questions=[],
        recent_responses=[],
        recent_question_types=[],
        hard_anti_repetition=True,
    )
    assert "[ANTI-REPETITION HARD MODE]" in msg


def test_openai_user_message_includes_interview_memory_block():
    agent = OpenAIAgent(api_key="test")
    msg = agent._build_user_message(
        question="How did you handle time pressure?",
        kb_chunks=["I maintained 92% QA at Webhelp under high volume."],
        question_type="situational",
        recent_questions=[],
        recent_responses=[],
        recent_question_types=[],
        memory_context=(
            "[INTERVIEW MEMORY]\n"
            "[METRICS]\n- 92% QA\n\n"
            "[CONSISTENCY RULES]\n- Keep facts aligned."
        ),
    )
    assert "[INTERVIEW MEMORY]" in msg
    assert "92% QA" in msg


def test_openai_opening_similarity_guard_detects_repetition():
    agent = OpenAIAgent(api_key="test")
    candidate_prefix = (
        "In my previous role at Webhelp, I led a high-volume queue "
        "and kept quality stable while priorities changed."
    )
    recent = [
        (
            "In my previous role at Webhelp, I handled escalations "
            "and kept a 92% QA score with clear communication."
        )
    ]
    assert agent._opening_too_similar(candidate_prefix, recent_responses=recent)


def test_openai_dynamic_max_tokens_is_shorter_than_legacy_cap():
    from src.response.openai_agent import MAX_OUTPUT_TOKENS

    assert MAX_OUTPUT_TOKENS["simple"] < 1024
    assert MAX_OUTPUT_TOKENS["situational"] < 1024
    assert MAX_OUTPUT_TOKENS["simple"] < MAX_OUTPUT_TOKENS["situational"]


def test_retrieval_postprocess_deduplicates_and_diversifies_sources():
    docs = [
        "I prioritized cases by urgency and kept documentation updated.",
        "I prioritized cases by urgency and kept documentation updated.  ",
        "I maintained 92% QA by verifying each case before closing.",
        "I maintained 92% QA by verifying each case before closing.",
        "I adapted quickly to process changes and shared notes with the team.",
    ]
    metas = [
        {"source": "star_stories_english.txt"},
        {"source": "star_stories_english.txt"},
        {"source": "star_stories_english.txt"},
        {"source": "star_stories_english.txt"},
        {"source": "profile_english.txt"},
    ]
    distances = [0.11, 0.12, 0.14, 0.15, 0.16]

    selected = KnowledgeRetriever._postprocess_documents(
        documents=docs,
        metadatas=metas,
        distances=distances,
        max_results=4,
        max_per_source=2,
    )

    # No exact duplicate content after normalization.
    normalized = [KnowledgeRetriever._normalize_doc(x) for x in selected]
    assert len(normalized) == len(set(normalized))
    # Should keep at least one chunk from the second source.
    assert any("adapted quickly to process changes" in x for x in normalized)
