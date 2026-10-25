import { getDb } from "@/lib/db";

export const STAT_TYPES = [
  "receiving_yards",
  "receptions",
  "rushing_yards",
  "passing_yards",
  "touchdowns",
] as const;

export type StatType = (typeof STAT_TYPES)[number];

export const POSITIONS = ["QB", "RB", "WR", "TE"] as const;

export type Position = (typeof POSITIONS)[number];

export interface BoardRow {
  playerId: string;
  name: string;
  position: string;
  teamAbbr: string;
  headshotUrl: string | null;
  logoUrl: string | null;
  colorPrimary: string | null;
  opponentTeamAbbr: string | null;
  gameId: string | null;
  statType: StatType;
  projectedValue: number;
  marketLine: number;
  edge: number;
  confidence: number | null;
  book: string | null;
  overOdds: number | null;
  underOdds: number | null;
  generatedAt: string;

  // The components behind the projection, for the per-row explanation.
  baselineValue: number | null;
  matchupMultiplier: number | null;
  environmentMultiplier: number | null;
  expTargets: number | null;
  expCarries: number | null;
  expAttempts: number | null;
  expYardsPerTarget: number | null;
  expCatchRate: number | null;
  expYardsPerCarry: number | null;
  expYardsPerAttempt: number | null;
  expTouchdowns: number | null;
  ownStddev: number | null;
  /**
   * The multipliers as feature 18 stored them, before feature 19 substituted a
   * NULL as neutral. Needed to tell "league-average matchup" apart from "no
   * matchup data for a week nobody has played", which both read as 1.000 on
   * `matchupMultiplier`.
   */
  passMatchupMultiplier: number | null;
  rushMatchupMultiplier: number | null;
  /** Games this season before this week. The sample every rate above rests on. */
  priorGames: number | null;
  /** True when the matched line was captured after the projection was generated. */
  lineCapturedLater: boolean;
  /** Out, Doubtful, Questionable, or null when the player is not on the report. */
  designation: string | null;
  /** DNP, Limited or Full. */
  practiceStatus: string | null;
}

export interface BoardFilters {
  season: number;
  week: number;
  position?: string;
  statType?: string;
  game?: string;
  /** Show players the latest injury report rules Out. Off by default. */
  includeUnavailable?: boolean;
}

export interface BoardGame {
  gameId: string;
  awayTeam: string;
  homeTeam: string;
  kickoffAt: string;
}

/** The most recent (season, week) with at least one matched edge, or null if none exists yet. */
export function getLatestBoardWeek(): { season: number; week: number } | null {
  const row = getDb()
    .prepare(
      `SELECT season, week FROM projections
       WHERE edge IS NOT NULL
       ORDER BY season DESC, week DESC
       LIMIT 1`,
    )
    .get() as { season: number; week: number } | undefined;
  return row ?? null;
}

