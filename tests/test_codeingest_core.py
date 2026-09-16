from pathlib import Path

import pytest

from center_kb import models
from center_kb.build import build_kb
from center_kb.codeingest import core
from tests.test_gitio import _stdin_offenders_in_module


class _StubExtractor:
    """Two sections in two groups, deliberately out of sorted order."""

    name = "stub"

    def detect(self, root: Path) -> bool:
        return True

    def extract(self, root: Path, opts) -> core.ExtractResult:
        return core.ExtractResult(
            sections=[
                core.CodeSection(
                    id="svc.beta", title="beta", summary="Service beta.",
                    group="services", l2_md="Beta service.\n",
                    l3_md="```yaml\nimage: beta:1\n```\n",
                ),
                core.CodeSection(
                    id="svc.alpha", title="alpha", summary="Service alpha.",
                    group="services", l2_md="Alpha service.\n",
                    l3_md="```yaml\nimage: alpha:1\n```\n",
                ),
                core.CodeSection(
                    id="dep.python", title="Python dependencies",
                    summary="3 direct Python dependencies.",
                    group="deps", l2_md="typer, pydantic, pyyaml\n",
                    l3_md="```\ntyper>=0.12\n```\n",
                ),
            ]
        )


def _opts(tmp_path: Path, **kw):
    return core.CodeIngestOptions(
        repo_root=tmp_path, kb_dir=tmp_path / ".kb",
        doc_id="demo-code", repo_id="demo", **kw
    )


def test_sections_are_sorted_by_group_then_id(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    l2 = (tmp_path / ".kb" / "demo-code" / "services.md").read_text(encoding="utf-8")
    assert l2.index("## svc.alpha") < l2.index("## svc.beta")


def test_one_md_and_raw_md_pair_per_group(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    report = core.run(_opts(tmp_path))
    doc = tmp_path / ".kb" / "demo-code"
    for stem in ("services", "deps"):
        assert (doc / f"{stem}.md").is_file()
        assert (doc / f"{stem}.raw.md").is_file()
    assert sorted(report.files_written) == sorted(
        ["_manifest.yaml", "deps.md", "deps.raw.md", "services.md", "services.raw.md"]
    )


def test_manifest_records_commit_and_commit_date_not_wall_clock(tmp_path, monkeypatch, run_git):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    run_git(tmp_path, "init")
    run_git(tmp_path, "add", "-A")
    # Pin the commit date away from today (set only for this test, via env —
    # the shared run_git fixture is untouched) so a date.today() regression
    # cannot pass this assertion by accident. See task-B1-report.md Finding 3.
    monkeypatch.setenv("GIT_AUTHOR_DATE", "2020-01-02T00:00:00+0000")
    monkeypatch.setenv("GIT_COMMITTER_DATE", "2020-01-02T00:00:00+0000")
    run_git(tmp_path, "commit", "-m", "c1")
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    m = models.load_yaml_model(
        tmp_path / ".kb" / "demo-code" / "_manifest.yaml", models.Manifest
    )
    head = run_git(tmp_path, "rev-parse", "HEAD")
    assert m.revision == head[:7]
    assert m.source_sha256 == head
    assert m.ingested.isoformat() == "2020-01-02"
    assert all(s.status == "summarized" and s.summary for s in m.sections)


def test_index_entry_carries_code_and_generated_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path, tags=("team-x",)))
    index = models.load_yaml_model(tmp_path / ".kb" / "index.yaml", models.KBIndex)
    entry = next(d for d in index.docs if d.id == "demo-code")
    assert entry.tags == ["code", "generated", "team-x"]


