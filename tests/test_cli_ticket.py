"""Tests for `kb ticket lint` — the CLI wrapper over `ticketlint.lint`.

Hermetic: reuses the `fed_hub` fixture (conftest.py) and the ticket-building
helpers from test_ticketlint.py — no network, no live hub, no LLM.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from strata_kb import gitio, kbcontext
from strata_kb.cli import app
from tests.conftest import make_stale
from tests.test_ticketlint import REFS, _build_ticket, _hub

runner = CliRunner()


def _golden_block(fed_hub: Path) -> str:
    block, warning = kbcontext.build_context_block(
        _hub(fed_hub), REFS, tags=["airspace"]
    )
    assert warning is None
    return block


def _broken_ref_ticket(fed_hub: Path, block: str) -> str:
    rev = gitio.head_commit(gitio.git_root(fed_hub))
    bad_block = (
        f"kb-context:\n  version: {rev}\n  refs:\n    - arinc-kb:arinc-424 §9.9\n"
    )
    return _build_ticket(
        block,
        overrides={
            "## KB context": f"```yaml\n{bad_block}```",
            "## Acceptance Criteria": (
                "- [ ] AC1: Show something per arinc-kb:arinc-424 §9.9"
            ),
        },
    )


def test_lint_golden_ticket_file_passes(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(_build_ticket(block), encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output


def test_lint_broken_ref_ticket_exits_1(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    text = _broken_ref_ticket(fed_hub, block)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 1
    assert "DoR: FAIL" in result.output


def test_lint_reads_from_stdin(fed_hub):
    block = _golden_block(fed_hub)
    text = _build_ticket(block)

    result = runner.invoke(
        app, ["ticket", "lint", "-", "--hub", str(fed_hub)], input=text
    )

    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output


def test_lint_json_output_pass(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(_build_ticket(block), encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub), "--json"]
    )

    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["pass"] is True
    assert data["errors"] == []


def test_lint_json_output_fail(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    text = _broken_ref_ticket(fed_hub, block)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub), "--json"]
    )

    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["pass"] is False
    assert data["errors"]


def test_lint_missing_file_exits_1_with_clear_error(tmp_path):
    missing = tmp_path / "does-not-exist.md"

    result = runner.invoke(app, ["ticket", "lint", str(missing)])

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "could not read file" in result.output
    assert str(missing) in result.output


def test_lint_non_utf8_file_names_encoding_as_the_problem(fed_hub, tmp_path):
    """Ticket bodies are explicitly UTF-8, so a latin-1/binary file is a
    realistic user error — it must produce a red one-liner naming
    encoding, not a raw traceback (UnicodeDecodeError is a ValueError, not
    an OSError). Mirrors test_missionlint's mission-side equivalent so the
    two error paths stay identical."""
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_bytes(b"caf\xe9 - not valid utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "utf-8" in result.output.lower()


def test_explicit_missions_dir_missing_is_a_hard_error(fed_hub, tmp_path):
    """An explicit --missions-dir that doesn't exist is a BA typo, not a
    missing mission — it must error out rather than silently letting
    check_parent_mission's .is_file() probing report 'mission file not
    found' for a mission that actually exists elsewhere."""
    block = _golden_block(fed_hub)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(_build_ticket(block), encoding="utf-8")
    bad_dir = tmp_path / "missons"  # typo, does not exist

    result = runner.invoke(
        app,
        [
            "ticket",
            "lint",
            str(ticket_path),
            "--hub",
            str(fed_hub),
            "--missions-dir",
            str(bad_dir),
        ],
    )

    assert result.exit_code == 1
    assert str(bad_dir) in result.output


