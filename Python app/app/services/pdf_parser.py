import fitz  # PyMuPDF
import re
from typing import List, Dict, Any
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

class PdfMetadataExtractor:
    """Extracts basic metadata from PDF file properties."""
    def extract(self, pdf_path: str) -> PdfMetadata:
        meta = PdfMetadata()
        try:
            doc = fitz.open(pdf_path)
            info = doc.metadata
            if info:
                meta.title = info.get("title", "")
                meta.authors = info.get("author", "")
                
                # very basic confidence
                if meta.title:
                    meta.confidence["title"] = 0.5
                if meta.authors:
                    meta.confidence["authors"] = 0.5
            doc.close()
        except Exception:
            pass
        return meta

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
