# Full-auto mode on Claude Code cloud — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/kb-auto run` works inside one Claude Code cloud session on its `claude/...` branch, for BA and Dev repos, with no hub clone and no GitHub GraphQL.

**Architecture:** One cloud switch (`cloud.is_cloud()`) gates every cloud-only behaviour. Nothing from the hub is copied: agents keep using the `strata-kb` MCP tools, and the non-agent code (runner, `kb resolve`, `kb mission next`) calls three new JSON routes on the same hub server; every other hub-reading CLI command refuses on cloud and points at its MCP tool. PR work moves from `gh pr` (GraphQL) to new `kb pr` subcommands over `gh api` REST. The session keeps itself alive by re-arming a `kb auto wait` background command while `kb auto run` runs detached.

**Tech Stack:** Python ≥3.11, typer, starlette, pydantic, pytest; `gh api` (REST) and `git` subprocesses.

**Spec:** `docs/superpowers/specs/2026-10-16-kb-auto-cloud-design.md`

## Global Constraints

- `requires-python >= 3.11`; no new runtime dependency.
- Cloud = `STRATA_KB_CLOUD` is `1` (forced on) or `0` (forced off); otherwise `CLAUDE_CODE_REMOTE` is `1` or `true` (case-insensitive). Nothing outside this switch changes local behaviour.
- Hub over HTTP uses `STRATA_KB_HUB_URL` (`mcpsetup.HUB_URL_VAR`) and `STRATA_KB_HTTP_TOKEN` (`dockersetup.TOKEN_VAR`) only. Never log or `repr` the token.
- Every text-mode file write passes `newline="\n"` (`tests/test_windows_hygiene.py` enforces it).
- On cloud, no hub content is written to disk and `resolve_hub` never clones (owner's decision).
- `/api/registry/entry` never returns the whole registry or workflow pins.
- Never `--dangerously-skip-permissions`; never edit `.claude/settings*.json` by hand in skills; never force-push.
- Release: version `1.30.0`, a CHANGELOG entry in the 1.29.0 style.
- Run tests with `uv run pytest <path> -q`; full suite with `uv run pytest -q` before the last commit.

## Review Focus

1. Hub server older than 1.30.0 (route returns 404) → one refusal line naming 1.30.0, not a traceback or a silent idle loop (Task 3 test).
2. Hub unreachable mid-loop (status 0) → runner idles like today's "hub plan not read", never counts a failed attempt (Task 3 test).
3. `kb resolve --write-cache` on cloud writes byte-for-byte what the local path writes for the same results (Task 3 test with one fixture hub served both ways).
4. `kb pr find --head` with a branch containing `/` (`auto/US-1`) → query `head=<owner>:auto/US-1` URL-encoded (Task 4 test).
5. `kb pr checks --watch` while CI has not created any check run yet → keeps waiting, never reports green on zero checks (Task 4 test).

---

### Task 0: Spike on cloud (throwaway, gate for everything else)

No code is kept. Run in a cloud session, against a **scratch GitHub repo the owner names** (not a product repo). If the owner has not named one, stop and ask.

- [ ] **Step 1:** In a cloud session on the scratch repo, start `nohup bash -c 'for i in $(seq 1 400); do date; sleep 30; done' > spike.log 2>&1 &`, then loop: a `run_in_background` Bash `sleep 6600; tail -1 spike.log` (or shorter if the tool caps lower), re-armed each time it returns. Pass = the session is still alive and `spike.log` still growing after > 3 h.
- [ ] **Step 2:** `git switch -c auto/spike && git commit --allow-empty -m spike && git push -u origin HEAD`. Pass = push accepted.
- [ ] **Step 3:** REST: `gh api -X POST repos/<o>/<r>/pulls -f head=auto/spike -f base=main -f title=spike -f body=spike`; `gh api -X PUT repos/<o>/<r>/pulls/<n>/merge -f merge_method=squash` with `main` protected (a) without and (b) with a required review; `gh api -X DELETE repos/<o>/<r>/git/refs/heads/auto/spike`. Pass = (a) and delete succeed; record whether (b) merges as admin.
- [ ] **Step 4:** `gh run list --limit 1` and `gh run view <id> --log-failed`. Pass = both work (else Task 4 also wraps `gh run`).
- [ ] **Step 5:** Write results to `docs/superpowers/specs/2026-10-16-kb-auto-cloud-spike.md` and commit. Any fail in steps 1–3 → stop, report to the owner, do not start Task 1.

### Task 1: Real default branch when `origin/HEAD` is missing

**Files:**
- Modify: `src/strata_kb/gitio.py` (`default_branch`, ~line 656)
- Test: `tests/test_gitio_default_branch.py` (create)

**Interfaces:**
- Produces: `gitio.default_branch(root: Path) -> str` — order: `refs/remotes/origin/HEAD`; else, when `has_remote(root)`, `git ls-remote --symref origin HEAD` (parse `ref: refs/heads/<b>\tHEAD`) then best-effort `git remote set-head origin <b>` (ignore failure); else `current_branch(root)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_default_branch_asks_the_remote_when_origin_head_is_missing(tmp_path):
    # bare remote whose HEAD is main; clone; `git remote set-head origin -d`;
    # `git switch -c claude/x`
    assert gitio.default_branch(clone) == "main"
    # and it was cached for next time
    assert _git(clone, "symbolic-ref", "refs/remotes/origin/HEAD").endswith("/main")

def test_default_branch_without_remote_is_current_branch(tmp_path):
    # `git init -b trunk`, one commit, no remote
    assert gitio.default_branch(repo) == "trunk"
```

- [ ] **Step 2:** `uv run pytest tests/test_gitio_default_branch.py -q` → first test FAILS (returns `claude/x`).
- [ ] **Step 3:** Implement as in Interfaces, reusing `gitio._run`.
- [ ] **Step 4:** `uv run pytest tests/test_gitio_default_branch.py tests/test_autorun_runner.py tests/test_autorun_switch.py -q` → PASS.
- [ ] **Step 5:** Commit `fix: default branch asks the remote when origin/HEAD is unset`.

### Task 2: Cloud switch and the hub JSON routes

**Files:**
- Create: `src/strata_kb/cloud.py`
- Modify: `src/strata_kb/web/api.py` (`build_routes`, three routes next to `/api/questions`)
- Test: `tests/test_cloud.py`, `tests/test_api_cloud_routes.py` (create; reuse the `web_client`, `token`, `hub_with_ticket` fixtures of `tests/test_api_questions.py`)

**Interfaces:**
- Produces: `cloud.is_cloud() -> bool` (rule in Global Constraints); `cloud.hub_http() -> tuple[str, str] | None` — `(url.rstrip("/"), token)` when both env vars are non-empty, else `None`.
- Produces (all plain `def`, auth from the existing `/api/*` middleware, `503 hub_unreachable` when `hub_handle(config)` is `None`):
  - `GET /api/plan/next[?repo=]` → `{"stories": [...], "unparented": [...], "notes": [...]}`; each item = `dataclasses.asdict(StoryStatus)` (tuples become lists).
  - `GET /api/registry/entry?repo_id=<id>` → `{"repo_id", "kind", "auto_merge", "dev_repos"}` (`dev_repos` = number of registry entries with kind `dev`); `400` without `repo_id`, `404 repo_not_registered` when absent.
  - `POST /api/resolve` (body: kb-context text, ≤ the existing body cap) → `{"version": ctx.version, "results": [{"ref": str(r.ref), "status", "citation", "content", "tokens", "reason", "pinned_rev"}]}`; `400 kb_context_error` on a parse error.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("env,expected", [
    ({}, False), ({"CLAUDE_CODE_REMOTE": "true"}, True), ({"CLAUDE_CODE_REMOTE": "1"}, True),
    ({"CLAUDE_CODE_REMOTE": "true", "STRATA_KB_CLOUD": "0"}, False), ({"STRATA_KB_CLOUD": "1"}, True),
])
def test_is_cloud(monkeypatch, env, expected): ...
def test_hub_http_needs_both_vars(monkeypatch): ...

@pytest.mark.parametrize("path", ["/api/plan/next", "/api/registry/entry?repo_id=x"])
def test_routes_require_auth(web_client, path):
    assert web_client.get(path).status_code == 401

def test_plan_next_matches_next_from_hub(web_client, hub_with_ticket, auth):
    hub = hub_with_ticket(rev=1)
    stories, unparented, notes = planstatus.next_from_hub(hub)
    body = web_client.get("/api/plan/next", headers=auth).json()
    assert [s["us_id"] for s in body["stories"]] == [s.us_id for s in stories]

def test_registry_entry_is_one_repo_without_pins(web_client, hub_with_ticket, auth):
    body = web_client.get("/api/registry/entry?repo_id=ba-one", headers=auth).json()
    assert set(body) == {"repo_id", "kind", "auto_merge", "dev_repos"}

def test_registry_entry_unknown_is_404(...): ...
def test_resolve_returns_results(web_client, hub_with_ticket, auth): ...   # status/citation per ref
def test_resolve_bad_context_is_400(...): ...
```

- [ ] **Step 2:** Run both files → FAIL.
- [ ] **Step 3:** Implement `cloud.py` and the three routes.
- [ ] **Step 4:** Run both files → PASS.
- [ ] **Step 5:** Commit `feat: hub JSON routes for plan, registry entry and resolve; cloud switch`.

### Task 3: Runner and CLI read the hub live on cloud

**Files:**
- Create: `src/strata_kb/hubapi.py`
- Modify: `src/strata_kb/autorun/runner.py` (`_resolve_hub`, `_check_done`, `preflight`), `src/strata_kb/autorun/picker.py` (`pick_dev`), `src/strata_kb/autorun/switch.py` (`registry_or_reason`, `warnings_for_on`), `src/strata_kb/cli.py` (`resolve`, `mission_next`, `_hub_or_reason`), `src/strata_kb/hub.py` (`resolve_hub`)
- Test: `tests/test_hubapi.py`, `tests/test_autorun_cloud.py`, `tests/test_cli_cloud_hub.py` (create)

**Interfaces:**
- Consumes: Task 2 routes and `cloud.*`.
- Produces (`hubapi.py`, client in the style of `autorun/qa.py`: `httpio.request`, bearer token, `KbError` on status 0 / non-2xx / bad JSON; a 404 on the route itself raises `KbError("hub server has no <route> — upgrade it to strata-kb 1.30.0 or later")`):
  - `class HubApi(base_url: str, token: str, http=httpio.request)`
  - `HubApi.plan_next(repo: str | None = None) -> tuple[list[StoryStatus], list[StoryStatus], list[str]]`
  - `HubApi.registry_entry(repo_id: str) -> dict | None` (`None` on `404 repo_not_registered`)
  - `HubApi.resolve(text: str) -> tuple[str, list[ResolvedRef]]` (version, results; `ref` re-parsed with `kbcontext`'s ref parser)
  - `hubapi.from_env() -> HubApi` (same env names and messages as `qa.from_env`)
- Changes on cloud only (`cloud.is_cloud()`):
  - Runner: the `hub` passed to `run_once` / `pick_dev` / `_check_done` is a `HubApi`; a small `plan_next(hub)` helper in `picker.py` dispatches `HubApi.plan_next()` vs `planstatus.next_from_hub(hub)` (keep calling the latter by module attribute so existing monkeypatching tests still work).
  - `preflight` / `warnings_for_on`: registry facts from `registry_entry(cfg.repo_id)`; refusal texts unchanged.
  - `kb resolve`: results from `HubApi.resolve`; the rest of the command (render, `--write-cache`, `--cache`, exit codes) unchanged.
  - `kb mission next`: the done set = `us_id`s with status `done` in `HubApi.plan_next()` stories + unparented, instead of loading the `-svc` doc.
  - `_hub_or_reason` (hence `_hub_or_exit`): returns `(None, "on Claude Code cloud the hub is read through the strata-kb MCP tools, not the CLI")`.
  - `resolve_hub`: raises `KbError` with that same message instead of cloning (guards anything missed).

- [ ] **Step 1: Write the failing tests** (fake `http` returning the Task 2 routes' bodies from `web_client`)

```python
def test_hubapi_plan_next_round_trips_storystatus(...): ...
def test_hubapi_404_route_names_1_30_0(...): ...                  # Review Focus 1
def test_cloud_runner_idles_when_hub_unreachable(...): ...        # status 0 -> outcome "idle", attempts unchanged (Review Focus 2)
def test_cloud_preflight_refuses_without_auto_merge(...): ...     # same text as local
def test_cloud_resolve_write_cache_matches_local(tmp_path, ...): ...  # Review Focus 3: bytes equal
def test_cloud_mission_next_done_set_from_hub(...): ...
def test_cloud_other_hub_commands_refuse(cli_runner, monkeypatch): ...  # e.g. `kb query x` -> exit 1, message names MCP
def test_cloud_resolve_hub_never_clones(monkeypatch): ...          # gitio.clone not called, KbError
def test_local_mode_unchanged(monkeypatch, ...): ...               # CLAUDE_CODE_REMOTE unset -> clone path, HubApi unused
```

- [ ] **Step 2:** `uv run pytest tests/test_hubapi.py tests/test_autorun_cloud.py tests/test_cli_cloud_hub.py -q` → FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Same, plus `uv run pytest tests/test_autorun_*.py tests/test_cli_mission.py tests/test_cli.py -q` → PASS.
- [ ] **Step 5:** Commit `feat: runner and CLI read the hub live through its API on Claude Code cloud`.

### Task 4: `kb pr` over the REST API

**Files:**
- Create: `src/strata_kb/ghrest.py`
- Modify: `src/strata_kb/cli.py` (new commands on the existing `pr_app`; widen its help to "Pull requests: the description gate and REST helpers.")
- Test: `tests/test_ghrest.py`, `tests/test_cli_pr_rest.py` (create)

**Interfaces:**
- Produces (`ghrest.py`, all raise `ghio.GHError` on a non-zero `gh` exit or bad JSON; every `gh` call has the 60 s timeout of `ghio`):
  - `origin_slug(root: Path) -> tuple[str, str]` — `(host, "owner/repo")` from `git remote get-url origin` via `pubgate.owner_repo_from_remote`; host from the URL (scp form `git@host:o/r` too).
  - `api(root: Path, method: str, path: str, body: dict | None = None) -> Any` — runs `gh api --hostname <host> -X <method> <path>` with `--input -` and the JSON body on stdin when `body` is given.
  - `find_prs(root, head: str, state: str = "open") -> list[dict]` — `state` in `open|closed|merged|all`; `GET repos/{slug}/pulls?head={owner}:{head}&state=…&per_page=100` (`head` URL-encoded; `merged` = `closed` filtered on `merged_at`).
  - `view_pr(root, ref: str | None = None) -> dict` — `ref` = number, branch, or `None` (current branch, any state, newest).
  - `open_pr(root, title: str, body: str, head: str | None = None, base: str | None = None) -> dict` — defaults: current branch, `gitio.default_branch(root)`.
  - `checks(root, ref: str | None = None) -> list[dict]` — check runs + commit statuses of the PR head SHA, each `{"name", "state"}` with `state` in `pending|success|failure`.
  - `merge_pr(root, ref: str | None, method: str = "squash", delete_branch: bool = False) -> dict` — `PUT …/pulls/{n}/merge`; then `DELETE …/git/refs/heads/<head>` when asked.
  - `edit_pr(root, ref: str | None, title: str | None = None, body: str | None = None) -> dict` — `PATCH …/pulls/{n}`.
  - Every PR dict the module returns has the `gh pr` JSON keys: `number`, `url`, `state` (`OPEN|CLOSED|MERGED`), `mergedAt`, `title`, `body`, `headRefName`.
- Produces (CLI): `kb pr find --head B [--state S] [--json]`, `kb pr view [REF] [--json]`, `kb pr open --title T (--body S | --body-file F) [--head B] [--base B]`, `kb pr checks [REF] [--watch] [--interval 15] [--timeout 3600]` (exit 0 all success, 1 any failure, 8 pending without `--watch` or on timeout), `kb pr merge [REF] [--squash|--merge] [--delete-branch] [--admin]` (`--admin` accepted for the skills' wording; REST merges with the caller's rights), `kb pr edit [REF] [--title T] [--body-file F]`. Without `--json`, print the PR URL (find/view/open) or one line per check.

- [ ] **Step 1: Write the failing tests** (fake `ghrest._gh(root, args, stdin) -> str` recording calls)

```python
def test_find_merged_filters_closed_on_merged_at(fake_gh): ...
def test_find_encodes_head_with_slash(fake_gh):
    ghrest.find_prs(root, "auto/US-1", "open")
    assert "head=o%3Aauto%2FUS-1" in fake_gh.calls[0].path
def test_checks_watch_waits_while_no_check_run_exists(fake_gh):   # 0 runs, then pending, then success -> exit 0 after 3 polls
def test_checks_failure_exits_1(...): ...
def test_merge_deletes_branch_when_asked(fake_gh): ...            # PUT …/merge then DELETE …/git/refs/heads/auto/US-1
def test_origin_slug_scp_and_https_and_ghe(tmp_path): ...         # git@github.com:o/r.git, https://ghe.corp/o/r -> ("ghe.corp","o/r")
def test_cli_view_json_has_gh_keys(cli_runner, fake_gh): ...
```

- [ ] **Step 2:** `uv run pytest tests/test_ghrest.py tests/test_cli_pr_rest.py -q` → FAIL.
- [ ] **Step 3:** Implement per Interfaces.
- [ ] **Step 4:** Same command → PASS; plus `uv run pytest tests/test_cli_prlint.py -q` (existing `kb pr lint` untouched).
- [ ] **Step 5:** Commit `feat: kb pr find|view|open|checks|merge|edit over the GitHub REST API`.

### Task 5: Skills call `kb pr`, not `gh pr`

**Files:**
- Modify: every file under `src/strata_kb/templates/init/` containing `gh pr ` (15 files: `bodies/*.md`, the full-copy `claude-*.md`, `QUICKSTART-ba.md`, `QUICKSTART-dev.md`)
- Modify: matching fixtures under `tests/fixtures/bodies-pre-auto/` (same mechanical edit, so the "switch off reads as before" tests still compare like with like)
- Test: `tests/test_template_bodies.py` (add one test)

**Interfaces:**
- Consumes: the `kb pr` CLI of Task 4.
- Rewrite table (apply verbatim):

| Before | After |
|---|---|
| `gh pr list --head <b> --state <s> --json number,url` | `kb pr find --head <b> --state <s> --json` |
| `gh pr create --title … --body …` | `kb pr open --title … --body …` |
| `gh pr checks --watch` | `kb pr checks --watch` |
| `gh pr merge --squash [--admin] --delete-branch` | `kb pr merge --squash [--admin] --delete-branch` |
| `gh pr view --json state,mergedAt` | `kb pr view --json` |
| `gh pr view <b> --json body --jq .body` | `kb pr view <b> --json` (read `body`) |
| `gh pr edit <b> … --body-file <f>` | `kb pr edit <b> … --body-file <f>` |
| `` `gh` can report an error from a worktree after the merge went through `` | `` `kb pr merge` can report an error after the merge went through `` |

`gh run …` lines stay unless Task 0 step 4 failed. `claude-settings-auto.json` already allows `Bash(kb pr *)`; leave `gh pr *` in it for older skills.

- [ ] **Step 1: Write the failing test**

```python
def test_no_template_calls_gh_pr():
    hits = [f for f in _templates_and_bodies() if re.search(r"\bgh pr (list|create|checks|merge|view|edit)\b", text(f))]
    assert hits == []
```

- [ ] **Step 2:** `uv run pytest tests/test_template_bodies.py -q` → new test FAILS listing the 15 files.
- [ ] **Step 3:** Apply the table to templates and the matching pre-auto fixtures.
- [ ] **Step 4:** `uv run pytest tests/test_template_bodies.py tests/test_initcmd*.py -q` → PASS.
- [ ] **Step 5:** Commit `feat: skills open, check and merge PRs through kb pr`.

### Task 6: `kb auto wait` and the cloud path of `/kb-auto run`

**Files:**
- Create: `src/strata_kb/autorun/wait.py`
- Modify: `src/strata_kb/cli.py` (`auto_app`: new `wait` command), `src/strata_kb/autorun/switch.py` (`status()` gains `"cloud"`)
- Modify: `src/strata_kb/templates/init/bodies/kb-auto.md` (and any `kb-auto` full copies)
- Test: `tests/test_autorun_wait.py` (create), `tests/test_autorun_switch.py`, `tests/test_template_bodies.py`

**Interfaces:**
- Consumes: `cloud.is_cloud()` (Task 2), `kb pr open|checks|merge` (Task 4), `autostate.load`, `lock.running_pid`.
- Produces: `wait.wait_for_change(kb_dir: Path, max_seconds: int, interval: int = 30, sleep=time.sleep, now=time.monotonic) -> str` — returns at the first of:
  - loop not running and `stop_reason` set → `"stopped: <reason>"`;
  - loop not running, no `stop_reason` → `"not running — see .kb/auto/run.log"`;
  - `(task, attempts, waiting_on)` differs from the first read → `"progress: <task or idle>, attempt <n>[, waiting on Q<ids>]"`;
  - `max_seconds` elapsed → `"still running: <task or idle>, attempt <n>"`.
- Produces: `kb auto wait [--max 6600] [--interval 30]` prints that line, exit 0; refuses under `STRATA_KB_AUTO_TASK=1` like `on|off|run`.
- Produces: `kb auto status --json` key `"cloud": bool`.
- Skill text — `run` gains a cloud branch taken when `cloud` is true:
  1. As today: `running` is a pid → say so, stop. Skip the "must be on the default branch" step.
  2. `kb auto on` if needed, warnings verbatim.
  3. Commit `.kb/config.yaml` and `.claude/settings.json` on the session branch (pathspec commit as today).
  4. When `origin/<default_branch>`'s `.kb/config.yaml` lacks `auto.enabled: true`: tell the owner the switch PR will be admin-merged into `<default_branch>`; `git fetch origin <default_branch>`; `git worktree add .kb/auto/worktrees/switch -b auto/switch FETCH_HEAD`; copy the two files from the session tree into it; commit; `git -C .kb/auto/worktrees/switch push -u origin HEAD`; `kb pr open --head auto/switch --title "chore: enable full-auto mode" --body-file <body passing kb-pr-lint>`; `kb pr checks auto/switch --watch` (red → stop and report); `kb pr merge auto/switch --squash --admin --delete-branch`; `git worktree remove .kb/auto/worktrees/switch`.
  5. `mkdir -p .kb/auto`; start detached as today; poll for the pid or a refusal as today.
  6. Arm the watcher: Bash `kb auto wait --max 6600` with `run_in_background`. On each return: report the line only when it is not `still running: …`; re-arm unless it starts with `stopped:` or `not running`.

- [ ] **Step 1: Write the failing tests**

```python
def test_wait_reports_stop(tmp_path): ...            # running None + stop_reason "ci-red" -> "stopped: ci-red"
def test_wait_reports_progress_on_task_change(...): ...
def test_wait_times_out_still_running(...): ...      # fake now jumps past max -> "still running: dev-implement-ticket:US-1, attempt 0"
def test_wait_refuses_inside_auto_task(cli_runner, monkeypatch): ...
def test_status_reports_cloud(monkeypatch, ...): ...
def test_kb_auto_body_has_cloud_path():
    body = read_body("kb-auto")
    assert "kb auto wait --max 6600" in body and "auto/switch" in body and "--admin" in body
```

- [ ] **Step 2:** Run the three test files → FAIL.
- [ ] **Step 3:** Implement `wait.py`, the command, the status key, and the skill text.
- [ ] **Step 4:** Same → PASS.
- [ ] **Step 5:** Commit `feat: kb auto wait and the cloud path of /kb-auto run`.

### Task 7: Release 1.30.0

**Files:**
- Modify: `pyproject.toml` (`version`), `uv.lock` (the `strata-kb` version line, as commit `299128d` did), `CHANGELOG.md`, `README.md` ("Full-auto mode" section), `src/strata_kb/templates/init/QUICKSTART-ba.md`, `QUICKSTART-dev.md`

- [ ] **Step 1:** Bump to `1.30.0`; CHANGELOG `## 1.30.0 — <date>` with bullets: **Cloud** (one session, `/kb-auto run` on `claude/...`, the switch PR), **Hub live reads** (`GET /api/plan/next`, `GET /api/registry/entry`, `POST /api/resolve`; upgrade the hub first; on cloud nothing from the hub is copied and other hub CLI commands point at the MCP tools), **`kb pr`** (REST, skills switched), **`kb auto wait`**, **Default branch** fix, **Upgrade** (hub, CLI, `kb init --kind ba|dev` again to get the skill changes; set `STRATA_KB_HUB_URL`/`STRATA_KB_HTTP_TOKEN` in the cloud environment), **Known limits** (session must stay open).
- [ ] **Step 2:** README and both QUICKSTARTs: a short "On Claude Code cloud" subsection under full-auto mode: env vars, the hub server version, what `/kb-auto run` does there.
- [ ] **Step 3:** `uv run pytest -q` → all PASS; `scripts/gate.sh` if the environment allows.
- [ ] **Step 4:** Commit `feat: full-auto mode on Claude Code cloud — 1.30.0`.
