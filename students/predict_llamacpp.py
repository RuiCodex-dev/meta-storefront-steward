"""Predictions from a local llama.cpp server (OpenAI-compatible), e.g. Muse Glimmer 30B GGUF on this PC.

    python students/predict_llamacpp.py --inp items.jsonl --out preds.jsonl [--url http://127.0.0.1:8088] [--ids ids.txt]
Resumable: ids already in the output file are skipped. Writes one JSON row per item, with wall-clock ms.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import messages, parse  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", default="http://127.0.0.1:8088")
    ap.add_argument("--ids", help="optional file with one id per line to restrict to")
    ap.add_argument("--max-tokens", type=int, default=600)
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.inp, encoding="utf-8")]
    if a.ids:
        keep = set(Path(a.ids).read_text().split())
        rows = [r for r in rows if r["id"] in keep]
    done = set()
    if Path(a.out).exists():
        done = {json.loads(l)["id"] for l in open(a.out, encoding="utf-8")}
    with open(a.out, "a", encoding="utf-8") as fo:
        for i, r in enumerate(rows):
            if r["id"] in done:
                continue
            t0 = time.time()
            resp = httpx.post(a.url + "/v1/chat/completions",
                              json={"model": "local", "messages": messages(r["text"]),
                                    "max_tokens": a.max_tokens, "temperature": 0}, timeout=900).json()
            msg = resp["choices"][0]["message"]
            out = msg.get("content") or ""
            fo.write(json.dumps({"id": r["id"], **parse(out), "ms": round((time.time() - t0) * 1000),
                                 "out_tokens": resp.get("usage", {}).get("completion_tokens"), "raw": out[:200]},
                                ensure_ascii=False) + "\n")
            fo.flush()
            print(f"{i + 1}/{len(rows)}", flush=True)


if __name__ == "__main__":
    main()
