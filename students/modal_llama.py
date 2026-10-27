"""Llama 3.2 3B-Instruct: zero-shot baseline and QLoRA student on one Modal A10G (Meta-hackathon credit).

Same prompt, targets and hyperparameters as students/train_lora.py (which proved too slow on the shared laptop GPU).
The gated weights are fetched with the HF token passed as an ephemeral Modal secret (never stored on Modal).
    <cloudgpu venv python> students/modal_llama.py
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("MODAL_CONFIG_PATH", r"C:\Users\Admin\.ruicodex-keys\modal.toml")
os.environ.setdefault("MODAL_PROFILE", "ruicodex")
import modal  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("torch==2.7.1", "transformers==5.20.2", "peft==0.21.2", "bitsandbytes==0.50.2",
                      "accelerate==1.15.0", "safetensors")
         .env({"HF_HOME": "/vol/hf"}))
vol = modal.Volume.from_name("meta-steward-glimmer", create_if_missing=True)
app = modal.App("meta-storefront-llama3b")
BASE = "meta-llama/Llama-3.2-3B-Instruct"


def _hf_token() -> str:
    def find(o):
        if isinstance(o, str) and o.startswith("hf_"):
            return o
        if isinstance(o, dict):
            for v in o.values():
                r = find(v)
                if r:
                    return r
    return find(json.load(open(Path.home() / ".ruicodex-keys" / "huggingface.json"))) or os.environ["HF_TOKEN"]


@app.function(image=image, gpu="A10G", volumes={"/vol": vol}, timeout=45 * 60, cpu=4.0, memory=32768)
def run(system: str, train_rows: list, test_sets: dict) -> dict:
    import math
    import random
    import torch
    from huggingface_hub import snapshot_download
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    t_start = time.time()
    path = snapshot_download(BASE, token=os.environ["HF_TOKEN"], allow_patterns=["*.json", "*.safetensors", "tokenizer*"])
    vol.commit()
    tok = AutoTokenizer.from_pretrained(path)
    tok.pad_token = tok.pad_token or tok.eos_token
    tok.padding_side = "left"
    q = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.bfloat16,
                           bnb_4bit_use_double_quant=True)
    model = AutoModelForCausalLM.from_pretrained(path, quantization_config=q, dtype=torch.bfloat16, device_map={"": 0})

    def msgs(t):
        return [{"role": "system", "content": system}, {"role": "user", "content": t}]

    def prompt(t):
        return tok.apply_chat_template(msgs(t), tokenize=False, add_generation_prompt=True)

    def predict(rows, bs=32):
        model.eval()
        out = []
        for i in range(0, len(rows), bs):
            ch = rows[i:i + bs]
            enc = tok([prompt(r["text"]) for r in ch], return_tensors="pt", padding=True, add_special_tokens=False).to(0)
            t0 = time.time()
            with torch.no_grad():
                g = model.generate(**enc, max_new_tokens=48, do_sample=False, pad_token_id=tok.pad_token_id)
            ms = (time.time() - t0) * 1000 / len(ch)
            for r, s in zip(ch, g):
                out.append({"id": r["id"], "out": tok.decode(s[enc["input_ids"].shape[1]:], skip_special_tokens=True),
                            "ms": round(ms, 1)})
        return out

    log = {}
    t0 = time.time()
    res = {"base": {k: predict(v) for k, v in test_sets.items()}}
    log["base_eval_min"] = round((time.time() - t0) / 60, 1)
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj",
                                                             "up_proj", "down_proj"]))
    tok.padding_side = "right"
    data = []
    for r in train_rows:
        p = tok(prompt(r["text"]), add_special_tokens=False)["input_ids"]
        t = tok(r["target"] + tok.eos_token, add_special_tokens=False)["input_ids"]
        data.append(((p + t)[:320], ([-100] * len(p) + t)[:320]))
    rnd = random.Random(20261027)
    bs, epochs = 16, 2
    steps = math.ceil(len(data) * epochs / bs)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=2e-4)
    warm = max(1, int(0.05 * steps))
    sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: min(1.0, (s + 1) / warm) * max(0.0, (steps - s) / steps))
    model.train()
    order, losses, t0 = [], [], time.time()
    for _ in range(steps):
        if len(order) < bs:
            order += rnd.sample(range(len(data)), len(data))
        idx, order = order[:bs], order[bs:]
        b = [data[i] for i in idx]
        L = max(len(x[0]) for x in b)
        ids = torch.tensor([x[0] + [tok.pad_token_id] * (L - len(x[0])) for x in b], device=0)
        lab = torch.tensor([x[1] + [-100] * (L - len(x[1])) for x in b], device=0)
        att = torch.tensor([[1] * len(x[0]) + [0] * (L - len(x[0])) for x in b], device=0)
        loss = model(input_ids=ids, attention_mask=att, labels=lab).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
        losses.append(round(loss.item(), 4))
        if (time.time() - t_start) / 60 > 36:
            log["stopped_early"] = len(losses)
            break
    log.update(train_examples=len(data), steps_planned=steps, steps_done=len(losses),
               train_min=round((time.time() - t0) / 60, 1), loss_first=losses[:5], loss_last=losses[-5:])
    model.save_pretrained("/vol/adapters/llama3b-steward-lora")
    vol.commit()
    tok.padding_side = "left"
    t0 = time.time()
    res["student"] = {k: predict(v) for k, v in test_sets.items()}
    log["student_eval_min"] = round((time.time() - t0) / 60, 1)
    log["total_min"] = round((time.time() - t_start) / 60, 1)
    res["log"] = log
    return res


def main():
    sys.path.insert(0, str(ROOT / "students"))
    from common import SYSTEM, parse  # noqa: E402
    S = ROOT / "data" / "students"
    train = [json.loads(l) for l in open(S / "train.jsonl", encoding="utf-8")]
    tests = {k: [json.loads(l) for l in open(S / f"{k}_items.jsonl", encoding="utf-8")] for k in ("test_real", "test_synth")}
    with modal.enable_output():
        with app.run():
            res = run.with_options(secrets=[modal.Secret.from_dict({"HF_TOKEN": _hf_token()})]).remote(SYSTEM, train, tests)
    for kind in ("base", "student"):
        for split, rows in res[kind].items():
            with open(S / f"pred_llama3b-{kind}_{split}.jsonl", "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps({"id": r["id"], **parse(r["out"]), "ms": r["ms"], "raw": r["out"][:200]},
                                       ensure_ascii=False) + "\n")
    (S / "llama3b_train_log.json").write_text(json.dumps(res["log"], indent=1), encoding="utf-8")
    print(json.dumps(res["log"], indent=1))


if __name__ == "__main__":
    main()
