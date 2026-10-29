"""SQLite storage. One file for pseudonymised records, a separate file for the re-identification map.

The clean database never contains a store review id, an author name or a user id: only HMAC pseudonyms.
The only link back to the store lives in `data/private/reidmap.sqlite`, opened solely by `reidmap.py`.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,      -- pseudonym R-xxxxxxxxxx
    store         TEXT NOT NULL,         -- play | appstore | synthetic
    package       TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'review',
    rating        INTEGER,
    lang          TEXT,
    title         TEXT,                  -- scrubbed
    text          TEXT NOT NULL,         -- scrubbed
    text_en       TEXT,                  -- store-provided English translation, scrubbed (Play only)
    version_code  INTEGER,
    version_name  TEXT,
    device        TEXT,
    os_version    TEXT,
    territory     TEXT,
    created_at    TEXT,
    modified_at   TEXT,
    dev_reply     TEXT,                  -- our own earlier reply (scrubbed), style examples
    dev_reply_at  TEXT,
    scrub_hits    TEXT,                  -- JSON list of placeholder types inserted by the scrubber
    synthetic     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_pkg ON items(package);

CREATE TABLE IF NOT EXISTS releases (
    package TEXT, track TEXT, name TEXT, status TEXT, version_codes TEXT, notes TEXT, fetched_at TEXT,
    PRIMARY KEY (package, track, name)
);

CREATE TABLE IF NOT EXISTS crash_issues (
    package TEXT, issue_id TEXT, type TEXT, cause TEXT, location TEXT,
    first_version INTEGER, last_version INTEGER, distinct_users INTEGER, error_reports INTEGER,
    fetched_at TEXT, PRIMARY KEY (package, issue_id)
);

CREATE TABLE IF NOT EXISTS vitals (
    package TEXT, metric TEXT, version_code TEXT, day TEXT, value REAL, users INTEGER,
    PRIMARY KEY (package, metric, version_code, day)
);

CREATE TABLE IF NOT EXISTS labels (
    item_id TEXT, source TEXT, category TEXT, severity INTEGER, language TEXT, gloss TEXT,
    raw TEXT, created_at TEXT, PRIMARY KEY (item_id, source)
);

CREATE TABLE IF NOT EXISTS splits (item_id TEXT PRIMARY KEY, split TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT, provider TEXT, model TEXT, mode TEXT, purpose TEXT,
    input_tokens INTEGER, cached_tokens INTEGER, output_tokens INTEGER,
    images INTEGER, frames INTEGER, cost_usd REAL, latency_ms INTEGER,
    prompt_sha TEXT, status TEXT
);

CREATE TABLE IF NOT EXISTS clusters (
    id TEXT PRIMARY KEY, package TEXT, run_id TEXT, title TEXT, summary TEXT, severity INTEGER,
    item_ids TEXT, languages TEXT, crash_issue_ids TEXT, first_seen_version TEXT,
    evidence TEXT, link_rule TEXT, confidence REAL, created_at TEXT
);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT, cluster_id TEXT, kind TEXT, lang TEXT, text TEXT, cites TEXT,
    verifier TEXT, status TEXT DEFAULT 'pending', edited_text TEXT,
    created_at TEXT, decided_at TEXT, posted_at TEXT, post_result TEXT
);

CREATE TABLE IF NOT EXISTS app_context (
    package TEXT, language TEXT, title TEXT, short_description TEXT, full_description TEXT, fetched_at TEXT,
    PRIMARY KEY (package, language)
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, actor TEXT, action TEXT, target TEXT, detail TEXT
);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    p = Path(path) if path else config.DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    _migrate(con)
    return con


# Columns added after the first schema; ALTER is idempotent through the column check.
_ADDED_COLUMNS = {
    "drafts": [("attempts", "TEXT")],          # JSON list: every draft the model wrote and what the verifier said
}


def _migrate(con: sqlite3.Connection) -> None:
    for table, cols in _ADDED_COLUMNS.items():
        have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for name, typ in cols:
            if name not in have:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
    con.commit()
