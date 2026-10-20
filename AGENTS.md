# AGENTS.md

Instructions for AI coding agents working in this project. This is the cross-tool
entry point: Codex, OpenCode, Cursor, GitHub Copilot, Gemini CLI, Aider, Zed,
Windsurf, and others read `AGENTS.md`.

## What this is

Statify.

> TODO: describe the project and the problem it solves.

## Stack

| Area | Choice |
| --- | --- |
| Framework | Next.js 16 (App Router) |
| Language | TypeScript 5, strict mode (app); Python 3.12+ (`pipeline/`) |
| UI | React 19 |
| Styling | Tailwind CSS v4 (CSS-first config in `app/globals.css`) |
| Lint | ESLint 9 flat config (`eslint.config.mjs`), `eslint-config-next` |
| Package manager | npm (`package-lock.json`) for the app, `uv` for `pipeline/` |
| Database | SQLite at `data/statify.db`, numbered SQL migrations in `pipeline/migrations/` |
| Auth | > TODO: none installed yet |
| Tests | pytest, in `pipeline/` only. The Next.js app has no runner. |

## Commands

App:

- Dev server: `npm run dev` (http://localhost:3000)
- Build: `npm run build`
- Production server: `npm run start`
- Lint: `npm run lint`

Data pipeline, all run from `pipeline/`:

- Apply schema migrations: `uv run statify migrate`
- Database location and row counts: `uv run statify status`
- Reference data: `uv run statify ingest teams`, `... ingest games --season <year>`,
  `... ingest players --season <year>`
- Weekly box-score actuals: `uv run statify ingest weekly --season <year> [--week <n>]`
- Red zone touches from play-by-play: `uv run statify ingest redzone --season <year> [--week <n>]`
- Next Gen Stats: `uv run statify ingest ngs --season <year> [--week <n>]` (2016 or later)
- Snap counts: `uv run statify ingest snaps --season <year> [--week <n>]`
- Depth charts: `uv run statify ingest depth --season <year> [--week <n>]`
- Injury reports: `uv run statify ingest injuries --season <year> [--week <n>]`
- Routes run: `uv run statify ingest routes --season <year> [--week <n>]` (2016 or later)
- Weather, settled readings for played games: `uv run statify ingest weather --season <year>`
- Stadium coordinates, once: `uv run statify ingest stadiums`
- Weather forecasts for upcoming games: `uv run statify ingest forecast --season <year> [--week <n>] [--dry-run]`
- Player prop lines: `uv run statify ingest props --season <year> --week <n> [--dry-run]`
- Prop identity audit: `uv run statify props audit --season <year> --week <n> [--dry-run]`
- Mark closing lines: `uv run statify props close --season <year> --week <n>`
- Team spreads and totals: `uv run statify ingest market --season <year> [--week <n>] [--dry-run]`
- Tests: `uv run pytest`

Ingest order matters: teams, then games and players for a season, then weekly,
redzone, ngs, snaps, depth, injuries, and weather. Prop lines need only teams,
games and players for the season. Each loader updates only the columns it owns, so
re-running one never wipes another's work.

`ingest snaps` also inserts rows for players who took offensive snaps but
recorded no stat, so run `ingest redzone` after it to fill their red zone
touches.

Three commands need `ODDS_API_KEY` in `.env` (gitignored) and spend metered
credits from The Odds API, but **they do not cost remotely the same**, because
two different endpoints are involved:

| Command | Endpoint | Measured cost |
| --- | --- | --- |
| `ingest props`, `props audit` | per event | markets times events, up to about **80 a week** |
| `ingest market` | bulk | **2**, for the whole slate |

Player props are not served by the bulk endpoint, which is the only reason
feature 7a pays per game. Team markets are, and the bulk price is one credit per
market however many games come back, so `ingest market --week 7` costs exactly
what omitting `--week` costs: **`--week` narrows what is stored, never what is
fetched**. Do not carry the props mental model across.

`ingest props` covers **five** markets: the four over/under lines plus
**anytime touchdown**, which is binary. That market quotes a price on the event
happening rather than a number to beat, so its outcomes carry no `point` at
all; a `Yes` price is stored as `over_odds` against a `line` of **0.5**, which
is literally what "anytime" means, and `under_odds` stays NULL because books
post no `No` side. Measured on 2026 week 7: 110 rows, 6 books, odds from -200
to +1100.

**The credit estimate is an upper bound, not a prediction.** Cost is markets
times events only when every event has lines posted. A week 7 slate estimated
at 70 cost **21** three days out, because books post player props game by game
as kickoff nears and only 2 of 14 events had any. Capturing early is cheap and
incomplete; capturing near kickoff costs the full amount and gets everything.

`props close` marks `is_closing` on the last capture before kickoff, per player,
stat type and book. It writes no new rows, makes no request and spends nothing.
**It only marks games that have already kicked off**, because which capture
closed a line is unknowable while a later one may still arrive, and it clears
and re-sets in one transaction so a line that moved late cannot leave two rows
marked. Feature 28 measures against these rows and nothing else.

Against a 500 a month free tier that makes one props capture per week the
binding constraint, while market captures are effectively free. All three take
`--dry-run` to print the slate and the estimate while spending nothing; props
additionally refuses to run below a 50-credit floor, which `ingest market` has
no need of. Historical odds are not available on the free tier, which blocks
features 27 and 28.

`ingest market` stores a row per game, team and book, so two rows per game carry
the same spread from opposite signs plus `implied_team_total`, which is
`game_total / 2 - spread / 2` and always sums back to the total across the pair.
Re-running decides novelty by **content**: a line that has not moved is not
stored again, because `captured_at` differs on every run and would otherwise
record the same slate twice. That is the mistake feature 7a made with 433 rows,
and a first version of this loader repeated it by doubling a 240-row slate.

Feeds disagree on team abbreviations (Next Gen Stats says `LAR` where the rest say
`LA`). Inbound rows go through `normalize_team()` in `statify/ingest/common.py`;
add aliases there, not per-loader.

Computed metrics, derived from data already stored rather than fetched:

- Team defense by position and play type: `uv run statify compute defense --season <year> [--week <n>]`
- Defensive matchup factors: `uv run statify compute matchup --season <year>`
- Defensive tendencies: `uv run statify compute tendencies --season <year>` (2016 to 2025)
- Game environment: `uv run statify compute environment --season <year>`
- Offensive pace and PROE: `uv run statify compute tempo --season <year> [--week <n>]`
- Player usage shares: `uv run statify compute usage --season <year> [--week <n>]`
- Player efficiency: `uv run statify compute efficiency --season <year> [--week <n>]`
- Trailing form: `uv run statify compute form --season <year>`
- Expected team volume: `uv run statify compute volume --season <year> [--week <n>]`
- Expected player opportunity: `uv run statify compute opportunity --season <year> [--week <n>]`
- Expected player efficiency: `uv run statify compute expected-efficiency --season <year> [--week <n>]`

`compute form` writes both the trailing windows (last 3, last 5, season to date)
and their exponentially weighted counterparts in one pass, so the two halves of
a row cannot disagree. The half-life is stored on every row rather than only in
the code. It covers usage and efficiency together, for the same reason: one row
is what was known entering that week, and two tables could disagree about what
"last 3 games" means.

**Rush yards over expected is measured only in a 10-carry game.** Next Gen Stats
publishes nothing below that, and measured on 2024 it is a hard threshold rather
than sparse sampling: 554 of 554 back-weeks at 10 or more carries have it, 0 of
819 below. So a back's trailing figure is built from his heavy-workload games
only. `games_std` does not say that, which is why `player_form_weekly` carries
`ryoe_games_l3`, `ryoe_games_l5` and `ryoe_games_std`: **read the sample count
before trusting the rate.** Entering week 17 of 2024 the league leader at 3.951
had one measured game against Derrick Henry's fifteen at 1.772, and every other
column on the two rows looked alike. Migrations 017 and 018 carry the same
warning.

`ryoe_per_att` also divides by NGS's own attempt count, recovered as `ryoe` over
`ryoe_per_att`, not by our `carries`. The two disagree on a quarter of rows.

**Routes are an approximation.** No free source publishes per-player route
counts, so `ingest routes` counts players on the field for a dropback. A player
who stayed in to block is counted too, and the error is uneven: measured on
2024, targets per route lands at 0.197 for receivers against a real figure near
0.20, but 0.151 for backs against a real figure near 0.20. Running back routes
are over-counted by roughly a quarter, so yards per route run for a back reads
about that much low. Migrations 015 and 016 carry the same warning. This lands on
`player_efficiency_weekly.yprr`: treat a receiver's figure as sound (measured on
2024, Nacua 3.21 and Collins 2.86 against published figures within about 0.1) and
a back's as a floor rather than an estimate.

