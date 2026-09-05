"""Load snap counts onto weekly_actuals.

This loader owns snaps and snap_share and nothing else: the weekly loader owns
the box score columns and the play-by-play pass owns red_zone_touches.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import normalize_team, utc_now, write_all
from statify.sources import nflverse

SOURCE_COLUMNS = [
    "game_id",
    "season",
    "week",
    "pfr_player_id",
    "team",
    "offense_snaps",
    "offense_pct",
]

SNAP_UPDATE = """
UPDATE weekly_actuals
SET snaps = :snaps, snap_share = :snap_share, updated_at = :updated_at
WHERE player_id = :player_id AND game_id = :game_id
"""

# Names only the keys and this loader's own columns; every counting stat takes
# its DEFAULT 0, which is the honest value for a player who was on the field and
# recorded nothing. red_zone_touches stays NULL until the play-by-play pass runs.
SNAP_INSERT = """
INSERT INTO weekly_actuals (
  player_id, game_id, season, week, team_abbr, snaps, snap_share, updated_at
)
VALUES (
  :player_id, :game_id, :season, :week, :team_abbr, :snaps, :snap_share, :updated_at
)
ON CONFLICT(player_id, game_id) DO UPDATE SET
  snaps = excluded.snaps,
  snap_share = excluded.snap_share,
  updated_at = excluded.updated_at
"""


def should_insert_orphan(source: dict) -> bool:
    """Whether a snap row with no weekly_actuals row deserves one.

    A player with offensive snaps and no box-score line is a real zero, and it is
    the denominator feature 10's snap share needs. A player with none is special
    teams only: inserting them would add a row that is zero in every column this
    project reads.
    """
    return (source["offense_snaps"] or 0) > 0


def snap_row(source: dict, player_id: str, updated_at: str) -> dict:
    """Build the stored row from one snap-count record.

    offense_pct arrives as a 0-to-1 fraction and is stored unrounded; rounding
    here would quietly change feature 10's snap share.
    """
    return {
        "player_id": player_id,
        "game_id": source["game_id"],
        "season": source["season"],
        "week": source["week"],
        "team_abbr": normalize_team(source["team"]),
        "snaps": int(source["offense_snaps"] or 0),
        "snap_share": source["offense_pct"],
        "updated_at": updated_at,
    }


def _crosswalk(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT pfr_id, player_id FROM players WHERE pfr_id IS NOT NULL"
    ).fetchall()
    if not rows:
        raise RuntimeError(
            "no players carry a pfr_id, so no snap row can be resolved. "
            "Run: statify ingest players --season <year>"
        )
    return {row[0]: row[1] for row in rows}


def load_snap_counts(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int, int, int]:
    """Fill snaps and snap_share. Returns (updated, inserted, unresolved, st_only)."""
    crosswalk = _crosswalk(conn)
    existing = {
        (row[0], row[1])
        for row in conn.execute(
            "SELECT player_id, game_id FROM weekly_actuals WHERE season = ?", (season,)
        )
    }
    frame = nflverse.snap_counts(season).select(SOURCE_COLUMNS)
    updated_at = utc_now()

    updates: list[dict] = []
    inserts: list[dict] = []
    unresolved = 0
    special_teams_only = 0
    for source in frame.iter_rows(named=True):
        if week is not None and source["week"] != week:
            continue

        player_id = crosswalk.get(source["pfr_player_id"])
        if player_id is None:
            # Mostly non-skill players we never stored, plus a few fringe
            # players with no Pro Football Reference page at all.
            unresolved += 1
            continue

        row = snap_row(source, player_id, updated_at)
        if (player_id, source["game_id"]) in existing:
            updates.append(row)
        elif should_insert_orphan(source):
            inserts.append(row)
        else:
            special_teams_only += 1

    write_all(conn, [(SNAP_UPDATE, updates), (SNAP_INSERT, inserts)])
    return len(updates), len(inserts), unresolved, special_teams_only
