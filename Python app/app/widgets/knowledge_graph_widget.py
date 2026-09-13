"""
knowledge_graph_widget.py — Dockable Knowledge Graph panel for CiteMind.

States:
  - docked (right sidebar, default width 380px)
  - collapsed (icon-only strip, 32px)
  - floating (detached window)

Contains:
  - Toolbar: pin, collapse, rebuild, embeddings, AI topics, zoom, filter
  - GraphCanvas: interactive force-directed graph
  - Progress bar for background builds
  - DB persistence for graph state and AI topics
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QDockWidget, QWidget, QVBoxLayout, QHBoxLayout, QToolBar,
    QPushButton, QLabel, QProgressBar, QComboBox, QLineEdit,
    QCheckBox, QSizePolicy, QGraphicsDropShadowEffect, QFrame,
    QToolButton, QMenu
)
from PySide6.QtCore import Qt, QTimer, Signal, QSize, QSettings
from PySide6.QtGui import QAction, QColor

from app.theme import icon, get_global_theme
from app.i18n import LanguageManager
from app.widgets.graph_canvas import GraphCanvas
from app.graph.graph_model import GraphModel
from app.graph.graph_cache import GraphCache
from app.graph.graph_worker import GraphBuildWorker, EmbeddingWorker, TopicExtractionWorker
from app.dialogs.ai_settings_dialog import AiSettingsDialog


class KnowledgeGraphWidget(QDockWidget):
    """
    Dockable interactive knowledge graph panel.

    Signals
    -------
    documentRequested : int
        Emitted with entry_id when a document node is clicked.
    filterRequested : str
        Emitted with search text when a keyword/author node is clicked.
    """

    documentRequested = Signal(int)
    filterRequested   = Signal(str)

    def __init__(self, lang: LanguageManager, parent=None):
        super().__init__(lang.tr("graph_panel_title"), parent)
        self._lang = lang
        self._db_path: Path | None = None
        self._model = None                    # EntryModel ref (set via set_model)
        self._graph_json: dict | None = None
        self._build_worker: GraphBuildWorker | None = None
        self._embed_worker: EmbeddingWorker | None = None
        self._topic_worker: TopicExtractionWorker | None = None
        self._collapsed = False
        self._entries: list[dict] = []
        self._current_mode: str = ""          # "tfidf", "ai_topics", "semantic"

        # Debounce rebuild
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(3000)
        self._rebuild_timer.timeout.connect(self._do_rebuild)

        self._setup_ui()
        self._apply_dock_style()

        # Dock widget features
        self.setFeatures(
            QDockWidget.DockWidgetMovable
            | QDockWidget.DockWidgetFloatable
            | QDockWidget.DockWidgetClosable
        )
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self.setMinimumWidth(250)

    # ── UI Setup ──────────────────────────────────────────────────────────
    def _setup_ui(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────
        header = QFrame()
        header.setObjectName("graphHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 8, 12, 8)
        header_layout.setSpacing(8)

        title_icon = QPushButton()
        title_icon.setIcon(icon("graph"))
        title_icon.setIconSize(QSize(18, 18))
        title_icon.setFixedSize(24, 24)
        title_icon.setFlat(True)
        header_layout.addWidget(title_icon)

        title_lbl = QLabel(self._lang.tr("graph_panel_title"))
        title_lbl.setObjectName("graphPanelTitle")
        header_layout.addWidget(title_lbl)
        header_layout.addStretch()

        # Collapse button
        self._btn_collapse = QPushButton()
        self._btn_collapse.setIcon(icon("chevron-right"))
        self._btn_collapse.setIconSize(QSize(16, 16))
        self._btn_collapse.setFixedSize(28, 28)
        self._btn_collapse.setToolTip(self._lang.tr("graph_btn_collapse"))
        self._btn_collapse.setCursor(Qt.PointingHandCursor)
        self._btn_collapse.clicked.connect(self._toggle_collapse)
        header_layout.addWidget(self._btn_collapse)

        layout.addWidget(header)

        # ── Collapsible body ──────────────────────────────────────────────
        self._body = QWidget()
        body_layout = QVBoxLayout(self._body)
        body_layout.setContentsMargins(8, 4, 8, 8)
        body_layout.setSpacing(6)

        # ── Toolbar row 1 — Build actions ─────────────────────────────────
        tb_row = QHBoxLayout()
        tb_row.setSpacing(4)

        self._btn_rebuild = QPushButton(self._lang.tr("graph_btn_rebuild"))
        self._btn_rebuild.setIcon(icon("refresh"))
        self._btn_rebuild.setObjectName("btnPrimary")
        self._btn_rebuild.setCursor(Qt.PointingHandCursor)
        self._btn_rebuild.setToolTip(self._lang.tr("graph_btn_rebuild_tip"))
        self._btn_rebuild.clicked.connect(self._do_rebuild)
        tb_row.addWidget(self._btn_rebuild)

        self._btn_embeddings = QPushButton(self._lang.tr("graph_btn_embeddings"))
        self._btn_embeddings.setIcon(icon("brain"))
        self._btn_embeddings.setCursor(Qt.PointingHandCursor)
        self._btn_embeddings.setToolTip(self._lang.tr("graph_btn_embeddings_tip"))
        self._btn_embeddings.clicked.connect(self._do_embeddings)
        tb_row.addWidget(self._btn_embeddings)

        self._btn_ai_topics = QPushButton(self._lang.tr("graph_btn_ai_topics"))
        self._btn_ai_topics.setIcon(icon("ai"))
        self._btn_ai_topics.setCursor(Qt.PointingHandCursor)
        self._btn_ai_topics.setToolTip(self._lang.tr("graph_btn_ai_topics_tip"))
        self._btn_ai_topics.clicked.connect(self._do_topics)
        tb_row.addWidget(self._btn_ai_topics)

        body_layout.addLayout(tb_row)

        keyword_limit_row = QHBoxLayout()
        keyword_limit_row.setSpacing(6)
        keyword_limit_row.addWidget(QLabel("Keyword cap"))
        self._keyword_limit_combo = QComboBox()
        self._keyword_limit_combo.addItems(["10", "25", "50", "75", "100", "150", "250"])
        self._keyword_limit_combo.setCurrentText(self._get_keyword_limit_setting())
        self._keyword_limit_combo.currentTextChanged.connect(self._save_keyword_limit_setting)
        keyword_limit_row.addWidget(self._keyword_limit_combo)
        keyword_limit_row.addStretch()
        body_layout.addLayout(keyword_limit_row)

        # ── Toolbar row 2 — Zoom + Fit ────────────────────────────────────
        zoom_row = QHBoxLayout()
        zoom_row.setSpacing(4)

        self._btn_zoom_in = QPushButton()
        self._btn_zoom_in.setIcon(icon("zoom-in"))
        self._btn_zoom_in.setIconSize(QSize(18, 18))
        self._btn_zoom_in.setFixedSize(28, 28)
        self._btn_zoom_in.setToolTip(self._lang.tr("graph_btn_zoom_in"))
        self._btn_zoom_in.setCursor(Qt.PointingHandCursor)
        self._btn_zoom_in.clicked.connect(lambda: self._canvas.zoom_step(1.3))
        zoom_row.addWidget(self._btn_zoom_in)

        self._btn_zoom_out = QPushButton()
        self._btn_zoom_out.setIcon(icon("zoom-out"))
        self._btn_zoom_out.setIconSize(QSize(18, 18))
        self._btn_zoom_out.setFixedSize(28, 28)
        self._btn_zoom_out.setToolTip(self._lang.tr("graph_btn_zoom_out"))
        self._btn_zoom_out.setCursor(Qt.PointingHandCursor)
        self._btn_zoom_out.clicked.connect(lambda: self._canvas.zoom_step(1 / 1.3))
        zoom_row.addWidget(self._btn_zoom_out)

        self._btn_zoom_reset = QPushButton()
        self._btn_zoom_reset.setIcon(icon("zoom-reset"))
        self._btn_zoom_reset.setIconSize(QSize(18, 18))
        self._btn_zoom_reset.setFixedSize(28, 28)
        self._btn_zoom_reset.setToolTip(self._lang.tr("graph_btn_zoom_reset"))
        self._btn_zoom_reset.setCursor(Qt.PointingHandCursor)
        self._btn_zoom_reset.clicked.connect(lambda: self._canvas.zoom_reset())
        zoom_row.addWidget(self._btn_zoom_reset)

        self._btn_fit = QPushButton()
        self._btn_fit.setIcon(icon("arrows-maximize"))
        self._btn_fit.setIconSize(QSize(18, 18))
        self._btn_fit.setFixedSize(28, 28)
        self._btn_fit.setToolTip(self._lang.tr("graph_btn_fit"))
        self._btn_fit.setCursor(Qt.PointingHandCursor)
        self._btn_fit.clicked.connect(lambda: self._canvas.fit_in_view())
        zoom_row.addWidget(self._btn_fit)

        # Cluster overlay toggle
        self._btn_clusters = QPushButton()
        self._btn_clusters.setIcon(icon("topology-ring-3"))
        self._btn_clusters.setIconSize(QSize(18, 18))
        self._btn_clusters.setFixedSize(28, 28)
        self._btn_clusters.setToolTip(self._lang.tr("graph_btn_clusters"))
        self._btn_clusters.setCursor(Qt.PointingHandCursor)
        self._btn_clusters.setCheckable(True)
        self._btn_clusters.toggled.connect(self._on_cluster_toggle)
        zoom_row.addWidget(self._btn_clusters)

        # Labels mode selector
        self._btn_labels = QToolButton()
        self._btn_labels.setIcon(icon("tag"))
        self._btn_labels.setIconSize(QSize(18, 18))
        self._btn_labels.setFixedSize(28, 28)
        self._btn_labels.setToolTip(self._lang.tr("graph_btn_labels"))
        self._btn_labels.setCursor(Qt.PointingHandCursor)
        self._btn_labels.setPopupMode(QToolButton.InstantPopup)
        self._btn_labels.setStyleSheet(
            "QToolButton::menu-indicator { image: none; }"
        )

        self._label_menu = QMenu(self._btn_labels)
        self._label_mode_group: list[QAction] = []

        for mode_key, tr_key in [
            ("none", "graph_label_none"),
            ("documents", "graph_label_docs"),
            ("keywords", "graph_label_keywords"),
            ("all", "graph_label_all"),
        ]:
            act = self._label_menu.addAction(self._lang.tr(tr_key))
            act.setCheckable(True)
            act.setChecked(mode_key == "none")
            act.setData(mode_key)
            act.triggered.connect(lambda checked, m=mode_key: self._on_label_mode(m))
            self._label_mode_group.append(act)

        self._btn_labels.setMenu(self._label_menu)
        zoom_row.addWidget(self._btn_labels)

        # Export button
        self._btn_export = QPushButton()
        self._btn_export.setIcon(icon("download"))
        self._btn_export.setIconSize(QSize(18, 18))
        self._btn_export.setFixedSize(28, 28)
        self._btn_export.setToolTip(self._lang.tr("graph_btn_export"))
        self._btn_export.setCursor(Qt.PointingHandCursor)
        self._btn_export.clicked.connect(self._do_export)
        zoom_row.addWidget(self._btn_export)

        zoom_row.addStretch()

        # Node type filter multi-select
        self._node_filter_btn = QToolButton()
        self._node_filter_btn.setText(self._lang.tr("graph_filter_all") + " ▼")
        self._node_filter_btn.setPopupMode(QToolButton.InstantPopup)
        self._node_filter_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self._node_filter_btn.setStyleSheet("QToolButton::menu-indicator { image: none; } padding-right: 5px;")
        
        self._node_filter_menu = QMenu(self._node_filter_btn)
        
        self._act_filter_docs = self._node_filter_menu.addAction(self._lang.tr("graph_filter_docs"))
        self._act_filter_docs.setCheckable(True)
        self._act_filter_docs.setChecked(True)
        self._act_filter_docs.toggled.connect(self._on_node_filter_changed)
        
        self._act_filter_keywords = self._node_filter_menu.addAction(self._lang.tr("graph_filter_keywords"))
        self._act_filter_keywords.setCheckable(True)
        self._act_filter_keywords.setChecked(True)
        self._act_filter_keywords.toggled.connect(self._on_node_filter_changed)
        
        self._node_filter_btn.setMenu(self._node_filter_menu)
        zoom_row.addWidget(self._node_filter_btn)

        # Layout selector
        self._layout_combo = QComboBox()
        self._layout_combo.addItems([
            self._lang.tr("graph_layout_force"),
            self._lang.tr("graph_layout_circular"),
            self._lang.tr("graph_layout_radial")
        ])
        self._layout_combo.currentIndexChanged.connect(self._on_layout_changed)
        zoom_row.addWidget(self._layout_combo)

        body_layout.addLayout(zoom_row)

        # ── Filter row ────────────────────────────────────────────────────
        filter_row = QHBoxLayout()
        filter_row.setSpacing(4)

        self._filter_search = QLineEdit()
        self._filter_search.setPlaceholderText(self._lang.tr("graph_filter_keyword"))
        self._filter_search.setObjectName("searchBar")
        self._filter_search.textChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self._filter_search)

        body_layout.addLayout(filter_row)

        # ── Edge type toggles ─────────────────────────────────────────────
        edge_row = QHBoxLayout()
        edge_row.setSpacing(8)

        self._chk_kw_overlap = QCheckBox(self._lang.tr("graph_edge_keyword"))
        self._chk_kw_overlap.setChecked(True)
        self._chk_kw_overlap.stateChanged.connect(self._on_edge_filter_changed)

        self._chk_semantic = QCheckBox(self._lang.tr("graph_edge_semantic"))
        self._chk_semantic.setChecked(True)
        self._chk_semantic.stateChanged.connect(self._on_edge_filter_changed)

        edge_row.addWidget(self._chk_kw_overlap)
        edge_row.addWidget(self._chk_semantic)
        edge_row.addStretch()
        body_layout.addLayout(edge_row)

        # ── Progress bar ──────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setFixedHeight(4)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._progress.setObjectName("graphProgress")
        body_layout.addWidget(self._progress)

        # ── Status label ──────────────────────────────────────────────────
        self._status_lbl = QLabel(self._lang.tr("graph_status_empty"))
        self._status_lbl.setObjectName("sectionTitle")
        self._status_lbl.setAlignment(Qt.AlignCenter)
        body_layout.addWidget(self._status_lbl)

        # ── Canvas ────────────────────────────────────────────────────────
        dark = get_global_theme() == "dark"
        self._canvas = GraphCanvas(dark_mode=dark, parent=self)
        self._canvas.nodeClicked.connect(self._on_node_clicked)
        self._canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        body_layout.addWidget(self._canvas, 1)

        layout.addWidget(self._body, 1)
        self.setWidget(container)
        
        # Apply initial filter state after canvas is ready
        self._on_node_filter_changed()

    # ── Styling ───────────────────────────────────────────────────────────
    def _apply_dock_style(self):
        dark = get_global_theme() == "dark"
        if dark:
            self.setStyleSheet("""
                QDockWidget {
                    font-size: 0px;  /* hide default title */
                }
                QDockWidget::title {
                    background: #1a1b26;
                    padding: 0px;
                    height: 0px;
                }
                #graphHeader {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #1e1040, stop:1 #1a1b26);
                    border-bottom: 1px solid #2a2b38;
                }
                #graphPanelTitle {
                    color: #a78bfa;
                    font-size: 13px;
                    font-weight: 600;
                    background: transparent;
                }
                #graphProgress {
                    background: #2a2b38;
                    border: none;
                    border-radius: 2px;
                }
                #graphProgress::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #7c3aed, stop:1 #a78bfa);
                    border-radius: 2px;
                }
                QCheckBox { color: #a0a0c0; font-size: 11px; }
                QCheckBox::indicator { width: 14px; height: 14px; }
            """)
        else:
            self.setStyleSheet("""
                QDockWidget {
                    font-size: 0px;
                }
                QDockWidget::title {
                    background: #eaeaf0;
                    padding: 0px;
                    height: 0px;
                }
                #graphHeader {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #e8e0ff, stop:1 #eaeaf0);
                    border-bottom: 1px solid #d4d4dc;
                }
                #graphPanelTitle {
                    color: #6d28d9;
                    font-size: 13px;
                    font-weight: 600;
                    background: transparent;
                }
                #graphProgress {
                    background: #d4d4dc;
                    border: none;
                    border-radius: 2px;
                }
                #graphProgress::chunk {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                        stop:0 #7c3aed, stop:1 #a78bfa);
                    border-radius: 2px;
                }
                QCheckBox { color: #555580; font-size: 11px; }
                QCheckBox::indicator { width: 14px; height: 14px; }
            """)

    # ── Public interface (called by MainWindow) ───────────────────────────
    def _get_keyword_limit_setting(self) -> str:
        settings = QSettings("CiteMind", "CiteMind")
        value = int(settings.value("graph_keyword_limit", 50))
        choices = [10, 25, 50, 75, 100, 150, 250]
        if value not in choices:
            value = 50
        return str(value)

    def _save_keyword_limit_setting(self, value: str) -> None:
        try:
            settings = QSettings("CiteMind", "CiteMind")
            settings.setValue("graph_keyword_limit", int(value))
        except Exception:
            pass

    def _get_keyword_limit(self) -> int:
        try:
            return max(1, int(self._keyword_limit_combo.currentText()))
        except Exception:
            return 50

    def set_data(self, entries: list[dict], db_path: Path) -> None:
        """Provide current entries and DB path for graph building."""
        self._entries = entries
        self._db_path = db_path

    def set_model(self, model) -> None:
        """Store a reference to EntryModel for DB persistence."""
        self._model = model

    def schedule_rebuild(self) -> None:
        """Debounced graph rebuild (3s delay after last change)."""
        self._rebuild_timer.start()

    def set_dark_mode(self, dark: bool) -> None:
        """Update theme across all child widgets."""
        self._canvas.set_dark_mode(dark)
        self._apply_dock_style()

    def try_load_cache(self) -> bool:
        """Attempt to load graph from DB, then fall back to sidecar cache."""
        # 1. Try DB persistence
        if self._model is not None:
            result = self._model.load_graph()
            if result:
                graph_json_str, built_at, mode = result
                try:
                    self._graph_json = json.loads(graph_json_str)
                    self._current_mode = mode
                    self._canvas.load_graph(self._graph_json)
                    gm = GraphModel.from_json(self._graph_json)
                    n, e = gm.node_count, gm.edge_count
                    self._status_lbl.setText(
                        self._lang.tr("graph_status_loaded").format(nodes=n, edges=e)
                    )
                    return True
                except Exception:
                    pass

        # 2. Fall back to sidecar JSON cache
        if self._db_path is None:
            return False
        cache = GraphCache(self._db_path)
        gm = cache.load()
        if gm is not None:
            self._graph_json = gm.to_json()
            self._canvas.load_graph(self._graph_json)
            n = gm.node_count
            e = gm.edge_count
            self._status_lbl.setText(
                self._lang.tr("graph_status_loaded").format(nodes=n, edges=e)
            )
            return True
        return False

    def _persist_graph(self, graph_json: dict, mode: str) -> None:
        """Save graph to DB if model available."""
        if self._model is not None:
            try:
                self._model.save_graph(json.dumps(graph_json, ensure_ascii=False), mode)
            except Exception:
                pass  # non-critical

    def _persist_ai_topics(self, graph_json: dict) -> None:
        """Save AI-extracted topics into each entry's ai_topics field."""
        if self._model is None:
            return
        nodes_list = graph_json.get("nodes", [])
        nodes = {n.get("id"): n for n in nodes_list if "id" in n}
        
        for nid, ndata in nodes.items():
            if ndata.get("node_type") != "document":
                continue
            try:
                entry_id = int(nid.split("_", 1)[1])
            except (ValueError, IndexError):
                continue
            # Collect topic labels connected to this doc node
            topics = []
            for edge in graph_json.get("edges", []):
                src, tgt = edge.get("source"), edge.get("target")
                partner = tgt if src == nid else (src if tgt == nid else None)
                if partner and partner in nodes and nodes[partner].get("node_type") == "keyword":
                    topics.append(nodes[partner].get("label", partner))
            if topics:
                try:
                    self._model.save_ai_topics(entry_id, topics)
                except Exception:
                    pass

    # ── Build / Embed actions ─────────────────────────────────────────────
    def _do_rebuild(self):
        """Trigger a full graph rebuild in background."""
        if not self._entries or self._db_path is None:
            self._status_lbl.setText(self._lang.tr("graph_status_no_data"))
            return

        self._abort_workers()

        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._btn_rebuild.setEnabled(False)
        self._status_lbl.setText(self._lang.tr("graph_status_building"))

        self._build_worker = GraphBuildWorker(
            self._entries,
            self._db_path,
            self,
            keyword_limit=self._get_keyword_limit(),
        )
        self._build_worker.progress.connect(self._on_build_progress)
        self._build_worker.finished.connect(self._on_build_finished)
        self._build_worker.error.connect(self._on_build_error)
        self._build_worker.start()

    def _do_embeddings(self):
        """Trigger Ollama embedding computation for semantic edges."""
        if self._graph_json is None:
            self._status_lbl.setText(self._lang.tr("graph_status_build_first"))
            return

        ollama_url = AiSettingsDialog.get_ollama_url()
        model_name = AiSettingsDialog.get_semantic_model_name()

        self._abort_workers()

        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._btn_embeddings.setEnabled(False)
        self._status_lbl.setText(self._lang.tr("graph_status_embedding"))

        self._embed_worker = EmbeddingWorker(
            self._entries, self._graph_json,
            ollama_url, model_name, self._db_path, self,
        )
        self._embed_worker.progress.connect(self._on_build_progress)
        self._embed_worker.finished.connect(self._on_embed_finished)
        self._embed_worker.error.connect(self._on_build_error)
        self._embed_worker.start()

    def _do_topics(self):
        """Use Ollama to extract thematic topics and rebuild the graph."""
        if not self._entries or self._db_path is None:
            self._status_lbl.setText(self._lang.tr("graph_status_no_data"))
            return

        ollama_url = AiSettingsDialog.get_ollama_url()
        model_name = AiSettingsDialog.get_semantic_model_name()

        self._abort_workers()

        self._progress.setVisible(True)
        self._progress.setValue(0)
        self._btn_ai_topics.setEnabled(False)
        self._btn_rebuild.setEnabled(False)
        self._status_lbl.setText(self._lang.tr("graph_status_topics"))

        self._topic_worker = TopicExtractionWorker(
            self._entries,
            ollama_url,
            model_name,
            self._db_path,
            self,
            keyword_limit=self._get_keyword_limit(),
        )
        self._topic_worker.progress.connect(self._on_build_progress)
        self._topic_worker.finished.connect(self._on_topics_finished)
        self._topic_worker.error.connect(self._on_build_error)
        self._topic_worker.start()

    def _abort_workers(self):
        for worker in (self._build_worker, self._embed_worker, self._topic_worker):
            if worker and worker.isRunning():
                worker.cancel()
                worker.wait()
        self._build_worker = None
        self._embed_worker = None
        self._topic_worker = None

    # ── Worker callbacks ──────────────────────────────────────────────────
    def _on_build_progress(self, pct: int):
        self._progress.setValue(pct)

    def _on_build_finished(self, graph_json: dict):
        self._graph_json = graph_json
        self._current_mode = "tfidf"
        self._canvas.load_graph(graph_json)
        gm = GraphModel.from_json(graph_json)
        n, e = gm.node_count, gm.edge_count
        self._status_lbl.setText(
            self._lang.tr("graph_status_loaded").format(nodes=n, edges=e)
        )
        self._progress.setVisible(False)
        self._btn_rebuild.setEnabled(True)
        self._persist_graph(graph_json, "tfidf")

    def _on_embed_finished(self, graph_json: dict):
        self._graph_json = graph_json
        self._current_mode = "semantic"
        self._canvas.load_graph(graph_json)
        gm = GraphModel.from_json(graph_json)
        n, e = gm.node_count, gm.edge_count
        self._status_lbl.setText(
            self._lang.tr("graph_status_semantic_done").format(nodes=n, edges=e)
        )
        self._progress.setVisible(False)
        self._btn_embeddings.setEnabled(True)
        self._persist_graph(graph_json, "semantic")

    def _on_topics_finished(self, graph_json: dict):
        self._graph_json = graph_json
        self._current_mode = "ai_topics"
        self._canvas.load_graph(graph_json)
        gm = GraphModel.from_json(graph_json)
        n, e = gm.node_count, gm.edge_count
        self._status_lbl.setText(
            self._lang.tr("graph_status_topics_done").format(nodes=n, edges=e)
        )
        self._progress.setVisible(False)
        self._btn_ai_topics.setEnabled(True)
        self._btn_rebuild.setEnabled(True)
        self._persist_graph(graph_json, "ai_topics")
        self._persist_ai_topics(graph_json)

    def _on_build_error(self, msg: str):
        self._status_lbl.setText(f"{msg[:100]}")
        self._progress.setVisible(False)
        self._btn_rebuild.setEnabled(True)
        self._btn_embeddings.setEnabled(True)
        self._btn_ai_topics.setEnabled(True)

    # ── Node click ────────────────────────────────────────────────────────
    def _on_node_clicked(self, node_id: str, node_type: str):
        if node_type == "document":
            # Extract entry_id from "doc_42"
            try:
                entry_id = int(node_id.split("_", 1)[1])
                self.documentRequested.emit(entry_id)
            except (ValueError, IndexError):
                pass
        elif node_type in ("keyword"):
            # Extract label for filtering
            node_data = self._canvas._node_items.get(node_id)
            if node_data:
                self.filterRequested.emit(node_data.node_label)

    # ── Collapse ──────────────────────────────────────────────────────────
    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._body.setVisible(not self._collapsed)
        if self._collapsed:
            self._btn_collapse.setIcon(icon("chevron-left"))
            self.setFixedWidth(48)
        else:
            self._btn_collapse.setIcon(icon("chevron-right"))
            self.setMinimumWidth(320)
            self.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX

    # ── Filter ────────────────────────────────────────────────────────────
    def _on_filter_changed(self, text: str):
        """Dim nodes that don't match the filter text."""
        text = text.strip().lower()
        if not text:
            self._canvas.clear_highlight()
            return
        # Find matching nodes
        matching: set[str] = set()
        for nid, item in self._canvas._node_items.items():
            label = item.node_label.lower()
            data_title = item.node_data.get("title", "").lower()
            data_authors = item.node_data.get("authors", "").lower()
            if text in label or text in data_title or text in data_authors:
                matching.add(nid)
                # Also show neighbors
                if self._canvas._graph_model:
                    for nb in self._canvas._graph_model.get_neighbors(nid):
                        matching.add(nb)

        for nid, item in self._canvas._node_items.items():
            item.set_dimmed(nid not in matching)

    def _on_edge_filter_changed(self):
        """Show/hide edges based on checkbox state."""
        visible_edge_types: set[str] = {"contains_keyword"}
        if self._chk_kw_overlap.isChecked():
            visible_edge_types.add("keyword_overlap")
        if self._chk_semantic.isChecked():
            visible_edge_types.add("semantic_similarity")

        self._canvas.filter_by_type(edge_types=visible_edge_types)

    def _on_node_filter_changed(self):
        """Filter visible nodes by checked types."""
        allowed_types: set[str] = set()
        if self._act_filter_docs.isChecked():
            allowed_types.add("document")
        if self._act_filter_keywords.isChecked():
            allowed_types.add("keyword")

        self._canvas.filter_by_type(node_types=allowed_types)
        
        # Update button text
        names = []
        if self._act_filter_docs.isChecked(): names.append(self._lang.tr("graph_filter_docs"))
        if self._act_filter_keywords.isChecked(): names.append(self._lang.tr("graph_filter_keywords"))
        
        label = ", ".join(names) if names else "-"
        if len(label) > 15:
            label = label[:12] + "..."
        self._node_filter_btn.setText(label + " ▼")

    def _on_layout_changed(self, idx: int):
        if idx == 0:
            self._canvas.apply_layout_algorithm("force")
        elif idx == 1:
            self._canvas.apply_layout_algorithm("circular")
        elif idx == 2:
            self._canvas.apply_layout_algorithm("radial")

    # ── Cluster overlay ───────────────────────────────────────────────────
    def _on_cluster_toggle(self, checked: bool):
        self._canvas.set_cluster_overlay(checked)

    def _on_label_mode(self, mode: str):
        # Radio-button behavior: uncheck all, check selected
        for act in self._label_mode_group:
            act.setChecked(act.data() == mode)
        self._canvas.set_label_mode(mode)

    # ── Export ────────────────────────────────────────────────────────────
    def _do_export(self):
        from app.dialogs.graph_export_dialog import GraphExportDialog
        dlg = GraphExportDialog(self._canvas, self._lang, self)
        dlg.exec()

    # ── Cleanup ───────────────────────────────────────────────────────────
    def closeEvent(self, event):
        self._abort_workers()
        super().closeEvent(event)
