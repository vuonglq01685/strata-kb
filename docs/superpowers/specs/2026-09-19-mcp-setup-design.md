# `kb mcp-setup` — connect a reader repo to the hub's HTTP MCP — Design

**Date:** 2026-09-19
**Status:** Approved
**Extends:** `2026-07-15-kind-aware-docker-setup-design.md`

## Problem

`kb init` scaffolds `.mcp.json` and `.cursor/mcp.json` on `child`, `ba` and
`dev` repos with two unresolved placeholders:

```json
{ "mcpServers": { "strata-kb": {
  "type": "http",
  "url": "${STRATA_KB_HUB_URL}/mcp",
  "headers": { "Authorization": "Bearer ${STRATA_KB_HTTP_TOKEN}" } } } }
```

Both Claude Code and Cursor expand those from the **process environment**.
Nothing in the toolchain sets them. QUICKSTART tells the user to set two
environment variables by hand and to obtain the token out of band. Three gaps
follow:

1. **No writer.** The user picks where the values live — shell profile, an
   ad-hoc `export`, nothing at all — and a repo with no root `.gitignore`
   (`ba` and `dev` get none from `kb init`; only `hub` does) invites a token
   into git.
2. **No verifier.** Nothing checks that the URL points at a hub or that the
   token is accepted. The first symptom is the assistant silently having no
   KB tools, which reads as "the KB is broken", not "my env is unset".
3. **`kb doctor` does not cover this.** Its `--hub` is the *git/path*
   federation hub used by `kb query` / `kb resolve` / `kb ticket lint`. The
   HTTP MCP endpoint at `:8321/mcp` is a different thing with a different
   value, and doctor never touches it.

Secondary, found while scoping: `dockersetup.repo_kind()` raises
`"repo kind is not recorded — run \`kb init\` first"` for `kind: ba` and
`kind: dev`. The kind *is* recorded; the message is wrong, and the function is
unusable by any new caller that supports those kinds.

## Decisions

### 1. New command `kb mcp-setup`

```
kb mcp-setup [PATH]
  --hub-url TEXT   Hub HTTP base, e.g. http://kb-hub.example.com:8321
  --token TEXT     Hub HTTP token (env: STRATA_KB_HTTP_TOKEN)
  --no-verify      Write the files, skip the network probe
```

`PATH` defaults to `.`, mirroring `docker-setup`. There is no `--force`:
writing merges line-by-line into `.env` and destroys nothing, so there is
nothing to guard.

It is the mirror of `docker-setup`: one command stands the service up
(`hub|child`), one connects a client to it (`child|ba|dev`).

**Kind guard.** `hub` exits 1 — "the hub serves MCP over stdio; it does not
need `mcp-setup`". Unset or unrecognised kind exits 1 — "run `kb init` first".

### 2. Resolution order

Both values resolve through the same chain, first hit wins:

`--flag` → environment variable → **the value already in `.env`** → hidden
prompt when stdin is a TTY → exit 1.

The `.env` rung is what makes a bare `kb mcp-setup` on an already-configured
repo mean *re-verify*, asking nothing. It also lets a URL change reuse the
stored token. Both properties are load-bearing for the assistant wrapper
(§5).

When `--token` is used, print one yellow line: the token lands in shell
history.

### 3. Writing

`write_env(repo_root, hub_url, token)`:

- Merge `STRATA_KB_HUB_URL` and `STRATA_KB_HTTP_TOKEN` into `.env`
  line-by-line, creating the file when absent and preserving every other
  line. On `child`, `.env` has a second real consumer — docker-compose
  variable substitution — so this is the right file, not an invention.
- Call `ensure_gitignored(repo_root)`, which creates `.gitignore` when the
  repo has none. `ba` and `dev` repos have none.

`normalize_hub_url(raw)` strips a trailing `/` (the templates append `/mcp`,
so a trailing slash yields `//mcp`) and rejects any scheme other than
`http`/`https` — the same S310 concern `cipublish._default_http` guards.

The token is never echoed. Output states that `.env` holds it, mirroring
`docker-setup`'s existing "token not shown; see .env".

### 4. Shell activation output

