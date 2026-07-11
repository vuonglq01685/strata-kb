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
| **L2** | Condensed summary | `.md` file — English prose condensed to ~20–30% of original length, **tables kept verbatim 100%** | Medium | `.kb/arinc-424/ch5-navigation-data-field-definitions.md` |
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
   (each field/item is one section, with standard ids: §5.3, §ch2, §app3...)
          │
          ▼
   Pre-generate:
   - L3 (original) for every section — DONE IMMEDIATELY
   - L2 (empty scaffold: tables present + blanks for summaries)
   - L1 (manifest, each section status = "pending")
          │
          │  kb ingest auto-summarize (claude → copilot, auto-detect)
          │  ← step 2: AI fills summaries (--no-summarize to skip;
          │    kb summarize to re-run/retry; kb-summarize skill = manual fallback)
          ▼
   For each pending section:
   - Read L3 (original)
   - Write English summary into L2
   - Write one-line summary into L1 (manifest)
   - Flip status: pending → summarized
          │
          │  kb build   ← step 3: machine checks, cannot be skipped
          ▼
   ✓ No sections still "pending"
   ✓ Every L2 table matches L3 100%
   ✓ Recount tokens per layer
          │
          │  Pull Request on GitHub   ← step 4: HUMAN review
          ▼
   SME (domain expert) reads the diff, compares to the PDF, edits if needed
          │
          │  Merge
          ▼
   status: summarized → reviewed.  Section is now ready for AI lookup.
          │
          │  kb query "your question..."   ← step 5: day-to-day use
          ▼
   Returns the 1–4 most relevant sections with clear citations
   (e.g. arinc-424 §5.129 (Supplement 22))
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
│   ├── cli.py                       `kb` CLI (11 commands, see §7)
│   ├── ingest/                      "split PDF into sections"
│   ├── build.py                     integrity checks
│   ├── query.py                     search & answer
│   ├── mcp.py                       MCP server for agent lookup (Phase 2)
│   ├── kbcontext.py, resolve.py     kb-context blocks + pin-aware resolve (Phase 2)
│   └── diff.py, doctor.py, gitio.py amendment diff + store health (Phase 2)
│
├── .claude/skills/kb-summarize/    ← "recipe" teaching AI how to summarize correctly
├── scripts/demo-federation.sh      ← demo: spins up kb-hub + 2 sample repos end-to-end (Phase 3)
├── .github/workflows/kb-publish.yml ← CI sample: push catalog to kb-hub when `.kb/` changes (Phase 3)
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

If step 5 prints the command list (`init`, `ingest`, `status`, `build`, `query`, `get`, `stats`, `publish`, `context`, `resolve`, `diff`, `approve`, `doctor`) — install succeeded.

