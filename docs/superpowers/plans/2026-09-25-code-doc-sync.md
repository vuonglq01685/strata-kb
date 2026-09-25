# `-code` Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `<repo_id>-code` derived on demand (never committed), produced only by deterministic `kb code-ingest`, configured identically for local runs and CI, with hub lag visible — plus two extractor fixes (`cmd.*` from strata's own workflows, Compose `!reset`/`!override`).

**Architecture:** A new `strata_kb/codeingest/sync.py` owns the shared ingest configuration (`code_ingest:` in `.kb/config.yaml`), the CI version pin, and `ensure_code_fresh()`; the commands that read working-code facts (`kb svc note`, `kb build`, `kb publish` in a dev repo) call it first, while `kb ticket check` reads the hub first. A new `strata_kb/codeingest/hublag.py` regenerates `-code` at `origin/<default>` in a detached worktree and compares L3 with the hub copy for `kb doctor`. `kb summarize` refuses documents tagged `generated`; `kb ci-publish` writes a job-summary line.

**Tech Stack:** Python ≥ 3.11, Typer, Pydantic v2, PyYAML 6, pytest, git CLI.

**Spec:** `docs/superpowers/specs/2026-09-25-code-doc-sync-design.md`

## Global Constraints

- Code, comments, docs, commit messages: English. Match the surrounding comment density (this codebase explains *why* in comments; do not add narration).
- Test interpreter: `PY=.venv/Scripts/python.exe` on Windows, `PY=.venv/bin/python` elsewhere. The venv is uv-managed and has no pip — never `pip install`. Run focused tests per task with `$PY -m pytest <files> -q`.
- The full suite takes 10–19 minutes: run it **once**, in Task 13, never per task.
- `strata_kb.__version__` is `"0+unknown"` in the source-tree venv; tests that need a version monkeypatch `strata_kb.__version__`.
- Typer `CliRunner` here is Click 8.4: `result.stderr` holds `err=True` output, `result.output` holds both streams.
- Diagnostic lines a command prints alongside `--json` go to stderr (`err=True`), never stdout.
- `-code` rows keep `status="summarized"`; index tag pair for `-code` stays `["code", "generated"]`.
- The gitignore line is exactly `.kb/*-code/`.
- Release: `1.4.0` (Task 13).
- Every commit message ends with a blank line then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- `cli.py` is touched by Tasks 3, 6, 7, 8, 10, 11, 12 — run tasks sequentially, in order.

---

### Task 1: Compose `!reset` / `!override` parse

**Depends on:** none

**Files:**
- Create: `src/strata_kb/codeingest/extractors/_composeyaml.py`
- Modify: `src/strata_kb/codeingest/extractors/services.py` (`_read_compose`, the `yaml.safe_load(text)` call ~line 281)
- Modify: `src/strata_kb/codeingest/extractors/integrations.py` (`_read_compose_env`, the `yaml.safe_load(text)` call ~line 172)
- Test: `tests/test_codeingest_composeyaml.py` (create)

**Interfaces:**
- Produces: `load_compose(text: str) -> object` in `strata_kb.codeingest.extractors._composeyaml`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_codeingest_composeyaml.py
from pathlib import Path

import pytest
import yaml

from strata_kb.codeingest import core
from strata_kb.codeingest.extractors import integrations as int_ext
from strata_kb.codeingest.extractors import services as svc_ext
from strata_kb.codeingest.extractors._composeyaml import load_compose


def _opts(root: Path) -> core.CodeIngestOptions:
    return core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="demo-code", repo_id="demo"
    )


_COMPOSE = (
    "services:\n"
    "  api:\n"
    "    image: api:1\n"
    "    ports: !reset []\n"
    "    environment:\n"
    "      REDIS_URL: redis://cache:6379\n"
    "  worker:\n"
    "    image: worker:1\n"
    "    environment: !override\n"
    "      QUEUE_URL: amqp://mq\n"
)


def test_reset_yields_the_empty_value_of_its_node_kind():
    assert load_compose("a: !reset\nb: !reset []\nc: !reset {}\n") == {
        "a": None, "b": [], "c": {},
    }


def test_override_yields_the_plain_value():
    data = load_compose(
        "ports: !override\n  - '8080:80'\nenv: !override\n  K: v\nn: !override 3\n"
    )
    assert data == {"ports": ["8080:80"], "env": {"K": "v"}, "n": 3}


def test_other_tags_still_fail_like_safe_load():
    with pytest.raises(yaml.YAMLError):
        load_compose("x: !!python/object/apply:os.system ['ls']\n")


def test_services_reads_a_compose_file_that_uses_reset(tmp_path):
    (tmp_path / "docker-compose.yml").write_text(_COMPOSE, encoding="utf-8")
    result = svc_ext.ServicesExtractor().extract(tmp_path, _opts(tmp_path))
    assert not any("docker-compose.yml" in w for w in result.warnings), result.warnings
    assert {"svc.api", "svc.worker"} <= {s.id for s in result.sections}


def test_integrations_reads_a_nested_compose_file_that_uses_reset(tmp_path):
    nested = tmp_path / "infra" / "compose"
    nested.mkdir(parents=True)
    (nested / "docker-compose.cpu.yml").write_text(_COMPOSE, encoding="utf-8")
    result = int_ext.IntegrationsExtractor().extract(tmp_path, _opts(tmp_path))
    assert not any("docker-compose.cpu.yml" in w for w in result.warnings), result.warnings
    assert "REDIS_URL" in "".join(s.l2_md + s.l3_md for s in result.sections)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_codeingest_composeyaml.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'strata_kb.codeingest.extractors._composeyaml'`.

- [ ] **Step 3: Write the loader**

```python
# src/strata_kb/codeingest/extractors/_composeyaml.py
"""YAML loading for Docker Compose files: `yaml.safe_load` plus Compose's
merge tags `!reset` and `!override` (Compose spec, "Merge and override").

A plain `SafeLoader` has no constructor for either tag and raises
`ConstructorError` for the whole file, so one `!reset` line used to drop
every service and env key the file declares. Every other tag still fails
exactly as it does under `yaml.safe_load`.
"""

from __future__ import annotations

import yaml


class _ComposeLoader(yaml.SafeLoader):
    """SafeLoader that also understands Compose's `!reset` / `!override`."""


def _reset(loader: _ComposeLoader, node: yaml.Node) -> object:
    # `!reset` clears the value an earlier file set; for topology that is
    # the empty value of the node's own kind.
    if isinstance(node, yaml.SequenceNode):
        return []
    if isinstance(node, yaml.MappingNode):
        return {}
    return None


def _override(loader: _ComposeLoader, node: yaml.Node) -> object:
    # `!override` replaces instead of merging; the value itself is plain.
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    tag = loader.resolve(yaml.ScalarNode, node.value, (True, False))
    return loader.yaml_constructors[tag](loader, node)


_ComposeLoader.add_constructor("!reset", _reset)
_ComposeLoader.add_constructor("!override", _override)


def load_compose(text: str) -> object:
    """`yaml.safe_load` for a compose file, `!reset`/`!override` included."""
    return yaml.load(text, Loader=_ComposeLoader)  # noqa: S506 - SafeLoader subclass
```

- [ ] **Step 4: Use it in both compose readers**

In `services.py` `_read_compose` and `integrations.py` `_read_compose_env`, replace only the load call; keep the surrounding `try/except yaml.YAMLError` and warning text unchanged:

```python
from strata_kb.codeingest.extractors._composeyaml import load_compose
...
        try:
            data = load_compose(text)
        except yaml.YAMLError as exc:
            warnings.append(f"could not parse {rel}: {exc}")
            continue
```

Do not touch `_read_k8s`, `_openapi_has_servers`, or any non-compose `yaml.safe_load`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_codeingest_composeyaml.py tests/test_codeingest_extractors.py -q`
Expected: PASS. If `svc.api` is not the id the extractor assigns, read the actual ids from the failing assertion and fix the test's expected ids (the extractor is right about its own slugs).

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/codeingest/extractors/_composeyaml.py src/strata_kb/codeingest/extractors/services.py src/strata_kb/codeingest/extractors/integrations.py tests/test_codeingest_composeyaml.py
git commit -m "fix: code-ingest reads compose files that use !reset/!override"
```

---

### Task 2: `cmd.*` skips workflows `kb init` scaffolds

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/initcmd.py` (add a constant right after `DEV_TEMPLATES`, ~line 241)
- Modify: `src/strata_kb/codeingest/extractors/commands.py` (`_read_ci`, ~line 481)
- Test: `tests/test_codeingest_extractors.py` (class `TestCommandsExtractor`, ~line 2318), `tests/test_init.py`

**Interfaces:**
- Produces: `SCAFFOLDED_WORKFLOW_NAMES: frozenset[str]` in `strata_kb.initcmd`.

- [ ] **Step 1: Write the failing tests**

Append to `TestCommandsExtractor` in `tests/test_codeingest_extractors.py` (module helpers `_opts`, `_by_id`, `cmd_ext` already exist there):

```python
    def test_ci_reader_skips_workflows_kb_init_scaffolds(self, tmp_path):
        # MyFlix field report 2026-09-25: kb-code.yml's `kb build` became
        # cmd.build and kb-pr-lint.yml's `kb pr lint` became cmd.lint, so
        # /dev-plan copied strata's own commands into ticket plans.
        root = tmp_path / "scaffolded"
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "kb-code.yml").write_text(
            "on: [push]\njobs:\n  publish:\n    steps:\n      - run: kb build\n",
            encoding="utf-8",
        )
        (wf / "kb-pr-lint.yml").write_text(
            "on: [pull_request]\njobs:\n  pr-lint:\n    steps:\n"
            '      - run: kb pr lint "$RUNNER_TEMP/body.md"\n',
            encoding="utf-8",
        )
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  ci:\n    steps:\n"
            "      - run: pnpm -r build\n      - run: pnpm -r lint\n",
            encoding="utf-8",
        )
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert "pnpm -r build" in sections["cmd.build"].l2_md.splitlines()[0]
        assert "pnpm -r lint" in sections["cmd.lint"].l2_md.splitlines()[0]
        blob = "".join(s.l2_md + s.l3_md for s in sections.values())
        assert "kb build" not in blob
        assert "kb pr lint" not in blob
```

Append to `tests/test_init.py`:

```python
def test_scaffolded_workflow_names_cover_every_kind():
    from strata_kb.initcmd import SCAFFOLDED_WORKFLOW_NAMES

    assert SCAFFOLDED_WORKFLOW_NAMES == {
        "kb-publish.yml", "kb-ticket-lint.yml", "kb-code.yml", "kb-pr-lint.yml",
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_codeingest_extractors.py -k scaffolds tests/test_init.py -k scaffolded_workflow -q`
Expected: FAIL — `cmd.build` first line is `kb build`; `ImportError: cannot import name 'SCAFFOLDED_WORKFLOW_NAMES'`.

- [ ] **Step 3: Add the constant**

In `initcmd.py`, directly after the closing `}` of `DEV_TEMPLATES`:

