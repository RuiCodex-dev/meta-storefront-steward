"""Synthetic training and test reviews, grounded in each real app's own store listing, crash causes and
release notes. Never generated from real reviews.

* Training pool: generator A = muse-spark-1.3 (Meta Model API).
* Held-out test pool: generator B = muse-spark-open-1026 (Baseten), a different model, so a student is never
  scored on text written by the same model that wrote its training data.

Every synthetic row is stored with synthetic=1 and store='synthetic', and is never mixed into the real test set.
"""
from __future__ import annotations

import datetime as dt
import json
import random
import threading
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import apps, db, llm, taxonomy
from .privacy import pseudo
from .privacy.scrub import scrub

LANGS = ["en", "en", "en", "tr", "de", "fr", "nl", "es", "it", "pt", "ru", "pl"]
GENERATORS = {
    "A": ("meta", "muse-spark-1.3"),
    "B": ("baseten", "meta-models/muse-spark-open-1026"),
}

SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["reviews"],
    "properties": {"reviews": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["text", "rating", "language", "category", "severity", "app_version"],
        "properties": {
            "text": {"type": "string"},
            "rating": {"type": "integer", "minimum": 1, "maximum": 5},
            "language": {"type": "string"},
            "category": {"type": "string", "enum": taxonomy.CATEGORIES},
            "severity": {"type": "integer", "minimum": 1, "maximum": 4},
            "app_version": {"type": "string"},
        }}}},
}

PROMPT = """Write {n} realistic Google Play reviews for the app below, as different ordinary users would.

App: {title}
Short description: {short}
Description excerpt: {desc}
Recent release notes: {notes}
Real crash/ANR signatures seen in this app (may inspire crash reports; users never quote stack traces): {crashes}

Target category for this batch: {category} ({cat_def}).
Languages, one per review in this order: {langs}.

Rules:
- Sound like real users: varied length (3 to 70 words), casual tone, some typos, slang, emoji, sometimes no punctuation.
- About one in four should be HARD: mixed signals where the tie-break rules below decide the category
  (e.g. praise plus a crash, an ads complaint plus a purchase problem).
- Mention only features plausible for this app. Use plausible version names.
- Never include names of people, e-mail addresses, phone numbers, order ids, links or handles.
- For each review give the category and severity a careful triager would assign under these rules:
{guide}
Return JSON only."""


def _context(con, package: str) -> dict:
    row = con.execute("SELECT title, short_description, full_description FROM app_context WHERE package=? "
                      "ORDER BY CASE WHEN language='en-US' THEN 0 WHEN language LIKE 'en%' THEN 1 ELSE 2 END LIMIT 1",
                      (package,)).fetchone()
    notes = con.execute("SELECT notes FROM releases WHERE package=? AND track='production' LIMIT 3",
                        (package,)).fetchall()
    note_txt = []
    for (n,) in notes:
        d = json.loads(n or "{}")
        note_txt.append(d.get("en-US") or next(iter(d.values()), ""))
    crashes = [r[0] for r in con.execute("SELECT cause FROM crash_issues WHERE package=? LIMIT 5", (package,))]
    return dict(title=row[0] if row else apps.get(package).name, short=(row[1] if row else "") or "",
                desc=((row[2] if row else "") or "")[:900], notes=" | ".join(x for x in note_txt if x)[:500] or "n/a",
                crashes="; ".join(c for c in crashes if c)[:400] or "none recorded")


_DEF = {c: d for c, d in [
    ("bug", "works wrongly but keeps running"), ("crash", "closes, freezes, will not start"),
    ("performance", "slow, laggy, battery, heat"), ("feature_request", "asks for something new"),
    ("billing", "purchases, refunds, prices"), ("ads", "ad volume or placement"),
    ("ux_confusion", "cannot find or understand how to do something"), ("praise", "positive, nothing actionable"),
    ("spam_or_offtopic", "unrelated, gibberish, promotion")]}


def generate_batch(gen: str, package: str, category: str, n: int, seed: int) -> list[dict]:
    provider, model = GENERATORS[gen]
    con = db.connect()
    rnd = random.Random(seed)
    langs = [rnd.choice(LANGS) for _ in range(n)]
    ctx = _context(con, package)
    msg = PROMPT.format(n=n, category=category, cat_def=_DEF[category], langs=", ".join(langs),
                        guide=taxonomy.GUIDE, **ctx)
    # the app's own store text can contain our support e-mail or a URL: scrub before it leaves
    msg, _ = scrub(msg)
    res = llm.chat(provider, model, [{"role": "user", "content": msg}], purpose=f"synth-{gen}",
                   max_tokens=6000 + 400 * n, schema=SCHEMA, temperature=1.0, con=con,
                   reasoning_effort="low" if provider == "meta" else None)
    out = []
    for i, r in enumerate(res.data["reviews"]):
        if r["category"] not in taxonomy.CATEGORIES:
            continue
        text, hits = scrub(r["text"])
        pid = pseudo.pseudonym("S", gen, package, category, str(seed), str(i))
        out.append(dict(id=pid, gen=gen, package=package, intended_category=r["category"],
                        intended_severity=r["severity"], text=text, rating=r["rating"],
                        lang=r["language"][:5], version=r["app_version"][:20], hits=hits, batch_category=category))
    return out


def store(rows: list[dict], split: str) -> int:
    con = db.connect()
    con.execute("CREATE TABLE IF NOT EXISTS synth_meta (item_id TEXT PRIMARY KEY, generator TEXT, "
                "batch_category TEXT, intended_category TEXT, intended_severity INTEGER, created_at TEXT)")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for r in rows:
        con.execute("INSERT OR REPLACE INTO items(id,store,package,kind,rating,lang,text,version_name,scrub_hits,"
                    "synthetic,created_at) VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                    (r["id"], "synthetic", r["package"], "review", r["rating"], r["lang"], r["text"], r["version"],
                     json.dumps(r["hits"]), now))
        con.execute("INSERT OR REPLACE INTO synth_meta VALUES (?,?,?,?,?,?)",
                    (r["id"], r["gen"], r["batch_category"], r["intended_category"], r["intended_severity"], now))
        con.execute("INSERT OR REPLACE INTO splits VALUES (?,?)", (r["id"], split))
    con.commit()
    return len(rows)


def run(gen: str, per_batch: int, split: str, workers: int = 8, packages: list[str] | None = None,
        categories: list[str] | None = None) -> dict:
    jobs = [(p, c) for p in (packages or [a.package for a in apps.included()])
            for c in (categories or taxonomy.CATEGORIES)]
    done = failed = stored = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(generate_batch, gen, p, c, per_batch, zlib.crc32(f"{gen}|{p}|{c}".encode()) & 0xFFFF): (p, c)
                for p, c in jobs}
        for f in as_completed(futs):
            try:
                rows = f.result()
                with lock:
                    stored += store(rows, split)
                    done += 1
            except llm.budget.BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001 - one failed batch must not stop the run
                failed += 1
                print("batch failed", futs[f], type(e).__name__, str(e)[:160])
    return dict(batches=len(jobs), done=done, failed=failed, stored=stored)
