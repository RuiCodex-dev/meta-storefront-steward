"""Paths and credential locations.

Credentials are read at run time from files outside the repository and are never logged.
Every path can be overridden with an environment variable so tests and other machines work.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("STEWARD_DATA", ROOT / "data"))          # git-ignored
RAW = DATA / "raw"                                                   # store exports, never leave the machine
PRIVATE = DATA / "private"                                           # re-identification map only
DB_PATH = Path(os.environ.get("STEWARD_DB", DATA / "clean" / "steward.db"))
DEMO = os.environ.get("STEWARD_DEMO") == "1"     # demo database: synthetic reviews only, store sync disabled

KEYS_DIR = Path(os.environ.get("STEWARD_KEYS", Path.home() / ".ruicodex-keys"))
META_KEY_FILE = KEYS_DIR / "storefront-steward" / "meta.json"
BASETEN_KEY_FILE = KEYS_DIR / "baseten.json"
ANTHROPIC_KEY_FILE = KEYS_DIR / "anthropic-site-chat.json"   # Rui Codex's own API credit
PSEUDONYM_KEY_FILE = KEYS_DIR / "storefront-steward" / "pseudonym.key"
PLAY_SERVICE_ACCOUNT = Path(os.environ.get(
    "STEWARD_PLAY_SA",
    Path.home() / ".claude" / "mcp-servers" / "app-publish-mcp" / "service-account.json"))

META_BASE_URL = "https://api.meta.ai/v1"
BASETEN_BASE_URL = "https://inference.baseten.co/v1"


class MissingKey(RuntimeError):
    pass


def _read_json(path: Path) -> dict:
    if not path.exists():
        raise MissingKey(f"no key file at {path.name} under STEWARD_KEYS; browsing works without keys, model calls "
                         f"need a Meta Model API key (see the README)")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def meta_api_key() -> str:
    return _read_json(META_KEY_FILE)["api_key"]


def anthropic_api_key() -> str:
    return _read_json(ANTHROPIC_KEY_FILE)["api_key"]


def baseten_api_key() -> str:
    return _read_json(BASETEN_KEY_FILE)["api_key"]


def ensure_dirs() -> None:
    for p in (RAW, PRIVATE, DB_PATH.parent):
        p.mkdir(parents=True, exist_ok=True)
