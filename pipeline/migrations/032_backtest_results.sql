-- Joins each projection to what actually happened. Feature 21's edge is just
-- an opinion until something checks it against an outcome; this is that
-- check.
--
-- KEYED BY projection_id, NOT (player, season, week, stat_type). Feature 20
-- made projections accumulate a history rather than hold one current row per
-- key: a player/week/stat can have more than one generation, one from
-- Tuesday and one from Thursday. Both are separately worth scoring, since how
-- a guess ages between generations is feature 29's question, so this table
-- scores every generation that reached a played week, never deduplicated to
-- "the latest one."
--
-- actual_value FOR touchdowns IS 0 OR 1, NOT A COUNT. projected_value there
-- is already a probability (feature 17's anytime_td_prob, carried through
-- feature 19 undecorated), so the actual it is compared against is whether a
-- rushing or receiving touchdown happened that week, the same 0/1 scale. For
-- the four yardage/count stat types it is the matching weekly_actuals column
-- directly.
--
-- beat_line IS NULLABLE ON PURPOSE, A THIRD STATE NOT FORCED INTO 0 OR 1. It
-- is NULL whenever there is no market_line to have taken a side of (every row
-- this feature produces on 2024, which has no prop_lines at all) or when
-- either side is an exact push: the projection exactly on the line, or the
-- actual exactly on the line. Forcing a push to 0 or 1 would misrepresent a
-- coin flip as a definite miss or hit.
--
-- UPSERT, UNLIKE projections. Feature 20's append-only table never overwrites
-- a stored projected_value; this one recomputes in place if weekly_actuals is
-- corrected later; projection_id already identifies one specific generation,
-- so there is no history being protected by refusing to overwrite here.
--
-- A GAME NOT YET PLAYED GETS NO ROW, not a row of NULLs. That is different
-- from an unmeasured quantity: there is nothing to backtest yet.
CREATE TABLE backtest_results (
  projection_id INTEGER PRIMARY KEY REFERENCES projections(id),
  actual_value  REAL    NOT NULL,
  error         REAL    NOT NULL,
  beat_line     INTEGER CHECK (beat_line IN (0, 1))
);
