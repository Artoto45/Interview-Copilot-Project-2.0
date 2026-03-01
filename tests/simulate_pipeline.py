"""
Pipeline Simulation — 20+ Synthetic Interview Questions
=========================================================
Tests the full pipeline: classify → retrieve → generate
Measures latency and analyzes response quality on 10 criteria.

Includes tricky questions where last words change the context.
"""

import asyncio
import json
import re
import sys
import time
import os

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.knowledge.classifier import QuestionClassifier
from src.knowledge.retrieval import KnowledgeRetriever
from src.knowledge.question_filter import QuestionFilter
from src.response.claude_agent import ResponseAgent

# ---------------------------------------------------------------------------
# 20+ Synthetic Interview Questions
# ---------------------------------------------------------------------------
QUESTIONS = [
    # --- Simple questions ---
    {
        "id": 1,
        "question": "Tell me about yourself.",
        "expected_type": "personal",
        "difficulty": "simple",
    },
    {
        "id": 2,
        "question": "What are your greatest strengths?",
        "expected_type": "personal",
        "difficulty": "simple",
    },
    {
        "id": 3,
        "question": "Why should we hire you?",
        "expected_type": "personal",
        "difficulty": "simple",
    },
    {
        "id": 4,
        "question": "What is your biggest weakness?",
        "expected_type": "personal",
        "difficulty": "simple",
    },
    {
        "id": 5,
        "question": "Where do you see yourself in five years?",
        "expected_type": "personal",
        "difficulty": "simple",
    },

    # --- Company questions ---
    {
        "id": 6,
        "question": "Why do you want to work for our company?",
        "expected_type": "company",
        "difficulty": "medium",
    },
    {
        "id": 7,
        "question": "What do you know about our company culture?",
        "expected_type": "company",
        "difficulty": "medium",
    },

    # --- Situational / Behavioral (STAR) ---
    {
        "id": 8,
        "question": "Describe a time when you had to deal with a difficult coworker.",
        "expected_type": "situational",
        "difficulty": "medium",
    },
    {
        "id": 9,
        "question": "Give me an example of a project where you showed leadership.",
        "expected_type": "situational",
        "difficulty": "medium",
    },
    {
        "id": 10,
        "question": "Tell me about a time you failed at something and what you learned from it.",
        "expected_type": "situational",
        "difficulty": "medium",
    },

    # --- Hybrid / Complex ---
    {
        "id": 11,
        "question": "What motivates you in your work, and how does that align with our team's goals?",
        "expected_type": "hybrid",
        "difficulty": "complex",
    },
    {
        "id": 12,
        "question": "Walk me through your experience and explain how it prepares you for this specific role.",
        "expected_type": "personal",
        "difficulty": "complex",
    },

    # --- Tricky: last words change the context ---
    {
        "id": 13,
        "question": "Can you tell me about your experience working in a team... that completely fell apart?",
        "expected_type": "situational",
        "difficulty": "tricky",
        "note": "Last phrase changes from positive teamwork to failure scenario",
    },
    {
        "id": 14,
        "question": "What would you say is your greatest achievement... that you now regret?",
        "expected_type": "situational",
        "difficulty": "tricky",
        "note": "Last phrase flips from positive to negative",
    },
    {
        "id": 15,
        "question": "How do you handle pressure when the deadline is tomorrow... and the entire project scope just changed?",
        "expected_type": "situational",
        "difficulty": "tricky",
        "note": "Last clause adds extreme complexity",
    },
    {
        "id": 16,
        "question": "Describe your approach to documentation... when no one else on the team cares about it.",
        "expected_type": "situational",
        "difficulty": "tricky",
        "note": "Last clause changes context to adversity",
    },
    {
        "id": 17,
        "question": "Tell me about a time you went above and beyond for a customer... who turned out to be completely wrong.",
        "expected_type": "situational",
        "difficulty": "tricky",
        "note": "Last clause reverses the positive into awkward territory",
    },
    {
        "id": 18,
        "question": "What's your ideal work environment... and what do you do when reality doesn't match it?",
        "expected_type": "hybrid",
        "difficulty": "tricky",
        "note": "Second part turns ideal scenario into coping question",
    },

    # --- Edge cases ---
    {
        "id": 19,
        "question": "If your previous supervisor were here right now, what would they say about your work ethic?",
        "expected_type": "personal",
        "difficulty": "complex",
    },
    {
        "id": 20,
        "question": "How do you prioritize tasks when everything seems equally urgent and your manager is unavailable?",
        "expected_type": "situational",
        "difficulty": "complex",
    },
    {
        "id": 21,
        "question": "What salary range are you expecting for this position?",
        "expected_type": "personal",
        "difficulty": "simple",
    },
    {
        "id": 22,
        "question": "Are you available to start immediately, or do you need to give notice at your current position?",
        "expected_type": "simple",
        "difficulty": "simple",
    },
]


