"""
main_window.py — MainWindowView: primary application window.
"""
import json
import os
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QListWidget,
    QListWidgetItem, QLabel, QPushButton, QToolBar, QStatusBar, QLineEdit,
    QComboBox, QCheckBox, QMessageBox, QSizePolicy, QAbstractItemView,
    QFileDialog, QMenuBar, QMenu, QApplication, QDockWidget, QStackedWidget,
    QTabWidget,
)
from PySide6.QtCore import Qt, QTimer, QSize, QSettings, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDragLeaveEvent, QDropEvent, QShortcut, QKeySequence

from app.theme import icon, ThemeManager
from app.adapter import EntryAdapter
from app.model import EntryModel
from app.views.entry_form import EntryFormWidget
from app.dialogs.export_dialog import ExportDialog
from app.widgets.toolbar_manager import ToolbarManager
from app.widgets.status_bar_manager import StatusBarManager
from app.dialogs.pdf_manager import PdfManagerDialog
from app.dialogs.ai_settings_dialog import AiSettingsDialog
from app.dialogs.settings_dialog import SettingsDialog
from app.dialogs.startup_dialog import StartupDialog
from app.dialogs.command_palette import CommandPalette
from app.widgets.entry_table import EntryTableWidget
from app.ai_worker import AiNotesWorker, ReferenceExtractionWorker
from app.i18n import LanguageManager
from app.widgets.knowledge_graph_widget import KnowledgeGraphWidget
from app.dialogs.reference_dag_dialog import ReferenceDagDialog
from app.widgets.thematic_sidebar import ThematicSidebarWidget, SortMode
from app.widgets.drop_overlay import DropOverlayWidget
from app.widgets.import_queue_widget import ImportQueueWidget
from app.widgets.pdf_viewer import PdfViewerWidget
from app.services.import_pipeline import ImportPipeline, DropItem, DropType
from app.services.learning import ImportLearningSystem
from app.workers.import_worker import ImportWorker
from app.services.update_service import UpdateService, UpdateWorker, ReleaseInfo


