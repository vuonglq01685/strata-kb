You are adding the one CI check the Dev templates do not ship: a workflow
that runs THIS repo's own tests. `kb-pr-lint.yml`, `kb-doctor.yml` and
`kb-code.yml` check the PR text, the citations and the code knowledge; none
of them runs the product's tests, so "CI is green" says nothing about the
code until this workflow exists. You write `.github/workflows/kb-test.yml`,
make the tests pass in it, and land it through a pull request.

*Counterpart in the superpowers plugin: none — this skill is strata-kb
specific.*

## Steps

- **Look first** — list `.github/workflows/`. A workflow other than the
  scaffolded `kb-*.yml` files whose `run:` steps run the repo's tests on
  `pull_request` already does this job: do not add a second. Add the
  one-line comment `# kb-test: runs the repo's tests on pull requests` at
  the top of that file, so the tooling that looks for the marker finds it,
  and carry on from the PR step with only that change. A `kb-test.yml`
  that exists and runs the tests means the work is already finished.
- **Choose the languages** — read `langs:` in `.kb/config.yaml`; when the
  key is missing, look for the manifests `kb init` looks for, at the root
  and up to three levels down (`package.json`, `pyproject.toml`,
  `go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle`, `*.csproj`,
  `composer.json`, `pubspec.yaml`, `Package.swift`). `e2e-playwright` needs
  a running app, so leave it out and say so under `## Notes`. A manifest
  below the root becomes a `working-directory:`.
- **Choose the commands** — per language, take the test command from
  `docs/conventions/<lang>/testing.md` (`docs/conventions/<lang>.local.md`
  wins when it overrides it), then confirm it against the manifest and the
  README: `pytest`, `npm test`, `go test ./...`, `cargo test`, `mvn test`
  or `gradle test`, `dotnet test`, `vendor/bin/phpunit`, `flutter test` or
  `dart test`, `swift test`. The job also needs the setup the tests need and
  nothing else: the language's `actions/setup-*` step on the version the
  manifest names, and the repo's own install command (`pip install -e .`,
  `npm ci`, `go mod download`, …).
- **Write `.github/workflows/kb-test.yml`** — one job per language, named
  `test-<lang>`, in this shape:

      name: kb-test
      on:
        pull_request:
        push:
          branches: [main]
      permissions:
        contents: read
      jobs:
        test-python:
          runs-on: ubuntu-latest
          steps:
            - uses: actions/checkout@v4
              with:
                persist-credentials: false
            - uses: actions/setup-python@v5
              with:
                python-version: "3.12"
            - run: pip install -e ".[dev]"
            - run: pytest -q

  `main` is the default branch unless an existing workflow's `branches:`
  list names another. The file name and `name: kb-test` stay as written:
  the auto-mode runner looks for `kb-test` in `.github/workflows/` to know
  the check exists, and branch protection keys on the job names.
- **Run the tests locally first** — run every command you chose, from the
  directory the job uses, and read the result before anything is committed.
  Red because the environment lacks something (a dependency, a setup
  step): fix the workflow. Red because the code is wrong: stop and report
  it; never edit a test to make it pass, and never skip or deselect tests
  to get a green run.
- **Branch and PR** — create the branch `auto/kb-test` from the default
  branch, commit `.github/workflows/kb-test.yml`, push, and open a PR
  whose description follows `.github/pull_request_template.md` (`kb pr
  lint` checks it): **Ticket** — `none: add the test workflow`;
  **Changes** — the workflow, the languages and the commands; **Testing** —
  a fenced block holding the local test command line and its summary
  lines, then `Blocking: No` as the last line, written after you re-read
  the workflow once for secrets, `pull_request_target` and write
  permissions and found none; **Notes** — what was left out (for example
  `e2e-playwright`).
- **Wait for the new check** — the PR runs the new `kb-test` workflow on
  itself. It must be green before the PR merges. When the PR is yours to
  merge, that is the rule; when a human asked for this skill, the PR is
  left for the human to merge, and you say so and name the PR.

## Hard rules

- Never edit, skip, or deselect a test to get a green run; diagnose the
  cause.
- Never add a secret, `pull_request_target`, or a `permissions:` scope
  beyond `contents: read`; the workflow only runs the repo's own tests.
- Never touch the scaffolded `kb-*.yml` workflows, and never rename
  `kb-test.yml` or its `name: kb-test`.
- Never work on the default branch; never push to a protected branch.
- Pin each third-party action to a version tag, as the other workflows do;
  never use a branch ref.

## Next step — ALWAYS end your response with this block

    ## Next step

    → 1. <next step> — <what it does>   (next in flow)
      2. <alternative> — <how>
      3. <stop/park> — <where the work is saved>

    State: workflow <✅ written|⬜ missing> · local tests <✅ green|❌ red|⬜ not run> · PR <✅ opened|✅ merged|⬜ not opened>

