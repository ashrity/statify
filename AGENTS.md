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
| Language | TypeScript 5, strict mode |
| UI | React 19 |
| Styling | Tailwind CSS v4 (CSS-first config in `app/globals.css`) |
| Lint | ESLint 9 flat config (`eslint.config.mjs`), `eslint-config-next` |
| Package manager | npm (`package-lock.json`) |
| Database | > TODO: none installed yet |
| Auth | > TODO: none installed yet |
| Tests | none installed yet |

## Commands

- Dev server: `npm run dev` (http://localhost:3000)
- Build: `npm run build`
- Production server: `npm run start`
- Lint: `npm run lint`

No test command is configured, so there is no required test gate yet. There is
no combined `Verify` command and no automatic GitHub checks. Until one exists,
`npm run build` plus `npm run lint` are the automated evidence for a change.

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
