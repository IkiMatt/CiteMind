"""
graph_worker.py — QThread workers for building the knowledge graph off the UI thread.

GraphBuildWorker:  entries → keywords → graph → cache → finished
EmbeddingWorker:   entries → Ollama /api/embed → semantic edges → finished  (Phase 2)
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.graph.graph_model import GraphModel
from app.graph.graph_builder import GraphBuilder
from app.graph.graph_cache import GraphCache
from app.graph.keyword_extractor import build_fallback_topic_assignments, filter_academic_keywords


def _coerce_ollama_url(raw_url: str | None) -> str:
    """Normalize the Ollama URL and ensure it has a scheme."""
    url = (raw_url or "http://localhost:11434").strip()
    if not url:
        url = "http://localhost:11434"
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    return url.rstrip("/")


def _format_ollama_error(exc: Exception, *, model_name: str | None = None) -> str:
    """Convert raw Ollama exceptions into a readable, actionable message."""
    try:
        import requests
    except Exception:
        requests = None

    if requests is not None and isinstance(exc, requests.exceptions.HTTPError):
        response = exc.response
        status = getattr(response, "status_code", "?")
        body = ""
        if response is not None:
            try:
                body = str(response.text or "").strip()
            except Exception:
                body = ""
        if status == 401:
            return (
                "Errore 401: Non autorizzato.\n\n"
                "Controlla la API Key nelle Impostazioni AI o usa un server locale senza chiave."
            )
        if status == 404:
            if model_name:
                return f"Model '{model_name}' not found.\nInstall it with: ollama pull {model_name}"
            return "Model not found in Ollama.\nInstall a model with: ollama pull <model-name>"
        if body:
            return f"Ollama HTTP {status}: {body[:300]}"
        return f"Ollama HTTP {status}: nessuna risposta dettagliata dal server."

    if requests is not None and isinstance(exc, requests.exceptions.RequestException):
        return f"Ollama non raggiungibile: {exc}"

    return f"Ollama error: {exc}"


class GraphBuildWorker(QThread):
    """
    Background thread that builds the full knowledge graph.

    Signals
    -------
    finished : object
        Serialized graph JSON (ready for GraphModel.from_json).
    progress : int
        Percentage 0-100.
    error : str
        Error message on failure.
    """

    finished = Signal(object)
    progress = Signal(int)
    error    = Signal(str)

    def __init__(self, entries: list[dict], db_path: Path, parent=None, keyword_limit: int = 50):
        super().__init__(parent)
        self._entries = entries
        self._db_path = db_path
        self._keyword_limit = max(1, int(keyword_limit))
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled: return
        try:
            self.progress.emit(10)

            builder = GraphBuilder(self._entries, keyword_limit=self._keyword_limit)
            self.progress.emit(30)

            graph_model = builder.build()
            self.progress.emit(70)

            # Cache the result
            cache = GraphCache(self._db_path)
            cache.save(graph_model)
            self.progress.emit(90)

            self.finished.emit(graph_model.to_json())
            self.progress.emit(100)

        except Exception as exc:
            self.error.emit(str(exc))


class EmbeddingWorker(QThread):
    """
    Background thread that computes embeddings via Ollama and adds
    semantic_similarity edges to an existing graph.

    Signals
    -------
    finished : object
        Updated serialized graph JSON with semantic edges added.
    progress : int
        Percentage 0-100.
    error : str
        Error message on failure.
    """

    finished = Signal(object)
    progress = Signal(int)
    error    = Signal(str)

    def __init__(
        self,
        entries: list[dict],
        graph_json: dict,
        ollama_url: str,
        model_name: str,
        db_path: Path,
        parent=None,
    ):
        super().__init__(parent)
        self._entries    = entries
        self._graph_json = graph_json
        self._ollama_url = _coerce_ollama_url(ollama_url)
        self._model_name = (model_name or "").strip() or "llama3.2"
        self._db_path    = db_path
        from app.dialogs.ai_settings_dialog import AiSettingsDialog
        self._api_key    = AiSettingsDialog.get_api_key()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def _make_text(self, entry: dict) -> str:
        """Build a text representation of the entry for embedding."""
        import os
        import json
        from app.ai_worker import extract_pdf_text
        
        parts = []
        if entry.get("title"):
            parts.append(entry["title"])
        if entry.get("authors"):
            parts.append(entry["authors"])
            
        ai_notes = entry.get("ai_notes")
        if ai_notes:
            try:
                notes_dict = json.loads(ai_notes)
                summary = notes_dict.get("summary_it") or notes_dict.get("summary_en")
                if summary:
                    parts.append(summary)
            except Exception:
                pass
                
        if entry.get("notes"):
            parts.append(entry["notes"])
            
        pdf_path = entry.get("pdf_path")
        if pdf_path and os.path.exists(pdf_path):
            try:
                pdf_text = extract_pdf_text(pdf_path, max_chars=2000)
                if pdf_text:
                    parts.append(pdf_text)
            except Exception:
                pass
                
        return "\n".join(parts)[:3000].strip()

    def run(self):
        if self._is_cancelled: return
        import requests
        import numpy as np
        from app.model import EntryModel

        try:
            url = _coerce_ollama_url(self._ollama_url)

            db = EntryModel(self._db_path)
            missing_ids = db.get_entries_without_embeddings()

            # Only check Ollama if we actually need to compute new embeddings
            if missing_ids:
                try:
                    headers = {}
                    if self._api_key:
                        headers["Authorization"] = f"Bearer {self._api_key}"

                    r = requests.get(f"{url}/api/tags", headers=headers, timeout=5)
                    r.raise_for_status()
                except Exception as exc:
                    self.error.emit(f"Ollama not reachable: {exc}")
                    return

            self.progress.emit(5)

            # Compute and save missing embeddings
            if missing_ids:
                entries_to_embed = [e for e in self._entries if e.get("id") in missing_ids]
                total = len(entries_to_embed)
                for idx, entry in enumerate(entries_to_embed):
                    if self._is_cancelled: return
                    eid = entry.get("id")
                    if eid is None:
                        continue
                    text = self._make_text(entry)
                    if not text.strip():
                        continue

                    try:
                        resp = requests.post(
                            f"{url}/api/embed",
                            json={
                                "model": self._model_name,
                                "input": text,
                            },
                            headers=headers,
                            timeout=60,
                            proxies={"http": None, "https": None},
                        )
                        resp.raise_for_status()
                        data = resp.json()
                        
                        vec = None
                        if "embeddings" in data and data["embeddings"]:
                            vec = np.array(data["embeddings"][0], dtype=np.float32)
                        elif "embedding" in data:
                            vec = np.array(data["embedding"], dtype=np.float32)
                            
                        if vec is not None:
                            db.save_embedding(eid, vec.tobytes(), len(vec), self._model_name)
                    except requests.exceptions.HTTPError as e:
                        if e.response is not None and e.response.status_code == 401:
                            self.error.emit("Errore 401: Non autorizzato. Controlla l'API Key nelle Impostazioni AI.")
                            break
                        continue  # skip this entry, don't fail the whole batch
                    except Exception:
                        continue  # skip this entry, don't fail the whole batch

                    pct = int(5 + 85 * (idx + 1) / max(total, 1))
                    self.progress.emit(min(pct, 90))

            self.progress.emit(90)

            # Load ALL embeddings from the DB
            raw_embeds = db.get_all_embeddings()
            all_embeddings = {}
            if raw_embeds:
                for eid, blob, dim in raw_embeds:
                    all_embeddings[eid] = np.frombuffer(blob, dtype=np.float32)

            # Rebuild graph model and add semantic edges
            gm = GraphModel.from_json(self._graph_json)
            if all_embeddings:
                GraphBuilder.add_semantic_edges(gm, all_embeddings)
                gm.detect_clusters()  # re-cluster with new edges

            # Save updated cache
            cache = GraphCache(self._db_path)
            cache.save(gm)

            self.finished.emit(gm.to_json())
            self.progress.emit(100)

        except Exception as exc:
            self.error.emit(str(exc))


# ── Prompt for LLM topic extraction ──────────────────────────────────────────
_TOPIC_PROMPT = """\
You are an expert academic librarian and research analyst.

