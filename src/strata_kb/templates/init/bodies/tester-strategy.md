Write the test strategy of this repo (`docs/test-strategy.md`) or amend it.
It ranks what to test first and why. You are the Tester; you open the PR and
never merge it: a human does. The strategy never blocks `/tester-test-story`:
a story is tested whether or not the strategy has a row for it.

Modes: no argument is **New**; `--amend` is **Amend**. `.kb/test-env.yaml` is optional:
a strategy can be written from documents alone, before any code or
environment exists. When the file exists, read it first: Types and Tools
must agree with it. When it is missing, write the planned environments
(front end, API, database, tools) under `## Environments & data`, mark them
"not set up yet", and tell the Tester to run `/tester-env-setup` before the first `/tester-test-story`.
Never commit `.env`, and never write a secret into the strategy:
environments point at `.kb/test-env.yaml`.

## New

1. **Template.** Copy `docs/templates/test-strategy.md` to
   `docs/test-strategy.md` on a new branch (`git switch -c strategy/rev-1`,
   from the default branch). Stop if the file already exists: use `--amend`.
2. **Scope.** Ask the Tester for the scope and for the `> Plan:` line (the BA
   repo id; `—` when there is no BA repo). Ask, do not guess.
3. **Ground.** Use the MCP tool `kb_search` with `kinds=["kb","ba"]`, or
   `kb query "<text>" --kind kb --kind ba` (CLI). Present **ALL** returned
   candidates with their citations, never silently drop one; when two hits
   score close, the Tester chooses, never auto-pick. Read the hub status:
   `kb mission next --from-hub --json`. It shows which missions and stories
   exist, which are `done`, and which `done` ones have no report yet.
4. **Rows.** Fill `## Priority order`, one row per target, by case:
   - docs only (no plan): rows are KB areas `[<repo:doc-id> §<section>]`,
     Pin `—`;
   - a plan exists: mission and story rows (Pin `rev <N>`), and KB-area rows
     for scope no mission covers yet;
   - joining late: put the untested `done` backlog first, ranked by risk.
   Every row has a Rank, a Risk (High, Medium, Low) and a Why that cites
   evidence. Fill the other sections too; leave no template placeholder.
5. **KB context.** `kb context new --refs "<refs>"` with exactly the KB-area
   refs the rows use; paste its block into `## KB context`.
6. **Lint.** `kb strategy lint docs/test-strategy.md --hub`; fix every finding
   until it exits 0. A `pin-moved` warning is a prompt to re-pin, not to
   ignore.
7. **Q1 review.** Dispatch the `test-case-reviewer` subagent in a fresh
   context, handing it only the path of `docs/test-strategy.md`,
   `.kb/test-env.yaml`, `docs/test-review-rubric.md` and
   `docs/test-review-rubric.local.md` (it wins where they disagree), and asking
   for the `## Strategy axes`. Name the model: the most capable one available. Never
   pre-judge a finding. Append each round to `## Review record`; round 2
   verifies only. Pass when no BLOCKER stands and at most 2 SUGGESTED remain.
8. **PR.** Commit `docs/test-strategy.md` (never `.env`), push with
   `git push -u origin HEAD`, open `kb pr open --title "test: strategy rev 1"
   --body-file <file>`. Never merge. The merge ships it: `kb report-ingest`
   publishes it as section `strategy` when it is lint-clean.

## `--amend`

1. **Branch, then findings.** Run `git fetch origin`, then start from the
   default branch: `git switch -c strategy/rev-<N> origin/<default>` (`<N>` is
   the next revision; find `<default>` as in `/tester-test-story`). Run
   `kb test stale --json`. When `docs/test-strategy.md` does not exist, the
   only finding is `tc-revision`: stop and point the Tester to New mode. No
   findings and no environment change (see step 2): say so and stop.
2. **One change per finding**, by code, proposed to the Tester one at a time,
   each approved or rejected by the Tester. Apply only the approved ones.
   - `pin-moved`: re-pin the row (`rev <N>`).
   - `.kb/test-env.yaml` now exists but `## Environments & data` still says
     "not set up yet" (check this even with no finding): point the section at
     the file and align Types and Tools with it, trigger `scope`.
   - `broken-target`: re-point the row to the new target, or drop it.
   - `coverage`: add a row, or a `last` row, for the story or area with none.
   - `kb-context`: refresh the block with `kb context new --refs "<refs>"`
     (fix or drop a broken ref); trigger `kb-context`.
   - `tc-revision`: not a strategy change. Name it to the Tester and leave it
     for `/tester-test-story`; propose no edit.
   - a rank change, citing the evidence that moved it (trigger `priority`).
   In an unattended run, `## Auto mode` below decides which of these you may make; otherwise the Tester decides every change.
3. **Revise.** Bump `> Revision:` by one and append one change-log row with the
   trigger set (kb-context, plan, coverage, priority, scope; comma-separated),
   what changed, which sections, and the Review cell.
4. **Lint, Q1, PR.** `kb strategy lint docs/test-strategy.md --hub` until it
   exits 0; Q1 as in New step 7 (a reorder must state what evidence changed);
   branch `strategy/rev-<N>`, commit, push, `kb pr open`. Never merge.

## Auto mode

Run `kb auto status --json`. When `enabled` is false, this section does not apply. When true, the rules below replace the human gates named in them.

