# Hub Accounts, Registry Page, Auto-merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Username/password accounts with roles on the hub UI, an admin-only Registry page that edits `federation/registry.yaml`, and a per-repo `auto_merge` flag that makes intake merge its own publish PR.

**Architecture:** A new stdlib-only `serving/accounts.py` (SQLite users + scrypt + session key + env bootstrap) feeds the existing `TokenAuthMiddleware`, which now attaches `request.state.user` for a valid session cookie. A pure `registryedit.py` computes registry changes and a small git helper lands them on the hub's default branch with the intake GitHub App token. Auto-merge is a post-step in the intake route: after `intake_publish` returns a PR URL, `intake.auto_merge_pr` merges it when the registry entry says so.

**Tech Stack:** Python 3, Starlette, Jinja2, Typer, pydantic, stdlib `sqlite3` / `hashlib.scrypt` / `secrets` / `hmac`, pytest, ruff, pyright.

**Spec:** `docs/superpowers/specs/2026-10-14-hub-accounts-registry-automerge-design.md`

## Global Constraints

- No new dependency. Accounts use stdlib `sqlite3`, `hashlib.scrypt`, `secrets`, `hmac`.
- No password, password hash, or default credential in any committed file (source, template, test fixture uses a throwaway value generated in the test).
- Roles are exactly `("admin", "ba", "dev")`.
- Accounts dir: `<config.kb_dir.parent>/.kb-auth/` → `users.db`, `session.key` (0600, 32 random bytes).
- Bootstrap env vars: `STRATA_KB_BOOTSTRAP_ADMIN`, `STRATA_KB_BOOTSTRAP_PASSWORD_HASH`. Hash only, never plaintext.
- Hash string format: `scrypt$n=16384,r=8,p=1$<salt-b64>$<hash-b64>`, 16-byte salt, 64-byte key.
- Session cookie name stays `strata_kb_session`, max age stays `SESSION_MAX_AGE` (43200), signed with `session.key`, **never** with `STRATA_KB_HTTP_TOKEN`.
- Bearer token still passes auth on every path but never carries a user/role.
- Registry pushes are **never** force-pushes to the default branch.
- Intake status states stay `processing` / `done` / `error`; new optional field `merged`.
- Gates before every commit: `ruff check .`, `ruff format --check .`, `pyright`, `pytest` (T0 + T1 in README).
- Version bump `1.25.0` → `1.26.0` with a CHANGELOG entry (Task 7).

## Review Focus

- Username case: `Vuonglq01685` at login must find `vuonglq01685` (column is `COLLATE NOCASE`) — test in Task 1.
- A role downgrade or password reset while a browser is logged in must take effect on the very next request — tests in Task 3.
- An admin removes the repo that is publishing right now, or toggles auto-merge mid-publish: no crash, publish completes under whatever registry `_authorize` read — covered by Task 6 using the registry from `_authorize` only.
- Registry POST with a stale view (entry already removed by another tab) must give a clear 409/400 message, not a 500 — test in Task 5.
- Hub restart with `.kb-auth/` already present and bootstrap vars still in `.env`: no duplicate user, no error, info log only — test in Task 1.

---

### Task 1: Accounts store

**Files:**
- Create: `src/strata_kb/serving/accounts.py`
- Test: `tests/test_accounts.py`

**Interfaces:**
- Produces:
  - `ROLES: tuple[str, ...] = ("admin", "ba", "dev")`
  - `class AccountError(KbError)`
  - `@dataclass(frozen=True) class User: username: str; role: str; password_hash: str; created_at: str; updated_at: str`
  - `hash_password(password: str) -> str`
  - `check_password(password: str, stored: str) -> bool`
  - `password_version(stored: str) -> str` — first 16 hex chars of sha256(stored)
  - `class Accounts: __init__(self, db_path: Path)`; methods `count() -> int`, `get(username) -> User | None`, `list() -> list[User]`, `add(username, password, role) -> User`, `add_hashed(username, password_hash, role) -> User`, `set_password(username, password) -> None`, `set_role(username, role) -> None`, `remove(username) -> None`, `verify(username, password) -> User | None`
  - `auth_dir_for(kb_dir: Path) -> Path` → `kb_dir.parent / ".kb-auth"`
  - `load_or_create_session_key(auth_dir: Path) -> bytes`
  - `bootstrap_from_env(accounts: Accounts, env: Mapping[str, str]) -> str` — returns the log line it emitted ("" when nothing to say)
  - `ensure_git_exclude(repo_root: Path) -> bool` — True when it appended `.kb-auth/` to `.git/info/exclude`