Below is a numbered list of academic articles (ID, authors, title).
Your task is to assign every article a small set of useful academic topics, following a clear hierarchy:

1) Primary discipline: the main field of the article, such as archaeology, art, history, literature, informatics, etc.
2) Optional sub-discipline: only if an additional field is clearly relevant to the article, such as landscape archaeology or digital archaeology.
3) Article-specific topic(s): one or two concrete research themes tied to the article itself.

Rules:
- Every article MUST receive at least 1 topic and at most 3 topics.
- Use English for topic names only; if the article is in Italian, translate to English.
- Merge equivalent terms across languages and variants so duplicates do not appear.
- Avoid generic labels such as "analysis", "study", "method", "data", "model", "research" unless they are clearly part of a more specific phrase.
- Prefer meaningful academic concepts over empty labels.
- The main discipline should always be explicit whenever possible.
- Use a hierarchy like: "Archaeology", "Digital Archaeology", "Roman Settlement Patterns".
- Topics should be broad enough to group multiple articles, but specific enough to remain informative.
- Return ONLY raw JSON, no markdown fences, no extra text.

Output format (strict JSON):
{{
  "topics": ["Topic A", "Topic B", ...],
  "assignments": {{
    "1": ["Topic A", "Topic B"],
    "2": ["Topic C"],
    ...
  }}
}}

