"""Trailing windows over a history of prior weeks.

Extracted from `form.py` when feature 13a needed the same windows keyed by team
rather than by player. Nothing here knows what a metric is: the caller supplies
the field names and decides what to do with the sums.

The boundary in `prior_games` is the piece that matters. A week N value must be
built from weeks strictly before N, and a leak leaves every number downstream
looking entirely reasonable, so feature 11a tests it directly rather than
inferring it from an aggregate.
"""

from __future__ import annotations


def prior_games(history: list[dict], week: int) -> list[dict]:
    """Games before `week`, oldest first.

    Strictly before. `<=` here would leak the week's own result into its own
    form and quietly invalidate every projection built on it.
    """
    return sorted((game for game in history if game["week"] < week), key=lambda g: g["week"])


def window_slice(prior: list[dict], size: int | None) -> list[dict]:
    """The most recent `size` games played, or all of them.

    Counted in games, not weeks. A player who missed a month has a last-3 window
    of his last three appearances; counting weeks would fold the absences in as
    zeros.
    """
    if size is None:
        return prior
    return prior[-size:]


def paired_sum(games: list[dict], numerator: str, denominator: str) -> tuple[float, float]:
    """Sum a numerator and denominator over games where both are present."""
    top = bottom = 0.0
    for game in games:
        if game.get(numerator) is None or game.get(denominator) is None:
            continue
        top += game[numerator]
        bottom += game[denominator]
    return top, bottom
