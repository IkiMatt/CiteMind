"""
graph_builder.py — Construct a GraphModel from database entries and keywords.

Creates document and keyword nodes.
Builds edges: contains_keyword, keyword_overlap (Jaccard).
Phase 2: adds semantic_similarity edges from embedding vectors.
"""
from __future__ import annotations

import re
from collections import Counter

from app.graph.graph_model import (
    GraphModel,
    NODE_DOCUMENT, NODE_KEYWORD,
    EDGE_CONTAINS_KW, EDGE_KEYWORD_OVERLAP,
    EDGE_SEMANTIC_SIM,
)
from app.graph.keyword_extractor import (
    extract_keywords_tfidf,
    filter_academic_keywords,
    filter_keywords_by_document_frequency,
)





class GraphBuilder:
    """
    Builds a ``GraphModel`` from a list of entry dicts.

    Parameters
    ----------
    entries : list[dict]
        Full entry records from the database.
    keywords : dict[int, list[str]] | None
        Pre-computed keywords.  If None, TF-IDF extraction runs automatically.
    keyword_overlap_threshold : float
        Minimum Jaccard similarity to create a keyword_overlap edge.
    """

    def __init__(
        self,
        entries: list[dict],
        keywords: dict[int, list[str]] | None = None,
        keyword_overlap_threshold: float = 0.35,
        keyword_limit: int = 50,
    ):
        self._entries = entries
        self._keywords = keywords
        self._threshold = max(0.0, min(1.0, keyword_overlap_threshold))
        self._keyword_limit = max(1, int(keyword_limit))

    def build(self) -> GraphModel:
        """Execute the full build pipeline and return a populated GraphModel."""
        gm = GraphModel()

        # 1. Prefer explicit per-entry AI topics already stored in the record.
        if self._keywords is None:
            explicit_keywords: dict[int, list[str]] = {}
            for entry in self._entries:
                eid = entry.get("id")
                if eid is None:
                    continue
                stored = entry.get("ai_topics") or []
                if isinstance(stored, str):
                    try:
                        import json
                        stored = json.loads(stored)
                    except Exception:
                        stored = []
                if isinstance(stored, (list, tuple)) and stored:
                    cleaned: list[str] = []
                    seen: set[str] = set()
                    for item in stored:
                        text = str(item).strip()
                        if not text:
                            continue
                        norm = text.lower()
                        if norm in seen:
                            continue
                        seen.add(norm)
                        cleaned.append(text)
                    explicit_keywords[int(eid)] = cleaned[:self._keyword_limit]
            if explicit_keywords:
                self._keywords = explicit_keywords
            else:
                self._keywords = extract_keywords_tfidf(self._entries, top_k=self._keyword_limit)
        else:
            self._keywords = {
                eid: filter_academic_keywords(list(kws)[:self._keyword_limit])
                for eid, kws in self._keywords.items()
            }

        self._keywords = filter_keywords_by_document_frequency(self._keywords, max_doc_fraction=0.5)

        # 2. Add document nodes
        for entry in self._entries:
            eid = entry.get("id")
            if eid is None:
                continue
            doc_id = f"doc_{eid}"
            authors = entry.get("authors", "").strip()
            title = entry.get("title", "").strip()
            label = authors or title or "(untitled)"
            year = entry.get("year", "")
            if year:
                label += f" ({year})"
            gm.add_node(
                doc_id,
                node_type=NODE_DOCUMENT,
                label=label,
                title=entry.get("title", ""),
                authors=entry.get("authors", ""),
                year=str(year),
                entry_type=entry.get("entry_type", "bibliography"),
                entry_id=eid,
            )

        # 3. Add keyword nodes + contains_keyword edges.
        # The limit is GLOBAL: it caps the total number of distinct keyword nodes in the graph
        # so memory stays controlled even with many documents.
        kw_nodes_added: set[str] = set()
        doc_kw_sets: dict[str, set[str]] = {}  # doc_id → set of kw_node_ids
        accepted_keywords: list[str] = []
        accepted_lookup: set[str] = set()

        for eid, kws in self._keywords.items():
            doc_id = f"doc_{eid}"
            if doc_id not in gm._g:
                continue
            kw_set: set[str] = set()
            for kw in kws:
                if not kw or not str(kw).strip():
                    continue
                key = str(kw).strip()
                low = key.lower()
                if low in accepted_lookup:
                    # already accepted globally, keep it for this doc
                    pass
                elif len(accepted_keywords) >= self._keyword_limit:
                    continue
                else:
                    accepted_keywords.append(key)
                    accepted_lookup.add(low)

                kw_id = f"kw_{key.lower().replace(' ', '_')}"
                if kw_id not in kw_nodes_added and low in accepted_lookup:
                    gm.add_node(kw_id, node_type=NODE_KEYWORD, label=key)
                    kw_nodes_added.add(kw_id)
                if low in accepted_lookup:
                    gm.add_edge(doc_id, kw_id, edge_type=EDGE_CONTAINS_KW, weight=1.0)
                    kw_set.add(kw_id)
            if kw_set:
                doc_kw_sets[doc_id] = kw_set

        # 4. Add keyword_overlap edges only when documents share at least one keyword,
        #    using a keyword→documents index to keep the computation lightweight and avoid
        #    excessive "spine" links caused by tiny threshold values.
        keyword_to_docs: dict[str, set[str]] = {}
        for doc_id, kw_set in doc_kw_sets.items():
            for kw_id in kw_set:
                keyword_to_docs.setdefault(kw_id, set()).add(doc_id)

        seen_pairs: set[tuple[str, str]] = set()
        for kw_id, doc_ids in keyword_to_docs.items():
            doc_list = sorted(doc_ids)
            for i in range(len(doc_list)):
                for j in range(i + 1, len(doc_list)):
                    a, b = doc_list[i], doc_list[j]
                    pair = (a, b) if a < b else (b, a)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    set_a = doc_kw_sets[a]
                    set_b = doc_kw_sets[b]
                    if not set_a or not set_b:
                        continue
                    intersection = len(set_a & set_b)
                    union = len(set_a | set_b)
                    if union == 0:
                        continue
                    jaccard = intersection / union
                    shared_ratio = intersection / min(len(set_a), len(set_b))
                    if jaccard >= self._threshold or (intersection >= 2 and shared_ratio >= 0.5):
                        gm.add_edge(
                            a, b,
                            edge_type=EDGE_KEYWORD_OVERLAP,
                            weight=round(max(jaccard, shared_ratio), 3),
                        )

        # 5. Detect clusters
        gm.detect_clusters()

        return gm

    @staticmethod
    def add_semantic_edges(
        gm: GraphModel,
        embeddings: dict[int, list[float]],
        threshold: float = 0.65,
    ) -> None:
        """
        Add semantic_similarity edges from precomputed embedding vectors.

        Parameters
        ----------
        gm : GraphModel
            The graph to augment in-place.
        embeddings : dict[int, list[float]]
            Mapping entry_id → embedding vector.
        threshold : float
            Minimum cosine similarity to create an edge.
        """
        import numpy as np

        ids = list(embeddings.keys())
        if len(ids) < 2:
            return

        vecs = np.array([embeddings[eid] for eid in ids])
        # Normalize
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms

        # Cosine similarity matrix
        sim_matrix = vecs @ vecs.T

        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                sim = float(sim_matrix[i, j])
                if sim >= threshold:
                    doc_a = f"doc_{ids[i]}"
                    doc_b = f"doc_{ids[j]}"
                    if doc_a in gm._g and doc_b in gm._g:
                        gm.add_edge(
                            doc_a, doc_b,
                            edge_type=EDGE_SEMANTIC_SIM,
                            weight=round(sim, 3),
                        )
