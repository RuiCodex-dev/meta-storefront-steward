"""A demo database anyone can open without keys: synthetic reviews only, plus the studio's own crash and release records.

Why it exists: the real database holds pseudonymised store reviews and never leaves the developer's machine
(`data/` is git-ignored). Judges and a clean clone still need to see the product work, so `demo/` carries, as
reviewable JSON lines:
  * reviews written by Muse Spark Open (held-out synthetic set; `store` = "synthetic", ids "S-..."),
    re-scanned for personal-data patterns before export;
  * the studio's own Play crash/ANR issues and releases (no user data: library, location, version, counts);
  * the outputs of ONE recorded agent pass over exactly that data (triage, issues, drafts, tickets, steps, receipts).
Store sync is disabled in demo mode (STEWARD_DEMO=1), and the page carries a banner saying every review is synthetic.

    python -m steward.demo source   # build data/demo/source.db from the real database (developer only)
    python -m steward.demo export   # write demo/*.jsonl from data/demo/source.db after the recorded pass
    python -m steward.demo merge    # add the recorded pass's receipts to the main ledger (developer only)
    python -m steward.demo load     # build data/demo/steward_demo.db from demo/*.jsonl (anyone)
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from pathlib import Path

from . import config, db
from .privacy import scan

DEMO_DIR = config.ROOT / "demo"
SOURCE_DB = config.DATA / "demo" / "source.db"
DEMO_DB = config.DATA / "demo" / "steward_demo.db"
TABLES = ["items", "labels", "crash_issues", "releases", "clusters", "drafts", "agent_steps", "receipts", "audit"]
SEED = 20261030
N_ACTIONABLE, N_OTHER = 150, 50


def build_source() -> Path:
    """Pick a seeded sample of held-out synthetic reviews and copy our own crash/release records, nothing else."""
    real = db.connect()
    SOURCE_DB.parent.mkdir(parents=True, exist_ok=True)
    if SOURCE_DB.exists():
        SOURCE_DB.unlink()
    out = db.connect(SOURCE_DB)
    out.execute("CREATE TABLE IF NOT EXISTS agent_steps (run_id TEXT, step INTEGER, ts TEXT, tool TEXT, args TEXT, "
                "result TEXT, cost_usd REAL)")
    rows = real.execute("SELECT i.*, l.category FROM items i JOIN splits s ON s.item_id=i.id JOIN labels l ON "
                        "l.item_id=i.id AND l.source='gold_claude' WHERE s.split='test_synth' ORDER BY i.id").fetchall()
    # every field, not only the text: a version string like "2.4.1(412)@google-pl" reads as a handle
    rows = [r for r in rows if not scan(json.dumps(dict(r), ensure_ascii=False))]
    act = [r for r in rows if r["category"] not in ("praise", "spam_or_offtopic")]
    other = [r for r in rows if r["category"] in ("praise", "spam_or_offtopic")]
    rnd = random.Random(SEED)
    pick = rnd.sample(act, min(N_ACTIONABLE, len(act))) + rnd.sample(other, min(N_OTHER, len(other)))
    cols = [c[1] for c in real.execute("PRAGMA table_info(items)")]
    for r in pick:
        d = dict(r)
        d["synthetic"] = 0          # the demo FEED: every item here is synthetic, marked by store and id prefix
        assert d["store"] == "synthetic" and d["id"].startswith("S-")
        out.execute(f"INSERT INTO items({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", [d[c] for c in cols])
    for t in ("crash_issues", "releases"):
        rs = real.execute(f"SELECT * FROM {t}").fetchall()
        if rs:
            out.executemany(f"INSERT INTO {t} VALUES ({','.join('?' * len(rs[0].keys()))})", [tuple(x) for x in rs])
    out.commit()
    print(f"source: {len(pick)} synthetic reviews, crash issues and releases -> {SOURCE_DB}")
    return SOURCE_DB


def merge_receipts(src: Path = SOURCE_DB) -> int:
    """Copy the receipts of a recorded demo pass into the main ledger, so the budget cap sees every cent."""
    con, main = db.connect(src), db.connect()
    rows = con.execute("SELECT ts,provider,model,mode,purpose,input_tokens,cached_tokens,output_tokens,images,frames,"
                       "cost_usd,latency_ms,prompt_sha,status FROM receipts").fetchall()
    have = {tuple(r) for r in main.execute("SELECT ts,provider,model,mode,purpose,input_tokens,cached_tokens,"
                                           "output_tokens,images,frames,cost_usd,latency_ms,prompt_sha,status "
                                           "FROM receipts WHERE purpose LIKE 'demo:%' OR ts >= ?",
                                           (min((r[0] for r in rows), default="9"),))}
    new = [tuple(r) for r in rows if tuple(r) not in have]
    main.executemany("INSERT INTO receipts(ts,provider,model,mode,purpose,input_tokens,cached_tokens,output_tokens,"
                     "images,frames,cost_usd,latency_ms,prompt_sha,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", new)
    main.commit()
    print(f"merged {len(new)} demo receipts into the main ledger")
    return len(new)


def export(src: Path = SOURCE_DB) -> None:
    con = db.connect(src)
    DEMO_DIR.mkdir(exist_ok=True)
    for t in TABLES:
        try:
            rows = [dict(r) for r in con.execute(f"SELECT * FROM {t}")]
        except sqlite3.OperationalError:
            rows = []
        for r in rows:   # the export is public: nothing in it may carry a personal-data pattern
            hits = scan(json.dumps(r, ensure_ascii=False))
            assert not hits, f"{t}: personal-data pattern {hits} in an exported row"
        with open(DEMO_DIR / f"{t}.jsonl", "w", encoding="utf-8", newline="\n") as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        print(f"{t}: {len(rows)} rows")


def load(out: Path = DEMO_DB) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    con = db.connect(out)
    con.execute("CREATE TABLE IF NOT EXISTS agent_steps (run_id TEXT, step INTEGER, ts TEXT, tool TEXT, args TEXT, "
                "result TEXT, cost_usd REAL)")
    for t in TABLES:
        p = DEMO_DIR / f"{t}.jsonl"
        if not p.exists():
            continue
        rows = [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            continue
        cols = list(rows[0].keys())
        con.executemany(f"INSERT INTO {t}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                        [[r.get(c) for c in cols] for r in rows])
    con.commit()
    print(f"demo database -> {out}")
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "load"
    {"source": build_source, "export": export, "load": load, "merge": merge_receipts}[cmd]()
