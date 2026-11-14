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
pip install "strata-kb[ingest]"
mkdir my-hub && cd my-hub && git init
kb init --kind hub
kb ingest source/employee-handbook.pdf --id hr-handbook --tags hr,policy
kb summarize     # needs the claude or copilot CLI on your PATH
kb build
git add -A && git commit -m "kb: hr-handbook"   # publish ships committed content
kb publish       # a hub searches only federation/, so it publishes to itself first
kb query "parental leave eligibility"
```

---

## Contents

[The problem](#the-problem) · [The method](#the-method) · [Install](#install) ·
[Repo kinds](#repo-kinds) · [The lifecycle](#the-lifecycle) ·
[Command reference](#command-reference) · [Guides](#guides) ·
[Development](#development) · [License](#license)

---

## The problem

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

## The method

### Four layers: L0 → L1 → L2 → L3

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

**The non-negotiable rule:** an AI may write the prose *around* tables. The
tables themselves are always machine-copied at both L2 and L3, and
`kb build` verifies it. Whitespace and alignment differences are normalised
(NBSP, tabs, trailing spaces, `:--` alignment rows); everything else is compared
byte for byte.

Every section has a stable id (`5.129`, `ch2`), which is also the citation key.
A section is `pending` until a model writes its summary, `summarized` after that,
and `reviewed` once a human approves it; approval is a human act and is never
automatic. A ticket or spec cites sections in a
`kb-context` block pinned to the hub's commit, so `kb resolve` can tell you
later whether what it cited still says the same thing.

### Federation: hub, child, ba, dev

One repo holds the shared, searchable copy; the others author or consume.

```
   outside documents                 product code
          |                               |
     +----v----+                     +----v----+
     |  child  |                     |   dev   |
     +----+----+                     +----+----+
          | kb publish                    | kb publish (CI: kb ci-publish)
          +--------------+  +-------------+
                         v  v
                    +---------+        read-only
                    |   hub   |<------------------ ba
                    +----+----+        (publishes its own plan)
                         |
              kb query / MCP / Web UI
```

Each repo publishes its full `.kb/` to the hub's `federation/<repo-id>/` through a
pull request. **Merging that pull request is the single gate that makes content
searchable.** Nothing is searched except what the hub holds. The system design
(data model, trust model, topologies) is in the
[architecture document](docs/src/architecture.en.md).

---

## Install

Needs **Python 3.11+** and **Git**.

```bash
pip install strata-kb            # kb CLI + MCP server
pip install "strata-kb[ingest]"  # + PDF ingestion (docling)
pip install "strata-kb[embed]"   # + semantic search
pip install "strata-kb[server]"  # + hosting the shared HTTP server and Web UI login
pip install "strata-kb[code]"    # + routes, pages, jobs, symbols in `kb code-ingest`
pip install "strata-kb[s3]"      # + S3 asset offloading
```

From source:

```bash
git clone https://github.com/vuonglq01685/strata-kb
cd strata-kb
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[ingest,dev]"
kb --help
```

- **Git 2.31 or newer** on any machine whose hub URL carries a credential (the
  `https://x-access-token:<token>@github.com/org/repo.git` shape the CI
  templates pass in `STRATA_KB_HUB`). Older git ignores the mechanism that hides
  the token and every hub command fails with git's own authentication error. An
  ssh `hub:`, a public `https://` hub and a local-directory `hub:` carry no
  credential and need no particular version.
- `.kb/config.yaml` is committed, so **never put a token in `hub:`** — pass a
  credentialed URL in `STRATA_KB_HUB`, which overrides the file.
- **Docker.** `kb docker-setup` (or `/kb-docker-setup`) prepares a hub (`.env`, a
  generated `STRATA_KB_HTTP_TOKEN`, `docker compose up -d`) or a child (pulls the
  ingest image, so ingestion needs no local Python). A `ba` or `dev` repo needs
  neither. Release tags push `ghcr.io/vuonglq01685/strata-kb`. The hub's HTTP
  auth is a bearer token plus local hub accounts — no OAuth or SSO. That is
  adequate for an internal network and not ready for the public internet.
- **Windows** is fully supported (every release is gated on `windows-latest`).
  `kb` forces UTF-8 on stdin/stdout/stderr on every OS. If a deep KB tree hits
  the 260-character path limit, run `git config --global core.longpaths true`
  and enable `LongPathsEnabled` in the registry.

---

## Repo kinds

`kb init --kind hub|child|ba|dev|tester` scaffolds a repo for its role and records
`kind:` in `.kb/config.yaml`. Re-running `kb init` refreshes the scaffold and
keeps your `.kb/config.yaml` and `.kb/index.yaml`.

