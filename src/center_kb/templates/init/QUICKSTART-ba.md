# CENTER-KB Quickstart (BA repo)

This repo is a **requirements** repo: it reads the shared knowledge base
to ground tickets in cited, versioned facts, and it versions the tickets
themselves under `tickets/`. It never ingests, summarizes, or publishes
KB content — that happens in `child` repos, reviewed on the `hub`.

## Setup once

1. **Install** — `pip install center-kb` (or clone this repo if someone
   already scaffolded it; otherwise `kb init --kind ba` in an empty
   folder creates it).
2. **Point at the hub** — fill `hub:` in `.kb/config.yaml` with the main
   hub's git URL or path. Used by `kb ticket lint` and `kb query`.
3. **Connect the shared MCP server** — set two environment variables so
   your AI assistant can reach the hub's search/citation tools:
   - `CENTER_KB_HUB_URL` — e.g. `http://kb-hub.example.com:8321`
   - `CENTER_KB_HTTP_TOKEN` — the hub token (ask the hub maintainer)
   `.mcp.json` (Claude Code) and `.cursor/mcp.json` (Cursor) are already
   wired to these two variables — nothing else to configure.
4. **Open this repo** in Claude Code, GitHub Copilot Chat, or Cursor —
   the `ba-ticket-author` skill/command/prompt is scaffolded for all
   three.

## Create a ticket

5. **Draft** — invoke `/ba-ticket-author` (or the `ba-ticket-author`
   skill) with the business need. It runs the pipeline for you:
   1. **Intake** — you describe the need: capability, role, value.
   2. **Ground** — it calls `kb_search`; review ALL candidates it shows
      you and pick the ones that actually apply.
   3. **Draft** — it fills the ticket template (story, ACs, use cases,
      sequence + business-flow diagrams), citing `doc-id §section` for
      every claim that touches a standard.
   4. **Pin** — once you confirm which sections apply, it calls
      `kb_context_new` and embeds the returned `## KB context` block.
   5. **Lint** — it runs `kb ticket lint` and fixes errors until it
      reports `DoR: PASS`.
   6. **Review** — it writes the draft to `tickets/<ticket-id>.md`. You
      review it, commit it, and paste it into Jira yourself — the
      assistant never publishes for you.

## DoR rules (what CI enforces)

Every pull request touching `tickets/**.md` runs
`.github/workflows/kb-ticket-lint.yml`, which runs `kb ticket lint`
against each changed ticket:

- Required sections present (Summary, User Story, Background,
  Acceptance Criteria, Use cases, both Mermaid diagrams, KB context,
  Definition of Ready).
- Every `## KB context` ref resolves at its pinned hub commit — no
  broken, malformed, or stale refs.
- Every inline `doc-id §section` citation is backed by a pinned ref
  (and vice versa) — citations and pins must agree.

What lint does **not** enforce — still the BA's judgment call:
- Whether an Acceptance Criterion that touches a standard actually has
  a citation (warning, not error).
- The business quality of the story itself.

**Branch protection:** lint running in CI does not by itself block a
merge. On the BA repo's GitHub settings, require the `kb-ticket-lint`
check to pass before merging into the branch tickets land on.

## CLI reference

- `kb init --kind ba` — scaffold or refresh this repo
- `kb ticket lint <file> [--hub <url>]` — run the DoR gate locally
  before opening a PR
- `kb doctor --hub <url>` — check the hub is reachable and
  `.kb/config.yaml` is valid (some diagnostics assume a `child`-style
  local KB and don't apply here — safe to ignore for a `ba` repo)
