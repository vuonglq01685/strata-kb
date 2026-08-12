---
description: Draft an epic-level Mission Plan (C4 L1/L2 diagrams, scope, US backlog) grounded in the KB with pinned citations, via the ba-mission-plan skill
argument-hint: "[business need]"
---

# /ba-mission-plan — draft a grounded, epic-level mission plan

Invoke the `ba-mission-plan` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the business need when given; when
empty, ask for it during Intake. Use a mission for a large feature that
spans several User Stories — small work goes straight to
`/ba-ticket-author`; a mission is not mandatory.

## Workflow

1. **Intake** — collect the business need at epic level: what capability,
   for whom, why it matters, and how success is measured. Agree the
   mission id with the BA: `M-<slug>`, where `<slug>` is lowercase
   kebab-case. The filename stem must equal the id. Ask for target tags
   (e.g. `#arinc424 #airspace`) or an explicit doc-id. Ask, don't guess.
2. **Ground** — use the MCP tool `kb_search`, within the token budget,
   when it is available; otherwise fall back to `kb query "<text>"
   --tags <tags>` (CLI). Present **ALL** returned candidates with their
   citations — never silently drop one. When the ambiguity note fires
   (two close-scoring hits), the BA MUST choose — never auto-pick.
3. **Draft** — start from `docs/missions/TEMPLATE.md` in the repo (the
   file `kb init --kind ba` scaffolds) and fill it in: Summary,
   Business goal, Scope, System context (C4 L1), Containers (C4 L2),
   Technology decisions, Non-functional requirements,
   Constraints & assumptions, US backlog, Sequencing, Open questions,
   KB context, Definition of Ready. Every
   `%%TODO: verify against codebase%%` you place in a C4 diagram gets
   one owned row in `## Technology decisions` at the same moment —
   never leave a placeholder without an owner.
   Keep the template's `> Mission: M-<slug>` id line and mermaid fences —
   do not recreate the document from scratch. Draw L1 and L2 from KB
   content plus what the BA states. Where a diagram needs code-level detail
   (service names, DB tables, …) that neither the KB nor the BA can supply,
   mark it `%%TODO: verify against codebase%%` — never invent it. Add the
   optional `## Components (C4 L3)` section ONLY when the BA supplies real
   component detail.
4. **Split** — propose the US backlog table with the header
   `| US ID | Title |` exactly (the lint parser matches this string, not
   a paraphrase) and one row per story below it, ids numbered
   `<mission-id>-US1`, `-US2`, … — numbers start at 1 and are never
   zero-padded (`-US01` fails lint's id pattern). The BA edits and
   confirms the split. Numbering gaps are fine if a story is dropped —
   never renumber, as ticket filenames may already use those ids. Each
   story's eventual ticket is saved as `tickets/<us-id>.md` (e.g.
   `tickets/<mission-id>-US1.md`) — that exact filename is what the
   coverage check (and `kb ticket lint`'s back-link check) looks for; a
   differently-named file will never show as drafted.

   **Story-size heuristic** — a story must be split further if it hits
   ANY of these:
   - more than 8 coded-value variants where each needs its own
     algorithm or business rule
   - touches more than 6 source entities (tables, APIs, documents)
   - mixes data construction/transformation with presentation for a
     complex domain
   - contains both the happy path and multiple heavy exception branches

   When a threshold is hit, present the BA the split alternative with
   the reasoning — never just a single title row. After the BA confirms
   the backlog, fill `## Sequencing` (US ID / Depends on / Size /
   Notes) — Devs never infer ordering.
5. **Pin** — once the BA confirms which sections actually apply, call the
   MCP tool `kb_context_new` when available; otherwise fall back to
   `kb context new --refs "<refs>" --tags "<tags>"` (CLI), passing exactly
   those confirmed refs (+ tags). Embed the block it returns verbatim
   under `## KB context`.
6. **Lint** — run `kb mission lint <file>` against the draft. Fix every
   error and re-run until it reports `DoR: PASS`. A coverage warning of
   `0/N US drafted` is EXPECTED at creation time — the tickets do not
   exist yet. Report remaining warnings to the BA; they are the BA's
   judgment call.
7. **Maturity review** — once lint reports `DoR: PASS`, run TWO
   sequential review passes yourself against `docs/review-rubric.md`,
   one role per pass — never blend the perspectives:
   - Pass 1, *Business-coverage reviewer* — act as PO/stakeholder;
     score the "Business coverage" axis of the rubric.
   - Pass 2, *Dev-implementability reviewer* — act as the tech lead who
     will slice this mission into tickets; score the "Dev
     implementability" axis.
   Each pass produces: a 1–5 score (the LOWEST maturity level fully
   satisfied — never averaged), the checklist with pass/fail per item,
   and a gap list where every gap names the section it lives in and a
   proposed fix.

   Apply the fixes, re-run `kb mission lint`, and review again — at
   most 3 rounds total; stop early when both axes score ≥ 4. A gap you
   cannot close yourself (a missing business decision, missing input)
   is NEVER invented: write `OPEN(<owner>)` at the spot and add an
   `## Open questions` row.

   Record the result in `## Review record`: on the first round replace
   the `Not yet reviewed.` placeholder; append one table row per round
   (`| Date | Round | Business | Dev | Reviewer |`) and list the
   still-open gaps on the `Open gaps:` line. Report both scores and the
   remaining owned gaps to the BA in the handover summary.
8. **Review → save** — write the final Markdown to
   `missions/<mission-id>.md`. Hand it to the BA to review and commit.

## Hard rules

- Citations are mandatory for every claim that touches a standard — no
  citation, no claim.
- Present ALL `kb_search` candidates and let the BA choose; this is
  mandatory when the ambiguity note fires — never auto-pick.
- Never fabricate codes, record/field names, numeric values, service
  names, or table names — the same verbatim-preservation rules as
  `kb-summarize` apply. Unsure → `%%TODO: verify against codebase%%`.
- **`kb mission lint` failing to RUN is not a PASS.** There is no MCP
  fallback for this gate. If the `kb` command is unavailable, tell the BA
  to install `center-kb` — never skip the lint step, and never hand over a
  mission you could not lint.
- Lint must report `DoR: PASS` before handover; report remaining warnings
  to the BA — do not hand over a failing mission silently.
- **Never auto-generate ticket files from the backlog.** Each story goes
  through `/ba-ticket-author` with its own grounding pass — a backlog row
  is a title, not a drafted ticket.
- Never tick a Definition of Ready checkbox yourself — only the BA
  confirms DoR items.
- The agent's output is a draft; the BA publishes it. Never push to Jira.
- English template headings are never localized; write the mission body in
  the BA's working language.
- Every C4 `%%TODO: verify against codebase%%` generates one owned row
  in `## Technology decisions`. A mission with an ownerless placeholder
  is not ready, even when lint passes.
- A mission touching large data volumes, concurrency, or timing
  constraints carries at least one quantified row in
  `## Non-functional requirements`.
- Fill `## Sequencing` once the BA confirms the backlog — Devs never
  infer execution order.
- An open question that changes architecture (infrastructure,
  deployment scope, data model) is flagged in `## Open questions` as a
  prerequisite of the foundational stories and closed before they
  start.
- Never alter the `| US ID | Title |` backlog header in any way — lint
  matches the string verbatim; extra columns FAIL. Dependency and size
  live in `## Sequencing`.
- The maturity review never edits business intent on its own authority —
  it closes gaps with facts already confirmed by the BA or the KB, and
  everything else becomes an owned `OPEN(...)`. Scores below 4 after
  3 rounds are reported, not hidden.
