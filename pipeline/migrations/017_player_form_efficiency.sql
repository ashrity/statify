-- Efficiency over the same windows feature 11 built for usage: the last 3 games,
-- the last 5, the season so far, and the exponentially weighted version of each.
--
-- Why these need windows at all: single-game efficiency is mostly noise. A.J.
-- Brown's 2024 yards per route run swings between 1.59 and 4.64 game to game
-- against a season figure of 2.65, and none of that swing is a change in how
-- good he is. Feature 16 needs what a player's efficiency is, not what it was
-- once.
--
-- Same rules as migration 013, inherited rather than restated in code: values
-- come only from games strictly before the row's week, windows count games
-- played rather than calendar weeks, and rates are a ratio of sums so a
-- 30-route game outweighs a 5-route one.
--
-- READ THIS BEFORE USING ryoe_per_att. Next Gen Stats publishes rush yards over
-- expected only for a back who carried the ball at least 10 times in the game.
-- Measured on 2024 this is a hard threshold, not sparse sampling:
--
--   1 to 4 carries    0 of 462 weeks     0%
--   5 to 9 carries    0 of 357 weeks     0%
--   10 to 14 carries  257 of 257 weeks   100%
--   15 or more        297 of 297 weeks   100%
--
-- So a back's trailing rush yards over expected is built only from his
-- heavy-workload games. A committee back with weeks of 18, 7, 16 and 4 carries
-- gets a window covering two games out of four, and they are his two best-usage
-- games. Nothing downstream can see that, and no free source fixes it.
--
-- The denominator is NGS's own attempt count, recovered as ryoe divided by
-- ryoe_per_att, not our carries. The two disagree on a quarter of rows.
--
-- Every column here is nullable and means "not enough history", never zero. The
-- games_* columns from migration 013 still say how much history there was.

-- receiving yards per route run
ALTER TABLE player_form_weekly ADD COLUMN yprr_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yprr_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yprr_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN yprr_ewma REAL;

-- receiving yards per target
ALTER TABLE player_form_weekly ADD COLUMN yards_per_target_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yards_per_target_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yards_per_target_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN yards_per_target_ewma REAL;

-- receptions per target
ALTER TABLE player_form_weekly ADD COLUMN catch_rate_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN catch_rate_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN catch_rate_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN catch_rate_ewma REAL;

-- catch rate over expected
ALTER TABLE player_form_weekly ADD COLUMN croe_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN croe_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN croe_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN croe_ewma REAL;

-- yards after catch over expected
ALTER TABLE player_form_weekly ADD COLUMN yacoe_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yacoe_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yacoe_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN yacoe_ewma REAL;

-- expected points added per target
ALTER TABLE player_form_weekly ADD COLUMN epa_per_target_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN epa_per_target_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN epa_per_target_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN epa_per_target_ewma REAL;

-- rushing yards per carry
ALTER TABLE player_form_weekly ADD COLUMN yards_per_carry_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yards_per_carry_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yards_per_carry_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN yards_per_carry_ewma REAL;

-- expected points added per carry
ALTER TABLE player_form_weekly ADD COLUMN epa_per_carry_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN epa_per_carry_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN epa_per_carry_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN epa_per_carry_ewma REAL;

-- rush yards over expected per attempt
ALTER TABLE player_form_weekly ADD COLUMN ryoe_per_att_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN ryoe_per_att_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN ryoe_per_att_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN ryoe_per_att_ewma REAL;

-- passing yards per attempt
ALTER TABLE player_form_weekly ADD COLUMN yards_per_attempt_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yards_per_attempt_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN yards_per_attempt_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN yards_per_attempt_ewma REAL;

-- completions per attempt
ALTER TABLE player_form_weekly ADD COLUMN completion_rate_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN completion_rate_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN completion_rate_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN completion_rate_ewma REAL;

-- expected points added per attempt
ALTER TABLE player_form_weekly ADD COLUMN epa_per_attempt_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN epa_per_attempt_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN epa_per_attempt_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN epa_per_attempt_ewma REAL;
