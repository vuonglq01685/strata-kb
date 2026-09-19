---
name: ba-mission-plan
description: Draft an epic-level Mission Plan (C4 L1/L2 diagrams, scope, US backlog) grounded in the KB with pinned citations, for a large feature that will be split into several tickets. Use when a BA asks to plan a big feature / epic / mission, or invokes /ba-mission-plan.
---

# ba-mission-plan — draft a grounded, epic-level mission plan

You are the ORCHESTRATOR of the mission-planning pipeline: Intake →
Ground → Draft → Split → Pin → Lint → Maturity review → Review. The
mission you write is a **draft** — the BA reviews and commits it. It
sits UPSTREAM of `ba-ticket-author`: each story in the backlog is
drafted later, one at a time, by that skill.

Use a mission for a large feature that spans several User Stories. Small
work goes straight to `/ba-ticket-author` — a mission is not mandatory.

An optional argument gives the business need directly; no argument = ask
for it during Intake.

## Workflow

1. **Intake** — collect the business need at epic level: what capability,
   for whom, why it matters, and how success is measured. Agree the
   mission id with the BA: `M-<slug>`, where `<slug>` is lowercase
   kebab-case. The filename stem must equal the id. Ask for target tags
   (e.g. `#arinc424 #airspace`) or an explicit doc-id. Ask, don't guess.
2. **Ground** — use the MCP tool `kb_search` when it is available;
   otherwise fall back to `kb query "<text>" --tags <tags>` (CLI).
   **Budget the search:** 500–800 tokens for broad discovery — enough
   for the citation plus a summary to choose from; `kb_get_section`
   only for a section already chosen; L3 only for a value that will be
   encoded in code or a test. Present **ALL** returned candidates with their
   citations — never silently drop one. When the ambiguity note fires
   (two close-scoring hits), the BA MUST choose — never auto-pick.
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
   `kb context new --refs "<refs>"` (CLI), passing exactly those
   confirmed refs. Embed the block it returns verbatim under
   `## KB context`. **Tags are NOT yours to set:** the engine derives
   them from the pinned sections' own tags. Leave the tool's `tags`
   argument unset and the CLI's `--tags` off — a tag passed by hand is
   validated against the hub vocabulary and an unknown one is an error.
   The tags the BA gave at intake are search keywords for
   `kb query --tags`, nothing more.
6. **Lint** — run `kb mission lint <file>` against the draft. Fix every
   error and re-run until it reports `DoR: PASS`. A coverage warning of
   `0/N US drafted` is EXPECTED at creation time — the tickets do not
   exist yet. Report remaining warnings to the BA; they are the BA's
   judgment call.
7. **Maturity review** — once lint reports `DoR: PASS`, read
   `docs/review-rubric.md`, then `docs/review-rubric.local.md` if it
   exists — the local file overrides the base one (same for
   `docs/ac-quality.md` and `docs/ac-quality.local.md`). Run TWO
   independent reviews of the draft — when your runtime can dispatch
   subagents, run them as TWO subagents IN PARALLEL; otherwise run TWO
   sequential passes, one role per pass. Never blend the two
   perspectives in one pass:
   - *Business-coverage reviewer* — acts as PO/stakeholder; scores the
     "Business coverage" axis of the rubric.
   - *Dev-implementability reviewer* — acts as the tech lead who will
     slice this mission into tickets; scores the "Dev implementability"
     axis.
   Each reviewer returns: a 1–5 score (the LOWEST maturity level fully
   satisfied — never averaged), the checklist with pass/fail per item,
   and a gap list where every gap names the section it lives in and a
   proposed fix.

   Apply the fixes, re-run `kb mission lint`, then review again — at
   most 3 rounds total; stop early when both axes score ≥ 4.

   **Rounds 2 and 3 are not a re-read.** When your runtime can
   dispatch subagents, dispatch ONE `gap-verifier` subagent; otherwise
   run this pass yourself, acting as `gap-verifier`. Either way, it
   reads only three things: the gaps still open, the current text of
   the sections that changed in response, and the rubric items those
   gaps map to — never the whole draft. It returns pass/fail per gap
   with a one-line reason. Do **not** re-read the rest of the draft
   and do **not** re-score an axis in this pass: an axis's score
   rises only when every gap of that axis passes — re-derive it as
   the LOWEST maturity level fully satisfied, using round 1's
   checklist updated with the verifier's pass/fail; otherwise carry
   the previous round's score forward unchanged.

   A gap you cannot close yourself (a missing business decision,
   missing input) is NEVER invented: write `OPEN(<owner>)` at the spot
   and add an `## Open questions` row.

   Record the result in `## Review record`: on the first round replace
   the `Not yet reviewed.` placeholder; append one table row per round
   (`| Date | Round | Business | Dev | Reviewer |`) — the `Reviewer`
   cell reads `gap-verifier` for rounds 2 and 3 — and list the
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
  one owned row in `## Technology decisions`.

  `-svc` responsibility text grounds a diagram — but it
  **never substitutes for a domain citation** in an Acceptance
  Criterion: standard values still come verbatim from a pinned
  domain section.
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
