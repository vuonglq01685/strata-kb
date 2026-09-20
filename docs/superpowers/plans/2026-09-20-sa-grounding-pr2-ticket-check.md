# SA grounding layer — PR 2 (`kb ticket check`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `kb ticket check <ticket.md>` — the machine gate that verifies every id in a ticket's `## Technical grounding` section against the real `<repo>-code` document (local `.kb/` first, hub federation second), exits 0 only when every id resolves and `Open decisions` is empty.

**Architecture:** One new engine module `src/strata_kb/ticketcheck.py` (no CLI/MCP imports — the same split `ticketlint.py` has), returning the existing `lintcore.LintReport`. It parses the section with `lintcore.section_body`, resolves ids against the document's `_manifest.yaml`, and deep-checks columns / routes / commands / files by slicing the document's own L2/L3 group files with `mdutils.slice_section` and `lintcore.table_rows`. Where the document comes from is the CLI's business: a `load_doc(repo, doc)` callable, local-then-hub. One new command `check` on the existing `ticket_app`. `LintReport.render` gains an optional verdict label so the last line reads `Grounding: PASS|FAIL`.

**Tech Stack:** Python 3.11+, typer, pydantic models already in `strata_kb.models`, pytest with the existing `fed_hub` / `run_git` fixtures and `tests/fixtures_coderepo.build_code_repo`.

**Spec:** `docs/superpowers/specs/2026-09-20-sa-grounding-design.md` — §3 (field rules), §7 (CLI, engine, document source, tests, non-goals), §8 (PR 2 scope), §9 (out of scope).

## Global Constraints

- **NEVER bump the version.** `pyproject.toml` and `uv.lock` untouched; CHANGELOG edits stay under the existing `## Unreleased` heading.
- No new dependency. No new extractor. `src/strata_kb/mdutils.py` is frozen — never edit it; `src/strata_kb/codeingest/core.py` is not touched (decision A5: revision match on the manifest is the clean-tree proof).
- Engine module has no CLI/MCP imports; the CLI is a thin wrapper (same pattern as `ticketlint.py` / `cli.ticket_lint`).
- Exit codes: `0` PASS, `1` any `[error]`. No exit `2` (there is no staleness tier — a revision mismatch is an error). `tests/test_readme.py::test_readme_pins_the_exit_code_contract` lists the producers of exit 2; this command must not be added to that sentence.
- Output mirrors `LintReport.render()`: `[error]` / `[warn]` / `[note]` lines, every error that points at a ticket line ends with `(line N)`, last line `Grounding: PASS` or `Grounding: FAIL`. `--json` emits `LintReport.to_json()`.
- Never crash on a bad document: unreadable manifest → error naming the file; unreadable L2/L3 group file → warning naming the file and that sub-check skipped.
- Id grammar (spec §7.2 step 6): `\b(svc|db|api|int|cmd|dep|struct)\.[A-Za-z0-9_][A-Za-z0-9_.-]*`. `[NEW: <reason>]` on a line exempts that line's ids (note). `Grounded on:` grammar: repo qualifier optional, same classes as `kbcontext._REF_RE`, revision `[0-9a-fA-F]{7,40}`, prefix match either way against `manifest.revision`.
- `struct.tree` L3 facts (from `codeingest/extractors/tree.py`): fence opens with `# tree, capped at depth 4`; directory lines end with `/` and carry the full relative path; file lines are `<indent>- <name>` under the nearest preceding directory line with a smaller indent; depth cap `_L3_DEPTH = 4`; line cap `_L3_MAX_LINES = 600` with marker `# … N more entries omitted from \`<first-dropped>\` onward (capped at 600 lines)`.
- L2 shapes (from the extractors): `cmd.*` → `**Primary:** \`<cmd>\`` then an optional `| Command | Source |` table; `db.<table>` → `| Column | Type | PK |` table; `api.<tag>` → `| Method | Path | Summary |` table.
- The three full SA wrappers (`claude-skill-sa-ticket-ground.md`, `copilot-sa-ticket-ground.prompt.md`, `cursor-sa-ticket-ground.md`) must stay byte-identical after the frontmatter (`tests/test_sa_ticket_ground.py`) — any edit is applied to all three.
- Before editing `LintReport.render` or `ticket_app`: run `mcp__gitnexus__impact` (upstream) — `render` is called from `cli.ticket_lint`, `cli.mission_lint` (defaulted new parameter, additive); `ticket_app` gains one command (additive). Run `mcp__gitnexus__detect_changes({scope:"all"})` before the final commit (CLAUDE.md).
- Windows dev box: Python `.venv/Scripts/python.exe`; commit messages via `git commit -F <file>` (write the file under the plan workspace, never `/tmp`); repo hooks refuse `grep`/`ls`/`find`/`git log` in Bash — use Read, `git ls-files`, `git status --short`, `git diff`; full suite ~17 min — run it once in the last task, scoped suites elsewhere.

---

## File map

| File | Action | Task |
|---|---|---|
| `src/strata_kb/lintcore.py` | `LintReport.render(self, label: str = "DoR")` | 1 |
| `src/strata_kb/ticketcheck.py` | create: constants, `LoadedDoc`, `DocLoadError`, `load_doc_dir`, `load_from_hub`, `check` + private checks | 1–5 |
| `tests/test_ticketcheck.py` | create: engine tests over a real `demo-code` built from `build_code_repo` | 1–4 |
| `src/strata_kb/cli.py` | `ticket_check` command on `ticket_app` (next to `ticket_lint`, ~line 2339) | 5 |
| `tests/test_cli_ticket_check.py` | create: CliRunner tests, local and hub branches | 5 |
| `README.md` §12 table, `src/strata_kb/templates/init/QUICKSTART-ba.md` CLI reference, 3 SA wrappers (drop the "no ticket check yet" hedge), `CHANGELOG.md` Unreleased bullet, spec §8 | 6 |

---

### Task 1: Engine skeleton — section, `Grounded on:`, document load, revision

**Files:**
- Modify: `src/strata_kb/lintcore.py:144-153` (`LintReport.render`)
- Create: `src/strata_kb/ticketcheck.py`
- Create: `tests/test_ticketcheck.py`

