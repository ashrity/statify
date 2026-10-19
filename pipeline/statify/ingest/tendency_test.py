from statify.ingest.tendency import (
    aggregate_counts,
    charting_counts,
    columns,
    play_index,
    pressure_counts,
    tendency_row,
    tendency_rows,
)

BUF_WK1 = ("BUF", 1)


def play(play_id=1, game_id="G", week=1, season_type="REG", defteam="BUF",
         dropback=1, special=0, sack=0, qb_hit=0):
    return {
        "game_id": game_id,
        "play_id": play_id,
        "week": week,
        "season_type": season_type,
        "defteam": defteam,
        "qb_dropback": dropback,
        "special_teams_play": special,
        "sack": sack,
        "qb_hit": qb_hit,
    }


def charted(play_id=1, game_id="G", shell="ZONE_COVERAGE", rushers=4):
    return {
        "nflverse_game_id": game_id,
        "play_id": play_id,
        "defense_man_zone_type": shell,
        "number_of_pass_rushers": rushers,
    }


def counts_for(participation, plays):
    totals, skipped = charting_counts(participation, play_index(plays))
    return totals, skipped


# --- what counts as a snap --------------------------------------------------


def test_a_dropback_is_charted():
    totals, _ = counts_for([charted()], [play()])
    assert totals[BUF_WK1]["coverage_snaps"] == 1


def test_a_run_is_not_a_coverage_snap():
    totals, _ = counts_for([charted()], [play(dropback=0)])
    assert totals == {}


def test_special_teams_are_excluded():
    """Participation covers punts, where the charting describes a return unit."""
    totals, _ = counts_for([charted()], [play(special=1)])
    assert totals == {}


def test_preseason_is_excluded():
    totals, _ = counts_for([charted()], [play(season_type="PRE")])
    assert totals == {}


def test_a_participation_row_with_no_play_is_counted_as_skipped():
    """Measured at zero on 2024, so any number here means the feed moved."""
    totals, skipped = counts_for([charted(play_id=99)], [play(play_id=1)])
    assert totals == {}
    assert skipped["no matching play"] == 1


def test_a_play_we_chose_not_to_count_is_not_reported_as_missing():
    """A punt is an exclusion, not feed drift. Conflating them cried wolf 6,382 times."""
    for excluded in (play(special=1), play(season_type="PRE"), play(defteam=None)):
        _totals, skipped = counts_for([charted()], [excluded])
        assert skipped == {}


# --- coverage ---------------------------------------------------------------


def test_man_counts_toward_both_the_numerator_and_denominator():
    totals, _ = counts_for([charted(shell="MAN_COVERAGE")], [play()])
    assert totals[BUF_WK1]["coverage_snaps"] == 1
    assert totals[BUF_WK1]["man_snaps"] == 1


def test_zone_counts_toward_the_denominator_only():
    totals, _ = counts_for([charted(shell="ZONE_COVERAGE")], [play()])
    assert totals[BUF_WK1]["coverage_snaps"] == 1
    assert totals[BUF_WK1]["man_snaps"] == 0


def test_an_empty_shell_is_not_a_charted_snap():
    """The trap: 23,497 rows carry "" rather than NULL, and would halve man rate."""
    totals, _ = counts_for([charted(shell="")], [play()])
    assert totals[BUF_WK1]["coverage_snaps"] == 0


def test_a_null_shell_is_not_a_charted_snap():
    totals, _ = counts_for([charted(shell=None)], [play()])
    assert totals[BUF_WK1]["coverage_snaps"] == 0


def test_an_unrecognised_shell_is_not_a_charted_snap():
    totals, _ = counts_for([charted(shell="SOMETHING_NEW")], [play()])
    assert totals[BUF_WK1]["coverage_snaps"] == 0


# --- pass rushers -----------------------------------------------------------


def test_four_rushers_is_not_a_blitz():
    """Four is the base rush almost every front sends."""
    totals, _ = counts_for([charted(rushers=4)], [play()])
    assert totals[BUF_WK1]["rusher_snaps"] == 1
    assert totals[BUF_WK1]["blitz_snaps"] == 0


def test_five_rushers_is_a_blitz():
    totals, _ = counts_for([charted(rushers=5)], [play()])
    assert totals[BUF_WK1]["blitz_snaps"] == 1


def test_rushers_are_summed_for_the_mean():
    rows = [charted(play_id=1, rushers=4), charted(play_id=2, rushers=6)]
    plays = [play(play_id=1), play(play_id=2)]
    totals, _ = counts_for(rows, plays)
    assert totals[BUF_WK1]["pass_rushers"] == 10
    assert totals[BUF_WK1]["rusher_snaps"] == 2


