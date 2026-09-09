# Reviewer G — `kb code-ingest` (criterion C12, plus C2/C5 as they apply to the generated document)

Repo: `D:\Projects\AERO-KB` @ `4b47b4c`, CLI `D:/Projects/AERO-KB/.venv/Scripts/kb` (center-kb 0.20.0).
Scratch: `<scratchpad>/G/`. All experiments ran outside the repo (see the note in *Scope & method* about one accidental write, reverted).

---

## Scope & method

Files read end-to-end: `src/center_kb/codeingest/core.py` (1242 L), `extractors/{tree,commands,deps,services,schema,integrations,api,_envkeys,_mdcells}.py` (~4200 L), the `code-ingest` command in `src/center_kb/cli.py:651-765`, `src/center_kb/templates/init/kb-code.yml`, README §7.12, spec `docs/superpowers/specs/2026-08-19-dev-agent-design.md` §3/§6, and `docs/superpowers/plans/2026-08-19-dev-agent-stage-b{,-handover}.md`.

Executed:

1. **Self-ingest of this repo, twice** → byte-identical; `kb build`; `kb stats`; token measurement of every section.
2. **A purpose-built adversarial polyglot fixture** (`<scratch>/G/poly`, git-committed): Node workspaces monorepo + `openapi.yaml` (tagged paths, `servers:` with `user:pass@`), Maven `pom.xml` + Flyway MySQL migrations (`) ENGINE=InnoDB…;`, `ADD COLUMN`, `RENAME`, `ADD CONSTRAINT`, quoted table name with a space, `IF NOT EXISTS`, a final `CREATE TABLE` with no `;`, `CREATE TABLE` in block and line comments), a second migration dir reusing a table name, `.csproj` + EF `Migrations/*.cs`, `go.mod`, `composer.json`, `schema.prisma`, Alembic `versions/*.py`, k8s Deployment+Service, `docker-compose.yml` (mapping value with a literal password, `${VAR}` interpolation, list-form `- KEY=value`, the YAML-mangled `- KAFKA_BROKER=kafka: 9092` shape), `.env.example` (comment, `export`, no-`=` line, lowercase key), a real `.env` with `SECRET=hunter2` and a host string existing nowhere else, a real `fixture.sqlite`, `Makefile`, `tox.ini`, `.github/workflows/ci.yml` with multi-line `run: |` and `working-directory:`, `Dockerfile` with `EXPOSE`.
3. Four further fixtures: name-sanitisation (`<scratch>/G/names`), malformed/binary manifests (`/bad`), pure Node monorepo (`/mono`), duplicate service name (`/dup`), filename-case (`/casey`), tree-only (`/tinyrepo`).
4. Published the generated doc to a scratch bare hub and ran `kb query` against it (`<scratch>/G/hub.git`, `/src2`).
5. `pytest tests/test_codeingest_core.py tests/test_codeingest_extractors.py tests/test_codeingest_scaffold.py tests/test_cli_codeingest.py -q` → **290 passed in 29.2 s** (foreground).

> **Read-only note.** My first invocation used `--kb-dir ./kb1` from a scratch cwd and the tool created `D:\Projects\AERO-KB\kb1` and `kb2` — `--kb-dir`, when relative, resolves against `--repo-root`, not the process CWD (`core.py:76`, deliberate "Ruling R23"). Both directories were moved out to scratch immediately; `git status --porcelain` on the repo is now empty. Recorded below as finding **G-11**.

---

## Verified good