# ---------------------------------------------------------------------------
# Quality Analysis Functions
# ---------------------------------------------------------------------------
CONTRACTIONS = [
    "i'm", "i've", "i'd", "i'll", "we've", "we're", "we'd",
    "they're", "they've", "it's", "don't", "didn't", "doesn't",
    "wasn't", "weren't", "won't", "can't", "couldn't", "shouldn't",
    "wouldn't", "that's", "what's", "there's", "here's", "he's",
    "she's", "isn't",
]

CONNECTORS = [
    "so basically", "what i found", "the thing is", "actually",
    "i'd say", "honestly", "in my experience", "what happened was",
    "to be honest", "the way i see it", "looking back",
]	

STAR_SIGNALS = {
    "situation": ["situation", "at webhelp", "in my role", "when i was", "there was a time", "at my previous"],
    "task": ["task", "needed to", "had to", "was responsible", "my job was", "i was asked"],
    "action": ["action", "so i", "what i did", "i decided", "i started", "i took", "my approach"],
    "result": ["result", "outcome", "ended up", "turned out", "improved", "reduced", "helped", "meant that"],
}


def analyze_response(response: str, question_type: str) -> dict:
    """Analyze response quality on 10 criteria."""
    text_lower = response.lower()
    sentences = [s.strip() for s in re.split(r'[.!?]+', response) if s.strip()]

    # 1. Contractions
    contraction_count = sum(1 for c in CONTRACTIONS if c in text_lower)
    contraction_score = min(10, contraction_count * 2)

    # 2. Short sentences (≤18 words)
    word_counts = [len(s.split()) for s in sentences if len(s.split()) > 1]
    if word_counts:
        short_pct = sum(1 for w in word_counts if w <= 18) / len(word_counts)
        sentence_score = round(short_pct * 10)
    else:
        sentence_score = 5

    # 3. Conversational connectors
    connector_count = sum(1 for c in CONNECTORS if c in text_lower)
    connector_score = min(10, connector_count * 3)

    # 4. STAR method (for situational/hybrid)
    star_score = 10
    if question_type in ("situational", "hybrid"):
        star_found = 0
        for component, signals in STAR_SIGNALS.items():
            if any(s in text_lower for s in signals):
                star_found += 1
        star_score = round((star_found / 4) * 10)

    # 5. Grounded in KB
    kb_signals = ["webhelp", "qa", "92%", "remote", "bpo", "documentation",
                  "quality", "process", "operations", "customer"]
    kb_count = sum(1 for s in kb_signals if s in text_lower)
    kb_score = min(10, kb_count * 2)

    # 6. Natural/speakable
    formal_words = ["utilize", "facilitate", "demonstrate", "regarding",
                    "furthermore", "nevertheless", "henceforth", "pursuant"]
    formal_count = sum(1 for w in formal_words if w in text_lower)
    natural_score = max(0, 10 - formal_count * 3)

    # 7. Bold keywords
    bold_matches = re.findall(r'\*\*[^*]+\*\*', response)
    bold_score = min(10, len(bold_matches) * 3)

    # 8. [PAUSE] markers
    pause_count = response.count("[PAUSE]")
    pause_score = min(10, pause_count * 4)

    # 9. No AI reveal
    ai_reveals = ["as an ai", "i'm an ai", "artificial intelligence",
                  "language model", "teleprompter", "copilot", "script"]
    ai_found = any(r in text_lower for r in ai_reveals)
    ai_score = 0 if ai_found else 10

    # 10. Length adequacy
    length_targets = {
        "simple": (1, 3),
        "personal": (3, 5),
        "company": (4, 6),
        "hybrid": (5, 7),
        "situational": (5, 7),
    }
    target = length_targets.get(question_type, (3, 5))
    if target[0] <= len(sentences) <= target[1]:
        length_score = 10
    elif abs(len(sentences) - target[0]) <= 1 or abs(len(sentences) - target[1]) <= 1:
        length_score = 7
    else:
        length_score = 4

    scores = {
        "contractions": contraction_score,
        "short_sentences": sentence_score,
        "connectors": connector_score,
        "star_method": star_score,
        "kb_grounded": kb_score,
        "natural_speakable": natural_score,
        "bold_keywords": bold_score,
        "pause_markers": pause_score,
        "no_ai_reveal": ai_score,
        "length_adequate": length_score,
    }
    scores["average"] = round(sum(scores.values()) / len(scores), 1)

    return scores


