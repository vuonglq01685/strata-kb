# Which ticket next, greenfield decisions once, and parallel task lanes — design

Date: 2026-09-24
Status: approved in conversation, spec for review
Builds on: `2026-09-22-sa-greenfield-grounding-design.md` (D-rows,
`[NEW: D<n>]`, SA inside the BA pipeline), `2026-09-23-compose-facts-grounding-design.md`
(outcome-level ACs, compose facts in `-code`), `2026-08-19-dev-agent-design.md`
(`dev-plan` / `dev-execute`, `kb svc note`, `hist.*`).

## 1. Problem

Field evidence from the MyFlix BA repo, one skeleton repo, one mission, one
ticket (`M-platform-operations-US1`):

1. **The first ticket of a greenfield repo is an architecture ticket.**
   `<repo>-code` is generated from code; a skeleton has no `svc.*`, `db.*`,
   `api.*`. Every grounding line is `[NEW: D<n>]`, every D-row waits for a
   human flip, one ticket at a time. The ticket described the architecture
   document's *target* state as if it were the repo's *current* state; the
   Dev's `dev-design` found 8 of 27 ACs contradicting the repo. 1.2.0 and
   1.3.0 fixed the AC layer and the D-row mechanism; what is left is
   **when** the D-rows get decided — today: per ticket, after the draft,
   inside the review loop.
2. **Nobody can answer "which ticket next".** `## Sequencing` orders stories
   inside one mission; nothing orders across missions, and nothing tells the
   BA which story is unblocked. After US1 merged, the BA had no next step.
   The data to answer exists: the Dev's `dev-handover` runs `kb svc note
   --ticket <id>` in the same PR as the code, CI (`kb-code.yml`) publishes
   `<repo>-svc` to the hub on merge, so the hub's `hist.*` tables carry every
   merged ticket id.
3. **Tasks execute one at a time.** `dev-plan` writes one task per AC with
   an `Interfaces` entry so each implementer sees only its own block, but
   nothing records which tasks depend on which. `dev-execute` therefore runs
   them sequentially even when most are independent. Running them in one
   shared checkout is not an option: a bare commit sweeps another agent's
   staged files, a pathspec commit sweeps its unstaged edits (measured
   2026-09-11).

## 2. Decisions (confirmed 2026-09-24)

| # | Decision | Rejected alternative |
|---|---|---|
| N1 | A story's `done` state is **derived from the hub**: its ticket id appears in a `hist.*` row of `<repo>-svc`. No status column, no `--done` flag. | `--done US1,US2` by hand (rots; add only if a repo never seeds `-svc`). A `> Status:` line in the ticket (the Dev never edits the ticket). |
| N2 | `kb mission next` is a **read-only query**, exit 0 after a report; 1 only for a bad directory flag. It is not a gate. | A lint that fails on a blocked story (a backlog is allowed to be blocked). |
| N3 | Cross-mission order is expressed in `## Sequencing` → `Depends on` by naming another mission's US id. No roadmap file. | `missions/ROADMAP.md` (a second place for the same edge). |
| N4 | In a greenfield mission the SA proposes every D-row **with a citation** to the architecture document on the hub, and the BA flips them **once, at mission time** (new step 5b). The SA still never writes `DECIDED` (G3 stands). | Auto-flip a cited row to `DECIDED` (spec 09-22 §8 keeps a human decision a human act). `<repo>-arch` as a second SA grounding source (G1 rejected it; the decision table already exists). |
| N5 | `dev-plan` records a `Depends on:` line per task; two tasks with no dependency path between them are **file-disjoint by construction**. `kb plan waves` computes the waves deterministically and errors on a shared path, a cycle, or an unknown id. | Let the orchestrator compute waves and the A2 reviewer eyeball file overlap (the exact class of error reviews have been missing). |
| N6 | A parallel wave runs each task in its **own git worktree** branched from the ticket branch's current HEAD; the controller merges lanes back with `--no-ff`, runs the full suite once per wave, and deletes the lanes. A merge conflict is a plan defect and goes back to `dev-plan`. | Shared checkout with pathspec commits (the sweep is documented git behaviour). Lanes cut from `origin/main` (earlier waves' commits would be missing). |

Standing constraints: `mdutils.py` frozen; templates and skill text in
English; impact analysis before touching any symbol; no version bump;
CHANGELOG under `## Unreleased`.

