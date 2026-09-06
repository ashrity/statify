-- Routes run, and the rates built on them.
--
-- weekly_actuals.routes_run has existed since feature 2 and been NULL ever
-- since. It is finally filled here, from participation data.
--
-- READ THIS BEFORE USING routes FOR EFFICIENCY. Nobody publishes per-player
-- route counts for free, so a route means "this player was on the field for a
-- dropback". A player who stayed in to block is counted as having run one, and
-- the error is not evenly spread. Measured against 2024 using targets per
-- route, whose true value is well established:
--
--   WR  0.196 against a real ~0.20  -- essentially correct
--   TE  0.173 against a real ~0.18  -- slight over-count
--   RB  0.150 against a real ~0.20  -- routes over-counted by roughly 25%
--
-- Backs release into a pattern far less often than receivers do. So yards per
-- route run for a running back, in feature 12, will read about 25% low, and
-- nothing downstream will flag it. Treat the receiver numbers as sound and the
-- back numbers as a floor.
--
-- Quarterbacks are excluded entirely: on the field for every dropback, they
-- would otherwise lead the league.

ALTER TABLE player_usage_weekly ADD COLUMN routes INTEGER;
ALTER TABLE player_usage_weekly ADD COLUMN team_dropbacks INTEGER;
ALTER TABLE player_usage_weekly ADD COLUMN route_participation REAL;
ALTER TABLE player_usage_weekly ADD COLUMN targets_per_route REAL;

ALTER TABLE player_form_weekly ADD COLUMN routes_pg_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN route_participation_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN targets_per_route_l3 REAL;
ALTER TABLE player_form_weekly ADD COLUMN routes_pg_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN route_participation_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN targets_per_route_l5 REAL;
ALTER TABLE player_form_weekly ADD COLUMN routes_pg_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN route_participation_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN targets_per_route_std REAL;
ALTER TABLE player_form_weekly ADD COLUMN routes_pg_ewma REAL;
ALTER TABLE player_form_weekly ADD COLUMN route_participation_ewma REAL;
ALTER TABLE player_form_weekly ADD COLUMN targets_per_route_ewma REAL;
