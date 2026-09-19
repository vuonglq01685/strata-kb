---
mode: agent
description: Draft a Dev-ready ticket grounded in the KB — Intake → Parent mission → Ground → Draft → Pin → Lint → Maturity review → Review, saved to tickets/<id>.md
---

# /ba-ticket-author — draft a grounded, Dev-ready ticket

Turn a business need into a Dev-ready ticket: Story, Background,
Acceptance Criteria, Use cases, Mermaid diagrams, and a pinned KB
citation block — saved to `tickets/<ticket-id>.md`. The output is a
**draft**: the BA reviews it, commits it, and pastes it into Jira.

## Workflow

1. **Intake** — collect the business need: capability, role, value. Ask
   for target tags (e.g. `#arinc424 #airspace`) or an explicit doc-id if
   the BA already has one. Ask, don't guess.
2. **Parent mission (optional)** — if the BA names a parent mission, read
   `missions/<mission-id>.md`: take the story title from its US backlog
   row, and put `> Parent mission: <mission-id>` on its own line directly
   under the ticket's H1 title. Save the ticket as
   `tickets/<mission-id>-US<n>.md` so the back-link check can find it.
   Use the mission's pinned refs as STARTING CANDIDATES ONLY — do not copy
   its `kb-context` into the ticket. A mission is broad and a ticket is
   narrow; a wholesale copy drags in refs the ticket never cites. Confirm
   and pin the ticket's own refs fresh in step 5.
3. **Ground** — use the MCP tool `kb_search` when it is available;
   otherwise fall back to `kb query "<text>" --tags <tags>` (CLI).
   **Budget the search:** 500–800 tokens for broad discovery — enough
   for the citation plus a summary to choose from; `kb_get_section`
   only for a section already chosen; L3 only for a value that will be
   encoded in code or a test. Present
   **ALL** returned candidates with their citations — never drop one
   silently. When the ambiguity note fires (two close-scoring hits), the
   BA MUST choose — never auto-pick.
   Search results tagged `code` come from `<repo>-code` and `<repo>-svc`
   — present them alongside domain candidates: a `-code` section is
   machine-extracted (trust it for names) while a `-svc` section is
   human-reviewed (trust it for responsibility). A known extractor
   limit: a service built from source often renders `Technology | none`
   in `-code` — the extractor looks for a dependency manifest in a
   directory named after the compose service, and otherwise falls back
   to the image name — so a `-code` hit for a service's name does not
   guarantee it also answers for `technology`; when it reads `none`,
   the existing `%%TODO: verify against codebase%%` rule applies to
   that one argument, not the whole container.
4. **Draft** — fill the standard ticket template (Summary, User Story,
   Background / Business context, Acceptance Criteria, Use cases,
   Sequence diagram, Business flow, Dependencies, Non-functional
   requirements, UI / presentation spec, Out of scope, Test data &
   verification, Open questions, KB context, Definition of Ready).

   **AC quality bar** — every AC must be verifiable by someone who has
   NOT read the KB. Banned weasel words per `docs/ac-quality.md`
   ("appropriate", "configured", "a subset", "responsive", …). When a
   value is not settled, write `OPEN(<owner>)` inside the AC AND add a
   row to `## Open questions` — never write vague and move on.

   **Fill every new section** — `## Dependencies`, `## Non-functional
   requirements`, `## UI / presentation spec`, `## Out of scope`,
   `## Test data & verification`, `## Open questions`. Not applicable →
   write `N/A — <reason>`; a blank section reads as "not considered".

   Every claim that touches a standard cites `[doc-id §section]`, only from
   candidates the BA confirmed in step 3. Code-level detail the KB and
   the BA cannot supply (service names, DB tables, …) →
   `%%TODO: verify against codebase%%` — never invented.
5. **Pin** — after the BA confirms which sections apply, call the MCP
   tool `kb_context_new` when available; otherwise fall back to
   `kb context new --refs "<refs>"` (CLI), passing exactly the confirmed
   refs. Embed the returned block verbatim under `## KB context`.
   **Tags are NOT yours to set:** the engine derives them from the
   pinned sections' own tags. Leave the tool's `tags` argument unset and
   the CLI's `--tags` off — a tag passed by hand is validated against the
   hub vocabulary and an unknown one is an error. The tags the BA gave at
   Intake are search keywords for `kb query --tags`, nothing more.
6. **Lint** — run `kb ticket lint <file>` (CLI, primary), or the MCP tool
   `kb_ticket_lint` as a fallback. Fix every error and re-run until it
   reports `DoR: PASS`. Report any remaining warnings to the BA.
