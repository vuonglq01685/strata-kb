---
description: Draft a Dev-ready ticket (story, ACs, use cases, Mermaid diagrams) grounded in the KB with pinned citations, via the ba-ticket-author skill
argument-hint: "[business need]"
---

Invoke the `ba-ticket-author` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the business need when given;
when empty, ask for it during Intake — and, with a `missions/` directory
present, run `kb mission next` first and propose the first `ready` story.
A `blocked` story may be drafted only with its reasons acknowledged by
the BA and carried into the handover.

Pipeline: Intake → Parent mission → Ground → Draft → Pin → Lint → Ground technical → Maturity review → Review → save,
to `tickets/<ticket-id>.md` — or `tickets/<mission-id>-US<n>.md`
when the ticket has a parent mission, so the back-link check can find it.
When the BA names a parent mission, read it for the story title, put
`> Parent mission: <mission-id>` on its own line directly under the
ticket's H1 title, and inherit its pinned refs as STARTING CANDIDATES
ONLY — never copy its `kb-context` wholesale; pin the ticket's own refs
fresh. Hard rules the skill enforces: citations are mandatory
for standard claims; budget `kb_search` at 500–800 tokens for broad
discovery, call `kb_get_section` only for a section already chosen, and
escalate to L3 only for a value that will be encoded in code or a test;
present ALL `kb_search` candidates and let the BA
choose — mandatory when the ambiguity note fires, never auto-pick. A
hit tagged `code` (`<repo>-code` / `<repo>-svc`) is not a candidate for
you — leave it to `/sa-ticket-ground`. Pin only BA-confirmed refs via `kb_context_new`, leaving its `tags`
argument unset — **Tags are NOT yours to set**: the engine derives
them from the pinned sections' own tags, a tag passed by hand is
validated against the hub vocabulary and an unknown one is an error,
and the BA's intake tags are search keywords for `kb query --tags`,
nothing more;
code detail becomes `%%TODO: verify against codebase%%`, never
invented, never looked up by you; `kb ticket lint` must report `DoR: PASS` before handover;
report the authoring cost at handover with `kb usage report --ticket
<ticket-id> --md`, reporting `no usage recorded yet` as-is rather than
guessing a number;
maturity review reads `docs/review-rubric.md`, then
`docs/review-rubric.local.md` if it exists — the local file overrides
the base one, same for `docs/ac-quality.md` and
`docs/ac-quality.local.md`;
review rounds 2 and 3 are a single `gap-verifier` pass over the still-open
gaps and the sections that changed, never a re-read of the whole draft;
never push to Jira — the BA publishes; never tick a Definition of Ready
checkbox yourself — only the BA confirms DoR items.

Code-level detail is not yours to ground: write
`%%TODO: verify against codebase%%` where a service, table, route or
file name is needed, add the owned `## Open questions` row, and let
step 7 (Ground technical) invoke `/sa-ticket-ground` on the saved
draft — it fills the SA-owned `## Technical grounding` section from the
hub's `<repo>-code` document, proposes an `OPEN` row in the parent
mission's `## Technology decisions` for anything the code does not have
yet (referenced as `[NEW: D<n>]`), and `kb ticket check` verifies every
id. Re-run `/sa-ticket-ground` by hand only when `-code` moves after
handover. Never read `<repo>-code` or `<repo>-svc` yourself; leave
`## Technical grounding` exactly as the template ships it, and carry the
SA's `## Needs input` block into your handover verbatim.
