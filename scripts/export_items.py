"""Write the evaluation item files (id, text) without touching splits. Safe to run any time."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from steward import config, db  # noqa: E402

con = db.connect()
out = config.DATA / "students"
out.mkdir(parents=True, exist_ok=True)
for split in ("test_real", "test_synth", "dev"):
    rows = con.execute("SELECT i.id, i.text FROM items i JOIN splits s ON s.item_id=i.id WHERE s.split=? ORDER BY i.id",
                       (split,)).fetchall()
    with open(out / f"{split}_items.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"id": r["id"], "text": r["text"]}, ensure_ascii=False) + "\n")
    print(split, len(rows))