- [ ] **Step 1: Write the failing tests** in `tests/test_accounts.py`:

```python
def test_hash_round_trip_and_format():
    h = hash_password("pw-1")
    assert h.startswith("scrypt$n=16384,r=8,p=1$")
    assert check_password("pw-1", h) and not check_password("pw-2", h)
    assert hash_password("pw-1") != h  # fresh salt

def test_check_password_rejects_malformed_hash():
    assert check_password("x", "not-a-hash") is False

def test_add_get_is_case_insensitive(tmp_path):
    a = Accounts(tmp_path / "users.db")
    a.add("vuonglq01685", "pw", "admin")
    assert a.get("VuongLQ01685").username == "vuonglq01685"
    assert a.verify("VUONGLQ01685", "pw").role == "admin"
    assert a.verify("vuonglq01685", "bad") is None
    assert a.verify("nobody", "pw") is None

def test_add_rejects_bad_role_and_duplicate(tmp_path):
    a = Accounts(tmp_path / "users.db")
    with pytest.raises(AccountError): a.add("u", "pw", "root")
    a.add("u", "pw", "dev")
    with pytest.raises(AccountError): a.add("U", "pw", "dev")

def test_last_admin_cannot_be_removed_or_demoted(tmp_path):
    a = Accounts(tmp_path / "users.db"); a.add("boss", "pw", "admin")
    with pytest.raises(AccountError): a.remove("boss")
    with pytest.raises(AccountError): a.set_role("boss", "dev")

def test_set_password_changes_version(tmp_path):
    a = Accounts(tmp_path / "users.db"); a.add("u", "pw", "dev")
    before = password_version(a.get("u").password_hash)
    a.set_password("u", "pw2")
    assert password_version(a.get("u").password_hash) != before

def test_session_key_is_stable_and_private(tmp_path):
    k1 = load_or_create_session_key(tmp_path / ".kb-auth")
    assert len(k1) == 32 and load_or_create_session_key(tmp_path / ".kb-auth") == k1
    assert oct((tmp_path / ".kb-auth" / "session.key").stat().st_mode & 0o777) == "0o600"  # skip on Windows

def test_bootstrap_creates_admin_only_when_empty(tmp_path):
    a = Accounts(tmp_path / "users.db")
    env = {"STRATA_KB_BOOTSTRAP_ADMIN": "boss",
           "STRATA_KB_BOOTSTRAP_PASSWORD_HASH": hash_password("pw")}
    assert "created" in bootstrap_from_env(a, env)
    assert a.verify("boss", "pw").role == "admin"
    assert "ignored" in bootstrap_from_env(a, env)  # restart: no duplicate, no raise
    assert a.count() == 1

def test_bootstrap_with_one_var_creates_nothing(tmp_path):
    a = Accounts(tmp_path / "users.db")
    msg = bootstrap_from_env(a, {"STRATA_KB_BOOTSTRAP_ADMIN": "boss"})
    assert "STRATA_KB_BOOTSTRAP_PASSWORD_HASH" in msg and a.count() == 0

def test_bootstrap_rejects_plaintext_in_hash_var(tmp_path):
    a = Accounts(tmp_path / "users.db")
    msg = bootstrap_from_env(a, {"STRATA_KB_BOOTSTRAP_ADMIN": "boss",
                                 "STRATA_KB_BOOTSTRAP_PASSWORD_HASH": "plain-password"})
    assert a.count() == 0 and "kb user hash" in msg

def test_ensure_git_exclude_is_idempotent(tmp_path, run_git):
    run_git(tmp_path, "init")
    assert ensure_git_exclude(tmp_path) is True
    assert ensure_git_exclude(tmp_path) is False
    assert (tmp_path / ".git/info/exclude").read_text().count(".kb-auth/") == 1

def test_ensure_git_exclude_outside_git_is_noop(tmp_path):
    assert ensure_git_exclude(tmp_path) is False
```

