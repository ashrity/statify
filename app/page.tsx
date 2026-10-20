import Link from "next/link";
import type { ReactNode } from "react";
import {
  getLatestBoardWeek,
  getWeeklyBoard,
  POSITIONS,
  STAT_TYPES,
  type BoardRow,
  type StatType,
} from "@/lib/projections";

const STAT_LABELS: Record<StatType, string> = {
  receiving_yards: "Rec Yards",
  receptions: "Receptions",
  rushing_yards: "Rush Yards",
  passing_yards: "Pass Yards",
  touchdowns: "Anytime TD",
};

function formatValue(statType: StatType, value: number): string {
  if (statType === "touchdowns") {
    return `${(value * 100).toFixed(1)}%`;
  }
  if (statType === "receptions") {
    return value.toFixed(1);
  }
  return value.toFixed(1);
}

function formatEdge(statType: StatType, edge: number): string {
  const sign = edge > 0 ? "+" : "";
  if (statType === "touchdowns") {
    return `${sign}${(edge * 100).toFixed(1)} pts`;
  }
  return `${sign}${edge.toFixed(1)}`;
}

function edgeColorClass(edge: number): string {
  if (edge > 0) return "text-positive";
  if (edge < 0) return "text-negative";
  return "text-muted";
}

function buildHref(
  current: Record<string, string | undefined>,
  changes: Record<string, string | undefined>,
): string {
  const params = new URLSearchParams();
  const merged = { ...current, ...changes };
  for (const [key, value] of Object.entries(merged)) {
    if (value) params.set(key, value);
  }
  const query = params.toString();
  return query ? `/?${query}` : "/";
}

function FilterLink({
  href,
  active,
  children,
}: {
  href: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      className={`rounded px-2 py-1 text-sm ${
        active
          ? "bg-foreground text-background"
          : "bg-surface text-muted hover:text-foreground"
      }`}
    >
      {children}
    </Link>
  );
}

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const asString = (value: string | string[] | undefined) =>
    Array.isArray(value) ? value[0] : value;

  const requestedSeason = asString(params.season);
  const requestedWeek = asString(params.week);
  const position = asString(params.position);
  const statType = asString(params.statType);

  const latest = getLatestBoardWeek();
  const season = requestedSeason ? Number(requestedSeason) : latest?.season;
  const week = requestedWeek ? Number(requestedWeek) : latest?.week;

  const rows: BoardRow[] =
    season && week ? getWeeklyBoard({ season, week, position, statType }) : [];

  const current = {
    season: requestedSeason,
    week: requestedWeek,
    position,
    statType,
  };

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-xl font-semibold">Statify</h1>
      {season && week ? (
        <p className="mt-1 text-sm text-muted">
          Season {season}, week {week} &middot; sorted by edge size
        </p>
      ) : (
        <p className="mt-1 text-sm text-muted">
          No projections with a matched market line yet.
        </p>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <FilterLink href={buildHref(current, { position: undefined })} active={!position}>
          All positions
        </FilterLink>
        {POSITIONS.map((pos) => (
          <FilterLink
            key={pos}
            href={buildHref(current, { position: pos })}
            active={position === pos}
          >
            {pos}
          </FilterLink>
        ))}
      </div>

      <div className="mt-2 flex flex-wrap gap-2">
        <FilterLink href={buildHref(current, { statType: undefined })} active={!statType}>
          All stats
        </FilterLink>
        {STAT_TYPES.map((stat) => (
          <FilterLink
            key={stat}
            href={buildHref(current, { statType: stat })}
            active={statType === stat}
          >
            {STAT_LABELS[stat]}
          </FilterLink>
        ))}
      </div>

      <table className="mt-6 w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted">
            <th className="py-2 pr-3">Player</th>
            <th className="py-2 pr-3">Pos</th>
            <th className="py-2 pr-3">Team</th>
            <th className="py-2 pr-3">Stat</th>
            <th className="py-2 pr-3">Book</th>
            <th className="py-2 pr-3 text-right">Line</th>
            <th className="py-2 pr-3 text-right">Projection</th>
            <th className="py-2 pr-3 text-right">Edge</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={`${row.playerId}-${row.statType}`}
              className="border-b border-border"
            >
              <td className="py-2 pr-3">{row.name}</td>
              <td className="py-2 pr-3 text-muted">{row.position}</td>
              <td className="py-2 pr-3 text-muted">{row.teamAbbr}</td>
              <td className="py-2 pr-3 text-muted">{STAT_LABELS[row.statType]}</td>
              <td className="py-2 pr-3 text-muted">{row.book ?? "-"}</td>
              <td className="py-2 pr-3 text-right">
                {formatValue(row.statType, row.marketLine)}
              </td>
              <td className="py-2 pr-3 text-right">
                {formatValue(row.statType, row.projectedValue)}
              </td>
              <td className={`py-2 pr-3 text-right font-medium ${edgeColorClass(row.edge)}`}>
                {formatEdge(row.statType, row.edge)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {rows.length === 0 && season && week && (
        <p className="mt-6 text-sm text-muted">No rows match the current filters.</p>
      )}
    </main>
  );
}
