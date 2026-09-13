"""
learning.py — Import learning system for CiteMind.

Tracks user corrections to imported metadata and applies learned patterns
to future imports. Wraps the EntryModel correction methods.
"""
from __future__ import annotations

from app.model import EntryModel


class ImportLearningSystem:
    """
    Learns from user corrections to improve future imports.
    Stores correction patterns in the import_corrections table.
    """

    def __init__(self, model: EntryModel):
        self._model = model

    def record_correction(self, original_data: dict, corrected_data: dict) -> None:
        """
        Compare original (auto-imported) data with user-corrected data.
        Record any differences as learned corrections.
        """
        fields_to_track = ("journal", "authors", "publisher", "title", "year")

        for field_name in fields_to_track:
            original_val = str(original_data.get(field_name, "")).strip()
            corrected_val = str(corrected_data.get(field_name, "")).strip()

            if original_val and corrected_val and original_val != corrected_val:
                self._model.record_correction(field_name, original_val, corrected_val)

    def apply_corrections(self, data: dict) -> dict:
        """
        Apply learned corrections to import data.
        Returns a new dict with corrections applied.
        """
        result = dict(data)
        for field_name in ("journal", "authors", "publisher"):
            corrections = self._model.get_corrections(field_name)
            val = result.get(field_name, "")
            if val and val in corrections:
                result[field_name] = corrections[val]
        return result

    def get_journal_mappings(self) -> dict[str, str]:
        """Return learned journal abbreviation → full name mappings."""
        return self._model.get_corrections("journal")

    def get_author_normalizations(self) -> dict[str, str]:
        """Return learned author name normalizations."""
        return self._model.get_corrections("authors")

    def get_all_corrections(self) -> list[dict]:
        """Return all corrections for display in settings."""
        return self._model.get_all_corrections()
