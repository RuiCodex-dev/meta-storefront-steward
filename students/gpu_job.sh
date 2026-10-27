#!/usr/bin/env bash
# One shared-GPU slot (<= 45 min): train the Llama 3.2 3B student, then predict with student and base model.
# Started by the Zindi gpu_queue; every path is absolute so the queue's working directory does not matter.
set -u
P=/c/Users/Admin/Desktop/Software/Hackathons/meta-storefront-steward
FT=/c/Users/Admin/Desktop/Software/Hackathons/_tools/venvs/meta-ft/Scripts/python.exe
BASE=/c/Users/Admin/Desktop/Software/Hackathons/_models/Llama-3.2-3B-Instruct
S=$P/data/students
LOG=$P/data/logs/gpu_job_$(date -u +%Y%m%dT%H%M%S).log
cd "$P"
{
  echo "start $(date -u)"
  "$P/.venv/Scripts/python" scripts/export_items.py
  timeout 1680 "$FT" students/train_lora.py --base "$BASE" --train "$S/train.jsonl" --out "$S/llama3b-lora" --max-minutes 25
  for split in test_real test_synth; do
    timeout 200 "$FT" students/predict_hf.py --base "$BASE" --adapter "$S/llama3b-lora" --inp "$S/${split}_items.jsonl" --out "$S/pred_llama3b-student_${split}.jsonl"
  done
  for split in test_real test_synth; do
    timeout 200 "$FT" students/predict_hf.py --base "$BASE" --inp "$S/${split}_items.jsonl" --out "$S/pred_llama3b-base_${split}.jsonl"
  done
  echo "end $(date -u)"
} > "$LOG" 2>&1
