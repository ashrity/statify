"""Join each projection to what actually happened.

Keyed by projection_id, not (player, season, week, stat_type): feature 20's
projections accumulate a history, so every generation that reached a played
week gets its own backtest row, never deduplicated to the latest one.
"""

from __future__ import annotations

import sqlite3

from statify.ingest.common import write

ACTUAL_COLUMN = {
    "receiving_yards": "receiving_yards",
    "receptions": "receptions",
    "rushing_yards": "rushing_yards",
    "passing_yards": "passing_yards",
}

PROJECTIONS_QUERY = """
SELECT p.id, p.player_id, p.season, p.week, p.stat_type, p.projected_value, p.market_line, p.edge,
       w.receiving_yards, w.receptions, w.rushing_yards, w.passing_yards,
       w.receiving_tds, w.rushing_tds
FROM projections p
JOIN weekly_actuals w ON w.player_id = p.player_id AND w.season = p.season AND w.week = p.week
WHERE p.season = :season
"""

BACKTEST_UPSERT = """
INSERT INTO backtest_results (projection_id, actual_value, error, beat_line)
VALUES (:projection_id, :actual_value, :error, :beat_line)
ON CONFLICT(projection_id) DO UPDATE SET
  actual_value = excluded.actual_value,
  error = excluded.error,
  beat_line = excluded.beat_line
"""


def actual_value(row: dict) -> float:
    """The outcome a projection is scored against.

    touchdowns is 0 or 1 (did he score rushing or receiving that week), the
    same scale projected_value is already on there (a probability). Every
    other stat type is the matching weekly_actuals column directly.
    """
    if row["stat_type"] == "touchdowns":
        return 1.0 if (row["receiving_tds"] + row["rushing_tds"]) > 0 else 0.0
    return float(row[ACTUAL_COLUMN[row["stat_type"]]])


def beat_line(actual: float, projected_value: float, market_line: float | None, edge: float | None) -> int | None:
    """Whether the projection's side of the line was the side that happened.

    None, not 0 or 1, when there is no line to have taken a side of, or when
    either side is an exact push: the projection exactly on the line, or the
    actual exactly on the line. A push is a third state, not a coin flip.
    """
    if market_line is None or edge is None or edge == 0:
        return None
    actual_margin = actual - market_line
    if actual_margin == 0:
        return None
    return 1 if (edge > 0) == (actual_margin > 0) else 0


def backtest_row(row: dict) -> dict:
    actual = actual_value(row)
    projected = row["projected_value"]
    return {
        "projection_id": row["id"],
        "actual_value": actual,
        "error": actual - projected,
        "beat_line": beat_line(actual, projected, row["market_line"], row["edge"]),
    }


def load_backtest_results(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    query = PROJECTIONS_QUERY
    params: dict = {"season": season}
    if week is not None:
        query += " AND p.week = :week"
        params["week"] = week
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]

    results = [backtest_row(row) for row in rows]
    if results:
        write(conn, BACKTEST_UPSERT, results)
    return len(results)
