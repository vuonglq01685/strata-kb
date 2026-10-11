# kb code-sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hub-owned documents that describe code follow the code: an `authored` guard, a deterministic `kb code-sync scan`, a rolling `kb-code-sync` issue kept by a `hub-sync` Docker service, `kb publish --branch`, and a `/kb-code-sync` skill.

**Architecture:** New package `src/strata_kb/codesync/` (facts → changes → scan → issue → runner), pure reads from git objects at two hub shas. GitHub issue calls are REST in `ghapp.py` (the image has no `gh`). The LLM work lives only in the shipped skill, run on the hub manager's own subscription.

**Tech Stack:** Python 3.12+, typer, pydantic, PyYAML, git CLI, urllib (existing deps only). Tests: pytest (+xdist). Lint: ruff, pyright.

**Spec:** `docs/superpowers/specs/2026-10-11-kb-code-sync-design.md`

## Global Constraints

- Existing dependencies only; no new package.
- Exit codes: `0` nothing to do / success, `2` findings, `1` error (same contract as `kb ticket stale`).
- `kb code-sync *` and `kb authored` run only on a `kind: hub` repo; any other kind exits `1` with a one-line message.
- The scan never uses an LLM, never writes the worktree, never opens `.kb-work/search.db`.
- Scan output is a pure function of (hub git history, baseline sha, scan sha): byte-identical on repeat.
- Names, verbatim: tag `authored`; opt-out tag `code-sync-skip`; issue label `kb-code-sync`; bot branch `kb-bot/code-sync`; baseline file `kb-code-sync.yaml` at the hub repo root; env `STRATA_KB_CODE_SYNC_INTERVAL` (seconds, default `86400`); env `STRATA_KB_GH_TOKEN` (token fallback when no App creds).
- `hub` compose service keeps its name and every current setting.
- Never auto-merge; `kb publish --branch` refuses any route that would not open a PR.
- No new field on `Manifest`, `SectionEntry`, `IndexEntry`, `FedIndexEntry` (`extra="forbid"`, read cross-install).
- Run before every commit: `uv run ruff check src tests && uv run ruff format --check src tests && uv run pyright` and the touched test files.

## Review Focus

