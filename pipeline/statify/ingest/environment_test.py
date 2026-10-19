from statify.ingest.environment import (
    consensus,
    latest_per_book,
    environment_rows,
    median,
    opponent_of,
    tempo_history_row,
    trailing_tempo,
)


def line(book="draftkings", spread=-3.0, total=50.0, captured="2026-10-19T22:00:00+00:00"):
    return {"book": book, "spread": spread, "game_total": total, "captured_at": captured}


# --- the median -------------------------------------------------------------


def test_an_odd_count_takes_the_middle():
    assert median([1.0, 5.0, 3.0]) == 3.0


def test_an_even_count_averages_the_middle_two():
    assert median([1.0, 2.0, 3.0, 4.0]) == 2.5


def test_a_single_value_is_its_own_median():
    assert median([7.5]) == 7.5


def test_nothing_has_no_median():
    assert median([]) is None


def test_negatives_order_correctly():
    """Spreads are negative for favourites; a string sort would ruin this."""
    assert median([-7.5, -3.0, -10.0]) == -7.5


# --- one row per book -------------------------------------------------------


def test_the_latest_capture_wins_per_book():
    rows = [line(captured="2026-10-19T10:00:00+00:00", spread=-2.0),
            line(captured="2026-10-19T22:00:00+00:00", spread=-3.5)]
    assert [r["spread"] for r in latest_per_book(rows)] == [-3.5]


def test_each_book_keeps_its_own_latest():
    rows = [line(book="a", spread=-2.0), line(book="b", spread=-4.0)]
    assert {r["spread"] for r in latest_per_book(rows)} == {-2.0, -4.0}


def test_a_book_that_moved_often_still_counts_once():
    """Otherwise the consensus would weight whichever book moved most."""
    rows = [line(captured=f"2026-10-19T0{n}:00:00+00:00") for n in range(1, 6)]
    assert len(latest_per_book(rows)) == 1


# --- the consensus ----------------------------------------------------------


def test_nine_books_agreeing_give_that_line():
    rows = [line(book=str(n), spread=-7.5, total=52.5) for n in range(9)]
    result = consensus(rows)
    assert result["spread"] == -7.5
    assert result["game_total"] == 52.5
    assert result["implied_team_total"] == 30.0
    assert result["books"] == 9


def test_a_single_stale_book_does_not_move_the_total():
    """Eight at 52.5 and one at 44.0 is a stale book, not a 47.6-point game."""
    rows = [line(book=str(n), total=52.5) for n in range(8)] + [line(book="stale", total=44.0)]
    assert consensus(rows)["game_total"] == 52.5
    assert sum(r["game_total"] for r in rows) / len(rows) != 52.5


def test_the_implied_total_is_derived_not_a_third_median():
    """Three independent medians need not satisfy total/2 - spread/2.

    Books at (-1, 40), (-10, 50) and (-3, 60) imply 20.5, 30.0 and 31.5. The
    median of those is 30.0, but the consensus spread is -3 and the consensus
    total 50, which give 26.5. Only the derived value keeps the identity that
    the two teams' implied totals sum to the game total.
    """
    rows = [line(book="a", spread=-1.0, total=40.0),
            line(book="b", spread=-10.0, total=50.0),
            line(book="c", spread=-3.0, total=60.0)]
    result = consensus(rows)
    assert result["spread"] == -3.0 and result["game_total"] == 50.0
    assert result["implied_team_total"] == 26.5
    assert result["implied_team_total"] != 30.0


def test_the_two_sides_of_a_game_still_sum_to_the_total():
    """The property the derived value exists to preserve."""
    books = [("a", -1.0, 40.0), ("b", -10.0, 50.0), ("c", -3.0, 60.0)]
    home = consensus([line(book=b, spread=s, total=t) for b, s, t in books])
    away = consensus([line(book=b, spread=-s, total=t) for b, s, t in books])
    assert home["implied_team_total"] + away["implied_team_total"] == home["game_total"]


def test_no_books_give_nulls_rather_than_zeros():
    result = consensus([])
    assert result["spread"] is None
    assert result["game_total"] is None
    assert result["implied_team_total"] is None
    assert result["books"] == 0
    assert result["market_captured_at"] is None


def test_the_capture_time_is_the_most_recent_any_book_posted():
    rows = [line(book="a", captured="2026-10-19T10:00:00+00:00"),
            line(book="b", captured="2026-10-19T22:00:00+00:00")]
    assert consensus(rows)["market_captured_at"] == "2026-10-19T22:00:00+00:00"


def test_a_book_missing_the_total_still_counts_toward_the_spread():
    """Books post the two markets separately; one gap must not discard both."""
    rows = [line(book="a", total=None), line(book="b", total=50.0), line(book="c", total=50.0)]
    result = consensus(rows)
    assert result["game_total"] == 50.0
    assert result["spread"] == -3.0
    assert result["books"] == 3


# --- trailing pace and PROE -------------------------------------------------


def tempo(week, pace=35.0, intervals=20, proe=0.0, plays=60):
    return tempo_history_row({"week": week, "neutral_seconds_per_play": pace,
                              "neutral_intervals": intervals, "proe": proe, "plays": plays})


