from statify.ingest.volume import (
    PASS_OWN_WEIGHT,
    RUSH_OWN_WEIGHT,
    blend,
    cross_season_weight,
    league_rates,
    own_rates,
    prior_season_rates,
    scheduled,
    team_week_totals,
    volume_row,
    volume_rows,
)

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def played(team, week, targets=30, carries=25, attempts=32):
    return {
        "team_abbr": team,
        "week": week,
        "targets": targets,
        "carries": carries,
        "attempts": attempts,
    }


def game(week, home, away):
    return {"week": week, "home_team": home, "away_team": away}


def row_for(week, history, totals=None):
    source = history if totals is None else totals
    return volume_row("BUF", 2024, week, history, team_week_totals(source), UPDATED_AT)


# --- the boundary -----------------------------------------------------------


def test_a_weeks_own_result_is_absent_from_its_own_expectation():
    """Leakage here has no downstream symptom, so it is asserted directly."""
    history = [played("BUF", 1, targets=20), played("BUF", 2, targets=99)]
    row = row_for(2, history)
    assert row["own_targets_pg"] == 20.0
    assert row["games_played"] == 1


def test_the_league_rate_excludes_the_week_it_is_built_for():
    """The subtler half: a prior own window against a league rate that leaked."""
    totals = [played("BUF", 1, carries=10), played("MIA", 1, carries=20), played("NYJ", 2, carries=900)]
    row = row_for(2, [played("BUF", 1, carries=10)], totals)
    assert row["league_carries_pg"] == 15.0


# --- the blend --------------------------------------------------------------


def test_the_blend_is_reproducible_from_the_row_alone():
    row = row_for(3, [played("BUF", 1, targets=40), played("BUF", 2, targets=40)])
    expected = (
        row["pass_own_weight"] * row["own_targets_pg"]
        + (1 - row["pass_own_weight"]) * row["league_targets_pg"]
    )
    assert row["exp_targets"] == expected


def test_pass_and_rush_lean_opposite_ways():
    """The measured asymmetry, pinned so a retune cannot silently invert it."""
    assert PASS_OWN_WEIGHT < 0.5 < RUSH_OWN_WEIGHT


def test_each_quantity_uses_the_weight_for_its_play_type():
    history = [played("BUF", 1, targets=50, carries=50, attempts=50)]
    totals = history + [played("MIA", 1, targets=10, carries=10, attempts=10)]
    row = row_for(2, history, totals)
    assert row["exp_targets"] == blend(50.0, 30.0, PASS_OWN_WEIGHT)
    assert row["exp_attempts"] == blend(50.0, 30.0, PASS_OWN_WEIGHT)
    assert row["exp_carries"] == blend(50.0, 30.0, RUSH_OWN_WEIGHT)
    assert row["exp_targets"] != row["exp_carries"]


def test_a_missing_side_collapses_to_the_other_rather_than_to_zero():
    assert blend(None, 30.0, 0.3) == 30.0
    assert blend(40.0, None, 0.3) == 40.0
    assert blend(None, None, 0.3) is None


# --- week 1 and absences ----------------------------------------------------


def test_week_one_is_entirely_null_rather_than_a_guess():
    """Nobody has played, so there is no own rate and no league rate either."""
    row = row_for(1, [])
    assert row["games_played"] == 0
    assert row["exp_targets"] is None
    assert row["exp_carries"] is None
    assert row["exp_attempts"] is None
    assert row["own_targets_pg"] is None
    assert row["league_targets_pg"] is None


def test_a_bye_is_not_a_week_of_zero_volume():
    """Rates are per game played. Dividing by weeks elapsed would halve this."""
    history = [played("BUF", 1, carries=20), played("BUF", 3, carries=30)]
    count, rates = own_rates(history, 4)
    assert count == 2
    assert rates["carries"] == 25.0


def test_a_team_with_no_history_still_gets_the_league_rate():
    """A first game in week 5 is unknown about the team, not unknown entirely."""
    totals = [played("MIA", 1, targets=30), played("NYJ", 2, targets=50)]
    row = row_for(5, [], totals)
    assert row["games_played"] == 0
    assert row["own_targets_pg"] is None
    assert row["exp_targets"] == 40.0


