# Phase 5 Stage B — `kb code-ingest`: cross-stack Codebase-as-Knowledge — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deterministic, LLM-free `kb code-ingest` that extracts cross-stack code structure — services/containers, dependencies with framework detection, build/test/lint commands, DB schema, external integrations, API surface, and the folder tree — into `.kb/<repo_id>-code/` in the existing 4-layer format, plus `--scaffold-svc` to seed the curated `.kb/<repo_id>-svc/` document, published to the hub on every merge by a scaffolded `kb-code.yml`.

**Architecture:** One new package `src/center_kb/codeingest/` — a `core.py` orchestrator/writer and seven extractors behind a two-method protocol — plus one Typer command. Extractors key on **artifact kind** (container manifest, dependency manifest, CI workflow, migration, API contract), never on programming language, so one set covers frontend and backend across project lines. `models.py`, `build.py`, `searchdb`, federation, MCP, and web are untouched: generated documents are ordinary 4-layer content.

**Tech Stack:** Python 3.11+, Typer, stdlib `json` / `tomllib` / `xml.etree.ElementTree` / `sqlite3` / `re`, PyYAML (already a core dependency — **no new dependency**), pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-19-dev-agent-design.md`

**Prerequisite:** `2026-08-19-dev-agent-stage-a.md` must be complete and released — this plan adds a row to the `DEV_TEMPLATES` map it created.

## Global Constraints

Copied verbatim from the spec; every task's requirements implicitly include this section.

- **Five MCP tools, unchanged.** `tests-gate/golden/mcp_tools.json` byte-identical; `tests-gate/regression/test_mcp_contract.py` green untouched (spec §3.1).
- **`models.py` is frozen** (spec §3.3). **`build.py` is frozen** (spec §3.7) — generated content satisfies its invariants by construction, never by relaxing the check.
- **Determinism** (spec §3.5): output is a pure function of the working tree. No wall-clock — `Manifest.ingested` = HEAD commit date. Sort sections by `(group, id)`, dependencies by name, tables by name; **preserve column order** (it carries meaning); sort keys when emitting YAML/JSON. Normalise path separators to `/` and line endings to `\n` — both mandatory because this repo supports Windows. Two runs on the same tree must produce byte-identical files (tested).
- **`kb build` must PASS without `--allow-pending`** on the generated document: every section has a non-empty `summary`, no `TODO:summarize` marker, and **no pipe table in L3 that is not verbatim in L2** — so all L3 detail goes in fenced code blocks (spec §3.7).
- **Never a secret channel** (spec §3.11): read only `.env.example` / `.env.sample` / `.env.template`, emit **keys only, never values**, never read a real `.env`. SQLite only via explicit `--db`.
- **Cross-stack by artifact kind, never by language** (spec §3.12).
- **Zero-detection rule** (spec §7): exit 1 when **no extractor other than `tree`** detected anything.
- Hermetic tests: no network, no live hub, no LLM. SQLite fixtures are generated at test time, never committed as binaries.
- Windows dev box: `uv run pytest`; `uv run ruff check <touched files>` only.
- Estimated effort: B1 ≈ 1 d, B2 ≈ 0.5 d, B3 ≈ 1.25 d, B4 ≈ 1.25 d, B5 ≈ 1 d, B6 ≈ 1.5 d, B7 ≈ 0.75 d, B8 ≈ 1 d, B9 ≈ 0.5 d, B10 ≈ 0.5 d — **≈ 8.75 dev-days** (spec §14 range 8–8.75).

## File Structure

| File | Responsibility |
|---|---|
| `src/center_kb/codeingest/__init__.py` | public surface: `run()`, `CodeIngestOptions`, `CodeIngestReport` |
| `src/center_kb/codeingest/core.py` | `CodeSection`, `ExtractResult`, `Extractor` protocol, orchestration, file/manifest/index writing, `--scaffold-svc`, stale-risk + orphan detection |
| `src/center_kb/codeingest/extractors/__init__.py` | `ALL_EXTRACTORS` registry, in deterministic order |
| `src/center_kb/codeingest/extractors/tree.py` | `struct.tree` |
| `src/center_kb/codeingest/extractors/deps.py` | `dep.<ecosystem>` + the framework lookup table |
| `src/center_kb/codeingest/extractors/services.py` | `svc.<name>` |
| `src/center_kb/codeingest/extractors/commands.py` | `cmd.build` / `cmd.test` / `cmd.lint` / `cmd.run` |
| `src/center_kb/codeingest/extractors/schema.py` | `db.<table>` |
| `src/center_kb/codeingest/extractors/integrations.py` | `int.<name>` |
| `src/center_kb/codeingest/extractors/api.py` | `api.<tag>` |
| `src/center_kb/cli.py` | `kb code-ingest` — thin, delegates to `codeingest.run()` |
| `src/center_kb/templates/init/kb-code.yml` | CI: publish on push-to-default, validate on PR |
| `tests/fixtures_coderepo.py` | the multi-stack fixture repo builder, shared by all Stage B tests |
| `tests/test_codeingest_core.py` | protocol, ordering, writer, determinism, build-compat |
| `tests/test_codeingest_extractors.py` | one test class per extractor |
| `tests/test_codeingest_scaffold.py` | `--scaffold-svc`, stale-risk, orphans, the build gate |
| `tests/test_cli_codeingest.py` | flags, `--json`, index tags, token preservation, exit codes |

---

## Task B1: `codeingest` core — protocol, orchestration, writer

**Files:**
- Create: `src/center_kb/codeingest/__init__.py`
- Create: `src/center_kb/codeingest/core.py`
- Create: `src/center_kb/codeingest/extractors/__init__.py`
- Create: `tests/test_codeingest_core.py`

**Interfaces:**
- Consumes: `center_kb.models` (`Manifest`, `SectionEntry`, `KBIndex`, `IndexEntry`, `load_yaml_model`, `save_yaml_model`), `center_kb.gitio` (HEAD commit + commit date + dirty check), `center_kb.config` (`effective_repo_id`).
- Produces, for every later task:

```python
@dataclass(frozen=True)
class CodeSection:
    id: str          # e.g. "svc.airspace-service" — no whitespace (mdutils._HEADING_RE)
    title: str       # e.g. "airspace-service"
    summary: str     # 1-2 deterministic sentences; MUST be non-empty (build invariant)
    group: str       # output file stem, e.g. "services" -> services.md + services.raw.md
    l2_md: str       # body under the "## <id> <title>" heading in the L2 file
    l3_md: str       # body under the same heading in the L3 file; fenced blocks only

@dataclass
class ExtractResult:
    sections: list[CodeSection] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class CodeIngestOptions:
    repo_root: Path
    kb_dir: Path
    doc_id: str
    repo_id: str
    db_paths: tuple[Path, ...] = ()
    tags: tuple[str, ...] = ()
    scaffold_svc: bool = False

@dataclass
class CodeIngestReport:
    doc_id: str
    sections_by_extractor: dict[str, int] = field(default_factory=dict)
    files_written: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    detected: list[str] = field(default_factory=list)       # extractor names that fired
    scaffolded: list[str] = field(default_factory=list)     # new -svc section ids
    stale_risk: list[str] = field(default_factory=list)     # -svc ids whose evidence moved
    orphans: list[str] = field(default_factory=list)        # -svc ids with no -code peer
    dirty_tree: bool = False

class Extractor(Protocol):
    name: str
    def detect(self, root: Path) -> bool: ...
    def extract(self, root: Path, opts: CodeIngestOptions) -> ExtractResult: ...

def run(opts: CodeIngestOptions) -> CodeIngestReport: ...
class CodeIngestError(Exception): ...        # raised on zero detection
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_codeingest_core.py`:

```python
from pathlib import Path

import pytest

from center_kb import models
from center_kb.build import build_kb
from center_kb.codeingest import core


class _StubExtractor:
    """Two sections in two groups, deliberately out of sorted order."""

    name = "stub"

    def detect(self, root: Path) -> bool:
        return True

    def extract(self, root: Path, opts) -> core.ExtractResult:
        return core.ExtractResult(
            sections=[
                core.CodeSection(
                    id="svc.beta", title="beta", summary="Service beta.",
                    group="services", l2_md="Beta service.\n",
                    l3_md="```yaml\nimage: beta:1\n```\n",
                ),
                core.CodeSection(
                    id="svc.alpha", title="alpha", summary="Service alpha.",
                    group="services", l2_md="Alpha service.\n",
                    l3_md="```yaml\nimage: alpha:1\n```\n",
                ),
                core.CodeSection(
                    id="dep.python", title="Python dependencies",
                    summary="3 direct Python dependencies.",
                    group="deps", l2_md="typer, pydantic, pyyaml\n",
                    l3_md="```\ntyper>=0.12\n```\n",
                ),
            ]
        )


def _opts(tmp_path: Path, **kw):
    return core.CodeIngestOptions(
        repo_root=tmp_path, kb_dir=tmp_path / ".kb",
        doc_id="demo-code", repo_id="demo", **kw
    )


def test_sections_are_sorted_by_group_then_id(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    l2 = (tmp_path / ".kb" / "demo-code" / "services.md").read_text(encoding="utf-8")
    assert l2.index("## svc.alpha") < l2.index("## svc.beta")


def test_one_md_and_raw_md_pair_per_group(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    report = core.run(_opts(tmp_path))
    doc = tmp_path / ".kb" / "demo-code"
    for stem in ("services", "deps"):
        assert (doc / f"{stem}.md").is_file()
        assert (doc / f"{stem}.raw.md").is_file()
    assert sorted(report.files_written) == sorted(
        ["_manifest.yaml", "deps.md", "deps.raw.md", "services.md", "services.raw.md"]
    )


def test_manifest_records_commit_and_commit_date_not_wall_clock(tmp_path, monkeypatch, run_git):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    run_git(tmp_path, "init")
    run_git(tmp_path, "add", "-A")
    run_git(tmp_path, "commit", "-m", "c1")
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    m = models.load_yaml_model(
        tmp_path / ".kb" / "demo-code" / "_manifest.yaml", models.Manifest
    )
    head = run_git(tmp_path, "rev-parse", "HEAD")
    assert m.revision == head[:7]
    assert m.source_sha256 == head
    iso = run_git(tmp_path, "show", "-s", "--format=%cs", "HEAD")
    assert m.ingested.isoformat() == iso
    assert all(s.status == "summarized" and s.summary for s in m.sections)


def test_index_entry_carries_code_and_generated_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path, tags=("team-x",)))
    index = models.load_yaml_model(tmp_path / ".kb" / "index.yaml", models.KBIndex)
    entry = next(d for d in index.docs if d.id == "demo-code")
    assert entry.tags == ["code", "generated", "team-x"]