## 3. Engine — `kb mission next`

### 3.1 CLI

```
kb mission next [--missions-dir DIR] [--tickets-dir DIR] [--repo-id ID]
                [--hub URL] [--kb-dir .kb] [--json]
```

- `--missions-dir` default `missions/` in the working directory; every
  `*.md` in it is a mission.
- `--tickets-dir` default the sibling `tickets/` of the missions dir when it
  is a directory, else none (coverage cannot be derived; note it).
- `--repo-id` default: the `<repo-id>` of the first `Grounded on:
  <repo-id>:<repo-id>-code @ <rev>` line found in the missions'
  `## Services & order` (`ticketcheck.GROUNDED_ON_RE`). None found and no
  flag → note `done: unknown (no repo id — pass --repo-id)`.
- Local first: `<kb-dir>/<repo-id>-svc` when its manifest exists (a dev
  machine), else the hub via `_hub_or_reason` (the hub resolution `kb
  ticket check` uses, without the exit); the `-svc` document via
  `ticketcheck.load_from_hub(federation_dir, repo_id, f"{repo_id}-svc")`.
  Not on the hub → note `done: unknown (<repo-id>-svc not published — the
  Dev repo has not run dev-code-seed, or CI has not published yet)`. A hub
  that is not configured or not reachable is not an error for this
  command: `_hub_or_reason` returns the reason and the report carries
  `done: unknown (<reason>)` — `_hub_or_exit` (used by the gates) wraps it
  and keeps exiting 1.
- A mission file without a `> Mission:` line is skipped with the note
  `skipped <path>: no '> Mission:' line`.
- Exit code 0 after a report; exit 1 with a red line only when
  `--missions-dir` (default `missions/`) or an explicit `--tickets-dir` is
  not a directory, as `kb ticket check` does. A mission file that cannot be
  read is reported as a note naming the file and skipped, never a crash.

### 3.2 Module `src/strata_kb/missionnext.py`

Pure engine: text in, statuses out. No filesystem, no CLI imports.

```python
@dataclass(frozen=True)
class Story:
    us_id: str
    mission_id: str
    title: str
    depends_on: tuple[str, ...]   # full US ids
    seq_index: int | None         # row index in ## Sequencing, None = absent

@dataclass(frozen=True)
class StoryStatus:
    us_id: str
    mission_id: str
    title: str
    status: str                   # done | drafted | ready | blocked
    reasons: tuple[str, ...]      # blocked only

def parse_mission(text: str) -> tuple[str | None, list[Story], DecisionTable]
def statuses(missions: list[ParsedMission], drafted: set[str], done: set[str] | None) -> list[StoryStatus]
def done_ids_from_history(history_l2: str) -> set[str]
def render(statuses, notes) -> str
def to_json(statuses, notes) -> dict
```

Parsing, all by reuse:

- Mission id: `mission.MISSION_LINE_RE`.
- Backlog ids and titles: `lintcore.table_rows(lintcore.section_body(text,
  "## US backlog"))[1:]` — cells 0 and 1. `check_backlog` is HIGH impact
  (`mission_lint` and `ticket_lint` route through it) and is not touched;
  the DoR gate keeps validating the table, this query only reads it.
- `## Sequencing`: `lintcore.section_body` + `lintcore.table_rows`; columns
  by header name via `lintcore.table_column` (moved there from
  `ticketcheck`, which keeps a `_table_column` alias).
- `Depends on` cell: every match of `M-[a-z0-9]+(?:-[a-z0-9]+)*-US[1-9]\d*`
  as-is; every bare `US[1-9]\d*` prefixed with the mission's own id;
  `none`, `-`, empty → no dependencies. Anything else in the cell is
  ignored (free-text notes are allowed there).
- `## Technology decisions`: `ticketcheck.parse_decisions`, whose `Decision`
  gains `blocks: tuple[str, ...] = ()` from the `Blocks` column, parsed with
  the same id rule. Default keeps `kb ticket check` byte-identical.
- `done`: `history_l2` is `read_group("history")` of the `-svc` document;
  every line matching `svcnote.ROW_RE` except the header (`Ticket`) and
  separator rows (`mdutils._SEP_ROW_RE`) contributes its `ticket` cell,
  across all `hist.*` sections.

Status, first rule that matches:

| Status | Rule |
|---|---|
| `done` | `us_id in done` |
| `drafted` | `us_id in drafted` (ticket file exists) |
| `ready` | no ticket file; every `depends_on` id is `done`; every D-row of the story's own mission whose `blocks` names it has `status == "DECIDED"` (case-insensitive) |
| `blocked` | otherwise; reasons, one per cause, in this order: `US <id> not done` (also when the dep is only `drafted`), `US <id> unknown` (no mission declares it), `D<n> OPEN (owner: <x>)` (any status other than `DECIDED`, printed as written; owner `?` when empty) |

`done is None` (hub could not answer): no story is `done`; the note explains
it; a story whose dependencies are all `drafted` still reads `blocked` with
`not done`.

Order: missions by file name; within a mission by `seq_index`, stories
absent from `## Sequencing` after those present, in backlog order. No
topological sort — a status is local to the story; a dependency cycle shows
as two `blocked` lines naming each other.

### 3.3 Output

```
note: done: unknown (myflix-svc not published — …)      ← only when it applies

| US | Mission | Status | Reason |
|---|---|---|---|
| M-platform-operations-US1 | M-platform-operations | done | |
| M-platform-operations-US2 | M-platform-operations | ready | |
| M-catalog-US1 | M-catalog | blocked | US M-platform-operations-US2 not done; D3 OPEN (owner: Alice) |

Next: M-platform-operations-US2 — <title>
```

`Next:` names the first `ready` story in output order; with none:
`Next: none ready — <n> blocked, <m> drafted, <k> done`. `--json` emits
`{"notes": [...], "stories": [...], "next": "<id>" | null}`.

## 4. BA skills, templates, docs

All four wrappers of each skill (Claude skill and command, Copilot prompt,
Cursor command) change together; the hard-rules block stays byte-identical
across a skill's four wrappers, as `tests/test_templates.py` already pins.

### 4.1 `ba-mission-plan`

- **Intake**: also ask for the doc-id of the architecture document on the
  hub (a domain document; `kb_search` finds it). Never ask "is this
  greenfield" — the SA sees that in `-code`.
- **Split**: when the SA's step 5 comes back with no existing `svc.*` (or
  the BA says the repo is a skeleton), the first story is the **foundation
  slice**: what the architecture document says must exist before any
  feature story — services, database, API skeleton — cited `[<arch> §x]`,
  outcome-level ACs, still at most 10; every other story `Depends on` it in
  `## Sequencing`. The story-size heuristic applies; the foundation may be
  two stories.
- **New step 5b — Decide**, after Ground services and before Pin: present
  the whole `## Technology decisions` table once. The BA flips to `DECIDED`
  the rows whose citation they confirm; a row with no citation keeps `OPEN`
  and a named owner. The agent never flips a status.
- New hard rule: *"A `[NEW: D<n>]` proposal that cites an architecture
  section on the hub is a recorded decision: the BA flips it at mission
  time, in step 5b, not ticket by ticket. A proposal without a citation
  stays `OPEN` with a human owner."*

### 4.2 `sa-ticket-ground --mission`

- **Load**: unchanged list (the architecture document is already in it).
- **Fill**: when `<repo>-code` has no `svc.*`, every service the mission
  needs comes from the architecture document; each appended D-row cites it
  in the Decision cell:
  `| D2 | New svc.api — REST gateway [myflix-arch §3.2] | OPEN | <SA / tech lead> | M-x-US1 |`.
  A row the document does not support is still a concrete proposal, never
  "TBD", and carries no citation — that is the signal for the BA to keep it
  `OPEN`.
- Hard rules: unchanged. The SA never writes `DECIDED`.

### 4.3 `ba-ticket-author`

- **Intake**: with no argument and a `missions/` directory present, run
  `kb mission next` first and show its table. Propose the first `ready`
  story; the BA may pick another. A `drafted` story points at its existing
  file. A `blocked` story may be drafted only with its reasons acknowledged
  by the BA, and those reasons go into the handover verbatim.
- Steps 2–9: unchanged.

### 4.4 `dev-handover`

One sentence in **Record service history**: *"`kb svc note` is what makes
`kb mission next` on the BA side see this story as done; a ticket that
skips it stays `drafted` forever."*

### 4.5 Templates and docs

- `mission-template.md`: `## Technology decisions` comment and example row
  D2 gain the citation form; `## Sequencing` comment: *"`Depends on` may
  name a story of another mission (`M-<other>-US<n>`); write `none` for a
  story that starts first."*; Definition of Ready gains
  `- [ ] Every D-row blocking a story with no dependency is DECIDED (kb mission next shows it ready)`.
