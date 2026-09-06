"""Count routes run, from who was on the field for each dropback.

This is the pipeline's first approximated metric. No free source publishes
per-player route counts, so a player on the field for a dropback is counted as
having run a route. A player who stayed in to block is counted too, and the
error is not evenly spread: measured on 2024, targets per route comes out at
0.196 for receivers against a real figure near 0.20, but 0.150 for backs against
a real figure near 0.20, so back routes are over-counted by roughly a quarter.

Migration 015 carries the same warning, because feature 12 will meet the numbers
in the schema rather than here.
"""

from __future__ import annotations

import sqlite3
from collections import Counter

from statify.ingest.common import utc_now, write
from statify.sources import nflverse

SEASON_TYPES = frozenset({"REG", "POST"})

# Quarterbacks are on the field for every dropback. Counting them puts Patrick
# Mahomes top of the league at 765 routes, which is wrong in a way that is
# obvious in a leaderboard and invisible in an aggregate.
ROUTE_POSITIONS = frozenset({"WR", "TE", "RB"})

PBP_COLUMNS = [
    "game_id",
    "play_id",
    "week",
    "season_type",
    "qb_dropback",
    "special_teams_play",
]

PARTICIPATION_COLUMNS = ["nflverse_game_id", "play_id", "offense_players"]

ROUTES_UPDATE = """
UPDATE weekly_actuals
SET routes_run = :routes_run, updated_at = :updated_at
WHERE player_id = :player_id AND game_id = :game_id
"""


def dropback_keys(plays: list[dict]) -> set[tuple[str, int]]:
    """Plays where receivers were running routes.

    Dropbacks rather than pass attempts: a sack or a scramble still had a route
    concept called, and counting only completions and incompletions would
    undercount every receiver.
    """
    return {
        (play["game_id"], play["play_id"])
        for play in plays
        if play.get("season_type") in SEASON_TYPES
        and play.get("qb_dropback") == 1
        and play.get("special_teams_play") != 1
    }


def parse_players(field: str | None) -> list[str]:
    """Split the semicolon-separated player list, dropping empties."""
    return [player_id for player_id in (field or "").split(";") if player_id]


def count_routes(
    participation: list[dict],
    dropbacks: set[tuple[str, int]],
    positions: dict[str, str],
) -> Counter:
    """Routes per (player, game).

    Participation covers every play including punts and kickoffs, where the
    "offense" is a return unit, so the dropback set is what keeps those out.
    """
    routes: Counter = Counter()
    for row in participation:
        key = (row["nflverse_game_id"], row["play_id"])
        if key not in dropbacks:
            continue
        for player_id in parse_players(row["offense_players"]):
            if positions.get(player_id) in ROUTE_POSITIONS:
                routes[(player_id, row["nflverse_game_id"])] += 1
    return routes


def load_routes(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int, int]:
    """Fill weekly_actuals.routes_run. Returns (updated, players, without_a_row)."""
    positions = {row[0]: row[1] for row in conn.execute("SELECT player_id, position FROM players")}
    known_rows = {
        (row[0], row[1])
        for row in conn.execute(
            "SELECT player_id, game_id FROM weekly_actuals WHERE season = ?", (season,)
        )
    }

    plays = [
        play
        for play in nflverse.pbp(season, PBP_COLUMNS).iter_rows(named=True)
        if week is None or play["week"] == week
    ]
    dropbacks = dropback_keys(plays)
    participation = list(
        nflverse.participation(season, PARTICIPATION_COLUMNS).iter_rows(named=True)
    )

    routes = count_routes(participation, dropbacks, positions)
    updated_at = utc_now()

    rows = []
    missing = 0
    for (player_id, game_id), count in routes.items():
        # A player with routes but no weekly_actuals row is a gap to report, not
        # a row to invent: this loader owns one column, not the table.
        if (player_id, game_id) not in known_rows:
            missing += 1
            continue
        rows.append(
            {
                "player_id": player_id,
                "game_id": game_id,
                "routes_run": count,
                "updated_at": updated_at,
            }
        )

    write(conn, ROUTES_UPDATE, rows)
    return len(rows), len({player_id for player_id, _ in routes}), missing
