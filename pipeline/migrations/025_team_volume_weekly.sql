-- How much offence a team is expected to produce in a week, before anything
-- is known about who on the team produces it. Feature 15b multiplies a
-- player's trailing share by these; feature 18 adjusts them for matchup and
-- environment.
--
-- THE TWO HALVES OF THIS TABLE DISAGREE WITH EACH OTHER, ON PURPOSE. Measured
-- on 2024 weeks 6 to 18, mean absolute error per team-week against four ways
-- of guessing:
--
--                    own last 3   own season   league mean   best blend
--   targets             6.186        5.913        5.720      5.667 @ 0.30
--   pass attempts       6.502        6.177        5.949      5.890 @ 0.30
--   carries             6.267        5.862        6.312      5.853 @ 0.90
--
-- A team's PASSING volume is barely a team property: the league mean beats the
-- team's own season, and the winning blend leans 70% on the league. A team's
-- RUSHING volume is a team property: there the league mean is the worst of the
-- four and the blend leans 80 to 90% on the team.
--
-- That is game script, not noise. Teams pass because they are behind, which
-- belongs to the game rather than to the offence, and run because they choose
-- to, which belongs to the offence. Anything reading this table should expect
-- exp_targets to sit close to the league and exp_carries to spread out.
--
-- No opponent adjustment here, measured and rejected. Scaling by the volume a
-- defence has allowed made targets clearly worse (5.667 to 6.021) and carries
-- only marginally better, inside the flat region described below. Feature 18
-- owns matchup multipliers and will have better material than raw volume
-- faced. No market or environment inputs either: game_environment_weekly holds
-- the implied total that ought to predict pass volume, but it exists for 2026
-- only, where six weeks of actuals is no basis for fitting a weight.
--
-- Driven by games, not by weekly_actuals. The row worth having is the one for
-- the week that has not been played, so rows follow the schedule and the
-- expectation is filled from whatever weeks precede it. Driving them off
-- actuals would emit a row for every week except the only one being projected.
-- A team on a bye has no game and gets no row.
--
-- Strictly prior, the same rule as features 11a, 13a, 13b and 14a, and the
-- same reason: a week N expectation built with week N's own result is
-- describing the game it is meant to project.
--
-- WEEK 1 IS ENTIRELY NULL AND THAT IS THE HONEST ANSWER. Nobody has played, so
-- there is no own rate and no league rate either. The cross-season prior that
-- would fill it is feature 30's shrinkage work; inventing one here would be an
-- unmeasured weight. games_played is 0 on those rows.
--
-- The blend weights are COLUMNS, not just constants in the code, for the
-- reason player_form_weekly stores ewma_half_life: when feature 30 or 31
-- retunes them, stored rows must not quietly disagree with the code that reads
-- them. pass_own_weight covers targets and attempts, rush_own_weight covers
-- carries.
--
-- rush_own_weight ships at 0.8 rather than the measured argmin of 0.90
-- deliberately. The rush curve is flat from 0.7 to 1.0 (5.882, 5.864, 5.853,
-- 5.862, a spread of 0.03 against the 0.25 the pass curve moves across the
-- same range), so one season's argmin is noise. The finding is "mostly the
-- team", not "0.90".
--
-- Every expectation is checkable from its own row:
--   exp = weight * own + (1 - weight) * league
CREATE TABLE team_volume_weekly (
  team_abbr           TEXT    NOT NULL REFERENCES teams(team_abbr),
  season              INTEGER NOT NULL,
  week                INTEGER NOT NULL,
  games_played        INTEGER NOT NULL,
  exp_targets         REAL,
  exp_carries         REAL,
  exp_attempts        REAL,
  own_targets_pg      REAL,
  own_carries_pg      REAL,
  own_attempts_pg     REAL,
  league_targets_pg   REAL,
  league_carries_pg   REAL,
  league_attempts_pg  REAL,
  pass_own_weight     REAL    NOT NULL,
  rush_own_weight     REAL    NOT NULL,
  updated_at          TEXT    NOT NULL,
  PRIMARY KEY (team_abbr, season, week)
);

CREATE INDEX idx_team_volume_season_week ON team_volume_weekly(season, week);
