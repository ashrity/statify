"""Load weekly injury reports and practice participation."""

from __future__ import annotations

import sqlite3

from statify.ingest.common import normalize_team, utc_now, write
from statify.sources import nflverse

# The feed writes practice participation as a sentence. Storing that verbatim
# would leave every downstream comparison one upstream copy edit from breaking.
PRACTICE_STATUSES = {
    "Did Not Participate In Practice": "DNP",
    "Limited Participation in Practice": "Limited",
    "Full Participation in Practice": "Full",
}

DESIGNATIONS = {"Out", "Doubtful", "Questionable"}

# 'Note' appears in both status columns as a report annotation rather than a
# status, and a handful of rows carry only whitespace.
NON_STATUSES = {"Note"}

SOURCE_COLUMNS = [
    "season",
    "week",
    "team",
    "gsis_id",
    "report_status",
    "practice_status",
]

# The current-season feed drops date_modified: 2024 carries it, 2026 does not,
# while every other column matches. report_at is part of this table's key, so
# without it there is no upstream timestamp to key a revision on. Rather than
# fail the season outright, those rows are stamped with the ingest time and
# novelty is decided by content, the rule ingest market and ingest forecast
# already follow: a designation that has not changed since the latest stored
# report is not stored again. Without that, every run would add a row per
# player per week, because utc_now() differs on every run.
TIMESTAMP_COLUMN = "date_modified"

INJURY_UPSERT = """
INSERT INTO injuries (
  player_id, season, week, team_abbr, designation, practice_status,
  report_at, updated_at
)
VALUES (
  :player_id, :season, :week, :team_abbr, :designation, :practice_status,
  :report_at, :updated_at
)
ON CONFLICT(player_id, season, week, report_at) DO UPDATE SET
  team_abbr = excluded.team_abbr,
  designation = excluded.designation,
  practice_status = excluded.practice_status,
  updated_at = excluded.updated_at
"""


def _blank(value: str | None) -> bool:
    return value is None or not value.strip() or value.strip() in NON_STATUSES


def normalize_practice_status(value: str | None) -> str | None:
    """Map the feed's sentence to the short form, or raise on an unknown one.

    Raising matters more than the mapping. A new upstream wording that silently
    became NULL would read as "no practice report" for a player who did not
    practise at all.
    """
    if _blank(value):
        return None
    status = PRACTICE_STATUSES.get(value.strip())
    if status is None:
        raise RuntimeError(f"unrecognized practice status: {value!r}")
    return status


def normalize_designation(value: str | None) -> str | None:
    """Keep a real game designation, drop annotations, raise on an unknown one."""
    if _blank(value):
        return None
    designation = value.strip()
    if designation not in DESIGNATIONS:
        raise RuntimeError(f"unrecognized injury designation: {designation!r}")
    return designation


LATEST_REPORTS_QUERY = """
SELECT player_id, week, designation, practice_status
FROM injuries
WHERE season = :season
ORDER BY report_at
"""


def injury_row(source: dict, updated_at: str, report_at: str) -> dict:
    return {
        "player_id": source["gsis_id"],
        "season": source["season"],
        "week": source["week"],
        "team_abbr": normalize_team(source["team"]),
        "designation": normalize_designation(source["report_status"]),
        "practice_status": normalize_practice_status(source["practice_status"]),
        "report_at": report_at,
        "updated_at": updated_at,
    }


def latest_reports(conn: sqlite3.Connection, season: int) -> dict[tuple[str, int], tuple]:
    """The most recent stored (designation, practice_status) per player and week."""
    latest: dict[tuple[str, int], tuple] = {}
    for row in conn.execute(LATEST_REPORTS_QUERY, {"season": season}):
        latest[(row[0], row[1])] = (row[2], row[3])
    return latest


def is_unchanged(row: dict, latest: dict[tuple[str, int], tuple]) -> bool:
    key = (row["player_id"], row["week"])
    if key not in latest:
        return False
    return latest[key] == (row["designation"], row["practice_status"])


def load_injuries(
    conn: sqlite3.Connection, season: int, week: int | None = None
) -> tuple[int, int, int]:
    """Upsert one season's injury reports.

    Returns (upserted, skipped, unchanged). unchanged is always 0 when the feed
    carries its own timestamp, since novelty is then the key's own business.
    """
    frame = nflverse.injuries(season)
    has_timestamp = TIMESTAMP_COLUMN in frame.columns
    columns = SOURCE_COLUMNS + ([TIMESTAMP_COLUMN] if has_timestamp else [])
    frame = frame.select(columns)

    known_players = {row[0] for row in conn.execute("SELECT player_id FROM players")}
    updated_at = utc_now()
    latest = {} if has_timestamp else latest_reports(conn, season)

    rows: list[dict] = []
    skipped = 0
    unchanged = 0
    for source in frame.iter_rows(named=True):
        if week is not None and source["week"] != week:
            continue
        if source["gsis_id"] not in known_players:
            skipped += 1
            continue

        if has_timestamp:
            stamp = source[TIMESTAMP_COLUMN]
            if stamp is None:
                skipped += 1
                continue
            report_at = stamp.isoformat(timespec="seconds")
        else:
            report_at = updated_at

        row = injury_row(source, updated_at, report_at)
        if not has_timestamp and is_unchanged(row, latest):
            unchanged += 1
            continue
        rows.append(row)

    write(conn, INJURY_UPSERT, rows)
    return len(rows), skipped, unchanged
