import pytest
from mcp.shared.memory import (
    create_connected_server_and_client_session as connect_client,
)

from strata_kb import gitio
from strata_kb.hub import HubHandle
from strata_kb.kbcontext import build_context_block
from strata_kb.mcp import ServerConfig, create_server, parse_args
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
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    kb = tmp_path / ".kb"
    kb.mkdir()
    with pytest.raises(SystemExit):
        parse_args(["--kb", str(kb)])


def test_parse_args_reads_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    kb = tmp_path / ".kb"
    kb.mkdir()
    (kb / "config.yaml").write_text("hub: /srv/kb-hub\n", encoding="utf-8")
    config = parse_args(["--kb", str(kb)])
    assert config.hub == "/srv/kb-hub"


def test_parse_args_flag_beats_env_and_config(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATA_KB_HUB", "/from-env")
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
async def test_kb_search_no_usable_terms_renders_note_in_band(fed_hub):
    """F-C9 review round 2: neither rendering surface had a test proving a
    note actually arrives. Real (unmocked) search_detailed() call — an MCP
    agent never sees stderr, so the note must travel in the tool text itself,
    ahead of the 'No matching section found' message."""
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_search", {"query": "§§§ ---"})
        text = _text(result)
        assert "no searchable terms" in text
        assert text.index("no searchable terms") < text.index(
            "No matching section found"
        )


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
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache"))
    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(tmp_path / "missing"))
    server = create_server(config)
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_ticket_lint", {"ticket_markdown": "# T\n"}
        )
        assert "hub unreachable" in _text(result)


@pytest.mark.anyio
async def test_hub_locked_cache_returns_guidance_not_a_crash(
    fed_hub, monkeypatch, caplog
):
    """Important 1 (Wave G fix round 2 re-review): resolve_hub can now raise
    gitio.GitError (hub.py's _discard_cache, when a stale cache's removal is
    blocked -- e.g. a locked .kb-work/search.sqlite3, and a serving MCP
    process is exactly the kind of process that would be holding it open).
    Before the round-3 fix, `_hub()` let that GitError propagate out of the
    tool call as an unhandled crash instead of the same "hub unreachable"
    guidance every other unreachable-hub path already returns. Fakes
    strata_kb.hub.resolve_hub itself, not some mcp-module alias -- `_hub()`
    re-imports the name fresh on every call (see the concurrency test
    below).

    N-6 (Wave G fix round 4 re-review): the round-3 guard swallowed the
    GitError with no log record -- pin that the caught exception now
    reaches the log at warning, the same way resolve_hub's own clone/pull
    failures already do (hub.py)."""
    from strata_kb import hub as hub_mod

    detail = "could not remove the stale hub cache at '...'"

    def fake_resolve_hub(hub_str):
        raise gitio.GitError(detail)

    monkeypatch.setattr(hub_mod, "resolve_hub", fake_resolve_hub)
    server = create_server(_config(fed_hub))
    with caplog.at_level("WARNING", logger="strata_kb.mcp"):
        async with connect_client(server, raise_exceptions=True) as client:
            result = await client.call_tool("kb_search", {"query": "anything"})
            assert "hub unreachable" in _text(result)
    assert any(
        r.name == "strata_kb.mcp" and detail in r.message for r in caplog.records
    ), caplog.records


@pytest.mark.anyio
async def test_hub_unreachable_returns_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(tmp_path / "cache"))
    config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(tmp_path / "missing"))
    server = create_server(config)
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_search", {"query": "anything"})
        assert "hub unreachable" in _text(result)


def _qr(mode: str, score: float, cite: str = "r:d §1"):
    from strata_kb.mdutils import count_tokens
    from strata_kb.query import QueryResult

    return QueryResult(
        doc_id="d", section_id="1", title="t", score=score,
        citation=cite, content="c", tokens=1, content_tokens=count_tokens("c"),
        match_mode=mode,
    )


def test_ambiguity_note_silent_for_single_leg_adjacent_ranks():
    # RRF: adjacent ranks within one leg always differ ~1.6% — a relative gap only adds noise
    from strata_kb.mcp import _ambiguity_note

    note = _ambiguity_note([_qr("keyword", 1 / 61), _qr("keyword", 1 / 62)])
    assert note == ""


