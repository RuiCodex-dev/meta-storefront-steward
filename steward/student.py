"""The distilled Muse Glimmer student, served on this PC by llama.cpp (official Q4_K_M base + our LoRA GGUF).

No network, no per-call cost: the triage tier the developer can run privately. Uses exactly the prompt the student
was trained on (students/common.py), one review per request, and the same outbound PII scan as hosted calls.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

from .privacy import scan

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "students"))
from common import messages, parse  # noqa: E402

URL = os.environ.get("STEWARD_STUDENT_URL", "http://127.0.0.1:8088")


def available(timeout: float = 2.0) -> bool:
    try:
        return httpx.get(URL + "/health", timeout=timeout).json().get("status") == "ok"
    except Exception:  # noqa: BLE001
        return False


def classify(text: str) -> dict:
    if scan(text):
        raise ValueError("personal data pattern in text; not sent even to the local model")
    t0 = time.time()
    r = httpx.post(URL + "/v1/chat/completions", json={"model": "glimmer-student", "messages": messages(text),
                                                       "max_tokens": 80, "temperature": 0}, timeout=900).json()
    out = parse(r["choices"][0]["message"].get("content") or "")
    out["ms"] = round((time.time() - t0) * 1000)
    return out
