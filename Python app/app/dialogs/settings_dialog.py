"""
settings_dialog.py — Unified Preferences dialog.
Tabs: General, Appearance, AI.
"""
import requests
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFormLayout, QWidget, QComboBox, QMessageBox,
    QTabWidget, QCheckBox, QGroupBox, QFontComboBox,
)
from PySide6.QtCore import Qt, QSettings, QTimer
from PySide6.QtGui import QFont

from app.theme import icon, ThemeManager
from app.i18n import LanguageManager


# Recommended models for multilingual academic summarization
_SUGGESTED_MODELS = [
    "gemma2",
    "llama3.2",
    "mistral",
    "qwen2.5",
    "phi3",
]


class SettingsDialog(QDialog):
    """Unified Preferences dialog with General, Appearance, and AI tabs."""

    # AI Settings keys (kept for backward compatibility)
    SETTINGS_PROVIDER = "ai_provider"
    SETTINGS_URL = "ollama_url"
    SETTINGS_MODEL = "ollama_model"
    SETTINGS_SEMANTIC_MODEL = "ollama_semantic_model"
    SETTINGS_API_KEY = "ollama_api_key"

    _DEFAULT_PROVIDER = "Ollama"
    _DEFAULT_URL = "http://localhost:11434"
    _DEFAULT_MODEL = "llama3.2"

    def __init__(self, lang_mgr: LanguageManager, theme_mgr: ThemeManager, parent=None):
        super().__init__(parent)
        self._lang = lang_mgr
        self._theme = theme_mgr
        self.setWindowTitle(self._lang.tr("pref_title"))
        self.setWindowIcon(icon("settings"))
        self.setMinimumWidth(580)
        self.setMinimumHeight(520)
        self.setModal(True)
        self._original_theme = self._theme.current
        self._original_font = self._theme.font_family
        self._build_ui()
        self._load()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header
        title = QLabel(f"⚙  {self._lang.tr('pref_header')}")
        title.setObjectName("sectionTitle")
        title.setProperty("class", "dialogHeaderTitle")
        root.addWidget(title)

        # Tab widget
        self._tabs = QTabWidget()
        root.addWidget(self._tabs, 1)

        self._build_general_tab()
        self._build_appearance_tab()
        self._build_ai_tab()

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_cancel = QPushButton(self._lang.tr("pref_btn_cancel"))
        btn_cancel.clicked.connect(self._revert_and_reject)

        self._btn_save = QPushButton(icon("file-download"), f"  {self._lang.tr('pref_btn_save')}")
        self._btn_save.setObjectName("btnPrimary")
        self._btn_save.setDefault(True)
        self._btn_save.clicked.connect(self._save_all)

        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(self._btn_save)
        root.addLayout(btn_row)

    # ── General Tab ───────────────────────────────────────────────────────
    def _build_general_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        # Language group
        lang_group = QGroupBox(self._lang.tr("pref_group_language"))
        lang_layout = QFormLayout(lang_group)
        lang_layout.setSpacing(8)

        self._lang_combo = QComboBox()
        self._lang_combo.addItem("English", "en")
        self._lang_combo.addItem("Italiano", "it")
        lang_layout.addRow(self._lang.tr("pref_language"), self._lang_combo)

        lang_note = QLabel(self._lang.tr("pref_language_note"))
        lang_note.setWordWrap(True)
        lang_note.setProperty("class", "dialogMutedText")
        lang_layout.addRow("", lang_note)

        layout.addWidget(lang_group)

        # Window group
        win_group = QGroupBox(self._lang.tr("pref_group_window"))
        win_layout = QVBoxLayout(win_group)
        win_layout.setSpacing(8)

        self._start_maximized_chk = QCheckBox(self._lang.tr("pref_start_maximized"))
        win_layout.addWidget(self._start_maximized_chk)

        layout.addWidget(win_group)
        layout.addStretch()

        self._tabs.addTab(page, self._lang.tr("pref_tab_general"))

    # ── Appearance Tab ────────────────────────────────────────────────────
    def _build_appearance_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        # Theme group
        theme_group = QGroupBox(self._lang.tr("pref_group_theme"))
        theme_layout = QFormLayout(theme_group)
        theme_layout.setSpacing(8)

        self._theme_combo = QComboBox()
        for key in ThemeManager.THEME_ORDER:
            self._theme_combo.addItem(self._theme.theme_display_name(key), key)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_preview)
        theme_layout.addRow(self._lang.tr("pref_theme"), self._theme_combo)

        layout.addWidget(theme_group)

        # Font group
        font_group = QGroupBox(self._lang.tr("pref_group_font"))
        font_layout = QFormLayout(font_group)
        font_layout.setSpacing(8)

        self._font_combo = QFontComboBox()
        self._font_combo.setCurrentFont(QFont(self._theme.font_family.split(",")[0].strip().strip("'")))
        font_layout.addRow(self._lang.tr("pref_font_family"), self._font_combo)

        layout.addWidget(font_group)
        layout.addStretch()

        self._tabs.addTab(page, self._lang.tr("pref_tab_appearance"))

    # ── AI Tab ────────────────────────────────────────────────────────────
    def _build_ai_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        # Info box
        info = QLabel(self._lang.tr("ai_settings_info"))
        info.setWordWrap(True)
        info.setOpenExternalLinks(True)
        info.setProperty("class", "dialogMutedTextLarge")
        layout.addWidget(info)

        btn_dl = QPushButton(icon("world-www"), f" {self._lang.tr('pref_download_ollama')}")
        btn_dl.setToolTip(self._lang.tr("pref_download_ollama_tip"))
        btn_dl.setObjectName("btnPrimary")
        btn_dl.clicked.connect(self._open_ollama_download)

        dl_layout = QHBoxLayout()
        dl_layout.addWidget(btn_dl)
        dl_layout.addStretch()
        layout.addLayout(dl_layout)

        # Form
        form_w = QWidget()
        form = QFormLayout(form_w)
        form.setSpacing(10)
        form.setContentsMargins(0, 10, 0, 0)

        # Provider
        self._provider_combo = QComboBox()
        self._provider_combo.addItems(["Ollama", "OpenAI", "Anthropic", "Gemini"])
        self._provider_combo.currentTextChanged.connect(self._on_provider_changed)
        form.addRow(self._lang.tr("ai_settings_provider") if hasattr(self._lang, "tr") else "AI Provider", self._provider_combo)

        # URL
        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("http://localhost:11434 (o URL personalizzato)")
        form.addRow(self._lang.tr("ai_settings_server_url"), self._url_edit)

        # Model selector (editable combo)
        model_container = QWidget()
        model_row = QHBoxLayout(model_container)
        model_row.setContentsMargins(0, 0, 0, 0)
        model_row.setSpacing(4)

        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        self._model_combo.addItems(_SUGGESTED_MODELS)
        self._model_combo.setToolTip(self._lang.tr("pref_model_tip"))
        model_row.addWidget(self._model_combo, 1)

        btn_refresh = QPushButton(f"🔄 {self._lang.tr('ai_settings_btn_refresh')}")
        btn_refresh.setToolTip(self._lang.tr("pref_btn_refresh_tip"))
        btn_refresh.setFixedWidth(82)
        btn_refresh.clicked.connect(self._fetch_models)
        model_row.addWidget(btn_refresh)

        btn_browse_model = QPushButton("📁")
        btn_browse_model.setToolTip(self._lang.tr("ai_settings_btn_browse_tip"))
        btn_browse_model.setFixedSize(24, 24)
        btn_browse_model.clicked.connect(lambda: self._browse_model(self._model_combo))
        model_row.addWidget(btn_browse_model)

        form.addRow(self._lang.tr("ai_settings_model"), model_container)

        # Semantic Model selector
        semantic_container = QWidget()
        semantic_row = QHBoxLayout(semantic_container)
        semantic_row.setContentsMargins(0, 0, 0, 0)
        semantic_row.setSpacing(4)

        self._semantic_model_combo = QComboBox()
        self._semantic_model_combo.setEditable(True)
        self._semantic_model_combo.addItems(_SUGGESTED_MODELS)
        self._semantic_model_combo.setToolTip(self._lang.tr("ai_settings_semantic_info"))
        semantic_row.addWidget(self._semantic_model_combo, 1)

        btn_browse_sem = QPushButton("📁")
        btn_browse_sem.setToolTip(self._lang.tr("ai_settings_btn_browse_tip"))
        btn_browse_sem.setFixedSize(24, 24)
        btn_browse_sem.clicked.connect(lambda: self._browse_model(self._semantic_model_combo))
        semantic_row.addWidget(btn_browse_sem)

        form.addRow(self._lang.tr("ai_settings_semantic_model"), semantic_container)

        # API Key field
        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self._api_key_input.setToolTip(self._lang.tr("ai_settings_api_key_tip"))
        form.addRow(self._lang.tr("ai_settings_api_key"), self._api_key_input)

        layout.addWidget(form_w)

        # Status label
        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setProperty("class", "dialogMutedTextLarge")
        layout.addWidget(self._status_lbl)

        # Test button
        btn_test_row = QHBoxLayout()
        btn_test = QPushButton(f"🔌  {self._lang.tr('ai_settings_btn_test')}")
        btn_test.clicked.connect(self._test_connection)
        btn_test_row.addWidget(btn_test)
        btn_test_row.addStretch()
        layout.addLayout(btn_test_row)

        layout.addStretch()

        self._tabs.addTab(page, self._lang.tr("pref_tab_ai"))
        self._on_provider_changed(self._provider_combo.currentText())

    def _on_provider_changed(self, provider: str):
        """Update placeholder and UI state based on selected provider."""
        provider = provider.lower()
        if provider == "openai":
            self._url_edit.setPlaceholderText("https://api.openai.com/v1/chat/completions (Opzionale)")
        elif provider == "anthropic":
            self._url_edit.setPlaceholderText("https://api.anthropic.com/v1/messages (Opzionale)")
        elif provider == "gemini":
            self._url_edit.setPlaceholderText("https://generativelanguage.googleapis.com/... (Opzionale)")
        else:
            self._url_edit.setPlaceholderText("http://localhost:11434")

    # ── load / save ──────────────────────────────────────────────────────
    def _load(self):
        s = QSettings("CiteMind", "CiteMind")

        # General
        lang = s.value("language", "en")
        idx = self._lang_combo.findData(lang)
        if idx >= 0:
            self._lang_combo.setCurrentIndex(idx)
        self._start_maximized_chk.setChecked(
            s.value("start_maximized", "true") == "true"
        )

        # Appearance
        theme = self._theme.current
        idx = self._theme_combo.findData(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)

        # AI
        provider = s.value(self.SETTINGS_PROVIDER, self._DEFAULT_PROVIDER)
        self._provider_combo.setCurrentText(provider)
        self._url_edit.setText(s.value(self.SETTINGS_URL, self._DEFAULT_URL))
        model = s.value(self.SETTINGS_MODEL, self._DEFAULT_MODEL)
        idx = self._model_combo.findText(model)
        if idx >= 0:
            self._model_combo.setCurrentIndex(idx)
        else:
            self._model_combo.setCurrentText(model)

        semantic_model = s.value(self.SETTINGS_SEMANTIC_MODEL, "")
        idx = self._semantic_model_combo.findText(semantic_model)
        if idx >= 0:
            self._semantic_model_combo.setCurrentIndex(idx)
        else:
            self._semantic_model_combo.setCurrentText(semantic_model)

        api_key = s.value(self.SETTINGS_API_KEY, "")
        self._api_key_input.setText(api_key)

        # Auto-fetch installed models
        QTimer.singleShot(100, self._fetch_models)

    def _save_all(self):
        s = QSettings("CiteMind", "CiteMind")

        # ── General ──────────────────────────────────────────────────────
        new_lang = self._lang_combo.currentData()
        old_lang = self._lang.current_lang
        s.setValue("start_maximized", "true" if self._start_maximized_chk.isChecked() else "false")

        # ── Appearance ───────────────────────────────────────────────────
        new_theme = self._theme_combo.currentData()
        new_font = self._font_combo.currentFont().family()
        # Save font as CSS-ready string
        font_css = f"'{new_font}', sans-serif"
        self._theme.font_family = font_css
        if new_theme != self._theme.current:
            self._theme.set_theme(new_theme)
        else:
            # Just re-apply in case font changed
            self._theme.apply()
            self._theme.themeChanged.emit(self._theme.current)

        # ── AI ───────────────────────────────────────────────────────────
        s.setValue(self.SETTINGS_PROVIDER, self._provider_combo.currentText())
        url = self._url_edit.text().strip()
        s.setValue(self.SETTINGS_URL, url)
        s.setValue(self.SETTINGS_MODEL, self._model_combo.currentText().strip() or self._DEFAULT_MODEL)
        s.setValue(self.SETTINGS_SEMANTIC_MODEL, self._semantic_model_combo.currentText().strip())
        s.setValue(self.SETTINGS_API_KEY, self._api_key_input.text().strip())

        # ── Language (last, because it triggers restart prompt) ───────────
        if new_lang != old_lang:
            self._lang.set_language(new_lang)
            self.accept()
            QMessageBox.information(
                self.parent(),
                self._lang.tr("msg_lang_changed_title"),
                self._lang.tr("msg_lang_changed_text"),
            )
            return

        self.accept()

    def _revert_and_reject(self):
        """Revert preview changes if the user cancels."""
        if self._theme.current != self._original_theme or self._theme.font_family != self._original_font:
            self._theme.font_family = self._original_font
            self._theme.set_theme(self._original_theme)
        self.reject()

    # ── theme preview ────────────────────────────────────────────────────
    def _on_theme_preview(self, idx: int):
        """Live-preview the selected theme."""
        theme_key = self._theme_combo.currentData()
        if theme_key and theme_key != self._theme.current:
            self._theme.set_theme(theme_key)

    # ── AI logic ─────────────────────────────────────────────────────────
    def _open_ollama_download(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("https://ollama.com/download"))

    def _browse_model(self, combo_box: QComboBox):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._lang.tr("ai_settings_btn_browse_tip"),
            "",
            "Model Files (*.gguf *.bin);;All Files (*)",
        )
        if path:
            combo_box.setCurrentText(path)

    def _test_connection(self):
        url = self._url_edit.text().strip() or self._DEFAULT_URL
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url
        try:
            r = requests.get(f"{url}/api/tags", timeout=5, proxies={"http": None, "https": None})
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            if models:
                self._status_lbl.setProperty("class", "")
                self._status_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
                self._status_lbl.setText(
                    f"{self._lang.tr('ai_settings_status_connected')}{', '.join(models)}"
                )
            else:
                self._status_lbl.setProperty("class", "dialogWarningText")
                self._status_lbl.setText(self._lang.tr("ai_settings_status_no_models"))
        except requests.ConnectionError:
            self._status_lbl.setProperty("class", "")
            self._status_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
            self._status_lbl.setText(self._lang.tr("ai_settings_status_unreachable"))
        except Exception as exc:
            self._status_lbl.setProperty("class", "")
            self._status_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
            self._status_lbl.setText(f"{self._lang.tr('ai_settings_status_error')}{exc}")

    def _fetch_models(self):
        """Fetch installed models from Ollama and update the combo box."""
        url = self._url_edit.text().strip() or self._DEFAULT_URL
        if not url.startswith("http://") and not url.startswith("https://"):
            url = "http://" + url
        try:
            r = requests.get(f"{url}/api/tags", timeout=5, proxies={"http": None, "https": None})
            r.raise_for_status()
            models = [m["name"] for m in r.json().get("models", [])]
            if models:
                current = self._model_combo.currentText()
                self._model_combo.clear()
                self._model_combo.addItems(models)
                idx = self._model_combo.findText(current)
                if idx >= 0:
                    self._model_combo.setCurrentIndex(idx)

                current_semantic = self._semantic_model_combo.currentText()
                self._semantic_model_combo.clear()
                self._semantic_model_combo.addItems([""] + models)
                idx_sem = self._semantic_model_combo.findText(current_semantic)
                if idx_sem >= 0:
                    self._semantic_model_combo.setCurrentIndex(idx_sem)

                self._status_lbl.setProperty("class", "")
                self._status_lbl.setStyleSheet("color: #22c55e; font-size: 12px;")
                self._status_lbl.setText(
                    self._lang.tr("ai_settings_status_found_models").format(count=len(models))
                )
            else:
                self._status_lbl.setProperty("class", "dialogWarningText")
                self._status_lbl.setText(self._lang.tr("ai_settings_status_none"))
        except Exception:
            self._status_lbl.setProperty("class", "")
            self._status_lbl.setStyleSheet("color: #ef4444; font-size: 12px;")
            self._status_lbl.setText(self._lang.tr("ai_settings_status_contact_fail"))

    # ── static helpers (backward compatible with AiSettingsDialog) ────────
    @staticmethod
    def get_ai_provider() -> str:
        """Return the stored AI provider."""
        return QSettings("CiteMind", "CiteMind").value(
            SettingsDialog.SETTINGS_PROVIDER, SettingsDialog._DEFAULT_PROVIDER
        )

    @staticmethod
    def get_ollama_url() -> str:
        """Return the stored Ollama URL."""
        return QSettings("CiteMind", "CiteMind").value(
            SettingsDialog.SETTINGS_URL, SettingsDialog._DEFAULT_URL
        )

    @staticmethod
    def get_model_name() -> str:
        """Return the stored Ollama model name."""
        return QSettings("CiteMind", "CiteMind").value(
            SettingsDialog.SETTINGS_MODEL, SettingsDialog._DEFAULT_MODEL
        )

    @staticmethod
    def get_semantic_model_name() -> str:
        """Return the stored semantic model name, or fallback to the main model."""
        s = QSettings("CiteMind", "CiteMind")
        semantic_model = s.value(SettingsDialog.SETTINGS_SEMANTIC_MODEL, "").strip()
        if semantic_model:
            return semantic_model
        return s.value(SettingsDialog.SETTINGS_MODEL, SettingsDialog._DEFAULT_MODEL)

    @staticmethod
    def get_api_key() -> str:
        """Return the stored API Key, or empty string."""
        return QSettings("CiteMind", "CiteMind").value(
            SettingsDialog.SETTINGS_API_KEY, ""
        ).strip()