- [ ] **Step 2: Run** `pytest tests/test_accounts.py -v` — Expected: FAIL (module not found).
- [ ] **Step 3: Implement `src/strata_kb/serving/accounts.py`.** Table per spec §5.1 (`username TEXT PRIMARY KEY COLLATE NOCASE`, `CHECK(role IN ...)`). One short-lived `sqlite3.connect` per call (no shared connection across threads). `verify` runs `check_password` against a module-level dummy hash when the user does not exist, so timing does not reveal existence. `bootstrap_from_env` logs via `logging.getLogger("strata_kb.accounts")` and never logs the hash. `session.key` written with `os.open(..., O_CREAT|O_EXCL|O_WRONLY, 0o600)`; the dir created with `mkdir(parents=True, exist_ok=True)`.
- [ ] **Step 4: Run** `pytest tests/test_accounts.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: SQLite accounts store with scrypt hashes and env bootstrap`.

---

### Task 2: `kb user` CLI

**Files:**
- Modify: `src/strata_kb/cli.py` (new `user_app = typer.Typer(help="Hub UI accounts: add, passwd, role, remove, list, hash.")`, `app.add_typer(user_app, name="user")`)
- Test: `tests/test_cli_user.py`

**Interfaces:**
- Consumes: Task 1 `Accounts`, `hash_password`, `auth_dir_for`, `AccountError`.
- Produces: commands `kb user add <username> --role <role> [--kb .kb]`, `kb user passwd <username>`, `kb user role <username> <role>`, `kb user remove <username>`, `kb user list`, `kb user hash`. All except `hash` open `auth_dir_for(kb) / "users.db"`.

- [ ] **Step 1: Write the failing tests** using `typer.testing.CliRunner` with `input=` for the prompts:

```python
def test_user_add_prompts_twice_and_stores(tmp_path):
    r = runner.invoke(app, ["user", "add", "boss", "--role", "admin", "--kb", str(tmp_path / ".kb")],
                      input="pw-123\npw-123\n")
    assert r.exit_code == 0
    assert Accounts(tmp_path / ".kb-auth/users.db").verify("boss", "pw-123")

def test_user_add_mismatched_confirmation_fails(tmp_path): ...  # input "a\nb\n" -> exit != 0, count() == 0

def test_user_list_never_prints_hashes(tmp_path): ...  # "scrypt$" not in output, "boss" and "admin" in output

def test_user_remove_last_admin_exits_1(tmp_path): ...

def test_user_hash_prints_verifiable_hash():
    r = runner.invoke(app, ["user", "hash"], input="pw\npw\n")
    line = r.output.strip().splitlines()[-1]
    assert check_password("pw", line)
```

- [ ] **Step 2: Run** `pytest tests/test_cli_user.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement** with `typer.prompt(..., hide_input=True, confirmation_prompt=True)`; `AccountError` → message on stderr, exit 1 (follow the CLI's existing `KbError` handling pattern).
- [ ] **Step 4: Run** tests — Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb user CLI for hub accounts`.

---

### Task 3: Username/password login and user sessions

