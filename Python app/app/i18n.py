"""
i18n.py — LanguageManager for handling translations.
"""
import json
from pathlib import Path
from PySide6.QtCore import QObject, Signal, QSettings

class LanguageManager(QObject):
    """Manages loading and retrieving translation strings."""
    
    languageChanged = Signal(str)

    def __init__(self):
        super().__init__()
        self._settings = QSettings("CiteMind", "CiteMind")
        self._current_lang = self._settings.value("language", "en")
        self._translations = {}
        self._load_translations()

    def _load_translations(self):
        import sys
        if getattr(sys, 'frozen', False):
            base_dir = Path(sys._MEIPASS) / "app"
        else:
            base_dir = Path(__file__).parent
            
        lang_file = base_dir / "languages" / f"{self._current_lang}.json"
        if lang_file.exists():
            try:
                with open(lang_file, "r", encoding="utf-8") as f:
                    self._translations = json.load(f)
            except Exception:
                self._translations = {}
        else:
            self._translations = {}

    def tr(self, key: str, default: str = "") -> str:
        """Translate a key, returning default (or key) if not found."""
        return self._translations.get(key, default or key)

    @property
    def current_lang(self) -> str:
        return self._current_lang

    def set_language(self, lang: str):
        """Update current language and persist setting."""
        if lang != self._current_lang:
            self._current_lang = lang
            self._settings.setValue("language", lang)
            self._load_translations()
            self.languageChanged.emit(lang)
