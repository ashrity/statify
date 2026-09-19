-- What each player did with the opportunity he got, per game. Feature 10 stored
-- the opportunity; this is the other half, and feature 16 multiplies the two.
--
-- Stored rather than derived for the same reason as player_usage_weekly: the
-- expected-catch and expected-YAC sums come from play-by-play, which is not in
-- the database, so a view would need a stored sums table anyway. The cost is the
-- same too, and AGENTS.md carries the ordering rule: recompute this after
-- anything writes weekly_actuals, and after compute usage, which owns routes.
--
-- READ THIS BEFORE USING yprr FOR A RUNNING BACK. Migration 015 explains why a
-- route here means "on the field for a dropback". Backs stay in to block far
-- more often than receivers do, so their route counts run about 25% high and
-- their yards per route run reads about 25% low. Measured on 2024: receiver
-- YPRR lands within about 0.1 of the published figure (Nacua 3.21, Collins
-- 2.87), which is why the receiver numbers are trustworthy and the back numbers
-- are a floor rather than an estimate.
--
-- Every rate is nullable, because a zero denominator is a real state and not a
-- rate of zero: a player with no targets has no catch rate. Counts are NOT NULL
-- where their source is. routes is nullable because compute usage may not have
-- run; the three EPA columns are nullable because nflverse leaves them undefined
-- for a player with no opportunity of that kind.
--
-- The two "over expected" metrics keep three columns each rather than one,
-- because their numerator and denominator have to come from the same plays.
-- cp is missing on 1 target in 17,748 and xyac_mean_yardage on 5% of
-- completions, so an expected sum built from 95% of plays divided by an actual
-- count built from 100% would read low with nothing to flag it.
--
-- yacoe here is NOT the Next Gen Stats figure. NGS builds it from player
-- tracking; this is built from the nflverse expected-YAC model in play-by-play.
-- Compared over 1,302 receiver weeks the two differ by a mean of 0.95 yards and
-- agree within a yard only 30% of the time. Both are real; they are not
-- interchangeable. This one is used because NGS covers no running backs at all,
-- and because it stores its own denominator so feature 12b can weight it by
-- volume across weeks. next_gen_stats still holds the tracking version.
CREATE TABLE player_efficiency_weekly (
  player_id           TEXT NOT NULL REFERENCES players(player_id),
  game_id             TEXT NOT NULL REFERENCES games(game_id),
  season              INTEGER NOT NULL,
  week                INTEGER NOT NULL,
  team_abbr           TEXT NOT NULL REFERENCES teams(team_abbr),

  routes              INTEGER,
  receiving_yards     INTEGER NOT NULL,
  yprr                REAL,
  targets             INTEGER NOT NULL,
  yards_per_target    REAL,
  receiving_epa       REAL,
  epa_per_target      REAL,
  receptions          INTEGER NOT NULL,
  catch_rate          REAL,
  cp_targets          INTEGER NOT NULL,
  cp_receptions       INTEGER NOT NULL,
  expected_receptions REAL NOT NULL,
  croe                REAL,
  xyac_receptions     INTEGER NOT NULL,
  xyac_actual_yards   INTEGER NOT NULL,
  expected_yac        REAL NOT NULL,
  yacoe               REAL,

  carries             INTEGER NOT NULL,
  rushing_yards       INTEGER NOT NULL,
  yards_per_carry     REAL,
  rushing_epa         REAL,
  epa_per_carry       REAL,

  attempts            INTEGER NOT NULL,
  completions         INTEGER NOT NULL,
  passing_yards       INTEGER NOT NULL,
  completion_rate     REAL,
  yards_per_attempt   REAL,
  passing_epa         REAL,
  epa_per_attempt     REAL,

  updated_at          TEXT NOT NULL,
  PRIMARY KEY (player_id, game_id)
);

CREATE INDEX idx_player_efficiency_season_week ON player_efficiency_weekly(season, week);