def test_a_weeks_own_tempo_is_absent_from_its_own_row():
    """Leakage here would describe the game being projected."""
    history = [tempo(1, pace=30.0), tempo(2, pace=99.0)]
    assert trailing_tempo(history, 2)["pace"] == 30.0


def test_a_first_week_has_no_trailing_tempo():
    values = trailing_tempo([tempo(1)], 1)
    assert values["pace"] is None and values["proe"] is None
    assert values["pace_weeks"] == 0 and values["proe_weeks"] == 0


def test_pace_is_weighted_by_intervals_not_averaged():
    """A blowout with 4 neutral snaps must not weigh the same as 30."""
    history = [tempo(1, pace=40.0, intervals=4), tempo(2, pace=30.0, intervals=30)]
    pace = trailing_tempo(history, 3)["pace"]
    assert pace == (40.0 * 4 + 30.0 * 30) / 34
    assert pace != 35.0


def test_proe_is_weighted_by_plays():
    history = [tempo(1, proe=10.0, plays=20), tempo(2, proe=-2.0, plays=60)]
    proe = trailing_tempo(history, 3)["proe"]
    assert proe == (10.0 * 20 + -2.0 * 60) / 80
    assert proe != 4.0


def test_a_bye_is_a_missing_week_not_a_zero():
    history = [tempo(w) for w in (1, 2, 4, 5)]
    assert trailing_tempo(history, 6)["pace_weeks"] == 4


def test_a_week_with_no_neutral_snaps_is_skipped_for_pace_only():
    """A blowout can leave no situation-neutral snaps; PROE survives it."""
    history = [tempo(1, pace=None, intervals=0), tempo(2, pace=30.0, intervals=20)]
    history[0]["neutral_seconds"] = None
    values = trailing_tempo(history, 3)
    assert values["pace"] == 30.0
    assert values["pace_weeks"] == 1
    assert values["proe_weeks"] == 2


def test_later_weeks_never_leak_backwards():
    history = [tempo(1, pace=30.0), tempo(5, pace=40.0), tempo(9, pace=50.0)]
    assert trailing_tempo(history, 5)["pace"] == 30.0


def test_a_negative_proe_survives():
    """PROE is a deviation and is negative for run-heavy teams."""
    assert trailing_tempo([tempo(1, proe=-8.0)], 2)["proe"] == -8.0


# --- assembling the row -----------------------------------------------------

UPDATED_AT = "2026-10-19T23:00:00+00:00"
GAME = {"game_id": "2026_07_CIN_BAL", "season": 2026, "week": 7,
        "home_team": "BAL", "away_team": "CIN"}


def histories_for(bal_pace=36.0, cin_pace=37.0):
    return {"BAL": [tempo(w, pace=bal_pace) for w in range(1, 7)],
            "CIN": [tempo(w, pace=cin_pace) for w in range(1, 7)]}


def test_the_opponent_is_the_other_side():
    assert opponent_of(GAME, "BAL") == "CIN"
    assert opponent_of(GAME, "CIN") == "BAL"


def test_a_team_is_never_its_own_opponent():
    for team in ("BAL", "CIN"):
        assert opponent_of(GAME, team) != team


def test_opponent_pace_is_the_other_teams_own_pace():
    rows = {r["team_abbr"]: r for r in
            environment_rows([GAME], {}, histories_for(), UPDATED_AT)}
    assert rows["BAL"]["pace"] == 36.0
    assert rows["BAL"]["opponent_pace"] == rows["CIN"]["pace"] == 37.0
    assert rows["CIN"]["opponent_pace"] == 36.0


def test_two_rows_per_game():
    rows = environment_rows([GAME], {}, histories_for(), UPDATED_AT)
    assert len(rows) == 2
    assert {r["team_abbr"] for r in rows} == {"BAL", "CIN"}


def test_a_game_with_no_market_still_gets_its_pace_half():
    """Past weeks can never have a line; feature 23 still wants the pace."""
    rows = environment_rows([GAME], {}, histories_for(), UPDATED_AT)
    for row in rows:
        assert row["implied_team_total"] is None and row["books"] == 0
        assert row["pace"] is not None and row["pace_weeks"] == 6


def test_a_missing_opponent_history_does_not_null_the_own_side():
    """The two halves fail independently."""
    rows = {r["team_abbr"]: r for r in environment_rows(
        [GAME], {}, {"BAL": [tempo(w) for w in range(1, 7)]}, UPDATED_AT)}
    assert rows["BAL"]["pace"] is not None
    assert rows["BAL"]["opponent_pace"] is None
    assert rows["CIN"]["pace"] is None
    assert rows["CIN"]["opponent_pace"] is not None


def test_the_market_attaches_to_the_right_team():
    market = {("2026_07_CIN_BAL", "BAL"): [line(spread=-2.5, total=51.0)],
              ("2026_07_CIN_BAL", "CIN"): [line(spread=2.5, total=51.0)]}
    rows = {r["team_abbr"]: r for r in
            environment_rows([GAME], market, histories_for(), UPDATED_AT)}
    assert rows["BAL"]["implied_team_total"] == 26.75
    assert rows["CIN"]["implied_team_total"] == 24.25
    assert rows["BAL"]["implied_team_total"] + rows["CIN"]["implied_team_total"] == 51.0


def test_no_games_produce_no_rows():
    assert environment_rows([], {}, {}, UPDATED_AT) == []
