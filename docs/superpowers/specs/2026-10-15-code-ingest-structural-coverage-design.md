# Code-ingest structural coverage — design

Date: 2026-10-15
Status: draft, awaiting owner approval

## 1. Intent

The BA-side SA (`sa-ticket-ground`) grounds tickets on the hub's
`<repo>-code` document only. It has no repository access. When the document
does not show a thing, the SA cannot tell "not built yet" from "built, but
the document does not see it". The prompt forbids parking "not built" under
`Open decisions`, so the SA asks the Dev, and the ticket's gate stays FAIL
until the Dev answers.

A real mission (myflix, 4 tickets, 17 Dev questions) showed that most of
those questions are not about logic at all. They are structural facts the
code holds and `kb code-ingest` does not extract:

| Group | Example question | Why the document cannot answer today |
|---|---|---|
| 1. Structure | "Is `GET /admin/stats` declared in `admin.controller.ts`?" | `api.py` reads committed OpenAPI files only; routes declared in code are invisible. |
| 1. Structure | "Is `playback_events` `PARTITION BY RANGE (created_at)`? Is there an index on `createdAt`?" | `schema.py` parses `PARTITION BY` and drops it; indexes are never emitted. |
| 1. Structure | "Where is the `/admin` page file? Does route group `(viewer)/watch` exist?" | `struct.tree` stops at depth 4 and 600 lines. |
| 1. Structure | "Does `maintenance.service.ts` already have a partition job?" | No extractor for scheduled jobs. |
| 2. Symbols | "Is there a public decorator in `common/decorators/index.ts`? Does `error-codes.ts` have `ASSET_NOT_READY`? Does `tokens.css` define `--admin-danger`?" | No extractor for exported names, enum members or CSS custom properties. |
| 3. Logic / values | Redis value shape, cookie name, `api-client` error mapping, nginx `secure_link`, env values | Out of scope — stays a Dev question. |

This design makes `kb code-ingest` answer groups 1 and 2 for every stack
strata-kb supports, and lets the SA conclude "absent, therefore new" when —
and only when — the document says its scan of that area was complete.

## 2. Goals

- The `-code` document lists, for every supported framework:
  HTTP routes declared in code, UI page routes, scheduled jobs, exported
  symbols (including enum members and CSS custom properties), every tracked
  file, and table partitioning, primary keys and indexes.
- Every new area carries a **coverage statement** per scope (directory,
  framework): `complete`, `partial` (with the unparsed sites named), or
  `not scanned` (with the reason).
- The SA prompt uses coverage: a thing absent from a `complete` scope is
  `[NEW: D<n>]`, not an `Open decisions` item. Absent from a `partial` or
  `not scanned` scope stays an `Open decisions` item, as today.
- `kb ticket check` verifies the new kinds of citation (routes from code,
  pages, jobs, symbols, files beyond depth 4) the same way it verifies
  `api.*` routes and `db.*` columns today, and rejects `[NEW: …]` on a thing
  the document already lists.
- Acceptance: on a fixture repo shaped like myflix (NestJS + Next.js +
  Prisma/Postgres, §7), the group-1/group-2 questions above are each
  answerable by citing a section id — the partition-job question only
  positively (a job that exists is listed; an absent one stays a Dev
  question, §5.8) — and the 7 group-3 questions are not.

## 3. Non-goals

- Logic, behaviour, bodies of functions, failure modes, data flow. Group 3
  stays with the Dev and GitNexus.
- Values: env values, string-constant values, enum member values, config
  file contents (nginx, etc.). Names only — route paths, cron expressions
  and CSS custom-property names are the only literal strings emitted, as
  structural facts (§5.6).
- Request/response body schemas beyond "which DTO type a handler takes"
  (see §5.2 — the DTO's field names and required flags are included because
  they are declared structure; validation semantics are not).
- Running the code, type checking, resolving imports across packages, or
  call graphs.
- Changing the Dev-repo SA (`dev-sa`) — it already has the code.
- Rewriting the existing extractors' readers (SQL, Prisma, Alembic, EF Core,
  SQLite, compose, …) to tree-sitter. Schema stays on its current parsers
  and is extended in place (§5.5).

## 4. Anti-goals

- **A false "complete".** If coverage says `complete` and a route, job or
  symbol exists that the document does not list, the SA writes `[NEW]` and
  the Dev builds a duplicate. Coverage must be conservative: any recognised
  call site the extractor cannot resolve statically makes its scope
  `partial`, never silently dropped.
