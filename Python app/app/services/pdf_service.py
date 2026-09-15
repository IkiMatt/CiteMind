"""Utilities for extracting text from PDF pages and isolating the bibliography section."""
from __future__ import annotations

import csv
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


def extract_embedded_images(pdf_path: str, output_dir: str | Path | None = None) -> list[dict]:
    """Extract unique embedded images and return their page and file metadata."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    destination = Path(output_dir) if output_dir else path.parent / ".citemind" / path.stem / "images"
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[dict] = []
    seen_xrefs: set[int] = set()

    with fitz.open(str(path)) as doc:
        for page_number, page in enumerate(doc, start=1):
            for image_index, image_info in enumerate(page.get_images(full=True), start=1):
                xref = int(image_info[0])
                if xref in seen_xrefs:
                    continue
                image = doc.extract_image(xref)
                extension = image.get("ext", "bin")
                output_path = destination / f"page_{page_number:04d}_image_{image_index:03d}.{extension}"
                output_path.write_bytes(image["image"])
                seen_xrefs.add(xref)
                extracted.append({
                    "page": page_number,
                    "file_path": str(output_path),
                    "xref": xref,
                    "width": image.get("width", 0),
                    "height": image.get("height", 0),
                    "extension": extension,
                })

    return extracted


def extract_tables(pdf_path: str, output_dir: str | Path | None = None) -> list[dict]:
    """Detect tables with PyMuPDF and save their extracted cells as CSV files."""
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    destination = Path(output_dir) if output_dir else path.parent / ".citemind" / path.stem / "tables"
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[dict] = []

    with fitz.open(str(path)) as doc:
        for page_number, page in enumerate(doc, start=1):
            finder = page.find_tables()
            for table_index, table in enumerate(finder.tables, start=1):
                rows = table.extract()
                if not rows:
                    continue
                output_path = destination / f"page_{page_number:04d}_table_{table_index:03d}.csv"
                with output_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
                    writer = csv.writer(csv_file)
                    writer.writerows(rows)
                extracted.append({
                    "page": page_number,
                    "file_path": str(output_path),
                    "rows": len(rows),
                    "columns": max((len(row) for row in rows), default=0),
                })

    return extracted
