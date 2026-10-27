"""QLoRA distillation of the Spark teacher into Llama 3.2 3B-Instruct, on one 8 GB laptop GPU.

Run in the shared fine-tune venv (torch + transformers + peft + bitsandbytes):
    python students/train_lora.py --base <dir> --train data/students/train.jsonl --out data/students/llama3b-lora
Train file: JSONL rows {"text": ..., "target": "<compact json>"} built by scripts/build_student_data.py.
Only the assistant turn is trained (prompt tokens are masked).
"""
import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import messages  # noqa: E402


def encode(tok, text, target, max_len):
    prompt = tok.apply_chat_template(messages(text), tokenize=False, add_generation_prompt=True)
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    t_ids = tok(target + tok.eos_token, add_special_tokens=False)["input_ids"]
    ids = (p_ids + t_ids)[:max_len]
    labels = ([-100] * len(p_ids) + t_ids)[:max_len]
    return ids, labels


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--train", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=float, default=2.0)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--max-len", type=int, default=320)
    ap.add_argument("--max-minutes", type=float, default=40.0, help="hard stop to respect the shared GPU slot")
    ap.add_argument("--seed", type=int, default=20261027)
    a = ap.parse_args()
    random.seed(a.seed)
    torch.manual_seed(a.seed)

    tok = AutoTokenizer.from_pretrained(a.base)
    tok.pad_token = tok.pad_token or tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        a.base, quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                                                       bnb_4bit_compute_dtype=torch.bfloat16,
                                                       bnb_4bit_use_double_quant=True),
        torch_dtype=torch.bfloat16, device_map={"": 0})
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.05, bias="none",
                                             task_type="CAUSAL_LM",
                                             target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                                             "gate_proj", "up_proj", "down_proj"]))
    rows = [json.loads(l) for l in open(a.train, encoding="utf-8")]
    data = [encode(tok, r["text"], r["target"], a.max_len) for r in rows]
    steps_per_epoch = math.ceil(len(data) / a.batch)
    total = int(steps_per_epoch * a.epochs)
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, (s + 1) / max(1, int(0.05 * total))) * max(0.0, (total - s) / total))
    model.train()
    t0, step, log = time.time(), 0, []
    order = []
    while step < total:
        if not order:
            order = list(range(len(data)))
            random.shuffle(order)
        idx, order = order[:a.batch], order[a.batch:]
        batch = [data[i] for i in idx]
        L = max(len(x[0]) for x in batch)
        ids = torch.tensor([x[0] + [tok.pad_token_id] * (L - len(x[0])) for x in batch], device="cuda")
        lab = torch.tensor([x[1] + [-100] * (L - len(x[1])) for x in batch], device="cuda")
        att = torch.tensor([[1] * len(x[0]) + [0] * (L - len(x[0])) for x in batch], device="cuda")
        loss = model(input_ids=ids, attention_mask=att, labels=lab).loss
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step(); sched.step(); opt.zero_grad(set_to_none=True)
        step += 1
        if step % 20 == 0 or step == total:
            el = (time.time() - t0) / 60
            log.append({"step": step, "loss": round(loss.item(), 4), "minutes": round(el, 2)})
            print(json.dumps(log[-1]), flush=True)
            if el > a.max_minutes:
                print("time budget reached, stopping early", flush=True)
                break
    Path(a.out).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    json.dump({"args": vars(a), "examples": len(data), "steps": step, "total_planned": total, "log": log,
               "minutes": round((time.time() - t0) / 60, 2),
               "gpu": torch.cuda.get_device_name(0), "peak_mem_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2)},
              open(Path(a.out) / "train_log.json", "w"), indent=1)


if __name__ == "__main__":
    main()
