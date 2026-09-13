"""
import_review_dialog.py — Review dialog for auto-imported entries.

Shows extracted metadata with per-field confidence badges.
User can edit fields before accepting, and corrections are recorded
for the learning system.
"""
from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QPushButton, QWidget, QScrollArea,
    QSizePolicy, QFrame,
)
from PySide6.QtCore import Qt, Signal

from app.services.import_pipeline import ImportResult
from app.theme import icon
from app.i18n import LanguageManager


def _confidence_badge(confidence: float, source: str = "") -> QLabel:
    """Create a colored confidence badge label."""
    if confidence >= 0.80:
        color = "#22c55e"
        icon_txt = "✅"
    elif confidence >= 0.50:
        color = "#f59e0b"
        icon_txt = "⚠️"
    else:
        color = "#ef4444"
        icon_txt = "❌"

    text = f"{icon_txt} {confidence:.0%}"
    if source:
        text += f" ({source})"

    lbl = QLabel(text)
    lbl.setProperty("class", "dialogMutedText")
    lbl.setFixedWidth(130)
    return lbl


class ImportReviewDialog(QDialog):
    """
    Shows auto-imported metadata with confidence indicators.
    User can edit fields. Corrections are recorded for learning.

    Signals
    -------
    accepted : int, dict
        Emitted with (entry_id, corrected_data) when user clicks Accept.
    skipped : int
        Emitted with entry_id when user clicks Skip (delete entry).
    """

    correctionsMade = Signal(int, dict, dict)  # entry_id, original, corrected

    REVIEW_FIELDS = [
        ("title", "Title:"),
        ("authors", "Authors:"),
        ("year", "Year:"),
        ("journal", "Journal:"),
        ("publisher", "Publisher:"),
        ("doi", "DOI:"),
        ("volume", "Volume:"),
        ("issue", "Issue:"),
        ("pages", "Pages:"),
        ("url", "URL:"),
    ]

    def __init__(self, result: ImportResult, lang: LanguageManager, parent=None):
        super().__init__(parent)
        self._result = result
        self._lang = lang
        self._fields: dict[str, QLineEdit] = {}
        self._original_data = dict(result.metadata)

        self.setWindowTitle("Review Import")
        self.setWindowIcon(icon("sparkles"))
        self.setMinimumWidth(600)
        self.setMinimumHeight(450)
        self.setModal(True)

        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        # Header
        header = QLabel(f"📋  Review: {self._result.filename}")
        header.setProperty("class", "dialogHeaderTitle")
        header.setWordWrap(True)
        root.addWidget(header)

        # Source info
        source_lbl = QLabel(f"Primary source: {self._result.source or 'unknown'}")
        source_lbl.setProperty("class", "dialogMutedText")
        root.addWidget(source_lbl)

        # Warnings
        if self._result.warnings:
            for w in self._result.warnings[:5]:
                wlbl = QLabel(f"⚠️ {w}")
                wlbl.setProperty("class", "dialogWarningText")
                wlbl.setWordWrap(True)
                root.addWidget(wlbl)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setProperty("class", "dialogSeparator")
        root.addWidget(sep)

        # Scrollable form
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        form_w = QWidget()
        form = QFormLayout(form_w)
        form.setSpacing(8)
        form.setContentsMargins(0, 0, 0, 0)

        for field_key, label_text in self.REVIEW_FIELDS:
            value = str(self._result.metadata.get(field_key, ""))
            conf = self._result.confidence.get(field_key, 0.0)
            source = ""  # Could get from source_map if available

            # Row: [confidence badge] [label] [line edit]
            row = QHBoxLayout()
            row.setSpacing(6)

            badge = _confidence_badge(conf, source)
            row.addWidget(badge)

            le = QLineEdit(value)
            le.setMinimumWidth(300)
            self._fields[field_key] = le
            row.addWidget(le, 1)

            form.addRow(QLabel(label_text), row)

        scroll.setWidget(form_w)
        root.addWidget(scroll, 1)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_skip = QPushButton("🗑  Skip (Delete)")
        btn_skip.setStyleSheet(
            "QPushButton { color: #ef4444; border: 1px solid #ef4444; "
            "border-radius: 6px; padding: 8px 16px; background: transparent; }"
            "QPushButton:hover { background: rgba(239, 68, 68, 0.1); }"
        )
        btn_skip.clicked.connect(self._on_skip)
        btn_row.addWidget(btn_skip)

        btn_row.addStretch()

        btn_accept = QPushButton("✅  Accept & Save")
        btn_accept.setProperty("class", "dialogPrimaryButton")
        btn_accept.setDefault(True)
        btn_accept.clicked.connect(self._on_accept)
        btn_row.addWidget(btn_accept)

        root.addLayout(btn_row)

    def _on_accept(self):
        """Collect edited fields and emit corrections if any changed."""
        corrected = {}
        for field_key, le in self._fields.items():
            corrected[field_key] = le.text().strip()

        # Check for corrections
        if corrected != self._original_data:
            self.correctionsMade.emit(
                self._result.entry_id,
                self._original_data,
                corrected,
            )

        self.accept()

    def _on_skip(self):
        self.reject()

    def get_corrected_data(self) -> dict:
        """Return the user-edited field values."""
        return {k: le.text().strip() for k, le in self._fields.items()}
