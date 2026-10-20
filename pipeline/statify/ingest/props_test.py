from datetime import datetime, timezone

import pytest

from statify.ingest.props import (
    ALL_MARKETS,
    closing_ids,
    BINARY_MARKET_STAT_TYPES,
    MARKET_STAT_TYPES,
    assert_within_budget,
    build_player_index,
    estimate_credits,
    is_new_capture,
    normalize_name,
    outcome_names,
    prop_rows,
    resolve_event,
    resolve_players,
)


@pytest.mark.parametrize(
    "given,expected",
    [
        ("A.J. Brown", "aj brown"),
        ("AJ Brown", "aj brown"),
        ("Michael Pittman Jr.", "michael pittman"),
        ("Michael Pittman", "michael pittman"),
        ("Jaxon Smith-Njigba", "jaxon smith njigba"),
        ("Ja'Marr Chase", "jamarr chase"),
        ("  Travis   Kelce  ", "travis kelce"),
        ("Amon-Ra St. Brown", "amon ra st brown"),
        ("Marvin Harrison III", "marvin harrison"),
    ],
)
def test_normalize_name(given, expected):
    assert normalize_name(given) == expected


def test_normalize_handles_missing():
    assert normalize_name(None) == ""
    assert normalize_name("") == ""


def test_different_players_do_not_collapse():
    """Normalization must fold spelling, never distinct people."""
    assert normalize_name("Josh Allen") != normalize_name("Keenan Allen")
    assert normalize_name("Justin Jefferson") != normalize_name("Van Jefferson")


def test_exact_match_resolves():
    index = build_player_index([("00-0034844", "Saquon Barkley")])
    matched, unmatched, ambiguous = resolve_players(["Saquon Barkley"], index)
    assert matched == {"Saquon Barkley": "00-0034844"}
    assert unmatched == [] and ambiguous == []


def test_spelling_difference_still_resolves():
    index = build_player_index([("00-0036389", "A.J. Brown")])
    matched, _, _ = resolve_players(["AJ Brown"], index)
    assert matched == {"AJ Brown": "00-0036389"}


def test_unknown_name_is_unmatched_not_guessed():
    index = build_player_index([("00-0034844", "Saquon Barkley")])
    matched, unmatched, ambiguous = resolve_players(["Some Practice Squad Guy"], index)
    assert matched == {} and ambiguous == []
    assert unmatched == ["Some Practice Squad Guy"]


def test_shared_name_is_refused_not_picked():
    """The most important test here: two Josh Allens must resolve to neither."""
    index = build_player_index(
        [("00-0034857", "Josh Allen"), ("00-0035704", "Josh Allen")]
    )
    matched, unmatched, ambiguous = resolve_players(["Josh Allen"], index)
    assert matched == {} and unmatched == []
    assert ambiguous == ["Josh Allen"]


def test_suffix_collision_is_caught_as_ambiguous():
    """Dropping 'Jr' is only safe because a real collision surfaces here."""
    index = build_player_index(
        [("00-0001", "Odell Beckham Jr."), ("00-0002", "Odell Beckham")]
    )
    _, _, ambiguous = resolve_players(["Odell Beckham"], index)
    assert ambiguous == ["Odell Beckham"]


TEAMS = {"Seattle Seahawks": "SEA", "New England Patriots": "NE"}
GAMES = {
    ("SEA", "NE"): [("2026_01_NE_SEA", "2026-09-10T00:20:00+00:00", 2026, 1)],
}


def event(**overrides):
    base = {
        "home_team": "Seattle Seahawks",
        "away_team": "New England Patriots",
        "commence_time": "2026-09-10T00:20:00Z",
    }
    return {**base, **overrides}


def test_event_resolves_to_game():
    assert resolve_event(event(), TEAMS, GAMES) == ("2026_01_NE_SEA", 2026, 1)


def test_small_kickoff_difference_still_resolves():
    """Books and the schedule disagree by minutes, which is not a different game."""
    assert resolve_event(event(commence_time="2026-09-10T00:35:00Z"), TEAMS, GAMES)[0] == "2026_01_NE_SEA"


def test_unknown_team_is_not_guessed():
    assert resolve_event(event(home_team="Toronto Argonauts"), TEAMS, GAMES) is None


def test_wrong_week_does_not_resolve():
    """A rematch months later must not attach to this game."""
    assert resolve_event(event(commence_time="2026-12-10T00:20:00Z"), TEAMS, GAMES) is None


def test_rematch_picks_the_nearer_kickoff():
    """Division rivals meet twice, so the matchup alone is not a key."""
    games = {
        ("SEA", "NE"): [
            ("2026_01_NE_SEA", "2026-09-10T00:20:00+00:00", 2026, 1),
            ("2026_14_NE_SEA", "2026-12-06T18:00:00+00:00", 2026, 14),
        ]
    }
    assert resolve_event(event(commence_time="2026-12-06T18:05:00Z"), TEAMS, games)[2] == 14


