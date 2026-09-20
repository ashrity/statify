"""Command line entry point for the pipeline."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from statify import migrate as migrations
from statify.config import settings
from statify.db import connection
from statify.ingest.common import utc_now, write
from statify.ingest import (
    defense,
    depth,
    efficiency,
    form,
    injuries,
    ngs,
    props,
    reference,
    routes,
    snaps,
    tempo,
    usage,
    weather,
    weekly,
)


def _cmd_migrate(_args: argparse.Namespace) -> int:
    with connection() as conn:
        applied = migrations.migrate(conn)

    noun = "migration" if len(applied) == 1 else "migrations"
    print(f"{len(applied)} {noun} applied")
    for version in applied:
        print(f"  {version}")
    return 0


def _cmd_ingest_teams(_args: argparse.Namespace) -> int:
    with connection() as conn:
        upserted, skipped = reference.load_teams(conn)

    print(f"{upserted} teams upserted ({skipped} historical abbreviations skipped)")
    return 0


def _cmd_ingest_games(args: argparse.Namespace) -> int:
    with connection() as conn:
        upserted, skipped = reference.load_games(conn, args.season)

    print(f"{upserted} games upserted ({skipped} without a kickoff time skipped)")
    return 0


def _cmd_ingest_players(args: argparse.Namespace) -> int:
    with connection() as conn:
        written, no_id, kept_newer = reference.load_players(conn, args.season)
        pfr_updated, pfr_missing = reference.load_player_ids(conn)

    print(f"{written} skill-position players written ({no_id} without a GSIS id skipped)")
    if kept_newer:
        print(f"{kept_newer} left alone, already carrying a roster season newer than {args.season}")
    print(f"{pfr_updated} pfr ids set ({pfr_missing} players still without one)")
    return 0


def _cmd_ingest_weekly(args: argparse.Namespace) -> int:
    with connection() as conn:
        upserted, skipped = weekly.load_weekly_actuals(conn, args.season, args.week)

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{upserted} weekly actuals upserted for {args.season} {scope}")
    print(f"{skipped} rows skipped (player not in the players table)")
    return 0


def _cmd_ingest_redzone(args: argparse.Namespace) -> int:
    with connection() as conn:
        games, updated, unmatched = weekly.load_red_zone_touches(conn, args.season, args.week)

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{games} games scanned for {args.season} {scope}")
    print(f"{updated} players given red zone touches (others set to 0)")
    print(f"{unmatched} player/game pairs with no weekly_actuals row (non-skill players)")
    return 0


def _cmd_ingest_ngs(args: argparse.Namespace) -> int:
    feeds = {
        "receiving": ngs.load_receiving,
        "passing": ngs.load_passing,
        "rushing": ngs.load_rushing,
    }
    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"Next Gen Stats for {args.season} {scope}")

    with connection() as conn:
        for name, load in feeds.items():
            upserted, skipped = load(conn, args.season, args.week)
            print(f"  {name:<10} {upserted:>5} upserted ({skipped} skipped)")
    return 0


def _cmd_ingest_snaps(args: argparse.Namespace) -> int:
    with connection() as conn:
        updated, inserted, unresolved, st_only = snaps.load_snap_counts(
            conn, args.season, args.week
        )

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{updated} weekly_actuals rows given snap counts for {args.season} {scope}")
    print(f"{inserted} rows inserted for players who played but recorded no stat")
    print(f"{st_only} skipped as special teams only (no offensive snaps)")
    print(f"{unresolved} snap rows unresolved (player not in the players table)")
    return 0


def _cmd_ingest_depth(args: argparse.Namespace) -> int:
    with connection() as conn:
        upserted, skipped = depth.load_depth_charts(conn, args.season, args.week)

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{upserted} depth chart rows upserted for {args.season} {scope}")
    print(f"{skipped} rows skipped (no week, no rank, or player not in the players table)")
    return 0


def _cmd_ingest_injuries(args: argparse.Namespace) -> int:
    with connection() as conn:
        upserted, skipped = injuries.load_injuries(conn, args.season, args.week)

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{upserted} injury rows upserted for {args.season} {scope}")
    print(f"{skipped} rows skipped (player not in the players table)")
    return 0


def _cmd_ingest_weather(args: argparse.Namespace) -> int:
    with connection() as conn:
        upserted, indoor, no_reading = weather.load_weather(conn, args.season)

    print(f"{upserted} games given weather for {args.season}")
    print(f"{indoor} indoor games skipped (weather does not apply)")
    print(f"{no_reading} outdoor games with no upstream reading")
    return 0


def _cmd_props_audit(args: argparse.Namespace) -> int:
    """Report how well the odds feed's identities resolve. Writes nothing."""
    from statify.sources import odds_api

    with connection() as conn:
        team_abbrs, games, player_index = props.load_reference(conn, args.season)

    events, remaining = odds_api.events()
    slate = []
    unresolved_events = []
    for event in events:
        resolved = props.resolve_event(event, team_abbrs, games)
        if resolved is None:
            unresolved_events.append(f"{event.get('away_team')} @ {event.get('home_team')}")
        elif resolved[2] == args.week:
            slate.append((event, resolved))

    markets = sorted(props.MARKET_STAT_TYPES)
    print(f"season {args.season} week {args.week}")
    print(f"  {len(slate)} of {len(events)} events resolved to a game for this week")
    print(f"  {len(unresolved_events)} events could not be resolved at all")
    print(f"  cost: {len(slate)} events x {len(markets)} markets = {len(slate) * len(markets)} credits")
    print(f"  credits remaining before: {remaining}")
    if args.dry_run:
        print("  dry run, nothing fetched")
        return 0

    names: list[str] = []
    with_lines = 0
    for event, _ in slate:
        payload, remaining = odds_api.event_odds(event["id"], markets)
        found = props.outcome_names(payload)
        # Books post props game by game as kickoff nears, so a slate pulled early
        # is partly empty. Without this the match rate looks like full coverage.
        if found:
            with_lines += 1
        names.extend(found)

    matched, unmatched, ambiguous = props.resolve_players(names, player_index)
    distinct = len(set(names))
    print()
    print(f"  {with_lines} of {len(slate)} events had lines posted")
    print(f"  {distinct} distinct player names in the slate")
    print(f"  {len(matched)} matched, {len(unmatched)} unmatched, {len(ambiguous)} ambiguous")
    if distinct:
        print(f"  match rate: {100 * len(matched) / distinct:.1f}%")
    print(f"  credits remaining after: {remaining}")
    if ambiguous:
        print()
        print("  AMBIGUOUS (refused, would be stored as nothing):")
        for name in ambiguous:
            print(f"    {name}")
    if unmatched:
        print()
        print("  UNMATCHED:")
        for name in unmatched:
            print(f"    {name}")
    return 0


