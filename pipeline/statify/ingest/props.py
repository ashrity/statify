"""Resolve The Odds API's identities onto ours, and load player prop lines.

The Odds API shares no keys with nflverse. Events are opaque hashes and players
are plain name strings, so both have to be resolved before anything can be
stored. That resolution is the whole risk of this feature: an unmatched player
is a visible gap, but a *mis*matched one silently attaches a real line to the
wrong person, and feature 21 then reports a large fake edge nobody can see.

So the rule is exact-after-normalization or nothing. No fuzzy scoring, and a
name that could be two players is refused rather than guessed.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta

# Generational suffixes are inconsistent between feeds: a book may write
# "Michael Pittman Jr." where the roster says "Michael Pittman". Dropping the
# suffix is safe only because a collision (a father and son both active) would
# be caught by the ambiguity refusal rather than silently resolved.
NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})

# A book's kickoff and the schedule's can differ by minutes. They cannot differ
# by a day, so this tolerance separates "same game" from "different week".
KICKOFF_TOLERANCE = timedelta(hours=24)

MARKET_STAT_TYPES = {
    "player_pass_yds": "passing_yards",
    "player_rush_yds": "rushing_yards",
    "player_reception_yds": "receiving_yards",
    "player_receptions": "receptions",
}


def normalize_name(name: str | None) -> str:
    """Fold a player name to the form both feeds agree on.

    Handles the differences actually seen between books and rosters: accents,
    case, periods in initials, apostrophes, hyphenated surnames, and trailing
    generational suffixes.
    """
    if not name:
        return ""
    folded = unicodedata.normalize("NFKD", name)
    folded = "".join(c for c in folded if not unicodedata.combining(c))
    folded = folded.lower()
    folded = re.sub(r"[.'`’]", "", folded)
    folded = re.sub(r"[-/]", " ", folded)
    parts = [p for p in folded.split() if p]
    while parts and parts[-1] in NAME_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def build_player_index(rows: list[tuple[str, str]]) -> dict[str, set[str]]:
    """Map each normalized name to every player id that claims it.

    A set rather than a single id on purpose: the size is what makes ambiguity
    detectable instead of order-dependent.
    """
    index: dict[str, set[str]] = {}
    for player_id, name in rows:
        index.setdefault(normalize_name(name), set()).add(player_id)
    return index


def resolve_players(
    names: list[str], index: dict[str, set[str]]
) -> tuple[dict[str, str], list[str], list[str]]:
    """Resolve book names to player ids. Returns (matched, unmatched, ambiguous)."""
    matched: dict[str, str] = {}
    unmatched: list[str] = []
    ambiguous: list[str] = []

    for name in sorted(set(names)):
        candidates = index.get(normalize_name(name), set())
        if not candidates:
            unmatched.append(name)
        elif len(candidates) > 1:
            ambiguous.append(name)
        else:
            matched[name] = next(iter(candidates))
    return matched, unmatched, ambiguous


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def resolve_event(
    event: dict,
    team_abbrs: dict[str, str],
    games: dict[tuple[str, str], list[tuple[str, str, int, int]]],
) -> tuple[str, int, int] | None:
    """Map an API event to (game_id, season, week), or None if it cannot be resolved.

    Division rivals meet twice a season, so the matchup alone is not a key; the
    kickoff time separates the two.
    """
    home = team_abbrs.get(event.get("home_team", ""))
    away = team_abbrs.get(event.get("away_team", ""))
    if home is None or away is None:
        return None

    candidates = games.get((home, away))
    if not candidates:
        return None

    commence = _parse_utc(event["commence_time"])
    best = min(candidates, key=lambda g: abs(_parse_utc(g[1]) - commence))
    if abs(_parse_utc(best[1]) - commence) > KICKOFF_TOLERANCE:
        return None
    return best[0], best[2], best[3]


def load_reference(conn: sqlite3.Connection, season: int):
    """Read the lookup tables the resolvers need."""
    team_abbrs = {row[0]: row[1] for row in conn.execute("SELECT name, team_abbr FROM teams")}
    games: dict[tuple[str, str], list[tuple[str, str, int, int]]] = {}
    for game_id, kickoff_at, home, away, gseason, week in conn.execute(
        "SELECT game_id, kickoff_at, home_team, away_team, season, week "
        "FROM games WHERE season = ?",
        (season,),
    ):
        games.setdefault((home, away), []).append((game_id, kickoff_at, gseason, week))
    players = build_player_index(
        list(conn.execute("SELECT player_id, name FROM players"))
    )
    return team_abbrs, games, players


def outcome_names(payload: dict) -> list[str]:
    """Every player name appearing in an event's markets."""
    names: list[str] = []
    for book in payload.get("bookmakers", []):
        for market in book.get("markets", []):
            if market.get("key") not in MARKET_STAT_TYPES:
                continue
            for outcome in market.get("outcomes", []):
                if outcome.get("description"):
                    names.append(outcome["description"])
    return names


