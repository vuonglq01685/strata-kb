# CENTER-KB Quickstart (dev repo)

This repo is a **product code** repo: it consumes the shared knowledge base
while implementing BA tickets, and it publishes two knowledge documents
about its OWN source code back to the hub. Generated structure
(`<repo_id>-code`) is automatic — `.github/workflows/kb-code.yml` runs
`kb code-ingest` → `kb build` → `kb ci-publish` on every push to `main` or
`master`. Curated responsibility knowledge (`<repo_id>-svc`) is bootstrapped
once via `/dev-code-seed` (see "Onboarding an existing project (once)"
below) and then accrues automatically per ticket via `kb svc note` (see
"Keeping it current" below). This repo never ingests documents from
outside itself — that happens in `child` repos, reviewed on the `hub`.

## Setup once

1. **Install** — `pip install center-kb` (or clone this repo if someone
   already scaffolded it; otherwise `kb init --kind dev` in an empty
   folder creates it).
2. **Point at the hub** — fill `hub:` in `.kb/config.yaml` with the main
   hub's git URL or path. This is the only read source for `kb query` /
   `kb resolve` / `kb get` / MCP.
3. **Point at the intake for publishing** — fill `intake:` in
   `.kb/config.yaml` with the hub's intake service URL, then ask the hub
   maintainer to add this repo under `repos:` in the hub's
   `federation/registry.yaml`. `kb-code.yml` uses both to publish
   `<repo_id>-code` automatically on every push to `main` or `master` —
   and, once `<repo_id>-svc` content is committed to that branch, the
   very same `kb ci-publish` step republishes it too: it diffs the whole
   `.kb/` tree, not `-code` alone, so a merged `-svc` amend rides the
   next push out to the hub with no separate command. What CI never
   does is *create* `-svc` content — `--scaffold-svc` is never passed
   there. The one-time seed below still runs `kb publish --pr` by hand
   for its first-ever publish, simply because that happens *before*
   anything has merged to the default branch yet, so there is no push
   for `kb-code.yml` to react to.
   Whether the hub PR `kb ci-publish` opens for `<repo_id>-code` then
   auto-merges is a **hub-side branch-protection/labeling policy** — not
   `kb-code.yml`'s own behavior — so ask the hub maintainer whether (and
   how) auto-merge is configured for this repo's PRs. It is safe to
   automate because `-code` is deterministic and LLM-free by
   construction. `<repo_id>-svc` PRs are never auto-merged: that
   document is LLM-drafted and always needs a human review before it can
   publish.
   **One consequence that matters more than it sounds:** `kb ci-publish`
   opens **one** hub PR per push, not one per document — the intake
   keys the publish branch by repo id and reuses it while a PR is
   pending, so a push carrying a regenerated `-code` alongside an
   already-merged `-svc` amend lands both in that **same** PR. A hub
   auto-merge rule that fires on "this is a `dev` repo's `-code` publish"
   would therefore also auto-merge whatever `-svc` content rode along
   with it. **The auto-merge rule must be path-scoped** — matching only
   changed paths under `.kb/<repo_id>-code/**` — never a whole-PR or
   whole-repo rule, or it silently defeats the `-svc` review gate this
   two-document split exists to protect.
4. **Connect the shared MCP server** — set two environment variables so
   your AI assistant can reach the hub's search/citation tools:
   - `CENTER_KB_HUB_URL` — e.g. `http://kb-hub.example.com:8321`
   - `CENTER_KB_HTTP_TOKEN` — the hub token (ask the hub maintainer)
   `.mcp.json` (Claude Code) and `.cursor/mcp.json` (Cursor) are already
   wired to these two variables — nothing else to configure.
5. **Open this repo** in Claude Code, GitHub Copilot Chat, or Cursor — the
   `dev-implement-ticket`, `dev-design`, `dev-plan`, `dev-execute`, and
   `dev-handover` skills/commands/prompts are scaffolded for all three.

## Onboarding an existing project (once)

An existing product repo already has services doing real work — adopting
center-kb should not mean documenting the system from a blank page. Run
`/dev-code-seed` (the `dev-code-seed` skill/command/prompt) once per repo,
and it walks seven steps:

