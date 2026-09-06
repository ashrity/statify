-- Exponentially weighted versions of every trailing-form metric.
--
-- The windows in feature 11a are blunt: last 3 treats a game three appearances
-- ago exactly like last week's and ignores the fourth entirely. These replace
-- that cliff with a decay, weighting a game by 0.5 ** (age / half_life) where
-- age counts appearances back from the current week.
--
-- Each rate weights its numerator and denominator, never the ratio. Weighting
-- the already-computed share instead is the obvious implementation and it
-- discards volume, exactly as a mean of ratios would: measured across 506
-- players it moves target share by 0.0027 on average and by 0.0202 for Mike
-- Evans, which is about 7% of his value and feeds a volume projection.
--
-- ewma_half_life is stored per row rather than left in the code so a parameter
-- change is visible in the data. It is a judgement, not a fitted value; feature
-- 31 is where weights get learned.
--
-- Nullable because SQLite cannot add a NOT NULL column without a default to a
-- populated table. Every row carries a value after the next compute form.
--
-- No games_ewma column: EWMA uses every prior game, so its count is exactly
-- games_std, and a second copy could only drift.
ALTER TABLE player_form_weekly ADD COLUMN ewma_half_life       REAL;
ALTER TABLE player_form_weekly ADD COLUMN targets_pg_ewma      REAL;
ALTER TABLE player_form_weekly ADD COLUMN carries_pg_ewma      REAL;
ALTER TABLE player_form_weekly ADD COLUMN target_share_ewma    REAL;
ALTER TABLE player_form_weekly ADD COLUMN air_yards_share_ewma REAL;
ALTER TABLE player_form_weekly ADD COLUMN wopr_ewma            REAL;
ALTER TABLE player_form_weekly ADD COLUMN adot_ewma            REAL;
ALTER TABLE player_form_weekly ADD COLUMN rz_touch_share_ewma  REAL;
ALTER TABLE player_form_weekly ADD COLUMN snap_share_ewma      REAL;
