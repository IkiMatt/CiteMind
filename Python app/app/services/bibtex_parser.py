"""
bibtex_parser.py — Parse BibTeX files into CiteMind entry dicts.

Regex-based parser — no external BibTeX library needed.
Handles @article, @book, @inproceedings, @incollection, @phdthesis, etc.
"""
from __future__ import annotations

import re
from pathlib import Path


# ── BibTeX field → CiteMind field mapping ─────────────────────────────────────
_FIELD_MAP = {
    "author": "authors",
    "title": "title",
    "year": "year",
    "journal": "journal",
    "journaltitle": "journal",  # biblatex
    "volume": "volume",
    "number": "issue",
    "issue": "issue",
    "pages": "pages",
    "doi": "doi",
    "url": "url",
    "publisher": "publisher",
    "edition": "edition",
    "note": "notes",
    "abstract": "notes",
    "address": "location",
    "location": "location",     # biblatex
    "booktitle": "journal",     # for @inproceedings / @incollection
    "school": "publisher",      # for @phdthesis / @mastersthesis
    "institution": "publisher",
    "editor": "publisher",      # store editors in publisher for chapters
    "series": "journal",
}

# ── BibTeX entry type → CiteMind entry_type + pub_type ────────────────────────
_TYPE_MAP = {
    "article": ("bibliography", "article"),
    "book": ("bibliography", "book"),
    "inbook": ("bibliography", "chapter"),
    "incollection": ("bibliography", "chapter"),
    "inproceedings": ("bibliography", "article"),
    "conference": ("bibliography", "article"),
    "phdthesis": ("tesi", "dottorato"),
    "mastersthesis": ("tesi", "magistrale"),
    "thesis": ("tesi", "magistrale"),
    "techreport": ("bibliography", "article"),
    "misc": ("bibliography", "article"),
    "online": ("sitography", ""),
    "webpage": ("sitography", ""),
    "unpublished": ("bibliography", "article"),
}

# ── Regex patterns ────────────────────────────────────────────────────────────
_ENTRY_PATTERN = re.compile(
    r'@(\w+)\s*\{([^,]*),\s*(.*?)\n\s*\}',
    re.DOTALL,
)

_FIELD_PATTERN = re.compile(
    r'(\w+)\s*=\s*(?:\{((?:[^{}]|\{[^{}]*\})*)\}|"([^"]*)"|\s*(\d+)\s*)',
    re.DOTALL,
)


class BibtexParser:
    """Parse BibTeX content into CiteMind entry dicts."""

    def parse_file(self, path: str) -> list[dict]:
        """Parse a .bib file and return a list of entry dicts."""
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return self.parse(content)

    def parse(self, content: str) -> list[dict]:
        """
        Parse BibTeX content string.

        Returns
        -------
        list[dict]
            Each dict is ready for EntryModel.create().
        """
        entries = []

        for match in _ENTRY_PATTERN.finditer(content):
            entry_type = match.group(1).lower()
            cite_key = match.group(2).strip()
            body = match.group(3)

            if entry_type in ("comment", "preamble", "string"):
                continue

            entry = self._parse_entry(entry_type, body)
            if entry:
                entries.append(entry)

        return entries

    def _parse_entry(self, bib_type: str, body: str) -> dict | None:
        """Parse a single BibTeX entry body into a CiteMind dict."""
        # Determine CiteMind entry_type and pub_type
        cm_type, cm_pub = _TYPE_MAP.get(bib_type, ("bibliography", "article"))

        fields: dict[str, str] = {}
        for match in _FIELD_PATTERN.finditer(body):
            key = match.group(1).lower()
            value = match.group(2) or match.group(3) or match.group(4) or ""
            value = self._clean_value(value)
            if value:
                fields[key] = value

        # Map BibTeX fields to CiteMind fields
        entry: dict[str, str] = {
            "entry_type": cm_type,
            "pub_type": cm_pub,
        }

        for bib_field, cm_field in _FIELD_MAP.items():
            if bib_field in fields:
                val = fields[bib_field]
                # Don't overwrite with lower-priority mapping
                if cm_field not in entry or not entry[cm_field]:
                    entry[cm_field] = val

        # Handle author format: "Last, First and Last2, First2" → "Last, First; Last2, First2"
        if "authors" in entry:
            entry["authors"] = self._normalize_authors(entry["authors"])

        # Check for editor flag
        if "editor" in fields and bib_type in ("book", "incollection", "inbook"):
            # If editor is in the fields, set is_editor flag
            if "authors" not in entry or not entry["authors"]:
                entry["authors"] = self._normalize_authors(fields["editor"])
                entry["is_editor"] = 1

        # Ensure all required fields exist
        for f in ("authors", "title", "year", "publisher", "journal", "volume",
                   "issue", "pages", "edition", "doi", "url", "access_date",
                   "notes", "pdf_path", "location"):
            entry.setdefault(f, "")

        entry.setdefault("is_read", 0)
        entry.setdefault("is_editor", 0)
        entry.setdefault("ai_notes", "")
        entry.setdefault("ai_topics", "")

        # Skip entries with no title
        if not entry.get("title"):
            return None

        return entry

    @staticmethod
    def _clean_value(value: str) -> str:
        """Clean a BibTeX field value."""
        # Remove surrounding braces and whitespace
        value = value.strip().strip("{}")
        # Remove LaTeX commands
        value = re.sub(r'\\textit\{([^}]*)\}', r'\1', value)
        value = re.sub(r'\\textbf\{([^}]*)\}', r'\1', value)
        value = re.sub(r'\\emph\{([^}]*)\}', r'\1', value)
        value = re.sub(r'\\\w+\{([^}]*)\}', r'\1', value)
        # Replace LaTeX dashes
        value = value.replace("---", "—").replace("--", "–")
        # Remove remaining braces
        value = value.replace("{", "").replace("}", "")
        # Normalize whitespace
        value = re.sub(r'\s+', ' ', value).strip()
        return value

    @staticmethod
    def _normalize_authors(authors_str: str) -> str:
        """
        Normalize BibTeX author format to CiteMind format.
        Input:  "Last, First and Last2, First2"
        Output: "Last, First; Last2, First2"
        """
        # Split on " and "
        authors = re.split(r'\s+and\s+', authors_str, flags=re.IGNORECASE)
        normalized = []
        for author in authors:
            author = author.strip()
            if not author:
                continue
            # Already in "Last, First" format? Keep it.
            if "," in author:
                normalized.append(author.strip())
            else:
                # "First Last" → "Last, First"
                parts = author.split()
                if len(parts) >= 2:
                    first = " ".join(parts[:-1])
                    last = parts[-1]
                    normalized.append(f"{last}, {first}")
                else:
                    normalized.append(author)
        return "; ".join(normalized)
