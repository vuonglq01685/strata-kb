# Strata Quickstart (BA repo)

This repo is a **requirements** repo: it reads the shared knowledge base
to ground tickets in cited, versioned facts, and it versions the tickets
themselves under `tickets/`. It never ingests, summarizes, or publishes
KB content — that happens in `child` repos, reviewed on the `hub`.

## Setup once

1. **Install** — `pip install strata-kb` (or clone this repo if someone
   already scaffolded it; otherwise `kb init --kind ba` in an empty
   folder creates it).
2. **Point at the hub** — fill `hub:` in `.kb/config.yaml` with the main
   hub's git URL or path. Used by `kb ticket lint` and `kb query`.
3. **Connect the shared MCP server** — run `kb mcp-setup` (in your assistant:
   `/kb-mcp-setup`). It asks for the hub's HTTP base URL and token, writes
   both into `.env`, makes sure git ignores that file, and then verifies them
   against the hub so a wrong URL and a rejected token give you different
   errors.
   - `STRATA_KB_HUB_URL` — e.g. `http://kb-hub.example.com:8321`
   - `STRATA_KB_HTTP_TOKEN` — the hub token (ask the hub maintainer)

   `.mcp.json` (Claude Code) and `.cursor/mcp.json` (Cursor) already read
   those two variables from your environment, so load `.env` into your shell
   (`set -a; source .env; set +a`, or use direnv) and restart your assistant —
   MCP reads the environment only at startup.

   This is a *different* value from `hub:` in `.kb/config.yaml`, which is the
   git/path federation hub used by `kb query` and the lint gates.
4. **Open this repo** in Claude Code, GitHub Copilot Chat, or Cursor —
   the `ba-ticket-author`, `ba-mission-plan` and `sa-ticket-ground`
   skills/commands/prompts are scaffolded for all three.

## Create a ticket

5. **Draft** — invoke `/ba-ticket-author` (or the `ba-ticket-author`
   skill) with the business need. It runs the pipeline for you:
   1. **Intake** — you describe the need: capability, role, value.
   2. **Parent mission (optional)** — if this ticket implements a story
      from a mission plan, name the mission. It reads
      `missions/<mission-id>.md`, takes the story title from the US
      backlog row, and writes `> Parent mission: <mission-id>` on its own
      line directly under the ticket's title — the input the back-link
      check (see below) reads. The ticket is then saved as
      `tickets/<mission-id>-US<n>.md` instead of `tickets/<ticket-id>.md`,
      so that check can find it.
   3. **Ground** — it calls `kb_search`; review ALL candidates it shows
      you and pick the ones that actually apply.
   4. **Draft** — it fills the ticket template (story, ACs, use cases,
      sequence + business-flow diagrams), citing `[doc-id §section]` for
      every claim that touches a standard.
   5. **Pin** — once you confirm which sections apply, it calls
      `kb_context_new` and embeds the returned `## KB context` block.
   6. **Lint** — it runs `kb ticket lint` and fixes errors until it
      reports `DoR: PASS`.
   7. **Ground technical** — it saves the draft and invokes
      `/sa-ticket-ground` on it as a separate run (no shared context).
      That fills the SA-owned `## Technical grounding` section from the hub's
      `<repo>-code` document (service, files, tables, routes, externals,
      test command — section ids only) and runs `kb ticket check` until
      it reports `Grounding: PASS`. You never fill that section
      yourself, and the SA never edits yours. Its `## Needs input` block
      comes back to you in the handover.
   8. **Maturity review** — once lint reports `DoR: PASS`, it runs two
      independent reviews — as two subagents in parallel where the
      runtime supports it, otherwise two sequential passes, one role
      per pass — one scoring "Business coverage", one scoring "Dev
      implementability" — against `docs/review-rubric.md`. It applies
      the fixes and reviews again, up to 3 rounds or until both axes
      score ≥ 4; a gap it cannot close itself becomes an owned
      `OPEN(<owner>)` open question instead of a guess. The result
      lands in the ticket's `## Review record` section.
   9. **Review → save** — it writes the draft to `tickets/<ticket-id>.md`
      (or `tickets/<mission-id>-US<n>.md` from step 2). You review it,
      commit it, and paste it into Jira yourself — the assistant never
      publishes for you.
Run `/sa-ticket-ground tickets/<ticket-id>.md` by hand only to re-ground
a ticket after `<repo>-code` has moved.

