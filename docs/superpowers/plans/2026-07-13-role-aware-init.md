# Role-Aware `kb init` + Hub-Only `kb docker-setup` + Cursor Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb init` requires a hub|child kind choice, scaffolds differently per kind (including Cursor assistant files), and a new hub-only `kb docker-setup` command creates `.env` + auto-generates the HTTP token.

**Architecture:** The kind persists as `kind:` in `.kb/config.yaml` (protected, committed). `initcmd.py` merges `COMMON_TEMPLATES` with `HUB_TEMPLATES` or `CHILD_TEMPLATES`; kind resolution (flag → prompt → error) lives in the CLI layer. `kb docker-setup` is a real CLI command in a new `dockersetup.py`; Claude/Copilot/Cursor slash commands are thin wrappers over it.

**Tech Stack:** Python ≥3.11, Typer (click), Pydantic v2, pytest + `typer.testing.CliRunner`, hatchling packaging (templates ship as package data under `src/center_kb/templates/init/`).

**Spec:** `docs/superpowers/specs/2026-07-13-role-aware-init-design.md`

## Global Constraints

- Kind values are exactly `"hub"` and `"child"`; `""` means legacy/unset.
- Non-interactive init without a kind exits non-zero with exactly: `kb init requires --kind hub|child when not running interactively.`
- Token variable name: `CENTER_KB_HTTP_TOKEN`; generated with `secrets.token_hex(24)` (48 hex chars). The token is NEVER echoed to stdout.
- Hub HTTP port is 8321; Web UI path `/ui`; MCP path `/mcp`.
- Child `.mcp.json` (Claude) uses `${CENTER_KB_HUB_URL}` / `${CENTER_KB_HTTP_TOKEN}`; child `.cursor/mcp.json` uses `${env:CENTER_KB_HUB_URL}` / `${env:CENTER_KB_HTTP_TOKEN}` (Cursor's interpolation syntax differs).
- The docker-compose service is named `hub` in BOTH kinds (the shared kb-ingest skill text `docker compose run --rm hub kb ingest` must keep working).
- `PROTECTED_FILES` (`.kb/index.yaml`, `.kb/config.yaml`) are never overwritten without `--force`. `kb init` never deletes files.
- All code comments in English. Conventional commit messages (`feat:`, `test:`, `docs:` …); no attribution footer.
- Run tests with `python -m pytest tests/<file> -v` from the repo root; full gate is `python -m pytest` + `ruff check src tests`.

---

### Task 1: `KBConfig.kind` field

**Files:**
- Modify: `src/center_kb/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: existing `KBConfig` (pydantic model with `hub: str`, `repo_id: str`), `load_config(kb_dir: Path) -> KBConfig`.
- Produces: `KBConfig.kind: Literal["", "hub", "child"]` defaulting to `""`. Later tasks call `load_config(path / ".kb").kind`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:

```python
def test_config_kind_defaults_to_empty(tmp_path):
    from center_kb.config import load_config

    assert load_config(tmp_path).kind == ""  # no config.yaml at all
    (tmp_path / "config.yaml").write_text("hub: /h\n", encoding="utf-8")
    assert load_config(tmp_path).kind == ""  # legacy config without kind


def test_config_kind_roundtrip(tmp_path):
    from center_kb.config import load_config

    (tmp_path / "config.yaml").write_text(
        "hub: '.'\nrepo_id: my-repo\nkind: hub\n", encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.kind == "hub"
    assert cfg.hub == "."


def test_config_kind_rejects_unknown_value(tmp_path):
    import pytest
    from pydantic import ValidationError

    from center_kb.config import load_config

    (tmp_path / "config.yaml").write_text("kind: server\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(tmp_path)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_config.py -v`
Expected: the two new positive tests FAIL (`AttributeError: 'KBConfig' object has no attribute 'kind'` or similar), `test_config_kind_rejects_unknown_value` FAIL (no ValidationError raised — unknown fields are ignored today).

- [ ] **Step 3: Implement**

In `src/center_kb/config.py`, change the imports and model:

```python
from typing import Literal

class KBConfig(BaseModel):
    hub: str = ""
    repo_id: str = ""
    kind: Literal["", "hub", "child"] = ""
```

(`from typing import Literal` goes with the existing imports at the top.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (all, including pre-existing tests).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/config.py tests/test_config.py
git commit -m "feat: add kind (hub|child) field to KBConfig"
```

---

### Task 2: Kind-aware `init_repo` — hub scaffold

Restructure `initcmd.py` into COMMON/HUB/CHILD maps and make `init_repo` take a required `kind`. This task delivers the **hub** kind (equivalent to today's scaffold, plus `kind: hub` and a pre-filled `repo_id` in config); the child templates land in Task 3 (`CHILD_TEMPLATES` starts as a placeholder-free minimal dict that Task 3 fills — to keep this task green, it starts as a copy of the hub-specific entries it can already satisfy, see Step 3).

**Files:**
- Modify: `src/center_kb/initcmd.py`
- Create: `src/center_kb/templates/init/config-hub.yaml`
- Rename: `src/center_kb/templates/init/docker-compose.yml` → `docker-compose-hub.yml`; `mcp.json` → `mcp-hub.json`; `QUICKSTART.md` → `QUICKSTART-hub.md`; delete `config.yaml` (replaced by `config-hub.yaml` here and `config-child.yaml` in Task 3)
- Modify: `tests/test_init.py`, `tests/test_templates.py`

**Interfaces:**
- Consumes: nothing new.
- Produces (used by Tasks 3–10):
  - `init_repo(target: Path, kind: str, force: bool = False) -> InitReport` — raises `ValueError` for kind not in `("hub", "child")`.
  - `template_map(kind: str) -> dict[str, str]`, `expected_files(kind: str) -> list[str]`.
  - Module constants `KIND_HUB = "hub"`, `KIND_CHILD = "child"`, `KINDS = (KIND_HUB, KIND_CHILD)`, dicts `COMMON_TEMPLATES`, `HUB_TEMPLATES`, `CHILD_TEMPLATES`.
  - Config templates contain a `{repo_id}` placeholder filled via `str.format` with the target folder name.

- [ ] **Step 1: Write the failing tests**

In `tests/test_init.py`, replace the import line and the first test, and add two new tests:

```python
from center_kb.initcmd import expected_files, init_repo
```

```python
def test_init_hub_creates_all_hub_files(tmp_path: Path):
    report = init_repo(tmp_path, "hub")
    assert sorted(report.created) == sorted(expected_files("hub"))
    assert report.skipped == []
    for rel in expected_files("hub"):
        assert (tmp_path / rel).is_file(), rel
    # hub-only artifacts present
    assert (tmp_path / "federation" / "README.md").is_file()
    assert (tmp_path / ".env.example").is_file()


def test_init_rejects_unknown_kind(tmp_path: Path):
    import pytest

    with pytest.raises(ValueError):
        init_repo(tmp_path, "server")


def test_init_hub_config_has_kind_and_repo_id(tmp_path: Path):
    repo = tmp_path / "my-hub-repo"
    repo.mkdir()
    init_repo(repo, "hub")
    text = (repo / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "kind: hub" in text
    assert 'hub: "."' in text
    assert 'repo_id: "my-hub-repo"' in text
    assert "{repo_id}" not in text
```

Then mechanically update every other existing test in `tests/test_init.py`: each `init_repo(tmp_path)` becomes `init_repo(tmp_path, "hub")` (and `init_repo(tmp_path, "hub", force=True)` for the force test), and every `runner.invoke(app, ["init", str(tmp_path)])` becomes `runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])` — the `--kind` option does not exist yet; those CLI tests will keep failing until Task 5, which is fine only if we do NOT touch them now. **Therefore:** in this task update ONLY the direct `init_repo(...)` call sites (tests `test_init_refreshes_scaffold_but_protects_index`, `test_init_is_idempotent_when_already_current`, `test_init_force_overwrites_protected_data`, `test_init_does_not_overwrite_config`, `test_kb_doctor_on_fresh_skeleton_requires_hub`, `test_quickstart_uses_correct_ingest_flag`, `test_init_scaffolds_ai_integration_files`, `test_init_scaffolds_kb_ingest_slash_command`, `test_init_scaffolds_kb_publish_slash_command`, `test_quickstart_and_instructions_have_cli_reference`, `test_kb_summarize_templates_have_prose_only_rules`, `test_init_scaffolds_kb_summarize_slash_command`, `test_kb_summarize_skill_is_parallel_orchestrator`) and delete the old `test_init_creates_all_files` (replaced above). Change `test_kb_doctor_on_fresh_skeleton_requires_hub` to use `init_repo(tmp_path, "child")` — a fresh HUB skeleton now has `hub: "."` so it no longer triggers the "no hub configured" error; the child skeleton (Task 3) keeps `hub: ""`. Since child templates don't exist until Task 3, mark it with `@pytest.mark.xfail(reason="child templates land in the next task", strict=True)` for now (Task 3 removes the marker). Leave the two CLI-runner tests (`test_cli_init_reports_and_next_steps`, `test_cli_init_updates_stale_scaffold`) completely untouched — the CLI shim in Step 3 keeps today's behavior, so they still pass as-is; Task 5 rewrites them.

In `tests/test_templates.py`, replace the init-templates test:

```python
from center_kb.initcmd import CHILD_TEMPLATES, COMMON_TEMPLATES, HUB_TEMPLATES


def test_all_init_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for mapping in (COMMON_TEMPLATES, HUB_TEMPLATES, CHILD_TEMPLATES):
        for resource_name in mapping.values():
            assert base.joinpath(resource_name).is_file(), resource_name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_init.py tests/test_templates.py -v`
Expected: FAIL — `ImportError: cannot import name 'expected_files'` (and `CHILD_TEMPLATES`).

- [ ] **Step 3: Implement**

Create `src/center_kb/templates/init/config-hub.yaml`:

```yaml
# CENTER-KB — repo config (commit to git).
# kind: this repo's role. "hub" hosts federation/ (the single source of truth
#       for search) and runs the shared HTTP MCP server + Web UI.
kind: hub
# hub: git URL or kb-hub path — the ONLY read source for kb query / MCP / Web UI.
#      This repo IS the hub, so it points at itself.
hub: "."
# repo_id: repo name on the federation (pre-filled from the folder name)
repo_id: "{repo_id}"
```

Rename the three hub templates (git keeps history):

```bash
git mv src/center_kb/templates/init/docker-compose.yml src/center_kb/templates/init/docker-compose-hub.yml
git mv src/center_kb/templates/init/mcp.json src/center_kb/templates/init/mcp-hub.json
git mv src/center_kb/templates/init/QUICKSTART.md src/center_kb/templates/init/QUICKSTART-hub.md
git rm src/center_kb/templates/init/config.yaml
```

Rewrite `src/center_kb/initcmd.py` in full:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

KIND_HUB = "hub"
KIND_CHILD = "child"
KINDS = (KIND_HUB, KIND_CHILD)

# target relative path -> template resource name under templates/init/
COMMON_TEMPLATES: dict[str, str] = {
    ".kb/index.yaml": "index.yaml",
    "source/.gitignore": "source-gitignore.txt",
    ".claude/skills/kb-summarize/SKILL.md": "claude-skill-kb-summarize.md",
    ".claude/commands/kb-summarize.md": "claude-command-kb-summarize.md",
    ".github/instructions/kb-summarize.instructions.md": "copilot-kb-summarize.instructions.md",
    ".claude/skills/kb-ingest/SKILL.md": "claude-skill-kb-ingest.md",
    ".github/prompts/kb-ingest.prompt.md": "copilot-kb-ingest.prompt.md",
    ".claude/skills/kb-publish/SKILL.md": "claude-skill-kb-publish.md",
    ".github/prompts/kb-publish.prompt.md": "copilot-kb-publish.prompt.md",
    ".github/workflows/kb-publish.yml": "kb-publish.yml",
}

HUB_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-hub.yaml",
    "docker-compose.yml": "docker-compose-hub.yml",
    ".env.example": "env.example",
    "federation/README.md": "federation-README.md",
    ".mcp.json": "mcp-hub.json",
    "QUICKSTART.md": "QUICKSTART-hub.md",
}

# Filled in by the child-scaffold task; kept separate so hub and child can
# diverge artifact-by-artifact.
CHILD_TEMPLATES: dict[str, str] = {
    ".kb/config.yaml": "config-child.yaml",
    "docker-compose.yml": "docker-compose-child.yml",
    ".mcp.json": "mcp-child.json",
    "QUICKSTART.md": "QUICKSTART-child.md",
}

# User data — never refreshed by default; only overwritten with --force.
PROTECTED_FILES: frozenset[str] = frozenset({".kb/index.yaml", ".kb/config.yaml"})


def template_map(kind: str) -> dict[str, str]:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}, got '{kind}'")
    extra = HUB_TEMPLATES if kind == KIND_HUB else CHILD_TEMPLATES
    return {**COMMON_TEMPLATES, **extra}


def expected_files(kind: str) -> list[str]:
    return list(template_map(kind))


@dataclass
class InitReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _render(resource_name: str, text: str, repo_id: str) -> str:
    """Config templates carry a {repo_id} placeholder; everything else is static."""
    if resource_name.startswith("config-"):
        return text.format(repo_id=repo_id)
    return text


def init_repo(target: Path, kind: str, force: bool = False) -> InitReport:
    """Scaffold a KB repo as the given kind (hub | child).

    Default: create missing files and refresh scaffold templates whose content
    changed. Protected data (``.kb/index.yaml``, ``.kb/config.yaml``) is left
    alone unless ``force=True``.
    """
    templates = template_map(kind)
    base = resources.files("center_kb").joinpath("templates/init")
    repo_id = target.resolve().name
    report = InitReport()
    for rel, resource_name in templates.items():
        dest = target / rel
        text = _render(
            resource_name,
            base.joinpath(resource_name).read_text(encoding="utf-8"),
            repo_id,
        )
        if dest.exists():
            if rel in PROTECTED_FILES and not force:
                report.skipped.append(rel)
                continue
            if dest.read_text(encoding="utf-8") == text:
                continue
            dest.write_text(text, encoding="utf-8")
            report.updated.append(rel)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        report.created.append(rel)
    return report
```

(The `import re` is unused until Task 4 adds `_record_kind` — omit it here and add it in Task 4 to keep ruff green.)

Also update `src/center_kb/cli.py` line 59 minimally so the module keeps importing and the xfail'd CLI tests fail for the intended reason: `report = init_repo(path, "hub", force=force)`. (Task 5 replaces this with real kind resolution.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py tests/test_templates.py -v`
Expected: PASS, with 3 XFAIL (the doctor test and the two CLI tests).

- [ ] **Step 5: Run the whole suite (other tests import initcmd)**

Run: `python -m pytest -q`
Expected: PASS + 3 xfail. If any other test calls `init_repo` positionally with one arg, add `"hub"` there too.

- [ ] **Step 6: Commit**

```bash
git add -A src/center_kb tests/test_init.py tests/test_templates.py
git commit -m "feat: kind-aware init_repo with COMMON/HUB/CHILD template maps (hub scaffold)"
```

---

### Task 3: Child scaffold templates

**Files:**
- Create: `src/center_kb/templates/init/config-child.yaml`, `docker-compose-child.yml`, `mcp-child.json`, `QUICKSTART-child.md`
- Modify: `src/center_kb/templates/init/QUICKSTART-hub.md` (final hub copy: docker-setup step)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `init_repo(target, kind)`, `expected_files(kind)`, `CHILD_TEMPLATES` from Task 2.
- Produces: a working `init_repo(target, "child")`; child artifacts per the spec matrix. No new code interfaces.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_init.py`, and remove the `xfail` marker from `test_kb_doctor_on_fresh_skeleton_requires_hub`:

```python
def test_init_child_creates_child_files_only(tmp_path: Path):
    report = init_repo(tmp_path, "child")
    assert sorted(report.created) == sorted(expected_files("child"))
    # child never hosts federation or the long-lived server
    assert not (tmp_path / "federation").exists()
    assert not (tmp_path / ".env.example").exists()
    # authoring skills are still there
    assert (tmp_path / ".claude" / "skills" / "kb-ingest" / "SKILL.md").is_file()
    assert (tmp_path / ".github" / "workflows" / "kb-publish.yml").is_file()


def test_init_child_config_points_at_no_hub_yet(tmp_path: Path):
    repo = tmp_path / "my-child-repo"
    repo.mkdir()
    init_repo(repo, "child")
    text = (repo / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "kind: child" in text
    assert 'hub: ""' in text
    assert 'repo_id: "my-child-repo"' in text


def test_child_compose_is_ingest_only(tmp_path: Path):
    init_repo(tmp_path, "child")
    text = (tmp_path / "docker-compose.yml").read_text(encoding="utf-8")
    assert "hub:" in text          # service name stays `hub` (shared skill text)
    assert "ports:" not in text    # no long-lived HTTP server
    assert "env_file" not in text
    assert "healthcheck" not in text
    assert "docker compose run --rm hub kb ingest" in text


def test_child_mcp_json_uses_env_expansion(tmp_path: Path):
    init_repo(tmp_path, "child")
    text = (tmp_path / ".mcp.json").read_text(encoding="utf-8")
    assert '"type": "http"' in text
    assert "${CENTER_KB_HUB_URL}/mcp" in text
    assert "Bearer ${CENTER_KB_HTTP_TOKEN}" in text


def test_quickstarts_match_kind(tmp_path: Path):
    hub_repo = tmp_path / "h"
    child_repo = tmp_path / "c"
    hub_repo.mkdir()
    child_repo.mkdir()
    init_repo(hub_repo, "hub")
    init_repo(child_repo, "child")
    hub_q = (hub_repo / "QUICKSTART.md").read_text(encoding="utf-8")
    child_q = (child_repo / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "kb docker-setup" in hub_q
    assert "docker compose up -d" in hub_q
    assert "kb docker-setup" not in child_q
    assert "docker compose up -d" not in child_q
    assert "hub:" in child_q and "kb publish" in child_q
    for text in (hub_q, child_q):
        assert "## CLI reference" in text
        assert "/kb-ingest" in text and "/kb-publish" in text
```

Also update `test_quickstart_uses_correct_ingest_flag` and `test_quickstart_and_instructions_have_cli_reference` to run against BOTH kinds (parametrize):

```python
import pytest

@pytest.mark.parametrize("kind", ["hub", "child"])
def test_quickstart_uses_correct_ingest_flag(tmp_path: Path, kind: str):
    init_repo(tmp_path, kind)
    text = (tmp_path / "QUICKSTART.md").read_text(encoding="utf-8")
    assert "--id" in text
    assert "--doc-id" not in text


@pytest.mark.parametrize("kind", ["hub", "child"])
def test_quickstart_and_instructions_have_cli_reference(tmp_path: Path, kind: str):
    init_repo(tmp_path, kind)
    quick = (tmp_path / "QUICKSTART.md").read_text(encoding="utf-8")
    instr = (
        tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    ).read_text(encoding="utf-8")
    for text in (quick, instr):
        assert "## CLI reference" in text
        for cmd in (
            "kb init", "kb ingest", "kb summarize", "kb status", "kb build",
            "kb query", "kb get", "kb stats", "kb diff",
            "kb publish", "kb resolve", "kb doctor",
        ):
            assert cmd in text, cmd
        assert "--level l2|l3" in text
        assert "l1|l2|l3" not in text
    assert "/kb-ingest" in quick
    assert "/kb-publish" in quick
    assert "/kb-summarize" in quick
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_init.py -v`
Expected: new tests FAIL with `FileNotFoundError` on `config-child.yaml` (the resource does not exist); doctor test no longer xfails but FAILs the same way.

- [ ] **Step 3: Create the child templates**

`src/center_kb/templates/init/config-child.yaml`:

```yaml
# CENTER-KB — repo config (commit to git).
# kind: this repo's role. "child" authors content locally and publishes it to
#       the main hub; it does not host the company-wide MCP/Web service.
kind: child
# hub: git URL or kb-hub path of the MAIN HUB — the ONLY read source for
#      kb query / MCP / Web UI. FILL THIS IN before publishing.
#      Local .kb/ content only reaches readers after `kb publish` and the PR
#      is merged on the hub.
hub: ""
# repo_id: repo name on the federation (pre-filled from the folder name)
repo_id: "{repo_id}"
```

`src/center_kb/templates/init/docker-compose-child.yml`:

```yaml
# Child repo: Docker is for ONE-SHOT ingest runs, not a long-lived server.
#   docker compose run --rm hub kb ingest source/<file>.pdf --id <doc-id> --no-summarize
# The company-wide MCP HTTP server + Web UI run on the MAIN hub repo, not here.
services:
  hub:
    image: ghcr.io/vuonglq01685/center-kb:latest
    volumes:
      - ./:/data
      - kb-model-cache:/home/app/.cache
volumes:
  kb-model-cache:
```

`src/center_kb/templates/init/mcp-child.json`:

```json
{
  "mcpServers": {
    "center-kb": {
      "type": "http",
      "url": "${CENTER_KB_HUB_URL}/mcp",
      "headers": { "Authorization": "Bearer ${CENTER_KB_HTTP_TOKEN}" }
    }
  }
}
```

`src/center_kb/templates/init/QUICKSTART-child.md`:

```markdown
# CENTER-KB Quickstart (child repo)

This repo AUTHORS knowledge and publishes it to the main hub. It does not
host the company-wide search service — `kb query` / MCP / Web UI read only
the hub's `federation/`.

## Connect the hub (required)

1. **Point at the main hub** — fill `hub:` in `.kb/config.yaml` (a git URL
   or a kb-hub path) and commit it. New content appears in search only after
   `kb publish` and the PR is merged on the hub.

## Author and publish

2. **Ingest the first document** — put the PDF in `source/`, then:
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   In Claude Code, Copilot Chat, or Cursor, prefer the `/kb-ingest` slash
   command — it asks for the id/tags/revision so you don't have to remember
   flags. (needs the ingest extra: `pip install "center-kb[ingest]"` — or run
   it inside Docker, no local Python needed:
   `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc --no-summarize`)
3. **Summarize** — `kb ingest` does this automatically when the Claude Code or
   GitHub Copilot CLI is installed (config: `llm:` in `.kb/index.yaml`).
   Manual fallback: `/kb-summarize` in your assistant, or `kb summarize` later.
   Then validate: `kb build`
4. **Publish** — `kb publish` mirrors `.kb/` to the hub and opens a PR there
   (in your assistant: `/kb-publish` runs diff → confirm → publish). Merging
   that PR on the hub makes the content searchable.

## Query (reads the hub)

5. **Query** — `kb query "your question"` (hub from `.kb/config.yaml`), the
   hub's web UI, or MCP. `.mcp.json` (Claude Code) and `.cursor/mcp.json`
   (Cursor) are pre-wired to the hub's HTTP endpoint — set two environment
   variables locally:
   - `CENTER_KB_HUB_URL` — e.g. `http://kb-hub.example.com:8321`
   - `CENTER_KB_HTTP_TOKEN` — the hub token (ask the hub maintainer)

## CLI reference

- `kb init` — scaffold or refresh a KB repo (asks hub|child; updates skills/templates; keeps `.kb/index.yaml`)
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (in Claude Code / Copilot Chat / Cursor: `/kb-ingest`)
- `kb summarize` — fill pending summaries via a headless LLM CLI
  (in your assistant: `/kb-summarize`)
- `kb status` — list docs and their pending sections
- `kb build` — validate the KB (manifests, tables, tokens)
- `kb query "<question>"` — BM25 search over the summaries
- `kb get <doc> <section> [--level l2|l3]` — read one section
- `kb stats` — token counts per level
- `kb diff <doc> --against <rev>` — changed sections vs a git rev
- `kb publish` — mirror `.kb/` to the federation hub (hub from
  `.kb/config.yaml` or `--hub`); opens a PR on the hub by default
  (in your assistant: `/kb-publish` runs diff → confirm → publish)
- `kb resolve <file>` — resolve a kb-context block and check freshness
- `kb doctor` — sanity-check the setup
```

Rewrite `src/center_kb/templates/init/QUICKSTART-hub.md` (full new content):

```markdown
# CENTER-KB Quickstart (main hub)

This repo IS the hub: it hosts `federation/` (the single source of truth for
search) and runs the shared HTTP MCP server + Web UI. Child repos publish
into it; merging their PRs here is the review gate.

1. **Configure the token** — run `kb docker-setup` (in Claude Code / Copilot
   Chat / Cursor: `/kb-docker-setup`). It creates `.env` and generates
   `CENTER_KB_HTTP_TOKEN`. The token is auto-generated for convenience —
   replace it with your own secret for real deployments. Manual fallback:
   `cp .env.example .env`, then edit the token yourself.
2. **Serve the hub** — `docker compose up -d` → web UI at
   http://localhost:8321/ui (sign in with the token).
   Without Docker: `python -m center_kb.mcp --hub . --transport http`
   (requires the `CENTER_KB_HTTP_TOKEN` env var).
3. **Ingest this repo's own documents (optional)** — the hub may keep its own
   `.kb/`: put the PDF in `source/`, then
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   (prefer the `/kb-ingest` slash command; or run inside Docker:
   `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc`)
   Summaries: automatic with a local LLM CLI, or `/kb-summarize`; validate
   with `kb build`; then `kb publish` mirrors into `federation/<repo-id>/`.
4. **Query** — `kb query "your question"`, the web UI, or MCP. The local
   `.mcp.json` / `.cursor/mcp.json` run the stdio server for the hub
   maintainer; remote clients (child repos, BA machines) use the HTTP
   endpoint instead:
   `http://<host>:8321/mcp` with header `Authorization: Bearer <token>`.

## CLI reference

- `kb init` — scaffold or refresh a KB repo (asks hub|child; updates skills/templates; keeps `.kb/index.yaml`)
- `kb docker-setup` — hub only: create `.env` + generate the HTTP token
  (in your assistant: `/kb-docker-setup`)
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (in Claude Code / Copilot Chat / Cursor: `/kb-ingest`)
- `kb summarize` — fill pending summaries via a headless LLM CLI
  (in your assistant: `/kb-summarize`)
- `kb status` — list docs and their pending sections
- `kb build` — validate the KB (manifests, tables, tokens)
- `kb query "<question>"` — BM25 search over the summaries
- `kb get <doc> <section> [--level l2|l3]` — read one section
- `kb stats` — token counts per level
- `kb diff <doc> --against <rev>` — changed sections vs a git rev
- `kb publish` — mirror `.kb/` to the federation hub (hub from
  `.kb/config.yaml` or `--hub`); opens a PR on the hub by default
  (in your assistant: `/kb-publish` runs diff → confirm → publish)
- `kb resolve <file>` — resolve a kb-context block and check freshness
- `kb doctor` — sanity-check the setup
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py tests/test_templates.py -v`
Expected: PASS (2 xfail remain: the CLI tests until Task 5).

- [ ] **Step 5: Commit**

```bash
git add -A src/center_kb/templates tests/test_init.py
git commit -m "feat: child scaffold — ingest-only compose, HTTP .mcp.json, per-kind QUICKSTARTs"
```

---

### Task 4: Record `kind:` in legacy configs

**Files:**
- Modify: `src/center_kb/initcmd.py`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `init_repo` from Task 2.
- Produces: `init_repo` appends `kind: <kind>` to a pre-existing `.kb/config.yaml` that lacks the key (text append — comments/values preserved) and reports it as `".kb/config.yaml (kind recorded)"` in `report.updated` (removed from `report.skipped`).

- [ ] **Step 1: Write the failing tests**

Replace `test_init_does_not_overwrite_config` and add one test in `tests/test_init.py`:

```python
def test_init_records_kind_in_legacy_config_without_touching_values(tmp_path):
    init_repo(tmp_path, "hub")
    cfg = tmp_path / ".kb" / "config.yaml"
    cfg.write_text("# my comment\nhub: /my/hub\n", encoding="utf-8")
    report = init_repo(tmp_path, "hub")
    text = cfg.read_text(encoding="utf-8")
    assert text.startswith("# my comment\nhub: /my/hub\n")
    assert "kind: hub" in text
    assert ".kb/config.yaml (kind recorded)" in report.updated
    assert ".kb/config.yaml" not in report.skipped


def test_init_does_not_duplicate_kind_line(tmp_path):
    init_repo(tmp_path, "hub")
    cfg = tmp_path / ".kb" / "config.yaml"
    report = init_repo(tmp_path, "hub")
    assert cfg.read_text(encoding="utf-8").count("kind:") == 1
    assert ".kb/config.yaml" in report.skipped  # normal protected skip
```

Also update `test_init_is_idempotent_when_already_current`: the second run's `skipped` assertion stays `[".kb/index.yaml", ".kb/config.yaml"]` (fresh configs already contain `kind:` so nothing is recorded) — no change needed, just verify it still passes.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_init.py -v -k "legacy or duplicate_kind"`
Expected: FAIL — no `(kind recorded)` entry; legacy config unchanged.

- [ ] **Step 3: Implement**

In `src/center_kb/initcmd.py` add `import re` at the top and:

```python
_KIND_LINE = re.compile(r"^kind:", re.MULTILINE)


def _record_kind(config_path: Path, kind: str) -> bool:
    """Append `kind:` to a pre-existing config.yaml that lacks it.

    Narrow exception to the protected-file skip: only ever ADDS the missing
    line, never rewrites user content (comments and values survive).
    """
    if not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    if _KIND_LINE.search(text):
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    config_path.write_text(text + f"kind: {kind}\n", encoding="utf-8")
    return True
```

At the end of `init_repo`, just before `return report`:

```python
    if _record_kind(target / ".kb" / "config.yaml", kind):
        if ".kb/config.yaml" in report.skipped:
            report.skipped.remove(".kb/config.yaml")
        report.updated.append(".kb/config.yaml (kind recorded)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py -v`
Expected: PASS (2 xfail).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/initcmd.py tests/test_init.py
git commit -m "feat: record kind in legacy .kb/config.yaml on re-init"
```

---

### Task 5: CLI kind resolution (`--kind`, prompt, non-TTY error) + per-kind next steps

**Files:**
- Modify: `src/center_kb/cli.py` (the `init` command and new helpers)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `init_repo(target, kind, force)`, `load_config(kb_dir).kind`.
- Produces:
  - `kb init [PATH] [--kind hub|child] [--force]` with `class RepoKind(str, Enum)` (`hub`, `child`).
  - `cli._stdin_isatty() -> bool` — module-level helper, monkeypatched in tests.
  - `cli._resolve_kind(target: Path, kind_flag: RepoKind | None) -> str` — persisted > flag > prompt > exit.
  - Exit codes: 1 on persisted/flag conflict, 2 on non-interactive missing kind.

- [ ] **Step 1: Write the failing tests**

In `tests/test_init.py`, delete the two `xfail` markers and replace `test_cli_init_reports_and_next_steps` / `test_cli_init_updates_stale_scaffold`, then add the resolution tests:

```python
def test_cli_init_hub_reports_and_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])
    assert result.exit_code == 0
    assert "created" in result.output
    assert "kb docker-setup" in result.output
    assert "docker compose up -d" in result.output
    # re-run: persisted kind, no flag needed, idempotent
    result2 = runner.invoke(app, ["init", str(tmp_path)])
    assert result2.exit_code == 0
    assert "0 created" in result2.output
    assert "0 updated" in result2.output
    assert "2 skipped" in result2.output


def test_cli_init_child_next_steps(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "child"])
    assert result.exit_code == 0
    assert "Fill hub:" in result.output
    assert "kb publish" in result.output
    assert "docker compose up -d" not in result.output


def test_cli_init_updates_stale_scaffold(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])
    skill = tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    skill.write_text("stale\n", encoding="utf-8")
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])
    assert result.exit_code == 0
    assert "updated" in result.output
    assert "stale" not in skill.read_text(encoding="utf-8")