ARTICLES:
{articles}
"""


class TopicExtractionWorker(QThread):
    """
    Background thread that uses Ollama to extract a minimal set of
    thematic topics from all articles and assign each article to its topics.

    This produces curated keywords that result in clean, meaningful clusters
    instead of the noisy TF-IDF approach.

    Signals
    -------
    finished : object
        ``{"topics": [...], "assignments": {doc_id: [topics]}}``
    progress : int
        Percentage 0-100.
    error : str
        Error message on failure.
    """

    finished = Signal(object)
    progress = Signal(int)
    error    = Signal(str)

    def __init__(
        self,
        entries: list[dict],
        ollama_url: str,
        model_name: str,
        db_path: Path,
        parent=None,
        keyword_limit: int = 50,
    ):
        super().__init__(parent)
        self._entries    = entries
        self._ollama_url = _coerce_ollama_url(ollama_url)
        self._model_name = (model_name or "").strip() or "llama3.2"
        self._db_path    = db_path
        self._keyword_limit = max(1, int(keyword_limit))
        from app.dialogs.ai_settings_dialog import AiSettingsDialog
        self._api_key    = AiSettingsDialog.get_api_key()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled: return
        import json
        import requests

        def fallback_graph() -> None:
            builder = GraphBuilder(self._entries, keyword_limit=self._keyword_limit)
            graph_model = builder.build()
            cache = GraphCache(self._db_path)
            cache.save(graph_model)
            self.finished.emit(graph_model.to_json())
            self.progress.emit(100)

        try:
            url = _coerce_ollama_url(self._ollama_url)

            # 1. Check Ollama reachable
            try:
                headers = {}
                if self._api_key:
                    headers["Authorization"] = f"Bearer {self._api_key}"

                r = requests.get(
                    f"{url}/api/tags",
                    headers=headers,
                    timeout=5,
                    proxies={"http": None, "https": None},
                )
                r.raise_for_status()
            except Exception as exc:
                fallback_graph()
                return

            self.progress.emit(10)

            # 2. Build the article list for the prompt
            lines = []
            valid_ids = []
            for entry in self._entries:
                if self._is_cancelled: return
                eid = entry.get("id")
                if eid is None:
                    continue
                authors = entry.get("authors", "").strip() or "Unknown"
                title = entry.get("title", "").strip() or "(untitled)"
                lines.append(f"{eid}. {authors} — {title}")
                valid_ids.append(eid)

            if not lines:
                self.error.emit("No entries to analyze.")
                return

            # Keep prompts compact and consistent: too much context makes the model
            # produce noisy, generic topics and also slows the whole graph pipeline.
            BATCH_SIZE = 25
            all_topics: set[str] = set()
            all_assignments: dict[str, list[str]] = {}

            batches = [lines[i:i + BATCH_SIZE] for i in range(0, len(lines), BATCH_SIZE)]

            for batch_idx, batch_lines in enumerate(batches):
                article_text = "\n".join(batch_lines)
                prompt = _TOPIC_PROMPT.format(articles=article_text)

                self.progress.emit(10 + int(70 * batch_idx / max(len(batches), 1)))

                # 3. Call Ollama
                payload = {
                    "model":  self._model_name,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 2048,
                    },
                }
                try:
                    resp = requests.post(
                        f"{url}/api/generate",
                        json=payload,
                        headers=headers,
                        timeout=300,
                        proxies={"http": None, "https": None},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except requests.exceptions.HTTPError as exc:
                    fallback_graph()
                    return
                except Exception as exc:
                    fallback_graph()
                    return

                raw = data.get("response", "").strip()

                # Strip markdown fences if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                    raw = raw.strip()

                result = json.loads(raw)

                # Merge topics and keep them concise: broad topics are useful only when
                # they are few enough to create meaningful document-document links.
                batch_topics = result.get("topics", [])
                cleaned_topics = []
                seen_topics = set()
                for topic in batch_topics:
                    text = str(topic).strip()
                    if not text:
                        continue
                    norm = text.lower()
                    if norm in seen_topics:
                        continue
                    seen_topics.add(norm)
                    cleaned_topics.append(text)
                cleaned_topics = filter_academic_keywords(cleaned_topics)
                all_topics.update(cleaned_topics)

                # Merge assignments
                batch_assignments = result.get("assignments", {})
                for doc_id_str, topics in batch_assignments.items():
                    cleaned = []
                    seen = set()
                    for topic in topics:
                        text = str(topic).strip()
                        if not text:
                            continue
                        norm = text.lower()
                        if norm in seen:
                            continue
                        seen.add(norm)
                        cleaned.append(text)
                    all_assignments[doc_id_str] = filter_academic_keywords(cleaned)[:min(self._keyword_limit, 10)]

            self.progress.emit(85)

            # 4. Convert to the format expected by GraphBuilder:
            #    {entry_id: [keyword_strings]}
            keywords: dict[int, list[str]] = {}
            fallback_topics = build_fallback_topic_assignments(self._entries, max_topics=3)
            for eid in valid_ids:
                eid_str = str(eid)
                if eid_str in all_assignments:
                    keywords[eid] = all_assignments[eid_str][:min(self._keyword_limit, 10)]
                else:
                    keywords[eid] = fallback_topics.get(eid, [])

                if not keywords[eid]:
                    keywords[eid] = fallback_topics.get(eid, [])

            # 5. Rebuild graph with LLM-curated topics, but keep the graph lightweight:
            #    few topics per article and a stricter overlap threshold prevents the
            #    giant "spine" effect caused by broad, low-similarity connections.
            builder = GraphBuilder(self._entries, keywords=keywords,
                                   keyword_overlap_threshold=0.35,
                                   keyword_limit=self._keyword_limit)
            graph_model = builder.build()

            # 6. Cache
            cache = GraphCache(self._db_path)
            cache.save(graph_model)

            self.progress.emit(95)

            self.finished.emit(graph_model.to_json())
            self.progress.emit(100)

        except json.JSONDecodeError as exc:
            fallback_graph()
        except requests.exceptions.HTTPError as exc:
            self.error.emit(_format_ollama_error(exc, model_name=self._model_name))
        except Exception as exc:
            self.error.emit(_format_ollama_error(exc, model_name=self._model_name))
