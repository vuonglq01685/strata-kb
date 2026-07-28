# Phase 4.1 — BA Mission Plan (`ba-mission-plan` + C4 mission template + `kb mission lint`) — Design

**Date:** 2026-07-28
**Status:** Proposed design — not yet implemented
**Builds on:** `docs/superpowers/specs/2026-07-17-ba-agent-design.md` (Phase 4, shipped in `a09f757`)
**Scope:** A second BA authoring flow that sits *upstream* of `ba-ticket-author`: an epic-level Mission Plan carrying C4 Level 1 (System Context) and Level 2 (Container) diagrams plus a US backlog, from which individual User Story tickets are then drafted. Ships as a separate skill (`ba-mission-plan`), a new mission template, a new `kb mission lint` DoR gate, one added check on `kb ticket lint`, and an extension of the existing CI gate. **No new MCP tool** (see §9). Jira integration remains Markdown-out only.

---

## 1. Problem

Phase 4 gives a BA a repeatable pipeline for *one* ticket: Intake → Ground → Draft → Pin → Lint → review. It has no upstream artifact. For a large feature the BA must hold the whole epic in their head, split it into User Stories by intuition, and re-ground every ticket from scratch — with nothing recording *why* the split looks the way it does, what system context the feature lives in, or which containers it touches.

The result is predictable: tickets that individually lint PASS but collectively miss a slice, duplicate scope, or contradict each other on system boundaries. Nothing in the repo says these seven tickets are one feature.

Phase 4.1 adds that upstream artifact and makes the epic→story link machine-checkable. It builds **no new engine**: everything reuses `kbcontext` + `resolve` + `doctor.check_context`, exactly as `ticketlint.py` already does.

## 2. Goals

- A BA runs `/ba-mission-plan` for a large feature and produces a standard mission document under `missions/`: business goal, scope, C4 L1 + L2 diagrams, constraints, a US backlog, and a pinned `kb-context` block.
- Every industry-standard claim in the mission carries a `doc-id §section` citation that resolves at the pinned hub commit — same discipline as tickets.
- Tickets drafted from a mission carry a machine-checkable pointer back to it, and the mission's backlog cannot silently rot.
- The BA can still write a standalone ticket for small work. Missions are for large features only; nothing becomes mandatory.
- Human-in-the-loop preserved: the agent never auto-generates ticket files from the backlog, never picks between close-scoring search hits, never invents system structure it cannot ground.

Non-goals: C4 Level 4 (Code); code-grounded C4 Level 3 (needs Phase 5 code-knowledge — L3 is optional and hand-supplied here); Jira REST integration; any change to the four core MCP tools; any change to `ticket.REQUIRED_HEADINGS`.

## 3. Architecture constraints

1. **Core four MCP tools unchanged** (`kb_search`, `kb_get_section`, `kb_context_new`, `kb_resolve`). Phase 4.1 adds **zero** MCP tools — the count stays at 5 (§9).
2. **Hub is the only read source.** Mission lint resolves refs against the hub federation exactly like `kb doctor --context` (reuses `doctor.check_context` → `resolve.resolve_refs`).
3. **`ticket.REQUIRED_HEADINGS` must not change.** It is a compatibility contract between the BA's local install, the shared MCP server, and CI (Phase 4 spec §3.6); changing it is a breaking change. The ticket→mission link is therefore carried by an *optional* blockquote line, not a new heading (§4.4).
4. **Citation style rules inherited from kb-summarize**: codes, record/field names, numbers, §refs verbatim; no inference beyond source; unsure → cite and flag, never fabricate.
5. **One content, one source**: the required-heading list lives in one Python constant; the shipped template and the skill wrappers must never drift from it (sync tests).
6. **`REQUIRED_MISSION_HEADINGS` carries the same version discipline** as its ticket counterpart: it is a contract across local install / shared server / CI, so changing it is a breaking change — minor/major release only, changelog entry mandatory.
7. **Backwards compatible by construction.** Existing tickets, existing BA repos, and existing MCP clients keep working with no migration step (§11).

## 4. Component A — mission document contract

### 4.1 Identity and file layout

One mechanically derivable rule, so lint needs no configuration:

| Thing | Form | Example |
|---|---|---|
| Mission id | `M-<slug>` | `M-airspace-filter` |
| Mission file | `missions/<mission-id>.md` | `missions/M-airspace-filter.md` |
| US id | `<mission-id>-US<n>` | `M-airspace-filter-US1` |
| Ticket file | `tickets/<us-id>.md` | `tickets/M-airspace-filter-US1.md` |

