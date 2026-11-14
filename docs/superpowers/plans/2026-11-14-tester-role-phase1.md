# Tester Role — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth repo kind `tester` that declares a test environment, writes linted test case specs and test reports, publishes them as `<repo_id>-test`, shows derived test statuses and a Test Report menu on the hub — run by hand (no `kb auto` yet).

**Architecture:** Python domain modules per concern (`testenv`, `testcases`, `testreport`, `testingest`, `testflow`), each with a typer sub-app in `cli.py` in the existing lazy-import style. Test status is an **overlay field** on `missionnext.StoryStatus` (`test_status`), never a change of `status`, so every existing `"done"` consumer keeps working. Claims gain a `role` column; an environment lock lives next to claims. Skills follow the stub + `bodies/` pattern.

**Tech Stack:** Python ≥3.11, typer, pydantic v2, PyYAML, starlette/jinja2, sqlite3, pytest. No new Python dependency.

**Spec:** `docs/superpowers/specs/2026-11-14-tester-role-design.md` (sections D1–D10; phase 1 of "Phases"). D11 (Dev/BA side) and D12 (`kb auto`) are phases 2–3, not here.

## Global Constraints

- Kind name `tester` (never `qa`); hub kind `tester`; hub role `tester`; menu label `Test Report`; hub document id `<repo_id>-test`, title `<repo_id> — tests`, tags `test`, `generated`.
- Statuses (strings, exact): `testing`, `closed`, `reopened`, `fix-done`. `closed` is final (O15).
- Report verdicts committed/published: only `PASS` | `FAIL`. `INCOMPLETE` and `BLOCKED-ENV` never appear in a committed report.
- `.kb/test-env.yaml` holds env var **names** only; secret values live in `.env` (git-ignored) or CI secrets.
- `retries` default `3`.
- Evidence images: PNG/WebP only, under `reports/<story-id>/assets/`, rewritten to `assets/<sha256>.<ext>` at ingest.
- Review convergence (Q1/Q2): round 1 exhaustive, round 2 verification only; pass when no BLOCKER and ≤2 SUGGESTED; still blocked → stop for a human.
- No new dependency in `pyproject.toml`. No import cycle (`tests/test_layering.py`). `kinds.py` imports only `errors`.
- Every CLI command: domain function returns an int exit code; errors are one red line + exit 1 (`cli.py` style, `_exit_with`).
- Version 1.36.0 → 1.37.0; CHANGELOG entry.

## Decisions this plan makes inside the spec's room

- **Known failures are derived, not stored.** D5 says "the hub keeps a known-failure row". This plan derives the open known-failure set from published `-test` reports (`testflow.known_failures`), the same way `done` is derived. Reason: one source of truth, nothing to write on publish. Behaviour is the spec's.
- **`test_status` overlay field** instead of rewriting `status` (see Architecture).
- **`Polarity` field** added to each TC (`positive` · `negative` · `boundary`) so lint can check "≥1 positive per AC" deterministically; "AC with a constraint needs a negative/boundary TC" is a lint **warning** when the AC text has a digit, and a Q1 rubric item otherwise.
- Login check of `verify` (D2) runs in the skill through Playwright, not in Python.

## Review Focus

1. A `-test` doc on the hub whose report names a story id that no BA plan holds → status overlay must skip it, the Test Report page must still list it (marked "unknown story"), never 500.
2. A hub with an existing `users.db` / `claims.db` created by 1.36.0 (old CHECK, no `role` column) → first open migrates in place; no data loss; a second open is a no-op.
3. `.kb/test-env.yaml` containing a real credential (`postgres://u:p@h/db`, a 40-char token) in any field → load refuses with the field name, never prints the value.
4. A report image path that is a symlink, `..`, absolute, a URL or outside `assets/` → ingest skips that report with a reason; publish never copies a file from outside the repo.
5. Two reports of different stories listing the same new regression key → the Test Report page shows one bug candidate and marks the later one `duplicate of`.

---

### Task 1: Kind `tester` in the vocabulary, config and CLI

**Files:**
- Modify: `src/strata_kb/kinds.py` (constants, `_CONFIG_TO_HUB`, `infer_kind`, new `is_test_doc`)
- Modify: `src/strata_kb/config.py:76` (`kind` Literal)
- Modify: `src/strata_kb/initcmd.py:22-27` (`KIND_TESTER`, `KINDS`)
- Modify: `src/strata_kb/cli.py:166-250` (`RepoKind`, `KIND_DESCRIPTIONS`, `_resolve_kind` prompt/error strings), `:290-300` (registry prompt "kb, ba, dev, tester"), `:335-341` (help)
- Modify: `src/strata_kb/doctor/checks/hub.py:731` (message lists `tester`), `src/strata_kb/dockersetup.py:90`, `src/strata_kb/doctor/remote.py:44` (`REMOTE_KINDS` gains `tester`)
- Test: `tests/test_kinds.py`, `tests/test_init.py` (update pinned strings at :87, :208, :1018-1029, :2221, :3305)

**Interfaces:**
- Produces: `kinds.TESTER = "tester"`; `kinds.HUB_KINDS = (KB, BA, DEV, TESTER)`; `kinds.MENU[TESTER] = "Test Report"`; `kinds.TEST_TITLE_SUFFIX = "— tests"`; `kinds.is_test_doc(title: str, tags: Iterable[str]) -> bool`; `initcmd.KIND_TESTER = "tester"`.

