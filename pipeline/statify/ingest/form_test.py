from statify.ingest.form import (
    VALUE_COLUMNS,
    decay_weights,
    ewma_values,
    form_columns,
    form_row,
    form_rows,
    measured_games,
    prior_games,
    ryoe_attempts,
    window_slice,
    window_values,
)

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def game(week, targets=5, team_targets=30, air_yards=50, team_air_yards=250,
         carries=0, red_zone_touches=1, team_red_zone_touches=10, snap_share=0.8,
         routes=30, team_dropbacks=40, **efficiency):
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
        "routes": routes,
        "team_dropbacks": team_dropbacks,
        **{field: None for field in EFFICIENCY_FIELDS},
        **efficiency,
    }


# Everything the efficiency rates read. Defaulted to None rather than 0 so a
# test that does not mention a metric leaves it absent rather than asserting
# against a denominator it never set.
EFFICIENCY_FIELDS = (
    "receiving_yards", "receptions", "receiving_epa",
    "rushing_yards", "rushing_epa",
    "attempts", "completions", "passing_yards", "passing_epa",
    "cp_targets", "catches_over_expected",
    "xyac_receptions", "yac_over_expected",
    "ryoe", "ryoe_attempts",
)


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


# --- recency weighting ------------------------------------------------------


def test_the_most_recent_game_carries_full_weight():
    assert decay_weights(1, 3.0) == [1.0]
    assert decay_weights(4, 3.0)[-1] == 1.0


def test_a_game_one_half_life_back_carries_half():
    """With a half-life of 3, three appearances back is one half-life, not three."""
    weights = decay_weights(4, 3.0)
    assert weights[-1] == 1.0     # most recent
    assert weights[-4] == 0.5     # three appearances back = one half-life
    assert round(weights[-2], 10) == round(0.5 ** (1 / 3), 10)


def test_weights_halve_every_half_life():
    weights = decay_weights(7, 3.0)
    assert weights[-1] == 1.0
    assert round(weights[-4], 10) == 0.5
    assert round(weights[-7], 10) == 0.25


def test_weights_are_ordered_oldest_first():
    weights = decay_weights(5, 3.0)
    assert weights == sorted(weights)


def test_ewma_weights_the_parts_not_the_ratio():
    """The trap. Weighting the share instead discards volume.

    Two games at 5/10 and 1/30 with weights 0.5 and 1.0:
      correct   (0.5*5 + 1*1) / (0.5*10 + 1*30) = 3.5/35   = 0.1
      incorrect (0.5*0.5 + 1*(1/30)) / 1.5      = 0.2833/1.5 = 0.1889
    """
    games = [game(1, targets=5, team_targets=10), game(2, targets=1, team_targets=30)]
    values = ewma_values(games, half_life=1.0)
    assert round(values["target_share"], 10) == 0.1
    assert round(values["target_share"], 4) != 0.1889


def test_ewma_leans_toward_the_recent_game():
    games = [game(1, targets=2, team_targets=20), game(2, targets=10, team_targets=20)]
    weighted = ewma_values(games, half_life=1.0)["target_share"]
    unweighted = window_values(games)["target_share"]
    assert weighted > unweighted


def test_ewma_of_a_single_game_is_that_game():
    values = ewma_values([game(1, targets=5, team_targets=20)], half_life=3.0)
    assert values["target_share"] == 0.25


def test_ewma_per_game_metrics_are_a_weighted_mean():
    games = [game(1, targets=0), game(2, targets=9)]
    # weights 0.5 and 1.0 -> (0.5*0 + 1*9) / 1.5 = 6.0
    assert ewma_values(games, half_life=1.0)["targets_pg"] == 6.0


def test_ewma_snap_share_is_a_weighted_mean():
    games = [game(1, snap_share=0.0), game(2, snap_share=0.9)]
    assert ewma_values(games, half_life=1.0)["snap_share"] == 0.6


def test_ewma_wopr_comes_from_the_weighted_shares():
    games = [game(1, targets=5, team_targets=10, air_yards=50, team_air_yards=100)]
    values = ewma_values(games, half_life=3.0)
    assert values["wopr"] == 1.5 * values["target_share"] + 0.7 * values["air_yards_share"]


def test_ewma_of_an_empty_history_is_all_null():
    assert ewma_values([], half_life=3.0) == dict.fromkeys(VALUE_COLUMNS)


def test_ewma_skips_games_missing_a_metric():
    games = [
        game(1, red_zone_touches=None, team_red_zone_touches=None),
        game(2, red_zone_touches=3, team_red_zone_touches=6),
    ]
    assert ewma_values(games, half_life=1.0)["rz_touch_share"] == 0.5


