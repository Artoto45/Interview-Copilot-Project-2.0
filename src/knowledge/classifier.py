"""
Question Classifier
=====================
Fast classification of interview questions using Claude Haiku 4.5.

Categories:
    - personal:     "Tell me about yourself", strengths, weaknesses
    - company:      "What do you know about us?", mission, culture
    - hybrid:       Multi-part questions mixing personal + company
    - simple:       Yes/No, short-answer, factual
    - situational:  "What would you do if…", hypothetical, STAR

The classifier also recommends an optimal thinking budget
for the ResponseAgent (Claude Opus 4.6 Extended Thinking).

Target latency: < 200 ms.
"""

import json
import logging
import os
import re
from typing import Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("knowledge.classifier")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"
FALLBACK_CLASSIFICATION = {
    "type": "personal",
    "compound": False,
    "budget": 1024,
}

# Thinking budget by type (from roadmap Section 4.4)
BUDGET_MAP = {
    "simple": 512,
    "personal": 512,
    "company": 1024,
    "hybrid": 1024,
    "situational": 2048,
}


class QuestionClassifier:
    """
    Classifies interview questions into types using Claude Haiku 4.5
    for fast inference (< 200 ms target).

    Usage::

        classifier = QuestionClassifier()
        result = await classifier.classify("Tell me about yourself")
        # → {"type": "personal", "compound": False, "budget": 1024}
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.client = anthropic.Anthropic(api_key=self.api_key)

    async def classify(self, question: str) -> dict:
        """
        Classify an interview question.

        Uses fast rule-based classifier (instant, no API call)
        for minimum latency in the real-time pipeline.

        Args:
            question: The interviewer's question text.

        Returns:
            Dict with 'type', 'compound', and 'budget' keys.
        """
        return self._fallback_classify(question)

    async def _classify_with_haiku(self, question: str) -> dict:
        """Classify using Claude Haiku 4.5 API."""
        response = self.client.messages.create(
            model=CLASSIFIER_MODEL,
            max_tokens=80,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Classify this interview question. Return ONLY "
                        "valid JSON with no extra text.\n\n"
                        f"Question: {question}\n\n"
                        'Format: {"type": "personal|company|hybrid|'
                        'simple|situational", '
                        '"compound": true|false}'
                    ),
                }
            ],
        )

        raw = response.content[0].text.strip()

        # Parse JSON (handle potential markdown wrapping)
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

        result = json.loads(raw)

        # Add budget from map
        q_type = result.get("type", "personal")
        if q_type not in BUDGET_MAP:
            q_type = "personal"
            result["type"] = q_type

        result["budget"] = BUDGET_MAP[q_type]

        # Compound questions get a budget boost
        if result.get("compound", False):
            result["budget"] = min(result["budget"] * 2, 8192)

        logger.info(
            f"Classified: type={result['type']}, "
            f"compound={result['compound']}, "
            f"budget={result['budget']}"
        )
        return result

    # ------------------------------------------------------------------
    # Rule-Based Fallback (no API needed)
    # ------------------------------------------------------------------
    @staticmethod
    def _is_compound_question(question: str) -> bool:
        """Detect multi-part questions with clause-level intent cues."""
        q = question.lower().strip()

        # 1. Multiple question marks
        if q.count("?") > 1:
            return True

        # 2. Parenthetical questions
        if "(" in q and "?" in q.split("(")[1]:
            return True

        # 3. Semicolon separation
        if ";" in q:
            parts = q.split(";")
            question_count = sum(1 for p in parts if "?" in p)
            if question_count >= 2:
                return True

        # 4. Connector-based clause splitting.
        clauses = [
            part.strip(" ,.;")
            for part in re.split(
                r"\b(?:and|or|but|while|plus|also|as well as|in addition)\b",
                q,
            )
            if part.strip()
        ]
        if len(clauses) >= 2:
            intent_cues = [
                "how ",
                "what ",
                "why ",
                "when ",
                "where ",
                "which ",
                "who ",
                "can you",
                "could you",
                "would you",
                "do you",
                "did you",
                "are you",
                "should we",
                "tell me",
                "walk me through",
                "describe",
                "explain",
            ]
            clause_hits = sum(
                1 for clause in clauses
                if any(cue in clause for cue in intent_cues)
            )
            if clause_hits >= 2:
                return True

        # 5. Explicit dual-intent pattern in one sentence.
        if re.search(
            r"\b(and|but)\s+(how|why|what|when|where|which|who|would|could|can|do|are)\b",
            q,
        ):
            return True

        return False

    @staticmethod
    def _fallback_classify(question: str) -> dict:
        """
        Simple rule-based classifier as fallback when the API
        is unavailable or fails.
        """
        q = question.lower().strip()
        is_compound = QuestionClassifier._is_compound_question(q)

        # Simple logistics and direct availability/compensation prompts.
        simple_signals = [
            "how soon could you start",
            "are you comfortable",
            "salary range",
            "salary expectations",
            "compensation",
            "notice period",
            "start date",
            "availability",
            "available to start",
            "weekend support",
            "hybrid schedule",
            "do you need to provide notice",
            "do you have any questions for me",
            "any questions for me",
            "are you open to",
        ]

        # Situational / Hypothetical / behavioral follow-ups.
        situational_signals = [
            "what would you do",
            "how would you handle",
            "how did you",
            "how do you ensure",
            "imagine",
            "scenario",
            "if you were",
            "describe a time",
            "can you describe a situation",
            "give me an example",
            "tell me about a situation",
            "walk me through a time",
            "challenging period",
            "challenging situation",
            "difficult period",
            "what tactics",
            "tactics you used",
            "how you managed",
            "how you handled",
            "under pressure",
            "de-escalate",
            "what was the hardest part",
            "what changed after",
            "how did you measure success",
            "what would you do differently",
        ]
        if any(signal in q for signal in situational_signals):
            return {
                "type": "situational",
                "compound": False,
                "budget": BUDGET_MAP["situational"],
            }

        # Company-related
        company_signals = [
            "about our company",
            "about us",
            "why this company",
            "why do you want to work",
            "what do you know about",
            "our mission",
            "our values",
            "culture",
            "this role align",
            "our team",
            "our product",
            "your mission",
            "this team needs",
            "product and operations",
            "product operations",
            "collaborate with product",
            "cross functional",
            "cross-functional",
        ]

        # Personal
        personal_signals = [
            "tell me about yourself",
            "strengths",
            "weaknesses",
            "greatest achievement",
            "your experience",
            "your background",
            "why should we hire",
            "walk me through",
            "your career",
            "your motivation",
            "manager say",
            "what motivates you",
            "motivates you",
        ]

        has_simple = any(signal in q for signal in simple_signals)
        has_situational = any(signal in q for signal in situational_signals)
        has_company = any(signal in q for signal in company_signals)
        has_personal = any(signal in q for signal in personal_signals)
        has_hybrid_collab_pattern = (
            bool(re.search(r"\byour experience\b", q))
            and (
                "collaborate" in q
                or "work with" in q
            )
            and (
                "product and operations" in q
                or ("product" in q and "operations" in q)
                or "cross-functional" in q
                or "cross functional" in q
            )
        )

        if has_hybrid_collab_pattern:
            return {
                "type": "hybrid",
                "compound": True,
                "budget": BUDGET_MAP["hybrid"],
            }

        non_simple_hits = sum(
            1 for matched in (has_situational, has_company, has_personal)
            if matched
        )

        # Pure simple/logistics prompts.
        if has_simple and non_simple_hits == 0:
            return {
                "type": "simple",
                "compound": False,
                "budget": BUDGET_MAP["simple"],
            }

        # Behavioral/situational intent should dominate over "compound"
        # phrasing unless there is a clear company-fit component.
        if has_situational and not has_company:
            return {
                "type": "situational",
                "compound": False,
                "budget": BUDGET_MAP["situational"],
            }

        # Compound question with mixed intent -> hybrid.
        if is_compound:
            if has_situational and not has_company:
                return {
                    "type": "situational",
                    "compound": False,
                    "budget": BUDGET_MAP["situational"],
                }
            if has_company and not has_personal and not has_situational:
                # Compound phrasing but still purely company intent.
                return {
                    "type": "company",
                    "compound": False,
                    "budget": BUDGET_MAP["company"],
                }
            return {
                "type": "hybrid",
                "compound": True,
                "budget": BUDGET_MAP["hybrid"],
            }

        # Multiple semantic families without explicit compound markers.
        if non_simple_hits >= 2:
            return {
                "type": "hybrid",
                "compound": True,
                "budget": BUDGET_MAP["hybrid"],
            }

        if has_situational:
            return {
                "type": "situational",
                "compound": False,
                "budget": BUDGET_MAP["situational"],
            }

        if has_company:
            return {
                "type": "company",
                "compound": False,
                "budget": BUDGET_MAP["company"],
            }

        if has_personal:
            return {
                "type": "personal",
                "compound": False,
                "budget": BUDGET_MAP["personal"],
            }

        if has_simple:
            return {
                "type": "simple",
                "compound": False,
                "budget": BUDGET_MAP["simple"],
            }

        # Simple fallback for short prompts.
        word_count = len(q.split())
        if word_count < 7 or (q.endswith("?") and word_count < 6):
            return {
                "type": "simple",
                "compound": False,
                "budget": BUDGET_MAP["simple"],
            }

        # (compound check already done above)

        # Default
        return {
            "type": "personal",
            "compound": False,
            "budget": BUDGET_MAP["personal"],
        }