def test_outcome_names_ignores_unmapped_markets():
    """player_anytime_td used to be the example here. Feature 7b made it a
    market we model, so the case needs one we genuinely do not."""
    payload = {
        "bookmakers": [
            {
                "markets": [
                    {"key": "player_receptions", "outcomes": [{"description": "A"}]},
                    {"key": "player_sacks", "outcomes": [{"description": "B"}]},
                ]
            }
        ]
    }
    assert outcome_names(payload) == ["A"]


def test_estimate_is_events_times_markets():
    assert estimate_credits(16, 4) == 64


def test_estimate_of_an_empty_slate_is_free():
    assert estimate_credits(0, 4) == 0


def test_budget_allows_a_run_that_clears_the_floor():
    assert_within_budget(estimate=64, remaining=421, floor=50)


def test_budget_allows_a_run_landing_exactly_on_the_floor():
    assert_within_budget(estimate=100, remaining=150, floor=50)


def test_budget_refuses_a_run_that_breaches_the_floor():
    with pytest.raises(RuntimeError, match="short by 1"):
        assert_within_budget(estimate=100, remaining=149, floor=50)


def test_refusal_names_the_numbers():
    with pytest.raises(RuntimeError) as exc:
        assert_within_budget(estimate=64, remaining=60, floor=50)
    message = str(exc.value)
    assert "64 credits needed" in message and "60 remaining" in message


def test_unknown_balance_does_not_block():
    """A missing header is a transient gap, not a reason to stop working."""
    assert_within_budget(estimate=1000, remaining=None, floor=50)


MATCHED = {"Jaxon Smith-Njigba": "00-0038542", "A.J. Brown": "00-0036389"}


def payload(outcomes, market="player_reception_yds", last_update="2026-09-05T02:35:52Z"):
    return {
        "bookmakers": [
            {"key": "draftkings", "markets": [
                {"key": market, "last_update": last_update, "outcomes": outcomes}
            ]}
        ]
    }


def test_over_and_under_collapse_into_one_row():
    rows = prop_rows(payload([
        {"name": "Over", "description": "A.J. Brown", "price": -111, "point": 60.5},
        {"name": "Under", "description": "A.J. Brown", "price": -113, "point": 60.5},
    ]), "G1", 2026, 1, MATCHED, "U")
    assert len(rows) == 1
    row = rows[0]
    assert row["line"] == 60.5
    assert row["over_odds"] == -111 and row["under_odds"] == -113
    assert row["stat_type"] == "receiving_yards" and row["book"] == "draftkings"


def test_captured_at_is_the_run_clock_not_the_book():
    """The book's last_update tracks republishing, not price movement.

    Keying on it produced 433 identical duplicate rows across two runs a minute
    apart, so the run's own clock is stored and duplication is prevented by
    comparing content instead.
    """
    rows = prop_rows(payload([
        {"name": "Over", "description": "A.J. Brown", "price": -111, "point": 60.5},
    ]), "G1", 2026, 1, MATCHED, "2026-09-05T09:00:00+00:00")
    assert rows[0]["captured_at"] == "2026-09-05T09:00:00+00:00"


def test_a_lone_side_still_stores():
    rows = prop_rows(payload([
        {"name": "Over", "description": "A.J. Brown", "price": -111, "point": 60.5},
    ]), "G1", 2026, 1, MATCHED, "U")
    assert rows[0]["over_odds"] == -111 and rows[0]["under_odds"] is None


def test_different_points_are_two_lines_not_one():
    """Merging them would invent a line the book never offered."""
    rows = prop_rows(payload([
        {"name": "Over", "description": "A.J. Brown", "price": -111, "point": 60.5},
        {"name": "Under", "description": "A.J. Brown", "price": -113, "point": 62.5},
    ]), "G1", 2026, 1, MATCHED, "U")
    assert len(rows) == 2
    assert sorted(r["line"] for r in rows) == [60.5, 62.5]


def test_unmatched_player_is_not_stored():
    rows = prop_rows(payload([
        {"name": "Over", "description": "Nobody At All", "price": -111, "point": 60.5},
    ]), "G1", 2026, 1, MATCHED, "U")
    assert rows == []


def test_unmapped_market_is_skipped():
    """A market we do not model at all. player_anytime_td used to be one of
    these; feature 7b gave it a path, so the case needs a different market."""
    rows = prop_rows(payload([
        {"name": "Yes", "description": "A.J. Brown", "price": 165},
    ], market="player_sacks"), "G1", 2026, 1, MATCHED, "U")
    assert rows == []


