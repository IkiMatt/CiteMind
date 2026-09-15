"""Optional R analysis for extracted PDF datasets."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.services.extraction_export import export_extracted_items


_R_SCRIPT = r'''
args <- commandArgs(trailingOnly = TRUE)
input_path <- args[[1]]
output_path <- args[[2]]
data <- read.csv(input_path, stringsAsFactors = FALSE, check.names = FALSE)

png(output_path, width = 1200, height = 700, res = 120)
if (nrow(data) == 0) {
  plot.new()
  text(0.5, 0.5, "No confirmed extracted items")
} else {
  counts <- table(data$object_type)
  barplot(counts, col = "#2563eb", las = 2,
          main = "CiteMind PDF extraction summary",
          xlab = "Extracted object type", ylab = "Count")
}
dev.off()
'''.lstrip()


def run_r_summary(model, entry_id: int, output_dir: str | Path) -> dict:
    """Export confirmed items and render a summary chart with Rscript."""
    rscript = shutil.which("Rscript") or shutil.which("Rscript.exe")
    if not rscript:
        raise RuntimeError("R non è disponibile: installare R e aggiungere Rscript al PATH.")

    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    dataset_path = destination / "extracted_confirmed.csv"
    script_path = destination / "citemind_summary.R"
    chart_path = destination / "extraction_summary.png"

    row_count = export_extracted_items(
        model,
        entry_id,
        dataset_path,
        file_format="csv",
        include_pending=False,
    )
    script_path.write_text(_R_SCRIPT, encoding="utf-8")

    completed = subprocess.run(
        [rscript, str(script_path), str(dataset_path), str(chart_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "Rscript failed"
        raise RuntimeError(message)

    return {
        "rows": row_count,
        "dataset_path": str(dataset_path),
        "script_path": str(script_path),
        "chart_path": str(chart_path),
    }