def test_explicit_missions_dir_overrides_the_sibling(fed_hub, tmp_path):
    """--missions-dir must override the sibling default, not merely
    supplement it. Both directories exist and disagree on the ticket's
    parent mission: the sibling's mission has a backlog that does NOT
    cover this ticket's US id, the explicit dir's does. A refactor to
    `sibling or missions_dir` would report PASS become FAIL here (Path is
    always truthy, so `or` would pick the sibling regardless of what
    --missions-dir was passed) — the assertion below cannot pass under
    both semantics."""
    block = _golden_block(fed_hub)
    (tmp_path / "missions").mkdir()
    (tmp_path / "missions" / "M-airspace-filter.md").write_text(
        "# Mission\n\n"
        "> Mission: M-airspace-filter\n\n"
        "## US backlog\n"
        "| US ID | Title |\n"
        "|---|---|\n"
        # sibling backlog covers a DIFFERENT story — US1 is absent.
        "| M-airspace-filter-US2 | Filter by altitude |\n",
        encoding="utf-8",
    )
    (tmp_path / "tickets").mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "M-airspace-filter.md").write_text(
        "# Mission\n\n"
        "> Mission: M-airspace-filter\n\n"
        "## US backlog\n"
        "| US ID | Title |\n"
        "|---|---|\n"
        # elsewhere's backlog DOES cover this ticket's US id.
        "| M-airspace-filter-US1 | Render polygons |\n",
        encoding="utf-8",
    )
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US1.md"
    text = _build_ticket(block).replace(
        "\n\n## Summary",
        "\n\n> Parent mission: M-airspace-filter\n\n## Summary",
        1,
    )
    ticket_path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "ticket",
            "lint",
            str(ticket_path),
            "--hub",
            str(fed_hub),
            "--missions-dir",
            str(elsewhere),
        ],
    )

    # PASS from --missions-dir (US1 covered there), never FAIL from the
    # sibling's mismatched backlog.
    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output
    assert "not in the backlog" not in result.output


def test_ticket_lint_resolves_sibling_missions_dir(fed_hub, tmp_path):
    """A ticket at tickets/<id>.md finds missions/ next to it, so the
    back-link check runs with no flag."""
    block = _golden_block(fed_hub)
    (tmp_path / "missions").mkdir()
    (tmp_path / "tickets").mkdir()
    (tmp_path / "missions" / "M-airspace-filter.md").write_text(
        "# Mission\n\n"
        "> Mission: M-airspace-filter\n\n"
        "## US backlog\n"
        "| US ID | Title |\n"
        "|---|---|\n"
        "| M-airspace-filter-US1 | Render polygons |\n",
        encoding="utf-8",
    )
    ticket_path = tmp_path / "tickets" / "M-airspace-filter-US1.md"
    text = _build_ticket(block).replace(
        "\n\n## Summary",
        "\n\n> Parent mission: M-airspace-filter\n\n## Summary",
        1,
    )
    ticket_path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app, ["ticket", "lint", str(ticket_path), "--hub", str(fed_hub)]
    )

    assert result.exit_code == 0, result.output
    assert "DoR: PASS" in result.output


def test_lint_exits_2_when_only_the_ref_is_stale(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    path = tmp_path / "M-airspace-US1.md"
    path.write_text(_build_ticket(block), encoding="utf-8")
    make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["ticket", "lint", str(path), "--hub", str(fed_hub), "--fail-on-stale"],
    )
    assert result.exit_code == 2, result.output
    # Click also exits 2 for a usage error (e.g. an unrecognised option) —
    # pin that this 2 came from the lint report, not from `--fail-on-stale`
    # failing to parse.
    assert "DoR: FAIL" in result.output


