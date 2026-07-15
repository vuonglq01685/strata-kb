# Kind-aware `kb docker-setup` + symbol-only heading filter — Design

**Date:** 2026-07-15
**Status:** Approved
**Extends:** `2026-07-13-role-aware-init-design.md`

## Problem

1. `kb docker-setup` stops at credentials (`.env` + token) and only *prints*
   `docker compose up -d` as a next step. Users expect "setup" to end with a
   running service.
2. Child repos get no `/kb-docker-setup` at all — the CLI refuses on
   `kind: child`. But the published image bundles the full `[ingest]` docling
   stack precisely so a child author needs **no local Python**; the only
   missing convenience is a Docker check + `docker compose pull` so the first
   ingest doesn't stall on an image download.
3. Ingest artifact: a PDF horizontal-rule/footnote line (`_____`) survives
   docling as a heading and becomes a fallback section node (e.g. `8.4-x1`)
   with an empty body in the raw file. Cosmetic, but noise.

## Decisions

### 1. `kb docker-setup` becomes kind-aware

`kb docker-setup [path] [--force] [--no-docker]` reads `kind:` from
`.kb/config.yaml`:

- **hub** — unchanged env/token flow (`run_setup`, `EnvExistsError` +
  `--force`/TTY confirm), then, unless `--no-docker`:
  - Docker daemon reachable → run `docker compose up -d` (output streamed);
    non-zero exit → red error, exit 1. Success → print UI URL + MCP snippet.
  - Docker not reachable → yellow note + the current manual next-steps block;
    exit 0 (env creation alone is still useful).
- **child** — never writes `.env` (no HTTP server, no secret to hold).
  Unless `--no-docker`:
  - Docker not reachable → red message, exit 1 (pull is the whole job).
  - Reachable → `docker compose pull`; non-zero → exit 1. Then print the
    one-shot ingest command and a note that the first ingest still downloads
    layout/table models into the `kb-model-cache` volume.
- **kind unset** — exit 1, "run `kb init` first" (unchanged).
- `--force` help text scoped to hub; ignored on child.
- `--no-docker` = prepare files/messages only, skip `docker info`/compose.

New helpers in `dockersetup.py`: `repo_kind(repo_root)`, `docker_ready()`
(`docker info`, 30 s timeout, `FileNotFoundError`/timeout → False),
`compose_up(repo_root)`, `compose_pull(repo_root)` (both stream output,
return exit code). `run_setup` keeps its hub-only guard so direct callers
stay safe.

### 2. Wrapper templates become common

The four `kb-docker-setup` wrappers (Claude skill + command, Copilot prompt,
Cursor command) move from `HUB_TEMPLATES` to `COMMON_TEMPLATES` with
kind-neutral text: describe both behaviors, keep the hard rules (never print
`.env`/token; relay errors verbatim; no manual workarounds). The CLI is the
single source of kind logic — wrappers stay thin.

### 3. Post-init next steps

- Hub: `kb docker-setup  # .env + HTTP token + docker compose up -d` → open
  UI → ingest.
- Child: fill `hub:` → `kb docker-setup  # optional: pull the Docker ingest
  image` → ingest → publish.

### 4. Docs

- `QUICKSTART-hub.md`: steps 1–2 merge (docker-setup now starts the service;
  manual fallback preserved). CLI reference line updated.
- `QUICKSTART-child.md`: new "pull the ingest image (optional)" step;
  CLI reference gains `kb docker-setup`.
- README: docker-setup description covers both kinds; slash-command list no
  longer says "and on the hub `/kb-docker-setup`".

### 5. Sectioner: drop symbol-only headings

In `_build_tree`, a heading whose normalized text contains **no alphanumeric
character** (`_____`, `---`, `***`) is skipped entirely — it opens no node
(no more `x1` fallbacks) and is not demoted to body text (it carries no
content; it is a graphic artifact). Applies at ingest time only; existing
KBs are untouched until re-ingest.

## Testing

- `test_dockersetup.py`: existing `run_setup` unit tests unchanged. CLI tests
  monkeypatch `docker_ready`/`compose_up`/`compose_pull`; cover hub with/
  without Docker, hub compose failure, child pull success/failure/no-Docker,
  `--no-docker` on both kinds, kind-less refusal. Token still never printed.
- `test_init.py`: docker-setup wrappers asserted for BOTH kinds (test renamed
  from `..._hub_only`); Cursor command both kinds; assistant-parity list
  includes `kb-docker-setup` for child; child QUICKSTART now mentions
  `kb docker-setup`.
- `test_sectioner.py`: symbol-only heading produces no unit and no `x1` id.

## Acceptance criteria

- `kb docker-setup` on hub with Docker: `.env` + token + service running,
  token absent from stdout.
- On hub without Docker: `.env` + token + manual steps, exit 0.
- On child with Docker: image pulled, ingest command printed, no `.env`.
- On child without Docker: exit 1, clear install message.
- Both kinds scaffold all four `/kb-docker-setup` wrappers.
- Re-ingesting a document with `_____` headings produces no `-x1` sections.
