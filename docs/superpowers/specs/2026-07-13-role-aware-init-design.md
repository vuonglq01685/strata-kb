# Role-aware `kb init` + hub-only `kb docker-setup` — Design

**Date:** 2026-07-13
**Status:** Approved

## Problem

CENTER-KB is hub-first: `kb query` / MCP / Web UI read only `federation/` on the
hub. Child repos author in `.kb/` and `kb publish` to the hub. Today `kb init`
scaffolds one identical layout for every repo (docker-compose, `.mcp.json`,
`federation/`, `.env.example`, …) with no hub-vs-child distinction, and the
post-init "Next steps" assume the hub role. There is also no guided way to
prepare the hub's `.env` + HTTP token.

## Goals

1. Make hub vs child a **required** choice when initializing a repo.
2. Scaffold differently for each kind.
3. Add a hub-only `kb docker-setup` CLI command with Claude/Copilot/Cursor
   slash-command wrappers that creates `.env` and auto-generates the HTTP token.
4. Extend assistant support from Claude Code + GitHub Copilot to also cover
   Cursor (commands, `.kb/**` rule, MCP wiring) at feature parity.

## Non-goals (out of scope)

- Changing the hub-first read path (federation-only query/MCP/Web).
- OAuth/SSO for HTTP MCP.
- Removing Docker from child repos (ingest stays Docker-first).
- Automated migration when a repo *switches* kind (manual config edit; init
  never deletes files).

---

## 1. Kind persistence

`KBConfig` (`src/center_kb/config.py`) gains `kind: str = ""` with allowed
values `"hub"`, `"child"`, `""` (legacy/unset). The kind lives in
`.kb/config.yaml` — already in `PROTECTED_FILES` and committed to git — so it
is the single durable record of the repo's role, readable by `kb docker-setup`,
`kb doctor`, and re-runs of `kb init`.

## 2. `kb init` kind resolution

`kb init [path] [--kind hub|child] [--force]`. Resolution order:

1. **Persisted kind wins.** If `.kb/config.yaml` has `kind:`, re-runs refresh
   silently with no prompt (today's idempotent-refresh workflow is preserved).
   A conflicting `--kind` exits 1 with a message pointing at `config.yaml`
   (switching kind is a deliberate manual edit).
2. **`--kind hub|child`** is used when no kind is persisted. Values validated
   by a Typer enum.
3. **Interactive prompt** when no persisted kind, no flag, and stdin is a TTY.
   The prompt shows both role descriptions and loops until a valid choice; no
   default.
   - **Main hub:** hosts `federation/`, the single source of truth for search;
     runs the shared HTTP MCP server + Web UI (`docker compose up -d`,
     port 8321); receives publishes from child repos (merging hub PRs is the
     review gate); may also keep its own `.kb/` and publish itself into
     `federation/<repo-id>/`.
   - **Child repo:** authoring repo — ingest PDFs → summarize → `kb build` →
     `kb publish` to the hub; needs Docker mainly for one-shot ingest
     (`docker compose run --rm hub kb ingest …`), not for the long-lived hub
     server; must set `hub:` (+ `repo_id:`) in `.kb/config.yaml`; does not host
     the company-wide MCP/Web service.
4. **Non-interactive without a kind** (no TTY, no flag, nothing persisted) →
   exit non-zero: `kb init requires --kind hub|child when not running
   interactively.`

**Legacy repos** (config.yaml exists but lacks `kind:`): kind resolves via
flag/prompt as in a fresh init, then a `kind: <value>` line is **appended to
the existing file text** — no YAML re-dump, so user comments and `hub:` /
`repo_id:` values survive. This append happens inside `init_repo` (a narrow
exception to the protected-file skip: it only ever adds the missing `kind:`
line, never rewrites the file). Reported as `updated .kb/config.yaml (kind
recorded)`.

**Layering:** kind resolution (flag/prompt/TTY detection) happens in the CLI
layer (`cli.py`); `init_repo(target, kind, force=False)` in `initcmd.py` stays
a pure, testable function.

## 3. Scaffold matrix

`TEMPLATE_MAP` splits into three dicts in `initcmd.py`; `init_repo` merges
`COMMON_TEMPLATES | HUB_TEMPLATES` or `COMMON_TEMPLATES | CHILD_TEMPLATES`.
Templates stay in the flat `templates/init/` directory; kind-specific variants
use `-hub` / `-child` suffixes.

### COMMON (both kinds)

| Target | Template |
|---|---|
| `.kb/index.yaml` | `index.yaml` |
| `source/.gitignore` | `source-gitignore.txt` |
| kb-summarize skill + command + Copilot instructions | unchanged |
| kb-ingest skill + Copilot prompt | unchanged |
| kb-publish skill + Copilot prompt | unchanged |
| `.github/workflows/kb-publish.yml` | unchanged |
| `.cursor/commands/kb-ingest.md` | `cursor-kb-ingest.md` (new) |
| `.cursor/commands/kb-publish.md` | `cursor-kb-publish.md` (new) |
| `.cursor/commands/kb-summarize.md` | `cursor-kb-summarize.md` (new) |
| `.cursor/rules/kb-summarize.mdc` | `cursor-kb-summarize.mdc` (new) |

### HUB only

| Target | Template | Notes |
|---|---|---|
| `.kb/config.yaml` | `config-hub.yaml` | `kind: hub`, `hub: "."`, `repo_id` pre-filled from folder name |
| `docker-compose.yml` | `docker-compose-hub.yml` | current full hub service (ports, env_file, healthcheck) |
| `.env.example` | `env.example` | unchanged |
| `federation/README.md` | `federation-README.md` | unchanged |
| `.mcp.json` | `mcp-hub.json` | current stdio config (maintainer-local); remote HTTP documented in hub QUICKSTART |
| `QUICKSTART.md` | `QUICKSTART-hub.md` | token via `/kb-docker-setup` → `compose up -d` → ingest/publish → query |
| `.claude/skills/kb-docker-setup/SKILL.md` | new | |
| `.claude/commands/kb-docker-setup.md` | new | |
| `.github/prompts/kb-docker-setup.prompt.md` | new | |
| `.cursor/commands/kb-docker-setup.md` | `cursor-kb-docker-setup.md` (new) | |
| `.cursor/mcp.json` | `cursor-mcp-hub.json` (new) | stdio, mirrors the hub `.mcp.json` |

### CHILD only

| Target | Template | Notes |
|---|---|---|
| `.kb/config.yaml` | `config-child.yaml` | `kind: child`, `hub: ""` + fill-me comment, `repo_id` from folder name |
| `docker-compose.yml` | `docker-compose-child.yml` | same image/volumes; **no ports, no env_file, no healthcheck**; header comment frames it as one-shot ingest (`docker compose run --rm hub kb ingest …`). Service keeps the name `hub` so the shared kb-ingest skill text works for both kinds. |
| `.mcp.json` | `mcp-child.json` | HTTP client: `"type": "http"`, `"url": "${CENTER_KB_HUB_URL}/mcp"`, `"Authorization": "Bearer ${CENTER_KB_HTTP_TOKEN}"` — env expansion means no secrets in git and the file stays byte-identical, so init re-runs keep refreshing it |
| `QUICKSTART.md` | `QUICKSTART-child.md` | fill `hub:` → ingest → summarize/build → `kb publish`; documents the two env vars for MCP |
| `.cursor/mcp.json` | `cursor-mcp-child.json` | HTTP client like `mcp-child.json`, but with Cursor's `${env:NAME}` interpolation syntax |

Child gets **no** `.env.example`, `federation/`, or docker-setup bundle.

### Cursor support

Cursor becomes a third supported assistant, at parity with Claude Code and
GitHub Copilot:

- **Commands** (`.cursor/commands/<name>.md`, optional `name`/`description`
  frontmatter): `kb-ingest`, `kb-publish`, `kb-summarize` in COMMON;
  `kb-docker-setup` hub-only. Content is adapted from the Copilot prompt
  variants (agent-agnostic instructions with the same hard rules — e.g.
  "NEVER run `kb ingest`" for the ingest command). The Claude `SKILL.md`
  files are deliberately **not** mirrored into `.cursor/skills/`: the
  kb-summarize skill is a Claude-specific parallel sub-agent orchestrator
  that Cursor cannot execute.
- **Rule** (`.cursor/rules/kb-summarize.mdc`, `globs: .kb/**`): the summary
  writing rules, mirroring `.github/instructions/kb-summarize.instructions.md`
  (`applyTo: ".kb/**"`).
- **MCP** (`.cursor/mcp.json`): Cursor does not read `.mcp.json`, so each
  kind gets a Cursor variant of its MCP client config. Hub: stdio
  (`python -m center_kb.mcp --kb .kb/`). Child: HTTP with
  `"url": "${env:CENTER_KB_HUB_URL}/mcp"` and
  `"Authorization": "Bearer ${env:CENTER_KB_HTTP_TOKEN}"` — Cursor's
  interpolation syntax is `${env:NAME}`, unlike Claude's `${NAME}`, which is
  why the child ships two MCP templates with the same semantics. Both stay
  byte-static and refreshable, with the same no-secrets-in-git property.

### Templating

The only substituted value is `repo_id` (suggested from the target folder
name), filled with `str.format` into the two config templates at init time.
Every other template is byte-for-byte static (keeps the existing
content-equality refresh logic working).

### Post-init "Next steps"

- **Hub:** configure token (`/kb-docker-setup` or manual `cp .env.example
  .env`) → `docker compose up -d` → ingest/publish → query.
- **Child:** fill `hub:` in `.kb/config.yaml` → `kb ingest` (or `/kb-ingest`)
  → `kb publish` (or `/kb-publish`).

### Preserved behavior

- `PROTECTED_FILES` (`.kb/index.yaml`, `.kb/config.yaml`) untouched unless
  `--force`.
- Content-changed scaffold files refresh; identical files are no-ops;
  `InitReport` created/updated/skipped reporting unchanged.
- Init never deletes files (including other-kind leftovers after a manual kind
  switch).

## 4. `kb docker-setup` (hub only)

New Typer command in `cli.py`; logic in a new module
`src/center_kb/dockersetup.py` (mirrors the `initcmd.py` pattern).

Behavior, in order:

1. **Hub gate.** Load `.kb/config.yaml`.
   - `kind == "child"` → exit 1: this command prepares the main hub; this repo
     is a child.
   - `kind` empty/missing → exit 1: run `kb init` first (it records the kind).
   - Only `kind == "hub"` proceeds.
2. **`.env` creation.**
   - Missing → create from `.env.example` (synthesize the
     `CENTER_KB_HTTP_TOKEN=` line if `.env.example` is absent).
   - Existing → never silently overwrite: on a TTY, `typer.confirm` before
     regenerating the token; non-TTY requires `--force`, otherwise exit 1 with
     "found existing .env — re-run with --force to regenerate the token".
3. **Token.** `secrets.token_hex(24)` written as the `CENTER_KB_HTTP_TOKEN`
   value. The token is **not echoed to stdout** (slash-command output lands in
   chat transcripts); the command reports that it was written to `.env`.
4. **Gitignore guard.** If `.env` is not covered by the root `.gitignore`
   (textual check), append a `.env` line and report it.
5. **Output.** Always prints:
   - the warning: *this token was auto-generated for convenience — replace it
     with your own secret for real deployments and store it in a secret
     manager*;
   - next steps: `docker compose up -d`, open `http://localhost:8321/ui`, and
     the client MCP config snippet:

     ```json
     {
       "mcpServers": {
         "center-kb": {
           "type": "http",
           "url": "http://<host>:8321/mcp",
           "headers": { "Authorization": "Bearer <token>" }
         }
       }
     }
     ```

**Wrappers** (hub scaffold only): `.claude/commands/kb-docker-setup.md`,
`.github/prompts/kb-docker-setup.prompt.md`, and
`.cursor/commands/kb-docker-setup.md` are thin — run `kb docker-setup`, relay
its output, never print `.env` contents into chat.
`.claude/skills/kb-docker-setup/SKILL.md` carries the same rules plus the
refusal behavior explanation.

## 5. MCP notes encoded in templates/docs

- The hub `.mcp.json` (stdio `python -m center_kb.mcp --kb .kb/`) is local IDE
  wiring for the hub maintainer, not Docker.
- Production hub serving: `python -m center_kb.mcp --hub <hub> --transport
  http` (or the Docker CMD) with `CENTER_KB_HTTP_TOKEN`.
- `.mcp.json` / `.cursor/mcp.json` are **client** config; the hub server
  process does not read them. Child/BA machines point at the shared hub HTTP
  endpoint via the child env-var templates (`${NAME}` for Claude Code,
  `${env:NAME}` for Cursor).

## 6. Error handling summary

| Situation | Behavior |
|---|---|
| `kb init`, no TTY, no `--kind`, nothing persisted | exit ≠ 0: "pass --kind hub\|child or run interactively" |
| `--kind` conflicts with persisted kind | exit 1, points at `config.yaml` |
| Invalid `--kind` value | Typer enum usage error |
| `kb docker-setup` on child repo | exit 1, role-specific message |
| `kb docker-setup` on kind-less repo | exit 1, "run kb init first" |
| Existing `.env`, non-TTY, no `--force` | exit 1, nothing modified |
| Kind switch after init | manual `config.yaml` edit; init refreshes new-kind files, never deletes old-kind files (documented) |

`kb doctor` gains one cheap check: warn when `kind:` is missing from
`.kb/config.yaml`.

## 7. Testing

Extends the existing `tests/test_init.py` / `CliRunner` patterns.

**Init:**
- Per-kind file-set assertions: hub gets federation/env/docker-setup bundle;
  child gets HTTP `.mcp.json` + ingest-only compose and none of the hub-only
  files; common files present for both.
- `--kind hub` / `--kind child` non-interactive paths.
- CliRunner (non-TTY) without `--kind` fails with the clear message.
- Interactive prompt path via `input="hub\n"` (and an invalid-then-valid
  input sequence).
- Persisted-kind reuse: re-run does not prompt, idempotent refresh still works.
- Conflicting `--kind` on re-run errors.
- Legacy config: `kind:` appended, existing `hub:`/comments preserved.
- Protected files / `--force` behavior unchanged (existing tests keep passing
  with kind parameter added).
- `repo_id` suggestion from folder name in both config templates.

**docker-setup:**
- On hub: `.env` created; token is 48 hex chars and ≠ `change-me`; warning
  text present; token absent from stdout; MCP snippet in output.
- Existing `.env` untouched without confirm/`--force`; `--force` regenerates.
- Refusal on child and on kind-less repos (exit 1 + message).
- Gitignore append when `.env` not ignored.

**Templates:**
- Content assertions for the three new docker-setup wrapper templates
  (invoke `kb docker-setup`, never print `.env` contents).
- Both QUICKSTARTs: next steps match kind; hub mentions `/kb-docker-setup`;
  child mentions filling `hub:` and has no "serve the hub" step.
- Child `.mcp.json` uses `${CENTER_KB_HUB_URL}` / `${CENTER_KB_HTTP_TOKEN}`;
  child `.cursor/mcp.json` uses `${env:CENTER_KB_HUB_URL}` /
  `${env:CENTER_KB_HTTP_TOKEN}`.
- Child compose has no `ports:`; service name stays `hub`.
- Cursor templates: the three common commands + hub-only docker-setup command
  carry the same hard rules as their Copilot counterparts (e.g.
  "NEVER run `kb ingest`"); `cursor-kb-summarize.mdc` has `globs` targeting
  `.kb/**` and the prose-only summary rules; assistant-parity assertion that
  every kb-* slash command exists for Claude, Copilot, and Cursor in the
  scaffold of each kind.
- `test_templates.py` resource-existence check covers the new/renamed
  templates via the merged maps.

## 8. Documentation

- README: role split (hub vs child), per-kind init flow, `kb docker-setup`.
- `QUICKSTART-hub.md` step 1 becomes `/kb-docker-setup` (manual
  `cp .env.example .env` as fallback).
- `QUICKSTART-child.md` next steps: fill `hub:` → ingest → publish; env vars
  for the MCP client.
- CLI reference in QUICKSTARTs/instructions gains `kb docker-setup` (hub
  QUICKSTART) and documents `kb init --kind`.
- README/QUICKSTARTs name Cursor as a supported assistant alongside Claude
  Code and GitHub Copilot (slash commands work in all three; MCP wiring via
  `.mcp.json` for Claude Code and `.cursor/mcp.json` for Cursor).

## 9. Acceptance criteria

- `kb init` in a TTY always asks hub vs child with clear descriptions and
  refuses to proceed without a choice.
- `kb init` without TTY requires `--kind hub|child`; missing kind fails
  clearly.
- Hub and child scaffolds differ per the matrix above.
- Re-running `kb init` on an initialized repo reuses the persisted kind and
  stays idempotent.
- `kb docker-setup` on a hub writes `.env`, generates a token, warns to
  replace it; refuses on child/kind-less repos.
- Tests cover both kinds, non-interactive `--kind`, the prompt path, and the
  docker-setup command + wrapper templates.
- Cursor gets the same kb-* slash commands as Claude/Copilot, a `.kb/**`
  summary-rules rule, and per-kind `.cursor/mcp.json` wiring.
- README / QUICKSTART next steps match the chosen kind.
