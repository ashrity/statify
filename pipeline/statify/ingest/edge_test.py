import sqlite3

import pytest

from statify import migrate as migrations
from statify.ingest.edge import (
    american_to_probability,
    earliest_after,
    edge_updates,
    latest_at_or_before,
    load_edges,
    market_value,
    matched_pairs,
    prop_lines_by_key,
    reprice_ids,
)


def projection(player, week, stat_type, projected_value, generated_at, pid=1):
    return {
        "id": pid,
        "player_id": player,
        "week": week,
        "stat_type": stat_type,
        "projected_value": projected_value,
        "generated_at": generated_at,
    }


def prop_line(player, week, stat_type, line, captured_at, lid, over_odds=None):
    return {
        "id": lid,
        "player_id": player,
        "week": week,
        "stat_type": stat_type,
        "line": line,
        "over_odds": over_odds,
        "captured_at": captured_at,
    }


# --- the temporal match -----------------------------------------------------


def test_a_line_captured_after_generation_is_ignored():
    candidates = [prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-02T00:00:00+00:00", 1)]
    match = latest_at_or_before(candidates, "2026-01-01T00:00:00+00:00")
    assert match is None


def test_the_latest_at_or_before_line_wins_among_several():
    candidates = sorted(
        [
            prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 1),
            prop_line("WR1", 3, "receiving_yards", 58.5, "2026-01-02T00:00:00+00:00", 2),
            prop_line("WR1", 3, "receiving_yards", 70.5, "2026-01-05T00:00:00+00:00", 3),
        ],
        key=lambda r: (r["captured_at"], r["id"]),
    )
    match = latest_at_or_before(candidates, "2026-01-03T00:00:00+00:00")
    assert match["line"] == 58.5


def test_a_capture_at_the_exact_same_instant_counts_as_available():
    candidates = [prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-01T00:00:00+00:00", 1)]
    match = latest_at_or_before(candidates, "2026-01-01T00:00:00+00:00")
    assert match is not None


def test_the_tie_break_is_deterministic_by_id():
    candidates = sorted(
        [
            prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 2),
            prop_line("WR1", 3, "receiving_yards", 56.5, "2026-01-01T00:00:00+00:00", 1),
        ],
        key=lambda r: (r["captured_at"], r["id"]),
    )
    match = latest_at_or_before(candidates, "2026-01-01T00:00:00+00:00")
    assert match["id"] == 2


def test_no_candidates_is_no_match():
    assert latest_at_or_before([], "2026-01-01T00:00:00+00:00") is None


# --- the full update set ------------------------------------------------------


