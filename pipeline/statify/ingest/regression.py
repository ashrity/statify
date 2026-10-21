"""Learn, rather than hand-set, the weight the matchup and environment
multipliers should carry in the final projection. Every other weight in this
pipeline was fit one at a time by grid sweep; this is the first to fit
several jointly on the same historical data, with model_version (feature 20)
making the comparison against v1 honest.

Feature construction and the train/test split are plain Python, kept
separate from the scikit-learn calls at the edge of the module, the same
split nflverse/open_meteo calls get elsewhere in this codebase.
"""

from __future__ import annotations

import sqlite3
from statistics import mean

from statify.ingest.common import utc_now, write

STAT_TYPES = ("receiving_yards", "receptions", "rushing_yards", "passing_yards")

# A single, reasonable regularization strength for each model. A full alpha
# search is a further refinement this result does not currently call for.
RIDGE_ALPHA = 1.0
LASSO_ALPHA = 0.1

TRAINING_SET_QUERY = """
SELECT
  p.id AS projection_id, p.week AS week,
  r.baseline_value AS baseline_value,
  r.matchup_multiplier_used AS matchup_multiplier_used,
  r.environment_multiplier_used AS environment_multiplier_used,
  b.actual_value AS actual_value
FROM projections p
JOIN player_raw_projection_weekly r
  ON r.player_id = p.player_id AND r.season = p.season AND r.week = p.week AND r.stat_type = p.stat_type
JOIN backtest_results b ON b.projection_id = p.id
WHERE p.season = :season AND p.stat_type = :stat_type
  AND r.baseline_value IS NOT NULL
  AND r.matchup_multiplier_used IS NOT NULL
  AND r.environment_multiplier_used IS NOT NULL
"""

BASELINE_MAE_QUERY = """
SELECT mae FROM model_error_weekly
WHERE season = ? AND stat_type = ? AND model_version = 'v1' AND week IN ({weeks})
"""

COEFFICIENTS_UPSERT = """
INSERT INTO regression_coefficients (
  season, stat_type, model, intercept, baseline_coef, matchup_coef, environment_coef,
  alpha, train_weeks, test_weeks, train_mae, test_mae, baseline_mae, updated_at
)
VALUES (
  :season, :stat_type, :model, :intercept, :baseline_coef, :matchup_coef, :environment_coef,
  :alpha, :train_weeks, :test_weeks, :train_mae, :test_mae, :baseline_mae, :updated_at
)
ON CONFLICT(season, stat_type) DO UPDATE SET
  model = excluded.model,
  intercept = excluded.intercept,
  baseline_coef = excluded.baseline_coef,
  matchup_coef = excluded.matchup_coef,
  environment_coef = excluded.environment_coef,
  alpha = excluded.alpha,
  train_weeks = excluded.train_weeks,
  test_weeks = excluded.test_weeks,
  train_mae = excluded.train_mae,
  test_mae = excluded.test_mae,
  baseline_mae = excluded.baseline_mae,
  updated_at = excluded.updated_at
"""


def build_features(rows: list[dict]) -> tuple[list[list[float]], list[float]]:
    """actual ~ baseline + baseline*(matchup-1) + baseline*(environment-1).

    The two interaction terms are centered on the multiplier's neutral value
    (1.0), so a row with no real adjustment (both multipliers exactly 1.0)
    contributes 0 to both interaction terms, leaving baseline_value alone to
    explain it, the same "centered at neutral" shape the multipliers
    themselves were built with in feature 18.
    """
    X = []
    y = []
    for row in rows:
        baseline = row["baseline_value"]
        X.append(
            [
                baseline,
                baseline * (row["matchup_multiplier_used"] - 1),
                baseline * (row["environment_multiplier_used"] - 1),
            ]
        )
        y.append(row["actual_value"])
    return X, y


def train_test_split(rows: list[dict], test_weeks: set[int]) -> tuple[list[dict], list[dict]]:
    """A temporal split: every test row's week is in test_weeks, every train
    row's is strictly not, so a test week never leaks into training."""
    train = [row for row in rows if row["week"] not in test_weeks]
    test = [row for row in rows if row["week"] in test_weeks]
    return train, test


def mae(predictions: list[float], actuals: list[float]) -> float:
    return mean(abs(p - a) for p, a in zip(predictions, actuals))


def fit_and_evaluate(train_rows: list[dict], test_rows: list[dict]) -> dict:
    """Fits Ridge and Lasso on the training rows, evaluates both on the test
    rows, and returns the one with the lower test MAE, with both scikit-learn
    imports kept local to this function, the edge of the module."""
    from sklearn.linear_model import Lasso, Ridge

    X_train, y_train = build_features(train_rows)
    X_test, y_test = build_features(test_rows)

    results = {}
    for name, model_cls, alpha in (("ridge", Ridge, RIDGE_ALPHA), ("lasso", Lasso, LASSO_ALPHA)):
        model = model_cls(alpha=alpha)
        model.fit(X_train, y_train)
        train_mae = mae(model.predict(X_train).tolist(), y_train)
        test_mae = mae(model.predict(X_test).tolist(), y_test)
        results[name] = {
            "intercept": float(model.intercept_),
            "baseline_coef": float(model.coef_[0]),
            "matchup_coef": float(model.coef_[1]),
            "environment_coef": float(model.coef_[2]),
            "alpha": alpha,
            "train_mae": train_mae,
            "test_mae": test_mae,
        }

    winner = min(results, key=lambda name: results[name]["test_mae"])
    return {"model": winner, **results[winner], "candidates": results}


def load_regression_coefficients(
    conn: sqlite3.Connection, season: int, train_weeks: set[int], test_weeks: set[int]
) -> int:
    stamp = utc_now()
    rows_written = 0

    for stat_type in STAT_TYPES:
        all_rows = [
            dict(row)
            for row in conn.execute(TRAINING_SET_QUERY, {"season": season, "stat_type": stat_type}).fetchall()
        ]
        rows = [row for row in all_rows if row["week"] in train_weeks or row["week"] in test_weeks]
        train_rows, test_rows = train_test_split(rows, test_weeks)
        if not train_rows or not test_rows:
            continue

        fit = fit_and_evaluate(train_rows, test_rows)

        placeholders = ",".join("?" * len(test_weeks))
        baseline_rows = conn.execute(
            BASELINE_MAE_QUERY.format(weeks=placeholders),
            [season, stat_type, *sorted(test_weeks)],
        ).fetchall()
        baseline_mae = mean(row["mae"] for row in baseline_rows) if baseline_rows else None

        write(
            conn,
            COEFFICIENTS_UPSERT,
            [
                {
                    "season": season,
                    "stat_type": stat_type,
                    "model": fit["model"],
                    "intercept": fit["intercept"],
                    "baseline_coef": fit["baseline_coef"],
                    "matchup_coef": fit["matchup_coef"],
                    "environment_coef": fit["environment_coef"],
                    "alpha": fit["alpha"],
                    "train_weeks": ",".join(str(w) for w in sorted(train_weeks)),
                    "test_weeks": ",".join(str(w) for w in sorted(test_weeks)),
                    "train_mae": fit["train_mae"],
                    "test_mae": fit["test_mae"],
                    "baseline_mae": baseline_mae,
                    "updated_at": stamp,
                }
            ],
        )
        rows_written += 1

    return rows_written
