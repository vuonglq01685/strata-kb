Write the test strategy of this repo (`docs/test-strategy.md`) or amend it.
It ranks what to test first and why. You are the Tester; you open the PR and
never merge it: a human does. The strategy never blocks `/tester-test-story`:
a story is tested whether or not the strategy has a row for it.

Modes: no argument is **New**; `--amend` is **Amend**. Read `.kb/test-env.yaml`
first (Types and Tools must agree with it); when it is missing, stop and tell
the Tester to run `/tester-env-setup`. Never commit `.env`, and never write a
secret into the strategy: environments point at `.kb/test-env.yaml`.

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
   `.kb/test-env.yaml` and `docs/test-review-rubric.md`, and asking for the
   `## Strategy axes`. Name the model: the most capable one available. Never
   pre-judge a finding. Append each round to `## Review record`; round 2
   verifies only. Pass when no BLOCKER stands and at most 2 SUGGESTED remain.
8. **PR.** Commit `docs/test-strategy.md` (never `.env`), push with
   `git push -u origin HEAD`, open `kb pr open --title "test: strategy rev 1"
   --body-file <file>`. Never merge. The merge ships it: `kb report-ingest`
   publishes it as section `strategy` when it is lint-clean.

## `--amend`

1. **Findings.** `kb test stale --json`. Group them by row. No findings: say
   so and stop.
2. **One change per finding**, proposed to the Tester one at a time, each
   approved or rejected by the Tester: re-pin a moved target, re-point a
   broken one, add a row (or a `last` row) for a story or area with none, or
   change a rank, citing the evidence that moved it. Apply only the approved
   ones. Auto mode is not available yet: the Tester decides every change.
3. **Revise.** Bump `> Revision:` by one and append one change-log row with the
   trigger set (kb-context, plan, coverage, priority, scope; comma-separated),
   what changed, which sections, and the Review cell.
4. **Lint, Q1, PR.** `kb strategy lint docs/test-strategy.md --hub` until it
   exits 0; Q1 as in New step 7 (a reorder must state what evidence changed);
   branch `strategy/rev-<N>`, commit, push, `kb pr open`. Never merge.
