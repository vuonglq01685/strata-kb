# code-ingest review fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `kb code-ingest` emit a `-code` document that is true for the
repository it ran on — tracked files only, commands classified by token,
no table merged across migration directories, every dependency group
rendered, workspace and `build:` services found — and make it refuse to
overwrite a document it did not generate.

**Architecture:** `tree.walk_tree()` (shared by all seven extractors)
takes its file list from `git ls-files` and falls back to the existing
`os.walk`; `core.run()` gains a foreign-destination guard beside the
existing curated-`-svc` guard; each extractor fix is local to its module.
One new shared helper module, `extractors/_lines.py`, holds
shell-continuation joining for the commands and services readers.

**Tech Stack:** Python 3.12, typer CLI, pytest (real filesystem, real git,
no mocks), ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-16-code-ingest-review-fixes-design.md`

## Global Constraints

- **No new dependencies.** Standard library plus what `pyproject.toml`
  already lists.
- **Determinism.** Every new listing is sorted; nothing depends on dict
  order, filesystem order, wall-clock time, or the machine.
- **Readers degrade, never raise.** A malformed input is one warning naming
  the file; every other reader still runs.
- **Never a secret channel.** No new reader opens `.env`; `env_file` is
  recorded by *name* only. Every command/image string that reaches a
  document passes through `redact_userinfo`.
- **Section ids are a contract.** `db.<name>`, `svc.<slug>`, `cmd.<purpose>`,
  `dep.<ecosystem>`, `struct.tree` keep their shapes; no qualified ids.
- **`--db` keeps resolving against `--repo-root`.** Only `--kb-dir` moves to
  the current directory.
- **Target release 0.23.0.** `pyproject.toml:3` is `0.22.0` today; Task 12
  bumps it and writes the changelog.
- **Test discipline.** Tests use `tmp_path`, the `run_git` fixture from
  `tests/conftest.py` (`run_git(root, *args) -> str`) for real git, and the
  `build_code_repo` fixture from `tests/fixtures_coderepo.py`. Existing
  helpers in `tests/test_codeingest_extractors.py`: `_opts(root)`,
  `_by_id(result)`, fixture `repo`; module aliases `tree_ext`, `deps_ext`,
  `svc_ext`, `cmd_ext`, `schema_ext` are imported near each class.
- **Commit trailer.** Every commit ends with
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- **Run the full code-ingest suite after each task:**
  `pytest tests/test_codeingest_core.py tests/test_codeingest_extractors.py tests/test_codeingest_scaffold.py tests/test_cli_codeingest.py -q`
  (290 passed at the start; the number only goes up).

---

### Task 1: `walk_tree()` from `git ls-files`, honest wording (G-3a)

**Files:**
- Modify: `src/center_kb/codeingest/extractors/tree.py` (module docstring,
  imports, `walk_tree`, `TreeExtractor.extract`)
- Test: `tests/test_codeingest_extractors.py` (`TestTreeExtractor`)

**Interfaces:**
- Consumes: `center_kb.codeingest.core._git(root, *args) -> CompletedProcess[str]`.
- Produces: `tree.tracked_files(root: Path) -> list[str] | None` (posix
  paths relative to `root`, or `None` when git is unusable or lists
  nothing); `walk_tree(root, kb_dir=None)` keeps its signature and return
  shape `list[tuple[int, Path, list[str]]]`.

- [ ] **Step 1: Write the failing tests**

Append to `class TestTreeExtractor` in `tests/test_codeingest_extractors.py`
(after `test_prunes_relative_kb_dir`):

```python
    def test_git_ignored_directories_are_absent_when_root_is_a_repo(self, repo, run_git):
        # Reviewer G-3: an unfiltered os.walk shipped .venv-artifact/,
        # .worktrees/ and a previous run's own output as "tracked files".
        (repo / ".gitignore").write_text(".venv-x/\nkb1/\n", encoding="utf-8")
        (repo / ".venv-x" / "lib").mkdir(parents=True)
        (repo / ".venv-x" / "lib" / "site.py").write_text("", encoding="utf-8")
        (repo / "kb1" / "demo-code").mkdir(parents=True)
        (repo / "kb1" / "demo-code" / "structure.md").write_text("x", encoding="utf-8")
        run_git(repo, "init")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-m", "c1")
        result = tree_ext.TreeExtractor().extract(repo, _opts(repo))
        s = _by_id(result)["struct.tree"]
        body = s.l2_md + s.l3_md
        assert ".venv-x" not in body
        assert "kb1" not in body
        assert "src/airspace" in body
        assert "tracked files" in s.summary
        assert result.warnings == []

    def test_untracked_file_in_a_repo_is_not_listed(self, repo, run_git):
        run_git(repo, "init")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-m", "c1")
        (repo / "scratch.txt").write_text("x", encoding="utf-8")
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        assert "scratch.txt" not in s.l3_md

    def test_non_git_root_is_unfiltered_and_says_so(self, repo):
        result = tree_ext.TreeExtractor().extract(repo, _opts(repo))
        s = _by_id(result)["struct.tree"]
        assert "tracked" not in s.summary
        assert "not a git repository" in s.summary
        assert any("not a git repository" in w for w in result.warnings)
        assert "src/airspace" in s.l3_md

    def test_repo_with_nothing_tracked_falls_back_to_the_unfiltered_walk(self, repo, run_git):
        run_git(repo, "init")   # no add, no commit: `git ls-files` lists nothing
        result = tree_ext.TreeExtractor().extract(repo, _opts(repo))
        s = _by_id(result)["struct.tree"]
        assert "src/airspace" in s.l3_md
        assert any("not a git repository" in w for w in result.warnings)

    def test_tracked_walk_still_prunes_ignored_dirs_and_the_kb_dir(self, repo, run_git):
        (repo / "dist").mkdir()
        (repo / "dist" / "bundle.js").write_text("", encoding="utf-8")
        (repo / ".kb" / "demo-code").mkdir(parents=True)
        (repo / ".kb" / "demo-code" / "structure.md").write_text("x", encoding="utf-8")
        run_git(repo, "init")
        run_git(repo, "add", "-A")
        run_git(repo, "commit", "-m", "c1")
        entries = tree_ext.walk_tree(repo, repo / ".kb")
        dirs = {rel.as_posix() for _d, rel, _f in entries}
        assert "dist" not in dirs
        assert ".kb" not in dirs and ".kb/demo-code" not in dirs
        assert "src/airspace" in dirs
        # preorder, alphabetical, root first at depth 0; every ancestor of a
        # kept file is present, pruned directories are not
        assert [e[1].as_posix() for e in entries] == [
            ".", ".github", ".github/workflows", "db", "db/migration",
            "src", "src/airspace", "web",
        ]
        assert entries[0][0] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_extractors.py::TestTreeExtractor -q`
Expected: the five new tests FAIL (`.venv-x` listed, `tracked_files` missing, no warning).

- [ ] **Step 3: Implement**

In `src/center_kb/codeingest/extractors/tree.py`:

Replace the module docstring's last sentence (`... a
single deterministic `os.walk` over the tree with `IGNORED_DIRS` (and the
caller's `kb_dir`) pruned in place.`) with:

```
`struct.tree` in the `structure` group, built by `walk_tree()` below — the
files `git ls-files` reports under the root (so a git-ignored virtualenv,
worktree or previous run's output never appears, and two checkouts of the
same commit list the same tree), with `IGNORED_DIRS` (and the caller's
`kb_dir`) pruned on top. A root that is not a git repository, or has no
tracked file, falls back to one deterministic `os.walk` with the same
pruning, and the section says so.
```

Change the import line to:

```python
from center_kb.codeingest.core import CodeIngestOptions, CodeSection, ExtractResult, _git
```

Add after `relposix`:

```python
def tracked_files(root: Path) -> list[str] | None:
    """`git ls-files` under `root`, as `/`-separated paths relative to
    `root` — or `None` when that listing cannot stand in for the tree:
    git failed (not a repository, git not installed) or listed nothing
    (a repository with no tracked file under `root`: a brand-new
    checkout, or the wrong root — an empty tree would be a lie). `-z`
    keeps non-ASCII names unquoted."""
    proc = _git(root, "ls-files", "-z")
    if proc.returncode != 0:
        return None
    paths = [p for p in proc.stdout.split("\0") if p]
    return paths or None


def _entries_from_tracked(
    resolved_root: Path, tracked: list[str], resolved_kb_dir: Path | None
) -> list[tuple[int, Path, list[str]]]:
    """The same `(depth, rel_dir, sorted_filenames)` preorder `walk_tree`'s
    os.walk branch produces, rebuilt from a tracked-file list. Git does
    not track empty directories, so none appear; every ancestor of a
    kept file does. A file is dropped when any directory component is
    in `IGNORED_DIRS` or its directory is (or lies under) `kb_dir` —
    exactly the two prunes the os.walk branch applies."""
    files_by_dir: dict[tuple[str, ...], list[str]] = {(): []}
    for posix in tracked:
        parts = tuple(posix.split("/"))
        dir_parts, name = parts[:-1], parts[-1]
        if any(part in IGNORED_DIRS for part in dir_parts):
            continue
        if resolved_kb_dir is not None:
            candidate = resolved_root.joinpath(*dir_parts)
            if candidate == resolved_kb_dir or resolved_kb_dir in candidate.parents:
                continue
        for i in range(1, len(dir_parts) + 1):
            files_by_dir.setdefault(dir_parts[:i], [])
        files_by_dir[dir_parts].append(name)
    entries: list[tuple[int, Path, list[str]]] = []
    for dir_parts in sorted(files_by_dir):
        rel = Path(*dir_parts) if dir_parts else Path(".")
        entries.append((len(dir_parts), rel, sorted(files_by_dir[dir_parts])))
    return entries
```

In `walk_tree`, after the `resolved_kb_dir` block and before
`entries: list[...] = []`, insert:

```python
    tracked = tracked_files(root)
    if tracked is not None:
        return _entries_from_tracked(root.resolve(), tracked, resolved_kb_dir)
```

and add to its docstring, before `Returns`:

```
    The file list comes from `git ls-files` when `root` is inside a git
    repository with at least one tracked file (see `tracked_files`);
    otherwise from `os.walk`. Both branches apply the same prunes and
    return the same shape.
```

In `TreeExtractor.extract`, replace the `summary = (...)` statement and the
final `return` with:

```python
        warnings: list[str] = []
        if tracked_files(root) is not None:
            files_phrase = f"{n_files} tracked files"
        else:
            files_phrase = f"{n_files} files (not a git repository — listing unfiltered)"
            warnings.append(
                f"{root} is not a git repository — the tree is an unfiltered "
                "directory walk, not the tracked files"
            )

        summary = (
            f"Repository layout: {n_dirs} directories, {files_phrase}, "
            f"entry points: {', '.join(entry_points) or 'none detected'}."
        )

        section = CodeSection(
            id="struct.tree",
            title="Repository tree",
            summary=summary,
            group="structure",
            l2_md=l2_md,
            l3_md=l3_md,
        )
        return ExtractResult(sections=[section], warnings=warnings)
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_extractors.py::TestTreeExtractor -q`
Expected: all PASS.

Run the full code-ingest suite (Global Constraints). Expected: all PASS —
the shared fixtures are not git repositories, so every other extractor
takes the unchanged `os.walk` branch.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/extractors/tree.py tests/test_codeingest_extractors.py
git commit -m "fix(code-ingest): struct.tree lists git-tracked files, not an unfiltered walk (G-3)"
```

---

### Task 2: L3 line cap and console scripts (G-3b, G-16)

**Files:**
- Modify: `src/center_kb/codeingest/extractors/tree.py` (`_L3_DEPTH`
  block, `_detect_entry_points`, `_render_l3`, `TreeExtractor.extract`)
- Test: `tests/test_codeingest_extractors.py` (`TestTreeExtractor`)

**Interfaces:**
- Produces: `_detect_entry_points(root, entries) -> tuple[list[str], list[str]]`
  (file entry points, `"<name> = <target>"` console-script lines);
  `_render_l3(root, entries) -> tuple[str, int]` (body, omitted line count);
  constant `_L3_MAX_LINES = 600`.

- [ ] **Step 1: Write the failing tests**

Append to `class TestTreeExtractor`:

```python
    def test_l3_is_capped_by_line_count_with_a_marker(self, tmp_path):
        # Reviewer G-3: 6 000 files in one unignored directory produced a
        # 25 k-token section; depth alone is not a cap.
        root = tmp_path / "wide"
        root.mkdir()
        for i in range(700):
            (root / f"f{i:04d}.txt").write_text("", encoding="utf-8")
        s = _by_id(tree_ext.TreeExtractor().extract(root, _opts(root)))["struct.tree"]
        lines = s.l3_md.splitlines()
        assert len(lines) <= tree_ext._L3_MAX_LINES + 4   # fences + two markers
        assert "# … 100 more entries omitted (capped at 600 lines)" in s.l3_md
        assert "700 files" in s.summary   # the summary still counts the whole tree

    def test_small_tree_has_no_omitted_marker(self, repo):
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        assert "more entries omitted" not in s.l3_md

    def test_console_scripts_are_listed_apart_from_file_entry_points(self, repo):
        # Reviewer G-16: `[project.scripts]` keys were mixed into a list of
        # file paths, so a bare `kb` sat next to `src/center_kb/web/app.py`.
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "airspace"\nversion = "1.0.0"\n'
            'dependencies = ["fastapi>=0.110"]\n'
            '[project.scripts]\nairspace = "airspace.cli:app"\n',
            encoding="utf-8",
        )
        (repo / "src" / "airspace" / "main.py").write_text("", encoding="utf-8")
        s = _by_id(tree_ext.TreeExtractor().extract(repo, _opts(repo)))["struct.tree"]
        assert "Detected entry points:\n\n- src/airspace/main.py\n" in s.l2_md
        assert (
            "Console scripts (pyproject [project.scripts]):\n\n- airspace = airspace.cli:app\n"
            in s.l2_md
        )
        assert "entry points: src/airspace/main.py; console scripts: airspace." in s.summary
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_extractors.py::TestTreeExtractor -q`
Expected: the three new tests FAIL.

- [ ] **Step 3: Implement**

In `tree.py`, after `_L3_DEPTH = 4  # L3 full-tree listing depth` add:

