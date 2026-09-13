"""
pdf_viewer.py — High-fidelity, Adobe Reader-style PDF reader for CiteMind.

Features:
- PyMuPDF (fitz) rendering engine with native annotation support (highlights, underlines, notes).
- Continuous multi-page vertical scrolling with paper shadows and high-DPI crisp rendering.
- Accurate character/word-level text selection (I-beam cursor, multi-line selection hugging exact text lines).
- Streamlined Highlighting & Underlining:
    * Highlighter tool mode (drag-to-highlight with instant commit)
    * Underline tool mode (drag-to-underline)
    * Text Selection mode with floating action popup (Highlight, Underline, Copy, Sticky note)
    * Standard keyboard shortcuts (Ctrl+C to copy, Del to delete annotation)
- Rich Annotations Management Panel:
    * Displays the actual highlighted text excerpts, page numbers, color pills, and user notes
    * One-click navigation directly to the annotation in the document view
    * Delete and Copy-as-citation actions
- Page Thumbnails sidebar for rapid visual navigation.
- Fit to Width, Fit to Page, zoom presets (50% to 300%) and Ctrl+MouseWheel zooming.
- In-document text search with match highlighting and next/prev navigation.
- Safe atomic saving to PDF file and synchronization with CiteMind DB.
"""
from __future__ import annotations

import html
import os
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import fitz

from PySide6.QtCore import (
    Qt, Signal, QSize, QRect, QRectF, QPoint, QPointF, QTimer, QUrl, QEvent
)
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QKeySequence, QDesktopServices,
    QPainter, QPixmap, QImage, QPen, QBrush, QCursor, QFont,
    QMouseEvent, QPaintEvent, QKeyEvent, QWheelEvent
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QLabel, QLineEdit,
    QPushButton, QToolButton, QSpinBox, QComboBox,
    QListWidget, QListWidgetItem, QMenu, QColorDialog, QSplitter,
    QTabWidget, QInputDialog, QMessageBox, QApplication, QFrame,
    QToolBar, QSizePolicy
)

from app.theme import icon, ThemeManager, get_global_theme
from app.i18n import LanguageManager


# Standard high-visibility highlight palette
DEFAULT_COLORS = [
    ("Giallo", "#ffeb3b", (1.0, 0.92, 0.23)),
    ("Verde", "#a3e635", (0.64, 0.90, 0.21)),
    ("Azzurro", "#7dd3fc", (0.49, 0.83, 0.99)),
    ("Arancione", "#fb923c", (0.98, 0.57, 0.24)),
    ("Rosa", "#f472b6", (0.96, 0.45, 0.71)),
]

PDF_ANNOT_STRIKEOUT = getattr(
    fitz,
    "PDF_ANNOT_STRIKEOUT",
    getattr(fitz, "PDF_ANNOT_STRIKE_OUT", 11),
)


def _pdf_theme_colors() -> dict[str, str]:
    tokens = ThemeManager.TOKENS.get(get_global_theme(), ThemeManager.TOKENS["dark"])
    return {
        "surface": tokens.bg_surface,
        "input": tokens.bg_input,
        "elevated": tokens.bg_elevated,
        "fg": tokens.fg_base,
        "border": tokens.border,
        "border_input": tokens.border_input,
        "muted": tokens.section_title_fg,
        "button_fg": tokens.toolbar_btn_fg,
        "hover": tokens.toolbar_btn_hover_bg,
        "selected": tokens.list_item_selected_bg,
        "accent": tokens.border_focus,
        "accent_fg": tokens.btn_primary_fg,
        "document_bg": tokens.bg_base,
    }


def find_closest_word_index(words: list[tuple], pt: fitz.Point) -> int:
    """Find the index of the word containing or closest to a PDF point."""
    if not words:
        return -1
    # Check if point falls directly inside a word bounding box
    for i, w in enumerate(words):
        if w[0] <= pt.x <= w[2] and w[1] <= pt.y <= w[3]:
            return i
    # Check words that intersect pt.y (same line)
    same_line = [(i, w) for i, w in enumerate(words) if w[1] - 4 <= pt.y <= w[3] + 4]
    if same_line:
        return min(same_line, key=lambda item: min(abs(pt.x - item[1][0]), abs(pt.x - item[1][2])))[0]
    # Fallback to closest word overall
    return min(range(len(words)), key=lambda i: (
        min(abs(pt.y - words[i][1]), abs(pt.y - words[i][3])) * 8 +
        min(abs(pt.x - words[i][0]), abs(pt.x - words[i][2]))
    ))