def test_cli_init_non_interactive_requires_kind(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path)])
    assert result.exit_code == 2
    assert "kb init requires --kind hub|child when not running interactively." in result.output


def test_cli_init_conflicting_kind_errors(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path), "--kind", "child"])
    result = runner.invoke(app, ["init", str(tmp_path), "--kind", "hub"])
    assert result.exit_code == 1
    assert "already initialized as 'child'" in result.output
    # nothing was scaffolded as hub
    assert not (tmp_path / ".env.example").exists()


def test_cli_init_interactive_prompt(tmp_path: Path, monkeypatch):
    from center_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="hub\n")
    assert result.exit_code == 0
    assert "Central knowledge hub" in result.output      # description shown
    assert "Authoring repo" in result.output
    assert (tmp_path / ".env.example").exists()


def test_cli_init_interactive_prompt_rejects_invalid_then_accepts(
    tmp_path: Path, monkeypatch
):
    from center_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(app, ["init", str(tmp_path)], input="server\nchild\n")
    assert result.exit_code == 0
    assert (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8").count(
        "kind: child"
    ) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_init.py -v -k "cli_init"`
Expected: FAIL — `--kind` is not a recognized option (usage error, exit 2 but with a different message; the assertion on message text fails).

- [ ] **Step 3: Implement**

In `src/center_kb/cli.py`, add near the top (after the existing imports):

```python
from enum import Enum