- **Truncation.** A list that is cut to fit a token budget cannot back a
  "complete" claim. New sections split by directory instead of truncating.
- **Secret leakage.** No value of an env var, constant or literal outside
  §5.6 may reach the output (same rule as `_envkeys.py`).
- **Non-determinism.** Output stays a pure function of the working tree
  (`core.py` contract): same commit, same bytes, regardless of machine.
- **Breaking existing ids.** `api.<tag>`, `db.<table>`, `svc.*`,
  `struct.tree` and every other current id keep their meaning and shape;
  tickets grounded today must still pass.

## 5. Design

### 5.1 Parsing: tree-sitter, optional extra

- New optional extra `code = ["tree-sitter>=…", "tree-sitter-language-pack==<pinned>"]`
  in `pyproject.toml`. Pinned exactly: grammar changes alter output, and
  output must be deterministic per strata-kb version.
- One shared module (e.g. `codeingest/extractors/_ts.py`) owns: language
  detection by extension, parser cache, and a small query helper. Each
  framework adapter is a set of tree-sitter queries plus a little Python to
  join prefixes.
- Without the extra installed, the new extractors do not detect-and-fail;
  they emit coverage `not scanned — install strata-kb[code]` for every
  scope they would have scanned. The SA then treats those areas exactly as
  today (Dev question). `kb code-ingest` prints one warning.
- `templates/init/kb-code.yml` installs `strata-kb[code]=={version}` in
  both jobs. `kb doctor` (dev kind) warns when `[code]` is missing locally.
  The Docker image is unchanged (it serves the hub; it does not ingest
  code).

### 5.2 HTTP routes declared in code — `route.<module>`

New group `routes`, ids `route.<slug>`, one section per module (controller
class, router file or route file — the unit the framework itself uses).
L2 table: `Method | Path | Handler | File | Request type`. `Path` is the
full path with every statically known prefix joined (class prefix, router
mount, group prefix, global prefix set in code). `Request type` is the
declared body/DTO type name when the signature carries one; L3 adds that
type's declared fields with their required/optional flag when the type is
defined in the same repo and its fields are statically declared.

Frameworks (the current `FRAMEWORKS` list in `deps.py`):

| Framework | Sources |
|---|---|
| NestJS | `@Controller(prefix)` + `@Get/@Post/…(path)`; `setGlobalPrefix` in `main.ts` |
| Express | `app/router.METHOD(path)`, `app.use(prefix, router)` |
| Next.js | `app/**/route.(ts|js)` exported `GET/POST/…`; `pages/api/**` (`ANY`) |
| Nuxt | `server/api/**`, `server/routes/**` (method from file suffix, else `ANY`) |
| Spring Boot | `@RequestMapping` on class + `@GetMapping/…`/`@RequestMapping(method=)` |
| Quarkus | JAX-RS `@Path` + `@GET/@POST/…` |
| Micronaut | `@Controller(prefix)` + `@Get/@Post/…` |
| ASP.NET Core | `[Route]` + `[HttpGet]/…` on controllers; minimal API `MapGet/MapPost/…`, `MapGroup` |
| FastAPI | `@app/@router.get/…`, `APIRouter(prefix=)`, `include_router(prefix=)` |
| Flask | `@app/@bp.route(path, methods=)`, `Blueprint(url_prefix=)` |
| Django | `urls.py` `path()/re_path()` + `include()` prefixes (method `ANY`) |
| Gin | `r.GET/…`, `Group(prefix)` |
| Laravel | `routes/*.php` `Route::get/…`, `Route::prefix()->group()` |
| Symfony | `#[Route]` attributes on controller + method |
| Actix Web | `#[get(path)]`, `web::scope`, `web::resource().route()` |
| Axum | `.route(path, get(h))`, `.nest(prefix, …)` |
| Rocket | `#[get(path)]`, `mount(prefix, routes![…])` |
| Vapor | `app.get(...)`, `grouped(...)` |

The existing OpenAPI `api.<tag>` sections stay unchanged. When both exist,
both are emitted; the SA cites either.

Partial coverage: a route whose path or prefix is not a string literal
(a variable, a computed value, a config lookup), a router mounted from a
variable the adapter cannot follow within the same file, or a decorator
form the adapter does not know. Each such site is named `file:line` in the
scope's coverage row.

