-- How much the opponent and the game's pace should move the raw projection
-- feature 19 is about to build, stopping at the multiplier rather than the
-- final number: that combination does not exist until feature 19 builds it,
-- which is also where these multipliers get consumed. Both
-- team_matchup_weekly and game_environment_weekly name feature 18 as their
-- consumer in their own migration comments; this is that consumer.
--
-- A MULTIPLIER, CENTERED AT 1.0. team_matchup_weekly already expresses a
-- defense as a difference from league average (negative is better), so
-- 1 + k * epa_over_league is the simplest function that is neutral (1.0) at
-- an average matchup and moves in the right direction either side of it. The
-- same shape covers the pace side: 1 + m * (pace_ratio - 1) is neutral at
-- league-average pace.
--
-- MEASURED BY GRID SWEEP, NOT CLOSED-FORM REGRESSION. A one-parameter OLS
-- through the origin would fit k and m in one step, but every weight in this
-- pipeline so far (features 15a, 15b, 16 and 17) was picked by sweeping a
-- grid and reading off the argmin or a round number in a flat region.
-- Switching methods here for one feature would make this table harder to
-- audit against its siblings than fitting it the same way is worth.
--
-- ONE ENVIRONMENT MULTIPLIER, NOT A PASS/RUSH SPLIT. Pace moves total plays;
-- splitting the pass/rush mix is pass rate over expected's job, already
-- computed in team_tempo_weekly but not spent here. A retune candidate for
-- feature 30 or 31, not this feature.
--
-- NO WEATHER, NO MARKET IMPLIED TOTAL. Migration 008 warns the stored weather
-- reading is a post-hoc fact, not a forecast, and using it would leak the
-- result of the game being projected. The market columns in
-- game_environment_weekly exist for 2026 week 7 only, 28 of 544 rows, the
-- same insufficient basis feature 15a measured and declined market inputs
-- over for team_volume_weekly. Both need a season of real data before a
-- weight can be measured honestly, not invented now.
--
-- DRIVEN BY player_opportunity_weekly'S ROW SET, the same reuse features 16
-- and 17 make.
--
-- NULL IS NEVER A DEFAULT. A multiplier is NULL when its underlying EPA
-- factor or pace figure is unmeasured (a defense's first time facing a
-- position/play-type, or a week with no trailing pace), not 1.0. Treating a
-- NULL multiplier as neutral is a decision for whoever consumes this table in
-- feature 19, made there, not substituted here.
--
-- TWO OF THREE WERE MEASURED AND REJECTED. Measured on 2024 weeks 6 to 18,
-- mean absolute error per player-week against the actual yardage, baselined
-- on feature 15b's opportunity times feature 16's efficiency:
--
--            k/m 0.0   k/m 0.5   argmin        k/m 3.0
--   pass      15.5468   15.6223   15.5468 @ 0.0   17.5630
--   rush      12.9706   12.9300   12.9300 @ 0.5    14.8734
--   environ.  18.6523   18.6650   18.6523 @ 0.0    18.8334
--
-- Pass matchup and environment both get monotonically worse as the
-- constant rises away from zero, the same honest outcome feature 15a found
-- measuring opponent adjustment on team volume: no adjustment beat any
-- adjustment, so PASS_MATCHUP_K and ENVIRONMENT_M both ship at 0.0. Rush
-- matchup is different: 0.5 is a genuine interior minimum, not a boundary
-- artifact, so RUSH_MATCHUP_K ships as measured.
--
-- The constants live on the row for the same reason every measured weight in
-- this project does: a retune in feature 30 or 31 must not leave stored rows
-- disagreeing with the code that reads them.
--
-- Every multiplier is checkable from its own row:
--   pass_matchup_multiplier = 1 + pass_matchup_k * opponent_pass_epa_over_league
--   rush_matchup_multiplier = 1 + rush_matchup_k * opponent_rush_epa_over_league
--   environment_multiplier  = 1 + environment_m * (pace_ratio - 1)
CREATE TABLE player_matchup_environment_weekly (
  player_id                        TEXT    NOT NULL REFERENCES players(player_id),
  season                            INTEGER NOT NULL,
  week                               INTEGER NOT NULL,
  team_abbr                         TEXT    NOT NULL REFERENCES teams(team_abbr),
  opponent_team_abbr                TEXT    NOT NULL REFERENCES teams(team_abbr),
  position                          TEXT    NOT NULL,
  pass_matchup_multiplier           REAL,
  rush_matchup_multiplier           REAL,
  environment_multiplier            REAL,
  opponent_pass_epa_over_league     REAL,
  opponent_rush_epa_over_league     REAL,
  own_pace                          REAL,
  opponent_pace                     REAL,
  league_pace                       REAL,
  pace_ratio                        REAL,
  pass_matchup_k                    REAL    NOT NULL,
  rush_matchup_k                    REAL    NOT NULL,
  environment_m                     REAL    NOT NULL,
  updated_at                        TEXT    NOT NULL,
  PRIMARY KEY (player_id, season, week)
);

CREATE INDEX idx_player_matchup_environment_season_week ON player_matchup_environment_weekly(season, week);