* **Determinism (C12) holds.** Two runs into two separate scratch KB dirs are byte-identical (`diff -r` clean, `--json` reports identical). 6.9 s and 8.0 s for a 10 692-file repo. Re-running in place after `kb build` is also a no-op (`diff -r` clean) — token counts are carried forward deliberately (`core.py:462`).
* **The secret guarantee (C12) survived every attack I could construct.** Zero hits for `hunter2`, `ONLYENVHOST`, `PLANTED_COMPOSE_MAPPING_PW`, `PLANTED_COMPOSE_LIST_VALUE`, `PLANTED_DB_PASSWORD`, `PLANTED_K8S_VALUE`, `sk_live…`, `sk_test_PLANTED_ENVEXAMPLE`, `s3cr3tPW`, `user:pass`, `appuser:` anywhere in the generated KB. `.env` is provably never opened (a host string present only in `.env` is absent from the output). The OpenAPI `servers[*].url` userinfo is redacted to `https://***@internal.example.com/v1`. The `_envkeys.py` shared sanitiser is genuinely well-built and the module docstring's account of the two prior leaks is accurate.
* **SQLite only via `--db` (C12).** `fixture.sqlite` with table `dbonly_table` is invisible without `--db`; `--db fixture.sqlite` (relative, resolved against `--repo-root`) adds `db.dbonly_table`. `_path_label` correctly avoids leaking absolute host paths.
* **Exit 1 when only `tree` detects (C12).** A README-only repo: `no code artifacts detected under … — looked for: services, deps, commands, schema, integrations, api`, exit 1, **nothing written**. The gate keys off what `extract()` produced, not `detect()` — a real improvement over the naive version.
* **`dirty_tree` (C12).** Warning fires after an uncommitted edit; the `--json` report carries the boolean. `revision`/`ingested` come from the HEAD commit, never `date.today()` (`core.py:143-158`).
* **SQL parser edge cases the README promises are all correct.** MySQL `) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;` does not smear into the next table; `CREATE TABLE IF NOT EXISTS \`order\`` parsed; a final `CREATE TABLE` with no `;` parsed; `CREATE TABLE` inside `/* */` and `--` comments correctly ignored **without** inflating the count-vs-recognised check; the quoted `"audit log"` name produced exactly the promised warning `found 2 CREATE TABLE statement(s) … recognised only 1 — the rest were skipped, not guessed at`; `ALTER … RENAME` and `ALTER … ADD CONSTRAINT` both warn **naming the file**.
* **Malformed input never tracebacks (robustness).** 12 deliberately broken manifests (YAML/JSON/TOML/XML/csproj/prisma/go.mod/workflow/k8s/alembic) plus two binary files matching globs: every one produced a named `[warn]`, the run continued, other readers still produced sections, exit 0. A second, valid `compose*.yml` still yielded its service.
* **Name sanitisation and id uniqueness are strong.** `"Api Gateway"`, `"svc/with/slash"`, `"  spaced  "`, `"dịch-vụ-đơn-hàng"`, `"тест"`, and two 80-char names all produced valid, unique, whitespace-free ids (`svc.svc-with-slash`, `svc.тест`, `svc.very-long-…-34fd56` / `-4e38b4`), each over-cap truncation warned. `mdutils.slice_section` resolves all of them, including the dotted `db.order.item` and the case-only pair `db.ORDER_ITEM` / `db.order_item`.
* **Ordering / separators (C12).** Sections sort by `(group, id)`; all paths render `/`; all written files are LF-only even on Windows (`_write_group(..., newline="\n")`).
* **Guard rails around the destination.** `--doc-id evil-svc` and `evil-SVC` both refused (exit 1); `--doc-id ../escape` refused; a `-svc`-shaped document copied to an unrelated name (`decoy`) is still refused as "already holds a curated document". Human prose written into `-svc/services.md` survives a `--scaffold-svc` re-run verbatim.
* **`--scaffold-svc` / `kb build` interaction (C13/C5).** Sections land `status: pending` with `<!-- TODO:summarize svc.x -->`; `kb build` exits 1 with `[error] poly-svc §svc.db: still has a TODO marker or an empty summary`; `--allow-pending` downgrades to `[warn]` and exits 0.
* **`--tags` merge/preserve (README claim).** `--tags alpha,beta` then `--tags gamma` then no `--tags` → `[code, generated, gamma, alpha, beta]` preserved throughout.
* **`node_modules` is pruned before descent.** Adding 6 000 files under `node_modules` cost 0.6 s and zero output lines.
* **The Stage B handover doc is unusually honest** — it already records the inert `tables:` heuristic, the empty `Technology` column, the paths-only `-svc` evidence, `os.walk(onerror=None)`, `CREATE TEMPORARY TABLE`, and the count-inflation bug. I have not re-reported those as new; where a known gap is contradicted by an *unqualified* README claim I say so explicitly.

---

## Findings

### CRITICAL

**G-1 — A hand-curated domain document at `<repo_id>-code` is silently destroyed, and its index summary is retained on top of the generated content.**
`core.py:445` (`for stale in doc_dir.glob("*.md"): stale.unlink()`) + `core.py:525` `_is_curated_destination`.
The curated-destination guard protects a `-svc` document. It cannot protect anything else: the `manifest.title` signal only matches `"… curated service knowledge"`; the `status in (pending, reviewed)` signal is gated behind `manifest.id != doc_id` (Ruling R49(1)); the remaining signals are `flow.`/`hist.` sections, `flows.md`/`history.md`, and a banner inside `services.md`. The `index.yaml` `curated` tag was explicitly dropped as a signal (Ruling R47c).