- `ticket-template.md`: unchanged.
- `QUICKSTART-ba.md`: new subsections *Which ticket next* and *Greenfield:
  decide the D-rows once*. `docs/src/guide-ba.{en,vi}.md`: §4.4 *Ticket kế
  tiếp* / *Which ticket next*, and the greenfield note in §4.3.
- README command table: `kb mission next` row.

`kb mission lint`, `kb ticket check`, the review rubric: unchanged.

## 5. Dev side — dependencies, waves, lanes

### 5.1 `dev-plan`

- Every task block carries one line directly under its title, same shape
  as `Exempt:`: `Depends on: none` or `Depends on: task 2, task 5`. The
  three headings Files / Interfaces / Steps are unchanged.
- The plan-author derives the line; it does not choose it. Task B depends
  on task A when B consumes an Interface A produces, **or** B and A share a
  path under Files. Consequence: two tasks with no dependency path are
  file-disjoint. The closing verification task depends on every other task.
- A2 plan-reviewer gains a fifth question: *"Is every `Depends on:` line
  consistent with Files and Interfaces — no two tasks without a dependency
  path share a path, every consumed interface names its producer, no
  cycle?"* A miss is a BLOCKER. The reviewer also runs `kb plan waves` and
  quotes its output; an error there is a BLOCKER on its own.

### 5.2 Engine — `kb plan waves docs/impl/<ticket-id>-plan.md [--json]`

`src/strata_kb/planwaves.py`, pure engine. It reuses `prlint`'s section
splitter for the task headings and reads, per task: its number from the
heading, the `Depends on:` line, and every path under **Files** (one path
per bullet, the `create / modify / test` label stripped; a path is the
first backtick span or the first whitespace-delimited token).

Errors (exit 1, each named with both task numbers):

- `task 4 depends on task 9 — no such task`
- `tasks 2 and 3 share <path> but neither depends on the other`
- `dependency cycle: 2 → 5 → 2`
- `task 3 has no Depends on: line` (a plan written before this change —
  every task must carry it before `dev-execute` may parallelise; `none` is
  the explicit form)

Output on success:

```
wave 1: task 1, task 2
wave 2: task 3
wave 3: task 4        (closing verification)
```

`--json`: `{"waves": [[1,2],[3],[4]]}`. Wave n = tasks whose every
dependency sits in an earlier wave. Ordering inside a wave is by task
number.

### 5.3 `dev-execute`

- After **Isolate**, run `kb plan waves`; an error stops the phase and
  returns the plan to `dev-plan` (the same route an incomplete task block
  takes). A plan without `Depends on:` lines runs sequentially as today,
  with that note in the Next-step block.
- A wave of one task: today's per-task flow, unchanged.
- A wave of two or more tasks, when the runtime can dispatch subagents:
  - **Lane**: `git worktree add .worktrees/<ticket-id>-task-<n> -b
    <ticket-id>-task-<n> HEAD` from the ticket branch. Where the runtime
    offers its own worktree isolation, use it only if its base contains the
    ticket branch's HEAD (verify with `git merge-base --is-ancestor`);
    otherwise create the lane by hand.
  - **Dispatch** one implementer per lane, at most **3 lanes at a time** —
    a larger wave runs in batches of 3 (`ponytail:` fixed cap; raise it once
    a measured wave shows the machine and the suite can take more). The
    implementer gets the same three things as today, plus its lane path,
    and the sentence *"Never use `run_in_background`; run every test in the
    foreground and let the call block."* Scoped tests inside the lane; the
    implementer commits in its lane branch; report to
    `docs/impl/<ticket-id>-review/task-<n>-report.md` inside the lane.
  - **Merge back**, in task-number order: `git merge --no-ff
    <ticket-id>-task-<n>` into the ticket branch; copy the report out of the
    lane if it did not land in the merge. A conflict is a plan defect: stop,
    do not resolve, return to `dev-plan` naming the two tasks.
  - **Verify the wave**: the controller runs `cmd.test` and `cmd.lint` once
    after the last merge of the wave and shows the output.
  - **A3 per task**, unchanged in substance: the diff is
    `git diff <merge-base>..<lane-branch>` written to `task-<n>.diff`; tick
    only after A3 is clean; then `git worktree remove` the lane and delete
    its branch.
