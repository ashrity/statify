"""Match each projection to its market line and calculate the edge.

No new table: projections' own migration comment already names this feature
as the one that fills in market_line, prop_line_id and edge, left NULL by
feature 20.

The match is temporal, not just by key. A projection generated Tuesday must
not be scored against a line not captured until Thursday, so the preferred
match is the latest prop_lines capture at or before the projection's own
generated_at, the strictly-prior instinct every earlier feature applies to
weeks, extended to a second clock: the order two independent processes
actually ran in.

That rule alone deadlocked against feature 20's content-based novelty. Books
post player props game by game as kickoff nears, so a capture usually lands
*after* the week's projections were generated; feature 20 then stores no new
projection row because no projected_value changed, leaving a newly captured
line with no row recent enough to see it. Measured on 2026 week 7: a capture
of 3,701 line rows matched 0 projections.

So a projection with no capture at or before it falls back to the earliest
capture *after* it. Two reasons that fallback is the earliest and not the
latest. It is the least future information that still produces a match, the
same instinct as preferring a strictly prior window. And it is stable: the
answer does not depend on when the command happened to run, where "the
latest" would keep moving as further captures arrived.

Already-matched rows are still never revisited, so this does not weaken the
guarantee it protects: a later capture cannot retroactively change what an
earlier projection was scored against. Whether a given row took the fallback
stays recoverable without a new column, by comparing the matched
prop_lines.captured_at against the projection's own generated_at.

What a projection is measured against depends on the stat type. Four of them
use the posted line. Touchdowns uses the probability implied by the book's
price, because the stored 0.5 "line" is not the market's opinion at all, only
the market saying "at least one"; see market_value.
"""

from __future__ import annotations

import sqlite3
from typing import NamedTuple

from statify.ingest.common import utc_now

PROJECTIONS_QUERY = """
SELECT id, player_id, week, stat_type, projected_value, generated_at
FROM projections
WHERE season = :season AND market_line IS NULL
"""

PROP_LINES_QUERY = """
SELECT id, player_id, week, stat_type, line, over_odds, captured_at
FROM prop_lines
WHERE season = :season
"""

EDGE_UPDATE = """
UPDATE projections
SET market_line = :market_line, prop_line_id = :prop_line_id, edge = :edge
WHERE id = :id
"""

# Repricing deliberately discards what a projection was scored against, which
# every other path in this command refuses to do. It is therefore scoped to
# games that have not kicked off: a line for a game already played is history,
# and rewriting it would also desynchronise backtest_results.beat_line, which
# is derived from market_line. A projection whose game cannot be resolved is
# left alone rather than guessed at.
REPRICE_SCOPE_QUERY = """
SELECT p.id
FROM projections p
JOIN player_matchup_environment_weekly me
  ON me.player_id = p.player_id AND me.season = p.season AND me.week = p.week
JOIN games g
  ON g.season = p.season AND g.week = p.week
 AND (g.home_team = me.team_abbr OR g.away_team = me.team_abbr)
WHERE p.season = :season AND p.market_line IS NOT NULL AND g.kickoff_at > :now
"""

# Must honour the same --week filter reprice_ids does, or left_alone subtracts
# a week-scoped clear from a season-wide total.
MATCHED_COUNT_QUERY = """
SELECT COUNT(*) FROM projections WHERE season = :season AND market_line IS NOT NULL
"""

# confidence is cleared with the edge it was derived from rather than left
# describing a line this row no longer points at. The command names
# compute confidence in its output so the gap is not silent.
REPRICE_CLEAR = """
UPDATE projections
SET market_line = NULL, prop_line_id = NULL, edge = NULL, confidence = NULL
WHERE id = :id
"""


def prop_lines_by_key(prop_lines: list[dict]) -> dict[tuple[str, int, str], list[dict]]:
    """Group prop_lines by (player, week, stat_type), each list sorted by
    (captured_at, id) so the latest-at-or-before search can walk it in order."""
    grouped: dict[tuple[str, int, str], list[dict]] = {}
    for row in prop_lines:
        key = (row["player_id"], row["week"], row["stat_type"])
        grouped.setdefault(key, []).append(row)
    for rows in grouped.values():
        rows.sort(key=lambda r: (r["captured_at"], r["id"]))
    return grouped


def latest_at_or_before(candidates: list[dict], generated_at: str) -> dict | None:
    """The candidate with the latest captured_at that is <= generated_at.

    candidates must already be sorted by (captured_at, id). A capture at the
    exact same instant as generation counts as available (<=, not <): the
    tie-break is id, the deterministic order candidates were sorted in.
    """
    match = None
    for candidate in candidates:
        if candidate["captured_at"] <= generated_at:
            match = candidate
        else:
            break
    return match


def american_to_probability(odds: int) -> float:
    """Implied probability from American odds. -200 is 0.6667, +150 is 0.40.

    The book's overround is left in. A two-way market could be de-vigged
    against its own other side, but anytime touchdown has no other side: books
    post no `No` price, so under_odds is NULL throughout. Rather than invent a
    vig constant, the figure stays as the book quotes it, which biases every
    touchdown edge slightly negative. Same discipline as the pipeline holding
    no weather coefficient: store what the source says, leave the modelling
    choice to a feature that measures it.
    """
    return -odds / (-odds + 100) if odds < 0 else 100 / (odds + 100)


