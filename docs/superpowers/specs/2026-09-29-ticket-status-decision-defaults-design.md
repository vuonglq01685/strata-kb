# Ticket status, decision defaults, NFR from KB, ticket folders — design

Date: 2026-09-29
Status: approved in conversation, spec for review
Builds on: `2026-09-24-mission-next-greenfield-design.md` (`kb mission next`,
`done` from `hist.*`), `2026-09-22-sa-greenfield-grounding-design.md`
(`Grounded on:` line, D-rows), `docs/review-rubric.md`, `docs/ac-quality.md`.

## 1. Problem

Field evidence from the MyFlix BA repo (`myflix-ba`, 7 missions, 3 tickets,
`M-platform-operations-US1` merged and published to the hub):

1. **A merged ticket reads `drafted`.** `kb mission next` printed
   `note: done: unknown (no repo id — pass --repo-id)` and the
   `ba-ticket-author` agent summarised the table without that line. Cause:
   the missions' `## Services & order` carry
   `- Grounded on: myflix:myflix-code @ 2946696, myflix:myflix-svc @ 2946696`
   (two docs, comma-separated, written by `sa-ticket-ground`); the template
   shows one doc; `GROUNDED_ON_RE` anchors `$` after one `@ <rev>` and does
   not match; `grounded_doc` returns None; nothing is `done`. `kb mission
   lint` does not check the line and reports `DoR: PASS`. With
   `--repo-id myflix` the story is `done` — the hub row exists.
2. **Status names answer the wrong question.** `ready` means "no ticket
   file yet, allowed to draft"; a BA reads it as "ready for Dev". `drafted`
   covers everything from an unlinted skeleton to a DoR-complete ticket
   waiting for a sprint.
3. **Reviewers ask routine questions instead of deciding.** The rubric and
   skill give a gap two exits only: a fact already in the KB, or
   `OPEN(<owner>)`. "What if the email is already registered?" becomes an
   Open question. The skill forbids the review from touching business
   intent "on its own authority". A senior BA decides that in one line.
4. **NFR numbers get demanded or invented.** Rubric item "NFRs are
   quantified where the work touches load…" plus lint's `nfr_target_ok`
   (digit or `OPEN(<owner>)`, else error) push the author to produce a
   number the KB never stated. The hub has a `non-functional-requirements`
   document; nothing says the number must come from it.
5. **Flat `tickets/` does not scale.** Every ticket of every mission sits
   in one directory. The BA wants `tickets/<mission-id>/`, a BA-named
   folder for tickets without a parent mission, and an automatic tidy of
   a pre-existing flat layout on the next ticket.

## 2. Decisions (confirmed 2026-09-29)

- **D1** Five statuses, first rule that matches: `done`, `ready`, `draft`,
  `to-draft`, `blocked`. `ready` = ticket file exists and every
  `## Definition of Ready` checkbox is ticked. No re-lint in `mission
  next`: DoR item 2 is "kb ticket lint PASS", the BA's tick is the word.
- **D2** `Grounded on:` accepts a comma-separated list; the `-code` entry
  wins. `kb mission lint` warns when the line cannot be parsed. The
  `ba-ticket-author` Intake prints every `note:` line verbatim.
- **D3** Routine business gaps are decided by the author or reviewer with
  a concrete value and a `DECIDED(default: …)` marker; only non-routine
  gaps (money, legal, external contracts, third-party data, access
  rights, data deletion) become `OPEN(<owner>)`. The BA vetoes in the
  handover; the marker never blocks DoR.
- **D4** NFR numbers come from the KB with a citation, or the row reads
  `N/A — no NFR source in KB`. A number without a KB citation FAILS the
  rubric; a missing number does not. No invented numbers, no `OPEN` for
  the sake of a number.
- **D5** Tickets live at `tickets/<mission-id>/<ticket-id>.md`; without a
  parent mission the BA names the folder. `kb ticket tidy` moves a flat
  layout; the skill runs it at Intake. Every reader accepts both layouts.
- **D6** Two PRs: PR1 engine (D1, D2, lint change for D4, D5); PR2 policy
  prose (D3, D4 wording) with template tests.

## 3. Status model (`kb mission next`)

