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


def test_parse_ref_nested_repo_qualifier():
    from center_kb.kbcontext import parse_ref

    ref = parse_ref("mid/repo-x:doc-a §1.1")
    assert ref.repo_id == "mid/repo-x"
    assert ref.doc_id == "doc-a"
    assert ref.section_id == "1.1"
    assert str(ref) == "mid/repo-x:doc-a §1.1"


def test_parse_ref_flat_qualifier_unchanged():
    from center_kb.kbcontext import parse_ref

    ref = parse_ref("repo-x:doc-a §1.1")
    assert ref.repo_id == "repo-x"


# --- Task 1: tag vocabulary + derivation ---


def test_tag_vocabulary_is_every_tag_on_the_federation(fed_hub):
    from center_kb.federation import load_federation

    vocab = kbcontext.tag_vocabulary(load_federation(fed_hub / "federation"))

    # fed_hub publishes arinc-kb:arinc-424 (tags: arinc424) and
    # icao-kb:icao-annex-2 (tags: icao, airspace).
    assert vocab == {"arinc424": "arinc424", "icao": "icao", "airspace": "airspace"}


def test_tag_vocabulary_keeps_the_first_spelling_in_dfs_order(fed_hub):
    from center_kb.federation import load_federation

    # 'aaa-kb' sorts before 'icao-kb', so its spelling of the same tag wins:
    # iter_entry_dirs() walks the federation name-ascending.
    make_fed_entry(fed_hub / "federation", "aaa-kb", "aaa-doc", tags=["AIRSPACE"])

    vocab = kbcontext.tag_vocabulary(load_federation(fed_hub / "federation"))

    assert vocab["airspace"] == "AIRSPACE"


def test_tag_vocabulary_skips_blank_tags(fed_hub):
    from center_kb.federation import load_federation

    make_fed_entry(fed_hub / "federation", "blank-kb", "blank-doc", tags=["  ", ""])

    vocab = kbcontext.tag_vocabulary(load_federation(fed_hub / "federation"))

    assert "" not in vocab
    assert len(vocab) == 3


def test_derive_tags_takes_the_tags_of_the_refs_documents(fed_hub):
    from center_kb.federation import load_federation

    repos = load_federation(fed_hub / "federation")
    refs = [kbcontext.parse_ref("arinc-kb:arinc-424 §5.3")]

    assert kbcontext.derive_tags(repos, refs) == ["arinc424"]


def test_derive_tags_unions_across_repos_sorted_by_lowercase_key(fed_hub):
    from center_kb.federation import load_federation

    repos = load_federation(fed_hub / "federation")
    refs = [
        kbcontext.parse_ref("arinc-kb:arinc-424 §5.3"),
        kbcontext.parse_ref("icao-kb:icao-annex-2 §1.1"),
    ]

    assert kbcontext.derive_tags(repos, refs) == ["airspace", "arinc424", "icao"]


def test_derive_tags_resolves_spelling_through_the_vocabulary_regardless_of_ref_order(
    fed_hub,
):
    """The previous suite compared `derive_tags` against itself on a
    fixture with no spelling clash, so it could not fail on the one
    order-dependence that actually existed: folding each ref's tags into
    the result in caller order let whichever ref came first pick the
    spelling. 'aaa-kb' sorts before 'icao-kb' in the federation DFS, so
    `tag_vocabulary` (and therefore `kb tags`) resolves the 'airspace' /
    'AIRSPACE' clash to 'AIRSPACE' — `derive_tags` must resolve to that
    same spelling no matter which ref the caller lists first. Against the
    pre-fix implementation, the reversed order used to return 'airspace'
    (icao-kb's spelling) instead."""
    from center_kb.federation import load_federation

    make_fed_entry(fed_hub / "federation", "aaa-kb", "aaa-doc", tags=["AIRSPACE"])
    repos = load_federation(fed_hub / "federation")
    aaa_ref = kbcontext.parse_ref("aaa-kb:aaa-doc §1.1")
    icao_ref = kbcontext.parse_ref("icao-kb:icao-annex-2 §1.1")
    expected = ["AIRSPACE", "icao"]

    assert kbcontext.derive_tags(repos, [aaa_ref, icao_ref]) == expected
    assert kbcontext.derive_tags(repos, [icao_ref, aaa_ref]) == expected


def test_derive_tags_dedupes_two_refs_into_one_document(fed_hub):
    from center_kb.federation import load_federation

    repos = load_federation(fed_hub / "federation")
    refs = [
        kbcontext.parse_ref("arinc-kb:arinc-424 §5.3"),
        kbcontext.parse_ref("arinc-kb:arinc-424 §5.3"),
    ]

    assert kbcontext.derive_tags(repos, refs) == ["arinc424"]


def test_derive_tags_ignores_a_document_absent_from_its_repo_index(fed_hub):
    from center_kb import models
    from center_kb.federation import load_federation

    # The document dir and its _manifest.yaml still exist, so the ref itself
    # resolves — but index.yaml no longer lists it, so it contributes no tag
    # and that is not an error.
    models.save_yaml_model(
        fed_hub / "federation" / "arinc-kb" / "index.yaml", models.KBIndex()
    )
    repos = load_federation(fed_hub / "federation")

    assert kbcontext.derive_tags(
        repos, [kbcontext.parse_ref("arinc-kb:arinc-424 §5.3")]
    ) == []