def _cmd_ingest_props(args: argparse.Namespace) -> int:
    from statify.sources import odds_api

    with connection() as conn:
        team_abbrs, games, _ = props.load_reference(conn, args.season)

    events, remaining = odds_api.events()
    slate = [
        (event, resolved)
        for event in events
        if (resolved := props.resolve_event(event, team_abbrs, games)) is not None
        and resolved[2] == args.week
    ]
    markets = sorted(props.MARKET_STAT_TYPES)
    estimate = props.estimate_credits(len(slate), len(markets))

    print(f"season {args.season} week {args.week}")
    print(f"  {len(slate)} events x {len(markets)} markets = {estimate} credits")
    print(f"  {remaining} credits remaining, floor {props.CREDIT_FLOOR}")

    if args.dry_run:
        print("  dry run, nothing fetched and nothing written")
        return 0

    props.assert_within_budget(estimate, remaining)

    with connection() as conn:
        _, _, player_index = props.load_reference(conn, args.season)
        latest = props.latest_stored(conn, args.season, args.week)
        captured_at = utc_now()
        rows: list[dict] = []
        all_names: list[str] = []
        with_lines = 0

        for event, (game_id, season, week) in slate:
            payload, remaining = odds_api.event_odds(event["id"], markets)
            names = props.outcome_names(payload)
            if names:
                with_lines += 1
            all_names.extend(names)
            matched, _, _ = props.resolve_players(names, player_index)
            rows.extend(props.prop_rows(payload, game_id, season, week, matched, captured_at))

        _, unmatched, ambiguous = props.resolve_players(all_names, player_index)
        moved = [row for row in rows if props.is_new_capture(row, latest)]
        write(conn, props.PROP_UPSERT, moved)

    print(f"  {with_lines} of {len(slate)} events had lines posted")
    print(f"  {len(rows)} lines offered, {len(moved)} written ({len(rows) - len(moved)} unchanged since the last capture)")
    print(f"  {len(unmatched)} unmatched and {len(ambiguous)} ambiguous names, stored as nothing")
    print(f"  {remaining} credits remaining")
    for label, names in (("UNMATCHED", unmatched), ("AMBIGUOUS", ambiguous)):
        if names:
            print()
            print(f"  {label}:")
            for name in names:
                print(f"    {name}")
    return 0


