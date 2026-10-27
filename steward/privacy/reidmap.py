"""The only link from a pseudonym back to a store review id.

Kept in its own SQLite file under data/private/. Exactly one caller is allowed: the store writer that
posts a reply the developer approved. Nothing else imports this module (a test enforces it).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .. import config

_PATH = config.PRIVATE / "reidmap.sqlite"


def _con(path: Path | None = None) -> sqlite3.Connection:
    p = path or _PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE IF NOT EXISTS reid (pseudonym TEXT PRIMARY KEY, store TEXT, package TEXT, "
                "store_review_id TEXT)")
    return con


def put(pseudonym: str, store: str, package: str, store_review_id: str, path: Path | None = None) -> None:
    con = _con(path)
    con.execute("INSERT OR REPLACE INTO reid VALUES (?,?,?,?)", (pseudonym, store, package, store_review_id))
    con.commit()
    con.close()


def resolve(pseudonym: str, path: Path | None = None) -> tuple[str, str, str] | None:
    con = _con(path)
    row = con.execute("SELECT store, package, store_review_id FROM reid WHERE pseudonym=?", (pseudonym,)).fetchone()
    con.close()
    return tuple(row) if row else None