**Files:**
- Modify: `src/strata_kb/serving/auth.py` (session format, middleware attaches user)
- Modify: `src/strata_kb/web/ui.py` (`login_post`, `_shell_ctx` gets `is_admin`)
- Modify: `src/strata_kb/web/app.py` (build `Accounts`, key, bootstrap, git exclude; pass to middleware and `ui.build_routes`)
- Modify: `src/strata_kb/templates/web/login.html`, `src/strata_kb/cli.py` (any "sign in with the token" text)
- Modify: `tests/conftest.py` (`web_client_logged_in`, new `admin_user` fixture), `tests/test_web_session.py`, `tests/test_web_login_body.py`, `tests/test_web_auth_ratelimit.py`, `tests/test_web_auth.py`, `tests/test_cli_errors.py` — wherever they post `{"token": ...}` to `/ui/login`
- Test: `tests/test_web_accounts_login.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `make_user_session(key: bytes, user: User, now: float | None = None) -> str` → `<issued>.<b64url(username)>.<password_version>.<hmac>`
  - `read_user_session(value: str, key: bytes, now: float | None = None) -> tuple[str, str] | None` → `(username, pw_ver)` when signature and age are valid
  - `class SessionAuth: key: bytes; accounts: Accounts` with `user_for(cookie_value: str) -> User | None` (checks user exists and `password_version` matches)
  - `TokenAuthMiddleware(app, token, limiter=None, trusted_proxies=0, session: SessionAuth | None = None)`; on a valid cookie it sets `scope.setdefault("state", {})["user"] = user`; bearer requests get no `user`.
  - `is_authorized_request(request, token, session=None) -> bool` — bearer OR `session.user_for(cookie)`.
  - `current_user(request) -> User | None` (reads `request.state.user`, default None)
  - `ui.build_routes(config, token, login_limiter=None, trusted_proxies=0, session: SessionAuth | None = None)`
  - Shell context key `is_admin: bool`.
  - Conftest fixtures: `admin_user(hub_dir) -> tuple[str, str]` (creates `admin`/random password in `hub_dir/.kb-auth`), `web_client_logged_in` logs in via `{"username", "password"}`.
  - `create_app` makes the `SessionAuth` from `auth_dir_for(config.kb_dir)`, runs `bootstrap_from_env(accounts, os.environ)` and `ensure_git_exclude(config.kb_dir.parent)` once.

- [ ] **Step 1: Write failing tests** in `tests/test_web_accounts_login.py`:

```python
def test_login_with_username_password_sets_cookie(web_client, admin_user):
    u, pw = admin_user
    r = web_client.post("/ui/login", data={"username": u, "password": pw}, follow_redirects=False)
    assert r.status_code == 303 and COOKIE_NAME in r.cookies

def test_wrong_password_and_unknown_user_same_message(web_client, admin_user):
    a = web_client.post("/ui/login", data={"username": admin_user[0], "password": "x"})
    b = web_client.post("/ui/login", data={"username": "ghost", "password": "x"})
    assert "Wrong username or password" in a.text and "Wrong username or password" in b.text

def test_token_in_login_form_no_longer_logs_in(web_client, token): ...  # data={"username": "", "password": token} -> no cookie

def test_empty_accounts_login_page_explains_bootstrap(web_client):
    r = web_client.get("/ui/login")
    assert "kb user add" in r.text and "STRATA_KB_BOOTSTRAP_ADMIN" in r.text

def test_cookie_signed_with_bearer_token_is_rejected(web_client, admin_user, token):
    forged = make_user_session(token.encode(), User(admin_user[0], "admin", "h", "", ""))
    web_client.cookies.set(COOKIE_NAME, forged)
    assert web_client.get("/ui", follow_redirects=False).status_code == 302

def test_password_change_ends_session(web_client_logged_in, hub_dir, admin_user):
    Accounts(hub_dir / ".kb-auth/users.db").set_password(admin_user[0], "new-pw")
    assert web_client_logged_in.get("/ui", follow_redirects=False).status_code == 302

def test_removed_user_session_ends(...): ...  # add 2nd admin, log in as it, remove it -> 302

def test_bearer_request_has_no_user(web_client, token): ...  # GET /ui with Bearer -> 200, nav has no "Registry"

def test_admin_sees_registry_nav(web_client_logged_in): ...  # 'href="/ui/registry"' in GET /ui

def test_old_format_cookie_rejected(web_client, token):
    web_client.cookies.set(COOKIE_NAME, make_session(token))  # pre-1.26 format
    assert web_client.get("/ui", follow_redirects=False).status_code == 302
