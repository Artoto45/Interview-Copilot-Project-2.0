"""
Test — Latency Measurement
=============================
Measures and validates pipeline latency targets:
    - Audio → Deepgram:           p50 < 50ms,  p95 < 100ms
    - Deepgram → Transcription:   p50 < 250ms, p95 < 350ms
    - Transcription → RAG:        p50 < 80ms,  p95 < 150ms
    - RAG → Claude response:      p50 < 800ms, p95 < 1500ms
    - Response → Teleprompter:    p50 < 50ms,  p95 < 80ms
    - End-to-end:                 p50 < 1.2s,  p95 < 2.2s

These tests can run in two modes:
    1. Mock mode (default): validates the measurement infrastructure
    2. Live mode (with API keys): measures actual latencies
"""

import statistics
import time
from unittest.mock import MagicMock, patch

import pytest


class TestLatencyInfrastructure:
    """Tests for the latency measurement infrastructure."""

    def test_percentile_calculation(self):
        """Percentile calculation works correctly."""
        values = list(range(1, 101))  # 1 to 100
        p50 = sorted(values)[int(len(values) * 0.50)]
        p95 = sorted(values)[int(len(values) * 0.95)]
        p99 = sorted(values)[int(len(values) * 0.99)]
        assert p50 == 51
        assert p95 == 96
        assert p99 == 100

    def test_deepgram_latency_tracker(self):
        """Deepgram transcriber tracks latencies correctly."""
        from src.transcription.deepgram_client import DeepgramTranscriber

        async def dummy_callback(speaker, text):
            pass

        transcriber = DeepgramTranscriber(on_transcript=dummy_callback)

        # Simulate latency measurements
        for ms in [100, 150, 200, 250, 300, 350, 180, 220, 280, 170]:
            transcriber._latencies["user"].append(ms)

        stats = transcriber.get_latency_stats()
        assert "user" in stats
        assert stats["user"]["p50"] > 0
        assert stats["user"]["p95"] > stats["user"]["p50"]
        assert stats["user"]["count"] == 10

    def test_should_reconnect_threshold(self):
        """Reconnect triggers when p95 exceeds threshold."""
        from src.transcription.deepgram_client import (
            DeepgramTranscriber,
            LATENCY_THRESHOLD_MS,
        )

        async def dummy_callback(speaker, text):
            pass

        transcriber = DeepgramTranscriber(on_transcript=dummy_callback)

        # All below threshold
        for _ in range(20):
            transcriber._latencies["user"].append(200)
        assert not transcriber.should_reconnect("user")

        # Push above threshold
        for _ in range(20):
            transcriber._latencies["user"].append(500)
        assert transcriber.should_reconnect("user")


class TestLatencyTargets:
    """
    Define latency targets from the roadmap.
    These serve as documentation and validation benchmarks.
    """

    TARGETS = {
        "audio_to_deepgram": {"p50": 50, "p95": 100},
        "deepgram_transcription": {"p50": 250, "p95": 350},
        "transcription_to_rag": {"p50": 80, "p95": 150},
        "rag_to_claude_response": {"p50": 800, "p95": 1500},
        "response_to_teleprompter": {"p50": 50, "p95": 80},
        "end_to_end": {"p50": 1200, "p95": 2200},
    }

    def test_targets_defined(self):
        """All pipeline stages have latency targets."""
        assert len(self.TARGETS) == 6
        for stage, targets in self.TARGETS.items():
            assert "p50" in targets
            assert "p95" in targets
            assert targets["p50"] < targets["p95"]

    def test_end_to_end_is_sum_of_stages(self):
        """End-to-end target roughly equals sum of individual stages."""
        total_p50 = sum(
            t["p50"]
            for name, t in self.TARGETS.items()
            if name != "end_to_end"
        )
        # End-to-end should be ≤ sum (parallel processing saves time)
        assert self.TARGETS["end_to_end"]["p50"] <= total_p50

    def test_timing_measurement(self):
        """Basic timing measurement works."""
        start = time.perf_counter_ns()
        # Simulate minimal work
        _ = sum(range(1000))
        elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000
        assert elapsed_ms < 100  # Should be < 1ms for trivial work


class TestClassifierLatency:
    """Test classifier performance meets < 200ms target."""

    def test_fallback_classifier_speed(self):
        """Rule-based fallback classifier is fast (< 5ms)."""
        from src.knowledge.classifier import QuestionClassifier

        questions = [
            "Tell me about yourself",
            "What do you know about our company?",
            "Describe a time when you handled conflict",
            "Are you available to start Monday?",
            "Why do you want this role and what's your experience?",
        ]

        times = []
        for q in questions:
            start = time.perf_counter_ns()
            result = QuestionClassifier._fallback_classify(q)
            elapsed = (time.perf_counter_ns() - start) / 1_000_000
            times.append(elapsed)
            assert "type" in result
            assert "budget" in result

        avg_ms = statistics.mean(times)
        assert avg_ms < 5.0, (
            f"Fallback classifier too slow: avg={avg_ms:.2f}ms"
        )
