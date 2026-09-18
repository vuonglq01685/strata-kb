import shutil

import yaml

from center_kb import kbcontext
from center_kb.hub import HubHandle
from center_kb.kbcontext import KBContext, KBRef, build_context_block
from center_kb.resolve import render_resolved, resolve_refs
from tests.conftest import make_fed_entry

REF = "arinc-kb:arinc-424 §5.3"


def _ctx_for(fed_hub, refs):
    block, _ = build_context_block(HubHandle(root=fed_hub), refs)
    return kbcontext.parse(block)


def _doc_dir(fed_hub):
    return fed_hub / "federation" / "arinc-kb" / "arinc-424"


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
    # the returned content is still the pinned version
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
        version="deadbee",  # a commit of the old local repo — not in the hub
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
    assert "Condensed: restrictive airspace" in text  # the True default renders content — symmetric with the False tests below


def test_render_resolved_status_only_omits_content(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    text = render_resolved(resolve_refs(handle, ctx), include_content=False)
    assert "status=ok" in text
    # the pinned section body must NOT be rendered
    assert "Condensed: restrictive airspace" not in text


def test_render_resolved_status_only_keeps_the_stale_reason(fed_hub, run_git):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"),
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "republish")
    text = render_resolved(resolve_refs(handle, ctx), include_content=False)
    assert "status=stale" in text
    assert "!!" in text  # the reason line survives — triage needs it
    assert "NEW codes" not in text and "designation codes" not in text


def test_deleted_section_is_broken(fed_hub):
    """(e) — the section is removed from the manifest.

    Reviewer C F-C6: this resolved as `stale`/exit 2, the same signal CI gets
    for "someone reworded a sentence", so CI could not block on a citation
    whose target is gone. C8's three statuses stay three — this is a
    reclassification, not a new status."""
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, [REF])
    manifest = _doc_dir(fed_hub) / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    data["sections"] = [s for s in data["sections"] if s["id"] != "5.3"]
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    (result,) = resolve_refs(handle, ctx)
    assert result.status == "broken"
    assert "no longer exists" in result.reason
    assert result.content, "the pinned bytes still resolve — only the link is broken"


def test_renumbered_section_is_broken(fed_hub):
    """(f) — §5.3 becomes §5.3a."""
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, [REF])
    manifest = _doc_dir(fed_hub) / "_manifest.yaml"
    data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    for sec in data["sections"]:
        if sec["id"] == "5.3":
            sec["id"] = "5.3a"
    manifest.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    (result,) = resolve_refs(handle, ctx)
    assert result.status == "broken"
    assert "no longer exists" in result.reason


def test_removed_document_is_broken_and_hints_a_command_that_works(fed_hub):
    """(g) — the whole document is gone. The old `stale` hint was a dead end:
    `kb diff arinc-424 --against <rev>` answers `doc 'arinc-424' is not in the
    worktree`."""
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, [REF])
    shutil.rmtree(_doc_dir(fed_hub))

    (result,) = resolve_refs(handle, ctx)
    assert result.status == "broken"
    assert "document" in result.reason and "no longer exists" in result.reason
    assert "kb diff" not in render_resolved([result])


def test_l2_edit_is_still_stale(fed_hub):
    """(a) — a genuine amendment must NOT be promoted to broken."""
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, [REF])
    l2 = _doc_dir(fed_hub) / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("Condensed:", "Condensed (rev 2):"),
        encoding="utf-8",
    )
    (result,) = resolve_refs(handle, ctx)
    assert result.status == "stale"
    assert "kb get" in render_resolved([result])


def test_heading_removed_from_l2_body_is_broken(fed_hub):
    """Review fix: manifest still lists §5.3 and `ch1.md` still exists, but
    the `## 5.3` heading itself was renamed/removed from the body —
    `slice_section` returns `None` even though `problem` was `""`. Must not
    raise `AttributeError` on `now.strip()`; must resolve `broken`."""
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, [REF])
    l2 = _doc_dir(fed_hub) / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("## 5.3", "## 5.3a"),
        encoding="utf-8",
    )
    (result,) = resolve_refs(handle, ctx)
    assert result.status == "broken"
    assert "no longer exists" in result.reason


def test_legacy_two_version_block_is_broken(fed_hub):
    """F-C6 nit: `hub_version` was parsed at kbcontext.py:190-191 and never
    consulted, so a legacy two-version block whose `version` happened to be a
    real hub commit resolved silently as ok."""
    handle = HubHandle(root=fed_hub)
    pinned = _ctx_for(fed_hub, [REF])
    ctx = KBContext(
        version=pinned.version, hub_version="deadbee", refs=pinned.refs
    )
    results = resolve_refs(handle, ctx)
    assert all(r.status == "broken" for r in results)
    assert "hub_version" in results[0].reason


