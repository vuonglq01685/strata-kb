from center_kb import kbcontext
from center_kb.hub import HubHandle
from center_kb.kbcontext import KBContext, KBRef, build_context_block
from center_kb.resolve import render_resolved, resolve_refs
from tests.conftest import make_fed_entry


def _ctx_for(fed_hub, refs):
    block, _ = build_context_block(HubHandle(root=fed_hub), refs)
    return kbcontext.parse(block)


def test_resolve_ok_roundtrip(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    results = resolve_refs(handle, ctx)
    assert [r.status for r in results] == ["ok"]
    assert "Condensed: restrictive airspace" in results[0].content
    assert results[0].citation.startswith("arinc-kb:arinc-424 §5.3")


def test_resolve_stale_after_republish(fed_hub, run_git):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"),
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "amendment republished")
    results = resolve_refs(handle, ctx)
    assert results[0].status == "stale"
    # nội dung trả về vẫn là bản pinned
    assert "designation codes" in results[0].content


def test_resolve_unqualified_ref_disambiguated(fed_hub):
    handle = HubHandle(root=fed_hub)
    head_block, _ = build_context_block(handle, ["arinc-kb:arinc-424 §5.3"])
    version = kbcontext.parse(head_block).version
    ctx = KBContext(
        version=version, refs=[KBRef(doc_id="arinc-424", section_id="5.3")]
    )
    results = resolve_refs(handle, ctx)
    assert results[0].status == "ok"


def test_resolve_unqualified_ambiguous_is_broken(fed_hub, run_git):
    handle = HubHandle(root=fed_hub)
    head_block, _ = build_context_block(handle, ["arinc-kb:arinc-424 §5.3"])
    version = kbcontext.parse(head_block).version
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    ctx = KBContext(
        version=version, refs=[KBRef(doc_id="arinc-424", section_id="5.3")]
    )
    results = resolve_refs(handle, ctx)
    assert results[0].status == "broken"
    assert "re-pin" in results[0].reason


def test_resolve_legacy_block_broken_with_hint(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = KBContext(
        version="deadbee",  # commit của repo local cũ — không có trong hub
        refs=[KBRef(doc_id="arinc-424", section_id="5.3")],
    )
    results = resolve_refs(handle, ctx)
    assert all(r.status == "broken" for r in results)
    assert "re-pin" in results[0].reason


def test_render_resolved_shows_status(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    text = render_resolved(resolve_refs(handle, ctx))
    assert "status=ok" in text
