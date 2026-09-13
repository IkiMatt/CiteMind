"""Dialog that renders the bibliography DAG produced from the last pages of a PDF."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel, QProgressBar, QPushButton, QHBoxLayout

from app.widgets.dag_viewer import DagViewer


class ReferenceDagDialog(QDialog):
    """Small modal dialog containing the DAG viewer and a loading indicator."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bibliography DAG")
        self.resize(980, 760)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        self._title = QLabel("Estrazione riferimenti bibliografici")
        self._title.setStyleSheet("font-weight: 600; font-size: 14px;")
        header.addWidget(self._title)
        header.addStretch()

        self._close_btn = QPushButton("Chiudi")
        self._close_btn.clicked.connect(self.close)
        header.addWidget(self._close_btn)
        root.addLayout(header)

        self._status = QLabel("Attendo l’estrazione del PDF...")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._progress = QProgressBar(self)
        self._progress.setRange(0, 0)
        self._progress.setVisible(True)
        root.addWidget(self._progress)

        self._viewer = DagViewer(self)
        root.addWidget(self._viewer, 1)

    def set_busy(self, busy: bool) -> None:
        self._progress.setVisible(busy)
        self._status.setText("Estrazione in corso..." if busy else "Grafico pronto")

    def set_status(self, text: str) -> None:
        self._status.setText(text)

    def set_html(self, html_text: str) -> None:
        self._viewer.set_html(html_text)
        self._progress.setVisible(False)
        self._status.setText("Grafico generato")
