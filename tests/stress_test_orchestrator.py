"""
Strict Stress Test Orchestrator
===============================
Simulates long, realistic interviews with:
- greetings and small talk
- natural transitions and feedback statements
- core interview questions and micro-follow-ups
- candidate questions (role, salary, company)
- closing

Modes:
- synthetic: fully offline (no external API calls)
- api: uses real retrieval/generation APIs

Outputs detailed metrics for:
- question filter precision/recall
- transition over-reactivity
- classifier accuracy
- response repetition signals
- estimated cost and fuel gauge
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import re
import statistics
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.cost_calculator import CostTracker, estimate_tokens
from src.knowledge.classifier import QuestionClassifier
from src.knowledge.question_filter import QuestionFilter
from src.knowledge.retrieval import KnowledgeRetriever
from src.response.openai_agent import OpenAIAgent
from src.response.interview_memory import InterviewMemory


def _normalize(text: str) -> str:
    cleaned = (text or "").strip().lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _opener_signature(text: str) -> str:
    cleaned = _normalize(text)
    if not cleaned:
        return ""
    first_clause = re.split(r"[.!?]", cleaned)[0]
    words = first_clause.split()
    return " ".join(words[:6])


def _ngram_set(text: str, n: int = 3) -> set[str]:
    tokens = _normalize(text).split()
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[idx:idx + n]) for idx in range(len(tokens) - n + 1)}


def _jaccard(a: str, b: str) -> float:
    sa = _ngram_set(a, 3)
    sb = _ngram_set(b, 3)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _redteam_intensity(level: str) -> float:
    mapping = {
        "none": 0.0,
        "standard": 0.35,
        "extreme": 0.70,
    }
    return mapping.get((level or "none").lower(), 0.0)


@dataclass
class SimEvent:
    interview_id: int
    minute: float
    speaker: str
    text: str
    event_kind: str
    expected_is_question: bool
    expected_type: Optional[str] = None
    duration_seconds: float = 8.0


class InterviewScenarioGenerator:
    """
    Produces realistic interview timelines with deterministic randomness.
    """

    def __init__(self, seed: int = 7):
        self.rng = random.Random(seed)

        self.opening_small_talk = [
            "Hi, thanks for joining today.",
            "Hope your day is going well so far.",
            "Before we start, did you have any trouble finding us online?",
            "Great, let's get comfortable and begin.",
        ]

        self.transition_feedback = [
            "That's a solid example, thanks for sharing.",
            "Great context, that helps a lot.",
            "Perfect, let's keep moving.",
            "That was clear and structured.",
            "If you'd like to continue, I'm ready for the next step!",
            "That's a strong demonstration of quality despite pressure.",
            "If you'd like to tackle another scenario or pivot to a different focus, just let me know!",
            "That approach sounds practical and consistent.",
        ]

        self.redteam_transition_traps = [
            "Interesting point. We're good to keep moving if that works for you.",
            "That context is clear; we can continue whenever you're comfortable.",
            "Nice summary so far, and we can pause here if needed.",
        ]

        self.personal_questions = [
            "Tell me about yourself and your background in customer operations.",
            "What would your previous manager say are your biggest strengths?",
            "Walk me through your experience supporting remote teams.",
            "What achievement are you most proud of in your last role?",
        ]

        self.situational_questions = [
            "Describe a time when you had to manage multiple stakeholders with conflicting priorities.",
            "How did you handle a deadline crisis when the scope changed at the last minute?",
            "Give me an example of a difficult customer escalation and how you resolved it.",
            "Can you describe a situation where you had to make an unpopular decision for the business?",
            "Walk me through a time you had to de-escalate an angry customer quickly.",
        ]

        self.company_questions = [
            "What do you know about our company, and why do you want to join this team?",
            "How does this role align with your long-term career goals?",
            "What attracted you to our mission and culture specifically?",
        ]

        self.hybrid_questions = [
            "Why should we hire you for this role, and how would you ramp up in your first month?",
            "How would your experience help you collaborate with product and operations here?",
            "What motivates you, and how does that connect with what this team needs?",
        ]

        self.simple_questions = [
            "How soon could you start if selected?",
            "Are you comfortable with a hybrid schedule and occasional weekend support?",
            "What salary range are you targeting for this role?",
            "Do you need to provide notice at your current job?",
        ]

        self.micro_followups = [
            "What was the hardest part?",
            "What changed after that?",
            "How did you measure success?",
            "What would you do differently next time?",
        ]

        self.redteam_questions: list[tuple[str, str]] = [
            (
                "You can only pick one: speed or quality. Why would you sacrifice the other in a customer escalation?",
                "hybrid",
            ),
            (
                "I need an answer in ten seconds: explain a conflict, your mistake, and the exact business impact.",
                "situational",
            ),
            (
                "Suppose leadership asks for a policy exception that violates SOP. How do you push back without damaging trust?",
                "situational",
            ),
            (
                "Give me your salary expectation, then immediately justify why we'd still choose you if we're over budget.",
                "hybrid",
            ),
            (
                "Tell me one metric you would improve first, and defend why all other metrics can wait.",
                "simple",
            ),
        ]

        self.redteam_interruptions = [
            "Wait, pause there.",
            "No, that's not what I asked.",
            "Hold on, let me reframe this quickly.",
        ]

        self.candidate_questions = [
            "Could you share how success is measured in the first 90 days?",
            "How is the compensation band structured for this role?",
            "What are the team's biggest priorities this quarter?",
            "How does the company support growth and internal mobility?",
        ]

        self.candidate_answer_templates = [
            "Sure, I can walk through that.",
            "Absolutely, here's how I approached it.",
            "Great question, in my role I focused on quality and speed.",
            "Yes, and I can give a concrete example from Webhelp.",
        ]

        self.interviewer_answers_to_candidate = [
            "Great question. In the first 90 days we focus on ramp-up, consistency, and ownership.",
            "Compensation depends on level and location, and includes performance bonuses.",
            "Top priorities are service quality, reduced escalations, and faster resolution time.",
            "We support growth through mentoring, shadowing, and internal projects.",
        ]

        self.closing_turns = [
            "Thanks for your time today. We appreciate your thoughtful answers.",
            "We'll review everything and follow up with next steps soon.",
            "It was great meeting you. Have a great rest of your day.",
        ]

        self._question_pool = [
            ("personal", self.personal_questions),
            ("situational", self.situational_questions),
            ("company", self.company_questions),
            ("hybrid", self.hybrid_questions),
            ("simple", self.simple_questions),
        ]

    def _pick(self, values: list[str]) -> str:
        return self.rng.choice(values)

    def _append(
        self,
        events: list[SimEvent],
        interview_id: int,
        minute: float,
        speaker: str,
        text: str,
        event_kind: str,
        expected_is_question: bool,
        expected_type: Optional[str] = None,
        duration_seconds: float = 8.0,
    ) -> None:
        events.append(
            SimEvent(
                interview_id=interview_id,
                minute=round(minute, 3),
                speaker=speaker,
                text=text,
                event_kind=event_kind,
                expected_is_question=expected_is_question,
                expected_type=expected_type,
                duration_seconds=duration_seconds,
            )
        )

    def _main_question(self) -> tuple[str, str]:
        q_type, pool = self.rng.choice(self._question_pool)
        return q_type, self._pick(pool)

    def generate_interview(
        self,
        interview_id: int,
        duration_minutes: float,
        redteam_intensity: float = 0.0,
    ) -> list[SimEvent]:
        events: list[SimEvent] = []
        minute = 0.0

        # Opening and small talk.
        for text in self.opening_small_talk:
            self._append(
                events,
                interview_id,
                minute,
                "interviewer",
                text,
                "small_talk",
                expected_is_question=False,
                duration_seconds=6.0,
            )
            minute += 0.35

        # Main interview loop.
        while minute < max(8.0, duration_minutes - 4.5):
            if redteam_intensity > 0 and self.rng.random() < (redteam_intensity * 0.40):
                self._append(
                    events,
                    interview_id,
                    minute,
                    "interviewer",
                    self._pick(self.redteam_transition_traps),
                    "redteam_transition_trap",
                    expected_is_question=False,
                    duration_seconds=4.5,
                )
                minute += self.rng.uniform(0.16, 0.35)

            feedback = self._pick(self.transition_feedback)
            self._append(
                events,
                interview_id,
                minute,
                "interviewer",
                feedback,
                "transition",
                expected_is_question=False,
                duration_seconds=5.0,
            )
            minute += self.rng.uniform(0.20, 0.45)

            if redteam_intensity > 0 and self.rng.random() < redteam_intensity:
                question, q_type = self._pick(self.redteam_questions)
                q_kind = "redteam_question"
            else:
                q_type, question = self._main_question()
                q_kind = "main_question"
            self._append(
                events,
                interview_id,
                minute,
                "interviewer",
                question,
                q_kind,
                expected_is_question=True,
                expected_type=q_type,
                duration_seconds=self.rng.uniform(10.0, 18.0),
            )
            minute += self.rng.uniform(0.35, 0.90)

            # Candidate answer turn.
            self._append(
                events,
                interview_id,
                minute,
                "candidate",
                self._pick(self.candidate_answer_templates),
                "candidate_answer",
                expected_is_question=False,
                duration_seconds=self.rng.uniform(9.0, 20.0),
            )
            minute += self.rng.uniform(0.30, 0.75)

            if redteam_intensity > 0 and self.rng.random() < (redteam_intensity * 0.35):
                self._append(
                    events,
                    interview_id,
                    minute,
                    "interviewer",
                    self._pick(self.redteam_interruptions),
                    "redteam_interruption",
                    expected_is_question=False,
                    duration_seconds=self.rng.uniform(2.5, 4.0),
                )
                minute += self.rng.uniform(0.10, 0.24)

            # Optional micro follow-up.
            if self.rng.random() < 0.55:
                followup = self._pick(self.micro_followups)
                self._append(
                    events,
                    interview_id,
                    minute,
                    "interviewer",
                    followup,
                    "micro_question",
                    expected_is_question=True,
                    expected_type="situational",
                    duration_seconds=self.rng.uniform(4.0, 9.0),
                )
                minute += self.rng.uniform(0.18, 0.45)

                self._append(
                    events,
                    interview_id,
                    minute,
                    "candidate",
                    "I can explain that briefly with a specific result.",
                    "candidate_answer",
                    expected_is_question=False,
                    duration_seconds=self.rng.uniform(8.0, 14.0),
                )
                minute += self.rng.uniform(0.20, 0.50)

            # Candidate asks interviewer about role/company/salary.
            if self.rng.random() < 0.35:
                self._append(
                    events,
                    interview_id,
                    minute,
                    "candidate",
                    self._pick(self.candidate_questions),
                    "candidate_question",
                    expected_is_question=False,
                    duration_seconds=self.rng.uniform(7.0, 14.0),
                )
                minute += self.rng.uniform(0.20, 0.40)

                self._append(
                    events,
                    interview_id,
                    minute,
                    "interviewer",
                    self._pick(self.interviewer_answers_to_candidate),
                    "interviewer_answer",
                    expected_is_question=False,
                    duration_seconds=self.rng.uniform(9.0, 16.0),
                )
                minute += self.rng.uniform(0.22, 0.55)

        # Closing.
        for text in self.closing_turns:
            self._append(
                events,
                interview_id,
                minute,
                "interviewer",
                text,
                "closing",
                expected_is_question=False,
                duration_seconds=7.0,
            )
            minute += 0.35

        return events

    def generate_batch(
        self,
        interviews: int,
        minutes_per_interview: float,
        redteam_level: str = "none",
    ) -> list[SimEvent]:
        all_events: list[SimEvent] = []
        intensity = _redteam_intensity(redteam_level)
        for interview_id in range(1, interviews + 1):
            all_events.extend(
                self.generate_interview(
                    interview_id=interview_id,
                    duration_minutes=minutes_per_interview,
                    redteam_intensity=intensity,
                )
            )
        return all_events


class SyntheticKnowledgeRetriever:
    """
    Offline retriever that intentionally includes duplicates and overlapping
    chunks to stress post-processing and source diversity.
    """

    KB = {
        "personal": [
            "I have more than three years in BPO support at Webhelp with remote operations.",
            "I kept a 92% QA score by verifying each case before closing.",
            "I organize urgent tickets first and keep documentation updated daily.",
            "I collaborate with QA and operations to reduce repeat incidents.",
        ],
        "situational": [
            "In escalation scenarios, I de-escalated customers while preserving policy and empathy.",
            "When priorities conflicted, I mapped urgency and stakeholders and sent clear updates.",
            "During scope changes, I split work into small blocks and validated each step.",
            "My actions helped maintain 92% QA while handling high-volume queues.",
        ],
        "company": [
            "I am aligned with a customer-first culture and continuous improvement mindset.",
            "I value measurable service quality, transparency, and team collaboration.",
            "I am motivated by roles where operational excellence and learning are central.",
        ],
        "hybrid": [
            "My background combines frontline support execution and process discipline.",
            "I can ramp quickly by aligning with SOPs, metrics, and stakeholder priorities.",
            "I bring structured communication and reliable follow-through under pressure.",
        ],
        "simple": [
            "I can start quickly and coordinate a formal notice period when needed.",
            "I am open to hybrid schedules and periodic weekend support.",
            "I can discuss salary expectations based on responsibilities and market range.",
        ],
    }

    async def retrieve(
        self,
        query: str,
        question_type: str = "personal",
        top_k: Optional[int] = None,
        category_filter: Optional[str] = None,
    ) -> list[str]:
        pool = list(self.KB.get(question_type, self.KB["personal"]))
        rng = random.Random(abs(hash(_normalize(query))) % (2**32))
        rng.shuffle(pool)
        top = pool[:4]
        duplicated = top + [top[0], top[1]]

        metadatas = []
        distances = []
        for idx, _doc in enumerate(duplicated):
            source = (
                "star_stories_english.txt" if idx % 2 == 0 else "profile_english.txt"
            )
            metadatas.append({"source": source, "category": question_type})
            distances.append(0.10 + (idx * 0.01))

        return KnowledgeRetriever._postprocess_documents(
            documents=duplicated,
            metadatas=metadatas,
            distances=distances,
            max_results=top_k or 4,
            max_per_source=2,
        )


class SyntheticResponseAgent:
    """
    Offline response generator that preserves the anti-repetition behavior
    expected from OpenAIAgent without calling external APIs.
    """

    def __init__(self):
        self._opener_agent = OpenAIAgent(api_key="synthetic")
        self.pricing_model = "synthetic_openai_gpt_4o_mini"
        self.supports_prompt_cache = False
        self.system_prompt_token_estimate = 1024
        self._recent_templates: list[str] = []

        self._templates = {
            "personal": [
                "I've worked in remote BPO operations for over three years, mainly at **Webhelp**. [PAUSE] I focus on prioritizing urgent queues, documenting clearly, and keeping quality stable around **92% QA**.",
                "My background is in high-volume customer operations where consistency matters every day. [PAUSE] At **Webhelp**, I built routines that protected quality and speed, which helped me sustain **92% QA**.",
                "I bring structured execution from my time in BPO support and remote collaboration. [PAUSE] I usually organize by urgency, verify each closure, and keep teams aligned through clear notes.",
            ],
            "situational": [
                "In one high-pressure case, priorities changed fast and several stakeholders needed updates. [PAUSE] I clarified the goal, split tasks by urgency, and verified each closure, which kept service quality at **92% QA**.",
                "There was a moment when escalations increased and timelines got tighter than expected. [PAUSE] I mapped risks first, communicated status early, and used a strict routine that protected quality and response times.",
                "I handled a similar scenario by defining the immediate objective and assigning clear action blocks. [PAUSE] That helped the team stay coordinated, reduce confusion, and keep consistent customer outcomes.",
            ],
            "company": [
                "What attracts me is the focus on measurable customer outcomes and operational discipline. [PAUSE] That matches how I worked at **Webhelp**, where clear process ownership supported quality and speed.",
                "I'm interested in this team because the role blends customer impact with process improvement. [PAUSE] My experience in remote support and QA-focused execution aligns well with that environment.",
                "I value cultures that combine accountability, learning, and collaboration across teams. [PAUSE] That's where my background in high-volume support and structured communication adds value quickly.",
            ],
            "hybrid": [
                "I'd connect my operations background with your team goals by ramping through SOPs and key metrics first. [PAUSE] In similar settings, that approach helped me deliver reliable quality while adapting to shifting priorities.",
                "My experience gives me a practical base for this role because I combine execution speed with process discipline. [PAUSE] I focus on stakeholder alignment, clear updates, and measurable outcomes from day one.",
                "I usually start by understanding expectations, risk points, and success metrics with the team. [PAUSE] That framework helped me keep **92% QA** while managing volume and cross-functional dependencies.",
            ],
            "simple": [
                "I can start quickly and align the exact date with a professional handover plan. [PAUSE] I'm also flexible with schedule expectations when the team needs coverage.",
                "I'm comfortable discussing compensation based on responsibilities, impact, and market range. [PAUSE] I can share a clear range once we align on scope.",
                "Yes, I'm open to hybrid routines and occasional weekend support when there's a clear plan. [PAUSE] I usually coordinate early so delivery stays predictable.",
            ],
        }

    @staticmethod
    def _normalize_for_memory(text: str) -> list[str]:
        cleaned = (text or "").lower()
        cleaned = cleaned.replace("[pause]", " ")
        cleaned = cleaned.replace("**", "")
        cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.split()

    @staticmethod
    def _ngrams(tokens: list[str], n: int = 4) -> set[str]:
        if len(tokens) < n:
            return {" ".join(tokens)} if tokens else set()
        return {
            " ".join(tokens[idx:idx + n])
            for idx in range(len(tokens) - n + 1)
        }

    def _forbidden_ngrams(
        self,
        recent_responses: list[str],
        recent_question_types: list[str],
        current_question_type: str,
    ) -> set[str]:
        if current_question_type not in {"simple", "situational"}:
            return set()

        if (
            recent_question_types
            and len(recent_question_types) == len(recent_responses)
        ):
            filtered = [
                response
                for response, q_type in zip(recent_responses, recent_question_types)
                if q_type in {"simple", "situational"}
            ]
        else:
            filtered = list(recent_responses)

        memory = filtered[-6:]
        if not memory:
            return set()

        counts: dict[str, int] = {}
        for response in memory:
            grams = self._ngrams(self._normalize_for_memory(response), n=4)
            for gram in grams:
                if len(gram) < 18:
                    continue
                counts[gram] = counts.get(gram, 0) + 1

        recurring = {gram for gram, freq in counts.items() if freq >= 2}
        if recurring:
            return recurring

        # If no recurring 4-grams yet, still discourage the top recent phrases.
        top = sorted(
            counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:4]
        return {gram for gram, _ in top}

    def _pick_template(
        self,
        question_type: str,
        recent_responses: list[str],
        recent_question_types: list[str],
    ) -> str:
        candidates = list(self._templates.get(question_type, self._templates["personal"]))
        if not recent_responses:
            chosen = candidates[0]
            self._recent_templates.append(chosen)
            return chosen

        recent_tail = recent_responses[-2:]
        forbidden = self._forbidden_ngrams(
            recent_responses=recent_responses,
            recent_question_types=recent_question_types,
            current_question_type=question_type,
        )

        scored = []
        for tpl in candidates:
            sim = max(_jaccard(tpl, old) for old in recent_tail)
            tpl_grams = self._ngrams(self._normalize_for_memory(tpl), n=4)
            overlap = len(tpl_grams & forbidden)
            score = sim + (overlap * 0.06)
            scored.append((score, tpl))
        scored.sort(key=lambda row: row[0])
        chosen = scored[0][1]

        if self._recent_templates and chosen == self._recent_templates[-1]:
            for _, alternative in scored[1:]:
                if alternative != self._recent_templates[-1]:
                    chosen = alternative
                    break

        self._recent_templates.append(chosen)
        self._recent_templates = self._recent_templates[-8:]
        return chosen

    async def generate_full(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
        recent_questions: Optional[list[str]] = None,
        recent_responses: Optional[list[str]] = None,
        recent_question_types: Optional[list[str]] = None,
    ) -> str:
        opener = self._opener_agent.get_instant_opener(question_type).strip()
        recent_responses = recent_responses or []
        recent_question_types = recent_question_types or []
        template = self._pick_template(
            question_type,
            recent_responses,
            recent_question_types,
        )

        kb_facts = []
        for chunk in kb_chunks[:2]:
            fact = chunk.strip()
            if fact:
                kb_facts.append(fact)
        fact_tail = ""
        if kb_facts:
            fact_tail = f" [PAUSE] {kb_facts[0]}"
            if len(kb_facts) > 1:
                fact_tail += f" Also, {kb_facts[1]}"

        response = f"{opener} {template}{fact_tail}"
        response = re.sub(r"\s+", " ", response).strip()
        return response


@dataclass
class SimulationConfig:
    mode: str
    interviews: int
    minutes_per_interview: float
    seed: int
    output_json: Path
    output_md: Path
    redteam_level: str = "none"


class StrictInterviewSimulator:
    def __init__(self, config: SimulationConfig):
        self.config = config
        self.question_filter = QuestionFilter()
        self.classifier = QuestionClassifier()
        default_embedding_api_name = (
            "synthetic_openai_embedding"
            if config.mode == "synthetic"
            else "openai_embedding"
        )
        self.cost_tracker = CostTracker(
            session_id=f"stress_{config.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            default_embedding_api_name=default_embedding_api_name,
        )

        if config.mode == "api":
            self.retriever = KnowledgeRetriever()
            self.response_agent = OpenAIAgent()
        else:
            self.retriever = SyntheticKnowledgeRetriever()
            self.response_agent = SyntheticResponseAgent()

        self.qa_history: list[dict] = []
        self.responses: list[str] = []
        self.openers: list[str] = []
        self.interview_memory = InterviewMemory()

        self.tp = 0
        self.fp = 0
        self.tn = 0
        self.fn = 0
        self.transition_fp = 0
        self.transition_total_non_question = 0
        self.classification_total = 0
        self.classification_correct = 0
        self.question_count = 0
        self.candidate_question_count = 0
        self.micro_question_count = 0
        self.per_event: list[dict] = []
        self.response_similarities: list[float] = []
        self.immediate_opener_repeats = 0
        self.redteam_questions_total = 0
        self.redteam_questions_passed = 0
        self.redteam_robustness_failures = 0

    @staticmethod
    def _is_redteam_response_robust(response: str) -> bool:
        text = _normalize(response)
        if not text:
            return False
        forbidden_markers = [
            "as an ai",
            "language model",
            "i cannot",
            "i can't provide",
            "teleprompter",
            "i'm unable",
        ]
        if any(marker in text for marker in forbidden_markers):
            return False
        return len(text.split()) >= 6

    async def _generate_response(
        self,
        question: str,
        question_type: str,
        kb_chunks: list[str],
    ) -> str:
        recent_questions = [row["question"] for row in self.qa_history[-3:]]
        recent_responses = [row["response"] for row in self.qa_history[-3:]]
        recent_question_types = [row["type"] for row in self.qa_history[-3:]]
        memory_context = self.interview_memory.build_prompt_context(
            question=question,
            question_type=question_type,
        )

        if self.config.mode == "api":
            chunks = []
            async for token in self.response_agent.generate(
                question=question,
                kb_chunks=kb_chunks,
                question_type=question_type,
                recent_questions=recent_questions,
                recent_responses=recent_responses,
                recent_question_types=recent_question_types,
                memory_context=memory_context,
            ):
                chunks.append(token)
            return "".join(chunks).strip()

        return await self.response_agent.generate_full(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
            recent_questions=recent_questions,
            recent_responses=recent_responses,
            recent_question_types=recent_question_types,
        )

    async def run(self, events: list[SimEvent]) -> dict:
        if self.config.mode == "api":
            await self.response_agent.warmup()

        for event in events:
            if event.speaker == "candidate":
                self.cost_tracker.track_transcription(
                    speaker="user",
                    duration_seconds=event.duration_seconds,
                    api_name="openai_realtime_user",
                )
                if event.event_kind == "candidate_question":
                    self.candidate_question_count += 1
                self.per_event.append({
                    "minute": event.minute,
                    "speaker": event.speaker,
                    "event_kind": event.event_kind,
                    "text": event.text,
                    "processed": False,
                })
                continue

            # Interviewer turn.
            self.cost_tracker.track_transcription(
                speaker="interviewer",
                duration_seconds=event.duration_seconds,
                api_name="deepgram_interviewer",
            )

            predicted = self.question_filter.is_interview_question(event.text)
            if event.event_kind == "transition" and not event.expected_is_question:
                self.transition_total_non_question += 1
                if predicted:
                    self.transition_fp += 1

            if event.expected_is_question and predicted:
                self.tp += 1
            elif event.expected_is_question and not predicted:
                self.fn += 1
            elif (not event.expected_is_question) and predicted:
                self.fp += 1
            else:
                self.tn += 1

            row = {
                "minute": event.minute,
                "speaker": event.speaker,
                "event_kind": event.event_kind,
                "text": event.text,
                "expected_is_question": event.expected_is_question,
                "predicted_is_question": predicted,
            }
            is_redteam_question = event.event_kind == "redteam_question"
            if is_redteam_question:
                self.redteam_questions_total += 1

            if not predicted:
                if is_redteam_question:
                    self.redteam_robustness_failures += 1
                self.per_event.append(row)
                continue

            if event.event_kind == "micro_question":
                self.micro_question_count += 1
            self.question_count += 1

            classification = self.classifier._fallback_classify(event.text)
            q_type = classification["type"]
            row["classification"] = classification

            if event.expected_type:
                self.classification_total += 1
                if q_type == event.expected_type:
                    self.classification_correct += 1

            kb_chunks = await self.retriever.retrieve(
                query=event.text,
                question_type=q_type,
            )

            # Embedding cost estimate.
            emb_tokens = estimate_tokens(event.text)
            embedding_api_name = (
                "synthetic_openai_embedding"
                if self.config.mode == "synthetic"
                else "openai_embedding"
            )
            self.cost_tracker.track_embedding(
                tokens=emb_tokens,
                question=event.text,
                api_name=embedding_api_name,
            )

            response = await self._generate_response(
                question=event.text,
                question_type=q_type,
                kb_chunks=kb_chunks,
            )
            row["response"] = response
            row["response_chars"] = len(response)
            if is_redteam_question:
                robust = self._is_redteam_response_robust(response)
                row["redteam_robust"] = robust
                if robust:
                    self.redteam_questions_passed += 1
                else:
                    self.redteam_robustness_failures += 1

            # Generation cost estimate.
            kb_tokens = sum(estimate_tokens(chunk) for chunk in kb_chunks)
            in_tokens = (
                getattr(self.response_agent, "system_prompt_token_estimate", 1024)
                + estimate_tokens(event.text)
                + kb_tokens
            )
            out_tokens = estimate_tokens(response)
            self.cost_tracker.track_generation(
                input_tokens=in_tokens,
                output_tokens=out_tokens,
                question=event.text,
                api_name=getattr(self.response_agent, "pricing_model", "openai_gpt_4o_mini"),
            )

            opener = _opener_signature(response)
            if self.openers and opener == self.openers[-1]:
                self.immediate_opener_repeats += 1
            self.openers.append(opener)
            self.responses.append(response)

            if len(self.responses) >= 2:
                sim = _jaccard(self.responses[-1], self.responses[-2])
                self.response_similarities.append(sim)

            self.qa_history.append({
                "question": event.text,
                "type": q_type,
                "response": response,
            })
            self.interview_memory.ingest_generated_response(
                question=event.text,
                question_type=q_type,
                response=response,
                kb_chunks=kb_chunks,
            )
            self.qa_history = self.qa_history[-12:]
            self.per_event.append(row)

        precision = self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0
        recall = self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) else 0.0
        )
        transition_fp_rate = (
            self.transition_fp / self.transition_total_non_question
            if self.transition_total_non_question else 0.0
        )
        cls_acc = (
            self.classification_correct / self.classification_total
            if self.classification_total else 0.0
        )
        avg_similarity = (
            statistics.mean(self.response_similarities)
            if self.response_similarities else 0.0
        )
        p95_similarity = (
            float(sorted(self.response_similarities)[math.ceil(0.95 * len(self.response_similarities)) - 1])
            if self.response_similarities else 0.0
        )
        opener_repeat_rate = (
            self.immediate_opener_repeats / len(self.openers)
            if self.openers else 0.0
        )
        redteam_score = (
            self.redteam_questions_passed / self.redteam_questions_total
            if self.redteam_questions_total else 1.0
        )

        report = self.cost_tracker.get_session_report()
        report.questions_processed = self.question_count
        report.responses_generated = len(self.responses)

        virtual_elapsed_minutes = self.config.interviews * self.config.minutes_per_interview
        saldo = self.cost_tracker.saldo_manager.build_snapshot(
            elapsed_minutes=virtual_elapsed_minutes
        )

        summary = {
            "mode": self.config.mode,
            "seed": self.config.seed,
            "interviews": self.config.interviews,
            "minutes_per_interview": self.config.minutes_per_interview,
            "total_virtual_minutes": virtual_elapsed_minutes,
            "total_events": len(events),
            "question_filter": {
                "tp": self.tp,
                "fp": self.fp,
                "tn": self.tn,
                "fn": self.fn,
                "precision": round(precision, 6),
                "recall": round(recall, 6),
                "f1": round(f1, 6),
                "transition_non_question_total": self.transition_total_non_question,
                "transition_false_positives": self.transition_fp,
                "transition_false_positive_rate": round(transition_fp_rate, 6),
            },
            "classification": {
                "total_labeled": self.classification_total,
                "correct": self.classification_correct,
                "accuracy": round(cls_acc, 6),
            },
            "responses": {
                "generated": len(self.responses),
                "immediate_opener_repeats": self.immediate_opener_repeats,
                "immediate_opener_repeat_rate": round(opener_repeat_rate, 6),
                "avg_consecutive_jaccard_3gram": round(avg_similarity, 6),
                "p95_consecutive_jaccard_3gram": round(p95_similarity, 6),
            },
            "coverage": {
                "candidate_questions": self.candidate_question_count,
                "micro_questions": self.micro_question_count,
            },
            "redteam": {
                "level": self.config.redteam_level,
                "questions_total": self.redteam_questions_total,
                "questions_passed": self.redteam_questions_passed,
                "robustness_failures": self.redteam_robustness_failures,
                "robustness_score": round(redteam_score, 6),
            },
            "costs": {
                "total_cost_usd": round(report.total_cost_usd, 6),
                "costs_by_category": {
                    key: round(value, 6)
                    for key, value in report.costs_by_category.items()
                },
                "api_calls_count": report.api_calls_count,
            },
            "saldo": saldo,
        }

        return {
            "summary": summary,
            "events": [asdict(event) for event in events],
            "event_results": self.per_event,
        }

def _build_markdown(report: dict) -> str:
    s = report["summary"]
    qf = s["question_filter"]
    cls = s["classification"]
    rsp = s["responses"]
    cov = s["coverage"]
    red = s.get("redteam", {})
    fuel = s["saldo"]["fuel_gauge"]
    providers = s["saldo"]["providers"]

    lines = [
        "# Strict Stress Simulation Report",
        "",
        f"- Mode: `{s['mode']}`",
        f"- Seed: `{s['seed']}`",
        f"- Interviews: `{s['interviews']}`",
        f"- Minutes/Interview: `{s['minutes_per_interview']}`",
        f"- Total Virtual Minutes: `{s['total_virtual_minutes']}`",
        f"- Total Events: `{s['total_events']}`",
        "",
        "## Question Filter",
        f"- TP={qf['tp']} FP={qf['fp']} TN={qf['tn']} FN={qf['fn']}",
        f"- Precision: `{qf['precision']}`",
        f"- Recall: `{qf['recall']}`",
        f"- F1: `{qf['f1']}`",
        f"- Transition FP Rate: `{qf['transition_false_positive_rate']}`",
        "",
        "## Classification",
        f"- Labeled: `{cls['total_labeled']}`",
        f"- Correct: `{cls['correct']}`",
        f"- Accuracy: `{cls['accuracy']}`",
        "",
        "## Response Repetition",
        f"- Responses: `{rsp['generated']}`",
        f"- Immediate opener repeats: `{rsp['immediate_opener_repeats']}`",
        f"- Immediate opener repeat rate: `{rsp['immediate_opener_repeat_rate']}`",
        f"- Avg consecutive 3-gram Jaccard: `{rsp['avg_consecutive_jaccard_3gram']}`",
        f"- P95 consecutive 3-gram Jaccard: `{rsp['p95_consecutive_jaccard_3gram']}`",
        "",
        "## Coverage",
        f"- Candidate questions: `{cov['candidate_questions']}`",
        f"- Micro follow-up questions: `{cov['micro_questions']}`",
        "",
        "## Cost & Fuel",
        f"- Total estimated cost: `${s['costs']['total_cost_usd']}`",
        f"- Bottleneck provider: `{fuel['bottleneck_provider']}`",
        f"- Minutes until any depletion: `{fuel['minutes_until_any_depletion']}` (`{fuel['human_readable_until_any_depletion']}`)",
        "",
    ]

    if red.get("questions_total", 0) > 0:
        lines.extend(
            [
                "## Red-Team Robustness",
                f"- Level: `{red.get('level')}`",
                f"- Questions total: `{red.get('questions_total')}`",
                f"- Questions passed: `{red.get('questions_passed')}`",
                f"- Robustness failures: `{red.get('robustness_failures')}`",
                f"- Robustness score: `{red.get('robustness_score')}`",
                "",
            ]
        )

    for provider in ("openai", "deepgram", "anthropic"):
        p = providers.get(provider, {})
        lines.append(
            f"- {provider}: remaining `${p.get('remaining_usd')}` | "
            f"minutes `{p.get('minutes_remaining')}` | "
            f"display `{p.get('human_readable_remaining')}`"
        )

    lines.append("")
    return "\n".join(lines)


def _default_output_paths(mode: str) -> tuple[Path, Path]:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / "tests" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    return (
        out_dir / f"strict_stress_{mode}_{ts}.json",
        out_dir / f"strict_stress_{mode}_{ts}.md",
    )


async def _run(config: SimulationConfig) -> dict:
    generator = InterviewScenarioGenerator(seed=config.seed)
    events = generator.generate_batch(
        interviews=config.interviews,
        minutes_per_interview=config.minutes_per_interview,
        redteam_level=config.redteam_level,
    )
    simulator = StrictInterviewSimulator(config=config)
    report = await simulator.run(events)

    config.output_json.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    config.output_md.write_text(_build_markdown(report), encoding="utf-8")
    return report


def _print_console_summary(report: dict) -> None:
    s = report["summary"]
    qf = s["question_filter"]
    cls = s["classification"]
    rsp = s["responses"]
    red = s.get("redteam", {})
    fuel = s["saldo"]["fuel_gauge"]
    print("=" * 72)
    print("STRICT STRESS SIMULATION SUMMARY")
    print("=" * 72)
    print(
        f"Mode={s['mode']} interviews={s['interviews']} "
        f"minutes/interview={s['minutes_per_interview']} "
        f"virtual_total={s['total_virtual_minutes']}"
    )
    print(
        f"QFilter precision={qf['precision']:.4f} recall={qf['recall']:.4f} "
        f"f1={qf['f1']:.4f} transition_fp_rate={qf['transition_false_positive_rate']:.4f}"
    )
    print(
        f"Classifier accuracy={cls['accuracy']:.4f} "
        f"(correct={cls['correct']}/{cls['total_labeled']})"
    )
    print(
        f"Responses={rsp['generated']} opener_repeat_rate={rsp['immediate_opener_repeat_rate']:.4f} "
        f"avg_jaccard3={rsp['avg_consecutive_jaccard_3gram']:.4f} "
        f"p95_jaccard3={rsp['p95_consecutive_jaccard_3gram']:.4f}"
    )
    if red.get("questions_total", 0) > 0:
        print(
            f"RedTeam level={red.get('level')} score={red.get('robustness_score'):.4f} "
            f"passed={red.get('questions_passed')}/{red.get('questions_total')}"
        )
    print(
        f"Estimated cost=${s['costs']['total_cost_usd']:.6f} | "
        f"fuel bottleneck={fuel['bottleneck_provider']} "
        f"({fuel['human_readable_until_any_depletion']})"
    )
    print("=" * 72)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Strict interview stress simulation (synthetic or API mode)."
    )
    parser.add_argument(
        "--mode",
        choices=["synthetic", "api"],
        default="synthetic",
        help="Simulation mode.",
    )
    parser.add_argument(
        "--interviews",
        type=int,
        default=4,
        help="Number of interviews to simulate.",
    )
    parser.add_argument(
        "--minutes-per-interview",
        type=float,
        default=70.0,
        help="Virtual minutes per interview.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Random seed for deterministic generation.",
    )
    parser.add_argument(
        "--redteam-level",
        choices=["none", "standard", "extreme"],
        default="none",
        help="Inject conversational adversarial attacks.",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default="",
        help="Optional JSON output path.",
    )
    parser.add_argument(
        "--output-md",
        type=str,
        default="",
        help="Optional Markdown output path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    default_json, default_md = _default_output_paths(args.mode)
    output_json = Path(args.output_json) if args.output_json else default_json
    output_md = Path(args.output_md) if args.output_md else default_md

    config = SimulationConfig(
        mode=args.mode,
        interviews=max(1, int(args.interviews)),
        minutes_per_interview=max(8.0, float(args.minutes_per_interview)),
        seed=int(args.seed),
        output_json=output_json,
        output_md=output_md,
        redteam_level=args.redteam_level,
    )

    if config.mode == "api":
        missing = [
            key for key in ("OPENAI_API_KEY",)
            if not os.getenv(key)
        ]
        if missing:
            print(
                "Missing required env vars for API mode: "
                + ", ".join(missing)
            )
            return 2

    report = asyncio.run(_run(config))
    _print_console_summary(report)
    print(f"JSON report: {config.output_json}")
    print(f"Markdown report: {config.output_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
