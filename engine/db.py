"""
Database layer — SQLite with WAL mode and a per-thread connection pool.

Design decisions:
  • threading.local()  — each thread reuses ONE connection (no open/close per
    call), which is safe for SQLite and eliminates connection-setup overhead in
    the ThreadPoolExecutor used by the fetcher.
  • pathlib             — all file paths are Path objects; DB_PATH is resolved
    at import time so os.makedirs is called once.
  • WAL + NORMAL sync  — survives concurrent reads during a write without
    blocking the FastAPI event loop.
  • Schema migration    — _safe_add_column() lets the DB upgrade in-place when
    new columns are added (e.g. entity_type was buyer_type in v4).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

from config import DB_PATH

# ── Connection pool (one connection per thread) ───────────────────────────────

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Return (or create) the per-thread SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


# ── Schema helpers ────────────────────────────────────────────────────────────

def _safe_add_column(conn: sqlite3.Connection, table: str, col: str, typedef: str) -> None:
    """Add a column if it doesn't already exist (idempotent migration)."""
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
    except sqlite3.OperationalError:
        pass  # Column already exists


# ── Database initialisation ───────────────────────────────────────────────────

def init_db() -> None:
    """Create tables and apply any pending migrations."""
    conn = _conn()

    # leads ───────────────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT,
            location    TEXT,
            website     TEXT UNIQUE,
            email       TEXT,
            phone       TEXT,
            all_emails  TEXT    DEFAULT '[]',
            all_phones  TEXT    DEFAULT '[]',
            keywords    TEXT,
            entity_type TEXT,
            description TEXT,
            extra_data  TEXT    DEFAULT '{}',
            score       INTEGER DEFAULT 0,
            status      TEXT    DEFAULT 'new',
            notes       TEXT    DEFAULT '',
            run_id      INTEGER,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # url_cache — skip URLs already processed in earlier runs ─────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS url_cache (
            url        TEXT PRIMARY KEY,
            status     TEXT    DEFAULT 'ok',
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # run_history ─────────────────────────────────────────────────────────────
    conn.execute("""
        CREATE TABLE IF NOT EXISTS runs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            finished_at  TIMESTAMP,
            params       TEXT    DEFAULT '{}',
            urls_found   INTEGER DEFAULT 0,
            urls_fetched INTEGER DEFAULT 0,
            leads_saved  INTEGER DEFAULT 0,
            leads_skip   INTEGER DEFAULT 0,
            status       TEXT    DEFAULT 'running'
        )
    """)

    # ── Migrations: bring existing v4 DBs up to date ─────────────────────────
    _safe_add_column(conn, "leads", "all_emails",  "TEXT DEFAULT '[]'")
    _safe_add_column(conn, "leads", "all_phones",  "TEXT DEFAULT '[]'")
    _safe_add_column(conn, "leads", "status",      "TEXT DEFAULT 'new'")
    _safe_add_column(conn, "leads", "notes",       "TEXT DEFAULT ''")
    _safe_add_column(conn, "leads", "run_id",      "INTEGER")
    _safe_add_column(conn, "leads", "extra_data",  "TEXT DEFAULT '{}'")
    # Rename buyer_type → entity_type (add new column; old data stays in buyer_type)
    _safe_add_column(conn, "leads", "entity_type", "TEXT")
    _safe_add_column(conn, "leads", "keywords",    "TEXT")

    conn.commit()


# ── URL Cache ─────────────────────────────────────────────────────────────────

def is_url_cached(url: str) -> bool:
    return _conn().execute(
        "SELECT 1 FROM url_cache WHERE url = ?", (url,)
    ).fetchone() is not None


def cache_url(url: str, status: str = "ok") -> None:
    conn = _conn()
    conn.execute(
        "INSERT OR REPLACE INTO url_cache (url, status, fetched_at) "
        "VALUES (?, ?, CURRENT_TIMESTAMP)",
        (url, status),
    )
    conn.commit()


def count_cached_urls() -> int:
    return _conn().execute("SELECT COUNT(*) FROM url_cache").fetchone()[0]


def clear_url_cache() -> None:
    conn = _conn()
    conn.execute("DELETE FROM url_cache")
    conn.commit()


# ── Run History ───────────────────────────────────────────────────────────────

