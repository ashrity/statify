import Link from "next/link";
import type { ReactNode } from "react";
import { BOARD_GRID, BoardRow } from "@/components/board/BoardRow";
import { SiteHeader } from "@/components/SiteHeader";
import { STAT_LABELS } from "@/lib/format";
import {
  getBoardGames,
  getLatestBoardWeek,
  getWeeklyBoard,
  POSITIONS,
  STAT_TYPES,
  type BoardGame,
  type BoardRow as Row,
} from "@/lib/projections";

/**
 * Kickoff day in US Eastern, the timezone an NFL slate is actually discussed
 * in, rather than whatever the server happens to be set to.
 */
function kickoffDay(kickoffAt: string): string {
  return new Date(kickoffAt).toLocaleDateString("en-US", {
    weekday: "short",
    timeZone: "America/New_York",
  });
}

function gameLabel(game: BoardGame): string {
  return `${game.awayTeam} @ ${game.homeTeam}`;
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
      className={`rounded-full border px-3 py-1 text-sm transition-colors ${
        active
          ? "border-foreground bg-foreground text-background"
          : "border-border text-muted hover:border-muted hover:text-foreground"
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
  const game = asString(params.game);
  const includeUnavailable = asString(params.includeUnavailable) === "1";

  const latest = getLatestBoardWeek();
  const season = requestedSeason ? Number(requestedSeason) : latest?.season;
  const week = requestedWeek ? Number(requestedWeek) : latest?.week;

  const rows: Row[] =
    season && week
      ? getWeeklyBoard({ season, week, position, statType, game, includeUnavailable })
      : [];
  // Counted rather than inferred, so the note can say how many are hidden
  // without a second opinion about what "unavailable" means.
  const withUnavailable: Row[] =
    season && week && !includeUnavailable
      ? getWeeklyBoard({ season, week, position, statType, game, includeUnavailable: true })
      : rows;
  const hidden = withUnavailable.length - rows.length;
  const games: BoardGame[] = season && week ? getBoardGames(season, week) : [];

  const current = {
    season: requestedSeason,
    week: requestedWeek,
    position,
    statType,
    game,
    includeUnavailable: includeUnavailable ? "1" : undefined,
  };

  const overs = rows.filter((row) => row.edge > 0).length;

  return (
    <>
      <SiteHeader active="/" />
      <main className="mx-auto max-w-6xl px-4 py-6">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Weekly board</h1>
            {season && week ? (
              <p className="mt-1 text-sm text-muted">
                Season {season}, week {week}. Sorted by edge, overs first and unders last.
              </p>
            ) : (
              <p className="mt-1 text-sm text-muted">
                No projections with a matched market line yet.
              </p>
            )}
          </div>
          {rows.length > 0 && (
            <p className="text-sm text-muted">
              <span className="text-foreground">{rows.length}</span> lines &middot;{" "}
              <span className="text-positive">{overs} over</span> &middot;{" "}
              <span className="text-negative">{rows.length - overs} under</span>
            </p>
          )}
        </div>

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

        {games.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            <FilterLink href={buildHref(current, { game: undefined })} active={!game}>
              All games
            </FilterLink>
            {games.map((g) => (
              <FilterLink
                key={g.gameId}
                href={buildHref(current, { game: g.gameId })}
                active={game === g.gameId}
              >
                {gameLabel(g)}
                <span className="ml-1.5 text-xs opacity-60">{kickoffDay(g.kickoffAt)}</span>
              </FilterLink>
            ))}
          </div>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <FilterLink
            href={buildHref(current, { includeUnavailable: undefined })}
            active={!includeUnavailable}
          >
            Available only
          </FilterLink>
          <FilterLink
            href={buildHref(current, { includeUnavailable: "1" })}
            active={includeUnavailable}
          >
            Include players listed Out
          </FilterLink>
          {!includeUnavailable && hidden > 0 && (
            <span className="text-xs text-muted">
              {hidden} row{hidden === 1 ? "" : "s"} hidden: the latest injury report rules
              those players Out
            </span>
          )}
        </div>

        {/* An edge is only comparable within one stat type, so a mixed board is
            ranked but not like for like. Worth saying once, above the table. */}
        {!statType && rows.length > 0 && (
          <p className="mt-4 text-xs text-muted">
            Showing every stat type together. Yards and receptions are not on the same
            scale, so filter to one stat for a like-for-like ranking.
          </p>
        )}

        <div className="mt-4 overflow-hidden rounded-lg border border-border">
          <div
            className={`${BOARD_GRID} border-b border-border bg-surface px-2 py-2 text-xs uppercase tracking-wide text-muted`}
          >
            <span>Player</span>
            <span>Stat</span>
            <span className="text-right">Line</span>
            <span className="text-right">Projection</span>
            <span className="text-right">Edge</span>
            <span className="text-right">Conf</span>
            <span className="text-right">Book</span>
          </div>
          {rows.map((row) => (
            <BoardRow key={`${row.playerId}-${row.statType}`} row={row} />
          ))}
          {rows.length === 0 && (
            <p className="px-3 py-6 text-sm text-muted">
              {season && week
                ? "No rows match the current filters."
                : "Run the pipeline to generate projections."}
            </p>
          )}
        </div>
      </main>
    </>
  );
}
