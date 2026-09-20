"""Compute what each defense allowed per week, by position faced and play type.

Nothing upstream publishes this, so every number here is a definition rather
than a value that can be checked against a box score. The guard is the shape of
the result: EPA allowed on passes to receivers comes out clearly positive and on
runs to backs slightly negative. An inversion means the attribution broke.

Feature 13a added the play type. Position alone put a back's carries and his
catches in one row and produced no pass bucket at all, so neither a rushing nor
a passing matchup could be asked of it.

Sacks count, as (QB, pass). They were excluded as "no player credited" until
feature 13a, which is true and unhelpful: a sack is the best outcome a pass rush
can produce. The useful consequence is that every play_type = 'pass' row for a
team-week now adds up to a complete dropback.
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
  team_abbr, season, week, position, play_type,
  plays, epa_allowed, epa_allowed_per_play, touchdowns_allowed, updated_at
)
VALUES (
  :team_abbr, :season, :week, :position, :play_type,
  :plays, :epa_allowed, :epa_allowed_per_play, :touchdowns_allowed, :updated_at
)
ON CONFLICT(team_abbr, season, week, position, play_type) DO UPDATE SET
  plays = excluded.plays,
  epa_allowed = excluded.epa_allowed,
  epa_allowed_per_play = excluded.epa_allowed_per_play,
  touchdowns_allowed = excluded.touchdowns_allowed,
  updated_at = excluded.updated_at
"""


SACK_BUCKET = ("QB", "pass")


def bucket(play: dict, positions: dict[str, str]) -> tuple[str, str] | None:
    """The position and play type a defense faced, or None if it has neither.

    Position alone was the old key and it could not answer two of the four
    questions feature 18 asks: a back's carries and his catches shared one row,
    and there was no pass bucket at all, because a pass belongs to whoever
    caught it.

    A sack is the case worth watching. It carries pass = 1 with no receiver, so
    reading the receiver id without checking yields None and the play
    disappears. It used to. A sack is the best outcome a pass rush can produce,
    and dropping it understated exactly the defenses this table exists to find,
    so it counts against the quarterback, the only party a sack can honestly be
    attributed to when no receiver exists.

    (QB, pass) is therefore mostly but not only sacks. 2024 put 1,428 plays
    there against 1,392 sacks: the other 36 are passes a quarterback caught, 31
    of them Taysom Hill, who nflverse lists at QB and who plays everywhere. Both
    belong in the bucket, but a reader expecting pure sack data would be wrong.
    """
    if play.get("two_point_attempt") == 1:
        return None
    if play.get("rush") == 1:
        player_id, play_type = play.get("rusher_player_id"), "rush"
    elif play.get("pass") == 1:
        if play.get("sack") == 1:
            return SACK_BUCKET
        player_id, play_type = play.get("receiver_player_id"), "pass"
    else:
        return None
    position = positions.get(player_id) if player_id else None
    return (position, play_type) if position else None


def exclusion_reason(play: dict, positions: dict[str, str]) -> str:
    """Why a play carries no bucket. Reported so the gap is never silent."""
    if play.get("two_point_attempt") == 1:
        return "two-point attempt"
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

        faced = bucket(play, positions)
        if faced is None:
            excluded[exclusion_reason(play, positions)] += 1
            continue
        position, play_type = faced
        if play.get("epa") is None:
            excluded["no epa on the play"] += 1
            continue

        totals_key = (play["defteam"], play["season"], play["week"], position, play_type)
        faced_totals = totals[totals_key]
        faced_totals["plays"] += 1
        faced_totals["epa_allowed"] += play["epa"]
        if play.get("touchdown") == 1:
            faced_totals["touchdowns_allowed"] += 1

    rows = [
        {
            "team_abbr": team,
            "season": season,
            "week": week,
            "position": position,
            "play_type": play_type,
            "plays": t["plays"],
            "epa_allowed": t["epa_allowed"],
            "epa_allowed_per_play": t["epa_allowed"] / t["plays"],
            "touchdowns_allowed": t["touchdowns_allowed"],
        }
        for (team, season, week, position, play_type), t in sorted(totals.items())
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