`compute efficiency` stores its own `yacoe`, which is **not** the Next Gen Stats
figure of the same name in `next_gen_stats`. NGS builds it from player tracking;
this is the nflverse expected-YAC model in play-by-play. Measured over 1,302
receiver weeks they differ by a mean of 0.95 yards and agree within a yard only
30% of the time. Both are real. The play-by-play one is computed because NGS
publishes nothing at all for running back receiving, and because it stores its
own denominator so it can be weighted by volume across weeks.

**Migration 019 emptied `team_defense_weekly`.** It added a `play_type` column
to the primary key and no honest value could be invented for the existing rows,
so they were dropped. Everything in that table is derived from play-by-play:
`uv run statify compute defense --season <year>` puts it back. `compute matchup`
refuses to run until it has.

`compute defense` now splits a back's carries from his catches, and **counts
sacks as `(QB, pass)`** rather than discarding them as having no receiver. A
sack is the best outcome a pass rush produces, so excluding it understated
exactly the defenses the table exists to identify, and including it makes every
`play_type = 'pass'` row for a team-week add up to a complete dropback. That
bucket is mostly but not purely sacks: 2024 put 1,428 plays there against 1,392
sacks, the rest being passes a quarterback caught, 31 of them Taysom Hill.

`compute matchup` turns that table into the number feature 18 multiplies by: a
defense's trailing EPA allowed minus the league's over the same weeks. **Negative
is always a better defense**, for every position and play type. A difference
rather than a ratio, because EPA per play crosses zero. It emits a row for every
bucket the season contains for every week a defense played, not only the buckets
that came up that week, so a factor can always be looked up; a defense that has
never faced a bucket gets a row with NULLs rather than no row at all.

