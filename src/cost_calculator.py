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
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from enum import Enum

logger = logging.getLogger("cost_calculator")


# ---------------------------------------------------------------------------
# Cost Configuration (Updated Q1 2025 rates)
# ---------------------------------------------------------------------------
class APIRates(Enum):
    """Current pricing from official APIs (as of March 2026)"""

    # OpenAI Realtime API (gpt-4o-mini-transcribe)
    OPENAI_REALTIME_INPUT = 0.020 / 60  # $0.020 per minute of input audio
    OPENAI_REALTIME_OUTPUT = 0.020 / 60  # $0.020 per minute of output audio

    # OpenAI Embeddings (text-embedding-3-small)
    OPENAI_EMBEDDING_INPUT = 0.020 / 1_000_000  # $0.020 per 1M input tokens

    # Anthropic Claude API (claude-3-5-sonnet-20250514)
    CLAUDE_INPUT = 3.0 / 1_000_000  # $3.00 per 1M input tokens
    CLAUDE_OUTPUT = 15.0 / 1_000_000  # $15.00 per 1M output tokens
    CLAUDE_CACHE_WRITE = 3.75 / 1_000_000  # $3.75 per 1M cache write tokens
    CLAUDE_CACHE_READ = 0.30 / 1_000_000  # $0.30 per 1M cache read tokens (90% discount)

    # Gemini 3.1 Pro (for agent use, not in pipeline currently)
    GEMINI_INPUT = 1.25 / 1_000_000  # $1.25 per 1M input tokens
    GEMINI_OUTPUT = 5.0 / 1_000_000  # $5.00 per 1M output tokens


