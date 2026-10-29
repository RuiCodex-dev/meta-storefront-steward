"""Spend guard for every paid model call.

The Meta Billing "spend limit" only sends an e-mail; it does not stop anything. This module is the cap.

* Each call is priced from the published price table BEFORE it is sent, using the worst case
  (all input uncached, the full `max_tokens` of output).
* If the ledger plus that worst case would cross the provider's cap, the call is refused with
  `BudgetExceeded` and nothing is sent.
* After the call the real usage is priced and written to the `receipts` table.

Caps (owner, 2026-10-26/27): Meta Model API USD 140 (credit is 150), Baseten USD 90 (credit is 100).
Prices: dev.meta.ai/docs/pricing-rate-limits and baseten.co/pricing, read 2026-10-27.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import sqlite3
import threading
from dataclasses import dataclass

CAPS_USD = {"meta": 140.0, "baseten": 90.0, "anthropic": 5.0, "local": float("inf")}  # anthropic: independent label review only

# USD per 1M tokens: (input, cached input, output)
TOKEN_PRICES = {
    ("meta", "muse-spark-1.3"): (1.25, 0.15, 4.25),
    ("meta", "muse-spark-1.2"): (1.25, 0.15, 4.25),
    ("meta", "muse-spark-1.1"): (1.25, 0.15, 4.25),
    ("meta", "muse-wonder-1.0"): (4.00, 0.20, 20.00),
    ("baseten", "meta-models/muse-spark-open-1026"): (1.25, 0.15, 4.25),
    ("anthropic", "claude-opus-5-5"): (4.00, 0.20, 20.00),
    ("local", "*"): (0.0, 0.0, 0.0),
}
PER_IMAGE = {("meta", "muse-image-1.0"): 0.01, ("meta", "sam-3.1"): 2.50 / 1000}
PER_FRAME = {("meta", "sam-3.1"): 0.20 / 1000}
FORBIDDEN_MODEL_SUBSTRINGS = ("contributor",)   # Contributor mode is never used (data plan)


_LOCK = threading.Lock()
_PENDING: dict[str, float] = {}   # worst-case cost of calls that are in flight, per provider


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Usage:
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    frames: int = 0


def _price_key(provider: str, model: str):
    if provider == "local":
        return ("local", "*")
    return (provider, model)


def check_model(provider: str, model: str) -> None:
    if any(s in model for s in FORBIDDEN_MODEL_SUBSTRINGS):
        raise ValueError(f"model {model!r} is a Contributor-mode variant; Standard mode only")
    known = set(TOKEN_PRICES) | set(PER_IMAGE) | set(PER_FRAME)
    if provider != "local" and (provider, model) not in known:
        raise ValueError(f"no price for {provider}/{model}; add it to budget.py before calling")


def cost(provider: str, model: str, u: Usage) -> float:
    key = _price_key(provider, model)
    usd = 0.0
    if key in TOKEN_PRICES:
        pin, pcached, pout = TOKEN_PRICES[key]
        uncached = max(u.input_tokens - u.cached_tokens, 0)
        usd += uncached * pin / 1e6 + u.cached_tokens * pcached / 1e6 + u.output_tokens * pout / 1e6
    usd += u.images * PER_IMAGE.get(key, 0.0)
    usd += u.frames * PER_FRAME.get(key, 0.0)
    return usd


def spent(con: sqlite3.Connection, provider: str) -> float:
    row = con.execute("SELECT COALESCE(SUM(cost_usd),0) FROM receipts WHERE provider=?", (provider,)).fetchone()
    return float(row[0])


def reserve(con: sqlite3.Connection, provider: str, model: str, worst: Usage) -> float:
    """Raise BudgetExceeded if spent + in-flight + this worst case would cross the cap.

    The worst case is added to an in-flight total under a lock, so parallel workers cannot all pass the
    check against the same ledger value. `record` (or `release`) removes it again.
    """
    check_model(provider, model)
    worst_usd = cost(provider, model, worst)
    cap = CAPS_USD[provider]
    with _LOCK:
        already = spent(con, provider)
        pending = _PENDING.get(provider, 0.0)
        if already + pending + worst_usd > cap:
            raise BudgetExceeded(
                f"{provider}: spent {already:.4f} + in flight {pending:.4f} + worst case {worst_usd:.4f} "
                f"> cap {cap:.2f} USD; call refused")
        _PENDING[provider] = pending + worst_usd
    return worst_usd


def release(provider: str, worst_usd: float) -> None:
    with _LOCK:
        _PENDING[provider] = max(0.0, _PENDING.get(provider, 0.0) - worst_usd)


def record(con: sqlite3.Connection, provider: str, model: str, purpose: str, u: Usage,
           latency_ms: int, prompt_text: str, status: str = "ok") -> float:
    usd = cost(provider, model, u)
    con.execute(
        "INSERT INTO receipts(ts,provider,model,mode,purpose,input_tokens,cached_tokens,output_tokens,images,frames,"
        "cost_usd,latency_ms,prompt_sha,status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"), provider, model, "standard", purpose,
         u.input_tokens, u.cached_tokens, u.output_tokens, u.images, u.frames, usd, latency_ms,
         hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()[:16], status))
    con.commit()
    return usd


def summary(con: sqlite3.Connection) -> list[dict]:
    rows = con.execute(
        "SELECT provider, model, purpose, COUNT(*) n, SUM(input_tokens) tin, SUM(cached_tokens) tcached, "
        "SUM(output_tokens) tout, SUM(images) imgs, SUM(frames) frames, SUM(cost_usd) usd, "
        "AVG(latency_ms) lat FROM receipts GROUP BY provider, model, purpose ORDER BY provider, model").fetchall()
    return [dict(r) for r in rows]