def test_rerun_preserves_user_added_index_tags(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    index_path = tmp_path / ".kb" / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    next(d for d in index.docs if d.id == "demo-code").tags.append("hand-added")
    models.save_yaml_model(index_path, index)
    core.run(_opts(tmp_path))
    index = models.load_yaml_model(index_path, models.KBIndex)
    assert "hand-added" in next(d for d in index.docs if d.id == "demo-code").tags


def test_rerun_preserves_per_section_tokens_written_by_build(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    assert build_kb(tmp_path / ".kb").ok
    path = tmp_path / ".kb" / "demo-code" / "_manifest.yaml"
    before = {s.id: s.tokens.l2 for s in
              models.load_yaml_model(path, models.Manifest).sections}
    assert all(v > 0 for v in before.values())
    core.run(_opts(tmp_path))
    after = {s.id: s.tokens.l2 for s in
             models.load_yaml_model(path, models.Manifest).sections}
    assert after == before


def test_two_runs_produce_byte_identical_trees(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    doc = tmp_path / ".kb" / "demo-code"
    first = {p.name: p.read_bytes() for p in sorted(doc.iterdir())}
    core.run(_opts(tmp_path))
    second = {p.name: p.read_bytes() for p in sorted(doc.iterdir())}
    assert first == second


def test_files_use_lf_endings_only(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    for p in (tmp_path / ".kb" / "demo-code").iterdir():
        assert b"\r\n" not in p.read_bytes(), p.name


def test_generated_document_builds_clean_without_allow_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    report = build_kb(tmp_path / ".kb")
    assert report.errors == [], report.errors
    assert report.ok


def test_zero_detection_beyond_tree_raises(tmp_path, monkeypatch):
    class _TreeOnly:
        name = "tree"

        def detect(self, root):
            return True

        def extract(self, root, opts):
            return core.ExtractResult(sections=[
                core.CodeSection(id="struct.tree", title="Repository tree",
                                 summary="Folder layout.", group="structure",
                                 l2_md="- src/\n", l3_md="```\nsrc/\n```\n")
            ])

    class _Silent:
        name = "deps"

        def detect(self, root):
            return False

        def extract(self, root, opts):
            raise AssertionError("must not be called when detect() is False")

    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_TreeOnly(), _Silent()])
    with pytest.raises(core.CodeIngestError):
        core.run(_opts(tmp_path))


def test_zero_detection_raises_even_when_a_non_tree_extractor_detects_but_contributes_nothing(
    tmp_path, monkeypatch
):
    # Task review, Important 1: the gate used to key off report.detected —
    # what detect() said — rather than what extract() actually produced.
    # Every detect() is deliberately looser than its extract() (e.g. an
    # ordinary typo in --db, or a pyproject.toml holding only [tool.ruff]),
    # so a non-tree extractor can fire detect()=True and still contribute
    # zero sections. Before the fix, this slipped past the gate and shipped
    # a tree-only document with exit 0.
    class _TreeOnly:
        name = "tree"

        def detect(self, root):
            return True

        def extract(self, root, opts):
            return core.ExtractResult(sections=[
                core.CodeSection(id="struct.tree", title="Repository tree",
                                 summary="Folder layout.", group="structure",
                                 l2_md="- src/\n", l3_md="```\nsrc/\n```\n")
            ])

    class _DetectsButContributesNothing:
        name = "deps"

        def detect(self, root):
            return True  # looser than extract() -- fires on a false positive

        def extract(self, root, opts):
            return core.ExtractResult(sections=[])  # nothing real found after all

    monkeypatch.setattr(
        core, "ALL_EXTRACTORS", [_TreeOnly(), _DetectsButContributesNothing()]
    )
    with pytest.raises(core.CodeIngestError):
        core.run(_opts(tmp_path))


def test_extractor_warnings_reach_the_report(tmp_path, monkeypatch):
    class _Noisy(_StubExtractor):
        name = "noisy"

        def extract(self, root, opts):
            result = super().extract(root, opts)
            result.warnings.append("could not parse pom.xml: mismatched tag")
            return result

    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_Noisy()])
    report = core.run(_opts(tmp_path))
    assert any("pom.xml" in w for w in report.warnings)


def test_dirty_tree_is_reported(tmp_path, monkeypatch, run_git):
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    run_git(tmp_path, "init")
    run_git(tmp_path, "add", "-A")
    run_git(tmp_path, "commit", "-m", "c1")
    (tmp_path / "f.txt").write_text("y", encoding="utf-8")
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    assert core.run(_opts(tmp_path)).dirty_tree is True


def test_duplicate_section_id_across_extractors_raises(tmp_path, monkeypatch):
    class _A:
        name = "a"

        def detect(self, root):
            return True

        def extract(self, root, opts):
            return core.ExtractResult(sections=[
                core.CodeSection(id="svc.x", title="x", summary="s.",
                                 group="services", l2_md="a\n", l3_md="```\na\n```\n")
            ])

    class _B:
        name = "b"

        def detect(self, root):
            return True

        def extract(self, root, opts):
            return core.ExtractResult(sections=[
                core.CodeSection(id="svc.x", title="x2", summary="s2.",
                                 group="services", l2_md="b\n", l3_md="```\nb\n```\n")
            ])

    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_A(), _B()])
    with pytest.raises(core.CodeIngestError):
        core.run(_opts(tmp_path))


