# Reviewer H — Web/API surface, KB health tooling (doctor/diff), engineering quality

Repo: `D:\Projects\AERO-KB` @ `main` 4b47b4c, v0.20.0. READ-ONLY: no file under the repo was
created, modified or deleted. All experiments ran in
`…/scratchpad/H/{lab,doc,df,crlf,crlf2,out}`.

---

## 1. Scope & method

| What | How |
|---|---|
| Live HTTP surface | Built a scratch hub (`demo-federation.sh` steps 1–3), published a **copy** of the repo's real `.kb/` as repo `aero` after injecting XSS probes into an L2 section's prose, a pipe table, a Figure/image line, a heading, the manifest `title`+`summary`, the L0 doc `title` and two L0 tag names. Ran `python -m center_kb.mcp --transport http` under `timeout` inside a single bash command, probed with `curl`, killed the server in the same command. Three server runs (ports 8399/8398/8397); none left running. |
| Auth / headers / rate limit | curl probes for 401/302/429, `curl -D -` for response headers, 10 unauthenticated `/api` hits, 8 bad logins, `X-Forwarded-For` rotation. |
| XSS | Fetched `/ui`, `/ui/docs`, `/ui/docs/<doc>`, `/ui/docs/<doc>/<sec>` (l2+l3), `/ui?q=<script>…` and grepped every rendered page for unescaped `<script`, `alert(`, `onmouseover`. |
| Traversal / IDOR | 10 encoded and raw traversal probes against `/assets/…`, `/ui/static/…`, `/ui/docs/…`, `/api/docs/…`. |
| doctor | Clean baseline (`kb doctor: OK`, exit 0), then 18 one-at-a-time corruptions of a pristine scratch KB + hub, each run to completion with exit code captured **without** a pipe. |
| diff | 12 scenarios against a real git rev in a scratch worktree. |
| Code quality | AST scan of `cli.py` (command → module), full census of `except Exception`/`except:`/`pass`, `typer.Exit` codes, `print` vs `logging`, `write_text`/`open(w)` newline audit. |
| Tests | Full suite in the foreground, `ruff check src tests`, AST assertion-strength scan of all 1805 test functions, module↔test map. |

---

## 2. Verified-good (evidence)

**Auth (`web/auth.py`, `web/ui.py`)**
- Token comparison is constant-time on **both** paths — `hmac.compare_digest` at `auth.py:41` (header) and `auth.py:52` (cookie), plus `ui.py:219` for the login form. `TypeError`/`CookieError` are caught and become 401, not 500.
- Measured on the live server: `/api/docs` unauth → `401 {"error": "unauthorized"}`; `/mcp` unauth → 401; `/` and `/ui` unauth → `302 → /ui/login`; `/api/health` and `/ui/static/*` exempt by design.
- **Token is NOT accepted in a query string**: `GET /api/docs?token=s3cr3t-…` → 401.
- Failed logins are logged without the submitted value (`ui.py:224`); anonymous `/ui` hits are deliberately *not* logged (`auth.py:68-78`) — tested at `tests/test_ratelimit.py:66`.
- Login limiter is checked **before** the token compare (`ui.py:209`), so lockout leaks no oracle.

**XSS — clean across the board.** Every probe came back escaped. Sample from `/ui/docs/icao-annex-3/2.9`:
```
<p>XSSPROBE1 prose &lt;script&gt;alert(1)&lt;/script&gt; and &lt;img src=x onerror=alert(2)&gt; and
   [x](javascript:alert(3)) and &lt;iframe src=&quot;//evil.example&quot;&gt;&lt;/iframe&gt; …</p>
<table>…<td>&lt;/td&gt;&lt;/tr&gt;&lt;script&gt;alert(6)&lt;/script&gt;</td>…</table>
<img src="/assets/0000…0000.png" alt="XSSPROBE3 alt&quot;&gt;&lt;script&gt;alert(7)&lt;/script&gt;" loading="lazy">
```
`grep -c "<script"` on every rendered page = **1** (the legitimate `app.js` tag).
- `mdrender.py` is a hand-written renderer (**no markdown library**), everything goes through
  `html.escape` (`mdrender.py:37-49, 65-69`); there is **no link syntax at all**, so there is no
  protocol allowlist to get wrong — `[x](javascript:…)` renders as literal text. Images are only
  emitted for `assets/<64 hex>.(png|webp)` (`mdrender.py:19-21`) and the alt text is escaped with
  `quote=True`.
- Jinja autoescape on (`templating.py:9`); TOC labels are `html.unescape`d then re-escaped by Jinja
  (`uidata.py:207`), heading anchors are slugified to `[a-z0-9-]` (`uidata.py:209`).
