"""Whole-studio reasoning with Muse Spark: one long context, cross-app issue clusters, verified citations.

No retrieval and no vector store. Every review (pseudonymised, scrubbed), every crash/ANR issue and every
release of every included app goes into ONE id-tagged context. Spark returns clusters as strict JSON.
Nothing it says is trusted until `verify_clusters` has checked:
  * every cited review id / crash id exists in the context;
  * every evidence quote is an exact substring of the cited review's text;
  * a review-to-crash link is accepted only if the app matches and the versions line up (rule recorded).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid

from . import db, llm

CLUSTER_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["clusters"],
    "properties": {"clusters": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["title", "summary", "severity", "apps", "review_ids", "crash_ids", "first_seen_version",
                     "evidence", "suggested_action"],
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "severity": {"type": "integer", "minimum": 1, "maximum": 4},
            "apps": {"type": "array", "items": {"type": "string"}},
            "review_ids": {"type": "array", "items": {"type": "string"}},
            "crash_ids": {"type": "array", "items": {"type": "string"}},
            "first_seen_version": {"type": "string"},
            "evidence": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["id", "quote"],
                "properties": {"id": {"type": "string"}, "quote": {"type": "string"}}}},
            "suggested_action": {"type": "string"},
        }}}},
}

SYSTEM = """You are the release steward for a small studio that ships many Android/iOS apps and games.
Below is the studio's complete feedback context: every written store review (personal data removed and
replaced by placeholders), every crash/ANR issue from Play vitals, and every release, all id-tagged.

Group the ACTIONABLE signals into issue clusters. A cluster may span several apps when the root cause is
shared (for example the same native library crashing in several games). Do not create clusters for pure praise.
Rules:
- Cite only ids that appear in the context. Evidence quotes must be copied exactly from the cited review text
  (a short exact substring, at most 12 words). Crash issues have no quotes; cite them in crash_ids.
