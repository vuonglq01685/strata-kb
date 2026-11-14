Test one story end to end on the declared test environment, and publish a
report only when the round ends `PASS` or `FAIL`. You are the Tester. You
open the report PR; you never merge it in this phase — a human does.

`<story>` is the story id given to the command (a parent story or an
unsplit story). Ask for it when it is empty. Read `.kb/test-env.yaml`
first; when it is missing, stop and tell the Tester to run
`/tester-env-setup`.

## Hold-and-release rules

- The claim and the environment lock are released **on any stop**, not only
  at the end: `kb test-env unlock` and `kb claim release <story>` (the claim
  is released after the report PR is opened, so a `reopened` story never keeps
  an open Tester claim). A stop never leaves either one held.
- Update the claim phase as you go: `kb claim update <story> --phase <p>`
  with `cases`, `scripts`, `run`, `report`, `review`, `publishing`. Exit 3
  from any `kb claim` or `kb test-env lock` call means the claim or lock is
  taken or lost: stop at once.
- Secrets: credentials come from env vars only, through
  `tests/fixtures/login.ts`. Never write a value into a test case, script,
  report, log, PR or chat.

## Steps

1. **Fetch the ticket.** `kb ticket fetch <story> --out tests/<story>/ticket.md`.
   Read its acceptance criteria and its `### Alternate / exception flows`.
   **Testable check**, before anything is held: run
   `kb mission next --from-hub --json` and read the rows of `<story>` and of
   its children (rows whose `parent` is `<story>`; an unsplit story is its own
   only row). Stop, holding nothing, unless the story's `test_status` is not
   `closed` (a closed story is final: never test it again) and every child
   (or the unsplit story itself) has `status` `done` and a `test_status` that
   is empty or `fix-done`. A child that is not `done`, or that is `reopened`
   (the Dev has not fixed it yet) or `testing` (another Tester holds it),
   means "not testable yet": say which child and why.
2. **Deploy check.** `kb test-env deployed <story>`. Exit 1 (hub or GitHub
   error): stop with the printed error; nothing is held. Exit 4 means the
   environment does not run the published commits yet: stop with
   "not deployed yet", say which repo the command printed, and take no lock
   or claim. One exception: when every printed reason is `no version_check`
   (the repo declares no version endpoint), a manual run asks the Tester to
   confirm the deploy and goes on only on a yes; any other reason, or no
   Tester to ask, stops with "not deployed yet".
3. **Lock the environment.** `kb test-env lock <story>`. Exit 3 means another
   round holds this environment: stop, "environment locked". The lock has a
   TTL: step 8.1 and step 8.5 re-run `kb test-env lock <story>` to refresh it.
4. **Branch, then take the claim.** Run `git fetch origin`. Find the default
   branch with `git rev-parse --abbrev-ref origin/HEAD` (it prints
   `origin/<default>`); when `origin/HEAD` is unset it fails, so use the
   `HEAD branch:` line of `git remote show origin`. Start from it, not from the branch you are on:
   `git switch -c test/<story>-R<n> origin/<default>` (`<n>` as in step 10).
   When that branch already exists, `git switch test/<story>-R<n>`.
   Never write, commit or push on the default branch: when
   `git branch --show-current` is the default branch, stop. Then
   `kb claim take <story>`; exit 3 means taken: unlock (`kb test-env unlock`)
   and stop. Then `kb claim update <story> --phase cases`.
5. **Explore and write the cases.** Walk each acceptance criterion in the
   app with Playwright MCP to learn the real UI text, routes and API
   behaviour. Write `tests/<story>/test-cases.md` from
   `docs/templates/test-cases.md`: one TC per `## TC-<n>` block, every field
   filled (Objective, Type, Priority, Technique, Polarity, Preconditions,
   Test data, Steps, Expected result, Script, Automation). Per AC: at least
   one positive TC, and one negative or boundary TC when the AC states a
   value, limit, format or state. Fill `## Alternate flows coverage` with
   every alternate or exception flow of the ticket. Pick the technique that
   fits (EP, BVA, decision table, state transition, use case).
   Run `kb testcase lint tests/<story>/test-cases.md`; fix every finding
   until it exits 0.
6. **Write the scripts.** `kb claim update <story> --phase scripts`. One
   Playwright Test file per TC at the path its `Script` field names. Rules:
   role/text/testid locators, no brittle CSS or XPath; no `waitForTimeout`
   or other fixed sleep; web-first assertions; every test creates or seeds
   its own data and does not depend on order; API checks through Playwright
   `request`; trace, screenshot and video kept on failure; credentials from
   env only, login through `tests/fixtures/login.ts`. Re-run
   `kb testcase lint` (no orphan scripts).
7. **Q1 review.** `kb claim update <story> --phase review`. Dispatch the
   `test-case-reviewer` subagent under the review contract below, handing it the
   test cases, the scripts and the seed and reset scripts they use, **before any run**. Append each round to the `## Review
   record` of `tests/<story>/test-cases.md` and lint again. A BLOCKER still
   standing after round 2 stops the task (see the stop rule).
