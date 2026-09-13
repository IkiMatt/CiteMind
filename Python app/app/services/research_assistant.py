"""
research_assistant.py — Higher-level research analysis for CiteMind.

Built on top of clustering + metrics to provide:
  - Thesis relevance scoring
  - Research gap detection
  - Topic timeline analysis
  - Paper recommendations
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field

import numpy as np

from app.model import EntryModel


@dataclass
class ResearchGap:
    """A detected gap or opportunity in the research landscape."""
    type: str          # "sparse_topic", "missing_bridge", "stale_topic"
    message: str
    cluster_label: str = ""
    cluster_ids: list[int] = field(default_factory=list)
    severity: str = "info"  # "info", "warning", "opportunity"


@dataclass
class TopicTimeline:
    """Paper counts per year for a topic cluster."""
    cluster_id: int
    cluster_label: str
    years: list[tuple[int, int]]  # [(year, count), ...]


class ResearchAssistant:
    """Higher-level research analysis built on clusters + metrics."""

    def __init__(self, model: EntryModel):
        self._model = model

    def thesis_relevance_score(
        self,
        entry_id: int,
        thesis_keywords: list[str],
        embeddings: dict[int, np.ndarray] | None = None,
        thesis_embedding: np.ndarray | None = None,
    ) -> float:
        """
        Score how relevant a paper is to the user's thesis.

        Formula:
        score = 0.5 * cosine_sim(paper_emb, thesis_emb)
              + 0.3 * keyword_overlap
              + 0.2 * pagerank

        Returns 0-1 relevance score.
        """
        score = 0.0

        # 1. Embedding similarity (50% weight)
        if embeddings and thesis_embedding is not None and entry_id in embeddings:
            vec = embeddings[entry_id]
            sim = self._cosine_sim(vec, thesis_embedding)
            score += 0.5 * max(0, sim)

        # 2. Keyword overlap (30% weight)
        entry = self._model.read_by_id(entry_id)
        if entry and thesis_keywords:
            text = f"{entry.get('title', '')} {entry.get('notes', '')}".lower()
            # Get AI topics
            topics = self._model.get_ai_topics(entry_id)
            text += " " + " ".join(topics).lower()

            matched = sum(1 for kw in thesis_keywords if kw.lower() in text)
            keyword_score = matched / len(thesis_keywords)
            score += 0.3 * keyword_score

        # 3. PageRank (20% weight)
        metrics = self._model.get_metrics(entry_id)
        if metrics:
            # Normalize PageRank to 0-1 (approximate)
            pr = metrics.get("pagerank", 0.0)
            score += 0.2 * min(1.0, pr * 10)  # scale up since PR is typically small

        return min(1.0, score)

    def detect_research_gaps(
        self,
        clusters: list[dict],
        entries: list[dict],
    ) -> list[ResearchGap]:
        """
        Identify under-explored areas:
        - Clusters with low density (loosely connected papers)
        - Time gaps (cluster active pre-2015 but no recent papers)
        - Small clusters that might need more exploration
        """
        gaps: list[ResearchGap] = []
        current_year = datetime.datetime.now().year

        for cluster in clusters:
            label = cluster.get("label", "Unknown")
            density = cluster.get("density", 0.0)
            entry_ids = cluster.get("entry_ids", [])
            cid = cluster.get("id", 0)

            # 1. Low-density clusters
            if density < 0.3 and len(entry_ids) >= 3:
                gaps.append(ResearchGap(
                    type="sparse_topic",
                    message=f"'{label}' has loosely connected papers (density: {density:.2f}) "
                            f"— potential area for a systematic review",
                    cluster_label=label,
                    cluster_ids=[cid],
                    severity="opportunity",
                ))

            # 2. Temporal gaps
            years: list[int] = []
            for eid in entry_ids:
                entry = next((e for e in entries if e.get("id") == eid), None)
                if entry:
                    try:
                        y = int(entry.get("year", "0"))
                        if 1900 <= y <= current_year + 1:
                            years.append(y)
                    except (ValueError, TypeError):
                        pass

            if years:
                max_year = max(years)
                if max_year < current_year - 5:
                    gaps.append(ResearchGap(
                        type="stale_topic",
                        message=f"'{label}' has no papers after {max_year} "
                                f"— declining or saturated topic?",
                        cluster_label=label,
                        cluster_ids=[cid],
                        severity="warning",
                    ))

            # 3. Very small clusters
            if 1 <= len(entry_ids) <= 2:
                gaps.append(ResearchGap(
                    type="sparse_topic",
                    message=f"'{label}' has only {len(entry_ids)} paper(s) "
                            f"— consider expanding research in this area",
                    cluster_label=label,
                    cluster_ids=[cid],
                    severity="info",
                ))

        return gaps

    def topic_timeline(
        self,
        clusters: list[dict],
        entries: list[dict],
    ) -> list[TopicTimeline]:
        """
        For each cluster, return year → paper count data
        for timeline visualization.
        """
        entries_by_id = {e.get("id"): e for e in entries}
        timelines: list[TopicTimeline] = []

        for cluster in clusters:
            year_counts: dict[int, int] = {}
            for eid in cluster.get("entry_ids", []):
                entry = entries_by_id.get(eid)
                if entry:
                    try:
                        y = int(entry.get("year", "0"))
                        if 1900 <= y <= 2100:
                            year_counts[y] = year_counts.get(y, 0) + 1
                    except (ValueError, TypeError):
                        pass

            if year_counts:
                years = sorted(year_counts.items())
                timelines.append(TopicTimeline(
                    cluster_id=cluster.get("id", 0),
                    cluster_label=cluster.get("label", ""),
                    years=years,
                ))

        return timelines

    def recommend_papers(
        self,
        entry_id: int,
        embeddings: dict[int, np.ndarray] | None = None,
        top_k: int = 5,
    ) -> list[tuple[int, float, str]]:
        """
        Recommend related papers based on:
        1. Embedding similarity (50% weight)
        2. Shared cluster (30% weight)
        3. Keyword overlap (20% weight)

        Returns [(entry_id, score, reason), ...]
        """
        entry = self._model.read_by_id(entry_id)
        if not entry:
            return []

        entry_clusters = self._model.get_entry_clusters(entry_id)
        entry_cluster_ids = {c.get("cluster_id") for c in entry_clusters}

        entry_topics = set(self._model.get_ai_topics(entry_id))

        all_entries = self._model.read_all_full()
        scores: list[tuple[int, float, str]] = []

        for other in all_entries:
            oid = other.get("id")
            if oid == entry_id:
                continue

            score = 0.0
            reason_parts = []

            # 1. Embedding similarity
            if embeddings and entry_id in embeddings and oid in embeddings:
                sim = self._cosine_sim(embeddings[entry_id], embeddings[oid])
                score += 0.5 * max(0, sim)
                if sim > 0.7:
                    reason_parts.append(f"High similarity ({sim:.0%})")

            # 2. Shared cluster
            other_clusters = self._model.get_entry_clusters(oid)
            other_cluster_ids = {c.get("cluster_id") for c in other_clusters}
            shared = entry_cluster_ids & other_cluster_ids
            if shared:
                score += 0.3
                reason_parts.append("Same topic cluster")

            # 3. Keyword overlap
            other_topics = set(self._model.get_ai_topics(oid))
            if entry_topics and other_topics:
                overlap = len(entry_topics & other_topics) / max(len(entry_topics | other_topics), 1)
                score += 0.2 * overlap
                if overlap > 0.3:
                    reason_parts.append("Shared keywords")

            if score > 0.1:
                reason = "; ".join(reason_parts) if reason_parts else "Related"
                scores.append((oid, score, reason))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        na = np.linalg.norm(a)
        nb = np.linalg.norm(b)
        if na == 0 or nb == 0:
            return 0.0
        return float(np.dot(a, b) / (na * nb))