def test_stale_group_files_are_pruned_when_a_group_disappears(tmp_path, monkeypatch):
    class _TwoGroups:
        name = "stub"

        def detect(self, root):
            return True

        def extract(self, root, opts):
            return core.ExtractResult(sections=[
                core.CodeSection(
                    id="svc.alpha", title="alpha", summary="Service alpha.",
                    group="services", l2_md="Alpha service.\n",
                    l3_md="```yaml\nimage: alpha:1\n```\n",
                ),
                core.CodeSection(
                    id="dep.python", title="Python dependencies",
                    summary="3 direct Python dependencies.",
                    group="deps", l2_md="typer, pydantic, pyyaml\n",
                    l3_md="```\ntyper>=0.12\n```\n",
                ),
            ])

    class _OneGroup:
        name = "stub"

        def detect(self, root):
            return True

        def extract(self, root, opts):
            return core.ExtractResult(sections=[
                core.CodeSection(
                    id="svc.alpha", title="alpha", summary="Service alpha.",
                    group="services", l2_md="Alpha service.\n",
                    l3_md="```yaml\nimage: alpha:1\n```\n",
                ),
            ])

    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_TwoGroups()])
    core.run(_opts(tmp_path))
    doc = tmp_path / ".kb" / "demo-code"
    assert (doc / "deps.md").is_file()
    assert (doc / "deps.raw.md").is_file()

    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_OneGroup()])
    core.run(_opts(tmp_path))
    assert not (doc / "deps.md").exists()
    assert not (doc / "deps.raw.md").exists()
    assert (doc / "services.md").is_file()
    assert (doc / "services.raw.md").is_file()
    assert (doc / "_manifest.yaml").is_file()


def test_full_extractor_set_on_the_fixture_repo_builds_clean(tmp_path):
    from tests.fixtures_coderepo import build_code_repo

    root = build_code_repo(tmp_path)
    db = root / "app.db"
    import sqlite3

    con = sqlite3.connect(db)
    con.execute("CREATE TABLE roster (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    report = core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code", repo_id="demo",
            db_paths=(db,),
        )
    )
    all_extractor_names = {
        "services", "deps", "commands", "tree", "schema", "integrations", "api"
    }
    assert set(report.detected) >= all_extractor_names
    # Test gap (task review): the assertion above only checks what
    # detect() said fired, not what extract() actually produced -- it
    # would stay green even if one extractor silently contributed zero
    # sections (the exact defect Important 1's zero-detection gate now
    # catches at the whole-run level; this pins the same property for
    # every extractor individually, on real fixture data, not stubs).
    assert all(
        report.sections_by_extractor[name] > 0 for name in all_extractor_names
    ), report.sections_by_extractor
    build = build_kb(root / ".kb")
    assert build.errors == [], build.errors
    assert build.ok


def test_generated_document_is_searchable_through_the_hub(
    tmp_path, run_git, monkeypatch
):
    """The whole point of using the 4-layer format: zero engine changes needed."""
    import sqlite3

    # Belt-and-braces alongside the hub's own `.kb/` below (which is what
    # actually keeps `resolve_hub()` off the clone-into-cache path today):
    # redirect the cache too, the same way every other hub test in this
    # suite does (tests/test_publish.py, tests/test_mcp.py,
    # tests/test_web_api.py) — so a future reorder of this test, or a
    # change to `hub.py`'s direct-path condition, cannot make this test
    # silently write into the real `~/.center-kb/hub/` on the host.
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "hub-cache"))

    from center_kb.hub import resolve_hub
    from center_kb.query import get_section, search
    from tests.fixtures_coderepo import build_code_repo

    root = build_code_repo(tmp_path / "repo")
    db = root / "app.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE roster (id INTEGER PRIMARY KEY, name TEXT)")
    con.commit()
    con.close()
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code", repo_id="demo",
            db_paths=(db,),
        )
    )
    assert build_kb(root / ".kb").ok

    # Publish by copying .kb/ into a hub federation dir — the shape kb publish produces.
    hub = tmp_path / "hub"
    dest = hub / "federation" / "demo"
    dest.mkdir(parents=True)
    for item in (root / ".kb").iterdir():
        target = dest / item.name
        if item.is_dir():
            import shutil

            shutil.copytree(item, target)
        else:
            import shutil

            shutil.copy2(item, target)
    # `kb publish`'s `_snapshot()` also writes a `_meta.yaml` at the leaf
    # (federation.FederationMeta) — `iter_entry_dirs()` only recognises a
    # directory as a leaf entry when BOTH `_meta.yaml` and `index.yaml`
    # are present (src/center_kb/federation.py); without it this entry is
    # silently skipped ("missing _meta.yaml or index.yaml").
    from center_kb.federation import FederationMeta

    models.save_yaml_model(
        dest / "_meta.yaml",
        FederationMeta(repo_id="demo", source_commit=""),
    )
    # `hub.resolve_hub()` only takes the direct, no-clone path when the
    # target itself has a `.kb/` (see `hub.py`'s `direct.is_dir() and
    # (direct / ".kb").is_dir()` check) — every real hub has one (its own
    # local KB, alongside `federation/`). Without it, `resolve_hub` falls
    # through to `git clone`-ing this path into the *real* on-disk hub
    # cache under the current user's home directory (`~/.center-kb/hub/`
    # by default) instead of staying inside `tmp_path`, which would leave
    # stray state on the host and break this suite's hermetic-tests rule.
    (hub / ".kb").mkdir(parents=True)
    run_git(hub, "init")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "publish demo-code")

    handle = resolve_hub(str(hub))
    assert handle is not None
    assert search(handle, "roster")
    assert search(handle, "airspace-service")
    section = get_section(handle, "demo-code", "db.roster", level="l3")
    assert section is not None
    assert "CREATE TABLE" in section.content


