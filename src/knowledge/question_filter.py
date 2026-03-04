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

UNICODE_PUNCT_TRANSLATION = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
    "\u00a0": " ",
})

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

# Leading conversational transitions that often precede the real question.
# We strip these prefixes before classifying to avoid over-reacting.
TRANSITION_PREFIX_PATTERNS = [
    r"^no problem[\s\.\!\,\-]*",
    r"^let'?s reset( once more| again)?[\s\.\!\,]*",
    r"^perfect[\s\.\!\,]*",
    r"^great[\s\.\!\,]*",
    r"^awesome[\s\.\!\,]*",
    r"^absolutely[\s\.\!\,]*",
    r"^sounds good[\s\.\!\,]*",
    r"^let'?s move forward[\s\.\!\,]*",
    r"^let'?s continue[\s\.\!\,]*",
    r"^all right[\s\.\!\,]*",
    r"^alright[\s\.\!\,]*",
    r"^okay[\s\.\!\,]*",
    r"^ok[\s\.\!\,]*",
    r"^thanks for sharing[\s\.\!\,]*",
    r"^that'?s a (solid|strong|great) "
    r"(example|demonstration|answer)[\s\.\!\,]*",
    r"^if you'?d like to continue[\s\.\!\,]*",
    r"^if you'?d like to (tackle|explore)[\s\w,\-]*[\s\.\!\,]*",
    r"^let'?s raise the bar( a bit)?[\s\.\!\,]*",
    r"^if you'?re ready[\s\.\!\,]*",
]
TRANSITION_PREFIX_RE = [
    re.compile(p, re.IGNORECASE) for p in TRANSITION_PREFIX_PATTERNS
]

# Phrases that are explicitly not interview questions unless followed by one.
NON_QUESTION_TRANSITIONS = [
    "if you'd like to continue",
    "i'm ready for the next step",
    "or wrap up whenever you feel complete",
    "or pivot to a different focus",
    "whenever you feel complete",
    "if you'd like to tackle another scenario",
]

QUESTION_INTENT_CUES = [
    "can you",
    "could you",
    "would you",
    "tell me",
    "give me",
    "walk me through",
    "describe",
    "explain",
    "how did you",
    "how would you",
    "what",
    "why",
    "when",
    "where",
    "which",
    "who",
    "do you",
    "did you",
    "have you",
    "are you",
    "is there",
    "would it",
]

# Fragment clues that usually indicate we caught the middle of a sentence
# instead of the full interview question.
FRAGMENT_LEADING_MARKERS = {
    "and",
    "or",
    "but",
    "during",
    "while",
    "because",
    "since",
    "although",
    "though",
    "after",
    "before",
    "with",
    "without",
    "plus",
    "also",
}

FRAGMENT_TRAILING_MARKERS = {
    "and",
    "or",
    "but",
    "because",
    "so",
    "to",
    "with",
    "for",
    "about",
    "in",
    "on",
    "at",
    "from",
}

QUESTION_OPENERS = {
    "can",
    "could",
    "would",
    "should",
    "do",
    "did",
    "are",
    "is",
    "have",
    "tell",
    "walk",
    "describe",
    "give",
    "what",
    "why",
    "how",
    "when",
    "where",
    "which",
    "who",
}

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

from nltk.stem import PorterStemmer
_stemmer = PorterStemmer()

def _normalize_tokens(text: str) -> set[str]:
    """Normalize text to stemmed tokens"""
    words = text.lower().split()
    return {_stemmer.stem(w.strip('?,.:;!')) for w in words if w}

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


def normalize_for_rules(text: str) -> str:
    candidate = (text or "").translate(UNICODE_PUNCT_TRANSLATION)
    candidate = re.sub(r"\s+", " ", candidate)
    return candidate.strip()


