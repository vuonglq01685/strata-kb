import pytest

# Contingency (see task-9-brief.md Step 1 + src/center_kb/mcp.py): SDK v2 (`mcp
# import Client`) has no released build on PyPI for this environment — use SDK v1
# (mcp>=1.2) with the in-memory client session `create_connected_server_and_client_session`
# instead of `mcp.Client`. Equivalent API: list_tools()/call_tool(name, args).
from mcp.shared.memory import create_connected_server_and_client_session as connect_client

from center_kb.mcp import ServerConfig, create_server, parse_args


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _text(result) -> str:
    return result.content[0].text


def test_parse_args_defaults():
    config = parse_args([])
    assert str(config.kb_dir) == ".kb"
    assert config.hub is None


def test_parse_args_hub():
    config = parse_args(["--kb", "x/.kb", "--hub", "git@host:kb-hub.git"])
    assert config.hub == "git@host:kb-hub.git"


@pytest.mark.anyio
async def test_lists_exactly_four_tools(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert sorted(t.name for t in tools.tools) == [
            "kb_context_new", "kb_get_section", "kb_resolve", "kb_search",
        ]


@pytest.mark.anyio
async def test_kb_search_returns_citation(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "airspace designation"}
        )
        assert "demo-doc §1.1" in _text(result)


@pytest.mark.anyio
async def test_kb_search_respects_budget(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        small = await client.call_tool(
            "kb_search", {"query": "records structure", "budget": 1}
        )
        # budget too small → only the first section is returned (search always returns >= 1)
        assert _text(small).count("--- [") == 1
        big = await client.call_tool(
            "kb_search", {"query": "records structure", "budget": 5000}
        )
        assert _text(big).count("--- [") == 2


@pytest.mark.anyio
async def test_kb_get_section_l3(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "demo-doc", "section": "1.1", "level": "l3"}
        )
        assert "Full raw text about airspace" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_unknown_doc_suggests(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "demodoc", "section": "1.1"}
        )
        assert "demo-doc" in _text(result)  # hints at the available doc


@pytest.mark.anyio
async def test_kb_resolve_reports_stale(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    block = f"kb-context:\n  version: {git_kb['rev1']}\n  refs:\n    - demo-doc §1.1\n"
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_resolve", {"kb_context": block})
        text = _text(result)
        assert "status=stale" in text
        assert "designation and type fields" in text  # content at the pinned version


@pytest.mark.anyio
async def test_kb_resolve_bad_block_returns_error_text(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_resolve", {"kb_context": "no block here"})
        assert "kb-context" in _text(result)


# --- Phase 3: hub enabled ---


def test_parse_args_transport_defaults():
    config = parse_args([])
    assert config.transport == "stdio"
    assert config.port == 8321


def test_parse_args_http():
    config = parse_args(["--transport", "http", "--host", "0.0.0.0", "--port", "9000"])
    assert config.transport == "http"
    assert config.host == "0.0.0.0"
    assert config.port == 9000


@pytest.mark.anyio
async def test_kb_search_reaches_hub_docs(fixture_kb, hub_worktree):
    server = create_server(
        ServerConfig(kb_dir=fixture_kb, hub=str(hub_worktree))
    )
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "restrictive airspace designation"}
        )
        assert "arinc-424 §5.3" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_falls_back_to_hub(fixture_kb, hub_worktree):
    server = create_server(
        ServerConfig(kb_dir=fixture_kb, hub=str(hub_worktree))
    )
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "arinc-424", "section": "5.3"}
        )
        assert "Restrictive" in _text(result)


def test_main_http_without_token_fails_fast(monkeypatch):
    from center_kb.mcp import main

    monkeypatch.delenv("CENTER_KB_HTTP_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        main(["--transport", "http"])


# --- kb_context_new ---


@pytest.mark.anyio
async def test_kb_context_new_single_ref(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new", {"refs": ["demo-doc §1.1"]}
        )
        text = _text(result)
        assert "kb-context:" in text
        assert f'version: "{git_kb["rev2"]}"' in text
        assert "- demo-doc §1.1" in text


@pytest.mark.anyio
async def test_kb_context_new_multi_ref(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new",
            {"refs": ["demo-doc §1.1", "demo-doc §1.2"], "tags": ["demo"]},
        )
        text = _text(result)
        assert "- demo-doc §1.1" in text
        assert "- demo-doc §1.2" in text
        assert "tags: [demo]" in text


@pytest.mark.anyio
async def test_kb_context_new_unresolvable_ref_returns_error_text(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new", {"refs": ["demo-doc §9.9"]}
        )
        text = _text(result)
        assert "9.9" in text
        assert "demo-doc" in text  # known-docs hint


@pytest.mark.anyio
async def test_kb_context_new_empty_refs_returns_error_text(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_context_new", {"refs": []})
        assert "is empty" in _text(result)


@pytest.mark.anyio
async def test_kb_context_new_dirty_warning_inline(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Airspace Records\n\nuncommitted edit\n\n## 1.2 Airway Records\n\nx\n",
        encoding="utf-8",
    )
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new", {"refs": ["demo-doc §1.1"]}
        )
        text = _text(result)
        assert "uncommitted changes" in text
        assert "kb-context:" in text


@pytest.mark.anyio
async def test_kb_context_new_with_hub_ref_pins_hub_version(
    git_kb, hub_worktree, run_git
):
    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    server = create_server(
        ServerConfig(kb_dir=git_kb["kb"], hub=str(hub_worktree))
    )
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new", {"refs": ["arinc-424 §5.3"]}
        )
        assert f'hub_version: "{hub_head}"' in _text(result)


# --- kb_search ambiguity annotation ---


@pytest.mark.anyio
async def test_kb_search_notes_close_scores(fixture_kb):
    # "records structure" scores demo-doc §1.1 and §1.2 exactly tied under
    # BM25Plus on this fixture — the clearest possible ambiguous case.
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "records structure"}
        )
        text = _text(result)
        assert "Note:" in text
        assert "demo-doc §1.1" in text
        assert "demo-doc §1.2" in text


@pytest.mark.anyio
async def test_kb_search_no_note_when_one_result_dominates(fixture_kb):
    # "airspace designation" scores §1.1 well above §1.2 (~55% relative gap)
    # on this fixture — not ambiguous.
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "airspace designation"}
        )
        assert "Note:" not in _text(result)