**Interfaces:**
- Produces:
  - `lintcore.LintReport.render(label: str = "DoR") -> str` — last line `f"{label}: PASS|FAIL"`.
  - `ticketcheck.HEADING = "## Technical grounding"`.
  - `ticketcheck.DocLoadError(Exception)`.
  - `ticketcheck.LoadedDoc` frozen dataclass: `manifest: models.Manifest`, `source: str`, `read_group: Callable[[str], str | None]` (group stem → L2 text), `read_raw: Callable[[str], str | None]` (group stem → L3 text).
  - `ticketcheck.load_doc_dir(doc_dir: Path, source: str) -> LoadedDoc` (raises `DocLoadError`).
  - `ticketcheck.LoadDoc = Callable[[str | None, str], LoadedDoc | None]` — `(repo_qualifier_or_None, doc_id)`; returns `None` when not found, raises `DocLoadError` when found but unreadable/ambiguous.
  - `ticketcheck.check(text: str, *, load_doc: LoadDoc, heading: str = HEADING) -> LintReport`.
  - Test helpers in `tests/test_ticketcheck.py`: fixture `code_doc` → `(kb_dir: Path, revision: str)`; `grounding(rev, **overrides) -> str`; `ticket(section: str) -> str`; `run(text, kb_dir) -> LintReport`; `errors(report)`, `warnings(report)`, `notes(report)`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_ticketcheck.py`:

```python
"""Engine tests for `kb ticket check` (`ticketcheck.check`).

Hermetic: the -code document is a REAL `demo-code` produced by
`codeingest.core.run()` over `tests/fixtures_coderepo.build_code_repo`, so
every id, column, route, command and tree path asserted here is what the
extractors actually emit (see the spec's §1 table). No hub, no network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_kb import models, ticketcheck
from strata_kb.codeingest import core
from strata_kb.lintcore import LintReport
from tests.fixtures_coderepo import build_code_repo


@pytest.fixture
def code_doc(tmp_path: Path, run_git) -> tuple[Path, str]:
    """(kb_dir, revision) for a freshly ingested `demo-code`."""
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    kb_dir = tmp_path / "kb"
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo"
        )
    )
    manifest = models.load_yaml_model(
        kb_dir / "demo-code" / "_manifest.yaml", models.Manifest
    )
    return kb_dir, manifest.revision


DEFAULTS = {
    "Grounded on": "demo:demo-code @ {rev}",
    "Service": "svc.airspace-service",
    "Files": ["src/airspace/service.py"],
    "Tables": "db.restrictive_airspace.designation",
    "Routes": "api.airspace — GET /airspace",
    "Externals": "int.kafka",
    "Verify with": "cmd.test — `pytest -q --cov=airspace`",
    "Open decisions": ["none"],
}


def grounding(rev: str, **overrides) -> str:
    """The `## Technical grounding` body, template order, with overrides.
    A list value renders as sub-bullets; `None` drops the field."""
    fields = {**DEFAULTS, **overrides}
    out: list[str] = []
    for name, value in fields.items():
        if value is None:
            continue
        if isinstance(value, list):
            out.append(f"- {name}:")
            out.extend(f"  - {item}" for item in value)
        else:
            out.append(f"- {name}: {str(value).format(rev=rev)}")
    return "\n".join(out)


def ticket(section: str | None) -> str:
    parts = ["# T-1 — Show airspace", "", "## Summary", "Something.", ""]
    if section is not None:
        parts += ["## Technical grounding", section, ""]
    parts += ["## Open questions", "- [ ] none", ""]
    return "\n".join(parts)


def run(text: str, kb_dir: Path) -> LintReport:
    def load_doc(repo, doc):
        d = kb_dir / doc
        if not (d / "_manifest.yaml").exists():
            return None
        return ticketcheck.load_doc_dir(d, str(d))

    return ticketcheck.check(text, load_doc=load_doc)


def errors(r: LintReport) -> list[str]:
    return [i.message for i in r.issues if i.level == "error"]


def warnings(r: LintReport) -> list[str]:
    return [i.message for i in r.issues if i.level == "warning"]


def notes(r: LintReport) -> list[str]:
    return list(r.notes)


# --- Task 1: section, Grounded on, load, revision -------------------------


def test_golden_section_passes(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev)), kb_dir)
    assert errors(report) == [], report.render("Grounding")
    assert report.passed is True
    assert any("demo-code read from" in n for n in notes(report))


def test_missing_section_is_an_error(code_doc):
    kb_dir, _ = code_doc
    report = run(ticket(None), kb_dir)
    assert report.passed is False
    assert errors(report) == ["missing '## Technical grounding' — run /sa-ticket-ground"]


def test_missing_grounded_on_stops_with_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, **{"Grounded on": None})), kb_dir)
    assert report.passed is False
    assert len(errors(report)) == 1
    assert "Grounded on:" in errors(report)[0]


def test_malformed_grounded_on_names_the_expected_shape(code_doc):
    kb_dir, _ = code_doc
    report = run(ticket(grounding("x", **{"Grounded on": "demo-code (rev abc1234)"})), kb_dir)
    assert len(errors(report)) == 1
    assert "<repo-id>:<doc-id> @ <revision>" in errors(report)[0]
    assert "(line 7)" in errors(report)[0]


def test_unknown_document_is_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, **{"Grounded on": "other:other-code @ {rev}"})), kb_dir)
    assert len(errors(report)) == 1
    assert "other-code" in errors(report)[0]
    assert "not found" in errors(report)[0]


def test_unreadable_manifest_is_an_error_not_a_traceback(code_doc):
    kb_dir, rev = code_doc
    (kb_dir / "demo-code" / "_manifest.yaml").write_text("id: [broken", encoding="utf-8")
    report = run(ticket(grounding(rev)), kb_dir)
    assert len(errors(report)) == 1
    assert "could not read" in errors(report)[0]
    assert "_manifest.yaml" in errors(report)[0]


def test_revision_mismatch_is_stale_grounding(code_doc):
    kb_dir, _ = code_doc
    report = run(ticket(grounding("deadbee")), kb_dir)
    assert any("stale grounding" in e and "deadbee" in e for e in errors(report))


def test_long_revision_prefix_matches(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev + "0" * (40 - len(rev)))), kb_dir)
    assert not any("stale grounding" in e for e in errors(report))


def test_empty_manifest_revision_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    path = kb_dir / "demo-code" / "_manifest.yaml"
    m = models.load_yaml_model(path, models.Manifest)
    m.revision = ""
    models.save_yaml_model(path, m)
    report = run(ticket(grounding(rev)), kb_dir)
    assert not any("stale grounding" in e for e in errors(report))
    assert any("no revision" in w for w in warnings(report))


def test_render_label_defaults_to_dor_and_accepts_grounding():
    r = LintReport(issues=[])
    assert r.render().endswith("DoR: PASS")
    assert r.render("Grounding").endswith("Grounding: PASS")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ticketcheck.py -q`
Expected: `ImportError: cannot import name 'ticketcheck'` (collection error).

- [ ] **Step 3: `LintReport.render` label** — in `src/strata_kb/lintcore.py` replace the method:

```python
    def render(self, label: str = "DoR") -> str:
        """Mirror `kb doctor`'s output style: one '[error]'/'[warn]'/'[note]'
        line per item, final line '<label>: PASS' or '<label>: FAIL'.
        `label` defaults to the DoR gates' wording; `kb ticket check`
        passes "Grounding"."""
        lines = [
            f"[{'error' if i.level == 'error' else 'warn'}] {i.message}"
            for i in self.issues
        ]
        lines += [f"[note] {note}" for note in self.notes]
        lines.append(f"{label}: {'PASS' if self.passed else 'FAIL'}")
        return "\n".join(lines)
```

- [ ] **Step 4: Create `src/strata_kb/ticketcheck.py`** (Task 1 slice — later tasks add the private checks named in `check()`'s body, so leave the marked call sites in place):

```python
"""`kb ticket check` engine — the SA grounding gate.

Verifies a ticket's `## Technical grounding` section (spec
2026-09-20-sa-grounding-design §3/§7) against the real `<repo>-code`
document: every `svc.* / db.* / api.* / int.* / cmd.*` id must exist in the
document's `_manifest.yaml` (or carry `[NEW: <reason>]`), columns / routes /
commands must match the document's own L2 tables, `Files:` must be listed in
`struct.tree`, and `Open decisions` must be empty.

No CLI/MCP imports here — `cli.py`'s `kb ticket check` is a thin wrapper, the
same split `ticketlint.py` has. Where the document comes from (local
`.kb/` or the hub federation) is the caller's `load_doc` callable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml
from pydantic import ValidationError

from strata_kb import lintcore, models
from strata_kb.doctor import Issue
from strata_kb.lintcore import LintReport
from strata_kb.mdutils import slice_section

HEADING = "## Technical grounding"