def test_rerun_preserves_user_added_index_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    index_path = tmp_path / ".kb" / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    next(d for d in index.docs if d.id == "demo-code").tags.append("hand-added")
    models.save_yaml_model(index_path, index)
    core.run(_opts(tmp_path))
    index = models.load_yaml_model(index_path, models.KBIndex)
    assert "hand-added" in next(d for d in index.docs if d.id == "demo-code").tags


def test_rerun_preserves_per_section_tokens_written_by_build(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    assert build_kb(tmp_path / ".kb").ok
    path = tmp_path / ".kb" / "demo-code" / "_manifest.yaml"
    before = {s.id: s.tokens.l2 for s in
              models.load_yaml_model(path, models.Manifest).sections}
    assert all(v > 0 for v in before.values())
    core.run(_opts(tmp_path))
    after = {s.id: s.tokens.l2 for s in
             models.load_yaml_model(path, models.Manifest).sections}
    assert after == before


def test_two_runs_produce_byte_identical_trees(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    doc = tmp_path / ".kb" / "demo-code"
    first = {p.name: p.read_bytes() for p in sorted(doc.iterdir())}
    core.run(_opts(tmp_path))
    second = {p.name: p.read_bytes() for p in sorted(doc.iterdir())}
    assert first == second


def test_files_use_lf_endings_only(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    for p in (tmp_path / ".kb" / "demo-code").iterdir():
        assert b"\r\n" not in p.read_bytes(), p.name


def test_generated_document_builds_clean_without_allow_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    report = build_kb(tmp_path / ".kb")
    assert report.errors == [], report.errors
    assert report.ok


def test_zero_detection_beyond_tree_raises(tmp_path, monkeypatch):
    class _TreeOnly:
        name = "tree"

        def detect(self, root):
            return True

        def extract(self, root, opts):
            return core.ExtractResult(sections=[
                core.CodeSection(id="struct.tree", title="Repository tree",
                                 summary="Folder layout.", group="structure",
                                 l2_md="- src/\n", l3_md="```\nsrc/\n```\n")
            ])

    class _Silent:
        name = "deps"

        def detect(self, root):
            return False

        def extract(self, root, opts):
            raise AssertionError("must not be called when detect() is False")

    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_TreeOnly(), _Silent()])
    with pytest.raises(core.CodeIngestError):
        core.run(_opts(tmp_path))


def test_extractor_warnings_reach_the_report(tmp_path, monkeypatch):
    class _Noisy(_StubExtractor):
        name = "noisy"

        def extract(self, root, opts):
            result = super().extract(root, opts)
            result.warnings.append("could not parse pom.xml: mismatched tag")
            return result

    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_Noisy()])
    report = core.run(_opts(tmp_path))
    assert any("pom.xml" in w for w in report.warnings)


def test_dirty_tree_is_reported(tmp_path, monkeypatch, run_git):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    run_git(tmp_path, "init")
    run_git(tmp_path, "add", "-A")
    run_git(tmp_path, "commit", "-m", "c1")
    (tmp_path / "f.txt").write_text("y", encoding="utf-8")
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    assert core.run(_opts(tmp_path)).dirty_tree is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_codeingest_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.codeingest'`.

- [ ] **Step 3: Write `core.py` — dataclasses and protocol**

Create `src/center_kb/codeingest/core.py` with the dataclasses and `Extractor` protocol exactly as given in **Interfaces** above, plus `class CodeIngestError(Exception)`. Import `ALL_EXTRACTORS` from `.extractors` and re-bind it as a module-level name in `core` (the tests monkeypatch `core.ALL_EXTRACTORS`, so `run()` must read the module attribute, not a closure).

- [ ] **Step 4: Write the git helpers**

In `core.py`, three small functions using `subprocess` through the existing `center_kb.gitio` conventions (fall back gracefully when the tree is not a git repo, since a scratch directory is a valid target):

- `_head_commit(root) -> str` — `git rev-parse HEAD`, `""` when unavailable.
- `_head_date(root) -> datetime.date | None` — `git show -s --format=%cs HEAD`, parsed with `date.fromisoformat`; `None` when unavailable. **Never `date.today()`.**
- `_is_dirty(root) -> bool` — `git status --porcelain` non-empty.

- [ ] **Step 5: Write the renderer**

In `core.py`, `_render_group(sections, level, banner) -> str` where `level` is `"l2"` or `"l3"`:

- H1: `# <doc_id>` followed by a blank line, then the banner line, then a blank line.
- For each section in the already-sorted order: `## <id> <title>`, blank line, the body (`l2_md` or `l3_md`), then a blank line.
- Join with `\n`, ensure exactly one trailing `\n`, and write with `encoding="utf-8", newline="\n"`.

Banner for the generated document: `> Generated by kb code-ingest at <short-commit> — do not edit by hand.` (use `unknown-commit` when there is no git).

- [ ] **Step 6: Write `run()`**

Order of operations:

1. Resolve options; `report = CodeIngestReport(doc_id=opts.doc_id)`; `report.dirty_tree = _is_dirty(...)`.
2. For each extractor in `ALL_EXTRACTORS`: call `detect()`; skip when False (never call `extract()` on a non-detecting extractor — a test asserts this); otherwise record the name in `report.detected`, run `extract()`, collect sections and warnings, and record the per-extractor count.
3. If `report.detected` contains nothing besides `"tree"`, raise `CodeIngestError` naming the artifact kinds that were looked for.
4. Sort all sections by `(group, id)`. Reject duplicate ids with a `CodeIngestError` naming both producers — two extractors claiming one id would make `slice_section` ambiguous.
5. Read the existing `_manifest.yaml` when present and build `{section_id: SectionTokens}` so tokens survive the rewrite (spec §6.4).
6. Write one `<group>.md` + `<group>.raw.md` pair per group.
7. Build the `Manifest`: `id=doc_id`, `title=f"{repo_id} — code knowledge"`, `revision=<short commit>`, `source_sha256=<full commit>`, `ingested=<commit date>`, and one `SectionEntry(id, title, summary, status="summarized", file=group, tokens=<preserved or default>)` per section, in sorted order. Save with `save_yaml_model`.
8. Upsert the `index.yaml` entry: create `.kb/index.yaml` from an empty `KBIndex` when missing; set `title`/`revision`/`summary` (`f"Generated code knowledge for the {repo_id} repository."`); set `tags` to `["code", "generated"]` plus `opts.tags` plus any pre-existing tags not in that set, preserving first-seen order.
9. When `opts.scaffold_svc`, call `scaffold_svc(opts, sections, report)` — implemented in Task B8.
10. Return the report.

- [ ] **Step 7: Write the extractor registry**

Create `src/center_kb/codeingest/extractors/__init__.py` with `ALL_EXTRACTORS: list = []` for now — Tasks B2–B7 each append their own entry. Keep the list in a fixed, documented order (`services, deps, commands, tree, schema, integrations, api`) so reports read the same way every run.

- [ ] **Step 8: Write `__init__.py`**

Create `src/center_kb/codeingest/__init__.py` re-exporting `run`, `CodeIngestOptions`, `CodeIngestReport`, `CodeIngestError`.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/test_codeingest_core.py -v`
Expected: PASS (12 tests).

- [ ] **Step 10: Lint and commit**

```bash
uv run ruff check src/center_kb/codeingest tests/test_codeingest_core.py
git add src/center_kb/codeingest tests/test_codeingest_core.py
git commit -m "feat: codeingest core — protocol, deterministic writer, manifest/index upsert (phase 5B)"
```

---

## Task B2: the multi-stack fixture repo + `tree` extractor

**Files:**
- Create: `tests/fixtures_coderepo.py`
- Create: `src/center_kb/codeingest/extractors/tree.py`
- Modify: `src/center_kb/codeingest/extractors/__init__.py`
- Create: `tests/test_codeingest_extractors.py`

**Interfaces:**
- Consumes: `CodeSection`, `ExtractResult` from B1.
- Produces: `build_code_repo(root: Path) -> Path` — the fixture every later extractor task extends, and `TreeExtractor` (`name = "tree"`, always detects).

- [ ] **Step 1: Write the fixture builder**

Create `tests/fixtures_coderepo.py`. One function that writes a repo covering several stacks at once; later tasks add to it rather than creating new fixtures:

```python
from pathlib import Path