`<slug>` is lowercase kebab-case chosen by the BA at intake. `<n>` is a positive integer, assigned sequentially by the agent and confirmed by the BA. **Gaps are allowed** — a story dropped during review leaves its number retired rather than forcing a renumber that would break already-drafted ticket filenames. Check 7 therefore tests format and uniqueness, never contiguity.

IDs are **local to the repo**. Jira assigns its own key only when the BA pastes the ticket in, so a Jira key can never be the identity a mission written *beforehand* refers to. A ticket may record `Jira: PROJ-123` for human convenience; that line is **not** part of any lint contract.

The mission id appears **inside the document**, not only in the filename, because lint also runs over stdin where no filename exists:

```markdown
# Filter and display controlled airspace

> Mission: M-airspace-filter
```

When linting an actual file, the filename stem must equal the declared mission id — a mismatch is an error, because every derived US id and ticket path would otherwise be wrong.

### 4.2 Required structure

`REQUIRED_MISSION_HEADINGS`, a constant in the new `mission.py` module. English headings are fixed (the lint contract); body language follows the BA's working language.

```markdown
# <Mission title — one line, imperative>

> Mission: M-<slug>

## Summary
<1–2 lines: what this feature is, at epic level>

## Business goal
<why this exists and how success is measured; cite `doc-id §section` for standard claims>

## Scope
**In scope:** …
**Out of scope:** …

## System context (C4 L1)
```mermaid
C4Context
  …
```

## Containers (C4 L2)
```mermaid
C4Container
  …
```

## Constraints & assumptions
<constraints, open questions, and any `%%TODO: verify against codebase%%` placeholders>

## US backlog
| US ID | Title |
|---|---|
| M-<slug>-US1 | … |
| M-<slug>-US2 | … |

## KB context
```yaml
kb-context:
  version: "<hub commit>"
  refs:
    - <repo:doc-id §section>
  tags: [ … ]
```

## Definition of Ready
- [ ] Business goal, scope, L1 + L2 diagrams, backlog present
- [ ] Every citation resolves at the pinned version (kb mission lint PASS)
- [ ] Backlog reviewed with the team; no known missing slice
```

`## Components (C4 L3)` is **deliberately not required**. When present, lint checks it like the other diagram sections; when absent, nothing fires. Phase 4 spec §12 defers code-grounded diagrams to Phase 5, so L3 here is only drawn from component knowledge the BA supplies directly.

### 4.3 US backlog table — no status column

Two columns only. A hand-maintained status column would rot the moment a ticket is written and nobody edits the mission. Instead `kb mission lint` **computes** coverage from the filesystem — does `tickets/<us-id>.md` exist? — and reports it as a warning (`3/7 US drafted`). Derived state cannot go stale.

### 4.4 Ticket-side back-link

An optional blockquote line immediately under the ticket's H1 title:

```markdown
# Filter airspace by ARINC 424 class

> Parent mission: M-airspace-filter
```

Optional by design. `ticket.REQUIRED_HEADINGS` is untouched, so every existing ticket still lints PASS with no edit. When the line *is* present, `kb ticket lint` enables one additional check (§5.2).

## 5. Component B — lint

### 5.1 `kb mission lint`

New Typer sub-app `kb mission`, mirroring `kb ticket`:

```
kb mission lint <file|-> [--kb-dir .kb] [--hub <url|path>] [--json]
```

Engine in the new `missionlint.py`. Checks, in order:

| # | Check | Level |
|---|---|---|
| 1 | H1 title present; `> Mission: <id>` present and well-formed; when a real file, filename stem equals the id | error |
| 2 | All `REQUIRED_MISSION_HEADINGS` present | error |
| 3 | `## System context (C4 L1)` contains a ```` ```mermaid ```` fence with `C4Context` **or** `flowchart` **at the start of a line** | error |
| 4 | `## Containers (C4 L2)` contains a fence with `C4Container` **or** `flowchart` at the start of a line | error |
| 5 | `## Components (C4 L3)` — only when the section exists: `C4Component` **or** `flowchart` at the start of a line | error |
| 6 | `## US backlog` parses as a pipe table with the exact header row `\| US ID \| Title \|` and ≥ 1 data row | error |
| 7 | Every US id matches `^<mission-id>-US[1-9]\d*$` (zero-padded ids like `US01` are rejected); no duplicates | error |
| 8 | `kb-context` block parses (`kbcontext.parse`) | error |
| 9 | Every ref resolves at the pinned version (`doctor.check_context`) | error (broken) / warning (stale) |
| 10 | Every inline citation in the body appears in `kb-context.refs` | error |
| 11 | Every pinned ref is cited at least once in the body | warning |
| 12 | Coverage: US ids with no `tickets/<us-id>.md` | warning |
| 13 | Unresolved `%%TODO: verify against codebase%%` placeholders remain | warning |

