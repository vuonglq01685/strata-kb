# tests/test_publish_hub.py
from pathlib import Path

import pytest
import yaml

from center_kb import publish
from center_kb.hub import HubHandle
from tests.conftest import make_fed_entry


def _git_repo(run_git, root: Path) -> None:
    run_git(root, "init")
    run_git(root, "config", "user.name", "test")
    run_git(root, "config", "user.email", "test@test.local")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "v1")


@pytest.fixture
def mid_fed(tmp_path: Path) -> Path:
    """federation/ của hub trung gian: 1 entry phẳng + 1 entry lồng + file tầng đỉnh."""
    fed = tmp_path / "mid" / "federation"
    make_fed_entry(fed, "repo-a", "doc-a")
    make_fed_entry(fed / "leaf-hub", "repo-b", "doc-b")
    (fed / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (fed / "registry.yaml").write_text("repos: {}\n", encoding="utf-8")
    (fed / ".gitkeep").write_text("", encoding="utf-8")
    return fed


@pytest.fixture
def upper(tmp_path: Path) -> HubHandle:
    root = tmp_path / "root-hub"
    (root / "federation").mkdir(parents=True)
    return HubHandle(root=root)


def test_snapshot_federation_mirrors_entries(mid_fed, upper):
    n_docs, changed, _skipped = publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    assert changed is True
    assert n_docs == 2
    dest = upper.federation_dir / "mid"
    assert (dest / "repo-a" / "index.yaml").exists()
    assert (dest / "repo-a" / "_meta.yaml").exists()  # _meta của leaf mirror verbatim
    assert (dest / "leaf-hub" / "repo-b" / "doc-b" / "_manifest.yaml").exists()


def test_snapshot_federation_excludes_top_level_files(mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    dest = upper.federation_dir / "mid"
    assert not (dest / "index.yaml").exists()      # aggregate index nguồn không đẩy
    assert not (dest / "registry.yaml").exists()
    assert not (dest / ".gitkeep").exists()
    assert not (dest / "_meta.yaml").exists()      # không viết meta gốc


def test_snapshot_federation_noop_when_unchanged(mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    n_docs, changed, _skipped = publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    assert changed is False
    assert n_docs == 2


def test_snapshot_federation_applies_deletions(mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    import shutil

    shutil.rmtree(mid_fed / "repo-a")
    _, changed, _skipped = publish._snapshot_federation(mid_fed, upper, "mid", "abc1235")
    assert changed is True
    assert not (upper.federation_dir / "mid" / "repo-a").exists()


def test_snapshot_federation_mirrors_the_hub_owned_asset_record(mid_fed, upper):
    """F-D6 overrule (finding 1): _assets.yaml is hub-written bookkeeping
    being mirrored upward on the fed->fed path, not a source artefact being
    smuggled in the way a child's config.yaml would be -- it must reach the
    upper hub like any other file under the entry."""
    from center_kb import assetstore, models

    record_path = mid_fed / "repo-a" / assetstore.RECORD_NAME
    models.save_yaml_model(
        record_path, models.AssetsRecord(assets=[f"doc-a/assets/{'a' * 64}.png"])
    )
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert dest_record.exists()
    assert dest_record.read_text(encoding="utf-8") == record_path.read_text(
        encoding="utf-8"
    )


def test_snapshot_federation_does_not_delete_the_asset_record_on_republish(
    mid_fed, upper
):
    """Finding 1: dest_man is built with no exclude list, so an
    _assets.yaml already mirrored to the upper hub must survive a later
    republish that touches unrelated entries -- before the fix, it was
    absent from every src_man (filtered every call) but present in dest_man,
    so diff_manifests classified it as deleted and the republish committed
    that deletion."""
    from center_kb import assetstore, models

    models.save_yaml_model(
        mid_fed / "repo-a" / assetstore.RECORD_NAME,
        models.AssetsRecord(assets=[f"doc-a/assets/{'b' * 64}.png"]),
    )
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")
    dest_record = upper.federation_dir / "mid" / "repo-a" / assetstore.RECORD_NAME
    assert dest_record.exists()

    make_fed_entry(mid_fed, "repo-c", "doc-c")  # unrelated change, non-empty diff
    _n_docs, changed, _skipped = publish._snapshot_federation(
        mid_fed, upper, "mid", "abc1235"
    )
    assert changed is True
    assert dest_record.exists()  # not wiped by the republish


def test_snapshot_federation_rejects_escaping_rid(mid_fed, upper):
    with pytest.raises(publish.PublishError):
        publish._snapshot_federation(mid_fed, upper, "../evil", "abc1234")


def test_snapshot_federation_missing_source_raises(tmp_path, upper):
    with pytest.raises(publish.PublishError, match="does not exist"):
        publish._snapshot_federation(
            tmp_path / "does-not-exist", upper, "mid", "abc1234"
        )


def test_snapshot_federation_empty_source_refuses_wipe(tmp_path, mid_fed, upper):
    publish._snapshot_federation(mid_fed, upper, "mid", "abc1234")

    empty_fed = tmp_path / "empty" / "federation"
    empty_fed.mkdir(parents=True)
    (empty_fed / ".gitkeep").write_text("", encoding="utf-8")

    with pytest.raises(publish.PublishError, match="empty"):
        publish._snapshot_federation(empty_fed, upper, "mid", "abc1235")

    assert (upper.federation_dir / "mid" / "repo-a").exists()


def test_find_cycle_segment_detects_own_id(tmp_path):
    from center_kb import federation
    from tests.conftest import make_fed_entry

    fed = tmp_path / "federation"
    make_fed_entry(fed / "root-hub" / "mid", "repo-a", "doc-a")  # nội dung đã quay vòng
    assert federation.find_cycle_segment(fed, {"mid"}) == "root-hub/mid/repo-a"


def test_find_cycle_segment_clean(tmp_path):
    from center_kb import federation
    from tests.conftest import make_fed_entry

    fed = tmp_path / "federation"
    make_fed_entry(fed, "repo-a", "doc-a")
    make_fed_entry(fed / "leaf-hub", "repo-b", "doc-b")
    assert federation.find_cycle_segment(fed, {"mid"}) is None


@pytest.fixture
def mid_hub(tmp_path: Path, run_git) -> Path:
    """Hub trung gian (git repo): .kb/ + federation/ có 2 entry."""
    root = tmp_path / "mid"
    (root / ".kb").mkdir(parents=True)
    fed = root / "federation"
    make_fed_entry(fed, "repo-a", "doc-a")
    make_fed_entry(fed / "leaf-hub", "repo-b", "doc-b")
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: mid\n", encoding="utf-8"
    )
    (root / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    _git_repo(run_git, root)
    return root


@pytest.fixture
def root_hub(tmp_path: Path, run_git) -> Path:
    root = tmp_path / "root-hub"
    (root / ".kb").mkdir(parents=True)
    (root / ".kb" / "config.yaml").write_text(
        "kind: hub\nrepo_id: root-hub\n", encoding="utf-8"
    )
    (root / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (root / "federation").mkdir()
    (root / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git_repo(run_git, root)
    return root


def test_publish_federation_direct_end_to_end(mid_hub, root_hub):
    report = publish.publish_federation(
        mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct"
    )
    assert report.repo_id == "mid"
    assert report.n_docs == 2
    fed = root_hub / "federation"
    assert (fed / "mid" / "repo-a" / "index.yaml").exists()
    assert (fed / "mid" / "leaf-hub" / "repo-b" / "index.yaml").exists()
    # aggregate index trên root chứa id lồng
    idx = yaml.safe_load((fed / "index.yaml").read_text(encoding="utf-8"))
    rids = {d["repo_id"] for d in idx["docs"]}
    assert rids == {"mid/repo-a", "mid/leaf-hub/repo-b"}


def test_publish_federation_second_run_noop(mid_hub, root_hub):
    publish.publish_federation(mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct")
    report = publish.publish_federation(
        mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct"
    )
    assert report.n_docs == 2  # no-op, không lỗi


def test_publish_federation_rejects_self_hub(mid_hub):
    with pytest.raises(publish.PublishError, match="federation cycle detected"):
        publish.publish_federation(
            mid_hub / ".kb", str(mid_hub), repo_id="mid", mode="direct"
        )


def test_publish_federation_rejects_own_id_in_entries(mid_hub, root_hub):
    # nội dung của 'mid' đã quay vòng về federation của chính nó
    make_fed_entry(mid_hub / "federation" / "upper" / "mid", "repo-c", "doc-c")
    with pytest.raises(publish.PublishError, match="federation cycle detected"):
        publish.publish_federation(
            mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct"
        )


def test_publish_federation_rejects_dest_id_in_entries(mid_hub, root_hub):
    # federation của mid chứa entry đến từ root-hub → đẩy lên root-hub là trả ngược
    make_fed_entry(mid_hub / "federation" / "root-hub", "repo-d", "doc-d")
    with pytest.raises(publish.PublishError, match="federation cycle detected"):
        publish.publish_federation(
            mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct"
        )


def test_publish_federation_allows_own_self_entry(mid_hub, root_hub):
    # hub tự publish .kb/ của nó → entry top-level trùng rid — không phải cycle
    make_fed_entry(mid_hub / "federation", "mid", "own-doc")
    report = publish.publish_federation(
        mid_hub / ".kb", str(root_hub), repo_id="mid", mode="direct"
    )
    assert report.n_docs == 3
    assert (
        root_hub / "federation" / "mid" / "mid" / "own-doc" / "_manifest.yaml"
    ).exists()


def test_find_cycle_segment_exempt_exact_only_skips_exact_match(tmp_path):
    from center_kb import federation

    fed = tmp_path / "federation"
    make_fed_entry(fed, "mid", "doc-a")  # exact self-entry — exempt
    make_fed_entry(fed / "upper" / "mid", "repo-c", "doc-c")  # nested — still a cycle
    assert (
        federation.find_cycle_segment(fed, {"mid"}, exempt_exact={"mid"})
        == "upper/mid/repo-c"
    )


def test_publish_federation_missing_federation_dir(tmp_path, run_git, root_hub):
    bare = tmp_path / "bare"
    (bare / ".kb").mkdir(parents=True)
    (bare / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    _git_repo(run_git, bare)
    with pytest.raises(publish.PublishError, match="no federation"):
        publish.publish_federation(bare / ".kb", str(root_hub), repo_id="bare", mode="direct")


def test_publish_federation_rejects_dest_with_same_repo_id(mid_hub, tmp_path, run_git):
    # upstream là cache clone của chính mình: cùng repo_id trong config
    clone = tmp_path / "cache-clone"
    (clone / ".kb").mkdir(parents=True)
    (clone / ".kb" / "config.yaml").write_text("kind: hub\nrepo_id: mid\n", encoding="utf-8")
    (clone / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (clone / "federation").mkdir()
    _git_repo(run_git, clone)
    with pytest.raises(publish.PublishError, match="federation cycle detected"):
        publish.publish_federation(mid_hub / ".kb", str(clone), repo_id="mid", mode="direct")


def test_find_cycle_segment_single_segment_dest_id(tmp_path):
    from center_kb import federation

    fed = tmp_path / "federation"
    make_fed_entry(fed, "root-hub", "doc-d")  # entry 1 segment mang id hub đích
    assert federation.find_cycle_segment(fed, {"root-hub"}, exempt_exact={"mid"}) == "root-hub"


def test_cli_hub_to_hub_publish_error_is_one_line_not_a_traceback(mid_hub, root_hub):
    """F-D9 finding 6: the hub-to-hub `except` tuple in cli.publish() (the
    `not is_self` branch that calls publish_mod.publish_federation) had no
    CLI-level coverage -- reverting the whole except clause still passed the
    48-test wave set. Same cycle setup as
    test_publish_federation_rejects_dest_id_in_entries, driven through the
    CLI instead of calling publish_federation directly."""
    from typer.testing import CliRunner

    from center_kb.cli import app

    runner = CliRunner()
    make_fed_entry(mid_hub / "federation" / "root-hub", "repo-d", "doc-d")
    result = runner.invoke(
        app,
        ["publish", "--direct", "--hub", str(root_hub), "--repo-id", "mid",
         "--kb-dir", str(mid_hub / ".kb")],
    )
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "federation cycle detected" in result.output
