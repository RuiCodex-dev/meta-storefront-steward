"""How often do the agent's deterministic checkers stop Muse Spark, and does one guided revision fix it?

Runs in a COPY of the database (data/eval/agent_checks.db) so the real approval queue is never touched; the copy's
new receipts are merged back into the main ledger afterwards, so the budget cap and the receipts page stay complete.

Replies: a seeded sample of held-out synthetic ACTIONABLE reviews, PER_LANG per language (written by Muse Spark Open,
never used for training). Tickets: every crash-backed issue of the latest clustering run.
Output: results/agent_checks.json (counts only, no review text) and a table in results/AGENT_CHECKS.md.

    python scripts/eval_agent_checks.py [--per-lang 12]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import random
import re
import shutil
import sqlite3
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from steward import config, db, draft, ticket  # noqa: E402

LANGS = ["en", "tr", "de", "fr", "nl", "es", "it", "pt", "pl", "ru"]
SEED = 20261030


def rule_of(problem: str) -> str:
    for key, name in [("too long", "length"), ("placeholder", "placeholder"), ("personal data", "personal data"),
                      ("promises", "promise"), ("language mismatch", "language"), ("cites unknown", "citation"),
                      ("not evidence", "citation"), ("no evidence", "citation"), ("outside this issue", "app"),
                      ("versions not in", "version")]:
        if key in problem:
            return name
    return "other"


def main(per_lang: int) -> dict:
    src = config.DB_PATH
    eval_dir = config.DATA / "eval"
    eval_dir.mkdir(parents=True, exist_ok=True)
    dst = eval_dir / "agent_checks.db"
    main_con = db.connect()
    main_con.execute("PRAGMA wal_checkpoint(FULL)")
    shutil.copyfile(src, dst)
    con = db.connect(dst)
    first_receipt = con.execute("SELECT COALESCE(MAX(id),0) FROM receipts").fetchone()[0]
    con.execute("DELETE FROM drafts")
    con.commit()

    rnd = random.Random(SEED)
    sample = []
    for lang in LANGS:
        ids = [r[0] for r in con.execute(
            "SELECT i.id FROM items i JOIN splits s ON s.item_id=i.id JOIN labels l ON l.item_id=i.id AND "
            "l.source='gold_claude' WHERE s.split='test_synth' AND i.lang=? AND l.category NOT IN "
            "('praise','spam_or_offtopic') ORDER BY i.id", (lang,))]
        sample += [(lang, i) for i in rnd.sample(ids, min(per_lang, len(ids)))]

    def one(pair):
        lang, iid = pair
        c = db.connect(dst)
        t0 = time.time()
        try:
            out = draft.draft_reply(iid, None, con=c)
            row = c.execute("SELECT attempts, text FROM drafts WHERE id=?", (out["draft_id"],)).fetchone()
            return {"lang": lang, "attempts": json.loads(row["attempts"]), "final_len": len(row["text"]),
                    "cost": out["cost_usd"], "s": time.time() - t0}
        except Exception as e:  # noqa: BLE001 - counted, never hidden
            return {"lang": lang, "error": f"{type(e).__name__}: {str(e)[:120]}"}

    with ThreadPoolExecutor(4) as ex:
        replies = list(ex.map(one, sample))

    run = con.execute("SELECT run_id FROM clusters ORDER BY created_at DESC LIMIT 1").fetchone()[0]
    crash_issues = [r[0] for r in con.execute("SELECT id FROM clusters WHERE run_id=? AND crash_issue_ids!='[]'",
                                              (run,))]
    tickets = []
    for cid in crash_issues:
        try:
            out = ticket.draft_ticket(cid, con=con)
            row = con.execute("SELECT attempts FROM drafts WHERE id=?", (out["draft_id"],)).fetchone()
            tickets.append({"attempts": json.loads(row["attempts"]), "cost": out["cost_usd"]})
        except Exception as e:  # noqa: BLE001
            tickets.append({"error": f"{type(e).__name__}: {str(e)[:120]}"})

    # merge the copy's receipts into the main ledger
    new = con.execute("SELECT ts,provider,model,mode,purpose,input_tokens,cached_tokens,output_tokens,images,frames,"
                      "cost_usd,latency_ms,prompt_sha,status FROM receipts WHERE id>?", (first_receipt,)).fetchall()
    main_con.executemany("INSERT INTO receipts(ts,provider,model,mode,purpose,input_tokens,cached_tokens,output_tokens,"
                         "images,frames,cost_usd,latency_ms,prompt_sha,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         [tuple(r) for r in new])
    main_con.commit()

    def summarise(rows, by_lang=False):
        ok = [r for r in rows if "error" not in r]
        first_pass = sum(1 for r in ok if not r["attempts"][0]["problems"])
        final_pass = sum(1 for r in ok if not r["attempts"][-1]["problems"])
        revised = [r for r in ok if r["attempts"][0]["problems"]]
        fixed = sum(1 for r in revised if not r["attempts"][-1]["problems"])
        rules_first = collections.Counter(rule_of(p) for r in ok for p in r["attempts"][0]["problems"])
        rules_final = collections.Counter(rule_of(p) for r in ok for p in r["attempts"][-1]["problems"])
        out = {"n": len(rows), "errors": len(rows) - len(ok),
               "error_messages": [r["error"] for r in rows if "error" in r], "first_attempt_pass": first_pass,
               "blocked_first": len(revised), "fixed_by_revision": fixed, "final_pass": final_pass,
               "still_blocked": len(ok) - final_pass, "rules_first_attempt": dict(rules_first),
               "rules_after_revision": dict(rules_final),
               "cost_usd_total": round(sum(r["cost"] for r in ok), 4),
               "cost_usd_per_item": round(sum(r["cost"] for r in ok) / max(len(ok), 1), 5)}
        if ok and "final_len" in ok[0]:
            out["final_chars_median"] = statistics.median(r["final_len"] for r in ok)
            out["final_chars_max"] = max(r["final_len"] for r in ok)
            out["seconds_median"] = round(statistics.median(r["s"] for r in ok), 1)
        if by_lang:
            out["by_language"] = {}
            for lang in LANGS:
                rl = [r for r in ok if r["lang"] == lang]
                out["by_language"][lang] = {"n": len(rl), "first_pass": sum(1 for r in rl if not r["attempts"][0]["problems"]),
                                            "final_pass": sum(1 for r in rl if not r["attempts"][-1]["problems"])}
        return out

    res = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "seed": SEED,
           "language_check_covers": sorted(draft._STOP) + ["ru (script)", "zh (script)"],
           "replies": summarise(replies, by_lang=True), "tickets": summarise(tickets),
           "receipts_merged": len(new)}
    (ROOT / "results" / "agent_checks.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(res, indent=1))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-lang", type=int, default=12)
    main(ap.parse_args().per_lang)
