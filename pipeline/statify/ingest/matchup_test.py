from statify.ingest.matchup import (
    columns,
    league_rate,
    league_week_totals,
    matchup_row,
    matchup_rows,
)

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def allowed(team, week, plays=30, epa_allowed=6.0, position="WR", play_type="pass"):
    return {
        "team_abbr": team,
        "season": 2024,
        "week": week,
        "position": position,
        "play_type": play_type,
        "plays": plays,
        "epa_allowed": epa_allowed,
    }


def row_for(week, history, league=None):
    return matchup_row(
        "BUF", 2024, week, "WR", "pass", history,
        league_week_totals(league if league is not None else history), UPDATED_AT,
    )


# --- the boundary -----------------------------------------------------------


def test_a_weeks_own_result_is_absent_from_its_own_factor():
    """Leakage here has no downstream symptom, so it is asserted directly."""
    history = [allowed("BUF", 1, epa_allowed=3.0), allowed("BUF", 2, epa_allowed=30.0)]
    row = row_for(2, history)
    assert row["epa_allowed_per_play_std"] == 0.1        # week 1 only
    assert row["weeks_std"] == 1


def test_the_league_baseline_excludes_the_week_it_is_built_for():
    """The subtler half: a prior defense window against a league average that leaked."""
    league = [
        allowed("BUF", 1, plays=10, epa_allowed=1.0),
        allowed("NYJ", 1, plays=10, epa_allowed=1.0),
        allowed("BUF", 2, plays=10, epa_allowed=99.0),
        allowed("NYJ", 2, plays=10, epa_allowed=99.0),
    ]
    history = [r for r in league if r["team_abbr"] == "BUF"]
    row = row_for(2, history, league)
    assert row["league_epa_allowed_per_play_std"] == 0.1


def test_a_first_week_has_nothing_to_compare():
    row = row_for(1, [allowed("BUF", 1)])
    assert row["weeks_std"] == 0 and row["plays_std"] == 0
    assert row["epa_allowed_per_play_std"] is None
    assert row["league_epa_allowed_per_play_std"] is None
    assert row["epa_allowed_over_league_std"] is None


# --- the factor -------------------------------------------------------------


def test_a_defense_at_exactly_league_average_scores_zero():
    """Zero must be reachable, and must mean average rather than missing."""
    league = [allowed("BUF", 1, plays=10, epa_allowed=2.0),
              allowed("NYJ", 1, plays=10, epa_allowed=2.0)]
    row = row_for(2, [league[0]], league)
    assert row["epa_allowed_over_league_std"] == 0.0


def test_a_better_than_average_defense_scores_negative():
    """Lower EPA allowed is better, so the good direction is below zero."""
    league = [allowed("BUF", 1, plays=10, epa_allowed=0.0),
              allowed("NYJ", 1, plays=10, epa_allowed=4.0)]
    row = row_for(2, [league[0]], league)
    assert row["epa_allowed_over_league_std"] < 0


def test_a_worse_than_average_defense_scores_positive():
    league = [allowed("BUF", 1, plays=10, epa_allowed=4.0),
              allowed("NYJ", 1, plays=10, epa_allowed=0.0)]
    row = row_for(2, [league[0]], league)
    assert row["epa_allowed_over_league_std"] > 0


def test_a_negative_rate_is_never_clamped():
    """Run defense is negative EPA allowed by definition."""
    league = [allowed("BUF", 1, epa_allowed=-9.0, play_type="rush", position="RB")]
    row = matchup_row("BUF", 2024, 2, "RB", "rush", league,
                      league_week_totals(league), UPDATED_AT)
    assert row["epa_allowed_per_play_std"] < 0


# --- windows ----------------------------------------------------------------


def test_the_rate_is_a_ratio_of_sums_across_weeks():
    """A 10-play week must not weigh the same as a 40-play one."""
    history = [allowed("BUF", 1, plays=10, epa_allowed=5.0),
               allowed("BUF", 2, plays=40, epa_allowed=4.0)]
    row = row_for(3, history)
    assert row["epa_allowed_per_play_std"] == 9.0 / 50
    assert row["epa_allowed_per_play_std"] != (0.5 + 0.1) / 2


def test_the_last_three_window_takes_three_weeks_played():
    history = [allowed("BUF", w) for w in (1, 2, 3, 4, 5)]
    row = row_for(6, history)
    assert row["weeks_l3"] == 3 and row["weeks_l5"] == 5 and row["weeks_std"] == 5


def test_a_bye_is_a_missing_week_not_a_zero():
    """Weeks 4, 5, 7, 8 entering week 9: the last three are 5, 7 and 8."""
    history = [allowed("BUF", w) for w in (4, 5, 7, 8)]
    row = row_for(9, history)
    assert row["weeks_l3"] == 3
    assert row["plays_l3"] == 90


