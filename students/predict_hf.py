"""Batch predictions with a local Hugging Face model (optionally with a LoRA adapter). Greedy decoding.

    python students/predict_hf.py --base <dir> [--adapter <dir>] --inp items.jsonl --out preds.jsonl
Input rows: {"id", "text"}. Output rows: {"id", "category", "severity", "language", "parsed", "ms"}.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import messages, parse  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--adapter")
    ap.add_argument("--inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--four-bit", action="store_true")
    a = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(a.adapter or a.base)
    tok.pad_token = tok.pad_token or tok.eos_token
    tok.padding_side = "left"
    kw = dict(torch_dtype=torch.bfloat16, device_map={"": 0})
    if a.four_bit:
        kw["quantization_config"] = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=torch.bfloat16)
    model = AutoModelForCausalLM.from_pretrained(a.base, **kw)
    if a.adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, a.adapter)
    model.eval()
    rows = [json.loads(l) for l in open(a.inp, encoding="utf-8")]
    with open(a.out, "w", encoding="utf-8") as fo:
        for i in range(0, len(rows), a.batch):
            chunk = rows[i:i + a.batch]
            prompts = [tok.apply_chat_template(messages(r["text"]), tokenize=False, add_generation_prompt=True)
                       for r in chunk]
            enc = tok(prompts, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda")
            t0 = time.time()
            with torch.no_grad():
                gen = model.generate(**enc, max_new_tokens=48, do_sample=False, pad_token_id=tok.pad_token_id)
            ms = (time.time() - t0) * 1000 / len(chunk)
            for r, g in zip(chunk, gen):
                out = tok.decode(g[enc["input_ids"].shape[1]:], skip_special_tokens=True)
                fo.write(json.dumps({"id": r["id"], **parse(out), "ms": round(ms, 1), "raw": out[:200]},
                                    ensure_ascii=False) + "\n")
            print(f"{i + len(chunk)}/{len(rows)}", flush=True)


if __name__ == "__main__":
    main()
