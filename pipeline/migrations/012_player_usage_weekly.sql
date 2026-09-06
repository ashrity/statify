-- What share of his team's opportunity each player took, per game. The
-- opportunity half of the projection: feature 15 multiplies these by efficiency
-- to get expected volume.
--
-- Stored rather than derived, which settles the question project-overview.md
-- left open. A view would be attractive at this size and could never go stale,
-- but the air yards denominator has to come from play-by-play and is not in the
-- database, so a view would need a denominators table anyway or the wrong
-- number. Storing also puts the arithmetic in functions the tests can reach.
-- The cost is that this table must be recomputed after anything writes
-- weekly_actuals; AGENTS.md carries that ordering rule.
--
-- Each metric keeps its numerator and denominator beside the share, because a
-- share cannot be re-aggregated across weeks and feature 11 needs the parts.
--
-- Every share is nullable. A zero denominator is a real state: a team that
-- attempted no passes has no target share to give, and storing 0.0 would say
-- "took none of the opportunity" where the truth is "there was none".
--
-- air_yards_share can legitimately be negative. A pass behind the line of
-- scrimmage carries negative air yards, so any clamp here would be wrong.
CREATE TABLE player_usage_weekly (
  player_id             TEXT NOT NULL REFERENCES players(player_id),
  game_id               TEXT NOT NULL REFERENCES games(game_id),
  season                INTEGER NOT NULL,
  week                  INTEGER NOT NULL,
  team_abbr             TEXT NOT NULL REFERENCES teams(team_abbr),
  targets               INTEGER NOT NULL,
  team_targets          INTEGER NOT NULL,
  target_share          REAL,
  air_yards             INTEGER NOT NULL,
  team_air_yards        INTEGER NOT NULL,
  air_yards_share       REAL,
  wopr                  REAL,
  adot                  REAL,
  red_zone_touches      INTEGER,
  team_red_zone_touches INTEGER,
  red_zone_touch_share  REAL,
  updated_at            TEXT NOT NULL,
  PRIMARY KEY (player_id, game_id)
);

CREATE INDEX idx_player_usage_season_week ON player_usage_weekly(season, week);