The runner starts this skill as `/tester-strategy --amend`, when `kb test stale` has strategy findings. Nobody answers questions during the run. Auto never writes a new strategy: with no `docs/test-strategy.md`, end `AUTO-RESULT: failed no-strategy`. Every step and every hard rule not named here stays as written, except the manual "Never merge" (the merge rule below replaces it in an unattended run).

**Already finished.** The runner re-runs a task after a crash, so check first. Run `git fetch origin && git switch --detach origin/<default>` (the working tree may be on an older branch), then `kb pr find --head auto/strategy --state all --json`, and the same for each `auto/strategy-r<N>` branch `git ls-remote --heads origin 'auto/strategy-r*'` lists (numeric `<N>` only). When `kb test stale --json` (run on that fresh default) has no strategy finding and a merged PR exists, change nothing and end `AUTO-RESULT: done`. An open PR means a crashed run: `git switch auto/strategy` (or the `-r<N>` branch) and continue at step 3 of the merge rule.

**Branch.** This replaces `--amend` step 1's `strategy/rev-<N>` and step 4's branch name. Start from the fresh default: `git fetch origin && git switch -c auto/strategy origin/<default>`. When `git ls-remote --heads origin auto/strategy` lists the branch, run `kb pr find --head auto/strategy --state all --json`. No PR ever means a run crashed after its push: switch to the branch and continue at step 2 of the merge rule (open the PR). Merged or closed PRs mean the branch is spent: never force-push over it and never delete it. Use `auto/strategy-r2` instead (`-r3`, … the first name `git ls-remote` does not list), with the same checks.

**Allowed changes.** Apply these without asking the Tester; one change per finding, as in `--amend` step 2:

- `pin-moved`: re-pin the row.
- `broken-target`: re-point a renamed or split target when the citations show the rename or split. Otherwise leave the row and record an Auto decision line proposing the drop for the Tester. Auto never drops a row.
- `coverage`: add a row for an uncovered story, or a `last` row for a story you judge not worth a rank, so the finding clears.
- `kb-context`: refresh the block (trigger `kb-context`).
- `.kb/test-env.yaml` alignment (trigger `scope`).
- A rank change, only with cited evidence and an agreeing reviewer (trigger `priority`).

`tc-revision` is not a strategy change: leave it. Nothing else changes.

**Decisions.** Write each change as one `**Auto decision:**` line: the finding, what you checked, the options, the choice, and why. Put the line directly under the `## Change log` table, outside any table row. A change that is only a re-pin needs no reviewer. For a re-point, an added row, a `last` row, a `kb-context` refresh, a `scope` alignment or a rank change, give a fresh-context reviewer (a subagent when your runtime can dispatch one, otherwise a separate pass that reads nothing but these inputs) the strategy rows, the evidence and your pick; it answers agree or object with a reason. On an objection, decide again once:

- a re-point, added row or `last` row then goes ahead as you decide;
- a rank change that is objected to twice is dropped: leave the ranks as they are and record the proposal (the old and new rank, the evidence) in its Auto decision line for the Tester.

**Revise.** As `--amend` step 3. The Review cell starts with `auto`, for example `auto: reviewer agreed`. A rank change that stands adds the trigger `priority`.

**Lint, Q1.** Run `kb strategy lint docs/test-strategy.md --hub` until it exits 0; fix by the rules above, never by skipping a finding. A lint that will not pass ends `AUTO-RESULT: failed lint`. Then Q1 as in New step 7, as a subagent. When you cannot dispatch one, end `AUTO-RESULT: failed test-review no-subagents`. A BLOCKER still standing after round 2 ends `AUTO-RESULT: failed test-review <id>`.

**The merge rule.** In an unattended run, this rule replaces "Never merge". A manual run never merges. Never run `kb publish`.

1. Commit `docs/test-strategy.md` (never `.env`) and push with `git push -u origin HEAD`.
2. Open the PR with `kb pr open --title "test: strategy rev <N>" --body-file <file>`.
3. Wait for the checks with `kb pr checks --watch`. If a check is red, read the failure (`gh run view --log-failed`), fix it, commit, `git push origin HEAD`, and watch again: up to 2 fix rounds in all. Still red after the second round: end `AUTO-RESULT: failed ci-red <pr-url>`. Never merge on red or pending checks.
4. Every check green: `kb pr merge --squash --delete-branch`. When the merge is refused for want of an approving review, do not retry: end `AUTO-RESULT: blocked-review <pr-url>`. A human reviews and merges the PR; the runner counts a merged parked amend as done.
5. After any merge error, run `kb pr view --json` before you end `failed`: `kb pr merge` can report an error after the merge went through. A merged PR is a success.
6. After the merge, the `kb-publish-request` workflow on `<default>` publishes the strategy. End `AUTO-RESULT: done`.

### Result line

End the reply with exactly one line, and make it the last line. Nothing follows it: no code fence, no markdown, no closing remark. It has one of three forms:

- `AUTO-RESULT: done`: the PR is merged, or the work was already finished. Write no text after `done`.
- `AUTO-RESULT: blocked-review <pr-url>`: the merge needs an approving review the agent may not give.
- `AUTO-RESULT: failed <reason>`: always a reason on the same line: `lint`, `ci-red <pr-url>`, `test-review <id>` or `test-review no-subagents`, or `no-strategy`.