### 5.3 UI page routes — `page.<app>`

New group `pages`, ids `page.<slug>` per front-end app (the directory that
owns the router). L2 table: `Path | File | Layout/group`. Route groups such
as `(admin)` and dynamic segments (`[id]`, `:id`, `[...slug]`) are kept as
written.

| Framework | Sources |
|---|---|
| Next.js | `app/**/page.*` (route groups, dynamic segments), `pages/**` |
| Nuxt | `pages/**` |
| SvelteKit (`svelte`) | `src/routes/**/+page.svelte` |
| Angular | `Routes` arrays: `{ path, component \| loadComponent \| loadChildren }` |
| Vue | `vue-router` `routes` arrays |
| React | `react-router` `<Route path>` and `createBrowserRouter` arrays |
| Flutter | `go_router` `GoRoute(path:)`, `MaterialApp(routes:)` maps |

Next.js `middleware.ts` `config.matcher` values are listed under the app's
section as a `Middleware matcher` row (they are literal route patterns;
what the middleware *does* stays group 3).

### 5.4 Scheduled jobs — `job.<module>`

New group `jobs`, ids `job.<slug>` per declaring file or manifest. L2
table: `Name | Schedule | Handler | File`.

| Source | Pattern |
|---|---|
| NestJS | `@Cron(expr)`, `@Interval(ms)`, `@Timeout(ms)` |
| Spring / Quarkus / Micronaut | `@Scheduled(cron=/fixedRate=/every=)` |
| ASP.NET Core | Hangfire `RecurringJob.AddOrUpdate`, Quartz triggers; `BackgroundService` subclasses listed with schedule `hosted` |
| Celery | `beat_schedule` entries, `@periodic_task`, `add_periodic_task` |
| Laravel | `$schedule->…` in `Console/Kernel.php`, `Schedule::` in `routes/console.php` |
| Symfony | `#[AsCronTask]`, `#[AsPeriodicTask]` |
| Node (any) | `node-cron` `cron.schedule`, `bullmq` repeatable jobs |
| Go | `robfig/cron` `AddFunc/AddJob` |
| Rust | `tokio-cron-scheduler` `Job::new*` |
| Manifests | k8s `CronJob` (`schedule`, image), GitHub Actions `on.schedule` is **not** included (CI, not product) |

### 5.5 Schema: partitioning, primary keys, indexes

Extend the existing `db.<table>` sections — no new group, no new ids. L2
gains rows: `Primary key`, `Partition` (`RANGE (created_at)` / `none`),
`Indexes` (one per line: name, columns, unique). Readers:

- SQL migrations: keep `PARTITION BY …` instead of dropping it; parse
  `CREATE [UNIQUE] INDEX … ON <table> (…)`, `ALTER TABLE … ADD CONSTRAINT …
  PRIMARY KEY/UNIQUE`, and `CREATE TABLE … PARTITION OF …` (child
  partitions listed under the parent).
- Prisma: `@id`, `@@id`, `@unique`, `@@unique`, `@@index`.
- Alembic: `op.create_index`, `op.create_primary_key`.
- EF Core: `HasKey`, `HasIndex`, `[Index]`, `[Key]`.
- SQLite file: `PRAGMA index_list`.

A DDL form the reader skips today (`RENAME`, `DROP`, other `ALTER`) makes
the affected table's index/partition rows `partial` with the statement
named, instead of a bare warning. Existing column rows are unchanged.

Prisma and SQL for one table *(builder-check call)*:
- The `sql` reader also reads `prisma/migrations/*/migration.sql`.
- Prisma keeps its id `db.<ModelName>` (no id change, §4) and gains a
  `Table` row with the `@@map` name (or the model name).
- SQL facts for that physical table (partition, indexes, primary key)
  merge into the Prisma section instead of emitting a second `db.*`
  section. Columns still come from the first reader, as today; only the
  §5.5 rows merge. Where two readers disagree on a merged row, both values
  are shown with their source and the table's schema coverage is `partial`.

### 5.6 Exported symbols — `sym.<package>`

