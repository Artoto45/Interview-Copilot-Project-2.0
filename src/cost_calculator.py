"""
Cost Calculator — Precise API Usage Cost Tracking
==================================================
Tracks consumption and calculates costs for:
    1. OpenAI Realtime API (dual-channel transcription)
    2. OpenAI Embeddings API (KB retrieval)
    3. Anthropic Claude API (response generation)
    4. Optional: Prometheus metrics storage

Architecture:
    - CostTracker: Global tracker (instantiated once in main)
    - CostEntry: Individual API call record
    - CostReport: Aggregated session report

Precision: Tracks bytes/tokens at the granular level for accuracy.
"""

import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from enum import Enum

from src.saldo import SaldoManager

logger = logging.getLogger("cost_calculator")


# ---------------------------------------------------------------------------
# Cost Configuration (Updated Q1 2025 rates)
# ---------------------------------------------------------------------------
class APIRates(Enum):
    """Current pricing from official APIs (as of March 2026)"""

    # Realtime transcription ($/minute audio)
    OPENAI_REALTIME_AUDIO = float(
        os.getenv("COST_OPENAI_REALTIME_AUDIO_PER_MINUTE", "0.020")
    ) / 60
    DEEPGRAM_REALTIME_AUDIO = float(
        os.getenv("COST_DEEPGRAM_REALTIME_AUDIO_PER_MINUTE", "0.0043")
    ) / 60

    # OpenAI Embeddings (text-embedding-3-small)
    OPENAI_EMBEDDING_INPUT = float(
        os.getenv("COST_OPENAI_EMBEDDING_INPUT_PER_1M", "0.020")
    ) / 1_000_000
    SYNTHETIC_OPENAI_EMBEDDING_INPUT = float(
        os.getenv(
            "COST_SYNTHETIC_OPENAI_EMBEDDING_INPUT_PER_1M",
            os.getenv("COST_OPENAI_EMBEDDING_INPUT_PER_1M", "0.020"),
        )
    ) / 1_000_000

    # OpenAI generation pricing (gpt-4o-mini)
    OPENAI_GPT4O_MINI_INPUT = float(
        os.getenv("COST_OPENAI_GPT4O_MINI_INPUT_PER_1M", "0.15")
    ) / 1_000_000
    OPENAI_GPT4O_MINI_OUTPUT = float(
        os.getenv("COST_OPENAI_GPT4O_MINI_OUTPUT_PER_1M", "0.60")
    ) / 1_000_000
    SYNTHETIC_OPENAI_GPT4O_MINI_INPUT = float(
        os.getenv(
            "COST_SYNTHETIC_OPENAI_GPT4O_MINI_INPUT_PER_1M",
            os.getenv("COST_OPENAI_GPT4O_MINI_INPUT_PER_1M", "0.15"),
        )
    ) / 1_000_000
    SYNTHETIC_OPENAI_GPT4O_MINI_OUTPUT = float(
        os.getenv(
            "COST_SYNTHETIC_OPENAI_GPT4O_MINI_OUTPUT_PER_1M",
            os.getenv("COST_OPENAI_GPT4O_MINI_OUTPUT_PER_1M", "0.60"),
        )
    ) / 1_000_000

    # Anthropic generation pricing (claude-3-5-sonnet/claude-sonnet families)
    CLAUDE_INPUT = float(
        os.getenv("COST_CLAUDE_INPUT_PER_1M", "3.0")
    ) / 1_000_000
    CLAUDE_OUTPUT = float(
        os.getenv("COST_CLAUDE_OUTPUT_PER_1M", "15.0")
    ) / 1_000_000
    CLAUDE_CACHE_WRITE = float(
        os.getenv("COST_CLAUDE_CACHE_WRITE_PER_1M", "3.75")
    ) / 1_000_000
    CLAUDE_CACHE_READ = float(
        os.getenv("COST_CLAUDE_CACHE_READ_PER_1M", "0.30")
    ) / 1_000_000

    # Gemini pricing
    GEMINI_INPUT = float(
        os.getenv("COST_GEMINI_INPUT_PER_1M", "1.25")
    ) / 1_000_000
    GEMINI_OUTPUT = float(
        os.getenv("COST_GEMINI_OUTPUT_PER_1M", "5.0")
    ) / 1_000_000
    DEGRADED_INPUT = 0.0
    DEGRADED_OUTPUT = 0.0