8. **Run the pipeline, steps 1–6 in order.** `kb claim update <story> --phase run`.
   The run log is local: `.kb/runlog/` (git-ignored), one file per round.
   1. **Preflight.** Re-run `kb test-env lock <story>` (exit 3: stop and
      release whatever is held). Env health (FE, API, DB `check`) and the
      deploy check again; record each app's commit with `kb test-env version`. A failure
      here ends the round `BLOCKED-ENV`.
   2. **Story run.** Run every TC of the story with
      `npx playwright test tests/<story>/` (a re-test round reruns all of
      them, not only the ones that failed before).
   3. **Clean retry.** Rerun each failing TC on a reset, reseeded DB, up to
      `retries` times (default 3): `kb test-env reset`, then
      `kb test-env seed <name>` for the seed that TC names. Always fails:
      stable failure. Sometimes passes: flaky, so that AC is *unverified*
      (never pass) and the script goes back to you; the Dev is not involved.
   4. **MCP confirmation.** Replay each stable failure by hand through
      Playwright MCP. Reproduced: it is a defect. Not reproduced: it is a
      script defect: record it in the run log; the round ends `INCOMPLETE`.
      Never edit a script during a round. The fix happens in the next round
      and goes back through Q1. The Dev is not involved.
   5. **Regression run.** Only when every story TC passed. First re-run
      `kb test-env lock <story>` (exit 3: stop and release whatever is held).
      Run `git fetch origin`, and read reports from `origin/<default>`, not
      the working tree: `git ls-tree -r --name-only origin/<default> reports/`
      lists them and `git show origin/<default>:reports/<s>/R<n>.md` reads
      one. The closed stories are those whose latest `reports/<s>/R<n>.md`
      there has `Verdict: PASS`. Run their scripts (`tests/<s>/`), with the same clean retry and MCP confirmation. The
      baseline is the newest PASS report whose `> Environment:` names this
      environment, read from its `## Regression` results and commits; with no
      such report there is "no baseline". For each
      confirmed regression failure:
      - Key it `<closed story id>/TC-<k>` and ask the hub:
        `curl -fsS -H "Authorization: Bearer $STRATA_KB_HTTP_TOKEN" "$STRATA_KB_HUB_URL/api/tests/known-failures"`
        (a GET; use exactly this shape; it answers a JSON object whose keys
        are the open known failures). If curl exits non-zero or the answer is
        empty or not a JSON object, **stop the round** and release whatever is
        held (`kb test-env unlock`, `kb claim release <story>`): never treat a
        failed call as "no known failures". If the key is an open known
        failure, it is not a new defect and not attributed to this story: list
        it on the `Known:` line of `## Regression` and move on. Never print
        the token.
      - Otherwise attribute it with `kb test-env changed <story>` (the files
        this story's child PRs changed). It is a **story regression** only
        when both hold: (a) **baseline** — the TC passed in the last recorded
        regression baseline (the last `PASS` round on this environment, with
        each app's commit); (b) **overlap** — the failing page, API route or
        service maps to a file in that list (use the Dev repo's `-code`
        routes/pages and `-svc` services). The guilty child is the one whose
        PR holds the file. With no baseline yet, overlap alone decides.
        Story regression: a defect of this story, `Regression: yes`, with the
        evidence for (a) and (b) written into it. Neither signal, or only
        one: an outside regression, recorded as `RD<k>`, which does not stop
        this story closing. A doubt means outside regression, never a reopen
        on a guess.
   6. **Post-check.** `kb test-env version` again. A changed commit means
      the round is void: `BLOCKED-ENV`. Then `kb test-env unlock`.
   A round whose story TCs failed skips the regression run; its report says
   `Run: no (story TCs failed)`.
9. **Round outcome.**
   | Outcome | When |
   |---|---|
   | `PASS` | every story TC passed, steps 1 and 6 clean |
   | `FAIL` | at least one confirmed story defect (story TC or story regression) |
   | `INCOMPLETE` | no defect, but at least one flaky or script-defect TC |
   | `BLOCKED-ENV` | step 1 or 6 failed |
   Only `PASS` and `FAIL` produce a committed `reports/<story>/R<n>.md`.
   `INCOMPLETE` and `BLOCKED-ENV` go to the local run log only; write the
   reason there, release whatever is still held (`kb test-env unlock`,
   `kb claim release <story>`) and stop. The
   story's status does not change and it is retried later.
10. **Write the report.** `kb claim update <story> --phase report`. `<n>` is
    one more than the highest `reports/<story>/R<n>.md`. Write
    `reports/<story>/R<n>.md` from `docs/templates/test-report.md`. The
    verdict follows the tables: any story FAIL gives `FAIL`, else `PASS`.
    One `### D<k>` per confirmed story failure, with `Guilty:` a child id of
    the story, `Regression: yes|no`, steps to reproduce, expected, actual,
    evidence and environment; a `Regression: yes` defect also carries its
    broken TC, baseline and overlap lines. One `### RD<k>` per outside
    regression, naming the `closed` story and its TC
    (`Story: <closed story id> · TC-<k>`). Evidence images are PNG or WebP
    under `reports/<story>/assets/`. No env var value or credential in the
    text. Write `## Regression` as exactly these lines (a PASS report always
    says `Run: yes`; every key is `<closed story id>/TC-<k>`):

    ```
    ## Regression
    Run: yes
    Failed: ST-0/TC-3, ST-0/TC-4
    Known: ST-0/TC-5
    ```

    or `Run: no (<reason>)` when the regression run was skipped. `Failed: none`
    and `Known: none` when empty. `Failed:` holds every confirmed regression
    failure that is new: each `Regression: yes` defect's broken TC and each
    `RD<k>`'s story and TC; `Known:` holds the keys the hub already knew.
    Run `kb report lint reports/<story>/R<n>.md` until it exits 0.
11. **Q2 review.** Dispatch the `test-report-reviewer` subagent under the
    review contract below. It checks that the verdict follows the evidence,
    every defect was reproduced through MCP and assigned to the right child,
    regression defects are confirmed and attribution is right, flaky tests
    were handled, and no secret leaked. A Q2 doubt on an attribution makes it
    an outside regression. Append each round to the report's `## Review
    record`, and run `kb report lint` again (its last row must be `pass`).
12. **Publish.** `kb claim update <story> --phase publishing`. Run
    `kb report-ingest` and confirm it lists your report and the test cases,
    not as skipped. Check `git branch --show-current` is
    `test/<story>-R<n>`, never the default branch; refuse to commit or push
    otherwise. Commit `tests/<story>/` (without `ticket.md`, which is
    git-ignored) and `reports/<story>/`, push the branch with
    `git push -u origin HEAD`, and open the PR with `kb pr open --title
    "test: <story> R<n> <PASS|FAIL>" --body-file <file>`, the body listing
    the verdict, the defects and the regression result. **Never merge it**:
    a human reviews and merges, and the merge publishes the report through the
    `kb-publish-request` workflow. **Never run `kb publish`.** Then
    `kb claim release <story>`.

## Review dispatch contract (every review in this flow)

Two reviews run here: Q1 (`test-case-reviewer`, step 7) and Q2
(`test-report-reviewer`, step 11).

- The author and the reviewer are NEVER the same subagent. A self-review
  never satisfies a review step.
- A reviewer starts from a fresh context and gets no conversation history —
  hand it only the paths it must read and the constraints that bind it.
- Artefacts move as FILE PATHS, never pasted into the dispatch prompt: the
  test cases, the scripts, the report, the run log. Whatever you paste stays
  in your context for the rest of the session.
- Never pre-judge: a dispatch prompt never tells a reviewer what not to flag
  and never rates a finding's severity for it.
- Name the model on every dispatch — a standard model for authors and
  fixers, the most capable one available for reviewers. Never inherit the
  session default silently.
- Convergence: round 1 is exhaustive; round 2 is verification only — it
  blocks only on round-1 items, regressions introduced by the fix, and any
  BLOCKER. The review passes when no BLOCKER stands and at most 2 SUGGESTED
  remain; every carried SUGGESTED is recorded as a row in `## Review record`.
- A finding goes to a fix subagent (never the reviewer), then to round 2.
- Criteria: `docs/test-review-rubric.md` — its `## Q1 axes` for the
  `test-case-reviewer`, its Q2 axes for the `test-report-reviewer` — then
  `docs/test-review-rubric.local.md`, which wins where they disagree.
  Severity is always BLOCKER / SUGGESTED / NOTE / NITS.
- `## Review record` is a table with the header exactly
  `| Date | Round | Verdict | Reviewer | Coverage | Open gaps |`, one row per
  round; the last row's Verdict is `pass` before the artefact is published
  (`kb report lint` checks the report's).
- Where the runtime cannot dispatch subagents, run the review as its own pass
  that reads ONLY the paths it was handed and reuses nothing it remembers
  from authoring, write up its findings the same way, then PAUSE and hand the
  result to the Tester. A pause is not a stop: it keeps the claim and the
  environment lock. On resume, re-run `kb test-env lock <story>` to refresh
  the lock (exit 3: stop and release whatever is held). The task does not
  advance on a fallback pass; only the Tester's explicit go-ahead does, and
  it is recorded in the `## Review record` row, for example
  `Reviewer: fallback, Tester-approved`.

**Stop.** A BLOCKER still standing after round 2 stops the task for a human:
release whatever is still held (`kb test-env unlock` if the lock is still
taken, `kb claim release <story>`), then say which finding stands and why. The text `AUTO-RESULT: failed test-review`
is reserved for the unattended runner of a later phase: do not write it in
this phase.
