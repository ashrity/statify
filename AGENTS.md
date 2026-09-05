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
- Tests: `uv run pytest`

Ingest order matters: teams, then games and players for a season, then weekly,
redzone, ngs, snaps, depth, and injuries. Each loader updates only the columns it owns, so
re-running one never wipes another's work.

`ingest snaps` also inserts rows for players who took offensive snaps but
recorded no stat, so run `ingest redzone` after it to fill their red zone
touches.

Feeds disagree on team abbreviations (Next Gen Stats says `LAR` where the rest say
`LA`). Inbound rows go through `normalize_team()` in `statify/ingest/common.py`;
add aliases there, not per-loader.

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
