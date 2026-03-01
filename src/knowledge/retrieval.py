"""
Knowledge Base — RAG Retrieval
================================
Semantic search over the ChromaDB knowledge base.

Retrieval strategy:
    - Query embedding via OpenAI text-embedding-3-small
    - ChromaDB similarity search (cosine distance)
    - Top-k=3 by default (adjustable per question type)
    - Optional metadata filtering by category
    - Context formatting for injection into Claude's user message

Best Practice (from roadmap): KB chunks go in the USER message,
NOT the system message — Claude Opus 4.6 Extended Thinking reasons
better over factual context when it appears as part of the question.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI
import chromadb

load_dotenv()
logger = logging.getLogger("knowledge.retrieval")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_TOP_K = 3
CHROMA_DIR = Path(__file__).resolve().parent.parent.parent / "chroma_data"

# Top-k by question type (more complex → more context)
TOP_K_BY_TYPE = {
    "simple": 2,
    "personal": 3,
    "company": 3,
    "hybrid": 5,
    "situational": 4,
}


class KnowledgeRetriever:
    """
    Retrieves relevant KB chunks for a given interview question
    using semantic similarity search.

    Usage::

        retriever = KnowledgeRetriever()
        chunks = await retriever.retrieve(
            query="Tell me about yourself",
            question_type="personal"
        )
    """

    def __init__(
        self,
        chroma_dir: Optional[Path] = None,
        collection_name: str = "interview_kb",
    ):
        self.chroma_dir = chroma_dir or CHROMA_DIR

        # OpenAI for query embeddings
        self.openai_client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
        )

        # ChromaDB
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.chroma_dir),
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def retrieve(
        self,
        query: str,
        question_type: str = "personal",
        top_k: Optional[int] = None,
        category_filter: Optional[str] = None,
    ) -> list[str]:
        """
        Retrieve the most relevant KB chunks for a question.

        Args:
            query: The interview question text.
            question_type: Classification result (personal/company/hybrid/simple).
            top_k: Number of chunks to retrieve (defaults based on question_type).
            category_filter: Optional — restrict to 'personal' or 'company' only.

        Returns:
            List of relevant text chunks, ordered by relevance.
        """
        if self.collection.count() == 0:
            logger.warning(
                "KB is empty — run ingestion first. "
                "Place documents in kb/personal/ or kb/company/."
            )
            return []

        # Determine top_k
        k = top_k or TOP_K_BY_TYPE.get(question_type, DEFAULT_TOP_K)

        # Generate query embedding
        query_embedding = self._embed_query(query)

        # Build where filter
        where_filter = None
        if category_filter:
            where_filter = {"category": category_filter}
        elif question_type == "personal":
            # Prefer personal KB for personal questions
            where_filter = {"category": "personal"}
        elif question_type == "company":
            where_filter = {"category": "company"}
        # hybrid/simple → search all

        # Query ChromaDB
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception:
            # If filtered query returns 0 results, retry without filter
            logger.info(
                f"Filtered query returned no results for "
                f"category={category_filter or question_type}, "
                f"retrying without filter…"
            )
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )

        # Extract documents
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        if not documents:
            logger.warning(f"No KB results for query: {query[:60]}…")
            return []

        logger.info(
            f"Retrieved {len(documents)} chunks "
            f"(type={question_type}, distances={[f'{d:.3f}' for d in distances]})"
        )

        return documents

    async def retrieve_with_metadata(
        self,
        query: str,
        question_type: str = "personal",
        top_k: Optional[int] = None,
    ) -> list[dict]:
        """
        Like retrieve(), but returns chunks with full metadata.

        Returns:
            List of dicts with 'text', 'category', 'topic', 'distance'.
        """
        if self.collection.count() == 0:
            return []

        k = top_k or TOP_K_BY_TYPE.get(question_type, DEFAULT_TOP_K)
        query_embedding = self._embed_query(query)

        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )

        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]

        return [
            {
                "text": doc,
                "category": meta.get("category", "unknown"),
                "topic": meta.get("topic", "unknown"),
                "source": meta.get("source", "unknown"),
                "distance": dist,
            }
            for doc, meta, dist in zip(documents, metadatas, distances)
        ]

    # ------------------------------------------------------------------
    # Formatting for Claude Prompt
    # ------------------------------------------------------------------
    @staticmethod
    def format_for_prompt(chunks: list[str]) -> str:
        """
        Format retrieved KB chunks for injection into the Claude
        user message.

        Best Practice: KB chunks go in the USER message, not the
        system message, for optimal Extended Thinking performance.
        """
        if not chunks:
            return "[No relevant knowledge base context available]"

        formatted = []
        for i, chunk in enumerate(chunks, 1):
            formatted.append(f"[KB Source {i}]:\n{chunk}")

        return "\n\n".join(formatted)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def _embed_query(self, text: str) -> list[float]:
        """Generate embedding for a single query text."""
        response = self.openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=[text],
        )
        return response.data[0].embedding
