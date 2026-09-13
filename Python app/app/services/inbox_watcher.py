"""
inbox_watcher.py — Monitor a folder for new PDFs and auto-import them.

Uses QFileSystemWatcher for cross-platform file monitoring.
Debounces file detection to wait for write completion.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, QFileSystemWatcher


class InboxWatcher(QObject):
    """
    Monitors a folder for new PDF files and signals for auto-import.

    Signals
    -------
    newFileDetected : str
        Emitted with the file path when a new PDF is found.
    """

    newFileDetected = Signal(str)

    def __init__(self, inbox_path: str, parent=None):
        super().__init__(parent)
        self._inbox_path = Path(inbox_path)
        self._watcher = QFileSystemWatcher(parent=self)
        self._watcher.directoryChanged.connect(self._on_directory_changed)
        self._known_files: set[str] = set()
        self._pending_files: list[str] = []
        self._active = False

        # Debounce timer — wait for file to finish writing
        self._debounce = QTimer(self)
        self._debounce.setInterval(2000)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._process_pending)

    @property
    def inbox_path(self) -> Path:
        return self._inbox_path

    @property
    def is_active(self) -> bool:
        return self._active

    def start(self) -> bool:
        """Start monitoring the inbox folder. Creates it if needed."""
        try:
            self._inbox_path.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False

        self._known_files = {
            f.name for f in self._inbox_path.iterdir() if f.is_file()
        }

        success = self._watcher.addPath(str(self._inbox_path))
        self._active = success
        return success

    def stop(self) -> None:
        """Stop monitoring."""
        if self._active:
            self._watcher.removePath(str(self._inbox_path))
            self._active = False
            self._debounce.stop()

    def set_inbox_path(self, path: str) -> None:
        """Change the monitored folder."""
        was_active = self._active
        if was_active:
            self.stop()
        self._inbox_path = Path(path)
        if was_active:
            self.start()

    def _on_directory_changed(self, path: str) -> None:
        """Called when the watched directory contents change."""
        try:
            current = {
                f.name for f in self._inbox_path.iterdir() if f.is_file()
            }
        except OSError:
            return

        new_files = current - self._known_files
        self._known_files = current

        # Filter for supported file types
        supported_exts = {".pdf", ".bib", ".ris"}
        for filename in new_files:
            ext = Path(filename).suffix.lower()
            if ext in supported_exts:
                full_path = str(self._inbox_path / filename)
                if full_path not in self._pending_files:
                    self._pending_files.append(full_path)

        if self._pending_files:
            self._debounce.start()  # restart debounce timer

    def _process_pending(self) -> None:
        """Process all pending files after debounce period."""
        files = list(self._pending_files)
        self._pending_files.clear()

        for filepath in files:
            if Path(filepath).exists():
                self.newFileDetected.emit(filepath)
