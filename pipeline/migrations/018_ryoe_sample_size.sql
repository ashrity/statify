-- How many games a trailing rush yards over expected actually came from.
--
-- The games_* columns from migration 013 report prior appearances, and for
-- every other metric that is also the sample size. Rush yards over expected is
-- the exception: Next Gen Stats measures it only for a game of 10 or more
-- carries (migration 017 has the numbers), so a back can have fifteen prior
-- games and one measured one.
--
-- Entering week 17 of 2024 that was not hypothetical. Sean Tucker's
-- ryoe_per_att_std read 3.951, the best in the league, from a single game, while
-- Derrick Henry's 1.772 came from fifteen. Both rows said games_std = 15.
-- Feature 16 would have weighted them equally.
--
-- No EWMA column: a decay-weighted count is not a sample size.
ALTER TABLE player_form_weekly ADD COLUMN ryoe_games_l3 INTEGER NOT NULL DEFAULT 0;
ALTER TABLE player_form_weekly ADD COLUMN ryoe_games_l5 INTEGER NOT NULL DEFAULT 0;
ALTER TABLE player_form_weekly ADD COLUMN ryoe_games_std INTEGER NOT NULL DEFAULT 0;
