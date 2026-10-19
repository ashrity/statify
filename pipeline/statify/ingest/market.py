"""Capture the market's view of a game: spread, total, and implied points.

Feature 14 needs implied team totals and cannot be built without them, and
feature 21 measures our projections against the same market recorded here.

Cheap, unlike feature 7a. Team markets are on the bulk odds endpoint, which
charges one credit per market however many games come back, so a whole slate
costs 2 against roughly 64 for a week of player props.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import utc_now, write
from statify.ingest.props import resolve_event
from statify.sources import odds_api

SPREADS = "spreads"
TOTALS = "totals"
MARKETS = [SPREADS, TOTALS]


def implied_team_total(game_total: float | None, spread: float | None) -> float | None:
    """What the market expects this team to score.

    `spread` is already signed from this team's point of view, so no extra
    negation: a favourite at -7.5 on a 52.5 total gets 26.25 + 3.75 = 30.0 and
    its opponent at +7.5 gets 22.5. The two always sum back to the total, which
    is the property worth testing, because a sign error here produces two
    plausible numbers that sum to the wrong thing.

    None when either input is missing, since books post the two markets
    separately and a half-known total is not a number.
    """
    if game_total is None or spread is None:
        return None
    return game_total / 2 - spread / 2


def market_points(bookmaker: dict) -> tuple[dict[str, float], float | None]:
    """One book's spreads by team name, and the game total.

    The totals market names its outcomes Over and Under rather than a team, so
    the total belongs to the game and is read once. Over and Under carry the
    same point; either will do.
    """
    spreads: dict[str, float] = {}
    total: float | None = None

    for market in bookmaker.get("markets") or []:
        for outcome in market.get("outcomes") or []:
            point = outcome.get("point")
            if point is None:
                continue
            if market.get("key") == SPREADS:
                spreads[outcome.get("name")] = point
            elif market.get("key") == TOTALS and total is None:
                total = point
    return spreads, total


def book_rows(bookmaker: dict, team_abbrs: dict[str, str]) -> list[dict]:
    """The two team rows one book contributes to a game.

    Driven by the spreads market, because that is the only one naming teams. A
    book with a total but no spread yields nothing: there would be no team to
    attach the implied total to.
    """
    spreads, total = market_points(bookmaker)
    rows = []
    for name, spread in spreads.items():
        team_abbr = team_abbrs.get(name)
        if team_abbr is None:
            continue
        rows.append(
            {
                "team_abbr": team_abbr,
                "book": bookmaker.get("key"),
                "spread": spread,
                "game_total": total,
                "implied_team_total": implied_team_total(total, spread),
            }
        )
    return rows


def event_rows(
    event: dict,
    game_id: str,
    season: int,
    week: int,
    team_abbrs: dict[str, str],
    captured_at: str,
    updated_at: str,
) -> list[dict]:
    """Every row one resolved event contributes, across all of its books."""
    rows = []
    for bookmaker in event.get("bookmakers") or []:
        for row in book_rows(bookmaker, team_abbrs):
            rows.append(
                {
                    "game_id": game_id,
                    "season": season,
                    "week": week,
                    "captured_at": captured_at,
                    "updated_at": updated_at,
                    **row,
                }
            )
    return rows


MARKET_UPSERT = """
INSERT INTO team_market_data (
  game_id, team_abbr, season, week, book,
  spread, game_total, implied_team_total, captured_at, updated_at
)
VALUES (
  :game_id, :team_abbr, :season, :week, :book,
  :spread, :game_total, :implied_team_total, :captured_at, :updated_at
)
ON CONFLICT(game_id, team_abbr, book, captured_at) DO UPDATE SET
  season = excluded.season,
  week = excluded.week,
  spread = excluded.spread,
  game_total = excluded.game_total,
  implied_team_total = excluded.implied_team_total,
  updated_at = excluded.updated_at
