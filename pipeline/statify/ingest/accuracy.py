"""Aggregate backtest_results into a stored error summary per week per stat
type: sample size, MAE, RMSE, and the beat-line hit rate.

beat_line_rate's denominator is beat_line_n, never n: a push (beat_line IS
NULL) is neither a hit nor a miss, and averaging it in as a 0 would
understate the rate exactly where the market and the model agreed to the
point of a tie.
"""

from __future__ import annotations

import math
import sqlite3

from statify.ingest.common import utc_now, write

BACKTEST_QUERY = """
SELECT p.season, p.week, p.stat_type, p.model_version, b.error, b.beat_line
FROM backtest_results b
JOIN projections p ON p.id = b.projection_id
WHERE p.season = :season
"""

ACCURACY_UPSERT = """
INSERT INTO model_error_weekly (
  season, week, stat_type, model_version, n, mae, rmse, beat_line_n, beat_line_rate, updated_at
)
VALUES (
  :season, :week, :stat_type, :model_version, :n, :mae, :rmse, :beat_line_n, :beat_line_rate, :updated_at
)
ON CONFLICT(season, week, stat_type, model_version) DO UPDATE SET
  n = excluded.n,
  mae = excluded.mae,
  rmse = excluded.rmse,
  beat_line_n = excluded.beat_line_n,
  beat_line_rate = excluded.beat_line_rate,
  updated_at = excluded.updated_at
"""


def mae(errors: list[float]) -> float:
    return sum(abs(e) for e in errors) / len(errors)


def rmse(errors: list[float]) -> float:
    return math.sqrt(sum(e * e for e in errors) / len(errors))


def beat_line_rate(beat_lines: list[int]) -> float | None:
    """Mean of the non-NULL beat_line values, or None if there were none."""
    return sum(beat_lines) / len(beat_lines) if beat_lines else None


def group_key(row: dict) -> tuple[int, int, str, str]:
    return (row["season"], row["week"], row["stat_type"], row["model_version"])


def accuracy_rows(backtest_rows: list[dict], updated_at: str | None = None) -> list[dict]:
    stamp = updated_at or utc_now()

    groups: dict[tuple[int, int, str, str], dict] = {}
    for row in backtest_rows:
        key = group_key(row)
        bucket = groups.setdefault(key, {"errors": [], "beat_lines": []})
        bucket["errors"].append(row["error"])
        if row["beat_line"] is not None:
            bucket["beat_lines"].append(row["beat_line"])

    rows = []
    for (season, week, stat_type, model_version), bucket in groups.items():
        errors = bucket["errors"]
        beat_lines = bucket["beat_lines"]
        rows.append(
            {
                "season": season,
                "week": week,
                "stat_type": stat_type,
                "model_version": model_version,
                "n": len(errors),
                "mae": mae(errors),
                "rmse": rmse(errors),
                "beat_line_n": len(beat_lines),
                "beat_line_rate": beat_line_rate(beat_lines),
                "updated_at": stamp,
            }
        )
    return rows


def load_model_error(conn: sqlite3.Connection, season: int, week: int | None = None) -> int:
    query = BACKTEST_QUERY
    params: dict = {"season": season}
    if week is not None:
        query += " AND p.week = :week"
        params["week"] = week
    backtest_rows = [dict(row) for row in conn.execute(query, params).fetchall()]

    rows = accuracy_rows(backtest_rows)
    if rows:
        write(conn, ACCURACY_UPSERT, rows)
    return len(rows)
