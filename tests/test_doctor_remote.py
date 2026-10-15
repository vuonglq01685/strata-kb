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
    [("ba", "../etc", ""), ("ba", "", "../etc"), ("hub", "demo", "")],
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
    assert result.exit_code == 0, result.output
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


def test_dev_repo_with_unset_repo_id_reads_the_dir_named_code_doc(git_kb, hub_worktree):
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text("kind: dev\n", encoding="utf-8")
    rid = git_kb["root"].name
    code = hub_worktree / "federation" / rid / f"{rid}-code"
    code.mkdir(parents=True)
    (code / "_manifest.yaml").write_text("id: x\n", encoding="utf-8")
    (code / "code.raw.md").write_text("## svc.api API\nGET /x\n", encoding="utf-8")
    facts = _facts(hub_worktree, kb, "dev")
    assert facts["code_sections"] is not None
    assert set(facts["code_sections"]) == {"svc.api"}


def test_an_explicit_hub_wins_over_the_mcp_in_env(git_kb, hub_worktree, monkeypatch):
    kb = _published_ba(git_kb, hub_worktree)
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub:8321")
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", "tok")

    def no_mcp(*_):
        raise AssertionError("MCP must not be called with an explicit hub")

    monkeypatch.setattr(remote, "fetch_facts", no_mcp)
    result = runner.invoke(
        app,
        ["doctor", "--kb-dir", str(kb), "--hub", str(hub_worktree), "--no-refresh"],
    )
    assert "hub checked over MCP" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


@pytest.mark.anyio
async def test_a_hub_side_refusal_reaches_the_client_as_an_error(hub_worktree):
    server = create_server(
        ServerConfig(kb_dir=hub_worktree / ".kb", hub=str(hub_worktree))
    )
    async with connect_client(server) as client:
        with pytest.raises(remote.RemoteDoctorError, match="kind must be one of"):
            await remote.call_facts(client, {"kind": "hub", "repo_id": "x"})


def test_outside_a_git_repo_nothing_on_the_hub_is_compared(tmp_path, hub_worktree):
    kb = tmp_path / "loose" / ".kb"
    kb.mkdir(parents=True)
    (kb / "config.yaml").write_text("kind: ba\n", encoding="utf-8")
    facts = _facts(hub_worktree, kb, "ba")
    assert facts["published"] is False and facts["snapshot_digest"] is None
    msgs = _msgs(remote.run(kb, facts, "http://hub"))
    assert not any("published" in m and "kind:" not in m for _, m in msgs)


def test_a_newer_hub_issue_field_does_not_crash_the_client(git_kb, hub_worktree):
    kb = _published_ba(git_kb, hub_worktree)
    facts = _facts(hub_worktree, kb, "ba")
    facts["issues"] = [{"level": "warning", "message": "m", "code": "", "new": 1}]
    assert ("warning", "m") in _msgs(remote.run(kb, facts, "http://hub"))


def test_a_credential_in_the_hub_url_never_reaches_the_error():
    with pytest.raises(remote.RemoteDoctorError) as err:
        remote.fetch_facts("http://u:s3cretpw@127.0.0.1:9", "t" * 32, {"kind": "ba"})
    assert "s3cretpw" not in str(err.value)


def test_installed_version_must_match_the_hub(git_kb, hub_worktree, monkeypatch):
    import strata_kb

    kb = _published_ba(git_kb, hub_worktree)
    facts = _facts(hub_worktree, kb, "ba")
    assert facts["hub_version"] == strata_kb.__version__
    assert not any("pip install" in m for _, m in _msgs(remote.run(kb, facts, "h")))

    facts["hub_version"] = "9.9.9"
    msgs = _msgs(remote.run(kb, facts, "h"))
    assert (
        "error",
        f"strata-kb {strata_kb.__version__} is installed but the hub runs 9.9.9 — "
        "every repo on a hub uses the hub's version: pip install strata-kb==9.9.9",
    ) in msgs


def test_workflow_pins_must_match_the_hub(tmp_path):
    import strata_kb

    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "kb-publish.yml").write_text(
        "      - run: pip install strata-kb==1.0.0\n", encoding="utf-8"
    )
    (wf / "kb-code.yml").write_text(
        f"      - run: pip install strata-kb=={strata_kb.__version__}\n",
        encoding="utf-8",
    )
    issues = remote.version_issues(tmp_path, strata_kb.__version__)
    assert [(i.level, i.message) for i in issues] == [
        (
            "error",
            f".github/workflows/kb-publish.yml pins strata-kb==1.0.0 but the hub "
            f"runs {strata_kb.__version__} — change the pin to "
            f"strata-kb=={strata_kb.__version__}",
        )
    ]


