# CENTER-KB Quickstart (dev repo)

This repo is a **product code** repo: it consumes the shared knowledge base
while implementing BA tickets, and it publishes generated knowledge about
its OWN source code (`<repo_id>-code`) back to the hub automatically —
`.github/workflows/kb-code.yml` runs `kb code-ingest` → `kb build` →
`kb ci-publish` on every push to `main` or `master`. Curated service
knowledge (`<repo_id>-svc`) is not available yet: that needs Stage C
(`dev-code-seed`, `kb svc note`). This repo never ingests documents from
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
   `<repo_id>-code` on every push to `main` or `master`; curated
   `<repo_id>-svc` knowledge still needs Stage C (`dev-code-seed`,
   `kb svc note`).
   Whether the hub PR `kb ci-publish` opens for `<repo_id>-code` then
   auto-merges is a **hub-side branch-protection/labeling policy** — not
   `kb-code.yml`'s own behavior — so ask the hub maintainer whether (and
   how) auto-merge is configured for this repo's PRs. It is safe to
   automate because `-code` is deterministic and LLM-free by
   construction. `<repo_id>-svc` PRs are never auto-merged: that
   document is LLM-drafted and always needs a human review before it can
   publish.
4. **Connect the shared MCP server** — set two environment variables so
   your AI assistant can reach the hub's search/citation tools:
   - `CENTER_KB_HUB_URL` — e.g. `http://kb-hub.example.com:8321`
   - `CENTER_KB_HTTP_TOKEN` — the hub token (ask the hub maintainer)
   `.mcp.json` (Claude Code) and `.cursor/mcp.json` (Cursor) are already
   wired to these two variables — nothing else to configure.
5. **Open this repo** in Claude Code, GitHub Copilot Chat, or Cursor — the
   `dev-implement-ticket`, `dev-design`, `dev-plan`, `dev-execute`, and
   `dev-handover` skills/commands/prompts are scaffolded for all three.

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

State is derived from those two files plus the current git branch and
whether a PR is open — never from conversation history — so any phase can
resume cold in a brand-new session. `kb init` never touches your
`docs/impl/` content: it only ever adds `docs/impl/.gitkeep` so the
directory exists before your first ticket does.

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

## Upgrading

Re-run `kb init --kind dev` to pick up new templates. This only ever
touches **scaffold files** — the skill/command/prompt wrappers,
`QUICKSTART-DEV.md`, `.github/workflows/kb-code.yml`, and the
`docs/impl/.gitkeep` marker — and only overwrites one when its content
differs from the new template; `.kb/config.yaml` and `.kb/index.yaml` are
never touched either way (the one exception being an explicit `--force`,
which overwrites them too). Anything you authored under `docs/impl/` is not
scaffolding: `kb init` never reads, writes, or overwrites it.
**If you hand-edited a wrapper, `kb-code.yml` (including any `--db` flags
you added), or QUICKSTART-DEV.md, back it up first: your edits are lost.**

## CLI reference

- `kb init --kind dev` — scaffold or refresh this repo
- `kb resolve <file> [--hub <url>]` — resolve a ticket's `kb-context`
  block and report freshness (ok/stale/broken)
- `kb get <doc-id> <section> [--level l3]` — fetch one section at a given
  level, escalating past the summary when a value must be encoded exactly
- `kb query "<text>"` — hybrid search over the hub's summaries
- `kb doctor --hub <url>` — check the hub is reachable and
  `.kb/config.yaml` is valid
