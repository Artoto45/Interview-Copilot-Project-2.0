"""
Response Agent - OpenAI GPT-4o-mini (Streaming)
===============================================
High quality + low latency interview copilot responses using native OpenAI.
"""

import logging
import os
import re
from collections import Counter
from typing import AsyncGenerator, Optional

import openai
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("response.openai")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """\
You are an English interview copilot. Your user is a non-native English \
speaker in a live job interview. You generate the EXACT words the candidate \
should say aloud.

CRITICAL RULES - follow ALL of these strictly:
1. Use contractions ALWAYS: I'm, we've, they're, I'd, it's, don't, wasn't
2. Short sentences: 12-18 words max per sentence for easy reading aloud
3. Use conversational connectors naturally, but rotate them.
   Never start every answer with the same opener.
4. STAR method for behavioral/situational questions:
   Situation -> Task -> Action -> Result (clear structure)
5. Match response length to the [LENGTH] tag below
6. Use ONLY facts from the [KNOWLEDGE BASE] - NEVER invent experiences,
   companies, job titles, or metrics that aren't in the KB
7. Never reveal you are an AI, a script, or a teleprompter
8. Write in first person as the candidate
9. Add [PAUSE] where the speaker should breathe (every 2-3 sentences)
10. Add **bold** on key words the speaker should emphasize
11. Replace formal vocabulary: "utilize"->"use", "regarding"->"about",
    "demonstrate"->"show", "facilitate"->"help"
12. Output ONLY the speakable words. NEVER include headers (#), titles,
    markdown sections, horizontal rules (---), bullet lists, delivery notes,
    tips, or meta-commentary. No preambles.
13. Reference specific facts from [KNOWLEDGE BASE] in every response:
    company names (Webhelp), metrics (92% QA), years (3+ years), specifics
    (remote, BPO, Python). The response MUST contain at least 2 KB facts.
14. Do NOT repeat the same sentence structure, opener, or wording from
    recent answers unless explicitly asked to repeat.
15. If [RECENT OPENERS TO AVOID] is provided, do not reuse those exact openings.
16. If [FORBIDDEN NGRAMS] is provided, avoid those exact phrases.
"""

LENGTH_GUIDE = {
    "simple": "1-2 sentences",
    "personal": "3-4 sentences",
    "company": "4-5 sentences",
    "hybrid": "5-6 sentences",
    "situational": "5-6 sentences (STAR format)",
}

TEMPERATURE_MAP = {
    "simple": 0.3,
    "personal": 0.3,
    "company": 0.3,
    "hybrid": 0.4,
    "situational": 0.5,
}

MAX_OUTPUT_TOKENS = {
    "simple": 180,
    "personal": 280,
    "company": 320,
    "hybrid": 380,
    "situational": 420,
}

TARGET_SENTENCES = {
    "simple": 2,
    "personal": 4,
    "company": 5,
    "hybrid": 6,
    "situational": 6,
}

STREAM_PREFIX_HOLD_WORDS = max(
    6,
    int(os.getenv("OPENAI_STREAM_PREFIX_HOLD_WORDS", "10")),
)
OPENING_SIMILARITY_THRESHOLD = 0.62
CONTRACTION_RE = re.compile(r"\b[A-Za-z]+['’][A-Za-z]+\b")
NUMERIC_FACT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*%\b|\b\d+(?:\.\d+)?\+?\s*"
    r"(?:years?|months?|weeks?|days?|tickets?|cases?|qa)\b",
    flags=re.IGNORECASE,
)
PROPER_NOUN_RE = re.compile(r"\b[A-Z][A-Za-z0-9&+\-]{2,}\b")
KB_ANCHOR_TERMS = (
    "webhelp",
    "qa",
    "remote",
    "bpo",
    "python",
    "automation",
    "process optimization",
    "3+ years",
    "92%",
    "90%",
)
STAR_SIGNAL_MAP = {
    "situation": ("situation", "there was a moment", "at webhelp", "in my role"),
    "task": ("task", "my responsibility", "i had to", "my goal was"),
    "action": ("action", "i developed", "i decided", "i took", "i made sure"),
    "result": ("result", "as a result", "this helped", "this allowed", "outcome"),
}
KB_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "were",
    "have",
    "been",
    "because",
    "where",
    "while",
    "when",
    "your",
    "their",
    "team",
    "work",
    "role",
    "used",
    "using",
    "about",
}

