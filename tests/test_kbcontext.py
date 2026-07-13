import pytest

from center_kb import kbcontext
from center_kb.hub import HubHandle
from center_kb.kbcontext import (
    KBContextError,
    KBRefNotFoundError,
    build_context_block,
    parse,
)
from tests.conftest import make_fed_entry

BLOCK = """kb-context:
  version: a3f9c21
  refs:
    - arinc-424 §5.3
    - arinc-424 §5.3.2
  tags: [arinc424, airspace]
"""

TICKET = f"""# TAL-1580 — Show Restrictive Airspace pop-up

As a dispatcher, I want to click on a restrictive airspace.

Acceptance criteria:
- Show field P1 [arinc-424 §5.3]

{BLOCK}
Additional notes after the block.
"""


def test_parse_ref_standard():
    ref = kbcontext.parse_ref("arinc-424 §5.3")
    assert ref.doc_id == "arinc-424"
    assert ref.section_id == "5.3"
    assert str(ref) == "arinc-424 §5.3"


def test_parse_ref_without_section_mark():
    ref = kbcontext.parse_ref("arinc-424 5.3.2")
    assert ref.section_id == "5.3.2"


def test_parse_ref_invalid_raises_with_hint():
    with pytest.raises(kbcontext.KBContextError, match="§"):
        kbcontext.parse_ref("just-a-doc-id")


def test_parse_pure_block():
    ctx = kbcontext.parse(BLOCK)
    assert ctx.version == "a3f9c21"
    assert [str(r) for r in ctx.refs] == ["arinc-424 §5.3", "arinc-424 §5.3.2"]
    assert ctx.tags == ["arinc424", "airspace"]


def test_parse_block_embedded_in_ticket():
    ctx = kbcontext.parse(TICKET)
    assert ctx.version == "a3f9c21"
    assert len(ctx.refs) == 2


def test_parse_missing_block_raises():
    with pytest.raises(kbcontext.KBContextError, match="kb-context"):
        kbcontext.parse("a ticket with no block at all")


def test_parse_missing_version_raises():
    with pytest.raises(kbcontext.KBContextError, match="version"):
        kbcontext.parse("kb-context:\n  refs:\n    - a §1\n")


def test_parse_missing_refs_raises():
    with pytest.raises(kbcontext.KBContextError, match="refs"):
        kbcontext.parse("kb-context:\n  version: abc1234\n")


def test_render_roundtrip():
    ctx = kbcontext.parse(BLOCK)
    rendered = kbcontext.render(ctx)
    assert kbcontext.parse(rendered) == ctx
    assert "§5.3" in rendered


def test_render_roundtrip_leading_zero_version():
    # An all-digit hash with a leading zero ("0123456"), if left unquoted,
    # gets parsed by PyYAML as an octal integer, corrupting the pinned version.
    ctx = kbcontext.KBContext(
        version="0123456", refs=[kbcontext.parse_ref("arinc-424 §5.3")]
    )
    rendered = kbcontext.render(ctx)
    assert '"0123456"' in rendered
    round_tripped = kbcontext.parse(rendered)
    assert round_tripped.version == "0123456"
    assert round_tripped == ctx


def test_parse_refs_scalar_raises_with_hint():
    with pytest.raises(kbcontext.KBContextError, match="list"):
        kbcontext.parse("kb-context:\n  version: abc1234\n  refs: arinc-424 §5.3\n")


def test_parse_tags_scalar_raises_with_hint():
    with pytest.raises(kbcontext.KBContextError, match="list"):
        kbcontext.parse(
            "kb-context:\n  version: abc1234\n  refs:\n    - a §1\n  tags: airspace\n"
        )


# --- Phase 3: hub_version + repo-prefixed refs ---


def test_parse_ref_with_repo_prefix():
    ref = kbcontext.parse_ref("crew-ops:roster-sop §3.2")
    assert ref.repo_id == "crew-ops"
    assert ref.doc_id == "roster-sop"
    assert ref.section_id == "3.2"
    assert str(ref) == "crew-ops:roster-sop §3.2"


def test_parse_ref_without_prefix_has_no_repo():
    ref = kbcontext.parse_ref("arinc-424 §5.3")
    assert ref.repo_id is None
    assert str(ref) == "arinc-424 §5.3"


def test_parse_block_with_hub_version():
    text = """kb-context:
  version: "4f2a91c"
  hub_version: "a3f9c21"
  refs:
    - arinc-424 §5.3
"""
    ctx = kbcontext.parse(text)
    assert ctx.version == "4f2a91c"
    assert ctx.hub_version == "a3f9c21"


def test_parse_block_without_hub_version_backward_compat():
    text = """kb-context:
  version: "4f2a91c"
  refs:
    - demo-doc §1.1
"""
    ctx = kbcontext.parse(text)
    assert ctx.hub_version is None


def test_render_with_hub_version_roundtrip():
    ctx = kbcontext.KBContext(
        version="4f2a91c",
        hub_version="a3f9c21",
        refs=[kbcontext.parse_ref("arinc-424 §5.3")],
        tags=["arinc424"],
    )
    rendered = kbcontext.render(ctx)
    assert 'hub_version: "a3f9c21"' in rendered
    assert kbcontext.parse(rendered).hub_version == "a3f9c21"


def test_render_without_hub_version_unchanged_format():
    ctx = kbcontext.KBContext(
        version="4f2a91c", refs=[kbcontext.parse_ref("demo-doc §1.1")]
    )
    rendered = kbcontext.render(ctx)
    assert "hub_version" not in rendered


# --- build_context_block() ---


def test_build_block_pins_hub_head_and_qualifies(fed_hub, run_git):
    block, warning = build_context_block(HubHandle(root=fed_hub), ["arinc-424 §5.3"])
    head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    assert f'version: "{head}"' in block
    assert "- arinc-kb:arinc-424 §5.3" in block
    assert "hub_version" not in block
    assert warning is None
    assert parse(block).refs[0].repo_id == "arinc-kb"


def test_build_block_multiple_refs_and_tags(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3", "icao-annex-2 §1.1"],
        tags=["airspace"],
    )
    assert "- arinc-kb:arinc-424 §5.3" in block
    assert "- icao-kb:icao-annex-2 §1.1" in block
    assert "tags: [airspace]" in block


def test_build_block_unknown_ref_raises(fed_hub):
    with pytest.raises(KBRefNotFoundError):
        build_context_block(HubHandle(root=fed_hub), ["ghost-doc §9.9"])


def test_build_block_unknown_section_raises(fed_hub):
    with pytest.raises(KBRefNotFoundError):
        build_context_block(HubHandle(root=fed_hub), ["arinc-424 §9.9"])


def test_build_block_ambiguous_doc_raises(fed_hub):
    make_fed_entry(fed_hub / "federation", "dup-kb", "arinc-424", sec_id="5.3")
    with pytest.raises(KBContextError) as exc:
        build_context_block(HubHandle(root=fed_hub), ["arinc-424 §5.3"])
    assert "dup-kb:arinc-424" in str(exc.value)


def test_build_block_stale_hub_warns(fed_hub):
    handle = HubHandle(root=fed_hub, stale=True, age_seconds=120.0)
    _, warning = build_context_block(handle, ["arinc-kb:arinc-424 §5.3"])
    assert warning is not None and "stale" in warning
