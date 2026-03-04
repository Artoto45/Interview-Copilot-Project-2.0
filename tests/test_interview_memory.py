from src.response.interview_memory import InterviewMemory


def test_memory_ingests_metrics_and_experience():
    memory = InterviewMemory(max_facts_per_category=12)
    memory.ingest_candidate_utterance(
        "I worked at Webhelp for 3 years and maintained 92% QA."
    )
    snap = memory.snapshot()

    metrics = " ".join(item["text"] for item in snap["metrics"])
    experiences = " ".join(item["text"] for item in snap["experiences"])
    domains = " ".join(item["text"] for item in snap["domains"])

    assert "92% qa" in metrics.lower()
    assert "worked at webhelp" in experiences.lower()
    assert "webhelp" in domains.lower()


def test_memory_prompt_context_contains_consistency_rules():
    memory = InterviewMemory(max_facts_per_category=12)
    memory.ingest_candidate_utterance(
        "I prioritize urgent tickets and keep documentation updated daily."
    )
    memory.ingest_generated_response(
        question="How do you handle pressure?",
        question_type="situational",
        response="At Webhelp I kept 92% QA while handling high-volume escalations.",
        kb_chunks=["I worked in remote BPO operations for over three years at Webhelp."],
    )

    context = memory.build_prompt_context(
        question="How did you prioritize under pressure?",
        question_type="situational",
    )
    assert "[INTERVIEW MEMORY]" in context
    assert "[CONSISTENCY RULES]" in context
    assert "92% QA" in context or "webhelp" in context.lower()
