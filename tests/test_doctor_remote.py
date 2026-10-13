"""`kb doctor` for ba/dev repos over the hub's MCP (1.22.1): BA and Dev have
no git access to the hub, so the hub answers `kb_doctor_hub` and the repo
compares that with its own `.kb/`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import (
    create_connected_server_and_client_session as connect_client,
)
from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.doctor import check_published_kind, remote
from strata_kb.hub import HubHandle
from strata_kb.mcp import ServerConfig, create_server
from strata_kb.publish import publish

runner = CliRunner()


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _facts(hub_root: Path, kb: Path, kind: str, ctx: str | None = None) -> dict:
    args = remote.request_args(kb, kind, ctx)
    return remote.hub_facts(HubHandle(root=hub_root), **args)


def _msgs(result) -> list[tuple[str, str]]:
    return [(i.level, i.message) for i in result.issues]


def _published_ba(git_kb, hub_worktree) -> Path:
    (hub_worktree / ".gitignore").write_text(".kb-work/\n", encoding="utf-8")
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text("kind: ba\nrepo_id: demo-kb\n", encoding="utf-8")
    return kb


def test_published_ba_repo_is_clean_over_mcp_then_drift_warns(git_kb, hub_worktree):
    kb = _published_ba(git_kb, hub_worktree)

    result = remote.run(kb, _facts(hub_worktree, kb, "ba"), "http://hub")
    msgs = _msgs(result)
    assert [m for m in msgs if m[0] == "error"] == []
    assert not any("published" in m for _, m in msgs if "kind:" not in m)
    assert ("info", "kind: ba → hub menu: Ticket") in msgs
    assert msgs[0][1].startswith("hub checked over MCP at http://hub")

    l2 = kb / "demo-doc" / "ch1-records.md"
    l2.write_text(l2.read_text(encoding="utf-8") + "\nEdited.\n", encoding="utf-8")
    result = remote.run(kb, _facts(hub_worktree, kb, "ba"), "http://hub")
    assert (
        "warning",
        "local .kb differs from the published snapshot federation/demo-kb "
        "— run `kb publish`",
    ) in _msgs(result)


def test_unpublished_repo_warns_over_mcp(git_kb, hub_worktree):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text("kind: ba\nrepo_id: ghost-kb\n", encoding="utf-8")
    result = remote.run(kb, _facts(hub_worktree, kb, "ba"), "http://hub")
    assert any("has not published to the hub yet" in m for _, m in _msgs(result))


@pytest.mark.parametrize(
    ("kind", "repo_id", "dir_name"),
    [("ba", "../etc", ""), ("ba", "", "../etc"), ("child", "demo", "")],
)
def test_hub_facts_refuses_a_bad_kind_or_entry_name(
    hub_worktree, kind, repo_id, dir_name
):
    facts = remote.hub_facts(
        HubHandle(root=hub_worktree), kind=kind, repo_id=repo_id, dir_name=dir_name
    )
    assert "error" in facts


def test_registry_kind_clash_matches_the_local_check(git_kb, fed_hub, run_git):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text("kind: dev\nrepo_id: demo\n", encoding="utf-8")
    run_git(git_kb["root"], "remote", "add", "origin", "https://github.com/o/demo.git")
    (fed_hub / "federation" / "registry.yaml").write_text(
        yaml.safe_dump({"repos": {"o/demo": {"repo_id": "demo", "kind": "ba"}}}),
        encoding="utf-8",
    )
    local = check_published_kind(kb, HubHandle(root=fed_hub), "dev")
    facts = _facts(fed_hub, kb, "dev")
    clash = [(i["level"], i["message"]) for i in facts["issues"]]
    assert ("error", local[-1].message) in clash


def test_kb_context_is_checked_on_the_hub(git_kb, hub_worktree):
    kb = _published_ba(git_kb, hub_worktree)
    facts = _facts(hub_worktree, kb, "ba", ctx="not a kb-context block")
    assert any(i["level"] == "error" for i in facts["issues"])
    assert facts["context_stale"] is False


def test_dev_repo_without_a_hub_code_doc_is_not_judged(git_kb, hub_worktree):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text("kind: dev\nrepo_id: demo-kb\n", encoding="utf-8")
    facts = _facts(hub_worktree, kb, "dev")
    assert facts["code_sections"] is None
    result = remote.run(kb, facts, "http://hub")
    assert (
        "warning",
        "hub lag not judged — the hub has no demo-kb-code yet",
    ) in _msgs(result)


def test_stale_hub_cache_flags_the_result(git_kb, hub_worktree):
    kb = _published_ba(git_kb, hub_worktree)
    facts = {**_facts(hub_worktree, kb, "ba"), "stale": True, "age_seconds": 42}
    result = remote.run(kb, facts, "http://hub")
    assert result.stale is True
    assert ("warning", "hub cache is stale (pull failed, age ~42s)") in _msgs(result)


@pytest.mark.anyio
async def test_the_mcp_tool_answers_with_the_hub_facts(git_kb, hub_worktree):
    kb = _published_ba(git_kb, hub_worktree)
    server = create_server(
        ServerConfig(kb_dir=hub_worktree / ".kb", hub=str(hub_worktree))
    )
    async with connect_client(server, raise_exceptions=True) as client:
        facts = await remote.call_facts(client, remote.request_args(kb, "ba", None))
    assert facts["published"] is True
    assert facts == _facts(hub_worktree, kb, "ba")


@pytest.mark.anyio
async def test_a_hub_without_the_tool_says_to_upgrade():
    async with connect_client(FastMCP("old-hub")) as client:
        with pytest.raises(remote.RemoteDoctorError, match="upgrade strata-kb"):
            await remote.call_facts(client, {"kind": "ba", "repo_id": "x"})


def test_unreachable_mcp_is_a_clear_error():
    with pytest.raises(remote.RemoteDoctorError, match="could not reach the hub's MCP"):
        remote.fetch_facts("http://127.0.0.1:9", "t" * 32, {"kind": "ba"})


def test_mcp_target_reads_env_then_dot_env(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB_URL", raising=False)
    monkeypatch.delenv("STRATA_KB_HTTP_TOKEN", raising=False)
    assert remote.mcp_target(tmp_path) is None
    (tmp_path / ".env").write_text(
        "STRATA_KB_HUB_URL=http://hub:8321/\nSTRATA_KB_HTTP_TOKEN=tok\n",
        encoding="utf-8",
    )
    assert remote.mcp_target(tmp_path) == ("http://hub:8321", "tok")
    monkeypatch.setenv("STRATA_KB_HUB_URL", "https://other")
    assert remote.mcp_target(tmp_path) == ("https://other", "tok")


def test_request_args_never_carry_the_remote_credential(git_kb, run_git):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text("kind: ba\n", encoding="utf-8")
    run_git(
        git_kb["root"],
        "remote",
        "add",
        "origin",
        "https://x-access-token:ghs_SECRET@github.com/o/demo.git",
    )
    args = remote.request_args(kb, "ba", None)
    assert "ghs_SECRET" not in str(args)
    assert args["repo_id"] == ""
    assert args["dir_name"] == git_kb["root"].name


def test_cli_doctor_uses_mcp_and_never_the_git_hub(git_kb, hub_worktree, monkeypatch):
    kb = _published_ba(git_kb, hub_worktree)
    (kb / "config.yaml").write_text(
        "kind: ba\nrepo_id: demo-kb\nhub: /no/such/hub\n", encoding="utf-8"
    )
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub:8321")
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", "tok")
    seen = {}

    def fake_fetch(url, token, args):
        seen.update(url=url, token=token)
        return remote.hub_facts(HubHandle(root=hub_worktree), **args)

    monkeypatch.setattr(remote, "fetch_facts", fake_fetch)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb), "--no-refresh"])
    assert seen == {"url": "http://hub:8321", "token": "tok"}
    assert "hub checked over MCP at http://hub:8321" in result.output
    assert "differs from the published snapshot" not in result.output


def test_cli_doctor_without_mcp_or_hub_points_at_mcp_setup(git_kb, monkeypatch):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text(
        "kind: dev\nrepo_id: demo-kb\nhub: /no/such/hub\n", encoding="utf-8"
    )
    for var in ("STRATA_KB_HUB", "STRATA_KB_HUB_URL", "STRATA_KB_HTTP_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb), "--no-refresh"])
    assert result.exit_code == 1
    assert "kb mcp-setup" in result.output


def test_cli_doctor_reports_an_mcp_failure(git_kb, monkeypatch):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text("kind: ba\nrepo_id: demo-kb\n", encoding="utf-8")
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub:8321")
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", "tok")

    def failing(url, token, args):
        raise remote.RemoteDoctorError("could not reach the hub's MCP")

    monkeypatch.setattr(remote, "fetch_facts", failing)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb), "--no-refresh"])
    assert result.exit_code == 1
    assert "[error] could not reach the hub's MCP" in result.output
