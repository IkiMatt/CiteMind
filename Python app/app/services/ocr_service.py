"""Create searchable PDF copies using Tesseract through OCRmyPDF."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


OCR_LANGUAGES = "ita+eng+fra+deu"


def create_searchable_pdf(pdf_path: str) -> str:
    source = Path(pdf_path)
    if not source.exists():
        raise FileNotFoundError(f"PDF non trovato: {pdf_path}")

    output = source.with_name(f"{source.stem}_ocr.pdf")
    if output.exists():
        output.unlink()

    command = [
        sys.executable,
        "-m",
        "ocrmypdf",
        "--skip-text",
        "--deskew",
        "-l",
        OCR_LANGUAGES,
        str(source),
        str(output),
    ]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail or "OCR non riuscito.")
    if not output.exists():
        raise RuntimeError("OCR completato senza creare il PDF risultante.")
    return str(output)