# Phase 5 — Dev Agent + Codebase-as-Knowledge (kind `dev`, `dev-implement-ticket`, `dev-code-seed`, `kb code-ingest`, `kb svc note`) — Design

**Date:** 2026-08-19
**Status:** Proposed design — not yet implemented (plan: `docs/superpowers/plans/2026-08-19-dev-agent.md`)
**Builds on:** `docs/superpowers/specs/2026-07-17-ba-agent-design.md` (Phase 4, shipped), `docs/superpowers/specs/2026-07-28-ba-mission-plan-design.md` (Phase 4.1, shipped), Architecture Spec v0.4 §14–15 (Phase 5 sketch)

**Scope:** Four stages, one design, because the contracts co-evolve.

- **Stage A — Consume.** A fourth repo kind (`kb init --kind dev`) and the `dev-implement-ticket` skill: a Dev takes a BA ticket, resolves its `kb-context` at the pinned version, checks freshness, grounds the work in domain + code knowledge, resolves the `%%TODO: verify against codebase%%` placeholders Phase 4 deliberately leaves in diagrams, and implements AC-by-AC with traceable citations.
- **Stage B — Produce (structure).** A deterministic, LLM-free `kb code-ingest` that extracts **cross-stack** code structure — services/containers, DB schema, dependencies with framework detection, external integrations, API surface — into `.kb/<repo_id>-code/` in the existing 4-layer format, published to the hub on every merge by a scaffolded `kb-code.yml`.
- **Stage C — Produce (responsibility).** A second, **curated** document `.kb/<repo_id>-svc/` holding what each service is *responsible for* and which business flows cross it. Bootstrapped once per repo by the `dev-code-seed` skill (LLM drafts L2 from deterministic code evidence in L3, a human corrects, `kb approve` gates it), then accumulated per ticket by `kb svc note`.
- **Stage D — Close the loop.** The eight BA wrappers learn to read both documents, so `ba-ticket-author` and `ba-mission-plan` stop emitting `%%TODO%%` for names and responsibilities the hub can now answer.

This closes the SDLC loop of Architecture v0.4 §15 at the level that matters: domain knowledge says *what the rule is*, code knowledge says *which service and table it lives in*, service knowledge says *what that service is responsible for* — and each merged ticket adds to the last two.

---

## 1. Problem

Phase 4/4.1 close the *authoring* half of the loop: a BA produces missions and tickets that are cited, pinned, and machine-gated. Five gaps remain.

- **No packaged flow for the Dev.** Nothing prompts a Dev to `kb_resolve` the pinned context, so the two-version drift protection the BA paid for goes unused; a Dev may implement from the current hub state, or from memory, instead of from the exact sections the BA cited.
- **The placeholders have no resolver.** `%%TODO: verify against codebase%%` was designed for "the Phase 5 agent", which does not exist.
- **The BA Agent is code-blind.** `kb_search` sees only domain documents, so any diagram needing a real service name, table, or integration point degrades to a placeholder.
- **The BA Agent is also responsibility-blind, which is the deeper gap.** A C4 container is `Container(alias, label, technology, description)` — four arguments. Names and technology can be extracted from code deterministically; **`description` — what the container is responsible for — cannot.** Without it a mission's C4 L2 is a box diagram with no meaning, `Rel(...)` labels stay empty, and a ticket's `sequenceDiagram` has participants but no messages. `kb mission lint` still passes (it only checks the `C4Container` keyword and required headings), so the gap surfaces one step later as a low **"Dev implementability"** score in the maturity review, then degrades into `OPEN(...)` rows — i.e. back into the verbal channel Phase 5 exists to remove.
- **Nothing brings knowledge back.** A Dev who discovers a KB gap mid-implementation has no defined feedback duty — the "curated KB dies quietly" risk of Architecture v0.4 §16.

**And the adoption case is the hardest one.** A framework is mostly adopted by projects already in flight. On day one such a repo has no center-kb ticket history at all, so any mechanism that accumulates knowledge *per ticket* yields exactly nothing, and never covers the responsibilities that already exist — which is 100% of the running system. Bootstrapping is therefore a first-class requirement, not a follow-on: Stage C needs both a **one-time seed** (covers the past) and a **per-ticket accumulator** (covers the future).

## 2. Goals

- A Dev runs `/dev-implement-ticket`, and gets: resolved pinned sections + freshness verdict, an implementation plan mapped AC-by-AC, placeholder resolutions verified against real code, and a TDD implementation whose standard-derived values are verbatim from the cited sections.
- Broken citations are a blocker surfaced to the BA (re-pin); stale citations are surfaced with both versions. Neither is ever silently worked around.
- `kb code-ingest` works on **any** stack a project line uses — frontend and backend — by keying on cross-stack artifacts rather than one language's syntax. Adding a framework is a row in a lookup table.
- `kb code-ingest` output is deterministic (same tree + commit → byte-identical), passes `kb build` with no `--allow-pending`, and publishes through the existing `kb ci-publish` with zero new hub-side machinery.
- A team adopting center-kb into a **running** project runs `/dev-code-seed` once and ends with a reviewed `-svc` document covering every service the extractors found — a finite, checklist-shaped task, not an open-ended "document the system".
- After the seed, knowledge accrues without new discipline: `kb svc note` records ticket↔service history automatically at handover.
- The BA Agent can fill all four `Container(...)` arguments and label `Rel(...)` from the hub, and only writes `%%TODO%%` when neither document answers.
- Human-in-the-loop preserved: the agent never edits the BA's ticket, never merges, never marks DoD items a human hasn't confirmed, and never modifies a `reviewed` section.

**Non-goals:** any change to the five MCP tools (§3.1); Jira REST integration; a full SQL or per-language parser (§7 states the deliberate limits); cross-repo call-graph analysis; automated write-back into the BA repo (§13); an LLM pass over the *deterministic* document (§3.5 forbids it).

## 3. Architecture constraints