```
Load into the current shell:
  bash/zsh:   set -a; source .env; set +a
  PowerShell: Get-Content .env | %{ $k,$v = $_.Split('=',2); [Environment]::SetEnvironmentVariable($k,$v) }
To persist: add the line above to ~/.zshrc, or use direnv.
```

Deliberately **not** two literal `export` lines: `source .env` reaches the
same environment without printing the token into terminal scrollback. The
`.env` files this command writes are plain `KEY=value`, so `source` is safe
on them; if a user has put exotic content in `.env`, `source` fails loudly
rather than silently.

### 5. Verification probe

Skipped under `--no-verify`. Two requests, 10s timeout each.

| Request | Result | Behaviour |
|---|---|---|
| `GET {url}/api/health` (auth-exempt) | status 0 | exit 1 — cannot reach `{url}`; check the URL, that the hub is running, and the firewall. Include the connection error. |
| | ≠ 200 | exit 1 — `/api/health` returned `{status}`; this URL does not look like a Strata KB hub. |
| `GET {url}/api/docs` + `Authorization: Bearer` | 200 | success — "token accepted, N documents visible". `N` from `{"docs": [...]}`; drop `N` if the body is not that shape. |
| | 401 / 403 | exit 1 — hub reachable but the token was rejected (`{status}`); ask the hub maintainer for a fresh token. |
| | 503 | **exit 0** + yellow warning — token accepted; the hub reports its own KB is not ready. Tell the hub maintainer. |
| | other | exit 1 — unexpected `{status}` from `/api/docs`. |

The two-request split is the point: `/api/health` sits in `web/auth.py`'s
`EXEMPT_PATHS`, so it separates "wrong URL / hub down" from "wrong token". A
503 from `/api/docs` can only arrive *after* the auth middleware passed the
request, so it proves the token is good — this command's job is done, hence
exit 0.

**On any probe failure `.env` stays written.** Rolling back would discard what
the user just typed. Print: `.env` is written — correct the value and re-run.

The command ends with: restart Claude Code / Cursor so MCP picks up the
environment. MCP servers read env only at client startup.

### 6. Assistant wrappers

Four files per repo, the same layout every other command uses:

```
.claude/skills/kb-mcp-setup/SKILL.md      claude-skill-kb-mcp-setup.md
.claude/commands/kb-mcp-setup.md          claude-command-kb-mcp-setup.md
.github/prompts/kb-mcp-setup.prompt.md    copilot-kb-mcp-setup.prompt.md
.cursor/commands/kb-mcp-setup.md          cursor-kb-mcp-setup.md
```

**The wrapper never handles the token.** An assistant runs the CLI in a
non-TTY subprocess, so the hidden prompt is unavailable; asking for the token
in chat would write a live credential into the transcript. The wrapper flow
is therefore:

1. Read `kind` from `.kb/config.yaml`. `hub` → say it does not apply, stop.
2. Ask for the hub URL in chat — not a secret.
3. Tell the user to run `kb mcp-setup --hub-url <url>` **in their own
   terminal**, where the hidden prompt works.
4. Once the user confirms, run bare `kb mcp-setup` — it finds both values in
   `.env` (§2), re-verifies, and the wrapper relays the result.
5. Close with the restart instruction.

**Scaffolding.** These rows cannot go in `COMMON_TEMPLATES`, which is the
hub+child merge. Add a new `MCP_CLIENT_TEMPLATES` dict and spread
`**MCP_CLIENT_TEMPLATES` into `CHILD_TEMPLATES`, `BA_TEMPLATES` and
`DEV_TEMPLATES`, using the `**{...}` spread `DEV_TEMPLATES` already uses. The
hub gets none of them.

### 7. Module layout

**New: `src/strata_kb/mcpsetup.py`** — pure logic plus the probe, so tests
monkeypatch helpers and never touch the network. Follows `dockersetup.py`.

```python
class McpSetupError(KbError): ...

def normalize_hub_url(raw: str) -> str
def write_env(repo_root: Path, hub_url: str, token: str) -> EnvReport
def probe(hub_url: str, token: str, http=None) -> ProbeResult   # `http` = test seam
```