class CostCategory(Enum):
    """Cost categories for breakdown analysis"""

    TRANSCRIPTION_INPUT = "transcription_input"  # Audio → text (user)
    TRANSCRIPTION_INTERVIEWER = "transcription_interviewer"  # Audio → text (interviewer)
    EMBEDDING = "embedding"  # Question → embedding for KB search
    RETRIEVAL = "retrieval"  # KB lookup (assumed zero-cost)
    GENERATION = "generation"  # Claude response generation
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

    # Cache metrics (Claude only)
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
    claude_input_tokens: int = 0
    claude_output_tokens: int = 0
    claude_cache_write_tokens: int = 0
    claude_cache_read_tokens: int = 0

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
            if "user" in entry.api_name.lower():
                self.transcription_user_minutes += entry.input_amount
            elif "interviewer" in entry.api_name.lower():
                self.transcription_interviewer_minutes += entry.input_amount

        elif entry.category == CostCategory.EMBEDDING:
            self.embedding_input_tokens += int(entry.input_amount)

        elif entry.category == CostCategory.GENERATION:
            self.claude_input_tokens += int(entry.input_amount)
            if entry.output_amount:
                self.claude_output_tokens += int(entry.output_amount)

        elif entry.category == CostCategory.CACHE_WRITE:
            self.claude_cache_write_tokens += entry.cache_write_tokens or 0

        elif entry.category == CostCategory.CACHE_READ:
            self.claude_cache_read_tokens += entry.cache_read_tokens or 0


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

        # When Claude generates:
        pipeline.cost_tracker.track_generation(
            input_tokens=2048,
            output_tokens=256,
            cache_write_tokens=1024,
            cache_read_tokens=1024,
            question="...",
        )

        # At session end:
        report = pipeline.cost_tracker.get_session_report()
        pipeline.cost_tracker.save_report(report)
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.start_time = datetime.now()
        self.entries: List[CostEntry] = []
        self.breakdown = SessionCostBreakdown(
            session_id=session_id,
            start_time=self.start_time.isoformat(),
            end_time="",
        )

    def track_transcription(
        self,
        speaker: str,
        duration_seconds: float,
        api_name: str = "openai_realtime",
    ):
        """
        Track transcription API cost.

        Args:
            speaker: "user" or "interviewer"
            duration_seconds: Length of audio segment
            api_name: "openai_realtime_user" or "openai_realtime_interviewer"
        """
        duration_minutes = duration_seconds / 60.0

        # Determine category and rate
        if speaker == "user":
            category = CostCategory.TRANSCRIPTION_INPUT
            rate = APIRates.OPENAI_REALTIME_INPUT.value
            api_name = api_name or "openai_realtime_user"
        else:
            category = CostCategory.TRANSCRIPTION_INTERVIEWER
            rate = APIRates.OPENAI_REALTIME_OUTPUT.value
            api_name = api_name or "openai_realtime_interviewer"

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

        self.entries.append(entry)
        self.breakdown.add_cost_entry(entry)

        logger.debug(
            f"Transcription ({speaker}): "
            f"{duration_seconds:.2f}s → ${cost:.6f}"
        )

    def track_embedding(
        self,
        tokens: int,
        question: Optional[str] = None,
        api_name: str = "openai_embedding",
    ):
        """
        Track embedding API cost.

        Args:
            tokens: Number of input tokens
            question: Original question (for context)
            api_name: "openai_embedding" typically
        """
        rate = APIRates.OPENAI_EMBEDDING_INPUT.value
        cost = tokens * rate

        entry = CostEntry(
            timestamp=datetime.now().isoformat(),
            category=CostCategory.EMBEDDING,
            api_name=api_name,
            input_amount=tokens,
            input_unit="tokens",
            cost_usd=cost,
            question_text=question[:100] if question else None,
            session_id=self.session_id,
        )

        self.entries.append(entry)
        self.breakdown.add_cost_entry(entry)

        logger.debug(
            f"Embedding: {tokens} tokens → ${cost:.6f}"
        )

    def track_generation(
        self,
        input_tokens: int,
        output_tokens: int,
        question: Optional[str] = None,
        api_name: str = "claude_sonnet",
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ):
        """
        Track Claude API generation cost.

        Args:
            input_tokens: Input tokens to Claude
            output_tokens: Output tokens from Claude
            question: Original question (for context)
            api_name: "claude_sonnet" typically
            cache_write_tokens: Tokens written to cache (first call)
            cache_read_tokens: Tokens read from cache (subsequent)
        """
        # Input cost (always charged)
        input_cost = input_tokens * APIRates.CLAUDE_INPUT.value

        # Output cost (always charged)
        output_cost = output_tokens * APIRates.CLAUDE_OUTPUT.value

        # Cache costs (mutually exclusive: write OR read, not both)
        cache_cost = 0.0
        cache_category = None

        if cache_write_tokens > 0:
            cache_cost = cache_write_tokens * APIRates.CLAUDE_CACHE_WRITE.value
            cache_category = CostCategory.CACHE_WRITE
        elif cache_read_tokens > 0:
            cache_cost = cache_read_tokens * APIRates.CLAUDE_CACHE_READ.value
            cache_category = CostCategory.CACHE_READ

        total_cost = input_cost + output_cost + cache_cost

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
            cost_usd=total_cost,
            question_text=question[:100] if question else None,
            session_id=self.session_id,
        )

        self.entries.append(entry)
        self.breakdown.add_cost_entry(entry)

        logger.debug(
            f"Generation: {input_tokens} in + {output_tokens} out → "
            f"${total_cost:.6f} "
            f"(cache: {cache_write_tokens} write, {cache_read_tokens} read)"
        )

    def get_session_report(self) -> SessionCostBreakdown:
        """Get final breakdown for session"""
        self.breakdown.end_time = datetime.now().isoformat()
        return self.breakdown

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
            "metrics": {
                "transcription_user_minutes": report.transcription_user_minutes,
                "transcription_interviewer_minutes": report.transcription_interviewer_minutes,
                "embedding_input_tokens": report.embedding_input_tokens,
                "claude_input_tokens": report.claude_input_tokens,
                "claude_output_tokens": report.claude_output_tokens,
                "claude_cache_write_tokens": report.claude_cache_write_tokens,
                "claude_cache_read_tokens": report.claude_cache_read_tokens,
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
        logger.info(f"  Claude input tokens:           {report.claude_input_tokens:10d}")
        logger.info(f"  Claude output tokens:          {report.claude_output_tokens:10d}")
        logger.info(f"  Claude cache write tokens:     {report.claude_cache_write_tokens:10d}")
        logger.info(f"  Claude cache read tokens:      {report.claude_cache_read_tokens:10d}")
        logger.info("")
        logger.info("TOTALS:")
        logger.info(f"  Total Cost:                    ${report.total_cost_usd:10.6f}")
        logger.info(f"  Questions Processed:           {report.questions_processed:10d}")
        logger.info(f"  Responses Generated:           {report.responses_generated:10d}")
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

