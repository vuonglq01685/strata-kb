# code-ingest review fixes — a generated document that is right about its own repo

**Status:** approved design, ready for an implementation plan
**Source:** reviewer G of the 2026-09-08 full framework review,
`docs/superpowers/reviews/2026-09-08-full-framework-review/G-code-ingest.md`
(findings G-1…G-19), and §5 đợt 3 item 3 of
`docs/superpowers/reviews/2026-09-08-full-framework-review.vi.md`.
**Predecessor:** `2026-09-14-ba-gates-review-fixes-design.md` (reviewer E,
merged as PR #50, 0.22.0). That batch made the BA gate read section bodies;
this batch makes `kb code-ingest` emit a `-code` document whose commands,
tree, schema, dependencies and services are true for the repository it ran
on — starting with this one.
**Approach:** as approved on 2026-09-16 — take the file list from
`git ls-files` instead of an unfiltered `os.walk`; refuse to write over a
document this command did not generate, with no override flag; classify
commands by token, not substring; never merge a table across migration
directories; render every dependency group; read workspace `package.json`
and a compose `build:` Dockerfile as service evidence.

## Goal

Reviewer G self-ingested this repository, built an adversarial polyglot
fixture (Node workspaces, Maven + Flyway, EF, Go, PHP, Prisma, Alembic, k8s,
compose, `.env`, SQLite), and published the result to a scratch hub. The
verdict splits cleanly in two.

The **safety half is strong and could not be broken**: byte-identical
output across runs, zero secret leaks across every mapping / list /
YAML-mangled / k8s / OpenAPI-userinfo attack, `.env` provably never opened,
SQLite only via `--db`, exit 1 when only `tree` detects, `dirty_tree` from
HEAD, `-svc` protected in both directions, twelve malformed manifests and
two binaries → named warnings and no traceback.

The **accuracy half is not met** — the document is wrong about the
framework's own repository:

- `cmd.lint` is `pip install "ruff>=0.15,<0.16"`, `cmd.run` is a `curl …
  /dev/null` health probe, `cmd.build` is `pip install -e ".[dev]"`,
  because `_classify` (`commands.py:154-163`) is an unanchored substring
  match (`/dev/null` contains `dev`, `:latest` contains `test`) and the
  first CI line in a job wins. `scripts/gate.sh` — this repo's own release
  gate — appears nowhere; `tox.ini`'s `commands =` is never read;
  multi-line `run:` blocks are split per line without joining `\`
  continuations, so shell fragments ship as test commands (G-2).
- `struct.tree` is 86 % git-ignored noise (`.venv-artifact/`,
  `.venv-runner/`, `.worktrees/`): 29 052 tokens against C3's 5 000
  ceiling, an L1 summary whose 24 of 28 "entry points" are vendored
  site-packages, the word *tracked* factually false, and the same commit
  producing different output on two machines (G-3).
- Two independent migration directories that both `CREATE TABLE users`
  produce one `db.users` whose columns exist in neither — `plan` from one
  schema, `last_login` ALTERed in from the other, `email`/`created_at`
  and the real primary key gone (G-4).
- `dep.python` lists 12 rows, two duplicated, three from the CI-runner-only
  `requirements-gate.txt`; the five `[project.optional-dependencies]`
  groups — including the entire PDF-ingest engine — are absent. Node
  `devDependencies` and PHP `require-dev` are read into a `dev` group the
  renderer never shows. `("gin-gonic/gin", "Gin")` can never match a real
  `go.mod` (G-5).
- The spec and README both list workspace `package.json` as a `services`
  source; no reader exists, so a Node monorepo gets zero `svc.*` sections
  and no Stage-D join key (G-6).
- `svc.hub` on this repo reads ``image ` ` ``: the compose file uses
  `build: .`, and the Dockerfile reader runs only when there is no compose
  file at all. `Technology` is `none` for every service in every fixture
  (G-8).
- A hand-curated document sitting at `<repo_id>-code` is deleted without a
  warning (`core.py:453`): the destination guard only recognises a `-svc`
  document (G-1, CRITICAL).
- A relative `--kb-dir` resolves against `--repo-root`, undocumented and
  unlike every other `kb` command; the reviewer's first run created two
  directories inside a repo they had been told not to touch (G-11).
- EF tables render a header row with no rows and `0 columns`; Alembic
  types render as `sa.Integer(` and `primary_key=True` is not seen (G-13);
  `[project.scripts]` keys are mixed into a list of file paths (G-16);
  `source_sha256` holds a git SHA-1 (G-15).

290 code-ingest tests are green. Every finding here is a shape the suite
does not cover, not a broken test.

## Decisions taken during brainstorming (2026-09-16)

1. **Scope: đợt 3 plus every accuracy finding.** G-1, G-2, G-3, G-4, G-5,
   G-6, G-8, G-11, G-13, G-15, G-16. G-9 (unpinned `kb-code.yml`) was
   already fixed by the reviewer-D/E batches (`pip install
   center-kb=={version}`). Out of scope, recorded below: G-7, G-10, G-12,
   G-14, G-17, G-18, G-19.
2. **`walk_tree()` takes its file list from `git ls-files`**, falling back
   to the existing `os.walk` when the root is not a git repository. Chosen
   over parsing `.gitignore` in Python (a matcher that drifts from git) and
   over widening `IGNORED_DIRS` (patches this repo only, leaves *tracked*
   false).
3. **A foreign destination is refused, with no `--force`.** The signal is
   the manifest this command itself writes — title suffix and the seven
   generated section prefixes — not a new model field. The operator moves
   the document or picks another `--doc-id`.
4. **Tables never merge across migration directories.** A duplicate
   `CREATE TABLE` from another directory is dropped with a warning naming
   both files; an `ALTER TABLE` from another directory is not applied and
   warns. The section id stays `db.<name>`; a qualified-id scheme was
   rejected because ids feed `kb-context` pins and `-svc` evidence
   matching and must not shift when a directory is added.
5. **`--kb-dir` resolves against the current directory**, the way every
   other `kb` command's `--kb-dir` does. `--db` keeps resolving against
   `--repo-root` (it names a file inside the repo; README already says so).
6. **`pip install` is no longer a build keyword** and the "first CI line
   wins" rule stays. With token matching, the install step that precedes
   the real command in every CI job no longer classifies at all, so the
   reviewer's "last line wins" suggestion is unnecessary churn.

   **Correction (2026-09-16, final whole-branch review, finding C1):**
   this premise is false whenever the installed *package name* is itself
   a `PURPOSE_KEYWORDS` entry — `pip install build twine` still classified
   as `build`, and `pip install ruff` as `lint`, under whole-token matching
   alone, because `build` and `ruff` are exact tokens. Token matching
   narrowed the false-positive class G-2 was about; it did not close it.
   The branch's own acceptance test caught this at the release commit
   (`cmd.build` was `pip install build twine`, not `python -m build`). The
   actual fix drops a line whose leading tokens are a package-manager
   install verb (`pip install`, `npm ci`, `apt-get install`, ...) before
   classification ever runs — still not "last line wins", which stays
   ruled out for the reasons this decision already gives.

## Scope

In scope, one release (0.23.0):

- `src/center_kb/codeingest/extractors/tree.py` — `walk_tree` from
  `git ls-files`, L3 line cap, honest wording, console scripts split from
  entry-point files (G-3, G-16).
- `src/center_kb/codeingest/core.py` — foreign-destination refusal,
  `--kb-dir` resolution, `source_sha256` (G-1, G-11, G-15).
- `src/center_kb/cli.py` — drop the R23 resolution block, help text.
- `src/center_kb/codeingest/extractors/commands.py` — token classifier,
  continuation joining, tox `commands =`, shell-script reader (G-2).
- `src/center_kb/codeingest/extractors/schema.py` — per-directory table
  ownership, EF "columns not extracted", Alembic balanced-paren type and
  `primary_key=True` (G-4, G-13).
- `src/center_kb/codeingest/extractors/deps.py` — optional-dependency and
  per-file groups, group rendering, Gin prefix (G-5).
- `src/center_kb/codeingest/extractors/services.py` — workspace reader,
  compose `build:` → Dockerfile, infrastructure image labels, `Command` and
  `Env file` rows (G-6, G-8).
- README §7.12, CHANGELOG, `pyproject.toml` version, Stage B handover
  notes.

Out of scope, deliberately:

- **G-7** (k8s evidence lost on dedupe), **G-14** (duplicate warnings on
  malformed input), **G-17** (`bin`/`build`/`target` pruned
  unconditionally), **G-18** (lowercase `.env.example` keys, k8s `env:`
  blocks in `integrations`), **G-19** (symlinked directories) — real, not
  accuracy-breaking, next batch.
- **G-10** (L2 larger than L3 in 6/7 sections, C1 latch inert on `-code`)
  — a rendering-shape question across every extractor; this batch keeps
  every new L2 addition compact (names only, constraints in L3) so it does
  not get worse.
- **G-12** (case-insensitive globbing finds a file on Windows and misses it
  on Linux) — needs a policy decision on `fnmatchcase` vs. documented
  lowercase-only names.
- **Retrieval vocabulary** ("how do I run the tests" not hitting
  `cmd.test`) — reviewer F's area.
- **Healthcheck**, `pnpm-workspace.yaml`, Maven `<plugins>`, `setup.cfg`
  `extras_require` — not read; README says so.

## Design

### 1. The tree walk (G-3, G-16)

`tree.walk_tree(root, kb_dir)` keeps its signature and return shape —
`list[(depth, rel_dir, sorted_filenames)]` in preorder — so the six
extractors that import it change nothing.

A new module-level helper `tracked_files(root) -> list[str] | None` runs
`git ls-files -z` through `core._git` (already present, stdin
`DEVNULL`) and returns the `/`-separated paths, or `None` when the process
fails (not a git repository, git absent). `walk_tree` calls it:

- **`git ls-files` succeeded:** build the directory map from the paths.
  Every ancestor directory of a listed file is an entry (git does not track
  empty directories, so none appear). A path is dropped when any of its
  directory components is in `IGNORED_DIRS`, or when the directory resolves
  to `kb_dir` — the same two prunes the walk applies today, so a tracked
  `.kb/` or `dist/` behaves exactly as before. Entries are sorted by path;
  filenames sorted within each directory.
- **`None`:** the existing `os.walk` loop, unchanged.

No caching: the call is milliseconds on a 10 k-file repo, and tests mutate
trees between calls in one process.

`TreeExtractor.extract` calls `tracked_files` once more to decide the
wording and the warning:

- git: summary `Repository layout: N directories, M tracked files, …`.
- not git: summary `… M files (not a git repository — listing unfiltered)`
  and one warning `<root> is not a git repository — the tree is an
  unfiltered directory walk`. Other extractors fall back silently; one
  warning per run is enough.

**L3 cap.** `_L3_MAX_LINES = 600` (≈ 5 000 tokens, C3's ceiling). After the
depth-4 filter, the rendered lines are truncated to the cap and the fence
gains a final line `# … N more entries omitted (capped at 600 lines)`. The
existing `# tree, capped at depth 4` marker stays. The summary's counts
remain whole-tree counts; the marker keeps the fence honest about the
difference, as the depth marker already does.

**Entry points.** `_detect_entry_points` returns `(files, console_scripts)`.
The L2 renders two lists — `Detected entry points:` (file paths, as today)
and `Console scripts (pyproject [project.scripts]):` with `- kb =
center_kb.cli:app` — and the summary reads `entry points: …; console
scripts: kb`. Either list may be `none detected`.

### 2. Foreign destinations (G-1)

In `core.run()`, after `existing_code_manifest` is loaded and after the
`_is_curated_destination` check, a new guard:

```python
_GENERATED_PREFIXES = ("struct.", "cmd.", "dep.", "db.", "svc.", "int.", "api.")

def _is_foreign_destination(doc_dir: Path, manifest: models.Manifest | None) -> str | None:
    """A reason string when `doc_dir` holds a document this command did not
    generate, else None."""
```

The destination *has content* when `doc_dir` contains any `*.md` or a
`_manifest.yaml`. A destination with content is foreign when:

- the manifest could not be loaded (`manifest is None` — missing or
  unreadable; `_load_manifest_guarded` already warned), or
- `manifest.title` does not end with `— code knowledge` (the exact suffix
  `run()` writes), or
- any `manifest.sections[*].id` starts with none of the seven prefixes.

Then `run()` raises `CodeIngestError`, exit 1, before `dirty_tree`, before
any extractor runs, before the stale-`.md` prune — nothing is written:

```
--doc-id 'poly-code' targets <dir>, which holds a document kb code-ingest
did not generate (title: 'Poly hand-written domain doc'); choose a
different --doc-id or --repo-id, or move that document away — nothing was
written
```

An empty or absent destination, and a `-code` document from a previous
run — including one whose statuses `kb summarize --redo` or `kb approve`
rewrote, since neither touches the title or the ids — pass as today. The
`index.yaml` summary-preservation rule in `_upsert_index_entry` is
unchanged: it exists to keep an LLM-drafted L0 summary, and the "human
summary kept on top of generated content" symptom disappears with the
refusal.

### 3. `--kb-dir` (G-11, G-15)

`CodeIngestOptions.__post_init__` resolves a relative `kb_dir` against
`Path.cwd()`; the CLI's R23 block that pre-resolved it against
`repo_root` is deleted (the dataclass is the one place the rule lives).
`db_paths` keep resolving against `repo_root`. `walk_tree`'s prune already
takes the absolute `kb_dir` and checks it lies inside `root`, so a KB
directory outside the repo simply is not pruned — correct.

CLI help: `KB directory (default: .kb, relative to the current directory
like every other kb command)`. `kb-code.yml` runs at the checkout root
with the default, so scaffolded CI is unaffected.

`source_sha256` is written as `""` by both `run()` and `scaffold_svc()`.
`revision` already carries the short commit; the web template hides the
row when the field is empty; nothing else reads it.

### 4. Commands (G-2)

**Classifier.** `_classify(text)` lowercases, splits on whitespace, strips
matching outer quotes from each token, and matches each keyword in
`PURPOSE_KEYWORDS` declaration order: a single-word keyword must equal a
token; a multi-word keyword must equal a run of consecutive tokens.
`PURPOSE_KEYWORDS["build"]` loses `"pip install"`. Reviewer G's seven
lines become the classifier's table test:

| line | before | after |
|---|---|---|
| `code=$(curl -s -o /dev/null -w "%{http_code}" …)` | run | None |
| `pip install "ruff>=0.15,<0.16"` | lint | None |
| `-e CENTER_KB_HTTP_TOKEN=smoke-test-token \` | test | None (joined, see below) |
| `--tag ghcr.io/vuonglq01685/center-kb:latest \` | test | None |
| `echo "starting deployment"` | run | None |
| `aws s3 cp devops.txt s3://bucket` | run | None |
| `ruff check .` | lint | lint |

plus `python -m build` → build, `npm run dev` → run, `go test ./...` →
test, `tox -e lint` → lint.

**Continuations.** `_join_continuations(text) -> list[str]`: lines ending
in `\` are joined to the next with a single space; blank lines and lines
whose first non-blank character is `#` are dropped. `_read_ci` applies it
to every `run:` block (the `_step_dir_label` cd/working-directory logic
reads the joined lines), and the tox and shell readers use it too.

**tox `commands =`.** `_read_python` keeps the env-name candidates and adds:
for `[testenv]` and every `[testenv:<name>]` section with a `commands`
value, each joined line is classified; a hit yields `(purpose, "tox" |
"tox -e <name>", "tox.ini")`, de-duplicated per `(purpose, command)`.

**Shell scripts.** New reader `_read_shell(root, opts)`: every `*.sh` at
the repo root and directly under `scripts/` (via `walk_tree`, depth ≤ 1).
Each script's joined lines are classified; for every purpose that appears
at least once, one candidate `(purpose, f"bash {rel}", rel)`. Order in
`extract()`: after the python reader, before presence-based defaults, so
`bash scripts/gate.sh` lands in the alternatives of `cmd.test`,
`cmd.lint` and `cmd.build`. `detect()` adds "any `*.sh` at root or
`scripts/`".

### 5. Schema (G-4, G-13)

`TableRecord` gains `directory: str` (the posix parent of the file whose
`CREATE TABLE` produced it) and `columns_known: bool = True`.

In `_apply_sql_file`:

- a second `CREATE TABLE <name>` whose directory differs from the kept
  record's: warning `duplicate CREATE TABLE 'users' in <loser> — keeping the
  definition from <winner> (a different migration directory); the two are
  not merged`; the statement is dropped. Same-directory duplicates keep
  today's `IF NOT EXISTS` wording.
- an `ALTER TABLE <name> ADD COLUMN` whose file directory differs from the
  record's: warning `ALTER TABLE 'users' ADD COLUMN in <rel> not applied —
  the table kept for 'users' was created in <winner>, a different migration
  directory`; nothing is appended. Same-directory ALTERs apply as today.

Which directory wins is the existing sorted-relpath order — deterministic
and unchanged.

**EF.** `_apply_ef_file` sets `columns_known=False`. `_render_section`
replaces the empty pipe table with `_Columns not extracted: EF Core
migrations are recognised by table name only._` and the summary reads
`Table Invoices: columns not extracted (EF migration), PK none detected
(source: …)`. The L3 DDL block is unchanged.

**Alembic.** `ALEMBIC_COLUMN_RE` captures only the column name; the type
is the text from the following comma to the first top-level comma or the
`sa.Column(` call's matching close paren (via the existing
`_matching_close_paren`), so `sa.Integer()` and `sa.JSON(none_as_null=True)`
render whole. `primary_key=True` anywhere in that call's arguments marks the
column as `pk`.

### 6. Dependencies (G-5)

Groups become first-class in the renderer; readers only add to them.

- **Python.** `[project.optional-dependencies].<extra>` → group
  `extra:<extra>`. `requirements.txt` at the root → `direct`; every other
  `requirements*.txt` (`requirements-gate.txt`, `requirements/dev.txt`) →
  a group named by its relpath. `setup.cfg install_requires` stays
  `direct`; `extras_require` is not read (README limit).
- **Node / PHP.** Unchanged readers; their `dev` group is now rendered.
- **Go.** `("github.com/gin-gonic/gin", "Gin")`.

`_render_section`:

- L2: the frameworks line and the `direct` table as today; when other
  groups exist, a second table `| Group | Packages |` with the package
  names comma-joined (no constraints — those live in L3).
- L3: one fenced block per group, `# <group>` header, `name constraint`
  lines, every group.
- Summary: `9 direct Python dependencies; 22 more in 6 groups (dev,
  extra:embed, …); frameworks: FastAPI.`
- `detect_frameworks` keeps scanning every group.

### 7. Services (G-6, G-8)

`ServiceRecord` gains `directory: str = ""`, `command: str = ""`,
`env_files: list[str]`.

**Workspaces.** New reader `_read_workspaces(root)`: the root
`package.json`'s `workspaces` — a list of globs, or `{"packages": [...]}`
— each glob resolved with `root.glob`, directories only, `IGNORED_DIRS`
components skipped, and only those holding a `package.json`. One record
per directory: `name` = that `package.json`'s `name` (else the directory
name), `image=""`, `source=<dir>/package.json`, `directory=<dir>`. Sorted
by directory. `detect()` returns True when the root `package.json` has a
`workspaces` key. Reader order in `extract()`: compose, Dockerfile
fallback, k8s, sln, workspaces. `_dedupe` fills an empty `directory` from a
later record silently (metadata, not evidence).

**Compose `build:`.** `_parse_dockerfile(text) -> (base_image, ports,
command)` is split out of `_read_dockerfile` (which now uses it). In
`_read_compose`, a service with an empty `image` and a `build:` key —
a string context, or a mapping with `context` and optional `dockerfile` —
resolves the Dockerfile relative to the compose file's directory:

- found: `image = f"build: {dockerfile_rel} (FROM {base})"`; `ports` from
  `EXPOSE` only when the compose service declares none; `command` from
  `CMD`/`ENTRYPOINT` (last wins, exec-form JSON rendered as a shell line,
  `redact_userinfo` applied); `source = "<compose>, <dockerfile>"`.
- missing: `image = f"build: {context} (Dockerfile not found)"` and a
  warning.

`env_file` (string or list) is recorded by name only — never opened.

`_render_section` adds `| Command | … |` and `| Env file | … |` rows when
non-empty; the lead sentence reads ``Container `hub` — built from
`Dockerfile` (base `python:3.12-slim`).`` when the image is a build.

**Technology.** `_technology_for` uses `record.directory` when set (else
`root / record.name` as today). Before `FRAMEWORKS`, the image's base name
is looked up in a new `_INFRA_IMAGES` table: `postgres`/`postgresql` →
PostgreSQL, `mysql`, `mariadb`, `redis`, `nginx`, `mongo`, `rabbitmq`,
`kafka` (incl. `cp-kafka`, `bitnami/kafka`), `elasticsearch`, `traefik`,
`minio`, `memcached`, `python`, `node` → Node.js, `golang` → Go,
`openjdk`/`eclipse-temurin`/`amazoncorretto` → Java. For a built service
the base is the `FROM` image, so `svc.hub` reads `Python`.

### 8. Release

`pyproject.toml` → `0.23.0`. CHANGELOG `## 0.23.0`:

- **Breaking:** a relative `--kb-dir` resolves against the current
  directory, not `--repo-root`; `kb code-ingest` exits 1 instead of
  overwriting a destination it did not generate.
- **Fixed:** one line per finding, G-1…G-16 as scoped.

README §7.12: the extractor table (`tree` reads `git ls-files`; `services`
lists workspace `package.json` and compose `build:` Dockerfiles; `deps`
names the groups; `commands` adds tox `commands =` and `*.sh`), the
`--kb-dir` row, the foreign-destination refusal, the 600-line cap, and the
"Deliberate parser limits" paragraph (no cross-directory merge, EF columns,
Maven plugins, `extras_require`, `pnpm-workspace.yaml`, healthcheck).
`docs/superpowers/plans/2026-08-19-dev-agent-stage-b-handover.md` gets a
dated note that the empty `Technology` column and the paths-only evidence
gaps it recorded are partly paid here (technology yes; `tables:`
heuristic no).

## Error handling

- Every new reader degrades, never raises: a malformed `workspaces` value,
  an unreadable `.sh`, a Dockerfile that is a directory, a tox `commands`
  value that is not a string — each is one warning naming the file, and
  every other reader still runs. The `_run` wrappers in each extractor
  already catch anything that slips through.
- `git ls-files` failing for any reason (not a repo, git missing, non-zero
  exit) is the fallback path, never an error.
- The foreign-destination refusal is the only new hard error; it fires
  before any write.
- Warnings that name two files always name both the kept and the dropped
  one, in that order.

## Testing

Real filesystem, real `git init` + commit (the suite already does this for
`revision`), no mocks. New tests reproduce reviewer G's fixtures:

- `tree`: a committed repo with a `.gitignore`d `.venv-x/` full of files →
  none in `struct.tree`, summary says `tracked`; the same tree without
  `.git` → unfiltered, `not a git repository` warning; 700 tracked files
  at depth 1 → L3 ends with the omitted-entries marker at 600 lines; a
  tracked `dist/` and the `--kb-dir` are still pruned; console scripts
  split from file entry points.
- `core`: a human document at `<repo>-code` (manifest title `Poly
  hand-written…`, section `ch1`, `body.md`) → exit 1, every byte intact;
  a manifest-less directory with `*.md` → exit 1; an unreadable manifest
  → exit 1; a previous `-code` run whose statuses were set to `pending` →
  proceeds; an empty directory → proceeds. Relative `--kb-dir` from a cwd
  outside the repo lands in the cwd and creates nothing under the repo;
  `source_sha256 == ""`.
- `commands`: the seven-line classifier table above; a workflow whose
  first step is `pip install ruff` and second `ruff check .` → `cmd.lint`
  primary is `ruff check .`; a `run: |` block with `\` continuations →
  one candidate, no fragments; `tox.ini` with `[testenv] commands = pytest
  -q` → `cmd.test` alternative `tox`; `scripts/gate.sh` containing `ruff
  check .` and `pytest` → `bash scripts/gate.sh` under `cmd.lint` and
  `cmd.test`.
- `schema`: the two-directory `users` fixture → columns of the sorted-first
  file only, both warnings present naming winner and loser, `last_login`
  absent; same-directory ALTER still applies; EF table renders the note
  and no empty table; Alembic `sa.Integer()` whole and `primary_key=True`
  → PK.
- `deps`: this repo's `pyproject.toml` shape → `extra:dev`, `extra:ingest`
  … in L3, names in the L2 group table, no duplicate `mcp`;
  `requirements-gate.txt` as its own group; Node `devDependencies`
  rendered; `github.com/gin-gonic/gin` → Gin.
- `services`: workspaces monorepo with two packages and no compose →
  `svc.<pkg>` × 2, `services.md` written, technology from each package's
  deps; compose `build: .` + Dockerfile → image `build: Dockerfile (FROM
  python:3.12-slim)`, ports from `EXPOSE`, `Command` row, `Env file` row
  naming `.env` while `.env`'s contents never appear; `postgres:16` →
  `PostgreSQL`; missing Dockerfile → warning.
- `cli`: self-ingest of this repository asserts `cmd.lint` primary `ruff
  check .`, `cmd.build` primary `python -m build`, `struct.tree` L3 under
  the cap and free of `.venv`, `svc.hub` technology `Python`, `dep.python`
  with no duplicate rows.

Existing tests that pass a relative `--kb-dir` with a `repo_root` other
than the cwd are updated to the new semantics; the plan lists them. The
existing code-ingest baseline (290 passed for reviewer G) and the full suite stay green (the full
suite needs the tiktoken cache once).

## Acceptance

- Self-ingest of this repository at the release commit: `cmd.lint` =
  `ruff check .`, `cmd.build` = `python -m build`, `cmd.run`, if present, is not a `curl` health probe, `bash scripts/gate.sh` listed, `struct.tree` L3 ≤
  600 lines with zero `.venv*`/`.worktrees` entries and the word *tracked*
  true, `svc.hub` shows the Dockerfile base image and `Python`,
  `dep.python` shows 9 direct rows plus the five extras groups with no
  duplicates.
- Reviewer G's polyglot fixture: `db.users` has exactly the columns of one
  file, two warnings name both files, `svc.gateway`/`svc.worker` exist
  from workspaces in the mono fixture, `postgres:16` → PostgreSQL.
- The curated-document fixture at `<repo>-code` exits 1 with the file
  tree byte-identical before and after.
- Two clones of the same commit, one with `.venv-artifact/` present,
  produce byte-identical `-code` documents.
- Every secret-guarantee test from the existing suite still passes; no
  new file is opened that was not opened before except `Dockerfile`s named
  by compose `build:`, `*.sh` at root/`scripts/`, and workspace
  `package.json`s.