# `- Grounded on: [<repo>:]<doc> @ <rev>` — repo/doc classes as in
# kbcontext._REF_RE; rev is a 7..40 hex commit (core.run() writes 7).
GROUNDED_ON_RE = re.compile(
    r"^-\s*Grounded on:\s*"
    r"(?:(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*):)?"
    r"(?P<doc>[A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*(?P<rev>[0-9a-fA-F]{7,40})\s*$"
)
ID_RE = re.compile(r"\b(?:svc|db|api|int|cmd|dep|struct)\.[A-Za-z0-9_][A-Za-z0-9_.-]*")
NEW_RE = re.compile(r"\[NEW(?::\s*(?P<reason>[^\]]*))?\]")
ROUTE_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S*)")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
# A top-level field line: `- Files:`, `- Verify with: ...` (column 0 only —
# sub-items are indented and may themselves contain a colon).
FIELD_RE = re.compile(r"^-\s*(?P<field>[A-Za-z][A-Za-z ]*?):\s*(?P<rest>.*)$")
SUBITEM_RE = re.compile(r"^\s+-\s*(?P<text>.*\S)\s*$")
PRIMARY_RE = re.compile(r"\*\*Primary:\*\*\s*`([^`]*)`")
TREE_CAP_RE = re.compile(r"^# … \d+ more entr(?:y|ies) omitted from `(?P<first>[^`]*)` onward")
TREE_DEPTH = 4  # codeingest.extractors.tree._L3_DEPTH

_NONE_WORDS = frozenset({"none", "n/a", "-"})


class DocLoadError(Exception):
    """The -code document exists but cannot be used: unreadable manifest,
    or the same doc id published by several repos with no qualifier."""


@dataclass(frozen=True)
class LoadedDoc:
    manifest: models.Manifest
    source: str  # human label for the [note] line, e.g. ".kb/demo-code"
    read_group: Callable[[str], str | None]  # group stem -> L2 text
    read_raw: Callable[[str], str | None]    # group stem -> L3 text


LoadDoc = Callable[[str | None, str], LoadedDoc | None]


def load_doc_dir(doc_dir: Path, source: str) -> LoadedDoc:
    manifest_path = doc_dir / "_manifest.yaml"
    try:
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
    except (yaml.YAMLError, OSError, UnicodeDecodeError, ValidationError) as exc:
        raise DocLoadError(f"could not read {manifest_path} ({exc})") from exc

    def _read(name: str) -> str | None:
        try:
            return (doc_dir / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    return LoadedDoc(
        manifest=manifest,
        source=source,
        read_group=lambda group: _read(f"{group}.md"),
        read_raw=lambda group: _read(f"{group}.raw.md"),
    )


# ---------------------------------------------------------------------------
# section parsing
# ---------------------------------------------------------------------------


@dataclass
class _Section:
    first_line: int                     # 1-based ticket line of the body's first line
    lines: list[str]                    # visible body lines (HTML comments blanked)
    field_of_line: list[str | None]     # the `- <Field>:` a line belongs to
    subitems: dict[str, list[tuple[int, str]]]  # field -> [(lineno, text)]


def _heading_line_index(text: str, heading: str) -> int:
    """0-based index of the heading line, judged on the same blanked view
    `lintcore.section_body` uses (a fenced/commented heading never counts)."""
    scan = lintcore._blank_invisible(text).splitlines()
    for i, line in enumerate(scan):
        if line.strip() == heading:
            return i
    return -1


def _parse_section(text: str, heading: str) -> _Section | None:
    body = lintcore.section_body(text, heading)
    if body is None:
        return None
    first_line = _heading_line_index(text, heading) + 2
    blanked = lintcore.HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), body)
    lines = blanked.splitlines()
    field_of_line: list[str | None] = []
    subitems: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    for i, line in enumerate(lines):
        if line and not line[0].isspace():
            m = FIELD_RE.match(line)
            current = m.group("field").strip() if m else None
        elif current is not None:
            m = SUBITEM_RE.match(line)
            if m:
                subitems.setdefault(current, []).append((first_line + i, m.group("text")))
        field_of_line.append(current)
    return _Section(first_line, lines, field_of_line, subitems)


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def check(text: str, *, load_doc: LoadDoc, heading: str = HEADING) -> LintReport:
    issues: list[Issue] = []
    notes: list[str] = []
    section = _parse_section(text, heading)
    if section is None:
        issues.append(Issue("error", f"missing '{heading}' — run /sa-ticket-ground"))
        return LintReport(issues, notes)

    grounded = _grounded_on(section, issues)
    if grounded is None:
        return LintReport(issues, notes)
    repo, doc_id, rev = grounded

    try:
        doc = load_doc(repo, doc_id)
    except DocLoadError as exc:
        issues.append(Issue("error", str(exc)))
        return LintReport(issues, notes)
    if doc is None:
        where = f"repo '{repo}'" if repo else "any repo"
        issues.append(
            Issue(
                "error",
                f"{doc_id} not found under --kb-dir or on the hub ({where}) — "
                "is the -code document published, and is the id spelled as "
                "`<repo-id>-code`?",
            )
        )
        return LintReport(issues, notes)
    notes.append(f"{doc_id} read from {doc.source}")

    _check_revision(doc, doc_id, rev, issues)
    # Task 2 adds:  _check_ids(section, doc, issues, notes)
    # Task 2 adds:  _check_service_present(section, issues)
    # Task 2 adds:  _check_open_decisions(section, issues)
    # Task 3 adds:  _check_tables_routes_commands(section, doc, issues)
    # Task 4 adds:  _check_files(section, doc, issues, notes)
    return LintReport(issues, notes)


def _grounded_on(section: _Section, issues: list[Issue]) -> tuple[str | None, str, str] | None:
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] != "Grounded on" or line[:1].isspace():
            continue
        m = GROUNDED_ON_RE.match(line.strip())
        if m is None:
            issues.append(
                Issue(
                    "error",
                    "'Grounded on:' must read `Grounded on: <repo-id>:<doc-id> @ "
                    f"<revision>` (revision = the -code manifest's `revision`) "
                    f"(line {section.first_line + i})",
                )
            )
            return None
        return m.group("repo"), m.group("doc"), m.group("rev").lower()
    issues.append(
        Issue(
            "error",
            "missing 'Grounded on: <repo-id>:<doc-id> @ <revision>' — the first "
            "line of the section; copy the revision from the -code manifest",
        )
    )
    return None


def _check_revision(doc: LoadedDoc, doc_id: str, rev: str, issues: list[Issue]) -> None:
    have = (doc.manifest.revision or "").lower()
    if not have:
        issues.append(
            Issue("warning", f"{doc_id} has no revision in its manifest — grounding revision not verified")
        )
        return
    if not (have.startswith(rev) or rev.startswith(have)):
        issues.append(
            Issue(
                "error",
                f"stale grounding: ticket says @{rev}, {doc_id} is @{have} — "
                "re-run /sa-ticket-ground against the current document",
            )
        )
```

- [ ] **Step 5: Run the Task 1 tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ticketcheck.py -q`
Expected: all 10 PASS (the golden test passes at this stage because no deep check exists yet — later tasks keep it green).

Also: `.venv/Scripts/python.exe -m pytest tests/test_ticketlint.py tests/test_cli_ticket.py tests/test_cli_mission.py -q -k "golden or render or lint_"` → PASS (render default unchanged).

- [ ] **Step 6: Commit**

```bash
printf '%s\n' 'feat(ticketcheck): engine skeleton — Grounded on, document load, revision check' > .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg1.txt
git add src/strata_kb/lintcore.py src/strata_kb/ticketcheck.py tests/test_ticketcheck.py
git commit -F .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg1.txt
```

---

### Task 2: Id scan, `[NEW:]`, `Service:` presence, `Open decisions`