```

- [ ] **Step 2: Run** `pytest tests/test_web_accounts_login.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.** Keep the login body cap, `max_fields` (raise to 4 → covers username, password), the shared limiter, the 413/429 paths and "never log submitted values" exactly as in today's `login_post`. Error copy: `"Wrong username or password."`. Empty-accounts copy on the login page: `No account exists yet. Create one with: docker compose exec hub kb user add <name> --role admin — or set STRATA_KB_BOOTSTRAP_ADMIN and STRATA_KB_BOOTSTRAP_PASSWORD_HASH (from kb user hash) in .env and restart.` `make_session`/`verify_session` (old format) are deleted once nothing calls them. `_credential_presented` keeps its current semantics.
- [ ] **Step 4: Update the existing login tests** to the new form fields; every behaviour they pinned (body cap, chunked body, multipart refusal, non-ASCII guess → failed login not 500, shared rate-limit bucket, httponly/secure cookie) must still be asserted.
- [ ] **Step 5: Run** `pytest tests/test_web_*.py tests/test_cli_errors.py tests/test_mcp_http.py -v` then full `pytest` — Expected: PASS.
- [ ] **Step 6: Commit** `feat: username/password hub login with role-carrying sessions`.

---

### Task 4: Registry model flag and pure edits

**Files:**
- Modify: `src/strata_kb/models.py` (`RegistryEntry.auto_merge: bool = False`)
- Create: `src/strata_kb/registryedit.py`
- Modify: `src/strata_kb/gitio.py` (non-force push helper)
- Test: `tests/test_registryedit.py`, `tests/test_models.py` (one case)

**Interfaces:**
- Produces:
  - `RegistryChange = Literal["add", "remove", "auto-merge"]`
  - `add_entry(reg: Registry, repo: str, repo_id: str, kind: str = "", workflow: str = "", auto_merge: bool = False) -> Registry`
  - `remove_entry(reg: Registry, repo: str) -> Registry`
  - `set_auto_merge(reg: Registry, repo: str, on: bool) -> Registry`
  - `dump_registry(reg: Registry) -> str` — YAML with top key `repos:`; an entry with only `repo_id` set dumps as the plain string; otherwise a mapping with only the non-default fields; key order preserved, new keys appended.
  - `commit_registry(hub_root: Path, text: str, message: str, push: Callable[[Path, str], None]) -> None` — in a temp worktree based on `gitio.default_branch(hub_root)`: write `federation/registry.yaml`, re-validate via `models.Registry`, `gitio.commit_paths`, then `push(worktree, default_branch)`; worktree always removed.
  - `gitio.push_head_with_token(root: Path, url: str, token: str, dest_branch: str, *, timeout: float | None = None) -> None` — `git push <url> HEAD:refs/heads/<dest_branch>` **without** `--force`, credentials via env exactly like `push_branch_with_token`; raises `GitError` on rejection.
  - All edit functions raise `KbError` with a user-facing message.

- [ ] **Step 1: Write failing tests**:

```python
def test_auto_merge_defaults_false_and_plain_string_still_loads():
    reg = Registry.model_validate({"repos": {"a/b": "rb", "c/d": {"repo_id": "rd", "auto_merge": True}}})
    assert reg.resolve("a/b").auto_merge is False and reg.resolve("c/d").auto_merge is True

def test_add_entry_validates_repo_id_and_uniqueness():
    reg = Registry(repos={"a/b": "rb"})
    with pytest.raises(KbError): add_entry(reg, "A/B", "x")        # case-colliding key
    with pytest.raises(KbError): add_entry(reg, "e/f", "rb")       # repo-id claimed
    with pytest.raises(KbError): add_entry(reg, "e/f", "../evil")  # normalize_repo_id
    with pytest.raises(KbError): add_entry(reg, "e/f", "ok", kind="nope")
    assert add_entry(reg, "e/f", "rf", kind="dev", auto_merge=True).resolve("e/f").auto_merge

def test_remove_and_toggle_unknown_key_raise():
    with pytest.raises(KbError): remove_entry(Registry(), "x/y")
    with pytest.raises(KbError): set_auto_merge(Registry(), "x/y", True)

def test_inputs_are_not_mutated():
    reg = Registry(repos={"a/b": "rb"}); set_auto_merge(reg, "a/b", True)
    assert reg.repos == {"a/b": "rb"}

def test_dump_round_trips_and_keeps_order():
    reg = Registry(repos={"z/z": "rz", "a/a": {"repo_id": "ra", "auto_merge": True}})
    text = dump_registry(reg)
    assert text.index("z/z") < text.index("a/a") and "rz" in text
    assert Registry.model_validate(yaml.safe_load(text)) == reg

def test_commit_registry_lands_on_default_branch(fed_hub, run_git):
    pushed = []
    commit_registry(fed_hub, "repos: {}\n", "registry: test (by admin)", lambda wt, br: pushed.append(br))
    assert pushed == [gitio.default_branch(fed_hub)]
    # worktree removed, hub checkout untouched
    assert gitio.is_dirty(fed_hub, Path("federation")) is False
```