// Feature 20's projections accumulate a history rather than holding one
// current row per key, so a view of "now" must pick only the latest
// generation per (player, week, stat_type) or a week with more than one run
// would show duplicate rows for the same player/stat.
//
// Sorted by signed edge descending: the biggest positive edges (the model
// says over) at the top, the biggest negative ones (the model says under) at
// the bottom. Edges are not on one scale across stat types, so the stat-type
// filter is what makes a like-for-like ranking.
const BOARD_QUERY = `
WITH latest AS (
  SELECT player_id, week, stat_type, MAX(id) AS max_id
  FROM projections
  WHERE season = :season AND week = :week
  GROUP BY player_id, week, stat_type
)
SELECT
  p.player_id   AS playerId,
  pl.name       AS name,
  pl.position   AS position,
  pl.team_abbr  AS teamAbbr,
  pl.headshot_url AS headshotUrl,
  t.logo_url    AS logoUrl,
  t.color_primary AS colorPrimary,
  me.opponent_team_abbr AS opponentTeamAbbr,
  g.game_id     AS gameId,
  p.stat_type   AS statType,
  p.projected_value AS projectedValue,
  p.market_line AS marketLine,
  p.edge        AS edge,
  p.confidence  AS confidence,
  prop.book     AS book,
  prop.over_odds  AS overOdds,
  prop.under_odds AS underOdds,
  p.generated_at AS generatedAt,
  r.baseline_value AS baselineValue,
  r.matchup_multiplier_used AS matchupMultiplier,
  r.environment_multiplier_used AS environmentMultiplier,
  o.exp_targets  AS expTargets,
  o.exp_carries  AS expCarries,
  o.exp_attempts AS expAttempts,
  e.exp_yards_per_target  AS expYardsPerTarget,
  e.exp_catch_rate        AS expCatchRate,
  e.exp_yards_per_carry   AS expYardsPerCarry,
  e.exp_yards_per_attempt AS expYardsPerAttempt,
  td.exp_touchdowns AS expTouchdowns,
  v.own_stddev AS ownStddev,
  me.pass_matchup_multiplier AS passMatchupMultiplier,
  me.rush_matchup_multiplier AS rushMatchupMultiplier,
  inj.designation AS designation,
  inj.practice_status AS practiceStatus,
  o.games_played AS priorGames,
  -- Recoverable without a column on projections: a line captured after the
  -- projection was generated means compute edge took its later-capture
  -- fallback, so the row is scored against a line it could not have seen.
  (prop.captured_at > p.generated_at) AS lineCapturedLater
FROM projections p
JOIN latest ON latest.max_id = p.id
JOIN players pl ON pl.player_id = p.player_id
LEFT JOIN teams t ON t.team_abbr = pl.team_abbr
LEFT JOIN prop_lines prop ON prop.id = p.prop_line_id
LEFT JOIN player_raw_projection_weekly r
  ON r.player_id = p.player_id AND r.season = p.season AND r.week = p.week AND r.stat_type = p.stat_type
LEFT JOIN player_opportunity_weekly o
  ON o.player_id = p.player_id AND o.season = p.season AND o.week = p.week
LEFT JOIN player_efficiency_expected_weekly e
  ON e.player_id = p.player_id AND e.season = p.season AND e.week = p.week
LEFT JOIN player_touchdown_expected_weekly td
  ON td.player_id = p.player_id AND td.season = p.season AND td.week = p.week
LEFT JOIN player_matchup_environment_weekly me
  ON me.player_id = p.player_id AND me.season = p.season AND me.week = p.week
LEFT JOIN player_variance_weekly v
  ON v.player_id = p.player_id AND v.season = p.season AND v.week = p.week AND v.stat_type = p.stat_type
-- Keyed on the team feature 18 recorded for this week, not players.team_abbr,
-- which is the player's current team: 2 of 2026 week 7's rows disagree, and
-- the schema notes warn that a trade must not rewrite history.
LEFT JOIN games g
  ON g.season = p.season AND g.week = p.week
 AND (g.home_team = me.team_abbr OR g.away_team = me.team_abbr)
-- The latest report for that player and week. Designations move through the
-- week, which is why report_at is part of this table's key, so an unqualified
-- join would multiply a row by every revision.
LEFT JOIN injuries inj
  ON inj.player_id = p.player_id AND inj.season = p.season AND inj.week = p.week
 AND inj.report_at = (
      SELECT MAX(i2.report_at) FROM injuries i2
      WHERE i2.player_id = p.player_id AND i2.season = p.season AND i2.week = p.week
    )
WHERE p.edge IS NOT NULL
  AND (:position IS NULL OR pl.position = :position)
  AND (:statType IS NULL OR p.stat_type = :statType)
  AND (:game IS NULL OR g.game_id = :game)
  -- A projection for a player who will not play is not wrong so much as
  -- meaningless, and the model has no idea: nothing upstream reads this table,
  -- so his volume is still projected as though he were starting.
  AND (:includeUnavailable = 1 OR inj.designation IS NULL OR inj.designation <> 'Out')
ORDER BY p.edge DESC
`;

/** The week's games that actually have board rows, in kickoff order. */
const BOARD_GAMES_QUERY = `
SELECT DISTINCT
  g.game_id   AS gameId,
  g.away_team AS awayTeam,
  g.home_team AS homeTeam,
  g.kickoff_at AS kickoffAt
FROM projections p
JOIN player_matchup_environment_weekly me
  ON me.player_id = p.player_id AND me.season = p.season AND me.week = p.week
JOIN games g
  ON g.season = p.season AND g.week = p.week
 AND (g.home_team = me.team_abbr OR g.away_team = me.team_abbr)
WHERE p.season = :season AND p.week = :week AND p.edge IS NOT NULL
ORDER BY g.kickoff_at, g.game_id
`;

export function getBoardGames(season: number, week: number): BoardGame[] {
  return getDb().prepare(BOARD_GAMES_QUERY).all({ season, week }) as BoardGame[];
}

/** SQLite has no boolean type, so the comparison comes back as 0 or 1. */
type RawBoardRow = Omit<BoardRow, "lineCapturedLater"> & { lineCapturedLater: number };

export function getWeeklyBoard(filters: BoardFilters): BoardRow[] {
  const rows = getDb()
    .prepare(BOARD_QUERY)
    .all({
      season: filters.season,
      week: filters.week,
      position: filters.position ?? null,
      statType: filters.statType ?? null,
      game: filters.game ?? null,
      includeUnavailable: filters.includeUnavailable ? 1 : 0,
    }) as RawBoardRow[];

  return rows.map((row) => ({ ...row, lineCapturedLater: row.lineCapturedLater === 1 }));
}
