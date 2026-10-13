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
preserves `.kb/index.yaml`, `.kb/config.yaml` and `.claude/settings.json` unless
`--force`. `--lang <id>` (dev, repeatable) forces a conventions pack whose
manifest is not detectable; `--assets none|s3` (hub) records the asset store.

Slash commands are scaffolded for **Claude Code, GitHub Copilot and
Cursor**: `/kb-ingest`, `/kb-summarize`, `/kb-approve`, `/kb-publish`,
`/kb-docker-setup` on hub and child repos; `/ba-ticket-author`,
`/ba-mission-plan`, `/sa-ticket-ground` and `/kb-publish` (it publishes the
plan) on a `ba` repo; the five
dev-workflow commands on a `dev` repo. MCP client wiring ships as
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
| `kb plan waves` | Dependency waves of a dev plan: which tasks can run in parallel lanes; errors on a shared file without a dependency, a cycle, or a missing `Depends on:` line |
| `kb assets` | Asset store operations on a hub: `migrate`, `verify` |
| `kb usage` | Token/cost measurement: ingest transcripts, record rows, render a report |

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
`{repo_id, kind, workflow?}` with `kind` one of `kb`, `ba`, `dev`:

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
# → human:  http://<host>:8321/ui      (sign in with the token; cookie stored)
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

### Menus — Overview, Document, Ticket, Code

The left rail is **Overview · Document · Ticket · Code**. Each menu lists one
kind and has its own search box, which is a real search (`kb query` with that
kind) rendered inside the menu; the tag cloud follows the menu. Overview counts
documents per kind.

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

### The eight MCP tools