`compute tendencies` is the other half of the matchup and the only `compute`
that ranks nobody. It stores what a defense *does*: man rate, blitz rate, pass
rushers per snap, sack rate and QB hit rate, per week and over the last 3, last
5 and season to date. A man-heavy defense is not a worse defense, so there is no
league baseline here, unlike `compute matchup`. It reads nflverse directly
rather than a stored table, so it depends on no other command.

**This `man_rate` is not comparable to a published one.** Measured on 2024 the
league figure here is 48.5%, where Next Gen Stats and PFF both report nearer 30
to 35%: they chart to different definitions, the same situation as `yacoe`. Only
compare a man rate from this table to another from this table. What survives the
gap is the ordering, and the ordering is right: Minnesota tops blitz rate at
40.0%, Green Bay is the league's most zone-heavy at 32.1% man, and Denver leads
both man coverage at 61.1% and sacks at 8.8%.

Its three rates use three different denominators, because the feeds cover
different plays: man over `coverage_snaps`, blitz and rushers over
`rusher_snaps`, sacks and hits over `dropbacks`. They fail independently too.
Four team-weeks in 2024, all in week 7, have full coverage charting and no
pass-rusher counts at all; those rows keep their man and sack rates and carry
NULL only in the blitz columns. `coverage_snaps` is also the sample size and
runs from 14 to 63 across a team-week, so read it before trusting a single
week's rate.

**`weather` and `game_forecast` are different facts and must not be confused.**
`ingest weather` records the settled game-time condition after a game is played;
`ingest forecast` records what was expected beforehand. Migration 008 warns that
projecting a game with its own game-time wind leaks the result of the game being
projected, which is the failure features 11a, 13a and 14a carry direct tests
against. `compute environment` reads the forecast, never the reading.

`ingest forecast` uses Open-Meteo: free, no key, no account. Its window has two
edges and the command reports both: a game **beyond 16 days** has no forecast
yet, and a game **already played** never will, because the provider's series
starts today and its archive returns actuals, which `weather` already holds. One
request per stadium rather than per game, and novelty is decided by **content**,
so a re-run stores nothing when the weather has not moved.