Option 1 is the next step in flow: run the tests, open the PR, wait for the
check, merge. A blocker takes option 1 instead and says so.

## Auto mode

Run `kb auto status --json`. When `enabled` is false, this section does not apply. When true, the rules below replace the human gates named in them.

The runner starts this skill as `/dev-test-workflow` when no workflow in `.github/workflows/` names `kb-test`, before it starts any ticket: every later PR needs this check green. Nobody answers questions during the run: a step above that leaves the PR "for the human to merge" is yours to carry out, under the rules below. Every step and every hard rule not named here stays as written.

**Decisions.** Write each decision as one `**Auto decision:**` line: what you checked, the options, the choice, and why (the languages, each command and where it came from, what was left out). Put the lines in the PR description's `## Notes`.

**A denied command.** A command the permission system denies ends the run with `AUTO-RESULT: failed command-denied <command>`. Never work around a denial: no other shell, no edit of the settings. The one exception is a denied `kb` command that has a `strata-kb` MCP tool: it counts as no CLI: run the MCP tool and carry on.

**Already finished.** The runner re-runs a task after a crash, so check first. A `kb-test.yml` (or a workflow carrying the `# kb-test` marker) that runs the repo's tests on `pull_request` and is on the default branch means the work is finished; `kb pr find --head auto/kb-test --state merged --json` shows the merge. When the file is missing from your working tree, create the branch as in **Branch first** below (`FETCH_HEAD` already holds the merged file) and end `AUTO-RESULT: done`. With no merged PR, look for an open one (`--state open`). An open PR means a crashed run: `git fetch origin && git switch auto/kb-test`, then `git pull origin auto/kb-test`, and continue at step 3 of the branch rule below (the CI step).

- **Look first: a workflow already runs the tests** → add the marker comment, then commit and open the PR as below with that single change, and log the workflow's name in an Auto decision line.
- **Run the tests locally first: red because the code is wrong — "stop and report it"** → no PR is opened. End `AUTO-RESULT: failed tests-red <the failing test names>`; the runner does not go on to tickets while the suite is red.
- **Choose the languages: no manifest and no `langs:`** → there is nothing to run. End `AUTO-RESULT: failed no-tests`.
- **Branch and PR: "the PR is left for the human to merge"** → you open it and merge it, by the branch rule below.

**Branch first.** Before you write or run anything, create the branch with `git fetch origin main && git switch -c auto/kb-test FETCH_HEAD`; never check out `main`. When `auto/kb-test` already exists, `git switch auto/kb-test` and bring it up to date with `git fetch origin main && git merge FETCH_HEAD`.

**The branch rule**, once the tests have run green locally.

1. Commit the workflow (stage it by name) with a message `<type>: <description>`, then `git push -u origin HEAD`.
2. Open the PR with `kb pr open --title "ci: add the kb-test workflow" --body "<the description from the Branch and PR step>"`. Run `kb pr lint` on the body first when you can, so `kb-pr-lint` starts green.
3. Wait for the checks with `kb pr checks --watch`. The jobs of the test workflow (`kb-test.yml`, or the workflow carrying the `# kb-test:` marker) must be among them, and green. If a check is red, read the failure (`gh run view --log-failed`), fix the workflow, commit, `git push origin HEAD`, and watch again: up to 2 rounds in all. Still red after the second round: end `AUTO-RESULT: failed ci-red <pr-url>`. Never merge on red or pending checks.
4. Every check green: `kb pr merge --squash --delete-branch`. Only when the merge is refused for want of an approving review you cannot give, use `kb pr merge --squash --admin --delete-branch` instead, and only after every required check is green. After any merge error, run `kb pr view --json` before you end `failed`: `kb pr merge` can report an error after the merge went through. A merged PR is a success.
5. The workflow lives outside `.kb/`, so there is nothing to `kb publish`.

### Result line

End the reply with exactly one line, and make it the last line. Nothing follows it: no code fence, no markdown, no closing remark. The `## Next step` block comes first. It has one of three forms:

- `AUTO-RESULT: done` — the workflow is merged and its check was green on its own PR, or the work was already finished. Write no text after `done`; always give a reason after `failed`.
- `AUTO-RESULT: blocked-qa Q<id>[,Q<id>...]` — never ends this skill, which asks the BA nothing.
- `AUTO-RESULT: failed <reason>` — anything else: `ci-red <pr-url>` after 2 fix rounds, `tests-red <the failing test names>`, `no-tests`, or `command-denied <command>`. The reason goes on the same line.