### Greenfield repos: what `[NEW: D<n>]` means

In a repo whose code is still a skeleton, most of what a ticket needs
does not exist yet. That is **not** missing data — it is a design
decision. The SA proposes it as a row in the parent mission's
`## Technology decisions` (status `OPEN`, a human owner) and writes
`[NEW: D<n>]` on the grounding line, pointing at that row.

`kb ticket check` verifies the reference: the row must exist and its
`Status` must be `DECIDED`. An `OPEN` row fails the gate and names its
owner — **you** decide and flip it to `DECIDED`; the SA never flips a
status. Pass `--missions-dir <dir>` when the missions do not sit in the
ticket's sibling `missions/` directory.

Only code that genuinely exists and the document cannot prove — internal
flow, failure modes, request bodies — belongs under `Open decisions` for
the Dev. A ticket with no parent mission has no table to point at and
keeps a free-text `[NEW: <reason>]`: the gate accepts it, but the
decision then has no owner.

## Mission plans — for large features

A feature that spans several User Stories gets a **mission plan** first;
small work goes straight to a ticket. A mission is never mandatory.

Per mission:

1. `/ba-mission-plan` — the agent walks Intake → Ground → Draft →
   Split → Ground services → Pin → Lint → Maturity review → Review and
   saves `missions/M-<slug>.md`. At **Ground services** it invokes
   `/sa-ticket-ground --mission` itself: that fills the SA-owned
   `## Services & order` section and appends a `## Technology decisions`
   row for every service the mission will create. Its gate then reports
   FAIL on exactly those rows until a human flips them to `DECIDED` —
   that is the expected result, not a defect; flipping is your call.
2. Review the C4 L1/L2 diagrams (Level 1 = System Context, Level 2 =
   Container), the scope split, and the US backlog.
3. `kb mission lint missions/M-<slug>.md` must report `DoR: PASS`.
   A `0/N US drafted` coverage warning is normal — the tickets do not
   exist yet.
4. Commit the mission, then draft each story with `/ba-ticket-author`,
   naming the parent mission. Tickets are saved as
   `tickets/M-<slug>-US<n>.md` and carry a
   `> Parent mission: M-<slug>` line.

What the mission gate enforces: required structure, an L1 and an L2
diagram, a well-formed backlog whose ids derive from the mission id, and
every citation resolving at the pinned hub version. What stays your
judgment: whether the backlog is complete.

Backlog numbering gaps are fine. If you drop a story, leave its number
retired — renumbering would break the filenames of tickets already
drafted.

## Code knowledge on the hub

Alongside domain documents, the hub holds two documents per product
repo, published by that repo's `dev`-kind workflow: `<repo>-code`
(generated structure — names: `svc.*`, `db.*`, `api.*`, `int.*`,
`cmd.*`, `struct.tree`) and `<repo>-svc` (curated responsibility —
meaning).

The BA skills do not read them. Where a ticket or mission needs a
service, table, route or file name, `ba-ticket-author` and
`ba-mission-plan` write `%%TODO: verify against codebase%%` with an owned
open question, and `/sa-ticket-ground` answers those from `<repo>-code`
in the SA-owned section — `## Technical grounding` in a ticket,
`## Services & order` in a mission. Every id it writes is checked against
the document by `kb ticket check`; what the document cannot prove —
internal flow, failure modes, request bodies — is parked under
`Open decisions` for the Dev, who has the code.

The section reference itself, spelled the way a real citation is:

```text
<repo>-code §svc.<name>
<repo>-svc §svc.<name>
```

**One caution:** `<repo>-svc` grounds a diagram — it is never a substitute
for a domain citation in an Acceptance Criterion. A code/format/enum/
threshold that encodes a standard still has to come from a pinned domain
section, not from a service's responsibility text.

## DoR rules (what CI enforces)

Every pull request runs `.github/workflows/kb-ticket-lint.yml` — the name
predates the mission gate and is kept for branch-protection compatibility.
The workflow itself is not filtered to `tickets/`/`missions/` paths (see
"Branch protection" below for why); its one lint step inspects the PR's
own diff and dispatches by directory: `kb ticket lint` for a changed
ticket, `kb mission lint` for a changed mission. A PR touching neither
directory exits cleanly with a notice — nothing to lint. For a ticket it
checks:

- Required sections present (Summary, User Story, Background,
  Acceptance Criteria, Use cases, both Mermaid diagrams, KB context,
  Definition of Ready).
- Every `## KB context` ref resolves at its pinned hub commit — no
  broken or malformed refs.
- Every inline `[doc-id §section]` citation is backed by a pinned ref.
- Citations are written `[doc-id §section]`. A citation in the old bare
  form still counts, with a warning telling you to bracket it.

(See "Mission plans" above for what the mission gate checks.)

What lint does **not** enforce — still the BA's judgment call:
- Whether an Acceptance Criterion that touches a standard actually has
  a citation (warning, not error).
- The business quality of the story itself.
- Whether the maturity review actually happened: lint only warns when
  `## Review record` is missing, empty, or still holds the placeholder.
- **Stale refs.** A ref still resolves after the cited section is amended
  upstream; lint reports it as a warning and exits 0. Run
  `kb ticket lint <file> --fail-on-stale` (`kb mission lint <file>
  --fail-on-stale` for a mission plan; exit 2 when staleness is the only
  failure) or set the repo variable `KB_FAIL_ON_STALE` to make the CI gate
  do it for you. `kb resolve <file> --status-only` reports the same thing on
  its own.
- **The reverse citation direction.** A pinned ref that the body never cites
  is a warning, not an error — the pin may be background the ticket did not
  need to quote.

**Branch protection:** lint running in CI does not by itself block a
merge. On the BA repo's GitHub settings, require the `kb-ticket-lint`
check to pass before merging into the branch tickets and missions land
on. The workflow's trigger is deliberately **not** `paths`-filtered:
GitHub never synthesizes a passing status for a job that never started,
so a `paths: ["tickets/**.md", "missions/**.md"]` filter on a *required*
check would leave any PR touching neither directory waiting forever.
Instead the job always starts, and its own lint step (above) is what
decides there was nothing to check.

### Configuring the CI gate

The scaffolded `kb-ticket-lint` workflow reads these repository settings:

| Setting | Where | What it is |
|---|---|---|
| `STRATA_KB_HUB` | Settings → Secrets and variables → Actions → **Variables** | The hub URL or path the gate resolves refs against |
| `KB_HUB_TOKEN` | same page → **Secrets** | A token with read access, for a private hub only |
| `KB_FAIL_ON_STALE` | **Variables**, optional | Set to any value to make an upstream amendment fail the gate |

The workflow reads them as `vars.STRATA_KB_HUB`, `secrets.KB_HUB_TOKEN` and `vars.KB_FAIL_ON_STALE`.

A pull request opened **from a fork** cannot read repository secrets, so on
a private hub the gate fails there with a hub-unreachable message. That is
the gate refusing to go green without checking, not a network fault — merge
fork contributions through a branch in this repository, or make the hub
readable without a token.

## Upgrading an existing BA repo

Re-run `kb init --kind ba` to pick up new templates. This only ever
touches **scaffold files** — the CI workflow, the skill/command/prompt
wrappers, and the ticket/mission templates under `docs/` — and only
overwrites one when its content differs from the new template;
`.kb/config.yaml`, `.kb/index.yaml`, and `.claude/settings.json` are never
touched by a plain `kb init` — but `--force` replaces all three outright:
your hand-edited `.kb/config.yaml` (`kind`, `repo_id`, `asset_store`
included), `.kb/index.yaml`, and your whole `.claude/settings.json` (hooks,
permissions and model included), none of it merged.
Your own `tickets/` and `missions/` content is not scaffolding:
`kb init` never touches any file you author there. (The one thing it
does place in each directory is an empty `.gitkeep`, so git can track
the directory before your first ticket or mission exists — it never
reads, writes, or overwrites anything else there.)
**If you hand-edited a wrapper, back it up first: your edits are lost.**

v0.13.0 also tightens `kb ticket lint`'s diagram check: the
diagram-type keyword (e.g. `sequenceDiagram`, `flowchart`) must now sit at
the **start of a line** inside the Mermaid fence, not merely appear
somewhere in it. If lint now rejects a diagram that used to pass, move
that keyword to the start of its own line inside the fence.

v0.13.0 also stops counting a required heading (e.g. `## Business goal`)
as present when it only appears inside a fenced code block — pasting a
reference mission or `TEMPLATE.md` into your own document as a quoted
example no longer satisfies the required-heading check. If lint now
rejects a ticket or mission that used to pass, move the real heading out
of the code fence.

