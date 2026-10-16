# Code-ingest Structural Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb code-ingest` emits routes, pages, jobs, exported symbols, a complete file list, schema partition/index/PK facts and a coverage statement, for every supported stack. The BA-side SA and `kb ticket check` then answer structural questions without asking the Dev.

**Architecture:** One shared tree-sitter layer (`_ts.py`), one scope finder (`_scopes.py`) and one coverage type (`_coverage.py`) are used by four new extractors (`routes`, `pages`, `jobs`, `symbols`). Each extractor has one adapter module per language family. `core.run()` gathers coverage rows from every extractor and renders `struct.coverage`. `tree.py` gains `struct.files.*`. `schema.py` gains partition/index/PK rows. `ticketcheck.py` verifies the new citations and enforces coverage on `[NEW]`.

**Tech Stack:** Python ≥3.11, `tree-sitter` + `tree-sitter-language-pack==0.13.0` (optional extra `code`), pytest, ruff, pyright.

**Spec:** `docs/superpowers/specs/2026-10-15-code-ingest-structural-coverage-design.md`

## Global Constraints

- Extra: `code = ["tree-sitter>=0.25.2,<0.27", "tree-sitter-language-pack==0.13.0"]`. **Never `>=1.0`**: 1.x downloads grammars from the network at runtime into `~/.cache`. 0.13.0 bundles every grammar in the wheel (verified offline: typescript, tsx, javascript, python, java, kotlin, csharp, go, rust, php, swift, dart, css, scss). It installs about 184 MB.
- Output is a pure function of the working tree: no network, no clock, sorted output, same bytes on every machine (`core.py` contract).
- Degrade, never crash: an unparseable file adds a warning plus a `partial` coverage row naming `file:line`.
- Names only, never values. The only literal strings emitted are route paths, page paths, middleware matcher patterns, cron/interval expressions and CSS custom-property names. Env values, constant values and enum member values are never emitted.
- Never truncate a list that can back `complete`. Section split levels are fixed (by file, scope or top-level directory), never by size.
- Existing ids (`svc.*`, `db.*`, `api.*`, `int.*`, `cmd.*`, `dep.*`, `struct.tree`) keep their shape. Tickets grounded before this release still pass.
- `jobs` coverage is **always** `partial`, with detail `jobs outside framework schedulers are not detectable`. `[NEW: …]` on a `Jobs:` line is always an error.
- Without the extra, every new extractor emits `not scanned — install strata-kb[code]` rows and one warning, and no sections.
- Existing extractors' tests must keep passing unchanged, except where a task explicitly changes an expectation.

## Review Focus

