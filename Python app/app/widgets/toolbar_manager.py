"""
toolbar_manager.py — Extracts the main toolbar setup from main_window.py
"""
from PySide6.QtWidgets import QToolBar, QLineEdit, QComboBox, QLabel, QWidget, QSizePolicy
from PySide6.QtGui import QAction
from PySide6.QtCore import QSize
from app.theme import icon, ThemeManager, get_global_theme

class ToolbarManager:
    """Manages the creation and configuration of the main toolbar."""

    def __init__(self, parent_window, lang_mgr, callbacks):
        self._window = parent_window
        self._lang = lang_mgr
        self._callbacks = callbacks
        self.toolbar = QToolBar("Main", self._window)
        self.toolbar.setIconSize(QSize(20, 20))
        self.toolbar.setMovable(False)
        self._window.addToolBar(self.toolbar)
        self._build()

    def _build(self):
        tb = self.toolbar
        lang = self._lang

        self.act_add_bib   = QAction(icon("book-upload"), lang.tr("tb_add_bib"), self._window)
        self.act_add_sit   = QAction(icon("world-www"), lang.tr("tb_add_sit"), self._window)
        self.act_add_tesi  = QAction(icon("file-certificate"), lang.tr("tb_add_tesi"), self._window)
        self.act_delete    = QAction(icon("trash"), lang.tr("tb_delete"), self._window)
        self.act_export    = QAction(icon("file-export"), lang.tr("tb_export"), self._window)
        self.act_pdf_mgr   = QAction(icon("folder-plus"), lang.tr("tb_pdf_mgr"), self._window)
        self.act_theme     = QAction(icon(ThemeManager.THEME_ICONS.get(get_global_theme(), "sun")), lang.tr("tb_theme"), self._window)
        self.act_support   = QAction(icon("coffee"), lang.tr("tb_support"), self._window)
        self.act_topic_dictionary = QAction(icon("book"), "Topic Dictionary", self._window)
        
        self.act_delete.setEnabled(False)

        # Connect callbacks
        self.act_add_bib.triggered.connect(lambda: self._callbacks["new_entry"]("bibliography"))
        self.act_add_sit.triggered.connect(lambda: self._callbacks["new_entry"]("sitography"))
        self.act_add_tesi.triggered.connect(lambda: self._callbacks["new_entry"]("tesi"))
        self.act_delete.triggered.connect(self._callbacks["delete_current"])
        self.act_export.triggered.connect(self._callbacks["open_export"])
        self.act_pdf_mgr.triggered.connect(self._callbacks["open_pdf_manager"])
        self.act_theme.triggered.connect(self._callbacks["toggle_theme"])
        self.act_support.triggered.connect(self._callbacks["open_support"])
        self.act_topic_dictionary.triggered.connect(self._callbacks["show_topic_dictionary"])

        tb.addAction(self.act_add_bib)
        tb.addAction(self.act_add_sit)
        tb.addAction(self.act_add_tesi)
        tb.addSeparator()
        tb.addAction(self.act_delete)
        tb.addSeparator()
        tb.addAction(self.act_export)
        tb.addAction(self.act_pdf_mgr)
        tb.addSeparator()
        tb.addAction(self.act_topic_dictionary)
        tb.addSeparator()

        # Search bar
        tb.addWidget(QLabel("  "))
        self.search = QLineEdit()
        self.search.setObjectName("searchBar")
        self.search.setPlaceholderText(f"🔍  {lang.tr('search_placeholder')}")
        self.search.textChanged.connect(self._callbacks["refresh_list"])
        tb.addWidget(self.search)

        tb.addSeparator()
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([
            lang.tr("filter_all"), 
            lang.tr("filter_bib"), 
            lang.tr("filter_sit"), 
            lang.tr("filter_tesi")
        ])
        self.filter_combo.currentIndexChanged.connect(self._callbacks["refresh_list"])
        tb.addWidget(self.filter_combo)

        # Thematic Sidebar toggle
        self.act_sidebar = QAction(icon("filter"), lang.tr("tb_sidebar"), self._window)
        self.act_sidebar.setToolTip(lang.tr("tb_sidebar_tip"))
        self.act_sidebar.setCheckable(True)
        self.act_sidebar.triggered.connect(self._callbacks["toggle_sidebar"])
        tb.addAction(self.act_sidebar)

        # Knowledge Graph toggle
        self.act_graph = QAction(icon("graph"), lang.tr("tb_graph"), self._window)
        self.act_graph.setToolTip(lang.tr("tb_graph_tip"))
        self.act_graph.setCheckable(True)
        self.act_graph.triggered.connect(self._callbacks["toggle_graph"])
        tb.addAction(self.act_graph)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)
        tb.addAction(self.act_support)
        tb.addAction(self.act_theme)
