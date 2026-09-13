"""
graph_canvas.py — Interactive QGraphicsView with force-directed layout.

Renders the knowledge graph with:
  - spring-force layout (runs in a QTimer loop)
  - zoom (mouse wheel)
  - pan  (middle-button drag / Ctrl+drag)
  - node drag
  - click selection → highlight subgraph
  - edge rendering with weight-based opacity
"""
from __future__ import annotations

import math
import random

from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsLineItem,
    QGraphicsEllipseItem, QGraphicsSimpleTextItem,
)
from PySide6.QtCore import Qt, QTimer, Signal, QPointF, QRectF
from PySide6.QtGui import (
    QPen, QColor, QPainter, QWheelEvent, QMouseEvent, QBrush, QFont,
    QPainterPath,
)

from app.widgets.graph_node_item import GraphNodeItem
from app.graph.graph_model import (
    GraphModel, NODE_DOCUMENT, NODE_KEYWORD,
)
from app.graph.force_engine import ForceEngine


# ── Force layout parameters ──────────────────────────────────────────────────
_REPULSION   = 8000.0     # node-node repulsion constant
_ATTRACTION  = 0.008      # edge spring constant
_DAMPING     = 0.85       # velocity damping per tick
_MAX_VEL     = 15.0       # max velocity cap
_EDGE_LENGTH = 120.0      # natural spring length
_TICK_MS     = 30         # layout timer interval
_SETTLE_TICKS = 200       # ticks before auto-stop


class _EdgeItem(QGraphicsLineItem):
    """A styled graph edge."""

    def __init__(self, source_id: str, target_id: str, edge_type: str,
                 weight: float, dark_mode: bool = True):
        super().__init__()
        self.source_id = source_id
        self.target_id = target_id
        self.edge_type = edge_type
        self.weight    = weight
        self._dark_mode = dark_mode
        self._apply_style()

    def _apply_style(self):
        color_map = {
            "contains_keyword":    "#4ade80" if self._dark_mode else "#16a34a",
            "keyword_overlap":     "#a78bfa" if self._dark_mode else "#7c3aed",
            "semantic_similarity": "#38bdf8" if self._dark_mode else "#0284c7",
        }
        base_color = QColor(color_map.get(self.edge_type, "#6b7280"))
        alpha = max(30, min(200, int(self.weight * 200)))
        base_color.setAlpha(alpha)
        width = max(0.6, min(2.5, self.weight * 2.5))
        pen = QPen(base_color, width)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setZValue(1)

    def set_dark_mode(self, dark: bool):
        self._dark_mode = dark
        self._apply_style()


