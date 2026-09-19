"""Compute what each player did with the opportunity he got, per game.

Feature 10 stored the opportunity; this is the other half. Most of it is
division over counts already in the database, but the two "over expected"
metrics need a pass over play-by-play, because the expectations live there:
`cp` is a per-throw completion probability and `xyac_mean_yardage` is expected
yards after catch.

Both of those sums keep their own denominator. `cp` is missing on 1 target in
17,748 and `xyac_mean_yardage` on 5% of completions, so an expected sum built
from 95% of the plays divided by an actual count built from 100% of them would
read low every time, with nothing downstream to flag it.

The yards-after-catch expectation here is the nflverse model, not the Next Gen
Stats one. They disagree: over 1,302 receiver weeks the mean difference is 0.95
yards and they agree within a yard only 30% of the time. This one is used
because NGS publishes nothing at all for running backs.

One number here is knowingly biased. `yprr` divides by the route counts feature
10b derived, and those count a player on the field for a dropback, so a back who
stayed in to block is counted as having run a route. Measured on 2024 the error
is small for receivers (Nacua 3.21, Collins 2.86, both within about 0.1 of the
published figures) and about 25% for backs, whose yprr therefore reads about
that much low. Migrations 015 and 016 and AGENTS.md carry the same warning.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import NamedTuple

from statify.ingest.common import utc_now, write
from statify.ingest.usage import share
from statify.sources import nflverse

SEASON_TYPES = frozenset({"REG", "POST"})

PBP_COLUMNS = [
    "game_id",
    "season_type",
    "receiver_player_id",
    "pass_attempt",
    "two_point_attempt",
    "complete_pass",
    "cp",
    "yards_after_catch",
    "xyac_mean_yardage",
]


class CatchSums(NamedTuple):
    """Catch-rate-over-expected parts, over targets that carried a probability."""

    targets: int
    receptions: int
    expected: float


class YacSums(NamedTuple):
    """YAC-over-expected parts, over completions that carried an expectation."""

    receptions: int
    actual_yards: int
    expected: float


def _is_target(play: dict) -> bool:
    """A charged pass attempt to a credited receiver.

    Two-point conversions are excluded so that `targets` counted here means the
    same thing as `targets` on weekly_actuals, which does not include them.
    """
    return (
        play.get("season_type") in SEASON_TYPES
        and bool(play.get("receiver_player_id"))
        and play.get("pass_attempt") == 1
        and play.get("two_point_attempt") != 1
    )


def expected_receptions(plays: list[dict]) -> dict[tuple[str, str], CatchSums]:
    """Expected catches per receiver per game, with the plays they came from."""
    sums: dict[tuple[str, str], list] = defaultdict(lambda: [0, 0, 0.0])
    for play in plays:
        if not _is_target(play) or play.get("cp") is None:
            continue
        entry = sums[(play["receiver_player_id"], play["game_id"])]
        entry[0] += 1
        entry[1] += 1 if play.get("complete_pass") == 1 else 0
        entry[2] += play["cp"]
    return {key: CatchSums(*value) for key, value in sums.items()}


def expected_yac(plays: list[dict]) -> dict[tuple[str, str], YacSums]:
    """Expected yards after catch per receiver per game, over completions only.

    A completion missing either the expectation or the actual yards is left out
    of both sums rather than out of one, which is the whole point of returning
    the denominator alongside.
    """
    sums: dict[tuple[str, str], list] = defaultdict(lambda: [0, 0, 0.0])
    for play in plays:
        if (
            not _is_target(play)
            or play.get("complete_pass") != 1
            or play.get("xyac_mean_yardage") is None
            or play.get("yards_after_catch") is None
        ):
            continue
        entry = sums[(play["receiver_player_id"], play["game_id"])]
        entry[0] += 1
        entry[1] += play["yards_after_catch"]
        entry[2] += play["xyac_mean_yardage"]
    return {key: YacSums(*value) for key, value in sums.items()}


# A player with no play-by-play rows at all. Zero denominators rather than
# missing keys, so every rate built on them comes out NULL through the same rule
# that handles a player who simply had no targets. The alternative, treating an
# absent player as having met expectations exactly, would read as a perfect
# score.
NO_CATCHES = CatchSums(0, 0, 0.0)
NO_YAC = YacSums(0, 0, 0.0)


def efficiency_row(actual: dict, catch: CatchSums, yac: YacSums, updated_at: str) -> dict:
    """One player's rates for one game.

    `actual` carries the box-score counts from weekly_actuals plus `routes` from
    player_usage_weekly, which is the only field here that comes from another
    computed table.
    """
    return {
        "player_id": actual["player_id"],
        "game_id": actual["game_id"],
        "season": actual["season"],
        "week": actual["week"],
        "team_abbr": actual["team_abbr"],

        "routes": actual["routes"],
        "receiving_yards": actual["receiving_yards"],
        "yprr": share(actual["receiving_yards"], actual["routes"]),
        "targets": actual["targets"],
        "yards_per_target": share(actual["receiving_yards"], actual["targets"]),
        "receiving_epa": actual["receiving_epa"],
        "epa_per_target": share(actual["receiving_epa"], actual["targets"]),
        "receptions": actual["receptions"],
        "catch_rate": share(actual["receptions"], actual["targets"]),
        "cp_targets": catch.targets,
        "cp_receptions": catch.receptions,
        "expected_receptions": catch.expected,
        "croe": share(catch.receptions - catch.expected, catch.targets),
        "xyac_receptions": yac.receptions,
        "xyac_actual_yards": yac.actual_yards,
        "expected_yac": yac.expected,
        "yacoe": share(yac.actual_yards - yac.expected, yac.receptions),

        "carries": actual["carries"],
        "rushing_yards": actual["rushing_yards"],
        "yards_per_carry": share(actual["rushing_yards"], actual["carries"]),
        "rushing_epa": actual["rushing_epa"],
        "epa_per_carry": share(actual["rushing_epa"], actual["carries"]),

        "attempts": actual["attempts"],
        "completions": actual["completions"],
        "passing_yards": actual["passing_yards"],
        "completion_rate": share(actual["completions"], actual["attempts"]),
        "yards_per_attempt": share(actual["passing_yards"], actual["attempts"]),
        "passing_epa": actual["passing_epa"],
        "epa_per_attempt": share(actual["passing_epa"], actual["attempts"]),

        "updated_at": updated_at,
    }


def aggregate_efficiency(
    actuals: list[dict],
    catch_by_game: dict[tuple[str, str], CatchSums],
    yac_by_game: dict[tuple[str, str], YacSums],
    updated_at: str,
) -> list[dict]:
    """Turn weekly actuals into efficiency rows, one per input row."""
    rows = []
    for actual in actuals:
        key = (actual["player_id"], actual["game_id"])
        rows.append(
            efficiency_row(
                actual,
                catch_by_game.get(key, NO_CATCHES),
                yac_by_game.get(key, NO_YAC),
                updated_at,
            )
        )
    return rows


# Thirty-five columns is past the point where spelling the statement out reads
# as a data contract, and past the point where a column present in the row dict
# but missing from the statement would be dropped in silence. Same call
# form.py made, for the same reason; a test asserts the two stay in step.
COLUMNS = (
    "player_id", "game_id", "season", "week", "team_abbr",
    "routes", "receiving_yards", "yprr",
    "targets", "yards_per_target", "receiving_epa", "epa_per_target",
    "receptions", "catch_rate",
    "cp_targets", "cp_receptions", "expected_receptions", "croe",
    "xyac_receptions", "xyac_actual_yards", "expected_yac", "yacoe",
    "carries", "rushing_yards", "yards_per_carry", "rushing_epa", "epa_per_carry",
    "attempts", "completions", "passing_yards", "completion_rate",
    "yards_per_attempt", "passing_epa", "epa_per_attempt",
    "updated_at",
)

KEY_COLUMNS = frozenset({"player_id", "game_id"})


def _upsert_sql() -> str:
    assignments = ",\n  ".join(
        f"{column} = excluded.{column}" for column in COLUMNS if column not in KEY_COLUMNS
    )
    return (
        f"INSERT INTO player_efficiency_weekly ({', '.join(COLUMNS)})\n"
        f"VALUES ({', '.join(':' + column for column in COLUMNS)})\n"
        "ON CONFLICT(player_id, game_id) DO UPDATE SET\n"
        f"  {assignments}\n"
    )


EFFICIENCY_UPSERT = _upsert_sql()

# routes is the one field from another computed table. A LEFT JOIN so a missing
# usage row costs a NULL yprr rather than dropping the player's whole box score.
ACTUALS_QUERY = """
SELECT w.player_id, w.game_id, w.season, w.week, w.team_abbr,
       u.routes,
       w.receiving_yards, w.targets, w.receiving_epa, w.receptions,
       w.carries, w.rushing_yards, w.rushing_epa,
       w.attempts, w.completions, w.passing_yards, w.passing_epa
