"""Load weekly box-score actuals into the database."""

from __future__ import annotations

import sqlite3
from collections import Counter

from statify.ingest.common import utc_now, write, write_all
from statify.sources import nflverse

# Preseason lines are not priced and preseason usage does not predict regular
# season usage, so only games the games table already holds are kept.
SEASON_TYPES = frozenset({"REG", "POST"})

# Database column -> player_stats column. Absent means the player had none of
# that action, so these coalesce to 0.
COUNTING_COLUMNS = {
    "targets": "targets",
    "receptions": "receptions",
    "receiving_yards": "receiving_yards",
    "air_yards": "receiving_air_yards",
    "yac": "receiving_yards_after_catch",
    "receiving_tds": "receiving_tds",
    "carries": "carries",
    "rushing_yards": "rushing_yards",
    "rushing_tds": "rushing_tds",
    "attempts": "attempts",
    "completions": "completions",
    "passing_yards": "passing_yards",
    "passing_tds": "passing_tds",
}

# Rate stats, so a missing value stays NULL. A player with no targets has
# undefined receiving EPA, not 0.0, and a fake zero would drag feature 12's
# efficiency averages down.
EPA_COLUMNS = ("receiving_epa", "rushing_epa", "passing_epa")

SOURCE_COLUMNS = [
    "player_id",
    "game_id",
    "season",
    "week",
    "season_type",
    "team",
    *COUNTING_COLUMNS.values(),
    *EPA_COLUMNS,
]

# Only the columns this loader owns are updated on conflict. snaps and
# snap_share (feature 4), routes_run, and red_zone_touches are written by later
# passes over these same rows, and a blanket update would silently wipe them.
WEEKLY_UPSERT = """
INSERT INTO weekly_actuals (
  player_id, game_id, season, week, team_abbr,
  targets, receptions, receiving_yards, air_yards, yac, receiving_tds, receiving_epa,
  carries, rushing_yards, rushing_tds, rushing_epa,
  attempts, completions, passing_yards, passing_tds, passing_epa,
  updated_at
)
VALUES (
  :player_id, :game_id, :season, :week, :team_abbr,
  :targets, :receptions, :receiving_yards, :air_yards, :yac, :receiving_tds, :receiving_epa,
  :carries, :rushing_yards, :rushing_tds, :rushing_epa,
  :attempts, :completions, :passing_yards, :passing_tds, :passing_epa,
  :updated_at
)
ON CONFLICT(player_id, game_id) DO UPDATE SET
  season = excluded.season,
  week = excluded.week,
  team_abbr = excluded.team_abbr,
  targets = excluded.targets,
  receptions = excluded.receptions,
  receiving_yards = excluded.receiving_yards,
  air_yards = excluded.air_yards,
  yac = excluded.yac,
  receiving_tds = excluded.receiving_tds,
  receiving_epa = excluded.receiving_epa,
  carries = excluded.carries,
  rushing_yards = excluded.rushing_yards,
  rushing_tds = excluded.rushing_tds,
  rushing_epa = excluded.rushing_epa,
  attempts = excluded.attempts,
  completions = excluded.completions,
  passing_yards = excluded.passing_yards,
  passing_tds = excluded.passing_tds,
  passing_epa = excluded.passing_epa,
  updated_at = excluded.updated_at
"""


