"""
Response Agent — OpenAI GPT-4o-mini (Streaming)
===================================================
High quality + low latency interview copilot responses using native OpenAI integration.
Replaces Gemini/Claude in Phase 6 to achieve lower costs while maintaining high quality.
"""

import logging
import os
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

CRITICAL RULES — follow ALL of these strictly:
1. Use contractions ALWAYS: I'm, we've, they're, I'd, it's, don't, wasn't
2. Short sentences: 12–18 words max per sentence for easy reading aloud
3. Start with conversational connectors: "So basically…", "What I found was…", \
   "The thing is…", "Actually…", "I'd say…", "Honestly…"
4. STAR method for behavioral/situational questions: \
   Situation → Task → Action → Result (clear structure)
5. Match response length to the [LENGTH] tag below
6. Use ONLY facts from the [KNOWLEDGE BASE] — NEVER invent experiences, \
   companies, job titles, or metrics that aren't in the KB
7. Never reveal you are an AI, a script, or a teleprompter
8. Write in first person as the candidate
9. Add [PAUSE] where the speaker should breathe (every 2–3 sentences)
10. Add **bold** on key words the speaker should emphasize
11. Replace formal vocabulary: "utilize"→"use", "regarding"→"about", \
    "demonstrate"→"show", "facilitate"→"help"
12. Output ONLY the speakable words. NEVER include headers (#), titles, \
    markdown sections, horizontal rules (---), bullet lists, delivery notes, \
    tips, or meta-commentary. No "Here's what you should say:" preambles.
13. Reference specific facts from [KNOWLEDGE BASE] in every response: \
    company names (Webhelp), metrics (92% QA), years (3+ years), specifics \
    (remote, BPO, Python). The response MUST contain at least 2 KB facts.
"""

# Length guides by question type
LENGTH_GUIDE = {
    "simple": "1–2 sentences",
    "personal": "3–4 sentences",
    "company": "4–5 sentences",
    "hybrid": "5–6 sentences",
    "situational": "5–6 sentences (STAR format)",
}

# Temperature by question type
TEMPERATURE_MAP = {
    "simple": 0.3,
    "personal": 0.3,
    "company": 0.3,
    "hybrid": 0.4,
    "situational": 0.5,
}

# Instant openers for two-phase response (no API call needed)
INSTANT_OPENERS = {
    "personal": "So basically, in my experience at Webhelp… ",
    "company": "So basically, what drew me to your company… ",
    "situational": "So basically, there was this time at Webhelp… ",
    "hybrid": "So basically, I'd approach that by… ",
    "simple": "Honestly, I'd say… ",
}


class OpenAIAgent:
    """
    Generates interview responses natively via OpenAI Async client.
    Features:
    - High-speed output stream (GPT-4o-mini is exceptionally fast)
    - Asynchronous streaming compatible with the realtime pipeline
    - Direct integration with CostTracker
    """

    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("OPENAI_API_KEY")
        if not key:
            logger.warning("OPENAI_API_KEY is not set. Response API will fail.")
            
        self.client = openai.AsyncOpenAI(api_key=key)
        self._warmed_up = False
        
        self._cache_stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "by_type": {}
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
                    {"role": "user", "content": "Hi"}
                ],
                max_tokens=5,
                temperature=0.0
            )
            self._warmed_up = True
            logger.info("OpenAIAgent initialized successfully ✓")
        except Exception as e:
            logger.warning(f"Model warmup failed: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_instant_opener(self, question_type: str) -> str:
        """Get an instant opener for two-phase response (0 latency)."""
        return INSTANT_OPENERS.get(question_type, "So basically… ")

    async def generate(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
    ) -> AsyncGenerator[str, None]:
        """
        Generate a streaming response with the OpenAI Async API.
        Yields text chunks immediately as they arrive.
        """
        user_message = self._build_user_message(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
        )

        temperature = TEMPERATURE_MAP.get(question_type, 0.3)

        if question_type not in self._cache_stats["by_type"]:
            self._cache_stats["by_type"][question_type] = {"calls": 0, "hits": 0}
            
        self._cache_stats["total_calls"] += 1
        self._cache_stats["by_type"][question_type]["calls"] += 1

        logger.info(
            f"Generating response: type={question_type}, "
            f"model={MODEL}, temp={temperature}"
        )

        try:
            response_stream = await self.client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message}
                ],
                temperature=temperature,
                max_tokens=1024,
                stream=True,
            )

            async for chunk in response_stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        yield delta.content

        except Exception as e:
            logger.error(f"OpenAI Response generation error: {e}", exc_info=True)
            yield f"[Error generating response: {e}]"

    # ------------------------------------------------------------------
    # Prompt Construction
    # ------------------------------------------------------------------
    def _build_user_message(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str,
    ) -> str:
        """Build the user message with KB context."""
        length = LENGTH_GUIDE.get(question_type, "3–4 sentences")

        kb_section = "\n\n".join(kb_chunks) if kb_chunks else (
            "[No knowledge base context available — answer with general "
            "best practices for this type of question]"
        )

        return (
            f"[QUESTION TYPE]: {question_type}\n"
            f"[LENGTH]: {length}\n\n"
            f"[KNOWLEDGE BASE]:\n{kb_section}\n\n"
            f"[INTERVIEWER QUESTION]:\n{question}"
        )

    # ------------------------------------------------------------------
    # Non-streaming variant (for testing)
    # ------------------------------------------------------------------
    async def generate_full(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str = "personal",
        thinking_budget: int = 0,
    ) -> str:
        """Generate a complete response (non-streaming, for testing)."""
        tokens = []
        async for token in self.generate(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
        ):
            tokens.append(token)
        return "".join(tokens)
