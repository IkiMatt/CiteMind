"""Utilities for extracting text from PDF pages and isolating the bibliography section."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import fitz


def _iter_tail_pages(doc: fitz.Document, last_n_pages: int) -> list[int]:
    """Return the last N physical pages in a PDF, preserving order."""
    if last_n_pages <= 0:
        return []
    total_pages = len(doc)
    if total_pages <= last_n_pages:
        return list(range(total_pages))
    start = total_pages - last_n_pages
    return list(range(start, total_pages))


def extract_last_pages_text(pdf_path: str, last_n_pages: int = 5, max_chars: int = 15000) -> str:
    """Extract text only from the last pages of a PDF to focus on the bibliography section."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    text_parts: list[str] = []
    total_chars = 0

    with fitz.open(str(path)) as doc:
        for page_index in _iter_tail_pages(doc, last_n_pages):
            page = doc[page_index]
            page_text = page.get_text("text", sort=True)
            if not page_text.strip():
                continue
            text_parts.append(page_text)
            total_chars += len(page_text)
            if total_chars >= max_chars:
                break

    return "\n".join(text_parts)[:max_chars].strip()


def extract_reference_candidates(pdf_path: str, last_n_pages: int = 5, max_chars: int = 15000) -> list[dict]:
    """Convenience wrapper: raw bibliography text → list of candidates for matching."""
    text = extract_last_pages_text(pdf_path, last_n_pages=last_n_pages, max_chars=max_chars)
    if not text:
        return []
    return [{"title": text[:200], "authors": [], "year": None, "source": "pdf_tail"}]
