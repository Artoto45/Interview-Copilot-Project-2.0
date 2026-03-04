import pytest

import main as coordinator
from src.response.fallback_manager import (
    DegradedResponseAgent,
    FallbackResponseManager,
)


class _DeterministicClassifier:
    @staticmethod
    def _fallback_classify(_: str) -> dict:
        return {
            "type": "situational",
            "budget": 0,
        }


class _DeterministicRetriever:
    async def retrieve_with_evidence(self, query: str, question_type: str) -> dict:
        _ = (query, question_type)
        return {
            "chunks": [
                "I worked at Webhelp in a remote BPO operation.",
                "I maintained 92% QA while handling high ticket volume.",
            ],
            "evidence": [
                {
                    "source": "profile_english.txt",
                    "topic": "experience",
                    "distance": 0.08,
                    "snippet": "Webhelp remote BPO operations",
                },
                {
                    "source": "star_stories_english.txt",
                    "topic": "quality",
                    "distance": 0.11,
                    "snippet": "maintained 92% QA",
                },
            ],
        }

    async def retrieve_with_metadata(
        self,
        query: str,
        question_type: str,
        top_k: int = 3,
    ) -> list[dict]:
        _ = (query, question_type, top_k)
        return []

    @staticmethod
    def _build_evidence_for_chunks(
        chunks: list[str],
        metadata_rows: list[dict],
    ) -> list[dict]:
        _ = metadata_rows
        return [
            {
                "source": "synthetic",
                "topic": "fallback",
                "distance": 0.5,
                "snippet": chunk[:80],
            }
            for chunk in chunks
        ]


class _DeterministicQuestionFilter:
    @staticmethod
    def normalize_question_text(text: str) -> str:
        return (text or "").strip()


class _DeterministicMemory:
    def __init__(self):
        self.generated: list[dict] = []

    @staticmethod
    def build_prompt_context(question: str, question_type: str) -> str:
        return (
            "[INTERVIEW MEMORY]\n"
            f"- question_type: {question_type}\n"
            f"- latest_question: {question[:40]}"
        )

    def ingest_generated_response(
        self,
        question: str,
        question_type: str,
        response: str,
        kb_chunks: list[str],
    ):
        self.generated.append(
            {
                "question": question,
                "question_type": question_type,
                "response": response,
                "kb_chunks": list(kb_chunks),
            }
        )


class _AlwaysValidProvider:
    pricing_model = "synthetic_provider"
    supports_prompt_cache = False
    system_prompt_token_estimate = 128
    _cache_stats = {"total_calls": 0, "cache_hits": 0, "by_type": {}}
    _last_cache_hits = 0

    async def warmup(self):
        return

    @staticmethod
    def get_instant_opener(question_type: str) -> str:
        _ = question_type
        return "I'd say "

    async def generate(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
        recent_questions: list[str] | None = None,
        recent_responses: list[str] | None = None,
        recent_question_types: list[str] | None = None,
        memory_context: str | None = None,
        force_hard_mode: bool = False,
    ):
        _ = (
            question,
            kb_chunks,
            question_type,
            thinking_budget,
            recent_questions,
            recent_responses,
            recent_question_types,
            memory_context,
            force_hard_mode,
        )
        yield "I'm at Webhelp, "
        yield "I've kept 92% QA, "
        yield "and I'd adapt to new workflows quickly."

    @staticmethod
    def validate_generated_response(
        response_text: str,
        question_type: str,
        kb_chunks: list[str],
    ) -> dict:
        _ = (question_type, kb_chunks)
        return {
            "is_valid": "webhelp" in response_text.lower(),
            "reasons": [],
            "kb_hits": 2,
            "required_kb_hits": 2,
            "contraction_ok": True,
            "star_components": 3,
            "star_ok": True,
            "question_type": question_type,
        }


class _RetryingProvider(_AlwaysValidProvider):
    def __init__(self):
        self.calls: list[dict] = []

    async def generate(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
        recent_questions: list[str] | None = None,
        recent_responses: list[str] | None = None,
        recent_question_types: list[str] | None = None,
        memory_context: str | None = None,
        force_hard_mode: bool = False,
    ):
        self.calls.append(
            {
                "question": question,
                "kb_chunks": list(kb_chunks),
                "question_type": question_type,
                "thinking_budget": thinking_budget,
                "recent_questions": list(recent_questions or []),
                "recent_responses": list(recent_responses or []),
                "recent_question_types": list(recent_question_types or []),
                "memory_context": memory_context,
                "force_hard_mode": force_hard_mode,
            }
        )
        if force_hard_mode:
            yield "I'm at Webhelp, "
            yield "I've kept 92% QA, "
            yield "and I'd use that experience here."
            return
        yield "This answer is too generic."

    @staticmethod
    def validate_generated_response(
        response_text: str,
        question_type: str,
        kb_chunks: list[str],
    ) -> dict:
        _ = (question_type, kb_chunks)
        valid = ("webhelp" in response_text.lower()) and ("92% qa" in response_text.lower())
        return {
            "is_valid": valid,
            "reasons": [] if valid else ["kb_facts<2 (hits=0)"],
            "question_type": question_type,
        }


