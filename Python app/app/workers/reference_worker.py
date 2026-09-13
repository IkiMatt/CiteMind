from PySide6.QtCore import QThread, Signal
from app.services.pdf_parser import PdfReferenceParser
from app.services.fuzzy_matcher import FuzzyMatcher

class ReferenceWorker(QThread):
    """
    QThread for async processing of PDF reference extraction and fuzzy matching.
    """
    finished = Signal(list)  # emits list of matched entry IDs
    error = Signal(str)      # emits error message

    def __init__(self, pdf_path: str, db_entries: list[dict], parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path
        self.db_entries = db_entries
        self._is_cancelled = False

    def run(self):
        try:
            # 1. Parse PDF
            parser = PdfReferenceParser(self.pdf_path)
            extracted_blocks = parser.extract_references()
            
            if self._is_cancelled:
                return
                
            if not extracted_blocks:
                self.finished.emit([])
                return
                
            # 2. Fuzzy Match
            matcher = FuzzyMatcher(self.db_entries)
            matched_ids = matcher.match_blocks(extracted_blocks, threshold=85)
            
            if self._is_cancelled:
                return
                
            self.finished.emit(matched_ids)
            
        except Exception as e:
            self.error.emit(str(e))

    def cancel(self):
        self._is_cancelled = True
