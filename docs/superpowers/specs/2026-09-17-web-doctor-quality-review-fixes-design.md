# Web + doctor + engineering-quality review fixes — the health tool stops crashing, the HTTP surface catches up with the rest of the code

**Status:** approved design, ready for an implementation plan
**Source:** reviewer H of the 2026-09-08 full framework review,
`docs/superpowers/reviews/2026-09-08-full-framework-review/H-web-doctor-quality.md`
(findings H1…H3, M4…M18, L19…L29).
**Predecessor:** `2026-09-15-dev-workflow-usage-review-fixes-design.md`
(reviewer F, PR #47). That batch gave the Dev side's promises a machine
anchor each; this batch does the same for the two things the framework
sells as trustworthy — `kb doctor` as the health check, and the HTTP
surface as a read-only window on the hub.
**Baseline:** the review ran against `main` @ 4b47b4c, v0.20.0. This spec
is written against HEAD 3f4ed58, v0.23.0, after a full finding-by-finding
staleness sweep (§ "Staleness sweep"). Five findings are already closed;
four shrank.
**Approach:** as approved on 2026-09-17 — one guard in the shared hub
funnel rather than per-command patches; a signed stateless session value
in place of the raw bearer cookie; one rate-limit bucket shared by the
login form and the header path; strict models on authored files but not on
the federation wire format; and the doctor blind spots that cost nothing
to close.

## Goal

Reviewer H probed a live server (XSS, traversal, auth, headers, rate
limits), corrupted a pristine KB 18 ways one at a time, ran 12 `kb diff`
scenarios, and audited the tree for exception handling, exit codes and
newline discipline. Most of what it found is *good*: constant-time token
compares on both paths, no token accepted in a query string, textbook XSS
escaping through a hand-written renderer with no link syntax at all, 10/10
traversal probes rejected, C7 hub-first holding on every web read, no
tracebacks in HTTP responses, and 1875 tests passing with 3960 asserts and
no mocking library anywhere.

What does not hold splits in two.

**`kb doctor` is the tool that crashes.** It dies with a rich
`ValidationError` traceback on an invalid `.kb/config.yaml` — the one input
it has a dedicated handler for — because the hub is resolved before the
config is checked. It also calls six realistic corruptions clean:
duplicate section ids, orphan L2 headings, stale token counts, an L3 file
edited after its L2, a typo'd manifest key (every summary silently becomes
`""`), and published content tampered with in place on the hub. And on the
same unreadable-config
condition where `kb publish` fails closed with an explicit "must not
silently blind the cycle guard" comment, doctor fails open.

**The HTTP surface is the one layer that did not get the hardening pass.**
The `/ui` session cookie *is* the shared secret that also authorises
`/api` and `/mcp`, with no `Secure` flag, no expiry and no way to log out.
No response carries a single security header. The login rate limiter —
whose own module docstring calls itself "defense-in-depth for the
shared-secret login" — is side-stepped completely by sending the same
secret in an `Authorization` header, which nothing limits. A corrupt
federation manifest takes the doc routes down with a bare 500 instead of
rendering inside the shell the redesign spec specifies.

Plus a tail of smaller truth problems: the README documents `kb diff` as
doing the opposite of what it does, in the middle of the BA→Dev workflow;
exit code 2 means both "citation stale" and "you passed the wrong flags";
`kb diff` never compares titles or ordering; and `ruff check passed`
carries almost no signal because only the default rule set is enabled,
which leaves all 11 `# noqa: BLE001` markers in `src/` inert.

## Staleness sweep (2026-09-17)

Three parallel read-only verifications against HEAD 3f4ed58. Findings that
waves C–F already closed, dropped from this batch:

| Finding | Closed by |
| --- | --- |
| **M7** limiter keys on raw peer IP, no proxy knob | `ratelimit.trusted_proxies_from_env()` + `client_key()` (N-th hop from the right, per-line XFF collection), wired into `ui.py:203` login and the intake route (F-D12 item 4). The knob exists; what remains is that it never reaches the header path — folded into M6. |
| **M12** "hub has no remote" when it has one | `PublishReport.remote` (`publish.py:38-45`, set at `:1437` from `gitio.has_remote`) plus the three-way `action` at `cli.py:1518-1524`. |
| **L21** README says "four tools" | `README.md:485` says five; `mcp.py` defines five. |
| **H3(a)(b)** CRLF on clone, no `.gitattributes` | `gitio.clone` runs `git -c core.autocrlf=false -c core.eol=lf clone` and calls `neutralize_line_endings(dest)` (`gitio.py:172-176, 374-390`); `kb init` scaffolds `templates/init/gitattributes.txt` (`federation/** -text`) and `gitattributes-child.txt` (`.kb/** -text`) (`initcmd.py:50, 63, 147`). Both cite F-D10. |
| **M15** POSIX-only release tooling | `venv_bin()` in `scripts/check_package.py:108-111` (used by `installed_version` at `:114-121`) and `scripts/gate.sh:24-25` (every venv call routed through it), tested at `tests/test_check_package.py:235-246`. |

Shrunk rather than closed:

- **H1** — the `kb publish` half is done: `publish.py:1082-1090`
  `_load_manifest_or_raise` converts `yaml.YAMLError | ValidationError |
  ValueError` into `PublishError`, and `cli.py:1571-1582` guards publish's
  own `config.yaml` read with a named `_CONFIG_READ_ERRORS` tuple. The
  `kb doctor` half is untouched (`cli.py:2581-2582`), and `_hub_or_exit`
  (`cli.py:397-433`) still catches only `HubConfigError` and
  `gitio.GitError`. That named tuple is what this batch reuses.
- **H3(c)** — `doctor._kb_tree_digest` (hash at `doctor.py:332`) and
  `_fed_tree_digest` (`:746`) still hash `read_bytes()` with no
  normalisation. The reproduction in the finding no longer occurs on a
  *fresh* clone, because F-D10 forces `autocrlf=false` and the
  `.gitattributes` pins exactly the paths these digests cover. It survives
  on legacy trees only: `neutralize_line_endings` runs on `clone`
  (`gitio.py:180`) and in intake (`intake.py:1650`), never on `pull`, so a
  cache clone created before F-D10 keeps its CRLF working tree and its
  unset local config until the TTL re-clone, and a hub created before the
  templates existed has no attributes file at all.
- **M15** — two leftovers: `installed_version` itself still has no test,
  and `gate.sh:37`'s "no interpreter found" hint still prints the
  POSIX-only `.venv/bin/pip install -e '.[dev]'`.
- **M10** — `RegistryEntry` (`models.py:115`) and `Registry` (`:141`)
  already carry `extra="forbid"` *with the rationale docstring this
  finding asks for*. It was applied to the registry/auth models only, not
  to the KB's own core models.

One finding the review did not have, surfaced by the sweep: `check_hub`'s
existing digest compare (`doctor.py:686-703`) is guarded by `if repo_id:`,
and `cli.py:2603` passes `repo_id=None` when doctor runs **at the hub** —
so the digest machinery exists and is simply never reached there.

Three items in the web layer the review missed, all in the same
unauthenticated auth surface, folded into § "HTTP surface":

1. `ui.py:224` `login_post` calls `await request.form()` with no body cap,
   while `intake_routes.py:59-65` wraps every intake upload in
   `_capped_receive`/`read_capped` precisely because "Starlette applies no
   size limit to a multipart file part".
2. Neither login response (`ui.py:209-234`) sets `Cache-Control:
   no-store`, so the token-entry form and its "Invalid token" error page
   are cacheable and sit in the back-forward cache.
3. `ServerConfig` has no trusted-proxy field — `build_routes`
   (`ui.py:197-207`) reads the env var directly — so wiring a limiter into
   `TokenAuthMiddleware` needs that plumbing, not a one-line call.