- first_seen_version: the earliest app version where the cluster appears, or "unknown".
- severity 1-4 (4 = crash/data loss/charged without delivery or several apps affected).
- suggested_action: one concrete engineering or store action.
Return JSON only."""


def _crash_key(package: str, issue_id: str) -> str:
    return "C-" + hashlib.sha256(f"{package}|{issue_id}".encode()).hexdigest()[:10]


def build_context(con, packages: list[str] | None = None, include_synthetic: bool = False) -> tuple[str, dict]:
    where = "" if include_synthetic else "WHERE i.synthetic=0"
    rows = con.execute(f"SELECT i.*, l.category, l.severity, l.gloss AS gloss_en FROM items i LEFT JOIN labels l ON "
                       f"l.item_id=i.id AND l.source=(SELECT source FROM labels WHERE item_id=i.id ORDER BY "
                       f"CASE source WHEN 'triage_live' THEN 0 WHEN 'gold_claude' THEN 1 ELSE 2 END LIMIT 1) "
                       f"{where} ORDER BY i.package, i.created_at").fetchall()
    if packages:
        rows = [r for r in rows if r["package"] in packages]
    index = {"reviews": {}, "crashes": {}, "releases": []}
    lines = []
    for r in rows:
        index["reviews"][r["id"]] = dict(r)
        lines.append(f"[REVIEW id={r['id']} app={r['package']} store={r['store']} rating={r['rating']} "
                     f"lang={r['lang']} version={r['version_name'] or 'unknown'} versionCode={r['version_code'] or ''} "
                     f"date={(r['created_at'] or '')[:10]} triage={r['category'] or '-'}] "
                     f"{(r['title'] + ' / ') if r['title'] else ''}{r['text']}")
    crashes = con.execute("SELECT * FROM crash_issues" + (" WHERE package IN (%s)" % ",".join("?" * len(packages))
                                                          if packages else ""), packages or ()).fetchall()
    for c in crashes:
        cid = _crash_key(c["package"], c["issue_id"])
        index["crashes"][cid] = dict(c)
        lines.append(f"[CRASH id={cid} app={c['package']} type={c['type']} users={c['distinct_users']} "
                     f"reports={c['error_reports']} first_versionCode={c['first_version']} "
                     f"last_versionCode={c['last_version']}] cause: {c['cause']} | location: {c['location']}")
    rels = con.execute("SELECT * FROM releases" + (" WHERE package IN (%s)" % ",".join("?" * len(packages))
                                                   if packages else ""), packages or ()).fetchall()
    for r in rels:
        index["releases"].append(dict(r))
        notes = json.loads(r["notes"] or "{}")
        en = notes.get("en-US") or next(iter(notes.values()), "")
        lines.append(f"[RELEASE app={r['package']} track={r['track']} name={r['name']} status={r['status']} "
                     f"versionCodes={r['version_codes']}] {en[:300]}")
    return "\n".join(lines), index


def verify_clusters(clusters: list[dict], index: dict) -> list[dict]:
    """Return clusters annotated with a verifier verdict; invented ids and inexact quotes are removed and counted."""
    out = []
    for c in clusters:
        problems = []
        rids = [r for r in c["review_ids"] if r in index["reviews"]]
        problems += [f"unknown review id {r}" for r in c["review_ids"] if r not in index["reviews"]]
        cids = [x for x in c["crash_ids"] if x in index["crashes"]]
        problems += [f"unknown crash id {x}" for x in c["crash_ids"] if x not in index["crashes"]]
        ev = []
        for e in c["evidence"]:
            src = index["reviews"].get(e["id"])
            full = ((src["title"] + " / ") if src and src.get("title") else "") + (src["text"] if src else "")
            if src and e["quote"] and e["quote"] in full:
                ev.append(e)
            else:
                problems.append(f"quote not found verbatim for {e['id']}")
        links = []
        for x in cids:
            crash = index["crashes"][x]
            for r in rids:
                rv = index["reviews"][r]
                if rv["package"] != crash["package"]:
                    continue
                vc = rv.get("version_code")
                if vc and crash["first_version"] and crash["last_version"] and \
                        crash["first_version"] <= vc <= crash["last_version"]:
                    links.append({"review": r, "crash": x, "rule": "same app, review version inside crash range"})
                elif vc is None:
                    links.append({"review": r, "crash": x, "rule": "same app, review version unknown (weak)"})
        if not rids and not cids:
            problems.append("cluster cites nothing that exists; dropped")
            continue
        fsv = c.get("first_seen_version") or "unknown"
        if fsv == "unknown" and cids:
            # deterministic, from Play vitals: the lowest versionCode any cited crash issue was first seen in
            codes = [index["crashes"][x]["first_version"] for x in cids if index["crashes"][x]["first_version"]]
            if codes:
                fsv = f"versionCode {min(codes)} (from crash data)"
        c2 = dict(c, review_ids=rids, crash_ids=cids, evidence=ev, links=links, problems=problems,
                  verified=not problems, first_seen_version=fsv)
        out.append(c2)
    return out


def cluster_studio(con=None, packages: list[str] | None = None, model: str = "muse-spark-1.3",
                   provider: str = "meta") -> dict:
    con = con or db.connect()
    ctx, index = build_context(con, packages)
    res = llm.chat(provider, model, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": ctx}],
                   purpose="cluster", max_tokens=12000, schema=CLUSTER_SCHEMA, schema_name="clusters",
                   temperature=0.0, reasoning_effort="medium" if provider == "meta" else None, con=con)
    verified = verify_clusters(res.data["clusters"], index)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4]
    for c in verified:
        cid = "K-" + uuid.uuid4().hex[:8]
        c["id"] = cid
        con.execute("INSERT INTO clusters VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            cid, ",".join(c["apps"]), run_id, c["title"], c["summary"], c["severity"], json.dumps(c["review_ids"]),
            json.dumps(sorted({index['reviews'][r]['lang'] or '' for r in c['review_ids']})),
            json.dumps(c["crash_ids"]), c["first_seen_version"],
            json.dumps({"evidence": c["evidence"], "links": c["links"], "problems": c["problems"],
                        "action": c["suggested_action"]}, ensure_ascii=False),
            "verified" if c["verified"] else "partially verified", None,
            dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
    con.commit()
    return {"run_id": run_id, "context_chars": len(ctx), "input_tokens": res.usage.input_tokens,
            "cached_tokens": res.usage.cached_tokens, "cost_usd": res.cost_usd, "latency_ms": res.latency_ms,
            "clusters": verified,
            "dropped_problems": sum(len(c["problems"]) for c in verified)}
