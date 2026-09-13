"""
csv_parser.py — Parse CSV files exported from Zotero, Mendeley, etc.
"""
import csv
from pathlib import Path


# Common column names mapped to CiteMind fields
_CSV_MAP = {
    "title": "title",
    "author": "authors",
    "authors": "authors",
    "publication year": "year",
    "year": "year",
    "date": "year",
    "publication title": "journal",
    "journal": "journal",
    "publisher": "publisher",
    "volume": "volume",
    "issue": "issue",
    "pages": "pages",
    "doi": "doi",
    "url": "url",
    "abstract": "notes",
    "note": "notes",
    "item type": "_type",
    "type": "_type",
}

class CsvParser:
    """Parse CSV content into CiteMind entry dicts."""

    def parse_file(self, path: str) -> list[dict]:
        """Parse a .csv file and return a list of entry dicts."""
        content = Path(path).read_text(encoding="utf-8", errors="replace")
        return self.parse(content)

    def parse(self, content: str) -> list[dict]:
        if not content.strip():
            return []

        # Sniff dialect
        try:
            dialect = csv.Sniffer().sniff(content[:1024])
        except csv.Error:
            dialect = csv.excel

        entries = []
        reader = csv.DictReader(content.splitlines(), dialect=dialect)
        
        for row in reader:
            entry = self._build_entry(row)
            if entry:
                entries.append(entry)
                
        return entries

    def _build_entry(self, row: dict) -> dict | None:
        entry = {
            "entry_type": "bibliography",
            "pub_type": "article",
        }

        for col_name, value in row.items():
            if not col_name or not value:
                continue
                
            clean_col = col_name.strip().lower()
            cm_field = _CSV_MAP.get(clean_col)
            
            if not cm_field:
                continue
                
            value = value.strip()
            
            if cm_field == "_type":
                # Very basic type mapping
                v_lower = value.lower()
                if "book" in v_lower:
                    entry["pub_type"] = "book"
                elif "thesis" in v_lower:
                    entry["entry_type"] = "tesi"
                    entry["pub_type"] = "magistrale"
                elif "web" in v_lower:
                    entry["entry_type"] = "sitography"
                    entry["pub_type"] = ""
            elif cm_field == "authors":
                # Assume authors are comma or semicolon separated
                authors = [a.strip() for a in value.replace(";", ",").split(",") if a.strip()]
                # Format as Last, First if possible, but for CSV we just join with ;
                entry["authors"] = "; ".join(authors)
            elif cm_field == "year":
                import re
                year_match = re.search(r'(\d{4})', value)
                if year_match:
                    entry["year"] = year_match.group(1)
            else:
                entry[cm_field] = value

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
