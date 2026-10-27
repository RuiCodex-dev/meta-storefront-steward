"""Shared prompt format for the distilled students (kept tiny so a 3B model and a 30B model see the same task)."""
import json
import re

CATEGORIES = ["bug", "crash", "performance", "feature_request", "billing", "ads", "ux_confusion", "praise",
              "spam_or_offtopic"]

SYSTEM = ("Triage one app-store review. Reply with compact JSON: "
          '{"category": one of ' + "|".join(CATEGORIES) + ', "severity": 1-4, "language": ISO 639-1}. '
          "Crash or freeze wins over everything; money problems are billing; praise with a wish is feature_request.")


def messages(text: str) -> list[dict]:
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]


def target(category: str, severity: int, language: str) -> str:
    return json.dumps({"category": category, "severity": int(severity), "language": language},
                      ensure_ascii=False, separators=(",", ":"))


def parse(out: str) -> dict:
    """Parse a student reply. Never raises: an unparseable reply becomes an explicit 'unparsed' label."""
    m = re.search(r"\{.*?\}", out, re.S)
    if m:
        try:
            d = json.loads(m.group(0))
            cat = d.get("category")
            if cat in CATEGORIES:
                sev = int(d.get("severity", 2))
                return {"category": cat, "severity": min(4, max(1, sev)), "language": str(d.get("language", ""))[:5],
                        "parsed": True}
        except (ValueError, TypeError):
            pass
    for c in CATEGORIES:                      # last resort: first category word in the text
        if c in out:
            return {"category": c, "severity": 2, "language": "", "parsed": False}
    return {"category": "praise", "severity": 1, "language": "", "parsed": False}
