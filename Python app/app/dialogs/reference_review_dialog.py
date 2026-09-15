"""Manual confirmation dialog for PDF bibliography matches."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class ReferenceReviewDialog(QDialog):
    """Let the user confirm which local bibliography matches to link."""

    def __init__(self, matches: list[dict], parent=None):
        super().__init__(parent)
        self._matches = matches
        self._list = QListWidget(self)

        self.setWindowTitle("Conferma riferimenti bibliografici")
        self.setMinimumSize(680, 460)
        self.setModal(True)

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "Queste sono corrispondenze trovate nell'archivio. "
            "Seleziona solo i riferimenti verificati nel PDF."
        ))
        root.addWidget(self._list, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate()

    def _populate(self) -> None:
        for match_id in self._matches:
            entry = match_id if isinstance(match_id, dict) else {}
            entry_id = int(entry.get("id", match_id))
            title = str(entry.get("title", "Riferimento senza titolo"))
            authors = str(entry.get("authors", "")).strip()
            year = str(entry.get("year", "")).strip()
            label = title
            if authors:
                label += f" — {authors}"
            if year:
                label += f" ({year})"

            item = QListWidgetItem(self._list)
            item.setData(Qt.UserRole, entry_id)
            checkbox = QCheckBox(label, self._list)
            checkbox.setChecked(True)
            checkbox.setToolTip("Conferma questo collegamento al record locale")
            self._list.addItem(item)
            self._list.setItemWidget(item, checkbox)

    def selected_ids(self) -> list[int]:
        """Return the IDs explicitly confirmed by the user."""
        selected: list[int] = []
        for index in range(self._list.count()):
            item = self._list.item(index)
            checkbox = self._list.itemWidget(item)
            if checkbox is not None and checkbox.isChecked():
                selected.append(int(item.data(Qt.UserRole)))
        return selected