def build_code_repo(root: Path) -> Path:
    """A deliberately multi-stack repo: Python + Node/React + Java + Docker +
    migrations + OpenAPI + CI. Every extractor finds something here."""
    (root / "src" / "airspace").mkdir(parents=True)
    (root / "src" / "airspace" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "airspace" / "service.py").write_text(
        '"""Airspace approval service."""\n', encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "airspace"\nversion = "1.0.0"\n'
        'dependencies = ["fastapi>=0.110", "pydantic>=2.7"]\n'
        "\n[tool.pytest.ini_options]\naddopts = \"-q\"\n",
        encoding="utf-8",
    )
    (root / "web").mkdir()
    (root / "web" / "package.json").write_text(
        '{\n  "name": "dashboard",\n  "dependencies": {"react": "^18.2.0"},\n'
        '  "devDependencies": {"eslint": "^9.0.0"},\n'
        '  "scripts": {"build": "vite build", "test": "vitest run",\n'
        '              "lint": "eslint .", "start": "vite"}\n}\n',
        encoding="utf-8",
    )
    (root / "pom.xml").write_text(
        '<?xml version="1.0"?>\n<project><dependencies>'
        "<dependency><groupId>org.springframework.boot</groupId>"
        "<artifactId>spring-boot-starter-web</artifactId>"
        "<version>3.2.0</version></dependency>"
        "</dependencies></project>\n",
        encoding="utf-8",
    )
    (root / "docker-compose.yml").write_text(
        "services:\n"
        "  airspace-service:\n"
        "    image: airspace:1.0\n"
        '    ports: ["8080:8080"]\n'
        "    depends_on: [postgres]\n"
        "    environment:\n"
        "      AIRSPACE_DB_URL: postgres://db/airspace\n"
        "      KAFKA_BROKER_URL: kafka:9092\n"
        "  postgres:\n"
        "    image: postgres:16\n"
        '    ports: ["5432:5432"]\n',
        encoding="utf-8",
    )
    (root / "Dockerfile").write_text(
        "FROM python:3.12-slim\nEXPOSE 8080\nCMD [\"uvicorn\", \"airspace:app\"]\n",
        encoding="utf-8",
    )
    (root / ".env.example").write_text(
        "AIRSPACE_DB_URL=postgres://localhost/airspace\n"
        "KAFKA_BROKER_URL=localhost:9092\n"
        "S3_BUCKET=airspace-assets\n"
        "SECRET_KEY=do-not-ship-this-value\n",
        encoding="utf-8",
    )
    migrations = root / "db" / "migration"
    migrations.mkdir(parents=True)
    (migrations / "V1__create_airspace.sql").write_text(
        "CREATE TABLE restrictive_airspace (\n"
        "  id BIGSERIAL PRIMARY KEY,\n"
        "  designation VARCHAR(20) NOT NULL,\n"
        "  airspace_type CHAR(1) NOT NULL\n"
        ");\n",
        encoding="utf-8",
    )
    (migrations / "V2__add_effective_date.sql").write_text(
        "ALTER TABLE restrictive_airspace ADD COLUMN effective_date DATE;\n",
        encoding="utf-8",
    )
    (root / "openapi.yaml").write_text(
        "openapi: 3.0.0\n"
        "servers:\n  - url: https://api.example.com/v1\n"
        "paths:\n"
        "  /airspace:\n"
        "    get:\n      tags: [airspace]\n      summary: List airspace\n"
        "    post:\n      tags: [airspace]\n      summary: Create airspace\n",
        encoding="utf-8",
    )
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "ci.yml").write_text(
        "on: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: pip install -e .\n"
        "      - run: pytest -q --cov=airspace\n"
        "      - run: ruff check src\n",
        encoding="utf-8",
    )
    # Noise that must be ignored by the tree extractor.
    (root / "node_modules" / "left-pad").mkdir(parents=True)
    (root / "node_modules" / "left-pad" / "index.js").write_text("", encoding="utf-8")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    return root
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_codeingest_extractors.py`:

```python
from pathlib import Path

import pytest

from center_kb.codeingest import core
from center_kb.codeingest.extractors import tree as tree_ext
from tests.fixtures_coderepo import build_code_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return build_code_repo(tmp_path)


def _opts(root: Path, **kw):
    return core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb",
        doc_id="demo-code", repo_id="demo", **kw
    )


def _by_id(result: core.ExtractResult) -> dict[str, core.CodeSection]:
    return {s.id: s for s in result.sections}


class TestTreeExtractor:
    def test_always_detects(self, repo):
        assert tree_ext.TreeExtractor().detect(repo) is True

    def test_emits_a_single_struct_tree_section(self, repo):
        sections = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))
        assert list(sections) == ["struct.tree"]
        assert sections["struct.tree"].group == "structure"
        assert sections["struct.tree"].summary

    def test_lists_real_directories_and_ignores_noise(self, repo):
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        body = s.l2_md + s.l3_md
        assert "src/airspace" in body
        assert "web" in body
        assert "node_modules" not in body
        assert "__pycache__" not in body

    def test_l3_has_no_pipe_table(self, repo):
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        assert "|" not in s.l3_md
        assert s.l3_md.lstrip().startswith("```")

    def test_paths_use_forward_slashes(self, repo):
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        assert "\\" not in s.l2_md + s.l3_md
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_codeingest_extractors.py -v`
Expected: FAIL — `ImportError: cannot import name 'tree'`.

- [ ] **Step 4: Write the `tree` extractor**

Create `src/center_kb/codeingest/extractors/tree.py`:

- `IGNORED_DIRS = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", "target", "bin", "obj", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".idea", ".vscode", ".kb"})` — the exact set; `.kb` is excluded so the KB never describes itself.
- `detect()` returns `True` unconditionally (documented in a comment: it is the reason the zero-detection rule counts extractors *other than* `tree`).
- `extract()` walks the tree with `os.walk`, pruning `IGNORED_DIRS` in place; renders paths relative to `root` with `as_posix()`; sorts every directory listing.
- **L2**: directory list to depth 2 as a Markdown bullet list, plus a detected-entry-points bullet list (any of `main.py`, `app.py`, `manage.py`, `index.js`, `index.ts`, `main.go`, `Program.cs`, `Application.java`, plus `[project.scripts]` names when `pyproject.toml` parses).
- **L3**: the full tree to depth 4 inside a plain fenced block. No pipe tables anywhere in L3.
- `summary`: `f"Repository layout: {n_dirs} directories, {n_files} tracked files, entry points: {', '.join(entry_points) or 'none detected'}."`
- Register `TreeExtractor()` in `extractors/__init__.py`'s `ALL_EXTRACTORS`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_codeingest_extractors.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/center_kb/codeingest tests/fixtures_coderepo.py tests/test_codeingest_extractors.py
git add src/center_kb/codeingest tests/fixtures_coderepo.py tests/test_codeingest_extractors.py
git commit -m "feat: tree extractor + the multi-stack code fixture (phase 5B)"
```

---

## Task B3: `deps` extractor + framework detection

**Files:**
- Create: `src/center_kb/codeingest/extractors/deps.py`
- Modify: `src/center_kb/codeingest/extractors/__init__.py`
- Modify: `tests/test_codeingest_extractors.py`

**Interfaces:**
- Consumes: `CodeSection`, `ExtractResult`.
- Produces: `DepsExtractor`, and `detect_frameworks(names: Iterable[str]) -> list[str]` — reused by Task B4 to fill a service's `technology`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_codeingest_extractors.py`:

```python
from center_kb.codeingest.extractors import deps as deps_ext


class TestDepsExtractor:
    def test_detects_when_any_manifest_exists(self, repo, tmp_path):
        assert deps_ext.DepsExtractor().detect(repo) is True
        empty = tmp_path / "empty"
        empty.mkdir()
        assert deps_ext.DepsExtractor().detect(empty) is False

    def test_one_section_per_ecosystem(self, repo):
        sections = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))
        assert set(sections) == {"dep.python", "dep.node", "dep.java"}
        for s in sections.values():
            assert s.group == "deps"
            assert s.summary

    def test_python_deps_are_listed_with_constraints(self, repo):
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.python"]
        assert "fastapi" in s.l2_md
        assert "fastapi>=0.110" in s.l3_md

    def test_node_separates_direct_from_dev_dependencies(self, repo):
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.node"]
        assert "react" in s.l2_md
        assert "eslint" in s.l3_md

    def test_java_deps_come_from_pom_xml(self, repo):
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.java"]
        assert "spring-boot-starter-web" in s.l3_md

    def test_frameworks_are_detected_for_frontend_and_backend(self, repo):
        sections = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))
        assert "FastAPI" in sections["dep.python"].l2_md
        assert "React" in sections["dep.node"].l2_md
        assert "Spring Boot" in sections["dep.java"].l2_md

    def test_dependencies_are_sorted_deterministically(self, repo):
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.python"]
        assert s.l3_md.index("fastapi") < s.l3_md.index("pydantic")

    def test_l3_has_no_pipe_table(self, repo):
        for s in deps_ext.DepsExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id

    def test_unparseable_manifest_warns_and_does_not_crash(self, repo):
        (repo / "pom.xml").write_text("<project><dependencies>", encoding="utf-8")
        result = deps_ext.DepsExtractor().extract(repo, _opts(repo))
        assert any("pom.xml" in w for w in result.warnings)
        assert {"dep.python", "dep.node"} <= {s.id for s in result.sections}


class TestFrameworkLookup:
    @pytest.mark.parametrize(
        "dep,expected",
        [
            ("spring-boot-starter-web", "Spring Boot"),
            ("Microsoft.AspNetCore.App", "ASP.NET Core"),
            ("fastapi", "FastAPI"),
            ("django", "Django"),
            ("flask", "Flask"),
            ("react", "React"),
            ("next", "Next.js"),
            ("@angular/core", "Angular"),
            ("vue", "Vue"),
        ],
    )
    def test_known_frameworks_map_to_labels(self, dep, expected):
        assert expected in deps_ext.detect_frameworks([dep])

    def test_unknown_dependency_yields_nothing(self):
        assert deps_ext.detect_frameworks(["left-pad"]) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_codeingest_extractors.py -k Deps -v`
Expected: FAIL — `ImportError: cannot import name 'deps'`.

- [ ] **Step 3: Write the framework lookup table**

In `deps.py`, an explicit prefix→label table (matched case-insensitively against the dependency name; longest prefix wins so `spring-boot-starter-web` cannot be shadowed):

```python
FRAMEWORKS: tuple[tuple[str, str], ...] = (
    ("spring-boot", "Spring Boot"),
    ("quarkus", "Quarkus"),
    ("micronaut", "Micronaut"),
    ("microsoft.aspnetcore", "ASP.NET Core"),
    ("microsoft.entityframeworkcore", "Entity Framework Core"),
    ("fastapi", "FastAPI"),
    ("django", "Django"),
    ("flask", "Flask"),
    ("sqlalchemy", "SQLAlchemy"),
    ("celery", "Celery"),
    ("@angular/core", "Angular"),
    ("@nestjs/core", "NestJS"),
    ("next", "Next.js"),
    ("nuxt", "Nuxt"),
    ("react", "React"),
    ("vue", "Vue"),
    ("svelte", "Svelte"),
    ("express", "Express"),
    ("gin-gonic/gin", "Gin"),
    ("laravel/framework", "Laravel"),
    ("symfony/framework-bundle", "Symfony"),
)


def detect_frameworks(names):
    """Deterministic: sorted, de-duplicated labels."""
```

- [ ] **Step 4: Write the per-ecosystem readers**

Each returns `(list[tuple[name, constraint]], list[warning])` and never raises:

