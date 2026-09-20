-- How good or bad a defense has been lately, relative to the league, going into
-- each week. Feature 18 multiplies by this.
--
-- team_defense_weekly says what a defense allowed. That is not yet a matchup
-- factor: 0.31 EPA per play means nothing without knowing that receivers
-- average 0.24 against everyone. The factor here is the difference between the
-- two, so a negative number is always a defense playing better than average and
-- a positive one always worse, whatever the position and play type.
--
-- A difference rather than a ratio, because EPA per play crosses zero. Run
-- defense averages about -0.06, so a ratio against it is unstable and flips
-- sign for no reason. Feature 18 can turn a difference into a multiplier; it
-- cannot rescue a ratio that blew up.
--
-- Both sides of that subtraction are STRICTLY PRIOR. A week N row uses only
-- weeks before N, for the defense and for the league baseline alike. Feature
-- 11a's rule and feature 11a's reason: a leak here leaves every number looking
-- entirely reasonable while feature 27's backtest silently measures nothing.
--
-- The league baseline is per position and play type, never one number. WR pass
-- averages +0.24 and RB rush -0.06 on 2024, so a single league figure would
-- make every rushing matchup look wonderful and every passing one dreadful.
--
-- Windows count weeks the defense actually played. A bye is simply a week with
-- no row, so a last-3 window reaches further back rather than folding a zero in.
--
-- plays_* sits beside each rate deliberately. Feature 12b learned this the hard
-- way with rush yards over expected: a rate with no sample size next to it
-- invites a consumer to treat one game's worth of evidence like fifteen.
--
-- Rates are nullable and mean "no prior data", never zero. Zero here would read
-- as "exactly league average", which is a claim rather than a gap.
CREATE TABLE team_matchup_weekly (
  team_abbr                         TEXT NOT NULL REFERENCES teams(team_abbr),
  season                            INTEGER NOT NULL,
  week                              INTEGER NOT NULL,
  position                          TEXT NOT NULL CHECK (position IN ('QB', 'RB', 'WR', 'TE')),
  play_type                         TEXT NOT NULL CHECK (play_type IN ('pass', 'rush')),

  weeks_l3                          INTEGER NOT NULL,
  plays_l3                          INTEGER NOT NULL,
  epa_allowed_per_play_l3           REAL,
  league_epa_allowed_per_play_l3    REAL,
  epa_allowed_over_league_l3        REAL,

  weeks_l5                          INTEGER NOT NULL,
  plays_l5                          INTEGER NOT NULL,
  epa_allowed_per_play_l5           REAL,
  league_epa_allowed_per_play_l5    REAL,
  epa_allowed_over_league_l5        REAL,

  weeks_std                         INTEGER NOT NULL,
  plays_std                         INTEGER NOT NULL,
  epa_allowed_per_play_std          REAL,
  league_epa_allowed_per_play_std   REAL,
  epa_allowed_over_league_std       REAL,

  updated_at                        TEXT NOT NULL,
  PRIMARY KEY (team_abbr, season, week, position, play_type)
);

CREATE INDEX idx_team_matchup_season_week ON team_matchup_weekly(season, week);