```python
# Workflow files `kb init` scaffolds, by file name, across every kind. Their
# `run:` steps are strata's own (`kb build`, `kb pr lint …`), never the
# repo's build/lint/test, so `kb code-ingest`'s CI command reader skips them.
# Derived from the template maps so a new scaffolded workflow is covered
# the moment it is added to one.
SCAFFOLDED_WORKFLOW_NAMES: frozenset[str] = frozenset(
    rel.removeprefix(".github/workflows/")
    for templates in (
        COMMON_TEMPLATES, HUB_TEMPLATES, CHILD_TEMPLATES, BA_TEMPLATES, DEV_TEMPLATES,
    )
    for rel in templates
    if rel.startswith(".github/workflows/")
)
```

- [ ] **Step 4: Skip those files in `_read_ci`**

At the top of `_read_ci`'s body (lazy import: `initcmd` pulls in template machinery the extractor module must not load at import time):

```python
    from strata_kb.initcmd import SCAFFOLDED_WORKFLOW_NAMES
```

and in the file loop, right after the `fnmatch` check:

```python
            if not fnmatch.fnmatch(name, "*.y*ml"):
                continue
            if name in SCAFFOLDED_WORKFLOW_NAMES:
                continue  # strata's own workflow — its commands are not the repo's
```

Extend the docstring's first sentence: "Every `run:` step across every workflow file except those `kb init` scaffolds (`initcmd.SCAFFOLDED_WORKFLOW_NAMES`), in file order …".

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_codeingest_extractors.py tests/test_init.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/initcmd.py src/strata_kb/codeingest/extractors/commands.py tests/test_codeingest_extractors.py tests/test_init.py
git commit -m "fix: cmd.* never comes from a workflow kb init scaffolds"
```

---

### Task 3: One ingest configuration — `code_ingest:` block, version pin note

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/config.py` (`KBConfig`, lines 36–42)
- Create: `src/strata_kb/codeingest/sync.py`
- Modify: `src/strata_kb/cli.py` (`code_ingest`, lines 1119–1227)
- Test: `tests/test_codeingest_sync.py` (create), `tests/test_cli_codeingest.py`

**Interfaces:**
- Produces (in `strata_kb.codeingest.sync`):
  - `KB_CODE_WORKFLOW: Path` = `Path(".github") / "workflows" / "kb-code.yml"`
  - `ci_pin(repo_root: Path) -> str | None`
  - `version_note(repo_root: Path) -> str | None`
  - `options_from_config(repo_root: Path, kb_dir: Path, repo_id: str, *, doc_id: str = "", db: Sequence[Path] = (), tags: Sequence[str] = (), scaffold_svc: bool = False) -> core.CodeIngestOptions`
- Produces (in `strata_kb.config`): `CodeIngestConfig` (`db: list[str]`, `tags: list[str]`), `KBConfig.code_ingest: CodeIngestConfig`.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/test_codeingest_sync.py
from pathlib import Path

import strata_kb
from strata_kb.codeingest import sync
from strata_kb.config import load_config


def _pin(root: Path, version: str) -> None:
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "kb-code.yml").write_text(
        f"jobs:\n  publish:\n    steps:\n      - run: pip install strata-kb=={version}\n",
        encoding="utf-8",
    )


def _config(root: Path, extra: str = "") -> Path:
    kb = root / ".kb"
    kb.mkdir(exist_ok=True)
    (kb / "config.yaml").write_text(f'kind: dev\nrepo_id: "demo"\n{extra}', encoding="utf-8")
    return kb


def test_config_without_the_block_has_empty_lists(tmp_path):
    cfg = load_config(_config(tmp_path)).code_ingest
    assert cfg.db == [] and cfg.tags == []


def test_ci_pin_reads_the_workflow_pin(tmp_path):
    _pin(tmp_path, "1.3.0")
    assert sync.ci_pin(tmp_path) == "1.3.0"


def test_ci_pin_is_none_without_the_workflow(tmp_path):
    assert sync.ci_pin(tmp_path) is None


def test_version_note_only_when_the_pin_differs(tmp_path, monkeypatch):
    _pin(tmp_path, "1.3.0")
    monkeypatch.setattr(strata_kb, "__version__", "1.3.0")
    assert sync.version_note(tmp_path) is None
    monkeypatch.setattr(strata_kb, "__version__", "1.4.0")
    note = sync.version_note(tmp_path)
    assert note is not None and "1.4.0" in note and "1.3.0" in note


def test_options_from_config_uses_the_code_ingest_block(tmp_path):
    kb = _config(tmp_path, "code_ingest:\n  db: [data/app.sqlite]\n  tags: [payments]\n")
    opts = sync.options_from_config(tmp_path, kb, "demo")
    assert opts.doc_id == "demo-code"
    assert opts.db_paths == ((tmp_path / "data" / "app.sqlite").resolve(),)
    assert opts.tags == ("payments",)


def test_flags_replace_the_config_lists(tmp_path):
    kb = _config(tmp_path, "code_ingest:\n  db: [data/app.sqlite]\n  tags: [payments]\n")
    opts = sync.options_from_config(
        tmp_path, kb, "demo", db=[Path("other.sqlite")], tags=["x"]
    )
    assert opts.db_paths == ((tmp_path / "other.sqlite").resolve(),)
    assert opts.tags == ("x",)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_codeingest_sync.py -q`
Expected: FAIL — `ImportError: cannot import name 'sync'` / `AttributeError: 'KBConfig' object has no attribute 'code_ingest'`.

- [ ] **Step 3: Add the config model**

In `config.py`, above `KBConfig`:

```python
class CodeIngestConfig(BaseModel):
    """`code_ingest:` — the one ingest configuration local runs and CI share
    (spec 2026-09-25 §4.2). `db` stays explicit-only, exactly like `--db`:
    a stray test fixture must never become published knowledge."""

    db: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
```

and in `KBConfig` after `langs`:

```python
    code_ingest: CodeIngestConfig = Field(default_factory=CodeIngestConfig)
```

- [ ] **Step 4: Create `sync.py`**

```python
# src/strata_kb/codeingest/sync.py
"""Keeping `<repo_id>-code` in step (spec 2026-09-25): one ingest
configuration shared by local runs and CI, and the CI version pin that
tells whether a local run can match what CI publishes."""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

from strata_kb import config as config_mod
from strata_kb.codeingest import core

KB_CODE_WORKFLOW = Path(".github") / "workflows" / "kb-code.yml"
_PIN_RE = re.compile(r"strata-kb==([^\s\"']+)")


def ci_pin(repo_root: Path) -> str | None:
    """The `strata-kb==<version>` pin in kb-code.yml, or None when the file
    or the pin is absent."""
    try:
        text = (repo_root / KB_CODE_WORKFLOW).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = _PIN_RE.search(text)
    return m.group(1) if m else None


def version_note(repo_root: Path) -> str | None:
    """One line when the installed package differs from CI's pin — different
    extractors, so local -code may differ from what CI publishes."""
    import strata_kb

    pin = ci_pin(repo_root)
    if pin is None or pin == strata_kb.__version__:
        return None
    return (
        f"strata-kb {strata_kb.__version__} is installed but kb-code.yml pins "
        f"{pin} — local -code may differ from what CI publishes"
    )


def options_from_config(
    repo_root: Path,
    kb_dir: Path,
    repo_id: str,
    *,
    doc_id: str = "",
    db: Sequence[Path] = (),
    tags: Sequence[str] = (),
    scaffold_svc: bool = False,
) -> core.CodeIngestOptions:
    """Ingest options from `code_ingest:` in .kb/config.yaml. A non-empty
    `db` or `tags` argument (a CLI flag) replaces that config list for
    this run — it never merges."""
    cfg = config_mod.load_config(kb_dir).code_ingest
    return core.CodeIngestOptions(
        repo_root=repo_root,
        kb_dir=kb_dir,
        doc_id=doc_id or f"{repo_id}-code",
        repo_id=repo_id,
        db_paths=tuple(db) if db else tuple(Path(p) for p in cfg.db),
        tags=tuple(tags) if tags else tuple(cfg.tags),
        scaffold_svc=scaffold_svc,
    )
```

- [ ] **Step 5: Run the unit tests to verify they pass**

Run: `$PY -m pytest tests/test_codeingest_sync.py -q`
Expected: PASS.

- [ ] **Step 6: Write the failing CLI tests**

Append to `tests/test_cli_codeingest.py` (it already has `runner`, `app`, `build_code_repo`, `_init_config`; add `from strata_kb import models` if missing):

```python
def _code_entry(root):
    index = models.load_yaml_model(root / ".kb" / "index.yaml", models.KBIndex)
    return next(d for d in index.docs if d.id == "demo-code")


def test_code_ingest_reads_tags_from_the_config_block(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    with (root / ".kb" / "config.yaml").open("a", encoding="utf-8") as fh:
        fh.write("code_ingest:\n  tags: [payments]\n")
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 0, result.output
    assert "payments" in _code_entry(root).tags
    assert "replace code_ingest" not in result.stderr


def test_code_ingest_flag_replaces_the_config_block_and_says_so(tmp_path):
    root = build_code_repo(tmp_path)
    _init_config(root)
    with (root / ".kb" / "config.yaml").open("a", encoding="utf-8") as fh:
        fh.write("code_ingest:\n  tags: [payments]\n")
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--tags", "other"])
    assert result.exit_code == 0, result.output
    tags = _code_entry(root).tags
    assert "other" in tags and "payments" not in tags
    assert "replace code_ingest" in result.stderr


def test_code_ingest_notes_a_version_pin_mismatch(tmp_path, monkeypatch):
    import strata_kb

    root = build_code_repo(tmp_path)
    _init_config(root)
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "kb-code.yml").write_text("- run: pip install strata-kb==0.0.1\n", encoding="utf-8")
    monkeypatch.setattr(strata_kb, "__version__", "1.4.0")
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb"), "--json"])
    assert result.exit_code == 0, result.output
    assert "kb-code.yml pins 0.0.1" in result.stderr
    json.loads(result.stdout)  # --json stdout stays pure
```

(`import json` at the top if the file lacks it.) If `build_code_repo` already writes a `.github/workflows/kb-code.yml`, the `mkdir(exist_ok=True)` and overwrite still hold.

- [ ] **Step 7: Run them to verify they fail**

Run: `$PY -m pytest tests/test_cli_codeingest.py -q -k "config_block or version_pin"`
Expected: FAIL — `payments` absent from tags; no note on stderr.

- [ ] **Step 8: Route `kb code-ingest` through the config**

In `cli.py` `code_ingest`, change the import line to `from strata_kb.codeingest import core, sync`, and replace the `tag_list = …` line plus the whole `opts = core.CodeIngestOptions(...)` call with:

```python
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    # Spec 2026-09-25 §4.2: `code_ingest:` in .kb/config.yaml is the one
    # configuration local runs and CI share; a flag replaces its list for
    # this run only, and says so below.
    opts = sync.options_from_config(
        resolved_root, resolved_kb_dir, rid, doc_id=did,
        db=list(db), tags=tag_list, scaffold_svc=scaffold_svc,
    )
```

Then, after the `except core.CodeIngestError` block and **before** `if json_out:`:

```python
    notes: list[str] = []
    if db or tag_list:
        notes.append(
            "--db/--tags replace code_ingest: in .kb/config.yaml for this run — "
            "output will differ from what CI publishes"
        )
    pin_note = sync.version_note(resolved_root)
    if pin_note:
        notes.append(pin_note)
    for note in notes:
        typer.secho(f"[note] {note}", fg=typer.colors.YELLOW, err=True)
