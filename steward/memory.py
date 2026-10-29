"""What changed since the last morning pass: match this run's issues to the previous run's, deterministically.

Two issues are the same issue when their evidence overlaps: the Jaccard similarity of their cited review ids and
crash ids is at least `SAME`. The model writes a new title every run, so titles are never compared. A previous
issue without a match is reported as quiet (no current signal cites it), not as fixed: only a release can claim that.
"""
from __future__ import annotations

import json

SAME = 0.3


def _sig(row) -> set[str]:
    return set(json.loads(row["item_ids"] or "[]")) | set(json.loads(row["crash_issue_ids"] or "[]"))


def runs(con) -> list[str]:
    return [r[0] for r in con.execute("SELECT run_id, MIN(created_at) t FROM clusters GROUP BY run_id ORDER BY t DESC")]


def compare(con, run_id: str | None = None) -> dict:
    order = runs(con)
    if not order:
        return {"run": None, "previous": None, "issues": {}, "quiet": []}
    run_id = run_id or order[0]
    prev = next((r for r in order[order.index(run_id) + 1:]), None) if run_id in order else None
    cur = con.execute("SELECT * FROM clusters WHERE run_id=?", (run_id,)).fetchall()
    old = con.execute("SELECT * FROM clusters WHERE run_id=?", (prev,)).fetchall() if prev else []
    used, issues = set(), {}
    for c in cur:
        s = _sig(c)
        best, score = None, 0.0
        for o in old:
            so = _sig(o)
            j = len(s & so) / len(s | so) if s | so else 0.0
            if j > score:
                best, score = o, j
        if prev is None:
            issues[c["id"]] = {"status": "first pass"}
        elif best is not None and score >= SAME:
            used.add(best["id"])
            issues[c["id"]] = {"status": "ongoing", "previous_issue": best["id"], "overlap": round(score, 2),
                               "new_signals": len(s - _sig(best))}
        else:
            issues[c["id"]] = {"status": "new"}
    quiet = [{"issue_id": o["id"], "title": o["title"]} for o in old if o["id"] not in used]
    return {"run": run_id, "previous": prev, "issues": issues, "quiet": quiet}


def same_issue_ids(con, cluster_id: str) -> list[str]:
    """Every issue id, in any run, whose evidence overlaps this one's enough to be the same issue (itself included)."""
    me = con.execute("SELECT * FROM clusters WHERE id=?", (cluster_id,)).fetchone()
    if me is None:
        return []
    s = _sig(me)
    out = []
    for o in con.execute("SELECT * FROM clusters"):
        so = _sig(o)
        if o["id"] == cluster_id or (s | so and len(s & so) / len(s | so) >= SAME):
            out.append(o["id"])
    return out