7. **Maturity review** — once lint reports `DoR: PASS`, read
   `docs/review-rubric.md`, then `docs/review-rubric.local.md` if it
   exists — the local file overrides the base one (same for
   `docs/ac-quality.md` and `docs/ac-quality.local.md`). Run TWO
   sequential review passes yourself, one role per pass — never blend
   the perspectives:
   - Pass 1, *Business-coverage reviewer* — act as PO/stakeholder;
     score the "Business coverage" axis of the rubric.
   - Pass 2, *Dev-implementability reviewer* — act as the dev who picks
     the ticket up next sprint; score the "Dev implementability" axis.
   Each pass produces: a 1–5 score (the LOWEST maturity level fully
   satisfied — never averaged), the checklist with pass/fail per item,
   and a gap list where every gap names the section it lives in and a
   proposed fix.

   Apply the fixes, re-run `kb ticket lint`, then review again — at most
   3 rounds total; stop early when both axes score ≥ 4.

   **Rounds 2 and 3 are not a re-read.** Run this pass yourself,
   acting as `gap-verifier`, reading only three things: the gaps
   still open, the current text of the sections that changed in
   response, and the rubric items those gaps map to. It returns
   pass/fail per gap with a one-line reason. Do **not** re-read the
   rest of the draft and do **not** re-score an axis in this pass: an
   axis's score rises only when every gap of that axis passes —
   re-derive it as the LOWEST maturity level fully satisfied, using
   round 1's checklist updated with the verifier's pass/fail;
   otherwise carry the previous round's score forward unchanged.

   A gap you cannot close yourself (a missing business decision,
   missing input) is NEVER invented: write `OPEN(<owner>)` at the spot
   and add an `## Open questions` row.

   Record the result in `## Review record`: on the first round replace
   the `Not yet reviewed.` placeholder; append one table row per round
   (`| Date | Round | Business | Dev | Reviewer |`) — the `Reviewer`
   cell reads `gap-verifier` for rounds 2 and 3 — and list the
   still-open gaps on the `Open gaps:` line. Report both scores and the
   remaining owned gaps to the BA in the
   handover summary, together with the output of `kb usage report
   --ticket <ticket-id> --md` — the authoring cost of this ticket in
   this repo. Say so in the same breath: the Dev repo's ledger holds
   the implementation half, and the two are joined by the shared
   ticket id. When the command answers `no usage recorded yet`, report
   that instead of guessing a number.
8. **Review → save** — write the final Markdown to
   `tickets/<ticket-id>.md`; the BA reviews it, commits it, and pastes it
   into Jira.

## Hard rules

- Citations are mandatory for every claim that touches a standard — no
  citation, no claim.
- Present ALL `kb_search` candidates and let the BA choose; mandatory
  when the ambiguity note fires — never auto-pick.
- Never fabricate codes, record/field names, or numeric values — the
  same verbatim-preservation rules as `kb-summarize` apply.
- Unverifiable code-level details become `%%TODO: verify against
  codebase%%` placeholders — never invented.
- **Ground code detail in the hub's code knowledge before reaching for
  a placeholder.** Two documents per product repo answer different
  questions:
  - `<repo>-code` **for names** — service/container names (`svc.*`),
    table names (`db.*`), endpoints (`api.*`), and detected
    technology.
  - `<repo>-svc` **for meaning** — what a container is responsible for
    (`svc.*`), and which services a business flow crosses (`flow.*`).

  Together they fill all four arguments of
  `Container(alias, label, technology, description)`: alias, label
  and technology from `-code`, description from `-svc`. Use `-svc`
  the same way for `Rel(...)` labels instead of leaving them empty.

  Write `%%TODO: verify against codebase%%` only when
  **neither document answers** — and then the existing rule stands:
  an owned `## Open questions` row.

  `-svc` responsibility text grounds a diagram — but it
  **never substitutes for a domain citation** in an Acceptance
  Criterion: standard values still come verbatim from a pinned
  domain section.
- The agent's output is a draft; the BA publishes it. Never push to Jira.
- Lint must report `DoR: PASS` before handover; report remaining
  warnings to the BA — do not hand over a failing ticket silently.
- Never tick a Definition of Ready checkbox yourself — only the BA
  confirms DoR items. Fixing a lint error is not the same as confirming
  DoR; leave every `## Definition of Ready` checkbox unchecked for the
  BA.
- English template headings are never localized; write the ticket body
  in the BA's working language.
- Report to the BA the count of ACs without citations, with reasons.
  Purely technical ACs (idempotency, rerunnability, internal error
  handling) need no citation — but say so explicitly.
- When KB body text contradicts the document's own canonical index
  table (ingest error, typo, identifier drift), use the index version,
  keep the citation slug unchanged, and report the discrepancy to the
  BA. Never silently propagate a source error.
- A ticket that touches UI without design input carries
  `OPEN(<owner>)` in `## UI / presentation spec` — it is not ready
  otherwise.
- Every `%%TODO: verify against codebase%%` and every `OPEN(...)` in
  the ticket has a matching `## Open questions` row with an owner.
- A ticket describing behavior under load, bulk processing, or timing
  constraints carries at least one quantified row in
  `## Non-functional requirements`.
- The maturity review never edits business intent on its own authority —
  it closes gaps with facts already confirmed by the BA or the KB, and
  everything else becomes an owned `OPEN(...)`. Scores below 4 after
  3 rounds are reported, not hidden.
