"""One command that pulls new data, recomputes every feature, and regenerates
projections, in the dependency order AGENTS.md has been documenting one
command at a time since feature 2.

ingest props is deliberately excluded: it spends metered, budget-constrained
Odds API credits, and "mid-week, then again near kickoff" is a human-timed
spending decision, not something a refresh should make silently on every
run. ingest teams and ingest stadiums are excluded too, as static reference
data set up once.

redzone runs after snaps, not before, even though AGENTS.md's general ingest
order lists them the other way: the specific note under ingest snaps says
snaps inserts rows for players redzone needs to already exist in order to
fill their red zone touches. The specific note wins.
"""

from __future__ import annotations

from typing import NamedTuple


def step_list(season: int, week: int | None = None) -> list[tuple[str, list[str]]]:
    """(label, argv) for every step, in dependency order."""
    w = ["--week", str(week)] if week is not None else []

    def ingest(name: str, *, weekly: bool = True) -> tuple[str, list[str]]:
        argv = ["ingest", name, "--season", str(season)]
        return (f"ingest {name}", argv + w if weekly else argv)

    def compute(name: str, *, weekly: bool = True) -> tuple[str, list[str]]:
        argv = ["compute", name, "--season", str(season)]
        return (f"compute {name}", argv + w if weekly else argv)

    return [
        ingest("games", weekly=False),
        ingest("players", weekly=False),
        ingest("weekly"),
        ingest("ngs"),
        ingest("snaps"),
        ingest("redzone"),  # after snaps: see module docstring
        ingest("depth"),
        ingest("injuries"),
        ingest("routes"),
        ingest("weather", weekly=False),
        ingest("forecast"),
        ingest("market"),
        compute("defense"),
        compute("matchup", weekly=False),
        compute("tendencies", weekly=False),
        compute("tempo"),
        compute("usage"),
        compute("efficiency"),
        compute("form", weekly=False),
        compute("volume"),
        compute("environment", weekly=False),
        compute("opportunity"),
        compute("expected-efficiency"),
        compute("touchdowns"),
        compute("matchup-adjustment"),
        compute("projection"),
        compute("generate-projections"),
        compute("edge"),
        compute("confidence"),
        compute("backtest"),
        compute("accuracy"),
    ]


class StepResult(NamedTuple):
    label: str
    ok: bool
    error: str | None


def run_refresh(season: int, week: int | None = None, dispatch=None) -> list[StepResult]:
    """Run every step, catching and recording a failure rather than raising it.

    `dispatch` defaults to cli.main, imported lazily here (not at module
    level) because cli.py imports this module to register the `refresh`
    subcommand; importing cli.main at the top of this file would be
    circular.
    """
    if dispatch is None:
        from statify.cli import main as dispatch

    results = []
    for label, argv in step_list(season, week):
        try:
            dispatch(argv)
            results.append(StepResult(label, True, None))
        except Exception as exc:
            # Deliberately broad: a step's own failure (known 2026 gaps,
            # missing an API key, anything) must not abort the remaining steps.
            results.append(StepResult(label, False, str(exc)))
    return results
