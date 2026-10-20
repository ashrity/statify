import math

from statify.ingest.confidence import (
    confidence_rows,
    normal_cdf,
    sample_stddev,
    touchdown_confidence,
    variance_row,
    yardage_confidence,
)

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def game(week, receiving_yards=0, receptions=None):
    return {
        "week": week,
        "receiving_yards": receiving_yards,
        "receptions": receptions if receptions is not None else receiving_yards / 10,
        "rushing_yards": 0,
        "passing_yards": 0,
    }


def projection(pid, player, week, stat_type, edge, season=2024):
    return {"id": pid, "player_id": player, "season": season, "week": week, "stat_type": stat_type, "edge": edge}


# --- sample standard deviation and its floor ------------------------------------


def test_stddev_is_none_below_the_two_game_floor():
    assert sample_stddev([]) is None
    assert sample_stddev([50.0]) is None


def test_stddev_at_the_floor_and_above():
    assert sample_stddev([10.0, 20.0]) == math.sqrt(((10 - 15) ** 2 + (20 - 15) ** 2) / 1)
    values = [10.0, 20.0, 30.0]
    mean = 20.0
    expected = math.sqrt(sum((v - mean) ** 2 for v in values) / 2)
    assert sample_stddev(values) == expected


# --- the normal CDF and yardage confidence --------------------------------------


def test_normal_cdf_at_zero_is_one_half():
    assert normal_cdf(0.0) == 0.5


def test_normal_cdf_rises_toward_one():
    assert normal_cdf(1.0) > normal_cdf(0.5) > 0.5
    assert normal_cdf(3.0) > 0.99


def test_zero_edge_reads_as_a_coin_flip():
    assert yardage_confidence(0.0, 10.0) == 0.5


def test_confidence_rises_as_edge_grows_relative_to_stddev():
    low = yardage_confidence(5.0, 20.0)
    high = yardage_confidence(40.0, 20.0)
    assert 0.5 < low < high < 1.0


def test_confidence_is_none_without_an_edge_or_a_stddev():
    assert yardage_confidence(None, 10.0) is None
    assert yardage_confidence(5.0, None) is None
    assert yardage_confidence(5.0, 0.0) is None


# --- touchdown confidence --------------------------------------------------------


def test_touchdown_confidence_reads_distance_from_a_coin_flip_either_side():
    assert touchdown_confidence(0.1) == 0.9
    assert touchdown_confidence(0.9) == 0.9
    assert touchdown_confidence(0.5) == 0.5


def test_touchdown_confidence_is_none_without_a_probability():
    assert touchdown_confidence(None) is None


# --- variance_row is driven by the projection's week, not play history ---------


def test_variance_row_reaches_an_unplayed_week():
    """The week that matters most is one the player hasn't played yet."""
    history = [game(1, receiving_yards=10), game(2, receiving_yards=20), game(3, receiving_yards=30)]
    row = variance_row("WR1", 2024, 4, "receiving_yards", history, UPDATED_AT)
    assert row["games_measured"] == 3
    assert row["own_stddev"] is not None


def test_variance_row_excludes_its_own_week():
    history = [game(1, receiving_yards=10), game(2, receiving_yards=99999)]
    row = variance_row("WR1", 2024, 2, "receiving_yards", history, UPDATED_AT)
    assert row["games_measured"] == 1
    assert row["own_stddev"] is None  # only 1 prior game, below the floor


# --- the full assembly: confidence_rows -----------------------------------------


def test_confidence_rows_computes_variance_only_once_per_key():
    histories = {"WR1": [game(1, 10), game(2, 20), game(3, 30)]}
    rows = [
        projection(1, "WR1", 4, "receiving_yards", edge=5.0),
        projection(2, "WR1", 4, "receptions", edge=1.0),
    ]
    variance, updates = confidence_rows(rows, histories, {}, updated_at=UPDATED_AT)
    assert len(variance) == 2  # one per stat_type, not per projection row
    assert len(updates) == 2


def test_touchdowns_never_gets_a_variance_row():
    rows = [projection(1, "WR1", 4, "touchdowns", edge=-0.2)]
    variance, updates = confidence_rows(rows, {}, {("WR1", 4): 0.3}, updated_at=UPDATED_AT)
    assert variance == []
    assert updates == [{"id": 1, "confidence": 0.7}]


def test_a_row_with_no_resolvable_confidence_produces_no_update():
    rows = [projection(1, "WR1", 2, "receiving_yards", edge=5.0)]
    histories = {"WR1": [game(1, 10)]}  # only 1 prior game: stddev is None
    variance, updates = confidence_rows(rows, histories, {}, updated_at=UPDATED_AT)
    assert updates == []
