---
mode: agent
description: Draft a Dev-ready ticket grounded in the KB — Intake → Ground → Draft → Pin → Lint → Review, saved to tickets/<id>.md
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
2. **Ground** — use the MCP tool `kb_search` when it is available;
   otherwise fall back to `kb query "<text>" --tags <tags>` (CLI). Present
   **ALL** returned candidates with their citations — never drop one
   silently. When the ambiguity note fires (two close-scoring hits), the
   BA MUST choose — never auto-pick.
3. **Draft** — fill the standard ticket template (Summary, User Story,
   Background / Business context, Acceptance Criteria, Use cases,
   Sequence diagram, Business flow, KB context, Definition of Ready).
   Every claim that touches a standard cites `doc-id §section`, only from
   candidates the BA confirmed in step 2. Code-level detail the KB and
   the BA cannot supply (service names, DB tables, …) →
   `%%TODO: verify against codebase%%` — never invented.
4. **Pin** — after the BA confirms which sections apply, call the MCP
   tool `kb_context_new` when available; otherwise fall back to
   `kb context new --refs "<refs>" --tags "<tags>"` (CLI), passing exactly
   the confirmed refs. Embed the returned block verbatim under
   `## KB context`.
5. **Lint** — run `kb ticket lint <file>` (CLI, primary), or the MCP tool
   `kb_ticket_lint` as a fallback. Fix every error and re-run until it
   reports `DoR: PASS`. Report any remaining warnings to the BA.
6. **Review → save** — write the final Markdown to
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
- The agent's output is a draft; the BA publishes it. Never push to Jira.
- Lint must report `DoR: PASS` before handover; report remaining
  warnings to the BA — do not hand over a failing ticket silently.
- English template headings are never localized; write the ticket body
  in the BA's working language.
