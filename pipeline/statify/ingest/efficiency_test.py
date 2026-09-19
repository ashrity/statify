from statify.ingest.efficiency import (
    COLUMNS,
    CatchSums,
    YacSums,
    aggregate_efficiency,
    efficiency_row,
    expected_receptions,
    expected_yac,
)

KEY = ("wr1", "G")
UPDATED_AT = "2026-01-01T00:00:00+00:00"


def actual(**overrides):
    base = {
        "player_id": "wr1",
        "game_id": "G",
        "season": 2024,
        "week": 1,
        "team_abbr": "PHI",
        "routes": 30,
        "receiving_yards": 90,
        "targets": 10,
        "receiving_epa": 5.0,
        "receptions": 7,
        "carries": 2,
        "rushing_yards": 12,
        "rushing_epa": -1.0,
        "attempts": 0,
        "completions": 0,
        "passing_yards": 0,
        "passing_epa": None,
    }
    return {**base, **overrides}


def row(catch=CatchSums(10, 7, 6.0), yac=YacSums(7, 40, 30.0), **overrides):
    return efficiency_row(actual(**overrides), catch, yac, UPDATED_AT)


def play(**overrides):
    base = {
        "game_id": "G",
        "season_type": "REG",
        "receiver_player_id": "wr1",
        "pass_attempt": 1,
        "two_point_attempt": 0,
        "complete_pass": 1,
        "cp": 0.6,
        "yards_after_catch": 5,
        "xyac_mean_yardage": 4.0,
    }
    return {**base, **overrides}


# --- what counts as a target ------------------------------------------------


def test_a_completed_pass_counts():
    assert expected_receptions([play()])[KEY] == (1, 1, 0.6)


def test_an_incompletion_counts_toward_the_denominator_only():
    """The expectation was spent whether or not he caught it."""
    sums = expected_receptions([play(complete_pass=0, yards_after_catch=None)])[KEY]
    assert sums.targets == 1
    assert sums.receptions == 0


def test_a_run_is_not_a_target():
    assert expected_receptions([play(pass_attempt=0)]) == {}


def test_a_two_point_conversion_is_not_a_target():
    """weekly_actuals excludes them, so counting them here would disagree."""
    assert expected_receptions([play(two_point_attempt=1)]) == {}


def test_preseason_is_not_a_target():
    assert expected_receptions([play(season_type="PRE")]) == {}


def test_postseason_is_a_target():
    assert expected_receptions([play(season_type="POST")])[KEY].targets == 1


def test_a_pass_with_no_credited_receiver_is_skipped():
    """A throwaway has a completion probability but nobody to credit it to."""
    assert expected_receptions([play(receiver_player_id=None, complete_pass=0)]) == {}


# --- the paired-sum rule, which is why these return denominators ------------


def test_a_missing_probability_leaves_the_play_out_of_both_sums():
    sums = expected_receptions([play(), play(cp=None)])[KEY]
    assert sums.targets == 1
    assert sums.expected == 0.6


def test_a_missing_expectation_leaves_the_completion_out_of_both_yac_sums():
    sums = expected_yac([play(), play(xyac_mean_yardage=None)])[KEY]
    assert sums.receptions == 1
    assert sums.actual_yards == 5
    assert sums.expected == 4.0


def test_a_completion_with_no_expectation_still_counts_for_catch_rate():
    """The two passes measure different things, so one gap must not create two."""
    plays = [play(xyac_mean_yardage=None)]
    assert expected_receptions(plays)[KEY].targets == 1
    assert expected_yac(plays) == {}


def test_a_target_with_no_probability_still_counts_for_yac():
    plays = [play(cp=None)]
    assert expected_receptions(plays) == {}
    assert expected_yac(plays)[KEY].receptions == 1


# --- yards after catch ------------------------------------------------------


def test_yac_ignores_incompletions():
    """There is no yardage after a catch that did not happen."""
    assert expected_yac([play(complete_pass=0, yards_after_catch=None)]) == {}


def test_yac_sums_actual_and_expected_over_the_same_completions():
    sums = expected_yac([
        play(yards_after_catch=5, xyac_mean_yardage=4.0),
        play(yards_after_catch=1, xyac_mean_yardage=6.5),
    ])[KEY]
    assert sums == (2, 6, 10.5)


def test_a_completion_with_no_recorded_yac_is_left_out_of_both():
    sums = expected_yac([play(), play(yards_after_catch=None)])[KEY]
    assert sums.receptions == 1
    assert sums.expected == 4.0


# --- accumulation -----------------------------------------------------------


def test_sums_accumulate_across_plays():
    sums = expected_receptions([play(cp=0.5), play(cp=0.25), play(cp=0.25)])[KEY]
    assert sums.targets == 3
    assert sums.expected == 1.0


def test_games_are_counted_separately():
    sums = expected_receptions([play(game_id="G1"), play(game_id="G2")])
    assert sums[("wr1", "G1")].targets == 1
    assert sums[("wr1", "G2")].targets == 1


def test_receivers_are_counted_separately():
    sums = expected_receptions([play(), play(receiver_player_id="te1")])
    assert set(sums) == {("wr1", "G"), ("te1", "G")}


