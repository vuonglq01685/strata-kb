# Asset Storage Init & Operations Tooling (Spec C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operator tooling for the asset store: `kb init --assets` scaffolding, a guided `/kb-init` command, `kb doctor` storage checks, and `kb assets migrate`/`verify`.

**Architecture:** `initcmd.py` gains an append-only `asset_store` recorder mirroring `_record_kind`; four `/kb-init` template files ride the existing `COMMON_TEMPLATES` machinery; `doctor.py` gains `check_asset_store` composed like the other checks; a new `assetcmd.py` holds `migrate_assets`/`verify_assets` with thin typer wrappers registered as the `kb assets` sub-app. Everything reuses spec B's `assetstore` seam (`store_for_hub`, `divert_and_record`, `MemoryStore`).

**Tech Stack:** Python ≥3.11, typer, pydantic, spec B's `assetstore`, pytest.

**Spec:** `docs/superpowers/specs/2026-07-17-asset-init-tooling-design.md`

## Global Constraints

- Run all tests with `.venv/bin/python -m pytest` from the repo root.
- Tests hermetic: no boto3, no network. Store seams take `MemoryStore` (or a failing stub); doctor's boto3-missing case uses an import-blocking monkeypatch.
- Profiles are `none | s3` only. `--assets` is hub-only: with kind child → error, exit 2.
- Config writes are **append-only** into protected `.kb/config.yaml`, mirroring `initcmd._record_kind` (never rewrite an existing `asset_store:` block).
- Size warning threshold: `ASSET_SIZE_WARN_BYTES = 100 * 1024 * 1024` (doctor, mode none).
- Reachability probe: one `store.exists()` on `assetstore.PROBE_NAME = "0" * 64 + ".png"` — `False` = reachable/OK; `AssetStoreError` = error.
- Migrate is forward-only (`none → s3`), scoped to `federation/` rids only, idempotent, one commit `assets: migrate to object store`; a failed rid's working tree is restored (`git checkout/clean -fd -- federation/<rid>`) before the command exits.
- `verify` never mutates anything; exit 0 OK / exit 1 on missing or dangling.
- Commit messages: `<type>: <description>`, no attribution footer.

---

### Task 1: `kb init --assets <none|s3>` — append-only config block

**Files:**
- Modify: `src/center_kb/initcmd.py` (add near `_record_kind`, lines 93-107), `src/center_kb/cli.py` (the `init` command, lines 107-160; `RepoKind` enum at line 43)
- Test: `tests/test_init.py`

