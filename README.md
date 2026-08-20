# CENTER-KB — A structured knowledge base that knows how to summarize itself

> This guide is written for **non-technical readers** (domain SMEs, reviewers, project managers). If you only need to understand the system and how to review, reading start to finish is enough. If you need to run commands, sections [7](#7-kb-command-dictionary) and [8](#8-end-to-end-workflow-step-by-step) have real, copy-paste examples.
>
> CENTER-KB is domain-agnostic — it turns *any* large, structured reference document (technical standards, regulations, internal specs, compliance manuals, engineering handbooks…) into a layered, AI-queryable, human-reviewable knowledge base. The worked examples throughout this guide happen to use an aviation standards dataset (ARINC 424, ICAO Annex 3) because that's the demo data bundled in this repo — nothing about the tool itself is aviation-specific. Swap in any PDF-based reference material for your own domain.

---

## Table of contents

1. [30-second summary](#1-30-second-summary)
2. [The problem CENTER-KB solves](#2-the-problem-center-kb-solves)
3. [Core idea: 4 layers L0 → L1 → L2 → L3](#3-core-idea-4-layers-l0--l1--l2--l3)
4. [How a document moves through the system](#4-how-a-document-moves-through-the-system)
5. [Directory layout — what lives where](#5-directory-layout--what-lives-where)
6. [Installation (first-time setup)](#6-installation-first-time-setup)
7. [`kb` command dictionary](#7-kb-command-dictionary)
8. [End-to-end workflow, step by step](#8-end-to-end-workflow-step-by-step)
9. [SME review role — checklist](#9-sme-review-role--checklist)
10. [Proof it works (real PoC numbers)](#10-proof-it-works-real-poc-numbers)
11. [Current limits & unfinished work](#11-current-limits--unfinished-work)
12. [FAQ](#12-faq)
13. [What to do when something breaks](#13-what-to-do-when-something-breaks)

---

## 1. 30-second summary

CENTER-KB takes **hundreds-of-pages** reference documents — technical standards, regulations, internal specs, compliance manuals (this repo's demo data: ARINC 424, ICAO Annex 3) — and turns them into a **structured knowledge base** where:

- **People** can read plain text/markdown files (no special software) and review via Pull Request — like reviewing a Word doc with track changes.
- **AI assistants** (such as Claude) can look up **exactly the needed passage**, instead of stuffing hundreds of thousands of tokens from the whole document into every question — saving **over 90% cost** per query.

No server, no database. The entire knowledge base is `.yaml` and `.md` files under `.kb/`, managed with Git just like code — the "**docs as code**" philosophy.

---

## 2. The problem CENTER-KB solves

Long reference documents — regardless of domain — share two painful traits:

| Trait | Why it hurts |
|---|---|
| **Very long** — hundreds of pages is normal for a standard, regulation, or spec (this repo's demo: ARINC 424 is 487 pages, ICAO Annex 3 is 224) | Nobody (human or AI) re-reads the whole document just to look up one field |
| **Tables that matter character-by-character** — codes, field lengths, character types, thresholds | If you summarize in prose (even with AI), it is easy to **miscopy one character in a table** → dangerous drift for whatever system relies on that data |

CENTER-KB addresses both at once:

- **Split by section** (e.g. in the demo data, each ARINC 424 field is its own section: §5.129 "Restrictive Airspace Designation") so lookup hits the right place, not the whole file.
- **Tables never go through AI for "rephrasing"** — tables are extracted verbatim by code (not rewritten by AI), and an automated check ensures tables in the summary **match 100%** the original. This is the system's most important safety latch (see section 3).

---

## 3. Core idea: 4 layers L0 → L1 → L2 → L3

Think of a **library lookup stack** with 4 layers from coarse to fine — like finding a book: department catalog → book table of contents → chapter summary → full text.

| Layer | Name | What it is | Size | Example in this repo's demo data |
|---|---|---|---|---|
| **L0** | Master catalog | A single `index.yaml` listing **every document** in the store: name, revision, tags, one-line description | Tiny (187 "tokens" for the whole store — see section 10) | `.kb/index.yaml` |
| **L1** | Detailed TOC | Per document, a `_manifest.yaml` listing **each section**: id, title, one-line summary (≤ 25 words), status | Tens of thousands of tokens per document | `.kb/arinc-424/_manifest.yaml` |
| **L2** | Condensed summary | `.md` file — prose condensed to ~20–30% of original length **in the source document's language**, **tables kept verbatim 100%** | Medium | `.kb/arinc-424/ch5-navigation-data-field-definitions.md` |
| **L3** | Full original | `.md` file — full text extracted from the PDF, nothing cut | Largest | `.kb/arinc-424/ch5-navigation-data-field-definitions.raw.md` |

**Why four layers instead of one copy?**
A typical lookup only needs L0 (which docs matter) → L1 (which sections matter — almost free, one-line summaries) → L2 (condensed content of the 1–4 relevant sections). Only when you need absolute legal/technical fidelity do you open L3. That way an AI can answer while loading only a tiny slice of the whole store.

### Concrete example — section §5.4 "Section Code"

**L1 (in the manifest — one search-oriented summary line):**
> Defines the Section Code field (SEC CODE) identifying the major navigation database section for a record, per Table 5-1, 1 alpha character.

**L2 (condensed prose in the `.md` file):**
> The Section Code field (SEC CODE) defines the major section of the navigation system database in which a record resides, per the encoding scheme in Table 5-1. Used on all records; length 1 character; alpha.

And immediately below is **Table 5-1 copied verbatim** — never rewritten by AI, because code extracts it straight from the PDF.

**Non-negotiable rule:** tables are **never** rewritten by AI. AI may only write the prose summary around tables; the tables themselves are always machine-copied from the source PDF at both L2 and L3. Before a change is accepted into the store (`kb build`), the system **automatically diffs every L2 table against L3** — if even one character differs, `kb build` fails and blocks the change.

---

## 4. How a document moves through the system

```
   Source PDF (487 pages, copyrighted)
          │
          │  kb ingest   ← step 1: machine, automatic
          ▼
   Split PDF into ~100–300 small "sections"
   (each field/item is one section, with standard ids: §5.3, §ch2, §appendix-3...)
          │
          ▼
   Pre-generate:
   - L3 (original) for every section — DONE IMMEDIATELY
   - L2 (empty scaffold: tables present + blanks for summaries)
   - L1 (manifest, each section status = "pending")
          │
          │  kb ingest auto-summarize (claude → copilot, auto-detect)
          │  ← step 2: AI fills summaries (--no-summarize to skip;
          │    kb summarize to re-run/retry; /kb-summarize = manual fallback)
          ▼
   For each pending section:
   - Read L3 (original)
   - Write summary into L2 (in the source's language)
   - Write one-line summary into L1 (manifest)
   - Flip status: pending → summarized
          │
          │  kb build   ← step 3: machine checks, cannot be skipped
          ▼
   ✓ No sections still "pending"
   ✓ Every L2 table matches L3 100%
   ✓ Recount tokens per layer
          │
          │  Pull Request on GitHub (this repo)   ← step 4: HUMAN review
          ▼
   SME (domain expert) reads the diff, compares to the PDF, edits if needed
          │
          │  Merge into this repo's main
          ▼
   .kb/ updated locally — NOT yet searchable anywhere.
          │
          │  kb publish   ← step 5: mirror to the hub + open a PR there
          ▼
   Hub PR merges (or direct-push on a local-path hub) → federation/ updated —
   this is the single review gate that makes content live.
          │
          │  kb query "your question..."   ← step 6: day-to-day use (reads the hub only)
          ▼
   Returns the 1–4 most relevant sections with clear citations
   (e.g. repo-id:arinc-424 §5.129 (Supplement 22))
```

In short: **machines do the mechanical work** (sectioning, verbatim tables, integrity checks), **AI does the language work** (writing summaries), **humans do final sign-off** (PR review) — no step skips the check that follows it.

---

## 5. Directory layout — what lives where

```
CENTER-KB/
├── .kb/                    ← ★ MAIN PRODUCT — what you review; this is the "knowledge base"
│   ├── index.yaml                          (L0 — master catalog)
│   ├── arinc-424/
│   │   ├── _manifest.yaml                  (L1 — detailed TOC)
│   │   ├── ch5-navigation-...md            (L2 — summary; READ THIS when reviewing)
│   │   └── ch5-navigation-...raw.md        (L3 — full original; use to cross-check)
│   └── icao-annex-3/  (same structure)
│
├── sources/                ← Copyrighted source PDFs — NOT committed to Git (see FAQ)
├── .kb-work/                ← Intermediate files from PDF parsing — ignore
├── .venv/                   ← Python install environment — ignore
│
├── .mcp.json                 ← MCP server config for Claude Code (Phase 2, see §7.8)
├── src/center_kb/              ← Tool source (devs only)
│   ├── cli.py                       `kb` CLI (19 commands, see §7)
│   ├── ingest/                      "split PDF into sections"
│   ├── build.py                     integrity checks
│   ├── query.py                     search & answer
│   ├── mcp.py                       MCP server for agent lookup (Phase 2)
│   ├── kbcontext.py, resolve.py     kb-context blocks + pin-aware resolve (Phase 2)
│   └── diff.py, doctor.py, gitio.py amendment diff + store health (Phase 2)
│
├── .claude/skills/kb-summarize/    ← "recipe" teaching AI how to summarize correctly
├── scripts/demo-federation.sh      ← demo: spins up kb-hub + 2 sample repos end-to-end (Phase 3)
├── .github/workflows/kb-publish.yml ← CI sample: publish to kb-hub on `kb-publish/*` tags created by `kb publish` (Phase 3)
├── docs/                            ← design docs & plans (tool developers)
│   └── deploy-remote-mcp.md                deploy a shared HTTP MCP server (Phase 3)
└── tests/                           ← automated tests for the tool
```

**Quick rule:** if you are an SME reviewing content, you **only need `.kb/`**. Everything else (`.venv/`, `.kb-work/`, `src/`) is internal machinery, unrelated to reading/reviewing domain content.

---

## 6. Installation (first-time setup)

Do this only if you want to **run `kb` on your machine** (e.g. try `kb query`, or `kb build` before opening a PR). If you only review PRs on GitHub, **skip this whole section**.

### Requirements
- **Python 3.11+** (this project uses Python 3.13).
- **Git** installed, with access to the repo.

### Steps

```bash
# 1. Enter the project directory
cd CENTER-KB

# 2. Create a Python virtualenv (once)
python3 -m venv .venv

# 3. Activate it (every new terminal)
source .venv/bin/activate

# 4. Install the tool + extras
#    (ingest = needed for "kb ingest"; dev = needed to run tests)
pip install -e ".[ingest,dev]"

# 5. Confirm install
kb --help
```

If step 5 prints the command list (`init`, `docker-setup`, `ingest`, `summarize`, `status`, `build`, `query`, `get`, `stats`, `publish`, `ci-publish`, `reindex`, `resolve`, `diff`, `approve`, `doctor`, `context`, `assets`, `ticket`) — install succeeded.

> **Note:** every new terminal session, run `source .venv/bin/activate` again first (you'll see `(.venv)` in the prompt).

### 6.1. Install from PyPI, web UI, and Docker

**Install the package** (once published): `pip install center-kb` — gives you the `kb` CLI and MCP server.
Create a new KB repo: `kb init` — it asks which of four kinds the repo is,
scaffolds accordingly, and records the choice as `kind:` in
`.kb/config.yaml` (re-runs reuse it); non-interactive runs pass
`--kind hub|child|ba|dev`.

| Kind | Purpose |
|---|---|
| `hub` | Central knowledge hub. Hosts `federation/` — the single source of truth for search — and runs the shared HTTP MCP server + Web UI. Receives publishes from child repos; merging hub PRs is the review gate that makes content searchable. |
| `child` | Authoring repo. Ingest PDFs → summarize → `kb build` → `kb publish` to the hub. Must point `hub:` in `.kb/config.yaml` at the main hub; does not host the company-wide MCP/Web service. |
| `ba` | Requirements repo (Phase 4, see [7.10](#710-phase-4--ba-ticket-authoring)). Drafts Dev-ready tickets — and, upstream of them for large features, epic-level mission plans (Phase 4.1) — grounded in the KB via the `ba-ticket-author` and `ba-mission-plan` skills, versions them under `tickets/` and `missions/`, and gates both with CI Definition-of-Ready checks (`kb ticket lint`, `kb mission lint`). Never ingests, summarizes, or publishes KB content. |
| `dev` | Product code repo (Phase 5 Stage A, see [7.11](#711-phase-5--dev-agent-workflow)). Implements BA tickets grounded in the KB via the `dev-implement-ticket` orchestrator and its four phase skills — design → plan → execute → handover, TDD enforced. Never ingests documents from outside the repo; from Stage B on it also publishes generated (`-code`) and curated (`-svc`) knowledge about its own source code — not yet shipped in Stage A. |

Then run `kb docker-setup` (or the `/kb-docker-setup` slash command) on a
hub or child repo: on the hub it creates `.env`, generates the HTTP token,
and starts the service (`docker compose up -d`); on a child it pulls the
ingest image for one-shot Docker ingest — a `ba` or `dev` repo needs
neither Docker nor this step. Slash commands (`/kb-ingest`, `/kb-summarize`, `/kb-publish`,
`/kb-docker-setup`) are scaffolded for **Claude Code, GitHub Copilot, and
Cursor** on hub/child repos (a `ba` repo gets `/ba-ticket-author` and
`/ba-mission-plan` instead, see [7.10](#710-phase-4--ba-ticket-authoring); a
`dev` repo gets the five dev-workflow commands instead, see
[7.11](#711-phase-5--dev-agent-workflow));
MCP client wiring ships as
`.mcp.json` (Claude Code)
and `.cursor/mcp.json` (Cursor) on every kind — stdio on the hub,
HTTP-with-env-vars on child, `ba`, and `dev` repos. Re-running `kb init` refreshes
scaffold files (skills, templates) and preserves `.kb/index.yaml` /
`.kb/config.yaml` unless `--force`.

**Web UI for humans:** the same HTTP process serves agents and people:

```bash
CENTER_KB_HTTP_TOKEN=secret python -m center_kb.mcp --hub . --transport http
# → agent:  http://<host>:8321/mcp   (Bearer token)
# → REST:   http://<host>:8321/api/… (Bearer token or cookie)
# → human:  http://<host>:8321/ui    (sign in with token; cookie stored)
```

The hub is **mandatory** — resolved from `--hub`, `CENTER_KB_HUB`, or `.kb/config.yaml`
(in that order); the server refuses to start without one. `/ui`, the MCP tools, and the
REST API all search **only** `federation/` on the hub — the server's local working
`.kb/` is never queried. Tags render as clickable chips, and a tag can be used alone
(no keywords) to browse matching documents.

**Docker:** `docker compose up -d` (image includes the full docling ingest stack);
ingest inside the container: `docker compose run --rm hub kb ingest source/x.pdf --id x`.
On `v*` release tags, CI publishes to PyPI and pushes image `ghcr.io/vuonglq01685/center-kb`.
First-time setup: `kb docker-setup` — on the hub it creates `.env`, generates
`CENTER_KB_HTTP_TOKEN` (auto-generated for convenience — replace it with your
own secret for real deployments) and runs `docker compose up -d`; on a child
it pulls the image so ingest needs no local Python.

---

## Windows

Windows is fully supported — `pip install center-kb` and every `kb` command
run natively (CI gates every release on `windows-latest`).

One OS-level note: very deep KB trees can exceed the legacy 260-character
path limit. If you hit `FileNotFoundError` on long paths, enable long paths
once: `git config --global core.longpaths true`, and set the registry key
`HKLM\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`.

`kb` also forces UTF-8 on stdin/stdout/stderr at startup on every OS, so piped I/O stays UTF-8 even under a non-UTF-8 locale (e.g. the Windows cp1252 console default).

---

## 7. `kb` command dictionary

The table below lists core commands (from Phase 1) in typical workflow order. Four Phase 2 commands — `context new`, `resolve`, `diff`, `doctor` — are in [7.8](#78-phase-2--workflow-integration). `kb publish` and the `--hub`/`--semantic` flags (Phase 3 — sharing knowledge across repos) are in [7.9](#79-phase-3--federation--remote-mcp). `kb ticket lint` and `kb mission lint` (Phase 4 — BA ticket/mission authoring, a `ba`-kind repo only) are in [7.10](#710-phase-4--ba-ticket-authoring).

| # | Command | Purpose | Who runs it |
|---|---|---|---|
| 1 | `kb ingest` | Bring one PDF in: split into sections, scaffold L1/L2/L3 | Person loading a new document |
| 2 | `kb status` | How many sections are still **unsummarized** (`pending`) | Anyone — to see remaining work |
| 3 | `kb summarize` | AI fills in the summary blanks via a headless LLM CLI (claude → copilot auto-detect); `kb ingest` runs this automatically unless `--no-summarize` | Automatic inside `kb ingest`; run directly to re-run/retry, or run `/kb-summarize` in Claude Code as manual fallback when no LLM CLI is installed (parallel sub-agents draft, the orchestrator writes) |
| 4 | `kb build` | Validate the whole store: no blanks left, tables match | Required before opening a Pull Request |
| 5 | `kb query` | Natural-language question → relevant passages **from the hub federation** (a hub is mandatory — set it in `.kb/config.yaml`); add `--semantic` to force semantic search (Phase 3, see [7.9](#79-phase-3--federation--remote-mcp)) | Day-to-day lookup |
| 6 | `kb get` | Fetch exactly one section by id (when you already know it) | When you know the section id |
| 7 | `kb stats` | Token counts per layer — cost-savings evidence | Tracking / reporting |
| 8 | `kb publish` | Mirror .kb/ (L0→L3) → a PR on the hub (commits directly on a local-path hub) | CI on every `.kb/` change (Phase 3) |
| 9 | `kb reindex` | Rebuild federation/index.yaml when it has drifted out of sync | Repair |

### 7.1 `kb ingest` — load a PDF into the system

```bash
kb ingest sources/ARINC424-22.pdf \
  --id arinc-424 \
  --tags arinc424,navdata,airspace \
  --revision "Supplement 22" \
  --sections 5
```

| Parameter | Meaning | Required? |
|---|---|---|
| `PDF` (first positional arg) | Path to the source PDF | Yes |
| `--id` | Short document id, e.g. `arinc-424` | Yes |
| `--tags` | Comma-separated classification labels for search filtering | No |
| `--revision` | Edition/revision label, e.g. `"Supplement 22"` — appears in every later citation | No, but **recommended** |
| `--sections` | Only process these chapters (e.g. `5,6`); empty = whole document | No |
| `--chapter-pattern` / `--appendix-pattern` / `--attachment-pattern` | Heading regex overrides used when splitting by heading patterns (defaults: `Chapter N` / `Appendix X` / `Attachment N`; remembered from the previous ingest) | No |
| `--no-bookmarks` | Ignore PDF bookmarks and force heading-pattern splitting | No |

By default, `kb ingest` splits the PDF by its own **PDF bookmarks/TOC** — parts are named after the document's own outline (chapters, `APPENDIX N` → `appendix-N`, `ATTACHMENT N` → `attachment-N`, front-matter, etc.). Pass `--no-bookmarks` to fall back to heading-pattern splitting instead (using `--chapter-pattern`/`--appendix-pattern`/`--attachment-pattern`, or their remembered defaults). The heading-pattern path also buckets everything before the first chapter (cover, TOC, foreword) into a `front-matter` part, and headings it cannot parse get readable slug ids from their titles (e.g. `2-legend-of-symbols`) grouped into their parent chapter's file.

The split/scaffold step itself **needs no AI** — fully automatic code. It takes seconds to tens of minutes depending on PDF length (first run is slower: downloads a page-layout model ~500MB; later runs reuse cache). Right after scaffolding, `kb ingest` also auto-runs the summarize step (see [7.3](#73-summarization-step)) via a headless LLM CLI unless `--no-summarize` is passed or `--llm none`.

Result: a new `.kb/<id>/` directory with L1/L2/L3 files; every section starts as `pending`.

Images and icons embedded in the PDF are pulled out during the same split step: each picture is saved once as a content-addressed file at `.kb/<id>/assets/<sha256>.png` (icons) or `.webp` (larger figures) — identical bytes always hash to the same filename, so re-ingesting never duplicates an asset. Descriptions are never generated; they come only from the source itself, preferring the image's own caption and falling back to OCR of any text baked into the image. L3 carries a relative `![description](assets/<sha256>.<ext>)` reference; L2 carries the same description as a `Figure: <description>` line so it's part of keyword/semantic search. In-table icon inlining and legend-based icon descriptions are planned; they activate after a per-document PoC validates docling's in-cell detection.

**Re-ingest is a full replace, not incremental:** every `kb ingest` on an existing `--id` deletes all of that doc's existing `.md` files before writing the new split. `--sections` filters *which* chapters get (re)written this run — e.g. re-ingesting with `--sections 5` leaves the doc's `.kb/<id>/` directory containing only chapter 5's files; chapters previously ingested but omitted this time are gone, not preserved.

### 7.2 `kb status` — what's left undone

```bash
$ kb status
arinc-424: 12/325 section pending
  - §5.312 Some Field Name (file: ch5-navigation-data-field-definitions.md)
  - §5.313 ...
Total: 12 section pending.
```

Use this to see **how much summarization work remains** before opening Claude Code.

### 7.3 Summarization step

This is the only step done by **AI**. By default `kb ingest` runs it automatically right after scaffolding, calling a headless LLM CLI (`claude` → `copilot`, auto-detected on `PATH`; pin one with `--llm`, or `--llm none`/`--no-summarize` to skip). Re-run or retry failed sections anytime with `kb summarize`. If no LLM CLI is installed, sections stay `pending` — open Claude Code and run `/kb-summarize` (skill at `.claude/skills/kb-summarize/SKILL.md`) as the manual fallback: it runs `kb status`, fans the pending sections out to parallel read-only sub-agents (~5 sections each, max 10 at a time), then merges their summaries itself under fixed style rules (keep every code/number, no invention).

Hard rules baked into the recipe:
- **Write in the source document's language** — never translate. A summary in a different language than its L3 source would share no vocabulary with it, and keyword search would stop matching.
- **Do not rephrase** codes, field names, numbers, units, or cross-refs (§x.y) — keep them verbatim.
- **Do not touch existing tables**.
- If unsure → keep the original wording; do not invent.

### 7.4 `kb build` — automated gate

```bash
$ kb build
kb build: OK
```

On failure, it reports clearly and **exits non-zero** (does not pass):

```bash
$ kb build
[error] arinc-424 §5.129: L2 table does not match L3 table
```

Two conditions for `kb build` to PASS:
1. **No remaining `TODO` markers or empty summaries** — every section has a summary (AI or human).
2. **Every table in the summary (L2) must match the original (L3) exactly** — the main safety latch against technical drift during summarization.

> Tip: while summarization is in progress (many `pending` sections), use `kb build --allow-pending` to validate finished parts without failing on unfinished ones.

`kb approve` marks summarized sections as `reviewed` after an SME check
(slash command: `/kb-approve`).

### 7.5 `kb query` — natural-language lookup

```bash
$ kb query "restrictive airspace" --tags arinc424 --budget 400
--- [arinc-424 §5.129 (Supplement 22)] score=17.19 ~246tk
## 5.129 Restrictive Airspace Designation

The Restrictive Airspace Designation field contains the number or name
that uniquely identifies the restrictive airspace, derived from official
government sources. ...

| Field Content      | Field Content   | Field Content   | Field Content   |
|---------------------|-----------------|-----------------|-----------------|
| Charted Designator | ICAO            | Type            | Rest. Desig.    |
| RJ(R)-116           | RJ              | R               | 116             |
...

--- [arinc-424 §5.126 (Supplement 22)] score=16.96 ~103tk
## 5.126 Restrictive Airspace Name
...
```

| Parameter | Meaning |
|---|---|
| `TEXT` (first arg) | Question / search keywords |
| `--tags` | Only search documents with these tags (pre-filter at doc level, not section) |
| `--budget` | Max tokens returned — smaller = cheaper, larger = more context |

Results always include a **clear citation** of the form `<doc-id> §<section> (<revision>)` — e.g. `arinc-424 §5.129 (Supplement 22)` — so you know exactly where the info came from and can cross-check the source.

How it works under the hood (optional to know, useful for why it's cheap): first filter by `tags` at L0 (nearly free), then rank related sections with a persistent hybrid index (SQLite FTS5 keyword search + optional semantic KNN, fused with RRF), then load L2 content of the top hits until `--budget` is hit. No AI call during lookup — pure code, fast, no model cost.

### 7.6 `kb get` — fetch one section when you know the id

```bash
kb get arinc-424 5.129 --level l2   # summary
kb get arinc-424 5.129 --level l3   # full original
```

Use when you already know the exact section (unlike `kb query`, which searches blind from a question).

### 7.7 `kb stats` — token numbers, savings evidence

```bash
$ kb stats
L0 index.yaml: 187 tokens
doc                  sections       L1         L2         L3   saving
arinc-424                 325    28486      76126      85669    11.1%
icao-annex-3                4      420       1778       2722    34.7%
```

The `saving` column is the L2-vs-L3 saving **for that document alone** — not the real per-query saving (which is much higher; see section 10), because each query loads only 1–4 sections, not the whole L2.

> A "token" is the unit of text an AI model must "read" — roughly like a word. Fewer tokens → cheaper and faster each AI call.

---

### 7.8 Phase 2 — Workflow integration

Phase 2 extends CENTER-KB beyond the CLI: Claude Code (or any MCP-capable agent) can query the knowledge base via an **MCP server**, and a document (Jira AC, spec…) can carry a **machine-readable citation** of a specific section, **pinning** the store version at write time — so you can detect when the store changed (amendment) while an old citation did not.

#### MCP server — 5 tools

Run `python -m center_kb.mcp --kb .kb` (already declared in `.mcp.json` at the repo root — Claude Code picks it up with no extra config).

| Tool | Purpose | Main params |
|---|---|---|
| `kb_search` | Find sections by natural language (tag match + hybrid FTS5/semantic search), return L2 within a token budget — returns every relevant section found, not just the best match, and flags when the top two are close in score | `query`, `tags`, `budget` |
| `kb_get_section` | Fetch exactly one section by id | `doc`, `section`, `level` (`l2`/`l3`) |
| `kb_context_new` | Pin a `kb-context` citation block at the current KB commit, from 1+ confirmed refs — lets an agent do this from chat, without the BA opening a terminal | `refs`, `tags` |
| `kb_resolve` | Accept a `kb-context` block (or a ticket containing one) — return the section at the **pinned version**, plus freshness `ok`/`stale`/`broken` | `kb_context` |
| `kb_ticket_lint` | Definition-of-Ready gate (Phase 4, see [7.10](#710-phase-4--ba-ticket-authoring)): lint a draft ticket's Markdown against required sections, story/AC/diagram structure, and `kb-context` refs resolving at their pinned version — run before handing the ticket to the BA, fix errors, and re-run until it reports PASS | `ticket_markdown` |

#### 4 new CLI commands

| Command | Purpose | Exit code |
|---|---|---|
| `kb context new --refs "<doc> §<section>,..."` | BA generates a `kb-context` block pinned at current HEAD — paste into a Jira ticket | `0` OK, `1` ref unresolvable / git error |
| `kb resolve <file\|->` | Re-read a `kb-context` block (file or stdin), return pinned-version sections + freshness | `0` all refs `ok`, `1` any `broken`, `2` no broken but some `stale` |
| `kb diff <doc-id> --against <rev>` | Diff added/removed/changed sections for one doc between the worktree and a git rev — what an amendment changed | `0` OK (even if empty), `1` error (missing doc, bad rev…) |
| `kb doctor [--context <file\|->]` | KB health check (broken TOC, missing files…); add `--context` to also check citation staleness | `0` OK, `1` KB errors, `2` no KB error but citation `stale` — CI uses this to flag "BA needs to reconfirm" |

`kb resolve` / `kb doctor --context` detect L2 content changes (what BAs read); `kb diff` reports L1 summary and L3 original changes (SME review scope). An L2-only edit shows stale on resolve but not in diff.

#### BA → Jira → Dev flow

1. BA asks an AI assistant (chat, via MCP) to draft the story; the assistant calls `kb_search`, shows the BA every returned candidate section (not just the best match), and — once the BA confirms which one(s) apply — calls `kb_context_new` with those refs. (Or, working at a terminal: `kb context new --refs "<doc> §<section>"` does the same thing directly.)
2. BA pastes the printed `kb-context` block into the Jira ticket description/AC — the block pins the current KB commit hash.
3. Dev opens the ticket; the agent (via MCP) calls `kb_resolve` with the ticket body — gets exactly what the BA saw when writing, not a newer store version if the KB has since changed.
4. If the result is `status=stale` (amendment after the ticket was written), Dev runs `kb diff <doc-id> --against <pinned-rev>` to see which sections changed, then checks with the BA whether the AC needs updating.
5. `kb doctor --context <ticket>` in CI can automatically block/flag tickets with `stale` citations before merge, without humans scanning every ticket.

> **Note:** `.mcp.json` already configures the MCP server in-repo — no extra setup for Claude Code to see the four tools. The `--hub` flag on `python -m center_kb.mcp` is now **active** — see [7.9](#79-phase-3--federation--remote-mcp) below.

---

### 7.9 Phase 3 — Federation & remote MCP

> **Hub-first architecture (2026-07-13):** `kb query`, MCP and the Web UI **read
> only the hub's `federation/`** — the local `.kb/` is a drafting desk, nobody
> queries it. `kb publish` mirrors the full L0→L3 into `federation/<repo-id>/`,
> rebuilds the aggregate `federation/index.yaml`, and (on a GitHub hub) opens a
> PR — merging that PR is the single review gate, and content only becomes
> searchable once it is merged. Details:
> `docs/superpowers/specs/2026-07-13-hub-federation-single-source-design.md`.

Phase 2 lets one knowledge store talk to developers via MCP and pin citations. Phase 3 solves the next problem: **one reference document often matters to many repos** (e.g. a shared technical standard used by a nav-data repo and a crew-ops repo alike) — you shouldn't ingest and summarize the same document in every repo. Phase 3 lets shared documents live as **a single copy** in a central store called **kb-hub**, while other repos only "reference" it.

**What is kb-hub?** Simply another Git repo with the same `.kb/` layout, plus a machine-generated `federation/` directory — a "catalog of catalogs": each participating repo mirrors its **full** `.kb/` (L0→L3, not just a slim snapshot) under `federation/<repo-id>/`, plus an aggregate `federation/index.yaml` listing every doc across every repo. kb-hub is not a long-running server — still just `.yaml`/`.md` files in Git, same docs-as-code philosophy.

**Three new things to know:**

1. **`kb publish`** — mirrors this store's full `.kb/` (L0→L3) into `federation/<repo-id>/` on the hub and rebuilds `federation/index.yaml`. The hub is read from `.kb/config.yaml` (`hub:` + `repo_id:`), not a CLI flag — `--hub`/`--repo-id` only override it. On a GitHub hub it opens/updates a Pull Request there (`--pr`); on a local-path hub it commits directly (`--direct`); with neither flag it auto-picks direct for local-path hubs. Run manually, or via CI (see `.github/workflows/kb-publish.yml`) on every `.kb/` change.
2. **`kb query`, `kb context new`, `kb resolve`, `kb doctor`** — all read **only** `federation/` on the hub (never the local `.kb/`). The hub is mandatory, resolved from `.kb/config.yaml` (or `--hub`/`CENTER_KB_HUB` to override). Example: `kb query "..."` returns every matching section across every published repo, full L2 content — no `[remote]`-truncated entries, because federation already holds the full mirror. Doc ids that collide across repos need qualifying as `repo-id:doc-id` (the tool tells you when it's ambiguous). The tool keeps a local hub clone fresh — no manual `git clone`.
3. **`--semantic`** on `kb query` — hybrid search already combines keyword and meaning when the embed extra is installed; `--semantic` now only warns clearly when embeddings are unavailable. Optional extra (`pip install -e ".[embed]"`) — without it, `kb query` still works with keyword match, no error.

**Offloading image assets to S3 (optional):** a hub can declare `asset_store: {mode: s3, bucket: ...}` in its `.kb/config.yaml`; from then on, publishes upload image assets (`<sha256>.png`/`.webp`) to that bucket instead of committing them into `federation/`, recording what was diverted in `_assets.yaml` alongside each doc. `/assets/<name>` on the hub server then serves diverted images straight from the bucket, with a local disk cache so repeat requests skip the round-trip. This needs `pip install "center-kb[s3]"` plus standard AWS credentials (env vars, shared config, or instance role) on any machine that publishes or serves — the intake server, CI, and the MCP/Web host. The default, `mode: none`, is unchanged: assets stay committed in git like every other `.kb/` file.

**`kb-context` blocks pin one hub commit.** The generated block records the hub's `version` (HEAD at write time) and repo-qualified refs (`repo-id:doc-id §section`). `kb resolve` walks the hub's git history at that pinned commit to answer `ok`/`stale`/`broken`. Older two-version blocks (`version` + `hub_version`, from the pre-2026-07-13 design) resolve as `broken` with a hint to re-pin via `kb context new` — see the [Migration](#migration-to-the-hub-first-architecture-v090) section below.

**Remote MCP lookup without cloning the repo:** previously an agent had to clone the repo first to use MCP. Phase 3 lets you run the MCP server as a shared HTTP service (not only local stdio), authenticated with a token — full deploy guide in [`docs/deploy-remote-mcp.md`](docs/deploy-remote-mcp.md).

**Want to see the full lifecycle for real (2 repos contributing to one hub, cross-repo search, stale citations after amendments)?** Run `bash scripts/demo-federation.sh` — it builds a hub and 2 sample repos in a temp directory, runs end-to-end, then cleans up without touching your real data.

**Multi-tier federation (hub → hub):** a `kind: hub` repo may itself declare
`hub:` + `repo_id:` in `.kb/config.yaml` — `kb publish` on such a repo mirrors
its **`federation/`** (not its own `.kb/`) into `federation/<hub-id>/` on the
upstream hub, keeping the nested layout (`federation/mid/repo-x/…`) (exception:
a hub pointing `hub:` at itself takes the self-publish route — its own `.kb/`
is mirrored into its own `federation/<repo-id>/` as an ordinary entry). Depth
is unbounded; entry ids become paths (`mid/repo-x:doc-id` when qualifying
refs). Publishing refuses with `federation cycle detected` when the chain
would loop content back (upstream resolves to itself, or an entry path
already contains a hub id from the chain). A hub without `hub:` is a root
hub — `kb publish` there errors with guidance. Scope search by choosing which
hub you query: a team hub returns the team's knowledge, the root hub returns
everything. Hub-to-hub publish needs direct git access to the upstream (or
`gh` for `--pr` mode) — the intake/OIDC route is child-repo-only and is not
supported anywhere in the chain; a hub with both `hub:` and `intake:` set
gets an explicit error instead of a silent wrong route. An emptied local
`federation/` will **not** propagate deletions upstream — publish refuses
rather than wipe the upstream hub's entries; delete `federation/<hub-id>/`
on the upstream manually if that is really intended.

---

### 7.10 Phase 4 — BA ticket authoring

Phase 4 adds a third `kind`, `ba` (a fourth, `dev`, follows in [7.11](#711-phase-5--dev-agent-workflow)) — a requirements repo that never ingests, summarizes, or publishes KB content, but drafts Dev-ready tickets grounded in it. The `ba-ticket-author` skill/command/prompt (Claude Code, GitHub Copilot, Cursor) runs an eight-step pipeline: **Intake** (the BA describes the business need — capability, role, value) → **Parent mission** (optional — if the BA names a parent mission, the agent reads its `missions/<mission-id>.md`, takes the story title from the US backlog row, and writes a `> Parent mission: <mission-id>` line directly under the ticket's title, saving the ticket as `tickets/<mission-id>-US<n>.md` so the back-link check below can find it) → **Ground** (`kb_search` surfaces candidate sections; the BA reviews and picks which apply) → **Draft** (fills the ticket template — story, ACs, use cases, sequence + business-flow Mermaid diagrams — citing `doc-id §section` for every claim that touches a standard) → **Pin** (`kb_context_new` embeds the returned `## KB context` block, pinned at the hub's current commit) → **Lint** (`kb ticket lint` — the Definition-of-Ready gate — runs and re-runs until it reports `DoR: PASS`) → **Maturity review** (once lint reports `DoR: PASS`, two independent reviews (parallel subagents where the runtime supports it, otherwise two sequential passes) score the draft against `docs/review-rubric.md` — Business coverage and Dev implementability — for up to 3 rounds or until both axes reach ≥ 4; a gap the agent cannot close itself becomes an owned `OPEN(<owner>)` open question; the result is recorded in `## Review record`) → **BA review** (the draft lands in `tickets/<ticket-id>.md`; the BA reads it, commits it, and pastes it into Jira themselves). The agent never pushes to Jira or opens tickets on its own — Markdown out, human-in-the-loop by design. `kb_ticket_lint` is the fifth MCP tool (see [7.8](#78-phase-2--workflow-integration) above), so an agent can run the same gate over MCP instead of a terminal.

**Mission plans (Phase 4.1)** sit *upstream* of that ticket flow, for a feature that spans several User Stories (small work still goes straight to a ticket — a mission is never mandatory). The `ba-mission-plan` skill/command/prompt runs **Intake → Ground → Draft → Split → Pin → Lint → Maturity review → Review**, saving `missions/M-<slug>.md`: a required-structure document carrying a C4 **Level 1** (System Context) *and* **Level 2** (Container) Mermaid diagram, plus a US backlog whose ids derive from the mission id. `kb mission lint` is the second Definition-of-Ready gate — required structure, both diagrams present, a well-formed backlog, and every citation resolving at the pinned hub version; a `0/N US drafted` coverage warning is expected and normal before any ticket exists. The mission↔ticket relationship is deliberately loose: the mission holds the authoritative US backlog, and a ticket that implements one row may *optionally* name its parent with a `> Parent mission: <mission-id>` line directly under its title, saved as `tickets/<mission-id>-US<n>.md` so `kb ticket lint`'s back-link check can find it — dropping the line is valid, just untraceable. Mission lint is deliberately **CLI-only, no MCP tool** (its distinguishing checks need filesystem access to the sibling `tickets/` directory that the shared MCP server does not have), so the MCP tool count is unchanged at **5** — `kb_ticket_lint` is still the only lint-related tool.

Every pull request on a `ba` repo runs `.github/workflows/kb-ticket-lint.yml` in CI — the workflow and job name stay `kb-ticket-lint` even though the gate now covers both directories, because branch protection on already-provisioned BA repos keys on that name and renaming it would leave them blocked on a check that never runs again. The trigger is deliberately not `paths`-filtered to `tickets/**.md`/`missions/**.md`: GitHub never synthesizes a passing status for a job that never started, so filtering a *required* check's trigger would leave any PR touching neither directory waiting forever. Instead the job always starts, and its one step inspects the PR's own diff and dispatches by directory, `kb ticket lint` for a changed ticket and `kb mission lint` for a changed mission — exiting 0 with a notice when nothing under either directory changed, and otherwise failing unless every changed file reports PASS (branch protection on the repo then blocks the merge).

| Command | Purpose | Exit code |
|---|---|---|
| `kb ticket lint <file\|-> [--hub <url>] [--json]` | Definition-of-Ready gate: required sections present, every `## KB context` ref resolves at its pinned hub commit, every inline `doc-id §section` citation is backed by a pinned ref (and vice versa) | `0` PASS, `1` FAIL |
| `kb mission lint <file\|-> [--hub <url>] [--json]` | Mission Definition-of-Ready gate: required structure, C4 L1 + L2 diagrams present, a well-formed backlog whose ids derive from the mission id, every citation resolving at its pinned hub commit | `0` PASS, `1` FAIL |

Scaffold a `ba` repo with `kb init --kind ba`; see `QUICKSTART-BA.md` (generated into the repo) for the full setup, including the two environment variables (`CENTER_KB_HUB_URL`, `CENTER_KB_HTTP_TOKEN`) that wire the assistant to the hub's MCP server, and the CI variable/secret (`CENTER_KB_HUB`, `KB_HUB_TOKEN`) the lint workflow needs.

---

### 7.11 Phase 5 — Dev agent workflow

Phase 5 Stage A adds a fourth `kind`, `dev` — a **product code repo**: it
consumes the shared KB while implementing BA tickets, and (from Stage B
on) publishes knowledge about its own source code back to the hub. The
boundary against `child`: a `child` repo ingests documents from
**outside** the repo and publishes them as domain knowledge; a `dev` repo
ingests **nothing**, and authors only knowledge **about its own code**.
Stage A ships the workflow that grounds that work in the KB; the
code-knowledge tooling itself (`kb code-ingest`, `kb svc note`) arrives in
Stages B and C.

One orchestrator plus four phase skills implement a ticket, each
separately invocable and resumable across sessions — state is derived
from which artifacts exist, never stored in a sidecar file:

```
/dev-implement-ticket <ticket>            → intake · resolve · ground · placeholders
                                          → dev-design    ── GATE 1: Dev approves design
                                          → dev-plan      ── GATE 2: Dev approves plan
                                          → dev-execute      (repeatable, resumable)
                                          → dev-handover  ── GATE 3: Dev opens PR
                                                             GATE 4: Dev merges
```

All five phases are scaffolded as slash commands for **Claude Code,
GitHub Copilot, and Cursor**: `/dev-implement-ticket`, `/dev-design`,
`/dev-plan`, `/dev-execute`, `/dev-handover`. A Dev normally reaches
`dev-design` through the orchestrator's own Run-the-phases step; the
table below covers the other four as direct entry points, plus the
CLI-only citation check:

| Situation | Command |
|---|---|
| New ticket, nothing started | `/dev-implement-ticket <ticket>` |
| Design approved, no plan yet | `/dev-plan <id>` |
| Plan approved, or execution already in progress | `/dev-execute <id>` |
| Code hand-implemented, needs a PR write-up | `/dev-handover <id>` |
| Lost track of where a ticket stands | `/dev-implement-ticket <id>` |
| Just want to check a citation, no implementation | `kb resolve <file>` |

Every entry point re-checks freshness first — the hub may have published
since the last session, so a ref that was `ok` yesterday can be `stale`
today; checking only at handover would be too late.

**Where work lives:** `docs/impl/<ticket-id>-design.md` (architectural-path
tickets only — a bounded ticket's design stays in chat, no file) and
`docs/impl/<ticket-id>-plan.md` (one task per AC, `- [ ]` checkboxes,
ticked one commit at a time). Those two files' existence, the
ticked-checkbox ratio, the branch, and whether a PR exists are the
complete state — any phase resumes cold in a new session.

**The four gates — all human, the agent does none of them:** GATE 1 the
Dev approves the design; GATE 2 the Dev approves the plan; GATE 3 the Dev
opens the PR; GATE 4 the Dev merges it. Enforced throughout: no production
code without a failing test observed first, and no completion claim
without shown verification output.

**Reserved doc-id suffixes.** `<repo_id>-code` (generated) and
`<repo_id>-svc` (curated) are reserved for a `dev` repo's own
code-knowledge documents — a domain document must not take either suffix.
Stage A ships only the `dev` kind and the five-skill workflow above; the
two documents themselves arrive in Stages B and C.

Scaffold a `dev` repo with `kb init --kind dev`; see `QUICKSTART-DEV.md`
(generated into the repo) for the full setup, including the two
environment variables (`CENTER_KB_HUB_URL`, `CENTER_KB_HTTP_TOKEN`) that
wire the assistant to the hub's MCP server, and allowlisting this repo in
the hub's `federation/registry.yaml` before publishing works (from Stage
B on).

---

## 8. End-to-end workflow, step by step

Real scenario: add a new document to the knowledge base, from PDF to ready-to-use.

```
Step 1 — Ingest PDF (technical owner runs)
  $ kb ingest sources/ARINC424-22.pdf --id arinc-424 \
      --tags arinc424,navdata --revision "Supplement 22" --sections 5
  → Creates .kb/arinc-424/ with 325 sections, all "pending"

Step 2 — Fill summaries (automatic — runs inside `kb ingest`)
  → kb ingest already called a headless LLM CLI for you (claude → copilot
    auto-detect); pass --no-summarize to skip, `kb summarize` to re-run/retry
  → No LLM CLI installed? Sections stay "pending" — open Claude Code and run
    `/kb-summarize` as the manual fallback (the per-wave `kb build
    --allow-pending` self-checks after each wave of ≤ 10 sub-agents)

Step 3 — Final gate check
  $ kb build
  kb build: OK
  → On FAIL, go back to step 2 and fix (usually a table that was touched)

Step 4 — Open a Pull Request on GitHub (this repo)
  → Diff shows exactly the changed .kb/*.yaml and .kb/*.md files
  → Domain SME reviews (see section 9 — review checklist)

Step 5 — Merge, then publish to the hub
  → Merge lands .kb/ on this repo's main — still not searchable anywhere
  → `kb publish` mirrors .kb/ (L0→L3) to federation/<repo-id>/ on the hub and
    opens a PR there (CI can do this automatically — kb-publish.yml)
  → Merging THAT PR on the hub is the single review gate: only then is the
    content live for kb query / MCP / Web UI
```

---

## 9. SME review role — checklist

If you were asked to review a Pull Request changing `.kb/`, this is what to do — **no coding, no commands**, just read the GitHub diff like a Word doc with track changes:

- [ ] **Read the new prose (L2, `.md` files without `.raw`)** — does it match your domain understanding of this content?
- [ ] **Cross-check the source PDF** (in `sources/` or your own copy) — did the summary omit anything important, or invent anything not in the original?
- [ ] **Check every code, field name, number, and unit** (e.g. `S/T`, `CUST/AREA`, field length, character type) — must stay **exactly as in the source**, not rephrased.
- [ ] **Tables:** you don't need to eyeball whether summary tables match originals — `kb build` **already checks and blocks the PR if they don't** before you see it. Still glance for Docling (PDF reader) row/column misreads vs the PDF — machines don't catch those.
- [ ] **One-line summaries in `_manifest.yaml`** (L1) — do they correctly say "what this section is about" so search can find them later?
- [ ] If something is wrong — **edit the `.md` or `.yaml` file directly in the GitHub UI** (like editing a normal document), comment why, or ask the PR author to fix.

After this PR merges, the change lands on this repo's `main` — that's the SME sign-off, not an AI draft. It is **not yet searchable**: run `kb publish` (or let CI's `kb-publish.yml` do it) to mirror the content onto the hub. That opens a second PR *on the hub*; merging it is what makes the content live for `kb query`/MCP/Web (see [7.9](#79-phase-3--federation--remote-mcp)).

---

## 10. Proof it works (real PoC numbers)

As of the latest trial run (see `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md` §10 for full detail):

- **Really ingested:** ARINC 424-22 chapter 5 (325 sections) + ICAO Annex 3 chapter 2 (4 sections).
- **`kb build` PASS** — no mismatched tables, no unfinished sections.
- **`kb query` returns the right section with the right citation** (e.g. `arinc-424 §5.213 (Supplement 22)`), truncated to the requested token budget.
- **Savings:** L0 (master catalog) is only 187 tokens for the whole store. A typical query returns 1–4 sections (~600–1,200 tokens) **instead of loading the whole original (~400,000 tokens)** — **≥ 99%** savings per lookup, beating the ≥ 90% target.
- **5 real bugs found and fixed** while processing real PDFs (repeated page headers mistaken for headings, "Source/Content:" labels mistaken for section titles, etc.) — each has an automated regression test.

---

## 11. Current limits & unfinished work

This is **Phase 1 + Phase 2 + Phase 3 + Phase 4 + Phase 5 Stage A**, not a finished product. Still missing:

- **No auto-generated "source-code understanding"** (e.g. reading OpenAPI, DB schemas, module lists into the KB) — different scope from today's PDF-based reference-document ingestion; reserved for later work.
- **HTTP MCP auth stops at bearer token** (one fixed secret), no OAuth/SSO yet — fine for today's internal/VPN network, not ready for the public internet.
- Summarization still needs a human to open Claude Code and trigger it — not fully background-automated.
- A small share of sections (~2.4% of ARINC chapter 5, 6/~250 items) failed PDF extraction — need manual SME cross-check when hit.
- **`status: reviewed` in the manifest is a manual, optional marker** — nothing in the CLI sets it automatically; `kb approve` (`/kb-approve`) is a manual, SME-triggered flip, not an automated one, and the `kb-review` auto-commit CI workflow stays gone. The operative review gate is still the Pull Request that `kb publish` opens on the hub: content is unreachable via `kb query`/MCP/Web until that PR merges. If a repo wants a per-section "SME re-checked" marker, run `kb approve` (or set `status: reviewed` by hand) before merging the source PR — CENTER-KB does not enforce it.

---

## 12. FAQ

**Why aren't the source PDFs in Git?**
Source reference documents are frequently copyrighted or otherwise restricted — this repo's demo docs (ARINC, ICAO) are a good example — so they must not go into a shared source repo. They live only on local machines under `sources/`, configured so Git **always ignores** that directory (no accidental commit).

**Why does Claude write summaries instead of ChatGPT/some API?**
The project uses an existing Claude Code subscription instead of paying for a separate API — cheaper for this trial phase. It doesn't affect summary quality, only operations (a person opens Claude Code instead of fully unattended runs).

**AI wrote the summary — how do we trust it isn't wrong?**
Three layers of protection: (1) AI is bound by strict style rules (no invention; keep codes/numbers verbatim); (2) tables — the easiest place to err — **never go through AI**, always machine-copied and auto-verified; (3) **a human SME always reviews before merge** — AI only drafts; it cannot publish final content alone.

**What is a "token", and why keep mentioning it?**
It's the unit of text an AI model processes (roughly like a word). It drives cost and speed of each AI call. CENTER-KB's 4-layer architecture exists mainly to **cut tokens loaded per lookup** while keeping accuracy.

**Do I need to code to review content?**
No. See section 9 — review is reading `.md`/`.yaml` files in the GitHub UI, same as reading a marked-up text document.

---

## 13. What to do when something breaks

| Situation | Likely cause | Fix |
|---|---|---|
| `kb build` errors "table mismatch" | Someone (usually AI) edited table content while summarizing | Open that section's `.raw.md` (L3), copy the table verbatim, paste over the `.md` (L2) |
| `kb build` reports remaining `pending`/`TODO` | Summarization step (step 2 in §8) not finished, failed, or skipped (`--no-summarize`) | Run `kb status` to see what's left, then `kb summarize` to retry — or, with no LLM CLI installed, back to Claude Code with `/kb-summarize` |
| `kb ingest` is very slow (10–30 min) first time | Normal — Docling downloads a layout model (~500MB) on first use | Wait, or check network if stuck. Later runs on the same PDF use cache and are much faster |
| `kb` says "command not found" | Virtualenv not activated | Run `source .venv/bin/activate` in the project directory first |
| `kb query` returns nothing | Keywords match no tags/content, or `--budget` too small | Drop `--tags`, raise `--budget`, or check spelling (the store keeps each document's own language — query in that language) |
| Unsure which files changed in a PR | — | Use GitHub "Files changed" — only `.kb/` is content to review; `src/`/`tests/` changes are tool code for developers |

---

## Migration to the hub-first architecture (v0.9.0)

1. Upgrade the CLI everywhere (`pip install -U center-kb`) — do not run two versions side by side.
2. In every repo: add `.kb/config.yaml` (`hub:` + `repo_id:`), delete
   `.github/workflows/kb-review.yml`, and replace `kb-publish.yml` with the new
   template (`kb init` does all three for you).
3. In every repo (the hub included): run `kb publish` once — the old
   federation-format entry is replaced by the full mirror, and the aggregate
   index is created.
4. On a GitHub hub: enable branch protection on `main` (*require PR* + *require
   branches up to date*).
5. Tickets carrying an old `kb-context` block (pinned to a local repo commit):
   `kb_resolve` will report `broken` with a hint — re-pin with `kb_context_new`
   the next time you touch that ticket.

---

## Release notes (v0.13.0)

Alongside the new mission-plan flow (Phase 4.1, see [7.10](#710-phase-4--ba-ticket-authoring)), this release changes four behaviors of the already-shipped `kb ticket lint` — a minor bump because everything is additive and `REQUIRED_HEADINGS` (the one thing the spec treats as breaking) is unchanged, but these four are worth knowing about:

1. **The diagram check is stricter.** `kb ticket lint`'s Mermaid check now requires the diagram-type keyword (e.g. `sequenceDiagram`, `flowchart`) at the **start of a line** inside the fence, not merely present anywhere in it. A hand-authored diagram that only mentions the keyword inside a node label (e.g. `A["flowchart of the flow"]`) now fails where it previously passed; the scaffolded `ticket-template.md` is unaffected — its keywords already sit at column 0.
2. **`--json` output gained a `notes` key.** The envelope is now `{"pass", "errors", "warnings", "notes"}`. Notes record checks that could not run (e.g. no hub configured); they never affect `pass` and existing consumers that only read `pass`/`errors`/`warnings` are unaffected.
3. **A citation-parsing bug is fixed.** The inline citation pattern used to absorb a sentence-ending period into the section id, so a ticket citing `arinc-424 §5.3.` at the end of a sentence got a spurious lint error *and* a spurious "never cited" warning even though the pinned ref matched. Those tickets now pass.
4. **A required heading inside a fenced code block no longer counts as present.** `check_headings` (shared by `kb ticket lint` and the new `kb mission lint`) used to scan every line of the document for a required heading, including lines inside a ` ``` ` fence — so a ticket or mission that pasted a reference document (e.g. `TEMPLATE.md`) into a fenced block as an example would pass the required-heading check without actually containing that section itself. Fences are now stripped before the scan, the same way citation scanning already strips them. A ticket that only passed because a required heading sat inside a fence now correctly fails with a "missing required heading" error; move the real heading out of the fence to fix it.

---

## Release

Before tagging, run the whole verification gate on your machine:

```bash
./scripts/gate.sh
```

It runs exactly what CI runs, in four tiers:

1. **T1 (unit/integration)** — `pytest` against the source tree.
2. **T2 (packaging)** — build the wheel + sdist, `uv lock --check`, `twine check`,
   install the wheel into a clean venv, check the version (`kb --version` matches
   `pyproject.toml`, and matches the tag when releasing), and make sure `tests/`,
   `.kb/` and `sources/` never sneak into the package.
3. **T3 (e2e against the installed artifact)** — runs the real user journey from
   the **installed wheel**, not the source tree, in a separate venv that has no
   `center-kb`: `kb init` → load an already-"ingested" fixture
   (`tests-gate/fixtures/pending-kb/`, standing in for the output of `ingest`) →
   `summarize` → `build` → `publish` → `query`/`get`/`context`/`resolve`/
   `diff` → `doctor`. T3 does **not** run a real `kb ingest` on a PDF — it only
   verifies `ingest`'s error path: install the bare wheel (without the `[ingest]`
   extra), then calling `kb ingest` must fail cleanly ("Docling is not
   installed"), not with a traceback. **A real PDF ingest is out of scope for the
   gate** — it needs the `[ingest]` extra (docling + torch, ~2GB) *and* a
   copyrighted PDF that must never be committed to the repo (see `sources/` in
   section 5), so it cannot run on a CI runner.
4. **T4 (regression)** — backward compatibility with older `.kb/` stores
   (v0.7.0/v0.8.0/v0.9.0), the MCP contract, golden output, and federation
   compatibility.

Once the gate is green on your machine:

```bash
# 1. Bump the version in pyproject.toml, then:
uv lock
git commit -am "chore: bump to X.Y.Z"

# 2. Tag — CI re-runs the whole gate (T1-T4 + image build/smoke), and only
#    publishes to PyPI and only retags the `:latest`/`:vX.Y.Z` image when
#    EVERYTHING is green.
git tag vX.Y.Z && git push --tags
```

A tag runs nothing different from a PR — that is deliberate
(`.github/workflows/_gate.yml` is shared by both). **If the gate is red at any
tier, nothing gets published**: PyPI is immutable, so `release.yml` only
publishes after both the gate AND the Docker image (built with the real
`[ingest]` extra) are green, and `:latest`/`:vX.Y.Z` on GHCR are only moved
after the PyPI publish succeeds. So feel free to delete the tag, fix the
problem, and tag again:

```bash
git push --delete origin vX.Y.Z
git tag -d vX.Y.Z
```

---

*This document describes Phase 1 (PoC) + Phase 2 (workflow integration) + Phase 3 (federation & remote MCP, hub-first single source since 2026-07-13) + Phase 4 (BA ticket authoring) + Phase 5 Stage A (kind `dev`, the 5-skill dev workflow) — updated 2026-08-20. Full technical design: `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md`, `docs/superpowers/specs/2026-07-10-aero-kb-phase2-design.md`, `docs/superpowers/specs/2026-07-10-aero-kb-phase3-design.md`, `docs/superpowers/specs/2026-07-13-hub-federation-single-source-design.md`, `docs/superpowers/specs/2026-07-17-ba-agent-design.md`, and `docs/superpowers/specs/2026-08-19-dev-agent-design.md`.*
