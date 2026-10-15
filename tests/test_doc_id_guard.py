"""2026-10-10 review §5.2 #1: a caller-supplied doc id must never leave
`<repo>/.kb/<doc>/` -- not via `..`, not via a separator, not via a symlink.

The planted target is the hub's own UNPUBLISHED `.kb/secret-draft`, which
`federation/arinc-kb/../../.kb/secret-draft` used to reach (cited as
`arinc-kb:secret-draft`)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.hub import HubHandle
from strata_kb.query import doc_dir, get_section, search

SECRET = "TOPSECRET unpublished draft text"
runner = CliRunner()


@pytest.fixture
def leaky_hub(fed_hub: Path) -> Path:
    """fed_hub plus an unpublished doc in the hub's own `.kb/`."""
    src = fed_hub / "federation" / "arinc-kb" / "arinc-424"
    dst = fed_hub / ".kb" / "secret-draft"
    shutil.copytree(src, dst)
    for name in ("ch1.md", "ch1.raw.md"):
        (dst / name).write_text(
            f"## 5.3 Restrictive Airspace\n\n{SECRET}\n", encoding="utf-8"
        )
    return fed_hub


TRAVERSALS = [
    ("../../.kb/secret-draft", None),
    ("arinc-kb:../../.kb/secret-draft", None),
    ("../../.kb/secret-draft", "arinc-kb"),
    ("..", "arinc-kb"),
    (".hidden", "arinc-kb"),
    ("arinc-424/../../../.kb/secret-draft", "arinc-kb"),
    ("a\\b", "arinc-kb"),
    ("", "arinc-kb"),
]


@pytest.mark.parametrize(("doc", "repo"), TRAVERSALS)
def test_get_section_refuses_a_doc_id_outside_the_grammar(leaky_hub, doc, repo):
    for level in ("l2", "l3"):
        assert (
            get_section(HubHandle(root=leaky_hub), doc, "5.3", level=level, repo=repo)
            is None
        )


def test_another_repos_doc_is_not_reachable_through_the_repo_filter(leaky_hub):
    hub = HubHandle(root=leaky_hub)
    assert get_section(hub, "../icao-kb/icao-annex-2", "1.1", repo="arinc-kb") is None
    # the honest route still works
    assert get_section(hub, "icao-annex-2", "1.1", repo="icao-kb") is not None


def test_ids_with_dots_and_dashes_still_resolve(fed_hub):
    entry = fed_hub / "federation" / "arinc-kb"
    shutil.copytree(entry / "arinc-424", entry / "arinc-424.v2_x")
    r = get_section(HubHandle(root=fed_hub), "arinc-424.v2_x", "5.3", repo="arinc-kb")
    assert r is not None
    assert "restrictive airspace" in r.content.lower()


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges")
def test_a_symlinked_doc_dir_pointing_outside_the_repo_is_refused(leaky_hub):
    link = leaky_hub / "federation" / "arinc-kb" / "linked"
    os.symlink(leaky_hub / ".kb" / "secret-draft", link, target_is_directory=True)
    assert (
        get_section(HubHandle(root=leaky_hub), "linked", "5.3", repo="arinc-kb") is None
    )
    assert doc_dir(leaky_hub / "federation" / "arinc-kb", "linked") is None


def test_doc_dir_accepts_a_plain_id(tmp_path):
    assert doc_dir(tmp_path, "arinc-424") == tmp_path / "arinc-424"
    assert doc_dir(tmp_path, "../x") is None


def test_search_never_returns_an_unpublished_doc(leaky_hub):
    hits = search(HubHandle(root=leaky_hub), "TOPSECRET unpublished draft")
    assert all(SECRET not in h.content for h in hits)
    assert all(h.doc_id != "secret-draft" for h in hits)


def test_kb_get_refuses_traversal(leaky_hub, fixture_kb):
    result = runner.invoke(
        app,
        [
            "get",
            "../../.kb/secret-draft",
            "5.3",
            "--level",
            "l3",
            "--repo",
            "arinc-kb",
            "--kb-dir",
            str(fixture_kb),
            "--hub",
            str(leaky_hub),
        ],
    )
    assert SECRET not in result.output
    assert result.exit_code != 0


@pytest.mark.anyio
async def test_mcp_kb_get_section_refuses_traversal(leaky_hub):
    from mcp.shared.memory import create_connected_server_and_client_session as connect

    from strata_kb.mcp import ServerConfig, create_server

    server = create_server(ServerConfig(kb_dir=leaky_hub / ".kb", hub=str(leaky_hub)))
    async with connect(server, raise_exceptions=True) as client:
        for args in (
            {"doc": "arinc-kb:../../.kb/secret-draft", "section": "5.3", "level": "l3"},
            {"doc": "../../.kb/secret-draft", "section": "5.3", "repo": "arinc-kb"},
            {"doc": "../../.kb/secret-draft", "section": "5.3"},
        ):
            result = await client.call_tool("kb_get_section", args)
            text = "".join(getattr(c, "text", "") for c in result.content)
            assert SECRET not in text
            assert "arinc-kb:secret-draft" not in text


def test_web_doc_routes_refuse_traversal(leaky_hub):
    from starlette.testclient import TestClient

    from strata_kb.mcp import ServerConfig
    from strata_kb.serving.accounts import Accounts
    from strata_kb.web.app import create_app

    # With no account every /ui page redirects to the setup form; the guard
    # under test is the doc route itself.
    Accounts(leaky_hub / ".kb-auth" / "users.db").add("boss", "pw", "admin")
    token = "t" * 48
    config = ServerConfig(kb_dir=leaky_hub / ".kb", hub=str(leaky_hub))
    auth = {"Authorization": f"Bearer {token}"}
    with TestClient(create_app(config, token)) as c:
        for path in (
            "/api/docs/..%2F..%2F.kb%2Fsecret-draft",
            "/api/docs/..%2F..%2F.kb%2Fsecret-draft/sections/5.3?level=l3",
            "/api/docs/.hidden?repo=arinc-kb",
            "/ui/docs/..%2F..%2F.kb%2Fsecret-draft",
            "/ui/docs/..%2F..%2F.kb%2Fsecret-draft/5.3",
        ):
            resp = c.get(path, headers=auth)
            assert SECRET not in resp.text, path
            assert resp.status_code in (404, 400), (path, resp.status_code)