New group `symbols`, ids `sym.<slug>` per package root (a directory with
its own manifest: `package.json`, `pyproject.toml`, `go.mod`, `*.csproj`,
`Cargo.toml`, `pom.xml`/`build.gradle*`, `composer.json`, `pubspec.yaml`,
`Package.swift`), else per top-level source directory. The split level is
fixed and never depends on size, so an id never moves as code grows
*(builder-check call)*. No truncation: L2 holds the full table
`Name | Kind | File`. Kinds: `function`, `class`,
`interface`, `type`, `const`, `enum`, `member` (of an exported enum or of an
exported `const` object literal, one level deep — this is how error-code
maps are usually written), `decorator` (an exported function used as a
decorator elsewhere in the repo is still `function`; the kind is what the
declaration is), `css-var`.

| Language | "Exported" means |
|---|---|
| TS/JS | `export` declarations, `export { … }`, `export default` (named by file) |
| Python | `__all__` when present, else module-level names not starting with `_` |
| Go | capitalised top-level identifiers |
| Java / Kotlin | `public` top-level types, their `public static final` fields, enum constants |
| C# | `public` types, `public const`/`static readonly` fields, enum members |
| PHP | classes, interfaces, traits, enums + cases, class `const` |
| Rust | `pub` items, `pub` enum variants |
| Swift | `public`/`open` declarations |
| Dart | top-level names not starting with `_` |
| CSS/SCSS | custom properties (`--name`) declared in any rule; SCSS `$vars` excluded |

Only names are emitted — never a value. Generated, vendored and test
directories (`IGNORED_DIRS`, plus test file conventions per language) are
skipped and named as such in coverage.

### 5.7 Every tracked file — `struct.files.<dir>`

`struct.tree` stays as it is (the overview SAs and Devs already use). New
sections `struct.files.<slug>` in group `structure`, one per top-level
directory (fixed, never split by size — §5.6): L3 is the complete, uncapped list of
tracked files under it, one per line. L2 is the file count and the
sub-directories. `kb ticket check`'s `Files:` check reads the union of
`struct.tree` and every `struct.files.*`; the "beyond depth cap" warning
only fires when no `struct.files.*` covers the path.

### 5.8 Coverage — `struct.coverage`

One new section, `struct.coverage` (group `structure`). L2 table:
`Area | Scope | Framework/language | Status | Detail`.

- Area: `routes`, `pages`, `jobs`, `symbols`, `files`, `schema`.
- Scope: a directory (the app/package root the adapter scanned).
- Status: `complete`, `partial`, `not scanned`.
- Detail: for `partial`, each unresolved site `file:line` (capped list with
  a count is acceptable here — this list never backs a "complete" claim);
  for `not scanned`, the reason (extra missing, language without adapter,
  framework detected but no adapter).

A framework detected by `deps.py` with no adapter for an area that applies
to it is `not scanned`, never silently absent.

