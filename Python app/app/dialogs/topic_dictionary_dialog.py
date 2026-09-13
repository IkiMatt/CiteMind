from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QLineEdit,
    QPushButton,
    QMessageBox,
)

from app.graph.keyword_extractor import normalize_topic_label


class TopicDictionaryDialog(QDialog):
    """Dialog for standardizing and managing the canonical topic dictionary."""

    _ALIASES = {
        "archaeological": "archaeology",
        "historical": "history",
        "artistic": "art",
        "classical": "classical archaeology",
        "digital": "digital humanities",
    }

    def __init__(self, model, parent=None):
        super().__init__(parent)
        self._model = model
        self.setWindowTitle("Topic Dictionary")
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header = QLabel("Canonical topic dictionary")
        header.setStyleSheet("font-size: 15px; font-weight: 700;")
        layout.addWidget(header)

        self._info = QLabel(
            "Standardize all AI topics. Rename a topic here and it will be applied to every matching record."
        )
        self._info.setWordWrap(True)
        self._info.setStyleSheet("color: #a7a9c2; font-size: 11px;")
        layout.addWidget(self._info)

        self._list = QListWidget()
        self._list.setAlternatingRowColors(True)
        self._list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._list)

        controls = QHBoxLayout()
        controls.setSpacing(8)

        self._rename_edit = QLineEdit()
        self._rename_edit.setPlaceholderText("Canonical label")
        self._rename_edit.setEnabled(False)

        self._apply_btn = QPushButton("Apply rename")
        self._apply_btn.setEnabled(False)
        self._apply_btn.clicked.connect(self._apply_rename)

        controls.addWidget(self._rename_edit)
        controls.addWidget(self._apply_btn)
        layout.addLayout(controls)

        self._reload_topics()

    def _canonicalize_topic(self, value: str) -> str:
        text = normalize_topic_label(value or "")
        if not text:
            return ""
        text = text.strip().lower()
        alias = self._ALIASES.get(text)
        if alias:
            return alias
        return text

    def _collect_topics(self) -> dict[str, list[str]]:
        entries = self._model.read_all()
        grouped: dict[str, list[str]] = defaultdict(list)

        for entry in entries:
            topics = entry.get("ai_topics", [])
            if isinstance(topics, str):
                import json
                try:
                    topics = json.loads(topics)
                except Exception:
                    topics = []

            if not isinstance(topics, (list, tuple)):
                continue

            for item in topics:
                label = str(item).strip()
                if not label:
                    continue
                canonical = self._canonicalize_topic(label)
                if canonical:
                    grouped[canonical].append(label)

        return dict(sorted(grouped.items()))

    def _reload_topics(self):
        topics = self._collect_topics()
        self._list.clear()
        for canonical, variants in topics.items():
            count = len(variants)
            label = f"{canonical} ({count})"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, canonical)
            self._list.addItem(item)

        if self._list.count() == 0:
            self._rename_edit.clear()
            self._rename_edit.setEnabled(False)
            self._apply_btn.setEnabled(False)
            self._info.setText("No AI topics found yet. Generate some from the AI Notes screen first.")
            return

        self._info.setText(
            "Standardize all AI topics. Rename a term here and it will be propagated to every record using that variant."
        )
        self._list.setCurrentRow(0)

    def _on_selection_changed(self):
        current = self._list.currentItem()
        if current is None:
            self._rename_edit.setEnabled(False)
            self._apply_btn.setEnabled(False)
            return

        canonical = current.data(Qt.UserRole)
        self._rename_edit.setText(str(canonical))
        self._rename_edit.setEnabled(True)
        self._apply_btn.setEnabled(True)

    def _apply_rename(self):
        current = self._list.currentItem()
        if current is None:
            return

        old_label = current.data(Qt.UserRole)
        new_label = self._rename_edit.text().strip()
        if not new_label:
            QMessageBox.warning(self, "Topic dictionary", "Insert a valid canonical label.")
            return

        if old_label == new_label:
            return

        entries = self._model.read_all()
        changed = 0
        for entry in entries:
            topics = entry.get("ai_topics", [])
            if isinstance(topics, str):
                import json
                try:
                    topics = json.loads(topics)
                except Exception:
                    topics = []

            if not isinstance(topics, (list, tuple)):
                continue

            updated = []
            for topic in topics:
                value = str(topic).strip()
                if not value:
                    continue
                if self._canonicalize_topic(value) == old_label:
                    updated.append(new_label)
                else:
                    updated.append(value)

            if updated != list(topics):
                self._model.save_ai_topics(entry["id"], updated)
                changed += 1

        QMessageBox.information(
            self,
            "Topic dictionary",
            f"Updated {changed} record(s) from '{old_label}' to '{new_label}'.",
        )
        self._reload_topics()
