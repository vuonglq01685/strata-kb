# Phase 4 — BA Agent (`ba-ticket-author` + ticket template + `kb ticket lint` + init kind `ba`) — Design

**Date:** 2026-07-17 (v2 — same-day revision after scope decisions, see §12)
**Status:** Proposed design — not yet implemented (plan: `docs/superpowers/plans/2026-07-17-ba-agent.md`)
**Scope:** All three Phase 4 items from Architecture Spec v0.3 §13.5 — skill `ba-ticket-author`, the standard ticket template, and the `kb ticket lint` DoR gate — **plus** two additions decided 2026-07-17: a dedicated BA repo kind (`kb init --kind ba`) and a scaffolded CI DoR gate on that repo's `tickets/` directory. Jira integration is **Markdown-out only**: the agent produces a paste-ready ticket body; the BA reviews and publishes to Jira manually (human-in-the-loop, §13.4). BAs work **in their own requirements repo** with an agentic client (Claude Code / Copilot / Cursor); a chat-only flow via MCP prompt was considered and **dropped** (decision 2026-07-17).

---

## 1. Problem

Phase 1–3 give BAs grounded *retrieval* (kb_search → confirm → kb_context_new → kb_resolve), but turning retrieved knowledge into a Dev-ready ticket is still ad-hoc: no standard structure, citations are optional in practice, diagrams are hand-made, and nothing enforces the team's Definition of Ready ("requirement touching an industry standard without a citation is not Ready"). Phase 4 packages the existing mechanisms into a repeatable ticket-authoring pipeline (Architecture v0.3 §13.2): Intake → Ground → Draft → Pin → Lint → BA review.

Phase 4 builds **no new engine**. The four core MCP tools are unchanged (§9.2 invariant); everything below is orchestration (a skill), a template, one lint command, and one new init kind — all reusing `kbcontext` + `resolve` + `doctor.check_context`.

## 2. Goals

- A BA, working in the team's requirements repo with Claude Code (or Copilot/Cursor), runs `/ba-ticket-author` and produces a standard ticket: Story, Background, ACs, use cases, Mermaid sequence + flow diagrams, pinned `kb-context` block — saved under `tickets/`, versioned by Git.
- Every industry-standard claim carries a `doc-id §section` citation that resolves at the pinned hub commit.
- A machine-checkable DoR gate at two levels: locally (`kb ticket lint` CLI / `kb_ticket_lint` MCP) and in CI (PR touching `tickets/` must lint PASS to merge).
- Onboarding a new BA is `pip install center-kb` + clone (or `kb init --kind ba`) + two env vars — no KB authoring machinery in their way.
- Human-in-the-loop preserved: the agent never pushes to Jira, never picks between close-scoring search hits on its own.

Non-goals: Jira REST integration (revisit later as a separate spec); an MCP prompt / chat-only no-repo flow (dropped 2026-07-17 — every BA uses the requirements repo); `kb ticket new` scaffolding command (deferred, §11); sequence-diagram grounding in code structure (needs Phase 5 code-knowledge — diagrams in Phase 4 are grounded in KB + BA input only).

## 3. Architecture constraints

1. **Core four MCP tools unchanged** (`kb_search`, `kb_get_section`, `kb_context_new`, `kb_resolve`). §9.2 explicitly allows Phase 4 to *add* tools — we add exactly one: `kb_ticket_lint`.
2. **Hub is the only read source.** Lint resolves refs against the hub federation exactly like `kb doctor --context` (reuses `doctor.check_context` → `resolve.resolve_refs`). This holds in CI too — the workflow needs read access to the hub.
3. **Ticket is Markdown** — renders in Jira/GitHub (Mermaid as diagram-as-code), lint-able as text, versioned in Git.
4. **Citation style rules inherited from kb-summarize**: codes, record/field names, numbers, §refs verbatim; no inference beyond source; unsure → cite and flag, never fabricate.
5. **One content, one source**: the required-heading list lives in one Python constant; the skill wrappers and the shipped template must never drift from it (sync tests).
6. **Version discipline**: `REQUIRED_HEADINGS` is a compatibility contract between the BA's local install, the shared MCP server, and CI. Changing it is a breaking change — minor/major release only, changelog entry mandatory.

## 4. Component A — standard ticket template

One canonical template, shipped in the package and scaffolded to `docs/tickets/TEMPLATE.md` on kind `ba` (only BAs draft tickets — decision 2026-07-17), so the BA repo carries the reference copy the skill and humans read.

