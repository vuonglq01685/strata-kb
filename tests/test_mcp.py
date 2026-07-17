import pytest
from mcp.shared.memory import (
    create_connected_server_and_client_session as connect_client,
)

from center_kb import gitio
from center_kb.hub import HubHandle
from center_kb.kbcontext import build_context_block
from center_kb.mcp import ServerConfig, create_server, parse_args
from tests.conftest import make_fed_entry
from tests.test_ticketlint import REFS, _build_ticket


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
async def test_lists_exactly_five_tools(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert sorted(t.name for t in tools.tools) == [
            "kb_context_new", "kb_get_section", "kb_resolve", "kb_search",
            "kb_ticket_lint",
        ]


# Snapshot of the core four tools' wire contract (name -> parameter names).
# kb_ticket_lint is new (Task 3) and must not perturb these.
_CORE_FOUR_PARAMS = {
    "kb_search": {"query", "tags", "budget"},
    "kb_get_section": {"doc", "section", "level", "repo"},
    "kb_context_new": {"refs", "tags"},
    "kb_resolve": {"kb_context"},
}


@pytest.mark.anyio
async def test_core_four_tool_signatures_unchanged(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        by_name = {t.name: t for t in tools.tools}
        for name, params in _CORE_FOUR_PARAMS.items():
            assert set(by_name[name].inputSchema["properties"]) == params


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


def _golden_ticket(fed_hub) -> str:
    block, warning = build_context_block(
        HubHandle(root=fed_hub), REFS, tags=["airspace"]
    )
    assert warning is None
    return _build_ticket(block)


@pytest.mark.anyio
async def test_kb_ticket_lint_golden_ticket_passes(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_ticket_lint", {"ticket_markdown": _golden_ticket(fed_hub)}
        )
        assert "DoR: PASS" in _text(result)


@pytest.mark.anyio
async def test_kb_ticket_lint_broken_ref_fails(fed_hub):
    block, warning = build_context_block(
        HubHandle(root=fed_hub), REFS, tags=["airspace"]
    )
    assert warning is None
    rev = gitio.head_commit(gitio.git_root(fed_hub))
    bad_block = (
        f"kb-context:\n  version: {rev}\n  refs:\n    - arinc-kb:arinc-424 §9.9\n"
    )
    text = _build_ticket(
        block,
        overrides={
            "## KB context": f"```yaml\n{bad_block}```",
            "## Acceptance Criteria": (
                "- [ ] AC1: Show something per arinc-kb:arinc-424 §9.9"
            ),
        },
    )
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_ticket_lint", {"ticket_markdown": text})
        assert "DoR: FAIL" in _text(result)


@pytest.mark.anyio
async def test_kb_ticket_lint_hub_unreachable_returns_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(tmp_path / "missing"))
    server = create_server(config)
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_ticket_lint", {"ticket_markdown": "# T\n"}
        )
        assert "hub unreachable" in _text(result)


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


def test_ambiguity_note_silent_for_distant_hybrid_pair():
    # cả hai hybrid nhưng score cách xa (top rank đầu cả 2 leg vs hạng ~40)
    # — không phải "score closely"
    from center_kb.mcp import _ambiguity_note

    assert _ambiguity_note([_qr("hybrid", 0.0328), _qr("hybrid", 0.020)]) == ""


@pytest.mark.anyio
async def test_kb_search_shows_match_mode_not_raw_score(fed_hub):
    # RRF score tuyệt đối (0.02/0.03) vô nghĩa với người đọc — hiển thị
    # match mode thay vì số thô (đồng bộ với web UI)
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "restrictive airspace designation"}
        )
        assert "match=keyword" in _text(result)
        assert "score=" not in _text(result)
