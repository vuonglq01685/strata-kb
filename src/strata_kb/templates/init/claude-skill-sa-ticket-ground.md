---
name: sa-ticket-ground
description: Fill the SA-owned "Technical grounding" section of a BA ticket (or "Services & order" of a mission plan) from the hub's <repo>-code document — section ids only, no inference. Use when a ticket has its business sections drafted and needs its technical half, or when the BA invokes /sa-ticket-ground.
---

# sa-ticket-ground — ground a ticket's technical half in the code document

You fill ONE section the BA never touches: `## Technical grounding` in a
ticket, or `## Services & order` in a mission plan (with `--mission`).
Your only source is the hub's `<repo>-code` document. You have **no
repository access** and you never read source code. You are **not a
reviewer** of the BA's work: you fill a different section, you do not
score it.

The argument is the ticket (or mission) file path; `--mission` switches
to the mission layer.

## Workflow

1. **Intake** — read the document. Identify the product repo id
   (`<repo-id>`) from the BA's input or the parent mission. Collect every
   `%%TODO: verify against codebase%%` in the BA-owned sections: these
   are the questions this pass must answer with an id, with
   `[NEW: D<n>]`, or by parking under `Open decisions`. Read the parent
   mission too: `> Parent mission: M-<slug>` under the ticket's title
   points at `missions/M-<slug>.md`. Load its `## Technology decisions`
   table — its D-rows are the only legal targets of `[NEW: D<n>]`. With
   `--mission` that table is in the file you are filling. No parent
   mission, no table: case 2 of Fill degrades to free text.
2. **Load** — from `<repo-id>-code` on the hub only, via the MCP tool
   `kb_get_section` (fallback: `kb get <repo-id>-code <section-id>`),
   discovering ids with `kb_search` (fallback: `kb query`) restricted to
   that document. For a ticket: `struct.tree` (L3 for the file list),
   every `svc.*`, `cmd.test`, and the `db.*` / `api.*` / `int.*` sections
   whose names match the ticket's nouns. For a mission (`--mission`):
   `svc.*`, `dep.*`, `struct.tree` and the architecture document on the
   hub — do **not** load `db.*` or `api.*`; they pull the plan down to the
   wrong layer. Note the document's revision: `kb get` prints it in the
   citation `(<revision>)` and `kb_get_section` returns it — that value
   goes on the `Grounded on:` line.
3. **Fill** — write the section from the loaded sections and nothing
   else. Every BA placeholder resolves to exactly one of three things:
   - an id that exists in `<repo>-code`;
   - `[NEW: D<n>]` — the thing does not exist yet, and row D<n> of the
     parent mission's `## Technology decisions` says what it will be. No
     matching row → append one first, then write the marker:
     `| D<n> | <concrete proposal: svc/table/route name and one line why> | OPEN | <human SA / tech lead> | <US id> |`
     The proposal is specific — a name the ticket can use — never "TBD".
     Without a parent mission this degrades to `[NEW: <reason>]`, and
     the handover says a mission would give the decision an owner;
   - `Open decisions` — only for code that EXISTS and the document
     cannot prove: internal flow, failure modes, body schemas, a
     contradiction with a BA statement. Never for a thing that is
     simply not built yet.

   On a `## Services & order` row a single `[NEW: D<n>]` exempts every
   unknown `svc.*` on that row, `Depends on` included. Put the marker on
   the new service only, and keep `Depends on` to services that already
   exist or carry their own decision row.

   Then fill the section field by field:
   - `Grounded on: <repo-id>:<repo-id>-code @ <revision>` — first line.
   - `Service:` — `svc.<name>` ids as the document spells them (a name
     over 40 characters carries an opaque 6-hex-character suffix; copy
     it, never retype it). The record has no directory field — a
     directory, when needed, is a `Files:` entry.
   - `Files:` — one path per sub-bullet, spelled exactly as `struct.tree`
     lists it. `struct.tree` stops at depth 4 and 600 lines: list the
     deepest directory it shows rather than a path you cannot see. A
     file the ticket will create: `<path> [NEW: D<n>]`.
   - `Tables:` — `db.<table>.<column>`, the column spelled as the table's
     `Column` cell. `none` when the ticket touches no table the document
     knows.
   - `Routes:` — `api.<tag> — <METHOD> <path>` copied from the tag's
     table. `none` when the document has no `api.*` for it.
   - `Externals:` — `int.<name>` ids, or `none`.
   - `Verify with:` — `cmd.test` followed by the command in
     backticks: the section's `Primary:` value or one of its
     alternatives, byte for byte.
   - `Open decisions:` — every question the document cannot answer,
     quoted in the BA's own words when it comes from a placeholder:
     internal flow, failure modes, request/response bodies, a table or
     route the BA assumed and the document lacks, a business statement
     that contradicts the code facts. `none` only when the list is empty.
   For a mission, the same discipline fills `## Services & order`: one
   row per `svc.<name>`, `Depends on` copied from the record, the reason
   citing that dependency; no files, no tables, no routes.
   Each BA placeholder is answered by an id here or parked here; the
   placeholder itself stays in the BA section untouched — the Dev reads
   the answer from this section.