Stadium coordinates come from `ingest stadiums`, which geocodes a maintained
`STADIUM_PLACES` map once into the `stadiums` table. **Place names, never
hand-typed coordinates**: nothing in nflverse publishes a latitude, Open-Meteo
resolves places but not venues, and the failure modes differ. A wrong place name
returns nothing or the wrong country and is visible; a wrong coordinate silently
returns the weather somewhere else. Measured: taking the geocoder's top hit puts
Levi's Stadium in Cuba and the Stade de France on Reunion, so the map carries a
country and, for every US entry, a state. **An unknown stadium is named in the
output, never skipped**, because the league adds venues most years; 40 are
covered across 2024 to 2026 and `GER00` and `MUN01` are the same Munich ground.

No weather coefficient lives anywhere in the pipeline. How much a 20mph wind
should cost a passing projection is feature 18's modelling choice; these
commands store conditions only.

`compute environment` is the market and pace half of the matchup, one row per
team per game. It needs `ingest market` and `compute tempo` to have run for the
season, and it is **driven by `games`, not by the market**: every game gets a
row and the market columns are NULL where no line was captured. Past weeks can
never have one, because historical odds are a paid tier, and feature 23's
backtest still wants their pace half. Measured on 2026: 544 rows, of which 28
carry a line (week 7, the only week captured) and 512 carry trailing pace (all
but week 1).

Its market columns are a **consensus**, the median across books at each book's
latest capture, not one row per book. The implied total is derived from the
consensus spread and total rather than taken as a third median, because three
independent medians over disagreeing books need not satisfy
`total / 2 - spread / 2`. A median also ignores a single stale book where a mean
would not. `books` records how many the consensus came from, and it is not
always nine: one 2026 week 7 game had eight.

Pace and PROE are trailing, strictly prior, and **volume-weighted rather than a
mean of weekly rates**. Baltimore's neutral-snap counts across six 2026 weeks
run from 7 to 37, so a mean would let a blowout weigh as much as a full game.
`pace_weeks` and `proe_weeks` record the sample behind each.

**There is no weather in `compute environment`, deliberately.** Migration 008
records that the stored reading is the settled game-time condition rather than a
pre-kickoff forecast, and using it as a projection input would leak the result
of the game being projected. Feature 14b adds a forecast source first; migration
023 repeats the warning.

**2026 cannot have routes or defensive tendencies.** nflverse participation data
stops at 2025, so for 2026 `ingest routes` fails outright, every `yprr` is NULL,
and `compute tendencies` has no input. `ingest depth` and `ingest injuries` also
fail on 2026 while still working on 2024: the current-season feeds have a
different column set. None of that is repaired yet.

`compute usage` reads `weekly_actuals`, so re-run it after anything that writes
that table: `ingest weekly`, `ingest snaps`, `ingest redzone`, or `ingest
routes`. `compute efficiency` then reads `weekly_actuals` and takes `routes` from
`player_usage_weekly`, and `compute form` reads all three, so the order is
weekly, redzone and snaps, then usage, then efficiency, then form. Each is stale
until the one before it has run. `compute matchup` sits on its own chain of two:
`compute defense` first, then `compute matchup`. It takes no `--week`, for the
same reason `compute form` does not.

The two commands disagree on what to do about a missing prerequisite, on
purpose. `compute efficiency` refuses to run at all when the season has weekly
actuals but no usage rows, rather than filling every `yprr` with NULL and
reporting success. `compute form` only warns, naming the command to run, because
it predates this dependency and ten of its twelve efficiency rates read
`weekly_actuals` directly: without `compute efficiency` it loses catch rate over
expected and YAC over expected and nothing else.

`compute form` takes no `--week`: a week's form is built from every earlier week,
so the season is the unit.

`compute volume` is the first command that predicts rather than records. It
reads `weekly_actuals` and `games` only, so it needs no feature table and sits
outside the usage/efficiency/form chain.

**Its rows follow the schedule, not the results.** The row worth having is for
the week nobody has played yet, so an unplayed week gets an expectation built
from everything before it. Re-run it after each week to refresh the later ones.
A team on a bye has no game and so has no row, which is why 2024 has 570 rows
rather than 32 times 22.

**Week 1 is entirely NULL and that is the answer, not a bug.** Nobody has
played, so there is no team rate and no league rate either. Feature 30's
cross-season shrinkage is what would fill it.

**Passing volume and rushing volume want opposite treatment**, which is the
measurement the table exists to encode. On 2024 weeks 6 to 18, mean absolute
error per team-week:

