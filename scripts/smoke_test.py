"""Day-1 smoke test from Belgium: is each Meta capability reachable, and what does one call cost?

Writes a short markdown log (no keys, no review data) to ops/SMOKE_<date>.md.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from steward import config, db, llm  # noqa: E402

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["category", "severity", "language", "gloss_en"],
    "properties": {
        "category": {"type": "string", "enum": ["bug", "crash", "performance", "feature_request", "billing", "ads",
                                                "ux_confusion", "praise", "spam_or_offtopic"]},
        "severity": {"type": "integer", "minimum": 1, "maximum": 4},
        "language": {"type": "string"},
        "gloss_en": {"type": "string"},
    },
}
SAMPLE = "Depuis la mise à jour 2.3 le jeu se ferme au niveau 12, dommage, j'adorais."   # synthetic


def main() -> None:
    con = db.connect()
    lines = [f"# Smoke test {dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')}", ""]
    r = httpx.get(config.META_BASE_URL + "/models", headers={"Authorization": "Bearer " + config.meta_api_key()},
                  timeout=60)
    ids = sorted(m["id"] for m in r.json().get("data", [])) if r.status_code == 200 else []
    lines.append(f"- `GET /v1/models` (Meta): HTTP {r.status_code}; {len(ids)} models: {', '.join(ids)}")

    msgs = [{"role": "system", "content": "Classify one app-store review. Answer with JSON only."},
            {"role": "user", "content": SAMPLE}]
    res = llm.chat("meta", "muse-spark-1.3", msgs, purpose="smoke", max_tokens=2000, schema=SCHEMA,
                   reasoning_effort="low", con=con)
    lines.append(f"- muse-spark-1.3 structured output: `{json.dumps(res.data, ensure_ascii=False)}`; "
                 f"tokens in/cached/out {res.usage.input_tokens}/{res.usage.cached_tokens}/{res.usage.output_tokens}; "
                 f"USD {res.cost_usd:.6f}; {res.latency_ms} ms")

    try:
        res2 = llm.chat("baseten", "meta-models/muse-spark-open-1026", msgs, purpose="smoke", max_tokens=4000,
                        schema=SCHEMA, con=con)
        lines.append(f"- Baseten muse-spark-open-1026 structured output: `{json.dumps(res2.data, ensure_ascii=False)}`; "
                     f"tokens in/out {res2.usage.input_tokens}/{res2.usage.output_tokens}; USD {res2.cost_usd:.6f}; "
                     f"{res2.latency_ms} ms")
    except Exception as e:  # report, do not hide
        lines.append(f"- Baseten muse-spark-open-1026: FAILED {type(e).__name__}: {str(e)[:200]}")

    lines.append(f"- Spend after test: {json.dumps(llm.spend_report(con))}")
    out = ROOT / "ops" / f"SMOKE_{dt.date.today()}.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