v0.19.0 makes an unknown `kb-context` tag a lint error. A block's tags are
derived from the documents your refs pin — `kb context new` fills them in
itself, so you never choose one. Passing `--tags` still works, but every tag
must already be published by some document on the hub; run `kb tags` to see
the real list. This check only fires once the hub federation actually
resolves, so it can be green on a machine where the hub mirror is empty or
unreachable and then turn red in CI, where the real hub resolves and the
same tag turns out unknown — a clean local lint is not a guarantee.

The `ba-ticket-author` skill still asks you for tags when it calls
`kb context new`. Anything you give it is validated against the hub and
**replaces** the derived set outright, so answering "none" and letting the
tags be derived instead is safe — and is the recommended answer.

If lint now rejects a ticket or mission that used to pass, check the error
message first: when it suggests a close match, that is almost always a
typo — correct the tag's spelling in the block's `tags:` line to match it,
which is just as safe for provenance since it touches neither `refs:` nor
`version:`. Otherwise, delete the tag from the block's `tags:` line —
nothing but this lint check reads them, so removing one is safe, and
removing the last one drops the line entirely, which parses fine. Either
way, **never re-run `kb context new`** to clear the error, since doing so
rewrites `version:` to today's HEAD and falsifies when the ticket was
grounded. Leave `refs:` and `version:` exactly as they are.

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
- `kb usage note --ticket <id> --phase <p> --model <m> --tokens-in N --tokens-out N --assistant <name>`
  — record a row by hand. Rows entered this way are estimates unless
  `--measured` is given. It always **appends** a new row, so it is never
  the way to fix one the automatic attribution got wrong — using it that way
  double-counts the tokens. The real repair is editing the stored row
  directly in `.kb/usage/<ticket>.jsonl`, then re-running `kb usage report`.
  If you already re-ingested the transcript, `--ticket` on
  `kb usage ingest-transcript` cannot help either: every row's uuid is
  already recorded, so there is nothing left for it to move.

A row is attributed to whichever ticket file the session mentioned most
recently (`tickets/<id>.md`, `missions/<id>.md`,
`docs/impl/<id>-{design,plan}.md`). Work done before any ticket file is
mentioned lands in `_unattributed.jsonl` — a large bucket there means
attribution is missing work, not that the work was free.

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
with it. Some steps in writing a ticket are judgment and some are mechanical;
running both on the same model pays the judgment price for the mechanical half.

| Tier | Steps |
| --- | --- |
| Strong | intake, pinning refs with `kb context new`, writing the acceptance criteria, and the maturity review |
| Cheap | the `kb ticket lint` fix loop up to `DoR: PASS` |

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

- `kb init --kind ba` — scaffold or refresh this repo
- `kb ticket lint <file> [--hub <url>]` — run the DoR gate locally
  before opening a PR
- `kb mission lint <file> [--hub <url>]` — run the mission DoR gate
  locally before opening a PR
- `kb ticket check <file> [--missions-dir <dir>] [--heading <h2>] [--hub <url>]`
  — run the SA grounding gate: every id in `## Technical grounding` must
  exist in the hub's `<repo>-code` document, every `[NEW: D<n>]` must name a
  `DECIDED` row of the parent mission's `## Technology decisions`
  (`--missions-dir`, default the sibling `missions/`), and `Open decisions`
  must be empty (`Grounding: PASS`). `--heading "## Services & order"`
  checks a mission plan's SA section against its own table
- `kb tags [--hub <url>]` — list every tag published on the hub, i.e. the
  tags a `kb-context` block may carry
- `kb doctor --hub <url>` — check the hub is reachable and
  `.kb/config.yaml` is valid (some diagnostics assume a `child`-style
  local KB and don't apply here — safe to ignore for a `ba` repo)
- `kb usage report [--ticket <id>] [--md]` — token and cost totals for this
  repo's tickets
- `kb usage ingest-transcript <path>` — backfill usage from a Claude Code
  transcript
- `kb mcp-setup [--hub-url URL] [--token T] [--no-verify]` — write the hub's
  HTTP MCP credentials into `.env` and verify them. Re-run it bare to verify
  again without retyping anything.
  (in your assistant: `/kb-mcp-setup`; prefer the hidden prompt or
  `STRATA_KB_HTTP_TOKEN` over `--token` — it puts the token in your shell
  history)