def test_no_plays_yields_no_sums():
    assert expected_receptions([]) == {}
    assert expected_yac([]) == {}


# --- each rate divides by the denominator it names --------------------------


def test_receiving_rates():
    r = row()
    assert r["yprr"] == 3.0              # 90 yards / 30 routes
    assert r["yards_per_target"] == 9.0  # 90 / 10
    assert r["catch_rate"] == 0.7        # 7 / 10
    assert r["epa_per_target"] == 0.5    # 5.0 / 10


def test_rushing_rates():
    r = row()
    assert r["yards_per_carry"] == 6.0   # 12 / 2
    assert r["epa_per_carry"] == -0.5    # -1.0 / 2


def test_passing_rates():
    r = row(attempts=20, completions=13, passing_yards=240, passing_epa=8.0)
    assert r["completion_rate"] == 0.65
    assert r["yards_per_attempt"] == 12.0
    assert r["epa_per_attempt"] == 0.4


def test_yprr_is_yards_over_routes_not_the_other_way_up():
    """Both are plausible-looking numbers, so assert the direction."""
    assert row(receiving_yards=90, routes=30)["yprr"] == 3.0


def test_croe_is_catches_above_expectation_per_target():
    assert row(catch=CatchSums(10, 7, 6.0))["croe"] == 0.1


def test_croe_is_negative_when_he_caught_fewer_than_expected():
    assert row(catch=CatchSums(10, 4, 6.0))["croe"] == -0.2


def test_yacoe_is_yards_above_expectation_per_reception():
    assert row(yac=YacSums(5, 40, 30.0))["yacoe"] == 2.0


# --- a denominator of zero is a state, not an error -------------------------


def test_no_targets_gives_no_receiving_rates():
    r = row(targets=0, receiving_yards=0, receptions=0, receiving_epa=None)
    assert r["catch_rate"] is None
    assert r["yards_per_target"] is None
    assert r["epa_per_target"] is None


def test_no_carries_gives_no_rushing_rates():
    r = row(carries=0, rushing_yards=0, rushing_epa=None)
    assert r["yards_per_carry"] is None
    assert r["epa_per_carry"] is None


def test_no_attempts_gives_no_passing_rates():
    r = row()
    assert r["completion_rate"] is None
    assert r["yards_per_attempt"] is None
    assert r["epa_per_attempt"] is None


def test_missing_routes_gives_no_yprr():
    """compute usage may not have run; that is not a YPRR of zero."""
    r = row(routes=None)
    assert r["routes"] is None
    assert r["yprr"] is None
    assert r["yards_per_target"] is not None


def test_a_null_epa_gives_a_null_rate_not_a_zero():
    assert row(receiving_epa=None)["epa_per_target"] is None


def test_zero_routes_gives_no_yprr():
    assert row(routes=0)["yprr"] is None


# --- the absent player ------------------------------------------------------


def test_a_player_with_no_play_by_play_rows_gets_null_not_a_perfect_score():
    """Zero caught against zero expected is 0.0, which would read as average."""
    rows = aggregate_efficiency([actual()], {}, {}, UPDATED_AT)
    assert rows[0]["cp_targets"] == 0
    assert rows[0]["expected_receptions"] == 0.0
    assert rows[0]["croe"] is None
    assert rows[0]["yacoe"] is None


def test_the_stored_counts_survive_an_absent_play_by_play_row():
    """His box score is still real even when the expectation pass found nothing."""
    rows = aggregate_efficiency([actual()], {}, {}, UPDATED_AT)
    assert rows[0]["targets"] == 10
    assert rows[0]["catch_rate"] == 0.7


# --- assembling rows --------------------------------------------------------


def test_one_row_per_weekly_actual():
    actuals = [actual(game_id="G1"), actual(game_id="G2")]
    assert len(aggregate_efficiency(actuals, {}, {}, UPDATED_AT)) == 2


def test_sums_are_matched_by_player_and_game():
    actuals = [actual(game_id="G1"), actual(game_id="G2")]
    catch = {("wr1", "G1"): CatchSums(10, 9, 6.0)}
    rows = {r["game_id"]: r for r in aggregate_efficiency(actuals, catch, {}, UPDATED_AT)}
    assert rows["G1"]["croe"] == 0.3
    assert rows["G2"]["croe"] is None


def test_another_players_sums_are_not_borrowed():
    catch = {("te1", "G"): CatchSums(10, 10, 5.0)}
    assert aggregate_efficiency([actual()], catch, {}, UPDATED_AT)[0]["croe"] is None


def test_keys_and_timestamp_are_carried_through():
    r = row()
    assert (r["player_id"], r["game_id"], r["season"], r["week"]) == ("wr1", "G", 2024, 1)
    assert r["team_abbr"] == "PHI"
    assert r["updated_at"] == UPDATED_AT


def test_no_actuals_yields_no_rows():
    assert aggregate_efficiency([], {}, {}, UPDATED_AT) == []


def test_the_statement_and_the_row_carry_the_same_columns():
    """Generated SQL, so a column added to one and not the other is silent."""
    assert set(COLUMNS) == set(row())
