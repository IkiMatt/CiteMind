"""
theme.py — Token-based design system, icon engine, QSS generation, and ThemeManager.

Architecture:
  DesignTokens   – @dataclass holding every colour / spacing / radius value
  *_TOKENS       – four preset instances (dark, light, terminal, ebook)
  _build_qss()   – single Jinja-free template function  tokens → QSS string
  ThemeManager    – public API  (unchanged from the original)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt, Signal, QObject, QSettings, QFile, QIODevice, QRectF, QSizeF, QPointF
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# ── module-level state (shared with all modules that call icon()) ──────────────
_icon_cache: dict = {}
_global_theme: str = "dark"


def get_global_theme() -> str:
    return _global_theme


def set_global_theme(name: str) -> None:
    global _global_theme
    _global_theme = name


# ─────────────────────────────────────────────────────────────────────────────
#  ICON ENGINE  (unchanged)
# ─────────────────────────────────────────────────────────────────────────────
class ThemeAwareIconEngine(QIconEngine):
    def __init__(self, name: str):
        super().__init__()
        self.name = name

    def paint(self, painter: QPainter, rect, mode, state):
        theme = _global_theme
        if theme == "terminal":
            color_hex = "#00ff41"
        elif theme == "ebook":
            color_hex = "#4a3a24"
        elif theme == "light":
            color_hex = "#434360"
        else:
            color_hex = "#c0c0e0"
        cache_key = f"{self.name}_{color_hex}"

        if cache_key not in _icon_cache:
            icon_dir = Path(__file__).resolve().parent.parent / "icon"
            svg_path = icon_dir / f"{self.name}.svg"
            png_path = icon_dir / f"{self.name}.png"

            if png_path.exists():
                pixmap = QPixmap(str(png_path))
                _icon_cache[cache_key] = pixmap if not pixmap.isNull() else None
            elif svg_path.exists():
                try:
                    xml = svg_path.read_text(encoding="utf-8")
                    xml = xml.replace("currentColor", color_hex)
                    _icon_cache[cache_key] = QSvgRenderer(xml.encode("utf-8"))
                except Exception:
                    _icon_cache[cache_key] = QSvgRenderer(str(svg_path))
            else:
                file = QFile(f":/icon/{self.name}.svg")
                if file.open(QIODevice.ReadOnly):
                    xml = file.readAll().data().decode("utf-8")
                    file.close()
                    xml = xml.replace("currentColor", color_hex)
                    _icon_cache[cache_key] = QSvgRenderer(xml.encode("utf-8"))
                else:
                    _icon_cache[cache_key] = None

        renderer = _icon_cache[cache_key]
        if renderer:
            painter.setRenderHint(QPainter.Antialiasing)
            if isinstance(renderer, QPixmap):
                painter.drawPixmap(rect, renderer.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                source_size = renderer.defaultSize()
                target = QRectF(rect)
                if source_size.isValid() and source_size.width() > 0 and source_size.height() > 0:
                    target.setSize(QSizeF(source_size).scaled(rect.size(), Qt.KeepAspectRatio))
                    target.moveCenter(QPointF(rect.center()))
                renderer.render(painter, target)

    def clone(self):
        return ThemeAwareIconEngine(self.name)

    def pixmap(self, size, mode, state):
        pm = QPixmap(size)
        pm.fill(Qt.transparent)
        painter = QPainter(pm)
        self.paint(painter, pm.rect(), mode, state)
        painter.end()
        return pm


def icon(name: str) -> QIcon:
    """Load an SVG icon from the compiled resources, auto-colored for the active theme."""
    return QIcon(ThemeAwareIconEngine(name))


# ─────────────────────────────────────────────────────────────────────────────
#  DESIGN TOKENS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class DesignTokens:
    """Every visual value that varies between themes lives here."""

    # ── base / canvas ────────────────────────────────────────────────────
    bg_base: str                  # QMainWindow / QDialog / QWidget background
    fg_base: str                  # primary text colour

    # ── surface layers ───────────────────────────────────────────────────
    bg_surface: str               # toolbar, panels  (slightly raised)
    bg_input: str                 # text inputs, list widgets
    bg_input_focus: str           # inputs when focused
    bg_elevated: str              # status-bar, group-box title bg

    # ── borders / dividers ───────────────────────────────────────────────
    border: str                   # default 1px borders
    border_input: str             # input-field borders (may differ from `border`)
    border_focus: str             # focused input border accent

    # ── splitter ─────────────────────────────────────────────────────────
    splitter: str

    # ── toolbar ──────────────────────────────────────────────────────────
    toolbar_btn_fg: str
    toolbar_btn_hover_bg: str
    toolbar_btn_hover_fg: str
    toolbar_btn_pressed_bg: str

    # ── search bar ───────────────────────────────────────────────────────
    search_bg: str
    search_border: str
    search_fg: str

    # ── list widget ──────────────────────────────────────────────────────
    list_item_fg: str
    list_item_selected_bg: str
    list_item_selected_fg: str
    list_item_selected_border: str
    list_item_hover_bg: str
    list_item_alternate_bg: str

    # ── selection highlight (text) ───────────────────────────────────────
    selection_bg: str

    # ── combo-box dropdown view ──────────────────────────────────────────
    combo_dropdown_bg: str
    combo_dropdown_border: str
    combo_dropdown_selection: str
    combo_dropdown_fg: str

    # ── buttons ──────────────────────────────────────────────────────────
    btn_bg: str
    btn_border: str
    btn_fg: str
    btn_hover_bg: str
    btn_hover_border: str
    btn_hover_fg: str
    btn_pressed_bg: str

    btn_primary_bg: str
    btn_primary_border: str
    btn_primary_fg: str
    btn_primary_hover_bg: str

    btn_danger_bg: str
    btn_danger_border: str
    btn_danger_fg: str
    btn_danger_hover_bg: str

    # ── labels ───────────────────────────────────────────────────────────
    section_title_fg: str
    entry_count_bg: str
    entry_count_fg: str
    autosave_fg: str

    # ── tabs ─────────────────────────────────────────────────────────────
    tab_pane_border: str
    tab_pane_bg: str
    tab_fg: str
    tab_selected_bg: str
    tab_selected_fg: str
    tab_hover_bg: str
    tab_hover_fg: str

    # ── group box ────────────────────────────────────────────────────────
    groupbox_border: str
    groupbox_fg: str
    groupbox_title_bg: str       # small bg pill behind group-box title

    # ── scrollbar ────────────────────────────────────────────────────────
    scrollbar_bg: str
    scrollbar_handle: str

    # ── status bar ───────────────────────────────────────────────────────
    statusbar_bg: str
    statusbar_border: str
    statusbar_fg: str

    # ── tooltip ──────────────────────────────────────────────────────────
    tooltip_bg: str
    tooltip_fg: str
    tooltip_border: str

    # ── menu ─────────────────────────────────────────────────────────────
    menu_bg: str
    menu_border: str
    menu_item_fg: str
    menu_item_selected_bg: str
    menu_item_selected_fg: str

    # ── tree widget ──────────────────────────────────────────────────────
    tree_bg: str
    tree_item_fg: str
    tree_item_selected_bg: str
    tree_item_selected_fg: str
    tree_branch_fg: str

    # ── header view ──────────────────────────────────────────────────────
    header_bg: str
    header_fg: str
    header_border: str

    # ── progress bar ─────────────────────────────────────────────────────
    progress_bg: str
    progress_chunk: str
    progress_fg: str

    # ── checkbox ─────────────────────────────────────────────────────────
    checkbox_indicator_bg: str
    checkbox_indicator_border: str
    checkbox_indicator_checked_bg: str
    checkbox_indicator_checked_border: str
    checkbox_checkmark_fg: str

    # ── slider ───────────────────────────────────────────────────────────
    slider_groove_bg: str
    slider_handle_bg: str
    slider_handle_border: str
    slider_sub_page: str          # "filled" part before handle

    # ── list category colours (bibliography / sitography / tesi) ─────────
    list_colors: dict = field(default_factory=dict)

    # ── icons ────────────────────────────────────────────────────────────
    icon_color: str = "#c0c0e0"


# ─────────────────────────────────────────────────────────────────────────────
#  TOKEN PRESETS
# ─────────────────────────────────────────────────────────────────────────────

DARK_TOKENS = DesignTokens(
    # base
    bg_base="#12131a", fg_base="#e0e0f0",
    # surfaces
    bg_surface="#1a1b26", bg_input="#1e1f2e",
    bg_input_focus="#222338", bg_elevated="#12131a",
    # borders
    border="#2a2b38", border_input="#3a3b4e", border_focus="#7c3aed",
    # splitter
    splitter="#2a2b38",
    # toolbar
    toolbar_btn_fg="#a0a0c0",
    toolbar_btn_hover_bg="#2a2b38", toolbar_btn_hover_fg="#c792ea",
    toolbar_btn_pressed_bg="#363748",
    # search
    search_bg="#1e1f2e", search_border="#3a3b4e", search_fg="#e0e0f0",
    # list
    list_item_fg="#c0c0e0",
    list_item_selected_bg="#2d2f4a", list_item_selected_fg="#e0e0ff",
    list_item_selected_border="#7c3aed", list_item_hover_bg="#222336",
    list_item_alternate_bg="#202131",
    # selection
    selection_bg="#4a1d96",
    # combo dropdown
    combo_dropdown_bg="#1e1f2e", combo_dropdown_border="#3a3b4e",
    combo_dropdown_selection="#4a1d96", combo_dropdown_fg="#e0e0f0",
    # buttons
    btn_bg="#2a2b3d", btn_border="#3a3b4e", btn_fg="#c0c0e0",
    btn_hover_bg="#353650", btn_hover_border="#7c3aed", btn_hover_fg="#e0e0ff",
    btn_pressed_bg="#282938",
    btn_primary_bg="#5b21b6", btn_primary_border="#7c3aed", btn_primary_fg="#fff",
    btn_primary_hover_bg="#6d28d9",
    btn_danger_bg="#4c0519", btn_danger_border="#9f1239", btn_danger_fg="#fca5a5",
    btn_danger_hover_bg="#6b0c26",
    # labels
    section_title_fg="#6b6b9a",
    entry_count_bg="#2d1b69", entry_count_fg="#a78bfa",
    autosave_fg="#34d399",
    # tabs
    tab_pane_border="#2a2b38", tab_pane_bg="#15162080",
    tab_fg="#6b6b9a",
    tab_selected_bg="#2a2b38", tab_selected_fg="#a78bfa",
    tab_hover_bg="#1e1f2e", tab_hover_fg="#c0c0e0",
    # group box
    groupbox_border="#2a2b38", groupbox_fg="#7878a8",
    groupbox_title_bg="#12131a",
    # scrollbar
    scrollbar_bg="#1a1b26", scrollbar_handle="#3a3b5e",
    # statusbar
    statusbar_bg="#0e0f18", statusbar_border="#2a2b38", statusbar_fg="#6b6b9a",
    # tooltip
    tooltip_bg="#1e1f2e", tooltip_fg="#e0e0f0", tooltip_border="#3a3b4e",
    # menu
    menu_bg="#1e1f2e", menu_border="#3a3b4e",
    menu_item_fg="#c0c0e0",
    menu_item_selected_bg="#2d2f4a", menu_item_selected_fg="#e0e0ff",
    # tree widget
    tree_bg="#1a1b26", tree_item_fg="#c0c0e0",
    tree_item_selected_bg="#2d2f4a", tree_item_selected_fg="#e0e0ff",
    tree_branch_fg="#3a3b5e",
    # header view
    header_bg="#1a1b26", header_fg="#a0a0c0", header_border="#2a2b38",
    # progress bar
    progress_bg="#1e1f2e", progress_chunk="#5b21b6", progress_fg="#e0e0f0",
    # checkbox
    checkbox_indicator_bg="#1e1f2e", checkbox_indicator_border="#3a3b4e",
    checkbox_indicator_checked_bg="#5b21b6", checkbox_indicator_checked_border="#7c3aed",
    checkbox_checkmark_fg="#ffffff",
    # slider
    slider_groove_bg="#1e1f2e", slider_handle_bg="#5b21b6",
    slider_handle_border="#7c3aed", slider_sub_page="#7c3aed",
    # list category colours
    list_colors={
        "bibliography": "#9d4edd", "sitography": "#0096c7", "tesi": "#f59e0b",
        "article": "#c084fc", "book": "#34d399", "chapter": "#60a5fa",
        "conference": "#fb7185", "report": "#fbbf24", "web": "#22d3ee",
    },
    # icon color
    icon_color="#c0c0e0",
)

LIGHT_TOKENS = DesignTokens(
    # base
    bg_base="#f5f5f8", fg_base="#23243a",
    # surfaces
    bg_surface="#eaeaf0", bg_input="#ffffff",
    bg_input_focus="#faf8ff", bg_elevated="#f5f5f8",
    # borders
    border="#d4d4dc", border_input="#c4c4d4", border_focus="#7c3aed",
    # splitter
    splitter="#d4d4dc",
    # toolbar
    toolbar_btn_fg="#555580",
    toolbar_btn_hover_bg="#dcdce8", toolbar_btn_hover_fg="#6d28d9",
    toolbar_btn_pressed_bg="#cbcbd8",
    # search
    search_bg="#ffffff", search_border="#c4c4d4", search_fg="#23243a",
    # list
    list_item_fg="#333360",
    list_item_selected_bg="#f3edff", list_item_selected_fg="#23243a",
    list_item_selected_border="#c4a7f5", list_item_hover_bg="#f0f0f8",
    list_item_alternate_bg="#f3edff",
    # selection
    selection_bg="#c4b5fd",
    # combo dropdown
    combo_dropdown_bg="#ffffff", combo_dropdown_border="#c4c4d4",
    combo_dropdown_selection="#c4b5fd", combo_dropdown_fg="#23243a",
    # buttons
    btn_bg="#e4e4f0", btn_border="#c4c4d4", btn_fg="#333360",
    btn_hover_bg="#d8d8ee", btn_hover_border="#7c3aed", btn_hover_fg="#23243a",
    btn_pressed_bg="#cdcde0",
    btn_primary_bg="#7c3aed", btn_primary_border="#6d28d9", btn_primary_fg="#fff",
    btn_primary_hover_bg="#6d28d9",
    btn_danger_bg="#fee2e2", btn_danger_border="#f87171", btn_danger_fg="#b91c1c",
    btn_danger_hover_bg="#fecaca",
    # labels
    section_title_fg="#8888a8",
    entry_count_bg="#e8e0ff", entry_count_fg="#6d28d9",
    autosave_fg="#059669",
    # tabs
    tab_pane_border="#d4d4dc", tab_pane_bg="#fafafc",
    tab_fg="#8888a8",
    tab_selected_bg="#e8e0ff", tab_selected_fg="#6d28d9",
    tab_hover_bg="#f0f0f8", tab_hover_fg="#555580",
    # group box
    groupbox_border="#d4d4dc", groupbox_fg="#8888a8",
    groupbox_title_bg="#f5f5f8",
    # scrollbar
    scrollbar_bg="#f0f0f4", scrollbar_handle="#c4c4d8",
    # statusbar
    statusbar_bg="#eaeaf0", statusbar_border="#d4d4dc", statusbar_fg="#8888a8",
    # tooltip
    tooltip_bg="#ffffff", tooltip_fg="#23243a", tooltip_border="#c4c4d4",
    # menu
    menu_bg="#ffffff", menu_border="#c4c4d4",
    menu_item_fg="#333360",
    menu_item_selected_bg="#e8e0ff", menu_item_selected_fg="#23243a",
    # tree widget
    tree_bg="#ffffff", tree_item_fg="#333360",
    tree_item_selected_bg="#e8e0ff", tree_item_selected_fg="#23243a",
    tree_branch_fg="#c4c4d8",
    # header view
    header_bg="#eaeaf0", header_fg="#555580", header_border="#d4d4dc",
    # progress bar
    progress_bg="#e4e4f0", progress_chunk="#7c3aed", progress_fg="#23243a",
    # checkbox
    checkbox_indicator_bg="#ffffff", checkbox_indicator_border="#c4c4d4",
    checkbox_indicator_checked_bg="#7c3aed", checkbox_indicator_checked_border="#6d28d9",
    checkbox_checkmark_fg="#ffffff",
    # slider
    slider_groove_bg="#e4e4f0", slider_handle_bg="#7c3aed",
    slider_handle_border="#6d28d9", slider_sub_page="#7c3aed",
    # list category colours
    list_colors={
        "bibliography": "#7c3aed", "sitography": "#0077b6", "tesi": "#d97706",
        "article": "#9333ea", "book": "#059669", "chapter": "#2563eb",
        "conference": "#e11d48", "report": "#b45309", "web": "#0891b2",
    },
    # icon color
    icon_color="#434360",
)

TERMINAL_TOKENS = DesignTokens(
    # base
    bg_base="#0a0a0a", fg_base="#00ff41",
    # surfaces
    bg_surface="#0d0d0d", bg_input="#111111",
    bg_input_focus="#0f1a0f", bg_elevated="#0a0a0a",
    # borders
    border="#1a3a1a", border_input="#1a3a1a", border_focus="#00ff41",
    # splitter
    splitter="#1a3a1a",
    # toolbar
    toolbar_btn_fg="#00cc33",
    toolbar_btn_hover_bg="#1a3a1a", toolbar_btn_hover_fg="#00ff41",
    toolbar_btn_pressed_bg="#0f2a0f",
    # search
    search_bg="#111111", search_border="#1a3a1a", search_fg="#00ff41",
    # list
    list_item_fg="#00cc33",
    list_item_selected_bg="#1a3a1a", list_item_selected_fg="#00ff41",
    list_item_selected_border="#00ff41", list_item_hover_bg="#111a11",
    list_item_alternate_bg="#101f10",
    # selection
    selection_bg="#1a5a1a",
    # combo dropdown
    combo_dropdown_bg="#111111", combo_dropdown_border="#1a3a1a",
    combo_dropdown_selection="#1a5a1a", combo_dropdown_fg="#00ff41",
    # buttons
    btn_bg="#151515", btn_border="#1a3a1a", btn_fg="#00cc33",
    btn_hover_bg="#1a3a1a", btn_hover_border="#00ff41", btn_hover_fg="#00ff41",
    btn_pressed_bg="#0f2a0f",
    btn_primary_bg="#0a4a0a", btn_primary_border="#00ff41", btn_primary_fg="#00ff41",
    btn_primary_hover_bg="#0f5a0f",
    btn_danger_bg="#3a0a0a", btn_danger_border="#ff4444", btn_danger_fg="#ff6666",
    btn_danger_hover_bg="#4a0f0f",
    # labels
    section_title_fg="#008822",
    entry_count_bg="#1a3a1a", entry_count_fg="#00ff41",
    autosave_fg="#00ff41",
    # tabs
    tab_pane_border="#1a3a1a", tab_pane_bg="#0d0d0d80",
    tab_fg="#008822",
    tab_selected_bg="#1a3a1a", tab_selected_fg="#00ff41",
    tab_hover_bg="#111a11", tab_hover_fg="#00cc33",
    # group box
    groupbox_border="#1a3a1a", groupbox_fg="#008822",
    groupbox_title_bg="#0a0a0a",
    # scrollbar
    scrollbar_bg="#0d0d0d", scrollbar_handle="#1a3a1a",
    # statusbar
    statusbar_bg="#080808", statusbar_border="#1a3a1a", statusbar_fg="#008822",
    # tooltip
    tooltip_bg="#111111", tooltip_fg="#00ff41", tooltip_border="#1a3a1a",
    # menu
    menu_bg="#111111", menu_border="#1a3a1a",
    menu_item_fg="#00cc33",
    menu_item_selected_bg="#1a3a1a", menu_item_selected_fg="#00ff41",
    # tree widget
    tree_bg="#0d0d0d", tree_item_fg="#00cc33",
    tree_item_selected_bg="#1a3a1a", tree_item_selected_fg="#00ff41",
    tree_branch_fg="#1a3a1a",
    # header view
    header_bg="#0d0d0d", header_fg="#00cc33", header_border="#1a3a1a",
    # progress bar
    progress_bg="#151515", progress_chunk="#0a4a0a", progress_fg="#00ff41",
    # checkbox
    checkbox_indicator_bg="#111111", checkbox_indicator_border="#1a3a1a",
    checkbox_indicator_checked_bg="#0a4a0a", checkbox_indicator_checked_border="#00ff41",
    checkbox_checkmark_fg="#00ff41",
    # slider
    slider_groove_bg="#151515", slider_handle_bg="#0a4a0a",
    slider_handle_border="#00ff41", slider_sub_page="#00ff41",
    # list category colours
    list_colors={
        "bibliography": "#00cc33", "sitography": "#00aaff", "tesi": "#ffaa00",
        "article": "#cc66ff", "book": "#00dd88", "chapter": "#66bbff",
        "conference": "#ff6688", "report": "#ffcc33", "web": "#00dddd",
    },
    # icon color
    icon_color="#00ff41",
)

EBOOK_TOKENS = DesignTokens(
    # base
    bg_base="#f8f4e8", fg_base="#2c2416",
    # surfaces
    bg_surface="#f0e8d4", bg_input="#fffdf5",
    bg_input_focus="#fffef8", bg_elevated="#f8f4e8",
    # borders
    border="#d8ceb8", border_input="#d0c4a8", border_focus="#8b6914",
    # splitter
    splitter="#d8ceb8",
    # toolbar
    toolbar_btn_fg="#5c4a32",
    toolbar_btn_hover_bg="#e8dcc4", toolbar_btn_hover_fg="#3a2810",
    toolbar_btn_pressed_bg="#d8ccb4",
    # search
    search_bg="#fffdf5", search_border="#d0c4a8", search_fg="#2c2416",
    # list
    list_item_fg="#3a3020",
    list_item_selected_bg="#ead8b8", list_item_selected_fg="#2c2416",
    list_item_selected_border="#9a7440", list_item_hover_bg="#f5eeda",
    list_item_alternate_bg="#ead8b8",
    # selection
    selection_bg="#e8d8a8",
    # combo dropdown
    combo_dropdown_bg="#fffdf5", combo_dropdown_border="#d0c4a8",
    combo_dropdown_selection="#e8d8a8", combo_dropdown_fg="#2c2416",
    # buttons
    btn_bg="#f0e4c8", btn_border="#d0c4a8", btn_fg="#3a3020",
    btn_hover_bg="#e8dab8", btn_hover_border="#8b6914", btn_hover_fg="#2c2416",
    btn_pressed_bg="#ddd0a8",
    btn_primary_bg="#8b6914", btn_primary_border="#7a5a10", btn_primary_fg="#fff",
    btn_primary_hover_bg="#7a5a10",
    btn_danger_bg="#f8e0d0", btn_danger_border="#c0603a", btn_danger_fg="#8b3018",
    btn_danger_hover_bg="#f0d0bc",
    # labels
    section_title_fg="#8a7a5a",
    entry_count_bg="#f0e4c8", entry_count_fg="#7a5a10",
    autosave_fg="#4a8030",
    # tabs
    tab_pane_border="#d8ceb8", tab_pane_bg="#faf6ea",
    tab_fg="#8a7a5a",
    tab_selected_bg="#f0e4c8", tab_selected_fg="#7a5a10",
    tab_hover_bg="#f5eeda", tab_hover_fg="#5c4a32",
    # group box
    groupbox_border="#d8ceb8", groupbox_fg="#8a7a5a",
    groupbox_title_bg="#f8f4e8",
    # scrollbar
    scrollbar_bg="#f0ead8", scrollbar_handle="#c8b890",
    # statusbar
    statusbar_bg="#f0e8d4", statusbar_border="#d8ceb8", statusbar_fg="#8a7a5a",
    # tooltip
    tooltip_bg="#fffdf5", tooltip_fg="#2c2416", tooltip_border="#d0c4a8",
    # menu
    menu_bg="#fffdf5", menu_border="#d0c4a8",
    menu_item_fg="#3a3020",
    menu_item_selected_bg="#f0e4c8", menu_item_selected_fg="#2c2416",
    # tree widget
    tree_bg="#fffdf5", tree_item_fg="#3a3020",
    tree_item_selected_bg="#f0e4c8", tree_item_selected_fg="#2c2416",
    tree_branch_fg="#c8b890",
    # header view
    header_bg="#f0e8d4", header_fg="#5c4a32", header_border="#d8ceb8",
    # progress bar
    progress_bg="#f0e4c8", progress_chunk="#8b6914", progress_fg="#2c2416",
    # checkbox
    checkbox_indicator_bg="#fffdf5", checkbox_indicator_border="#d0c4a8",
    checkbox_indicator_checked_bg="#8b6914", checkbox_indicator_checked_border="#7a5a10",
    checkbox_checkmark_fg="#ffffff",
    # slider
    slider_groove_bg="#f0e4c8", slider_handle_bg="#8b6914",
    slider_handle_border="#7a5a10", slider_sub_page="#8b6914",
    # list category colours
    list_colors={
        "bibliography": "#6a4c93", "sitography": "#3a6ea5", "tesi": "#8b6914",
        "article": "#8055a8", "book": "#3f8060", "chapter": "#4f78a8",
        "conference": "#a65363", "report": "#9b7620", "web": "#3a7f8f",
    },
    # icon color
    icon_color="#4a3a24",
)


# ─────────────────────────────────────────────────────────────────────────────
#  QSS BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def _build_qss(t: DesignTokens, font_family: str) -> str:
    """Generate a complete QSS stylesheet from a *DesignTokens* instance."""
    return f"""