```

Update the `--db` option help to: `"SQLite file to read (repeatable, explicit only; replaces code_ingest.db for this run)"` and `--tags` help to: `"Extra index tags, comma-separated (replaces code_ingest.tags for this run)"`.

- [ ] **Step 9: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_codeingest_sync.py tests/test_cli_codeingest.py tests/test_config*.py -q`
Expected: PASS. (If no `tests/test_config*.py` exists, drop that pattern.)

- [ ] **Step 10: Commit**

```bash
git add src/strata_kb/config.py src/strata_kb/codeingest/sync.py src/strata_kb/cli.py tests/test_codeingest_sync.py tests/test_cli_codeingest.py
git commit -m "feat: code_ingest config block shared by local runs and CI"
```

---

### Task 4: `index.yaml` stops carrying `-code`'s revision

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/codeingest/core.py` (the `_upsert_index_entry` call for `-code`, lines 501–505)
- Modify: `src/strata_kb/federation.py` (`load_federation`, lines 261–287)
- Test: `tests/test_codeingest_index.py` (create)

**Interfaces:**
- Produces: `-code` index entries always have `revision == ""`; `load_federation()` returns index entries whose empty `revision` is filled from `<entry>/<doc>/_manifest.yaml`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_codeingest_index.py
from strata_kb import models
from strata_kb.codeingest import core
from strata_kb.federation import FederationMeta, load_federation
from tests.fixtures_coderepo import build_code_repo


def test_code_index_entry_is_identical_across_commits(tmp_path, run_git):
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "one")
    opts = core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="demo-code", repo_id="demo"
    )
    core.run(opts)
    first = (root / ".kb" / "index.yaml").read_bytes()
    (root / "NOTES.txt").write_text("changed\n", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "two")
    core.run(opts)
    assert (root / ".kb" / "index.yaml").read_bytes() == first
    manifest = models.load_yaml_model(
        root / ".kb" / "demo-code" / "_manifest.yaml", models.Manifest
    )
    assert manifest.revision == run_git(root, "rev-parse", "--short=7", "HEAD")


def _entry(tmp_path, index_revision: str):
    entry = tmp_path / "federation" / "demo"
    (entry / "demo-code").mkdir(parents=True)
    models.save_yaml_model(
        entry / "demo-code" / "_manifest.yaml",
        models.Manifest(id="demo-code", title="t", revision="abc1234"),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="demo-code", title="t", revision=index_revision)]),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id="demo", source_commit="abc1234",
                       published_at="2026-09-25T00:00:00+00:00"),
    )
    return tmp_path / "federation"


def test_load_federation_fills_an_empty_revision_from_the_manifest(tmp_path):
    [repo] = load_federation(_entry(tmp_path, ""))
    assert repo.index.docs[0].revision == "abc1234"


def test_load_federation_keeps_a_recorded_revision(tmp_path):
    [repo] = load_federation(_entry(tmp_path, "fff0000"))
    assert repo.index.docs[0].revision == "fff0000"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_codeingest_index.py -q`
Expected: FAIL — `index.yaml` bytes differ (revision changed); empty revision stays `""`.

- [ ] **Step 3: Write `-code`'s index entry without a revision**

In `core.run`, lines 501–505:

```python
    # Spec 2026-09-25 §4.1: `-code` is gitignored, `index.yaml` is not — a
    # revision here would churn the committed index on every local ingest.
    # The manifest carries the revision; federation.load_federation reads it.
    _upsert_index_entry(
        opts.kb_dir, opts.doc_id, manifest.title, "",
        f"Generated code knowledge for the {opts.repo_id} repository.",
        ["code", "generated"], opts.tags, report,
    )
```

Leave the `-svc` call (line ~1267) unchanged.

- [ ] **Step 4: Fill empty revisions in `load_federation`**

In `federation.py`, add above `load_federation`:

```python
def _with_manifest_revisions(index: models.KBIndex, entry_dir: Path) -> models.KBIndex:
    """An index entry with no `revision` takes its document's manifest
    revision. code-ingest leaves `-code`'s index revision empty so a dev
    repo's committed `index.yaml` never churns (spec 2026-09-25 §4.1);
    every reader of `IndexEntry.revision` goes through here."""
    for doc in index.docs:
        if doc.revision:
            continue
        try:
            manifest = models.load_yaml_model(
                entry_dir / doc.id / "_manifest.yaml", models.Manifest
            )
        except (OSError, yaml.YAMLError, ValidationError, UnicodeDecodeError):
            continue
        doc.revision = manifest.revision
    return index
```

and in `load_federation`, change `index=index,` to `index=_with_manifest_revisions(index, child),`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_codeingest_index.py tests/test_federation*.py tests/test_codeingest_scaffold.py tests/test_cli_codeingest.py -q`
Expected: PASS. A test that asserted a `-code` index entry's revision equals the commit must now assert `""` (index) and the commit on the manifest — update it, do not revert the change.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/codeingest/core.py src/strata_kb/federation.py tests/test_codeingest_index.py
git commit -m "feat: -code revision lives in its manifest, not the committed index"
```

---

### Task 5: `ensure_code_fresh()`

**Depends on:** Task 3

**Files:**
- Modify: `src/strata_kb/codeingest/sync.py`
- Test: `tests/test_codeingest_sync.py`

**Interfaces:**
- Consumes: `options_from_config`, `version_note` (Task 3); `core._head_commit`, `core._git`, `core.run`.
- Produces:
  - `FreshResult` dataclass: `regenerated: bool`, `reason: str = ""`, `report: core.CodeIngestReport | None = None`, `notes: list[str]`.
  - `has_code_doc(kb_dir: Path, repo_id: str) -> bool`
  - `ensure_code_fresh(kb_dir: Path, repo_id: str, repo_root: Path | None = None) -> FreshResult` — raises `core.CodeIngestError` when the ingest refuses. `reason` is one of `"missing"`, `"no git"`, `"unreadable manifest"`, `"revision"`, `"dirty"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_codeingest_sync.py`:

```python
import pytest

from tests.fixtures_coderepo import build_code_repo


@pytest.fixture
def repo(tmp_path, run_git):
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    _config(root)
    (root / ".gitignore").write_text(".kb/*-code/\n", encoding="utf-8")
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    return root


def test_regenerates_when_missing_then_is_a_no_op(repo):
    first = sync.ensure_code_fresh(repo / ".kb", "demo")
    assert first.regenerated and first.reason == "missing"
    assert (repo / ".kb" / "demo-code" / "_manifest.yaml").is_file()
    assert not sync.ensure_code_fresh(repo / ".kb", "demo").regenerated


def test_regenerates_after_a_new_commit(repo, run_git):
    sync.ensure_code_fresh(repo / ".kb", "demo")
    (repo / "NOTES.txt").write_text("x\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "two")
    assert sync.ensure_code_fresh(repo / ".kb", "demo").reason == "revision"


def test_regenerates_on_a_tracked_change(repo):
    sync.ensure_code_fresh(repo / ".kb", "demo")
    (repo / "docker-compose.yml").write_text(
        (repo / "docker-compose.yml").read_text(encoding="utf-8") + "\n", encoding="utf-8"
    )
    assert sync.ensure_code_fresh(repo / ".kb", "demo").reason == "dirty"


def test_an_untracked_file_or_a_kb_edit_does_not_trigger(repo):
    sync.ensure_code_fresh(repo / ".kb", "demo")
    (repo / "scratch.txt").write_text("x\n", encoding="utf-8")
    cfg = repo / ".kb" / "config.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    assert not sync.ensure_code_fresh(repo / ".kb", "demo").regenerated


def test_a_non_git_directory_always_regenerates(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    build_code_repo(root)
    _config(root)
    sync.ensure_code_fresh(root / ".kb", "demo")
    assert sync.ensure_code_fresh(root / ".kb", "demo").reason == "no git"


def test_has_code_doc(repo):
    assert not sync.has_code_doc(repo / ".kb", "demo")
    sync.ensure_code_fresh(repo / ".kb", "demo")
    assert sync.has_code_doc(repo / ".kb", "demo")
```

