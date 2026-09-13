"""
metrics.py — Graph-based metrics for CiteMind papers.

Computes per-paper metrics using NetworkX graph algorithms:
  - degree centrality
  - betweenness centrality (bridge detection)
  - closeness centrality
  - PageRank
  - cluster role classification

All metrics are computed on the document-only subgraph.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import networkx as nx

from app.graph.graph_model import GraphModel, NODE_DOCUMENT


@dataclass
class PaperMetrics:
    """Per-paper graph metrics."""
    entry_id: int
    degree_centrality: float = 0.0
    betweenness: float = 0.0
    closeness: float = 0.0
    pagerank: float = 0.0
    cluster_role: str = ""  # 'central', 'bridge', 'isolated', 'peripheral'

    def to_dict(self) -> dict:
        return {
            "entry_id": self.entry_id,
            "degree_centrality": self.degree_centrality,
            "betweenness": self.betweenness,
            "closeness": self.closeness,
            "pagerank": self.pagerank,
            "cluster_role": self.cluster_role,
        }


class GraphMetrics:
    """Compute and cache graph-theoretic metrics for each paper."""

    def compute_all(self, gm: GraphModel) -> dict[int, PaperMetrics]:
        """
        Compute metrics for all document nodes in the graph.

        Returns
        -------
        dict[int, PaperMetrics]
            Mapping entry_id → PaperMetrics.
        """
        doc_nodes = []
        node_to_eid: dict[str, int] = {}

        for nid, attrs in gm.nodes(node_type=NODE_DOCUMENT):
            eid = attrs.get("entry_id")
            if eid is not None:
                doc_nodes.append(nid)
                node_to_eid[nid] = eid

        if len(doc_nodes) < 2:
            # Not enough nodes for meaningful metrics
            return {
                node_to_eid[nid]: PaperMetrics(entry_id=node_to_eid[nid], cluster_role="isolated")
                for nid in doc_nodes
            }

        # Build document-only subgraph
        sub = gm._g.subgraph(doc_nodes).copy()

        # Compute centrality metrics
        degree = nx.degree_centrality(sub)
        try:
            betweenness = nx.betweenness_centrality(sub, weight="weight")
        except Exception:
            betweenness = {n: 0.0 for n in sub.nodes}

        try:
            closeness = nx.closeness_centrality(sub)
        except Exception:
            closeness = {n: 0.0 for n in sub.nodes}

        try:
            pagerank = nx.pagerank(sub, weight="weight", max_iter=100)
        except Exception:
            pagerank = {n: 1.0 / len(sub) for n in sub.nodes}

        # Compute percentiles for role classification
        betweenness_vals = list(betweenness.values())
        pagerank_vals = list(pagerank.values())
        degree_vals = list(degree.values())

        p90_betweenness = float(np.percentile(betweenness_vals, 90)) if betweenness_vals else 0
        p80_pagerank = float(np.percentile(pagerank_vals, 80)) if pagerank_vals else 0

        # Get cluster info for bridge detection
        clusters = gm.clusters
        node_cluster: dict[str, int] = {}
        for cid, cluster_set in enumerate(clusters):
            for nid in cluster_set:
                node_cluster[nid] = cid

        results: dict[int, PaperMetrics] = {}
        for nid in doc_nodes:
            eid = node_to_eid[nid]
            d = degree.get(nid, 0.0)
            b = betweenness.get(nid, 0.0)
            c = closeness.get(nid, 0.0)
            p = pagerank.get(nid, 0.0)

            role = self._classify_role(nid, d, b, p, p90_betweenness,
                                       p80_pagerank, node_cluster, sub)

            results[eid] = PaperMetrics(
                entry_id=eid,
                degree_centrality=round(d, 6),
                betweenness=round(b, 6),
                closeness=round(c, 6),
                pagerank=round(p, 6),
                cluster_role=role,
            )

        return results

    def find_bridge_papers(self, gm: GraphModel) -> list[int]:
        """
        Find papers that bridge different clusters.
        These have high betweenness centrality and connect nodes from
        different communities.
        """
        metrics = self.compute_all(gm)
        return [
            m.entry_id for m in metrics.values()
            if m.cluster_role == "bridge"
        ]

    def find_isolated_papers(self, gm: GraphModel) -> list[int]:
        """Find papers with very few connections."""
        metrics = self.compute_all(gm)
        return [
            m.entry_id for m in metrics.values()
            if m.cluster_role == "isolated"
        ]

    def find_central_papers(self, gm: GraphModel) -> list[int]:
        """Find the most central/important papers."""
        metrics = self.compute_all(gm)
        return [
            m.entry_id for m in metrics.values()
            if m.cluster_role == "central"
        ]

    def compute_topic_density(
        self,
        embeddings: dict[int, np.ndarray],
        cluster_entry_ids: list[int],
    ) -> float:
        """
        Average pairwise cosine similarity within a cluster.
        Returns 0-1 where 1 = perfectly homogeneous.
        """
        vecs = [embeddings[eid] for eid in cluster_entry_ids if eid in embeddings]
        if len(vecs) < 2:
            return 1.0

        matrix = np.array(vecs)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix = matrix / norms

        sim = matrix @ matrix.T
        n = len(vecs)
        total = 0.0
        count = 0
        for i in range(n):
            for j in range(i + 1, n):
                total += sim[i, j]
                count += 1

        return float(total / count) if count > 0 else 0.0

    def semantic_distance(
        self,
        embeddings: dict[int, np.ndarray],
        entry_a: int,
        entry_b: int,
    ) -> float:
        """
        Semantic distance between two papers (1 - cosine_similarity).
        Returns 0-2 where 0 = identical, 1 = orthogonal, 2 = opposite.
        """
        if entry_a not in embeddings or entry_b not in embeddings:
            return 1.0  # unknown → assume orthogonal

        va = embeddings[entry_a]
        vb = embeddings[entry_b]

        na = np.linalg.norm(va)
        nb = np.linalg.norm(vb)
        if na == 0 or nb == 0:
            return 1.0

        sim = float(np.dot(va, vb) / (na * nb))
        return 1.0 - sim

    # ── Role classification ───────────────────────────────────────────────

    @staticmethod
    def _classify_role(
        node_id: str,
        degree: float,
        betweenness: float,
        pagerank: float,
        p90_betweenness: float,
        p80_pagerank: float,
        node_cluster: dict[str, int],
        graph: nx.Graph,
    ) -> str:
        """
        Classify a paper's structural role in the knowledge graph.

        Roles:
          - isolated: degree < 2 connections
          - bridge: high betweenness, connects different clusters
          - central: high PageRank, hub within its cluster
          - peripheral: everything else
        """
        # Count actual edges (degree centrality is normalized)
        actual_degree = graph.degree(node_id) if node_id in graph else 0

        if actual_degree < 2:
            return "isolated"

        # Check if this node bridges different clusters
        if betweenness >= p90_betweenness and p90_betweenness > 0:
            my_cluster = node_cluster.get(node_id)
            neighbor_clusters = set()
            for nb in graph.neighbors(node_id):
                nc = node_cluster.get(nb)
                if nc is not None and nc != my_cluster:
                    neighbor_clusters.add(nc)
            if neighbor_clusters:
                return "bridge"

        if pagerank >= p80_pagerank and p80_pagerank > 0:
            return "central"

        return "peripheral"