**Files:**
- Modify: `src/strata_kb/ticketcheck.py` (add three functions, wire the three Task-2 call sites in `check()`)
- Modify: `tests/test_ticketcheck.py` (append)

**Interfaces:**
- Consumes: `_Section`, `LoadedDoc`, `ID_RE`, `NEW_RE`, `_NONE_WORDS` from Task 1.
- Produces: `_known_ids(doc) -> set[str]`; `_check_ids(section, doc, issues, notes)`; `_check_service_present(section, issues)`; `_check_open_decisions(section, issues)`; `_id_lines(section)` iterator of `(lineno, line)` for lines that are id-scanned (everything except `Grounded on` and `Files` lines) — Task 3 reuses it.

- [ ] **Step 1: Append the failing tests**

```python
# --- Task 2: ids, [NEW], Service, Open decisions ---------------------------


def test_unknown_ids_are_errors_with_line_numbers(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(
        rev,
        Service="svc.nope",
        Tables="db.ghost.col",
        Routes="api.missing",
        Externals="int.unknown",
    ))
    report = run(text, kb_dir)
    msgs = errors(report)
    for bad, line in (("svc.nope", 8), ("db.ghost", 11), ("api.missing", 12), ("int.unknown", 13)):
        assert any(f"unknown id '{bad}'" in m and f"(line {line})" in m for m in msgs), (bad, msgs)


def test_new_marker_exempts_the_line_and_emits_a_note(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Externals="int.stripe [NEW: billing arrives with this ticket]"))
    report = run(text, kb_dir)
    assert not any("int.stripe" in e for e in errors(report))
    assert any("new: int.stripe — billing arrives with this ticket" in n for n in notes(report))


def test_new_marker_without_a_reason_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Externals="int.stripe [NEW]")), kb_dir)
    assert not any("int.stripe" in e for e in errors(report))
    assert any("[NEW] without a reason" in w for w in warnings(report))


def test_ids_inside_file_paths_are_not_scanned(code_doc):
    # `src/api.py` must not be read as the id `api.py`.
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Files=["src/api.py [NEW: new module]"])), kb_dir)
    assert not any("api.py" in e for e in errors(report))


def test_missing_service_line_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Service="none")), kb_dir)
    assert any("no `svc.<name>`" in w for w in warnings(report))


def test_open_decisions_fail_the_gate_one_error_each_plus_summary(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, **{"Open decisions": [
        "Failure mode: what if Kafka is down during approval?",
        "Request body of POST /airspace",
    ]}))
    report = run(text, kb_dir)
    assert report.passed is False
    msgs = errors(report)
    assert any("open decision: Failure mode: what if Kafka is down" in m and "(line 16)" in m for m in msgs)
    assert any("open decision: Request body of POST /airspace" in m and "(line 17)" in m for m in msgs)
    assert "2 open decision(s) — resolve before Dev" in msgs


def test_open_decisions_none_variants_pass(code_doc):
    kb_dir, rev = code_doc
    for word in ("none", "None", "N/A", "n/a"):
        report = run(ticket(grounding(rev, **{"Open decisions": [word]})), kb_dir)
        assert not any("open decision" in e for e in errors(report)), word


def test_inline_open_decision_counts_too(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, **{"Open decisions": "retry policy unknown"})), kb_dir)
    assert any("open decision: retry policy unknown" in e for e in errors(report))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ticketcheck.py -q -k "unknown_ids or new_marker or file_paths or service_line or open_decision"`
Expected: FAILED (no errors/warnings produced yet).

- [ ] **Step 3: Implement** — add to `ticketcheck.py` after `_check_revision`, and replace the three `# Task 2 adds:` comments in `check()` with the real calls (order: `_check_ids`, `_check_service_present`, `_check_open_decisions`):

```python
def _known_ids(doc: LoadedDoc) -> set[str]:
    return {s.id for s in doc.manifest.sections}


def _id_lines(section: _Section):
    """(lineno, line) for every visible line that is scanned for ids — the
    `Grounded on:` line (a doc id, not a section id) and `Files:` lines
    (paths such as `src/api.py` would read as `api.py`) are skipped."""
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] in ("Grounded on", "Files"):
            continue
        if line.strip():
            yield section.first_line + i, line


def _check_ids(section: _Section, doc: LoadedDoc, issues: list[Issue], notes: list[str]) -> None:
    known = _known_ids(doc)
    for lineno, line in _id_lines(section):
        new = NEW_RE.search(line)
        for raw in ID_RE.findall(line):
            sid = raw.rstrip(".")
            if sid in known:
                continue
            # db.<table>.<column>: the table half is the section id.
            if sid.startswith("db.") and sid.count(".") >= 2:
                table = sid.rsplit(".", 1)[0]
                if table in known:
                    continue  # column verified in Task 3
                sid = table
            if new is not None:
                reason = (new.group("reason") or "").strip()
                if reason:
                    notes.append(f"new: {sid} — {reason} (line {lineno})")
                else:
                    issues.append(Issue("warning", f"[NEW] without a reason for {sid} (line {lineno})"))
                continue
            issues.append(
                Issue(
                    "error",
                    f"unknown id '{sid}' — not a section of {doc.manifest.id}; copy the "
                    f"id from the document or mark the line [NEW: <reason>] (line {lineno})",
                )
            )


def _check_service_present(section: _Section, issues: list[Issue]) -> None:
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Service" and any(
            sid.startswith("svc.") for sid in ID_RE.findall(line)
        ):
            return
    issues.append(Issue("warning", "no `svc.<name>` on the `Service:` line — which service does this ticket touch?"))


def _check_open_decisions(section: _Section, issues: list[Issue]) -> None:
    items: list[tuple[int, str]] = list(section.subitems.get("Open decisions", []))
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Open decisions" and not line[:1].isspace():
            rest = FIELD_RE.match(line).group("rest").strip()
            if rest:
                items.insert(0, (section.first_line + i, rest))
    open_items = [(n, t) for n, t in items if t.strip().casefold() not in _NONE_WORDS]
    for lineno, item in open_items:
        issues.append(Issue("error", f"open decision: {item} (line {lineno})"))
    if open_items:
        issues.append(Issue("error", f"{len(open_items)} open decision(s) — resolve before Dev"))
```

- [ ] **Step 4: Run the file**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ticketcheck.py -q`
Expected: all PASS, including the Task 1 golden test (the golden `Files` line is skipped by `_id_lines`; `db.restrictive_airspace.designation` resolves to its table; `cmd.test`/`api.airspace`/`int.kafka`/`svc.airspace-service` are all manifest ids).

- [ ] **Step 5: Commit**

```bash
printf '%s\n' 'feat(ticketcheck): id resolution, [NEW] notes, Service presence, Open decisions gate' > .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg2.txt
git add src/strata_kb/ticketcheck.py tests/test_ticketcheck.py
git commit -F .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg2.txt
```

---

### Task 3: Column, route and command checks against the document's L2 tables

**Files:**
- Modify: `src/strata_kb/ticketcheck.py` (add `_check_tables_routes_commands` + helpers; wire the Task-3 call site)
- Modify: `tests/test_ticketcheck.py` (append)

**Interfaces:**
- Consumes: `_id_lines`, `_known_ids`, `LoadedDoc.read_group`, `PRIMARY_RE`, `ROUTE_RE`, `CODE_SPAN_RE`, `lintcore.table_rows`, `mdutils.slice_section`.
- Produces: `_check_tables_routes_commands(section, doc, issues)`; `_l2_slice(doc, sid, unreadable, issues) -> str | None` (memoises "group unreadable" warnings per group in the `unreadable` set).

- [ ] **Step 1: Append the failing tests**

```python
# --- Task 3: columns, routes, commands -------------------------------------


