import pytest

from aero_kb import kbcontext

BLOCK = """kb-context:
  version: a3f9c21
  refs:
    - arinc-424 §5.3
    - arinc-424 §5.3.2
  tags: [arinc424, airspace]
"""

TICKET = f"""# TAL-1580 — Hiển thị pop-up Restrictive Airspace

Là một dispatcher, tôi muốn click vào restrictive airspace.

Acceptance criteria:
- Hiển thị field P1 [arinc-424 §5.3]

{BLOCK}
Ghi chú thêm sau block.
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
        kbcontext.parse_ref("chỉ-có-doc-id")


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
        kbcontext.parse("ticket không có block nào")


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
    # Hash toàn chữ số với leading zero ("0123456") không được quote sẽ bị
    # PyYAML parse thành số nguyên bát phân (octal), phá pin version.
    ctx = kbcontext.KBContext(
        version="0123456", refs=[kbcontext.parse_ref("arinc-424 §5.3")]
    )
    rendered = kbcontext.render(ctx)
    assert '"0123456"' in rendered
    round_tripped = kbcontext.parse(rendered)
    assert round_tripped.version == "0123456"
    assert round_tripped == ctx


def test_parse_refs_scalar_raises_with_hint():
    with pytest.raises(kbcontext.KBContextError, match="danh sách"):
        kbcontext.parse("kb-context:\n  version: abc1234\n  refs: arinc-424 §5.3\n")


def test_parse_tags_scalar_raises_with_hint():
    with pytest.raises(kbcontext.KBContextError, match="danh sách"):
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
