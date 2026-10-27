"""Muse Glimmer 30B on a Modal H100: zero-shot baseline, QLoRA distillation from the Spark teacher, student eval.

Paid only from the Meta-hackathon Modal credit (app and volume names start with `meta-`). One function call,
hard timeout, the ephemeral app stops when this script exits. Training data is synthetic only; the test items are
the pseudonymised, scrubbed real reviews and the held-out synthetic reviews.

    MODAL_CONFIG_PATH=... MODAL_PROFILE=ruicodex  <cloudgpu venv python> students/modal_glimmer.py --stage all
Outputs (local, git-ignored): data/students/pred_glimmer-{base,student}_{test_real,test_synth}.jsonl,
data/students/glimmer_train_log.json. The adapter stays in the private Modal volume `meta-steward-glimmer`.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("MODAL_CONFIG_PATH", r"C:\Users\Admin\.ruicodex-keys\modal.toml")
os.environ.setdefault("MODAL_PROFILE", "ruicodex")
import modal  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GPU = os.environ.get("META_GPU", "H100")
MAX_MIN = int(os.environ.get("META_MAX_MIN", "80"))
BASE = "meta-models/Muse-Glimmer-30B"

image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("torch==2.7.1", "transformers==5.20.2", "peft==0.21.2", "bitsandbytes==0.50.2",
                      "accelerate==1.15.0", "safetensors")
         .env({"HF_HOME": "/vol/hf"}))
vol = modal.Volume.from_name("meta-steward-glimmer", create_if_missing=True)
app = modal.App("meta-storefront-glimmer")

SYSTEM = None  # filled from students/common.py at call time (sent as an argument)


@app.function(image=image, gpu=GPU, volumes={"/vol": vol}, timeout=MAX_MIN * 60, cpu=8.0, memory=65536)
def run(stage: str, system: str, train_rows: list, test_sets: dict, cfg: dict) -> dict:
    import math
    import random
    import re
    import subprocess
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoTokenizer, BitsAndBytesConfig, MuseGlimmerForConditionalGeneration

    t_start = time.time()
    log = {"gpu": subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
                                 capture_output=True, text=True).stdout.strip()}
    path = snapshot_download(BASE, allow_patterns=["*.json", "*.safetensors", "*.jinja", "tokenizer*"])
    vol.commit()
    log["download_min"] = round((time.time() - t_start) / 60, 1)
    tok = AutoTokenizer.from_pretrained(path)
    tok.padding_side = "left"
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                           bnb_4bit_use_double_quant=True, bnb_4bit_quant_storage=torch.bfloat16)
    model = MuseGlimmerForConditionalGeneration.from_pretrained(path, quantization_config=q, dtype=torch.bfloat16,
                                                               device_map="auto")
    log["load_min"] = round((time.time() - t_start) / 60, 1)

    def msgs(text):
        return [{"role": "system", "content": system}, {"role": "user", "content": text}]

    def prompt(text):
        return tok.apply_chat_template(msgs(text), tokenize=False, add_generation_prompt=True,
                                       reasoning_strength="low")

    def answer_part(s: str) -> str:
        # Glimmer may think first (to=self ...); the answer is the to=user channel
        m = re.search(r"to=user<\|message\|>(.*?)(<\|eot\|>|$)", s, re.S)
        return m.group(1) if m else s

    def predict(rows, max_new, bs):
        out = []
        model.eval()
        for i in range(0, len(rows), bs):
            chunk = rows[i:i + bs]
            enc = tok([prompt(r["text"]) for r in chunk], return_tensors="pt", padding=True,
                      add_special_tokens=False).to(model.device)
            t0 = time.time()
            with torch.no_grad():
                g = model.generate(**enc, max_new_tokens=max_new, do_sample=False, pad_token_id=tok.pad_token_id)
            ms = (time.time() - t0) * 1000 / len(chunk)
            for r, seq in zip(chunk, g):
                txt = tok.decode(seq[enc["input_ids"].shape[1]:], skip_special_tokens=False)
                out.append({"id": r["id"], "out": answer_part(txt)[:300], "ms": round(ms, 1),
                            "new_tokens": int((seq[enc["input_ids"].shape[1]:] != tok.pad_token_id).sum())})
        return out

    res = {"log": log}
    if stage in ("all", "base"):
        t0 = time.time()
        res["base"] = {k: predict(v, cfg.get("base_max_new", 320), cfg.get("bs", 24)) for k, v in test_sets.items()}
        log["base_eval_min"] = round((time.time() - t0) / 60, 1)
    if stage in ("all", "train"):
        from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
        model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none",
                                                 task_type="CAUSAL_LM",
                                                 # language-model attention only; the vision tower is untouched
                                                 target_modules=r"^(?!.*vision).*\.(q_proj|k_proj|v_proj|o_proj)$"))
        data = []
        for r in train_rows:
            p = prompt(r["text"])
            full = tok.apply_chat_template(msgs(r["text"]) + [{"role": "assistant", "content": r["target"]}],
                                           tokenize=False, reasoning_strength="low")
            tgt = full[len(p):] if full.startswith(p) else " to=user<|message|>" + r["target"] + "<|eot|>"
            pi = tok(p, add_special_tokens=False)["input_ids"]
            ti = tok(tgt, add_special_tokens=False)["input_ids"]
            data.append(((pi + ti)[:384], ([-100] * len(pi) + ti)[:384]))
        rnd = random.Random(20261027)
        epochs, micro, accum = cfg.get("epochs", 2), cfg.get("micro", 8), cfg.get("accum", 2)
        steps = math.ceil(len(data) * epochs / (micro * accum))
        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=cfg.get("lr", 2e-4))
        warm = max(1, int(0.05 * steps))
        sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * max(0.0, (steps - s) / steps))
        model.train()
        order, losses, t0 = [], [], time.time()
        for step in range(steps):
            for _ in range(accum):
                if len(order) < micro:
                    order += rnd.sample(range(len(data)), len(data))
                idx, order = order[:micro], order[micro:]
                b = [data[i] for i in idx]
                L = max(len(x[0]) for x in b)
                ids = torch.tensor([[tok.pad_token_id] * (L - len(x[0])) + x[0] for x in b], device=model.device)
                lab = torch.tensor([[-100] * (L - len(x[1])) + x[1] for x in b], device=model.device)
                att = torch.tensor([[0] * (L - len(x[0])) + [1] * len(x[0]) for x in b], device=model.device)
                loss = model(input_ids=ids, attention_mask=att, labels=lab).loss / accum
                loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
            losses.append(round(loss.item() * accum, 4))
            if (time.time() - t_start) / 60 > MAX_MIN - 18:       # leave time to save and evaluate
                log["stopped_early_at_step"] = step + 1
                break
        log.update(train_examples=len(data), train_steps_planned=steps, train_steps_done=len(losses),
                   train_min=round((time.time() - t0) / 60, 1), loss_first=losses[:5], loss_last=losses[-5:])
        model.save_pretrained("/vol/adapters/glimmer-steward-lora")
        vol.commit()
        t0 = time.time()
        res["student"] = {k: predict(v, cfg.get("student_max_new", 48), cfg.get("bs", 24)) for k, v in test_sets.items()}
        log["student_eval_min"] = round((time.time() - t0) / 60, 1)
    log["total_min"] = round((time.time() - t_start) / 60, 1)
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="all", choices=["all", "base", "train"])
    a = ap.parse_args()
    sys.path.insert(0, str(ROOT / "students"))
    from common import SYSTEM as system, parse  # noqa: E402
    S = ROOT / "data" / "students"
    train = [json.loads(l) for l in open(S / "train.jsonl", encoding="utf-8")]
    tests = {k: [json.loads(l) for l in open(S / f"{k}_items.jsonl", encoding="utf-8")] for k in ("test_real", "test_synth")}
    t0 = time.time()
    with modal.enable_output():
        with app.run():
            res = run.remote(a.stage, system, train if a.stage != "base" else [], tests, {})
    wall = round((time.time() - t0) / 60, 1)
    res["log"]["wall_min_local"] = wall
    for kind in ("base", "student"):
        for split, rows in (res.get(kind) or {}).items():
            with open(S / f"pred_glimmer-{kind}_{split}.jsonl", "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps({"id": r["id"], **parse(r["out"]), "ms": r["ms"],
                                        "new_tokens": r["new_tokens"], "raw": r["out"][:200]}, ensure_ascii=False) + "\n")
    (S / "glimmer_train_log.json").write_text(json.dumps(res["log"], indent=1), encoding="utf-8")
    print(json.dumps(res["log"], indent=1))


if __name__ == "__main__":
    main()