Exit code 1 if any error, else 0. `--json` emits `{"pass": bool, "errors": [...], "warnings": [...], "notes": [...]}`.

Checks 3–5 accept either C4-native or `flowchart` syntax. Mermaid's own documentation states the C4 diagram type is experimental and its "syntax and properties are subject to change in future releases". Binding a breaking-change-class lint contract to upstream-experimental syntax would mean a Mermaid release could fail every team's DoR gate. The check's purpose is *a diagram exists at this level*, not *this diagram is syntactically C4* — so the looser contract is also the more honest one. The shipped template uses C4-native; teams whose renderer lacks C4 support fall back to `flowchart` without failing DoR.

Anchoring at line start rather than requiring the keyword to be the very first token keeps a Mermaid init directive (`%%{init: …}%%` on the line above) from failing an otherwise valid diagram, while still refusing to match the word `flowchart` buried in a node label.

Checks 1 and 12 need paths that stdin and any non-file caller lack. Signature:

```python
lint(
    text: str,
    hub: "HubHandle | None",
    *,
    path: Path | None = None,
    tickets_dir: Path | None = None,
) -> LintReport
```

When `path is None` the filename half of check 1 is skipped; when `tickets_dir is None` check 12 is skipped. Each skip emits **a note saying so**. A skipped check must never be indistinguishable from a passed one.

### 5.2 One added check on `kb ticket lint`

| # | Check | Level |
|---|---|---|
| 10 | When `> Parent mission: <id>` is present: id well-formed; `missions/<id>.md` exists; the ticket's own US id appears in that mission's backlog table | error |

Same degradation rule: without a repo path the check reduces to the format test, and the report carries a note that the rest was skipped. This makes the *existing* fifth MCP tool `kb_ticket_lint` weaker than the CLI — the note is what keeps that visible rather than silently implied.

### 5.3 Module layout

`ticketlint.py` is 276 lines with cleanly separated private check functions, most of which apply verbatim to missions. Shared logic moves to a new module with an accurate name rather than being imported across a private boundary.

| Module | Contents |
|---|---|
| `mission.py` (new) | `REQUIRED_MISSION_HEADINGS`, `MISSION_ID_RE`, `us_id_re(mission_id)` (factory, not a static regex — check 7 must enforce "this US id belongs to *this* mission"), backlog table regex |
| `lintcore.py` (new, extracted) | `LintReport`, `_section_body`, `_check_title`, `_check_headings(text, required)`, `_check_diagram(text, heading, keywords)`, `_strip_bare_kb_context`, `_citation_scan_text`, `_cite_matches_ref`, `_check_citation_consistency`, the `doctor.check_context` wrapper |
| `ticketlint.py` (thinner) | `_check_story`, `_check_ac_present`, `_check_ac_citations`, the new parent-mission check, `lint()` |
| `missionlint.py` (new) | `_check_backlog`, `_check_coverage`, `_check_placeholders`, `lint()` |
| `ticket.py` | gains `PARENT_MISSION_RE`. `REQUIRED_HEADINGS` **unchanged** |

`_check_diagram` changes its `keyword: str` parameter to a tuple of accepted keywords. The extraction is behaviour-preserving; the existing `tests/test_ticketlint.py` suite passing unchanged is the acceptance condition (§10).

## 6. Component C — skill `ba-mission-plan` + wrappers

Four thin wrappers, same file layout pattern as `ba-ticket-author`, registered in `BA_TEMPLATES` and scaffolded on kind `ba` only. The Claude skill is the orchestrator.

Workflow — seven steps, one more than the ticket pipeline:

1. **Intake** — the business need at epic level, target tags or explicit docs, and the mission slug agreed with the BA. Ask, don't guess.
2. **Ground** — `kb_search` within budget. Present **all** returned candidates with citations. If the ambiguity note fires, the BA chooses — never auto-pick.
3. **Draft** — fill the template. C4 L1 and L2 are drawn from KB content plus what the BA states. Anything requiring code structure (service names, database tables) becomes `%%TODO: verify against codebase%%` rather than an invention. L3 only when the BA supplies real component knowledge.
4. **Split the backlog** — propose the US list, the BA edits and confirms. The agent assigns sequential ids per §4.1.
5. **Pin** — `kb_context_new(confirmed refs, tags)` → embed in `## KB context`.
6. **Lint** — `kb mission lint`. Fix errors, re-run until PASS, report warnings. **Coverage 0/N at creation time is expected** and must not be treated as failure.
7. **Review → save** — write `missions/M-<slug>.md`; the BA reviews and commits.