- [ ] **Step 1: Write the failing tests**

```python
def test_hub_kind_maps_tester():
    assert kinds.hub_kind("tester") == "tester"

def test_test_doc_is_recognised_and_infers_tester():
    assert kinds.is_test_doc("acme — tests", ["test", "generated"])
    assert not kinds.is_test_doc("acme — tests", ["test"])
    # infer_kind over an index holding one test doc returns TESTER
```

Update the pinned strings in `tests/test_init.py` to `hub|child|ba|dev|tester` and "five kinds".

- [ ] **Step 2: Run** `pytest tests/test_kinds.py tests/test_init.py -q` — Expected: FAIL on the new asserts.
- [ ] **Step 3: Implement** the constants and branches above. `infer_kind`: a doc with `is_test_doc` → `TESTER` (checked before the `-code`/`-svc` rule). `KBConfig.kind` Literal gains `"tester"`.
- [ ] **Step 4: Run** `pytest tests/test_kinds.py tests/test_init.py tests/test_registrykind.py tests/test_doctor_hubkind.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: add tester repo kind to the kind vocabulary`

### Task 2: `kb init --kind tester` scaffold

**Files:**
- Modify: `src/strata_kb/initcmd.py` (`TESTER_TEMPLATES`, `TESTER_LOCAL_OVERRIDES`, `scaffold_tester_local_overrides`, `template_map`, `SCAFFOLDED_WORKFLOW_NAMES`, `init_repo` post-processing, `_SETTINGS_REL` branches `kind in (KIND_BA, KIND_DEV, KIND_TESTER)`)
- Modify: `src/strata_kb/upgradecmd.py:14,43` (allow `KIND_TESTER`)
- Modify: `src/strata_kb/cli.py` init next-steps block (a `tester` branch: "run /tester-env-setup")
- Create in `src/strata_kb/templates/init/`: `config-tester.yaml`, `QUICKSTART-tester.md`, `mcp-tester.json`, `cursor-mcp-tester.json`, `codeowners-tester`, `test-review-rubric.md`, `test-review-rubric-local-stub.md`, `test-cases-template.md`, `test-report-template.md`, `test-env.example.yaml`, `playwright-login-fixture.ts`
- Test: `tests/test_init_tester.py`

**Interfaces:**
- Consumes: `initcmd.KIND_TESTER` (Task 1).
- Produces: scaffolded paths (exact): `.kb/config.yaml`, `QUICKSTART-TESTER.md`, `.mcp.json`, `.cursor/mcp.json`, `.claude/settings.json`, `docs/test-review-rubric.md`, `docs/templates/test-cases.md`, `docs/templates/test-report.md`, `.kb/test-env.example.yaml`, `tests/fixtures/login.ts`; local overrides `docs/test-review-rubric.local.md`, `.github/CODEOWNERS`. Gitignore lines: `.kb/*-test/`, `.kb/auto/`, `.env`, `test-results/`, `playwright-report/`, `.kb/runlog/`, `tests/*/ticket.md`. Skill wrappers are added by Task 12.

- [ ] **Step 1: Write the failing tests**

```python
def test_init_tester_scaffolds_exactly_the_tester_set(tmp_path):
    report = init_repo(tmp_path, "tester")
    assert sorted(report.created) == sorted(
        expected_files("tester") + list(initcmd.TESTER_LOCAL_OVERRIDES) + [".gitignore"])

def test_tester_config_has_kind_and_mcp_has_playwright(tmp_path):
    init_repo(tmp_path, "tester")
    assert "kind: tester" in (tmp_path / ".kb/config.yaml").read_text()
    mcp = json.loads((tmp_path / ".mcp.json").read_text())
    assert set(mcp["mcpServers"]) == {"strata-kb", "playwright"}

def test_tester_gitignore_hides_env_and_playwright_output(tmp_path):
    init_repo(tmp_path, "tester")
    gi = (tmp_path / ".gitignore").read_text()
    for line in (".env", "test-results/", "playwright-report/", ".kb/*-test/", "tests/*/ticket.md"):
        assert line in gi.splitlines()

def test_upgrade_accepts_a_tester_repo(tmp_path): ...  # mirrors tests/test_upgrade.py ba case
```

- [ ] **Step 2: Run** `pytest tests/test_init_tester.py -q` — Expected: FAIL (`kind must be one of`).
- [ ] **Step 3: Implement** the maps. `mcp-tester.json` = `mcp-child.json` plus `"playwright": {"command": "npx", "args": ["@playwright/mcp@<pinned>", "--browser", "chromium"]}`; pin = output of `npm view @playwright/mcp version` at implementation time, written literally. Templates `test-cases-template.md` and `test-report-template.md` are the D4/D6 skeletons of the spec verbatim, with the `Polarity` row added to each TC table after `Technique`. `test-review-rubric.md` follows `pr-review-rubric.md`'s shape: severity ladder, `## Q1 axes`, `## Q2 axes` (the D8 table items as checkboxes).
- [ ] **Step 4: Run** `pytest tests/test_init_tester.py tests/test_init.py tests/test_template_bodies.py tests/test_upgrade.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: scaffold tester repos with kb init --kind tester`

### Task 3: `testenv` — load and validate `.kb/test-env.yaml`

**Files:**
- Create: `src/strata_kb/testenv.py`
- Modify: `src/strata_kb/cli.py` (`test_env_app = typer.Typer(...)`, `app.add_typer(test_env_app, name="test-env")`, command `check`)
- Test: `tests/test_testenv.py`

