"""Compute what each defense does: coverage shell, pass rush, and pressure.

Feature 13a rated defenses against the league. This one ranks nobody. A defense
playing man 61% of the time is not better than one playing zone, it is a
different problem, and feature 18 pairs that with what a receiver is good at.

READ THIS BEFORE COMPARING man_rate TO A PUBLISHED FIGURE. Measured on 2024 the
league man rate here is 48.5%, where Next Gen Stats and PFF both report nearer
30 to 35%. They chart to different definitions, the same way this project's
yacoe differs from the Next Gen Stats column of that name. A man rate from this
table is comparable only to another man rate from this table. The ordering is
what survives, and the ordering is right: Denver and Detroit most man, Green
Bay most zone, Minnesota most blitz.

The counts come from two feeds that cover different plays, which is why each
rate keeps its own denominator. Coverage is charted only where nflverse
classified the shell, pass rusher counts only where it recorded a number, and
sacks come from play-by-play, which has every dropback.
"""

from __future__ import annotations

import sqlite3
from collections import Counter, defaultdict

from statify.ingest.common import utc_now, write
from statify.ingest.usage import share
from statify.ingest.windows import paired_sum, prior_games, window_slice
from statify.sources import nflverse

SEASON_TYPES = frozenset({"REG", "POST"})

# The same three windows as features 11 and 13a, minus the exponential one: the
# build plan asks for recency weighting in feature 11, not here.
WINDOWS: tuple[tuple[str, int | None], ...] = (("l3", 3), ("l5", 5), ("std", None))

MAN_COVERAGE = "MAN_COVERAGE"
ZONE_COVERAGE = "ZONE_COVERAGE"
COVERAGE_SHELLS = frozenset({MAN_COVERAGE, ZONE_COVERAGE})

# Five or more rushers is the standard definition of a blitz: four is the base
# rush that almost every front sends.
BLITZ_RUSHERS = 5

# A defense fields eleven players, so it cannot rush more. One 2024 row claims
# 45. Values outside the range are dropped and counted rather than averaged,
# because a single absurd number survives review inside a weekly mean.
MIN_RUSHERS = 1
MAX_RUSHERS = 11

COUNT_FIELDS = (
    "coverage_snaps", "man_snaps",
    "rusher_snaps", "blitz_snaps", "pass_rushers",
    "dropbacks", "sacks", "qb_hits",
)


def _new_counts() -> dict[str, int]:
    return dict.fromkeys(COUNT_FIELDS, 0)


def is_defensive_snap(play: dict) -> bool:
    """A scrimmage play with a defense to credit.

    Special teams are excluded because participation covers punts, where the
    charting columns describe a return unit rather than a coverage shell.
    """
    return (
        play.get("season_type") in SEASON_TYPES
        and bool(play.get("defteam"))
        and play.get("special_teams_play") != 1
    )


def play_index(plays: list[dict]) -> dict[tuple[str, int], dict]:
    """(game_id, play_id) to play, over every play.

    Deliberately unfiltered. Filtering here would make a punt indistinguishable
    from a play that is genuinely missing, and "no matching play" is the signal
    that the feeds have drifted apart. A punt is not drift; it is a play we
    chose not to count, and `is_defensive_snap` is where that choice lives.
    """
    return {(play["game_id"], play["play_id"]): play for play in plays}


def pressure_counts(plays: list[dict]) -> dict[tuple[str, int], dict[str, int]]:
    """Dropbacks, sacks and QB hits per defense per week, from play-by-play alone."""
    totals: dict[tuple[str, int], dict[str, int]] = defaultdict(_new_counts)
    for play in plays:
        if not is_defensive_snap(play) or play.get("qb_dropback") != 1:
            continue
        counts = totals[(play["defteam"], play["week"])]
        counts["dropbacks"] += 1
        counts["sacks"] += 1 if play.get("sack") == 1 else 0
        counts["qb_hits"] += 1 if play.get("qb_hit") == 1 else 0
    return totals


def charting_counts(
    rows: list[dict], index: dict[tuple[str, int], dict]
) -> tuple[dict[tuple[str, int], dict[str, int]], Counter]:
    """Coverage and pass rusher counts per defense per week.

    Returns the totals and a tally of what was skipped, so a feed that changes
    shape upstream shows up as a number rather than as a quietly smaller
    denominator.
    """
    totals: dict[tuple[str, int], dict[str, int]] = defaultdict(_new_counts)
    skipped: Counter = Counter()

    for row in rows:
        play = index.get((row["nflverse_game_id"], row["play_id"]))
        if play is None:
            skipped["no matching play"] += 1
            continue
        if not is_defensive_snap(play) or play.get("qb_dropback") != 1:
            continue
        counts = totals[(play["defteam"], play["week"])]

        # Empty string, not NULL, on a play nflverse did not classify. An
        # IS NOT NULL filter keeps all of them and halves the man rate.
        shell = (row.get("defense_man_zone_type") or "").strip()
        if shell in COVERAGE_SHELLS:
            counts["coverage_snaps"] += 1
            counts["man_snaps"] += 1 if shell == MAN_COVERAGE else 0

        rushers = row.get("number_of_pass_rushers")
        if rushers is not None:
            if MIN_RUSHERS <= rushers <= MAX_RUSHERS:
                counts["rusher_snaps"] += 1
                counts["blitz_snaps"] += 1 if rushers >= BLITZ_RUSHERS else 0
                counts["pass_rushers"] += rushers
            elif rushers != 0:
                skipped["pass rusher count out of range"] += 1
    return totals, skipped