1. **Five MCP tools, unchanged** (`kb_search`, `kb_get_section`, `kb_context_new`, `kb_resolve`, `kb_ticket_lint`). Phase 5 adds **zero** MCP tools; `tests-gate/golden/mcp_tools.json` stays byte-identical. Every new capability is a CLI command — the Dev always has a shell in-repo. Mirrors the `kb_mission_lint` rejection (Phase 4.1 §9).
2. **Hub is the only read source.** Refs resolve against the hub federation exactly like `kb doctor --context`; code knowledge becomes readable to agents only after its hub PR merges.
3. **No pydantic model changes.** Appendix B sketched extra manifest keys (`generated`, `source_commit`, per-section `kind`). Implementing them would change `save_yaml_model` output for *every* existing manifest (pydantic dumps defaults), breaking golden fixtures and re-hashing every published doc. The intent maps onto existing fields instead (§6.4) — a deliberate deviation from Appendix B. `SectionEntry.status` already has `pending`/`summarized`/`reviewed`, which is the whole lifecycle Stage C needs.
4. **4-layer format untouched.** Both documents are ordinary sections: `## <sid> <title>` headings (`mdutils._HEADING_RE` requires a whitespace-free sid), `.md` (L2) + `.raw.md` (L3) pairs, `_manifest.yaml`, an `index.yaml` entry. `kb build`, `searchdb`, federation, and the web UI need no code changes.
5. **The generated document is deterministic and LLM-free.** Extractors are pure functions of the working tree; ordering is sorted; re-running on the same commit produces byte-identical files. This is what makes "never stale" true for `-code` and makes a hub auto-merge policy safe. An LLM pass over `-code` is forbidden, not deferred.
6. **The curated document is LLM-drafted and human-gated.** `-svc` L2 is drafted by the existing `kb summarize` runner from deterministic L3 evidence and must reach `reviewed` via `kb approve` before it can publish. This is the same pattern Phase 1–3 already chose for PDFs — L3 is the raw source, L2 is the summary — applied to a different input. It is the *only* place in Phase 5 where an LLM touches content.
7. **`kb build` invariants hold by construction:** every generated section has a non-empty `summary` and no `TODO:summarize` marker, so `-code` builds clean without `--allow-pending`; L3 never contains a Markdown pipe table that is not verbatim in L2, so all L3 detail uses fenced code blocks.
8. **Two documents, never one.** `-code` and `-svc` cannot share a document, for three independent reasons: (a) `-code` is overwritten every merge and would silently delete human content; (b) `-svc` carries `pending` sections during a seed, which would fail `kb build` for the whole document; (c) `-code` is machine fact and may auto-merge, `-svc` is a claim and must be reviewed. They are joined by **section id**, not by file.
9. **Code is ground truth.** Both documents are summaries for orientation and diagram-grounding. When either disagrees with the code, the code wins; `-code` self-heals on the next merge, `-svc` raises a stale-risk warning (§8.3) for a human to resolve.
10. **The curated document never sources a standard value.** Responsibility text is for locating and cross-checking work. Every code, format, enum, or threshold encoded in code or tests comes verbatim from a domain KB section at the pinned version. Without this rule, a Dev Agent could implement from another Dev's note instead of from the standard, breaking the citation chain that is center-kb's entire value.
11. **Generated knowledge is never a secret channel.** The `integrations` extractor reads only `.env.example`/`.env.sample`/`.env.template` and emits **keys only, never values**; it never reads a real `.env`. SQLite input stays explicit `--db` only. Same spirit as Phase 4's citation-verbatim rules: automation must not widen the blast radius.
12. **Cross-stack by construction.** Extractors key on artifact *kind* (dependency manifest, container manifest, migration, API contract), not on programming language. center-kb is a framework applied across project lines; a single-stack extractor set turns §8's zero-detection `exit 1` into a hard failure on most adopting repos.

## 4. Component A — kind `dev`

Fourth repo kind alongside `hub`, `child`, `ba`. A `dev` repo is a *product code repo*: it consumes the KB while implementing tickets, and it produces knowledge **about its own source code** — generated (`-code`) and curated (`-svc`).

**Boundary against kind `child`, stated explicitly because Stage C crosses Phase 4's original line.** The Phase 4 sketch described `dev` as "never ingests, never summarizes, never authors". Stage C makes that false, so the boundary moves to a defensible place:

> A `child` repo ingests documents from **outside** the repo (PDF standards, references) and publishes them as domain knowledge. A `dev` repo ingests **nothing**, and authors only knowledge **about its own code**.

`dev` therefore carries `kb summarize` / `kb approve` / `kb publish` wrappers (Stage C needs them) but **never** `kb ingest`, `source/.gitignore`, `kb-docker-setup`, or `kb-publish.yml`.

`kb init --kind dev` scaffolds exactly (`DEV_TEMPLATES`, a separate map like `BA_TEMPLATES` — **not** merged with `COMMON_TEMPLATES`):

| Path | Source template | Stage |
|---|---|---|
| `.kb/config.yaml` | `config-dev.yaml` *(new)* | A |
| `.kb/index.yaml` | `index.yaml` *(reuse)* | A |
| `.mcp.json` | `mcp-child.json` *(reuse)* | A |
| `.cursor/mcp.json` | `cursor-mcp-child.json` *(reuse)* | A |
| `.claude/skills/dev-implement-ticket/SKILL.md` | `claude-skill-dev-implement-ticket.md` *(new)* | A |
| `.claude/commands/dev-implement-ticket.md` | `claude-command-dev-implement-ticket.md` *(new)* | A |
| `.github/prompts/dev-implement-ticket.prompt.md` | `copilot-dev-implement-ticket.prompt.md` *(new)* | A |
| `.cursor/commands/dev-implement-ticket.md` | `cursor-dev-implement-ticket.md` *(new)* | A |
| `QUICKSTART-DEV.md` | `QUICKSTART-dev.md` *(new)* | A |
| `.github/workflows/kb-code.yml` | `kb-code.yml` *(new)* | B |
| `.claude/skills/dev-code-seed/SKILL.md` | `claude-skill-dev-code-seed.md` *(new)* | C |
| `.claude/commands/dev-code-seed.md` | `claude-command-dev-code-seed.md` *(new)* | C |
| `.github/prompts/dev-code-seed.prompt.md` | `copilot-dev-code-seed.prompt.md` *(new)* | C |
| `.cursor/commands/dev-code-seed.md` | `cursor-dev-code-seed.md` *(new)* | C |
| `.claude/skills/kb-summarize/SKILL.md` | `claude-skill-kb-summarize.md` *(reuse)* | C |
| `.claude/commands/kb-summarize.md` | `claude-command-kb-summarize.md` *(reuse)* | C |
| `.github/instructions/kb-summarize.instructions.md` | `copilot-kb-summarize.instructions.md` *(reuse)* | C |
| `.cursor/commands/kb-summarize.md` | `cursor-kb-summarize.md` *(reuse)* | C |
| `.cursor/rules/kb-summarize.mdc` | `cursor-kb-summarize.mdc` *(reuse)* | C |
| `.claude/skills/kb-approve/SKILL.md` | `claude-skill-kb-approve.md` *(reuse)* | C |
| `.claude/commands/kb-approve.md` | `claude-command-kb-approve.md` *(reuse)* | C |
| `.github/prompts/kb-approve.prompt.md` | `copilot-kb-approve.prompt.md` *(reuse)* | C |
| `.cursor/commands/kb-approve.md` | `cursor-kb-approve.md` *(reuse)* | C |
| `.claude/skills/kb-publish/SKILL.md` | `claude-skill-kb-publish.md` *(reuse)* | C |
| `.github/prompts/kb-publish.prompt.md` | `copilot-kb-publish.prompt.md` *(reuse)* | C |
| `.cursor/commands/kb-publish.md` | `cursor-kb-publish.md` *(reuse)* | C |

