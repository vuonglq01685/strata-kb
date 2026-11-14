Set up the test environment this repo tests against. You ask for each item,
write the declaration, and verify it. The file holds NAMES only; values go to
`.env`.

## Rules

- `.kb/test-env.yaml` holds env var **names only** (`user_env`,
  `password_env`, `url_env`). Secret values — passwords, tokens, DB URLs with
  credentials — go only to `.env`, which is git-ignored. Never put a value in
  the YAML, a commit, a PR or the chat, and never echo a value back: when you
  confirm an item, say the name you stored, not what the user typed.
- The test environment is a shared, non-production system. Refuse a `name` of
  `production` or `prod`, and ask the Tester to list any `protected_urls`.
- DB access is the Tester's own scripts (any engine). kb adds no driver; you
  only record the script paths.

## Steps

1. Read `.kb/test-env.example.yaml` and any existing `.kb/test-env.yaml`
   (keep what is already right). Tell the Tester what is about to be asked.
2. Ask **item by item**, one question at a time, waiting for each answer:
   1. Environment `name` (for example `staging`) and, optionally,
      `protected_urls`.
   2. Each app under test, one per Dev repo the stories touch: `repo`, the
      front-end `url` and/or `api_base`.
   3. Each app's `version_check`: the `url` that returns the deployed commit
      and the JSON `field` that holds it. It is required for unattended runs;
      with none, say a manual run will ask the Tester to confirm the deploy.
   4. The DB: the NAME of the env var holding its URL (`url_env`), and the
      scripts `check` (exit 0 when the DB answers), `reset`, and each named
      seed under `seeds`. Offer to write a missing script, then show it for
      the Tester to read before saving. It must touch only `$<url_env>`.
   5. Each account role (`buyer`, `admin`, …): the NAMES of the user and
      password env vars, declared with the convention `TEST_<ROLE>_USER` and
      `TEST_<ROLE>_PASSWORD` (the login fixture reads exactly those). Ask for
      the values separately (step 4).
   6. `api_auth`: `cookie` or `bearer`.
   7. `retries` (default `3`).
3. Write `.kb/test-env.yaml` from `.kb/test-env.example.yaml`: names only.
4. Write `TEST_FE_URL=<front-end url>` (the `url` of the first app in `apps` that
   has one; not a secret; the scaffolded
   `playwright.config.ts` uses it as `baseURL`) and the secret values the
   Tester gives you to `.env` only, one
   `NAME=value` line each. Append: replace only lines with the same NAME and
   keep every other line (including `STRATA_KB_HUB_URL` and
   `STRATA_KB_HTTP_TOKEN` from `kb mcp-setup`). If `.env` is missing, create
   it. Confirm `.env` is listed in `.gitignore`. Do not print `.env` back.
5. Run `kb test-env check`. It validates the file: names only, no
   secret-looking value, scripts inside the repo. Fix what it prints with the
   Tester and re-run until it passes.
6. Explore the login page with Playwright MCP, only to discover selectors:
   open the app `url`, find the user, password and submit controls by role,
   label or test id. Never type a password or any credential through MCP, as
   tool-call arguments are logged. Fill
   `tests/fixtures/login.ts` with those selectors. The fixture reads the
   credentials from the env vars only. Keep the file in the Tester's repo; it
   is created once and re-running this skill edits it, never recreates it.
7. Run `kb test-env verify`. It prints one `ok` or `FAIL` line per item: each
   app URL, the DB `check`, `reset`, each seed, each version endpoint. Then
   log in as each account with the smoke spec: `npx playwright test
   tests/fixtures/login.smoke.spec.ts` (it reads credentials from env only;
   create-once like the fixture, extend its role list to match the accounts)
   and add one `ok`/`FAIL` line per account.
8. Report every item as `ok` or `FAIL`, with the item name and the one-line
   reason. Never include a credential in a reason. For each `FAIL`, say what
   the Tester fixes (a name, a script, a selector) and offer to re-run steps
   5–7. Finish only when every item is `ok`; otherwise stop and say which
   items remain.
