import { formatOdds } from "@/lib/format";
import type { BoardRow } from "@/lib/projections";

export interface ExplainStep {
  /** "×", "−" or "=" shown in front of the row; blank for the first line. */
  operator: string;
  label: string;
  value: string;
  /** Where the number came from, in plain English. */
  note?: string;
  /** The final line, the edge itself. */
  total?: boolean;
}

export interface Explanation {
  steps: ExplainStep[];
  confidence: string;
  caveat?: string;
  /** Sample size and line-timing warnings, shown under the arithmetic. */
  warnings: string[];
}

/**
 * The sample behind every rate on the row, and the line's timing.
 *
 * This project is emphatic that a rate means little without its sample count
 * (`player_form_weekly.ryoe_games_l3` carries the same caveat), and the
 * confidence model makes it worse rather than better: two similar games give a
 * tiny standard deviation, so `Phi(edge / stddev)` saturates toward 1.0 on the
 * thinnest samples. A reader has to see the game count to discount that.
 */
function warnings(row: BoardRow): string[] {
  const out: string[] = [];
  if (row.priorGames !== null && row.priorGames <= 2) {
    out.push(
      `Thin sample: ${row.priorGames} prior game${row.priorGames === 1 ? "" : "s"} this ` +
        `season. Every rate above is built from that, and the confidence figure does not ` +
        `account for sample size, only for how much the number moves.`,
    );
  }
  if (row.designation) {
    const practice = row.practiceStatus ? `, practice: ${row.practiceStatus}` : "";
    out.push(
      `Listed ${row.designation} on the latest injury report${practice}. The projection ` +
        `does not know: nothing upstream reads injury data, so his volume above is built ` +
        `as though he were starting, and his team-mates' volume is too.`,
    );
  }
  if (row.lineCapturedLater) {
    out.push(
      "This line was captured after the projection was generated, so the projection " +
        "did not see it. Fine for deciding a bet, but it is not a clean strictly-prior " +
        "comparison for scoring the model.",
    );
  }
  return out;
}

interface ProductParts {
  opportunityLabel: string;
  opportunityValue: number | null;
  opportunityNote: string;
  efficiencyLabel: string;
  efficiencyValue: number | null;
  efficiencyNote: string;
  /** Catch rate reads as a percentage; the yardage rates read as a number. */
  efficiencyIsRate: boolean;
}

function productParts(row: BoardRow): ProductParts | null {
  switch (row.statType) {
    case "receiving_yards":
      return {
        opportunityLabel: "Expected targets",
        opportunityValue: row.expTargets,
        opportunityNote: "his trailing target share applied to the team's projected pass volume",
        efficiencyLabel: "Expected yards per target",
        efficiencyValue: row.expYardsPerTarget,
        efficiencyNote: "his trailing rate, shrunk toward the average at his position",
        efficiencyIsRate: false,
      };
    case "receptions":
      return {
        opportunityLabel: "Expected targets",
        opportunityValue: row.expTargets,
        opportunityNote: "his trailing target share applied to the team's projected pass volume",
        efficiencyLabel: "Expected catch rate",
        efficiencyValue: row.expCatchRate,
        efficiencyNote: "his trailing rate, shrunk toward the average at his position",
        efficiencyIsRate: true,
      };
    case "rushing_yards":
      return {
        opportunityLabel: "Expected carries",
        opportunityValue: row.expCarries,
        opportunityNote: "his trailing carry share applied to the team's projected rush volume",
        efficiencyLabel: "Expected yards per carry",
        efficiencyValue: row.expYardsPerCarry,
        efficiencyNote: "his trailing rate, shrunk toward the average at his position",
        efficiencyIsRate: false,
      };
    case "passing_yards":
      return {
        opportunityLabel: "Expected attempts",
        opportunityValue: row.expAttempts,
        opportunityNote: "his trailing share of the team's projected pass attempts",
        efficiencyLabel: "Expected yards per attempt",
        efficiencyValue: row.expYardsPerAttempt,
        efficiencyNote: "his trailing rate, shrunk toward the average at his position",
        efficiencyIsRate: false,
      };
    default:
      return null;
  }
}

/** Rushing leans on the rush factor, every other stat on the pass factor. */
function upstreamMatchup(row: BoardRow): number | null {
  return row.statType === "rushing_yards"
    ? row.rushMatchupMultiplier
    : row.passMatchupMultiplier;
}

/**
 * Three different things read as 1.000 and they must not be conflated: a
 * coefficient fixed at zero because it was measured and rejected, a genuinely
 * league-average opponent, and no data at all substituted as neutral.
 */
function matchupNote(row: BoardRow, value: number): string {
  const side = row.opponentTeamAbbr ? `vs ${row.opponentTeamAbbr}` : "vs the opponent";
  if (upstreamMatchup(row) === null) {
    return (
      "no adjustment available: opponent defence is only measured through weeks already " +
      "played, so a week nobody has played yet has none, and it is substituted as neutral"
    );
  }
  if (value === 1) {
    return row.statType === "rushing_yards"
      ? `${side}: a league-average run defence, so nothing to adjust`
      : "neutral by construction: a pass-matchup adjustment was measured against results and found to add nothing, so its coefficient is fixed at 0";
  }
  return `${side}: their run defence relative to the league, over their recent weeks`;
}