/* ── Base ───────────────────────────────────────────────────────── */
QMainWindow, QDialog, QWidget {{
    background-color: {t.bg_base};
    color: {t.fg_base};
    font-family: {font_family};
    font-size: 13px;
}}

/* ── Splitter ───────────────────────────────────────────────────── */
QSplitter::handle {{ background: {t.splitter}; width: 2px; }}

/* ── Toolbar ────────────────────────────────────────────────────── */
QToolBar {{
    background: {t.bg_surface};
    border-bottom: 1px solid {t.border};
    spacing: 4px; padding: 4px 8px;
}}
QToolBar QToolButton {{
    background: transparent; border: none;
    border-radius: 6px; padding: 6px; color: {t.toolbar_btn_fg};
}}
QToolBar QToolButton:hover  {{ background: {t.toolbar_btn_hover_bg}; color: {t.toolbar_btn_hover_fg}; }}
QToolBar QToolButton:pressed{{ background: {t.toolbar_btn_pressed_bg}; }}

/* ── Search bar ─────────────────────────────────────────────────── */
QLineEdit#searchBar {{
    background: {t.search_bg}; border: 1px solid {t.search_border};
    border-radius: 18px; padding: 4px 12px;
    color: {t.search_fg}; min-width: 200px;
}}
QLineEdit#searchBar:focus {{ border-color: {t.border_focus}; }}

