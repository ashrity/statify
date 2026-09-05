"""The only module that imports the nflverse data library.

Keeping every upstream call behind this boundary is what makes swapping the
source, or stubbing it in a test, a one-file change.
"""

from __future__ import annotations

from typing import Any, Callable

import nflreadpy as nfl
import polars as pl


def _pull(name: str, fn: Callable[..., Any], **kwargs: Any) -> pl.DataFrame:
    try:
        frame = fn(**kwargs)
    except Exception as exc:
        raise RuntimeError(f"nflverse {name} pull failed: {exc}") from exc

    if frame.height == 0:
        raise RuntimeError(f"nflverse {name} pull returned no rows")
    return frame


def teams() -> pl.DataFrame:
    return _pull("teams", nfl.load_teams)


def schedules(season: int) -> pl.DataFrame:
    return _pull("schedules", nfl.load_schedules, seasons=[season])


def rosters(season: int) -> pl.DataFrame:
    return _pull("rosters", nfl.load_rosters, seasons=[season])


def player_stats(season: int) -> pl.DataFrame:
    """Weekly per-player box-score stats. Carries game_id, so no schedule join is needed."""
    return _pull(
        "player_stats",
        nfl.load_player_stats,
        seasons=[season],
        summary_level="week",
    )


def pbp(season: int, columns: list[str]) -> pl.DataFrame:
    """Play-by-play, narrowed on arrival.

    A season is roughly 49k rows by 372 columns, and nothing downstream wants the
    other 360, so the projection happens here rather than in the caller.
    """
    return _pull("pbp", nfl.load_pbp, seasons=[season]).select(columns)


# Next Gen Stats is tracking data, which the league only publishes from 2016.
NGS_FIRST_SEASON = 2016


def next_gen_stats(season: int, stat_type: str) -> pl.DataFrame:
    """One NGS feed for one season. stat_type is passing, receiving, or rushing."""
    if season < NGS_FIRST_SEASON:
        raise RuntimeError(
            f"Next Gen Stats begins in {NGS_FIRST_SEASON}; {season} has none. "
            "Player tracking was not published before then."
        )
    return _pull(
        f"next_gen_stats {stat_type}",
        nfl.load_nextgen_stats,
        seasons=[season],
        stat_type=stat_type,
    )
