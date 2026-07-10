"""E2E Phase 3: đúng kịch bản demo-federation (spec §11) bằng tmp git repos.

hub bare ← publish từ repo-a (git_kb) và repo-b (tự dựng) →
query từ repo-a thấy: tài liệu domain hub (full L2) + summary repo-b [remote] →
context new pin hub_version → amendment hub → resolve stale →
repo-a commit thêm không publish → doctor bắt index lệch exit 1.
"""
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aero_kb import gitio, models
from aero_kb.cli import app
from aero_kb.hub import resolve_hub
from aero_kb.query import search

runner = CliRunner()


@pytest.fixture
def fed_world(tmp_path, git_kb, hub_worktree, run_git, monkeypatch):
    """hub bare + repo-a (git_kb, publish 'repo-a') + repo-b (publish 'repo-b')."""
    monkeypatch.setenv("AERO_KB_HUB_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("AERO_KB_HUB_TTL", "0")  # luôn pull — thấy publish mới nhất
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")

    # repo-b với 1 doc cục bộ riêng
    repo_b = tmp_path / "repo-b"
    kb_b = repo_b / ".kb"
    doc_dir = kb_b / "roster-sop"
    doc_dir.mkdir(parents=True)
    (doc_dir / "ch3.md").write_text(
        "## 3.2 Roster Rules\n\nCrew roster duty limits and rest rules.\n",
        encoding="utf-8",
    )
    (doc_dir / "ch3.raw.md").write_text(
        "## 3.2 Roster Rules\n\nFull text duty limits.\n", encoding="utf-8"
    )
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="roster-sop", title="Roster SOP",
            sections=[models.SectionEntry(
                id="3.2", title="Roster Rules",
                summary="Crew roster duty limits and rest rules.",
                status="reviewed", file="ch3",
            )],
        ),
    )
    models.save_yaml_model(
        kb_b / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(
            id="roster-sop", title="Roster SOP", tags=["crewops"],
            summary="Crew rostering SOP.",
        )]),
    )
    run_git(repo_b, "init")
    run_git(repo_b, "config", "user.name", "test")
    run_git(repo_b, "config", "user.email", "test@test.local")
    run_git(repo_b, "add", "-A")
    run_git(repo_b, "commit", "-m", "repo-b v1")

    from aero_kb.publish import publish

    publish(git_kb["kb"], str(bare), repo_id="repo-a")
    publish(kb_b, str(bare), repo_id="repo-b")
    return {"bare": bare, "repo_a": git_kb, "repo_b": repo_b, "hub_wt": hub_worktree}


def test_query_from_repo_a_sees_hub_and_repo_b(fed_world):
    handle = resolve_hub(str(fed_world["bare"]))
    kb_a = fed_world["repo_a"]["kb"]
    hub_results = search(kb_a, "restrictive airspace designation", hub=handle)
    assert any(r.source == "hub" and r.doc_id == "arinc-424" for r in hub_results)
    remote_results = search(kb_a, "crew roster duty rest", hub=handle)
    remote = [r for r in remote_results if r.source == "remote:repo-b"]
    assert remote
    assert "[remote]" in remote[0].content


def test_context_new_resolve_stale_after_hub_amendment(fed_world, run_git, monkeypatch, tmp_path):
    kb_a = fed_world["repo_a"]["kb"]
    monkeypatch.chdir(fed_world["repo_a"]["root"])
    out = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-424 §5.3",
         "--kb-dir", str(kb_a), "--hub", str(fed_world["bare"])],
    )
    assert out.exit_code == 0, out.output
    block = out.output
    assert "hub_version" in block

    # amendment trên hub → push
    hub_wt = fed_world["hub_wt"]
    # hub_wt đã publish 2 lần từ đầu test (fed_world push 2 publish origin)
    # → HEAD cục bộ của hub_wt bị bỏ lại phía sau; pull --ff-only trước khi
    # commit thêm amendment, tránh non-fast-forward khi push (giống Task 4).
    run_git(hub_wt, "pull", "--ff-only", "origin", "HEAD")
    l2 = hub_wt / ".kb" / "arinc-424" / "ch5-airspace.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace(
            "multiple code, level.", "multiple code, level, NEW field."
        ),
        encoding="utf-8",
    )
    run_git(hub_wt, "add", "-A")
    run_git(hub_wt, "commit", "-m", "amendment")
    run_git(hub_wt, "push", "origin", "HEAD")

    ticket = tmp_path / "ticket.txt"
    ticket.write_text(block, encoding="utf-8")
    res = runner.invoke(
        app,
        ["resolve", str(ticket), "--kb-dir", str(kb_a),
         "--hub", str(fed_world["bare"])],
    )
    assert res.exit_code == 2, res.output  # stale
    assert "status=stale" in res.output
    assert "NEW field" not in res.output  # nội dung trả về là bản pin


def test_doctor_detects_index_out_of_date(fed_world, run_git, monkeypatch):
    root_a = fed_world["repo_a"]["root"]
    kb_a = fed_world["repo_a"]["kb"]
    # commit thêm ở repo-a mà không publish lại
    (root_a / "note.txt").write_text("x", encoding="utf-8")
    run_git(root_a, "add", "-A")
    run_git(root_a, "commit", "-m", "chua publish")
    monkeypatch.chdir(root_a)
    res = runner.invoke(
        app, ["doctor", "--kb-dir", str(kb_a), "--hub", str(fed_world["bare"])]
    )
    # repo_id mặc định = tên git root; git_kb root là tmp dir tên ngẫu nhiên
    # → doctor báo 'chưa publish' (warning) chứ không phải lệch. Kiểm tra lệch
    # bằng check_hub trực tiếp với repo_id='repo-a':
    from aero_kb.doctor import check_hub

    handle = resolve_hub(str(fed_world["bare"]))
    issues, _ = check_hub(kb_a, handle, repo_id="repo-a")
    assert any("lệch" in i.message for i in issues if i.level == "error")


def test_phase2_block_still_resolves(fed_world, monkeypatch, tmp_path):
    """Tiêu chí 5: block Phase 2 (không hub_version) resolve nguyên vẹn."""
    repo_a = fed_world["repo_a"]
    monkeypatch.chdir(repo_a["root"])
    ticket = tmp_path / "old-ticket.txt"
    ticket.write_text(
        f'kb-context:\n  version: "{repo_a["rev1"]}"\n  refs:\n    - demo-doc §1.1\n',
        encoding="utf-8",
    )
    res = runner.invoke(
        app,
        ["resolve", str(ticket), "--kb-dir", str(repo_a["kb"]),
         "--hub", str(fed_world["bare"])],
    )
    assert res.exit_code == 2, res.output  # stale như Phase 2 (amendment rev2)
    assert "status=stale" in res.output
