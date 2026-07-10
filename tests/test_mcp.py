import pytest

# Contingency (xem task-9-brief.md Step 1 + src/aero_kb/mcp.py): SDK v2 (`mcp
# import Client`) chưa release trên PyPI của môi trường này — dùng SDK v1
# (mcp>=1.2) với client in-memory session `create_connected_server_and_client_session`
# thay cho `mcp.Client`. API tương đương: list_tools()/call_tool(name, args).
from mcp.shared.memory import create_connected_server_and_client_session as connect_client

from aero_kb.mcp import ServerConfig, create_server, parse_args


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _text(result) -> str:
    return result.content[0].text


def test_parse_args_defaults():
    config = parse_args([])
    assert str(config.kb_dir) == ".kb"
    assert config.hub is None


def test_parse_args_hub_kept_but_inactive():
    config = parse_args(["--kb", "x/.kb", "--hub", "git@host:kb-hub.git"])
    assert config.hub == "git@host:kb-hub.git"


@pytest.mark.anyio
async def test_lists_exactly_three_tools(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert sorted(t.name for t in tools.tools) == [
            "kb_get_section", "kb_resolve", "kb_search",
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
        # budget quá nhỏ → chỉ section đầu tiên được trả (search luôn trả >= 1)
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
        assert "demo-doc" in _text(result)  # gợi ý doc hiện có


@pytest.mark.anyio
async def test_kb_resolve_reports_stale(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    block = f"kb-context:\n  version: {git_kb['rev1']}\n  refs:\n    - demo-doc §1.1\n"
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_resolve", {"kb_context": block})
        text = _text(result)
        assert "status=stale" in text
        assert "designation and type fields" in text  # nội dung tại bản pin


@pytest.mark.anyio
async def test_kb_resolve_bad_block_returns_error_text(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_resolve", {"kb_context": "khong co block"})
        assert "kb-context" in _text(result)