def test_an_impossible_rusher_count_is_dropped_and_reported():
    """One 2024 row claims 45. A defense fields eleven players."""
    totals, skipped = counts_for([charted(rushers=45)], [play()])
    assert totals[BUF_WK1]["rusher_snaps"] == 0
    assert totals[BUF_WK1]["pass_rushers"] == 0
    assert skipped["pass rusher count out of range"] == 1


def test_zero_rushers_is_not_an_error():
    """A run play carries zero. It is not charted, and not a data problem."""
    totals, skipped = counts_for([charted(rushers=0)], [play()])
    assert totals[BUF_WK1]["rusher_snaps"] == 0
    assert skipped == {}


def test_a_missing_rusher_count_is_simply_absent():
    totals, skipped = counts_for([charted(rushers=None)], [play()])
    assert totals[BUF_WK1]["rusher_snaps"] == 0
    assert skipped == {}


# --- pressure, from play-by-play alone --------------------------------------


def test_dropbacks_sacks_and_hits_are_counted():
    totals = pressure_counts([play(play_id=1, sack=1, qb_hit=1), play(play_id=2)])
    assert totals[BUF_WK1] == dict(
        coverage_snaps=0, man_snaps=0, rusher_snaps=0, blitz_snaps=0,
        pass_rushers=0, dropbacks=2, sacks=1, qb_hits=1)


def test_a_run_is_not_a_dropback():
    assert pressure_counts([play(dropback=0)]) == {}


def test_pressure_needs_no_participation_row():
    """Sacks exist only in play-by-play, which is why both feeds are read."""
    totals = pressure_counts([play(sack=1)])
    assert totals[BUF_WK1]["sacks"] == 1


# --- accumulation -----------------------------------------------------------


def test_weeks_are_counted_separately():
    rows = [charted(play_id=1, game_id="G1"), charted(play_id=1, game_id="G2")]
    plays = [play(play_id=1, game_id="G1", week=1),
             play(play_id=1, game_id="G2", week=2)]
    totals, _ = counts_for(rows, plays)
    assert totals[("BUF", 1)]["coverage_snaps"] == 1
    assert totals[("BUF", 2)]["coverage_snaps"] == 1


def test_defenses_are_counted_separately():
    rows = [charted(play_id=1), charted(play_id=2)]
    plays = [play(play_id=1, defteam="BUF"), play(play_id=2, defteam="NYJ")]
    totals, _ = counts_for(rows, plays)
    assert set(totals) == {("BUF", 1), ("NYJ", 1)}


def test_both_feeds_land_in_one_row():
    totals, skipped = aggregate_counts([charted(shell="MAN_COVERAGE", rushers=6)],
                                       [play(sack=1, qb_hit=1)])
    assert totals[BUF_WK1] == dict(
        coverage_snaps=1, man_snaps=1, rusher_snaps=1, blitz_snaps=1,
        pass_rushers=6, dropbacks=1, sacks=1, qb_hits=1)
    assert skipped == {}


def test_no_input_yields_nothing():
    totals, skipped = aggregate_counts([], [])
    assert totals == {} and skipped == {}


# --- the weekly rates -------------------------------------------------------

UPDATED_AT = "2026-01-01T00:00:00+00:00"


def week_counts(**overrides):
    base = dict(coverage_snaps=0, man_snaps=0, rusher_snaps=0, blitz_snaps=0,
                pass_rushers=0, dropbacks=0, sacks=0, qb_hits=0)
    return {**base, **overrides}


def test_each_rate_divides_by_the_denominator_it_names():
    """Every count differs, so a swapped denominator cannot produce these answers."""
    row = tendency_row("BUF", 2024, 1, week_counts(
        coverage_snaps=40, man_snaps=10,
        rusher_snaps=50, blitz_snaps=20, pass_rushers=200,
        dropbacks=25, sacks=5, qb_hits=10), UPDATED_AT)
    assert row["man_rate"] == 10 / 40
    assert row["blitz_rate"] == 20 / 50
    assert row["pass_rushers_per_snap"] == 200 / 50
    assert row["sack_rate"] == 5 / 25
    assert row["qb_hit_rate"] == 10 / 25


def test_a_zero_denominator_is_null_not_zero():
    """A week with nothing charted has no man rate, which is not a rate of zero."""
    row = tendency_row("BUF", 2024, 1, week_counts(dropbacks=30), UPDATED_AT)
    assert row["man_rate"] is None
    assert row["blitz_rate"] is None
    assert row["pass_rushers_per_snap"] is None


