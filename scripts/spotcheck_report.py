"""Summarise the owner's spot check of the Claude gold labels. Writes counts only (no review text) to results/."""
from __future__ import annotations

import json
import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> dict:
    from steward.web.app import _spot_sample  # the same fixed, seeded sample the page shows
    con = sqlite3.connect(ROOT / "data" / "clean" / "steward.db")
    con.execute("CREATE TABLE IF NOT EXISTS spotcheck (item_id TEXT PRIMARY KEY, verdict TEXT, corrected TEXT, ts TEXT)")
    ids = _spot_sample(con)
    out = {"sample": len(ids), "checked": 0, "agree": 0, "disagree": 0, "by_set": {}, "corrections": {}}
    for i in ids:
        syn = con.execute("SELECT synthetic FROM items WHERE id=?", (i,)).fetchone()[0]
        key = "synthetic" if syn else "real"
        b = out["by_set"].setdefault(key, {"sample": 0, "checked": 0, "agree": 0})
        b["sample"] += 1
        row = con.execute("SELECT verdict, corrected FROM spotcheck WHERE item_id=?", (i,)).fetchone()
        if not row:
            continue
        out["checked"] += 1
        b["checked"] += 1
        if row[0] == "agree":
            out["agree"] += 1
            b["agree"] += 1
        else:
            out["disagree"] += 1
            gold = con.execute("SELECT category FROM labels WHERE item_id=? AND source='gold_claude'", (i,)).fetchone()[0]
            k = f"{gold} -> {row[1] or gold + ' (severity)'}"
            out["corrections"][k] = out["corrections"].get(k, 0) + 1
    out["agreement"] = round(out["agree"] / out["checked"], 3) if out["checked"] else None
    (ROOT / "results" / "spotcheck.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    main()
