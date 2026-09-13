"""
graph_node_item.py — Custom QGraphicsItem for graph nodes.

Each node is a circle with a label, colored by type or cluster.
Supports dragging, hover glow, and click selection.
"""
from __future__ import annotations

import math

from PySide6.QtWidgets import (
    QGraphicsTextItem,
    QGraphicsItem,
)
from PySide6.QtCore import Qt, QRectF, QPointF, QPropertyAnimation, QEasingCurve, QObject, Property
from PySide6.QtGui import QPen, QBrush, QColor, QPainter, QFont, QRadialGradient, QPolygonF, QPainterPath


# ── Color palettes by node type ──────────────────────────────────────────────
NODE_COLORS_DARK = {
    "document":  {"fill": "#7c3aed", "border": "#a78bfa", "text": "#e0e0f0"},
    "keyword":   {"fill": "#059669", "border": "#34d399", "text": "#e0f0e8"},
    "root":      {"fill": "#c0392b", "border": "#e74c3c", "text": "#ffffff"},
    "reference": {"fill": "#2471a3", "border": "#3498db", "text": "#e0f0ff"},
    "default":   {"fill": "#6366f1", "border": "#818cf8", "text": "#e0e0f0"},
}

NODE_COLORS_LIGHT = {
    "document":  {"fill": "#8b5cf6", "border": "#7c3aed", "text": "#23243a"},
    "keyword":   {"fill": "#10b981", "border": "#059669", "text": "#23243a"},
    "root":      {"fill": "#e74c3c", "border": "#c0392b", "text": "#ffffff"},
    "reference": {"fill": "#3498db", "border": "#2471a3", "text": "#23243a"},
    "default":   {"fill": "#6366f1", "border": "#4f46e5", "text": "#23243a"},
}

# Cluster hue palette (10 distinct hues)
CLUSTER_HUES = [270, 150, 30, 200, 350, 90, 310, 60, 180, 240]


def _size_for_type(node_type: str) -> float:
    """Return radius based on node type."""
    if node_type == "root":
        return 22.0
    elif node_type == "document":
        return 18.0
    elif node_type == "reference":
        return 16.0
    elif node_type == "keyword":
        return 12.0
    return 12.0