- [ ] **Step 2: Run** `pytest tests/test_registryedit.py tests/test_models.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.** Reuse `pubgate.normalize_repo_id`; whole-file re-validation uses `models.Registry.model_validate` only (load-time rules). Worktree add/remove under `intake._hub_write_lock` (import it) so it never races an intake worktree add.
- [ ] **Step 4: Run** tests — Expected: PASS. Run `pytest tests/test_federation_registry.py tests/test_publish_registry.py tests/test_registrykind.py` — Expected: PASS (no regression from the new field).
- [ ] **Step 5: Commit** `feat: registry auto_merge flag and pure registry edits`.

---

### Task 5: Registry page (admin only)

**Files:**
- Create: `src/strata_kb/web/registry_routes.py`, `src/strata_kb/templates/web/registry.html`
- Modify: `src/strata_kb/web/app.py` (wire routes), `src/strata_kb/templates/web/_partials/left_rail.html` (nav item when `shell.is_admin`), `src/strata_kb/templates/web/static/style.css` (switch + table, reuse existing tokens)
- Test: `tests/test_web_registry.py`

**Interfaces:**
- Consumes: Task 3 `current_user`, `SessionAuth`; Task 4 edit functions, `commit_registry`, `gitio.push_head_with_token`; `federation.load_registry`, `gitio.log_commits`, `hub_mod.pull_once`, `ghapp.mint_installation_token`, `ghapp.repo_full_from_url`.
- Produces:
  - `build_registry_routes(config: ServerConfig, intake_cfg: IntakeConfig | None, session: SessionAuth, push: Callable[[Path, str], None] | None = None) -> list[Route]`
  - Routes: `GET /ui/registry`, `POST /ui/registry/add` (fields `repo`, `repo_id`, `kind`, `workflow`, `auto_merge`), `POST /ui/registry/remove` (`repo`, `confirm=yes`), `POST /ui/registry/auto-merge` (`repo`, `on` = `1|0`); every POST also carries `csrf`.
  - `csrf_token(key: bytes, cookie_value: str) -> str` — HMAC of the session cookie value with a fixed `b"csrf"` label.
  - `push=None` → real push: mint the App installation token for the hub repo (`intake_cfg.creds`) and call `gitio.push_head_with_token`; then `hub_mod.pull_once(config.hub)`.
  - Read-only mode (spec §6.3): `intake_cfg is None` or `not gitio.has_remote(hub_root)` → page renders with a banner, no forms, POSTs return 409.
  - Commit message: `registry: <add|remove|auto-merge on|auto-merge off> <repo> (by <username>)`.
  - A new process-wide `registry_lock = threading.Lock()` held around read-modify-commit-push.

- [ ] **Step 1: Write failing tests** (inject `push` that records calls; use `web_client_logged_in` + a non-admin fixture):

```python
def test_anonymous_redirects_bearer_and_non_admin_get_403(web_client, token, dev_client):
    assert web_client.get("/ui/registry", follow_redirects=False).status_code == 302
    assert web_client.get("/ui/registry", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert dev_client.get("/ui/registry").status_code == 403
    assert dev_client.post("/ui/registry/add", data={...}).status_code == 403

def test_admin_lists_entries_and_history(admin_registry_client): ...  # repo keys, repo-ids, switch state, last commit subject

def test_post_without_or_with_wrong_csrf_is_403(admin_registry_client): ...

def test_add_writes_yaml_commits_and_pushes(admin_registry_client, fed_hub, pushes):
    r = admin_registry_client.post("/ui/registry/add", data={..., "repo": "acme/new", "repo_id": "new", "kind": "dev", "auto_merge": "on", "csrf": csrf})
    assert r.status_code == 303 and len(pushes) == 1
    assert "registry: add acme/new (by admin)" in commit_subjects(fed_hub)

def test_toggle_auto_merge_and_remove(admin_registry_client, ...): ...

def test_invalid_add_leaves_file_untouched_and_shows_message(...): ...  # repo_id "../x" -> 400, registry.yaml bytes unchanged, no push

def test_remove_of_already_removed_key_is_409_with_message(...): ...  # stale tab

def test_read_only_when_intake_disabled(...): ...  # intake_cfg=None -> GET 200 with banner text, POST 409, no forms

def test_push_rejected_shows_error_and_no_local_change(...): ...  # push raises GitError -> 502 page, hub checkout clean
```

- [ ] **Step 2: Run** `pytest tests/test_web_registry.py -v` — Expected: FAIL.
- [ ] **Step 3: Implement.** Layout follows the mockup (`https://claude.ai/artifact/3EQrSt8ouGD83RB7BzYWjm`) and the hub's existing `style.css` tokens: add form on top, table (Repository, repo_id, Kind badge, Workflow pin, Auto-merge switch, Remove), "Recent changes" from `gitio.log_commits(hub_root, "federation/registry.yaml")` (last 10). Remove is two-step in-page (first POST without `confirm=yes` re-renders with a confirm button). Remove copy says published content under `federation/<repo_id>/` is not deleted. Workflow pin placeholder: `owner/repo/.github/workflows/kb-code.yml@refs/heads/main`. Responses `no-store`.
- [ ] **Step 4: Run** `pytest tests/test_web_registry.py tests/test_web_ui.py tests/test_web_headers.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: admin-only registry page on the hub UI`.

---

### Task 6: Auto-merge after intake publish

**Files:**
- Modify: `src/strata_kb/ghapp.py` (`merge_pr`), `src/strata_kb/intake.py` (`auto_merge_pr`, `IntakeConfig.merge_hook`), `src/strata_kb/web/intake_routes.py` (call it, `merged` field), `src/strata_kb/intake.py` `StatusStore.set` (optional `merged`), `src/strata_kb/cipublish.py` and `src/strata_kb/publish.py` (print merged)
- Test: `tests/test_ghapp.py`, `tests/test_intake_http.py`, `tests/test_cli_ci_publish_summary.py` (or the existing cipublish test file)

**Interfaces:**
- Produces:
  - `ghapp.parse_pr_url(url: str) -> tuple[str, int]` → `("owner/repo", number)`; raises `GHAppError` on anything else.
  - `ghapp.merge_pr(repo_full: str, token: str, number: int, method: str = "merge", http=_default_http) -> None` — `PUT {API}/repos/{repo_full}/pulls/{number}/merge` with `{"merge_method": method}`; 200 → return; 405 with method `merge` → retry once with `squash`; anything else → `GHAppError(f"merge PR #{number} on '{repo_full}' -> {status}: {message}")`.
  - `IntakeConfig.merge_hook: Callable[[str], None] | None = None` (test seam; receives the PR URL).
  - `intake.auto_merge_pr(cfg: IntakeConfig, pr_url: str) -> tuple[bool, str]` → `(merged, detail)`; never raises `GHAppError`/`GitError` (returns `(False, reason)`); on success calls `hub_mod.pull_once(cfg.hub_ref)` and swallows its failure with a warning.
  - `StatusStore.set(..., merged: bool | None = None)` — key written only when not None.
  - Intake JSON response and status: `{"repo_id", "pr_url", "merged": bool}` when a PR exists.

- [ ] **Step 1: Write failing tests**:

```python
# test_ghapp.py
def test_merge_pr_puts_merge_method(): ...  # fake http records PUT body {"merge_method": "merge"}, 200 -> None
def test_merge_pr_falls_back_to_squash_on_405(): ...
def test_merge_pr_raises_with_status_and_message_on_409(): ...
def test_parse_pr_url(): assert parse_pr_url("https://github.com/o/r/pull/12") == ("o/r", 12)

# test_intake_http.py (existing fixtures: registry entry for the OIDC repository)
def test_auto_merge_entry_merges_and_reports_merged(...):  # merge_hook records url; response merged True; status merged True, state "done"
def test_plain_and_false_entries_never_merge(...):        # merge_hook not called; merged False
def test_merge_failure_keeps_publish_done_with_detail(...):  # merge_hook raises GHAppError -> 200, state "done", merged False, detail mentions failure (OIDC caller only)
def test_no_change_publish_does_not_merge(...):           # pr_url "" -> merge_hook not called
def test_decision_uses_registry_read_by_authorize(...):    # flip registry.yaml on disk after _authorize -> still uses the read one

# cipublish
def test_ci_publish_prints_merged(...):  # response {"pr_url": u, "merged": true} -> output contains "merged: " + u
```

- [ ] **Step 2: Run** those tests — Expected: FAIL.
- [ ] **Step 3: Implement.** In the intake route, after `intake_publish` returns a non-empty `pr_url`, look up `registry.resolve(claims["repository"])` (the `registry` returned by `_authorize`) and, when `auto_merge`, run `intake.auto_merge_pr` via `run_in_threadpool` inside the same `concurrency_limiter` block. `auto_merge_pr` mints the token with `ghapp.mint_installation_token(cfg.creds, repo_full, http=cfg.http or default)` unless `merge_hook` is set. Log merge failures at warning with status and message. `publish.py` polling logic is unchanged (`done`/`error` only).
- [ ] **Step 4: Run** `pytest tests/test_ghapp.py tests/test_intake_http.py tests/test_intake_publish.py tests/test_publish_intake_cli.py tests/test_cli_ci_publish_summary.py -v` — Expected: PASS.
- [ ] **Step 5: Commit** `feat: intake auto-merges publish PRs for auto_merge registry entries`.

---

### Task 7: Docs, templates, version

**Files:**
- Modify: `src/strata_kb/templates/init/QUICKSTART-hub.md`, `src/strata_kb/templates/init/QUICKSTART-dev.md` (step 3 auto-merge paragraph, step 7 seed-PR review sentence), `src/strata_kb/templates/init/env.example` (two commented bootstrap vars + pointer to `kb user hash`), `src/strata_kb/templates/init/hub-gitignore.txt` (`.kb-auth/`), README sections that describe hub UI login or the auto-merge policy, `docs/` guide sources that state the old path-scoped policy (grep `auto-merge`), `CHANGELOG.md`, `pyproject.toml` version → `1.26.0`, `uv.lock` if it pins the project version
- Test: existing `tests/test_templates.py`, `tests/test_readme.py`, `tests/test_init.py`

- [ ] **Step 1:** `grep -rn "auto-merge\|sign in with the token\|/ui/login" README.md docs src/strata_kb/templates` and update every hit to the new behaviour (spec §8). QUICKSTART-hub gets: bootstrap via env (with `kb user hash`), or `docker compose exec hub kb user add <name> --role admin`; Registry page; GitHub App needs `contents: write` + `pull_requests: write`; a protected default branch must allow the App to push; `.kb-auth/` is never committed; deleting `.kb-auth/session.key` logs everyone out.
- [ ] **Step 2:** Add a test in `tests/test_init.py` that `kb init --kind hub` writes `.kb-auth/` into `.gitignore`, and in `tests/test_templates.py` that `env.example` mentions both bootstrap vars only as comments.
- [ ] **Step 3: Run** `ruff check . && ruff format --check . && pyright && pytest` — Expected: all green.
- [ ] **Step 4: Commit** `docs: hub accounts, registry page and auto-merge — 1.26.0`.
