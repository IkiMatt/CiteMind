"""
import_pipeline.py — Orchestrate the full import pipeline for dropped files.

Pipeline stages:
  Drop → PDF Parse → DOI Extract → API Enrich → AI Fallback → Dedup → Insert → Embed → Graph

Each stage populates an ImportContext which flows through the pipeline.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum

import requests

from app.services.pdf_parser import PdfMetadataExtractor
from app.services.metadata_enrichment import MetadataEnricher
from app.services.bibtex_parser import BibtexParser
from app.services.ris_parser import RisParser
from app.services.csv_parser import CsvParser


class DropType(Enum):
    PDF = "pdf"
    BIBTEX = "bib"
    RIS = "ris"
    CSV = "csv"
    DOI = "doi"
    URL = "url"


@dataclass
class DropItem:
    """A single item dropped by the user."""
    type: DropType
    path: str = ""       # file path for PDF/BibTeX/RIS
    value: str = ""      # DOI string or URL


@dataclass
class ImportResult:
    """Result of processing a single dropped item."""
    entry_id: int | None = None
    entry_ids: list[int] = field(default_factory=list)  # for multi-entry imports (BibTeX)
    metadata: dict = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    source: str = ""        # primary source: "crossref", "openalex", "ollama", "pdf_parse"
    warnings: list[str] = field(default_factory=list)
    needs_review: bool = False
    error: str = ""
    filename: str = ""


@dataclass
class ImportContext:
    """Mutable context flowing through pipeline stages."""
    item: DropItem
    metadata: dict = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    source_map: dict[str, str] = field(default_factory=dict)
    pdf_text: str = ""
    doi: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    pdf_path: str = ""
    abort: bool = False
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    is_duplicate: bool = False
    existing_entry_id: int | None = None
    # Populated by insertion stage
    entry_id: int | None = None
    entry_ids: list[int] = field(default_factory=list)


# ── DOI regex ─────────────────────────────────────────────────────────────────
_DOI_REGEX = re.compile(r'(10\.\d{4,}/[^\s,;"\'\]>]+)')


class ImportPipeline:
    """
    Orchestrates the full import flow.
    Each method handles one format type, delegating to parsers and enrichers.
    """

    def __init__(self, model, ollama_url: str = "", model_name: str = ""):
        self._model = model
        self._ollama_url = ollama_url
        self._model_name = model_name
        self._pdf_parser = PdfMetadataExtractor()
        self._enricher = MetadataEnricher()
        self._bibtex_parser = BibtexParser()
        self._ris_parser = RisParser()
        self._csv_parser = CsvParser()

    def process(self, item: DropItem) -> ImportResult:
        """
        Process a single dropped item through the full pipeline.
        This method is designed to be called from a QThread worker.
        """
        ctx = ImportContext(item=item)

        try:
            if item.type == DropType.PDF:
                self._process_pdf(ctx)
            elif item.type == DropType.BIBTEX:
                return self._process_bibtex(ctx)
            elif item.type == DropType.RIS:
                return self._process_ris(ctx)
            elif item.type == DropType.CSV:
                return self._process_csv(ctx)
            elif item.type == DropType.DOI:
                self._process_doi(ctx)
            elif item.type == DropType.URL:
                self._process_url(ctx)
            else:
                ctx.error = f"Unsupported drop type: {item.type}"

        except Exception as exc:
            ctx.error = str(exc)

        return self._build_result(ctx)

    # ── PDF processing ────────────────────────────────────────────────────

    def _process_pdf(self, ctx: ImportContext) -> None:
        """Full pipeline for a dropped PDF."""
        path = ctx.item.path
        ctx.pdf_path = path

        # Stage 1: PDF parse
        pdf_meta = self._pdf_parser.extract(path)
        ctx.metadata = {
            "title": pdf_meta.title,
            "authors": pdf_meta.authors,
            "year": pdf_meta.year,
            "doi": pdf_meta.doi,
        }
        ctx.confidence = dict(pdf_meta.confidence)
        ctx.doi = pdf_meta.doi
        ctx.abstract = pdf_meta.abstract
        ctx.keywords = pdf_meta.keywords

        for k, v in ctx.confidence.items():
            ctx.source_map[k] = "pdf_parse"

        # Stage 2: API enrichment (if DOI or title found)
        self._enrich(ctx)

        # Stage 3: Ollama fallback for missing fields
        self._ollama_fallback(ctx)

        # Stage 4: Dedup check
        self._check_duplicate(ctx)
        if ctx.is_duplicate:
            ctx.warnings.append(f"Duplicate detected (entry #{ctx.existing_entry_id})")
            return

        # Stage 5: Insert entry
        self._insert_entry(ctx)

    # ── DOI processing ────────────────────────────────────────────────────

    def _process_doi(self, ctx: ImportContext) -> None:
        """Pipeline for a dropped DOI string."""
        ctx.doi = ctx.item.value.strip()
        # Clean DOI
        ctx.doi = re.sub(r'^https?://(?:dx\.)?doi\.org/', '', ctx.doi)

        # Enrich from APIs
        self._enrich(ctx)

        if not ctx.metadata.get("title"):
            ctx.error = f"Could not find metadata for DOI: {ctx.doi}"
            return

        # Dedup check
        self._check_duplicate(ctx)
        if ctx.is_duplicate:
            ctx.warnings.append(f"Duplicate detected (entry #{ctx.existing_entry_id})")
            return

        # Insert
        self._insert_entry(ctx)

    # ── URL processing ────────────────────────────────────────────────────

    def _process_url(self, ctx: ImportContext) -> None:
        """Pipeline for a dropped URL."""
        url = ctx.item.value.strip()

        # Check if URL contains a DOI
        doi_match = _DOI_REGEX.search(url)
        if doi_match:
            ctx.doi = doi_match.group(1)
            self._enrich(ctx)
        else:
            ctx.metadata["url"] = url

        if not ctx.metadata.get("title"):
            # Create a sitography entry with just the URL
            ctx.metadata.setdefault("entry_type", "sitography")
            ctx.metadata["url"] = url
            ctx.metadata["title"] = url  # placeholder

        self._check_duplicate(ctx)
        if ctx.is_duplicate:
            ctx.warnings.append(f"Duplicate detected (entry #{ctx.existing_entry_id})")
            return

        self._insert_entry(ctx)

    # ── BibTeX processing ─────────────────────────────────────────────────

    def _process_bibtex(self, ctx: ImportContext) -> ImportResult:
        """Process a BibTeX file — may create multiple entries."""
        entries = self._bibtex_parser.parse_file(ctx.item.path)
        created_ids: list[int] = []
        warnings: list[str] = []

        for entry_data in entries:
            title = entry_data.get("title", "")
            doi = entry_data.get("doi", "")

            # Dedup
            if doi and self._model.check_duplicate_doi(doi):
                warnings.append(f"Skipped duplicate DOI: {doi}")
                continue
            if title and self._model.check_duplicate_title(title):
                warnings.append(f"Skipped duplicate title: {title[:60]}…")
                continue

            entry_id = self._model.create(entry_data)
            created_ids.append(entry_id)

        return ImportResult(
            entry_id=created_ids[0] if created_ids else None,
            entry_ids=created_ids,
            metadata={"count": len(created_ids)},
            source="bibtex",
            warnings=warnings,
            filename=Path(ctx.item.path).name,
        )

    # ── RIS processing ────────────────────────────────────────────────────

    def _process_ris(self, ctx: ImportContext) -> ImportResult:
        """Process a RIS file — may create multiple entries."""
        entries = self._ris_parser.parse_file(ctx.item.path)
        created_ids: list[int] = []
        warnings: list[str] = []

        for entry_data in entries:
            title = entry_data.get("title", "")
            doi = entry_data.get("doi", "")

            if doi and self._model.check_duplicate_doi(doi):
                warnings.append(f"Skipped duplicate DOI: {doi}")
                continue
            if title and self._model.check_duplicate_title(title):
                warnings.append(f"Skipped duplicate title: {title[:60]}…")
                continue

            entry_id = self._model.create(entry_data)
            created_ids.append(entry_id)

        return ImportResult(
            entry_id=created_ids[0] if created_ids else None,
            entry_ids=created_ids,
            metadata={"count": len(created_ids)},
            source="ris",
            warnings=warnings,
            filename=Path(ctx.item.path).name,
        )

    # ── CSV processing ────────────────────────────────────────────────────

    def _process_csv(self, ctx: ImportContext) -> ImportResult:
        """Process a CSV file — may create multiple entries."""
        entries = self._csv_parser.parse_file(ctx.item.path)
        created_ids: list[int] = []
        warnings: list[str] = []

        for entry_data in entries:
            title = entry_data.get("title", "")
            doi = entry_data.get("doi", "")

            if doi and self._model.check_duplicate_doi(doi):
                warnings.append(f"Skipped duplicate DOI: {doi}")
                continue
            if title and self._model.check_duplicate_title(title):
                warnings.append(f"Skipped duplicate title: {title[:60]}…")
                continue

            entry_id = self._model.create(entry_data)
            created_ids.append(entry_id)

        return ImportResult(
            entry_id=created_ids[0] if created_ids else None,
            entry_ids=created_ids,
            metadata={"count": len(created_ids)},
            source="csv",
            warnings=warnings,
            filename=Path(ctx.item.path).name,
        )

    # ══════════════════════════════════════════════════════════════════════
    # ── Shared pipeline stages ───────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════

    def _enrich(self, ctx: ImportContext) -> None:
        """API enrichment stage — Crossref → OpenAlex → Semantic Scholar."""
        try:
            result = self._enricher.enrich(
                doi=ctx.doi or ctx.metadata.get("doi"),
                title=ctx.metadata.get("title"),
            )
        except Exception:
            return  # non-critical

        # Merge: API results override PDF-parsed data if higher confidence
        for field_name, value in result.metadata.items():
            if not value:
                continue
            api_conf = result.per_field_confidence.get(field_name, 0)
            local_conf = ctx.confidence.get(field_name, 0)
            if api_conf > local_conf:
                ctx.metadata[field_name] = value
                ctx.confidence[field_name] = api_conf
                ctx.source_map[field_name] = result.per_field_source.get(field_name, "api")

        # Abstract and keywords
        if result.abstract and len(result.abstract) > len(ctx.abstract):
            ctx.abstract = result.abstract
        if result.keywords:
            ctx.keywords = list(set(ctx.keywords + result.keywords))[:10]

        # Update DOI if found
        if result.metadata.get("doi") and not ctx.doi:
            ctx.doi = result.metadata["doi"]

    def _ollama_fallback(self, ctx: ImportContext) -> None:
        """Use Ollama to fill in missing metadata. Only if configured and fields are missing."""
        if not self._ollama_url or not self._model_name:
            return

        # Check which important fields are missing
        missing = []
        for f in ("title", "authors", "year"):
            if not ctx.metadata.get(f):
                missing.append(f)

        if not missing and ctx.abstract:
            return  # nothing to infer

        # Extract text from PDF if available
        if ctx.pdf_path and not ctx.pdf_text:
            try:
                from app.ai_worker import extract_pdf_text
                ctx.pdf_text = extract_pdf_text(ctx.pdf_path, max_chars=3000)
            except Exception:
                pass

        if not ctx.pdf_text:
            return

        # Build prompt
        known = {k: v for k, v in ctx.metadata.items() if v}
        prompt = self._build_metadata_prompt(known, ctx.pdf_text[:2000])

        try:
            url = self._ollama_url
            if not url.startswith("http"):
                url = "http://" + url

            resp = requests.post(
                f"{url}/api/generate",
                json={
                    "model": self._model_name,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.1, "num_predict": 1024},
                },
                timeout=120,
            )
            resp.raise_for_status()
            raw = resp.json().get("response", "").strip()

            # Strip markdown fences
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            result = json.loads(raw)

            # Fill in missing fields with AI results (low confidence)
            for f in ("title", "authors", "year", "journal", "abstract", "keywords"):
                val = result.get(f, "")
                if val and not ctx.metadata.get(f):
                    if isinstance(val, list):
                        val = ", ".join(val)
                    ctx.metadata[f] = str(val)
                    ctx.confidence[f] = 0.45  # AI-inferred = low confidence
                    ctx.source_map[f] = "ollama"

            # Never trust AI-generated DOIs
            if "doi" in result and not ctx.metadata.get("doi"):
                ctx.warnings.append("AI suggested a DOI — ignored (unverifiable)")

            # Abstract
            if result.get("abstract") and not ctx.abstract:
                ctx.abstract = str(result["abstract"])

            # Keywords
            if result.get("keywords") and isinstance(result["keywords"], list):
                ctx.keywords = list(set(ctx.keywords + result["keywords"]))[:10]

        except Exception as exc:
            ctx.warnings.append(f"AI fallback failed: {exc}")

    def _check_duplicate(self, ctx: ImportContext) -> None:
        """Check if entry already exists by DOI or title."""
        doi = ctx.metadata.get("doi", "")
        title = ctx.metadata.get("title", "")

        if doi:
            existing = self._model.find_by_doi(doi)
            if existing:
                ctx.is_duplicate = True
                ctx.existing_entry_id = existing["id"]
                return

        if title:
            existing = self._model.find_by_title(title)
            if existing:
                ctx.is_duplicate = True
                ctx.existing_entry_id = existing["id"]
                return

    def _insert_entry(self, ctx: ImportContext) -> None:
        """Create the entry in the database."""
        entry_data = {
            "entry_type": ctx.metadata.get("entry_type", "bibliography"),
            "pub_type": ctx.metadata.get("pub_type", "article"),
            "authors": ctx.metadata.get("authors", ""),
            "title": ctx.metadata.get("title", ""),
            "year": ctx.metadata.get("year", ""),
            "publisher": ctx.metadata.get("publisher", ""),
            "journal": ctx.metadata.get("journal", ""),
            "volume": ctx.metadata.get("volume", ""),
            "issue": ctx.metadata.get("issue", ""),
            "pages": ctx.metadata.get("pages", ""),
            "edition": ctx.metadata.get("edition", ""),
            "doi": ctx.metadata.get("doi", ""),
            "url": ctx.metadata.get("url", ""),
            "access_date": ctx.metadata.get("access_date", ""),
            "notes": ctx.abstract or ctx.metadata.get("notes", ""),
            "pdf_path": ctx.pdf_path,
            "location": ctx.metadata.get("location", ""),
            "is_read": 0,
            "is_editor": 0,
            "ai_notes": "",
            "ai_topics": "",
        }

        # Apply learned corrections
        entry_data = self._apply_corrections(entry_data)

        ctx.entry_id = self._model.create(entry_data)

        # Save keywords as AI topics if available
        if ctx.keywords and ctx.entry_id:
            self._model.save_ai_topics(ctx.entry_id, ctx.keywords)

    def _apply_corrections(self, data: dict) -> dict:
        """Apply learned corrections from user feedback."""
        try:
            for field_name in ("journal", "authors", "publisher"):
                corrections = self._model.get_corrections(field_name)
                val = data.get(field_name, "")
                if val and val in corrections:
                    data[field_name] = corrections[val]
        except Exception:
            pass
        return data

    # ── Helpers ───────────────────────────────────────────────────────────

    def _build_result(self, ctx: ImportContext) -> ImportResult:
        """Convert ImportContext to ImportResult."""
        needs_review = False
        # Flag for review if any important field has low confidence
        for f in ("title", "authors", "year"):
            if ctx.confidence.get(f, 0) < 0.6:
                needs_review = True
                break

        return ImportResult(
            entry_id=ctx.entry_id,
            entry_ids=[ctx.entry_id] if ctx.entry_id else [],
            metadata=ctx.metadata,
            confidence=ctx.confidence,
            source=self._primary_source(ctx.source_map),
            warnings=ctx.warnings,
            needs_review=needs_review,
            error=ctx.error,
            filename=Path(ctx.item.path).name if ctx.item.path else ctx.item.value,
        )

    @staticmethod
    def _primary_source(source_map: dict[str, str]) -> str:
        """Determine the primary metadata source."""
        if not source_map:
            return ""
        from collections import Counter
        counts = Counter(source_map.values())
        return counts.most_common(1)[0][0] if counts else ""

    @staticmethod
    def _build_metadata_prompt(known: dict, text_excerpt: str) -> str:
        """Build the Ollama prompt for metadata inference."""
        known_str = json.dumps(known, indent=2, ensure_ascii=False) if known else "{}"
        return f"""\