FROM weekly_actuals w
LEFT JOIN player_usage_weekly u
  ON u.player_id = w.player_id AND u.game_id = w.game_id
WHERE w.season = ?
"""


def _require_usage(conn: sqlite3.Connection, season: int) -> None:
    """Refuse to run before compute usage has.

    Only meaningful once there are actuals to compute against: a season with
    nothing ingested at all has no ordering mistake to report. With actuals but
    no usage rows, every yprr would be NULL and the run would still report
    success, which is the failure this guard exists to make loud.
    """
    count = conn.execute(
        "SELECT COUNT(*) FROM player_usage_weekly WHERE season = ?", (season,)
    ).fetchone()[0]
    if count == 0:
        raise RuntimeError(
            f"no usage rows for {season}; routes come from that table. "
            f"Run: statify compute usage --season {season}"
        )


def load_efficiency(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int]:
    """Compute and upsert one season's efficiency. Returns (rows, rows_without_routes)."""
    query, params = ACTUALS_QUERY, (season,)
    if week is not None:
        query += " AND w.week = ?"
        params = (season, week)
    actuals = [dict(row) for row in conn.execute(query, params)]
    if not actuals:
        return 0, 0

    _require_usage(conn, season)
    plays = list(nflverse.pbp(season, PBP_COLUMNS).iter_rows(named=True))
    rows = aggregate_efficiency(
        actuals, expected_receptions(plays), expected_yac(plays), utc_now()
    )

    write(conn, EFFICIENCY_UPSERT, rows)
    return len(rows), sum(1 for row in rows if row["routes"] is None)