def test_child_repo_checks_the_hub_over_mcp_too(git_kb, hub_worktree, monkeypatch):
    (hub_worktree / ".gitignore").write_text(".kb-work/\n", encoding="utf-8")
    publish(git_kb["kb"], str(hub_worktree), repo_id="demo-kb")
    kb = git_kb["kb"]
    (kb / "config.yaml").write_text("kind: child\nrepo_id: demo-kb\n", encoding="utf-8")
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub:8321")
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", "tok")
    monkeypatch.setattr(
        remote,
        "fetch_facts",
        lambda url, token, args: remote.hub_facts(HubHandle(root=hub_worktree), **args),
    )
    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb), "--no-refresh"])
    assert result.exit_code == 0, result.output
    assert "hub checked over MCP" in result.output
    assert "differs from the published snapshot" not in result.output


def test_git_path_says_the_version_was_not_checked(git_kb, fed_hub, monkeypatch):
    for var in ("STRATA_KB_HUB_URL", "STRATA_KB_HTTP_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    result = runner.invoke(
        app, ["doctor", "--kb-dir", str(git_kb["kb"]), "--hub", str(fed_hub)]
    )
    assert "[info] strata-kb version not checked against the hub" in result.output


def test_fix_pins_rewrites_only_the_version_string(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    body = "    runs-on: self-hosted\n      - run: pip install strata-kb==1.0.0\n"
    (wf / "kb-publish.yml").write_text(body, encoding="utf-8")
    changed = remote.fix_pins(tmp_path, "1.22.1")
    assert changed == [".github/workflows/kb-publish.yml: strata-kb==1.0.0 → 1.22.1"]
    assert (wf / "kb-publish.yml").read_text(encoding="utf-8") == body.replace(
        "1.0.0", "1.22.1"
    )
    assert remote.fix_pins(tmp_path, "1.22.1") == []


def test_pins_with_the_code_extra_are_read_reported_and_fixed_with_it(tmp_path):
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    line = '      - run: pip install "strata-kb[code]==1.0.0"\n'
    (wf / "kb-code.yml").write_text(line, encoding="utf-8")
    (msg,) = [
        i.message
        for i in remote.version_issues(tmp_path, "1.22.1")
        if "pins" in i.message
    ]
    assert "pins strata-kb[code]==1.0.0" in msg
    assert "change the pin to strata-kb[code]==1.22.1" in msg
    changed = remote.fix_pins(tmp_path, "1.22.1")
    assert changed == [".github/workflows/kb-code.yml: strata-kb[code]==1.0.0 → 1.22.1"]
    assert (wf / "kb-code.yml").read_text(encoding="utf-8") == line.replace(
        "1.0.0", "1.22.1"
    )
    assert not [
        i for i in remote.version_issues(tmp_path, "1.22.1") if "pins" in i.message
    ]


@pytest.mark.parametrize("bad", ["1.0 --index-url http://evil", "../x", "", "1.0;rm"])
def test_install_version_refuses_a_bad_hub_version(bad, monkeypatch):
    def never(*_a, **_k):
        raise AssertionError("must not run pip")

    monkeypatch.setattr(remote.subprocess, "run", never)
    assert "invalid version" in (remote.install_version(bad) or "")


def test_install_version_falls_back_to_uv(monkeypatch):
    calls = []

    def fake_run(cmd, **_k):
        calls.append(cmd)
        ok = cmd[0] == "/usr/bin/uv"
        return remote.subprocess.CompletedProcess(
            cmd, 0 if ok else 1, "", "No module named pip"
        )

    monkeypatch.setattr(remote.subprocess, "run", fake_run)
    monkeypatch.setattr(remote.shutil, "which", lambda _: "/usr/bin/uv")
    assert remote.install_version("1.22.1") is None
    assert calls[0][1:4] == ["-m", "pip", "install"]
    assert calls[1][:3] == ["/usr/bin/uv", "pip", "install"]
    assert calls[1][-1] == "strata-kb==1.22.1"


def test_refresh_agent_files_leaves_ci_and_config_alone(tmp_path):
    from strata_kb import initcmd

    initcmd.init_repo(tmp_path, "ba")
    wf = tmp_path / ".github" / "workflows" / "kb-publish.yml"
    cfg = tmp_path / ".kb" / "config.yaml"
    skill = tmp_path / ".claude" / "skills" / "kb-publish" / "SKILL.md"
    wf.write_text("custom ci\n", encoding="utf-8")
    cfg.write_text("kind: ba\nintake: https://x\n", encoding="utf-8")
    skill.write_text("stale\n", encoding="utf-8")

    report = initcmd.refresh_agent_files(tmp_path, "ba")

    assert ".claude/skills/kb-publish/SKILL.md" in report.updated
    assert skill.read_text(encoding="utf-8") != "stale\n"
    assert wf.read_text(encoding="utf-8") == "custom ci\n"
    assert cfg.read_text(encoding="utf-8") == "kind: ba\nintake: https://x\n"
    assert all(r.startswith(initcmd.AGENT_FILE_PREFIXES) for r in report.updated)


def test_refresh_agent_files_updates_the_rubric_but_not_its_local_override(tmp_path):
    from strata_kb import initcmd

    initcmd.init_repo(tmp_path, "dev")
    rubric = tmp_path / "docs" / "pr-review-rubric.md"
    local = tmp_path / "docs" / "pr-review-rubric.local.md"
    rubric.write_text("stale rubric\n", encoding="utf-8")
    local.write_text("my own axes\n", encoding="utf-8")

    report = initcmd.refresh_agent_files(tmp_path, "dev")

    assert "docs/pr-review-rubric.md" in report.updated
    assert "Pre-code" in rubric.read_text(encoding="utf-8")
    assert local.read_text(encoding="utf-8") == "my own axes\n"
    assert "docs/pr-review-rubric.local.md" not in report.updated


def _mcp_cli(git_kb, hub_worktree, monkeypatch, hub_version=None):
    """A published ba repo whose doctor talks to `hub_worktree` over a fake MCP."""
    kb = _published_ba(git_kb, hub_worktree)
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(remote.UPGRADED_ENV, raising=False)
    monkeypatch.setenv("STRATA_KB_HUB_URL", "http://hub:8321")
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", "tok")

    def fake_fetch(url, token, args):
        facts = remote.hub_facts(HubHandle(root=hub_worktree), **args)
        return {**facts, "hub_version": hub_version or facts["hub_version"]}

    monkeypatch.setattr(remote, "fetch_facts", fake_fetch)
    return kb


def _doctor(kb):
    return runner.invoke(app, ["doctor", "--kb-dir", str(kb), "--no-refresh"])


def test_a_mismatch_installs_the_hub_version_and_reruns(
    git_kb, hub_worktree, monkeypatch
):
    import strata_kb
    from strata_kb import cli

    kb = _mcp_cli(git_kb, hub_worktree, monkeypatch, hub_version="9.9.9")
    seen = {}
    monkeypatch.setattr(
        remote, "install_version", lambda v: seen.setdefault("v", v) and None
    )
    monkeypatch.setattr(
        cli,
        "_rerun_doctor",
        lambda kb_dir, ctx, no_refresh, env: seen.update(env=env, nr=no_refresh) or 0,
    )
    result = _doctor(kb)
    assert result.exit_code == 0, result.output
    assert seen["v"] == "9.9.9"
    assert seen["env"][remote.UPGRADED_ENV] == strata_kb.__version__
    assert seen["nr"] is True
    assert f"strata-kb {strata_kb.__version__} → 9.9.9" in result.output


def test_a_failed_install_reports_the_mismatch(git_kb, hub_worktree, monkeypatch):
    kb = _mcp_cli(git_kb, hub_worktree, monkeypatch, hub_version="9.9.9")
    monkeypatch.setattr(remote, "install_version", lambda v: "no network")
    result = _doctor(kb)
    assert result.exit_code == 1
    assert "could not install strata-kb==9.9.9: no network" in result.output
    assert "pip install strata-kb==9.9.9" in result.output


@pytest.mark.parametrize("env", ["CI", remote.UPGRADED_ENV])
def test_no_install_in_ci_or_after_an_upgrade(git_kb, hub_worktree, monkeypatch, env):
    kb = _mcp_cli(git_kb, hub_worktree, monkeypatch, hub_version="9.9.9")
    monkeypatch.setenv(env, "1")

    def never(v):
        raise AssertionError("must not install")

    monkeypatch.setattr(remote, "install_version", never)
    result = _doctor(kb)
    assert result.exit_code == 1
    assert "pip install strata-kb==9.9.9" in result.output


def test_a_matching_version_refreshes_skills_and_commands(
    git_kb, hub_worktree, monkeypatch
):
    kb = _mcp_cli(git_kb, hub_worktree, monkeypatch)
    root = kb.resolve().parent
    skill = root / ".claude" / "skills" / "kb-publish" / "SKILL.md"
    wf = root / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "kb-publish.yml").write_text("custom\n", encoding="utf-8")

    result = _doctor(kb)

    assert result.exit_code == 0, result.output
    assert skill.is_file()
    assert "updated skills/commands for strata-kb" in result.output
    assert (wf / "kb-publish.yml").read_text(encoding="utf-8") == "custom\n"
    assert "updated skills/commands" not in _doctor(kb).output  # nothing left to do


def test_doctor_sets_a_stale_workflow_pin_to_the_hub_version(
    git_kb, hub_worktree, monkeypatch
):
    import strata_kb

    kb = _mcp_cli(git_kb, hub_worktree, monkeypatch)
    wf = kb.resolve().parent / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    body = "    runs-on: self-hosted\n      - run: pip install strata-kb==1.0.0\n"
    (wf / "kb-publish.yml").write_text(body, encoding="utf-8")

    result = _doctor(kb)

    assert result.exit_code == 0, result.output
    v = strata_kb.__version__
    assert (wf / "kb-publish.yml").read_text(encoding="utf-8") == body.replace(
        "1.0.0", v
    )
    assert f"kb-publish.yml: strata-kb==1.0.0 → {v} — commit it" in result.output
