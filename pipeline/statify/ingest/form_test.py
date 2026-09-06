from statify.ingest.form import (
    form_row,
    form_rows,
    prior_games,
    window_slice,
    window_values,
)

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def game(week, targets=5, team_targets=30, air_yards=50, team_air_yards=250,
         carries=0, red_zone_touches=1, team_red_zone_touches=10, snap_share=0.8):
    return {
        "week": week,
        "targets": targets,
        "team_targets": team_targets,
        "air_yards": air_yards,
        "team_air_yards": team_air_yards,
        "carries": carries,
        "red_zone_touches": red_zone_touches,
        "team_red_zone_touches": team_red_zone_touches,
        "snap_share": snap_share,
    }


# --- the boundary, which is the whole feature -------------------------------


def test_a_weeks_own_game_is_absent_from_its_own_window():
    """The failure this guards has no downstream symptom, so assert it directly."""
    history = [game(6), game(7), game(8)]
    assert [g["week"] for g in prior_games(history, 8)] == [6, 7]


def test_no_prior_games_before_the_first_appearance():
    assert prior_games([game(1), game(2)], 1) == []


def test_later_weeks_never_leak_backwards():
    history = [game(1), game(5), game(9)]
    assert [g["week"] for g in prior_games(history, 5)] == [1]


def test_prior_games_are_ordered_oldest_first():
    """An unordered history makes 'last 3' arbitrary while still looking fine."""
    history = [game(9), game(1), game(5)]
    assert [g["week"] for g in prior_games(history, 12)] == [1, 5, 9]


# --- windows count games, not weeks -----------------------------------------


def test_window_takes_the_most_recent_games():
    prior = [game(w) for w in (1, 2, 3, 4, 5)]
    assert [g["week"] for g in window_slice(prior, 3)] == [3, 4, 5]


def test_window_skips_weeks_the_player_missed():
    """A.J. Brown played week 1 then weeks 6 and 7; entering week 8 that is his last 3."""
    prior = [game(1), game(6), game(7)]
    assert [g["week"] for g in window_slice(prior, 3)] == [1, 6, 7]


def test_a_short_history_returns_what_exists():
    prior = [game(1), game(2)]
    assert len(window_slice(prior, 3)) == 2


def test_season_to_date_takes_everything_prior():
    prior = [game(w) for w in range(1, 12)]
    assert len(window_slice(prior, None)) == 11


# --- volume weighting -------------------------------------------------------


def test_rates_are_a_ratio_of_sums_not_a_mean_of_ratios():
    """5/10 and 1/30 give 6/40, not the mean of 0.5 and 0.033."""
    values = window_values([
        game(1, targets=5, team_targets=10),
        game(2, targets=1, team_targets=30),
    ])
    assert values["target_share"] == 6 / 40
    assert values["target_share"] != (0.5 + 1 / 30) / 2


def test_per_game_metrics_divide_by_games():
    values = window_values([game(1, targets=4), game(2, targets=10)])
    assert values["targets_pg"] == 7.0


def test_wopr_is_built_from_the_windowed_shares():
    values = window_values([
        game(1, targets=5, team_targets=10, air_yards=50, team_air_yards=100),
    ])
    assert values["wopr"] == 1.5 * 0.5 + 0.7 * 0.5


def test_snap_share_is_a_mean():
    """The one metric with no stored denominator, so a mean is all there is."""
    values = window_values([game(1, snap_share=0.6), game(2, snap_share=1.0)])
    assert values["snap_share"] == 0.8


def test_a_zero_denominator_in_a_window_is_null_not_an_error():
    values = window_values([game(1, targets=0, team_targets=0)])
    assert values["target_share"] is None


def test_games_missing_a_metric_are_skipped_for_that_metric_only():
    """A NULL red zone count must not poison the target share too."""
    values = window_values([
        game(1, red_zone_touches=None, team_red_zone_touches=None),
        game(2, red_zone_touches=2, team_red_zone_touches=8),
    ])
    assert values["rz_touch_share"] == 0.25
    assert values["target_share"] is not None


# --- assembling rows --------------------------------------------------------


def test_an_empty_window_is_all_null_with_zero_counts():
    row = form_row("p", 2024, 1, [game(1)], UPDATED_AT)
    assert row["games_l3"] == 0 and row["games_l5"] == 0 and row["games_std"] == 0
    assert row["target_share_l3"] is None
    assert row["wopr_std"] is None
    assert row["snap_share_l5"] is None


def test_sample_size_reflects_what_was_available():
    """Two prior games give a value computed from two, not a NULL and not a third."""
    row = form_row("p", 2024, 3, [game(1), game(2), game(3)], UPDATED_AT)
    assert row["games_l3"] == 2
    assert row["games_l5"] == 2
    assert row["target_share_l3"] is not None


def test_last_three_and_season_diverge_once_there_is_enough_history():
    history = [game(w, targets=1) for w in range(1, 6)] + [game(6, targets=20)]
    row = form_row("p", 2024, 7, history, UPDATED_AT)
    assert row["games_l3"] == 3 and row["games_std"] == 6
    assert row["targets_pg_l3"] > row["targets_pg_std"]


def test_one_row_per_appearance():
    rows = form_rows("p", 2024, [game(1), game(4), game(9)], UPDATED_AT)
    assert [r["week"] for r in rows] == [1, 4, 9]


def test_each_row_sees_only_its_own_past():
    rows = form_rows("p", 2024, [game(1), game(2), game(3)], UPDATED_AT)
    assert [r["games_std"] for r in rows] == [0, 1, 2]


def test_no_history_produces_no_rows():
    assert form_rows("p", 2024, [], UPDATED_AT) == []