def test_lint_exits_1_when_something_else_also_fails(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    path = tmp_path / "M-airspace-US1.md"
    path.write_text(
        _build_ticket(block).replace("## Use cases", "## Use case"),
        encoding="utf-8",
    )
    make_stale(fed_hub)

    result = runner.invoke(
        app,
        ["ticket", "lint", str(path), "--hub", str(fed_hub), "--fail-on-stale"],
    )
    assert result.exit_code == 1


def test_lint_exits_0_on_a_stale_ref_without_the_flag(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    path = tmp_path / "M-airspace-US1.md"
    path.write_text(_build_ticket(block), encoding="utf-8")
    make_stale(fed_hub)

    result = runner.invoke(app, ["ticket", "lint", str(path), "--hub", str(fed_hub)])
    assert result.exit_code == 0


def test_lint_exits_1_when_the_only_failure_is_a_broken_ref_not_stale(
    fed_hub, tmp_path
):
    """The `code` tag on a broken-ref `Issue` is `""`, not `"stale-ref"`
    (`doctor.py`) — so `--fail-on-stale` must not accidentally promote a
    broken ref to exit 2. This is the discrimination `stale_errors` exists
    to make (see `tests/test_lintcore.py`'s unit test), pinned here at the
    CLI so a regression that conflated the two codes would be caught."""
    block = _golden_block(fed_hub)
    text = _broken_ref_ticket(fed_hub, block)
    path = tmp_path / "tal.md"
    path.write_text(text, encoding="utf-8")

    result = runner.invoke(
        app,
        ["ticket", "lint", str(path), "--hub", str(fed_hub), "--fail-on-stale"],
    )
    assert result.exit_code == 1, result.output
    assert "DoR: FAIL" in result.output


def test_export_writes_tracker_body(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    ticket_path = tmp_path / "tal.md"
    ticket_path.write_text(_build_ticket(block), encoding="utf-8")

    result = runner.invoke(app, ["ticket", "export", str(ticket_path)])

    assert result.exit_code == 0, result.output
    assert "## KB context" in result.output
    assert "## Definition of Ready" not in result.output
    assert "## Review record" not in result.output

    out = tmp_path / "jira.md"
    result = runner.invoke(
        app, ["ticket", "export", str(ticket_path), "--out", str(out)]
    )
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").startswith("# TAL-1580")


def _plan_hub(fed_hub, tmp_path, run_git):
    from tests.test_missionlint import MISSION_ID
    from tests.test_planingest import US1, context_block
    from tests.test_ticketfetch import publish_plan

    publish_plan(fed_hub, "ba-one", tmp_path / "ba-one", context_block(fed_hub))
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "publish plan")
    return US1, MISSION_ID


def test_fetch_writes_ticket_under_docs_impl(fed_hub, tmp_path, run_git, monkeypatch):
    us1, _ = _plan_hub(fed_hub, tmp_path, run_git)
    work = tmp_path / "dev-repo"
    work.mkdir()
    monkeypatch.chdir(work)

    result = runner.invoke(app, ["ticket", "fetch", us1, "--hub", str(fed_hub)])

    assert result.exit_code == 0, result.output
    path = Path("docs") / "impl" / us1 / "ticket.md"
    assert f"fetched: ba-one:ba-one-plan §{us1} -> {path}" in result.output
    text = (work / path).read_text(encoding="utf-8")
    assert text.startswith("# TAL-1580")
    assert "> Fetched from hub: ba-one:ba-one-plan" in text
    assert "\r" not in text


def test_fetch_out_overwrites_and_creates_parents(fed_hub, tmp_path, run_git):
    us1, _ = _plan_hub(fed_hub, tmp_path, run_git)
    out = tmp_path / "a" / "b" / "t.md"
    out.parent.mkdir(parents=True)
    out.write_text("stale", encoding="utf-8")
    args = ["ticket", "fetch", f"ba-one:{us1}", "--hub", str(fed_hub), "--out"]

    result = runner.invoke(app, [*args, str(out)])

    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").startswith("# TAL-1580")


def test_fetch_unknown_id_exits_1_with_hint(fed_hub, tmp_path, run_git, monkeypatch):
    _plan_hub(fed_hub, tmp_path, run_git)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        app, ["ticket", "fetch", "M-nope-US9", "--hub", str(fed_hub)]
    )

    assert result.exit_code == 1
    assert "ask the BA to run kb publish" in result.output
    assert not (tmp_path / "docs").exists()


def test_fetch_unreachable_hub_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["ticket", "fetch", "M-x-US1", "--hub", str(tmp_path / "no-hub")]
    )
    assert result.exit_code == 1


