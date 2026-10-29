"""Engineering hand-off: Muse Spark writes a bug ticket for one issue; a deterministic verifier checks it.

The ticket goes into the same approval queue as replies. Approving it exports a Markdown file for the studio's
tracker; nothing is sent anywhere. The verifier rejects a ticket that
  * cites an id that is not evidence of this issue,
  * names an app that is not in this issue,
  * mentions a version number that appears nowhere in the issue's reviews, crash issues or releases,
  * contains personal data.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from . import config, db, llm
from .privacy import scan
from .reason import _crash_key

TICKET_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["title", "apps", "affected_versions", "symptoms", "user_impact", "suspected_component",
                 "first_step", "evidence_ids"],
    "properties": {
        "title": {"type": "string"},
        "apps": {"type": "array", "items": {"type": "string"}},
        "affected_versions": {"type": "array", "items": {"type": "string"}},
        "symptoms": {"type": "string"},
        "user_impact": {"type": "string"},
        "suspected_component": {"type": "string"},
        "first_step": {"type": "string"},
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM = """You write the engineering ticket for one issue found in a small studio's store feedback.
The developer approves the ticket before it reaches the tracker. Use ONLY the evidence given: reviews (personal
data removed), crash/ANR issues from Play vitals with cause and location, and releases.
- apps: package names exactly as given. affected_versions: only version names or versionCodes that appear in the
  evidence. evidence_ids: the review ids and crash ids you relied on.
- suspected_component: the library, module or screen the evidence points at; say "unknown" if it does not.
- first_step: one concrete debugging step a developer can start today.
- Never invent stack frames, user counts or versions. Never include names or contact details.
Return JSON only."""

MAX_ATTEMPTS = 2
_VERSION = re.compile(r"\b\d+(?:\.\d+)+\b|\b\d{2,}\b")


def _evidence(con, cluster) -> tuple[str, set[str], set[str], set[str]]:
    rids = json.loads(cluster["item_ids"] or "[]")
    cids = set(json.loads(cluster["crash_issue_ids"] or "[]"))
    lines, versions, packages = [], set(), set()
    for r in con.execute("SELECT * FROM items WHERE id IN (%s)" % ",".join("?" * len(rids)), rids) if rids else []:
        packages.add(r["package"])
        versions |= {str(v) for v in (r["version_name"], r["version_code"]) if v}
        lines.append(f"[REVIEW id={r['id']} app={r['package']} rating={r['rating']} version={r['version_name']} "
                     f"versionCode={r['version_code']}] {r['text']}")
    for c in con.execute("SELECT * FROM crash_issues"):
        key = _crash_key(c["package"], c["issue_id"])
        if key not in cids:
            continue
        packages.add(c["package"])
        versions |= {str(v) for v in (c["first_version"], c["last_version"]) if v}
        lines.append(f"[CRASH id={key} app={c['package']} type={c['type']} users={c['distinct_users']} "
                     f"reports={c['error_reports']} versionCodes={c['first_version']}..{c['last_version']}] "
                     f"cause: {c['cause']} | location: {c['location']}")
    for p in sorted(packages):
        for r in con.execute("SELECT * FROM releases WHERE package=?", (p,)):
            versions |= {r["name"] or ""} | set(re.findall(r"\d+", r["version_codes"] or ""))
            lines.append(f"[RELEASE app={p} track={r['track']} name={r['name']} versionCodes={r['version_codes']}]")
    versions.discard("")
    return "\n".join(lines), set(rids) | cids, packages, versions


def verify(t: dict, *, ids: set[str], packages: set[str], versions: set[str]) -> list[str]:
    problems = []
    bad = [e for e in t["evidence_ids"] if e not in ids]
    if bad:
        problems.append(f"cites ids that are not evidence of this issue: {bad}")
    if not t["evidence_ids"]:
        problems.append("cites no evidence")
    stray = [a for a in t["apps"] if a not in packages]
    if stray:
        problems.append(f"names apps outside this issue: {stray}")
    text_versions = set(_VERSION.findall(" ".join(t["affected_versions"])))
    unknown = sorted(v for v in text_versions if v not in versions and not any(v in x for x in versions))
    if unknown:
        problems.append(f"versions not in the evidence: {unknown}")
    pii = scan(json.dumps(t, ensure_ascii=False))
    if pii:
        problems.append(f"personal data pattern(s): {pii}")
    return problems


def render(t: dict, cluster) -> str:
    return (f"# {t['title']}\n\n"
            f"- Apps: {', '.join(t['apps'])}\n- Affected versions: {', '.join(t['affected_versions']) or 'unknown'}\n"
            f"- Suspected component: {t['suspected_component']}\n- Source issue: {cluster['id']} "
            f"(severity {cluster['severity']})\n\n## Symptoms\n{t['symptoms']}\n\n## User impact\n{t['user_impact']}\n\n"
            f"## First step\n{t['first_step']}\n\n## Evidence\n" + "\n".join(f"- {e}" for e in t["evidence_ids"]) + "\n")


def draft_ticket(cluster_id: str, con=None, provider: str = "meta", model: str = "muse-spark-1.3") -> dict:
    con = con or db.connect()
    c = con.execute("SELECT * FROM clusters WHERE id=?", (cluster_id,)).fetchone()
    if c is None:
        raise KeyError(cluster_id)
    ev, ids, packages, versions = _evidence(con, c)
    action = json.loads(c["evidence"] or "{}").get("action", "")
    msgs = [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"[ISSUE id={c['id']} severity={c['severity']}] {c['title']}: {c['summary']} "
                                        f"Suggested action: {action}\n\n{ev}"}]
    attempts, spent = [], 0.0
    for n in range(1, MAX_ATTEMPTS + 1):
        res = llm.chat(provider, model, msgs, purpose="ticket" if n == 1 else "ticket-revise", max_tokens=3000,
                       schema=TICKET_SCHEMA, schema_name="ticket", temperature=0.2,
                       reasoning_effort="low" if provider == "meta" else None, con=con)
        spent += res.cost_usd
        t = res.data
        problems = verify(t, ids=ids, packages=packages, versions=versions)
        attempts.append({"text": t["title"], "problems": problems})
        if not problems:
            break
        msgs = msgs + [{"role": "assistant", "content": res.text},
                       {"role": "user", "content": "The deterministic verifier rejected this ticket:\n- "
                        + "\n- ".join(problems) + "\nRewrite it so that it passes. JSON only."}]
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    cur = con.execute("INSERT INTO drafts(item_id,cluster_id,kind,lang,text,cites,verifier,status,created_at,attempts) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (c["id"], c["id"], "ticket", "en", render(t, c), json.dumps(t["evidence_ids"]),
                       json.dumps(problems), "pending" if not problems else "rejected_by_verifier", now,
                       json.dumps(attempts, ensure_ascii=False)))
    con.commit()
    return {"draft_id": cur.lastrowid, "title": t["title"], "problems": problems, "attempts": len(attempts),
            "cost_usd": spent}


def export(draft_id: int, con=None) -> str:
    """Write an approved ticket to data/tickets/ for the tracker. Returns the path."""
    con = con or db.connect()
    d = con.execute("SELECT * FROM drafts WHERE id=? AND kind='ticket'", (draft_id,)).fetchone()
    if d is None or d["status"] != "approved":
        raise PermissionError("only an approved ticket can be exported")
    text = d["edited_text"] or d["text"]
    if scan(text):
        raise ValueError("ticket text failed the outbound check; not exported")
    out = config.DATA / "tickets"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{d['cluster_id']}-{draft_id}.md"
    path.write_text(text, encoding="utf-8", newline="\n")
    return str(path)