| | own last 3 | own season | league mean | shipped |
| --- | --- | --- | --- | --- |
| targets | 6.186 | 5.913 | 5.720 | **5.667** |
| pass attempts | 6.502 | 6.177 | 5.949 | **5.890** |
| carries | 6.267 | 5.862 | 6.312 | **5.864** |

A team's passing volume is barely a team property: the league mean beats the
team's own season, so `PASS_OWN_WEIGHT` is 0.3. Rushing volume is one: there
the league mean is the worst of the four, so `RUSH_OWN_WEIGHT` is 0.8. That is
game script, not noise. Teams pass because they are behind, which belongs to
the game; they run because they choose to, which belongs to the offence.

`RUSH_OWN_WEIGHT` is deliberately not the measured argmin of 0.90: the rush
curve is flat from 0.7 to 1.0 while the pass curve moves eight times as much
across the same range, so one season's argmin is noise. Both weights are stored
as columns on every row, like `ewma_half_life` on `player_form_weekly`, so a
retune cannot leave stored rows disagreeing with the code that reads them.

Opponent adjustment was measured and rejected here: it made targets clearly
worse (5.667 to 6.021). Market inputs were left out because
`game_environment_weekly` exists for 2026 only, where six weeks of actuals is
no basis for fitting a weight. Feature 18 owns both.

`compute opportunity` belongs after `compute volume`, the only table it reads
besides `weekly_actuals`, and has no dependency on `compute usage`, `compute
form`, or `compute efficiency`. It refuses to run before `compute volume` has,
naming that command, the same guard `compute efficiency` uses for `compute
usage`.

**It has no roster source, on purpose.** A player's row for week N exists only
if he has at least one game this season before week N and his
most-recent-as-of-week-N team has a game in week N. `depth_charts` would
normally supply a roster, but it fails outright on 2026, the season this has
to run against, so nothing here depends on it. The consequence is explicit: a
rookie's or new signing's debut week gets no row, and an in-season trade shows
up only from his first game under the new team onward, never proactively.

**Targets, carries and attempts are a blend; routes is not.** Each of the
first three is `weight * own_pg + (1 - weight) * (team_exp * share)`, own_pg
being his trailing per-game average and share his trailing share of his
team's same quantity. `exp_routes` is always `own_routes_pg`: feature 15a
left team dropbacks unprojected, since the only source stops publishing after
2025, and nothing here invents a substitute.

**Unlike `team_volume_weekly`, the two sides mostly agree at the player
level.** Measured on 2024 weeks 6 to 18, mean absolute error per player-week
over the 4,761 rows where both sides were available:

| weight | targets | carries | attempts |
| --- | --- | --- | --- |
| 0.0 | 1.3358 | 1.0858 | 0.8285 |
| 0.3 | 1.3338 | 1.0837 | 0.8286 |
| 0.5 | 1.3336 | 1.0831 | 0.8311 |
| 1.0 | 1.3385 | 1.0840 | 0.8425 |

Every curve is close to flat, because a team's own expectation is itself
built from the same recent weeks a player's share is, so the two signals
largely agree instead of pulling apart the way team-level pass and rush did.
Argmins were 0.4, 0.5 and 0.1, each inside a flat band rather than a sharp
minimum, so `TARGETS_OWN_WEIGHT` and `CARRIES_OWN_WEIGHT` ship at the round
0.5 and `ATTEMPTS_OWN_WEIGHT` at the round 0.2, the "round number inside the
flat region" judgement call `RUSH_OWN_WEIGHT` already made, rather than one
season's argmin.

`compute expected-efficiency` reuses `player_opportunity_weekly`'s row set
(feature 15b) rather than re-deriving which (player, week) pairs are worth
projecting a second time, so it belongs after `compute opportunity` and
refuses to run before that table is filled for the season.

**It shrinks a rate, not a count, which is why it blends toward the league
rate at the player's position rather than toward a team-level figure.** A
player's own trailing yards per target, catch rate, yards per carry and yards
per attempt are each blended against the league rate among every player at the
same position over the same strictly-prior weeks: a RB's catch rate and a
WR's catch rate are not draws from the same distribution, so pooling across
positions would be the wrong baseline.

**Unlike the volume tables, every rate here has a real minimum, not a flat
curve.** Measured on 2024 weeks 6 to 18, mean absolute error per player-week
against the actual realized rate that week:

