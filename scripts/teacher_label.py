"""Label the synthetic training pool with the Spark teacher (guided prompt, batches of 20, cached prefix).

Writes labels with source='teacher_spark13'. Re-running only labels what is still unlabelled.
"""
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from steward import db, llm, triage  # noqa: E402


def main(split: str = "train", source: str = "teacher_spark13", provider: str = "meta",
         model: str = "muse-spark-1.3", mode: str = "guided") -> None:
    con = db.connect()
    rows = con.execute(
        "SELECT i.id, i.text FROM items i JOIN splits s ON s.item_id=i.id WHERE s.split=? AND i.id NOT IN "
        "(SELECT item_id FROM labels WHERE source=?)", (split, source)).fetchall()
    items = [{"id": r["id"], "text": r["text"]} for r in rows]
    print(f"{len(items)} items to label with {provider}/{model} ({mode})", flush=True)
    out = triage.label_items(provider, model, items, mode=mode, batch=20, workers=6, purpose=f"label-{source}")
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    for iid, lab in out.items():
        con.execute("INSERT OR REPLACE INTO labels VALUES (?,?,?,?,?,?,?,?)",
                    (iid, source, lab["category"], int(lab["severity"]), lab["language"], lab["gloss_en"],
                     json.dumps(lab, ensure_ascii=False), now))
    con.commit()
    print(f"labelled {len(out)}/{len(items)}; spend {llm.spend_report(con)}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1:]
    main(*a) if a else main()
