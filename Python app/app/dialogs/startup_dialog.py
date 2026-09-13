"""
startup_dialog.py — StartupDialog: project picker shown at application launch.

Allows the user to:
  • Create a new .db project file
  • Open an existing .db project file
  • Re-open a recently used project from a persistent list
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QWidget, QSizePolicy,
)
from PySide6.QtCore import Qt, QSettings, QSize
from PySide6.QtGui import QFont, QPixmap, QPainter
import sqlite3

from app.theme import icon


# Maximum number of recent projects persisted
_MAX_RECENTS = 8


class StartupDialog(QDialog):
    """Project picker dialog shown at application startup."""

    def __init__(self, lang_mgr, parent=None):
        super().__init__(parent)
        self._lang = lang_mgr
        self._selected_path: Path | None = None
        self._settings = QSettings("CiteMind", "CiteMind")

        self.setWindowTitle(self._lang.tr("startup_title"))
        self.setWindowIcon(icon("LOGOsvg"))
        self.setFixedSize(600, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self._build_ui()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Header ────────────────────────────────────────────────────────
        header = QWidget()
        header.setObjectName("startupHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(40, 40, 40, 40)
        header_layout.setSpacing(24)
        
        logo_label = QLabel()
        logo_label.setObjectName("startupLogo")
        logo_label.setPixmap(icon("LOGOsvg").pixmap(80, 80))
        logo_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(logo_label)

        vbox = QVBoxLayout()
        vbox.setSpacing(4)
        title = QLabel(self._lang.tr("app_title"))
        title.setObjectName("startupTitle")
        title.setFont(QFont("Segoe UI", 32, QFont.Bold))
        vbox.addWidget(title)

        subtitle = QLabel(self._lang.tr("app_subtitle"))
        subtitle.setObjectName("startupSubtitle")
        vbox.addWidget(subtitle)
        
        author = QLabel("Mattia Curto")
        author.setObjectName("startupAuthor")
        vbox.addWidget(author)
        
        header_layout.addLayout(vbox)
        header_layout.addStretch()
        root.addWidget(header)

        # ── Body ──────────────────────────────────────────────────────────
        body_widget = QWidget()
        body_widget.setObjectName("startupBody")
        body = QVBoxLayout(body_widget)
        body.setContentsMargins(36, 28, 36, 28)
        body.setSpacing(16)

        # Action buttons row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(16)

        btn_new = QPushButton(icon("folder-plus"), self._lang.tr("startup_new_project"))
        btn_new.setObjectName("btnPrimary")
        btn_new.setMinimumHeight(48)
        btn_new.setCursor(Qt.PointingHandCursor)
        btn_new.clicked.connect(self._on_new)
        btn_row.addWidget(btn_new)

        btn_open = QPushButton(icon("books"), self._lang.tr("startup_open_project"))
        btn_open.setObjectName("btnSecondary")
        btn_open.setMinimumHeight(48)
        btn_open.setCursor(Qt.PointingHandCursor)
        btn_open.clicked.connect(self._on_open)
        btn_row.addWidget(btn_open)

        body.addLayout(btn_row)

        # Recent projects section
        lbl_recent = QLabel(self._lang.tr("startup_recent"))
        lbl_recent.setObjectName("sectionTitle")
        body.addWidget(lbl_recent)

        self._recent_list = QListWidget()
        self._recent_list.setSelectionMode(QListWidget.SingleSelection)
        self._recent_list.itemDoubleClicked.connect(self._on_recent_double_click)
        self._recent_list.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body.addWidget(self._recent_list)

        # Bottom row: remove recent + open selected
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        btn_remove = QPushButton(icon("trash"), self._lang.tr("startup_remove_recent"))
        btn_remove.setObjectName("btnSecondary")
        btn_remove.setToolTip(self._lang.tr("startup_remove_recent_tip"))
        btn_remove.setCursor(Qt.PointingHandCursor)
        btn_remove.clicked.connect(self._on_remove_recent)
        bottom.addWidget(btn_remove)

        bottom.addStretch()
        
        btn_exit = QPushButton(icon("x"), "Close")
        btn_exit.setObjectName("btnDanger")
        btn_exit.setCursor(Qt.PointingHandCursor)
        btn_exit.clicked.connect(self.reject)
        bottom.addWidget(btn_exit)

        btn_open_sel = QPushButton(icon("books"), self._lang.tr("startup_open_selected"))
        btn_open_sel.setObjectName("btnPrimary")
        btn_open_sel.setCursor(Qt.PointingHandCursor)
        btn_open_sel.clicked.connect(self._on_open_selected)
        btn_open_sel.setMinimumWidth(120)
        bottom.addWidget(btn_open_sel)

        body.addLayout(bottom)
        root.addWidget(body_widget)

        self._populate_recents()

    # ── recent projects helpers ───────────────────────────────────────────
    def _get_recents(self) -> list[str]:
        raw = self._settings.value("recent_projects", [])
        if isinstance(raw, str):
            return [raw] if raw else []
        return list(raw) if raw else []

    def _save_recents(self, recents: list[str]):
        self._settings.setValue("recent_projects", recents[:_MAX_RECENTS])

    def _populate_recents(self):
        self._recent_list.clear()
        recents = self._get_recents()
        if not recents:
            item = QListWidgetItem(self._lang.tr("startup_no_recents"))
            item.setFlags(Qt.NoItemFlags)
            self._recent_list.addItem(item)
            return
        for path_str in recents:
            p = Path(path_str)
            item = QListWidgetItem()
            item.setData(Qt.UserRole, path_str)
            item.setSizeHint(QSize(0, 64))
            self._recent_list.addItem(item)
            
            w = QWidget()
            l = QVBoxLayout(w)
            l.setContentsMargins(8, 4, 8, 4)
            l.setSpacing(2)
            
            title = QLabel(p.name)
            title.setObjectName("startupProjectTitle")
            
            subtitle = QLabel(str(p.parent))
            subtitle.setObjectName("startupProjectSubtitle")
            
            exists = p.exists()
            if not exists:
                title.setProperty("error", True)
                subtitle.setText(self._lang.tr("startup_file_missing"))
                item.setToolTip(self._lang.tr("startup_file_missing"))
            else:
                item.setToolTip(str(p))
                try:
                    conn = sqlite3.connect(path_str)
                    cursor = conn.execute("SELECT COUNT(*) FROM entries")
                    count = cursor.fetchone()[0]
                    conn.close()
                    stats = QLabel(f"{count} {self._lang.tr('entries').lower()}")
                    stats.setObjectName("startupProjectStats")
                    
                    row = QHBoxLayout()
                    row.addWidget(title)
                    row.addStretch()
                    row.addWidget(stats)
                    l.addLayout(row)
                except Exception:
                    l.addWidget(title)
            
            if not exists or 'row' not in locals():
                l.addWidget(title)
                
            l.addWidget(subtitle)
            self._recent_list.setItemWidget(item, w)

    # ── actions ───────────────────────────────────────────────────────────
    def _on_new(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._lang.tr("dialog_new_archive"),
            str(Path.home()),
            self._lang.tr("dialog_db_files"),
        )
        if path:
            if not path.endswith(".db"):
                path += ".db"
            self._selected_path = Path(path)
            self._add_to_recents(path)
            self.accept()

    def _on_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._lang.tr("dialog_open_archive"),
            str(Path.home()),
            self._lang.tr("dialog_db_files"),
        )
        if path:
            self._selected_path = Path(path)
            self._add_to_recents(path)
            self.accept()

    def _on_recent_double_click(self, item: QListWidgetItem):
        path_str = item.data(Qt.UserRole)
        if not path_str:
            return
        p = Path(path_str)
        if not p.exists():
            # Remove stale entry
            recents = self._get_recents()
            recents = [r for r in recents if r != path_str]
            self._save_recents(recents)
            self._populate_recents()
            return
        self._selected_path = p
        self._add_to_recents(path_str)
        self.accept()

    def _on_open_selected(self):
        item = self._recent_list.currentItem()
        if item:
            self._on_recent_double_click(item)

    def _on_remove_recent(self):
        item = self._recent_list.currentItem()
        if not item:
            return
        path_str = item.data(Qt.UserRole)
        if not path_str:
            return
        recents = self._get_recents()
        recents = [r for r in recents if r != path_str]
        self._save_recents(recents)
        self._populate_recents()

    def _add_to_recents(self, path_str: str):
        recents = self._get_recents()
        # Move to top if already present
        recents = [r for r in recents if r != path_str]
        recents.insert(0, path_str)
        self._save_recents(recents)

    # ── public API ────────────────────────────────────────────────────────
    def selected_path(self) -> Path | None:
        return self._selected_path

    # ── class helper for recents management from outside ──────────────────
    @staticmethod
    def add_recent_project(path_str: str):
        """Add a project path to the recent list (called from MainWindow)."""
        settings = QSettings("CiteMind", "CiteMind")
        raw = settings.value("recent_projects", [])
        if isinstance(raw, str):
            recents = [raw] if raw else []
        else:
            recents = list(raw) if raw else []
        recents = [r for r in recents if r != path_str]
        recents.insert(0, path_str)
        settings.setValue("recent_projects", recents[:_MAX_RECENTS])
