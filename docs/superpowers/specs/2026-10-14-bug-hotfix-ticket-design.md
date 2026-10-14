# Bug / hotfix tickets — design

Date: 2026-10-14 · Target release: 1.25.0

## Intent

The framework runs missions and user-story tickets well, in order. Once a
product is live, the BA also has to log bugs and production hotfixes. A bug
is not a user story: it has no "As a … I want … so that …", no business
flow, and its acceptance is "the steps no longer reproduce the wrong
result". Today every file under `tickets/` is linted as a story, so a bug
report fails CI, never publishes to the hub, and the Dev cannot
`kb ticket fetch` it.

This change adds a second ticket type — **bug** (with a **hotfix**
variant) — with its own template, its own lint contract, attachments
(screenshots) that reach the hub, a BA skill that writes one, and a Dev
skill that fixes one the way `superpowers:systematic-debugging` works: root
cause first, a failing reproduction test before any fix.

## Goals

- A BA writes a bug report from a template with: environment,
  pre-conditions, numbered steps to reproduce, expected result, actual
  result, attachments (images, optional), impact/severity.
- A bug may link to an existing ticket (`> Related ticket: <id>`) or to
  nothing.
- `kb ticket lint` (CLI, MCP `kb_ticket_lint`, CI `kb-ticket-lint.yml`)
  recognises a bug and checks it against the bug contract — no CI or MCP
  signature change.
- `kb plan-ingest` publishes a ready bug to the hub; its screenshots
  publish with it and render on the hub ticket page.
- `kb ticket fetch <BUG-id>` gives the Dev the bug and (CLI) its images.
- `/ba-bug-report` (BA) and `/dev-fix-bug` (Dev) skills, installed by
  `kb init` for all four clients (Claude skill + command, Copilot prompt,
  Cursor command).

## Non-goals

- No change to user-story tickets: every existing ticket keeps passing
  without an edit (`REQUIRED_HEADINGS` stays as is).
- No Jira sync, no SLA timers, no on-call paging.
- No maturity review (two-reviewer rubric) for bugs — a bug is a fact
  report, not a design.
- No new MCP tool and no new parameter on an existing one.
- No JPEG/GIF attachments in this release (see Attachments).
- No bug-specific hub page or badge; a bug shows in the hub's ticket list
  like any ticket, its title carrying the `BUG-<n>` id.

## Anti-goals

- A bug that lints green but cannot be reproduced from its text alone.
- A Dev skill that lets the agent "try a fix" before a failing test
  reproduces the bug.
- Screenshots that live only in the BA repo, invisible to the Dev.

## The bug ticket

### Identity and place

- Id `BUG-<n>` (file stem), for both bug and hotfix. It already matches
  every id rule in the code (`prlint._TICKET_ID`, `usage.ledger.STEM_RE`,
  `planstatus.safe_name`), so PR lint, usage attribution and fetch work
  unchanged.
- File `tickets/bugs/BUG-<n>.md`. Attachments in `tickets/bugs/BUG-<n>/`.

### Header lines (under the H1)

```
# BUG-12 — <one-line symptom>
> Type: bug                 # bug | hotfix
> Severity: S2              # S1 | S2 | S3 | S4
> Revision: 1
> Related ticket: M-billing-US3   # optional; a ticket id, or `none`
```

`> Type:` is the type discriminator. No `> Type:` line → user story, as
today. Severity scale (template comment):

| Sev | Meaning |
|---|---|
| S1 | Production down, data loss or security exposure; no workaround |
| S2 | A core function is broken; workaround painful or none |
| S3 | A function misbehaves; a reasonable workaround exists |
| S4 | Cosmetic / wording / layout |

`hotfix` means "ships ahead of the next planned release, from the
production line". The lint does not tie it to a severity (business call).

### Sections

Required (`BUG_REQUIRED_HEADINGS`), each non-empty:

1. `## Summary`
2. `## Environment` — env (production/staging/…), app version/build,
   device/browser/OS, account/role, when first seen.
3. `## Pre-conditions` — the state that must hold before step 1 (data,
   flags, logged-in role).
4. `## Steps to reproduce` — a numbered list (`1.`), at least one step.
5. `## Expected result` — with concrete values; cite `[doc-id §section]`
   when the expectation comes from a standard / an AC.
6. `## Actual result` — what happens, with concrete values, error text
   verbatim.
7. `## Attachments` — images `![caption](BUG-<n>/<file>.png)` and/or
   `N/A — <reason>`.
8. `## Impact` — who/how many are hit, frequency, workaround.
9. `## Definition of Ready`

Recommended (warning when missing/empty): `## Open questions`.

Optional, validated only when present: `## KB context` (same block and
checks as a story), `## Technical grounding` (SA-owned, same
`kb ticket check`), `## Change log`.

A `> Parent mission:` line on a bug is an error: a bug is not a backlog
story; it links with `> Related ticket:`.

Bug Definition of Ready (template):

- [ ] Steps reproduce the actual result on the stated environment
- [ ] Expected and actual result stated with concrete values
- [ ] Attachments added, or `N/A — <reason>`
- [ ] Severity set; related ticket linked or `none`
- [ ] Every open question has an owner

### Attachments

- Format: PNG or WebP only — the hub's asset convention
  (`assetstore._ASSET_NAME_RE`) is sha-named png/webp. Lint errors on any
  other extension with "save it as PNG". *Shortcut, the limit is
  documented; upgrade by widening the asset regex + content types when a
  BA needs JPEG.*
- Path: relative, inside the bug's own folder (`BUG-<n>/…`). Absolute
  paths, `..`, and `http(s)://` images are errors (the hub CSP is
  `img-src 'self'`, and a Dev may not reach an external host).