def test_fetch_refuses_traversal_and_absolute_ids(
    fed_hub, tmp_path, run_git, monkeypatch
):
    _plan_hub(fed_hub, tmp_path, run_git)
    work = tmp_path / "dev-repo"
    work.mkdir()
    monkeypatch.chdir(work)
    outside = tmp_path / "outside"

    for bad in ("../x", "../../x", str(outside), "repo:../x"):
        result = runner.invoke(app, ["ticket", "fetch", bad, "--hub", str(fed_hub)])
        assert result.exit_code == 1, (bad, result.output)
        assert "not a ticket id" in result.output

    assert list(work.iterdir()) == []
    assert not outside.exists()


def test_fetch_copies_bug_assets_next_to_ticket(
    fed_hub, tmp_path, run_git, monkeypatch
):
    from tests.test_ticketfetch import _bug_hub

    _, name = _bug_hub(fed_hub, tmp_path, run_git)
    work = tmp_path / "dev-repo"
    work.mkdir()
    monkeypatch.chdir(work)

    result = runner.invoke(app, ["ticket", "fetch", "BUG-12", "--hub", str(fed_hub)])

    assert result.exit_code == 0, result.output
    impl = work / "docs" / "impl" / "BUG-12"
    assert f"](assets/{name})" in (impl / "ticket.md").read_text(encoding="utf-8")
    assert (impl / "assets" / name).is_file()


def test_fetch_warns_per_asset_missing_from_the_hub_clone(
    fed_hub, tmp_path, run_git, monkeypatch
):
    from strata_kb import ticketfetch
    from tests.test_ticketfetch import _bug_hub

    hub, name = _bug_hub(fed_hub, tmp_path, run_git)
    ticketfetch.assets_of(hub, "BUG-12")[0].unlink()
    work = tmp_path / "dev-repo"
    work.mkdir()
    monkeypatch.chdir(work)

    result = runner.invoke(app, ["ticket", "fetch", "BUG-12", "--hub", str(fed_hub)])

    assert result.exit_code == 0, result.output
    assert f"warning: assets/{name} is not in the hub clone" in result.output
    assert f"/assets/{name}" in result.output
    assert not (work / "docs" / "impl" / "BUG-12" / "assets").exists()


def _fetch_in_dev_repo(fed_hub, tmp_path, run_git, monkeypatch, target, repo_id):
    us1, _ = _plan_hub(fed_hub, tmp_path, run_git)
    work = tmp_path / "dev-repo"
    (work / ".kb").mkdir(parents=True)
    (work / ".kb" / "config.yaml").write_text(f"repo_id: {repo_id}\n", encoding="utf-8")
    monkeypatch.chdir(work)
    # a ticket targeting `target`
    plan = fed_hub / "federation" / "ba-one" / "ba-one-plan"
    for f in plan.rglob("*.raw.md"):
        f.write_text(
            f.read_text(encoding="utf-8").replace(
                "> Parent mission:", f"> Target repo: {target}\n> Parent mission:", 1
            ),
            encoding="utf-8",
        )
    result = runner.invoke(app, ["ticket", "fetch", us1, "--hub", str(fed_hub)])
    return us1, result


def test_ticket_fetch_warns_on_other_target(fed_hub, tmp_path, run_git, monkeypatch):
    us1, result = _fetch_in_dev_repo(
        fed_hub, tmp_path, run_git, monkeypatch, "other-api", "this-repo"
    )

    assert result.exit_code == 0, result.output
    assert f"{us1} targets other-api, this repo is this-repo" in result.output
    assert (Path("docs") / "impl" / us1 / "ticket.md").is_file()


def test_ticket_fetch_no_warning_same_target(fed_hub, tmp_path, run_git, monkeypatch):
    us1, result = _fetch_in_dev_repo(
        fed_hub, tmp_path, run_git, monkeypatch, "this-repo", "this-repo"
    )

    assert result.exit_code == 0, result.output
    assert "targets" not in result.output