1. **A monorepo with two apps that both have `admin.controller.ts`.** Expect two distinct `route.*` ids, each stable across runs and when the other app is deleted. Pinned in Task 2 (`test_slugs_stable_when_sibling_removed`) and Task 6 (`test_two_apps_same_controller_name_distinct_ids`).
2. **A route path built from a variable or template literal (`@Get(\`${BASE}/x\`)`, `router.get(PATH, …)`).** Expect that route not listed, its scope `partial`, and the site named `file:line`. Pinned in Task 6 (`test_dynamic_path_marks_scope_partial`).
3. **A repo with no `[code]` extra installed (a Dev's laptop).** Expect `kb code-ingest` to still succeed, `struct.coverage` with `not scanned — install strata-kb[code]` rows, and the gate rejecting `[NEW]` in those areas. Pinned in Task 3 (`test_without_extra_rows_are_not_scanned`) and Task 11 (`test_new_rejected_when_scope_not_scanned`).
4. **A ticket grounded before this release, with `[NEW]` on a file beyond depth 4 that already existed.** Expect it to still PASS, with a note at most. Pinned in Task 11 (`test_new_on_existing_thing_is_note_when_listed_only_after_grounded_rev`).
5. **Generated or vendored code (`dist/`, `node_modules/`, `*.generated.ts`, `__generated__/`, `migrations/` for symbols) and test files.** Expect them never listed as symbols or routes. Pinned in Task 9 (`test_generated_and_test_files_skipped`).

---

## File Structure

New, under `src/strata_kb/codeingest/extractors/`:
- `_ts.py` — tree-sitter availability, language by extension, parse, query, string-literal helper.
- `_scopes.py` — package scopes (manifest dirs) with their detected frameworks; longest-prefix lookup.
- `_coverage.py` — `CoverageRow`, row merge/sort, `struct.coverage` rendering.
- `_slugs.py` — stable unique slug assignment (moved out of `services.py`).
- `routes.py` + `_routes_js.py`, `_routes_jvm.py`, `_routes_dotnet.py`, `_routes_py.py`, `_routes_php.py`, `_routes_go.py`, `_routes_rust.py`, `_routes_swift.py`.
- `pages.py` (all page frameworks; they are all JS/TS or Dart).
- `jobs.py` + `_jobs_adapters.py` (all languages: each pattern is one query).
- `symbols.py` + `_symbols_lang.py` (one exported-name rule per language) + CSS.

Modified: `types.py`, `extractors/__init__.py`, `core.py`, `tree.py`, `schema.py`, `services.py`, `deps.py`, `ticketcheck.py`, `ticketstale.py`, `codesync/facts.py`, `mcp.py`, `cli.py` (ticket check wiring), `doctor/checks/dev.py`, `templates/init/bodies/sa-ticket-ground.md`, `templates/init/ticket-template.md`, `templates/init/kb-code.yml`, `templates/init/QUICKSTART-dev.md`, `templates/init/QUICKSTART-ba.md`, `pyproject.toml`, `uv.lock`, `CHANGELOG.md`, `README.md`, `docs/src/guide-{dev,ba}.{en,vi}.md`.

Tests: `tests/test_codeingest_ts.py`, `tests/test_codeingest_scopes.py`, `tests/test_codeingest_coverage.py`, `tests/test_codeingest_routes_*.py`, `tests/test_codeingest_pages.py`, `tests/test_codeingest_jobs.py`, `tests/test_codeingest_symbols.py`, `tests/test_codeingest_myflix_fixture.py`, plus additions to `tests/test_codeingest_extractors.py`, `tests/test_ticketcheck.py`, `tests/test_codesync_facts.py`, `tests/test_doctor_checks.py`.

Test helpers named in the steps (`write`, `git_init_add`, `run_routes`, `section`, `table_rows`, `coverage`, …) are small local functions in each test file: write files, `git init` + `git add`, run one extractor, find a section, split an L2 pipe table into rows (`lintcore.table_rows`), and read a `struct.coverage` status. Tests that need tree-sitter use `pytest.importorskip("tree_sitter_language_pack")`. CI's `dev` extra gains `tree-sitter-language-pack==0.13.0` so they run there.

---

### Task 1: `code` extra and the tree-sitter layer

**Files:**
- Modify: `pyproject.toml` (new extra `code`; add the same two pins to `dev`), `uv.lock` (`uv lock`)
- Create: `src/strata_kb/codeingest/extractors/_ts.py`
- Test: `tests/test_codeingest_ts.py`

**Interfaces:**
- Produces:
  - `available() -> bool`: True iff `tree_sitter_language_pack` imports.
  - `LANG_BY_SUFFIX: dict[str, str]`: `.ts→typescript`, `.tsx→tsx`, `.js/.mjs/.cjs/.jsx→javascript`, `.py→python`, `.java→java`, `.kt/.kts→kotlin`, `.cs→csharp`, `.go→go`, `.rs→rust`, `.php→php`, `.swift→swift`, `.dart→dart`, `.css→css`, `.scss→scss`.
  - `language_for(rel_path: str) -> str | None`
  - `parse(lang: str, source: bytes) -> tree_sitter.Tree` (parsers cached per lang)
  - `matches(lang: str, query: str, node: tree_sitter.Node) -> list[dict[str, list[tree_sitter.Node]]]` (queries compiled once per `(lang, query)`)
  - `node_text(node) -> str` (utf-8, `errors="replace"`)
  - `string_literal(node) -> str | None`: the content of a plain string literal in any supported language. None for a template literal with substitutions, a concatenation, an identifier, an f-string with fields, or interpolation.
  - `line_of(node) -> int` (1-based)

- [ ] **Step 1: Write the failing tests**

```python
ts = pytest.importorskip("tree_sitter_language_pack")
from strata_kb.codeingest.extractors import _ts

def test_language_for_maps_suffixes():
    assert _ts.language_for("apps/api/src/a.controller.ts") == "typescript"
    assert _ts.language_for("x/page.tsx") == "tsx"
    assert _ts.language_for("README.md") is None

def test_string_literal_plain_vs_dynamic():
    t = _ts.parse("typescript", b'f("a/b"); f(`x${y}`); f("a" + b); f(`plain`)')
    calls = [m["arg"][0] for m in _ts.matches("typescript",
        "(call_expression arguments: (arguments . (_) @arg))", t.root_node)]
    assert [_ts.string_literal(n) for n in calls] == ["a/b", None, None, "plain"]

def test_string_literal_python_fstring_is_dynamic():
    t = _ts.parse("python", b'f("a")\nf(f"{x}/b")\n')
    args = [m["a"][0] for m in _ts.matches("python", "(call arguments: (argument_list . (_) @a))", t.root_node)]
    assert [_ts.string_literal(n) for n in args] == ["a", None]

def test_available_false_when_pack_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "tree_sitter_language_pack", None)
    assert _ts.available() is False
```

Plus one `string_literal` case each for java, kotlin, csharp, go (interpreted and raw string), rust, php (single- and double-quoted, `"$x"` dynamic), swift (`"\(x)"` dynamic) and dart (`'$x'` dynamic).

- [ ] **Step 2: Run to verify fail**

Run: `uv run --extra dev pytest tests/test_codeingest_ts.py -q`
Expected: FAIL, `ModuleNotFoundError: strata_kb.codeingest.extractors._ts`

- [ ] **Step 3: Add the extra, run `uv lock`, implement `_ts.py`**

Import `tree_sitter_language_pack` lazily inside `available()` and `parse()`, so importing `_ts` never fails without the extra.

- [ ] **Step 4: Run to verify pass**

Run: `uv run --extra dev pytest tests/test_codeingest_ts.py -q`
Expected: PASS

- [ ] **Step 5: Commit** — `feat(codeingest): tree-sitter layer behind the code extra`

---

### Task 2: Stable slugs and scopes

**Files:**
- Create: `src/strata_kb/codeingest/extractors/_slugs.py`, `src/strata_kb/codeingest/extractors/_scopes.py`
- Modify: `src/strata_kb/codeingest/extractors/services.py:865` (call `_slugs.assign_slugs`), `src/strata_kb/codeingest/extractors/deps.py` (per-file dependency-name function)
- Test: `tests/test_codeingest_scopes.py`

**Interfaces:**
- Produces:
  - `_slugs.assign_slugs(names: list[str]) -> list[str]`: the algorithm moved verbatim from `services._assign_slugs`. It is parallel to `names`, and a suffix depends only on the name's own length. `services._assign_slugs` becomes a thin call; every existing services test passes unchanged.
  - `deps.manifest_dep_names(path: Path) -> list[str]`: dependency names of ONE manifest (`package.json`, `pyproject.toml`, `requirements*.txt`, `pom.xml`, `build.gradle(.kts)`, `*.csproj`, `go.mod`, `composer.json`, `Cargo.toml`, `Package.swift`, `pubspec.yaml`). Extract it from the existing `_read_<eco>` per-file bodies, so the readers call it. `deps` output is unchanged.
  - `@dataclass(frozen=True) class Scope: path: str; manifest: str; frameworks: tuple[str, ...]`. `path` is a repo-relative posix dir, or `"."`.
  - `find_scopes(root: Path, kb_dir: Path) -> list[Scope]`: one per directory holding a manifest above, from `tree.tracked_files` (fall back to `walk_tree`) with `IGNORED_DIRS` pruned. Sorted by path. `frameworks = tuple(deps.detect_frameworks(manifest_dep_names(...)))`. Several manifests in one dir merge.
  - `scope_of(scopes: list[Scope], rel_path: str) -> Scope | None`: longest path prefix.

- [ ] **Step 1: Write the failing tests**

```python
def test_find_scopes_monorepo(tmp_path):
    write(tmp_path, "package.json", '{"workspaces":["apps/*"]}')
    write(tmp_path, "apps/api/package.json", '{"dependencies":{"@nestjs/core":"^10"}}')
    write(tmp_path, "apps/web/package.json", '{"dependencies":{"next":"14","react":"18"}}')
    git_init_add(tmp_path)
    scopes = _scopes.find_scopes(tmp_path, tmp_path / ".kb")
    assert [(s.path, s.frameworks) for s in scopes] == [
        (".", ()), ("apps/api", ("NestJS",)), ("apps/web", ("Next.js", "React"))]
    assert _scopes.scope_of(scopes, "apps/api/src/a.ts").path == "apps/api"
    assert _scopes.scope_of(scopes, "tools/x.ts").path == "."

def test_slugs_stable_when_sibling_removed():
    a = _slugs.assign_slugs(["apps/api/src/admin/admin.controller", "apps/admin/src/admin/admin.controller"])
    b = _slugs.assign_slugs(["apps/api/src/admin/admin.controller"])
    assert a[0] == b[0] and len(set(a)) == 2
```

- [ ] **Step 2: Run to verify fail** — `uv run --extra dev pytest tests/test_codeingest_scopes.py -q` → FAIL (module missing)
- [ ] **Step 3: Implement**, moving the slug code and the per-file dependency parse
- [ ] **Step 4: Run** `uv run --extra dev pytest tests/test_codeingest_scopes.py tests/test_codeingest_extractors.py -q` → PASS (services and deps tests unchanged)
- [ ] **Step 5: Commit** — `refactor(codeingest): shared slugs, per-manifest deps, package scopes`

---

### Task 3: Coverage rows and `struct.coverage`

**Files:**
- Create: `src/strata_kb/codeingest/extractors/_coverage.py`
- Modify: `src/strata_kb/codeingest/types.py` (`ExtractResult.coverage`), `src/strata_kb/codeingest/core.py` (collect, render, `_GENERATED_PREFIXES`, zero-detection exclusion)
- Test: `tests/test_codeingest_coverage.py`

**Interfaces:**
- Produces:
  - `types.ExtractResult.coverage: list[CoverageRow] = field(default_factory=list)`
  - `@dataclass(frozen=True) class CoverageRow: area: str; scope: str; framework: str; status: str; detail: str = ""`. `area ∈ {"routes","pages","jobs","symbols","files","schema"}`, `status ∈ {"complete","partial","not scanned"}`.
  - `merge_rows(rows: list[CoverageRow]) -> list[CoverageRow]`: one row per `(area, scope, framework)`. The worst status wins (`not scanned` > `partial` > `complete`). Details are joined, sorted and de-duplicated; when there are over 20 sites, show 20 plus `+N more`.
  - `render_section(rows) -> CodeSection`: id `struct.coverage`, group `structure`, title `Coverage`. L2 table `Area | Scope | Framework/language | Status | Detail`. L3 holds the same table with untruncated detail.
  - `NOT_INSTALLED = "not scanned — install strata-kb[code]"`
  - `JOBS_DETAIL = "jobs outside framework schedulers are not detectable"`
  - `core.run()`: after all extractors, if any row exists, appends `render_section(merge_rows(all_rows))`. `_GENERATED_PREFIXES` gains `"route."`, `"page."`, `"job."`, `"sym."` (`struct.` is already present). The zero-detection rule ignores `routes`, `pages`, `jobs` and `symbols` the way it ignores `tree`.

- [ ] **Step 1: Write the failing tests**

```python
def test_merge_worst_status_wins():
    rows = [CoverageRow("routes","apps/api","NestJS","complete"),
            CoverageRow("routes","apps/api","NestJS","partial","apps/api/src/x.ts:12")]
    assert merge_rows(rows) == [CoverageRow("routes","apps/api","NestJS","partial","apps/api/src/x.ts:12")]

def test_render_is_deterministic_and_sorted(): ...  # two calls, shuffled input → identical l2/l3

def test_core_emits_struct_coverage_from_extractor_rows(tmp_path, monkeypatch):
    # fake extractor in ALL_EXTRACTORS returning one row → .kb/<id>-code/structure.md has "## struct.coverage"
```

- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_codeingest_coverage.py -q` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** `uv run --extra dev pytest tests/test_codeingest_coverage.py tests/test_codeingest_core.py -q` → PASS
- [ ] **Step 5: Commit** — `feat(codeingest): coverage rows and struct.coverage`

---

### Task 4: Complete file list — `struct.files.<dir>`

**Files:**
- Modify: `src/strata_kb/codeingest/extractors/tree.py` (`TreeExtractor.extract`), `src/strata_kb/ticketcheck.py:1069` (`_check_files`)
- Test: `tests/test_codeingest_extractors.py`, `tests/test_ticketcheck.py`

**Interfaces:**
- Produces:
  - Sections `struct.files.<slug>`, one per top-level tracked directory. The slug is `assign_slugs([dir])`. Root-level files go in `struct.files.root`. Group `structure`, title `Files: <dir>/`.
  - L2: `<n> files` plus the immediate sub-directories.
  - L3: one fenced block listing every tracked file path (repo-relative, full path per line, sorted, no cap).
  - Coverage row `CoverageRow("files", <dir>, "-", "complete")` per section. It is `partial` with detail `not a git repository — os.walk listing` when not a git repo.
  - `ticketcheck._files_union(doc) -> set[str]`: the `struct.tree` paths ∪ every `struct.files.*` L3 line ∪ every directory prefix of those. `_check_files` uses it. The depth-cap warning fires only when no `struct.files.*` section exists.

- [ ] **Step 1: Failing tests**
  - `test_struct_files_lists_deep_paths_uncapped`: a fixture with `apps/web/src/app/(admin)/admin/page.tsx` → the L3 of `struct.files.apps` contains that exact line.
  - `test_struct_files_ids_fixed_per_top_dir`: add 700 files under `apps/`; the ids are still exactly `{"struct.files.apps", "struct.files.root"}`.
  - `test_files_check_accepts_path_beyond_depth_4_when_listed` and `test_files_check_unknown_deep_path_is_error_when_struct_files_present` (ticketcheck).
- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_codeingest_extractors.py -k struct_files tests/test_ticketcheck.py -k files -q` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the same** → PASS. Then `uv run --extra dev pytest tests/test_codeingest_self_ingest.py -q` → PASS (update its expected id set if it pins one).
- [ ] **Step 5: Commit** — `feat(codeingest): struct.files sections list every tracked file`

---

### Task 5: Schema — partition, primary key, indexes, Prisma table name

**Files:**
- Modify: `src/strata_kb/codeingest/extractors/schema.py` (`TableRecord`, `MIGRATION_GLOBS`, `_apply_sql_file`, `_apply_prisma_file`, `_apply_alembic_file`, `_apply_ef_file`, `_read_sqlite`, `_merge_tables`, `_render_section`)
- Test: `tests/test_codeingest_extractors.py`

**Interfaces:**
- Produces:
  - `TableRecord` gains `table_name: str = ""` (the physical name: Prisma `@@map` or the model name; the other readers use `name`), `partition: str = ""` (e.g. `RANGE (created_at)`), `indexes: list[tuple[str, str, bool]]` (name, comma-joined columns, unique), `partitions: list[str]` (child tables from `PARTITION OF`), `schema_partial: list[str]` (statements the reader skipped).
  - L2 adds rows after the column table: `Table: <table_name>`, `Primary key: <cols or none>`, `Partition: <expr or none>` (plus `Partitions: a, b` when any), `Indexes:` with one `- <name> (<cols>)[ unique]` per index or `none`. Where two sources disagree on one row, both are shown as `<value> [<source>]`.
  - `MIGRATION_GLOBS` gains `**/prisma/migrations/*/migration.sql`.
  - Merge: a SQL record whose name equals a Prisma record's `table_name` merges `partition`, `partitions`, `indexes` and `pk` (if Prisma has none) into the Prisma record. The SQL record is not emitted. Columns keep the first-reader rule.
  - Coverage: per scope that has any table, `CoverageRow("schema", scope, reader, status)`, where status is `partial` with `schema_partial` sites when any, else `complete`. Emitted even without the `code` extra (schema does not use tree-sitter).
  - The SQL reader recognises `CREATE [UNIQUE] INDEX [IF NOT EXISTS] <name> ON <table> [USING x] (<cols>)`, `ALTER TABLE <t> ADD CONSTRAINT <n> PRIMARY KEY|UNIQUE (<cols>)` and `) PARTITION BY <RANGE|LIST|HASH> (<expr>)`. Today the `ADD CONSTRAINT/INDEX` warning branch at `schema.py:767` skips these; it now records them, and still never adds a column.
  - Prisma: `@id`, `@@id([a, b])`, `@unique`, `@@unique`, `@@index([a, b], name: "x")`, `@@map("t")`. Alembic: `op.create_index(name, table, [cols], unique=)`, `op.create_primary_key`. EF: `HasKey`, `HasIndex(...).IsUnique()`, `[Index(...)]`, `[Key]`. SQLite: `PRAGMA index_list` / `index_info`.

- [ ] **Step 1: Failing tests** (one per reader plus the merge), e.g.

```python
def test_prisma_and_sql_migration_merge_partition_and_index(tmp_path):
    write(tmp_path, "prisma/schema.prisma", '''model PlaybackEvent {
  id BigInt @default(autoincrement())
  createdAt DateTime @map("created_at")
  @@id([id, createdAt])
  @@index([createdAt])
  @@map("playback_events")
}''')
    write(tmp_path, "prisma/migrations/20260101_init/migration.sql",
          'CREATE TABLE "playback_events" ("id" BIGINT, "created_at" TIMESTAMPTZ, PRIMARY KEY ("id","created_at")) PARTITION BY RANGE ("created_at");')
    sec = only_section(run_schema(tmp_path), "db.PlaybackEvent")
    assert "Table: playback_events" in sec.l2_md
    assert "Partition: RANGE (\"created_at\")" in sec.l2_md
    assert "PlaybackEvent_createdAt_idx (createdAt)" in sec.l2_md
    assert not any(s.id == "db.playback_events" for s in run_schema(tmp_path).sections)
```

  Also: `test_sql_create_index_recorded_not_a_column`, `test_alter_rename_marks_schema_partial`, `test_alembic_create_index`, `test_ef_has_index_unique`, `test_sqlite_pragma_indexes`.
- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_codeingest_extractors.py -k "schema or prisma or sql or alembic or ef or sqlite" -q` → the new tests FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the same** → all PASS (existing schema tests unchanged, except the `ADD CONSTRAINT/INDEX skipped` warning assertions, which now expect the recorded index)
- [ ] **Step 5: Commit** — `feat(codeingest): schema partition, primary key and index facts`

---

### Task 6: Routes extractor — core plus JS/TS adapters

**Files:**
- Create: `src/strata_kb/codeingest/extractors/routes.py`, `src/strata_kb/codeingest/extractors/_routes_js.py`
- Modify: `src/strata_kb/codeingest/extractors/__init__.py` (register after `api`)
- Test: `tests/test_codeingest_routes_js.py`

**Interfaces:**
- Consumes: `_ts.*`, `_scopes.find_scopes/scope_of`, `_slugs.assign_slugs`, `CoverageRow`, `NOT_INSTALLED`.
- Produces:
  - `@dataclass(frozen=True) class Route: method: str; path: str; handler: str; file: str; line: int; request_type: str = ""`. `method` is upper-case or `ANY`. `path` is the full joined path, starting with `/`.
  - `@dataclass class AdapterResult: routes: list[Route]; dynamic_sites: list[str]` (`"file:line"` entries).
  - Adapter protocol: `ADAPTERS: dict[str, Callable[[Path, Scope, list[str]], AdapterResult]]`, keyed by framework label. It receives the repo root, the scope and that scope's tracked source files. Each `_routes_<lang>.py` exports `ADAPTERS` and `routes.py` merges them.
  - `RoutesExtractor(name="routes")`. A section per module file `route.<assign_slugs(path-without-suffix)>`, group `routes`, title = file path. L2 table `Method | Path | Handler | File | Request type`, sorted by (path, method). L3: the request type's declared fields (`name | type | required`) when declared in the same repo, else `request type declared outside the repo`.
  - Coverage per (scope, framework with an adapter): `complete`, or `partial` with `dynamic_sites`. A framework in `ROUTE_FRAMEWORKS` without an adapter gives `not scanned` with detail `no adapter for <fw> yet`. `ROUTE_FRAMEWORKS` holds the 18 labels in spec §5.2.
- JS/TS adapters (`NestJS`, `Express`, `Next.js`, `Nuxt`):
  - NestJS: class `@Controller(p)` + method `@Get/Post/Put/Patch/Delete/Options/Head/All(p?)`. `All` maps to `ANY`. The prefix is `app.setGlobalPrefix('x')` in any file of the scope. A `@Body() dto: T` parameter sets `request_type=T`. `T` fields come from `class T { a!: string; b?: number }` (required = no `?`). `@Controller({ path: 'x' })` is supported.
  - Express: `<id>.get|post|put|patch|delete|all(path, …)` on identifiers bound to `express()` or `express.Router()`/`Router()` in the same file. A mount `app.use('/p', routerIdent)` with the router imported from a relative file joins the prefix. A mount that cannot be followed is a dynamic site.
  - Next.js: `app/**/route.(ts|js)` exporting `GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS`. Path from the dirs, with route groups `(x)` removed and `[id]` kept. `pages/api/**` gives `ANY`.
  - Nuxt: `server/api/**` → `/api/...`, `server/routes/**` → `/...`. Method from the `.get.ts`/`.post.ts` suffix, else `ANY`.
  - Any recognised call whose path argument has `string_literal(...) is None` is a dynamic site.
  - Suspicious-sign rule (spec §5.8), shared by every adapter in `routes.py`: a call or decorator whose callee name is one of the adapter's HTTP-method names (`Get`, `get`, `GetMapping`, `HttpGet`, `GET`, …) that did not become a `Route` is a dynamic site. Adapters return those sites; `routes.py` never drops one silently.

- [ ] **Step 1: Failing tests**

```python
pytest.importorskip("tree_sitter_language_pack")

def test_nest_controller_joins_global_and_class_prefix(tmp_path):
    nest_app(tmp_path, "apps/api", main='app.setGlobalPrefix("api")',
             files={"src/admin/admin.controller.ts": '''
@Controller("admin") export class AdminController {
  @Get("stats") stats() {}
  @Post("users") create(@Body() dto: CreateUserDto) {}
}
export class CreateUserDto { name!: string; note?: string }'''})
    sec = section(run_routes(tmp_path), "apps/api/src/admin/admin.controller.ts")
    assert table_rows(sec.l2_md) == [
        ["GET", "/api/admin/stats", "AdminController.stats", "apps/api/src/admin/admin.controller.ts", ""],
        ["POST", "/api/admin/users", "AdminController.create", "apps/api/src/admin/admin.controller.ts", "CreateUserDto"]]
    assert "| name | string | yes |" in sec.l3_md and "| note | string | no |" in sec.l3_md
    assert coverage(run_routes(tmp_path), "routes", "apps/api") == "complete"

def test_dynamic_path_marks_scope_partial(tmp_path): ...  # @Get(`${BASE}/x`) → partial, detail "apps/api/src/x.controller.ts:3"
def test_two_apps_same_controller_name_distinct_ids(tmp_path): ...
def test_express_router_mount_prefix(tmp_path): ...       # app.use("/v1", require("./users")) + router.get("/:id") → GET /v1/:id
def test_next_route_handlers_and_groups(tmp_path): ...    # app/(admin)/api/stats/route.ts export GET → GET /api/stats
def test_nuxt_server_routes(tmp_path): ...
def test_framework_without_adapter_is_not_scanned(tmp_path): ...  # pom.xml with spring-boot before Task 14 → not scanned
def test_without_extra_rows_are_not_scanned(tmp_path, monkeypatch): ...  # _ts.available False → no route.* sections, row status NOT_INSTALLED
```

- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_codeingest_routes_js.py -q` → FAIL
- [ ] **Step 3: Implement** `routes.py` (scan, merge adapters, render, coverage) and `_routes_js.py`
- [ ] **Step 4: Run** `uv run --extra dev pytest tests/test_codeingest_routes_js.py tests/test_codeingest_core.py tests/test_codeingest_self_ingest.py -q` → PASS
- [ ] **Step 5: Commit** — `feat(codeingest): route.* from code for NestJS, Express, Next.js, Nuxt`

---

### Task 7: Pages extractor

**Files:**
- Create: `src/strata_kb/codeingest/extractors/pages.py`
- Modify: `extractors/__init__.py`
- Test: `tests/test_codeingest_pages.py`

**Interfaces:**
- Produces: `PagesExtractor(name="pages")`. Section `page.<assign_slugs(scope.path or repo_id)>` per scope whose frameworks include a page framework. Group `pages`, title `Pages: <scope>`. L2 table `Path | File | Layout/group`, sorted by path, with a `Middleware matcher:` row listing the Next.js `config.matcher` literals (a non-literal matcher is a dynamic site). Coverage `pages` per (scope, framework).
- Sources (spec §5.3):
  - Next.js: `app/**/page.(tsx|ts|jsx|js)` (Path drops `(group)` segments; Layout/group shows them, e.g. `(admin)`), and `pages/**` excluding `_app`, `_document` and `api/`.
  - Nuxt: `pages/**/*.vue`.
  - SvelteKit (framework `Svelte`): `src/routes/**/+page.svelte`.
  - Angular: object literals with a `path:` string inside an array typed `Routes` or passed to `RouterModule.forRoot/forChild` or `provideRouter`.
  - Vue: arrays passed to `createRouter({ routes })`.
  - React: `<Route path="…">` JSX and objects in `createBrowserRouter([...])`; nested `children` join paths.
  - Flutter: `GoRoute(path: '…')` (nested `routes:` join) and `MaterialApp(routes: {'/x': …})` (Dart via tree-sitter).

- [ ] **Step 1: Failing tests**: `test_next_app_router_groups_and_dynamic_segments` (`(admin)/admin/page.tsx` → Path `/admin`, group `(admin)`; `(viewer)/watch/[id]/page.tsx` → `/watch/[id]`), `test_next_middleware_matcher_listed`, `test_nuxt_pages`, `test_sveltekit_pages`, `test_angular_routes_array`, `test_vue_router_routes`, `test_react_router_nested_children`, `test_flutter_go_router_nested`, `test_backend_only_scope_has_no_pages_row`.
- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_codeingest_pages.py -q` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the same** → PASS
- [ ] **Step 5: Commit** — `feat(codeingest): page.* routes for Next.js, Nuxt, SvelteKit, Angular, Vue, React, Flutter`

---

### Task 8: Jobs extractor (all sources)

**Files:**
- Create: `src/strata_kb/codeingest/extractors/jobs.py`
- Modify: `extractors/__init__.py`
- Test: `tests/test_codeingest_jobs.py`

**Interfaces:**
- Produces: `JobsExtractor(name="jobs")`. Section `job.<assign_slugs(path-without-suffix)>` per declaring file or manifest, group `jobs`. L2 table `Name | Schedule | Handler | File`. `Schedule` is the literal expression (`0 3 * * *`, `every 5m`, `interval 60000ms`, `hosted`); a non-literal schedule is `(dynamic)` and its site is listed. **Coverage: one `jobs` row per scope, always `partial`, detail `JOBS_DETAIL` plus any dynamic sites.**
- Sources (spec §5.4): NestJS `@Cron/@Interval/@Timeout`; Spring/Quarkus/Micronaut `@Scheduled(cron=|fixedRate=|every=)`; Hangfire `RecurringJob.AddOrUpdate`; Quartz `WithCronSchedule`; C# classes deriving `BackgroundService` (schedule `hosted`); Celery `beat_schedule` dict entries, `@periodic_task`, `add_periodic_task`; Laravel `$schedule->command|job|call(...)->cron|daily…` and `Schedule::` in `routes/console.php`; Symfony `#[AsCronTask]`, `#[AsPeriodicTask]`; `node-cron` `cron.schedule`; BullMQ `repeat: { pattern | every }`; Go `robfig/cron` `AddFunc/AddJob`; Rust `tokio-cron-scheduler` `Job::new*`; k8s `kind: CronJob` YAML (`metadata.name`, `spec.schedule`; read with PyYAML, no tree-sitter needed). GitHub Actions `on.schedule` is excluded.
- Name: the method or function name, or the decorator `name:` option when present, or the k8s `metadata.name`.

- [ ] **Step 1: Failing tests**: `test_nest_cron_job_listed_and_scope_partial` (asserts `Schedule` `0 3 * * *` and coverage status `partial` with `JOBS_DETAIL`); `test_k8s_cronjob_listed`; and one test per remaining source.
- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_codeingest_jobs.py -q` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the same** → PASS
- [ ] **Step 5: Commit** — `feat(codeingest): job.* from framework schedulers and k8s CronJob`

---

### Task 9: Symbols extractor — JS/TS and CSS

**Files:**
- Create: `src/strata_kb/codeingest/extractors/symbols.py`, `src/strata_kb/codeingest/extractors/_symbols_lang.py`
- Modify: `extractors/__init__.py`
- Test: `tests/test_codeingest_symbols.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Symbol: name: str; kind: str; file: str`. `kind ∈ {function, class, interface, type, const, enum, member, css-var}`.
  - `EXPORTERS: dict[str, Callable[[tree_sitter.Tree, bytes], list[tuple[str, str]]]]`, keyed by `_ts` language id, returning `(name, kind)`. `_symbols_lang.py` holds one exporter per language; this task adds typescript/tsx/javascript, css and scss.
  - `SymbolsExtractor(name="symbols")`. Section `sym.<assign_slugs(scope.path)>` per scope (spec §5.6; repo root `.` → `sym.root`), group `symbols`, title `Symbols: <scope>`. L2 table `Name | Kind | File`, sorted by (file, name), never truncated.
  - Coverage `symbols` per (scope, language): `complete`, or `partial` for files that failed to parse or `export * from` a module outside the repo. A language present in the scope without an exporter gives `not scanned`.
- JS/TS rules: `export function|class|interface|type|const|let|enum`, `export { a, b as c }` (emits the exported name), `export default` (name = the declared name, else file stem), `export * from './x'` (re-exports that file's names, followed once within the repo). Members: each enum member of an exported enum, and each property key of an exported `const X = { … }` object literal (with `as const` too), one level, kind `member`, named `X.KEY`.
- CSS/SCSS: every `--name` declared in any rule, kind `css-var`, de-duplicated per file. SCSS `$vars` are excluded.
- Skipped: `IGNORED_DIRS`; `*.d.ts`, `*.generated.*`, `__generated__/`; tests (`*.test.*`, `*.spec.*`, `__tests__/`, `test/`, `tests/`). The coverage row detail names how many files each skip rule removed.

- [ ] **Step 1: Failing tests**

```python
def test_error_code_object_members_listed(tmp_path):
    write(tmp_path, "packages/shared/package.json", "{}")
    write(tmp_path, "packages/shared/src/error-codes.ts",
          'export const ErrorCodes = { ASSET_NOT_READY: "E1", NOT_FOUND: "E2" } as const;')
    rows = table_rows(section(run_symbols(tmp_path), "sym.packages-shared").l2_md)
    assert ["ErrorCodes.ASSET_NOT_READY", "member", "packages/shared/src/error-codes.ts"] in rows
    assert not any("E1" in c for r in rows for c in r)   # names only, never values

def test_css_custom_properties(tmp_path): ...            # :root { --admin-danger: red } → ["--admin-danger","css-var",...]
def test_export_list_and_default(tmp_path): ...
def test_reexport_star_followed_once(tmp_path): ...
def test_generated_and_test_files_skipped(tmp_path): ...
def test_language_without_exporter_not_scanned(tmp_path): ...  # a .go file before Task 18 → not scanned
```

- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_codeingest_symbols.py -q` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the same** → PASS
- [ ] **Step 5: Commit** — `feat(codeingest): sym.* exported names for JS/TS and CSS custom properties`

---

### Task 10: myflix-shaped acceptance fixture

**Files:**
- Create: `tests/fixtures/codeingest-myflix/` (a minimal tree, spec §7), `tests/test_codeingest_myflix_fixture.py`

**Interfaces:**
- Consumes: the `kb code-ingest` CLI end to end (`core.run`).

- [ ] **Step 1: Write the fixture and the test.** The test copies the fixture into `tmp_path`, runs `git init` and `git add`, runs `core.run`, then asserts one cited row per question:

| Question (spec §1) | Assertion |
|---|---|
| `GET /admin/stats` declared? | `route.*` for `apps/api/src/admin/admin.controller.ts` has `GET /api/admin/stats` |
| `POST /playback/session` + DTO fields | row present; L3 lists the DTO fields with required flags |
| `playback_events` partition + PK | `db.PlaybackEvent` has `Partition: RANGE ("created_at")` and `Primary key: id, created_at` |
| index on `createdAt` | `Indexes:` row present |
| `/admin` page file | `page.apps-web` has Path `/admin`, group `(admin)` |
| `(viewer)/watch` route | Path `/watch/[id]` present |
| partition job exists | `job.*` lists it from `maintenance.service.ts` |
| public decorator | `sym.apps-api` has `Public`, `function` |
| `ASSET_NOT_READY` | `sym.packages-shared` has `ErrorCodes.ASSET_NOT_READY` |
| `--admin-danger` token | `sym.apps-web` has `--admin-danger`, `css-var` |
| coverage | routes/pages/symbols/files rows for those scopes are `complete`; `jobs` is `partial` |
| dynamic route | `apps/api/src/legacy.controller.ts` with `` @Get(`${V}/x`) `` → routes `apps/api` is `partial`, site named |

  Because of that last row, the "routes complete" assertion targets a second scope (`apps/media`) that has no dynamic route.
- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_codeingest_myflix_fixture.py -q` → PASS (Tasks 1–9 done). Any FAIL is a bug in the owning task: fix it there.
- [ ] **Step 3: Commit** — `test(codeingest): myflix-shaped acceptance fixture`

---

### Task 11: `kb ticket check` — new citations, coverage gate, `[NEW]` on existing things

**Files:**
- Modify: `src/strata_kb/ticketcheck.py`, `src/strata_kb/mcp.py:355` (`kb_ticket_check`), `src/strata_kb/cli.py` (`kb ticket check`)
- Test: `tests/test_ticketcheck.py`, `tests/test_cli_ticket_check.py`

**Interfaces:**
- Consumes: section shapes from Tasks 3–9; `ticketstale.drift_refs`.
- Produces:
  - `ID_RE` prefixes add `route|page|job|sym`.
  - `normalise_path(p: str) -> str`: `:id`, `{id}`, `{id:int}`, `<int:id>`, `<id>`, `[id]`, `[...slug]` → `{}`; strip a trailing `/` except at the root. Used by both `api.*` and `route.*` route matching.
  - `_check_tables_routes_commands`: `route.<slug>` with `METHOD /path` is checked like `api.*` against the `Method`/`Path` columns. `page.<slug> — /path` is checked against `Path`. `job.<slug> — <name>` against `Name`. `sym.<slug> — <Name>` against `Name`. Each failure is an error naming the valid values, like the `api.*` message.
  - New fields read: `Pages`, `Jobs`, `Symbols` (via `FIELD_RE`; no parser change needed beyond reading their lines).
  - `_check_new_coverage(section, doc, issues)`: for each `[NEW…]` line in `Routes`, `Pages`, `Jobs`, `Symbols` or `Files`, the target path is the `` `…` `` or bare path after ` in ` (or the entry itself for `Files`). A line with no path is the error `[NEW] in <field> must name the file it will live in (… in <path> [NEW: D<n>])`. The scope is the longest `struct.coverage` scope prefixing the path for that area (`Files` → `files`). Status `partial` or `not scanned` → error `cannot claim new: coverage of <scope> (<area>) is <status>; move it to Open decisions (line N)`. A `Jobs` `[NEW]` is always that error. If the doc has no `struct.coverage` (pre-release doc), skip with no issue.
  - `_check_new_exists(section, doc, issues, notes, moved, load_at)`: a `[NEW]` route/page/job/symbol/file that is listed in the current doc → error `already exists in <id>; cite it instead (line N)` when not `moved`. When `moved`: call `load_at(repo, doc_id, rev, [that id])` → listed at the grounded revision is an error, otherwise a note `<thing> now exists in <id> — built since grounding`. A `load_at` of `None` or a failed one gives the note.
  - `check(..., load_at: LoadAt | None = None)`, where `LoadAt = Callable[[str | None, str, str, list[str]], list[ResolvedRef] | None]`. `mcp.kb_ticket_check` and the CLI pass `lambda r, d, rev, ids: ticketstale.drift_refs(hub, r, d, rev, ids)`.

- [ ] **Step 1: Failing tests** (synthetic `LoadedDoc` fixtures as the existing tests build them):
  - `test_route_citation_from_code_verified` and `test_route_param_syntax_normalised` (`GET /watch/:id` matches a `Path` of `/watch/{id}`)
  - `test_page_job_symbol_citations_verified`
  - `test_new_rejected_when_scope_partial` and `test_new_rejected_when_scope_not_scanned`
  - `test_new_on_jobs_always_rejected`
  - `test_new_requires_target_file`
  - `test_new_on_existing_route_is_error_at_same_revision`
  - `test_new_on_existing_thing_is_note_when_listed_only_after_grounded_rev` (`load_at` returns no ref for it)
  - `test_doc_without_struct_coverage_skips_coverage_gate`
  - `test_existing_ticket_fixtures_unchanged`: every ticket fixture already in `tests/` gives the same report as before.
- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_ticketcheck.py tests/test_cli_ticket_check.py -q` → the new tests FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the same** → PASS
- [ ] **Step 5: Commit** — `feat(ticketcheck): verify route/page/job/sym citations and gate [NEW] on coverage`

---

### Task 12: Drift and code-sync learn the new prefixes

**Files:**
- Modify: `src/strata_kb/ticketstale.py` (`cited_ids`: `route.`/`page.`/`job.`/`sym.` are cited like `api.`), `src/strata_kb/codesync/facts.py` (`_CODE` adds `("route.", _route)`, `("page.", _page)`, `("job.", _job)` only), `src/strata_kb/ticketcheck.py` (`_judge_drift` facts for the new citations, reusing the Task 11 checks)
- Test: `tests/test_codesync_facts.py`, `tests/test_ticketcheck.py`

**Interfaces:**
- Produces:
  - `facts._route(l2, l3) -> frozenset[Fact]`: one fact per (method, normalised path).
  - `facts._page`: one per path.
  - `facts._job`: one per (name, schedule).
  - `in_scope("sym.x", "code")` and `in_scope("struct.files.x", "code")` stay False.

- [ ] **Step 1: Failing tests**: `test_route_facts`, `test_page_facts`, `test_job_facts`, `test_sym_and_files_not_in_codesync_scope`, `test_moved_revision_route_citation_still_valid_is_pass_note` (ticketcheck).
- [ ] **Step 2: Run** `uv run --extra dev pytest tests/test_codesync_facts.py tests/test_ticketcheck.py -k "facts or moved" -q` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** `uv run --extra dev pytest tests/test_codesync_*.py tests/test_ticketcheck.py -q` → PASS
- [ ] **Step 5: Commit** — `feat(codesync): route/page/job facts; drift judges new citations`

---

### Task 13: SA prompt, ticket template, CI template, doctor

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/sa-ticket-ground.md`, `src/strata_kb/templates/init/ticket-template.md:89-113`, `src/strata_kb/templates/init/kb-code.yml` (both `pip install` lines → `"strata-kb[code]=={version}"`), `src/strata_kb/doctor/checks/dev.py` (new `check_code_extra() -> list[Issue]`), `src/strata_kb/doctor/run.py` (call it for kind dev), `src/strata_kb/templates/init/QUICKSTART-dev.md`, `QUICKSTART-ba.md`
- Test: the existing template tests (`tests/test_template_*`, `tests/test_init*`), `tests/test_doctor_checks.py`

**Interfaces:**
- Produces:
  - Prompt text, as spec §5.9:
    - Load also `struct.coverage`, `route.*`, `page.*`, `job.*`, `sym.*`, `struct.files.*`.
    - The coverage rule applies to the six areas only; `svc.*`, `int.*`, volumes, devices and whole new `db.*` tables keep today's rule.
    - `[NEW]` lines name `in <path>`.
    - Jobs: an absent job always goes to Open decisions.
    - The `struct.tree` depth-4 sentence becomes "use `struct.files.*` for paths deeper than `struct.tree` shows".
  - Ticket template adds, after `Routes:`: `- Pages: page.<app> — <path>, … — or none`, `- Jobs: job.<file> — <name>, … — or none`, `- Symbols: sym.<package> — <Name>, … — or none`. `Routes:` reads `api.<tag> | route.<file> — <METHOD> <path>`. The `Files:` hint reads "as listed in struct.tree or struct.files.*".
  - `check_code_extra`: a `warning` `strata-kb[code] is not installed — routes, pages, jobs and symbols will be 'not scanned'; pip install "strata-kb[code]"` when `_ts.available()` is False.

- [ ] **Step 1: Failing tests**: `test_sa_prompt_mentions_struct_coverage_and_jobs_rule` (asserts the exact phrases `struct.coverage`, `never complete` / `Open decisions` for jobs, and `in <path> [NEW: D<n>]`); `test_ticket_template_has_pages_jobs_symbols_fields`; `test_kb_code_workflow_installs_code_extra`; `test_doctor_warns_without_code_extra`.
- [ ] **Step 2: Run** `uv run --extra dev pytest tests -k "sa_prompt or ticket_template or kb_code_workflow or code_extra" -q` → FAIL
- [ ] **Step 3: Implement.** Re-render the SA wrappers if the repo keeps rendered copies, and run the test that pins bodies to wrappers.
- [ ] **Step 4: Run** `uv run --extra dev pytest tests -k "template or init or doctor" -q` → PASS
- [ ] **Step 5: Commit** — `feat(sa): ground on coverage, new Pages/Jobs/Symbols fields, code extra in CI`

---

### Tasks 14–20: Language adapters

Each task has the same shape, and each adds tests in its own `tests/test_codeingest_routes_<lang>.py` (jobs and symbols cases are included in the same file):

- **Files:** Create `extractors/_routes_<lang>.py` (export `ADAPTERS`). Modify `routes.py` to merge it, `_symbols_lang.py` to add the language's exporter, and `jobs.py` if that task's job patterns were stubbed. Register nothing new.
- **Step 1:** Write failing tests: per framework one test asserting `table_rows(...)` for a controller with a class/group prefix and a path param, one `test_<fw>_dynamic_path_partial`, and one symbols test per language listing the export rule's edge (e.g. Go lower-case not exported).
- **Step 2:** `uv run --extra dev pytest tests/test_codeingest_routes_<lang>.py -q` → FAIL
- **Step 3:** Implement with the rules below.
- **Step 4:** Same command → PASS, then `uv run --extra dev pytest tests/test_codeingest_*.py -q` → PASS
- **Step 5:** Commit `feat(codeingest): <lang> routes, jobs and symbols`

| Task | Lang (`_ts` ids) | Route rules (spec §5.2) | Exported symbols (spec §5.6) |
|---|---|---|---|
| 14 | JVM (`java`, `kotlin`) | Spring: class `@RequestMapping(p)` + `@Get/Post/Put/Patch/DeleteMapping(p)`, `@RequestMapping(value=, method=)`; Quarkus: `@Path` on class + method with `@GET/@POST/…`; Micronaut: `@Controller(p)` + `@Get/@Post/…(p)`. Request type: the `@RequestBody`/`@Body` parameter type. | `public` top-level types, `public static final` fields, enum constants (`member`, `Enum.CONST`); Kotlin: top-level non-`private`/`internal` declarations, `object` `const val`, enum entries |
| 15 | .NET (`csharp`) | `[Route("p")]` on controller (`[controller]` token → class name minus `Controller`, lower-cased) + `[HttpGet("p")]`…; minimal API `MapGet/MapPost/…(p, …)`, `MapGroup(p)` chains. Request type: `[FromBody] T`. | `public` types, `public const` / `public static readonly` fields, enum members |
| 16 | Python (`python`) | FastAPI: `@<x>.get/post/…(p)`, `APIRouter(prefix=)`, `include_router(r, prefix=)` (same file, or a module imported relatively); Flask: `@<x>.route(p, methods=[…])` (default `GET`), `Blueprint(..., url_prefix=)`, `register_blueprint(bp, url_prefix=)`; Django: `urls.py` `path()/re_path()` with `include()` prefixes, method `ANY`. Request type: a FastAPI parameter annotated with a Pydantic model declared in the repo (fields with required = no default). | `__all__` when it is a literal list/tuple, else module-level `def`/`class`/assignment names not starting with `_`; `Enum` subclass members |
| 17 | PHP (`php`) | Laravel: `routes/*.php` `Route::get/post/…(p, …)`, `Route::prefix(p)->group(fn)`, `Route::resource` expands to the 7 resource routes; Symfony: `#[Route(p, methods: [...])]` on class + method | classes, interfaces, traits, enums + cases (`member`), class `const` (`member`, `Class::CONST`) |
| 18 | Go (`go`) | Gin: `<r>.GET/POST/…(p, h)`, `<g> := <r>.Group(p)` chains | capitalised top-level funcs, types, consts, vars |
| 19 | Rust (`rust`) | Actix: `#[get(p)]`…, `web::scope(p)`, `web::resource(p).route(web::get().to(h))`; Axum: `.route(p, get(h).post(h2))`, `.nest(p, router)`; Rocket: `#[get(p)]`…, `mount(p, routes![…])` | `pub` items; `pub enum` variants (`member`) |
| 20 | Swift + Dart (`swift`, `dart`) | Vapor: `app.get("a", ":id")` (segments joined), `grouped("p")` chains, `RouteCollection.boot`; Flutter has no HTTP routes (pages done in Task 7) | Swift: `public`/`open` declarations; Dart: top-level names not starting with `_`, enum values (`member`) |

Jobs patterns for these languages are already in Task 8. If Task 8 left any language's pattern untested, the task for that language adds its test.

---

### Task 21: Docs and release 1.28.0

**Files:**
- Modify: `pyproject.toml` (version `1.28.0`), `uv.lock`, `CHANGELOG.md` (new top entry `## 1.28.0 — <date>`), `tests/test_readme.py` (version test), `README.md` (code-ingest section lists the new section kinds, the `code` extra and coverage), `docs/src/guide-dev.en.md`, `guide-dev.vi.md`, `guide-ba.en.md`, `guide-ba.vi.md` (SA grounding: coverage rule, new fields)

- [ ] **Step 1:** Update `test_version_is_…_everywhere` to 1.28.0 → run `uv run --extra dev pytest tests/test_readme.py -q` → FAIL
- [ ] **Step 2:** Bump the version. The CHANGELOG entry covers: the new section kinds, `struct.coverage`, the `[code]` extra (pinned 0.13.0, about 184 MB, never 1.x), the gate changes, jobs always `partial`, the upgrade steps (`pip install "strata-kb[code]"`, re-run `kb init --kind dev` for `kb-code.yml` and `kb init --kind ba` for the SA prompt, re-publish `-code`), and the sentence "The guide PDFs under `docs/` were not rebuilt for this release" (the test requires it).
- [ ] **Step 3:** Run `uv run --extra dev --extra server pytest -q -n 8` → the same pre-existing failures as `main` only. Run `uv run --extra dev ruff check src tests`, `uv run --extra dev ruff format --check src tests` and `uv run --extra dev pyright src` → clean.
- [ ] **Step 4: Commit** — `docs: code-ingest structural coverage — 1.28.0`
