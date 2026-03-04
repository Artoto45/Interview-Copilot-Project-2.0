"""
Fallback response manager with provider circuit breaker and degraded mode.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
from typing import AsyncGenerator, Optional

from src.response.openai_agent import OpenAIAgent

logger = logging.getLogger("response.fallback")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _parse_chain(raw: str) -> list[str]:
    items = [item.strip().lower() for item in raw.split(",")]
    return [item for item in items if item]


class DegradedResponseAgent:
    """
    Local safe fallback when all remote providers fail.
    """

    pricing_model = "degraded_local"
    supports_prompt_cache = False
    system_prompt_token_estimate = 80

    def __init__(self):
        self._cache_stats = {"total_calls": 0, "cache_hits": 0, "by_type": {}}

    async def warmup(self) -> None:
        return

    @staticmethod
    def get_instant_opener(question_type: str) -> str:
        map_ = {
            "simple": "Sure, in short, ",
            "personal": "From my experience, ",
            "company": "From what I know about your team, ",
            "hybrid": "I would approach it like this, ",
            "situational": "One practical example is, ",
        }
        return map_.get(question_type, "I would answer it this way, ")

    async def generate(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
        recent_questions: Optional[list[str]] = None,
        recent_responses: Optional[list[str]] = None,
        recent_question_types: Optional[list[str]] = None,
        memory_context: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        self._cache_stats["total_calls"] += 1

        opener = self.get_instant_opener(question_type)
        facts = [chunk.strip() for chunk in (kb_chunks or []) if chunk.strip()]
        if facts:
            primary = facts[0]
            secondary = facts[1] if len(facts) > 1 else ""
        else:
            primary = "I would stay structured, clear, and focused on measurable outcomes."
            secondary = ""

        response = (
            f"{opener}{primary} [PAUSE] "
            "I can adapt this to the exact context of your question and keep it concise."
        )
        if secondary:
            response += f" Also, {secondary}"

        words = response.split()
        for idx, word in enumerate(words):
            suffix = " " if idx < len(words) - 1 else ""
            yield word + suffix


class FallbackResponseManager:
    """
    Tries providers in order with strict stage timeouts and auto-fallback.
    """

    def __init__(
        self,
        provider_chain: Optional[list[str]] = None,
        providers_override: Optional[dict[str, object]] = None,
    ):
        raw_chain = os.getenv(
            "RESPONSE_PROVIDER_CHAIN",
            "openai,anthropic,degraded",
        )
        self.provider_chain = (
            [item.strip().lower() for item in provider_chain]
            if provider_chain
            else _parse_chain(raw_chain)
        )
        if not self.provider_chain:
            self.provider_chain = ["openai", "degraded"]

        self.failure_threshold = max(
            1,
            _env_int("RESPONSE_CIRCUIT_FAILURE_THRESHOLD", 2),
        )
        self.cooldown_s = max(
            5.0,
            _env_float("RESPONSE_CIRCUIT_COOLDOWN_S", 45.0),
        )
        self.first_token_timeout_s = max(
            2.0,
            _env_float("RESPONSE_FIRST_TOKEN_TIMEOUT_S", 8.0),
        )
        self.per_token_timeout_s = max(
            2.0,
            _env_float("RESPONSE_PER_TOKEN_TIMEOUT_S", 10.0),
        )

        self._provider_timeouts_s = {
            "openai": max(8.0, _env_float("RESPONSE_TIMEOUT_OPENAI_S", 30.0)),
            "anthropic": max(8.0, _env_float("RESPONSE_TIMEOUT_ANTHROPIC_S", 32.0)),
            "gemini": max(8.0, _env_float("RESPONSE_TIMEOUT_GEMINI_S", 30.0)),
            "degraded": max(1.0, _env_float("RESPONSE_TIMEOUT_DEGRADED_S", 4.0)),
        }

        self._providers = providers_override or self._build_default_providers()
        self._consecutive_failures: dict[str, int] = {}
        self._circuit_open_until: dict[str, float] = {}

        self.last_provider_used: Optional[str] = None
        self._active_provider_name: Optional[str] = None

        # Exposed compatibility attributes expected by main.py
        self.pricing_model = "openai_gpt_4o_mini"
        self.supports_prompt_cache = False
        self.system_prompt_token_estimate = 1024
        self._cache_stats = {"total_calls": 0, "cache_hits": 0, "by_type": {}}
        self._last_cache_hits = 0
        self._local_validator: Optional[OpenAIAgent] = None

    def _build_default_providers(self) -> dict[str, object]:
        providers: dict[str, object] = {
            "openai": OpenAIAgent(),
            "degraded": DegradedResponseAgent(),
        }
        try:
            from src.response.claude_agent import ResponseAgent as ClaudeAgent

            providers["anthropic"] = ClaudeAgent()
        except Exception as exc:
            logger.warning(f"Anthropic provider unavailable: {exc}")

        try:
            from src.response.gemini_agent import GeminiAgent

            providers["gemini"] = GeminiAgent()
        except Exception as exc:
            logger.warning(f"Gemini provider unavailable: {exc}")

        return providers

    async def warmup(self) -> None:
        for name in self.provider_chain:
            provider = self._providers.get(name)
            if provider is None:
                continue
            warmup = getattr(provider, "warmup", None)
            if not callable(warmup):
                continue
            timeout_s = min(12.0, self._provider_timeouts_s.get(name, 12.0))
            try:
                await asyncio.wait_for(warmup(), timeout=timeout_s)
            except Exception as exc:
                logger.warning(f"Warmup failed for provider={name}: {exc}")

    def get_instant_opener(self, question_type: str) -> str:
        for name in self.provider_chain:
            provider = self._providers.get(name)
            if provider is None:
                continue
            if self._is_circuit_open(name):
                continue
            func = getattr(provider, "get_instant_opener", None)
            if callable(func):
                return func(question_type)
        return DegradedResponseAgent.get_instant_opener(question_type)

    def _is_circuit_open(self, provider_name: str) -> bool:
        until = self._circuit_open_until.get(provider_name, 0.0)
        return until > time.monotonic()

    def _mark_success(self, provider_name: str) -> None:
        self._consecutive_failures[provider_name] = 0
        self._circuit_open_until[provider_name] = 0.0

    def _mark_failure(self, provider_name: str) -> None:
        count = self._consecutive_failures.get(provider_name, 0) + 1
        self._consecutive_failures[provider_name] = count
        if count >= self.failure_threshold:
            self._circuit_open_until[provider_name] = time.monotonic() + self.cooldown_s
            logger.warning(
                f"Circuit opened for provider={provider_name} "
                f"for {self.cooldown_s:.1f}s after {count} consecutive failures."
            )

    def _sync_exposed_state(self, provider_name: str) -> None:
        provider = self._providers.get(provider_name)
        if provider is None:
            return
        self._active_provider_name = provider_name
        self.last_provider_used = provider_name
        self.pricing_model = getattr(provider, "pricing_model", self.pricing_model)
        self.supports_prompt_cache = bool(
            getattr(provider, "supports_prompt_cache", False)
        )
        self.system_prompt_token_estimate = int(
            getattr(provider, "system_prompt_token_estimate", 1024)
        )
        self._cache_stats = getattr(
            provider,
            "_cache_stats",
            {"total_calls": 0, "cache_hits": 0, "by_type": {}},
        )
        self._last_cache_hits = int(getattr(provider, "_last_cache_hits", 0))

    @staticmethod
    def _filter_kwargs_for_generate(provider: object, kwargs: dict) -> dict:
        signature = inspect.signature(provider.generate)
        accepted = set(signature.parameters.keys())
        return {key: value for key, value in kwargs.items() if key in accepted}

    @staticmethod
    def _looks_like_error_prefix(text: str) -> bool:
        probe = (text or "").strip().lower()
        if not probe:
            return False
        return probe.startswith("[error") or probe.startswith("error generating response")

    async def _stream_provider(
        self,
        provider_name: str,
        provider: object,
        kwargs: dict,
        timeout_s: float,
    ) -> AsyncGenerator[str, None]:
        gen_kwargs = self._filter_kwargs_for_generate(provider, kwargs)
        stream = provider.generate(**gen_kwargs)
        iterator = stream.__aiter__()
        deadline = time.monotonic() + timeout_s

        emitted = 0
        probe_tokens: list[str] = []
        probe_text = ""
        probe_decided = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Provider {provider_name} timed out ({timeout_s:.1f}s)")

            step_timeout = min(
                remaining,
                self.first_token_timeout_s if emitted == 0 else self.per_token_timeout_s,
            )
            try:
                token = await asyncio.wait_for(iterator.__anext__(), timeout=step_timeout)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError as exc:
                raise TimeoutError(
                    f"Provider {provider_name} token timeout after {step_timeout:.1f}s"
                ) from exc

            if token is None:
                continue
            text_token = str(token)

            if not probe_decided:
                probe_tokens.append(text_token)
                probe_text = "".join(probe_tokens)
                should_decide = (
                    len(probe_text) >= 64
                    or any(ch in text_token for ch in ".!?]")
                )
                if should_decide:
                    if self._looks_like_error_prefix(probe_text):
                        raise RuntimeError(
                            f"Provider {provider_name} returned error payload: {probe_text[:120]}"
                        )
                    probe_decided = True
                    for held in probe_tokens:
                        emitted += 1
                        yield held
                    probe_tokens.clear()
                continue

            emitted += 1
            yield text_token

        if not probe_decided and probe_tokens:
            if self._looks_like_error_prefix("".join(probe_tokens)):
                raise RuntimeError(
                    f"Provider {provider_name} returned error payload: {''.join(probe_tokens)[:120]}"
                )
            for held in probe_tokens:
                emitted += 1
                yield held

        if emitted == 0:
            raise RuntimeError(f"Provider {provider_name} produced empty output")

    async def generate(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
        recent_questions: Optional[list[str]] = None,
        recent_responses: Optional[list[str]] = None,
        recent_question_types: Optional[list[str]] = None,
        memory_context: Optional[str] = None,
        force_hard_mode: bool = False,
    ) -> AsyncGenerator[str, None]:
        kwargs = {
            "question": question,
            "kb_chunks": kb_chunks,
            "question_type": question_type,
            "thinking_budget": thinking_budget,
            "recent_questions": recent_questions or [],
            "recent_responses": recent_responses or [],
            "recent_question_types": recent_question_types or [],
            "memory_context": memory_context,
            "force_hard_mode": force_hard_mode,
        }

        last_error: Optional[Exception] = None

        for provider_name in self.provider_chain:
            provider = self._providers.get(provider_name)
            if provider is None:
                continue
            if self._is_circuit_open(provider_name):
                logger.info(f"Skipping provider={provider_name} (circuit open).")
                continue

            timeout_s = self._provider_timeouts_s.get(provider_name, 30.0)
            emitted_any = False
            try:
                logger.info(f"Generating via provider={provider_name} (timeout={timeout_s:.1f}s)")
                async for token in self._stream_provider(
                    provider_name=provider_name,
                    provider=provider,
                    kwargs=kwargs,
                    timeout_s=timeout_s,
                ):
                    emitted_any = True
                    yield token
                self._mark_success(provider_name)
                self._sync_exposed_state(provider_name)
                return
            except Exception as exc:
                # Do not append fallback output after partial user-visible stream.
                if emitted_any:
                    self._mark_failure(provider_name)
                    self._sync_exposed_state(provider_name)
                    logger.error(
                        f"Provider {provider_name} failed after partial stream. "
                        "Stopping fallback chain to avoid mixed outputs."
                    )
                    return
                last_error = exc
                self._mark_failure(provider_name)
                logger.warning(
                    f"Provider failed provider={provider_name}: {exc}. Trying next fallback."
                )
                continue

        # Hard safety net (should not happen when degraded is in chain).
        degraded = self._providers.get("degraded", DegradedResponseAgent())
        self._sync_exposed_state("degraded")
        logger.error(f"All providers failed; using degraded fallback. Last error: {last_error}")
        async for token in self._stream_provider(
            provider_name="degraded",
            provider=degraded,
            kwargs=kwargs,
            timeout_s=self._provider_timeouts_s.get("degraded", 4.0),
        ):
            yield token

    def _iter_validation_providers(self):
        seen: set[str] = set()
        preferred = [
            self._active_provider_name,
            self.last_provider_used,
            "openai",
        ]
        for name in preferred:
            if not name or name in seen:
                continue
            provider = self._providers.get(name)
            if provider is None:
                continue
            seen.add(name)
            yield name, provider

        for name in self.provider_chain:
            if name in seen:
                continue
            provider = self._providers.get(name)
            if provider is None:
                continue
            seen.add(name)
            yield name, provider

    def _normalize_validation_report(
        self,
        report: object,
        response_text: str,
        question_type: str,
        kb_chunks: list[str],
    ) -> dict:
        default_reasons = [] if (response_text or "").strip() else ["empty_response"]
        if not isinstance(report, dict):
            return {
                "is_valid": bool((response_text or "").strip()),
                "reasons": default_reasons,
                "kb_hits": 0,
                "required_kb_hits": 2 if kb_chunks else 0,
                "contraction_ok": True,
                "star_components": 0,
                "star_ok": True,
                "question_type": question_type,
            }

        normalized = dict(report)
        normalized["is_valid"] = bool(normalized.get("is_valid", bool((response_text or "").strip())))
        reasons = normalized.get("reasons")
        if isinstance(reasons, list):
            normalized["reasons"] = [str(item) for item in reasons]
        elif reasons:
            normalized["reasons"] = [str(reasons)]
        else:
            normalized["reasons"] = default_reasons if not normalized["is_valid"] else []
        normalized.setdefault("kb_hits", 0)
        normalized.setdefault("required_kb_hits", 2 if kb_chunks else 0)
        normalized.setdefault("contraction_ok", True)
        normalized.setdefault("star_components", 0)
        normalized.setdefault("star_ok", True)
        normalized.setdefault("question_type", question_type)
        return normalized

    def _get_local_validator(self) -> OpenAIAgent:
        if self._local_validator is None:
            self._local_validator = OpenAIAgent()
        return self._local_validator

    def validate_generated_response(
        self,
        response_text: str,
        question_type: str,
        kb_chunks: list[str],
    ) -> dict:
        """
        Validate generated text with the best available validator.
        Prefers the active provider's validator, then OpenAI heuristics.
        """
        for provider_name, provider in self._iter_validation_providers():
            validator = getattr(provider, "validate_generated_response", None)
            if not callable(validator):
                continue
            try:
                report = validator(
                    response_text=response_text,
                    question_type=question_type,
                    kb_chunks=kb_chunks,
                )
                return self._normalize_validation_report(
                    report,
                    response_text=response_text,
                    question_type=question_type,
                    kb_chunks=kb_chunks,
                )
            except Exception as exc:
                logger.warning(
                    f"Validation failed for provider={provider_name}: {exc}"
                )

        try:
            report = self._get_local_validator().validate_generated_response(
                response_text=response_text,
                question_type=question_type,
                kb_chunks=kb_chunks,
            )
            return self._normalize_validation_report(
                report,
                response_text=response_text,
                question_type=question_type,
                kb_chunks=kb_chunks,
            )
        except Exception as exc:
            logger.warning(f"Local OpenAI validator unavailable: {exc}")

        return self._normalize_validation_report(
            report={},
            response_text=response_text,
            question_type=question_type,
            kb_chunks=kb_chunks,
        )

    async def generate_full(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
        recent_questions: Optional[list[str]] = None,
        recent_responses: Optional[list[str]] = None,
        recent_question_types: Optional[list[str]] = None,
        memory_context: Optional[str] = None,
        force_hard_mode: bool = False,
    ) -> str:
        """Generate a complete response in non-streaming form."""
        tokens: list[str] = []
        async for token in self.generate(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
            thinking_budget=thinking_budget,
            recent_questions=recent_questions,
            recent_responses=recent_responses,
            recent_question_types=recent_question_types,
            memory_context=memory_context,
            force_hard_mode=force_hard_mode,
        ):
            tokens.append(token)
        return "".join(tokens)

    async def generate_full_with_validation(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
        recent_questions: Optional[list[str]] = None,
        recent_responses: Optional[list[str]] = None,
        recent_question_types: Optional[list[str]] = None,
        memory_context: Optional[str] = None,
    ) -> tuple[str, dict]:
        """
        Generate a full response and validate it.
        Retries once with force_hard_mode=True when validation fails.
        """
        first = await self.generate_full(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
            thinking_budget=thinking_budget,
            recent_questions=recent_questions,
            recent_responses=recent_responses,
            recent_question_types=recent_question_types,
            memory_context=memory_context,
            force_hard_mode=False,
        )
        first_report = self.validate_generated_response(
            response_text=first,
            question_type=question_type,
            kb_chunks=kb_chunks,
        )
        if first_report.get("is_valid"):
            first_report["attempts"] = 1
            first_report["retried"] = False
            return first, first_report

        logger.warning(
            "Validation failed on first attempt; retrying with hard mode. "
            f"reasons={first_report.get('reasons', [])}"
        )
        second = await self.generate_full(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
            thinking_budget=thinking_budget,
            recent_questions=recent_questions,
            recent_responses=recent_responses,
            recent_question_types=recent_question_types,
            memory_context=memory_context,
            force_hard_mode=True,
        )
        second_report = self.validate_generated_response(
            response_text=second,
            question_type=question_type,
            kb_chunks=kb_chunks,
        )
        second_report["attempts"] = 2
        second_report["retried"] = True
        return second, second_report