def test_form_row_records_the_half_life_even_with_no_history():
    row = form_row("p", 2024, 1, [game(1)], UPDATED_AT)
    assert row["ewma_half_life"] == 3.0
    assert row["target_share_ewma"] is None


def test_form_row_ewma_uses_only_prior_games():
    """Reuses prior_games, so a week's own result must not reach its EWMA."""
    history = [game(1, targets=5, team_targets=20), game(2, targets=20, team_targets=20)]
    row = form_row("p", 2024, 2, history, UPDATED_AT)
    assert row["target_share_ewma"] == 0.25


def test_form_columns_cover_every_ewma_value():
    columns = set(form_columns())
    assert "ewma_half_life" in columns
    for value in VALUE_COLUMNS:
        assert f"{value}_ewma" in columns


# --- efficiency rates (feature 12b) -----------------------------------------

# Each rate, with a small and a large game. The large one has the worse rate, so
# a mean of ratios always lands above the ratio of sums and the two can never be
# confused by an unlucky choice of numbers.
EFFICIENCY_RATES = [
    ("yprr", "receiving_yards", "routes", (30, 5), (60, 40)),
    ("yards_per_target", "receiving_yards", "targets", (30, 2), (60, 20)),
    ("catch_rate", "receptions", "targets", (2, 2), (4, 20)),
    ("croe", "catches_over_expected", "cp_targets", (1.0, 2), (1.0, 20)),
    ("yacoe", "yac_over_expected", "xyac_receptions", (4.0, 2), (4.0, 20)),
    ("epa_per_target", "receiving_epa", "targets", (4.0, 2), (4.0, 20)),
    ("yards_per_carry", "rushing_yards", "carries", (20, 2), (40, 20)),
    ("epa_per_carry", "rushing_epa", "carries", (4.0, 2), (4.0, 20)),
    ("yards_per_attempt", "passing_yards", "attempts", (30, 2), (60, 20)),
    ("completion_rate", "completions", "attempts", (2, 2), (4, 20)),
    ("epa_per_attempt", "passing_epa", "attempts", (4.0, 2), (4.0, 20)),
]


def test_every_efficiency_rate_is_a_ratio_of_sums():
    """The error feature 11a exists to prevent, which each new rate can reintroduce."""
    for rate, numerator, denominator, small, large in EFFICIENCY_RATES:
        games = [
            game(1, **{numerator: small[0], denominator: small[1]}),
            game(2, **{numerator: large[0], denominator: large[1]}),
        ]
        expected = (small[0] + large[0]) / (small[1] + large[1])
        mean_of_ratios = (small[0] / small[1] + large[0] / large[1]) / 2
        values = window_values(games)
        assert values[rate] == expected, rate
        assert values[rate] != mean_of_ratios, rate


def test_every_efficiency_rate_is_null_without_a_denominator():
    for rate, numerator, denominator, _small, _large in EFFICIENCY_RATES:
        values = window_values([game(1, **{numerator: 5, denominator: 0})])
        assert values[rate] is None, rate


def test_every_efficiency_rate_is_null_when_the_metric_is_absent():
    """A receiver's window must not invent a passing rate out of nothing."""
    values = window_values([game(1)])
    for rate, *_ in EFFICIENCY_RATES:
        assert values[rate] is None, rate


def test_a_difference_numerator_sums_rather_than_averaging():
    """+2 over 10 targets and -1 over 20 is 1/30, not the mean of 0.2 and -0.05."""
    games = [
        game(1, catches_over_expected=2.0, cp_targets=10),
        game(2, catches_over_expected=-1.0, cp_targets=20),
    ]
    assert window_values(games)["croe"] == 1 / 30
    assert window_values(games)["croe"] != (0.2 + -0.05) / 2


def test_a_negative_over_expected_window_stays_negative():
    games = [game(1, catches_over_expected=-3.0, cp_targets=10)]
    assert window_values(games)["croe"] < 0


def test_efficiency_rates_use_the_same_prior_window_as_usage():
    """One boundary for the whole row, inherited from feature 11a."""
    history = [
        game(1, receiving_yards=100, routes=50),
        game(2, receiving_yards=0, routes=50),
    ]
    row = form_row("p", 2024, 2, history, UPDATED_AT)
    assert row["yprr_std"] == 2.0