GENERATION_RATE_TABLE = {
    # OpenAI
    "openai_gpt_4o_mini": (
        APIRates.OPENAI_GPT4O_MINI_INPUT.value,
        APIRates.OPENAI_GPT4O_MINI_OUTPUT.value,
        0.0,
        0.0,
    ),
    "openai:gpt-4o-mini": (
        APIRates.OPENAI_GPT4O_MINI_INPUT.value,
        APIRates.OPENAI_GPT4O_MINI_OUTPUT.value,
        0.0,
        0.0,
    ),
    "synthetic_openai_gpt_4o_mini": (
        APIRates.SYNTHETIC_OPENAI_GPT4O_MINI_INPUT.value,
        APIRates.SYNTHETIC_OPENAI_GPT4O_MINI_OUTPUT.value,
        0.0,
        0.0,
    ),
    "synthetic:openai-gpt-4o-mini": (
        APIRates.SYNTHETIC_OPENAI_GPT4O_MINI_INPUT.value,
        APIRates.SYNTHETIC_OPENAI_GPT4O_MINI_OUTPUT.value,
        0.0,
        0.0,
    ),
    # Anthropic
    "claude_sonnet": (
        APIRates.CLAUDE_INPUT.value,
        APIRates.CLAUDE_OUTPUT.value,
        APIRates.CLAUDE_CACHE_WRITE.value,
        APIRates.CLAUDE_CACHE_READ.value,
    ),
    "anthropic:claude-sonnet": (
        APIRates.CLAUDE_INPUT.value,
        APIRates.CLAUDE_OUTPUT.value,
        APIRates.CLAUDE_CACHE_WRITE.value,
        APIRates.CLAUDE_CACHE_READ.value,
    ),
    # Gemini
    "gemini_flash": (
        APIRates.GEMINI_INPUT.value,
        APIRates.GEMINI_OUTPUT.value,
        0.0,
        0.0,
    ),
    "google:gemini-2.5-flash": (
        APIRates.GEMINI_INPUT.value,
        APIRates.GEMINI_OUTPUT.value,
        0.0,
        0.0,
    ),
    # Local degraded fallback mode (no external API cost)
    "degraded_local": (
        APIRates.DEGRADED_INPUT.value,
        APIRates.DEGRADED_OUTPUT.value,
        0.0,
        0.0,
    ),
    "degraded:local": (
        APIRates.DEGRADED_INPUT.value,
        APIRates.DEGRADED_OUTPUT.value,
        0.0,
        0.0,
    ),
}

EMBEDDING_RATE_TABLE = {
    "openai_embedding": APIRates.OPENAI_EMBEDDING_INPUT.value,
    "openai:text-embedding-3-small": APIRates.OPENAI_EMBEDDING_INPUT.value,
    "synthetic_openai_embedding": APIRates.SYNTHETIC_OPENAI_EMBEDDING_INPUT.value,
    "synthetic:openai-text-embedding-3-small": APIRates.SYNTHETIC_OPENAI_EMBEDDING_INPUT.value,
}