def _known_player_ids(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT player_id FROM players")}


def _require_games(conn: sqlite3.Connection, rows: list[dict], season: int) -> None:
    """A player row for a game we never ingested is a missing precondition, not bad data."""
    known = {row[0] for row in conn.execute("SELECT game_id FROM games WHERE season = ?", (season,))}
    missing = sorted({row["game_id"] for row in rows} - known)
    if missing:
        raise RuntimeError(
            f"{len(missing)} game(s) missing from the games table, "
            f"e.g. {', '.join(missing[:3])}. "
            f"Run: statify ingest games --season {season}"
        )


def _weekly_row(source: dict, updated_at: str) -> dict:
    row = {
        "player_id": source["player_id"],
        "game_id": source["game_id"],
        "season": source["season"],
        "week": source["week"],
        "team_abbr": source["team"],
        "updated_at": updated_at,
    }
    for column, source_column in COUNTING_COLUMNS.items():
        row[column] = int(source[source_column] or 0)
    for column in EPA_COLUMNS:
        row[column] = source[column]
    return row


def load_weekly_actuals(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int]:
    """Upsert one season's weekly box-score lines. Returns (upserted, skipped)."""
    frame = nflverse.player_stats(season).select(SOURCE_COLUMNS)
    known_players = _known_player_ids(conn)
    updated_at = utc_now()

    rows: list[dict] = []
    skipped = 0
    for source in frame.iter_rows(named=True):
        if source["season_type"] not in SEASON_TYPES:
            continue
        if week is not None and source["week"] != week:
            continue

        # player_stats covers every position; players holds only the skill
        # positions this project projects, and only for the seasons rostered.
        if source["player_id"] not in known_players:
            skipped += 1
            continue

        rows.append(_weekly_row(source, updated_at))

    _require_games(conn, rows, season)
    write(conn, WEEKLY_UPSERT, rows)
    return len(rows), skipped


PBP_COLUMNS = [
    "game_id",
    "week",
    "yardline_100",
    "rush_attempt",
    "pass_attempt",
    "rusher_player_id",
    "receiver_player_id",
    "two_point_attempt",
]

# Zeroing first is what makes NULL mean "the play-by-play pass has not run for
# this game" rather than "this player had no red zone work". Feature 10 cannot
# compute red zone touch share without that distinction.
RED_ZONE_RESET = """
UPDATE weekly_actuals
SET red_zone_touches = 0, updated_at = :updated_at
WHERE game_id = :game_id
"""

RED_ZONE_UPDATE = """
UPDATE weekly_actuals
SET red_zone_touches = :red_zone_touches, updated_at = :updated_at
WHERE game_id = :game_id AND player_id = :player_id
"""


def count_red_zone_touches(plays: list[dict]) -> Counter:
    """Tally (game_id, player_id) touches inside the 20.

    A touch is a rush attempt, or a target whether or not it was caught, which is
    how red zone touch share is normally read. Two-point conversions are untimed
    scrimmage plays that no usage rate counts.
    """
    touches: Counter = Counter()
    for play in plays:
        if play["yardline_100"] is None or play["yardline_100"] > 20:
            continue
        if play["two_point_attempt"] == 1:
            continue

        if play["rush_attempt"] == 1 and play["rusher_player_id"]:
            touches[(play["game_id"], play["rusher_player_id"])] += 1
        elif play["pass_attempt"] == 1 and play["receiver_player_id"]:
            touches[(play["game_id"], play["receiver_player_id"])] += 1
    return touches


def load_red_zone_touches(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int, int]:
    """Fill red_zone_touches from play-by-play. Returns (games, updated, unmatched)."""
    frame = nflverse.pbp(season, PBP_COLUMNS)
    if week is not None:
        frame = frame.filter(frame["week"] == week)

    plays = list(frame.iter_rows(named=True))
    touches = count_red_zone_touches(plays)
    updated_at = utc_now()

    games = sorted({play["game_id"] for play in plays})
    resets = [{"game_id": game_id, "updated_at": updated_at} for game_id in games]

    known = {
        (row[0], row[1])
        for row in conn.execute(
            "SELECT game_id, player_id FROM weekly_actuals WHERE season = ?", (season,)
        )
    }
    # A rusher or receiver with no weekly_actuals row is a non-skill player, or a
    # player absent from the players table. Expected, but worth counting.
    matched = {pair: count for pair, count in touches.items() if pair in known}

    updates = [
        {
            "game_id": game_id,
            "player_id": player_id,
            "red_zone_touches": count,
            "updated_at": updated_at,
        }
        for (game_id, player_id), count in matched.items()
    ]

    write_all(conn, [(RED_ZONE_RESET, resets), (RED_ZONE_UPDATE, updates)])
    return len(games), len(updates), len(touches) - len(matched)