def test_league_rates_are_per_team_game_not_per_week():
    totals = team_week_totals([played("BUF", 1, targets=10), played("MIA", 1, targets=30)])
    assert league_rates(totals, 2)["targets"] == 20.0


# --- rows follow the schedule -----------------------------------------------


def test_a_team_on_a_bye_gets_no_row():
    schedule = [game(1, "BUF", "MIA"), game(2, "BUF", "NYJ")]
    assert scheduled(schedule) == {("BUF", 1), ("MIA", 1), ("BUF", 2), ("NYJ", 2)}


def test_an_unplayed_week_still_gets_a_row():
    """The point of the table. Driving rows off actuals would omit exactly this."""
    actuals = [played("BUF", 1), played("MIA", 1)]
    schedule = [game(1, "BUF", "MIA"), game(2, "BUF", "MIA")]
    rows = volume_rows(actuals, schedule, 2024, updated_at=UPDATED_AT)
    week_two = [row for row in rows if row["week"] == 2]
    assert len(week_two) == 2
    assert all(row["exp_targets"] is not None for row in week_two)


def test_one_week_can_be_recomputed_on_its_own():
    actuals = [played("BUF", 1), played("MIA", 1)]
    schedule = [game(1, "BUF", "MIA"), game(2, "BUF", "MIA")]
    rows = volume_rows(actuals, schedule, 2024, week=2, updated_at=UPDATED_AT)
    assert {row["week"] for row in rows} == {2}


def test_rows_cover_both_sides_of_every_game():
    schedule = [game(1, "BUF", "MIA"), game(1, "NYJ", "NE")]
    rows = volume_rows([], schedule, 2024, updated_at=UPDATED_AT)
    assert sorted(row["team_abbr"] for row in rows) == ["BUF", "MIA", "NE", "NYJ"]


# --- feature 30: cross-season shrinkage -----------------------------------------


def test_no_prior_season_leaves_exp_targets_exactly_as_before():
    """A season with nothing earlier on file (2024) must be provably unchanged."""
    history = [played("BUF", 1, targets=40), played("BUF", 2, targets=40)]
    row = volume_row("BUF", 2024, 3, history, team_week_totals(history), UPDATED_AT)
    expected = blend(row["own_targets_pg"], row["league_targets_pg"], PASS_OWN_WEIGHT)
    assert row["exp_targets"] == expected
    assert row["prior_season"] is None
    assert row["cross_season_weight"] is None
    assert row["prior_season_targets_pg"] is None


def test_week_one_with_a_prior_season_is_no_longer_null():
    """The exact gap feature 30 exists to fill."""
    prior_totals = [played("BUF", w, targets=20) for w in range(1, 18)]
    row = volume_row("BUF", 2026, 1, [], team_week_totals([]), UPDATED_AT, prior_season=2025, prior_season_totals=prior_totals)
    assert row["games_played"] == 0
    assert row["prior_season"] == 2025
    assert row["prior_season_targets_pg"] == 20.0
    assert row["cross_season_weight"] == 0.0  # pure prior season at zero games played
    assert row["exp_targets"] is not None


def test_cross_season_weight_rises_toward_one_as_games_played_grows():
    assert cross_season_weight(0, k=3.0) == 0.0
    low = cross_season_weight(1, k=3.0)
    high = cross_season_weight(10, k=3.0)
    assert 0.0 < low < high < 1.0


def test_prior_season_rates_is_none_for_a_team_absent_from_that_season():
    totals = [played("MIA", 1, targets=30)]
    rates = prior_season_rates(totals, "BUF")
    assert rates["targets"] is None


def test_own_targets_pg_is_unaffected_by_shrinkage():
    """own_targets_pg keeps its pure in-season meaning; only exp_targets shrinks."""
    history = [played("BUF", 1, targets=40)]
    prior_totals = [played("BUF", w, targets=10) for w in range(1, 18)]
    row = volume_row(
        "BUF", 2026, 2, history, team_week_totals(history), UPDATED_AT,
        prior_season=2025, prior_season_totals=prior_totals,
    )
    assert row["own_targets_pg"] == 40.0  # unchanged: one prior game this season, pure in-season