function environmentNote(row: BoardRow, value: number): string {
  if (value === 1) {
    return "neutral by construction: a pace adjustment was measured against results and found to add nothing, so its coefficient is fixed at 0";
  }
  const side = row.opponentTeamAbbr ? `vs ${row.opponentTeamAbbr}` : "vs the opponent";
  return `${side}: the game's projected pace relative to the league`;
}

function marketLineNote(book: string, capturedLater: boolean): string {
  return capturedLater
    ? `the first line ${book} posted after this projection was generated`
    : `the latest line from ${book} before this projection was generated`;
}

function confidenceNote(row: BoardRow): string {
  if (row.confidence === null) {
    return "Not scored: it takes at least 2 prior games to measure his week-to-week swing.";
  }
  const pct = `${(row.confidence * 100).toFixed(0)}%`;
  if (row.statType === "touchdowns") {
    return (
      `${pct} confidence: the edge measured against how much a single-game ` +
      `coin-toss outcome at this probability naturally swings. A disagreement with the ` +
      `price scores higher than simply being likely to score.`
    );
  }
  if (row.ownStddev === null) {
    return `${pct} confidence.`;
  }
  return (
    `${pct} confidence: the edge measured against his own weekly swing of ` +
    `${row.ownStddev.toFixed(1)}, read off a normal curve. A big edge on a steady ` +
    `player scores higher than the same edge on a volatile one.`
  );
}

/** The chain of arithmetic behind one row's edge, in the order it is computed. */
export function explainRow(row: BoardRow): Explanation {
  const steps: ExplainStep[] = [];

  if (row.statType === "touchdowns") {
    steps.push({
      operator: "",
      label: "Expected touchdowns",
      value: (row.expTouchdowns ?? 0).toFixed(3),
      note: "his trailing rushing and receiving touchdown rates applied to his projected carries and targets",
    });
    steps.push({
      operator: "→",
      label: "Chance of at least one",
      value: `${(row.projectedValue * 100).toFixed(1)}%`,
      note: "the Poisson tail of that rate, which is what an anytime-touchdown market prices",
    });
    steps.push({
      operator: "−",
      label: "Market probability",
      value: `${(row.marketLine * 100).toFixed(1)}%`,
      note:
        `what ${row.book ?? "the book"} is pricing at ${formatOdds(row.overOdds)}. The posted ` +
        `0.5 line is not the market's opinion, only the market saying "at least one", so the ` +
        `price is the opinion`,
    });
    steps.push({
      operator: "=",
      label: "Edge",
      value: `${row.edge > 0 ? "+" : ""}${(row.edge * 100).toFixed(1)} pts`,
      total: true,
    });
    return {
      steps,
      confidence: confidenceNote(row),
      caveat:
        "No matchup or pace adjustment is applied here: neither was ever measured against a touchdown probability, only against yards.",
      warnings: [
        ...warnings(row),
        "The book's margin is left in its price, because an anytime-touchdown market has no" +
          " No side to de-vig against. That pushes this edge slightly negative, so a small" +
          " positive here is worth less than it looks.",
      ],
    };
  }

  const parts = productParts(row);
  if (!parts || parts.opportunityValue === null || parts.efficiencyValue === null) {
    return { steps, confidence: confidenceNote(row), warnings: warnings(row) };
  }

  steps.push({
    operator: "",
    label: parts.opportunityLabel,
    value: parts.opportunityValue.toFixed(2),
    note: parts.opportunityNote,
  });
  steps.push({
    operator: "×",
    label: parts.efficiencyLabel,
    value: parts.efficiencyIsRate
      ? `${(parts.efficiencyValue * 100).toFixed(1)}%`
      : parts.efficiencyValue.toFixed(2),
    note: parts.efficiencyNote,
  });
  steps.push({
    operator: "=",
    label: "Baseline projection",
    value: (row.baselineValue ?? 0).toFixed(1),
    note: "opportunity times efficiency, before any adjustment",
  });

  const matchup = row.matchupMultiplier ?? 1;
  const environment = row.environmentMultiplier ?? 1;
  steps.push({
    operator: "×",
    label: "Matchup",
    value: matchup.toFixed(3),
    note: matchupNote(row, matchup),
  });
  steps.push({
    operator: "×",
    label: "Environment",
    value: environment.toFixed(3),
    note: environmentNote(row, environment),
  });
  steps.push({
    operator: "=",
    label: "Projection",
    value: row.projectedValue.toFixed(1),
  });
  steps.push({
    operator: "−",
    label: "Market line",
    value: row.marketLine.toFixed(1),
    note: row.book ? marketLineNote(row.book, row.lineCapturedLater) : undefined,
  });
  steps.push({
    operator: "=",
    label: "Edge",
    value: `${row.edge > 0 ? "+" : ""}${row.edge.toFixed(1)}`,
    total: true,
  });

  return { steps, confidence: confidenceNote(row), warnings: warnings(row) };
}
