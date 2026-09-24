"""CLI tests for `kb mission lint`. Hermetic — `fed_hub` git fixture as
the hub, no network."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import kbcontext
from strata_kb.cli import app
from strata_kb.hub import HubHandle
from tests.conftest import make_stale

runner = CliRunner()

MISSION_ID = "M-airspace-filter"


def _golden_block(fed_hub: Path) -> str:
    block, _warning = kbcontext.build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3"],
        tags=["airspace"],
    )
    return block


def _golden_block_with_icao(fed_hub: Path) -> str:
    """Pins icao-kb:icao-annex-2 §1.1 alongside the usual arinc-kb ref, so
    `make_stale` (which edits the icao-kb entry) has a pinned ref of this
    mission's own context to act on. The body still only inline-cites the
    arinc-kb ref, same as `_golden_block` — the extra pin is uncited, which
    is only ever a warning (never a failure), so it cannot affect any of
    the exit-code assertions below."""
    block, _warning = kbcontext.build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"],
        tags=["airspace"],
    )
    return block


def _mission_text(block: str) -> str:
    return "\n".join(
        [
            "# Filter and display controlled airspace",
            "",
            f"> Mission: {MISSION_ID}",
            "",
            "## Summary",
            "Show controlled airspace on the planning map.",
            "",
            "## Business goal",
            "Cut briefing time. Records per arinc-kb:arinc-424 §5.3.",
            "",
            "## Scope",
            "**In scope:** rendering. **Out of scope:** editing.",
            "",
            "## System context (C4 L1)",
            "```mermaid",
            "C4Context",
            '  Person(d, "Dispatcher")',
            '  System(kb, "Knowledge Base")',
            '  Rel(d, kb, "queries")',
            "```",
            "",
            "## Containers (C4 L2)",
            "```mermaid",
            "C4Container",
            '  Container(api, "Airspace API", "Python")',
            '  Container(db, "Airspace DB", "Postgres")',
            '  Rel(api, db, "reads from")',
            "```",
            "",
            "## Constraints & assumptions",
            "None recorded.",
            "",
            "## US backlog",
            "| US ID | Title |",
            "|---|---|",
            f"| {MISSION_ID}-US1 | Render polygons |",
            "",
            "## KB context",
            f"```yaml\n{block}\n```",
            "",
            "## Definition of Ready",
            "- [ ] Backlog reviewed",
            "",
        ]
    )


@pytest.fixture
def mission_file(fed_hub: Path, tmp_path: Path) -> Path:
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_text(_mission_text(_golden_block(fed_hub)), encoding="utf-8")
    return path


def test_lint_passing_mission_exits_0(fed_hub: Path, mission_file: Path):
    result = runner.invoke(
        app, ["mission", "lint", str(mission_file), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output
    # mission_file has no missions/tickets sibling layout, so coverage is
    # skipped — assert the note actually appears rather than trusting a
    # bare PASS, which a silently-skipped check would also produce.
    assert "[note] coverage check skipped — no tickets directory supplied" in (
        result.output
    )


def test_lint_failing_mission_exits_1(fed_hub: Path, tmp_path: Path):
    path = tmp_path / f"{MISSION_ID}.md"
    text = _mission_text(_golden_block(fed_hub)).replace("## US backlog", "")
    path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app, ["mission", "lint", str(path), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 1
    assert "DoR: FAIL" in result.output


def test_lint_reads_stdin_and_notes_the_skipped_checks(
    fed_hub: Path, mission_file: Path
):
    result = runner.invoke(
        app,
        ["mission", "lint", "-", "--hub", str(fed_hub)],
        input=mission_file.read_text(encoding="utf-8"),
    )
    assert result.exit_code == 0, result.output
    assert "[note] filename check skipped" in result.output
    assert "[note] coverage check skipped" in result.output


def test_lint_json_output(fed_hub: Path, mission_file: Path):
    result = runner.invoke(
        app,
        ["mission", "lint", str(mission_file), "--hub", str(fed_hub), "--json"],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["pass"] is True
    assert data["errors"] == []
    # Pin the actual note content on the JSON surface too: `data["notes"]`
    # being non-empty here is what proves this "pass" reflects a skipped
    # coverage check, not a real one — an empty/omitted notes list would
    # let a skip masquerade as a full pass through --json.
    assert data["notes"] == [
        "coverage check skipped — no tickets directory supplied"
    ]


def test_lint_uses_sibling_tickets_dir_by_default(
    fed_hub: Path, tmp_path: Path
):
    """A mission at missions/<id>.md resolves tickets/ as its sibling, so
    the coverage check runs without the BA passing a flag."""
    (tmp_path / "missions").mkdir()
    (tmp_path / "tickets").mkdir()
    path = tmp_path / "missions" / f"{MISSION_ID}.md"
    path.write_text(_mission_text(_golden_block(fed_hub)), encoding="utf-8")

    result = runner.invoke(
        app, ["mission", "lint", str(path), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0, result.output
    assert "0/1 US drafted" in result.output
    assert "coverage check skipped" not in result.output


def test_lint_missing_file_exits_1_with_clear_error(fed_hub: Path, tmp_path: Path):
    result = runner.invoke(
        app,
        ["mission", "lint", str(tmp_path / "nope.md"), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
    assert "could not read file" in result.output


def test_explicit_tickets_dir_overrides_the_sibling(fed_hub: Path, tmp_path: Path):
    """--tickets-dir must override the sibling default, not merely
    supplement it. Both directories exist and disagree on coverage: the
    sibling has neither story drafted, the explicit dir has one of two.
    (With a single-story backlog, full coverage prints nothing at all —
    see test_missionlint.py — so two stories are needed for a visible,
    discriminating fraction.) A refactor to `sibling or tickets_dir` would
    report 0/2 here, since a Path is always truthy and `or` would pick the
    sibling regardless of what --tickets-dir was passed."""
    (tmp_path / "missions").mkdir()
    (tmp_path / "tickets").mkdir()  # sibling: empty, both stories missing
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / f"{MISSION_ID}-US1.md").write_text("x", encoding="utf-8")

    text = _mission_text(_golden_block(fed_hub)).replace(
        f"| {MISSION_ID}-US1 | Render polygons |",
        f"| {MISSION_ID}-US1 | Render polygons |\n"
        f"| {MISSION_ID}-US2 | Filter by altitude |",
    )
    path = tmp_path / "missions" / f"{MISSION_ID}.md"
    path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "mission", "lint", str(path), "--hub", str(fed_hub),
            "--tickets-dir", str(elsewhere),
        ],
    )

    # 1/2 from --tickets-dir (US1 drafted there), never 0/2 from the sibling.
    assert "1/2 US drafted" in result.output, result.output
    assert "0/2 US drafted" not in result.output


def test_explicit_tickets_dir_missing_is_a_hard_error(fed_hub: Path, tmp_path: Path):
    """An explicit --tickets-dir that doesn't exist is a BA typo, not
    missing tickets — it must error out rather than silently reporting
    '0/N US drafted' via check_coverage's per-file .is_file() probing."""
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_text(_mission_text(_golden_block(fed_hub)), encoding="utf-8")
    bad_dir = tmp_path / "tikcets"  # typo, does not exist

    result = runner.invoke(
        app,
        [
            "mission", "lint", str(path), "--hub", str(fed_hub),
            "--tickets-dir", str(bad_dir),
        ],
    )

    assert result.exit_code == 1
    assert str(bad_dir) in result.output


