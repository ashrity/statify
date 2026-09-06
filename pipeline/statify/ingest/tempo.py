"""Compute offensive tempo and pass rate over expected, per team and week.

Both numbers are derived from play-by-play rather than published anywhere, so
both are definitions this module chooses. The pace one is the delicate half: see
`play_intervals` for why there are two of them.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from statify.ingest.common import utc_now, write
from statify.sources import nflverse

SEASON_TYPES = frozenset({"REG", "POST"})

# A longer gap between snaps spans a timeout, injury or replay review. Those are
# stoppages, not tempo.
MAX_GAP_SECONDS = 60

# Situation-neutral: before the fourth quarter and inside one score, which is
# where teams run their preferred tempo rather than racing or bleeding the clock.
NEUTRAL_QUARTERS = frozenset({1, 2, 3})
NEUTRAL_MARGIN = 7

PBP_COLUMNS = [
    "game_id",
    "season",
    "week",
    "season_type",
    "posteam",
    "play_id",
    "fixed_drive",
    "game_seconds_remaining",
    "pass",
    "rush",
    "pass_oe",
    "qtr",
    "score_differential",
    "incomplete_pass",
]

TEMPO_UPSERT = """
INSERT INTO team_tempo_weekly (
  team_abbr, season, week, plays,
  pace_intervals, seconds_per_play, neutral_intervals, neutral_seconds_per_play,
  proe, updated_at
)
VALUES (
  :team_abbr, :season, :week, :plays,
  :pace_intervals, :seconds_per_play, :neutral_intervals, :neutral_seconds_per_play,
  :proe, :updated_at
)
ON CONFLICT(team_abbr, season, week) DO UPDATE SET
  plays = excluded.plays,
  pace_intervals = excluded.pace_intervals,
  seconds_per_play = excluded.seconds_per_play,
  neutral_intervals = excluded.neutral_intervals,
  neutral_seconds_per_play = excluded.neutral_seconds_per_play,
  proe = excluded.proe,
  updated_at = excluded.updated_at
"""


def is_scrimmage_play(play: dict) -> bool:
    return (
        play.get("posteam") is not None
        and play.get("season_type") in SEASON_TYPES
        and (play.get("pass") == 1 or play.get("rush") == 1)
    )


def is_neutral(previous: dict, play: dict) -> bool:
    """Whether an interval reflects preferred tempo rather than game script.

    The previous play matters as much as this one: an incompletion stops the
    clock, so the snap that follows it consumes almost no game time and would
    read as blazing tempo.
    """
    if play.get("qtr") not in NEUTRAL_QUARTERS:
        return False
    margin = play.get("score_differential")
    if margin is None or abs(margin) > NEUTRAL_MARGIN:
        return False
    return previous.get("incomplete_pass") != 1


def play_intervals(plays: list[dict]) -> list[dict]:
    """Seconds between consecutive snaps within a drive.

    Sorts internally rather than trusting the caller. An unordered frame yields
    negative gaps that the filter would quietly discard, leaving a believable
    average computed from a fraction of the plays.
    """
    ordered = sorted(plays, key=lambda p: (p["game_id"], p["play_id"]))
    intervals: list[dict] = []
    previous: dict | None = None

    for play in ordered:
        if (
            previous is not None
            and previous["game_id"] == play["game_id"]
            and previous["fixed_drive"] == play["fixed_drive"]
            and previous["game_seconds_remaining"] is not None
            and play["game_seconds_remaining"] is not None
        ):
            seconds = previous["game_seconds_remaining"] - play["game_seconds_remaining"]
            if 0 < seconds <= MAX_GAP_SECONDS:
                intervals.append(
                    {
                        "team_abbr": play["posteam"],
                        "season": play["season"],
                        "week": play["week"],
                        "seconds": seconds,
                        "neutral": is_neutral(previous, play),
                    }
                )
        previous = play
    return intervals


def _mean(values: list[float]) -> float | None:
    """None rather than zero when there is nothing to average."""
    return sum(values) / len(values) if values else None


def aggregate_tempo(plays: list[dict]) -> list[dict]:
    """Group plays into per team and week tempo rows."""
    scrimmage = [play for play in plays if is_scrimmage_play(play)]
    buckets: dict[tuple, dict] = defaultdict(
        lambda: {"plays": 0, "pace": [], "neutral": [], "proe": []}
    )

    for play in scrimmage:
        bucket = buckets[(play["posteam"], play["season"], play["week"])]
        bucket["plays"] += 1
        if play.get("pass_oe") is not None:
            bucket["proe"].append(play["pass_oe"])

    for interval in play_intervals(scrimmage):
        bucket = buckets[(interval["team_abbr"], interval["season"], interval["week"])]
        bucket["pace"].append(interval["seconds"])
        if interval["neutral"]:
            bucket["neutral"].append(interval["seconds"])

    return [
        {
            "team_abbr": team,
            "season": season,
            "week": week,
            "plays": b["plays"],
            "pace_intervals": len(b["pace"]),
            "seconds_per_play": _mean(b["pace"]),
            "neutral_intervals": len(b["neutral"]),
            "neutral_seconds_per_play": _mean(b["neutral"]),
            "proe": _mean(b["proe"]),
        }
        for (team, season, week), b in sorted(buckets.items())
    ]


def load_team_tempo(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int]:
    """Compute and upsert one season's tempo. Returns (rows, rows_without_neutral)."""
    frame = nflverse.pbp(season, PBP_COLUMNS)
    plays = [
        play for play in frame.iter_rows(named=True) if week is None or play["week"] == week
    ]

    rows = aggregate_tempo(plays)
    updated_at = utc_now()
    for row in rows:
        row["updated_at"] = updated_at

    write(conn, TEMPO_UPSERT, rows)
    return len(rows), sum(1 for row in rows if row["neutral_intervals"] == 0)