# ---------------------------------------------------------------------------
# Main Simulation
# ---------------------------------------------------------------------------
async def run_simulation():
    """Run all 22 questions through the pipeline and analyze."""
    print("=" * 70)
    print("  INTERVIEW COPILOT — Pipeline Simulation")
    print(f"  Questions: {len(QUESTIONS)}")
    print("=" * 70)
    print()

    # Initialize components
    classifier = QuestionClassifier()
    retriever = KnowledgeRetriever()
    response_agent = ResponseAgent()
    question_filter = QuestionFilter()

    # Warmup
    print("Warming up Claude API…")
    await response_agent.warmup()
    print()

    results = []

    for q in QUESTIONS:
        qid = q["id"]
        question = q["question"]
        expected = q["expected_type"]
        difficulty = q["difficulty"]

        print(f"─── Q{qid:02d} ({difficulty}) ───")
        print(f"  Q: {question}")

        # Filter check
        passed_filter = question_filter.is_interview_question(question)
        if not passed_filter:
            print(f"  ❌ REJECTED by QuestionFilter")
            results.append({
                "id": qid, "question": question, "difficulty": difficulty,
                "filtered": True, "latency_ms": 0, "scores": None,
            })
            print()
            continue

        # Full pipeline with timing
        t0 = time.perf_counter()

        # 1. Classify
        classification = classifier._fallback_classify(question)
        t1 = time.perf_counter()

        # 2. Retrieve
        kb_chunks = await retriever.retrieve(
            query=question,
            question_type=classification["type"],
        )
        t2 = time.perf_counter()

        # 3. Generate
        tokens = []
        first_token_time = None
        async for token in response_agent.generate(
            question=question,
            kb_chunks=kb_chunks,
            question_type=classification["type"],
        ):
            if first_token_time is None:
                first_token_time = time.perf_counter()
            tokens.append(token)
        t3 = time.perf_counter()

        response = "".join(tokens)
        total_ms = (t3 - t0) * 1000
        classify_ms = (t1 - t0) * 1000
        retrieve_ms = (t2 - t1) * 1000
        ttft_ms = ((first_token_time or t3) - t0) * 1000
        generate_ms = (t3 - t2) * 1000

        # Analyze quality
        scores = analyze_response(response, classification["type"])

        # Type match
        type_match = classification["type"] == expected

        print(f"  Type: {classification['type']} "
              f"{'✅' if type_match else '⚠️ expected: ' + expected}")
        print(f"  Latency: {total_ms:.0f}ms total "
              f"(classify={classify_ms:.0f}ms, "
              f"retrieve={retrieve_ms:.0f}ms, "
              f"generate={generate_ms:.0f}ms, "
              f"TTFT={ttft_ms:.0f}ms)")
        print(f"  Quality: {scores['average']}/10")
        print(f"  Response: {response[:120]}…" if len(response) > 120
              else f"  Response: {response}")
        print()

        results.append({
            "id": qid,
            "question": question,
            "difficulty": difficulty,
            "expected_type": expected,
            "actual_type": classification["type"],
            "type_match": type_match,
            "filtered": False,
            "latency_total_ms": round(total_ms),
            "latency_classify_ms": round(classify_ms),
            "latency_retrieve_ms": round(retrieve_ms),
            "latency_generate_ms": round(generate_ms),
            "latency_ttft_ms": round(ttft_ms),
            "response_chars": len(response),
            "response": response,
            "scores": scores,
        })

    # --- Summary ---
    print()
    print("=" * 70)
    print("  SIMULATION RESULTS SUMMARY")
    print("=" * 70)

    processed = [r for r in results if not r["filtered"]]
    filtered = [r for r in results if r["filtered"]]

    # Latency stats
    latencies = [r["latency_total_ms"] for r in processed]
    ttfts = [r["latency_ttft_ms"] for r in processed]

    if latencies:
        print(f"\n  LATENCY (total pipeline):")
        print(f"    Average: {sum(latencies)/len(latencies):.0f}ms")
        print(f"    Min:     {min(latencies)}ms")
        print(f"    Max:     {max(latencies)}ms")
        print(f"    Median:  {sorted(latencies)[len(latencies)//2]}ms")
        print(f"\n  TIME TO FIRST TOKEN:")
        print(f"    Average: {sum(ttfts)/len(ttfts):.0f}ms")
        print(f"    Min:     {min(ttfts)}ms")
        print(f"    Max:     {max(ttfts)}ms")

    # Quality stats
    if processed:
        all_scores = {k: [] for k in processed[0]["scores"].keys()}
        for r in processed:
            for k, v in r["scores"].items():
                all_scores[k].append(v)

        print(f"\n  QUALITY SCORES (avg across {len(processed)} responses):")
        for criterion, vals in all_scores.items():
            avg = sum(vals) / len(vals)
            emoji = "✅" if avg >= 7 else "⚠️" if avg >= 5 else "❌"
            print(f"    {emoji} {criterion:20s}: {avg:.1f}/10")

    # Type accuracy
    type_matches = sum(1 for r in processed if r.get("type_match", False))
    print(f"\n  CLASSIFICATION ACCURACY: {type_matches}/{len(processed)} "
          f"({type_matches/len(processed)*100:.0f}%)")

    # Filter stats
    print(f"\n  QUESTION FILTER: {len(filtered)} rejected, "
          f"{len(processed)} accepted")

    # Save results
    output_path = os.path.join(
        os.path.dirname(__file__), "logs", "simulation_results.json"
    )
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n  Full results saved to: {output_path}")

    return results


if __name__ == "__main__":
    asyncio.run(run_simulation())
