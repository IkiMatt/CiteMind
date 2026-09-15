"""
ai_worker.py — Background worker that extracts PDF text and calls
a local Ollama instance to generate multilingual summaries and key points.

Requires Ollama running locally (default: http://localhost:11434).
Recommended model: gemma4 (fast, multilingual, ~3GB).

Signals:
    finished(dict)  — emitted with the parsed JSON result
    error(str)      — emitted on any failure
"""
import json
from typing import Any

import pymupdf as fitz
import requests
from PySide6.QtCore import QThread, Signal

from app.services.pdf_service import extract_last_pages_text


# Maximum characters to send to the model (to stay within context limits)
_MAX_CHARS = 12_000
# Pages to scan for text extraction
_MAX_PAGES = 10


def _parse_logical_ranges(pages_str: str) -> list[tuple[int, int]]:
    """Parse '12-34, 45' into a list of ranges [(12, 34), (45, 45)]."""
    if not pages_str: return []
    ranges = []
    parts = pages_str.replace(" ", "").split(",")
    for part in parts:
        if "-" in part:
            try:
                start, end = part.split("-")
                ranges.append((int(start), int(end)))
            except ValueError:
                pass
        else:
            try:
                num = int(part)
                ranges.append((num, num))
            except ValueError:
                pass
    return ranges

def extract_pdf_text(pdf_path: str, max_chars: int = _MAX_CHARS, pages_str: str = "") -> str:
    """Extract text from a PDF, up to max_chars characters."""
    text_parts: list[str] = []
    total = 0
    
    def _find_physical_page(doc, logical_num: int) -> int:
        for i in range(len(doc)):
            if hasattr(doc[i], "get_label") and doc[i].get_label() == str(logical_num):
                return i
        
        def check_page_has_number(page_idx, num):
            if page_idx < 0 or page_idx >= len(doc): return False
            text = doc[page_idx].get_text("text").strip()
            if not text: return False
            lines = [line.strip() for line in text.split("\n") if line.strip()]
            corners = lines[:4] + lines[-4:]
            num_str = str(num)
            for line in corners:
                if line == num_str: return True
                if num_str in line:
                    digits = ''.join(filter(str.isdigit, line))
                    if digits == num_str: return True
            return False

        for offset in range(0, 3):
            target_num = logical_num + offset
            for i in range(len(doc)):
                if check_page_has_number(i, target_num):
                    return max(0, i - offset)
                    
        return min(len(doc) - 1, max(0, logical_num - 1))

    try:
        with fitz.open(pdf_path) as doc:
            doc_len = len(doc)
            pages_to_read = []
            
            if pages_str:
                ranges = _parse_logical_ranges(pages_str)
                for start_log, end_log in ranges:
                    start_phys = _find_physical_page(doc, start_log)
                    end_phys = start_phys + (end_log - start_log)
                    for p in range(start_phys, end_phys + 1):
                        if 0 <= p < doc_len and p not in pages_to_read:
                            pages_to_read.append(p)
            else:
                pages_to_read = list(range(min(doc_len, _MAX_PAGES)))

            for i in pages_to_read:
                page_text = doc[i].get_text("text")
                text_parts.append(page_text)
                total += len(page_text)
                if total >= max_chars:
                    break
    except Exception as exc:
        raise RuntimeError(f"Impossibile leggere il PDF: {exc}") from exc

    full = "\n".join(text_parts)
    return full[:max_chars]


