-- How much of a team's expected volume (feature 15a) belongs to one player, for
-- a week he has not played yet. Feature 16 multiplies this by expected
-- efficiency to get a raw stat projection; feature 18 adjusts the result for
-- matchup and environment.
--
-- DRIVEN BY HIS OWN HISTORY CROSSED WITH HIS TEAM'S SCHEDULE, NOT BY RESULTS.
-- The row worth having is the one for the week he has not played, the same
-- reason team_volume_weekly follows games rather than weekly_actuals. A
-- player's row for week N exists only if he has at least one game this season
-- before week N and his most-recent-as-of-week-N team has a game in week N.
-- There is no roster source behind this: depth_charts would normally supply
-- one, but it fails outright on 2026, the season this has to run against, so
-- nothing here is built to depend on it. The consequence is explicit: a
-- rookie's or new signing's debut week gets no row, and an in-season trade is
-- reflected only from his first game under the new team onward, never
-- proactively.
--
-- TARGETS, CARRIES AND ATTEMPTS ARE A BLEND; ROUTES IS NOT. Each of the first
-- three is weight * own_pg + (1 - weight) * (team_exp * share), where own_pg
-- is his trailing per-game average, share is his trailing share of his team's
-- same quantity, and team_exp is team_volume_weekly's expectation for his
-- team that week. The weight is measured per stat on 2024 the same way feature
-- 15a measured pass_own_weight and rush_own_weight, and stored as a column for
-- the same reason: a retune in feature 30 or 31 must not leave stored rows
-- disagreeing with the code that reads them.
--
-- UNLIKE THE TEAM LEVEL, THE TWO SIDES MOSTLY AGREE HERE. Measured on 2024
-- weeks 6 to 18, mean absolute error per player-week over the 4,761 rows
-- where both sides were available:
--
--            weight 0.0   weight 0.3   weight 0.5   weight 1.0
--   targets      1.3358       1.3338       1.3336       1.3385
--   carries      1.0858       1.0837       1.0831       1.0840
--   attempts     0.8285       0.8286       0.8311       0.8425
--
-- Every curve is close to flat: a player's own trailing rate and his trailing
-- share of the team's expectation largely agree, because the team's own
-- expectation is itself built from the same recent weeks his share is. That
-- is the opposite of team_volume_weekly's sharp pass/rush split, where the
-- two sides actively disagreed. Argmins were 0.4, 0.5 and 0.1, each inside a
-- flat band rather than a sharp minimum, so targets_own_weight and
-- carries_own_weight ship at the round 0.5 and attempts_own_weight at the
-- round 0.2, the same "round number inside the flat region" judgement 15a
-- made for rush_own_weight rather than one season's argmin.
--
-- exp_routes has no weight column because there is nothing to blend against.
-- Feature 15a deliberately left team dropbacks unprojected, because the only
-- source of team dropbacks is participation data that stops publishing after
-- 2025, and nothing here invents a substitute. exp_routes is always
-- own_routes_pg, unconditionally.
--
-- NULL, never 0, for an unknown. A missing row means the player has no prior
-- game this season to build from. Once he has one, a stat he genuinely
-- produced none of (a WR with zero pass attempts) is a real 0, not NULL.
-- routes_run is nullable at the source and stays NULL wherever it is unknown,
-- which is every row in 2026 and every QB.
--
-- Every expectation is checkable from its own row:
--   exp_targets  = targets_own_weight  * own_targets_pg  + (1 - targets_own_weight)  * (team_exp_targets  * target_share)
--   exp_carries  = carries_own_weight  * own_carries_pg  + (1 - carries_own_weight)  * (team_exp_carries  * carries_share)
--   exp_attempts = attempts_own_weight * own_attempts_pg + (1 - attempts_own_weight) * (team_exp_attempts * attempts_share)
--   exp_routes   = own_routes_pg
CREATE TABLE player_opportunity_weekly (
  player_id            TEXT    NOT NULL REFERENCES players(player_id),
  season               INTEGER NOT NULL,
  week                 INTEGER NOT NULL,
  team_abbr            TEXT    NOT NULL REFERENCES teams(team_abbr),
  games_played         INTEGER NOT NULL,
  exp_targets          REAL,
  exp_carries          REAL,
  exp_attempts         REAL,
  exp_routes           REAL,
  own_targets_pg       REAL,
  own_carries_pg       REAL,
  own_attempts_pg      REAL,
  own_routes_pg        REAL,
  target_share         REAL,
  carries_share        REAL,
  attempts_share       REAL,
  team_exp_targets     REAL,
  team_exp_carries     REAL,
  team_exp_attempts    REAL,
  targets_own_weight   REAL    NOT NULL,
  carries_own_weight   REAL    NOT NULL,
  attempts_own_weight  REAL    NOT NULL,
  updated_at           TEXT    NOT NULL,
  PRIMARY KEY (player_id, season, week)
);

CREATE INDEX idx_player_opportunity_season_week ON player_opportunity_weekly(season, week);
