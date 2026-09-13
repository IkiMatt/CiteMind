"""
entry_table.py — EntryTableWidget: A customizable list/table for displaying entries.
"""
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QWidget, QHBoxLayout, 
    QCheckBox, QLabel, QPushButton
)
from PySide6.QtCore import Qt, Signal, QSize, QVariantAnimation, QObject
from PySide6.QtGui import QColor

from app.theme import icon, get_global_theme, DARK_TOKENS, LIGHT_TOKENS
from app.i18n import LanguageManager


class RowWidget(QWidget):
    """Custom widget to handle hover animations."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("rowContainer")
        self.setAttribute(Qt.WA_Hover)
        
        self._bg_color = QColor(0, 0, 0, 0)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(150)
        self._anim.valueChanged.connect(self._on_bg_changed)
        
    def _on_bg_changed(self, color):
        self._bg_color = color
        self.setStyleSheet(f"#rowContainer {{ background-color: rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()}); border-radius: 6px; }}")

    def enterEvent(self, event):
        dark = get_global_theme() == "dark"
        target = QColor(DARK_TOKENS.list_item_hover_bg) if dark else QColor(LIGHT_TOKENS.list_item_hover_bg)
        
        self._anim.stop()
        self._anim.setStartValue(self._bg_color)
        self._anim.setEndValue(target)
        self._anim.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._anim.stop()
        self._anim.setStartValue(self._bg_color)
        self._anim.setEndValue(QColor(0, 0, 0, 0))
        self._anim.start()
        super().leaveEvent(event)


class EntryTableWidget(QListWidget):
    """
    Displays the list of bibliographic entries with inline actions.
    """
    
    entrySelected = Signal(int)
    readStatusChanged = Signal(int, int)
    pdfOpenRequested = Signal(str)
    pdfUnlinkRequested = Signal(int)
    pdfLinkRequested = Signal(int)

    def __init__(self, lang_mgr: LanguageManager, parent=None):
        super().__init__(parent)
        self._lang = lang_mgr
        self.setSelectionMode(QListWidget.SingleSelection)
        self.currentItemChanged.connect(self._on_item_changed)

    def _on_item_changed(self, current: QListWidgetItem | None, previous: QListWidgetItem | None):
        if current is None:
            self.entrySelected.emit(-1)
        else:
            entry_id = current.data(Qt.UserRole)
            if entry_id is not None:
                self.entrySelected.emit(entry_id)

    def populate(self, entries: list[dict], theme_colors: dict, prev_id: int | None = None):
        """Populates the list with the given entries."""
        self.blockSignals(True)
        self.clear()

        for e in entries:
            label   = e.get("authors") or e.get("title") or "(untitled)"
            year    = e.get("year", "")
            display = label + (f"  ({year})" if year else "")

            item = QListWidgetItem()
            item.setData(Qt.UserRole, e["id"])
            et_val = e.get("entry_type", "bibliography")

            w = RowWidget()
            l = QHBoxLayout(w)
            l.setContentsMargins(8, 4, 8, 4)
            l.setSpacing(8)

            chk = QCheckBox("")
            chk.setChecked(bool(e.get("is_read", 0)))
            chk.setToolTip(self._lang.tr("tip_mark_read"))
            chk.setCursor(Qt.PointingHandCursor)
            chk.setMinimumWidth(20)
            chk.stateChanged.connect(
                lambda state, eid=e["id"]: self.readStatusChanged.emit(eid, 1 if state else 0)
            )
            l.addWidget(chk)

            lbl = QLabel(display)
            color = theme_colors.get(et_val, "#7c3aed")
            lbl.setStyleSheet(f"color: {color}; background: transparent; font-size: 13px;")
            lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
            l.addWidget(lbl, 1)

            # AI notes indicator
            if e.get("ai_notes"):
                ai_dot = QLabel("✨")
                ai_dot.setToolTip(self._lang.tr("tip_ai_available"))
                ai_dot.setStyleSheet("background: transparent; font-size: 11px;")
                ai_dot.setAttribute(Qt.WA_TransparentForMouseEvents)
                l.addWidget(ai_dot)

            pdf_path = e.get("pdf_path")
            if pdf_path:
                btn_pdf = QPushButton(icon("file-download"), "")
                btn_pdf.setFixedSize(QSize(24, 24))
                btn_pdf.setToolTip(self._lang.tr("tip_open_pdf").format(path=pdf_path))
                btn_pdf.setStyleSheet("border: none; background: transparent; padding: 0;")
                btn_pdf.setCursor(Qt.PointingHandCursor)
                btn_pdf.clicked.connect(lambda checked, p=pdf_path: self.pdfOpenRequested.emit(p))
                l.addWidget(btn_pdf)

                btn_unlink = QPushButton("✕")
                btn_unlink.setFixedSize(QSize(20, 20))
                btn_unlink.setToolTip(self._lang.tr("tip_unlink_pdf"))
                btn_unlink.setStyleSheet(
                    "QPushButton { border: none; background: transparent; "
                    "color: #ef4444; font-weight: bold; font-size: 12px; padding: 0; }"
                    "QPushButton:hover { color: #fca5a5; }"
                )
                btn_unlink.setCursor(Qt.PointingHandCursor)
                btn_unlink.clicked.connect(lambda checked, eid=e["id"]: self.pdfUnlinkRequested.emit(eid))
                l.addWidget(btn_unlink)
            else:
                btn_link = QPushButton(icon("folder-plus"), "")
                btn_link.setFixedSize(QSize(24, 24))
                btn_link.setToolTip(self._lang.tr("tip_link_pdf"))
                btn_link.setStyleSheet("border: none; background: transparent; padding: 0;")
                btn_link.setCursor(Qt.PointingHandCursor)
                btn_link.clicked.connect(lambda checked, eid=e["id"]: self.pdfLinkRequested.emit(eid))
                l.addWidget(btn_link)

            item.setSizeHint(QSize(50, 40))
            sublbl = e.get("title", "") if e.get("authors") else ""
            if sublbl:
                item.setToolTip(sublbl)
            
            self.addItem(item)
            self.setItemWidget(item, w)
            if e["id"] == prev_id:
                self.setCurrentItem(item)

        self.blockSignals(False)

    def select_entry(self, entry_id: int):
        for i in range(self.count()):
            item = self.item(i)
            if item.data(Qt.UserRole) == entry_id:
                self.setCurrentItem(item)
                return True
        return False