def test_a_matched_projection_gets_an_edge_update():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-02T00:00:00+00:00")
    lines = [prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-01T00:00:00+00:00", 10)]
    updates = edge_updates([proj], lines)
    assert len(updates) == 1
    assert updates[0] == {"id": 1, "market_line": 60.5, "prop_line_id": 10, "edge": 65.0 - 60.5}


# --- touchdowns are measured against the book's price, not the 0.5 line -------


@pytest.mark.parametrize(
    "odds,expected",
    [
        (-200, 2 / 3),
        (-320, 320 / 420),
        (-110, 110 / 210),
        (100, 0.5),
        (150, 0.4),
        (2200, 100 / 2300),
    ],
)
def test_american_odds_convert_to_implied_probability(odds, expected):
    assert american_to_probability(odds) == pytest.approx(expected)


def test_a_favourite_is_more_likely_than_an_underdog():
    assert american_to_probability(-320) > american_to_probability(320)


def test_market_value_for_a_yardage_stat_is_the_posted_line():
    line = prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-01T00:00:00+00:00", 1)
    assert market_value(line, "receiving_yards") == 60.5


def test_market_value_for_touchdowns_ignores_the_half_line():
    """The 0.5 only encodes "at least one"; the opinion is in the price."""
    line = prop_line("RB1", 3, "touchdowns", 0.5, "2026-01-01T00:00:00+00:00", 1, over_odds=-320)
    assert market_value(line, "touchdowns") == pytest.approx(320 / 420)


def test_touchdowns_with_no_price_has_no_market_value():
    line = prop_line("RB1", 3, "touchdowns", 0.5, "2026-01-01T00:00:00+00:00", 1, over_odds=None)
    assert market_value(line, "touchdowns") is None


def test_touchdowns_edge_is_our_probability_minus_the_book_s():
    proj = projection("RB1", 3, "touchdowns", 0.798, "2026-01-02T00:00:00+00:00")
    lines = [prop_line("RB1", 3, "touchdowns", 0.5, "2026-01-01T00:00:00+00:00", 11, over_odds=-320)]
    updates = edge_updates([proj], lines)
    assert updates[0]["market_line"] == pytest.approx(320 / 420)
    assert updates[0]["edge"] == pytest.approx(0.798 - 320 / 420)


def test_a_heavy_favourite_the_model_also_likes_gets_a_small_edge_not_a_huge_one():
    """The whole point: a player the book already prices as likely is not an edge.

    Against the old fixed 0.5 line this projection would have scored +0.298.
    """
    proj = projection("RB1", 3, "touchdowns", 0.798, "2026-01-02T00:00:00+00:00")
    lines = [prop_line("RB1", 3, "touchdowns", 0.5, "2026-01-01T00:00:00+00:00", 11, over_odds=-320)]
    assert edge_updates([proj], lines)[0]["edge"] < 0.05


def test_the_model_can_disagree_downward_with_a_favourite():
    proj = projection("RB1", 3, "touchdowns", 0.596, "2026-01-02T00:00:00+00:00")
    lines = [prop_line("RB1", 3, "touchdowns", 0.5, "2026-01-01T00:00:00+00:00", 11, over_odds=-250)]
    assert edge_updates([proj], lines)[0]["edge"] < 0


def test_a_touchdowns_row_with_no_price_is_not_matched_at_all():
    proj = projection("RB1", 3, "touchdowns", 0.42, "2026-01-02T00:00:00+00:00")
    lines = [prop_line("RB1", 3, "touchdowns", 0.5, "2026-01-01T00:00:00+00:00", 11)]
    assert edge_updates([proj], lines) == []


def test_a_priced_capture_is_preferred_over_an_unpriced_earlier_one():
    proj = projection("RB1", 3, "touchdowns", 0.42, "2026-01-03T00:00:00+00:00")
    lines = [
        prop_line("RB1", 3, "touchdowns", 0.5, "2026-01-01T00:00:00+00:00", 10),
        prop_line("RB1", 3, "touchdowns", 0.5, "2026-01-02T00:00:00+00:00", 11, over_odds=120),
    ]
    assert edge_updates([proj], lines)[0]["prop_line_id"] == 11


def test_no_matching_line_leaves_the_projection_untouched():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-02T00:00:00+00:00")
    updates = edge_updates([proj], [])
    assert updates == []


def test_a_different_player_or_stat_type_is_not_matched():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-02T00:00:00+00:00")
    lines = [
        prop_line("WR2", 3, "receiving_yards", 60.5, "2026-01-01T00:00:00+00:00", 1),
        prop_line("WR1", 3, "receptions", 4.5, "2026-01-01T00:00:00+00:00", 2),
    ]
    assert edge_updates([proj], lines) == []


def test_a_null_line_is_not_a_match():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-02T00:00:00+00:00")
    lines = [prop_line("WR1", 3, "receiving_yards", None, "2026-01-01T00:00:00+00:00", 1)]
    assert edge_updates([proj], lines) == []


# --- the later-capture fallback -----------------------------------------------


def test_earliest_after_picks_the_first_capture_past_generation():
    candidates = sorted(
        [
            prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 1),
            prop_line("WR1", 3, "receiving_yards", 58.5, "2026-01-04T00:00:00+00:00", 2),
            prop_line("WR1", 3, "receiving_yards", 70.5, "2026-01-05T00:00:00+00:00", 3),
        ],
        key=lambda r: (r["captured_at"], r["id"]),
    )
    match = earliest_after(candidates, "2026-01-03T00:00:00+00:00")
    assert match["line"] == 58.5