1. **Preflight** — confirms `.kb/config.yaml` has `hub:`, `repo_id:`, and
   `intake:`; confirms this repo is allowlisted in the hub's
   `federation/registry.yaml` (ask the hub maintainer if it isn't yet);
   warns if the working tree is dirty.
2. **Extract** — runs `kb code-ingest --scaffold-svc`, which regenerates
   `<repo_id>-code` and creates a `pending` `svc.<name>` scaffold in
   `<repo_id>-svc` for every service the extractors found, backed by
   deterministic code evidence in each section's L3.
3. **Draft** — runs `kb summarize <repo_id>-svc`, asking an LLM to write
   an L2 responsibility paragraph for every scaffolded section from that
   L3 evidence.
4. **Review — the actual work, and it is yours.** Walk every drafted
   `svc.*` section, L2 next to its L3 evidence, and correct it.
   **The LLM draft is a draft, not a fact.** It can name the wrong flow,
   miss a responsibility, or over-claim one — approving a section you
   have not read defeats the entire point of the gate. Where a
   responsibility touches a domain standard, cite `doc-id §section` from
   the hub instead of restating the rule in your own words.
5. **Approve** — `kb approve <repo_id>-svc` (or `--section <id>` for a
   subset) flips the sections you just corrected from `summarized` to
   `reviewed`.
6. **Flows (optional)** — add `flow.<name>` sections for business flows
   that cross several services, if you can describe them. Skip freely —
   a missing flow beats a guessed one.
7. **Validate and publish** — `kb build` **without** `--allow-pending`
   must pass before you publish; resolve or remove anything still
   `pending` (`--allow-pending` is only for the middle of a seed, never
   for what you publish). Then commit and run `kb publish --pr` to open
   a PR on the hub — plain `kb publish` would instead tag the commit and
   poll the intake service for up to ten minutes, waiting on a
   tag-triggered CI run this repo never has (`kb-code.yml` has no tag
   trigger), then fail with a misleading "check the Actions run" error.
   **That hub PR is reviewed by a BA or architect**, the same
   as any other hub content — this is curated knowledge, not generated
   knowledge, so it publishes through review, not auto-merge (see the
   auto-merge policy note in step 3 of "Setup once" above — it is not
   repeated here).

Budget **10–15 min per service** for step 4 — that is the honest cost of
a seed, and it is a one-time cost. Everything after the seed publishes is
either regenerated automatically (`<repo_id>-code`) or accrued a few
lines at a time (`<repo_id>-svc §hist.*`, see "Keeping it current" below)
— no per-ticket documentation discipline required.

## Implement a ticket

Pick the entry point that matches where the work already stands — every
phase is resumable, because state lives in `docs/impl/`, the branch, and
the PR, not in the assistant's memory:

| Situation | Run |
| --- | --- |
| New ticket, nothing started | `/dev-implement-ticket <ticket>` |
| Small ticket, the whole change is obvious | `/dev-implement-ticket <ticket>` — the flow collapses itself; the design stays in chat |
| Design approved, no plan yet | `/dev-plan <id>` |
| Plan approved, or execution already in progress | `/dev-execute <id>` |
| Code hand-implemented, needs a PR write-up | `/dev-handover <id>` |
| Lost track of where a ticket stands | `/dev-implement-ticket <id>` |
| Just want to check a citation, no implementation | `kb resolve <file>` |

`/dev-implement-ticket` is also the orchestrator: given a ticket fresh, it
runs Intake → Resolve → Ground → Placeholders, then invokes `dev-design`,
`dev-plan`, `dev-execute`, and `dev-handover` in order, detecting how far a
ticket already got so it never redoes finished work.

## Where work lives

- `docs/impl/<ticket-id>-design.md` — the design produced by `dev-design`.
- `docs/impl/<ticket-id>-plan.md` — the checkbox task plan produced by
  `dev-plan`, and the resume point `dev-execute` reads from.
- `docs/impl/<ticket-id>-context.md` — the resolved-context cache written
  by `dev-implement-ticket`; gitignored, regenerated by any full
  re-resolve. Not a state marker — it may legitimately be absent.

State is derived from those first two files plus the current git branch and
whether a PR is open — never from conversation history — so any phase can
resume cold in a brand-new session. `kb init` never touches your
`docs/impl/` content: it only ever adds `docs/impl/.gitkeep` (so the
directory exists before your first ticket does) and `docs/impl/.gitignore`
(so the context cache never lands in a PR).

## The four gates

Nothing in this pipeline merges or ships without a human:

1. **Design approved** — the Dev signs off on `dev-design`'s output before
   any plan is written.
2. **Plan approved** — the Dev signs off on `dev-plan`'s task breakdown
   before any code is written.
3. **PR opened** — `dev-handover` writes up the PR body; a human opens it.
4. **Merged** — a human reviews and merges. The agent does neither of the
   last two itself.

## What is enforced

- **TDD** — no production code without a failing test observed first, at
  every step of `dev-execute`. No exception for a small ticket, a
  deadline, or an "obvious" change.
- **Shown verification** — no completion claim without pasting the real
  command output; a claim without it is never accepted.
- **Pinned values, verbatim** — every code/format/enum/threshold that
  encodes a standard comes from the resolved section at its pinned hub
  version, with a citation comment. Nothing is invented or "remembered."
- **The ticket is read-only** — the agent reports placeholder resolutions
  and findings back to the BA; it never edits the ticket itself.

## Keeping it current

The two code-knowledge documents stay current in two different ways —
neither needs new per-ticket discipline from you:

- **`<repo_id>-code`** needs nothing from you. `kb-code.yml` re-runs
  `kb code-ingest` → `kb build` → `kb ci-publish` on every push to the
  default branch, so it always reflects the current commit's structure.
- **`<repo_id>-svc`** accrues automatically at handover: `dev-handover`
  runs `kb svc note <service> --ticket <id> --title "<title>" --refs
  "<refs>"` for every service a ticket touched, appending one row to
  that service's `hist.<service>` section. You never hand-edit `hist.*`
  — it is an append-only log written only by `kb svc note`.

**Responsibility text can still drift, and it self-reports rather than
self-heals.** When `kb code-ingest --scaffold-svc` refreshes a service's
L3 code evidence, and that section's L2 is already `reviewed`, it
compares the old and new rendered evidence as a **whole-body,
whitespace-trimmed** string — not a semantic diff over specific fields.
**Any** change other than to leading/trailing whitespace flags
`stale-risk: svc.<name>` in the ingest report: a real change (a file
or table added or removed) will trip it, but so will a change in
nothing but *how* the evidence is rendered, with zero code changed
underneath (see the upgrade note just below for exactly that case).
That is not an error and it never touches L2 — it is a flag that a
human-reviewed sentence may no longer match the code, for a human to
resolve. **Amend that section's L2 prose by hand and
leave it `reviewed`** — the person correcting it is the reviewer; no
further approval step is needed.

**Do not reach for `kb summarize --redo` to fix one service.**
`redo_reset` has no per-section scope: it resets **every** section of the
document to `pending` and blanks every `summary`, including sections
that were already `reviewed`, and rebuilds every L2 file from its
scaffold — `services.md` included, not just `history.md`. It is not the
data-loss event it sounds like **for the accrued ticket history**: the
scaffold rebuild keeps every `|`-prefixed line, so the `hist.*` ticket
rows in L2 survive, and `redo_reset` never rewrites `history.raw.md` at
all, so the L3 record survives too. **It genuinely is a data-loss event
for a service's responsibility prose, though**: a human's corrected
`svc.*` text is wiped from both `services.md` (L2) and the manifest's
`summary` field. `services.raw.md`'s code evidence survives, so the
section can always be re-drafted from scratch — but the human's
corrections themselves come back only from git, not from
`kb summarize`. `kb summarize --redo` does not stop at the reset,
either: it re-summarizes in the same command right away. That includes
`hist.*` — its ticket rows survive as described above, but the
machine-authored summary `kb svc note` wrote for that section is
replaced by LLM prose — and every section that was `reviewed` before the
redo loses that status and is re-summarized from scratch along with
everything else. Use the hand-amend path above instead — `--redo` is for
re-seeding a whole document from scratch, never for correcting one
entry.

**The first `kb code-ingest --scaffold-svc` run after upgrading past this
release will likely report `stale-risk` for every already-`reviewed`
`svc.*` section, even though nothing in your code changed.** This release
relabels two L3 evidence lines in the `services` extractor — `tables:`
and `files:` become explicit name-match heuristics, stated as such
because their absence proves nothing — which changes the rendered L3
bytes those sections compare against, not the code they describe. Expect
the one-time `stale-risk` batch, open each flagged section, confirm the
responsibility prose still holds, and amend by hand only where it does
not; there is nothing to fix in the code itself.

**A note on the `kb-summarize` wrapper's wording.** The `kb-summarize`
skill/command/prompt scaffolded on this repo is the identical resource a
`child` repo gets, and its own text says "after `kb ingest`" and
"`kb ingest` generated the scaffold." Both are literally true on a
`child` repo and **false here** — a `dev` repo never runs `kb ingest`
at all. On this repo, read every `kb ingest` mention in that wrapper as
`kb code-ingest --scaffold-svc`: that is the command that actually
created the scaffold `kb-summarize` fills, in the Onboarding step above.

## Upgrading

Re-run `kb init --kind dev` to pick up new templates. This only ever
touches **scaffold files** — the skill/command/prompt wrappers,
`QUICKSTART-DEV.md`, `.github/workflows/kb-code.yml`, and the
`docs/impl/.gitkeep` marker — and only overwrites one when its content
differs from the new template; `.kb/config.yaml`, `.kb/index.yaml`, and
`.claude/settings.json` are never touched by a plain `kb init` — but
`--force` replaces all three outright: your hand-edited `.kb/config.yaml`
(`kind`, `repo_id`, `asset_store` included), `.kb/index.yaml`, and your whole
`.claude/settings.json` (hooks, permissions and model included), none of it
merged. Anything you authored under `docs/impl/` is not scaffolding:
`kb init` never reads, writes, or overwrites it.
**If you hand-edited a wrapper, `kb-code.yml` (including any `--db` flags
you added), or QUICKSTART-DEV.md, back it up first: your edits are lost.**

## Token and cost measurement

`kb init` wrote `.claude/settings.json` with one `Stop` hook that calls
`kb usage ingest-transcript --hook-stdin` after each turn. It reads Claude
Code's own transcript — the numbers are the assistant's real usage, not an
estimate — and appends them to `.kb/usage/<ticket>.jsonl`, which is committed,
so a ticket's cost travels with the ticket. `.claude/settings.json` itself is
committed too — a teammate who pulls the repo without `kb` on their `PATH`
otherwise sees this hook fail on every turn.

It **adds about 0.6s per turn** (the cost of starting the `kb` CLI; parsing the
transcript itself is ~60ms). That is the price of the data.

- `kb usage report` — writes `.kb/usage/report.html`; open it in a browser. Per
  ticket, per phase, per model, plus a `_unattributed` bucket.
- `kb usage report --ticket <id> --md` — a Markdown table for a PR body.
- `kb usage ingest-transcript <path>` — backfill. Every transcript under
  `~/.claude/projects/<this-repo>/` can be ingested now; re-ingesting is safe,
  rows are de-duplicated by the transcript's own row ids.
- Subagent cost is recorded separately (`sidechain`), so a `dev-execute` run
  that fans work out to subagents shows where the tokens actually went.
- `kb usage note --ticket <id> --phase <p> --model <m> --tokens-in N --tokens-out N`
  — record a row by hand. It always **appends** a new row, so it is never
  the way to fix one the automatic attribution got wrong — using it that way
  double-counts the tokens. The real repair is editing the stored row
  directly in `.kb/usage/<ticket>.jsonl`, then re-running `kb usage report`.
  If you already re-ingested the transcript, `--ticket` on
  `kb usage ingest-transcript` cannot help either: every row's uuid is
  already recorded, so there is nothing left for it to move.

A row is attributed to whichever ticket file the session mentioned most
recently (`docs/impl/<id>-{design,plan}.md`, `tickets/<id>.md`,
`missions/<id>.md`). Work done before any ticket file is mentioned lands in
`_unattributed.jsonl` — a large bucket there means attribution is missing
work, not that the work was free.

If `.kb/usage/*.jsonl` isn't growing, check `.kb/usage/ingest-errors.log` —
the hook fails silently by design (a `Stop` hook cannot block a turn from
ending), so this file is the only place a failure — a mistyped `kind:`, a
missing transcript, a corrupt ledger line — is ever visible.

**The `kb` on your `PATH` must be 0.19.0 or newer.** An older `kb` has no
`usage` command, so the hook exits 2 — and a `Stop` hook exiting 2 blocks the
turn from ending instead of failing quietly. Nothing reaches
`ingest-errors.log` either, because the failure happens before `kb usage` runs
at all. Run `kb --version` if a session starts refusing to finish, and upgrade
rather than deleting the hook.

**Re-ingesting is always safe**, because a call already in the ledger is
recognised and skipped. So if you ever have reason to distrust a ledger file,
the repair is to delete it and re-ingest the transcripts:

```bash
rm .kb/usage/<ticket>.jsonl
for f in ~/.claude/projects/<this-repo-slug>/*.jsonl; do
  kb usage ingest-transcript "$f"
done
```

If this repo already had a `.claude/settings.json`, `kb init` left it alone.
Merge the hook in by hand:

```json
{"hooks": {"Stop": [{"hooks": [
  {
    "type": "command",
    "command": "kb usage ingest-transcript --hook-stdin",
    "timeout": 30,
    "statusMessage": "Recording token usage..."
  }
]}]}}
```

`--force` does not merge this hook in for you: it replaces the whole file
with the scaffolded one, so a repo with its own `.claude/settings.json`
still needs the hand-merge above.

`.kb/usage/report.html` is generated, not a record — the committed `.jsonl`
ledgers are. Regenerate it whenever you want with `kb usage report`; commit it
only if you want it browsable on GitHub.

Prices come from a table shipped with the package; override it per model in
`.kb/usage-prices.yaml`. The report prints the table's `effective_date` and
warns when it is over 90 days old. A model with no rates is reported as
`unpriced` with its token counts — never as free.

## Model tiering

A recommendation, not a rule — nothing in `kb` enforces or measures compliance
with it. Some steps in this pipeline are judgment and some are mechanical;
running both on the same model pays the judgment price for the mechanical half.

| Tier | Steps |
| --- | --- |
| Strong | `dev-design`, `dev-plan`, and the review checkpoint inside each `dev-execute` task |
| Cheap | the lint/format fix loop, re-running the suite until green, ticking plan checkboxes, assembling the PR body, `kb usage report --ticket <id> --md`, and the `kb svc note` calls at handover |

Which model belongs to which tier follows the price table in force —
`usage-prices.yaml` shipped with the package, overridable per model at
`.kb/usage-prices.yaml`. That table carries an `effective_date` and is the only
list of models in this project; this page deliberately keeps no second copy to
rot.

**Switch at phase boundaries, never inside a phase.** Changing model mid-session
discards the prompt cache and pays a fresh cache write at the new model:
`cache_write` costs 1.25x input at 5m and 2x at 1h, and every write measured
here so far has been 1h. Three cheap-model turns in the middle of a
strong-model session can cost **more** than not tiering at all.

Check the result instead of trusting it: `kb usage report` already breaks
spending down by model, and subagent cost is separated as `sidechain`, so a
tiering change shows up in the report the next ticket generates.

## CLI reference

- `kb init --kind dev` — scaffold or refresh this repo
- `kb resolve <file> [--hub <url>]` — resolve a ticket's `kb-context`
  block and report freshness (ok/stale/broken)
- `kb get <doc-id> <section> [--level l3]` — fetch one section at a given
  level, escalating past the summary when a value must be encoded exactly
- `kb query "<text>"` — hybrid search over the hub's summaries
- `kb code-ingest [--scaffold-svc]` — (re)generate `<repo_id>-code`; add
  `--scaffold-svc` to also upsert the `<repo_id>-svc` scaffold (seed/amend)
- `kb svc note <service> --ticket <id> --title "<title>" [--refs "..."]`
  — append this ticket to `<repo_id>-svc §hist.<service>` (run by
  `dev-handover`; idempotent per ticket)
- `kb doctor --hub <url>` — check the hub is reachable and
  `.kb/config.yaml` is valid
- `kb usage report [--ticket <id>] [--md]` — token and cost totals for this
  repo's tickets
- `kb usage ingest-transcript <path>` — backfill usage from a Claude Code
  transcript
