import Link from "next/link";
import { getAccuracyTrend } from "@/lib/accuracy";
import { STAT_TYPES, type StatType } from "@/lib/projections";

const STAT_LABELS: Record<StatType, string> = {
  receiving_yards: "Rec Yards",
  receptions: "Receptions",
  rushing_yards: "Rush Yards",
  passing_yards: "Pass Yards",
  touchdowns: "Anytime TD",
};

function isStatType(value: string | undefined): value is StatType {
  return !!value && (STAT_TYPES as readonly string[]).includes(value);
}

export default async function AccuracyPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const params = await searchParams;
  const requested = Array.isArray(params.statType) ? params.statType[0] : params.statType;
  const statType: StatType = isStatType(requested) ? requested : "receiving_yards";

  const rows = getAccuracyTrend(statType);

  return (
    <main className="mx-auto max-w-5xl px-4 py-8">
      <h1 className="text-xl font-semibold">Model accuracy over time</h1>
      <p className="mt-1 text-sm text-muted">
        {STAT_LABELS[statType]} &middot; mean absolute error and RMSE, by week
      </p>

      <div className="mt-4 flex flex-wrap gap-2">
        {STAT_TYPES.map((stat) => (
          <Link
            key={stat}
            href={`/accuracy?statType=${stat}`}
            className={`rounded px-2 py-1 text-sm ${
              statType === stat
                ? "bg-foreground text-background"
                : "bg-surface text-muted hover:text-foreground"
            }`}
          >
            {STAT_LABELS[stat]}
          </Link>
        ))}
      </div>

      <table className="mt-6 w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border text-left text-muted">
            <th className="py-2 pr-3">Season</th>
            <th className="py-2 pr-3">Week</th>
            <th className="py-2 pr-3 text-right">n</th>
            <th className="py-2 pr-3 text-right">MAE</th>
            <th className="py-2 pr-3 text-right">RMSE</th>
            <th className="py-2 pr-3 text-right">Beat line</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.season}-${row.week}`} className="border-b border-border">
              <td className="py-2 pr-3 text-muted">{row.season}</td>
              <td className="py-2 pr-3 text-muted">{row.week}</td>
              <td className="py-2 pr-3 text-right">{row.n}</td>
              <td className="py-2 pr-3 text-right">{row.mae.toFixed(2)}</td>
              <td className="py-2 pr-3 text-right">{row.rmse.toFixed(2)}</td>
              <td className="py-2 pr-3 text-right">
                {row.beatLineN > 0 ? `${(row.beatLineRate! * 100).toFixed(0)}%` : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {rows.length === 0 && (
        <p className="mt-6 text-sm text-muted">No accuracy data yet for this stat type.</p>
      )}
    </main>
  );
}
