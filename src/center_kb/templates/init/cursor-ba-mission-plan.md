---
name: ba-mission-plan
description: Draft an epic-level Mission Plan grounded in the KB — Intake → Ground → Draft → Split → Pin → Lint → Review, saved to missions/M-<slug>.md
---

# /ba-mission-plan — draft a grounded, epic-level mission plan

Turn a large, multi-story business need into an epic-level Mission Plan:
Summary, Business goal, Scope, System context (C4 L1), Containers (C4 L2),
Constraints & assumptions, US backlog, KB context, and Definition of Ready
— saved to `missions/M-<slug>.md`. The output is a **draft**: the BA
reviews and commits it. It sits UPSTREAM of `ba-ticket-author`: each
backlog story is drafted later, one at a time, by that skill. Use a
mission for a large feature that spans several User Stories — small work
goes straight to `/ba-ticket-author`; a mission is not mandatory.

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
   Constraints & assumptions, US backlog, KB context, Definition of Ready.
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
   `<mission-id>-US1`, `-US2`, … The BA edits and confirms the split.
   Numbering gaps are fine if a story is dropped — never renumber, as
   ticket filenames may already use those ids.
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
7. **Review → save** — write the final Markdown to
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
