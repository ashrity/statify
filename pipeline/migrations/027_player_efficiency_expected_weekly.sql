-- How well a player is expected to convert an opportunity into yards,
-- catches or completions, for a week he has not played yet. Feature 19
-- multiplies this by feature 15b's expected opportunity to get a raw stat
-- projection.
--
-- SHRINKS A RATE, NOT A COUNT. Features 15a and 15b both blend one count
-- against another (a team's own targets against the league's, a player's own
-- targets against his team-share estimate). A rate behaves differently: a WR
-- with two targets in his only game has a trailing catch rate of 0% or 100%,
-- not a number worth trusting on its own. So each rate here blends the
-- player's own trailing rate against the league rate AT HIS POSITION over the
-- same prior weeks, the same shrinkage idea sabermetrics calls regression to
-- the mean, applied position by position because a RB's catch rate and a WR's
-- catch rate are not draws from the same distribution.
--
-- DRIVEN BY player_opportunity_weekly'S ROW SET, NOT RE-DERIVED. Feature 15b
-- already decided which (player, week) pairs are worth projecting: a player
-- needs at least one prior game this season, and his most-recent team needs a
-- game that week. Re-deriving that here would be a second implementation of
-- the same rule with its own chance to disagree, so this table's rows are
-- exactly feature 15b's rows; a season with no opportunity rows gets a clear
-- refusal naming `compute opportunity`, not a silent empty run.
--
-- EACH RATE HAS ITS OWN SAMPLE SIZE, AND IT IS NOT games_played. A player can
-- have ten prior games and a yards-per-carry built from one of them, if the
-- other nine were pass plays only. receiving_opportunities, rushing_opportunities
-- and passing_opportunities count prior games where the relevant count was
-- actually nonzero, not games played, the same caveat
-- player_form_weekly.ryoe_games_l3 carries for rush yards over expected:
-- read the sample count before trusting the rate.
--
-- NULL, never 0, for an unknown. A rate with no prior opportunity at all (a
-- WR who has never carried the ball) is unknown, not a real zero.
--
-- UNLIKE team_volume_weekly AND player_opportunity_weekly, EVERY RATE HERE HAS
-- A REAL MINIMUM, not a flat curve. Measured on 2024 weeks 6 to 18, mean
-- absolute error per player-week against the actual realized rate that week:
--
--                      weight 0.0   weight 0.3   argmin        weight 1.0
--   yards_per_target      4.2317       4.2063     4.2036 @ 0.2    4.5190
--   catch_rate             0.2484       0.2463     0.2461 @ 0.4    0.2514
--   yards_per_carry        2.4821       2.4310     2.4310 @ 0.3    2.6567
--   yards_per_attempt      1.8591       1.8307     1.8307 @ 0.3    2.0670
--
-- Leaning entirely on a player's own trailing rate is the worst choice at
-- every stat (the weight 1.0 column is the largest number in every row), and
-- blending beats the position baseline alone too, by a smaller but real
-- margin. All four argmins are already round numbers in 0.2 to 0.4, so they
-- ship as measured rather than needing the "round number in a flat region"
-- compromise features 15a and 15b both made.
--
-- `compute expected-efficiency` reuses `player_opportunity_weekly`'s row set
-- (feature 15b), so a season needs that table filled first; the loader
-- refuses with a named next command otherwise.
--
-- The weight lives on the row for the same reason pass_own_weight and
-- rush_own_weight do: a retune in feature 30 or 31 must not leave stored rows
-- disagreeing with the code that reads them.
--
-- Every expectation is checkable from its own row:
--   exp_X = X_own_weight * own_X + (1 - X_own_weight) * position_X
CREATE TABLE player_efficiency_expected_weekly (
  player_id                    TEXT    NOT NULL REFERENCES players(player_id),
  season                       INTEGER NOT NULL,
  week                         INTEGER NOT NULL,
  team_abbr                    TEXT    NOT NULL REFERENCES teams(team_abbr),
  position                     TEXT    NOT NULL,
  exp_yards_per_target         REAL,
  exp_catch_rate               REAL,
  exp_yards_per_carry          REAL,
  exp_yards_per_attempt        REAL,
  own_yards_per_target         REAL,
  own_catch_rate               REAL,
  own_yards_per_carry          REAL,
  own_yards_per_attempt        REAL,
  position_yards_per_target    REAL,
  position_catch_rate          REAL,
  position_yards_per_carry     REAL,
  position_yards_per_attempt   REAL,
  receiving_opportunities      INTEGER NOT NULL,
  rushing_opportunities        INTEGER NOT NULL,
  passing_opportunities        INTEGER NOT NULL,
  yards_per_target_own_weight  REAL    NOT NULL,
  catch_rate_own_weight        REAL    NOT NULL,
  yards_per_carry_own_weight   REAL    NOT NULL,
  yards_per_attempt_own_weight REAL    NOT NULL,
  updated_at                   TEXT    NOT NULL,
  PRIMARY KEY (player_id, season, week)
);

CREATE INDEX idx_player_efficiency_expected_season_week ON player_efficiency_expected_weekly(season, week);
