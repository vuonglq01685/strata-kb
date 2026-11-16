# Strata Quickstart (tester repo)

**Full guide:** https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-tester.en.md
(Tiếng Việt: https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-tester.vi.md)

You test a story end to end: write test cases from its acceptance criteria, script
them in Playwright, run them against a deployed test environment, and publish a
report (`<repo_id>-test`, shown as Test Report on the hub). This repo reads the
knowledge base and tickets; it never changes them.

## Set up (once)

1. **Install and scaffold.** `pip install strata-kb`, then `kb init --kind tester`
   (safe to re-run).
2. **Point at the hub.** In `.kb/config.yaml` fill `hub:`, `intake:`; `repo_id` must
   equal this repo's id in the hub's `federation/registry.yaml`. **Never put a token
   in `hub:` or `intake:`**: the file is committed.
3. **Connect your assistant.** `kb mcp-setup` writes `STRATA_KB_HUB_URL` and
   `STRATA_KB_HTTP_TOKEN` into `.env` (git-ignored). Load it and restart your
   assistant. The `playwright` MCP server is already in `.mcp.json`.
4. **Describe the test environment.** Run `/tester-env-setup`: it writes
   `.kb/test-env.yaml` (env var names only; values live in `.env`) and verifies it.
   `.kb/test-env.example.yaml` shows the shape.

## Plan the testing

5. **Write the test strategy.** Run `/tester-strategy` before the first
   `/tester-test-story`: it writes `docs/test-strategy.md` (what to test first
   and why) and opens a PR. When the stale issue opens (`kb test stale`), run
   `/tester-strategy --amend`. The strategy never blocks `/tester-test-story`.

## Run it unattended (optional)

`kb auto run` can test stories on its own, on the Tester's machine (it needs Chromium and
a `version_check` for every app). An unattended run **merges its own report and strategy
PRs** once `lint` is green, so set up branch protection on `main` first: `lint` required,
code-owner review, and a real owner in `.github/CODEOWNERS`. `kb auto run` refuses until
it is. Turn it on with `kb auto on`, commit `.kb/config.yaml`, then `kb auto run`. If the repo was scaffolded earlier, run `kb upgrade` first to refresh the settings.
Read the guide's Automation section before turning it on:
https://github.com/vuonglq01685/strata-kb/blob/main/docs/src/guide-tester.en.md#4-automation-modes

## Layout

```
.kb/test-env.yaml                the environment, no secret values
.env                             secret values (git-ignored)
tests/<story-id>/test-cases.md   test case specification
tests/<story-id>/tc<NN>.spec.ts  one script per test case
tests/fixtures/login.ts          login fixture
reports/<story-id>/R<n>.md       report of round n
docs/test-strategy.md            priority order, from /tester-strategy
docs/test-review-rubric.md       review criteria (+ .local.md override)
```

Templates: `docs/templates/test-cases.md`, `docs/templates/test-report.md`,
`docs/templates/test-strategy.md`.
