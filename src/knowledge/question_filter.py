"""
Question Filter — Interview Question Detection
==================================================
Middleware that evaluates whether a transcribed turn is a
"useful interview question" worth triggering the RAG pipeline.

This prevents non-questions (greetings, muletillas, noise,
process commands) from wasting API calls and generating
irrelevant teleprompter responses.

Design: rule-based for zero latency, no API calls needed.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger("knowledge.question_filter")

# ---------------------------------------------------------------------------
# Noise patterns (reject these)
# ---------------------------------------------------------------------------
NOISE_PATTERNS = [
    # Greetings and pleasantries
    r"^(hi|hello|hey|good morning|good afternoon|good evening|nice to meet you|how are you)[\s\.\!]*$",
    # Process commands (meta about the interview itself)
    r"^(can we|let'?s|shall we)\s*(start|restart|begin|retake|resume|pause|stop|end|wrap up)",
    # Filler words only
    r"^(um+|uh+|hmm+|ah+|ok+|okay|alright|sure|right|yeah|yes|no|yep|nope|so|well)[\s\.\!\?]*$",
    # Very short acknowledgments
    r"^(thank you|thanks|great|perfect|excellent|wonderful|cool|got it|I see|makes sense)[\s\.\!]*$",
    # Introductions / meta-talk
    r"^(welcome|let me introduce|before we (start|begin)|we('re| are) going to)",
    # Closing remarks
    r"^(thank you for (your time|coming)|that'?s all|we('re| are) done|have a (good|great|nice) (day|one))",
]
NOISE_RE = [re.compile(p, re.IGNORECASE) for p in NOISE_PATTERNS]

# ---------------------------------------------------------------------------
# Interview question signals (boost these)
# ---------------------------------------------------------------------------
INTERVIEW_SIGNALS = [
    # Classic interview openers
    "tell me about yourself",
    "walk me through",
    "describe a time",
    "give me an example",
    "what would you do",
    "how would you handle",
    "how do you",
    "why do you want",
    "why should we hire",
    "what are your",
    "what is your",
    "what's your",
    "where do you see yourself",
    "what motivates you",
    "what can you bring",
    "what makes you",
    # Behavioral / STAR
    "tell me about a situation",
    "tell me about a time",
    "can you describe",
    "have you ever",
    # Company-focused
    "what do you know about",
    "why this company",
    "why this role",
    "why this position",
    # Technical
    "explain",
    "how does",
    "what experience",
    "what tools",
    "what technologies",
    "how familiar",
    # Strengths/weaknesses
    "strength",
    "weakness",
    "biggest challenge",
    "greatest achievement",
    "proud of",
    "failure",
    "mistake",
    "conflict",
    "disagreement",
    # Salary/logistics (still should generate a response)
    "salary",
    "compensation",
    "availability",
    "start date",
    "notice period",
    "work remotely",
    "relocate",
]

# Minimum word count to consider a turn as a potential question
MIN_WORD_COUNT = 4

# If it's clearly a question (has ?), lower the bar
MIN_WORD_COUNT_WITH_QUESTION_MARK = 3

try:
    from nltk.stem import PorterStemmer
except ImportError:
    PorterStemmer = None


class _LightStemmer:
    """Minimal fallback stemmer when NLTK is unavailable."""

    SUFFIXES = ("ing", "ed", "ly", "es", "s")

    @classmethod
    def stem(cls, word: str) -> str:
        token = word.lower().strip("?,.:;!")
        for suffix in cls.SUFFIXES:
            if len(token) > len(suffix) + 2 and token.endswith(suffix):
                return token[: -len(suffix)]
        return token


_stemmer = PorterStemmer() if PorterStemmer else _LightStemmer()


def _normalize_tokens(text: str) -> set[str]:
    """Normalize text to stemmed tokens."""
    words = text.lower().split()
    return {_stemmer.stem(w.strip("?,.:;!")) for w in words if w}

def has_interview_signal_fuzzy(question: str, threshold: float = 0.70) -> bool:
    """Check for interview signals using fuzzy matching
    
    Fast path: direct string matching (O(1))
    Slow path: fuzzy matching with stemming (O(n))
    """
    q = question.lower()
    
    # Fast path: direct signals
    for signal in INTERVIEW_SIGNALS:
        if signal in q:
            return True
    
    # Slow path: fuzzy matching
    q_tokens = _normalize_tokens(question)
    if not q_tokens:
        return False
    
    for signal in INTERVIEW_SIGNALS:
        signal_tokens = _normalize_tokens(signal)
        if not signal_tokens:
            continue
        
        # Token overlap ratio
        overlap = len(q_tokens & signal_tokens) / len(signal_tokens)
        if overlap >= threshold:
            logger.debug(f"Fuzzy match '{signal}' (overlap={overlap:.2f})")
            return True
    
    return False


class QuestionFilter:
    """
    Evaluates whether a transcribed utterance is an interview
    question worth processing.

    Usage::

        qf = QuestionFilter()
        if qf.is_interview_question("Tell me about yourself"):
            await process_question(text)
    """

    def __init__(self):
        self._total_checked = 0
        self._total_passed = 0
        self._total_rejected = 0

    def is_interview_question(self, text: str) -> bool:
        """
        Determine if the text is a real interview question.

        Returns True if the question should trigger the RAG pipeline.
        """
        self._total_checked += 1

        if not text or not text.strip():
            self._reject("empty", text)
            return False

        cleaned = text.strip()
        words = cleaned.split()
        word_count = len(words)
        has_question_mark = "?" in cleaned

        # --- Check 1: Reject noise patterns ---
        for pattern in NOISE_RE:
            if pattern.search(cleaned):
                self._reject("noise_pattern", cleaned)
                return False

        # --- Check 2: Minimum length ---
        min_words = (
            MIN_WORD_COUNT_WITH_QUESTION_MARK
            if has_question_mark
            else MIN_WORD_COUNT
        )
        if word_count < min_words:
            self._reject(f"too_short ({word_count} words)", cleaned)
            return False

        # --- Check 3: Strong interview signals (always pass) ---
        text_lower = cleaned.lower()
        if has_interview_signal_fuzzy(text_lower):
            self._accept(f"interview_signal (fuzzy/exact)", cleaned)
            return True

        # --- Check 4: Has question mark (likely a question) ---
        if has_question_mark and word_count >= MIN_WORD_COUNT_WITH_QUESTION_MARK:
            self._accept("has_question_mark", cleaned)
            return True

        # --- Check 5: Long enough statement (might be a prompt) ---
        # "Tell me about your experience at X" doesn't have a ?
        if word_count >= 6:
            self._accept(f"long_statement ({word_count} words)", cleaned)
            return True

        # Default: reject
        self._reject("no_signals", cleaned)
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _accept(self, reason: str, text: str):
        self._total_passed += 1
        logger.info(
            f"QUESTION ACCEPTED ({reason}): "
            f"{text[:80]}{'…' if len(text) > 80 else ''}"
        )

    def _reject(self, reason: str, text: str):
        self._total_rejected += 1
        logger.info(
            f"QUESTION REJECTED ({reason}): "
            f"{text[:80]}{'…' if len(text) > 80 else ''}"
        )

    @property
    def stats(self) -> dict:
        return {
            "total_checked": self._total_checked,
            "total_passed": self._total_passed,
            "total_rejected": self._total_rejected,
        }