| Status | Condition | Reason column |
|---|---|---|
| `done` | ticket id is in a `hist.*` row of the hub's `<repo>-svc` | |
| `ready` | ticket file exists, every DoR checkbox `- [x]` | |
| `draft` | ticket file exists, some DoR checkbox `- [ ]` | `DoR 5/8 ticked` |
| `to-draft` | no file, every `Depends on` done, every D-row that `Blocks` it `DECIDED` | |
| `blocked` | no file, at least one reason | one reason per cause (unchanged) |

- `Next:` names the first `to-draft` story (replaces `ready`); the
  none-ready line counts all five.
- `statuses()` takes `drafted: dict[str, tuple[int, int]]` (ticket id →
  ticked, total DoR boxes) instead of `set[str]`. `cli.py` reads every
  ticket under `tickets/` (`rglob("*.md")`, stem = ticket id) and counts
  boxes in `## Definition of Ready` with `lintcore.CHECKBOX_STATE_RE`. No
  DoR section → `0/0` → `draft`, reason `no Definition of Ready section`.
- JSON: `status` values change; no new field. CHANGELOG marks the rename
  breaking; minor version bump.
- A DoR ticked by hand while lint fails reads `ready`. Accepted: the
  checklist is the BA's statement, not the engine's.

## 4. `Grounded on:` parsing and its lint

- `GROUNDED_ON_RE` (ticketcheck.py) matches one entry; a new
  `grounded_entries(line) -> list[(repo, doc, rev)]` splits the value on
  `,` and matches each entry with the existing single-entry pattern.
  `missionnext.grounded_doc` returns the first entry whose doc ends in
  `-code`, else the first entry. `ticketcheck`'s own `## Technical
  grounding` check keeps demanding exactly one entry — a ticket grounds
  on one `-code` doc; only the mission line is lenient.
- `kb mission lint`: when `## Services & order` exists and no line
  parses as `Grounded on:`, warning
  `no parseable 'Grounded on: <repo>:<doc> @ <rev>' line — kb mission
  next cannot derive done`. Warning, not error: a mission is authored
  before the SA grounds it.
- `mission-template.md` line 93 gains one sentence: a comma-separated list
  is allowed; the `-code` entry is the one `kb mission next` reads.
- Skill Intake (claude/cursor/copilot ba-ticket-author): "Print every
  `note:` line of `kb mission next` to the BA verbatim, before the table.
  A `done: unknown` note means the table's `draft`/`ready` rows may be
  merged stories — say so."

## 5. `DECIDED(default: …)`

Written into `review-rubric.md`, `ac-quality.md`, the ba-ticket-author
skill/command (three platforms), and the ticket template's AC comment.

- Shape: the AC states the concrete outcome; the marker closes the line:
  `… then the system rejects with "Email đã được sử dụng"
  DECIDED(default: reject, no login hint)`.
- Routine (decide): duplicate / empty / malformed input, error messages,
  default sort and pagination, empty states, length limits, simple retry.
  Non-routine (`OPEN(<owner>)`): money, legal, external contracts,
  third-party data, access rights, data deletion.
- A `DECIDED(default)` is not an open question: no `## Open questions`
  row. Lint counts only `OPEN` and `%%TODO%%`; no code change.
- Handover lists every `DECIDED(default)` under "Defaults to veto"; the BA
  deletes the marker to accept or edits the value. A marker left in the
  file does not block DoR. `kb ticket export` keeps the marker so the Dev
  knows a default from a stakeholder requirement.
- Rubric item "Every unknown is owned" becomes "Every unknown is owned
  (`OPEN(<owner>)`) or decided (`DECIDED(default: …)`)". New reviewer
  rule: a routine gap must come with a proposed default; a question
  without a decision is the reviewer's gap, not the ticket's.
- Skill hard rule "The maturity review never edits business intent on its
  own authority" becomes "The maturity review closes routine gaps with
  `DECIDED(default: …)`; only non-routine gaps become `OPEN(<owner>)`."

## 6. NFR from the KB

- Author: when an NFR trigger fires, search the KB's NFR document. A
  number found → row `| Concern | Target | How to measure | Source |` with
  Source = citation. Not found → `Target: N/A — no NFR source in KB`,
  Source empty. No proposed number, no `OPEN`, no Open-questions row.
- `acquality.nfr_target_ok` also accepts `N/A — <reason>`
  (`^N/A\s*[—-]\s*\S`). Moods ("fast", "ổn định") stay errors.