@pytest.mark.asyncio
async def test_process_question_end_to_end_with_fallback_manager(monkeypatch):
    messages: list[dict] = []
    memory = _DeterministicMemory()
    provider = _AlwaysValidProvider()

    async def fake_broadcast(message: dict):
        messages.append(message)

    monkeypatch.setattr(coordinator, "broadcast_message", fake_broadcast)
    monkeypatch.setattr(
        coordinator,
        "_log_conversation",
        lambda question, response, q_type, metadata=None: None,
    )

    await coordinator._speculative.cancel_all()
    await coordinator._speculative.clear_retrieval()
    await coordinator._cancel_pending_fragment()

    coordinator.pipeline.classifier = _DeterministicClassifier()
    coordinator.pipeline.retriever = _DeterministicRetriever()
    coordinator.pipeline.question_filter = _DeterministicQuestionFilter()
    coordinator.pipeline.response_agent = FallbackResponseManager(
        provider_chain=["openai", "degraded"],
        providers_override={
            "openai": provider,
            "degraded": DegradedResponseAgent(),
        },
    )
    coordinator.pipeline.interview_memory = memory
    coordinator.pipeline.session_metrics = None
    coordinator.pipeline.cost_tracker = None
    coordinator.pipeline.conversation_history = []
    coordinator.pipeline.total_responses = 0
    coordinator.pipeline.total_questions = 0

    await coordinator.process_question(
        "Tell me about a time you handled pressure and what changed after that?",
        raw_question=(
            "Tell me about a time you handled pressure and what changed after that?"
        ),
        question_meta={
            "filter_reason": "has_question_mark",
            "fragment_risk": False,
            "fragment_reason": "none",
        },
    )

    assert any(msg.get("type") == "new_question" for msg in messages)
    assert any(msg.get("type") == "response_end" for msg in messages)

    streamed_text = "".join(
        msg.get("data", "")
        for msg in messages
        if msg.get("type") == "token"
    )
    assert "Webhelp" in streamed_text
    assert "92% QA" in streamed_text

    assert coordinator.pipeline.total_responses == 1
    assert len(coordinator.pipeline.conversation_history) == 1

    entry = coordinator.pipeline.conversation_history[0]
    assert entry["provider"] == "openai"
    assert entry["validation"]["is_valid"] is True
    assert entry["validation"]["attempts"] == 1
    assert entry["validation"]["retried"] is False
    assert len(entry["kb_evidence"]) >= 1
    assert len(memory.generated) == 1


@pytest.mark.asyncio
async def test_process_question_retries_when_validation_fails(monkeypatch):
    messages: list[dict] = []
    provider = _RetryingProvider()

    async def fake_broadcast(message: dict):
        messages.append(message)

    monkeypatch.setattr(coordinator, "broadcast_message", fake_broadcast)
    monkeypatch.setattr(
        coordinator,
        "_log_conversation",
        lambda question, response, q_type, metadata=None: None,
    )

    await coordinator._speculative.cancel_all()
    await coordinator._speculative.clear_retrieval()
    await coordinator._cancel_pending_fragment()

    coordinator.pipeline.classifier = _DeterministicClassifier()
    coordinator.pipeline.retriever = _DeterministicRetriever()
    coordinator.pipeline.question_filter = _DeterministicQuestionFilter()
    coordinator.pipeline.response_agent = FallbackResponseManager(
        provider_chain=["openai", "degraded"],
        providers_override={
            "openai": provider,
            "degraded": DegradedResponseAgent(),
        },
    )
    coordinator.pipeline.interview_memory = _DeterministicMemory()
    coordinator.pipeline.session_metrics = None
    coordinator.pipeline.cost_tracker = None
    coordinator.pipeline.conversation_history = []
    coordinator.pipeline.total_responses = 0
    coordinator.pipeline.total_questions = 0

    await coordinator.process_question(
        "What tactics did you use in that challenging period?",
        raw_question="What tactics did you use in that challenging period?",
        question_meta={
            "filter_reason": "has_question_mark",
            "fragment_risk": False,
            "fragment_reason": "none",
        },
    )

    assert len(provider.calls) >= 2
    assert provider.calls[0].get("force_hard_mode") is False
    assert provider.calls[1].get("force_hard_mode") is True

    assert len(coordinator.pipeline.conversation_history) == 1
    entry = coordinator.pipeline.conversation_history[0]
    assert entry["validation"]["attempts"] == 2
    assert entry["validation"]["retried"] is True
    assert entry["validation"]["is_valid"] is True

    streamed_text = "".join(
        msg.get("data", "")
        for msg in messages
        if msg.get("type") == "token"
    )
    assert "Webhelp" in streamed_text
    assert "92% QA" in streamed_text
