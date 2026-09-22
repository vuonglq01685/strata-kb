# Changelog

All notable changes to Strata are recorded here. This project follows
[Semantic Versioning](https://semver.org/).

## Unreleased

- `kb ticket check` verifies `[NEW: D<n>]` markers against the parent mission's `## Technology decisions`: the row must exist and be `DECIDED` (an `OPEN` row fails, naming its owner). Greenfield tickets ground code that does not exist yet through a decided design row instead of parking it under `Open decisions`. New `--missions-dir` (default: the sibling `missions/`, as `kb ticket lint`) and `--heading "## Services & order"` to check a mission plan's SA section against its own table.
- BA repos: `/sa-ticket-ground` now runs **inside** the BA pipelines — `ba-ticket-author` step 7 (Ground technical, after `DoR: PASS`) and `ba-mission-plan` step 5 (Ground services, after the backlog is confirmed) — instead of being a manual follow-up, and its handover ends with a fixed `## Needs input` block naming every decision still waiting for a human. The SA proposes an `OPEN` row in the parent mission's `## Technology decisions` for anything the code does not have yet and references it as `[NEW: D<n>]`; only a human flips `OPEN` to `DECIDED`. Ticket and mission templates, the review rubric, `QUICKSTART-BA.md` and both BA guides updated to match. Re-run `kb init --kind ba` to pick up the new skill and template text.

## 1.1.0 — 2026-09-21

- Ingest keeps code blocks (fenced, line breaks and Vietnamese diacritics read back from the PDF text layer), bullet lists, and single-spaced words in L3; text drawn inside a figure becomes the image's alt text instead of loose paragraphs. Re-ingest to pick this up.
- Hub reader renders fenced code and bullet lists, styles headings/figures/code like a markdown preview, and shows the previous/next pager above the article as well as below.

## 1.0.2 — 2026-09-21

- Left-rail section rows truncate long slug ids so titles no longer wrap into a one-word column.
- T4 Windows hub clone uses `core.autocrlf=false` / `core.eol=lf` (same as `gitio.clone`), so the legacy-KB publish mirror check is not poisoned by Git for Windows CRLF rewriting.
- Golden corpus is a synthetic handbook; copyrighted ARINC/ICAO extracts are gone.

### BA repos — the SA grounding layer

- **`/sa-ticket-ground`** (new skill on `ba` repos; Claude Code, Copilot and
  Cursor wrappers) fills the SA-owned `## Technical grounding` section of a
  ticket — or, with `--mission`, `## Services & order` of a mission plan — from
  the hub's `<repo>-code` document. Ids only: every line names a section id
  that exists in the document, or carries `[NEW: <reason>]`, or is parked
  under `Open decisions`. It has no repository access and never infers.
- `docs/tickets/TEMPLATE.md` gains `## Technical grounding` (a recommended
  section — `kb ticket lint` warns when it is missing; legacy tickets keep
  passing); `docs/missions/TEMPLATE.md` gains `## Services & order`. Neither
  has a `Flow` or `Failure modes` field: the code document cannot prove them.
- `ba-ticket-author` and `ba-mission-plan` no longer read `<repo>-code` /
  `<repo>-svc`; they write `%%TODO: verify against codebase%%` and hand off to
  the SA skill.
- **`kb ticket check <file>`** — the machine gate for `## Technical grounding`:
  every `svc.* / db.* / api.* / int.* / cmd.*` id must exist in the
  `<repo>-code` document (read from `--kb-dir` when present, otherwise from
  the hub federation), `Grounded on: <repo-id>:<doc-id> @ <revision>` must
  match the document's manifest revision, columns / routes / commands must
  match its own tables, `Files:` must appear in `struct.tree` (paths beyond
  the depth or line cap degrade to a warning), and `Open decisions` must be
  empty. Exit `0` PASS, `1` FAIL; `--json` for CI. Every error that points at
  a ticket line names it. No MCP tool yet.

Re-run `kb init --kind ba` to pick up the new templates and wrappers.

## 1.0.1 — 2026-09-19

First release of **Strata** (`strata-kb`) — Knowledge Base as Code for large
reference documents, in any domain.

### The model

- **Four layers per store.** L0 `index.yaml` (master catalogue) → L1
  `_manifest.yaml` (per-document contents with ≤ 25-word section summaries) →
  L2 `.md` (condensed prose, tables verbatim, in the source's own language) →
  L3 `.raw.md` (full extracted original). A lookup walks down only as far as it
  needs to, which is where the token saving comes from.
- **Tables never pass through a model.** They are machine-extracted at both L2
  and L3, and `kb build` diffs every L2 table against its L3 original after
  normalising whitespace and alignment only. A table altered, dropped,
  duplicated, reordered or invented fails the build in either direction.
- **Everything is files in Git.** No database, no runtime state. The review
  surface is an ordinary pull request.

### Repo kinds

`kb init --kind hub|child|ba|dev` scaffolds a repo and records the choice in
`.kb/config.yaml`. A `hub` hosts `federation/` and the shared service; a `child`
authors documents and publishes them; a `ba` drafts tickets and mission plans
grounded in the KB; a `dev` implements those tickets and publishes knowledge
about its own source code. Re-running `kb init` refreshes scaffolding and
preserves data unless `--force`.

Slash commands are scaffolded for Claude Code, GitHub Copilot and Cursor, and
MCP client wiring ships as `.mcp.json` and `.cursor/mcp.json` on every kind —
but with `${STRATA_KB_HUB_URL}` and `${STRATA_KB_HTTP_TOKEN}` placeholders
that nothing sets on their own. **`kb mcp-setup`** connects a `child`, `ba` or
`dev` repo to the hub's HTTP MCP service: it writes both values into `.env`,
makes sure git ignores it, and verifies them against `GET /api/health` (no
token) and `GET /api/docs` (token), so a wrong URL and a rejected token give
different errors. Values resolve flag → environment → the value already in
`.env` → hidden prompt, so a bare re-run verifies again without retyping.
`/kb-mcp-setup` wrappers ship for Claude Code, Copilot and Cursor; they never
take the token in chat. `kb docker-setup` run against a `ba` or `dev` repo
names the actual kind and points at `kb mcp-setup` instead.

### Authoring

- `kb ingest` splits a PDF by its own outline (or by heading pattern with
  `--no-bookmarks`), writes L3, scaffolds L1/L2, and extracts every embedded
  image once as a content-addressed asset. Descriptions come from the source —
  the image's own caption, falling back to OCR — never generated. Re-ingest is a
  full replace by default and a surgical per-chapter rewrite with `--sections`.
  The report names every sectioning decision, so nothing is silent.
- `kb summarize` fills L1/L2 blanks through a headless LLM CLI (`claude` →
  `copilot`, auto-detected), and runs automatically inside `kb ingest`.
  `/kb-summarize` is the manual fallback when no CLI is installed. Supports
  `--redo`, `--print-prompt`, and verbatim copy for sections under 200
  characters.
- `kb build` gates the store: no leftover blanks, full table integrity, and
  quality rules (`--strict` turns warnings into errors). It also fails when L3
  changed after summarization or L2 changed after approval, and never writes a
  manifest while reporting an error. `--allow-pending` validates work in
  progress.
- `kb approve` records `reviewed: {by, at, l2_sha256}` per section behind a
  clean tree and a passing strict build.
- `kb status`, `kb stats`, `kb doctor` report what is left, what it costs, and
  what is broken.

### Search

- `kb query` runs hybrid search — SQLite FTS5 keyword plus optional semantic
  KNN, fused with RRF — over the hub's `federation/`, returning L2 sections
  within a token budget with `<repo-id>:<doc-id> §<section> (<revision>)`
  citations. No model call happens during a lookup.
- `kb get` fetches one section at a chosen level; `kb tags` lists the published
  tag vocabulary.
- Sections are never cut mid-way, which is what keeps returned tables verbatim;
  `--budget` is therefore advisory and the first result always comes back whole.

### Hub and federation

- `kb publish` mirrors a store's full `.kb/` (L0→L3) into
  `federation/<repo-id>/` on the hub and rebuilds the aggregate index. It copies
  `.kb/` **artefacts only** and names anything withheld — config files and
  dotfiles never reach the hub.
- `kb ci-publish` publishes from a child's own GitHub Actions job using OIDC, no
  secrets. Uploaded paths are capped at 110 UTF-16 code units so
  `federation/<repo-id>/<path>` stays inside a Windows client's `MAX_PATH`. Its
  urllib wrapper lives in `strata_kb.httpio` with a `timeout` parameter, so the
  `file://` scheme guard is shared across its callers rather than duplicated
  per caller (the dev-machine intake flow in `publish.py` keeps its own copy
  by design).
- **Multi-tier federation:** a hub may publish its own `federation/` upward into
  another hub, unbounded in depth, with cycle detection. Scope a search by
  choosing which hub you query.
- **Optional S3 asset offloading** (`asset_store: {mode: s3, bucket: …}`) keeps
  large images out of git and serves them from the bucket with a local cache.
- `kb reindex` repairs a drifted `federation/index.yaml`;
  `federation/index.yaml` records `content_sha256` per snapshot so `kb doctor`
  detects content modified in place on the hub.
- All git operations (clone, fetch, pull, push) pass credentials through the
  credential helper — tokens never appear in `remote.origin.url` or in any log
  line. This is what sets the git ≥ 2.31 floor for a credentialed `hub:` URL.

### MCP server and Web UI

- One process serves both: stdio for a local agent, or HTTP with a bearer token
  for a shared deployment — `/mcp` for agents, `/api/…` for REST, `/ui` for
  people.
- Five MCP tools: `kb_search`, `kb_get_section`, `kb_context_new`, `kb_resolve`,
  `kb_ticket_lint`. `kb_search` caps each ranking leg at 50 results before
  fusion and says so when matches were dropped; it flags cross-repo duplicates,
  exact score ties, and hybrid-confirmed near-ties.
- A hub is mandatory — the server refuses to start without one, and never
  queries its own working `.kb/`.
- Security headers on every response (CSP `script-src 'self'`,
  `X-Frame-Options: DENY`, nosniff, `Referrer-Policy`, `Permissions-Policy`;
  HSTS on https). The `/ui` session cookie is a signed, expiring value derived
  from the token, never the token itself; `POST /ui/logout` ends a session.
  Failed `Authorization` attempts share the login form's rate-limit bucket, so
  the lockout cannot be side-stepped through the header. A corrupt published
  snapshot renders a 503 error page, not a bare 500.

### Citations that pin a version

`kb context new` writes a `kb-context` block pinned at the hub's current commit;
`kb resolve` answers `ok`/`stale`/`broken` by walking the hub's history at that
commit; `kb diff` reports what an amendment changed between two revisions —
titles, L1 summaries, the L2 slice, the L3 original, added and removed sections,
and manifest reorders. `kb doctor --context` runs the same check in CI.

### BA repos

`ba-ticket-author` and `ba-mission-plan` run grounded, human-gated pipelines that
produce Markdown only — the agent never pushes to a tracker. Two
Definition-of-Ready gates, `kb ticket lint` and `kb mission lint`, check required
structure, diagrams, backlog well-formedness, and that every citation resolves at
its pinned commit. Mission lint is CLI-only by design: its checks need
filesystem access to the sibling `tickets/` directory that a shared MCP server
does not have.

### Dev repos

- A five-command agent workflow (`/dev-implement-ticket` plus design, plan,
  execute, handover) with four human gates, resumable across sessions from
  artifacts alone — no sidecar state file. No production code without a failing
  test observed first; no completion claim without shown verification output.
- Five independent review subagents in front of those gates — A1 (design), A2
  (plan), A3 (per task), A4 (branch), A5 (merge-risk) — so the agent that
  writes an artifact never judges it. A shared `## Review dispatch contract`
  in every phase wrapper keeps author and reviewer in separate contexts; only
  A5 is machine-checked.
- `docs/pr-review-rubric.md` and its create-once
  `docs/pr-review-rubric.local.md` override, scaffolded by `kb init --kind
  dev`, hold the pre-code and merge-risk axes and the BLOCKER/SUGGESTED/
  NOTE/NITS severity ladder every review uses.
- `kb code-ingest` extracts a codebase's structure into `.kb/<repo_id>-code/`,
  deterministically and with no LLM, through seven extractors organised by
  artifact kind rather than language: services, deps, commands, tree, schema,
  integrations, api. Dependency detection covers Python, JavaScript, Java,
  .NET, Go, PHP, Rust, Swift and Dart ecosystems, and framework detection
  includes Playwright e2e suites. It refuses a destination it did not write, and
  exits 1 when no extractor other than `tree` found anything.
- **Two security properties, not conveniences:** the `integrations` extractor
  emits keys and never values (the only env file it opens is
  `.env.example`/`.sample`/`.template`, and its regex has no capture group
  around the value at all), and SQLite schema input is `--db`-only and never
  inferred, so a stray scratch database cannot become published company
  knowledge.
- `kb svc note` appends an idempotent row to `<repo_id>-svc §hist.<service>`;
  `/dev-code-seed` bootstraps the curated `-svc` document once per repo.
  `-code` and `-svc` are deliberately separate documents — overwrite versus
  accumulate, `pending` versus clean build, auto-merge versus review — joined by
  the `svc.<name>` section id so a C4 `Container(...)` can be filled from both.

### Measurement, linting, and operations

- `kb usage` ingests agent transcripts, records rows and renders a token/cost
  report.
- `kb pr lint` checks that a pull-request description carries its evidence,
  across nine required sections including `## Review`, which fails the PR on
  a missing verdict line or on `Blocking: Yes`.
- `kb assets migrate` / `verify` operate a hub's asset store.
- `kb docker-setup` prepares a hub (`.env`, token, `docker compose up -d`) or a
  child (pull the ingest image). Release tags publish to PyPI and push
  `ghcr.io/vuonglq01685/strata-kb`.

### Platform support

Python 3.11, 3.12 and 3.13 on Linux and Windows, gated on every release. `kb`
forces UTF-8 on stdin/stdout/stderr at startup on every OS. Git ≥ 2.31 is
required on any machine whose `hub:` URL carries a credential.

### Known limitations

- **HTTP authentication stops at a bearer token** — one fixed secret, no OAuth
  or SSO. Adequate for an internal network; not ready for the public internet.
- **A governed hub that `gh` cannot open a pull request on has no publish
  route.** Against a hub carrying a non-empty `federation/registry.yaml` whose
  remote `gh repo view` cannot answer for, `kb publish`, `--pr` and `--direct`
  all exit 1. `kb ci-publish` is not a fourth route: it runs only inside a
  child's own GitHub Actions job, the intake accepts only GitHub Actions OIDC
  tokens, and it lands content through `api.github.com` — GitHub at both ends.
  What is available, in order:
  - *Hub on GitHub or GitHub Enterprise, `gh` merely not set up here:* install
    and authenticate `gh` for that host (`GH_HOST=<host>` for Enterprise) until
    `gh repo view` succeeds inside the hub clone, then publish with `--pr`. This
    is the ordinary fix and the common case.
  - *Hub on github.com, publisher is a child repo's CI:* wire the child to the
    intake service and publish from its Actions job with `kb ci-publish`. This
    does not exist for an **intermediate hub** publishing upward — hub-to-hub
    publish gets the same refusals, and `kb ci-publish` tars `.kb/`, not
    `federation/`. For an intermediate hub the only route is `--pr` with a
    working `gh`, on any host.
  - *Hub not on GitHub at all (GitLab, Gitea, self-hosted):* no route in this
    release. The only lever is the hub owner removing
    `federation/registry.yaml`, which restores `--direct` for every publisher
    and gives up the governance the registry was added for.
- **The registry is a mistake guard, not a security boundary.** A child's remote
  URL is self-asserted, so the check cannot authenticate anyone, and the
  remote-less exemption is a convenience for a purely local hub. Branch
  protection on the hub, plus the OIDC intake, are the controls that actually
  hold.
- **Summarization is triggered, not scheduled.** It runs inside `kb ingest` or
  on demand; there is no unattended background pass.
- **`status: reviewed` is never set automatically.** `kb approve` is a
  deliberate human action. The operative gate is the pull request `kb publish`
  opens on the hub.
- **PDF extraction is not perfect.** A small share of sections in a complex
  document can come through malformed and need a human cross-check against the
  source.
