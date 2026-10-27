#!/usr/bin/env bash
# One shared-GPU slot (<= 45 min): Muse Glimmer 30B Q4_K_M with partial GPU offload, zero-shot predictions.
# Resumable: predict_llamacpp.py skips ids already written. Server is always stopped at the end.
set -u
P=/c/Users/Admin/Desktop/Software/Hackathons/meta-storefront-steward
S=$P/data/students
LOG=$P/data/logs/gpu_job_glimmer_$(date -u +%Y%m%dT%H%M%S).log
cd "$P"
{
  echo "start $(date -u)"
  PID=$(powershell -NoProfile -ExecutionPolicy Bypass -File students/start_glimmer.ps1 -Gpu 22 -Budget 256 | tr -d '\r' | tail -1)
  echo "server pid $PID"
  for i in $(seq 1 60); do curl -s -m 2 http://127.0.0.1:8088/health | grep -q ok && break; sleep 5; done
  timeout 1500 "$P/.venv/Scripts/python" students/predict_llamacpp.py --inp "$S/test_real_items.jsonl" --out "$S/pred_glimmer-base_test_real.jsonl"
  timeout 900 "$P/.venv/Scripts/python" students/predict_llamacpp.py --inp "$S/test_synth_items.jsonl" --ids "$S/glimmer_subset_synth_ids.txt" --out "$S/pred_glimmer-base_test_synth.jsonl"
  powershell -NoProfile -Command "Stop-Process -Id $PID -Force"
  echo "end $(date -u)"
} > "$LOG" 2>&1
