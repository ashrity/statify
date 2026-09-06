from statify.ingest.usage import (
    aggregate_usage,
    share,
    team_air_yards,
    usage_row,
    weighted_opportunity,
)

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def actual(**overrides):
    base = {
        "player_id": "00-0036389",
        "game_id": "2024_01_GB_PHI",
        "season": 2024,
        "week": 1,
        "team_abbr": "PHI",
        "targets": 10,
        "air_yards": 95,
        "red_zone_touches": 3,
        "routes_run": 30,
    }
    return {**base, **overrides}


def play(**overrides):
    base = {
        "game_id": "G",
        "season_type": "REG",
        "posteam": "PHI",
        "pass": 0,
        "rush": 0,
        "air_yards": None,
        "receiver_player_id": None,
    }
    return {**base, **overrides}


def test_share_divides():
    assert share(10, 40) == 0.25


def test_zero_denominator_is_none_not_zero():
    """A team with no targets has no share to give, which is not a share of zero."""
    assert share(0, 0) is None
    assert share(5, 0) is None


def test_zero_numerator_is_zero_not_none():
    """A player who drew none of an existing opportunity took 0.0 of it."""
    assert share(0, 40) == 0.0


def test_none_numerator_is_none():
    assert share(None, 40) is None


def test_negative_numerator_gives_a_negative_share():
    """A pass behind the line has negative air yards; nflverse shows -0.0169."""
    assert share(-4, 237) < 0


def test_wopr_uses_the_published_weights():
    assert weighted_opportunity(0.3448, 0.4388) == 1.5 * 0.3448 + 0.7 * 0.4388


def test_wopr_matches_nflverse_on_a_real_row():
    """A.J. Brown, 2024 week 1, from the published columns."""
    assert round(weighted_opportunity(0.3448, 0.4388), 4) == 0.8244


def test_wopr_is_none_when_either_share_is_missing():
    """Treating a missing share as zero would understate the other half."""
    assert weighted_opportunity(None, 0.4) is None
    assert weighted_opportunity(0.3, None) is None


def test_team_air_yards_counts_every_pass_attempt():
    """Including a throwaway with no receiver: that is the 3.4% the denominator needs."""
    totals = team_air_yards([
        play(**{"pass": 1, "air_yards": 12, "receiver_player_id": "a"}),
        play(**{"pass": 1, "air_yards": 9}),
    ])
    assert totals[("PHI", "G")] == 21


def test_team_air_yards_ignores_runs_and_missing_charts():
    totals = team_air_yards([
        play(rush=1, air_yards=12),
        play(**{"pass": 1, "air_yards": None, "receiver_player_id": "b"}),
    ])
    assert totals == {}


def test_team_air_yards_ignores_preseason():
    assert team_air_yards([play(season_type="PRE", **{"pass": 1, "air_yards": 12})]) == {}


def test_usage_row_computes_every_share():
    team = {"targets": 29, "air_yards": 237, "red_zone_touches": 10, "dropbacks": 40}
    row = usage_row(actual(), team, UPDATED_AT)
    assert row["target_share"] == 10 / 29
    assert row["air_yards_share"] == 95 / 237
    assert row["adot"] == 9.5
    assert row["red_zone_touch_share"] == 0.3


def test_adot_is_none_without_targets():
    team = {"targets": 29, "air_yards": 237, "red_zone_touches": 10, "dropbacks": 40}
    assert usage_row(actual(targets=0, air_yards=0), team, UPDATED_AT)["adot"] is None


def test_team_targets_are_summed_from_our_player_rows():
    """Measured: this agrees with nflverse on 98% of rows, a pbp count on 89%."""
    rows = aggregate_usage(
        [actual(player_id="a", targets=10), actual(player_id="b", targets=30)],
        {("PHI", "2024_01_GB_PHI"): 200},
        {("PHI", "2024_01_GB_PHI"): 40},
        UPDATED_AT,
    )
    assert {r["team_targets"] for r in rows} == {40}
    assert round(sum(r["target_share"] for r in rows), 9) == 1.0


def test_a_null_red_zone_count_stays_out_of_the_team_total():
    """NULL means the play-by-play pass has not run, not that the player had none."""
    rows = aggregate_usage(
        [actual(player_id="a", red_zone_touches=3), actual(player_id="b", red_zone_touches=None)],
        {("PHI", "2024_01_GB_PHI"): 200},
        {("PHI", "2024_01_GB_PHI"): 40},
        UPDATED_AT,
    )
    by_id = {r["player_id"]: r for r in rows}
    assert by_id["a"]["team_red_zone_touches"] == 3
    assert by_id["b"]["red_zone_touch_share"] is None


def test_separate_games_do_not_share_a_denominator():
    rows = aggregate_usage(
        [actual(game_id="G1", targets=10), actual(game_id="G2", targets=30)],
        {("PHI", "G1"): 100, ("PHI", "G2"): 300},
        {("PHI", "G1"): 20, ("PHI", "G2"): 60},
        UPDATED_AT,
    )
    assert {r["team_targets"] for r in rows} == {10, 30}


def test_a_game_with_no_air_yards_yields_null_shares():
    """Better a visible NULL than a share computed against a denominator of zero."""
    rows = aggregate_usage([actual(targets=0, air_yards=0)], {}, {}, UPDATED_AT)
    assert rows[0]["team_air_yards"] == 0
    assert rows[0]["air_yards_share"] is None
    assert rows[0]["wopr"] is None


def test_empty_input():
    assert aggregate_usage([], {}, {}, UPDATED_AT) == []
