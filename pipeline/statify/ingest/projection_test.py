from statify.ingest.projection import (
    STAT_TYPES,
    neutral,
    product_row,
    projection_rows,
    projection_rows_for_player_week,
)

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def opportunity(player, week, team="BUF", exp_targets=10.0, exp_carries=5.0, exp_attempts=0.0):
    return {
        "player_id": player,
        "season": 2024,
        "week": week,
        "team_abbr": team,
        "exp_targets": exp_targets,
        "exp_carries": exp_carries,
        "exp_attempts": exp_attempts,
    }


def efficiency(player, week, exp_yards_per_target=8.0, exp_catch_rate=0.7, exp_yards_per_carry=4.0, exp_yards_per_attempt=7.0):
    return {
        "player_id": player,
        "week": week,
        "exp_yards_per_target": exp_yards_per_target,
        "exp_catch_rate": exp_catch_rate,
        "exp_yards_per_carry": exp_yards_per_carry,
        "exp_yards_per_attempt": exp_yards_per_attempt,
    }


def touchdown(player, week, anytime_td_prob=0.3, exp_touchdowns=0.35):
    return {"player_id": player, "week": week, "anytime_td_prob": anytime_td_prob, "exp_touchdowns": exp_touchdowns}


def matchup(player, week, position="WR", pass_matchup_multiplier=1.1, rush_matchup_multiplier=1.05, environment_multiplier=0.95):
    return {
        "player_id": player,
        "week": week,
        "position": position,
        "pass_matchup_multiplier": pass_matchup_multiplier,
        "rush_matchup_multiplier": rush_matchup_multiplier,
        "environment_multiplier": environment_multiplier,
    }


# --- the substitution rule -------------------------------------------------------


def test_a_missing_multiplier_becomes_neutral():
    assert neutral(None) == 1.0
    assert neutral(0.8) == 0.8


def test_product_row_uses_the_neutral_substitution_but_reports_it():
    baseline, raw, matchup_used, env_used = product_row(10.0, 2.0, None, None)
    assert baseline == 20.0
    assert raw == 20.0
    assert matchup_used == 1.0
    assert env_used == 1.0


def test_product_row_is_none_when_a_component_is_missing():
    baseline, raw, _, _ = product_row(None, 2.0, 1.1, 0.9)
    assert baseline is None
    assert raw is None


# --- each formula ------------------------------------------------------------------


def test_receiving_yards_is_targets_times_ypt_times_pass_side():
    rows = projection_rows_for_player_week(
        "WR1", 2024, 3, "BUF",
        opportunity("WR1", 3, exp_targets=10.0),
        efficiency("WR1", 3, exp_yards_per_target=8.0),
        touchdown("WR1", 3),
        matchup("WR1", 3, pass_matchup_multiplier=1.1, environment_multiplier=0.9),
        UPDATED_AT,
    )
    by_stat = {r["stat_type"]: r for r in rows}
    assert by_stat["receiving_yards"]["raw_projection"] == 10.0 * 8.0 * 1.1 * 0.9
    assert by_stat["receiving_yards"]["baseline_value"] == 80.0


def test_receptions_uses_catch_rate_and_the_same_pass_side_multiplier():
    rows = projection_rows_for_player_week(
        "WR1", 2024, 3, "BUF",
        opportunity("WR1", 3, exp_targets=10.0),
        efficiency("WR1", 3, exp_catch_rate=0.6),
        touchdown("WR1", 3),
        matchup("WR1", 3, pass_matchup_multiplier=1.2, environment_multiplier=1.0),
        UPDATED_AT,
    )
    by_stat = {r["stat_type"]: r for r in rows}
    assert by_stat["receptions"]["raw_projection"] == 10.0 * 0.6 * 1.2 * 1.0


def test_rushing_yards_uses_the_rush_side_multiplier():
    rows = projection_rows_for_player_week(
        "RB1", 2024, 3, "BUF",
        opportunity("RB1", 3, exp_carries=15.0),
        efficiency("RB1", 3, exp_yards_per_carry=4.5),
        touchdown("RB1", 3),
        matchup("RB1", 3, position="RB", rush_matchup_multiplier=0.9, environment_multiplier=1.1),
        UPDATED_AT,
    )
    by_stat = {r["stat_type"]: r for r in rows}
    assert by_stat["rushing_yards"]["raw_projection"] == 15.0 * 4.5 * 0.9 * 1.1


def test_passing_yards_uses_attempts_and_the_pass_side_multiplier():
    rows = projection_rows_for_player_week(
        "QB1", 2024, 3, "BUF",
        opportunity("QB1", 3, exp_attempts=30.0),
        efficiency("QB1", 3, exp_yards_per_attempt=7.5),
        touchdown("QB1", 3),
        matchup("QB1", 3, position="QB", pass_matchup_multiplier=1.05, environment_multiplier=1.0),
        UPDATED_AT,
    )
    by_stat = {r["stat_type"]: r for r in rows}
    assert by_stat["passing_yards"]["raw_projection"] == 30.0 * 7.5 * 1.05 * 1.0


def test_touchdowns_is_the_probability_undecorated_by_any_multiplier():
    rows = projection_rows_for_player_week(
        "WR1", 2024, 3, "BUF",
        opportunity("WR1", 3),
        efficiency("WR1", 3),
        touchdown("WR1", 3, anytime_td_prob=0.42, exp_touchdowns=0.5),
        matchup("WR1", 3, pass_matchup_multiplier=1.5, environment_multiplier=1.5),
        UPDATED_AT,
    )
    by_stat = {r["stat_type"]: r for r in rows}
    assert by_stat["touchdowns"]["raw_projection"] == 0.42
    assert by_stat["touchdowns"]["baseline_value"] == 0.5
    assert by_stat["touchdowns"]["matchup_multiplier_used"] is None
    assert by_stat["touchdowns"]["environment_multiplier_used"] is None


def test_every_stat_type_is_emitted_exactly_once():
    rows = projection_rows_for_player_week(
        "WR1", 2024, 3, "BUF", opportunity("WR1", 3), efficiency("WR1", 3), touchdown("WR1", 3), matchup("WR1", 3), UPDATED_AT
    )
    assert {r["stat_type"] for r in rows} == set(STAT_TYPES)
    assert len(rows) == len(STAT_TYPES)


# --- missing components ----------------------------------------------------------


def test_missing_efficiency_leaves_the_product_stats_none_but_not_touchdowns():
    rows = projection_rows_for_player_week(
        "WR1", 2024, 3, "BUF", opportunity("WR1", 3), None, touchdown("WR1", 3), matchup("WR1", 3), UPDATED_AT
    )
    by_stat = {r["stat_type"]: r for r in rows}
    assert by_stat["receiving_yards"]["raw_projection"] is None
    assert by_stat["touchdowns"]["raw_projection"] is not None


def test_a_player_with_no_known_position_is_skipped_entirely():
    rows = projection_rows_for_player_week(
        "GHOST", 2024, 3, "BUF", opportunity("GHOST", 3), efficiency("GHOST", 3), touchdown("GHOST", 3), None, UPDATED_AT
    )
    assert rows == []


# --- assembling the full table ----------------------------------------------------


def test_projection_rows_joins_by_player_and_week():
    rows = projection_rows(
        [opportunity("WR1", 3)], [efficiency("WR1", 3)], [touchdown("WR1", 3)], [matchup("WR1", 3)], 2024, updated_at=UPDATED_AT
    )
    assert len(rows) == len(STAT_TYPES)
    assert all(r["player_id"] == "WR1" and r["week"] == 3 for r in rows)