You are an expert academic librarian. Given the following partial metadata
and text excerpt from an academic paper, fill in the missing fields.

KNOWN METADATA:
{known_str}

TEXT EXCERPT (first 2000 chars):
{text_excerpt}

Return ONLY a JSON object with these keys (leave empty string if truly unknown):
{{
    "title": "",
    "authors": "",
    "year": "",
    "journal": "",
    "abstract": "",
    "keywords": [],
    "methodology": "",
    "geographic_scope": "",
    "chronological_scope": ""
}}

Rules:
- Do NOT invent DOIs. Only extract if explicitly visible in the text.
- For authors, use "Last, First" format separated by semicolons.
- For year, only extract if explicitly stated.
- Keywords should be 3-6 topical terms.
"""

    # ── Format detection ──────────────────────────────────────────────────

    @staticmethod
    def detect_drop_type(path: str) -> DropType | None:
        """Detect the type of a dropped file."""
        ext = Path(path).suffix.lower()
        if ext == ".pdf":
            return DropType.PDF
        elif ext == ".bib":
            return DropType.BIBTEX
        elif ext == ".ris":
            return DropType.RIS
        elif ext == ".csv":
            return DropType.CSV
        return None

    @staticmethod
    def extract_doi_from_text(text: str) -> str | None:
        """Try to extract a DOI from arbitrary text."""
        match = _DOI_REGEX.search(text)
        if match:
            doi = match.group(1).rstrip(".,;:)]}")
            return doi
        return None