def _cmd_compute_defense(args: argparse.Namespace) -> int:
    with connection() as conn:
        rows, excluded = defense.load_team_defense(conn, args.season, args.week)

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{rows} team/week/position rows for {args.season} {scope}")
    total = sum(excluded.values())
    print(f"{total} plays excluded, with no position to attribute them to:")
    for reason, count in excluded.most_common():
        print(f"  {count:>6}  {reason}")
    return 0


def _cmd_compute_tempo(args: argparse.Namespace) -> int:
    with connection() as conn:
        rows, without_neutral = tempo.load_team_tempo(conn, args.season, args.week)

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{rows} team/week tempo rows for {args.season} {scope}")
    print(f"{without_neutral} rows have no situation-neutral snaps (pace stored as NULL)")
    return 0


def _cmd_compute_usage(args: argparse.Namespace) -> int:
    with connection() as conn:
        rows, no_air_yards = usage.load_usage(conn, args.season, args.week)

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{rows} usage rows for {args.season} {scope}")
    if no_air_yards:
        print(f"{no_air_yards} rows in games with no charted air yards (shares stored as NULL)")
    return 0


def _cmd_compute_efficiency(args: argparse.Namespace) -> int:
    with connection() as conn:
        rows, no_routes = efficiency.load_efficiency(conn, args.season, args.week)

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{rows} efficiency rows for {args.season} {scope}")
    if no_routes:
        print(f"{no_routes} rows have no route count (yprr stored as NULL)")
    return 0


def _cmd_compute_form(args: argparse.Namespace) -> int:
    with connection() as conn:
        counts = form.load_form(conn, args.season)

    print(f"{counts.rows} form rows for {args.season}")
    print(f"{counts.no_history} are a player's first game, with no prior form")
    if counts.efficiency_rows == 0:
        print(
            f"no efficiency rows for {args.season}, so catch rate and YAC over "
            f"expected are NULL on every row. Run: statify compute efficiency "
            f"--season {args.season}"
        )
    else:
        print(f"{counts.with_over_expected} carry catch rate over expected")
    return 0


def _cmd_ingest_routes(args: argparse.Namespace) -> int:
    with connection() as conn:
        updated, players, missing = routes.load_routes(conn, args.season, args.week)

    scope = f"week {args.week}" if args.week is not None else "full season"
    print(f"{updated} weekly_actuals rows given routes for {args.season} {scope}")
    print(f"{players} players ran at least one route")
    if missing:
        print(f"{missing} player/game pairs had routes but no weekly_actuals row")
    return 0


def _format_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024 or unit == "GB":
            return f"{num_bytes:.0f} {unit}" if unit == "B" else f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} GB"