import click


class RepoKind(str, Enum):
    hub = "hub"
    child = "child"


KIND_DESCRIPTIONS = """\
This repo can be one of two kinds:

  hub   — Central knowledge hub. Hosts federation/, the single source of
          truth for search. Runs the shared HTTP MCP server + Web UI
          (docker compose up -d, port 8321). Receives publishes from child
          repos — merging hub PRs is the review gate that makes content
          searchable. May also keep its own .kb/ and publish itself.

  child — Authoring repo. Ingest PDFs → summarize → kb build → kb publish
          to the hub. Docker is only needed for one-shot ingest runs, not
          for a long-lived server. Must point hub: in .kb/config.yaml at
          the main hub. Does not host the company-wide MCP/Web service.
"""


def _stdin_isatty() -> bool:
    return sys.stdin.isatty()


def _resolve_kind(target: Path, kind_flag: RepoKind | None) -> str:
    """persisted kind > --kind flag > interactive prompt > hard error."""
    from center_kb.config import load_config

    persisted = load_config(target / ".kb").kind
    if persisted:
        if kind_flag is not None and kind_flag.value != persisted:
            typer.secho(
                f"this repo is already initialized as '{persisted}' "
                f"(.kb/config.yaml) — --kind {kind_flag.value} conflicts. "
                "Edit .kb/config.yaml deliberately if you really mean to switch.",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        return persisted
    if kind_flag is not None:
        return kind_flag.value
    if _stdin_isatty():
        typer.echo(KIND_DESCRIPTIONS)
        return typer.prompt(
            "Initialize this repo as", type=click.Choice(["hub", "child"])
        )
    typer.secho(
        "kb init requires --kind hub|child when not running interactively.",
        fg=typer.colors.RED,
    )
    raise typer.Exit(2)
```

Replace the `init` command body:

```python
@app.command()
def init(
    path: Path = typer.Argument(Path("."), help="Target directory (default: current)"),
    kind: RepoKind | None = typer.Option(
        None,
        "--kind",
        help="Repo kind: hub (hosts federation + the shared MCP/Web service) "
        "or child (authors and publishes to the hub). Required on first init "
        "when not running interactively.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Also overwrite protected data (.kb/index.yaml)",
    ),
) -> None:
    """Scaffold or refresh a KB repo: skills/templates update by default; data is preserved."""
    from center_kb.initcmd import init_repo

    resolved = _resolve_kind(path, kind)
    report = init_repo(path, resolved, force=force)
    for rel in report.created:
        typer.echo(f"  created  {rel}")
    for rel in report.updated:
        typer.echo(f"  updated  {rel}")
    for rel in report.skipped:
        typer.secho(
            f"  skipped  {rel} (protected data — use --force to overwrite)",
            fg=typer.colors.YELLOW,
        )
    typer.echo(
        f"kb init ({resolved}): {len(report.created)} created, "
        f"{len(report.updated)} updated, {len(report.skipped)} skipped."
    )
    typer.echo("Next steps:")
    if resolved == "hub":
        typer.echo(
            "  1. kb docker-setup   (or /kb-docker-setup in your AI assistant)"
            "  # .env + HTTP token"
        )
        typer.echo(
            "  2. docker compose up -d    # MCP HTTP + Web UI at http://localhost:8321/ui"
        )
        typer.echo("  3. kb ingest source/<file>.pdf --id <doc-id>")
    else:
        typer.echo("  1. Fill hub: in .kb/config.yaml with the main hub URL/path")
        typer.echo("  2. kb ingest source/<file>.pdf --id <doc-id>    (or /kb-ingest)")
        typer.echo("  3. kb publish    (or /kb-publish)")
    typer.echo("  (details: QUICKSTART.md)")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py -v`
Expected: PASS, no xfail remaining in this file.

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS. `tests/test_cli.py` and others invoke `init` via CliRunner in places — if any invoke `["init", ...]` without `--kind` on a fresh dir, they now exit 2: add `"--kind", "hub"` (or `"child"` where the test needs an unconfigured hub) at those call sites.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/cli.py tests/
git commit -m "feat: kb init requires kind — persisted > --kind > TTY prompt > error"
```

---

### Task 6: `kb docker-setup` CLI command

**Files:**
- Create: `src/center_kb/dockersetup.py`
- Modify: `src/center_kb/cli.py`
- Test: `tests/test_dockersetup.py` (new)

**Interfaces:**
- Consumes: `load_config(kb_dir).kind` (Task 1), `cli._stdin_isatty` (Task 5).
- Produces:
  - `dockersetup.run_setup(repo_root: Path, regenerate: bool = False) -> SetupReport` where `SetupReport` is a dataclass `(env_created: bool, gitignore_updated: bool)`.
  - `dockersetup.DockerSetupError(RuntimeError)` and `dockersetup.EnvExistsError(DockerSetupError)`.
  - `dockersetup.TOKEN_VAR = "CENTER_KB_HTTP_TOKEN"`.
  - CLI command `kb docker-setup [PATH] [--force]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dockersetup.py`:

```python
import re
from pathlib import Path

from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.initcmd import init_repo

runner = CliRunner()

TOKEN_RE = re.compile(r"^CENTER_KB_HTTP_TOKEN=([0-9a-f]{48})$", re.MULTILINE)


def test_run_setup_creates_env_with_token(tmp_path: Path):
    from center_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    report = run_setup(tmp_path)
    assert report.env_created
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    match = TOKEN_RE.search(env)
    assert match, env
    assert match.group(1) != "change-me"


def test_run_setup_synthesizes_env_without_example(tmp_path: Path):
    from center_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    (tmp_path / ".env.example").unlink()
    run_setup(tmp_path)
    assert TOKEN_RE.search((tmp_path / ".env").read_text(encoding="utf-8"))


def test_run_setup_refuses_existing_env_without_regenerate(tmp_path: Path):
    import pytest

    from center_kb.dockersetup import EnvExistsError, run_setup

    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text("CENTER_KB_HTTP_TOKEN=mine\n", encoding="utf-8")
    with pytest.raises(EnvExistsError):
        run_setup(tmp_path)
    assert "mine" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_run_setup_regenerates_with_flag(tmp_path: Path):
    from center_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text(
        "OTHER=keep\nCENTER_KB_HTTP_TOKEN=mine\n", encoding="utf-8"
    )
    report = run_setup(tmp_path, regenerate=True)
    assert not report.env_created
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "OTHER=keep" in env
    assert "mine" not in env
    assert TOKEN_RE.search(env)


def test_run_setup_refuses_child_and_kindless(tmp_path: Path):
    import pytest

    from center_kb.dockersetup import DockerSetupError, run_setup

    child = tmp_path / "c"
    child.mkdir()
    init_repo(child, "child")
    with pytest.raises(DockerSetupError, match="child"):
        run_setup(child)

    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(DockerSetupError, match="kb init"):
        run_setup(bare)


def test_run_setup_adds_env_to_gitignore(tmp_path: Path):
    from center_kb.dockersetup import run_setup

    init_repo(tmp_path, "hub")
    report = run_setup(tmp_path)
    assert report.gitignore_updated
    assert ".env" in (tmp_path / ".gitignore").read_text(encoding="utf-8").split()
    # second run with regenerate: already ignored, no duplicate
    report2 = run_setup(tmp_path, regenerate=True)
    assert not report2.gitignore_updated


def test_cli_docker_setup_happy_path_never_prints_token(tmp_path: Path):
    init_repo(tmp_path, "hub")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 0
    token = TOKEN_RE.search((tmp_path / ".env").read_text(encoding="utf-8")).group(1)
    assert token not in result.output
    assert "auto-generated" in result.output
    assert "secret manager" in result.output
    assert "docker compose up -d" in result.output
    assert "http://localhost:8321/ui" in result.output
    assert "Bearer <token>" in result.output


def test_cli_docker_setup_refuses_child(tmp_path: Path):
    init_repo(tmp_path, "child")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 1
    assert "child" in result.output
    assert not (tmp_path / ".env").exists()


def test_cli_docker_setup_existing_env_needs_force(tmp_path: Path):
    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text("CENTER_KB_HTTP_TOKEN=mine\n", encoding="utf-8")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)])
    assert result.exit_code == 1
    assert "--force" in result.output
    assert "mine" in (tmp_path / ".env").read_text(encoding="utf-8")
    result2 = runner.invoke(app, ["docker-setup", str(tmp_path), "--force"])
    assert result2.exit_code == 0
    assert "mine" not in (tmp_path / ".env").read_text(encoding="utf-8")


def test_cli_docker_setup_tty_confirm_regenerates(tmp_path: Path, monkeypatch):
    from center_kb import cli

    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    init_repo(tmp_path, "hub")
    (tmp_path / ".env").write_text("CENTER_KB_HTTP_TOKEN=mine\n", encoding="utf-8")
    result = runner.invoke(app, ["docker-setup", str(tmp_path)], input="y\n")
    assert result.exit_code == 0
    assert "mine" not in (tmp_path / ".env").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dockersetup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.dockersetup'` / unknown command `docker-setup`.

- [ ] **Step 3: Implement the module**

Create `src/center_kb/dockersetup.py`:

```python
from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from center_kb.config import load_config

TOKEN_VAR = "CENTER_KB_HTTP_TOKEN"
_TOKEN_LINE = re.compile(rf"^{TOKEN_VAR}=.*$", re.MULTILINE)
_DEFAULT_ENV = f"{TOKEN_VAR}=change-me\n"


class DockerSetupError(RuntimeError):
    """Setup cannot proceed (wrong repo kind, missing prerequisites)."""


class EnvExistsError(DockerSetupError):
    """.env already exists — the caller must opt into regenerating the token."""


@dataclass
class SetupReport:
    env_created: bool
    gitignore_updated: bool


def run_setup(repo_root: Path, regenerate: bool = False) -> SetupReport:
    """Prepare the hub for Docker HTTP serving: .env + a fresh random token.

    The token is written to .env only — callers must not echo it.
    """
    _require_hub_kind(repo_root)
    env_path = repo_root / ".env"
    env_created = not env_path.exists()
    if not env_created and not regenerate:
        raise EnvExistsError(
            "found existing .env — re-run with --force to regenerate the token"
        )
    if env_created:
        example = repo_root / ".env.example"
        base = (
            example.read_text(encoding="utf-8") if example.exists() else _DEFAULT_ENV
        )
    else:
        base = env_path.read_text(encoding="utf-8")
    line = f"{TOKEN_VAR}={secrets.token_hex(24)}"
    if _TOKEN_LINE.search(base):
        content = _TOKEN_LINE.sub(lambda _match: line, base, count=1)
    else:
        if base and not base.endswith("\n"):
            base += "\n"
        content = base + line + "\n"
    env_path.write_text(content, encoding="utf-8")
    return SetupReport(
        env_created=env_created, gitignore_updated=_ensure_gitignored(repo_root)
    )


def _require_hub_kind(repo_root: Path) -> None:
    kind = load_config(repo_root / ".kb").kind
    if kind == "child":
        raise DockerSetupError(
            "this repo is a child — kb docker-setup prepares the MAIN hub "
            "(the repo that hosts federation/ and the shared MCP/Web service)"
        )
    if kind != "hub":
        raise DockerSetupError(
            "repo kind is not recorded — run `kb init` first "
            "(it records kind: hub|child in .kb/config.yaml)"
        )


def _ensure_gitignored(repo_root: Path) -> bool:
    """Make sure .env never lands in git; returns True when .gitignore changed."""
    gitignore = repo_root / ".gitignore"
    lines = (
        gitignore.read_text(encoding="utf-8").splitlines()
        if gitignore.exists()
        else []
    )
    if any(line.strip() in (".env", "/.env") for line in lines):
        return False
    lines.append(".env")
    gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return True
```

Add the CLI command to `src/center_kb/cli.py` (after `init`):

```python
@app.command("docker-setup")
def docker_setup(
    path: Path = typer.Argument(Path("."), help="Hub repo root (default: current)"),
    force: bool = typer.Option(
        False, "--force", help="Regenerate the token inside an existing .env"
    ),
) -> None:
    """Hub only: create .env and generate CENTER_KB_HTTP_TOKEN for Docker HTTP serving."""
    from center_kb import dockersetup

    try:
        try:
            report = dockersetup.run_setup(path, regenerate=force)
        except dockersetup.EnvExistsError:
            if _stdin_isatty() and typer.confirm(
                f"Found existing .env — regenerate {dockersetup.TOKEN_VAR}?"
            ):
                report = dockersetup.run_setup(path, regenerate=True)
            else:
                raise
    except dockersetup.DockerSetupError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    action = "created" if report.env_created else "updated"
    typer.echo(
        f".env {action} — {dockersetup.TOKEN_VAR} written (token not shown; see .env)."
    )
    if report.gitignore_updated:
        typer.echo(".gitignore updated: added .env")
    typer.secho(
        "This token was auto-generated for convenience — replace it with your "
        "own secret for real deployments, and store it in a secret manager.",
        fg=typer.colors.YELLOW,
    )
    typer.echo("Next steps:")
    typer.echo("  1. docker compose up -d")
    typer.echo("  2. Open http://localhost:8321/ui (sign in with the token from .env)")
    typer.echo("  3. Point remote MCP clients at the hub:")
    typer.echo('     { "mcpServers": { "center-kb": { "type": "http",')
    typer.echo('       "url": "http://<host>:8321/mcp",')
    typer.echo('       "headers": { "Authorization": "Bearer <token>" } } } }')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_dockersetup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/dockersetup.py src/center_kb/cli.py tests/test_dockersetup.py
git commit -m "feat: kb docker-setup — hub-only .env creation + token generation"
```

---

### Task 7: docker-setup wrapper templates (Claude skill + command, Copilot prompt)

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-kb-docker-setup.md`, `claude-command-kb-docker-setup.md`, `copilot-kb-docker-setup.prompt.md`
- Modify: `src/center_kb/initcmd.py` (`HUB_TEMPLATES`)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `HUB_TEMPLATES`, `init_repo`, `expected_files`.
- Produces: three new hub-only scaffold targets: `.claude/skills/kb-docker-setup/SKILL.md`, `.claude/commands/kb-docker-setup.md`, `.github/prompts/kb-docker-setup.prompt.md`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_init.py`:

```python
def test_init_scaffolds_kb_docker_setup_hub_only(tmp_path: Path):
    hub_repo = tmp_path / "h"
    child_repo = tmp_path / "c"
    hub_repo.mkdir()
    child_repo.mkdir()
    init_repo(hub_repo, "hub")
    init_repo(child_repo, "child")
    skill = hub_repo / ".claude" / "skills" / "kb-docker-setup" / "SKILL.md"
    command = hub_repo / ".claude" / "commands" / "kb-docker-setup.md"
    prompt = hub_repo / ".github" / "prompts" / "kb-docker-setup.prompt.md"
    assert skill.is_file() and command.is_file() and prompt.is_file()
    skill_text = skill.read_text(encoding="utf-8")
    prompt_text = prompt.read_text(encoding="utf-8")
    assert "name: kb-docker-setup" in skill_text
    assert "mode: agent" in prompt_text
    for text in (skill_text, prompt_text):
        assert "kb docker-setup" in text          # wraps the CLI
        assert "NEVER print" in text              # secret stays out of chat
        assert "auto-generated" in text           # replace-token warning relayed
        assert "MAIN hub only" in text            # refusal explained
    command_text = command.read_text(encoding="utf-8")
    assert "kb-docker-setup" in command_text      # invokes the skill by name
    # child scaffold ships none of it
    assert not (child_repo / ".claude" / "skills" / "kb-docker-setup").exists()
    assert not (child_repo / ".github" / "prompts" / "kb-docker-setup.prompt.md").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_init.py::test_init_scaffolds_kb_docker_setup_hub_only -v`
Expected: FAIL — skill file does not exist.

- [ ] **Step 3: Create the templates and map entries**

`src/center_kb/templates/init/claude-skill-kb-docker-setup.md`:

```markdown
---
name: kb-docker-setup
description: Prepare the CENTER-KB hub for Docker HTTP serving — create .env and auto-generate the HTTP token. MAIN hub only; refuses on child repos.
---

# kb-docker-setup — prepare the hub for Docker HTTP serving

Thin wrapper around the `kb docker-setup` CLI. Your job: run the command,
relay its output, keep the secret out of the chat.

Hard rules:
- NEVER print the contents of `.env` (or the token) into the chat. The CLI
  deliberately does not echo the token; do not read the file to "show" it.
- This command is for the MAIN hub only. If the CLI refuses because the repo
  is a child (`kind: child` in `.kb/config.yaml`), relay that message — do
  NOT work around it by creating `.env` manually.

## Workflow

1. Run `kb docker-setup`.
   - It reports "found existing .env" → ask the user whether to regenerate
     the token, and only then re-run with `--force`.
2. Relay the output: `.env` written, the warning that the token was
   auto-generated (replace it with your own secret for real deployments and
   store it in a secret manager), and the next steps
   (`docker compose up -d`, the Web UI at http://localhost:8321/ui, the
   client MCP config snippet).
3. Non-zero exit → show the error verbatim and stop. Do not retry with
   guessed fixes.
```

`src/center_kb/templates/init/claude-command-kb-docker-setup.md`:

```markdown
---
description: Prepare the hub for Docker HTTP serving (.env + HTTP token) — MAIN hub only
---

Invoke the `kb-docker-setup` skill with the Skill tool and follow its
workflow exactly.
```

`src/center_kb/templates/init/copilot-kb-docker-setup.prompt.md`:

```markdown
---
mode: agent
description: Prepare the CENTER-KB hub for Docker HTTP serving — create .env and auto-generate the HTTP token. MAIN hub only.
---

# /kb-docker-setup — prepare the hub (.env + token)

Thin wrapper around the `kb docker-setup` CLI. Run the command, relay its
output, keep the secret out of the chat.

Hard rules:
- NEVER print the contents of `.env` (or the token) into the chat. The CLI
  deliberately does not echo the token; do not read the file to "show" it.
- This command is for the MAIN hub only. If the CLI refuses because the repo
  is a child (`kind: child` in `.kb/config.yaml`), relay that message — do
  NOT work around it by creating `.env` manually.

## Workflow

1. Run `kb docker-setup`.
   - It reports "found existing .env" → ask the user whether to regenerate
     the token, and only then re-run with `--force`.
2. Relay the output: `.env` written, the warning that the token was
   auto-generated (replace it with your own secret for real deployments and
   store it in a secret manager), and the next steps
   (`docker compose up -d`, the Web UI at http://localhost:8321/ui, the
   client MCP config snippet).
3. Non-zero exit → show the error verbatim and stop. Do not retry with
   guessed fixes.
```

In `src/center_kb/initcmd.py`, add to `HUB_TEMPLATES`:

```python
    ".claude/skills/kb-docker-setup/SKILL.md": "claude-skill-kb-docker-setup.md",
    ".claude/commands/kb-docker-setup.md": "claude-command-kb-docker-setup.md",
    ".github/prompts/kb-docker-setup.prompt.md": "copilot-kb-docker-setup.prompt.md",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py tests/test_templates.py -v`
Expected: PASS (the templates-exist test picks the new resources up via `HUB_TEMPLATES`).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates src/center_kb/initcmd.py tests/test_init.py
git commit -m "feat: kb-docker-setup wrappers for Claude and Copilot (hub scaffold)"
```

---

### Task 8: Cursor support — commands, rule, MCP wiring

**Files:**
- Create: `src/center_kb/templates/init/cursor-kb-ingest.md`, `cursor-kb-publish.md`, `cursor-kb-summarize.md`, `cursor-kb-summarize.mdc`, `cursor-kb-docker-setup.md`, `cursor-mcp-child.json`
- Modify: `src/center_kb/initcmd.py` (all three maps)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: the three template maps; the Copilot prompt templates (content basis — bodies are mirrored below).
- Produces: Cursor scaffold targets. Note: the hub's `.cursor/mcp.json` maps to the EXISTING `mcp-hub.json` resource (the stdio config is byte-identical for Claude and Cursor — no `cursor-mcp-hub.json` file needed; TEMPLATE_MAP maps two targets to one resource).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_init.py`:

```python
def test_init_scaffolds_cursor_commands_and_rule(tmp_path: Path):
    init_repo(tmp_path, "child")
    for name in ("kb-ingest", "kb-publish", "kb-summarize"):
        cmd = tmp_path / ".cursor" / "commands" / f"{name}.md"
        assert cmd.is_file(), name
        assert f"name: {name}" in cmd.read_text(encoding="utf-8")
    ingest = (tmp_path / ".cursor" / "commands" / "kb-ingest.md").read_text(
        encoding="utf-8"
    )
    assert "NEVER run `kb ingest`" in ingest
    assert "docker compose run --rm hub kb ingest" in ingest
    publish = (tmp_path / ".cursor" / "commands" / "kb-publish.md").read_text(
        encoding="utf-8"
    )
    assert "NEVER run `kb publish`" in publish
    rule = tmp_path / ".cursor" / "rules" / "kb-summarize.mdc"
    assert rule.is_file()
    rule_text = rule.read_text(encoding="utf-8")
    assert "globs: .kb/**" in rule_text
    assert "Summarize the prose ONLY" in rule_text
    assert "Table-only section:" in rule_text


def test_init_scaffolds_cursor_mcp_per_kind(tmp_path: Path):
    hub_repo = tmp_path / "h"
    child_repo = tmp_path / "c"
    hub_repo.mkdir()
    child_repo.mkdir()
    init_repo(hub_repo, "hub")
    init_repo(child_repo, "child")
    hub_mcp = (hub_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    assert "center_kb.mcp" in hub_mcp                      # stdio, same as .mcp.json
    assert hub_mcp == (hub_repo / ".mcp.json").read_text(encoding="utf-8")
    child_mcp = (child_repo / ".cursor" / "mcp.json").read_text(encoding="utf-8")
    assert "${env:CENTER_KB_HUB_URL}/mcp" in child_mcp     # Cursor env syntax
    assert "Bearer ${env:CENTER_KB_HTTP_TOKEN}" in child_mcp


def test_assistant_slash_command_parity(tmp_path: Path):
    """Every kb-* command exists for Claude, Copilot, and Cursor in each kind."""
    common = ["kb-ingest", "kb-publish", "kb-summarize"]
    layouts = {
        "claude": lambda n: (
            Path(".claude/commands") / f"{n}.md"
            if n in ("kb-summarize", "kb-docker-setup")
            else Path(".claude/skills") / n / "SKILL.md"
        ),
        "copilot": lambda n: (
            Path(".github/instructions/kb-summarize.instructions.md")
            if n == "kb-summarize"
            else Path(".github/prompts") / f"{n}.prompt.md"
        ),
        "cursor": lambda n: Path(".cursor/commands") / f"{n}.md",
    }
    for kind, names in (("hub", common + ["kb-docker-setup"]), ("child", common)):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        for assistant, layout in layouts.items():
            for name in names:
                assert (repo / layout(name)).is_file(), (kind, assistant, name)


def test_cursor_docker_setup_command_hub_only(tmp_path: Path):
    hub_repo = tmp_path / "h"
    child_repo = tmp_path / "c"
    hub_repo.mkdir()
    child_repo.mkdir()
    init_repo(hub_repo, "hub")
    init_repo(child_repo, "child")
    cmd = hub_repo / ".cursor" / "commands" / "kb-docker-setup.md"
    assert cmd.is_file()
    text = cmd.read_text(encoding="utf-8")
    assert "NEVER print" in text
    assert "MAIN hub only" in text
    assert not (child_repo / ".cursor" / "commands" / "kb-docker-setup.md").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_init.py -v -k "cursor or parity"`
Expected: FAIL — `.cursor/` files are not scaffolded.

- [ ] **Step 3: Create the Cursor templates**

`src/center_kb/templates/init/cursor-kb-ingest.md` — Cursor command frontmatter (`name`/`description`), body identical to the Copilot prompt body (everything below its frontmatter in `copilot-kb-ingest.prompt.md`):

```markdown
---
name: kb-ingest
description: Ingest a source PDF into the .kb/ knowledge base — interview for id/tags/revision, then run kb ingest
---

# /kb-ingest — ingest a PDF into CENTER-KB

Turn a source PDF into `.kb/` scaffolding via the `kb ingest` CLI. Your
job: resolve the file, confirm metadata with the user, run the command.

NEVER run `kb ingest` until the user has explicitly confirmed all three
values: document id, tags, and revision — even when they look obvious from
the file name. If the user already provided some of them, ask only for the
missing ones. "none" is a valid answer for tags and revision.

## Workflow

1. **Resolve the file.** The argument is a file name — look for it in
   `source/`. If that directory does not exist, list the repository root
   to find the actual source folder before giving up.
   - No argument given → list the PDFs in `source/` and ask which one.
   - File not found → say so, show the files that ARE present, and ask
     again. Never silently pick a different file.
2. **Propose metadata, then ask.** Derive suggestions from the file name:
   - `id`: short, stable, kebab-case (e.g. `ARINC424-22.pdf` → `arinc-424`)
   - `revision`: edition/supplement hints in the name (e.g. `Supplement 22`)
   - `tags`: 2–4 lowercase topical keywords
   Present all three suggestions and ask the user to confirm or correct
   each one. Wait for the answer before doing anything else.
3. **Run the command** (only after confirmation). Docker-first: the
   scaffold ships `docker-compose.yml` and the image bundles the ingest
   extra, so prefer it — no local Python setup needed.
   - **Docker path** — when `docker info` succeeds and
     `docker-compose.yml` exists:
     `docker compose run --rm hub kb ingest source/<file>.pdf --id <id> --tags "<tags>" --revision "<revision>" --no-summarize`
     The container has no LLM CLI, so `--no-summarize` is explicit; fill
     the summaries yourself afterwards (follow the kb-summarize rules),
     then validate with `docker compose run --rm hub kb build`.
   - **Local fallback** — when Docker is not available (daemon down or no
     compose file), use the local CLI (requires
     `pip install "center-kb[ingest]"`), which auto-summarizes as usual:
     `kb ingest source/<file>.pdf --id <id> --tags "<tags>" --revision "<revision>"`
   Omit `--tags` / `--revision` when the user answered "none".
4. **Report the outcome.** Relay the CLI output: number of sections,
   summarize result, `kb build` status.
   - Some sections failed to summarize → tell the user to run
     `kb summarize` and stop.
   - Non-zero exit → show the error output verbatim. Do NOT retry with
     guessed parameters; ask the user how to proceed.
```

`src/center_kb/templates/init/cursor-kb-publish.md` — same treatment for the publish prompt:

```markdown
---
name: kb-publish
description: Review and publish the local KB to the federation hub — diff vs the published snapshot, confirm, then kb publish (PR on the hub).
---

# /kb-publish — diff → confirm → publish (PR on the hub)

The hub federation is the single source of truth: content is searchable only
after the publish PR is merged on the hub. Local `.kb/` is just a drafting desk.

NEVER run `kb publish` until the user has explicitly confirmed, after
seeing the diff, that the current .kb/ state should be published.

## Workflow

1. **Check state.** Run `kb status`. If any section is still `pending`,
   stop and tell the user to summarize first (`kb summarize`, or the
   /kb-summarize command).
2. **Show what will be published.** Run `kb doctor` — it reports whether
   local .kb differs from the published snapshot. For each doc with
   changes, run `kb diff <doc-id> --against HEAD` (use another git rev if
   the user names one) and present the added/changed sections.
3. **Confirm — the gate.** State the hub (from `.kb/config.yaml`, or
   `CENTER_KB_HUB` if set) and that a publish PR will be opened on it
   (local-path hub → direct push). Ask for one explicit go/no-go and wait.
4. **Execute** (only after confirmation): `kb publish`. Relay the result:
   repo-id, source commit, doc count, and the **PR URL** — remind the user
   the content goes live when that PR is merged on the hub.
5. **Errors.**
   - Missing hub config → tell the user to fill `hub:` in `.kb/config.yaml`.
   - `gh` missing in PR mode → install GitHub CLI, or `kb publish --direct`
     only if direct pushes are allowed for this hub.
   - Other git/hub errors → show the stderr and suggest `kb doctor`.
```

`src/center_kb/templates/init/cursor-kb-summarize.md` — self-contained (Cursor has no sub-agent orchestrator; the writing rules live in the rule file):

```markdown
---
name: kb-summarize
description: Fill pending CENTER-KB summaries — kb status → edit L2/L1 per the writing rules → kb build
---

# /kb-summarize — fill pending summaries

Fill every pending summary in `.kb/` by editing the files directly. The
writing rules in `.cursor/rules/kb-summarize.mdc` apply to all `.kb/**`
edits — follow them exactly.

## Workflow

1. Run `kb status` and list the pending sections. An argument, if given, is
   a doc-id filter — only process that document.
2. For each pending section, read the matching `.raw.md` (L3) source, then:
   - in the L2 `.md` file, replace the
     `<!-- TODO:summarize <section-id> -->` marker with a condensed
     paragraph (never touch the tables);
   - in `_manifest.yaml`, set the section's one-sentence `summary`
     (≤ 25 words) and flip `status: pending` → `status: summarized`.
3. When every section of a doc is summarized, fill the doc's one-sentence
   `summary` in `.kb/index.yaml`.
4. Validate with `kb build` — it must pass. If it reports a table integrity
   error, restore the table verbatim from the `.raw.md` file.
```

`src/center_kb/templates/init/cursor-kb-summarize.mdc` — the rule (frontmatter + the writing-rules body mirrored from the Copilot instructions):

```markdown
---
description: CENTER-KB summary writing rules for .kb/ files
globs: .kb/**
alwaysApply: false
---

# CENTER-KB summarize rules

Files under `.kb/` belong to a CENTER-KB knowledge base. When editing them
to fill in summaries (after `kb ingest`), follow these rules exactly.

## What to edit

- In `.kb/<doc-id>/<file>.md` (L2): replace each
  `<!-- TODO:summarize <section-id> -->` marker with a condensed paragraph.
  Never touch the markdown tables — they are verbatim copies.
- In `.kb/<doc-id>/_manifest.yaml` (L1): set `summary` (one sentence,
  ≤ 25 words) per section and flip `status: pending` → `status: summarized`.
- In `.kb/index.yaml`: when every section of a doc is summarized, fill the
  doc's one-sentence `summary`.
- Nothing else. `.raw.md` files (L3) are read-only source text.

## Writing rules (mandatory)

- Write every summary in the **same language as the source text** in the
  matching `.raw.md` (L3) file — never translate. English source → English
  summary; Vietnamese source → Vietnamese summary. The only exception is the
  fixed `Table-only section: <title>.` label below, which stays in English so
  that it matches what `kb summarize` writes for the same case.
- Summarize the prose ONLY. Never describe, list, or reconstruct table
  contents — the tables are already copied verbatim into the section.
- If a section has no prose (heading + tables only): delete the marker
  line (leave nothing) and set the manifest `summary` to
  `Table-only section: <title>.` — do NOT invent prose about the tables.
- Keep the L2 paragraph under ~35% of the original prose length. If your
  draft is longer, compress harder.
- L2 paragraph: ~20–30% of the original length, keep the logical structure.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...),
  numeric values, units, cross-references (§x.y). Never paraphrase
  technical terms.
- Do NOT infer beyond the source text. When unsure, keep the original
  sentence.
- Do NOT summarize, create, or delete tables.

## Validate

After editing, run `kb build` — it must pass. If it reports a table
integrity error, restore the table verbatim from the `.raw.md` file.
```

`src/center_kb/templates/init/cursor-kb-docker-setup.md`:

```markdown
---
name: kb-docker-setup
description: Prepare the CENTER-KB hub for Docker HTTP serving — create .env and auto-generate the HTTP token. MAIN hub only.
---

# /kb-docker-setup — prepare the hub (.env + token)

Thin wrapper around the `kb docker-setup` CLI. Run the command, relay its
output, keep the secret out of the chat.

Hard rules:
- NEVER print the contents of `.env` (or the token) into the chat. The CLI
  deliberately does not echo the token; do not read the file to "show" it.
- This command is for the MAIN hub only. If the CLI refuses because the repo
  is a child (`kind: child` in `.kb/config.yaml`), relay that message — do
  NOT work around it by creating `.env` manually.

## Workflow

1. Run `kb docker-setup`.
   - It reports "found existing .env" → ask the user whether to regenerate
     the token, and only then re-run with `--force`.
2. Relay the output: `.env` written, the warning that the token was
   auto-generated (replace it with your own secret for real deployments and
   store it in a secret manager), and the next steps
   (`docker compose up -d`, the Web UI at http://localhost:8321/ui, the
   client MCP config snippet).
3. Non-zero exit → show the error verbatim and stop. Do not retry with
   guessed fixes.
```

`src/center_kb/templates/init/cursor-mcp-child.json`:

```json
{
  "mcpServers": {
    "center-kb": {
      "url": "${env:CENTER_KB_HUB_URL}/mcp",
      "headers": { "Authorization": "Bearer ${env:CENTER_KB_HTTP_TOKEN}" }
    }
  }
}
```

In `src/center_kb/initcmd.py`, add to `COMMON_TEMPLATES`:

```python
    ".cursor/commands/kb-ingest.md": "cursor-kb-ingest.md",
    ".cursor/commands/kb-publish.md": "cursor-kb-publish.md",
    ".cursor/commands/kb-summarize.md": "cursor-kb-summarize.md",
    ".cursor/rules/kb-summarize.mdc": "cursor-kb-summarize.mdc",
```

to `HUB_TEMPLATES`:

```python
    ".cursor/commands/kb-docker-setup.md": "cursor-kb-docker-setup.md",
    ".cursor/mcp.json": "mcp-hub.json",
```

to `CHILD_TEMPLATES`:

```python
    ".cursor/mcp.json": "cursor-mcp-child.json",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py tests/test_templates.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates src/center_kb/initcmd.py tests/test_init.py
git commit -m "feat: Cursor support — kb-* commands, .kb rule, per-kind .cursor/mcp.json"
```

---

### Task 9: `kb doctor` warns when kind is missing

**Files:**
- Modify: `src/center_kb/doctor.py`, `src/center_kb/cli.py` (doctor command)
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `load_config`, `Issue` dataclass in `doctor.py`.
- Produces: `doctor.check_kind(kb_dir: Path) -> list[Issue]` — `[]` when kind is set; one warning Issue when missing; one error Issue when config.yaml is unparseable.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_doctor.py`:

```python
def test_check_kind_warns_when_missing(tmp_path):
    from center_kb.doctor import check_kind

    # no config at all -> warn
    issues = check_kind(tmp_path)
    assert [i.level for i in issues] == ["warning"]
    assert "kind" in issues[0].message

    # kind present -> clean
    (tmp_path / "config.yaml").write_text("kind: hub\nhub: '.'\n", encoding="utf-8")
    assert check_kind(tmp_path) == []

    # invalid kind value -> error, not a crash
    (tmp_path / "config.yaml").write_text("kind: server\n", encoding="utf-8")
    issues = check_kind(tmp_path)
    assert [i.level for i in issues] == ["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_doctor.py -v -k check_kind`
Expected: FAIL — `ImportError: cannot import name 'check_kind'`.

- [ ] **Step 3: Implement**

In `src/center_kb/doctor.py` add (after `check_kb`; `yaml` and `ValidationError` are already imported):

```python
def check_kind(kb_dir: Path) -> list[Issue]:
    """Warn when the repo's hub|child kind is not recorded in config.yaml."""
    from center_kb.config import load_config

    try:
        kind = load_config(kb_dir).kind
    except (yaml.YAMLError, ValidationError) as exc:
        return [Issue("error", f"config.yaml is invalid: {_flatten(exc)}")]
    if not kind:
        return [
            Issue(
                "warning",
                "repo kind is not recorded in .kb/config.yaml — run `kb init` "
                "to record kind: hub|child",
            )
        ]
    return []
```

In `src/center_kb/cli.py`, inside the `doctor` command, change the import and the first `issues` line:

```python
    from center_kb.doctor import check_context, check_hub, check_kb, check_kind
```

```python
    issues = check_kind(kb_dir) + check_kb(kb_dir)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_doctor.py tests/test_doctor_hub.py tests/test_cli_doctor_diff.py -v`
Expected: PASS. If a pre-existing doctor test asserts an exact issue list on a kind-less fixture, it now sees one extra warning — add `kind: hub` (or the appropriate kind) to that fixture's config.yaml rather than weakening the assertion.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/doctor.py src/center_kb/cli.py tests/
git commit -m "feat: kb doctor warns when repo kind is not recorded"
```

---

### Task 10: README + final verification

**Files:**
- Modify: `README.md`
- Modify: `.kb/config.yaml` of THIS repo (record its kind — this repo is the hub for its own KB? Check `hub:` value: if it points at a hub, it is a child; if empty/`.`, treat as hub. Read the file first and pick accordingly — do NOT guess.)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update README**

Read `README.md:200-240`. Replace the `kb init` description sentence (around line 210, currently starting "Create a new KB repo: `kb init` (scaffolds `.kb/`, `federation/`, `.mcp.json`, CI workflow,") with:

```markdown
Create a new KB repo: `kb init` — it asks whether the repo is the **main hub**
(hosts `federation/` + the shared MCP HTTP server + Web UI) or a **child**
(authors and publishes to the hub) and scaffolds accordingly; non-interactive
runs pass `--kind hub|child`. The choice is recorded as `kind:` in
`.kb/config.yaml`, and re-runs reuse it. Hub repos then run `kb docker-setup`
(or the `/kb-docker-setup` slash command) to create `.env` and generate the
HTTP token. Slash commands (`/kb-ingest`, `/kb-summarize`, `/kb-publish`,
and on the hub `/kb-docker-setup`) are scaffolded for **Claude Code, GitHub
Copilot, and Cursor**; MCP client wiring ships as `.mcp.json` (Claude Code)
and `.cursor/mcp.json` (Cursor) — stdio on the hub, HTTP-with-env-vars on
children.
```

Also, in the Docker paragraph around line 230 ("**Docker:** `docker compose up -d` …"), append one sentence:

```markdown
First-time hub setup: `kb docker-setup` creates `.env` and generates
`CENTER_KB_HTTP_TOKEN` (auto-generated for convenience — replace it with your
own secret for real deployments).
```

Keep surrounding text intact; adjust only these two spots.

- [ ] **Step 2: Record this repo's kind**

Read `D:\Projects\AERO-KB\.kb\config.yaml`. If the file does not exist, skip this step. Otherwise: if `hub:` is empty or `"."`, append `kind: hub`; if it points elsewhere, append `kind: child`. (Manual append, preserving existing lines — same rule as `_record_kind`.)

- [ ] **Step 3: Full verification**

Run: `python -m pytest -q`
Expected: ALL PASS, no xfail markers remaining from this plan.

Run: `ruff check src tests`
Expected: clean.

Run a smoke test of both scaffolds in a temp dir:

```bash
cd "$(mktemp -d)" && mkdir hub-demo child-demo
kb init hub-demo --kind hub && kb docker-setup hub-demo
kb init child-demo --kind child
kb docker-setup child-demo; echo "exit=$? (expect 1)"
```

Expected: hub scaffold + `.env` created with warning text; child docker-setup refuses with exit 1.

- [ ] **Step 4: Commit**

```bash
git add README.md .kb/config.yaml
git commit -m "docs: role-aware init flow, kb docker-setup, and Cursor support in README"
```

---

## Self-Review Notes (already applied)

- Spec §2 prompt copy → `KIND_DESCRIPTIONS` (Task 5); exact non-TTY error string matches spec.
- Spec §3 matrix → Tasks 2/3/7/8 map entries; hub `.cursor/mcp.json` reuses `mcp-hub.json` (byte-identical stdio config) instead of a separate `cursor-mcp-hub.json` file — same semantics as the spec, one less duplicate resource.
- Spec §4 docker-setup behaviors → Task 6 (gate, .env, token, gitignore, output, no token echo).
- Spec §6 error table → Tasks 5 (exit 1 conflict / exit 2 non-TTY), 6 (child refusal, --force), 9 (doctor warning).
- Spec §7 test list → Tasks 1–9 test steps; parity test in Task 8.
- Spec §8 docs → Tasks 3 (QUICKSTARTs) and 10 (README).
- Type consistency: `init_repo(target, kind, force=False)` used identically in Tasks 2–8; `run_setup(repo_root, regenerate=False)` in Task 6 CLI and tests; `check_kind` naming consistent between Task 9 code and test.
