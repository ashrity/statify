"""Load nflverse reference data into the local database."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from statify.sources import nflverse

# load_teams() carries 36 rows: the 32 active franchises plus retired aliases that
# share a team_id with a current one. Every actual data table (schedules, rosters,
# player_stats) spells the Rams LA, the Raiders LV, and the Chargers LAC, so those
# are the rows to keep and these are the ones to drop. A pre-2016 season would need
# STL restored, and a pre-2020 season OAK and SD.
HISTORICAL_TEAM_ABBRS = frozenset({"LAR", "STL", "OAK", "SD"})

# nflverse normalizes every kickoff to Eastern clock time regardless of where the
# game is played, so a London game reads 09:30 rather than 14:30 local.
EASTERN = ZoneInfo("America/New_York")

# A closed retractable roof shields the field just as a fixed dome does, which is
# what is_dome exists to answer for the weather adjustment.
DOME_ROOFS = frozenset({"dome", "closed"})

# The offensive skill positions this project projects. Matches the CHECK
# constraint on players.position.
SKILL_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})

TEAMS_UPSERT = """
INSERT INTO teams (team_abbr, name, updated_at)
VALUES (:team_abbr, :name, :updated_at)
ON CONFLICT(team_abbr) DO UPDATE SET
  name = excluded.name,
  updated_at = excluded.updated_at
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write(conn: sqlite3.Connection, statement: str, rows: list[dict]) -> None:
    conn.execute("BEGIN")
    try:
        conn.executemany(statement, rows)
        conn.execute("COMMIT")
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise


def load_teams(conn: sqlite3.Connection) -> tuple[int, int]:
    """Upsert the active NFL teams. Returns (upserted, skipped)."""
    frame = nflverse.teams()
    updated_at = _utc_now()

    rows: list[dict] = []
    skipped = 0
    for source in frame.select(["team_abbr", "team_name"]).iter_rows(named=True):
        if source["team_abbr"] in HISTORICAL_TEAM_ABBRS:
            skipped += 1
            continue
        rows.append(
            {
                "team_abbr": source["team_abbr"],
                "name": source["team_name"],
                "updated_at": updated_at,
            }
        )

    _write(conn, TEAMS_UPSERT, rows)
    return len(rows), skipped


GAMES_UPSERT = """
INSERT INTO games (
  game_id, season, week, game_type, kickoff_at,
  home_team, away_team, is_dome, updated_at
)
VALUES (
  :game_id, :season, :week, :game_type, :kickoff_at,
  :home_team, :away_team, :is_dome, :updated_at
)
ON CONFLICT(game_id) DO UPDATE SET
  season = excluded.season,
  week = excluded.week,
  game_type = excluded.game_type,
  kickoff_at = excluded.kickoff_at,
  home_team = excluded.home_team,
  away_team = excluded.away_team,
  is_dome = excluded.is_dome,
  updated_at = excluded.updated_at
"""


def kickoff_to_utc(gameday: str, gametime: str) -> str:
    """Combine an nflverse date and Eastern clock time into a UTC ISO-8601 string."""
    local = datetime.strptime(f"{gameday} {gametime}", "%Y-%m-%d %H:%M")
    return local.replace(tzinfo=EASTERN).astimezone(timezone.utc).isoformat(timespec="seconds")


def load_games(conn: sqlite3.Connection, season: int) -> tuple[int, int]:
    """Upsert one season's schedule. Returns (upserted, skipped)."""
    frame = nflverse.schedules(season)
    updated_at = _utc_now()

    columns = [
        "game_id", "season", "week", "game_type",
        "gameday", "gametime", "home_team", "away_team", "roof",
    ]

    rows: list[dict] = []
    skipped = 0
    for source in frame.select(columns).iter_rows(named=True):
        # A scheduled game with no kickoff time yet cannot satisfy kickoff_at NOT NULL.
        if not source["gameday"] or not source["gametime"]:
            skipped += 1
            continue

        rows.append(
            {
                "game_id": source["game_id"],
                "season": source["season"],
                "week": source["week"],
                "game_type": source["game_type"],
                "kickoff_at": kickoff_to_utc(source["gameday"], source["gametime"]),
                "home_team": source["home_team"],
                "away_team": source["away_team"],
                "is_dome": 1 if source["roof"] in DOME_ROOFS else 0,
                "updated_at": updated_at,
            }
        )

    _write(conn, GAMES_UPSERT, rows)
    return len(rows), skipped


PLAYERS_UPSERT = """
INSERT INTO players (player_id, name, position, team_abbr, updated_at)
VALUES (:player_id, :name, :position, :team_abbr, :updated_at)
ON CONFLICT(player_id) DO UPDATE SET
  name = excluded.name,
  position = excluded.position,
  team_abbr = excluded.team_abbr,
  updated_at = excluded.updated_at
"""


def load_players(conn: sqlite3.Connection, season: int) -> tuple[int, int]:
    """Upsert one season's skill-position players. Returns (upserted, skipped)."""
    frame = nflverse.rosters(season)
    updated_at = _utc_now()

    rows: list[dict] = []
    skipped = 0
    for source in frame.select(["gsis_id", "full_name", "position", "team"]).iter_rows(named=True):
        if source["position"] not in SKILL_POSITIONS:
            continue

        # A few roster rows carry no GSIS id, and that id is the join key every
        # weekly table depends on. An unkeyable player is worse than a missing one.
        if not source["gsis_id"]:
            skipped += 1
            continue

        rows.append(
            {
                "player_id": source["gsis_id"],
                "name": source["full_name"],
                "position": source["position"],
                "team_abbr": source["team"],
                "updated_at": updated_at,
            }
        )

    _write(conn, PLAYERS_UPSERT, rows)
    return len(rows), skipped