## Decisions taken during brainstorming (2026-09-17)

1. **Scope: HIGH + MEDIUM + cheap LOW, minus the renderer swap.** In: H1
   (doctor half), H2, M4, M5, M6, M8, M9, M10, M11, M13, M14, M16, M17,
   L19, L20, L22, L23, L24, L26 (as a documented non-action), L28, L29,
   the M15 leftovers, the three missed web items, and H3(c) as an optional
   legacy self-heal. Deferred: **M18** (swap `mdrender` for a markdown
   library — already ruled out of scope by
   `2026-07-12-web-ui-search-readability-design.md:38`, and today's
   renderer has no link syntax at all, which is *why* the XSS surface is
   clean), **L25** (reader-table overflow), **L27** (`utf8io` newline
   translation), and the `B`/`I`/`UP`/`SIM` ruff families.
2. **Clean errors go in the funnel, not the command.** `_CONFIG_READ_ERRORS`
   is today a *local* re-declared in three command bodies (`cli.py:1571`,
   `:1763`, `:1830`, each with a comment pointing at the other two), so it
   is first hoisted to a single module-level constant — otherwise
   `_hub_or_exit` cannot see it and the duplication grows to four. The
   guard then lands inside `_hub_or_exit` (`cli.py:397-433`), which 11 hub
   commands route through, so one guard fixes all of them; `doctor`
   additionally calls `check_kind(kb_dir)`
   *before* `_hub_or_exit` so `doctor.py:119-126`'s own "config.yaml is
   invalid" Issue finally fires and doctor reports rather than dies.
   Rejected: a top-level typer-callback handler only — it would print a
   clean line but leave doctor's own handler dead code.
3. **Session cookie: signed, stateless, no new env knob.**
   `<issued-at>.<hmac_sha256(token, issued-at)>`, verified with
   `compare_digest`, rejected past `SESSION_MAX_AGE`. Rejected: a
   server-side session store (mutable state, a second sweeper to test when
   the first one is already untested, everyone logged out on restart) and
   keeping the raw token with flags added (the cookie would still be an
   admin-equivalent credential).
4. **`Secure` is derived, not configured.** From the request scheme, or
   from `X-Forwarded-Proto: https` when `CENTER_KB_TRUSTED_PROXIES > 0` —
   reusing F-D12's knob instead of inventing
   `CENTER_KB_HTTP_INSECURE_COOKIE`. Plain HTTP with no declared proxy
   sets the cookie without `Secure` and logs a warning once, so local dev
   works and a misconfigured TLS deployment says so in the log rather than
   locking the operator out of `/ui` with no explanation.
5. **One rate-limit bucket for failed shared-secret attempts.** `app.py`
   builds a single `SlidingWindowLimiter` and passes it to both
   `build_routes(login_limiter=…)` and `TokenAuthMiddleware`, so attempts
   spent over the header are attempts the login form no longer has. Only
   *failed* auth counts. The middleware wraps its scope in
   `Request(scope)` to reuse `ratelimit.client_key()` unchanged,
   trusted-proxy logic included.
6. **Strict models on authored files, permissive on the wire.**
   `extra="forbid"` onto `Manifest`, `SectionEntry`, `IndexEntry`,
   `KBIndex`, copying `Registry`'s rationale docstring. **Not** onto
   `FedIndexEntry`/`FederationIndex`: they are machine-generated and
   shared across installs, and this very batch adds a field to them — a
   0.23 install reading a 0.24 hub must not hard-error on a key it does
   not know.
7. **doctor gains four checks, not five.** Duplicate section ids, `## `
   headings absent from the manifest, `tokens` drift, and hub content
   tampering. All four are errors (exit 1), not warnings — warnings exit 2,
   and decision 9 is about making 2 mean one thing. Rejected: the
   `.raw.md`-newer-than-`.md` mtime check — mtime ordering is meaningless
   after a clone or checkout, so it would fire on clean trees and get
   muted.
