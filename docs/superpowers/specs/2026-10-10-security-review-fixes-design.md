# Security review fixes: hub reads only `federation/`, bounded login, a working dev intake publish

**Status:** design for approval
**Source:** §5.2 findings #1, #2, #3, #4, #5, #6, #9, #10 and §8 đợt 1 item 2 of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md` (batch 1b of
that review's wave 1; batch 1a was `2026-10-10-usage-cost-review-fixes-design.md`).
**Approach:** as chosen on 2026-10-10:
- One doc-id guard shared by every reader.
- A capped receive channel on `/ui/login`.
- Byte compare for the form token.
- A read limiter on the two intake GET routes.
- `/intake/status` becomes **public but minimal**, so the zero-secret dev
  CLI works again. An OIDC caller still gets `detail`.
- The extras folded in: assets served from `federation/` only (#10), weak
  or non-ASCII server tokens refused at start (#5), timeouts on intake's
  network git calls (#9).

## Goal

README §10 promises that the hub server reads **only** `federation/`, that
login is rate-limited and bounded, and that a developer can publish through
the intake with zero secrets. The review broke all three with PoCs:

| # | Level | What breaks |
|---|---|---|
| 1 | MEDIUM | `kb_get_section(doc="../../.kb/secret-draft")` returns the hub's **unpublished** `.kb/` content and cites it as `repo-a:secret-draft`. `../other-rid/doc` gets past the `repo=` filter. The same raw join is in `web/api.load_manifest`, which `/api/docs/<doc>` and `/ui/docs/<doc>` use. |
| 2 | MEDIUM | `POST /ui/login` with a chunked body (no `Content-Length`) skips the 8 KiB check. `request.form()` then buffers up to 1 MiB per field × 1000 fields. 500–600 fields OOM-kill the whole service (MCP + REST + UI + intake). No token needed. |
| 3 | LOW | A non-ASCII form token makes `hmac.compare_digest(str, str)` raise `TypeError`, so the response is a 500. An operator token with a non-ASCII character also breaks login outright. |
| 4 | LOW | `/intake/manifest` and `/intake/status` have no limiter. Each request does a JWT RSA verify, a registry load and a hub resolve. |
| 5 | LOW | The server accepts any non-empty token, including `change-me` from `env.example`. The session cookie is `HMAC(token, issued)`, so whoever holds a cookie can brute-force a weak token offline. |
| 6 | LOW, **functional** | `publish_via_intake` polls `/intake/status` with no `Authorization`. The route has demanded OIDC since #55 (LOW-1), so every dev-machine `kb publish` through `intake:` times out after 600 s even when the hub PR is open. |
| 9 | LOW | Intake runs `git pull` / `push` under `repo_lock(rid)` and `_hub_write_lock` with no timeout. A hung remote locks publishing for every rid. |
| 10 | INFO | `/assets/{name}` globs the hub's own `.kb/` before `federation/`. |

After this batch:

1. no server or CLI read path can leave `<repo>/.kb/<doc>/` for a doc id
   that came from a caller;
2. no unauthenticated request can make the server buffer more than
   `LOGIN_MAX_BODY` bytes;
3. `kb publish` through `intake:` from a dev machine returns the hub PR URL
   again;
4. the server refuses to start on a token it cannot defend.

## Design

### 1. One doc-id guard (#1)

`models.DOC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")`. This is
the doc grammar `kbcontext._REF_RE` already enforces for `kb-context` refs,
which is why `kb_context_new` and `kb_resolve` were not affected.
`kbcontext._REF_RE` builds its `doc` group from the same pattern string, so
the two grammars cannot drift.

`query.doc_dir(kb_dir, doc_id) -> Path | None` (new, public):

- returns `None` when `doc_id` does not match `DOC_ID_RE`. The grammar
  already excludes `/`, `\` and a leading `.`, so `..` cannot appear as a
  path segment;
- as a second line of defence, returns `None` unless
  `(kb_dir / doc_id).resolve().is_relative_to(kb_dir.resolve())`. This
  catches a symlinked doc folder inside a published snapshot;
- otherwise returns `kb_dir / doc_id`.

Callers:

- `query.get_section`: the holder filter and `_get_section_in` both go
  through `doc_dir`. The guard runs **after** the `repo:doc` split, so a
  qualified `repo-a:../../.kb/x` is rejected too. `repo` itself needs no
  guard: it is only compared for equality against `meta.repo_id` of
  repos `load_federation` already found.
- `web/api.load_manifest`: covers `/api/docs/<doc>`, the section routes and
  `/ui/docs/<doc>`.

An invalid id reads as **not found**. The not-found message stays as it is
(it lists known docs) and never echoes whether a path exists. This replaces
today's `AmbiguousDocError`, which listed every repo holding the traversal
target.

### 2. Bounded `/ui/login` body (#2)

Move `_capped_receive` out of `web/intake_routes.py` into a new
`web/bodycap.py` as
`capped_receive(request, max_bytes, overflow: Callable[[], Exception])`.
Intake keeps its behaviour by passing
`lambda: intake.IntakeError(413, ...)`. The docstring explaining why an
exception raised inside `receive` survives `await form()` moves with it.

`login_post` keeps the `Content-Length` pre-check (cheap, and it spends no
lockout attempt). It then parses the form through
`Request(request.scope, capped_receive(request, LOGIN_MAX_BODY, _TooLarge))`
and turns `_TooLarge` into the same 413 response. It also passes
`max_fields=4` to `form()`, so a small body with many fields cannot cost a
parse per field. Order is unchanged: size check, then rate limit, then
parse, then compare.

### 3. Byte compare on the form token (#3)

`hmac.compare_digest(submitted.encode("utf-8"), token.encode("utf-8"))`.
Item 5 makes a non-ASCII **server** token impossible. A non-ASCII
**submitted** value is then a wrong guess: it gets the normal "Invalid
token" page and counts against the limiter like any wrong token.

### 4. Read limiter on `/intake/manifest` and `/intake/status` (#4)

A second `SlidingWindowLimiter` in `intake_routes`:
`INTAKE_READ_MAX_ATTEMPTS = 120` per `INTAKE_WINDOW_SECONDS`, keyed by
`client_key(request, cfg.trusted_proxies)`. It runs **before** any JWT work
and returns 429 `rate_limited`.

The limit is 120, not the publish route's 30, because one dev CLI polls
status every 5 s (12/min). Several developers behind one NAT share the key
when `STRATA_KB_TRUSTED_PROXIES` is 0. On a 429 the CLI simply keeps
polling, as it already does for any non-200.

### 5. Refuse a token the server cannot defend (#5)

`mcp.check_http_token(token)`, called in `main()` for the http transport
right after the empty check. It raises `SystemExit` with one line when the
token:

- is `change-me` (the shipped placeholder), or
- is shorter than 32 characters, or
- is not printable ASCII (`token.isascii() and token.isprintable()`). A
  header token is compared as `str` and cannot carry non-ASCII reliably.

The message says how to make a good one: `kb docker-setup --force`
regenerates `.env` with `secrets.token_hex(24)` (48 characters), or use
`python -c "import secrets; print(secrets.token_hex(24))"`. There is **no
override flag**: a weak token on a server that serves copyrighted documents
is the thing being fixed.

`create_http_app` does not check, so tests that build the app with a short
token keep working. Only the operator entry point refuses.

**Breaking** for a deployment with a short token. The CHANGELOG says so, and
names the one-line fix.

Out of scope for #5: signing the cookie with a secret independent of the
token. With a 128-bit+ token enforced, offline brute force of a cookie is
not practical.

### 6. `/intake/status`: public, minimal (#6)

The response depends on whether the request carries a token:

- **No `Authorization` header:** `{"state", "pr_url"}` only. No `detail`,
  ever. 404 `{"state": "unknown"}` when there is no record. This is the
  contract `docs/deploy-remote-mcp.md` and the `EXEMPT_PATHS` comment
  already describe. It keeps the LOW-1 fix intact: raw git stderr, paths
  and branch names never reach an unauthenticated caller.
- **`Authorization: Bearer <OIDC>`:** today's behaviour. The caller must be
  `rid`'s registered repo, and the full record including `detail` is
  returned. A present but invalid token is still an error (401/403). It is
  never silently downgraded to the public view.

The key is `repo_id` + full `commit` SHA, so a caller has to know the commit
to read anything. What leaks is the state and the hub PR URL, on a hub that
is itself on the internal network, the same assumption as MCP.

`publish_via_intake`:

- `state == "error"` without `detail` → `PublishError("intake rejected the
  publish — see the Actions run for tag '<tag>' in the child repo")`. The
  child CI's job summary already carries the detail (1.4.0).
- A 401 means a 1.9.x-or-older hub. The CLI fails fast instead of polling
  600 s: `"the hub's /intake/status requires a token (hub older than
  1.10.0) — the publish may still have succeeded; check the Actions run for
  tag '<tag>'. Upgrade the hub server to get the PR link here."`

Docs: `docs/deploy-remote-mcp.md` gains the detail-only-with-OIDC sentence.
The `EXEMPT_PATHS` comment and the LOW-1 comment in `status()` are rewritten
to describe the two views.

### 7. Assets from `federation/` only (#10)

`web/ui._find_asset` drops `hub.kb_dir` from its search bases. A hub whose
own documents need serving publishes them into `federation/<rid>/` like any
child, and their assets go with them. Disk cache and store fallback are
unchanged.

### 8. Network git timeouts on the intake path (#9)

`gitio.pull` already takes `timeout` (and then turns off git's prompts).
`push_branch` and `push_branch_with_token` get the same keyword-only
`timeout`, with the same prompt-off env and the same
`TimeoutExpired → GitError("<op> timed out after Ns")`.

Intake passes `timeout=INTAKE_GIT_TIMEOUT_SECONDS = 300` at
`intake.py:1657` (pull), `:1834` and `:1838` (push). CLI callers pass
nothing: a developer's interactive push or credential prompt is unchanged.

`worktree add` is local and needs no timeout. PR creation through
`ghio`/GitHub App HTTP is out of scope.

## Out of scope

- #7 (OIDC `repository_id` binding) and #8 (README telling users to commit a
  token URL). #8 is docs, and goes in batch 1c.
- #11–#14 (INFO).
- An independent cookie secret (see §5).
- Rate-limiting `/api/health`.

## Testing

Every finding gets a test that reproduces it first:

- **#1.**
  - `get_section` with `../../.kb/x`, `repo-a:../../.kb/x`,
    `../other-rid/doc`, `a/b`, `a\b` and `.hidden` returns `None`. A
    planted unpublished `.kb/secret` is never read.
  - A symlinked doc dir pointing outside `kb_dir` is refused.
  - The same cases through `kb_get_section` (MCP), `kb get` (CLI),
    `/api/docs/<doc>` and `/ui/docs/<doc>` → not found / 404.
  - Valid ids with `.` and `-` still resolve.
  - A negative test that unpublished `.kb/` never surfaces through
    `kb_search` either (closes review note C7).
- **#2.**
  - A chunked login body over 8 KiB → 413, and memory is not consumed
    (assert the receive stops at the cap).
  - 5 fields → 413 or a failed login, never a 500.
  - The existing Content-Length test is kept.
  - Intake's capped-body tests pass unchanged against the moved helper.
- **#3.** A non-ASCII submitted token → 200 login page with the error, and
  it counts against the limiter.
- **#4.** The 121st manifest/status request from one key in a window → 429
  before any JWT verify (a fake verifier counts calls). The two routes share
  a bucket, and the publish limiter is separate.
- **#5.**
  - `check_http_token` refuses `change-me`, 31 characters, and a non-ASCII
    or non-printable token, and accepts `token_hex(24)`.
  - `main()` with a weak token exits before uvicorn starts.
- **#6.**
  - No header → `{state, pr_url}` with no `detail` key, for `done`,
    `error` and `processing`.
  - Valid OIDC → full record.
  - Invalid OIDC → 401.
  - Wrong rid → 403.
  - `publish_via_intake` returns the PR URL against the real route through
    `TestClient`, not a fake `http_get_json`. That is the gap that hid this
    bug.
  - An error with no detail → the Actions message.
  - 401 → fail fast with the upgrade message, after one poll.
- **#10.** An asset present only under the hub's `.kb/` → 404 / store
  fallback. The same asset under `federation/` → served.
- **#9.**
  - `push_branch(..., timeout=0.01)` against a fake hanging git (the
    `cli_stub` pattern) → `GitError` "timed out", with
    `GIT_TERMINAL_PROMPT=0` in the child env.
  - Intake passes the timeout (monkeypatched `gitio`).

The full suite runs offline with the tiktoken stub, as the 1.9.0 batch did.

## Delivery

One PR, release **1.10.0**. It is a minor bump because two operator-visible
contracts change: the token is refused at start, and the status response
varies by auth.

CHANGELOG lines:

- traversal fixed in `kb_get_section` / `kb get` / doc routes;
- login body bounded;
- `/intake/status` is public with `{state, pr_url}`, and `detail` only for
  the OIDC caller. Dev `kb publish` through `intake:` works again;
- **breaking:** the http server refuses `change-me`, tokens under 32
  characters and non-ASCII tokens. Run `kb docker-setup --force` or set a
  `token_hex(24)` value;
- intake git calls time out after 300 s;
- `/assets/` no longer reads the hub's own `.kb/`.
