"""
style_editor.py — DropTextEdit widget and CustomStyleEditorDialog.
Allows users to create and edit custom citation style templates.
"""
import json
import re

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QLineEdit, QTextEdit, QMessageBox,
    QAbstractItemView,
)
from PySide6.QtCore import Qt, QSettings, QDataStream, QIODevice

from app.citation_engine import CitationStyleEngine
from app.i18n import LanguageManager


# ─────────────────────────────────────────────────────────────────────────────
#  SYNTAX HIGHLIGHTER
# ─────────────────────────────────────────────────────────────────────────────
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QColor, QFont

class TemplateHighlighter(QSyntaxHighlighter):
    """Highlights {fields} and HTML tags in the custom template editor."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._field_format = QTextCharFormat()
        self._field_format.setForeground(QColor("#a78bfa"))
        self._field_format.setFontWeight(QFont.Bold)
        
        self._tag_format = QTextCharFormat()
        self._tag_format.setForeground(QColor("#10b981"))
        
    def highlightBlock(self, text: str):
        # Highlight {fields}
        for match in re.finditer(r'\{[^}]+\}', text):
            self.setFormat(match.start(), match.end() - match.start(), self._field_format)
            
        # Highlight HTML tags <b>, <i>, </b>, </i>
        for match in re.finditer(r'</?[bi]>', text):
            self.setFormat(match.start(), match.end() - match.start(), self._tag_format)

# ─────────────────────────────────────────────────────────────────────────────
#  DROP-AWARE TEXT EDIT
# ─────────────────────────────────────────────────────────────────────────────
class DropTextEdit(QTextEdit):
    """QTextEdit that accepts drops from QListWidget and inserts {field} tokens."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if (event.mimeData().hasText()
                or event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist")):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if (event.mimeData().hasText()
                or event.mimeData().hasFormat("application/x-qabstractitemmodeldatalist")):
            event.acceptProposedAction()
            cursor = self.cursorForPosition(event.position().toPoint())
            self.setTextCursor(cursor)
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        md   = event.mimeData()
        text = ""
        if md.hasFormat("application/x-qabstractitemmodeldatalist"):
            data   = md.data("application/x-qabstractitemmodeldatalist")
            stream = QDataStream(data, QIODevice.ReadOnly)
            while not stream.atEnd():
                _row      = stream.readInt32()
                _col      = stream.readInt32()
                map_count = stream.readInt32()
                for _ in range(map_count):
                    role  = stream.readInt32()
                    value = stream.readQVariant()
                    if role == Qt.DisplayRole:
                        text = "{" + str(value) + "}"
        elif md.hasText():
            text = md.text()

        if text:
            cursor = self.cursorForPosition(event.position().toPoint())
            self.setTextCursor(cursor)
            cursor.insertText(text)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


