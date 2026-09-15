"""
entry_form.py — EntryFormWidget: right-panel form for editing a single entry.
"""
import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QTabWidget, QLabel, QLineEdit, QTextEdit, QComboBox, QCompleter,
    QPushButton, QTextBrowser, QProgressBar, QSizePolicy, QCheckBox,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, Signal, QStringListModel, QTimer, QSize
from PySide6.QtGui import QColor, QPalette

from app.theme import icon
from app.i18n import LanguageManager


_LANG_KEYS = {
    "English 🇬🇧": "en",
    "Italiano 🇮🇹": "it",
    "Français 🇫🇷": "fr",
    "Deutsch 🇩🇪": "de",
}


class EntryFormWidget(QWidget):
    """Right-panel form for editing a single entry."""

    fieldChanged     = Signal(str, str)
    journalCompleted = Signal(str)
    # Emitted when the user clicks "Genera AI Notes" — carries current entry_id
    aiNotesRequested = Signal(int)
    semanticKeywordsRequested = Signal(int)
    topicsEdited = Signal(int, list)
    resetAiTopicsRequested = Signal(int)
    resetAllAiTopicsRequested = Signal()
    bibliographyRequested = Signal(int)
    ocrRequested = Signal(int)
    referenceGraphRequested = Signal(int)
    extractionExportRequested = Signal(int)
    rAnalysisRequested = Signal(int)
    manualBibliographyEdited = Signal(int, list)

    def __init__(self, lang_mgr: LanguageManager, parent=None):
        super().__init__(parent)
        self._lang       = lang_mgr
        self._building   = False
        self._fields: dict[str, QWidget] = {}
        self._labels: dict[str, QLabel]  = {}
        self._current_id: int | None     = None
        self._ai_data:    dict           = {}   # parsed JSON from DB or API
        self._field_timers: dict[str, QTimer] = {}
        self._suppress_reference_sync = False
        self._build_ui()

    # ── build ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        # Type header row
        top = QHBoxLayout()
        self._type_label = QLabel("BIBLIOGRAPHY")
        self._type_label.setObjectName("sectionTitle")
        self._type_combo = QComboBox()
        self._type_combo.addItems(["bibliography", "sitography", "tesi"])
        self._type_combo.setFixedWidth(130)
        self._pub_type_label = QLabel(self._lang.tr("entry_form_subtype"))
        self._pub_type_combo = QComboBox()
        self._pub_type_combo.setFixedWidth(140)
        top.addWidget(self._type_label)
        top.addStretch()
        top.addWidget(QLabel("Type:"))
        top.addWidget(self._type_combo)
        top.addWidget(self._pub_type_label)
        top.addWidget(self._pub_type_combo)
        root.addLayout(top)

        self._tabs = QTabWidget()
        root.addWidget(self._tabs)

        # Tab 1: Core
        core_w = QWidget()
        form   = QFormLayout(core_w)
        form.setSpacing(8)
        form.setContentsMargins(8, 10, 8, 8)
        self._add_field(form, "authors",   self._lang.tr("entry_form_authors"), self._lang.tr("entry_form_placeholder_authors"))
        
        self._is_editor_chk = QCheckBox(self._lang.tr("entry_form_is_editor"))
        self._is_editor_chk.stateChanged.connect(
            lambda state: self._emit("is_editor", 1 if state == Qt.Checked else 0)
        )
        form.addRow("", self._is_editor_chk)
        
        self._add_field(form, "title",     self._lang.tr("entry_form_title"),      self._lang.tr("entry_form_placeholder_title"))
        self._title_warning_lbl = QLabel(
            self._lang.tr("entry_form_duplicate_title")
        )
        self._title_warning_lbl.setStyleSheet(
            "color: #ef4444; font-weight: bold; font-size: 11px;"
        )
        self._title_warning_lbl.setVisible(False)
        form.addRow("", self._title_warning_lbl)
        self._add_field(form, "year",      self._lang.tr("entry_form_year"),       self._lang.tr("entry_form_placeholder_year"))
        self._add_field(form, "publisher", self._lang.tr("entry_form_publisher"),  self._lang.tr("entry_form_placeholder_publisher"))
        self._add_field(form, "location",  self._lang.tr("entry_form_location"),   "")
        self._add_field(form, "edition",   self._lang.tr("entry_form_edition"),    "e.g. 3rd ed.")
        self._add_field(form, "pages",     self._lang.tr("entry_form_pages"),      "e.g. 45–67")
        self._tabs.addTab(core_w, icon("book"), f" {self._lang.tr('entry_form_tab_data')}")

        # Tab 2: Journal
        jrnl_w = QWidget()
        form2  = QFormLayout(jrnl_w)
        form2.setSpacing(8)
        form2.setContentsMargins(8, 10, 8, 8)
        self._add_field(form2, "journal", self._lang.tr("entry_form_journal"), self._lang.tr("entry_form_placeholder_journal"))
        self._add_field(form2, "volume",  self._lang.tr("entry_form_volume"),  "e.g. 12")
        self._add_field(form2, "issue",   self._lang.tr("entry_form_issue"),   "e.g. 3")
        self._add_field(form2, "doi",     self._lang.tr("entry_form_doi"),     "e.g. 10.xxxx/yyyy")
        self._tabs.addTab(jrnl_w, icon("news"), f" {self._lang.tr('filter_bib')}")

        # Tab 3: Web
        web_w = QWidget()
        form3 = QFormLayout(web_w)
        form3.setSpacing(8)
        form3.setContentsMargins(8, 10, 8, 8)
        self._add_field(form3, "url",         "URL:",         "https://…")
        self._add_field(form3, "access_date", self._lang.tr("entry_form_access_date"), "DD/MM/YYYY")
        self._tabs.addTab(web_w, icon("world-www"), f" {self._lang.tr('filter_sit')}")

        # Tab 4: Notes
        note_w = QWidget()
        vl     = QVBoxLayout(note_w)
        vl.setContentsMargins(8, 10, 8, 8)
        self._notes = QTextEdit()
        self._notes.setPlaceholderText(self._lang.tr("entry_form_placeholder_notes"))
        vl.addWidget(self._notes)
        self._fields["notes"] = self._notes
        timer_notes = QTimer(self)
        timer_notes.setSingleShot(True)
        timer_notes.setInterval(400)
        timer_notes.timeout.connect(lambda: self._emit("notes", self._notes.toPlainText()))
        self._field_timers["notes"] = timer_notes
        self._notes.textChanged.connect(timer_notes.start)
        self._tabs.addTab(note_w, icon("notes"), f" {self._lang.tr('entry_form_tab_notes')}")

        # Tab 5: Extracted references
        self._tabs.addTab(self._build_bibliography_tab(), icon("book"), " References")

        # Tab 6: AI Notes
        self._tabs.addTab(self._build_ai_tab(), icon("sparkles"), f" {self._lang.tr('entry_form_tab_ai')}")

        # Tab 7: AI Analysis (Semantic & Topics)
        self._tabs.addTab(self._build_analysis_tab(), icon("chart-pie"), f" {self._lang.tr('entry_form_tab_analysis')}")

        self._meta_label = QLabel("")
        self._meta_label.setObjectName("sectionTitle")
        self._meta_label.setAlignment(Qt.AlignRight)
        root.addWidget(self._meta_label)

        self._type_combo.currentTextChanged.connect(self._on_type_changed)
        self._pub_type_combo.currentTextChanged.connect(
            lambda v: self._emit("pub_type", v.lower())
        )

    def _build_bibliography_tab(self) -> QWidget:
        """Display extracted references list + button to open external DAG dialog."""
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(12, 12, 12, 12)
        vl.setSpacing(8)

        # ── Sezione Automatica ─────────────────────────────────────────────
        top_row = QHBoxLayout()
        self._btn_refresh_bibliography = QPushButton("✨ Avvia parsing PDF")
        self._btn_refresh_bibliography.setEnabled(False)
        self._btn_refresh_bibliography.setToolTip("Estrae automaticamente i riferimenti dal PDF allegato.")
        self._btn_refresh_bibliography.clicked.connect(self._on_refresh_bibliography_clicked)
        top_row.addWidget(self._btn_refresh_bibliography)

        self._btn_ocr_pdf = QPushButton(icon("scan"), "")
        self._btn_ocr_pdf.setObjectName("ocrPdfButton")
        self._btn_ocr_pdf.setIconSize(QSize(22, 22))
        self._btn_ocr_pdf.setToolTip("Crea una copia PDF ricercabile con OCR (italiano, inglese, francese e tedesco)")
        self._btn_ocr_pdf.setAccessibleName("OCR PDF")
        self._btn_ocr_pdf.setFixedSize(34, 34)
        self._btn_ocr_pdf.clicked.connect(self._on_ocr_pdf_clicked)
        self._btn_ocr_pdf.setEnabled(False)
        top_row.addWidget(self._btn_ocr_pdf)

        self._reference_progress = QProgressBar()
        self._reference_progress.setRange(0, 0)
        self._reference_progress.setVisible(False)
        self._reference_progress.setFixedHeight(4)
        top_row.addWidget(self._reference_progress)
        
        self._reference_status = QLabel("")
        self._reference_status.setStyleSheet("color: #8888a8; font-size: 11px;")
        top_row.addWidget(self._reference_status)
        top_row.addStretch()
        vl.addLayout(top_row)

        # ── Sezione Manuale ──────────────────────────────────────────────
        manual_row = QHBoxLayout()
        self._manual_ref_combo = QComboBox()
        self._manual_ref_combo.setEditable(True)
        self._manual_ref_combo.setInsertPolicy(QComboBox.NoInsert)
        self._manual_ref_combo.setPlaceholderText("Cerca nel database per aggiungere un riferimento...")
        self._manual_ref_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        self._ref_completer = QCompleter(self)
        self._ref_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._ref_completer.setFilterMode(Qt.MatchContains)
        self._manual_ref_combo.setCompleter(self._ref_completer)
        
        manual_row.addWidget(self._manual_ref_combo, 1)
        
        self._btn_add_manual_ref = QPushButton("Aggiungi")
        self._btn_add_manual_ref.clicked.connect(self._on_add_manual_ref)
        manual_row.addWidget(self._btn_add_manual_ref)
        
        self._btn_remove_manual_ref = QPushButton("Rimuovi")
        self._btn_remove_manual_ref.clicked.connect(self._on_remove_manual_ref)
        manual_row.addWidget(self._btn_remove_manual_ref)
        
        vl.addLayout(manual_row)

        # ── Lista Referenze Trovate ────────────────────────────────────────
        ref_header = QHBoxLayout()
        ref_label = QLabel("Referenze collegate:")
        ref_label.setStyleSheet("font-weight: 600; font-size: 13px;")
        ref_header.addWidget(ref_label)
        ref_header.addStretch()

        self._btn_open_graph = QPushButton("📊 Apri Grafico Cronologico")
        self._btn_open_graph.setEnabled(False)
        self._btn_open_graph.setToolTip("Apre il DAG cronologico in una finestra esterna con scala temporale.")
        self._btn_open_graph.clicked.connect(self._on_open_graph_clicked)
        ref_header.addWidget(self._btn_open_graph)

        self._btn_export_dataset = QPushButton(icon("file-export"), "")
        self._btn_export_dataset.setFixedSize(34, 34)
        self._btn_export_dataset.setToolTip("Esporta gli elementi estratti dal PDF in CSV o JSON")
        self._btn_export_dataset.setAccessibleName("Esporta dataset PDF")
        self._btn_export_dataset.clicked.connect(self._on_export_dataset_clicked)
        self._btn_export_dataset.setEnabled(False)
        ref_header.addWidget(self._btn_export_dataset)

        self._btn_r_analysis = QPushButton(icon("chart-line"), "")
        self._btn_r_analysis.setFixedSize(34, 34)
        self._btn_r_analysis.setToolTip("Genera un grafico riepilogativo con R")
        self._btn_r_analysis.setAccessibleName("Analisi R")
        self._btn_r_analysis.clicked.connect(self._on_r_analysis_clicked)
        self._btn_r_analysis.setEnabled(False)
        ref_header.addWidget(self._btn_r_analysis)
        vl.addLayout(ref_header)

        self._ref_list_widget = QListWidget()
        self._ref_list_widget.setAlternatingRowColors(True)
        self._ref_list_widget.setStyleSheet("""
            QListWidget {
                font-size: 12px;
                selection-background-color: #d8c7f2;
                selection-color: #241338;
            }
            QListWidget::item { padding: 4px 8px; }
            QListWidget::item:selected,
            QListWidget::item:selected:active,
            QListWidget::item:selected:!active {
                background: #d8c7f2;
                color: #241338;
            }
        """)
        ref_palette = self._ref_list_widget.palette()
        ref_palette.setColor(QPalette.Highlight, QColor("#d8c7f2"))
        ref_palette.setColor(QPalette.HighlightedText, QColor("#241338"))
        self._ref_list_widget.setPalette(ref_palette)
        vl.addWidget(self._ref_list_widget, 1)
        
        return w

    def _on_open_graph_clicked(self):
        """Emette segnale per aprire il dialog esterno del grafo."""
        if self._current_id is not None:
            self.referenceGraphRequested.emit(self._current_id)

    def _on_export_dataset_clicked(self):
        if self._current_id is not None:
            self.extractionExportRequested.emit(self._current_id)

    def _on_r_analysis_clicked(self):
        if self._current_id is not None:
            self.rAnalysisRequested.emit(self._current_id)

    def _on_refresh_bibliography_clicked(self):
        if self._current_id is not None:
            self.bibliographyRequested.emit(self._current_id)

    def _on_ocr_pdf_clicked(self):
        if self._current_id is not None:
            self.ocrRequested.emit(self._current_id)

    def _on_add_manual_ref(self):
        if self._current_id is not None:
            text = self._manual_ref_combo.currentText()
            # Emette segnale con il testo/ID (qui inviamo il testo al MainWindow)
            self.manualBibliographyEdited.emit(self._current_id, [{"action": "add", "text": text}])
            self._manual_ref_combo.clearEditText()

    def _on_remove_manual_ref(self):
        if self._current_id is not None:
            text = self._manual_ref_combo.currentText()
            self.manualBibliographyEdited.emit(self._current_id, [{"action": "remove", "text": text}])
            self._manual_ref_combo.clearEditText()

    def _build_analysis_tab(self) -> QWidget:
        w = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(16, 16, 16, 16)
        vl.setSpacing(16)

        # ── Tags ─────────────────────────────────────────────────────────
        lbl_topics = QLabel(f"🏷️  {self._lang.tr('analysis_ai_topics_title')}")
        lbl_topics.setStyleSheet("font-weight: 700; font-size: 14px;")
        vl.addWidget(lbl_topics)

        reset_row = QHBoxLayout()
        reset_row.setSpacing(6)
        self._btn_generate_topics = QPushButton(self._lang.tr("analysis_tags_edit"))
        self._btn_generate_topics.clicked.connect(self._emit_generate_semantic_keywords)
        self._btn_generate_topics.setEnabled(False)
        reset_row.addWidget(self._btn_generate_topics)

        self._btn_reset_entry_topics = QPushButton(self._lang.tr("analysis_tags_reset_entry"))
        self._btn_reset_entry_topics.clicked.connect(self._emit_reset_entry_topics)
        self._btn_reset_entry_topics.setEnabled(False)
        reset_row.addWidget(self._btn_reset_entry_topics)

        self._btn_reset_all_topics = QPushButton(self._lang.tr("analysis_tags_reset_all"))
        self._btn_reset_all_topics.clicked.connect(self._emit_reset_all_topics)
        reset_row.addWidget(self._btn_reset_all_topics)
        reset_row.addStretch()
        vl.addLayout(reset_row)

        self._topics_editor = QLineEdit()
        self._topics_editor.setPlaceholderText(self._lang.tr("analysis_tags_placeholder"))
        self._topics_editor.setEnabled(False)
        self._topics_editor.setClearButtonEnabled(True)
        self._topics_editor.editingFinished.connect(self._emit_topics_edited)
        self._topics_editor.returnPressed.connect(self._emit_topics_edited)
        self._topics_editor.textEdited.connect(self._update_topic_completion)
        self._topics_completer = QCompleter([])
        self._topic_completion_base = ""
        self._pending_topic_completion = ""
        self._topics_completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._topics_completer.setCompletionMode(QCompleter.PopupCompletion)
        self._topics_completer.setFilterMode(Qt.MatchContains)
        self._topics_completer.activated.connect(
            self._on_topic_completion_activated
        )
        self._topics_editor.setCompleter(self._topics_completer)
        vl.addWidget(self._topics_editor)

        self._topics_container = QWidget()
        self._topics_layout = QHBoxLayout(self._topics_container)
        self._topics_layout.setContentsMargins(0, 0, 0, 0)
        self._topics_layout.setSpacing(6)
        
        self._topics_empty_lbl = QLabel(self._lang.tr("analysis_ai_topics_empty"))
        self._topics_empty_lbl.setStyleSheet("color: #8888a8; font-size: 12px; font-style: italic;")
        
        vl.addWidget(self._topics_container)
        vl.addWidget(self._topics_empty_lbl)

        # ── Semantic Analysis ─────────────────────────────────────────────
        lbl_semantic = QLabel(f"📊  {self._lang.tr('analysis_semantic_title')}")
        lbl_semantic.setStyleSheet("font-weight: 700; font-size: 14px; margin-top: 10px;")
        vl.addWidget(lbl_semantic)

        self._semantic_container = QWidget()
        form = QFormLayout(self._semantic_container)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)

        self._cluster_lbl = QLabel("-")
        self._role_lbl = QLabel("-")
        
        self._centrality_bar = QProgressBar()
        self._centrality_bar.setFixedHeight(6)
        self._centrality_bar.setTextVisible(False)
        self._centrality_bar.setStyleSheet("QProgressBar { background: #e0e0e0; border-radius: 3px; } QProgressBar::chunk { background: #3b82f6; border-radius: 3px; }")
        
        self._pagerank_bar = QProgressBar()
        self._pagerank_bar.setFixedHeight(6)
        self._pagerank_bar.setTextVisible(False)
        self._pagerank_bar.setStyleSheet("QProgressBar { background: #e0e0e0; border-radius: 3px; } QProgressBar::chunk { background: #10b981; border-radius: 3px; }")

        self._betweenness_bar = QProgressBar()
        self._betweenness_bar.setFixedHeight(6)
        self._betweenness_bar.setTextVisible(False)
        self._betweenness_bar.setStyleSheet("QProgressBar { background: #e0e0e0; border-radius: 3px; } QProgressBar::chunk { background: #f59e0b; border-radius: 3px; }")

        form.addRow(f"{self._lang.tr('analysis_cluster')}:", self._cluster_lbl)
        form.addRow(f"{self._lang.tr('analysis_role')}:", self._role_lbl)
        form.addRow(f"{self._lang.tr('analysis_centrality')}:", self._centrality_bar)
        form.addRow(f"{self._lang.tr('analysis_pagerank')}:", self._pagerank_bar)
        form.addRow(f"{self._lang.tr('analysis_betweenness')}:", self._betweenness_bar)

        self._semantic_empty_lbl = QLabel(self._lang.tr("analysis_semantic_empty"))
        self._semantic_empty_lbl.setStyleSheet("color: #8888a8; font-size: 12px; font-style: italic;")

        vl.addWidget(self._semantic_container)
        vl.addWidget(self._semantic_empty_lbl)
        
        vl.addStretch()
        return w

    def _build_ai_tab(self) -> QWidget:
        """Build the AI Notes tab widget."""
        w  = QWidget()
        vl = QVBoxLayout(w)
        vl.setContentsMargins(12, 12, 12, 12)
        vl.setSpacing(10)

        # ── Top bar: language selector + generate button ──────────────────
        top = QHBoxLayout()

        lang_lbl = QLabel("Lingua:")
        lang_lbl.setStyleSheet("font-weight: 600;")
        self._ai_lang_combo = QComboBox()
        self._ai_lang_combo.addItems(list(_LANG_KEYS.keys()))
        self._ai_lang_combo.setFixedWidth(160)
        self._ai_lang_combo.currentIndexChanged.connect(self._refresh_ai_display)

        top.addWidget(lang_lbl)
        top.addWidget(self._ai_lang_combo)
        top.addStretch()

        import os
        from PySide6.QtGui import QPixmap, QImage
        from app.theme import get_global_theme
        
        # Calcola la root del progetto partendo da app/views/entry_form.py
        import sys
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        logo_path = os.path.join(base_dir, "icon", "ollama.png")
        
        if os.path.exists(logo_path):
            powered_lbl = QLabel("Powered by")
            powered_lbl.setStyleSheet("color: #8888a8; font-size: 11px; font-weight: bold;")
            top.addWidget(powered_lbl)
            
            img = QImage(logo_path)
            if get_global_theme() == "dark":
                img.invertPixels(QImage.InvertMode.InvertRgb)
                
            pix = QPixmap.fromImage(img).scaledToHeight(28, Qt.SmoothTransformation)
            
            self._logo_lbl = QLabel()
            self._logo_lbl.setPixmap(pix)
            self._logo_lbl.setToolTip("Modello AI locale tramite Ollama")
            top.addWidget(self._logo_lbl)
            top.addSpacing(15)

        self._btn_gen_ai = QPushButton("⚡  Genera / Aggiorna")
        self._btn_gen_ai.setObjectName("btnPrimary")
        self._btn_gen_ai.setFixedHeight(30)
        self._btn_gen_ai.setToolTip(
            "Legge il PDF collegato e genera riassunto + punti chiave in tutte le lingue.\n"
            "Il risultato viene salvato nel database."
        )
        self._btn_gen_ai.clicked.connect(self._on_generate_clicked)
        top.addWidget(self._btn_gen_ai)

        vl.addLayout(top)

        # ── Progress bar (hidden by default) ─────────────────────────────
        self._ai_progress = QProgressBar()
        self._ai_progress.setRange(0, 0)   # indeterminate
        self._ai_progress.setFixedHeight(4)
        self._ai_progress.setVisible(False)
        self._ai_progress.setStyleSheet(
            "QProgressBar { border: none; background: transparent; }"
            "QProgressBar::chunk { background: #7c3aed; border-radius: 2px; }"
        )
        vl.addWidget(self._ai_progress)

        # ── Status label ─────────────────────────────────────────────────
        self._ai_status = QLabel("")
        self._ai_status.setStyleSheet("color: #8888a8; font-size: 12px; font-style: italic;")
        self._ai_status.setWordWrap(True)
        vl.addWidget(self._ai_status)

        # ── Summary area ─────────────────────────────────────────────────
        summary_lbl = QLabel(f"📄  {self._lang.tr('ai_summary_title')}")
        summary_lbl.setStyleSheet("font-weight: 700; font-size: 13px;")
        vl.addWidget(summary_lbl)

        self._ai_summary = QTextBrowser()
        self._ai_summary.setOpenExternalLinks(False)
        self._ai_summary.setFixedHeight(110)
        self._ai_summary.setPlaceholderText(
            self._lang.tr("ai_notes_empty")
        )
        vl.addWidget(self._ai_summary)

        # ── Key points area ──────────────────────────────────────────────
        kp_lbl = QLabel(f"🔑  {self._lang.tr('ai_keypoints_title')}")
        kp_lbl.setStyleSheet("font-weight: 700; font-size: 13px;")
        vl.addWidget(kp_lbl)

        self._ai_keypoints = QTextBrowser()
        self._ai_keypoints.setOpenExternalLinks(False)
        self._ai_keypoints.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        vl.addWidget(self._ai_keypoints)

        # ── No-PDF notice (shown when no pdf_path) ───────────────────────
        self._ai_no_pdf_lbl = QLabel(
            self._lang.tr("ai_notes_no_pdf_notice")
        )
        self._ai_no_pdf_lbl.setAlignment(Qt.AlignCenter)
        self._ai_no_pdf_lbl.setStyleSheet(
            "color: #8888a8; font-size: 13px; padding: 30px;"
        )
        self._ai_no_pdf_lbl.setWordWrap(True)
        self._ai_no_pdf_lbl.setVisible(False)
        vl.addWidget(self._ai_no_pdf_lbl)

        return w

    def reload_icons(self):
        self._tabs.setTabIcon(0, icon("book"))
        self._tabs.setTabIcon(1, icon("news"))
        self._tabs.setTabIcon(2, icon("world-www"))
        self._tabs.setTabIcon(3, icon("notes"))
        self._tabs.setTabIcon(4, icon("book"))
        self._tabs.setTabIcon(5, icon("sparkles"))
        self._tabs.setTabIcon(6, icon("chart-pie"))
        
        # Aggiorna il logo Ollama se presente
        if hasattr(self, "_logo_lbl"):
            import os
            from PySide6.QtGui import QPixmap, QImage
            from PySide6.QtCore import Qt
            from app.theme import get_global_theme
            
            import sys
            if getattr(sys, 'frozen', False):
                base_dir = sys._MEIPASS
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            logo_path = os.path.join(base_dir, "icon", "ollama.png")
            if os.path.exists(logo_path):
                img = QImage(logo_path)
                if get_global_theme() == "dark":
                    img.invertPixels(QImage.InvertMode.InvertRgb)
                pix = QPixmap.fromImage(img).scaledToHeight(28, Qt.SmoothTransformation)
                self._logo_lbl.setPixmap(pix)

    def _add_field(self, form, key: str, label: str, placeholder: str = ""):
        le  = QLineEdit()
        le.setPlaceholderText(placeholder)
        lbl = QLabel(label)
        self._labels[key] = lbl
        form.addRow(lbl, le)
        self._fields[key] = le
        
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(400)
        self._field_timers[key] = timer
        
        def on_timeout():
            self._emit(key, le.text())
            
        timer.timeout.connect(on_timeout)
        
        def on_text_changed(text):
            import re
            if key == "year" and text:
                if not (text.isdigit() and len(text) == 4):
                    le.setProperty("invalid", True)
                    le.setStyleSheet("QLineEdit { border: 1px solid #ef4444; }")
                else:
                    le.setProperty("invalid", False)
                    le.setStyleSheet("")
            elif key == "doi" and text:
                if not re.match(r'^10\.\d{4,}/[^\s]+$', text):
                    le.setProperty("invalid", True)
                    le.setStyleSheet("QLineEdit { border: 1px solid #ef4444; }")
                else:
                    le.setProperty("invalid", False)
                    le.setStyleSheet("")
            else:
                if le.property("invalid"):
                    le.setProperty("invalid", False)
                    le.setStyleSheet("")
                    
            if not self._building:
                timer.start()

        le.textChanged.connect(on_text_changed)

        if key == "journal":
            self._journal_completer = QCompleter([])
            self._journal_completer.setCaseSensitivity(Qt.CaseInsensitive)
            le.setCompleter(self._journal_completer)
            self._journal_completer.activated.connect(self.journalCompleted.emit)
            le.editingFinished.connect(lambda: self.journalCompleted.emit(le.text()))

    # ── slots ──────────────────────────────────────────────────────────────
    def _on_type_changed(self, v: str):
        self._update_pub_combo(v)
        self._emit("entry_type", v)

    def _update_pub_combo(self, et: str, pt: str = ""):
        self._building = True
        self._pub_type_combo.clear()
        if et == "bibliography":
            self._pub_type_combo.addItems(["Article", "Book", "Chapter"])
            self._pub_type_label.setVisible(True)
            self._pub_type_combo.setVisible(True)
        elif et == "tesi":
            self._pub_type_combo.addItems(["Triennale", "Magistrale", "Dottorato", "Specializzazione"])
            self._pub_type_label.setVisible(True)
            self._pub_type_combo.setVisible(True)
        else:
            self._pub_type_combo.addItems(["Webpage"])
            self._pub_type_label.setVisible(False)
            self._pub_type_combo.setVisible(False)

        if pt:
            idx = self._pub_type_combo.findText(pt.capitalize())
            if idx >= 0:
                self._pub_type_combo.setCurrentIndex(idx)
        self._building = False

    def _emit(self, field: str, value: str):
        if not self._building:
            self.fieldChanged.emit(field, value)
            if field in ("entry_type", "pub_type"):
                self._update_labels()

    def _update_labels(self):
        et = self._type_combo.currentText()
        pt = self._pub_type_combo.currentText().lower()

        if et == "tesi":
            self._labels.get("publisher", QLabel()).setText(self._lang.tr("entry_form_university"))
            self._labels.get("journal",   QLabel()).setText(self._lang.tr("entry_form_program"))
        else:
            if pt == "book":
                self._labels.get("title",     QLabel()).setText(self._lang.tr("entry_form_book_title"))
                self._labels.get("journal",   QLabel()).setText(self._lang.tr("entry_form_series"))
                self._labels.get("publisher", QLabel()).setText(self._lang.tr("entry_form_publisher"))
            elif pt == "chapter":
                self._labels.get("title",     QLabel()).setText(self._lang.tr("entry_form_chapter_title"))
                self._labels.get("journal",   QLabel()).setText(self._lang.tr("entry_form_book_title"))
                self._labels.get("publisher", QLabel()).setText(self._lang.tr("entry_form_editors"))
            else:
                self._labels.get("title",     QLabel()).setText(self._lang.tr("entry_form_title"))
                self._labels.get("journal",   QLabel()).setText(self._lang.tr("entry_form_journal"))
                self._labels.get("publisher", QLabel()).setText(self._lang.tr("entry_form_publisher"))

    # ── AI Notes helpers ──────────────────────────────────────────────────
    def _on_generate_clicked(self):
        if self._current_id is not None:
            self.aiNotesRequested.emit(self._current_id)

    def _emit_generate_semantic_keywords(self):
        if self._current_id is not None:
            self.semanticKeywordsRequested.emit(self._current_id)

    def _emit_topics_edited(self):
        if self._current_id is None:
            return
        raw = self._topics_editor.text()
        keywords = []
        for item in raw.split(","):
            value = item.strip()
            if value:
                keywords.append(value)
        self.topicsEdited.emit(self._current_id, keywords)

    def _update_topic_completion(self, text: str):
        """Complete only the topic currently being typed after the last comma."""
        if not self._topics_editor.isEnabled():
            return
        current = text.rsplit(",", 1)[-1].strip()
        self._topic_completion_base = text.rsplit(",", 1)[0].strip()
        self._topics_completer.setCompletionPrefix(current)
        if current:
            QTimer.singleShot(0, lambda prefix=current: self._show_topic_completion(prefix))
        else:
            self._topics_completer.popup().hide()

    def _show_topic_completion(self, prefix: str):
        """Open completion for the text after the last comma."""
        current = self._topics_editor.text().rsplit(",", 1)[-1].strip()
        if current != prefix or not self._topics_editor.hasFocus():
            return
        self._topics_completer.setCompletionPrefix(prefix)
        self._topics_completer.complete(self._topics_editor.rect())

    def _on_topic_completion_activated(self, completion: str):
        """Keep earlier tags when replacing only the current completion segment."""
        self._pending_topic_completion = completion
        QTimer.singleShot(0, self._apply_topic_completion)

    def _apply_topic_completion(self):
        """Apply the selected completion after QLineEdit's default insertion."""
        completion = self._pending_topic_completion
        self._pending_topic_completion = ""
        base = self._topic_completion_base
        value = completion.strip()
        combined = f"{base}, {value}" if base and value else (base or value)
        self._topics_editor.setText(combined)
        self._topics_editor.setCursorPosition(len(combined))
        QTimer.singleShot(0, self._emit_topics_edited)

    def _emit_reset_entry_topics(self):
        if self._current_id is not None:
            self.resetAiTopicsRequested.emit(self._current_id)

    def _emit_reset_all_topics(self):
        self.resetAllAiTopicsRequested.emit()

    def _refresh_ai_display(self):
        """Update summary/key-points widgets from cached _ai_data for selected lang."""
        lang_label = self._ai_lang_combo.currentText()
        lang_code  = _LANG_KEYS.get(lang_label, "en")

        summary    = self._ai_data.get(f"summary_{lang_code}", "")
        key_points = self._ai_data.get(f"key_points_{lang_code}", [])

        self._ai_summary.setPlainText(summary)

        if isinstance(key_points, list):
            html = "<ul style='margin:0; padding-left:18px;'>"
            for pt in key_points:
                html += f"<li style='margin-bottom:5px;'>{pt}</li>"
            html += "</ul>"
        else:
            html = str(key_points)
        self._ai_keypoints.setHtml(html)

    def _set_ai_ui_visible(self, has_pdf: bool):
        self._ai_no_pdf_lbl.setVisible(not has_pdf)
        self._ai_lang_combo.setVisible(has_pdf)
        self._ai_summary.setVisible(has_pdf)
        self._ai_keypoints.setVisible(has_pdf)
        self._btn_gen_ai.setEnabled(has_pdf)

    # ── public API ─────────────────────────────────────────────────────────
    def load(self, data: dict):
        self._building = True
        self._current_id = data.get("id")
        self._btn_generate_topics.setEnabled(self._current_id is not None)
        self._btn_reset_entry_topics.setEnabled(self._current_id is not None)
        self._topics_editor.setEnabled(self._current_id is not None)
        has_pdf = bool(data.get("pdf_path", "").strip())
        self._btn_refresh_bibliography.setEnabled(self._current_id is not None and has_pdf)
        self._btn_ocr_pdf.setEnabled(self._current_id is not None and has_pdf)
        self._btn_export_dataset.setEnabled(self._current_id is not None and has_pdf)
        self._btn_r_analysis.setEnabled(self._current_id is not None and has_pdf)
        for key, widget in self._fields.items():
            val = data.get(key, "")
            if isinstance(widget, QTextEdit):
                widget.setPlainText(str(val))
            else:
                widget.setText(str(val))
                
        is_editor = data.get("is_editor", 0)
        self._is_editor_chk.setChecked(bool(is_editor))
        et  = data.get("entry_type", "bibliography")
        idx = self._type_combo.findText(et)
        if idx >= 0:
            self._type_combo.setCurrentIndex(idx)
        self._type_label.setText(et.upper())
        pt = data.get("pub_type", "")
        self._update_pub_combo(et, pt)
        self._update_labels()
        ca = data.get("created_at", "")
        ma = data.get("modified_at", "")
        self._meta_label.setText(f"Created: {ca}   Modified: {ma}")
        
        # Stop all running debounce timers so loading doesn't trigger saves
        for timer in self._field_timers.values():
            timer.stop()
            
        self._building = False

        # ── Load AI Notes ──
        has_pdf = bool(data.get("pdf_path", "").strip())
        self._set_ai_ui_visible(has_pdf)
        raw_ai = data.get("ai_notes", "")
        if raw_ai:
            try:
                self._ai_data = json.loads(raw_ai)
                self._refresh_ai_display()
                self._ai_status.setText(self._lang.tr("ai_notes_available"))
            except json.JSONDecodeError:
                self._ai_data = {}
                self._ai_status.setText("")
        else:
            self._ai_data = {}
            self._ai_summary.clear()
            self._ai_keypoints.clear()
            if has_pdf:
                self._ai_status.setText(self._lang.tr("ai_notes_none"))
            else:
                self._ai_status.setText("")

        # ── Load Analysis Data (Topics & Semantic) ──
        # Parse topics
        topics = data.get("ai_topics", [])
        if isinstance(topics, str):
            try:
                import json as _json
                topics = _json.loads(topics)
            except Exception:
                topics = []
                
        # Clear existing topic badges
        while self._topics_layout.count():
            item = self._topics_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
                
        self._render_topic_badges(topics)

    def _render_topic_badges(self, topics: list):
        """Refresh the visible topic badges without reloading the whole entry."""
        while self._topics_layout.count():
            item = self._topics_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if topics and isinstance(topics, list) and len(topics) > 0:
            self._topics_empty_lbl.setVisible(False)
            self._topics_container.setVisible(True)
            for t in topics:
                badge = QLabel(str(t))
                badge.setStyleSheet("""
                    QLabel {
                        background-color: #f3e8ff;
                        color: #6d28d9;
                        border: 1px solid #d8b4fe;
                        border-radius: 12px;
                        padding: 4px 10px;
                        font-weight: 600;
                        font-size: 11px;
                    }
                """)
                self._topics_layout.addWidget(badge)
            self._topics_layout.addStretch()
            self._topics_editor.setText(", ".join(str(t) for t in topics))
        else:
            self._topics_empty_lbl.setVisible(True)
            self._topics_container.setVisible(False)
            self._topics_editor.setText("")

    def set_topics(self, topics: list[str]):
        """Update the manual topic editor and badges after a save."""
        cleaned = [str(topic).strip() for topic in topics if str(topic).strip()]
        self._render_topic_badges(cleaned)
        self._topics_editor.setText(", ".join(cleaned))
            
        # Invece di estratto biblio grezzo, carichiamo i riferimenti
        # Questo sarà popolato dal controller principale (MainWindow) che chiederà
        # di renderizzare il grafo in base a linked_references.
        pass

    def render_reference_graph(self, graph_json: dict):
        """Popola la lista delle referenze trovate nel tab."""
        self._ref_list_widget.clear()
        nodes = graph_json.get("nodes", [])
        
        # Filtra: mostra solo le referenze (non il nodo root)
        refs = [n for n in nodes if n.get("node_type") != "root"]
        
        if not refs:
            item = QListWidgetItem("Nessuna referenza collegata.")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self._ref_list_widget.addItem(item)
            self._btn_open_graph.setEnabled(False)
            return
        
        for ref in refs:
            label = ref.get("label", "?")
            title = ref.get("title", "")
            topics = ref.get("ai_topics", [])
            
            # Build display: "Label — Title [topic1, topic2]"
            parts = [label]
            if title:
                short_title = title[:50] + "…" if len(title) > 50 else title
                parts.append(f"— {short_title}")
            if topics:
                parts.append(f"[{', '.join(topics[:2])}]")
            
            display = " ".join(parts)
            item = QListWidgetItem(display)
            item.setData(Qt.UserRole, ref.get("id", ""))
            item.setToolTip(ref.get("tooltip", display))
            self._ref_list_widget.addItem(item)
        
        self._btn_open_graph.setEnabled(len(refs) > 0)
        
    def set_reference_processing(self, processing: bool, status: str = ""):
        self._reference_progress.setVisible(processing)
        if processing:
            self._reference_progress.setRange(0, 0)
        self._reference_status.setText(status)
        self._btn_refresh_bibliography.setEnabled(not processing and self._current_id is not None)

    def set_semantic_data(self, cluster: dict | None, metrics: dict | None):
        """Called by MainWindow to update semantic metrics in the Analysis tab."""
        if not cluster and not metrics:
            self._semantic_empty_lbl.setVisible(True)
            self._semantic_container.setVisible(False)
            return
            
        self._semantic_empty_lbl.setVisible(False)
        self._semantic_container.setVisible(True)
        
        if cluster:
            label = cluster.get("label", "Unknown")
            color = cluster.get("color", "#7c3aed")
            self._cluster_lbl.setText(f"● {label}")
            self._cluster_lbl.setStyleSheet(f"color: {color}; font-weight: 600;")
        else:
            self._cluster_lbl.setText("-")
            self._cluster_lbl.setStyleSheet("")
            
        if metrics:
            role = metrics.get("cluster_role", "")
            role_tr = self._lang.tr(role.lower()) if role else "-"
            self._role_lbl.setText(role_tr)
            
            c_val = min(100, int(metrics.get("degree_centrality", 0) * 100))
            self._centrality_bar.setValue(c_val)
            self._centrality_bar.setToolTip(f"{c_val}%")
            
            p_val = min(100, int(metrics.get("pagerank", 0) * 100))
            self._pagerank_bar.setValue(p_val)
            self._pagerank_bar.setToolTip(f"{p_val}%")
            
            b_val = min(100, int(metrics.get("betweenness", 0) * 100))
            self._betweenness_bar.setValue(b_val)
            self._betweenness_bar.setToolTip(f"{b_val}%")
        else:
            self._role_lbl.setText("-")
            self._centrality_bar.setValue(0)
            self._pagerank_bar.setValue(0)
            self._betweenness_bar.setValue(0)

    def clear(self):
        self._building = True
        self._current_id = None
        for widget in self._fields.values():
            widget.clear() if isinstance(widget, QTextEdit) else widget.clear()
        self._is_editor_chk.setChecked(False)
        self._meta_label.setText("")
        self._ai_data = {}
        self._ai_summary.clear()
        self._ai_keypoints.clear()
        self._ai_status.setText("")
        self._topics_editor.clear()
        self._building = False

    def set_ai_notes(self, data: dict):
        """Called by MainWindowView when the AI worker finishes successfully."""
        self._ai_data = data
        self._refresh_ai_display()
        self._ai_status.setText(self._lang.tr("ai_notes_finished"))
        self._ai_progress.setVisible(False)
        self._btn_gen_ai.setEnabled(True)

    def set_ai_generating(self, generating: bool):
        """Show/hide the indeterminate progress bar while generating."""
        self._ai_progress.setVisible(generating)
        self._btn_gen_ai.setEnabled(not generating)
        if generating:
            self._ai_status.setText(self._lang.tr("ai_notes_generating"))

    def set_ai_error(self, msg: str):
        """Display an error message in the AI Notes tab."""
        self._ai_progress.setVisible(False)
        self._btn_gen_ai.setEnabled(True)
        self._ai_status.setText(f"❌  Errore: {msg}")

    def get_publisher(self) -> str:
        le = self._fields.get("publisher")
        return le.text() if isinstance(le, QLineEdit) else ""

    def set_publisher(self, pub: str):
        le = self._fields.get("publisher")
        if isinstance(le, QLineEdit):
            le.setText(pub)

    def set_title_warning(self, is_duplicate: bool):
        if hasattr(self, "_title_warning_lbl"):
            self._title_warning_lbl.setVisible(is_duplicate)

    def set_journal_completions(self, journals: list[str]):
        if hasattr(self, "_journal_completer"):
            self._journal_completer.setModel(QStringListModel(journals, self))

    def set_topic_completions(self, topics: list[str]):
        if hasattr(self, "_topics_completer"):
            unique = []
            seen = set()
            for t in topics:
                value = str(t).strip()
                if not value or value.lower() in seen:
                    continue
                seen.add(value.lower())
                unique.append(value)
            self._topics_completer.setModel(QStringListModel(unique, self))
