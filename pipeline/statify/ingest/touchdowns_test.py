import math

from statify.ingest.touchdowns import (
    RECEIVING_TD_RATE_OWN_WEIGHT,
    RUSHING_TD_RATE_OWN_WEIGHT,
    anytime_probability,
    position_rate_for,
    position_week_totals,
    touchdown_row,
    touchdown_rows,
)
from statify.ingest.volume import blend

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def played(player, week, carries=0, rushing_tds=0, targets=0, receiving_tds=0):
    return {
        "player_id": player,
        "week": week,
        "carries": carries,
        "rushing_tds": rushing_tds,
        "targets": targets,
        "receiving_tds": receiving_tds,
    }


def driver(player, week, team="BUF", exp_targets=5.0, exp_carries=0.0):
    return {
        "player_id": player,
        "season": 2024,
        "week": week,
        "team_abbr": team,
        "exp_targets": exp_targets,
        "exp_carries": exp_carries,
    }


# --- own and position rate arithmetic -------------------------------------------


def test_own_rate_is_tds_over_the_denominator_across_prior_games():
    history = [played("WR1", 1, targets=10, receiving_tds=1), played("WR1", 2, targets=10, receiving_tds=1)]
    row = touchdown_row("WR1", 2024, 3, "BUF", "WR", 10.0, 0.0, history, {}, UPDATED_AT)
    assert row["own_receiving_td_rate"] == 2 / 20


def test_a_position_with_no_prior_week_is_none():
    row = touchdown_row("WR1", 2024, 1, "BUF", "WR", 10.0, 0.0, [], {}, UPDATED_AT)
    assert row["position_receiving_td_rate"] is None


def test_a_never_present_denominator_is_none_not_zero():
    """A WR who has never carried the ball."""
    history = [played("WR1", 1, carries=0, rushing_tds=0), played("WR1", 2, carries=0, rushing_tds=0)]
    row = touchdown_row("WR1", 2024, 3, "BUF", "WR", 10.0, 0.0, history, {}, UPDATED_AT)
    assert row["own_rushing_td_rate"] is None
    assert row["rushing_opportunities"] == 0


def test_opportunity_count_is_games_with_a_real_denominator():
    history = [played("RB1", 1, carries=10, targets=0), played("RB1", 2, carries=0, targets=3)]
    row = touchdown_row("RB1", 2024, 3, "BUF", "RB", 3.0, 10.0, history, {}, UPDATED_AT)
    assert row["rushing_opportunities"] == 1
    assert row["receiving_opportunities"] == 1


def test_position_rate_pools_the_position_strictly_prior():
    rows = [
        played("WR1", 1, targets=10, receiving_tds=1),
        played("WR2", 1, targets=10, receiving_tds=1),
        played("WR1", 2, targets=10, receiving_tds=999),  # must not leak into week 2's position rate
    ]
    totals = position_week_totals([{**r, "position": "WR"} for r in rows])
    assert position_rate_for("WR", 2, totals, "receiving_tds", "targets") == 2 / 20


# --- the blend and the combined count -------------------------------------------


def test_the_rate_blend_is_reproducible_from_the_row_alone():
    history = [played("WR1", 1, targets=10, receiving_tds=2)]
    totals = position_week_totals([{**played("WR2", 1, targets=10, receiving_tds=1), "position": "WR"}])
    row = touchdown_row("WR1", 2024, 2, "BUF", "WR", 8.0, 0.0, history, totals, UPDATED_AT)
    expected = blend(row["own_receiving_td_rate"], row["position_receiving_td_rate"], RECEIVING_TD_RATE_OWN_WEIGHT)
    assert row["exp_receiving_td_rate"] == expected
    assert row["exp_receiving_tds"] == 8.0 * expected


def test_exp_touchdowns_is_the_sum_of_both_phases():
    history = [
        played("RB1", 1, carries=10, rushing_tds=1, targets=5, receiving_tds=1),
        played("RB1", 2, carries=10, rushing_tds=1, targets=5, receiving_tds=1),
    ]
    row = touchdown_row("RB1", 2024, 3, "BUF", "RB", 5.0, 10.0, history, {}, UPDATED_AT)
    assert row["exp_touchdowns"] == row["exp_rushing_tds"] + row["exp_receiving_tds"]


def test_exp_touchdowns_is_none_when_either_phase_is_unknown():
    """exp_carries unknown (None, as in week 1) must not be read as a zero rushing phase."""
    history = [played("RB1", 1, carries=10, rushing_tds=1, targets=5, receiving_tds=1)]
    row = touchdown_row("RB1", 2024, 2, "BUF", "RB", 5.0, None, history, {}, UPDATED_AT)
    assert row["exp_rushing_tds"] is None
    assert row["exp_touchdowns"] is None
    assert row["anytime_td_prob"] is None


def test_each_rate_carries_its_own_weight():
    row = touchdown_row("RB1", 2024, 2, "BUF", "RB", 5.0, 10.0, [played("RB1", 1)], {}, UPDATED_AT)
    assert row["rushing_td_rate_own_weight"] == RUSHING_TD_RATE_OWN_WEIGHT
    assert row["receiving_td_rate_own_weight"] == RECEIVING_TD_RATE_OWN_WEIGHT


# --- the Poisson conversion ------------------------------------------------------


def test_zero_expected_touchdowns_is_zero_probability():
    assert anytime_probability(0.0) == 0.0


def test_a_large_expected_count_approaches_but_never_reaches_one():
    prob = anytime_probability(10.0)
    assert 0.99 < prob < 1.0


def test_the_probability_matches_the_textbook_formula():
    assert anytime_probability(0.5) == 1 - math.exp(-0.5)


def test_unknown_expected_touchdowns_is_an_unknown_probability():
    assert anytime_probability(None) is None


# --- the strictly-prior boundary -------------------------------------------------


def test_a_weeks_own_result_is_absent_from_its_own_expectation():
    history = [played("WR1", 1, targets=10, receiving_tds=1), played("WR1", 2, targets=10, receiving_tds=999)]
    row = touchdown_row("WR1", 2024, 2, "BUF", "WR", 10.0, 0.0, history, {}, UPDATED_AT)
    assert row["own_receiving_td_rate"] == 1 / 10


# --- rows follow the driver set --------------------------------------------------


def test_rows_follow_the_driver_set_one_to_one():
    drivers = [driver("WR1", 2), driver("WR2", 2)]
    player_rows = [played("WR1", 1), played("WR2", 1)]
    positions = {"WR1": "WR", "WR2": "WR"}
    rows = touchdown_rows(drivers, player_rows, positions, 2024, updated_at=UPDATED_AT)
    assert {row["player_id"] for row in rows} == {"WR1", "WR2"}


def test_a_driver_row_with_no_known_position_is_skipped():
    rows = touchdown_rows([driver("GHOST", 2)], [], {}, 2024, updated_at=UPDATED_AT)
    assert rows == []