class GraphNodeItem(QGraphicsItem):
    """
    A draggable, hoverable graph node.

    Keyword nodes are rendered as triangles to distinguish them from document nodes.
    """
    
    class Helper(QObject):
        """Helper to allow QPropertyAnimation on QGraphicsItem."""
        def __init__(self, parent):
            super().__init__()
            self._parent = parent
            
        def get_scale(self):
            return self._parent.scale()
            
        def set_scale(self, val):
            self._parent.setScale(val)
            
        scale_prop = Property(float, get_scale, set_scale)

    def __init__(
        self,
        node_id: str,
        node_type: str,
        label: str,
        node_data: dict,
        dark_mode: bool = True,
        cluster_index: int = -1,
    ):
        self.node_id    = node_id
        self.node_type  = node_type
        self.node_label = label
        self.node_data  = node_data
        self._dark_mode = dark_mode
        self._cluster_index = cluster_index
        self._hovered   = False
        self._selected  = False
        self._dimmed    = False
        
        # Temporary overrides for export
        self._export_font_family = ""
        self._export_font_size = 0
        self._export_show_authors = True
        self._export_show_title = True
        self._export_show_year = True
        self._export_z_value = None

        self._radius = _size_for_type(node_type)
        self._brush = QBrush()
        self._pen = QPen()

        super().__init__()

        self.setFlags(
            QGraphicsItem.ItemIsMovable
            | QGraphicsItem.ItemIsSelectable
            | QGraphicsItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setZValue(10)
        
        self._anim_helper = self.Helper(self)
        self._scale_anim = QPropertyAnimation(self._anim_helper, b"scale_prop")
        self._scale_anim.setDuration(150)
        self._scale_anim.setEasingCurve(QEasingCurve.OutQuad)

        # Label — uses QGraphicsTextItem for rich HTML formatting
        self._label_item = QGraphicsTextItem(self)
        self._label_item.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self._label_item.setVisible(False)  # Hidden by default
        self._build_label_html()
        self._reposition_label()

        self._apply_style()

    def boundingRect(self):
        r = self._radius
        return QRectF(-r, -r, r * 2, r * 2)

    def shape(self):
        path = QPainterPath()
        if self.node_type == "keyword":
            points = QPolygonF([
                QPointF(0, -self._radius),
                QPointF(self._radius, self._radius),
                QPointF(-self._radius, self._radius),
            ])
            path.addPolygon(points)
        else:
            path.addEllipse(self.boundingRect())
        return path

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing)
        if self.node_type == "keyword":
            points = QPolygonF([
                QPointF(0, -self._radius),
                QPointF(self._radius, self._radius),
                QPointF(-self._radius, self._radius),
            ])
            painter.setBrush(self._brush)
            painter.setPen(self._pen)
            painter.drawPolygon(points)
        else:
            painter.setBrush(self._brush)
            painter.setPen(self._pen)
            painter.drawEllipse(self.boundingRect())

    def setBrush(self, brush):
        self._brush = brush

    def setPen(self, pen):
        self._pen = pen

    # ── Label content ─────────────────────────────────────────────────────
    def _build_label_html(self):
        """Build the HTML content for the label based on node type."""
        font_family_style = f"font-family: '{self._export_font_family}';" if self._export_font_family else ""
        
        if self.node_type == "document":
            authors = self.node_data.get("authors", "").strip()
            title = self.node_data.get("title", "").strip()
            year = self.node_data.get("year", "").strip()

            parts = []
            if authors and self._export_show_authors:
                display_authors = self._truncate(authors, 30)
                sz = self._export_font_size if self._export_font_size > 0 else 9
                parts.append(
                    f'<span style="{font_family_style}font-weight:700; font-size:{sz}px;">'
                    f'{display_authors}</span>'
                )
            if title and self._export_show_title:
                display_title = self._truncate(title, 35)
                sz = max(6, self._export_font_size - 1) if self._export_font_size > 0 else 8
                parts.append(
                    f'<span style="{font_family_style}font-size:{sz}px; font-style:italic;">'
                    f'{display_title}</span>'
                )
            if year and self._export_show_year:
                sz = max(6, self._export_font_size - 2) if self._export_font_size > 0 else 7
                parts.append(
                    f'<span style="{font_family_style}font-size:{sz}px; opacity:0.7;">({year})</span>'
                )

            html = "<br>".join(parts) if parts else "(untitled)"
        elif self.node_type in ("root", "reference"):
            # Compact label for DAG nodes: just "Surname (Year)"
            sz = self._export_font_size if self._export_font_size > 0 else 9
            html = (
                f'<span style="{font_family_style}font-weight:600; font-size:{sz}px;">'
                f'{self._truncate(self.node_label, 22)}</span>'
            )
            # Set tooltip with full info
            tooltip = self.node_data.get("tooltip", "")
            if tooltip:
                self.setToolTip(tooltip)
        else:
            sz = max(6, self._export_font_size - 1) if self._export_font_size > 0 else 8
            html = (
                f'<span style="{font_family_style}font-size:{sz}px;">'
                f'{self._truncate(self.node_label, 24)}</span>'
            )

        # Add a subtle background buffer for readability
        bg_color = "rgba(14, 15, 24, 0.85)" if self._dark_mode else "rgba(255, 255, 255, 0.85)"
        max_w = 140 if self.node_type in ("root", "reference") else 200
        buffered_html = (
            f'<div style="background-color: {bg_color}; padding: 2px 4px; border-radius: 3px; max-width: {max_w}px;">'
            f'{html}</div>'
        )

        self._label_item.setHtml(buffered_html)
        self._label_item.setTextWidth(max_w + 10)
        self._reposition_label()

    # ── Styling ───────────────────────────────────────────────────────────
    def _apply_style(self):
        palette = NODE_COLORS_DARK if self._dark_mode else NODE_COLORS_LIGHT
        colors = palette.get(self.node_type, palette["default"])

        fill_color = QColor(colors["fill"])
        border_color = QColor(colors["border"])
        text_color = QColor(colors["text"])

        # If part of a cluster, tint the fill color
        if self._cluster_index >= 0 and self.node_type == "document":
            hue = CLUSTER_HUES[self._cluster_index % len(CLUSTER_HUES)]
            sat = 180 if self._dark_mode else 160
            val = 160 if self._dark_mode else 200
            fill_color = QColor.fromHsv(hue, sat, val)
            border_color = fill_color.lighter(130)

        if self._dimmed:
            fill_color.setAlpha(40)
            border_color.setAlpha(60)
            text_color.setAlpha(60)
        elif self._hovered:
            fill_color = fill_color.lighter(130)

        self.setBrush(QBrush(fill_color))
        self.setPen(QPen(border_color, 2.0 if self._hovered or self._selected else 1.2))

        self._label_item.setDefaultTextColor(text_color)

        # Hover emphasis is handled by the thicker outline and scale animation,
        # without attaching a QGraphicsEffect to the custom QGraphicsItem.

    def _reposition_label(self):
        """Position label below the node circle."""
        r = _size_for_type(self.node_type)
        br = self._label_item.boundingRect()
        self._label_item.setPos(-br.width() / 2, r + 2)

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        return text[: max_len - 1] + "…"

    # ── Public API ────────────────────────────────────────────────────────
    def set_dimmed(self, dimmed: bool):
        self._dimmed = dimmed
        self._apply_style()

    def set_label_visible(self, visible: bool):
        self._label_item.setVisible(visible)

    def set_highlighted(self, highlighted: bool):
        self._selected = highlighted
        self._apply_style()

    def set_dark_mode(self, dark: bool):
        self._dark_mode = dark
        self._apply_style()

    def set_cluster_index(self, idx: int):
        self._cluster_index = idx
        self._apply_style()

    def apply_export_overrides(self, font_family: str, font_size: int,
                               show_authors: bool, show_title: bool, show_year: bool, z_value: int):
        """Temporarily override styling for export."""
        self._export_font_family = font_family
        self._export_font_size = font_size
        self._export_show_authors = show_authors
        self._export_show_title = show_title
        self._export_show_year = show_year
        self._export_z_value = z_value
        self.setZValue(z_value)
        self._label_item.setFlag(QGraphicsItem.ItemIgnoresTransformations, False)
        self._build_label_html()

    def clear_export_overrides(self):
        """Restore normal styling after export."""
        self._export_font_family = ""
        self._export_font_size = 0
        self._export_show_authors = True
        self._export_show_title = True
        self._export_show_year = True
        self._export_z_value = None
        self.setZValue(20 if self._hovered else 10)
        self._label_item.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self._build_label_html()

    # ── Events ────────────────────────────────────────────────────────────
    def hoverEnterEvent(self, event):
        self._hovered = True
        self._apply_style()
        self.setZValue(20)
        
        self._scale_anim.stop()
        self._scale_anim.setEndValue(1.1)
        self._scale_anim.start()
        
        # Show tooltip
        tip_parts = [f"<b>{self.node_label}</b>"]
        if self.node_type == "document":
            title = self.node_data.get("title", "")
            if title:
                tip_parts.append(f"<i>{title}</i>")
            year = self.node_data.get("year", "")
            if year:
                tip_parts.append(f"Year: {year}")
            etype = self.node_data.get("entry_type", "")
            if etype:
                tip_parts.append(f"Type: {etype}")
        self.setToolTip("<br>".join(tip_parts))
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hovered = False
        self._apply_style()
        self.setZValue(10)
        
        self._scale_anim.stop()
        self._scale_anim.setEndValue(1.0)
        self._scale_anim.start()
        
        super().hoverLeaveEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            # Notify canvas (the QGraphicsView) to update edges.
            # _on_node_moved lives on GraphCanvas, not on QGraphicsScene.
            scene = self.scene()
            if scene:
                for view in scene.views():
                    if hasattr(view, "_on_node_moved"):
                        view._on_node_moved(self)
                        break
        return super().itemChange(change, value)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        scene = self.scene()
        if scene:
            for view in scene.views():
                if hasattr(view, "_on_node_pressed"):
                    view._on_node_pressed(self)
                    break

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        scene = self.scene()
        if scene:
            for view in scene.views():
                if hasattr(view, "_on_node_released"):
                    view._on_node_released(self)
                    break