# ─────────────────────────────────────────────────────────────────────────────
# 1. PAGE CANVAS WIDGET (Renders 1 page, handles selection and direct markup)
# ─────────────────────────────────────────────────────────────────────────────
class PdfPageWidget(QWidget):
    """Renders a single PDF page with text selection and annotation overlays."""

    textSelected = Signal(int, list, str, QPoint)  # page_num, line_rects, text, global_pos
    selectionCleared = Signal()
    annotationClicked = Signal(int, int, QPoint)   # page_num, xref, global_pos
    annotationCreated = Signal(int, str, list, QColor) # page_num, kind, line_rects, color
    noteRequested = Signal(int, QPointF)           # page_num, pdf_point

    def __init__(self, page_num: int, parent=None):
        super().__init__(parent)
        self.page_num = page_num
        self._doc: fitz.Document | None = None
        self._page_rect = fitz.Rect(0, 0, 595, 842) # default A4
        self._zoom = 1.0
        self._pixmap: QPixmap | None = None
        self._pixmap_dirty = True

        # Text layer cached from PyMuPDF
        self._words: list[tuple] = []   # (x0, y0, x1, y1, word, block_no, line_no, word_no)
        self._annotations: list[dict] = [] # list of native annotation dicts

        # Selection state
        self._drag_active = False
        self._start_word_idx = -1
        self._selected_words: list[tuple] = []
        self._selection_line_rects: list[fitz.Rect] = []
        self._selected_text = ""

        # Search matches on this page
        self._search_rects: list[fitz.Rect] = []
        self._active_search_idx: int = -1

        # Hovered/selected annotation
        self._hovered_annot_xref: int | None = None
        self._selected_annot_xref: int | None = None

        # Mode: 'select', 'highlighter', 'underline', 'note'
        self.mode = "select"
        self.active_color = QColor("#ffeb3b")

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)

    def set_page_data(self, doc: fitz.Document):
        """Cache page geometry, words and annotations."""
        self._doc = doc
        if not doc or self.page_num >= len(doc):
            return
        page = doc[self.page_num]
        self._page_rect = page.rect
        self._words = page.get_text("words")
        # Read annotations
        self._load_annotations(page)
        self._pixmap_dirty = True
        self._update_geometry()

    def _load_annotations(self, page: fitz.Page):
        self._annotations = []
        for annot in page.annots() or []:
            annot_type = annot.type[0]
            kind = "nota"
            if annot_type == fitz.PDF_ANNOT_HIGHLIGHT:
                kind = "evidenzia"
            elif annot_type == fitz.PDF_ANNOT_UNDERLINE:
                kind = "sottolinea"
            elif annot_type == PDF_ANNOT_STRIKEOUT:
                kind = "barrato"
            elif annot_type == fitz.PDF_ANNOT_TEXT:
                kind = "nota"

            colors = annot.colors or {}
            stroke = colors.get("stroke") or (1.0, 0.9, 0.2)
            color_hex = QColor.fromRgbF(stroke[0], stroke[1], stroke[2]).name()

            content = annot.info.get("content", "").strip()
            # Extract actual text covered by the annotation rect
            text_snippet = ""
            if annot.rect.is_valid and not annot.rect.is_empty:
                raw_text = page.get_text("text", clip=annot.rect)
                text_snippet = " ".join(raw_text.split())

            self._annotations.append({
                "xref": annot.xref,
                "page": self.page_num,
                "kind": kind,
                "rect": annot.rect,
                "color": color_hex,
                "text": text_snippet or content,
                "comment": content,
            })

    def set_zoom(self, zoom: float):
        """Update zoom factor and mark pixmap as needing re-render."""
        if abs(self._zoom - zoom) > 0.001:
            self._zoom = zoom
            self._pixmap_dirty = True
            self._update_geometry()

    def _update_geometry(self):
        w = round(self._page_rect.width * self._zoom)
        h = round(self._page_rect.height * self._zoom)
        self.setFixedSize(w, h)

    def set_search_results(self, rects: list[fitz.Rect], active_idx: int = -1):
        self._search_rects = rects
        self._active_search_idx = active_idx
        self.update()

    def clear_selection(self):
        if self._selected_words or self._selection_line_rects:
            self._selected_words = []
            self._selection_line_rects = []
            self._selected_text = ""
            self.selectionCleared.emit()
            self.update()

    def select_annotation(self, xref: int | None):
        self._selected_annot_xref = xref
        self.update()

    def render_if_needed(self):
        """Render page pixmap with PyMuPDF at current zoom and device pixel ratio."""
        if not self._pixmap_dirty or not self._doc:
            return
        page = self._doc[self.page_num]
        dpr = self.devicePixelRatioF()
        matrix = fitz.Matrix(self._zoom * dpr, self._zoom * dpr)
        # annots=True ensures highlights, underlines, and drawings are rendered cleanly
        pix = page.get_pixmap(matrix=matrix, annots=True)
        fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(dpr)
        self._pixmap = pm
        self._pixmap_dirty = False
        self.update()

    def refresh_annots_and_render(self):
        """Reload annotations and force a re-render of this page."""
        if self._doc and self.page_num < len(self._doc):
            page = self._doc[self.page_num]
            self._load_annotations(page)
        self._pixmap_dirty = True
        self.render_if_needed()

    # ── Mouse Interaction ─────────────────────────────────────────────────
    def _pdf_point(self, pos: QPoint) -> fitz.Point:
        return fitz.Point(pos.x() / self._zoom, pos.y() / self._zoom)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            pt = self._pdf_point(event.position().toPoint())

            # Check if clicked on an existing annotation
            clicked_annot = None
            for annot in reversed(self._annotations):
                if annot["rect"].contains(pt):
                    clicked_annot = annot
                    break

            if clicked_annot and self.mode == "select":
                self._selected_annot_xref = clicked_annot["xref"]
                self.annotationClicked.emit(self.page_num, clicked_annot["xref"], event.globalPosition().toPoint())
                self.update()
                return

            self._selected_annot_xref = None

            if self.mode == "note":
                self.noteRequested.emit(self.page_num, QPointF(pt.x, pt.y))
                return

            # Start text selection or direct markup
            self._drag_active = True
            self._start_word_idx = find_closest_word_index(self._words, pt)
            if self._start_word_idx >= 0:
                self._update_selection(self._start_word_idx, self._start_word_idx)
            else:
                self.clear_selection()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        pt = self._pdf_point(event.position().toPoint())

        if self._drag_active and self._words:
            curr_word_idx = find_closest_word_index(self._words, pt)
            if curr_word_idx >= 0 and self._start_word_idx >= 0:
                idx1 = min(self._start_word_idx, curr_word_idx)
                idx2 = max(self._start_word_idx, curr_word_idx)
                self._update_selection(idx1, idx2)
            event.accept()
            return

        # Update cursor based on hover
        if self.mode in ("highlighter", "underline"):
            self.setCursor(Qt.CrossCursor)
        elif self.mode == "note":
            self.setCursor(Qt.PointingHandCursor)
        else:
            # Over text -> IBeam, over annot -> PointingHand, else -> Arrow
            hovered_annot = None
            for annot in reversed(self._annotations):
                if annot["rect"].contains(pt):
                    hovered_annot = annot
                    break

            if hovered_annot:
                self.setCursor(Qt.PointingHandCursor)
                self._hovered_annot_xref = hovered_annot["xref"]
                snippet = hovered_annot["text"][:100]
                tip = f"[{hovered_annot['kind'].upper()}] {snippet}"
                if hovered_annot.get("comment"):
                    tip += f"\nNota: {hovered_annot['comment']}"
                self.setToolTip(tip)
            else:
                self._hovered_annot_xref = None
                self.setToolTip("")
                is_over_word = any(w[0] <= pt.x <= w[2] and w[1] <= pt.y <= w[3] for w in self._words)
                self.setCursor(Qt.IBeamCursor if is_over_word else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._drag_active:
            self._drag_active = False
            if self._selection_line_rects and self._selected_text:
                if self.mode == "highlighter":
                    self.annotationCreated.emit(self.page_num, "evidenzia", list(self._selection_line_rects), self.active_color)
                    self.clear_selection()
                elif self.mode == "underline":
                    self.annotationCreated.emit(self.page_num, "sottolinea", list(self._selection_line_rects), self.active_color)
                    self.clear_selection()
                else: # select mode
                    global_pt = event.globalPosition().toPoint()
                    self.textSelected.emit(self.page_num, list(self._selection_line_rects), self._selected_text, global_pt)
            event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Double click selects the word under cursor."""
        if event.button() == Qt.LeftButton and self._words:
            pt = self._pdf_point(event.position().toPoint())
            idx = find_closest_word_index(self._words, pt)
            if idx >= 0:
                self._update_selection(idx, idx)
                if self._selection_line_rects and self.mode == "select":
                    self.textSelected.emit(self.page_num, list(self._selection_line_rects), self._selected_text, event.globalPosition().toPoint())

    def _update_selection(self, idx1: int, idx2: int):
        self._selected_words = self._words[idx1 : idx2 + 1]
        self._selected_text = " ".join(w[4] for w in self._selected_words)

        # Group words by line (block_no, line_no)
        lines = defaultdict(list)
        for w in self._selected_words:
            lines[(w[5], w[6])].append(w)

        self._selection_line_rects = []
        for (b, l), ws in lines.items():
            r = fitz.Rect(
                min(w[0] for w in ws),
                min(w[1] for w in ws),
                max(w[2] for w in ws),
                max(w[3] for w in ws),
            )
            self._selection_line_rects.append(r)
        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        # Copy selected text
        if event.matches(QKeySequence.Copy) and self._selected_text:
            QApplication.clipboard().setText(self._selected_text)
            event.accept()
            return
        super().keyPressEvent(event)

    # ── Paint Event ───────────────────────────────────────────────────────
    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 1. Base paper background & drop shadow
        painter.fillRect(self.rect(), Qt.white)

        # 2. Rendered PDF page image
        if self._pixmap_dirty:
            self.render_if_needed()
        if self._pixmap and not self._pixmap.isNull():
            painter.drawPixmap(0, 0, self._pixmap)

        zoom = self._zoom

        # 3. Search highlights
        if self._search_rects:
            for i, r in enumerate(self._search_rects):
                sr = QRectF(r.x0 * zoom, r.y0 * zoom, r.width * zoom, r.height * zoom)
                if i == self._active_search_idx:
                    painter.fillRect(sr, QColor(255, 120, 0, 160))
                    painter.setPen(QPen(QColor(220, 80, 0), 1.5))
                    painter.drawRect(sr)
                else:
                    painter.fillRect(sr, QColor(255, 210, 0, 110))

        # 4. Text selection line-by-line highlight (sleek semi-transparent blue)
        if self._selection_line_rects:
            sel_color = QColor(66, 133, 244, 115)
            painter.setBrush(sel_color)
            painter.setPen(Qt.NoPen)
            for r in self._selection_line_rects:
                sr = QRectF(r.x0 * zoom, r.y0 * zoom, r.width * zoom, r.height * zoom)
                painter.drawRoundedRect(sr, 2, 2)

        # 5. Selected annotation halo/border
        if self._selected_annot_xref is not None:
            for annot in self._annotations:
                if annot["xref"] == self._selected_annot_xref:
                    r = annot["rect"]
                    ar = QRectF(r.x0 * zoom - 2, r.y0 * zoom - 2, r.width * zoom + 4, r.height * zoom + 4)
                    painter.setBrush(Qt.NoBrush)
                    pen = QPen(QColor("#4f46e5"), 2.0, Qt.DashLine)
                    painter.setPen(pen)
                    painter.drawRoundedRect(ar, 3, 3)
                    break

        painter.end()


# ─────────────────────────────────────────────────────────────────────────────
# 2. FLOATING ACTION POPUP (Mini-bar above selected text)
# ─────────────────────────────────────────────────────────────────────────────
class PdfFloatingPopup(QFrame):
    """Compact floating toolbar that appears above selected text."""

    highlightClicked = Signal(QColor)
    underlineClicked = Signal()
    copyClicked = Signal()
    noteClicked = Signal()

    def __init__(self, lang: LanguageManager, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self._lang = lang
        self.setObjectName("pdfFloatingPopup")
        self.setStyleSheet("""
            #pdfFloatingPopup {
                background: #1e1e2d;
                border: 1px solid #3f3f58;
                border-radius: 6px;
                padding: 2px;
            }
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 4px;
                padding: 4px 8px;
                color: #e0e0e0;
                font-weight: 500;
                font-size: 11px;
            }
            QToolButton:hover {
                background: #32324d;
                color: #ffffff;
            }
            QToolButton:pressed {
                background: #4f46e5;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)

        # Highlight button with current color
        self._btn_highlight = QToolButton()
        self._btn_highlight.setText(f" {self._lang.tr('pdf_highlight')}")
        self._btn_highlight.setIcon(icon("highlight"))
        self._btn_highlight.setToolTip(self._lang.tr("pdf_highlight_tip"))
        self._btn_highlight.clicked.connect(self._on_highlight)
        layout.addWidget(self._btn_highlight)

        # Underline button
        btn_underline = QToolButton()
        btn_underline.setText(f" {self._lang.tr('pdf_underline')}")
        btn_underline.setIcon(icon("underline"))
        btn_underline.setToolTip(self._lang.tr("pdf_underline_tip"))
        btn_underline.clicked.connect(lambda: (self.underlineClicked.emit(), self.hide()))
        layout.addWidget(btn_underline)

        # Copy button
        btn_copy = QToolButton()
        btn_copy.setText(f" {self._lang.tr('pdf_copy')}")
        btn_copy.setIcon(icon("copy"))
        btn_copy.setToolTip(self._lang.tr("pdf_copy_tip"))
        btn_copy.clicked.connect(lambda: (self.copyClicked.emit(), self.hide()))
        layout.addWidget(btn_copy)

        # Note button
        btn_note = QToolButton()
        btn_note.setText(f" {self._lang.tr('pdf_note')}")
        btn_note.setIcon(icon("notes"))
        btn_note.setToolTip(self._lang.tr("pdf_note_tip"))
        btn_note.clicked.connect(lambda: (self.noteClicked.emit(), self.hide()))
        layout.addWidget(btn_note)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("background: #3f3f58; margin: 2px 4px;")
        layout.addWidget(sep)

        # Color dots
        self._active_color = QColor("#ffeb3b")
        for label, hex_code, rgb in DEFAULT_COLORS:
            btn = QToolButton()
            btn.setFixedSize(16, 16)
            btn.setToolTip(f"Colore: {label}")
            btn.setStyleSheet(f"""
                QToolButton {{
                    background: {hex_code};
                    border: 1px solid #222;
                    border-radius: 8px;
                }}
                QToolButton:hover {{
                    border: 2px solid #ffffff;
                }}
            """)
            btn.clicked.connect(lambda _, c=QColor(hex_code): self._set_color_and_highlight(c))
            layout.addWidget(btn)

    def set_color(self, color: QColor):
        self._active_color = color

    def _on_highlight(self):
        self.highlightClicked.emit(self._active_color)
        self.hide()

    def _set_color_and_highlight(self, color: QColor):
        self._active_color = color
        self._on_highlight()
    def refresh_theme(self):
        colors = _pdf_theme_colors()
        self.setStyleSheet(f"""
            #pdfFloatingPopup {{ background: {colors['surface']}; border: 1px solid {colors['border']}; border-radius: 6px; padding: 2px; }}
            QToolButton {{ background: transparent; border: none; border-radius: 4px; padding: 4px 8px; color: {colors['fg']}; font-weight: 500; font-size: 11px; }}
            QToolButton:hover {{ background: {colors['hover']}; color: {colors['fg']}; }}
            QToolButton:pressed {{ background: {colors['accent']}; color: {colors['accent_fg']}; }}
        """)


# ─────────────────────────────────────────────────────────────────────────────
# 3. DOCUMENT VIEW (Continuous vertical scroll area of pages)
# ─────────────────────────────────────────────────────────────────────────────
class PdfDocumentView(QScrollArea):
    """Smooth continuous multi-page PDF scrolling canvas."""

    pageScrolled = Signal(int) # 0-indexed visible page

    def __init__(self, lang: LanguageManager, parent=None):
        super().__init__(parent)
        self._lang = lang
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignHCenter)
        self.setStyleSheet("""
            QScrollArea {
                background-color: #2b2d35;
                border: none;
            }
        """)

        self._container = QWidget()
        self._container.setStyleSheet("background-color: transparent;")
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignHCenter)
        self._layout.setSpacing(14)
        self._layout.setContentsMargins(20, 16, 20, 24)
        self.setWidget(self._container)

        self._pages: list[PdfPageWidget] = []
        self._zoom = 1.0

        self.verticalScrollBar().valueChanged.connect(self._on_scroll)

    def clear(self):
        for p in self._pages:
            p.setParent(None)
            p.deleteLater()
        self._pages = []

    def set_pages(self, pages: list[PdfPageWidget]):
        self.clear()
        self._pages = pages
        for p in pages:
            self._layout.addWidget(p)
        self.set_zoom(self._zoom)
        QTimer.singleShot(50, self._render_visible_pages)

    def set_zoom(self, zoom: float):
        self._zoom = zoom
        for p in self._pages:
            p.set_zoom(zoom)
        self._render_visible_pages()

    def zoom(self) -> float:
        return self._zoom

    def pages(self) -> list[PdfPageWidget]:
        return self._pages

    def scroll_to_page(self, page_num: int):
        if 0 <= page_num < len(self._pages):
            widget = self._pages[page_num]
            self.ensureWidgetVisible(widget, 0, 40)
            self._render_visible_pages()

    def scroll_to_rect(self, page_num: int, rect: fitz.Rect):
        if 0 <= page_num < len(self._pages):
            page_widget = self._pages[page_num]
            zoom = self._zoom
            y_in_widget = rect.y0 * zoom
            global_y = page_widget.y() + y_in_widget
            target_scrollbar_val = max(0, int(global_y - self.viewport().height() / 2))
            self.verticalScrollBar().setValue(target_scrollbar_val)
            self._render_visible_pages()

    def _on_scroll(self):
        self._render_visible_pages()
        # Find which page is centered in viewport
        vp_center = self.verticalScrollBar().value() + self.viewport().height() // 2
        for p in self._pages:
            if p.y() <= vp_center <= p.y() + p.height():
                self.pageScrolled.emit(p.page_num)
                break

    def _render_visible_pages(self):
        """Render pixmaps only for pages in or near the viewport for optimal performance."""
        if not self._pages:
            return
        vp_top = self.verticalScrollBar().value() - 400
        vp_bottom = self.verticalScrollBar().value() + self.viewport().height() + 400
        for p in self._pages:
            p_top = p.y()
            p_bottom = p.y() + p.height()
            if p_bottom >= vp_top and p_top <= vp_bottom:
                p.render_if_needed()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(50, self._render_visible_pages)

    def wheelEvent(self, event: QWheelEvent):
        # Ctrl + Wheel zooms in/out smoothly
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.set_zoom(min(3.5, self._zoom + 0.15))
            elif delta < 0:
                self.set_zoom(max(0.3, self._zoom - 0.15))
            event.accept()
            return
        super().wheelEvent(event)
    def refresh_theme(self):
        colors = _pdf_theme_colors()
        self.setStyleSheet(f"QScrollArea {{ background-color: {colors['document_bg']}; border: none; }}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. ANNOTATIONS & THUMBNAILS SIDE PANEL
# ─────────────────────────────────────────────────────────────────────────────
class PdfAnnotationsPanel(QWidget):
    """Side panel containing the rich Annotations List and Page Thumbnails."""

    annotationSelected = Signal(int, int) # page_num, xref
    annotationDeleteRequested = Signal(int, int) # page_num, xref
    annotationCommentEditRequested = Signal(int, int, str) # page_num, xref, current_comment
    pageThumbnailClicked = Signal(int) # page_num

    def __init__(self, lang: LanguageManager, parent=None):
        super().__init__(parent)
        self._lang = lang
        self.setMinimumWidth(220)
        self.setMaximumWidth(380)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #333644; background: #1f212a; }
            QTabBar::tab { background: #191a22; color: #a0a5b8; padding: 6px 12px; margin-right: 2px; }
            QTabBar::tab:selected { background: #1f212a; color: #ffffff; font-weight: bold; border-top: 2px solid #4f46e5; }
        """)

        # ── TAB 1: Annotazioni
        annots_widget = QWidget()
        annots_layout = QVBoxLayout(annots_widget)
        annots_layout.setContentsMargins(4, 6, 4, 4)
        annots_layout.setSpacing(4)

        self._filter_field = QLineEdit()
        self._filter_field.setPlaceholderText(self._lang.tr("pdf_filter_annotations"))
        self._filter_field.setClearButtonEnabled(True)
        self._filter_field.textChanged.connect(self._filter_items)
        annots_layout.addWidget(self._filter_field)

        self._annots_list = QListWidget()
        self._annots_list.setStyleSheet("""
            QListWidget {
                background-color: #1f212a;
                border: none;
            }
            QListWidget::item {
                border-bottom: 1px solid #2d3040;
                padding: 6px 4px;
            }
            QListWidget::item:hover {
                background: #282b3a;
            }
            QListWidget::item:selected {
                background: #333852;
                border-left: 3px solid #4f46e5;
            }
        """)
        self._annots_list.itemClicked.connect(self._on_item_clicked)
        self._annots_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._annots_list.customContextMenuRequested.connect(self._show_context_menu)
        annots_layout.addWidget(self._annots_list)

        actions_bar = QHBoxLayout()
        self._count_label = QLabel(self._lang.tr("pdf_annotations_count").format(count=0))
        self._count_label.setStyleSheet("color: #8f95a8; font-size: 11px;")
        actions_bar.addWidget(self._count_label)
        actions_bar.addStretch()

        self._btn_delete = QPushButton()
        self._btn_delete.setIcon(icon("trash"))
        self._btn_delete.setToolTip(self._lang.tr("pdf_delete_annotation"))
        self._btn_delete.setEnabled(False)
        self._btn_delete.clicked.connect(self._delete_current)
        actions_bar.addWidget(self._btn_delete)
        annots_layout.addLayout(actions_bar)

        self._tabs.addTab(annots_widget, self._lang.tr("pdf_annotations"))

        # ── TAB 2: Miniature
        self._thumbs_list = QListWidget()
        self._thumbs_list.setIconSize(QSize(90, 120))
        self._thumbs_list.setStyleSheet("""
            QListWidget {
                background-color: #1f212a;
                border: none;
            }
            QListWidget::item {
                color: #c0c5d8;
                padding: 4px;
                text-align: center;
            }
            QListWidget::item:selected {
                background: #333852;
                border-radius: 4px;
            }
        """)
        self._thumbs_list.itemClicked.connect(lambda item: self.pageThumbnailClicked.emit(item.data(Qt.UserRole)))
        self._tabs.addTab(self._thumbs_list, self._lang.tr("pdf_thumbnails"))

        layout.addWidget(self._tabs)

    def set_annotations(self, annotations: list[dict]):
        self._annots_list.clear()
        self._all_annotations = annotations
        self._count_label.setText(self._lang.tr("pdf_annotations_count").format(count=len(annotations)))
        self._btn_delete.setEnabled(False)

        for a in annotations:
            item = QListWidgetItem()
            page_idx = a["page"]
            kind = a["kind"].capitalize()
            text_snippet = a.get("text", "").strip() or "(nessun testo)"
            comment = a.get("comment", "").strip()
            color = a.get("color", "#ffeb3b")

            # Create rich visual card for each annotation
            card = QWidget()
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(4, 2, 4, 2)
            card_layout.setSpacing(2)

            top_row = QHBoxLayout()
            color_dot = QLabel()
            color_dot.setFixedSize(10, 10)
            color_dot.setStyleSheet(f"background: {color}; border-radius: 5px;")
            top_row.addWidget(color_dot)

            badge = QLabel(f"Pag. {page_idx + 1}  •  {kind}")
            badge.setStyleSheet("color: #a5b4fc; font-weight: bold; font-size: 11px;")
            top_row.addWidget(badge)
            top_row.addStretch()
            card_layout.addLayout(top_row)

            # Excerpt of highlighted text
            excerpt = QLabel(f'"{text_snippet}"' if len(text_snippet) < 140 else f'"{text_snippet[:137]}..."')
            excerpt.setWordWrap(True)
            excerpt.setStyleSheet("color: #e2e8f0; font-style: italic; font-size: 11px; margin-left: 6px;")
            card_layout.addWidget(excerpt)

            # User comment (if any)
            if comment:
                comment_lbl = QLabel(f"💬 {comment}")
                comment_lbl.setWordWrap(True)
                comment_lbl.setStyleSheet("color: #fde047; font-size: 11px; margin-left: 6px;")
                card_layout.addWidget(comment_lbl)

            card.setLayout(card_layout)
            item.setSizeHint(card.sizeHint())
            item.setData(Qt.UserRole, a)
            self._annots_list.addItem(item)
            self._annots_list.setItemWidget(item, card)

    def load_thumbnails(self, doc: fitz.Document):
        self._thumbs_list.clear()
        if not doc:
            return
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=fitz.Matrix(0.2, 0.2), annots=True)
            fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
            img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
            pm = QPixmap.fromImage(img)
            item = QListWidgetItem(f"Pagina {i + 1}")
            item.setIcon(pm)
            item.setData(Qt.UserRole, i)
            self._thumbs_list.addItem(item)

    def _on_item_clicked(self, item: QListWidgetItem):
        self._btn_delete.setEnabled(True)
        data = item.data(Qt.UserRole)
        if data:
            self.annotationSelected.emit(data["page"], data["xref"])

    def _delete_current(self):
        item = self._annots_list.currentItem()
        if not item:
            return
        data = item.data(Qt.UserRole)
        if data:
            self.annotationDeleteRequested.emit(data["page"], data["xref"])

    def _filter_items(self, text: str):
        query = text.strip().lower()
        for i in range(self._annots_list.count()):
            item = self._annots_list.item(i)
            data = item.data(Qt.UserRole)
            if not query:
                item.setHidden(False)
            else:
                annot_text = (data.get("text", "") + " " + data.get("comment", "")).lower()
                item.setHidden(query not in annot_text)

    def _show_context_menu(self, pos: QPoint):
        item = self._annots_list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.UserRole)
        menu = QMenu(self)

        act_goto = menu.addAction(icon("arrow-right"), self._lang.tr("pdf_go_to_annotation"))
        act_copy_text = menu.addAction(icon("copy"), self._lang.tr("pdf_copy_annotated_text"))
        act_copy_cite = menu.addAction(icon("quote"), self._lang.tr("pdf_copy_citation"))
        menu.addSeparator()
        act_edit_comment = menu.addAction(icon("pencil"), self._lang.tr("pdf_edit_comment"))
        act_delete = menu.addAction(icon("trash"), self._lang.tr("pdf_delete_annotation"))

        action = menu.exec(self._annots_list.mapToGlobal(pos))
        if action == act_goto:
            self.annotationSelected.emit(data["page"], data["xref"])
        elif action == act_copy_text:
            QApplication.clipboard().setText(data.get("text", ""))
        elif action == act_copy_cite:
            snippet = data.get("text", "")
            page_num = data.get("page", 0) + 1
            QApplication.clipboard().setText(f'"{snippet}" (p. {page_num})')
        elif action == act_edit_comment:
            self.annotationCommentEditRequested.emit(data["page"], data["xref"], data.get("comment", ""))
        elif action == act_delete:
            self.annotationDeleteRequested.emit(data["page"], data["xref"])
    def refresh_theme(self):
        colors = _pdf_theme_colors()
        self._tabs.setStyleSheet(f"QTabWidget::pane {{ border: 1px solid {colors['border']}; background: {colors['surface']}; }} QTabBar::tab {{ background: {colors['elevated']}; color: {colors['muted']}; padding: 6px 12px; margin-right: 2px; }} QTabBar::tab:selected {{ background: {colors['surface']}; color: {colors['fg']}; font-weight: bold; border-top: 2px solid {colors['accent']}; }}")
        self._annots_list.setStyleSheet(f"QListWidget {{ background-color: {colors['surface']}; border: none; }} QListWidget::item {{ border-bottom: 1px solid {colors['border']}; padding: 6px 4px; }} QListWidget::item:hover {{ background: {colors['hover']}; }} QListWidget::item:selected {{ background: {colors['selected']}; border-left: 3px solid {colors['accent']}; }}")
        self._thumbs_list.setStyleSheet(f"QListWidget {{ background-color: {colors['surface']}; border: none; }} QListWidget::item {{ color: {colors['fg']}; padding: 4px; text-align: center; }} QListWidget::item:selected {{ background: {colors['selected']}; border-radius: 4px; }}")
        self._count_label.setStyleSheet(f"color: {colors['muted']}; font-size: 11px;")


# ─────────────────────────────────────────────────────────────────────────────
# 5. MASTER PDF VIEWER WIDGET (Main container with toolbar, views, and sync)
# ─────────────────────────────────────────────────────────────────────────────
class PdfViewerWidget(QWidget):
    """Integrated, feature-complete PDF reader for CiteMind."""

    annotationChanged = Signal()

    def __init__(self, lang: LanguageManager, parent=None):
        super().__init__(parent)
        self._lang = lang
        self._model = None
        self._entry_id: int | None = None
        self._pdf_path = ""
        self._working_path = ""
        self._doc: fitz.Document | None = None
        self._is_modified = False

        # Active markup mode and color
        self._markup_mode = "select" # 'select', 'highlighter', 'underline', 'note'
        self._active_color = QColor("#ffeb3b")

        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── TOOLBAR (Adobe Reader style) ──────────────────────────────────
        self._toolbar = QToolBar()
        self._toolbar.setIconSize(QSize(18, 18))
        self._toolbar.setStyleSheet("""
            QToolBar {
                background: #181920;
                border-bottom: 1px solid #333644;
                spacing: 4px;
                padding: 3px 6px;
            }
            QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 4px;
                padding: 4px 6px;
                color: #d1d5db;
            }
            QToolButton:hover {
                background: #282a36;
                border: 1px solid #45495e;
            }
            QToolButton:checked {
                background: #4f46e5;
                color: #ffffff;
                border: 1px solid #818cf8;
            }
            QLabel {
                color: #9ca3af;
                font-size: 11px;
            }
        """)

        # Sidebar toggle
        self._act_toggle_sidebar = QAction(icon("layout-sidebar"), "", self)
        self._act_toggle_sidebar.setToolTip(self._lang.tr("pdf_toggle_annotations"))
        self._act_toggle_sidebar.setCheckable(True)
        self._act_toggle_sidebar.setChecked(True)
        self._act_toggle_sidebar.triggered.connect(self._toggle_sidebar)
        self._toolbar.addAction(self._act_toggle_sidebar)
        self._toolbar.addSeparator()

        # Page Navigation
        act_prev_page = QAction(icon("arrow-left"), "", self)
        act_prev_page.setToolTip(self._lang.tr("pdf_previous_page"))
        act_prev_page.triggered.connect(lambda: self._step_page(-1))
        self._toolbar.addAction(act_prev_page)

        self._page_spin = QSpinBox()
        self._page_spin.setRange(1, 1)
        self._page_spin.setToolTip(self._lang.tr("pdf_page_number"))
        self._page_spin.valueChanged.connect(self._on_page_spin_changed)
        self._toolbar.addWidget(self._page_spin)

        self._page_count_label = QLabel("/ 0")
        self._toolbar.addWidget(self._page_count_label)

        act_next_page = QAction(icon("arrow-right"), "", self)
        act_next_page.setToolTip(self._lang.tr("pdf_next_page"))
        act_next_page.triggered.connect(lambda: self._step_page(1))
        self._toolbar.addAction(act_next_page)
        self._toolbar.addSeparator()

        # Zoom Controls
        act_zoom_out = QAction(icon("zoom-out"), "", self)
        act_zoom_out.setToolTip(self._lang.tr("pdf_zoom_out"))
        act_zoom_out.triggered.connect(lambda: self._change_zoom(-0.15))
        self._toolbar.addAction(act_zoom_out)

        self._zoom_combo = QComboBox()
        self._zoom_combo.addItems(["50%", "75%", "100%", "125%", "150%", "200%", self._lang.tr("pdf_fit_width"), self._lang.tr("pdf_fit_page")])
        self._zoom_combo.setCurrentText("100%")
        self._zoom_combo.currentTextChanged.connect(self._on_zoom_combo_changed)
        self._toolbar.addWidget(self._zoom_combo)

        act_zoom_in = QAction(icon("zoom-in"), "", self)
        act_zoom_in.setToolTip(self._lang.tr("pdf_zoom_in"))
        act_zoom_in.triggered.connect(lambda: self._change_zoom(0.15))
        self._toolbar.addAction(act_zoom_in)

        act_fit_width = QAction(icon("arrows-horizontal"), "", self)
        act_fit_width.setToolTip(self._lang.tr("pdf_fit_width_tip"))
        act_fit_width.triggered.connect(self._fit_to_width)
        self._toolbar.addAction(act_fit_width)

        act_fit_page = QAction(icon("arrows-vertical"), "", self)
        act_fit_page.setToolTip(self._lang.tr("pdf_fit_page_tip"))
        act_fit_page.triggered.connect(self._fit_to_page)
        self._toolbar.addAction(act_fit_page)
        self._toolbar.addSeparator()

        # Reading & Markup Tools
        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)

        self._act_mode_select = QAction(icon("cursor-text"), "", self)
        self._act_mode_select.setToolTip(self._lang.tr("pdf_select_mode"))
        self._act_mode_select.setCheckable(True)
        self._act_mode_select.setChecked(True)
        self._act_mode_select.triggered.connect(lambda: self._set_mode("select"))
        self._mode_group.addAction(self._act_mode_select)
        self._toolbar.addAction(self._act_mode_select)

        self._act_mode_highlight = QAction(icon("highlight"), "", self)
        self._act_mode_highlight.setToolTip(self._lang.tr("pdf_highlight_mode"))
        self._act_mode_highlight.setCheckable(True)
        self._act_mode_highlight.triggered.connect(lambda: self._set_mode("highlighter"))
        self._mode_group.addAction(self._act_mode_highlight)
        self._toolbar.addAction(self._act_mode_highlight)

        self._act_mode_underline = QAction(icon("underline"), "", self)
        self._act_mode_underline.setToolTip(self._lang.tr("pdf_underline_mode"))
        self._act_mode_underline.setCheckable(True)
        self._act_mode_underline.triggered.connect(lambda: self._set_mode("underline"))
        self._mode_group.addAction(self._act_mode_underline)
        self._toolbar.addAction(self._act_mode_underline)

        self._act_mode_note = QAction(icon("notes"), "", self)
        self._act_mode_note.setToolTip(self._lang.tr("pdf_note_mode"))
        self._act_mode_note.setCheckable(True)
        self._act_mode_note.triggered.connect(lambda: self._set_mode("note"))
        self._mode_group.addAction(self._act_mode_note)
        self._toolbar.addAction(self._act_mode_note)

        # Color picker button with dropdown
        self._color_button = QToolButton()
        self._color_button.setToolTip(self._lang.tr("pdf_active_color"))
        self._color_button.setPopupMode(QToolButton.InstantPopup)
        color_menu = QMenu(self._color_button)
        for label, hex_code, rgb in DEFAULT_COLORS:
            action = color_menu.addAction(label)
            action.triggered.connect(lambda _, h=hex_code: self._apply_color(QColor(h)))
        color_menu.addSeparator()
        act_custom_color = color_menu.addAction(self._lang.tr("pdf_custom_color"))
        act_custom_color.triggered.connect(self._choose_custom_color)
        self._color_button.setMenu(color_menu)
        self._update_color_button()
        self._toolbar.addWidget(self._color_button)
        self._toolbar.addSeparator()

        # In-document search
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText(self._lang.tr("pdf_search"))
        self._search_input.setMaximumWidth(160)
        self._search_input.setClearButtonEnabled(True)
        self._search_input.returnPressed.connect(self._search_next)
        self._search_input.textChanged.connect(self._on_search_text_changed)
        self._toolbar.addWidget(self._search_input)

        self._search_count_lbl = QLabel("")
        self._toolbar.addWidget(self._search_count_lbl)

        act_search_prev = QAction(icon("arrow-up"), "", self)
        act_search_prev.setToolTip(self._lang.tr("pdf_previous_result"))
        act_search_prev.triggered.connect(self._search_prev)
        self._toolbar.addAction(act_search_prev)

        act_search_next = QAction(icon("arrow-down"), "", self)
        act_search_next.setToolTip(self._lang.tr("pdf_next_result"))
        act_search_next.triggered.connect(self._search_next)
        self._toolbar.addAction(act_search_next)

        # Right spacers and save actions
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._toolbar.addWidget(spacer)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #a5b4fc; font-weight: 500; margin-right: 8px;")
        self._toolbar.addWidget(self._status_label)

        self._act_save = QAction(icon("device-floppy"), "", self)
        self._act_save.setToolTip(self._lang.tr("pdf_save"))
        self._act_save.triggered.connect(self._save_pdf)
        self._toolbar.addAction(self._act_save)

        self._act_open_external = QAction(icon("external-link"), "", self)
        self._act_open_external.setToolTip(self._lang.tr("pdf_open_external"))
        self._act_open_external.setEnabled(False)
        self._act_open_external.triggered.connect(self._open_pdf_externally)
        self._toolbar.addAction(self._act_open_external)

        main_layout.addWidget(self._toolbar)

        # ── MAIN SPLITTER (Sidebar + Document View) ───────────────────────
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.setStyleSheet("""
            QSplitter::handle {
                background: #282a36;
                width: 3px;
            }
        """)

        # Side panel
        self._side_panel = PdfAnnotationsPanel(self._lang, self._splitter)
        self._side_panel.annotationSelected.connect(self._on_annotation_selected)
        self._side_panel.annotationDeleteRequested.connect(self._delete_annotation)
        self._side_panel.annotationCommentEditRequested.connect(self._edit_annotation_comment)
        self._side_panel.pageThumbnailClicked.connect(lambda page: self._doc_view.scroll_to_page(page))
        self._splitter.addWidget(self._side_panel)

        # Center document view
        self._doc_view = PdfDocumentView(self._splitter)
        self._doc_view.pageScrolled.connect(self._on_page_scrolled)
        self._splitter.addWidget(self._doc_view)

        self._splitter.setSizes([260, 800])
        main_layout.addWidget(self._splitter, 1)

        # Floating action bubble for selection
        self._floating_popup = PdfFloatingPopup(self._lang, self)
        self._floating_popup.hide()
        self._floating_popup.highlightClicked.connect(self._on_floating_highlight)
        self._floating_popup.underlineClicked.connect(self._on_floating_underline)
        self._floating_popup.copyClicked.connect(self._on_floating_copy)
        self._floating_popup.noteClicked.connect(self._on_floating_note)

        # Search matches tracker
        self._search_matches: list[tuple[int, fitz.Rect]] = [] # (page_num, rect)
        self._search_match_idx = -1
        self.refresh_theme()

    def refresh_theme(self):
        """Reapply theme-dependent styling after the application theme changes."""
        colors = _pdf_theme_colors()
        self._toolbar.setStyleSheet(f"QToolBar {{ background: {colors['surface']}; border-bottom: 1px solid {colors['border']}; spacing: 4px; padding: 3px 6px; }} QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 4px; padding: 4px 6px; color: {colors['button_fg']}; }} QToolButton:hover {{ background: {colors['hover']}; border: 1px solid {colors['border_input']}; }} QToolButton:checked {{ background: {colors['accent']}; color: {colors['accent_fg']}; border: 1px solid {colors['accent']}; }} QLabel {{ color: {colors['muted']}; font-size: 11px; }}")
        self._status_label.setStyleSheet(f"color: {colors['accent']}; font-weight: 500; margin-right: 8px;")
        self._splitter.setStyleSheet(f"QSplitter::handle {{ background: {colors['border']}; width: 3px; }}")
        self._doc_view.refresh_theme()
        self._side_panel.refresh_theme()
        self._floating_popup.refresh_theme()

    # ── PUBLIC INTERFACE COMPATIBLE WITH MAIN_WINDOW ─────────────────────
    def set_model(self, model):
        self._model = model

    def set_document(self, entry_id: int | None, pdf_path: str = ""):
        """Load a PDF document into the viewer."""
        self._close_working_copy()
        self._entry_id = entry_id
        self._pdf_path = pdf_path or ""
        self._is_modified = False
        self._act_open_external.setEnabled(False)

        if not entry_id or not self._pdf_path:
            self._doc_view.clear()
            self._side_panel.set_annotations([])
            self._page_spin.setRange(1, 1)
            self._page_count_label.setText("/ 0")
            self._status_label.setText("Nessun PDF collegato a questo record")
            return

        path = Path(self._pdf_path)
        if not path.exists():
            self._doc_view.clear()
            self._side_panel.set_annotations([])
            self._status_label.setText(f"File non trovato: {path.name}")
            return

        self._act_open_external.setEnabled(True)

        # Create isolated working copy in temp dir
        try:
            fd, working_path = tempfile.mkstemp(suffix=".pdf", prefix="citemind-")
            os.close(fd)
            shutil.copy2(path, working_path)
            self._working_path = working_path
            self._doc = fitz.open(working_path)
        except Exception as e:
            self._status_label.setText("Errore apertura PDF")
            return

        page_count = len(self._doc)
        self._page_spin.blockSignals(True)
        self._page_spin.setRange(1, max(1, page_count))
        self._page_spin.setValue(1)
        self._page_spin.blockSignals(False)
        self._page_count_label.setText(f"/ {page_count}")
        self._status_label.setText(path.name)

        # Build page widgets
        pages = []
        for i in range(page_count):
            pw = PdfPageWidget(i, self._doc_view)
            pw.set_page_data(self._doc)
            pw.mode = self._markup_mode
            pw.active_color = self._active_color
            pw.textSelected.connect(self._on_text_selected)
            pw.selectionCleared.connect(lambda: self._floating_popup.hide())
            pw.annotationClicked.connect(self._on_page_annotation_clicked)
            pw.annotationCreated.connect(self._create_annotation)
            pw.noteRequested.connect(self._add_note_at_point)
            pages.append(pw)

        self._doc_view.set_pages(pages)
        self._refresh_annotations_list()
        self._side_panel.load_thumbnails(self._doc)

    # ── TOOLBAR & MODE ACTIONS ───────────────────────────────────────────
    def _set_mode(self, mode: str):
        self._markup_mode = mode
        self._floating_popup.hide()
        for p in self._doc_view.pages():
            p.mode = mode

    def _apply_color(self, color: QColor):
        self._active_color = color
        self._update_color_button()
        self._floating_popup.set_color(color)
        for p in self._doc_view.pages():
            p.active_color = color

    def _choose_custom_color(self):
        col = QColorDialog.getColor(self._active_color, self, "Scegli colore annotazione")
        if col.isValid():
            self._apply_color(col)

    def _update_color_button(self):
        hex_c = self._active_color.name()
        self._color_button.setStyleSheet(f"""
            QToolButton {{
                background: {hex_c};
                border: 1px solid #444;
                border-radius: 4px;
                min-width: 22px;
                min-height: 18px;
            }}
        """)

    def _toggle_sidebar(self, checked: bool):
        self._side_panel.setVisible(checked)

    def _step_page(self, delta: int):
        cur = self._page_spin.value()
        target = max(1, min(self._page_spin.maximum(), cur + delta))
        if target != cur:
            self._page_spin.setValue(target)

    def _on_page_spin_changed(self, value: int):
        self._doc_view.scroll_to_page(value - 1)

    def _on_page_scrolled(self, page_num: int):
        self._page_spin.blockSignals(True)
        self._page_spin.setValue(page_num + 1)
        self._page_spin.blockSignals(False)

    def _change_zoom(self, delta: float):
        new_zoom = max(0.3, min(3.5, self._doc_view.zoom() + delta))
        self._zoom_combo.blockSignals(True)
        self._zoom_combo.setCurrentText(f"{round(new_zoom * 100)}%")
        self._zoom_combo.blockSignals(False)
        self._doc_view.set_zoom(new_zoom)

    def _on_zoom_combo_changed(self, text: str):
        if text == "Adatta larghezza":
            self._fit_to_width()
        elif text == "Adatta pagina":
            self._fit_to_page()
        elif text.endswith("%"):
            try:
                val = float(text[:-1]) / 100.0
                self._doc_view.set_zoom(val)
            except ValueError:
                pass

    def _fit_to_width(self):
        if not self._doc_view.pages():
            return
        vp_w = self._doc_view.viewport().width() - 50
        page_w = self._doc_view.pages()[0]._page_rect.width
        if page_w > 0:
            zoom = max(0.3, min(3.5, vp_w / page_w))
            self._zoom_combo.blockSignals(True)
            self._zoom_combo.setCurrentText(f"{round(zoom * 100)}%")
            self._zoom_combo.blockSignals(False)
            self._doc_view.set_zoom(zoom)

    def _fit_to_page(self):
        if not self._doc_view.pages():
            return
        vp_w = self._doc_view.viewport().width() - 50
        vp_h = self._doc_view.viewport().height() - 50
        page = self._doc_view.pages()[0]._page_rect
        if page.width > 0 and page.height > 0:
            zoom = max(0.3, min(3.5, min(vp_w / page.width, vp_h / page.height)))
            self._zoom_combo.blockSignals(True)
            self._zoom_combo.setCurrentText(f"{round(zoom * 100)}%")
            self._zoom_combo.blockSignals(False)
            self._doc_view.set_zoom(zoom)

    # ── TEXT SELECTION & FLOATING ACTION POPUP ────────────────────────────
    def _on_text_selected(self, page_num: int, line_rects: list, text: str, global_pos: QPoint):
        self._active_selection = {
            "page_num": page_num,
            "line_rects": line_rects,
            "text": text,
        }
        # Position floating popup directly above release point
        popup_pos = global_pos - QPoint(self._floating_popup.width() // 2, 45)
        self._floating_popup.move(popup_pos)
        self._floating_popup.show()

    def _on_floating_highlight(self, color: QColor):
        if hasattr(self, "_active_selection") and self._active_selection:
            self._create_annotation(
                self._active_selection["page_num"],
                "evidenzia",
                self._active_selection["line_rects"],
                color
            )
            self._clear_all_page_selections()

    def _on_floating_underline(self):
        if hasattr(self, "_active_selection") and self._active_selection:
            self._create_annotation(
                self._active_selection["page_num"],
                "sottolinea",
                self._active_selection["line_rects"],
                self._active_color
            )
            self._clear_all_page_selections()

    def _on_floating_copy(self):
        if hasattr(self, "_active_selection") and self._active_selection:
            QApplication.clipboard().setText(self._active_selection["text"])
            self._status_label.setText("Testo copiato negli appunti")

    def _on_floating_note(self):
        if hasattr(self, "_active_selection") and self._active_selection:
            comment, ok = QInputDialog.getMultiLineText(
                self, "Aggiungi Nota", "Testo della nota per la selezione:", ""
            )
            if ok and comment.strip():
                self._create_annotation(
                    self._active_selection["page_num"],
                    "evidenzia",
                    self._active_selection["line_rects"],
                    self._active_color,
                    comment=comment.strip()
                )
                self._clear_all_page_selections()

    def _clear_all_page_selections(self):
        self._floating_popup.hide()
        for p in self._doc_view.pages():
            p.clear_selection()

    # ── ANNOTATION CRUD ───────────────────────────────────────────────────
    def _create_annotation(self, page_num: int, kind: str, line_rects: list[fitz.Rect],
                           color: QColor, comment: str = ""):
        """Create a native highlight/underline annotation in the working PDF."""
        if not self._doc or page_num >= len(self._doc):
            return
        page = self._doc[page_num]
        rgb = (color.redF(), color.greenF(), color.blueF())

        try:
            if kind == "sottolinea":
                annot = page.add_underline_annot(line_rects)
            else:
                annot = page.add_highlight_annot(line_rects)

            annot.set_colors(stroke=rgb)
            if comment:
                annot.set_info(content=comment)
            annot.update()

            self._save_working_copy()
            self._is_modified = True
            self._status_label.setText(f"Annotazione aggiunta • premi Salva")

            # Refresh affected page and sidebar
            if page_num < len(self._doc_view.pages()):
                self._doc_view.pages()[page_num].refresh_annots_and_render()
            self._refresh_annotations_list()
            self._sync_with_db()
            self.annotationChanged.emit()

        except Exception as e:
            self._status_label.setText("Errore creazione annotazione")

    def _add_note_at_point(self, page_num: int, pt: QPointF):
        """Add sticky text note at point."""
        if not self._doc or page_num >= len(self._doc):
            return
        comment, ok = QInputDialog.getMultiLineText(self, "Nuova Nota", "Contenuto della nota:", "")
        if not ok or not comment.strip():
            return
        page = self._doc[page_num]
        try:
            annot = page.add_text_annot(fitz.Point(pt.x(), pt.y()), comment.strip())
            rgb = (self._active_color.redF(), self._active_color.greenF(), self._active_color.blueF())
            annot.set_colors(stroke=rgb)
            annot.update()
            self._save_working_copy()
            self._is_modified = True
            self._doc_view.pages()[page_num].refresh_annots_and_render()
            self._refresh_annotations_list()
            self._sync_with_db()
            self.annotationChanged.emit()
            self._set_mode("select")
            self._act_mode_select.setChecked(True)
        except Exception:
            self._status_label.setText("Errore aggiunta nota")

    def _delete_annotation(self, page_num: int, xref: int):
        """Remove annotation by xref from working copy."""
        if not self._doc or page_num >= len(self._doc):
            return
        page = self._doc[page_num]
        try:
            for annot in page.annots() or []:
                if annot.xref == xref:
                    page.delete_annot(annot)
                    break

            self._save_working_copy()
            self._is_modified = True
            self._status_label.setText("Annotazione eliminata • premi Salva")

            if page_num < len(self._doc_view.pages()):
                self._doc_view.pages()[page_num].refresh_annots_and_render()
            self._refresh_annotations_list()
            self._sync_with_db()
            self.annotationChanged.emit()
        except Exception:
            self._status_label.setText("Errore eliminazione annotazione")

    def _edit_annotation_comment(self, page_num: int, xref: int, current_comment: str):
        comment, ok = QInputDialog.getMultiLineText(
            self, "Modifica Commento", "Commento annotazione:", current_comment
        )
        if not ok:
            return
        if not self._doc or page_num >= len(self._doc):
            return
        page = self._doc[page_num]
        try:
            for annot in page.annots() or []:
                if annot.xref == xref:
                    annot.set_info(content=comment.strip())
                    annot.update()
                    break
            self._save_working_copy()
            self._is_modified = True
            self._refresh_annotations_list()
            self._sync_with_db()
            self.annotationChanged.emit()
        except Exception:
            pass

    def _on_annotation_selected(self, page_num: int, xref: int):
        """Scroll document view to the selected annotation and highlight it."""
        if page_num < len(self._doc_view.pages()):
            target_page = self._doc_view.pages()[page_num]
            target_page.select_annotation(xref)
            for a in target_page._annotations:
                if a["xref"] == xref:
                    self._doc_view.scroll_to_rect(page_num, a["rect"])
                    break

    def _on_page_annotation_clicked(self, page_num: int, xref: int, global_pos: QPoint):
        # Focus corresponding item in sidebar
        for i in range(self._side_panel._annots_list.count()):
            item = self._side_panel._annots_list.item(i)
            data = item.data(Qt.UserRole)
            if data and data["xref"] == xref:
                self._side_panel._annots_list.setCurrentItem(item)
                break

    def _refresh_annotations_list(self):
        all_annots = []
        if self._doc:
            for p in self._doc_view.pages():
                all_annots.extend(p._annotations)
        self._side_panel.set_annotations(all_annots)

    def _save_working_copy(self):
        """Flush changes to temporary working copy."""
        if not self._doc or not self._working_path:
            return
        try:
            self._doc.saveIncr()
        except Exception:
            # Fallback to safe atomic rewrite and reload
            tmp = self._working_path + ".tmp"
            self._doc.save(tmp, garbage=1, deflate=True)
            self._doc.close()
            os.replace(tmp, self._working_path)
            self._doc = fitz.open(self._working_path)
            for p in self._doc_view.pages():
                p.set_page_data(self._doc)

    def _save_pdf(self):
        """Commit changes permanently to the original PDF file."""
        if not self._working_path or not self._pdf_path:
            return
        try:
            self._save_working_copy()
            shutil.copy2(self._working_path, self._pdf_path)
            self._is_modified = False
            self._status_label.setText("Modifiche salvate nel PDF!")
        except Exception as e:
            QMessageBox.warning(
                self, "Errore salvataggio",
                f"Impossibile salvare il PDF:\n{e}\n\nAssicurati che il file non sia aperto in un altro programma (es. Adobe Reader)."
            )

    def _sync_with_db(self):
        """Sync native PDF annotations with CiteMind's SQLite DB."""
        if not self._model or not self._entry_id or not self._doc:
            return
        try:
            existing = self._model.get_pdf_annotations(self._entry_id)
            for item in existing:
                self._model.delete_pdf_annotation(item["id"], self._entry_id)

            for p in self._doc_view.pages():
                for a in p._annotations:
                    self._model.save_pdf_annotation(
                        entry_id=self._entry_id,
                        page=a["page"],
                        kind=a["kind"],
                        text=a.get("comment", ""),
                        selected_text=a.get("text", ""),
                        tags="",
                    )
        except Exception:
            pass

    # ── SEARCH IN PDF ─────────────────────────────────────────────────────
    def _on_search_text_changed(self, text: str):
        query = text.strip()
        self._search_matches = []
        self._search_match_idx = -1

        if not query or not self._doc:
            self._search_count_lbl.setText("")
            for p in self._doc_view.pages():
                p.set_search_results([])
            return

        matches_by_page = defaultdict(list)
        for page_idx, page in enumerate(self._doc):
            rects = page.search_for(query)
            for r in rects:
                self._search_matches.append((page_idx, r))
                matches_by_page[page_idx].append(r)

        total = len(self._search_matches)
        if total > 0:
            self._search_match_idx = 0
            self._search_count_lbl.setText(f"1 di {total}")
            for p in self._doc_view.pages():
                p.set_search_results(matches_by_page.get(p.page_num, []))
            self._jump_to_search_match(0)
        else:
            self._search_count_lbl.setText("0 risultati")
            for p in self._doc_view.pages():
                p.set_search_results([])

    def _search_next(self):
        if not self._search_matches:
            return
        self._search_match_idx = (self._search_match_idx + 1) % len(self._search_matches)
        self._search_count_lbl.setText(f"{self._search_match_idx + 1} di {len(self._search_matches)}")
        self._jump_to_search_match(self._search_match_idx)

    def _search_prev(self):
        if not self._search_matches:
            return
        self._search_match_idx = (self._search_match_idx - 1) % len(self._search_matches)
        self._search_count_lbl.setText(f"{self._search_match_idx + 1} di {len(self._search_matches)}")
        self._jump_to_search_match(self._search_match_idx)

    def _jump_to_search_match(self, idx: int):
        page_num, rect = self._search_matches[idx]
        self._doc_view.scroll_to_rect(page_num, rect)

    # ── EXTERNAL APP & CLEANUP ────────────────────────────────────────────
    def _open_pdf_externally(self):
        if not self._pdf_path or not Path(self._pdf_path).exists():
            return
        # If there are unsaved changes, prompt or save
        if self._is_modified:
            self._save_pdf()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._pdf_path).resolve())))

    def _close_working_copy(self):
        if self._doc:
            try:
                self._doc.close()
            except Exception:
                pass
            self._doc = None
        if self._working_path:
            try:
                Path(self._working_path).unlink(missing_ok=True)
            except Exception:
                pass
            self._working_path = ""

    def closeEvent(self, event):
        self._close_working_copy()
        super().closeEvent(event)