def test_ticket_fetch_malformed_config_does_not_block_fetch(
    fed_hub, tmp_path, run_git, monkeypatch
):
    us1, _ = _plan_hub(fed_hub, tmp_path, run_git)
    work = tmp_path / "dev-repo"
    (work / ".kb").mkdir(parents=True)
    (work / ".kb" / "config.yaml").write_text("repo_id: [unclosed\n", encoding="utf-8")
    monkeypatch.chdir(work)

    result = runner.invoke(app, ["ticket", "fetch", us1, "--hub", str(fed_hub)])

    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert (Path("docs") / "impl" / us1 / "ticket.md").is_file()


def test_duplicate_stem_is_error(fed_hub, tmp_path):
    block = _golden_block(fed_hub)
    one = tmp_path / "tickets" / "M-x" / "TAL-1.md"
    two = tmp_path / "tickets" / "TAL-1.md"
    for p in (one, two):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_build_ticket(block), encoding="utf-8")

    result = runner.invoke(app, ["ticket", "lint", str(one), "--hub", str(fed_hub)])

    assert result.exit_code == 1
    assert f"duplicate ticket id TAL-1: {one}, {two}" in result.output


def test_lint_child_reads_its_parent_from_the_folder(fed_hub, tmp_path):
    from tests.test_ticketlint_family import API, PID, WEB, family

    texts = family(_golden_block(fed_hub))
    folder = tmp_path / "tickets"
    folder.mkdir()
    for tid, text in texts.items():
        (folder / f"{tid}.md").write_text(text, encoding="utf-8")

    for tid in (PID, API, WEB):
        result = runner.invoke(
            app, ["ticket", "lint", str(folder / f"{tid}.md"), "--hub", str(fed_hub)]
        )
        assert result.exit_code == 0, result.output
    (folder / f"{PID}.md").unlink()
    result = runner.invoke(
        app, ["ticket", "lint", str(folder / f"{API}.md"), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 1 and "not found" in result.output


def _write_family(folder, texts):
    folder.mkdir(parents=True)
    for tid, text in texts.items():
        (folder / f"{tid}.md").write_text(text, encoding="utf-8")


def test_unconfigured_ba_repo_relints_its_own_published_ticket(plan_hub, tmp_path):
    from tests.test_planstatus import US
    from tests.test_ticketlint_family import family

    texts = family(_golden_block(plan_hub.root), pid=US[1])
    for name, expect in (("ba-one", False), ("ba-two", True)):
        repo = tmp_path / "work" / name
        _write_family(repo / "tickets", texts)
        result = runner.invoke(
            app,
            [
                "ticket", "lint", str(repo / "tickets" / f"{US[1]}.md"),
                "--hub", str(plan_hub.root), "--kb-dir", str(repo / ".kb"),
            ],
        )  # fmt: skip
        assert ("already published by ba-one" in result.output) is expect, result.output


def test_malformed_config_never_breaks_lint(fed_hub, tmp_path):
    from tests.test_ticketlint_family import PID, family

    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text("repo_id: [unclosed\n", encoding="utf-8")
    plain = tmp_path / "tickets" / "TAL-1.md"
    plain.parent.mkdir()
    plain.write_text(_build_ticket(_golden_block(fed_hub)), encoding="utf-8")
    args = ["--hub", str(fed_hub), "--kb-dir", str(kb)]
    ok = runner.invoke(app, ["ticket", "lint", str(plain), *args])
    assert ok.exit_code == 0, ok.output

    texts = family(_golden_block(fed_hub))
    _write_family(tmp_path / "fam", texts)
    fam = runner.invoke(
        app, ["ticket", "lint", str(tmp_path / "fam" / f"{PID}.md"), *args]
    )
    assert fam.exit_code == 0 and "config unreadable" in fam.output, fam.output