def aggregate_counts(
    participation: list[dict], plays: list[dict]
) -> tuple[dict[tuple[str, int], dict[str, int]], Counter]:
    """Every count for every defense week, from both feeds."""
    pressure = pressure_counts(plays)
    charting, skipped = charting_counts(participation, play_index(plays))

    totals: dict[tuple[str, int], dict[str, int]] = defaultdict(_new_counts)
    for source in (pressure, charting):
        for key, counts in source.items():
            for field, value in counts.items():
                totals[key][field] += value
    return dict(totals), skipped


# Each rate against the denominator counted over the same plays as its
# numerator. The three denominators differ because the feeds do: coverage is
# charted only where nflverse classified a shell, rusher counts only where it
# recorded a number, and sacks come from play-by-play, which has every
# dropback. Dividing one feed's numerator by another's would be a plausible
# number computed from two populations.
RATES = {
    "man_rate": ("man_snaps", "coverage_snaps"),
    "blitz_rate": ("blitz_snaps", "rusher_snaps"),
    "pass_rushers_per_snap": ("pass_rushers", "rusher_snaps"),
    "sack_rate": ("sacks", "dropbacks"),
    "qb_hit_rate": ("qb_hits", "dropbacks"),
}


def tendency_row(
    team_abbr: str, season: int, week: int, counts: dict[str, int], updated_at: str
) -> dict:
    """One defense's tendencies for one week, counts and rates together."""
    row: dict = {"team_abbr": team_abbr, "season": season, "week": week}
    row.update({field: counts[field] for field in COUNT_FIELDS})
    for name, (numerator, denominator) in RATES.items():
        row[name] = share(counts[numerator], counts[denominator])
    row["updated_at"] = updated_at
    return row


def window_rates(weeks: list[dict]) -> dict[str, float | None]:
    """The five rates over a set of weeks, each a ratio of sums.

    Never a mean of weekly rates. A week where a defense faced 14 charted snaps
    must not weigh the same as one where it faced 63, and 2024 contains both.
    """
    return {
        name: share(*paired_sum(weeks, numerator, denominator))
        for name, (numerator, denominator) in RATES.items()
    }


def tendency_rows(
    totals: dict[tuple[str, int], dict[str, int]], season: int, updated_at: str
) -> list[dict]:
    """A row per defense per week, each window built only from earlier weeks.

    The boundary is feature 11a's and is reused rather than reimplemented. A
    week N row must see only weeks before N; a leak here would leave every
    number looking entirely reasonable.
    """
    histories: dict[str, list[dict]] = defaultdict(list)
    for (team_abbr, week), counts in totals.items():
        histories[team_abbr].append({"week": week, **counts})

    rows = []
    for team_abbr, history in sorted(histories.items()):
        for game in sorted(history, key=lambda g: g["week"]):
            row = tendency_row(team_abbr, season, game["week"], game, updated_at)
            prior = prior_games(history, game["week"])
            for suffix, size in WINDOWS:
                weeks = window_slice(prior, size)
                row[f"weeks_{suffix}"] = len(weeks)
                for name, value in window_rates(weeks).items():
                    row[f"{name}_{suffix}"] = value
            rows.append(row)
    return rows


KEY_COLUMNS = ("team_abbr", "season", "week")

PBP_COLUMNS = [
    "game_id",
    "play_id",
    "week",
    "defteam",
    "season_type",
    "qb_dropback",
    "special_teams_play",
    "sack",
    "qb_hit",
]

PARTICIPATION_COLUMNS = [
    "nflverse_game_id",
    "play_id",
    "defense_man_zone_type",
    "number_of_pass_rushers",
]


def columns() -> list[str]:
    """Every column of team_tendency_weekly, in a fixed order.

    Generated from the same constants the rows are, so the statement and the
    dict cannot drift apart. A test asserts they name the same set.
    """
    names = list(KEY_COLUMNS)
    names.extend(COUNT_FIELDS)
    names.extend(RATES)
    for suffix, _ in WINDOWS:
        names.append(f"weeks_{suffix}")
        names.extend(f"{name}_{suffix}" for name in RATES)
    names.append("updated_at")
    return names


def _upsert_sql() -> str:
    names = columns()
    assignments = ",\n  ".join(
        f"{name} = excluded.{name}" for name in names if name not in KEY_COLUMNS
    )
    return (
        f"INSERT INTO team_tendency_weekly ({', '.join(names)})\n"
        f"VALUES ({', '.join(':' + name for name in names)})\n"
        f"ON CONFLICT({', '.join(KEY_COLUMNS)}) DO UPDATE SET\n"
        f"  {assignments}\n"
    )


TENDENCY_UPSERT = _upsert_sql()


def load_tendencies(conn: sqlite3.Connection, season: int) -> tuple[int, int, Counter]:
    """Compute and upsert one season's tendencies.

    Returns (rows, rows_with_no_prior_week, skipped). Takes no week filter: the
    windows need the season, for the same reason compute form does not.
    """
    plays = list(nflverse.pbp(season, PBP_COLUMNS).iter_rows(named=True))
    participation = list(
        nflverse.participation(season, PARTICIPATION_COLUMNS).iter_rows(named=True)
    )

    totals, skipped = aggregate_counts(participation, plays)
    rows = tendency_rows(totals, season, utc_now())

    write(conn, TENDENCY_UPSERT, rows)
    return len(rows), sum(1 for row in rows if row["weeks_std"] == 0), skipped