```python
# Hard line cap on the L3 listing (≈ 5 000 tokens, C3's ceiling). Depth
# alone does not bound a wide directory — reviewer G grew a 27-file repo's
# L3 to 25 k tokens with one unignored vendor directory.
_L3_MAX_LINES = 600
```

Replace `_detect_entry_points` with:

```python
def _detect_entry_points(
    root: Path, entries: list[tuple[int, Path, list[str]]]
) -> tuple[list[str], list[str]]:
    """(file entry points, console scripts). Files are repo-relative paths
    whose basename is in `_ENTRY_POINT_NAMES`; console scripts are the
    `[project.scripts]` entries rendered `name = module:attr` — kept
    apart because a script *name* is not a path."""
    found: set[str] = set()
    for _depth, rel, filenames in entries:
        for name in filenames:
            if name in _ENTRY_POINT_NAMES:
                found.add(relposix(root, root / rel / name))

    console: list[str] = []
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError):
            data = {}
        project = data.get("project", {}) if isinstance(data, dict) else {}
        scripts = project.get("scripts", {}) if isinstance(project, dict) else {}
        if isinstance(scripts, dict):
            console = [f"{k} = {scripts[k]}" for k in sorted(scripts, key=str)]

    return sorted(found), console
```

Replace `_render_l3` with:

```python
def _render_l3(root: Path, entries: list[tuple[int, Path, list[str]]]) -> tuple[str, int]:
    """(rendered listing capped at `_L3_MAX_LINES`, number of lines cut)."""
    lines: list[str] = []
    for depth, rel, filenames in entries:
        if depth > _L3_DEPTH:
            continue
        if rel != Path("."):
            lines.append(f"{'  ' * (depth - 1)}- {relposix(root, root / rel)}/")
        file_indent = "  " * depth
        lines.extend(f"{file_indent}- {name}" for name in filenames)
    omitted = max(0, len(lines) - _L3_MAX_LINES)
    return "\n".join(lines[:_L3_MAX_LINES]), omitted
```

In `TreeExtractor.extract`, replace the line
`entry_points = _detect_entry_points(root, entries)` with
`entry_points, console_scripts = _detect_entry_points(root, entries)`,
replace the `l2_md = (...)` and `l3_md = ...` statements with:

```python
        l2_md = (
            "Directory layout (depth 2):\n\n"
            f"{_render_l2(root, entries)}\n\n"
            "Detected entry points:\n\n"
            + ("\n".join(f"- {ep}" for ep in entry_points) or "- none detected")
            + "\n\nConsole scripts (pyproject [project.scripts]):\n\n"
            + ("\n".join(f"- {cs}" for cs in console_scripts) or "- none detected")
            + "\n"
        )
        # Two markers keep the fenced block honest about its own caps —
        # depth 4 and _L3_MAX_LINES — so the summary's whole-tree counts
        # never silently contradict a truncated listing. Both live inside
        # the fence so they can never register as a pipe table.
        body, omitted = _render_l3(root, entries)
        tail = (
            f"\n# … {omitted} more entries omitted (capped at {_L3_MAX_LINES} lines)"
            if omitted else ""
        )
        l3_md = "```\n# tree, capped at depth 4\n" + body + tail + "\n```\n"
```

and in the `summary = (...)` statement change the last f-string to:

```python
            f"entry points: {', '.join(entry_points) or 'none detected'}; "
            f"console scripts: "
            f"{', '.join(cs.split(' = ', 1)[0] for cs in console_scripts) or 'none detected'}."
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_extractors.py::TestTreeExtractor -q` then the full code-ingest suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/extractors/tree.py tests/test_codeingest_extractors.py
git commit -m "fix(code-ingest): cap struct.tree L3 at 600 lines, list console scripts apart from files (G-3, G-16)"
```

---

### Task 3: Refuse a destination `kb code-ingest` did not generate (G-1)

**Files:**
- Modify: `src/center_kb/codeingest/core.py` (guard in `run()` right after
  the `_is_curated_destination` check; new helper next to it)
- Test: `tests/test_codeingest_core.py`, `tests/test_cli_codeingest.py`

**Interfaces:**
- Produces: `core._GENERATED_PREFIXES: tuple[str, ...]`;
  `core._foreign_destination_reason(doc_dir: Path, manifest: models.Manifest | None) -> str | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_codeingest_core.py`:

```python
# ---------------------------------------------------------------------------
# Reviewer G-1: a hand-curated document at <repo>-code was deleted without
# a warning. The destination guard now also refuses any document this
# command did not itself generate — no override flag.
# ---------------------------------------------------------------------------


def _write_human_doc(doc_dir: Path, title: str = "Poly hand-written domain doc") -> None:
    doc_dir.mkdir(parents=True)
    (doc_dir / "body.md").write_text("## ch1 Chapter one\n\nHuman prose.\n", encoding="utf-8")
    (doc_dir / "body.raw.md").write_text("## ch1 Chapter one\n\nRaw prose.\n", encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="demo-code", title=title,
            sections=[models.SectionEntry(
                id="ch1", title="Chapter one", summary="A curated chapter.",
                status="reviewed", file="body",
            )],
        ),
    )


def test_human_document_at_the_code_slot_is_refused_and_left_intact(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    doc_dir = tmp_path / ".kb" / "demo-code"
    _write_human_doc(doc_dir)
    before = {p.name: p.read_bytes() for p in doc_dir.iterdir()}

    with pytest.raises(core.CodeIngestError) as excinfo:
        core.run(_opts(tmp_path))

    assert "did not generate" in str(excinfo.value)
    assert "Poly hand-written domain doc" in str(excinfo.value)
    assert {p.name: p.read_bytes() for p in doc_dir.iterdir()} == before
    assert not (tmp_path / ".kb" / "index.yaml").exists()


def test_document_with_a_foreign_section_id_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    doc_dir = tmp_path / ".kb" / "demo-code"
    _write_human_doc(doc_dir, title="demo — code knowledge")   # title passes, id does not
    with pytest.raises(core.CodeIngestError) as excinfo:
        core.run(_opts(tmp_path))
    assert "ch1" in str(excinfo.value)


def test_markdown_without_a_manifest_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    doc_dir = tmp_path / ".kb" / "demo-code"
    doc_dir.mkdir(parents=True)
    (doc_dir / "notes.md").write_text("mine\n", encoding="utf-8")
    with pytest.raises(core.CodeIngestError) as excinfo:
        core.run(_opts(tmp_path))
    assert "missing or unreadable" in str(excinfo.value)
    assert (doc_dir / "notes.md").read_text(encoding="utf-8") == "mine\n"


def test_previous_run_with_rewritten_statuses_still_reingests(tmp_path, monkeypatch):
    # `kb summarize --redo` / `kb approve` rewrite statuses on a -code
    # manifest; neither touches the title or the ids, so a re-run proceeds.
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    manifest_path = tmp_path / ".kb" / "demo-code" / "_manifest.yaml"
    m = models.load_yaml_model(manifest_path, models.Manifest)
    for s in m.sections:
        s.status = "pending"
    models.save_yaml_model(manifest_path, m)
    report = core.run(_opts(tmp_path))
    assert report.files_written


def test_empty_destination_directory_is_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    (tmp_path / ".kb" / "demo-code").mkdir(parents=True)
    assert core.run(_opts(tmp_path)).files_written
```

In `tests/test_cli_codeingest.py`, replace
`test_cli_degrades_on_wrong_shaped_existing_code_manifest` with:

```python
def test_cli_refuses_a_wrong_shaped_existing_code_manifest_without_a_traceback(tmp_path):
    # Review round 2 wanted no traceback here; reviewer G-1 wants no
    # overwrite either: an unreadable manifest at the -code slot means
    # nobody can tell whose document this is, so it is refused, intact.
    root = build_code_repo(tmp_path)
    _init_config(root)
    first = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert first.exit_code == 0, first.output
    manifest = root / ".kb" / "demo-code" / "_manifest.yaml"
    manifest.write_text("- a\n- b\n", encoding="utf-8")
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", str(root / ".kb")])
    assert result.exit_code == 1
    assert "could not read" in result.output          # the guarded-load warning
    assert "did not generate" in result.output
    assert "Traceback" not in result.output
    assert manifest.read_text(encoding="utf-8") == "- a\n- b\n"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_core.py tests/test_cli_codeingest.py -q -k "refus or foreign or without_a_manifest or rewritten_statuses or empty_destination"`
Expected: FAIL — `run()` currently deletes the files and exits 0.

- [ ] **Step 3: Implement**

In `core.py`, directly after the `if _is_curated_destination(...): raise ...`
block in `run()`, add:

```python
    # Reviewer G-1: the curated guard above knows what a -svc document
    # looks like; it cannot recognise *any other* human document that
    # happens to sit at this run's destination — which the stale-.md prune
    # below would then delete. The property that matters is "did this
    # command write what is here?", answered from the manifest this
    # command itself writes. Checked before anything is written.
    foreign_reason = _foreign_destination_reason(doc_dir, existing_code_manifest)
    if foreign_reason is not None:
        raise CodeIngestError(
            f"--doc-id {opts.doc_id!r} targets {doc_dir}, which holds a "
            f"document kb code-ingest did not generate ({foreign_reason}); "
            "choose a different --doc-id or --repo-id, or move that "
            "document away — nothing was written",
            report=report,
        )
```

Add next to `_is_curated_destination` (before it):