from center_kb.resolve import (
    CACHE_MARKER,
    cache_digest,
    cache_problem,
    read_cache_header,
    refs_of,
    render_cache,
)


def _results(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    return ctx, resolve_refs(handle, ctx)


def test_stale_hint_names_kb_get_never_kb_diff(fed_hub, run_git):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"), encoding="utf-8")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "republish")
    text = render_resolved(resolve_refs(handle, ctx), include_content=False)
    assert "kb diff" not in text
    assert "run `kb get arinc-424 5.3 --level l3` for the current hub version" in text


def test_render_cache_layout_and_header(fed_hub):
    ctx, results = _results(fed_hub)
    text = render_cache(ctx.version, results, today="2026-09-15", stem="T-7", previous=None)
    assert text.startswith("# Context cache — T-7\n")
    hdr = read_cache_header(text)
    assert hdr is not None
    assert hdr.version == ctx.version
    assert hdr.refs == refs_of(results) == frozenset({"arinc-kb:arinc-424 §5.3"})
    assert "## Resolved sections\n" in text
    assert "Condensed: restrictive airspace" in text
    assert text.index(CACHE_MARKER) > text.index("## Resolved sections")
    assert text.rstrip().endswith("|---|---|---|")
    assert cache_problem(text, ctx.version, results) == ""


def test_render_cache_carries_the_placeholder_map_over_byte_for_byte(fed_hub):
    ctx, results = _results(fed_hub)
    first = render_cache(ctx.version, results, today="2026-09-15", stem="T-7", previous=None)
    edited = first + "| <max-alt> | 45000 | src/limits.py:12 |\n"
    second = render_cache(ctx.version, results, today="2026-09-16", stem="T-7", previous=edited)
    assert second[second.index(CACHE_MARKER):] == edited[edited.index(CACHE_MARKER):]
    assert cache_problem(second, ctx.version, results) == ""


def test_render_cache_migrates_a_pre_0_23_cache_without_marker(fed_hub):
    ctx, results = _results(fed_hub)
    previous = (
        "# Context cache — T-7\n\n"
        "## Placeholder map\n"
        "| placeholder | verified value | evidence (file:line or ref) |\n"
        "|---|---|---|\n"
        "| <max-alt> | 45000 | src/limits.py:12 |\n"
    )
    text = render_cache(ctx.version, results, today="2026-09-15", stem="T-7", previous=previous)
    assert CACHE_MARKER + "\n## Placeholder map" in text
    assert "| <max-alt> | 45000 | src/limits.py:12 |" in text
    assert cache_problem(text, ctx.version, results) == ""


def test_editing_above_the_marker_is_detected(fed_hub):
    ctx, results = _results(fed_hub)
    text = render_cache(ctx.version, results, today="2026-09-15", stem="T-7", previous=None)
    tampered = text.replace("Condensed: restrictive airspace", "Condensed: whatever I remember")
    assert cache_problem(tampered, ctx.version, results) == "resolved block edited since written"


def test_editing_below_the_marker_is_allowed(fed_hub):
    ctx, results = _results(fed_hub)
    text = render_cache(ctx.version, results, today="2026-09-15", stem="T-7", previous=None)
    assert cache_problem(text + "| x | y | z |\n", ctx.version, results) == ""


def test_a_foreign_cache_is_detected_by_its_ref_set(fed_hub):
    ctx, results = _results(fed_hub)
    other_ctx = _ctx_for(fed_hub, ["icao-kb:icao-annex-2 §1.1"])
    other = render_cache(other_ctx.version, resolve_refs(HubHandle(root=fed_hub), other_ctx),
                         today="2026-09-15", stem="T-8", previous=None)
    problem = cache_problem(other, ctx.version, results)
    assert problem.startswith("refs differ")
    assert "arinc-kb:arinc-424 §5.3" in problem


def test_a_version_mismatch_is_detected(fed_hub):
    ctx, results = _results(fed_hub)
    text = render_cache("deadbeef", results, today="2026-09-15", stem="T-7", previous=None)
    assert cache_problem(text, ctx.version, results) == f"version deadbeef != ticket {ctx.version}"


def test_a_headerless_file_is_invalid(fed_hub):
    ctx, results = _results(fed_hub)
    assert read_cache_header("just prose\n") is None
    assert cache_problem("just prose\n", ctx.version, results) == "header"


def test_cache_digest_is_sha256_of_the_segment():
    import hashlib
    assert cache_digest("abc\n") == hashlib.sha256(b"abc\n").hexdigest()
