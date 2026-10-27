"""Keyed pseudonyms. HMAC-SHA256 with a secret kept outside the repository.

The same review always maps to the same pseudonym (so re-runs are stable), and nobody without the
key can recompute or reverse it. The key is created once on first use.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from pathlib import Path

from .. import config

_KEY: bytes | None = None


def _key(path: Path | None = None) -> bytes:
    global _KEY
    if os.environ.get("STEWARD_TEST_PSEUDONYM_KEY"):
        return os.environ["STEWARD_TEST_PSEUDONYM_KEY"].encode()
    if _KEY is None:
        p = path or config.PSEUDONYM_KEY_FILE
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(secrets.token_hex(32), encoding="utf-8")
        _KEY = p.read_text(encoding="utf-8").strip().encode()
    return _KEY


def pseudonym(prefix: str, *parts: str) -> str:
    msg = "\x1f".join(parts).encode("utf-8")
    return f"{prefix}-" + hmac.new(_key(), msg, hashlib.sha256).hexdigest()[:10]


def review_id(store: str, package: str, store_review_id: str) -> str:
    return pseudonym("R", store, package, store_review_id)
