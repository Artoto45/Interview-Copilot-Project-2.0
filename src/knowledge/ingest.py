"""
Knowledge Base — Document Ingestion Pipeline
===============================================
Loads documents from ``kb/personal/`` and ``kb/company/``, splits them
into semantic chunks, generates embeddings via OpenAI
``text-embedding-3-small``, and stores them in a ChromaDB collection
with metadata (category, topic).

Chunk strategy:
    - chunk_size=300 chars, overlap=50 chars
    - Separators: paragraph → line → sentence
    - Metadata: category (personal/company), topic, source file
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from langchain_text_splitters import RecursiveCharacterTextSplitter
from openai import OpenAI
import chromadb

load_dotenv()
logger = logging.getLogger("knowledge.ingest")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
EMBEDDING_MODEL = "text-embedding-3-small"

KB_DIR = Path(__file__).resolve().parent.parent.parent / "kb"
CHROMA_DIR = Path(__file__).resolve().parent.parent.parent / "chroma_data"

SUPPORTED_EXTENSIONS = {".txt", ".md"}


class KnowledgeIngestor:
    """
    Ingests documents from the knowledge base directories, creates
    embeddings, and stores them in ChromaDB.

    Usage::

        ingestor = KnowledgeIngestor()
        stats = ingestor.ingest_all()
        print(f"Ingested {stats['total_chunks']} chunks")
    """

    def __init__(
        self,
        kb_dir: Optional[Path] = None,
        chroma_dir: Optional[Path] = None,
        collection_name: str = "interview_kb",
    ):
        self.kb_dir = kb_dir or KB_DIR
        self.chroma_dir = chroma_dir or CHROMA_DIR
        self.collection_name = collection_name

        # Text splitter
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            separators=["\n\n", "\n", ". ", ", ", " "],
        )

        # OpenAI client for embeddings
        self.openai_client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY", ""),
        )

        # ChromaDB persistent client
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.chroma_dir),
        )
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest_all(self) -> dict:
        """
        Ingest all documents from kb/personal/ and kb/company/.

        Returns a summary dict with counts.
        """
        stats = {
            "personal_files": 0,
            "company_files": 0,
            "total_chunks": 0,
            "errors": [],
        }

        # Ingest personal KB
        personal_dir = self.kb_dir / "personal"
        if personal_dir.exists():
            for filepath in personal_dir.iterdir():
                if filepath.suffix.lower() in SUPPORTED_EXTENSIONS:
                    try:
                        n = self.ingest_file(
                            filepath, category="personal"
                        )
                        stats["personal_files"] += 1
                        stats["total_chunks"] += n
                    except Exception as e:
                        stats["errors"].append(
                            f"{filepath.name}: {e}"
                        )
                        logger.error(
                            f"Error ingesting {filepath}: {e}",
                            exc_info=True,
                        )

        # Ingest company KB
        company_dir = self.kb_dir / "company"
        if company_dir.exists():
            for filepath in company_dir.iterdir():
                if filepath.suffix.lower() in SUPPORTED_EXTENSIONS:
                    try:
                        n = self.ingest_file(
                            filepath, category="company"
                        )
                        stats["company_files"] += 1
                        stats["total_chunks"] += n
                    except Exception as e:
                        stats["errors"].append(
                            f"{filepath.name}: {e}"
                        )
                        logger.error(
                            f"Error ingesting {filepath}: {e}",
                            exc_info=True,
                        )

        logger.info(
            f"Ingestion complete: "
            f"{stats['personal_files']} personal files, "
            f"{stats['company_files']} company files, "
            f"{stats['total_chunks']} total chunks"
        )
        return stats

    def ingest_file(
        self,
        filepath: Path,
        category: str,
        topic: Optional[str] = None,
    ) -> int:
        """
        Ingest a single file into the KB.

        Args:
            filepath: Path to the document file.
            category: 'personal' or 'company'.
            topic: Optional topic tag (auto-derived from filename if None).

        Returns:
            Number of chunks ingested.
        """
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        text = filepath.read_text(encoding="utf-8")
        if not text.strip():
            logger.warning(f"Empty file skipped: {filepath}")
            return 0

        # Auto-derive topic from filename
        if topic is None:
            topic = filepath.stem.replace("_", " ").replace("-", " ")

        return self.ingest_text(
            text=text,
            category=category,
            topic=topic,
            source=filepath.name,
        )

    def ingest_text(
        self,
        text: str,
        category: str,
        topic: str,
        source: str = "manual",
    ) -> int:
        """
        Ingest raw text into the KB.

        Splits → embeds → stores in ChromaDB.
        """
        # 1. Split into chunks and filter invalid ones
        raw_chunks = self.splitter.split_text(text)
        chunks = [
            c for c in raw_chunks 
            if len(c.strip()) >= 20 and len(c.split()) >= 5
        ]
        
        if not chunks:
            logger.warning(f"No valid chunks generated from '{source}'")
            return 0

        logger.info(
            f"Ingesting '{source}': {len(chunks)} valid chunks "
            f"(category={category}, topic={topic})"
        )

        # deduplication: delete old chunks for this source
        try:
            self.collection.delete(where={"source": source})
            logger.info(f"  ✓ Deduplication: Deleted old chunks for '{source}'")
        except Exception:
            pass

        # 2. Generate embeddings
        embeddings = self._embed(chunks)

        # 3. Create IDs and metadata
        ids = [
            f"{category}_{topic.replace(' ', '_')}_{source}_{i}"
            for i in range(len(chunks))
        ]
        metadatas = [
            {
                "category": category,
                "topic": topic,
                "source": source,
                "chunk_index": i,
            }
            for i in range(len(chunks))
        ]

        # 4. Upsert into ChromaDB
        self.collection.upsert(
            ids=ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        logger.info(
            f"  ✓ Stored {len(chunks)} chunks in collection "
            f"'{self.collection_name}'"
        )
        return len(chunks)

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    def _embed(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for a list of texts using OpenAI
        text-embedding-3-small.
        """
        response = self.openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def get_stats(self) -> dict:
        """Get current collection statistics."""
        count = self.collection.count()
        return {
            "collection": self.collection_name,
            "total_chunks": count,
            "chroma_dir": str(self.chroma_dir),
        }

    def clear(self):
        """Delete all documents from the collection."""
        self.chroma_client.delete_collection(self.collection_name)
        self.collection = self.chroma_client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"Cleared collection '{self.collection_name}'")
