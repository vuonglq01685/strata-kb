from aero_kb import gitio, models
from aero_kb.doctor import check_hub
from aero_kb.federation import FederationMeta
from aero_kb.hub import HubHandle


def _errors(issues):
    return [i.message for i in issues if i.level == "error"]


def _warnings(issues):
    return [i.message for i in issues if i.level == "warning"]


def _fed_entry(hub_root, repo_id, source_commit, doc_id="local-doc"):
    entry = hub_root / "federation" / repo_id
    (entry / "manifests").mkdir(parents=True)
    models.save_yaml_model(
        entry / "_meta.yaml",
        FederationMeta(repo_id=repo_id, source_commit=source_commit),
    )
    models.save_yaml_model(
        entry / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id=doc_id, title=doc_id)]),
    )


def test_hub_unreachable_is_warning(git_kb):
    issues, stale = check_hub(git_kb["kb"], None)
    assert not _errors(issues)
    assert any("không truy cập được" in w for w in _warnings(issues))
    assert stale is False


def test_hub_stale_cache_flags_stale(git_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree, stale=True, age_seconds=3600.0)
    issues, stale = check_hub(git_kb["kb"], handle)
    assert stale is True
    assert any("cache" in w for w in _warnings(issues))


def test_collision_local_hub_is_error_with_guidance(git_kb, hub_worktree):
    hub_kb = hub_worktree / ".kb"
    index = models.load_yaml_model(hub_kb / "index.yaml", models.KBIndex)
    index.docs.append(models.IndexEntry(id="demo-doc", title="Demo (hub)"))
    models.save_yaml_model(hub_kb / "index.yaml", index)
    handle = HubHandle(root=hub_worktree)
    issues, _ = check_hub(git_kb["kb"], handle)
    collision = [e for e in _errors(issues) if "demo-doc" in e]
    assert collision
    # hướng dẫn dọn dẹp từng bước phải nằm trong thông điệp
    assert "xóa" in collision[0].lower()
    assert "kb context new" in collision[0]


def test_index_out_of_date_is_error(git_kb, hub_worktree):
    _fed_entry(hub_worktree, "repo-a", source_commit="0000000")
    handle = HubHandle(root=hub_worktree)
    issues, _ = check_hub(git_kb["kb"], handle, repo_id="repo-a")
    assert any("lệch" in e for e in _errors(issues))


def test_index_up_to_date_ok(git_kb, hub_worktree):
    head = gitio.head_commit(git_kb["root"])
    _fed_entry(hub_worktree, "repo-a", source_commit=head)
    handle = HubHandle(root=hub_worktree)
    issues, stale = check_hub(git_kb["kb"], handle, repo_id="repo-a")
    assert not _errors(issues)
    assert stale is False


def test_not_published_is_warning(git_kb, hub_worktree):
    handle = HubHandle(root=hub_worktree)
    issues, _ = check_hub(git_kb["kb"], handle, repo_id="chua-publish")
    assert any("chưa publish" in w for w in _warnings(issues))


def test_federation_cross_collision_warning(git_kb, hub_worktree):
    head = gitio.head_commit(git_kb["root"])
    _fed_entry(hub_worktree, "repo-a", head, doc_id="shared-doc")
    _fed_entry(hub_worktree, "repo-b", "1111111", doc_id="shared-doc")
    handle = HubHandle(root=hub_worktree)
    issues, _ = check_hub(git_kb["kb"], handle, repo_id="repo-a")
    assert any("shared-doc" in w for w in _warnings(issues))


def test_cli_doctor_hub_collision_exit_1(git_kb, hub_worktree, monkeypatch):
    from typer.testing import CliRunner

    from aero_kb.cli import app

    hub_kb = hub_worktree / ".kb"
    index = models.load_yaml_model(hub_kb / "index.yaml", models.KBIndex)
    index.docs.append(models.IndexEntry(id="demo-doc", title="Demo (hub)"))
    models.save_yaml_model(hub_kb / "index.yaml", index)
    monkeypatch.chdir(git_kb["root"])
    result = CliRunner().invoke(
        app, ["doctor", "--kb-dir", str(git_kb["kb"]), "--hub", str(hub_worktree)]
    )
    assert result.exit_code == 1
    assert "demo-doc" in result.output
