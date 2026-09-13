"""
clustering.py — Semantic clustering engine for CiteMind.

Assigns papers to thematic clusters using embedding vectors.
Supports multiple algorithms with automatic fallback:
  1. HDBSCAN (if installed, best for noisy data)
  2. Louvain community detection on cosine-similarity graph
  3. Agglomerative clustering (scipy, always available)

All clustering operates on numpy arrays of embedding vectors.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from collections import Counter

import numpy as np
import networkx as nx


# ── Perceptually distinct palette for cluster coloring ────────────────────────
CLUSTER_PALETTE = [
    "#7c3aed",  # violet
    "#06b6d4",  # cyan
    "#f59e0b",  # amber
    "#ef4444",  # red
    "#22c55e",  # green
    "#ec4899",  # pink
    "#3b82f6",  # blue
    "#f97316",  # orange
    "#8b5cf6",  # purple
    "#14b8a6",  # teal
    "#e11d48",  # rose
    "#84cc16",  # lime
]


@dataclass
class ClusterAssignment:
    """One entry's membership in a cluster."""
    cluster_id: int
    is_primary: bool
    confidence: float  # 0.0–1.0


@dataclass
class Cluster:
    """A thematic cluster of papers."""
    id: int
    label: str
    color: str
    entry_ids: list[int] = field(default_factory=list)
    centroid: np.ndarray | None = None
    density: float = 0.0
    description: str = ""


@dataclass
class ClusterResult:
    """Complete result of a clustering run."""
    clusters: list[Cluster]
    assignments: dict[int, list[ClusterAssignment]]  # entry_id → assignments
    noise_entries: list[int]  # entries not assigned to any cluster


