"""Export extracted PDF items as portable CSV or JSON datasets."""
from __future__ import annotations

import csv
import json
from pathlib import Path


_EXPORT_FIELDS = (
    "entry_id",
    "id",
    "object_type",
    "content_text",
    "file_path",
    "page",
    "bbox_json",
    "source",
    "confidence",
    "review_status",
    "metadata_json",
)


def export_extracted_items(model, entry_id: int, output_path: str | Path,
                           file_format: str | None = None,
                           include_pending: bool = True) -> int:
    """Export extracted items for an entry and return the number of rows."""
    destination = Path(output_path)
    fmt = (file_format or destination.suffix.lstrip(".")).lower()
    if fmt not in {"csv", "json"}:
        raise ValueError("Formato non supportato: usare CSV o JSON")

    rows = model.get_pdf_extracted_items(entry_id)
    if not include_pending:
        rows = [row for row in rows if row.get("review_status") == "confirmed"]
    normalized = [{field: row.get(field, "") for field in _EXPORT_FIELDS} for row in rows]

    destination.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        destination.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    else:
        with destination.open("w", encoding="utf-8-sig", newline="") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=_EXPORT_FIELDS)
            writer.writeheader()
            writer.writerows(normalized)
    return len(normalized)