Required structure (headings are the lint contract, English headings fixed; body language follows the BA's working language):

```markdown
# <Title — one line, imperative, with identifier>

## Summary
<1–2 lines business summary>

## User Story
As a <role>, I want <capability>, so that <value>.

## Background / Business context
<context; every industry-standard claim cites `doc-id §section`>

## Acceptance Criteria
- [ ] AC1 … (cite `doc-id §section` when it touches a standard)
- [ ] AC2 …

## Use cases
### Main flow
### Alternate / exception flows

## Sequence diagram
```mermaid
sequenceDiagram
  …
```

## Business flow
```mermaid
flowchart TD
  …
```

## KB context
```yaml
kb-context:
  version: "<hub commit>"
  refs:
    - <repo:doc-id §section>
  tags: [ … ]
```

## Definition of Ready
- [ ] Story, ACs, use cases, both diagrams present
- [ ] Every citation resolves at the pinned version (kb ticket lint PASS)
- [ ] No stale refs
```

Single source of truth for the required-heading list is a Python constant in the new `ticket.py` module; a unit test asserts the shipped template and the constant never drift.

## 5. Component B — `kb ticket lint` (DoR gate)

New Typer sub-app `kb ticket` with one command for now:

```
kb ticket lint <file|-> [--kb-dir .kb] [--hub <url|path>] [--json]
```

New module `src/center_kb/ticketlint.py` (engine, no CLI deps) returning `list[Issue]` (reuse `doctor.Issue`) + a machine summary. Checks, in order:

| # | Check | Level |
|---|---|---|
| 1 | All required headings present (constant from `ticket.py`) | error |
| 2 | User Story matches `As a … I want … so that …` (case-insensitive, multiline) | error |
| 3 | ≥ 1 Acceptance Criterion checkbox item | error |
| 4 | `## Sequence diagram` contains a ```` ```mermaid ```` fence with `sequenceDiagram`; `## Business flow` contains one with `flowchart` | error |
| 5 | `kb-context` block parses (`kbcontext.parse`) | error |
| 6 | Every ref resolves at the pinned version — delegate to `doctor.check_context` | error (broken) / warning (stale) |
| 7 | Consistency: every inline citation `doc §sec` in the body appears in `kb-context.refs` | error |
| 8 | Reverse consistency: every pinned ref is cited at least once in the body | warning |
| 9 | An AC containing no citation | warning (lint cannot judge whether the AC touches a standard) |

Exit code: 1 if any error, else 0 (warnings allowed, printed). `--json` emits `{"pass": bool, "errors": [...], "warnings": [...]}` for agent/CI consumption. Human output mirrors `kb doctor` style (`[error] …` / `[warn] …` + final `DoR: PASS|FAIL`). Body text is UTF-8 throughout (Vietnamese bodies + `§` on Windows consoles — `utf8io` applies; tests must cover a Vietnamese-body ticket).

Inline-citation extraction (check 7) uses a conservative regex for `<doc-id> §<sec>` / `<repo:doc-id> §<sec>` matching `kbcontext._REF_RE` semantics; refs without repo qualifier match a pinned ref with any repo qualifier.

## 6. Component C — MCP tool `kb_ticket_lint`

Same engine (`ticketlint.lint(text, hub)`), exposed as the fifth MCP tool:

```python
kb_ticket_lint(ticket_markdown: str) -> str
```

Rendered as text like the other tools, prefixed by the standard stale-hub note. Registered in `mcp.create_server`; the core four are untouched. With the BA-repo decision this tool is a *secondary* channel (agents in the repo can run the CLI), kept because it is thin over the same engine and lets any MCP-connected client lint without a shell.

## 7. Component D — skill `ba-ticket-author` + wrappers

Four thin templates (file layout same pattern as kb-approve) registered in `BA_TEMPLATES` — scaffolded on kind `ba` **only**: `.claude/skills/ba-ticket-author/SKILL.md`, `.claude/commands/ba-ticket-author.md`, `.github/prompts/ba-ticket-author.prompt.md`, `.cursor/commands/ba-ticket-author.md`. Devs do NOT draft tickets (decision 2026-07-17) — hub/child scaffolds gain nothing from Phase 4; a dedicated `kb init --kind dev` with its own agent ships with Phase 5 (§12).

The Claude skill is the orchestrator (kb-summarize style: explicit workflow + hard rules). Workflow = pipeline §13.2:

1. **Intake** — collect the business need, target tags (`#arinc424 #airspace`) or explicit doc; ask, don't guess.
2. **Ground** — `kb_search` within budget. Present **all** returned candidates with citations. If the ambiguity note fires (two close scores), the BA must choose — never auto-pick.
3. **Draft** — fill the template (§4). Every standard claim cites `doc-id §section` from the confirmed candidates only. Diagram rules: sequence/flow drawn from KB content + what the BA states; where code structure would be needed (service names, DB tables), mark placeholders `%%TODO: verify against codebase%%` rather than inventing (Phase 5 removes this limitation).
4. **Pin** — after the BA confirms the applied sections: `kb_context_new(confirmed refs, tags)` → embed the returned block in `## KB context`.
5. **Lint** — `kb ticket lint` (CLI in the repo; `kb_ticket_lint` MCP as fallback). Fix errors, re-run until PASS; report remaining warnings to the BA.
6. **Review → save → Jira** — write the final Markdown to `tickets/<ticket-id>.md`, let the BA review and commit; the BA pastes to Jira. **Never** push to Jira, never mark DoR checkboxes the BA has not confirmed.

Hard rules block (verbatim in all four wrappers): citations mandatory for standard claims — no citation, no claim; never fabricate codes/values (kb-summarize style rules); present-and-confirm before pinning; agent output is a draft — the BA publishes; lint FAIL is a blocker, do not hand over a failing ticket silently.

## 8. Component E — `kb init --kind ba` (BA requirements repo)

Third repo kind alongside `hub` and `child` (role-aware init, v0.3 §role-aware). A BA repo *consumes* the KB and *versions tickets*; it authors no KB documents, so it must not carry ingest/summarize/publish machinery.

`kb init --kind ba` scaffolds exactly:

| Path | Source template | Purpose |
|---|---|---|
| `.kb/config.yaml` | `config-ba.yaml` (new) | `kind: ba` + hub URL |
| `.mcp.json` | `mcp-child.json` (reuse) | HTTP MCP → shared server (`${CENTER_KB_HUB_URL}` + token env) |
| `.cursor/mcp.json` | `cursor-mcp-child.json` (reuse) | same, for Cursor |
| 4 × `ba-ticket-author` wrappers | Component D | the skill |
| `docs/tickets/TEMPLATE.md` | `ticket-template.md` | reference template |
| `tickets/.gitkeep` | — | where tickets live |
| `.github/workflows/kb-ticket-lint.yml` | Component F | CI DoR gate |
| `QUICKSTART-BA.md` | `QUICKSTART-ba.md` (new) | one-page onboarding |

Explicitly NOT scaffolded on `ba`: kb-ingest / kb-summarize / kb-approve / kb-publish / kb-docker-setup wrappers, `kb-publish.yml`, source-dir gitignore. And symmetrically: nothing from Phase 4 is added to hub/child scaffolds. Implementation note: `initcmd` grows a per-kind template map (`BA_TEMPLATES`, NOT merged into `COMMON_TEMPLATES`); `KINDS`/`template_map()` go from 2-way to 3-way; the interactive kind prompt (`_resolve_kind`) gains the third option; `config.KBConfig.kind` Literal gains `"ba"` — kind validation lives in that pydantic Literal, so without this one-line change `load_config` rejects `kind: ba`; `doctor.check_kind` itself needs no change.

`QUICKSTART-BA.md` content (one page): setup once — install, clone-or-init, two env vars (`CENTER_KB_HUB_URL`, `CENTER_KB_HTTP_TOKEN`), open in Claude Code; per ticket — the 6-step flow of §7; DoR rules — what lint enforces, what stays the BA's judgment (AC citations).

## 9. Component F — CI DoR gate (`kb-ticket-lint.yml`)

New init template `kb-ticket-lint.yml`, scaffolded on kind `ba` only. Behavior:

- Trigger: `pull_request` with `paths: ["tickets/**.md"]`.
- Steps: checkout → setup-python → `pip install center-kb` → for each changed `tickets/*.md` (diff vs base): `kb ticket lint <file> --hub "$CENTER_KB_HUB"` → any FAIL fails the job.
- Hub access: `CENTER_KB_HUB` from repo variable; auth for a private hub via `secrets.KB_HUB_TOKEN`, mirroring the auth approach of the existing `kb-publish.yml` / OIDC intake patterns (documents are copyrighted — never bake credentials into the workflow file).
- Branch protection on the BA repo (require the check) is a repo setting, documented in QUICKSTART-BA, not enforced by the tool.

This makes DoR machine-enforced: a requirement touching a standard without a resolving citation cannot merge into `tickets/`.

## 10. Docs

- QUICKSTART-child + QUICKSTART-hub: add the BA flow one-liner + `kb ticket lint` to the CLI reference.
- QUICKSTART-BA: new, per §8.
- README: Phase 4 section — pipeline, the three kinds table (`hub` / `child` / `ba`), the new command, the fifth MCP tool.
- AERO-KB_Architecture v0.4 (separate doc task, after implementation): §13 "thiết kế" → "vận hành"; init kinds 2 → 3; MCP tools 4 → 5.

## 11. Testing (hermetic — no live hub network, no LLM; `git_kb` fixture)

- `tests/test_ticketlint.py`: every check in §5 — golden pass ticket; each mutation (missing heading, bad story, no AC, missing mermaid, malformed kb-context, broken ref, stale ref via post-pin edit, inline-cite-not-pinned, pinned-not-cited, AC-without-citation) asserts exact level + message fragment; a Vietnamese-body golden ticket; `--json` shape.
- `tests/test_cli_ticket.py`: exit codes, stdin (`-`), `--json`.
- MCP tests: `kb_ticket_lint` registered (5 tools total); happy + broken-ref paths; core-four signatures unchanged (snapshot assert).
- `tests/test_init.py`: kind `ba` scaffolds exactly the §8 set and NOT the authoring wrappers; hub/child scaffolds do NOT gain `ba-ticket-author` or `docs/tickets/TEMPLATE.md` (assert absence — hub/child expected-file lists unchanged); workflow file content (paths filter, no hardcoded secrets).
- Template-sync test: required-headings constant ⊆ shipped template; skill wrappers reference the same headings.

## 12. Deferred / dropped (recorded so context is not lost)

- **MCP prompt `ba-ticket-author`** — DROPPED (decision 2026-07-17): all BAs work in the requirements repo with an agentic client; no chat-only persona to serve. Revisit only if a no-repo BA persona reappears.
- **Kind `dev` (Developer agent)** — decided 2026-07-17: Devs do not draft tickets; a dedicated `kb init --kind dev` with its own agent/mode ships with Phase 5 (Developer Package / Codebase-as-Knowledge). Phase 4 deliberately adds nothing to Dev-facing scaffolds.
- **Jira REST draft creation** — possible later behind an explicit flag/skill step; needs credentials story; not in this phase per decision 2026-07-17.
- **`kb ticket new`** — render an empty template to `tickets/<id>.md`; trivial, add when someone asks.
- **Code-grounded diagrams** — arrives with Phase 5 code-knowledge; the `%%TODO: verify against codebase%%` placeholder convention is designed so Phase 5 agents can find and resolve them.
- **Real-world check before pilot (not a code task):** confirm the team's Jira renders Mermaid (plugin) — otherwise diagrams paste as code blocks.

## 13. Decisions log

| Decision | Choice |
|---|---|
| Packaging | Integrate into `center-kb` (2026-07-17): lint engine must live next to `doctor`/`resolve`; skill is a thin template; AERO-specific overrides live in the AERO repos, not a fork |
| Jira integration | Markdown out, BA pastes manually; no API in Phase 4 |
| BA working model | Dedicated requirements repo per team + agentic client; new init kind `ba` (2026-07-17) |
| Who drafts tickets | Only BAs — wrappers + template scaffold on kind `ba` only; hub/child untouched; Devs get their own kind `dev` + agent in Phase 5 (2026-07-17) |
| Chat-only flow | Dropped — no MCP prompt (2026-07-17) |
| CI DoR gate | IN scope (2026-07-17): `kb-ticket-lint.yml` scaffolded on kind `ba` |
| Lint engine placement | New `ticketlint.py`, reuses `doctor.check_context` / `kbcontext` / `resolve`; CLI + MCP are thin wrappers over one engine |
| 5th MCP tool | `kb_ticket_lint` kept as secondary channel — allowed by §9.2; primary gate is the CLI in-repo + CI |
| Template ownership | Package template scaffolded to `docs/tickets/TEMPLATE.md`; headings constant in `ticket.py` is the lint contract; sync tests |
| Heading contract stability | Changing `REQUIRED_HEADINGS` = breaking change; minor/major release + changelog only |
| Heading language | English headings fixed (lint contract); body in the BA's working language (UTF-8, Vietnamese covered by tests) |
| AC citation check | Warning, not error — lint cannot judge which AC touches a standard; the BA owns that judgment via DoR checklist |
| Diagrams without Phase 5 | KB + BA input only; unverifiable code details become `%%TODO%%` placeholders, never invented |
