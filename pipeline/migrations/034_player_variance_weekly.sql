-- A player's own week-to-week volatility on one stat type, strictly prior,
-- the half of feature 26 that is stored. The other half,
-- projections.confidence, is an existing locked column this feature updates
-- in place rather than a new table; this table is the one new thing feature
-- 26 needs, the same situation features 18 and 24 were in with no locked
-- schema to match.
--
-- A MINIMUM OF 2 PRIOR GAMES, OR NULL. One game gives a standard deviation
-- of exactly 0, which would read as perfect certainty, the opposite of what
-- a single game actually tells you about volatility. own_stddev is NULL
-- below that floor, not a fabricated 0.
--
-- SAMPLE standard deviation (n - 1), not population. This is an estimate
-- built from a sample of a player's games, not the full population of every
-- game he will ever play.
--
-- NO ROW FOR touchdowns. Its confidence reuses feature 17's own
-- anytime_td_prob directly; fitting a normal model to a 0/1 outcome would be
-- a second, worse-fitting model for a quantity that already has a
-- principled one.
CREATE TABLE player_variance_weekly (
  player_id      TEXT    NOT NULL REFERENCES players(player_id),
  season         INTEGER NOT NULL,
  week           INTEGER NOT NULL,
  stat_type      TEXT    NOT NULL CHECK (
    stat_type IN ('receiving_yards', 'receptions', 'rushing_yards', 'passing_yards')
  ),
  own_stddev     REAL,
  games_measured INTEGER NOT NULL,
  updated_at     TEXT    NOT NULL,
  PRIMARY KEY (player_id, season, week, stat_type)
);

CREATE INDEX idx_player_variance_season_week ON player_variance_weekly(season, week);