Repro (`<scratch>/G/ckb`):
```
# .kb-like dir holding a human doc: index.yaml tags [domain, curated],
# _manifest.yaml id=poly-code title="Poly hand-written domain doc" section ch1 status=reviewed,
# body.md + body.raw.md with human prose
kb code-ingest --repo-root <poly> --kb-dir <ckb> --repo-id poly
→ exit 0, no warning
ls ckb/poly-code   # body.md and body.raw.md are GONE; 15 generated files in their place
```
The `index.yaml` entry afterwards is the worst of both worlds — generated title and revision, but the human summary preserved verbatim:
```yaml
- id: poly-code
  title: poly — code knowledge          # overwritten
  revision: 70c451e                     # overwritten
  tags: [code, generated, domain, curated]
  summary: A carefully curated human document.   # PRESERVED, now a lie
```
Impact: unrecoverable loss of unversioned human work, plus a published index entry that misdescribes a generated document as curated. Violates **C12** (the `-code`/`-svc` reservation is enforced in one direction only) and **C16** (`kb init` preserves human content; this command does not). Recoverable via git only if the KB was committed.

### HIGH

**G-2 — `cmd.lint` and `cmd.run` on this very repo are wrong, because `_classify` is an unanchored substring match and "first CI line wins".**
`extractors/commands.py:56-67` (`PURPOSE_KEYWORDS`), `:154-163` (`_classify`), `:12` / `:454` (first CI-sourced candidate is primary).

Generated `aero-code`:
| section | primary command emitted | reality |
|---|---|---|
| `cmd.lint` | `pip install "ruff>=0.15,<0.16"` | `ruff check .` (demoted to an "alternative") |
| `cmd.run` | `code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8321/api/docs)` | `python -m center_kb.mcp …` (Dockerfile `CMD`) — never surfaced |
| `cmd.build` | `pip install -e ".[dev]"` | `python -m build` (demoted) |

