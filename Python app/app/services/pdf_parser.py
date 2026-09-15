import fitz  # PyMuPDF
import re
from typing import List
from dataclasses import dataclass, field

@dataclass
class PdfMetadata:
    title: str = ""
    authors: str = ""
    year: str = ""
    doi: str = ""
    abstract: str = ""
    keywords: list[str] = field(default_factory=list)
    confidence: dict[str, float] = field(default_factory=dict)
    field_sources: dict[str, str] = field(default_factory=dict)

class PdfMetadataExtractor:
    """Extract metadata from PDF properties and the first page."""

    _DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)
    _YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

    def extract(self, pdf_path: str) -> PdfMetadata:
        meta = PdfMetadata()
        try:
            with fitz.open(pdf_path) as doc:
                info = doc.metadata or {}
                meta.title = (info.get("title") or "").strip()
                meta.authors = (info.get("author") or "").strip()
                if meta.title:
                    meta.confidence["title"] = 0.5
                    meta.field_sources["title"] = "pdf_metadata"
                if meta.authors:
                    meta.confidence["authors"] = 0.5
                    meta.field_sources["authors"] = "pdf_metadata"

                if len(doc):
                    self._extract_first_page(doc[0], meta)
        except Exception:
            pass
        return meta

    def _extract_first_page(self, page: fitz.Page, meta: PdfMetadata) -> None:
        """Fill only missing fields using visible first-page text."""
        page_text = page.get_text("text", sort=True)
        lines = [line.strip() for line in page_text.splitlines() if line.strip()]
        if not lines:
            return

        if not meta.title:
            title = self._first_page_title(page)
            if title:
                meta.title = title
                meta.confidence["title"] = 0.65
                meta.field_sources["title"] = "pdf_first_page"

        if not meta.authors:
            author_line = self._author_line(lines, meta.title)
            if author_line:
                meta.authors = author_line
                meta.confidence["authors"] = 0.55
                meta.field_sources["authors"] = "pdf_first_page"

        if not meta.year:
            year_match = self._YEAR_RE.search(page_text[:3000])
            if year_match:
                meta.year = year_match.group(0)
                meta.confidence["year"] = 0.45
                meta.field_sources["year"] = "pdf_first_page"

        if not meta.doi:
            doi_match = self._DOI_RE.search(page_text[:5000])
            if doi_match:
                meta.doi = doi_match.group(0).rstrip(".,;)")
                meta.confidence["doi"] = 0.75
                meta.field_sources["doi"] = "pdf_first_page"

        abstract = self._labeled_section(lines, ("abstract", "摘要", "riassunto"))
        if abstract and not meta.abstract:
            meta.abstract = abstract[:4000]
            meta.confidence["abstract"] = 0.7
            meta.field_sources["abstract"] = "pdf_first_page"

        keywords = self._keywords(lines)
        if keywords and not meta.keywords:
            meta.keywords = keywords[:20]
            meta.confidence["keywords"] = 0.7
            meta.field_sources["keywords"] = "pdf_first_page"

    @staticmethod
    def _first_page_title(page: fitz.Page) -> str:
        """Select the largest meaningful text line near the top of the page."""
        candidates: list[tuple[float, str]] = []
        for block in page.get_text("dict", sort=True).get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                text = " ".join(span.get("text", "").strip() for span in line.get("spans", []))
                text = re.sub(r"\s+", " ", text).strip()
                if 15 <= len(text) <= 240 and "@" not in text:
                    size = max((float(span.get("size", 0)) for span in line.get("spans", [])), default=0)
                    candidates.append((size, text))
        return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else ""

    @staticmethod
    def _author_line(lines: list[str], title: str) -> str:
        """Find a short author-like line close to the title."""
        title_index = lines.index(title) if title in lines else 0
        for line in lines[title_index + 1:title_index + 6]:
            lower = line.lower()
            if len(line) > 200 or "@" in line or lower.startswith(("abstract", "keywords", "introduction")):
                continue
            if "," in line or " and " in lower or " et al" in lower:
                return line
        return ""

    @staticmethod
    def _labeled_section(lines: list[str], labels: tuple[str, ...]) -> str:
        for index, line in enumerate(lines):
            if line.lower().rstrip(":").strip() in labels:
                section: list[str] = []
                for candidate in lines[index + 1:]:
                    if candidate.lower().rstrip(":").strip() in ("keywords", "key words", "introduction"):
                        break
                    section.append(candidate)
                return " ".join(section).strip()
        return ""

    @staticmethod
    def _keywords(lines: list[str]) -> list[str]:
        for line in lines:
            if ":" not in line:
                continue
            label, values = line.split(":", 1)
            if label.lower().strip() in ("keywords", "key words", "parole chiave"):
                return [value.strip(" .;") for value in re.split(r"[,;]", values) if value.strip()]
        return []