def test_unknown_column_is_an_error_known_column_is_fine(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, Tables="db.restrictive_airspace.nope")), kb_dir)
    assert any("column 'nope'" in e and "db.restrictive_airspace" in e and "(line 11)" in e for e in errors(bad))
    good = run(ticket(grounding(rev, Tables="db.restrictive_airspace.effective_date")), kb_dir)
    assert not any("column" in e for e in errors(good))


def test_route_must_be_a_row_of_the_tag_table(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, Routes="api.airspace — DELETE /airspace")), kb_dir)
    assert any("route 'DELETE /airspace'" in e and "api.airspace" in e and "(line 12)" in e for e in errors(bad))
    good = run(ticket(grounding(rev, Routes="api.airspace — POST /airspace")), kb_dir)
    assert not any("route" in e for e in errors(good))


def test_tag_without_a_route_pair_is_accepted(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Routes="api.airspace")), kb_dir)
    assert not any("route" in e for e in errors(report))


def test_command_must_be_primary_or_an_alternative_verbatim(code_doc):
    kb_dir, rev = code_doc
    bad = run(ticket(grounding(rev, **{"Verify with": "cmd.test — `pytest -q`"})), kb_dir)
    assert any("command not in cmd.test" in e and "(line 14)" in e for e in errors(bad))
    alt = run(ticket(grounding(rev, **{"Verify with": "cmd.test — `pytest`"})), kb_dir)
    assert not any("command" in e for e in errors(alt))
    other = run(ticket(grounding(rev, **{"Verify with": "cmd.lint — `ruff check src`"})), kb_dir)
    assert not any("command" in e for e in errors(other))


def test_command_line_without_a_code_span_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, **{"Verify with": "cmd.test"})), kb_dir)
    assert any("cmd.test" in w and "backticks" in w for w in warnings(report))


def test_unreadable_group_file_degrades_to_a_warning(code_doc):
    kb_dir, rev = code_doc
    (kb_dir / "demo-code" / "db.md").write_bytes(b"\xff\xfe\x00\xd8")
    report = run(ticket(grounding(rev, Tables="db.restrictive_airspace.nope")), kb_dir)
    assert not any("column" in e for e in errors(report))
    assert any("db.md" in w and "skipped" in w for w in warnings(report))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ticketcheck.py -q -k "column or route or command or group_file"`
Expected: FAILED (no such errors yet; the no-code-span case has no warning yet).

- [ ] **Step 3: Implement** — add after `_check_open_decisions`; replace the `# Task 3 adds:` comment in `check()` with `_check_tables_routes_commands(section, doc, issues)`:

