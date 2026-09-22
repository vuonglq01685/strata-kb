# SA grounding in greenfield repos, and SA inside the BA pipeline — design

Date: 2026-09-22
Status: approved in conversation, spec for review
Extends: `2026-09-20-sa-grounding-design.md` (all of it stays; this
document changes §5, §6, §7, §9 and the templates of §3/§4).

## 1. Problem

Two blockers observed on the first real missions and tickets:

1. **DoR cannot close in a skeleton repo.** `kb ticket check` fails by
   design while `Open decisions` is non-empty. In a repo whose code is a
   skeleton, `<repo>-code` has no `svc.*`, `db.*`, `api.*` sections, so
   the SA — following "no data → Open decisions, never infer" — parks
   every placeholder. Every ticket fails the gate; the DoR checkbox
   `Technical grounding filled by SA; kb ticket check PASS` can never be
   ticked. The `[NEW: <reason>]` escape exists in the engine but the skill
   never says when it is the right answer instead of parking.
2. **SA runs as a separate manual step.** `/sa-ticket-ground` is invoked
   by hand after `/ba-ticket-author` finishes. The maturity review never
   sees the technical half, and the SA's "what is missing" answer arrives
   after the BA thinks the ticket is done. Spec 2026-09-20 §9 deferred
   auto-invocation "until the flow is stable"; the flow is now stable
   enough that the manual step is the blocker.

## 2. Decisions (confirmed 2026-09-22)

| # | Decision | Rejected alternative |
|---|---|---|
| G1 | "No data" splits in two. Code that **exists** but the document cannot see (internal flow, failure modes, bodies) → `Open decisions`, gate FAIL, Dev answers — unchanged. Code that **does not exist yet** is a *design decision*, not an inference: the SA proposes it and writes `[NEW: D<n>]`, where `D<n>` is a row of the parent mission's `## Technology decisions`. | Treat greenfield as "no data" and park (today's behaviour — guaranteed FAIL). Author a separate target-architecture document on the hub (`<repo>-arch`) as a second grounding source — heavier, and the decision table already exists in the mission. Tell the Dev to add compose/OpenAPI files so `-code` sees them — cannot precede the ticket that asks for that code. |
| G2 | The gate verifies `[NEW: D<n>]`: the row must exist and its `Status` must be `DECIDED`; `OPEN` is an error naming the owner. | Accept `OPEN` with a warning — DoR closes with an unsettled decision in the Dev's hands. Free-text reasons only — no way to tell a decided design from a guess. |
| G3 | The SA may **append** rows to `## Technology decisions` (status `OPEN`, owner a human, `Blocks` the US id) — the one exception to "never edit a BA-owned section". It never edits or deletes an existing row and never flips a status; a human does that. | A separate SA-owned decisions section — two tables, one meaning; mission lint already checks the existing one. |
| G4 | `sa-ticket-ground` runs **inside** `ba-ticket-author` after `DoR: PASS` and before the maturity review; `kb ticket check` re-runs after every review round that changed the draft, and the SA is re-invoked only on a FAIL. Mission: `--mission` runs after the BA confirms `## Sequencing`, before the review. The standalone `/sa-ticket-ground` command stays for re-grounding when `-code` moves. | Run SA after the review (reviewer never sees the technical half). Run SA before lint (draft still moving, wasted grounding). |
| G5 | A ticket with no `> Parent mission:` keeps free-text `[NEW: <reason>]` (note only) — there is no table to hold a D-row. A ticket **with** a parent mission that uses a free-text reason gets a warning pointing at the table. | Force a mission for every greenfield ticket — a mission is documented as never mandatory. |

Standing constraints: no new extractor; `mdutils.py` frozen; `-code`
stays LLM-free; templates and skill text in English; impact analysis
before touching any symbol; no version bump in either PR.

## 3. Skill `sa-ticket-ground` — what changes

Applies to all four wrappers (skill, command, copilot prompt, cursor
command); the hard-rules block stays byte-identical across them.

**Intake** — additionally read the parent mission
(`> Parent mission: M-<slug>` → `missions/M-<slug>.md`) and load its
`## Technology decisions` table: the D-rows are the only legal targets
of `[NEW: D<n>]`. With `--mission`, the table is in the file itself.

**Fill** — every BA placeholder resolves to exactly one of:

1. an id that exists in `<repo>-code` (unchanged);
2. `[NEW: D<n>]` — the thing does not exist yet and D<n> says what it
   will be. No matching row → the SA appends one:
   `| D<n> | <concrete proposal: svc/table/route name and one line why> | OPEN | <human SA / tech lead> | <US id> |`
   then writes `[NEW: D<n>]` on the grounding line. The proposal is
   specific (a name the ticket can use), never "TBD";
