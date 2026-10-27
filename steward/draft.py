"""Reply drafts that cannot overclaim: Spark writes, a deterministic verifier decides what reaches the queue.

The verifier rejects a draft that
  * is longer than the store allows (Play 350 characters),
  * is not in the reviewer's language,
  * promises a date, a refund or compensation (only a human may promise those),
  * contains personal data or a leftover placeholder,
  * cites something that does not exist.
Rejected drafts are kept with the reasons, so the queue shows what the model tried and why it was stopped.
"""
from __future__ import annotations

import datetime as dt
import json
import re

from . import db, llm
from .privacy import scan

LIMITS = {"play": 350, "appstore": 5970}

REPLY_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["reply_text", "language", "cites", "promises"],
    "properties": {
        "reply_text": {"type": "string"},
        "language": {"type": "string"},
        "cites": {"type": "array", "items": {"type": "string"}},
        "promises": {"type": "array", "items": {"type": "string"}},
    },
}

SYSTEM = """You draft public replies to app-store reviews for a small studio. The developer approves every reply
before it is posted. Write in the reviewer's language, warm and specific, never generic.
Hard rules:
- At most {limit} characters.
- Never promise a date, a refund, compensation, or a feature; say what is being looked at instead.
- Reply in this language: {reply_lang}.
- Refer ONLY to what this reviewer wrote. The issue cluster tells you what the team is looking at; never repeat
  details other reviewers mentioned as if this reviewer had said them.
- Never invent facts. Use only the review, the issue cluster and the release notes given.
- Never include names, e-mails, links or placeholders like [NAME].
- cites: the ids you relied on (review id, cluster id, release name). promises: list any commitment you made
  (should be empty).
Match the tone of the developer's own earlier replies:
{style}
Return JSON only."""

_PROMISE = re.compile(
    r"(?i)\b(tomorrow|next week|next month|within \d+|in \d+ days|by (monday|tuesday|wednesday|thursday|friday|"
    r"january|february|march|april|may|june|july|august|september|october|november|december)|"
    r"refund|money back|compensat|we will add|will be added|yarın|haftaya|iade|rembours|dédommag|demain|"
    r"erstatt|morgen|nächste woche|terugbetal|volgende week|reembols|mañana|rimbors|domani|reembolso|amanhã|"
    r"возврат|завтра|"
    # "try the latest version" implies a fix already shipped, which only a release note may claim
    r"(try|give) the (latest|newest|new) (version|update)|neueste[nr]? version|son sürüm|dernière version|"
    r"laatste versie|última versión|ultima versione|última versão)")

_STOP = {
    "en": {"the", "and", "you", "for", "thank", "thanks", "we", "is", "to", "your"},
    "tr": {"ve", "bir", "için", "teşekkür", "bu", "çok", "ederiz", "sizin", "oyun", "değerli"},
    "de": {"und", "der", "die", "das", "danke", "wir", "ist", "für", "nicht", "ihr"},
    "fr": {"et", "le", "la", "les", "merci", "nous", "pour", "est", "vous", "votre"},
    "nl": {"en", "de", "het", "een", "bedankt", "we", "voor", "is", "jouw", "uw"},
    "es": {"y", "el", "la", "los", "gracias", "para", "es", "tu", "nosotros", "que"},
    "it": {"e", "il", "la", "grazie", "per", "che", "è", "tuo", "siamo", "non"},
    "pt": {"e", "o", "a", "obrigado", "obrigada", "para", "é", "seu", "você", "que"},
}


