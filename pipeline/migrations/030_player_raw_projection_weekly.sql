-- One raw projected value per player per week per stat type, assembled from
-- features already built. No new weight is fitted here: "v1 weights set
-- from domain research rather than learned" (project-overview.md) describes
-- what features 15 through 18 already did, not a fresh decision made here.
--
-- FOUR STAT TYPES ARE A PRODUCT; TOUCHDOWNS IS NOT. receiving_yards,
-- receptions, rushing_yards and passing_yards are each opportunity (feature
-- 15b) times efficiency (feature 16) times the matchup and environment
-- multipliers (feature 18). touchdowns is feature 17's anytime_td_prob,
-- copied through undecorated: feature 7b's anytime-touchdown market prices a
-- probability against a fixed 0.5 line, and no matchup/environment
-- multiplier was ever measured against a probability, only against
-- receiving and rushing yards. Multiplying one onto the other would be
-- exactly the unmeasured extrapolation feature 18 itself declined to make
-- for pass matchup and environment.
--
--   receiving_yards = exp_targets  * exp_yards_per_target  * pass_matchup_multiplier * environment_multiplier
--   receptions      = exp_targets  * exp_catch_rate        * pass_matchup_multiplier * environment_multiplier
--   rushing_yards   = exp_carries  * exp_yards_per_carry   * rush_matchup_multiplier * environment_multiplier
--   passing_yards   = exp_attempts * exp_yards_per_attempt * pass_matchup_multiplier * environment_multiplier
--   touchdowns      = anytime_td_prob
--
-- A NULL MULTIPLIER BECOMES 1.0 HERE, AND ONLY HERE. Feature 18 stored NULL
-- for an unmeasured matchup or pace factor and explicitly left the
-- substitution to its consumer. This is that consumer: matchup_multiplier_used
-- and environment_multiplier_used record what was ACTUALLY multiplied in (1.0
-- when the source was NULL), not the source value, so a row's own arithmetic
-- is checkable without re-deriving the substitution rule from a second table.
--
-- NO POSITION GATING. A receiving_yards row for a player who never gets
-- targeted is correctly near-zero or NULL on its own, the same way
-- compute volume and compute usage never gate by position.
--
-- DRIVEN BY player_opportunity_weekly'S ROW SET crossed with the five stat
-- types, the same reuse features 16, 17 and 18 all make.
--
-- baseline_value is opportunity times efficiency (or exp_touchdowns for the
-- touchdowns row) BEFORE any multiplier, stored so the multiplier's own
-- effect can be read off directly: raw_projection / baseline_value recovers
-- it exactly for the four product stat types.
CREATE TABLE player_raw_projection_weekly (
  player_id                   TEXT    NOT NULL REFERENCES players(player_id),
  season                      INTEGER NOT NULL,
  week                         INTEGER NOT NULL,
  stat_type                    TEXT    NOT NULL CHECK (
    stat_type IN ('receiving_yards', 'receptions', 'rushing_yards', 'passing_yards', 'touchdowns')
  ),
  team_abbr                    TEXT    NOT NULL REFERENCES teams(team_abbr),
  position                     TEXT    NOT NULL,
  raw_projection                REAL,
  baseline_value                REAL,
  matchup_multiplier_used        REAL,
  environment_multiplier_used    REAL,
  updated_at                     TEXT    NOT NULL,
  PRIMARY KEY (player_id, season, week, stat_type)
);

CREATE INDEX idx_player_raw_projection_season_week ON player_raw_projection_weekly(season, week);
