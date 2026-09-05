"""Load weekly offensive depth charts."""

from __future__ import annotations

import sqlite3

from statify.ingest.common import normalize_team, utc_now, write
from statify.sources import nflverse

# The feed lists a player once per formation and depth position, so an RB shows
# up as RB3 on offense plus PR1 and KOR1 on special teams. Only the offensive
# listing says anything about the usage this project models, and keeping the rest
# would break the (player_id, season, week) primary key.
OFFENSE = "Offense"

SOURCE_COLUMNS = ["season", "week", "club_code", "gsis_id", "position", "depth_team", "formation"]

DEPTH_UPSERT = """
INSERT INTO depth_charts (
  player_id, season, week, team_abbr, position, depth_rank, updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr, :position, :depth_rank, :updated_at
)
ON CONFLICT(player_id, season, week) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  position = excluded.position,
  depth_rank = excluded.depth_rank,
  updated_at = excluded.updated_at
"""


def depth_row(source: dict, updated_at: str) -> dict:
    return {
        "player_id": source["gsis_id"],
        "season": source["season"],
        "week": source["week"],
        "team_abbr": normalize_team(source["club_code"]),
        "position": source["position"],
        "depth_rank": int(source["depth_team"]),
        "updated_at": updated_at,
    }


def dedupe_depth_rows(rows: list[dict]) -> list[dict]:
    """Collapse a player week to its best listed rank.

    209 duplicate keys survive the offense filter for 2024, all of them literal
    repeats. Taking the minimum makes an identical pair a no-op and resolves a
    genuine disagreement toward the more prominent listing rather than whichever
    row happened to arrive last.
    """
    best: dict[tuple[str, int, int], dict] = {}
    for row in rows:
        key = (row["player_id"], row["season"], row["week"])
        current = best.get(key)
        if current is None or row["depth_rank"] < current["depth_rank"]:
            best[key] = row
    return list(best.values())


def load_depth_charts(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int]:
    """Upsert one season's offensive depth chart. Returns (upserted, skipped)."""
    frame = nflverse.depth_charts(season).select(SOURCE_COLUMNS)
    known_players = {row[0] for row in conn.execute("SELECT player_id FROM players")}
    updated_at = utc_now()

    rows: list[dict] = []
    skipped = 0
    for source in frame.iter_rows(named=True):
        if source["formation"] != OFFENSE:
            continue
        # The Super Bowl bye carries no week and no game to attach to.
        if source["week"] is None or not source["depth_team"]:
            skipped += 1
            continue
        if week is not None and source["week"] != week:
            continue
        if source["gsis_id"] not in known_players:
            skipped += 1
            continue

        rows.append(depth_row(source, updated_at))

    deduped = dedupe_depth_rows(rows)
    write(conn, DEPTH_UPSERT, deduped)
    return len(deduped), skipped
