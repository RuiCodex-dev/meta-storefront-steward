import ast
from pathlib import Path

from steward.privacy import scan, scrub
from tests.fixtures.pii_reviews import CONTROLS, PLANTED

HARD = ("EMAIL", "PHONE", "ORDER_ID", "IBAN", "NUMBER", "URL", "HANDLE")


def test_fixture_is_the_size_the_data_plan_promises():
    assert len(PLANTED) == 40
    assert len({p["lang"] for p in PLANTED}) == 8


def test_every_hard_identifier_is_removed():
    missed = []
    for rec in PLANTED:
        clean, _ = scrub(rec["text"], rec["author"])
        for kind, values in rec["planted"].items():
            if kind in HARD:
                missed += [(kind, v) for v in values if v in clean]
    assert missed == [], missed


def test_names_removed_at_least_95_percent():
    total = removed = 0
    for rec in PLANTED:
        clean, _ = scrub(rec["text"], rec["author"])
        for v in rec["planted"].get("NAME", []):
            total += 1
            removed += v not in clean
    assert total >= 20
    assert removed / total >= 0.95, (removed, total)


def test_controls_unchanged():
    for t in CONTROLS:
        clean, hits = scrub(t, None)
        assert clean == t and hits == [], (t, clean, hits)


def test_generic_author_is_not_treated_as_a_name():
    clean, hits = scrub("A Google user would love a dark mode", "A Google user")
    assert clean == "A Google user would love a dark mode" and hits == []


def test_outbound_scan_flags_raw_and_passes_scrubbed():
    flagged = sum(bool(scan(r["text"])) for r in PLANTED if set(r["planted"]) & set(HARD))
    hard_total = sum(1 for r in PLANTED if set(r["planted"]) & set(HARD))
    assert flagged == hard_total
    for rec in PLANTED:
        clean, _ = scrub(rec["text"], rec["author"])
        leftover = [k for k in scan(clean) if k in HARD]
        assert leftover == [], (rec["text"], clean, leftover)
    for t in CONTROLS:
        assert scan(t) == []


def test_reidmap_is_imported_only_by_the_store_writer():
    root = Path(__file__).resolve().parent.parent / "steward"
    importers = []
    for py in root.rglob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""] + [a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if any("reidmap" in n for n in names):
                importers.append(py.relative_to(root).as_posix())
    allowed = {"act/writer.py", "connectors/ingest.py"}
    assert set(importers) <= allowed, importers


def test_phone_at_sentence_end_is_removed_whole():
    # Regression: a number closing a sentence used to keep its last group ("[PHONE] 78.").
    for text in ("Ecrivez-moi au 06 12 34 56 78.", "Bel 02 123 45 67.", "call +32 471 23 45 67.",
                 "card 4111 1111 1111 1111."):
        clean, hits = scrub(text)
        assert not any(ch.isdigit() for ch in clean), (text, clean)
        assert hits
    # Controls: a decimal or a version number must not be eaten as a phone.
    assert scrub("version 2.4 crashed at level 12.")[0] == "version 2.4 crashed at level 12."
    assert scrub("costs 0.99 now")[0] == "costs 0.99 now"