```python
# The section-id prefixes the seven extractors produce (README §7.12's
# section-id contract). A -code manifest holding any other id was not
# written by `run()`.
_GENERATED_PREFIXES = ("struct.", "cmd.", "dep.", "db.", "svc.", "int.", "api.")


def _foreign_destination_reason(
    doc_dir: Path, manifest: models.Manifest | None
) -> str | None:
    """A one-line reason when `doc_dir` holds content this command did not
    generate, else None. "Content" is any `*.md` or a `_manifest.yaml`;
    an absent or empty directory is never foreign. With content present,
    the manifest must be readable, carry `run()`'s own title suffix, and
    list only generated section ids — `kb summarize --redo` and `kb
    approve` rewrite statuses, never the title or the ids, so a previous
    run always passes."""
    has_content = (doc_dir / "_manifest.yaml").is_file() or any(doc_dir.glob("*.md"))
    if not has_content:
        return None
    if manifest is None:
        return "its _manifest.yaml is missing or unreadable"
    if not manifest.title.endswith("— code knowledge"):
        return f"title: {manifest.title!r}"
    foreign_ids = sorted(
        s.id for s in manifest.sections if not s.id.startswith(_GENERATED_PREFIXES)
    )
    if foreign_ids:
        return f"section(s) {', '.join(foreign_ids)} were not produced by any extractor"
    return None
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_core.py tests/test_cli_codeingest.py -q` then the full code-ingest suite. Expected: PASS. If an existing test's stub sections use an id outside the seven prefixes across two `run()` calls, change that stub id to a generated prefix (e.g. `svc.x`) — the prefix set is the contract, not the test.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/core.py tests/test_codeingest_core.py tests/test_cli_codeingest.py
git commit -m "fix(code-ingest): refuse to overwrite a document this command did not generate (G-1)"
```

---

### Task 4: `--kb-dir` resolves against the cwd; `source_sha256` empty (G-11, G-15)

**Files:**
- Modify: `src/center_kb/codeingest/core.py` (`CodeIngestOptions.__post_init__`,
  the two `source_sha256=full_commit` lines in `run()` and `scaffold_svc()`)
- Modify: `src/center_kb/cli.py` (`code_ingest`: R23 block, help text)
- Test: `tests/test_cli_codeingest.py`, `tests/test_codeingest_scaffold.py`,
  `tests/test_codeingest_core.py`, `tests/test_codeingest_extractors.py`

- [ ] **Step 1: Update the tests to the new contract**

In `tests/test_cli_codeingest.py` replace
`test_kb_dir_relative_path_resolves_against_repo_root_not_cwd` with:

```python
def test_kb_dir_relative_path_resolves_against_cwd_like_every_other_kb_command(tmp_path, monkeypatch):
    # Reviewer G-11: resolving against --repo-root was undocumented and
    # created directories inside a repo the reviewer had been told not to touch.
    root = tmp_path / "proj"
    build_code_repo(root)
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    result = runner.invoke(app, ["code-ingest", "--repo-root", str(root),
                                "--kb-dir", "out/.kb", "--repo-id", "demo"])
    assert result.exit_code == 0, result.output
    assert (other_cwd / "out" / ".kb" / "demo-code" / "_manifest.yaml").is_file()
    assert not (root / "out").exists()
```

In `tests/test_codeingest_scaffold.py` replace
`test_options_post_init_resolves_relative_kb_dir_against_repo_root` with:

```python
def test_options_post_init_resolves_relative_kb_dir_against_cwd(tmp_path, monkeypatch):
    root = build_code_repo(tmp_path)
    other_cwd = tmp_path / "elsewhere"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    opts = core.CodeIngestOptions(
        repo_root=root, kb_dir=Path("out/.kb"), doc_id="demo-code", repo_id="demo",
    )
    assert opts.kb_dir == (other_cwd / "out" / ".kb").resolve()

    core.run(opts)
    assert (other_cwd / "out" / ".kb" / "demo-code" / "_manifest.yaml").is_file()
    assert not (root / "out").exists()
```

In `tests/test_codeingest_extractors.py::TestTreeExtractor::test_prunes_relative_kb_dir`
add `monkeypatch` to the signature and insert `monkeypatch.chdir(repo)` as
the first line of the body (the relative `docs/kb` now means cwd-relative,
and only a KB directory inside the repo is pruned).

In `tests/test_codeingest_core.py::test_manifest_records_commit_and_commit_date_not_wall_clock`
replace `assert m.source_sha256 == head` with:

```python
    assert m.source_sha256 == ""   # G-15: the field is a content hash, not a git SHA
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli_codeingest.py::test_kb_dir_relative_path_resolves_against_cwd_like_every_other_kb_command tests/test_codeingest_scaffold.py::test_options_post_init_resolves_relative_kb_dir_against_cwd tests/test_codeingest_core.py::test_manifest_records_commit_and_commit_date_not_wall_clock -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `core.py`, `CodeIngestOptions.__post_init__`: replace the comment block
and the `kb = ...` line with:

```python
        # A relative `kb_dir` is relative to the process CWD — the same
        # rule every other `kb` command's --kb-dir follows (reviewer G-11
        # replaced Ruling R23's repo-root resolution, which no help text
        # documented and which wrote inside a repo the operator had not
        # pointed at). `tree.walk_tree()` prunes an absolute kb_dir only
        # when it lies inside repo_root, so a KB outside the repo is
        # simply not pruned — correct. `db_paths` keep resolving against
        # `repo_root`: a --db names a file inside the repository.
        root = self.repo_root.resolve()
        kb = self.kb_dir if self.kb_dir.is_absolute() else Path.cwd() / self.kb_dir
```

In `run()` and `scaffold_svc()` change `source_sha256=full_commit,` to
`source_sha256="",` (both occurrences) and add above the first one:

```python
            # G-15: `source_sha256` is the PDF ingest's content hash; a git
            # SHA-1 does not belong in it. `revision` carries the commit.
```

In `cli.py`, `code_ingest`: delete the `# Ruling R23: ...` comment block and
the `resolved_kb_dir = (...)` statement; replace with:

```python
    resolved_root = repo_root.resolve()
    # Relative --kb-dir is cwd-relative, like every other kb command (G-11).
    resolved_kb_dir = kb_dir.resolve()
```

and change the option help to
`help="KB directory (default: .kb, relative to the current directory like every other kb command)"`.

- [ ] **Step 4: Run the tests**

Run the full code-ingest suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/core.py src/center_kb/cli.py tests/test_cli_codeingest.py tests/test_codeingest_scaffold.py tests/test_codeingest_core.py tests/test_codeingest_extractors.py
git commit -m "fix(code-ingest): --kb-dir is cwd-relative; source_sha256 no longer holds a git SHA (G-11, G-15)"
```

---

### Task 5: Token classifier and `\`-continuation joining (G-2a)

**Files:**
- Create: `src/center_kb/codeingest/extractors/_lines.py`
- Modify: `src/center_kb/codeingest/extractors/commands.py`
  (`PURPOSE_KEYWORDS`, `_classify`, `_read_ci`, module docstring)
- Test: `tests/test_codeingest_extractors.py` (`TestCommandsExtractor`),
  `tests/test_codeingest_lines.py` (new)

**Interfaces:**
- Produces: `_lines.join_continuations(text: str) -> list[str]`;
  `commands._classify(text: str) -> str | None` (token match).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_codeingest_lines.py`:

```python
from center_kb.codeingest.extractors._lines import join_continuations


def test_backslash_continuations_are_joined_with_a_space():
    text = "docker build \\\n    --tag x:latest \\\n    .\npytest -q\n"
    assert join_continuations(text) == ["docker build --tag x:latest .", "pytest -q"]


def test_blank_and_comment_lines_are_dropped():
    assert join_continuations("# setup\n\n  # more\nruff check .\n") == ["ruff check ."]


def test_trailing_continuation_at_end_of_text_is_kept():
    assert join_continuations("echo a \\") == ["echo a"]
```

Append to `class TestCommandsExtractor` in `tests/test_codeingest_extractors.py`:

```python
    @pytest.mark.parametrize(
        ("line", "purpose"),
        [
            # Reviewer G-2's seven lines: substring matching classified all
            # but the last two wrongly (`/dev/null` ⊃ dev, `:latest` ⊃ test).
            ('code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8321/api/docs)', None),
            ('pip install "ruff>=0.15,<0.16"', None),
            ("-e CENTER_KB_HTTP_TOKEN=smoke-test-token", None),
            ("--tag ghcr.io/vuonglq01685/center-kb:latest", None),
            ('echo "starting deployment"', None),
            ("aws s3 cp devops.txt s3://bucket", None),
            ("bash scripts/gate.sh", None),
            ("ruff check .", "lint"),
            ("python -m build", "build"),
            ("npm run dev", "run"),
            ("go test ./...", "test"),
            ("tox -e lint", "lint"),
            ('"$PY" -m pytest -q', "test"),
            ("vite (npm run start)", "run"),
            ("cd web && npm run build", "build"),
            ("pytest -q --cov=airspace", "test"),
        ],
    )
    def test_classify_matches_whole_tokens_only(self, line, purpose):
        assert cmd_ext._classify(line) == purpose

    def test_install_step_before_the_real_command_does_not_win(self, tmp_path):
        # aero's own _gate.yml: `pip install "ruff..."` precedes `ruff check .`.
        root = tmp_path / "gate"
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "_gate.yml").write_text(
            "on: [push]\njobs:\n  t0-lint:\n    runs-on: ubuntu-latest\n    steps:\n"
            '      - run: pip install "ruff>=0.15,<0.16"\n'
            "      - run: ruff check .\n",
            encoding="utf-8",
        )
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert sections["cmd.lint"].l2_md.splitlines()[0] == "**Primary:** `ruff check .`"
        assert "cmd.build" not in sections

    def test_continued_run_block_is_one_command_not_fragments(self, tmp_path):
        root = tmp_path / "cont"
        wf = root / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "ci.yml").write_text(
            "on: [push]\njobs:\n  img:\n    runs-on: ubuntu-latest\n    steps:\n"
            "      - run: |\n"
            "          docker build \\\n"
            "            --tag ghcr.io/x/y:latest \\\n"
            "            .\n",
            encoding="utf-8",
        )
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert sections["cmd.build"].l2_md.splitlines()[0] == (
            "**Primary:** `docker build --tag ghcr.io/x/y:latest .`"
        )
        assert "cmd.test" not in sections
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_lines.py tests/test_codeingest_extractors.py::TestCommandsExtractor -q`
Expected: `_lines` import error; the parametrized rows for `/dev/null`, `pip install`, `smoke-test-token`, `:latest`, `deployment`, `devops.txt` FAIL; the two workflow tests FAIL.

- [ ] **Step 3: Implement**

Create `src/center_kb/codeingest/extractors/_lines.py`:

```python
"""Shell-text line helper shared by the commands and services readers.

A CI `run: |` block, a tox `commands =` value, a shell script and a
Dockerfile all use `\\` line continuation; splitting such text per line
shipped fragments like `--tag ghcr.io/x:latest \\` as commands (reviewer
G-2). Joining lives here, once, rather than per reader.
"""
from __future__ import annotations


def join_continuations(text: str) -> list[str]:
    """Logical lines of `text`: a line ending in `\\` is joined to the
    next with one space; blank lines and lines whose first non-blank
    character is `#` are dropped. Every line is stripped."""
    joined: list[str] = []
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if pending:
            line = f"{pending} {line}".strip()
            pending = ""
        if line.endswith("\\"):
            pending = line[:-1].rstrip()
            continue
        if not line or line.startswith("#"):
            continue
        joined.append(line)
    if pending:
        joined.append(pending)
    return joined
```

In `commands.py`:

Add the import `from center_kb.codeingest.extractors._lines import join_continuations`
next to the other `center_kb.codeingest.extractors` imports.

In `PURPOSE_KEYWORDS["build"]` delete `"pip install"` (an install is not a
build; with token matching it was the only reason the install step of a CI
job outranked the real command).

Replace `_classify` with:

```python
_TOKEN_STRIP = "\"'()"


def _classify(text: str) -> str | None:
    """First purpose in `PURPOSE_KEYWORDS`' own declaration order (`test`
    before `lint` before `build` before `run`) whose keyword appears in
    `text` as whole tokens: a one-word keyword must equal a whitespace-
    delimited token (outer quotes and parens stripped), a multi-word
    keyword must equal a run of consecutive tokens. A substring match
    classified `/dev/null` as `run` and `:latest` as `test` (reviewer
    G-2); a token match cannot."""
    tokens = [tok.strip(_TOKEN_STRIP) for tok in text.lower().split()]
    for purpose, keywords in PURPOSE_KEYWORDS.items():
        for keyword in keywords:
            kw_tokens = keyword.split()
            width = len(kw_tokens)
            if any(
                tokens[i:i + width] == kw_tokens
                for i in range(len(tokens) - width + 1)
            ):
                return purpose
    return None
```

In `_read_ci`, replace `lines = run.splitlines()` with
`lines = join_continuations(run)` and the inner loop

```python
                    for line in lines:
                        stripped = line.strip()
                        if not stripped:
                            continue
                        purpose = _classify(stripped)
                        if purpose is not None:
                            candidates.append((purpose, stripped, source))
```

with

```python
                    for line in lines:
                        purpose = _classify(line)
                        if purpose is not None:
                            candidates.append((purpose, line, source))