class MainWindowView(QMainWindow):
    """Primary application window."""

    def __init__(self, adapter: EntryAdapter, theme_mgr: ThemeManager, lang_mgr: LanguageManager):
        super().__init__()
        self._adapter   = adapter
        self._theme     = theme_mgr
        self._lang      = lang_mgr
        self._ai_worker: AiNotesWorker | None = None
        self._reference_worker: ReferenceExtractionWorker | None = None
        self._ocr_worker = None
        self._dag_dialog: ReferenceDagDialog | None = None
        self._local_dag_dialog = None
        self._local_dag_widget = None
        self._import_worker: ImportWorker | None = None
        self._update_worker: UpdateWorker | None = None
        self._pending_release: ReleaseInfo | None = None
        self._learning = ImportLearningSystem(adapter._model)

        self._adapter.entriesChanged.connect(self._refresh_list)
        self._adapter.entrySelected.connect(self._on_entry_selected)
        self._adapter.autosaved.connect(self._on_autosaved)
        self._adapter.statsChanged.connect(self._on_stats)
        self._theme.themeChanged.connect(self._on_theme_changed)

        self._autosave_timer = QTimer()
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(2000)
        self._autosave_timer.timeout.connect(lambda: getattr(self, "_status_mgr", None) and self._status_mgr.set_autosave(""))

        # Command Palette Shortcut
        self._palette_shortcut = QShortcut(QKeySequence("Ctrl+Shift+P"), self)
        self._palette_shortcut.activated.connect(self._show_command_palette)

        self.setWindowIcon(icon("Logo"))
        self.setMinimumSize(1040, 680)
        self.setAcceptDrops(True)
        self._build_ui()
        self._build_graph_dock()
        self._build_import_dock()
        self._build_reference_graph_dock()
        self._update_window_title()
        self._refresh_list()
        self._on_stats(adapter.get_stats())
        QTimer.singleShot(1500, lambda: self._check_for_updates(silent=True))

    # ── build ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Menu bar ───────────────────────────────────────────────────────
        menu_bar = QMenuBar(self)
        self.setMenuBar(menu_bar)

        archive_menu = menu_bar.addMenu(self._lang.tr('menu_archive'))

        act_new_db = QAction(icon("folder-plus"), self._lang.tr("act_new_db"), self)
        act_new_db.setToolTip(self._lang.tr("act_new_db_tip"))
        act_new_db.triggered.connect(self._new_archive)

        act_open_db = QAction(icon("books"), self._lang.tr("act_open_db"), self)
        act_open_db.setToolTip(self._lang.tr("act_open_db_tip"))
        act_open_db.triggered.connect(self._open_archive)

        act_preferences = QAction(icon("settings"), self._lang.tr("act_preferences"), self)
        act_preferences.setToolTip(self._lang.tr("act_preferences_tip"))
        act_preferences.triggered.connect(self._open_preferences)

        act_quit = QAction(self._lang.tr("act_quit"), self)
        act_quit.triggered.connect(self.close)

        archive_menu.addAction(act_new_db)
        archive_menu.addAction(act_open_db)
        archive_menu.addSeparator()
        archive_menu.addAction(act_preferences)
        archive_menu.addSeparator()
        archive_menu.addAction(act_quit)

        # ── Edit Menu ────────────────────────────────────────────────────
        edit_menu = menu_bar.addMenu(self._lang.tr('menu_edit'))

        act_cut = QAction(icon("scissors"), self._lang.tr("act_cut"), self)
        act_cut.setShortcut("Ctrl+X")
        act_cut.triggered.connect(lambda: self._editor_action("cut"))
        edit_menu.addAction(act_cut)

        act_copy = QAction(icon("copy"), self._lang.tr("act_copy"), self)
        act_copy.setShortcut("Ctrl+C")
        act_copy.triggered.connect(lambda: self._editor_action("copy"))
        edit_menu.addAction(act_copy)

        act_paste = QAction(icon("clipboard"), self._lang.tr("act_paste"), self)
        act_paste.setShortcut("Ctrl+V")
        act_paste.triggered.connect(lambda: self._editor_action("paste"))
        edit_menu.addAction(act_paste)

        # ── View Menu ─────────────────────────────────────────────────────
        view_menu = menu_bar.addMenu(self._lang.tr('menu_view'))

        self._toggle_graph_act = QAction(icon("network"), self._lang.tr("view_graph"), self)
        self._toggle_graph_act.setCheckable(True)
        self._toggle_graph_act.triggered.connect(self._toggle_graph)
        view_menu.addAction(self._toggle_graph_act)

        self._act_global_dag = QAction(icon("chart-sankey"), self._lang.tr("view_global_dag"), self)
        self._act_global_dag.setCheckable(True)
        self._act_global_dag.triggered.connect(self._on_global_dag_requested)
        view_menu.addAction(self._act_global_dag)

        self._toggle_pdf_act = QAction(icon("file-type-pdf"), self._lang.tr("view_pdf_reader"), self)
        self._toggle_pdf_act.setCheckable(True)
        self._toggle_pdf_act.triggered.connect(self._toggle_pdf_viewer)
        view_menu.addAction(self._toggle_pdf_act)

        # ── Tools Menu ─────────────────────────────────────────────────────
        tools_menu = menu_bar.addMenu(self._lang.tr("menu_tools"))

        self._act_topic_dictionary = QAction(icon("book"), self._lang.tr("act_topic_dictionary"), self)
        self._act_topic_dictionary.triggered.connect(self._show_topic_dictionary)
        tools_menu.addAction(self._act_topic_dictionary)

        self._act_check_updates = QAction(icon("refresh-alert"), self._lang.tr("act_check_updates"), self)
        self._act_check_updates.setToolTip(self._lang.tr("act_check_updates_tip"))
        self._act_check_updates.triggered.connect(lambda: self._check_for_updates(silent=False))
        tools_menu.addAction(self._act_check_updates)

        # ── Licenze Menu ─────────────────────────────────────────────────────
        licenze_menu = menu_bar.addMenu(self._lang.tr('menu_licenze'))

        act_licenze = QAction(icon("certificate"), self._lang.tr("act_licenze"), self)
        act_licenze.triggered.connect(self._show_licenze)
        licenze_menu.addAction(act_licenze)
        

        # ── Toolbar ───────────────────────────────────────────────────────
        callbacks = {
            "new_entry": self._new_entry,
            "delete_current": self._delete_current,
            "open_export": self._open_export,
            "open_pdf_manager": self._open_pdf_manager,
            "toggle_theme": self._toggle_theme,
            "open_support": self._open_support,
            "show_topic_dictionary": self._show_topic_dictionary,
            "refresh_list": self._refresh_list,
            "toggle_sidebar": self._toggle_sidebar,
            "toggle_graph": self._toggle_graph,
        }
        self._toolbar_mgr = ToolbarManager(self, self._lang, callbacks)
        self._act_add_bib = self._toolbar_mgr.act_add_bib
        self._act_add_sit = self._toolbar_mgr.act_add_sit
        self._act_add_tesi = self._toolbar_mgr.act_add_tesi
        self._act_delete = self._toolbar_mgr.act_delete
        self._act_export = self._toolbar_mgr.act_export
        self._act_pdf_mgr = self._toolbar_mgr.act_pdf_mgr
        self._act_theme = self._toolbar_mgr.act_theme
        self._act_support = self._toolbar_mgr.act_support
        self._act_sidebar = self._toolbar_mgr.act_sidebar
        self._act_graph = self._toolbar_mgr.act_graph
        self._search = self._toolbar_mgr.search
        self._filter_combo = self._toolbar_mgr.filter_combo
        self._toggle_graph_act = self._toolbar_mgr.act_graph

        # ── Central splitter ──────────────────────────────────────────────
        central  = QWidget()
        self.setCentralWidget(central)
        h_layout = QHBoxLayout(central)
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)
        h_layout.addWidget(splitter)

        # Left — entry list
        left_panel = QWidget()
        left_panel.setMinimumWidth(340)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(8, 8, 4, 8)
        left_layout.setSpacing(6)

        hdr = QHBoxLayout()
        list_title = QLabel(self._lang.tr("section_entries"))
        list_title.setObjectName("sectionTitle")
        self._count_badge = QLabel("0")
        self._count_badge.setObjectName("entryCount")
        hdr.addWidget(list_title)
        hdr.addStretch()
        hdr.addWidget(self._count_badge)
        left_layout.addLayout(hdr)

        # ── List widget stack (flat list + thematic sidebar) ────────────
        self._list_stack = QStackedWidget()

        # Page 0: entry table widget
        self._list = EntryTableWidget(self._lang, self)
        self._list.entrySelected.connect(self._on_list_selection)
        self._list.readStatusChanged.connect(self._adapter.set_read_status)
        self._list.pdfOpenRequested.connect(self._open_pdf)
        self._list.pdfUnlinkRequested.connect(self._unlink_pdf_row)
        self._list.pdfLinkRequested.connect(self._link_pdf_manual)
        self._list_stack.addWidget(self._list)

        # Page 1: thematic sidebar
        self._thematic_sidebar = ThematicSidebarWidget(self._lang)
        self._thematic_sidebar.entrySelected.connect(self._on_sidebar_entry_selected)
        self._thematic_sidebar.pdfOpenRequested.connect(self._open_pdf)
        self._list_stack.addWidget(self._thematic_sidebar)

        left_layout.addWidget(self._list_stack)
        splitter.addWidget(left_panel)

        # Right — form
        right_panel  = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(4, 8, 8, 8)
        right_layout.setSpacing(0)

        self._pdf_widget = PdfViewerWidget(self._lang, right_panel)
        self._pdf_widget.set_model(self._adapter._model)

        form_panel = QWidget()
        form_layout = QVBoxLayout(form_panel)
        form_layout.setContentsMargins(0, 4, 0, 0)
        self._welcome = QLabel(
            f"⬅  {self._lang.tr('welcome_msg')}"
        )
        self._welcome.setAlignment(Qt.AlignCenter)
        self._welcome.setStyleSheet("color:#3a3b5e; font-size:15px; padding:30px;")
        form_layout.addWidget(self._welcome)

        self._form = EntryFormWidget(self._lang)
        self._form.setVisible(False)
        self._form.fieldChanged.connect(self._on_field_changed)
        self._form.journalCompleted.connect(self._on_journal_completed)
        self._form.aiNotesRequested.connect(self._on_ai_notes_requested)
        self._form.semanticKeywordsRequested.connect(self._on_semantic_keywords_requested)
        self._form.topicsEdited.connect(self._on_topics_edited)
        self._form.resetAiTopicsRequested.connect(self._on_reset_ai_topics_requested)
        self._form.resetAllAiTopicsRequested.connect(self._on_reset_all_ai_topics_requested)
        self._form.bibliographyRequested.connect(self._on_bibliography_requested)
        self._form.ocrRequested.connect(self._on_ocr_requested)
        self._form.referenceGraphRequested.connect(self._on_reference_graph_requested)
        self._form.extractionExportRequested.connect(self._on_extraction_export_requested)
        self._form.rAnalysisRequested.connect(self._on_r_analysis_requested)
        self._form.manualBibliographyEdited.connect(self._on_manual_bibliography_edited)
        form_layout.addWidget(self._form, 1)

        self._work_tabs = QTabWidget()
        self._work_tabs.addTab(form_panel, "Entry")
        self._work_tabs.addTab(self._pdf_widget, "PDF")
        self._work_tabs.currentChanged.connect(self._on_work_tab_changed)
        right_layout.addWidget(self._work_tabs, 1)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 700])

        # ── Status bar ────────────────────────────────────────────────────
        self._status_mgr = StatusBarManager(self, self._lang, self._theme)

    def _check_for_updates(self, silent: bool = False):
        if self._update_worker and self._update_worker.isRunning():
            return
        self._act_check_updates.setEnabled(False)
        self._update_worker = UpdateWorker(parent=self)
        self._update_worker.found.connect(lambda release: self._on_update_found(release, silent))
        self._update_worker.failed.connect(lambda error: self._on_update_failed(error, silent))
        self._update_worker.finished.connect(lambda: self._act_check_updates.setEnabled(True))
        self._update_worker.start()

    def _on_update_found(self, release: ReleaseInfo | None, silent: bool):
        if release is None:
            if not silent:
                QMessageBox.information(self, self._lang.tr("update_title"), self._lang.tr("update_none"))
            return
        self._pending_release = release
        answer = QMessageBox.question(
            self,
            self._lang.tr("update_title"),
            self._lang.tr("update_available").format(version=release.version),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self._download_update(release)

    def _download_update(self, release: ReleaseInfo):
        self._act_check_updates.setEnabled(False)
        self._update_worker = UpdateWorker(release, self)
        self._update_worker.progress.connect(lambda value: self.statusBar().showMessage(f"{self._lang.tr('update_downloading')} {value}%"))
        self._update_worker.downloaded.connect(self._on_update_downloaded)
        self._update_worker.failed.connect(lambda error: self._on_update_failed(error, False))
        self._update_worker.finished.connect(lambda: self._act_check_updates.setEnabled(True))
        self._update_worker.start()

    def _on_update_downloaded(self, installer_path: str):
        QMessageBox.information(self, self._lang.tr("update_title"), self._lang.tr("update_ready"))
        UpdateService.install_after_exit(Path(installer_path))
        self.close()

    def _on_update_failed(self, error: str, silent: bool):
        if not silent:
            QMessageBox.warning(self, self._lang.tr("update_error_title"), self._lang.tr("update_error").format(error=error))

    # ── window title & DB label ────────────────────────────────────────────
    def _update_window_title(self):
        db_path = self._adapter._model._conn.execute(
            "PRAGMA database_list"
        ).fetchone()
        if db_path:
            db_name = Path(db_path[2]).name if db_path[2] else "bibliography.db"
        else:
            db_name = "bibliography.db"
        self.setWindowTitle(f"CiteMind — {db_name}")
        if hasattr(self, "_status_mgr"):
            self._status_mgr.set_db_name(db_name)

    # ── Command Palette ────────────────────────────────────────────────────
    def _show_command_palette(self):
        commands = [
            {"name": self._lang.tr("tb_add_bib"), "icon": "book-upload", "action": lambda: self._new_entry("bibliography")},
            {"name": self._lang.tr("tb_add_sit"), "icon": "world-www", "action": lambda: self._new_entry("sitography")},
            {"name": self._lang.tr("tb_add_tesi"), "icon": "file-certificate", "action": lambda: self._new_entry("tesi")},
            {"name": self._lang.tr("act_new_db"), "icon": "folder-plus", "action": self._new_archive},
            {"name": self._lang.tr("act_open_db"), "icon": "books", "action": self._open_archive},
            {"name": self._lang.tr("act_preferences"), "icon": "settings", "action": self._open_preferences},
            {"name": self._lang.tr("tb_theme"), "icon": "sun", "action": self._toggle_theme},
            {"name": self._lang.tr("tb_export"), "icon": "file-export", "action": self._open_export},
            {"name": self._lang.tr("tb_graph"), "icon": "graph", "action": lambda: self._toggle_graph(not self._graph_widget.isVisible())},
            {"name": self._lang.tr("tb_sidebar"), "icon": "filter", "action": lambda: self._toggle_sidebar(self._list_stack.currentIndex() == 0)},
            {"name": self._lang.tr("act_quit"), "icon": "power", "action": self.close},
        ]
        cp = CommandPalette(self, commands)
        cp.exec()

    # ── Archive management ─────────────────────────────────────────────────
    def _current_db_dir(self) -> str:
        """Return the directory of the currently open database."""
        db_info = self._adapter._model._conn.execute("PRAGMA database_list").fetchone()
        if db_info and db_info[2]:
            return str(Path(db_info[2]).parent)
        return str(Path.home())

    def _new_archive(self):
        path, _ = QFileDialog.getSaveFileName(
            self, self._lang.tr("dialog_new_archive"), self._current_db_dir(),
            self._lang.tr("dialog_db_files")
        )
        if path:
            if not path.endswith(".db"):
                path += ".db"
            StartupDialog.add_recent_project(path)
            self._switch_db(path)

    def _open_archive(self):
        path, _ = QFileDialog.getOpenFileName(
            self, self._lang.tr("dialog_open_archive"), self._current_db_dir(),
            self._lang.tr("dialog_db_files")
        )
        if path:
            StartupDialog.add_recent_project(path)
            self._switch_db(path)

    def _switch_db(self, new_path: str):
        """Flush pending saves, swap the model/adapter to a new DB file."""
        # 1. Save any pending changes
        self._adapter._flush_save()

        # 2. Abort any running AI worker
        if self._ai_worker and self._ai_worker.isRunning():
            self._ai_worker.cancel()
            self._ai_worker.wait()
            self._ai_worker = None

        # 3. Close current model
        old_model = self._adapter._model
        old_model.close()

        # 4. Open new model
        new_model = EntryModel(Path(new_path))
        new_adapter = EntryAdapter(new_model, self)
        new_adapter.entriesChanged.connect(self._refresh_list)
        new_adapter.entrySelected.connect(self._on_entry_selected)
        new_adapter.autosaved.connect(self._on_autosaved)
        new_adapter.statsChanged.connect(self._on_stats)

        self._adapter = new_adapter
        self._pdf_widget.set_model(new_model)
        self._pdf_widget.set_document(None)

        # 5. Persist last-used path
        QSettings("CiteMind", "CiteMind").setValue("last_db_path", new_path)

        # 6. Reset UI
        self._form.clear()
        self._form.setVisible(False)
        self._welcome.setVisible(True)
        self._act_delete.setEnabled(False)
        self._update_window_title()
        self._refresh_list()
        self._on_stats(self._adapter.get_stats())
        self.statusBar().showMessage(self._lang.tr("status_archive_opened").format(name=Path(new_path).name))
 
    def _open_preferences(self):
        """Open the unified Preferences dialog."""
        SettingsDialog(self._lang, self._theme, self).exec()

    # ── Knowledge Graph dock ────────────────────────────────────────────────
    def _build_graph_dock(self):
        """Create the knowledge graph dock widget (hidden by default)."""
        self._graph_widget = KnowledgeGraphWidget(self._lang, self)
        self._graph_widget.set_model(self._adapter._model)
        self._graph_widget.documentRequested.connect(self._on_graph_doc_requested)
        self._graph_widget.filterRequested.connect(self._on_graph_filter_requested)
        self.addDockWidget(Qt.RightDockWidgetArea, self._graph_widget)
        self._graph_widget.setVisible(False)

        # Feed data whenever entries change
        self._adapter.entriesChanged.connect(self._feed_graph_data)

    def _toggle_pdf_viewer(self, checked: bool):
        self._work_tabs.setCurrentIndex(1 if checked else 0)
        if hasattr(self, "_toggle_pdf_act"):
            self._toggle_pdf_act.setChecked(checked)

    def _on_work_tab_changed(self, index: int):
        if hasattr(self, "_toggle_pdf_act"):
            self._toggle_pdf_act.setChecked(index == 1)

    def _build_reference_graph_dock(self):
        """Create the reference graph dock widget (hidden by default)."""
        from app.dialogs.reference_graph_dialog import ReferenceGraphWidget
        self._ref_graph_widget = ReferenceGraphWidget(self._lang, self)
        self._ref_graph_dock = QDockWidget(self._lang.tr("view_global_dag"), self)
        self._ref_graph_dock.setWidget(self._ref_graph_widget)
        self._ref_graph_dock.setFeatures(
            QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self._ref_graph_dock)
        self._ref_graph_dock.setVisible(False)
        self._ref_graph_dock.visibilityChanged.connect(self._on_ref_graph_dock_visibility_changed)

    def _on_ref_graph_dock_visibility_changed(self, visible: bool):
        if hasattr(self, "_act_global_dag"):
            self._act_global_dag.setChecked(visible)

    def _toggle_graph(self, checked: bool):
        """Show/hide the Knowledge Graph dock panel."""
        self._graph_widget.setVisible(checked)
        if checked:
            self._feed_graph_data()

    def _toggle_sidebar(self, checked: bool):
        """Switch between the flat list and the thematic sidebar."""
        self._list_stack.setCurrentIndex(1 if checked else 0)
        if checked:
            self._thematic_sidebar._rebuild()

    def _feed_graph_data(self):
        """Push current entries + DB path to the graph widget."""
        if not self._graph_widget.isVisible():
            return
        db_path = self._adapter._model._conn.execute(
            "PRAGMA database_list"
        ).fetchone()
        if db_path and db_path[2]:
            p = Path(db_path[2])
        else:
            p = Path.home() / "bibliography.db"
        entries = self._adapter._model.read_all_full()
        self._graph_widget.set_data(entries, p)
        # Try cache, rebuild if stale or missing
        if not self._graph_widget.try_load_cache():
            self._graph_widget.schedule_rebuild()

    def _on_graph_doc_requested(self, entry_id: int):
        """A document node was clicked in the graph → select it in the list."""
        if self._list_stack.currentIndex() == 1:
            self._thematic_sidebar.select_entry(entry_id)
        else:
            self._list.select_entry(entry_id)

    def _on_graph_filter_requested(self, text: str):
        """A keyword/author node was clicked → set search filter."""
        self._search.setText(text)

    # ── Import dock ────────────────────────────────────────────────────────
    def _build_import_dock(self):
        """Create the import queue dock widget (hidden by default)."""
        self._import_queue = ImportQueueWidget()
        self._import_queue.entryClicked.connect(self._on_import_entry_clicked)

        self._import_dock = QDockWidget("Import Queue", self)
        self._import_dock.setWidget(self._import_queue)
        self._import_dock.setFeatures(
            QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable
        )
        self.addDockWidget(Qt.BottomDockWidgetArea, self._import_dock)
        self._import_dock.setVisible(False)

        # Drop overlay (invisible until drag enters)
        self._drop_overlay = DropOverlayWidget(parent=self)

    def _on_import_entry_clicked(self, entry_id: int):
        """Navigate to an imported entry in the list."""
        self._on_graph_doc_requested(entry_id)
        self._adapter.select_entry(entry_id)

    # ── Drag and Drop ─────────────────────────────────────────────────────
    _SUPPORTED_EXTENSIONS = {".pdf", ".bib", ".ris"}
    _DOI_REGEX = re.compile(r'(10\.\d{4,}/[^\s,;"\'\]>]+)')

    def dragEnterEvent(self, event: QDragEnterEvent):
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path and Path(path).suffix.lower() in self._SUPPORTED_EXTENSIONS:
                    event.acceptProposedAction()
                    self._drop_overlay.show_overlay()
                    return
        if mime.hasText():
            text = mime.text().strip()
            if self._DOI_REGEX.search(text) or text.startswith("http"):
                event.acceptProposedAction()
                self._drop_overlay.show_overlay()
                return
        event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent):
        self._drop_overlay.hide_overlay()

    def dropEvent(self, event: QDropEvent):
        self._drop_overlay.hide_overlay()
        event.acceptProposedAction()

        items: list[DropItem] = []
        mime = event.mimeData()

        # File drops
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if not path:
                    continue
                drop_type = ImportPipeline.detect_drop_type(path)
                if drop_type:
                    items.append(DropItem(type=drop_type, path=path))

        # Text drops (DOI or URL)
        if mime.hasText():
            text = mime.text().strip()
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                doi = ImportPipeline.extract_doi_from_text(line)
                if doi:
                    items.append(DropItem(type=DropType.DOI, value=doi))
                elif line.startswith("http"):
                    items.append(DropItem(type=DropType.URL, value=line))

        if items:
            self._start_import(items)

    def _start_import(self, items: list[DropItem]):
        """Queue items and start the import worker."""
        # Show import dock
        self._import_dock.setVisible(True)

        # Add items to queue UI
        queue_items: list[tuple[int, DropItem]] = []
        for item in items:
            filename = Path(item.path).name if item.path else item.value[:50]
            idx = self._import_queue.add_item(filename)
            queue_items.append((idx, item))

        # Create pipeline
        ollama_url = AiSettingsDialog.get_ollama_url()
        model_name = AiSettingsDialog.get_model_name()
        pipeline = ImportPipeline(
            model=self._adapter._model,
            ollama_url=ollama_url,
            model_name=model_name,
        )

        # Abort previous worker if running
        if self._import_worker and self._import_worker.isRunning():
            self._import_worker.cancel()
            self._import_worker.wait()

        # Start background worker
        self._import_worker = ImportWorker(pipeline, queue_items, parent=self)
        self._import_worker.itemStarted.connect(self._on_import_item_started)
        self._import_worker.itemCompleted.connect(self._on_import_item_completed)
        self._import_worker.allCompleted.connect(self._on_import_all_completed)
        self._import_worker.start()

    def _on_import_item_started(self, idx: int, status: str):
        self._import_queue.update_status(idx, status)

    def _on_import_item_completed(self, idx: int, result):
        from app.services.import_pipeline import ImportResult
        self._import_queue.complete_item(idx, result)

        # If needs review, show review dialog
        if result.needs_review and result.entry_id:
            self._show_import_review(result)

    def _on_import_all_completed(self):
        """All imports finished — refresh the list."""
        self._refresh_list()
        self._on_stats(self._adapter.get_stats())
        self.statusBar().showMessage("✅  Import completed")

    def _show_import_review(self, result):
        """Show review dialog for a low-confidence import."""
        from app.dialogs.import_review_dialog import ImportReviewDialog
        dlg = ImportReviewDialog(result, self._lang, self)
        dlg.correctionsMade.connect(self._on_import_corrections)
        if dlg.exec() == ImportReviewDialog.Accepted:
            # Update entry with corrected data
            corrected = dlg.get_corrected_data()
            if result.entry_id:
                self._adapter._model.update(result.entry_id, corrected)
                self._refresh_list()
        elif result.entry_id:
            # User skipped — delete the entry
            self._adapter._model.delete(result.entry_id)
            self._refresh_list()

    def _on_import_corrections(self, entry_id: int, original: dict, corrected: dict):
        """Record user corrections for the learning system."""
        self._learning.record_correction(original, corrected)

    # ── Thematic sidebar integration ──────────────────────────────────────
    def _on_sidebar_entry_selected(self, entry_id: int):
        """Entry selected via the thematic sidebar."""
        self._adapter.select_entry(entry_id)
        self._act_delete.setEnabled(True)

    # ── theme ──────────────────────────────────────────────────────────────
    def _toggle_theme(self):
        self._theme.toggle()

    def _open_support(self):
        QDesktopServices.openUrl(QUrl("https://buymeacoffee.com/ikimattia"))

    def _on_theme_changed(self, name: str):
        if hasattr(self, "_status_mgr"):
            self._status_mgr.update_theme()
        self._act_theme.setIcon(icon(self._theme.theme_icon(name)))
        self.setWindowIcon(icon("Logo"))
        self._act_add_bib.setIcon(icon("book-upload"))
        self._act_add_sit.setIcon(icon("world-www"))
        self._act_add_tesi.setIcon(icon("file-certificate"))
        self._act_delete.setIcon(icon("trash"))
        self._act_export.setIcon(icon("file-export"))
        self._act_pdf_mgr.setIcon(icon("folder-plus"))
        self._act_graph.setIcon(icon("graph"))
        self._act_sidebar.setIcon(icon("filter"))
        self._graph_widget.set_dark_mode(name == "dark")
        self._form.reload_icons()
        self._pdf_widget.refresh_theme()
        self._refresh_list()

    # ── list ───────────────────────────────────────────────────────────────
    def _refresh_list(self):
        search  = self._search.text().strip()
        fi      = self._filter_combo.currentIndex()
        et      = "" if fi == 0 else (
            "bibliography" if fi == 1 else ("sitography" if fi == 2 else "tesi")
        )
        entries = self._adapter.load_entries(search, et)
        colors  = self._theme.list_colors()

        # Feed data to the new thematic sidebar
        try:
            clusters = self._adapter._model.get_all_clusters()
            for c in clusters:
                c["entry_ids"] = self._adapter._model.get_cluster_entries(c["id"])
            metrics = self._adapter._model.get_all_metrics()
            self._thematic_sidebar.set_theme_colors(colors)
            self._thematic_sidebar.set_entries(entries, clusters, metrics)
        except Exception as e:
            print("Error updating thematic sidebar:", e)

        prev_id = self._adapter.current_id
        self._list.populate(entries, colors, prev_id)

        self._count_badge.setText(str(len(entries)))
        self._form.set_journal_completions(self._adapter.get_distinct_journals())
        self._form.set_topic_completions(self._adapter.get_distinct_ai_topics())

    # ── selection / CRUD ───────────────────────────────────────────────────
    def _on_list_selection(self, entry_id: int):
        if entry_id == -1:
            self._adapter.select_entry(None)
            self._form.clear()
            self._form.setVisible(False)
            self._welcome.setVisible(True)
            self._act_delete.setEnabled(False)
            self._thematic_sidebar.clear_selection()
            return
        
        self._adapter.select_entry(entry_id)
        self._act_delete.setEnabled(True)

    def _on_entry_selected(self, data: dict):
        self._welcome.setVisible(False)
        self._form.setVisible(True)
        self._form.load(data)
        self._form.set_title_warning(self._adapter.has_duplicate_title(data.get("title", "")))

        entry_id = data.get("id")
        self._pdf_widget.set_document(entry_id, data.get("pdf_path", ""))
        if hasattr(self, "_graph_widget") and self._graph_widget is not None:
            canvas = getattr(self._graph_widget, "_canvas", None)
            if canvas is not None:
                if entry_id is not None:
                    canvas.highlight_node(f"doc_{entry_id}")
                else:
                    canvas.clear_highlight()
        
        # Load semantic data
        if entry_id is not None:
            cluster = self._adapter._model.get_primary_cluster(entry_id)
            metrics = self._adapter._model.get_metrics(entry_id)
            self._form.set_semantic_data(cluster, metrics)
            self._refresh_reference_graph(entry_id)
            if self._local_dag_dialog is not None and self._local_dag_dialog.isVisible():
                self._local_dag_widget.load_graph(self._last_ref_graph_json)
            if self._ref_graph_dock.isVisible():
                self._refresh_global_reference_graph()
        else:
            self._form.set_semantic_data(None, None)

    def _new_entry(self, entry_type: str):
        new_id = self._adapter.new_entry(entry_type)
        self._refresh_list()
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.UserRole) == new_id:
                self._list.setCurrentItem(item)
                break
        self._form.clear()
        self._form.setVisible(True)
        self._welcome.setVisible(False)
        self._adapter.select_entry(new_id)

    def _open_pdf(self, path: str):
        if os.path.exists(path):
            entry_id = self._adapter.current_id
            if entry_id is None:
                linked = self._adapter._model.get_linked_entries()
                match = next((entry for entry in linked if entry.get("pdf_path") == path), None)
                entry_id = match.get("id") if match else None
            self._pdf_widget.set_document(entry_id, path)
            self._work_tabs.setCurrentIndex(1)
        else:
            QMessageBox.warning(self, self._lang.tr("msg_pdf_not_found_title"),
                                f"{self._lang.tr('msg_pdf_not_found_text')}\n{path}")

    def _delete_current(self):
        if self._adapter.current_id is None:
            return
        ret = QMessageBox.question(
            self, self._lang.tr("msg_delete_confirm_title"),
            self._lang.tr("msg_delete_confirm_text"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self._adapter.delete_entry(self._adapter.current_id)
            self._form.clear()
            self._form.setVisible(False)
            self._welcome.setVisible(True)
            self._act_delete.setEnabled(False)

    # ── dialogs ────────────────────────────────────────────────────────────
    def _open_export(self):
        ExportDialog(self._adapter, self._lang, self).exec()

    def _open_pdf_manager(self):
        PdfManagerDialog(self._adapter, self._lang, self).exec()

    def _on_extraction_export_requested(self, entry_id: int):
        """Export extracted PDF items for the selected entry."""
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Esporta dataset PDF",
            str(Path.home() / "citemind_extraction.csv"),
            "CSV (*.csv);;JSON (*.json)",
        )
        if not path:
            return

        include_pending = QMessageBox.question(
            self,
            "Elementi da verificare",
            "Includere anche immagini, tabelle o metadati ancora da verificare?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes

        try:
            from app.services.extraction_export import export_extracted_items
            file_format = "json" if path.lower().endswith(".json") else "csv"
            count = export_extracted_items(
                self._adapter._model,
                entry_id,
                path,
                file_format=file_format,
                include_pending=include_pending,
            )
            QMessageBox.information(
                self,
                "Esportazione completata",
                f"Esportati {count} elementi in:\n{path}",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Esportazione fallita", str(exc))

    def _on_r_analysis_requested(self, entry_id: int):
        """Run the optional R summary for confirmed extracted items."""
        entry = self._adapter._model.read_by_id(entry_id)
        pdf_path = (entry or {}).get("pdf_path", "").strip()
        if not pdf_path:
            QMessageBox.warning(self, "Analisi R", "L'entry non dispone di un PDF associato.")
            return

        from app.services.r_analysis import run_r_summary
        output_dir = Path(pdf_path).parent / ".citemind" / Path(pdf_path).stem / "r_analysis"
        try:
            result = run_r_summary(self._adapter._model, entry_id, output_dir)
            QMessageBox.information(
                self,
                "Analisi R completata",
                f"Grafico creato con {result['rows']} elementi confermati:\n{result['chart_path']}",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Analisi R non disponibile", str(exc))


    def _unlink_pdf_row(self, entry_id: int):
        ret = QMessageBox.question(
            self, self._lang.tr("msg_unlink_pdf_title"),
            self._lang.tr("msg_unlink_pdf_text"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self._adapter.unlink_pdf(entry_id)

    def _link_pdf_manual(self, entry_id: int):
        file_path, _ = QFileDialog.getOpenFileName(
            self, self._lang.tr("dialog_pdf_link_title"), "", self._lang.tr("dialog_pdf_files")
        )
        if file_path:
            self._adapter._model.update(entry_id, {"pdf_path": file_path})
            self._adapter.entriesChanged.emit()

    # ── AI Notes ───────────────────────────────────────────────────────────
    def _on_ai_notes_requested(self, entry_id: int):
        """User clicked ⚡ Genera in the AI Notes tab."""
        ollama_url  = AiSettingsDialog.get_ollama_url()
        model_name  = AiSettingsDialog.get_model_name()

        data = self._adapter._model.read_by_id(entry_id)
        pdf_path = data.get("pdf_path", "").strip()
        if not pdf_path:
            QMessageBox.warning(self, self._lang.tr("ai_notes_no_pdf_title"),
                                self._lang.tr("ai_notes_no_pdf_text"))
            return
        if not os.path.exists(pdf_path):
            QMessageBox.warning(self, self._lang.tr("ai_notes_pdf_not_found_title"),
                                f"{self._lang.tr('ai_notes_pdf_not_found_text')}\n{pdf_path}")
            return

        pages_str = data.get("pages", "").strip()

        # Abort any previous running worker
        if self._ai_worker and self._ai_worker.isRunning():
            self._ai_worker.cancel()
            self._ai_worker.wait()

        self._form.set_ai_generating(True)

        self._ai_worker = AiNotesWorker(pdf_path, ollama_url, model_name, pages_str, self)
        self._ai_worker.finished.connect(
            lambda result, eid=entry_id: self._on_ai_finished(eid, result)
        )
        self._ai_worker.error.connect(self._on_ai_error)
        self._ai_worker.start()

    def _save_ai_topics_from_entry(self, entry_id: int, result: dict | None = None):
        if entry_id is None:
            return
        keywords = []
        if isinstance(result, dict):
            keywords = result.get("ai_topics") or []
            key_points = result.get("key_points_en") or result.get("key_points_it") or []
            if key_points:
                from app.graph.keyword_extractor import derive_topics_from_key_points
                derived = derive_topics_from_key_points(key_points)
                if derived:
                    keywords = derived

        if not keywords:
            data = self._adapter._model.read_by_id(entry_id)
            if not data:
                return
            from app.graph.keyword_extractor import build_semantic_keyword_profile

            profile = build_semantic_keyword_profile(data)
            keywords = profile.get("keywords", []) or profile.get("topics", [])
        if not keywords:
            return

        cleaned = []
        seen = set()
        for item in keywords:
            value = str(item).strip()
            if not value:
                continue
            if value.lower() in seen:
                continue
            seen.add(value.lower())
            cleaned.append(value)

        if cleaned:
            self._adapter._model.save_ai_topics(entry_id, cleaned[:5])

    def _on_ai_finished(self, entry_id: int, result: dict):
        import json as _json
        json_str = _json.dumps(result, ensure_ascii=False)
        self._adapter.save_ai_notes(entry_id, json_str)
        self._save_ai_topics_from_entry(entry_id, result)
        self._adapter.select_entry(entry_id)
        self._form.set_ai_notes(result)
        self._refresh_list()

    def _on_ai_error(self, msg: str):
        self._form.set_ai_error(msg)

    def _launch_reference_dag(self, force_refresh: bool = False, references_override: list[dict] | None = None):
        """Second phase: build the chronology graph from extracted bibliography only."""
        from app.widgets.dag_viewer import is_dag_viewer_available

        entry_id = self._adapter.current_id
        if entry_id is None:
            QMessageBox.warning(self, "Bibliography DAG", "Seleziona prima un record.")
            return

        if not is_dag_viewer_available():
            self.statusBar().showMessage("Grafico disabilitato: QtWebEngine non disponibile. Puoi comunque editare manualmente il record.")
            return

        self._dag_dialog = ReferenceDagDialog(self)
        self._dag_dialog.set_busy(True)
        self._dag_dialog.show()

        refs = references_override if references_override is not None else self._adapter._model.get_extracted_bibliography(entry_id)
        if refs and not force_refresh:
            self._form.set_extracted_bibliography(refs)
            self._on_reference_dag_ready(refs)
            return

        entry = self._adapter._model.read_by_id(entry_id)
        pdf_path = (entry or {}).get("pdf_path", "").strip()
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Bibliography DAG", "Questo record non ha un PDF valido collegato e nessuna bibliografia estratta salvata.")
            self._dag_dialog.set_status("Nessun PDF valido e nessuna bibliografia salvata.")
            self._dag_dialog.set_busy(False)
            return

        if self._reference_worker and self._reference_worker.isRunning():
            self._reference_worker.cancel()
            self._reference_worker.wait()

        self._reference_worker = ReferenceExtractionWorker(
            pdf_path=pdf_path,
            ollama_url=AiSettingsDialog.get_ollama_url(),
            model_name=AiSettingsDialog.get_model_name(),
            last_n_pages=5,
            parent=self,
        )
        self._reference_worker.finished.connect(self._on_reference_dag_ready)
        self._reference_worker.error.connect(self._on_reference_dag_error)
        self._reference_worker.start()

    def _on_bibliography_requested(self, entry_id: int):
        entry = self._adapter._model.read_by_id(entry_id)
        pdf_path = (entry or {}).get("pdf_path", "").strip()
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "Bibliography", "Questo record non dispone di un PDF associato.")
            return

        if hasattr(self, "_reference_worker") and self._reference_worker and self._reference_worker.isRunning():
            self._reference_worker.cancel()
            self._reference_worker.wait()

        self._form.set_reference_processing(True, "Estrazione riferimenti dal PDF in corso...")

        from app.workers.reference_worker import ReferenceWorker
        all_entries = self._adapter._model.read_all_full()
        self._reference_worker = ReferenceWorker(pdf_path, all_entries, self)
        self._reference_worker.finished.connect(lambda match_ids: self._on_reference_extraction_finished(entry_id, match_ids))
        self._reference_worker.error.connect(self._on_reference_extraction_error)
        self._reference_worker.start()

    def _on_ocr_requested(self, entry_id: int):
        entry = self._adapter._model.read_by_id(entry_id)
        pdf_path = (entry or {}).get("pdf_path", "").strip()
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, "OCR", "Questo record non dispone di un PDF associato.")
            return

        if self._ocr_worker and self._ocr_worker.isRunning():
            return

        from app.workers.ocr_worker import OcrWorker
        self._form.set_reference_processing(True, "Creazione PDF ricercabile in corso...")
        self._ocr_worker = OcrWorker(pdf_path, self)
        self._ocr_worker.finished.connect(lambda output: self._on_ocr_finished(entry_id, output))
        self._ocr_worker.error.connect(self._on_ocr_error)
        self._ocr_worker.start()

    def _on_ocr_finished(self, entry_id: int, output_path: str):
        self._adapter._model.update(entry_id, {"pdf_path": output_path})
        self._form.set_reference_processing(False, "PDF ricercabile creato.")
        self._refresh_list()
        updated_entry = self._adapter._model.read_by_id(entry_id)
        self._on_entry_selected(updated_entry)

    def _on_ocr_error(self, message: str):
        self._form.set_reference_processing(False, f"OCR non disponibile: {message}")
        QMessageBox.warning(self, "OCR", message)

    def _on_reference_extraction_finished(self, entry_id: int, match_ids: list[int]):
        self._form.set_reference_processing(
            False,
            f"Estrazione completata. Proposte {len(match_ids)} corrispondenze.",
        )
        if not match_ids:
            self._refresh_reference_graph(entry_id)
            return

        all_entries = self._adapter._model.read_all_full()
        by_id = {int(entry["id"]): entry for entry in all_entries}
        candidates = [by_id[match_id] for match_id in match_ids if match_id in by_id]

        from app.dialogs.reference_review_dialog import ReferenceReviewDialog
        dialog = ReferenceReviewDialog(candidates, self)
        if dialog.exec() != ReferenceReviewDialog.Accepted:
            self._form.set_reference_processing(False, "Corrispondenze non confermate.")
            return

        confirmed_ids = dialog.selected_ids()
        current_linked = self._adapter._model.get_linked_references(entry_id)
        new_linked = list(dict.fromkeys(current_linked + confirmed_ids))
        self._adapter._model.save_linked_references(entry_id, new_linked)
        self._refresh_reference_graph(entry_id)

    def _on_reference_extraction_error(self, msg: str):
        self._form.set_reference_processing(False, f"Errore: {msg}")

    def _on_manual_bibliography_edited(self, entry_id: int, actions: list[dict]):
        if not actions:
            return
            
        current_linked = self._adapter._model.get_linked_references(entry_id)
        
        for action in actions:
            act_type = action.get("action")
            text = action.get("text", "")
            if act_type == "add" and text:
                # the combo box has "Title Author Year", we'll just try to find exact match in DB or parse ID.
                # Actually our fuzzy matcher can do this easily:
                from app.services.fuzzy_matcher import FuzzyMatcher
                all_entries = self._adapter._model.read_all_full()
                matcher = FuzzyMatcher(all_entries)
                # Fuzzy match using a threshold of 80 to get the closest DB entry
                matches = matcher.match_blocks([text], threshold=80)
                if matches:
                    current_linked.extend(matches)
            elif act_type == "remove" and text:
                from app.services.fuzzy_matcher import FuzzyMatcher
                all_entries = self._adapter._model.read_all_full()
                matcher = FuzzyMatcher(all_entries)
                matches = matcher.match_blocks([text], threshold=80)
                if matches:
                    current_linked = [ref for ref in current_linked if ref not in matches]
                    
        new_linked = list(set(current_linked))
        self._adapter._model.save_linked_references(entry_id, new_linked)
        self._refresh_reference_graph(entry_id)

    def _refresh_reference_graph(self, entry_id: int):
        linked = self._adapter._model.get_linked_references(entry_id)
        from app.services.graph_generator import generate_reference_graph_json
        graph_json = generate_reference_graph_json(entry_id, linked, self._adapter._model)
        self._last_ref_graph_json = graph_json
        self._form.render_reference_graph(graph_json)

    def _on_reference_graph_requested(self, entry_id: int):
        """Apre il dialog esterno (modale) con il DAG cronologico per la riga corrente."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout
        from app.dialogs.reference_graph_dialog import ReferenceGraphWidget

        if not hasattr(self, "_last_ref_graph_json") or not self._last_ref_graph_json:
            self._refresh_reference_graph(entry_id)

        graph_json = getattr(self, "_last_ref_graph_json", None)
        if not graph_json or not graph_json.get("nodes"):
            QMessageBox.information(self, "Grafico", "Nessuna referenza collegata da visualizzare.")
            return

        # Create a temporary floating dialog for the single entry
        dlg = QDialog(self)
        dlg.setWindowTitle("DAG Bibliografico Locale")
        dlg.resize(1100, 750)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(0, 0, 0, 0)
        widget = ReferenceGraphWidget(self._lang, dlg)
        lay.addWidget(widget)
        widget.load_graph(graph_json)
        self._local_dag_dialog = dlg
        self._local_dag_widget = widget
        dlg.finished.connect(self._clear_local_dag)
        dlg.show()

    def _clear_local_dag(self) -> None:
        """Release references to the closed local DAG dialog."""
        self._local_dag_dialog = None
        self._local_dag_widget = None

    def _on_global_dag_requested(self, checked: bool):
        """Mostra/Nasconde il dock widget con il DAG cronologico globale."""
        self._ref_graph_dock.setVisible(checked)
        if checked:
            self._refresh_global_reference_graph()

    def _refresh_global_reference_graph(self) -> None:
        """Aggiorna il DAG globale mantenendo il dock aperto."""
        from app.services.graph_generator import generate_global_reference_graph_json

        graph_json = generate_global_reference_graph_json(
            self._adapter._model,
            active_id=self._adapter.current_id,
        )
        if not graph_json or not graph_json.get("nodes"):
            self._ref_graph_dock.setVisible(False)
            self._act_global_dag.setChecked(False)
            QMessageBox.information(self, "Grafico Globale", "Nessuna referenza trovata nell'intero database.")
            return
        self._ref_graph_widget.load_graph(graph_json)

    def _on_topics_edited(self, entry_id: int, topics: list[str]):
        if entry_id is None:
            return
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in topics:
            value = str(item).strip()
            if value and value.casefold() not in seen:
                seen.add(value.casefold())
                cleaned.append(value)
        self._adapter._model.save_ai_topics(entry_id, cleaned)
        self._form.set_topics(cleaned)
        self._adapter.entriesChanged.emit()
        self._refresh_list()

    def _on_semantic_keywords_requested(self, entry_id: int):
        if entry_id is None:
            return
        data = self._adapter._model.read_by_id(entry_id)
        if not data:
            return
        from app.graph.keyword_extractor import build_semantic_keyword_profile

        profile = build_semantic_keyword_profile(data)
        keywords = profile.get("keywords", []) or profile.get("topics", [])
        if not keywords:
            QMessageBox.warning(self, "Semantic keywords", "No meaningful keywords could be extracted for this article.")
            return

        self._adapter._model.save_ai_topics(entry_id, keywords)
        self._adapter.select_entry(entry_id)
        self._adapter.entriesChanged.emit()
        self._refresh_list()

    def _on_reset_ai_topics_requested(self, entry_id: int):
        if entry_id is None:
            return
        reply = QMessageBox.question(
            self,
            "Reset AI topics",
            "Clear AI topics for this article?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._adapter._model.clear_ai_topics(entry_id)
            self._adapter.entriesChanged.emit()
            if self._adapter.current_id == entry_id:
                self._adapter.select_entry(entry_id)

    def _on_reset_all_ai_topics_requested(self):
        reply = QMessageBox.question(
            self,
            "Reset all AI topics",
            "Delete AI topics from every article? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._adapter._model.clear_all_ai_topics()
            self._adapter.entriesChanged.emit()
            if self._adapter.current_id is not None:
                self._adapter.select_entry(self._adapter.current_id)

    # ── field signals ──────────────────────────────────────────────────────
    def _on_journal_completed(self, journal_name: str):
        if not journal_name:
            return
        if not self._form.get_publisher().strip():
            pub = self._adapter.get_top_publisher_for_journal(journal_name)
            if pub:
                self._form.set_publisher(pub)

    def _on_field_changed(self, field: str, value: str):
        self._adapter.stage_change(field, value)
        if field == "title":
            self._form.set_title_warning(self._adapter.has_duplicate_title(value))

    def _on_autosaved(self, doc_id: int):
        if not hasattr(self, "_status_mgr"):
            return
        self._status_mgr.set_autosave("  ✓ Salvato  ")
        self._autosave_timer.start()

    def _editor_action(self, action_name: str):
        """Perform cut/copy/paste on the currently focused widget."""
        fw = QApplication.focusWidget()
        if fw and hasattr(fw, action_name):
            getattr(fw, action_name)()

    def _show_topic_dictionary(self):
        from app.dialogs.topic_dictionary_dialog import TopicDictionaryDialog
        dlg = TopicDictionaryDialog(self._adapter._model, self)
        dlg.exec()
        self._adapter.entriesChanged.emit()
        self._refresh_list()

    def _show_licenze(self):
        """Show license information dialog."""
        from PySide6.QtWidgets import QDialog, QTextEdit, QVBoxLayout, QTabWidget
        from PySide6.QtGui import QFont
        
        dlg = QDialog(self)
        dlg.setWindowTitle(self._lang.tr("act_licenze"))
        dlg.setMinimumSize(600, 450)
        
        layout = QVBoxLayout(dlg)
        tabs = QTabWidget()
        
        def _add_license_tab(title, path):
            txt = QTextEdit()
            txt.setReadOnly(True)
            txt.setFont(QFont("Consolas", 10))
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    txt.setPlainText(f.read())
            else:
                txt.setPlainText(f"File not found: {path.name}")
            tabs.addTab(txt, title)
            
        import sys
        if getattr(sys, 'frozen', False):
            licenses_dir = Path(sys._MEIPASS) / "app" / "licenses"
        else:
            licenses_dir = Path(__file__).parent.parent / "licenses"
        _add_license_tab("CiteMind (Apache 2.0)", licenses_dir / "LICENSE_CiteMind.txt")
        _add_license_tab("Ollama (MIT)", licenses_dir / "LICENSE_Ollama.txt")
        
        # Add a tab for 3rd party
        third_party = QTextEdit()
        third_party.setReadOnly(True)
        third_party.setFont(QFont("Segoe UI", 11))
        msg = (
            "CiteMind v1.0\n"
            "Sviluppato per scopi accademici da Mattia Curto.\n\n"
            "Componenti di terze parti:\n"
            "- Icone: Tabler Icons (Licenza MIT)\n"
            "- Framework GUI: PySide6 (Licenza LGPL)\n"
            "- LLM Locale: Ollama\n"
            "- Gestore documenti: python-docx\n"
        )
        third_party.setPlainText(msg)
        tabs.addTab(third_party, "Terze Parti / Info")
        
        layout.addWidget(tabs)
        dlg.exec()

    def _on_stats(self, stats: dict):
        if not hasattr(self, "_status_mgr"):
            return
        total = stats.get("total", 0)
        biblio = stats.get("biblio", 0) or 0
        sito   = stats.get("sito",   0) or 0
        tesi   = stats.get("tesi",   0) or 0
        self._status_mgr.set_stats(
            f"  Totali: <b>{total}</b>  (Bib: {biblio} | Sit: {sito} | Tesi: {tesi})  "
        )

    def closeEvent(self, event):
        if hasattr(self, "_ai_worker") and self._ai_worker and self._ai_worker.isRunning():
            self._ai_worker.cancel()
            self._ai_worker.wait()
        if hasattr(self, "_import_worker") and self._import_worker and self._import_worker.isRunning():
            self._import_worker.cancel()
            self._import_worker.wait()
        self._graph_widget._abort_workers()
        self._adapter._flush_save()
        event.accept()
