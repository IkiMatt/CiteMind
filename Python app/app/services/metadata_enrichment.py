"""
metadata_enrichment.py — Query authoritative APIs for paper metadata.

Sources (tried in order):
  1. Crossref  — most complete, free, rate-limited
  2. OpenAlex  — fast, good coverage, free
  3. Semantic Scholar — good for CS/medical, has abstracts

Each source returns a SourceResult with per-field confidence.
Results are merged with conflict resolution (highest confidence wins).
"""
from __future__ import annotations

import time
import re
from dataclasses import dataclass, field

import requests


@dataclass
class SourceResult:
    """Metadata from a single API source."""
    title: str = ""
    authors: str = ""
    year: str = ""
    journal: str = ""
    doi: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    publisher: str = ""
    abstract: str = ""
    url: str = ""
    keywords: list[str] = field(default_factory=list)
    source_name: str = ""
    confidence: float = 0.0


@dataclass
class EnrichmentResult:
    """Merged metadata from multiple sources."""
    metadata: dict[str, str]
    per_field_confidence: dict[str, float]
    per_field_source: dict[str, str]
    keywords: list[str]
    abstract: str = ""

    @property
    def overall_confidence(self) -> float:
        if not self.per_field_confidence:
            return 0.0
        return sum(self.per_field_confidence.values()) / len(self.per_field_confidence)


# ── Retry decorator ──────────────────────────────────────────────────────────

def _retry(func, max_attempts: int = 3, backoff: tuple = (1, 3, 10)):
    """Simple retry wrapper for API calls."""
    def wrapper(*args, **kwargs):
        last_exc = None
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
                if attempt < max_attempts - 1:
                    time.sleep(backoff[min(attempt, len(backoff) - 1)])
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 429:
                    wait = int(exc.response.headers.get("Retry-After", 5))
                    time.sleep(min(wait, 30))
                    last_exc = exc
                else:
                    raise
        raise last_exc
    return wrapper