def market_value(prop_line: dict, stat_type: str) -> float | None:
    """The number a projection is measured against, in the projection's units.

    For the four yardage and count stats that is the posted line. For
    touchdowns it is the probability implied by the book's price, not the 0.5
    line: a 0.5 line only encodes "at least one", so scoring a probability
    against it measures every player against a coin flip and flatters exactly
    the ones the book already prices as likely. Measured on 2026 week 7,
    Jahmyr Gibbs went from the board's best touchdown edge at +29.8 points
    against 0.5 to +3.6 against the -320 the book actually quoted.
    """
    if stat_type != "touchdowns":
        return prop_line["line"]
    odds = prop_line["over_odds"]
    if odds is None or odds == 0:
        return None
    return american_to_probability(odds)


def earliest_after(candidates: list[dict], generated_at: str) -> dict | None:
    """The candidate with the earliest captured_at strictly after generated_at.

    candidates must already be sorted by (captured_at, id). Used only when
    nothing was captured at or before generation, so there is no prior line
    to prefer.
    """
    for candidate in candidates:
        if candidate["captured_at"] > generated_at:
            return candidate
    return None


def edge_update(projection: dict, prop_line: dict) -> dict:
    market = market_value(prop_line, projection["stat_type"])
    return {
        "id": projection["id"],
        "market_line": market,
        "prop_line_id": prop_line["id"],
        "edge": projection["projected_value"] - market,
    }


def matched_pairs(
    projections: list[dict], prop_lines: list[dict]
) -> list[tuple[dict, dict, bool]]:
    """Each projection paired with the line it is scored against.

    The third element is True when the pair took the later-capture fallback,
    which the command reports so a run that leans on it is not silent.
    """
    grouped = prop_lines_by_key(prop_lines)
    pairs = []
    for projection in projections:
        key = (projection["player_id"], projection["week"], projection["stat_type"])
        candidates = [
            row
            for row in grouped.get(key, [])
            if market_value(row, projection["stat_type"]) is not None
        ]
        match = latest_at_or_before(candidates, projection["generated_at"])
        was_later = False
        if match is None:
            match = earliest_after(candidates, projection["generated_at"])
            was_later = match is not None
        if match is None:
            continue
        pairs.append((projection, match, was_later))
    return pairs


def edge_updates(projections: list[dict], prop_lines: list[dict]) -> list[dict]:
    return [edge_update(p, line) for p, line, _ in matched_pairs(projections, prop_lines)]


class EdgeResult(NamedTuple):
    matched: int
    later: int
    """Matched against a capture after the projection was generated."""
    cleared: int
    """Repriced: a previous match discarded so a newer line could be taken."""
    left_alone: int
    """Already matched and not repriced, because the game has kicked off."""


def reprice_ids(
    conn: sqlite3.Connection, season: int, now: str, week: int | None = None
) -> list[int]:
    """Already-matched projections whose game has not kicked off yet."""
    query = REPRICE_SCOPE_QUERY
    params: dict = {"season": season, "now": now}
    if week is not None:
        query += " AND p.week = :week"
        params["week"] = week
    return [row[0] for row in conn.execute(query, params).fetchall()]


def load_edges(
    conn: sqlite3.Connection,
    season: int,
    week: int | None = None,
    reprice: bool = False,
) -> EdgeResult:
    projections_count = conn.execute(
        "SELECT COUNT(*) FROM projections WHERE season = ?", (season,)
    ).fetchone()[0]
    if projections_count == 0:
        raise RuntimeError(
            f"no projections for {season}. Run: statify compute generate-projections --season {season}"
        )

    cleared = 0
    left_alone = 0
    if reprice:
        count_query = MATCHED_COUNT_QUERY
        count_params: dict = {"season": season}
        if week is not None:
            count_query += " AND week = :week"
            count_params["week"] = week
        matched_before = conn.execute(count_query, count_params).fetchone()[0]
        ids = reprice_ids(conn, season, utc_now(), week)
        if ids:
            conn.execute("BEGIN")
            try:
                conn.executemany(REPRICE_CLEAR, [{"id": i} for i in ids])
                conn.execute("COMMIT")
            except sqlite3.Error:
                conn.execute("ROLLBACK")
                raise
        cleared = len(ids)
        left_alone = matched_before - cleared

    query = PROJECTIONS_QUERY
    params: dict = {"season": season}
    if week is not None:
        query += " AND week = :week"
        params["week"] = week
    projections = [dict(row) for row in conn.execute(query, params).fetchall()]

    prop_lines = [dict(row) for row in conn.execute(PROP_LINES_QUERY, {"season": season}).fetchall()]

    pairs = matched_pairs(projections, prop_lines)
    updates = [edge_update(p, line) for p, line, _ in pairs]
    later = sum(1 for _, _, was_later in pairs if was_later)
    if updates:
        conn.execute("BEGIN")
        try:
            conn.executemany(EDGE_UPDATE, updates)
            conn.execute("COMMIT")
        except sqlite3.Error:
            conn.execute("ROLLBACK")
            raise
    return EdgeResult(len(updates), later, cleared, left_alone)
