import { getDb } from "@/lib/db";
import type { StatType } from "@/lib/projections";

export interface AccuracyRow {
  season: number;
  week: number;
  statType: StatType;
  n: number;
  mae: number;
  rmse: number;
  beatLineN: number;
  beatLineRate: number | null;
}

// Chronological, not by magnitude: this page's whole point is reading a
// trend in the order it happened, the opposite sort direction from the
// weekly board.
const ACCURACY_QUERY = `
SELECT
  season   AS season,
  week     AS week,
  stat_type AS statType,
  n        AS n,
  mae      AS mae,
  rmse     AS rmse,
  beat_line_n AS beatLineN,
  beat_line_rate AS beatLineRate
FROM model_error_weekly
WHERE stat_type = :statType
ORDER BY season ASC, week ASC
`;

export function getAccuracyTrend(statType: StatType): AccuracyRow[] {
  return getDb().prepare(ACCURACY_QUERY).all({ statType }) as AccuracyRow[];
}
