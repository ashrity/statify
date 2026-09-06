"""Compute what each defense allowed per week, by the position it faced.

Nothing upstream publishes this, so every number here is a definition rather
than a value that can be checked against a box score. The guard is the shape of
the result: EPA allowed on passes to receivers comes out clearly positive and on
runs to backs slightly negative. An inversion means the attribution broke.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

from statify.ingest.common import utc_now, write
from statify.sources import nflverse

SEASON_TYPES = frozenset({"REG", "POST"})

PBP_COLUMNS = [
    "season",
    "week",
    "season_type",
    "defteam",
    "epa",
    "pass",
    "rush",
    "sack",
    "receiver_player_id",
    "rusher_player_id",
    "touchdown",
    "two_point_attempt",
]

DEFENSE_UPSERT = """
INSERT INTO team_defense_weekly (
  team_abbr, season, week, position,
  plays, epa_allowed, epa_allowed_per_play, touchdowns_allowed, updated_at
)
VALUES (
  :team_abbr, :season, :week, :position,
  :plays, :epa_allowed, :epa_allowed_per_play, :touchdowns_allowed, :updated_at
)
ON CONFLICT(team_abbr, season, week, position) DO UPDATE SET
  plays = excluded.plays,
  epa_allowed = excluded.epa_allowed,
  epa_allowed_per_play = excluded.epa_allowed_per_play,
  touchdowns_allowed = excluded.touchdowns_allowed,
  updated_at = excluded.updated_at
"""


def position_faced(play: dict, positions: dict[str, str]) -> str | None:
    """The position a defense was facing on this play, or None if it has none.

    A sack is the case worth watching: it carries pass = 1 with no receiver, so
    anything that reads the receiver id without checking gets None from the
    position map and could quietly bucket it somewhere.
    """
    if play.get("two_point_attempt") == 1:
        return None
    if play.get("rush") == 1:
        player_id = play.get("rusher_player_id")
    elif play.get("pass") == 1:
        player_id = play.get("receiver_player_id")
    else:
        return None
    return positions.get(player_id) if player_id else None


def exclusion_reason(play: dict, positions: dict[str, str]) -> str:
    """Why a play carries no position. Reported so the gap is never silent."""
    if play.get("two_point_attempt") == 1:
        return "two-point attempt"
    if play.get("sack") == 1:
        return "sack"
    player_id = (
        play.get("rusher_player_id") if play.get("rush") == 1 else play.get("receiver_player_id")
    )
    if not player_id:
        return "no player credited"
    return "player not in players table"


def aggregate_defense(
    plays: list[dict], positions: dict[str, str]
) -> tuple[list[dict], Counter]:
    """Group plays into per team, week and position totals.

    The per-play rate is a ratio of sums, never a mean of per-play values and
    never a mean of weekly rates. Both of those produce a plausible number that
    is wrong, which is the failure this table cannot detect on its own.
    """
    totals: dict[tuple, dict] = defaultdict(
        lambda: {"plays": 0, "epa_allowed": 0.0, "touchdowns_allowed": 0}
    )
    excluded: Counter = Counter()

    for play in plays:
        if play.get("season_type") not in SEASON_TYPES or not play.get("defteam"):
            continue
        if play.get("pass") != 1 and play.get("rush") != 1:
            continue

        position = position_faced(play, positions)
        if position is None:
            excluded[exclusion_reason(play, positions)] += 1
            continue
        if play.get("epa") is None:
            excluded["no epa on the play"] += 1
            continue

        bucket = totals[(play["defteam"], play["season"], play["week"], position)]
        bucket["plays"] += 1
        bucket["epa_allowed"] += play["epa"]
        if play.get("touchdown") == 1:
            bucket["touchdowns_allowed"] += 1

    rows = [
        {
            "team_abbr": team,
            "season": season,
            "week": week,
            "position": position,
            "plays": t["plays"],
            "epa_allowed": t["epa_allowed"],
            "epa_allowed_per_play": t["epa_allowed"] / t["plays"],
            "touchdowns_allowed": t["touchdowns_allowed"],
        }
        for (team, season, week, position), t in sorted(totals.items())
    ]
    return rows, excluded


def load_team_defense(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, Counter]:
    """Compute and upsert one season's defensive splits. Returns (rows, excluded)."""
    positions = {
        row[0]: row[1] for row in conn.execute("SELECT player_id, position FROM players")
    }
    frame = nflverse.pbp(season, PBP_COLUMNS)
    plays = [
        play
        for play in frame.iter_rows(named=True)
        if week is None or play["week"] == week
    ]

    rows, excluded = aggregate_defense(plays, positions)
    updated_at = utc_now()
    for row in rows:
        row["updated_at"] = updated_at

    write(conn, DEFENSE_UPSERT, rows)
    return len(rows), excluded
