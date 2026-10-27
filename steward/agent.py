"""The steward agent: Muse Spark plans and calls tools; every tool is ours, logged, and none can post.

One run = the developer's "morning pass" across the whole studio:
  look at the studio -> pull what is new -> triage it -> group issues across apps -> prepare reply drafts
  -> report. Posting is not a tool. The agent can only put drafts in the approval queue.
Each step (tool, arguments, short result, cost) is written to `agent_steps` and shown on /agent.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import uuid

import httpx

from . import apps, budget, db, draft, llm, reason, triage

MODEL = ("meta", "muse-spark-1.3")
MAX_STEPS = 10

SYSTEM = """You are Storefront Steward, an operations agent for a small studio with many apps on
Google Play and the App Store. Run the developer's morning pass with the tools you have:
1. Look at the studio overview.
2. If the store data looks stale, sync it.
3. Triage anything untriaged.
4. Group the actionable signals into issues across apps (one call covers the whole studio).
5. Prepare reply drafts for the most severe issues that contain reviews (the developer approves them later).
6. Finish with a short report for the developer: what changed, the top issues with app names and severity,
   how many drafts wait for approval, and one recommended engineering action.
You cannot post anything to a store and you must not claim that anything was posted. Be economical: do not
repeat a tool call with the same arguments. Stop by calling `finish`."""

TOOLS = [
    {"type": "function", "function": {"name": "studio_overview", "description":
        "Counts per app: written reviews, untriaged reviews, actionable reviews, crash/ANR issues, latest release.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "sync_store", "description":
        "Pull recent reviews (Play last 7 days, App Store) and Play crash/ANR issues for all included apps.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "triage_untriaged", "description":
        "Label every untriaged real review with category, severity, language and an English gloss.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "cluster_issues", "description":
        "Read the whole studio in one long context and group actionable reviews and crash issues into issues, "
        "with verified citations. Returns issue ids, titles, severity, apps and counts.",
        "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
    {"type": "function", "function": {"name": "draft_replies", "description":
        "Draft verified replies for the reviews in one issue and put them in the approval queue.",
        "parameters": {"type": "object", "properties": {"issue_id": {"type": "string"}},
                       "required": ["issue_id"], "additionalProperties": False}}},
    {"type": "function", "function": {"name": "finish", "description": "End the run with the report.",
        "parameters": {"type": "object", "properties": {"report": {"type": "string"}},
                       "required": ["report"], "additionalProperties": False}}},
]


def _ensure_tables(con) -> None:
    con.execute("CREATE TABLE IF NOT EXISTS agent_steps (run_id TEXT, step INTEGER, ts TEXT, tool TEXT, args TEXT, "
                "result TEXT, cost_usd REAL)")


def _latest_label_source_sql() -> str:
    return "(SELECT 1 FROM labels l WHERE l.item_id=i.id AND l.source IN ('triage_live','gold_claude'))"


# ------------------------------------------------------------------------------------------------ tools
def t_studio_overview(con) -> dict:
    out = []
    for a in apps.included():
        n = con.execute("SELECT COUNT(*) FROM items WHERE synthetic=0 AND package=?", (a.package,)).fetchone()[0]
        crashes = con.execute("SELECT COUNT(*) FROM crash_issues WHERE package=?", (a.package,)).fetchone()[0]
        if not n and not crashes:
            continue
        untriaged = con.execute(f"SELECT COUNT(*) FROM items i WHERE synthetic=0 AND package=? AND NOT EXISTS "
                                f"{_latest_label_source_sql()}", (a.package,)).fetchone()[0]
        actionable = con.execute("SELECT COUNT(DISTINCT i.id) FROM items i JOIN labels l ON l.item_id=i.id AND "
                                 "l.source IN ('triage_live','gold_claude') WHERE i.synthetic=0 AND i.package=? AND "
                                 "l.category NOT IN ('praise','spam_or_offtopic')", (a.package,)).fetchone()[0]
        out.append({"app": a.name, "package": a.package, "reviews": n, "untriaged": untriaged,
                    "actionable": actionable, "crash_issues": crashes})
    last = con.execute("SELECT MAX(fetched_at) FROM crash_issues").fetchone()[0]
    return {"apps_with_signals": out, "apps_included": len(apps.included()), "excluded_by_policy":
            len(apps.excluded()), "last_sync_utc": last}


def t_sync_store(con) -> dict:
    from .connectors import ingest
    before = con.execute("SELECT COUNT(*) FROM items WHERE synthetic=0").fetchone()[0]
    res = {"play_recent_reviews": ingest.ingest_play_api(con), "appstore_reviews": ingest.ingest_asc(con),
           "crash_issues": ingest.ingest_vitals(con)}
    res["new_reviews"] = con.execute("SELECT COUNT(*) FROM items WHERE synthetic=0").fetchone()[0] - before
    return res


def t_triage_untriaged(con) -> dict:
    rows = con.execute(f"SELECT i.id, i.text FROM items i WHERE synthetic=0 AND NOT EXISTS "
                       f"{_latest_label_source_sql()}").fetchall()
    if not rows:
        return {"triaged": 0, "note": "nothing untriaged"}
    items = [{"id": r["id"], "text": r["text"]} for r in rows]
    local = os.environ.get("STEWARD_LOCAL_URL")
    engine = "muse-spark-1.3 guided"
    labels = {}
    if local:
        try:
            httpx.get(local.rsplit("/v1", 1)[0] + "/health", timeout=3).raise_for_status()
            labels = triage.label_items("local", "local", items, mode="guided", batch=5, workers=1,
                                        purpose="agent-triage-local")
            engine = "local open-weights model"
        except Exception:  # noqa: BLE001 - fall back to the hosted teacher
            labels = {}
    if not labels:
        labels = triage.label_items(*MODEL, items, mode="guided", purpose="agent-triage")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for iid, lab in labels.items():
        con.execute("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?,?)",
                    (iid, "triage_live", lab["category"], int(lab["severity"]), lab["language"], lab["gloss_en"],
                     json.dumps({"engine": engine}), now))
    con.commit()
    return {"triaged": len(labels), "engine": engine}


def t_cluster_issues(con) -> dict:
    r = reason.cluster_studio(con)
    return {"issues": [{"issue_id": c["id"], "title": c["title"], "severity": c["severity"],
                        "apps": [apps.get(p).name if apps.get(p) else p for p in c["apps"]],
                        "reviews": len(c["review_ids"]), "crash_issues": len(c["crash_ids"]),
                        "verified": c["verified"]} for c in r["clusters"]],
            "context_tokens": r["input_tokens"], "cached_tokens": r["cached_tokens"]}


def t_draft_replies(con, issue_id: str) -> dict:
    c = con.execute("SELECT * FROM clusters WHERE id=?", (issue_id,)).fetchone()
    if c is None:
        return {"error": f"unknown issue id {issue_id}"}
    ev = json.loads(c["evidence"])
    cl = {"id": c["id"], "title": c["title"], "summary": c["summary"], "suggested_action": ev.get("action", "")}
    out = []
    for rid in json.loads(c["item_ids"]):
        if con.execute("SELECT 1 FROM drafts WHERE item_id=? AND status IN ('pending','approved','posted')",
                       (rid,)).fetchone():
            out.append({"review": rid, "status": "already queued"})
            continue
        d = draft.draft_reply(rid, cl, con=con)
        out.append({"review": rid, "status": "queued" if not d["problems"] else "blocked by verifier",
                    "problems": d["problems"]})
    return {"issue": c["title"], "drafts": out}


IMPL = {"studio_overview": t_studio_overview, "sync_store": t_sync_store, "triage_untriaged": t_triage_untriaged,
        "cluster_issues": t_cluster_issues, "draft_replies": t_draft_replies}


def run(max_steps: int = MAX_STEPS, con=None) -> dict:
    con = con or db.connect()
    _ensure_tables(con)
    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:4]
    msgs: list[dict] = [{"role": "system", "content": SYSTEM},
                        {"role": "user", "content": "Run the morning pass now."}]
    report, seen = None, set()
    for step in range(1, max_steps + 1):
        res = llm.chat(*MODEL, msgs, purpose="agent-plan", max_tokens=4000, tools=TOOLS, temperature=0.0,
                       reasoning_effort="low", con=con)
        con.execute("INSERT INTO agent_steps VALUES (?,?,?,?,?,?,?)",
                    (run_id, step, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "plan",
                     json.dumps({"tool_calls": len(getattr(res.message, "tool_calls", None) or [])}),
                     (res.message.content or "")[:2000], round(res.cost_usd, 6)))
        m = res.message
        calls = list(getattr(m, "tool_calls", None) or [])
        msgs.append({"role": "assistant", "content": m.content or "",
                     **({"tool_calls": [c.model_dump() for c in calls]} if calls else {})})
        if not calls:
            report = m.content
            break
        for call in calls:
            name = call.function.name
            args = json.loads(call.function.arguments or "{}")
            key = (name, json.dumps(args, sort_keys=True))
            before = budget.spent(con, "meta") + budget.spent(con, "baseten")
            if name == "finish":
                report = args.get("report", "")
                result = {"ok": True}
            elif key in seen:
                result = {"error": "duplicate call skipped; use the earlier result"}
            elif name in IMPL:
                seen.add(key)
                try:
                    result = IMPL[name](con, **args)
                except Exception as e:  # noqa: BLE001 - the agent sees the error and can adapt
                    result = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
            else:
                result = {"error": f"unknown tool {name}"}
            text = json.dumps(result, ensure_ascii=False)[:6000]
            msgs.append({"role": "tool", "tool_call_id": call.id, "content": text})
            con.execute("INSERT INTO agent_steps VALUES (?,?,?,?,?,?,?)",
                        (run_id, step, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), name,
                         json.dumps(args), text[:4000],
                         round(budget.spent(con, "meta") + budget.spent(con, "baseten") - before, 6)))
            con.commit()
        if report is not None:
            break
    con.execute("INSERT INTO agent_steps VALUES (?,?,?,?,?,?,?)",
                (run_id, 999, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "report", "{}",
                 report or "(no report: step limit reached)", 0.0))
    con.commit()
    return {"run_id": run_id, "report": report}