`cmd.lint` is wrong because `_gate.yml#t0-lint`'s *first* step is the install (`.github/workflows/_gate.yml:…  - run: pip install "ruff>=0.15,<0.16"`) and "ruff" is a lint keyword. `cmd.run` is wrong because `/dev/null` contains the substring `dev`, a `run` keyword. Reproduced directly:
```
$ python -c 'from center_kb.codeingest.extractors.commands import _classify; ...'
   run  <-  code=$(curl -s -o /dev/null -w "%{http_code}" ...)
  lint  <-  pip install "ruff>=0.15,<0.16"
  test  <-  -e CENTER_KB_HTTP_TOKEN=smoke-test-token \
  test  <-  --tag ghcr.io/vuonglq01685/center-kb:latest \      # "la-TEST"
   run  <-  echo "starting deployment"
   run  <-  aws s3 cp devops.txt s3://bucket
  None  <-  bash scripts/gate.sh
```
The last two rows in the shipped `cmd.test` alternatives table are literal shell continuation fragments (`--tag ghcr.io/…:latest \`, `-e CENTER_KB_HTTP_TOKEN=smoke-test-token \`) presented as test commands, because a multi-line `run:` block is split per line with no `\`-continuation joining.

Also: **`scripts/gate.sh` — this repo's own documented release gate (C17) — appears nowhere in the commands document**, because there is no shell-script reader and `bash scripts/gate.sh` classifies to `None`. And **`tox.ini`'s `commands = pytest -q` is never read**: `_read_python` (`commands.py:361-380`) only turns tox *env names* into `tox -e <name>` and classifies the name (`_tox_env_names`, `:345`), so a `tox.ini` with `[testenv]` and an envlist of `py311` contributes nothing.

Violates **C12** (the sections `dev-execute`/`dev-handover` depend on for "how do I test/lint this repo?" are wrong on the framework's own repo) and **C11** (the Dev workflow's evidence rule).

**G-3 — The tree extractor ignores `.gitignore`, so the framework's own `-code` document is 86 % noise from git-ignored directories, and its L1 summary calls them "tracked files".**
`extractors/tree.py:25-30` (hard-coded `IGNORED_DIRS`), `:162` (`… {n_files} tracked files …`).

`IGNORED_DIRS` contains `.venv` but not `.venv-artifact`, `.venv-runner`, `.worktrees`, `.superpowers`, `.benchmarks` — all of which **are** in this repo's `.gitignore`. Measured on `aero-code`:

```
struct.tree  L2 = 681 tokens, L3 = 29 052 tokens
of the L3: 3 344 / 3 797 lines (88.1 %) and 24 922 / 29 079 tokens (85.7 %)
come from .venv-artifact/ .venv-runner/ .worktrees/ .superpowers/ .benchmarks/
```
The L1 summary that goes into `index.yaml`/search reads:
> `Repository layout: 1415 directories, 10692 tracked files, entry points: .venv-artifact/Lib/site-packages/annotated_doc/main.py, .venv-artifact/Lib/site-packages/center_kb/web/app.py, .venv-artifact/Lib/site-packages/dotenv/main.py, … (24 of 28 entry points are vendored site-packages)`

Two separate defects: (a) the word *tracked* is factually false — this is an unfiltered `os.walk`, and my very first run proved it by listing my own untracked `kb1/` output directory in the tree on the second run; (b) the determinism guarantee is weaker than claimed. `tree.py`'s own module docstring says pruning exists so "output would [not] depend on whether dependencies happen to be installed" — but `.venv-artifact`/`.venv-runner` exist only after someone runs `scripts/gate.sh`, and `.worktrees/` only while an SDD task is in flight, so **the same commit produces different `struct.tree` output on two developers' machines**. There is also no file-count cap, only `_L3_DEPTH = 4`: adding 6 000 files in an unignored `vendorlib/` grew `structure.raw.md` from 897 B to 91 050 B (≈25 k tokens) for a 27-file repo.
Violates **C12** (determinism, "pure function of the working tree") and **C2/C3** (a 29 k-token L3 section against a 300–5 000 target).

**G-4 — A table name reused in two independent migration directories produces a fabricated schema that exists nowhere in the repo, with no warning that ALTERs crossed schemas.**
`extractors/schema.py:646-729` — one flat `tables: dict[str, TableRecord]` keyed on the bare table name across every reader and every directory; `:679` warns on the duplicate `CREATE TABLE` but `:719-728` then applies later `ALTER`s to whichever record won.

Fixture: `services/billing/migrations/001_init.sql` has `users(id, plan)`; `src/main/resources/db/migration/V1__init.sql` has `users(id, email, created_at, PRIMARY KEY (id))`; `V2__alter.sql` has `ALTER TABLE users ADD COLUMN last_login`.

Emitted:
```markdown
## db.users users
| Column | Type | PK |
| id | BIGINT NOT NULL |  |
| plan | VARCHAR(32) NOT NULL |  |
| last_login | DATETIME NULL |  |
_Source: services/billing/migrations/001_init.sql, src/main/resources/db/migration/V2__alter.sql_
```
`email`, `created_at` and the real `PRIMARY KEY (id)` are gone; `plan` and `last_login` are joined into a table that exists in neither schema. The only warning is `duplicate CREATE TABLE 'users' in src/…/V1__init.sql; keeping first` — which names the *loser*, never says which file won, and says nothing about the cross-schema ALTER. The L1 summary compounds it: `Table users: 3 columns, PK none detected`.
Violates **C12** (deterministic ≠ correct; no invention) and **C2** ("no invention", "codes/field names verbatim").

**G-5 — `deps` silently omits every optional-dependency group; `dep.python` on this repo lists 12 rows of which 2 are duplicates and 3 come from a CI-runner-only file.**
`extractors/deps.py:307-340` (`_read_node` reads `devDependencies` only into a separate group that is not rendered) and the `_read_python` body (`pyproject.toml` → `[project].dependencies`, `setup.cfg` → `install_requires`, every `requirements*.txt`) — `[project.optional-dependencies]` is never read.

`aero-code §dep.python` as shipped:
```
| jinja2 | >=3.1 |      | mcp | >=1.2 |        | mcp | >=1.2,<2 |
| pydantic | >=2.7 |    | pypdf | >=4.0 |      | pytest | >=8.0 |
| PyYAML | >=6.0 |      | pyyaml | >=6.0 |     | starlette | >=0.37 |
| tiktoken | >=0.7 |    | typer | >=0.12 |     | uvicorn | >=0.30 |
Frameworks detected: none
```
Reality (`pyproject.toml`): 9 direct deps plus five extras — `ingest` (**docling**, imagehash, Pillow, pypdfium2), `dev` (11 incl. **ruff**, pytest, httpx, build, twine, PyJWT), `embed` (sqlite-vec, fastembed), `server`, `s3` (boto3). ~20 packages, including the entire PDF-ingest engine, are absent. `mcp` and `PyYAML`/`pyyaml` appear twice because `requirements-gate.txt` is merged into the same "direct" bucket with no per-file attribution — the L3 renders one `# direct` header, so a reader cannot tell that `pytest>=8.0` is a runner-venv dependency rather than a runtime one. My polyglot fixture reproduces the same omission for Node (`devDependencies` vitest/eslint absent), PHP (`require-dev` phpunit absent), and Maven (`<plugins>` surefire absent).

Related, same file: **`("gin-gonic/gin", "Gin")` at `deps.py:74` can never match a real `go.mod`**, because module paths are `github.com/gin-gonic/gin` and `detect_frameworks` matches on *prefix*:
```
detect_frameworks(['github.com/gin-gonic/gin']) -> []
detect_frameworks(['gin-gonic/gin'])            -> ['Gin']
```
Violates **C12** (the `dep.<ecosystem>` prefix contract in README §7.12 promises "direct dependencies + framework detection").

**G-6 — `services` never reads workspace `package.json`, although both the spec and the README list it as a source; a Node monorepo therefore gets zero `svc.*` sections and no Stage-D join key at all.**
Spec `docs/superpowers/specs/2026-08-19-dev-agent-design.md:354` and README §7.12 table both say: `services` | `docker-compose*.yml`, `Dockerfile`, k8s manifests, `*.sln`, **workspace `package.json`**. `extractors/services.py` has readers `_read_compose`, `_read_dockerfile`, `_read_k8s`, `_read_sln` only; the sole `package.json` reference is `_dep_names_from_directory` (`:550`), which feeds the *Technology* column.

Repro (`<scratch>/G/mono` — root `package.json` with `workspaces:["packages/*"]` and two workspace packages, no compose/Dockerfile/k8s):
```
$ kb code-ingest --repo-root <mono> --kb-dir <monokb> --repo-id mono
detected: deps, commands, tree          # "services" not even detected
files written: 7                        # no services.md at all
```
Violates **C12** (documented extractor input not implemented) and breaks **C13**/Stage D for the whole Node-monorepo class: `kb svc note` has no service to attach to and the C4 `Container(alias, label, technology, …)` join key is empty.

### MEDIUM

**G-7 — A service declared in both compose and k8s silently loses the k8s evidence; the rendered `Source` never names the k8s file.**
`extractors/services.py:379-432` (`_dedupe`). First occurrence wins; only three things warn (image fill, differing images, differing raw names). Ports, `containerPort`, replicas and the source path of the loser are dropped unconditionally.
In the polyglot fixture, compose `gateway` and the k8s Deployment+Service `gateway` share an image, so **no warning at all** fired and `deploy/k8s/deployment.yaml` appears nowhere in `services.md`. With differing images (`<scratch>/G/dup`) the warning is only about the image:
```
[warn] service 'gw': kept image 'nginx:1.27' from docker-compose.yml, discarded 'ghcr.io/x/gw:9' from k8s/d.yaml
| Ports | none |                       # k8s containerPort 9000 lost, unwarned
| Source | docker-compose.yml |         # k8s/d.yaml never named
```
The same mechanism collapses four genuinely distinct compose services (`Api Gateway`, `api.gateway`, `API_GATEWAY`, `api-gateway`) into one `svc.api-gateway` — warned, but the resulting document presents one service where the compose file declares four.

**G-8 — `svc.hub` in this repo's own document says the service has no image, and the Dockerfile is never consulted when a compose file exists.**
`extractors/services.py:710-720` — the Dockerfile reader runs only `if not compose_records`.
`docker-compose.yml` uses `build: .`, so `image` is empty and the L2 renders, verbatim:
```markdown
## svc.hub hub
Container `hub` — image ``.
| Image |  |
| Technology | none |
| Env keys | none |
```
Wrong on four counts: the service *does* have an image (built from `./Dockerfile`, base `python:3.12-slim`); `EXPOSE 8321` and the real `CMD` are never surfaced; `env_file: .env` is not mentioned (correctly not opened, but its existence is knowledge); and the healthcheck is dropped. The `Technology` column is `none` for every service I produced in every fixture (`postgres:16`, `nginx:1.27`, `ghcr.io/example/gateway`) because `_technology_for` (`services.py:592`) looks for a directory literally named after the compose service and otherwise feeds the image base name to a 21-entry `FRAMEWORKS` list that contains no infrastructure images. This is recorded in the Stage B handover §3 as a deferred item — but README §7.12's section-id contract table states `svc.<name>` yields "image, ports, `depends_on`, **detected technology**" with no qualification, and Stage D's C4 wrapper is documented to read `technology` from exactly here.

**G-9 — `kb-code.yml` installs center-kb unpinned, so the published `-code` document can change without a single line of the repo changing.**
`src/center_kb/templates/init/kb-code.yml:29` and `:47` — `- run: pip install center-kb`.
This is the same failure mode the repo's own `_gate.yml` documents at length for ruff ("A lint gate that upgrades itself is not a gate" — pinned `ruff>=0.15,<0.16` after 0.16.0 flagged 127 findings on `main`). A center-kb minor release that changes an extractor produces a hub PR whose diff is caused by the tool, not by the code — and because `-code` is the document the hub is *encouraged* to auto-merge under a path-scoped policy (C12/README §7.12), that diff may merge with no human reading it. Everything else about the workflow is right: `concurrency` with `cancel-in-progress: false`, `permissions: contents: read` (+`id-token: write` only on publish), `python-version: "3.12"` pinned, `kb build` before `kb ci-publish`, `--scaffold-svc` deliberately never passed with a correct explanatory comment, and a comment telling the operator to re-add `--db` flags after a re-init.

**G-10 — The generated document inverts L2/L3 and therefore switches off the C1 table latch entirely for `-code` docs.**
Measured after `kb build --kb-dir <kb1>`:
```
section          L2      L3         L2/L3
cmd.build        231     204        113 %
cmd.lint          74      50        148 %
cmd.run           52      36        144 %
cmd.test         215     189        114 %
dep.python       135     102        132 %
svc.hub           63      45        140 %
struct.tree      681   29052          2 %
```
Six of seven sections have **L2 larger than L3** — because L2 renders pipe tables and L3 renders compact fenced blocks — and six of seven are below C3's 300-token floor while `struct.tree` L3 is 5.8× over the 5 000 ceiling. Consequence for C1: `build.extract_tables` sees **0 tables in every L3 file and 5 in the L2 files**, so "every L3 table appears in L2" is vacuously true and, combined with F-B (no reverse check), nothing in `kb build` validates a single `-code` table against anything. Regeneration is the only safeguard.

**G-11 — A relative `--kb-dir` writes inside `--repo-root`, undocumented.**
`core.py:57-80` (`CodeIngestOptions.__post_init__`) and `cli.py:679-683`. Deliberate (Ruling R23, to keep the writer and `walk_tree`'s pruning consistent), but neither `--help` ("KB directory") nor README §7.12 ("KB directory to write into (default: `.kb`)") says so, and it is the opposite of what a shell user expects. In my session it silently created two directories inside the repo I had been instructed not to touch.

**G-12 — A single non-lowercase filename is found on Windows and missed on Linux — broader than the README's "duplicate filename" caveat, and silent.**
Every extractor matches with `fnmatch.fnmatch` (case-normalised per OS) or `Path.glob`. README §7.12 frames the risk as "a repo with e.g. both `ci.yml` and a differently-cased duplicate", i.e. duplicates. The real exposure is any single file:
```
$ ls casey/ → OpenAPI.YAML  Docker-Compose.YML  package.json
$ kb code-ingest ... (Windows)
detected: services, deps, commands, tree, integrations, api
  api: 1  services: 1        →  api.alpha, svc.s1
$ python -c "import fnmatch; print(fnmatch.fnmatch('OpenAPI.YAML','openapi*.y*ml'), fnmatch.fnmatchcase('OpenAPI.YAML','openapi*.y*ml'))"
True False        # Linux behaves like the second value
```
On the Linux CI runner both sections vanish, with no warning — the *published* document is stable but silently poorer than what the developer validated locally.

**G-13 — Empty and truncated column data are rendered as if authoritative.**
* `db.Invoices` (EF migration) emits a markdown table with a header row and **no rows**, plus L1 `Table Invoices: 0 columns, PK none detected`. `_read_ef` (`schema.py:913-916`) documents "every EF-sourced TableRecord has an empty column list" as a deliberate limitation, but nothing in the *document* says so — a reader concludes the table has no columns.
* `db.events` (Alembic) renders types `sa.Integer(` and `sa.JSON(` — `ALEMBIC_COLUMN_RE`'s `([^,)]+)` capture (`schema.py:835`) stops at the paren — and `PK` is blank despite `primary_key=True`.

**G-14 — Duplicate and unreadable warnings on malformed input.**
One broken `docker-compose.yml` produced three identical multi-line PyYAML tracebacks (services, integrations, and again), `openapi.yaml` two, `package.json` two, `pyproject.toml` two — 21 warnings for 12 bad files, each embedding a 5-line YAML error block. Correct behaviour, poor signal-to-noise for the CI log that is the only consumer.

### LOW

**G-15** — `_manifest.yaml` stores a 40-hex **git SHA-1** in a field named `source_sha256` (`core.py:453`: `source_sha256=full_commit`).
**G-16** — `_detect_entry_points` (`tree.py:97-110`) mixes `[project.scripts]` *keys* into a list of file paths, so `aero-code`'s entry-point list contains a bare `kb` alongside `src/center_kb/web/app.py`.
**G-17** — `IGNORED_DIRS` unconditionally prunes `bin`, `obj`, `build`, `target` — legitimate source directories in many repos (`bin/` scripts, Go/Rust layouts) — with no warning and no opt-out.
**G-18** — `.env.example` keys that are not fully upper-case are dropped with no warning (`_ENV_KEY_RE = ^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=`, `integrations.py`): my planted `LOWER_case_key=` vanished silently. Also, `integrations` reads compose but **not** k8s `env:` blocks, so `REDIS_URL`'s source line says `.env.example, docker-compose.yml` while `deploy/k8s/deployment.yaml` also declares it.
**G-19** — `os.walk` runs with `followlinks=False`, so a symlinked directory renders as an empty directory in the tree with no note. (I could not exercise real symlinks: MSYS `ln -s` on this Windows host copies instead of linking. No loop risk, by inspection.)

---

## Is the generated document actually good knowledge?

**Readability of L2 (C2).** Genuinely good in shape: every section is a short lead sentence plus a small property/column table, human-readable, no dumps — with the sole exception of `struct.tree`, whose L2 is a bare 40-line indented listing and whose L3 is a 29 k-token dump. The banner (`> Generated by kb code-ingest at <sha> — do not edit by hand.`) is clear.

**L1 searchability.** The summaries are well-formed and specific — `Table Customer: 3 columns, PK id (source: prisma/schema.prisma)`, `External integration kafka: configured through 2 environment keys (KAFKA_BROKER, KAFKA_BROKER_URL)`, `How to test this repository: npm test -- --coverage (source: CI: …)`. The one bad summary is `struct.tree`'s (G-3).

**Does `kb query "how do I run the tests"` hit `cmd.test`?** **No.** Published to a scratch hub and queried:
```
$ kb query "how do I run the tests" --hub <hub.git> --budget 900
--- [poly:poly-code §cmd.run  ...]     ← wrong section, wins on "run"
--- [poly:poly-code §cmd.lint ...]
--- [poly:poly-code §cmd.build ...]    ← budget exhausted; cmd.test never returned
```
`cmd.test` only appears at `--budget 4000`, in **fourth** place. `"test command"` does hit `cmd.test` first. Worse: `"which database tables exist"` returns `int.other` and `svc.gateway` and **no `db.*` section at all** at any budget — the db sections' bodies are pipe tables of column names and contain neither the word "table" nor "database" outside the heading. `"what services does this repo run"` returns the three `cmd.*` sections, not the `svc.*` ones. The retrieval layer is reviewer F's area, but the *ingest* side contributes: section bodies carry almost no natural-language vocabulary for the concept they represent.

**Against Stage D's expectation (`svc.<name>` → alias / label / technology).** `alias` = the id, fine. `label` = the title, fine. `technology` = `none` on every service in every fixture I built and in this repo (G-8). The C4 `Container(...)` call the join key exists to fill can populate only two of its three code-sourced fields today.

**`--scaffold-svc` L3 "evidence" — is it useful for an LLM drafting responsibilities?** Barely. For the polyglot fixture:
```
svc.gateway → files: none        tables: none
svc.worker  → files: none        tables: none
svc.db      → files: V1__init.sql, V2__alter.sql     tables: none
```
Two of three services get literally `none / none`; the third gets two files only because the substring "db" happens to appear in `src/main/resources/db/migration/`. The `tables: none` line is emitted for the one service that owns all seven tables. Everything else in the block (image, ports, depends_on, env keys, source) is already in `-code`. So the scaffold contributes structure (`pending` sections, TODO markers, the correct `kb build` gate) but essentially **no new grounding**; a drafting agent must read the repo itself. The handover doc (§2, §4) says exactly this, and the honest label `(name-match heuristic; absence proves nothing)` is in the output — good — but the L2 the human curator actually reads shows only the TODO marker, so the caveat never reaches them.

---

## Criteria scorecard

| Criterion | Verdict | One line |
|---|---|---|
| **C12** deterministic, LLM-free | **met** | Byte-identical across runs and in place; no LLM, no network; ~7 s on a 10 k-file repo. |
| **C12** byte-identical *same commit, same platform* | **partially met** | Holds per-machine, but `struct.tree` depends on git-ignored dirs that exist only on some checkouts (G-3), and case-insensitive globbing changes *which artifacts are found* between Windows and Linux (G-12). |
| **C12** 7 extractors keyed by artifact kind | **partially met** | All 7 exist and fire, but the `services` extractor's documented workspace-`package.json` input is unimplemented (G-6) and `deps` drops every optional-dependency group (G-5). |
| **C12** exit 1 when only `tree` detects | **met** | Verified; keys off produced sections, not `detect()`; nothing written. |
| **C12** integrations = keys only, never values | **met** | Zero leaks across mapping / list / YAML-mangled / k8s / OpenAPI-userinfo attacks. |
| **C12** only `.env.example`/`.sample`/`.template`, never `.env` | **met** | A value present only in `.env` is provably absent from the output. |
| **C12** SQLite only via explicit `--db` | **met** | A committed `.sqlite` is invisible without `--db`; `--db` works, label is host-independent. |
| **C12** `dirty_tree` warning | **met** | Fires on an uncommitted edit; `revision`/`ingested` from HEAD, never wall-clock. |
| **C12** `-code` auto-mergeable / `-svc` never | **partially met** | `-svc` is well protected in both directions; but `-code` is auto-merge-safe only if the tool is pinned, and it is not (G-9) — and the reservation is not enforced against a human doc already sitting at `<repo>-code` (G-1). |
| **C12** *accuracy of the emitted document* | **not met** | On the framework's own repo: wrong `cmd.lint`, wrong `cmd.run`, no `gate.sh`, `image ``` `` for `svc.hub`, 20 missing deps, 86 % tree noise; on the fixture: a fabricated `users` table (G-4). |
| **C2** four layers, L2 condensed vs L3 | **not met (for `-code`)** | L2 is *larger* than L3 in 6/7 sections; the "no invention" rule is broken by the merged `users` table (G-4) and by "tracked files" (G-3). |
| **C2** tables never described/transcribed into prose | **met** | Tables are rendered as tables; no prose transcription anywhere. |
| **C3** 300–5 000 tokens per unit | **not met** | 6/7 sections below 300; `struct.tree` L3 = 29 052. |
| **C5** `kb build` gate | **met** | Passes on a clean `-code`; recounts tokens correctly (0/0 at ingest → real values after build); fails on `-svc` `pending`, passes with `--allow-pending`. |
| **C1** table integrity latch on `-code` | **n.a. / inert** | L3 contains no tables at all, so the L3→L2 check is vacuous; combined with F-B nothing validates `-code` tables (G-10). |
| **C16** human content preserved on re-run | **not met** | A curated document at `<repo>-code` is deleted without warning, and its index summary is kept on top of generated content (G-1). |
| Robustness (malformed / binary / huge / symlink) | **met** | 12 malformed manifests + 2 binaries → named warnings, no traceback, run continues; `node_modules` pruned pre-walk; `followlinks=False`. |

---

## Top 3 recommendations

1. **Fix the two accuracy bugs that make the document actively wrong before adding any feature.**
   (a) In `commands.py`, anchor `_classify` to the command's *executable token* rather than a substring of the whole line (`/dev/null` → `run`, `…:latest` → `test`, `pip install "ruff…"` → `lint` are all one-token-away fixes), pick the primary as the *last* matching CI line in a job rather than the first (the install step always precedes the real command), join `\`-continued lines before classifying, and add a shell-script reader so `scripts/gate.sh`-style entry points are findable. (b) In `schema.py`, key the table dict on `(source_dir, name)` — or at minimum refuse to apply an `ALTER` from directory A to a `CREATE TABLE` from directory B and warn instead of merging (G-4).

2. **Make `tree` honest and bounded, and close the `-code` clobber.**
   Consult `.gitignore` (or at minimum union `IGNORED_DIRS` with `git check-ignore`/`git ls-files`), cap `struct.tree` L3 by file count as well as depth, and change `tracked files` to `files` — or actually enumerate `git ls-files`, which would fix the wording, the noise, the cross-machine determinism gap and the 29 k-token section in one change. Separately, in `core.py:445`, refuse (exit 1) rather than delete when the destination holds a manifest this command did not write — the current guard tests for `-svc`-ness, when the property that matters is "someone else owns this directory" (G-1).

3. **Close the gap between README §7.12's contract table and the code, in whichever direction is cheaper.**
   Either implement workspace `package.json` as a `services` source and render optional-dependency / dev-dependency groups (both are small: `deps.py` already has a `Groups` abstraction and the renderer already handles multiple groups), or amend the spec, the README and the section-id contract table to say they are not read — and do the same for `Technology`, which the contract table promises unqualified while the Stage B handover already records it as always empty. Also pin `center-kb` in `kb-code.yml` (`pip install "center-kb==<version>"` or a `>=x,<x+1` range), for the same reason `_gate.yml` pins ruff: a document that is auto-merged must not change because the tool upgraded itself.
