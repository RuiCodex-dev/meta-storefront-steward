"""The triage label set, shared by the teacher prompt, the students, the gold labels and the metrics."""
from __future__ import annotations

CATEGORIES = [
    "bug",              # something works wrongly but the app keeps running
    "crash",            # app closes, freezes, will not start, ANR
    "performance",      # slow, laggy, battery, heat, size
    "feature_request",  # asks for something new or different
    "billing",          # purchases, subscriptions, refunds, prices
    "ads",              # advertising volume, placement, ad-related breakage
    "ux_confusion",     # cannot find or understand how to do something
    "praise",           # positive with no actionable problem
    "spam_or_offtopic", # unrelated, gibberish, wrong app, promotion
]

SEVERITY = {
    1: "no action needed (praise, off-topic)",
    2: "minor: cosmetic, one-off, a wish",
    3: "major: a core feature fails or blocks progress for this user",
    4: "critical: crash/data loss/charged-without-delivery, or many users affected",
}

TRIAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category", "severity", "language", "gloss_en"],
    "properties": {
        "category": {"type": "string", "enum": CATEGORIES},
        "severity": {"type": "integer", "minimum": 1, "maximum": 4},
        "language": {"type": "string", "description": "ISO 639-1 code of the review text"},
        "gloss_en": {"type": "string", "description": "one neutral English sentence, no names, no quotes"},
    },
}

GUIDE = """You triage app-store reviews for a small studio. Return exactly one category and one severity.

Categories:
- bug: something works wrongly but the app keeps running (wrong score, button does nothing, progress not saved).
- crash: the app closes, freezes, will not start, black screen, ANR.
- performance: slow, laggy, stutters, drains battery, overheats, too large.
- feature_request: asks for something new or different (new levels, dark mode, a language, an option).
- billing: purchases, subscriptions, refunds, prices, "paid but did not receive".
- ads: too many/too long ads, ads that cannot be closed, ads that break the game.
- ux_confusion: the user cannot find or understand how to do something that exists.
- praise: positive with no actionable problem.
- spam_or_offtopic: unrelated, gibberish, wrong app, promotion.

Tie-breaks (apply in order):
1. A crash or freeze wins over everything else ("love it but it crashes" = crash).
2. Money wins next: any charge/refund/purchase problem = billing, even if it is also a bug.
3. Ads complaint + crash caused by an ad = crash; ads complaint alone = ads.
4. Praise with a wish ("great, please add more levels") = feature_request, severity 2.
5. A rating alone does not decide the category; read the text.

Severity: 1 no action needed (praise, off-topic); 2 minor (cosmetic, one-off, a wish); 3 major (a core feature
fails or progress is blocked for this user); 4 critical (crash, data loss, charged without delivery).

gloss_en: one neutral English sentence describing the feedback. Never repeat names, e-mails, ids or quotes.
Placeholders like [NAME] or [EMAIL] mean personal data was removed; ignore them.
"""
