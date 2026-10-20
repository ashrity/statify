-- Aggregates feature 23's backtest_results into a stored error summary per
-- week per stat type, so accuracy is a queryable fact rather than something
-- recomputed by hand. No table for this is locked in project-overview.md,
-- unlike every table since feature 15b; this one is designed fresh, the same
-- way feature 18 designed player_matchup_environment_weekly.
--
-- STORED PER WEEK, NOT JUST PER SEASON. Feature 29's "running accuracy
-- report showing performance trend over time" needs a row per week to trend
-- across; a single season-wide number could not show that.
--
-- model_version IS PART OF THE KEY, NEVER AVERAGED ACROSS. A retune in
-- feature 30 or 31 gets its own rows rather than blending its accuracy into
-- the version it replaced.
--
-- beat_line_n AND beat_line_rate'S DENOMINATOR IS beat_line_n, NEVER n. A
-- push (backtest_results.beat_line IS NULL) is neither a hit nor a miss, and
-- averaging it in as a 0 would understate the rate exactly where the market
-- and the model agreed to the point of a tie.
--
-- RECOMPUTED IN PLACE, NOT APPENDED. This is a pure derived summary, the
-- shape every compute table in this project takes except projections
-- itself, whose append-only history this table does not need: a backtest
-- row's own content already carries projection_id's history.
CREATE TABLE model_error_weekly (
  season         INTEGER NOT NULL,
  week           INTEGER NOT NULL,
  stat_type      TEXT    NOT NULL,
  model_version  TEXT    NOT NULL,
  n              INTEGER NOT NULL,
  mae            REAL    NOT NULL,
  rmse           REAL    NOT NULL,
  beat_line_n    INTEGER NOT NULL,
  beat_line_rate REAL,
  updated_at     TEXT    NOT NULL,
  PRIMARY KEY (season, week, stat_type, model_version)
);
