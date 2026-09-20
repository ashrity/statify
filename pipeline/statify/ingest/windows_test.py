"""These helpers are already covered through form_test.py, on player histories.

What is untested there, and is the entire reason feature 13a moved them, is that
they do not care what a row represents. Everything below uses team weeks.
"""

from statify.ingest.windows import paired_sum, prior_games, window_slice


def defense_week(week, plays=30, epa_allowed=6.0):
    return {"week": week, "plays": plays, "epa_allowed": epa_allowed}


def test_a_teams_own_week_is_absent_from_its_own_window():
    weeks = [defense_week(w) for w in (5, 6, 7)]
    assert [w["week"] for w in prior_games(weeks, 7)] == [5, 6]


def test_a_bye_week_is_simply_a_week_that_is_not_there():
    """No row for the bye, so the window reaches further back rather than counting a zero."""
    weeks = [defense_week(w) for w in (4, 5, 7, 8)]
    assert [w["week"] for w in window_slice(prior_games(weeks, 9), 3)] == [5, 7, 8]


def test_a_ratio_of_sums_over_team_weeks():
    """A 12-play week must not weigh the same as a 40-play one."""
    weeks = [defense_week(1, plays=12, epa_allowed=6.0),
             defense_week(2, plays=40, epa_allowed=4.0)]
    top, bottom = paired_sum(weeks, "epa_allowed", "plays")
    assert (top, bottom) == (10.0, 52)
    assert top / bottom != (6.0 / 12 + 4.0 / 40) / 2


def test_a_week_missing_either_side_is_left_out_of_both_sums():
    weeks = [defense_week(1), defense_week(2, epa_allowed=None)]
    assert paired_sum(weeks, "epa_allowed", "plays") == (6.0, 30)


def test_a_negative_numerator_survives():
    """Run defence is negative EPA allowed by definition; no clamping anywhere."""
    weeks = [defense_week(1, plays=20, epa_allowed=-3.0)]
    assert paired_sum(weeks, "epa_allowed", "plays") == (-3.0, 20)


def test_an_empty_history_sums_to_nothing():
    assert paired_sum([], "epa_allowed", "plays") == (0.0, 0.0)
    assert prior_games([], 5) == []
