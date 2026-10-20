-- Expected touchdowns for a week a player has not played yet: a rushing rate
-- per carry and a receiving rate per target, each blended toward the league
-- rate at his position, multiplied by feature 15b's expected carries and
-- targets, and combined into one Poisson rate plus the probability of
-- scoring at least one. Feature 7b's anytime-touchdown market prices exactly
-- that probability.
--
-- A SEPARATE MODEL FROM FEATURE 16, ON PURPOSE. A player scores 0, 1 or
-- rarely 2 touchdowns in a game, a shape a Poisson distribution fits far
-- better than the continuous yardage rates feature 16 blends. Bolting a
-- fifth rate onto that table would borrow its shrinkage logic for a
-- quantity that does not behave the same way.
--
-- THE SAME SHRINKAGE AS FEATURE 16, APPLIED TO TOUCHDOWN RATES. Each rate
-- blends the player's own trailing TDs-per-carry or TDs-per-target against
-- the league rate among every player at the same position over the same
-- strictly-prior weeks. A touchdown rate is an even smaller-sample quantity
-- than a yardage rate, so the same regression-to-the-mean logic applies at
-- least as strongly.
--
-- NO RED-ZONE VOLUME PROJECTION HERE, DELIBERATELY. red_zone_touches is a
-- stronger scoring signal than total volume, but no feature projects expected
-- red-zone touches: feature 15b stops at targets, carries, attempts and
-- routes. Building that whole second volume pipeline for one feature would be
-- exactly the unmeasured scope creep features 15a and 15b both declined, so
-- this model multiplies a TD rate by the volume that already exists.
--
-- POISSON, NOT NEGATIVE BINOMIAL. Poisson is the simpler of the two named in
-- the build plan and needs no new dependency beyond the standard library's
-- math.exp. It probably understates variance for a high-volume scorer; that
-- is a retune candidate for feature 30 or 31, not a blocker here.
--
-- DRIVEN BY player_opportunity_weekly'S ROW SET, the same reuse feature 16
-- makes: a season with no opportunity rows gets a clear refusal naming
-- `compute opportunity`, not a silent empty run.
--
-- NULL, never 0, for an unknown: a rate with no prior opportunity (a WR who
-- has never carried the ball) is unknown, not a real zero.
--
-- THE OPPOSITE SIGNAL FROM FEATURE 16. Measured on 2024 weeks 6 to 18, mean
-- absolute error per player-week against the actual realized rate that week:
--
--                     weight 0.0   weight 0.8   argmin        weight 1.0
--   rushing_td_rate     0.05168     0.04965     0.04929 @ 1.0    0.04929
--   receiving_td_rate   0.07597     0.07510     0.07509 @ 0.9    0.07510
--
-- Both curves improve monotonically with the own-weight, the opposite of
-- feature 16 where shrinking toward the position clearly helped. A boundary
-- argmin from one season's grid is the textbook overfitting signal, so
-- neither ships at the literal edge; 0.8 sits inside both flat high-weight
-- plateaus, the same judgement `RUSH_OWN_WEIGHT` makes in
-- `team_volume_weekly`. Shrinking a touchdown rate toward the position
-- barely helps and for rushing actively hurts, likely because a touchdown
-- role (goal-line back, slot-fade target) varies more within a position
-- than yardage efficiency does.
--
-- `exp_touchdowns` reproduced an end-to-end MAE of 0.270 against actual
-- combined touchdowns that week, over the same 4,761 rows.
--
-- The weight lives on the row for the same reason every blended weight in
-- this project does: a retune in feature 30 or 31 must not leave stored rows
-- disagreeing with the code that reads them.
--
-- Every expectation is checkable from its own row:
--   exp_rushing_td_rate   = rushing_td_rate_own_weight   * own_rushing_td_rate   + (1 - rushing_td_rate_own_weight)   * position_rushing_td_rate
--   exp_receiving_td_rate = receiving_td_rate_own_weight * own_receiving_td_rate + (1 - receiving_td_rate_own_weight) * position_receiving_td_rate
--   exp_rushing_tds    = exp_carries * exp_rushing_td_rate      (exp_carries from player_opportunity_weekly)
--   exp_receiving_tds  = exp_targets * exp_receiving_td_rate    (exp_targets from player_opportunity_weekly)
--   exp_touchdowns     = exp_rushing_tds + exp_receiving_tds
--   anytime_td_prob    = 1 - exp(-exp_touchdowns)
CREATE TABLE player_touchdown_expected_weekly (
  player_id                     TEXT    NOT NULL REFERENCES players(player_id),
  season                        INTEGER NOT NULL,
  week                          INTEGER NOT NULL,
  team_abbr                     TEXT    NOT NULL REFERENCES teams(team_abbr),
  position                      TEXT    NOT NULL,
  exp_rushing_tds               REAL,
  exp_receiving_tds             REAL,
  exp_touchdowns                REAL,
  anytime_td_prob               REAL,
  exp_rushing_td_rate           REAL,
  exp_receiving_td_rate         REAL,
  own_rushing_td_rate           REAL,
  own_receiving_td_rate         REAL,
  position_rushing_td_rate      REAL,
  position_receiving_td_rate    REAL,
  rushing_opportunities         INTEGER NOT NULL,
  receiving_opportunities       INTEGER NOT NULL,
  rushing_td_rate_own_weight    REAL    NOT NULL,
  receiving_td_rate_own_weight  REAL    NOT NULL,
  updated_at                    TEXT    NOT NULL,
  PRIMARY KEY (player_id, season, week)
);

CREATE INDEX idx_player_touchdown_expected_season_week ON player_touchdown_expected_weekly(season, week);
