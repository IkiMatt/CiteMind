"""
main.py — CiteMind Application entry point.

Bibliography / Sitography Manager
MVA Architecture: Model → Adapter → View
Stack: Python + PySide6 + SQLite + python-docx + Ollama (local LLM)
"""
import sys
import json
from pathlib import Path

import PySide6.QtSvg  # noqa: F401 — ensures SVG rendering plugin is loaded
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings

from app.theme import ThemeManager
from app.citation_engine import CitationStyleEngine
from app.model import EntryModel
from app.adapter import EntryAdapter
from app.i18n import LanguageManager
from app.views.main_window import MainWindowView
from app.dialogs.startup_dialog import StartupDialog


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("CiteMind")
    app.setOrganizationName("CiteMind")
    app.setStyle("Fusion")

    theme_mgr = ThemeManager(app)
    theme_mgr.apply()

    lang_mgr = LanguageManager()

    settings = QSettings("CiteMind", "CiteMind")
    try:
        CitationStyleEngine.load_custom_styles(
            json.loads(settings.value("custom_styles", "{}"))
        )
    except Exception:
        CitationStyleEngine.load_custom_styles({})

    # ── Startup dialog: user picks or creates a project ───────────────────
    startup = StartupDialog(lang_mgr)
    if startup.exec() != StartupDialog.Accepted:
        sys.exit(0)

    db_path = startup.selected_path()
    if db_path is None:
        sys.exit(0)

    # Persist chosen path so next launch shows it in recents
    settings.setValue("last_db_path", str(db_path))

    model   = EntryModel(db_path)
    adapter = EntryAdapter(model)
    window  = MainWindowView(adapter, theme_mgr, lang_mgr)

    # Start maximized by default, unless user chose otherwise
    if settings.value("start_maximized", "true") == "true":
        window.showMaximized()
    else:
        window.show()

    code = app.exec()
    model.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