**Interfaces:**
- Produces: `initcmd.record_asset_store(config_path: Path, mode: str) -> str` returning `"recorded" | "exists" | "no-config"`; `initcmd.init_repo(target, kind, force=False, assets: str | None = None)` — appends the block and reports; `InitReport.notes: list[str]` (new field, printed plainly by the CLI); CLI option `--assets` (enum `AssetsMode: none|s3`), hub-only.
- Consumes: existing `_record_kind` pattern, `InitReport`, `_resolve_kind`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_init.py`, matching its existing style)

```python
def test_record_asset_store_appends_s3_block(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("kind: hub\nhub: '.'\n", encoding="utf-8")
    assert initcmd.record_asset_store(cfg, "s3") == "recorded"
    text = cfg.read_text(encoding="utf-8")
    assert "kind: hub" in text  # existing content preserved
    assert "asset_store:" in text and "mode: s3" in text
    assert 'bucket: ""' in text and 'prefix: "assets/"' in text
    # parses into the spec B model
    from center_kb import config as config_mod

    assert config_mod.load_config(tmp_path).asset_store.mode == "s3"


def test_record_asset_store_appends_none_block(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("kind: hub\n", encoding="utf-8")
    assert initcmd.record_asset_store(cfg, "none") == "recorded"
    from center_kb import config as config_mod

    assert config_mod.load_config(tmp_path).asset_store.mode == "none"


def test_record_asset_store_never_rewrites_existing_block(tmp_path):
    cfg = tmp_path / "config.yaml"
    original = "kind: hub\nasset_store:\n  mode: s3\n  bucket: my-bucket\n"
    cfg.write_text(original, encoding="utf-8")
    assert initcmd.record_asset_store(cfg, "none") == "exists"
    assert cfg.read_text(encoding="utf-8") == original


def test_record_asset_store_missing_config(tmp_path):
    assert initcmd.record_asset_store(tmp_path / "config.yaml", "s3") == "no-config"


def test_init_repo_assets_records_block_and_reports(tmp_path):
    initcmd.init_repo(tmp_path, "hub")
    report = initcmd.init_repo(tmp_path, "hub", assets="s3")
    assert any("asset_store recorded" in u for u in report.updated)
    text = (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "mode: s3" in text


def test_init_repo_assets_exists_notes_left_unchanged(tmp_path):
    initcmd.init_repo(tmp_path, "hub", assets="s3")
    report = initcmd.init_repo(tmp_path, "hub", assets="none")
    assert any("left unchanged" in n for n in report.notes)
    text = (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    assert "mode: s3" in text and "mode: none" not in text


def test_cli_init_assets_rejected_for_child(tmp_path, ...cli runner fixture...):
    # run: kb init <tmp_path> --kind child --assets s3   (via the file's CLI runner)
    # assert exit code 2 and "hub" in the error output
    ...
```

The CLI test adapts to how `tests/test_init.py` (or `tests/test_cli.py`) invokes the `init` command today — read it first; the exit-2 + hub-only-message assertions are canonical.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_init.py -v -k asset`
Expected: FAIL — `AttributeError: module 'center_kb.initcmd' has no attribute 'record_asset_store'`

- [ ] **Step 3: Implement**

In `src/center_kb/initcmd.py`:

```python
ASSET_MODES = ("none", "s3")
_ASSET_STORE_LINE = re.compile(r"^asset_store:", re.MULTILINE)

_ASSET_BLOCKS = {
    "none": "asset_store:\n  mode: none\n",
    "s3": (
        "asset_store:\n"
        "  # Object store for image assets. Fill bucket (and endpoint for\n"
        "  # MinIO/R2); credentials come from the environment (boto3 chain).\n"
        "  mode: s3\n"
        '  bucket: ""\n'
        '  region: ""\n'
        '  endpoint: ""\n'
        '  prefix: "assets/"\n'
    ),
}


def record_asset_store(config_path: Path, mode: str) -> str:
    """Append an asset_store block to config.yaml when absent.

    Append-only, like _record_kind: an existing block is the operator's
    data and is never rewritten. Returns "recorded" | "exists" | "no-config".
    """
    if mode not in ASSET_MODES:
        raise ValueError(f"assets mode must be one of {ASSET_MODES}, got '{mode}'")
    if not config_path.exists():
        return "no-config"
    text = config_path.read_text(encoding="utf-8")
    if _ASSET_STORE_LINE.search(text):
        return "exists"
    if text and not text.endswith("\n"):
        text += "\n"
    config_path.write_text(text + _ASSET_BLOCKS[mode], encoding="utf-8", newline="\n")
    return "recorded"
```

Extend `InitReport` and `init_repo`:

```python
@dataclass
class InitReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
```

`init_repo` gains `assets: str | None = None`; after the `_record_kind` call at the end:

```python
    if assets is not None:
        outcome = record_asset_store(target / ".kb" / "config.yaml", assets)
        if outcome == "recorded":
            report.updated.append(".kb/config.yaml (asset_store recorded)")
        elif outcome == "exists":
            report.notes.append(
                "asset_store already configured in .kb/config.yaml — left unchanged"
            )
    return report
```

In `src/center_kb/cli.py`: add the enum next to `RepoKind`:

```python
class AssetsMode(str, Enum):
    none = "none"
    s3 = "s3"
```

In the `init` command signature add:

```python
    assets: AssetsMode | None = typer.Option(
        None,
        "--assets",
        help="Hub asset storage: none (assets in git, default) or s3 "
        "(object store — spec B). Hub kind only.",
    ),
```

and in the body, after `resolved = _resolve_kind(path, kind)`:

```python
    if assets is not None and resolved != "hub":
        typer.secho(
            "--assets applies to hubs only — a child never configures asset "
            "storage (bytes ride the publish transport to the hub).",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)
    report = init_repo(path, resolved, force=force, assets=assets.value if assets else None)
```

Print notes after the skipped loop:

```python
    for note in report.notes:
        typer.secho(f"  note     {note}", fg=typer.colors.YELLOW)
```

And extend the hub "Next steps" branch: when `assets is AssetsMode.s3`, add:

```python
        typer.echo(
            "  4. Assets (s3): fill bucket/region/endpoint in .kb/config.yaml, "
            'export credentials (AWS env chain), pip install "center-kb[s3]", '
            "then: kb doctor"
        )
```

- [ ] **Step 4: Run the init tests**

Run: `.venv/bin/python -m pytest tests/test_init.py tests/test_cli.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/initcmd.py src/center_kb/cli.py tests/test_init.py
git commit -m "feat: kb init --assets records asset_store block (hub only)"
```

---

### Task 2: `/kb-init` guided command templates

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-kb-init.md`, `src/center_kb/templates/init/claude-command-kb-init.md`, `src/center_kb/templates/init/copilot-kb-init.prompt.md`, `src/center_kb/templates/init/cursor-kb-init.md`
- Modify: `src/center_kb/initcmd.py` (`COMMON_TEMPLATES`, lines 13-36)
- Test: `tests/test_templates.py`, `tests/test_init.py`

**Interfaces:**
- Consumes: `kb init --kind <hub|child> [--assets <none|s3>]` (Task 1) and `kb doctor`.
- Produces: four template files scaffolded into every repo by `init_repo`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_init.py`:

```python
def test_init_scaffolds_kb_init_command_templates(tmp_path):
    initcmd.init_repo(tmp_path, "hub")
    for rel in (
        ".claude/skills/kb-init/SKILL.md",
        ".claude/commands/kb-init.md",
        ".github/prompts/kb-init.prompt.md",
        ".cursor/commands/kb-init.md",
    ):
        assert (tmp_path / rel).is_file(), rel
```

(`tests/test_templates.py` needs no new test — its existing resource-existence test iterates `COMMON_TEMPLATES` values and will cover the new entries automatically; just confirm it still passes.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_init.py -v -k kb_init`
Expected: FAIL — the four files are not created

- [ ] **Step 3: Add the template entries and files**

In `initcmd.py`, add to `COMMON_TEMPLATES`:

```python
    ".claude/skills/kb-init/SKILL.md": "claude-skill-kb-init.md",
    ".claude/commands/kb-init.md": "claude-command-kb-init.md",
    ".github/prompts/kb-init.prompt.md": "copilot-kb-init.prompt.md",
    ".cursor/commands/kb-init.md": "cursor-kb-init.md",
```

Create `src/center_kb/templates/init/claude-skill-kb-init.md`:

```markdown
---
name: kb-init
description: Guided setup for a CENTER-KB repo — choose the repo role (hub or child) and, for hubs, the asset storage mode, then scaffold and verify. Use when asked to set up or initialize a KB repo, or when the user invokes /kb-init.
---

# kb-init — guided repo setup

Thin wrapper around the `kb init` CLI. Your job: ask the two setup
questions, run the command, relay next steps, verify with `kb doctor`.

Hard rules:
- The ONLY way to scaffold is the `kb init` CLI — never hand-write
  `.kb/config.yaml` or template files.
- Never change an already-recorded kind or an existing `asset_store:`
  block; `kb init` refuses, and so should you.
- Non-zero exit → show the error verbatim and stop.

## Workflow

1. **Role** — ask which role this repo plays:
   - **hub** — aggregation + read/search server: hosts `federation/`,
     serves `/ui` + `/api` + `/mcp`, receives publishes, owns asset storage.
   - **child** — authoring repo: ingests PDFs, summarizes, publishes
     snapshots to the hub. Never configures asset storage.
   (Skip the question if `.kb/config.yaml` already records `kind:` — say so.)

2. **Assets mode** (hub only) — ask which storage mode:
   - **none** (recommended first run) — image assets stay in git; zero
     cloud setup. Fine for a compressed corpus; `kb doctor` warns if it
     outgrows plain git.
   - **s3** — assets go to an object store (AWS S3, MinIO, R2). Needs a
     private bucket and credentials in the environment.

3. **Run** `kb init --kind <role>` (add `--assets <mode>` for a hub) and
   relay its output.

4. **Next steps** — relay the CLI's own next-steps list. For `--assets s3`
   additionally walk the operator through: fill `bucket` (+ `endpoint` for
   MinIO/R2) in `.kb/config.yaml`, export credentials (AWS env chain),
   `pip install "center-kb[s3]"`.

5. **Verify** — run `kb doctor` and relay the result. For s3 it probes the
   bucket; expect `kb doctor: OK` before calling setup done. If assets
   already exist in git, mention `kb assets migrate`.
```

Create `src/center_kb/templates/init/claude-command-kb-init.md`:

```markdown
---
description: Guided CENTER-KB repo setup (role + asset storage) via kb init
---

Invoke the `kb-init` skill with the Skill tool and follow its workflow
exactly.
```

Create `src/center_kb/templates/init/copilot-kb-init.prompt.md` with the same content as the skill file but without the YAML frontmatter block, starting at the `# kb-init — guided repo setup` heading (Copilot prompts in this repo carry no frontmatter — confirm against an existing `copilot-kb-*.prompt.md` and match its header style if it differs).

Create `src/center_kb/templates/init/cursor-kb-init.md` the same way, matching the existing `cursor-kb-*.md` header style.

- [ ] **Step 4: Run the template and init tests**

Run: `.venv/bin/python -m pytest tests/test_templates.py tests/test_init.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init src/center_kb/initcmd.py tests/test_init.py
git commit -m "feat: guided /kb-init command templates for all assistants"
```

---

### Task 3: doctor storage checks + probe constant

**Files:**
- Modify: `src/center_kb/assetstore.py` (one constant), `src/center_kb/doctor.py`, `src/center_kb/cli.py` (the `doctor` command, lines 967-1020)
- Test: `tests/test_doctor.py`

**Interfaces:**
- Consumes: `assetstore.from_config`, `assetstore.AssetStoreError`, `assetstore.MemoryStore`, `config.load_config` (spec B / Task 1).
- Produces: `assetstore.PROBE_NAME = "0" * 64 + ".png"`; `doctor.ASSET_SIZE_WARN_BYTES = 100 * 1024 * 1024`; `doctor.check_asset_store(kb_dir: Path, handle, store=None) -> list[Issue]` (`store` test seam overrides construction); wired into the CLI `doctor` command. Task 4/5 reuse `PROBE_NAME`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_doctor.py`, matching its style)

```python
def _hub_cfg(tmp_path, block: str) -> Path:
    kb = tmp_path / ".kb"
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "config.yaml").write_text("kind: hub\n" + block, encoding="utf-8")
    return kb


def test_asset_store_none_mode_no_issues(tmp_path):
    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: none\n")
    assert doctor.check_asset_store(kb, None) == []


def test_asset_store_missing_block_no_issues(tmp_path):
    kb = _hub_cfg(tmp_path, "")
    assert doctor.check_asset_store(kb, None) == []


def test_asset_store_s3_empty_bucket_errors(tmp_path):
    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: s3\n")
    issues = doctor.check_asset_store(kb, None)
    assert any(i.level == "error" and "bucket" in i.message for i in issues)


def test_asset_store_s3_probe_ok(tmp_path):
    from center_kb import assetstore

    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: s3\n  bucket: b\n")
    assert doctor.check_asset_store(kb, None, store=assetstore.MemoryStore()) == []


def test_asset_store_s3_probe_failure_errors(tmp_path):
    from center_kb import assetstore

    class _Down(assetstore.MemoryStore):
        def exists(self, name):
            raise assetstore.AssetStoreError("connect timeout")

    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: s3\n  bucket: b\n")
    issues = doctor.check_asset_store(kb, None, store=_Down())
    assert any(i.level == "error" and "connect timeout" in i.message for i in issues)


def test_asset_store_none_mode_size_warning(tmp_path, monkeypatch):
    kb = _hub_cfg(tmp_path, "asset_store:\n  mode: none\n")
    assets = kb / "doc1" / "assets"
    assets.mkdir(parents=True)
    (assets / ("a" * 64 + ".png")).write_bytes(b"x" * 2048)
    monkeypatch.setattr(doctor, "ASSET_SIZE_WARN_BYTES", 1024)
    issues = doctor.check_asset_store(kb, None)
    assert any(i.level == "warning" and "s3" in i.message for i in issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_doctor.py -v -k asset_store`
Expected: FAIL — `AttributeError: module ... has no attribute 'check_asset_store'`

- [ ] **Step 3: Implement**

In `src/center_kb/assetstore.py` add near the other constants:

```python
# Well-known nonexistent key for reachability probes (doctor, kb assets):
# a clean "not found" proves bucket + credentials + endpoint work.
PROBE_NAME = "0" * 64 + ".png"
```

In `src/center_kb/doctor.py`:

```python
ASSET_SIZE_WARN_BYTES = 100 * 1024 * 1024


def check_asset_store(kb_dir: Path, handle, store=None) -> list[Issue]:
    """Storage health per asset_store mode; [] when the block is absent."""
    from center_kb import assetstore
    from center_kb.config import load_config

    try:
        cfg = load_config(kb_dir).asset_store
    except Exception:  # noqa: BLE001 — check_kind already reports invalid config
        return []
    if cfg.mode == "none":
        total = 0
        roots = [kb_dir]
        if handle is not None:
            roots.append(handle.federation_dir)
        for root in roots:
            if not root.is_dir():
                continue
            total += sum(
                p.stat().st_size for p in root.glob("**/assets/*") if p.is_file()
            )
        if total > ASSET_SIZE_WARN_BYTES:
            return [
                Issue(
                    "warning",
                    f"in-git assets total {total // (1024 * 1024)} MB — consider "
                    "asset_store mode: s3 (kb assets migrate) or git-LFS",
                )
            ]
        return []
    if store is None:
        try:
            store = assetstore.from_config(cfg)
        except assetstore.AssetStoreError as exc:
            return [Issue("error", f"asset_store: {_flatten(exc)}")]
    try:
        store.exists(assetstore.PROBE_NAME)
    except assetstore.AssetStoreError as exc:
        return [Issue("error", f"asset store unreachable: {_flatten(exc)}")]
    return []
```

(Empty bucket: `from_config` → `S3Store.__init__` raises `AssetStoreError("...bucket...")` — caught above. Missing boto3: the probe's lazy import raises the extra-naming `AssetStoreError` — also caught. Both surface as errors without special cases.)

In `src/center_kb/cli.py` `doctor` command, extend the imports and composition:

```python
    from center_kb.doctor import (
        check_asset_store,
        check_context,
        check_hub,
        check_kb,
        check_kind,
    )

    handle = _hub_or_exit(hub, kb_dir)
    issues = check_kind(kb_dir) + check_kb(kb_dir) + check_asset_store(kb_dir, handle)
```

- [ ] **Step 4: Run the doctor tests**

Run: `.venv/bin/python -m pytest tests/test_doctor.py tests/test_cli_doctor_diff.py tests/test_doctor_hub.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/assetstore.py src/center_kb/doctor.py src/center_kb/cli.py tests/test_doctor.py
git commit -m "feat: kb doctor asset-store checks (s3 probe, none-mode size warning)"
```

---

### Task 4: `kb assets migrate`

**Files:**
- Create: `src/center_kb/assetcmd.py`
- Modify: `src/center_kb/cli.py` (register the sub-app next to the existing `app.add_typer(context_app, name="context")` at line 21)
- Test: `tests/test_assetcmd.py` (new)

**Interfaces:**
- Consumes: `assetstore.store_for_hub`, `assetstore.divert_and_record`, `assetstore.AssetStoreError`, `assetstore.PROBE_NAME`, `assetstore.RECORD_NAME`, `gitio` helpers, `hub.HubHandle`.
- Produces: `assetcmd.AssetCmdError(RuntimeError)`; `assetcmd.migrate_assets(handle, store=None) -> MigrateReport` (`MigrateReport(per_rid: dict[str, int], committed: bool)`); CLI `kb assets migrate`. Task 5 adds `verify_assets` to the same module.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_assetcmd.py` (hub fixture: a real `git init` repo with `federation/<rid>/doc1/assets/<sha>.png`, following the hub-clone fixture style in `tests/test_publish.py` — read it first):

```python
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from center_kb import assetcmd, assetstore, gitio, models
from center_kb.hub import HubHandle

DATA = b"MIGRATEME"
SHA = hashlib.sha256(DATA).hexdigest()


@pytest.fixture
def hub_root(tmp_path) -> Path:
    root = tmp_path / "hub"
    assets = root / "federation" / "rid-a" / "doc1" / "assets"
    assets.mkdir(parents=True)
    (assets / f"{SHA}.png").write_bytes(DATA)
    (root / "federation" / "rid-a" / "doc1" / "ch1.md").write_text(
        f"![x](assets/{SHA}.png)\n", encoding="utf-8"
    )
    (root / ".kb").mkdir()
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: s3\n  bucket: b\n", encoding="utf-8"
    )
    gitio._run(root, "init", "-q")           # adapt to the file's git-helper style
    gitio._run(root, "add", "-A")
    gitio._run(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "seed")
    return root


def test_migrate_uploads_strips_records_commits(hub_root):
    store = assetstore.MemoryStore()
    report = assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    assert report.per_rid == {"rid-a": 1}
    assert report.committed
    assert store.get(f"{SHA}.png") == DATA
    dest = hub_root / "federation" / "rid-a"
    assert not (dest / "doc1" / "assets" / f"{SHA}.png").exists()
    rec = models.load_yaml_model(dest / "_assets.yaml", models.AssetsRecord)
    assert rec.assets == [f"doc1/assets/{SHA}.png"]
    tracked = gitio._run(hub_root, "ls-files", "--", "federation").stdout
    assert f"{SHA}.png" not in tracked and "_assets.yaml" in tracked
    status = gitio._run(hub_root, "status", "--porcelain").stdout.strip()
    assert status == ""  # everything committed


def test_migrate_second_run_noop(hub_root):
    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    report = assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    assert report.per_rid == {} or all(n == 0 for n in report.per_rid.values())
    assert not report.committed


def test_migrate_requires_s3_mode(hub_root):
    (hub_root / ".kb" / "config.yaml").write_text("kind: hub\n", encoding="utf-8")
    with pytest.raises(assetcmd.AssetCmdError, match="mode"):
        assetcmd.migrate_assets(HubHandle(root=hub_root))


def test_migrate_failure_restores_failed_rid(hub_root):
    class _Down(assetstore.MemoryStore):
        def put(self, name, data):
            raise assetstore.AssetStoreError("bucket down")

    with pytest.raises(assetstore.AssetStoreError):
        assetcmd.migrate_assets(HubHandle(root=hub_root), store=_Down())
    # failed rid restored: binaries back, no half state, nothing staged
    assert (hub_root / "federation" / "rid-a" / "doc1" / "assets" / f"{SHA}.png").exists()
    status = gitio._run(hub_root, "status", "--porcelain", "--", "federation").stdout.strip()
    assert status == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_assetcmd.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.assetcmd'`

- [ ] **Step 3: Implement**

Create `src/center_kb/assetcmd.py`:

```python
"""Operator commands for the asset store: migrate (none→s3 backfill) and
verify (coverage check). Both run against a hub clone and never touch a
child's .kb/."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from center_kb import assetstore, gitio, models

logger = logging.getLogger("center_kb.assetcmd")

_REF_RE = re.compile(r"assets/([0-9a-f]{64}\.(?:png|webp))")


class AssetCmdError(RuntimeError):
    """Preconditions unmet (mode/config), distinct from store failures."""


@dataclass
class MigrateReport:
    per_rid: dict[str, int] = field(default_factory=dict)
    committed: bool = False


def _require_store(handle, store):
    if store is not None:
        return store
    resolved = assetstore.store_for_hub(handle)
    if resolved is None:
        raise AssetCmdError(
            "asset_store.mode is not s3 in the hub's .kb/config.yaml — "
            "run `kb init --assets s3` and fill the bucket first"
        )
    resolved.exists(assetstore.PROBE_NAME)  # reachability; raises AssetStoreError
    return resolved


def _rid_dirs(handle) -> list[Path]:
    fed = handle.federation_dir
    if not fed.is_dir():
        return []
    return sorted(p for p in fed.iterdir() if p.is_dir())


def migrate_assets(handle, store=None) -> MigrateReport:
    """Divert every in-git asset under federation/ to the store, rid by rid.

    Idempotent: content-addressed puts skip existing keys; upload precedes
    unlink (spec B ordering) so there is no image-down window. A failed
    rid's working tree is restored before the error surfaces, so a later
    unrelated commit can never pick up half-migrated state."""
    store = _require_store(handle, store)
    report = MigrateReport()
    for rid_dir in _rid_dirs(handle):
        try:
            diverted = assetstore.divert_and_record(rid_dir, store)
        except assetstore.AssetStoreError:
            rel = f"federation/{rid_dir.name}"
            for args in (("checkout", "--", rel), ("clean", "-fd", "--", rel)):
                result = gitio._run(handle.root, *args)
                if result.returncode != 0:
                    logger.warning("restore failed: git %s: %s", args, result.stderr)
            raise
        if diverted:
            report.per_rid[rid_dir.name] = len(diverted)
    if report.per_rid:
        report.committed = gitio.commit_paths(
            handle.root, "assets: migrate to object store", ["federation"]
        )
    return report
```

(Adapt the two `gitio._run` calls to `gitio`'s actual helper signatures — read `src/center_kb/gitio.py` first; the intake failure-path in `src/center_kb/intake.py` uses the same restore pair and is the reference.)

In `src/center_kb/cli.py`, next to the existing sub-app registration (line 21):

```python
assets_app = typer.Typer(help="Asset store operations (hub): migrate, verify")
app.add_typer(assets_app, name="assets")
```

and the command (near the other hub-side commands, using the same `_hub_or_exit` pattern the `doctor` command uses):

```python
@assets_app.command()
def migrate(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Move in-git federation assets to the configured object store (none → s3)."""
    from center_kb import assetcmd, assetstore

    handle = _hub_or_exit(hub, kb_dir)
    try:
        report = assetcmd.migrate_assets(handle)
    except (assetcmd.AssetCmdError, assetstore.AssetStoreError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    for rid, n in sorted(report.per_rid.items()):
        typer.echo(f"  {rid}: {n} asset(s) migrated")
    if not report.per_rid:
        typer.echo("nothing to migrate — no in-git assets under federation/")
    elif report.committed:
        typer.echo("committed: assets: migrate to object store")
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_assetcmd.py tests/test_cli.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/assetcmd.py src/center_kb/cli.py tests/test_assetcmd.py
git commit -m "feat: kb assets migrate — forward-only none-to-s3 backfill"
```

---

### Task 5: `kb assets verify`

**Files:**
- Modify: `src/center_kb/assetcmd.py`, `src/center_kb/cli.py` (the `assets_app` from Task 4)
- Test: `tests/test_assetcmd.py`

**Interfaces:**
- Consumes: Task 4's module scaffolding (`_REF_RE`, `_rid_dirs`, `AssetCmdError`), `assetstore.RECORD_NAME`, `assetstore.store_for_hub`, `models.AssetsRecord`.
- Produces: `assetcmd.verify_assets(handle, store=None) -> VerifyReport` — `VerifyReport(missing_records: list[str], dangling_refs: list[str], orphans: list[str])`, `.ok` property; CLI `kb assets verify` (exit 1 on missing/dangling; orphans informational).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_assetcmd.py`; reuses the Task 4 fixture)

```python
def _migrated_hub(hub_root) -> assetstore.MemoryStore:
    store = assetstore.MemoryStore()
    assetcmd.migrate_assets(HubHandle(root=hub_root), store=store)
    return store


def test_verify_ok_after_migrate(hub_root):
    store = _migrated_hub(hub_root)
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert report.ok
    assert report.missing_records == [] and report.dangling_refs == []


def test_verify_reports_missing_record_entry(hub_root):
    store = _migrated_hub(hub_root)
    store.data.clear()  # bytes vanished from the bucket
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert not report.ok
    assert any(SHA in m for m in report.missing_records)
    assert any(SHA in d for d in report.dangling_refs)


def test_verify_reports_dangling_ref(hub_root):
    store = _migrated_hub(hub_root)
    ghost = "9" * 64
    md = hub_root / "federation" / "rid-a" / "doc1" / "ch1.md"
    md.write_text(md.read_text(encoding="utf-8") + f"![g](assets/{ghost}.png)\n", encoding="utf-8")
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert any(ghost in d for d in report.dangling_refs)


def test_verify_reports_orphan_record_entry(hub_root):
    store = _migrated_hub(hub_root)
    md = hub_root / "federation" / "rid-a" / "doc1" / "ch1.md"
    md.write_text("no refs anymore\n", encoding="utf-8")
    report = assetcmd.verify_assets(HubHandle(root=hub_root), store=store)
    assert report.ok  # orphans are informational only
    assert any(SHA in o for o in report.orphans)


def test_verify_local_mode_checks_files(hub_root):
    # mode none: record entries must resolve as local files
    (hub_root / ".kb" / "config.yaml").write_text(
        "kind: hub\nasset_store:\n  mode: none\n", encoding="utf-8"
    )
    dest = hub_root / "federation" / "rid-a"
    models.save_yaml_model(
        dest / "_assets.yaml", models.AssetsRecord(assets=["doc1/assets/" + "8" * 64 + ".png"])
    )
    report = assetcmd.verify_assets(HubHandle(root=hub_root))
    assert not report.ok and report.missing_records
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_assetcmd.py -v -k verify`
Expected: FAIL — `AttributeError: ... no attribute 'verify_assets'`

- [ ] **Step 3: Implement** (append to `src/center_kb/assetcmd.py`)

```python
@dataclass
class VerifyReport:
    missing_records: list[str] = field(default_factory=list)
    dangling_refs: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing_records and not self.dangling_refs


def _record_entries(rid_dir: Path) -> list[str]:
    path = rid_dir / assetstore.RECORD_NAME
    if not path.exists():
        return []
    try:
        return models.load_yaml_model(path, models.AssetsRecord).assets
    except Exception:  # noqa: BLE001 — a corrupt record is a verify finding
        return []


def _entry_resolves(rid_dir: Path, rel: str, store) -> bool:
    if (rid_dir / rel).is_file():
        return True
    return store is not None and store.exists(Path(rel).name)


def verify_assets(handle, store=None) -> VerifyReport:
    """Read-only coverage check: record entries resolvable, markdown refs
    resolvable, orphan record entries listed (informational)."""
    if store is None:
        store = assetstore.store_for_hub(handle)  # None in mode: none
    report = VerifyReport()
    referenced: set[str] = set()
    recorded: dict[str, str] = {}  # basename -> "rid: relpath"

    for rid_dir in _rid_dirs(handle):
        for rel in _record_entries(rid_dir):
            label = f"{rid_dir.name}: {rel}"
            recorded[Path(rel).name] = label
            if not _entry_resolves(rid_dir, rel, store):
                report.missing_records.append(label)

    md_roots = [handle.federation_dir, handle.kb_dir]
    local_names = {
        p.name
        for root in md_roots
        if root.is_dir()
        for p in root.glob("**/assets/*")
        if p.is_file()
    }
    for root in md_roots:
        if not root.is_dir():
            continue
        for md in root.rglob("*.md"):
            for m in _REF_RE.finditer(md.read_text(encoding="utf-8", errors="replace")):
                name = m.group(1)
                referenced.add(name)
                if name in local_names:
                    continue
                if name in recorded and store is not None and store.exists(name):
                    continue
                report.dangling_refs.append(f"{md.relative_to(handle.root)}: {name}")

    report.orphans = sorted(
        label for name, label in recorded.items() if name not in referenced
    )
    report.dangling_refs = sorted(set(report.dangling_refs))
    return report
```

CLI command (append to the `assets_app` block in `cli.py`):

```python
@assets_app.command()
def verify(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = config)"
    ),
) -> None:
    """Check asset coverage: records vs store, markdown refs, orphans."""
    from center_kb import assetcmd, assetstore

    handle = _hub_or_exit(hub, kb_dir)
    try:
        report = assetcmd.verify_assets(handle)
    except (assetcmd.AssetCmdError, assetstore.AssetStoreError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    for label in report.missing_records:
        typer.secho(f"[missing] recorded but not in store: {label}", fg=typer.colors.RED)
    for label in report.dangling_refs:
        typer.secho(f"[dangling] referenced but unresolvable: {label}", fg=typer.colors.RED)
    for label in report.orphans:
        typer.echo(f"[orphan] recorded but never referenced: {label}")
    if not report.ok:
        raise typer.Exit(1)
    typer.echo("kb assets verify: OK")
```

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_assetcmd.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/assetcmd.py src/center_kb/cli.py tests/test_assetcmd.py
git commit -m "feat: kb assets verify — record, reference, and orphan coverage"
```

---

### Task 6: QUICKSTART storage section + full verification

**Files:**
- Modify: `src/center_kb/templates/init/QUICKSTART-hub.md`
- Test: full suite + gate

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Add the storage section**

Read `src/center_kb/templates/init/QUICKSTART-hub.md`, match its tone, add a "Asset storage" section covering exactly (prose, not this outline):

1. `mode: none` (default): image assets live in git; fine for a compressed corpus; `kb doctor` warns past ~100 MB.
2. Switching to s3 — the checklist: create a **private** bucket (block public access), create credentials scoped to Get/Put/Head on the `assets/` prefix, export them (AWS env chain; set `endpoint` in the config for MinIO/R2), `pip install "center-kb[s3]"`, run `kb init --assets s3` (or edit `.kb/config.yaml`), fill `bucket`/`region`/`endpoint`, `kb doctor`, then `kb assets migrate` if assets already exist in git, `kb assets verify` to confirm.
3. Manual rollback (s3 → none): download each `assets/<sha>` named in the `_assets.yaml` files back into its rid tree, delete the `_assets.yaml` files, set `mode: none`, commit — the local-first resolver keeps serving throughout.
4. Optional git-LFS note for large `mode: none` corpora.

- [ ] **Step 2: Full verification**

Run: `.venv/bin/python -m pytest tests -q`
Expected: all pass, no regressions.
Run the gate per the repo's documented invocation (`scripts/gate.sh`).
Expected: all tiers green. If `uv lock --check` fails, no dependency changed in this spec — that would be a bug, not a relock case: STOP and investigate.

- [ ] **Step 3: Commit**

```bash
git add src/center_kb/templates/init/QUICKSTART-hub.md
git commit -m "docs: hub QUICKSTART asset-storage section (setup, migrate, rollback)"
```

---

## Self-Review Notes

- Spec §3 (`kb init --assets`) → Task 1. §4 (`/kb-init` templates) → Task 2. §5 (doctor) → Task 3. §6.1 (migrate) → Task 4. §6.2 (verify) → Task 5. §7 (QUICKSTART) → Task 6. §8 error handling → Tasks 1 (exit 2 child), 3 (probe/bucket/boto3 errors), 4 (restore-on-failure, doctor-style errors, exit 1), 5 (read-only, exit 1). §9 testing → every task.
- Type consistency: `record_asset_store` outcomes ("recorded"/"exists"/"no-config") used identically in Task 1's tests and implementation; `PROBE_NAME` defined Task 3, consumed Task 4 (`_require_store`); `MigrateReport`/`VerifyReport` field names match between tests and code; `AssetCmdError` raised in Task 4, caught in both CLI wrappers.
- Known adaptation points called out explicitly rather than guessed: `gitio._run` helper signatures (Task 4 — intake's restore pair is the reference), CLI runner fixture style (Task 1), copilot/cursor template header conventions (Task 2).