```

Update the module docstring's "Classification (`_classify()`) is a single
keyword lookup ..." sentence to say "a whole-token match (never a
substring: `/dev/null` is not `dev`) against `PURPOSE_KEYWORDS`, checked in
the dict's own declaration order", and the `_read_ci` docstring's "A
multi-line `run:` block is split on newlines into one candidate per line"
to "A multi-line `run:` block is split into logical lines by
`join_continuations` (a `\` continuation is one command) — one candidate
per line".

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_lines.py tests/test_codeingest_extractors.py::TestCommandsExtractor -q` then the full code-ingest suite. Expected: PASS. (`build_code_repo`'s CI has `pip install -e .`, `pytest -q --cov=airspace`, `ruff check src`; `cmd.build` now comes from `vite build (npm run build)` — still present, still `build`.)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/extractors/_lines.py src/center_kb/codeingest/extractors/commands.py tests/test_codeingest_lines.py tests/test_codeingest_extractors.py
git commit -m "fix(code-ingest): classify commands by whole token and join shell continuations (G-2)"
```

---

### Task 6: tox `commands =` and a shell-script reader (G-2b)

**Files:**
- Modify: `src/center_kb/codeingest/extractors/commands.py` (`_read_python`,
  new `_tox_commands`, new `_read_shell`, `CommandsExtractor.detect/extract`)
- Test: `tests/test_codeingest_extractors.py` (`TestCommandsExtractor`)

**Interfaces:**
- Produces: `_tox_commands(text) -> list[tuple[str, str]]` (`(invocation, logical line)`);
  `_read_shell(root, opts) -> tuple[list[Candidate], list[str]]`;
  constant `_SHELL_DIRS = (Path("."), Path("scripts"))`.

- [ ] **Step 1: Write the failing tests**

Append to `class TestCommandsExtractor`:

```python
    def test_tox_commands_are_read_not_only_env_names(self, tmp_path):
        # Reviewer G-2: `[testenv] commands = pytest -q` with envlist py311
        # contributed nothing, because only env *names* were classified.
        root = tmp_path / "toxrepo"
        root.mkdir()
        (root / "tox.ini").write_text(
            "[tox]\nenvlist = py311\n\n[testenv]\ncommands =\n    pytest -q \\\n        --maxfail=1\n"
            "\n[testenv:style]\ncommands = ruff check .\n",
            encoding="utf-8",
        )
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        assert sections["cmd.test"].l2_md.splitlines()[0] == "**Primary:** `tox`"
        assert sections["cmd.lint"].l2_md.splitlines()[0] == "**Primary:** `tox -e style`"
        # one candidate per (purpose, invocation), even though two lines matched
        assert sections["cmd.lint"].l3_md.count("tox -e style") == 1

    def test_shell_scripts_at_root_and_scripts_dir_are_command_sources(self, tmp_path):
        # Reviewer G-2: aero's own release gate, scripts/gate.sh, appeared nowhere.
        root = tmp_path / "shrepo"
        (root / "scripts").mkdir(parents=True)
        (root / "scripts" / "gate.sh").write_text(
            '#!/usr/bin/env bash\nset -euo pipefail\n"$PY" -m ruff check .\n'
            '"$PY" -m pytest -q\n"$PY" -m build\n',
            encoding="utf-8",
        )
        (root / "run.sh").write_text("#!/bin/sh\nuvicorn app:main\n", encoding="utf-8")
        (root / "deep").mkdir()
        (root / "deep" / "ignored.sh").write_text("pytest\n", encoding="utf-8")
        assert cmd_ext.CommandsExtractor().detect(root) is True
        sections = _by_id(cmd_ext.CommandsExtractor().extract(root, _opts(root)))
        for purpose in ("lint", "test", "build"):
            assert "bash scripts/gate.sh" in sections[f"cmd.{purpose}"].l2_md
            assert "scripts/gate.sh" in sections[f"cmd.{purpose}"].l2_md
        assert "bash run.sh" in sections["cmd.run"].l2_md
        assert "deep/ignored.sh" not in sections["cmd.test"].l2_md + sections["cmd.test"].l3_md

    def test_shell_script_is_an_alternative_when_ci_exists(self, repo):
        (repo / "scripts").mkdir()
        (repo / "scripts" / "gate.sh").write_text("pytest -q\n", encoding="utf-8")
        s = _by_id(cmd_ext.CommandsExtractor().extract(repo, _opts(repo)))["cmd.test"]
        assert "pytest -q --cov=airspace" in s.l2_md.splitlines()[0]   # CI still primary
        assert "bash scripts/gate.sh" in s.l3_md
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_extractors.py::TestCommandsExtractor -q`
Expected: the three new tests FAIL.

- [ ] **Step 3: Implement**

In `commands.py`, after `_tox_env_names` add:

```python
def _tox_commands(text: str) -> list[tuple[str, str]]:
    """`(invocation, logical command line)` for every `commands =` value
    of `[testenv]` (invocation `tox`) and `[testenv:<name>]` (`tox -e
    <name>`), continuations joined. Env names alone say nothing about
    what an env runs (reviewer G-2: `envlist = py311` + `commands =
    pytest -q` contributed nothing)."""
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    found: list[tuple[str, str]] = []
    for section in parser.sections():
        if section == "testenv":
            invocation = "tox"
        elif section.startswith("testenv:"):
            invocation = f"tox -e {section.split(':', 1)[1].strip()}"
        else:
            continue
        raw = parser.get(section, "commands", fallback="")
        found.extend((invocation, line) for line in join_continuations(raw))
    return found
```

In `_read_python`, inside the tox `else:` branch, after the
`for name in sorted(names): ...` loop, add:

```python
            for invocation, line in _tox_commands(text):
                purpose = _classify(line)
                candidate = (purpose, invocation, rel)
                if purpose is not None and candidate not in candidates:
                    candidates.append(candidate)
```

(`_tox_commands` parses the same `text` a second time; the tox file is
small and the two helpers stay independently testable.) Widen that branch's
`except` — it already catches `configparser.Error` — no change needed.

Before the `# reader: presence-based defaults` banner add:

```python
# ---------------------------------------------------------------------------
# reader: shell — *.sh at the repo root and directly under scripts/
# ---------------------------------------------------------------------------

_SHELL_DIRS = (Path("."), Path("scripts"))


def _read_shell(root: Path, opts: CodeIngestOptions) -> tuple[list[Candidate], list[str]]:
    """Every `*.sh` at the repo root or directly under `scripts/`. The
    script's logical lines are classified; for each purpose that appears
    at least once the candidate is `bash <script>` with the script as
    source — a Dev agent is told to run the script, not one line torn out
    of it. `bash scripts/gate.sh` is aero's own documented release gate
    and was invisible before this reader (reviewer G-2)."""
    candidates: list[Candidate] = []
    warnings: list[str] = []
    for _depth, reldir, filenames in walk_tree(root, opts.kb_dir):
        if reldir not in _SHELL_DIRS:
            continue
        for name in filenames:
            if not name.endswith(".sh"):
                continue
            path = root / reldir / name
            rel = relposix(root, path)
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"could not parse {rel}: {exc}")
                continue
            purposes = {
                purpose
                for purpose in (_classify(line) for line in join_continuations(text))
                if purpose is not None
            }
            for purpose in PURPOSES:
                if purpose in purposes:
                    candidates.append((purpose, f"bash {rel}", rel))
    return candidates, warnings
```

In `CommandsExtractor.detect`, inside the `for depth, reldir, filenames in walk_tree(root):`
loop, add before `for name in filenames:`:

```python
            if reldir in _SHELL_DIRS and any(f.endswith(".sh") for f in filenames):
                return True
```

In `CommandsExtractor.extract`, insert
`+ _run(_read_shell, "shell scripts", root, opts)` between the python and
presence-based lines, and update the module docstring's "Five readers ...
five sources" to "Six readers ... six sources — CI workflows, npm scripts, a
Makefile, tox/pytest config, shell scripts at the root or under `scripts/`,
and presence-based defaults" with the reader order "(npm, make, python,
shell, presence-based)" wherever the old four-item order is listed
(`_select`'s docstring too).

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_extractors.py::TestCommandsExtractor -q` then the full code-ingest suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/extractors/commands.py tests/test_codeingest_extractors.py
git commit -m "feat(code-ingest): read tox commands and root/scripts shell scripts as command evidence (G-2)"
```

---

### Task 7: Tables never merge across migration directories (G-4)

**Files:**
- Modify: `src/center_kb/codeingest/extractors/schema.py` (`TableRecord`,
  `_apply_sql_file`, new `_dirname`)
- Test: `tests/test_codeingest_extractors.py` (`TestSchemaExtractor`)

**Interfaces:**
- Produces: `TableRecord.created_in: str = ""` (repo-relative file of the
  `CREATE TABLE`); `TableRecord.columns_known: bool = True` (used by Task 8);
  `_dirname(rel: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `class TestSchemaExtractor`:

```python
    def _two_dir_users(self, tmp_path):
        root = tmp_path / "twodirs"
        billing = root / "services" / "billing" / "migrations"
        flyway = root / "src" / "main" / "resources" / "db" / "migration"
        billing.mkdir(parents=True)
        flyway.mkdir(parents=True)
        (billing / "001_init.sql").write_text(
            "CREATE TABLE users (\n  id BIGINT NOT NULL,\n  plan VARCHAR(32) NOT NULL\n);\n",
            encoding="utf-8",
        )
        (flyway / "V1__init.sql").write_text(
            "CREATE TABLE users (\n  id BIGINT NOT NULL,\n  email VARCHAR(255) NOT NULL,\n"
            "  created_at DATETIME NOT NULL,\n  PRIMARY KEY (id)\n);\n",
            encoding="utf-8",
        )
        (flyway / "V2__alter.sql").write_text(
            "ALTER TABLE users ADD COLUMN last_login DATETIME NULL;\n", encoding="utf-8"
        )
        return root

    def test_duplicate_table_in_another_directory_is_not_merged(self, tmp_path):
        # Reviewer G-4: `plan` + `last_login` were joined into a users table
        # that exists in neither schema.
        root = self._two_dir_users(tmp_path)
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.users"]
        assert "| plan |" in s.l2_md
        assert "email" not in s.l2_md
        assert "last_login" not in s.l2_md
        assert "Table users: 2 columns" in s.summary
        assert any(
            "duplicate CREATE TABLE 'users' in src/main/resources/db/migration/V1__init.sql" in w
            and "keeping the definition from services/billing/migrations/001_init.sql" in w
            and "not merged" in w
            for w in result.warnings
        )

    def test_alter_from_another_directory_is_not_applied_and_warns(self, tmp_path):
        root = self._two_dir_users(tmp_path)
        result = schema_ext.SchemaExtractor().extract(root, _opts(root))
        s = _by_id(result)["db.users"]
        assert "V2__alter.sql" not in s.l2_md          # not in Source either
        assert any(
            "ALTER TABLE 'users' ADD COLUMN in src/main/resources/db/migration/V2__alter.sql not applied"
            in w and "created in services/billing/migrations/001_init.sql" in w
            for w in result.warnings
        )

    def test_alter_in_the_same_directory_still_applies(self, repo):
        s = _by_id(schema_ext.SchemaExtractor().extract(repo, _opts(repo)))["db.restrictive_airspace"]
        assert "| effective_date |" in s.l2_md
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_extractors.py::TestSchemaExtractor -q`
Expected: the first two new tests FAIL (`last_login` present, old warning wording).

- [ ] **Step 3: Implement**

In `schema.py`, `TableRecord` gains two fields after `source`:

```python
    created_in: str = ""       # the file whose CREATE TABLE produced this record
    columns_known: bool = True  # False when the reader recognises the table name only (EF)
```

Add after `_join_source`:

```python
def _dirname(rel: str) -> str:
    """Directory part of a repo-relative posix path (`"."` at the root)."""
    return rel.rsplit("/", 1)[0] if "/" in rel else "."
```

In `_apply_sql_file`, replace the `if name in tables:` block (comment and
`_warn_duplicate` + `continue`) with:

```python
        if name in tables:
            existing = tables[name]
            if _dirname(existing.created_in) != _dirname(rel):
                # Two independent migration directories (a per-service
                # schema and a Flyway tree, say) that both create a table
                # of this name describe two different tables. Merging
                # them fabricated a schema that exists nowhere (reviewer
                # G-4); the first in sorted-path order is kept whole and
                # the warning names both files.
                warnings.append(
                    f"duplicate CREATE TABLE {name!r} in {rel} — keeping the "
                    f"definition from {existing.created_in} (a different "
                    "migration directory); the two are not merged"
                )
            else:
                # A same-directory re-CREATE (most plausibly `IF NOT
                # EXISTS` re-asserting a table) must not discard the
                # ALTER TABLE ... ADD COLUMNs already accumulated (task
                # review round 1, Minor 4) — keep the first, warn.
                _warn_duplicate("CREATE TABLE", name, rel, warnings)
            continue
```

and add `created_in=rel,` to the `tables[name] = TableRecord(...)` call
below it. In the ALTER loop, after the `if record is None: ... continue`
block and before `record.columns.append(...)`, add:

```python
        if _dirname(record.created_in) != _dirname(rel):
            warnings.append(
                f"ALTER TABLE {name!r} ADD COLUMN in {rel} not applied — the "
                f"table kept for {name!r} was created in {record.created_in}, "
                "a different migration directory"
            )
            continue
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_extractors.py::TestSchemaExtractor -q` then the full code-ingest suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/extractors/schema.py tests/test_codeingest_extractors.py
git commit -m "fix(code-ingest): never merge a table across migration directories (G-4)"
```

---

### Task 8: EF "columns not extracted"; Alembic whole types and PK (G-13)

**Files:**
- Modify: `src/center_kb/codeingest/extractors/schema.py` (`_clean_type`
  docstring, `ALEMBIC_COLUMN_RE`, new `_alembic_columns`,
  `_apply_alembic_file`, `_apply_ef_file`, `_render_section`)
- Test: `tests/test_codeingest_extractors.py` (`TestSchemaExtractor`)

**Interfaces:**
- Consumes: `TableRecord.columns_known` (Task 7), `_matching_close_paren`,
  `_split_top_level_quote_blind`.
- Produces: `_alembic_columns(scope: str) -> tuple[list[tuple[str, str]], str]`.

- [ ] **Step 1: Write the failing tests**

In `TestSchemaExtractor`, replace
`test_alembic_truncated_column_type_is_left_visibly_incomplete_not_fabricated`
with:

```python
    def test_alembic_column_types_are_captured_whole_and_primary_key_is_seen(self, tmp_path):
        # Reviewer G-13: `[^,)]+` stopped at the first paren, rendering
        # `sa.Integer(` and missing `primary_key=True`. Round 2's concern —
        # never fabricate `sa.Numeric(10)` from `sa.Numeric(10, 2)` — holds
        # because the type is now the first top-level argument, parens
        # balanced, not a truncated capture with a paren appended.
        root = tmp_path / "alembic-types"
        versions = root / "versions"
        versions.mkdir(parents=True)
        (versions / "0001_x.py").write_text(
            "def upgrade():\n"
            "    op.create_table(\n"
            "        'widgets',\n"
            "        sa.Column('id', sa.Integer(), primary_key=True),\n"
            "        sa.Column('amt', sa.Numeric(10, 2), nullable=False),\n"
            "        sa.Column('meta', sa.JSON(none_as_null=True)),\n"
            "    )\n",
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.widgets"]
        assert "| id | sa.Integer() | yes |" in s.l2_md
        assert "| amt | sa.Numeric(10, 2) |  |" in s.l2_md
        assert "| meta | sa.JSON(none_as_null=True) |  |" in s.l2_md
        assert "PK id" in s.summary
```

Append to the class:

```python
    def test_ef_table_says_columns_not_extracted_instead_of_an_empty_table(self, tmp_path):
        # Reviewer G-13: a header row with no rows and "0 columns" reads as
        # "this table has no columns".
        root = tmp_path / "efrepo"
        mig = root / "Migrations"
        mig.mkdir(parents=True)
        (mig / "20240101_Init.cs").write_text(
            'migrationBuilder.CreateTable(\n    name: "Invoices",\n    columns: table => new {}\n);\n',
            encoding="utf-8",
        )
        s = _by_id(schema_ext.SchemaExtractor().extract(root, _opts(root)))["db.Invoices"]
        assert "| Column | Type | PK |" not in s.l2_md
        assert "_Columns not extracted: EF Core migrations are recognised by table name only._" in s.l2_md
        assert "_Source: Migrations/20240101_Init.cs_" in s.l2_md
        assert "Table Invoices: columns not extracted (EF migration), PK none detected" in s.summary
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_extractors.py::TestSchemaExtractor -q`
Expected: both FAIL.

- [ ] **Step 3: Implement**

In `schema.py`:

Replace `_clean_type`'s docstring with:

```
    """Collapse embedded whitespace/newlines to single spaces — the one
    place every reader's column *type-and-constraints* text is cleaned.
    Never appends a closing paren: a literal like `DEFAULT '('` is
    genuinely unbalanced and must stay visibly so (Ruling R36)."""
```

Replace `ALEMBIC_COLUMN_RE = re.compile(r"sa\.Column\(\s*['\"](\w+)['\"]\s*,\s*([^,)]+)")` with:

```python
# Only the column *name* is captured; the type is the call's first
# top-level argument, found by balanced-paren scanning (reviewer G-13 —
# `[^,)]+` stopped at the first paren, so `sa.Integer()` rendered as
# `sa.Integer(`). `primary_key=True` among the remaining arguments marks
# the column as the PK.
ALEMBIC_COLUMN_RE = re.compile(r"sa\.Column\(\s*['\"](\w+)['\"]\s*,")
```

Add after `_matching_close_paren`:

```python
def _alembic_columns(scope: str) -> tuple[list[tuple[str, str]], str]:
    """`(columns, pk)` for every `sa.Column('name', <type>, ...)` call in
    `scope` (one `op.create_table(...)` call's text)."""
    columns: list[tuple[str, str]] = []
    pk = ""
    for cm in ALEMBIC_COLUMN_RE.finditer(scope):
        call_open = scope.index("(", cm.start())
        call_close = _matching_close_paren(scope, call_open)
        args = _split_top_level_quote_blind(scope[cm.end():call_close])
        if not args:
            continue
        cname = _clean_name(cm.group(1))
        columns.append((cname, _clean_type(args[0])))
        if not pk and any(a.replace(" ", "") == "primary_key=True" for a in args[1:]):
            pk = cname
    return columns, pk
```

In `_apply_alembic_file`, replace

```python
        columns = [
            (_clean_name(cm.group(1)), _clean_type(cm.group(2)))
            for cm in ALEMBIC_COLUMN_RE.finditer(scope)
        ]
```

with `columns, pk = _alembic_columns(scope)`, and in the `TableRecord(...)`
below use `pk=pk` and `ddl=_reconstruct_ddl(name, columns, pk)`, adding
`created_in=rel`.

In `_apply_ef_file`'s `TableRecord(...)` add `created_in=rel, columns_known=False`.
In `_apply_prisma_file`'s `TableRecord(...)` add `created_in=rel`; in
`_read_sqlite`'s `TableRecord(...)` add `created_in=` with the same
expression that call already passes as `source=` — every record names the
file it came from.

Replace `_render_section` with:

```python
def _render_section(record: TableRecord) -> CodeSection:
    pk_cols = _pk_columns(record.pk)
    if record.columns_known:
        l2_lines = ["| Column | Type | PK |", "| --- | --- | --- |"]
        for cname, ctype in record.columns:
            mark = "yes" if cname.casefold() in pk_cols else ""
            l2_lines.append(f"| {escape_cell(cname)} | {escape_cell(ctype)} | {mark} |")
        columns_phrase = f"{len(record.columns)} columns"
    else:
        # An EF migration names the table but this reader extracts no
        # columns from it — say so in the document, never an empty table
        # a reader would take for "no columns" (reviewer G-13).
        l2_lines = [
            "_Columns not extracted: EF Core migrations are recognised by table name only._"
        ]
        columns_phrase = "columns not extracted (EF migration)"
    l2_lines.append("")
    l2_lines.append(f"_Source: {record.source}_")
    l2_md = "\n".join(l2_lines) + "\n"

    source_files = "\n".join(record.source.split(", ")) if record.source else ""
    l3_md = f"```sql\n{record.ddl}\n```\n\n```\n{source_files}\n```\n"

    summary = (
        f"Table {record.name}: {columns_phrase}, "
        f"PK {record.pk or 'none detected'} (source: {record.source})."
    )

    return CodeSection(
        id=f"db.{record.name}",
        title=record.name,
        summary=summary,
        group="db",
        l2_md=l2_md,
        l3_md=l3_md,
    )
```

Update `_read_ef`'s docstring: "... every EF-sourced `TableRecord` has an
empty column list and `columns_known=False`, which the renderer states in
the document."

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_extractors.py::TestSchemaExtractor -q` then the full code-ingest suite. Expected: PASS. If `test_clean_type_does_not_fabricate_a_closing_paren_for_a_literal` still passes (it should — `_clean_type` is unchanged in behaviour), leave it.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/extractors/schema.py tests/test_codeingest_extractors.py
git commit -m "fix(code-ingest): EF tables say columns were not extracted; Alembic types whole, PK seen (G-13)"
```

---

### Task 9: Dependency groups rendered; extras and per-file groups; Gin (G-5)

**Files:**
- Modify: `src/center_kb/codeingest/extractors/deps.py` (`FRAMEWORKS`,
  `Groups` comment, `_read_python`, `_render_section`)
- Test: `tests/test_codeingest_extractors.py` (`TestDepsExtractor`, `TestFrameworkLookup`)

- [ ] **Step 1: Write the failing tests**

Append to `class TestDepsExtractor`:

```python
    def test_optional_dependency_groups_are_read_and_rendered(self, repo):
        # Reviewer G-5: five extras (the whole PDF-ingest engine among them)
        # were absent; only [project].dependencies was read.
        (repo / "pyproject.toml").write_text(
            '[project]\nname = "airspace"\nversion = "1.0.0"\n'
            'dependencies = ["fastapi>=0.110", "pydantic>=2.7"]\n'
            "[project.optional-dependencies]\n"
            'ingest = ["docling>=2.0", "Pillow>=10"]\n'
            'dev = ["ruff>=0.15,<0.16", "pytest>=8.0"]\n',
            encoding="utf-8",
        )
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.python"]
        assert "| fastapi | >=0.110 |" in s.l2_md
        assert "| Group | Packages |" in s.l2_md
        assert "| extra:dev | pytest, ruff |" in s.l2_md
        assert "| extra:ingest | docling, Pillow |" in s.l2_md
        assert ">=0.15,<0.16" not in s.l2_md            # constraints live in L3
        assert "# extra:dev\npytest>=8.0\nruff>=0.15,<0.16" in s.l3_md
        assert s.summary == (
            "2 direct Python dependencies; 4 more in 2 groups (extra:dev, extra:ingest); "
            "frameworks: FastAPI."
        )

    def test_non_root_requirements_files_are_their_own_group(self, repo):
        # Reviewer G-5: requirements-gate.txt merged into `direct` duplicated
        # mcp/pyyaml and hid that pytest was a runner-venv dependency.
        (repo / "requirements.txt").write_text("fastapi>=0.110\n", encoding="utf-8")
        (repo / "requirements-gate.txt").write_text("pytest>=8.0\nfastapi>=0.100\n", encoding="utf-8")
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.python"]
        assert s.l2_md.count("| fastapi |") == 1
        assert "| requirements-gate.txt | fastapi, pytest |" in s.l2_md
        assert "# requirements-gate.txt\nfastapi>=0.100\npytest>=8.0" in s.l3_md

    def test_node_dev_dependencies_are_rendered(self, repo):
        s = _by_id(deps_ext.DepsExtractor().extract(repo, _opts(repo)))["dep.node"]
        assert "| dev | eslint |" in s.l2_md
        assert "# dev\neslint^9.0.0" in s.l3_md
        assert s.summary == "1 direct Node dependencies; 1 more in 1 groups (dev); frameworks: React."
```

Append to `class TestFrameworkLookup`:

```python
    def test_gin_is_detected_from_a_real_go_module_path(self):
        # Reviewer G-5: ("gin-gonic/gin", "Gin") never matched go.mod's
        # `github.com/gin-gonic/gin`.
        assert deps_ext.detect_frameworks(["github.com/gin-gonic/gin"]) == ["Gin"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_extractors.py::TestDepsExtractor tests/test_codeingest_extractors.py::TestFrameworkLookup -q`
Expected: the four new tests FAIL.

- [ ] **Step 3: Implement**

In `deps.py`:

Change `("gin-gonic/gin", "Gin"),` to `("github.com/gin-gonic/gin", "Gin"),`.

Replace the `Groups` comment with:

```python
# Groups map a scope name to its (name, constraint) pairs. Every ecosystem
# uses "direct"; node and php add "dev"; python adds "extra:<name>" per
# `[project.optional-dependencies]` table and one group per non-root
# `requirements*.txt`, named by that file's repo-relative path. Every group
# is rendered (reviewer G-5) — names in L2, constraints in L3.
```

In `_read_python`, inside the `else:` branch after the `dependencies`
handling (after the `elif deps: warnings.append(...)` block, same
indentation as `deps = project.get(...)`), add:

```python
                    extras = project.get("optional-dependencies", {})
                    if isinstance(extras, dict):
                        for extra in sorted(extras, key=str):
                            specs = extras[extra]
                            if isinstance(specs, list):
                                _merge(groups, f"extra:{extra}", [
                                    _split_pep508(d) for d in specs if isinstance(d, str)
                                ])
                            else:
                                warnings.append(
                                    f"could not parse {rel}: optional-dependencies "
                                    f"{extra!r} is not a list"
                                )
                    elif extras:
                        warnings.append(
                            f"could not parse {rel}: 'project.optional-dependencies' is not a table"
                        )
```

In the `requirements*.txt` loop replace `_merge(groups, "direct", pairs)` with:

```python
            # Only the root requirements.txt is the runtime set; every other
            # requirements file (a CI runner venv, a docs build) is its own
            # group so nothing is duplicated or misattributed (reviewer G-5).
            _merge(groups, "direct" if rel == "requirements.txt" else rel, pairs)
```

Replace `_render_section` with:

```python
def _render_section(section_id: str, label: str, groups: Groups) -> CodeSection:
    direct = groups.get("direct", [])
    others = [(g, groups[g]) for g in sorted(groups) if g != "direct" and groups[g]]
    all_names = (name for deps in groups.values() for name, _constraint in deps)
    labels = detect_frameworks(all_names)

    l2_lines = [
        f"**Frameworks detected:** {', '.join(labels) if labels else 'none'}",
        "",
        "| Package | Constraint |",
        "| --- | --- |",
    ]
    l2_lines.extend(
        f"| {escape_cell(redact_userinfo(name))} | {escape_cell(redact_userinfo(constraint))} |"
        for name, constraint in direct
    )
    if others:
        # Names only — constraints are in L3 — so the L2 stays the condensed layer.
        l2_lines += ["", "| Group | Packages |", "| --- | --- |"]
        l2_lines.extend(
            f"| {escape_cell(group)} | "
            f"{escape_cell(', '.join(redact_userinfo(name) for name, _c in deps))} |"
            for group, deps in others
        )
    l2_md = "\n".join(l2_lines) + "\n"

    l3_blocks = []
    for group_name, deps in [("direct", direct), *others]:
        if not deps:
            continue
        body = "\n".join(_fmt_dep(name, constraint) for name, constraint in deps)
        l3_blocks.append(f"```\n# {group_name}\n{body}\n```")
    l3_md = "\n\n".join(l3_blocks) + "\n"

    extra_count = sum(len(deps) for _g, deps in others)
    summary = f"{len(direct)} direct {label} dependencies"
    if others:
        summary += (
            f"; {extra_count} more in {len(others)} groups "
            f"({', '.join(group for group, _d in others)})"
        )
    summary += f"; frameworks: {', '.join(labels)}." if labels else "."

    return CodeSection(
        id=section_id,
        title=f"{label} dependencies",
        summary=summary,
        group="deps",
        l2_md=l2_md,
        l3_md=l3_md,
    )
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_extractors.py::TestDepsExtractor tests/test_codeingest_extractors.py::TestFrameworkLookup -q` then the full code-ingest suite. Expected: PASS. (`test_go_mod_skips_comment_only_lines_in_require_block` asserts `"1 direct Go dependencies."` — unchanged when there is no other group.)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/extractors/deps.py tests/test_codeingest_extractors.py
git commit -m "fix(code-ingest): render every dependency group, read extras and per-file requirements, fix Gin prefix (G-5)"
```

---

### Task 10: Workspace `package.json` as a services source (G-6)

**Files:**
- Modify: `src/center_kb/codeingest/extractors/services.py` (`ServiceRecord`,
  new `_read_workspaces`, `_dedupe`, `_technology_for`, `_render_section`
  lead sentence and summary, `ServicesExtractor.detect/extract`, module docstring)
- Test: `tests/test_codeingest_extractors.py` (`TestServicesExtractor`)

**Interfaces:**
- Consumes: `tree.IGNORED_DIRS`.
- Produces: `ServiceRecord.directory: str = ""`, `ServiceRecord.command: str = ""`,
  `ServiceRecord.env_files: list[str]`, `ServiceRecord.base_image: str = ""`
  (Task 11 fills the last three); `_read_workspaces(root) -> tuple[list[ServiceRecord], list[str]]`.

- [ ] **Step 1: Write the failing tests**

Append to `class TestServicesExtractor`:

```python
    def _mono(self, tmp_path):
        root = tmp_path / "mono"
        (root / "packages" / "api").mkdir(parents=True)
        (root / "packages" / "web").mkdir(parents=True)
        (root / "package.json").write_text(
            '{"name": "mono", "private": true, "workspaces": ["packages/*"]}\n',
            encoding="utf-8",
        )
        (root / "packages" / "api" / "package.json").write_text(
            '{"name": "@mono/api", "dependencies": {"express": "^4.19.0"}}\n', encoding="utf-8"
        )
        (root / "packages" / "web" / "package.json").write_text(
            '{"name": "web", "dependencies": {"react": "^18.2.0"}}\n', encoding="utf-8"
        )
        (root / "packages" / "stray.txt").write_text("", encoding="utf-8")
        return root

    def test_workspace_packages_become_services_in_a_node_monorepo(self, tmp_path):
        # Reviewer G-6: spec and README list workspace package.json as a
        # services source; no reader existed, so a monorepo got no svc.* at all.
        root = self._mono(tmp_path)
        assert svc_ext.ServicesExtractor().detect(root) is True
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        titles = sorted(s.title for s in result.sections)
        assert titles == ["@mono/api", "web"]
        by_title = {s.title: s for s in result.sections}
        assert "| Technology | Express |" in by_title["@mono/api"].l2_md
        assert "| Technology | React |" in by_title["web"].l2_md
        assert "| Source | packages/web/package.json |" in by_title["web"].l2_md
        assert "Workspace package `web` in `packages/web` — no container image." in by_title["web"].l2_md

    def test_workspaces_object_form_and_missing_package_json_are_handled(self, tmp_path):
        root = self._mono(tmp_path)
        (root / "package.json").write_text(
            '{"workspaces": {"packages": ["packages/*", "tools/*"]}}\n', encoding="utf-8"
        )
        (root / "tools" / "empty").mkdir(parents=True)       # no package.json: not a service
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        assert sorted(s.title for s in result.sections) == ["@mono/api", "web"]

    def test_malformed_workspaces_value_warns_and_continues(self, tmp_path):
        root = self._mono(tmp_path)
        (root / "package.json").write_text('{"workspaces": "packages/*"}\n', encoding="utf-8")
        (root / "docker-compose.yml").write_text(
            "services:\n  db:\n    image: postgres:16\n", encoding="utf-8"
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        assert [s.title for s in result.sections] == ["db"]
        assert any("'workspaces' is not a list" in w for w in result.warnings)

    def test_compose_service_with_the_same_name_as_a_workspace_keeps_compose_evidence(self, tmp_path):
        root = self._mono(tmp_path)
        (root / "docker-compose.yml").write_text(
            "services:\n  web:\n    image: web:1.0\n    ports: ['3000:3000']\n", encoding="utf-8"
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        web = {s.title: s for s in result.sections}["web"]
        assert "| Image | web:1.0 |" in web.l2_md
        assert "| Technology | React |" in web.l2_md      # directory filled from the workspace record
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_extractors.py::TestServicesExtractor -q`
Expected: the four new tests FAIL.

- [ ] **Step 3: Implement**

In `services.py`:

Change the tree import to
`from center_kb.codeingest.extractors.tree import IGNORED_DIRS, relposix, walk_tree`.

`ServiceRecord` gains, after `source`:

```python
    directory: str = ""                 # the service's own code directory, when known
    command: str = ""                   # Dockerfile CMD/ENTRYPOINT as one shell line (Task 11)
    env_files: list[str] = field(default_factory=list)  # compose env_file *names*, never opened
    base_image: str = ""                # FROM of a built service (Task 11); feeds technology
```

After `_read_sln` add:

```python
# ---------------------------------------------------------------------------
# reader: workspace package.json (Node monorepos)
# ---------------------------------------------------------------------------


def _read_workspaces(root: Path) -> tuple[list[ServiceRecord], list[str]]:
    """The root `package.json`'s `workspaces` — a list of globs, or the
    `{"packages": [...]}` object form — each resolved to directories that
    hold their own `package.json`. One image-less record per package,
    named from that package's `name` (else the directory name), with
    `directory` set so the Technology column reads the package's own
    dependencies. Listed in the spec and README from the start, never
    implemented (reviewer G-6); without it a Node monorepo has no
    `svc.*` and no Stage-D join key."""
    path = root / "package.json"
    if not path.is_file():
        return [], []
    rel = relposix(root, path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [f"could not parse {rel}: {exc}"]
    if not isinstance(data, dict):
        return [], [f"could not parse {rel}: top-level is not an object"]
    workspaces = data.get("workspaces")
    if workspaces is None:
        return [], []
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages")
    if not isinstance(workspaces, list):
        return [], [f"could not parse {rel}: 'workspaces' is not a list"]

    records: list[ServiceRecord] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for pattern in workspaces:
        if not isinstance(pattern, str):
            warnings.append(f"could not parse {rel}: workspace entry {pattern!r} is not a string")
            continue
        for match in sorted(root.glob(pattern)):
            if not match.is_dir():
                continue
            rel_dir = relposix(root, match)
            if any(part in IGNORED_DIRS for part in Path(rel_dir).parts):
                continue
            pkg = match / "package.json"
            if not pkg.is_file() or rel_dir in seen:
                continue
            seen.add(rel_dir)
            name = match.name
            try:
                pkg_data = json.loads(pkg.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                warnings.append(f"could not parse {rel_dir}/package.json: {exc}")
            else:
                pkg_name = pkg_data.get("name") if isinstance(pkg_data, dict) else None
                if isinstance(pkg_name, str) and pkg_name.strip():
                    name = pkg_name
            records.append(ServiceRecord(
                name=name, image="", source=f"{rel_dir}/package.json", directory=rel_dir,
            ))
    records.sort(key=lambda r: r.directory)
    return records, warnings
```

In `_dedupe`, after the image-fill `if` block add:

```python
        if not merged.directory and rec.directory:
            # Metadata, not evidence: a workspace record only tells a
            # compose-declared service where its code lives.
            merged = replace(merged, directory=rec.directory)
```

Replace `_technology_for` with:

```python
def _technology_for(root: Path, record: ServiceRecord) -> str:
    directory = root / (record.directory or record.name)
    names = _dep_names_from_directory(directory) if directory.is_dir() else []
    if not names:
        base = _image_base_name(record.base_image or record.image)
        names = [base] if base else []
    labels = detect_frameworks(names)
    return ", ".join(labels) if labels else "none"
```

(Task 11 adds the infrastructure-image lookup here.)

In `_render_section`, replace the first element of `l2_lines`
(`f"Container `{name}` — image `{record.image}`.",`) with `_lead_sentence(name, record),`
and add before `_render_section`:

```python
def _lead_sentence(name: str, record: ServiceRecord) -> str:
    if not record.image and record.directory:
        return f"Workspace package `{name}` in `{record.directory}` — no container image."
    return f"Container `{name}` — image `{record.image}`."
```

and in `summary` change `image {record.image},` to `image {record.image or 'none'},`.

In `ServicesExtractor.detect`, before the k8s fallback add:

```python
        pkg = root / "package.json"
        if pkg.is_file():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                data = None
            if isinstance(data, dict) and "workspaces" in data:
                return True
```

In `ServicesExtractor.extract`, after the sln block and before `_dedupe`, add:

```python
        try:
            ws_records, ws_warnings = _read_workspaces(root)
        except Exception as exc:
            ws_records, ws_warnings = [], [f"could not read workspace package.json: {exc}"]
        records.extend(ws_records)
        warnings.extend(ws_warnings)
```

Update the module docstring: "Four readers" → "Five readers" and add
"workspace `package.json`" to the list of manifest kinds.

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_extractors.py::TestServicesExtractor -q` then the full code-ingest suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/extractors/services.py tests/test_codeingest_extractors.py
git commit -m "feat(code-ingest): workspace package.json packages are services (G-6)"
```

---

### Task 11: Compose `build:` reads its Dockerfile; Command/Env-file rows; infrastructure images (G-8)

**Files:**
- Modify: `src/center_kb/codeingest/extractors/services.py` (`_read_compose`,
  new `_parse_dockerfile`/`_resolve_build`, `_read_dockerfile`,
  `_INFRA_IMAGES`, `_technology_for`, `_lead_sentence`, `_render_section`)
- Test: `tests/test_codeingest_extractors.py` (`TestServicesExtractor`)

**Interfaces:**
- Consumes: `_lines.join_continuations`; `ServiceRecord.command/env_files/base_image` (Task 10).
- Produces: `_parse_dockerfile(text) -> tuple[str, list[str], str]`
  (runtime-stage `FROM` image, `EXPOSE` ports, last `CMD`/`ENTRYPOINT` as a shell line);
  `_resolve_build(compose_dir, build) -> tuple[str, Path | None]`; `_INFRA_IMAGES`.

- [ ] **Step 1: Write the failing tests**

Append to `class TestServicesExtractor`:

```python
    def test_compose_build_reads_the_dockerfile_for_image_ports_and_command(self, tmp_path):
        # Reviewer G-8: aero's svc.hub rendered ``image ` ` `` because
        # compose says `build: .` and the Dockerfile reader ran only when
        # there was no compose file at all.
        root = tmp_path / "hubrepo"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  hub:\n    build: .\n    env_file: .env\n", encoding="utf-8"
        )
        (root / "Dockerfile").write_text(
            "FROM python:3.12-slim AS build\nRUN pip install build\n"
            "FROM python:3.12-slim\nEXPOSE 8321\n"
            'CMD ["python", "-m", "center_kb.mcp", \\\n     "--transport", "http"]\n',
            encoding="utf-8",
        )
        (root / ".env").write_text("SECRET=hunter2\n", encoding="utf-8")
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        s = _by_id(result)["svc.hub"]
        assert "Container `hub` — built from `Dockerfile` (base `python:3.12-slim`)." in s.l2_md
        assert "| Image | build: Dockerfile (FROM python:3.12-slim) |" in s.l2_md
        assert "| Ports | 8321 |" in s.l2_md
        assert "| Command | python -m center_kb.mcp --transport http |" in s.l2_md
        assert "| Env file | .env |" in s.l2_md
        assert "| Technology | Python |" in s.l2_md
        assert "| Source | docker-compose.yml, Dockerfile |" in s.l2_md
        assert "hunter2" not in s.l2_md + s.l3_md
        assert result.warnings == []

    def test_compose_build_mapping_with_context_and_dockerfile_keys(self, tmp_path):
        root = tmp_path / "ctx"
        (root / "services" / "api").mkdir(parents=True)
        (root / "docker-compose.yml").write_text(
            "services:\n  api:\n    build:\n      context: services/api\n"
            "      dockerfile: Dockerfile.prod\n    ports: ['9000:9000']\n",
            encoding="utf-8",
        )
        (root / "services" / "api" / "Dockerfile.prod").write_text(
            "FROM node:20\nEXPOSE 3000\n", encoding="utf-8"
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.api"]
        assert "| Image | build: services/api/Dockerfile.prod (FROM node:20) |" in s.l2_md
        assert "| Ports | 9000:9000 |" in s.l2_md        # compose ports win over EXPOSE
        assert "| Technology | Node.js |" in s.l2_md

    def test_compose_build_without_a_dockerfile_warns(self, tmp_path):
        root = tmp_path / "nodf"
        root.mkdir()
        (root / "docker-compose.yml").write_text(
            "services:\n  worker:\n    build: ./worker\n", encoding="utf-8"
        )
        result = svc_ext.ServicesExtractor().extract(root, _opts(root))
        s = _by_id(result)["svc.worker"]
        assert "| Image | build: ./worker (Dockerfile not found) |" in s.l2_md
        assert any("worker" in w and "no Dockerfile" in w for w in result.warnings)

    def test_infrastructure_images_get_a_technology_label(self, repo):
        s = _by_id(svc_ext.ServicesExtractor().extract(repo, _opts(repo)))["svc.postgres"]
        assert "| Technology | PostgreSQL |" in s.l2_md

    def test_dockerfile_fallback_uses_the_runtime_stage_and_command(self, tmp_path):
        root = tmp_path / "solo2"
        root.mkdir()
        (root / "Dockerfile").write_text(
            "FROM golang:1.22 AS build\nFROM gcr.io/distroless/static\nEXPOSE 8080\n"
            'ENTRYPOINT ["/app"]\n',
            encoding="utf-8",
        )
        s = _by_id(svc_ext.ServicesExtractor().extract(root, _opts(root)))["svc.demo"]
        assert "| Image | gcr.io/distroless/static |" in s.l2_md
        assert "| Command | /app |" in s.l2_md
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_codeingest_extractors.py::TestServicesExtractor -q`
Expected: the five new tests FAIL.

- [ ] **Step 3: Implement**

In `services.py`:

Add `import os` to the standard-library imports and the import
`from center_kb.codeingest.extractors._lines import join_continuations`.

Replace `_read_dockerfile` with:

```python
def _exec_form_to_shell(rest: str) -> str:
    """`["python", "-m", "x"]` -> `python -m x`; shell form is returned as is."""
    if rest.startswith("["):
        try:
            items = json.loads(rest)
        except json.JSONDecodeError:
            return rest
        if isinstance(items, list) and all(isinstance(i, str) for i in items):
            return " ".join(items)
    return rest


def _parse_dockerfile(text: str) -> tuple[str, list[str], str]:
    """`(image, ports, command)`: the image of the *last* `FROM` (the
    runtime stage of a multi-stage build — the first `FROM` is a build
    stage that never runs), every `EXPOSE` port, and the last
    `CMD`/`ENTRYPOINT` rendered as one shell line. Continuations joined."""
    image = ""
    ports: list[str] = []
    command = ""
    for line in join_continuations(text):
        parts = line.split()
        directive = parts[0].upper()
        if directive == "FROM" and len(parts) >= 2:
            image = parts[1]
        elif directive == "EXPOSE":
            for token in parts[1:]:
                port = token.split("/", 1)[0]  # "8080/tcp" -> "8080"
                if port:
                    ports.append(port)
        elif directive in ("CMD", "ENTRYPOINT") and len(parts) >= 2:
            command = _exec_form_to_shell(line.split(None, 1)[1].strip())
    return image, ports, command


def _read_dockerfile(root: Path, repo_id: str) -> tuple[list[ServiceRecord], list[str]]:
    """A root `Dockerfile`, read only as the Ruling-R1 fallback (the
    caller only calls this when `_read_compose()` produced zero
    services). Yields one service named `repo_id`."""
    path = root / "Dockerfile"
    if not path.is_file():
        return [], []
    rel = relposix(root, path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"could not parse {rel}: {exc}"]
    image, ports, command = _parse_dockerfile(text)
    record = ServiceRecord(
        name=repo_id, image=image, ports=ports, source=rel, command=command, base_image=image,
    )
    return [record], []
```

Before `_read_compose` add:

```python
def _resolve_build(compose_dir: Path, build: object) -> tuple[str, Path | None]:
    """`(context label, Dockerfile path)` for a compose `build:` value — a
    string context, or a mapping with `context` (default `.`) and
    `dockerfile` (default `Dockerfile`). `None` when the value has the
    wrong shape."""
    if isinstance(build, str):
        context, dockerfile = build, "Dockerfile"
    elif isinstance(build, dict):
        context = build.get("context", ".")
        dockerfile = build.get("dockerfile", "Dockerfile")
        if not isinstance(context, str) or not isinstance(dockerfile, str):
            return "", None
    else:
        return "", None
    return context, compose_dir / context / dockerfile
```

In `_read_compose`, replace the `records.append(ServiceRecord(...))` call
(and the two `image = ...` lines before it) with:

```python
            image = spec.get("image", "")
            if not isinstance(image, str):
                image = str(image) if image is not None else ""
            ports = _stringify_list(spec.get("ports", []))
            source = rel
            command = ""
            base_image = ""
            build = spec.get("build")
            if not image and build is not None:
                # A `build:` service has no image name, but it has a
                # Dockerfile — and that Dockerfile's runtime stage, EXPOSE
                # and CMD are the knowledge a reader wants (reviewer G-8:
                # aero's own hub service rendered an empty image).
                context, dockerfile_path = _resolve_build(path.parent, build)
                if dockerfile_path is not None and dockerfile_path.is_file():
                    # normpath (not resolve) collapses `./` and `../` without
                    # following symlinks, so the label stays repo-relative.
                    normalised = Path(os.path.normpath(dockerfile_path))
                    try:
                        dockerfile_rel = relposix(root, normalised)
                    except ValueError:  # a build context outside the repo
                        dockerfile_rel = normalised.as_posix()
                    try:
                        base_image, exposed, command = _parse_dockerfile(
                            dockerfile_path.read_text(encoding="utf-8")
                        )
                    except (OSError, UnicodeDecodeError) as exc:
                        warnings.append(f"could not parse {dockerfile_rel}: {exc}")
                        exposed = []
                    image = f"build: {dockerfile_rel} (FROM {base_image or 'unknown'})"
                    if not ports:
                        ports = exposed
                    source = f"{rel}, {dockerfile_rel}"
                else:
                    image = f"build: {context or '.'} (Dockerfile not found)"
                    warnings.append(
                        f"service {name!r} in {rel}: build context {context or '.'!r} "
                        "has no Dockerfile"
                    )
            records.append(ServiceRecord(
                name=str(name),
                image=image,
                ports=ports,
                depends_on=_stringify_list(spec.get("depends_on", [])),
                env_keys=_env_keys_from(spec.get("environment", {})),
                source=source,
                command=command,
                env_files=_stringify_list(spec.get("env_file", [])),
                base_image=base_image,
            ))
```

Before `_image_base_name` add:

```python
# Infrastructure images have no dependency manifest to read; label them by
# repository name (reviewer G-8: Technology was `none` on every service in
# every fixture). Matched on the image's base name, exactly.
_INFRA_IMAGES: dict[str, str] = {
    "postgres": "PostgreSQL", "postgresql": "PostgreSQL", "mysql": "MySQL",
    "mariadb": "MariaDB", "redis": "Redis", "nginx": "nginx", "mongo": "MongoDB",
    "rabbitmq": "RabbitMQ", "kafka": "Kafka", "cp-kafka": "Kafka",
    "elasticsearch": "Elasticsearch", "traefik": "Traefik", "minio": "MinIO",
    "memcached": "Memcached", "python": "Python", "node": "Node.js",
    "golang": "Go", "openjdk": "Java", "eclipse-temurin": "Java", "amazoncorretto": "Java",
}
```

Replace `_technology_for` with:

```python
def _technology_for(root: Path, record: ServiceRecord) -> str:
    directory = root / (record.directory or record.name)
    names = _dep_names_from_directory(directory) if directory.is_dir() else []
    labels = detect_frameworks(names)
    if labels:
        return ", ".join(labels)
    base = _image_base_name(record.base_image or record.image)
    if base in _INFRA_IMAGES:
        return _INFRA_IMAGES[base]
    labels = detect_frameworks([base]) if base else []
    return ", ".join(labels) if labels else "none"
```

Replace `_lead_sentence` with:

```python
def _lead_sentence(name: str, record: ServiceRecord) -> str:
    if record.base_image and record.image.startswith("build: "):
        dockerfile = record.image[len("build: "):].split(" (", 1)[0]
        return f"Container `{name}` — built from `{dockerfile}` (base `{record.base_image}`)."
    if not record.image and record.directory:
        return f"Workspace package `{name}` in `{record.directory}` — no container image."
    return f"Container `{name}` — image `{record.image}`."
```

In `_render_section`'s `l2_lines`, insert after the `Ports` row:

```python
        *([f"| Command | {escape_cell(redact_userinfo(record.command))} |"] if record.command else []),
```

and after the `Env keys` row:

```python
        *([f"| Env file | {escape_cell(', '.join(record.env_files))} |"] if record.env_files else []),
```

Add `from center_kb.codeingest.extractors._envkeys import env_keys_from, redact_userinfo`
(extend the existing `_envkeys` import). In `record_dict`, add the three
keys only when non-empty so unchanged fixtures keep byte-identical L3:

```python
    for key, value in (
        ("command", record.command), ("env_files", record.env_files), ("directory", record.directory),
    ):
        if value:
            record_dict[key] = value
```

- [ ] **Step 4: Run the tests**

Run: `pytest tests/test_codeingest_extractors.py::TestServicesExtractor -q` then the full code-ingest suite. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/codeingest/extractors/services.py tests/test_codeingest_extractors.py
git commit -m "fix(code-ingest): compose build: reads its Dockerfile; Command/Env file rows; infra image technology (G-8)"
```

---

### Task 12: Self-ingest acceptance test, docs, changelog, 0.23.0

**Files:**
- Create: `tests/test_codeingest_self_ingest.py`
- Modify: `README.md` (§7.12), `CHANGELOG.md`, `pyproject.toml:3`,
  `docs/superpowers/plans/2026-08-19-dev-agent-stage-b-handover.md` (§3)

- [ ] **Step 1: Write the acceptance tests (they run against this checkout)**

Create `tests/test_codeingest_self_ingest.py`:

```python
"""Reviewer G's acceptance, automated: `kb code-ingest` on the framework's
own repository must be right about it, and two clones of the same commit
— one carrying git-ignored directories — must produce byte-identical
documents. Skipped outside a git checkout of this repository."""
from pathlib import Path

import pytest

from center_kb import models
from center_kb.codeingest import core

REPO = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (REPO / ".git").exists(), reason="needs the framework's own git checkout"
)


def _ingest(root: Path, kb_dir: Path) -> Path:
    core.run(core.CodeIngestOptions(repo_root=root, kb_dir=kb_dir, doc_id="aero-code", repo_id="aero"))
    return kb_dir / "aero-code"


def _section(text: str, heading: str) -> str:
    return text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]


