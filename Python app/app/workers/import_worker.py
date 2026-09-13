"""
import_worker.py — QThread worker for running import pipeline in background.

Processes drop items sequentially, emitting progress signals for the UI.
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.services.import_pipeline import ImportPipeline, ImportResult, DropItem


class ImportWorker(QThread):
    """
    Background worker for the import pipeline.
    Processes a list of DropItems sequentially.

    Signals
    -------
    itemStarted : int, str
        (queue_index, status) emitted when a new item begins processing.
    itemCompleted : int, ImportResult
        (queue_index, result) emitted when an item finishes.
    allCompleted : (no args)
        Emitted when all items have been processed.
    """

    itemStarted = Signal(int, str)
    itemCompleted = Signal(int, object)
    allCompleted = Signal()

    def __init__(self, pipeline: ImportPipeline,
                 items: list[tuple[int, DropItem]],
                 parent=None):
        """
        Parameters
        ----------
        pipeline : ImportPipeline
            Configured import pipeline instance.
        items : list[tuple[int, DropItem]]
            List of (queue_index, DropItem) to process.
        """
        super().__init__(parent)
        self._pipeline = pipeline
        self._items = items
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        for queue_idx, drop_item in self._items:
            if self._is_cancelled:
                break
            try:
                # Emit parsing status
                self.itemStarted.emit(queue_idx, "parsing")

                result = self._pipeline.process(drop_item)
                self.itemCompleted.emit(queue_idx, result)

            except Exception as exc:
                error_result = ImportResult(error=str(exc), filename=drop_item.path or drop_item.value)
                self.itemCompleted.emit(queue_idx, error_result)

        self.allCompleted.emit()


class ClusterWorker(QThread):
    """
    Background worker for clustering papers.

    Signals
    -------
    finished : object
        Emitted with ClusterResult when done.
    error : str
        Emitted with error message on failure.
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, embeddings: dict, method: str = "auto",
                 min_cluster_size: int = 3, parent=None):
        super().__init__(parent)
        self._embeddings = embeddings
        self._method = method
        self._min_cluster_size = min_cluster_size

    def run(self):
        try:
            from app.graph.clustering import SemanticClusterEngine
            engine = SemanticClusterEngine()
            result = engine.cluster_papers(
                self._embeddings,
                method=self._method,
                min_cluster_size=self._min_cluster_size,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class MetricsWorker(QThread):
    """
    Background worker for computing graph metrics.

    Signals
    -------
    finished : object
        Emitted with {entry_id: PaperMetrics.to_dict()} when done.
    error : str
        Error message on failure.
    """

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, graph_model, parent=None):
        super().__init__(parent)
        self._gm = graph_model

    def run(self):
        try:
            from app.graph.metrics import GraphMetrics
            engine = GraphMetrics()
            metrics = engine.compute_all(self._gm)
            result = {eid: m.to_dict() for eid, m in metrics.items()}
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))


class EmbeddingWorker(QThread):
    """
    Background worker for generating embeddings via Ollama.

    Signals
    -------
    progress : int, int
        (current, total) progress counter.
    finished : object
        {entry_id: numpy_array} of generated embeddings.
    error : str
        Error message on failure.
    """

    progress = Signal(int, int)
    finished = Signal(object)
    error = Signal(str)

    def __init__(self, entries: list[dict], ollama_url: str,
                 model_name: str, parent=None):
        super().__init__(parent)
        self._entries = entries
        self._ollama_url = ollama_url
        self._model_name = model_name

    def run(self):
        import numpy as np
        import requests

        results = {}
        total = len(self._entries)

        for i, entry in enumerate(self._entries):
            self.progress.emit(i + 1, total)

            eid = entry.get("id")
            text = self._build_embedding_text(entry)
            if not text.strip():
                continue

            try:
                url = self._ollama_url
                if not url.startswith("http"):
                    url = "http://" + url

                resp = requests.post(
                    f"{url}/api/embed",
                    json={
                        "model": self._model_name,
                        "input": text,
                    },
                    timeout=60,
                    proxies={"http": None, "https": None}
                )
                resp.raise_for_status()
                data = resp.json()

                # Ollama returns {"embeddings": [[...], ...]} or {"embedding": [...]}
                if "embeddings" in data and data["embeddings"]:
                    vec = np.array(data["embeddings"][0], dtype=np.float32)
                elif "embedding" in data:
                    vec = np.array(data["embedding"], dtype=np.float32)
                else:
                    continue

                results[eid] = vec

            except Exception:
                continue  # Skip failed entries, don't abort the batch

        self.finished.emit(results)

    @staticmethod
    def _build_embedding_text(entry: dict) -> str:
        """Build text to embed from entry fields."""
        parts = []
        title = entry.get("title", "")
        if title:
            parts.append(title)
        authors = entry.get("authors", "")
        if authors:
            parts.append(f"Authors: {authors}")
        journal = entry.get("journal", "")
        if journal:
            parts.append(f"Journal: {journal}")
        notes = entry.get("notes", "")
        if notes:
            parts.append(notes[:500])

        # AI-generated topics/summary
        import json
        ai_notes = entry.get("ai_notes", "")
        if ai_notes:
            try:
                ai_data = json.loads(ai_notes)
                summary = ai_data.get("summary_en", "") or ai_data.get("summary_it", "")
                if summary:
                    parts.append(summary)
            except Exception:
                pass

        ai_topics = entry.get("ai_topics", "")
        if ai_topics:
            try:
                topics = json.loads(ai_topics)
                if isinstance(topics, list):
                    parts.append("Topics: " + ", ".join(topics))
            except Exception:
                pass

        return " ".join(parts)
