from pathlib import Path

from typer.testing import CliRunner

from strata_kb import models
from strata_kb.cli import app
from tests.conftest import make_fed_entry
from tests.test_publish_hub import _git_repo

runner = CliRunner()


def _mid_with_unreviewed_own_kb(tmp_path: Path, name: str) -> tuple[Path, Path]:
    """A `kind: hub` mid-tier hub whose federation/ has one mirrored entry and
    whose own .kb/ (a drafting desk, never published by publish_federation)
    holds an unreviewed section — for proving the gate does not fire on the
    hub-to-hub `not is_self` branch."""
    mid = tmp_path / f"{name}-mid"
    (mid / ".kb").mkdir(parents=True)
    make_fed_entry(mid / "federation", "repo-a", "doc-a")
    (mid / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    doc = mid / ".kb" / "own-doc"
    doc.mkdir(parents=True)
    (doc / "ch1.md").write_text("## 1.1 T\n\nBody.\n", encoding="utf-8")
    (doc / "ch1.raw.md").write_text("## 1.1 T\n\nBody.\n", encoding="utf-8")
    (doc / "_manifest.yaml").write_text(
        "id: own-doc\ntitle: own-doc\nsections:\n"
        "  - id: '1.1'\n    title: T\n    summary: s\n    status: summarized\n    file: ch1\n",
        encoding="utf-8",
    )
    root_hub = tmp_path / f"{name}-root-hub"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / "federation").mkdir()
    (root_hub / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    return mid, root_hub


def _args(git_kb, hub_worktree, *extra):
    return ["publish", "--hub", str(hub_worktree), "--repo-id", "demo-kb",
            "--kb-dir", str(git_kb["kb"]), "--direct", *extra]


def test_publish_warns_about_unreviewed_sections(git_kb, hub_worktree):
    result = runner.invoke(app, _args(git_kb, hub_worktree))
    assert result.exit_code == 0, result.output
    assert "[warn] 2 section(s) in 1 doc(s) are published without SME review" in result.output


def test_publish_require_reviewed_refuses_before_any_hub_write(git_kb, hub_worktree):
    result = runner.invoke(app, _args(git_kb, hub_worktree, "--require-reviewed"))
    assert result.exit_code == 1
    assert "without SME review" in result.output
    assert not (hub_worktree / "federation" / "demo-kb").exists()


def test_hub_to_hub_federation_publish_skips_unreviewed_gate(tmp_path, run_git):
    """R12: publish_federation() (hub-to-hub, `not is_self`) mirrors federation/
    only — the mid-tier hub's own unreviewed .kb/ content must not warn, and
    must not be blocked by --require-reviewed either."""
    mid, root_hub = _mid_with_unreviewed_own_kb(tmp_path, "warn")
    (mid / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: mid\nhub: {root_hub}\n", encoding="utf-8"
    )
    _git_repo(run_git, root_hub)
    _git_repo(run_git, mid)

    result = runner.invoke(app, ["publish", "--kb-dir", str(mid / ".kb")])
    assert result.exit_code == 0, result.output
    assert "without SME review" not in result.output

    mid2, root_hub2 = _mid_with_unreviewed_own_kb(tmp_path, "require")
    (mid2 / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: mid2\nhub: {root_hub2}\n", encoding="utf-8"
    )
    _git_repo(run_git, root_hub2)
    _git_repo(run_git, mid2)

    result = runner.invoke(
        app, ["publish", "--kb-dir", str(mid2 / ".kb"), "--require-reviewed"]
    )
    assert result.exit_code == 0, result.output
    assert "without SME review" not in result.output


def test_publish_require_reviewed_passes_when_all_reviewed(git_kb, hub_worktree, run_git):
    mpath = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    for s in m.sections:
        s.status = "reviewed"
    models.save_yaml_model(mpath, m)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "reviewed")
    result = runner.invoke(app, _args(git_kb, hub_worktree, "--require-reviewed"))
    assert result.exit_code == 0, result.output
    assert "without SME review" not in result.output


def test_publish_require_reviewed_ignores_hist_but_not_other_summarized(
    git_kb, hub_worktree, run_git
):
    """F-L7 fix round 1: `kb svc note` always leaves its `hist.*` row
    `summarized`, and a whole-doc `kb approve` never flips it -- so
    --require-reviewed must not count it, or the gate would re-trip after
    every note with no way to clear it short of naming the section. A real
    (non-hist) summarized section must still block."""
    mpath = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    src_file = m.sections[0].file
    for s in m.sections:
        s.status = "reviewed"
    m.sections.append(models.SectionEntry(
        id="hist.api", title="api — ticket history", summary="Tickets: 1.",
        status="summarized", file=src_file,
    ))
    models.save_yaml_model(mpath, m)
    l2 = git_kb["kb"] / "demo-doc" / f"{src_file}.md"
    l2.write_text(
        l2.read_text(encoding="utf-8")
        + "\n## hist.api api — ticket history\n\n```text\nT-1 | x\n```\n",
        encoding="utf-8",
    )
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "reviewed + hist.api")

    result = runner.invoke(app, _args(git_kb, hub_worktree, "--require-reviewed"))
    assert result.exit_code == 0, result.output
    assert "without SME review" not in result.output

    m.sections[0].status = "summarized"
    models.save_yaml_model(mpath, m)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "regress 1.1")

    result = runner.invoke(app, _args(git_kb, hub_worktree, "--require-reviewed"))
    assert result.exit_code == 1
    assert "without SME review" in result.output
