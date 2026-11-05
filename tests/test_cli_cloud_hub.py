"""CLI on Claude Code cloud: `kb resolve` and `kb mission next` read the hub over
its API; every other hub command refuses and points at the MCP tools."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from strata_kb import gitio, hubapi
from strata_kb import hub as hub_mod
from strata_kb.cli import app
from strata_kb.errors import KbError
from tests.test_cli_mission import _ba_layout
from tests.test_hubapi import client_http

runner = CliRunner()
MCP_ONLY = (
    "on Claude Code cloud the hub is read through the strata-kb MCP tools, not the CLI"
)


@pytest.fixture
def cloud(monkeypatch):
    monkeypatch.setenv("STRATA_KB_CLOUD", "1")
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)


@pytest.fixture
def api_over(monkeypatch, token):
    def install(http) -> None:
        monkeypatch.setattr(
            hubapi, "from_env", lambda: hubapi.HubApi("http://hub", token, http=http)
        )

    return install


def _ticket(tmp_path, run_git, fed_hub, refs: list[str], name="t.md"):
    head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    path = tmp_path / name
    body = "".join(f"    - {r}\n" for r in refs)
    path.write_text(
        f'kb-context:\n  version: "{head}"\n  refs:\n{body}', encoding="utf-8"
    )
    return path


def test_cloud_resolve_write_cache_matches_local(
    tmp_path, fed_hub, fixture_kb, run_git, web_client, api_over, monkeypatch
):
    ticket = _ticket(
        tmp_path, run_git, fed_hub,
        ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"],
    )  # fmt: skip
    local_cache = tmp_path / "local" / "docs" / "impl" / "T-1" / "context.md"
    cloud_cache = tmp_path / "cloud" / "docs" / "impl" / "T-1" / "context.md"
    args = ["resolve", str(ticket), "--kb-dir", str(fixture_kb)]
    monkeypatch.setenv("STRATA_KB_CLOUD", "0")
    local = runner.invoke(
        app, [*args, "--hub", str(fed_hub), "--write-cache", str(local_cache)]
    )

    monkeypatch.setenv("STRATA_KB_CLOUD", "1")
    api_over(client_http(web_client))
    cloud = runner.invoke(app, [*args, "--write-cache", str(cloud_cache)])

    assert local.exit_code == cloud.exit_code == 0, (local.output, cloud.output)
    assert cloud.output == local.output
    assert cloud_cache.read_bytes() == local_cache.read_bytes()
    assert b"\r" not in cloud_cache.read_bytes()


def test_cloud_resolve_keeps_broken_exit_code_and_status_only(
    tmp_path, fed_hub, fixture_kb, run_git, web_client, api_over, cloud
):
    ticket = _ticket(tmp_path, run_git, fed_hub, ["arinc-kb:arinc-424 §9.9"])
    api_over(client_http(web_client))

    result = runner.invoke(
        app, ["resolve", str(ticket), "--status-only", "--kb-dir", str(fixture_kb)]
    )

    assert result.exit_code == 1
    assert "status=broken" in result.output


def test_cloud_resolve_bad_block_exits_1_with_hub_message(
    tmp_path, fixture_kb, web_client, api_over, cloud
):
    ticket = tmp_path / "bad.md"
    ticket.write_text("no block here", encoding="utf-8")
    api_over(client_http(web_client))

    result = runner.invoke(app, ["resolve", str(ticket), "--kb-dir", str(fixture_kb)])

    assert result.exit_code == 1
    assert "Traceback" not in result.output


def test_cloud_resolve_unreachable_hub_exits_1_one_line(
    tmp_path, fixture_kb, api_over, cloud
):
    ticket = tmp_path / "t.md"
    ticket.write_text(
        'kb-context:\n  version: "abc"\n  refs:\n    - a:b §1\n', encoding="utf-8"
    )
    api_over(lambda *a, **k: (0, b"connection refused"))

    result = runner.invoke(app, ["resolve", str(ticket), "--kb-dir", str(fixture_kb)])

    assert result.exit_code == 1
    assert "hub unreachable: connection refused" in result.output
    assert "Traceback" not in result.output


def _plan_http(*done_ids: str, code=200):
    stories = [
        {"us_id": u, "mission_id": "M-platform", "title": "t", "status": "done",
         "reasons": [], "depends_on": []}
        for u in done_ids
    ]  # fmt: skip

    def http(method, url, headers, body=None, timeout=60):
        return code, json.dumps(
            {"stories": stories, "unparented": [], "notes": []}
        ).encode()

    return http


def test_cloud_mission_next_done_set_from_hub(tmp_path, api_over, cloud):
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    api_over(_plan_http("M-platform-US1"))

    result = runner.invoke(
        app, ["mission", "next", "--missions-dir", str(root / "missions")]
    )

    assert result.exit_code == 0, result.output
    assert "| M-platform-US1 | M-platform | done |  |" in result.output
    assert "| M-platform-US2 | M-platform | to-draft |  |" in result.output
    assert result.output.rstrip().endswith("Next: M-platform-US2 — Observability")


def test_cloud_mission_next_counts_unparented_done(tmp_path, api_over, cloud):
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))

    def http(method, url, headers, body=None, timeout=60):
        row = {"us_id": "M-platform-US1", "mission_id": "", "title": "t",
               "status": "done", "reasons": [], "depends_on": []}  # fmt: skip
        return 200, json.dumps(
            {"stories": [], "unparented": [row], "notes": []}
        ).encode()

    api_over(http)
    result = runner.invoke(
        app, ["mission", "next", "--missions-dir", str(root / "missions")]
    )
    assert "| M-platform-US1 | M-platform | done |  |" in result.output


def test_cloud_mission_next_unreachable_hub_is_a_note(tmp_path, api_over, cloud):
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    api_over(lambda *a, **k: (0, b"connection refused"))

    result = runner.invoke(
        app, ["mission", "next", "--missions-dir", str(root / "missions")]
    )

    assert result.exit_code == 0, result.output
    assert "note: done: unknown (hub unreachable: connection refused)" in result.output
    assert "| M-platform-US1 | M-platform | ready |  |" in result.output


def test_cloud_mission_next_from_hub_uses_the_api(tmp_path, api_over, cloud):
    api_over(_plan_http("M-platform-US1"))
    result = runner.invoke(app, ["mission", "next", "--from-hub", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["stories"][0]["us_id"] == "M-platform-US1"


def test_cloud_other_hub_commands_refuse(tmp_path, fixture_kb, cloud):
    result = runner.invoke(
        app, ["query", "airspace", "--kb-dir", str(fixture_kb), "--hub", str(tmp_path)]
    )
    assert result.exit_code == 1
    assert MCP_ONLY in result.output


def test_cloud_resolve_hub_never_clones(tmp_path, monkeypatch, cloud):
    monkeypatch.setattr(
        gitio, "clone", lambda *a, **k: pytest.fail("cloud must never clone the hub")
    )
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache"))

    with pytest.raises(KbError, match="strata-kb MCP tools"):
        hub_mod.resolve_hub("https://example.invalid/hub.git")
    assert not (tmp_path / "cache").exists()


def test_cloud_resolve_hub_still_reads_a_local_hub_path(tmp_path, cloud):
    (tmp_path / ".kb").mkdir()
    assert hub_mod.resolve_hub(str(tmp_path)).root == tmp_path.resolve()


def test_local_mode_unchanged(tmp_path, fed_hub, fixture_kb, run_git, monkeypatch):
    monkeypatch.setenv("STRATA_KB_CLOUD", "0")
    monkeypatch.setattr(
        hubapi, "from_env", lambda: pytest.fail("local mode must not use the API")
    )
    ticket = _ticket(tmp_path, run_git, fed_hub, ["arinc-kb:arinc-424 §5.3"])

    result = runner.invoke(
        app,
        ["resolve", str(ticket), "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0, result.output

    cloned = []

    def clone(*a, **k):
        cloned.append(a)
        raise gitio.GitError("offline")

    monkeypatch.setattr(gitio, "clone", clone)
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache"))
    assert hub_mod.resolve_hub("https://example.invalid/hub.git") is None
    assert cloned