**Interfaces:**
- Produces:
  - pydantic models (`extra="forbid"`): `VersionCheck(url: str, field: str)`; `App(repo: str, url: str = "", api_base: str = "", version_check: VersionCheck | None = None)`; `Db(url_env: str, check: str, reset: str, seeds: dict[str, str] = {})`; `Account(user_env: str, password_env: str)`; `TestEnv(name: str, apps: list[App], db: Db, accounts: dict[str, Account], api_auth: Literal["cookie","bearer"] = "cookie", retries: int = 3, protected_urls: list[str] = [])`.
  - `class TestEnvError(KbError)`.
  - `testenv.ENV_FILE = ".kb/test-env.yaml"`.
  - `testenv.secret_like(value: str) -> bool` (credential detector; reused by Task 7).
  - `testenv.load(repo_root: Path) -> TestEnv` (raises `TestEnvError`).
  - `testenv.check(repo_root: Path) -> int` (CLI body; prints `test-env: OK` or one line per problem).

- [ ] **Step 1: Write the failing tests**

```python
def test_load_valid_env(tmp_path): ...            # example file → TestEnv, retries == 3
def test_refuses_credential_url_and_names_field(tmp_path):
    # apps[0].url = "postgres://u:p@h/db"
    with pytest.raises(TestEnvError, match=r"apps\[0\]\.url") as e: load(tmp_path)
    assert "u:p" not in str(e.value)
def test_refuses_long_token_in_any_field(tmp_path): ...   # 40-char [A-Za-z0-9_-] run → error
def test_env_var_names_must_be_upper_snake(tmp_path): ... # url_env "test_db" → error
def test_script_paths_must_stay_in_repo(tmp_path): ...    # reset "../x.sh", "/abs.sh" → error
def test_missing_file_says_run_tester_env_setup(tmp_path): ...
```

- [ ] **Step 2: Run** `pytest tests/test_testenv.py -q` — Expected: FAIL (module missing).
- [ ] **Step 3: Implement.** Secret shape = URL with `user:pass@` userinfo, or any `[A-Za-z0-9_\-]{32,}` run; scan every string leaf of the raw YAML before model validation; error text names the path (`apps[0].url`) only. Env var names match `^[A-Z][A-Z0-9_]*$`. Script paths: relative, no `..`, inside `repo_root`.
- [ ] **Step 4: Run** `pytest tests/test_testenv.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb test-env check validates the declared test environment`

### Task 4: `testenv` — verify, reset, seed, version

**Files:**
- Modify: `src/strata_kb/testenv.py`
- Modify: `src/strata_kb/cli.py` (commands `verify`, `reset`, `seed <name>`, `version`)
- Test: `tests/test_testenv_run.py`

**Interfaces:**
- Consumes: `TestEnv`, `load` (Task 3); `httpio.request(method, url, headers, body=None, timeout=60) -> tuple[int, bytes]`; `mcpsetup.read_env_value(repo_root, var) -> str`.
- Produces:
  - `testenv.SCRIPT_TIMEOUT = 600`, `testenv.HTTP_TIMEOUT = 15`.
  - `testenv.app_commits(env: TestEnv, http=httpio.request) -> dict[str, str]` (repo → commit; raises `TestEnvError` naming the repo when a check fails or the field is missing).
  - `testenv.run_script(repo_root: Path, env: TestEnv, script: str, run=subprocess.run) -> int` — refuses (`TestEnvError`) when `env.name.lower() in {"production","prod"}` or the DB URL value is in `env.protected_urls`; runs `["bash", script]`, `cwd=repo_root`, `timeout=SCRIPT_TIMEOUT`, env = `os.environ` + `{url_env: value}` where value comes from `os.environ` then `.env`; missing value → `TestEnvError("<url_env> is not set")`.
  - `testenv.verify(repo_root, http=..., run=...) -> int` — FE `url` answers 2xx/3xx, `api_base` answers <500, `db.check` exits 0, `db.reset` exits 0, every seed exits 0, every `version_check` returns a commit. One line per item `ok|FAIL <item>: <reason>`, exit 1 on any FAIL. Account login is not checked here (the skill does it).
  - CLI: `kb test-env verify|reset|seed <name>|version` (`version` prints `repo commit` lines).

- [ ] **Step 1: Write the failing tests** (fake `http`/`run` callables; no network)

```python
def test_app_commits_reads_the_field(): ...           # {"commit":"abc"} → {"shop-fe":"abc"}
def test_version_check_missing_field_names_repo(): ...
def test_run_script_refuses_production(tmp_path): ...
def test_run_script_refuses_protected_url(tmp_path, monkeypatch): ...
def test_run_script_passes_only_url_env_from_dotenv(tmp_path): ...  # env has TEST_DB_URL from .env
def test_verify_prints_each_item_and_exits_1_on_any_fail(tmp_path, capsys): ...
```

