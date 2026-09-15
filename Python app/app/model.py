"""
model.py — EntryModel: SQLite persistence layer.
All database access runs through this class.
"""
import sqlite3
import threading
import datetime
import json
from pathlib import Path



import functools

def locked(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return func(self, *args, **kwargs)
    return wrapper

class EntryModel:
    """SQLite persistence layer — all SQL runs through this class."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS entries (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_type             TEXT    NOT NULL DEFAULT 'bibliography',
        pub_type               TEXT    NOT NULL DEFAULT '',
        authors                TEXT    NOT NULL DEFAULT '',
        title                  TEXT    NOT NULL DEFAULT '',
        year                   TEXT    NOT NULL DEFAULT '',
        publisher              TEXT    NOT NULL DEFAULT '',
        journal                TEXT    NOT NULL DEFAULT '',
        volume                 TEXT    NOT NULL DEFAULT '',
        issue                  TEXT    NOT NULL DEFAULT '',
        pages                  TEXT    NOT NULL DEFAULT '',
        edition                TEXT    NOT NULL DEFAULT '',
        doi                    TEXT    NOT NULL DEFAULT '',
        url                    TEXT    NOT NULL DEFAULT '',
        access_date            TEXT    NOT NULL DEFAULT '',
        notes                  TEXT    NOT NULL DEFAULT '',
        pdf_path               TEXT    NOT NULL DEFAULT '',
        is_read                INTEGER NOT NULL DEFAULT 0,
        ai_notes               TEXT    NOT NULL DEFAULT '',
        ai_topics              TEXT    NOT NULL DEFAULT '',
        extracted_bibliography TEXT    NOT NULL DEFAULT '',
        linked_references      TEXT    NOT NULL DEFAULT '[]',
        is_editor              INTEGER NOT NULL DEFAULT 0,
        location               TEXT    NOT NULL DEFAULT '',
        created_at             TEXT    NOT NULL,
        modified_at            TEXT    NOT NULL
    );
    """

    GRAPH_SCHEMA = """
    CREATE TABLE IF NOT EXISTS graph_state (
        id          INTEGER PRIMARY KEY CHECK (id = 1),
        graph_json  TEXT    NOT NULL DEFAULT '',
        built_at    TEXT    NOT NULL DEFAULT '',
        mode        TEXT    NOT NULL DEFAULT ''
    );
    """

    FTS_SCHEMA = """
    CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
        title, authors, publisher, journal, notes, abstract
    );
    """

    FTS_TRIGGERS = """
    DROP TRIGGER IF EXISTS entries_ai;
    DROP TRIGGER IF EXISTS entries_ad;
    DROP TRIGGER IF EXISTS entries_au;

    CREATE TRIGGER entries_ai AFTER INSERT ON entries BEGIN
        INSERT INTO entries_fts(rowid, title, authors, publisher, journal, notes, abstract)
        VALUES (new.id, new.title, new.authors, new.publisher, new.journal, new.notes, new.ai_notes);
    END;
    CREATE TRIGGER entries_ad AFTER DELETE ON entries BEGIN
        DELETE FROM entries_fts WHERE rowid = old.id;
    END;
    CREATE TRIGGER entries_au AFTER UPDATE ON entries BEGIN
        DELETE FROM entries_fts WHERE rowid = old.id;
        INSERT INTO entries_fts(rowid, title, authors, publisher, journal, notes, abstract)
        VALUES (new.id, new.title, new.authors, new.publisher, new.journal, new.notes, new.ai_notes);
    END;
    """

    # ── Phase-2 schema: embeddings, clusters, metrics, learning ────────────
    EMBEDDINGS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS embeddings (
        entry_id    INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
        model_name  TEXT    NOT NULL DEFAULT '',
        vector      BLOB    NOT NULL,
        dimensions  INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT    NOT NULL
    );
    """

    CLUSTERS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS clusters (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        label       TEXT    NOT NULL DEFAULT '',
        color       TEXT    NOT NULL DEFAULT '#7c3aed',
        description TEXT    NOT NULL DEFAULT '',
        paper_count INTEGER NOT NULL DEFAULT 0,
        density     REAL    NOT NULL DEFAULT 0.0,
        created_at  TEXT    NOT NULL
    );
    """

    CLUSTER_ASSIGNMENTS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS cluster_assignments (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
        cluster_id  INTEGER NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
        is_primary  INTEGER NOT NULL DEFAULT 0,
        confidence  REAL    NOT NULL DEFAULT 0.0,
        UNIQUE(entry_id, cluster_id)
    );
    """

    GRAPH_METRICS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS graph_metrics (
        entry_id            INTEGER PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
        degree_centrality   REAL NOT NULL DEFAULT 0.0,
        betweenness         REAL NOT NULL DEFAULT 0.0,
        closeness           REAL NOT NULL DEFAULT 0.0,
        pagerank            REAL NOT NULL DEFAULT 0.0,
        cluster_role        TEXT NOT NULL DEFAULT '',
        updated_at          TEXT NOT NULL DEFAULT ''
    );
    """

    IMPORT_CORRECTIONS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS import_corrections (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        field       TEXT    NOT NULL,
        original    TEXT    NOT NULL,
        corrected   TEXT    NOT NULL,
        frequency   INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT    NOT NULL
    );
    """

    META_SCHEMA = """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT ''
    );
    """

    PDF_ANNOTATIONS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS pdf_annotations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id    INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
        page        INTEGER NOT NULL DEFAULT 0,
        kind        TEXT NOT NULL DEFAULT 'nota',
        text        TEXT NOT NULL DEFAULT '',
        selected_text TEXT NOT NULL DEFAULT '',
        tags        TEXT NOT NULL DEFAULT '',
        pdf_xrefs   TEXT NOT NULL DEFAULT '[]',
        created_at  TEXT NOT NULL,
        modified_at TEXT NOT NULL
    );
    """

    PDF_EXTRACTED_ITEMS_SCHEMA = """
    CREATE TABLE IF NOT EXISTS pdf_extracted_items (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        entry_id        INTEGER NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
        object_type     TEXT NOT NULL DEFAULT 'text',
        content_text    TEXT NOT NULL DEFAULT '',
        file_path       TEXT NOT NULL DEFAULT '',
        page            INTEGER NOT NULL DEFAULT 0,
        bbox_json       TEXT NOT NULL DEFAULT '',
        source          TEXT NOT NULL DEFAULT 'pdf_text',
        confidence      REAL NOT NULL DEFAULT 0.0,
        review_status   TEXT NOT NULL DEFAULT 'pending',
        metadata_json   TEXT NOT NULL DEFAULT '{}',
        created_at      TEXT NOT NULL,
        modified_at     TEXT NOT NULL
    );
    """

    _SCHEMA_VERSION = "2"

    def __init__(self, db_path: Path):
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._conn.execute(self.SCHEMA)
        self._conn.execute(self.GRAPH_SCHEMA)
        self._conn.execute(self.FTS_SCHEMA)
        self._conn.executescript(self.FTS_TRIGGERS)
        # Phase-2 tables (idempotent CREATE IF NOT EXISTS)
        self._conn.execute(self.EMBEDDINGS_SCHEMA)
        self._conn.execute(self.CLUSTERS_SCHEMA)
        self._conn.execute(self.CLUSTER_ASSIGNMENTS_SCHEMA)
        self._conn.execute(self.GRAPH_METRICS_SCHEMA)
        self._conn.execute(self.IMPORT_CORRECTIONS_SCHEMA)
        self._conn.execute(self.META_SCHEMA)
        self._conn.execute(self.PDF_ANNOTATIONS_SCHEMA)
        self._conn.execute(self.PDF_EXTRACTED_ITEMS_SCHEMA)
        self._conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (self._SCHEMA_VERSION,)
        )
        # Safe migrations for columns added in later versions
        for migration in [
            "ALTER TABLE entries ADD COLUMN pub_type               TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE entries ADD COLUMN pdf_path               TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE entries ADD COLUMN is_read                INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE entries ADD COLUMN ai_notes               TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE entries ADD COLUMN ai_topics              TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE entries ADD COLUMN extracted_bibliography TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE entries ADD COLUMN linked_references      TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE entries ADD COLUMN is_editor              INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE entries ADD COLUMN location               TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE pdf_annotations ADD COLUMN selected_text TEXT NOT NULL DEFAULT ''",
            "ALTER TABLE pdf_annotations ADD COLUMN pdf_xrefs TEXT NOT NULL DEFAULT '[]'",
        ]:
            try:
                self._conn.execute(migration)
            except sqlite3.OperationalError:
                pass
                
        # Populate FTS if empty but entries exist
        row = self._conn.execute("SELECT COUNT(*) FROM entries_fts").fetchone()
        if row and row[0] == 0:
            self._conn.execute("""
                INSERT INTO entries_fts(rowid, title, authors, publisher, journal, notes, abstract)
                SELECT id, title, authors, publisher, journal, notes, ai_notes FROM entries;
            """)
        
        self._conn.commit()

    # ── helpers ───────────────────────────────────────────────────────────
    @staticmethod
    def _now() -> str:
        return datetime.datetime.now().isoformat(sep=" ", timespec="seconds")

    @staticmethod
    def _row2dict(row: sqlite3.Row) -> dict:
        return dict(row) if row else {}

    # ── CRUD ──────────────────────────────────────────────────────────────
    @locked
    def create(self, data: dict) -> int:
        now  = self._now()
        cols = list(data.keys()) + ["created_at", "modified_at"]
        vals = list(data.values()) + [now, now]
        ph   = ", ".join("?" * len(cols))
        sql  = f"INSERT INTO entries ({', '.join(cols)}) VALUES ({ph})"
        cur  = self._conn.execute(sql, vals)
        self._conn.commit()
        return cur.lastrowid

    @locked
    def read_all(self, search: str = "", entry_type: str = "") -> list[dict]:
        sql  = "SELECT entries.* FROM entries "
        args = []
        if search:
            sql += "JOIN entries_fts ON entries.id = entries_fts.rowid "
            sql += "WHERE entries_fts MATCH ? "
            # Escape double quotes for FTS
            clean_search = search.replace('"', '""')
            args.append(f'"{clean_search}"*')
        else:
            sql += "WHERE 1=1 "
            
        if entry_type:
            sql += " AND entries.entry_type = ?"
            args.append(entry_type)
            
        if search:
            sql += " ORDER BY bm25(entries_fts) "
        else:
            sql += " ORDER BY entries.authors COLLATE NOCASE, entries.title COLLATE NOCASE"
            
        return [self._row2dict(r) for r in self._conn.execute(sql, args)]

    @locked
    def read_by_id(self, entry_id: int) -> dict:
        row = self._conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return self._row2dict(row)

    @locked
    def get_entries_by_ids(self, entry_ids: list[int]) -> list[dict]:
        """Return multiple entries by their IDs."""
        if not entry_ids:
            return []
        placeholders = ",".join("?" * len(entry_ids))
        sql = f"SELECT * FROM entries WHERE id IN ({placeholders})"
        return [self._row2dict(r) for r in self._conn.execute(sql, entry_ids)]

    @locked
    def update(self, entry_id: int, data: dict) -> None:
        data["modified_at"] = self._now()
        sets = ", ".join(f"{k}=?" for k in data)
        vals = list(data.values()) + [entry_id]
        self._conn.execute(f"UPDATE entries SET {sets} WHERE id=?", vals)
        self._conn.commit()

    @locked
    def delete(self, entry_id: int) -> None:
        self._conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))
        self._conn.commit()

    # ── Queries ───────────────────────────────────────────────────────────
    @locked
    def get_distinct_journals(self) -> list[str]:
        sql = "SELECT DISTINCT journal FROM entries WHERE journal != '' ORDER BY journal COLLATE NOCASE"
        return [r["journal"] for r in self._conn.execute(sql)]

    @locked
    def get_distinct_ai_topics(self) -> list[str]:
        """Return all unique stored AI topic labels, sorted alphabetically."""
        topics: set[str] = set()
        for entry in self.read_all_full():
            raw = entry.get("ai_topics", "")
            if not raw:
                continue
            try:
                items = json.loads(raw)
            except Exception:
                continue
            if not isinstance(items, list):
                continue
            for item in items:
                value = str(item).strip()
                if value:
                    topics.add(value)
        return sorted(topics, key=lambda s: s.lower())

    @locked
    def get_top_publisher_for_journal(self, journal: str) -> str:
        sql = """
            SELECT publisher, COUNT(publisher) as cnt
            FROM entries
            WHERE journal = ? AND publisher != ''
            GROUP BY publisher
            ORDER BY cnt DESC
            LIMIT 1
        """
        row = self._conn.execute(sql, (journal,)).fetchone()
        return row["publisher"] if row else ""

    @locked
    def check_duplicate_title(self, title: str, exclude_id: int | None = None) -> bool:
        if not title.strip():
            return False
        sql  = "SELECT COUNT(*) FROM entries WHERE title = ? COLLATE NOCASE"
        args = [title.strip()]
        if exclude_id is not None:
            sql  += " AND id != ?"
            args.append(exclude_id)
        row = self._conn.execute(sql, tuple(args)).fetchone()
        return row[0] > 0

    @locked
    def check_duplicate_doi(self, doi: str, exclude_id: int | None = None) -> bool:
        """Check if a DOI already exists in the database."""
        if not doi.strip():
            return False
        sql = "SELECT COUNT(*) FROM entries WHERE doi = ? COLLATE NOCASE"
        args: list = [doi.strip()]
        if exclude_id is not None:
            sql += " AND id != ?"
            args.append(exclude_id)
        row = self._conn.execute(sql, tuple(args)).fetchone()
        return row[0] > 0

    @locked
    def find_by_doi(self, doi: str) -> dict | None:
        """Return the entry matching the given DOI, or None."""
        if not doi.strip():
            return None
        row = self._conn.execute(
            "SELECT * FROM entries WHERE doi = ? COLLATE NOCASE", (doi.strip(),)
        ).fetchone()
        return self._row2dict(row) if row else None

    @locked
    def find_by_title(self, title: str) -> dict | None:
        """Return the entry matching the given title (case-insensitive), or None."""
        if not title.strip():
            return None
        row = self._conn.execute(
            "SELECT * FROM entries WHERE title = ? COLLATE NOCASE", (title.strip(),)
        ).fetchone()
        return self._row2dict(row) if row else None

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        """Normalize titles/authors so matching is robust against punctuation and case."""
        if value is None:
            return ""
        value = str(value).strip()
        value = value.replace("&", " and ")
        value = value.replace("—", "-").replace("–", "-")
        value = value.replace(".", " ")
        value = "".join(ch for ch in value.lower() if ch.isalnum() or ch.isspace() or ch in "- ")
        return " ".join(value.split())

    @staticmethod
    def _author_tokens(value: str | list[str] | None) -> set[str]:
        """Return a normalized set of author surnames/tokens for fuzzy comparison."""
        if value is None:
            return set()
        if isinstance(value, list):
            raw = " ".join(str(v) for v in value)
        else:
            raw = str(value)
        parts = []
        for chunk in raw.replace(";", ",").split(","):
            parts.extend(part.strip() for part in chunk.split(" and "))
        tokens: set[str] = set()
        for part in parts:
            part = EntryModel._normalize_text(part)
            if part:
                tokens.add(part)
        return tokens

    @locked
    def match_references(self, references: list[dict]) -> list[dict]:
        """Match LLM reference candidates against the local archive.

        Returns a list of dicts with the keys: "reference", "match", "match_score",
        "match_type". If no record matches, "match" is None and the reference remains
        available as a "phantom" reference for DAG generation.
        """
        known_entries = self.read_all_full()
        matches: list[dict] = []

        for ref in references or []:
            best_match: dict | None = None
            best_score = 0.0
            title = str(ref.get("title") or "").strip()
            authors = ref.get("authors") or []
            year = ref.get("year")
            title_norm = self._normalize_text(title)
            author_tokens = self._author_tokens(authors)

            for entry in known_entries:
                entry_title = str(entry.get("title") or "").strip()
                entry_title_norm = self._normalize_text(entry_title)
                entry_authors = entry.get("authors") or ""
                entry_author_tokens = self._author_tokens(entry_authors)

                score = 0.0
                if entry_title_norm and title_norm:
                    if entry_title_norm == title_norm:
                        score += 0.7
                    elif title_norm in entry_title_norm or entry_title_norm in title_norm:
                        score += 0.5
                    elif len(title_norm) > 4 and entry_title_norm and entry_title_norm[:8] == title_norm[:8]:
                        score += 0.3

                if year not in (None, "", 0):
                    try:
                        entry_year = int(str(entry.get("year") or "").strip()[:4])
                        ref_year = int(str(year).strip()[:4])
                        if ref_year == entry_year:
                            score += 0.2
                    except ValueError:
                        pass

                if author_tokens and entry_author_tokens:
                    overlap = len(author_tokens & entry_author_tokens)
                    if overlap:
                        score += min(0.2, overlap * 0.1)

                if score > best_score:
                    best_score = score
                    best_match = entry

            if best_match is not None and best_score >= 0.55:
                match_type = "exact" if best_score >= 0.8 else "fuzzy"
                matches.append({
                    "reference": ref,
                    "match": best_match,
                    "match_score": round(best_score, 3),
                    "match_type": match_type,
                })
            else:
                matches.append({
                    "reference": ref,
                    "match": None,
                    "match_score": 0.0,
                    "match_type": "phantom",
                })

        return matches

    @locked
    def stats(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*) total, "
            "SUM(entry_type='bibliography') biblio, "
            "SUM(entry_type='sitography') sito, "
            "SUM(entry_type='tesi') tesi "
            "FROM entries"
        ).fetchone()
        return self._row2dict(row)

    @locked
    def read_all_full(self) -> list[dict]:
        """Return all entries (unfiltered, unsorted) — used by the graph builder."""
        return [self._row2dict(r) for r in self._conn.execute("SELECT * FROM entries")]

    @locked
    def get_latest_modified_at(self) -> str | None:
        """Return the most recent modified_at timestamp, or None if empty."""
        row = self._conn.execute(
            "SELECT MAX(modified_at) as latest FROM entries"
        ).fetchone()
        return row["latest"] if row and row["latest"] else None

    # ── PDF link management ───────────────────────────────────────────────
    @locked
    def get_linked_entries(self) -> list[dict]:
        """Return all entries that have a pdf_path set."""
        sql = "SELECT * FROM entries WHERE pdf_path != '' ORDER BY authors COLLATE NOCASE"
        return [self._row2dict(r) for r in self._conn.execute(sql)]

    @locked
    def unlink_pdf(self, entry_id: int) -> None:
        """Remove the pdf_path association from an entry."""
        self._conn.execute("UPDATE entries SET pdf_path='' WHERE id=?", (entry_id,))
        self._conn.commit()

    @locked
    def unlink_all_pdfs(self) -> int:
        """Remove pdf_path from all entries. Returns count of affected rows."""
        cur = self._conn.execute("UPDATE entries SET pdf_path='' WHERE pdf_path != ''")
        self._conn.commit()
        return cur.rowcount

    # ── PDF annotations ──────────────────────────────────────────────────
    @locked
    def get_pdf_annotations(self, entry_id: int) -> list[dict]:
        """Return page notes and reading markers for one entry."""
        rows = self._conn.execute(
            "SELECT * FROM pdf_annotations WHERE entry_id=? "
            "ORDER BY page, id", (entry_id,)
        )
        return [self._row2dict(row) for row in rows]

    @locked
    def save_pdf_annotation(self, entry_id: int, page: int, kind: str,
                            text: str, tags: str = "", selected_text: str = "",
                            annotation_id: int | None = None) -> int:
        """Create or update a PDF annotation associated with an entry."""
        now = self._now()
        if annotation_id is None:
            cur = self._conn.execute(
                "INSERT INTO pdf_annotations "
                "(entry_id, page, kind, text, selected_text, tags, created_at, modified_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (entry_id, max(0, int(page)), kind, text.strip(), selected_text.strip(),
                 tags.strip(), now, now),
            )
            annotation_id = cur.lastrowid
        else:
            self._conn.execute(
                "UPDATE pdf_annotations SET page=?, kind=?, text=?, selected_text=?, tags=?, modified_at=? "
                "WHERE id=? AND entry_id=?",
                (max(0, int(page)), kind, text.strip(), selected_text.strip(), tags.strip(), now,
                 annotation_id, entry_id),
            )
        self._conn.commit()
        return int(annotation_id)

    # ── PDF extracted items ─────────────────────────────────────────────
    @locked
    def get_pdf_extracted_items(self, entry_id: int,
                                object_type: str = "") -> list[dict]:
        """Return extracted PDF items for one entry, ordered by page."""
        sql = "SELECT * FROM pdf_extracted_items WHERE entry_id=?"
        args: list = [entry_id]
        if object_type:
            sql += " AND object_type=?"
            args.append(object_type)
        sql += " ORDER BY page, id"
        return [self._row2dict(row) for row in self._conn.execute(sql, args)]

    @locked
    def save_pdf_extracted_item(self, entry_id: int, object_type: str,
                                content_text: str = "", file_path: str = "",
                                page: int = 0, bbox_json: str = "",
                                source: str = "pdf_text", confidence: float = 0.0,
                                review_status: str = "pending",
                                metadata_json: str = "{}",
                                item_id: int | None = None) -> int:
        """Create or update one extracted PDF item and return its id."""
        now = self._now()
        values = (
            object_type.strip() or "text",
            content_text.strip(),
            file_path.strip(),
            max(0, int(page)),
            bbox_json.strip(),
            source.strip() or "pdf_text",
            max(0.0, min(1.0, float(confidence))),
            review_status.strip() or "pending",
            metadata_json.strip() or "{}",
        )
        if item_id is None:
            cur = self._conn.execute(
                "INSERT INTO pdf_extracted_items "
                "(entry_id, object_type, content_text, file_path, page, bbox_json, "
                "source, confidence, review_status, metadata_json, created_at, modified_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (entry_id, *values, now, now),
            )
            item_id = cur.lastrowid
        else:
            self._conn.execute(
                "UPDATE pdf_extracted_items SET object_type=?, content_text=?, "
                "file_path=?, page=?, bbox_json=?, source=?, confidence=?, "
                "review_status=?, metadata_json=?, modified_at=? "
                "WHERE id=? AND entry_id=?",
                (*values, now, item_id, entry_id),
            )
        self._conn.commit()
        return int(item_id)

    @locked
    def delete_pdf_extracted_item(self, entry_id: int, item_id: int) -> None:
        """Delete one extracted item belonging to an entry."""
        self._conn.execute(
            "DELETE FROM pdf_extracted_items WHERE id=? AND entry_id=?",
            (item_id, entry_id),
        )
        self._conn.commit()

    @locked
    def delete_pdf_annotation(self, annotation_id: int, entry_id: int) -> None:
        """Delete one annotation, scoped to its owning entry."""
        self._conn.execute(
            "DELETE FROM pdf_annotations WHERE id=? AND entry_id=?",
            (annotation_id, entry_id),
        )
        self._conn.commit()

    @locked
    def set_pdf_annotation_xrefs(self, annotation_id: int, entry_id: int,
                                 xrefs: list[int]) -> None:
        """Store the PDF annotation handles so markup can be removed later."""
        self._conn.execute(
            "UPDATE pdf_annotations SET pdf_xrefs=?, modified_at=? WHERE id=? AND entry_id=?",
            (json.dumps([int(xref) for xref in xrefs]), self._now(), annotation_id, entry_id),
        )
        self._conn.commit()

    # ── AI Notes ──────────────────────────────────────────────────────────
    @locked
    def save_ai_notes(self, entry_id: int, json_str: str) -> None:
        """Persist AI-generated notes (JSON string) for an entry."""
        self._conn.execute(
            "UPDATE entries SET ai_notes=?, modified_at=? WHERE id=?",
            (json_str, self._now(), entry_id)
        )
        self._conn.commit()

    @locked
    def get_ai_notes(self, entry_id: int) -> str:
        """Retrieve the stored AI notes JSON string for an entry."""
        row = self._conn.execute(
            "SELECT ai_notes FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        return row["ai_notes"] if row else ""

    @staticmethod
    def _normalize_reference(value: object) -> dict | None:
        """Coerce a raw reference-like object into a safe dict with expected keys."""
        if not isinstance(value, dict):
            return None

        title = str(value.get("title") or "").strip()
        if not title:
            return None

        authors = value.get("authors") or []
        if isinstance(authors, str):
            authors = [p.strip() for p in authors.split(";") if p.strip()]
        authors = [str(a).strip() for a in authors if str(a).strip()]

        year = value.get("year")
        try:
            if year not in (None, "", "null"):
                year = int(year)
            else:
                year = None
        except (TypeError, ValueError):
            year = None

        normalized: dict = {
            "title": title,
            "authors": authors,
            "year": year,
        }

        if "source" in value:
            source = value.get("source")
            source_text = str(source).strip() if source is not None else ""
            normalized["source"] = source_text or None

        return normalized

    @locked
    def save_extracted_bibliography(self, entry_id: int, references: list[dict]) -> None:
        """Persist extracted bibliography entries for one record as JSON."""
        normalized: list[dict] = []
        if isinstance(references, dict):
            references = references.get("references") or references.get("items") or []
        if not isinstance(references, list):
            references = []

        for item in references:
            ref = self._normalize_reference(item)
            if ref is not None:
                normalized.append(ref)

        payload = json.dumps(normalized, ensure_ascii=False)
        self._conn.execute(
            "UPDATE entries SET extracted_bibliography=?, modified_at=? WHERE id=?",
            (payload, self._now(), entry_id),
        )
        self._conn.commit()

    @locked
    def get_extracted_bibliography(self, entry_id: int) -> list[dict]:
        """Return the stored extracted bibliography for one record, or []."""
        row = self._conn.execute(
            "SELECT extracted_bibliography FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        if not row or not row["extracted_bibliography"]:
            return []
        try:
            value = json.loads(row["extracted_bibliography"])
            if not isinstance(value, list):
                return []
            normalized: list[dict] = []
            for item in value:
                ref = self._normalize_reference(item)
                if ref is not None:
                    normalized.append(ref)
            return normalized
        except Exception:
            return []

    @locked
    def save_linked_references(self, entry_id: int, references: list[int]) -> None:
        """Persist linked references (list of IDs) for one record."""
        if not isinstance(references, list):
            references = []
        payload = json.dumps(references)
        self._conn.execute(
            "UPDATE entries SET linked_references=?, modified_at=? WHERE id=?",
            (payload, self._now(), entry_id),
        )
        self._conn.commit()

    @locked
    def get_linked_references(self, entry_id: int) -> list[int]:
        """Return the stored linked references IDs for one record, or [] if none."""
        row = self._conn.execute(
            "SELECT linked_references FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        if not row or not row["linked_references"]:
            return []
        try:
            val = json.loads(row["linked_references"])
            return val if isinstance(val, list) else []
        except Exception:
            return []

    @locked
    def save_ai_topics(self, entry_id: int, topics: list[str]) -> None:
        """Persist the AI-extracted topic tags for an entry."""
        self._conn.execute(
            "UPDATE entries SET ai_topics=? WHERE id=?",
            (json.dumps(topics, ensure_ascii=False), entry_id)
        )
        self._conn.commit()

    @locked
    def get_ai_topics(self, entry_id: int) -> list[str]:
        """Return the AI topics list for an entry, or [] if none."""
        row = self._conn.execute(
            "SELECT ai_topics FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        if not row or not row["ai_topics"]:
            return []
        try:
            return json.loads(row["ai_topics"])
        except Exception:
            return []

    @locked
    def clear_ai_topics(self, entry_id: int | None = None) -> None:
        """Remove AI topics for one entry or for all entries when entry_id is None."""
        if entry_id is None:
            self._conn.execute("UPDATE entries SET ai_topics = '[]', modified_at = ?", (self._now(),))
        else:
            self._conn.execute(
                "UPDATE entries SET ai_topics = '[]', modified_at = ? WHERE id = ?",
                (self._now(), entry_id),
            )
        self._conn.commit()

    @locked
    def clear_all_ai_topics(self) -> int:
        """Delete all AI topic assignments across the table. Returns number of rows cleared."""
        cur = self._conn.execute("UPDATE entries SET ai_topics = '[]', modified_at = ? WHERE ai_topics != '[]'", (self._now(),))
        self._conn.commit()
        return cur.rowcount

    # ── Graph state (DB persistence) ──────────────────────────────────────
    @locked
    def save_graph(self, graph_json_str: str, mode: str = "") -> None:
        """Upsert the graph JSON blob into the graph_state table (single row)."""
        self._conn.execute(
            """
            INSERT INTO graph_state (id, graph_json, built_at, mode)
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                graph_json = excluded.graph_json,
                built_at   = excluded.built_at,
                mode       = excluded.mode
            """,
            (graph_json_str, self._now(), mode)
        )
        self._conn.commit()

    @locked
    def load_graph(self) -> tuple[str, str, str] | None:
        """Return (graph_json_str, built_at, mode) or None if not stored."""
        row = self._conn.execute(
            "SELECT graph_json, built_at, mode FROM graph_state WHERE id=1"
        ).fetchone()
        if not row or not row["graph_json"]:
            return None
        return (row["graph_json"], row["built_at"], row["mode"])

    # ══════════════════════════════════════════════════════════════════════
    # ── EMBEDDINGS ────────────────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════

    @locked
    def save_embedding(self, entry_id: int, vector_blob: bytes,
                       dimensions: int, model_name: str = "") -> None:
        """Upsert an embedding vector (as raw bytes) for an entry."""
        self._conn.execute(
            """
            INSERT INTO embeddings (entry_id, model_name, vector, dimensions, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(entry_id) DO UPDATE SET
                model_name = excluded.model_name,
                vector     = excluded.vector,
                dimensions = excluded.dimensions,
                created_at = excluded.created_at
            """,
            (entry_id, model_name, vector_blob, dimensions, self._now())
        )
        self._conn.commit()

    @locked
    def get_embedding(self, entry_id: int) -> tuple[bytes, int, str] | None:
        """Return (vector_blob, dimensions, model_name) or None."""
        row = self._conn.execute(
            "SELECT vector, dimensions, model_name FROM embeddings WHERE entry_id=?",
            (entry_id,)
        ).fetchone()
        if not row:
            return None
        return (row["vector"], row["dimensions"], row["model_name"])

    @locked
    def get_all_embeddings(self) -> list[tuple[int, bytes, int]]:
        """Return [(entry_id, vector_blob, dimensions), ...] for all entries."""
        rows = self._conn.execute(
            "SELECT entry_id, vector, dimensions FROM embeddings ORDER BY entry_id"
        ).fetchall()
        return [(r["entry_id"], r["vector"], r["dimensions"]) for r in rows]

    @locked
    def get_entries_without_embeddings(self) -> list[int]:
        """Return entry IDs that have no embedding yet."""
        rows = self._conn.execute(
            "SELECT id FROM entries WHERE id NOT IN (SELECT entry_id FROM embeddings)"
        ).fetchall()
        return [r["id"] for r in rows]

    @locked
    def delete_embedding(self, entry_id: int) -> None:
        """Remove embedding for an entry."""
        self._conn.execute("DELETE FROM embeddings WHERE entry_id=?", (entry_id,))
        self._conn.commit()

    # ══════════════════════════════════════════════════════════════════════
    # ── CLUSTERS ──────────────────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════

    @locked
    def create_cluster(self, label: str, color: str = "#7c3aed",
                       description: str = "", density: float = 0.0) -> int:
        """Create a cluster and return its id."""
        cur = self._conn.execute(
            """INSERT INTO clusters (label, color, description, paper_count, density, created_at)
               VALUES (?, ?, ?, 0, ?, ?)""",
            (label, color, description, density, self._now())
        )
        self._conn.commit()
        return cur.lastrowid

    @locked
    def update_cluster(self, cluster_id: int, **kwargs) -> None:
        """Update cluster fields (label, color, description, paper_count, density)."""
        if not kwargs:
            return
        sets = ", ".join(f"{k}=?" for k in kwargs)
        vals = list(kwargs.values()) + [cluster_id]
        self._conn.execute(f"UPDATE clusters SET {sets} WHERE id=?", vals)
        self._conn.commit()

    @locked
    def get_all_clusters(self) -> list[dict]:
        """Return all clusters ordered by paper count descending."""
        rows = self._conn.execute(
            "SELECT * FROM clusters ORDER BY paper_count DESC"
        ).fetchall()
        return [self._row2dict(r) for r in rows]

    @locked
    def delete_all_clusters(self) -> None:
        """Remove all clusters and assignments (full reset before re-clustering)."""
        self._conn.execute("DELETE FROM cluster_assignments")
        self._conn.execute("DELETE FROM clusters")
        self._conn.commit()

    @locked
    def delete_cluster(self, cluster_id: int) -> None:
        """Delete a single cluster and its assignments."""
        self._conn.execute("DELETE FROM cluster_assignments WHERE cluster_id=?", (cluster_id,))
        self._conn.execute("DELETE FROM clusters WHERE id=?", (cluster_id,))
        self._conn.commit()

    # ── Cluster Assignments ───────────────────────────────────────────────

    @locked
    def assign_cluster(self, entry_id: int, cluster_id: int,
                       is_primary: bool = False, confidence: float = 0.0) -> None:
        """Assign an entry to a cluster (upsert)."""
        self._conn.execute(
            """INSERT INTO cluster_assignments (entry_id, cluster_id, is_primary, confidence)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(entry_id, cluster_id) DO UPDATE SET
                   is_primary = excluded.is_primary,
                   confidence = excluded.confidence""",
            (entry_id, cluster_id, int(is_primary), confidence)
        )
        self._conn.commit()

    @locked
    def get_entry_clusters(self, entry_id: int) -> list[dict]:
        """Return cluster assignments for an entry, primary first."""
        rows = self._conn.execute(
            """SELECT ca.cluster_id, ca.is_primary, ca.confidence,
                      c.label, c.color
               FROM cluster_assignments ca
               JOIN clusters c ON c.id = ca.cluster_id
               WHERE ca.entry_id = ?
               ORDER BY ca.is_primary DESC, ca.confidence DESC""",
            (entry_id,)
        ).fetchall()
        return [self._row2dict(r) for r in rows]

    @locked
    def get_cluster_entries(self, cluster_id: int) -> list[int]:
        """Return entry IDs belonging to a cluster."""
        rows = self._conn.execute(
            "SELECT entry_id FROM cluster_assignments WHERE cluster_id=? ORDER BY confidence DESC",
            (cluster_id,)
        ).fetchall()
        return [r["entry_id"] for r in rows]

    @locked
    def get_primary_cluster(self, entry_id: int) -> dict | None:
        """Return the primary cluster for an entry, or None."""
        row = self._conn.execute(
            """SELECT ca.cluster_id, ca.confidence, c.label, c.color
               FROM cluster_assignments ca
               JOIN clusters c ON c.id = ca.cluster_id
               WHERE ca.entry_id = ? AND ca.is_primary = 1""",
            (entry_id,)
        ).fetchone()
        return self._row2dict(row) if row else None

    @locked
    def get_all_assignments(self) -> list[dict]:
        """Return all cluster assignments with cluster metadata."""
        rows = self._conn.execute(
            """SELECT ca.entry_id, ca.cluster_id, ca.is_primary, ca.confidence,
                      c.label, c.color
               FROM cluster_assignments ca
               JOIN clusters c ON c.id = ca.cluster_id
               ORDER BY ca.entry_id, ca.is_primary DESC"""
        ).fetchall()
        return [self._row2dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════════════════
    # ── GRAPH METRICS ─────────────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════

    @locked
    def save_metrics(self, entry_id: int, degree_centrality: float = 0.0,
                     betweenness: float = 0.0, closeness: float = 0.0,
                     pagerank: float = 0.0, cluster_role: str = "") -> None:
        """Upsert graph metrics for an entry."""
        self._conn.execute(
            """INSERT INTO graph_metrics
                   (entry_id, degree_centrality, betweenness, closeness, pagerank,
                    cluster_role, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(entry_id) DO UPDATE SET
                   degree_centrality = excluded.degree_centrality,
                   betweenness       = excluded.betweenness,
                   closeness         = excluded.closeness,
                   pagerank          = excluded.pagerank,
                   cluster_role      = excluded.cluster_role,
                   updated_at        = excluded.updated_at""",
            (entry_id, degree_centrality, betweenness, closeness,
             pagerank, cluster_role, self._now())
        )
        self._conn.commit()

    @locked
    def save_metrics_batch(self, metrics_list: list[dict]) -> None:
        """Bulk upsert graph metrics. Each dict must have 'entry_id' + metric fields."""
        for m in metrics_list:
            self.save_metrics(
                entry_id=m["entry_id"],
                degree_centrality=m.get("degree_centrality", 0.0),
                betweenness=m.get("betweenness", 0.0),
                closeness=m.get("closeness", 0.0),
                pagerank=m.get("pagerank", 0.0),
                cluster_role=m.get("cluster_role", ""),
            )

    @locked
    def get_metrics(self, entry_id: int) -> dict | None:
        """Return graph metrics for an entry, or None."""
        row = self._conn.execute(
            "SELECT * FROM graph_metrics WHERE entry_id=?", (entry_id,)
        ).fetchone()
        return self._row2dict(row) if row else None

    @locked
    def get_all_metrics(self) -> dict[int, dict]:
        """Return {entry_id: metrics_dict} for all entries with metrics."""
        rows = self._conn.execute("SELECT * FROM graph_metrics").fetchall()
        return {r["entry_id"]: self._row2dict(r) for r in rows}

    @locked
    def clear_metrics(self) -> None:
        """Remove all cached metrics (before recomputation)."""
        self._conn.execute("DELETE FROM graph_metrics")
        self._conn.commit()

    # ══════════════════════════════════════════════════════════════════════
    # ── IMPORT CORRECTIONS (Learning System) ──────────────────────────────
    # ══════════════════════════════════════════════════════════════════════

    @locked
    def record_correction(self, field: str, original: str, corrected: str) -> None:
        """Record a user correction. Increments frequency if already known."""
        existing = self._conn.execute(
            "SELECT id, frequency FROM import_corrections WHERE field=? AND original=? AND corrected=?",
            (field, original, corrected)
        ).fetchone()
        if existing:
            self._conn.execute(
                "UPDATE import_corrections SET frequency = frequency + 1 WHERE id=?",
                (existing["id"],)
            )
        else:
            self._conn.execute(
                "INSERT INTO import_corrections (field, original, corrected, frequency, created_at) VALUES (?, ?, ?, 1, ?)",
                (field, original, corrected, self._now())
            )
        self._conn.commit()

    @locked
    def get_corrections(self, field: str) -> dict[str, str]:
        """Return {original: corrected} mapping for a field, most frequent first."""
        rows = self._conn.execute(
            "SELECT original, corrected FROM import_corrections WHERE field=? ORDER BY frequency DESC",
            (field,)
        ).fetchall()
        return {r["original"]: r["corrected"] for r in rows}

    @locked
    def get_all_corrections(self) -> list[dict]:
        """Return all corrections sorted by frequency."""
        rows = self._conn.execute(
            "SELECT * FROM import_corrections ORDER BY frequency DESC"
        ).fetchall()
        return [self._row2dict(r) for r in rows]

    # ══════════════════════════════════════════════════════════════════════
    # ── META ──────────────────────────────────────────────────────────────
    # ══════════════════════════════════════════════════════════════════════

    @locked
    def get_meta(self, key: str, default: str = "") -> str:
        """Read a value from the meta key-value table."""
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    @locked
    def set_meta(self, key: str, value: str) -> None:
        """Upsert a value in the meta key-value table."""
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value)
        )
        self._conn.commit()

    @locked
    def close(self):
        self._conn.close()