/* ── List widget ────────────────────────────────────────────────── */
QListWidget {{
    background: {t.bg_surface}; alternate-background-color: {t.list_item_alternate_bg};
    border: none; outline: none; padding: 4px;
}}
QListWidget::item {{
    border-radius: 6px; padding: 8px 10px; margin: 2px 0; color: {t.list_item_fg};
}}
QListWidget::item:selected {{
    background: {t.list_item_selected_bg}; color: {t.list_item_selected_fg}; border-left: 3px solid {t.list_item_selected_border};
}}
QListWidget::item:hover:!selected {{ background: {t.list_item_hover_bg}; }}

/* ── Input controls ─────────────────────────────────────────────── */
QLineEdit, QTextEdit, QDateEdit, QComboBox, QSpinBox {{
    background: {t.bg_input}; border: 1px solid {t.border_input};
    border-radius: 6px; padding: 5px 8px;
    color: {t.fg_base}; selection-background-color: {t.selection_bg};
}}
QLineEdit:focus, QTextEdit:focus, QDateEdit:focus,
QComboBox:focus, QSpinBox:focus {{
    border-color: {t.border_focus}; background: {t.bg_input_focus};
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {t.combo_dropdown_bg}; border: 1px solid {t.combo_dropdown_border};
    selection-background-color: {t.combo_dropdown_selection}; color: {t.combo_dropdown_fg};
}}

