"""The only module that imports the nflverse data library.

Keeping every upstream call behind this boundary is what makes swapping the
source, or stubbing it in a test, a one-file change.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Callable

import nflreadpy as nfl
import polars as pl
from nflreadpy.config import update_config

CACHE_VARIABLE = "NFLREADPY_CACHE"


def cache_mode_to_apply(environ: Mapping[str, str]) -> str | None:
    """"filesystem", or None when the environment has already chosen.

    nflreadpy caches in memory by default, which lasts exactly as long as one
    process. Every statify command is its own process, so nothing was ever
    reused: each compute re-downloaded the whole play-by-play parquet, and a
    GitHub outage on 19 September 2025 stopped all work for twenty minutes
    despite the same file having been fetched several times that session.

    The environment wins when it has an opinion. NFLREADPY_CACHE is the
    documented way to configure this, and it is also the documented way to force
    a fresh pull mid-week when injuries have moved since the last run, so
    overriding it here would remove the escape hatch.
    """
    if (environ.get(CACHE_VARIABLE) or "").strip():
        return None
    return "filesystem"


def _configure_cache() -> None:
    mode = cache_mode_to_apply(os.environ)
    if mode:
        update_config(cache_mode=mode)


_configure_cache()


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


def players_master() -> pl.DataFrame:
    """Every player nflverse knows, with the cross-source id columns.

    Distinct from rosters(), which is one season's active players. This is the
    all-time table, and the only place gsis_id and pfr_id sit side by side.
    """
    return _pull("players_master", nfl.load_players)


def snap_counts(season: int) -> pl.DataFrame:
    """Per-player per-game snap counts, from Pro Football Reference.

    Keyed by pfr_player_id with no GSIS column, which is why players carries
    pfr_id.
    """
    return _pull("snap_counts", nfl.load_snap_counts, seasons=[season])


def depth_charts(season: int) -> pl.DataFrame:
    """Weekly depth charts. Carries gsis_id directly, so no crosswalk is needed."""
    return _pull("depth_charts", nfl.load_depth_charts, seasons=[season])


def injuries(season: int) -> pl.DataFrame:
    """Weekly injury reports. Carries gsis_id directly."""
    return _pull("injuries", nfl.load_injuries, seasons=[season])


def participation(season: int, columns: list[str]) -> pl.DataFrame:
    """Who was on the field for each play. Available from 2016.

    Narrowed on arrival like pbp: the frame is 26 columns wide and only three
    are needed to count routes.
    """
    return _pull("participation", nfl.load_participation, seasons=[season]).select(columns)
