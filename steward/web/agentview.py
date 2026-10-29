"""Turn the agent's step log into a readable timeline: one plain sentence per tool call, raw JSON on demand."""
from __future__ import annotations

import datetime as dt
import json


def _j(s: str):
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return None


def summarize(tool: str, result: str) -> str:
    r = _j(result)
    if not isinstance(r, dict):
        return (result or "")[:240]
    if "error" in r:
        return f"error: {r['error']}"
    if tool == "studio_overview":
        a = r.get("apps_with_signals", [])
        return (f"{len(a)} of {r.get('apps_included')} apps have signals · "
                f"{sum(x['untriaged'] for x in a)} untriaged reviews · {sum(x['crash_issues'] for x in a)} crash/ANR "
                f"issues · {r.get('excluded_by_policy')} apps excluded by policy")
    if tool == "sync_store":
        return (f"{r.get('new_reviews', 0)} new review(s) · Play last 7 days: {r.get('play_recent_reviews')} · "
                f"App Store: {r.get('appstore_reviews')} · {r.get('crash_issues')} crash/ANR issues refreshed (read-only)")
    if tool == "triage_untriaged":
        return f"{r.get('triaged', 0)} triaged · {r.get('engine', r.get('note', ''))}"
    if tool == "cluster_issues":
        iss = r.get("issues", [])
        st = [i.get("since_last_pass", {}).get("status") for i in iss]
        multi = [i for i in iss if len(i.get("apps", [])) > 1]
        txt = (f"{len(iss)} issues from one {r.get('context_tokens', 0):,}-token context "
               f"({r.get('cached_tokens', 0):,} cached) · {st.count('new')} new · {st.count('ongoing')} ongoing · "
               f"{len(r.get('quiet_since_last_pass', []))} quiet · {sum(1 for i in iss if i.get('verified'))} fully "
               f"verified")
        if multi:
            m = max(multi, key=lambda i: (i["severity"], len(i["apps"])))
            txt += f" · cross-app: “{m['title']}” ({', '.join(m['apps'])})"
        return txt
    if tool == "draft_replies":
        d = r.get("drafts", [])
        q = sum(1 for x in d if x["status"] == "queued")
        b = sum(1 for x in d if x["status"].startswith("blocked"))
        rev = sum(1 for x in d if x.get("attempts", 1) > 1)
        a = sum(1 for x in d if x["status"] == "already queued")
        parts = [f"{q} queued"] + ([f"{rev} revised after the verifier"] if rev else []) + \
                ([f"{b} still blocked"] if b else []) + ([f"{a} already in the queue"] if a else [])
        return f"“{r.get('issue')}”: " + " · ".join(parts)
    if tool == "draft_ticket":
        if "ticket" not in r:
            return r.get("status", "")
        extra = " · revised after the verifier" if r.get("attempts", 1) > 1 else ""
        return f"ticket “{r['ticket']}” · {r['status']}{extra}"
    if tool == "finish":
        return "report written"
    return json.dumps(r, ensure_ascii=False)[:240]


def timeline(rows: list[dict]) -> dict:
    steps, report, tools, cost = [], None, 0, 0.0
    for s in rows:
        cost += s.get("cost_usd") or 0.0
        if s["tool"] == "report":
            report = s["result"]
            continue
        if s["tool"] == "plan":
            if (s.get("result") or "").strip():
                steps.append({"kind": "plan", "summary": s["result"].strip(), "cost": s.get("cost_usd") or 0.0})
            continue
        tools += 1
        steps.append({"kind": "tool", "tool": s["tool"], "args": s.get("args") or "{}",
                      "summary": summarize(s["tool"], s.get("result") or ""), "raw": s.get("result") or "",
                      "cost": s.get("cost_usd") or 0.0})
    secs = None
    ts = [s["ts"] for s in rows if s.get("ts")]
    if len(ts) > 1:
        secs = int((dt.datetime.fromisoformat(max(ts)) - dt.datetime.fromisoformat(min(ts))).total_seconds())
    return {"steps": steps, "report": report, "done": report is not None, "tools": tools, "cost": cost,
            "seconds": secs}