def start_run(params: dict[str, Any]) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO runs (params) VALUES (?)",
        (json.dumps(params, default=str),),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(
    run_id:       int,
    urls_found:   int,
    urls_fetched: int,
    leads_saved:  int,
    leads_skip:   int,
    status:       str = "done",
) -> None:
    conn = _conn()
    conn.execute(
        """UPDATE runs
           SET finished_at = CURRENT_TIMESTAMP,
               urls_found = ?, urls_fetched = ?,
               leads_saved = ?, leads_skip = ?, status = ?
           WHERE id = ?""",
        (urls_found, urls_fetched, leads_saved, leads_skip, status, run_id),
    )
    conn.commit()


def get_runs(limit: int = 10) -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Leads ─────────────────────────────────────────────────────────────────────

def insert_lead(lead: dict[str, Any]) -> int:
    """Insert a lead and return its new id. Raises on UNIQUE constraint."""
    conn = _conn()
    # Separate known columns from extra schema fields
    extra = {
        k: v for k, v in lead.items()
        if k not in {
            "company", "location", "website", "email", "phone",
            "all_emails", "all_phones", "keywords", "entity_type",
            "description", "score", "status", "run_id",
        }
    }

    cur = conn.execute(
        """INSERT INTO leads
               (company, location, website, email, phone,
                all_emails, all_phones, keywords, entity_type,
                description, extra_data, score, status, run_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?)""",
        (
            lead.get("company"),
            lead.get("location"),
            lead.get("website"),
            lead.get("email"),
            lead.get("phone"),
            json.dumps(lead.get("all_emails") or []),
            json.dumps(lead.get("all_phones") or []),
            ", ".join(lead.get("keywords") or []),
            lead.get("entity_type"),
            lead.get("description"),
            json.dumps(extra),
            lead.get("score", 0),
            lead.get("run_id"),
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_lead(
    lead_id: int,
    status: str | None = None,
    notes:  str | None = None,
) -> None:
    conn = _conn()
    if status is not None and notes is not None:
        conn.execute(
            "UPDATE leads SET status = ?, notes = ? WHERE id = ?",
            (status, notes, lead_id),
        )
    elif status is not None:
        conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
    elif notes is not None:
        conn.execute("UPDATE leads SET notes = ? WHERE id = ?", (notes, lead_id))
    conn.commit()


def get_all_leads() -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM leads ORDER BY score DESC, created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_lead(lead_id: int) -> dict | None:
    row = _conn().execute(
        "SELECT * FROM leads WHERE id = ?", (lead_id,)
    ).fetchone()
    return dict(row) if row else None


def clear_leads() -> None:
    conn = _conn()
    conn.execute("DELETE FROM leads")
    conn.commit()


def count_leads() -> int:
    return _conn().execute("SELECT COUNT(*) FROM leads").fetchone()[0]


def get_stats() -> dict[str, Any]:
    conn = _conn()
    total     = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
    avg_score = conn.execute("SELECT AVG(score) FROM leads").fetchone()[0] or 0

    by_location = conn.execute("""
        SELECT location, COUNT(*) AS cnt FROM leads
        WHERE location IS NOT NULL GROUP BY location ORDER BY cnt DESC LIMIT 10
    """).fetchall()

    by_entity_type = conn.execute("""
        SELECT entity_type, COUNT(*) AS cnt FROM leads
        WHERE entity_type IS NOT NULL GROUP BY entity_type ORDER BY cnt DESC
    """).fetchall()

    by_status = conn.execute("""
        SELECT status, COUNT(*) AS cnt FROM leads GROUP BY status
    """).fetchall()

    score_dist = {
        "high":   conn.execute("SELECT COUNT(*) FROM leads WHERE score >= 80").fetchone()[0],
        "medium": conn.execute("SELECT COUNT(*) FROM leads WHERE score >= 60 AND score < 80").fetchone()[0],
        "low":    conn.execute("SELECT COUNT(*) FROM leads WHERE score < 60").fetchone()[0],
    }

    cached_urls = conn.execute("SELECT COUNT(*) FROM url_cache").fetchone()[0]

    return {
        "total":          total,
        "avg_score":      round(avg_score, 1),
        "by_location":    [dict(r) for r in by_location],
        "by_entity_type": [dict(r) for r in by_entity_type],
        "by_status":      [dict(r) for r in by_status],
        "score_dist":     score_dist,
        "cached_urls":    cached_urls,
    }