- Rubric business item becomes: "Every NFR row cites a KB source or reads
  `N/A — no NFR source in KB`; a number without a KB citation FAILS."
  Reviewers do not ask for a number the KB does not hold.
- `OPEN(<owner>)` in Target stays legal when a named owner will measure.
- Template NFR comment and skill text updated to the same words.

## 7. Ticket folders and `kb ticket tidy`

Layout: `tickets/<mission-id>/<ticket-id>.md`. No parent mission → the
skill asks the BA for a kebab-case folder (epic/feature, e.g.
`epic-billing`) and saves `tickets/<folder>/<ticket-id>.md`. It never
invents a folder name.

Readers accept both layouts, never fail on layout:

- `kb mission next`: `rglob("*.md")` under `tickets/`.
- `kb mission lint` coverage: `tickets/<mission-id>/<us>.md`, then
  `tickets/<us>.md`.
- `kb ticket lint` `_resolve_missions_dir`: walk up to the nearest
  ancestor named `tickets`; `missions/` is its sibling.
- usage transcript path regex: one optional folder between `tickets/`
  and the stem.
- CI `kb-ticket-lint.yml` already globs `tickets/**/*.md` and dispatches
  on `tickets/*`; no change.

`kb ticket tidy [--tickets-dir <dir>] [--into <folder> <file>...]`,
idempotent, exit 0 always:

- Default: every flat `tickets/*.md` with a valid `> Parent mission: M-x`
  line is renamed to `tickets/M-x/<stem>.md` (folder created). Prints
  `moved: <from> → <to>`. Flat files without a parent print
  `unsorted: tickets/<stem>.md — pass --into <folder>`.
- `--into <folder> <file>...`: moves the named files into
  `tickets/<folder>/`.
- No git calls; the BA commits and git detects the rename.

Skill Intake, before `kb mission next`: run `kb ticket tidy`; for every
`unsorted` line ask the BA for the folder and run `--into`. The first
ticket after upgrade tidies a pre-existing repo.

`kb ticket lint` never errors on a flat file — layout belongs to tidy,
not to DoR.

## 8. Tests

PR1:
- `test_missionnext.py`: five statuses; first-match order; `ready` vs
  `draft` from DoR counts; `0/0` reads `draft`; `Next:` picks `to-draft`;
  `grounded_doc` on a two-doc line picks `-code`; no `-code` picks first.
- `test_ticketcheck`: single-entry `Grounded on:` still PASSes; the
  ticket-side check still rejects two entries.
- `test_missionlint.py`: warning when `Grounded on:` unparseable;
  coverage finds `tickets/<mission>/<us>.md`.
- `test_acquality.py`: `N/A — no NFR source in KB` passes, `N/A` alone
  and moods fail.
- `test_cli_mission.py`: nested tickets read; `--tickets-dir` still
  honoured; `_resolve_missions_dir` from a nested ticket.
- `test_ticket_tidy.py` (new): moves parented files, reports unsorted,
  `--into` moves, second run is a no-op.
- `test_usage_transcript.py`: cursor set from a nested ticket path.
- `test_templates.py`: skill text carries "print every `note:` line",
  new status names, `kb ticket tidy` at Intake, folder save path.

PR2:
- `test_templates.py`: rubric carries the decided-or-owned item and the
  NFR-cites-KB item; ac-quality carries the `DECIDED(default: …)` section
  and the routine/non-routine lists; the skill carries the veto list and
  the replaced hard rule; the ticket template's NFR comment names
  `N/A — no NFR source in KB`.

## 9. Out of scope

- An `in-progress` status from Dev branches or Jira.
- Re-running `kb ticket lint` inside `kb mission next`.
- A lint error for `DECIDED(default)` shape or for flat ticket files.
- Migrating `.kb/usage/*.jsonl` (keyed by ticket id, unaffected).

## 10. Risks

- Status rename breaks scripts parsing JSON `status`. Mitigation:
  CHANGELOG breaking note, minor bump.
- `DECIDED(default)` read by a Dev as a hard requirement. Mitigation: the
  marker survives export; the skill's handover names it a default.
- Regex leniency accepts a mission line the template did not describe.
  Mitigation: the template gains one sentence allowing the list; the
  lint warning covers the unparseable case.