def test_derive_tags_ignores_an_unqualified_ref(fed_hub):
    from center_kb.federation import load_federation

    # A ref that has not been auto-qualified yet has repo_id None and cannot
    # be attributed to a repo. build_context_block always qualifies first;
    # this pins that derive_tags does not guess.
    repos = load_federation(fed_hub / "federation")

    assert kbcontext.derive_tags(repos, [kbcontext.parse_ref("arinc-424 §5.3")]) == []


def test_unknown_tag_error_is_a_kb_context_error():
    assert issubclass(kbcontext.UnknownTagError, KBContextError)


def test_suggest_tags_returns_the_nearest_canonical_spellings():
    vocab = {"airspace": "AirSpace", "arinc424": "arinc424", "icao": "icao"}

    assert kbcontext.suggest_tags("airspce", vocab) == ["AirSpace"]


def test_suggest_tags_is_case_and_whitespace_insensitive():
    vocab = {"airspace": "airspace"}

    assert kbcontext.suggest_tags("  AIRSPACE  ", vocab) == ["airspace"]


def test_suggest_tags_returns_empty_for_nothing_close():
    vocab = {"airspace": "airspace", "icao": "icao"}

    assert kbcontext.suggest_tags("zzzzzzzz", vocab) == []


def test_suggest_tags_on_an_empty_vocabulary_is_empty():
    assert kbcontext.suggest_tags("airspace", {}) == []


# --- Task 2: build_context_block derives and validates ---


def test_build_block_derives_tags_when_none_are_passed(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"],
    )
    assert "tags: [airspace, arinc424, icao]" in block


def test_build_block_derived_tags_do_not_depend_on_ref_order(fed_hub):
    forward, _ = build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"],
    )
    reverse, _ = build_context_block(
        HubHandle(root=fed_hub),
        ["icao-kb:icao-annex-2 §1.1", "arinc-kb:arinc-424 §5.3"],
    )
    assert parse(forward).tags == parse(reverse).tags


def test_build_block_omits_tags_line_when_nothing_is_derivable(fed_hub):
    from center_kb import models

    models.save_yaml_model(
        fed_hub / "federation" / "arinc-kb" / "index.yaml", models.KBIndex()
    )
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"]
    )
    assert "tags:" not in block
    assert parse(block).tags == []


def test_build_block_explicit_tag_is_rendered_in_canonical_spelling(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["ICAO"]
    )
    assert "tags: [icao]" in block


def test_build_block_explicit_tags_replace_rather_than_extend_derived(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["icao"]
    )
    # 'arinc424' would be derived from arinc-424's own document; an explicit
    # list replaces the derived set outright so a block is either fully
    # derived or fully caller-chosen, never an unattributable mix.
    assert parse(block).tags == ["icao"]


def test_build_block_explicit_tags_dedupe_by_case(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["icao", "ICAO"]
    )
    assert parse(block).tags == ["icao"]


def test_build_block_unknown_tag_raises(fed_hub):
    with pytest.raises(kbcontext.UnknownTagError) as exc:
        build_context_block(
            HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["ghost-tag"]
        )
    assert "ghost-tag" in str(exc.value)
    assert "kb tags" in str(exc.value)


def test_build_block_unknown_tag_suggests_the_nearest_real_tag(fed_hub):
    with pytest.raises(kbcontext.UnknownTagError) as exc:
        build_context_block(
            HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["airspce"]
        )
    assert "airspace" in str(exc.value)


def test_build_block_empty_vocabulary_names_the_real_cause(fed_hub):
    from center_kb import models

    for rid in ("arinc-kb", "icao-kb"):
        models.save_yaml_model(
            fed_hub / "federation" / rid / "index.yaml", models.KBIndex()
        )
    with pytest.raises(kbcontext.UnknownTagError) as exc:
        build_context_block(
            HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["airspace"]
        )
    message = str(exc.value)
    assert "no tags at all" in message
    assert "drop --tags" in message


def test_build_block_unknown_tag_on_a_stale_hub_says_so(fed_hub):
    handle = HubHandle(root=fed_hub, stale=True, age_seconds=120.0)
    with pytest.raises(kbcontext.UnknownTagError) as exc:
        build_context_block(handle, ["arinc-kb:arinc-424 §5.3"], tags=["ghost-tag"])
    assert "stale" in str(exc.value)


def test_build_block_reports_a_bad_ref_before_a_bad_tag(fed_hub):
    # Ref validation must run first: a broken ref is the more fundamental
    # problem and must not be masked by a tag complaint.
    with pytest.raises(KBRefNotFoundError):
        build_context_block(
            HubHandle(root=fed_hub), ["arinc-424 §9.9"], tags=["ghost-tag"]
        )


def test_build_block_blank_explicit_tags_fall_back_to_derivation(fed_hub):
    # `kb context new` without --tags hands build_context_block an empty
    # list (cli.py:1160), not None — both must derive.
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["", "  "]
    )
    assert parse(block).tags == ["arinc424"]