> **Note:** every new terminal session, run `source .venv/bin/activate` again first (you'll see `(.venv)` in the prompt).

### 6.1. Install from PyPI, web UI, and Docker

**Install the package** (once published): `pip install center-kb` — gives you the `kb` CLI and MCP server.
Create a new KB repo: `kb init` (scaffolds `.kb/`, `federation/`, `.mcp.json`, CI workflow,
`docker-compose.yml`, `QUICKSTART.md` — existing files are not overwritten).

**Web UI for humans:** the same HTTP process serves agents and people:

```bash
CENTER_KB_HTTP_TOKEN=secret python -m center_kb.mcp --hub . --transport http
# → agent:  http://<host>:8321/mcp   (Bearer token)
# → REST:   http://<host>:8321/api/… (Bearer token or cookie)
# → human:  http://<host>:8321/ui    (sign in with token; cookie stored)
```

**Docker:** `docker compose up -d` (image includes the full docling ingest stack);
ingest inside the container: `docker compose run --rm hub kb ingest source/x.pdf --id x`.
On `v*` release tags, CI publishes to PyPI and pushes image `ghcr.io/vuonglq01685/center-kb`.

---

## 7. `kb` command dictionary

The table below lists core commands (from Phase 1) in typical workflow order. Four Phase 2 commands — `context new`, `resolve`, `diff`, `doctor` — are in [7.8](#78-phase-2--workflow-integration). `kb publish` and the `--hub`/`--semantic` flags (Phase 3 — sharing knowledge across repos) are in [7.9](#79-phase-3--federation--remote-mcp).

| # | Command | Purpose | Who runs it |
|---|---|---|---|
| 1 | `kb ingest` | Bring one PDF in: split into sections, scaffold L1/L2/L3 | Person loading a new document |
| 2 | `kb status` | How many sections are still **unsummarized** (`pending`) | Anyone — to see remaining work |
| 3 | `kb summarize` | AI fills in the summary blanks via a headless LLM CLI (claude → copilot auto-detect); `kb ingest` runs this automatically unless `--no-summarize` | Automatic inside `kb ingest`; run directly to re-run/retry, or use the `kb-summarize` skill in Claude Code as manual fallback when no LLM CLI is installed |
| 4 | `kb build` | Validate the whole store: no blanks left, tables match | Required before opening a Pull Request |
| 5 | `kb query` | Natural-language question → relevant passages; add `--hub <url\|path>` to search the shared hub, `--semantic` to force semantic search (Phase 3, see [7.9](#79-phase-3--federation--remote-mcp)) | Day-to-day lookup |
| 6 | `kb get` | Fetch exactly one section by id (when you already know it) | When you know the section id |
| 7 | `kb stats` | Token counts per layer — cost-savings evidence | Tracking / reporting |
| 8 | `kb publish --hub <url\|path>` | Push this store's catalog (L0) + TOC (L1) to the shared kb-hub — does not push summary/original content | CI on every `.kb/` change (Phase 3) |
| 9 | `kb approve` | Sign-off stamp: flip section `summarized → reviewed`. CI form: `kb approve --all-changed --against <rev>` finds changed sections | Usually CI after PR merge to `main` (`kb-review` workflow); run manually for off-PR approvals |

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

By default, `kb ingest` splits the PDF by its own **PDF bookmarks/TOC** — parts are named after the document's own outline (chapters, `ATTACHMENT N` → `attN`, front-matter, etc.). Pass `--no-bookmarks` to fall back to heading-pattern splitting instead (using `--chapter-pattern`/`--appendix-pattern`/`--attachment-pattern`, or their remembered defaults).

The split/scaffold step itself **needs no AI** — fully automatic code. It takes seconds to tens of minutes depending on PDF length (first run is slower: downloads a page-layout model ~500MB; later runs reuse cache). Right after scaffolding, `kb ingest` also auto-runs the summarize step (see [7.3](#73-summarization-step)) via a headless LLM CLI unless `--no-summarize` is passed or `--llm none`.

Result: a new `.kb/<id>/` directory with L1/L2/L3 files; every section starts as `pending`.

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

This is the only step done by **AI**. By default `kb ingest` runs it automatically right after scaffolding, calling a headless LLM CLI (`claude` → `copilot`, auto-detected on `PATH`; pin one with `--llm`, or `--llm none`/`--no-summarize` to skip). Re-run or retry failed sections anytime with `kb summarize`. If no LLM CLI is installed, sections stay `pending` — open Claude Code and run the `kb-summarize` skill (at `.claude/skills/kb-summarize/SKILL.md`) as the manual fallback: it runs `kb status`, reads each section, writes summaries under fixed style rules (keep every code/number, no invention), and saves.

Hard rules baked into the recipe:
- **Write in English** (same language as the source, for best search accuracy).
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

How it works under the hood (optional to know, useful for why it's cheap): first filter by `tags` at L0 (nearly free), then rank related sections with classic text search (BM25) over L1 one-liners, then load L2 content of the top hits until `--budget` is hit. No AI call during lookup — pure code, fast, no model cost.

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

#### MCP server — 3 tools

Run `python -m center_kb.mcp --kb .kb` (already declared in `.mcp.json` at the repo root — Claude Code picks it up with no extra config).

| Tool | Purpose | Main params |
|---|---|---|
| `kb_search` | Find sections by natural language (tag match + BM25), return L2 within a token budget | `query`, `tags`, `budget` |
| `kb_get_section` | Fetch exactly one section by id | `doc`, `section`, `level` (`l2`/`l3`) |
| `kb_resolve` | Accept a `kb-context` block (or a ticket containing one) — return the section at the **pinned version**, plus freshness `ok`/`stale`/`broken` | `kb_context` |

#### 4 new CLI commands

| Command | Purpose | Exit code |
|---|---|---|
| `kb context new --refs "<doc> §<section>,..."` | BA generates a `kb-context` block pinned at current HEAD — paste into a Jira ticket | `0` OK, `1` ref unresolvable / git error |
| `kb resolve <file\|->` | Re-read a `kb-context` block (file or stdin), return pinned-version sections + freshness | `0` all refs `ok`, `1` any `broken`, `2` no broken but some `stale` |
| `kb diff <doc-id> --against <rev>` | Diff added/removed/changed sections for one doc between the worktree and a git rev — what an amendment changed | `0` OK (even if empty), `1` error (missing doc, bad rev…) |
| `kb doctor [--context <file\|->]` | KB health check (broken TOC, missing files…); add `--context` to also check citation staleness | `0` OK, `1` KB errors, `2` no KB error but citation `stale` — CI uses this to flag "BA needs to reconfirm" |

`kb resolve` / `kb doctor --context` detect L2 content changes (what BAs read); `kb diff` reports L1 summary and L3 original changes (SME review scope). An L2-only edit shows stale on resolve but not in diff.

#### BA → Jira → Dev flow

1. BA runs `kb context new --refs "<doc> §<section>"` after reading the relevant spec passage.
2. BA pastes the printed `kb-context` block into the Jira ticket description/AC — the block pins the current KB commit hash.
3. Dev opens the ticket; the agent (via MCP) calls `kb_resolve` with the ticket body — gets exactly what the BA saw when writing, not a newer store version if the KB has since changed.
4. If the result is `status=stale` (amendment after the ticket was written), Dev runs `kb diff <doc-id> --against <pinned-rev>` to see which sections changed, then checks with the BA whether the AC needs updating.
5. `kb doctor --context <ticket>` in CI can automatically block/flag tickets with `stale` citations before merge, without humans scanning every ticket.

> **Note:** `.mcp.json` already configures the MCP server in-repo — no extra setup for Claude Code to see the three tools. The `--hub` flag on `python -m center_kb.mcp` is now **active** — see [7.9](#79-phase-3--federation--remote-mcp) below.

---

### 7.9 Phase 3 — Federation & remote MCP

Phase 2 lets one knowledge store talk to developers via MCP and pin citations. Phase 3 solves the next problem: **one reference document often matters to many repos** (e.g. a shared technical standard used by a nav-data repo and a crew-ops repo alike) — you shouldn't ingest and summarize the same document in every repo. Phase 3 lets shared documents live as **a single copy** in a central store called **kb-hub**, while other repos only "reference" it.

**What is kb-hub?** Simply another Git repo with the same `.kb/` layout, plus a machine-generated `federation/` directory — a "catalog of catalogs": each participating repo contributes a slim snapshot (L0 + L1 only, no summary/original content) so other repos know what that repo holds without visiting it. kb-hub is not a long-running server — still just `.yaml`/`.md` files in Git, same docs-as-code philosophy.

**Three new things to know:**

1. **`kb publish --hub <url|path>`** — push this store's catalog (L0) and TOC (L1) to kb-hub so other repos "know" what you hold. Does not push summaries (L2) or originals (L3) — those stay in the source repo. Run manually, or via CI (see `.github/workflows/kb-publish.yml`) on every `.kb/` change.
2. **`--hub <url|path>`** on `kb query`, `kb context new`, `kb resolve`, `kb doctor` — expand search/checks to the kb-hub, not only the local store. Example: `kb query "..." --hub https://.../kb-hub.git` returns domain docs living on the hub (full content like local docs) plus one-line summaries of docs in other repos (marked `[remote]`; deep reads require that repo). The tool keeps a local hub clone fresh — no manual `git clone`.
3. **`--semantic`** on `kb query` — force lookup by **question meaning** instead of keyword match alone (BM25). Useful when the question uses different words than the source but the same idea. Optional extra (`pip install -e ".[embed]"`) — without it, `kb query` still works with keyword match as before, no error.

**`kb-context` blocks can now pin 2 versions.** If a BA cites a section that lives on kb-hub, the generated block includes `hub_version` next to `version` — pinning both local and central stores at write time. Older Phase 2 blocks (only `version`) still resolve as before; no migration needed.

**Remote MCP lookup without cloning the repo:** previously an agent had to clone the repo first to use MCP. Phase 3 lets you run the MCP server as a shared HTTP service (not only local stdio), authenticated with a token — full deploy guide in [`docs/deploy-remote-mcp.md`](docs/deploy-remote-mcp.md).

**Want to see the full lifecycle for real (2 repos contributing to one hub, cross-repo search, stale citations after amendments)?** Run `bash scripts/demo-federation.sh` — it builds a hub and 2 sample repos in a temp directory, runs end-to-end, then cleans up without touching your real data.

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
    the kb-summarize skill as the manual fallback (self-checks every 5–10
    sections with `kb build --allow-pending`)

Step 3 — Final gate check
  $ kb build
  kb build: OK
  → On FAIL, go back to step 2 and fix (usually a table that was touched)

Step 4 — Open a Pull Request on GitHub
  → Diff shows exactly the changed .kb/*.yaml and .kb/*.md files
  → Domain SME reviews (see section 9 — review checklist)

Step 5 — Merge
  → CI (kb-review workflow) runs `kb approve --all-changed` and commits:
    changed sections flip summarized → reviewed
  → Knowledge base now has new content, ready for kb query
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

After the PR merges, CI (`kb-review` workflow) **automatically** flips the changed sections to `status: reviewed` in the manifest — marking content as SME-signed-off, not an AI draft. You don't hand-edit any YAML for that.

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

This is **Phase 1 + Phase 2 + Phase 3**, not a finished product. Still missing:

- **No auto-generated "source-code understanding"** (e.g. reading OpenAPI, DB schemas, module lists into the KB) — different scope from today's PDF-based reference-document ingestion; reserved for later work.
- **HTTP MCP auth stops at bearer token** (one fixed secret), no OAuth/SSO yet — fine for today's internal/VPN network, not ready for the public internet.
- Summarization still needs a human to open Claude Code and trigger it — not fully background-automated.
- A small share of sections (~2.4% of ARINC chapter 5, 6/~250 items) failed PDF extraction — need manual SME cross-check when hit.
- **`reviewed` means "merged into `main`"**, not "a second person re-checked" — valid when the KB builder is the SME (current context). If later builder ≠ reviewer, re-enable the gate (CODEOWNERS + branch protection requiring review) before trusting `reviewed`. See `docs/superpowers/specs/2026-07-11-review-automation-design.md` §2.
- **`reviewed` status on the hub lags one beat:** the `kb-review` workflow's auto-commit does not trigger `kb-publish` (anti-loop), so the hub snapshot only updates `status` on the next content push. Lookup is unaffected (federation reads L1 summaries, not `status`).

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
| `kb build` reports remaining `pending`/`TODO` | Summarization step (step 2 in §8) not finished, failed, or skipped (`--no-summarize`) | Run `kb status` to see what's left, then `kb summarize` to retry — or, with no LLM CLI installed, back to Claude Code with the `kb-summarize` skill |
| `kb ingest` is very slow (10–30 min) first time | Normal — Docling downloads a layout model (~500MB) on first use | Wait, or check network if stuck. Later runs on the same PDF use cache and are much faster |
| `kb` says "command not found" | Virtualenv not activated | Run `source .venv/bin/activate` in the project directory first |
| `kb query` returns nothing | Keywords match no tags/content, or `--budget` too small | Drop `--tags`, raise `--budget`, or check spelling (store content is English) |
| Unsure which files changed in a PR | — | Use GitHub "Files changed" — only `.kb/` is content to review; `src/`/`tests/` changes are tool code for developers |

---

*This document describes Phase 1 (PoC) + Phase 2 (workflow integration) + Phase 3 (federation & remote MCP) — updated 2026-07-11. Full technical design: `docs/superpowers/specs/2026-07-10-aero-kb-phase1-design.md`, `docs/superpowers/specs/2026-07-10-aero-kb-phase2-design.md`, and `docs/superpowers/specs/2026-07-10-aero-kb-phase3-design.md`.*
