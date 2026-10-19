from statify.ingest.market import (
    book_rows,
    event_rows,
    implied_team_total,
    in_week,
    is_new_capture,
    market_points,
    resolve_slate,
)

TEAM_ABBRS = {"San Francisco 49ers": "SF", "Washington Commanders": "WAS"}
CAPTURED_AT = "2026-10-19T22:00:00+00:00"
UPDATED_AT = "2026-10-19T22:00:00+00:00"


def spreads(home=-7.5, away=7.5):
    return {"key": "spreads", "outcomes": [
        {"name": "San Francisco 49ers", "point": home, "price": -102},
        {"name": "Washington Commanders", "point": away, "price": -118},
    ]}


def totals(point=52.5):
    return {"key": "totals", "outcomes": [
        {"name": "Over", "point": point, "price": -105},
        {"name": "Under", "point": point, "price": -115},
    ]}


def book(key="draftkings", markets=None):
    return {"key": key, "markets": [spreads(), totals()] if markets is None else markets}


def by_team(rows):
    return {r["team_abbr"]: r for r in rows}


# --- the arithmetic ---------------------------------------------------------


def test_the_measured_example():
    """San Francisco at -7.5 on a 52.5 total, straight from the live feed."""
    assert implied_team_total(52.5, -7.5) == 30.0
    assert implied_team_total(52.5, 7.5) == 22.5


def test_the_two_sides_sum_to_the_game_total():
    """A sign error gives two plausible numbers that fail exactly this."""
    assert implied_team_total(52.5, -7.5) + implied_team_total(52.5, 7.5) == 52.5


def test_a_pick_em_splits_the_total_evenly():
    assert implied_team_total(44.0, 0.0) == 22.0


def test_a_missing_total_has_no_implied_total():
    assert implied_team_total(None, -3.5) is None


def test_a_missing_spread_has_no_implied_total():
    assert implied_team_total(47.0, None) is None


def test_a_big_favourite_still_sums():
    assert implied_team_total(38.0, -14.0) + implied_team_total(38.0, 14.0) == 38.0


# --- reading one book -------------------------------------------------------


def test_spreads_and_the_total_are_both_read():
    found, total = market_points(book())
    assert found == {"San Francisco 49ers": -7.5, "Washington Commanders": 7.5}
    assert total == 52.5


def test_the_total_comes_from_either_outcome():
    """Over and Under carry the same point, so the first one found is enough."""
    _found, total = market_points({"key": "x", "markets": [totals(49.0)]})
    assert total == 49.0


def test_a_book_with_no_markets_yields_nothing():
    assert market_points({"key": "x"}) == ({}, None)
    assert book_rows({"key": "x"}, TEAM_ABBRS) == []


def test_an_outcome_with_no_point_is_skipped():
    markets = [{"key": "spreads", "outcomes": [{"name": "San Francisco 49ers"}]}]
    assert market_points({"key": "x", "markets": markets}) == ({}, None)


# --- the two rows a book contributes ----------------------------------------


def test_a_book_contributes_one_row_per_team():
    rows = by_team(book_rows(book(), TEAM_ABBRS))
    assert set(rows) == {"SF", "WAS"}
    assert rows["SF"]["spread"] == -7.5
    assert rows["SF"]["game_total"] == 52.5
    assert rows["SF"]["implied_team_total"] == 30.0


def test_the_favourite_gets_the_larger_implied_total():
    rows = by_team(book_rows(book(), TEAM_ABBRS))
    assert rows["SF"]["spread"] < rows["WAS"]["spread"]
    assert rows["SF"]["implied_team_total"] > rows["WAS"]["implied_team_total"]


def test_a_missing_totals_market_keeps_the_spread():
    """Books post the two separately; losing the spread we have would be worse."""
    rows = by_team(book_rows(book(markets=[spreads()]), TEAM_ABBRS))
    assert rows["SF"]["spread"] == -7.5
    assert rows["SF"]["game_total"] is None
    assert rows["SF"]["implied_team_total"] is None


def test_a_missing_spreads_market_yields_no_rows():
    """There would be no team to attach the implied total to."""
    assert book_rows(book(markets=[totals()]), TEAM_ABBRS) == []


def test_an_unknown_team_name_yields_no_row():
    """A row with no team is worse than a missing row; the FK would reject it anyway."""
    rows = book_rows(book(), {"San Francisco 49ers": "SF"})
    assert [r["team_abbr"] for r in rows] == ["SF"]


def test_the_book_key_is_carried():
    assert book_rows(book(key="fanduel"), TEAM_ABBRS)[0]["book"] == "fanduel"


# --- assembling an event ----------------------------------------------------


def event(bookmakers=None):
    return {"bookmakers": [book("draftkings"), book("fanduel")]
            if bookmakers is None else bookmakers}


def test_every_book_contributes_two_rows():
    rows = event_rows(event(), "2026_07_WAS_SF", 2026, 7, TEAM_ABBRS,
                      CAPTURED_AT, UPDATED_AT)
    assert len(rows) == 4
    assert {r["book"] for r in rows} == {"draftkings", "fanduel"}
    assert {r["team_abbr"] for r in rows} == {"SF", "WAS"}


