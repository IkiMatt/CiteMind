from PySide6.QtCore import QThread, Signal

from app.services.ocr_service import create_searchable_pdf


class OcrWorker(QThread):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, pdf_path: str, parent=None):
        super().__init__(parent)
        self.pdf_path = pdf_path

    def run(self):
        try:
            self.finished.emit(create_searchable_pdf(self.pdf_path))
        except Exception as exc:
            self.error.emit(str(exc))