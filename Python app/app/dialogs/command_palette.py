"""
command_palette.py — Implements a VSCode-like command palette (Ctrl+Shift+P)
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QAbstractItemView
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QShortcut, QKeySequence

from app.theme import icon

class CommandPalette(QDialog):
    """
    A quick-action palette for executing commands.
    """
    def __init__(self, parent=None, commands=None):
        """
        commands: list of dicts like:
        [{"name": "New Bibliography Entry", "icon": "book-upload", "action": callback}]
        """
        super().__init__(parent)
        self.setWindowFlags(Qt.Popup | Qt.FramelessWindowHint)
        self.setFixedSize(500, 350)
        self._commands = commands or []
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Type a command...")
        self.search_box.setStyleSheet("""
            QLineEdit {
                padding: 12px;
                font-size: 16px;
                border: none;
                border-bottom: 1px solid #333;
                background: transparent;
            }
        """)
        self.search_box.textChanged.connect(self._filter_commands)
        
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_widget.setStyleSheet("""
            QListWidget {
                border: none;
                font-size: 14px;
                padding: 8px;
            }
            QListWidget::item {
                padding: 8px;
            }
        """)
        self.list_widget.itemActivated.connect(self._execute_selected)
        
        layout.addWidget(self.search_box)
        layout.addWidget(self.list_widget)
        
        self.search_box.installEventFilter(self)
        self._populate_list(self._commands)
        
    def _populate_list(self, cmds):
        self.list_widget.clear()
        for cmd in cmds:
            item = QListWidgetItem(cmd["name"])
            if cmd.get("icon"):
                item.setIcon(icon(cmd["icon"]))
            item.setData(Qt.UserRole, cmd)
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _filter_commands(self, text):
        if not text.strip():
            self._populate_list(self._commands)
            return
        
        filtered = [
            c for c in self._commands 
            if text.lower() in c["name"].lower()
        ]
        self._populate_list(filtered)

    def eventFilter(self, obj, event):
        if obj == self.search_box and event.type() == QKeyEvent.KeyPress:
            if event.key() == Qt.Key_Down:
                row = self.list_widget.currentRow()
                if row < self.list_widget.count() - 1:
                    self.list_widget.setCurrentRow(row + 1)
                return True
            elif event.key() == Qt.Key_Up:
                row = self.list_widget.currentRow()
                if row > 0:
                    self.list_widget.setCurrentRow(row - 1)
                return True
            elif event.key() == Qt.Key_Return:
                self._execute_selected(self.list_widget.currentItem())
                return True
            elif event.key() == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def _execute_selected(self, item):
        if not item:
            return
        cmd = item.data(Qt.UserRole)
        self.accept()
        if "action" in cmd and callable(cmd["action"]):
            cmd["action"]()

    def showEvent(self, event):
        super().showEvent(event)
        self.search_box.clear()
        self.search_box.setFocus()
        
        # Center on parent
        if self.parent():
            parent_geom = self.parent().geometry()
            x = parent_geom.x() + (parent_geom.width() - self.width()) // 2
            y = parent_geom.y() + (parent_geom.height() - self.height()) // 2
            # Adjust to appear near the top like VSCode
            y = parent_geom.y() + 80
            self.move(x, y)