def test_lint_non_utf8_file_names_encoding_as_the_problem(
    fed_hub: Path, tmp_path: Path
):
    """Mission/ticket bodies are explicitly UTF-8 with Vietnamese text and
    '§' characters, so a latin-1/binary file is a realistic user error —
    it must produce a red one-liner naming encoding, not a raw traceback
    (UnicodeDecodeError is a ValueError, not an OSError)."""
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_bytes(b"caf\xe9 - not valid utf-8")

    result = runner.invoke(
        app, ["mission", "lint", str(path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "utf-8" in result.output.lower()


def test_mission_lint_exits_2_when_only_the_ref_is_stale(fed_hub, tmp_path):
    block = _golden_block_with_icao(fed_hub)
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_text(_mission_text(block), encoding="utf-8")
    make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["mission", "lint", str(path), "--hub", str(fed_hub),
         "--fail-on-stale"],
    )
    assert result.exit_code == 2, result.output
    # Click also exits 2 for a usage error (e.g. an unrecognised option) —
    # pin that this 2 came from the lint report, not from `--fail-on-stale`
    # failing to parse.
    assert "DoR: FAIL" in result.output


def test_mission_lint_exits_1_when_something_else_also_fails(fed_hub, tmp_path):
    block = _golden_block_with_icao(fed_hub)
    path = tmp_path / f"{MISSION_ID}.md"
    text = _mission_text(block).replace("## US backlog", "")
    path.write_text(text, encoding="utf-8")
    make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["mission", "lint", str(path), "--hub", str(fed_hub),
         "--fail-on-stale"],
    )
    assert result.exit_code == 1


def test_mission_lint_exits_0_on_a_stale_ref_without_the_flag(fed_hub, tmp_path):
    block = _golden_block_with_icao(fed_hub)
    path = tmp_path / f"{MISSION_ID}.md"
    path.write_text(_mission_text(block), encoding="utf-8")
    make_stale(fed_hub)

    result = runner.invoke(
        app, ["mission", "lint", str(path), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0


# --- kb mission next -------------------------------------------------------

PLATFORM_NEXT = """# Platform operations
> Mission: M-platform

## US backlog
| US ID | Title |
|---|---|
| M-platform-US1 | Foundation slice |
| M-platform-US2 | Observability |

## Sequencing
| US ID | Depends on | Size | Notes |
|---|---|---|---|
| M-platform-US1 | none | L | first |
| M-platform-US2 | US1 | M | |

## Technology decisions
| # | Decision | Status | Owner | Blocks |
|---|---|---|---|---|
| D1 | New svc.airspace-service | DECIDED | lead | M-platform-US1 |

## Services & order
- Grounded on: demo:demo-code @ abc1234
"""


def _ba_layout(tmp_path: Path, *, drafted: tuple[str, ...] = ()) -> Path:
    root = tmp_path / "ba"
    (root / "missions").mkdir(parents=True)
    (root / "tickets").mkdir()
    (root / "missions" / "M-platform.md").write_text(PLATFORM_NEXT, encoding="utf-8")
    for us in drafted:
        (root / "tickets" / f"{us}.md").write_text(f"# {us}\n", encoding="utf-8")
    return root


def _svc_kb(tmp_path: Path) -> Path:
    """A dev-side .kb with demo-code AND demo-svc whose history records
    M-platform-US1 — what CI publishes to the hub after dev-handover."""
    from strata_kb import svcnote
    from strata_kb.codeingest import core
    from tests.fixtures_coderepo import build_code_repo

    repo = tmp_path / "dev"
    repo.mkdir()
    build_code_repo(repo)
    kb_dir = tmp_path / "devkb"
    core.run(core.CodeIngestOptions(
        repo_root=repo, kb_dir=kb_dir, doc_id="demo-code", repo_id="demo", scaffold_svc=True,
    ))
    svcnote.add_note(
        kb_dir, "demo", "airspace-service",
        svcnote.Note(ticket="M-platform-US1", title="Foundation slice", refs=()),
    )
    return kb_dir


def test_mission_next_local_svc_marks_done_and_names_next(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    kb_dir = _svc_kb(tmp_path)
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"), "--kb-dir", str(kb_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "| M-platform-US1 | M-platform | done |  |" in result.output
    assert "| M-platform-US2 | M-platform | ready |  |" in result.output
    assert result.output.rstrip().endswith("Next: M-platform-US2 — Observability")


def test_mission_next_without_repo_id_reports_unknown_done(tmp_path):
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    (root / "missions" / "M-platform.md").write_text(
        PLATFORM_NEXT.replace("- Grounded on: demo:demo-code @ abc1234\n", ""), encoding="utf-8"
    )
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(root / "missions")])
    assert result.exit_code == 0, result.output
    assert "note: done: unknown (no repo id — pass --repo-id)" in result.output
    assert "| M-platform-US1 | M-platform | drafted |  |" in result.output
    assert "| M-platform-US2 | M-platform | blocked | US M-platform-US1 not done |" in result.output
    assert "Next: none ready — 1 blocked, 1 drafted, 0 done" in result.output


def test_mission_next_svc_absent_on_hub_is_a_note(tmp_path, fed_hub):
    root = _ba_layout(tmp_path)
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"),
        "--kb-dir", str(empty_kb), "--hub", str(fed_hub),
    ])
    assert result.exit_code == 0, result.output
    assert "note: done: unknown (demo-svc not published" in result.output
    assert "| M-platform-US1 | M-platform | ready |  |" in result.output