3. `Open decisions` — only for code that exists and the document cannot
   prove (flow, failure mode, body schema, a contradiction with a BA
   statement). Never for a thing that is simply not built yet.

Without a parent mission, case 2 degrades to `[NEW: <reason>]`; the
handover says a mission would give the decision an owner.

**Gate** — `kb ticket check <file> [--missions-dir <dir>]`; for a
mission `kb ticket check --heading "## Services & order" <file>`. A D-row
still `OPEN` is a FAIL the SA reports, never resolves by flipping it.

**Handover** — ends with a fixed block, in the BA's language, English
heading:

```
## Needs input
- Decisions proposed (OPEN → DECIDED by owner): D3 (svc.billing, owner: <x>, blocks US2), …
- Open decisions for the Dev (code exists, document cannot prove): …
- BA-section contradictions: …
```

New hard rules (appended to the block):

```
- A thing the code does not have yet is a design decision, not missing
  data: propose it as a `## Technology decisions` row (status OPEN, a
  human owner) and reference it as [NEW: D<n>]. Never park "not built
  yet" under Open decisions.
- You may APPEND rows to `## Technology decisions`; never edit or delete
  an existing row, never change a Status — only a human flips OPEN to
  DECIDED.
```

## 4. BA pipelines — what changes

### `ba-ticket-author`

Pipeline becomes Intake → Parent mission → Ground → Draft → Pin → Lint →
**Ground technical** → Maturity review → Review → save.

- **6b. Ground technical** — once `kb ticket lint` reports `DoR: PASS`,
  invoke `sa-ticket-ground` on the saved draft as its own subagent (no
  shared context: the SA sees the file and the hub, not the BA's
  reasoning). Keep its `## Needs input` block for the handover.
- **Maturity review** — the Dev-implementability reviewer receives the
  `## Technical grounding` section and the SA's `## Needs input` block as
  input. After each round that changed the draft, run `kb ticket check`;
  FAIL → re-invoke `sa-ticket-ground` with only the changed sections and
  the failing lines (same discipline as `gap-verifier`); PASS → do not
  re-ground.
