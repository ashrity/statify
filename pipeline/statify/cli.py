"""Command line entry point for the pipeline."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from statify import migrate as migrations
from statify.config import settings
from statify.db import connection
from statify.ingest import depth, injuries, ngs, reference, snaps, weekly


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

    status_cmd = subcommands.add_parser("status", help="show database location and row counts")
    status_cmd.set_defaults(func=_cmd_status)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