- Resume: the first wave with an unticked task; ticked siblings are
  skipped; the remaining tasks of that wave run under the same rules.
- Runtime without subagents: sequential in wave order, today's fallback.

A4, A5, the gates, and `dev-handover` are unchanged.

### 5.4 Docs

`QUICKSTART-dev.md`: one paragraph on `Depends on:`, `kb plan waves`, and
lanes. README command table: `kb plan waves` row.

## 6. Testing

- `tests/test_missionnext.py` — text fixtures only: two missions with a
  cross-mission dependency; each of the four statuses with the exact reason
  strings; bare `US2` prefixed with the mission id; `none` / `-` / empty
  cells; D-row `blocks` `OPEN` → blocked with owner, `DECIDED` → ready;
  unknown dependency; dependency `drafted` but not done → `not done`;
  story absent from Sequencing ordered last; `done=None` → note and no
  `done` row; `Next:` both forms; JSON shape; `done_ids_from_history`
  skips header and separator rows and reads several `hist.*` sections.
- `tests/test_cli_mission.py` — `mission next` over a temporary
  `missions/` + `tickets/`; default dirs; `--repo-id`; repo id derived from
  `Grounded on:`; `-svc` absent on the hub → note, exit 0; `hist.*` read
  through a fake federation directory (the fixture layout of
  `tests/test_cli_ticket_check.py`).
- `tests/test_missionlint.py` — unchanged; `check_backlog` is untouched.
- `tests/test_ticketcheck.py` — `Decision.blocks` parsed, several ids, empty
  cell; existing tests unchanged.
- `tests/test_planwaves.py` — a three-task plan text: waves; each error
  message; `none`; missing line; `--json`.
- `tests/test_cli_*` for `plan waves`: exit 0 / 1, `--json`.
- `tests/test_templates.py` — needles: `kb mission next` in the four
  `ba-ticket-author` wrappers and `QUICKSTART-ba.md`; `Decide` (step 5b) in
  the four `ba-mission-plan` wrappers; the citation example row in
  `mission-template.md`; the `kb svc note … kb mission next` sentence in the
  four `dev-handover` wrappers; `Depends on:` in the four `dev-plan`
  wrappers; `kb plan waves` and `worktree` in the four `dev-execute`
  wrappers; hard-rules blocks identical across each skill's four wrappers;
  `index.yaml` still maps every wrapper.
- Manual, recorded in the PR: on the MyFlix BA repo, `kb mission next`
  shows US1 `done` (or `drafted` with the `-svc` note) and a `Next:` line;
  on the MyFlix Dev repo, `kb plan waves` on the US1 plan prints waves or
  names the missing `Depends on:` lines.

## 7. Rollout — three PRs, no version bump

- **PR 1 — BA engine.** `missionnext.py`, `cli.py` (`mission next`),
  `lintcore.table_column`, `ticketcheck.Decision.blocks`, README row,
  the three test files above. `impact` on `parse_decisions`,
  `_table_column` before editing; `detect_changes` before commit.
- **PR 2 — BA skills, templates, docs.** Four wrappers each of
  `ba-mission-plan`, `sa-ticket-ground`, `ba-ticket-author`, `dev-handover`;
  `mission-template.md`; `QUICKSTART-ba.md`; both `guide-ba` sources;
  `test_templates.py`.
- **PR 3 — Dev side.** `planwaves.py`, `cli.py` (`plan waves`), four
  wrappers each of `dev-plan` and `dev-execute`, `QUICKSTART-dev.md`, README
  row, `test_planwaves.py`, CLI test, `test_templates.py`.

PR 3 is independent of PR 1 and PR 2. CHANGELOG entries under
`## Unreleased`, one bullet per PR.

## 8. Out of scope

- `--done` on `kb mission next` (add only for a repo that never seeds
  `-svc`).
- A roadmap file or a priority beyond dependencies.
- Auto-flipping `OPEN → DECIDED` on a citation or any other signal.
- A CI step for `kb mission next` or `kb plan waves`.
- Changing `kb mission lint`, `kb ticket check`, the review rubric, A4, A5.
- Raising the 3-lane cap, or making it configurable, before a measured run.
- Detecting a merged ticket for a docs-only story that touched no service
  (no `hist.*` row; the BA drafts the next story by hand).