def _cmd_status(_args: argparse.Namespace) -> int:
    path = settings.db_path
    print(f"database   {path}")
    if not path.exists():
        print("           not created yet - run: statify migrate")
        return 1

    print(f"size       {_format_size(path.stat().st_size)}")

    with connection() as conn:
        applied = conn.execute(
            "SELECT version, applied_at FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
        print(f"migration  {applied['version']} (applied {applied['applied_at']})" if applied else "migration  none applied")

        # Read the table list from the schema rather than hardcoding it, so later
        # features show up here without touching this command.
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name != 'schema_migrations' "
                "ORDER BY name"
            )
        ]
        if not tables:
            print()
            print("no data tables yet")
            return 0

        print()
        width = max(len(name) for name in tables)
        for name in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            print(f"{name:<{width}}  {count:>7,}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="statify", description="Statify data pipeline")
    subcommands = parser.add_subparsers(dest="command", required=True)

    migrate_cmd = subcommands.add_parser("migrate", help="apply pending schema migrations")
    migrate_cmd.set_defaults(func=_cmd_migrate)

    ingest_cmd = subcommands.add_parser("ingest", help="pull reference data from nflverse")
    datasets = ingest_cmd.add_subparsers(dest="dataset", required=True)

    teams_cmd = datasets.add_parser("teams", help="load the active NFL teams")
    teams_cmd.set_defaults(func=_cmd_ingest_teams)

    games_cmd = datasets.add_parser("games", help="load one season's schedule")
    games_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2025")
    games_cmd.set_defaults(func=_cmd_ingest_games)

    players_cmd = datasets.add_parser("players", help="load one season's skill-position players")
    players_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2025")
    players_cmd.set_defaults(func=_cmd_ingest_players)

    weekly_cmd = datasets.add_parser("weekly", help="load one season's weekly box-score actuals")
    weekly_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2025")
    weekly_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    weekly_cmd.set_defaults(func=_cmd_ingest_weekly)

    redzone_cmd = datasets.add_parser("redzone", help="fill red zone touches from play-by-play")
    redzone_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2025")
    redzone_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    redzone_cmd.set_defaults(func=_cmd_ingest_redzone)

    ngs_cmd = datasets.add_parser("ngs", help="load one season's Next Gen Stats")
    ngs_cmd.add_argument("--season", type=int, required=True, help="season year, 2016 or later")
    ngs_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    ngs_cmd.set_defaults(func=_cmd_ingest_ngs)

    snaps_cmd = datasets.add_parser("snaps", help="fill snaps and snap share from snap counts")
    snaps_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2025")
    snaps_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    snaps_cmd.set_defaults(func=_cmd_ingest_snaps)

    depth_cmd = datasets.add_parser("depth", help="load one season's offensive depth charts")
    depth_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2025")
    depth_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    depth_cmd.set_defaults(func=_cmd_ingest_depth)

    injuries_cmd = datasets.add_parser("injuries", help="load one season's injury reports")
    injuries_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2025")
    injuries_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    injuries_cmd.set_defaults(func=_cmd_ingest_injuries)

    weather_cmd = datasets.add_parser("weather", help="load one season's per-game weather")
    weather_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2025")
    weather_cmd.set_defaults(func=_cmd_ingest_weather)

    props_cmd = subcommands.add_parser("props", help="player prop lines from The Odds API")
    props_sub = props_cmd.add_subparsers(dest="action", required=True)
    audit_cmd = props_sub.add_parser("audit", help="report identity match rates without storing")
    audit_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2026")
    audit_cmd.add_argument("--week", type=int, required=True, help="week to audit")
    audit_cmd.add_argument("--dry-run", action="store_true", help="show cost and exit")
    audit_cmd.set_defaults(func=_cmd_props_audit)

    props_ingest_cmd = datasets.add_parser("props", help="load player prop lines from The Odds API")
    props_ingest_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2026")
    props_ingest_cmd.add_argument("--week", type=int, required=True, help="week to capture")
    props_ingest_cmd.add_argument("--dry-run", action="store_true", help="show cost and exit without spending")
    props_ingest_cmd.set_defaults(func=_cmd_ingest_props)

    compute_cmd = subcommands.add_parser("compute", help="derive metrics from data already stored")
    computations = compute_cmd.add_subparsers(dest="computation", required=True)

    defense_cmd = computations.add_parser("defense", help="team defense splits by position faced")
    defense_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2024")
    defense_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    defense_cmd.set_defaults(func=_cmd_compute_defense)

    tempo_cmd = computations.add_parser("tempo", help="offensive pace and pass rate over expected")
    tempo_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2024")
    tempo_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    tempo_cmd.set_defaults(func=_cmd_compute_tempo)

    usage_cmd = computations.add_parser("usage", help="player share of team opportunity")
    usage_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2024")
    usage_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    usage_cmd.set_defaults(func=_cmd_compute_usage)

    efficiency_cmd = computations.add_parser("efficiency", help="player output per opportunity")
    efficiency_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2024")
    efficiency_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    efficiency_cmd.set_defaults(func=_cmd_compute_efficiency)

    form_cmd = computations.add_parser("form", help="trailing usage form entering each week")
    form_cmd.add_argument("--season", type=int, required=True, help="season year, e.g. 2024")
    form_cmd.set_defaults(func=_cmd_compute_form)

    routes_cmd = datasets.add_parser("routes", help="count routes run from participation data")
    routes_cmd.add_argument("--season", type=int, required=True, help="season year, 2016 or later")
    routes_cmd.add_argument("--week", type=int, help="limit to one week; omit for the whole season")
    routes_cmd.set_defaults(func=_cmd_ingest_routes)

    status_cmd = subcommands.add_parser("status", help="show database location and row counts")
    status_cmd.set_defaults(func=_cmd_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
