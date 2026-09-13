"""
graph_cache.py — Persist and reload the knowledge graph as a JSON sidecar file.

The cache file sits next to the SQLite database:
    bibliography.db  →  bibliography.graph.json

Invalidation is timestamp-based: if any entry was modified after the cache
was written, the cache is considered stale.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from app.graph.graph_model import GraphModel


class GraphCache:
    """Read / write / validate a cached graph JSON file."""

    SUFFIX = ".graph.json"

    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._cache_path = self._db_path.with_suffix(self.SUFFIX)

    @property
    def cache_path(self) -> Path:
        return self._cache_path

    # ── Write ─────────────────────────────────────────────────────────────
    def save(self, graph_model: GraphModel) -> None:
        """Serialize the graph model to the sidecar JSON file."""
        payload = {
            "version": 1,
            "timestamp": time.time(),
            "graph": graph_model.to_json(),
        }
        try:
            self._cache_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass  # non-critical — graph will just be rebuilt next time

    # ── Read ──────────────────────────────────────────────────────────────
    def load(self) -> GraphModel | None:
        """Load the cached graph.  Returns None if cache is missing or corrupt."""
        if not self._cache_path.exists():
            return None
        try:
            raw = self._cache_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            return GraphModel.from_json(payload["graph"])
        except (OSError, json.JSONDecodeError, KeyError):
            return None

    # ── Validation ────────────────────────────────────────────────────────
    def is_valid(self, latest_modified_at: str | None = None) -> bool:
        """
        Check if the cache exists and is not stale.

        Parameters
        ----------
        latest_modified_at : str | None
            ISO-formatted timestamp of the most recently modified entry.
            If None, the cache is considered stale.
        """
        if not self._cache_path.exists():
            return False
        if latest_modified_at is None:
            return False

        try:
            raw = self._cache_path.read_text(encoding="utf-8")
            payload = json.loads(raw)
            cache_ts = payload.get("timestamp", 0)
        except (OSError, json.JSONDecodeError):
            return False

        # Compare cache timestamp vs latest entry modification
        # Parse ISO datetime to epoch (approximate comparison)
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(latest_modified_at)
            entry_ts = dt.timestamp()
        except (ValueError, TypeError):
            return False

        return cache_ts >= entry_ts

    def invalidate(self) -> None:
        """Delete the cache file."""
        try:
            if self._cache_path.exists():
                self._cache_path.unlink()
        except OSError:
            pass
