from statify.ingest.opportunity import (
    ATTEMPTS_OWN_WEIGHT,
    CARRIES_OWN_WEIGHT,
    TARGETS_OWN_WEIGHT,
    attach_team_totals,
    opportunity_row,
    opportunity_rows,
)
from statify.ingest.volume import blend
from statify.ingest.windows import prior_games

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def played(player, team, week, targets=5, carries=3, attempts=0, routes_run=10):
    return {
        "player_id": player,
        "team_abbr": team,
        "week": week,
        "targets": targets,
        "carries": carries,
        "attempts": attempts,
        "routes_run": routes_run,
    }


def team_totals(team, week, targets=20, carries=20, attempts=20):
    return {"team_abbr": team, "week": week, "targets": targets, "carries": carries, "attempts": attempts}


def game(week, home, away):
    return {"week": week, "home_team": home, "away_team": away}


def row_for(week, history, team_exp=None):
    totals = {(g["team_abbr"], g["week"]): team_totals(g["team_abbr"], g["week"]) for g in history}
    attached = attach_team_totals(history, totals)
    prior = prior_games(attached, week)
    return opportunity_row("WR1", 2024, week, prior, team_exp or {}, UPDATED_AT)


# --- the boundary -------------------------------------------------------------


def test_a_weeks_own_result_is_absent_from_its_own_expectation():
    history = [played("WR1", "BUF", 1, targets=1), played("WR1", "BUF", 2, targets=99)]
    row = row_for(2, history)
    assert row["own_targets_pg"] == 1.0
    assert row["games_played"] == 1


def test_a_player_with_no_prior_game_gets_no_row():
    """The debut week has no history to build from, so it must not appear."""
    actuals = [played("WR1", "BUF", 3)]
    team_actuals = [team_totals("BUF", 3)]
    schedule = [game(1, "BUF", "MIA"), game(2, "BUF", "MIA"), game(3, "BUF", "MIA")]
    volume = [{"team_abbr": "BUF", "week": w, "exp_targets": 20.0, "exp_carries": 20.0, "exp_attempts": 20.0} for w in (1, 2, 3)]
    rows = opportunity_rows(actuals, team_actuals, schedule, volume, 2024, updated_at=UPDATED_AT)
    assert rows == []


# --- own rate, share and the blend --------------------------------------------


def test_own_rate_is_a_plain_mean_over_prior_games():
    history = [played("WR1", "BUF", 1, carries=10), played("WR1", "BUF", 2, carries=20)]
    row = row_for(3, history)
    assert row["own_carries_pg"] == 15.0


def test_share_is_the_players_sum_over_the_teams_sum():
    history = [played("WR1", "BUF", 1, targets=5), played("WR1", "BUF", 2, targets=15)]
    row = row_for(3, history)
    assert row["target_share"] == 20.0 / 40.0


def test_zero_prior_targets_is_a_real_number_not_none():
    """A player with one prior game and zero targets in it genuinely took none."""
    history = [played("WR1", "BUF", 1, targets=0)]
    row = row_for(2, history)
    assert row["own_targets_pg"] == 0.0
    assert row["target_share"] == 0.0


def test_missing_routes_leaves_the_own_rate_none_rather_than_zero():
    history = [played("WR1", "BUF", 1, routes_run=None), played("WR1", "BUF", 2, routes_run=None)]
    row = row_for(3, history)
    assert row["own_routes_pg"] is None
    assert row["exp_routes"] is None


def test_exp_routes_is_always_the_own_average_with_no_weight():
    history = [played("WR1", "BUF", 1, routes_run=30), played("WR1", "BUF", 2, routes_run=10)]
    row = row_for(3, history)
    assert row["exp_routes"] == row["own_routes_pg"] == 20.0


