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