def guess_language(text: str) -> str:
    if re.search(r"[Ѐ-ӿ]", text):
        return "ru"
    if re.search(r"[一-鿿]", text):
        return "zh"
    words = set(re.findall(r"[a-zà-ÿğışçöü]+", text.lower()))
    scores = {lang: len(words & sw) for lang, sw in _STOP.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "und"


def verify(draft: dict, *, store: str, review_lang: str | None, known_ids: set[str]) -> list[str]:
    problems = []
    text = draft["reply_text"]
    if len(text) > LIMITS.get(store, 350):
        problems.append(f"too long: {len(text)} > {LIMITS.get(store, 350)} characters")
    if re.search(r"\[(NAME|EMAIL|URL|PHONE|ORDER_ID|IBAN|NUMBER|HANDLE)\]", text):
        problems.append("contains a personal-data placeholder")
    pii = scan(text)
    if pii:
        problems.append(f"personal data pattern(s): {pii}")
    if _PROMISE.search(text) or draft.get("promises"):
        problems.append("promises a date, refund, compensation or feature")
    want = (review_lang or "").split("-")[0].lower()
    if want and want not in ("und", "zh-hans") and want in _STOP:
        got = guess_language(text)
        if got != "und" and got != want:
            problems.append(f"language mismatch: review {want}, reply looks {got}")
    bad = [c for c in draft.get("cites", []) if c not in known_ids]
    if bad:
        problems.append(f"cites unknown ids: {bad}")
    return problems


def _style_examples(con, package: str, k: int = 4) -> str:
    rows = con.execute("SELECT dev_reply FROM items WHERE synthetic=0 AND dev_reply IS NOT NULL AND package=? "
                       "LIMIT ?", (package, k)).fetchall()
    if len(rows) < k:
        rows += con.execute("SELECT dev_reply FROM items WHERE synthetic=0 AND dev_reply IS NOT NULL LIMIT ?",
                            (k - len(rows),)).fetchall()
    return "\n".join(f'- "{r[0][:300]}"' for r in rows) or "- (no earlier replies)"


def draft_reply(item_id: str, cluster: dict | None = None, con=None, provider: str = "meta",
                model: str = "muse-spark-1.3") -> dict:
    con = con or db.connect()
    it = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    store = it["store"] if it["store"] in LIMITS else "play"
    limit = LIMITS[store]
    rel = con.execute("SELECT name, notes FROM releases WHERE package=? AND track='production' LIMIT 2",
                      (it["package"],)).fetchall()
    rel_txt = "; ".join(f"{r['name']}: {(json.loads(r['notes'] or '{}').get('en-US') or '')[:200]}" for r in rel)
    known = {item_id} | ({cluster["id"]} if cluster else set()) | {r["name"] for r in rel}
    # Store metadata is the reviewer's device language, not the language of the text; prefer the triaged one.
    lab = con.execute("SELECT language FROM labels WHERE item_id=? ORDER BY CASE source WHEN 'triage_live' THEN 0 "
                      "WHEN 'gold_claude' THEN 1 ELSE 2 END LIMIT 1", (item_id,)).fetchone()
    reply_lang = (lab[0] if lab and lab[0] and lab[0] != "und" else None) or it["lang"] or "the review's language"
    user = (f"[REVIEW id={item_id} rating={it['rating']} lang={it['lang']} version={it['version_name']}]\n"
            f"{(it['title'] + ' / ') if it['title'] else ''}{it['text']}\n\n"
            + (f"[CLUSTER id={cluster['id']}] {cluster['title']}: {cluster['summary']} "
               f"Planned action: {cluster.get('suggested_action', '')}\n\n" if cluster else "")
            + f"[RELEASES] {rel_txt or 'none'}")
    res = llm.chat(provider, model, [{"role": "system", "content": SYSTEM.format(limit=limit, reply_lang=reply_lang,
                                                                                   style=_style_examples(con, it['package']))},
                                     {"role": "user", "content": user}],
                   purpose="draft-reply", max_tokens=3000, schema=REPLY_SCHEMA, schema_name="reply",
                   temperature=0.3, reasoning_effort="low" if provider == "meta" else None, con=con)
    d = res.data
    problems = verify(d, store=store, review_lang=reply_lang, known_ids=known)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    cur = con.execute("INSERT INTO drafts(item_id,cluster_id,kind,lang,text,cites,verifier,status,created_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (item_id, cluster["id"] if cluster else None, "reply", d["language"], d["reply_text"],
                       json.dumps(d["cites"]), json.dumps(problems), "pending" if not problems else "rejected_by_verifier",
                       now))
    con.commit()
    return {"draft_id": cur.lastrowid, **d, "problems": problems, "cost_usd": res.cost_usd}