def strip_transition_prefixes(text: str, max_rounds: int = 4) -> str:
    """
    Remove leading transition phrases so classification focuses
    on the true question content.
    """
    candidate = (text or "").strip()
    if not candidate:
        return candidate

    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        before = candidate
        for pattern in TRANSITION_PREFIX_RE:
            candidate = pattern.sub("", candidate, count=1).lstrip(" ,.-")
        if candidate == before:
            break

    return candidate.strip()


def is_non_question_transition(text: str) -> bool:
    lowered = normalize_for_rules(text).lower()
    if not lowered:
        return True
    return any(phrase in lowered for phrase in NON_QUESTION_TRANSITIONS)


def has_explicit_question_mark(text: str) -> bool:
    """
    Detect real question marks (e.g., sentence-ending '?'),
    ignoring mojibake cases like "that?s".
    """
    candidate = normalize_for_rules(text)
    return bool(re.search(r"\?(?=\s|$|[\"')\]])", candidate))


def has_question_intent(text: str) -> bool:
    lowered = normalize_for_rules(text).lower()
    return any(cue in lowered for cue in QUESTION_INTENT_CUES)


def analyze_fragment_risk(text: str) -> dict:
    """
    Heuristic detector for likely truncated question fragments.

    Returns:
        Dict with:
            - is_fragment: bool
            - reason: str
            - normalized_text: str
    """
    cleaned = normalize_for_rules(text)
    normalized = strip_transition_prefixes(cleaned)
    if not normalized:
        return {
            "is_fragment": True,
            "reason": "empty_after_normalization",
            "normalized_text": "",
        }

    words = [w for w in re.split(r"\s+", normalized) if w]
    if not words:
        return {
            "is_fragment": True,
            "reason": "empty_tokens",
            "normalized_text": normalized,
        }

    first = re.sub(r"^[^a-zA-Z]+|[^a-zA-Z]+$", "", words[0].lower())
    last = re.sub(r"^[^a-zA-Z]+|[^a-zA-Z]+$", "", words[-1].lower())

    has_qmark = has_explicit_question_mark(normalized)
    has_intent = has_question_intent(normalized)
    strong_signal = has_interview_signal_fuzzy(normalized.lower())
    is_opening = first in QUESTION_OPENERS

    if first in FRAGMENT_LEADING_MARKERS and not is_opening:
        return {
            "is_fragment": True,
            "reason": "leading_fragment_marker",
            "normalized_text": normalized,
        }

    if last in FRAGMENT_TRAILING_MARKERS and len(words) >= 3:
        return {
            "is_fragment": True,
            "reason": "trailing_fragment_marker",
            "normalized_text": normalized,
        }

    # Short question-shaped fragments often look valid, but are incomplete.
    if (
        has_qmark
        and has_intent
        and not strong_signal
        and len(words) <= 6
        and not is_opening
    ):
        return {
            "is_fragment": True,
            "reason": "short_ambiguous_question_fragment",
            "normalized_text": normalized,
        }

    return {
        "is_fragment": False,
        "reason": "none",
        "normalized_text": normalized,
    }


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

    @staticmethod
    def normalize_question_text(text: str) -> str:
        """
        Normalize interviewer turn text for downstream classification/logging.
        """
        cleaned = normalize_for_rules(text or "")
        normalized = strip_transition_prefixes(cleaned)
        return normalized or cleaned

    def analyze_interview_turn(self, text: str) -> dict:
        """
        Determine if the text is a real interview question and provide
        structured metadata for gating/classification.

        Returns:
            Dict with:
                - is_question: bool
                - normalized_text: str
                - reason: str
                - fragment_risk: bool
                - fragment_reason: str
        """
        self._total_checked += 1

        if not text or not text.strip():
            self._reject("empty", text)
            return {
                "is_question": False,
                "normalized_text": "",
                "reason": "empty",
                "fragment_risk": False,
                "fragment_reason": "none",
            }

        cleaned = normalize_for_rules(text.strip())
        normalized = strip_transition_prefixes(cleaned)
        if not normalized:
            self._reject("transition_only", cleaned)
            return {
                "is_question": False,
                "normalized_text": "",
                "reason": "transition_only",
                "fragment_risk": False,
                "fragment_reason": "none",
            }

        # Keep original for logs, classify on normalized payload.
        cleaned = normalized
        words = cleaned.split()
        word_count = len(words)
        has_question_mark = has_explicit_question_mark(cleaned)
        text_lower = cleaned.lower()
        strong_signal = has_interview_signal_fuzzy(text_lower)
        intent_signal = has_question_intent(text_lower)

        # --- Check 1: Reject noise patterns ---
        for pattern in NOISE_RE:
            if pattern.search(cleaned):
                self._reject("noise_pattern", cleaned)
                return {
                    "is_question": False,
                    "normalized_text": cleaned,
                    "reason": "noise_pattern",
                    "fragment_risk": False,
                    "fragment_reason": "none",
                }

        # --- Check 2: Minimum length ---
        min_words = (
            MIN_WORD_COUNT_WITH_QUESTION_MARK
            if has_question_mark
            else MIN_WORD_COUNT
        )
        if word_count < min_words:
            self._reject(f"too_short ({word_count} words)", cleaned)
            return {
                "is_question": False,
                "normalized_text": cleaned,
                "reason": f"too_short ({word_count} words)",
                "fragment_risk": False,
                "fragment_reason": "none",
            }

        # --- Check 3: Reject transition-only feedback early ---
        if (
            is_non_question_transition(text_lower)
            and not strong_signal
            and not intent_signal
        ):
            self._reject("non_question_transition", cleaned)
            return {
                "is_question": False,
                "normalized_text": cleaned,
                "reason": "non_question_transition",
                "fragment_risk": False,
                "fragment_reason": "none",
            }

        # --- Check 4: Strong interview signals ---
        if strong_signal and not has_question_mark and not intent_signal:
            self._reject("signal_without_question_intent", cleaned)
            return {
                "is_question": False,
                "normalized_text": cleaned,
                "reason": "signal_without_question_intent",
                "fragment_risk": False,
                "fragment_reason": "none",
            }

        # Strong signal + question intent passes.
        if strong_signal:
            self._accept(f"interview_signal (fuzzy/exact)", cleaned)
            fragment = analyze_fragment_risk(cleaned)
            return {
                "is_question": True,
                "normalized_text": cleaned,
                "reason": "interview_signal (fuzzy/exact)",
                "fragment_risk": bool(fragment["is_fragment"]),
                "fragment_reason": str(fragment["reason"]),
            }

        # --- Check 5: Has question mark + intent (likely a real question) ---
        if (
            has_question_mark
            and word_count >= MIN_WORD_COUNT_WITH_QUESTION_MARK
            and intent_signal
        ):
            self._accept("has_question_mark", cleaned)
            fragment = analyze_fragment_risk(cleaned)
            return {
                "is_question": True,
                "normalized_text": cleaned,
                "reason": "has_question_mark",
                "fragment_risk": bool(fragment["is_fragment"]),
                "fragment_reason": str(fragment["reason"]),
            }

        # --- Check 4.5: Reject empathy/active listening statements ---
        empathy_patterns = [
            "i understand", "that must have been", "that sounds", 
            "that makes sense", "i hear you", "i see", "got it"
        ]
        if not has_question_mark:
            if any(text_lower.startswith(p) for p in empathy_patterns):
                self._reject("empathy_statement", cleaned)
                return {
                    "is_question": False,
                    "normalized_text": cleaned,
                    "reason": "empathy_statement",
                    "fragment_risk": False,
                    "fragment_reason": "none",
                }

        # Default: reject
        self._reject("no_signals", cleaned)
        return {
            "is_question": False,
            "normalized_text": cleaned,
            "reason": "no_signals",
            "fragment_risk": False,
            "fragment_reason": "none",
        }

    def is_interview_question(self, text: str) -> bool:
        """
        Backward-compatible API used by tests and existing callers.
        """
        analysis = self.analyze_interview_turn(text)
        return bool(analysis["is_question"])

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
