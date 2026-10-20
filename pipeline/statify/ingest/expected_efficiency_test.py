from statify.ingest.expected_efficiency import (
    CATCH_RATE_OWN_WEIGHT,
    YARDS_PER_TARGET_OWN_WEIGHT,
    efficiency_row,
    expected_efficiency_rows,
    position_rate_for,
    position_week_totals,
)
from statify.ingest.volume import blend

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def played(player, week, targets=5, receiving_yards=50, receptions=3, carries=0, rushing_yards=0, attempts=0, passing_yards=0):
    return {
        "player_id": player,
        "week": week,
        "targets": targets,
        "receiving_yards": receiving_yards,
        "receptions": receptions,
        "carries": carries,
        "rushing_yards": rushing_yards,
        "attempts": attempts,
        "passing_yards": passing_yards,
    }


def driver(player, week, team="BUF"):
    return {"player_id": player, "season": 2024, "week": week, "team_abbr": team}


# --- own and position rate arithmetic -----------------------------------------


def test_own_rate_is_the_ratio_over_prior_games():
    history = [played("WR1", 1, targets=4, receiving_yards=40), played("WR1", 2, targets=6, receiving_yards=90)]
    row = efficiency_row("WR1", 2024, 3, "BUF", "WR", history, {}, UPDATED_AT)
    assert row["own_yards_per_target"] == 130 / 10


def test_a_position_with_no_prior_week_is_none():
    row = efficiency_row("WR1", 2024, 1, "BUF", "WR", [], {}, UPDATED_AT)
    assert row["position_yards_per_target"] is None
    assert row["exp_yards_per_target"] == row["own_yards_per_target"]  # both None, blend falls back cleanly


def test_a_never_present_denominator_is_none_not_zero():
    """A QB's yards per carry, with zero carries in every prior game."""
    history = [played("QB1", 1, carries=0, rushing_yards=0), played("QB1", 2, carries=0, rushing_yards=0)]
    row = efficiency_row("QB1", 2024, 3, "BUF", "QB", history, {}, UPDATED_AT)
    assert row["own_yards_per_carry"] is None
    assert row["rushing_opportunities"] == 0


def test_opportunity_count_is_games_with_a_real_denominator_not_games_played():
    history = [
        played("RB1", 1, carries=10, rushing_yards=40, targets=0, receiving_yards=0),
        played("RB1", 2, carries=0, rushing_yards=0, targets=3, receiving_yards=20),
    ]
    row = efficiency_row("RB1", 2024, 3, "BUF", "RB", history, {}, UPDATED_AT)
    assert row["rushing_opportunities"] == 1
    assert row["receiving_opportunities"] == 1


def test_position_rate_pools_every_player_at_that_position_strictly_prior():
    rows = [
        played("WR1", 1, targets=10, receiving_yards=100),
        played("WR2", 1, targets=10, receiving_yards=50),
        played("WR1", 2, targets=999, receiving_yards=999),  # must not leak into week 2's position rate
    ]
    totals = position_week_totals([{**r, "position": "WR"} for r in rows])
    assert position_rate_for("WR", 2, totals, "receiving_yards", "targets") == 150 / 20


def test_position_rate_does_not_mix_positions():
    rows = [played("WR1", 1, targets=10, receiving_yards=100), played("RB1", 1, carries=10, rushing_yards=500)]
    totals = position_week_totals(
        [{**rows[0], "position": "WR"}, {**rows[1], "position": "RB"}]
    )
    assert position_rate_for("WR", 2, totals, "receiving_yards", "targets") == 10.0
    assert position_rate_for("RB", 2, totals, "rushing_yards", "carries") == 50.0


# --- the blend ------------------------------------------------------------------


def test_the_blend_is_reproducible_from_the_row_alone():
    history = [played("WR1", 1, targets=4, receiving_yards=40)]
    totals = position_week_totals([{**played("WR2", 1, targets=10, receiving_yards=50), "position": "WR"}])
    row = efficiency_row("WR1", 2024, 2, "BUF", "WR", history, totals, UPDATED_AT)
    expected = blend(row["own_yards_per_target"], row["position_yards_per_target"], YARDS_PER_TARGET_OWN_WEIGHT)
    assert row["exp_yards_per_target"] == expected


def test_each_rate_carries_its_own_weight():
    row = efficiency_row("WR1", 2024, 2, "BUF", "WR", [played("WR1", 1)], {}, UPDATED_AT)
    assert row["yards_per_target_own_weight"] == YARDS_PER_TARGET_OWN_WEIGHT
    assert row["catch_rate_own_weight"] == CATCH_RATE_OWN_WEIGHT


# --- the strictly-prior boundary ------------------------------------------------


def test_a_weeks_own_result_is_absent_from_its_own_expectation():
    history = [played("WR1", 1, targets=4, receiving_yards=40), played("WR1", 2, targets=100, receiving_yards=10000)]
    row = efficiency_row("WR1", 2024, 2, "BUF", "WR", history, {}, UPDATED_AT)
    assert row["own_yards_per_target"] == 10.0


# --- rows follow player_opportunity_weekly's row set ----------------------------


def test_rows_follow_the_driver_set_one_to_one():
    drivers = [driver("WR1", 2), driver("WR2", 2)]
    player_rows = [played("WR1", 1), played("WR2", 1)]
    positions = {"WR1": "WR", "WR2": "WR"}
    rows = expected_efficiency_rows(drivers, player_rows, positions, 2024, updated_at=UPDATED_AT)
    assert {row["player_id"] for row in rows} == {"WR1", "WR2"}


def test_a_driver_row_with_no_known_position_is_skipped():
    drivers = [driver("GHOST", 2)]
    rows = expected_efficiency_rows(drivers, [], {}, 2024, updated_at=UPDATED_AT)
    assert rows == []
