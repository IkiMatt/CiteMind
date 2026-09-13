"""
import_queue_widget.py — Dockable import progress panel.

Shows a queue of files being imported with per-item status,
confidence scores, and accept/edit/skip actions.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QProgressBar, QSizePolicy,
    QFrame,
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor

from app.services.import_pipeline import ImportResult


# ── Status icons ──────────────────────────────────────────────────────────────
_STATUS_ICONS = {
    "queued": "⏳",
    "parsing": "🔄",
    "enriching": "🔍",
    "ai": "🧠",
    "done": "✅",
    "error": "❌",
    "review": "⚠️",
    "duplicate": "🔁",
}


class ImportQueueWidget(QWidget):
    """
    Shows import progress for dropped files.

    Signals
    -------
    reviewRequested : int
        Emitted with entry_id when user clicks Edit on an imported entry.
    entryClicked : int
        Emitted with entry_id when user clicks on a completed import.
    dismissed : (no args)
        Emitted when user dismisses the queue panel.
    """

    reviewRequested = Signal(int)
    entryClicked = Signal(int)
    dismissed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []  # tracking data for each queue item
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        header = QFrame()
        header.setObjectName("importQueueHeader")
        header.setStyleSheet("""
            #importQueueHeader {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1e1040, stop:1 #1a1b26);
                border-bottom: 1px solid #2a2b38;
                padding: 6px 12px;
            }
        """)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 6, 12, 6)
        header_layout.setSpacing(8)

        title = QLabel("📥 Import Queue")
        title.setStyleSheet("color: #a78bfa; font-size: 12px; font-weight: 600; background: transparent;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self._count_label = QLabel("0 items")
        self._count_label.setStyleSheet("color: #8888a8; font-size: 11px; background: transparent;")
        header_layout.addWidget(self._count_label)

        btn_clear = QPushButton("✕")
        btn_clear.setFixedSize(20, 20)
        btn_clear.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: #8888a8; font-size: 14px; }"
            "QPushButton:hover { color: #ef4444; }"
        )
        btn_clear.setCursor(Qt.PointingHandCursor)
        btn_clear.setToolTip("Clear completed imports")
        btn_clear.clicked.connect(self._clear_completed)
        header_layout.addWidget(btn_clear)

        layout.addWidget(header)

        # ── List ──────────────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.setStyleSheet("""
            QListWidget {
                border: none;
                background: #1a1b26;
            }
            QListWidget::item {
                padding: 4px 0;
                border-bottom: 1px solid #2a2b38;
            }
            QListWidget::item:hover {
                background: #252636;
            }
        """)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, 1)

    # ── Public API ────────────────────────────────────────────────────────

    def add_item(self, filename: str) -> int:
        """Add a new item to the queue. Returns the queue index."""
        idx = len(self._items)
        self._items.append({
            "filename": filename,
            "status": "queued",
            "result": None,
        })

        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 48))
        self._list.addItem(item)

        widget = self._create_item_widget(filename, "queued")
        self._list.setItemWidget(item, widget)

        self._update_count()
        return idx

    def update_status(self, idx: int, status: str, detail: str = "") -> None:
        """Update the status of a queue item."""
        if idx < 0 or idx >= len(self._items):
            return
        self._items[idx]["status"] = status

        item = self._list.item(idx)
        if item:
            filename = self._items[idx]["filename"]
            widget = self._create_item_widget(filename, status, detail)
            self._list.setItemWidget(item, widget)

    def complete_item(self, idx: int, result: ImportResult) -> None:
        """Mark an item as completed with its result."""
        if idx < 0 or idx >= len(self._items):
            return
        self._items[idx]["result"] = result

        status = "done"
        detail = ""
        if result.error:
            status = "error"
            detail = result.error[:80]
        elif result.needs_review:
            status = "review"
            detail = f"Confidence: {result.confidence.get('title', 0):.0%}"
        elif not result.entry_id and not result.entry_ids:
            status = "duplicate"
            detail = "Already in library"
        else:
            count = len(result.entry_ids) if result.entry_ids else 1
            detail = f"{count} entry(ies) imported from {result.source}"

        self.update_status(idx, status, detail)

    def clear(self) -> None:
        """Remove all items."""
        self._list.clear()
        self._items.clear()
        self._update_count()

    # ── Internal ──────────────────────────────────────────────────────────

    def _create_item_widget(self, filename: str, status: str,
                            detail: str = "") -> QWidget:
        """Create the widget for a queue item."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(w)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(8)

        # Status icon
        icon_lbl = QLabel(_STATUS_ICONS.get(status, "❓"))
        icon_lbl.setFixedWidth(22)
        icon_lbl.setStyleSheet("font-size: 14px; background: transparent;")
        layout.addWidget(icon_lbl)

        # File info
        info = QVBoxLayout()
        info.setSpacing(1)
        info.setContentsMargins(0, 0, 0, 0)

        name_lbl = QLabel(filename)
        name_lbl.setStyleSheet("color: #c8c8e0; font-size: 12px; font-weight: 500; background: transparent;")
        info.addWidget(name_lbl)

        if detail:
            detail_lbl = QLabel(detail)
            color = "#22c55e" if status == "done" else (
                "#ef4444" if status == "error" else "#f59e0b"
            )
            detail_lbl.setStyleSheet(
                f"color: {color}; font-size: 10px; background: transparent;"
            )
            info.addWidget(detail_lbl)

        layout.addLayout(info, 1)

        # Progress indicator for active items
        if status in ("parsing", "enriching", "ai"):
            prog = QProgressBar()
            prog.setRange(0, 0)  # indeterminate
            prog.setFixedSize(40, 4)
            prog.setTextVisible(False)
            prog.setStyleSheet(
                "QProgressBar { border: none; background: #2a2b38; border-radius: 2px; }"
                "QProgressBar::chunk { background: #7c3aed; border-radius: 2px; }"
            )
            layout.addWidget(prog)

        return w

    def _on_item_clicked(self, item: QListWidgetItem):
        idx = self._list.row(item)
        if idx < 0 or idx >= len(self._items):
            return
        result = self._items[idx].get("result")
        if result and result.entry_id:
            self.entryClicked.emit(result.entry_id)

    def _clear_completed(self):
        """Remove completed items from the queue."""
        indices_to_remove = []
        for i, data in enumerate(self._items):
            if data["status"] in ("done", "error", "duplicate"):
                indices_to_remove.append(i)

        for i in reversed(indices_to_remove):
            self._list.takeItem(i)
            self._items.pop(i)

        self._update_count()
        if not self._items:
            self.dismissed.emit()

    def _update_count(self):
        active = sum(1 for d in self._items if d["status"] not in ("done", "error", "duplicate"))
        total = len(self._items)
        self._count_label.setText(f"{active} active / {total} total")
