# Strata

**Knowledge Base as Code.** Strata turns large reference documents — standards,
regulations, internal specs, policy manuals, engineering handbooks, compliance
frameworks — into a layered knowledge base that humans review in a pull request
and AI agents query for exactly the passage they need.

Nothing about Strata is tied to a domain or an industry. If your organisation
has documents too long for anyone to re-read on demand, Strata is for those
documents.

- **No database, no runtime state.** The knowledge base is `.yaml` and `.md`
  files in Git. Review it the way you review code.
- **Tables are never rewritten by an AI.** They are machine-copied from the
  source and automatically diffed against the original on every build.
- **A query loads a slice, not a corpus.** Typical lookups return 1–4 sections
  instead of a whole document — a few sections' worth of tokens per call, not
  the document's.

```bash
pip install strata-kb
kb init --kind hub
kb ingest source/employee-handbook.pdf --id hr-handbook --tags hr,policy
kb build
kb query "parental leave eligibility"
```

---

## Table of contents

1. [The problem](#1-the-problem)
2. [Four layers: L0 → L1 → L2 → L3](#2-four-layers-l0--l1--l2--l3)
3. [Repo kinds](#3-repo-kinds)
4. [Installation](#4-installation)
5. [The lifecycle](#5-the-lifecycle)
6. [Command reference](#6-command-reference)
7. [Authoring a document](#7-authoring-a-document)
8. [Searching](#8-searching)
9. [The hub and federation](#9-the-hub-and-federation)
10. [MCP server and Web UI](#10-mcp-server-and-web-ui)
11. [Citations that pin a version](#11-citations-that-pin-a-version)
12. [BA repos — tickets and missions](#12-ba-repos--tickets-and-missions)
13. [Dev repos — code knowledge](#13-dev-repos--code-knowledge)
14. [Reviewing content](#14-reviewing-content)
15. [Configuration](#15-configuration)
16. [Exit codes](#16-exit-codes)
17. [Troubleshooting](#17-troubleshooting)
18. [FAQ](#18-faq)
19. [Development and release](#19-development-and-release)

---

## 1. The problem

Long reference documents share two traits, whatever the field:

| Trait | Why it hurts |
|---|---|
| **Hundreds of pages** | Nobody — human or model — re-reads the whole thing to answer one question. Pasting it into a prompt is slow and expensive; doing it on every question is untenable. |
| **Detail that matters character-by-character** | Codes, field lengths, thresholds, identifiers. Summarise those into prose and a single miscopied character silently becomes wrong data in whatever depends on it. |

Strata attacks both at once:

- **Split by section**, so a lookup lands on the right passage instead of the
  right document.
- **Tables never pass through a model.** Code extracts them verbatim, and
  `kb build` diffs every summary table against the original. A table that was
  altered, dropped, duplicated, reordered or invented fails the build and
  blocks the change — in both directions.

---

## 2. Four layers: L0 → L1 → L2 → L3

Think of a library lookup stack, coarse to fine: department catalogue → table of
contents → chapter summary → full text.

| Layer | Name | What it holds | Typical size |
|---|---|---|---|
| **L0** | Master catalogue | One `index.yaml` listing every document: id, revision, tags, one-line description | Hundreds of tokens for the whole store |
| **L1** | Detailed contents | Per document, a `_manifest.yaml` listing each section: id, title, a ≤ 25-word summary, status | Tens of thousands of tokens per document |
| **L2** | Condensed summary | `.md` — prose condensed to ~20–30% of the original, **in the source document's language**, tables kept verbatim | Medium |
| **L3** | Full original | `.raw.md` — full extracted text, nothing cut | Largest |

A lookup walks L0 (which documents matter) → L1 (which sections matter — almost
free) → L2 (condensed content of the few relevant sections). L3 is opened only
when absolute fidelity is required. That is where the token saving comes from:
the model never loads what it did not need.

**Example — a section at L1 and L2.**

L1, one search-oriented line in the manifest:

> Defines the Record Type field identifying whether a record is standard or
> tailored, per Table 4-1, 1 alpha character.

L2, condensed prose in the `.md`:

> The Record Type field identifies whether a record is a standard record or a
> tailored record, per the encoding in Table 4-1. Used on all records; length 1
> character; alpha.

Immediately below it sits Table 4-1, copied verbatim — never rewritten, because
code extracted it straight from the source.

**The non-negotiable rule:** an AI may write the prose *around* tables. The
tables themselves are always machine-copied at both L2 and L3, and
`kb build` verifies it. Whitespace and alignment differences are normalised
(NBSP, tabs, trailing spaces, `:--` alignment rows); everything else is compared
byte for byte.

---

## 3. Repo kinds

`kb init` asks which of four kinds a repo is and scaffolds accordingly, recording
the choice as `kind:` in `.kb/config.yaml`. Non-interactive runs pass
`--kind hub|child|ba|dev`.

| Kind | Purpose |
|---|---|
| **`hub`** | Central knowledge hub. Hosts `federation/` — the single source of truth for search — and runs the shared HTTP MCP server and Web UI. Receives publishes from every other repo; merging a hub PR is the gate that makes content searchable. |
| **`child`** | Authoring repo. Ingest documents → summarize → `kb build` → `kb publish` to the hub. Points `hub:` at the hub. Does not host the shared service. |
| **`ba`** | Requirements repo. Drafts Dev-ready tickets — and, for large features, epic-level mission plans — grounded in the KB, versioned under `tickets/` and `missions/` and gated by CI Definition-of-Ready checks. Never ingests or summarizes KB content; it publishes only its own plan (`<repo_id>-plan`, from the ready missions and tickets) to the hub. |
| **`dev`** | Product code repo. Implements BA tickets grounded in the KB through a five-command agent workflow. Never ingests outside documents; it publishes knowledge about *its own source code* — generated (`-code`) and curated (`-svc`). |

**Hub kinds.** On the hub every repo files under one of three kinds, recorded
in its `_meta.yaml` and shown as a menu in the Web UI (section 10): `hub` and
`child` publish **`kb`** (the **Document** menu), `ba` publishes **`ba`**
(**Ticket**) and `dev` publishes **`dev`** (**Code**). A repo has exactly one
kind, fixed by `kb init --kind`; the mapping is not configurable. `kb publish`
refuses a repo whose kind is not recorded in `.kb/config.yaml` (run
`kb init --kind <child|ba|dev|hub>`) and prints `kind: <kind> → hub menu: <menu>`
before it sends anything.

Re-running `kb init` refreshes scaffold files (skills, templates, workflows) and
preserves `.kb/index.yaml` and `.kb/config.yaml` unless `--force`, and merges
`.claude/settings.json` in `ba` and `dev` repos (your entries stay; `--force`
replaces it; hub and child repos have none). `--lang <id>` (dev, repeatable) forces a conventions pack whose
manifest is not detectable; `--assets none|s3` (hub) records the asset store.

Slash commands are scaffolded for **Claude Code, GitHub Copilot and
Cursor**: `/kb-ingest`, `/kb-summarize`, `/kb-approve`, `/kb-publish`,
`/kb-docker-setup` on hub and child repos; `/ba-ticket-author`,
`/ba-mission-plan`, `/ba-bug-report`, `/ba-answer-questions`, `/sa-ticket-ground`,
`/kb-publish` (it publishes the plan) and `/kb-auto` on a `ba` repo; the five
dev-workflow commands, `/dev-fix-bug`, `/dev-sa`, `/dev-test-workflow` and `/kb-auto` on a `dev` repo. MCP client wiring ships as
`.mcp.json` (Claude Code) and `.cursor/mcp.json` (Cursor) on every kind —
stdio on the hub, HTTP-with-env-vars everywhere else.

---

## 4. Installation

### Requirements

- **Python 3.11+**
- **Git.** Version **2.31 or newer** on any machine whose hub URL carries a
  credential (the `https://x-access-token:<token>@github.com/org/repo.git`
  shape the CI templates pass in `STRATA_KB_HUB`). The token is kept out of the
  clone's git config and handed to git through `GIT_CONFIG_COUNT`, which git
  added in 2.31; older versions ignore it silently and every hub command fails
  with git's own authentication error. `.kb/config.yaml` is committed, so never
  put a token in `hub:` — pass a credentialed URL in `STRATA_KB_HUB`, which
  overrides the file.
  Debian 11 (git 2.30.2) and Ubuntu 20.04 (2.25.1) are both below the floor. An
  ssh `hub:` (`git@…`), a public `https://` hub and a `hub:` pointing at a local
  directory carry no credential and need no particular git version.

### From PyPI

```bash
pip install strata-kb            # kb CLI + MCP server
pip install "strata-kb[ingest]"  # + PDF ingestion (docling)
pip install "strata-kb[embed]"   # + semantic search
pip install "strata-kb[server]"  # + HTTP MCP/Web UI auth
pip install "strata-kb[code]"    # + routes, pages, jobs and symbols in `kb code-ingest` (tree-sitter, about 184 MB)
pip install "strata-kb[s3]"      # + S3 asset offloading
```

### From source

```bash
git clone https://github.com/vuonglq01685/strata-kb
cd strata-kb
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[ingest,dev]"
kb --help
```

Re-activate the virtualenv (`source .venv/bin/activate`) in every new terminal.

### Docker

`kb docker-setup` (or `/kb-docker-setup`) prepares a repo: on a hub it writes
`.env`, generates `STRATA_KB_HTTP_TOKEN` and runs `docker compose up -d`; on a
child it pulls the ingest image so ingestion needs no local Python. A `ba` or
`dev` repo needs neither Docker nor this step.

```bash
docker compose up -d
docker compose run --rm hub kb ingest source/handbook.pdf --id hr-handbook
```

Release tags publish to PyPI and push `ghcr.io/vuonglq01685/strata-kb`.

### Windows

Fully supported — every release is gated on `windows-latest`. `kb` forces UTF-8
on stdin/stdout/stderr at startup on every OS, so piped I/O stays UTF-8 even
under a non-UTF-8 console locale.

Deep KB trees can exceed the legacy 260-character path limit. If you hit
`FileNotFoundError` on long paths, enable long paths once:
`git config --global core.longpaths true`, and set
`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`.

---

## 5. The lifecycle

```
   Source document (PDF)
          │
          │  kb ingest                    machine, no AI
          ▼
   Split into sections, each with a stable id
          │
          ├─ L3 written immediately (full original)
          ├─ L2 scaffolded (tables present, summaries blank)
          └─ L1 manifest written, every section status = pending
          │
          │  kb summarize                 AI fills the blanks
          ▼                               (runs inside kb ingest by default)
   L2 prose + L1 one-liners written, status → summarized
          │
          │  kb build                     machine gate, cannot be skipped
          ▼
   ✓ nothing still pending      ✓ every L2 table matches L3
   ✓ quality rules              ✓ token counts refreshed
          │
          │  Pull request                 HUMAN review
          ▼
   A subject-matter expert reads the diff and edits what is wrong
          │
          │  merge → kb publish           mirror to the hub
          ▼
   A pull request on the hub. Merging it is the single gate that
   makes content live.
          │
          │  kb query / MCP / Web UI
          ▼
   The 1–4 most relevant sections, with citations
```

Machines do the mechanical work (sectioning, verbatim tables, integrity checks).
AI does the language work (summaries). Humans sign off. No step skips the check
that follows it.

---

## 6. Command reference

| Command | Purpose |
|---|---|
| `kb init` | Scaffold or refresh a KB repo of a given kind. On a hub (`--kind hub [--yes]`) it also records the hub kind of registry entries that lack one — see [Registry kinds](#registry-kinds-and-the-1200-upgrade) |
| `kb docker-setup` | Prepare the repo for Docker (hub: `.env` + token + start; child: pull image) |
| `kb mcp-setup` | Write the hub's HTTP MCP credentials into a reader repo's `.env` and verify them |
| `kb ingest` | Parse a PDF, split into sections, write L3 and scaffold L1/L2 |
| `kb summarize` | Fill pending L1/L2 summaries via a headless LLM CLI |
| `kb authored` | Tag a hub doc `authored` (markdown is the master; `kb ingest` refuses it) |
| `kb code-sync` | Hub only. `scan` lists hub docs that name code that changed since the baseline (`--md`, `--json`, `--baseline <sha>`; exit `0` nothing, `2` findings, `1` error); `issue [--json]` finds the hub job's own `kb-code-sync` issue among the open ones (needs `gh`; exit `0` a usable one, `2` none, `1` error); `baseline [--at <sha>]` records the commit the sync is current at; `run [--issue] [--loop]` is the `hub-sync` job: one scan, optionally the `kb-code-sync` issue update, optionally forever |
| `kb user` | Hub only. Accounts for the hub web UI, stored in `<hub root>/.kb-auth/users.db`. `add <username> --role admin\|ba\|dev` and `passwd <username>` prompt for the password twice; `role <username> <role>`; `remove <username>`; `list` (never prints hashes); `hash` prints a password hash for `STRATA_KB_BOOTSTRAP_PASSWORD_HASH` and touches no database. All but `hash` take `--kb` (default `.kb`). The last admin cannot be removed or demoted: one line on stderr, exit `1` |
| `kb status` | List sections still pending summarization |
| `kb build` | Validate the store: no blanks, table integrity, quality rules, token counts |
| `kb approve` | Mark sections reviewed (`summarized` → `reviewed`) |
| `kb query` | Hybrid search (FTS5 keyword + semantic KNN, RRF-fused) → L2 within a budget |
| `kb get` | Fetch exactly one section at a chosen level |
| `kb stats` | Token size per level, per document |
| `kb tags` | List every tag published on the hub federation |
| `kb publish` | Mirror `.kb/` (L0→L3) to the hub's `federation/<repo-id>/` and rebuild the index; `--branch <name>` (hub self-publish only) commits the mirror on that checked-out branch and opens or reuses its PR |
| `kb ci-publish` | Publish from a child's or `ba` repo's GitHub Actions job via OIDC, no secrets |
| `kb reindex` | Rebuild `federation/index.yaml` when it has drifted |
| `kb doctor` | Store health check; `--context` also checks citation staleness. A `child`, `ba` or `dev` repo with `kb mcp-setup` done checks the hub over its MCP, no hub clone, and fails when its strata-kb (installed, or pinned in `.github/workflows/`) is not the hub's version |
| `kb context new` | Generate a `kb-context` citation block pinned at the hub's current commit |
| `kb resolve` | Resolve a `kb-context` block — sections at the pinned version, plus freshness |
| `kb diff` | Diff added/removed/changed sections between the worktree and a git rev |
| `kb code-ingest` | Extract a codebase's structure into `.kb/<repo_id>-code/` — deterministic, no LLM |
| `kb plan-ingest` | Build `.kb/<repo_id>-plan/` from the ready missions and tickets of a `ba` repo — deterministic, offline, no LLM |
| `kb svc note` | Record which tickets touched which service in `<repo_id>-svc` |
| `kb ticket lint` | Definition-of-Ready gate for a BA ticket |
| `kb ticket check` | SA grounding gate: every id in `## Technical grounding` exists in the hub's `<repo>-code` document |
| `kb ticket export` | The ticket for the tracker: guidance comments, `## Definition of Ready` and `## Review record` dropped |
| `kb ticket fetch` | A ticket from the hub by id (`<id>` or `<repo>:<id>`), restored to its source shape with a provenance line; writes `docs/impl/<id>/ticket.md` (`--out` to change), always overwriting; `1` if the id is not on the hub or several repos hold it |
| `kb ticket stale` | Every ticket and mission whose citations the hub moved since they were pinned (`--md` / `--json`); `0` current, `2` stale only, `1` broken |
| `kb mission lint` | Definition-of-Ready gate for a BA mission plan |
| `kb mission next` | Which story next: done / ready / draft / to-draft / blocked across `missions/`, done derived from the hub's `<repo>-svc` history, ready and draft from the ticket's Definition of Ready checklist |
| `kb mission next --from-hub` | The same report from the hub's published `<ba-repo>-plan` alone, with no `missions/` or `tickets/` (`--repo <ba-repo>` to pick one); a published ticket is `ready`, and `to-draft` reads `not ready (no published ticket)`; MCP `kb_mission_next` gives the same report |
| `kb ticket tidy` | Move flat `tickets/*.md` into `tickets/<mission-id>/` by their `> Parent mission: M-x [@ rev N]` line; `--into <folder>` for the rest |
| `kb impl tidy` | Move flat `docs/impl/<id>-{design,plan,context}.md` and `<id>-review/` into `docs/impl/<id>/`; never overwrites |
| `kb pr lint` | Check a pull-request description carries its evidence |
| `kb pr find\|view\|open\|checks\|merge\|edit` | Pull requests over the GitHub REST API (`gh api`), JSON keys as in `gh pr --json`; what the skills call instead of `gh pr`, which GraphQL-blocked Claude Code cloud cannot run |
| `kb plan waves` | Dependency waves of a dev plan: which tasks can run in parallel lanes; errors on a shared file without a dependency, a cycle, a missing `Depends on:` line, or an empty `Serial resource:` line; tasks with a `Serial resource:` line print after `serial:` and run one at a time |
| `kb assets` | Asset store operations on a hub: `migrate`, `verify` |
| `kb usage` | Token/cost measurement: ingest transcripts, record rows, render a report |
| `kb auto` | Full-auto mode for `ba` and `dev` repos. `on` / `off` flip the `auto:` switch in `.kb/config.yaml` (`on` prints the admin-merge warning first); `status [--json]` shows the switch and the runner's task, attempts, waiting questions and stop reason; `run [--once] [--hub URL]` runs the loop (exit `0` done, `2` stopped, `1` refused); `wait [--max 6600] [--interval 30]` blocks until the loop ends or changes. See [Full-auto mode](#full-auto-mode) |

`kb usage` records what each ticket cost from Claude Code's own transcripts,
subagents included (`Stop` + `SubagentStop` hooks, scaffolded by
`kb init --kind ba|dev`). Prices come from a packaged list-price table that a
repo can override per model in `.kb/usage-prices.yaml`; a model with no row
is reported `unpriced`, never guessed. Fast-mode calls are priced at the
standard rate and flagged, so a total that contains them is a lower bound.

| Subcommand | Purpose |
|---|---|
| `kb usage ingest-transcript <file>` | Append a transcript's API calls (and its session's subagents) to `.kb/usage/<ticket>.jsonl`. `--hook-stdin` reads the hook payload and never blocks a turn; `--ticket <id>` forces the attribution |
| `kb usage note --ticket --phase --model --assistant --tokens-in --tokens-out` | Append one row by hand — for an assistant with no hook, or to repair an attribution. `--cache-read`, `--cache-write-5m`, `--cache-write-1h`; `--est` (default) or `--measured` |
| `kb usage report` | Aggregate per ticket · phase · model · actor · main vs subagents, with the unattributed share. HTML at `.kb/usage/report.html` (`--out`), or `--md` / `--json` to stdout; `--ticket <id>` for one ticket; `--with <other .kb>` adds another repo's ledger (e.g. the BA repo's) to price a ticket end to end; `--summary` prints the short `## Usage` block a PR body carries |

---

## 7. Authoring a document

### `kb ingest`

```bash
kb ingest source/employee-handbook.pdf \
  --id hr-handbook \
  --tags hr,policy,benefits \
  --revision "2026 edition" \
  --sections 4
```

| Flag | Meaning | Required |
|---|---|---|
| `PDF` (positional) | Path to the source document | yes |
| `--id` | Short document id, e.g. `hr-handbook` | yes |
| `--tags` | Comma-separated labels used to pre-filter search | no |
| `--revision` | Edition label — appears in every later citation | recommended |
| `--sections` | Only process these chapters (`4,5`); empty = whole document | no |
| `--chapter-pattern` / `--appendix-pattern` / `--attachment-pattern` | Heading regex overrides for pattern splitting (defaults `Chapter N` / `Appendix X` / `Attachment N`; remembered between runs) | no |
| `--no-bookmarks` | Ignore the PDF outline and split by heading pattern instead | no |
| `--no-summarize` / `--llm none` | Skip the automatic summarize pass | no |

By default the split follows the PDF's own **bookmarks/outline**, so parts are
named after the document's own structure (`APPENDIX N` → `appendix-N`,
`ATTACHMENT N` → `attachment-N`, front matter, and so on). `--no-bookmarks`
falls back to heading patterns, buckets everything before the first chapter into
`front-matter`, and gives unparseable headings readable slug ids from their
titles.

The split needs no AI. It takes seconds to tens of minutes depending on document
length; the first run is slower because a page-layout model (~500 MB) is
downloaded and cached.

**Images.** Every embedded picture is saved once as a content-addressed file at
`.kb/<id>/assets/<sha256>.png` (icons) or `.webp` (larger figures), so identical
bytes never duplicate across re-ingests. Descriptions are never generated — they
come from the source, preferring the image's own caption and falling back to OCR
of text baked into the image. L3 carries `![description](assets/<sha256>.<ext>)`;
L2 carries the same description as a `Figure: <description>` line so it is
searchable.

**Re-ingest.** Without `--sections`, ingesting an existing `--id` is a full
replace: every `.md` of that document is deleted before the new split is
written. With `--sections 6`, only chapter 6's files and manifest entries are
rewritten — every other chapter, including reviewed summaries and their status,
is untouched. A `--sections` value matching no heading **deletes** that chapter,
and the report says so.

The report names every sectioning decision, so nothing is silent: headings
demoted to text, fallback ids, numbered headings that arrived out of order,
duplicate ids renamed `<id>-2`, bookmarks the split missed, sections the outline
does not name, and the L3 token distribution.

### `kb status`

```console
$ kb status
hr-handbook: 12/325 section pending
  - §4.12 Parental leave (file: ch4-benefits.md)
  - §4.13 ...
Total: 12 section pending.
```

### `kb summarize`

The only AI step. `kb ingest` runs it automatically right after scaffolding,
calling a headless LLM CLI (`claude` → `copilot`, auto-detected on `PATH`; pin
one with `--llm`). Re-run or retry anytime with `kb summarize`.

With no LLM CLI installed, sections stay `pending` — open your agent and run
`/kb-summarize` as the manual fallback: it reads `kb status`, fans pending
sections out to parallel read-only sub-agents (~5 sections each, 10 at a time),
and merges their output under fixed style rules.

Rules baked into the recipe:

- **Write in the source document's language.** Never translate — a summary in a
  different language shares no vocabulary with its L3 source, and keyword search
  stops matching.
- **Never rephrase** codes, field names, numbers, units or cross-references.
- **Never touch existing tables.**
- If unsure, keep the original wording. Do not invent.

Useful flags: `--redo [--section <id>] [--include-reviewed --yes] [--dry-run]`
re-runs over sections that already have a summary (`--redo --all` for the whole
store; reviewed sections are skipped unless `--include-reviewed`).
`--print-prompt` prints the prompt a section would get, for the manual path.
`--max-workers <n>` sets the parallel LLM calls (default `llm.max_workers` in
`index.yaml`).
Sections with ≤ 200 characters of prose are copied verbatim without an LLM call.

### `kb build`

```console
$ kb build
kb build: OK
```

```console
$ kb build
[error] hr-handbook §4.12: L2 table does not match L3 table
```

Three checks, the third warn-only unless `--strict`:

1. **No leftover `TODO` markers or empty summaries.**
2. **Every L2 table matches its L3 original exactly** — the main safety latch.
3. **Quality rules:** L2 prose ≤ 35% of L3 prose (floor 120 chars); no L2
   sentence quoting ≥ 4 cells of its own table; no uppercase code in L2 absent
   from L3; ≥ 45% of L2 words present in L3 (measured only at ≥ 20 words); L1
   ≤ 25 words; L0 summary ≤ 30 words; table-only and brief sections carry their
   fixed labels; every `index.yaml` summary filled. Reported as
   `[warn] … (quality)` by default; `--strict` makes them errors.

`kb build` also fails when a section's L3 changed after it was summarized
(`l3_sha256`) or its L2 changed after approval (`reviewed.l2_sha256`), and it
never writes `_manifest.yaml` while reporting an error.

While summarization is still in progress, `kb build --allow-pending` validates
the finished parts without failing on the unfinished ones. In a `dev` repo,
`kb build` and `kb doctor` regenerate `<repo_id>-code` first; `--no-refresh`
checks it as it is.

### `kb approve`

Requires a clean `.kb/<doc>` tree and a passing `kb build --strict`. Records
`reviewed: {by, at, l2_sha256}` per section (`--by 'name <email>'` overrides the
git identity). `kb publish` and `kb ci-publish` warn how many sections ship
unreviewed; `--require-reviewed` makes that fatal. Slash command: `/kb-approve`.

---

## 8. Searching

### `kb query`

```console
$ kb query "parental leave eligibility" --tags hr --budget 400
--- [ops:hr-handbook §4.12 (2026 edition)] match=keyword ~246tk
## 4.12 Parental leave

An employee becomes eligible for paid parental leave after 12 months of
continuous service. Entitlement is calculated per the table below.

| Service       | Paid weeks | Unpaid weeks |
|---------------|------------|--------------|
| 12–24 months  | 8          | 4            |
| 24+ months    | 14         | 4            |
```

| Flag | Meaning |
|---|---|
| `TEXT` (positional) | The question or keywords |
| `--tags` | Only search documents carrying these tags (document-level pre-filter); a document id is also accepted as a tag. |
| `--budget` | Maximum tokens returned. **Advisory:** the first result is always returned whatever its size, and sections are never cut mid-way — that is what keeps tables verbatim. |
| `--semantic` | Force semantic search; warns clearly when embeddings are unavailable |
| `--kind` | Only search one kind of repo: `kb` (Document), `ba` (Ticket) or `dev` (Code). Repeatable; omit for all kinds, exactly as before. An unknown value is an error, never ignored |

Every result carries a citation of the form `<repo-id>:<doc-id> §<section> (<revision>)`
— e.g. `ops:hr-handbook §4.12 (2026 edition)` — so the federation repo, document
and revision are never ambiguous.

Under the hood: filter by tags at L0 (nearly free) → rank with a persistent
hybrid index (SQLite FTS5 keyword search + optional semantic KNN, fused with
RRF) → load L2 content of the top hits until the budget is reached. **No model
call happens during a lookup** — it is pure code, fast, and free.

`kb query`, MCP and the Web UI all read **only** the hub's `federation/`. The
local `.kb/` is a drafting desk; nobody queries it.

**Searching by kind.** The same filter is on every entry point: `kb query --kind
dev --kind kb`, MCP `kb_search(..., kinds=["dev", "kb"])` and REST
`/api/search?q=…&kind=dev&kind=kb` (an unknown value answers `400` with error
code `unknown_kind`; the CLI and MCP print the error instead). Each REST
`/api/search` result, and each entry of `/api/docs`, carries its `kind`. A kind
filter narrows the candidates before ranking, so a menu search in the Web UI can
list more hits than the kind chip of the top search shows: the chip only filters
the one budgeted search the top box ran.
The agent skills pass the kind they need: BA skills search `--kind kb --kind
dev`; `dev-implement-ticket` searches `--kind dev` for its own code (plus
separate `--kind ba` and `--kind kb` lookups); `sa-ticket-ground` searches
`--kind dev`; `kb-code-sync` searches `--kind kb`.

### `kb get`

```bash
kb get hr-handbook 4.12 --level l2   # summary
kb get hr-handbook 4.12 --level l3   # full original
```

### `kb stats`

An illustration (not a measured corpus):

```console
$ kb stats
L0 index.yaml: 187 tokens
doc                  sections       L1         L2         L3   saving
hr-handbook               325    28486      23140      85669    73.0%
travel-policy               4      420        790       2722    71.0%
```

The `saving` column is L2-vs-L3 for that document as a whole. The quality rules
put L2 prose at no more than 35 % of L3 per section (`kb build --strict` fails
above it), so a healthy store saves at least ~65 % here. A query then loads 1–4
sections of L2, not all of it.

---

## 9. The hub and federation

One reference document usually matters to several repos. Rather than ingesting
and summarizing it once per repo, shared documents live as a single copy on a
central **hub**.

A hub is an ordinary Git repo with the same `.kb/` layout plus a
machine-generated `federation/` directory — a catalogue of catalogues. Each
participating repo mirrors its **full** `.kb/` (L0→L3) under
`federation/<repo-id>/`, alongside an aggregate `federation/index.yaml` listing
every document across every repo. A hub is not a long-running server; it is
still `.yaml` and `.md` files in Git.

### `kb publish`

Mirrors this store's `.kb/` into `federation/<repo-id>/` on the hub and rebuilds
the aggregate index. The hub comes from `.kb/config.yaml` (`hub:` + `repo_id:`);
`--hub`/`--repo-id` only override it.

| Mode | Behaviour |
|---|---|
| `--pr` | Open or update a pull request on the hub. Needs a git remote, and `gh` able to open a PR on that host. |
| `--direct` | Commit directly. Refused on a *governed* hub — one carrying a non-empty `federation/registry.yaml` — that has a git remote. |
| *(neither)* | It picks direct only for a hub with no git remote; for a remote hub it opens a PR, or refuses when `gh` cannot open one. |
| `--branch <name>` | Hub self-publish only (see [Code sync](#code-sync)). You must be on `<name>`. It mirrors `.kb/` into `federation/<repo-id>/`, commits on top of the branch (no `checkout -B`, no reset), pushes without force, and opens or reuses the PR. It refuses the default branch, direct mode, the intake route, and any case where no PR would open. |

A *governed* hub that `gh` cannot open a pull request on has no publish route
in this release — see "Known limitations" in [`CHANGELOG.md`](CHANGELOG.md) for
what is available instead.

Publish copies `.kb/` **artefacts only** — documents, indexes, manifests,
`assets/`. Anything else (`.kb/config.yaml`, dotfiles) is withheld with a
`[warn] … (allowlist)` line naming it, so a `config.yaml` someone put a
credential in never reaches the hub. It still sits in this repo's own history:
`kb doctor` warns when a tracked `config.yaml` carries one.

`kb ci-publish` is the CI route: it runs inside the child's (or `ba` repo's) own
GitHub Actions job, authenticates to an intake service with GitHub Actions OIDC, and needs no
secrets. Uploaded paths are capped at 110 UTF-16 code units so that
`federation/<repo-id>/<path>` stays inside a Windows client's `MAX_PATH`. A path
crossing the cap is refused with `400` and the whole upload fails.

### Registry kinds and the 1.20.0 upgrade

`federation/registry.yaml` entries carry the hub kind of each repo. An entry is
either a plain `repo_id` string (still valid, kind unknown) or a mapping
`{repo_id, kind, workflow?, auto_merge?}` with `kind` one of `kb`, `ba`, `dev`
(`auto_merge: true` makes the hub merge that repo's publish PRs itself; default
`false`; the Registry page writes it, see [Hub accounts and the Registry
page](#hub-accounts-and-the-registry-page)):

```yaml
repos:
  acme/handbook: {repo_id: handbook, kind: kb}
  acme/billing: {repo_id: billing, kind: dev}
  acme/billing-reqs: {repo_id: billing-reqs, kind: ba}
```

On a governed hub the registry decides the kind; the publisher's own kind is
only checked against it. Both the snapshot route (`kb publish`) and the intake
route (`kb ci-publish`) record the kind in the leaf's `_meta.yaml`. A repo whose
kind maps to something else than its registry entry (`child` or `hub` against
`kb` is fine; `ba` against `dev` is not) is refused: `kb publish` exits with
`kind mismatch: registry says '<kind>' for <repo>, this repo publishes as
'<kind>' — fix kind: in federation/registry.yaml or the repo's
.kb/config.yaml`, and the intake answers `403` with the same text. A registry
entry with no `kind` still publishes: the repo's own kind is recorded.

Leaves published before 1.20.0 have no recorded kind. They are not rewritten
and nothing moves under `federation/`: the kind is inferred when read (a
generated plan document, with a plan title and the `plan`/`generated` tags, is
`ba`; a `-code` or `-svc` document with the `code` tag is `dev`; anything
else is `kb`), so the Web UI and kind-filtered search are right immediately.
The kind is recorded on the repo's next publish that carries one (the registry
pin, or an upgraded publisher's own kind), even with unchanged content: that
publish opens one PR that only updates `_meta.yaml`.

**`kb init --kind hub`** on an existing hub fills in the missing registry kinds.
It proposes one per kind-less entry from what that repo has published, a
namespace holding nested leaves (a child hub) is proposed as `kb`, and it asks
for any entry with nothing published yet (or nothing readable) to infer from. It prints the diff
and asks before writing; `--yes` writes without asking, but exits `1` naming
the entries it cannot infer. It edits `registry.yaml` line by line, so comments
survive, and never commits: review the change and open the hub PR yourself. An
invalid `registry.yaml` makes it exit `1`.

**Upgrade order.** Upgrade the hub (and its intake service) first. Then upgrade every publisher that
reads the registry itself (local or direct `kb publish`, and child hubs) and
only then run `kb init --kind hub` and commit the registry: an older strata-kb
rejects a registry that has `kind:`. Publishers on the intake route are
unaffected. Old clients keep publishing meanwhile: the registry kind wins and the
leaf kind is inferred.

`kb init --kind hub` on a hub whose registry has kind-less entries asks to fill
them. Decline until the publishers are upgraded. A non-interactive run without
`--yes` prints a warning naming the entries, writes nothing and exits `0`, so automated hub upgrades keep working; re-run with `--yes` once the publishers are upgraded.

### Code sync

A hub document written by hand or ingested from a PDF (architecture, standards,
designs) goes stale when the `-code` / `-svc` documents it names change. Code
sync finds those documents and keeps them true, without an LLM in the daily job.

**Mark the documents.** A hub document whose markdown is now the master gets the
tag `authored`: `kb authored <doc>` (`--off` removes it). `kb ingest` then
refuses to re-ingest it, so a PDF can no longer overwrite the hand fixes.
`kb summarize --redo` stays allowed. A document tagged `code-sync-skip` is left
out of the scan. `kb code-sync scan` prints a `note:` for each hub document that
is not `authored`.

**Daily detection.** The `hub-sync` compose service runs
`kb code-sync run --issue --loop`: scan, update the issue, sleep. It never pulls,
commits or pushes (the `hub` service pulls `/data`). The scan compares the
`-code` / `-svc` documents between the baseline commit (`kb-code-sync.yaml` at
the hub root) and the tip of the default branch, and lists hub sections that
name something added, removed or changed. Same inputs give byte-identical output.
One issue labelled `kb-code-sync` stays open while there are findings: it is
created when they appear, rewritten only when the findings change, and closed
with a comment when the scan finds nothing. A scan error never closes it.

**Categories.** Every finding falls in one category, and the work order lists
them in this order: `removed` (code gone, prose likely wrong), `changed`
(facts changed, check and fix), `added` (new code, docs may need a mention),
`image` (the name sits in a picture's description; it may need a redraw).
`kb code-sync scan --json` gives each finding a `category` and a `counts` object.

**The job's issue.** The first line of the issue body is an identity marker
(`<!-- kb-code-sync work-order v1 scan:<sha> baseline:<sha> -->`) and the last
is the findings digest. `kb code-sync issue` lists the open `kb-code-sync`
issues and judges each one; `/kb-code-sync` works only from the one it calls
usable, and takes nothing from it: it scans from the baseline recorded in git,
which `kb code-sync issue --json` prints as `baseline_sha`. It never reads
issue text or comments and never edits, closes, comments on or relabels an
issue. The job in turn only rewrites or closes an issue that carries the
identity marker, so a labelled issue a person opened is left alone.

| Kind | Meaning | Used? |
|---|---|---|
| `current` | The job wrote it, its baseline is the recorded one, and a local scan gives the same findings | yes |
| `stale` | The job wrote it, but its baseline or findings differ from a local scan (the reason says which); a baseline moved by an earlier round lands here | yes, scanned from the recorded baseline |
| `duplicate` | The job wrote it, but a newer job issue exists | reported only |
| `foreign` | No identity marker, no digest, no baseline, or the baseline is not in the default branch's history | reported only |

**Sprint cadence.** Detection is daily. The hub manager runs `/kb-code-sync` in
their agent any time the issue is open; the skill re-runs the scan, judges each
finding (fix, no change needed, or needs the SA), edits the sections,
re-summarizes, runs `kb build --strict`, moves the baseline
(`kb code-sync baseline --at <scan sha>`), commits, and publishes with
`kb publish --branch kb-bot/code-sync`. That is one rolling pull request: later
runs merge the default branch into `kb-bot/code-sync` and add to it. At sprint
review (every two weeks) the SA or hub manager reviews the PR, may run
`kb approve`, and merges. The skill never merges and never approves. It ships to
hub repos only, as the standard four wrapper files (Claude Code skill and command, Copilot prompt, Cursor command).

**Prerequisites.**

| Need | Why |
|---|---|
| `origin/HEAD` set (`git remote set-head origin --auto`) | The scan reads the default branch's tip; a hub with a remote and no `origin/HEAD` exits `1` |
| GitHub App with `issues: write`, `pull_requests: read`, `contents: read` | `hub-sync` calls the issues REST API and reads the baseline from the hub repo. The intake App must have the permissions added and the installation re-approved by an org admin |
| `STRATA_KB_GH_TOKEN` | Token fallback, only when the App (`STRATA_KB_GH_APP_ID` / `STRATA_KB_GH_APP_KEY`) is not configured; it needs the same three permissions on the hub repo |
| `STRATA_KB_CODE_SYNC_INTERVAL` | Seconds between scans (default `86400`, minimum `60`) |
| `gh`, logged in, on the manager's machine | `kb publish --branch` and the PR title and body |

With no credentials, `hub-sync` still scans and logs the work order, logs one
line that the issue was not updated and why, and keeps running.

### Multi-tier federation

A `kind: hub` repo may itself declare `hub:` + `repo_id:`. Publishing such a repo
mirrors its **`federation/`** (not its own `.kb/`) into `federation/<hub-id>/`
upstream, keeping the nested layout (`federation/mid/repo-x/…`). Depth is
unbounded, and entry ids become paths (`mid/repo-x:doc-id` when qualifying a
ref). Publishing refuses with `federation cycle detected` when a chain would loop
content back. Scope a search by choosing which hub you query: a team hub returns
the team's knowledge, the root hub returns everything.

**Only `kb` goes upward.** A child hub has the full Document, Ticket and Code
menus itself and accepts `ba` and `dev` publishes, but when it publishes to its
parent it sends only its own `kb` leaves (its own documents and the nested `kb`
leaves of hubs below it). `kb publish` prints one `skipped  <leaf> (kind <kind>
stays on this hub)` line for each leaf held back. A `ba` or `dev` leaf the child
hub pushed to its parent before 1.20.0 is removed from the parent on its next
publish (git history keeps it, and the child hub still has it). A parent never
serves a non-`kb` leaf nested under a child hub: the Web UI and search ignore it
and `kb doctor` names it.

Hub-to-hub publishing needs direct git access upstream, or `gh` for `--pr`. The
intake/OIDC route is for child, `dev` and `ba` repos only. An emptied local `federation/` will not
propagate deletions upstream — publish refuses rather than wipe entries.
Removing *some* entries does propagate, as an ordinary mirror, in a pull request
on the upstream hub.

### Asset offloading to S3

A hub can declare `asset_store: {mode: s3, bucket: …}` in `.kb/config.yaml`.
Publishes then upload image assets to that bucket instead of committing them,
recording what was diverted in `_assets.yaml` next to each document.
`/assets/<name>` on the hub serves diverted images from the bucket with a local
disk cache. Needs `pip install "strata-kb[s3]"` plus standard AWS credentials on
every machine that publishes or serves. The default, `mode: none`, keeps assets
in git like any other file.

### `kb reindex` and `kb doctor`

`kb reindex` rebuilds `federation/index.yaml` from the sub-snapshots when it has
drifted; `--force` also drops and rebuilds the search index. `kb doctor` checks store health: broken contents, missing files, a
section id whose manifest rows span more than one file, a `## ` heading absent
from the manifest, published content modified in place on the hub, files a
publish would never have written (named one by one, with "rotate any credential
they contain"), a hub clone storing a credential in its own `.git/config`, and a
git older than 2.31. On the hub it also checks kinds: registry entries without a
`kind` (warning, fix with `kb init --kind hub`), a leaf whose recorded kind
clashes with the registry or is unknown, and non-`kb` leaves nested under a child
hub (errors). In a child repo it prints the hub menu the repo lands in as an `info`
line (`kind: kb → hub menu: Document`) and flags a hub registry that has no kind
for the repo (warning) or a different one (error: publishing will be refused).
`federation/index.yaml` records `content_sha256` per
snapshot so tampering is detectable.

### Try it end to end

```bash
bash scripts/demo-federation.sh
```

Builds a hub and two sample repos in a temp directory, runs the full lifecycle
including cross-repo search and stale citations after an amendment, then cleans
up without touching your data.

---

## 10. MCP server and Web UI

The same process serves agents and people.

```bash
# local, stdio — already declared in .mcp.json
python -m strata_kb.mcp --kb .kb

# shared, HTTP — the token must be ≥ 32 printable ASCII characters
export STRATA_KB_HTTP_TOKEN=$(python -c "import secrets; print(secrets.token_hex(24))")
python -m strata_kb.mcp --hub . --transport http
# → agent:  http://<host>:8321/mcp     (Bearer token)
# → REST:   http://<host>:8321/api/…   (Bearer token or cookie)
# → human:  http://<host>:8321/ui      (sign in with a hub account; cookie stored)
```

A hub is **mandatory** — resolved from `--hub`, `STRATA_KB_HUB`, or
`.kb/config.yaml`, in that order. The server refuses to start without one, and
`/ui`, the MCP tools and the REST API search only `federation/` — never the
server's own working `.kb/`. In the UI, tags render as clickable chips and can be
used alone to browse matching documents.

The HTTP server keeps the hub fresh by itself: every
`STRATA_KB_HUB_PULL_INTERVAL` seconds (default `300`, `0` = off) it runs
`git pull --ff-only` on the hub checkout and re-syncs the search index when
HEAD moved, so a merged hub PR is searchable without a restart. A diverged or
hand-edited checkout is never touched; the pull fails with a logged warning.

### Menus — Overview, Document, Ticket, Code, Q&A

The left rail is **Overview · Document · Ticket · Code · Q&A**. The first four
each list one kind and have their own search box, which is a real search (`kb query` with that
kind) rendered inside the menu; the tag cloud follows the menu. Overview counts
documents per kind. **Q&A** is the odd one out: it lists ticket questions, not
documents, and has no search box (see [Ticket Q&A](#ticket-qa)).

| Menu | Kind | Shows |
|---|---|---|
| Document | `kb` | Ingested and hub-authored documents. The `?filter=` substring box is gone: use the menu search (`?q=`) |
| Ticket | `ba` | The `<repo_id>-plan` documents BA repos publish, as missions and tickets with a derived status |
| Code | `dev` | `<repo_id>-code` (generated) and `<repo_id>-svc` (curated, with the `hist.*` ticket history) at `/ui/code` |

The top search box searches **all kinds** in one relevance-ranked list. Each hit
carries a kind badge, and the chips above the list (All, Document, Ticket, Code,
with counts) narrow it without leaving the page (`/ui?q=…&kind=dev`). The chip
filters the one budgeted search the top box ran, so the menu's own search can
list more hits than the chip shows. A tag-only browse with `?kind=` stays inside
that kind's menu; an unknown `?kind=` shows the empty state.

The Ticket menu shows what BA repos publish as `<repo_id>-plan` documents, with
a status derived from what the hub already holds: nothing new is stored and
there is no write path. It used to be called Plans: `/ui/plans…` answers `301`
to the same path under `/ui/tickets…`, query string kept, so old links work.

| Route | Shows |
|---|---|
| `/ui/tickets` | Every BA repo and its missions, each with status counts. `?repo=<id>` shows one repo, including its "tickets without mission" |
| `/ui/tickets/{mission}?repo=<id>` | The mission summary and its backlog: each story's status, its reasons and a link to its ticket |
| `/ui/tickets/{mission}/{story}?repo=<id>` | The ticket (L3, rendered like the section reader). A ticket with no mission is `/ui/tickets/tickets/{story}?repo=<id>` |

Status per story, in this order: **done** (the story id is in a `hist.*` row of
the Dev repo's `-svc`, found from the mission's `Grounded on:` line), **ready**
(its ticket is published, so its Definition of Ready passed), **not ready** (no
published ticket, every dependency done) or **blocked** (with its reasons). The
repo rides in `?repo=` because nested federation ids contain `/`; without it the
one repo holding the id is used, and several holders give a 404 page naming
them. `*-plan` documents appear under Ticket, not Document; a search hit in one
links to its Ticket page. The CLI twin is
`kb mission next --from-hub [--repo <ba-repo>] [--json]`; over MCP it is
`kb_mission_next`.

### Ticket Q&A

A Dev who meets a business question while designing or planning a published
ticket asks the BA; the BA answers; the hub keeps the thread. It is the one
place the hub stores something that is not in git.

- **Store.** SQLite at `<hub root>/.kb-qa/qa.db` (in Docker `/data/.kb-qa/qa.db`),
  created, and git-excluded, on the first Q&A call. **Never commit `.kb-qa/`**: a
  new hub's `.gitignore` lists it, and the hub also adds it to
  `.git/info/exclude` when the web UI starts. Back it up with the hub volume.
- **Write path.** Only the MCP tools `kb_question_ask`, `kb_question_list` and
  `kb_question_answer`. All three, the list included, work only against the
  **hub itself**: the shared hub's HTTP server, or the stdio server run inside the
  hub's own checkout (`--kb <hub>/.kb`, `hub: "."`, a local path holding `.kb/`).
  Any other target is refused: a dev repo's stdio server, even one pointing at the
  hub's path, or a hub URL read through a local cache clone, answers `Q&A needs the
  shared hub server — point MCP at it (kb mcp-setup)`, because a store there would
  not be the shared one. BA and Dev repos point MCP at the hub's HTTP server
  with `kb mcp-setup`.
- **Who may write.** Any caller the hub authenticates: the bearer token, or a
  session of any role. `asked_by` and `answered_by` are names the caller types
  (the skills pass `git config user.name`): tracking, not authentication. Limits:
  question and answer 4000 characters, context 1000, names 100 (one printable
  line, no control characters), at most 50 changed sections per answer, and at
  most 50 open questions per ticket.
- **States.** *open* (no answer), *waiting* (answered, but the answer changes the
  ticket and that ticket revision is not on the hub yet: shown as "waiting for
  publish") and *answered*. The state is derived, never stored: a ticket's
  revision is its own `> Revision: N` line (absent = 1), not the hub's git HEAD.
- **Pages.** Read-only, no forms. `/ui/questions` lists the tickets that have
  questions, grouped by BA repo, with open, waiting and answered counts and the
  age of the oldest open one (`?all=1` includes fully answered tickets);
  `/ui/questions/ticket?repo=<repo-id>&ticket=<id>` shows one ticket's questions,
  with `?repo=` in the query string because nested repo-ids contain `/`. The
  ticket page of the Ticket menu gains an "N unresolved questions" link while
  any are open or waiting.
- **BA side.** `/ba-answer-questions` (BA repos). It lists this repo's open
  questions and walks them one ticket at a time. The BA gives each answer. When
  an answer changes the ticket, all the answers of that ticket go into **one**
  amendment under `ba-ticket-author`'s amend rules: `> Revision:` N+1, one
  `## Change log` row with Trigger `question`, Revision N+1 and Affected set to
  the changed sections, one maturity review round, and `kb ticket lint` must
  pass. Amend mode unticks the Definition of Ready boxes whose evidence changed,
  so **the BA must re-tick them**; the skill records no answer for a ticket
  whose Definition of Ready is not fully ticked, so Q&A never takes a ticket off
  the hub. It then calls `kb_question_answer` with `answer_rev` = N+1 and the
  changed sections, or with `answer_rev` unset only when the hub's own revision
  already carries the answer. It never commits, pushes or publishes: the BA
  merges as usual, and the answer shows as waiting for publish until revision
  N+1 is on the hub.
- **Dev side.** See [Questions while designing](#the-agent-workflow): business
  questions become `Q<id>` lines in the design or plan, and a blocking one stops
  GATE 1 or GATE 2.

### The fourteen MCP tools

| Tool | Purpose | Main params |
|---|---|---|
| `kb_search` | Find sections by natural language and return L2 within a token budget. Ranking is capped: each leg is capped at 50 results before fusion, and the tool says so when matches were dropped. It also flags when the top two results are the same section published by two repos, when their keyword scores tie exactly, or when both are hybrid-confirmed within the ambiguity ratio. | `query`, `tags`, `budget`, `kinds` |
| `kb_get_section` | Fetch exactly one section | `doc`, `section`, `level` |
| `kb_context_new` | Pin a `kb-context` citation block at the hub's current commit, from confirmed refs | `refs`, `tags` |
| `kb_resolve` | Resolve a `kb-context` block (or a ticket containing one) — sections at the pinned version plus freshness | `kb_context` |
| `kb_ticket_lint` | Run the Definition-of-Ready gate over a draft ticket. The `> Parent mission:` back-link is checked when `ticket_id` is passed: against `mission_markdown`, else the mission on the hub's plan | `ticket_markdown`, `ticket_id`, `mission_markdown` |
| `kb_ticket_check` | Run the SA grounding gate (`kb ticket check`) against the hub's `-code` document, a moved revision judged from hub history. `[NEW: D<n>]` reads `mission_markdown`, else the hub's plan; no local `-code` fallback | `ticket_markdown`, `mission_markdown`, `heading` |
| `kb_ticket_stale` | The `kb ticket stale --md` report for one ticket or mission: kb-context citations the hub amended (stale) or lost (broken) since they were pinned, and moved `-code` sections it is grounded on (architecture) | `markdown`, `file_name` |
| `kb_mission_lint` | Run the mission Definition-of-Ready gate (`kb mission lint`). `mission_id` checks the file name against the `> Mission:` line; the ticket-coverage warning needs the local `tickets/` and is skipped with a note | `mission_markdown`, `mission_id` |
| `kb_ticket_fetch` | A ticket a BA published, read from the hub's `<ba-repo>-plan` by id — the text `kb ticket fetch` writes; the client saves it to `docs/impl/<id>/ticket.md` | `ticket` |
| `kb_question_ask` | Ask the BA a question about a published ticket (`<id>` or `<repo>:<id>`); returns `Q<id>` and the hub path of the ticket's Q&A page. **Writes**: hub-local only (the HTTP server or the hub's own checkout), any authenticated caller, self-declared name | `ticket`, `question`, `asked_by`, `context`, `blocks` |
| `kb_question_list` | List ticket questions oldest first with their derived state (`open`, `waiting`, `answered`, or `all`) and, once answered, the answer, `answer_rev`, changed sections and the hub's current ticket revision. Hub-local only (the HTTP server or the hub's own checkout) | `ticket`, `repo`, `status` |
| `kb_question_answer` | Record the BA's answer to an open question. `answer_rev` (greater than the hub's current ticket revision, with the changed `ticket_sections`) when the answer changed the ticket, which keeps the question *waiting* until that revision lands; unset otherwise. **Writes**: hub-local only (the HTTP server or the hub's own checkout), self-declared name | `id`, `answer`, `answered_by`, `ticket_sections`, `answer_rev` |
| `kb_mission_next` | Which story next, from the plans published on the hub — the `kb mission next --from-hub` report (a BA's unpublished `missions/` and `tickets/` need the CLI) | `repo` |
| `kb_doctor_hub` | The hub's side of `kb doctor` for a child, ba or dev repo, as JSON: the hub's strata-kb version, whether `federation/<repo_id>` is published and its digest, the hub's `-code` section digests, the registry's kind pin, citation checks. Called by the CLI, not meant for agents | `kind`, `repo_id`, `remote_url`, `dir_name`, `kb_context` |

### Security

Every response carries CSP (`script-src 'self'`), `X-Frame-Options: DENY`,
nosniff, `Referrer-Policy` and `Permissions-Policy`; HSTS on https. The `/ui`
session cookie is a signed, expiring value keyed with `.kb-auth/session.key`
(never with the bearer token, which every child repo holds); it carries the
username, not the role. `POST /ui/logout` ends a session. The server refuses to start on
the `change-me` placeholder, a token shorter than 32 characters, or one that is
not printable ASCII. The login body is capped at 8 KiB however it is sent.

Three per-caller rate limiters exist: `/intake/publish` (30/min),
`/intake/manifest` + `/intake/status` (120/min, shared), and `/ui/login`
(5/min); a failed `Authorization` attempt shares the login bucket, so the lockout
cannot be side-stepped by using the header. **Behind a reverse proxy, set
`STRATA_KB_TRUSTED_PROXIES`** to the number of trusted proxies in front of the
server. The default is `0` — `X-Forwarded-For` ignored, keyed on the socket peer.
Leaving it at `0` behind a proxy makes every limiter key every caller on the
proxy's address, so one caller can exhaust them for everyone. Full guide:
[`docs/deploy-remote-mcp.md`](docs/deploy-remote-mcp.md).

HTTP auth is a bearer token for `/api`, `/mcp` and CI, plus local hub accounts
for the UI — no OAuth or SSO. That is adequate for an internal network and not
ready for the public internet.

### Hub accounts and the Registry page

People sign in to `/ui` with a username and password. Accounts live in
`<hub>/.kb-auth/` (`users.db` and `session.key`); **never commit that
directory** — a new hub's `.gitignore` lists it and the running hub also adds it
to `.git/info/exclude`. Deleting `session.key` logs everyone out. Roles are
`admin`, `ba` and `dev`; only `admin` sees and uses the **Registry** page.

- **First run.** While no account exists, every `/ui` page redirects to
  `/ui/setup`. The hub prints a one-time setup code to its log at start
  (`docker compose logs hub`; with systemd, `journalctl -u <unit>`): enter it
  with a username and password to create the first account, which becomes the
  `admin`. The code lives only in memory and changes on every restart; the
  bearer token never opens this page. Once an account exists `/ui/setup`
  returns 404. The two alternatives below keep working.
- **Bootstrap.** While no account exists, set `STRATA_KB_BOOTSTRAP_ADMIN` and
  `STRATA_KB_BOOTSTRAP_PASSWORD_HASH` (the output of `kb user hash`) and the hub
  creates that admin on start. In a Compose `.env`, single-quote the hash
  (`STRATA_KB_BOOTSTRAP_PASSWORD_HASH='<hash>'`): Compose expands `$`. Plaintext is never accepted; once any account
  exists both variables are ignored (and no setup code is printed). Or run
  `docker compose exec hub kb user add <name> --role admin`.
- **Manage.** `kb user add|passwd|role|remove|list|hash` (see the command
  reference). The last admin cannot be removed or demoted.
- **The bearer token** still works for `/api`, `/mcp` and CI. On the UI it is
  read-only: it never opens the Registry page.
- **Registry page** (`/ui/registry`, admin only). Add or remove a child repo and
  switch its **auto-merge** on or off. Each edit is a commit on the hub's
  default branch, pushed with the intake GitHub App and never force-pushed; if
  the default branch is protected the App must be allowed to push to it. The
  page is read-only when intake is not configured or the hub has no git remote.
  Removing a repo does not delete its published content.
- **Auto-merge** is a per-repo switch. Right after intake opens a repo's publish
  PR it merges it (a merge commit, or a squash when the repo forbids merge
  commits) — the whole PR, including any `-svc` content riding along. The App
  needs `contents: write` and `pull_requests: write`. If the merge fails the PR
  stays open and the publish is still `done`, with `"merged": false` and the
  reason in `detail`; a merged one reports `"merged": true`, and `kb publish` / `kb ci-publish` print "merged" (the CI step summary still shows `hub PR: <url>`).

---

## 11. Citations that pin a version

A ticket, spec or acceptance criterion can carry a machine-readable citation
that pins the store version at the moment it was written. When the store is
later amended, the citation is detectably stale instead of silently wrong.

```bash
kb context new --refs "hr-handbook §4.12, travel-policy §2.1"   # BA generates the block
kb resolve ticket.md                                            # Dev resolves it later
kb diff hr-handbook --against <pinned-rev>                      # what changed since
kb doctor --context ticket.md                                   # CI gate
```

The generated block records the hub's `version` (HEAD at write time) and
repo-qualified refs (`repo-id:doc-id §section`). `kb resolve` walks the hub's
history at that commit and answers `ok`, `stale` or `broken`. `--status-only`
prints only the verdict per ref; `--write-cache <path>` also writes the dev
context cache (`docs/impl/<ticket-id>/context.md`); `--status-only --cache
<path>` validates that cache against the ticket and exits 1 on a mismatch.

`kb diff` reports what changed between two revs of a document: section title and
L1 summary, the L2 slice, the L3 original, added and removed sections, and
whether the manifest order changed. A renumbered section shows as an add plus a
remove, because the id is the citation key.

**The flow in practice.** A BA asks an assistant to draft a story; the assistant
calls `kb_search`, shows every candidate section, and — once the BA confirms
which apply — calls `kb_context_new`. The BA pastes the block into the ticket.
When a Dev picks the ticket up, their agent calls `kb_resolve` and gets exactly
what the BA saw, not a newer store version. If the result is `stale`, `kb diff`
shows what the amendment changed, and the BA decides whether the acceptance
criteria need updating. `kb doctor --context` runs the same check in CI.

---

## 12. BA repos — tickets and missions

A `ba` repo never ingests or summarizes KB content; it publishes only its own
plan. It drafts Dev-ready tickets grounded in the KB, and what it sends to the
hub is the plan itself: one generated document, `<repo_id>-plan`.

**Publishing the plan.** `kb publish` (or `/kb-publish`) in a `ba` repo runs
`kb plan-ingest` and `kb build`, then tags `kb-publish/<ts>`; the tag triggers
`.github/workflows/kb-publish.yml`, which rebuilds the plan and runs `kb
ci-publish`, and the intake opens the hub PR, exactly as for a child repo.
`.kb/<repo_id>-plan/` and `.kb/index.yaml` are generated, so `kb init --kind ba`
gitignores both (`.gitattributes` carries `.kb/** -text`, as in dev and child
repos). Nothing is published on merge: only the BA's `kb publish` sends it.

`kb plan-ingest` is deterministic, offline and LLM-free. A **mission** is
published when `kb mission lint` finds no structural error and every box of its
`## Definition of Ready` is ticked. A **ticket** needs the same two things from
`kb ticket lint`, and `kb mission next` must not demote it to `draft` (below).
Citation resolution is not a gate: it needs the hub, and `kb-ticket-lint.yml`
already gates the pull request on it. Each item left out prints
`skipped: <file> — <reason>` (and goes to the Actions step summary); a skip
never fails the command. The reasons:

| Reason | Meaning |
|---|---|
| `lint error: <first error>` (`(+N more)`) | The lint reports a structural error |
| `Definition of Ready not fully ticked (<ticked>/<total>)` | A box is unticked, or there is no DoR section |
| `parent mission rev <M> affects this story` | The ticket is behind its mission (below) |
| `fenced line starting with '## ' would split the section — indent it inside the fence` | A `## ` line inside a code fence would cut the section for readers |
| `id contains whitespace` | The ticket's file stem is not a usable section id |
| `duplicate id <stem>; kept the first` | Two files share a stem |
| `no '# ' title line` | The file has no H1 |

The document has one group per mission (`M-<slug>.md` and `.raw.md`, holding the
mission and its tickets) and a `tickets` group for tickets with no published
parent. A section is `## <id> <title>`. L3 is the source with the H1 dropped, the
headings demoted one level, and `## Review record` and `## Definition of Ready`
removed (`## Open questions` stays); L2 keeps every table verbatim plus the
summary and business goal (missions) or the story and acceptance criteria
(tickets). The index entry is tagged `plan, generated`. An item that stops qualifying drops
out on the next publish; `/kb-publish` shows the BA what is in the plan before
the go/no-go (run `kb plan-ingest` to see the `skipped:` lines).

To turn this on, the hub operator adds the repo to `federation/registry.yaml`
(the key is the repo's `owner/repo`, mapped to its `repo_id`; leave `workflow:`
unset, because the intake compares it to the full `job_workflow_ref`, which
includes the publish tag), and the BA sets `intake:` in
`.kb/config.yaml`. An existing `ba` repo adds `intake:` by hand and re-runs `kb
init --kind ba` to get the workflow, the `kb-publish` skill, `.gitattributes`
and the gitignore lines; until `intake:` is set, `kb publish` takes the
snapshot route (a direct mirror or a PR on the hub, no CI). A hub redeploy is needed once to get the intake fix that opens a
new PR when the old `publish/<repo-id>` branch was deleted. On the hub the plan
shows up under the **Ticket** menu (section 10) and to agents as the document
`<repo_id>-plan`, next to `-code` and `-svc`.

**`ba-ticket-author`** runs a nine-step pipeline: **Intake** (the business
need — capability, role, value) → **Parent mission** (optional; reads
`missions/<mission-id>.md`, takes the story title from the backlog row, writes a
`> Parent mission: <mission-id> @ rev <N>` line under the title (`@ rev` is
optional; absent means rev 1) and saves as
`tickets/<mission-id>/<mission-id>-US<n>.md`) → **Ground** (`kb_search` surfaces candidates,
the BA picks) → **Draft** (story, acceptance criteria, use cases, sequence and
business-flow Mermaid diagrams, citing `doc-id §section` for every claim touching
a standard) → **Pin** (`kb_context_new` embeds the `## KB context` block) →
**Lint** (`kb ticket lint` until it reports `DoR: PASS`) → **Ground technical**
(`sa-ticket-ground`, run as its own subagent, fills `## Technical grounding`
and runs `kb ticket check`) → **Maturity review** (two independent reviews
score Business coverage and Dev implementability against
`docs/review-rubric.md` — one round by default; rounds 2–3 run on request or
above 6 ACs and stop early once both reach ≥ 4; a gap the agent cannot close
becomes an owned `OPEN(<owner>)` question, recorded in `## Review record`) →
**BA review** (the human reads it, commits it, and pastes the output of
`kb ticket export` into the tracker).

The review scores are agent-reported: `kb ticket lint` checks only that
`## Review record` has the right shape, not how a score was reached.

The agent never pushes to a tracker or opens a ticket on its own. Markdown out,
human in the loop by design.

**`sa-ticket-ground`** fills the one section the BA never touches:
`## Technical grounding` — service, files, tables, routes, pages, jobs, symbols,
externals and the test command, each a section id that exists in the hub's
`<repo>-code` document, or `[NEW: <reason>]`, or parked under `Open decisions`.
It has no repository access and never infers: internal flow, failure modes and
request bodies are not in the document, so they go to `Open decisions` for the
Dev. For a route, page, job, symbol, file or a table's partition, index or
primary key, "not in the document" means "not built" only when
`struct.coverage` says `complete` for that area and scope (see `kb code-ingest`
below); otherwise it goes to `Open decisions` too.
With `--mission` it fills a mission plan's `## Services & order` from
`svc.*` (with each record's `Depends on` cell) and the hub's architecture
document — never `db.*` or `api.*`. The BA skills themselves no longer
read `-code`/`-svc`; they write `%%TODO: verify against codebase%%` and
hand off.

**Mission plans** sit upstream, for a feature spanning several stories (small
work goes straight to a ticket — a mission is never mandatory).
`ba-mission-plan` runs **Intake → Ground → Draft → Split → Pin → Lint → Maturity
review → Review**, saving `missions/M-<slug>.md` with a C4 **Level 1** (System
Context) *and* **Level 2** (Container) diagram plus a user-story backlog whose
ids derive from the mission id.

**Keeping them current.** Every mission and ticket carries `> Revision: <N>`
under its title (absent reads as 1, with a lint warning) and an append-only
`## Change log` before `## Review record`:
`| Rev | Date | Trigger | What changed | Affected | Review |`. With `N > 1` the
log must hold exactly one row per revision `2..N`, in order, and each `Trigger`
is one or more of `kb-context`, `architecture`, `scope`, `delivery`, `question`
(the last only for amendments made from `/ba-answer-questions`); lint fails
otherwise. `Affected` lists full story ids (`M-<slug>-US<n>`) in a mission and
section names in a ticket. `Review` holds the amendment's maturity scores, never
`## Review record`.

`/ba-mission-plan --amend M-<slug>` and `/ba-ticket-author --amend <ticket>`
make the change. They read the file and its `kb ticket stale --md` findings,
ask for the trigger, re-pin `## KB context` with `kb_context_new` (the full ref
list, replacing the block). A ticket amend runs `kb ticket check` whatever the
trigger and calls `sa-ticket-ground` first for an `architecture` trigger, for
any other only when the check FAILs with `re-run /sa-ticket-ground`; a mission
amend runs `sa-ticket-ground --mission` plus `kb ticket check` only for an
`architecture` trigger. Then they bump `Revision`,
append the row, lint, review the changed sections for one round and hand the
diff to the BA. The agent never ticks a Definition of Ready box (an amended
ticket gets the affected boxes unticked), commits or pushes. The rules: a story
`kb mission next` reports `done` is frozen and new work gets the next free US
number; a `DECIDED` decision is superseded, never edited. The superseding row
says `Supersedes D<k>` in its Decision cell and `D<k>` becomes `SUPERSEDED`;
`kb ticket check` then rejects a `[NEW: D<k>]` naming it and points at the
superseding row, and `kb mission next` judges a `SUPERSEDED` blocker by the row
that supersedes it. A ticket's parent line is `> Parent mission: M-<slug> @ rev
<N>`; when the mission's revision is higher and a later change-log row lists the
story in `Affected`, `kb mission next` reports the ticket `draft` with reason
`parent mission rev <M> affects this story`, and `kb plan-ingest` leaves it out.

| Command | Purpose | Exit |
|---|---|---|
| `kb ticket lint <file\|-> [--hub <url>] [--json] [--fail-on-stale]` | Required sections present; every `## KB context` ref resolves at its pinned commit; every inline `doc-id §section` citation is backed by a pinned ref and vice versa | `0` PASS, `1` FAIL, `2` stale |
| `kb mission lint <file\|-> [--hub <url>] [--json] [--fail-on-stale]` | Required structure; C4 L1 + L2 diagrams present; a well-formed backlog whose ids derive from the mission id; every citation resolving at its pinned commit | `0` PASS, `1` FAIL, `2` stale |
| `kb ticket check <file\|-> [--kb-dir <dir>] [--hub <url>] [--json] [--missions-dir <dir>] [--heading <h2>]` | SA grounding gate: every `svc.* / db.* / api.* / int.* / cmd.* / route.* / page.* / job.* / sym.*` id in `## Technical grounding` exists in the hub's `<repo>-code` first (the copy the SA grounded on), then a local `--kb-dir` copy with a `(local fallback — …)` note, columns / routes / pages / jobs / symbols / commands match its tables, `Files:` are in `struct.tree` or a `struct.files.*` section, every `[NEW: D<n>]` names a `DECIDED` row of the parent mission's `## Technology decisions` (`--missions-dir`, default the sibling `missions/`; a mission missing there is read from the hub's plan), and `Open decisions` is empty. It also always fails any `[NEW]` on a `Jobs:` line and a `[NEW]` for something the document already lists at the revision the ticket was grounded on (`already exists in <id>; cite it instead`). With a `struct.coverage` section it further fails a `[NEW: D<n>]` on a route, page, symbol, file or partition/index/primary key whose scope is `partial` or `not scanned` (`cannot claim new: coverage of <scope> … is <status>; move it to Open decisions`), a `[NEW]` in `Routes:`, `Pages:`, `Symbols:` or a `Tables:` index/partition/primary key that does not name the file it will live in (`… in <path> [NEW: D<n>]`), and a line that cites an id and also carries `[NEW]` (put the new item on its own sub-bullet). A `Grounded on:` revision that moved is not a failure by itself: when every cited fact still holds it is a PASS with a `[note]`, or a `[warn]` plus a unified diff of each changed cited section; when one is gone it is a FAIL (`grounding drifted since @<old> (now @<new>) and no longer holds — re-run /sa-ticket-ground`). `dev-implement-ticket` runs it right after Intake. `--heading "## Services & order"` checks a mission plan's SA section against its own decisions table | `0` PASS, `1` FAIL |
| `kb mission next [--missions-dir <dir>] [--tickets-dir <dir>] [--repo-id <id>] [--kb-dir <dir>] [--hub <url>] [--json]` | Read-only: every backlog story across `missions/` as `done` (its id is in a `hist.*` row of the hub's `-svc` document), `ready` (a ticket file exists under `tickets/` — flat or `tickets/<mission-id>/` — with every `## Definition of Ready` box ticked), `draft` (a ticket file with an unticked box, reason `DoR n/m ticked`, or no `## Definition of Ready` section, reason `no Definition of Ready section`), `to-draft` (no ticket, every `Depends on` done, every D-row that `Blocks` it `DECIDED`) or `blocked` (reasons named); ends with `Next: <us-id> — <title>` naming the first `to-draft` story. The `-svc` document is derived from the missions' `Grounded on:` line (a comma-separated list is read, the `-code` entry wins; `<x>-code` → `<x>-svc`, `--repo-id` overrides); `--kb-dir` is read first when it holds the `-svc` document (a dev machine), the hub second; no `Grounded on:` line, an unconfigured or unreachable hub, a `-svc` not on the hub, and a missing tickets dir are each a `note:` line, never a red line | `0` after a report; `1` for a bad directory flag or a malformed `.kb/config.yaml` |
| `kb ticket tidy [--tickets-dir <dir>] [--into <folder> <file>...]` | Move each flat `tickets/*.md` whose `> Parent mission: M-x [@ rev N]` line is valid to `tickets/M-x/<name>`; print `moved:` per file, `conflict:` when the destination exists (nothing is overwritten), `unsorted:` for a file without a parent mission, `note:` for an unreadable file or a FILE under `--into` that is not a flat file directly under tickets/. With `--into`, move the named files into `tickets/<folder>/` instead. Idempotent; no git — commit the renames yourself | `0` after a report; `1` for a bad `--tickets-dir`, a bad `--into` name, FILES without `--into`, or `--into` without files |

Mission lint runs over MCP too (`kb_mission_lint`), without the ticket-coverage
warning: that check needs filesystem access to the sibling `tickets/` directory,
which only the CLI has. Ticket lint and ticket check run over MCP too
(`kb_ticket_lint`, `kb_ticket_check`); the client passes the mission's text
(`mission_markdown`) when it is not on the hub yet. Only the CLI's local
`-code` fallback (`--kb-dir`) has no MCP twin. `kb ticket lint --missions-dir`
and `kb mission lint --tickets-dir` point either gate at a non-sibling folder.

Every pull request on a `ba` repo runs `.github/workflows/kb-ticket-lint.yml`.
The trigger is deliberately **not** `paths`-filtered: GitHub never synthesises a
passing status for a job that never starts, so filtering a required check would
leave unrelated PRs waiting forever. The job always starts, inspects the PR's own
diff, and dispatches `kb ticket lint` or `kb mission lint` by directory — exiting
0 with a notice when neither directory changed.

A ticket is checked again after it merges: `ba` and `dev` repos also get
`.github/workflows/kb-doctor.yml`, which runs `kb ticket stale` every day (and on
demand) over `tickets/` and `missions/`. While any citation is stale or broken it
keeps one open issue labelled `kb-stale-citations` listing them; once everything
is current again it closes that issue. Besides KB-context citations, `kb ticket
stale` compares the `svc.*` ids of a mission's `## Services & order` and the ids
of a ticket's `## Technical grounding` with the `-code` document they were
grounded on (`Kind` column: `kb-context` or `architecture`); a cited section
that changed is `stale`, one that is gone is `broken`, and a `Grounded on:`
revision that is not on the hub is one `stale` finding, `baseline not on hub`.
Only cited sections count. It needs the same `STRATA_KB_HUB` variable
and `KB_HUB_TOKEN` secret as `kb-ticket-lint.yml`.

**Bug tickets.** A defect in something already live is a bug ticket, not a
story. `/ba-bug-report` drafts it as `tickets/bugs/BUG-<n>.md` from
`docs/tickets/BUG-TEMPLATE.md` (installed by `kb init --kind ba`). Under the
title it carries `> Type: bug|hotfix` (a hotfix ships ahead of the next
release), `> Severity: S1..S4` (required) and optionally `> Related ticket:
<id|none>`; it has no `> Parent mission:`. Sections: Summary, Environment,
Pre-conditions, Steps to reproduce, Expected result, Actual result,
Attachments, Impact, Definition of Ready. Screenshots are PNG or WebP files in
`tickets/bugs/BUG-<n>/`, referenced in `## Attachments` as
`![caption](BUG-<n>/<file>.png)`, or `N/A — <reason>`. `kb ticket lint`, MCP
`kb_ticket_lint` and `kb-ticket-lint.yml` lint a bug against this contract
automatically; stories are unchanged. `kb plan-ingest` (so `kb publish` and the
merge-to-`main` CI) publishes a ready bug with its images copied to
`<repo>-plan/assets/<sha256>.<ext>`, and the hub's ticket page renders them.
The BA ticks the Definition of Ready; the agent never does.

**Answering a Dev's questions.** `/ba-answer-questions` walks the open Dev
questions for this repo's tickets (see [Ticket Q&A](#ticket-qa)). It needs MCP
pointed at the hub's HTTP server (`kb mcp-setup`). An answer that changes a ticket is one
amendment per ticket: `> Revision:` N+1, one `## Change log` row with Trigger
`question`, then Definition of Ready, which amend mode unticks and the BA must
re-tick, and `kb ticket lint` must pass. The skill never commits, pushes or
publishes; until the BA merges and the revision lands, the hub shows the answer
as waiting for publish.

Scaffold with `kb init --kind ba`; the generated `QUICKSTART-BA.md` covers
`kb mcp-setup` (`/kb-mcp-setup`), which writes the hub's HTTP MCP credentials
(`STRATA_KB_HUB_URL`, `STRATA_KB_HTTP_TOKEN`) into `.env` and verifies them
(`--hub-url`, `--token` — prefer the `STRATA_KB_HTTP_TOKEN` env var, which stays
out of shell history — and `--no-verify` to skip the probe), and the CI
variable and secret (`STRATA_KB_HUB`, `KB_HUB_TOKEN`) the lint workflow needs.

---

## 13. Dev repos — code knowledge

A `dev` repo consumes the shared KB while implementing tickets, and publishes
knowledge about **its own source code** back to the hub. The boundary against
`child`: a `child` ingests documents from outside the repo; a `dev` ingests
nothing and authors only knowledge about its own code.

### The agent workflow

One orchestrator plus four phase skills, each separately invocable and resumable
across sessions. State is derived from which artifacts exist — never stored in a
sidecar file.

```
/dev-implement-ticket <ticket>   → intake · check · resolve · ground · placeholders
                                 → dev-design    ── GATE 1: Dev approves design
                                 → dev-plan      ── GATE 2: Dev approves plan
                                 → dev-execute      (repeatable, resumable)
                                 → dev-handover  ── GATE 3: Dev opens PR
                                                    GATE 4: Dev merges
```

| Situation | Command |
|---|---|
| New ticket, nothing started | `/dev-implement-ticket <ticket>` |
| Small ticket, the change is obvious | `/dev-implement-ticket <ticket>` — the flow collapses itself; `design.md` is one paragraph |
| Design approved, no plan yet | `/dev-plan <id>` |
| Plan approved, or execution underway | `/dev-execute <id>` |
| Code hand-implemented, needs a PR write-up | `/dev-handover <id>` |
| Lost track of where a ticket stands | `/dev-implement-ticket <id>` |
| A BA-reported bug (`BUG-<n>`) | `/dev-fix-bug BUG-<n>` |
| A technical question that needs evidence from this repo and the hub | `/dev-sa <question>` |
| Just checking a citation | `kb resolve <file>` |

Work lives in `docs/impl/<ticket-id>/design.md` (every ticket, one paragraph for a small one) and
`docs/impl/<ticket-id>/plan.md` (one task per acceptance criterion, `- [ ]`
checkboxes ticked one commit at a time). Those two files, the ticked-checkbox
ratio, the branch, and whether a PR exists are the complete state.

Every entry point re-checks citation freshness first — the hub may have published
since the last session, so a ref that was `ok` yesterday can be `stale` today.
All four gates are human.

- **Machine-enforced:** `kb pr lint` (in `kb-pr-lint.yml`) fails a PR without
  `## Ticket` / `## Changes` / `## Testing`, without a fence holding the plan's
  `cmd.test` run, or without A5's `Blocking: No`; `kb build` fails while a
  `<repo_id>-svc` section is `pending`; `kb resolve --status-only --cache`
  refuses a context cache that no longer matches the ticket.
- **Prompt-only** — stated in every skill, measured by nothing: test-first TDD
  (no production code without a failing test observed first), shown
  verification output for every completion claim, the GATE 1 / GATE 2
  approvals and the A1–A4 reviews. The human at each gate is the check.
  `QUICKSTART-dev.md` lists both sides in full.

**A ticket id is enough.** Given only `M-<slug>-US<n>` (or a plain ticket stem),
`dev-implement-ticket` runs `kb ticket fetch <id>` first: the hub is the source of
truth, so it finds the `*-plan` document holding that section (`<repo>:<id>`
when several repos hold it; exit `1` when none does or the id is ambiguous),
restores the ticket to its source shape with a provenance line
(`> Fetched from hub: <repo>:<doc> §<id> @ <rev> — do not edit; amend in the BA
repo.`) and writes `docs/impl/<id>/ticket.md`, overwriting it every time. That
copy is derivable, so `docs/impl/.gitignore` ignores `*/ticket.md`. A path or a
pasted body remains the fallback when the hub has no copy or is unreachable. The
hub copy has no `## Definition of Ready`: being published means it was fully
ticked, so no dev step requires that section. The parent mission's `##
Sequencing` is read the same way (`kb get <doc> <M-id> --level l3`) when there is
no local mission file. A ticket whose mission moved on after it was written is
`draft` on the BA side (`kb mission next`, reason `parent mission rev <M> affects
this story`) and is left out of `-plan`: a Dev sees the story as *not ready* in
the Ticket menu, and `kb ticket fetch` finds nothing until the BA amends and republishes.

**Fixing a bug.** `/dev-fix-bug BUG-<n>` (or a saved bug's path) is the bug
counterpart of `/dev-implement-ticket`, in the style of
`superpowers:systematic-debugging`: Intake (fetch, then branch `fix/<BUG-id>`,
or `hotfix/<BUG-id>` off the production line the Dev names) → Reproduce (a
failing test that shows the Actual result; no fix without it) → Root cause
(written hypotheses in `docs/impl/<id>/rootcause.md`; three failed ones stop the
flow for an architecture talk) → Fix (one change at the root cause) → Handover
(`/dev-handover` with bug rules: no design or plan, the reproduction test and
the root cause replace them). `kb ticket fetch BUG-<n>` also copies the bug's
images to `docs/impl/<id>/assets/` and warns once per image missing from the
hub clone (open `<hub>/assets/<name>`); MCP `kb_ticket_fetch` returns text only.

**Questions while designing.** The `design-author` and `plan-author` subagents
never call the hub. What they cannot decide goes into a `## Questions raised`
section of the draft, each item tagged `business` or `technical` with the ACs it
blocks. The orchestrating skill sorts them. A *technical* one goes to `dev-sa`
(below), which returns a decision with `path:line` and `doc §section` evidence;
the skill writes it under `## Technical decisions` as `SA-<n>` and re-dispatches
the author. A *business* one is asked with MCP `kb_question_ask` (see [Ticket
Q&A](#ticket-qa)) and listed under `## Open questions` as `Q<id>`. An open
question that blocks an AC stops GATE 1 or GATE 2 with the hub's Q&A link; one
that blocks nothing does not. On every entry `/dev-implement-ticket` reads
`kb_question_list` for the ticket: an *answered* question is shown with its
changed sections, the ticket is re-fetched and, when a changed section touches
an approved design, the flow goes back to `dev-design`; a *waiting* one is shown
as information only; an *open* blocking one stops the flow. The `State:` line
gains a fifth marker, `BA-Q: none | open Q<ids> | waiting Q<ids>`. When the Q&A
tools are refused and every `Q<id>` line in the design and plan carries
`— answered rev N` (or there are none), the flow continues with
`BA-Q: unknown (Q&A unavailable)`; `dev-design` and `dev-plan` then keep a
`blocks: none` business question as `OPEN(BA)` and stop only on a blocking one.
A newly answered line is marked `— answered rev N — re-draft`, and the phase
re-dispatches its author once for it. `OPEN(BA)` remains for
the case `dev-execute` meets mid-implementation, which returns to `dev-design`.
The Pre-code axis of the PR review rubric accepts a hub-asked `Q<id>`.

**`/dev-sa`.** The Dev-repo solution architect: given one technical question, the
ticket in flight and the current draft, it reads this repo's source freely and
the hub's `-code`, `-svc` and domain documents, and returns a decision, the
reasoning, the rejected alternatives and the evidence; or `business question:
<why>` when the answer would change what an AC means. Dispatched by `dev-design`
and `dev-plan`, or called directly as `/dev-sa <question>`. It returns text only:
it never writes the hub, the ticket, the design or the code.

### `kb code-ingest` — the generated document

Extracts a codebase's structure into `.kb/<repo_id>-code/` — **deterministic and
LLM-free**: pure functions of the working tree, no network call. The output is an
ordinary 4-layer document, so build, query, federation and the Web UI read it
with zero special-casing.

Not shipped: relationship sections (`rel.<name>`), planned in Architecture v0.4
§14.1. Seven extractors read build, deploy and contract files — manifests,
compose files, migrations, OpenAPI, the file list. Four more (`routes`, `pages`, `jobs`,
`symbols`) read **source syntax** with tree-sitter, which needs the optional
`code` extra (see "Routes, pages, jobs and symbols" below).

```
kb code-ingest [--repo-root .] [--kb-dir .kb] [--repo-id <cfg>]
               [--doc-id <repo_id>-code] [--db <path>]... [--tags "a,b"]
               [--scaffold-svc] [--json]
```

Eleven extractors, organised by **artifact kind rather than language**, because
Strata is adopted across many project lines and a single-stack extractor set
would leave most repos with nothing on day one:

| Extractor | Reads | Section prefix |
|---|---|---|
| `services` | `docker-compose*.yml` (a `build:` service is read through its Dockerfile — runtime-stage `FROM`, `EXPOSE`, `CMD`; `env_file` by name only), `Dockerfile`, k8s manifests, `*.sln`, workspace `package.json` | `svc.<name>` |
| `deps` | `pyproject.toml`, `requirements*.txt`, `setup.cfg`, `package.json`, `pom.xml`, `build.gradle{,.kts}`, `*.csproj`, `go.mod`, `composer.json`, plus Rust, Swift and Dart manifests | `dep.<ecosystem>` |
| `commands` | `package.json` scripts, `Makefile` targets, `tox.ini`, `pyproject` tool sections, `*.sh` at the root or under `scripts/`, `pom.xml`, `*.csproj`, `.github/workflows/*.yml` `run:` steps (CI wins over a local script; classified by whole token, never substring) | `cmd.build`/`test`/`lint`/`run` |
| `tree` | `git ls-files` — so a git-ignored virtualenv never appears and two checkouts of one commit agree — plus always-pruned build directories. Outside a git repo it is an unfiltered walk and says so. L3 is capped at 600 lines and depth 4. | `struct.tree` |
| `schema` | `**/migrations/*.sql`, Flyway/Liquibase layouts, `schema.prisma`, Alembic `versions/*.py`, EF `Migrations/*.cs`, plus explicitly named `--db` SQLite files | `db.<table>` |
| `integrations` | `.env.example`/`.sample`/`.template` **keys**, compose `environment:` **keys** | `int.<name>` |
| `api` | `openapi*.y*ml`, `swagger*.json` | `api.<tag>` |
| `routes` | HTTP routes declared in source code (needs `[code]`) | `route.<slug>` |
| `pages` | UI page routes (file-system routers work without `[code]`) | `page.<slug>` |
| `jobs` | scheduled jobs declared by framework schedulers (needs `[code]`) | `job.<slug>` |
| `symbols` | exported names, enum and object members, CSS custom properties (needs `[code]`) | `sym.<slug>` |

`tree` also emits `struct.files.<dir>` and every extractor reports into one
`struct.coverage` section (below). `tree` always finds something, and the four
source-reading extractors are not counted as evidence of a codebase either, so
the zero-detection rule is: `kb code-ingest` exits `1` when **none of `services`, `deps`,
`commands`, `schema`, `integrations` and `api`** found anything. A document
holding only a folder listing and source-derived sections is a
misconfiguration, not knowledge.

#### Routes, pages, jobs and symbols — the `code` extra

`pip install "strata-kb[code]"` adds `tree-sitter` and
`tree-sitter-language-pack==0.13.0` (about 184 MB). The pin is exact and stays
below 1.0: grammars ship inside the wheel, whereas 1.x downloads them from the
network at run time, which would break the no-network, same-bytes contract.
Languages: JS/TS, Java/Kotlin, C#, Python, PHP, Go, Rust, Swift and Dart (plus
CSS/SCSS for custom properties). `kb-code.yml` installs `strata-kb[code]` in
both jobs, and `kb doctor` in a Dev repo warns when it is missing locally.
Without the extra, `routes` and `symbols` emit `not scanned — install
strata-kb[code]` coverage rows and no sections. `pages` rows for Angular, Vue,
React and Flutter read the same, but the file-system routers (Next.js, Nuxt,
SvelteKit) still produce `page.*` sections. `jobs` rows stay `partial` (jobs are
never complete) with the install note added to the detail, and Kubernetes
`CronJob` manifests still produce `job.*` sections. Each affected extractor
prints its own warning, so there can be up to four. `struct.files.*` and the
schema rows do not need the extra.

| Section | Holds |
|---|---|
| `route.<slug>` | One section per controller class, router file or route file. L2 table `Method \| Path \| Handler \| File \| Request type`, with every statically known prefix joined (class prefix, router mount, group prefix, global prefix); L3 adds the declared fields of a request type defined in the repo. |
| `page.<slug>` | One section per front-end app. L2 table `Path \| File \| Layout/group`; route groups such as `(admin)` and dynamic segments (`[id]`, `:id`, `[...slug]`) are kept as written, and a Next.js `middleware` `config.matcher` shows as a `Middleware matcher` row. |
| `job.<slug>` | One section per declaring file or manifest. L2 table `Name \| Schedule \| Handler \| File`; the schedule is the expression as written, or `hosted`, or `(dynamic)`. |
| `sym.<slug>` | One section per package root (a directory with its own manifest), else per top-level directory. L2 table `Name \| Kind \| File`; kinds `function`, `class`, `interface`, `type`, `const`, `enum`, `member`, `css-var`. Names only, never a value. |
| `struct.files.<dir>` | Every tracked file under one top-level directory, uncapped (`struct.files.root` for files at the repo root). `struct.tree` stays the capped overview. |
| `db.<table>` | Gains `Table`, `Primary key`, `Partition` and `Indexes` rows (`Partitions` for child partitions). A Prisma model and the SQL migration for the same table merge into one `db.<Model>` section; where they disagree both values show, tagged with their source. |

Supported frameworks. **Routes:** NestJS, Express, Next.js, Nuxt, Spring Boot,
Quarkus, Micronaut, ASP.NET Core, FastAPI, Flask, Django, Gin, Laravel,
Symfony, Actix Web, Axum, Rocket, Vapor. **Pages:** Next.js, Nuxt, SvelteKit,
Angular, Vue, React (react-router), Flutter (go_router). **Jobs:** NestJS,
Spring / Quarkus / Micronaut, Hangfire, Quartz and .NET hosted services,
Celery, Laravel, Symfony, node-cron, BullMQ, robfig/cron,
tokio-cron-scheduler, Kubernetes `CronJob`. Sections split by file, package or
top-level directory — never by size — and no list is truncated, so a list can
back a `complete` claim.

**`struct.coverage` — what the scan proves.** One L2 table,
`Area | Scope | Framework/language | Status | Detail`, with the areas `routes`,
`pages`, `jobs`, `symbols`, `files` and `schema`. Status:

| Status | Meaning |
|---|---|
| `complete` | Every recognised form in that scope was resolved. |
| `partial` | Something was seen but not resolved (a dynamic route path, a file that does not parse, a re-export the reader cannot follow). Each site is named as `file:line`; it is never silently dropped. |
| `not scanned` | Nothing was looked at, and the detail says why (extra missing, a language or framework without an adapter). |

An area is only as good as the forms the adapters know: a home-made decorator
is a known blind spot, which is why `complete` is conservative. **`jobs` is
never `complete`**: a job can live where no adapter looks (`pg_cron` in a
migration, a hand-written `setInterval`, a crontab), so the row is always
`partial` with the detail `jobs outside framework schedulers are not
detectable`. A job that exists is listed; an absent one is always a Dev
question. A `-code` document made by an older release has no `struct.coverage`:
the SA treats every area as `not scanned`, and the gate does not apply the coverage rules to it.

The SA uses it: for a route, page, symbol, file or a table's partition, index
or primary key, absent from a `complete` scope means new: a route, page or
symbol is written `<thing> in <path> [NEW: D<n>]`, a new index, partition or
primary key is a `Tables:` sub-bullet `index <name> (<cols>) | partition RANGE
(<col>) | primary key (<cols>) on db.<table> in <path> [NEW: D<n>]` (`<path>` is
the migration), and a new file is its own `Files:` entry, `<path> [NEW: D<n>]`.
The scope is the longest one listed in a `struct.coverage` row other than
`files` that prefixes the path, and it needs its own row for the area: a nested package with no row
for it is `not scanned`, whatever its parent says. Absent from a `partial` or
`not scanned` scope goes to `Open decisions`. Only names are emitted — the literal strings
that appear are route and page paths, middleware matchers, cron or interval
expressions and CSS custom-property names; env values, constant values and enum
member values never are. The new `Pages:`, `Jobs:` and `Symbols:` lines of
`## Technical grounding`, and the `QUICKSTART-BA.md` / `QUICKSTART-DEV.md`
files `kb init` writes, describe the same fields.

**Never a secret channel — two security properties, not conveniences.**

1. The `integrations` extractor emits **keys only, never values**. The only env
   file it opens is `.env.example`/`.sample`/`.template` — never a real `.env` —
   and its regex has no capture group around the value at all, so there is
   nothing to leak whatever a matched line holds. Compose `environment:` blocks
   *are* read and do hold real inline values, but only the key survives, through
   the same sanitiser. Neither a developer's local `.env` nor a value hardcoded
   into `docker-compose.yml` can reach a document CI publishes.
2. SQLite schema input is **`--db`-only, never inferred.** A stray `.db` or
   `.sqlite` in the repo — a test fixture, a scratch database — is never read
   unless named explicitly on the command line, so it cannot become published
   company knowledge by accident.

**Stated parser limits, so they are not mistaken for bugs.** `schema` recognises
`CREATE TABLE` and `ALTER TABLE … ADD COLUMN` in sorted filename order; it does
not implement a SQL dialect. A `CREATE TABLE` of a name already created in a
*different* migration directory is dropped with a warning naming both files, and
an `ADD COLUMN` applies only inside the directory of its `CREATE TABLE` — two
independent schemas sharing a table name are never merged into one that exists
nowhere. Partition clauses, primary keys, `CREATE INDEX` and `ADD CONSTRAINT … PRIMARY KEY|UNIQUE` are read. A statement it does not apply (`RENAME`, an unknown `ALTER` action, an unparsed index) is a site: the `schema` coverage row of that scope and reader reads `partial` and names the `file:line`. `FOREIGN KEY` and `CHECK` constraints only warn. A
dialect-specific trailing clause (`) ENGINE=InnoDB …;`, `) WITHOUT ROWID;`,
`) PARTITION BY RANGE (id);`, or a final statement with no `;` at all) is handled
correctly — the closing paren is located by depth, not by scanning for an
adjacent `);`. A table name outside the recognised identifier shape is skipped
**with a warning naming the file**: the reader counts `CREATE TABLE` keywords and
compares against what it recognised, so a skip is never silent. EF Core
migrations are recognised by table name only. `build.gradle{,.kts}` is matched by
regex, not parsed as a DSL. Maven `<plugins>`, `setup.cfg` `extras_require`,
`pnpm-workspace.yaml` and compose `healthcheck:` are not read.

**A destination this command did not write is refused.** If `.kb/<doc_id>/`
already holds Markdown or a manifest and that manifest is missing, unreadable,
not titled `… — code knowledge`, or lists a section id outside the
generated prefixes, `kb code-ingest` exits 1 and writes nothing. There is no
override flag — move the document or choose another `--doc-id`.

**Determinism, and its one caveat.** Extractors are pure functions of the files
git tracks, plus explicitly named `--db` files. Sections sort by `(group, id)`,
dependencies by name, tables by name (column order is preserved — it carries
meaning), and YAML/JSON keys sort on write. Path separators normalise to `/` and
line endings to `\n`, even on Windows. Re-running on the same commit **on the
same platform** produces byte-identical files, which is what makes
`kb ci-publish`'s hash diff a true no-op on an unchanged tree. Several glob
matches case-normalise per OS, so a cross-platform re-run is not covered by this
guarantee; CI always runs on Linux, so what gets published is stable. The
manifest's `revision`/`ingested` derive from the **HEAD commit**, while the
working tree may hold uncommitted changes — `kb code-ingest` prints a
`dirty_tree` warning when it detects this.

### `kb svc note` and `/dev-code-seed` — the curated document

`<repo_id>-code` holds names and structure. `<repo_id>-svc` holds what each
service is **responsible for** — LLM-drafted from the code evidence and gated by
a human before it can publish.

**Why two documents and never one:**

1. **Overwrite vs. accumulate.** `-code` is fully regenerated on every merge;
   sharing a document would silently delete human-authored content beside it.
2. **`pending` vs. a clean build.** `-svc` carries `pending` sections during a
   seed or an amend; folding that into `-code` would fail `kb build` for the
   whole document, including the parts CI regenerates automatically.
3. **Auto-merge vs. review.** `-code` is machine fact; `-svc` is a human claim
   and needs review. Auto-merge is a per-repo switch that merges the whole
   publish PR, so the `-svc` review happens locally in `/dev-code-seed`, before
   publish. One document can't carry both review styles at once.

The two are joined by **section id, not by file**: `svc.<name>` deliberately
exists in both. `-code §svc.<name>` supplies `alias`/`label`/`technology`,
`-svc §svc.<name>` supplies `description` — together filling all four arguments
of a C4 `Container(alias, label, technology, description)`.

**Section-id prefix contract.** Each prefix has exactly one owner. The BA agent,
the Dev workflow and future tooling key on these, so they are stable:

| Prefix | Document | Owner | Content |
|---|---|---|---|
| `struct.tree` | `-code` | extractor | package/folder layout and entry points |
| `struct.files.<dir>` | `-code` | extractor | every tracked file under a top-level directory |
| `struct.coverage` | `-code` | extractor | per area and scope: `complete`, `partial` or `not scanned` |
| `svc.<name>` | `-code` | extractor | image, ports, `depends_on`, detected technology |
| `db.<table>` | `-code` | extractor | columns, types, PK/FK, DDL |
| `dep.<ecosystem>` | `-code` | extractor | direct dependencies and framework detection |
| `int.<name>` | `-code` | extractor | external integrations, keys only |
| `api.<tag>` | `-code` | extractor | endpoints from an in-repo OpenAPI contract |
| `route.<slug>` | `-code` | extractor | HTTP routes declared in code |
| `page.<slug>` | `-code` | extractor | UI page routes |
| `job.<slug>` | `-code` | extractor | scheduled jobs of framework schedulers |
| `sym.<slug>` | `-code` | extractor | exported names, enum members, CSS custom properties |
| `cmd.<purpose>` | `-code` | extractor | how to build, test, lint and run this repo |
| `svc.<name>` | `-svc` | human (LLM-drafted) | what this service is responsible for |
| `flow.<name>` | `-svc` | human | a business flow and the services it crosses |
| `hist.<name>` | `-svc` | `kb svc note` | append-only log of tickets that touched this service |

**Bootstrapping, once per repo — `/dev-code-seed`.** A project adopting Strata
already has services doing real work, so the seed is a one-time pass rather than
documentation discipline that would yield nothing for what already exists. Seven
steps: **Preflight** (hub, repo-id, intake configured and the repo allowlisted;
warns, does not block, on a dirty tree) → **Extract** (`kb code-ingest
--scaffold-svc` creates a `pending` `svc.<name>` per detected service) →
**Draft** (`kb summarize <repo_id>-svc` writes each responsibility paragraph from
that evidence) → **Review** (a human walks every draft against its evidence — the
LLM output is a draft, never a fact, and approving one unread defeats the gate)
→ **Approve** (`kb approve <repo_id>-svc`) → **Flows** (optional `flow.<name>`
sections) → **Validate and publish** (`kb build` *without* `--allow-pending`,
then `kb publish --pr`). Budget **~10–15 min per service** for the review step.

**Accruing after the seed — `kb svc note`.**

```bash
kb svc note payments-api --ticket ABC-123 --title "Add refund endpoint" \
  --refs "hr-handbook §4.12"
```

Appends one row to `<repo_id>-svc §hist.<service>`. L2 is a
`| Ticket | Title | Domain refs |` table sorted by ticket id; L3 is a fenced
record with no pipe table, satisfying the table-integrity invariant by
construction. Deterministic and **idempotent** — re-running for the same ticket
and service updates that row instead of duplicating it. `hist.*` sections are
facts, not claims, so they are written `summarized` with a freshly rendered
summary and never block `kb build`. It exits 1 on any of: no resolvable repo-id;
a missing `-svc` or paired `-code` document; an unknown service (a typo must not
invent one); an unreadable manifest; or a `hist.*` manifest/file desync.

`dev-handover` runs this for every service a ticket touched, so a repo that has
completed the seed needs no further per-ticket documentation discipline.

### Operational prerequisites for a `dev` repo

- **Register the repo in the hub's `federation/registry.yaml`.** Both `-code` and
  `-svc` publish through it. Be clear about what it does: on the git path it is a
  *mistake guard* — a child's remote URL is self-asserted, so the check cannot
  authenticate anyone. Branch protection on the hub plus the OIDC intake are the
  actual security boundary.
- **Decide whether the hub auto-merges this repo's publish PRs.** It is a
  per-repo switch on the hub's Registry page. `kb ci-publish` opens one hub PR per
  publish, not per document — the intake keys the publish branch by repo id and
  reuses it while a PR is pending — so a publish carrying both a regenerated
  `-code` and an already-merged `-svc` amend lands both in one PR, and auto-merge
  merges the **whole PR**. The `-svc` review therefore happens locally in
  `/dev-code-seed` step 4, before the section reaches `reviewed`, never at the
  hub.
- **Run `kb mcp-setup`** (or `/kb-mcp-setup`) for each developer — it writes
  `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN` into `.env` and verifies them.
- **Budget the one-time seed:** ~10–15 min per service.

`kb-code.yml` ships two jobs: on a `kb-publish/*` tag (pushed by `kb publish`)
it regenerates `-code`, builds and publishes; on `pull_request` it runs
`kb build` only and **never publishes**. A push to the default branch publishes
nothing: the intake accepts a publish only from a `kb-publish/*` tag, so a dev
repo publishes with `kb publish` after a merge, like a `ba` repo. `--scaffold-svc` is deliberately never passed in CI — CI
must never create `pending` content, since that would fail its own build step.

### Full-auto mode

A switch per `ba` and `dev` repo that lets the two repos run on their own, on
your machine, until every ticket on the hub is done. In this mode no step waits
for a person: the agent reviews its own work, picks the best option, decides,
writes down why, merges and publishes. It is built for **one BA repo and one Dev
repo per hub**. Nothing changes while the switch is off: every skill shows the
text it always showed.

**Security note. Read before turning it on.** The permission deny list that
`kb init` writes (below) is defence in depth, not a boundary. An unattended run
**merges pull requests with admin rights** (`gh pr merge --admin`, only when
branch protection asks for a review the agent cannot give, and only after every
required check is green) and publishes to the hub, with no human review. A ticket
the agent misreads goes straight to `main` and to the hub. Before you run it,
the repo owner **must** enable GitHub branch protection on `main`: block force
pushes and deletions, **include administrators**, and keep the repo's CI check as a
**required status check**: in a Dev repo the `test-<lang>` job(s) of `kb-test.yml`
(or of the workflow carrying the `kb-test` marker, see below); in a BA repo the
`lint` job of `kb-ticket-lint.yml`. Branch protection picks checks by job name.
Without that, "green CI" is only a convention the agent follows. Do **not**
require approving reviews on `main` in an auto-mode repo: the agent cannot approve
its own pull request, and `gh pr merge --admin` is refused when administrators
are included in the rule. If you do require reviews, exclude administrators from
that rule so `--admin` can merge; the owner then accepts that the agent can
bypass that protection on `main` the same way. The deny list
also cannot see the current branch: the agent's working tree must never sit on
`main` with commits on it. The skills branch first; the runner does not guard this.

**The easy path: `/kb-auto`.** `kb init --kind ba|dev` also ships a `kb-auto`
skill (`/kb-auto on|off|status|run` in Claude Code, Copilot and Cursor). `run`
turns the switch on if needed, commits and pushes `.kb/config.yaml` and
`.claude/settings.json` when they are not yet on the default branch (only when
your tree is on that branch), starts `kb auto run` detached with its output in
`.kb/auto/run.log`, and shows the preflight reasons if it refuses. `status`
reads `kb auto status --json`, whose `running` (pid or `null`) and
`default_branch` fields exist for it. The prerequisites below still
hold; the skill only does the mechanical steps for you.

**Prerequisites.**

- A person writes the first mission (`/ba-mission-plan`) before the switch goes
  on. The loop works the backlog it is given; it does not invent one.
- The hub is on **1.29.0 or later**. The runner polls ticket Q&A over the new
  `GET /api/questions` route (below), which an older hub does not have.
- `.kb/config.yaml` (with `auto.enabled: true`) and `.claude/settings.json` are
  **committed and pushed to the default branch** before `kb auto run`. `kb auto on` only
  edits the file. A dirty `.kb/` makes `kb publish` refuse, so no ticket would
  reach `done`, and the BA's Q&A worktree is checked out from the default branch,
  where the switch would still read `false`.
- Both repos' hub registry entries have `auto_merge: true` (the Registry page),
  and both repos have `intake:` set in `.kb/config.yaml`. Otherwise a merged
  publish PR never reaches the hub, no `hist` row lands and no story reaches
  `done`.
- `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN` in the environment of the
  terminal that runs the loop (the same values `kb mcp-setup` wrote to `.env`
  and `.mcp.json` uses).
- The `claude` CLI on the `PATH`, **logged in with a Claude subscription**. The
  runner never uses an API key and inherits whatever login `claude` has.
- Re-run `kb init --kind ba` or `kb init --kind dev` after upgrading the CLI: it
  writes the permission allowlist and refreshes the skills with their **Auto mode**
  sections and `/kb-auto`, and a Dev repo gets the new `dev-test-workflow` skill.

**The switch.** `.kb/config.yaml` of a `ba` or `dev` repo carries an `auto:`
block, off by default:

```yaml
auto:
  enabled: false
  qa_interval: 300     # seconds between Q&A checks
  idle_interval: 600   # seconds to wait when there is no work yet
  hotfix_base: ""      # branch a hotfix starts from and merges to; empty = main
```

An existing repo's `config.yaml` has no live `auto:` block (`kb init` only adds
it, commented, to a new one). `kb auto on` appends `auto:` with `enabled: true`
only, so add `qa_interval`, `idle_interval` or `hotfix_base` by hand to change them.

| Command | What it does |
|---|---|
| `kb auto on` | Sets `enabled: true` (comments and other keys stay), then prints one sentence: commit and push `.kb/config.yaml` and `.claude/settings.json` to the default branch before `kb auto run`. First prints the plain warnings: "Auto mode merges pull requests as admin, with no review. Turn it on only for a repo where that is acceptable."; and, when the hub's `federation/registry.yaml` lists **more than one `dev` repo**, that auto mode is built for one Dev per hub (a warning, not a refusal). A repo whose kind is not `ba` or `dev` exits `1` |
| `kb auto off` | Sets `enabled: false` (and prints the same commit sentence). A running loop stops at the next task boundary; it never kills a task midway |
| `kb auto status [--json]` | The switch, the intervals, `hotfix_base`, and the runner's `task`, `attempts`, `waiting_on` (question ids) and `stop_reason`, one `key: value` per line |
| `kb auto run [--once] [--hub URL]` | Run the loop in the foreground and log to stderr. Holds an OS lock on `.kb/auto/run.lock` (pid inside) for its lifetime: a second `kb auto run` in the same repo exits `1` with "already running (pid N)" while the first is alive; the OS drops the lock when the holder dies, so a file left by a crash is never stale. `--once` runs one step, prints its outcome (`ran`, `idle`, `waiting`, `stopped` or `done`) and exits `0` for every outcome except `stopped` (`2`). The loop exits `0` done, `2` stopped, `1` refused or error, `130` interrupted with Ctrl-C |

The switch is the single source of truth. A skill run by hand with the switch on
also takes the auto path.

**Preflight.** `kb auto run` refuses to start (exit `1`, every reason printed)
when the switch is off, the repo kind is not `ba`/`dev`, `intake:` is empty, or
the repo's hub registry entry is missing or lacks `auto_merge: true` (both the BA
repo and the Dev repo need it). It also refuses when `.kb/config.yaml` or
`.claude/settings.json` is untracked or has uncommitted changes, or when the
default branch's copy of `.kb/config.yaml` is missing or lacks `auto.enabled: true`:
commit and push the switch to the default branch first (the check reads `origin/<default>` after a fetch, because the skills and the Q&A worktree work from origin).

**One task, one fresh process.** The runner holds no model context. For each task
it starts a new `claude -p --output-format json --permission-mode acceptEdits`
process from the repo root (so `CLAUDE.md` and `.claude/settings.json` apply),
sends a prompt naming the skill and its argument (`/dev-implement-ticket
M-x-US3`), and reads the result when the process exits. The context is gone
before the next task starts. It never uses `--dangerously-skip-permissions` or
`bypassPermissions`. A task has a ceiling of 4 hours; past it the attempt counts
as failed.

**The BA loop.** Each turn the first of these that applies, from
`kb mission next --json`:

1. A story held by a **mission blocker** (an open D-row, or an unticked `## Open
   questions` row with `blocks:`): `/ba-mission-plan --amend <mission>`. The agent
   decides the D-row or answers the question, records why, and flips it to
   `DECIDED` or ticks it.
2. A story that is `draft`: `/ba-ticket-author --amend <ticket>`, until it passes.
3. The `Next:` story that is `to-draft`: `/ba-ticket-author <story>`.
4. Nothing to do: sleep `idle_interval`. The BA does not stop while Dev work is
   open.

Every task that changes the repo ends the same way: a branch, a PR, wait for CI,
fix and push until it is green, squash-merge. The merge to `main` triggers
`kb-publish-request.yml`, which publishes.

**The BA Q&A thread.** While the BA loop runs, a background thread checks the hub
every `qa_interval` for **open** questions on this repo's tickets. When there are
any and no answer is in progress, it runs `/ba-answer-questions` in a **separate
`claude -p` process in its own git worktree** (`.kb/auto/worktrees/qa`, branch
`auto/qa`), beside the main task: own context, own files. It answers from the
mission, the ticket and the KB, amends the ticket when the answer changes it,
re-ticks the Definition of Ready after a fresh-context check, and goes through the
same PR, green CI, merge, publish path. One answer at a time; new questions wait
for the next check. Whichever side merges second merges `main` in and re-runs
lint and check.

**The Dev loop.** One ticket at a time, from `kb mission next --from-hub --json`:

1. No workflow in `.github/workflows/` runs the repo's tests (none contains the
   marker `kb-test`): `/dev-test-workflow`, once. The agent writes `kb-test.yml`
   from the repo's languages and conventions, makes it pass and merges it. The
   Dev templates only ship `kb-pr-lint.yml` and `kb-code.yml`, which do not run
   the product's tests; "green" must mean tests ran. If your repo already has a
   workflow that runs its tests, the skill puts a `# kb-test:` comment in it
   instead of adding a second one.
2. **Bugs first**: an unparented `BUG-n` that is ready runs `/dev-fix-bug`. A
   hotfix branches from and merges to `main` unless `auto.hotfix_base` names a
   production branch.
3. Then the first `ready` unparented ticket that is not a bug (a ticket with no
   mission): `/dev-implement-ticket <id>`.
4. Then the first `ready` story in mission order **whose dependencies are all
   `done`**: `/dev-implement-ticket <id>`: design, plan, execute, handover with
   GATE 1 to 4 decided by the agent, then PR, green CI, merge, and `kb publish` so
   the `hist` row reaches the hub and the story shows `done`.

**Waiting on Q&A.** When a business question blocks a ticket the task ends
`blocked-qa Q<ids>`. The Dev does not start another ticket; the loop sleeps
`qa_interval`, checks those questions, and when **all** are `answered` (not just
`waiting`: the amended ticket must be on the hub) re-runs the same task in a fresh
process, which picks up the answers as it always does. The BA side does the
answering, in its Q&A thread.

**Stop rules.**

- **Two failed attempts stop the loop.** A task that ends `failed` twice stops it.
  A red CI that two fix rounds did not turn green (`ci-red`) stops it at once.
  `kb auto status` shows `stop_reason`; the log says which ticket, PR and checks.
  Fix the problem, then `kb auto run` again: it clears the stop and **resumes the
  same task** with fresh attempts.
- **A task that ended `done` is still picked.** The hub may not show it as `done`
  yet (the publish PR is still merging). The runner does not run it again: it
  waits `idle_interval` and checks again, and after 5 checks it stops with
  `<task> ended done but is still picked after 5 checks`.
- **The BA's Q&A thread fails twice in a row.** Two answer runs in a row that did
  not end `done` stop the loop with `qa thread: <reason>`. A usage-limit wait does
  not count.
- **Usage limit.** When `claude` reports the subscription limit, the task is
  retried after 15, then 30, then 60 minutes (and 60 from then on); the backoff
  resets after any other result. A usage-limit wait never counts as a failed
  attempt.
- **`kb auto off`** stops the loop at the next task boundary (`stop_reason:
  switched off`).
- **Done.** Before each task the runner checks the hub. When every mission story
  and every unparented ticket and bug is `done` it logs a summary and exits `0`.
  The BA side also needs no open question. A ticket without a mission or a bug is
  `done` when its id appears in a `hist.*` row of the Dev repo's `-svc` document,
  which `/dev-handover` writes only after the work, and which reaches the hub
  only after the PR merged and the Dev published.
- A crash or restart re-reads the state and re-runs the same task; the skills
  resume from `docs/impl/<id>/`, the branch and the open PR.

**State and logs.** `.kb/auto/` (git-ignored by `kb init`): `state.json` (current
task, attempts, the question ids it waits on, the stop reason), `logs/` (one file
per task: prompt, output, exit code, duration) and `worktrees/qa`.

**What the agent decides.** Each human gate has an auto path. The agent first
self-reviews, with a fresh-context reviewer subagent for anything the skill
already reviews, and writes down what it checked and why it chose.

| Gate (human today) | Skill | In auto mode |
|---|---|---|
| Pick the KB references ("never auto-pick") | `ba-ticket-author` | Picks the best-matching ones, notes why |
| DoR box "Every AC is Given/When/Then" | `ba-ticket-author` | Reviews every AC; ticks only if all pass, else rewrites first (two rounds, then `failed ac-quality`) |
| Amend asks the BA for the trigger | `ba-ticket-author` | The trigger comes from the runner (D-row, Q&A, failing check) |
| D-row `OPEN` to `DECIDED`; mission open question with `blocks:` | `ba-mission-plan` | Decides or answers with reasons in the change log; ticks it |
| "Never answer a question yourself" | `ba-answer-questions` | Answers from mission, ticket and KB; amends and re-ticks the DoR |
| BA skills never commit, push or publish | BA skills | Branch, PR, green CI, merge, publish |
| `/kb-publish` go/no-go | `kb-publish` | Reviews the diff and proceeds, or ends `failed publish-review` |
| GATE 1 design approval, GATE 2 plan approval | `dev-design`, `dev-plan` | The independent review is the approval; a clean review flips `status: approved`; two fix rounds, then `failed design-review` / `failed plan-review` |
| Build and test commands | `dev-plan` | Read from the repo (CI config, conventions, manifests); none found ends `failed no-test-command` |
| "Let the Dev choose" on findings; stale citations, `[warn]`, unmerged dependencies | Dev skills | The agent chooses and notes why; a real blocker becomes a BA question |
| GATE 3/4: a human opens and merges the PR | `dev-handover` | Opens the PR, fixes CI until green, merges, then `kb publish` |
| Branch only once the Dev agrees; hotfix asks which line | `dev-fix-bug` | Branches at once; base from `auto.hotfix_base`, else `main` |
| Open blocking question stops the ticket | `dev-implement-ticket` | Stops and reports `blocked-qa <ids>` to the runner |

Every decision leaves an **`**Auto decision:**`** line: in the BA's `## Change
log` (under the table), in the Dev's `docs/impl/<id>/auto-decisions.md` (copied
into the PR's `## Notes`), or in the reply of `kb-publish`.

**The `AUTO-RESULT:` contract.** The runner's prompt asks for one last line of
the reply, in one of three forms. A skill you write yourself and want the runner
to drive must end the same way:

```
AUTO-RESULT: done
AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]
AUTO-RESULT: failed <reason>
```

No text may follow it. A missing or malformed line counts as a failed attempt
(`no result line`, `bad result line`).

**Permission allowlist.** `kb init --kind ba|dev` writes `.claude/settings.json`
(beside the usage hooks) so a headless run does not stop on a permission prompt.
It is **merged** into an existing file: your own entries stay, only what is
missing is added, and an unchanged file is not rewritten. `--force` replaces the
whole file instead. A file that is not valid JSON is left alone with a note.

- **Allowed:** `git` (add, commit, status, diff, log, fetch, `pull origin`, switch
  to `auto/*`, `fix/*` and `hotfix/*`, `switch -c`, `checkout -b`, branch, worktree,
  merge, `push -u origin HEAD`, `push origin HEAD`, bare `pull`), `gh pr`, `gh run` (view, watch, rerun, list), file
  `Read`, `Edit` and `Write`, the `strata-kb` MCP tools, and `kb` subcommands
  (`mission`, `ticket`, `publish`, `svc`, `impl`, `plan`, `pr`, `resolve`,
  `context`, `query`, `doctor`, `code-ingest`, `usage`, `auto`, `status`,
  `diff`, `plan-ingest`). `kb auto on|off|run` are allowed so `/kb-auto` works in
  your own session. A task process the loop starts carries `STRATA_KB_AUTO_TASK=1`,
  under which `kb auto on`, `off` and `run` refuse (`status` still works), so a task
  can neither flip the switch nor start a second loop — in the main tree or in the
  BA Q&A worktree.
- **Per language (Dev repos):** test, install, lint and build commands for each
  language in `.kb/config.yaml` `langs:`, from `LANG_COMMANDS` in
  `initcmd.py`: for example `pytest`, `uv sync`, `ruff`, `pyright` for Python;
  `npm test`, `npm ci`, `npm run lint`, `npm run build`, `npx tsc` for TypeScript;
  `go test`, `go build`, `go vet`; `cargo test`, `cargo clippy`; `mvn test`,
  `./gradlew test`; `dotnet test`; `composer install`, `vendor/bin/phpunit`;
  `flutter test`, `dart analyze`; `swift test`. A Dev repo with no recorded
  language gets none.
- **Denied:** any `git push` that names `main` or `master`, force-push, `+` or `:`
  refspecs and `--delete`; `git checkout`, `switch` and `branch` forms that move
  onto, create, rename or delete `main` or `master` (a branch id that merely
  contains the word, like `auto/M-domain-US1`, is fine); `git reset --hard`; `gh repo delete`, `gh run delete`; `kb init`;
  `rm -rf /*`; editing or writing `.claude/settings.json`,
  `.claude/settings.local.json` and `.git/**`.

**Hub side.** 1.29.0 adds `GET /api/questions` (same bearer token as the rest of
`/api`; params `repo`, `ticket`, `status` = `open` (default), `waiting`,
`answered` or `all`). It is read-only JSON, `{"questions": [...]}`, and the
runner uses it instead of MCP. **Upgrade the hub to 1.29.0 before a runner polls
Q&A.** `kb mission next --from-hub --json` (and the MCP tool `kb_mission_next`)
gain `unparented`, the tickets and bugs without a mission with their statuses,
and every story and ticket carries `depends_on`.

**Known limits.**

- Usage-limit waits follow the 15 / 30 / 60 minute ladder; a reset time in the
  message is not parsed.
- The skills run `git fetch origin main`: the default branch must
  be `main`.
- A tool outside the allowlist and the per-language table is denied, and a Dev task
  ends `failed command-denied <command>`. Widen `.claude/settings.json` by hand
  (add the command to `permissions.allow`), then `kb auto run`.
- One BA repo and one Dev repo per hub, one ticket at a time per repo. The BA's Q&A
  thread is the only concurrency.

#### On Claude Code cloud

`/kb-auto run` also works in a Claude Code cloud session, with no local machine.
Cloud is detected from `CLAUDE_CODE_REMOTE` (`STRATA_KB_CLOUD=1|0` forces it).
Set `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN` in the cloud environment; the
hub must be **1.30.0 or later** (`GET /api/plan/next`, `GET /api/registry/entry`,
`POST /api/resolve`). On cloud the runner, `kb auto on`, `kb resolve` and
`kb mission next [--from-hub]` read the hub live through those routes and copy
nothing from it; every other hub-reading `kb` command refuses and points at the
`strata-kb` MCP tools. `kb pr find|view|open|checks|merge|edit` talk to the GitHub
REST API (`gh api`), because GraphQL is blocked there; the skills call `kb pr`, not
`gh pr`. The origin must be a plain GitHub URL.

`/kb-auto run` there stays on the session's `claude/...` branch. When the default
branch's switch is off it opens an `auto/switch` PR that flips only `auto.enabled`
(it stops if the default branch's `.claude/settings.json` differs), waits for green
checks, admin squash-merges it after telling you, starts `kb auto run` detached and
keeps `kb auto wait [--max 6600] [--interval 30]` armed in the background.
**The session must stay open** for the whole run. Not verified on real cloud yet:
a session lasting over 3 h, pushing `auto/*` branches, an admin merge past a
required review, `gh run` over REST. `kb publish --branch` (used by `kb-code-sync`)
still opens its PR through `gh pr` and fails on cloud. `/kb-auto run` is re-runnable:
it removes a leftover local `auto/switch` worktree and branch itself. A switch PR left
open by a failed run (red checks, merge error) and its remote `auto/switch` branch must
be closed and deleted on GitHub by hand first; the skill stops and says so, and never
force-pushes.

---

## 14. Reviewing content

If you were asked to review a pull request changing `.kb/`, this is the whole
job. No commands, no code — read the diff like a document with tracked changes.

- [ ] **Read the new prose** (L2 — the `.md` files without `.raw`). Does it match
      your understanding of the subject?
- [ ] **Cross-check the source document.** Did the summary omit anything
      important, or add anything that is not in the original?
- [ ] **Check every code, identifier, number and unit.** They must be exactly as
      in the source, not rephrased.
- [ ] **Tables:** you do not need to verify that summary tables match the
      originals — `kb build` already checked and would have blocked the PR. Do
      glance for extraction errors (a misread row or column) against the source;
      machines do not catch those.
- [ ] **One-line summaries in `_manifest.yaml`** (L1). Do they correctly say what
      the section is about, so search can find it later?
- [ ] If something is wrong, **edit the `.md` or `.yaml` directly in the web UI**,
      comment why, or ask the author to fix it.

Merging that PR is the subject-matter sign-off — not an AI draft. It does not yet
make the content searchable: `kb publish` mirrors it to the hub and opens a
second PR *there*, and merging that one is what makes it live.

---

## 15. Configuration

### `.kb/config.yaml`

| Key | Meaning |
|---|---|
| `kind` | `hub`, `child`, `ba` or `dev` — set by `kb init`, reused on re-runs |
| `hub` | Hub location: a git URL or a local directory. Mandatory for every command that reads the federation. Committed with the file, so it carries no credential — a URL that needs one goes in `STRATA_KB_HUB`. |
| `repo_id` | This repo's entry id under `federation/` |
| `intake` | Intake service URL for `kb ci-publish` (child, `dev` and `ba` repos; http(s) only) |
| `asset_store` | `{mode: none}` (default) or `{mode: s3, bucket: …}` |
| `auto` | `ba` and `dev` repos: `{enabled: false, qa_interval: 300, idle_interval: 600, hotfix_base: ""}` — the full-auto switch and its poll intervals in seconds; see [Full-auto mode](#full-auto-mode) |

### Environment variables

| Variable | Meaning |
|---|---|
| `STRATA_KB_HUB` | Hub location — overrides `.kb/config.yaml`, overridden by `--hub` |
| `STRATA_KB_HUB_URL` | Base URL of the hub's HTTP service, for MCP clients |
| `STRATA_KB_HTTP_TOKEN` | Bearer token for the HTTP MCP server, REST API and Web UI |
| `STRATA_KB_HUB_CACHE` | Local hub clone directory (default `~/.strata-kb/hub/`) |
| `STRATA_KB_HUB_TTL` | How long the local hub clone is considered fresh |
| `STRATA_KB_HUB_PULL_INTERVAL` | HTTP server only: seconds between automatic hub pulls (default `300`, `0` = off) |
| `STRATA_KB_INTAKE` | Intake service URL (http(s) only) |
| `STRATA_KB_INTAKE_AUDIENCE` | OIDC audience the intake expects |
| `STRATA_KB_TRUSTED_PROXIES` | Number of trusted reverse proxies (default `0`) — see [§10](#10-mcp-server-and-web-ui) |
| `STRATA_KB_ALLOWED_HOSTS` | HTTP server only: host names `/mcp` accepts besides localhost, comma-separated (e.g. `kb.example.com`); unset, `/mcp` behind a proxy at a real name answers `421 Invalid Host header` |
| `STRATA_KB_GH_APP_ID` / `STRATA_KB_GH_APP_KEY` | GitHub App credentials for the intake service, and for `hub-sync`'s `kb-code-sync` issue (needs `issues: write`, `pull_requests: read`, `contents: read`) |
| `STRATA_KB_GH_TOKEN` | Token for `hub-sync`'s issue calls when no GitHub App is configured (needs `issues: write`, `pull_requests: read`, `contents: read` on the hub repo) |
| `STRATA_KB_CODE_SYNC_INTERVAL` | Seconds between `hub-sync` scans (default `86400`) |

---

## 16. Exit codes

| Exit | Meaning |
|---|---|
| `0` | Success |
| `1` | error — including a misconfiguration (bad flag combination, missing required setting) |
| `2` | citation stale — `kb resolve`, `kb doctor --context`, `kb ticket lint --fail-on-stale`, `kb mission lint --fail-on-stale`; `kb doctor` also exits 2, with or without `--context`, when the hub cache itself is stale (a failed pull) |

Caveat: the CLI framework emits `2` of its own accord for an unrecognised flag or
a bad parameter type. A CI script that must distinguish "stale" from "you called
me wrong" should check which command it ran, not only the code.

---

## 17. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `kb build`: "table mismatch" | A table was edited, added, duplicated or reordered in L2 | Open the section's `.raw.md` (L3), copy the table verbatim, paste over the `.md` (L2) |
| `kb build`: sections still `pending`/`TODO` | Summarization did not finish, failed, or was skipped | `kb status` to see what is left, then `kb summarize` to retry — or `/kb-summarize` with no LLM CLI installed |
| `kb ingest` is very slow on the first run | Normal — a layout model (~500 MB) is downloading | Wait. Later runs use the cache. |
| `kb: command not found` | Virtualenv not activated | `source .venv/bin/activate` |
| MCP server fails to start: "Executable not found in $PATH: python" | `.mcp.json` calls `python`, but the system only has `python3` or the venv is not on `PATH` | Point the `command` at an absolute interpreter path, e.g. `.venv/bin/python` |
| Every hub command fails with a git auth error | git older than 2.31 with a credentialed `hub:` URL | Upgrade git, or switch `hub:` to ssh — see [Requirements](#requirements) |
| `kb query` returns nothing | No tag or content match, or `--budget` too small | Drop `--tags`, raise `--budget`, check spelling — and query in the document's own language |
| `kb publish` refuses on a governed hub | `gh` cannot open a PR on that host | Authenticate `gh` for the host (`GH_HOST=<host>` for Enterprise) until `gh repo view` succeeds inside the hub clone, then `--pr` |
| `kb publish` in a `ba` repo takes the snapshot route, or the intake rejects the tag | `intake:` is empty in `.kb/config.yaml`, or the repo is not in the hub's `federation/registry.yaml` (or a `workflow:` pin is set, which never matches a tag-triggered publish) | Set `intake:`, and ask the hub operator to map the repo's `owner/repo` to your `repo_id` in the registry, with no `workflow:` pin — see [§12](#12-ba-repos--tickets-and-missions) |
| A mission or ticket is missing from `<repo_id>-plan` | It did not qualify | `kb plan-ingest` prints a `skipped: <file> — <reason>` line for each; fix what it names |
| `kb ticket fetch <id>` exits `1` | The id is not on the hub (the BA has not published it), or several repos hold it | Ask the BA to `kb publish`, or qualify the id as `<repo>:<id>`, or pass the ticket by path or paste |
| `kb doctor` names files inside a federation entry | An older publish mirrored more than `.kb/` artefacts | Publish again to strip them, and **rotate any credential they contained** — removing a file does not remove it from git history |

---

## 18. FAQ

**Why aren't source documents in Git?**
They are frequently copyrighted or otherwise restricted, so they must not go into
a shared repo. They live only on local machines under `source/`. `kb init`
writes a `.gitignore` there (and in `sources/`) that ignores every file, and
`kb doctor` warns about any file in either folder that git already tracks.

**An AI wrote the summaries — how do we trust them?**
Three layers. (1) The model is bound by strict style rules: no invention, codes
and numbers verbatim. (2) Tables — the easiest thing to get wrong — never pass
through the model; they are machine-copied and automatically verified. (3) A
human always reviews before merge. AI drafts; it cannot publish.

**What is a "token", and why does it keep coming up?**
It is the unit of text a model processes, roughly a word. It drives the cost and
latency of every call. The four-layer architecture exists mainly to cut tokens
per lookup while keeping accuracy.

**Do I need to write code to review content?**
No. See [§14](#14-reviewing-content) — it is reading `.md` and `.yaml` files in a
web diff.

**Can I use a model API instead of a CLI subscription?**
The summarize step shells out to a headless LLM CLI (`claude`, `copilot`) rather
than calling an API directly, so it runs on an existing subscription. That
affects operations, not quality.

**Is `status: reviewed` set automatically?**
No. `kb approve` is a deliberate human action. The operative gate is the pull
request that `kb publish` opens on the hub — content is unreachable through
`kb query`, MCP and the Web UI until that merges. Use `kb approve` when you want
a per-section marker, and `kb publish --require-reviewed` to enforce it.

---

## 19. Development and release

Run the whole verification gate locally before tagging:

```bash
./scripts/gate.sh
```

It runs the same tiers CI runs, on one interpreter and one OS. Green here catches
a red PR before you push; it is not the matrix. CI additionally runs
ubuntu × 3.11/3.12/3.13 plus windows-latest.

| Tier | What it does |
|---|---|
| **T0** | `ruff check .`, `ruff format --check .`, and `pyright` (basic mode, `src/`) |
| **T1** | `pytest` against the source tree |
| **T2** | Build wheel + sdist, `uv lock --check`, `twine check`, install the wheel into a clean venv, verify `kb --version` matches `pyproject.toml` (and the tag when releasing), and confirm `tests/`, `.kb/` and `sources/` never enter the package |
| **T2b** | Install the built sdist into a separate clean venv, run `kb --version`, and load a packaged template through `importlib.resources` |
| **T3** | The real user journey **from the installed wheel**: `kb init` → load an already-ingested fixture → `summarize` → `build` → `publish` → `query`/`get`/`context`/`resolve`/`diff` → `doctor`. It does not run a real PDF ingest — that needs the `[ingest]` extra (~2 GB) and a document that must never be committed — it verifies only that `kb ingest` fails cleanly without the extra, rather than with a traceback. |
| **T4** | Backward compatibility with older `.kb/` stores, the MCP contract, golden output, and federation compatibility |

Then:

```bash
# 1. Bump the version in pyproject.toml
uv lock
git commit -am "chore: bump to X.Y.Z"

# 2. Tag. CI re-runs the whole gate plus the image build and smoke test,
#    and publishes only when everything is green.
git tag vX.Y.Z && git push --tags
```

A tag runs nothing different from a pull request — `.github/workflows/_gate.yml`
is shared by both. **If any tier is red, nothing is published.** PyPI is
immutable, so `release.yml` publishes only after both the gate and the Docker
image (built with the real `[ingest]` extra) are green, and `:latest`/`:vX.Y.Z`
on GHCR move only after the PyPI publish succeeds. To retry a tag:

```bash
git push --delete origin vX.Y.Z
git tag -d vX.Y.Z
```

---

## License

Apache-2.0. See [LICENSE](LICENSE).
