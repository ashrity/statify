import type { StatType } from "@/lib/projections";

export const STAT_LABELS: Record<StatType, string> = {
  receiving_yards: "Rec Yards",
  receptions: "Receptions",
  rushing_yards: "Rush Yards",
  passing_yards: "Pass Yards",
  touchdowns: "Anytime TD",
};

/**
 * `touchdowns` is a probability, not a count: feature 17 projects it as a
 * Poisson tail and feature 7b's market quotes it against a fixed 0.5 line, so
 * it reads as a percentage while every other stat reads as its own unit.
 */
export function formatValue(statType: StatType, value: number): string {
  if (statType === "touchdowns") return `${(value * 100).toFixed(1)}%`;
  return value.toFixed(1);
}

export function formatEdge(statType: StatType, edge: number): string {
  const sign = edge > 0 ? "+" : "";
  if (statType === "touchdowns") return `${sign}${(edge * 100).toFixed(1)} pts`;
  return `${sign}${edge.toFixed(1)}`;
}

export function formatConfidence(confidence: number | null): string {
  return confidence === null ? "-" : `${(confidence * 100).toFixed(0)}%`;
}

/** American odds, which carry their own sign and need the plus kept. */
export function formatOdds(odds: number | null): string {
  if (odds === null) return "-";
  return odds > 0 ? `+${odds}` : `${odds}`;
}

export function edgeToneClass(edge: number): string {
  if (edge > 0) return "text-positive";
  if (edge < 0) return "text-negative";
  return "text-muted";
}
