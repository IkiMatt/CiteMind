"""
adapter.py — EntryAdapter: business-logic bridge between Model and Views.
Manages the current selection, staged edits, debounced auto-save, and
emits Qt signals so Views can react to state changes without tight coupling.
"""
from PySide6.QtCore import QObject, QTimer, Signal

from app.model import EntryModel


class EntryAdapter(QObject):
    """Business logic between Model and View."""

    entriesChanged = Signal()
    entrySelected  = Signal(object)
    autosaved      = Signal(str)
    statsChanged   = Signal(object)

    def __init__(self, model: EntryModel, parent=None):
        super().__init__(parent)
        self._model = model
        self._current_id: int | None = None
        self._dirty_data: dict = {}
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(400)
        self._save_timer.timeout.connect(self._flush_save)

    # ── properties ────────────────────────────────────────────────────────
    @property
    def current_id(self) -> int | None:
        return self._current_id

    # ── entry loading ─────────────────────────────────────────────────────
    def load_entries(self, search: str = "", entry_type: str = "") -> list[dict]:
        return self._model.read_all(search, entry_type)

    def select_entry(self, entry_id: int):
        data = self._model.read_by_id(entry_id)
        self._current_id = entry_id
        self._dirty_data = {}
        self.entrySelected.emit(data)

    # ── CRUD ──────────────────────────────────────────────────────────────
    def new_entry(self, entry_type: str = "bibliography") -> int:
        skeleton = {
            "entry_type": entry_type,
            "pub_type": (
                "article"   if entry_type == "bibliography" else
                "triennale" if entry_type == "tesi" else ""
            ),
            "authors": "", "title": "", "year": "", "publisher": "",
            "journal": "", "volume": "", "issue": "", "pages": "",
            "edition": "", "doi": "", "url": "", "access_date": "",
            "notes": "", "pdf_path": "", "is_read": 0, "ai_notes": "",
        }
        new_id = self._model.create(skeleton)
        self._current_id = new_id
        self._dirty_data = {}
        self.entriesChanged.emit()
        self.statsChanged.emit(self._model.stats())
        return new_id

    def stage_change(self, field: str, value: str):
        if self._current_id is None:
            return
        self._dirty_data[field] = value
        self._save_timer.start()

    def delete_entry(self, entry_id: int):
        self._model.delete(entry_id)
        if self._current_id == entry_id:
            self._current_id = None
        self.entriesChanged.emit()
        self.statsChanged.emit(self._model.stats())

    # ── queries ───────────────────────────────────────────────────────────
    def get_stats(self) -> dict:
        return self._model.stats()

    def get_distinct_journals(self) -> list[str]:
        return self._model.get_distinct_journals()

    def get_distinct_ai_topics(self) -> list[str]:
        return self._model.get_distinct_ai_topics()

    def get_top_publisher_for_journal(self, journal: str) -> str:
        return self._model.get_top_publisher_for_journal(journal)

    def has_duplicate_title(self, title: str) -> bool:
        return self._model.check_duplicate_title(title, self._current_id)

    def set_read_status(self, entry_id: int, is_read: int) -> None:
        self._model.update(entry_id, {"is_read": is_read})

    def get_all_for_export(self, entry_type: str = "") -> list[dict]:
        return self._model.read_all(entry_type=entry_type)

    # ── PDF link management ───────────────────────────────────────────────
    def get_linked_entries(self) -> list[dict]:
        return self._model.get_linked_entries()

    def unlink_pdf(self, entry_id: int) -> None:
        self._model.unlink_pdf(entry_id)
        self.entriesChanged.emit()

    def unlink_all_pdfs(self) -> int:
        count = self._model.unlink_all_pdfs()
        self.entriesChanged.emit()
        return count

    # ── AI Notes ──────────────────────────────────────────────────────────
    def save_ai_notes(self, entry_id: int, json_str: str) -> None:
        """Persist AI-generated notes for an entry."""
        self._model.save_ai_notes(entry_id, json_str)

    def get_ai_notes(self, entry_id: int) -> str:
        """Return the stored AI notes JSON string for an entry."""
        return self._model.get_ai_notes(entry_id)

    # ── auto-save ─────────────────────────────────────────────────────────
    def _flush_save(self):
        if self._current_id is None or not self._dirty_data:
            return
        self._model.update(self._current_id, self._dirty_data)
        self._dirty_data = {}
        self.autosaved.emit("✓ Auto-saved")
        self.entriesChanged.emit()
        self.statsChanged.emit(self._model.stats())
