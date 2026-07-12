import pytest

from center_kb import kbcontext

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


def test_build_context_block_single_ref_pins_head(git_kb):
    block, warning = kbcontext.build_context_block(
        git_kb["kb"], ["demo-doc §1.1"]
    )
    assert warning is None
    assert "kb-context:" in block
    assert f'version: "{git_kb["rev2"]}"' in block
    assert "- demo-doc §1.1" in block


def test_build_context_block_multi_ref(git_kb):
    block, _ = kbcontext.build_context_block(
        git_kb["kb"], ["demo-doc §1.1", "demo-doc §1.2"], tags=["demo", "airspace"]
    )
    assert "- demo-doc §1.1" in block
    assert "- demo-doc §1.2" in block
    assert "tags: [demo, airspace]" in block


def test_build_context_block_rejects_unresolvable_ref(git_kb):
    with pytest.raises(kbcontext.KBRefNotFoundError, match="9.9"):
        kbcontext.build_context_block(git_kb["kb"], ["demo-doc §9.9"])


def test_build_context_block_rejects_empty_refs(git_kb):
    with pytest.raises(kbcontext.KBContextError, match="is empty"):
        kbcontext.build_context_block(git_kb["kb"], [])


def test_build_context_block_dirty_warning(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Airspace Records\n\nuncommitted edit\n\n## 1.2 Airway Records\n\nx\n",
        encoding="utf-8",
    )
    block, warning = kbcontext.build_context_block(git_kb["kb"], ["demo-doc §1.1"])
    assert warning is not None
    assert "uncommitted changes" in warning
    assert "kb-context:" in block  # block is still produced alongside the warning


def test_build_context_block_with_hub_ref_pins_hub_version(
    git_kb, hub_worktree, run_git
):
    from center_kb.hub import HubHandle

    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    block, _ = kbcontext.build_context_block(
        git_kb["kb"], ["arinc-424 §5.3"], hub=HubHandle(root=hub_worktree)
    )
    assert f'hub_version: "{hub_head}"' in block
