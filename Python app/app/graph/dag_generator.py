"""Generate a chronological citation DAG from parsed references and archive entries."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import networkx as nx
from pyvis.network import Network


def _safe_year(value: Any) -> int | None:
    """Coerce a year-like value into an integer or None."""
    if value in (None, "", "null"):
        return None
    try:
        return int(str(value).strip()[:4])
    except (TypeError, ValueError):
        return None


def _norm_title(value: Any) -> str:
    """Normalize titles for node identity."""
    text = str(value or "").strip()
    return " ".join(text.split())


def _node_label(reference: dict[str, Any], *, in_archive: bool) -> str:
    """Build the node label for the DAG."""
    title = _norm_title(reference.get("title") or reference.get("reference", {}).get("title"))
    if len(title) > 60:
        title = title[:57] + "..."
    state = "archivio" if in_archive else "fantasma"
    return f"{title} ({state})"


def _merge_reference_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize and deduplicate references before building the DAG."""
    merged: dict[str, dict[str, Any]] = {}
    for item in items or []:
        title = _norm_title(item.get("title") or item.get("reference", {}).get("title"))
        if not title:
            continue
        bucket = merged.setdefault(
            title,
            {
                "title": title,
                "year": item.get("year"),
                "authors": list(item.get("authors") or []),
                "source": item.get("source") or "bibliography",
            },
        )
        if item.get("year") not in (None, "", "null"):
            bucket["year"] = item.get("year")
        authors = item.get("authors") or []
        if isinstance(authors, str):
            authors = [authors]
        for author in authors:
            text = str(author).strip()
            if text and text not in bucket["authors"]:
                bucket["authors"].append(text)

    return list(merged.values())


def build_reference_dag(
    references: list[dict[str, Any]],
    known_entries: list[dict[str, Any]] | None = None,
    *,
    source_label: str = "bibliography",
) -> nx.DiGraph:
    """Create a chronologically ordered citation DAG.

    The graph includes all available reference data, but redundant relationships are
    removed so the DAG stays readable and functional instead of becoming a dense
    chain of duplicate links.
    """
    graph = nx.DiGraph()
    known = known_entries or []

    all_refs: list[dict[str, Any]] = []
    for ref in references or []:
        all_refs.append(ref)
    for entry in known:
        raw_bib = entry.get("extracted_bibliography") or entry.get("bibliography") or []
        if isinstance(raw_bib, str):
            try:
                raw_bib = json.loads(raw_bib)
            except Exception:
                raw_bib = []
        if isinstance(raw_bib, list):
            all_refs.extend(raw_bib)

    archive_titles = {_norm_title(item.get("title") or ""): item for item in known if _norm_title(item.get("title") or "")}
    ordered = sorted(
        _merge_reference_items(all_refs),
        key=lambda item: (_safe_year(item.get("year")) is None, _safe_year(item.get("year")) or 0, _norm_title(item.get("title"))),
    )

    for ref in ordered:
        title = _norm_title(ref.get("title"))
        if not title:
            continue
        year = _safe_year(ref.get("year"))
        entry = archive_titles.get(title)
        in_archive = entry is not None
        graph.add_node(
            title,
            title=title,
            year=year,
            authors=ref.get("authors") or [],
            source=ref.get("source") or source_label,
            in_archive=in_archive,
            color="#22c55e" if in_archive else "#f59e0b",
            size=18 if in_archive else 14,
            label=_node_label(ref, in_archive=in_archive),
        )

    seen_edges: set[tuple[str, str]] = set()
    for idx, ref in enumerate(ordered):
        title = _norm_title(ref.get("title"))
        if not title:
            continue
        year = _safe_year(ref.get("year"))
        prev_candidates = [
            item for item in ordered[:idx]
            if _safe_year(item.get("year")) is not None and year is not None and _safe_year(item.get("year")) <= year
        ]
        if not prev_candidates:
            continue
        prev = max(prev_candidates, key=lambda item: (_safe_year(item.get("year")) or 0, _norm_title(item.get("title"))))
        prev_title = _norm_title(prev.get("title"))
        if not prev_title or prev_title == title:
            continue
        edge = (prev_title, title)
        if edge in seen_edges:
            continue
        graph.add_edge(prev_title, title, weight=1)
        seen_edges.add(edge)

    if graph.number_of_nodes() == 0:
        return graph

    try:
        topo = list(nx.topological_sort(graph))
        if len(topo) != graph.number_of_nodes():
            relabel = sorted(graph.nodes(data=True), key=lambda item: (item[1].get("year") is None, item[1].get("year") or 0, item[0]))
            value_order = [node for node, _ in relabel]
            nx.set_node_attributes(graph, {node: idx for idx, node in enumerate(value_order)}, "order")
        else:
            nx.set_node_attributes(graph, {node: idx for idx, node in enumerate(topo)}, "order")
    except nx.NetworkXUnfeasible:
        ordered_nodes = sorted(graph.nodes(data=True), key=lambda item: (item[1].get("year") is None, item[1].get("year") or 0, item[0]))
        nx.set_node_attributes(graph, {node: idx for idx, (node, _) in enumerate(ordered_nodes)}, "order")

    return graph


def render_reference_dag_html(graph: nx.DiGraph, *, height: str = "700px") -> str:
    """Export a NetworkX DAG to interactive HTML using PyVis."""
    if graph.number_of_nodes() == 0:
        return "<div style='padding:12px;color:#666;font-family:sans-serif;'>Nessuna referenza disponibile.</div>"

    net = Network(height=height, width="100%", directed=True, bgcolor="#111827", font_color="#f3f4f6", notebook=False)
    net.barnes_hut()

    for node_id, attrs in graph.nodes(data=True):
        net.add_node(
            node_id,
            label=attrs.get("label") or str(node_id),
            title=str(node_id),
            color=attrs.get("color", "#60a5fa"),
            size=attrs.get("size", 18),
            font={"size": 14, "color": "#f3f4f6"},
            shape="dot",
        )

    for source, target, attrs in graph.edges(data=True):
        net.add_edge(source, target, value=attrs.get("weight", 1), arrows="to", color="#93c5fd")

    html_body = net.generate_html(notebook=False)
    return html_body


def save_reference_dag_html(graph: nx.DiGraph, output_path: str | Path) -> str:
    """Persist the rendered HTML to disk and return the same HTML string."""
    html_text = render_reference_dag_html(graph)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_text, encoding="utf-8")
    return html_text