INSTANT_OPENERS = {
    "personal": [
        "Honestly, from my experience at Webhelp... ",
        "What I found in my last role is... ",
        "I'd say a key point from my background is... ",
    ],
    "company": [
        "What attracts me to your company is... ",
        "Honestly, what stands out about this role is... ",
        "I'd say your mission aligns with how I work because... ",
    ],
    "situational": [
        "There was a moment at Webhelp where... ",
        "One clear example from my experience is... ",
        "What happened in that situation was... ",
    ],
    "hybrid": [
        "I'd approach that by combining experience and fit... ",
        "From what I've done before, I'd handle it like this... ",
        "What I learned in similar scenarios is... ",
    ],
    "simple": [
        "Honestly, I'd say... ",
        "I'd put it this way... ",
        "The short answer is... ",
    ],
}


class OpenAIAgent:
    """
    Generates interview responses via OpenAI Async client.
    """

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            logger.warning("OPENAI_API_KEY is not set. Response API will fail.")

        self.pricing_model = "openai_gpt_4o_mini"
        self.supports_prompt_cache = False
        self.system_prompt_token_estimate = 1024

        self.client = openai.AsyncOpenAI(api_key=key)
        self._warmed_up = False
        self._cache_stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "by_type": {},
        }
        self._opener_state = {
            "cursor_by_type": {},
            "last_global": "",
        }

    async def warmup(self):
        """Warm up the Async OpenAI client with a tiny initial API call."""
        if self._warmed_up:
            return

        logger.info("Warming up OpenAI ResponseAgent...")
        try:
            await self.client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "Hi"},
                ],
                max_tokens=5,
                temperature=0.0,
            )
            self._warmed_up = True
            logger.info("OpenAIAgent initialized successfully")
        except Exception as e:
            logger.warning(f"Model warmup failed: {e}")

    def get_instant_opener(self, question_type: str) -> str:
        """Return rotating opener to avoid repetitive starts."""
        options = INSTANT_OPENERS.get(question_type) or INSTANT_OPENERS["simple"]
        cursor = self._opener_state["cursor_by_type"].get(question_type, 0)
        opener = options[cursor % len(options)]

        if opener == self._opener_state["last_global"] and len(options) > 1:
            cursor += 1
            opener = options[cursor % len(options)]

        self._opener_state["cursor_by_type"][question_type] = cursor + 1
        self._opener_state["last_global"] = opener
        return opener

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
        """
        Generate a streaming response with the OpenAI Async API.
        """
        recent_questions = recent_questions or []
        recent_responses = recent_responses or []
        recent_question_types = recent_question_types or []
        temperature = TEMPERATURE_MAP.get(question_type, 0.3)
        max_tokens = MAX_OUTPUT_TOKENS.get(question_type, 320)

        if question_type not in self._cache_stats["by_type"]:
            self._cache_stats["by_type"][question_type] = {
                "calls": 0,
                "hits": 0,
            }
        self._cache_stats["total_calls"] += 1
        self._cache_stats["by_type"][question_type]["calls"] += 1

        logger.info(
            f"Generating response: type={question_type}, "
            f"model={MODEL}, temp={temperature}, max_tokens={max_tokens}"
        )

        attempts = [1] if force_hard_mode else [0, 1]
        for attempt in attempts:
            hard_mode = attempt == 1
            user_message = self._build_user_message(
                question=question,
                kb_chunks=kb_chunks,
                question_type=question_type,
                recent_questions=recent_questions,
                recent_responses=recent_responses,
                recent_question_types=recent_question_types,
                hard_anti_repetition=hard_mode,
                memory_context=memory_context,
            )
            held_tokens: list[str] = []
            full_text = ""
            yielded_live = False
            retry_with_hard_mode = False

            try:
                response_stream = await self.client.chat.completions.create(
                    model=MODEL,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )

                async for chunk in response_stream:
                    if not (chunk.choices and len(chunk.choices) > 0):
                        continue
                    delta = chunk.choices[0].delta
                    if not (delta and delta.content):
                        continue
                    token = delta.content
                    full_text += token

                    if not yielded_live:
                        held_tokens.append(token)
                        if self._should_evaluate_held_prefix(held_tokens):
                            held_text = "".join(held_tokens)
                            if (
                                not hard_mode
                                and self._opening_too_similar(
                                    held_text,
                                    recent_responses=recent_responses,
                                )
                            ):
                                retry_with_hard_mode = True
                                logger.info(
                                    "Anti-repetition guard triggered; "
                                    "retrying in hard mode."
                                )
                                break

                            for held in held_tokens:
                                yield held
                            held_tokens.clear()
                            yielded_live = True
                        continue

                    yield token
                    if self._should_stop_early(
                        text=full_text,
                        question_type=question_type,
                    ):
                        break

                if retry_with_hard_mode:
                    continue

                if held_tokens:
                    for held in held_tokens:
                        yield held
                break

            except Exception as e:
                logger.error(f"OpenAI response generation error: {e}", exc_info=True)
                yield f"[Error generating response: {e}]"
                break

    def _build_user_message(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str,
        recent_questions: list[str],
        recent_responses: list[str],
        recent_question_types: Optional[list[str]] = None,
        hard_anti_repetition: bool = False,
        memory_context: Optional[str] = None,
    ) -> str:
        """Build user message with KB context and anti-repetition context."""
        length = LENGTH_GUIDE.get(question_type, "3-4 sentences")

        kb_section = "\n\n".join(kb_chunks) if kb_chunks else (
            "[No knowledge base context available - answer with general "
            "best practices for this type of question]"
        )

        recent_q_section = (
            "\n".join(f"- {q}" for q in recent_questions[-3:])
            if recent_questions else "[none]"
        )
        recent_r_section = (
            "\n".join(f"- {r[:220]}" for r in recent_responses[-2:])
            if recent_responses else "[none]"
        )
        recent_openers = []
        for resp in recent_responses[-3:]:
            first_clause = re.split(r"[.!?]", (resp or "").strip(), maxsplit=1)[0]
            opener = " ".join(first_clause.split()[:8]).strip()
            if opener:
                recent_openers.append(opener)
        deduped_openers = []
        for opener in recent_openers:
            if opener not in deduped_openers:
                deduped_openers.append(opener)
        opener_section = (
            "\n".join(f"- {op}" for op in deduped_openers)
            if deduped_openers else "[none]"
        )
        forbidden_ngrams = self._extract_forbidden_ngrams(
            recent_responses=recent_responses,
            recent_question_types=recent_question_types or [],
            current_question_type=question_type,
        )
        forbidden_section = (
            "\n".join(f"- {gram}" for gram in forbidden_ngrams)
            if forbidden_ngrams else "[none]"
        )
        hard_mode_section = ""
        if hard_anti_repetition:
            hard_mode_section = (
                "[ANTI-REPETITION HARD MODE]:\n"
                "Use a different first verb and sentence structure than prior answers.\n"
                "Avoid timeline anchors already used in recent answers.\n"
                "Keep facts consistent, but take a new narrative path.\n\n"
            )

        return (
            f"[QUESTION TYPE]: {question_type}\n"
            f"[LENGTH]: {length}\n\n"
            "[ANTI-REPETITION]:\n"
            "Use a different opener and wording than the recent answers.\n"
            "Keep core facts consistent, but vary phrasing and sentence flow.\n\n"
            f"{hard_mode_section}"
            f"[RECENT OPENERS TO AVOID]:\n{opener_section}\n\n"
            f"[FORBIDDEN NGRAMS]:\n{forbidden_section}\n\n"
            f"[RECENT QUESTIONS]:\n{recent_q_section}\n\n"
            f"[RECENT ANSWERS]:\n{recent_r_section}\n\n"
            f"{memory_context or '[INTERVIEW MEMORY]\\n[none]'}\n\n"
            f"[KNOWLEDGE BASE]:\n{kb_section}\n\n"
            f"[INTERVIEWER QUESTION]:\n{question}"
        )

    @staticmethod
    def _normalize_for_ngram_memory(text: str) -> list[str]:
        cleaned = (text or "").lower()
        cleaned = cleaned.replace("[pause]", " ")
        cleaned = cleaned.replace("**", "")
        cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.split()

    @staticmethod
    def _should_evaluate_held_prefix(tokens: list[str]) -> bool:
        text = "".join(tokens).strip()
        if not text:
            return False
        words = OpenAIAgent._normalize_for_ngram_memory(text)
        if len(words) >= STREAM_PREFIX_HOLD_WORDS:
            return True
        return bool(re.search(r"[.!?]\s*$", text))

    @staticmethod
    def _trigram_jaccard(a_tokens: list[str], b_tokens: list[str]) -> float:
        if not a_tokens or not b_tokens:
            return 0.0

        def grams(tokens: list[str], n: int = 3) -> set[str]:
            if len(tokens) < n:
                return {" ".join(tokens)} if tokens else set()
            return {
                " ".join(tokens[idx:idx + n])
                for idx in range(len(tokens) - n + 1)
            }

        ga = grams(a_tokens, 3)
        gb = grams(b_tokens, 3)
        if not ga or not gb:
            return 0.0
        return len(ga & gb) / len(ga | gb)

    def _opening_too_similar(
        self,
        candidate_prefix: str,
        recent_responses: list[str],
    ) -> bool:
        cand_tokens = self._normalize_for_ngram_memory(candidate_prefix)[:26]
        if len(cand_tokens) < 6:
            return False

        cand_head4 = " ".join(cand_tokens[:4])
        for response in recent_responses[-5:]:
            recent_tokens = self._normalize_for_ngram_memory(response)[:28]
            if len(recent_tokens) < 6:
                continue
            if " ".join(recent_tokens[:4]) == cand_head4:
                return True
            score = self._trigram_jaccard(cand_tokens, recent_tokens)
            if score >= OPENING_SIMILARITY_THRESHOLD:
                return True
        return False

    def _should_stop_early(self, text: str, question_type: str) -> bool:
        tokens = self._normalize_for_ngram_memory(text)
        if not tokens:
            return False

        target_sentences = TARGET_SENTENCES.get(question_type, 4)
        sentence_count = len(re.findall(r"[.!?]+", text))
        if sentence_count < target_sentences:
            return False
        if not re.search(r"[.!?]\s*$", text.strip()):
            return False

        # Keep outputs concise and predictable for live reading.
        max_words = max(45, MAX_OUTPUT_TOKENS.get(question_type, 320) // 2)
        return len(tokens) >= max_words

    def _extract_forbidden_ngrams(
        self,
        recent_responses: list[str],
        recent_question_types: list[str],
        current_question_type: str,
        n: int = 4,
        max_items: int = 8,
    ) -> list[str]:
        """
        Build a short blacklist of overused 4-grams for repetitive domains.
        """
        if current_question_type not in {"simple", "situational", "hybrid", "personal"}:
            return []

        if not recent_responses:
            return []

        if recent_question_types and len(recent_question_types) == len(recent_responses):
            paired = zip(recent_responses, recent_question_types)
            filtered = [
                response
                for response, q_type in paired
                if q_type in {"simple", "situational"}
            ]
        else:
            filtered = list(recent_responses[-4:])

        if not filtered:
            return []

        grams = Counter()
        for response in filtered[-6:]:
            tokens = self._normalize_for_ngram_memory(response)
            if len(tokens) < n:
                continue
            for idx in range(len(tokens) - n + 1):
                gram_tokens = tokens[idx:idx + n]
                phrase = " ".join(gram_tokens)
                if len(phrase) < 18:
                    continue
                grams[phrase] += 1

        if not grams:
            return []

        items = [
            phrase for phrase, freq in grams.most_common()
            if freq >= 2
        ]
        if not items:
            items = [phrase for phrase, _ in grams.most_common(3)]

        return items[:max_items]

    @staticmethod
    def _normalize_for_fact_match(text: str) -> str:
        normalized = (text or "").lower()
        normalized = normalized.replace("’", "'")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _extract_kb_fact_markers(self, kb_chunks: list[str]) -> set[str]:
        markers: set[str] = set()
        if not kb_chunks:
            return markers

        kb_text = "\n".join(kb_chunks)
        kb_text_norm = self._normalize_for_fact_match(kb_text)

        for match in NUMERIC_FACT_RE.findall(kb_text):
            m = self._normalize_for_fact_match(match)
            if m:
                markers.add(m)

        for match in PROPER_NOUN_RE.findall(kb_text):
            m = self._normalize_for_fact_match(match)
            if len(m) >= 4 and m not in KB_STOPWORDS:
                markers.add(m)

        for token in re.findall(r"\b[a-zA-Z]{5,}\b", kb_text_norm):
            if token in KB_STOPWORDS:
                continue
            markers.add(token)

        for anchor in KB_ANCHOR_TERMS:
            if anchor in kb_text_norm:
                markers.add(anchor)

        # Keep marker set bounded and deterministic.
        return set(sorted(markers)[:120])

    def _count_kb_fact_hits(self, response_text: str, kb_chunks: list[str]) -> int:
        if not kb_chunks:
            return 0

        response_norm = self._normalize_for_fact_match(response_text)
        markers = self._extract_kb_fact_markers(kb_chunks)
        hits = {
            marker for marker in markers
            if marker and marker in response_norm
        }
        return len(hits)

    @staticmethod
    def _count_star_components(response_text: str) -> int:
        response_norm = (response_text or "").lower()
        found = 0
        for _, cues in STAR_SIGNAL_MAP.items():
            if any(cue in response_norm for cue in cues):
                found += 1
        return found

    def validate_generated_response(
        self,
        response_text: str,
        question_type: str,
        kb_chunks: list[str],
    ) -> dict:
        """
        Validate response quality constraints required by the interview prompt.
        """
        reasons: list[str] = []

        kb_hits = self._count_kb_fact_hits(response_text, kb_chunks)
        required_kb_hits = 2 if kb_chunks else 0
        kb_ok = kb_hits >= required_kb_hits
        if not kb_ok:
            reasons.append(f"kb_facts<{required_kb_hits} (hits={kb_hits})")

        sentence_count = len(re.findall(r"[.!?]+", response_text))
        contraction_ok = sentence_count <= 1 or bool(CONTRACTION_RE.search(response_text))
        if not contraction_ok:
            reasons.append("missing_contractions")

        star_components = self._count_star_components(response_text)
        star_required = question_type in {"situational", "hybrid"}
        star_ok = (not star_required) or (star_components >= 3)
        if not star_ok:
            reasons.append(f"weak_star_structure (components={star_components})")

        return {
            "is_valid": kb_ok and contraction_ok and star_ok,
            "reasons": reasons,
            "kb_hits": kb_hits,
            "required_kb_hits": required_kb_hits,
            "contraction_ok": contraction_ok,
            "star_components": star_components,
            "star_ok": star_ok,
            "question_type": question_type,
        }

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
        Generate a full response and run post-generation validation.
        Retries once in hard mode if validation fails.
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
        first_validation = self.validate_generated_response(
            response_text=first,
            question_type=question_type,
            kb_chunks=kb_chunks,
        )
        if first_validation["is_valid"]:
            first_validation["attempts"] = 1
            first_validation["retried"] = False
            return first, first_validation

        logger.warning(
            "Post-generation validation failed (attempt=1): "
            f"{first_validation['reasons']}"
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
        second_validation = self.validate_generated_response(
            response_text=second,
            question_type=question_type,
            kb_chunks=kb_chunks,
        )
        second_validation["attempts"] = 2
        second_validation["retried"] = True
        return second, second_validation

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
        """Generate a complete response (non-streaming, useful for tests)."""
        tokens = []
        async for token in self.generate(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
            recent_questions=recent_questions,
            recent_responses=recent_responses,
            recent_question_types=recent_question_types,
            memory_context=memory_context,
            force_hard_mode=force_hard_mode,
        ):
            tokens.append(token)
        return "".join(tokens)
