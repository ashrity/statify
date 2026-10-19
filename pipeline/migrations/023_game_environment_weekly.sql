-- What kind of game this is expected to be, per team. Feature 18 multiplies
-- opportunity by these: a 30-point implied total against a fast opponent is a
-- very different projection from 17 against a slow one.
--
-- A row per team per game, because an implied total belongs to a team and so
-- does pace. The opponent's figures ride on the same row rather than making
-- feature 18 self-join, since game pace is set by both offences: a fast team
-- facing a slow one sees fewer drives than its own number suggests.
--
-- Driven by games, not by the market. Every game in a season gets a row, and
-- the market half is NULL where no capture exists. Past weeks can never have
-- one, because historical odds are a paid tier, and feature 23's backtest will
-- still want the pace half for them.
--
-- The market columns are a consensus across books at each book's latest
-- capture: the median spread and the median game total, with the implied total
-- DERIVED from those two rather than taken as a third median. Three
-- independent medians over disagreeing books need not satisfy
-- total / 2 - spread / 2, and that identity is the thing worth being able to
-- check.
--
-- Pace and PROE are strictly prior: a week N row uses weeks before N only. The
-- same rule as features 11a, 13a and 13b, and the same reason. A week 7 row
-- using week 7's own pace would be describing the game it is meant to project.
--
-- Both are volume-weighted rather than a mean of weekly rates.
-- team_tempo_weekly stores neutral_seconds_per_play beside neutral_intervals
-- and proe beside plays precisely so that is possible; a blowout week with 4
-- neutral snaps must not weigh the same as a close one with 30.
--
-- NO WEATHER HERE, DELIBERATELY. Migration 008 records that the weather
-- reading is the settled game-time condition rather than a pre-kickoff
-- forecast, and warns this feature against treating it as forward-looking.
-- Using it would leak the result of the game being projected, which is exactly
-- what features 11a and 13a have direct tests against. Feature 14b adds a
-- forecast source and then the adjustment.
--
-- books, pace_weeks and proe_weeks are the sample sizes. Feature 12b learned
-- the hard way that a value with no sample size beside it invites a consumer
-- to trust one book, or one week, as much as nine.
CREATE TABLE game_environment_weekly (
  game_id            TEXT NOT NULL REFERENCES games(game_id),
  team_abbr          TEXT NOT NULL REFERENCES teams(team_abbr),
  season             INTEGER NOT NULL,
  week               INTEGER NOT NULL,

  spread             REAL,
  game_total         REAL,
  implied_team_total REAL,
  books              INTEGER NOT NULL,
  market_captured_at TEXT,

  pace               REAL,
  pace_weeks         INTEGER NOT NULL,
  proe               REAL,
  proe_weeks         INTEGER NOT NULL,

  opponent_pace      REAL,
  opponent_proe      REAL,

  updated_at         TEXT NOT NULL,
  PRIMARY KEY (game_id, team_abbr)
);

CREATE INDEX idx_game_environment_season_week ON game_environment_weekly(season, week);