def test_ambiguity_note_fires_when_top2_both_hybrid():
    # both confirmed by 2 legs → genuinely ambiguous, worth prompting review of both
    from strata_kb.mcp import _ambiguity_note

    note = _ambiguity_note(
        [_qr("hybrid", 0.032, "a:x §1"), _qr("hybrid", 0.031, "b:y §2")]
    )
    assert "score closely" in note
    assert "a:x §1" in note and "b:y §2" in note


def test_ambiguity_note_fires_on_exact_tie():
    from strata_kb.mcp import _ambiguity_note

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
        assert "score closely" not in _text(result)  # 2 keyword results at adjacent ranks


def test_ambiguity_note_silent_for_distant_hybrid_pair():
    # both hybrid but scores far apart (top rank in both legs vs rank ~40)
    # — not "score closely"
    from strata_kb.mcp import _ambiguity_note

    assert _ambiguity_note([_qr("hybrid", 0.0328), _qr("hybrid", 0.020)]) == ""


@pytest.mark.anyio
async def test_kb_search_shows_match_mode_not_raw_score(fed_hub):
    # absolute RRF scores (0.02/0.03) are meaningless to the reader — show
    # the match mode instead of raw numbers (in sync with the web UI)
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "restrictive airspace designation"}
        )
        assert "match=keyword" in _text(result)
        assert "score=" not in _text(result)


def test_create_server_warms_the_native_import(fed_hub, monkeypatch):
    """F-C1: the warm-up must happen while create_server runs (no loop yet),
    not on the first tool call (on the loop)."""
    from strata_kb import mcp as mcp_mod
    from strata_kb import searchdb

    calls = []
    monkeypatch.setattr(searchdb, "warm_vec", lambda: (calls.append(1), True)[1])
    mcp_mod.create_server(_config(fed_hub))
    assert calls == [1]


@pytest.mark.anyio
async def test_tool_body_does_not_block_the_event_loop(fed_hub, monkeypatch):
    """F-C1, second layer: a sync tool body run inline on the loop starves
    every other task. With the body on a worker thread the loop keeps ticking."""
    import asyncio
    import time as _time

    from strata_kb import mcp as mcp_mod

    def slow_search(*args, **kwargs):
        _time.sleep(0.5)
        from strata_kb.query import SearchOutcome

        return SearchOutcome(results=[])

    monkeypatch.setattr(mcp_mod, "search_detailed", slow_search)
    server = create_server(_config(fed_hub))
    ticks = 0

    async def heartbeat():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    async with connect_client(server, raise_exceptions=True) as client:
        hb = asyncio.create_task(heartbeat())
        await client.call_tool("kb_search", {"query": "airspace"})
        hb.cancel()
    assert ticks >= 5, f"event loop was starved during the tool call (ticks={ticks})"


@pytest.mark.anyio
async def test_hub_resolution_is_serialized_under_concurrent_calls(fed_hub, monkeypatch):
    """R20 (final-branch review, Important): tool bodies now run on their own
    worker threads concurrently (F-C1's fix, above) — two `kb_search` calls
    in flight at once used to be impossible (everything ran inline on the
    single event-loop thread) and now genuinely race. `hub.resolve_hub`
    clones/pulls into a cache shared by every call, so without a lock around
    it in `_hub()`, two concurrent URL-hub resolutions could run
    `git clone`/`git pull` against the same directory at the same time.
    `_hub()` does `from strata_kb.hub import resolve_hub` fresh on every
    call, so the fake must replace `strata_kb.hub.resolve_hub` itself (the
    name `_hub()` actually resolves), not some module-level alias in
    `strata_kb.mcp`."""
    import asyncio
    import threading as _threading
    import time as _time

    from strata_kb import hub as hub_mod
    from strata_kb.hub import HubHandle

    lock = _threading.Lock()
    active = 0
    overlap_seen = False

    def fake_resolve_hub(hub_str):
        nonlocal active, overlap_seen
        with lock:
            active += 1
            if active > 1:
                overlap_seen = True
        _time.sleep(0.2)
        with lock:
            active -= 1
        return HubHandle(root=fed_hub)

    monkeypatch.setattr(hub_mod, "resolve_hub", fake_resolve_hub)
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        results = await asyncio.gather(
            client.call_tool("kb_search", {"query": "airspace"}),
            client.call_tool("kb_search", {"query": "runway"}),
        )
    assert overlap_seen is False, "resolve_hub ran concurrently — _hub()'s lock is missing"
    for result in results:
        assert result.isError is False


