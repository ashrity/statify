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
  statType: StatType;
  projectedValue: number;
  marketLine: number;
  edge: number;
  book: string | null;
  generatedAt: string;
}

export interface BoardFilters {
  season: number;
  week: number;
  position?: string;
  statType?: string;
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
  p.stat_type   AS statType,
  p.projected_value AS projectedValue,
  p.market_line AS marketLine,
  p.edge        AS edge,
  prop.book     AS book,
  p.generated_at AS generatedAt
FROM projections p
JOIN latest ON latest.max_id = p.id
JOIN players pl ON pl.player_id = p.player_id
LEFT JOIN prop_lines prop ON prop.id = p.prop_line_id
WHERE p.edge IS NOT NULL
  AND (:position IS NULL OR pl.position = :position)
  AND (:statType IS NULL OR p.stat_type = :statType)
ORDER BY ABS(p.edge) DESC
`;

export function getWeeklyBoard(filters: BoardFilters): BoardRow[] {
  return getDb()
    .prepare(BOARD_QUERY)
    .all({
      season: filters.season,
      week: filters.week,
      position: filters.position ?? null,
      statType: filters.statType ?? null,
    }) as BoardRow[];
}