def test_earliest_after_ignores_a_capture_at_the_same_instant():
    candidates = [prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-01T00:00:00+00:00", 1)]
    assert earliest_after(candidates, "2026-01-01T00:00:00+00:00") is None


def test_a_projection_with_no_prior_capture_falls_back_to_a_later_one():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-01T00:00:00+00:00")
    lines = [prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-02T00:00:00+00:00", 10)]
    updates = edge_updates([proj], lines)
    assert updates == [{"id": 1, "market_line": 60.5, "prop_line_id": 10, "edge": 65.0 - 60.5}]


def test_the_fallback_is_the_earliest_later_capture_not_the_latest():
    """Stability: the answer must not depend on when the command happened to run."""
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-01T00:00:00+00:00")
    lines = [
        prop_line("WR1", 3, "receiving_yards", 70.5, "2026-01-05T00:00:00+00:00", 11),
        prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-02T00:00:00+00:00", 10),
    ]
    assert edge_updates([proj], lines)[0]["prop_line_id"] == 10


def test_a_prior_capture_still_wins_over_a_later_one():
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-03T00:00:00+00:00")
    lines = [
        prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 10),
        prop_line("WR1", 3, "receiving_yards", 70.5, "2026-01-05T00:00:00+00:00", 11),
    ]
    assert edge_updates([proj], lines)[0]["prop_line_id"] == 10


def test_matched_pairs_flags_only_the_rows_that_took_the_fallback():
    prior = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-03T00:00:00+00:00", pid=1)
    later = projection("WR2", 3, "receiving_yards", 65.0, "2026-01-01T00:00:00+00:00", pid=2)
    lines = [
        prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 10),
        prop_line("WR2", 3, "receiving_yards", 60.5, "2026-01-02T00:00:00+00:00", 11),
    ]
    flags = {p["id"]: was_later for p, _, was_later in matched_pairs([prior, later], lines)}
    assert flags == {1: False, 2: True}


def test_a_null_line_is_skipped_rather_than_blocking_an_earlier_one():
    """A NULL line carries no number to beat, so it is not a candidate at all."""
    proj = projection("WR1", 3, "receiving_yards", 65.0, "2026-01-03T00:00:00+00:00")
    lines = [
        prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 10),
        prop_line("WR1", 3, "receiving_yards", None, "2026-01-02T00:00:00+00:00", 11),
    ]
    assert edge_updates([proj], lines)[0]["prop_line_id"] == 10


def test_prop_lines_by_key_sorts_each_group_by_captured_at_then_id():
    lines = [
        prop_line("WR1", 3, "receiving_yards", 60.5, "2026-01-02T00:00:00+00:00", 2),
        prop_line("WR1", 3, "receiving_yards", 55.5, "2026-01-01T00:00:00+00:00", 1),
    ]
    grouped = prop_lines_by_key(lines)
    key = ("WR1", 3, "receiving_yards")
    assert [row["id"] for row in grouped[key]] == [1, 2]


# --- repricing: discard a match so a newer capture can be taken ----------------


@pytest.fixture()
def db():
    connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.row_factory = sqlite3.Row
    migrations.migrate(connection)
    yield connection
    connection.close()