class GraphCanvas(QGraphicsView):
    """
    Interactive graph visualization with force-directed layout.

    Signals
    -------
    nodeClicked : (str, str)
        Emitted as (node_id, node_type) when a node is clicked.
    nodeHovered : str
        Emitted with node_id when a node is hovered.
    """

    nodeClicked = Signal(str, str)
    nodeHovered = Signal(str)

    def __init__(self, dark_mode: bool = True, parent=None):
        super().__init__(parent)
        self._dark_mode = dark_mode
        self._graph_model: GraphModel | None = None

        # Data structures
        self._node_items: dict[str, GraphNodeItem] = {}
        self._edge_items: list[_EdgeItem] = []
        self._velocities: dict[str, QPointF] = {}
        self._cluster_overlay_items: list = []    # cluster bubble graphics items
        self._cluster_overlay_enabled: bool = False
        self._label_mode: str = "none"  # "none", "documents", "keywords", "all"

        # Layout control
        self._force_engine = ForceEngine()
        self._layout_timer = QTimer(self)
        self._layout_timer.setInterval(_TICK_MS)
        self._layout_timer.timeout.connect(self._layout_tick)
        self._layout_running = False

        # Pan state
        self._panning = False
        self._pan_start = QPointF()

        # Scene
        scene = QGraphicsScene(self)
        scene.setSceneRect(-2000, -2000, 4000, 4000)
        self.setScene(scene)

        # Rendering
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._apply_background()

    # ── Public API ────────────────────────────────────────────────────────
    def load_graph(self, graph_json: dict) -> None:
        """Load a graph from JSON and start layout."""
        self._graph_model = GraphModel.from_json(graph_json)
        self._rebuild_scene()

    def clear_graph(self) -> None:
        """Remove all items and stop layout."""
        self._stop_layout()
        self.scene().clear()
        self._node_items.clear()
        self._edge_items.clear()
        self._velocities.clear()
        self._cluster_overlay_items.clear()
        self._graph_model = None

    def set_dark_mode(self, dark: bool) -> None:
        self._dark_mode = dark
        self._apply_background()
        for item in self._node_items.values():
            item.set_dark_mode(dark)
        for item in self._edge_items:
            item.set_dark_mode(dark)

    def highlight_node(self, node_id: str) -> None:
        """Highlight a node and its neighbors, dim everything else."""
        if self._graph_model is None:
            return
        neighbors = set(self._graph_model.get_neighbors(node_id))
        neighbors.add(node_id)

        for nid, item in self._node_items.items():
            if nid in neighbors:
                item.set_dimmed(False)
                item.set_highlighted(nid == node_id)
            else:
                item.set_dimmed(True)
                item.set_highlighted(False)

    def clear_highlight(self) -> None:
        """Remove all dimming/highlight."""
        for item in self._node_items.values():
            item.set_dimmed(False)
            item.set_highlighted(False)

    def fit_in_view(self) -> None:
        """Auto-zoom to fit all nodes."""
        if self._node_items:
            rect = self.scene().itemsBoundingRect()
            rect.adjust(-50, -50, 50, 50)
            
            # Expand the scene rect massively to allow infinite panning
            huge_rect = QRectF(rect.x() - 20000, rect.y() - 20000, rect.width() + 40000, rect.height() + 40000)
            self.scene().setSceneRect(huge_rect)
            
            self.fitInView(rect, Qt.KeepAspectRatio)

    def filter_by_type(self, node_types: set[str] | None = None,
                       edge_types: set[str] | None = None) -> None:
        """Show/hide nodes and edges by type."""
        for nid, item in self._node_items.items():
            if node_types is not None:
                item.setVisible(item.node_type in node_types)
            else:
                item.setVisible(True)

        for edge in self._edge_items:
            if edge_types is not None:
                edge.setVisible(edge.edge_type in edge_types)
            else:
                edge.setVisible(True)

    def filter_node_types(self, allowed_types: set[str] | None) -> None:
        """Show only nodes of the given types (None = show all).
        Connected edges are hidden when either endpoint is hidden."""
        for nid, item in self._node_items.items():
            if allowed_types is None:
                item.setVisible(True)
            else:
                item.setVisible(item.node_type in allowed_types)

        for edge in self._edge_items:
            src = self._node_items.get(edge.source_id)
            tgt = self._node_items.get(edge.target_id)
            if src and tgt:
                edge.setVisible(src.isVisible() and tgt.isVisible())

    def zoom_step(self, factor: float) -> None:
        """Zoom by a multiplicative factor (>1 = in, <1 = out)."""
        self.scale(factor, factor)

    def zoom_reset(self) -> None:
        """Reset zoom to 1:1 identity transform."""
        self.resetTransform()

    def set_labels_visible(self, visible: bool) -> None:
        """Toggle visibility of all node labels (backward compat)."""
        self.set_label_mode("all" if visible else "none")

    def set_label_mode(self, mode: str) -> None:
        """Set label visibility mode: 'none', 'documents', 'keywords', 'all'."""
        self._label_mode = mode
        for item in self._node_items.values():
            if mode == "none":
                item.set_label_visible(False)
            elif mode == "all":
                item.set_label_visible(True)
            elif mode == "documents":
                item.set_label_visible(item.node_type == "document")
            elif mode == "keywords":
                item.set_label_visible(item.node_type == "keyword")

    def set_cluster_overlay(self, enabled: bool) -> None:
        """Toggle the transparent topic-cluster overlay."""
        self._cluster_overlay_enabled = enabled
        if enabled:
            self._rebuild_cluster_overlay()
        else:
            self._clear_cluster_overlay()

    def _clear_cluster_overlay(self) -> None:
        for item in self._cluster_overlay_items:
            try:
                # Check if item still exists in C++ (PySide6 safety)
                if item and self.scene():
                    self.scene().removeItem(item)
            except RuntimeError:
                # Item already deleted by scene.clear()
                pass
        self._cluster_overlay_items.clear()

    def _rebuild_cluster_overlay(self) -> None:
        """Draw transparent ellipses around each cluster of nodes."""
        self._clear_cluster_overlay()
        if self._graph_model is None:
            return

        # Hue palette – same as node cluster colours
        from app.widgets.graph_node_item import CLUSTER_HUES
        clusters = self._graph_model.clusters

        for idx, cluster in enumerate(clusters):
            if len(cluster) < 2:
                continue

            # Gather positions of visible member nodes
            pts = []
            topic_name = ""
            for nid in cluster:
                item = self._node_items.get(nid)
                if item and item.isVisible():
                    pts.append(item.pos())

            # Find topic label from keyword neighbors of cluster members
            if not topic_name and self._graph_model:
                for nid in cluster:
                    for nb in self._graph_model.get_neighbors(nid):
                        nb_item = self._node_items.get(nb)
                        if nb_item and nb_item.node_type == "keyword":
                            topic_name = nb_item.node_label
                            break
                    if topic_name:
                        break

            if not pts:
                continue

            # Bounding rect with generous padding
            xs = [p.x() for p in pts]
            ys = [p.y() for p in pts]
            cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
            hw = max(max(xs) - min(xs), 60) / 2 + 50
            hh = max(max(ys) - min(ys), 60) / 2 + 50

            hue = CLUSTER_HUES[idx % len(CLUSTER_HUES)]
            fill = QColor.fromHsv(hue, 120, 160, 35)
            border = QColor.fromHsv(hue, 160, 200, 120)

            ellipse = QGraphicsEllipseItem(cx - hw, cy - hh, hw * 2, hh * 2)
            ellipse.setBrush(QBrush(fill))
            pen = QPen(border, 1.5, Qt.DashLine)
            ellipse.setPen(pen)
            ellipse.setZValue(0)
            self.scene().addItem(ellipse)
            self._cluster_overlay_items.append(ellipse)

            # Cluster label at top-centre
            if topic_name:
                lbl = QGraphicsSimpleTextItem(topic_name)
                font = QFont("Segoe UI", 8)
                font.setItalic(True)
                lbl.setFont(font)
                lbl_color = QColor.fromHsv(hue, 100, 220)
                lbl.setBrush(QBrush(lbl_color))
                br = lbl.boundingRect()
                lbl.setPos(cx - br.width() / 2, cy - hh + 4)
                lbl.setZValue(1)
                # Attach type to help with Z-value overrides
                lbl.setData(0, "cluster_label")
                ellipse.setData(0, "cluster_bg")
                self.scene().addItem(lbl)
                self._cluster_overlay_items.append(lbl)

    # ── Export Layer Overrides ────────────────────────────────────────────
    def apply_export_layer_overrides(self, edge_z: int, cluster_bg_z: int, cluster_lbl_z: int):
        """Temporarily change layer ordering for export."""
        for edge in self._edge_items:
            edge.setZValue(edge_z)
        
        for item in self._cluster_overlay_items:
            item_type = item.data(0)
            if item_type == "cluster_bg":
                item.setZValue(cluster_bg_z)
            elif item_type == "cluster_label":
                item.setZValue(cluster_lbl_z)

    def apply_export_cluster_font(self, font_family: str, font_size: int):
        """Temporarily change cluster label font for export."""
        self._original_cluster_fonts = {}
        for item in self._cluster_overlay_items:
            if item.data(0) == "cluster_label":
                self._original_cluster_fonts[id(item)] = item.font()
                font = QFont(font_family, font_size)
                font.setItalic(True)
                item.setFont(font)

    def clear_export_layer_overrides(self):
        """Restore normal layer ordering and fonts after export."""
        for edge in self._edge_items:
            edge.setZValue(1)
        
        for item in self._cluster_overlay_items:
            item_type = item.data(0)
            if item_type == "cluster_bg":
                item.setZValue(0)
            elif item_type == "cluster_label":
                item.setZValue(1)
                # Restore original font if we saved it
                if hasattr(self, "_original_cluster_fonts") and id(item) in self._original_cluster_fonts:
                    item.setFont(self._original_cluster_fonts[id(item)])

    # ── Scene rebuild ─────────────────────────────────────────────────────
    def _rebuild_scene(self):
        self._stop_layout()
        self.scene().clear()
        self._node_items.clear()
        self._edge_items.clear()
        self._velocities.clear()
        self._cluster_overlay_items.clear()  # Crucial: already deleted by scene.clear()

        if self._graph_model is None:
            return

        # Build cluster membership map
        cluster_map: dict[str, int] = {}
        for idx, cluster in enumerate(self._graph_model.clusters):
            for nid in cluster:
                cluster_map[nid] = idx

        # Add nodes
        for nid, attrs in self._graph_model.nodes():
            node_type = attrs.get("node_type", "default")
            label = attrs.get("label", nid)
            cluster_idx = cluster_map.get(nid, -1)

            item = GraphNodeItem(
                nid, node_type, label, attrs,
                dark_mode=self._dark_mode,
                cluster_index=cluster_idx,
            )
            # Random initial positions
            x = random.uniform(-300, 300)
            y = random.uniform(-300, 300)
            item.setPos(x, y)
            self.scene().addItem(item)
            self._node_items[nid] = item
            self._velocities[nid] = QPointF(0, 0)
            # Apply current label mode
            if self._label_mode == "none":
                item.set_label_visible(False)
            elif self._label_mode == "all":
                item.set_label_visible(True)
            elif self._label_mode == "documents":
                item.set_label_visible(node_type == "document")
            elif self._label_mode == "keywords":
                item.set_label_visible(node_type == "keyword")

        # Prepare data for ForceEngine
        node_ids = list(self._node_items.keys())
        engine_edges = []

        # Add edges
        for src, tgt, attrs in self._graph_model.edges():
            if src not in self._node_items or tgt not in self._node_items:
                continue
            edge_type = attrs.get("edge_type", "")
            weight = attrs.get("weight", 0.5)
            engine_edges.append((src, tgt, weight))
            
            edge_item = _EdgeItem(src, tgt, edge_type, weight, self._dark_mode)
            self.scene().addItem(edge_item)
            self._edge_items.append(edge_item)

        # Set up engine
        initial_positions = {nid: (self._node_items[nid].x(), self._node_items[nid].y()) for nid in node_ids}
        self._force_engine.set_graph(node_ids, initial_positions, engine_edges)

        self._update_edge_positions()
        self._start_layout()

    # ── Force-directed layout ─────────────────────────────────────────────
    def _start_layout(self):
        self._force_engine.reset_cooling()
        self._layout_running = True
        self._layout_timer.start()

    def _stop_layout(self):
        self._layout_running = False
        self._layout_timer.stop()

    def _layout_tick(self):
        """One step of the force-directed algorithm using ForceEngine."""
        if self._force_engine.is_settled():
            self._stop_layout()
            self.fit_in_view()
            if self._cluster_overlay_enabled:
                self._rebuild_cluster_overlay()
            return

        nodes = self._node_items
        if len(nodes) < 2:
            self._stop_layout()
            return

        # Advance engine simulation
        new_positions = self._force_engine.tick()

        # Update QGraphicsItems
        for nid, (nx, ny) in new_positions.items():
            if nid in nodes:
                item = nodes[nid]
                item.setPos(nx, ny)

        self._update_edge_positions()
        if self._cluster_overlay_enabled:
            self._rebuild_cluster_overlay()

    def _update_edge_positions(self):
        """Reposition all edge lines to connect node centers."""
        for edge in self._edge_items:
            src_item = self._node_items.get(edge.source_id)
            tgt_item = self._node_items.get(edge.target_id)
            if src_item and tgt_item:
                edge.setLine(
                    src_item.pos().x(), src_item.pos().y(),
                    tgt_item.pos().x(), tgt_item.pos().y(),
                )

    def _on_node_moved(self, node_item: GraphNodeItem):
        """Called by GraphNodeItem.itemChange when dragged."""
        self._update_edge_positions()
        # If simulation is running or we just moved a node, update the engine
        if self._force_engine and self._force_engine.positions is not None:
            if node_item.node_id in self._force_engine.id_to_idx:
                idx = self._force_engine.id_to_idx[node_item.node_id]
                self._force_engine.positions[idx] = [node_item.x(), node_item.y()]
                # Give a little energy back to the system so it reacts to the drag
                if self._force_engine.temperature < 0.2:
                    self._force_engine.temperature = 0.2
                    if not self._layout_running:
                        self._start_layout()

    def _on_node_pressed(self, node_item: GraphNodeItem):
        if self._force_engine:
            self._force_engine.pin_node(node_item.node_id)
            
    def _on_node_released(self, node_item: GraphNodeItem):
        if self._force_engine:
            self._force_engine.unpin_node(node_item.node_id)

    def apply_layout_algorithm(self, name: str):
        """Apply a static layout or return to force-directed."""
        if not self._force_engine or not self._node_items:
            return
            
        if name == "force":
            self._force_engine.reset_cooling()
            self._start_layout()
            return
            
        from app.graph.layout_algorithms import circular_layout, radial_layout, timeline_layout
        
        node_ids = list(self._node_items.keys())
        positions = {}
        
        if name == "circular":
            positions = circular_layout(node_ids, radius=400.0)
        elif name == "radial":
            edges = []
            if self._graph_model:
                for src, tgt, _ in self._graph_model.edges():
                    edges.append((src, tgt, 1.0))
            center = node_ids[0] if node_ids else ""
            # find node with highest degree for center
            if edges:
                degrees = {}
                for src, tgt, _ in edges:
                    degrees[src] = degrees.get(src, 0) + 1
                    degrees[tgt] = degrees.get(tgt, 0) + 1
                if degrees:
                    center = max(degrees.items(), key=lambda x: x[1])[0]
            positions = radial_layout(node_ids, edges, center)
        elif name == "timeline":
            node_years = {}
            if self._graph_model:
                for nid, attrs in self._graph_model.nodes():
                    year = attrs.get("year")
                    try:
                        node_years[nid] = int(year) if year else 0
                    except (ValueError, TypeError):
                        node_years[nid] = 0
            positions = timeline_layout(node_years, spacing_x=250.0, spacing_y=130.0)
            
        if positions:
            self._stop_layout()
            for nid, (x, y) in positions.items():
                if nid in self._node_items:
                    item = self._node_items[nid]
                    item.setPos(x, y)
                if nid in self._force_engine.id_to_idx:
                    idx = self._force_engine.id_to_idx[nid]
                    self._force_engine.positions[idx] = [x, y]
            
            # Stop the force engine completely so it doesn't drift
            self._force_engine.temperature = 0.0
            self._update_edge_positions()
            self.fit_in_view()
            if self._cluster_overlay_enabled:
                self._rebuild_cluster_overlay()

    # ── Theming ───────────────────────────────────────────────────────────
    def _apply_background(self):
        if self._dark_mode:
            bg = QColor("#0e0f18")
        else:
            bg = QColor("#f5f5f8")
        self.setBackgroundBrush(QBrush(bg))

    # ── Events ────────────────────────────────────────────────────────────
    def wheelEvent(self, event: QWheelEvent):
        """Zoom in/out."""
        factor = 1.15
        if event.angleDelta().y() < 0:
            factor = 1.0 / factor
        self.scale(factor, factor)

    def mousePressEvent(self, event: QMouseEvent):
        """Start panning on middle button, Ctrl+left, or left click on empty space."""
        item = self.itemAt(event.pos())
        
        if event.button() == Qt.MiddleButton or (
            event.button() == Qt.LeftButton and event.modifiers() & Qt.ControlModifier
        ) or (
            event.button() == Qt.LeftButton and not isinstance(item, GraphNodeItem)
        ):
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
            
            if not isinstance(item, GraphNodeItem):
                self.clear_highlight()
                
            event.accept()
            return

        # Check if a node was clicked
        if isinstance(item, GraphNodeItem):
            self.highlight_node(item.node_id)
            self.nodeClicked.emit(item.node_id, item.node_type)
        else:
            # Click on empty space → clear highlight
            self.clear_highlight()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x())
            )
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y())
            )
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self._panning:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