class CostCategory(Enum):
    """Cost categories for breakdown analysis"""

    TRANSCRIPTION_INPUT = "transcription_input"  # Audio → text (user)
    TRANSCRIPTION_INTERVIEWER = "transcription_interviewer"  # Audio → text (interviewer)
    EMBEDDING = "embedding"  # Question → embedding for KB search
    RETRIEVAL = "retrieval"  # KB lookup (assumed zero-cost)
    GENERATION = "generation"  # LLM response generation
    CACHE_WRITE = "cache_write"  # Prompt caching (first call)
    CACHE_READ = "cache_read"  # Prompt caching (subsequent calls)


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------
@dataclass
class CostEntry:
    """Single API call cost record"""

    timestamp: str
    category: CostCategory
    api_name: str  # "openai_realtime", "openai_embedding", "claude", etc.

    # Input metrics
    input_amount: float  # tokens or seconds (audio)
    input_unit: str  # "tokens", "seconds", "minutes"

    # Output metrics (if applicable)
    output_amount: Optional[float] = None
    output_unit: Optional[str] = None

    # Cache metrics (provider-dependent)
    cache_write_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None

    # Calculated cost
    cost_usd: float = 0.0

    # Context
    question_text: Optional[str] = None  # For debugging
    session_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Serialize to dict for JSON"""
        data = asdict(self)
        data["category"] = self.category.value
        return data


@dataclass
class SessionCostBreakdown:
    """Aggregated costs for a session"""

    session_id: str
    start_time: str
    end_time: str

    # Counters by category
    costs_by_category: Dict[str, float] = field(default_factory=dict)

    # API calls count
    api_calls_count: Dict[str, int] = field(default_factory=dict)

    # Token/duration totals
    transcription_user_minutes: float = 0.0
    transcription_interviewer_minutes: float = 0.0
    embedding_input_tokens: int = 0
    generation_input_tokens: int = 0
    generation_output_tokens: int = 0
    generation_cache_write_tokens: int = 0
    generation_cache_read_tokens: int = 0

    # Totals
    total_cost_usd: float = 0.0
    questions_processed: int = 0
    responses_generated: int = 0

    def add_cost_entry(self, entry: CostEntry):
        """Add a cost entry to this breakdown"""
        category = entry.category.value

        # Update category cost
        self.costs_by_category[category] = \
            self.costs_by_category.get(category, 0.0) + entry.cost_usd

        # Update API call count
        self.api_calls_count[entry.api_name] = \
            self.api_calls_count.get(entry.api_name, 0) + 1

        # Update totals
        self.total_cost_usd += entry.cost_usd

        # Update detailed metrics
        if entry.category == CostCategory.TRANSCRIPTION_INPUT:
            if "interviewer" in entry.api_name.lower():
                self.transcription_interviewer_minutes += entry.input_amount
            else:
                self.transcription_user_minutes += entry.input_amount

        elif entry.category == CostCategory.TRANSCRIPTION_INTERVIEWER:
            self.transcription_interviewer_minutes += entry.input_amount

        elif entry.category == CostCategory.EMBEDDING:
            self.embedding_input_tokens += int(entry.input_amount)

        elif entry.category == CostCategory.GENERATION:
            self.generation_input_tokens += int(entry.input_amount)
            if entry.output_amount:
                self.generation_output_tokens += int(entry.output_amount)

        elif entry.category == CostCategory.CACHE_WRITE:
            self.generation_cache_write_tokens += (
                entry.cache_write_tokens or 0
            )

        elif entry.category == CostCategory.CACHE_READ:
            self.generation_cache_read_tokens += (
                entry.cache_read_tokens or 0
            )


# ---------------------------------------------------------------------------
# Cost Tracker
# ---------------------------------------------------------------------------
class CostTracker:
    """
    Global cost tracker for a session.

    Usage in main.py:
        # In start_pipeline():
        pipeline.cost_tracker = CostTracker(session_id=session_id)

        # When transcription happens (automatic via callbacks):
        pipeline.cost_tracker.track_transcription(
            speaker="user",
            duration_seconds=5.2,
            api_name="openai_realtime_user"
        )

        # When embedding happens:
        pipeline.cost_tracker.track_embedding(
            tokens=150,
            question="Tell me about your background"
        )

        # When response model generates:
        pipeline.cost_tracker.track_generation(
            input_tokens=2048,
            output_tokens=256,
            cache_write_tokens=1024,
            cache_read_tokens=1024,
            question="...",
            api_name="openai_gpt_4o_mini",
        )

        # At session end:
        report = pipeline.cost_tracker.get_session_report()
        pipeline.cost_tracker.save_report(report)
    """

    def __init__(
        self,
        session_id: str,
        default_embedding_api_name: str = "openai_embedding",
    ):
        self.session_id = session_id
        self.start_time = datetime.now()
        self.entries: List[CostEntry] = []
        self.breakdown = SessionCostBreakdown(
            session_id=session_id,
            start_time=self.start_time.isoformat(),
            end_time="",
        )
        self.saldo_manager = SaldoManager()
        self.default_embedding_api_name = default_embedding_api_name

    def _register_entry(self, entry: CostEntry):
        self.entries.append(entry)
        self.breakdown.add_cost_entry(entry)
        self.saldo_manager.record_cost(entry.api_name, entry.cost_usd)

    def track_transcription(
        self,
        speaker: str,
        duration_seconds: float,
        api_name: str = "openai_realtime_user",
    ):
        """
        Track transcription API cost.

        Args:
            speaker: "user" or "interviewer"
            duration_seconds: Length of audio segment
            api_name: e.g. "openai_realtime_user", "deepgram_interviewer"
        """
        duration_minutes = duration_seconds / 60.0

        category = (
            CostCategory.TRANSCRIPTION_INPUT
            if speaker == "user"
            else CostCategory.TRANSCRIPTION_INTERVIEWER
        )

        api_lower = (api_name or "").lower()
        if "deepgram" in api_lower:
            rate = APIRates.DEEPGRAM_REALTIME_AUDIO.value
        else:
            rate = APIRates.OPENAI_REALTIME_AUDIO.value

        cost = duration_minutes * rate

        entry = CostEntry(
            timestamp=datetime.now().isoformat(),
            category=category,
            api_name=api_name,
            input_amount=duration_minutes,
            input_unit="minutes",
            cost_usd=cost,
            session_id=self.session_id,
        )

        self._register_entry(entry)

        logger.debug(
            f"Transcription ({speaker}): "
            f"{duration_seconds:.2f}s → ${cost:.6f}"
        )

    def track_embedding(
        self,
        tokens: int,
        question: Optional[str] = None,
        api_name: Optional[str] = None,
    ):
        """
        Track embedding API cost.

        Args:
            tokens: Number of input tokens
            question: Original question (for context)
            api_name: Embedding pricing key. Uses tracker default when omitted.
        """
        resolved_api_name = api_name or self.default_embedding_api_name
        rate = self._resolve_embedding_rate(resolved_api_name)
        cost = tokens * rate

        entry = CostEntry(
            timestamp=datetime.now().isoformat(),
            category=CostCategory.EMBEDDING,
            api_name=resolved_api_name,
            input_amount=tokens,
            input_unit="tokens",
            cost_usd=cost,
            question_text=question[:100] if question else None,
            session_id=self.session_id,
        )

        self._register_entry(entry)

        logger.debug(
            f"Embedding: {tokens} tokens → ${cost:.6f}"
        )

    def track_generation(
        self,
        input_tokens: int,
        output_tokens: int,
        question: Optional[str] = None,
        api_name: str = "openai_gpt_4o_mini",
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ):
        """
        Track generation cost for the active LLM provider.

        Args:
            input_tokens: Input tokens to model
            output_tokens: Output tokens from model
            question: Original question (for context)
            api_name: Pricing key (e.g. openai_gpt_4o_mini, claude_sonnet)
            cache_write_tokens: Tokens written to cache (first call)
            cache_read_tokens: Tokens read from cache (subsequent)
        """
        (
            input_rate,
            output_rate,
            cache_write_rate,
            cache_read_rate,
        ) = self._resolve_generation_rates(api_name)

        # Input/output cost (always charged)
        input_cost = input_tokens * input_rate
        output_cost = output_tokens * output_rate

        # Cache costs (mutually exclusive: write OR read, not both)
        cache_cost = 0.0

        if cache_write_tokens > 0:
            cache_cost = cache_write_tokens * cache_write_rate
            if cache_write_rate > 0:
                self._register_entry(
                    CostEntry(
                        timestamp=datetime.now().isoformat(),
                        category=CostCategory.CACHE_WRITE,
                        api_name=api_name,
                        input_amount=cache_write_tokens,
                        input_unit="tokens",
                        cache_write_tokens=cache_write_tokens,
                        cost_usd=cache_cost,
                        question_text=question[:100] if question else None,
                        session_id=self.session_id,
                    )
                )
        elif cache_read_tokens > 0:
            cache_cost = cache_read_tokens * cache_read_rate
            if cache_read_rate > 0:
                self._register_entry(
                    CostEntry(
                        timestamp=datetime.now().isoformat(),
                        category=CostCategory.CACHE_READ,
                        api_name=api_name,
                        input_amount=cache_read_tokens,
                        input_unit="tokens",
                        cache_read_tokens=cache_read_tokens,
                        cost_usd=cache_cost,
                        question_text=question[:100] if question else None,
                        session_id=self.session_id,
                    )
                )

        generation_cost = input_cost + output_cost
        total_with_cache = generation_cost + cache_cost

        # Generation entry
        entry = CostEntry(
            timestamp=datetime.now().isoformat(),
            category=CostCategory.GENERATION,
            api_name=api_name,
            input_amount=input_tokens,
            input_unit="tokens",
            output_amount=output_tokens,
            output_unit="tokens",
            cache_write_tokens=cache_write_tokens if cache_write_tokens > 0 else None,
            cache_read_tokens=cache_read_tokens if cache_read_tokens > 0 else None,
            cost_usd=generation_cost,
            question_text=question[:100] if question else None,
            session_id=self.session_id,
        )

        self._register_entry(entry)

        logger.debug(
            f"Generation: {input_tokens} in + {output_tokens} out → "
            f"${total_with_cache:.6f} "
            f"(cache: {cache_write_tokens} write, {cache_read_tokens} read)"
        )

    @staticmethod
    def _resolve_generation_rates(api_name: str) -> tuple[float, float, float, float]:
        rates = GENERATION_RATE_TABLE.get(api_name)
        if rates:
            return rates

        logger.warning(
            f"Unknown generation api_name='{api_name}', "
            "falling back to openai_gpt_4o_mini rates"
        )
        return GENERATION_RATE_TABLE["openai_gpt_4o_mini"]

    @staticmethod
    def _resolve_embedding_rate(api_name: str) -> float:
        rate = EMBEDDING_RATE_TABLE.get(api_name)
        if rate is not None:
            return rate

        logger.warning(
            f"Unknown embedding api_name='{api_name}', "
            "falling back to openai_embedding rates"
        )
        return EMBEDDING_RATE_TABLE["openai_embedding"]

    def get_session_report(self) -> SessionCostBreakdown:
        """Get final breakdown for session"""
        self.breakdown.end_time = datetime.now().isoformat()
        return self.breakdown

    def get_saldo_snapshot(self) -> dict:
        elapsed_minutes = (datetime.now() - self.start_time).total_seconds() / 60.0
        return self.saldo_manager.build_snapshot(elapsed_minutes)

    def save_report(self, report: SessionCostBreakdown, output_dir: Optional[Path] = None):
        """
        Save cost report to JSON.

        Args:
            report: The SessionCostBreakdown to save
            output_dir: Directory to save to (default: ./logs)
        """
        if output_dir is None:
            output_dir = Path(__file__).parent.parent / "logs"

        output_dir.mkdir(parents=True, exist_ok=True)

        # Create report file
        report_path = output_dir / f"costs_{report.session_id}.json"

        # Serialize report
        report_dict = {
            "session_id": report.session_id,
            "start_time": report.start_time,
            "end_time": report.end_time,
            "costs_by_category": report.costs_by_category,
            "api_calls_count": report.api_calls_count,
            "saldo": self.get_saldo_snapshot(),
            "metrics": {
                "transcription_user_minutes": report.transcription_user_minutes,
                "transcription_interviewer_minutes": report.transcription_interviewer_minutes,
                "embedding_input_tokens": report.embedding_input_tokens,
                "generation_input_tokens": report.generation_input_tokens,
                "generation_output_tokens": report.generation_output_tokens,
                "generation_cache_write_tokens": report.generation_cache_write_tokens,
                "generation_cache_read_tokens": report.generation_cache_read_tokens,
            },
            "totals": {
                "total_cost_usd": round(report.total_cost_usd, 6),
                "questions_processed": report.questions_processed,
                "responses_generated": report.responses_generated,
            },
            "cost_breakdown": {
                cat: round(cost, 6)
                for cat, cost in report.costs_by_category.items()
            }
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2, ensure_ascii=False)

        logger.info(f"Cost report saved: {report_path}")
        self._log_report_summary(report)

    def _log_report_summary(self, report: SessionCostBreakdown):
        """Log a summary of the cost report"""
        logger.info("=" * 60)
        logger.info("SESSION COST REPORT")
        logger.info("=" * 60)
        logger.info(f"Session ID: {report.session_id}")
        logger.info(f"Duration: {report.start_time} → {report.end_time}")
        logger.info("")
        logger.info("COST BREAKDOWN BY CATEGORY:")
        for cat, cost in sorted(report.costs_by_category.items()):
            logger.info(f"  {cat:30s}: ${cost:8.6f}")
        logger.info("")
        logger.info("API CALLS COUNT:")
        for api, count in sorted(report.api_calls_count.items()):
            logger.info(f"  {api:30s}: {count:4d} calls")
        logger.info("")
        logger.info("USAGE METRICS:")
        logger.info(f"  Transcription (user):          {report.transcription_user_minutes:8.2f} minutes")
        logger.info(f"  Transcription (interviewer):   {report.transcription_interviewer_minutes:8.2f} minutes")
        logger.info(f"  Embedding input tokens:        {report.embedding_input_tokens:10d}")
        logger.info(f"  Generation input tokens:       {report.generation_input_tokens:10d}")
        logger.info(f"  Generation output tokens:      {report.generation_output_tokens:10d}")
        logger.info(f"  Generation cache write tokens: {report.generation_cache_write_tokens:10d}")
        logger.info(f"  Generation cache read tokens:  {report.generation_cache_read_tokens:10d}")
        logger.info("")
        logger.info("TOTALS:")
        logger.info(f"  Total Cost:                    ${report.total_cost_usd:10.6f}")
        logger.info(f"  Questions Processed:           {report.questions_processed:10d}")
        logger.info(f"  Responses Generated:           {report.responses_generated:10d}")
        saldo = self.get_saldo_snapshot()
        fuel = saldo.get("fuel_gauge", {})
        logger.info("BALANCE / FUEL GAUGE:")
        for provider, info in saldo.get("providers", {}).items():
            logger.info(
                f"  {provider:30s}: ${info['remaining_usd']:10.4f} "
                f"({info['human_readable_remaining']})"
            )
        logger.info(
            "  bottleneck: "
            f"{fuel.get('bottleneck_provider')} "
            f"({fuel.get('human_readable_until_any_depletion')})"
        )
        logger.info("=" * 60)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def estimate_tokens(text: str) -> int:
    """
    Rough estimate of token count for text.

    OpenAI models: ~4 characters ≈ 1 token (average)
    More accurate: use tiktoken library
    """
    return max(1, len(text) // 4)


def estimate_embedding_tokens(question: str) -> int:
    """Estimate tokens for embedding input"""
    # text-embedding-3-small: typically 50-500 tokens for questions
    return estimate_tokens(question)


def format_cost_for_display(cost_usd: float) -> str:
    """Format cost for user display"""
    if cost_usd < 0.001:
        return f"${cost_usd*1_000_000:.2f}µ"  # Micro-dollars
    elif cost_usd < 0.01:
        return f"${cost_usd*1000:.2f}m"  # Milli-dollars
    else:
        return f"${cost_usd:.4f}"