| Kind | Purpose | Guide |
|---|---|---|
| **`hub`** | Central knowledge hub. Hosts `federation/` — the single source of truth for search — and runs the shared HTTP MCP server and Web UI. Merging a hub PR is the gate that makes content searchable. | [Hub](docs/src/guide-hub.en.md) |
| **`child`** | Authoring repo. Ingest documents → summarize → `kb build` → `kb publish` to the hub. Does not host the shared service. | [Child](docs/src/guide-child.en.md) |
| **`ba`** | Requirements repo. Drafts Dev-ready tickets and mission plans grounded in the KB, gated by CI Definition-of-Ready checks. Publishes only its own plan (`<repo_id>-plan`). | [BA](docs/src/guide-ba.en.md) |
| **`dev`** | Product code repo. Implements BA tickets grounded in the KB through an agent workflow. Publishes knowledge about *its own code* (`-code` generated, `-svc` curated), never outside documents. | [Dev](docs/src/guide-dev.en.md) |
| **`tester`** | System and integration tests per story. Writes test cases grounded in BA tickets and the KB, runs Playwright scripts against the shared test environment, and files a signed `PASS`/`FAIL` report per round. Publishes only `<repo_id>-test`. One `tester` repo per BA repo. Phase 1: run by hand with `/tester-env-setup` and `/tester-test-story`; the Dev/BA hand-over and `kb auto` for `tester` are not built yet. | — (guide comes later) |

Slash commands are scaffolded for Claude Code, GitHub Copilot and Cursor, and the
MCP client is wired in `.mcp.json` and `.cursor/mcp.json`; each guide lists them
and the few that differ per assistant.

`ba` and `dev` repos can run unattended (`/kb-auto`, `kb auto`). **Read the
Automation modes section of the [BA](docs/src/guide-ba.en.md) or
[Dev](docs/src/guide-dev.en.md) guide before turning it on:** an unattended run
merges its own pull requests with the rights of your `gh` login and publishes with no
human review, and it needs branch protection on `main` first (`kb auto run` refuses
until the merge policy is set up); see Automation modes, Security, Merge policy.

---

## The lifecycle

```
 source PDF ──kb ingest──► sections, L3 full text, L2/L1 scaffold   (machine, no AI)
            ──kb l3 ─────► L3 checked against the PDF               (human, if flagged)
            ──kb summarize► L2 prose + L1 one-liners                (AI fills the blanks)
            ──kb build───► gate: nothing pending, tables match, quality rules
            ── pull request ► a subject-matter expert reads the diff (human)
            ──kb publish─► pull request on the hub; merge = live
            ──kb query / MCP / Web UI──► the 1–4 most relevant sections, with citations
```

Machines do the mechanical work (sectioning, verbatim tables, integrity checks).
AI does the language work (summaries). Humans sign off. No step skips the check
that follows it. Source documents never go into Git: they live under `source/`,
which `kb init` ignores.

---

## Command reference

Every command takes `--help`. One line per command or group; the guides give the
daily use.

| Command | Purpose |
|---|---|
| `kb init` | Scaffold or refresh a repo of a given kind |
| `kb upgrade` | Refresh a ba/dev repo's scaffold on a new branch and open a PR (never merges) |
| `kb docker-setup` | Prepare Docker (hub: `.env`, token, start; child: pull image) |
| `kb mcp-setup` | Write the hub's HTTP MCP credentials into a reader repo's `.env` and verify them |
| `kb ingest` | Parse a PDF, split into sections, write L3, scaffold L1/L2 |
| `kb l3` | `report`, `confirm`, `lint` and `fix` (`on`, `off`, `pages`, `apply`): check L3 against the PDF and record review |
| `kb summarize` | Fill pending L1/L2 summaries via a headless LLM CLI |
| `kb authored` | Tag a hub doc `authored` (markdown is the master; `kb ingest` refuses it) |
| `kb status` | List sections still pending summarization |
| `kb build` | Validate the store: no blanks, table integrity, quality rules, token counts |
| `kb approve` | Mark sections reviewed |
| `kb query` | Hybrid search (keyword + semantic, RRF-fused) → L2 within a budget |
| `kb get` | Fetch exactly one section at a chosen level |
| `kb stats` | Token size per level, per document |
| `kb tags` | List every tag published on the hub |
| `kb publish` | Mirror `.kb/` to the hub's `federation/<repo-id>/` through a pull request |
| `kb ci-publish` | Publish from a repo's GitHub Actions job via OIDC, no secrets |
| `kb reindex` | Rebuild `federation/index.yaml` when it has drifted |
| `kb doctor` | Store and hub health check; `--context` also checks citation staleness |
| `kb context new` | Generate a `kb-context` citation block pinned at the hub's commit |
| `kb resolve` | Resolve a `kb-context` block: sections at the pinned version, plus freshness |
| `kb diff` | Diff sections between the worktree and a git rev |
| `kb assets` | Asset store operations on a hub: `migrate`, `verify` |
| `kb code-sync` | Hub only: `scan`, `issue`, `baseline`, `run` — hub docs that name code that changed |
| `kb user` | Hub only: accounts for the Web UI (`add`, `passwd`, `role`, `remove`, `list`, `hash`); roles `admin`, `ba`, `dev`, `tester` |
| `kb code-ingest` | Extract a codebase's structure into `.kb/<repo_id>-code/` — deterministic, no LLM |
| `kb svc note` | Record which tickets touched which service in `<repo_id>-svc` |
| `kb plan-ingest` | Build `.kb/<repo_id>-plan/` from the ready missions and tickets of a `ba` repo |
| `kb plan waves` | Dependency waves of a dev plan: which tasks can run in parallel |
| `kb ticket` | BA ticket gates and tools: `kb ticket lint` (Definition of Ready), `kb ticket check` (SA grounding), `kb ticket stale`, `kb ticket export`, `kb ticket tidy`, and `kb ticket fetch` (a published ticket by id, for a Dev) |
| `kb mission` | `lint` (Definition of Ready) and `next` (which story is done, ready, draft or blocked) for BA mission plans |
| `kb impl tidy` | Move flat `docs/impl/<id>-*` files into `docs/impl/<id>/` |
| `kb pr` | `lint`, `find`, `view`, `open`, `checks`, `merge`, `edit`: pull requests over the GitHub REST API (what the skills call instead of `gh pr`) |
| `kb claim` | Ticket claims on the hub for several Devs on one repo, and Tester claims on a story: `take`, `update`, `release`, `list` |
| `kb test-env` | Tester repo: the test environment in `.kb/test-env.yaml` — `check`, `verify`, `reset`, `seed`, `version`, `deployed`, `changed`, `lock`, `unlock` |
| `kb testcase lint` | Check a story's `tests/<story-id>/test-cases.md` against its ticket |
| `kb report lint` | Check a test report `reports/<story-id>/R<n>.md` (verdict, defects, evidence, secrets) |
| `kb report-ingest` | Build `.kb/<repo_id>-test/` from the lint-clean test cases and reports of a `tester` repo |
| `kb auto` | Full-auto mode for `ba` and `dev` repos: `on`, `off`, `status`, `run`, `wait` |
| `kb usage` | Token and cost measurement: `kb usage ingest-transcript`, `kb usage note`, `kb usage report` |