_PROMPT_TEMPLATE = """\
You are an expert academic librarian and multilingual summarizer.
Below is the text extracted from an academic PDF.

Your task: produce a structured JSON object (no markdown, raw JSON only) with the following keys:
  "summary_en"      : a concise 3-5 sentence summary in English
  "summary_it"      : a concise 3-5 sentence summary in Italian
  "summary_fr"      : a concise 3-5 sentence summary in French
  "summary_de"      : a concise 3-5 sentence summary in German
  "key_points_en"   : a JSON array of 4-6 key bullet points in English
  "key_points_it"   : a JSON array of 4-6 key bullet points in Italian
  "key_points_fr"   : a JSON array of 4-6 key bullet points in French
  "key_points_de"   : a JSON array of 4-6 key bullet points in German
  "ai_topics"       : an array of exactly 5 concise graph-ready topics in English, each 1 to 3 words max, entity-centric, specific nouns or named entities only, no adjectives, no broad filler, no metadata, no author names.

STRICT TOPIC RULES:
- Each topic must be extremely concise: 1 to 3 words maximum.
- Use nouns, concepts, or named entities only.
- Avoid adjectives, broad fillers, metadata, and names.
- Prefer precise graph hubs such as "Machine Learning", "Supply Chain", "Climate Change".
- Ignore author names, publisher names, headers, page numbers, and acknowledgments.
- Output exactly 5 items and keep them suitable for UI tags/chips.

Return ONLY the raw JSON object, no extra text, no markdown fences.

PDF TEXT:
\"\"\"
{text}
\"\"\"
"""

REFERENCE_EXTRACTION_SYSTEM_PROMPT = """You are a strict bibliographic extraction engine.

Task:
- Read the raw extracted text from the end of an academic PDF.
- Identify only real references that are likely part of the bibliography or cited works section.
- Return ONLY a JSON array. Do not wrap it in markdown or prose.
- Each element must be an object with exactly these keys:
  {
    "title": "string",
    "authors": ["string", "string"],
    "year": 2020,
    "source": "string or null"
  }

Hard rules:
- Prefer exact bibliographic titles from the text; do not invent missing metadata.
- If a title is uncertain, omit the reference rather than hallucinating.
- Do not include page numbers, journal headers, captions, figure text, footnotes, or acknowledgements.
- Replace author names with a clean list of strings in the form "Surname, Initials" or "First Last".
- Use year as an integer when explicit; otherwise use null.
- Use source as a short label such as journal, book, conference, or report when clearly available; otherwise use null.
- Remove duplicates.
- Output valid JSON, UTF-8 encoded, with double quotes around keys and string values.
- Return only the JSON array and nothing else.
"""


def _coerce_reference_list(payload: Any) -> list[dict]:
    """Normalize various potential LLM responses into a flat list of reference dicts."""
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("references") or payload.get("items") or []
    else:
        items = []

    normalized: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        authors = item.get("authors") or []
        if isinstance(authors, str):
            authors = [p.strip() for p in authors.split(";") if p.strip()]
        authors = [str(a).strip() for a in authors if str(a).strip()]
        year = item.get("year")
        try:
            if year not in (None, "", "null"):
                year = int(year)
        except (TypeError, ValueError):
            year = None
        ref = {
            "title": title,
            "authors": authors,
            "year": year,
            "source": str(item.get("source") or "").strip() or None,
        }
        normalized.append(ref)
    return normalized


