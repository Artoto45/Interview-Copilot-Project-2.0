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
        """Detect multi-part questions with improved logic"""
        q = question.lower().strip()
        
        # 1. Multiple question marks
        if q.count("?") > 1:
            return True
        
        # 2. Connectors with multiple clauses
        import re
        connectors = r'\s+(and|or|plus|also|as well as|in addition|furthermore|additionally)\s+'
        parts = re.split(connectors, q)
        
        if len(parts) >= 3:
            # Check if at least 2 parts contain question-like content
            question_count = sum(
                1 for p in parts 
                if '?' in p or p.strip().endswith(('?', 'do', 'does', 'did'))
            )
            if question_count >= 2:
                return True
        
        # 3. Parenthetical questions
        if "(" in q and "?" in q.split("(")[1]:
            return True
        
        # 4. Semicolon separation
        if ";" in q:
            parts = q.split(";")
            question_count = sum(1 for p in parts if "?" in p)
            if question_count >= 2:
                return True
        
        return False

    @staticmethod
    def _fallback_classify(question: str) -> dict:
        """
        Simple rule-based classifier as fallback when the API
        is unavailable or fails.
        """
        q = question.lower().strip()

        # --- Check compound FIRST (multiple question marks or 'and') ---
        is_compound = QuestionClassifier._is_compound_question(q)
        if is_compound:
            return {
                "type": "hybrid",
                "compound": True,
                "budget": BUDGET_MAP["hybrid"],
            }

        # Situational / Hypothetical
        situational_signals = [
            "what would you do",
            "how would you handle",
            "imagine",
            "scenario",
            "if you were",
            "describe a time",
            "give me an example",
            "tell me about a situation",
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
        ]
        if any(signal in q for signal in company_signals):
            return {
                "type": "company",
                "compound": False,
                "budget": BUDGET_MAP["company"],
            }

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
        ]
        if any(signal in q for signal in personal_signals):
            return {
                "type": "personal",
                "compound": False,
                "budget": BUDGET_MAP["personal"],
            }

        # Simple (short questions, yes/no)
        word_count = len(q.split())
        if word_count < 6 or (q.endswith("?") and word_count < 5):
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
