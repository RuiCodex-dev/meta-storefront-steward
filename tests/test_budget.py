import pytest

from steward import budget, db


def test_price_table_matches_published_prices():
    u = budget.Usage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert budget.cost("meta", "muse-spark-1.3", u) == pytest.approx(1.25 + 4.25)
    cached = budget.Usage(input_tokens=1_000_000, cached_tokens=1_000_000)
    assert budget.cost("meta", "muse-spark-1.3", cached) == pytest.approx(0.15)
    assert budget.cost("meta", "muse-image-1.0", budget.Usage(images=100)) == pytest.approx(1.0)
    assert budget.cost("meta", "sam-3.1", budget.Usage(images=1000, frames=1000)) == pytest.approx(2.70)


def test_contributor_mode_refused(tmp_path):
    con = db.connect(tmp_path / "b.db")
    with pytest.raises(ValueError):
        budget.reserve(con, "meta", "muse-spark-1.3-contributor", budget.Usage(input_tokens=10))


def test_unknown_model_refused(tmp_path):
    con = db.connect(tmp_path / "b.db")
    with pytest.raises(ValueError):
        budget.reserve(con, "meta", "some-new-model", budget.Usage(input_tokens=10))


def test_cap_blocks_before_sending(tmp_path):
    con = db.connect(tmp_path / "b.db")
    budget.record(con, "meta", "muse-spark-1.3", "t", budget.Usage(output_tokens=32_900_000), 1, "x")  # ~139.83
    assert budget.spent(con, "meta") == pytest.approx(139.825)
    budget.reserve(con, "meta", "muse-spark-1.3", budget.Usage(output_tokens=10_000))           # +0.0425 ok
    with pytest.raises(budget.BudgetExceeded):
        budget.reserve(con, "meta", "muse-spark-1.3", budget.Usage(output_tokens=100_000))      # +0.425 too much


def test_caps_are_the_owner_numbers():
    assert budget.CAPS_USD["meta"] == 140.0 and budget.CAPS_USD["baseten"] == 90.0


def test_in_flight_calls_count_against_the_cap(tmp_path):
    con = db.connect(tmp_path / "b.db")
    big = budget.Usage(output_tokens=20_000_000)          # 85 USD worst case each
    w = budget.reserve(con, "meta", "muse-spark-1.3", big)
    with pytest.raises(budget.BudgetExceeded):             # a second parallel call would cross 140
        budget.reserve(con, "meta", "muse-spark-1.3", big)
    budget.release("meta", w)
    budget.release("meta", budget.reserve(con, "meta", "muse-spark-1.3", big))