```python
def _l2_slice(doc: LoadedDoc, sid: str, unreadable: set[str], issues: list[Issue]) -> str | None:
    """The `## <sid> …` L2 section text, or None (group file unreadable —
    warned once per group, the sub-check is skipped)."""
    group = next((s.file for s in doc.manifest.sections if s.id == sid), None)
    if group is None or group in unreadable:
        return None
    text = doc.read_group(group)
    if text is None:
        unreadable.add(group)
        issues.append(
            Issue("warning", f"could not read {group}.md of {doc.manifest.id} — column/route/command checks for its sections skipped")
        )
        return None
    return slice_section(text, sid)


def _table_column(rows: list[list[str]], name: str) -> int | None:
    header = [c.strip().lower() for c in rows[0]] if rows else []
    return header.index(name) if name in header else None


def _check_tables_routes_commands(section: _Section, doc: LoadedDoc, issues: list[Issue]) -> None:
    known = _known_ids(doc)
    unreadable: set[str] = set()
    for lineno, line in _id_lines(section):
        if NEW_RE.search(line):
            continue
        ids = [i for i in ID_RE.findall(line)]
        for raw in ids:
            # db.<table>.<column>
            if raw.startswith("db.") and raw.count(".") >= 2 and raw not in known:
                table, column = raw.rsplit(".", 1)
                if table not in known:
                    continue  # reported by _check_ids
                body = _l2_slice(doc, table, unreadable, issues)
                if body is None:
                    continue
                rows = lintcore.table_rows(body)
                col = _table_column(rows, "column")
                names = {r[col] for r in rows[1:] if col is not None and len(r) > col}
                if column not in names:
                    issues.append(
                        Issue("error", f"column '{column}' is not in {table} ({', '.join(sorted(names)) or 'no columns'}) (line {lineno})")
                    )
            # api.<tag> — METHOD /path
            elif raw.startswith("api.") and raw in known:
                pairs = ROUTE_RE.findall(line)
                if not pairs:
                    continue
                body = _l2_slice(doc, raw, unreadable, issues)
                if body is None:
                    continue
                rows = lintcore.table_rows(body)
                mi, pi = _table_column(rows, "method"), _table_column(rows, "path")
                have = {(r[mi].upper(), r[pi]) for r in rows[1:] if mi is not None and pi is not None and len(r) > max(mi, pi)}
                for method, path in pairs:
                    if (method.upper(), path) not in have:
                        issues.append(
                            Issue("error", f"route '{method} {path}' is not in {raw} — copy a row of its table (line {lineno})")
                        )
            # cmd.<x> — `command`
            elif raw.startswith("cmd.") and raw in known:
                span = CODE_SPAN_RE.search(line)
                if span is None:
                    issues.append(Issue("warning", f"{raw}: put the command in backticks so it can be verified (line {lineno})"))
                    continue
                body = _l2_slice(doc, raw, unreadable, issues)
                if body is None:
                    continue
                allowed: set[str] = set()
                m = PRIMARY_RE.search(body)
                if m:
                    allowed.add(m.group(1))
                rows = lintcore.table_rows(body)
                ci = _table_column(rows, "command")
                allowed |= {r[ci] for r in rows[1:] if ci is not None and len(r) > ci}
                if span.group(1) not in allowed:
                    issues.append(
                        Issue("error", f"command not in {raw} — copy the primary or an alternative verbatim ({', '.join(sorted(allowed))}) (line {lineno})")
                    )
```

- [ ] **Step 4: Run the file**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ticketcheck.py -q`
Expected: all PASS. (Golden: `designation` is a column; `GET /airspace` is a row; `pytest -q --cov=airspace` is the primary.)

- [ ] **Step 5: Commit**

```bash
printf '%s\n' 'feat(ticketcheck): verify columns, routes and commands against the -code L2 tables' > .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg3.txt
git add src/strata_kb/ticketcheck.py tests/test_ticketcheck.py
git commit -F .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg3.txt
```

---

### Task 4: `Files:` against `struct.tree` (depth and line caps)

**Files:**
- Modify: `src/strata_kb/ticketcheck.py` (add `_tree_paths`, `_check_files`; wire the Task-4 call site)
- Modify: `tests/test_ticketcheck.py` (append)

**Interfaces:**
- Consumes: `_Section.subitems["Files"]`, `LoadedDoc.read_raw`, `TREE_CAP_RE`, `TREE_DEPTH`, `NEW_RE`.
- Produces: `_tree_paths(l3_text) -> tuple[set[str], str | None]` (paths, first-dropped entry or None); `_check_files(section, doc, issues, notes)`.

- [ ] **Step 1: Append the failing tests**

```python
# --- Task 4: Files vs struct.tree -------------------------------------------


def test_files_present_missing_and_new(code_doc):
    kb_dir, rev = code_doc
    text = ticket(grounding(rev, Files=[
        "src/airspace/service.py",
        "db/migration/V1__create_airspace.sql",
        "src/airspace/ghost.py",
        "src/airspace/approval.py [NEW: created by this ticket]",
    ]))
    report = run(text, kb_dir)
    msgs = errors(report)
    assert any("file 'src/airspace/ghost.py' not in struct.tree" in m and "(line 12)" in m for m in msgs)
    assert not any("service.py" in m or "V1__create" in m for m in msgs)
    assert any("new: src/airspace/approval.py — created by this ticket" in n for n in notes(report))


def test_directory_entries_count_as_paths(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Files=["src/airspace", "db/migration/"])), kb_dir)
    assert not any("not in struct.tree" in e for e in errors(report))


def test_path_beyond_depth_cap_is_a_warning_not_an_error(code_doc):
    kb_dir, rev = code_doc
    report = run(ticket(grounding(rev, Files=["src/airspace/deep/deeper/x.py"])), kb_dir)
    assert not any("not in struct.tree" in e for e in errors(report))
    assert any("cannot verify 'src/airspace/deep/deeper/x.py'" in w and "depth" in w for w in warnings(report))


def test_path_after_the_line_cap_marker_is_a_warning(tmp_path: Path, run_git):
    root = tmp_path / "repo"
    root.mkdir()
    build_code_repo(root)
    wide = root / "wide"
    wide.mkdir()
    for n in range(700):  # 700 files > _L3_MAX_LINES=600 → the tree is capped
        (wide / f"f{n:04d}.txt").write_text("x", encoding="utf-8")
    run_git(root, "init")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "init")
    kb_dir = tmp_path / "kb"
    core.run(core.CodeIngestOptions(repo_root=root, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo"))
    rev = models.load_yaml_model(kb_dir / "demo-code" / "_manifest.yaml", models.Manifest).revision
    raw = (kb_dir / "demo-code" / "structure.raw.md").read_text(encoding="utf-8")
    assert "more entries omitted" in raw  # precondition: the cap fired
    report = run(ticket(grounding(rev, Files=["wide/f0699.txt", "wide/f0000.txt", "aaa.txt"])), kb_dir)
    # The listing is truncated, so an absent path can never be proven absent:
    # f0699 (past the cut) and aaa.txt (would sort before it, but the marker
    # names a bare file name, so order is not comparable) are both warnings;
    # f0000 is listed → ok. No false errors on a capped tree.
    assert any("cannot verify 'wide/f0699.txt'" in w and "line cap" in w for w in warnings(report))
    assert any("cannot verify 'aaa.txt'" in w and "line cap" in w for w in warnings(report))
    assert not any("f0000" in e for e in errors(report))
    assert not any("not in struct.tree" in e for e in errors(report))


def test_missing_structure_raw_is_a_warning(code_doc):
    kb_dir, rev = code_doc
    (kb_dir / "demo-code" / "structure.raw.md").unlink()
    report = run(ticket(grounding(rev)), kb_dir)
    assert not any("struct.tree" in e for e in errors(report))
    assert any("structure.raw.md" in w and "file checks skipped" in w for w in warnings(report))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ticketcheck.py -q -k "files_present or directory_entries or depth_cap or line_cap or structure_raw"`
Expected: FAILED.

- [ ] **Step 3: Implement** — add after `_check_tables_routes_commands`; replace the `# Task 4 adds:` comment in `check()` with `_check_files(section, doc, issues, notes)`:

```python
def _tree_paths(l3_text: str) -> tuple[set[str], str | None]:
    """(every path listed in struct.tree's fence, first entry dropped by the
    line cap or None). Directory lines end with `/` and carry their full
    relative path; a file line's directory is the nearest preceding
    directory line with a smaller indent (root files have none)."""
    paths: set[str] = set()
    first_dropped: str | None = None
    stack: list[tuple[int, str]] = []
    in_fence = False
    for raw in l3_text.splitlines():
        if raw.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        cap = TREE_CAP_RE.match(raw)
        if cap:
            first_dropped = cap.group("first")
            continue
        m = re.match(r"^( *)- (.+)$", raw)
        if not m:
            continue
        indent, name = len(m.group(1)), m.group(2)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if name.endswith("/"):
            d = name[:-1]
            stack.append((indent, d))
            paths.add(d)
        else:
            parent = stack[-1][1] if stack else ""
            paths.add(f"{parent}/{name}" if parent else name)
    return paths, first_dropped


def _check_files(section: _Section, doc: LoadedDoc, issues: list[Issue], notes: list[str]) -> None:
    entries = section.subitems.get("Files", [])
    if not entries:
        return
    group = next((s.file for s in doc.manifest.sections if s.id == "struct.tree"), None)
    raw = doc.read_raw(group) if group else None
    if raw is None:
        issues.append(
            Issue("warning", f"could not read {group or 'structure'}.raw.md of {doc.manifest.id} — file checks skipped")
        )
        return
    paths, first_dropped = _tree_paths(raw)
    for lineno, text in entries:
        new = NEW_RE.search(text)
        path = NEW_RE.sub("", text).strip().strip("`").rstrip("/")
        if new is not None:
            reason = (new.group("reason") or "").strip()
            if reason:
                notes.append(f"new: {path} — {reason} (line {lineno})")
            else:
                issues.append(Issue("warning", f"[NEW] without a reason for {path} (line {lineno})"))
            continue
        if path in paths:
            continue
        if path.count("/") >= TREE_DEPTH:
            issues.append(
                Issue("warning", f"cannot verify '{path}': beyond struct.tree's depth cap ({TREE_DEPTH}) — list the deepest directory the document shows (line {lineno})")
            )
        elif first_dropped is not None:
            # ponytail: the cap marker names a bare file name, so "does this
            # path sort after the cut" is not decidable from the document;
            # a capped tree makes every absent path unverifiable, never an
            # error. Upgrade path: a full-path marker in tree.py's renderer.
            issues.append(
                Issue("warning", f"cannot verify '{path}': struct.tree hit its line cap (listing stops at '{first_dropped}') — the document cannot prove absence (line {lineno})")
            )
        else:
            issues.append(
                Issue("error", f"file '{path}' not in struct.tree of {doc.manifest.id} — spell it as the document lists it, or mark [NEW: <reason>] (line {lineno})")
            )
```

- [ ] **Step 4: Run the file**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ticketcheck.py -q`
Expected: all PASS. (The capped-tree test builds its own repo; the marker text is `lines[_L3_MAX_LINES].strip().removeprefix("- ")`, i.e. a bare file name such as `f0553.txt` — which is exactly why a capped tree turns every absent path into a warning rather than trying to compare order.)

- [ ] **Step 5: Commit**

```bash
printf '%s\n' 'feat(ticketcheck): verify Files against struct.tree, degrade past the depth and line caps' > .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg4.txt
git add src/strata_kb/ticketcheck.py tests/test_ticketcheck.py
git commit -F .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg4.txt
```

---

### Task 5: Hub loader + `kb ticket check` CLI command

**Files:**
- Modify: `src/strata_kb/ticketcheck.py` (add `load_from_hub`)
- Modify: `src/strata_kb/cli.py` (new command directly after `ticket_lint`, which ends ~line 2431)
- Create: `tests/test_cli_ticket_check.py`

**Interfaces:**
- Consumes: `_hub_or_exit(hub_flag, kb_dir) -> HubHandle` (cli.py:570), `HubHandle.federation_dir`, `federation.load_federation(dir) -> list[FederatedRepo]` (`.meta.repo_id`, `.kb_dir` = `federation/<repo-id>/`), `ticketcheck.check`, `load_doc_dir`.
- Produces: `ticketcheck.load_from_hub(federation_dir: Path, repo: str | None, doc: str) -> LoadedDoc | None` (raises `DocLoadError` on ambiguity); CLI `kb ticket check <file|-> [--kb-dir .kb] [--hub URL] [--json]`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_cli_ticket_check.py`:

```python
"""`kb ticket check` — the CLI wrapper over `ticketcheck.check`, both
document sources: local --kb-dir and the hub federation mirror."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from strata_kb import models
from strata_kb.cli import app
from strata_kb.federation import FederationMeta, write_federation_index
from tests.test_ticketcheck import code_doc, grounding, ticket  # noqa: F401  (fixture re-export)