8. **Hub tamper detection via a stored digest.** `kb reindex` writes
   `content_sha256` per snapshot into `federation/index.yaml` (through
   `federation.build_federation_index:290`); `check_hub` recomputes and
   compares; the field absent means a pre-0.24 hub, skipped with a note.
   Nothing at the hub can serve as a comparison basis otherwise — the
   child's local `.kb` lives on another machine. The `if repo_id:` skip is
   removed in the same pass.
9. **Exit codes: usage errors move to 1, stale keeps 2.** The 8
   misconfiguration `Exit(2)` sites become `Exit(1)`; `cli.py:2170`
   (resolve) and `:2650` (doctor) keep 2. Rejected: moving stale to 3,
   which breaks the one exit code the README publishes as a CI contract.
   Documented residual: click's own bad-flag errors also emit 2 and we do
   not control that.
10. **`kb diff` reports titles and ordering; renumbers stay add+remove.**
    A section id is the citation key, so an SME must see the old one
    disappear. Rejected: body-matching rename detection — a heuristic with
    ambiguous cases and a fourth glyph in the output contract.
11. **The hygiene trip-wire is inverted.** No list of guarded modules; the
    test scans every write-mode call under `src/center_kb` and requires
    `newline="\n"` or a `# newline-exempt: <reason>` comment at the call
    site. Exemptions live next to the code they excuse and a new writer
    fails until someone states why.
12. **Ruff: `BLE`, `RUF100`, `S` now; `B`/`I`/`UP`/`SIM` later.** Measured
    on HEAD: `B` 103 (53 B904, 43 B008 — all typer `Option()` defaults),
    `BLE` 32, `RUF100` 37 dead noqas, `S` 6142 (6030 = `assert` in tests),
    `I` 19, `UP` 61, `SIM` 15. The 198 mechanical edits belong in their own
    PR, not mixed into a batch that rewrites auth, doctor and gitio.
13. **CSP allows inline styles.** `script-src 'self'` is the part that
    matters; templates carry ~30 inline `style=` attributes plus three
    `<noscript><style>` blocks (`doc.html:63-66`, `search.html:29`,
    `section.html:45`), and refactoring them is cosmetic churn against a
    CSS-exfil-class risk. Scripts are already clean: one external `app.js`
    (`base.html:8`), zero inline script.
14. **L26 (login CSRF) is a documented non-action.** With `SameSite=lax`
    plus `form-action 'self'`, the residual is login-CSRF, and forging it
    requires already holding the shared secret — the attacker would be
    logging the victim into the attacker's own credential. A token here
    needs server state or a signed double-submit for one form and buys
    nothing.
