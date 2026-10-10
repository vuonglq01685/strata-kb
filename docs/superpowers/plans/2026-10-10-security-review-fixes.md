# Security review fixes Implementation Plan

**Goal:**
- No read path can leave `<repo>/.kb/<doc>/` for a doc id a caller supplied.
- No unauthenticated request can make the server buffer more than
  `LOGIN_MAX_BODY` bytes.
- Dev `kb publish` through `intake:` returns the hub PR URL again.
- The server refuses a token it cannot defend.

**Spec:** `docs/superpowers/specs/2026-10-10-security-review-fixes-design.md`

**Tech stack:** Python 3.11+, Starlette, python-multipart, pytest.

## Global constraints

- Release **1.10.0**: bump `pyproject.toml`, the `strata-kb` entry in
  `uv.lock`, and add a `## 1.10.0 — 2026-10-10` heading to the CHANGELOG.
- Every fix lands with a test that fails on `main` first.
- Test command:
  `uv run pytest -q -p tikstub`. `tikstub` is a scratchpad plugin standing
  in for `cl100k_base`, because the egress proxy blocks its download; see
  review §4.3.
- Lint: `uv run ruff check .`
- Commit messages via `git commit -F <file>`.

## Deviations from the spec (decided while planning)

Recorded during implementation:

- **Web doc routes (#1).** Starlette's `{doc}` path parameter never matches
  a decoded `/`, so `/api/docs/<doc>` and `/ui/docs/<doc>` were not
  reachable with `../` over HTTP. The tests for them pass on `main` too.
  They go through the same guard as defence in depth. The MCP tool and
  `kb get` were reachable, and their tests fail on `main`.
- **Many-fields login (#2).** Starlette turns "too many fields" into a 400
  inside a mounted app, so the test accepts 400 or 413. Login also sets
  `max_files=0`: a file part is refused rather than spooled.
- **Token check (#5).** A token containing a space is refused as well. It
  cannot survive a `.env` line or a `Bearer` header intact.
- **Short tokens in the repo.** The release smoke test
  (`.github/workflows/release.yml`) and `tests-gate/e2e/test_server.py`
  used short tokens and now use 32+ characters. README §10's
  `STRATA_KB_HTTP_TOKEN=secret` example now generates one.
- **Existing asset tests.** These planted assets under the hub's `.kb/`, so
  they now plant them under `federation/arinc-kb/`.

---

### Task 1: Doc-id guard (#1)

**Files:**
- `src/strata_kb/models.py`: `DOC_ID_PATTERN`, `DOC_ID_RE`.
- `src/strata_kb/kbcontext.py`: `_REF_RE` builds its `doc` group from
  `DOC_ID_PATTERN`.
- `src/strata_kb/query.py`: `doc_dir()`, used by `get_section` and
  `_get_section_in`.
- `src/strata_kb/web/api.py`: `load_manifest` goes through `query.doc_dir`.
- Tests: `tests/test_doc_id_guard.py` (new).

- [ ] Write failing tests. Cases:
  - `get_section` with `../../.kb/secret`, `repo-a:../../.kb/secret`,
    `../other/doc`, `a/b`, `a\b`, `.hidden` → `None`, with the planted
    secret never read.
  - A symlinked doc dir → `None`.
  - The same ids through MCP `kb_get_section`, `kb get`,
    `/api/docs/<doc>` and `/ui/docs/<doc>` → not found.
  - `kb_search` never returns the unpublished doc.
  - Ids containing `.` and `-` still resolve.
- [ ] Implement, then run the new tests plus `test_query*`, `test_web_api*`,
  `test_mcp*` and `test_kbcontext*`.

### Task 2: Shared capped receive + bounded login (#2, #3)

**Files:**
- `src/strata_kb/web/bodycap.py` (new): `capped_receive(request,
  max_bytes, overflow)`.
- `src/strata_kb/web/intake_routes.py`: uses `bodycap`.
- `src/strata_kb/web/ui.py`: `login_post` parses through the capped
  request with `max_fields=4`, and compares bytes.
- Tests: `tests/test_web_login_body.py` (new).

- [ ] Write failing tests:
  - A chunked 64 KiB body → 413, and the receive stops at the cap.
  - Many small fields → 413 or a failed login, never a 500.
  - A non-ASCII token → the login page with the error, and it counts
    against the limiter.
- [ ] Implement, then run `test_web_*` and `test_intake_http.py`.

### Task 3: Intake read limiter + public minimal status (#4, #6)

**Files:**
- `src/strata_kb/web/ratelimit.py`: `INTAKE_READ_MAX_ATTEMPTS = 120`.
- `src/strata_kb/web/intake_routes.py`: a read limiter on manifest and
  status (before JWT work), and status's two views.
- `src/strata_kb/web/auth.py`: the `EXEMPT_PATHS` comment.
- `src/strata_kb/publish.py`: `publish_via_intake` handles an error with
  no detail, and fails fast on 401.
- `docs/deploy-remote-mcp.md`.
- Tests: `tests/test_intake_http.py` (status tests updated, limiter tests)
  and `tests/test_publish_intake_cli.py` (a real-route poll through
  `TestClient`, error without detail, 401 fail-fast).

- [ ] Write failing tests, then implement, then run the intake and publish
  tests.

### Task 4: Server token strength (#5)

**Files:**
- `src/strata_kb/mcp.py`: `check_http_token()`, called in `main()`.
- Tests: `tests/test_mcp_token_strength.py` (new).

- [ ] Write failing tests:
  - `change-me`, 31 characters, a non-ASCII token and a token with a
    control character are refused.
  - `token_hex(24)` is accepted.
  - `main()` exits before uvicorn starts.
- [ ] Implement. Check existing `main()` tests for short tokens and
  update them.

### Task 5: Assets from `federation/` only (#10)

**Files:**
- `src/strata_kb/web/ui.py`: `_find_asset`.
- Tests:
  `tests/test_web_assets_federation_only.py` (new).

- [ ] Write a failing test: an asset only under the hub `.kb/` is not
  served from there, and under `federation/` it is. Then implement.

### Task 6: Intake git timeouts (#9)

**Files:**
- `src/strata_kb/gitio.py`: `push_branch` and `push_branch_with_token`
  get `timeout=`.
- `src/strata_kb/intake.py`: `INTAKE_GIT_TIMEOUT_SECONDS = 300`, passed at
  pull and both pushes.
- Tests: `tests/test_gitio_timeout.py` (new).

- [ ] Write failing tests:
  - A hanging fake git → `GitError` "timed out", with
    `GIT_TERMINAL_PROMPT=0` in the child env.
  - Intake passes the timeout.
- [ ] Implement.

### Task 7: Release

- [ ] Bump the version to 1.10.0 (`pyproject.toml`, `uv.lock`) and add the
  CHANGELOG entry from spec §Delivery.
- [ ] Full suite, then `ruff check .`, then commit and push.