runner = CliRunner()


def _publish_to_hub(fed_hub: Path, kb_dir: Path, repo_id: str, run_git) -> None:
    """Mirror `demo-code` into `fed_hub/federation/<repo_id>/` the way
    `kb publish` lays it out (full .kb mirror + _meta.yaml + index.yaml)."""
    entry = fed_hub / "federation" / repo_id
    shutil.copytree(kb_dir / "demo-code", entry / "demo-code")
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="demo-code", title="demo — code knowledge", tags=["code"])]),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id=repo_id, source_commit="abc1234", published_at="2026-09-20T00:00:00+00:00"),
    )
    write_federation_index(fed_hub / "federation")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", f"publish {repo_id}")


def test_local_kb_dir_golden_exits_0(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 0, result.output
    assert result.output.rstrip().endswith("Grounding: PASS")
    assert "[note] demo-code read from" in result.output


def test_bad_id_exits_1_and_names_it(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev, Service="svc.nope")), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 1
    assert "[error] unknown id 'svc.nope'" in result.output
    assert "(line 8)" in result.output
    assert result.output.rstrip().endswith("Grounding: FAIL")


def test_json_output_shape(code_doc, tmp_path):
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev, **{"Open decisions": ["retry policy?"]})), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir), "--json"])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["pass"] is False
    assert any("open decision: retry policy?" in e for e in data["errors"])
    assert set(data) == {"pass", "errors", "warnings", "notes"}


def test_reads_stdin(code_doc):
    kb_dir, rev = code_doc
    result = runner.invoke(app, ["ticket", "check", "-", "--kb-dir", str(kb_dir)], input=ticket(grounding(rev)))
    assert result.exit_code == 0, result.output


def test_non_utf8_file_is_a_red_line_not_a_traceback(code_doc, tmp_path):
    kb_dir, _ = code_doc
    path = tmp_path / "t.md"
    path.write_bytes(b"\xff\xfe# bad")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output


def test_hub_branch_resolves_the_document_from_the_federation(code_doc, fed_hub, run_git, tmp_path):
    kb_dir, rev = code_doc
    _publish_to_hub(fed_hub, kb_dir, "demo", run_git)
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(empty_kb), "--hub", str(fed_hub)])
    assert result.exit_code == 0, result.output
    assert "[note] demo-code read from hub federation/demo" in result.output


def test_hub_ambiguous_holders_need_a_repo_qualifier(code_doc, fed_hub, run_git, tmp_path):
    kb_dir, rev = code_doc
    _publish_to_hub(fed_hub, kb_dir, "demo", run_git)
    _publish_to_hub(fed_hub, kb_dir, "demo-fork", run_git)
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev, **{"Grounded on": "demo-code @ {rev}"})), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(empty_kb), "--hub", str(fed_hub)])
    assert result.exit_code == 1
    assert "several repos" in result.output and "demo, demo-fork" in result.output
    path.write_text(ticket(grounding(rev, **{"Grounded on": "demo-fork:demo-code @ {rev}"})), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(empty_kb), "--hub", str(fed_hub)])
    assert result.exit_code == 0, result.output
    assert "read from hub federation/demo-fork" in result.output


def test_hub_not_needed_when_the_document_is_local(code_doc, tmp_path):
    # No --hub, no config: the local branch must not call _hub_or_exit.
    kb_dir, rev = code_doc
    path = tmp_path / "t.md"
    path.write_text(ticket(grounding(rev)), encoding="utf-8")
    result = runner.invoke(app, ["ticket", "check", str(path), "--kb-dir", str(kb_dir)])
    assert result.exit_code == 0, result.output
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_ticket_check.py -q`
Expected: FAILED — typer reports `No such command 'check'` (exit code 2 in the result).

- [ ] **Step 3: `load_from_hub`** — append to `ticketcheck.py` (after `load_doc_dir`):

```python
def load_from_hub(federation_dir: Path, repo: str | None, doc: str) -> LoadedDoc | None:
    """The -code document from the hub's federation mirror. Same holder
    rule as `resolve.resolve_refs`: with a qualifier, that repo; without,
    exactly one repo may publish the doc id, otherwise the caller must
    qualify it."""
    from strata_kb.federation import load_federation

    holders = [
        r for r in load_federation(federation_dir)
        if (repo is None or r.meta.repo_id == repo)
        and (r.kb_dir / doc / "_manifest.yaml").exists()
    ]
    if not holders:
        return None
    if len(holders) > 1:
        names = ", ".join(sorted(r.meta.repo_id for r in holders))
        raise DocLoadError(
            f"{doc} is published by several repos ({names}) — qualify it: "
            f"`Grounded on: <repo-id>:{doc} @ <revision>`"
        )
    holder = holders[0]
    return load_doc_dir(holder.kb_dir / doc, f"hub federation/{holder.meta.repo_id}")
