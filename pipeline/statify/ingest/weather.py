"""Load per-game weather from the nflverse schedule.

Wind and temperature only. nflverse publishes no precipitation, so
precip_chance is left for a future provider and this loader never writes it.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import utc_now, write
from statify.sources import nflverse

SOURCE_COLUMNS = ["game_id", "temp", "wind"]

# precip_chance is absent from both the column list and the conflict update, so
# a later precipitation loader can own it without this one blanking its work.
WEATHER_UPSERT = """
INSERT INTO weather (
  game_id, wind_mph, temperature_f, observed_at, updated_at
)
VALUES (
  :game_id, :wind_mph, :temperature_f, :observed_at, :updated_at
)
ON CONFLICT(game_id) DO UPDATE SET
  wind_mph = excluded.wind_mph,
  temperature_f = excluded.temperature_f,
  observed_at = excluded.observed_at,
  updated_at = excluded.updated_at
"""


def has_reading(source: dict) -> bool:
    """Whether the schedule carries a usable reading for this game.

    Both values are required rather than either. In 2024 they are always both
    present or both absent, but requiring both keeps the rule from silently
    depending on which column happens to be checked first.
    """
    return source["temp"] is not None and source["wind"] is not None


def weather_row(source: dict, observed_at: str, updated_at: str) -> dict:
    return {
        "game_id": source["game_id"],
        "wind_mph": float(source["wind"]),
        "temperature_f": float(source["temp"]),
        "observed_at": observed_at,
        "updated_at": updated_at,
    }


def load_weather(conn: sqlite3.Connection, season: int) -> tuple[int, int, int]:
    """Upsert one season's weather. Returns (upserted, indoor, no_reading)."""
    outdoor = {
        row[0]: row[1]
        for row in conn.execute(
            "SELECT game_id, kickoff_at FROM games WHERE season = ? AND is_dome = 0",
            (season,),
        )
    }
    all_games = {
        row[0] for row in conn.execute("SELECT game_id FROM games WHERE season = ?", (season,))
    }
    if not all_games:
        raise RuntimeError(
            f"no games for {season}. Run: statify ingest games --season {season}"
        )

    frame = nflverse.schedules(season).select(SOURCE_COLUMNS)
    updated_at = utc_now()

    rows: list[dict] = []
    indoor = 0
    no_reading = 0
    for source in frame.iter_rows(named=True):
        game_id = source["game_id"]
        if game_id not in all_games:
            raise RuntimeError(
                f"{game_id} is in the schedule but not in the games table. "
                f"Run: statify ingest games --season {season}"
            )
        if game_id not in outdoor:
            indoor += 1
            continue
        if not has_reading(source):
            no_reading += 1
            continue

        rows.append(weather_row(source, outdoor[game_id], updated_at))

    write(conn, WEATHER_UPSERT, rows)
    return len(rows), indoor, no_reading
