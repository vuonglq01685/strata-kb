# BA Template & Skill Upgrade — Design

Date: 2026-08-12
Status: approved by BA (brainstorming session)
Source requirements: `KB-BA/docs/ba-template-skill-upgrade.md` (user-authored, domain-agnostic)

## Goal

Make BA missions/tickets Dev-ready by construction: verifiable ACs, owned
placeholders, NFR / UI / sequencing sections, and self-contradiction handling
for KB sources. All changes land at the scaffold source in this repo
(center-kb), so every BA repo gets them via `kb init --kind ba`.

## Governing principles (from requirements doc)

- NT1 — the template determines the output, not the author: fix templates
  first, skills second.
- NT2 — an AC that cannot be acceptance-tested does not exist: ban weasel
  words, replace with `OPEN(<owner>)`.
- NT3 — "unknown" is valid; "unknown without an owner" is not: every
  placeholder generates an owned open-question row.
- NT4 — a document must state *what*, *with what*, and *what it looks like*:
  add NFR / technology / UI sections.
- NT5 — self-contradicting sources are reported, not propagated: prefer the
  document's canonical index table, keep the citation slug, flag to the BA.

## Verified constraints

- `kb mission lint` matches the `## US backlog` header row `| US ID | Title |`
  verbatim — extra columns FAIL. Dependency/size live in a separate
  `## Sequencing` section.
- Adding new `##` sections to either template keeps `DoR: PASS`.

## Decisions made

| Decision | Choice |
|---|---|
| Where to edit | center-kb source (`src/center_kb/templates/init/`), not the KB-BA workspace copies |
| Lint enforcement | New checks as **warnings** (never errors); DoR still PASS; BA judges |
| Guidance language | English (consistent with existing templates; headings never localized) |
| Banned-word list location | New scaffolded doc `docs/ac-quality.md` (source: `templates/init/ac-quality.md`); templates and skills point to it; list is bilingual VI+EN because it is a *detection* list |
| Mission section name | `## Technology decisions` (per requirements §4.1) |

## File map (all under `src/center_kb/` unless noted)

| Change | Files |
|---|---|
| Ticket template | `templates/init/ticket-template.md` |
| Mission template | `templates/init/mission-template.md` |
| AC quality doc (new) | `templates/init/ac-quality.md` + `BA_TEMPLATES` entry in `initcmd.py` → scaffolds to `docs/ac-quality.md` |
| Ticket skill + mirrors | `templates/init/claude-skill-ba-ticket-author.md`, `cursor-ba-ticket-author.md`, `copilot-ba-ticket-author.prompt.md` (claude-command variant is a thin pointer — untouched) |
| Mission skill + mirrors | `templates/init/claude-skill-ba-mission-plan.md`, `cursor-ba-mission-plan.md`, `copilot-ba-mission-plan.prompt.md`, `claude-command-ba-mission-plan.md` (full copy — kept in sync) |
| Lint warnings | `ticketlint.py`, `missionlint.py` + tests |

## Ticket template changes

Six new sections inserted before `## KB context`, in this order:

1. `## Dependencies` — `Blocked by:` / `Blocks:` lines; "None" when empty —
   a blank section reads as "not considered".
2. `## Non-functional requirements` — table
   `| Concern | Target | How to measure | Source |`; every row needs a number
   or threshold, or `OPEN(<owner>)`; pure data/backoffice tickets write
   `N/A — <reason>`. No "fast", "stable", "handles load".
3. `## UI / presentation spec` — layout, labels, empty state, error state,
   visual-distinction rules (must say *by what means* — label, color, shape,
   grouping), display order, or mockup link. No design input →
   `OPEN(<owner>)`; no UI → `N/A`.
4. `## Out of scope` — this ticket's own boundary (distinct from the
   mission's); list the things easily mistaken as in-scope.
5. `## Test data & verification` — sample records + expected values,
   tolerances for numeric checks, how to verify each hard-to-test AC; no
   sample data yet → `OPEN(<owner>)`.
6. `## Open questions` —
   `- [ ] Q1 — <question> — owner: <who> — blocks: <AC# or section>`;
   every `OPEN(...)` and every `%%TODO%%` in the ticket must have a row here.

AC section guidance (HTML comment, English): one observable outcome per AC
with concrete values; no weasel words (see `docs/ac-quality.md`); an
unsettled value is written `OPEN(<owner>)` in the AC **and** gets an Open
questions row — never left vague.

Definition of Ready gains:

- Every AC is acceptance-testable; no weasel words remain
- Dependencies, NFR, UI spec, Out of scope, Test data filled or `N/A` with reason
- Every open question has an owner

## Mission template changes

- `## Technology decisions` (after `## Containers (C4 L2)`) — table
  `| # | Decision | Status | Owner | Blocks |` with status OPEN/DECIDED;
  every `%%TODO: verify against codebase%%` in the C4 sections has exactly
  one row; a placeholder without an owner means not ready, even if lint
  passes.
- `## Non-functional requirements` — same table format as tickets; at least
  one quantified NFR is mandatory when the mission touches large data
  volumes, concurrency, or real-time constraints; unsettled →
  `OPEN(<owner>)`, never blank.