| Tool | Purpose | Main params |
|---|---|---|
| `kb_search` | Find sections by natural language and return L2 within a token budget. Ranking is capped: each leg is capped at 50 results before fusion, and the tool says so when matches were dropped. It also flags when the top two results are the same section published by two repos, when their keyword scores tie exactly, or when both are hybrid-confirmed within the ambiguity ratio. | `query`, `tags`, `budget`, `kinds` |
| `kb_get_section` | Fetch exactly one section | `doc`, `section`, `level` |
| `kb_context_new` | Pin a `kb-context` citation block at the hub's current commit, from confirmed refs | `refs`, `tags` |
| `kb_resolve` | Resolve a `kb-context` block (or a ticket containing one) — sections at the pinned version plus freshness | `kb_context` |
| `kb_ticket_lint` | Run the Definition-of-Ready gate over a draft ticket. The `> Parent mission:` back-link is checked when `ticket_id` is passed: against `mission_markdown`, else the mission on the hub's plan | `ticket_markdown`, `ticket_id`, `mission_markdown` |
| `kb_ticket_check` | Run the SA grounding gate (`kb ticket check`) against the hub's `-code` document, a moved revision judged from hub history. `[NEW: D<n>]` reads `mission_markdown`, else the hub's plan; no local `-code` fallback | `ticket_markdown`, `mission_markdown`, `heading` |
| `kb_mission_next` | Which story next, from the plans published on the hub — the `kb mission next --from-hub` report (a BA's unpublished `missions/` and `tickets/` need the CLI) | `repo` |
| `kb_doctor_hub` | The hub's side of `kb doctor` for a child, ba or dev repo, as JSON: the hub's strata-kb version, whether `federation/<repo_id>` is published and its digest, the hub's `-code` section digests, the registry's kind pin, citation checks. Called by the CLI, not meant for agents | `kind`, `repo_id`, `remote_url`, `dir_name`, `kb_context` |

### Security

Every response carries CSP (`script-src 'self'`), `X-Frame-Options: DENY`,
nosniff, `Referrer-Policy` and `Permissions-Policy`; HSTS on https. The `/ui`
session cookie is a signed, expiring value derived from the token, never the
token itself. `POST /ui/logout` ends a session. The server refuses to start on
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

HTTP auth stops at a bearer token — one fixed secret, no OAuth or SSO. That is
adequate for an internal network and not ready for the public internet.

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
`## Technical grounding` — service, files, tables, routes, externals and the
test command, each a section id that exists in the hub's `<repo>-code`
document, or `[NEW: <reason>]`, or parked under `Open decisions`. It has no
repository access and never infers: internal flow, failure modes and request
bodies are not in the document, so they go to `Open decisions` for the Dev.
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
is one or more of `kb-context`, `architecture`, `scope`, `delivery`; lint fails
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
| `kb ticket check <file\|-> [--kb-dir <dir>] [--hub <url>] [--json] [--missions-dir <dir>] [--heading <h2>]` | SA grounding gate: every `svc.* / db.* / api.* / int.* / cmd.*` id in `## Technical grounding` exists in the hub's `<repo>-code` first (the copy the SA grounded on), then a local `--kb-dir` copy with a `(local fallback — …)` note, columns / routes / commands match its tables, `Files:` are in `struct.tree`, every `[NEW: D<n>]` names a `DECIDED` row of the parent mission's `## Technology decisions` (`--missions-dir`, default the sibling `missions/`; a mission missing there is read from the hub's plan), and `Open decisions` is empty. A `Grounded on:` revision that moved is not a failure by itself: when every cited fact still holds it is a PASS with a `[note]`, or a `[warn]` plus a unified diff of each changed cited section; when one is gone it is a FAIL (`grounding drifted since @<old> (now @<new>) and no longer holds — re-run /sa-ticket-ground`). `dev-implement-ticket` runs it right after Intake. `--heading "## Services & order"` checks a mission plan's SA section against its own decisions table | `0` PASS, `1` FAIL |
| `kb mission next [--missions-dir <dir>] [--tickets-dir <dir>] [--repo-id <id>] [--kb-dir <dir>] [--hub <url>] [--json]` | Read-only: every backlog story across `missions/` as `done` (its id is in a `hist.*` row of the hub's `-svc` document), `ready` (a ticket file exists under `tickets/` — flat or `tickets/<mission-id>/` — with every `## Definition of Ready` box ticked), `draft` (a ticket file with an unticked box, reason `DoR n/m ticked`, or no `## Definition of Ready` section, reason `no Definition of Ready section`), `to-draft` (no ticket, every `Depends on` done, every D-row that `Blocks` it `DECIDED`) or `blocked` (reasons named); ends with `Next: <us-id> — <title>` naming the first `to-draft` story. The `-svc` document is derived from the missions' `Grounded on:` line (a comma-separated list is read, the `-code` entry wins; `<x>-code` → `<x>-svc`, `--repo-id` overrides); `--kb-dir` is read first when it holds the `-svc` document (a dev machine), the hub second; no `Grounded on:` line, an unconfigured or unreachable hub, a `-svc` not on the hub, and a missing tickets dir are each a `note:` line, never a red line | `0` after a report; `1` for a bad directory flag or a malformed `.kb/config.yaml` |
| `kb ticket tidy [--tickets-dir <dir>] [--into <folder> <file>...]` | Move each flat `tickets/*.md` whose `> Parent mission: M-x [@ rev N]` line is valid to `tickets/M-x/<name>`; print `moved:` per file, `conflict:` when the destination exists (nothing is overwritten), `unsorted:` for a file without a parent mission, `note:` for an unreadable file or a FILE under `--into` that is not a flat file directly under tickets/. With `--into`, move the named files into `tickets/<folder>/` instead. Idempotent; no git — commit the renames yourself | `0` after a report; `1` for a bad `--tickets-dir`, a bad `--into` name, FILES without `--into`, or `--into` without files |

Mission lint is deliberately **CLI-only**: its distinguishing checks need
filesystem access to the sibling `tickets/` directory that a shared MCP server
does not have. Ticket lint and ticket check run over MCP too
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

### `kb code-ingest` — the generated document

Extracts a codebase's structure into `.kb/<repo_id>-code/` — **deterministic and
LLM-free**: pure functions of the working tree, no network call. The output is an
ordinary 4-layer document, so build, query, federation and the Web UI read it
with zero special-casing.

Not shipped: relationship sections (`rel.<name>`) and an AST extractor, both
planned in Architecture v0.4 §14.1. The extractors read build, deploy and
contract files — manifests, compose files, migrations, OpenAPI — never source
syntax.

```
kb code-ingest [--repo-root .] [--kb-dir .kb] [--repo-id <cfg>]
               [--doc-id <repo_id>-code] [--db <path>]... [--tags "a,b"]
               [--scaffold-svc] [--json]
```

Seven extractors, organised by **artifact kind rather than language**, because
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

`tree` always finds something, so the zero-detection rule is: `kb code-ingest`
exits `1` when **no extractor other than `tree`** found anything. A document
holding only a folder listing is a misconfiguration, not knowledge.

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
nowhere. `RENAME`/`DROP` and `ADD CONSTRAINT`/`INDEX` warn as out of scope. A
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
not titled `… — code knowledge`, or lists a section id outside the seven
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
3. **Auto-merge vs. review.** `-code` is machine fact and may be auto-merged by
   hub policy; `-svc` is a human claim and always needs review. One document can't carry
   both publish policies at once.

The two are joined by **section id, not by file**: `svc.<name>` deliberately
exists in both. `-code §svc.<name>` supplies `alias`/`label`/`technology`,
`-svc §svc.<name>` supplies `description` — together filling all four arguments
of a C4 `Container(alias, label, technology, description)`.

**Section-id prefix contract.** Each prefix has exactly one owner. The BA agent,
the Dev workflow and future tooling key on these, so they are stable:

| Prefix | Document | Owner | Content |
|---|---|---|---|
| `struct.tree` | `-code` | extractor | package/folder layout and entry points |
| `svc.<name>` | `-code` | extractor | image, ports, `depends_on`, detected technology |
| `db.<table>` | `-code` | extractor | columns, types, PK/FK, DDL |
| `dep.<ecosystem>` | `-code` | extractor | direct dependencies and framework detection |
| `int.<name>` | `-code` | extractor | external integrations, keys only |
| `api.<tag>` | `-code` | extractor | endpoints from an in-repo OpenAPI contract |
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
- **Decide the hub's auto-merge policy for `-code` PRs, and exclude `-svc`.**
  This is a constraint on *how* the policy is implemented: `kb ci-publish` opens
  one hub PR per publish, not per document — the intake keys the publish branch by
  repo id and reuses it while a PR is pending — so a publish carrying both a
  regenerated `-code` and an already-merged `-svc` amend lands both in one PR.
  The rule must therefore be **path-scoped to `.kb/<repo_id>-code/**`**, never a
  whole-PR or whole-repo rule, or it will auto-merge `-svc` content riding
  along.
- **Run `kb mcp-setup`** (or `/kb-mcp-setup`) for each developer — it writes
  `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN` into `.env` and verifies them.
- **Budget the one-time seed:** ~10–15 min per service.

`kb-code.yml` ships two jobs: on a `kb-publish/*` tag (pushed by `kb publish`)
it regenerates `-code`, builds and publishes; on `pull_request` it runs
`kb build` only and **never publishes**. A push to the default branch publishes
nothing: the intake accepts a publish only from a `kb-publish/*` tag, so a dev
repo publishes with `kb publish` after a merge, like a `ba` repo. `--scaffold-svc` is deliberately never passed in CI — CI
must never create `pending` content, since that would fail its own build step.

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
