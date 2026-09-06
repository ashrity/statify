-- How fast a team's offense played, and how much more it passed than the
-- situation called for. Feature 14's game-environment factors.
--
-- Keyed to the team that ran the plays, not the defense that faced them. The
-- overview places pace and proe_allowed inside team_defense_weekly, but every
-- pace figure is a property of the offense; a defense's "pace allowed" is just
-- its opponent's pace, reachable by joining games. Storing it once removes the
-- chance of the two views disagreeing.
--
-- Two pace columns because neither definition is right alone. Gaps between
-- snaps measure tempo, but an incompletion stops the clock, so a pass-heavy
-- team looks fast for a reason that is not tempo: raw pace averages 29.1
-- seconds against a median of 36.0, and that gap is the artifact. The
-- situation-neutral figure removes it but loses about a fifth of team-weeks,
-- and not at random, since a blowout has almost no neutral snaps. Both ship
-- with their interval count so a consumer can prefer the neutral value and see
-- when it is unreliable rather than trusting a number computed from four plays.
--
-- proe carries no situation filter. pass_oe is already the deviation from an
-- expected pass rate that accounts for down, distance, score and time, so
-- filtering again would adjust twice.
CREATE TABLE team_tempo_weekly (
  team_abbr                TEXT NOT NULL REFERENCES teams(team_abbr),
  season                   INTEGER NOT NULL,
  week                     INTEGER NOT NULL,
  plays                    INTEGER NOT NULL,
  pace_intervals           INTEGER NOT NULL,
  seconds_per_play         REAL,
  neutral_intervals        INTEGER NOT NULL,
  neutral_seconds_per_play REAL,
  proe                     REAL,
  updated_at               TEXT NOT NULL,
  PRIMARY KEY (team_abbr, season, week)
);

CREATE INDEX idx_team_tempo_season_week ON team_tempo_weekly(season, week);
