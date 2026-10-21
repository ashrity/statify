-- Fills the one gap team_volume_weekly's own migration names by number:
-- "Week 1 is entirely NULL and that is the answer, not a bug... Feature 30's
-- cross-season shrinkage is what would fill it." These columns are that
-- shrinkage, additive beside the existing ones, the same pattern migrations
-- 014, 015, 017 and 018 used to extend player_form_weekly without disturbing
-- what was already there.
--
-- own_targets_pg, own_carries_pg AND own_attempts_pg KEEP THEIR EXISTING
-- MEANING, UNCHANGED: pure in-season, exactly as feature 15a shipped and
-- verified them. The cross-season blend sits between that and exp_targets,
-- never inside own_targets_pg itself, so a reader who already trusts that
-- column's definition is not surprised by it.
--
-- cross_season_weight = games_played / (games_played + k): 0 at week 1
-- (pure prior season, the exact row that was previously NULL), approaching 1
-- as the season goes on (pure current season, matching what the table
-- already did before this feature existed). k is measured and fixed in
-- code, like every other weight in this pipeline.
--
-- NULL WHEN THERE IS NO PRIOR SEASON ON FILE, which is every 2024 row: this
-- project has nothing before 2024. exp_targets/exp_carries/exp_attempts on
-- those rows are provably unchanged, because blend() collapses to the
-- existing own_targets_pg whenever prior_season_targets_pg is NULL.
--
-- "Prior season" means the most recent earlier season this database has
-- weekly_actuals for, not a multi-season career average. For 2026 that is
-- 2025, ingested as this feature's own prerequisite; games already had
-- 2025's schedule, but weekly_actuals did not until now.
--
-- ONE SHARED k, MEASURED ON 2026 WEEKS 1 TO 5, THE ONLY WEEKS WITH BOTH A
-- PRIOR SEASON AND GAMES LEFT TO SHRINK. Mean absolute error against actual
-- team volume, 126 team-weeks:
--
--            k=8      k=12 (argmin)   k=20     no shrinkage
--   targets   5.8798   5.8786          5.8790    6.2589
--   carries   5.3017   5.2954          5.2959    5.9399
--   attempts  6.1316   6.1313          6.1304    6.4524
--
-- Shrinkage beat no shrinkage for every quantity, by a wide margin for
-- targets and carries. targets and carries show a real, if shallow, interior
-- minimum near k=12; attempts is nearly flat across the whole range tried
-- (k=1000 differs from k=8 by 0.004, noise). One shared k=10.0 ships rather
-- than three separately fit constants: a single season is not enough
-- evidence to trust three noisy per-quantity optima, and all three cluster
-- near this value regardless.
ALTER TABLE team_volume_weekly ADD COLUMN prior_season INTEGER;
ALTER TABLE team_volume_weekly ADD COLUMN prior_season_targets_pg REAL;
ALTER TABLE team_volume_weekly ADD COLUMN prior_season_carries_pg REAL;
ALTER TABLE team_volume_weekly ADD COLUMN prior_season_attempts_pg REAL;
ALTER TABLE team_volume_weekly ADD COLUMN cross_season_weight REAL;
