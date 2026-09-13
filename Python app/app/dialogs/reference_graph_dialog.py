"""
reference_graph_dialog.py — Widget per visualizzare il DAG cronologico
delle referenze bibliografiche con scala temporale, topic coloring,
export PNG e controlli di navigazione.
"""
from __future__ import annotations

import os
from pathlib import Path
from collections import Counter

from PySide6.QtCore import Qt, QRectF, QTimer, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGraphicsSimpleTextItem, QComboBox, QFileDialog,
    QToolButton, QGraphicsEllipseItem, QSizePolicy,
)
from PySide6.QtGui import QFont, QColor, QBrush, QPen, QImage, QPainter

from app.theme import icon
from app.widgets.graph_canvas import GraphCanvas


# ── Topic Color Palette ───────────────────────────────────────────────────
_TOPIC_COLORS = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#e91e63", "#00bcd4", "#8bc34a",
    "#ff5722", "#607d8b", "#795548", "#cddc39", "#673ab7",
]


class ReferenceGraphWidget(QWidget):
    """Widget per il DAG cronologico delle referenze."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Grafico Cronologico Referenze")
        self.setMinimumSize(250, 250)

        self._topic_color_map: dict[str, str] = {}
        self._graph_json: dict = {}
        self._labels_visible: bool = True
        self._color_mode_index: int = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        # ── Header ──────────────────────────────────────────────────────
        header = QHBoxLayout()
        title = QLabel("📊 DAG Cronologico — Referenze Bibliografiche")
        title.setStyleSheet("font-weight: 700; font-size: 14px;")
        header.addWidget(title)
        header.addStretch()

        self._info_label = QLabel("")
        self._info_label.setStyleSheet("color: #8888a8; font-size: 11px;")
        header.addWidget(self._info_label)
        root.addLayout(header)

        # ── Toolbar ─────────────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        # Topic color filter
        toolbar.addWidget(QLabel("Colore per:"))
        self._color_combo = QComboBox()
        self._color_combo.addItem("Tipo nodo (default)")
        self._color_combo.addItem("AI Topic")
        self._color_combo.currentIndexChanged.connect(self._on_color_mode_changed)
        toolbar.addWidget(self._color_combo)

        toolbar.addStretch()

        # Pulsante per mostrare/nascondere le etichette
        btn_toggle_labels = QPushButton()
        btn_toggle_labels.setIcon(icon("tag"))
        btn_toggle_labels.setIconSize(QSize(18, 18))
        btn_toggle_labels.setFixedSize(28, 28)
        btn_toggle_labels.setToolTip("Mostra o nasconde le etichette di testo dei nodi nel grafico.")
        btn_toggle_labels.clicked.connect(self._toggle_labels_visibility)
        toolbar.addWidget(btn_toggle_labels)

        # Zoom controls
        btn_zoom_in = QToolButton()
        btn_zoom_in.setIcon(icon("zoom-in"))
        btn_zoom_in.setIconSize(QSize(18, 18))
        btn_zoom_in.setFixedSize(28, 28)
        btn_zoom_in.setToolTip("Zoom In")
        btn_zoom_in.clicked.connect(lambda: self._canvas.zoom_step(1.3))
        toolbar.addWidget(btn_zoom_in)

        btn_zoom_out = QToolButton()
        btn_zoom_out.setIcon(icon("zoom-out"))
        btn_zoom_out.setIconSize(QSize(18, 18))
        btn_zoom_out.setFixedSize(28, 28)
        btn_zoom_out.setToolTip("Zoom Out")
        btn_zoom_out.clicked.connect(lambda: self._canvas.zoom_step(0.7))
        toolbar.addWidget(btn_zoom_out)

        btn_fit = QToolButton()
        btn_fit.setIcon(icon("arrows-maximize"))
        btn_fit.setIconSize(QSize(18, 18))
        btn_fit.setFixedSize(28, 28)
        btn_fit.setToolTip("Adatta alla vista")
        btn_fit.clicked.connect(lambda: self._canvas.fit_in_view())
        toolbar.addWidget(btn_fit)

        # Export
        btn_export = QPushButton()
        btn_export.setIcon(icon("download"))
        btn_export.setIconSize(QSize(18, 18))
        btn_export.setFixedSize(28, 28)
        btn_export.setToolTip("Salva il grafico come immagine PNG ad alta risoluzione.")
        btn_export.clicked.connect(self._export_png)
        toolbar.addWidget(btn_export)

        root.addLayout(toolbar)

        # ── Legend (dynamic) ────────────────────────────────────────────
        self._legend_layout = QHBoxLayout()
        self._legend_layout.setSpacing(12)
        root.addLayout(self._legend_layout)

        # ── Canvas ──────────────────────────────────────────────────────
        self._canvas = GraphCanvas(dark_mode=True, parent=self)
        root.addWidget(self._canvas, 1)

        self._year_labels: list = []

    # ── Public API ────────────────────────────────────────────────────────
    def load_graph(self, graph_json: dict):
        """Carica il grafo e applica il layout timeline con scala temporale."""
        self._graph_json = graph_json
        self._build_topic_color_map(graph_json)

        self._canvas.load_graph(graph_json)
        self._canvas.apply_layout_algorithm("timeline")

        # Preserve view settings when the graph is refreshed.
        self._canvas.set_label_mode("all" if self._labels_visible else "none")

        # Applica tooltips ai nodi
        for node in graph_json.get("nodes", []):
            nid = node.get("id")
            tooltip = node.get("tooltip", "")
            if nid in self._canvas._node_items and tooltip:
                self._canvas._node_items[nid].setToolTip(tooltip)

        # Conta nodi
        n_nodes = len(graph_json.get("nodes", []))
        n_edges = len(graph_json.get("edges", []))
        self._info_label.setText(f"{n_nodes} nodi · {n_edges} archi")

        # Draw time axis
        self._draw_time_axis()

        if self._color_mode_index == 1:
            self._apply_topic_colors()
            self._update_legend_topics()
        else:
            self._update_legend_default()

    # ── Visibility Toggle Handler ─────────────────────────────────────────
    def _toggle_labels_visibility(self):
        """Alterna la visibilità delle etichette dei nodi."""
        self._labels_visible = not self._labels_visible
        
        # Se il canvas ha un metodo nativo per impostare la visibilità
        if hasattr(self._canvas, "set_label_mode"):
            mode = "all" if self._labels_visible else "none"
            self._canvas.set_label_mode(mode)
        else:
            # Fallback iterando direttamente sugli item del canvas
            for item in self._canvas._node_items.values():
                if hasattr(item, "_label_item") and item._label_item:
                    item._label_item.setVisible(self._labels_visible)

    # ── Topic Coloring ────────────────────────────────────────────────────
    def _build_topic_color_map(self, graph_json: dict):
        """Build a color map for all distinct AI topics."""
        topics: list[str] = []
        for node in graph_json.get("nodes", []):
            topic = node.get("ai_topic", "")
            if topic:
                topics.append(topic)

        # Count and sort by frequency
        counts = Counter(topics)
        distinct = [t for t, _ in counts.most_common()]

        self._topic_color_map = {}
        for i, topic in enumerate(distinct):
            self._topic_color_map[topic] = _TOPIC_COLORS[i % len(_TOPIC_COLORS)]

    def _on_color_mode_changed(self, index: int):
        self._color_mode_index = index
        if index == 0:
            self._apply_default_colors()
            self._update_legend_default()
        elif index == 1:
            self._apply_topic_colors()
            self._update_legend_topics()

    def _apply_default_colors(self):
        """Reset node colors to default type-based."""
        for nid, item in self._canvas._node_items.items():
            item._apply_style()

    def _apply_topic_colors(self):
        """Color nodes by their primary AI topic."""
        for node in self._graph_json.get("nodes", []):
            nid = node.get("id")
            topic = node.get("ai_topic", "")
            if nid not in self._canvas._node_items:
                continue
            item = self._canvas._node_items[nid]
            if topic and topic in self._topic_color_map:
                color = QColor(self._topic_color_map[topic])
                item.setBrush(QBrush(color))
                item.setPen(QPen(color.lighter(140), 1.5))
            else:
                # Grey for no topic
                grey = QColor("#777788")
                item.setBrush(QBrush(grey))
                item.setPen(QPen(grey.lighter(130), 1.2))
            item.update()

    def _update_legend_default(self):
        """Show default legend (node types)."""
        self._clear_legend()
        for color, text in [
            ("#e74c3c", "● Documento corrente"),
            ("#3498db", "● Referenza nel DB"),
            ("#7c3aed", "● Doc. generico"),
        ]:
            lbl = QLabel(f'<span style="color:{color}; font-size:14px;">●</span> {text}')
            lbl.setStyleSheet("font-size: 11px;")
            self._legend_layout.addWidget(lbl)
        self._legend_layout.addStretch()

    def _update_legend_topics(self):
        """Show topic-based legend."""
        self._clear_legend()
        for topic, color in self._topic_color_map.items():
            short = topic[:25] + "…" if len(topic) > 25 else topic
            lbl = QLabel(f'<span style="color:{color}; font-size:14px;">●</span> {short}')
            lbl.setStyleSheet("font-size: 11px;")
            self._legend_layout.addWidget(lbl)

        # "Senza topic" in grey
        lbl = QLabel('<span style="color:#777788; font-size:14px;">●</span> Senza topic')
        lbl.setStyleSheet("font-size: 11px;")
        self._legend_layout.addWidget(lbl)
        self._legend_layout.addStretch()

    def _clear_legend(self):
        while self._legend_layout.count():
            item = self._legend_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    # ── Export PNG ─────────────────────────────────────────────────────────
    def _export_png(self):
        """Export the current graph view as a high-resolution PNG."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Salva Grafico", str(Path.home() / "dag_bibliografico.png"),
            "Immagini PNG (*.png);;Tutti i file (*)",
        )
        if not path:
            return

        scene = self._canvas.scene()
        if not scene:
            return

        # High-resolution render (2x)
        rect = scene.itemsBoundingRect()
        rect.adjust(-80, -80, 80, 80)
        scale = 2.0
        w = int(rect.width() * scale)
        h = int(rect.height() * scale)

        # Cap at 16384 pixels per side
        if w > 16384:
            scale *= 16384 / w
            w = 16384
            h = int(rect.height() * scale)
        if h > 16384:
            scale *= 16384 / h
            h = 16384
            w = int(rect.width() * scale)

        image = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        image.fill(QColor("#0e0f18"))

        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        scene.render(painter, QRectF(0, 0, w, h), rect)
        painter.end()

        image.save(path)

    # ── Time Axis ─────────────────────────────────────────────────────────
    def _draw_time_axis(self):
        """Disegna etichette degli anni come asse verticale a sinistra."""
        scene = self._canvas.scene()
        for item in self._year_labels:
            try:
                if scene:
                    scene.removeItem(item)
            except RuntimeError:
                pass
        self._year_labels.clear()

        # Raccolta anni e posizioni Y
        years_y: dict[int, float] = {}
        for nid, item in self._canvas._node_items.items():
            attrs = None
            if self._canvas._graph_model:
                attrs = self._canvas._graph_model.get_node(nid)
            if not attrs:
                continue
            year = attrs.get("year")
            try:
                yr = int(year) if year else 0
            except (ValueError, TypeError):
                yr = 0
            if yr > 0:
                y_pos = item.pos().y()
                years_y[yr] = y_pos

        if not years_y:
            return

        all_x = [item.pos().x() for item in self._canvas._node_items.values()]
        min_x_val = min(all_x) - 120 if all_x else -120
        max_x_val = max(all_x) + 120 if all_x else 120

        for year, y_pos in sorted(years_y.items()):
            label = QGraphicsSimpleTextItem(str(year))
            font = QFont("Segoe UI", 12, QFont.Bold)
            label.setFont(font)
            label.setBrush(QBrush(QColor("#a78bfa")))
            br = label.boundingRect()
            label.setPos(min_x_val - br.width() - 25, y_pos - br.height() / 2)
            label.setZValue(10)
            scene.addItem(label)
            self._year_labels.append(label)

            from PySide6.QtWidgets import QGraphicsLineItem
            line = QGraphicsLineItem(min_x_val - 10, y_pos, max_x_val, y_pos)
            pen = QPen(QColor("#333355"), 0.8, Qt.DashLine)
            line.setPen(pen)
            line.setZValue(-1)
            scene.addItem(line)
            self._year_labels.append(line)