def test_efficiency_rates_are_weighted_toward_recent_games():
    games = [
        game(1, receiving_yards=10, routes=50),
        game(2, receiving_yards=90, routes=50),
    ]
    weighted = ewma_values(games, half_life=1.0)["yprr"]
    assert weighted > window_values(games)["yprr"]


def test_form_columns_names_every_efficiency_rate_in_every_window():
    columns = set(form_columns())
    for rate, *_ in EFFICIENCY_RATES + [("ryoe_per_att",)]:
        for suffix in ("l3", "l5", "std", "ewma"):
            assert f"{rate}_{suffix}" in columns, f"{rate}_{suffix}"


# --- rush yards over expected, the one borrowed denominator ------------------


def test_attempts_are_recovered_from_the_two_published_figures():
    """NGS gives a total and a rate; their quotient is the count it divided by."""
    assert ryoe_attempts(30.0, 2.0) == 15.0


def test_a_negative_total_still_recovers_a_positive_count():
    assert ryoe_attempts(-30.0, -2.0) == 15.0


def test_a_zero_rate_recovers_nothing():
    """Zero over expected on a real workload, but the count is unrecoverable."""
    assert ryoe_attempts(0.0, 0.0) is None


def test_a_missing_rate_recovers_nothing():
    assert ryoe_attempts(30.0, None) is None


def test_a_missing_total_recovers_nothing():
    assert ryoe_attempts(None, 2.0) is None


def test_ryoe_is_weighted_by_ngs_attempts_not_our_carries():
    """The measured disagreement: 18 attempts against 25 carries on one 2024 game."""
    games = [
        game(1, carries=25, ryoe=36.0, ryoe_attempts=18.0),
        game(2, carries=10, ryoe=-6.0, ryoe_attempts=12.0),
    ]
    assert window_values(games)["ryoe_per_att"] == 30.0 / 30.0
    # What our carries would have given, which is a different number entirely.
    assert window_values(games)["ryoe_per_att"] != 30.0 / 35.0


def test_a_game_ngs_never_measured_is_left_out_of_the_window():
    """Under 10 carries NGS publishes nothing, so that game cannot join the average."""
    games = [
        game(1, carries=20, ryoe=20.0, ryoe_attempts=20.0),
        game(2, carries=4, ryoe=None, ryoe_attempts=None),
    ]
    assert window_values(games)["ryoe_per_att"] == 1.0


def test_ryoe_is_null_when_ngs_measured_nothing_in_the_window():
    assert window_values([game(1, carries=4)])["ryoe_per_att"] is None


# --- how big the RYOE sample was --------------------------------------------


def test_measured_games_counts_only_games_carrying_both_parts():
    games = [
        game(1, ryoe=10.0, ryoe_attempts=12.0),
        game(2, ryoe=None, ryoe_attempts=None),
        game(3, ryoe=5.0, ryoe_attempts=11.0),
    ]
    assert measured_games(games, "ryoe", "ryoe_attempts") == 2


def test_measured_games_of_an_empty_window_is_zero():
    assert measured_games([], "ryoe", "ryoe_attempts") == 0


def test_appearances_and_measured_games_can_disagree():
    """Sean Tucker, 2024: fifteen prior games, one of them measured."""
    history = [game(w, carries=4) for w in range(1, 16)]
    history.append(game(16, carries=20, ryoe=40.0, ryoe_attempts=20.0))
    row = form_row("p", 2024, 17, history, UPDATED_AT)
    assert row["games_std"] == 16
    assert row["ryoe_games_std"] == 1
    assert row["ryoe_per_att_std"] == 2.0


def test_a_window_ngs_never_measured_reports_zero_not_null():
    """games_std says he played; ryoe_games_std says nobody measured him."""
    row = form_row("p", 2024, 5, [game(w, carries=3) for w in range(1, 5)], UPDATED_AT)
    assert row["games_std"] == 4
    assert row["ryoe_games_std"] == 0
    assert row["ryoe_per_att_std"] is None


def test_the_sample_count_follows_its_own_window():
    history = [
        game(1, ryoe=10.0, ryoe_attempts=10.0),
        game(2, ryoe=10.0, ryoe_attempts=10.0),
        game(3, carries=2),
        game(4, carries=2),
    ]
    row = form_row("p", 2024, 5, history, UPDATED_AT)
    assert row["ryoe_games_std"] == 2
    assert row["ryoe_games_l3"] == 1   # weeks 2, 3 and 4; only week 2 measured


def test_form_columns_names_the_sample_counts():
    columns = set(form_columns())
    for suffix in ("l3", "l5", "std"):
        assert f"ryoe_games_{suffix}" in columns
    assert "ryoe_games_ewma" not in columns
