# D — Conventions pack shipped with the center-kb package

**Status:** approved design, ready for an implementation plan
**Roadmap items:** batch 5 (D1–D5) of
`docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md`.
**Approach:** option A as approved on 2026-08-24 — a language-detecting
post-step inside `kb init` (kind `dev` only). `template_map()` stays static,
linter presets ship embedded in the conventions base file, `CLAUDE.md` is
touched only through an append-only marker block. No MCP change, no schema
change, no new MCP tool.

## Goal

Per the settled decision, conventions have no hub tier: everything ships in
the package and is scaffolded by `kb init`. A dev repo gets, per detected
language:

- a **base** conventions file (`docs/conventions/<lang>.md`) that is
  package-owned and receives upstream updates on re-init,
- a **local** override file (`docs/conventions/<lang>.local.md`) that the
  package never touches and that wins over base on conflict (D3),
- thin **pointer rules** in the places each assistant reads every session
  (`CLAUDE.md`, `.cursor/rules/`, `.github/instructions/`) (D2),
- a **linter/formatter preset** embedded in the base file that the first task
  of a dev plan materialises when the repo has no linter (D1),
- and dev-skill text that points at these files explicitly instead of the
  vague "the repo's existing conventions" (D4).

Every scaffold/template change bumps its trip-wire test deliberately (D5).

## Decisions taken during brainstorming (2026-08-24)

1. **D1 delivery = plan-task, not init-time scaffold.** `kb init` never writes
   `ruff.toml` / eslint config / etc. Preset content lives verbatim in the
   *Linting* section of each base conventions file; `dev-plan` gains one
   sentence: when the repo has no linter, the plan's first task sets one up
   from that preset and records the command as `cmd.lint`. Rationale: writing
   linter configs at init risks clobbering repos that already have a
   differently-configured linter, and adds files to the re-init overwrite
   cycle for no benefit.
2. **CLAUDE.md = append-only marker block** (`<!-- kb:conventions -->`),
   modelled on the existing `_record_kind` pattern: missing file → create with
   the block; file present without marker → append the block; marker present →
   skip. User content is never rewritten.
3. **Language scope v1 = all six ecosystems** codeingest can already read:
   `python`, `ts`, `java`, `go`, `php`, `dotnet`.
4. **Mechanism = post-step detection** (approach A). Rejected: scaffolding all
   six languages statically (≈24 irrelevant files in a single-language repo);
   a separate `kb conventions init` CLI (new surface, contradicts the
   scaffold-at-init decision).

## Scope

**In:**

- `src/center_kb/conventions.py` — new module: language detection + the
  conventions scaffold step.
- `src/center_kb/initcmd.py` — `init_repo()` calls the step for kind `dev`.
- `src/center_kb/templates/init/` — 9 new resources: 6 base files
  (`conventions-python.md`, `conventions-ts.md`, `conventions-java.md`,
  `conventions-go.md`, `conventions-php.md`, `conventions-dotnet.md`),
  1 local stub (`conventions-local-stub.md`), 2 pointer templates
  (`conventions-pointer.mdc`, `conventions-pointer.instructions.md`).
- Skill-text round, 2 skills × 4 wrappers: `dev-plan` (D1 sentence) and
  `dev-execute` (D4 checkpoint), plus their canon pins.
- `tests/test_conventions.py` (new), `tests/test_init.py`,
  `tests/test_templates.py`.

**Out, and deliberately so:**

- **MCP.** No tool, no signature, no docstring changes. The golden
  `tests-gate/golden/mcp_tools.json` stays byte-identical — verified by
  `git diff` at review time, as in the C1 batch.
- **Kinds `hub`, `child`, `ba`.** Conventions describe product code; only
  kind `dev` writes product code.
- **`dev-handover`.** The D4 conflict finding flows into the PR body through
  the existing findings path; no handover text change.
- **`template_map()` / `expected_files()`.** Untouched; conventions files are
  written by the post-step, not the static map.
- **A hub-side conventions tier** — rejected earlier at roadmap level.
- **D4's "if conventions content ready" coupling to the shared template
  round** — moot: this batch ships content and skill text together.

## Evidence this design rests on

Read from the tree at `4afe27d`, 2026-08-24. Each fact decided something.

**1. The re-init overwrite loop is the D3 tension.** `init_repo()`
(`initcmd.py:268–279`) rewrites any existing file not in `PROTECTED_FILES`
whenever its content differs from the template. A hand-edited conventions
file in that loop would be silently reverted on the next `kb init`. Hence the
two-file split: base rides the overwrite semantics on purpose (that is how it
receives upstream updates), local is skipped-once-created by the conventions
step itself.

**2. `_record_kind` is the CLAUDE.md model.** `initcmd.py:212–226` appends a
missing `kind:` line to a pre-existing user file and never rewrites content.
The marker block reuses exactly this shape.

