---
mode: agent
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
   are the questions this pass must answer with an id or park under
   `Open decisions`.
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
   else, field by field:
   - `Grounded on: <repo-id>:<repo-id>-code @ <revision>` — first line.
   - `Service:` — `svc.<name>` ids as the document spells them (a name
     over 40 characters carries an opaque 6-hex-character suffix; copy
     it, never retype it). The record has no directory field — a
     directory, when needed, is a `Files:` entry.
   - `Files:` — one path per sub-bullet, spelled exactly as `struct.tree`
     lists it. `struct.tree` stops at depth 4 and 600 lines: list the
     deepest directory it shows rather than a path you cannot see. A
     file the ticket will create: `<path> [NEW: <why it does not exist
     yet>]`.
   - `Tables:` — `db.<table>.<column>`, the column spelled as the table's
     `Column` cell. `none` when the ticket touches no table the document
     knows.
   - `Routes:` — `api.<tag> — <METHOD> <path>` copied from the tag's
     table. `none` when the document has no `api.*` for it.
   - `Externals:` — `int.<name>` ids, or `none`.
   - `Verify with:` — `cmd.test — \`<command>\``, the section's
     `Primary:` value or one of its alternatives, byte for byte.
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
4. **Gate** — run `kb ticket check <file>` (CLI; there is no MCP
   fallback). Fix every `[error]` and re-run until it prints
   `Grounding: PASS`. A non-empty `Open decisions` is a FAIL by design:
   report the list to the BA instead of emptying it by guessing. If the
   installed `kb` has no `ticket check` command yet, verify every id by
   hand against the document's `_manifest.yaml` section list and say in
   the handover that the gate did not run.
5. **Handover** — report: the ids grounded, the `[NEW]` entries, the
   open decisions (count and text), the BA placeholders answered, and any
   BA-section contradiction found. The BA decides what goes back to the
   business side and what goes to the Dev.

## Hard rules

- Every line in `## Technical grounding` must either
  - point at a section id that exists in the `<repo>-code` document, OR
  - carry `[NEW: <reason>]` saying why it does not exist yet, OR
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