CLI dispatch stays in `cli.py`, as `docker_setup` does.

**New: `src/strata_kb/httpio.py`** — `cipublish._default_http` extracted, with
a `timeout` parameter added:

```python
def request(method, url, headers, body=None, timeout=60) -> tuple[int, bytes]
```

`cipublish._default_http` becomes a thin call into it. The reason to extract
rather than copy twelve lines: the S310 scheme guard is a security check, and
two copies of a security guard is how one copy drifts. The repo already has
`gitio.py`, `ghio.py` and `utf8io.py`, so `httpio.py` fits the naming.

`request` keeps `cipublish`'s existing conventions unchanged — status `0`
means a connection-level failure (DNS, refused, timeout), and `HTTPError` is
flattened to `(code, body)`.

### 8. Changes to `dockersetup.py`

These are prerequisites, not opportunistic refactoring — `mcpsetup` needs to
read `ba`/`dev` kinds and to reuse the `.env`/`.gitignore` writers.

- `repo_kind()` returns whatever kind is recorded (`hub|child|ba|dev`) and
  raises only when it is empty or unrecognised. Each caller asserts the kinds
  it supports.
- `docker_setup` in `cli.py` gains its own `hub|child` guard, with a message
  that names the actual kind — replacing the wrong "kind is not recorded"
  that `ba`/`dev` currently hit.
- `_ensure_gitignored()` → `ensure_gitignored()` (public).
- Extract `set_env_line(text, var, value) -> str` from the existing
  `_TOKEN_LINE` regex logic. `run_setup` and `mcpsetup.write_env` both use it.
- `_require_hub_kind()` must be tightened in the same change. It currently
  raises only on `kind == "child"`, which was sufficient while `repo_kind()`
  raised for everything else. Once `repo_kind()` returns `ba`/`dev`, that test
  lets them through. Invert it: raise unless the kind is `hub`. `run_setup` is
  only reached from `_docker_setup_hub` today, so nothing is broken in
  practice — but the guard must not be left depending on its caller.

## Documentation

- `QUICKSTART-child.md`, `QUICKSTART-ba.md`, `QUICKSTART-dev.md` — replace the
  "set two environment variables" step with `kb mcp-setup`, keep both variable
  names documented, and add the command to the reference list at the foot of
  each file.
- `docs/deploy-remote-mcp.md` — add the client-side half.

## Testing

Mirrors the `dockersetup` test style: helpers are monkeypatched, no test
touches a real network or a real Docker.

| Area | Cases |
|---|---|
| `normalize_hub_url` | strips trailing `/`; rejects `file://` and `ftp://`; rejects empty |
| `write_env` | creates `.env`; merges while preserving other lines; updates an existing value in place; creates `.gitignore` when absent; appends `.env` to an existing `.gitignore`; no-op when already ignored |
| `probe` (seam `http`) | connection failure (status 0); health ≠ 200; docs 200 with N; docs 200 with an unexpected body; 401; 403; 503; 500 |
| CLI | `hub` exits 1; unset kind exits 1; happy path on child/ba/dev exits 0 **and the token never appears in stdout**; `--no-verify` never calls the seam; probe failure exits 1 with `.env` still written; a re-run resolves both values from `.env` without prompting; `--token` prints the history warning |
| `dockersetup` regression | `repo_kind` returns `ba`/`dev` instead of raising; `docker_setup` still exits 1 on `ba`/`dev`, with the new message; `_require_hub_kind` raises on `ba` and `dev`, not only on `child` |
| `httpio` | existing `cipublish` tests stay green; `request` rejects a non-http(s) scheme |
| init parity | the four wrapper files exist on child/ba/dev and **not** on hub — extend the existing assistant-parity test's command list |

Coverage target: 80%, per the repository rule.

## Out of scope

- Filling `hub:` in `.kb/config.yaml`. That is the git/path federation hub, a
  different value from the HTTP MCP URL; folding both into one command invites
  users to conflate them. `kb mcp-setup` does one thing.
- A `hub`-side variant that verifies `localhost:8321` against the hub's own
  `.env`. Different behaviour under one command name.
- Any MCP check inside `kb doctor`.
