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


def _qr(mode: str, score: float, cite: str = "r:d §1"):
    from center_kb.query import QueryResult

    return QueryResult(
        doc_id="d", section_id="1", title="t", score=score,
        citation=cite, content="c", tokens=1, match_mode=mode,
    )


def test_ambiguity_note_silent_for_single_leg_adjacent_ranks():
    # RRF: rank kề nhau cùng leg luôn cách ~1.6% — gap tương đối chỉ tạo noise
    from center_kb.mcp import _ambiguity_note

    note = _ambiguity_note([_qr("keyword", 1 / 61), _qr("keyword", 1 / 62)])
    assert note == ""


def test_ambiguity_note_fires_when_top2_both_hybrid():
    # cả hai được 2 leg xác nhận → ambiguous thật, đáng nhắc review cả hai
    from center_kb.mcp import _ambiguity_note

    note = _ambiguity_note(
        [_qr("hybrid", 0.032, "a:x §1"), _qr("hybrid", 0.031, "b:y §2")]
    )
    assert "score closely" in note
    assert "a:x §1" in note and "b:y §2" in note


def test_ambiguity_note_fires_on_exact_tie():
    from center_kb.mcp import _ambiguity_note

    assert "score closely" in _ambiguity_note(
        [_qr("keyword", 0.016), _qr("keyword", 0.016)]
    )


@pytest.mark.anyio
async def test_kb_search_no_note_for_ordinary_keyword_ranking(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "airspace designation type"}
        )
        assert "score closely" not in _text(result)  # 2 kết quả keyword rank kề
