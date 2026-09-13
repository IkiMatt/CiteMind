"""
ris_parser.py — Parse RIS (Research Information Systems) files.

RIS is a tagged format used by Zotero, Mendeley, Web of Science, etc.
Each record starts with TY and ends with ER.
"""
from __future__ import annotations

import re
from pathlib import Path


# ── RIS tag → CiteMind field mapping ──────────────────────────────────────────
_RIS_MAP = {
    "TI": "title",
    "T1": "title",
    "AU": "authors",
    "A1": "authors",
    "PY": "year",
    "Y1": "year",
    "DA": "year",
    "JO": "journal",
    "JF": "journal",
    "T2": "journal",
    "VL": "volume",
    "IS": "issue",
    "SP": "_start_page",
    "EP": "_end_page",
    "DO": "doi",
    "UR": "url",
    "PB": "publisher",
    "AB": "notes",
    "N2": "notes",
    "KW": "_keyword",
    "SN": "_issn",
    "LA": "_language",
    "CY": "location",
    "ET": "edition",
    "M1": "_misc1",
}

# ── RIS type → CiteMind entry_type + pub_type ─────────────────────────────────
_TYPE_MAP = {
    "JOUR": ("bibliography", "article"),
    "ABST": ("bibliography", "article"),
    "BOOK": ("bibliography", "book"),
    "CHAP": ("bibliography", "chapter"),
    "CONF": ("bibliography", "article"),
    "CPAPER": ("bibliography", "article"),
    "THES": ("tesi", "magistrale"),
    "DISS": ("tesi", "dottorato"),
    "ELEC": ("sitography", ""),
    "ICOMM": ("sitography", ""),
    "WEB": ("sitography", ""),
    "GEN": ("bibliography", "article"),
    "RPRT": ("bibliography", "article"),
    "MGZN": ("bibliography", "article"),
    "NEWS": ("bibliography", "article"),
}


class RisParser:
    """Parse RIS content into CiteMind entry dicts."""

    def parse_file(self, path: str) -> list[dict]:
        """Parse a .ris file and return a list of entry dicts."""
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return self.parse(content)

    def parse(self, content: str) -> list[dict]:
        """
        Parse RIS content string.

        Returns
        -------
        list[dict]
            Each dict is ready for EntryModel.create().
        """
        entries = []
        current_record: dict[str, list[str]] = {}
        current_type = ""

        for line in content.split("\n"):
            line = line.rstrip()
            if not line:
                continue

            # RIS tag format: "XX  - value" (6-char prefix)
            match = re.match(r'^([A-Z][A-Z0-9])\s{2}-\s?(.*)', line)
            if not match:
                continue

            tag = match.group(1)
            value = match.group(2).strip()

            if tag == "TY":
                current_record = {}
                current_type = value.strip()
            elif tag == "ER":
                if current_record:
                    entry = self._build_entry(current_type, current_record)
                    if entry:
                        entries.append(entry)
                current_record = {}
                current_type = ""
            else:
                current_record.setdefault(tag, []).append(value)

        # Handle file without final ER
        if current_record:
            entry = self._build_entry(current_type, current_record)
            if entry:
                entries.append(entry)

        return entries

    def _build_entry(self, ris_type: str, record: dict[str, list[str]]) -> dict | None:
        """Convert a parsed RIS record to a CiteMind entry dict."""
        cm_type, cm_pub = _TYPE_MAP.get(ris_type, ("bibliography", "article"))

        entry: dict[str, str | int] = {
            "entry_type": cm_type,
            "pub_type": cm_pub,
        }

        authors: list[str] = []
        keywords: list[str] = []
        start_page = ""
        end_page = ""

        for tag, values in record.items():
            cm_field = _RIS_MAP.get(tag)
            if not cm_field:
                continue

            for value in values:
                value = value.strip()
                if not value:
                    continue

                if cm_field == "authors":
                    authors.append(self._normalize_author(value))
                elif cm_field == "_keyword":
                    keywords.append(value)
                elif cm_field == "_start_page":
                    start_page = value
                elif cm_field == "_end_page":
                    end_page = value
                elif cm_field == "year":
                    # Extract just the year from various date formats
                    year_match = re.search(r'(\d{4})', value)
                    if year_match:
                        entry["year"] = year_match.group(1)
                elif cm_field.startswith("_"):
                    continue  # internal fields
                else:
                    # For multi-value fields, concatenate
                    if cm_field in entry and entry[cm_field]:
                        entry[cm_field] = str(entry[cm_field]) + " " + value
                    else:
                        entry[cm_field] = value

        # Set authors
        entry["authors"] = "; ".join(authors)

        # Merge pages
        if start_page:
            if end_page and end_page != start_page:
                entry["pages"] = f"{start_page}–{end_page}"
            else:
                entry["pages"] = start_page

        # Store keywords in notes if present
        if keywords:
            existing_notes = str(entry.get("notes", ""))
            kw_str = "Keywords: " + ", ".join(keywords)
            entry["notes"] = (existing_notes + "\n" + kw_str).strip() if existing_notes else kw_str

        # Ensure all required fields
        for f in ("authors", "title", "year", "publisher", "journal", "volume",
                   "issue", "pages", "edition", "doi", "url", "access_date",
                   "notes", "pdf_path", "location"):
            entry.setdefault(f, "")

        entry.setdefault("is_read", 0)
        entry.setdefault("is_editor", 0)
        entry.setdefault("ai_notes", "")
        entry.setdefault("ai_topics", "")

        if not entry.get("title"):
            return None

        return entry

    @staticmethod
    def _normalize_author(author: str) -> str:
        """
        Normalize RIS author format.
        RIS typically uses "Last, First" or "First Last".
        """
        author = author.strip()
        if "," in author:
            return author  # Already "Last, First"
        parts = author.split()
        if len(parts) >= 2:
            return f"{parts[-1]}, {' '.join(parts[:-1])}"
        return author
