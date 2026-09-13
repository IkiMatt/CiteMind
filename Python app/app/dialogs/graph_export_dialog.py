"""
graph_export_dialog.py — Export dialog for Knowledge Graph.

Advanced tool for total customization of the exported graph, including
dimensions, format, quality, labels, layers, and a live dynamic legend.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QSlider, QComboBox, QCheckBox, QPushButton,
    QFileDialog, QMessageBox, QSpinBox, QTabWidget, QWidget,
    QRadioButton, QButtonGroup, QFontComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QDoubleSpinBox,
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QSplitter
)
from PySide6.QtCore import Qt, QRectF, QSize, QTimer
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QBrush, QPen, QPixmap, QWheelEvent

from app.i18n import LanguageManager


class PreviewView(QGraphicsView):
    """Custom view for panning and zooming the preview."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def wheelEvent(self, event: QWheelEvent):
        factor = 1.15
        if event.angleDelta().y() < 0:
            factor = 1.0 / factor
        self.scale(factor, factor)


class GraphExportDialog(QDialog):
    """Modal dialog for exporting the graph canvas with advanced customization."""

    def __init__(self, canvas, lang: LanguageManager, parent=None):
        super().__init__(parent)
        self._canvas = canvas
        self._lang = lang
        self._graph_model = canvas._graph_model
        
        self.setWindowTitle(lang.tr("graph_export_title"))
        self.resize(1100, 750)
        
        # Original scene dimensions for aspect ratio
        scene = self._canvas.scene()
        self._base_rect = scene.itemsBoundingRect()
        self._base_rect.adjust(-30, -30, 30, 30)
        self._aspect_ratio = self._base_rect.width() / self._base_rect.height() if self._base_rect.height() > 0 else 1.0

        # Debounce timer for live preview
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(300)
        self._preview_timer.timeout.connect(self._generate_preview)
        
        self._preview_item = None

        self._build_ui()
        
        # Initial preview generation
        QTimer.singleShot(100, self._generate_preview)

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        
        splitter = QSplitter(Qt.Horizontal)
        
        # ── Left Pane: Settings ───────────────────────────────────────────
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tabs = QTabWidget()
        self._create_general_tab()
        self._create_labels_tab()
        self._create_layers_tab()
        self._create_legend_tab()
        left_layout.addWidget(self.tabs)
        
        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_cancel = QPushButton(self._lang.tr("graph_export_cancel"))
        self._btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_cancel)

        self._btn_export = QPushButton(self._lang.tr("graph_export_save"))
        self._btn_export.setObjectName("btnPrimary")
        self._btn_export.clicked.connect(self._do_export)
        btn_row.addWidget(self._btn_export)
        left_layout.addLayout(btn_row)
        
        splitter.addWidget(left_widget)
        
        # ── Right Pane: Preview ───────────────────────────────────────────
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        
        toolbar = QHBoxLayout()
        lbl_preview = QLabel("<b>Live Preview</b>")
        toolbar.addWidget(lbl_preview)
        toolbar.addStretch()
        
        btn_zoom_in = QPushButton("Zoom In")
        btn_zoom_in.clicked.connect(lambda: self._preview_view.scale(1.2, 1.2))
        btn_zoom_out = QPushButton("Zoom Out")
        btn_zoom_out.clicked.connect(lambda: self._preview_view.scale(1.0/1.2, 1.0/1.2))
        btn_fit = QPushButton("Fit to View")
        btn_fit.clicked.connect(self._fit_preview)
        
        toolbar.addWidget(btn_zoom_in)
        toolbar.addWidget(btn_zoom_out)
        toolbar.addWidget(btn_fit)
        right_layout.addLayout(toolbar)
        
        self._preview_scene = QGraphicsScene()
        self._preview_view = PreviewView(self._preview_scene)
        # Checkerboard background for transparent previews
        bg_pixmap = QPixmap(20, 20)
        bg_pixmap.fill(QColor(220, 220, 220))
        painter = QPainter(bg_pixmap)
        painter.fillRect(0, 0, 10, 10, QColor(255, 255, 255))
        painter.fillRect(10, 10, 10, 10, QColor(255, 255, 255))
        painter.end()
        self._preview_view.setBackgroundBrush(QBrush(bg_pixmap))
        
        right_layout.addWidget(self._preview_view)
        
        splitter.addWidget(right_widget)
        
        # Set splitter proportions (approx 35% left, 65% right)
        splitter.setSizes([380, 720])
        main_layout.addWidget(splitter)
        
    def _schedule_preview(self, *_):
        """Called whenever a setting changes to restart the debounce timer."""
        self._preview_timer.start()

    def _create_general_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        # Format & Quality
        fmt_grp = QGroupBox("Format & Quality")
        fl = QFormLayout(fmt_grp)
        
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems(["PNG", "JPG", "SVG", "HTML (Interactive D3)"])
        self._fmt_combo.currentTextChanged.connect(self._on_format_changed)
        self._fmt_combo.currentTextChanged.connect(self._schedule_preview)
        fl.addRow("Format:", self._fmt_combo)
        
        self._quality_spin = QSpinBox()
        self._quality_spin.setRange(10, 100)
        self._quality_spin.setValue(95)
        self._quality_spin.setSuffix(" %")
        self._quality_spin.setEnabled(False) # Only for JPG
        # Quality doesn't affect preview, no need to schedule preview
        fl.addRow("Quality (JPG):", self._quality_spin)
        
        self._chk_transparent = QCheckBox(self._lang.tr("graph_export_transparent"))
        self._chk_transparent.setChecked(False)
        self._chk_transparent.toggled.connect(self._schedule_preview)
        fl.addRow("Background:", self._chk_transparent)
        
        layout.addWidget(fmt_grp)
        
        # Size Mode
        size_grp = QGroupBox("Image Dimensions")
        sl = QVBoxLayout(size_grp)
        
        self._size_mode_group = QButtonGroup(self)
        
        # Mode 1: Scale & DPI
        mode1_layout = QHBoxLayout()
        self._radio_scale = QRadioButton("Scale & DPI (Original)")
        self._radio_scale.setChecked(True)
        self._size_mode_group.addButton(self._radio_scale, 1)
        mode1_layout.addWidget(self._radio_scale)
        
        self._scale_spin = QDoubleSpinBox()
        self._scale_spin.setRange(0.5, 5.0)
        self._scale_spin.setSingleStep(0.1)
        self._scale_spin.setValue(2.0)
        self._scale_spin.setSuffix(" x")
        self._scale_spin.valueChanged.connect(self._schedule_preview)
        
        self._dpi_spin = QSpinBox()
        self._dpi_spin.setRange(72, 600)
        self._dpi_spin.setValue(150)
        self._dpi_spin.setSuffix(" DPI")
        self._dpi_spin.valueChanged.connect(self._schedule_preview)
        
        mode1_layout.addWidget(QLabel("Scale:"))
        mode1_layout.addWidget(self._scale_spin)
        mode1_layout.addWidget(QLabel("Resolution:"))
        mode1_layout.addWidget(self._dpi_spin)
        sl.addLayout(mode1_layout)
        
        # Mode 2: Custom Pixels
        mode2_layout = QHBoxLayout()
        self._radio_pixels = QRadioButton("Custom Pixels")
        self._size_mode_group.addButton(self._radio_pixels, 2)
        mode2_layout.addWidget(self._radio_pixels)
        
        self._width_spin = QSpinBox()
        self._width_spin.setRange(100, 10000)
        self._width_spin.setValue(1920)
        self._width_spin.setSuffix(" px")
        self._width_spin.setEnabled(False)
        self._width_spin.valueChanged.connect(self._schedule_preview)
        
        self._height_spin = QSpinBox()
        self._height_spin.setRange(100, 10000)
        self._height_spin.setValue(int(1920 / self._aspect_ratio))
        self._height_spin.setSuffix(" px")
        self._height_spin.setEnabled(False)
        self._height_spin.valueChanged.connect(self._schedule_preview)
        
        self._chk_aspect = QCheckBox("Lock Aspect Ratio")
        self._chk_aspect.setChecked(True)
        self._chk_aspect.setEnabled(False)
        
        mode2_layout.addWidget(QLabel("W:"))
        mode2_layout.addWidget(self._width_spin)
        mode2_layout.addWidget(QLabel("H:"))
        mode2_layout.addWidget(self._height_spin)
        
        sl.addLayout(mode2_layout)
        sl.addWidget(self._chk_aspect)
        
        layout.addWidget(size_grp)
        layout.addStretch()
        
        self.tabs.addTab(tab, "General")
        
        # Connections
        self._size_mode_group.idClicked.connect(self._on_size_mode_changed)
        self._size_mode_group.idClicked.connect(self._schedule_preview)
        self._width_spin.valueChanged.connect(self._on_width_changed)
        self._height_spin.valueChanged.connect(self._on_height_changed)

    def _create_labels_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        vis_grp = QGroupBox(self._lang.tr("graph_export_visibility"))
        vl = QVBoxLayout(vis_grp)

        self._chk_docs = QCheckBox(self._lang.tr("graph_filter_docs"))
        self._chk_docs.setChecked(True)
        self._chk_docs.toggled.connect(self._schedule_preview)
        self._chk_kw = QCheckBox(self._lang.tr("graph_filter_keywords"))
        self._chk_kw.setChecked(True)
        self._chk_kw.toggled.connect(self._schedule_preview)
        self._chk_auth = QCheckBox(self._lang.tr("graph_filter_authors"))
        self._chk_auth.setChecked(True)
        self._chk_auth.toggled.connect(self._schedule_preview)
        
        h_vis = QHBoxLayout()
        h_vis.addWidget(self._chk_docs)
        h_vis.addWidget(self._chk_kw)
        h_vis.addWidget(self._chk_auth)
        vl.addLayout(h_vis)
        layout.addWidget(vis_grp)
        
        lbl_grp = QGroupBox("Label Customization")
        fl = QFormLayout(lbl_grp)
        
        self._chk_labels = QCheckBox(self._lang.tr("graph_export_show_labels"))
        self._chk_labels.setChecked(True)
        self._chk_labels.toggled.connect(self._schedule_preview)
        fl.addRow("", self._chk_labels)
        
        self._font_combo = QFontComboBox()
        self._font_combo.setCurrentFont(QFont("Segoe UI"))
        self._font_combo.currentFontChanged.connect(self._schedule_preview)
        fl.addRow("Node Font Family:", self._font_combo)
        
        self._font_size_spin = QSpinBox()
        self._font_size_spin.setRange(6, 72)
        self._font_size_spin.setValue(10)
        self._font_size_spin.setSuffix(" px")
        self._font_size_spin.valueChanged.connect(self._schedule_preview)
        fl.addRow("Node Base Font Size:", self._font_size_spin)
        
        self._cluster_font_combo = QFontComboBox()
        self._cluster_font_combo.setCurrentFont(QFont("Segoe UI"))
        self._cluster_font_combo.currentFontChanged.connect(self._schedule_preview)
        fl.addRow("Cluster Font Family:", self._cluster_font_combo)
        
        self._cluster_font_size_spin = QSpinBox()
        self._cluster_font_size_spin.setRange(6, 72)
        self._cluster_font_size_spin.setValue(14)
        self._cluster_font_size_spin.setSuffix(" px")
        self._cluster_font_size_spin.valueChanged.connect(self._schedule_preview)
        fl.addRow("Cluster Font Size:", self._cluster_font_size_spin)
        
        layout.addWidget(lbl_grp)
        
        doc_fields_grp = QGroupBox("Document Label Fields")
        dfl = QVBoxLayout(doc_fields_grp)
        self._chk_doc_title = QCheckBox("Show Title")
        self._chk_doc_title.setChecked(True)
        self._chk_doc_title.toggled.connect(self._schedule_preview)
        self._chk_doc_auth = QCheckBox("Show Authors")
        self._chk_doc_auth.setChecked(True)
        self._chk_doc_auth.toggled.connect(self._schedule_preview)
        self._chk_doc_year = QCheckBox("Show Year")
        self._chk_doc_year.setChecked(True)
        self._chk_doc_year.toggled.connect(self._schedule_preview)
        dfl.addWidget(self._chk_doc_title)
        dfl.addWidget(self._chk_doc_auth)
        dfl.addWidget(self._chk_doc_year)
        layout.addWidget(doc_fields_grp)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Labels")

    def _create_layers_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        z_grp = QGroupBox("Layer Ordering (Drag & Drop)")
        z_grp.setToolTip("Items at the top of the list will appear in front.")
        fl = QVBoxLayout(z_grp)
        
        from PySide6.QtWidgets import QListWidget, QAbstractItemView, QListWidgetItem
        
        self._layer_list = QListWidget()
        self._layer_list.setDragDropMode(QAbstractItemView.InternalMove)
        self._layer_list.setDefaultDropAction(Qt.MoveAction)
        self._layer_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._layer_list.setAlternatingRowColors(True)
        
        # Populate with default order (top to bottom)
        items = [
            ("Graph Nodes", "nodes"),
            ("Cluster Labels", "cluster_lbl"),
            ("Graph Edges", "edges"),
            ("Cluster Backgrounds", "cluster_bg"),
        ]
        
        for display_name, internal_id in items:
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, internal_id)
            self._layer_list.addItem(item)
            
        self._layer_list.model().rowsMoved.connect(self._schedule_preview)
        
        fl.addWidget(self._layer_list)
        layout.addWidget(z_grp)
        
        info = QLabel("Tip: Drag items up or down to change their Z-Index order. The top item covers the ones below it.")
        info.setWordWrap(True)
        info.setStyleSheet("color: gray; font-style: italic;")
        layout.addWidget(info)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Layers")

    def _create_legend_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        opt_grp = QGroupBox("Legend Options")
        fl = QFormLayout(opt_grp)
        
        self._chk_legend = QCheckBox("Include Legend")
        self._chk_legend.setChecked(True)
        self._chk_legend.toggled.connect(self._schedule_preview)
        fl.addRow("", self._chk_legend)
        
        self._legend_pos = QComboBox()
        self._legend_pos.addItems(["Bottom", "Top", "Left", "Right"])
        self._legend_pos.currentTextChanged.connect(self._schedule_preview)
        fl.addRow("Position:", self._legend_pos)
        
        self._chk_legend_clusters = QCheckBox("Include Clusters in Legend")
        self._chk_legend_clusters.setChecked(self._canvas._cluster_overlay_enabled)
        self._chk_legend_clusters.toggled.connect(self._schedule_preview)
        fl.addRow("", self._chk_legend_clusters)
        
        self._legend_font_size = QSpinBox()
        self._legend_font_size.setRange(6, 48)
        self._legend_font_size.setValue(12)
        self._legend_font_size.valueChanged.connect(self._schedule_preview)
        fl.addRow("Legend Font Size:", self._legend_font_size)
        
        layout.addWidget(opt_grp)
        
        # Cluster aliases editor
        cluster_grp = QGroupBox("Edit Cluster Legend Names")
        cl = QVBoxLayout(cluster_grp)
        
        self._cluster_table = QTableWidget()
        self._cluster_table.setColumnCount(2)
        self._cluster_table.setHorizontalHeaderLabels(["Original Topic", "Legend Display Name"])
        self._cluster_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._cluster_table.itemChanged.connect(self._schedule_preview)
        self._populate_cluster_table()
        
        cl.addWidget(self._cluster_table)
        layout.addWidget(cluster_grp)
        
        self.tabs.addTab(tab, "Legend")

    def _populate_cluster_table(self):
        if not self._graph_model:
            return
            
        self._cluster_table.blockSignals(True)
        clusters = self._graph_model.clusters
        valid_clusters = [c for c in clusters if len(c) >= 2]
        self._cluster_table.setRowCount(len(valid_clusters))
        
        from app.widgets.graph_node_item import CLUSTER_HUES
        
        row = 0
        for idx, cluster in enumerate(clusters):
            if len(cluster) < 2:
                continue
                
            topic_name = f"Cluster {idx+1}"
            # Find topic label from keyword neighbors
            for nid in cluster:
                for nb in self._graph_model.get_neighbors(nid):
                    nb_item = self._canvas._node_items.get(nb)
                    if nb_item and nb_item.node_type == "keyword":
                        topic_name = nb_item.node_label
                        break
                if topic_name != f"Cluster {idx+1}":
                    break
                    
            item_orig = QTableWidgetItem(topic_name)
            item_orig.setFlags(item_orig.flags() & ~Qt.ItemIsEditable)
            
            # Show color indicator
            hue = CLUSTER_HUES[idx % len(CLUSTER_HUES)]
            color = QColor.fromHsv(hue, 160, 200)
            item_orig.setBackground(QBrush(color))
            if color.lightness() < 128:
                item_orig.setForeground(QBrush(QColor("white")))
            else:
                item_orig.setForeground(QBrush(QColor("black")))
                
            item_edit = QTableWidgetItem(topic_name)
            
            self._cluster_table.setItem(row, 0, item_orig)
            self._cluster_table.setItem(row, 1, item_edit)
            
            # Store idx for mapping later
            item_orig.setData(Qt.UserRole, idx)
            row += 1
        self._cluster_table.blockSignals(False)

    # ── Signal Handlers ───────────────────────────────────────────────────
    def _on_format_changed(self, fmt: str):
        is_jpg = (fmt == "JPG")
        is_html = (fmt == "HTML (Interactive D3)")
        
        self._quality_spin.setEnabled(is_jpg)
        
        if is_jpg or is_html:
            self._chk_transparent.setChecked(False)
            self._chk_transparent.setEnabled(False)
        else:
            self._chk_transparent.setEnabled(True)
            
        # Hide dimension options for HTML
        self._size_mode_group.button(1).setEnabled(not is_html)
        self._size_mode_group.button(2).setEnabled(not is_html)
        self._scale_spin.setEnabled(not is_html and self._size_mode_group.checkedId() == 1)
        self._dpi_spin.setEnabled(not is_html and self._size_mode_group.checkedId() == 1)
        self._width_spin.setEnabled(not is_html and self._size_mode_group.checkedId() == 2)
        self._height_spin.setEnabled(not is_html and self._size_mode_group.checkedId() == 2)
            
    def _on_size_mode_changed(self, id: int):
        is_custom = (id == 2)
        self._scale_spin.setEnabled(not is_custom)
        self._dpi_spin.setEnabled(not is_custom)
        
        self._width_spin.setEnabled(is_custom)
        self._height_spin.setEnabled(is_custom)
        self._chk_aspect.setEnabled(is_custom)
        
    def _on_width_changed(self, val: int):
        if self._chk_aspect.isChecked() and self._width_spin.hasFocus():
            self._height_spin.blockSignals(True)
            self._height_spin.setValue(int(val / self._aspect_ratio))
            self._height_spin.blockSignals(False)
            
    def _on_height_changed(self, val: int):
        if self._chk_aspect.isChecked() and self._height_spin.hasFocus():
            self._width_spin.blockSignals(True)
            self._width_spin.setValue(int(val * self._aspect_ratio))
            self._width_spin.blockSignals(False)

    def _fit_preview(self):
        if self._preview_item:
            self._preview_view.fitInView(self._preview_item, Qt.KeepAspectRatio)

    # ── Live Preview Logic ────────────────────────────────────────────────
    def _apply_canvas_overrides(self):
        """Applies temporary overrides to the canvas items."""
        show_labels = self._chk_labels.isChecked()
        show_docs = self._chk_docs.isChecked()
        show_kw = self._chk_kw.isChecked()
        show_auth = self._chk_auth.isChecked()
        
        font_family = self._font_combo.currentFont().family()
        font_size = self._font_size_spin.value()
        
        cluster_font_family = self._cluster_font_combo.currentFont().family()
        cluster_font_size = self._cluster_font_size_spin.value()
        
        show_doc_title = self._chk_doc_title.isChecked()
        show_doc_auth = self._chk_doc_auth.isChecked()
        show_doc_year = self._chk_doc_year.isChecked()
        
        # Calculate Z-values based on list order (bottom item has lowest Z)
        z_map = {}
        count = self._layer_list.count()
        for i in range(count):
            item = self._layer_list.item(i)
            internal_id = item.data(Qt.UserRole)
            z_map[internal_id] = count - i # Top item gets highest Z
            
        z_nodes = z_map.get("nodes", 10)
        z_edges = z_map.get("edges", 1)
        z_cluster_lbl = z_map.get("cluster_lbl", 1)
        z_cluster_bg = z_map.get("cluster_bg", 0)

        self._original_vis = {}
        self._original_lbl_vis = {}
        for nid, item in self._canvas._node_items.items():
            self._original_vis[nid] = item.isVisible()
            self._original_lbl_vis[nid] = item._label_item.isVisible()

            type_ok = (
                (item.node_type == "document" and show_docs) or
                (item.node_type == "keyword" and show_kw) or
                (item.node_type == "author" and show_auth)
            )
            item.setVisible(type_ok)

            if not show_labels:
                item._label_item.setVisible(False)
            
            item.apply_export_overrides(
                font_family, font_size, show_doc_auth, show_doc_title, show_doc_year, z_nodes
            )

        self._original_edge_vis = []
        for edge in self._canvas._edge_items:
            self._original_edge_vis.append(edge.isVisible())
            src = self._canvas._node_items.get(edge.source_id)
            tgt = self._canvas._node_items.get(edge.target_id)
            if src and tgt:
                edge.setVisible(src.isVisible() and tgt.isVisible())

        self._canvas.apply_export_layer_overrides(z_edges, z_cluster_bg, z_cluster_lbl)
        self._canvas.apply_export_cluster_font(cluster_font_family, cluster_font_size)

    def _revert_canvas_overrides(self):
        """Restores canvas items to their original state."""
        for nid, item in self._canvas._node_items.items():
            item.clear_export_overrides()
            item.setVisible(self._original_vis.get(nid, True))
            item._label_item.setVisible(self._original_lbl_vis.get(nid, True))
            
        for i, edge in enumerate(self._canvas._edge_items):
            if i < len(self._original_edge_vis):
                edge.setVisible(self._original_edge_vis[i])
                
        self._canvas.clear_export_layer_overrides()

    def _build_legend_config(self) -> dict:
        cfg = {
            "show": self._chk_legend.isChecked(),
            "position": self._legend_pos.currentText().lower(),
            "clusters": self._chk_legend_clusters.isChecked(),
            "font_size": self._legend_font_size.value(),
            "cluster_names": {}
        }
        for row in range(self._cluster_table.rowCount()):
            idx = self._cluster_table.item(row, 0).data(Qt.UserRole)
            display_name = self._cluster_table.item(row, 1).text()
            cfg["cluster_names"][idx] = display_name
        return cfg

    def _generate_preview(self):
        """Generates a lightweight preview image and updates the scene."""
        legend_cfg = self._build_legend_config()
        w, h, rect, graph_w, graph_h, legend_space = self._calculate_dimensions(legend_cfg)
        
        # Calculate a scale factor to prevent lag (max dimension ~1200px)
        max_dim = max(w, h)
        preview_scale = 1.0
        if max_dim > 1200:
            preview_scale = 1200.0 / max_dim
            
        pw = int(w * preview_scale)
        ph = int(h * preview_scale)
        p_graph_w = int(graph_w * preview_scale)
        p_graph_h = int(graph_h * preview_scale)
        p_legend_space = int(legend_space * preview_scale)
        
        fmt = self._fmt_combo.currentText().lower()
        transparent = self._chk_transparent.isChecked()
        
        img = QImage(pw, ph, QImage.Format_ARGB32_Premultiplied)
        if transparent and fmt == "png":
            img.fill(QColor(0, 0, 0, 0))
        else:
            bg = QColor("#0e0f18") if self._canvas._dark_mode else QColor("#f5f5f8")
            img.fill(bg)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        pos = legend_cfg["position"]
        target_graph = QRectF(0, 0, p_graph_w, p_graph_h)
        if legend_cfg["show"]:
            if pos == "top":
                target_graph.moveTop(p_legend_space)
            elif pos == "left":
                target_graph.moveLeft(p_legend_space)

        # Apply overrides, render, revert
        self._apply_canvas_overrides()
        
        # Force scene to update its internal state before rendering
        self._canvas.scene().update()
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()
        
        self._canvas.scene().render(painter, target_graph, rect)
        
        if legend_cfg["show"]:
            # Need to adjust font size for the scaled preview
            preview_legend_cfg = legend_cfg.copy()
            preview_legend_cfg["font_size"] = max(4, int(legend_cfg["font_size"] * preview_scale))
            self._draw_legend(painter, pw, ph, preview_legend_cfg, p_graph_w, p_graph_h, p_legend_space)
            
        self._draw_watermark(painter, pw, ph, preview_scale)
            
        self._revert_canvas_overrides()
        painter.end()

        # Update the preview scene
        pixmap = QPixmap.fromImage(img)
        if not self._preview_item:
            self._preview_item = QGraphicsPixmapItem(pixmap)
            self._preview_scene.addItem(self._preview_item)
            self._fit_preview()
        else:
            self._preview_item.setPixmap(pixmap)

    # ── Export Logic ──────────────────────────────────────────────────────
    def _do_export(self):
        fmt_text = self._fmt_combo.currentText()
        if fmt_text.startswith("HTML"):
            fmt = "html"
        else:
            fmt = fmt_text.lower()
            
        ext_map = {"png": "PNG (*.png)", "jpg": "JPEG (*.jpg)", "svg": "SVG (*.svg)", "html": "HTML (*.html)"}

        path, _ = QFileDialog.getSaveFileName(
            self,
            self._lang.tr("graph_export_save"),
            f"knowledge_graph.{fmt}",
            ext_map.get(fmt, "All (*)"),
        )
        if not path:
            return

        transparent = self._chk_transparent.isChecked()
        legend_cfg = self._build_legend_config()

        self._apply_canvas_overrides()

        try:
            if fmt == "svg":
                self._export_svg(path, legend_cfg, transparent)
            elif fmt == "html":
                self._export_html(path, legend_cfg)
            else:
                self._export_raster(path, fmt, legend_cfg, transparent)
            QMessageBox.information(
                self,
                self._lang.tr("graph_export_title"),
                self._lang.tr("graph_export_success").format(path=path),
            )
            self.accept()
        except Exception as exc:
            QMessageBox.warning(self, "Error", str(exc))
        finally:
            self._revert_canvas_overrides()

    def _calculate_dimensions(self, legend_cfg: dict) -> tuple[int, int, QRectF, int, int, int]:
        """Calculate final image width, height, target rect, and legend dimensions."""
        scene = self._canvas.scene()
        rect = scene.itemsBoundingRect()
        rect.adjust(-30, -30, 30, 30)

        if self._size_mode_group.checkedId() == 1:
            # Scale & DPI
            scale = self._scale_spin.value()
            dpi_scale = self._dpi_spin.value() / 96.0
            graph_w = int(rect.width() * scale * dpi_scale)
            graph_h = int(rect.height() * scale * dpi_scale)
        else:
            # Custom pixels
            graph_w = self._width_spin.value()
            graph_h = self._height_spin.value()
            
        legend_space = 0
        w, h = graph_w, graph_h
        
        if legend_cfg["show"]:
            fs = legend_cfg["font_size"]
            pad = 20 + fs
            
            pos = legend_cfg["position"]
            if pos in ["bottom", "top"]:
                lines = 1
                if legend_cfg["clusters"] and len(legend_cfg["cluster_names"]) > 0:
                    lines = 2
                legend_space = pad * lines + 20
                h += legend_space
            else:
                legend_space = 250 + fs * 5
                w += legend_space
                
        return w, h, rect, graph_w, graph_h, legend_space

    def _export_raster(self, path: str, fmt: str, legend_cfg: dict, transparent: bool):
        w, h, rect, graph_w, graph_h, legend_space = self._calculate_dimensions(legend_cfg)

        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)

        if transparent and fmt == "png":
            img.fill(QColor(0, 0, 0, 0))
        else:
            bg = QColor("#0e0f18") if self._canvas._dark_mode else QColor("#f5f5f8")
            img.fill(bg)

        painter = QPainter(img)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        pos = legend_cfg["position"]
        target_graph = QRectF(0, 0, graph_w, graph_h)
        if legend_cfg["show"]:
            if pos == "top":
                target_graph.moveTop(legend_space)
            elif pos == "left":
                target_graph.moveLeft(legend_space)

        self._canvas.scene().render(painter, target_graph, rect)

        if legend_cfg["show"]:
            self._draw_legend(painter, w, h, legend_cfg, graph_w, graph_h, legend_space)

        self._draw_watermark(painter, w, h)
        painter.end()

        quality = self._quality_spin.value() if fmt == "jpg" else -1
        img.save(path, fmt.upper(), quality)

    def _export_svg(self, path: str, legend_cfg: dict, transparent: bool):
        from PySide6.QtSvg import QSvgGenerator

        w, h, rect, graph_w, graph_h, legend_space = self._calculate_dimensions(legend_cfg)

        gen = QSvgGenerator()
        gen.setFileName(path)
        gen.setSize(gen.size().__class__(w, h))
        gen.setViewBox(QRectF(0, 0, w, h))
        gen.setTitle("CiteMind Knowledge Graph")

        painter = QPainter(gen)
        painter.setRenderHint(QPainter.Antialiasing)

        if not transparent:
            bg = QColor("#0e0f18") if self._canvas._dark_mode else QColor("#f5f5f8")
            painter.fillRect(QRectF(0, 0, w, h), bg)

        pos = legend_cfg["position"]
        target_graph = QRectF(0, 0, graph_w, graph_h)
        if legend_cfg["show"]:
            if pos == "top":
                target_graph.moveTop(legend_space)
            elif pos == "left":
                target_graph.moveLeft(legend_space)

        self._canvas.scene().render(painter, target_graph, rect)

        if legend_cfg["show"]:
            self._draw_legend(painter, w, h, legend_cfg, graph_w, graph_h, legend_space)

        self._draw_watermark(painter, w, h)
        painter.end()

    def _draw_watermark(self, painter: QPainter, total_w: int, total_h: int, scale: float = 1.0):
        from app.theme import icon
        size = int(80 * scale)
        if size < 16:
            return
        logo_pm = icon("LOGOsvg").pixmap(size, size)
        x = total_w - size - int(20 * scale)
        y = total_h - size - int(20 * scale)
        painter.setOpacity(0.85)
        painter.drawPixmap(x, y, logo_pm)
        painter.setOpacity(1.0)

    def _draw_legend(self, painter: QPainter, total_w: int, total_h: int, legend_cfg: dict, graph_w: int, graph_h: int, legend_space: int):
        dark = self._canvas._dark_mode
        from app.widgets.graph_node_item import NODE_COLORS_DARK, NODE_COLORS_LIGHT, CLUSTER_HUES
        palette = NODE_COLORS_DARK if dark else NODE_COLORS_LIGHT

        text_col = QColor("#e0e0f0") if dark else QColor("#23243a")
        
        font = self._font_combo.currentFont()
        font.setPointSize(legend_cfg["font_size"])
        painter.setFont(font)
        fm = painter.fontMetrics()
        
        node_items = [
            ("graph_filter_docs", "document"),
            ("graph_filter_keywords", "keyword"),
            ("graph_filter_authors", "author"),
        ]
        
        cluster_items = []
        if legend_cfg["clusters"]:
            for idx, display_name in legend_cfg["cluster_names"].items():
                hue = CLUSTER_HUES[idx % len(CLUSTER_HUES)]
                fill = QColor.fromHsv(hue, 180 if dark else 160, 160 if dark else 200)
                border = fill.lighter(130)
                cluster_items.append((display_name, fill, border))

        pos = legend_cfg["position"]
        dot_r = fm.height() // 2
        spacing_x = int(dot_r * 3)
        spacing_y = fm.height() + 10
        
        if pos in ["bottom", "top"]:
            start_x = 20
            start_y = 20 if pos == "top" else total_h - legend_space + 20
            
            cx, cy = start_x, start_y
            for tr_key, node_type in node_items:
                colors = palette.get(node_type, palette["default"])
                painter.setBrush(QBrush(QColor(colors["fill"])))
                painter.setPen(QPen(QColor(colors["border"]), 1.5))
                painter.drawEllipse(cx, cy, dot_r*2, dot_r*2)
                
                painter.setPen(QPen(text_col))
                label = self._lang.tr(tr_key)
                painter.drawText(cx + dot_r*2 + 10, cy + dot_r*2, label)
                cx += dot_r*2 + 20 + fm.horizontalAdvance(label) + spacing_x
            
            if cluster_items:
                cx = start_x
                cy += spacing_y
                for display_name, fill, border in cluster_items:
                    painter.setBrush(QBrush(fill))
                    painter.setPen(QPen(border, 1.5))
                    painter.drawEllipse(cx, cy, dot_r*2, dot_r*2)
                    
                    painter.setPen(QPen(text_col))
                    painter.drawText(cx + dot_r*2 + 10, cy + dot_r*2, display_name)
                    cx += dot_r*2 + 20 + fm.horizontalAdvance(display_name) + spacing_x
                    if cx > total_w - 100:
                        cx = start_x
                        cy += spacing_y
        else:
            start_x = 20 if pos == "left" else total_w - legend_space + 20
            start_y = 20
            
            cx, cy = start_x, start_y
            
            painter.setPen(QPen(text_col))
            painter.drawText(cx, cy + dot_r*2, "Node Types")
            cy += spacing_y
            
            for tr_key, node_type in node_items:
                colors = palette.get(node_type, palette["default"])
                painter.setBrush(QBrush(QColor(colors["fill"])))
                painter.setPen(QPen(QColor(colors["border"]), 1.5))
                painter.drawEllipse(cx, cy, dot_r*2, dot_r*2)
                
                painter.setPen(QPen(text_col))
                label = self._lang.tr(tr_key)
                painter.drawText(cx + dot_r*2 + 10, cy + dot_r*2, label)
                cy += spacing_y
                
            if cluster_items:
                cy += 10
                painter.setPen(QPen(text_col))
                painter.drawText(cx, cy + dot_r*2, "Clusters")
                cy += spacing_y
                
                for display_name, fill, border in cluster_items:
                    painter.setBrush(QBrush(fill))
                    painter.setPen(QPen(border, 1.5))
                    painter.drawEllipse(cx, cy, dot_r*2, dot_r*2)
                    
                    painter.setPen(QPen(text_col))
                    painter.drawText(cx + dot_r*2 + 10, cy + dot_r*2, display_name)
                    cy += spacing_y

    def keyPressEvent(self, event):
        """Prevent Enter key from closing the dialog."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.ignore()
        else:
            super().keyPressEvent(event)
            
    def _export_html(self, path: str, legend_cfg: dict):
        """Export graph as interactive D3.js HTML."""
        import json
        
        # Build node and edge data
        nodes_data = []
        for nid, item in self._canvas._node_items.items():
            if not item.isVisible():
                continue
            
            # Find cluster index if any
            cluster_id = -1
            if self._graph_model:
                for idx, cluster in enumerate(self._graph_model.clusters):
                    if nid in cluster:
                        cluster_id = idx
                        break
                        
            nodes_data.append({
                "id": nid,
                "label": item.node_label,
                "type": item.node_type,
                "group": cluster_id,
                "val": 10 if item.node_type == "document" else (6 if item.node_type == "keyword" else 4)
            })
            
        edges_data = []
        for edge in self._canvas._edge_items:
            if not edge.isVisible():
                continue
            edges_data.append({
                "source": edge.source_id,
                "target": edge.target_id,
                "weight": edge.weight
            })
            
        graph_json = json.dumps({"nodes": nodes_data, "links": edges_data})
        
        # Build HTML template
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>CiteMind Knowledge Graph</title>
    <style>
        body {{ margin: 0; padding: 0; background-color: #0e0f18; color: white; font-family: sans-serif; overflow: hidden; }}
        #graph {{ width: 100vw; height: 100vh; }}
        .node-label {{ font-size: 10px; fill: #e0e0f0; pointer-events: none; }}
        .node-doc {{ fill: #484b6a; stroke: #6b6f9e; stroke-width: 2px; }}
        .node-kw {{ fill: #1e1e2e; stroke: #f28b82; stroke-width: 1.5px; }}
        .node-auth {{ fill: #1e1e2e; stroke: #81c995; stroke-width: 1px; }}
        .link {{ stroke: #2a2b3d; stroke-opacity: 0.6; }}
        #tooltip {{
            position: absolute; opacity: 0; background: rgba(30, 30, 46, 0.9); border: 1px solid #6b6f9e;
            padding: 8px; border-radius: 4px; pointer-events: none; font-size: 12px; z-index: 10;
        }}
    </style>
    <script src="https://d3js.org/d3.v7.min.js"></script>
</head>
<body>
    <div id="tooltip"></div>
    <div id="graph"></div>
    <script>
        const data = {graph_json};
        
        const width = window.innerWidth;
        const height = window.innerHeight;
        
        const svg = d3.select("#graph").append("svg")
            .attr("width", width)
            .attr("height", height)
            .call(d3.zoom().on("zoom", (e) => g.attr("transform", e.transform)));
            
        const g = svg.append("g");
        
        const simulation = d3.forceSimulation(data.nodes)
            .force("link", d3.forceLink(data.links).id(d => d.id).distance(d => 100 / d.weight))
            .force("charge", d3.forceManyBody().strength(-200))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collide", d3.forceCollide().radius(d => d.val + 10).iterations(2));
            
        const link = g.append("g")
            .selectAll("line")
            .data(data.links)
            .join("line")
            .attr("class", "link")
            .attr("stroke-width", d => Math.sqrt(d.weight));
            
        const tooltip = d3.select("#tooltip");
        
        const node = g.append("g")
            .selectAll("circle")
            .data(data.nodes)
            .join("circle")
            .attr("r", d => d.val)
            .attr("class", d => d.type === "document" ? "node-doc" : (d.type === "keyword" ? "node-kw" : "node-auth"))
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended))
            .on("mouseover", (event, d) => {{
                tooltip.transition().duration(200).style("opacity", .9);
                tooltip.html("<b>" + d.label + "</b><br/>Type: " + d.type)
                    .style("left", (event.pageX + 10) + "px")
                    .style("top", (event.pageY - 28) + "px");
            }})
            .on("mouseout", () => tooltip.transition().duration(500).style("opacity", 0));
            
        const labels = g.append("g")
            .selectAll("text")
            .data(data.nodes)
            .join("text")
            .attr("class", "node-label")
            .attr("dx", 12)
            .attr("dy", ".35em")
            .text(d => d.label);
            
        simulation.on("tick", () => {{
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);
                
            node
                .attr("cx", d => d.x)
                .attr("cy", d => d.y);
                
            labels
                .attr("x", d => d.x)
                .attr("y", d => d.y);
        }});
        
        function dragstarted(event) {{
            if (!event.active) simulation.alphaTarget(0.3).restart();
            event.subject.fx = event.subject.x;
            event.subject.fy = event.subject.y;
        }}
        
        function dragged(event) {{
            event.subject.fx = event.x;
            event.subject.fy = event.y;
        }}
        
        function dragended(event) {{
            if (!event.active) simulation.alphaTarget(0);
            event.subject.fx = null;
            event.subject.fy = null;
        }}
    </script>
</body>
</html>
"""
        Path(path).write_text(html_content, encoding="utf-8")