- Tag names, doc titles, breadcrumbs, `data-text=` attributes and `href` query strings all escaped
  (`&#39;`, `%3Cscript%3E`); the malicious tag `tag" onmouseover=alert('attr')` renders as
  `tag&#34; onmouseover=…` inside the element, never as an attribute.
- **`static/app.js` has zero HTML sinks** — `grep -rn "innerHTML|outerHTML|insertAdjacentHTML|document.write|eval("` over `templates/` → *none*. It uses `textContent`, `dataset`, `classList`, `setAttribute` only, and never consumes API JSON. There is no Mermaid rendering on the web path.

**Path traversal / IDOR — 10/10 rejected (404):**
`/assets/..%2f..%2fpyproject.toml`, `/assets/../../../etc/hosts`, `/ui/static/..%2f..%2f__init__.py`,
`/ui/static/../../__init__.py`, `/ui/docs/..%2f..%2fetc`, `/ui/docs/%2e%2e/%2e%2e`,
`/api/docs/..%2F..%2Fx`, `/api/docs/icao-annex-3/sections/..%2f..%2f..%2fx`,
`/ui/docs/icao-annex-3/2.9%2f..%2f2.1`, `/api/get?doc=../../`.
The guards are real, not accidental: `ui.py:166` rejects `..`, leading `/`, `:` and `\` (Windows
drive + backslash), `ui.py:423` pins asset names to `^[0-9a-f]{64}\.(png|webp)$`, and `OSError`
(ENAMETOOLONG) degrades to 404 rather than 500 (`ui.py:174-177`).

**C7 hub-first on the web path — holds.** Every web read goes through `api.hub_handle(config)` →
`resolve_hub(config.hub)` → `hub.federation_dir`. The only other filesystem root touched is
`hub.kb_dir` in `ui.py:454` (the **hub's** `.kb`, for asset lookup), never the caller's local `.kb/`.
The local `.kb` is read exactly once, for `config.yaml` → hub ref.

**Error responses do not leak tracebacks.** A deliberately corrupted federation manifest produced a
bare `Internal Server Error` body; the YAML parse error stayed in the server log.

**doctor exit codes 0/1/2 for `--context` are exactly right** (measured):
fresh pin → `EXIT=0 / kb doctor: OK`; L2 amended + republished →
`EXIT=2 / [warning] child:icao-annex-3 §2.1: L2 content has changed since the pinned version`;
nonexistent ref → `EXIT=1 / [error] … §9.9 is not in manifest 'icao-annex-3' at rev f4bbd25`.

**diff classification and output stability** — added/removed/changed are correct and ordered
deterministically (added in new-manifest order, removed in old order, changed in new order);
bad rev → `EXIT=1 rev 'deadbeef' does not exist in the repo (force-push or shallow clone?)`;
doc missing in worktree / at rev → clean `EXIT=1` messages.

**utf8io works.** Under a pipe the interpreter default is `cp1252`; after `import center_kb.cli`,
`sys.stdout.encoding == utf-8` and `§` comes out as `\xc2\xa7`. Verified end-to-end through
`kb get … | …`.

**Test suite health.** `pytest tests -q --durations=15`: **1875 passed, 5 skipped, 0 failed,
0 errors, 548.43 s**. `ruff check src tests` → `All checks passed!` (ruff 0.15.22).
Slowest: `test_ingest_cli.py::test_ingest_is_quiet_when_every_item_reaches_l3` 10.38 s,
`test_llm.py::test_run_raises_on_timeout` 5.11 s, `test_federation_e2e.py::test_full_lifecycle`
5.06 s, then a tail of git/intake tests at 2–4 s. Nothing pathological.

**Test quality is genuinely high.** 3960 `assert` statements across 1805 test functions. An AST scan
for functions with **neither** an `assert` **nor** a `pytest.raises/warns` found exactly **one**
(`tests/test_utf8io.py:54`, a deliberate "must not raise" smoke test). `unittest.mock`/`MagicMock`
appear **nowhere** — the suite uses real filesystems, real git repos and `monkeypatch` seams.
`tests/test_web_ui.py` alone has ~110 route tests covering XSS escaping
(`test_section_page_title_xss_escaped:787`), percent-encoded traversal (`:1144`), absolute-path
params (`:1161`), ENAMETOOLONG (`:1184`), content types, a11y labels and no-JS fallbacks.

**Packaging.** `scripts/check_package.py` guarantees: (1) installed-wheel `kb --version` ==
`pyproject.version`, (2) tag == version when `--tag` given, (3) wheel top level is *allowlisted* to
`center_kb/` + `*.dist-info` only, (4) sdist top level allowlisted to `{src, PKG-INFO,
pyproject.toml, README.md, LICENSE, .gitignore}` — so `.kb/` (verbatim copyrighted text) can never
ship, (5) `dist/` has both a wheel and an sdist, plus (6) the web static assets (`style.css`,
`app.js`, ≥1 `.woff2`) are present inside the wheel. `pyproject.toml:64-65`
`only-include = ["src"]` backs it. The allowlist-over-denylist rationale is documented and correct.

**Clean logging discipline.** `typer.echo/secho` appears **only** in `cli.py` (187 uses); library
modules use `logging.getLogger("center_kb.<mod>")`; `logging.basicConfig` only in `mcp.main()`.
Credential redaction (`gitio.redact_url`) is applied to clone/pull errors.

---

## 3. Findings

### HIGH

**H1 — `kb doctor` (and every hub-resolving command) dies with a full traceback on an invalid `.kb/config.yaml`; doctor's own handler for that case is unreachable.**
`cli.py:1805` calls `_hub_or_exit(hub, kb_dir)` **before** `check_kind(kb_dir)` on `cli.py:1806`.
`_hub_or_exit` → `config.require_hub` → `load_config` → `models.load_yaml_model` (`models.py:94-96`)
raises `pydantic.ValidationError` / `yaml.ParserError`, which nothing catches. The dedicated
`doctor.check_kind` branch that returns `Issue("error", f"config.yaml is invalid: …")`
(`doctor.py:120-121`) can therefore never fire on this path.
```
$ printf 'hub: <hub>\nrepo_id: child\nkind: bogus\n' > .kb/config.yaml
$ kb doctor --kb-dir .kb
┌──────────── Traceback (most recent call last) ────────────┐
│ D:\Projects\AERO-KB\src\center_kb\cli.py:1805 in doctor   │
│ …  D:\…\pydantic\main.py:732 in model_validate            │
ValidationError: 1 validation error for KBConfig
kind  Input should be '', 'hub', 'child', 'ba' or 'dev' …
EXIT=1
```
Same with invalid YAML (`hub: [unclosed`) → `ParserError` traceback. `kb publish` shows the same
rich traceback for a corrupt `_manifest.yaml` (`ParserError: while parsing a block mapping`).
Violates **C15** ("clean error not traceback") and undermines **C8** (doctor is the health tool and
is the thing that crashes). `tests/test_config.py` has no invalid-YAML case, so nothing catches it.

**H2 — README documents the opposite of what `kb diff` does, in the middle of the BA→Dev workflow.**
`README.md:449`: *"`kb resolve` / `kb doctor --context` detect L2 content changes …; **`kb diff`
reports L1 summary and L3 original changes** (SME review scope). **An L2-only edit shows stale on
resolve but not in diff.**"* — false. `diff.py:101-104` compares the `.md` (L2) slice and reports it
as `prose`; `tests/test_diff.py:69 test_prose_changed_when_l2_edited` pins that behaviour.
```
# edited only ch2-general-provisions.md (L2), nothing else
$ kb diff icao-annex-3 --against 970217e
icao-annex-3 — changes since 970217e:
~ §2.1 Objective, determination and provision of meteorological service (prose)
EXIT=0
```
The README is the sole spec for step 4 of the Dev flow (`README.md:456`), so a reader will draw the
wrong conclusion about what an amendment did. Criterion **C8**.

**H3 — Windows/CRLF: a fresh hub cache clone produces a permanent false "run `kb publish`" warning and two content-identical churn commits on the hub.**
`gitio.clone` (`gitio.py:83-90`) never sets `core.autocrlf=false`, `kb init` scaffolds no
`.gitattributes` (not in `src/center_kb/templates/init/`), and the Git-for-Windows **default**
`core.autocrlf=true` is what this machine has. The tool's own writers emit LF
(`newline="\n"`), so the two sides disagree byte-for-byte, and
`doctor._kb_tree_digest` hashes `path.read_bytes()` (`doctor.py:198-210`) — no normalisation.
```
$ kb publish --kb-dir <child>/.kb     → kb publish: child @ 18ec75a — 1 doc, push.
$ rm -rf $CENTER_KB_HUB_CACHE          # simulate a new machine / TTL re-clone
$ kb doctor --kb-dir <child>/.kb
[warning] local .kb differs from the published snapshot federation/child — run `kb publish`
LOCAL  CRLF 0  bareLF 65
FRESH CLONE CRLF 65  bareLF 0
bytes identical: False
$ kb publish --kb-dir <child>/.kb      # hub commits 3 → 5, content unchanged
392d391 publish: reindex (child)
5a982a3 publish: child @ 18ec75a       <-- duplicate of
bf012fb publish: reindex (child)
3dba715 publish: child @ 18ec75a
```
`docs/deploy-remote-mcp.md:7-10` acknowledges *"a global `autocrlf=true` on other hub clones
degrades no-op detection"* — but it is only a note to operators, nothing enforces it, and the
doctor false positive is not mentioned. Violates **C15** ("Windows fully supported") and dents
**C7** (`kb publish` is supposed to be a no-op when nothing changed —
`tests/test_publish.py::test_publish_twice_no_change_is_noop`).
Fix is one line in `gitio.clone`: `git -c core.autocrlf=false -c core.eol=lf clone …`
(`intake.py:239` already does exactly this for the intake clone).

### MEDIUM

**M4 — Session cookie carries the raw bearer token, has no `Secure` flag and no expiry; there is no logout.**
`ui.py:221`: `resp.set_cookie(COOKIE_NAME, submitted, httponly=True, samesite="lax")`.
Observed on the wire:
```
set-cookie: center_kb_token=s3cr3t-token-abcdefgh; HttpOnly; Path=/; SameSite=lax
```
The cookie value **is** the shared secret that also authorises `/api` and `/mcp` (`login.html:23`
says so). `grep -rn "logout|delete_cookie|secure=True"` over `src/` → nothing; the routes list
(`ui.py:505-514`) has no logout. `docs/deploy-remote-mcp.md` implies a TLS front
(`CENTER_KB_INTAKE_AUDIENCE=https://kb.internal:8321`), so any single plain-HTTP request to that
host exfiltrates an admin-equivalent credential, and a user who "signs out" cannot. C15.

**M5 — No security headers on any response.** `curl -D - /ui` returns only
`date`, `server`, `content-length`, `content-type`. No `Content-Security-Policy`,
`X-Frame-Options`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`,
`Strict-Transport-Security`, `Permissions-Policy`. `grep` confirms none of these strings exists
anywhere in `src/`. The UI is framable, and there is zero defence-in-depth if the (currently
excellent) escaping ever regresses. C15.

**M6 — Rate limiting protects the login form but not the identical secret over `Authorization`.**
Measured: 8 bad `POST /ui/login` → `200 200 200 200 200 429 429 429` (correct, 5/min), and a
*correct* login during the window is also 429 (accepted design). But:
```
# 10 consecutive unauthenticated GET /api/docs
401 401 401 401 401 401 401 401 401 401     <- no 429, ever
```
`web/ratelimit.py:1-8` claims *"Defense-in-depth for the shared-secret login"*, yet the limiter is
only wired into `ui.py:198` (login) and `intake_routes.py:31` (intake publish, 30/min). `/api/*` and
`/mcp` — the same secret, no lockout — are unlimited, so the login limiter is bypassed by simply
using the header. C15.

**M7 — The limiter keys on the raw peer IP with no proxy awareness.** `ui.py:206` /
`intake_routes.py:88`: `request.client.host`. Rotating `X-Forwarded-For` does **not** bypass it
(good, verified: `xff1 200 xff2 200 xff3 200` still counted against the one peer), but the
documented deployment puts the server behind a reverse proxy — where **every** user collapses into
one bucket and five failed logins from anybody lock out the whole organisation for 60 s. There is no
config knob either way.

**M8 — A corrupt federation manifest returns a bare `500` on the doc routes.**
`web/api.py:66` calls `models.load_yaml_model` with no guard, so a snapshot that
`uidata._iter_manifests` (`uidata.py:103`) survives gracefully takes the doc routes down:
```
/api/docs/arinc-424      -> 500  "Internal Server Error"
/ui/docs/arinc-424       -> 500  (no shell, no breadcrumbs)
/ui                      -> 200  (degrades correctly)
```
No traceback leaked (good), but the redesign spec's contract (*"404 … and 400 … render inside the
new shell"*, `2026-07-29-web-ui-redesign-design.md:100-101`) is not met, and there is no test for
this path. C7/C15.

**M9 — `kb doctor` blind spots.** Five realistic corruptions pass with `kb doctor: OK`, exit 0 — see
the matrix in §4: duplicate section id within a doc, orphan `## ` heading in L2, stale `tokens:`
counts, `.raw.md` newer than `.md`, and tampering with published content on the hub. `doctor.py`
only ever checks manifest→file direction plus orphan *files* (`doctor.py:67-71`); it never parses
L2/L3 headings back, never checks id uniqueness, never recounts tokens (`kb build` does — but
doctor is what the README sells as the health check), and `check_hub` only compares
`federation/index.yaml` against `build_federation_index` (metadata), never content digests. C8.

**M10 — `models.py` accepts unknown keys silently.** No `model_config = ConfigDict(extra="forbid")`
on any model (`models.py:13-91`). A typo'd manifest key loads, the field takes its default, and
nothing complains:
```
# summary: -> sumary: throughout _manifest.yaml
$ kb doctor --kb-dir .kb   →  kb doctor: OK   EXIT=0
```
Every L1 summary becomes `""` and the doc publishes that way. Contrast `usage/prices` which *does*
reject misspelled keys (`tests/test_usage_prices.py:142`) — the KB's own core models are the loose
ones. C8/C16.

**M11 — Exit code `2` is overloaded.** `README.md:445-448` documents `2` as "citation stale" for
`kb resolve` and `kb doctor --context`. It is also the usage-error code for
`init` (`cli.py:144`, `:180`), `summarize --llm` (`:498`), `usage ingest-transcript` (`:950`),
`publish --pr --direct` (`:1226`), hub-to-hub intake (`:1268`) and `ci-publish` (`:1333`).
A CI script written from the README will read `kb publish --pr --direct` (a misconfiguration) as
"no error, just a stale citation". Distribution: `Exit()` ×1, `Exit(0)` ×3, `Exit(1)` ×51,
`Exit(2)` ×9.

**M12 — `kb publish` reports "hub has no remote" when the hub demonstrably has one.**
`cli.py:1194`: `action = "push" if report.pushed else "commit only (hub has no remote)"`.
`report.pushed` is false both for "no remote" and for "nothing to push".
```
$ git -C <cache> remote -v
origin  …/hub.git (fetch) / (push)
$ kb publish --kb-dir <child>/.kb
kb publish: child @ 18ec75a — 1 doc, commit only (hub has no remote).
```
An operator will conclude their hub is misconfigured.

**M13 — Doctor fails *open* where publish fails *closed* on the same condition.**
`cli.py:1847` `except Exception: dest_rid = ""` — an unreadable upstream `.kb/config.yaml` silently
disables the identity-based self-hub check; `publish.py:280` raises
`PublishError("could not read the upstream hub's .kb/config.yaml")` for exactly the same read,
with the comment *"fail closed: a corrupt upstream config must not silently blind the … cycle
guard"*. Two policies for one condition.
Related: `cli.py:1821 except Exception: pass  # config hỏng đã được check_kind báo` is
self-refuting — H1 proves `check_kind` never runs on that path; and `cli.py:1813
except Exception: repo_id = None` silently disables the whole published-snapshot comparison when
`git_root` fails.

**M14 — `kb diff` never compares section titles; renames and reorders are invisible.**
`diff.py:96-118` compares only `summary`, the `.md` slice and the `.raw.md` slice.
Measured on a real rev:

| change | reported |
|---|---|
| title changed in the manifest only | **no changes since 970217e** |
| sections reordered in the manifest | **no changes since 970217e** |
| §2.3 renumbered to §2.4 (manifest + both md files) | `+ §2.4 …` and `- §2.3 …` (add+remove, not a rename) |

Title is L1 metadata and is squarely in the "SME review scope" the README assigns to `kb diff`. C8.

**M15 — POSIX-only release tooling on a project that claims full Windows support.**
`scripts/check_package.py:107`: `[str(venv / "bin" / "kb"), "--version"]` — on Windows that is
`Scripts/kb.exe`, so `installed_version()` can never run. `scripts/gate.sh:19,44,53` hard-codes
`.venv/bin/python`, `$ARTIFACT/bin/pip`, `$RUNNER/bin/pytest`, and the file's own header says it is
*"exactly what CI will run"*. A Windows developer cannot run T2/T3/T4 locally at all.
`tests/test_check_package.py` covers only the pure helpers (`pyproject_version`, `tag_matches`,
`wheel_offenders`, `wheel_required_missing`, `sdist_offenders`) — `installed_version` is untested.
C15/C17.

**M16 — `test_windows_hygiene.py`'s CRLF trip-wire is a hardcoded 6-module list.**
`tests/test_windows_hygiene.py:27-34` guards `models.py, initcmd.py, dockersetup.py, summarize.py,
ingest/scaffold.py, conventions.py`. At least three other modules write **committed** content and
are not guarded: `svcnote.py:455-456` (L2/L3 for `-svc` docs), `codeingest/core.py:201`
(`_write_group` for `-code` docs) and `usage/ledger.py:150`. They happen to be correct today, so the
gap is latent, not live — but the trip-wire's whole purpose is to catch the next one. Same class of
scope drift the `check_package` allowlist docstring warns about.

**M17 — REST / Web UI diverge from MCP and CLI in ways an integrator would not expect.**
Same `query.search()` engine (good), different envelope:

| | budget clamp | close-top-2 note | stale-hub-cache note | L3 `snippet` |
|---|---|---|---|---|
| MCP `kb_search` (`mcp.py:106,123`) | **none** | yes (`_ambiguity_note`) | yes (`_stale_note`) | shown as `raw match:` |
| CLI `kb query` (`cli.py:1117`) | none | no | no (only `_hub_or_exit`'s `[warn]`) | shown |
| REST `/api/search` (`api.py:157`) | 1 … 20000 | no | no | **counted in `tokens`, never returned** |
| Web `/ui` (`ui.py:229-234`) | 200 … 8000 | no | no | **counted in `tokens`, never rendered** |

C6 only demands the top-2 flag on MCP, so this is a divergence rather than a violation — but the
REST/UI `tokens` number then describes text the caller never receives. (The UI omission is
deliberate and tested: `tests/test_web_ui.py:948`.) `kb get` also drops the stale-hub note that
`kb_get_section` emits (`mcp.py:154`).

**M18 — `mdrender` collapses lists, code fences and indentation into run-on paragraphs.**
The L3 tab is billed as the *verbatim original*. Verified:
```
- bullet one / - bullet two / - bullet three   →  <p>- bullet one - bullet two - bullet three</p>
```code block\n    indented```                 →  <p>``` code block line 1 indented line 2 ```</p>
```
`mdrender.py:105-108` joins every non-blank line of a paragraph with a single space. The bundled
demo data contains **zero** bullet lines (`grep -c "^[-*] " .kb/**/*.raw.md` → 0), so nothing breaks
today, and `2026-07-12-web-ui-search-readability-design.md:38` explicitly lists "swap the markdown
renderer for a library" as out of scope. But README §1 markets the tool as domain-agnostic, and any
KB built from a document with lists will silently lose structure on the reader page.

### LOW

- **L19** `--hub` help text `"kb-hub URL/path (empty = don't use)"` on 9 commands (`cli.py:1104,
  1143, 1440, 1465, 1494, 1536, 1614, 1792` + `1204`) contradicts C7 (hub mandatory); the two
  `assets` commands (`:1384, :1409`) have the correct `"(empty = config)"`.
- **L20** `hub.resolve_hub`'s docstring (`hub.py:58-61`): *"the caller continues with the local KB
  only (the hub is an enhancement, not a hard requirement)"* — stale since the 2026-07-13 hub-first
  change; every caller now errors or 503s.
- **L21** `README.md:437` says *"no extra setup for Claude Code to see the **four** tools"* — there
  are five (C9).
- **L22** `/api/health` is unauthenticated and returns `hub_configured` / `hub_reachable`
  (`api.py:73-80`) — minor pre-auth information disclosure.
- **L23** `SlidingWindowLimiter._sweep` (`ratelimit.py:50-61`), the only thing bounding limiter
  memory against IP rotation, has **no test** (`grep -rn "_sweep" tests/` → nothing).
- **L24** `cipublish.py:75,129,131,152` uses bare `print()`; every other user-facing message in the
  codebase goes through `typer.echo/secho` (cli.py) or `logging`.
- **L25** `.reader-body table` (`style.css:254-259`) has no `overflow-x: auto` wrapper — a wide
  ARINC table squashes in the reader, while the doc page's `.sec-table` (`:220`) does have one.
  Cells also lack `white-space: pre-wrap`, so runs of spaces collapse visually even though
  `mdrender` preserves them.
- **L26** Login is the only state-changing browser route and carries no CSRF token
  (`ui.py:205-227`). `SameSite=lax` blocks the cross-site POST in current browsers, so the residual
  risk is login-CSRF only.
- **L27** `utf8io.force_utf8_streams` (`utf8io.py:14-19`) reconfigures encoding but not newline
  translation, so `kb get … --level l3 > out.md` on Windows writes CRLF — a redirected L3 dump is
  not byte-verbatim (observed: `b'--- […]\r\n## 2.1 …\r\n'`).
- **L28** ruff runs with the **default** rule set only — `pyproject.toml:67-69` sets nothing but
  `per-file-ignores`, so only `E4/E7/E9/F` are active. The `# noqa: BLE001` markers scattered through
  `src/` (11 of them) are inert because `BLE` is not enabled, and `RUF100` (unused-noqa) is not
  enabled either. "ruff check passed" therefore carries much less signal than it appears to.
- **L29** `kb status` (`cli.py:605-628`) is the only command whose logic lives entirely in `cli.py`
  with no module behind it, and it calls `models.load_yaml_model` unguarded — same traceback class
  as H1 on a corrupt manifest.

---

## 4. doctor coverage matrix

Baseline: clean scratch KB + published hub → `kb doctor: OK`, exit 0. One corruption at a time.
(The `[warning] local .kb differs from the published snapshot` line appears in most rows because the
mutation itself is genuinely unpublished; it does not affect the exit code.)

| # | Corruption | Caught? | Message | Exit |
|---|---|---|---|---|
| 1 | manifest lists a section missing from L2 (heading renamed in `.md`) | **yes** | `[error] icao-annex-3 §2.3: could not slice section in 'ch2-general-provisions.md'` | 1 |
| 2 | same, missing from L3 (`.raw.md`) | **yes** | `[error] … could not slice section in 'ch2-general-provisions.raw.md'` | 1 |
| 3 | L2 file deleted | **yes** | `[error] icao-annex-3 §2: missing L2 file '…md'` (one per section) | 1 |
| 4 | orphan `## 2.77` heading in L2, not in the manifest | **NO** | `kb doctor: OK` | 0 |
| 5 | duplicate section id inside one doc (`2.3` → second `2.1`) | **NO** | `kb doctor: OK` | 0 |
| 6 | doc in `index.yaml` with no directory | **yes** | `[error] doc 'ghost-doc' is in the index but missing _manifest.yaml` | 1 |
| 7 | directory with a manifest, absent from `index.yaml` | **yes** | `[error] doc 'rogue-doc' has a manifest but is not in index.yaml` | 1 |
| 8 | `file:` stem points at a nonexistent file | **yes** | `[error] … missing L2 file 'nope-missing.md'` + L3, per section | 1 |
| 9 | `tokens.l2/l3` wildly stale (99999 / 1) | **NO** | `kb doctor: OK` | 0 |
| 10 | invalid YAML in `_manifest.yaml` | **yes** | `[error] icao-annex-3: _manifest.yaml is corrupt — … mapping values are not allowed here …` | 1 |
| 11 | `status:` outside the enum (`approved`) | **yes** | `[error] … Input should be 'pending', 'summarized' or 'reviewed'` | 1 |
| 12 | `.raw.md` edited + mtime newer than `.md` | **NO** | `kb doctor: OK` | 0 |
| 13 | typo'd manifest key (`sumary:` for `summary:`) | **NO** | `kb doctor: OK` (summaries silently become `""`) | 0 |
| 14 | invalid YAML in `index.yaml` | **yes** | `[error] index.yaml in '…' is corrupt — …` | 1 |
| 15 | invalid `kind:` / invalid YAML in `config.yaml` | **NO — crashes** | rich `ValidationError` / `ParserError` traceback (**H1**) | 1 |
| 16 | hub: `federation/index.yaml` drifted from the sub-snapshots | **yes** | `[error] federation/index.yaml is out of sync with the snapshots — run 'kb reindex'` | 1 |
| 17 | hub: `federation/index.yaml` deleted | **yes** | `[error] federation/index.yaml is missing — run 'kb reindex'` | 1 |
| 18 | hub: published L2 content tampered with in place | **NO** | `kb doctor: OK` | 0 |
| 19 | `--context` fresh / stale / broken | **yes** | `OK` / `[warning] L2 content has changed since the pinned version` / `[error] §9.9 is not in manifest … at rev …` | 0 / 2 / 1 |

**Caught 12/19, missed 6, crashed 1.**

---

## 5. Criteria scorecard

| Criterion | Verdict | Why (one line) |
|---|---|---|
| **C7 — hub-first (REST API + Web UI read only `federation/`)** | **met** | Every web read goes through `resolve_hub(config.hub).federation_dir`; the only local read is `.kb/config.yaml`; `_find_asset` touches the **hub's** `.kb`, never the caller's. Hub down → 503 on `/api/*` and the section page, "hub offline" chip on the UI. |
| **C7 — publish/no-op integrity as seen from the web/health tools** | **partially** | H3: a fresh hub cache clone on Windows makes a byte-identical publish produce two hub commits and a permanent false drift warning. |
| **C8 — `kb doctor`** | **partially** | Exit codes 0/1/2 exact; catches 12/19 corruptions; misses duplicate ids, orphan L2 headings, stale token counts, L3-newer-than-L2, unknown manifest keys and hub content tampering; and **crashes with a traceback** on the very case (`config.yaml` invalid) it has a handler for (H1). |
| **C8 — `kb diff`** | **partially** | Added/removed/changed classification and output order are correct and deterministic; error paths are clean (exit 1). But titles and ordering are never compared (M14) and the README states the opposite of the actual L2 behaviour (H2). |
| **C15 — web security (bearer token, cookie for /ui, rate limiting on auth)** | **partially** | Constant-time compares, 401/302 correct, no query-string token, no traceback leaks, textbook-clean XSS and traversal defence. But: cookie = raw secret with no `Secure`/expiry and no logout (M4); zero security headers (M5); the limiter covers login+intake only, so the same secret is unlimited over `Authorization` (M6) and collapses to one bucket behind a proxy (M7). |
| **C15 — Windows fully supported** | **partially** | `utf8io` verified working under pipes; but `gate.sh` and `check_package.py` cannot run on Windows at all (M15), and the default `core.autocrlf=true` produces false doctor warnings + hub churn (H3). |
| **C15 — sdist contains only `src/`** | **met** | `only-include=["src"]` + an allowlist check in `check_package.py`, with the copyright rationale documented. |
| **C17 — release gate scripting** | **partially** | T1–T4 are wired and the packaging check is well designed, but the runner is POSIX-only, so "run the gate before tagging" is not available to a Windows developer. |
| **Code quality** | **good with specific gaps** | Clean layering (`typer.echo` only in `cli.py`, `logging` in libraries, one shared `_hub_or_exit` used by 11 of 12 hub commands with identical flag>env>config precedence); no dead `except:`/`BaseException` swallows (the two `BaseException` handlers re-raise after closing the sqlite connection — correct). Weak points: `cli.py` at 1871 LOC keeps ~505 lines of orchestration that no module owns (the doctor hub/kind branch at `:1808-1852` contains three of the four silent `except Exception`s and both H1 and M13), exit code `2` is overloaded (M11), models are non-strict (M10), and ruff runs on the default rule set only (L28). |
| **Test quality** | **strong** | 1875 pass / 5 skip / 0 fail in 548 s; ruff clean; 3960 asserts over 1805 tests; exactly one test with no assertion at all; **no mocking library anywhere** — real filesystems, real git, `monkeypatch` seams. Untested: `check_package.installed_version`, `ratelimit._sweep`, the corrupt-`config.yaml` path (H1), the corrupt-federation-manifest 500 (M8), cookie flags, security headers, `/api` rate limiting. `tests/test_windows_hygiene.py`'s writer list is a hardcoded 6 (M16). |

---

## 6. Top 3 recommendations

1. **Make the health tool survive the thing it exists to diagnose, and stop shipping tracebacks.**
   Move `check_kind(kb_dir)` above `_hub_or_exit` in `cli.py:1805-1806` (or wrap `load_config` in
   `_hub_or_exit`), and add a top-level `except (yaml.YAMLError, ValidationError)` in the typer
   `main` callback that prints one red line and exits 1. Then close the doctor blind spots that
   cost nothing to add: duplicate section ids, L2/L3 headings absent from the manifest, and a
   `tokens` recount (`kb build` already computes it). Add `extra="forbid"` to the models in
   `models.py` so a typo'd manifest key is an error instead of a silently empty summary.

2. **Bring the HTTP surface up to the level the rest of the code already sets.** One small
   middleware adds `Content-Security-Policy: default-src 'self'`, `X-Frame-Options: DENY`,
   `X-Content-Type-Options: nosniff` and `Referrer-Policy: strict-origin-when-cross-origin`;
   `set_cookie(..., secure=True, max_age=…)` behind a `CENTER_KB_HTTP_INSECURE_COOKIE` escape hatch
   for local dev, plus a `/ui/logout` route that deletes it; store a derived session id rather than
   the raw bearer token; and apply the existing `SlidingWindowLimiter` to unauthenticated `/api/*`
   and `/mcp` responses in `TokenAuthMiddleware` so the login lockout cannot be side-stepped by
   using the header. Guard `api.load_manifest` (`api.py:66`) so a corrupt snapshot renders the
   error page instead of a bare 500.

3. **Close the Windows gap for real, not by documentation.** Pass `-c core.autocrlf=false -c
   core.eol=lf` in `gitio.clone` (copy the two lines already in `intake.py:239`), ship a
   `.gitattributes` (`* text=auto eol=lf`) in the `kb init` scaffold for both hub and child, and
   normalise line endings in `_kb_tree_digest`/`_fed_tree_digest` before hashing. In the same pass,
   make `scripts/check_package.py` and `scripts/gate.sh` pick `bin` vs `Scripts` from
   `sys.platform`, and replace `test_windows_hygiene.COMMITTED_WRITERS`'s hardcoded list with a scan
   of every module that writes under a `.kb` path. Finally, fix `README.md:449` to match
   `kb diff`'s real (better) behaviour and give `ruff` an explicit `select` that includes `B`,
   `BLE`, `S` and `RUF100`, so the passing lint result starts meaning something.