def test_self_ingest_is_accurate_about_this_repository(tmp_path):
    doc = _ingest(REPO, tmp_path / "kb")

    commands = (doc / "commands.md").read_text(encoding="utf-8")
    assert "**Primary:** `ruff check .`" in _section(commands, "cmd.lint")
    assert "**Primary:** `python -m build`" in _section(commands, "cmd.build")
    assert "/dev/null" not in commands
    assert "bash scripts/gate.sh" in commands

    structure = (doc / "structure.raw.md").read_text(encoding="utf-8")
    assert ".venv" not in structure and ".worktrees" not in structure
    assert structure.count("\n") <= 610
    manifest = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    tree_summary = next(s.summary for s in manifest.sections if s.id == "struct.tree")
    assert "tracked files" in tree_summary

    services = (doc / "services.md").read_text(encoding="utf-8")
    assert "| Technology | Python |" in _section(services, "svc.hub")
    assert "FROM python:3.12-slim" in _section(services, "svc.hub")

    deps = (doc / "deps.md").read_text(encoding="utf-8")
    python_l2 = _section(deps, "dep.python")
    assert python_l2.count("| mcp |") == 1
    assert "| extra:dev |" in python_l2 and "| extra:ingest |" in python_l2
    assert "| requirements-gate.txt |" in python_l2