def test_outcome_without_a_point_is_skipped():
    """Anytime TD has no point; nothing else should reach here without one."""
    rows = prop_rows(payload([
        {"name": "Over", "description": "A.J. Brown", "price": 165},
    ]), "G1", 2026, 1, MATCHED, "U")
    assert rows == []


def test_a_market_the_book_never_timestamped_still_stores():
    """last_update is no longer read, so its absence must not lose a real line."""
    rows = prop_rows(payload([
        {"name": "Over", "description": "A.J. Brown", "price": -111, "point": 60.5},
        {"name": "Under", "description": "A.J. Brown", "price": -113, "point": 60.5},
    ], last_update=None), "G1", 2026, 1, MATCHED, "U")
    assert len(rows) == 1 and rows[0]["line"] == 60.5


LATEST = {("00-0036389", "G1", "receiving_yards", "draftkings"): (60.5, -111, -113)}


def line_row(line=60.5, over=-111, under=-113):
    return {"player_id": "00-0036389", "game_id": "G1", "stat_type": "receiving_yards",
            "book": "draftkings", "line": line, "over_odds": over, "under_odds": under}


def test_unchanged_line_is_not_a_new_capture():
    """The bug this guards: books republish constantly without moving a price."""
    assert is_new_capture(line_row(), LATEST) is False


def test_moved_line_is_a_new_capture():
    assert is_new_capture(line_row(line=62.5), LATEST) is True


def test_moved_juice_alone_is_a_new_capture():
    """The number can hold while the price moves; that is still information."""
    assert is_new_capture(line_row(over=-120), LATEST) is True
    assert is_new_capture(line_row(under=-105), LATEST) is True


def test_first_sighting_is_always_a_new_capture():
    assert is_new_capture(line_row(), {}) is True


def test_a_different_book_is_tracked_separately():
    row = line_row()
    row["book"] = "fanduel"
    assert is_new_capture(row, LATEST) is True


# --- the binary touchdown market (feature 7b) -------------------------------


def td_payload(outcomes, book="draftkings"):
    return {"bookmakers": [{"key": book, "markets": [
        {"key": "player_anytime_td", "outcomes": outcomes}]}]}


def test_a_yes_outcome_becomes_an_over_price_at_half_a_touchdown():
    """point is None on every outcome, which the over/under builder drops."""
    rows = prop_rows(td_payload([
        {"name": "Yes", "description": "A.J. Brown", "price": 125, "point": None},
    ]), "G1", 2026, 1, MATCHED, "U")
    assert len(rows) == 1
    assert rows[0]["stat_type"] == "touchdowns"
    assert rows[0]["line"] == 0.5
    assert rows[0]["over_odds"] == 125
    assert rows[0]["under_odds"] is None


def test_a_no_outcome_becomes_an_under_price():
    rows = prop_rows(td_payload([
        {"name": "Yes", "description": "A.J. Brown", "price": 125, "point": None},
        {"name": "No", "description": "A.J. Brown", "price": -150, "point": None},
    ]), "G1", 2026, 1, MATCHED, "U")
    assert len(rows) == 1
    assert (rows[0]["over_odds"], rows[0]["under_odds"]) == (125, -150)


def test_one_row_per_player_not_per_outcome():
    rows = prop_rows(td_payload([
        {"name": "Yes", "description": "A.J. Brown", "price": 125, "point": None},
        {"name": "Yes", "description": "Jaxon Smith-Njigba", "price": 150, "point": None},
    ]), "G1", 2026, 1, MATCHED, "U")
    assert len(rows) == 2


def test_an_unmatched_player_yields_no_row():
    """The same refusal to guess that feature 7a built."""
    rows = prop_rows(td_payload([
        {"name": "Yes", "description": "Nobody At All", "price": 125, "point": None},
    ]), "G1", 2026, 1, MATCHED, "U")
    assert rows == []


def test_each_book_keeps_its_own_price():
    payload_two = {"bookmakers": [
        {"key": "draftkings", "markets": [{"key": "player_anytime_td", "outcomes": [
            {"name": "Yes", "description": "A.J. Brown", "price": 125, "point": None}]}]},
        {"key": "fanduel", "markets": [{"key": "player_anytime_td", "outcomes": [
            {"name": "Yes", "description": "A.J. Brown", "price": 140, "point": None}]}]},
    ]}
    rows = prop_rows(payload_two, "G1", 2026, 1, MATCHED, "U")
    assert {r["book"]: r["over_odds"] for r in rows} == {"draftkings": 125, "fanduel": 140}