"""


def resolve_slate(
    events: list[dict], team_abbrs: dict[str, str], games: dict
) -> tuple[list[tuple[dict, tuple]], list[str]]:
    """Split a slate into events we can place and events we cannot.

    An unresolved event is a game quietly missing from the capture, not an
    error, so it is returned by name rather than raised or dropped.
    """
    matched: list[tuple[dict, tuple]] = []
    unresolved: list[str] = []
    for event in events:
        resolved = resolve_event(event, team_abbrs, games)
        if resolved is None:
            unresolved.append(f"{event.get('away_team')} @ {event.get('home_team')}")
        else:
            matched.append((event, resolved))
    return matched, unresolved


def in_week(matched: list[tuple[dict, tuple]], week: int | None) -> list[tuple[dict, tuple]]:
    """Filter to one week.

    This narrows what is stored, never what is fetched: the bulk endpoint
    returns the whole upcoming slate and charges per market, so unlike
    `ingest props` a narrower week saves no credits.
    """
    if week is None:
        return matched
    return [pair for pair in matched if pair[1][2] == week]


def latest_stored(conn: sqlite3.Connection, season: int) -> dict[tuple, tuple]:
    """The most recent stored numbers per game, team and book."""
    rows = conn.execute(
        """
        SELECT game_id, team_abbr, book, spread, game_total
        FROM team_market_data
        WHERE (game_id, team_abbr, book, captured_at) IN (
          SELECT game_id, team_abbr, book, MAX(captured_at)
          FROM team_market_data WHERE season = ?
          GROUP BY game_id, team_abbr, book
        )
        """,
        (season,),
    )
    return {(r[0], r[1], r[2]): (r[3], r[4]) for r in rows}


def is_new_capture(row: dict, latest: dict[tuple, tuple]) -> bool:
    """Whether this row says anything the stored history does not.

    Novelty is decided by content, never by the clock. Two runs minutes apart
    carry different `captured_at` values and would both be stored, which is how
    feature 7a ended up with 433 duplicate rows, and how a first version of this
    loader doubled a 240-row slate to 480 on an immediate re-run.

    Lines move several times a week and every move is wanted. A line that has
    not moved is not history, it is the same fact recorded twice.
    """
    key = (row["game_id"], row["team_abbr"], row["book"])
    previous = latest.get(key)
    if previous is None:
        return True
    return (row["spread"], row["game_total"]) != previous


def load_market_data(
    conn: sqlite3.Connection, season: int, week: int | None = None, dry_run: bool = False
) -> dict:
    """Capture the current slate's team markets.

    A dry run reads only the free events endpoint, so it reports the slate and
    the cost without spending anything.
    """
    team_abbrs = {row[0]: row[1] for row in conn.execute("SELECT name, team_abbr FROM teams")}
    games: dict[tuple[str, str], list] = {}
    for game_id, kickoff_at, home, away, gseason, gweek in conn.execute(
        "SELECT game_id, kickoff_at, home_team, away_team, season, week "
        "FROM games WHERE season = ?",
        (season,),
    ):
        games.setdefault((home, away), []).append((game_id, kickoff_at, gseason, gweek))

    if dry_run:
        events, remaining = odds_api.events()
    else:
        events, remaining = odds_api.bulk_odds(MARKETS)

    matched, unresolved = resolve_slate(events, team_abbrs, games)
    scoped = in_week(matched, week)

    result = {
        "events": len(events),
        "resolved": len(matched),
        "unresolved": unresolved,
        "in_scope": len(scoped),
        "estimate": len(MARKETS),
        "remaining": remaining,
        "rows": 0,
    }
    if dry_run:
        return result

    captured_at = utc_now()
    rows: list[dict] = []
    for event, (game_id, gseason, gweek) in scoped:
        rows.extend(
            event_rows(event, game_id, gseason, gweek, team_abbrs, captured_at, captured_at)
        )

    latest = latest_stored(conn, season)
    fresh = [row for row in rows if is_new_capture(row, latest)]

    write(conn, MARKET_UPSERT, fresh)
    result["rows"] = len(fresh)
    result["unchanged"] = len(rows) - len(fresh)
    return result