- Lint checks the file exists when it knows the ticket path (CLI / CI);
  over MCP (no path) it checks only the shape.
- `kb plan-ingest` copies each referenced image to
  `<repo>-plan/assets/<sha256>.<ext>` and rewrites the reference to
  `assets/<sha256>.<ext>` in the published L2/L3. Unreferenced old assets
  in that folder are removed. Publish already mirrors `**/assets/*`
  (`pubgate.is_kb_artifact`) and the hub already serves `/assets/<name>`
  from any federation folder or the object store.
- Hub ticket page (`web/gfmrender.render`): an image whose src is
  `assets/<sha>.(png|webp)` is rewritten to `/assets/<sha>.<ext>`.
- `kb ticket fetch` (CLI) copies the referenced assets from the hub clone
  to `docs/impl/<id>/assets/` so the Markdown's relative links work
  locally. MCP `kb_ticket_fetch` returns text only; the Dev skill tells the
  Dev to open `<hub>/assets/<name>` or use the CLI.

### Lint and publish

- `ticket.ticket_type(text) -> "story" | "bug" | "hotfix"`; an unknown
  `> Type:` value is an error naming the allowed values.
- `ticketlint.lint()` dispatches: story → today's checks unchanged; bug /
  hotfix → a new `buglint` module reusing `lintcore` (headings, filled
  sections, context block, revision, DoR checklist).
- CI `kb-ticket-lint.yml` is untouched — the dispatch is inside
  `kb ticket lint`.
- `kb plan-ingest` publishes a bug like a ticket (same lint + DoR gate),
  group `tickets`; its L2 keeps `Summary`, `Steps to reproduce`,
  `Expected result`, `Actual result`.
- `kb mission next`, `kb mission lint`, `kb ticket tidy`,
  `kb ticket stale` need no change (verified by the touchpoint survey:
  they key on backlog ids or tolerate any ticket).

## Skills

### `/ba-bug-report` (BA repo)

Intake (what broke, where, who saw it; screenshots the BA has) → Related
ticket (optional; read it when local) → Draft from
`docs/tickets/BUG-TEMPLATE.md` (next free `BUG-<n>`; copy screenshots into
`tickets/bugs/BUG-<n>/`, PNG/WebP) → optional KB grounding of the
expected result (`kb_search`, BA confirms; `kb_context_new` pin) →
Lint until `DoR: PASS` → hand over (BA commits; `kb publish` ships it).
Hard rules: never invent steps, values or error text — missing facts are
`OPEN(<owner>)` + an Open questions row; one bug per ticket; never edit a
done story to describe a bug.

### `/dev-fix-bug` (Dev repo)

Mirrors `superpowers:systematic-debugging`, inside the strata-kb flow:

1. **Intake** — `kb impl tidy`; fetch the bug (`kb_ticket_fetch` /
   `kb ticket fetch BUG-<n>`, saved as `docs/impl/<id>/ticket.md`); read
   the related ticket when linked. Branch `fix/<BUG-id>` (bug) or
   `hotfix/<BUG-id>` from the production line the Dev names (hotfix). Run
   `kb ticket check` only when `## Technical grounding` exists; resolve
   `kb-context` only when the block exists (broken → BA blocker).
2. **Reproduce** — turn Pre-conditions + Steps into a failing automated
   test that shows the Actual result. Not reproducible → stop, report to
   the BA with what was tried (no fix without a reproduction).
3. **Root cause** — read errors fully, check recent changes
   (`git log` on the touched files), trace the bad value to its source,
   compare with working code; one written hypothesis at a time, tested
   minimally. Recorded in `docs/impl/<id>/rootcause.md`
   (symptom, hypothesis log, root cause, evidence file:line).
4. **Fix** — one change at the root cause; the reproduction test passes;
   the full suite passes. Three failed hypotheses → stop and raise the
   architecture question with the Dev.
5. **Handover** — `/dev-handover` (PR body Ticket / Changes / Testing;
   Ticket = `BUG-<n>`, root cause one line under Changes).

Re-entry is derived, never stored: `rootcause.md` absent → Reproduce;
present without `Root cause:` filled → Root cause; filled and no PR →
Fix/Handover. Ends with the same `## Next step` block shape as the other
Dev skills, its State line being
`repro <✅|⬜> · root cause <✅|⬜> · fix <✅|⬜> · PR <…>`.

## Install (`kb init`)

- BA kind: `.claude/skills/ba-bug-report/SKILL.md`,
  `.claude/commands/ba-bug-report.md`, `.github/prompts/ba-bug-report.prompt.md`,
  `.cursor/commands/ba-bug-report.md`, `docs/tickets/BUG-TEMPLATE.md`.
- Dev kind: the same four files for `dev-fix-bug`.
- Shared bodies under `templates/init/bodies/` (the 1.15.2 rule: one body
  per skill, stubs include it).

## Docs and release

README skill lists, QUICKSTART-ba / QUICKSTART-dev, guide-ba / guide-dev
(en + vi), CHANGELOG `## 1.25.0`, `pyproject.toml` version 1.25.0.

## Calls made without the BA/PM (check these)

- One id prefix `BUG-<n>` for both bug and hotfix; hotfix is a `> Type:`.
- Severity S1–S4 scale and wording above.
- PNG/WebP only for attachments in 1.25.0.
- Bugs publish into the hub's `tickets` group (no separate group/badge).
- Separate skills (`ba-bug-report`, `dev-fix-bug`) rather than a mode of
  `ba-ticket-author` / `dev-implement-ticket`.
- No maturity review for bugs.
- Branch names `fix/<BUG-id>` / `hotfix/<BUG-id>`.
