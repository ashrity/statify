-- Learned, rather than hand-set, weights for the matchup and environment
-- multipliers feature 18 fit one at a time by grid sweep. This is the first
-- feature in this pipeline to fit several weights jointly on the same
-- historical data, and model_version (feature 20's own reason for existing)
-- is what makes comparing its answer against v1's honest.
--
-- STORED FOR INSPECTION, NOT A SERIALIZED MODEL FILE. Every hand-measured
-- weight in this project lives as a readable constant with its measurement
-- recorded beside it; a learned one gets the same treatment rather than
-- disappearing into a pickle nobody can read.
--
-- touchdowns IS NOT HERE. Its Poisson structure (feature 17) is not a
-- linear regression target.
--
-- train_mae/test_mae ARE THE FITTED MODEL'S OWN ERROR; baseline_mae IS v1'S,
-- on the exact same held-out weeks, read from model_error_weekly. The whole
-- point of this table is that comparison being a real number, not a claim.
CREATE TABLE regression_coefficients (
  season            INTEGER NOT NULL,
  stat_type         TEXT    NOT NULL CHECK (
    stat_type IN ('receiving_yards', 'receptions', 'rushing_yards', 'passing_yards')
  ),
  model             TEXT    NOT NULL CHECK (model IN ('ridge', 'lasso')),
  intercept         REAL    NOT NULL,
  baseline_coef     REAL    NOT NULL,
  matchup_coef      REAL    NOT NULL,
  environment_coef  REAL    NOT NULL,
  alpha             REAL    NOT NULL,
  train_weeks       TEXT    NOT NULL,
  test_weeks        TEXT    NOT NULL,
  train_mae         REAL    NOT NULL,
  test_mae          REAL    NOT NULL,
  baseline_mae      REAL,
  updated_at        TEXT    NOT NULL,
  PRIMARY KEY (season, stat_type)
);