Explicitly **NOT** scaffolded on `dev`: `kb-ingest` wrappers, `kb-docker-setup` wrappers, `kb-init` wrappers, `.github/workflows/kb-publish.yml` (that is the child's tag flow; `dev` uses `kb-code.yml`), `source/.gitignore`, and every BA artifact. Symmetrically, hub/child/ba scaffolds gain nothing from Phase 5.

**Implementation notes** (mirror of Phase 4 §8): `initcmd` gains `KIND_DEV` + `DEV_TEMPLATES`; `KINDS` and `template_map()` go 3-way → 4-way; `cli.RepoKind` gains `dev`; `KIND_DESCRIPTIONS` gains a fourth paragraph and its "one of three kinds" line (`cli.py:67`) becomes "one of four kinds"; `_resolve_kind`'s interactive loop accepts `dev`; `config.KBConfig.kind` Literal (`config.py:36`) gains `"dev"` — without it `load_config` rejects the scaffolded config. `doctor.check_kind` needs no change. The non-interactive error string (`cli.py:126`) intentionally still reads `--kind hub|child`, frozen by an existing test — standing Phase 4 decision.

**Config note.** `config-dev.yaml` carries `hub:` (required — the only read source), `repo_id:`, and `intake:` (Stage B publishes through the OIDC intake exactly like a child repo). The dev repo must be allowlisted in the hub's `federation/registry.yaml`; `cipublish.run()` never inspects `kind`, and `intake.authorize()` gates on that registry alone, so no hub-side code changes. QUICKSTART-DEV documents the operational step.

## 5. Component B — skill `dev-implement-ticket` + 4 wrappers

Four thin wrappers (Claude skill + Claude command + Copilot prompt + Cursor command), registered in `DEV_TEMPLATES` on kind `dev` only. The Claude skill is the orchestrator; Copilot/Cursor variants fall back to CLI throughout, and to sequential self-review where the flow says "subagent".

**Workflow — seven steps:**

1. **Intake** — receive the ticket: a pasted Markdown body, or a path the Dev supplies (tickets live in the BA repo or Jira, not here). Confirm the ticket / US id and the target branch. No `kb-context` block → stop: the ticket is not Ready (DoR requires it); send it back rather than improvising context.
2. **Resolve** — call `kb_resolve` on the ticket text when available; otherwise `kb resolve - < ticket.md`. Triage: **broken** → BLOCKER, report to the BA for a re-pin, never implement around a citation that no longer resolves. **stale** → show both versions and let humans decide (see below). **ok** → proceed.
3. **Ground** — read the resolved L2; escalate to L3 (`kb_get_section … l3`) for any value that will be encoded in code or tests. Then locate the work: `kb_search` **both** own-repo documents — `<repo_id>-code` for structure (which service, which table) and `<repo_id>-svc` for responsibility (what that service is *for*) — then read the actual code. Knowledge orients; code decides.
4. **Resolve placeholders** — for every remaining `%%TODO: verify against codebase%%`: verify the real name against the codebase and record `placeholder → verified value (file:line or code-knowledge ref)`. Report the list to the BA; **never edit the ticket**. A placeholder that cannot be verified here is a finding: `OPEN(BA)`.
5. **Plan** — map **every AC** to code changes + a test; include placeholder resolutions, touched modules, and any AC not implementable as written marked `OPEN(BA)` — reinterpreting an AC is forbidden. Get the Dev's confirmation before writing code.
6. **Implement** — TDD per AC: failing test first, then code. Standard-derived values verbatim from the resolved sections, each carrying a `doc-id §section` citation comment. Run the project's own tests and linters.
7. **Handover (DoD)** — assemble the PR: ticket id, the `kb-context` refs (so the reviewer can `kb resolve` them), the AC→test map, the placeholder-resolution list, and any `OPEN(...)` findings. Re-run step 2's freshness check — a hub publish mid-implementation must be surfaced, not discovered in review. Then:
   - run `kb svc note <service> --ticket <id> --title "<title>" --refs "<refs>"` for **each** service touched (§9) — the entry lands in this same PR;
   - if the ticket **changed what a service is responsible for**, report `amend needed: <repo_id>-svc §svc.<name>` as a PR finding. Do **not** edit a `reviewed` section;
   - list every KB gap, ambiguity, or contradiction found as a concrete feedback item (issue or PR on the owning child repo / hub).

   The Dev — not the agent — merges.

**On the stale-ref diff.** `kb diff` is the wrong tool here and must not appear in these wrappers: `diff_doc(kb_dir, doc_id, against=...)` compares the **local** `.kb/` worktree against a **local** git rev, and it takes a doc-id, not a `doc-id §section` ref. A `dev` repo holds no local copy of the cited domain document — it lives on the hub. The working pair is: `kb resolve` (returns the **pinned** content plus the `stale` verdict and reason) and `kb get <doc-id> <section> [--level l3]` (reads **current** hub state via `_hub_or_exit`). The agent presents both and the humans decide.

**Hard rules block (verbatim in all four wrappers):**

- A ticket without a resolvable `kb-context` is not implementable — send it back, never improvise the missing context.
- Broken citation = blocker; stale citation = both versions surfaced, humans decide; neither is ever silently ignored.
- Never invent or "remember" a standard value — every code/format/enum/threshold encoded in code or tests is read verbatim from the resolved section at the pinned version, with a citation comment.
- **`<repo>-svc` is for locating and cross-checking work only. It is never a source for an AC or a standard value** (§3.10).
- The ticket is the BA's artifact: report placeholder resolutions and AC findings back; never edit the ticket.
- Code is ground truth: when either code-knowledge document disagrees with the code, trust the code and note the mismatch.
- Never modify a `reviewed` section of `-svc`; propose an amend instead.
- `hist.*` entries are appended only by `kb svc note`, never hand-edited.
- An AC that cannot be implemented as written becomes `OPEN(BA)` — never reinterpreted.
- Never push to a protected branch, never merge, never tick DoD/AC checkboxes for humans.
- KB feedback items found during implementation go in the PR description — dropping them silently violates DoD.

## 6. Component C — the two code-knowledge documents

### 6.1 Identity and layout

| | Generated | Curated |
|---|---|---|
| Doc id | `<repo_id>-code` | `<repo_id>-svc` |
| Location | `.kb/<repo_id>-code/` | `.kb/<repo_id>-svc/` |
| Index tags | `[code, generated]` + `--tags` | `[code, curated]` + `--tags` |
| Written by | `kb code-ingest` (overwrite) | `kb code-ingest --scaffold-svc` (upsert scaffold), `kb summarize` (L2 draft), a human (L2 correction), `kb svc note` (append `hist.*`) |
| `status` | `summarized` | `pending` → `summarized` → `reviewed` |
| Published by | CI, every merge | a human, via PR |

`<repo_id>` comes from `.kb/config.yaml` (folder-name fallback). Both `-code` and `-svc` are **reserved doc-id suffixes**, documented in README; a domain document must not take them. Collision is a documented misconfiguration, not lint-enforced — there is nothing to lint a domain document's name against.

### 6.2 Section-id prefix contract

Each prefix has exactly one owner. The BA Agent, the Dev Agent, and future tooling key on these, so they are stable contract.

| Prefix | Document | Owner | Content |
|---|---|---|---|
| `struct.tree` | `-code` | extractor | package/folder layout + entry points |
| `svc.<name>` | `-code` | extractor | image, ports, `depends_on`, detected technology |
| `db.<table>` | `-code` | extractor | columns, types, PK/FK, DDL |
| `dep.<ecosystem>` | `-code` | extractor | direct dependencies + framework detection |
| `int.<name>` | `-code` | extractor | external integrations (keys only, §3.11) |
| `api.<tag>` | `-code` | extractor | endpoints from an in-repo OpenAPI contract |
| `svc.<name>` | `-svc` | **human** (LLM-drafted) | **what this service is responsible for** |
| `flow.<name>` | `-svc` | **human** | a business flow and the services it crosses |
| `hist.<name>` | `-svc` | `kb svc note` | append-only log of tickets that touched this service |

**`svc.<name>` deliberately collides across the two documents.** That is the join key: `<repo>-code §svc.airspace-service` gives `alias`, `label`, `technology`; `<repo>-svc §svc.airspace-service` gives `description`. Together they fill all four arguments of `Container(alias, label, technology, description)` and supply `Rel(...)` labels. This is why **Stage B must ship before Stage C**: the extractor is what normalises the id, and without a normalised id every contributor invents their own name and the two documents never join.

`hist.<name>` is a separate section rather than part of `svc.<name>` for a specific reason: it appends on every ticket, and folding it into `svc.<name>` would push a just-`reviewed` section back to `pending` each time.

Prefixes dropped from the earlier sketch: `rel.` (no producer, and `dep.`/`svc.` cover it) and `struct.api.<module>` (per-language function signatures — the most expensive thing to build and the least useful for either consumer; C4 L2 is containers, not classes, and the Dev reads real code anyway).

### 6.3 L2 / L3 content rules

| | `-code` | `-svc` |
|---|---|---|
| **L2** (`.md`) | generated digest: service one-liner + ports, table column/type/PK digest, dependency overview. Pipe tables allowed. | **responsibility prose**: what the service is for, which flows cross it, citing `doc-id §section` of the domain KB where a rule applies. LLM draft, human-corrected. |
| **L3** (`.raw.md`) | full extracted detail: complete `CREATE TABLE` DDL, full pinned dependency list, full endpoint list — **always in fenced code blocks, never pipe tables** (§3.7). | **code evidence**, deterministic: files belonging to the service, routes/handlers/entry points, tables it reaches, module-level docstrings/comment headers — in a fenced block. |

`-svc`'s shape is deliberately identical to a domain document's: L3 is the raw source, L2 is the summary. That is what lets `collect_pending()` → `build_section_prompt()` → `summarize_kb()` run **unmodified** — the code evidence in L3 *is* the prompt material.

Both files carry a banner under the H1: `> Generated by kb code-ingest at <short-commit> — do not edit by hand.` for `-code`, and for `-svc` `> Responsibility text is human-owned. L3 code evidence regenerated at <short-commit>.`

### 6.4 Manifest and index mapping (no model changes)

| Appendix B sketch | Implemented as |
|---|---|
| `generated: true` | doc-id suffix + index tag (`generated` / `curated`) + banner line |
| `source_commit: "9d1c4e2"` | `Manifest.revision` = short HEAD commit; `Manifest.source_sha256` = full HEAD commit hash |
| per-section `kind:` | section-id prefix (§6.2) |
| `tokens: {l2, l3}` | already exists — filled by `kb build` |

**Two notes on the mapping, recorded because both look wrong at a glance.**

`Manifest.source_sha256` holds a 40-char git commit, not a sha256 of a source file. This is safe — the field is declared in `models.py:39` and never read or validated anywhere — but it is a semantic overload, and it is visible in published manifests. It is chosen over adding a field because §3.3 forbids model changes.

`Manifest.ingested` = **HEAD commit date**, never wall-clock, or determinism (§3.5) breaks.

**`kb code-ingest` must preserve per-section `tokens` when it rewrites a manifest.** `build_kb` fills `sec.tokens` and calls `save_yaml_model` (`build.py:73-76`), so a wholesale rewrite zeroes what build wrote. In CI the order (`code-ingest` → `build` → `ci-publish`) refills them, so published bytes stay deterministic — but a Dev running `code-ingest` alone would produce pointless git churn. Preserve them by section id, the same way §8.1 preserves user-added index tags.

### 6.5 Dirty-tree caveat

`Manifest.revision` is HEAD while the working tree may hold uncommitted changes, so a local run can describe content that is not in any commit. CI runs on a clean checkout, so published artifacts are honest. `kb code-ingest` prints a warning when the tree is dirty.

## 7. Component D — `codeingest` engine + cross-stack extractors

New package `src/center_kb/codeingest/`: `core.py` (orchestrate → assemble → write → upsert index) and `extractors/`.

```python
@dataclass
class ExtractResult:
    sections: list[CodeSection]
    warnings: list[str]        # a single unparseable file names itself here; never crashes the run

class Extractor(Protocol):
    name: str
    def detect(self, root: Path) -> bool: ...           # cheap: does this repo have my input?
    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult: ...
```

`CodeSection` (dataclass in `core.py`): `id`, `title`, `summary`, `group` (file stem), `l2_md`, `l3_md`. `core.py` sorts by `(group, id)`, renders one `.md` + `.raw.md` pair per group, and never touches groups no extractor produced. Returning `ExtractResult` rather than a bare list makes warnings part of the contract, so they are testable.

**Extractors are classified by artifact kind, not by language** (§3.12):

| Prio | Extractor | Input | Sections | Parser |
|---|---|---|---|---|
| 1 | `services` | `docker-compose*.yml`, `Dockerfile`, k8s manifests, `*.sln`, workspace `package.json` | `svc.<name>` | PyYAML, `xml.etree`, re |
| 1 | `deps` | `pyproject.toml`, `requirements*.txt`, `setup.cfg`, `package.json`, `pom.xml`, `build.gradle{,.kts}`, `*.csproj`, `go.mod`, `composer.json` | `dep.<ecosystem>` + framework detection | `tomllib`, `json`, `xml.etree`, re |
| 1 | `tree` | directory tree, ignoring `node_modules`/`target`/`bin`/`obj`/`dist`/`build`/`venv`/`__pycache__`/`.git` | `struct.tree` | — |
| 2 | `schema` | `**/migrations/*.sql`, Flyway/Liquibase layouts, `schema.prisma`, Alembic `versions/*.py`, EF `Migrations/*.cs`, plus explicit `--db` SQLite | `db.<table>` | re, `sqlite3` |
| 3 | `integrations` | `.env.example`/`.sample`/`.template` **keys**, compose `environment:` **keys**, OpenAPI `servers:` | `int.<name>` | PyYAML, re |
| 3 | `api` | `openapi*.y*ml`, `swagger*.json` | `api.<tag>` | PyYAML, `json` |

Everything runs on the stdlib plus PyYAML, which is already a core dependency — **no new dependency**, and `requires-python = ">=3.11"` guarantees `tomllib`.

**Framework detection** is a static lookup table from dependency name → technology label: `spring-boot-starter-*` → Spring Boot, `Microsoft.AspNetCore.*` → ASP.NET Core, `fastapi`/`django`/`flask`, `react`/`next` → React/Next.js, `@angular/core` → Angular, `vue`. It is the only source of the `technology` argument of a C4 container, and it covers frontend and backend identically. Adding a framework is one row.

**Deliberate parser limits, stated so they are not mistaken for bugs.** `schema` recognises `CREATE TABLE` and `ALTER TABLE … ADD COLUMN`, applied in sorted filename order; it does not implement a SQL dialect, and anything else (renames, complex drops) produces a warning naming the file rather than a guess. `build.gradle` is matched by regex, not parsed as Groovy/Kotlin DSL. This is why §3.9 says the code wins.

**Determinism rules** (§3.5), including two that are mandatory because this repo supports Windows: normalise path separators to `/`; normalise line endings to `\n`. Plus: sort sections by `(group, id)`, dependencies by name, tables by name — but **preserve column order**, which carries meaning; sort keys when emitting YAML/JSON so upstream dict order cannot leak.

**Zero-detection rule (revised).** `tree` always detects, so "no extractor detected anything" can no longer happen. The rule becomes: **exit 1 when no extractor other than `tree` detected anything** — a document holding only a directory tree is a misconfiguration, not knowledge.

## 8. Component E — `kb code-ingest` CLI

```
kb code-ingest [--repo-root .] [--kb-dir .kb] [--repo-id <cfg>] [--doc-id <repo_id>-code]
               [--db <path>]... [--tags "a,b"] [--scaffold-svc] [--json]
```

Thin CLI over `codeingest.run()`, following the `ingestcmd`/`initcmd` pattern.

### 8.1 Default behaviour (generated document)

Run every detecting extractor plus explicit `--db`; write `.kb/<doc-id>/`; create or update the `index.yaml` entry, **preserving user-added tags**; preserve per-section `tokens` (§6.4); print a report (sections per extractor, files written, warnings, dirty-tree warning). Idempotent: an unchanged tree rewrites identical bytes, so `kb ci-publish`'s hash diff sees nothing to publish. `kb build` is **not** called implicitly — the workflow runs it as its own step so the two failure modes stay distinguishable.

### 8.2 `--scaffold-svc` (curated document)

For each `svc.<name>` the extractors found, upsert a section into `.kb/<repo_id>-svc/`:

- **absent** → create with `status: pending`, an L2 heading plus `<!-- TODO:summarize svc.<name> -->` (the exact marker `summarize.rebuild_l2_scaffold` produces), and L3 filled with deterministic code evidence;
- **present** → refresh **L3 evidence only**; never touch L2 or `status`. Upsert, never clobber.

`flow.*` sections are never created or touched by the extractor — they are human-authored only. `hist.*` sections are left untouched; only `kb svc note` writes them.

### 8.3 Stale-risk detection

When refreshing L3 evidence for a section whose L2 is already `reviewed`, compare new evidence against old. If it changed materially (files added/removed, routes changed, tables changed), emit `stale-risk: svc.<name>` in the report and in `--json`. It never edits L2. This is the mitigation for the one real cost of a curated document: it cannot self-heal, so it must at least self-report.

**How a human amends one section — and one trap to document.** Correct that section's L2 prose by hand and leave it `reviewed`: the person editing it *is* the reviewer. Do **not** reach for `kb summarize --redo`. `redo_reset()` has no per-section scope: it resets **every** section of the document — `reviewed` ones included — to `pending`, clears each `summary`, and rebuilds every L2 file from scaffold (`summarize.py:314-343`). It is the right tool for re-seeding a document from scratch and a destructive one for amending a single service. A per-section variant is recorded as follow-on work (§15).

### 8.4 Orphans

A `svc.<name>` in `-svc` with no counterpart in `-code` (service deleted or renamed) is reported as `orphan: svc.<name>`. Never auto-deleted — it is human-authored content.

## 9. Component F — `kb svc note` CLI

```
kb svc note <service> --ticket <id> --title "<title>" --refs "doc §s, doc §s"
             [--kb-dir .kb] [--doc-id <repo_id>-svc] [--json]
```

A new `svc` sub-app, following the `kb context new` / `kb ticket lint` / `kb mission lint` precedent. Appends one row to `-svc §hist.<service>`: L2 is a `| Ticket | Title | Domain refs |` pipe table sorted by ticket id; L3 is a fenced block with the fuller record (ticket path, AC ids). L3 carries **no** pipe table, satisfying §3.7 by construction.

Deterministic and **idempotent**: re-running for the same ticket + service updates that row rather than duplicating it. `hist.*` sections are written with `status: summarized` and a fixed extractor-authored `summary` — they are facts ("this ticket touched this service"), not claims, so they need no review and cannot block `kb build`.

Creates `hist.<service>` if absent. Exits 1 if `<service>` has no `svc.<name>` section in `-code` — a typo must not invent a service.

## 10. Component G — skill `dev-code-seed` + 4 wrappers

The one-time bootstrap for a repo adopting center-kb, and the answer to §1's adoption problem. Four wrappers, kind `dev` only.

**Workflow:**

1. **Preflight** — confirm `.kb/config.yaml` has `hub:`, `repo_id:`, `intake:`; confirm the repo is allowlisted on the hub (or tell the Dev to request it); warn if the tree is dirty.
2. **Extract** — `kb code-ingest --scaffold-svc`. Report sections per extractor. If it exits 1 (nothing but `tree` detected), stop and explain which artifact kinds were looked for — this is a configuration problem (e.g. `--db` paths, a missing compose file), not a reason to hand-write knowledge.
3. **Draft** — `kb summarize <repo_id>-svc` (the doc-id argument keeps it off `-code`). Uses the configured runner and `llm.max_workers`.
4. **Review — the actual work, and it is a human's** — walk the drafted `svc.*` one at a time. For each: show the draft L2 beside its L3 code evidence, and ask the Dev to correct it. The agent must state plainly that a draft may be wrong and that approving it unread defeats the gate. Where a responsibility derives from a standard, cite `doc-id §section` from the domain KB — never restate the rule from the draft.
5. **Approve** — `kb approve <repo_id>-svc` (or `--section` for a subset) to flip `summarized` → `reviewed`. Only sections the Dev confirmed.
6. **Flows (optional)** — add `flow.<name>` sections for business flows crossing several services, if the Dev can describe them. Skipped freely; a missing flow is better than a guessed one.
7. **Validate and publish** — `kb build` **without** `--allow-pending` must pass; anything still `pending` is either approved or removed. Then commit and `kb publish` (PR mode) for BA/architect review on the hub.

**Hard rules block (verbatim in all four wrappers):**

- The LLM draft is a **draft**. Never approve a section the Dev has not read and corrected.
- A responsibility that touches a standard cites `doc-id §section` from the domain KB. Never restate a rule from the draft as if it were the standard (§3.10).
- Never invent a service, table, or flow that the extractors did not find and the Dev did not confirm.
- `kb build --allow-pending` is for the middle of a seed only. Publishing requires a clean `kb build` — never publish `pending` knowledge.
- Unsure about a service's responsibility → leave it `pending` and record an owned open question. A blank is honest; a guess is not.
- Never edit `-code`: it is regenerated and overwritten on the next merge.
- Never run `kb summarize --redo` to fix one service. It resets the **whole** document, `reviewed` sections included, and rebuilds every L2 from scaffold (§8.3). Amend by hand.

**Note on the build gate — it is free and it is load-bearing.** `kb build` has `--allow-pending` but **no** `--doc-id` (`cli.py:597-606`), so it validates the whole index. Therefore any `pending` section committed to the default branch fails CI. That is exactly the desired behaviour: **unreviewed knowledge cannot reach the hub**, enforced without a line of new code and without touching `build.py`.

## 11. Component H — CI workflow `kb-code.yml`

New init template, kind `dev` only.

- Trigger: `push` to the default branch (a merge means the structure may have changed) plus `workflow_dispatch`.
- Steps: checkout → setup-python → `pip install center-kb` → `kb code-ingest` (with the repo's committed flags, e.g. `--db` paths, edited once by the team) → `kb build` → `kb ci-publish`.
- **Deliberately no `--scaffold-svc` in CI.** CI must never create `pending` content: it would fail its own `kb build` step. The seed and every amend are human-driven and local (§10). Clean split: **CI owns the deterministic document, humans own the curated one.**
- Publish path: the existing OIDC intake — `kb ci-publish` diffs content hashes against the hub and opens a hub PR. No secrets, no tag dance, `intake:` from the committed config. No `kb-publish/*` tag is involved, so the child tag flow and this flow cannot trigger each other.
- Auto-merge of `-code` hub PRs is a hub-side branch-protection/labeling policy documented in QUICKSTART-DEV, not tool behaviour. `-svc` PRs are never auto-merged.

## 12. Component I — BA wrappers read code knowledge (Stage D)

The earlier sketch left this as "a template-only follow-up, not in this phase's gate". **That is reversed here**, because it is the step that makes Stages B and C worth anything: without it the BA Agent does not know the two documents exist, and keeps writing `%%TODO%%` over knowledge that is now on the hub — a road built with no gate.

Eight files change (`ba-ticket-author` and `ba-mission-plan`, each in Claude-skill / Claude-command / Copilot-prompt / Cursor-command form). The additions go where the existing hard rule already sits (`claude-skill-ba-mission-plan.md:118-120`, "never fabricate … service names"):

- Prefer `<repo>-code` sections for **names**: service/container names, table names, endpoints, detected technology.
- Prefer `<repo>-svc` sections for **meaning**: what a container is responsible for (the `description` argument), `Rel(...)` labels, and which services a flow crosses.
- Fill all four arguments of `Container(alias, label, technology, description)` when both documents can answer.
- Write `%%TODO: verify against codebase%%` only when **neither** document answers — and then the existing rule stands: one owned row in `## Technology decisions`.
- `-svc` responsibility text grounds a diagram; it never substitutes for a domain citation in an AC (§3.10).

## 13. Testing (hermetic — no live hub, no LLM, no network; `git_kb` fixture patterns)

- `tests/test_codeingest_extractors.py` — a fixture mini-repo covering **several stacks at once** (a Python package with `pyproject.toml`; a `package.json` with a React dependency; a `pom.xml`; a `docker-compose.yml` with two services and `depends_on`; a `.env.example`; a SQL migration directory; an `openapi.yaml`) plus a SQLite file generated at test time. Asserts: golden section ids/titles per extractor, framework detection per ecosystem, `.env.example` **keys only and no values** (§3.11), `CREATE TABLE` + `ALTER TABLE ADD COLUMN` accumulation, a single unparseable file producing a warning that names it while other sections survive, and the revised zero-detection `exit 1` (a repo with only a directory tree).
- **Determinism test** — two runs produce byte-identical trees; a fixture with `\r\n` and Windows-style paths still yields `/` separators and `\n` endings.
- **Build-compat test (the load-bearing one)** — run `kb code-ingest` on the fixture, then `build_kb()`: PASS with **no** `--allow-pending`, proving the summary/TODO and table-integrity invariants (§3.7) by construction rather than by review.
- `tests/test_codeingest_scaffold.py` — `--scaffold-svc` creates `pending` sections with the exact `<!-- TODO:summarize <sid> -->` marker; a second run refreshes L3 only and leaves L2 + `status` untouched; a `reviewed` section whose evidence changed yields `stale-risk`; a `-svc` section with no `-code` counterpart yields `orphan`; `build_kb()` on the scaffolded state FAILS without `--allow-pending` and PASSES with it (the §10 gate, asserted).
- `tests/test_cli_codeingest.py` — flags, `--json` shape, index entry created with `[code, generated]` / `[code, curated]` and updated **without clobbering user tags**, per-section `tokens` preserved across a rewrite, exit codes.
- `tests/test_svcnote.py` — `kb svc note` appends a sorted row; re-running the same ticket updates instead of duplicating; L3 contains no pipe table; unknown service exits 1; `hist.*` is `status: summarized` so `build_kb()` stays clean.
- **Search/federation smoke** — publish both documents into the `git_kb` fixture hub; `kb query` finds `db.<table>` and both `svc.<name>` sections; `kb_get_section` returns L3 DDL and L3 code evidence. The assertion is that **zero engine changes** were needed.
- `tests/test_init.py` — kind `dev` scaffolds exactly the §4 set per stage and **none** of the ingest/docker/BA artifacts; hub/child/ba expected-file lists byte-identical to before (assert absence); `_resolve_kind` accepts `dev`; the frozen non-interactive error string unchanged.
- `tests/test_templates.py` — `dev-implement-ticket` × 4 contain the 7 steps, `kb_resolve` **and** `kb resolve`, `kb get` (and **not** `kb diff`), `%%TODO: verify against codebase%%`, "never edit the ticket", `OPEN(BA)`, the `-svc`-is-not-a-source rule, the `kb svc note` handover step, and the KB-feedback DoD rule. `dev-code-seed` × 4 contain the 7 steps, `--scaffold-svc`, `kb summarize <doc>`, `kb approve`, the draft-is-a-draft rule, and the never-publish-pending rule. Claude skills carry `name: dev-implement-ticket` / `name: dev-code-seed`; Copilot prompts carry `mode: agent`; Claude command files are the 2-line Skill invokers (kb-approve pattern). The 8 BA wrappers contain the `-code`/`-svc` preference rules and the four-argument `Container(...)` instruction.
- **Workflow content test** — `kb-code.yml` triggers on push-to-default + `workflow_dispatch`; runs `code-ingest` → `build` → `ci-publish`; contains **no** `--scaffold-svc`, no hardcoded URL, no token.
- **MCP contract** — golden `mcp_tools.json` byte-identical; exactly 5 tools; `tests-gate/regression/test_mcp_contract.py` green untouched.
- **Config** — `kind: dev` round-trips through `load_config`; `doctor.check_kind` unchanged.

## 14. Compatibility and rollout

| Stage | Content | Est. | Release |
|---|---|---|---|
| **A** | kind `dev` + `dev-implement-ticket` | 1–1.5 d | minor |
| **B** | cross-stack extractors + `kb code-ingest` + `--scaffold-svc` + `kb-code.yml` | 7–7.5 d | minor |
| **C** | `dev-code-seed` + `kb svc note` + step-7 handover + hard rules + reused wrappers | 2–2.5 d | minor |
| **D** | 8 BA wrappers read code knowledge | 0.5–1 d | minor |
| | **Total** | **~11–12.5 d** | |

Order is mandatory: **C needs B** (normalised `svc.<name>` ids, §6.2) and **D needs B + C** (content to read).

- Stage A is purely additive: no engine, model, or MCP change; existing hub/child/ba repos untouched.
- Stages B–D add a package, two commands, and templates; `models.py`, `build.py`, `searchdb`, federation, MCP, and web are untouched.
- Existing golden fixtures (`tests-gate/golden/*`) stay byte-identical — enforced by §3.3.
- Re-running `kb init --kind dev` refreshes wrappers/workflow per the standing non-protected-file overwrite behaviour; `.kb/config.yaml` and `.kb/index.yaml` are protected. QUICKSTART-DEV repeats the hand-edit warning.
- **Operational prerequisites** (not code): allowlist each dev repo in the hub's `federation/registry.yaml`; decide the hub auto-merge policy for `-code` PRs (and that `-svc` PRs are excluded); set `CENTER_KB_HUB_URL` + `CENTER_KB_HTTP_TOKEN` per Dev; budget the seed pass (~10–15 min per service, once).

## 15. Deferred / follow-on

- **More extractors** — GraphQL schema, ORM model introspection, route introspection for frameworks that need runtime, cross-repo call graph. The `Extractor` protocol is the seam; each is its own small plan.
- **Extractor plugins via entry points** — let a project line ship `center-kb-ext-<stack>`. Rejected for now, not forever: `kb build` invariants, determinism, and auto-merge safety would depend on third-party code, and §3.5/§3.7 rest on those guarantees. The public `Extractor` protocol is documented so this can be added later without changing the contract.
- **Per-ticket responsibility authoring by the Dev** (the heavier version of Stage C, where a Dev writes new responsibility prose at every ticket). Deferred deliberately: it demands continuous discipline and so runs straight into the Architecture v0.4 §16 "curated KB dies quietly" risk, whereas a one-time seed plus automatic `hist.*` accrual does not. Revisit only if the pilot shows seed + `hist.` leaves a real gap.
- **`kb summarize --redo --section <id>`** — a per-section re-draft. Today `redo_reset()` is document-wide and destroys `reviewed` content (§8.3), so amending one service has to be a hand edit. Add when a repo does enough amending to justify an engine change.
- **`kb code-ingest --check`** — CI-only verification that committed `-code` matches the tree (fail = someone hand-edited generated files). Add on the first hand-edit incident.
- **Dev-side ticket write-back** — opening the placeholder-resolution report as a PR against the BA repo automatically. Needs a cross-repo credential story; manual paste-back is fine for the pilot.
- **LLM pass over `-code`** — forbidden, not deferred (§3.5).

## 16. Decisions log

| Decision | Choice |
|---|---|
| Packaging | Everything in `center-kb`; shipped as four stages, A first (unblocks the pilot, needs no new engine) |
| Extractor classification | By **artifact kind** (container manifest, dependency manifest, migration, API contract), never by language — center-kb is a framework across project lines (§3.12). Rejected: the per-language set (`python` AST + `deps` + `sqlite`), which exits 1 on most adopting repos |
| `struct.api.<module>` | **Dropped.** Per-language function signatures are the most expensive extractor and the least useful: C4 L2 is containers, and the Dev reads real code anyway |
| Framework detection | Static dependency-name → technology lookup table; the only source of C4 `technology`, identical for FE and BE; one row per framework |
| Generated vs curated | **Two documents, never one** — overwrite-vs-accumulate, `pending`-vs-clean build, auto-merge-vs-review (§3.8). Joined by a deliberately colliding `svc.<name>` id |
| Curated L2 authorship | LLM **draft** from deterministic L3 code evidence, corrected by a human, gated by `kb approve` — the exact pattern Phase 1–3 chose for PDFs, reusing `summarize_kb()`/`approve_sections()` unmodified. Rejected: pure human authoring (too slow to bootstrap) and unreviewed LLM output (a self-confirming loop: code → description → code) |
| Bootstrap vs accumulation | **Both, because they cover different time.** A one-time seed covers the running system's past; `hist.*` covers every future ticket. A per-ticket-only mechanism yields nothing on adoption day — the case that matters most for a framework |
| Responsibility text authority | Never a source for an AC or standard value (§3.10) — that stays verbatim from a pinned domain section, or the work stops |
| Stale handling for `-svc` | Cannot self-heal, so it must self-report: `stale-risk` when L3 evidence changes under a `reviewed` L2 (§8.3); orphans reported, never auto-deleted |
| CI vs human split | CI owns `-code` only; `--scaffold-svc` never runs in CI (it would fail CI's own clean `kb build`). That same clean build is the free gate that stops unreviewed knowledge reaching the hub |
| Stale-ref diff tooling | `kb resolve` (pinned + verdict) + `kb get` (current hub). **`kb diff` is wrong here** and is banned from the wrappers: it compares the local worktree to a local rev and a `dev` repo has no local copy of the cited document |
| MCP tools | Zero added — count stays 5; every new capability is a CLI command (mirrors Phase 4.1 §9) |
| Appendix B manifest keys | Not model fields — mapped onto existing fields (`revision`/`source_sha256` = commit; kind = id prefix; generated = suffix + tag). Rejected: extending `SectionEntry`/`Manifest`, which re-serializes every existing manifest and churns golden fixtures and content hashes |
| `source_sha256` = git commit | Accepted overload, documented (§6.4) rather than fixed with a new field |
| L3 tables | Fenced code blocks only — keeps the table-integrity invariant satisfiable by construction |
| `.env` handling | `.env.example` **keys only**, never values, never the real `.env` (§3.11) |
| SQLite input | Explicit `--db` only, never auto-globbed — a test fixture database must not become published company knowledge |
| Zero extraction | Exit 1 when nothing but `tree` detected — a directory tree alone is misconfiguration, not knowledge |
| Publish path | `kb ci-publish` (OIDC intake) for `-code` on push-to-default; `kb publish` (PR) for `-svc` by a human. Idempotent via content-hash diff; auto-merge is hub policy, `-svc` excluded |
| Ticket ownership | The Dev Agent never edits the BA's ticket; resolutions and AC findings are reported back as `OPEN(BA)` |
| Kind `dev` boundary | `child` ingests documents from outside the repo; `dev` ingests nothing and authors only knowledge about its own code. Phase 4's "never authors" is superseded and the reason recorded (§4) |
| BA wrapper update | **In this phase's gate** as Stage D — reversing the earlier "template-only follow-up". Without it Stages B and C are unread |
| Extractor plugins | Deferred, not rejected — protocol stays public and documented (§15) |
| `dev` scaffold shape | Separate `DEV_TEMPLATES` map (not `COMMON_TEMPLATES`), exactly like `BA_TEMPLATES`; hub/child/ba scaffolds gain nothing |
| Slash commands | Both skills ship all four wrappers (Claude skill + Claude command + Copilot prompt + Cursor command); `kb-summarize`/`kb-approve`/`kb-publish` wrappers are reused on `dev` for the seed flow |
| Non-interactive init message | Stays `--kind hub|child` (frozen by an existing test) — standing Phase 4 decision |
| Doc-id namespace | `-code` and `-svc` reserved by convention, documented in README; collision is a documented misconfiguration, not lint-enforced |