4. **Gate** — run `kb ticket check <file> [--missions-dir <dir>]` (CLI;
   there is no MCP fallback); for a mission,
   `kb ticket check --heading "## Services & order" <file>`.
   `--missions-dir` defaults to the ticket's sibling `missions/`
   directory — pass it when the missions live elsewhere. Fix every
   `[error]` and re-run until it prints `Grounding: PASS`, except a
   D-row still `OPEN`: that FAIL is reported, not fixed. What the
   engine's own words mean:
   - `needs a parent mission to hold the decision` — no back-link. Ask
     the BA to add `> Parent mission: M-<slug>` under the title, or
     write `[NEW: <reason>]` instead.
   - `parent mission '<id>' not found under missions/` — pass
     `--missions-dir`; never delete the marker to silence it.
   - `decision D<n> not in <file>'s Technology decisions` — append the
     row there first.
   - `decision D<n> is <status> (owner: <x>)` — a human decides before
     Dev. Report it and stop; NEVER flip a Status to make the gate pass.
   - warning `has Technology decisions — reference the row as
     [NEW: D<n>]` — you used free text where a D-row belongs.
   A non-empty `Open decisions` is a FAIL by design: report the list to
   the BA instead of emptying it by guessing.
5. **Handover** — report: the ids grounded, the `[NEW: D<n>]` entries,
   the open decisions (count and text), the BA placeholders answered,
   and any BA-section contradiction found. The BA decides what goes back
   to the business side and what goes to the Dev. End the report with
   this fixed block — English heading, entries in the BA's language:

```
## Needs input
- Decisions proposed (OPEN → DECIDED by owner): D3 (svc.billing, owner: <x>, blocks US2), …
- Open decisions for the Dev (code exists, document cannot prove): …
- BA-section contradictions: …
```

## Hard rules

- Every line in the SA-owned section (`## Technical grounding`, or
  `## Services & order` with `--mission`) must either
  - point at a section id that exists in the `<repo>-code` document, OR
  - carry `[NEW: D<n>]` naming a DECIDED row of the parent mission's
    `## Technology decisions` — `[NEW: <reason>]` only when there is no
    parent mission, OR
  - go under `Open decisions`.
- No data → `Open decisions`. Never infer; never fill from a generic
  pattern or from what "a service like this usually has".
- Never edit a BA-owned section. A business statement that contradicts
  the code facts goes under `Open decisions`, quoted, not corrected.
- The first line is `Grounded on: <repo-id>:<doc-id> @ <revision>`,
  copied from the document's own manifest revision. Ground only on the
  hub's copy — a document you cannot find on the hub is not a source.
- Never write internal flow; never write failure modes — the document
  cannot prove either. Those questions go to `Open decisions` for the
  Dev, who has the code and GitNexus.
- `kb ticket check` failing to RUN is not a PASS. No CLI → tell the BA
  to install `strata-kb`; never hand over an unchecked section as
  checked.
- Never tick a Definition of Ready checkbox; only the BA confirms DoR.
- English headings stay English; write the section's free text in the
  BA's working language.
- A thing the code does not have yet is a design decision, not missing
  data: propose it as a `## Technology decisions` row (status OPEN, a
  human owner) and reference it as [NEW: D<n>]. Never park "not built
  yet" under Open decisions.
- You may APPEND rows to `## Technology decisions`; never edit or delete
  an existing row, never change a Status — only a human flips OPEN to
  DECIDED.
