from aero_kb import kbcontext, models
from aero_kb.resolve import render_resolved, resolve_refs


def _ctx(version: str, *refs: str) -> kbcontext.KBContext:
    return kbcontext.KBContext(
        version=version, refs=[kbcontext.parse_ref(r) for r in refs]
    )


def test_ok_when_section_unchanged(git_kb):
    # §1.2 is unchanged between rev1 and the worktree
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §1.2"))
    assert results[0].status == "ok"
    assert "Airway Records" in results[0].content
    assert results[0].citation == "demo-doc §1.2 (Rev 1)"
    assert results[0].tokens > 0


def test_stale_returns_pinned_content(git_kb):
    # §1.1 changed after rev1 — returns the content AT THE PINNED VERSION, not the new one
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
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev1"], "missing-doc §1.1"))
    assert results[0].status == "broken"


def test_broken_bad_rev_does_not_break_batch(git_kb):
    results = resolve_refs(
        git_kb["kb"], _ctx("deadbeef", "demo-doc §1.1", "demo-doc §1.2")
    )
    assert [r.status for r in results] == ["broken", "broken"]
    assert "deadbeef" in results[0].reason


def test_broken_corrupt_manifest_at_pin_does_not_break_batch(git_kb, run_git):
    # Manifest YAML is broken AT THE PINNED REV → that ref is broken, the other ref in the batch is still ok
    root = git_kb["root"]
    doc = git_kb["kb"] / "broken-doc"
    doc.mkdir()
    (doc / "_manifest.yaml").write_text("sections: [unclosed", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "broken manifest")
    rev3 = run_git(root, "rev-parse", "--short", "HEAD")
    results = resolve_refs(
        git_kb["kb"], _ctx(rev3, "broken-doc §1.1", "demo-doc §1.2")
    )
    assert results[0].status == "broken"
    assert "manifest" in results[0].reason
    assert results[1].status == "ok"


def test_worktree_corrupt_manifest_does_not_raise(git_kb):
    # Worktree manifest is broken (bad schema) → does not raise, ref becomes stale
    manifest_path = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    manifest_path.write_text("sections: 5", encoding="utf-8")
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev2"], "demo-doc §1.1"))
    assert results[0].status == "stale"
    assert "worktree" in results[0].reason


def test_broken_missing_l2_at_pin(git_kb, run_git):
    # Manifest at the rev points to an L2 file that doesn't exist at that rev → broken
    root = git_kb["root"]
    doc = git_kb["kb"] / "missing-l2"
    doc.mkdir()
    manifest = models.Manifest(
        id="missing-l2",
        title="Missing L2",
        sections=[models.SectionEntry(id="1.1", title="X", file="ch1")],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "doc missing l2")
    rev3 = run_git(root, "rev-parse", "--short", "HEAD")
    results = resolve_refs(git_kb["kb"], _ctx(rev3, "missing-l2 §1.1"))
    assert results[0].status == "broken"
    assert "ch1" in results[0].reason


def test_broken_slice_fail_at_pin(git_kb, run_git):
    # L2 file exists at the rev but doesn't contain the section's heading → broken
    root = git_kb["root"]
    doc = git_kb["kb"] / "no-slice"
    doc.mkdir()
    manifest = models.Manifest(
        id="no-slice",
        title="No Slice",
        sections=[models.SectionEntry(id="1.1", title="X", file="ch1")],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    (doc / "ch1.md").write_text("## 2.2 Other\n\nOther content.\n", encoding="utf-8")
    run_git(root, "add", "-A")
    run_git(root, "commit", "-m", "doc cannot be sliced")
    rev3 = run_git(root, "rev-parse", "--short", "HEAD")
    results = resolve_refs(git_kb["kb"], _ctx(rev3, "no-slice §1.1"))
    assert results[0].status == "broken"
    assert "1.1" in results[0].reason


def test_stale_when_section_removed_from_worktree(git_kb):
    # Section resolves at the pin but has disappeared from the worktree L2 → stale
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    text = l2.read_text(encoding="utf-8").split("## 1.2")[0]
    l2.write_text(text, encoding="utf-8")
    results = resolve_refs(git_kb["kb"], _ctx(git_kb["rev2"], "demo-doc §1.2"))
    assert results[0].status == "stale"
    assert "worktree" in results[0].reason
    assert "Airway Records" in results[0].content  # still returns the pinned version


def test_render_resolved_marks_status(git_kb):
    results = resolve_refs(
        git_kb["kb"], _ctx(git_kb["rev1"], "demo-doc §1.1", "demo-doc §1.2")
    )
    text = render_resolved(results)
    assert f"@ {git_kb['rev1']}] status=stale" in text
    assert "status=ok" in text
    # the "see the changes" hint for a stale ref must include --against with the pinned rev
    # (bare `kb diff` defaults to --against HEAD → would misreport a clean worktree)
    assert f"kb diff demo-doc --against {git_kb['rev1']}" in text