class AiNotesWorker(QThread):
    """Background thread: extract PDF text → call AI provider → return notes."""

    finished = Signal(object)   # parsed result dict
    error    = Signal(str)      # error message

    def __init__(self, pdf_path: str, ollama_url: str, model_name: str, pages_str: str = "", parent=None):
        super().__init__(parent)
        self._pdf_path    = pdf_path
        self._base_url    = ollama_url.rstrip("/")
        self._model_name  = model_name
        self._pages_str   = pages_str
        from app.dialogs.ai_settings_dialog import AiSettingsDialog
        
        # We need to get provider and API key
        # For backward compatibility, AiSettingsDialog will provide these
        self._api_key = AiSettingsDialog.get_api_key()
        
        # Determine provider (default to ollama if not implemented yet in dialog)
        if hasattr(AiSettingsDialog, "get_ai_provider"):
            self._provider = AiSettingsDialog.get_ai_provider()
        else:
            self._provider = "Ollama"
            
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled: return
        try:
            # 1. Extract text
            text = extract_pdf_text(self._pdf_path, pages_str=self._pages_str)
            if not text.strip():
                self.error.emit(
                    "Il PDF non contiene testo estraibile (potrebbe essere uno scan)."
                )
                return

            if self._is_cancelled: return
            
            # 2. Build prompt
            prompt = _PROMPT_TEMPLATE.format(text=text)
            
            # 3. Call specific provider
            provider = self._provider.lower()
            if provider == "openai":
                result = self._call_openai(prompt)
            elif provider == "anthropic":
                result = self._call_anthropic(prompt)
            elif provider == "gemini":
                result = self._call_gemini(prompt)
            else:
                result = self._call_ollama(prompt)
                
            self.finished.emit(result)

        except json.JSONDecodeError as exc:
            self.error.emit(f"Risposta non valida dal modello (JSON malformato): {exc}")
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            body   = exc.response.text[:300] if exc.response is not None else ""
            if status == 401:
                self.error.emit(
                    "Errore 401: Non autorizzato.\n\n"
                    "L'API Key inserita nelle impostazioni non è corretta per questo provider."
                )
            else:
                self.error.emit(f"Errore API (HTTP {status}): {body}")
        except requests.exceptions.ConnectionError:
            self.error.emit("Impossibile connettersi al server AI. Controlla la tua connessione o l'URL.")
        except requests.exceptions.Timeout:
            self.error.emit("Timeout: Il server AI ha impiegato troppo tempo per rispondere.")
        except requests.exceptions.RequestException as exc:
            self.error.emit(f"Errore di comunicazione: {str(exc)}")
        except Exception as exc:
            self.error.emit(f"Errore imprevisto: {str(exc)}")

    def _call_ollama(self, prompt: str) -> dict:
        base_url = self._base_url or "http://localhost:11434"
        if not base_url.startswith(("http://", "https://")):
            base_url = "http://" + base_url

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": self._model_name or "llama3.2",
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3},
            },
            headers=headers,
            timeout=300,
        )
        response.raise_for_status()
        return self._parse_json_response(response.json().get("response", ""))

    def _call_openai(self, prompt: str) -> dict:
        url = self._base_url or "https://api.openai.com/v1/chat/completions"
        if not url.startswith("http"):
            url = "https://api.openai.com/v1/chat/completions"
        response = requests.post(
            url,
            json={
                "model": self._model_name or "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.3,
            },
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            timeout=120,
        )
        response.raise_for_status()
        raw = response.json()["choices"][0]["message"]["content"]
        return self._parse_json_response(raw)

    def _call_anthropic(self, prompt: str) -> dict:
        url = self._base_url or "https://api.anthropic.com/v1/messages"
        if not url.startswith("http"):
            url = "https://api.anthropic.com/v1/messages"
        response = requests.post(
            url,
            json={
                "model": self._model_name or "claude-3-haiku-20240307",
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt + "\n\nProvide ONLY valid JSON output."}],
                "temperature": 0.3,
            },
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            timeout=120,
        )
        response.raise_for_status()
        return self._parse_json_response(response.json()["content"][0]["text"])

    def _call_gemini(self, prompt: str) -> dict:
        model = self._model_name or "gemini-1.5-flash"
        url = self._base_url or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        if not url.startswith("http"):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        response = requests.post(
            url,
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"},
            },
            headers={"Content-Type": "application/json"},
            params={"key": self._api_key},
            timeout=120,
        )
        response.raise_for_status()
        return self._parse_json_response(response.json()["candidates"][0]["content"]["parts"][0]["text"])

    @staticmethod
    def _parse_json_response(raw: str) -> dict:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```", 1)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            if "```" in raw:
                raw = raw.split("```", 1)[0]
        return json.loads(raw.strip())


