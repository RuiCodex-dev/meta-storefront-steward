"""Deterministic, local removal of personal data from review text.

Runs before any model sees a record, and again (as `scan`) on every text that leaves the machine.
Each hit is replaced by a typed placeholder so models still see that *something* was there:
[EMAIL] [URL] [PHONE] [ORDER_ID] [IBAN] [NUMBER] [HANDLE] [NAME].

Bias on purpose: a false positive costs a few characters of context; a false negative leaks a person.
"""
from __future__ import annotations

import re
import unicodedata

PLACEHOLDER = re.compile(r"\[(EMAIL|URL|PHONE|ORDER_ID|IBAN|NUMBER|HANDLE|NAME)\]")

# Order matters: the most specific patterns run first so a URL's digits are not read as a phone.
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.UNICODE)),
    ("URL", re.compile(r"(?i)\b(?:https?://|www\.)\S+")),
    ("ORDER_ID", re.compile(r"\bGPA\.\d{4}-\d{4}-\d{4}-\d{5}(?:\.\.\d+)?\b")),
    ("ORDER_ID", re.compile(r"\bM[A-Z0-9]{9}\b(?=[^a-z]|$)")),                       # Apple order id shape
    # The keyword is case-insensitive; the id itself must be upper-case/digits and contain a digit,
    # otherwise "sipariş gelmedi" would read the next ordinary word as an id.
    ("ORDER_ID", re.compile(r"(?i:\b(?:order|transaction|receipt|bestelling|commande|bestellung|sipariş|pedido|ordine)"
                            r"(?:\s*(?:id|no|nr|number|numéro|nummer|numarası|numero))?)\s*[:#]?\s*"
                            r"((?=[A-Z0-9-]*\d)[A-Z0-9][A-Z0-9-]{6,})")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,3})?\b")),
    ("PHONE", re.compile(r"(?<![\w.])(?:\+|00)\d[\d\s().\-/]{7,}\d(?![\w.])")),
    ("PHONE", re.compile(r"(?<![\w.])0\d{1,3}[\s.\-/]\d{2,4}(?:[\s.\-/]\d{2,4}){1,3}(?![\w.])")),
    ("NUMBER", re.compile(r"(?<![\w.])(?:\d[ \-]?){12,18}\d(?![\w.])")),               # card-like digit runs
    ("HANDLE", re.compile(r"(?<![\w@])@[A-Za-z0-9_.]{2,30}\b")),
]

_SELF_NAME = re.compile(
    r"(?i)\b(my name is|i am called|je m'appelle|mon nom est|ich heiße|ich heisse|mein name ist|"
    r"mijn naam is|ik heet|me llamo|mi nombre es|mi chiamo|meu nome é|benim adım|adım)\s+"
    r"([A-ZÀ-ÖØ-ÞĞİŞÇÜÖ][\w'’-]+(?:\s+[A-ZÀ-ÖØ-ÞĞİŞÇÜÖ][\w'’-]+)?)")

# Store placeholders for anonymous authors; never treated as a name to scrub.
_GENERIC_AUTHORS = {"a google user", "google user", "un utilisateur de google", "ein google-nutzer",
                    "een google-gebruiker", "bir google kullanıcısı", "usuario de google", ""}
_NAME_STOP = {"the", "and", "app", "game", "user", "love", "best", "good", "nice", "cool", "fan", "pro",
              "player", "gamer", "official", "real", "king", "queen", "boss", "big", "little", "mr", "mrs", "ms"}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s)


def _name_tokens(author: str | None) -> list[str]:
    if not author or author.strip().lower() in _GENERIC_AUTHORS:
        return []
    toks = [t for t in re.split(r"[\s_.\-]+", _norm(author)) if len(t) >= 3 and t.lower() not in _NAME_STOP]
    return toks


def scrub(text: str | None, author: str | None = None) -> tuple[str, list[str]]:
    """Return (clean_text, hit_types). `author` is the reviewer's display name, if the store gave one."""
    if not text:
        return "", []
    out = _norm(text)
    hits: list[str] = []

    def sub(label: str, pat: re.Pattern, s: str) -> str:
        def repl(m: re.Match) -> str:
            hits.append(label)
            if label == "ORDER_ID" and m.lastindex:            # keep the word "order", drop the id
                return m.group(0)[: m.start(1) - m.start(0)] + "[ORDER_ID]"
            return f"[{label}]"
        return pat.sub(repl, s)

    for label, pat in _PATTERNS:
        out = sub(label, pat, out)

    def self_name(m: re.Match) -> str:
        hits.append("NAME")
        return f"{m.group(1)} [NAME]"
    out = _SELF_NAME.sub(self_name, out)

    if author:
        full = _norm(author).strip()
        if full and full.lower() not in _GENERIC_AUTHORS and len(full) >= 3:
            pat = re.compile(r"(?i)(?<!\w)" + re.escape(full) + r"(?!\w)")
            out = sub("NAME", pat, out)
        for tok in _name_tokens(author):
            # only capitalised occurrences: "Rose" the person, not "rose" the flower
            pat = re.compile(r"(?<!\w)" + re.escape(tok[:1].upper() + tok[1:]) + r"(?!\w)")
            out = sub("NAME", pat, out)
    return out, hits


def scan(text: str | None) -> list[str]:
    """Outbound check. Returns the types of personal data still present (placeholders are ignored)."""
    if not text:
        return []
    probe = PLACEHOLDER.sub(" ", _norm(text))
    found = []
    for label, pat in _PATTERNS:
        if pat.search(probe):
            found.append(label)
    if _SELF_NAME.search(probe):
        found.append("NAME")
    return sorted(set(found))