def test_a_zero_numerator_is_zero_not_null():
    """A defense that charted snaps and never played man really did play 0% man."""
    row = tendency_row("BUF", 2024, 1, week_counts(coverage_snaps=30), UPDATED_AT)
    assert row["man_rate"] == 0.0


def test_one_feed_missing_does_not_null_the_other():
    """Coverage and pressure come from different places and fail independently."""
    row = tendency_row("BUF", 2024, 1,
                       week_counts(dropbacks=30, sacks=3), UPDATED_AT)
    assert row["man_rate"] is None
    assert row["sack_rate"] == 0.1


def test_the_counts_are_carried_through_beside_the_rates():
    """coverage_snaps is the sample size; a rate without it invites overreading."""
    row = tendency_row("BUF", 2024, 1, week_counts(coverage_snaps=14, man_snaps=7),
                       UPDATED_AT)
    assert row["coverage_snaps"] == 14 and row["man_snaps"] == 7
    assert row["man_rate"] == 0.5


# --- trailing windows -------------------------------------------------------


def season_counts(*weeks):
    """(week, coverage_snaps, man_snaps) tuples into the shape tendency_rows wants."""
    return {("BUF", w): week_counts(coverage_snaps=c, man_snaps=m,
                                    rusher_snaps=c, blitz_snaps=m,
                                    pass_rushers=c, dropbacks=c, sacks=m, qb_hits=m)
            for w, c, m in weeks}


def rows_by_week(totals):
    return {r["week"]: r for r in tendency_rows(totals, 2024, UPDATED_AT)}


def test_a_weeks_own_result_is_absent_from_its_own_window():
    """Inherited from feature 11a, asserted here because leakage is invisible."""
    rows = rows_by_week(season_counts((1, 10, 1), (2, 10, 9)))
    assert rows[2]["weeks_std"] == 1
    assert rows[2]["man_rate_std"] == 0.1      # week 1 only


def test_a_first_week_has_no_window():
    rows = rows_by_week(season_counts((1, 10, 5)))
    assert rows[1]["weeks_std"] == 0
    assert rows[1]["man_rate_std"] is None
    assert rows[1]["man_rate"] == 0.5          # the week itself is still measured


def test_a_bye_is_a_missing_week_not_a_zero():
    """Weeks 4, 5, 7, 8 entering week 9: the last three are 5, 7 and 8."""
    rows = rows_by_week(season_counts((4, 10, 1), (5, 10, 2), (7, 10, 3),
                                      (8, 10, 4), (9, 10, 5)))
    assert rows[9]["weeks_l3"] == 3
    assert rows[9]["man_rate_l3"] == 9 / 30    # weeks 5, 7 and 8


def test_a_window_is_a_ratio_of_sums_not_a_mean_of_rates():
    """A 14-snap week must not weigh the same as a 63-snap one; 2024 has both."""
    rows = rows_by_week(season_counts((1, 10, 5), (2, 40, 4), (3, 10, 0)))
    assert rows[3]["man_rate_std"] == 9 / 50
    assert rows[3]["man_rate_std"] != (0.5 + 0.1) / 2


def test_the_windows_narrow_as_they_should():
    rows = rows_by_week(season_counts(*[(w, 10, 5) for w in range(1, 8)]))
    assert rows[7]["weeks_l3"] == 3
    assert rows[7]["weeks_l5"] == 5
    assert rows[7]["weeks_std"] == 6


def test_every_window_column_is_present_on_every_row():
    rows = rows_by_week(season_counts((1, 10, 5)))
    for name in ("man_rate", "blitz_rate", "pass_rushers_per_snap",
                 "sack_rate", "qb_hit_rate"):
        for suffix in ("l3", "l5", "std"):
            assert f"{name}_{suffix}" in rows[1], f"{name}_{suffix}"


def test_defenses_do_not_share_a_history():
    totals = {("BUF", 1): week_counts(coverage_snaps=10, man_snaps=10),
              ("NYJ", 1): week_counts(coverage_snaps=10, man_snaps=0),
              ("BUF", 2): week_counts(coverage_snaps=10, man_snaps=5)}
    rows = {(r["team_abbr"], r["week"]): r for r in tendency_rows(totals, 2024, UPDATED_AT)}
    assert rows[("BUF", 2)]["man_rate_std"] == 1.0


def test_no_counts_produce_no_rows():
    assert tendency_rows({}, 2024, UPDATED_AT) == []


def test_the_statement_and_the_row_carry_the_same_columns():
    """Generated SQL, so a column in one and not the other is silent."""
    row = tendency_rows(season_counts((1, 10, 5)), 2024, UPDATED_AT)[0]
    assert set(columns()) == set(row)
