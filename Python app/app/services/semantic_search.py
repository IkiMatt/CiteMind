"""
semantic_search.py — Embedding-based semantic search for CiteMind.

Searches by meaning rather than keyword matching.
Uses cosine similarity between query embedding and paper embeddings.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import requests

from app.model import EntryModel


@dataclass
class SearchResult:
    """A single semantic search result."""
    entry_id: int
    similarity: float  # 0-1 cosine similarity
    title: str = ""
    authors: str = ""
    year: str = ""


class SemanticSearch:
    """Search by meaning using embedding vectors."""

    def __init__(self, model: EntryModel, ollama_url: str = "", model_name: str = ""):
        self._model = model
        self._ollama_url = ollama_url
        self._model_name = model_name
        self._embedding_cache: dict[int, np.ndarray] | None = None

    def search(self, query: str, top_k: int = 20) -> list[SearchResult]:
        """
        Semantic search using embeddings.

        1. Generate embedding for query text via Ollama /api/embed
        2. Compute cosine similarity against all paper embeddings
        3. Return ranked results with similarity scores
        """
        if not query.strip():
            return []

        # Generate query embedding
        query_vec = self._embed_text(query)
        if query_vec is None:
            return []

        # Load all embeddings
        embeddings = self._load_embeddings()
        if not embeddings:
            return []

        # Compute similarities
        results: list[tuple[int, float]] = []
        for eid, vec in embeddings.items():
            sim = self._cosine_similarity(query_vec, vec)
            results.append((eid, sim))

        # Sort by similarity descending
        results.sort(key=lambda x: x[1], reverse=True)

        # Build SearchResult objects
        search_results: list[SearchResult] = []
        for eid, sim in results[:top_k]:
            entry = self._model.read_by_id(eid)
            search_results.append(SearchResult(
                entry_id=eid,
                similarity=sim,
                title=entry.get("title", ""),
                authors=entry.get("authors", ""),
                year=entry.get("year", ""),
            ))

        return search_results

    def hybrid_search(self, query: str, top_k: int = 20) -> list[SearchResult]:
        """
        Combine semantic + lexical search.
        - 60% weight: embedding cosine similarity
        - 40% weight: keyword match score
        """
        semantic = self.search(query, top_k=top_k * 2)
        if not semantic:
            return []

        # Simple keyword score: count query word occurrences in entry text
        query_words = set(query.lower().split())

        results: list[tuple[SearchResult, float]] = []
        for sr in semantic:
            entry = self._model.read_by_id(sr.entry_id)
            text = f"{entry.get('title', '')} {entry.get('authors', '')} {entry.get('notes', '')}".lower()
            keyword_score = sum(1 for w in query_words if w in text) / max(len(query_words), 1)

            combined = 0.6 * sr.similarity + 0.4 * keyword_score
            sr.similarity = combined
            results.append((sr, combined))

        results.sort(key=lambda x: x[1], reverse=True)
        return [sr for sr, _ in results[:top_k]]

    def find_similar(self, entry_id: int, top_k: int = 5) -> list[SearchResult]:
        """Find papers similar to a given entry."""
        embeddings = self._load_embeddings()
        if entry_id not in embeddings:
            return []

        target_vec = embeddings[entry_id]
        results: list[tuple[int, float]] = []

        for eid, vec in embeddings.items():
            if eid == entry_id:
                continue
            sim = self._cosine_similarity(target_vec, vec)
            results.append((eid, sim))

        results.sort(key=lambda x: x[1], reverse=True)

        search_results: list[SearchResult] = []
        for eid, sim in results[:top_k]:
            entry = self._model.read_by_id(eid)
            search_results.append(SearchResult(
                entry_id=eid,
                similarity=sim,
                title=entry.get("title", ""),
                authors=entry.get("authors", ""),
                year=entry.get("year", ""),
            ))

        return search_results

    # ── Internal ──────────────────────────────────────────────────────────

    def _embed_text(self, text: str) -> np.ndarray | None:
        """Generate embedding via Ollama /api/embed."""
        if not self._ollama_url or not self._model_name:
            return None

        try:
            url = self._ollama_url
            if not url.startswith("http"):
                url = "http://" + url

            resp = requests.post(
                f"{url}/api/embed",
                json={"model": self._model_name, "input": text},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()

            if "embeddings" in data and data["embeddings"]:
                return np.array(data["embeddings"][0], dtype=np.float32)
            elif "embedding" in data:
                return np.array(data["embedding"], dtype=np.float32)

        except Exception:
            return None
        return None

    def _load_embeddings(self) -> dict[int, np.ndarray]:
        """Load all embeddings from DB, caching in memory."""
        if self._embedding_cache is not None:
            return self._embedding_cache

        raw = self._model.get_all_embeddings()
        self._embedding_cache = {}
        for eid, blob, dims in raw:
            vec = np.frombuffer(blob, dtype=np.float32)
            self._embedding_cache[eid] = vec

        return self._embedding_cache

    def invalidate_cache(self):
        """Clear the in-memory embedding cache."""
        self._embedding_cache = None

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """Compute cosine similarity between two vectors."""
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))