TRIGGER_WORDS = [
    "bibliografia", "bibliography", "references", "works cited", 
    "literatur", "referencias", "bibliographie"
]

class PdfReferenceParser:
    """
    Parses a PDF to automatically extract the bibliography section based on 
    trigger words and font size heuristics.
    """
    
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        
    def extract_references(self) -> List[str]:
        """
        Main extraction method.
        Returns a list of extracted reference text blocks.
        """
        try:
            doc = fitz.open(self.pdf_path)
        except Exception as e:
            print(f"Error opening PDF: {e}")
            return []
            
        num_pages = len(doc)
        if num_pages == 0:
            return []
            
        # 1. Trovare il trigger nell'ultimo 20% del documento
        start_page = max(0, int(num_pages * 0.8))
        
        trigger_found = False
        trigger_page_idx = -1
        trigger_block_idx = -1
        
        # We will parse pages and keep their dict structure to avoid re-parsing
        pages_data = {}
        
        for p_idx in range(start_page, num_pages):
            page = doc[p_idx]
            page_dict = page.get_text("dict")
            pages_data[p_idx] = page_dict
            
            if trigger_found:
                continue
                
            blocks = page_dict.get("blocks", [])
            for b_idx, block in enumerate(blocks):
                if block.get("type") != 0:  # only text blocks
                    continue
                
                # Uniamo il testo del blocco per la ricerca del trigger
                text = ""
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text += span.get("text", "") + " "
                        
                clean_text = text.strip().lower()
                # Rimuoviamo punteggiatura fine stringa o numeri che potrebbero essere indici
                clean_text = re.sub(r'[\d\W_]+$', '', clean_text).strip()
                
                # Check if it matches a trigger word exactly or starts with it
                for tw in TRIGGER_WORDS:
                    if clean_text == tw or clean_text.startswith(tw + "\n"):
                        trigger_found = True
                        trigger_page_idx = p_idx
                        trigger_block_idx = b_idx
                        break
                
                if trigger_found:
                    break
                    
        if not trigger_found:
            doc.close()
            return []
            
        # 2. Trovare la dimensione del font (size) del primo blocco utile 
        # subito dopo il titolo della bibliografia
        target_font_size = None
        
        for p_idx in range(trigger_page_idx, num_pages):
            blocks = pages_data.get(p_idx, doc[p_idx].get_text("dict")).get("blocks", [])
            start_b_idx = trigger_block_idx + 1 if p_idx == trigger_page_idx else 0
            
            for b_idx in range(start_b_idx, len(blocks)):
                block = blocks[b_idx]
                if block.get("type") != 0:
                    continue
                    
                # Cerca il primo span di testo valido
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "").strip()
                        if text and len(text) > 3:  # ignore empty or very short strings (e.g. page numbers)
                            target_font_size = span.get("size")
                            break
                    if target_font_size is not None:
                        break
                if target_font_size is not None:
                    break
            if target_font_size is not None:
                break
                
        if target_font_size is None:
            doc.close()
            return []
            
        # 3. Estrazione dei blocchi con quella specifica dimensione del font (+/- 0.5)
        extracted_blocks = []
        
        for p_idx in range(trigger_page_idx, num_pages):
            blocks = pages_data.get(p_idx, doc[p_idx].get_text("dict")).get("blocks", [])
            start_b_idx = trigger_block_idx + 1 if p_idx == trigger_page_idx else 0
            
            for b_idx in range(start_b_idx, len(blocks)):
                block = blocks[b_idx]
                if block.get("type") != 0:
                    continue
                
                block_valid_text = ""
                has_target_font = False
                
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        size = span.get("size")
                        text = span.get("text", "")
                        
                        # Check size within +/- 0.5
                        if abs(size - target_font_size) <= 0.5:
                            has_target_font = True
                            block_valid_text += text + " "
                            
                if has_target_font:
                    cleaned_text = block_valid_text.strip()
                    # Rimuoviamo gli a capo superflui per ricomporre il blocco
                    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
                    if cleaned_text:
                        extracted_blocks.append(cleaned_text)
                        
        doc.close()
        
        return [b for b in extracted_blocks if len(b) > 10]