/* ── Push buttons ───────────────────────────────────────────────── */
QPushButton {{
    background: {t.btn_bg}; border: 1px solid {t.btn_border};
    border-radius: 7px; padding: 7px 18px;
    color: {t.btn_fg}; font-weight: 500;
}}
QPushButton:hover  {{ background: {t.btn_hover_bg}; border-color: {t.btn_hover_border}; color: {t.btn_hover_fg}; }}
QPushButton:pressed{{ background: {t.btn_pressed_bg}; }}
QPushButton#btnPrimary {{
    background: {t.btn_primary_bg}; border-color: {t.btn_primary_border}; color: {t.btn_primary_fg};
}}
QPushButton#btnPrimary:hover  {{ background: {t.btn_primary_hover_bg}; }}
QPushButton#btnDanger {{
    background: {t.btn_danger_bg}; border-color: {t.btn_danger_border}; color: {t.btn_danger_fg};
}}
QPushButton#btnDanger:hover  {{ background: {t.btn_danger_hover_bg}; }}

/* ── Labels ─────────────────────────────────────────────────────── */
QLabel#sectionTitle {{
    font-size: 11px; font-weight: 600; color: {t.section_title_fg};
    letter-spacing: 1px; text-transform: uppercase;
}}
QLabel#entryCount {{
    background: {t.entry_count_bg}; color: {t.entry_count_fg};
    border-radius: 10px; padding: 2px 10px;
    font-size: 11px; font-weight: 700;
}}
QLabel#autosaveLabel {{ color: {t.autosave_fg}; font-size: 11px; }}