What `complete` promises: every *recognised* form in that scope was
resolved. Unknown forms (a home-made decorator, a meta-annotation) are a
known blind spot for `routes`, `pages` and `symbols`; adapters still mark a
scope `partial` on the suspicious signs they can see (an import from the
framework's routing package that matched no known form).

**`jobs` is never `complete`** *(owner decision)*. A job can live where no
adapter looks: `pg_cron` in a SQL migration, a hand-written `setInterval`,
a k8s CronJob in another directory, a server crontab. The `jobs` rows are
always `partial`, with detail "jobs outside framework schedulers are not
detectable". So `job.*` sections answer "this job exists" positively, but
an absent job always stays an `Open decisions` item for the Dev, and the
gate (§5.10) rejects `[NEW: D<n>]` on a `Jobs:` line.

### 5.9 SA prompt and ticket template

`templates/init/bodies/sa-ticket-ground.md` (and the command/skill/Cursor/
Copilot wrappers that render it):

- Load step: also `struct.coverage`, and the `route.*`, `page.*`, `job.*`,
  `sym.*`, `struct.files.*` sections matching the ticket's nouns.
- New rule, **only for the six coverage areas** (a route, page, job,
  symbol, file, or a table's partition/index/primary key): "absent from
  the document" means *not built* only when `struct.coverage` shows
  `complete` for that area and the scope that would contain it. Then the
  line is `[NEW: D<n>]`. Otherwise it is an `Open decisions` item, quoting
  the coverage row's status. Everything else (`svc.*`, `int.*`, volumes,
  devices, a whole new `db.*` table, greenfield services from the
  architecture document) keeps today's rule unchanged: not built →
  `[NEW: D<n>]`, never `Open decisions`. *(Builder-check call.)*
- Scope of a new thing: a `[NEW: D<n>]` line in `Routes:`, `Pages:`,
  `Jobs:` or `Symbols:` names the file it will live in
  (`… in <path> [NEW: D<n>]`); the scope is the longest `struct.coverage`
  scope that prefixes that path. A `Files:` entry is its own path.
  *(Builder-check call.)*
- New fields in `## Technical grounding` (ticket template
  `templates/init/ticket-template.md`, and wherever the field list is
  repeated): `Pages:`, `Jobs:`, `Symbols:`. `Routes:` accepts
  `route.<slug> — METHOD /path` as well as `api.<tag> — …`.

### 5.10 `kb ticket check`

- `route.<slug> — METHOD /path`: verified against the section's table, as
  `api.*` is today.
- `page.<slug> — /path`, `job.<slug> — <name>`, `sym.<slug> — <Name>`:
  verified against the section's `Path` / `Name` column.
- `Files:` uses `struct.files.*` (§5.7).
- New error: a `[NEW: D<n>]` line in the six areas whose scope (§5.9) is
  `partial` or `not scanned` — "cannot claim new: coverage of `<scope>` is
  `<status>`; move it to Open decisions". The gate, not only the prompt,
  guards the false-complete anti-goal. *(Builder-check call.)*
- New check: a `[NEW: …]` line whose route, page, job, symbol or file *is*
  listed in the document. **Error** when it is listed at the ticket's
  `Grounded on:` revision ("already exists in `<id>`; cite it instead");
  **note** when it appears only in a later revision (a sibling story built
  it — not a failure). Tickets grounded before this release cite
  revisions without the new sections, so they keep passing.
  *(Builder-check call.)*
- Route matching normalises path-parameter syntax (`:id`, `{id}`,
  `<int:id>`, `[id]` → one placeholder) and trailing `/`. The global
  prefix is part of `route.*` paths; `api.*` (OpenAPI) paths stay as the
  document writes them. *(Builder-check call.)*
- `ticketstale` / `groundingdrift` learn the new prefixes so a moved
  citation is judged by its cited facts, as for `api.*` and `db.*` today.
  `codesync/facts.py` (`kb code-sync scan`) adds `route.`, `page.` and
  `job.` only — not `sym.` or `struct.files.`, whose churn on every commit
  would drown the report. *(Builder-check call.)*

## 6. Constraints

- Python 3.12 (current), no network, no LLM — the `core.py` contract.
- Determinism: sorted output; tree-sitter and grammar versions pinned in
  the `code` extra.
- Degrade, never crash: one unparseable file is a warning plus a `partial`
  coverage row, as every current extractor does.
- `CodeSection.id` uniqueness across all extractors (`core.run()` aborts on
  a duplicate) — new ids use the existing slug/collision rules in
  `services.py`/`api.py`.
- Existing documents and grounded tickets keep passing (§4).
- Release: minor version bump, CHANGELOG entry, Dev and BA guides
  (`docs/src`) and QUICKSTARTs updated for `[code]` and the new fields.

## 7. Acceptance fixture

A fixture repo under `tests/` shaped like myflix: `apps/api` (NestJS with a
controller prefix, a `setGlobalPrefix`, a DTO, a `@Cron` job, a
`common/decorators/index.ts` exporting a `Public` decorator),
`apps/web` (Next.js app router with `(admin)` and `(viewer)` groups,
`middleware.ts` matcher, `styles/tokens.css` with `--admin-*` vars),
`packages/shared/src/error-codes.ts` (exported const object), Prisma schema
plus a raw SQL migration with `PARTITION BY RANGE` and `CREATE INDEX`.

The test asserts each group-1/group-2 question in §1 resolves to a cited
row, `struct.coverage` is `complete` for those scopes except `jobs`
(always `partial`, §5.8), and a
deliberately dynamic route in the fixture makes its scope `partial` with
the site named. One smaller fixture per other framework asserts its
route/page/job/symbol rows.

## 8. Left to the builder

- Exact tree-sitter queries per framework and the module layout under
  `codeingest/extractors/`.
- Which (framework, area) pairs apply and therefore must produce a row
  (e.g. no `pages` row for a backend-only framework); the adapter tables
  above are the starting point.
- Slug rules for new ids, reusing existing helpers.
- Delivery order. Suggested: shared tree-sitter layer + coverage +
  `struct.files` + schema extension first (they help every stack), then
  the TS/JS stack (largest current user), then JVM, .NET, Python, PHP, Go,
  Rust, Swift, Dart.
