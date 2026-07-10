from aero_kb import kbcontext
from aero_kb.resolve import render_resolved, resolve_refs


def _ctx(version: str, *refs: str) -> kbcontext.KBContext:
    return kbcontext.KBContext(
        version=version, refs=[kbcontext.parse_ref(r) for r in refs]
    )


def test_ok_when_section_unchanged(git_kb):
    # §1.2 không đổi giữa rev1 và worktree
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §1.2"))
    assert results[0].status == "ok"
    assert "Airway Records" in results[0].content
    assert results[0].citation == "demo-doc §1.2 (Rev 1)"
    assert results[0].tokens > 0


def test_stale_returns_pinned_content(git_kb):
    # §1.1 đã đổi sau rev1 — trả nội dung TẠI BẢN PIN, không phải bản mới
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §1.1"))
    assert results[0].status == "stale"
    assert "designation and type fields" in results[0].content
    assert "NEW multiple code" not in results[0].content
    assert results[0].reason


def test_pin_at_head_is_ok(git_kb):
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev2"], "demo-doc §1.1"))
    assert results[0].status == "ok"


def test_broken_unknown_section(git_kb):
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §9.9"))
    assert results[0].status == "broken"
    assert "9.9" in results[0].reason


def test_broken_unknown_doc(git_kb):
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "khong-co §1.1"))
    assert results[0].status == "broken"


def test_broken_bad_rev_does_not_break_batch(git_kb):
    results = resolve_refs(
        git_kb["kb"], _ctx("deadbeef", "demo-doc §1.1", "demo-doc §1.2")
    )
    assert [r.status for r in results] == ["broken", "broken"]
    assert "deadbeef" in results[0].reason


def test_render_resolved_marks_status(git_kb):
    results = resolve_refs(
        git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §1.1", "demo-doc §1.2")
    )
    text = render_resolved(results, git_kb["rev1"])
    assert f"@ {git_kb['rev1']}] status=stale" in text
    assert "status=ok" in text
    assert "kb diff demo-doc" in text  # gợi ý xem thay đổi cho ref stale