- [ ] **Step 2: Run** `pytest tests/test_testenv_run.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as specified. `version_check` JSON field lookup supports dotted paths (`build.git_sha`).
- [ ] **Step 4: Run** `pytest tests/test_testenv_run.py tests/test_testenv.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb test-env verify, reset, seed and version`

### Task 5: Deploy check and story change set (GitHub, no clone)

**Files:**
- Create: `src/strata_kb/testdeploy.py`
- Modify: `src/strata_kb/cli.py` (`kb test-env deployed <story>`, `kb test-env changed <story>`)
- Test: `tests/test_testdeploy.py`

**Interfaces:**
- Consumes: `testenv.app_commits`, `testenv.load`; `ticketfetch.find(hub, ref) -> (repo, doc, path)`; `planparents._children(text, parent_id)` (children + repo); `federation.load_federation(federation_dir)` → `FederatedRepo.meta.source_commit`, `.meta.source_url`; `ghapp.repo_full_from_url(url) -> str`; `ghrest.api(root, method, path) -> Any`.
- Produces:
  - `testdeploy.story_repos(hub, story: str) -> dict[str, list[str]]` (Dev repo id → child ticket ids; unsplit story → its target repo).
  - `testdeploy.deployed(hub, env: TestEnv, story, *, api=ghrest.api, root: Path) -> list[str]` — empty = deployed; else one reason per repo (`<repo>: env at <c1>, publish at <c2> not deployed yet` / `<repo>: no version_check` / `<repo>: not published`). Rule: GitHub `repos/<slug>/compare/<source_commit>...<env_commit>` `status` in `{"identical","ahead"}`.
  - `testdeploy.changed_files(hub, story, *, api=ghrest.api, root) -> dict[str, list[str]]` (child id → files of its merged PRs, found by `search/issues?q=repo:<slug>+is:pr+is:merged+"<child id>"` then `repos/<slug>/pulls/<n>/files`).
  - CLI exits: `deployed` 0 = deployed, 4 = not yet (prints reasons), 1 = error.

- [ ] **Step 1: Write the failing tests** (fake `api`, hub from `make_fed_entry` + `publish_ba` fixtures)

```python
def test_deployed_when_env_descends_from_publish(...): ...   # compare status "ahead" → []
def test_not_deployed_when_behind(...): ...                  # "behind" → one reason naming repo
def test_split_story_checks_every_child_repo(...): ...
def test_changed_files_maps_child_to_pr_files(...): ...
```

- [ ] **Step 2: Run** `pytest tests/test_testdeploy.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as specified; `planparents._children` is private — expose `planparents.children(text, parent_id)` as a public alias in this task.
- [ ] **Step 4: Run** `pytest tests/test_testdeploy.py tests/test_planstatus_parents.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb test-env deployed and changed for a story`

### Task 6: Test case spec parser and `kb testcase lint`

**Files:**
- Create: `src/strata_kb/testcases.py`
- Modify: `src/strata_kb/ticket.py` (new `alternate_flows(text) -> list[str]`)
- Modify: `src/strata_kb/cli.py` (`testcase_app`, command `lint <file> [--ticket PATH] [--hub] [--json]`)
- Test: `tests/test_testcases.py`, `tests/test_ticket.py` (alternate flows)

**Interfaces:**
- Consumes: `lintcore.ac_items(text)`, `lintcore.AC_ID_RE`, `lintcore.section_body`, `lintcore.table_rows`, `lintcore.table_column`, `lintcore.LintReport`, `doctor.Issue`; `planrev.parse_revision(text) -> int | None`.
- Produces:
  - `ticket.alternate_flows(text: str) -> list[str]` — visible list items (`-`/`*`/`1.`) under `### Alternate / exception flows` inside `## Use cases`, `[]` when absent.
  - `@dataclass(frozen=True) TestCase(tc_id: str, title: str, fields: dict[str, str])` (keys exactly: `Objective, Type, Priority, Technique, Polarity, Preconditions, Test data, Steps, Expected result, Script, Automation`).
  - `@dataclass(frozen=True) CaseSpec(story: str, children: tuple[str, ...], revision: int | None, trace: dict[str, tuple[str, ...]], cases: tuple[TestCase, ...], flows: dict[str, tuple[str, ...]])` — `flows` = optional `## Alternate flows coverage` table (flow text → TC ids).
  - `testcases.parse(text: str) -> CaseSpec`.
  - `testcases.lint(text: str, ticket_text: str, *, spec_dir: Path) -> LintReport` — errors: missing heading/field, placeholder left (`<…>` or `…` only), AC without TC, AC without a `positive` TC, TC citing unknown AC, flow without TC, `Script` path missing on disk or not under `spec_dir`, script file under `spec_dir` named by no TC, `Ticket revision` ≠ ticket's `> Revision:`. Warning: AC whose text has a digit and no `negative`/`boundary` TC. Label `TC`.
  - CLI: `--ticket` reads a local fetched ticket (default `tests/<story>/ticket.md`); `--hub` fetches via `ticketfetch`. Exit 0 PASS / 1 FAIL.

- [ ] **Step 1: Write the failing tests** (build spec text from `docs/templates/test-cases.md`; ticket via `tests.test_ticketlint._build_ticket`)

```python
def test_clean_spec_passes(tmp_path): ...
def test_ac_without_positive_tc_is_error(tmp_path): ...
def test_alternate_flow_without_tc_is_error(tmp_path): ...
def test_orphan_script_and_missing_script_are_errors(tmp_path): ...
def test_revision_mismatch_is_error(tmp_path): ...
def test_digit_ac_without_boundary_is_warning(tmp_path): ...
def test_alternate_flows_parses_list_under_use_cases(): ...
```

- [ ] **Step 2: Run** `pytest tests/test_testcases.py tests/test_ticket.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** same — Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb testcase lint checks test case specs against the ticket`

### Task 7: Test report parser and `kb report lint`