Exit codes: `0` success, `1` error (including a misconfiguration), `2` citation
stale (and a few command-specific results, listed in the guides), `3` a ticket
claim taken or lost, `4` the test environment is not deployed yet (`kb test-env deployed`).

---

## Guides

One guide per role: who it is for, first-time setup, daily work, automation
modes, troubleshooting and a short reference appendix. English first, then
Vietnamese; the PDFs are rendered from the same sources.

| Role | Markdown (EN) | Markdown (VI) | PDF (EN) | PDF (VI) |
|---|---|---|---|---|
| Hub operator | [guide-hub.en.md](docs/src/guide-hub.en.md) | [guide-hub.vi.md](docs/src/guide-hub.vi.md) | [PDF](docs/strata-guide-hub.en.pdf) | [PDF](docs/strata-guide-hub.vi.pdf) |
| Child author | [guide-child.en.md](docs/src/guide-child.en.md) | [guide-child.vi.md](docs/src/guide-child.vi.md) | [PDF](docs/strata-guide-child.en.pdf) | [PDF](docs/strata-guide-child.vi.pdf) |
| Business analyst | [guide-ba.en.md](docs/src/guide-ba.en.md) | [guide-ba.vi.md](docs/src/guide-ba.vi.md) | [PDF](docs/strata-guide-ba.en.pdf) | [PDF](docs/strata-guide-ba.vi.pdf) |
| Developer | [guide-dev.en.md](docs/src/guide-dev.en.md) | [guide-dev.vi.md](docs/src/guide-dev.vi.md) | [PDF](docs/strata-guide-dev.en.pdf) | [PDF](docs/strata-guide-dev.vi.pdf) |

- Architecture — data model, components, federation, trust model, topologies:
  [EN](docs/src/architecture.en.md) · [VI](docs/src/architecture.vi.md) ·
  [PDF EN](docs/strata-architecture.en.pdf) · [PDF VI](docs/strata-architecture.vi.pdf)
- Running the hub as a remote MCP server: [docs/deploy-remote-mcp.md](docs/deploy-remote-mcp.md)
- Release notes: [CHANGELOG.md](CHANGELOG.md)

---

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[ingest,dev]"
./scripts/gate.sh          # the CI tiers on one interpreter: lint, tests, package checks
pytest                     # tests only
```

The gate runs `ruff check .`, `ruff format --check .` and `pyright` (T0), the
tests (T1), then builds the wheel and sdist and checks them (T2), runs the real
user journey from the installed wheel (T3) and the compatibility suites (T4). CI
adds ubuntu × Python 3.11/3.12/3.13 and `windows-latest`.

To release: bump the version in `pyproject.toml`, run `uv lock`, commit, and once
CI on `main` is green for that commit push the tag `vX.Y.Z`. The release re-runs
the artifact tiers and the image build and publishes to PyPI and GHCR only when
everything is green. To rebuild the PDFs:
`uv run --extra docs python docs/src/build_pdf.py`.

---

## License

Apache-2.0. See [LICENSE](LICENSE).
