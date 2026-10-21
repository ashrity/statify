"""The last build-plan item: a gradient-boosted tree per stat type, on the
same historical data and the same held-out temporal split feature 31 used,
fed the raw features rather than feature 31's hand-built interaction terms.
A tree model finds interactions on its own, so re-engineering them would
just redo feature 31's work for a model that does not need it.

XGBoost and SHAP calls are kept at the edge of the module, the same
discipline feature 31 used for scikit-learn.
"""

from __future__ import annotations

import sqlite3
from statistics import mean

from statify.ingest.common import utc_now, write
from statify.ingest.regression import STAT_TYPES, TRAINING_SET_QUERY, mae, train_test_split

FEATURE_NAMES = ("baseline_value", "matchup_multiplier_used", "environment_multiplier_used")

# A single, reasonable set of boosting parameters, matched to the sample
# size this project actually has rather than tuned. A shallow tree and a
# modest round count, the same restraint feature 31 applied to its
# regularization strength.
N_ESTIMATORS = 100
MAX_DEPTH = 3
LEARNING_RATE = 0.1

V1_MAE_QUERY = """
SELECT mae FROM model_error_weekly
WHERE season = ? AND stat_type = ? AND model_version = 'v1' AND week IN ({weeks})
"""

RIDGE_MAE_QUERY = """
SELECT test_mae FROM regression_coefficients WHERE season = ? AND stat_type = ?
"""

BOOSTED_UPSERT = """
INSERT INTO gradient_boost_results (
  season, stat_type, n_estimators, max_depth, learning_rate,
  train_mae, test_mae, v1_mae, ridge_mae,
  importance_baseline, importance_matchup, importance_environment,
  shap_baseline, shap_matchup, shap_environment, updated_at
)
VALUES (
  :season, :stat_type, :n_estimators, :max_depth, :learning_rate,
  :train_mae, :test_mae, :v1_mae, :ridge_mae,
  :importance_baseline, :importance_matchup, :importance_environment,
  :shap_baseline, :shap_matchup, :shap_environment, :updated_at
)
ON CONFLICT(season, stat_type) DO UPDATE SET
  n_estimators = excluded.n_estimators,
  max_depth = excluded.max_depth,
  learning_rate = excluded.learning_rate,
  train_mae = excluded.train_mae,
  test_mae = excluded.test_mae,
  v1_mae = excluded.v1_mae,
  ridge_mae = excluded.ridge_mae,
  importance_baseline = excluded.importance_baseline,
  importance_matchup = excluded.importance_matchup,
  importance_environment = excluded.importance_environment,
  shap_baseline = excluded.shap_baseline,
  shap_matchup = excluded.shap_matchup,
  shap_environment = excluded.shap_environment,
  updated_at = excluded.updated_at
"""


def build_raw_features(rows: list[dict]) -> tuple[list[list[float]], list[float]]:
    """The raw features, no hand-built interaction terms: a tree model finds
    interactions on its own."""
    X = [[row[name] for name in FEATURE_NAMES] for row in rows]
    y = [row["actual_value"] for row in rows]
    return X, y


def fit_boosted_model(train_rows: list[dict], test_rows: list[dict]) -> dict:
    """Fits XGBRegressor on the raw features, evaluates on the held-out test
    rows, and returns train/test MAE plus gain-based and SHAP importance
    per feature."""
    import shap
    from xgboost import XGBRegressor

    X_train, y_train = build_raw_features(train_rows)
    X_test, y_test = build_raw_features(test_rows)

    model = XGBRegressor(n_estimators=N_ESTIMATORS, max_depth=MAX_DEPTH, learning_rate=LEARNING_RATE)
    model.fit(X_train, y_train)

    train_mae = mae(model.predict(X_train).tolist(), y_train)
    test_mae = mae(model.predict(X_test).tolist(), y_test)

    importances = model.feature_importances_.tolist()

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)
    # shap_values entries are numpy scalars; sqlite3 silently stores a numpy
    # float as raw bytes (not a REAL) unless cast to a native Python float first.
    shap_importance = [float(mean(abs(row[i]) for row in shap_values)) for i in range(len(FEATURE_NAMES))]

    return {
        "train_mae": train_mae,
        "test_mae": test_mae,
        "importance": dict(zip(FEATURE_NAMES, importances)),
        "shap_importance": dict(zip(FEATURE_NAMES, shap_importance)),
    }


def load_boosted_results(
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

        fit = fit_boosted_model(train_rows, test_rows)

        v1_placeholders = ",".join("?" * len(test_weeks))
        v1_rows = conn.execute(
            V1_MAE_QUERY.format(weeks=v1_placeholders), [season, stat_type, *sorted(test_weeks)]
        ).fetchall()
        v1_mae = mean(row["mae"] for row in v1_rows) if v1_rows else None

        ridge_row = conn.execute(RIDGE_MAE_QUERY, (season, stat_type)).fetchone()
        ridge_mae = ridge_row["test_mae"] if ridge_row else None

        write(
            conn,
            BOOSTED_UPSERT,
            [
                {
                    "season": season,
                    "stat_type": stat_type,
                    "n_estimators": N_ESTIMATORS,
                    "max_depth": MAX_DEPTH,
                    "learning_rate": LEARNING_RATE,
                    "train_mae": fit["train_mae"],
                    "test_mae": fit["test_mae"],
                    "v1_mae": v1_mae,
                    "ridge_mae": ridge_mae,
                    "importance_baseline": fit["importance"]["baseline_value"],
                    "importance_matchup": fit["importance"]["matchup_multiplier_used"],
                    "importance_environment": fit["importance"]["environment_multiplier_used"],
                    "shap_baseline": fit["shap_importance"]["baseline_value"],
                    "shap_matchup": fit["shap_importance"]["matchup_multiplier_used"],
                    "shap_environment": fit["shap_importance"]["environment_multiplier_used"],
                    "updated_at": stamp,
                }
            ],
        )
        rows_written += 1

    return rows_written