# ══════════════════════════════════════════════════════════════════════════════
# ── API Sources ──────────────────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class CrossrefSource:
    """Query Crossref REST API."""

    BASE_URL = "https://api.crossref.org/works"
    HEADERS = {
        "User-Agent": "CiteMind/1.0 (academic bibliography manager; mailto:citemind@example.com)",
    }

    def query(self, doi: str | None = None, title: str | None = None) -> SourceResult | None:
        """Query Crossref by DOI or title search."""
        try:
            if doi:
                return self._query_by_doi(doi)
            elif title:
                return self._query_by_title(title)
        except Exception:
            return None
        return None

    def _query_by_doi(self, doi: str) -> SourceResult | None:
        resp = requests.get(
            f"{self.BASE_URL}/{doi}",
            headers=self.HEADERS,
            timeout=10,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json().get("message", {})
        return self._parse(data, confidence=0.95)

    def _query_by_title(self, title: str) -> SourceResult | None:
        resp = requests.get(
            self.BASE_URL,
            params={"query.title": title, "rows": 3},
            headers=self.HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("message", {}).get("items", [])
        if not items:
            return None

        # Pick the best match (highest score)
        best = items[0]
        best_title = " ".join(best.get("title", []))
        # Simple similarity check
        if self._title_similarity(title, best_title) < 0.5:
            return None

        return self._parse(best, confidence=0.70)

    def _parse(self, data: dict, confidence: float) -> SourceResult:
        authors_list = data.get("author", [])
        authors = "; ".join(
            f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
            for a in authors_list
        )

        # Year from published-print or published-online
        year = ""
        for date_field in ("published-print", "published-online", "issued"):
            date_parts = data.get(date_field, {}).get("date-parts", [[]])
            if date_parts and date_parts[0]:
                y = date_parts[0][0]
                if y:
                    year = str(y)
                    break

        return SourceResult(
            title=" ".join(data.get("title", [])),
            authors=authors,
            year=year,
            journal=" ".join(data.get("container-title", [])),
            doi=data.get("DOI", ""),
            volume=data.get("volume", ""),
            issue=data.get("issue", ""),
            pages=data.get("page", ""),
            publisher=data.get("publisher", ""),
            abstract=self._clean_abstract(data.get("abstract", "")),
            url=data.get("URL", ""),
            source_name="crossref",
            confidence=confidence,
        )

    @staticmethod
    def _clean_abstract(html: str) -> str:
        """Remove HTML tags from Crossref abstracts."""
        if not html:
            return ""
        return re.sub(r'<[^>]+>', '', html).strip()

    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        """Simple word-overlap similarity between two titles."""
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / max(len(wa), len(wb))


class OpenAlexSource:
    """Query OpenAlex API."""

    BASE_URL = "https://api.openalex.org/works"

    def query(self, doi: str | None = None, title: str | None = None) -> SourceResult | None:
        try:
            if doi:
                return self._query_by_doi(doi)
            elif title:
                return self._query_by_title(title)
        except Exception:
            return None
        return None

    def _query_by_doi(self, doi: str) -> SourceResult | None:
        resp = requests.get(
            f"{self.BASE_URL}/doi:{doi}",
            params={"mailto": "citemind@example.com"},
            timeout=10,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._parse(resp.json(), confidence=0.92)

    def _query_by_title(self, title: str) -> SourceResult | None:
        resp = requests.get(
            self.BASE_URL,
            params={"search": title, "per_page": 3, "mailto": "citemind@example.com"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return None
        return self._parse(results[0], confidence=0.65)

    def _parse(self, data: dict, confidence: float) -> SourceResult:
        authorships = data.get("authorships", [])
        authors = "; ".join(
            a.get("author", {}).get("display_name", "")
            for a in authorships
        )

        year = str(data.get("publication_year", ""))

        # Journal from primary_location
        journal = ""
        loc = data.get("primary_location", {})
        if loc:
            source = loc.get("source", {})
            if source:
                journal = source.get("display_name", "")

        doi = (data.get("doi") or "").replace("https://doi.org/", "")

        # Abstract — OpenAlex uses inverted index
        abstract = self._reconstruct_abstract(data.get("abstract_inverted_index"))

        return SourceResult(
            title=data.get("display_name", "") or data.get("title", ""),
            authors=authors,
            year=year,
            journal=journal,
            doi=doi,
            abstract=abstract,
            url=data.get("id", ""),
            source_name="openalex",
            confidence=confidence,
        )

    @staticmethod
    def _reconstruct_abstract(inverted_index: dict | None) -> str:
        """Reconstruct abstract from OpenAlex's inverted index format."""
        if not inverted_index:
            return ""
        word_positions: list[tuple[int, str]] = []
        for word, positions in inverted_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        return " ".join(w for _, w in word_positions)


class SemanticScholarSource:
    """Query Semantic Scholar API."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1/paper"
    FIELDS = "title,authors,year,venue,abstract,externalIds,publicationTypes"

    def query(self, doi: str | None = None, title: str | None = None) -> SourceResult | None:
        try:
            if doi:
                return self._query_by_doi(doi)
            elif title:
                return self._query_by_title(title)
        except Exception:
            return None
        return None

    def _query_by_doi(self, doi: str) -> SourceResult | None:
        resp = requests.get(
            f"{self.BASE_URL}/DOI:{doi}",
            params={"fields": self.FIELDS},
            timeout=10,
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._parse(resp.json(), confidence=0.90)

    def _query_by_title(self, title: str) -> SourceResult | None:
        resp = requests.get(
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": title, "limit": 3, "fields": self.FIELDS},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json().get("data", [])
        if not data:
            return None
        return self._parse(data[0], confidence=0.60)

    def _parse(self, data: dict, confidence: float) -> SourceResult:
        authors = "; ".join(
            a.get("name", "")
            for a in data.get("authors", [])
        )

        ext_ids = data.get("externalIds", {})
        doi = ext_ids.get("DOI", "")

        return SourceResult(
            title=data.get("title", ""),
            authors=authors,
            year=str(data.get("year", "")),
            journal=data.get("venue", ""),
            doi=doi,
            abstract=data.get("abstract", "") or "",
            source_name="semantic_scholar",
            confidence=confidence,
        )


# ══════════════════════════════════════════════════════════════════════════════
# ── Enrichment Orchestrator ──────────────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

class MetadataEnricher:
    """
    Query authoritative APIs before falling back to AI.
    Tries Crossref → OpenAlex → Semantic Scholar, merges results.
    """

    SOURCES = [
        CrossrefSource(),
        OpenAlexSource(),
        SemanticScholarSource(),
    ]

    METADATA_FIELDS = ["title", "authors", "year", "journal", "doi",
                       "volume", "issue", "pages", "publisher", "url"]

    def enrich(self, doi: str | None = None,
               title: str | None = None) -> EnrichmentResult:
        """
        Try each source in order. Merge results with conflict resolution.
        Higher confidence wins per field.
        """
        source_results: list[SourceResult] = []

        for source in self.SOURCES:
            try:
                result = source.query(doi=doi, title=title)
                if result and result.confidence > 0.3:
                    source_results.append(result)
                    # If we have high confidence from DOI lookup, we can stop early
                    if result.confidence > 0.90 and doi:
                        break
            except Exception:
                continue

        return self._merge_results(source_results)

    def _merge_results(self, results: list[SourceResult]) -> EnrichmentResult:
        """Merge multiple source results — highest confidence wins per field."""
        metadata: dict[str, str] = {}
        confidence: dict[str, float] = {}
        source_map: dict[str, str] = {}
        best_abstract = ""
        best_abstract_conf = 0.0
        all_keywords: list[str] = []

        for sr in results:
            for field_name in self.METADATA_FIELDS:
                value = getattr(sr, field_name, "")
                if not value:
                    continue
                field_conf = sr.confidence
                # If this field has better confidence, use it
                if field_name not in confidence or field_conf > confidence[field_name]:
                    metadata[field_name] = str(value)
                    confidence[field_name] = field_conf
                    source_map[field_name] = sr.source_name

            # Abstract
            if sr.abstract and sr.confidence > best_abstract_conf:
                best_abstract = sr.abstract
                best_abstract_conf = sr.confidence

            # Keywords
            all_keywords.extend(sr.keywords)

        # Deduplicate keywords
        seen = set()
        unique_kw = []
        for kw in all_keywords:
            kw_lower = kw.lower()
            if kw_lower not in seen:
                seen.add(kw_lower)
                unique_kw.append(kw)

        return EnrichmentResult(
            metadata=metadata,
            per_field_confidence=confidence,
            per_field_source=source_map,
            keywords=unique_kw[:10],
            abstract=best_abstract,
        )
