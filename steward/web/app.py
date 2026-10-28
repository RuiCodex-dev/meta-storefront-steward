"""Storefront Steward web app: inbox, issue board, approval queue, receipts. Local, read-mostly.

Run:  .venv/Scripts/python -m uvicorn steward.web.app:app --port 8765
Only pseudonyms and scrubbed text are ever rendered. Store writes happen only through the approval queue,
and only as a dry run unless STEWARD_LIVE=1 is set for the process.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from .. import apps, budget, config, db
from ..act import writer
from ..draft import verify

HERE = Path(__file__).resolve().parent
app = FastAPI(title="Storefront Steward")
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
T = Jinja2Templates(directory=HERE / "templates")
T.env.filters["loads"] = lambda s: json.loads(s) if s else []
T.env.filters["short"] = lambda p: (apps.get(p).name if apps.get(p) else p)
def _highlight(text: str, quote: str) -> Markup:
    """Escape review text (it is user-written) and only then wrap the verified quote in <mark>."""
    t, q = escape(text or ""), escape(quote or "")
    return Markup(str(t).replace(str(q), f"<mark>{q}</mark>", 1) if q else str(t))


T.env.filters["highlight"] = _highlight
T.env.globals["live"] = lambda: os.environ.get("STEWARD_LIVE") == "1"


def _con():
    return db.connect()


def _best_label_sql() -> str:
    return ("(SELECT source FROM labels WHERE item_id=i.id ORDER BY CASE source WHEN 'triage_live' THEN 0 "
            "WHEN 'gold_claude' THEN 1 ELSE 2 END LIMIT 1)")


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    con = _con()
    stats = {
        "apps": len(apps.included()), "excluded": len(apps.excluded()),
        "reviews": con.execute("SELECT COUNT(*) FROM items WHERE synthetic=0").fetchone()[0],
        "crashes": con.execute("SELECT COUNT(*) FROM crash_issues").fetchone()[0],
        "releases": con.execute("SELECT COUNT(*) FROM releases").fetchone()[0],
        "clusters": con.execute("SELECT COUNT(*) FROM clusters WHERE run_id=(SELECT run_id FROM clusters "
                                "ORDER BY created_at DESC LIMIT 1)").fetchone()[0],
        "pending": con.execute("SELECT COUNT(*) FROM drafts WHERE status='pending'").fetchone()[0],
        "synthetic": con.execute("SELECT COUNT(*) FROM items WHERE synthetic=1").fetchone()[0],
    }
    spend = {p: (round(budget.spent(con, p), 4), budget.CAPS_USD[p]) for p in ("meta", "baseten")}
    ev = None
    p = config.ROOT / "results" / "eval.json"
    if p.exists():
        ev = json.loads(p.read_text(encoding="utf-8"))
    return T.TemplateResponse(request, "home.html", {"stats": stats, "spend": spend, "ev": ev})


@app.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request, app_: str | None = None, category: str | None = None):
    con = _con()
    rows = con.execute(f"SELECT i.*, l.category, l.severity, l.gloss, l.source AS lsource FROM items i LEFT JOIN "
                       f"labels l ON l.item_id=i.id AND l.source={_best_label_sql()} WHERE i.synthetic=0 "
                       f"ORDER BY COALESCE(l.severity,0) DESC, i.created_at DESC").fetchall()
    rows = [r for r in rows if (not app_ or r["package"] == app_) and (not category or r["category"] == category)]
    return T.TemplateResponse(request, "inbox.html", {"rows": rows, "app_": app_, "category": category})


@app.get("/board", response_class=HTMLResponse)
def board(request: Request):
    con = _con()
    run = con.execute("SELECT run_id FROM clusters ORDER BY created_at DESC LIMIT 1").fetchone()
    clusters = []
    if run:
        for c in con.execute("SELECT * FROM clusters WHERE run_id=? ORDER BY severity DESC", (run[0],)):
            d = dict(c)
            d["ev"] = json.loads(c["evidence"])
            d["reviews"] = [dict(r) for r in con.execute(
                "SELECT id, package, rating, lang, version_name, text, title FROM items WHERE id IN (%s)" %
                ",".join("?" * len(json.loads(c["item_ids"]))), json.loads(c["item_ids"]))] if json.loads(
                c["item_ids"]) else []
            d["crash_n"] = len(json.loads(c["crash_issue_ids"]))
            from ..reason import _crash_key
            keys = set(json.loads(c["crash_issue_ids"]))
            d["crashes"] = [dict(x) for x in con.execute("SELECT * FROM crash_issues")
                            if _crash_key(x["package"], x["issue_id"]) in keys]
            clusters.append(d)
    return T.TemplateResponse(request, "board.html", {"clusters": clusters, "run": run[0] if run else None})


@app.get("/queue", response_class=HTMLResponse)
def queue(request: Request):
    con = _con()
    rows = con.execute("SELECT d.*, i.text AS review, i.rating, i.package, i.store FROM drafts d JOIN items i "
                       "ON i.id=d.item_id ORDER BY d.id DESC").fetchall()
    audit = con.execute("SELECT * FROM audit ORDER BY id DESC LIMIT 20").fetchall()
    return T.TemplateResponse(request, "queue.html", {"rows": rows, "audit": audit})


@app.post("/queue/{draft_id}")
def decide(draft_id: int, action: str = Form(...), text: str = Form("")):
    con = _con()
    d = con.execute("SELECT d.*, i.store FROM drafts d JOIN items i ON i.id=d.item_id WHERE d.id=?",
                    (draft_id,)).fetchone()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    if action == "approve":
        final = text.strip() or d["text"]
        problems = verify({"reply_text": final, "cites": [], "promises": []}, store=d["store"],
                          review_lang=d["lang"], known_ids=set())
        if problems:
            con.execute("UPDATE drafts SET verifier=? WHERE id=?", (json.dumps(problems), draft_id))
        else:
            con.execute("UPDATE drafts SET status='approved', edited_text=?, decided_at=? WHERE id=?",
                        (final if final != d["text"] else None, now, draft_id))
    elif action == "reject":
        con.execute("UPDATE drafts SET status='rejected', decided_at=? WHERE id=?", (now, draft_id))
    elif action == "post":
        writer.post(draft_id, actor="owner-via-ui", con=con)
    con.commit()
    return RedirectResponse("/queue", status_code=303)


@app.get("/receipts", response_class=HTMLResponse)
def receipts(request: Request):
    con = _con()
    return T.TemplateResponse(request, "receipts.html", {
        "rows": budget.summary(con),
        "spend": {p: (round(budget.spent(con, p), 4), budget.CAPS_USD[p]) for p in ("meta", "baseten")},
        "recent": con.execute("SELECT * FROM receipts ORDER BY id DESC LIMIT 30").fetchall()})


@app.get("/agent", response_class=HTMLResponse)
def agent_page(request: Request):
    con = _con()
    con.execute("CREATE TABLE IF NOT EXISTS agent_steps (run_id TEXT, step INTEGER, ts TEXT, tool TEXT, args TEXT, "
                "result TEXT, cost_usd REAL)")
    runs = [r[0] for r in con.execute("SELECT DISTINCT run_id FROM agent_steps ORDER BY run_id DESC LIMIT 10")]
    steps = {r: [dict(x) for x in con.execute("SELECT * FROM agent_steps WHERE run_id=? ORDER BY step, rowid",
                                              (r,))] for r in runs}
    return T.TemplateResponse(request, "agent.html", {"runs": runs, "steps": steps})


@app.post("/agent/run")
def agent_run():
    from .. import agent
    agent.run()
    return RedirectResponse("/agent", status_code=303)


# ------------------------------------------------------------------ owner spot check of the Claude gold labels
def _spot_sample(con) -> list[str]:
    """Fixed, seeded sample: every actionable real review, 14 real praise items, 30 held-out synthetic items."""
    import random
    rnd = random.Random(20261029)
    real = con.execute("SELECT l.item_id, l.category FROM labels l JOIN splits s ON s.item_id=l.item_id "
                       "WHERE s.split='test_real' AND l.source='gold_claude' ORDER BY l.item_id").fetchall()
    act = [r[0] for r in real if r[1] not in ("praise", "spam_or_offtopic")]
    rest = [r[0] for r in real if r[0] not in act]
    synth = [r[0] for r in con.execute("SELECT l.item_id FROM labels l JOIN splits s ON s.item_id=l.item_id "
                                       "WHERE s.split='test_synth' AND l.source='gold_claude' ORDER BY l.item_id")]
    return act + rnd.sample(rest, min(14, len(rest))) + rnd.sample(synth, min(30, len(synth)))


@app.get("/spotcheck", response_class=HTMLResponse)
def spotcheck(request: Request):
    con = _con()
    con.execute("CREATE TABLE IF NOT EXISTS spotcheck (item_id TEXT PRIMARY KEY, verdict TEXT, corrected TEXT, ts TEXT)")
    ids = _spot_sample(con)
    rows = []
    for i in ids:
        r = con.execute("SELECT i.id, i.text, i.synthetic, l.category, l.severity, sc.verdict, sc.corrected FROM items i "
                        "JOIN labels l ON l.item_id=i.id AND l.source='gold_claude' LEFT JOIN spotcheck sc "
                        "ON sc.item_id=i.id WHERE i.id=?", (i,)).fetchone()
        rows.append(dict(r))
    done = sum(1 for r in rows if r["verdict"])
    agree = sum(1 for r in rows if r["verdict"] == "agree")
    from ..taxonomy import CATEGORIES
    return T.TemplateResponse(request, "spotcheck.html", {"rows": rows, "done": done, "agree": agree,
                                                          "cats": CATEGORIES})


@app.post("/spotcheck/{item_id}")
def spotcheck_save(item_id: str, verdict: str = Form(...), corrected: str = Form("")):
    con = _con()
    con.execute("INSERT OR REPLACE INTO spotcheck VALUES (?,?,?,?)",
                (item_id, verdict, corrected or None, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))
    con.commit()
    return RedirectResponse(f"/spotcheck#{item_id}", status_code=303)


# ------------------------------------------------------------------ live try-it: scrub, then triage locally
@app.get("/try", response_class=HTMLResponse)
def try_page(request: Request):
    from .. import student
    return T.TemplateResponse(request, "try.html", {"result": None, "local": student.available()})


@app.post("/try", response_class=HTMLResponse)
def try_run(request: Request, text: str = Form(...)):
    import time as _t
    from .. import student, triage
    from ..privacy import scrub
    clean, hits = scrub(text)
    local = student.available()
    t0 = _t.time()
    if local:
        lab = student.classify(clean)
        engine = "Muse Glimmer 30B student, on this PC (llama.cpp, no network)"
    else:
        lab = next(iter(triage.label_items("meta", "muse-spark-1.3", [{"id": "try", "text": clean}],
                                           purpose="try-it").values()))
        engine = "Muse Spark 1.3 teacher (hosted)"
    res = {"clean": clean, "hits": hits, "label": lab, "engine": engine, "ms": round((_t.time() - t0) * 1000)}
    return T.TemplateResponse(request, "try.html", {"result": res, "local": local, "text": text})
