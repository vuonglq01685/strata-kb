"""doctor.run(): the `kb doctor` checks as a library call (1.15.0). The CLI
prints its issues after check_kind's and maps them to exit codes; these
tests call run() directly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import doctor
from strata_kb.cli import app
from strata_kb.federation import write_federation_index
from strata_kb.hub import HubHandle

runner = CliRunner()


def _cli_lines(kb: Path, hub: Path) -> list[str]:
    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb), "--hub", str(hub)])
    return [line for line in result.output.splitlines() if line.startswith("[")]


def _messages(result: doctor.DoctorResult) -> list[str]:
    return [f"[{i.level}] {i.message}" for i in result.issues]


def test_a_clean_kb_has_no_issue_and_is_not_stale(git_kb, fed_hub):
    result = doctor.run(git_kb["kb"], HubHandle(root=fed_hub))
    assert [i for i in result.issues if i.level == "error"] == []
    assert result.stale is False


def test_the_cli_prints_check_kind_then_run(git_kb, fed_hub):
    (git_kb["kb"] / "demo-doc" / "ch1-records.raw.md").unlink()
    result = doctor.run(git_kb["kb"], HubHandle(root=fed_hub))
    assert any(i.level == "error" for i in result.issues)
    kind = [f"[{i.level}] {i.message}" for i in doctor.check_kind(git_kb["kb"])]
    assert kind + _messages(result) == _cli_lines(git_kb["kb"], fed_hub)


def _stop_hook_only(repo_root: Path) -> None:
    hook = {"hooks": [{"type": "command", "command": f"{doctor._USAGE_HOOK} --x"}]}
    (repo_root / ".claude").mkdir(exist_ok=True)
    (repo_root / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"Stop": [hook]}}), encoding="utf-8"
    )


@pytest.mark.parametrize(("kind", "checked"), [("ba", True), ("child", False)])
def test_usage_hooks_are_checked_for_ba_and_dev_only(git_kb, fed_hub, kind, checked):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text(f"kind: {kind}\nrepo_id: demo\n", encoding="utf-8")
    _stop_hook_only(kb.resolve().parent)
    result = doctor.run(kb, HubHandle(root=fed_hub))
    assert any("SubagentStop" in i.message for i in result.issues) is checked


def test_a_stale_citation_sets_stale(git_kb, fed_hub, run_git):
    rev1 = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "Condensed: restrictive airspace designation codes.",
            "Condensed: restrictive airspace designation codes, amended.",
        ),
        encoding="utf-8",
    )
    write_federation_index(fed_hub / "federation")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "amend arinc-424 5.3")
    context = (
        f'kb-context:\n  version: "{rev1}"\n  refs:\n    - arinc-kb:arinc-424 §5.3\n'
    )

    result = doctor.run(git_kb["kb"], HubHandle(root=fed_hub), context_text=context)
    assert result.stale is True
    assert doctor.run(git_kb["kb"], HubHandle(root=fed_hub)).stale is False
