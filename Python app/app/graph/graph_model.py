"""
graph_model.py — In-memory graph model wrapping NetworkX.

Stores Document and Keyword nodes with typed edges.
Supports community detection for thematic clustering.
Serializes to / from JSON for caching.
"""
from __future__ import annotations

import json
from typing import Any

import networkx as nx


# ── Node types ────────────────────────────────────────────────────────────────
NODE_DOCUMENT = "document"
NODE_KEYWORD  = "keyword"

# ── Edge types ────────────────────────────────────────────────────────────────
EDGE_CONTAINS_KW   = "contains_keyword"
EDGE_KEYWORD_OVERLAP = "keyword_overlap"
EDGE_SEMANTIC_SIM  = "semantic_similarity"


class GraphModel:
    """Thin wrapper around a ``networkx.MultiGraph`` with typed nodes and edges."""

    def __init__(self):
        self._g = nx.MultiGraph()
        self._clusters: list[set[str]] = []

    # ── Node API ──────────────────────────────────────────────────────────
    def add_node(self, node_id: str, node_type: str, label: str, **data: Any) -> None:
        self._g.add_node(node_id, node_type=node_type, label=label, **data)

    def get_node(self, node_id: str) -> dict | None:
        if node_id in self._g.nodes:
            return dict(self._g.nodes[node_id])
        return None

    def nodes(self, node_type: str | None = None):
        """Iterate over (node_id, attrs) pairs, optionally filtered by type."""
        for nid, attrs in self._g.nodes(data=True):
            if node_type is None or attrs.get("node_type") == node_type:
                yield nid, attrs

    @property
    def node_count(self) -> int:
        return self._g.number_of_nodes()

    # ── Edge API ──────────────────────────────────────────────────────────
    def add_edge(self, source: str, target: str, edge_type: str,
                 weight: float = 1.0, **data: Any) -> None:
        self._g.add_edge(source, target, edge_type=edge_type,
                         weight=weight, **data)

    def edges(self, edge_type: str | None = None):
        """Iterate over (source, target, attrs) triples."""
        for u, v, attrs in self._g.edges(data=True):
            if edge_type is None or attrs.get("edge_type") == edge_type:
                yield u, v, attrs

    def get_neighbors(self, node_id: str) -> list[str]:
        if node_id in self._g:
            return list(self._g.neighbors(node_id))
        return []

    @property
    def edge_count(self) -> int:
        return self._g.number_of_edges()

    # ── Subgraph ──────────────────────────────────────────────────────────
    def subgraph_around(self, node_id: str, depth: int = 1) -> set[str]:
        """Return set of node IDs within *depth* hops of *node_id*."""
        visited: set[str] = set()
        frontier = {node_id}
        for _ in range(depth):
            next_frontier: set[str] = set()
            for nid in frontier:
                if nid not in visited:
                    visited.add(nid)
                    next_frontier.update(self._g.neighbors(nid))
            frontier = next_frontier - visited
        visited.update(frontier)
        return visited

    # ── Clustering ────────────────────────────────────────────────────────
    def detect_clusters(self, min_size: int = 2) -> list[set[str]]:
        """
        Detect communities using greedy modularity optimization.
        Only considers document nodes for clustering.
        """
        doc_nodes = [nid for nid, a in self._g.nodes(data=True)
                     if a.get("node_type") == NODE_DOCUMENT]
        if len(doc_nodes) < min_size:
            self._clusters = []
            return self._clusters

        sub = self._g.subgraph(doc_nodes).copy()
        if sub.number_of_edges() == 0:
            self._clusters = []
            return self._clusters

        try:
            from networkx.algorithms.community import greedy_modularity_communities
            communities = greedy_modularity_communities(sub, weight="weight")
            self._clusters = [set(c) for c in communities if len(c) >= min_size]
        except Exception:
            self._clusters = []
        return self._clusters

    @property
    def clusters(self) -> list[set[str]]:
        return self._clusters

    # ── Serialization ─────────────────────────────────────────────────────
    def to_json(self) -> dict:
        """Serialize to a JSON-safe dict."""
        nodes = []
        for nid, attrs in self._g.nodes(data=True):
            node = {"id": nid}
            node.update(attrs)
            nodes.append(node)

        edges = []
        for u, v, attrs in self._g.edges(data=True):
            edge = {"source": u, "target": v}
            edge.update(attrs)
            edges.append(edge)

        clusters = [sorted(c) for c in self._clusters]
        return {"nodes": nodes, "edges": edges, "clusters": clusters}

    @classmethod
    def from_json(cls, data: dict) -> "GraphModel":
        """Deserialize from a JSON dict without modifying the input."""
        gm = cls()
        for node in data.get("nodes", []):
            nid = node.get("id")
            if nid is None:
                continue
            # Pass all attributes except 'id' to add_node
            attrs = {k: v for k, v in node.items() if k != "id"}
            gm._g.add_node(nid, **attrs)

        for edge in data.get("edges", []):
            src = edge.get("source")
            tgt = edge.get("target")
            if src is None or tgt is None:
                continue
            attrs = {k: v for k, v in edge.items() if k not in ("source", "target")}
            gm._g.add_edge(src, tgt, **attrs)

        gm._clusters = [set(c) for c in data.get("clusters", [])]
        return gm

    def to_json_string(self) -> str:
        return json.dumps(self.to_json(), ensure_ascii=False)

    @classmethod
    def from_json_string(cls, s: str) -> "GraphModel":
        return cls.from_json(json.loads(s))
