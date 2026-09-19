from pathlib import Path

from strata_kb import doctor
from strata_kb.hub import HubHandle
from tests.conftest import make_fed_entry


def _mid(tmp_path: Path) -> Path:
    root = tmp_path / "mid"
    make_fed_entry(root / "federation", "repo-a", "doc-a")
    return root


def test_check_federation_publish_clean_not_published_yet(tmp_path):
    root = _mid(tmp_path)
    upper = tmp_path / "root-hub"
    (upper / "federation").mkdir(parents=True)
    issues = doctor.check_federation_publish(root, HubHandle(root=upper), "mid")
    assert [i.level for i in issues] == ["warning"]
    assert "not published" in issues[0].message


def test_check_federation_publish_digest_match_no_issue(tmp_path):
    from strata_kb import publish

    root = _mid(tmp_path)
    upper = tmp_path / "root-hub"
    (upper / "federation").mkdir(parents=True)
    handle = HubHandle(root=upper)
    publish._snapshot_federation(root / "federation", handle, "mid", "abc1234")
    assert doctor.check_federation_publish(root, handle, "mid") == []


def test_check_federation_publish_digest_drift_warns(tmp_path):
    from strata_kb import publish

    root = _mid(tmp_path)
    upper = tmp_path / "root-hub"
    (upper / "federation").mkdir(parents=True)
    handle = HubHandle(root=upper)
    publish._snapshot_federation(root / "federation", handle, "mid", "abc1234")
    make_fed_entry(root / "federation", "repo-new", "doc-new")
    issues = doctor.check_federation_publish(root, handle, "mid")
    assert any("differs from the published snapshot" in i.message for i in issues)


def test_check_federation_publish_meta_only_drift_warns(tmp_path):
    from strata_kb import publish

    root = _mid(tmp_path)
    upper = tmp_path / "root-hub"
    (upper / "federation").mkdir(parents=True)
    handle = HubHandle(root=upper)
    publish._snapshot_federation(root / "federation", handle, "mid", "abc1234")
    meta = root / "federation" / "repo-a" / "_meta.yaml"
    meta.write_text(meta.read_text(encoding="utf-8").replace("abc1234", "def5678"), encoding="utf-8")
    issues = doctor.check_federation_publish(root, handle, "mid")
    assert any("differs from the published snapshot" in i.message for i in issues)


def test_check_federation_publish_warns_on_cycle(tmp_path):
    root = _mid(tmp_path)
    make_fed_entry(root / "federation" / "upper" / "mid", "repo-c", "doc-c")
    issues = doctor.check_federation_publish(root, None, "mid")
    assert any("cycle" in i.message for i in issues)


def test_check_federation_publish_invalid_segment_errors(tmp_path):
    root = _mid(tmp_path)
    make_fed_entry(root / "federation", "-bad-name", "doc-z")
    issues = doctor.check_federation_publish(root, None, "mid")
    assert any(i.level == "error" and "-bad-name" in i.message for i in issues)


def test_check_federation_publish_self_entry_not_a_cycle(tmp_path):
    root = _mid(tmp_path)
    make_fed_entry(root / "federation", "mid", "own-doc")  # self-published entry
    issues = doctor.check_federation_publish(root, None, "mid")
    assert not any("cycle" in i.message for i in issues)


def test_cli_doctor_hub_kind_self_hub_no_false_warnings(tmp_path, run_git):
    from typer.testing import CliRunner

    from strata_kb.cli import app
    from tests.test_publish_hub import _git_repo

    hub = tmp_path / "hub"
    (hub / ".kb").mkdir(parents=True)
    (hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (hub / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: hub-self\nhub: {hub}\n", encoding="utf-8"
    )
    fed = hub / "federation"
    make_fed_entry(fed, "repo-a", "doc-a")
    _git_repo(run_git, hub)
    from strata_kb.federation import write_federation_index

    write_federation_index(fed)
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "index")

    result = CliRunner().invoke(app, ["doctor", "--kb-dir", str(hub / ".kb")])
    assert result.exception is None, result.output
    assert "not published" not in result.output
    assert "differs from the published snapshot" not in result.output


def test_cli_doctor_hub_kind_unpublished_upstream_warns(tmp_path, run_git):
    from typer.testing import CliRunner

    from strata_kb.cli import app
    from tests.test_publish_hub import _git_repo

    root_hub = tmp_path / "root-hub"
    (root_hub / ".kb").mkdir(parents=True)
    (root_hub / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root_hub / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: root-hub\n", encoding="utf-8"
    )
    fed0 = root_hub / "federation"
    fed0.mkdir()
    (fed0 / ".gitkeep").write_text("", encoding="utf-8")
    _git_repo(run_git, root_hub)
    from strata_kb.federation import write_federation_index

    write_federation_index(fed0)
    run_git(root_hub, "add", "-A")
    run_git(root_hub, "commit", "-m", "index")

    mid = tmp_path / "mid"
    (mid / ".kb").mkdir(parents=True)
    (mid / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (mid / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: mid\nhub: {root_hub}\n", encoding="utf-8"
    )
    make_fed_entry(mid / "federation", "repo-a", "doc-a")
    _git_repo(run_git, mid)
    from strata_kb.federation import write_federation_index as wfi

    wfi(mid / "federation")
    run_git(mid, "add", "-A")
    run_git(mid, "commit", "-m", "index")

    result = CliRunner().invoke(app, ["doctor", "--kb-dir", str(mid / ".kb")])
    assert result.exception is None, result.output
    assert "not published" in result.output


def test_cli_doctor_hub_kind_outside_git_does_not_crash(tmp_path):
    from typer.testing import CliRunner

    from strata_kb.cli import app

    loose = tmp_path / "loose"
    (loose / ".kb").mkdir(parents=True)
    (loose / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (loose / ".kb" / "config.yaml").write_text(
        f"kind: hub\nrepo_id: loose\nhub: {loose}\n", encoding="utf-8"
    )
    fed = loose / "federation"
    fed.mkdir()
    from strata_kb.federation import write_federation_index

    write_federation_index(fed)

    result = CliRunner().invoke(app, ["doctor", "--kb-dir", str(loose / ".kb")])
    assert result.exception is None, result.output
    assert "multi-tier checks skipped" in result.output
