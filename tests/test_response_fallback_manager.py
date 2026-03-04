import pytest

from src.response.fallback_manager import (
    DegradedResponseAgent,
    FallbackResponseManager,
)


class _FailProvider:
    pricing_model = "openai_gpt_4o_mini"
    supports_prompt_cache = False
    system_prompt_token_estimate = 1024
    _cache_stats = {"total_calls": 0, "cache_hits": 0, "by_type": {}}

    async def warmup(self):
        return

    def get_instant_opener(self, question_type: str) -> str:
        return "Fail opener "

    async def generate(self, **kwargs):
        raise RuntimeError("provider failed")
        yield ""


class _GoodProvider:
    pricing_model = "claude_sonnet"
    supports_prompt_cache = True
    system_prompt_token_estimate = 1024
    _cache_stats = {"total_calls": 0, "cache_hits": 0, "by_type": {}}

    async def warmup(self):
        return

    def get_instant_opener(self, question_type: str) -> str:
        return "Good opener "

    async def generate(self, **kwargs):
        yield "One "
        yield "solid "
        yield "answer."


class _GoodProviderWithValidator(_GoodProvider):
    def validate_generated_response(
        self,
        response_text: str,
        question_type: str,
        kb_chunks: list[str],
    ) -> dict:
        return {
            "is_valid": "solid answer" in response_text.lower(),
            "reasons": [],
            "question_type": question_type,
        }


class _RetryProvider:
    pricing_model = "openai_gpt_4o_mini"
    supports_prompt_cache = False
    system_prompt_token_estimate = 1024
    _cache_stats = {"total_calls": 0, "cache_hits": 0, "by_type": {}}

    def __init__(self):
        self.calls = []

    async def warmup(self):
        return

    def get_instant_opener(self, question_type: str) -> str:
        return "Retry opener "

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
            yield "One "
            yield "solid "
            yield "answer."
            return
        yield "generic reply"

    def validate_generated_response(
        self,
        response_text: str,
        question_type: str,
        kb_chunks: list[str],
    ) -> dict:
        _ = (question_type, kb_chunks)
        is_valid = "solid answer" in response_text.lower()
        return {
            "is_valid": is_valid,
            "reasons": [] if is_valid else ["kb_facts<2 (hits=0)"],
            "question_type": question_type,
        }


@pytest.mark.asyncio
async def test_fallback_manager_uses_next_provider_on_failure():
    manager = FallbackResponseManager(
        provider_chain=["openai", "anthropic", "degraded"],
        providers_override={
            "openai": _FailProvider(),
            "anthropic": _GoodProvider(),
            "degraded": DegradedResponseAgent(),
        },
    )

    tokens = []
    async for token in manager.generate(
        question="Tell me about a conflict you resolved.",
        kb_chunks=["I maintained 92% QA at Webhelp."],
        question_type="situational",
    ):
        tokens.append(token)

    text = "".join(tokens)
    assert "solid answer" in text.lower()
    assert manager.last_provider_used == "anthropic"
    assert manager.pricing_model == "claude_sonnet"


@pytest.mark.asyncio
async def test_fallback_manager_uses_degraded_when_all_fail():
    manager = FallbackResponseManager(
        provider_chain=["openai", "anthropic", "degraded"],
        providers_override={
            "openai": _FailProvider(),
            "anthropic": _FailProvider(),
            "degraded": DegradedResponseAgent(),
        },
    )

    tokens = []
    async for token in manager.generate(
        question="What is your expected salary?",
        kb_chunks=["I can discuss compensation based on market range."],
        question_type="simple",
    ):
        tokens.append(token)

    text = "".join(tokens).lower()
    assert "market range" in text or "structured" in text
    assert manager.last_provider_used == "degraded"
    assert manager.pricing_model == "degraded_local"


@pytest.mark.asyncio
async def test_fallback_manager_generate_full_with_validation_compatible():
    manager = FallbackResponseManager(
        provider_chain=["anthropic"],
        providers_override={
            "anthropic": _GoodProviderWithValidator(),
            "degraded": DegradedResponseAgent(),
        },
    )

    text, report = await manager.generate_full_with_validation(
        question="Tell me about your strengths.",
        kb_chunks=["Webhelp", "92% QA"],
        question_type="personal",
    )

    assert "solid answer" in text.lower()
    assert report["is_valid"] is True
    assert report["attempts"] == 1
    assert report["retried"] is False


@pytest.mark.asyncio
async def test_fallback_manager_generate_full_exists_and_returns_text():
    manager = FallbackResponseManager(
        provider_chain=["anthropic"],
        providers_override={
            "anthropic": _GoodProvider(),
            "degraded": DegradedResponseAgent(),
        },
    )

    text = await manager.generate_full(
        question="Tell me about yourself.",
        kb_chunks=["3+ years remote support", "Webhelp"],
        question_type="personal",
    )

    assert text == "One solid answer."


@pytest.mark.asyncio
async def test_fallback_manager_validation_retry_enables_hard_mode():
    provider = _RetryProvider()
    manager = FallbackResponseManager(
        provider_chain=["openai", "degraded"],
        providers_override={
            "openai": provider,
            "degraded": DegradedResponseAgent(),
        },
    )

    text, report = await manager.generate_full_with_validation(
        question="Tell me about a challenge.",
        kb_chunks=["Webhelp", "92% QA"],
        question_type="situational",
    )

    assert len(provider.calls) == 2
    assert provider.calls[0].get("force_hard_mode") is False
    assert provider.calls[1].get("force_hard_mode") is True
    assert "solid answer" in text.lower()
    assert report["is_valid"] is True
    assert report["attempts"] == 2
    assert report["retried"] is True
