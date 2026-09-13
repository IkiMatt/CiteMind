"""
thematic_sidebar.py — Multi-mode sortable, collapsible bibliography sidebar.

Replaces the flat QListWidget with a QTreeWidget that supports:
  - 6 sort modes (author, year, semantic relevance, cluster, centrality, date)
  - Collapsible cluster groups with colored headers
  - Entry item widgets with checkbox, PDF link, AI badge
"""
from __future__ import annotations

import os
from enum import Enum

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QPushButton, QCheckBox, QComboBox, QSizePolicy,
    QAbstractItemView, QFileDialog, QMessageBox, QToolButton
)
from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QColor, QBrush, QIcon, QPixmap, QPainter

from app.theme import icon
from app.i18n import LanguageManager


class SortMode(Enum):
    AUTHOR = "author"
    YEAR = "year"
    DATE_ADDED = "date_added"
    AI_TOPICS = "ai_topics"


# ── Display labels for sort modes ─────────────────────────────────────────────
_SORT_LABELS = {
    SortMode.AUTHOR: "📝 Author (A-Z)",
    SortMode.YEAR: "📅 Year",
    SortMode.DATE_ADDED: "🕐 Date Added",
    SortMode.AI_TOPICS: "🧠 AI Topics",
}


def _make_color_icon(hex_color: str, size: int = 12) -> QIcon:
    """Create a small colored circle icon."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(hex_color))
    p.setPen(Qt.NoPen)
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pix)


class ThematicSidebarWidget(QWidget):
    """
    Multi-mode sortable, collapsible bibliography sidebar.

    Signals
    -------
    entrySelected : int
        Emitted with entry_id when user clicks an entry.
    readStatusChanged : int, int
        Emitted with (entry_id, is_read) when read checkbox changes.
    pdfOpenRequested : str
        Emitted with pdf_path when PDF button clicked.
    pdfLinkRequested : int
        Emitted with entry_id for manual PDF linking.
    pdfUnlinkRequested : int
        Emitted with entry_id for PDF unlinking.
    """

    entrySelected = Signal(int)
    readStatusChanged = Signal(int, int)
    pdfOpenRequested = Signal(str)
    pdfLinkRequested = Signal(int)
    pdfUnlinkRequested = Signal(int)

    def __init__(self, lang: LanguageManager, parent=None):
        super().__init__(parent)
        self._lang = lang
        self._entries: list[dict] = []
        self._sort_mode = SortMode.AUTHOR
        self._current_id: int | None = None
        self._building = False
        self._theme_colors: dict[str, str] = {}

        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        # ── Sort toolbar ──────────────────────────────────────────────────
        sort_row = QHBoxLayout()
        sort_row.setContentsMargins(8, 4, 8, 0)
        sort_row.setSpacing(6)

        sort_label = QLabel(self._lang.tr("sort_by") if hasattr(self._lang, 'tr') else "Sort:")
        sort_label.setStyleSheet("font-size: 11px; color: #8888a8;")
        sort_row.addWidget(sort_label)

        self._sort_combo = QComboBox()
        self._sort_combo.setFixedHeight(26)
        for mode in SortMode:
            self._sort_combo.addItem(_SORT_LABELS[mode], mode.value)
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        sort_row.addWidget(self._sort_combo, 1)

        layout.addLayout(sort_row)

        # ── Tree widget ───────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(20)
        self._tree.setAnimated(True)
        self._tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self._tree.setRootIsDecorated(True)
        self._tree.setExpandsOnDoubleClick(True)
        self._tree.currentItemChanged.connect(self._on_item_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._tree.setStyleSheet("""
            QTreeWidget {
                border: none;
                outline: none;
            }
            QTreeWidget::item {
                padding: 2px 0;
                min-height: 32px;
            }
        """)
        layout.addWidget(self._tree, 1)

    # ── Public API ────────────────────────────────────────────────────────

    def set_entries(self, entries: list[dict], *args, **kwargs) -> None:
        """Full refresh with data."""
        self._entries = entries
        self._rebuild()

    def set_sort_mode(self, mode: SortMode) -> None:
        self._sort_mode = mode
        idx = list(SortMode).index(mode)
        self._sort_combo.blockSignals(True)
        self._sort_combo.setCurrentIndex(idx)
        self._sort_combo.blockSignals(False)
        self._rebuild()

    def set_theme_colors(self, colors: dict[str, str]) -> None:
        """Set per-entry_type color mapping from ThemeManager."""
        self._theme_colors = colors

    def select_entry(self, entry_id: int) -> None:
        """Programmatically select an entry in the tree."""
        self._current_id = entry_id
        self._select_by_id(entry_id)

    def get_count(self) -> int:
        """Return total visible entry count."""
        return len(self._entries)

    # ── Sort logic ────────────────────────────────────────────────────────

    def _on_sort_changed(self, index: int):
        mode_val = self._sort_combo.itemData(index)
        for mode in SortMode:
            if mode.value == mode_val:
                self._sort_mode = mode
                break
        self._rebuild()

    def _rebuild(self):
        """Re-sort and re-render the tree."""
        self._building = True
        prev_id = self._current_id
        self._tree.clear()

        if self._sort_mode == SortMode.AUTHOR:
            self._build_grouped_view("author", reverse=False)
        elif self._sort_mode == SortMode.YEAR:
            self._build_grouped_view("year", reverse=True)
        elif self._sort_mode == SortMode.DATE_ADDED:
            self._build_grouped_view("date_added", reverse=True)
        elif self._sort_mode == SortMode.AI_TOPICS:
            self._build_grouped_view("ai_topics", reverse=False)

        self._building = False

        # Restore selection
        if prev_id is not None:
            self._select_by_id(prev_id)

    def _build_grouped_view(self, group_field: str, reverse: bool = False):
        """Build a grouped view based on the field."""
        groups: dict[str, list[dict]] = {}

        for entry in self._entries:
            if group_field == "author":
                val = entry.get("authors", "") or entry.get("title", "")
                if val:
                    first_letter = val[0].upper()
                    if not first_letter.isalpha():
                        first_letter = "#"
                else:
                    first_letter = "Unknown"
                groups.setdefault(first_letter, []).append(entry)

            elif group_field == "year":
                val = entry.get("year", "")
                try:
                    decade = str(int(val) // 10 * 10) + "s"
                except (ValueError, TypeError):
                    decade = "Unknown"
                groups.setdefault(decade, []).append(entry)

            elif group_field == "date_added":
                val = entry.get("created_at", "")
                if val and len(val) >= 7:
                    month = val[:7]  # YYYY-MM
                else:
                    month = "Unknown"
                groups.setdefault(month, []).append(entry)

            elif group_field == "ai_topics":
                val = entry.get("ai_topics", "")
                if not val:
                    groups.setdefault("Nessun Topic", []).append(entry)
                else:
                    import json
                    try:
                        if val.strip().startswith("["):
                            topics_list = json.loads(val)
                        else:
                            topics_list = [t.strip() for t in val.split(",")]
                    except Exception:
                        topics_list = [t.strip() for t in val.split(",")]
                        
                    topics = [str(t).strip().title() for t in topics_list if str(t).strip()]
                    if not topics:
                         groups.setdefault("Nessun Topic", []).append(entry)
                    else:
                        for topic in set(topics):
                            groups.setdefault(topic, []).append(entry)

        # Sort group keys
        sorted_keys = sorted(groups.keys(), reverse=reverse)

        for key in sorted_keys:
            group_entries = groups[key]
            group_item = QTreeWidgetItem(self._tree)
            group_item.setText(0, f"{key} ({len(group_entries)})")
            group_item.setFlags(group_item.flags() & ~Qt.ItemIsSelectable)
            font = group_item.font(0)
            font.setBold(True)
            group_item.setFont(0, font)
            group_item.setExpanded(True)

            # Sort entries within the group
            def sort_key(e):
                if group_field == "year":
                    return e.get("year", "")
                elif group_field == "date_added":
                    return e.get("created_at", "")
                else:
                    return e.get("authors", "").lower()
            
            for entry in sorted(group_entries, key=sort_key, reverse=(group_field in ("year", "date_added"))):
                child = QTreeWidgetItem(group_item)
                self._configure_item(child, entry)

    # ── Item configuration ────────────────────────────────────────────────

    def _configure_item(self, item: QTreeWidgetItem, entry: dict):
        """Configure a tree item for a bibliography entry."""
        eid = entry.get("id", 0)
        item.setData(0, Qt.UserRole, eid)

        # Build display text
        authors = entry.get("authors") or entry.get("title") or "(untitled)"
        year = entry.get("year", "")
        display = authors + (f"  ({year})" if year else "")

        # Remove badge references

        # AI notes indicator
        if entry.get("ai_notes"):
            display += " ✨"

        # PDF indicator
        pdf_path = entry.get("pdf_path")
        if pdf_path:
            item.setData(0, Qt.UserRole + 1, pdf_path)
            display += " 📄"

        # Read status
        if entry.get("is_read"):
            display = "✓ " + display

        item.setText(0, display)

        # Color by entry type
        et = entry.get("entry_type", "bibliography")
        color = self._theme_colors.get(et, "#a0a0c0")
        item.setForeground(0, QBrush(QColor(color)))

        # Tooltip
        title = entry.get("title", "")
        if title and title != authors:
            item.setToolTip(0, title)

        item.setSizeHint(0, QSize(0, 34))

    # ── Selection handling ────────────────────────────────────────────────

    def _on_item_changed(self, current, previous):
        if self._building or current is None:
            return
        eid = current.data(0, Qt.UserRole)
        if eid is not None:
            self._current_id = eid
            self.entrySelected.emit(eid)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        if self._building:
            return
        eid = item.data(0, Qt.UserRole)
        if eid is not None:
            pdf_path = item.data(0, Qt.UserRole + 1)
            if pdf_path:
                self.pdfOpenRequested.emit(pdf_path)

    def _select_by_id(self, entry_id: int):
        """Find and select the tree item with the given entry_id."""
        self._tree.blockSignals(True)
        iterator = self._tree_iterator()
        for item in iterator:
            if item.data(0, Qt.UserRole) == entry_id:
                self._tree.setCurrentItem(item)
                self._tree.scrollToItem(item)
                break
        self._tree.blockSignals(False)

    def _tree_iterator(self):
        """Iterate over all items in the tree (depth-first)."""
        stack = [self._tree.topLevelItem(i) for i in range(self._tree.topLevelItemCount())]
        while stack:
            item = stack.pop(0)
            if item is None:
                continue
            yield item
            for i in range(item.childCount()):
                stack.insert(i, item.child(i))