def test_same_commit_with_and_without_ignored_dirs_is_byte_identical(tmp_path, run_git):
    a, b = tmp_path / "a", tmp_path / "b"
    run_git(tmp_path, "clone", "-q", str(REPO), str(a))
    run_git(tmp_path, "clone", "-q", str(REPO), str(b))
    junk = b / ".venv-artifact" / "Lib" / "site-packages" / "x"
    junk.mkdir(parents=True)
    (junk / "main.py").write_text("", encoding="utf-8")
    (b / ".worktrees" / "t").mkdir(parents=True)
    (b / ".worktrees" / "t" / "app.py").write_text("", encoding="utf-8")

    doc_a = _ingest(a, tmp_path / "ka")
    doc_b = _ingest(b, tmp_path / "kb")
    names = sorted(p.name for p in doc_a.iterdir())
    assert names == sorted(p.name for p in doc_b.iterdir())
    for name in names:
        assert (doc_a / name).read_bytes() == (doc_b / name).read_bytes(), name
```

- [ ] **Step 2: Run them**

Run: `pytest tests/test_codeingest_self_ingest.py -q`
Expected: PASS (≈ 20 s). If `cmd.lint`/`cmd.build` assertions fail, read
the generated `commands.md` in `tmp_path` — the fix belongs in the
extractor, not in the assertion (the primary must be the CI line that
actually lints/builds).

- [ ] **Step 3: README §7.12**

In the flag table replace the `--kb-dir` row with:

```
| `--kb-dir` | KB directory to write into (default: `.kb`, relative to the current directory like every other `kb` command) |
```

and the `--db` row with:

```
| `--db` | An explicit SQLite file to read for schema — repeatable; never inferred (§3.11 below). A relative path is relative to `--repo-root` |
```

In the extractor table replace these rows:

```
| `services` | `docker-compose*.yml` (a `build:` service is read through its Dockerfile — runtime-stage `FROM`, `EXPOSE`, `CMD`; `env_file` by name only), `Dockerfile`, k8s manifests, `*.sln`, workspace `package.json` | `svc.<name>` |
| `deps` | `pyproject.toml` (`dependencies` and every `optional-dependencies` group), `requirements*.txt` (the root file is `direct`; any other is its own group), `setup.cfg`, `package.json` (`dependencies` and `devDependencies`), `pom.xml`, `build.gradle{,.kts}`, `*.csproj`, `go.mod`, `composer.json` (`require` and `require-dev`) | `dep.<ecosystem>` |
| `commands` | `package.json` `scripts`, `Makefile` targets, `tox.ini` (env names and `commands =`), `pyproject` tool sections, `*.sh` at the root or under `scripts/`, `pom.xml`, `*.csproj`, and `.github/workflows/*.yml` `run:` steps (CI wins over a local script when both exist; commands are classified by whole token, never substring) | `cmd.build`/`cmd.test`/`cmd.lint`/`cmd.run` |
| `tree` | `git ls-files` — the tracked files at HEAD, so a git-ignored virtualenv or worktree never appears and two checkouts of one commit agree — plus the always-pruned `node_modules`/`target`/`bin`/`obj`/`dist`/`build`/`venv`/`__pycache__`/`.git`/`.kb`. Outside a git repository it is an unfiltered walk and the section says so. The L3 listing is capped at 600 lines (and depth 4) with a marker | `struct.tree` |
```

After the "Reserved doc-id suffixes" paragraph add:

```
**A destination this command did not write is refused.** If
`.kb/<doc_id>/` already holds Markdown or a manifest and that manifest is
missing, unreadable, not titled `… — code knowledge`, or lists a section
id outside the seven generated prefixes, `kb code-ingest` exits 1 and
writes nothing — a hand-curated document that happens to sit at
`<repo_id>-code` is never deleted. Move it or choose another `--doc-id`;
there is no override flag.
```

In the "Deliberate parser limits" paragraph, after the sentence ending
"applied in sorted filename order; it does not implement a SQL dialect."
add:

```
A `CREATE TABLE` of a name already created in a *different* migration
directory is dropped with a warning naming both files, and an `ALTER
TABLE … ADD COLUMN` is applied only inside the directory of its `CREATE
TABLE` — two independent schemas that share a table name are never
merged into one that exists nowhere. EF Core migrations are recognised by
table name only and the section says "columns not extracted". Maven
`<plugins>`, `setup.cfg` `extras_require`, `pnpm-workspace.yaml` and
compose `healthcheck:` are not read.
```

In the "Determinism guarantee" paragraph change "Extractors are pure
functions of the working tree" to "Extractors are pure functions of the
tracked files at HEAD (plus `--db` files named explicitly)".

- [ ] **Step 4: Changelog, version, handover**

`pyproject.toml:3` → `version = "0.23.0"`. Then `uv sync --all-extras` (or
`pip install -e . --no-deps`) so the installed metadata matches.

Insert at the top of `CHANGELOG.md`'s entries (above `## 0.22.0`):