- **Handover** — the BA's summary carries the SA's `## Needs input`
  verbatim (D-rows waiting for `DECIDED` are the BA's to chase, not the
  Dev's).
- Hard rule edit: "hand the ticket to `/sa-ticket-ground` once the
  business sections are drafted" becomes "step 6b invokes it; re-run
  `/sa-ticket-ground` by hand only when `-code` moves after handover".

### `ba-mission-plan`

Pipeline becomes Intake → Ground → Draft → Split → **Ground services** →
Pin → Lint → Maturity review → Review → save.

- **4b. Ground services** — once the BA confirms the backlog and
  `## Sequencing` is filled, invoke `sa-ticket-ground --mission`. The SA
  fills `## Services & order` and appends D-rows for every service the
  mission will create. `kb mission lint` already warns on an ownerless
  D-row — unchanged.
- The Dev-implementability reviewer receives `## Services & order`.

### Review rubric

`templates/init/review-rubric.md`, Dev-implementability axis, one new
checklist item: "Every `%%TODO: verify against codebase%%` in a BA
section is answered in `## Technical grounding` by an id, a
`[NEW: D<n>]`, or an Open decisions entry — none is silently dropped."

## 5. Templates

- `ticket-template.md`, `## Technical grounding` comment gains:
  "Code the ticket will create → `[NEW: D<n>]`, where D<n> is a DECIDED
  row of the parent mission's Technology decisions. No parent mission →
  `[NEW: <reason>]`."
- `mission-template.md`, `## Technology decisions` comment gains: "The SA
  appends rows here for services, tables and routes the mission will
  create; tickets reference them as `[NEW: D<n>]`. Only a human flips
  OPEN to DECIDED." Example second row:
  `| D2 | New svc.<name> — <one line> | OPEN | <SA / tech lead> | <US id> |`.
- `## Services & order` comment: `[NEW: D<n>]` replaces the free-form
  `[NEW: <why it does not exist yet>]` in the example row.
- `QUICKSTART-ba.md`: step 6 folds into step 5 as 6b; a new short
  subsection "Greenfield repos: what `[NEW: D<n>]` means".
- `docs/src/guide-ba.{en,vi}.md` §3.8 / §4.3 updated the same way.
- README command table: `kb ticket check` gains `--missions-dir` and
  `--heading`.

## 6. Engine `kb ticket check`

### 6.1 CLI

```
kb ticket check <ticket.md | -> [--kb-dir .kb] [--hub URL] [--json]
                [--missions-dir DIR] [--heading "## Technical grounding"]
```

- `--missions-dir` — default resolves exactly as `ticket_lint` does:
  when the file sits in a directory named `tickets/`, its sibling
  `missions/` if it is a directory; otherwise none. Reused, not copied:
  extract the sibling-resolution block of `ticket_lint` into a helper
  both commands call (impact analysis first — `ticket_lint` has tests
  pinning the behaviour).
- `--heading` — passed to `ticketcheck.check(heading=…)`, which already
  takes it. `## Services & order` makes the decisions table the file's
  own.

### 6.2 Engine

`ticketcheck.check` gains a `decisions: Callable[[], DecisionTable | None]`
argument built by the CLI (so the engine keeps no filesystem or CLI
imports):

- Ticket heading: `ticket.PARENT_MISSION_RE` on the ticket text →
  `missions_dir / f"{id}.md"` → `lintcore.section_body(text,
  mission.TECH_DECISIONS_HEADING)` → `lintcore.table_rows`. Columns by
  header name (`#`, `Status`, `Owner`), not position.
- `## Services & order` heading: same parse on the checked text itself.
- No back-link / no file / no section → `None`.

`_check_ids` and `_check_files`, on a `[NEW: …]` whose reason matches
`^D\d+$` (after trim):

| Situation | Result |
|---|---|
| table `None` and the ticket has no `> Parent mission:` | error `[NEW: D3] needs a parent mission to hold the decision — add the back-link or write [NEW: <reason>]` |
| table `None`, back-link present | error naming the missing file / section (mirrors `check_parent_mission` wording) |
| row missing | error `decision D3 not in <mission>'s Technology decisions` |
| `Status` not `DECIDED` (case-insensitive) | error `decision D3 is OPEN (owner: <x>) — a human decides before Dev` |
| `DECIDED` | note `new: <id> — D3 (DECIDED, owner <x>)` |

Free-text `[NEW: <reason>]` keeps today's note. When the decisions table
is present and non-empty, a free-text reason additionally warns
`mission <id> has Technology decisions — reference the row as
[NEW: D<n>]`. Empty reason: existing warning, unchanged.

Exit codes, `Open decisions` semantics, `Grounding: PASS/FAIL` line:
unchanged.

### 6.3 Tests

- `tests/test_ticketcheck.py` — a mission fixture with a decisions table
  (`D1 DECIDED`, `D2 OPEN owner Alice`): `[NEW: D1]` on a `Service:` line
  and on a `Files:` entry → PASS + note; `[NEW: D2]` → error containing
  `Alice`; `[NEW: D9]` → missing-row error; ticket without back-link +
  `[NEW: D1]` → error; back-link to a missing file → error; free-text
  `[NEW]` with table present → warning, PASS; `heading="## Services &
  order"` with the table in the same text → PASS; column lookup by
  header name survives a reordered table.
- `tests/test_cli_ticket_check.py` — `--missions-dir` explicit; sibling
  default from `tickets/<id>.md`; no default when the file is elsewhere;
  `--heading "## Services & order"`.
- `tests/test_ticketlint.py` — the extracted sibling helper keeps
  `ticket lint`'s behaviour (existing tests are the pin).
- `tests/test_templates.py` / `tests/test_init.py` — needles: `[NEW: D`
  in ticket and mission templates and in all four SA wrappers;
  `## Needs input` in the four SA wrappers; `Ground technical` in the
  four `ba-ticket-author` wrappers and `Ground services` in the four
  `ba-mission-plan` wrappers; hard-rules block identical across the SA
  four; copilot/cursor differ only on frontmatter line 2; rubric
  template carries the new checklist item.

## 7. Rollout

**PR 1 — engine and CLI.** `ticketcheck.py`, `cli.py` (two options, one
shared helper with `ticket_lint`), three test files, README rows.
`impact` on `ticketcheck.check`, `ticket_lint`, and any helper touched;
`detect_changes` before commit.

**PR 2 — skills, templates, docs.** Four SA wrappers, eight BA wrappers,
`ticket-template.md`, `mission-template.md`, `review-rubric.md`,
`QUICKSTART-ba.md`, both `guide-ba` sources, template tests.
Spec 2026-09-20 §9: strike "Auto-invoking SA after BA".

No version bump in either PR; CHANGELOG under `## Unreleased`.

**After PR 2 — measure on the MyFlix KB.** One skeleton mission → two
tickets through the new pipeline. Count per ticket: D-rows proposed,
D-rows DECIDED at handover, Open decisions. Consistently many Open
decisions on a *skeleton* repo means the SA is still parking "not built
yet" — fix the skill text, not the gate.

## 8. Out of scope

- `kb mission check` as its own command (`--heading` covers the SA's
  need; a dedicated command is a wrapper away).
- A CI step for `kb ticket check` in `kb-ticket-lint.yml`.
- Auto-flipping `OPEN → DECIDED` on any signal — a human decision stays
  a human act.
- A target-architecture document on the hub (rejected in G1; revisit if
  D-rows prove too thin to carry a design).
