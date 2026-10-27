"""Scores with honest uncertainty: every number comes with n and a 95% bootstrap interval."""
from __future__ import annotations

import random
from collections import Counter

from .taxonomy import CATEGORIES


def macro_f1(gold: list[str], pred: list[str], labels: list[str] | None = None) -> float:
    labels = labels or sorted(set(gold))           # classes present in gold; absent classes would be undefined
    f1s = []
    for c in labels:
        tp = sum(g == c and p == c for g, p in zip(gold, pred))
        fp = sum(g != c and p == c for g, p in zip(gold, pred))
        fn = sum(g == c and p != c for g, p in zip(gold, pred))
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    return sum(f1s) / len(f1s) if f1s else 0.0


def accuracy(gold, pred) -> float:
    return sum(g == p for g, p in zip(gold, pred)) / len(gold) if gold else 0.0


def within1(gold: list[int], pred: list[int]) -> float:
    return sum(abs(g - p) <= 1 for g, p in zip(gold, pred)) / len(gold) if gold else 0.0


def actionable_recall(gold: list[str], pred: list[str]) -> float:
    """Share of reviews that need action (not praise/spam) that the model also flags as needing action."""
    idx = [i for i, g in enumerate(gold) if g not in ("praise", "spam_or_offtopic")]
    if not idx:
        return float("nan")
    return sum(pred[i] not in ("praise", "spam_or_offtopic") for i in idx) / len(idx)


def bootstrap(fn, *cols, n: int = 2000, seed: int = 20261027) -> tuple[float, float, float]:
    """Point estimate and percentile 95% CI of fn over resampled rows."""
    rows = list(zip(*cols))
    point = fn(*[list(c) for c in cols])
    rnd = random.Random(seed)
    vals = []
    for _ in range(n):
        s = [rows[rnd.randrange(len(rows))] for _ in rows]
        vals.append(fn(*[list(c) for c in zip(*s)]))
    vals = sorted(v for v in vals if v == v)
    if not vals:
        return point, float("nan"), float("nan")
    return point, vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def confusion(gold: list[str], pred: list[str]) -> dict:
    return dict(Counter(zip(gold, pred)))


def report(gold_cat, pred_cat, gold_sev, pred_sev) -> dict:
    labels = [c for c in CATEGORIES if c in set(gold_cat)]
    out = {"n": len(gold_cat)}
    out["macro_f1"] = bootstrap(lambda g, p: macro_f1(g, p, labels), gold_cat, pred_cat)
    out["accuracy"] = bootstrap(accuracy, gold_cat, pred_cat)
    out["severity_within1"] = bootstrap(within1, gold_sev, pred_sev)
    out["actionable_recall"] = bootstrap(actionable_recall, gold_cat, pred_cat)
    return out