```
## 0.23.0

### Breaking — `kb code-ingest` paths and destinations

- A relative `--kb-dir` is relative to the current directory, like every
  other `kb` command — no longer to `--repo-root`. `kb-code.yml` runs at
  the checkout root with the default and is unaffected.
- A destination `.kb/<doc_id>/` that holds a document this command did
  not generate (missing/unreadable manifest, foreign title, foreign
  section id) is refused with exit 1 instead of being overwritten.
- `_manifest.yaml`'s `source_sha256` is empty for `-code`/`-svc`
  documents; `revision` carries the commit.

### Fixed — the generated `-code` document (reviewer G, 2026-09-08)

- `struct.tree` lists `git ls-files`, not an unfiltered walk: git-ignored
  virtualenvs and worktrees are gone, "tracked files" is true, two
  checkouts of one commit agree, and L3 is capped at 600 lines (G-3).
- `cmd.*` classify commands by whole token (`/dev/null` is not `dev`,
  `:latest` is not `test`), join `\` continuations, no longer treat `pip
  install` as a build, and read tox `commands =` and `*.sh` at the root
  or under `scripts/` (G-2).
- `db.*` never merge a table across migration directories; the warning
  names both files (G-4). EF tables say "columns not extracted"; Alembic
  types render whole and `primary_key=True` is seen (G-13).
- `dep.*` render every group: `optional-dependencies`, `devDependencies`,
  `require-dev`, and each non-root `requirements*.txt` as its own group;
  Gin is detected from `github.com/gin-gonic/gin` (G-5).
- `svc.*` come from workspace `package.json` too (G-6); a compose
  `build:` service shows its Dockerfile's runtime image, `EXPOSE`, `CMD`
  and `env_file` names; infrastructure images get a Technology label (G-8).
- Console scripts are listed apart from file entry points (G-16).
```

