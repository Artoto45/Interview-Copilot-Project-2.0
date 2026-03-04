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
import re
from collections import defaultdict
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

MAX_CHUNKS_PER_SOURCE = 2
MMR_LAMBDA = float(os.getenv("RAG_MMR_LAMBDA", "0.72"))
MMR_CANDIDATE_MULTIPLIER = max(
    2,
    int(os.getenv("RAG_MMR_CANDIDATE_MULTIPLIER", "4")),
)
SEMANTIC_DEDUP_THRESHOLD = float(
    os.getenv("RAG_SEMANTIC_DEDUP_THRESHOLD", "0.93")
)


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
        self._doc_embedding_cache: dict[str, list[float]] = {}

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

        # Query ChromaDB (wider candidate pool for MMR reranking)
        candidate_k = max(k, min(48, (k * MMR_CANDIDATE_MULTIPLIER) + 2))
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=candidate_k,
                where=where_filter,
                include=["documents", "metadatas", "distances", "embeddings"],
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
                n_results=candidate_k,
                include=["documents", "metadatas", "distances", "embeddings"],
            )

        # Extract documents
        documents = results.get("documents", [[]])[0]
        distances = results.get("distances", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        doc_embeddings = results.get("embeddings", [[]])[0]

        if not documents:
            logger.warning(f"No KB results for query: {query[:60]}…")
            return []

        if doc_embeddings is None or len(doc_embeddings) != len(documents):
            doc_embeddings = self._get_or_embed_documents(documents)

        documents = self._postprocess_documents(
            documents=documents,
            metadatas=metadatas,
            distances=distances,
            max_results=k,
            max_per_source=MAX_CHUNKS_PER_SOURCE,
            query_embedding=query_embedding,
            doc_embeddings=doc_embeddings,
            mmr_lambda=MMR_LAMBDA,
            semantic_dedup_threshold=SEMANTIC_DEDUP_THRESHOLD,
        )

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

    async def retrieve_with_evidence(
        self,
        query: str,
        question_type: str = "personal",
        top_k: Optional[int] = None,
        category_filter: Optional[str] = None,
    ) -> dict:
        """
        Retrieve chunks and attach lightweight evidence metadata for logging.

        Returns:
            Dict with:
                - chunks: list[str]
                - evidence: list[dict]
        """
        chunks = await self.retrieve(
            query=query,
            question_type=question_type,
            top_k=top_k,
            category_filter=category_filter,
        )
        if not chunks:
            return {"chunks": [], "evidence": []}

        metadata_rows = await self.retrieve_with_metadata(
            query=query,
            question_type=question_type,
            top_k=max(len(chunks) * 3, top_k or len(chunks)),
        )
        evidence = self._build_evidence_for_chunks(chunks, metadata_rows)
        return {"chunks": chunks, "evidence": evidence}

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

    @classmethod
    def _build_evidence_for_chunks(
        cls,
        chunks: list[str],
        metadata_rows: list[dict],
        max_snippet_chars: int = 160,
    ) -> list[dict]:
        """
        Align selected chunks with metadata rows and return log-safe evidence.
        """
        if not chunks:
            return []

        by_norm: dict[str, dict] = {}
        for row in metadata_rows or []:
            text = str(row.get("text", "") or "")
            norm = cls._normalize_doc(text)[:260]
            if norm and norm not in by_norm:
                by_norm[norm] = row

        evidence: list[dict] = []
        for idx, chunk in enumerate(chunks, start=1):
            norm = cls._normalize_doc(chunk)[:260]
            row = by_norm.get(norm)

            # Fallback approximate match if exact-normalized text wasn't found.
            if row is None:
                for candidate in metadata_rows or []:
                    candidate_text = str(candidate.get("text", "") or "")
                    c_norm = cls._normalize_doc(candidate_text)
                    if norm and c_norm and (norm in c_norm or c_norm in norm):
                        row = candidate
                        break

            evidence.append({
                "rank": idx,
                "source": (row or {}).get("source", "unknown"),
                "category": (row or {}).get("category", "unknown"),
                "topic": (row or {}).get("topic", "unknown"),
                "distance": float((row or {}).get("distance", -1.0)),
                "snippet": chunk[:max_snippet_chars].replace("\n", " ").strip(),
            })

        return evidence

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

    def _get_or_embed_documents(self, documents: list[str]) -> list[list[float]]:
        """
        Return embeddings for candidate documents using a tiny in-memory cache
        keyed by normalized chunk content.
        """
        if not documents:
            return []

        keys = [self._normalize_doc(doc)[:800] for doc in documents]
        missing_positions = [
            idx for idx, key in enumerate(keys)
            if key not in self._doc_embedding_cache
        ]

        if missing_positions:
            missing_docs = [documents[idx] for idx in missing_positions]
            response = self.openai_client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=missing_docs,
            )
            for pos, emb in zip(missing_positions, response.data):
                self._doc_embedding_cache[keys[pos]] = emb.embedding

        return [self._doc_embedding_cache[key] for key in keys]

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if a is None or b is None or len(a) == 0 or len(b) == 0 or len(a) != len(b):
            return 0.0
        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for x, y in zip(a, b):
            fx = float(x)
            fy = float(y)
            dot += fx * fy
            norm_a += fx * fx
            norm_b += fy * fy
        if norm_a <= 0.0 or norm_b <= 0.0:
            return 0.0
        return dot / ((norm_a ** 0.5) * (norm_b ** 0.5))

    @staticmethod
    def _normalize_doc(text: str) -> str:
        lowered = (text or "").strip().lower()
        lowered = re.sub(r"\s+", " ", lowered)
        return lowered

    @classmethod
    def _postprocess_documents(
        cls,
        documents: list[str],
        metadatas: list[dict],
        distances: list[float],
        max_results: int,
        max_per_source: int = MAX_CHUNKS_PER_SOURCE,
        query_embedding: Optional[list[float]] = None,
        doc_embeddings: Optional[list[list[float]]] = None,
        mmr_lambda: float = MMR_LAMBDA,
        semantic_dedup_threshold: float = SEMANTIC_DEDUP_THRESHOLD,
    ) -> list[str]:
        """
        Remove duplicate/near-duplicate chunks, apply MMR reranking,
        and reduce source concentration.
        """
        if not documents:
            return []

        rows = []
        for idx, doc in enumerate(documents):
            meta = metadatas[idx] if idx < len(metadatas) else {}
            distance = distances[idx] if idx < len(distances) else 999.0
            emb = (
                doc_embeddings[idx]
                if doc_embeddings is not None and idx < len(doc_embeddings)
                else None
            )
            rows.append((doc, meta or {}, float(distance), emb))

        # Stage 1: exact duplicate cleanup.
        dedup_rows = []
        seen_norm = set()
        for doc, meta, distance, emb in rows:
            norm = cls._normalize_doc(doc)
            if len(norm) < 12:
                continue
            sig = norm[:260]
            if sig in seen_norm:
                continue
            seen_norm.add(sig)
            dedup_rows.append((doc, meta, distance, emb))

        # Stage 2: semantic dedup if embeddings are available.
        sem_rows = []
        sem_embs: list[list[float]] = []
        for doc, meta, distance, emb in dedup_rows:
            if emb is None:
                sem_rows.append((doc, meta, distance, emb))
                continue
            too_similar = False
            for selected_emb in sem_embs:
                if cls._cosine_similarity(emb, selected_emb) >= semantic_dedup_threshold:
                    too_similar = True
                    break
            if too_similar:
                continue
            sem_rows.append((doc, meta, distance, emb))
            sem_embs.append(emb)

        selected: list[str] = []
        source_counts = defaultdict(int)

        # Stage 3: MMR selection when query+doc embeddings are available.
        use_mmr = (
            query_embedding is not None
            and len(query_embedding) > 0
            and len(sem_rows) > 0
            and all(row[3] is not None for row in sem_rows)
        )

        ranked_rows = sem_rows
        if use_mmr:
            q_emb = query_embedding if query_embedding is not None else []
            available = list(range(len(sem_rows)))
            chosen: list[int] = []
            mmr_lambda = max(0.10, min(0.95, float(mmr_lambda)))

            while available and len(chosen) < len(sem_rows):
                best_idx = None
                best_score = -999.0
                for idx in available:
                    _doc, _meta, _dist, emb = sem_rows[idx]
                    emb = emb if emb is not None else []
                    rel = cls._cosine_similarity(q_emb, emb)
                    if chosen:
                        max_div = max(
                            cls._cosine_similarity(
                                emb,
                                sem_rows[other_idx][3]
                                if sem_rows[other_idx][3] is not None
                                else [],
                            )
                            for other_idx in chosen
                        )
                    else:
                        max_div = 0.0
                    score = (mmr_lambda * rel) - ((1.0 - mmr_lambda) * max_div)
                    # Small deterministic tie-breaker by distance.
                    score -= float(sem_rows[idx][2]) * 0.01
                    if score > best_score:
                        best_score = score
                        best_idx = idx
                if best_idx is None:
                    break
                chosen.append(best_idx)
                available.remove(best_idx)

            ranked_rows = [sem_rows[idx] for idx in chosen]

        # Pass 1: respect source cap for diversity.
        for doc, meta, _distance, _emb in ranked_rows:
            if len(selected) >= max_results:
                break
            source = str(meta.get("source", "unknown")).lower()
            if source_counts[source] >= max_per_source:
                continue
            selected.append(doc)
            source_counts[source] += 1

        # Pass 2: backfill if we filtered too aggressively.
        if len(selected) < max_results:
            selected_norm = {cls._normalize_doc(doc)[:260] for doc in selected}
            for doc, _meta, _distance, _emb in ranked_rows:
                if len(selected) >= max_results:
                    break
                norm = cls._normalize_doc(doc)
                if len(norm) < 12:
                    continue
                sig = norm[:260]
                if sig in selected_norm:
                    continue
                selected.append(doc)
                selected_norm.add(sig)

        return selected
