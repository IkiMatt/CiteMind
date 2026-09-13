"""Reusable PySide6 widget that renders a DAG HTML preview.

Falls back to QTextBrowser when QtWebEngine is not available in the runtime,
so the application still works without the external QtWebEngine process.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QTextBrowser

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - runtime fallback
    QWebEngineView = None


def is_dag_viewer_available() -> bool:
    """Return True when a QtWebEngine-backed DAG viewer can be used."""
    return QWebEngineView is not None


class DagViewer(QWidget):
    """Display a generated DAG HTML graph in an embedded browser-like panel."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._html: str = ""
        self._temp_path: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._status = QLabel("Caricamento grafo...")
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setStyleSheet("padding: 8px; color: #d1d5db;")

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)

        if QWebEngineView is not None:
            self._web_view = QWebEngineView(self)
        else:
            self._web_view = QTextBrowser(self)
            self._web_view.setOpenExternalLinks(True)
            self._web_view.setReadOnly(True)
            self._web_view.setStyleSheet("background: #0f172a; color: #f3f4f6;")
        self._web_view.setVisible(True)

        layout.addWidget(self._status)
        layout.addWidget(self._progress)
        layout.addWidget(self._web_view)

    def set_html(self, html_text: str) -> None:
        """Render raw HTML into the embedded browser."""
        self._html = html_text
        self._status.setText("Grafico pronto")
        self._status.setVisible(True)
        self._web_view.setHtml(html_text)

    def load_from_file(self, path: str | Path) -> None:
        """Load HTML from a file path."""
        self._temp_path = Path(path)
        self._status.setText("Caricamento file grafico...")
        if QWebEngineView is not None:
            self._web_view.setUrl(self._temp_path.as_uri())
        else:
            self._web_view.setHtml(self._temp_path.read_text(encoding="utf-8"))

    def set_loading(self, is_loading: bool) -> None:
        """Toggle the loading indicator while async inference is running."""
        self._progress.setVisible(is_loading)
        self._progress.setRange(0, 0) if is_loading else self._progress.setRange(0, 1)
        self._status.setText("Generazione DAG in corso..." if is_loading else "Grafico pronto")

    @property
    def web_view(self):
        return self._web_view