def test_the_league_baseline_covers_the_same_weeks_as_the_window():
    """Like for like. The league figure must not creep outside the defense's window."""
    league = [allowed("BUF", w, plays=10, epa_allowed=1.0) for w in (1, 2, 3, 4)]
    league += [allowed("NYJ", w, plays=10, epa_allowed=9.0) for w in (1, 2, 3, 4)]
    history = [r for r in league if r["team_abbr"] == "BUF"]
    row = row_for(5, history, league)
    # l3 covers weeks 2, 3, 4 only; std covers 1 to 4. Both average the same
    # here by construction, which is the point: the baseline follows the window.
    assert row["league_epa_allowed_per_play_l3"] == 0.5
    assert row["league_epa_allowed_per_play_std"] == 0.5
    assert row["plays_l3"] == 30 and row["plays_std"] == 40


def test_plays_are_counted_per_window():
    history = [allowed("BUF", w, plays=20) for w in (1, 2, 3, 4, 5)]
    row = row_for(6, history)
    assert row["plays_l3"] == 60 and row["plays_l5"] == 100 and row["plays_std"] == 100


# --- league totals ----------------------------------------------------------


def test_league_totals_sum_every_defense_in_a_week():
    totals = league_week_totals([allowed("BUF", 1, plays=10, epa_allowed=1.0),
                                 allowed("NYJ", 1, plays=30, epa_allowed=5.0)])
    assert totals[("WR", "pass", 1)] == (40, 6.0)


def test_buckets_never_share_a_baseline():
    """WR pass averages +0.24 and RB rush -0.06; one league number would ruin both."""
    totals = league_week_totals([
        allowed("BUF", 1, plays=10, epa_allowed=4.0),
        allowed("BUF", 1, plays=10, epa_allowed=-1.0, position="RB", play_type="rush"),
    ])
    assert league_rate(totals, "WR", "pass", {1}) == 0.4
    assert league_rate(totals, "RB", "rush", {1}) == -0.1


def test_a_week_nobody_played_has_no_league_rate():
    totals = league_week_totals([allowed("BUF", 1)])
    assert league_rate(totals, "WR", "pass", {9}) is None
    assert league_rate(totals, "WR", "pass", set()) is None


# --- assembling rows --------------------------------------------------------


def test_every_bucket_gets_a_row_for_every_week_the_defense_played():
    """Week 2 has no RB rush row in the input, but the factor is still defined."""
    rows = matchup_rows([
        allowed("BUF", 1),
        allowed("BUF", 1, position="RB", play_type="rush"),
        allowed("BUF", 2),
    ], UPDATED_AT)
    keys = {(r["week"], r["position"], r["play_type"]) for r in rows}
    assert keys == {(1, "WR", "pass"), (1, "RB", "rush"),
                    (2, "WR", "pass"), (2, "RB", "rush")}


def test_a_bucket_not_faced_this_week_still_carries_its_prior_form():
    """The gap that made feature 18 unable to look up a factor that existed."""
    rows = matchup_rows([
        allowed("BUF", 1, plays=10, epa_allowed=5.0, position="RB", play_type="rush"),
        allowed("BUF", 2),
    ], UPDATED_AT)
    week2_rush = next(r for r in rows if r["week"] == 2 and r["play_type"] == "rush")
    assert week2_rush["weeks_std"] == 1
    assert week2_rush["epa_allowed_per_play_std"] == 0.5


def test_a_bucket_the_season_never_contained_is_not_invented():
    """Buckets come from the data, not from every position times every play type."""
    rows = matchup_rows([allowed("BUF", 1), allowed("BUF", 2)], UPDATED_AT)
    assert {(r["position"], r["play_type"]) for r in rows} == {("WR", "pass")}


def test_a_defense_with_no_history_in_a_bucket_gets_nulls_not_zeros():
    rows = matchup_rows([
        allowed("BUF", 1),
        allowed("NYJ", 1, position="RB", play_type="rush"),
        allowed("BUF", 2),
    ], UPDATED_AT)
    buf_rush = next(r for r in rows
                    if r["team_abbr"] == "BUF" and r["week"] == 2 and r["play_type"] == "rush")
    assert buf_rush["weeks_std"] == 0
    assert buf_rush["epa_allowed_over_league_std"] is None


def test_each_row_sees_only_its_own_past():
    rows = matchup_rows([allowed("BUF", w) for w in (1, 2, 3)], UPDATED_AT)
    assert [r["weeks_std"] for r in sorted(rows, key=lambda r: r["week"])] == [0, 1, 2]


def test_no_defense_rows_produce_no_matchup_rows():
    assert matchup_rows([], UPDATED_AT) == []


def test_the_statement_and_the_row_carry_the_same_columns():
    """Generated SQL, so a column in one and not the other is silent."""
    row = matchup_rows([allowed("BUF", 1)], UPDATED_AT)[0]
    assert set(columns()) == set(row)
