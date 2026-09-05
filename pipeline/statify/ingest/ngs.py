"""Load Next Gen Stats into the database.

NGS is a sparse enrichment, not a base table. It covers roughly 39% of
skill-player weeks and is position-siloed: receiving is WR and TE, rushing is RB,
passing is QB. A missing row means unmeasured, never zero.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import normalize_team, utc_now, write
from statify.sources import nflverse


def align_postseason_weeks(
    ngs_weeks: list[int], schedule_weeks: list[int]
) -> dict[int, int]:
    """Map NGS postseason week numbers onto the schedule's.

    NGS leaves a gap where the Pro Bowl sits, so it numbers the Super Bowl one
    higher than the schedule does: 2024 runs 19, 20, 21, 23 against the
    schedule's 19, 20, 21, 22. Storing the raw number would drop every Super Bowl
    from every join with no error, so the translation happens on the way in.

    Rather than assume the offset, only a week the schedule does not recognize is
    remapped, and only when it is the last one. Anything else means the
    assumption broke and the caller should stop instead of guessing.
    """
    known = set(schedule_weeks)
    mapping = {week: week for week in ngs_weeks if week in known}

    unknown = sorted(set(ngs_weeks) - known)
    if not unknown:
        return mapping

    if len(unknown) > 1 or unknown[0] != max(ngs_weeks):
        raise RuntimeError(
            f"cannot align NGS postseason weeks {sorted(ngs_weeks)} to schedule "
            f"weeks {sorted(schedule_weeks)}: expected at most one unrecognized "
            f"week, as the highest. Got {unknown}."
        )

    if not schedule_weeks:
        raise RuntimeError(
            f"NGS reports postseason week {unknown[0]} but the games table has no "
            "postseason weeks for this season. Run: statify ingest games"
        )

    mapping[unknown[0]] = max(schedule_weeks)
    return mapping


# Shared by all three feeds. player_gsis_id is the join key: the NGS frames have
# no column called player_id.
KEY_COLUMNS = ["player_gsis_id", "season", "week", "season_type", "team_abbr"]

RECEIVING_METRICS = {
    "avg_separation": "avg_separation",
    "yacoe": "avg_yac_above_expectation",
    "avg_cushion": "avg_cushion",
}

RECEIVING_UPSERT = """
INSERT INTO next_gen_stats (
  player_id, season, week, team_abbr,
  avg_separation, yacoe, avg_cushion, updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr,
  :avg_separation, :yacoe, :avg_cushion, :updated_at
)
ON CONFLICT(player_id, season, week) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  avg_separation = excluded.avg_separation,
  yacoe = excluded.yacoe,
  avg_cushion = excluded.avg_cushion,
  updated_at = excluded.updated_at
"""


def _postseason_mapping(conn: sqlite3.Connection, season: int, sources: list[dict]) -> dict[int, int]:
    """Build the NGS-to-schedule week map from the whole season.

    Must run before any --week filter: identifying the Super Bowl needs the full
    set of NGS postseason weeks, and one week in isolation looks like a gap.
    """
    schedule_weeks = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT week FROM games WHERE season = ? AND game_type <> 'REG'",
            (season,),
        )
    ]
    ngs_weeks = sorted({s["week"] for s in sources if s["season_type"] == "POST"})
    return align_postseason_weeks(ngs_weeks, schedule_weeks)


def _require_games(conn: sqlite3.Connection, season: int) -> None:
    count = conn.execute("SELECT COUNT(*) FROM games WHERE season = ?", (season,)).fetchone()[0]
    if count == 0:
        raise RuntimeError(
            f"no games for {season}; the postseason week remap reads them. "
            f"Run: statify ingest games --season {season}"
        )


def _load_feed(
    conn: sqlite3.Connection,
    season: int,
    stat_type: str,
    metrics: dict[str, str],
    upsert: str,
    week: int | None = None,
) -> tuple[int, int]:
    """Upsert one NGS feed. Returns (upserted, skipped)."""
    _require_games(conn, season)
    frame = nflverse.next_gen_stats(season, stat_type).select(KEY_COLUMNS + list(metrics.values()))

    # Week 0 is the season-to-date aggregate. Stored, it would look like a normal
    # week and corrupt every rolling average in feature 11.
    sources = [s for s in frame.iter_rows(named=True) if s["week"] > 0]
    mapping = _postseason_mapping(conn, season, sources)
    known_players = {row[0] for row in conn.execute("SELECT player_id FROM players")}
    updated_at = utc_now()

    rows: list[dict] = []
    skipped = 0
    for source in sources:
        schedule_week = (
            mapping[source["week"]] if source["season_type"] == "POST" else source["week"]
        )
        if week is not None and schedule_week != week:
            continue
        if not source["player_gsis_id"] or source["player_gsis_id"] not in known_players:
            skipped += 1
            continue

        row = {
            "player_id": source["player_gsis_id"],
            "season": source["season"],
            "week": schedule_week,
            "team_abbr": normalize_team(source["team_abbr"]),
            "updated_at": updated_at,
        }
        row.update({column: source[src] for column, src in metrics.items()})
        rows.append(row)

    write(conn, upsert, rows)
    return len(rows), skipped


def load_receiving(conn: sqlite3.Connection, season: int, week: int | None = None) -> tuple[int, int]:
    """WR and TE only; the receiving feed carries no running backs."""
    return _load_feed(conn, season, "receiving", RECEIVING_METRICS, RECEIVING_UPSERT, week)


PASSING_METRICS = {
    "cpoe": "completion_percentage_above_expectation",
    "time_to_throw": "avg_time_to_throw",
}

PASSING_UPSERT = """
INSERT INTO next_gen_stats (
  player_id, season, week, team_abbr, cpoe, time_to_throw, updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr, :cpoe, :time_to_throw, :updated_at
)
ON CONFLICT(player_id, season, week) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  cpoe = excluded.cpoe,
  time_to_throw = excluded.time_to_throw,
  updated_at = excluded.updated_at
"""

RUSHING_METRICS = {
    "ryoe": "rush_yards_over_expected",
    "ryoe_per_att": "rush_yards_over_expected_per_att",
}

RUSHING_UPSERT = """
INSERT INTO next_gen_stats (
  player_id, season, week, team_abbr, ryoe, ryoe_per_att, updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr, :ryoe, :ryoe_per_att, :updated_at
)
ON CONFLICT(player_id, season, week) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  ryoe = excluded.ryoe,
  ryoe_per_att = excluded.ryoe_per_att,
  updated_at = excluded.updated_at
"""


def load_passing(conn: sqlite3.Connection, season: int, week: int | None = None) -> tuple[int, int]:
    """QB only."""
    return _load_feed(conn, season, "passing", PASSING_METRICS, PASSING_UPSERT, week)


def load_rushing(conn: sqlite3.Connection, season: int, week: int | None = None) -> tuple[int, int]:
    """RB only; the rushing feed carries no scrambling quarterbacks."""
    return _load_feed(conn, season, "rushing", RUSHING_METRICS, RUSHING_UPSERT, week)
