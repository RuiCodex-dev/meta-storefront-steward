"""Triage labellers: the Spark teacher, zero-shot baselines, and a keyword-rule floor.

`label_items` sends items in batches of `batch` with a fixed system prompt, so the long label guide and
the worked examples form a stable prefix the API can cache between calls.
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import llm, taxonomy

FEWSHOT = [  # synthetic, written for this guide; cover every tie-break
    ("Love this game but since the update it closes when I open the shop", "crash", 4, "en"),
    ("Paid 4,99 for no ads and the ads are still there!!", "billing", 3, "en"),
    ("trop de pubs, une toutes les 30 secondes", "ads", 3, "fr"),
    ("Super leuk spel, graag meer levels!", "feature_request", 2, "nl"),
    ("Wo stelle ich die Sprache um? Finde es nirgends", "ux_confusion", 2, "de"),
    ("Oyun çok kasıyor, telefon ısınıyor", "performance", 3, "tr"),
    ("el botón de recompensa no da las monedas", "bug", 3, "es"),
    ("Bellissimo, consigliato a tutti", "praise", 1, "it"),
    ("follow my channel for free gems", "spam_or_offtopic", 1, "en"),
    ("great app but the ad after every level freezes the screen", "crash", 4, "en"),
    ("ich habe gekauft aber nichts bekommen und die werbung nervt", "billing", 4, "de"),
    ("ok", "praise", 1, "en"),
]

BATCH_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["labels"],
    "properties": {"labels": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "category", "severity", "language", "gloss_en"],
        "properties": {"id": {"type": "string"}, **taxonomy.TRIAGE_SCHEMA["properties"]}}}},
}


def system_prompt(mode: str) -> str:
    if mode == "zeroshot":
        return ("Classify each app-store review into exactly one category: " + ", ".join(taxonomy.CATEGORIES)
                + ". Severity 1 (no action) to 4 (critical). Give the ISO 639-1 language code and a one-sentence "
                "neutral English gloss. Return JSON only.")
    shots = "\n".join(f'- "{t}" -> {c}, severity {s}, language {l}' for t, c, s, l in FEWSHOT)
    return taxonomy.GUIDE + "\nWorked examples:\n" + shots + "\nReturn JSON only, one label per input id."


def _user(items: list[dict]) -> str:
    return json.dumps([{"id": it["id"], "text": it["text"]} for it in items], ensure_ascii=False)


def label_batch(provider: str, model: str, items: list[dict], mode: str, purpose: str) -> dict[str, dict]:
    res = llm.chat(provider, model,
                   [{"role": "system", "content": system_prompt(mode)}, {"role": "user", "content": _user(items)}],
                   purpose=purpose, max_tokens=4000 + 160 * len(items), schema=BATCH_SCHEMA, schema_name="labels",
                   temperature=0.0, reasoning_effort="low" if provider == "meta" else None)
    want = {it["id"] for it in items}
    out = {}
    for lab in res.data["labels"]:
        if lab["id"] in want and lab["category"] in taxonomy.CATEGORIES:
            out[lab["id"]] = lab
    return out


def label_items(provider: str, model: str, items: list[dict], mode: str = "guided", batch: int = 20,
                workers: int = 6, purpose: str = "label") -> dict[str, dict]:
    chunks = [items[i:i + batch] for i in range(0, len(items), batch)]
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(label_batch, provider, model, ch, mode, purpose) for ch in chunks]
        for f in as_completed(futs):
            try:
                out.update(f.result())
            except llm.budget.BudgetExceeded:
                raise
            except Exception as e:  # noqa: BLE001
                print("label batch failed:", type(e).__name__, str(e)[:160])
    # one retry, item by item batches of 5, for anything a batch dropped
    missing = [it for it in items if it["id"] not in out]
    for i in range(0, len(missing), 5):
        try:
            out.update(label_batch(provider, model, missing[i:i + 5], mode, purpose + "-retry"))
        except llm.budget.BudgetExceeded:
            raise
        except Exception as e:  # noqa: BLE001
            print("retry failed:", str(e)[:120])
    return out


# ------------------------------------------------------------------ keyword-rule floor
_RULES = [
    ("crash", r"crash|closes|close itself|freez|won'?t (open|start)|black screen|kapan|donuyor|açılmıyor|plante|"
              r"se ferme|stürzt|absturz|crasht|sluit af|se cierra|si chiude|fecha sozinho|trava|вылета|закрыва|zamyka|wywala"),
    ("billing", r"refund|charged|paid|purchase|subscription|money|price|iade|para|ücret|rembours|payé|abonnement|"
                r"erstatt|bezahlt|gekauft|terugbetal|betaald|reembolso|pagu|cobr|rimborso|pagato|деньг|подписк|zwrot|kasę|zapłac"),
    ("ads", r"\bads?\b|advert|reklam|pub(s|licité)?\b|werbung|reclame|anuncio|pubblicit|anúncio|реклам"),
    ("performance", r"lag|slow|battery|heat|stutter|kasıyor|şarj|yavaş|lent|akku|langzaam|lento|тормоз|батаре|wolno"),
    ("feature_request", r"please add|add more|would be nice|wish|ekle|ajout|bitte|graag|añad|aggiung|adicion|добав|dodaj"),
    ("ux_confusion", r"how do i|can'?t find|where is|nasıl|où|wie kann|waar|dónde|dove|onde|как |gdzie"),
    ("bug", r"bug|doesn'?t work|not working|broken|hata|çalışmıyor|ne marche|funktioniert nicht|werkt niet|no funciona|"
            r"non funziona|não funciona|не работает|nie działa"),
]


def rule_label(text: str) -> dict:
    t = text.lower()
    for cat, pat in _RULES:
        if re.search(pat, t):
            sev = 4 if cat == "crash" else 3 if cat in ("billing", "bug") else 2
            return {"category": cat, "severity": sev}
    return {"category": "praise", "severity": 1}
