"""Independent second-model review of the 50 spot-check cards. NOT a human check.

The owner asked for the 30-minute spot check to be done for him (29 Oct). It is therefore done by a different model,
and it is reported as an independent AI review, never as a human check.

* Reviewer: Claude Opus 5.5 (Anthropic API), not Muse Spark (the teacher) and not the session that wrote the gold
  labels. It gets its own prompt (the label definitions only) and labels each item BLIND: it never sees the gold
  label, the teacher's label or anyone's reasoning. Agreement is computed afterwards, in code.
* Same 50 cards as the owner's spot-check page (`steward.web.app._spot_sample`, fixed seed).
* Same privacy rules as every model call: scrubbed, pseudonymised text only; the outbound personal-data scan runs
  first and blocks the call on any hit; priced before sending against its own cap; written to the receipts table.
* "Agreed" = same category AND severity within one level (the spot-check page asked whether the label is right;
  severity within one is the same tolerance as the evaluation's severity metric). Exact-severity agreement is also
  reported.

Output: results/spotcheck.json (per-card labels, counts and disagreements; no review text).
Needs `pip install anthropic==2.3.0` (only this script; the app and the demo do not use it).
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import anthropic  # noqa: E402

from steward import budget, config, db, taxonomy  # noqa: E402
from steward.privacy import scan  # noqa: E402
from steward.web.app import _spot_sample  # noqa: E402

MODEL = "claude-opus-5-5"
REVIEWER = "independent AI review (not human)"

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["category", "severity", "note"],
    "properties": {
        "category": {"type": "string", "enum": taxonomy.CATEGORIES},
        "severity": {"type": "integer", "enum": [1, 2, 3, 4]},
        "note": {"type": "string", "description": "one short sentence, no quotes from the review"},
    },
}

SYSTEM = (
    "You are reviewing app-store feedback for a small games and apps studio, as an independent second opinion.\n"
    "Read one review and decide its single category and its severity, using exactly these definitions.\n\n"
    "Categories:\n" + "\n".join(f"- {c}" for c in taxonomy.CATEGORIES) + "\n"
    "bug = something works wrongly while the app keeps running; crash = closes, freezes, will not start, ANR; "
    "performance = slow, laggy, battery, heat, size; feature_request = asks for something new or different; "
    "billing = purchases, subscriptions, refunds, prices; ads = advertising volume, placement or breakage; "
    "ux_confusion = cannot find or understand something that exists; praise = positive, nothing to act on; "
    "spam_or_offtopic = unrelated, gibberish, wrong app.\n"
    "When several apply: a crash or freeze wins; then any money problem is billing; an ad that causes a crash is a "
    "crash; praise that asks for more is a feature_request at severity 2. The star rating alone decides nothing.\n\n"
    "Severity: " + "; ".join(f"{k} = {v}" for k, v in taxonomy.SEVERITY.items()) + ".\n"
    "Placeholders such as [NAME] or [EMAIL] mean personal data was removed. Return JSON only."
)


def review_one(client, con, text: str) -> tuple[dict, float]:
    if scan(text):
        raise ValueError("personal-data pattern in outbound text; not sent")
    worst = budget.Usage(input_tokens=len(SYSTEM + text) // 3 + 200, output_tokens=4000)
    reserved = budget.reserve(con, "anthropic", MODEL, worst)
    t0 = time.time()
    try:
        r = client.messages.create(
            model=MODEL, max_tokens=4000, system=SYSTEM,
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": f"Review:\n{text}"}])
    except Exception:
        budget.release("anthropic", reserved)
        budget.record(con, "anthropic", MODEL, "independent-review", budget.Usage(),
                      int((time.time() - t0) * 1000), text, status="error")
        raise
    budget.release("anthropic", reserved)
    u = r.usage
    usd = budget.record(con, "anthropic", MODEL, "independent-review",
                        budget.Usage(input_tokens=u.input_tokens, cached_tokens=u.cache_read_input_tokens or 0,
                                     output_tokens=u.output_tokens),
                        int((time.time() - t0) * 1000), SYSTEM + text)
    if r.stop_reason != "end_turn":
        raise RuntimeError(f"stop_reason={r.stop_reason}")
    out = json.loads(next(b.text for b in r.content if b.type == "text"))
    return out, usd


def cross_family(con, ids) -> dict:
    """The gold labels and this reviewer are both Claude models, so their mistakes can correlate. As a control,
    the same agreement rule applied to labels the Meta models already produced for these cards (no new calls)."""
    out = {}
    for src, name in (("spark13_guided", "Muse Spark 1.3, guided (teacher prompt)"),
                      ("sparkopen_guided", "Muse Spark Open, guided (Baseten)")):
        n = a = 0
        dis = []
        for i in ids:
            g = con.execute("SELECT category, severity FROM labels WHERE item_id=? AND source='gold_claude'", (i,)).fetchone()
            l = con.execute("SELECT category, severity FROM labels WHERE item_id=? AND source=?", (i, src)).fetchone()
            if not l:
                continue
            n += 1
            ok = g[0] == l[0] and abs(g[1] - l[1]) <= 1
            a += ok
            if not ok:
                dis.append({"item_id": i, "gold": {"category": g[0], "severity": g[1]},
                            "model": {"category": l[0], "severity": l[1]}})
        out[name] = {"n": n, "agreed": a, "disagreements": dis}
    return out


def main() -> dict:
    con = db.connect()
    client = anthropic.Anthropic(api_key=config.anthropic_api_key())
    ids = _spot_sample(con)
    rows, cost = [], 0.0
    for iid in ids:
        it = con.execute("SELECT id, text, title, synthetic FROM items WHERE id=?", (iid,)).fetchone()
        gold = con.execute("SELECT category, severity FROM labels WHERE item_id=? AND source='gold_claude'",
                           (iid,)).fetchone()
        text = ((it["title"] + " / ") if it["title"] else "") + it["text"]
        try:
            lab, usd = review_one(client, con, text)
            cost += usd
        except Exception as e:  # noqa: BLE001 - counted and listed, never hidden
            rows.append({"item_id": iid, "set": "synthetic" if it["synthetic"] else "real", "error": str(e)[:160]})
            continue
        rows.append({"item_id": iid, "set": "synthetic" if it["synthetic"] else "real",
                     "gold": {"category": gold["category"], "severity": gold["severity"]},
                     "reviewer": {"category": lab["category"], "severity": lab["severity"]},
                     "note": lab["note"][:200]})
    ok = [r for r in rows if "error" not in r]

    def agree(r, exact=False):
        same = r["gold"]["category"] == r["reviewer"]["category"]
        d = abs(r["gold"]["severity"] - r["reviewer"]["severity"])
        return same and (d == 0 if exact else d <= 1)

    by_set = {}
    for s in ("real", "synthetic"):
        rs = [r for r in ok if r["set"] == s]
        by_set[s] = {"n": len(rs), "agreed": sum(agree(r) for r in rs),
                     "category_agreed": sum(r["gold"]["category"] == r["reviewer"]["category"] for r in rs)}
    res = {
        "reviewer": REVIEWER, "model": MODEL, "method": "blind relabel with its own prompt; agreement computed in code",
        "agreement_rule": "same category and severity within one level",
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "sample": len(ids), "reviewed": len(ok), "errors": len(rows) - len(ok),
        "agreed": sum(agree(r) for r in ok),
        "category_agreed": sum(r["gold"]["category"] == r["reviewer"]["category"] for r in ok),
        "exact_agreed": sum(agree(r, exact=True) for r in ok),
        "by_set": by_set, "cost_usd": round(cost, 4),
        "disagreements": [r for r in ok if not agree(r)],
        "severity_one_level_apart": [r for r in ok if agree(r) and not agree(r, exact=True)],
        "error_items": [r for r in rows if "error" in r],
        "cross_family_control": cross_family(con, ids),
        "items": [{k: r[k] for k in ("item_id", "set", "gold", "reviewer")} for r in ok],
    }
    (ROOT / "results" / "spotcheck.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n",
                                                     encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in res.items() if k not in ("disagreements", "items")}, indent=1))
    for r in res["disagreements"]:
        print("DISAGREE", r["item_id"], r["set"], r["gold"], "->", r["reviewer"], "|", r["note"])
    return res


if __name__ == "__main__":
    main()