- **python** — `pyproject.toml` via `tomllib` (`project.dependencies`, PEP 508 split on the first of `><=!~[;`), `setup.cfg` via `configparser`, and `requirements*.txt` line-wise (skip blanks, `#`, `-r`, `-e`).
- **node** — every `package.json` found at depth ≤ 2 (so the fixture's `web/package.json` is found), reading `dependencies` and `devDependencies` separately.
- **java** — `pom.xml` via `xml.etree.ElementTree` (namespace-agnostic: match on tag `endswith("dependency")`), plus `build.gradle`/`build.gradle.kts` via `re.findall(r"""(?:implementation|api|compileOnly|testImplementation)\s*[('"]+([^'")]+)""")` — regex by design, not a DSL parse.
- **dotnet** — `*.csproj` via `xml.etree` (`PackageReference` `Include`/`Version`).
- **go** — `go.mod`, the `require` block plus single-line `require`.
- **php** — `composer.json` `require` / `require-dev`.

Ecosystem section ids: `dep.python`, `dep.node`, `dep.java`, `dep.dotnet`, `dep.go`, `dep.php`. Emit a section only when that ecosystem produced at least one dependency; a manifest that exists but yields nothing is a warning.

- [ ] **Step 5: Write the section rendering**

- **L2**: `**Frameworks detected:** <labels or none>` then a pipe table `| Package | Constraint |` of direct dependencies (pipe tables are allowed in L2).
- **L3**: a fenced block per group (`direct`, `dev`) listing `name constraint` one per line, sorted by name. **No pipe tables.**
- `summary`: `f"{n} direct {ecosystem} dependencies" + (f"; frameworks: {', '.join(labels)}." if labels else ".")`

Register `DepsExtractor()` in `ALL_EXTRACTORS` after `services`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_codeingest_extractors.py -v`
Expected: PASS (Tree + Deps + FrameworkLookup, 25 tests).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/center_kb/codeingest tests/test_codeingest_extractors.py
git add src/center_kb/codeingest tests/test_codeingest_extractors.py
git commit -m "feat: deps extractor across 6 ecosystems + framework detection (phase 5B)"
```

---

## Task B4: `services` extractor

**Files:**
- Create: `src/center_kb/codeingest/extractors/services.py`
- Modify: `src/center_kb/codeingest/extractors/__init__.py`
- Modify: `tests/test_codeingest_extractors.py`

**Interfaces:**
- Consumes: `detect_frameworks()` from B3 (to label a service's technology).
- Produces: `ServicesExtractor` emitting `svc.<name>` — **the join key** Stage C's `-svc` document reuses and Stage C's `kb svc note` validates against.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_codeingest_extractors.py`:

```python
from center_kb.codeingest.extractors import services as svc_ext


class TestServicesExtractor:
    def test_detects_compose_dockerfile_or_k8s(self, repo, tmp_path):
        assert svc_ext.ServicesExtractor().detect(repo) is True
        empty = tmp_path / "empty2"
        empty.mkdir()
        assert svc_ext.ServicesExtractor().detect(empty) is False

    def test_one_section_per_compose_service(self, repo):
        sections = _by_id(svc_ext.ServicesExtractor().extract(repo, _opts(repo)))
        assert "svc.airspace-service" in sections
        assert "svc.postgres" in sections
        for s in sections.values():
            assert s.group == "services"

    def test_section_ids_have_no_whitespace(self, repo):
        for s in svc_ext.ServicesExtractor().extract(repo, _opts(repo)).sections:
            assert " " not in s.id and "\t" not in s.id

    def test_records_image_ports_and_depends_on(self, repo):
        s = _by_id(svc_ext.ServicesExtractor().extract(repo, _opts(repo)))["svc.airspace-service"]
        body = s.l2_md + s.l3_md
        assert "airspace:1.0" in body
        assert "8080" in body
        assert "postgres" in body

    def test_environment_keys_only_never_values(self, repo):
        s = _by_id(svc_ext.ServicesExtractor().extract(repo, _opts(repo)))["svc.airspace-service"]
        body = s.l2_md + s.l3_md
        assert "KAFKA_BROKER_URL" in body
        assert "kafka:9092" not in body
        assert "postgres://db/airspace" not in body

    def test_dockerfile_only_repo_yields_one_service_named_after_the_repo(self, tmp_path):
        root = tmp_path / "solo"
        root.mkdir()
        (root / "Dockerfile").write_text("FROM node:20\nEXPOSE 3000\n", encoding="utf-8")
        sections = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))
        assert "svc.demo" in sections          # opts.repo_id == "demo"
        assert "3000" in sections["svc.demo"].l2_md

    def test_k8s_deployment_is_picked_up(self, tmp_path):
        root = tmp_path / "k8s"
        (root / "deploy").mkdir(parents=True)
        (root / "deploy" / "app.yaml").write_text(
            "apiVersion: apps/v1\nkind: Deployment\n"
            "metadata:\n  name: notify-service\n"
            "spec:\n  template:\n    spec:\n      containers:\n"
            "        - name: notify\n          image: notify:2.1\n"
            "          ports:\n            - containerPort: 9000\n",
            encoding="utf-8",
        )
        sections = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))
        assert "svc.notify-service" in sections
        assert "notify:2.1" in sections["svc.notify-service"].l3_md

    def test_services_are_sorted_by_name(self, repo):
        ids = [s.id for s in svc_ext.ServicesExtractor().extract(repo, _opts(repo)).sections]
        assert ids == sorted(ids)

    def test_l3_has_no_pipe_table(self, repo):
        for s in svc_ext.ServicesExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id

    def test_malformed_compose_warns_and_does_not_crash(self, tmp_path):
        root = tmp_path / "bad"
        root.mkdir()
        (root / "docker-compose.yml").write_text("services: [", encoding="utf-8")
        (root / "Dockerfile").write_text("FROM alpine\n", encoding="utf-8")
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        assert any("docker-compose.yml" in w for w in result.warnings)
        assert result.sections  # the Dockerfile path still produced a service
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_codeingest_extractors.py -k Services -v`
Expected: FAIL — `ImportError: cannot import name 'services'`.

- [ ] **Step 3: Write the source readers**

Four readers, each returning `(list[ServiceRecord], list[warning])` where `ServiceRecord` is a local dataclass with `name`, `image`, `ports: list[str]`, `depends_on: list[str]`, `env_keys: list[str]`, `source: str` (the file it came from):

- **compose** — every `docker-compose*.y*ml` at the root, via `yaml.safe_load`; iterate `services` (sorted); `ports` normalised to strings; `environment` accepted in both mapping and `KEY=value` list form but **only the key is kept** (spec §3.11).
- **dockerfile** — a root `Dockerfile` with no compose file present yields one service named `opts.repo_id`; parse `EXPOSE` for ports and `FROM` for the base image.
- **k8s** — `*.y*ml` under any directory, `yaml.safe_load_all` (multi-doc); take documents whose `kind` is `Deployment`, `StatefulSet`, or `Service`; name from `metadata.name`; image and `containerPort` from the first container.
- **sln** — a root `*.sln`, one candidate container per `Project(...)` line, name from the project name.

De-duplicate by name, preferring the compose record (it is closest to what actually runs), and note the discarded source in a warning only when the images disagree.

- [ ] **Step 4: Write the section rendering**

- `id = f"svc.{name}"`, `title = name`. Names are slugified to remove whitespace (`mdutils._HEADING_RE` requires `\S+`).
- **L2**: a one-line description (`f"Container `{name}` — image `{image}`."`) then a pipe table `| Property | Value |` with rows Image, Ports, Depends on, Technology (from `detect_frameworks` over the ecosystem deps when the service maps to a code directory, otherwise from the image name), Env keys (comma-joined **keys**), Source.
- **L3**: a fenced `yaml` block reproducing the extracted record (name, image, ports, depends_on, env_keys — keys only), plus a plain fenced block naming the source file.
- `summary`: `f"Container {name} from {source}: image {image}, ports {ports or 'none'}, depends on {depends_on or 'nothing'}."`

Register `ServicesExtractor()` first in `ALL_EXTRACTORS`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_codeingest_extractors.py -v`
Expected: PASS (35 tests).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/center_kb/codeingest tests/test_codeingest_extractors.py
git add src/center_kb/codeingest tests/test_codeingest_extractors.py
git commit -m "feat: services extractor — compose, Dockerfile, k8s, sln; env keys only (phase 5B)"
```

---

## Task B5: `commands` extractor

**Files:**
- Create: `src/center_kb/codeingest/extractors/commands.py`
- Modify: `src/center_kb/codeingest/extractors/__init__.py`
- Modify: `tests/test_codeingest_extractors.py`

**Interfaces:**
- Consumes: nothing beyond core.
- Produces: `CommandsExtractor` emitting `cmd.build`, `cmd.test`, `cmd.lint`, `cmd.run` — the sections `dev-execute` and `dev-handover` read to satisfy the evidence rule (spec §3.14). This is the task that makes Stage A's verification gate executable.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_codeingest_extractors.py`:

```python
from center_kb.codeingest.extractors import commands as cmd_ext


class TestCommandsExtractor:
    def test_detects_when_any_command_source_exists(self, repo, tmp_path):
        assert cmd_ext.CommandsExtractor().detect(repo) is True
        empty = tmp_path / "empty3"
        empty.mkdir()
        assert cmd_ext.CommandsExtractor().detect(empty) is False

    def test_emits_purpose_sections(self, repo):
        sections = _by_id(cmd_ext.CommandsExtractor().extract(repo, _opts(repo)))
        assert {"cmd.build", "cmd.test", "cmd.lint"} <= set(sections)
        for s in sections.values():
            assert s.group == "commands"
            assert s.summary

    def test_ci_run_steps_win_over_local_scripts(self, repo):
        s = _by_id(cmd_ext.CommandsExtractor().extract(repo, _opts(repo)))["cmd.test"]
        # CI runs pytest; web/package.json runs vitest. CI is the source of truth.
        assert "pytest -q --cov=airspace" in s.l2_md
        assert "CI" in s.l2_md
        assert "vitest run" in s.l3_md          # kept as an alternative

    def test_local_scripts_are_used_when_there_is_no_ci(self, tmp_path):
        root = tmp_path / "nocI"
        root.mkdir()
        (root / "package.json").write_text(
            '{"scripts": {"test": "jest", "build": "tsc"}}\n', encoding="utf-8"
        )
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert "jest" in sections["cmd.test"].l2_md
        assert "tsc" in sections["cmd.build"].l2_md

    def test_makefile_targets_are_collected(self, tmp_path):
        root = tmp_path / "mk"
        root.mkdir()
        (root / "Makefile").write_text(
            "test:\n\tpytest -q\n\nlint:\n\truff check .\n", encoding="utf-8"
        )
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert "make test" in sections["cmd.test"].l2_md
        assert "make lint" in sections["cmd.lint"].l2_md

    def test_l3_has_no_pipe_table(self, repo):
        for s in cmd_ext.CommandsExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id

    def test_no_section_when_a_purpose_has_no_command(self, tmp_path):
        root = tmp_path / "only-build"
        root.mkdir()
        (root / "package.json").write_text('{"scripts": {"build": "tsc"}}\n', encoding="utf-8")
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert "cmd.build" in sections
        assert "cmd.test" not in sections
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_codeingest_extractors.py -k Commands -v`
Expected: FAIL — `ImportError: cannot import name 'commands'`.

- [ ] **Step 3: Write the classifier and readers**

`PURPOSES = ("build", "test", "lint", "run")`. Classification of a command string or script name uses a keyword table, first match in this order so `test` beats `build` for `pytest`:

```python
PURPOSE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "test": ("pytest", "vitest", "jest", "mocha", "go test", "dotnet test",
             "mvn test", "gradle test", "phpunit", "test"),
    "lint": ("ruff", "eslint", "flake8", "mypy", "golangci-lint",
             "dotnet format", "checkstyle", "lint", "format"),
    "build": ("build", "compile", "tsc", "vite build", "mvn package",
              "gradle build", "dotnet build", "pip install", "go build"),
    "run": ("start", "serve", "uvicorn", "gunicorn", "dotnet run",
            "go run", "dev"),
}
```

Readers, each returning `list[tuple[purpose, command, source]]`:

- **ci** — every `.github/workflows/*.y*ml` via `yaml.safe_load`; walk `jobs.*.steps[*].run`; split multi-line `run:` blocks on newlines; source label `f"CI: {file}#{job}"`.
- **npm** — every `package.json` at depth ≤ 2, `scripts`; command rendered as `npm run <name>` (`npm test` for the `test` script); source label the file path.
- **make** — a root `Makefile`, target names via `re.finditer(r"^([a-zA-Z0-9_.-]+):(?!=)", text, re.M)`; command rendered `make <target>`.
- **python** — `tox.ini` env names (`tox -e <env>`) and `pyproject.toml` `[tool.pytest.ini_options]` presence (`pytest`).
- **maven / gradle / dotnet / go** — presence-based defaults only: `pom.xml` → `mvn -B verify`; `build.gradle*` → `./gradlew build`; `*.csproj`/`*.sln` → `dotnet build` / `dotnet test`; `go.mod` → `go build ./...` / `go test ./...`.

**Priority:** for each purpose, the primary command is the first CI-sourced candidate; if none, the first local candidate in reader order (npm, make, python, presence-based). Every other candidate is retained as an alternative. Emit a section only for purposes with at least one command.

- [ ] **Step 4: Write the section rendering**

- **L2**: `**Primary:** \`<command>\`` plus `_Source: CI: .github/workflows/ci.yml#test_` (the string `CI` must appear when CI-sourced, asserted by a test), then a pipe table `| Command | Source |` of alternatives when any exist.
- **L3**: a fenced `bash` block with the primary command, then a fenced block listing every alternative as `# <source>` / `<command>` pairs. **No pipe tables.**
- `summary`: `f"How to {purpose} this repository: {primary} (source: {source})."`

Register `CommandsExtractor()` third in `ALL_EXTRACTORS`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_codeingest_extractors.py -v`
Expected: PASS (42 tests).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/center_kb/codeingest tests/test_codeingest_extractors.py
git add src/center_kb/codeingest tests/test_codeingest_extractors.py
git commit -m "feat: commands extractor — cmd.build/test/lint/run, CI over local scripts (phase 5B)"
```

---

## Task B6: `schema` extractor

**Files:**
- Create: `src/center_kb/codeingest/extractors/schema.py`
- Modify: `src/center_kb/codeingest/extractors/__init__.py`
- Modify: `tests/test_codeingest_extractors.py`

**Interfaces:**
- Consumes: `CodeIngestOptions.db_paths` for the explicit SQLite path.
- Produces: `SchemaExtractor` emitting `db.<table>`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_codeingest_extractors.py`:

```python
import sqlite3

from center_kb.codeingest.extractors import schema as schema_ext


