import pytest
from mcp.shared.memory import (
    create_connected_server_and_client_session as connect_client,
)

from center_kb.mcp import ServerConfig, create_server, parse_args
from tests.conftest import make_fed_entry


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _text(result) -> str:
    return result.content[0].text


def _config(fed_hub) -> ServerConfig:
    return ServerConfig(kb_dir=fed_hub / ".kb", hub=str(fed_hub))


def test_parse_args_requires_hub(tmp_path, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    kb = tmp_path / ".kb"
    kb.mkdir()
    with pytest.raises(SystemExit):
        parse_args(["--kb", str(kb)])


def test_parse_args_reads_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("CENTER_KB_HUB", raising=False)
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text("hub: /srv/kb-hub\n", encoding="utf-8")
    config = parse_args(["--kb", str(kb)])
    assert config.hub == "/srv/kb-hub"


def test_parse_args_flag_beats_env_and_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB", "/from-env")
    kb = tmp_path / ".kb"
    kb.mkdir()
    config = parse_args(["--kb", str(kb), "--hub", "/from-flag"])
    assert config.hub == "/from-flag"


@pytest.mark.anyio
async def test_lists_exactly_four_tools(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert sorted(t.name for t in tools.tools) == [
            "kb_context_new", "kb_get_section", "kb_resolve", "kb_search",
        ]


@pytest.mark.anyio
async def test_kb_search_returns_federation_citation(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "restrictive airspace designation"}
        )
        assert "arinc-kb:arinc-424 §5.3" in _text(result)
        assert "Condensed: restrictive airspace" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_l3_and_repo_param(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section",
            {"doc": "arinc-424", "section": "5.3", "level": "l3", "repo": "arinc-kb"},
        )
        assert "Full raw restrictive airspace" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_ambiguous_lists_candidates(fed_hub):
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "arinc-424", "section": "5.3"}
        )
        assert "dup-kb:arinc-424" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_not_found_lists_known_docs(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_get_section", {"doc": "ghost", "section": "1.1"}
        )
        assert "arinc-kb:arinc-424" in _text(result)


@pytest.mark.anyio
async def test_context_new_and_resolve_roundtrip(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        block = await client.call_tool(
            "kb_context_new", {"refs": ["arinc-424 §5.3"]}
        )
        assert "- arinc-kb:arinc-424 §5.3" in _text(block)
        resolved = await client.call_tool(
            "kb_resolve", {"kb_context": _text(block)}
        )
        assert "status=ok" in _text(resolved)


@pytest.mark.anyio
async def test_hub_unreachable_returns_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(tmp_path / "missing"))
    server = create_server(config)
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_search", {"query": "anything"})
        assert "hub unreachable" in _text(result)