| weight | yards/target | catch rate | yards/carry | yards/attempt |
| --- | --- | --- | --- | --- |
| 0.0 | 4.2317 | 0.2484 | 2.4821 | 1.8591 |
| 0.3 | 4.2063 | 0.2463 | 2.4310 | 1.8307 |
| argmin | 4.2036 @ 0.2 | 0.2461 @ 0.4 | 2.4310 @ 0.3 | 1.8307 @ 0.3 |
| 1.0 | 4.5190 | 0.2514 | 2.6567 | 2.0670 |

Leaning entirely on a player's own trailing rate is the worst choice at every
stat, and blending beats the position baseline alone too, by a smaller but
real margin. All four argmins are already round numbers in 0.2 to 0.4, so
`YARDS_PER_TARGET_OWN_WEIGHT` (0.2), `CATCH_RATE_OWN_WEIGHT` (0.4),
`YARDS_PER_CARRY_OWN_WEIGHT` (0.3) and `YARDS_PER_ATTEMPT_OWN_WEIGHT` (0.3)
ship as measured, with no "round number in a flat region" compromise needed.

Each rate's sample size is tracked separately from `games_played`, as
`receiving_opportunities`, `rushing_opportunities` and `passing_opportunities`:
a player can have ten prior games and a yards-per-carry built from one of
them, if the other nine were pass plays only. Read the opportunity count
before trusting the rate, the same caveat `player_form_weekly.ryoe_games_l3`
carries for rush yards over expected.

`compute` reads play-by-play and the tables the ingest commands filled, so run
the relevant `ingest` commands for a season first.

**nflverse pulls are cached on disk for 24 hours.** `statify/sources/nflverse.py`
sets `cache_mode = filesystem`, because nflreadpy's default caches in memory
only and every statify command is its own process: without this, each `compute`
re-downloaded the whole play-by-play parquet, and a GitHub outage stopped all
work. Measured on 2024, `compute defense` takes about 3.6s cold and 1.2s warm,
and a warm run completes with the network unreachable.

Two things follow from that:

- **A mid-week re-pull may serve yesterday's data.** Injuries, depth charts and
  rosters change daily, and the intended workflow runs once mid-week and again
  near kickoff. Force a fresh download when it matters:
  `NFLREADPY_CACHE=off uv run statify ingest injuries --season <year> --week <n>`.
  Setting `NFLREADPY_CACHE` to anything non-empty also stops the project
  overriding it, so `filesystem`, `memory` and `off` all behave as documented.
- **The cache is not where it says it is**, on the Microsoft Store build of
  Python. nflreadpy reports `%LOCALAPPDATA%\nflreadpy\nflreadpy\Cache`, but Store
  Python virtualizes writes, so the parquet files actually land under
  `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.13_<id>\LocalCache\Local\nflreadpy\...`.
  Ask Python for `nflreadpy.config.get_config().cache_dir` and call `.resolve()`
  on it rather than trusting the printed path.

`uv run pytest` (from `pipeline/`) is the test command, so the testing gate in
`blueprint/context/coding-standards.md` is on: a step that adds pure logic ships a
passing test in the same diff. It covers the Python pipeline only; the Next.js app
has no runner, and UI work still rides on build output and observed behavior.

There is no combined `Verify` command and no automatic GitHub checks. Until one
exists, `uv run pytest` plus `npm run build` and `npm run lint` are the automated
evidence for a change.

## Conventions

- Server components by default; add `'use client'` only for interactivity,
  hooks, or browser APIs.
- Routes live in `app/`, at the repository root (there is no `src/`).
- Import alias: `@/*` maps to `./*`.
- Components in PascalCase files, functions in camelCase, types and interfaces in
  PascalCase with no prefix.
- Tailwind utility classes for styling. No inline styles, no `tailwind.config.js`
  (v4 uses `@theme` in `app/globals.css`).
- No `any`. Use precise types or `unknown`.
- Keep functions under 50 lines where practical; no commented-out code, unused
  imports, or unused variables.
- Comment the why, not the what. No banner blocks or narration of obvious code.
- No em dashes in generated content (docs, comments, commit messages).

## Working style

- Small, reviewable changes, one at a time.
- A new branch per feature or fix; ask before committing, merging, or pushing.
- Conventional commit messages (`feat:`, `fix:`, `chore:`). No AI attribution in
  commit messages.
- Do not add features that were not asked for, and do not refactor unrelated
  code.
- Verify UI behavior by running the app, not by reading the code and assuming.

<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->
