"""Turn teacher-labelled synthetic items into student training files. Synthetic only: no real review is used.

Outputs (git-ignored, under data/students/):
  train.jsonl / dev.jsonl         {"id","text","target"} for students/train_lora.py
  fireworks_train.jsonl           {"messages":[...]} for Fireworks managed SFT (Muse Glimmer)
  test_real.jsonl / test_synth.jsonl   {"id","text"} for predictions
A 10% dev split is carved from the training pool with a fixed seed.
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "students"))
from steward import config, db  # noqa: E402
from common import messages, target  # noqa: E402


def main(teacher: str = "teacher_spark13") -> None:
    con = db.connect()
    out = config.DATA / "students"
    out.mkdir(parents=True, exist_ok=True)
    rows = con.execute(
        "SELECT i.id, i.text, l.category, l.severity, l.language FROM items i JOIN splits s ON s.item_id=i.id "
        "JOIN labels l ON l.item_id=i.id AND l.source=? WHERE s.split IN ('train','dev') AND i.synthetic=1 "
        "ORDER BY i.id", (teacher,)).fetchall()
    rnd = random.Random(20261027)
    rows = list(rows)
    rnd.shuffle(rows)
    n_dev = len(rows) // 10
    dev, train = rows[:n_dev], rows[n_dev:]
    for r in dev:
        con.execute("UPDATE splits SET split='dev' WHERE item_id=?", (r["id"],))
    con.commit()
    with open(out / "train.jsonl", "w", encoding="utf-8") as ft, open(out / "fireworks_train.jsonl", "w",
                                                                        encoding="utf-8") as ff:
        for r in train:
            t = target(r["category"], r["severity"], r["language"])
            ft.write(json.dumps({"id": r["id"], "text": r["text"], "target": t}, ensure_ascii=False) + "\n")
            ff.write(json.dumps({"messages": messages(r["text"]) + [{"role": "assistant", "content": t}]},
                                ensure_ascii=False) + "\n")
    with open(out / "dev.jsonl", "w", encoding="utf-8") as fd:
        for r in dev:
            fd.write(json.dumps({"id": r["id"], "text": r["text"],
                                 "target": target(r["category"], r["severity"], r["language"])},
                                ensure_ascii=False) + "\n")
    for split in ("test_real", "test_synth", "dev"):
        items = con.execute("SELECT i.id, i.text FROM items i JOIN splits s ON s.item_id=i.id WHERE s.split=? "
                            "ORDER BY i.id", (split,)).fetchall()
        with open(out / f"{split}_items.jsonl", "w", encoding="utf-8") as f:
            for r in items:
                f.write(json.dumps({"id": r["id"], "text": r["text"]}, ensure_ascii=False) + "\n")
    print(f"train {len(train)}, dev {len(dev)}")


if __name__ == "__main__":
    main()
