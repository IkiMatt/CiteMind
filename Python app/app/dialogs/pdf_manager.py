"""
pdf_manager.py — PDF scanning, auto-matching, link management.

Classes:
  PdfScanThread   — background worker that scans folders and scores PDF↔entry matches
  PdfManagerDialog — combined dialog for scanning and managing links
"""
import os

import pymupdf as fitz
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QMessageBox, QProgressBar,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QTabWidget
)

from app.theme import icon, get_global_theme
from app.adapter import EntryAdapter
from app.i18n import LanguageManager


# ─────────────────────────────────────────────────────────────────────────────
#  BACKGROUND SCAN WORKER
# ─────────────────────────────────────────────────────────────────────────────
class PdfScanThread(QThread):
    progress = Signal(int, int)
    finished = Signal(object)

    def __init__(self, folders: list[str], unlinked_entries: list[dict]):
        super().__init__()
        self.folders  = folders
        self.entries  = unlinked_entries
        self._cancel  = False

    def cancel(self):
        self._cancel = True

    def run(self):
        pdf_files = []
        for folder in self.folders:
            for root, _, files in os.walk(folder):
                if self._cancel:
                    break
                for f in files:
                    if f.lower().endswith(".pdf"):
                        pdf_files.append(os.path.join(root, f))

        results = []
        total   = len(pdf_files)

        for i, pdf_path in enumerate(pdf_files):
            if self._cancel:
                break

            text = ""
            try:
                with fitz.open(pdf_path) as doc:
                    if len(doc) > 0:
                        text = doc[0].get_text("text").lower()
            except Exception:
                pass

            best_match     = None
            best_score     = 0
            best_precision = "none"

            for e in self.entries:
                authors = e.get("authors", "").lower()
                title   = e.get("title",   "").lower()

                author_in_text = False
                if authors:
                    surnames = [p.split(",")[0].strip() for p in authors.split(";")]
                    for surname in surnames:
                        if surname and surname in text:
                            author_in_text = True
                            break

                title_words = [w for w in title.split() if len(w) > 3]
                words_found = sum(1 for w in title_words if w in text)
                title_ratio = words_found / len(title_words) if title_words else 0

                if author_in_text and title_ratio > 0.75:
                    precision = "green";  score = 100 + title_ratio * 10
                elif author_in_text and title_ratio > 0.4:
                    precision = "yellow"; score = 60  + title_ratio * 10
                elif title_ratio > 0.7:
                    precision = "yellow"; score = 50  + title_ratio * 10
                elif author_in_text or title_ratio > 0.3:
                    precision = "red";    score = 20  + title_ratio * 10
                else:
                    precision = "none";   score = 0

                if score > best_score:
                    best_score     = score
                    best_match     = e
                    best_precision = precision

            if best_match and best_precision != "none":
                results.append({
                    "pdf_path":    pdf_path,
                    "entry_id":    best_match["id"],
                    "entry_label": f"{best_match.get('authors', '')} - {best_match.get('title', '')}",
                    "precision":   best_precision,
                })

            self.progress.emit(i + 1, total)

        self.finished.emit(results)


