import math

import pytest

from steward import metrics, triage
from students.common import parse


def test_macro_f1_perfect_and_known_value():
    g = ["a", "a", "b", "b"]
    assert metrics.macro_f1(g, g) == 1.0
    # a: P=1/2? pred a,b,b,b -> a: tp1 fp0 fn1 => f1 .667 ; b: tp2 fp1 fn0 => f1 .8
    assert metrics.macro_f1(g, ["a", "b", "b", "b"]) == pytest.approx((2 / 3 + 0.8) / 2)


def test_bootstrap_interval_contains_point_and_is_ordered():
    g = ["praise"] * 40 + ["crash"] * 10
    p = ["praise"] * 38 + ["crash"] * 2 + ["crash"] * 8 + ["praise"] * 2
    point, lo, hi = metrics.bootstrap(metrics.accuracy, g, p, n=500)
    assert lo <= point <= hi and 0 <= lo and hi <= 1


def test_actionable_recall_ignores_praise():
    g = ["praise", "crash", "billing", "spam_or_offtopic"]
    p = ["crash", "praise", "billing", "praise"]
    assert metrics.actionable_recall(g, p) == 0.5
    assert math.isnan(metrics.actionable_recall(["praise"], ["praise"]))


def test_rule_baseline_examples():
    assert triage.rule_label("the game crashes at level 3")["category"] == "crash"
    assert triage.rule_label("please refund, I was charged twice")["category"] == "billing"
    assert triage.rule_label("çok güzel oyun")["category"] == "praise"


def test_student_parse_never_raises():
    assert parse('{"category":"crash","severity":4,"language":"en"}')["category"] == "crash"
    assert parse("garbage")["parsed"] is False
    assert parse('{"category":"nonsense"} but billing')["category"] == "billing"
