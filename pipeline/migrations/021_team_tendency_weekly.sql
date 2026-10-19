-- What a defense does, as opposed to how well it does it.
--
-- Feature 13a rated defenses: EPA allowed against the league, where negative is
-- better. This table ranks nobody. A defense that plays man 61% of the time is
-- not better or worse than one that plays zone, it is a different problem, and
-- a receiver who separates against press cares about which one he is facing in
-- a way no EPA figure captures. Feature 18 pairs these with player traits
-- rather than treating them as quality.
--
-- That is also why there is no league baseline here, unlike team_matchup_weekly.
-- "0.31 EPA allowed" means nothing without knowing the league allows 0.24, but
-- "plays man 61% of the time" is already the fact feature 18 wants.
--
-- READ THIS BEFORE COMPARING man_rate TO ANYTHING. Measured on 2024 the league
-- man rate here is 48.5%. Next Gen Stats and PFF both publish figures nearer 30
-- to 35%. Neither is wrong; they chart to different definitions, the same way
-- this project's yacoe differs from the Next Gen Stats column of that name.
-- A man rate from this table is comparable only to another man rate from this
-- table. What survives the difference is the ordering, and the ordering is
-- right: Denver and Detroit most man at 61%, Green Bay most zone at 32% man.
--
-- The blitz and sack orderings land the same way. Minnesota tops blitz rate at
-- 40%, which is Brian Flores doing what he is known for, and Denver tops sack
-- rate at 8.8%. None of that was fitted.
--
-- Every rate divides by a denominator counted over the same plays as its
-- numerator: man by coverage_snaps, blitz and rushers by rusher_snaps, sacks
-- and hits by dropbacks. The three denominators differ because the three feeds
-- do: coverage is charted only on dropbacks nflverse classified, rusher counts
-- only where it recorded one, and sacks come from play-by-play, which has them
-- all. Mixing them would produce a plausible number computed from two different
-- populations.
--
-- Counts are NOT NULL and rates are nullable, following migration 012. A zero
-- denominator means the week has nothing to measure, not a rate of zero.
--
-- coverage_snaps is also the sample size, and it is small enough to matter:
-- measured on 2024 the median team-week has 37 charted snaps and the thinnest
-- has 14. Read it before trusting a single week's man_rate.
CREATE TABLE team_tendency_weekly (
  team_abbr                 TEXT NOT NULL REFERENCES teams(team_abbr),
  season                    INTEGER NOT NULL,
  week                      INTEGER NOT NULL,

  coverage_snaps            INTEGER NOT NULL,
  man_snaps                 INTEGER NOT NULL,
  man_rate                  REAL,

  rusher_snaps              INTEGER NOT NULL,
  blitz_snaps               INTEGER NOT NULL,
  blitz_rate                REAL,
  pass_rushers              INTEGER NOT NULL,
  pass_rushers_per_snap     REAL,

  dropbacks                 INTEGER NOT NULL,
  sacks                     INTEGER NOT NULL,
  sack_rate                 REAL,
  qb_hits                   INTEGER NOT NULL,
  qb_hit_rate               REAL,

  weeks_l3                  INTEGER NOT NULL,
  man_rate_l3               REAL,
  blitz_rate_l3             REAL,
  pass_rushers_per_snap_l3  REAL,
  sack_rate_l3              REAL,
  qb_hit_rate_l3            REAL,

  weeks_l5                  INTEGER NOT NULL,
  man_rate_l5               REAL,
  blitz_rate_l5             REAL,
  pass_rushers_per_snap_l5  REAL,
  sack_rate_l5              REAL,
  qb_hit_rate_l5            REAL,

  weeks_std                 INTEGER NOT NULL,
  man_rate_std              REAL,
  blitz_rate_std            REAL,
  pass_rushers_per_snap_std REAL,
  sack_rate_std             REAL,
  qb_hit_rate_std           REAL,

  updated_at                TEXT NOT NULL,
  PRIMARY KEY (team_abbr, season, week)
);

CREATE INDEX idx_team_tendency_season_week ON team_tendency_weekly(season, week);