def test_mission_next_no_hub_configured_is_a_note_not_a_red_line(tmp_path, monkeypatch):
    """Grounded on present, no --hub, STRATA_KB_HUB unset, no local -svc,
    and --kb-dir an empty dir (no .kb/config.yaml) — the common BA case.
    Must still exit 0 with a table, not the red line `_hub_or_exit` prints."""
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    root = _ba_layout(tmp_path)
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"), "--kb-dir", str(empty_kb),
    ])
    assert result.exit_code == 0, result.output
    assert "note: done: unknown (" in result.output
    assert "| M-platform-US1 | M-platform | ready |  |" in result.output


def test_mission_next_reads_history_from_the_hub(tmp_path, fed_hub, run_git):
    import shutil

    from strata_kb import models
    from strata_kb.federation import FederationMeta, write_federation_index

    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    kb_dir = _svc_kb(tmp_path)
    entry = fed_hub / "federation" / "demo"
    shutil.copytree(kb_dir / "demo-svc", entry / "demo-svc")
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="demo-svc", title="demo — services", tags=["code"])]),
    )
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id="demo", source_commit="abc1234", published_at="2026-09-24T00:00:00+00:00"),
    )
    write_federation_index(fed_hub / "federation")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "publish demo")
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"),
        "--kb-dir", str(empty_kb), "--hub", str(fed_hub), "--json",
    ])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["next"] == "M-platform-US2"
    assert [s["status"] for s in data["stories"]] == ["done", "ready"]
    assert data["notes"] == []