**3. `detect_frameworks()` cannot detect at init time.** It matches
*dependency names* (`codeingest/extractors/deps.py:83`), which requires
parsing manifests. Init-time detection needs only manifest *presence*; the
node reader's depth-≤-2 `package.json` scan sets the precedent for search
depth.

**4. The D1 anchor exists.** `dev-plan`'s "No `-code` document yet" bullet
(`claude-skill-dev-plan.md:49–53`) already handles the missing-`cmd.*` case
by asking the Dev once; it says nothing about a repo with *no linter at all*.
The D1 sentence extends this bullet in place.

**5. The D4 anchor exists in all four wrappers.** The checkpoint line "the
change follows the repo's existing conventions" appears in
`claude-skill-dev-execute.md:59`, `claude-command-dev-execute.md:51`,
`copilot-dev-execute.prompt.md:59`, `cursor-dev-execute.md:59`.

**6. `_render` substitutes only `{repo_id}` and only for `config-*`**
(`initcmd.py:201–209`). Pointer templates need `{lang}`/`{globs}`
substitution, so the conventions step gets its own small render helper rather
than widening `_render`'s contract.

**7. Dev repos scaffold no `CLAUDE.md` today** (`DEV_TEMPLATES`,
`initcmd.py:96–145`) — the marker step is the first time init touches it.

## Design

### §1 Engine — `src/center_kb/conventions.py`

```python
LANG_MANIFESTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dotnet", ("*.csproj",)),
    ("go",     ("go.mod",)),
    ("java",   ("pom.xml", "build.gradle", "build.gradle.kts")),
    ("php",    ("composer.json",)),
    ("python", ("pyproject.toml", "setup.cfg", "requirements*.txt")),
    ("ts",     ("package.json",)),
)
```

- `detect_langs(root: Path) -> list[str]` — glob each pattern at the repo
  root and up to two directory levels below it (root counts as depth 0;
  `web/package.json` is depth 1 — matching the codeingest node reader's
  precedent);
  skip `.git`, `node_modules`, `.kb`, `docs` while walking. Deterministic:
  sorted language ids, de-duplicated.
- `scaffold_conventions(target: Path, report: InitReport) -> None` — for each
  detected language:
  - `docs/conventions/<lang>.md` from `conventions-<lang>.md` — create when
    missing, rewrite when content differs (same semantics as the main loop:
    `created` / `updated` rows in the report).
  - `docs/conventions/<lang>.local.md` from `conventions-local-stub.md` —
    create when missing; when present, skip unconditionally (report
    `skipped`). Never compared, never rewritten, `--force` does **not**
    override it (it is user data in the same sense as `.kb/config.yaml`,
    but its path is dynamic so it cannot sit in `PROTECTED_FILES` —
    the step enforces the skip itself).
  - `.cursor/rules/coding-<lang>.mdc` from `conventions-pointer.mdc` and
    `.github/instructions/coding-<lang>.instructions.md` from
    `conventions-pointer.instructions.md`, both rendered with a local helper
    substituting `{lang}` (language id) and `{globs}` (comma-separated file
    globs per language, e.g. `**/*.py` for python; a module-level
    `LANG_GLOBS` map). Package-owned: same create/refresh semantics as base.
  - No detected language → `report.notes.append("no language manifests
    detected — conventions skipped; re-run kb init after adding code")`.
- `ensure_claude_block(target: Path, report: InitReport) -> None` — marker
  `<!-- kb:conventions -->`:
  - `CLAUDE.md` missing → create it containing only the block (`created`).
  - present without marker → append the block, preserving existing content
    byte-for-byte (`updated: "CLAUDE.md (conventions block appended)"`).
  - marker present → do nothing.
  - The block is **generic** — it points at `docs/conventions/` as a
    directory convention rather than naming languages, so detecting a new
    language later never requires editing the block:

    ```markdown
    <!-- kb:conventions -->
    **Coding conventions.**
    For each language you touch, read `docs/conventions/<lang>.md`; if
    `docs/conventions/<lang>.local.md` exists it overrides the base file.
    Where either conflicts with the repo's existing dominant style, the
    repo wins locally — record the conflict as a finding in the PR.
    ```

- `init_repo()` (`initcmd.py`) calls `scaffold_conventions` +
  `ensure_claude_block` after the main loop and after `_record_kind`,
  guarded by `kind == KIND_DEV`. Everything stays idempotent: a second
  `kb init` run with unchanged templates reports no `created`/`updated`
  conventions rows.

### §2 Content — the nine template resources

**Base `conventions-<lang>.md`** (six files, English, ~150–250 lines each).
Identical section skeleton; content covers what the linter cannot enforce:

1. **Naming** — the language's idiom (PEP 8 for python, Effective Go, PSR-12,
   .NET naming guidelines, Google Java Style, TS/ESLint community norms).
2. **Module structure** — file/package organisation, size discipline,
   cohesion; organise by feature, not by type.