(The fixture's compose file is `docker-compose.yml` at the repo root; if `build_code_repo` names it differently, use that file.)

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_codeingest_sync.py -q`
Expected: FAIL — `AttributeError: module 'strata_kb.codeingest.sync' has no attribute 'ensure_code_fresh'`.

- [ ] **Step 3: Implement**

Append to `sync.py` (add `from dataclasses import dataclass, field`, `import yaml`, `from pydantic import ValidationError`, `from strata_kb import models` to the imports):

```python
@dataclass
class FreshResult:
    regenerated: bool
    reason: str = ""
    report: core.CodeIngestReport | None = None
    notes: list[str] = field(default_factory=list)


def has_code_doc(kb_dir: Path, repo_id: str) -> bool:
    """This repo already has a `-code` document: its directory, or its
    `index.yaml` entry (a fresh clone of a migrated repo has only that)."""
    doc_id = f"{repo_id}-code"
    if (kb_dir / doc_id).is_dir():
        return True
    try:
        index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    except (OSError, yaml.YAMLError, ValidationError, UnicodeDecodeError):
        return False
    return any(d.id == doc_id for d in index.docs)


def _stale_reason(repo_root: Path, kb_dir: Path, doc_id: str) -> str:
    """Why `-code` must be regenerated, or "" when it matches the tree."""
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        return "missing"
    head = core._head_commit(repo_root)
    if not head:
        return "no git"
    try:
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
    except (OSError, yaml.YAMLError, ValidationError, UnicodeDecodeError):
        return "unreadable manifest"
    if manifest.revision != head[:7]:
        return "revision"
    # Tracked changes only (an untracked file is invisible to the tree
    # extractor's `git ls-files`), and never under .kb/: edits there do not
    # change -code, and a still-tracked -code in an unmigrated repo would
    # otherwise re-trigger itself on every call.
    args = ["status", "--porcelain", "--untracked-files=no", "--", "."]
    try:
        args.append(f":(exclude){kb_dir.relative_to(repo_root).as_posix()}")
    except ValueError:
        pass  # .kb outside the repo: nothing to exclude
    proc = core._git(repo_root, *args)
    if proc.returncode != 0 or proc.stdout.strip():
        return "dirty"
    return ""


def ensure_code_fresh(
    kb_dir: Path, repo_id: str, repo_root: Path | None = None
) -> FreshResult:
    """Regenerate `<repo_id>-code` when it is missing, older than HEAD, or
    the tracked tree has changes outside .kb/ (spec 2026-09-25 §4.1).
    Never scaffolds -svc. Raises core.CodeIngestError when the ingest
    refuses; callers print it."""
    kb_abs = kb_dir.resolve()
    root = (repo_root or kb_abs.parent).resolve()
    opts = options_from_config(root, kb_abs, repo_id)
    reason = _stale_reason(root, kb_abs, opts.doc_id)
    if not reason:
        return FreshResult(regenerated=False)
    report = core.run(opts)
    notes = [f"refreshed {opts.doc_id} from the working tree ({reason})"]
    pin_note = version_note(root)
    if pin_note:
        notes.append(pin_note)
    return FreshResult(regenerated=True, reason=reason, report=report, notes=notes)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_codeingest_sync.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/codeingest/sync.py tests/test_codeingest_sync.py
git commit -m "feat: ensure_code_fresh regenerates -code only when the tree moved"
```

---

### Task 6: `kb svc note`, `kb build`, `kb publish` refresh `-code` first

**Depends on:** Task 5

**Files:**
- Modify: `src/strata_kb/cli.py` (`svc_note` ~1230; `build` ~1089; `publish` ~1774; new helpers near `_hub_or_exit` ~611)
- Modify: `src/strata_kb/svcnote.py` (unknown-service error, lines 324–350)
- Test: `tests/test_cli_code_refresh.py` (create); `tests/test_svcnote.py` (wording updates only)

**Interfaces:**
- Consumes: `sync.ensure_code_fresh`, `sync.has_code_doc`, `FreshResult.notes`.
- Produces: `_refresh_code_or_exit(kb_dir: Path, repo_id: str) -> None` and `_refresh_dev_code(kb_dir: Path) -> None` in `cli.py`; `--no-refresh` on `kb svc note` and `kb build`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_code_refresh.py
from pathlib import Path

from typer.testing import CliRunner

from strata_kb import cli
from strata_kb.cli import app
from strata_kb.codeingest import core
from tests.fixtures_coderepo import build_code_repo

runner = CliRunner()

_BILLING = "services:\n  billing-service:\n    image: billing:1\n"


def _dev_repo(tmp_path: Path, run_git) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    kb = root / ".kb"
    kb.mkdir(exist_ok=True)
    (kb / "config.yaml").write_text(
        'kind: dev\nhub: ""\nrepo_id: "demo"\nintake: ""\n', encoding="utf-8"
    )
    (root / ".gitignore").write_text(".kb/*-code/\n", encoding="utf-8")
    core.run(core.CodeIngestOptions(
        repo_root=root, kb_dir=kb, doc_id="demo-code", repo_id="demo", scaffold_svc=True,
    ))
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    return root


def _add_billing(root: Path, run_git) -> None:
    (root / "compose.billing.yml").write_text(_BILLING, encoding="utf-8")
    run_git(root, "add", "compose.billing.yml")


def _note(root: Path, *extra: str):
    return runner.invoke(app, [
        "svc", "note", "billing-service", "--ticket", "T-1", "--title", "Billing",
        "--kb-dir", str(root / ".kb"), *extra,
    ])


def test_svc_note_finds_a_service_the_ticket_just_added(tmp_path, run_git):
    root = _dev_repo(tmp_path, run_git)
    _add_billing(root, run_git)
    result = _note(root)
    assert result.exit_code == 0, result.output
    assert "refreshed demo-code" in result.stderr


def test_svc_note_no_refresh_reads_the_document_as_it_is(tmp_path, run_git):
    root = _dev_repo(tmp_path, run_git)
    _add_billing(root, run_git)
    result = _note(root, "--no-refresh")
    assert result.exit_code == 1
    assert "unknown service 'billing-service'" in result.output
    assert "git add" in result.output


def test_build_refreshes_code_in_a_dev_repo(tmp_path, run_git):
    root = _dev_repo(tmp_path, run_git)
    _add_billing(root, run_git)
    result = runner.invoke(app, ["build", "--kb-dir", str(root / ".kb"), "--allow-pending"])
    assert result.exit_code == 0, result.output
    assert "refreshed demo-code" in result.stderr
    assert "svc.billing-service" in (root / ".kb" / "demo-code" / "services.md").read_text(encoding="utf-8")


def test_build_before_the_seed_does_not_ingest(tmp_path):
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text('kind: dev\nrepo_id: "demo"\n', encoding="utf-8")
    (kb / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    result = runner.invoke(app, ["build", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "refreshed" not in result.stderr
    assert not (kb / "demo-code").exists()


def test_publish_refreshes_before_anything_else(tmp_path, monkeypatch):
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text('kind: dev\nrepo_id: "demo"\nhub: ""\n', encoding="utf-8")
    seen: list[Path] = []
    monkeypatch.setattr(cli, "_refresh_dev_code", lambda kb_dir: seen.append(kb_dir))
    runner.invoke(app, ["publish", "--kb-dir", str(kb)])  # fails later: no hub
    assert seen == [kb]
```

If the services extractor slugs `billing-service` differently, take the id from `demo-code/services.md` in the failing run and use it in all three places.

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_cli_code_refresh.py -q`
Expected: FAIL — `unknown service`, `No such option: --no-refresh`, `AttributeError: ... '_refresh_dev_code'`.

- [ ] **Step 3: Add the two helpers to `cli.py`**

Directly after `_hub_or_exit`:

```python
def _refresh_code_or_exit(kb_dir: Path, repo_id: str) -> None:
    """Bring `<repo_id>-code` up to the working tree before a command reads
    it (spec 2026-09-25 §4.1). Notes go to stderr so --json stays pure."""
    from strata_kb.codeingest import core, sync

    try:
        result = sync.ensure_code_fresh(kb_dir, repo_id)
    except core.CodeIngestError as exc:
        typer.secho(
            f"could not refresh {repo_id}-code: {exc}", fg=typer.colors.RED, err=True
        )
        raise typer.Exit(1)
    for note in result.notes:
        typer.secho(f"[note] {note}", fg=typer.colors.YELLOW, err=True)


def _refresh_dev_code(kb_dir: Path) -> None:
    """`kb build` / `kb publish` in a dev repo: refresh `-code` first — but
    only once the repo has one, so a repo before /dev-code-seed builds and
    publishes exactly as before. Any other kind: no-op."""
    from strata_kb.codeingest import sync
    from strata_kb.config import load_config

    try:
        cfg = load_config(kb_dir)
    except (*_CONFIG_READ_ERRORS, OSError):
        return  # the command's own config read reports a broken file
    if cfg.kind != "dev" or not cfg.repo_id or not sync.has_code_doc(kb_dir, cfg.repo_id):
        return
    _refresh_code_or_exit(kb_dir, cfg.repo_id)
```

- [ ] **Step 4: Wire `kb svc note`**

Add the option after `repo_id`:

```python
    no_refresh: bool = typer.Option(
        False, "--no-refresh",
        help="Read <repo_id>-code as it is; skip regenerating it from the working tree",
    ),
```

and after the `rid is None` block:

```python
    if not no_refresh:
        _refresh_code_or_exit(kb_dir, rid)
```

- [ ] **Step 5: Wire `kb build`**

Add the option after `strict`:

```python
    no_refresh: bool = typer.Option(
        False, "--no-refresh",
        help="Dev repo: validate <repo_id>-code as it is; skip regenerating it first",
    ),
```

and as the first statement after the `from strata_kb.build import build_kb` import:

```python
    # Dev repo (spec 2026-09-25 §4.1): validate what the merge would
    # publish — on a PR checkout -code is absent until this regenerates it.
    if not no_refresh:
        _refresh_dev_code(kb_dir)
```

- [ ] **Step 6: Wire `kb publish`**

Right after `mode = "pr" if pr else "direct" if direct else "auto"` (~line 1774):

```python
    # Spec 2026-09-25 §4.4: a hand publish sends the -code CI would send for
    # this commit — never a stale or summarized copy. No --no-refresh here:
    # skipping it is exactly the divergence this prevents.
    if cfg.kind == "dev":
        _refresh_dev_code(kb_dir)
```

- [ ] **Step 7: Rewrite the unknown-service error**

In `svcnote.py`, replace the comment block and `raise` at lines 325–350 with:

```python
        # Spec 2026-09-25 §4.1: `kb svc note` regenerates -code from the
        # working tree first, so a stale snapshot is no longer a cause. Two
        # remain: a typo (mind the opaque hash suffix on a name over 40
        # characters, Ruling R1), or a new service whose files git does not
        # track yet — the tree extractor lists files with `git ls-files`.
        raise SvcNoteError(
            f"unknown service '{service}' — no svc.{service} section in "
            f"{code_doc_id} (list the real ids in "
            f"{code_doc_id}/_manifest.yaml or services.md and copy one "
            "verbatim — a service name longer than 40 characters carries "
            "an opaque 6-hex-character hash suffix, e.g. "
            "'-a1b2c3', that must be copied exactly, never retyped. "
            "If the service is new, `git add` its files first: "
            f"{code_doc_id} only sees files git tracks)"
        )
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_cli_code_refresh.py tests/test_svcnote.py tests/test_cli_codeingest.py tests/test_build*.py tests/test_publish*.py -q`
Expected: PASS. A `test_svcnote.py` assertion on the old wording ("never writes back", "snapshot") is updated to the new wording (`git add`); a `kb build` test that runs in a dev repo with a `-code` entry and no git may now regenerate — pass `--no-refresh` in that test only if it is not about refresh.

- [ ] **Step 9: Commit**

```bash
git add src/strata_kb/cli.py src/strata_kb/svcnote.py tests/test_cli_code_refresh.py tests/test_svcnote.py
git commit -m "feat: svc note, build and publish refresh -code from the working tree"
```

---

### Task 7: `kb ticket check` reads the hub first

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/cli.py` (`ticket_check`: `--hub` help ~2450–2456, `load_doc` closure ~2499–2507)
- Test: `tests/test_cli_ticket_check.py`

**Interfaces:**
- Consumes: `_hub_or_reason(hub_flag, kb_dir) -> tuple[HubHandle | None, str]`, `ticketcheck.load_from_hub`, `ticketcheck.load_doc_dir`.
- Produces: `[note] <doc> read from <local> (local fallback — <reason>)` when the local copy is used.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_ticket_check.py` (it has `runner`, `app`, `ticket`, `grounding`, `_publish_to_hub`, fixtures `code_doc`, `fed_hub`, `run_git`; add `from strata_kb import models` if missing):

```python
def test_hub_copy_wins_over_a_local_copy(code_doc, fed_hub, run_git, tmp_path):
    # Spec 2026-09-25 §4.1: a dev repo's local -code is regenerated from its
    # branch, so its revision is never the one the SA grounded on.
    kb_dir, rev = code_doc
    _publish_to_hub(fed_hub, kb_dir, "demo", run_git)
    manifest_path = kb_dir / "demo-code" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.revision = "0000000"
    models.save_yaml_model(manifest_path, manifest)
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir),
                                 "--hub", str(fed_hub)])
    assert result.exit_code == 0, result.output
    assert "[note] demo-code read from hub federation/demo" in result.output


