---
description: Draft a Dev-ready ticket (story, ACs, use cases, Mermaid diagrams) grounded in the KB with pinned citations, via the ba-ticket-author skill
argument-hint: "[business need | --amend <ticket>]"
---

Invoke the `ba-ticket-author` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the business need when given;
when empty, ask for it during Intake — and, with a `missions/` directory
present, run `kb ticket tidy` first (then `kb mission next`).
Print every `conflict:` and `note:` line of `kb ticket tidy` to the BA
as well. Print every `note:` line of `kb mission next` to the BA verbatim, before
the table, and propose the first `to-draft` story; for every `unsorted:`
line ask the BA for its folder and run
`kb ticket tidy --into <folder> <file>`. A `blocked` story may be drafted
only with its reasons acknowledged by the BA and carried into the
handover.

With `--amend <ticket>`, skip Intake and follow the skill's `## Amend mode`:
read the ticket and its `kb_ticket_stale` findings (CLI: `kb ticket stale
--md <file>`), ask the BA for the
trigger(s) (`kb-context`, `architecture`, `scope`, `delivery`), re-pin with
`kb_context_new` (FULL ref list, whole block replaced), run `kb ticket check`
on every amend (`/sa-ticket-ground` first for an `architecture` trigger, else
only when the check FAILs with `re-run /sa-ticket-ground`; any other FAIL goes to the BA), bump `> Revision:` and
append a `## Change log` row (`Affected` = section names), run `kb_ticket_lint` (CLI
fallback `kb ticket lint`) until `DoR: PASS`, review the changed sections only (one round, scores
in the row's `Review` cell, never in `## Review record`), untick the DoR
boxes whose evidence changed and update the `@ rev` pin. A `done` story's
ticket is frozen: new work gets the next free US number. A `DECIDED` row is
superseded, never edited (a superseded row still cited by a `[NEW: D<k>]`
forces the `architecture` trigger). The agent never ticks DoR, commits or pushes.

**Hub access — MCP first.** Reach the hub through the `strata-kb` MCP
tools (`kb_search`, `kb_get_section`, `kb_resolve`, `kb_context_new`,
`kb_ticket_lint`, `kb_ticket_check`,
`kb_ticket_stale`) whenever your client exposes them; fall back to the
matching CLI command only when it does not, or the MCP server cannot be
reached. Every `kb ticket check` below runs as the MCP tool `kb_ticket_check`
(the ticket's text; the local parent mission file's text, when there is
one, as `mission_markdown`), every `kb ticket stale` as `kb_ticket_stale` (the file's text and its
repo-relative path, e.g. `tickets/<M-id>/<us-id>.md`); the CLI is the fallback.
`kb ticket tidy`, `kb ticket export` and `kb publish` have no MCP tool and
stay CLI. `kb mission next` stays CLI too:
it reads this repo's unpublished `missions/` and `tickets/`, which
`kb_mission_next` (the published plan only) cannot see.

Pipeline: Intake → Parent mission → Ground → Draft → Pin → Lint → Ground technical → Maturity review → Review → save,
to `tickets/<mission-id>/<mission-id>-US<n>.md` under a parent mission, so
the back-link check can find it; otherwise ask the BA for a kebab-case
folder name (an epic or feature, e.g. `epic-billing`) and never invent
the folder name.
When the BA names a parent mission, read it for the story title, put
`> Parent mission: <mission-id> @ rev <N>` on its own line directly
under the ticket's H1 title (`<N>` = the mission's current `> Revision:`;
`@ rev` is optional, absent = rev 1), and inherit its pinned refs as STARTING CANDIDATES
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
invented, never looked up by you; `kb_ticket_lint` (CLI fallback `kb ticket lint`) must report `DoR: PASS` before handover — with a
`> Parent mission:` line pass `ticket_id` (file name without `.md`) and the
mission's text as `mission_markdown`, so the back-link checks run over MCP
too (CI runs the full check on the PR);
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
id. Re-run `/sa-ticket-ground` by hand only when `kb ticket check` fails
with `re-run /sa-ticket-ground`. Never read `<repo>-code` or `<repo>-svc` yourself; leave
`## Technical grounding` exactly as the template ships it, and carry the
SA's `## Needs input` block into your handover verbatim.