def seed(conn, kickoff_at, captured_at, generated_at, line=60.5, market_line=55.0):
    """One projection already matched to one line, for a game at kickoff_at."""
    stamp = "2026-01-01T00:00:00+00:00"
    conn.execute(
        "INSERT INTO teams (team_abbr, name, updated_at) VALUES ('NE', 'New England', ?)", (stamp,)
    )
    conn.execute(
        "INSERT INTO teams (team_abbr, name, updated_at) VALUES ('CHI', 'Chicago', ?)", (stamp,)
    )
    conn.execute(
        "INSERT INTO players (player_id, name, position, team_abbr, updated_at)"
        " VALUES ('P1', 'Test', 'WR', 'NE', ?)",
        (stamp,),
    )
    conn.execute(
        "INSERT INTO games"
        " (game_id, season, week, game_type, kickoff_at, home_team, away_team, updated_at)"
        " VALUES ('G1', 2026, 7, 'REG', ?, 'CHI', 'NE', ?)",
        (kickoff_at, stamp),
    )
    conn.execute(
        "INSERT INTO player_matchup_environment_weekly"
        " (player_id, season, week, team_abbr, opponent_team_abbr, position,"
        "  pass_matchup_k, rush_matchup_k, environment_m, updated_at)"
        " VALUES ('P1', 2026, 7, 'NE', 'CHI', 'WR', 0.0, 0.5, 0.0, ?)",
        (stamp,),
    )
    conn.execute(
        "INSERT INTO prop_lines"
        " (id, player_id, game_id, season, week, stat_type, book, line, captured_at, updated_at)"
        " VALUES (10, 'P1', 'G1', 2026, 7, 'receiving_yards', 'dk', ?, ?, ?)",
        (line, captured_at, stamp),
    )
    conn.execute(
        "INSERT INTO projections"
        " (id, player_id, season, week, stat_type, model_version, projected_value,"
        "  market_line, prop_line_id, edge, confidence, generated_at)"
        " VALUES (1, 'P1', 2026, 7, 'receiving_yards', 'v1', 70.0, ?, 10, ?, 0.8, ?)",
        (market_line, 70.0 - market_line, generated_at),
    )


def row(conn):
    return conn.execute(
        "SELECT market_line, prop_line_id, edge, confidence FROM projections WHERE id = 1"
    ).fetchone()


def test_without_reprice_an_already_matched_row_is_untouched(db):
    seed(db, "2099-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
    result = load_edges(db, 2026)
    assert result.matched == 0
    assert result.cleared == 0
    assert row(db)["market_line"] == 55.0


def test_reprice_rematches_against_the_newer_capture(db):
    """The whole point: a fresh capture reaches a row that was already matched."""
    seed(db, "2099-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
    result = load_edges(db, 2026, reprice=True)
    assert result.cleared == 1
    assert result.matched == 1
    after = row(db)
    assert after["market_line"] == 60.5
    assert after["edge"] == pytest.approx(70.0 - 60.5)


def test_reprice_leaves_a_game_that_has_kicked_off_alone(db):
    """A line for a played game is history, and beat_line is derived from it."""
    seed(db, "2020-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
    result = load_edges(db, 2026, reprice=True)
    assert result.cleared == 0
    assert result.left_alone == 1
    assert row(db)["market_line"] == 55.0


def test_reprice_clears_the_confidence_derived_from_the_old_edge(db):
    seed(db, "2099-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
    load_edges(db, 2026, reprice=True)
    # Re-matched in the same run, so confidence stays NULL until compute
    # confidence runs again rather than describing the line it no longer points at.
    assert row(db)["confidence"] is None


def test_reprice_scope_respects_the_week_filter(db):
    seed(db, "2099-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
    result = load_edges(db, 2026, week=9, reprice=True)
    assert result.cleared == 0
    assert row(db)["market_line"] == 55.0


def test_reprice_ids_skips_a_projection_whose_game_cannot_be_resolved(db):
    seed(db, "2099-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
    db.execute("DELETE FROM player_matchup_environment_weekly")
    assert reprice_ids(db, 2026, "2026-06-01T00:00:00+00:00") == []


def test_left_alone_is_scoped_to_the_week_not_the_season(db):
    """Otherwise a week-scoped clear is subtracted from a season-wide total."""
    seed(db, "2020-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00")
    # A second matched projection in a different week, which --week 7 must ignore.
    db.execute(
        "INSERT INTO projections"
        " (id, player_id, season, week, stat_type, model_version, projected_value,"
        "  market_line, prop_line_id, edge, generated_at)"
        " VALUES (2, 'P1', 2026, 9, 'receiving_yards', 'v1', 70.0, 55.0, 10, 15.0,"
        "  '2026-01-02T00:00:00+00:00')"
    )
    result = load_edges(db, 2026, week=7, reprice=True)
    assert result.cleared == 0
    assert result.left_alone == 1
