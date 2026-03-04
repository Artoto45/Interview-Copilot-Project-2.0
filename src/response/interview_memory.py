"""
Interview memory profile for cross-question consistency.

Tracks candidate facts observed in:
- candidate utterances
- generated answers
- KB chunks used in generated answers
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


_METRIC_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*%\s*(?:qa)?\b)|(?:\b\d+(?:\.\d+)?\s*(?:years?|months?|weeks?|days?|hours?|tickets?|cases?|qa)\b)",
    flags=re.IGNORECASE,
)
_MONEY_RE = re.compile(r"\$\s*\d+(?:[.,]\d+)?(?:\s*[kKmM])?")
_EMPLOYER_RE = re.compile(
    r"\b(?:at|with|in)\s+([A-Z][A-Za-z0-9&\-.]*(?:\s+[A-Z][A-Za-z0-9&\-.]*){0,2})"
)
_SPLIT_RE = re.compile(r"[.!?;\n]+")
_NORM_WS_RE = re.compile(r"\s+")

_STRENGTH_KEYWORDS = (
    "prioritize",
    "prioritization",
    "quality",
    "stakeholder",
    "stakeholders",
    "communication",
    "documentation",
    "escalation",
    "escalations",
    "collaboration",
    "collaborative",
    "ownership",
    "discipline",
    "adapt",
    "adaptability",
    "consistency",
)

_DOMAIN_KEYWORDS = (
    "webhelp",
    "bpo",
    "remote",
    "qa",
    "customer",
    "support",
    "operations",
    "python",
    "leadership",
    "stakeholder",
)

_CONSTRAINT_KEYWORDS = (
    "salary",
    "compensation",
    "notice",
    "start date",
    "start",
    "hybrid",
    "weekend",
    "schedule",
)


def _normalize_text(text: str) -> str:
    text = (text or "").strip()
    return _NORM_WS_RE.sub(" ", text)


def _norm_key(text: str) -> str:
    return _normalize_text(text).lower()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class MemoryFact:
    text: str
    category: str
    source: str
    first_seen_at: str = field(default_factory=_utc_now_iso)
    last_seen_at: str = field(default_factory=_utc_now_iso)
    hits: int = 1
    question_type: Optional[str] = None

    def touch(self, question_type: Optional[str] = None) -> None:
        self.last_seen_at = _utc_now_iso()
        self.hits += 1
        if question_type:
            self.question_type = question_type


class InterviewMemory:
    """
    Stores a compact dynamic profile to reduce contradictions and generic drift.
    """

    def __init__(self, max_facts_per_category: int = 24):
        self.max_facts_per_category = max(4, int(max_facts_per_category))
        self._facts_by_category: dict[str, dict[str, MemoryFact]] = {
            "metrics": {},
            "experiences": {},
            "strengths": {},
            "domains": {},
            "constraints": {},
        }

    def ingest_candidate_utterance(self, text: str) -> None:
        self._ingest_text(
            text=text,
            source="candidate",
            question_type=None,
            include_sentence_facts=True,
        )

    def ingest_generated_response(
        self,
        question: str,
        question_type: str,
        response: str,
        kb_chunks: list[str],
    ) -> None:
        self._ingest_text(
            text=response,
            source="generated_response",
            question_type=question_type,
            include_sentence_facts=True,
        )

        for chunk in (kb_chunks or [])[:3]:
            self._ingest_text(
                text=chunk,
                source="kb_context",
                question_type=question_type,
                include_sentence_facts=False,
            )

        # Keep short pointer to question intent, helps later ranking.
        q_norm = _normalize_text(question)
        if q_norm:
            self._store_fact(
                category="domains",
                text=f"recent question theme: {q_norm[:140]}",
                source="question_trace",
                question_type=question_type,
            )

    def snapshot(self) -> dict[str, list[dict]]:
        payload: dict[str, list[dict]] = {}
        for category, bucket in self._facts_by_category.items():
            rows = sorted(
                bucket.values(),
                key=lambda fact: (-fact.hits, fact.last_seen_at),
            )
            payload[category] = [
                {
                    "text": fact.text,
                    "source": fact.source,
                    "hits": fact.hits,
                    "last_seen_at": fact.last_seen_at,
                    "question_type": fact.question_type,
                }
                for fact in rows
            ]
        return payload

    def build_prompt_context(
        self,
        question: str,
        question_type: str,
        max_items: int = 10,
        max_chars: int = 1000,
    ) -> str:
        question_tokens = set(_norm_key(question).split())
        if not question_tokens:
            question_tokens = set()

        sections = []
        for category in (
            "experiences",
            "metrics",
            "strengths",
            "domains",
            "constraints",
        ):
            selected = self._rank_facts(
                category=category,
                question_tokens=question_tokens,
                question_type=question_type,
                max_items=max_items,
            )
            if not selected:
                continue
            lines = "\n".join(f"- {fact.text}" for fact in selected)
            sections.append(f"[{category.upper()}]\n{lines}")

        if not sections:
            return "[INTERVIEW MEMORY]\n[no prior profile facts yet]"

        body = "\n\n".join(sections)
        if len(body) > max_chars:
            body = body[: max_chars - 3].rstrip() + "..."

        return (
            "[INTERVIEW MEMORY]\n"
            f"{body}\n\n"
            "[CONSISTENCY RULES]\n"
            "- Keep these facts consistent unless the candidate explicitly corrects them.\n"
            "- Prefer specific facts over generic claims.\n"
            "- If a detail is uncertain, stay neutral instead of inventing."
        )

    def _ingest_text(
        self,
        text: str,
        source: str,
        question_type: Optional[str],
        include_sentence_facts: bool,
    ) -> None:
        text = _normalize_text(text)
        if not text:
            return

        lower = text.lower()

        for metric in _METRIC_RE.findall(text):
            self._store_fact(
                category="metrics",
                text=metric,
                source=source,
                question_type=question_type,
            )
        for amount in _MONEY_RE.findall(text):
            self._store_fact(
                category="metrics",
                text=amount,
                source=source,
                question_type=question_type,
            )

        for employer in _EMPLOYER_RE.findall(text):
            cleaned = _normalize_text(employer)
            if cleaned:
                self._store_fact(
                    category="experiences",
                    text=f"worked at {cleaned}",
                    source=source,
                    question_type=question_type,
                )

        for keyword in _STRENGTH_KEYWORDS:
            if keyword in lower:
                self._store_fact(
                    category="strengths",
                    text=keyword,
                    source=source,
                    question_type=question_type,
                )

        for keyword in _DOMAIN_KEYWORDS:
            if keyword in lower:
                self._store_fact(
                    category="domains",
                    text=keyword,
                    source=source,
                    question_type=question_type,
                )

        for keyword in _CONSTRAINT_KEYWORDS:
            if keyword in lower:
                self._store_fact(
                    category="constraints",
                    text=keyword,
                    source=source,
                    question_type=question_type,
                )

        if include_sentence_facts:
            for sentence in _SPLIT_RE.split(text):
                sentence = _normalize_text(sentence)
                if len(sentence) < 24:
                    continue
                if len(sentence.split()) > 18:
                    continue
                if any(char.isdigit() for char in sentence) or " at " in sentence.lower():
                    self._store_fact(
                        category="experiences",
                        text=sentence,
                        source=source,
                        question_type=question_type,
                    )

    def _store_fact(
        self,
        category: str,
        text: str,
        source: str,
        question_type: Optional[str],
    ) -> None:
        text = _normalize_text(text)
        if not text:
            return
        bucket = self._facts_by_category.get(category)
        if bucket is None:
            return

        key = _norm_key(text)
        existing = bucket.get(key)
        if existing:
            existing.touch(question_type=question_type)
            return

        bucket[key] = MemoryFact(
            text=text,
            category=category,
            source=source,
            question_type=question_type,
        )

        if len(bucket) > self.max_facts_per_category:
            self._trim_bucket(
                bucket=bucket,
                max_items=self.max_facts_per_category,
            )

    @staticmethod
    def _trim_bucket(
        bucket: dict[str, MemoryFact],
        max_items: int,
    ) -> None:
        keys = sorted(
            bucket.keys(),
            key=lambda k: (
                bucket[k].hits,
                bucket[k].last_seen_at,
                len(bucket[k].text),
            ),
        )
        while len(bucket) > 0 and len(keys) > 0 and len(bucket) > max_items:
            drop = keys.pop(0)
            bucket.pop(drop, None)

    def _rank_facts(
        self,
        category: str,
        question_tokens: set[str],
        question_type: str,
        max_items: int,
    ) -> list[MemoryFact]:
        bucket = self._facts_by_category.get(category, {})
        if not bucket:
            return []

        rows: list[tuple[float, MemoryFact]] = []
        for fact in bucket.values():
            tokens = set(_norm_key(fact.text).split())
            overlap = len(tokens & question_tokens)
            type_bonus = 1.0 if fact.question_type and fact.question_type == question_type else 0.0
            score = (fact.hits * 2.0) + (overlap * 1.8) + type_bonus
            rows.append((score, fact))

        rows.sort(key=lambda item: (item[0], item[1].last_seen_at), reverse=True)
        return [fact for _, fact in rows[: max(1, max_items)]]
