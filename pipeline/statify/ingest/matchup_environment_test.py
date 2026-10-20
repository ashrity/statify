import pytest

from statify.ingest.matchup_environment import (
    combined_pace,
    environment_multiplier,
    league_pace_by_week,
    matchup_environment_row,
    matchup_environment_rows,
    matchup_index,
    multiplier,
    opponent_map,
    pace_ratio,
)

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def game(game_id, week, home, away):
    return {"game_id": game_id, "week": week, "home_team": home, "away_team": away}


def matchup(team, week, position, play_type, epa):
    return {"team_abbr": team, "week": week, "position": position, "play_type": play_type, "epa_allowed_over_league_std": epa}


def environment(game_id, team, pace=None, opponent_pace=None):
    return {"game_id": game_id, "team_abbr": team, "pace": pace, "opponent_pace": opponent_pace}


def driver(player, week, team="BUF"):
    return {"player_id": player, "season": 2024, "week": week, "team_abbr": team}


# --- opponent lookup -----------------------------------------------------------


def test_opponent_map_covers_both_sides():
    schedule = [game("G1", 1, "BUF", "MIA")]
    mapping = opponent_map(schedule)
    assert mapping[("BUF", 1)] == ("MIA", "G1")
    assert mapping[("MIA", 1)] == ("BUF", "G1")


# --- the matchup multiplier -----------------------------------------------------


def test_matchup_multiplier_is_one_plus_k_times_the_epa_factor():
    assert multiplier(1.5, 0.2) == 1 + 1.5 * 0.2
    assert multiplier(1.5, -0.1) == 1 + 1.5 * -0.1


def test_a_missing_epa_factor_is_none_not_a_default():
    assert multiplier(1.5, None) is None


def test_a_neutral_matchup_leaves_the_multiplier_at_one():
    assert multiplier(1.5, 0.0) == 1.0


def test_matchup_index_looks_up_the_opponents_row_at_the_players_position():
    rows = [matchup("MIA", 3, "WR", "pass", 0.2), matchup("BUF", 3, "WR", "pass", -0.5)]
    index = matchup_index(rows)
    assert index[("MIA", 3, "WR", "pass")] == 0.2
    assert index[("BUF", 3, "WR", "pass")] == -0.5


# --- the environment multiplier -------------------------------------------------


def test_combined_pace_averages_both_sides():
    assert combined_pace(28.0, 30.0) == 29.0


def test_combined_pace_falls_back_to_the_one_side_present():
    assert combined_pace(28.0, None) == 28.0
    assert combined_pace(None, None) is None


def test_a_faster_than_league_team_gets_a_ratio_above_one():
    """Lower seconds-per-play is faster, so league/own > 1 for a fast team."""
    assert pace_ratio(league=28.0, own=26.0) > 1.0
    assert pace_ratio(league=28.0, own=30.0) < 1.0


def test_pace_ratio_is_none_when_either_side_is_missing():
    assert pace_ratio(None, 26.0) is None
    assert pace_ratio(28.0, None) is None


def test_environment_multiplier_is_neutral_at_a_ratio_of_one():
    assert environment_multiplier(2.0, 1.0) == 1.0


def test_environment_multiplier_scales_with_m():
    assert environment_multiplier(2.0, 1.1) == pytest.approx(1 + 2.0 * 0.1)


def test_league_pace_by_week_is_the_cross_sectional_mean():
    rows = [
        environment("G1", "BUF", pace=20.0, opponent_pace=30.0),  # combined 25
        environment("G1", "MIA", pace=30.0, opponent_pace=20.0),  # combined 25
        environment("G2", "NYJ", pace=27.0, opponent_pace=None),  # combined 27, week 2
    ]
    rows[2]["week"] = 2
    rows[0]["week"] = rows[1]["week"] = 1
    league = league_pace_by_week(rows)
    assert league[1] == 25.0
    assert league[2] == 27.0


# --- a full row ------------------------------------------------------------------


def test_a_row_combines_both_multipliers_and_stores_their_components():
    matchup_rows = {("MIA", 3, "WR", "pass"): 0.2, ("MIA", 3, "WR", "rush"): -0.1}
    environment_rows = {("G1", "BUF"): {"pace": 26.0, "opponent_pace": 30.0}}
    league_pace = {3: 28.0}
    row = matchup_environment_row(
        "WR1", 2024, 3, "BUF", "WR", "MIA", "G1",
        matchup_rows, environment_rows, league_pace,
        pass_k=1.5, rush_k=1.0, env_m=2.0, updated_at=UPDATED_AT,
    )
    assert row["pass_matchup_multiplier"] == 1 + 1.5 * 0.2
    assert row["rush_matchup_multiplier"] == 1 + 1.0 * -0.1
    assert row["own_pace"] == 26.0
    assert row["pace_ratio"] == 28.0 / 28.0  # combined (26+30)/2 = 28
    assert row["environment_multiplier"] == 1.0


def test_a_row_with_no_matchup_or_pace_data_is_all_none():
    row = matchup_environment_row(
        "WR1", 2024, 1, "BUF", "WR", "MIA", "G1",
        {}, {}, {},
        pass_k=1.5, rush_k=1.0, env_m=2.0, updated_at=UPDATED_AT,
    )
    assert row["pass_matchup_multiplier"] is None
    assert row["environment_multiplier"] is None


# --- rows follow the driver set, crossed with a known opponent -----------------


def test_rows_require_a_known_opponent():
    schedule = [game("G1", 2, "BUF", "MIA")]
    drivers = [driver("WR1", 2), driver("WR1", 1)]  # week 1 has no scheduled game in this test
    positions = {"WR1": "WR"}
    rows = matchup_environment_rows(drivers, schedule, [], [], positions, 2024, updated_at=UPDATED_AT)
    assert {row["week"] for row in rows} == {2}


def test_a_driver_row_with_no_known_position_is_skipped():
    schedule = [game("G1", 2, "BUF", "MIA")]
    rows = matchup_environment_rows([driver("GHOST", 2)], schedule, [], [], {}, 2024, updated_at=UPDATED_AT)
    assert rows == []