class SemanticClusterEngine:
    """
    Manages clustering of papers using embedding vectors.
    Supports multiple algorithms with automatic selection.
    """

    def cluster_papers(
        self,
        embeddings: dict[int, np.ndarray],
        method: str = "auto",
        min_cluster_size: int = 3,
        n_clusters_hint: int | None = None,
    ) -> ClusterResult:
        """
        Cluster papers based on their embedding vectors.

        Parameters
        ----------
        embeddings : dict[int, np.ndarray]
            Mapping of entry_id → embedding vector.
        method : str
            "auto", "hdbscan", "louvain", or "agglomerative".
        min_cluster_size : int
            Minimum papers per cluster.
        n_clusters_hint : int | None
            Approximate number of clusters (used by agglomerative).

        Returns
        -------
        ClusterResult
        """
        if len(embeddings) < min_cluster_size:
            return ClusterResult(clusters=[], assignments={}, noise_entries=list(embeddings.keys()))

        entry_ids = list(embeddings.keys())
        vectors = np.array([embeddings[eid] for eid in entry_ids])

        # Normalize vectors for cosine similarity
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vectors_norm = vectors / norms

        if method == "auto":
            method = self._select_method(len(entry_ids))

        if method == "hdbscan":
            labels = self._cluster_hdbscan(vectors_norm, min_cluster_size)
        elif method == "louvain":
            labels = self._cluster_louvain(vectors_norm, entry_ids)
        else:
            labels = self._cluster_agglomerative(vectors_norm, n_clusters_hint, min_cluster_size)

        return self._build_result(entry_ids, vectors_norm, labels, min_cluster_size)

    def cluster_from_graph(
        self,
        graph: nx.Graph,
        entry_ids: list[int],
        min_cluster_size: int = 2,
    ) -> ClusterResult:
        """
        Cluster papers using community detection on an existing graph.
        Useful when embeddings are not available.
        """
        doc_nodes = [f"doc_{eid}" for eid in entry_ids if f"doc_{eid}" in graph]
        if len(doc_nodes) < min_cluster_size:
            return ClusterResult(clusters=[], assignments={}, noise_entries=entry_ids)

        sub = graph.subgraph(doc_nodes).copy()
        if sub.number_of_edges() == 0:
            return ClusterResult(clusters=[], assignments={}, noise_entries=entry_ids)

        try:
            from networkx.algorithms.community import greedy_modularity_communities
            communities = greedy_modularity_communities(sub, weight="weight")
            communities = [c for c in communities if len(c) >= min_cluster_size]
        except Exception:
            return ClusterResult(clusters=[], assignments={}, noise_entries=entry_ids)

        clusters = []
        assignments: dict[int, list[ClusterAssignment]] = {}
        assigned_ids: set[int] = set()

        for idx, community in enumerate(communities):
            cluster_id = idx + 1
            color = CLUSTER_PALETTE[idx % len(CLUSTER_PALETTE)]
            cluster_entry_ids = []

            for node_id in community:
                try:
                    eid = int(node_id.split("_", 1)[1])
                    cluster_entry_ids.append(eid)
                    assigned_ids.add(eid)
                    assignments.setdefault(eid, []).append(
                        ClusterAssignment(
                            cluster_id=cluster_id,
                            is_primary=True,
                            confidence=0.8,
                        )
                    )
                except (ValueError, IndexError):
                    continue

            clusters.append(Cluster(
                id=cluster_id,
                label=f"Cluster {cluster_id}",
                color=color,
                entry_ids=cluster_entry_ids,
                density=self._compute_graph_density(sub, community),
            ))

        noise = [eid for eid in entry_ids if eid not in assigned_ids]
        return ClusterResult(clusters=clusters, assignments=assignments, noise_entries=noise)

    # ── Algorithm selection ───────────────────────────────────────────────

    @staticmethod
    def _select_method(n_entries: int) -> str:
        """Auto-select the best clustering algorithm."""
        try:
            import hdbscan  # noqa: F401
            if n_entries >= 20:
                return "hdbscan"
        except ImportError:
            pass
        if n_entries >= 10:
            return "louvain"
        return "agglomerative"

    # ── HDBSCAN ───────────────────────────────────────────────────────────

    @staticmethod
    def _cluster_hdbscan(vectors: np.ndarray, min_cluster_size: int) -> np.ndarray:
        """Cluster using HDBSCAN on cosine distance."""
        try:
            import hdbscan
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=max(min_cluster_size, 3),
                metric="euclidean",  # on L2-normalized vectors ≈ cosine
                cluster_selection_method="eom",
                prediction_data=True,
            )
            labels = clusterer.fit_predict(vectors)
            return labels
        except ImportError:
            # Fallback if hdbscan not available
            return SemanticClusterEngine._cluster_agglomerative(vectors, None, min_cluster_size)

    # ── Louvain (via cosine similarity graph) ─────────────────────────────

    @staticmethod
    def _cluster_louvain(vectors: np.ndarray, entry_ids: list[int],
                         threshold: float = 0.5) -> np.ndarray:
        """Build cosine similarity graph, then run Louvain community detection."""
        n = len(vectors)
        sim_matrix = vectors @ vectors.T

        # Build graph with edges above threshold
        G = nx.Graph()
        for i in range(n):
            G.add_node(i)
        for i in range(n):
            for j in range(i + 1, n):
                sim = float(sim_matrix[i, j])
                if sim >= threshold:
                    G.add_edge(i, j, weight=sim)

        if G.number_of_edges() == 0:
            return np.full(n, -1, dtype=int)

        try:
            from networkx.algorithms.community import greedy_modularity_communities
            communities = greedy_modularity_communities(G, weight="weight")
            labels = np.full(n, -1, dtype=int)
            for cid, community in enumerate(communities):
                for node in community:
                    labels[node] = cid
            return labels
        except Exception:
            return np.full(n, -1, dtype=int)

    # ── Agglomerative (scipy fallback) ────────────────────────────────────

    @staticmethod
    def _cluster_agglomerative(vectors: np.ndarray,
                                n_clusters: int | None,
                                min_cluster_size: int) -> np.ndarray:
        """Hierarchical agglomerative clustering using scipy."""
        from scipy.cluster.hierarchy import linkage, fcluster
        from scipy.spatial.distance import pdist

        n = len(vectors)
        if n < 2:
            return np.array([0] * n)

        # Cosine distance
        distances = pdist(vectors, metric="cosine")
        # Replace NaN with max distance
        distances = np.nan_to_num(distances, nan=1.0)

        Z = linkage(distances, method="ward")

        if n_clusters is None:
            # Auto-determine: use silhouette-like heuristic
            # Try k = sqrt(n) capped at 20
            n_clusters = max(2, min(int(math.sqrt(n)), 20))

        labels = fcluster(Z, t=n_clusters, criterion="maxclust") - 1  # 0-indexed
        return labels

    # ── Result builder ────────────────────────────────────────────────────

    def _build_result(
        self,
        entry_ids: list[int],
        vectors: np.ndarray,
        labels: np.ndarray,
        min_cluster_size: int,
    ) -> ClusterResult:
        """Convert raw cluster labels into a structured ClusterResult."""
        unique_labels = set(labels)
        unique_labels.discard(-1)  # noise label

        # Count members per cluster
        label_counts = Counter(labels)

        # Merge small clusters into noise
        valid_labels: set[int] = set()
        for lbl, count in label_counts.items():
            if lbl != -1 and count >= min_cluster_size:
                valid_labels.add(lbl)

        # Build clusters
        clusters: list[Cluster] = []
        assignments: dict[int, list[ClusterAssignment]] = {}
        noise: list[int] = []

        # Remap labels to sequential IDs
        label_to_cid: dict[int, int] = {}
        for new_id, old_label in enumerate(sorted(valid_labels), start=1):
            label_to_cid[old_label] = new_id

        # Compute centroids
        cluster_vectors: dict[int, list[np.ndarray]] = {}
        cluster_entries: dict[int, list[int]] = {}

        for i, (eid, lbl) in enumerate(zip(entry_ids, labels)):
            if lbl in label_to_cid:
                cid = label_to_cid[lbl]
                cluster_vectors.setdefault(cid, []).append(vectors[i])
                cluster_entries.setdefault(cid, []).append(eid)
            else:
                noise.append(eid)

        for cid in sorted(cluster_entries.keys()):
            vecs = np.array(cluster_vectors[cid])
            centroid = vecs.mean(axis=0)
            # Normalize centroid
            cn = np.linalg.norm(centroid)
            if cn > 0:
                centroid = centroid / cn

            # Compute density: average pairwise cosine similarity
            density = self._compute_density(vecs)

            color = CLUSTER_PALETTE[(cid - 1) % len(CLUSTER_PALETTE)]
            eids = cluster_entries[cid]

            clusters.append(Cluster(
                id=cid,
                label=f"Cluster {cid}",
                color=color,
                entry_ids=eids,
                centroid=centroid,
                density=density,
            ))

            # Compute per-paper confidence (similarity to centroid)
            for i_local, eid in enumerate(eids):
                sim = float(vecs[i_local] @ centroid)
                assignments.setdefault(eid, []).append(
                    ClusterAssignment(
                        cluster_id=cid,
                        is_primary=True,
                        confidence=max(0.0, min(1.0, sim)),
                    )
                )

        # Add secondary cluster assignments for papers near other centroids
        self._assign_secondary_clusters(entry_ids, vectors, labels,
                                         clusters, assignments, label_to_cid)

        return ClusterResult(clusters=clusters, assignments=assignments, noise_entries=noise)

    def _assign_secondary_clusters(
        self,
        entry_ids: list[int],
        vectors: np.ndarray,
        labels: np.ndarray,
        clusters: list[Cluster],
        assignments: dict[int, list[ClusterAssignment]],
        label_to_cid: dict[int, int],
        threshold: float = 0.5,
        max_secondary: int = 2,
    ) -> None:
        """Assign papers to secondary clusters based on centroid proximity."""
        if not clusters:
            return

        centroids = {c.id: c.centroid for c in clusters if c.centroid is not None}
        if not centroids:
            return

        for i, (eid, lbl) in enumerate(zip(entry_ids, labels)):
            if lbl not in label_to_cid:
                continue
            primary_cid = label_to_cid[lbl]
            vec = vectors[i]

            # Compute similarity to all other cluster centroids
            sims: list[tuple[int, float]] = []
            for cid, centroid in centroids.items():
                if cid == primary_cid:
                    continue
                sim = float(vec @ centroid)
                if sim >= threshold:
                    sims.append((cid, sim))

            sims.sort(key=lambda x: x[1], reverse=True)
            for cid, sim in sims[:max_secondary]:
                assignments[eid].append(
                    ClusterAssignment(
                        cluster_id=cid,
                        is_primary=False,
                        confidence=max(0.0, min(1.0, sim)),
                    )
                )

    # ── Density helpers ───────────────────────────────────────────────────

    @staticmethod
    def _compute_density(vectors: np.ndarray) -> float:
        """Average pairwise cosine similarity within a cluster."""
        n = len(vectors)
        if n < 2:
            return 1.0
        sim_matrix = vectors @ vectors.T
        # Sum upper triangle (excluding diagonal)
        total = 0.0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                total += sim_matrix[i, j]
                count += 1
        return float(total / count) if count > 0 else 0.0

    @staticmethod
    def _compute_graph_density(graph: nx.Graph, nodes: set) -> float:
        """Density of a subgraph induced by a set of nodes."""
        sub = graph.subgraph(nodes)
        n = sub.number_of_nodes()
        if n < 2:
            return 1.0
        max_edges = n * (n - 1) / 2
        return sub.number_of_edges() / max_edges if max_edges > 0 else 0.0

    # ── Label generation ──────────────────────────────────────────────────

    @staticmethod
    def generate_cluster_labels(
        clusters: list[Cluster],
        entries: list[dict],
    ) -> list[Cluster]:
        """
        Generate human-readable labels for clusters using TF-IDF
        on the titles of member papers.
        """
        from app.graph.keyword_extractor import _tokenize, _simple_lemma, _STOPWORDS

        entries_by_id = {e["id"]: e for e in entries}

        for cluster in clusters:
            # Collect words from member paper titles
            word_freq: Counter = Counter()
            for eid in cluster.entry_ids:
                entry = entries_by_id.get(eid, {})
                title = entry.get("title", "")
                tokens = _tokenize(title)
                lemmas = [_simple_lemma(t) for t in tokens]
                word_freq.update(lemmas)

            # Pick top 2-3 most common words as label
            top_words = [w for w, _ in word_freq.most_common(3)]
            if top_words:
                # Capitalize and join
                label = " & ".join(w.capitalize() for w in top_words)
                cluster.label = label

        return clusters
