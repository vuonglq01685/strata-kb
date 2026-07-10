from aero_kb import kbcontext, models
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


def test_broken_corrupt_manifest_at_pin_does_not_break_batch(git_kb, run_git):
    # Manifest YAML hỏng TẠI REV PIN → ref đó broken, ref khác trong batch vẫn ok
    root = git_kb["root"]
    doc = git_kb["kb"] / "hong-doc"
    doc.mkdir()
    (doc / "_manifest.yaml").write_text("sections: [unclosed", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "manifest hong")
    rev3 = run_git(root, "rev-parse", "--short", "HEAD")
    results = resolve_refs(
        git_kb["kb"], _ctx(rev3, "hong-doc §1.1", "demo-doc §1.2")
    )
    assert results[0].status == "broken"
    assert "manifest" in results[0].reason
    assert results[1].status == "ok"


def test_worktree_corrupt_manifest_does_not_raise(git_kb):
    # Manifest worktree hỏng (schema sai) → không raise, ref thành stale
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest_path.write_text("sections: 5", encoding="utf-8")
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev2"], "demo-doc §1.1"))
    assert results[0].status == "stale"
    assert "worktree" in results[0].reason


def test_broken_missing_l2_at_pin(git_kb, run_git):
    # Manifest tại rev trỏ tới file L2 không tồn tại ở rev đó → broken
    root = git_kb["root"]
    doc = git_kb["kb"] / "thieu-l2"
    doc.mkdir()
    manifest = models.Manifest(
        id="thieu-l2",
        title="Thieu L2",
        sections=[models.SectionEntry(id="1.1", title="X", file="ch1")],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "doc thieu l2")
    rev3 = run_git(root, "rev-parse", "--short", "HEAD")
    results = resolve_refs(git_kb["kb"], _ctx(rev3, "thieu-l2 §1.1"))
    assert results[0].status == "broken"
    assert "ch1" in results[0].reason


def test_broken_slice_fail_at_pin(git_kb, run_git):
    # File L2 tồn tại tại rev nhưng không chứa heading của section → broken
    root = git_kb["root"]
    doc = git_kb["kb"] / "khong-slice"
    doc.mkdir()
    manifest = models.Manifest(
        id="khong-slice",
        title="Khong Slice",
        sections=[models.SectionEntry(id="1.1", title="X", file="ch1")],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    (doc / "ch1.md").write_text("## 2.2 Khac\n\nNoi dung khac.\n", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "doc khong slice duoc")
    rev3 = run_git(root, "rev-parse", "--short", "HEAD")
    results = resolve_refs(git_kb["kb"], _ctx(rev3, "khong-slice §1.1"))
    assert results[0].status == "broken"
    assert "1.1" in results[0].reason


def test_stale_when_section_removed_from_worktree(git_kb):
    # Section resolve được tại pin nhưng đã biến mất khỏi L2 worktree → stale
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    text = l2.read_text(encoding="utf-8").split("## 1.2")[0]
    l2.write_text(text, encoding="utf-8")
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev2"], "demo-doc §1.2"))
    assert results[0].status == "stale"
    assert "worktree" in results[0].reason
    assert "Airway Records" in results[0].content  # vẫn trả bản pin


def test_render_resolved_marks_status(git_kb):
    results = resolve_refs(
        git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §1.1", "demo-doc §1.2")
    )
    text = render_resolved(results)
    assert f"@ {git_kb['rev1']}] status=stale" in text
    assert "status=ok" in text
    # gợi ý xem thay đổi cho ref stale phải kèm --against đúng rev pin
    # (bare `kb diff` mặc định --against HEAD → worktree sạch báo sai)
    assert f"kb diff demo-doc --against {git_kb['rev1']}" in text
