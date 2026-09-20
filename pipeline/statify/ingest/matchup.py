"""Turn what a defense allowed into how good that was, relative to the league.

team_defense_weekly says a defense allowed 0.31 EPA per play. That is not a
matchup factor until you know receivers average 0.24 against everyone. The
subtraction is this module's whole job, and both sides of it are strictly prior:
a week N row sees only weeks before N.

The league baseline is measured over the same weeks the defense's own window
covers, not over the calendar. A defense whose last three games were weeks 5, 7
and 8 is compared against what the league allowed in weeks 5, 7 and 8. Comparing
it against a season-long league average instead would mix two time scales and
quietly reward every defense that had a bye in a high-scoring week.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict

from statify.ingest.common import utc_now, write
from statify.ingest.usage import share
from statify.ingest.windows import paired_sum, prior_games, window_slice

# Same three windows as feature 11, minus the exponential one: the build plan
# asks for recency weighting in feature 11, not here.
WINDOWS: tuple[tuple[str, int | None], ...] = (("l3", 3), ("l5", 5), ("std", None))

LeagueTotals = dict[tuple[str, str, int], tuple[int, float]]


def league_week_totals(rows: list[dict]) -> LeagueTotals:
    """Every defense's plays and EPA allowed, summed per position, play type and week."""
    totals: dict[tuple[str, str, int], list] = defaultdict(lambda: [0, 0.0])
    for row in rows:
        entry = totals[(row["position"], row["play_type"], row["week"])]
        entry[0] += row["plays"]
        entry[1] += row["epa_allowed"]
    return {key: (plays, epa) for key, (plays, epa) in totals.items()}


def league_rate(
    totals: LeagueTotals, position: str, play_type: str, weeks: set[int]
) -> float | None:
    """What the whole league allowed over exactly these weeks.

    A ratio of sums, so a 14-game week counts for more than a 6-game one. None
    when no week in the set was played, which is the state a week 1 row is in.
    """
    plays = 0
    epa = 0.0
    for week in weeks:
        if (position, play_type, week) in totals:
            week_plays, week_epa = totals[(position, play_type, week)]
            plays += week_plays
            epa += week_epa
    return share(epa, plays)


def matchup_row(
    team_abbr: str,
    season: int,
    week: int,
    position: str,
    play_type: str,
    history: list[dict],
    totals: LeagueTotals,
    updated_at: str,
) -> dict:
    """One defense's standing in one bucket, entering one week."""
    row = {
        "team_abbr": team_abbr,
        "season": season,
        "week": week,
        "position": position,
        "play_type": play_type,
        "updated_at": updated_at,
    }
    prior = prior_games(history, week)

    for suffix, size in WINDOWS:
        weeks = window_slice(prior, size)
        epa, plays = paired_sum(weeks, "epa_allowed", "plays")
        rate = share(epa, plays)
        league = league_rate(totals, position, play_type, {w["week"] for w in weeks})

        row[f"weeks_{suffix}"] = len(weeks)
        row[f"plays_{suffix}"] = int(plays)
        row[f"epa_allowed_per_play_{suffix}"] = rate
        row[f"league_epa_allowed_per_play_{suffix}"] = league
        # None rather than 0.0 when either side is missing. Zero is a claim
        # ("exactly league average"), not an absence.
        row[f"epa_allowed_over_league_{suffix}"] = (
            rate - league if rate is not None and league is not None else None
        )
    return row


