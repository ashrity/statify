-- Reference tables. Every weekly table joins against these keys, so treat the
-- primary keys here as permanent.

-- Stadium and roof live on games, not teams: nflverse records them per game, and
-- neutral-site games mean a team's venue is not a stable team attribute.
CREATE TABLE teams (
  team_abbr   TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

-- team_abbr is nullable: free agents exist, and a roster pull can name a player
-- before a team assignment resolves. Weekly tables carry their own team_abbr so a
-- mid-season trade never rewrites history.
CREATE TABLE players (
  player_id   TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  position    TEXT NOT NULL CHECK (position IN ('QB', 'RB', 'WR', 'TE')),
  team_abbr   TEXT REFERENCES teams(team_abbr),
  updated_at  TEXT NOT NULL
);

CREATE TABLE games (
  game_id     TEXT PRIMARY KEY,
  season      INTEGER NOT NULL,
  week        INTEGER NOT NULL,
  game_type   TEXT NOT NULL,
  kickoff_at  TEXT NOT NULL,
  home_team   TEXT NOT NULL REFERENCES teams(team_abbr),
  away_team   TEXT NOT NULL REFERENCES teams(team_abbr),
  is_dome     INTEGER NOT NULL DEFAULT 0 CHECK (is_dome IN (0, 1)),
  updated_at  TEXT NOT NULL
);

CREATE INDEX idx_games_season_week ON games(season, week);
CREATE INDEX idx_players_team ON players(team_abbr);