/* ── Startup Dialog ─────────────────────────────────────────────── */
QWidget#startupHeader {{
    background: {t.bg_surface};
    border-bottom: 2px solid {t.border};
}}
QLabel#startupTitle {{
    color: {t.fg_base}; letter-spacing: 1px;
}}
QLabel#startupSubtitle {{
    color: {t.section_title_fg};
}}
QLabel#startupAuthor {{
    color: {t.btn_primary_bg}; margin-top: 4px; font-style: italic;
}}
QWidget#startupBody {{
    background: {t.bg_base};
}}
QLabel#startupProjectTitle {{
    font-weight: bold; font-size: 14px; color: {t.fg_base};
}}
QLabel#startupProjectTitle[error="true"] {{
    color: {t.btn_danger_fg};
}}
QLabel#startupProjectSubtitle {{
    color: {t.section_title_fg}; font-size: 11px;
}}
QLabel#startupProjectStats {{
    color: {t.autosave_fg}; font-size: 11px; font-weight: bold;
}}

/* ── Generic Dialog Labels ──────────────────────────────────────── */
QLabel.dialogHeaderTitle {{
    font-size: 15px; font-weight: 700; color: {t.fg_base};
}}
QLabel.dialogMutedText {{
    font-size: 11px; color: {t.section_title_fg};
}}
QLabel.dialogMutedTextLarge {{
    font-size: 12px; color: {t.section_title_fg}; margin-bottom: 4px;
}}
QLabel.dialogWarningText {{
    color: {t.btn_danger_fg}; font-size: 11px; font-style: italic;
}}
QFrame.dialogSeparator {{
    color: {t.border};
}}

