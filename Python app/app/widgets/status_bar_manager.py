"""
status_bar_manager.py — Extracts the main status bar setup from main_window.py
"""
from PySide6.QtWidgets import QStatusBar, QLabel

class StatusBarManager:
    """Manages the creation and updates of the main status bar."""

    def __init__(self, parent_window, lang_mgr, theme_mgr):
        self._window = parent_window
        self._lang = lang_mgr
        self._theme = theme_mgr
        self.status_bar = QStatusBar()
        self._window.setStatusBar(self.status_bar)
        
        self.lbl_autosave = QLabel("")
        self.lbl_autosave.setObjectName("autosaveLabel")
        
        self.lbl_stats = QLabel("")
        
        self.lbl_db = QLabel("")
        self.lbl_db.setStyleSheet("padding-right:8px; color: #8888a8; font-size: 11px;")
        
        self.lbl_theme = QLabel(f"{self._lang.tr('status_theme')}{self._theme.current.capitalize()}")
        self.lbl_theme.setStyleSheet("padding-right:8px;")
        
        self.status_bar.addPermanentWidget(self.lbl_autosave)
        self.status_bar.addPermanentWidget(self.lbl_stats)
        self.status_bar.addPermanentWidget(self.lbl_db)
        self.status_bar.addPermanentWidget(self.lbl_theme)
        self.status_bar.showMessage(self._lang.tr("status_ready"))

    def show_message(self, message: str, timeout: int = 0):
        self.status_bar.showMessage(message, timeout)

    def set_autosave(self, text: str):
        self.lbl_autosave.setText(text)

    def set_stats(self, text: str):
        self.lbl_stats.setText(text)

    def set_db_name(self, name: str):
        self.lbl_db.setText(f"📦  {name}")

    def update_theme(self):
        self.lbl_theme.setText(f"{self._lang.tr('status_theme')}{self._theme.current.capitalize()}")