Hard rules block, verbatim in all four wrappers:

- Citations mandatory for standard claims — no citation, no claim.
- Never fabricate codes, values, service names, or table names. Unsure → `%%TODO%%`.
- Present-and-confirm before pinning.
- Lint FAIL is a blocker. **`kb` failing to run is not a PASS** — tell the BA to install it; never skip the lint step silently.
- Agent output is a draft; the BA publishes.
- **Never auto-generate ticket files from the backlog.** Each US goes through `ba-ticket-author` with its own grounding pass.

## 7. Component D — `ba-ticket-author` gains a mission step

When the BA names a parent mission, the ticket skill reads `missions/<id>.md`, takes the US title from the backlog row, and fills the `> Parent mission:` line.

It uses the mission's pinned refs as **starting candidates only**. It must not copy the mission's `kb-context` into the ticket wholesale: a mission is broad and a ticket is narrow, so a wholesale copy drags in refs the ticket never cites and floods check 11 with warnings. The ticket pins its own refs, confirmed fresh.

## 8. Component E — scaffolding and CI

### 8.1 `BA_TEMPLATES` additions

| Path | Source template |
|---|---|
| `.claude/skills/ba-mission-plan/SKILL.md` | `claude-skill-ba-mission-plan.md` |
| `.claude/commands/ba-mission-plan.md` | `claude-command-ba-mission-plan.md` |
| `.github/prompts/ba-mission-plan.prompt.md` | `copilot-ba-mission-plan.prompt.md` |
| `.cursor/commands/ba-mission-plan.md` | `cursor-ba-mission-plan.md` |
| `docs/missions/TEMPLATE.md` | `mission-template.md` |
| `missions/.gitkeep` | `gitkeep.txt` |

`tickets-gitkeep.txt` is renamed `gitkeep.txt` and both entries point at it — an internal resource name with no user-visible effect. Nothing is added to hub or child scaffolds.

### 8.2 CI gate — extend, do not rename

`kb-ticket-lint.yml` grows to cover both directories:

- `paths: ["tickets/**.md", "missions/**.md"]`
- For each changed file, dispatch by directory: `tickets/` → `kb ticket lint`, `missions/` → `kb mission lint`. Any FAIL fails the job.

**The workflow filename and job name stay exactly as they are**, even though `kb-ticket-lint` now under-describes what it does. Branch protection on already-provisioned BA repos keys on the job name; renaming it would leave those repos waiting forever on a required check that never runs again. That operational hazard outweighs the naming accuracy.

Full checkout gives CI both `tickets/` and `missions/`, so check 12 and ticket check 10 run at full strength there — CI is the strongest of the three lint contexts.

## 9. Decision — no `kb_mission_lint` MCP tool

The symmetric move would be a sixth MCP tool mirroring `kb_ticket_lint`. It is deliberately **not** built:

- Mission lint's distinguishing value over ticket lint is precisely the traceability checks (12, and ticket-side 10), and those need filesystem access the shared MCP server does not have. An MCP `kb_mission_lint` would be a strictly degraded copy of the CLI.
- Phase 4 spec §12 already decided every BA works inside the requirements repo — the chat-only persona that would need a shell-free lint was dropped. Nothing is left to serve.
- Every registered tool costs context in every connected agent, and dilutes the "core four unchanged" invariant.

Accepted cost: having `kb_ticket_lint` without `kb_mission_lint` is asymmetric and looks odd on the tool list. Recorded here so the reason survives. The decision is reversible at no cost — adding a tool later is purely additive.

Consequence to handle regardless: the `ba-mission-plan` skill has no MCP fallback for its lint step, which is why "`kb` failing to run is not a PASS" is an explicit hard rule (§6).

## 10. Testing (hermetic — no live hub, no LLM; `git_kb` fixture)

