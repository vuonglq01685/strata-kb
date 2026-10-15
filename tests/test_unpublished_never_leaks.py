"""C7 (2026-10-10 review): every read path serves the hub's `federation/`
only. A document that sits in the hub's own `.kb/` but was never published
must not come back from search or get, on any surface: library, CLI, MCP,
REST or the Web UI."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from starlette.testclient import TestClient
from typer.testing import CliRunner

from strata_kb import query
from strata_kb.cli import app
from strata_kb.hub import HubHandle
from strata_kb.mcp import ServerConfig, create_server
from strata_kb.web.app import create_app
from tests.conftest import make_fed_entry

SECRET = "zebracornquill"
DOC = "secret-draft"
TOKEN = "s3cr3t-token-abcdefgh-unpublished"
# Words that only the unpublished document's own text contains. Asserting on
# these, not on SECRET, keeps a surface that echoes the query from passing
# for a leak.
CONTENT = ("condensed draft", "raw draft text", "draft summary")


def _leaks(text: str) -> list[str]:
    return [marker for marker in CONTENT if marker in text]


@pytest.fixture
def leaky_hub(fed_hub: Path, tmp_path: Path) -> Path:
    """fed_hub plus one unpublished document in its own `.kb/`."""
    scratch = tmp_path / "scratch-federation"
    make_fed_entry(
        scratch,
        "hub-own",
        DOC,
        tags=["airspace"],
        sec_summary=f"{SECRET} draft summary.",
        l2=f"## 1.1 Draft\n\n{SECRET} condensed draft.\n",
        l3=f"## 1.1 Draft\n\n{SECRET} raw draft text.\n",
    )
    shutil.copytree(scratch / "hub-own" / DOC, fed_hub / ".kb" / DOC)
    shutil.copy(scratch / "hub-own" / "index.yaml", fed_hub / ".kb" / "index.yaml")
    return fed_hub


def test_library_search_and_get_skip_the_local_kb(leaky_hub):
    hub = HubHandle(root=leaky_hub)
    outcome = query.search_detailed(hub, SECRET)
    assert outcome.results == []
    assert _leaks("".join(outcome.notes)) == []
    for level in ("l2", "l3"):
        assert query.get_section(hub, DOC, "1.1", level=level) is None


def test_cli_query_and_get_skip_the_local_kb(leaky_hub):
    runner = CliRunner()
    kb = str(leaky_hub / ".kb")
    hub = str(leaky_hub)
    result = runner.invoke(app, ["query", SECRET, "--kb-dir", kb, "--hub", hub])
    assert _leaks(result.output) == []
    for level in ("l2", "l3"):
        result = runner.invoke(
            app, ["get", DOC, "1.1", "--level", level, "--kb-dir", kb, "--hub", hub]
        )
        assert result.exit_code != 0
        assert _leaks(result.output) == []


@pytest.mark.anyio
async def test_mcp_tools_skip_the_local_kb(leaky_hub):
    config = ServerConfig(kb_dir=leaky_hub / ".kb", hub=str(leaky_hub))
    server = create_server(config)
    async with create_connected_server_and_client_session(server) as client:
        for tool, args in (
            ("kb_search", {"query": SECRET}),
            ("kb_get_section", {"doc": DOC, "section": "1.1"}),
            ("kb_get_section", {"doc": DOC, "section": "1.1", "level": "l3"}),
        ):
            result = await client.call_tool(tool, args)
            text = "".join(getattr(c, "text", "") for c in result.content)
            assert _leaks(text) == [], tool


def test_rest_and_ui_skip_the_local_kb(leaky_hub):
    from strata_kb.serving.accounts import Accounts

    # With no account /ui is only the setup form; the leak check needs the real UI.
    Accounts(leaky_hub / ".kb-auth" / "users.db").add("boss", "pw", "admin")
    config = ServerConfig(kb_dir=leaky_hub / ".kb", hub=str(leaky_hub))
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with TestClient(create_app(config, TOKEN)) as client:
        for path, params in (
            ("/api/search", {"q": SECRET}),
            ("/api/docs", {}),
            (f"/api/docs/{DOC}", {}),
            (f"/api/docs/{DOC}/sections/1.1", {}),
            ("/ui", {"q": SECRET}),
            (f"/ui/docs/{DOC}", {}),
        ):
            response = client.get(path, params=params, headers=headers)
            assert _leaks(response.text) == [], path
            assert response.url.path != "/ui/setup", path