def test_the_game_identity_is_stamped_on_every_row():
    rows = event_rows(event(), "2026_07_WAS_SF", 2026, 7, TEAM_ABBRS,
                      CAPTURED_AT, UPDATED_AT)
    for row in rows:
        assert row["game_id"] == "2026_07_WAS_SF"
        assert row["season"] == 2026 and row["week"] == 7
        assert row["captured_at"] == CAPTURED_AT


def test_an_event_with_no_books_yields_nothing():
    assert event_rows({}, "G", 2026, 7, TEAM_ABBRS, CAPTURED_AT, UPDATED_AT) == []


def test_books_disagreeing_produce_different_rows():
    """Nine books rarely post the identical line; each keeps its own."""
    other = {"key": "betmgm", "markets": [spreads(home=-8.0, away=8.0), totals(53.0)]}
    rows = event_rows(event([book("draftkings"), other]), "G", 2026, 7,
                      TEAM_ABBRS, CAPTURED_AT, UPDATED_AT)
    sf = {r["book"]: r for r in rows if r["team_abbr"] == "SF"}
    assert sf["draftkings"]["implied_team_total"] == 30.0
    assert sf["betmgm"]["implied_team_total"] == 30.5


# --- placing a slate --------------------------------------------------------

GAMES = {
    ("SF", "WAS"): [("2026_07_WAS_SF", "2026-10-20T00:15:00+00:00", 2026, 7)],
    ("CHI", "NE"): [("2026_08_NE_CHI", "2026-10-23T00:15:00+00:00", 2026, 8)],
}
SLATE_ABBRS = {
    "San Francisco 49ers": "SF", "Washington Commanders": "WAS",
    "Chicago Bears": "CHI", "New England Patriots": "NE",
}


def slate_event(home="San Francisco 49ers", away="Washington Commanders",
                commence="2026-10-20T00:15:00Z"):
    return {"home_team": home, "away_team": away, "commence_time": commence}


def test_a_known_matchup_resolves_to_its_game():
    matched, unresolved = resolve_slate([slate_event()], SLATE_ABBRS, GAMES)
    assert unresolved == []
    assert matched[0][1] == ("2026_07_WAS_SF", 2026, 7)


def test_an_unknown_matchup_is_named_rather_than_dropped():
    """A quietly missing game is worse than a noisy one."""
    event = slate_event(home="Toronto Argonauts", away="Washington Commanders")
    matched, unresolved = resolve_slate([event], SLATE_ABBRS, GAMES)
    assert matched == []
    assert unresolved == ["Washington Commanders @ Toronto Argonauts"]


def test_a_season_with_no_games_resolves_nothing_and_says_so():
    """The first-run case: schedules never ingested for this season."""
    matched, unresolved = resolve_slate([slate_event(), slate_event(
        home="Chicago Bears", away="New England Patriots",
        commence="2026-10-23T00:15:00Z")], SLATE_ABBRS, {})
    assert matched == []
    assert len(unresolved) == 2


def test_week_filtering_narrows_what_is_stored():
    events = [slate_event(),
              slate_event(home="Chicago Bears", away="New England Patriots",
                          commence="2026-10-23T00:15:00Z")]
    matched, _ = resolve_slate(events, SLATE_ABBRS, GAMES)
    assert len(matched) == 2
    assert [p[1][2] for p in in_week(matched, 7)] == [7]
    assert len(in_week(matched, None)) == 2


def test_a_week_with_nothing_on_the_slate_is_empty_not_everything():
    matched, _ = resolve_slate([slate_event()], SLATE_ABBRS, GAMES)
    assert in_week(matched, 12) == []


# --- novelty is decided by content, not by the clock ------------------------


def stored_row(spread=-7.5, total=52.5, team="SF", book_key="draftkings"):
    return {"game_id": "G", "team_abbr": team, "book": book_key,
            "spread": spread, "game_total": total}


def test_an_unseen_line_is_new():
    assert is_new_capture(stored_row(), {}) is True


def test_an_unchanged_line_is_not_new():
    """Two runs minutes apart carry different clocks and the same facts."""
    latest = {("G", "SF", "draftkings"): (-7.5, 52.5)}
    assert is_new_capture(stored_row(), latest) is False


def test_a_moved_spread_is_new():
    latest = {("G", "SF", "draftkings"): (-7.5, 52.5)}
    assert is_new_capture(stored_row(spread=-8.0), latest) is True


def test_a_moved_total_is_new():
    latest = {("G", "SF", "draftkings"): (-7.5, 52.5)}
    assert is_new_capture(stored_row(total=53.0), latest) is True


def test_each_book_is_judged_separately():
    """One book moving must not suppress another that also moved."""
    latest = {("G", "SF", "draftkings"): (-7.5, 52.5)}
    assert is_new_capture(stored_row(book_key="fanduel"), latest) is True


def test_each_team_is_judged_separately():
    latest = {("G", "SF", "draftkings"): (-7.5, 52.5)}
    assert is_new_capture(stored_row(team="WAS", spread=7.5), latest) is True
