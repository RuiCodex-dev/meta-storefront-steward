"""Muse Image and SAM 3.1 through the same gates as every other call: outbound scan, budget cap, receipts."""
from __future__ import annotations

import base64
import re
import time

import httpx

from . import budget, config, db
from .privacy import scan

BOX = re.compile(r"<\|box;x1=(?P<x1>-?\d+(?:\.\d+)?);y1=(?P<y1>-?\d+(?:\.\d+)?);x2=(?P<x2>-?\d+(?:\.\d+)?);"
                 r"y2=(?P<y2>-?\d+(?:\.\d+)?);w=(?P<w>\d+);h=(?P<h>\d+)(?:;c=(?P<c>[\d.]+))?\|>")
MASK = re.compile(r"<\|mask;[^|]*\|>")


def _headers() -> dict:
    return {"Authorization": "Bearer " + config.meta_api_key(), "Content-Type": "application/json"}


def generate_image(prompt: str, *, size: str = "1024x1536", purpose: str, con=None, references: list[bytes] | None = None,
                   output_format: str = "png") -> bytes:
    con = con or db.connect()
    if scan(prompt):
        raise ValueError("personal data pattern in image prompt; blocked")
    reserved = budget.reserve(con, "meta", "muse-image-1.0", budget.Usage(images=1))
    t0 = time.time()
    try:
        if references:
            body = {"model": "muse-image-1.0", "prompt": prompt, "size": size, "output_format": output_format,
                    "images": [{"image_url": "data:image/png;base64," + base64.b64encode(b).decode()}
                               for b in references]}
            r = httpx.post(config.META_BASE_URL + "/images/edits", json=body, headers=_headers(), timeout=300)
        else:
            body = {"model": "muse-image-1.0", "prompt": prompt, "n": 1, "size": size, "output_format": output_format}
            r = httpx.post(config.META_BASE_URL + "/images/generations", json=body, headers=_headers(), timeout=300)
        r.raise_for_status()
    except Exception:
        budget.release("meta", reserved)
        budget.record(con, "meta", "muse-image-1.0", purpose, budget.Usage(), int((time.time() - t0) * 1000), prompt,
                      status="error")
        raise
    budget.release("meta", reserved)
    budget.record(con, "meta", "muse-image-1.0", purpose, budget.Usage(images=1), int((time.time() - t0) * 1000),
                  prompt)
    return base64.b64decode(r.json()["data"][0]["b64_json"])


def segment(image: bytes, concept: str, *, purpose: str, con=None, mime: str = "image/png") -> dict:
    """SAM 3.1 on one image, one noun-phrase concept. Returns boxes in source pixels plus the raw mask tokens."""
    con = con or db.connect()
    reserved = budget.reserve(con, "meta", "sam-3.1", budget.Usage(images=1))
    t0 = time.time()
    body = {"model": "sam-3.1", "input": [{"type": "message", "role": "user", "content": [
        {"type": "input_text", "text": concept},
        {"type": "input_image", "image_url": f"data:{mime};base64," + base64.b64encode(image).decode()}]}],
            "metadata": {"include_confidence": "true"}}
    try:
        r = httpx.post(config.META_BASE_URL + "/responses", json=body, headers=_headers(), timeout=300)
        r.raise_for_status()
    except Exception:
        budget.release("meta", reserved)
        budget.record(con, "meta", "sam-3.1", purpose, budget.Usage(), int((time.time() - t0) * 1000), concept,
                      status="error")
        raise
    budget.release("meta", reserved)
    budget.record(con, "meta", "sam-3.1", purpose, budget.Usage(images=1), int((time.time() - t0) * 1000), concept)
    d = r.json()
    text = d.get("output_text") or "".join(
        p.get("text", "") for o in d.get("output", []) for p in (o.get("content") or []) if isinstance(p, dict))
    boxes = [{k: (float(v) if v is not None else None) for k, v in m.groupdict().items()} for m in BOX.finditer(text)]
    return {"boxes": boxes, "masks": MASK.findall(text), "raw": text[:2000]}