**Files:**
- Create: `src/strata_kb/testreport.py`
- Modify: `src/strata_kb/cli.py` (`report_app`, `kb report lint <file> [--json]`)
- Test: `tests/test_testreport.py`

**Interfaces:**
- Consumes: `lintcore.section_body`, `table_rows`, `table_column`, `LintReport`; `buglint.image_problems(src, stem, base_dir)`; `mcpsetup.read_env_value`.
- Produces:
  - `VERDICTS = ("PASS", "FAIL")`.
  - `@dataclass(frozen=True) Defect(defect_id: str, symptom: str, guilty: str, regression: bool, broken_tc: str = "", baseline: str = "", overlap: str = "")`.
  - `@dataclass(frozen=True) RegressionDefect(rd_id: str, symptom: str, story: str, tc: str)` with `key` property `f"{story}/{tc}"`.
  - `@dataclass(frozen=True) Report(story: str, round: int, verdict: str, env_name: str, commits: dict[str, str], date: str, results: tuple[tuple[str, str, str], ...], defects: tuple[Defect, ...], regression_ran: bool, regression_failed: tuple[str, ...], known: tuple[str, ...], regression_defects: tuple[RegressionDefect, ...], review_passed: bool)` — `results` rows = (AC, TC, PASS|FAIL); `regression_failed` = keys `<story>/TC-<k>`; `known` = keys listed as `known:`.
  - `testreport.parse(text: str) -> Report`.
  - `testreport.lint(text: str, *, report_dir: Path, story_children: tuple[str, ...], repo_root: Path) -> LintReport` — D6 rules: headings; verdict ∈ VERDICTS and consistent (any FAIL row or any defect → FAIL, else PASS); every defect `guilty` ∈ `story_children` (or the story itself when unsplit); every defect has `Regression: yes|no`, every `yes` has `Broken TC`, `Baseline` (or `no baseline`), `Overlap`; every RD names a story ≠ this story; images pass `image_problems(src, "assets", report_dir)`; no `.env` value (≥8 chars) and no credential shape (Task 3's detector, reused) in the text; `## Review record` last row verdict `pass` else error "Q2 has not passed". Label `REPORT`.

- [ ] **Step 1: Write the failing tests** (fixture report from `docs/templates/test-report.md`)

```python
def test_pass_report_parses_and_lints_clean(tmp_path): ...
def test_fail_row_with_pass_verdict_is_error(tmp_path): ...
def test_incomplete_verdict_is_refused(tmp_path): ...
def test_regression_yes_defect_needs_baseline_and_overlap(tmp_path): ...
def test_guilty_child_must_belong_to_story(tmp_path): ...
def test_dotenv_value_in_report_is_error_without_echoing_it(tmp_path): ...
def test_image_outside_assets_is_error(tmp_path): ...
def test_review_not_passed_is_error(tmp_path): ...
```

- [ ] **Step 2: Run** `pytest tests/test_testreport.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement**, calling `testenv.secret_like` for the credential scan.
- [ ] **Step 4: Run** `pytest tests/test_testreport.py tests/test_testenv.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb report lint checks test reports`

### Task 8: `kb report-ingest` and publish refresh

**Files:**
- Create: `src/strata_kb/testingest.py`
- Modify: `src/strata_kb/cli.py` (`@app.command(name="report-ingest")`, `_refresh_tester_doc(kb_dir)` beside `_refresh_ba_plan` at ~:843, call at ~:2743 when `plan.refresh_test`)
- Modify: `src/strata_kb/publish.py:1339,1374` (`PublishPlan.refresh_test = cfg.kind == "tester"`)
- Test: `tests/test_testingest.py`, `tests/test_publish_plan.py` (one case)

**Interfaces:**
- Consumes: `testcases.lint/parse`, `testreport.lint/parse`; `planingest` helpers by pattern (not import of privates): `codeingest.types.CodeSection`, `codeingest.core._write_group`, `_render_group`, `_upsert_index_entry`, `_head_commit`, `_head_date`; `buglint.rewrite_images`; `models.Manifest`, `models.SectionEntry`, `models.save_yaml_model`; `kinds.TEST_TITLE_SUFFIX`.
- Produces:
  - `class TestIngestError(KbError)`; `@dataclass TestIngestReport(doc_id: str, published: list[str], skipped: list[tuple[str, str]], files_written: list[str])`.
  - `testingest.run(repo_root: Path, kb_dir: Path, repo_id: str, tests_dir: Path, reports_dir: Path, children_of: Callable[[str], tuple[str, ...]]) -> TestIngestReport` — pure function of the tree. Doc dir `kb_dir/f"{repo_id}-test"`; one group per story (`planstatus.safe_name` guard); sections `f"{story}.cases"` (from `test-cases.md`) and `f"{story}.R{n}"` (each `R<n>.md`, ascending). Ship only lint-clean files (offline lint, `children_of` supplies children); a story's reports ship only if its cases ship. Section summary: cases → `"<k> test cases"`, report → `"R<n> <verdict> — <passed>/<total>"`. Images: every markdown image in the report, rewritten to `assets/<sha256>.<ext>`, symlink/outside-folder refusal as `planingest._attach`; `<doc_dir>/assets/` holds exactly the wanted set. Manifest title `f"{repo_id} {TEST_TITLE_SUFFIX}"`, index tags `["test","generated"]`. Refuses a doc dir whose manifest title lacks the suffix.
  - CLI `kb report-ingest [--repo-root .] [--kb-dir .kb] [--tests-dir tests] [--reports-dir reports] [--json]`; `children_of` reads `tests/<story>/ticket.md` via `planparents.children`.

- [ ] **Step 1: Write the failing tests**

```python
def test_story_group_has_cases_then_rounds(tmp_path): ...
def test_report_skipped_when_cases_fail_lint(tmp_path): ...
def test_images_hashed_into_assets_and_refs_rewritten(tmp_path): ...
def test_symlinked_image_skips_report_with_reason(tmp_path): ...
def test_output_is_deterministic(tmp_path): ...        # two runs → identical bytes
def test_tester_publish_plan_refreshes_test_doc(tmp_path): ...  # test_publish_plan style
```

- [ ] **Step 2: Run** `pytest tests/test_testingest.py tests/test_publish_plan.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** same plus `tests/test_publish_allowlist.py` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb report-ingest builds the <repo>-test hub document`

### Task 9: Claims — `role` column, Tester phases, environment lock

**Files:**
- Modify: `src/strata_kb/ticketclaim.py` (schema, migration, `Claim.role`, `take(..., role="dev")`, `held(..., role="")`, `TESTER_PHASES`, env lock)
- Modify: `src/strata_kb/web/claim_api.py` (body `role`; parent story allowed when `role == "tester"`; routes `/api/env-locks`)
- Modify: `src/strata_kb/claimclient.py`, `src/strata_kb/claimcmd.py`, `src/strata_kb/cli.py` (claim role from config kind: `tester` → `"tester"`, else `"dev"`; `kb test-env lock|unlock`)
- Test: `tests/test_ticketclaim.py`, `tests/test_api_claims.py`, `tests/test_claimclient.py`

**Interfaces:**
- Produces:
  - `ticketclaim.ROLES = ("dev", "tester")`; `TESTER_PHASES = ("claimed","cases","scripts","run","report","review","publishing")`; `update()` validates phase against `PHASES` for `dev`, `TESTER_PHASES` for `tester`.
  - Migration in `ClaimStore.__init__`: if `PRAGMA table_info(claims)` lacks `role` → `ALTER TABLE claims ADD COLUMN role TEXT NOT NULL DEFAULT 'dev'`; drop and recreate `one_open_claim` on `(repo, ticket, role) WHERE closed_at IS NULL`. `_COLUMNS`, `Claim`, `_claim` gain `role` (last field before `token_hash`).
  - `ClaimStore.take(repo, ticket, holder, token=None, role="dev") -> tuple[Claim, str]`; `held(repo="", ticket="", role="") -> list[Claim]`.
  - Env lock table `env_locks(name TEXT PRIMARY KEY, holder TEXT, story TEXT, token_hash TEXT, taken_at TEXT, last_seen TEXT)`; `@dataclass(frozen=True) EnvLock(name, holder, story, taken_at, last_seen)`; `ClaimStore.lock_env(name, holder, story, token=None) -> tuple[EnvLock, str]` (raises `ClaimTaken`-like `EnvLocked(lock)`), `refresh_env(name, token) -> EnvLock`, `unlock_env(name, token) -> None`, `env_lock(name) -> EnvLock | None`; same TTL and lazy expiry as claims.
  - API: POST `/api/claims` accepts `"role"`; POST `/api/env-locks` `{name, holder, story, token?}` → 201/200, 409 `{"error":"env_locked","lock":…}`; PATCH/DELETE `/api/env-locks/{name}`; GET `/api/env-locks`.
  - Client: `ClaimClient.take(ticket, holder, claim_token=None, role="dev")`, `lock_env(name, holder, story, token=None)`, `unlock_env(name, token)`; `EnvLockedError(KbError)`.
  - CLI `kb test-env lock <story>` / `unlock` (env name from `test-env.yaml`, token in `LocalClaims`), exit 3 when locked.

- [ ] **Step 1: Write the failing tests**

```python
def test_old_db_without_role_migrates_in_place(tmp_path): ...  # create 1.36 schema, add row, open store → role 'dev', row kept; reopen no-op
def test_dev_and_tester_can_hold_same_story(store): ...
def test_two_testers_cannot_hold_same_story(store): ...       # ClaimTaken
def test_tester_phase_validation(store): ...                   # "cases" ok for tester, refused for dev
def test_env_lock_exclusive_and_expires(store, clock): ...
def test_api_tester_may_claim_parent_story(web_client, auth, ...): ...
def test_api_env_lock_conflict_is_409(web_client, auth): ...
```

- [ ] **Step 2: Run** `pytest tests/test_ticketclaim.py tests/test_api_claims.py tests/test_claimclient.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** same plus `tests/test_web_claims.py tests/test_autorun_claims.py tests/test_cli_claim.py` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: tester claims and test environment lock on the hub`

### Task 10: Derived test status and known failures (`testflow`)

**Files:**
- Create: `src/strata_kb/testflow.py`
- Modify: `src/strata_kb/missionnext.py:51-62` (`StoryStatus.test_status: str = ""`, `test_round: int = 0`, `regression_bug: bool = False`), `missionnext.render` (shows `test_status` after `status` when set)
- Modify: `src/strata_kb/planstatus.py` (`hub_plans` applies `testflow.overlay` to every `PlanRepo`)
- Modify: `src/strata_kb/doctor/checks/hub.py` (duplicate tester repos)
- Modify: `src/strata_kb/svcnote.py` / `missionnext.py` (new `fix_rounds_from_history(history_l2) -> dict[str, frozenset[int]]` reading `fix:R<n>` refs)
- Test: `tests/test_testflow.py`, `tests/test_planstatus.py` (overlay case)

**Interfaces:**
- Consumes: `federation.load_federation`, `kinds.is_test_doc`, `ticketcheck.load_doc_dir`, `testreport.parse`, `ticketclaim.ClaimStore.held(role="tester")`, `ticketclaim.claims_db_path`.
- Produces:
  - `@dataclass(frozen=True) TestFacts(reports: dict[str, tuple[Report, ...]], testing: frozenset[str], fix_rounds: dict[str, frozenset[int]])` (reports by story, ascending round, from every published `-test` doc).
  - `testflow.load_facts(hub: HubHandle) -> TestFacts` (missing `claims.db` → no `testing`; unreadable report → skipped with a logged warning).
  - `testflow.story_test_status(story: str, children: tuple[str, ...], facts) -> dict[str, str]` — ids → status per D3: held tester claim → story `testing`; latest report PASS → story + children `closed`; FAIL → story `reopened`, guilty children `reopened` (or `fix-done` when `fix_rounds[child]` has that round), other children unchanged; no report → `{}`.
  - `testflow.overlay(repo: PlanRepo, facts) -> PlanRepo` — returns a new `PlanRepo` with `test_status`, `test_round`, `regression_bug` set (immutable `dataclasses.replace`); `status` untouched.
  - `@dataclass(frozen=True) KnownFailure(key: str, story: str, round: int, rd_id: str, duplicates: tuple[str, ...])`.
  - `testflow.known_failures(facts) -> dict[str, KnownFailure]` — walk reports in (report date, story, round) order: a key in `regression_failed` opens it (first report owns it, later reports in its open window append `f"{story} R{n}"` to `duplicates`); a later report with `regression_ran` and the key not in `regression_failed` closes it.
  - `testflow.STATUSES = ("testing","closed","reopened","fix-done")`.
  - `testflow.duplicate_testers(hub: HubHandle, facts) -> list[str]` — one message per BA repo whose stories are covered by `-test` docs of more than one tester repo (story → BA repo via `ticketfetch.find`); `doctor/checks/hub.py` reports each as an error (spec D1: one tester repo per BA repo).

- [ ] **Step 1: Write the failing tests** (hub = `plan_hub` fixture + `make_fed_entry` for a `qa-repo` `-test` doc)

```python
def test_pass_report_closes_story_and_children(...): ...
def test_fail_reopens_only_guilty_child(...): ...
def test_fix_round_in_history_gives_fix_done(...): ...
def test_held_tester_claim_gives_testing(...): ...
def test_closed_is_final_even_if_revision_bumps(...): ...
def test_status_field_never_changes(...): ...       # status stays "done"
def test_report_for_unknown_story_is_ignored(...): ...   # Review Focus 1
def test_known_failure_dedupes_and_closes(...): ...      # Review Focus 5
def test_two_tester_repos_for_one_ba_repo_is_doctor_error(...): ...
```

- [ ] **Step 2: Run** `pytest tests/test_testflow.py tests/test_planstatus.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** as specified. `testflow` must not import `web`; `planstatus` imports `testflow` (check no cycle with `test_layering`).
- [ ] **Step 4: Run** `pytest tests/test_testflow.py tests/test_planstatus.py tests/test_planstatus_parents.py tests/test_layering.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: derive testing, closed, reopened and fix-done from published reports`

### Task 11: Hub — role `tester`, Test Report pages, ticket status

**Files:**
- Modify: `src/strata_kb/serving/accounts.py:29,46-54` (`ROLES` gains `tester`; DDL CHECK built from `ROLES`; migration: when `sqlite_master.sql` for `users` lacks `'tester'`, rebuild table in one transaction: create `users_new`, copy, drop, rename)
- Create: `src/strata_kb/web/testui.py`, `src/strata_kb/templates/web/tests.html`, `tests_story.html`
- Modify: `src/strata_kb/web/app.py:90-102` (`routes += testui.test_routes(config)`), `_partials/left_rail.html`, `_partials/tab_bar.html` (link `/ui/tests` "Test Report"), `_partials/status.html` (`plan_status` shows `test_status` badge when set; `plan_counts` keys gain test statuses), `plan_ticket.html` + `web/planui.py:_ticket_page` (own status line, report round links, `regression` badge), `src/strata_kb/web/api.py` (GET `/api/tests/known-failures` → JSON of `known_failures`)
- Test: `tests/test_accounts.py`, `tests/test_web_tests.py`, `tests/test_web_plans.py` (status badge)

**Interfaces:**
- Consumes: `testflow.load_facts`, `known_failures`, `STATUSES`; `ui._render_page`, `gfmrender.render`; `/assets/{name}` route (existing).
- Produces:
  - Routes: `/ui/tests` (list; query `status=all|testing|reopened|closed|regression|candidates`, default `all`), `/ui/tests/{story}` (cases + rounds), `/ui/tests/{story}/R{n}` (rendered report with images).
  - List row: story, round, verdict, test status, date, links ticket/report; candidates filter = open known failures not marked duplicate; unknown story rows labelled "unknown story".

- [ ] **Step 1: Write the failing tests**

```python
def test_old_users_db_gains_tester_role(tmp_path): ...    # Review Focus 2
def test_menu_link_on_every_page(web_client_logged_in): ...  # 'href="/ui/tests"' on /ui, /ui/tickets, /ui/questions
def test_list_filters_by_status(...): ...
def test_report_page_renders_asset_image(...): ...        # <img src="/assets/<sha>.png">
def test_candidates_show_one_row_per_key(...): ...
def test_ticket_page_shows_test_status_and_rounds(...): ...
def test_tester_role_can_view_not_registry(...): ...
```

- [ ] **Step 2: Run** `pytest tests/test_accounts.py tests/test_web_tests.py tests/test_web_plans.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** following `qaui.py` / `questions.html` structure (chip filters, panels, empty state "No test reports yet").
- [ ] **Step 4: Run** `pytest tests/test_accounts.py tests/test_web_tests.py tests/test_web_plans.py tests/test_web_questions.py tests/test_web_ui.py tests/test_layering.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: Test Report menu and test status on the hub`

### Task 12: Tester skills (env setup, test a story, Q1/Q2)

**Files:**
- Create in `src/strata_kb/templates/init/`: `bodies/tester-env-setup.md`, `bodies/tester-test-story.md`; four wrappers each (`claude-skill-…`, `claude-command-…`, `copilot-….prompt.md`, `cursor-….md`)
- Modify: `src/strata_kb/initcmd.py` (`TESTER_TEMPLATES` gains the 8 wrappers), `src/strata_kb/templates/init/claude-settings-auto.json` (allow `Bash(kb test-env *)`, `Bash(kb testcase *)`, `Bash(kb report*)`, `Bash(kb report-ingest*)`, `Bash(npx playwright test*)`, `mcp__playwright__*`)
- Test: `tests/test_init_tester.py` (wrappers), `tests/test_template_bodies.py` (passes unchanged), `tests/test_tester_skills.py`

**Interfaces:**
- Consumes: every CLI from Tasks 3–9.
- Produces: slash commands `/tester-env-setup`, `/tester-test-story <story>`.
- Body content (pinned, tested by phrase):
  - `tester-env-setup`: ask item by item (D2 list), write `.kb/test-env.yaml` from `.kb/test-env.example.yaml`, write secret values only to `.env`, run `kb test-env check` then `kb test-env verify`, explore the login page with Playwright MCP and fill `tests/fixtures/login.ts`, log in each account, report each item ok/FAIL.
  - `tester-test-story`: `kb ticket fetch <story> --out tests/<story>/ticket.md` → `kb test-env deployed <story>` (exit 4 → stop "not deployed yet") → `kb test-env lock <story>` → `kb claim take <story>` → explore ACs with Playwright MCP → write `tests/<story>/test-cases.md` from `docs/templates/test-cases.md` → `kb testcase lint` → scripts per D5 rules → **Q1** → run pipeline D5 steps 1–6 in order (story run, clean retry with `kb test-env reset`/`seed`, MCP confirmation, regression run over every `closed` story's scripts with `GET /api/tests/known-failures` dedupe and the attribution rule using `kb test-env changed`, post-check `kb test-env version`) → write `reports/<story>/R<n>.md` only for PASS/FAIL (else local run log, stop) → `kb report lint` → **Q2** → `kb report-ingest` → open PR (never merge) → `kb test-env unlock`, `kb claim release`.
  - Review dispatch contract copied from `bodies/dev-design.md:304-330` with names `test-case-reviewer` (Q1) and `test-report-reviewer` (Q2), criteria `docs/test-review-rubric.md` + `.local.md`, convergence rule from Global Constraints, `## Review record` table `| Date | Round | Verdict | Reviewer | Coverage | Open gaps |`, stop text "AUTO-RESULT: failed test-review" reserved for phase 3.

- [ ] **Step 1: Write the failing tests**

```python
def test_init_tester_has_all_four_wrappers_per_skill(tmp_path): ...
def test_test_story_body_orders_the_pipeline(): ...   # index("deployed") < index("lock") < index("Q1") < index("regression") < index("Q2") < index("report-ingest")
def test_test_story_body_never_merges(): ...          # "never merge" present; no "kb pr merge"
def test_env_setup_body_keeps_secrets_out_of_yaml(): ...  # ".env" and "names only" present
```

- [ ] **Step 2: Run** `pytest tests/test_init_tester.py tests/test_tester_skills.py tests/test_template_bodies.py -q` — Expected: FAIL.
- [ ] **Step 3: Write** the bodies and wrappers.
- [ ] **Step 4: Run** same — Expected: PASS.
- [ ] **Step 5: Commit** `feat: tester-env-setup and tester-test-story skills`

### Task 13: Docs, version, full suite

**Files:**
- Modify: `README.md` (Repo kinds table row `tester`, federation sketch, command table rows `kb test-env`, `kb testcase`, `kb report`, `kb report-ingest`), `CHANGELOG.md` (`## 1.37.0 — <date>`), `pyproject.toml` (version `1.37.0`), `docs/src/architecture.en.md` + `.vi.md` (kind list, status list)
- Test: `tests/test_readme.py`, golden outputs under `tests-gate/golden/cli_outputs` if the gate pins `kb --help`

- [ ] **Step 1: Run** `pytest -q` — Expected: only README/golden mismatches fail.
- [ ] **Step 2: Update** docs and regenerate golden CLI outputs the way `tests-gate/regression/test_golden_output.py` documents.
- [ ] **Step 3: Run** `pytest -q` — Expected: PASS, no skips added.
- [ ] **Step 4: Commit** `docs: tester role in README, architecture and changelog (1.37.0)`
