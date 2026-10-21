-- The last build-plan item. A gradient-boosted tree per stat type, on the
-- same historical data and the same held-out temporal split feature 31
-- used, this time fed the raw features rather than hand-built interaction
-- terms: a tree model finds interactions on its own, and re-engineering
-- them would just redo feature 31's work for a model that does not need it.
--
-- v1_mae AND ridge_mae ARE READ FROM model_error_weekly AND
-- regression_coefficients ON THE SAME HELD-OUT WEEKS, not re-measured here.
-- The point of this table is a real three-way comparison, not three
-- separate claims that happen to sit near each other.
--
-- importance_* AND shap_* ARE STORED, NOT PLOTTED. Every weight in this
-- project lives as a readable, queryable number; feature importance and
-- SHAP output get the same treatment the build-plan line asks for, rather
-- than a chart nobody can query later.
CREATE TABLE gradient_boost_results (
  season                  INTEGER NOT NULL,
  stat_type                TEXT    NOT NULL CHECK (
    stat_type IN ('receiving_yards', 'receptions', 'rushing_yards', 'passing_yards')
  ),
  n_estimators              INTEGER NOT NULL,
  max_depth                 INTEGER NOT NULL,
  learning_rate             REAL    NOT NULL,
  train_mae                 REAL    NOT NULL,
  test_mae                  REAL    NOT NULL,
  v1_mae                    REAL,
  ridge_mae                 REAL,
  importance_baseline       REAL    NOT NULL,
  importance_matchup        REAL    NOT NULL,
  importance_environment    REAL    NOT NULL,
  shap_baseline              REAL    NOT NULL,
  shap_matchup               REAL    NOT NULL,
  shap_environment           REAL    NOT NULL,
  updated_at                 TEXT    NOT NULL,
  PRIMARY KEY (season, stat_type)
);