/* ── Tabs ───────────────────────────────────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {t.tab_pane_border}; border-radius: 8px; background: {t.tab_pane_bg};
}}
QTabBar::tab {{
    background: transparent; border: none; padding: 8px 18px;
    color: {t.tab_fg}; border-radius: 6px 6px 0 0;
}}
QTabBar::tab:selected {{ background: {t.tab_selected_bg}; color: {t.tab_selected_fg}; font-weight: 600; }}
QTabBar::tab:hover:!selected {{ background: {t.tab_hover_bg}; color: {t.tab_hover_fg}; }}

/* ── Group box ──────────────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {t.groupbox_border}; border-radius: 8px;
    margin-top: 12px; padding-top: 8px;
    color: {t.groupbox_fg}; font-size: 11px; font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; top: -6px;
    background: {t.groupbox_title_bg}; padding: 0 4px;
}}

/* ── Scrollbar (vertical) ───────────────────────────────────────── */
QScrollBar:vertical {{
    background: {t.scrollbar_bg}; width: 8px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t.scrollbar_handle}; border-radius: 4px; min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

/* ── Scrollbar (horizontal) ─────────────────────────────────────── */
QScrollBar:horizontal {{
    background: {t.scrollbar_bg}; height: 8px; margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {t.scrollbar_handle}; border-radius: 4px; min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: none; }}

/* ── Status bar ─────────────────────────────────────────────────── */
QStatusBar {{
    background: {t.statusbar_bg}; border-top: 1px solid {t.statusbar_border};
    color: {t.statusbar_fg}; font-size: 11px;
}}

/* ── Tooltip ────────────────────────────────────────────────────── */
QToolTip {{
    background: {t.tooltip_bg}; color: {t.tooltip_fg};
    border: 1px solid {t.tooltip_border};
    border-radius: 4px; padding: 4px 8px;
    font-size: 12px;
}}

/* ── Menu ───────────────────────────────────────────────────────── */
QMenu {{
    background: {t.menu_bg}; border: 1px solid {t.menu_border};
    border-radius: 6px; padding: 4px 0;
}}
QMenu::item {{
    padding: 6px 24px 6px 12px; color: {t.menu_item_fg};
}}
QMenu::item:selected {{
    background: {t.menu_item_selected_bg}; color: {t.menu_item_selected_fg};
    border-radius: 4px;
}}
QMenu::separator {{
    height: 1px; background: {t.border}; margin: 4px 8px;
}}

/* ── Tree widget ────────────────────────────────────────────────── */
QTreeWidget, QTreeView {{
    background: {t.tree_bg}; border: none; outline: none;
    color: {t.tree_item_fg};
}}
QTreeWidget::item, QTreeView::item {{
    padding: 4px 6px; border-radius: 4px;
}}
QTreeWidget::item:selected, QTreeView::item:selected {{
    background: {t.tree_item_selected_bg}; color: {t.tree_item_selected_fg};
}}
QTreeWidget::item:hover:!selected, QTreeView::item:hover:!selected {{
    background: {t.list_item_hover_bg};
}}
QTreeWidget::branch, QTreeView::branch {{
    background: transparent;
}}

/* ── Header view ────────────────────────────────────────────────── */
QHeaderView {{
    background: {t.header_bg};
}}
QHeaderView::section {{
    background: {t.header_bg}; color: {t.header_fg};
    border: none; border-right: 1px solid {t.header_border};
    border-bottom: 1px solid {t.header_border};
    padding: 4px 8px; font-size: 11px; font-weight: 600;
}}

/* ── Progress bar ───────────────────────────────────────────────── */
QProgressBar {{
    background: {t.progress_bg}; border: 1px solid {t.border};
    border-radius: 6px; text-align: center;
    color: {t.progress_fg}; font-size: 11px;
    min-height: 16px;
}}
QProgressBar::chunk {{
    background: {t.progress_chunk}; border-radius: 5px;
}}

/* ── Checkbox ───────────────────────────────────────────────────── */
QCheckBox {{
    spacing: 6px; color: {t.fg_base};
}}
QCheckBox::indicator {{
    width: 16px; height: 16px; border-radius: 3px;
    border: 1px solid {t.checkbox_indicator_border};
    background: {t.checkbox_indicator_bg};
}}
QCheckBox::indicator:checked {{
    background: {t.checkbox_indicator_checked_bg};
    border-color: {t.checkbox_indicator_checked_border};
    image: none;
}}

/* ── Slider ─────────────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    background: {t.slider_groove_bg}; height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {t.slider_handle_bg}; border: 1px solid {t.slider_handle_border};
    width: 14px; height: 14px; margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {t.slider_sub_page}; border-radius: 3px;
}}
QSlider::groove:vertical {{
    background: {t.slider_groove_bg}; width: 6px;
    border-radius: 3px;
}}
QSlider::handle:vertical {{
    background: {t.slider_handle_bg}; border: 1px solid {t.slider_handle_border};
    width: 14px; height: 14px; margin: 0 -5px;
    border-radius: 7px;
}}
QSlider::sub-page:vertical {{
    background: {t.slider_sub_page}; border-radius: 3px;
}}
"""

# ─────────────────────────────────────────────────────────────────────────────
#  THEME MANAGER  (public API unchanged)
# ─────────────────────────────────────────────────────────────────────────────
class ThemeManager(QObject):
    """Manages Light/Dark/Terminal/Ebook theme toggling and persistence."""

    themeChanged = Signal(str)  # "dark", "light", "terminal", or "ebook"

    # Order used for cycling through themes
    THEME_ORDER = ["dark", "light", "terminal", "ebook"]

    # Expose token objects for programmatic access
    TOKENS = {
        "dark": DARK_TOKENS,
        "light": LIGHT_TOKENS,
        "terminal": TERMINAL_TOKENS,
        "ebook": EBOOK_TOKENS,
    }

    LIST_COLORS = {
        "dark":     DARK_TOKENS.list_colors,
        "light":    LIGHT_TOKENS.list_colors,
        "terminal": TERMINAL_TOKENS.list_colors,
        "ebook":    EBOOK_TOKENS.list_colors,
    }

    DEFAULT_FONT_FAMILY = "'Segoe UI', 'Inter', sans-serif"

    def __init__(self, app: QApplication, parent=None):
        super().__init__(parent)
        self._app = app
        self._settings = QSettings("CiteMind", "CiteMind")
        self._current = self._settings.value("theme", "dark")
        # Validate saved theme
        if self._current not in self.TOKENS:
            self._current = "dark"
        self._font_family = self._settings.value("font_family", self.DEFAULT_FONT_FAMILY)
        set_global_theme(self._current)

    @property
    def current(self) -> str:
        return self._current

    @property
    def font_family(self) -> str:
        return self._font_family

    @font_family.setter
    def font_family(self, value: str):
        self._font_family = value
        self._settings.setValue("font_family", value)

    def apply(self):
        t = self.TOKENS.get(self._current, self.TOKENS["dark"])
        qss = _build_qss(t, self._font_family)
        self._app.setStyleSheet(qss)

    def set_theme(self, name: str):
        """Set a specific theme by name."""
        if name not in self.TOKENS:
            return
        self._current = name
        set_global_theme(self._current)
        self._settings.setValue("theme", self._current)
        self.apply()
        self.themeChanged.emit(self._current)

    def toggle(self):
        """Cycle through all themes in THEME_ORDER."""
        try:
            idx = self.THEME_ORDER.index(self._current)
        except ValueError:
            idx = -1
        next_idx = (idx + 1) % len(self.THEME_ORDER)
        self.set_theme(self.THEME_ORDER[next_idx])

    def list_colors(self) -> dict:
        return self.LIST_COLORS.get(self._current, self.LIST_COLORS["dark"])

    # Theme icons mapping
    THEME_ICONS = {
        "dark": "moon",
        "light": "sun",
        "terminal": "terminal",
        "ebook": "book",
    }

    def theme_display_name(self, theme_key: str) -> str:
        """Return a user-friendly display name for a theme key."""
        names = {
            "dark": "Dark",
            "light": "Light",
            "terminal": "Terminal",
            "ebook": "eBook",
        }
        return names.get(theme_key, theme_key.capitalize())

    def theme_icon(self, theme_key: str) -> str:
        """Return the icon name corresponding to the theme key."""
        return self.THEME_ICONS.get(theme_key, "sun")

    def next_theme_name(self, current: str | None = None) -> str:
        """Return the next theme name in THEME_ORDER."""
        curr = current or self._current
        try:
            idx = self.THEME_ORDER.index(curr)
        except ValueError:
            idx = 0
        return self.THEME_ORDER[(idx + 1) % len(self.THEME_ORDER)]
