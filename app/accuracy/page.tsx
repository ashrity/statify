import Link from "next/link";
import { SiteHeader } from "@/components/SiteHeader";
import { getAccuracyTrend } from "@/lib/accuracy";
import { STAT_LABELS } from "@/lib/format";
import { STAT_TYPES, type StatType } from "@/lib/projections";

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
    <>
      <SiteHeader active="/accuracy" />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <h1 className="text-2xl font-semibold tracking-tight">Model accuracy</h1>
        <p className="mt-1 text-sm text-muted">
          {STAT_LABELS[statType]} &middot; mean absolute error and RMSE, by week
        </p>

        <div className="mt-4 flex flex-wrap gap-2">
          {STAT_TYPES.map((stat) => (
            <Link
              key={stat}
              href={`/accuracy?statType=${stat}`}
              className={`rounded-full border px-3 py-1 text-sm transition-colors ${
                statType === stat
                  ? "border-foreground bg-foreground text-background"
                  : "border-border text-muted hover:border-muted hover:text-foreground"
              }`}
            >
              {STAT_LABELS[stat]}
            </Link>
          ))}
        </div>

        <div className="mt-4 overflow-hidden rounded-lg border border-border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-border bg-surface text-left text-xs uppercase tracking-wide text-muted">
                <th className="px-3 py-2">Season</th>
                <th className="px-3 py-2">Week</th>
                <th className="px-3 py-2 text-right">n</th>
                <th className="px-3 py-2 text-right">MAE</th>
                <th className="px-3 py-2 text-right">RMSE</th>
                <th className="px-3 py-2 text-right">Beat line</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.season}-${row.week}`} className="border-b border-border">
                  <td className="px-3 py-2 text-muted">{row.season}</td>
                  <td className="px-3 py-2 text-muted">{row.week}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.n}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.mae.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{row.rmse.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {row.beatLineN > 0 ? `${(row.beatLineRate! * 100).toFixed(0)}%` : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {rows.length === 0 && (
            <p className="px-3 py-6 text-sm text-muted">
              No accuracy data yet for this stat type.
            </p>
          )}
        </div>
      </main>
    </>
  );
}