def matchup_rows(rows: list[dict], updated_at: str) -> list[dict]:
    """A row per defense, per week it played, per bucket the season contains.

    Every bucket, not only the ones a defense happened to face that week. A
    factor describes what a defense allowed *before* this week, so it is well
    defined whether or not this week's opponent happens to hand the ball to a
    tight end. Emitting only the buckets that occurred left feature 18 unable to
    look up a factor that existed: entering week 18 of 2024 all 32 defenses had
    prior sack history and only 25 carried a QB pass row.

    Buckets come from the data rather than from the cross product of positions
    and play types, so a combination the season never contained is not invented.
    """
    totals = league_week_totals(rows)

    histories: dict[tuple[str, int, str, str], list[dict]] = defaultdict(list)
    weeks_played: dict[tuple[str, int], set[int]] = defaultdict(set)
    buckets: set[tuple[str, str]] = set()
    for row in rows:
        histories[(row["team_abbr"], row["season"], row["position"], row["play_type"])].append(row)
        weeks_played[(row["team_abbr"], row["season"])].add(row["week"])
        buckets.add((row["position"], row["play_type"]))

    out = []
    for (team_abbr, season), weeks in sorted(weeks_played.items()):
        for week in sorted(weeks):
            for position, play_type in sorted(buckets):
                out.append(
                    matchup_row(
                        team_abbr, season, week, position, play_type,
                        histories.get((team_abbr, season, position, play_type), []),
                        totals, updated_at,
                    )
                )
    return out


KEY_COLUMNS = ("team_abbr", "season", "week", "position", "play_type")

WINDOW_COLUMNS = (
    "weeks",
    "plays",
    "epa_allowed_per_play",
    "league_epa_allowed_per_play",
    "epa_allowed_over_league",
)


def columns() -> list[str]:
    """Every column of team_matchup_weekly, in a fixed order.

    Generated rather than spelled out, though 21 columns is under the threshold
    where form.py gave up on writing statements by hand. The reason is
    different: these names already come from looping WINDOWS in matchup_row, and
    a hand-written statement would be a second place to keep in step with it.
    """
    names = list(KEY_COLUMNS)
    for suffix, _ in WINDOWS:
        names.extend(f"{column}_{suffix}" for column in WINDOW_COLUMNS)
    names.append("updated_at")
    return names


def _upsert_sql() -> str:
    names = columns()
    assignments = ",\n  ".join(
        f"{name} = excluded.{name}" for name in names if name not in KEY_COLUMNS
    )
    return (
        f"INSERT INTO team_matchup_weekly ({', '.join(names)})\n"
        f"VALUES ({', '.join(':' + name for name in names)})\n"
        f"ON CONFLICT({', '.join(KEY_COLUMNS)}) DO UPDATE SET\n"
        f"  {assignments}\n"
    )


MATCHUP_UPSERT = _upsert_sql()

DEFENSE_QUERY = """
SELECT team_abbr, season, week, position, play_type, plays, epa_allowed
FROM team_defense_weekly
WHERE season = ?
ORDER BY team_abbr, position, play_type, week
"""


def _require_defense(conn: sqlite3.Connection, season: int) -> None:
    """Refuse to run before compute defense has.

    Migration 019 empties team_defense_weekly, so an empty input is the expected
    state on a first run here rather than an unlikely one. Writing a table of
    NULLs and reporting success would be the wrong answer to the most likely
    situation.
    """
    count = conn.execute(
        "SELECT COUNT(*) FROM team_defense_weekly WHERE season = ?", (season,)
    ).fetchone()[0]
    if count == 0:
        raise RuntimeError(
            f"no defensive splits for {season}; matchup factors are built from them. "
            f"Run: statify compute defense --season {season}"
        )


def load_matchup(conn: sqlite3.Connection, season: int) -> tuple[int, int]:
    """Compute and upsert one season's matchup factors. Returns (rows, rows_with_no_prior).

    Takes no week filter, for feature 11's reason: a week's factor depends on
    every earlier week, so the season is the unit.
    """
    _require_defense(conn, season)
    rows = [dict(row) for row in conn.execute(DEFENSE_QUERY, (season,))]
    out = matchup_rows(rows, utc_now())
    write(conn, MATCHUP_UPSERT, out)
    return len(out), sum(1 for row in out if row["weeks_std"] == 0)