class ReferenceExtractionWorker(QThread):
    """Background worker that extracts bibliography references from the last pages of a PDF."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, pdf_path: str, ollama_url: str, model_name: str, last_n_pages: int = 5, parent=None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._base_url = (ollama_url or "http://localhost:11434").strip().rstrip("/")
        self._model_name = (model_name or "llama3.2").strip()
        self._last_n_pages = max(1, int(last_n_pages))
        self._api_key = ""
        try:
            from app.dialogs.ai_settings_dialog import AiSettingsDialog
            self._api_key = AiSettingsDialog.get_api_key()
        except Exception:
            self._api_key = ""
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled:
            return
        try:
            text = extract_last_pages_text(self._pdf_path, last_n_pages=self._last_n_pages, max_chars=16_000)
            if not text.strip():
                self.error.emit("Nessun testo rilevato nelle ultime pagine del PDF.")
                return

            payload = self._call_ollama(text)
            self.finished.emit(payload)
        except Exception as exc:  # pragma: no cover - worker-level error propagation
            self.error.emit(str(exc))

    def _call_ollama(self, raw_text: str) -> list[dict]:
        """Call Ollama with a strict system prompt and parse the result as JSON."""
        base_url = self._base_url
        if not base_url.startswith(("http://", "https://")):
            base_url = "http://" + base_url

        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        response = requests.post(
            f"{base_url}/api/generate",
            json={
                "model": self._model_name,
                "system": REFERENCE_EXTRACTION_SYSTEM_PROMPT,
                "prompt": raw_text,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.0, "num_predict": 4096},
            },
            headers=headers,
            timeout=300,
        )
        response.raise_for_status()
        raw = response.json().get("response", "")
        return self._parse_json_response(raw)

    @staticmethod
    def _parse_json_response(raw: str) -> list[dict]:
        """Parse JSON from a model response and normalize it to bibliography entries."""
        payload = raw.strip()
        if not payload:
            return []

        if payload.startswith("```"):
            payload = payload.strip("`")
            if payload.lower().startswith("json"):
                payload = payload[4:].lstrip()

        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Risposta JSON non valida da Ollama: {exc}") from exc

        refs = _coerce_reference_list(parsed)
        deduped: list[dict] = []
        seen: set[str] = set()
        for ref in refs:
            key = (ref.get("title") or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                deduped.append(ref)
        return deduped

    def _call_openai(self, prompt: str) -> dict:
        url = self._base_url or "https://api.openai.com/v1/chat/completions"
        if not url.startswith("http"):
            url = "https://api.openai.com/v1/chat/completions"
            
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self._model_name or "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        return self._parse_json_response(raw)
        
    def _call_anthropic(self, prompt: str) -> dict:
        url = self._base_url or "https://api.anthropic.com/v1/messages"
        if not url.startswith("http"):
            url = "https://api.anthropic.com/v1/messages"
            
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json"
        }
        
        # Anthropic suggests prefilling json response
        prompt = prompt + "\n\nProvide ONLY valid JSON output."
        
        payload = {
            "model": self._model_name or "claude-3-haiku-20240307",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
        }
        
        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        raw = resp.json()["content"][0]["text"]
        return self._parse_json_response(raw)
        
    def _call_gemini(self, prompt: str) -> dict:
        model = self._model_name or "gemini-1.5-flash"
        url = self._base_url or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        if not url.startswith("http"):
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            
        params = {"key": self._api_key}
        headers = {"Content-Type": "application/json"}
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "responseMimeType": "application/json"
            }
        }
        
        resp = requests.post(url, json=payload, headers=headers, params=params, timeout=120)
        resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
        return self._parse_json_response(raw)

    def _parse_json_response(self, raw: str) -> dict:
        raw = raw.strip()
        # Strip possible markdown fences
        if raw.startswith("```"):
            raw = raw.split("```", 1)[1]
            if raw.startswith("json"):
                raw = raw[4:]
            
            # Find the closing fence
            if "```" in raw:
                raw = raw.split("```")[0]
                
            raw = raw.strip()
            
        return json.loads(raw)