# --- P57 item 3 (wave-j-round-2-brief.md): codeingest.core._git() was a ---
# --- byte-for-byte twin of gitio._run before the Wave J Critical fix --  ---
# --- same omission, same hazard shape, one module over. Not reachable ---
# --- from the MCP stdio server today (only cli.py calls it, off that ---
# --- surface), but the ruling is about the call shape, not about who ---
# --- currently imports the module -- a structural check scoped to ---
# --- gitio alone is how a second instance of the same bug survives. ---
# --- Reuses gitio's checker verbatim (see tests/test_gitio.py for its ---
# --- evasion coverage) rather than a second, drifting implementation.


def test_every_subprocess_run_call_in_codeingest_core_has_a_verifiably_safe_stdin():
    offenders = _stdin_offenders_in_module(core)
    assert offenders == [], (
        f"subprocess.run() in codeingest/core.py has an unsafe or unverifiable stdin= at: {offenders}"
    )


# ---------------------------------------------------------------------------
# Reviewer G-1: a hand-curated document at <repo>-code was deleted without
# a warning. The destination guard now also refuses any document this
# command did not itself generate — no override flag.
# ---------------------------------------------------------------------------


def _write_human_doc(doc_dir: Path, title: str = "Poly hand-written domain doc") -> None:
    doc_dir.mkdir(parents=True)
    (doc_dir / "body.md").write_text("## ch1 Chapter one\n\nHuman prose.\n", encoding="utf-8")
    (doc_dir / "body.raw.md").write_text("## ch1 Chapter one\n\nRaw prose.\n", encoding="utf-8")
    models.save_yaml_model(
        doc_dir / "_manifest.yaml",
        models.Manifest(
            id="demo-code", title=title,
            sections=[models.SectionEntry(
                id="ch1", title="Chapter one", summary="A curated chapter.",
                status="reviewed", file="body",
            )],
        ),
    )


def test_human_document_at_the_code_slot_is_refused_and_left_intact(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    doc_dir = tmp_path / ".kb" / "demo-code"
    _write_human_doc(doc_dir)
    before = {p.name: p.read_bytes() for p in doc_dir.iterdir()}

    with pytest.raises(core.CodeIngestError) as excinfo:
        core.run(_opts(tmp_path))

    assert "did not generate" in str(excinfo.value)
    assert "Poly hand-written domain doc" in str(excinfo.value)
    assert {p.name: p.read_bytes() for p in doc_dir.iterdir()} == before
    assert not (tmp_path / ".kb" / "index.yaml").exists()


def test_document_with_a_foreign_section_id_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    doc_dir = tmp_path / ".kb" / "demo-code"
    _write_human_doc(doc_dir, title="demo — code knowledge")   # title passes, id does not
    with pytest.raises(core.CodeIngestError) as excinfo:
        core.run(_opts(tmp_path))
    assert "ch1" in str(excinfo.value)


def test_markdown_without_a_manifest_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    doc_dir = tmp_path / ".kb" / "demo-code"
    doc_dir.mkdir(parents=True)
    (doc_dir / "notes.md").write_text("mine\n", encoding="utf-8")
    with pytest.raises(core.CodeIngestError) as excinfo:
        core.run(_opts(tmp_path))
    assert "missing or unreadable" in str(excinfo.value)
    assert (doc_dir / "notes.md").read_text(encoding="utf-8") == "mine\n"


def test_previous_run_with_rewritten_statuses_still_reingests(tmp_path, monkeypatch):
    # `kb summarize --redo` / `kb approve` rewrite statuses on a -code
    # manifest; neither touches the title or the ids, so a re-run proceeds.
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    core.run(_opts(tmp_path))
    manifest_path = tmp_path / ".kb" / "demo-code" / "_manifest.yaml"
    m = models.load_yaml_model(manifest_path, models.Manifest)
    for s in m.sections:
        s.status = "pending"
    models.save_yaml_model(manifest_path, m)
    report = core.run(_opts(tmp_path))
    assert report.files_written


def test_empty_destination_directory_is_fine(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ALL_EXTRACTORS", [_StubExtractor()])
    (tmp_path / ".kb" / "demo-code").mkdir(parents=True)
    assert core.run(_opts(tmp_path)).files_written
