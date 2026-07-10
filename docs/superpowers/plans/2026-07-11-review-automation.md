# Review Automation (`kb approve` + CI auto-flip) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `kb approve` command that flips section `status: summarized → reviewed`, plus a GitHub Action that runs it automatically when a PR merges into `main`.

**Architecture:** Change detection reuses `diff.py` (extended to also detect L2 prose changes). A new `review.py` module holds the approve logic and consumes `DiffReport`. `cli.py` registers the `approve` command following the existing typer patterns. A new workflow `kb-review.yml` runs `kb approve --all-changed` after each push to `main` touching `.kb/**` and commits the flips back with three loop guards.

**Tech Stack:** Python 3.10+ (CI uses 3.12), typer, pydantic, PyYAML, pytest (`typer.testing.CliRunner`), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-07-11-review-automation-design.md` — read it before starting; exit-code semantics and trade-offs live there.

## Global Constraints

- ALL code, comments, docstrings, and CLI strings in **English** (repo-wide rule; README/spec docs are Vietnamese).
- `kb build` must NOT change any status — it stays pure validation.
- No new fields in `_manifest.yaml` / `.kb/` format; only the `status` value changes.
- Manifest writes go through `models.save_yaml_model` (keeps YAML format stable).
- Errors surface as `typer.secho(..., fg=typer.colors.RED)` + `typer.Exit(1)`; warnings as yellow to stderr (`err=True`) — match `cli.py` conventions.
- Exit-code contract (spec §3.1): explicit request that flips nothing = exit 1; `--all-changed` scan that finds nothing = exit 0.
- Heavy imports inside command functions (lazy import), as all existing commands do.
- Conventional commit messages (`feat:`, `test:`, `docs:`, `ci:`), no attribution footer.
- Run tests with `python -m pytest <file> -v` from the repo root (venv active).

---

### Task 1: Extend `diff.py` — detect L2 prose changes

`diff_doc()` currently compares L1 (manifest `summary`) and L3 (`{file}.raw.md`) but not L2 (`{file}.md`). Add `prose_changed` to `SectionChange`, compare L2 the same way L3 is compared, and extract the duplicated slice-and-compare logic into one helper.

**Files:**
- Modify: `src/aero_kb/diff.py`
- Test: `tests/test_diff.py`

**Interfaces:**
- Consumes: `gitio.read_at`, `mdutils.slice_section` (existing).
- Produces: `SectionChange` gains field `prose_changed: bool = False` (order: `summary_changed`, `prose_changed`, `content_changed`). `DiffReport` unchanged. `render_diff` prints kind `prose` alongside `summary`/`content`. Task 3 relies on `diff_doc(kb_dir, doc_id, against)` returning added/changed including L2-only edits.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_diff.py`:

```python
def test_prose_changed_when_l2_edited(git_kb):
    # edit ONLY the L2 prose of §1.2 — summary (L1) and raw (L3) untouched
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "airway record structure, route identifiers.",
            "airway record structure, REVISED identifiers.",
        ),
        encoding="utf-8",
    )
    report = diff_doc(git_kb["kb"], "demo-doc", against="HEAD")
    assert [c.section_id for c in report.changed] == ["1.2"]
    change = report.changed[0]
    assert change.prose_changed is True
    assert change.summary_changed is False
    assert change.content_changed is False
    assert "prose" in render_diff(report)
```