In the handover doc, at the end of §3 add:

```
> 2026-09-16: paid in part by the reviewer-G batch (0.23.0) — a compose
> `build:` service now reads its Dockerfile and `Technology` labels
> infrastructure images and workspace packages. The `tables:` heuristic in
> §2 is unchanged.
```

- [ ] **Step 5: Run everything**

Run: `ruff check .` — Expected: clean.
Run: `pytest tests/test_codeingest_core.py tests/test_codeingest_extractors.py tests/test_codeingest_scaffold.py tests/test_cli_codeingest.py tests/test_codeingest_lines.py tests/test_codeingest_self_ingest.py -q` — Expected: PASS.
Run: `pytest -q` (full suite; needs the tiktoken cache once) — Expected: PASS, including the version-pin test.

- [ ] **Step 6: Commit**

```bash
git add README.md CHANGELOG.md pyproject.toml docs/superpowers/plans/2026-08-19-dev-agent-stage-b-handover.md tests/test_codeingest_self_ingest.py
git commit -m "chore: release 0.23.0 — code-ingest is right about its own repo (reviewer G)"
```

---

## Self-review against the spec

- **§1 tree** → Tasks 1, 2. **§2 foreign destinations** → Task 3. **§3
  `--kb-dir`, `source_sha256`** → Task 4. **§4 commands** (classifier,
  continuations, tox, shell) → Tasks 5, 6. **§5 schema** (directories, EF,
  Alembic) → Tasks 7, 8. **§6 deps** → Task 9. **§7 services** (workspaces,
  `build:`, technology, rows) → Tasks 10, 11. **§8 release + README** →
  Task 12. **Acceptance** (self-ingest, two clones) → Task 12 tests.
- Names used across tasks: `join_continuations` (Task 5 → 6, 11);
  `TableRecord.created_in`/`columns_known` (Task 7 → 8);
  `ServiceRecord.directory/command/env_files/base_image` (Task 10 → 11);
  `_lead_sentence` (Task 10 → 11); `tracked_files` (Task 1 → 12 via
  behaviour only).