def test_the_game_identity_is_stamped():
    rows = prop_rows(td_payload([
        {"name": "Yes", "description": "A.J. Brown", "price": 125, "point": None},
    ]), "G1", 2026, 7, MATCHED, "CAPTURED")
    assert rows[0]["game_id"] == "G1"
    assert rows[0]["season"] == 2026 and rows[0]["week"] == 7
    assert rows[0]["captured_at"] == "CAPTURED" and rows[0]["updated_at"] == "CAPTURED"


def test_every_market_we_model_is_requested():
    """The request list and the two maps must not drift: a market absent here
    is never fetched, and one present with no mapping is paid for and dropped."""
    assert set(ALL_MARKETS) == {*MARKET_STAT_TYPES, *BINARY_MARKET_STAT_TYPES}
    assert "player_anytime_td" in ALL_MARKETS
    assert len(ALL_MARKETS) == 5


def test_the_two_market_maps_do_not_overlap():
    """A market in both would take whichever branch is checked first."""
    assert set(MARKET_STAT_TYPES) & set(BINARY_MARKET_STAT_TYPES) == set()


def test_every_stat_type_is_one_the_schema_allows():
    """prop_lines CHECKs stat_type, so an unlisted value fails at write time."""
    allowed = {"passing_yards", "rushing_yards", "receiving_yards",
               "receptions", "touchdowns"}
    assert set(MARKET_STAT_TYPES.values()) | set(BINARY_MARKET_STAT_TYPES.values()) <= allowed


# --- the closing rule (feature 7b) ------------------------------------------

KICKOFF = datetime(2026, 9, 10, 0, 20, tzinfo=timezone.utc)


def capture(row_id, captured, player="p1", stat="receptions", book="draftkings"):
    return {"id": row_id, "player_id": player, "stat_type": stat,
            "book": book, "captured_at": captured}


def test_a_single_capture_is_the_closing_one():
    assert closing_ids([capture(1, "2026-09-05T03:33:00+00:00")], KICKOFF) == {1}


def test_the_latest_before_kickoff_wins_even_when_a_later_one_exists():
    """Three captures, the middle one closing: the third is after kickoff."""
    rows = [capture(1, "2026-09-05T00:00:00+00:00"),
            capture(2, "2026-09-09T23:00:00+00:00"),
            capture(3, "2026-09-10T01:00:00+00:00")]
    assert closing_ids(rows, KICKOFF) == {2}


def test_a_capture_after_kickoff_is_never_closing():
    """A line posted during the game is not what the market thought before it."""
    assert closing_ids([capture(1, "2026-09-10T02:00:00+00:00")], KICKOFF) == set()


def test_a_capture_exactly_at_kickoff_is_excluded():
    assert closing_ids([capture(1, "2026-09-10T00:20:00+00:00")], KICKOFF) == set()


def test_everything_after_kickoff_leaves_nothing_marked():
    rows = [capture(1, "2026-09-11T00:00:00+00:00"), capture(2, "2026-09-12T00:00:00+00:00")]
    assert closing_ids(rows, KICKOFF) == set()


def test_each_book_is_marked_independently():
    """One book publishing late must not mask another book's closing number."""
    rows = [capture(1, "2026-09-05T00:00:00+00:00", book="draftkings"),
            capture(2, "2026-09-09T00:00:00+00:00", book="draftkings"),
            capture(3, "2026-09-06T00:00:00+00:00", book="fanduel")]
    assert closing_ids(rows, KICKOFF) == {2, 3}


def test_each_stat_type_is_marked_independently():
    rows = [capture(1, "2026-09-05T00:00:00+00:00", stat="receptions"),
            capture(2, "2026-09-05T00:00:00+00:00", stat="touchdowns")]
    assert closing_ids(rows, KICKOFF) == {1, 2}


def test_each_player_is_marked_independently():
    rows = [capture(1, "2026-09-05T00:00:00+00:00", player="p1"),
            capture(2, "2026-09-05T00:00:00+00:00", player="p2")]
    assert closing_ids(rows, KICKOFF) == {1, 2}


def test_no_captures_mark_nothing():
    assert closing_ids([], KICKOFF) == set()


def test_the_audit_sees_binary_market_names_too():
    """Otherwise it reports a match rate for four markets while ingest pays
    for five, and a touchdown-only player looks like full coverage."""
    payload_both = {"bookmakers": [{"key": "dk", "markets": [
        {"key": "player_receptions", "outcomes": [
            {"name": "Over", "description": "A.J. Brown", "point": 4.5}]},
        {"key": "player_anytime_td", "outcomes": [
            {"name": "Yes", "description": "Saquon Barkley", "price": -140}]},
    ]}]}
    assert set(outcome_names(payload_both)) == {"A.J. Brown", "Saquon Barkley"}

