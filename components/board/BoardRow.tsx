import { PlayerAvatar } from "@/components/board/PlayerAvatar";
import { explainRow } from "@/lib/explain";
import {
  STAT_LABELS,
  edgeToneClass,
  formatConfidence,
  formatEdge,
  formatOdds,
  formatValue,
} from "@/lib/format";
import type { BoardRow as Row } from "@/lib/projections";

/** Shared by the header and every row so the columns line up without a table. */
export const BOARD_GRID =
  "grid grid-cols-[1.9fr_3rem_4.5rem_5rem_4.5rem_5rem_5rem] items-center gap-x-3";

/**
 * One player's row, expandable into the arithmetic behind its edge.
 *
 * A native `<details>` rather than client-side state: the whole row is the
 * toggle, it needs no JavaScript, and the page stays a server component. The
 * columns are a grid rather than a `<table>` because a `<details>` cannot
 * legally wrap a `<tr>`, and a second row per player would halve the density.
 */
export function BoardRow({ row }: { row: Row }) {
  const explanation = explainRow(row);

  return (
    <details className="group border-b border-border">
      <summary
        className={`${BOARD_GRID} cursor-pointer list-none px-2 py-2 hover:bg-surface`}
      >
        <span className="flex min-w-0 items-center gap-2">
          <PlayerAvatar
            name={row.name}
            headshotUrl={row.headshotUrl}
            logoUrl={row.logoUrl}
            colorPrimary={row.colorPrimary}
            teamAbbr={row.teamAbbr}
          />
          <span className="min-w-0">
            <span className="block truncate font-medium">{row.name}</span>
            <span className="block text-xs text-muted">
              {row.position} {row.teamAbbr}
              {row.opponentTeamAbbr && ` vs ${row.opponentTeamAbbr}`}
              {row.designation && (
                <span
                  className={`ml-1.5 rounded px-1 py-0.5 text-[10px] font-semibold uppercase ${
                    row.designation === "Questionable"
                      ? "bg-surface text-muted"
                      : "bg-negative/15 text-negative"
                  }`}
                >
                  {row.designation === "Questionable" ? "Q" : row.designation}
                </span>
              )}
            </span>
          </span>
        </span>

        <span className="text-xs text-muted">{STAT_LABELS[row.statType]}</span>
        <span className="text-right tabular-nums text-muted">
          {formatValue(row.statType, row.marketLine)}
        </span>
        <span className="text-right tabular-nums">
          {formatValue(row.statType, row.projectedValue)}
        </span>
        <span className={`text-right font-semibold tabular-nums ${edgeToneClass(row.edge)}`}>
          {formatEdge(row.statType, row.edge)}
        </span>
        <span className="text-right tabular-nums text-muted">
          {formatConfidence(row.confidence)}
        </span>
        <span className="flex items-center justify-end gap-1 text-xs text-muted">
          {row.book ?? "-"}
          <span className="transition-transform group-open:rotate-90">›</span>
        </span>
      </summary>

      <div className="bg-surface px-2 pb-4 pt-1 text-sm">
        <dl className="mx-auto max-w-2xl">
          {explanation.steps.map((step) => (
            <div
              key={step.label}
              className={`flex gap-3 border-t border-border/60 py-1.5 ${
                step.total ? "mt-1 border-t-2 border-border font-semibold" : ""
              }`}
            >
              <span className="w-4 shrink-0 text-right text-muted">{step.operator}</span>
              <dt className="flex-1">
                {step.label}
                {step.note && <span className="block text-xs text-muted">{step.note}</span>}
              </dt>
              <dd
                className={`shrink-0 tabular-nums ${
                  step.total ? edgeToneClass(row.edge) : ""
                }`}
              >
                {step.value}
              </dd>
            </div>
          ))}
        </dl>

        <p className="mx-auto mt-3 max-w-2xl text-xs text-muted">{explanation.confidence}</p>
        {explanation.caveat && (
          <p className="mx-auto mt-1 max-w-2xl text-xs text-muted">{explanation.caveat}</p>
        )}
        <p className="mx-auto mt-1 max-w-2xl text-xs text-muted">
          Market price {formatOdds(row.overOdds)}
          {row.underOdds !== null && ` over / ${formatOdds(row.underOdds)} under`}.
          {row.priorGames !== null &&
            ` Built from ${row.priorGames} prior game${row.priorGames === 1 ? "" : "s"} this season,`}
          {row.priorGames !== null ? " all" : " Every number above is"} strictly before this week.
        </p>

        {explanation.warnings.map((warning) => (
          <p
            key={warning}
            className="mx-auto mt-2 max-w-2xl border-l-2 border-negative pl-2 text-xs text-muted"
          >
            {warning}
          </p>
        ))}
      </div>
    </details>
  );
}
