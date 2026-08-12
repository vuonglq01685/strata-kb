---
name: ba-ticket-author
description: Draft a Dev-ready ticket (story, ACs, use cases, Mermaid diagrams) grounded in the KB with pinned citations. Use when a BA asks to write a user story / requirement / ticket, or invokes /ba-ticket-author.
---

# ba-ticket-author — draft a grounded, Dev-ready ticket

You are the ORCHESTRATOR of the ticket-authoring pipeline: Intake →
Parent mission → Ground → Draft → Pin → Lint → Review. The ticket you
write is a **draft** — the BA reviews it, commits it, and pastes it into
Jira; you never publish it yourself.

An optional argument gives the business need directly; no argument = ask
for it during Intake.

## Workflow

1. **Intake** — collect the business need: what capability, for which
   role, and why it matters. Ask for target tags (e.g. `#arinc424
   #airspace`) or an explicit doc-id if the BA already has one. Ask,
   don't guess — a vague need gets a clarifying question, not a search.
2. **Parent mission (optional)** — if the BA names a parent mission, read
   `missions/<mission-id>.md`: take the story title from its US backlog
   row, and put `> Parent mission: <mission-id>` on its own line directly
   under the ticket's H1 title. Save the ticket as
   `tickets/<mission-id>-US<n>.md` so the back-link check can find it.
   Use the mission's pinned refs as STARTING CANDIDATES ONLY — do not copy
   its `kb-context` into the ticket. A mission is broad and a ticket is
   narrow; a wholesale copy drags in refs the ticket never cites. Confirm
   and pin the ticket's own refs fresh in step 5.
3. **Ground** — call the MCP tool `kb_search` within the token budget
   when it is available; otherwise fall back to `kb query "<text>"
   --tags <tags>` (CLI). Present **ALL** returned candidates to the BA
   with their citations — never silently drop one. When the ambiguity
   note fires (two close-scoring hits), the BA MUST choose between
   them — never auto-pick.
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

   Every claim that touches an industry standard cites `doc-id
   §section` — and only from the candidates the BA confirmed in step 3,
   never a fresh, unconfirmed search hit. Where a diagram needs
   code-level detail (service names, DB tables, …) that neither the KB
   nor the BA can supply, mark it `%%TODO: verify against codebase%%` —
   never invent it.
5. **Pin** — once the BA confirms which sections actually apply, call
   the MCP tool `kb_context_new` when available; otherwise fall back to
   `kb context new --refs "<refs>" --tags "<tags>"` (CLI), passing
   exactly those confirmed refs (+ tags). Embed the block it returns
   verbatim under `## KB context`.
6. **Lint** — run `kb ticket lint <file>` (CLI, primary) against the
   draft; fall back to the MCP tool `kb_ticket_lint` when the CLI is not
   available in this environment. Fix every error and re-run until it
   reports `DoR: PASS`. Report any remaining warnings to the BA — they
   are not blockers, but they are the BA's judgment call.
7. **Review → save** — write the final Markdown to
   `tickets/<ticket-id>.md`. Hand it to the BA to review and commit;
   the BA — not you — pastes it into Jira.

## Hard rules

- Citations are mandatory for every claim that touches a standard — no
  citation, no claim.
- Present ALL `kb_search` candidates and let the BA choose; this is
  mandatory when the ambiguity note fires — never auto-pick.
- Never fabricate codes, record/field names, or numeric values — the
  same verbatim-preservation rules as `kb-summarize` apply.
- Unverifiable code-level details become `%%TODO: verify against
  codebase%%` placeholders — never invented.
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
