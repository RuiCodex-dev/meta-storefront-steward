"""One door for every model call: Meta Model API, Baseten (Muse Spark Open) and local open weights.

Every call goes through three checks before anything leaves the machine:
1. the outbound PII scan (`privacy.scan`) on every text part: any hit blocks the call;
2. the budget guard (`budget.reserve`) with the worst-case cost: over the cap blocks the call;
3. Standard mode only: Contributor-mode model ids are refused.
After the call the real usage is priced and written to `receipts`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from . import budget, config, db
from .privacy import scan


class OutboundPIIBlocked(RuntimeError):
    pass


class TruncatedOutput(RuntimeError):
    pass


def _strip_fences(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        s = s.rsplit("```", 1)[0]
    return s.strip()


PROVIDERS = {
    "meta": (config.META_BASE_URL, config.meta_api_key),
    "baseten": (config.BASETEN_BASE_URL, config.baseten_api_key),
}
_clients: dict[str, OpenAI] = {}


def client(provider: str) -> OpenAI:
    if provider not in _clients:
        if provider == "local":
            import os
            _clients[provider] = OpenAI(base_url=os.environ.get("STEWARD_LOCAL_URL", "http://127.0.0.1:8088/v1"),
                                        api_key="local")
        else:
            url, key = PROVIDERS[provider]
            _clients[provider] = OpenAI(base_url=url, api_key=key(), timeout=600, max_retries=2)
    return _clients[provider]


def _texts(messages: list[dict]) -> list[str]:
    out = []
    for m in messages:
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out += [p.get("text", "") for p in c if isinstance(p, dict) and p.get("type") in ("text", "input_text")]
    return out


def _approx_tokens(s: str) -> int:
    return max(1, len(s) // 3)          # conservative for multilingual text


@dataclass
class Result:
    text: str
    data: Any
    usage: budget.Usage
    cost_usd: float
    latency_ms: int
    model: str
    provider: str
    message: Any = None          # raw assistant message (carries tool_calls for the agent loop)


def chat(provider: str, model: str, messages: list[dict], *, purpose: str, max_tokens: int = 1024,
         schema: dict | None = None, schema_name: str = "out", temperature: float | None = 0.0,
         reasoning_effort: str | None = None,
         con=None, extra: dict | None = None, tools: list[dict] | None = None) -> Result:
    con = con or db.connect()
    # 1. outbound privacy gate
    for t in _texts(messages):
        hits = scan(t)
        if hits:
            raise OutboundPIIBlocked(f"{purpose}: personal data pattern(s) {hits} in outbound text; call blocked")
    # 2. budget gate (worst case: no cache, full output)
    prompt_text = "\n".join(_texts(messages))
    worst = budget.Usage(input_tokens=_approx_tokens(prompt_text) + 200, output_tokens=max_tokens)
    reserved = budget.reserve(con, provider, model, worst)
    kw: dict[str, Any] = dict(model=model, messages=messages, max_tokens=max_tokens)
    if temperature is not None:
        kw["temperature"] = temperature
    if schema is not None:
        kw["response_format"] = {"type": "json_schema",
                                 "json_schema": {"name": schema_name, "schema": schema, "strict": True}}
    if reasoning_effort:
        kw["reasoning_effort"] = reasoning_effort
    if extra:
        kw.update(extra)
    if tools:
        kw["tools"] = tools
    t0 = time.time()
    try:
        resp = client(provider).chat.completions.create(**kw)
    except Exception:
        budget.release(provider, reserved)
        budget.record(con, provider, model, purpose, budget.Usage(), int((time.time() - t0) * 1000), prompt_text,
                      status="error")
        raise
    budget.release(provider, reserved)
    ms = int((time.time() - t0) * 1000)
    u = resp.usage
    cached = 0
    if u is not None and getattr(u, "prompt_tokens_details", None):
        cached = getattr(u.prompt_tokens_details, "cached_tokens", 0) or 0
    usage = budget.Usage(input_tokens=getattr(u, "prompt_tokens", 0) or 0, cached_tokens=cached,
                         output_tokens=getattr(u, "completion_tokens", 0) or 0)
    choice = resp.choices[0]
    text = choice.message.content or ""
    has_tools = bool(getattr(choice.message, "tool_calls", None))
    status = "ok" if (text or has_tools) else f"empty({choice.finish_reason})"
    usd = budget.record(con, provider, model, purpose, usage, ms, prompt_text, status=status)
    if not text and not has_tools:
        # Reasoning tokens count against max_tokens; a 'length' stop with no content means the
        # budget was spent thinking. Say so instead of failing inside json.loads.
        raise TruncatedOutput(f"{provider}/{model}: no content (finish_reason={choice.finish_reason}, "
                              f"output_tokens={usage.output_tokens}, max_tokens={max_tokens})")
    data = None
    if schema is not None:
        if choice.finish_reason == "length":
            raise TruncatedOutput(f"{provider}/{model}: output cut at max_tokens={max_tokens} "
                                  f"(output_tokens={usage.output_tokens}); JSON incomplete")
        data = json.loads(_strip_fences(text))
    return Result(text=text, data=data, usage=usage, cost_usd=usd, latency_ms=ms, model=model, provider=provider,
                  message=choice.message)


def spend_report(con=None) -> dict:
    con = con or db.connect()
    return {p: {"spent_usd": round(budget.spent(con, p), 4), "cap_usd": budget.CAPS_USD[p]}
            for p in ("meta", "baseten")}