3. **Error handling** — the idiomatic mechanism (exceptions / `error`
   returns / `Result`-style), never silently swallow, fail fast at
   boundaries.
4. **Logging** — structured logging via the standard facility; no
   `print` / `console.log` in committed code.
5. **Citation comments** — the standard-derived-value format the dev skills
   already require (`# per <DOC-ID> §<section> @ <rev>`), stated once as the
   normative reference.
6. **Testing** — AAA structure, behaviour-describing names, what must carry a
   test.
7. **Linting (preset)** — verbatim config content plus the commands, so a
   plan task can materialise it without reading package internals:
   - python — ruff (`ruff.toml`: lint + format), command `ruff check . &&
     ruff format --check .`
   - ts — eslint + prettier configs, command `npx eslint . && npx prettier
     --check .`
   - java — spotless (format) + checkstyle (lint) snippets for both Maven
     and Gradle
   - go — gofmt + golangci-lint (`.golangci.yml`)
   - php — php-cs-fixer (`.php-cs-fixer.dist.php`)
   - dotnet — `dotnet format` + analyzers configured through `.editorconfig`
   - each file also carries the standard `.editorconfig` block (duplicated
     across the six files by design — small, and keeps every base file
     self-contained).

**`conventions-local-stub.md`** — a few lines: this file belongs to the repo;
re-init never touches it; entries here override the base file; record local
deviations here.

**`conventions-pointer.mdc`** — Cursor rule with frontmatter
(`globs: {globs}`, `alwaysApply: false`) and a 2–3 line body: read
`docs/conventions/{lang}.md`, then `docs/conventions/{lang}.local.md` if
present; local wins.

**`conventions-pointer.instructions.md`** — Copilot instructions with
`applyTo: "{globs}"` frontmatter and the same body.

### §3 Skill text — D1 + D4 (2 skills × 4 wrappers + canon)

- **`dev-plan`** — extend the existing "No `-code` document yet" bullet: when
  the repo has no linter (nothing to record as `cmd.lint`), the plan's
  **first task** is to set one up from the *Linting* section of
  `docs/conventions/<lang>.md`, and the command it establishes is recorded as
  `cmd.lint` for the closing task, `dev-execute`, and `dev-handover`. One
  sentence; the plan format itself is unchanged.
- **`dev-execute`** — the checkpoint item "does the change follow the repo's
  existing conventions" becomes: does the change follow
  `docs/conventions/<lang>.md` plus `<lang>.local.md` overrides; where they
  conflict with the repo's existing dominant style, **the repo wins
  locally** — record the conflict as a finding so it reaches the PR body.
- Both changes land in all four wrappers (claude-skill, claude-command,
  copilot, cursor) with the canon pins in `tests/test_templates.py` bumped in
  the same commit.

### §4 Tests and trip-wires (D5)

TDD per unit; the trip-wire bumps are deliberate and named in commit
messages.

- **`tests/test_conventions.py`** (new):
  - detection: one case per language manifest, a manifest at depth 2, a
    manifest at depth 3 (not detected), a multi-language repo (sorted
    result), an empty repo (empty result), ignored directories
    (`node_modules` containing `package.json` does not make the repo `ts`).
  - scaffold: base created; base rewritten when template content changes;
    base left alone when identical; local stub created once then never
    rewritten (even with `--force`); pointer files rendered with the right
    `{lang}`/`{globs}` values.
  - CLAUDE.md: created when missing; appended when marker absent (existing
    user bytes preserved exactly); untouched when marker present; running
    init twice appends the block once.
  - report rows: created/updated/skipped/notes as specified in §1.
- **`tests/test_init.py`** — `expected_files()` is unchanged for all four
  kinds (static map untouched); add an integration case: `kb init --kind
  dev` on a fixture with `pyproject.toml` produces the python conventions
  set; any pinned-count change is a deliberate bump with the reason in the
  commit message.
- **`tests/test_templates.py`** — canon pins for `dev-plan` and
  `dev-execute` bumped for the D1/D4 wording, in both places the canon is
  pinned, as in every template round.
- **Golden gate** — `git diff main...HEAD -- tests-gate/golden
  src/center_kb/mcp.py` must be empty at review time.

## Error handling

- Detection walks defensively: unreadable directories are skipped, never
  raised — a permission error on some subtree must not fail `kb init`.
- `CLAUDE.md` with unusual encodings: read as UTF-8 like every other file the
  package touches; a decode error surfaces as a normal error message naming
  the file (fail fast, no silent skip).
- A `docs/conventions/` path blocked by a same-named file (a file named
  `docs/conventions`) fails with the OS error naming the path — same
  behaviour as the main loop's `mkdir(parents=True)`.

## Sequencing

1. Engine (`conventions.py` + `initcmd.py` wiring) with its tests.
2. The nine template resources (content round).
3. Skill-text round (D1 + D4, 8 wrapper files + canon bumps).
4. Integration pass over `test_init.py`, golden-gate verification.
