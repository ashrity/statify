"""Load nflverse reference data into the local database."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from statify.ingest.common import utc_now as _utc_now, write as _write
from statify.sources import nflverse

# load_teams() carries 36 rows: the 32 active franchises plus retired aliases that
# share a team_id with a current one. schedules, rosters, and player_stats spell
# the Rams LA, the Raiders LV, and the Chargers LAC, so those are the rows to keep
# and these are the ones to drop. A pre-2016 season would need STL restored, and a
# pre-2020 season OAK and SD.
#
# Not every feed agrees: Next Gen Stats says LAR. Inbound rows go through
# normalize_team() in common.py rather than widening this table.
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
INSERT INTO teams (team_abbr, name, logo_url, color_primary, color_secondary, updated_at)
VALUES (:team_abbr, :name, :logo_url, :color_primary, :color_secondary, :updated_at)
ON CONFLICT(team_abbr) DO UPDATE SET
  name = excluded.name,
  logo_url = excluded.logo_url,
  color_primary = excluded.color_primary,
  color_secondary = excluded.color_secondary,
  updated_at = excluded.updated_at
"""


def load_teams(conn: sqlite3.Connection) -> tuple[int, int]:
    """Upsert the active NFL teams. Returns (upserted, skipped)."""
    frame = nflverse.teams()
    updated_at = _utc_now()

    rows: list[dict] = []
    skipped = 0
    columns = ["team_abbr", "team_name", "team_logo_espn", "team_color", "team_color2"]
    for source in frame.select(columns).iter_rows(named=True):
        if source["team_abbr"] in HISTORICAL_TEAM_ABBRS:
            skipped += 1
            continue
        rows.append(
            {
                "team_abbr": source["team_abbr"],
                "name": source["team_name"],
                "logo_url": source["team_logo_espn"],
                "color_primary": source["team_color"],
                "color_secondary": source["team_color2"],
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


# The WHERE clause is the point: it guards only the conflict path, so a backfill
# still inserts players who have since retired (weekly_actuals has a foreign key
# here), but never drags an existing row back to an older season's team.
# >= rather than > so re-pulling the current season still picks up a midseason
# trade. COALESCE because rows written before migration 004 carry NULL, and NULL
# loses every comparison, which would freeze them forever.
PLAYERS_UPSERT = """
INSERT INTO players (player_id, name, position, team_abbr, roster_season, updated_at)
VALUES (:player_id, :name, :position, :team_abbr, :roster_season, :updated_at)
ON CONFLICT(player_id) DO UPDATE SET
  name = excluded.name,
  position = excluded.position,
  team_abbr = excluded.team_abbr,
  roster_season = excluded.roster_season,
  updated_at = excluded.updated_at
WHERE excluded.roster_season >= COALESCE(players.roster_season, 0)
"""


# Guard-free for the same reason PLAYER_PFR_ID_UPDATE is: a headshot is identity
# rather than roster state. The WHERE clause only avoids rewriting a row that
# already holds this exact URL, so a re-run reports no spurious changes.
PLAYER_HEADSHOT_UPDATE = """
UPDATE players SET headshot_url = :headshot_url, updated_at = :updated_at
WHERE player_id = :player_id
  AND (headshot_url IS NULL OR headshot_url <> :headshot_url)
"""


def load_players(conn: sqlite3.Connection, season: int) -> tuple[int, int, int]:
    """Upsert one season's skill-position players.

    Returns (written, no_gsis_id, kept_newer). The guard on PLAYERS_UPSERT means
    rows sent is not rows changed, so the count comes from total_changes rather
    than len(rows), which would overstate a backfill by every player already
    carrying a more recent roster season.
    """
    frame = nflverse.rosters(season)
    updated_at = _utc_now()

    rows: list[dict] = []
    headshots: list[dict] = []
    skipped = 0
    columns = ["gsis_id", "full_name", "position", "team", "headshot_url"]
    for source in frame.select(columns).iter_rows(named=True):
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
                "roster_season": season,
                "updated_at": updated_at,
            }
        )
        if source["headshot_url"]:
            headshots.append(
                {
                    "player_id": source["gsis_id"],
                    "headshot_url": source["headshot_url"],
                    "updated_at": updated_at,
                }
            )

    before = conn.total_changes
    _write(conn, PLAYERS_UPSERT, rows)
    written = conn.total_changes - before

    # Outside the roster_season guard on purpose, for the same reason pfr_id is:
    # a photo is identity, not roster state, so the guard would leave it NULL on
    # every player already stamped with a newer season.
    _write(conn, PLAYER_HEADSHOT_UPDATE, headshots)
    return written, skipped, len(rows) - written


# Deliberately not part of PLAYERS_UPSERT: that statement is guarded by
# roster_season so an old backfill cannot rewrite a current team, and pfr_id is
# identity rather than roster state. Running it through the guard would leave the
# id NULL on every row already stamped with a newer season.
PLAYER_PFR_ID_UPDATE = """
UPDATE players SET pfr_id = :pfr_id, updated_at = :updated_at
WHERE player_id = :player_id AND (pfr_id IS NULL OR pfr_id <> :pfr_id)
"""


def load_player_ids(conn: sqlite3.Connection) -> tuple[int, int]:
    """Fill pfr_id for players already in the table. Returns (updated, still_missing).

    The master table is all-time and much larger than our roster, so this walks
    it once and keeps only the ids we can actually use.
    """
    known = {row[0] for row in conn.execute("SELECT player_id FROM players")}
    updated_at = _utc_now()

    frame = nflverse.players_master().select(["gsis_id", "pfr_id"])
    rows = [
        {"player_id": source["gsis_id"], "pfr_id": source["pfr_id"], "updated_at": updated_at}
        for source in frame.iter_rows(named=True)
        if source["gsis_id"] in known and source["pfr_id"]
    ]

    before = conn.total_changes
    _write(conn, PLAYER_PFR_ID_UPDATE, rows)
    updated = conn.total_changes - before

    missing = conn.execute("SELECT COUNT(*) FROM players WHERE pfr_id IS NULL").fetchone()[0]
    return updated, missing
