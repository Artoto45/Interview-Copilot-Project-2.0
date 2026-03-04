"""
Response Agent — Claude Sonnet 4 (Prompt Caching + Fast Streaming)
====================================================================
High quality + low latency via:
    - Anthropic Prompt Caching (85% TTFT reduction after first call)
    - AsyncAnthropic (non-blocking event loop)
    - NO Extended Thinking
    - Enhanced prompt with KB grounding and no meta-commentary

Target latency: ~2s after cache warm, ~4s on cache miss.
"""

import logging
import os
from typing import AsyncIterator, Optional

import anthropic
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("response.claude")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MODEL = "claude-3-5-sonnet-20241022"  # Corrected to valid Claude model

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


class ResponseAgent:
    """
    Generates interview responses using Claude Sonnet 4 with:
    - Prompt caching (85% TTFT reduction)
    - Async streaming
    - Two-phase instant openers
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY", "")
        self.pricing_model = "claude_sonnet"
        self.supports_prompt_cache = True
        self.system_prompt_token_estimate = 1024
        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        self._warmed_up = False
        
        # Phase 3 Quality: Cache Audit & Optimization
        self._cache_stats = {
            "total_calls": 0,
            "cache_hits": 0,
            "by_type": {}
        }

    async def warmup(self):
        """Prime the prompt cache with the system prompt."""
        if self._warmed_up:
            return
            
        logger.info("Warming up ResponseAgent cache...")
        try:
            # Send a minimal request with the exact system prompt
            # to trigger server-side caching
            await self.client.messages.create(
                model=MODEL,
                max_tokens=10,
                temperature=0.0,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": "Hi"}],
            )
            self._warmed_up = True
            logger.info("ResponseAgent cache warmed up successfully ✓")
        except Exception as e:
            logger.warning(f"Cache warmup failed: {e}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get_instant_opener(self, question_type: str) -> str:
        """
        Get an instant opener for two-phase response.
        Returns a speakable opener in <1ms (no API call).
        """
        return INSTANT_OPENERS.get(question_type, "So basically… ")

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
    ) -> AsyncIterator[str]:
        """
        Generate a streaming response with prompt caching.

        The system prompt is cached server-side via cache_control.
        After first call, subsequent calls get ~85% TTFT reduction.

        Yields:
            Response text tokens (streaming).
        """
        if not self.api_key:
            logger.error("ANTHROPIC_API_KEY not set")
            yield "[Error: API key not configured]"
            return

        user_message = self._build_user_message(
            question=question,
            kb_chunks=kb_chunks,
            question_type=question_type,
            memory_context=memory_context,
        )

        temperature = TEMPERATURE_MAP.get(question_type, 0.3)

        # Initialize stats for this type
        if question_type not in self._cache_stats["by_type"]:
            self._cache_stats["by_type"][question_type] = {"calls": 0, "hits": 0}
            
        self._cache_stats["total_calls"] += 1
        self._cache_stats["by_type"][question_type]["calls"] += 1

        logger.info(
            f"Generating response: type={question_type}, "
            f"model={MODEL}, temp={temperature}, "
            f"cache_hits={self._cache_stats['cache_hits']}/{self._cache_stats['total_calls']}"
        )

        try:
            # System prompt with cache_control for prompt caching
            # After first call, this is served from cache (~85% faster)
            async with self.client.messages.stream(
                model=MODEL,
                max_tokens=1024,
                temperature=temperature,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": user_message}],
            ) as stream:
                # Track cache performance from response headers
                async for text in stream.text_stream:
                    yield text

                # After stream completes, check cache usage
                response = await stream.get_final_message()
                if response.usage:
                    cached = getattr(response.usage, 'cache_read_input_tokens', 0)
                    if cached and cached > 0:
                        self._cache_stats["cache_hits"] += 1
                        self._cache_stats["by_type"][question_type]["hits"] += 1
                        logger.info(
                            f"CACHE HIT ⚡ {cached} tokens from cache"
                        )
                    else:
                        cache_created = getattr(
                            response.usage, 'cache_creation_input_tokens', 0
                        )
                        if cache_created and cache_created > 0:
                            logger.info(
                                f"CACHE CREATED: {cache_created} tokens cached "
                                f"for next requests"
                            )

        except Exception as e:
            logger.error(f"Response generation error: {e}", exc_info=True)
            yield f"[Error generating response: {e}]"

    # ------------------------------------------------------------------
    # Prompt Construction
    # ------------------------------------------------------------------
    def _build_user_message(
        self,
        question: str,
        kb_chunks: list[str],
        question_type: str,
        memory_context: Optional[str] = None,
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
            f"{memory_context or '[INTERVIEW MEMORY]\\n[none]'}\n\n"
            f"[KNOWLEDGE BASE]:\n{kb_section}\n\n"
            f"[INTERVIEWER QUESTION]:\n{question}"
        )

    # ------------------------------------------------------------------
    # Warmup (also primes the cache)
    # ------------------------------------------------------------------
    async def warmup(self):
        """
        Pre-warm API connection AND prime the prompt cache.
        This ensures the first real question gets a cache hit.
        """
        if self._warmed_up:
            return

        try:
            logger.info("Warming up Claude API + priming prompt cache…")
            # Use the full system prompt to prime the cache
            response = await self.client.messages.create(
                model=MODEL,
                max_tokens=5,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": "Hi"}],
            )
            self._warmed_up = True

            # Check if cache was created
            if response.usage:
                cache_created = getattr(
                    response.usage, 'cache_creation_input_tokens', 0
                )
                logger.info(
                    f"Claude API warmup complete ✓ "
                    f"(cache primed: {cache_created} tokens)"
                )
        except Exception as e:
            logger.warning(f"Warmup failed (non-critical): {e}")

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
