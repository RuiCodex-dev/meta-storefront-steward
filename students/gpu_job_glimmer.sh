#!/usr/bin/env bash
# One shared-GPU slot: Muse Glimmer 30B Q4_K_M with partial GPU offload, zero-shot predictions on this PC.
# Resumable: predict_llamacpp.py skips ids already written.
#
# HARD CAP. The whole job, the llama-server it starts and every child die at CAP seconds (default 40 min, inside the
# queue's 45-min slot), whatever they are doing. Why: on 27 Oct the first version hung for 4 h 20 min with no output.
# It read the server PID through a pipe (`PID=$(powershell start_glimmer.ps1 | tail -1)`). Start-Process with
# redirection creates llama-server with inherited handles, so the server kept that pipe open, the command substitution
# never saw end-of-file, and nothing in the script had a deadline. Now:
#   * the PID comes from a file; the launcher's output goes to NUL (no pipe to inherit);
#   * every step's timeout is the time left until one deadline;
#   * a watchdog kills the server (PID file, then any llama-server still on our port) and this job's whole Windows
#     process tree at the cap; an EXIT/INT/TERM trap stops the server on every other exit path.
# Test without a GPU or model: GLIMMER_JOB_FAKE=1 (hanging step) or =2 (hang outside any step, watchdog only),
#   GLIMMER_JOB_CAP_SEC=20 bash students/gpu_job_glimmer.sh
set -u
P=/c/Users/Admin/Desktop/Software/Hackathons/meta-storefront-steward
S=$P/data/students
CAP=${GLIMMER_JOB_CAP_SEC:-2400}
PORT=8088
FAKE=${GLIMMER_JOB_FAKE:-0}
LOG=$P/data/logs/gpu_job_glimmer_$(date -u +%Y%m%dT%H%M%S).log
PIDF=$P/data/logs/glimmer_server.pid
DEADLINE=$(( $(date +%s) + CAP ))
MYWIN=$(cat /proc/$$/winpid)
cd "$P"
exec > "$LOG" 2>&1

left() { echo $(( DEADLINE - $(date +%s) )); }

stop_server() {
  if [ -s "$PIDF" ]; then
    taskkill //PID "$(tr -dc '0-9' < "$PIDF")" //T //F >/dev/null 2>&1
    rm -f "$PIDF"
  fi
  # fallback: anything still serving our model on our port (never touches other llama-servers)
  powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { \$_.Name -eq 'llama-server.exe' -and \$_.CommandLine -match '--port $PORT' -and \$_.CommandLine -match 'Muse-Glimmer' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force }" >/dev/null 2>&1 < /dev/null
}

# Git Bash: a child's Windows parent is not bash, so `taskkill /T` on bash misses MSYS children. Walk the MSYS tree
# (ps -l: PID PPID PGID WINPID ...; a leading status letter shifts the columns) and kill each process by WINPID too.
_ps() { ps -l | awk 'NR>1 { o = ($1 ~ /^[0-9]+$/) ? 0 : 1; print $(1+o), $(2+o), $(4+o) }'; }
kill_tree() {   # top-down: a parent dies before its children, so it cannot react to a child's death
  local pid=$1 c w kids
  kids=$(_ps | awk -v p="$pid" '$2==p {print $1}')
  w=$(_ps | awk -v p="$pid" '$1==p {print $3}')
  kill -9 "$pid" 2>/dev/null
  [ -n "$w" ] && taskkill //PID "$w" //T //F >/dev/null 2>&1
  for c in $kids; do kill_tree "$c"; done
}

step() {   # step <max seconds> <command...>: bounded by the smaller of its own budget and the time left
  local budget=$1; shift
  local t; t=$(left); [ "$t" -gt "$budget" ] && t=$budget
  if [ "$t" -le 5 ]; then echo "skip (cap reached): $*"; return 124; fi
  timeout --kill-after=10 "$t" "$@"
}

echo "start $(date -u) cap=${CAP}s fake=$FAKE job_winpid=$MYWIN"
# `&&`: only a sleep that ran its full course may kill (a killed sleep on normal exit must not fall through)
( sleep "$CAP" && { echo "CAP ${CAP}s reached $(date -u): hard kill of server and job tree"; stop_server
  for c in $(_ps | awk -v p="$$" '$2==p {print $1}'); do [ "$c" != "$BASHPID" ] && kill_tree "$c"; done
  echo "end $(date -u) (killed at cap)"
  taskkill //PID "$MYWIN" //T //F >/dev/null 2>&1; kill -9 "$$" 2>/dev/null; } ) &
WD=$!
disown "$WD"          # no job-control notice in the log when the watchdog is removed
trap 'stop_server; kill_tree "$WD"; echo "end $(date -u)"' EXIT
trap 'exit 124' INT TERM

if [ "$FAKE" != "0" ]; then
  # same launch path as the real server (Start-Process with redirection) with a harmless stand-in
  step 60 powershell -NoProfile -Command "\$p = Start-Process ping.exe -ArgumentList '-n','100000','127.0.0.1' -RedirectStandardOutput '$(cygpath -w "$P/data/logs/fake_server.out")' -WindowStyle Hidden -PassThru; Set-Content -Path '$(cygpath -w "$PIDF")' -Value \$p.Id -Encoding ascii" > /dev/null 2>&1 < /dev/null
  echo "fake server pid $(tr -dc '0-9' < "$PIDF")"
  if [ "$FAKE" = "3" ]; then
    sleep 3; exit 0                   # finishes normally: the watchdog and its sleep must not outlive the job
  elif [ "$FAKE" = "2" ]; then
    sleep 100000                      # a hang outside any step timeout: only the watchdog can end it
  else
    step 100000 sleep 100000          # a hanging step: its own deadline ends it
  fi
  exit 124
fi

step 60 powershell -NoProfile -ExecutionPolicy Bypass -File students/start_glimmer.ps1 -Gpu 22 -Budget 256 \
  -PidFile "$(cygpath -w "$PIDF")" > /dev/null 2>&1 < /dev/null
echo "server pid $(tr -dc '0-9' < "$PIDF" 2>/dev/null)"
ok=0
while [ "$(left)" -gt 10 ]; do
  curl -s -m 2 "http://127.0.0.1:$PORT/health" | grep -q ok && { ok=1; break; }
  sleep 5
done
[ "$ok" = 1 ] || { echo "server never became healthy"; exit 1; }
step 1500 "$P/.venv/Scripts/python" students/predict_llamacpp.py --inp "$S/test_real_items.jsonl" \
  --out "$S/pred_glimmer-base_test_real.jsonl"
step 900 "$P/.venv/Scripts/python" students/predict_llamacpp.py --inp "$S/test_synth_items.jsonl" \
  --ids "$S/glimmer_subset_synth_ids.txt" --out "$S/pred_glimmer-base_test_synth.jsonl"