- `## Sequencing` (immediately after `## US backlog`) — table
  `| US ID | Depends on | Size | Notes |`. Separate section because the
  backlog header is matched verbatim by lint.
- `## Open questions` split out of `## Constraints & assumptions` —
  `- [ ] Q1 — <question> — owner: <who> — impact: <architecture / scope / cost> — blocks: <US id>`;
  architecture-changing questions must be closed before foundational
  stories start. (Rationale: buried in Constraints, nobody sees the blocker.)
- Definition of Ready gains: every `%%TODO%%` has an owned Technology
  decisions row; Sequencing covers the whole backlog; architecture-impacting
  open questions closed.

## `ac-quality.md` (new scaffolded doc)

Bilingual (VI + EN) banned-word table per requirements §6:
configured/đã cấu hình; appropriate/reasonable/phù hợp/hợp lý; a subset/một
tập con/một số trường; responsive/phản hồi tốt/không bị chậm; handled
correctly/xử lý đúng; where applicable/nếu cần; full support for/hỗ trợ đầy
đủ; "distinguished by type" without the means/phân biệt theo loại — each with
its replacement rule. Exception clause: a banned phrase is allowed only when
immediately followed by `OPEN(<owner>)` plus an `## Open questions` row.

## Skill changes

### `ba-ticket-author` (+ cursor/copilot mirrors)

Workflow step 4 (Draft) additions:

- **AC quality bar** — each AC verifiable by someone who has not read the
  KB; banned words per `docs/ac-quality.md`; missing value →
  `OPEN(<owner>)` in the AC + an Open questions row; never vague-and-move-on.
- **Fill all new sections** — Dependencies, NFR, UI spec, Out of scope,
  Test data & verification, Open questions; not applicable → `N/A` with
  reason; blank means "not considered".

Hard rules additions:

- Report to the BA the count of ACs without citations and why (purely
  technical ACs — idempotency, rerunnability, internal error handling —
  need no citation, but must be called out).
- When KB body text contradicts the document's own canonical index table
  (ingest error, typo, identifier drift), use the index version, keep the
  citation slug unchanged, and report the discrepancy to the BA. Never
  silently propagate a source error. (NT5)
- A ticket touching UI without design input must carry
  `OPEN(<owner>)` in `## UI / presentation spec` — not ready otherwise.
- Every `%%TODO: verify against codebase%%` and every `OPEN(...)` in the
  ticket has a matching `## Open questions` row with an owner.
- A ticket describing behavior under load, bulk processing, or timing
  constraints must have at least one quantified NFR row.

### `ba-mission-plan` (+ cursor/copilot/claude-command mirrors)

Workflow step 4 (Split) addition — story-size heuristic; a story must be
split further if it hits any of:

- more than 8 coded-value variants each needing its own algorithm or
  business rule
- touches more than 6 source entities (tables, APIs, documents)
- mixes data construction/transformation with presentation for a complex
  domain
- contains both the happy path and multiple heavy exception branches

When a threshold is hit, present the BA the split alternative with
reasoning — not just a single title row.

Hard rules additions (per requirements §7.2):

- every C4 `%%TODO%%` generates an owned `## Technology decisions` row;
  placeholders without owners = not ready even if lint passes
- quantified NFR mandatory for large-data / concurrent / time-constrained
  missions
- `## Sequencing` must be filled once the BA confirms the backlog — Devs
  never infer ordering
- architecture-changing open questions are flagged and are prerequisites
  for foundational stories
- never alter the `| US ID | Title |` backlog header in any way — lint
  matches it verbatim; extra columns FAIL

## Lint changes (warnings only — never errors, existing checks untouched)

| File | New warnings |
|---|---|
| `ticketlint.py` | banned word in the AC section without `OPEN(` on the same line; orphan `OPEN(`/`%%TODO%%` (no matching `## Open questions` row); new section missing or empty |
| `missionlint.py` | C4 `%%TODO%%` without a `## Technology decisions` row; `## Sequencing` missing or not covering every backlog US id; open-question row without an owner |

Banned-word matching: case-insensitive, bilingual VI+EN, scanned only inside
`## Acceptance Criteria`; `OPEN(` on the same line suppresses the warning.
Legacy docs without the new sections get warnings only — `DoR: PASS` is
preserved; nothing breaks.

## Verification

- TDD for every new lint check; full test suite green.
- `kb init --kind ba` into a temp dir → filled sample template lints PASS.
- Lint the existing KB-BA mission + 14 tickets (copies): only new warnings
  appear, no new FAIL.

## Out of scope

- Syncing the KB-BA workspace (`kb init` re-run happens there afterwards).
- Re-drafting the weakest existing ticket with the new template
  (requirements §9 step 6) — done in KB-BA after sync.
- Turning the new lint warnings into errors.

## Untouched (requirements §8)

Citation + version-pinning mechanism; "agent never ticks DoR" rule;
verbatim-preservation rule (only the NT5 self-contradiction branch is
added); "agent drafts, BA publishes" boundary; the original 9 ticket
sections; the `| US ID | Title |` header.
