import asyncio

from tests.run_full_pipeline_realistic_sim import (
    SyntheticKnowledgeRetrieverAdapter,
    SyntheticResponseAgentAdapter,
)


def test_synthetic_retriever_adapter_provides_evidence_bundle():
    async def _run():
        retriever = SyntheticKnowledgeRetrieverAdapter()
        bundle = await retriever.retrieve_with_evidence(
            query="Tell me about a time you influenced leadership.",
            question_type="situational",
        )
        assert "chunks" in bundle
        assert "evidence" in bundle
        assert bundle["chunks"]
        assert bundle["evidence"]
        assert len(bundle["chunks"]) == len(bundle["evidence"])
        assert all("source" in row for row in bundle["evidence"])
        assert all("snippet" in row for row in bundle["evidence"])

    asyncio.run(_run())


def test_synthetic_response_adapter_returns_validated_text():
    async def _run():
        agent = SyntheticResponseAgentAdapter()
        text, validation = await agent.generate_full_with_validation(
            question="Tell me about a time you handled conflicting priorities.",
            kb_chunks=[
                "When priorities conflicted, I mapped urgency and stakeholders and sent clear updates.",
                "My actions helped maintain 92% QA while handling high-volume queues.",
            ],
            question_type="situational",
            recent_questions=["How do you prioritize under pressure?"],
            recent_responses=["I prioritize by urgency and business impact."],
            recent_question_types=["situational"],
        )
        assert text
        assert isinstance(text, str)
        assert validation["is_valid"] is True
        assert validation["attempts"] == 1
        assert validation["retried"] is False

    asyncio.run(_run())