def test_local_copy_is_the_fallback_when_no_hub_is_reachable(code_doc, tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 0, result.output
    assert "(local fallback" in result.output
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_cli_ticket_check.py -q -k "hub_copy_wins or local_copy_is_the_fallback"`
Expected: FAIL — the first reports `stale grounding` (local read first); the second lacks `(local fallback`.

- [ ] **Step 3: Replace the `load_doc` closure**

```python
    def load_doc(repo: str | None, doc: str) -> ticketcheck.LoadedDoc | None:
        # Hub first (spec 2026-09-25 §4.1): the SA grounded on the hub copy,
        # and a dev repo's local -code is regenerated from its working tree,
        # so its revision is the branch's, never the grounding's. The local
        # copy is the fallback when no hub is reachable or the hub does not
        # hold the doc (the hub's own checkout, a doc not published yet).
        handle, reason = _hub_or_reason(hub, kb_dir)
        if handle is not None:
            found = ticketcheck.load_from_hub(handle.federation_dir, repo, doc)
            if found is not None:
                return found
            reason = "not on the hub"
        local = kb_dir / doc
        if (local / "_manifest.yaml").exists():
            return ticketcheck.load_doc_dir(local, f"{local} (local fallback — {reason})")
        if handle is None:
            typer.secho(reason or "hub unavailable", fg=typer.colors.RED)
            raise typer.Exit(1)
        return None
```

Change the `--hub` option help to: `"kb-hub URL/path (empty = config); read first — the -code document under --kb-dir is the fallback"`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_cli_ticket_check.py tests/test_ticketcheck.py -q`
Expected: PASS. An existing assertion `"[note] demo-code read from <local path>"` for a local-only run becomes a check for `"(local fallback"`; update it.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/cli.py tests/test_cli_ticket_check.py
git commit -m "feat: ticket check grounds against the hub copy first"
```

---

### Task 8: `kb summarize` never touches generated documents

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/summarize.py` (`collect_pending` ~116, `plan_redo` ~492, new `GENERATED_TAG` / `generated_doc_ids`)
- Modify: `src/strata_kb/cli.py` (`summarize` ~800–845, new helper)
- Test: `tests/test_summarize_generated.py` (create)

**Interfaces:**
- Produces: `summarize.GENERATED_TAG = "generated"`, `summarize.generated_doc_ids(kb_dir: Path) -> set[str]`, `cli._refuse_generated_or_note(kb_dir: Path, doc_id: str) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_summarize_generated.py
from pathlib import Path

from typer.testing import CliRunner

from strata_kb import models, summarize
from strata_kb.cli import app
from strata_kb.codeingest import core
from tests.fixtures_coderepo import build_code_repo

runner = CliRunner()


def _kb(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    core.run(core.CodeIngestOptions(
        repo_root=root, kb_dir=root / ".kb", doc_id="demo-code", repo_id="demo",
        scaffold_svc=True,
    ))
    return root / ".kb"


def test_generated_doc_ids(tmp_path):
    assert summarize.generated_doc_ids(_kb(tmp_path)) == {"demo-code"}


def test_plan_redo_all_skips_generated_documents(tmp_path):
    # The route that put an LLM summary into MyFlix's -code (2026-09-22):
    # `kb summarize --redo --all` reset code-ingest's `summarized` rows.
    plan = summarize.plan_redo(_kb(tmp_path), None)
    assert plan.items and all(i.doc_id != "demo-code" for i in plan.items)


def test_collect_pending_skips_generated_documents(tmp_path):
    kb = _kb(tmp_path)
    path = kb / "demo-code" / "_manifest.yaml"
    manifest = models.load_yaml_model(path, models.Manifest)
    manifest.sections[0].status = "pending"
    models.save_yaml_model(path, manifest)
    assert all(p.doc_id != "demo-code" for p in summarize.collect_pending(kb))


def test_cli_refuses_a_generated_document(tmp_path):
    result = runner.invoke(app, ["summarize", "demo-code", "--kb-dir", str(_kb(tmp_path)),
                                 "--llm", "none"])
    assert result.exit_code == 1
    assert "never summarized" in result.output


def test_cli_notes_the_skip_on_an_all_documents_run(tmp_path):
    result = runner.invoke(app, ["summarize", "--redo", "--all", "--dry-run",
                                 "--kb-dir", str(_kb(tmp_path))])
    assert "skipped generated document(s): demo-code" in result.stderr
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_summarize_generated.py -q`
Expected: FAIL — `AttributeError: module 'strata_kb.summarize' has no attribute 'generated_doc_ids'`.

- [ ] **Step 3: Implement in `summarize.py`**

Near the top, after the imports:

```python
# code-ingest tags every `-code` document `generated`. Its L1/L2 are
# deterministic; an LLM summary would make the published text depend on
# who published last (spec 2026-09-25 §4.4), so summarize never touches it.
GENERATED_TAG = "generated"


def generated_doc_ids(kb_dir: Path) -> set[str]:
    """Documents `kb code-ingest` owns — never summarized, never redone."""
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    return {e.id for e in index.docs if GENERATED_TAG in e.tags}
```

In `collect_pending`'s loop and in `plan_redo`'s loop, right after the `if doc_id and entry.id != doc_id: continue` line:

```python
        if GENERATED_TAG in entry.tags:
            continue
```

- [ ] **Step 4: Implement in `cli.py`**

Add above `_dispatch_summarize`:

```python
def _refuse_generated_or_note(kb_dir: Path, doc_id: str) -> None:
    """Spec 2026-09-25 §4.4: -code has one producer, `kb code-ingest`."""
    from strata_kb.summarize import generated_doc_ids

    generated = generated_doc_ids(kb_dir)
    if doc_id and doc_id in generated:
        typer.secho(
            f"{doc_id} is generated by `kb code-ingest` and is never summarized — "
            "re-run `kb code-ingest` to regenerate it",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if not doc_id and generated:
        typer.secho(
            f"[note] skipped generated document(s): {', '.join(sorted(generated))}",
            fg=typer.colors.YELLOW,
            err=True,
        )
```

In `summarize`, between `_validate_summarize_args(...)` and `_dispatch_summarize(...)`:

```python
    _refuse_generated_or_note(kb_dir, doc_id)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_summarize_generated.py tests/test_summarize*.py tests/test_cli_summarize*.py -q`
Expected: PASS. (Drop patterns that match no file.)

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/summarize.py src/strata_kb/cli.py tests/test_summarize_generated.py
git commit -m "feat: kb summarize never touches a generated -code document"
```

---

### Task 9: `kb init --kind dev` ignores `-code`; template and skill text

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/initcmd.py` (`init_repo`'s `if kind == KIND_DEV:` block ~494; new helper after `_apply_gitignore` ~300)
- Modify: `src/strata_kb/templates/init/kb-code.yml`
- Modify (all that contain the phrases below): `src/strata_kb/templates/init/{claude-skill,claude-command,cursor}-dev-{plan,implement-ticket,handover}.md`, `src/strata_kb/templates/init/copilot-dev-{plan,implement-ticket,handover}.prompt.md`
- Test: `tests/test_init.py`, `tests/test_templates.py`

**Interfaces:**
- Produces: `initcmd._CODE_DOC_LINE = ".kb/*-code/"`, `initcmd._ensure_code_doc_ignored(target: Path, report: InitReport) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_init.py`:

```python
def test_init_dev_gitignores_the_code_document(tmp_path: Path):
    init_repo(tmp_path, "dev")
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".kb/*-code/" in lines


def test_init_dev_appends_to_an_existing_gitignore_once(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    init_repo(tmp_path, "dev")
    init_repo(tmp_path, "dev")
    lines = (tmp_path / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "node_modules/"
    assert lines.count(".kb/*-code/") == 1


def test_kb_code_workflow_points_db_flags_to_the_config():
    from importlib import resources

    text = resources.files("strata_kb").joinpath("templates/init/kb-code.yml").read_text(encoding="utf-8")
    assert "code_ingest" in text
    assert "--db <path>" not in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_init.py -q -k "gitignore or kb_code_workflow"`
Expected: FAIL — no `.gitignore` written for kind dev; template still says `--db <path>`.

- [ ] **Step 3: Add the helper and call it**

In `initcmd.py`, after `_apply_gitignore`:

```python
_CODE_DOC_LINE = ".kb/*-code/"


def _ensure_code_doc_ignored(target: Path, report: InitReport) -> None:
    """Dev repos: `-code` is derived on demand and never committed (spec
    2026-09-25 §4.1). A glob, because repo_id is often unset at init time
    and `-code` is a reserved suffix. Append-only, like `_apply_gitignore`."""
    dest = target / ".gitignore"
    if not dest.exists():
        dest.write_text(_CODE_DOC_LINE + "\n", encoding="utf-8", newline="\n")
        report.created.append(".gitignore")
        return
    try:
        lines = dest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        report.notes.append(
            ".gitignore is not readable as UTF-8; left untouched. "
            f"Add `{_CODE_DOC_LINE}` to it by hand."
        )
        return
    if any(line.strip() == _CODE_DOC_LINE for line in lines):
        return
    lines.append(_CODE_DOC_LINE)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    report.updated.append(".gitignore")
```

In `init_repo`, first line inside `if kind == KIND_DEV:`:

```python
        _ensure_code_doc_ignored(target, report)
```

- [ ] **Step 4: Update `kb-code.yml`**

Replace the validate-job comment (lines 18–20) with:

```yaml
  # PR: validate only. Never publishes. `kb build` regenerates -code from
  # the merge ref first (it is never committed), so this validates what the
  # merge would publish — and catches a malformed -svc edit or a `pending`
  # section committed before review, before merge, not after.
```

Replace the comment block above `- run: kb code-ingest` (lines 46–54) with:

```yaml
      # Ingest configuration (SQLite paths, extra tags) lives in
      # .kb/config.yaml under `code_ingest:` — shared with every local
      # refresh, and safe from `kb init --kind dev`, which overwrites this
      # file on every re-run. Never add --db flags here.
      # NOTE: the flag that scaffolds a placeholder -svc document is
      # deliberately never passed here. CI must not create `pending` content
      # — it would fail its own `kb build` step. Seeding and amending the
      # curated -svc document are human, local actions (see /dev-code-seed).
```

- [ ] **Step 5: Update the dev skill text (every flavour that carries it)**

Find the files: `grep -ln "kb code-ingest\` first\|code-ingest\` not yet run\|not yet generated (\`kb code-ingest" src/strata_kb/templates/init/*.md`. Apply the same replacement in each, keeping each file's own line wrapping:

`dev-handover` — replace the sentence

> If the ticket added or renamed a service, run `kb code-ingest` first — `kb svc note` validates the service against this repo's own committed `<repo_id>-code`, which CI regenerates on the hub but never writes back here.

with

> `kb svc note` regenerates `<repo_id>-code` from the working tree first, so a service the ticket added is found once its files are tracked (`git add`).

`dev-plan` — replace

> when `-code §cmd.*` has not been generated in this repo (`kb code-ingest` not yet run),

with

> when `-code §cmd.*` has no entry (this repo has not run `/dev-code-seed` yet, or code-ingest found no such command),

`dev-implement-ticket` — replace

> A document missing from the hub means either not yet generated (`kb code-ingest` for `<repo_id>-code`, `dev-code-seed` for `<repo_id>-svc`) or generated and not yet published — check `.kb/<repo_id>-code/` and `.kb/<repo_id>-svc/` locally: present → say "generated, unpublished: run `kb publish`" in one line; absent → "not generated".

with

> A `<repo_id>-code` missing from the hub is not yet published — CI publishes it on merge to the default branch; `kb doctor` says whether the hub lags. A `<repo_id>-svc` missing from the hub is either not yet seeded (`dev-code-seed`) or seeded and not yet published — check `.kb/<repo_id>-svc/` locally: present → say "seeded, unpublished: run `kb publish --pr`" in one line; absent → "not seeded".

Keep the sentence that follows ("Reads stay hub-only either way; …") unchanged.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_init.py tests/test_templates.py -q`
Expected: PASS. `test_init.py`'s dev file-list expectation (`expected_files("dev")` vs `report.created`) must now include `.gitignore` — update the expectation, not the code. If `test_templates.py` enforces identical shared blocks across flavours, a flavour you missed will fail there; fix that file.

- [ ] **Step 7: Commit**

```bash
git add src/strata_kb/initcmd.py src/strata_kb/templates/init tests/test_init.py tests/test_templates.py
git commit -m "feat: kb init --kind dev gitignores -code; workflow and skills follow"
```

---

### Task 10: `kb doctor` dev-repo sync checks

**Depends on:** Task 3

**Files:**
- Modify: `src/strata_kb/doctor.py` (`_kb_tree_digest` ~336; `check_hub` ~469 and its digest block ~854; new `check_dev_sync`)
- Modify: `src/strata_kb/cli.py` (`doctor`, the `else:` branch ~3086–3088)
- Test: `tests/test_doctor_checks.py`

**Interfaces:**
- Consumes: `sync.KB_CODE_WORKFLOW`, `sync.version_note` (Task 3).
- Produces:
  - `_kb_tree_digest(root, synthesized=None, exclude_docs: frozenset[str] = frozenset()) -> str`
  - `check_hub(..., code_doc: str | None = None)` — keyword-only, new.
  - `check_dev_sync(kb_dir: Path, repo_root: Path, repo_id: str | None) -> list[Issue]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_doctor_checks.py` (it has `_minimal_kb`; add imports `shutil`, `import strata_kb`, `from strata_kb import models`, `from strata_kb.federation import FederationMeta`, `from strata_kb.hub import HubHandle` as needed):

```python
def _workflow(root, body):
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "kb-code.yml").write_text(body, encoding="utf-8")


def test_dev_sync_warns_on_db_flags_in_the_workflow(tmp_path):
    kb = _minimal_kb(tmp_path, kind="dev")
    _workflow(tmp_path, "      - run: kb code-ingest --db data/app.sqlite\n")
    msgs = [i.message for i in doctor.check_dev_sync(kb, tmp_path, "child")]
    assert any("code_ingest.db" in m for m in msgs)


def test_dev_sync_warns_on_a_version_pin_mismatch(tmp_path, monkeypatch):
    kb = _minimal_kb(tmp_path, kind="dev")
    _workflow(tmp_path, "      - run: pip install strata-kb==0.0.1\n")
    monkeypatch.setattr(strata_kb, "__version__", "1.4.0")
    msgs = [i.message for i in doctor.check_dev_sync(kb, tmp_path, "child")]
    assert any("pins 0.0.1" in m for m in msgs)


def test_dev_sync_warns_on_a_tracked_code_document(tmp_path, run_git):
    kb = _minimal_kb(tmp_path, kind="dev")
    (kb / "child-code").mkdir()
    (kb / "child-code" / "services.md").write_text("# x\n", encoding="utf-8")
    run_git(tmp_path, "init")
    run_git(tmp_path, "add", "-A")
    run_git(tmp_path, "commit", "-m", "init")
    msgs = [i.message for i in doctor.check_dev_sync(kb, tmp_path, "child")]
    assert any("git rm -r --cached .kb/child-code" in m for m in msgs)


def test_dev_sync_is_quiet_on_a_clean_repo(tmp_path, run_git):
    kb = _minimal_kb(tmp_path, kind="dev")
    run_git(tmp_path, "init")
    run_git(tmp_path, "add", "-A")
    run_git(tmp_path, "commit", "-m", "init")
    assert doctor.check_dev_sync(kb, tmp_path, "child") == []


def test_digest_can_exclude_the_code_document(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    for root in (a, b):
        (root / "child-svc").mkdir(parents=True)
        (root / "child-svc" / "services.md").write_text("# same\n", encoding="utf-8")
        (root / "child-code").mkdir()
    (a / "child-code" / "services.md").write_text("# branch A\n", encoding="utf-8")
    (b / "child-code" / "services.md").write_text("# branch B\n", encoding="utf-8")
    assert doctor._kb_tree_digest(a) != doctor._kb_tree_digest(b)
    skip = frozenset({"child-code"})
    assert doctor._kb_tree_digest(a, exclude_docs=skip) == doctor._kb_tree_digest(b, exclude_docs=skip)


def test_check_hub_ignores_the_code_document_for_a_dev_repo(tmp_path):
    kb = _minimal_kb(tmp_path, kind="dev")
    hub = tmp_path / "hub"
    (hub / ".kb").mkdir(parents=True)
    (hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    entry = hub / "federation" / "child"
    shutil.copytree(kb, entry)
    models.save_yaml_model(entry / "_meta.yaml", FederationMeta(
        repo_id="child", source_commit="abc1234", published_at="2026-09-25T00:00:00+00:00",
    ))
    write_federation_index(hub / "federation")  # from strata_kb.federation
    (kb / "child-code").mkdir()
    (kb / "child-code" / "services.md").write_text("# local branch\n", encoding="utf-8")
    handle = HubHandle(root=hub)
    dev_issues, _ = doctor.check_hub(kb, handle, repo_id="child", code_doc="child-code")
    assert not any("differs from the published snapshot" in i.message for i in dev_issues)
    issues, _ = doctor.check_hub(kb, handle, repo_id="child")
    assert any("differs from the published snapshot" in i.message for i in issues)
```

If `pubgate.is_kb_artifact` excludes `config.yaml` from the digest, the `copytree` including it is harmless; if it does not, add `ignore=shutil.ignore_patterns("config.yaml")` to both the copy and nothing else.

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_doctor_checks.py -q -k "dev_sync or exclude_the_code or ignores_the_code"`
Expected: FAIL — `AttributeError: ... 'check_dev_sync'`; `TypeError: ... unexpected keyword argument 'exclude_docs'` / `'code_doc'`.

- [ ] **Step 3: `_kb_tree_digest` gains `exclude_docs`**

Add the parameter `exclude_docs: frozenset[str] = frozenset()` to the signature and, in the file loop right after `rel` is computed (and before the `is_kb_artifact` filter), skip excluded documents:

```python
        if exclude_docs and rel.split("/", 1)[0] in exclude_docs:
            continue  # a dev repo's -code is branch-local (spec 2026-09-25 §4.3)
```

(`rel` is the POSIX relative path the loop already builds; if the loop names it differently, use that variable.)

- [ ] **Step 4: `check_hub` gains `code_doc`**

Add `code_doc: str | None = None` after `warn_untracked_index` in the keyword-only section and document it in the docstring: "`code_doc` (a dev repo's `<repo_id>-code`) is left out of the published-snapshot digest: it is regenerated per branch and CI publishes it." Replace the digest comparison block:

```python
            skip = frozenset({code_doc}) if code_doc else frozenset()
            if _kb_tree_digest(kb_dir.resolve(), exclude_docs=skip) != _kb_tree_digest(
                entry, synthesized, exclude_docs=skip
            ):
                advice = (
                    "merge to the default branch; CI publishes it"
                    if code_doc
                    else "run `kb publish`"
                )
                issues.append(
                    Issue(
                        "warning",
                        f"local .kb differs from the published snapshot "
                        f"federation/{repo_id} — {advice}",
                    )
                )
```

- [ ] **Step 5: Add `check_dev_sync`**

In `doctor.py` (add `import re` and `import subprocess` if absent):

```python
_DB_FLAG_RE = re.compile(r"kb code-ingest[^\n]*--db")


def check_dev_sync(kb_dir: Path, repo_root: Path, repo_id: str | None) -> list[Issue]:
    """Dev repo: what makes local `-code` differ from CI's (spec 2026-09-25
    §4.2) and the one migration step a gitignore line cannot do (§5)."""
    from strata_kb.codeingest import sync

    issues: list[Issue] = []
    try:
        workflow = (repo_root / sync.KB_CODE_WORKFLOW).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        workflow = ""
    if _DB_FLAG_RE.search(workflow):
        issues.append(Issue(
            "warning",
            "kb-code.yml passes --db to kb code-ingest — move the paths to "
            "`code_ingest.db` in .kb/config.yaml before re-running "
            "`kb init --kind dev`, which overwrites the workflow",
        ))
    pin_note = sync.version_note(repo_root)
    if pin_note:
        issues.append(Issue("warning", pin_note))
    if repo_id:
        try:
            rel = (kb_dir.resolve() / f"{repo_id}-code").relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            rel = ""
        if rel:
            proc = subprocess.run(
                ["git", "ls-files", "--", rel], cwd=repo_root, capture_output=True,
                text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                issues.append(Issue(
                    "warning",
                    f"{rel} is tracked by git but is derived on demand — run "
                    f"`git rm -r --cached {rel}` and commit (a .gitignore line "
                    "does not untrack files)",
                ))
    return issues
```

- [ ] **Step 6: Wire it into `kb doctor`**

Replace the `else:` branch (~3086–3088):

```python
    else:
        dev_code = f"{repo_id}-code" if cfg_kind == "dev" and repo_id else None
        hub_issues, hub_stale = check_hub(kb_dir, handle, repo_id=repo_id, code_doc=dev_code)
        issues += hub_issues
        if cfg_kind == "dev":
            from strata_kb.doctor import check_dev_sync

            issues += check_dev_sync(kb_dir, kb_dir.resolve().parent, repo_id)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_doctor_checks.py tests/test_cli_doctor*.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/strata_kb/doctor.py src/strata_kb/cli.py tests/test_doctor_checks.py
git commit -m "feat: kb doctor checks a dev repo's -code sync setup"
```

---

### Task 11: `kb doctor` reports hub lag

**Depends on:** Task 3, Task 10

**Files:**
- Modify: `src/strata_kb/gitio.py` (new `worktree_add_detached`, after `worktree_add` ~345)
- Create: `src/strata_kb/codeingest/hublag.py`
- Modify: `src/strata_kb/doctor.py` (new `check_hub_lag`)
- Modify: `src/strata_kb/cli.py` (`doctor`, the dev branch from Task 10)
- Test: `tests/test_codeingest_hublag.py` (create)

**Interfaces:**
- Consumes: `sync.options_from_config`, `sync.version_note`; `gitio.has_remote`, `gitio.default_branch`, `gitio.rev_exists`, `gitio.worktree_remove`; `core.run`, `core._git`.
- Produces:
  - `gitio.worktree_add_detached(root: Path, path: Path, rev: str) -> None`
  - `hublag.LagReport` (`state: Literal["in-sync", "lags", "unknown"]`, `reason`, `ref`, `ref_date`, `only_on_main`, `only_on_hub`, `changed`)
  - `hublag.l3_sections(doc_dir: Path) -> dict[str, str]`
  - `hublag.check(repo_root: Path, kb_dir: Path, federation_dir: Path, repo_id: str) -> LagReport`
  - `doctor.check_hub_lag(kb_dir: Path, repo_root: Path, handle: HubHandle | None, repo_id: str | None) -> list[Issue]`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_codeingest_hublag.py
import shutil
from pathlib import Path

import pytest

import strata_kb
from strata_kb.codeingest import core, hublag
from tests.fixtures_coderepo import build_code_repo


@pytest.fixture
def clone(tmp_path, run_git):
    src = tmp_path / "src"
    src.mkdir()
    build_code_repo(src)
    (src / ".kb").mkdir(exist_ok=True)
    (src / ".kb" / "config.yaml").write_text('kind: dev\nrepo_id: "demo"\n', encoding="utf-8")
    (src / ".gitignore").write_text(".kb/*-code/\n", encoding="utf-8")
    run_git(src, "init", "-b", "main")
    run_git(src, "add", "-A")
    run_git(src, "commit", "-m", "init")
    bare = tmp_path / "origin.git"
    run_git(tmp_path, "clone", "--bare", str(src), str(bare))
    work = tmp_path / "clone"
    run_git(tmp_path, "clone", str(bare), str(work))
    return work


def _publish(clone: Path, fed: Path) -> None:
    """The hub copy CI would publish for the clone's current commit."""
    core.run(core.CodeIngestOptions(
        repo_root=clone, kb_dir=clone / ".kb", doc_id="demo-code", repo_id="demo",
    ))
    dest = fed / "demo" / "demo-code"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(clone / ".kb" / "demo-code", dest)


def test_l3_sections_split_by_heading_and_drop_the_banner(tmp_path):
    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "services.raw.md").write_text(
        "# demo-code\n\n> Generated by kb code-ingest at abc1234 — do not edit by hand.\n\n"
        "## svc.a Service a\n\nbody a\n\n## svc.b Service b\n\nbody b\n",
        encoding="utf-8",
    )
    assert hublag.l3_sections(doc) == {"svc.a": "body a", "svc.b": "body b"}


def test_in_sync_when_the_hub_matches_main(clone, tmp_path):
    fed = tmp_path / "hub" / "federation"
    _publish(clone, fed)
    report = hublag.check(clone, clone / ".kb", fed, "demo")
    assert report.state == "in-sync", report


def test_lags_when_main_moved_past_the_hub(clone, tmp_path, run_git):
    fed = tmp_path / "hub" / "federation"
    _publish(clone, fed)
    (clone / "compose.billing.yml").write_text(
        "services:\n  billing-service:\n    image: billing:1\n", encoding="utf-8"
    )
    run_git(clone, "add", "-A")
    run_git(clone, "commit", "-m", "billing")
    run_git(clone, "push", "origin", "main")
    report = hublag.check(clone, clone / ".kb", fed, "demo")
    assert report.state == "lags"
    assert any("billing" in s for s in report.only_on_main)
    assert report.ref == "origin/main"


def test_worktree_is_removed_afterwards(clone, tmp_path, run_git):
    fed = tmp_path / "hub" / "federation"
    _publish(clone, fed)
    hublag.check(clone, clone / ".kb", fed, "demo")
    assert len(run_git(clone, "worktree", "list").splitlines()) == 1


def test_unknown_on_a_version_pin_mismatch(clone, tmp_path, monkeypatch):
    fed = tmp_path / "hub" / "federation"
    _publish(clone, fed)
    wf = clone / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "kb-code.yml").write_text("- run: pip install strata-kb==0.0.1\n", encoding="utf-8")
    monkeypatch.setattr(strata_kb, "__version__", "1.4.0")
    report = hublag.check(clone, clone / ".kb", fed, "demo")
    assert report.state == "unknown" and "pins 0.0.1" in report.reason


def test_unknown_without_a_remote(tmp_path, run_git):
    root = tmp_path / "solo"
    root.mkdir()
    build_code_repo(root)
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    fed = tmp_path / "hub" / "federation"
    (fed / "demo" / "demo-code").mkdir(parents=True)
    (fed / "demo" / "demo-code" / "_manifest.yaml").write_text("id: demo-code\ntitle: t\n", encoding="utf-8")
    report = hublag.check(root, root / ".kb", fed, "demo")
    assert report.state == "unknown" and "remote" in report.reason
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_codeingest_hublag.py -q`
Expected: FAIL — `ImportError: cannot import name 'hublag'`.

- [ ] **Step 3: Add `gitio.worktree_add_detached`**

```python
def worktree_add_detached(root: Path, path: Path, rev: str) -> None:
    """Check `rev` out, detached, into its own working tree at `path` —
    read-only use; no branch is created or moved."""
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = _run(root, "worktree", "add", "--detach", str(path), rev)
    if proc.returncode != 0:
        raise GitError(f"git worktree add --detach {rev} failed: {proc.stderr.strip()}")
```

- [ ] **Step 4: Create `hublag.py`**

```python
# src/strata_kb/codeingest/hublag.py
"""Does the hub's `<repo_id>-code` match what the default branch would
produce? (spec 2026-09-25 §4.3a)

Content, not commits: the intake opens no PR when nothing changed, so the
hub's recorded commit may trail main legitimately. L3 only: it is the
machine fact, and L1/L2 of a hub copy published after `kb summarize` differ
without anything having lagged.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from strata_kb import gitio
from strata_kb.codeingest import core, sync

_BANNER_PREFIX = "> Generated by kb code-ingest at "


@dataclass
class LagReport:
    state: Literal["in-sync", "lags", "unknown"]
    reason: str = ""
    ref: str = ""
    ref_date: str = ""
    only_on_main: list[str] = field(default_factory=list)
    only_on_hub: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)


def l3_sections(doc_dir: Path) -> dict[str, str]:
    """Section id -> L3 body across every `*.raw.md`, banner dropped.
    Headings are `## <id> <title>` (core._render_group)."""
    out: dict[str, str] = {}
    for path in sorted(doc_dir.glob("*.raw.md")):
        current: str | None = None
        body: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(_BANNER_PREFIX):
                continue
            if line.startswith("## "):
                if current is not None:
                    out[current] = "\n".join(body).strip()
                current = line[3:].split(" ", 1)[0]
                body = []
            elif current is not None:
                body.append(line)
        if current is not None:
            out[current] = "\n".join(body).strip()
    return out


def check(repo_root: Path, kb_dir: Path, federation_dir: Path, repo_id: str) -> LagReport:
    doc_id = f"{repo_id}-code"
    pin_note = sync.version_note(repo_root)
    if pin_note:
        return LagReport("unknown", reason=pin_note)
    hub_doc = federation_dir / repo_id / doc_id
    if not (hub_doc / "_manifest.yaml").exists():
        return LagReport("unknown", reason=f"the hub has no {doc_id} yet")
    if not gitio.has_remote(repo_root):
        return LagReport("unknown", reason="no git remote — nothing to compare the hub with")
    ref = f"origin/{gitio.default_branch(repo_root)}"
    if not gitio.rev_exists(repo_root, ref):
        return LagReport("unknown", reason=f"no local ref {ref} — run `git fetch`", ref=ref)
    ref_date = core._git(repo_root, "show", "-s", "--format=%cs", ref).stdout.strip()
    base = sync.options_from_config(repo_root, kb_dir, repo_id)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "main"
        try:
            gitio.worktree_add_detached(repo_root, work, ref)
        except gitio.GitError as exc:
            return LagReport("unknown", reason=str(exc), ref=ref, ref_date=ref_date)
        try:
            # kb_dir inside the worktree, so the tree extractor prunes the
            # worktree's own .kb/ exactly as a real checkout's is pruned.
            core.run(core.CodeIngestOptions(
                repo_root=work, kb_dir=work / ".kb", doc_id=doc_id, repo_id=repo_id,
                db_paths=base.db_paths, tags=base.tags,
            ))
            main = l3_sections(work / ".kb" / doc_id)
        except core.CodeIngestError as exc:
            return LagReport(
                "unknown", reason=f"code-ingest failed at {ref}: {exc}",
                ref=ref, ref_date=ref_date,
            )
        finally:
            gitio.worktree_remove(repo_root, work)
    hub = l3_sections(hub_doc)
    only_main = sorted(main.keys() - hub.keys())
    only_hub = sorted(hub.keys() - main.keys())
    changed = sorted(k for k in main.keys() & hub.keys() if main[k] != hub[k])
    state = "lags" if (only_main or only_hub or changed) else "in-sync"
    return LagReport(state, ref=ref, ref_date=ref_date,
                     only_on_main=only_main, only_on_hub=only_hub, changed=changed)
```

`base.db_paths` are already absolute, resolved against the real checkout — the database files are data, not code (spec §4.3a step 2).

- [ ] **Step 5: Run the hublag tests to verify they pass**

Run: `$PY -m pytest tests/test_codeingest_hublag.py -q`
Expected: PASS. If `test_in_sync_when_the_hub_matches_main` reports `changed` sections, print both bodies: a difference that comes from the checkout directory's name or path means an extractor leaks the root path — report it back rather than masking it in the comparison.

- [ ] **Step 6: Add `doctor.check_hub_lag` and wire it**

```python
def check_hub_lag(
    kb_dir: Path, repo_root: Path, handle: "HubHandle | None", repo_id: str | None
) -> list[Issue]:
    """Dev repo: is the hub's -code what the default branch would publish?"""
    if handle is None or not repo_id:
        return []
    from strata_kb.codeingest import hublag

    report = hublag.check(repo_root, kb_dir, handle.federation_dir, repo_id)
    if report.state == "in-sync":
        return []
    if report.state == "unknown":
        return [Issue("warning", f"hub lag not judged — {report.reason}")]
    parts = []
    if report.only_on_main:
        parts.append("only on main: " + ", ".join(report.only_on_main))
    if report.only_on_hub:
        parts.append("only on the hub: " + ", ".join(report.only_on_hub))
    if report.changed:
        parts.append("changed: " + ", ".join(report.changed))
    return [Issue(
        "warning",
        f"hub {repo_id}-code lags {report.ref} (as of {report.ref_date}) — "
        f"{'; '.join(parts)} — check for a pending -code PR on the hub, or the "
        "latest kb-code.yml run",
    )]
```

In `cli.py` `doctor`, extend the dev branch added in Task 10:

```python
        if cfg_kind == "dev":
            from strata_kb.doctor import check_dev_sync, check_hub_lag

            repo_root = kb_dir.resolve().parent
            issues += check_dev_sync(kb_dir, repo_root, repo_id)
            issues += check_hub_lag(kb_dir, repo_root, handle, repo_id)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_codeingest_hublag.py tests/test_doctor_checks.py tests/test_cli_doctor*.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/strata_kb/gitio.py src/strata_kb/codeingest/hublag.py src/strata_kb/doctor.py src/strata_kb/cli.py tests/test_codeingest_hublag.py
git commit -m "feat: kb doctor reports when the hub's -code lags main"
```

---

### Task 12: `kb ci-publish` job summary

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/cipublish.py` (new `write_step_summary`)
- Modify: `src/strata_kb/cli.py` (`ci_publish`, lines 1964–1988)
- Test: `tests/test_cli_ci_publish_summary.py` (create)

**Interfaces:**
- Produces: `cipublish.write_step_summary(line: str) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cli_ci_publish_summary.py
from typer.testing import CliRunner

from strata_kb import cipublish
from strata_kb.cli import app

runner = CliRunner()


def _kb(tmp_path):
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text('intake: "https://kb.test"\nrepo_id: "demo"\n', encoding="utf-8")
    return kb


def test_writes_the_pr_url(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(cipublish, "run", lambda *a, **k: "https://gh/pull/8")
    result = runner.invoke(app, ["ci-publish", "--kb-dir", str(_kb(tmp_path))])
    assert result.exit_code == 0, result.output
    assert summary.read_text(encoding="utf-8") == "kb ci-publish: hub PR: https://gh/pull/8\n"


def test_writes_no_change(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setattr(cipublish, "run", lambda *a, **k: "")
    runner.invoke(app, ["ci-publish", "--kb-dir", str(_kb(tmp_path))])
    assert summary.read_text(encoding="utf-8") == "kb ci-publish: no content change on the hub\n"


def test_writes_the_error(tmp_path, monkeypatch):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    def boom(*a, **k):
        raise cipublish.CIPublishError("intake rejected the publish (HTTP 403): nope")

    monkeypatch.setattr(cipublish, "run", boom)
    result = runner.invoke(app, ["ci-publish", "--kb-dir", str(_kb(tmp_path))])
    assert result.exit_code == 1
    assert "error — intake rejected" in summary.read_text(encoding="utf-8")


def test_no_summary_outside_actions(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    cipublish.write_step_summary("anything")  # must not raise or write
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$PY -m pytest tests/test_cli_ci_publish_summary.py -q`
Expected: FAIL — `FileNotFoundError` on `summary.md`; `AttributeError: ... 'write_step_summary'`.

- [ ] **Step 3: Implement**

In `cipublish.py` (add `import os` if absent):

```python
def write_step_summary(line: str) -> None:
    """Append one line to the GitHub Actions job summary; a no-op outside
    Actions. The same hub PR URL repeating run after run is how a pending
    hub PR becomes visible (spec 2026-09-25 §4.3b)."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"kb ci-publish: {line}\n")
    except OSError:
        pass  # a summary is a courtesy; never fail the publish over it
```

In `cli.py` `ci_publish`, change the `try:` body to capture the result and write the summary on both paths:

```python
    try:
        pr_url = cipublish.run(
            kb_dir, url, effective_repo_id(repo_id, kb_dir), require_reviewed=require_reviewed
        )
    except (
        # (keep the existing comment block and exception tuple unchanged)
        KbError,
        gitio.GitError, OSError,
        *_CONFIG_READ_ERRORS,
    ) as exc:
        cipublish.write_step_summary(f"error — {exc}")
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    cipublish.write_step_summary(
        f"hub PR: {pr_url}" if pr_url else "no content change on the hub"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `$PY -m pytest tests/test_cli_ci_publish_summary.py tests/test_publish_intake_cli.py tests/test_cli_errors.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/cipublish.py src/strata_kb/cli.py tests/test_cli_ci_publish_summary.py
git commit -m "feat: kb ci-publish writes its outcome to the job summary"
```

---

### Task 13: Docs, changelog, release 1.4.0, full suite

**Depends on:** Tasks 1–12

**Files:**
- Modify: `docs/src/guide-dev.en.md`, `docs/src/guide-dev.vi.md`
- Modify: `docs/src/architecture.en.md`, `docs/src/architecture.vi.md` (the `-code` row ~line 368 and the text after it)
- Modify: `src/strata_kb/templates/init/QUICKSTART-dev.md` (lines 6–9, 266–267, 352)
- Modify: `CHANGELOG.md`, `pyproject.toml`
- The PDFs under `docs/` are not rebuilt (they need macOS fonts; no recent PR rebuilds them).

- [ ] **Step 1: `guide-dev.en.md`**

§1.2 table, `-code` row, "Regenerated" cell: `on demand, from the working tree — never committed; CI publishes it on every push to the default branch`.

§2.1, after the config block, add:

~~~markdown
If the KB should carry SQLite schema, or extra index tags, say so here —
not in `kb-code.yml` — so every local refresh and CI ingest the same way:

```yaml
code_ingest:
  db: [data/app.sqlite]   # explicit only
  tags: [payments]
```
~~~

§2.4, after the quoted block, add: `This auto-merge rule is also what keeps the hub from lagging main: without it, every push adds to one pending hub PR that someone has to merge. \`kb doctor\` reports when the hub's \`-code\` lags.`

Replace §8.1 body with:

```markdown
`-code` is never committed. `.gitignore` carries `.kb/*-code/`, and the
document is regenerated from your working tree whenever a command needs it:
`kb svc note`, `kb build` and `kb publish` refresh it first when it is
missing, older than `HEAD`, or your tracked files have changes. A new file
counts once it is tracked (`git add`). `kb ticket check` reads the hub copy
first — that is what the SA grounded on.

`kb-code.yml` re-runs `kb code-ingest` → `kb build` → `kb ci-publish` on every
push to the default branch, so the hub reflects the current commit once its
PR merges.

| Trigger | Steps | Publishes |
|---|---|---|
| push to default branch, or manual dispatch | code-ingest → build → ci-publish | yes |
| pull request | build (which regenerates `-code` from the merge ref) | **never** |

`-code` has one producer, `kb code-ingest`: `kb summarize` refuses it. A hub
copy that was summarized before 1.4.0 returns to the deterministic L1/L2 on
the next CI publish — a one-time diff, not lost information; L3 is
unchanged.

`--scaffold-svc` is deliberately never passed in CI. CI must never create
`pending` content, since that would fail its own build step.
```

§9 table, replace the `kb svc note` row and add three rows:

```markdown
| `kb svc note`: "unknown service" | A typo, or the new service's files are not tracked yet | Copy the id from `services.md`; `git add` the new files and retry |
| `kb doctor`: "hub `<repo>`-code lags origin/main" | The last `-code` publish has not merged on the hub, or the last `kb-code.yml` run failed | Open the hub PR named in the Actions job summary; merge it or fix the run |
| `kb doctor`: "kb-code.yml passes --db" | Ingest configuration lives in the workflow | Move the paths to `code_ingest.db` in `.kb/config.yaml`, then re-run `kb init --kind dev` |
| `kb doctor`: "`.kb/<repo>-code` is tracked by git" | A repo from before 1.4.0 | `git rm -r --cached .kb/<repo>-code` and commit, in one PR |
```

§10 command table: `kb code-ingest [--db p] [--tags t] [--scaffold-svc] [--json]` (`--db`/`--tags` replace `code_ingest:` for that run); `kb svc note … [--no-refresh]`; `kb build [--strict] [--no-refresh]`.

§7.4: add one sentence — "Local `-code` is what CI would produce if your tracked files were committed now; `kb doctor` warns when your installed strata-kb differs from the version `kb-code.yml` pins."

- [ ] **Step 2: `guide-dev.vi.md`** — the same changes, in Vietnamese, at the matching sections. Use this text for §8.1:

```markdown
`-code` không bao giờ được commit. `.gitignore` có dòng `.kb/*-code/`, và
tài liệu được sinh lại từ working tree mỗi khi một lệnh cần đến nó:
`kb svc note`, `kb build` và `kb publish` làm mới nó trước khi chạy nếu nó
chưa có, cũ hơn `HEAD`, hoặc các file đang được git track có thay đổi. File
mới chỉ được tính sau khi `git add`. `kb ticket check` đọc bản trên hub
trước — đó là bản SA đã dùng để ground ticket.

`kb-code.yml` chạy lại `kb code-ingest` → `kb build` → `kb ci-publish` ở mỗi
lần push lên nhánh mặc định, nên hub phản ánh commit hiện tại ngay khi PR của
nó được merge.

| Kích hoạt | Các bước | Publish |
|---|---|---|
| push lên nhánh mặc định, hoặc chạy tay | code-ingest → build → ci-publish | có |
| pull request | build (sinh lại `-code` từ merge ref) | **không bao giờ** |

`-code` chỉ có một nguồn sinh là `kb code-ingest`: `kb summarize` từ chối nó.
Bản trên hub từng được summarize trước 1.4.0 sẽ trở về L1/L2 deterministic ở
lần CI publish kế tiếp — diff một lần, không mất thông tin; L3 không đổi.

`--scaffold-svc` cố ý không bao giờ được truyền trong CI. CI không được tạo
nội dung `pending`, vì như vậy chính bước build của nó sẽ fail.
```

- [ ] **Step 3: `architecture.{en,vi}.md`** — `-code` row (~line 368): "Regenerated" cell `on demand from the working tree; CI publishes on every merge` (vi: `sinh lại khi cần từ working tree; CI publish ở mỗi lần merge`). Add after the paragraph that follows the table (en): "`-code` is never committed: its revision lives in its manifest, not in `index.yaml`, so a dev repo's committed index does not change when code does." (vi: "`-code` không bao giờ được commit: revision của nó nằm trong manifest, không nằm trong `index.yaml`, nên index đã commit của repo dev không đổi khi code đổi.")

- [ ] **Step 4: `QUICKSTART-dev.md` template** — lines 6–9: after "…on every push to `main` or `master`" add "; locally, `kb svc note`, `kb build` and `kb publish` regenerate it from your working tree — it is never committed (`.gitignore`: `.kb/*-code/`)". Line ~266–267 (the "needs nothing from you" bullet): same sentence. Line ~352 (hand-edited `kb-code.yml` including `--db` flags): replace the `--db` advice with "ingest configuration belongs in `code_ingest:` in `.kb/config.yaml`, which `kb init` never overwrites".

- [ ] **Step 5: `CHANGELOG.md`** — rename `## Unreleased` to `## 1.4.0 — <today's date, YYYY-MM-DD>` and add at its top:

```markdown
- `<repo_id>-code` is derived on demand and never committed. `kb init --kind dev` adds `.kb/*-code/` to `.gitignore`; `kb svc note`, `kb build` and `kb publish` (dev repos) regenerate it from the working tree first when it is missing, older than `HEAD`, or tracked files changed (`--no-refresh` on `svc note` and `build`). The PR job's `kb build` therefore validates what the merge would publish. `-code`'s revision moves from `index.yaml` to its manifest only, so the committed index no longer churns; the hub reads the manifest.
- `kb ticket check` reads the hub copy of `-code` first — the copy the SA grounded on — and falls back to the local one with a `(local fallback — …)` note.
- `code_ingest:` in `.kb/config.yaml` (`db`, `tags`) is the one ingest configuration local runs and CI share; `--db`/`--tags` replace it for a run and say so. `kb-code.yml` no longer carries `--db` flags.
- `kb doctor` (dev repos) warns on `--db` flags left in `kb-code.yml`, on an installed strata-kb that differs from `kb-code.yml`'s pin, on a still-tracked `.kb/<repo>-code`, and when the hub's `-code` lags `origin/<default>` — judged by regenerating `-code` at that ref and comparing L3, naming the sections that differ. Its published-snapshot check leaves `-code` out for dev repos.
- `kb ci-publish` writes `hub PR: <url>` / `no content change on the hub` / the error to the GitHub Actions job summary.
- `kb summarize` never touches a generated (`-code`) document: `--redo --all` skips it with a note, `kb summarize <repo>-code` exits 1. A hub copy summarized earlier returns to deterministic L1/L2 on the next CI publish.
- `kb code-ingest`: `cmd.*` no longer comes from workflows `kb init` scaffolds (`kb-code.yml`, `kb-pr-lint.yml`, `kb-publish.yml`, `kb-ticket-lint.yml`); compose files using `!reset` / `!override` parse instead of being skipped.
- Migration for an existing dev repo: move `--db` flags to `code_ingest.db`, re-run `kb init --kind dev`, then `git rm -r --cached .kb/<repo>-code` and commit — in one PR. `kb doctor` walks you through it.
```

- [ ] **Step 6: `pyproject.toml`** — `version = "1.4.0"`.

- [ ] **Step 7: Run the full suite once**

Run: `$PY -m pytest -q` (10–19 minutes; run it in the background and wait for completion).
Expected: all tests pass. Any failure: read it, fix at the root (a test that encoded the old behaviour is updated to the new spec'd behaviour; a real regression is fixed in code), re-run the affected files, then the full suite again.

- [ ] **Step 8: Commit**

```bash
git add docs/src CHANGELOG.md pyproject.toml src/strata_kb/templates/init/QUICKSTART-dev.md
git commit -m "docs: -code sync in guides and changelog — release 1.4.0"
```