```

- [ ] **Step 4: The CLI command** — in `src/strata_kb/cli.py`, directly after the `ticket_lint` function body (it ends with `raise typer.Exit(2 if report.stale_errors == errors else 1)`), add:

```python
@ticket_app.command("check")
def ticket_check(
    source: str = typer.Argument(
        ..., help="Ticket file (or '-' to read from stdin)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "",
        "--hub",
        envvar="STRATA_KB_HUB",
        help="kb-hub URL/path (empty = config); consulted only when the "
        "-code document is not under --kb-dir",
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
) -> None:
    """SA grounding gate: every id in '## Technical grounding' exists in the
    -code document, columns/routes/commands/files match it, and Open
    decisions is empty. Exit 0 PASS, 1 FAIL."""
    from strata_kb import ticketcheck

    if source == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(source).read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.secho(
                f"file '{source}' is not valid UTF-8: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)

    def load_doc(repo: str | None, doc: str) -> ticketcheck.LoadedDoc | None:
        # Local first (a dev machine, or the hub's own checkout): the BA repo
        # never has a -code document locally, so it always falls through to
        # the hub — which is the point, the SA grounded on the hub copy.
        local = kb_dir / doc
        if (local / "_manifest.yaml").exists():
            return ticketcheck.load_doc_dir(local, str(local))
        handle = _hub_or_exit(hub, kb_dir)
        return ticketcheck.load_from_hub(handle.federation_dir, repo, doc)

    report = ticketcheck.check(text, load_doc=load_doc)
    if json_output:
        typer.echo(json.dumps(report.to_json()))
    else:
        typer.echo(report.render("Grounding"))
    if not report.passed:
        raise typer.Exit(1)
```

- [ ] **Step 5: Run both CLI suites**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_ticket_check.py tests/test_cli_ticket.py tests/test_ticketcheck.py -q`
Expected: all PASS. If `test_hub_branch_resolves_the_document_from_the_federation` fails on `_hub_or_exit` requiring `.kb/config.yaml`: `--hub <path>` is the flag branch of `require_hub` and needs no config — check `result.output` for the real message before changing anything.

- [ ] **Step 6: Commit**

```bash
printf '%s\n' 'feat(cli): kb ticket check — SA grounding gate over local .kb or the hub federation' > .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg5.txt
git add src/strata_kb/ticketcheck.py src/strata_kb/cli.py tests/test_cli_ticket_check.py
git commit -F .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg5.txt
```

---

### Task 6: Docs, SA-wrapper hedge removal, CHANGELOG, graph check, full suite

**Files:**
- Modify: `README.md` §12 command table (after the `kb mission lint` row, ~line 684) and the sentence after it
- Modify: `src/strata_kb/templates/init/QUICKSTART-ba.md` "## CLI reference" (after the `kb mission lint` bullet, ~line 378)
- Modify: `src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md`, `copilot-sa-ticket-ground.prompt.md`, `cursor-sa-ticket-ground.md` (Gate step, identical edit ×3)
- Modify: `CHANGELOG.md` (`## Unreleased` last bullet)
- Modify: `docs/superpowers/specs/2026-09-20-sa-grounding-design.md` §8 (PR 2 line → shipped)
- Test: `tests/test_readme.py`, `tests/test_sa_ticket_ground.py`, `tests/test_templates.py`, `tests/test_init.py`

**Interfaces:** none new.

- [ ] **Step 1: Failing test for the docs** — append to `tests/test_cli_ticket_check.py`:

```python
def test_docs_name_the_check_command():
    from importlib import resources
    from pathlib import Path as _P

    readme = (_P(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    assert "`kb ticket check <file\\|-> [--kb-dir <dir>] [--hub <url>] [--json]`" in readme
    quick = resources.files("strata_kb").joinpath("templates/init/QUICKSTART-ba.md").read_text(encoding="utf-8")
    assert "- `kb ticket check <file> [--hub <url>]`" in quick
    for name in ("claude-skill-sa-ticket-ground.md", "copilot-sa-ticket-ground.prompt.md", "cursor-sa-ticket-ground.md"):
        text = resources.files("strata_kb").joinpath(f"templates/init/{name}").read_text(encoding="utf-8")
        assert "has no `ticket check` command yet" not in text, name
    changelog = (_P(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "follows in a\n  separate PR" not in changelog
    assert "`kb ticket check <file>`" in changelog
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_ticket_check.py -q -k docs_name`
Expected: FAILED on the README row.

- [ ] **Step 3: README §12** — add this row after the `kb mission lint` row:

```markdown
| `kb ticket check <file\|-> [--kb-dir <dir>] [--hub <url>] [--json]` | SA grounding gate: every `svc.* / db.* / api.* / int.* / cmd.*` id in `## Technical grounding` exists in the `<repo>-code` document (local `--kb-dir` first, hub federation second), `Grounded on:` matches the document's revision, columns / routes / commands match its tables, `Files:` are in `struct.tree`, and `Open decisions` is empty | `0` PASS, `1` FAIL |
```

Then change the sentence below the table from `Mission lint is deliberately **CLI-only** — …` to `Mission lint and ticket check are deliberately **CLI-only** — mission lint's distinguishing checks need filesystem access to the sibling \`tickets/\` directory that a shared MCP server does not have, and ticket check's local-first document lookup reads \`--kb-dir\`. \`kb_ticket_lint\` remains the only lint tool over MCP.` Do **not** touch the exit-code sentence `tests/test_readme.py` pins (it lists exit-2 producers; this command adds none).

- [ ] **Step 4: QUICKSTART-ba CLI reference** — after the `kb mission lint` bullet add:

```markdown
- `kb ticket check <file> [--hub <url>]` — run the SA grounding gate: every
  id in `## Technical grounding` must exist in the hub's `<repo>-code`
  document and `Open decisions` must be empty (`Grounding: PASS`)
```

- [ ] **Step 5: SA wrappers — drop the hedge, identically in all three.** In the Gate step replace

```
   report the list to the BA instead of emptying it by guessing. If the
   installed `kb` has no `ticket check` command yet, verify every id by
   hand against the document's `_manifest.yaml` section list and say in
   the handover that the gate did not run.
```

with

```
   report the list to the BA instead of emptying it by guessing.
```

(A small Python replace script with a match-exactly-once assert per file is the safest way; then `tests/test_sa_ticket_ground.py` byte-identity must stay green.)

- [ ] **Step 6: CHANGELOG** — under `## Unreleased`, replace the bullet

```
- `kb ticket check`, the machine gate for the new section, follows in a
  separate PR; until it lands the SA skill verifies ids by hand and says so.
```

with

```
- **`kb ticket check <file>`** — the machine gate for `## Technical grounding`:
  every `svc.* / db.* / api.* / int.* / cmd.*` id must exist in the
  `<repo>-code` document (read from `--kb-dir` when present, otherwise from
  the hub federation), `Grounded on: <repo-id>:<doc-id> @ <revision>` must
  match the document's manifest revision, columns / routes / commands must
  match its own tables, `Files:` must appear in `struct.tree` (paths beyond
  the depth or line cap degrade to a warning), and `Open decisions` must be
  empty. Exit `0` PASS, `1` FAIL; `--json` for CI. Every error names the
  ticket line. No MCP tool yet.
```

- [ ] **Step 7: Spec** — (a) §8, "PR 2 — `kb ticket check`" paragraph: append `Shipped 2026-09-20 as planned in docs/superpowers/plans/2026-09-20-sa-grounding-pr2-ticket-check.md.` (b) §7.2 step 10, the third outcome bullet: replace `or the fence carries the \`# … N more entries omitted\` marker and the path sorts after the named first-dropped entry → warning` with `or the fence carries the \`# … N more entries omitted\` marker (the marker names a bare file name, so order is not comparable — every absent path on a capped tree is unverifiable) → warning`.

- [ ] **Step 8: Scoped verification**

Run: `.venv/Scripts/python.exe -m pytest tests/test_cli_ticket_check.py tests/test_readme.py tests/test_sa_ticket_ground.py tests/test_templates.py tests/test_init.py -q -k "docs_name or readme or sa_ or quickstart_ba or citation_example"`
Expected: all PASS.

- [ ] **Step 9: Full suite once**

Run: `.venv/Scripts/python.exe -m pytest -q` (≈17 min; poll the output file yourself if run in the background).
Expected: all PASS; count = previous baseline + the new tests in this PR.

- [ ] **Step 10: Graph change analysis (CLAUDE.md)**

Call `mcp__gitnexus__detect_changes({scope: "all"})` (or `--scope compare --base-ref main`). Not `partial`/`truncated`; expected touched symbols: `LintReport.render`, `ticket_check`, the new `ticketcheck` module functions, doc sections. Risk low. Re-index first (`npx gitnexus analyze`) if it reports stale.

- [ ] **Step 11: Commit**

```bash
printf '%s\n' 'docs: kb ticket check in README, QUICKSTART-BA, CHANGELOG; SA wrappers drop the pre-gate hedge' > .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg6.txt
git add README.md src/strata_kb/templates/init/QUICKSTART-ba.md src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md src/strata_kb/templates/init/copilot-sa-ticket-ground.prompt.md src/strata_kb/templates/init/cursor-sa-ticket-ground.md CHANGELOG.md docs/superpowers/specs/2026-09-20-sa-grounding-design.md tests/test_cli_ticket_check.py
git commit -F .superpowers/sdd/2026-09-20-sa-grounding-pr2-ticket-check/msg6.txt
```

---

## Done when

- `.venv/Scripts/python.exe -m pytest -q` green.
- A ticket with a deliberately wrong id → `kb ticket check` exits 1 and prints `[error] unknown id '<id>' … (line N)`; the golden ticket → exit 0, last line `Grounding: PASS` (spec "Verify").
- `pyproject.toml` and `uv.lock` byte-identical to `main`.
- PR body states: no version bump; MCP tool, CI-workflow step and `kb mission check` remain follow-ups (spec §9); next step is the smoke run on strata-kb itself, then the three-ticket measurement.