- `tests/test_missionlint.py` — a golden PASS mission; one mutation per check 1–13 asserting exact level and message fragment; a Vietnamese-body golden mission (UTF-8 + `§`); `--json` shape; **both `C4Container` and `flowchart` fences PASS** checks 3–5; `tickets_dir=None` skips check 12 **and emits the note**.
- `tests/test_ticketlint.py` — new check 10: valid parent mission / missing mission file / US id absent from backlog / no repo path → note. Plus an assertion that `REQUIRED_HEADINGS` is unchanged, guarding the breaking-change contract.
- **`lintcore` extraction: the entire existing `tests/test_ticketlint.py` suite must pass unchanged, before and after.** This is the acceptance condition for the refactor, not a new test.
- `tests/test_cli_mission.py` — exit codes, stdin (`-`), `--json`.
- MCP tests — assert exactly **5 tools** and no `kb_mission_lint`; core-four signature snapshot unchanged.
- `tests/test_init.py` — kind `ba` scaffolds exactly the §8.1 additions; hub/child gain nothing (assert absence); workflow contains both path filters and no hardcoded secrets.
- Template-sync test — `REQUIRED_MISSION_HEADINGS` ⊆ `mission-template.md`; all four wrappers reference the same heading set. Same shape as the existing ticket sync test.

Error handling: an unparseable backlog table reports the offending row rather than swallowing it; a missing `missions/<id>.md` under ticket check 10 is an error, not a crash; hub unreachability inherits `kb doctor --context` behaviour verbatim; UTF-8 throughout via `utf8io`.

## 11. Compatibility and rollout

No migration step is required:

- `ticket.REQUIRED_HEADINGS` unchanged → every existing ticket still lints PASS.
- `> Parent mission:` is optional → provisioned BA repos keep working untouched.
- No MCP tool added or removed → connected clients see no change.
- Version bump: **minor** (0.13.0). Phase 4 spec §3.6 classifies only a `REQUIRED_HEADINGS` change as breaking; this is additive.

Operational note for already-provisioned BA repos: re-running `kb init --kind ba` picks up the new templates. Per `initcmd.py:193–204`, any file **not** in `PROTECTED_FILES` is overwritten when its content differs — so `kb-ticket-lint.yml` and the four `ba-ticket-author` wrappers are refreshed, which is the intent, **but a team that hand-edited a wrapper loses those edits**. This is pre-existing init behaviour, not something introduced here; QUICKSTART-BA must state it in one line.

## 12. Docs

- QUICKSTART-BA: the mission flow, and guidance on when a mission is warranted (large feature spanning multiple stories) versus writing a standalone ticket (small work). Plus the re-init overwrite warning from §11.
- README: extend the Phase 4 section with the mission plan, the new command, and the mission→ticket relationship.
- Architecture document: separate task after implementation — `kb ticket lint` is no longer the only DoR gate; MCP tool count stays 5.

## 13. Decisions log

| Decision | Choice |
|---|---|
| Mission↔ticket relationship | Mission produces a US backlog; tickets point back at it (2026-07-28). Rejected: mission as an isolated artifact with no enforced link; mission as an extra section inside a large ticket (breaks one-ticket-one-story) |
| C4 depth | L1 + L2 required; L3 optional and hand-supplied; L4 out of scope. Guessing L3/L4 would violate the skill's own never-fabricate rule |
| Skill packaging | Separate skill `ba-mission-plan` with its own four wrappers. The command name *is* the mode selector — clearer than branching inside one long orchestrator, and the two flows have different heading contracts |
| Where traceability is enforced | Downstream, at ticket lint, where both artifacts exist. Enforcing it at mission lint would fail every freshly written mission and invert the authoring order |
| Backlog status tracking | No status column; coverage derived from the filesystem so it cannot rot |
| US identity | Repo-local ids (`M-<slug>-US<n>`). Jira keys cannot serve — Jira assigns them only after the BA pastes the ticket, long after the mission is written |
| Mermaid C4 syntax | Lint accepts C4-native **or** `flowchart`; template ships C4-native. Mermaid documents C4 as experimental with syntax subject to change; a DoR gate must not be hostage to that |
| Ticket back-link mechanism | Optional blockquote under the H1, not a new required heading — keeps `REQUIRED_HEADINGS` and therefore every existing ticket intact |
| Lint engine placement | Extract `lintcore.py`; add `missionlint.py`. Rejected: importing `ticketlint`'s private helpers (silent coupling), and one module with a `kind` parameter (one file carrying two heading contracts) |
| MCP tool | None added — see §9. Count stays at 5 |
| CI gate | Extend `kb-ticket-lint.yml` to both directories; filename and job name frozen to protect existing branch protection rules |
| Skipped checks | Always reported as notes. A check that could not run must never read as a check that passed |