# Leave enough credits that a bad estimate cannot strand the month. The free
# tier is 500, one week of a full slate is roughly 60, so this floor is about
# one emergency pull in reserve.
CREDIT_FLOOR = 50


def estimate_credits(event_count: int, market_count: int) -> int:
    """Credits a run will cost.

    Measured against the live API: cost is markets times events, and neither the
    region count nor the number of books returned changes it.
    """
    return event_count * market_count


def assert_within_budget(
    estimate: int, remaining: int | None, floor: int = CREDIT_FLOOR
) -> None:
    """Refuse a run that would leave fewer than `floor` credits."""
    if remaining is None:
        # The header is missing rather than the balance being zero. Blocking on a
        # transient absence would be worse than proceeding without the guard.
        return
    if remaining - estimate < floor:
        shortfall = floor - (remaining - estimate)
        raise RuntimeError(
            f"refusing to run: {estimate} credits needed, {remaining} remaining, "
            f"which would leave {remaining - estimate} against a floor of {floor} "
            f"(short by {shortfall}). Narrow the scope with --week, or wait for "
            "the monthly reset."
        )


PROP_UPSERT = """
INSERT INTO prop_lines (
  player_id, game_id, season, week, stat_type, book,
  line, over_odds, under_odds, captured_at, is_closing, updated_at
)
VALUES (
  :player_id, :game_id, :season, :week, :stat_type, :book,
  :line, :over_odds, :under_odds, :captured_at, 0, :updated_at
)
ON CONFLICT(player_id, game_id, stat_type, book, captured_at) DO UPDATE SET
  line = excluded.line,
  over_odds = excluded.over_odds,
  under_odds = excluded.under_odds,
  updated_at = excluded.updated_at
"""


def prop_rows(
    payload: dict,
    game_id: str,
    season: int,
    week: int,
    matched: dict[str, str],
    captured_at: str,
) -> list[dict]:
    """Turn one event's payload into storable rows.

    Over and Under arrive as separate outcomes and collapse into one row. They
    are grouped by (player, point) rather than player alone: if a book somehow
    posts the two sides at different numbers, those are two lines, and merging
    them would invent a line that was never offered.

    captured_at is the run's own clock, not the market's last_update. That field
    records when a book last published, not when it last moved a price, so books
    bump it constantly without changing anything; keying on it produced 433
    identical duplicate rows across two runs a minute apart.
    """
    rows: list[dict] = []
    for book in payload.get("bookmakers", []):
        for market in book.get("markets", []):
            stat_type = MARKET_STAT_TYPES.get(market.get("key"))
            if stat_type is None:
                continue

            sides: dict[tuple[str, float], dict] = {}
            for outcome in market.get("outcomes", []):
                player_id = matched.get(outcome.get("description", ""))
                if player_id is None or outcome.get("point") is None:
                    continue
                key = (player_id, float(outcome["point"]))
                row = sides.setdefault(
                    key,
                    {
                        "player_id": player_id,
                        "game_id": game_id,
                        "season": season,
                        "week": week,
                        "stat_type": stat_type,
                        "book": book["key"],
                        "line": float(outcome["point"]),
                        "over_odds": None,
                        "under_odds": None,
                        "captured_at": captured_at,
                        "updated_at": captured_at,
                    },
                )
                if outcome.get("name") == "Over":
                    row["over_odds"] = outcome.get("price")
                elif outcome.get("name") == "Under":
                    row["under_odds"] = outcome.get("price")

            rows.extend(sides.values())
    return rows


def latest_stored(conn: sqlite3.Connection, season: int, week: int) -> dict[tuple, tuple]:
    """The most recent stored line per player, game, stat type and book."""
    rows = conn.execute(
        """
        SELECT player_id, game_id, stat_type, book, line, over_odds, under_odds
        FROM prop_lines
        WHERE (player_id, game_id, stat_type, book, captured_at) IN (
          SELECT player_id, game_id, stat_type, book, MAX(captured_at)
          FROM prop_lines WHERE season = ? AND week = ?
          GROUP BY player_id, game_id, stat_type, book
        )
        """,
        (season, week),
    )
    return {(r[0], r[1], r[2], r[3]): (r[4], r[5], r[6]) for r in rows}


def is_new_capture(row: dict, latest: dict[tuple, tuple]) -> bool:
    """Whether this row says anything the stored history does not.

    A capture is worth keeping only when the number moved. Storing an unchanged
    line again would inflate the table without adding information, and feature
    28's closing-line work would then be reading noise.
    """
    key = (row["player_id"], row["game_id"], row["stat_type"], row["book"])
    previous = latest.get(key)
    if previous is None:
        return True
    return (row["line"], row["over_odds"], row["under_odds"]) != previous