# ─────────────────────────────────────────────────────────────────────────────
#  PDF UNIFIED MANAGER DIALOG  (Scanner + Managed Links)
# ─────────────────────────────────────────────────────────────────────────────
class PdfManagerDialog(QDialog):
    """Unified dialog: tab 1 for managing existing links, tab 2 for scanning new PDFs."""

    def __init__(self, adapter: EntryAdapter, lang_mgr: LanguageManager, parent=None):
        super().__init__(parent)
        self._adapter     = adapter
        self._lang        = lang_mgr
        self._results:    list[dict] = []
        self._thread:     PdfScanThread | None = None
        self._all_entries: list[dict] = []
        self.folders:     list[str]  = []

        self.setWindowTitle(self._lang.tr("pdf_manager_title"))
        self.setWindowIcon(icon("folder-plus"))
        self.setMinimumSize(920, 560)
        self._build_ui()
        self._load_linked()

    # ── UI ────────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        self._tabs = QTabWidget()
        
        # Build tabs
        self._tab_linked = QWidget()
        self._build_linked_tab()
        
        self._tab_scanner = QWidget()
        self._build_scanner_tab()
        
        self._tabs.addTab(self._tab_linked, icon("books"), f" {self._lang.tr('pdf_mgr_tab_linked')}")
        self._tabs.addTab(self._tab_scanner, icon("search"), f" {self._lang.tr('pdf_mgr_tab_scanner')}")
        
        root.addWidget(self._tabs)

    def _build_linked_tab(self):
        layout = QVBoxLayout(self._tab_linked)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(10)

        hdr = QHBoxLayout()
        title_lbl = QLabel(self._lang.tr("pdf_mgr_linked_title"))
        title_lbl.setObjectName("sectionTitle")
        self._badge = QLabel("0")
        self._badge.setObjectName("entryCount")
        hdr.addWidget(title_lbl)
        hdr.addStretch()
        hdr.addWidget(self._badge)
        layout.addLayout(hdr)

        info = QLabel(
            self._lang.tr("pdf_mgr_linked_info")
        )
        info.setWordWrap(True)
        info.setProperty("class", "dialogMutedTextLarge")
        layout.addWidget(info)

        self._linked_table = QTableWidget(0, 3)
        self._linked_table.setHorizontalHeaderLabels([
            self._lang.tr("pdf_mgr_col_record"), 
            self._lang.tr("pdf_mgr_col_pdf"), 
            self._lang.tr("pdf_mgr_col_actions")
        ])
        self._linked_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._linked_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self._linked_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._linked_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._linked_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._linked_table.verticalHeader().setVisible(False)
        self._linked_table.setAlternatingRowColors(True)
        layout.addWidget(self._linked_table)

        bottom = QHBoxLayout()
        self._btn_unlink_all = QPushButton(icon("trash"), f"  {self._lang.tr('pdf_mgr_btn_unlink_all')}")
        self._btn_unlink_all.setObjectName("btnDanger")
        self._btn_unlink_all.setToolTip(self._lang.tr("pdf_mgr_tip_unlink_all"))
        self._btn_unlink_all.clicked.connect(self._unlink_all)

        btn_close = QPushButton(self._lang.tr("pdf_mgr_btn_close"))
        btn_close.clicked.connect(self.accept)

        bottom.addWidget(self._btn_unlink_all)
        bottom.addStretch()
        bottom.addWidget(btn_close)
        layout.addLayout(bottom)

    def _build_scanner_tab(self):
        layout = QVBoxLayout(self._tab_scanner)
        layout.setContentsMargins(12, 16, 12, 12)
        layout.setSpacing(10)

        # Top bar
        top_h = QHBoxLayout()
        self.btn_add_folder = QPushButton(icon("folder-plus"), f"  {self._lang.tr('pdf_mgr_btn_add_folder')}")
        self.btn_add_folder.clicked.connect(self._add_folder)
        self.lbl_folders = QLabel(self._lang.tr("pdf_mgr_lbl_no_folder"))
        self.lbl_folders.setProperty("class", "dialogMutedText")
        self.btn_scan = QPushButton(icon("search"), f"  {self._lang.tr('pdf_mgr_btn_scan')}")
        self.btn_scan.setObjectName("btnPrimary")
        self.btn_scan.setEnabled(False)
        self.btn_scan.clicked.connect(self._do_scan)
        top_h.addWidget(self.btn_add_folder)
        top_h.addWidget(self.lbl_folders, 1)
        top_h.addWidget(self.btn_scan)
        layout.addLayout(top_h)

        # Progress + status
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.lbl_status = QLabel("")
        self.lbl_status.setProperty("class", "dialogMutedTextLarge")
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.lbl_status)

        # Legend
        legend = QLabel(
            self._lang.tr("pdf_mgr_legend")
        )
        legend.setProperty("class", "dialogMutedText")
        layout.addWidget(legend)

        # Table
        self.scanner_table = QTableWidget(0, 4)
        self.scanner_table.setHorizontalHeaderLabels([
            self._lang.tr("pdf_mgr_col_pdf"), 
            self._lang.tr("pdf_mgr_col_record"), 
            self._lang.tr("pdf_mgr_col_prec"), 
            self._lang.tr("pdf_mgr_col_link")
        ])
        self.scanner_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.scanner_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.scanner_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.scanner_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.scanner_table.setColumnWidth(0, 220)
        self.scanner_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.scanner_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.scanner_table.verticalHeader().setVisible(False)
        self.scanner_table.setAlternatingRowColors(True)
        layout.addWidget(self.scanner_table)

        # Bottom bar
        bottom_h = QHBoxLayout()
        self.btn_select_all = QPushButton(f"\u2611 {self._lang.tr('pdf_mgr_btn_select_all')}")
        self.btn_select_all.setEnabled(False)
        self.btn_select_all.clicked.connect(lambda: self._set_all_checks(True))
        self.btn_deselect_all = QPushButton(f"\u2610 {self._lang.tr('pdf_mgr_btn_deselect_all')}")
        self.btn_deselect_all.setEnabled(False)
        self.btn_deselect_all.clicked.connect(lambda: self._set_all_checks(False))
        self.btn_cancel = QPushButton(self._lang.tr("pdf_mgr_btn_close"))
        self.btn_cancel.clicked.connect(self.accept)
        self.btn_save = QPushButton(icon("file-download"), f"  {self._lang.tr('pdf_mgr_btn_save')}")
        self.btn_save.setObjectName("btnPrimary")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self._save_links)

        bottom_h.addWidget(self.btn_select_all)
        bottom_h.addWidget(self.btn_deselect_all)
        bottom_h.addStretch()
        bottom_h.addWidget(self.btn_cancel)
        bottom_h.addWidget(self.btn_save)
        layout.addLayout(bottom_h)


    # ── LINKED TAB LOGIC ───────────────────────────────────────────────────
    def _load_linked(self):
        self._linked_table.setRowCount(0)
        linked = self._adapter.get_linked_entries()
        self._badge.setText(str(len(linked)))
        self._btn_unlink_all.setEnabled(len(linked) > 0)

        for row, e in enumerate(linked):
            self._linked_table.insertRow(row)

            label    = f"{e.get('authors', '')} \u2014 {e.get('title', '')}".strip(" \u2014")
            item_rec = QTableWidgetItem(label)
            item_rec.setData(Qt.UserRole, e["id"])
            item_rec.setToolTip(label)
            self._linked_table.setItem(row, 0, item_rec)

            pdf_path = e.get("pdf_path", "")
            item_pdf = QTableWidgetItem(os.path.basename(pdf_path))
            item_pdf.setToolTip(pdf_path)
            self._linked_table.setItem(row, 1, item_pdf)

            btn = QPushButton(f"\u2715 {self._lang.tr('pdf_mgr_btn_unlink')}")
            btn.setObjectName("btnDanger")
            btn.setFixedHeight(26)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, eid=e["id"]: self._unlink_one(eid))

            btn_rename = QPushButton(self._lang.tr("pdf_mgr_btn_rename"))
            btn_rename.setFixedHeight(26)
            btn_rename.setCursor(Qt.PointingHandCursor)
            btn_rename.clicked.connect(lambda checked, entry=e: self._rename_one(entry))

            cell_w = QWidget()
            cell_l = QHBoxLayout(cell_w)
            cell_l.setContentsMargins(4, 2, 4, 2)
            cell_l.addWidget(btn_rename)
            cell_l.addWidget(btn)
            self._linked_table.setCellWidget(row, 2, cell_w)

        if not linked:
            self._linked_table.insertRow(0)
            placeholder = QTableWidgetItem(self._lang.tr("pdf_mgr_placeholder_no_linked"))
            placeholder.setTextAlignment(Qt.AlignCenter)
            placeholder.setFlags(Qt.ItemIsEnabled)
            self._linked_table.setItem(0, 0, placeholder)
            self._linked_table.setSpan(0, 0, 1, 3)

    def _rename_one(self, e: dict):
        import re
        pdf_path = e.get("pdf_path")
        if not pdf_path or not os.path.exists(pdf_path):
            QMessageBox.warning(self, self._lang.tr("style_editor_error_title"), self._lang.tr("msg_pdf_not_found_text"))
            return

        authors = e.get("authors", "")
        first_author = ""
        if authors:
            parts = authors.split(";")
            if parts:
                first_author = parts[0].split(",")[0].strip()
        
        anno = e.get("year", "").strip()
        titolo = e.get("title", "").strip()
        
        parts = []
        if first_author: parts.append(first_author)
        if anno: parts.append(anno)
        if titolo: parts.append(titolo)
        
        raw_name = "_".join(parts)
        if not raw_name:
            raw_name = "documento"

        safe_name = re.sub(r'[\\/*?:"<>|]', "", raw_name)
        safe_name = safe_name.replace(" ", "_")
        if len(safe_name) > 150:
            safe_name = safe_name[:150]
            
        safe_name += ".pdf"
        
        dir_name = os.path.dirname(pdf_path)
        new_path = os.path.join(dir_name, safe_name)
        
        if new_path == pdf_path:
            QMessageBox.information(self, self._lang.tr("pdf_mgr_msg_rename_correct_title"), self._lang.tr("pdf_mgr_msg_rename_correct_text"))
            return
            
        if os.path.exists(new_path):
            QMessageBox.warning(self, self._lang.tr("style_editor_error_title"), self._lang.tr("pdf_mgr_msg_rename_exists_text").format(name=safe_name))
            return

        try:
            os.rename(pdf_path, new_path)
            self._adapter._model.update(e["id"], {"pdf_path": new_path})
            self._adapter.entriesChanged.emit()
            self._load_linked()
            QMessageBox.information(self, self._lang.tr("pdf_mgr_msg_rename_success_title"), self._lang.tr("pdf_mgr_msg_rename_success_text").format(name=safe_name))
        except Exception as ex:
            QMessageBox.critical(self, self._lang.tr("style_editor_error_title"), f"{self._lang.tr('ai_settings_status_error')}{str(ex)}")

    def _unlink_one(self, entry_id: int):
        ret = QMessageBox.question(
            self, self._lang.tr("msg_unlink_pdf_title"),
            self._lang.tr("msg_unlink_pdf_text"),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            self._adapter.unlink_pdf(entry_id)
            self._load_linked()

    def _unlink_all(self):
        linked_count = len(self._adapter.get_linked_entries())
        if linked_count == 0:
            return
        ret = QMessageBox.question(
            self, self._lang.tr("pdf_mgr_msg_unlink_all_title"),
            self._lang.tr("pdf_mgr_msg_unlink_all_text").format(count=linked_count),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ret == QMessageBox.Yes:
            removed = self._adapter.unlink_all_pdfs()
            self._load_linked()
            QMessageBox.information(self, self._lang.tr("docx_export_success_title"), self._lang.tr("pdf_mgr_msg_unlink_all_success").format(count=removed))


    # ── SCANNER TAB LOGIC ──────────────────────────────────────────────────
    def _add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, self._lang.tr("pdf_mgr_btn_add_folder"))
        if folder and folder not in self.folders:
            self.folders.append(folder)
            self.lbl_folders.setText("; ".join(self.folders))
            self.lbl_folders.setProperty("class", "")
            self.btn_scan.setEnabled(True)

    def _do_scan(self):
        if not self.folders:
            return
        self._all_entries = self._adapter.get_all_for_export()
        unlinked = [e for e in self._all_entries if not e.get("pdf_path")]

        self.btn_add_folder.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.btn_select_all.setEnabled(False)
        self.btn_deselect_all.setEnabled(False)
        self.scanner_table.setRowCount(0)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.lbl_status.setText(self._lang.tr("pdf_mgr_status_scanning").format(count=len(unlinked)))
        self.btn_save.setEnabled(False)

        self._thread = PdfScanThread(self.folders, unlinked)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_scan_finished)
        self._thread.start()

    def _on_progress(self, curr: int, tot: int):
        self.progress_bar.setMaximum(tot)
        self.progress_bar.setValue(curr)
        self.lbl_status.setText(self._lang.tr("pdf_mgr_status_analyzed").format(curr=curr, tot=tot))

    def _on_scan_finished(self, results: list[dict]):
        self.progress_bar.setVisible(False)
        self.btn_add_folder.setEnabled(True)
        self.btn_scan.setEnabled(True)

        prec_order    = {"green": 0, "yellow": 1, "red": 2}
        results_sorted = sorted(results, key=lambda r: prec_order.get(r["precision"], 3))
        self._results  = results_sorted

        all_labels = [
            f"{e.get('authors', '')} \u2014 {e.get('title', '')}".strip(" \u2014")
            for e in self._all_entries
        ]
        all_ids = [e["id"] for e in self._all_entries]
        dark    = get_global_theme() == "dark"

        self.scanner_table.setRowCount(len(results_sorted))
        for row, res in enumerate(results_sorted):
            p_val = res["precision"]
            if p_val == "green":
                emoji     = self._lang.tr("pdf_mgr_prec_high")
                row_color = QColor("#0d2b1a") if dark else QColor("#e6f9ee")
            elif p_val == "yellow":
                emoji     = self._lang.tr("pdf_mgr_prec_med")
                row_color = QColor("#2b2200") if dark else QColor("#fffbe6")
            else:
                emoji     = self._lang.tr("pdf_mgr_prec_low")
                row_color = QColor("#2b0a0a") if dark else QColor("#fff0f0")

            # Col 0: PDF filename
            item_pdf = QTableWidgetItem(os.path.basename(res["pdf_path"]))
            item_pdf.setToolTip(res["pdf_path"])
            item_pdf.setBackground(row_color)
            self.scanner_table.setItem(row, 0, item_pdf)
            self.scanner_table.setRowHeight(row, 36)

            # Col 1: combo for manual override
            combo = QComboBox()
            combo.addItems(all_labels)
            try:
                combo.setCurrentIndex(all_ids.index(res["entry_id"]))
            except ValueError:
                pass
            combo.setProperty("all_ids", all_ids)
            self.scanner_table.setCellWidget(row, 1, combo)
            res["combo"] = combo

            # Col 2: precision badge
            item_prec = QTableWidgetItem(emoji)
            item_prec.setTextAlignment(Qt.AlignCenter)
            item_prec.setBackground(row_color)
            self.scanner_table.setItem(row, 2, item_prec)

            # Col 3: checkbox
            chk = QCheckBox()
            chk.setChecked(p_val in ["green", "yellow"])
            chk.setToolTip(self._lang.tr("pdf_mgr_col_link"))
            cell_w = QWidget()
            cell_l = QHBoxLayout(cell_w)
            cell_l.setAlignment(Qt.AlignCenter)
            cell_l.setContentsMargins(0, 0, 0, 0)
            cell_l.addWidget(chk)
            self.scanner_table.setCellWidget(row, 3, cell_w)
            res["checkbox"] = chk

        if results_sorted:
            self.btn_save.setEnabled(True)
            self.btn_select_all.setEnabled(True)
            self.btn_deselect_all.setEnabled(True)
            g = sum(1 for r in results_sorted if r["precision"] == "green")
            y = sum(1 for r in results_sorted if r["precision"] == "yellow")
            r = sum(1 for r in results_sorted if r["precision"] == "red")
            self.lbl_status.setText(
                self._lang.tr("pdf_mgr_status_found").format(
                    count=len(results_sorted), g=g, y=y, r=r
                )
            )
        else:
            self.lbl_status.setText(self._lang.tr("pdf_mgr_status_none"))
            QMessageBox.information(
                self, self._lang.tr("pdf_mgr_msg_no_results_title"),
                self._lang.tr("pdf_mgr_msg_no_results_text")
            )

    def _set_all_checks(self, state: bool):
        for res in self._results:
            chk = res.get("checkbox")
            if chk:
                chk.setChecked(state)

    def _save_links(self):
        count = 0
        for res in self._results:
            chk = res.get("checkbox")
            if chk and chk.isChecked():
                combo   = res.get("combo")
                all_ids = combo.property("all_ids") if combo else []
                idx     = combo.currentIndex() if combo else -1
                entry_id = all_ids[idx] if (0 <= idx < len(all_ids)) else res["entry_id"]
                self._adapter._model.update(entry_id, {"pdf_path": res["pdf_path"]})
                count += 1

        if count > 0:
            self._adapter.entriesChanged.emit()
            self._load_linked() # automatically refresh linked tab 
            QMessageBox.information(self, self._lang.tr("docx_export_success_title"), self._lang.tr("pdf_mgr_msg_save_success").format(count=count))
            self._tabs.setCurrentIndex(0) # switch to linked tab
        else:
            self.accept()

    def closeEvent(self, event):
        if self._thread and self._thread.isRunning():
            self._thread.cancel()
            self._thread.wait()
        event.accept()
