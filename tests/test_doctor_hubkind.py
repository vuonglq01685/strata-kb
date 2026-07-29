from pathlib import Path

from center_kb import doctor
from center_kb.hub import HubHandle
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
    from center_kb import publish

    root = _mid(tmp_path)
    upper = tmp_path / "root-hub"
    (upper / "federation").mkdir(parents=True)
    handle = HubHandle(root=upper)
    publish._snapshot_federation(root / "federation", handle, "mid", "abc1234")
    assert doctor.check_federation_publish(root, handle, "mid") == []


def test_check_federation_publish_digest_drift_warns(tmp_path):
    from center_kb import publish

    root = _mid(tmp_path)
    upper = tmp_path / "root-hub"
    (upper / "federation").mkdir(parents=True)
    handle = HubHandle(root=upper)
    publish._snapshot_federation(root / "federation", handle, "mid", "abc1234")
    make_fed_entry(root / "federation", "repo-new", "doc-new")
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