class TestSchemaExtractor:
    def test_detects_migration_directories(self, repo, tmp_path):
        assert schema_ext.SchemaExtractor().detect(repo) is True
        empty = tmp_path / "empty4"
        empty.mkdir()
        assert schema_ext.SchemaExtractor().detect(empty) is False

    def test_one_section_per_table_from_sql_migrations(self, repo):
        sections = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))
        assert "db.restrictive_airspace" in sections
        assert sections["db.restrictive_airspace"].group == "db"

    def test_alter_table_add_column_accumulates(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert "designation" in s.l2_md
        assert "effective_date" in s.l2_md      # added by V2, applied in filename order

    def test_column_order_is_preserved_not_sorted(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert s.l2_md.index("designation") < s.l2_md.index("airspace_type")

    def test_primary_key_is_recorded(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert "PRIMARY KEY" in s.l3_md or "PK" in s.l2_md

    def test_l3_ddl_is_in_a_sql_fence_with_no_pipe_table(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert "```sql" in s.l3_md
        assert "|" not in s.l3_md

    def test_prisma_schema_is_read(self, tmp_path):
        root = tmp_path / "prisma-repo"
        (root / "prisma").mkdir(parents=True)
        (root / "prisma" / "schema.prisma").write_text(
            "model Airspace {\n  id Int @id\n  designation String\n}\n", encoding="utf-8"
        )
        sections = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))
        assert "db.Airspace" in sections

    def test_explicit_db_flag_reads_sqlite(self, tmp_path):
        root = tmp_path / "sqlite-repo"
        root.mkdir()
        db = root / "app.db"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE roster (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        con.commit()
        con.close()
        result = schema_ext.SchemaExtractor().extract(
            root, _opts(root, db_paths=(db,))
        )
        sections = _by_id(result)
        assert "db.roster" in sections
        assert "name" in sections["db.roster"].l2_md

    def test_stray_sqlite_file_is_never_read_without_the_flag(self, tmp_path):
        root = tmp_path / "stray"
        root.mkdir()
        con = sqlite3.connect(root / "fixture.db")
        con.execute("CREATE TABLE secret_fixture (id INTEGER)")
        con.commit()
        con.close()
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        assert all("secret_fixture" not in s.id for s in result.sections)

    def test_unsupported_ddl_warns_instead_of_guessing(self, tmp_path):
        root = tmp_path / "renames"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE a (id INT);\nALTER TABLE a RENAME TO b;\n", encoding="utf-8"
        )
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        assert any("001.sql" in w for w in result.warnings)

    def test_tables_are_sorted_by_name(self, tmp_path):
        root = tmp_path / "two-tables"
        mig = root / "migrations"
        mig.mkdir(parents=True)
        (mig / "001.sql").write_text(
            "CREATE TABLE zulu (id INT);\nCREATE TABLE alpha (id INT);\n", encoding="utf-8"
        )
        ids = [s.id for s in schema_ext.SchemaExtractor().extract(root, _opts(root)).sections]
        assert ids == sorted(ids)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_codeingest_extractors.py -k Schema -v`
Expected: FAIL — `ImportError: cannot import name 'schema'`.

- [ ] **Step 3: Write the SQL reader with explicit, documented limits**

In `schema.py`, a `TableRecord` dataclass (`name`, `columns: list[tuple[name, type_and_constraints]]`, `pk: str`, `ddl: str`, `source: str`) and:

- `MIGRATION_GLOBS = ("**/migrations/*.sql", "**/migration/*.sql", "**/db/migration/*.sql", "**/changelog/*.sql")`, deduplicated and **sorted by path** so accumulation order is deterministic.
- `CREATE_RE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`\[]?(?P<name>[A-Za-z_][\w.]*)[\"`\]]?\s*\((?P<body>.*?)\);", re.S | re.I)`
- `ADD_COL_RE = re.compile(r"ALTER\s+TABLE\s+[\"`\[]?(?P<name>[A-Za-z_][\w.]*)[\"`\]]?\s+ADD\s+(?:COLUMN\s+)?(?P<col>[^;]+);", re.I)`
- `UNSUPPORTED_RE = re.compile(r"ALTER\s+TABLE\s+.*?\b(RENAME|DROP)\b", re.I)` → emits a warning naming the file; the statement is skipped, never guessed.
- Column splitting: split the `CREATE TABLE` body on commas **at paren depth 0**; drop entries starting with `PRIMARY KEY`/`FOREIGN KEY`/`CONSTRAINT`/`UNIQUE`/`CHECK` from the column list but record `PRIMARY KEY (...)` into `pk`; also detect inline `PRIMARY KEY` on a column.

State in a module docstring that this recognises `CREATE TABLE` and `ALTER TABLE … ADD COLUMN` only, and that this is why spec §3.9 makes the code ground truth.

- [ ] **Step 4: Write the other readers**

- **prisma** — `**/schema.prisma`, `re.finditer(r"^model\s+(\w+)\s*\{(.*?)^\}", text, re.S | re.M)`; field lines are `name type ...`.
- **alembic** — `**/versions/*.py`, `re.finditer(r"op\.create_table\(\s*['\"](\w+)['\"]", text)`; columns via `sa.Column\(\s*['\"](\w+)['\"]\s*,\s*([^,)]+)`.
- **ef** — `**/Migrations/*.cs`, `migrationBuilder\.CreateTable\(\s*name:\s*"(\w+)"`.
- **sqlite** — only for paths in `opts.db_paths`; `sqlite3.connect(f"file:{path}?mode=ro", uri=True)`; read `SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name`; columns via `PRAGMA table_info(<name>)` (preserving `cid` order). A missing path is a warning, not a crash.

Merge records by table name; when two sources disagree, keep the first by reader order (sql, prisma, alembic, ef, sqlite) and warn.

- [ ] **Step 5: Write the section rendering**

- **L2**: a pipe table `| Column | Type | PK |` in **declaration order**, then `_Source: <file>_`.
- **L3**: the full DDL in a fenced `sql` block (reconstructed `CREATE TABLE` when the source was not SQL), then a plain fenced block naming the source files. **No pipe tables.**
- `summary`: `f"Table {name}: {len(columns)} columns, PK {pk or 'none detected'} (source: {source})."`

Register `SchemaExtractor()` fifth in `ALL_EXTRACTORS`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_codeingest_extractors.py -v`
Expected: PASS (53 tests).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/center_kb/codeingest tests/test_codeingest_extractors.py
git add src/center_kb/codeingest tests/test_codeingest_extractors.py
git commit -m "feat: schema extractor — SQL migrations, Prisma, Alembic, EF, explicit SQLite (phase 5B)"
```

---

## Task B7: `integrations` + `api` extractors

**Files:**
- Create: `src/center_kb/codeingest/extractors/integrations.py`
- Create: `src/center_kb/codeingest/extractors/api.py`
- Modify: `src/center_kb/codeingest/extractors/__init__.py`
- Modify: `tests/test_codeingest_extractors.py`

**Interfaces:**
- Consumes: core only.
- Produces: `IntegrationsExtractor` (`int.<name>`) and `ApiExtractor` (`api.<tag>`) — the last two extractors; after this task `ALL_EXTRACTORS` is complete with seven entries.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_codeingest_extractors.py`:

```python
from center_kb.codeingest.extractors import api as api_ext
from center_kb.codeingest.extractors import integrations as int_ext


class TestIntegrationsExtractor:
    def test_detects_env_example_or_openapi_servers(self, repo, tmp_path):
        assert int_ext.IntegrationsExtractor().detect(repo) is True
        empty = tmp_path / "empty5"
        empty.mkdir()
        assert int_ext.IntegrationsExtractor().detect(empty) is False

    def test_groups_keys_into_named_integrations(self, repo):
        sections = _by_id(int_ext.IntegrationsExtractor().extract(repo, _opts(repo)))
        assert "int.kafka" in sections
        assert "int.s3" in sections
        for s in sections.values():
            assert s.group == "integrations"
            assert s.summary

    def test_never_emits_a_value(self, repo):
        result = int_ext.IntegrationsExtractor().extract(repo, _opts(repo))
        blob = "".join(s.l2_md + s.l3_md for s in result.sections)
        for secret in ("do-not-ship-this-value", "localhost:9092",
                       "airspace-assets", "postgres://localhost/airspace"):
            assert secret not in blob

    def test_never_reads_a_real_dotenv(self, tmp_path):
        root = tmp_path / "real-env"
        root.mkdir()
        (root / ".env").write_text("REAL_SECRET_TOKEN=abc123\n", encoding="utf-8")
        result = int_ext.IntegrationsExtractor().extract(root, _opts(root))
        blob = "".join(s.l2_md + s.l3_md for s in result.sections)
        assert "REAL_SECRET_TOKEN" not in blob
        assert "abc123" not in blob

    def test_l3_has_no_pipe_table(self, repo):
        for s in int_ext.IntegrationsExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id


class TestApiExtractor:
    def test_detects_an_openapi_file(self, repo, tmp_path):
        assert api_ext.ApiExtractor().detect(repo) is True
        empty = tmp_path / "empty6"
        empty.mkdir()
        assert api_ext.ApiExtractor().detect(empty) is False

    def test_one_section_per_tag(self, repo):
        sections = _by_id(api_ext.ApiExtractor().extract(repo, _opts(repo)))
        assert "api.airspace" in sections
        assert sections["api.airspace"].group == "api"

    def test_lists_methods_and_paths(self, repo):
        s = _by_id(api_ext.ApiExtractor().extract(repo, _opts(repo)))["api.airspace"]
        assert "GET" in s.l2_md and "POST" in s.l2_md
        assert "/airspace" in s.l2_md

    def test_untagged_paths_land_in_api_surface(self, tmp_path):
        root = tmp_path / "untagged"
        root.mkdir()
        (root / "openapi.yaml").write_text(
            "openapi: 3.0.0\npaths:\n  /health:\n    get:\n      summary: Health\n",
            encoding="utf-8",
        )
        assert "api.surface" in _by_id(api_ext.ApiExtractor().extract(root, _opts(root)))

    def test_l3_has_no_pipe_table(self, repo):
        for s in api_ext.ApiExtractor().extract(repo, _opts(repo)).sections:
            assert "|" not in s.l3_md, s.id

    def test_malformed_openapi_warns(self, tmp_path):
        root = tmp_path / "bad-api"
        root.mkdir()
        (root / "openapi.yaml").write_text("paths: [", encoding="utf-8")
        result = api_ext.ApiExtractor().extract(root, _opts(root))
        assert any("openapi.yaml" in w for w in result.warnings)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_codeingest_extractors.py -k "Integrations or Api" -v`
Expected: FAIL — `ImportError: cannot import name 'integrations'`.

- [ ] **Step 3: Write `integrations.py`**

- `ENV_FILES = (".env.example", ".env.sample", ".env.template")` — exactly these three names; **never** `.env`. Put a comment naming spec §3.11 above the tuple.
- Read key names only: `re.finditer(r"^\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", text, re.M)` — the value is never captured, so it cannot leak.
- Also collect keys from compose `environment:` (mapping keys or the part before `=` in list form) and hostnames from OpenAPI `servers[*].url` **as URLs only when the file is committed** (they are already public contract).
- Group keys into integrations by prefix table, first match wins:

```python
INTEGRATION_PREFIXES: tuple[tuple[str, str], ...] = (
    ("KAFKA", "kafka"), ("RABBIT", "rabbitmq"), ("REDIS", "redis"),
    ("S3", "s3"), ("MINIO", "s3"), ("AWS", "aws"), ("AZURE", "azure"),
    ("GCP", "gcp"), ("SMTP", "smtp"), ("MAIL", "smtp"),
    ("ELASTIC", "elasticsearch"), ("OPENSEARCH", "elasticsearch"),
    ("KEYCLOAK", "keycloak"), ("OIDC", "oidc"), ("OAUTH", "oauth"),
    ("STRIPE", "stripe"), ("TWILIO", "twilio"),
)
```

Keys matching no prefix but ending in `_URL`/`_ENDPOINT`/`_HOST`/`_URI` group into `int.other`; everything else is dropped (a plain `SECRET_KEY` is not an integration and must not be published).

- **L2**: pipe table `| Env key | Source |`. **L3**: fenced block listing keys, one per line, sorted. `summary`: `f"External integration {name}: configured through {n} environment keys ({', '.join(keys)})."`

- [ ] **Step 4: Write `api.py`**

- `API_GLOBS = ("openapi*.y*ml", "openapi*.json", "swagger*.y*ml", "swagger*.json", "**/openapi*.y*ml")`.
- Load with `yaml.safe_load` (YAML is a JSON superset, so one loader covers both); a parse failure is a warning naming the file.
- For each `paths.<path>.<method>` where method is in `("get","post","put","patch","delete","head","options")`: take the first entry of `tags` or `"surface"`; group operations by tag, sorted by `(path, method)`.
- **L2**: `**Servers:** <urls>` then pipe table `| Method | Path | Summary |`. **L3**: fenced block with `METHOD /path — summary` lines. `summary`: `f"API tag {tag}: {n} operations ({methods}) from {file}."`

Register both, last in `ALL_EXTRACTORS` (order: services, deps, commands, tree, schema, integrations, api).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_codeingest_extractors.py -v`
Expected: PASS (64 tests).

- [ ] **Step 6: Prove the full extractor set builds clean end to end**

Append to `tests/test_codeingest_core.py` and run:

```python
def test_full_extractor_set_on_the_fixture_repo_builds_clean(tmp_path):
    from tests.fixtures_coderepo import build_code_repo

    root = build_code_repo(tmp_path)
    db = root / "app.db"
    import sqlite3

    con = sqlite3.connect(db)
    con.execute("CREATE TABLE roster (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    report = core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code",
            repo_id="demo", db_paths=(db,),
        )
    )
    assert set(report.detected) >= {
        "services", "deps", "commands", "tree", "schema", "integrations", "api"
    }
    build = build_kb(root / ".kb")
    assert build.errors == [], build.errors
    assert build.ok
```

Run: `uv run pytest tests/test_codeingest_core.py -v`
Expected: PASS — this is the load-bearing assertion that the table-integrity and summary invariants hold by construction.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/center_kb/codeingest tests/test_codeingest_extractors.py tests/test_codeingest_core.py
git add src/center_kb/codeingest tests/test_codeingest_extractors.py tests/test_codeingest_core.py
git commit -m "feat: integrations + api extractors; full-set build-compat test (phase 5B)"
```

---

## Task B8: `kb code-ingest` CLI + `--scaffold-svc`

**Files:**
- Modify: `src/center_kb/codeingest/core.py` (add `scaffold_svc()`, stale-risk, orphans)
- Modify: `src/center_kb/cli.py` (new `code-ingest` command)
- Create: `tests/test_codeingest_scaffold.py`
- Create: `tests/test_cli_codeingest.py`

**Interfaces:**
- Consumes: `run()` and every extractor.
- Produces: the `kb code-ingest` command surface, and the `.kb/<repo_id>-svc/` document Stage C's `dev-code-seed` and `kb svc note` operate on. `scaffold_svc` writes sections with `status="pending"` and the exact marker `f"<!-- TODO:summarize {sid} -->"` that `summarize.collect_pending()` / `rebuild_l2_scaffold()` already recognise.

- [ ] **Step 1: Write the failing scaffold test**

Create `tests/test_codeingest_scaffold.py`:

```python
from pathlib import Path

from center_kb import models
from center_kb.build import build_kb
from center_kb.codeingest import core
from center_kb.summarize import collect_pending
from tests.fixtures_coderepo import build_code_repo


def _run(root: Path, **kw) -> core.CodeIngestReport:
    return core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code",
            repo_id="demo", **kw
        )
    )


def test_scaffold_creates_pending_svc_sections_with_the_exact_marker(tmp_path):
    root = build_code_repo(tmp_path)
    report = _run(root, scaffold_svc=True)
    assert "svc.airspace-service" in report.scaffolded
    svc_dir = root / ".kb" / "demo-svc"
    l2 = (svc_dir / "services.md").read_text(encoding="utf-8")
    assert "<!-- TODO:summarize svc.airspace-service -->" in l2
    manifest = models.load_yaml_model(svc_dir / "_manifest.yaml", models.Manifest)
    assert all(s.status == "pending" for s in manifest.sections)


def test_scaffold_l3_holds_deterministic_code_evidence(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    l3 = (root / ".kb" / "demo-svc" / "services.raw.md").read_text(encoding="utf-8")
    assert "airspace-service" in l3
    assert "```" in l3
    assert "|" not in l3


def test_scaffolded_sections_are_visible_to_collect_pending(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    pending = collect_pending(root / ".kb", "demo-svc")
    assert {p.section_id for p in pending} >= {"svc.airspace-service", "svc.postgres"}


def test_svc_index_entry_is_tagged_code_curated(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    index = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    entry = next(d for d in index.docs if d.id == "demo-svc")
    assert entry.tags == ["code", "curated"]


def test_second_run_refreshes_l3_only_and_never_touches_reviewed_l2(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    svc_dir = root / ".kb" / "demo-svc"
    l2_path = svc_dir / "services.md"
    l2_path.write_text(
        l2_path.read_text(encoding="utf-8").replace(
            "<!-- TODO:summarize svc.airspace-service -->",
            "Owns airspace approval decisions.",
        ),
        encoding="utf-8",
    )
    manifest_path = svc_dir / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        if sec.id == "svc.airspace-service":
            sec.status = "reviewed"
            sec.summary = "Owns airspace approval decisions."
    models.save_yaml_model(manifest_path, manifest)

    _run(root, scaffold_svc=True)

    assert "Owns airspace approval decisions." in l2_path.read_text(encoding="utf-8")
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    reviewed = next(s for s in manifest.sections if s.id == "svc.airspace-service")
    assert reviewed.status == "reviewed"
    assert reviewed.summary == "Owns airspace approval decisions."


def test_changed_evidence_under_a_reviewed_section_raises_stale_risk(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    manifest_path = root / ".kb" / "demo-svc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    for sec in manifest.sections:
        sec.status = "reviewed"
        sec.summary = "Reviewed by a human."
    models.save_yaml_model(manifest_path, manifest)

    compose = root / "docker-compose.yml"
    compose.write_text(
        compose.read_text(encoding="utf-8").replace("8080:8080", "9090:9090"),
        encoding="utf-8",
    )
    report = _run(root, scaffold_svc=True)
    assert "svc.airspace-service" in report.stale_risk


def test_service_removed_from_code_is_reported_as_orphan_not_deleted(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    compose = root / "docker-compose.yml"
    compose.write_text(
        "services:\n  airspace-service:\n    image: airspace:1.0\n", encoding="utf-8"
    )
    report = _run(root, scaffold_svc=True)
    assert "svc.postgres" in report.orphans
    l2 = (root / ".kb" / "demo-svc" / "services.md").read_text(encoding="utf-8")
    assert "## svc.postgres" in l2


def test_scaffolded_state_fails_build_without_allow_pending_and_passes_with_it(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root, scaffold_svc=True)
    strict = build_kb(root / ".kb")
    assert not strict.ok
    assert any("demo-svc" in e for e in strict.errors)
    lenient = build_kb(root / ".kb", allow_pending=True)
    assert lenient.ok


def test_code_document_still_builds_clean_when_scaffold_is_not_requested(tmp_path):
    root = build_code_repo(tmp_path)
    _run(root)
    assert not (root / ".kb" / "demo-svc").exists()
    assert build_kb(root / ".kb").ok
```

- [ ] **Step 2: Write the failing CLI test**

Create `tests/test_cli_codeingest.py`:

```python
import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app
from tests.fixtures_coderepo import build_code_repo

runner = CliRunner()


def _init_config(root: Path, repo_id: str = "demo") -> None:
    (root / ".kb").mkdir(exist_ok=True)
    (root / ".kb" / "config.yaml").write_text(
        f'kind: dev\nhub: ""\nrepo_id: "{repo_id}"\nintake: ""\n', encoding="utf-8"
    )


def test_code_ingest_writes_the_document_and_reports(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 0, result.output
    assert (root / ".kb" / "demo-code" / "_manifest.yaml").is_file()
    assert "services" in result.output


def test_json_output_shape(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    for key in ("doc_id", "sections_by_extractor", "files_written", "warnings",
                "detected", "dirty_tree"):
        assert key in payload
    assert payload["doc_id"] == "demo-code"


def test_repo_id_comes_from_config_and_doc_id_is_derived(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root, repo_id="dashboard")
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--json"])
    assert json.loads(result.output)["doc_id"] == "dashboard-code"


def test_explicit_doc_id_overrides(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"),
                                "--doc-id", "custom-code", "--json"])
    assert json.loads(result.output)["doc_id"] == "custom-code"


def test_db_flag_is_repeatable(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    for name in ("a.db", "b.db"):
        con = sqlite3.connect(root / name)
        con.execute(f"CREATE TABLE t_{name[0]} (id INTEGER)")
        con.commit()
        con.close()
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"),
                                "--db", str(root / "a.db"),
                                "--db", str(root / "b.db")])
    assert result.exit_code == 0, result.output
    db_md = (root / ".kb" / "demo-code" / "db.md").read_text(encoding="utf-8")
    assert "t_a" in db_md and "t_b" in db_md


def test_tags_flag_appends_to_the_reserved_tags(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                        "--kb-dir", str(root / ".kb"), "--tags", "team-x,platform"])
    index = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    entry = next(d for d in index.docs if d.id == "demo-code")
    assert entry.tags == ["code", "generated", "team-x", "platform"]


def test_scaffold_svc_flag_creates_the_curated_document(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--scaffold-svc"])
    assert result.exit_code == 0, result.output
    assert (root / ".kb" / "demo-svc" / "_manifest.yaml").is_file()


def test_exit_1_when_only_the_tree_extractor_detects(tmp_path):
    root = tmp_path / "bare"
    (root / "src").mkdir(parents=True)
    (root / "src" / "notes.txt").write_text("hello", encoding="utf-8")
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 1
    assert "no code artifacts" in result.output.lower()


def test_build_is_not_called_implicitly(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 0
    assert "kb build: OK" not in result.output
```

- [ ] **Step 3: Run both test files to verify they fail**

Run: `uv run pytest tests/test_codeingest_scaffold.py tests/test_cli_codeingest.py -v`
Expected: FAIL — `AttributeError: module 'center_kb.codeingest.core' has no attribute 'scaffold_svc'` and `No such command 'code-ingest'`.

- [ ] **Step 4: Implement `scaffold_svc()` in `core.py`**

```python
def scaffold_svc(opts, sections, report) -> None:
    """Upsert the curated -svc document from the svc.* sections just extracted.

    Absent section -> create as pending with the TODO:summarize marker and L3
    code evidence. Present section -> refresh L3 evidence ONLY; never touch L2
    or status (spec 8.2). Upsert, never clobber.
    """
```

Details:

- `svc_doc_id = f"{opts.repo_id}-svc"`; group name `"services"` for `svc.*`, `"flows"` reserved for human-authored `flow.*`, `"history"` for `hist.*`.
- Build evidence per service: the files whose path contains the service name, its ports and image, the tables it appears to reach (name match against `db.*` ids), and any module-level docstring/comment header found in the first 5 lines of those files. Render inside a fenced block, sorted — this is the prompt material `summarize.build_section_prompt` will read.
- Read the existing manifest when present; for each existing section keep `status`, `summary`, and its L2 slice verbatim (use `mdutils.slice_section` to lift it out of the old file and re-emit it unchanged).
- For a **new** section: L2 body is exactly `<!-- TODO:summarize svc.<name> -->`, `status="pending"`, `summary=""`; append the id to `report.scaffolded`.
- For an existing **`reviewed`** section whose new evidence differs from the old L3 slice: append the id to `report.stale_risk`.
- For an existing section with no matching `svc.*` in this run: keep it untouched and append the id to `report.orphans`.
- Banner: `> Responsibility text is human-owned. L3 code evidence regenerated at <short-commit>.`
- Index entry tags: `["code", "curated"]` plus `opts.tags` plus pre-existing extras.

- [ ] **Step 5: Add the CLI command**

In `src/center_kb/cli.py`, after the `build` command, a thin wrapper:

```python
@app.command(name="code-ingest")
def code_ingest(
    repo_root: Path = typer.Option(Path("."), "--repo-root", help="Repository root to scan"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    repo_id: str = typer.Option("", "--repo-id", help="Repo ID (default: config, then folder name)"),
    doc_id: str = typer.Option("", "--doc-id", help="Document ID (default: <repo_id>-code)"),
    db: list[Path] = typer.Option([], "--db", help="SQLite file to read (repeatable, explicit only)"),
    tags: str = typer.Option("", "--tags", help="Extra index tags, comma-separated"),
    scaffold_svc: bool = typer.Option(
        False, "--scaffold-svc",
        help="Also upsert the curated <repo_id>-svc scaffold (pending sections)",
    ),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Extract code structure into .kb/<repo_id>-code/ — deterministic, no LLM."""
```

Body: resolve `repo_id` via `config.effective_repo_id(repo_id, kb_dir)`; default `doc_id` to `f"{rid}-code"`; parse `tags`; build `CodeIngestOptions`; call `codeingest.run()`; catch `CodeIngestError` → `typer.secho(str(exc), fg=RED)` + `raise typer.Exit(1)`; print the report (or `json.dumps(asdict(report), indent=2)` when `--json`). The zero-detection message must contain the phrase **"no code artifacts"** and list the artifact kinds searched for. Do **not** call `build_kb` — a test asserts this.

- [ ] **Step 6: Run both test files to verify they pass**

Run: `uv run pytest tests/test_codeingest_scaffold.py tests/test_cli_codeingest.py -v`
Expected: PASS (19 tests).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/center_kb/codeingest src/center_kb/cli.py tests/test_codeingest_scaffold.py tests/test_cli_codeingest.py
git add src/center_kb/codeingest src/center_kb/cli.py tests/test_codeingest_scaffold.py tests/test_cli_codeingest.py
git commit -m "feat: kb code-ingest CLI + --scaffold-svc with stale-risk and orphan reporting (phase 5B)"
```

---

## Task B9: CI workflow `kb-code.yml` + registration on kind `dev`

**Files:**
- Create: `src/center_kb/templates/init/kb-code.yml`
- Modify: `src/center_kb/initcmd.py` (one row in `DEV_TEMPLATES`)
- Modify: `tests/test_init.py`
- Modify: `tests/test_templates.py`

**Interfaces:**
- Consumes: `kb code-ingest` from B8 and the existing `kb ci-publish`.
- Produces: `.github/workflows/kb-code.yml` on every `kb init --kind dev` repo.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_kb_code_workflow_has_both_triggers():
    text = _read_init_template("kb-code.yml")
    assert "push:" in text
    assert "workflow_dispatch:" in text
    assert "pull_request:" in text


def test_kb_code_publish_job_runs_the_full_chain():
    text = _read_init_template("kb-code.yml")
    assert "kb code-ingest" in text
    assert "kb build" in text
    assert "kb ci-publish" in text


def test_kb_code_pull_request_job_validates_but_never_publishes():
    import yaml

    wf = yaml.safe_load(_read_init_template("kb-code.yml"))
    jobs = wf["jobs"]
    pr_job = next(j for name, j in jobs.items() if "validate" in name)
    steps = " ".join(str(s.get("run", "")) for s in pr_job["steps"])
    assert "kb build" in steps
    assert "ci-publish" not in steps
    assert "code-ingest" not in steps


def test_kb_code_never_scaffolds_svc_in_ci():
    assert "--scaffold-svc" not in _read_init_template("kb-code.yml")


def test_kb_code_has_no_hardcoded_url_or_token():
    text = _read_init_template("kb-code.yml")
    assert "https://" not in text
    assert "secrets." not in text
    assert "id-token: write" in text
```

Append to `tests/test_init.py`:

```python
def test_init_kind_dev_scaffolds_the_code_workflow(tmp_path: Path):
    init_repo(tmp_path, "dev")
    assert (tmp_path / ".github" / "workflows" / "kb-code.yml").is_file()
    assert not (tmp_path / ".github" / "workflows" / "kb-publish.yml").exists()


def test_kb_code_workflow_is_not_on_hub_child_or_ba(tmp_path: Path):
    for kind in ("hub", "child", "ba"):
        assert ".github/workflows/kb-code.yml" not in expected_files(kind), kind
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k kb_code tests/test_init.py -k code_workflow -v`
Expected: FAIL — missing resource `kb-code.yml`.

- [ ] **Step 3: Write the workflow template**

Create `src/center_kb/templates/init/kb-code.yml` with two jobs. Model the OIDC permissions and setup steps on the existing `kb-publish.yml`; read that file first and match its style.

```yaml
name: kb-code

on:
  push:
    branches: [main, master]
  pull_request:
  workflow_dispatch:

jobs:
  # PR: validate only. Never publishes. This job is what catches a malformed
  # -svc edit or a `pending` section committed before review — before merge,
  # not after.
  validate:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install center-kb
      - run: kb build

  publish:
    if: github.event_name != 'pull_request'
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write        # OIDC — no secrets in this repo
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0     # code-ingest reads HEAD's commit and commit date
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install center-kb
      # Add --db <path> flags here if this repo has SQLite databases whose
      # schema belongs in the KB. Deliberately explicit: a stray test fixture
      # must never become published company knowledge.
      # NOTE: --scaffold-svc is deliberately absent. CI must not create
      # `pending` content — it would fail its own `kb build` step. Seeding and
      # amending the curated -svc document are human, local actions
      # (see /dev-code-seed).
      - run: kb code-ingest
      - run: kb build
      - run: kb ci-publish
```

- [ ] **Step 4: Register it on kind `dev`**

In `src/center_kb/initcmd.py`, add one row to `DEV_TEMPLATES`:

```python
    ".github/workflows/kb-code.yml": "kb-code.yml",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -v`
Expected: PASS.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check src/center_kb/initcmd.py tests/test_init.py tests/test_templates.py
git add src/center_kb/templates/init/kb-code.yml src/center_kb/initcmd.py tests/test_init.py tests/test_templates.py
git commit -m "feat: kb-code.yml — publish on merge, validate on PR; registered on kind dev (phase 5B)"
```

---

## Task B10: federation smoke test, docs, release

**Files:**
- Modify: `tests/test_codeingest_core.py` (federation smoke)
- Modify: `README.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: everything from B1–B9.
- Produces: the released minor version Stage C builds on.

- [ ] **Step 1: Write the failing federation smoke test**

Append to `tests/test_codeingest_core.py`:

```python
def test_generated_document_is_searchable_through_the_hub(tmp_path, run_git):
    """The whole point of using the 4-layer format: zero engine changes needed."""
    import sqlite3

    from center_kb.hub import resolve_hub
    from center_kb.query import get_section, search
    from tests.fixtures_coderepo import build_code_repo

    root = build_code_repo(tmp_path / "repo")
    db = root / "app.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE roster (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code",
            repo_id="demo", db_paths=(db,),
        )
    )
    assert build_kb(root / ".kb").ok

    # Publish by copying .kb/ into a hub federation dir — the shape kb publish produces.
    hub = tmp_path / "hub"
    dest = hub / "federation" / "demo"
    dest.mkdir(parents=True)
    for item in (root / ".kb").iterdir():
        target = dest / item.name
        if item.is_dir():
            import shutil

            shutil.copytree(item, target)
        else:
            import shutil

            shutil.copy2(item, target)
    run_git(hub, "init")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "publish demo-code")

    handle = resolve_hub(str(hub))
    assert handle is not None
    assert search(handle, "roster")
    assert search(handle, "airspace-service")
    section = get_section(handle, "demo-code", "db.roster", level="l3")
    assert section is not None
    assert "CREATE TABLE" in section.content
```

- [ ] **Step 2: Run it to verify it fails, then passes**

Run: `uv run pytest tests/test_codeingest_core.py -k searchable -v`

If it fails for a reason other than a real defect (e.g. the fixture hub layout needs `index.yaml` at the federation root), fix the **test's** publish emulation to match what `kb publish` actually writes — read `src/center_kb/publish.py` for the exact layout before changing anything in `codeingest`. The assertion under test is that **no engine change is needed**; if `codeingest` output genuinely cannot be searched, that is a spec-level defect and must be raised, not patched around.

Expected once correct: PASS.

- [ ] **Step 3: Document `kb code-ingest` in README**

Add: the command with every flag; the seven extractors and the artifact kinds each reads; the reserved `-code` / `-svc` doc-id suffixes; the section-id prefix contract table from spec §6.2; the determinism guarantee and the dirty-tree caveat; the `--db`-only SQLite rule and the `.env.example`-keys-only rule, both stated as security properties; and the `kb-code.yml` two-job design with the note that auto-merging `-code` hub PRs is a hub-side policy while `-svc` PRs are never auto-merged.

- [ ] **Step 4: Full suite**

Run: `uv run pytest -q`
Expected: PASS, `tests-gate/regression/test_mcp_contract.py` green, `tests-gate/golden/*` unchanged.

- [ ] **Step 5: Confirm the golden fixtures really are untouched**

Run: `git status --short tests-gate/`
Expected: empty output.

- [ ] **Step 6: Bump the version and commit**

In `pyproject.toml`, bump the minor version (`0.16.0` → `0.17.0`).

```bash
git add README.md pyproject.toml tests/test_codeingest_core.py
git commit -m "docs: kb code-ingest + extractor set; chore: bump to 0.17.0"
```

---

## Self-review notes (spec coverage for Stage B)

| Spec section | Covered by |
|---|---|
| §3.5 determinism (incl. Windows path/EOL) | B1 Steps 4–6, B1 tests `two_runs…`, `lf_endings`, `commit_date_not_wall_clock`; B2 `forward_slashes` |
| §3.7 build invariants by construction | B1 `builds_clean…`, B7 Step 6 full-set build-compat |
| §3.11 never a secret channel | B4 `environment_keys_only_never_values`, B7 `never_emits_a_value`, `never_reads_a_real_dotenv`, B6 `stray_sqlite_file_is_never_read_without_the_flag` |
| §3.12 cross-stack by artifact kind | B3 (6 ecosystems), B4 (4 container sources), B5 (5 command sources), B6 (5 schema sources) |
| §6.1 identity, tags | B1 `index_entry_carries_code_and_generated_tags`, B8 `svc_index_entry_is_tagged_code_curated` |
| §6.2 prefix contract incl. `cmd.*` | B2–B7, one task per prefix family |
| §6.3 L2/L3 rules | every extractor's `l3_has_no_pipe_table` test |
| §6.4 manifest mapping + token preservation | B1 `manifest_records_commit…`, `rerun_preserves_per_section_tokens…` |
| §6.5 dirty-tree caveat | B1 `dirty_tree_is_reported` |
| §7 protocol, extractor table, limits, zero-detection | B1 Step 3, B2–B7, B1 `zero_detection_beyond_tree_raises` |
| §8.1 CLI default behaviour | B8 CLI tests |
| §8.2 `--scaffold-svc` upsert-never-clobber | B8 `second_run_refreshes_l3_only…` |
| §8.3 stale-risk | B8 `changed_evidence_under_a_reviewed_section…` |
| §8.4 orphans | B8 `service_removed_from_code_is_reported_as_orphan_not_deleted` |
| §10 the free build gate | B8 `scaffolded_state_fails_build_without_allow_pending…` |
| §11 CI workflow, both jobs | B9 |
| §13 search/federation smoke | B10 Step 1 |
| §14 rollout | B10 |

**Not in this plan, by design:** `dev-code-seed`, `kb svc note`, and the eight BA wrapper updates are Stage C/D — see `2026-08-19-dev-agent-stage-cd.md`.