# ─────────────────────────────────────────────────────────────────────────────
#  CUSTOM STYLE EDITOR DIALOG
# ─────────────────────────────────────────────────────────────────────────────
class CustomStyleEditorDialog(QDialog):
    def __init__(self, lang_mgr: LanguageManager, parent=None):
        super().__init__(parent)
        self._lang = lang_mgr
        self.setWindowTitle(self._lang.tr("style_editor_title"))
        self.setMinimumSize(820, 520)
        self._settings = QSettings("CiteMind", "CiteMind")

        raw_styles = self._settings.value("custom_styles", "{}")
        try:
            self._styles = json.loads(raw_styles)
        except Exception:
            self._styles = {}

        self._build_ui()
        self._refresh_list()

    def _build_ui(self):
        root = QHBoxLayout(self)

        # ── Left: list of saved styles ────────────────────────────────────
        left = QVBoxLayout()
        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_select)

        btn_h = QHBoxLayout()
        self._btn_add = QPushButton(self._lang.tr("style_editor_btn_new"))
        self._btn_del = QPushButton(self._lang.tr("style_editor_btn_delete"))
        self._btn_add.clicked.connect(self._on_add)
        self._btn_del.clicked.connect(self._on_del)
        btn_h.addWidget(self._btn_add)
        btn_h.addWidget(self._btn_del)

        left.addWidget(QLabel(self._lang.tr("style_editor_my_styles")))
        left.addWidget(self._list)
        left.addLayout(btn_h)
        root.addLayout(left, 1)

        # ── Middle: editor + preview ──────────────────────────────────────
        mid = QVBoxLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText(self._lang.tr("style_editor_name_placeholder"))

        self._template_edit = DropTextEdit()
        self._highlighter = TemplateHighlighter(self._template_edit.document())
        self._template_edit.setPlaceholderText(
            self._lang.tr("style_editor_template_placeholder")
        )
        self._template_edit.setStyleSheet("font-size: 14px;")

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        self._preview.setStyleSheet("padding: 8px; border: 1px solid #555;")

        btn_save = QPushButton(self._lang.tr("style_editor_btn_save"))
        btn_save.setObjectName("btnPrimary")
        btn_save.clicked.connect(self._on_save_current)

        self._template_edit.textChanged.connect(self._update_preview)

        mid.addWidget(QLabel(self._lang.tr("style_editor_name")))
        mid.addWidget(self._name_edit)
        mid.addWidget(QLabel(self._lang.tr("style_editor_template")))
        mid.addWidget(self._template_edit)
        mid.addWidget(QLabel(self._lang.tr("style_editor_preview")))
        mid.addWidget(self._preview)
        mid.addWidget(btn_save)
        root.addLayout(mid, 2)

        # ── Right: field palette ──────────────────────────────────────────
        right = QVBoxLayout()
        right.addWidget(QLabel(self._lang.tr("style_editor_fields")))

        self._field_list = QListWidget()
        self._field_list.setDragEnabled(True)
        self._field_list.setDragDropMode(QAbstractItemView.DragOnly)
        self._field_list.setDefaultDropAction(Qt.CopyAction)
        self._field_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._field_list.itemDoubleClicked.connect(self._on_field_dblclick)

        for f in ["authors", "year", "title", "journal", "publisher",
                  "volume", "issue", "pages", "doi", "url", "access_date", "notes"]:
            item = QListWidgetItem(f)
            item.setData(Qt.UserRole, f)
            self._field_list.addItem(item)

        right.addWidget(self._field_list)
        right.addWidget(QLabel(self._lang.tr("style_editor_instructions")))
        root.addLayout(right, 1)

    def _on_field_dblclick(self, item):
        field_name = item.data(Qt.UserRole) or item.text()
        self._template_edit.insertPlainText("{" + field_name + "}")
        self._template_edit.setFocus()

    def _refresh_list(self):
        self._list.clear()
        self._list.addItems(self._styles.keys())

    def _on_select(self, item):
        if not item:
            return
        name = item.text()
        self._name_edit.setText(name)
        self._template_edit.setPlainText(self._styles.get(name, ""))
        self._update_preview()

    def _on_add(self):
        self._name_edit.clear()
        self._template_edit.clear()
        self._name_edit.setFocus()

    def _on_del(self):
        item = self._list.currentItem()
        if not item:
            return
        name = item.text()
        if name in self._styles:
            del self._styles[name]
        self._save_to_settings()
        self._refresh_list()
        self._name_edit.clear()
        self._template_edit.clear()

    def _on_save_current(self):
        name = self._name_edit.text().strip()
        tpl  = self._template_edit.toPlainText().strip()
        if not name or not tpl:
            QMessageBox.warning(self, self._lang.tr("style_editor_error_title"), self._lang.tr("style_editor_error_text"))
            return
        self._styles[name] = tpl
        self._save_to_settings()
        self._refresh_list()
        items = self._list.findItems(name, Qt.MatchExactly)
        if items:
            self._list.setCurrentItem(items[0])
        QMessageBox.information(self, self._lang.tr("style_editor_saved_title"), self._lang.tr("style_editor_saved_text").format(name=name))

    def _save_to_settings(self):
        self._settings.setValue("custom_styles", json.dumps(self._styles))
        CitationStyleEngine.load_custom_styles(self._styles)

    def _update_preview(self):
        tpl = self._template_edit.toPlainText()
        mock = {
            "authors": "Doe, J.", "year": "2024",
            "title": "Example Title of the Article",
            "journal": "Science Journal", "publisher": "Nature Pub.",
            "volume": "5", "issue": "2",
        }
        # Use CitationStyleEngine logic for consistency
        runs = CitationStyleEngine._get_strategy("preview")._custom_format(mock, tpl) if hasattr(CitationStyleEngine._get_strategy("preview"), '_custom_format') else []
        if not runs:
            # fallback to direct parsing
            from app.citation_engine import CustomStyle
            cs = CustomStyle("preview", tpl)
            runs = cs.format_bibliography(mock)

        html = ""
        for text, is_bold, is_italic in runs:
            # Escape HTML characters
            import html as html_lib
            safe = html_lib.escape(text)
            if is_bold:
                safe = f"<b>{safe}</b>"
            if is_italic:
                safe = f"<i>{safe}</i>"
            html += safe
        self._preview.setText(html)