1. A `-code` republish that only changes the banner sha, an `Image` tag, `Source` path or formatting → zero findings (test in Task 3).
2. Generic or short names (`api`, `web`, `db`, a `cmd.test` purpose word) → never a match, even when they appear everywhere in prose (test in Task 4).
3. Baseline sha missing from hub history (force-push) → exit `1`, and the runner must NOT close the open issue (tests in Tasks 4 and 6).
4. Uncommitted edits in the hub worktree (auto-pull mid-scan, a manager's draft) → scan output unchanged, since it reads git objects only (test in Task 4).
5. No GitHub credentials in the container → `hub-sync` logs one line per run and keeps looping, never crash-loops (test in Task 6).

---

### Task 1: `authored` tag, ingest guard, `kb authored`

**Files:**
- Create: `src/strata_kb/authored.py`
- Modify: `src/strata_kb/ingestcmd.py:150-156` (`_run_ingest`), `src/strata_kb/ingest/scaffold.py` (`scaffold_doc`, top of body), `src/strata_kb/cli.py` (new `authored` command, after `ingest`)
- Test: `tests/test_authored.py`

**Interfaces:**
- Produces: `AUTHORED_TAG = "authored"`, `SKIP_TAG = "code-sync-skip"`; `is_authored(kb_dir: Path, doc_id: str) -> bool`; `set_authored(kb_dir: Path, doc_id: str, on: bool) -> bool` (returns True when `.kb/index.yaml` changed; raises `ValueError` when `doc_id` is not in the index). Both read/write via `models.load_yaml_model` / `save_yaml_model` on `KBIndex`; tag order preserved, no duplicates.

- [ ] **Step 1: Write the failing tests** in `tests/test_authored.py`, using the `fixture_kb` fixture (`tests/conftest.py:99`):
  - `test_set_authored_adds_tag_once` — `set_authored(kb, doc, True)` is True, again is False, tags contain `"authored"` once.
  - `test_set_authored_off_removes_tag` — then `set_authored(kb, doc, False)` is True and tag gone.
  - `test_set_authored_unknown_doc_raises` — `pytest.raises(ValueError, match="not in")`.
  - `test_ingest_refuses_authored_doc` — mark the doc, call `ingestcmd.run_ingest(...)` with a full re-ingest; `pytest.raises(ValueError, match="authored")`; doc files byte-identical before/after; assert the PDF parser was never called (monkeypatch `parser.load_or_parse` to fail the test).
  - `test_ingest_refuses_authored_doc_with_sections` — same with `sections`/chapters set.
  - `test_scaffold_doc_refuses_authored_doc` — call `scaffold.scaffold_doc` directly on an authored doc → `ValueError`.
  - `test_summarize_redo_allowed_on_authored_doc` — `kb summarize <doc> --redo --section <id> --dry-run` via `CliRunner` exits 0 on an authored doc.
  - `test_cli_authored_toggles_and_rejects_non_hub` — `kb authored <doc>` then `--off` on a hub kb (exit 0, message names the doc); on a `kind: child` config exit 1.

- [ ] **Step 2: Run** `uv run pytest tests/test_authored.py -q` — expect FAIL (`ModuleNotFoundError: strata_kb.authored`).

- [ ] **Step 3: Implement.**
  - `authored.py` as in Interfaces.
  - Guard in `_run_ingest` right after `scaffold.validate_doc_id(opts.doc_id)`: if `is_authored(opts.kb_dir, opts.doc_id)` raise `ValueError` with exact text: `"'<doc>' is tagged authored: its markdown is the master and re-ingest would overwrite it — run `kb authored <doc> --off` first if you really mean to replace it"`. The CLI already prints `ValueError` as one red line, exit 1 (`cli.py:802`).
  - Same check at the top of `scaffold_doc` (it has `kb_dir` via its args; if not, pass the index path the caller already has). Same message.
  - CLI `kb authored DOC_ID [--off] [--kb-dir .kb]`: hub-kind check via `config.load_config`; prints `kb authored: <doc> marked` / `unmarked` / `already marked`.

- [ ] **Step 4: Run** `uv run pytest tests/test_authored.py tests/test_ingest_cli.py tests/test_ingest_seam.py -q` — PASS.

- [ ] **Step 5: Commit** `feat: authored tag guards hub docs against re-ingest`.

---

### Task 2: code facts per section

**Files:**
- Create: `src/strata_kb/codesync/__init__.py` (empty), `src/strata_kb/codesync/facts.py`
- Test: `tests/test_codesync_facts.py`

**Interfaces:**
- Produces:
  - `Fact = tuple[str, str]` — `(kind, value)`.
  - `facts_for(section_id: str, doc_kind: Literal["code", "svc"], l2: str, l3: str) -> frozenset[Fact]`.
  - Kinds and sources (spec §5.2):

    | Prefix | Kinds | Source |
    |---|---|---|
    | `svc.*` code | `depends_on`, `port`, `env_key`, `technology` | L2 property rows via `ticketcheck._property(l2, "Depends on" / "Ports" / "Env keys" / "Technology")`; split list cells on `,`, strip spaces and backticks; read the extractor's render (`codeingest/extractors/services.py:1090-1105`) for the exact cell format |
    | `db.*` | `column`, `column_type` (`"<col>:<type>"`), `pk` | L2 `| Column | Type | PK |` via `lintcore.table_rows` + `table_column` |
    | `api.*` | `route` (`"<METHOD> <path>"`) | L2 `| Method | Path | Summary |` |
    | `int.*` | `env_key` | L2 `| Env key | Source |` |
    | `cmd.*` | `command` | `ticketcheck.PRIMARY_RE` on L2 |
    | `dep.*` | `framework` | detected-framework rows only (read `extractors/deps.py:865-875` render); never versions |
    | `svc.*`, `flow.*` svc | `text` | sha256 hex of L3 with banner lines dropped and whitespace runs collapsed |
    | anything else (`struct.tree`, `hist.*`, unknown) | — | empty frozenset |

  - `BANNER_PREFIX` reused from `codeingest/hublag.py` (import, don't copy).

- [ ] **Step 1: Write the failing tests** — fixtures are small hand-written L2/L3 strings copied from a real `kb code-ingest` run on `tests/fixtures_coderepo.py` output (generate once in the test via the existing `code_doc` fixture, `conftest.py:182`, and slice sections with `mdutils.slice_section`):
  - `test_svc_facts_include_depends_on_ports_env_technology`
  - `test_svc_facts_ignore_image_source_volumes_healthcheck` — two L2s differing only in `Image`/`Source`/`Volumes`/`Healthcheck` → equal facts.
  - `test_db_facts_columns_types_pk`
  - `test_api_facts_routes`
  - `test_int_facts_env_keys`
  - `test_cmd_facts_primary_command_only`
  - `test_dep_facts_frameworks_not_versions` — version bump only → equal facts.
  - `test_svc_doc_text_fact_ignores_banner_and_whitespace`
  - `test_struct_tree_and_hist_have_no_facts`

- [ ] **Step 2: Run** `uv run pytest tests/test_codesync_facts.py -q` — FAIL (module missing).

- [ ] **Step 3: Implement** `facts_for` as one dispatch on the id prefix and `doc_kind`; one small private parser per row of the table above.

- [ ] **Step 4: Run** the same — PASS.

- [ ] **Step 5: Commit** `feat: code-sync fact extraction per -code/-svc section`.

---

### Task 3: changes between two hub shas

**Files:**
- Create: `src/strata_kb/codesync/changes.py`
- Modify: `src/strata_kb/gitio.py` (two helpers)
- Test: `tests/test_codesync_changes.py`, `tests/test_gitio.py` (append)

**Interfaces:**
- Consumes: `facts_for`, `Fact` (Task 2).
- Produces:
  - `gitio.resolve_commit(root: Path, rev: str) -> str` — full sha; `GitError` if missing.
  - `gitio.ls_tree(root: Path, rev: str, relpath: str) -> list[str]` — POSIX paths of blobs under `relpath` at `rev` (`git ls-tree -r --name-only`); `GitError` if `rev` missing.
  - ```python
    @dataclass(frozen=True)
    class ChangedItem:
        repo_id: str
        doc_id: str            # e.g. "acme-code"
        section_id: str | None # None = whole doc added/removed
        title: str             # real name (section title; doc title when section_id is None)
        status: Literal["added", "removed", "changed"]
        added: frozenset[Fact]
        removed: frozenset[Fact]
    ```
  - `code_changes(root: Path, base: str, head: str) -> list[ChangedItem]` — sorted by `(repo_id, doc_id, section_id or "")`.

- [ ] **Step 1: Write the failing tests.** Build a hub git repo with `make_fed_entry` (`conftest.py:390`) holding `acme/acme-code` (multi-section L2/L3 shaped like real `-code`) and `acme/acme-svc`; commit; mutate; commit; call `code_changes(hub, c1, c2)`:
  - `test_removed_dependency_is_one_changed_item` — `removed == {("depends_on", "ledger")}`, `added == frozenset()`.
  - `test_banner_image_and_reformat_only_changes_yield_nothing` (Review Focus 1) — change banner sha, `Image`, `Source`, add blank lines → `[]`.
  - `test_added_and_removed_sections` — new `db.refunds` → `status="added"`; dropped `int.stripe` → `"removed"`; facts carried.
  - `test_new_dev_repo_is_one_doc_level_item` — `section_id is None`, `status="added"`.
  - `test_svc_flow_text_change_is_changed` — `-svc §flow.checkout` prose edit → one item with `text` facts.
  - `test_reads_git_objects_not_worktree` — uncommitted worktree edit after `c2` → same result.
  - `test_missing_base_raises_git_error`.
  - In `tests/test_gitio.py`: `test_resolve_commit_full_sha`, `test_ls_tree_lists_blobs_at_rev`.

- [ ] **Step 2: Run** `uv run pytest tests/test_codesync_changes.py tests/test_gitio.py -q` — FAIL.

- [ ] **Step 3: Implement.** Discover docs at each sha with `ls_tree(root, sha, "federation")`, keeping paths matching `federation/(?:.+/)?(?P<rid>[^/]+)/(?P<doc>[^/]+-(?:code|svc))/_manifest.yaml`; read manifests, `<stem>.md`, `<stem>.raw.md` through one `gitio.BatchReader`; slice per section with `mdutils.slice_section` (occurrence from `mdutils.heading_occurrences`); a section is `changed` only when `facts_for` differs.

- [ ] **Step 4: Run** — PASS.

- [ ] **Step 5: Commit** `feat: code-sync changes between two hub commits`.

---

### Task 4: baseline, reverse map, `kb code-sync scan` / `baseline`

**Files:**
- Create: `src/strata_kb/codesync/baseline.py`, `src/strata_kb/codesync/scan.py`
- Modify: `src/strata_kb/cli.py` (new `code_sync_app = typer.Typer(...)`, `app.add_typer(code_sync_app, name="code-sync")`, commands `scan`, `baseline`)
- Test: `tests/test_codesync_scan.py`, `tests/test_cli_codesync.py`

**Interfaces:**
- Consumes: `code_changes`, `ChangedItem` (Task 3); `AUTHORED_TAG`, `SKIP_TAG` (Task 1).
- Produces:
  - `baseline.BASELINE_FILE = "kb-code-sync.yaml"`, `baseline.BOT_BRANCH = "kb-bot/code-sync"`.
  - `baseline.parse(text: str) -> str | None` — the `baseline:` value of the file's text; None when the key is missing.
  - `baseline.read_at(root: Path, rev: str) -> str | None` — `parse` of the file at `rev`; None when absent.
  - `baseline.write(root: Path, sha: str) -> None` — writes `baseline: <full sha>\n`.
  - `baseline.scan_ref(root: Path) -> str` — full sha of `gitio.origin_head_ref(root)`; on `GitError` (no remote) of `HEAD`.
  - `baseline.resolve(root: Path, scan_sha: str) -> tuple[str | None, str]` — `(baseline_sha, source)`; source `"bot-branch"` when `refs/remotes/origin/kb-bot/code-sync` exists and holds the file, else `"default-branch"` (file at `scan_sha`).
  - ```python
    @dataclass(frozen=True)
    class Finding:
        doc_id: str; section_id: str; section_title: str
        term: str; image: bool; item: ChangedItem
    @dataclass(frozen=True)
    class ScanResult:
        scan_sha: str; baseline_sha: str | None; baseline_source: str
        findings: tuple[Finding, ...]; notes: tuple[str, ...]
    ```
  - `scan.match_terms(item: ChangedItem) -> list[str]`; `scan.STOP_WORDS: frozenset[str]` (at least `api app web db service server main core data common shared base default test build lint run`), `scan.MIN_TERM_LEN = 4`.
  - `scan.run_scan(root: Path, *, baseline_sha: str | None = None) -> ScanResult`.
  - `scan.render_markdown(r: ScanResult) -> str`, `scan.to_json(r: ScanResult) -> dict`, `scan.digest(r: ScanResult) -> str` (sha256 hex of canonical JSON of findings only), `scan.exit_code(r: ScanResult) -> int` (`2` if findings else `0`).

- [ ] **Step 1: Write the failing tests** (hub repo: `fed_hub` fixture plus a hub-owned doc `federation/kb-hub/arch/` via `make_fed_entry`, and `kb-hub/.kb/config.yaml` with `kind: hub`, `hub: "."`, `repo_id: kb-hub`):
  - `test_removed_dependency_matches_arch_section` — arch L3 says "payment-service calls ledger"; after removing the dep: one finding `section_id` of that section, `term == "payment-service"` or `"ledger"`, image False.
  - `test_generic_and_short_names_never_match` (Review Focus 2) — service titled `api`, `cmd.test` changed, prose full of "api" and "test" → no findings.
  - `test_cmd_matches_on_command_string_only`.
  - `test_word_boundary_case_insensitive` — `Ledger` matches; `ledgerX` does not.
  - `test_match_inside_image_description_sets_image_flag` — term only inside `![...](assets/...)` alt text (see `mdutils.extract_image_descs`).
  - `test_generated_and_skip_tagged_docs_excluded`.
  - `test_not_authored_doc_gets_note` — notes contain `"<doc> is not tagged authored"`.
  - `test_no_baseline_file_is_note_and_exit_0`.
  - `test_baseline_missing_from_history_raises` (Review Focus 3) — `GitError` / CLI exit 1.
  - `test_bot_branch_baseline_wins` — create `origin/kb-bot/code-sync` with a newer baseline (use `hub_with_origin`, `conftest.py:309`) → only later changes reported, `baseline_source == "bot-branch"`.
  - `test_dirty_worktree_does_not_change_output` (Review Focus 4) — `to_json` equal before/after an uncommitted edit to arch L3.
  - `test_output_is_byte_identical_on_repeat` — `render_markdown` twice equal; `digest` stable.
  - `tests/test_cli_codesync.py`: `test_scan_md_json_and_exit_codes` (0 / 2 / 1), `test_baseline_writes_scan_sha_by_default`, `test_baseline_at_sha`, `test_non_hub_kind_exits_1`.

- [ ] **Step 2: Run** `uv run pytest tests/test_codesync_scan.py tests/test_cli_codesync.py -q` — FAIL.

- [ ] **Step 3: Implement.**
  - `match_terms`: section title, the id suffix after the prefix (slug), and every value in `item.added | item.removed` except kinds `text`; for `cmd.*` only `command` values; drop terms in `STOP_WORDS` or shorter than `MIN_TERM_LEN`; dedupe, sorted.
  - `run_scan`: `scan_sha = scan_ref(root)`; `baseline_sha` param else `resolve()`; None → result with note `no baseline — run kb code-sync baseline`; else `code_changes(root, baseline_sha, scan_sha)`; hub rid = `config.effective_repo_id("", root / ".kb")`; read hub docs at `scan_sha` from `federation/<rid>/` (index.yaml for tags; skip `generated`/`code-sync-skip`); per section L3 regex `(?<![\w-])<re.escape(term)>(?![\w-])`, `re.IGNORECASE`; one `Finding` per (section, item), first matching term.
  - Markdown shape exactly as spec §5.5, plus header lines `Scan: <sha12> · Baseline: <sha12> (<source>) · <n> finding(s)` and the notes, and last line `<!-- kb-code-sync digest:<hex> -->`.
  - CLI `kb code-sync scan [--md|--json] [--baseline SHA]` (default: one line per finding) and `kb code-sync baseline [--at SHA]` (prints the sha written).

- [ ] **Step 4: Run** — PASS.

- [ ] **Step 5: Commit** `feat: kb code-sync scan and baseline`.

---

### Task 5: rolling issue over GitHub REST

**Files:**
- Modify: `src/strata_kb/ghapp.py` (issue + contents helpers)
- Create: `src/strata_kb/codesync/issue.py`
- Test: `tests/test_ghapp.py` (append), `tests/test_codesync_issue.py`

**Interfaces:**
- Consumes: `ScanResult`, `render_markdown`, `digest`, `exit_code` (Task 4).
- Produces (all take `http=_default_http` like `create_or_get_pr`):
  - `ghapp.find_open_issue(repo_full: str, token: str, label: str, http=...) -> tuple[int, str] | None` — `(number, body)` of the newest open issue with `label`.
  - `ghapp.create_issue(repo_full, token, title: str, body: str, label: str, http=...) -> int` — ensures the label exists first (POST `/labels`, 422 = exists).
  - `ghapp.update_issue_body(repo_full, token, number: int, body: str, http=...) -> None`.
  - `ghapp.close_issue(repo_full, token, number: int, comment: str, http=...) -> None`.
  - `ghapp.read_file(repo_full, token, path: str, ref: str, http=...) -> str | None` — contents API, base64-decoded; 404 → None.
  - `issue.LABEL = "kb-code-sync"`, `issue.TITLE = "kb code-sync: hub documents to update"`.
  - `issue.sync_issue(r: ScanResult, *, repo_full: str, token: str, http=...) -> Literal["created", "updated", "unchanged", "closed", "none"]`.
  - `issue.issue_token(repo_full: str, http=...) -> str | None` — `STRATA_KB_GH_TOKEN` if set; else App creds from `STRATA_KB_GH_APP_ID` / `STRATA_KB_GH_APP_KEY` → `mint_installation_token`; else None. Reuse the env names `intake.intake_config_from_env` reads; do not require `STRATA_KB_INTAKE_AUDIENCE`.

- [ ] **Step 1: Write the failing tests** with a fake `http` recording requests (pattern already in `tests/test_ghapp.py`):
  - `test_findings_and_no_issue_creates_one_with_label`.
  - `test_same_digest_does_not_patch` — existing body carries the same digest marker → `"unchanged"`, no PATCH request.
  - `test_new_digest_updates_body`.
  - `test_zero_findings_closes_with_comment`; `test_zero_findings_and_no_issue_is_none`.
  - `test_read_file_decodes_and_404_is_none`.
  - `test_issue_token_prefers_env_token_then_app`.

- [ ] **Step 2: Run** `uv run pytest tests/test_ghapp.py tests/test_codesync_issue.py -q` — FAIL.

- [ ] **Step 3: Implement** on top of `ghapp._call`; close comment text: `"kb code-sync: nothing left to update as of <sha12>."`.

- [ ] **Step 4: Run** — PASS.

- [ ] **Step 5: Commit** `feat: code-sync rolling issue via GitHub REST`.

---

### Task 6: `kb code-sync run` and the `hub-sync` service

**Files:**
- Create: `src/strata_kb/codesync/runner.py`
- Modify: `src/strata_kb/cli.py` (`code-sync run`), `src/strata_kb/templates/init/docker-compose-hub.yml`, `docker-compose.yml` (repo root), `src/strata_kb/templates/init/env.example`
- Test: `tests/test_codesync_runner.py`, `tests/test_init.py` (compose assertions)

**Interfaces:**
- Consumes: `run_scan`, `baseline.resolve`, `BOT_BRANCH`, `BASELINE_FILE` (Task 4); `sync_issue`, `issue_token`, `ghapp.read_file` (Task 5).
- Produces:
  - `runner.run_once(root: Path, *, issue: bool, http=...) -> int` — exit code; logs one summary line.
  - `runner.run_loop(root: Path, *, interval: int, issue: bool, sleep=time.sleep, http=...) -> NoReturn`.
  - `runner.interval_from_env() -> int` — `STRATA_KB_CODE_SYNC_INTERVAL`, default `86400`; non-integer or `< 60` → `SystemExit` with a one-line message (same convention as `ratelimit.trusted_proxies_from_env`).
  - CLI `kb code-sync run [--issue] [--loop]`.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_once_with_creds_reads_bot_branch_baseline_over_rest` — fake http returns a `kb-code-sync.yaml` for ref `kb-bot/code-sync`; `run_scan` receives that sha; no `git fetch` subprocess runs.
  - `test_run_once_without_creds_logs_and_returns` (Review Focus 5) — no env creds → returns scan exit code, logs `issue not updated: no GitHub credentials`, no exception.
  - `test_scan_error_never_closes_issue` (Review Focus 3) — baseline not in history → returns 1, fake http saw no close/PATCH.
  - `test_run_loop_survives_errors_and_sleeps_interval` — `sleep` stub raising after 2 calls; both iterations ran; errors logged, not raised.
  - `test_interval_from_env_rejects_garbage`.
  - `tests/test_init.py`: `test_hub_compose_has_hub_sync_service` — template and repo-root compose both have `services["hub-sync"]` with `command` `["kb", "code-sync", "run", "--issue", "--loop"]`, `env_file: .env`, volume `./:/data`, a `mem_limit`; `services["hub"]` unchanged (existing pins still pass, `_assert_no_dangling_volumes` passes).

- [ ] **Step 2: Run** `uv run pytest tests/test_codesync_runner.py tests/test_init.py -q` — FAIL.

- [ ] **Step 3: Implement.** Root is `/data` in the container (`WORKDIR /data`). With creds, baseline = `baseline.parse(ghapp.read_file(repo_full, token, BASELINE_FILE, BOT_BRANCH))` when that returns text, else `baseline.resolve`; repo from `ghapp.repo_full_from_url(gitio.remote_url(root))`. Compose `hub-sync`: same `image:`/`build:` line as `hub`, no ports, no healthcheck, `mem_limit: 256m` (measure with `docker stats` on a real hub if available, note the figure in a comment the way `hub` does). `env.example`: add `STRATA_KB_GH_TOKEN=` and `STRATA_KB_CODE_SYNC_INTERVAL=86400`, each with a one-line comment; note the App needs `issues: write`.

- [ ] **Step 4: Run** `uv run pytest tests/test_codesync_runner.py tests/test_init.py tests/test_dockersetup.py -q` — PASS.

- [ ] **Step 5: Commit** `feat: hub-sync service runs kb code-sync daily`.

---

### Task 7: `kb publish --branch` (hub self-publish only)

**Files:**
- Modify: `src/strata_kb/publish.py` (`publish()` param + new `_publish_on_branch`), `src/strata_kb/gitio.py` (`push_branch` gets `force: bool = True`), `src/strata_kb/cli.py` (`publish` option)
- Test: `tests/test_publish_branch.py`

**Interfaces:**
- Produces: `publish(..., branch: str | None = None)`; `_publish_on_branch(kb_abs: Path, handle: HubHandle, rid: str, source_commit: str, branch: str) -> PublishReport`; `gitio.push_branch(root, branch, token=None, *, timeout=None, force=True)` (existing callers unchanged).

- [ ] **Step 1: Write the failing tests** (`hub_with_origin` fixture; `ghio.can_open_pr` / `create_pr` / `pr_url_for_branch` monkeypatched):
  - `test_branch_publish_commits_on_current_branch_without_reset` — on `kb-bot/code-sync` with a prior commit X: after publish, X is an ancestor of the branch tip, tip touches only `federation/`, push called with `force=False`, PR opened for that branch.
  - `test_branch_publish_reuses_open_pr` — `pr_url_for_branch` returns a URL → no `create_pr`.
  - `test_branch_must_be_checked_out` — current branch differs → `PublishError` naming both branches.
  - `test_branch_refuses_when_no_pr_possible` — no remote or `can_open_pr` False → `PublishError`, nothing committed.
  - `test_branch_refuses_non_self_publish_and_direct_and_intake` — CLI exit 1 for each.
  - `test_plain_self_publish_still_uses_publish_rid_branch` — regression.

- [ ] **Step 2: Run** `uv run pytest tests/test_publish_branch.py -q` — FAIL.

- [ ] **Step 3: Implement.** In `publish()`: `branch` set and not `is_self` → `PublishError`; `branch` set → skip `decide_mode`, require `has_remote` and `ghio.can_open_pr`, call `_publish_on_branch`. `_publish_on_branch` = `_publish_pr` without `checkout_branch`/final `checkout`, with `push_branch(..., force=False)`. CLI: `--branch NAME`; with `--direct` or on an intake/federation route → exit 1 with a one-line reason.

- [ ] **Step 4: Run** `uv run pytest tests/test_publish_branch.py tests/test_publish*.py -q` — PASS.

- [ ] **Step 5: Commit** `feat: kb publish --branch for a rolling hub PR`.

---

### Task 8: `/kb-code-sync` skill, docs, release 1.19.0

**Files:**
- Create: `src/strata_kb/templates/init/claude-skill-kb-code-sync.md`, `claude-command-kb-code-sync.md`, `copilot-kb-code-sync.prompt.md`, `cursor-kb-code-sync.md`, `bodies/kb-code-sync.md`
- Modify: `src/strata_kb/initcmd.py:71-81` (`HUB_TEMPLATES`), `tests/test_init.py` (hub freeze at `:815` gets a named `_CODE_SYNC_WRAPPERS` list, like `_MCP_SETUP_WRAPPERS`), `tests/test_templates.py`, `README.md`, `CHANGELOG.md`, `pyproject.toml` (`1.19.0`), `uv.lock` (via `uv lock`)

**Interfaces:**
- Consumes: CLI from Tasks 1, 4, 7 (`kb authored`, `kb code-sync scan --json`, `kb code-sync baseline --at`, `kb publish --branch kb-bot/code-sync`).

- [ ] **Step 1: Write the failing tests:**
  - `test_hub_ships_kb_code_sync_wrappers` — `expected_files("hub")` contains the four paths `.claude/skills/kb-code-sync/SKILL.md`, `.claude/commands/kb-code-sync.md`, `.github/prompts/kb-code-sync.prompt.md`, `.cursor/commands/kb-code-sync.md`; `child`/`ba`/`dev` do not.
  - `test_kb_code_sync_body_states_hard_rules` — body contains `never merge`, `never \`kb approve\``, `kb publish --branch kb-bot/code-sync`, `kb code-sync scan --json`, `kb code-sync baseline --at`.
  - Existing include-marker tests in `tests/test_templates.py` cover the stubs (stubs end with `<!-- strata-kb:include bodies/kb-code-sync.md -->`).

- [ ] **Step 2: Run** `uv run pytest tests/test_init.py tests/test_templates.py -q` — FAIL.

- [ ] **Step 3: Write the templates.** Stubs copy `kb-approve`'s / `dev-code-seed`'s shape. The body is the spec §7 flow, steps 1-8, verbatim in intent (step 1's draft check is `git diff --no-index --quiet .kb/<doc> federation/<hub rid>/<doc>` per touched doc; non-zero → stop), and its HARD rules list; the PR body format of step 8; where the manager answers "needs the SA". Register the four rows in `HUB_TEMPLATES`.

- [ ] **Step 4: Docs.** README: `kb authored`, `kb code-sync scan|baseline|run`, `kb publish --branch` rows in the command tables; a "Code sync" section (flow, cadence, `hub-sync` service, env vars, App `issues: write` prerequisite). CHANGELOG `## 1.19.0 — <date>` entry. Bump `pyproject.toml`, run `uv lock`.

- [ ] **Step 5: Run** the full suite `uv run pytest -n auto -q` and `uv run ruff check src tests && uv run ruff format --check src tests && uv run pyright` — all PASS.

- [ ] **Step 6: Commit** `feat: /kb-code-sync skill, docs — 1.19.0`.