def test_the_blend_is_reproducible_from_the_row_alone():
    history = [played("WR1", "BUF", 1, targets=10), played("WR1", "BUF", 2, targets=10)]
    team_exp = {"exp_targets": 25.0, "exp_carries": 25.0, "exp_attempts": 25.0}
    row = row_for(3, history, team_exp)
    team_share_estimate = row["team_exp_targets"] * row["target_share"]
    expected = blend(row["own_targets_pg"], team_share_estimate, TARGETS_OWN_WEIGHT)
    assert row["exp_targets"] == expected


def test_each_stat_carries_its_own_weight_onto_the_row():
    row = row_for(2, [played("WR1", "BUF", 1)])
    assert row["targets_own_weight"] == TARGETS_OWN_WEIGHT
    assert row["carries_own_weight"] == CARRIES_OWN_WEIGHT
    assert row["attempts_own_weight"] == ATTEMPTS_OWN_WEIGHT


def test_a_missing_team_expectation_falls_back_to_the_players_own_rate():
    """Week 1 team volume rows are entirely NULL; this must not become a 0."""
    history = [played("WR1", "BUF", 1, targets=10), played("WR1", "BUF", 2, targets=10)]
    row = row_for(3, history, team_exp={"exp_targets": None, "exp_carries": None, "exp_attempts": None})
    assert row["exp_targets"] == row["own_targets_pg"]


# --- an in-season team change --------------------------------------------------


def test_a_team_change_is_reflected_only_from_its_first_game_onward():
    history = [
        played("WR1", "BUF", 1, targets=10),
        played("WR1", "BUF", 2, targets=10),
        played("WR1", "MIA", 3, targets=10),
    ]
    totals = {
        ("BUF", 1): team_totals("BUF", 1),
        ("BUF", 2): team_totals("BUF", 2),
        ("MIA", 3): team_totals("MIA", 3),
    }
    attached = attach_team_totals(history, totals)

    row_before_trade = opportunity_row("WR1", 2024, 3, prior_games(attached, 3), {}, UPDATED_AT)
    assert row_before_trade["team_abbr"] == "BUF"

    row_after_trade = opportunity_row("WR1", 2024, 4, prior_games(attached, 4), {}, UPDATED_AT)
    assert row_after_trade["team_abbr"] == "MIA"


# --- rows follow the player's history crossed with the schedule --------------


def test_an_unplayed_week_still_gets_a_row_for_a_returning_player():
    actuals = [played("WR1", "BUF", 1)]
    team_actuals = [team_totals("BUF", 1)]
    schedule = [game(1, "BUF", "MIA"), game(2, "BUF", "MIA")]
    volume = [{"team_abbr": "BUF", "week": 2, "exp_targets": 20.0, "exp_carries": 20.0, "exp_attempts": 20.0}]
    rows = opportunity_rows(actuals, team_actuals, schedule, volume, 2024, updated_at=UPDATED_AT)
    assert [row["week"] for row in rows] == [2]
    assert rows[0]["exp_targets"] is not None


def test_a_bye_week_for_his_team_gets_no_row():
    actuals = [played("WR1", "BUF", 1)]
    team_actuals = [team_totals("BUF", 1)]
    schedule = [game(1, "BUF", "MIA")]  # BUF has no game in week 2
    rows = opportunity_rows(actuals, team_actuals, schedule, [], 2024, week=2, updated_at=UPDATED_AT)
    assert rows == []


def test_one_week_can_be_recomputed_on_its_own():
    actuals = [played("WR1", "BUF", 1), played("WR1", "BUF", 2)]
    team_actuals = [team_totals("BUF", 1), team_totals("BUF", 2)]
    schedule = [game(1, "BUF", "MIA"), game(2, "BUF", "MIA"), game(3, "BUF", "MIA")]
    volume = [{"team_abbr": "BUF", "week": 3, "exp_targets": 20.0, "exp_carries": 20.0, "exp_attempts": 20.0}]
    rows = opportunity_rows(actuals, team_actuals, schedule, volume, 2024, week=3, updated_at=UPDATED_AT)
    assert {row["week"] for row in rows} == {3}