Also extend the existing `test_changed_summary_detected` (the `git_kb` fixture changes §1.1's L2 *and* summary between rev1 and HEAD — see `tests/conftest.py:129-142`). Add one line after the `content_changed` assert:

```python
    assert report.changed[0].prose_changed is True
```

and update its comment to:

```python
    # fixture: §1.1's summary (L1) + prose (L2) change between rev1 and the worktree; L3 stays the same
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_diff.py -v`
Expected: `test_prose_changed_when_l2_edited` FAILS with `AttributeError: 'SectionChange' object has no attribute 'prose_changed'` (or TypeError); `test_changed_summary_detected` FAILS on the new assert.

- [ ] **Step 3: Implement in `src/aero_kb/diff.py`**

Add the field to `SectionChange`:

```python
@dataclass
class SectionChange:
    section_id: str
    title: str
    summary_changed: bool = False
    prose_changed: bool = False
    content_changed: bool = False
```

Add a helper below `_raw_section` (this replaces the inline cache logic currently at lines 73-86):

```python
def _level_changed(
    root: Path,
    against: str,
    doc_dir: Path,
    sec_id: str,
    new_file: str,
    old_file: str,
    suffix: str,
    cache_new: dict[str, str | None],
    cache_old: dict[str, str | None],
) -> bool:
    """Compare one section's slice of a level file (worktree vs `against`)."""
    if new_file not in cache_new:
        path = doc_dir / f"{new_file}{suffix}"
        cache_new[new_file] = (
            path.read_text(encoding="utf-8") if path.exists() else None
        )
    new_text = _raw_section(cache_new[new_file], sec_id)
    if old_file not in cache_old:
        cache_old[old_file] = gitio.read_at(
            root, against, doc_dir / f"{old_file}{suffix}"
        )
    old_text = _raw_section(cache_old[old_file], sec_id)
    return (new_text or "").strip() != (old_text or "").strip()
```

In `diff_doc()`, replace the loop body from `raw_cache_old: dict...` down to the `report.changed.append(...)` block with:

```python
    raw_cache_old: dict[str, str | None] = {}
    raw_cache_new: dict[str, str | None] = {}
    prose_cache_old: dict[str, str | None] = {}
    prose_cache_new: dict[str, str | None] = {}
    for sec in new.sections:
        old_sec = old_by_id.get(sec.id)
        if old_sec is None:
            continue
        summary_changed = old_sec.summary.strip() != sec.summary.strip()
        prose_changed = _level_changed(
            root, against, doc_dir, sec.id, sec.file, old_sec.file,
            ".md", prose_cache_new, prose_cache_old,
        )
        content_changed = _level_changed(
            root, against, doc_dir, sec.id, sec.file, old_sec.file,
            ".raw.md", raw_cache_new, raw_cache_old,
        )
        if summary_changed or prose_changed or content_changed:
            report.changed.append(
                SectionChange(
                    sec.id,
                    sec.title,
                    summary_changed=summary_changed,
                    prose_changed=prose_changed,
                    content_changed=content_changed,
                )
            )
    return report
```

In `render_diff()`, extend the kinds tuple:

```python
        kinds = [
            k
            for k, on in (
                ("summary", c.summary_changed),
                ("prose", c.prose_changed),
                ("content", c.content_changed),
            )
            if on
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_diff.py tests/test_cli_doctor_diff.py -v`
Expected: all PASS (existing diff/doctor CLI tests must not regress).

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/diff.py tests/test_diff.py
git commit -m "feat: detect L2 prose changes in kb diff"
```

---

### Task 2: `review.py` — core approve logic (per-doc and per-section)

New module with the status-flip function. Only `summarized` sections flip; `pending` is skipped and reported; `reviewed` stays untouched (idempotent).

**Files:**
- Create: `src/aero_kb/review.py`
- Test: `tests/test_review.py` (new)

**Interfaces:**
- Consumes: `models.load_yaml_model`, `models.save_yaml_model`, `models.Manifest`.
- Produces (Tasks 3 and 4 rely on these exact signatures):
  - `@dataclass ApproveReport` with fields `doc_id: str`, `flipped: list[str]`, `skipped_pending: list[str]`, `missing: list[str]` (all lists default to empty).
  - `approve_sections(kb_dir: Path, doc_id: str, section_ids: list[str] | None = None) -> ApproveReport` — raises `ValueError` if the doc's manifest doesn't exist.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_review.py`:

```python
import pytest

from aero_kb import models
from aero_kb.review import approve_sections


def _statuses(kb, doc_id="demo-doc"):
    manifest = models.load_yaml_model(kb / doc_id / "_manifest.yaml", models.Manifest)
    return {s.id: s.status for s in manifest.sections}


def test_approve_flips_all_summarized_sections(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc")
    assert report.flipped == ["1.1", "1.2"]
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "reviewed"}


def test_approve_specific_section_only(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc", ["1.1"])
    assert report.flipped == ["1.1"]
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_approve_skips_pending_and_reports_it(git_kb):
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    manifest.sections[0].status = "pending"
    models.save_yaml_model(manifest_path, manifest)

    report = approve_sections(git_kb["kb"], "demo-doc")
    assert report.flipped == ["1.2"]
    assert report.skipped_pending == ["1.1"]
    assert _statuses(git_kb["kb"])["1.1"] == "pending"


def test_approve_is_idempotent(git_kb):
    approve_sections(git_kb["kb"], "demo-doc")
    report = approve_sections(git_kb["kb"], "demo-doc")
    assert report.flipped == []
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "reviewed"}


def test_approve_reports_missing_section(git_kb):
    report = approve_sections(git_kb["kb"], "demo-doc", ["9.9"])
    assert report.missing == ["9.9"]
    assert report.flipped == []


def test_approve_unknown_doc_raises(git_kb):
    with pytest.raises(ValueError, match="missing-doc"):
        approve_sections(git_kb["kb"], "missing-doc")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_review.py -v`
Expected: all FAIL with `ModuleNotFoundError: No module named 'aero_kb.review'`.

- [ ] **Step 3: Implement `src/aero_kb/review.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from aero_kb import models


@dataclass
class ApproveReport:
    doc_id: str
    flipped: list[str] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


def approve_sections(
    kb_dir: Path, doc_id: str, section_ids: list[str] | None = None
) -> ApproveReport:
    """Flip status summarized → reviewed in <doc>/_manifest.yaml.

    section_ids=None targets every section of the doc. `pending` sections
    are skipped and reported (cannot approve what isn't summarized yet);
    `reviewed` sections are left untouched, so re-running is safe.
    """
    manifest_path = kb_dir / doc_id / "_manifest.yaml"
    if not manifest_path.exists():
        raise ValueError(f"doc '{doc_id}' is not in the worktree ({manifest_path})")
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    by_id = {s.id: s for s in manifest.sections}

    report = ApproveReport(doc_id=doc_id)
    if section_ids is None:
        targets = [s.id for s in manifest.sections]
    else:
        report.missing = [sid for sid in section_ids if sid not in by_id]
        targets = [sid for sid in section_ids if sid in by_id]

    for sid in targets:
        sec = by_id[sid]
        if sec.status == "summarized":
            sec.status = "reviewed"
            report.flipped.append(sid)
        elif sec.status == "pending":
            report.skipped_pending.append(sid)

    if report.flipped:
        models.save_yaml_model(manifest_path, manifest)
    return report
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_review.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/review.py tests/test_review.py
git commit -m "feat: review.py — approve_sections flips summarized to reviewed"
```

---

### Task 3: `review.py` — `--all-changed` detection (single doc and all docs)

Compute which sections changed vs a git rev (via `diff_doc`, so L1/L2/L3 all count) and approve exactly those. A doc that doesn't exist at the rev at all is brand-new: every section counts as changed.

**Files:**
- Modify: `src/aero_kb/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `diff_doc` (Task 1), `approve_sections` (Task 2), `gitio.git_root`, `gitio.read_at` (raises `gitio.GitError` on a bad rev), `models.KBIndex`.
- Produces (Task 4 relies on these):
  - `changed_section_ids(kb_dir: Path, doc_id: str, against: str) -> list[str] | None` — `None` means the doc doesn't exist at `against` (treat all sections as changed).
  - `approve_all_changed(kb_dir: Path, against: str, doc_id: str | None = None) -> list[ApproveReport]` — `doc_id=None` scans every doc in `index.yaml`; raises `ValueError` (missing index/doc) or `gitio.GitError` (bad rev).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review.py` (add imports at the top of the file: `from aero_kb import gitio` and extend the review import line):

```python
from aero_kb import gitio
from aero_kb.review import approve_all_changed, changed_section_ids
```

```python
def _add_new_doc(kb, register_in_index: bool) -> None:
    """A doc present in the worktree but absent at every committed rev."""
    doc_dir = kb / "new-doc"
    doc_dir.mkdir()
    (doc_dir / "ch1.md").write_text("## 1.1 Intro\n\nCondensed intro.\n", encoding="utf-8")
    (doc_dir / "ch1.raw.md").write_text("## 1.1 Intro\n\nRaw intro.\n", encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="new-doc",
            title="New Doc",
            sections=[
                models.SectionEntry(
                    id="1.1",
                    title="Intro",
                    summary="Intro summary.",
                    status="summarized",
                    file="ch1",
                )
            ],
        ),
    )
    if register_in_index:
        index_path = kb / "index.yaml"
        index = models.load_yaml_model(index_path, models.KBIndex)
        index.docs.append(models.IndexEntry(id="new-doc", title="New Doc"))
        models.save_yaml_model(index_path, index)


def test_changed_ids_since_rev1(git_kb):
    # only §1.1 changed between rev1 and HEAD/worktree (see git_kb fixture)
    assert changed_section_ids(git_kb["kb"], "demo-doc", git_kb["rev1"]) == ["1.1"]


def test_changed_ids_catches_l2_only_edit(git_kb):
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "airway record structure, route identifiers.",
            "airway record structure, REVISED identifiers.",
        ),
        encoding="utf-8",
    )
    assert changed_section_ids(git_kb["kb"], "demo-doc", "HEAD") == ["1.2"]


def test_changed_ids_new_doc_returns_none(git_kb):
    _add_new_doc(git_kb["kb"], register_in_index=False)
    assert changed_section_ids(git_kb["kb"], "new-doc", "HEAD") is None


def test_all_changed_flips_only_changed_sections(git_kb):
    reports = approve_all_changed(git_kb["kb"], git_kb["rev1"])
    assert [(r.doc_id, r.flipped) for r in reports] == [("demo-doc", ["1.1"])]
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_all_changed_nothing_changed_returns_empty(git_kb):
    assert approve_all_changed(git_kb["kb"], "HEAD") == []
    assert _statuses(git_kb["kb"]) == {"1.1": "summarized", "1.2": "summarized"}


def test_all_changed_new_doc_flips_all_its_summarized_sections(git_kb):
    _add_new_doc(git_kb["kb"], register_in_index=True)
    reports = approve_all_changed(git_kb["kb"], "HEAD")
    by_doc = {r.doc_id: r.flipped for r in reports}
    assert by_doc == {"new-doc": ["1.1"]}
    assert _statuses(git_kb["kb"], "new-doc") == {"1.1": "reviewed"}


def test_all_changed_single_doc_scope(git_kb):
    _add_new_doc(git_kb["kb"], register_in_index=True)
    reports = approve_all_changed(git_kb["kb"], git_kb["rev1"], doc_id="demo-doc")
    assert [r.doc_id for r in reports] == ["demo-doc"]
    # new-doc untouched despite being changed too
    assert _statuses(git_kb["kb"], "new-doc") == {"1.1": "summarized"}


def test_all_changed_bad_rev_raises(git_kb):
    with pytest.raises(gitio.GitError):
        approve_all_changed(git_kb["kb"], "deadbeef1234")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_review.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'approve_all_changed'`; Task 2 tests still PASS.

- [ ] **Step 3: Implement in `src/aero_kb/review.py`**

Add to the imports: `from aero_kb import gitio, models` and `from aero_kb.diff import diff_doc`. Append:

```python
def changed_section_ids(kb_dir: Path, doc_id: str, against: str) -> list[str] | None:
    """Ids of sections added or changed (summary/prose/content) vs `against`.

    None means the doc does not exist at `against` at all (brand-new doc) —
    the caller should treat every section as changed.
    """
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    if gitio.read_at(root, against, kb_abs / doc_id / "_manifest.yaml") is None:
        return None
    report = diff_doc(kb_dir, doc_id, against=against)
    return [c.section_id for c in report.added] + [
        c.section_id for c in report.changed
    ]


def approve_all_changed(
    kb_dir: Path, against: str, doc_id: str | None = None
) -> list[ApproveReport]:
    """Approve the sections that differ from `against` (CI mode).

    doc_id=None scans every doc in index.yaml; docs whose manifest is
    missing in the worktree are skipped. Docs with no changes produce no
    report. Raises GitError on a bad rev, ValueError on a missing doc/index.
    """
    if doc_id is not None:
        doc_ids = [doc_id]
    else:
        index_path = kb_dir / "index.yaml"
        if not index_path.exists():
            raise ValueError(f"KB index not found ({index_path})")
        index = models.load_yaml_model(index_path, models.KBIndex)
        doc_ids = [
            e.id for e in index.docs if (kb_dir / e.id / "_manifest.yaml").exists()
        ]

    reports: list[ApproveReport] = []
    for did in doc_ids:
        changed = changed_section_ids(kb_dir, did, against)
        if changed is not None and not changed:
            continue  # doc untouched since `against`
        reports.append(approve_sections(kb_dir, did, changed))
    return reports
```

Note: when `changed` is `None` (new doc), `approve_sections(kb_dir, did, None)` targets all sections — exactly the "everything is added" semantics.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_review.py tests/test_diff.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/aero_kb/review.py tests/test_review.py
git commit -m "feat: approve_all_changed — approve sections changed since a rev"
```

---

### Task 4: CLI command `kb approve`

Register the command with the four call modes and the exit-code contract from spec §3.1.

**Files:**
- Modify: `src/aero_kb/cli.py` (add the command after `diff`, before `doctor`)
- Test: `tests/test_cli_approve.py` (new)

**Interfaces:**
- Consumes: `approve_sections`, `approve_all_changed` (Tasks 2-3), `gitio.GitError`.
- Produces: `kb approve [DOC_ID] [--section ...] [--all-changed] [--against REV] [--kb-dir PATH]`.

**Flag validation rules (all exit 1 with a red message):**
- `--all-changed` and `--against` must appear together (no `HEAD` default — in CI the worktree equals HEAD, so a default would be a silent no-op).
- `--section` cannot combine with `--all-changed`.
- `DOC_ID` is required unless `--all-changed` is given.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_approve.py`:

```python
from typer.testing import CliRunner

from aero_kb import models
from aero_kb.cli import app

runner = CliRunner()


def _statuses(kb, doc_id="demo-doc"):
    manifest = models.load_yaml_model(kb / doc_id / "_manifest.yaml", models.Manifest)
    return {s.id: s.status for s in manifest.sections}


def test_approve_doc_flips_all_summarized(git_kb):
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 0
    assert "2 section(s)" in result.output
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "reviewed"}


def test_approve_single_section(git_kb):
    result = runner.invoke(
        app,
        ["approve", "demo-doc", "--section", "1.1", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_approve_all_changed_ci_mode(git_kb):
    result = runner.invoke(
        app,
        [
            "approve",
            "--all-changed",
            "--against",
            git_kb["rev1"],
            "--kb-dir",
            str(git_kb["kb"]),
        ],
    )
    assert result.exit_code == 0
    assert _statuses(git_kb["kb"]) == {"1.1": "reviewed", "1.2": "summarized"}


def test_approve_all_changed_nothing_to_do_exits_0(git_kb):
    result = runner.invoke(
        app,
        ["approve", "--all-changed", "--against", "HEAD", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 0
    assert "nothing to approve" in result.output


def test_approve_explicit_nothing_to_flip_exits_1(git_kb):
    runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1


def test_approve_missing_section_exits_1(git_kb):
    result = runner.invoke(
        app,
        ["approve", "demo-doc", "--section", "9.9", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1


def test_approve_unknown_doc_exits_1(git_kb):
    result = runner.invoke(app, ["approve", "missing-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1


def test_approve_bad_rev_exits_1(git_kb):
    result = runner.invoke(
        app,
        [
            "approve",
            "--all-changed",
            "--against",
            "deadbeef1234",
            "--kb-dir",
            str(git_kb["kb"]),
        ],
    )
    assert result.exit_code == 1


def test_all_changed_requires_against(git_kb):
    result = runner.invoke(app, ["approve", "--all-changed", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1


def test_against_requires_all_changed(git_kb):
    result = runner.invoke(
        app,
        ["approve", "demo-doc", "--against", "HEAD", "--kb-dir", str(git_kb["kb"])],
    )
    assert result.exit_code == 1


def test_section_incompatible_with_all_changed(git_kb):
    result = runner.invoke(
        app,
        [
            "approve",
            "demo-doc",
            "--section",
            "1.1",
            "--all-changed",
            "--against",
            "HEAD",
            "--kb-dir",
            str(git_kb["kb"]),
        ],
    )
    assert result.exit_code == 1


def test_doc_id_required_without_all_changed(git_kb):
    result = runner.invoke(app, ["approve", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli_approve.py -v`
Expected: all FAIL (typer reports "No such command 'approve'" → exit code 2, so even the exit-1 assertions fail).

- [ ] **Step 3: Implement the command in `src/aero_kb/cli.py`**

Insert between the `diff` and `doctor` commands:

```python
@app.command()
def approve(
    doc_id: str = typer.Argument(
        "", help="Document ID (optional with --all-changed: empty = scan all docs)"
    ),
    section: list[str] = typer.Option(
        [], "--section", help="Section ID(s) to approve, e.g. 5.3 (repeatable)"
    ),
    all_changed: bool = typer.Option(
        False,
        "--all-changed",
        help="Approve the sections added/changed vs --against (CI mode)",
    ),
    against: str = typer.Option(
        "", "--against", help="Git rev to compare with (required with --all-changed)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Mark sections as reviewed (status: summarized → reviewed)."""
    from aero_kb import gitio
    from aero_kb.review import approve_all_changed, approve_sections

    if all_changed != bool(against):
        typer.secho(
            "--all-changed and --against must be used together, "
            "e.g. `kb approve --all-changed --against HEAD^`",
            fg=typer.colors.RED,
        )
        raise typer.Exit(1)
    if all_changed and section:
        typer.secho(
            "--section cannot be combined with --all-changed", fg=typer.colors.RED
        )
        raise typer.Exit(1)
    if not all_changed and not doc_id:
        typer.secho(
            "DOC_ID is required unless --all-changed is used", fg=typer.colors.RED
        )
        raise typer.Exit(1)

    try:
        if all_changed:
            reports = approve_all_changed(kb_dir, against, doc_id=doc_id or None)
        else:
            reports = [approve_sections(kb_dir, doc_id, list(section) or None)]
    except (ValueError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)

    flipped_total = 0
    has_missing = False
    for rep in reports:
        for sid in rep.skipped_pending:
            typer.secho(
                f"[warn] {rep.doc_id} §{sid} is still pending — cannot approve",
                fg=typer.colors.YELLOW,
                err=True,
            )
        for sid in rep.missing:
            has_missing = True
            typer.secho(
                f"[error] {rep.doc_id} §{sid} not found in manifest",
                fg=typer.colors.RED,
            )
        if rep.flipped:
            flipped_total += len(rep.flipped)
            ids = ", ".join(f"§{sid}" for sid in rep.flipped)
            typer.echo(f"{rep.doc_id}: {len(rep.flipped)} section(s) → reviewed: {ids}")

    if has_missing:
        raise typer.Exit(1)
    if flipped_total == 0:
        if all_changed:
            typer.echo("kb approve: nothing to approve")
        else:
            typer.secho(
                "kb approve: no summarized section to approve", fg=typer.colors.RED
            )
            raise typer.Exit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli_approve.py tests/test_review.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite (regression check)**

Run: `python -m pytest`
Expected: all PASS (slow embedding tests are skipped by default).

- [ ] **Step 6: Commit**

```bash
git add src/aero_kb/cli.py tests/test_cli_approve.py
git commit -m "feat: kb approve command — manual and --all-changed CI modes"
```

---

### Task 5: GitHub Action `kb-review.yml`

Auto-run `kb approve --all-changed` after each push to `main` touching `.kb/**`, commit the flips back. Three loop guards: `[skip ci]` in the message, `GITHUB_TOKEN` pushes don't trigger workflows, and a job-level author filter.

**Files:**
- Create: `.github/workflows/kb-review.yml`

**Interfaces:**
- Consumes: `kb approve --all-changed --against <rev>` (Task 4) — exits 0 when there is nothing to approve, non-zero only on real errors.
- Produces: bot commits on `main` shaped `review: auto-mark reviewed @ <short-sha> [skip ci]`.

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/kb-review.yml`:

```yaml
# Auto-mark sections reviewed after a PR merges into main.
# Valid only while KB authors are the SMEs themselves ("merged = approved") —
# see docs/superpowers/specs/2026-07-11-review-automation-design.md §2.
name: kb-review
on:
  push:
    branches: [main]
    paths: [".kb/**"]

permissions:
  contents: write

jobs:
  approve:
    runs-on: ubuntu-latest
    # Loop guard (layer 3): skip pushes authored by the bot itself.
    if: github.event.head_commit.author.name != 'github-actions[bot]'
    steps:
      - uses: actions/checkout@v4
        with:
          # Full history so `--against BEFORE` is always reachable.
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .
      - name: Approve sections changed by this push
        run: |
          BEFORE="${{ github.event.before }}"
          # Zero-SHA on force-push/branch-create → fall back to the merge
          # commit's first parent; no parent at all → nothing to compare.
          if [ "$BEFORE" = "0000000000000000000000000000000000000000" ] \
              || ! git rev-parse --verify --quiet "$BEFORE^{commit}" > /dev/null; then
            if git rev-parse --verify --quiet "HEAD^" > /dev/null; then
              BEFORE="HEAD^"
            else
              echo "No previous commit to compare against — skipping."
              exit 0
            fi
          fi
          kb approve --all-changed --against "$BEFORE"
      - name: Commit status flips back to main
        run: |
          if git diff --quiet -- .kb; then
            echo "No status changes to commit."
            exit 0
          fi
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          SHORT_SHA="$(git rev-parse --short HEAD)"
          git add .kb
          # Loop guard (layer 1): [skip ci]. Layer 2: pushes made with
          # GITHUB_TOKEN do not trigger new workflow runs.
          git commit -m "review: auto-mark reviewed @ ${SHORT_SHA} [skip ci]"
          git push
```

- [ ] **Step 2: Validate the YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/kb-review.yml', encoding='utf-8')); print('yaml ok')"`
Expected: `yaml ok`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/kb-review.yml
git commit -m "ci: kb-review workflow — auto-flip reviewed after merge to main"
```

---

### Task 6: Documentation — README updates

Reflect the new command and the automation in the Vietnamese README: command dictionary (§7), end-to-end flow (§8), SME checklist (§9), known limitations (§11).

**Files:**
- Modify: `README.md`

**Interfaces:** none (docs only). README prose stays in Vietnamese (repo convention); command names/flags stay verbatim.

- [ ] **Step 1: §7 command table — add `kb approve`**

In the table at `README.md:204-213`, append one row after row 8 (`kb publish`):

```markdown
| 9 | `kb approve` | Đóng dấu thẩm định: chuyển section `summarized → reviewed`. Dạng CI: `kb approve --all-changed --against <rev>` tự tìm các section thay đổi | Bình thường CI tự chạy sau khi PR merge vào `main` (workflow `kb-review`); chạy tay khi cần duyệt ngoài luồng PR |
```

- [ ] **Step 2: §8 flow — update "Bước 5 — Merge"**

Replace lines:

```
Bước 5 — Merge
  → Sau merge, các section chuyển trạng thái: summarized → reviewed
  → Kho tri thức giờ đã có nội dung mới, sẵn sàng cho kb query
```

with:

```
Bước 5 — Merge
  → CI (workflow kb-review) tự chạy `kb approve --all-changed` và commit lại:
    các section vừa thay đổi chuyển trạng thái summarized → reviewed
  → Kho tri thức giờ đã có nội dung mới, sẵn sàng cho kb query
```

- [ ] **Step 3: §9 SME checklist — update the closing paragraph**

Replace the paragraph at `README.md:434`:

```markdown
Sau khi PR được merge, phần bạn vừa duyệt sẽ chuyển trạng thái `status: reviewed` trong manifest — đánh dấu đây là nội dung đã qua thẩm định chuyên môn, không còn là bản nháp do AI viết.
```

with:

```markdown
Sau khi PR được merge, CI (workflow `kb-review`) **tự động** chuyển các section vừa thay đổi sang `status: reviewed` trong manifest — đánh dấu đây là nội dung đã qua thẩm định chuyên môn, không còn là bản nháp do AI viết. Bạn không phải sửa tay dòng YAML nào.
```

- [ ] **Step 4: §11 limitations — add the review-automation trade-offs**

Append two bullets to the list ending at `README.md:457`:

```markdown
- **`reviewed` nghĩa là "đã được merge vào `main`"**, không phải "có người thứ hai soi lại" — chỉ hợp lệ khi người dựng KB chính là SME (bối cảnh hiện tại). Nếu sau này người dựng KB ≠ người thẩm định, phải bật lại gate (CODEOWNERS + branch protection require review) trước khi tin vào ý nghĩa của `reviewed`. Xem `docs/superpowers/specs/2026-07-11-review-automation-design.md` §2.
- **Trạng thái `reviewed` trên hub trễ một nhịp:** commit tự động của workflow `kb-review` không kích hoạt `kb-publish` (cơ chế chống lặp), nên bản snapshot trên kb-hub chỉ cập nhật `status` ở lần push nội dung kế tiếp. Không ảnh hưởng tra cứu (federation đọc tóm tắt L1, không đọc `status`).
```

- [ ] **Step 5: Verify and commit**

Skim the four edited spots for broken markdown (table pipes, code fences). Then:

```bash
git add README.md
git commit -m "docs: README — kb approve command and CI auto-review flow"
```

---

## Final Verification (after all tasks)

- [ ] Run: `python -m pytest` → all PASS.
- [ ] Run: `kb approve --help` → shows the four modes' options.
- [ ] Manual smoke test in a scratch clone (optional but recommended): commit a `.kb` edit, run `kb approve --all-changed --against HEAD^`, confirm only the edited sections flip.