def test_mission_next_explicit_repo_id_and_tickets_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    root = _ba_layout(tmp_path)
    elsewhere = tmp_path / "drafts"
    elsewhere.mkdir()
    (elsewhere / "M-platform-US1.md").write_text("# x\n", encoding="utf-8")
    kb_dir = _svc_kb(tmp_path)
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"), "--tickets-dir", str(elsewhere),
        "--repo-id", "demo", "--kb-dir", str(kb_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "| M-platform-US1 | M-platform | done |  |" in result.output


def test_mission_next_bad_dirs_are_red_lines(tmp_path):
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "does not exist or is not a directory" in result.output
    root = _ba_layout(tmp_path)
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"), "--tickets-dir", str(tmp_path / "nope"),
    ])
    assert result.exit_code == 1
    assert "does not exist or is not a directory" in result.output


def test_mission_next_unreadable_mission_is_skipped_with_a_note(tmp_path):
    root = _ba_layout(tmp_path)
    # No `Grounded on:` line, so no repo id is derived and the hub is never
    # consulted — this test has no hub and no --kb-dir with a -svc document.
    (root / "missions" / "M-platform.md").write_text(
        PLATFORM_NEXT.replace("- Grounded on: demo:demo-code @ abc1234\n", ""), encoding="utf-8"
    )
    (root / "missions" / "M-bad.md").write_bytes(b"\xff\xfe# bad")
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(root / "missions")])
    assert result.exit_code == 0, result.output
    assert "note: skipped" in result.output and "M-bad.md" in result.output
    assert "| M-platform-US1 |" in result.output


def test_mission_next_no_mission_line_is_skipped_with_a_note(tmp_path):
    root = _ba_layout(tmp_path)
    # No `Grounded on:` line, so no repo id is derived and the hub is never
    # consulted — this test has no hub and no --kb-dir with a -svc document.
    (root / "missions" / "M-platform.md").write_text(
        PLATFORM_NEXT.replace("- Grounded on: demo:demo-code @ abc1234\n", ""), encoding="utf-8"
    )
    (root / "missions" / "notes.md").write_text("# Notes\n\nfree text\n", encoding="utf-8")
    result = runner.invoke(app, ["mission", "next", "--missions-dir", str(root / "missions")])
    assert result.exit_code == 0, result.output
    assert "note: skipped" in result.output and "notes.md" in result.output
    assert "no '> Mission:' line" in result.output
    assert "| M-platform-US1 |" in result.output


def test_docs_name_the_next_command():
    from pathlib import Path as _P

    root = _P(__file__).resolve().parents[1]
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "| `kb mission next` | Which story next: done / drafted / ready / blocked across `missions/`, done derived from the hub's `<repo>-svc` history |" in readme
    assert "`kb mission next [--missions-dir <dir>] [--tickets-dir <dir>] [--repo-id <id>] [--kb-dir <dir>] [--hub <url>] [--json]`" in readme
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    assert changelog.index("## Unreleased") < changelog.index("## 1.3.0")
    assert "`kb mission next`" in changelog
    assert "`--kb-dir` is read first when it holds the `-svc` document (a dev machine), the hub second" in readme
    assert "derived from the grounded `-code` document" in changelog


def test_mission_next_nested_repo_id_derives_the_svc_doc_from_the_code_doc(tmp_path, fed_hub):
    root = _ba_layout(tmp_path)
    (root / "missions" / "M-platform.md").write_text(
        PLATFORM_NEXT.replace("demo:demo-code @ abc1234", "mid/repo-x:repo-x-code @ abc1234"),
        encoding="utf-8",
    )
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"),
        "--kb-dir", str(empty_kb), "--hub", str(fed_hub),
    ])
    assert result.exit_code == 0, result.output
    # the doc id is repo-x-svc, never mid/repo-x-svc
    assert "note: done: unknown (repo-x-svc not published" in result.output
    assert "mid/repo-x-svc" not in result.output


def test_mission_next_unqualified_grounded_on_resolves_locally(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    (root / "missions" / "M-platform.md").write_text(
        PLATFORM_NEXT.replace("demo:demo-code @ abc1234", "demo-code @ abc1234"), encoding="utf-8"
    )
    kb_dir = _svc_kb(tmp_path)
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"), "--kb-dir", str(kb_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "| M-platform-US1 | M-platform | done |  |" in result.output
    assert "done: unknown" not in result.output