15. **Release 0.24.0**, breaking in four ways (§ "Sequencing and
    release").

## Scope

In:

- `cli.py` — `_hub_or_exit` guard, doctor's `check_kind` ordering, the
  three fail-open blocks, `status`, 8 exit-code flips, `--hub` help text on
  8 commands, `query`/`get` stale note.
- `doctor.py` — four new checks, the `if repo_id:` unskip, optional newline
  normalisation in the two digests.
- `models.py` — `extra="forbid"` on the four authored models.
- `federation.py`, `cli.py reindex` — `content_sha256` per snapshot.
- `diff.py` — title comparison, order detection, render kinds.
- `web/auth.py` — `make_session`/`verify_session`, cookie name, limiter and
  trusted-proxy plumbing, the shared auth helper for `/api/health`.
- `web/headers.py` (new) — security-header middleware.
- `web/app.py` — middleware wiring, shared limiter, exception handler.
- `web/ui.py` — cookie flags, `/ui/logout`, login body cap, `no-store`,
  honest `tokens`.
- `web/api.py` — `SnapshotCorruptError`, honest `tokens`, health trim.
- `templates/web/base.html` (logout control), `login.html`.
- `cipublish.py` — 6 bare `print()`.
- `hub.py` — `resolve_hub` docstring.
- `scripts/gate.sh` — the POSIX-only hint line.
- `pyproject.toml` — ruff `select` and `per-file-ignores`.
- `README.md` — exit-code table, the `kb diff` line, the exit-2 caveat.
- `docs/deploy-remote-mcp.md` — stale CRLF note, the two new operator
  facts.
- `tests/` — per § "Tests", plus the rewritten `test_windows_hygiene.py`.
- `CHANGELOG.md` — 0.24.0.

Out: M18, L25, L27, the `B`/`I`/`UP`/`SIM` ruff families, the mtime check,
a CSRF token, and any change to `mdrender.py`'s escaping — it is the reason
the XSS result is clean.

## 1. Clean errors, fail-closed doctor (H1, M13, L29)

`_CONFIG_READ_ERRORS` — `(yaml.YAMLError, ValidationError, ValueError)`,
currently a local re-declared verbatim at `cli.py:1571`, `:1763` and
`:1830` — is hoisted to one module-level constant and the three locals
deleted. `_hub_or_exit` then wraps its `require_hub` call in it and exits 1
with one red line naming the file and the parse or validation message. This
is the root-cause
placement: 11 hub commands funnel through it, so none of them can show a
traceback for a corrupt `.kb/config.yaml` afterwards. `kb doctor` then
calls `check_kind(kb_dir)` *before* `_hub_or_exit`, which is what finally
makes `doctor.py:119-126` reachable — doctor reports the bad config as an
Issue and exits 1 instead of dying on the way to it. `kb status`
(`cli.py:864`) routes its own loads through the same tuple.

The three fail-open blocks in doctor's hub branch flip to fail-closed,
matching `publish.py:1291-1294`:

| Site | Today | After |
| --- | --- | --- |
| `cli.py:2588-2590` | `except Exception: repo_id = None` — silently disables the whole published-snapshot comparison | `Issue("error", …)`, exit 1 |
| `cli.py:2595-2597` | `except Exception: pass  # config hỏng đã được check_kind báo` — self-refuting, since `check_kind` never ran | an Issue; the comment becomes true and unnecessary |
| `cli.py:2626-2628` | `except Exception: dest_rid = ""` — an unreadable upstream config blinds the self-hub check | `Issue("error", "could not read the upstream hub's .kb/config.yaml: …")`, the same wording `PublishError` uses |

One condition, one message, one policy.

## 2. Strict models (M10)

`extra="forbid"` plus `Registry`'s rationale docstring onto `Manifest`
(`models.py:56-63`), `SectionEntry` (`:37-46`), `IndexEntry` (`:66-71`) and
`KBIndex` (`:82-84`). A typo'd `sumary:` becomes a validation error at
load, which doctor and build both surface, instead of an empty L1 summary
that publishes.

`FedIndexEntry`/`FederationIndex` (`:87-99`) stay permissive, deliberately
and with a comment saying so: § 3 adds `content_sha256` to that file, and
forbidding unknown keys there would make every older install hard-error on
a hub written by a newer one.

## 3. doctor checks (M9)

| Check | Mechanism | Message |
| --- | --- | --- |
| duplicate section id in one doc | `Counter` over the manifest's section ids | `[error] <doc> §<id>: duplicate section id in _manifest.yaml` |
| `## ` heading absent from the manifest | `mdutils.heading_occurrences` per L2/L3 file, set-difference against the manifest ids | `[error] <doc>: heading '<id>' in '<file>' is not in _manifest.yaml` |
| `tokens.l2/l3` drift | recount with `mdutils.count_tokens` over the sliced text | `[error] <doc> §<id>: tokens.l2 is 99999, recount is 412 — run 'kb build'` |
| hub content tampered | `content_sha256` per snapshot in `federation/index.yaml`, recomputed by `check_hub` | `[error] federation/<rid> content does not match its published digest` |

All errors (exit 1). The mtime check is rejected per decision 7.

`kb reindex` writes the digest through `federation.build_federation_index`
using the same tree walk `_fed_tree_digest` already implements; a snapshot
with no `content_sha256` yields a note ("published before 0.24 — content
digest not verified"), not a failure, so upgrading a hub is a `kb reindex`
away rather than a flag day. The `if repo_id:` guard at `doctor.py:686`
goes, so the compare runs when doctor is invoked at the hub itself.

Optional (decision 1): normalise CRLF→LF in `_kb_tree_digest` and
`_fed_tree_digest` before hashing, ~2 lines each, which self-heals legacy
caches that predate F-D10. Droppable without touching anything else.

## 4. `kb diff` (M14) and the README line it contradicts (H2)

`diff_doc` (`diff.py:90-131`) compares `sec.title` and reports `title` as a
third change kind, rendered in the stable order `(title, summary, prose)`.
Order detection compares the id sequences **restricted to ids present on
both sides**, so an add or a remove alone can never fake a reorder; a
genuine reshuffle emits one line:

```
icao-annex-3 — changes since 970217e:
~ §2.1 Objective, determination and provision of meteorological service (title, prose)
~ §2.9 Meteorological observations (summary)
• section order changed
+ §2.4 New requirement
- §2.3 Old requirement
```

`README.md:475` is rewritten to state what `kb diff` actually does —
summary, title, L2 prose, L3 original and ordering — and the sentence "An
L2-only edit shows stale on resolve but not in diff" is deleted;
`tests/test_diff.py:69` has pinned the opposite behaviour all along.

## 5. HTTP surface (M4, M5, M6, M8, L22, L23, and the three missed items)

**Session.** `web/auth.py` gains `make_session(token, now)` returning
`f"{ts}.{hmac_sha256(token, ts).hexdigest()}"` and `verify_session(value,
token, now)` doing a `compare_digest` on the signature plus an age check
against `SESSION_MAX_AGE = 43200` (12 h). `COOKIE_NAME` becomes
`center_kb_session`, so a pre-0.24 raw-token cookie stops authorising and
the browser is redirected to login once. `set_cookie(…, httponly=True,
samesite="lax", max_age=SESSION_MAX_AGE, secure=<derived>)` per decision 4.
`POST /ui/logout` (a form control in the header) deletes the cookie and
redirects 303 to `/ui/login`.

**Headers.** A ~25-line ASGI middleware in `web/headers.py`, installed
*outside* `TokenAuthMiddleware` so 302s, 401s and 429s carry the headers
too: `default-src 'self'`, `script-src 'self'`, `style-src 'self'
'unsafe-inline'` (decision 13), `img-src 'self'`, `object-src 'none'`,
`frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`, plus
`X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin` and
`Permissions-Policy: camera=(), microphone=(), geolocation=()`. HSTS is
emitted only when the request is https, so a plain-HTTP dev host is never
pinned.

**One bucket (M6).** `app.py` constructs the `SlidingWindowLimiter` and
injects it into both `build_routes` and `TokenAuthMiddleware`, along with
the `trusted_proxies` value read once at startup — which also removes
`build_routes`'s direct env read. The middleware counts **only failed**
auth for non-exempt paths, keyed by `ratelimit.client_key(Request(scope),
trusted_proxies)`; exhausted returns `429 {"error": "too many attempts"}`
for API/MCP paths and a 429 HTML page for `/ui`. Authorised traffic never
touches the limiter, so no legitimate client is throttled.

**Corrupt snapshot (M8).** `api.load_manifest` (`api.py:102-104`) wraps
`load_yaml_model` in the same error tuple as § 1 and raises a new
`SnapshotCorruptError`. One exception handler registered in `app.py`
branches on path prefix: 503 JSON `{"error": …}` for `/api/*`, the
templated error shell for `/ui/*`, meeting the redesign spec's "renders
inside the new shell" contract. `/ui` itself already degrades correctly and
stays 200.

**The rest.** Login POST body capped with intake's existing
`read_capped`/`_capped_receive`; `Cache-Control: no-store` on both login
responses; `/api/health` returns `{"status": "ok"}` to an unauthenticated
caller, with `hub_configured`/`hub_reachable` retained for an authenticated
one through a small shared helper in `auth.py` (L22 — the operator probe
keeps working, the pre-auth disclosure goes); `_sweep` gets a test that
monkeypatches `_SWEEP_THRESHOLD` low and asserts the key table shrinks
(L23).

## 6. Exit codes, docs, trip-wire, parity, lint

**Exit codes (M11).** `Exit(2)` → `Exit(1)` at `cli.py:149, 192, 205`
(init), `543` (`summarize --llm`), `1220` (`usage ingest-transcript`),
`1575`, `1625` (publish flag conflicts), `1779` (`ci-publish`). Stale keeps
2 at `:2170` and `:2650`. Care for the plan: of the existing `exit_code ==
2` assertions, `test_cli_mission.py:273`, `test_cli_ticket.py:266` and
`test_lintcore.py` are stale-class and must keep 2 — only the
init/summarize/usage/hub ones flip. README gains an exit-code table with
the click caveat.

**Docs.** L19: `(empty = don't use)` → `(empty = config)` on `cli.py:1390,
1447, 2033, 2058, 2087, 2180, 2323, 2567`, matching the two `assets`
commands that already got it right. L20: `hub.resolve_hub`'s docstring
(`hub.py:159-161`) stops claiming the hub is "an enhancement, not a hard
requirement". `docs/deploy-remote-mcp.md:6-10` drops the stale autocrlf
advice (F-D10 enforces it in code) and gains the two new operator facts:
what the security headers are, and that `CENTER_KB_TRUSTED_PROXIES > 0` is
what lets the session cookie earn `Secure` behind a TLS-terminating proxy.

**Trip-wire (M16).** `tests/test_windows_hygiene.py` drops
`COMMITTED_WRITERS` (`:35-42`) and AST-walks every module under
`src/center_kb` instead: each write-mode `write_text(`/`open(` must pass
`newline="\n"` or carry `# newline-exempt: <reason>` at the call site.
`svcnote.py:455-456`, `codeingest/core.py:206-207` and
`usage/ledger.py:165` already pass `newline="\n"` and go green with no
edits; the known local/binary writers (`hub.py:154` marker,
`intake.py:1330` state JSON, `ingest/parser.py:129` cache, `web/ui.py:517`
asset bytes) get the comment.

**Parity (M17).** `tokens` counts only text the response carries
(`api.py:203-213`, `ui.py:260-270`), so the number stops describing an L3
snippet the caller never receives. `mcp.py:139`'s `_stale_note` is reused
by CLI `kb query` (`cli.py:1383-1430`), CLI `kb get` (`:1440-1465`) and
REST `/api/search`. Close-top-2 stays MCP-only (C6 scopes it there); both
budget clamps stay and get documented per surface.

**Lint (L28).** `[tool.ruff.lint] select = ["E4", "E7", "E9", "F", "BLE",
"RUF100", "S"]`; `per-file-ignores` keeps `tests/* = ["E402"]` and adds
`S101` for `tests/*`, plus `S603`/`S607` at the subprocess wrappers with a
stated reason. That leaves ~28 real hits to triage individually —
`S105`/`S106` (11), `S324` (7), `S310` (5), `S608` (5) — each either fixed
or given a justified `noqa`, which `RUF100` now keeps honest. The 11
`BLE001` markers become live for the first time.

**Leftovers.** A test for `check_package.installed_version` using the
stub-script pattern `test_init.py` already uses for `KB_STUB_RC`;
`gate.sh:37`'s hint made platform-aware; `cipublish.py:77, 113, 152, 158,
160, 181` bare `print()` → `typer.echo`.

## 7. Tests

TDD first, in the suite's existing style: real filesystems, real git repos,
`monkeypatch` seams, no mocking library.

| Area | Cases |
| --- | --- |
| session | round-trip; expiry past `SESSION_MAX_AGE`; tampered signature; a pre-0.24 raw-token cookie is rejected; `Secure` derived from scheme; derived from `X-Forwarded-Proto` with `CENTER_KB_TRUSTED_PROXIES=1`; absent on plain HTTP with a logged warning; logout clears and redirects |
| headers | present on 200, 302, 401, 429; HSTS only under https; CSP admits `app.js` and inline `style=` |
| limiter | failed header auth counts; successful auth does not; login and header share one bucket (spend on one, locked on the other); 429 shape per path prefix; `_sweep` |
| snapshot corrupt | `/api/docs/<doc>` → 503 JSON; `/ui/docs/<doc>` → error shell with the chrome; `/ui` still 200 |
| doctor | duplicate ids; orphan heading; token drift; hub tamper caught; `content_sha256` absent → note, exit 0; invalid `config.yaml` → Issue, exit 1, **no traceback**; unreadable upstream config → error, not silence |
| models | unknown key rejected on the four authored models; **accepted** on `FederationIndex` (the deliberate asymmetry, with the reason in the test name) |
| diff | title-only change; reorder; renumber still add+remove |
| cli | the 8 exit-code flips; the stale-class 2s unchanged; `kb status` on a corrupt config |
| parity | `tokens` equals the tokens of the returned text on REST and UI; stale note present on `kb query`, `kb get`, `/api/search` |
| misc | login body cap; `no-store`; `/api/health` minimal unauthenticated, full authenticated; `installed_version`; the rewritten hygiene scan catches a deliberately unmarked writer |

Gate: T1–T4 through `scripts/gate.sh`, with the new ruff `select` passing
and the full suite green (≈550 s, 1875+ tests today).

## 8. Sequencing and release

Six groups. Four of them edit `cli.py`, so they run **sequentially** —
group 3 (`web/`) is the only one safe to run in parallel with the others.
This is a deliberate constraint: a parallel batch sharing one checkout has
already cost this project a commit race.

1. § 1 clean-error funnel, `check_kind` ordering, fail-closed blocks; § 2
   strict models
2. § 3 doctor checks, `content_sha256`, `kb reindex`, the `if repo_id:`
   unskip
3. § 5 HTTP surface — session, logout, headers, shared limiter,
   `SnapshotCorruptError`, body cap, `no-store`, health trim, `_sweep` test
4. § 4 `kb diff`; § 6 exit-code flips and parity
5. § 6 docs, trip-wire, ruff `select` and the ~28 triaged hits,
   `installed_version`, `gate.sh` hint, `cipublish` echoes, optional H3(c)
6. Release 0.24.0

**0.24.0 is breaking four ways**, each one changing an outcome someone
already depends on, so each gets its own CHANGELOG line:

1. Every browser session needs one re-login — the cookie's name and value
   both change.
2. A typo'd manifest key that used to load with an empty summary is now a
   validation error.
3. Eight commands that exited 2 on misconfiguration now exit 1.
4. `kb doctor` now fails trees it previously called OK — duplicate ids,
   orphan headings, stale token counts, tampered hub content. This is the
   point of the batch, but it means a KB that was green can go red on
   upgrade with nothing having changed on disk.

**Pre-merge verification, because of (2) and (4):** run `kb doctor` against
this repo's own `.kb/` and a freshly published scratch hub before the
strict-models change is called done. If the real data carries unknown keys
or drifted token counts, we learn it from the gate, not from a user.

**Branch:** `h-web-doctor-quality-review-fixes` off `main` once PR #47
(wave F) merges.