@pytest.mark.anyio
async def test_kb_search_too_many_tags_returns_message_not_error(fed_hub):
    """F-C10 addition 1 (MCP half): `tags` is agent-supplied on this tool —
    an oversized list must come back as in-band tool text, not a raised
    ValueError the agent sees as a tool error."""
    from strata_kb.searchdb import MAX_TAGS

    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search",
            {"query": "airspace", "tags": [f"t{i}" for i in range(MAX_TAGS + 1)]},
        )
        assert result.isError is False, "should be a normal tool result, not an error"
        assert "too many tags" in _text(result)


@pytest.mark.anyio
async def test_kb_search_index_busy_returns_message_not_error(fed_hub, monkeypatch):
    """F-C10 addition 2: the CLI already turns IndexBusyError into a clean
    message (Task 4) — kb_search must do the same in-band, not raise."""
    from strata_kb import mcp as mcp_mod
    from strata_kb.searchdb import IndexBusyError

    def raise_busy(*a, **k):
        raise IndexBusyError("search index search.db is in use by another process")

    monkeypatch.setattr(mcp_mod, "search_detailed", raise_busy)
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_search", {"query": "airspace"})
        assert result.isError is False, "should be a normal tool result, not an error"
        assert _text(result) == "search index search.db is in use by another process"


@pytest.mark.anyio
async def test_kb_search_client_db_error_returns_message_not_error(
    fed_hub, monkeypatch
):
    """F-C10 addition 2: a client-classified DatabaseError (e.g. a lost
    UNIQUE race) must come back as clean in-band text, mirroring the CLI's
    wording, not a raised exception."""
    import sqlite3

    from strata_kb import mcp as mcp_mod

    def raise_integrity(*a, **k):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: sections.repo_id")

    monkeypatch.setattr(mcp_mod, "search_detailed", raise_integrity)
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_search", {"query": "airspace"})
        assert result.isError is False, "should be a normal tool result, not an error"
        assert "Error executing tool" not in _text(result)
        assert "search index rejected the query" in _text(result)
        assert "UNIQUE constraint failed" in _text(result)


@pytest.mark.anyio
async def test_kb_search_unrelated_value_error_is_not_swallowed(fed_hub, monkeypatch):
    """F-C10 review finding 1: `except ValueError` was too coarse —
    `pydantic.ValidationError` (raised deep in the search path when a
    federation `_manifest.yaml` is malformed) is also a `ValueError`
    subclass but is NOT the tag-cap refusal. Dressing it up as clean
    `isError=False` tool text would be indistinguishable from a real search
    answer — the worst place for this to happen. Only
    `searchdb.TooManyTagsError` gets the clean in-band message; any other
    ValueError must keep propagating as a tool error."""
    from strata_kb import mcp as mcp_mod

    def raise_unrelated(*a, **k):
        raise ValueError("3 validation errors for Manifest")

    monkeypatch.setattr(mcp_mod, "search_detailed", raise_unrelated)
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_search", {"query": "airspace"})
        assert result.isError is True, "must surface as a tool error, not a normal result"
        assert "validation errors" in _text(result)


@pytest.mark.anyio
async def test_kb_search_corrupt_db_error_still_propagates(fed_hub, monkeypatch):
    """F-C10 review finding 2: addition 2's re-raise branch
    (`if classify_db_error(exc) != "client": raise`) was untested — a
    genuinely corrupt index (after `_search_index`'s rebuild-once already
    failed) must NOT be returned as a clean `isError=False`
    'search index rejected the query' message; it must keep propagating.
    Mirrors the CLI's `test_query_lock_db_error_still_propagates`."""
    import sqlite3

    from strata_kb import mcp as mcp_mod

    def raise_corrupt(*a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(mcp_mod, "search_detailed", raise_corrupt)
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_search", {"query": "airspace"})
        assert result.isError is True, "must surface as a tool error, not a normal result"
        assert "search index rejected the query" not in _text(result)
        assert "database disk image is malformed" in _text(result)


@pytest.mark.anyio
async def test_kb_get_section_level_validation(fed_hub):
    server = create_server(_config(fed_hub))
    async with connect_client(server, raise_exceptions=True) as client:
        bad = await client.call_tool(
            "kb_get_section",
            {"doc": "arinc-kb:arinc-424", "section": "5.3", "level": "verbatim"},
        )
        assert "level 'verbatim' is invalid — use 'l2' or 'l3'." in _text(bad)
        good = await client.call_tool(
            "kb_get_section",
            {"doc": "arinc-kb:arinc-424", "section": "5.3", "level": "L3"},
        )
        assert "Verbatim" in _text(good)
