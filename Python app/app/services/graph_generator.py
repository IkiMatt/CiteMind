"""
graph_generator.py — Generates GraphModel-compatible JSON dicts for the
reference DAG (single-entry and global views).
"""
from __future__ import annotations
import json


def make_compact_label(entry: dict) -> str:
    """Short label for graph nodes: 'Cognome (Anno)'."""
    authors = entry.get("authors", "")
    year = entry.get("year", "")

    if isinstance(authors, str):
        first_author = authors.split(",")[0].split(";")[0].strip()
    elif isinstance(authors, list):
        first_author = str(authors[0]).strip() if authors else ""
    else:
        first_author = str(authors)

    # Solo cognome (prima parola)
    surname = first_author.split()[-1] if first_author else ""
    if len(surname) > 16:
        surname = surname[:14] + "…"

    if surname and year:
        return f"{surname} ({year})"
    return surname or str(year) or "?"


def make_tooltip(entry: dict) -> str:
    """Full tooltip with all info."""
    authors = entry.get("authors", "")
    year = entry.get("year", "")
    title = entry.get("title", "Senza titolo")

    parts = []
    if title:
        parts.append(title)
    if authors:
        parts.append(f"Autori: {authors}")
    if year:
        parts.append(f"Anno: {year}")

    ai_topics = _get_topics_list(entry)
    if ai_topics:
        parts.append(f"Topics: {', '.join(ai_topics)}")

    return "\n".join(parts)


def _get_topics_list(entry: dict) -> list[str]:
    """Extract AI topics from an entry dict."""
    raw = entry.get("ai_topics", "")
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def transitive_reduction(edges: list[dict]) -> list[dict]:
    """Removes redundant edges (A->B) if there is an indirect path (A->...->B)."""
    adj: dict[str, set[str]] = {}
    for e in edges:
        u, v = e["source"], e["target"]
        adj.setdefault(u, set()).add(v)

    reduced_edges = []
    for e in edges:
        u, v = e["source"], e["target"]
        queue = [child for child in adj.get(u, set()) if child != v]
        visited = set(queue)

        found_indirect = False
        while queue:
            curr = queue.pop(0)
            if curr == v:
                found_indirect = True
                break
            for nxt in adj.get(curr, set()):
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(nxt)

        if not found_indirect:
            reduced_edges.append(e)

    return reduced_edges


def _build_node(entry: dict, node_type: str) -> dict:
    """Build a single node dict for GraphModel."""
    eid = entry.get("id", 0)
    ai_topics = _get_topics_list(entry)
    
    compact_lbl = make_compact_label(entry)
    title_lbl = entry.get("title", "Senza titolo")
    
    return {
        "id": f"doc_{eid}",
        "node_type": node_type,
        "label": compact_lbl,
        "compact_label": compact_lbl,
        "full_label": title_lbl,
        "tooltip": make_tooltip(entry),
        "year": entry.get("year", ""),
        "authors": entry.get("authors", ""),
        "title": entry.get("title", ""),
        "ai_topic": ai_topics[0] if ai_topics else "",
        "ai_topics": ai_topics,
    }


def generate_reference_graph_json(entry_id: int, linked_refs: list[int], db_model) -> dict:
    """DAG per una singola entry: root + referenze."""
    nodes: list[dict] = []
    edges: list[dict] = []

    all_ids = list(set([entry_id] + linked_refs))
    entries = db_model.get_entries_by_ids(all_ids)
    entries_map = {e["id"]: e for e in entries}

    if entry_id not in entries_map:
        return {"nodes": [], "edges": []}

    nodes.append(_build_node(entries_map[entry_id], "root"))

    for ref_id in linked_refs:
        if ref_id == entry_id:
            continue
        ref_entry = entries_map.get(ref_id)
        if not ref_entry:
            continue
        nodes.append(_build_node(ref_entry, "reference"))
        edges.append({
            "source": f"doc_{entry_id}",
            "target": f"doc_{ref_id}",
            "edge_type": "reference",
        })

    return {"nodes": nodes, "edges": transitive_reduction(edges)}


def generate_global_reference_graph_json(db_model, active_id: int | None = None) -> dict:
    """DAG globale di tutte le referenze nel database."""
    nodes: list[dict] = []
    edges: list[dict] = []
    included_ids: set[int] = set()

    all_entries = db_model.read_all_full()
    known_ids = {entry.get("id") for entry in all_entries if entry.get("id")}
    included_ids.update(known_ids)

    for entry in all_entries:
        entry_id = entry.get("id")
        if not entry_id:
            continue

        linked_json = entry.get("linked_references") or "[]"
        try:
            linked_refs = json.loads(linked_json)
        except Exception:
            linked_refs = []

        if linked_refs:
            for ref_id in linked_refs:
                if ref_id not in known_ids:
                    continue
                edges.append({
                    "source": f"doc_{entry_id}",
                    "target": f"doc_{ref_id}",
                    "edge_type": "reference",
                })

    for entry in all_entries:
        if entry["id"] in included_ids:
            node_type = "root" if active_id is not None and entry["id"] == active_id else "document"
            nodes.append(_build_node(entry, node_type))

    return {"nodes": nodes, "edges": transitive_reduction(edges)}