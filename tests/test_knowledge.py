"""
Test — Knowledge Module
=========================
Tests for KB ingestion, retrieval, and question classifier.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from src.knowledge.classifier import QuestionClassifier, BUDGET_MAP


class TestQuestionClassifier:
    """Tests for the rule-based fallback classifier."""

    def test_classify_personal(self):
        """Detects personal questions."""
        result = QuestionClassifier._fallback_classify(
            "Tell me about yourself"
        )
        assert result["type"] == "personal"
        assert result["budget"] == BUDGET_MAP["personal"]

    def test_classify_company(self):
        """Detects company questions."""
        result = QuestionClassifier._fallback_classify(
            "What do you know about our company?"
        )
        assert result["type"] == "company"
        assert result["budget"] == BUDGET_MAP["company"]

    def test_classify_situational(self):
        """Detects situational/behavioral questions."""
        result = QuestionClassifier._fallback_classify(
            "Describe a time when you had to handle a difficult colleague"
        )
        assert result["type"] == "situational"
        assert result["budget"] == BUDGET_MAP["situational"]

    def test_classify_situational_hypothetical(self):
        """Detects hypothetical questions."""
        result = QuestionClassifier._fallback_classify(
            "What would you do if a project deadline was suddenly moved up?"
        )
        assert result["type"] == "situational"

    def test_classify_simple_short(self):
        """Short questions classified as simple."""
        result = QuestionClassifier._fallback_classify(
            "When can you start?"
        )
        assert result["type"] == "simple"
        assert result["budget"] == BUDGET_MAP["simple"]

    def test_classify_compound_hybrid(self):
        """Multi-part questions detected as hybrid."""
        result = QuestionClassifier._fallback_classify(
            "Why do you want to work here and what makes you a good fit? "
            "Also, how does your experience relate?"
        )
        assert result["type"] == "hybrid"
        assert result["compound"] is True
        assert result["budget"] == BUDGET_MAP["hybrid"]

    def test_classify_strengths(self):
        """Strengths question is personal."""
        result = QuestionClassifier._fallback_classify(
            "What are your greatest strengths?"
        )
        assert result["type"] == "personal"

    def test_budget_map_completeness(self):
        """All question types have a budget assigned."""
        expected_types = ["simple", "personal", "company", "hybrid", "situational"]
        for q_type in expected_types:
            assert q_type in BUDGET_MAP
            assert isinstance(BUDGET_MAP[q_type], int)
            assert BUDGET_MAP[q_type] > 0

    def test_budget_ordering(self):
        """Budget increases with question complexity."""
        assert BUDGET_MAP["simple"] <= BUDGET_MAP["personal"]
        assert BUDGET_MAP["personal"] < BUDGET_MAP["company"]
        assert BUDGET_MAP["company"] <= BUDGET_MAP["hybrid"]
        assert BUDGET_MAP["hybrid"] < BUDGET_MAP["situational"]


class TestKnowledgeIngestor:
    """Tests for KnowledgeIngestor (mocked OpenAI/ChromaDB)."""

    @patch("src.knowledge.ingest.OpenAI")
    @patch("src.knowledge.ingest.chromadb.PersistentClient")
    def test_ingest_text_splits_and_stores(self, mock_chroma, mock_openai):
        """Ingesting text splits it into chunks and stores embeddings."""
        from src.knowledge.ingest import KnowledgeIngestor

        # Mock embedding response
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1] * 1536
        mock_openai_instance = mock_openai.return_value
        mock_openai_instance.embeddings.create.return_value = MagicMock(
            data=[mock_embedding, mock_embedding]
        )

        # Mock ChromaDB
        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_chroma.return_value.get_or_create_collection.return_value = (
            mock_collection
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            ingestor = KnowledgeIngestor(
                kb_dir=Path(tmpdir),
                chroma_dir=Path(tmpdir) / "chroma",
            )

            text = (
                "I have 5 years of experience in software engineering. "
                "I worked at Google on search infrastructure. "
                "My key achievement was reducing latency by 40%."
            )
            n = ingestor.ingest_text(
                text=text,
                category="personal",
                topic="experience",
            )

            assert n > 0
            mock_collection.upsert.assert_called_once()


class TestKnowledgeRetriever:
    """Tests for KnowledgeRetriever."""

    def test_format_for_prompt_with_chunks(self):
        """Formats chunks for Claude prompt injection."""
        from src.knowledge.retrieval import KnowledgeRetriever

        chunks = ["I have 5 years of experience.", "I worked at Google."]
        formatted = KnowledgeRetriever.format_for_prompt(chunks)
        assert "[KB Source 1]" in formatted
        assert "[KB Source 2]" in formatted
        assert "5 years" in formatted

    def test_format_for_prompt_empty(self):
        """Returns placeholder when no chunks available."""
        from src.knowledge.retrieval import KnowledgeRetriever

        formatted = KnowledgeRetriever.format_for_prompt([])
        assert "No relevant" in formatted

    def test_top_k_by_type(self):
        """Different question types get different top-k values."""
        from src.knowledge.retrieval import TOP_K_BY_TYPE

        assert TOP_K_BY_TYPE["simple"] < TOP_K_BY_TYPE["hybrid"]
        assert TOP_K_BY_TYPE["personal"] <= TOP_K_BY_TYPE["company"]
