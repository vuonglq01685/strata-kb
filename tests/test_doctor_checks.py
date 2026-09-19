"""The doctor checks added by the reviewer-H batch (H1, M13, M9)."""
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from strata_kb import models
from strata_kb.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_hub_env(monkeypatch):
    """`--hub` carries envvar="STRATA_KB_HUB" -- without this, a dev/CI box
    with that variable set would resolve a different hub than every test
    here assumes, silently. No global scrub exists in conftest.py today;
    fixed once in this file since Tasks 3-6 all extend it."""
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)


def _minimal_kb(root: Path, kind: str = "child") -> Path:
    kb = root / ".kb"
    kb.mkdir(parents=True)
    (kb / "index.yaml").write_text("docs: []\n", encoding="utf-8", newline="\n")
    (kb / "config.yaml").write_text(
        f"hub: {root / 'hub'}\nrepo_id: child\nkind: {kind}\n",
        encoding="utf-8",
        newline="\n",
    )
    return kb


def test_doctor_reports_invalid_config_as_an_issue(tmp_path):
    """M13/H1: the message comes from doctor.check_kind, which means the
    check ran — not from _hub_or_exit's guard, which would mean it did not."""
    kb = _minimal_kb(tmp_path)
    (kb / "config.yaml").write_text(
        f"hub: {tmp_path / 'hub'}\nrepo_id: child\nkind: bogus\n",
        encoding="utf-8",
        newline="\n",
    )

    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb)])

    assert result.exit_code == 1, result.output
    assert "[error] config.yaml is invalid" in result.output


def test_doctor_reports_an_unreadable_upstream_config_instead_of_skipping(
    tmp_path, monkeypatch, run_git
):
    """M13: publish.py fails closed on this read; doctor must too.

    Reaching cli.py's upstream-identity read needs a hub that actually
    resolves (a real dir with .kb/, so resolve_hub takes its "use it
    directly" branch instead of failing the clone) and a .kb tree that is
    inside a real git repo (so git_root doesn't short-circuit into the
    "multi-tier checks skipped" warning first) — neither is optional
    plumbing here, both gate reaching the block under test.
    """
    from strata_kb import config as config_mod

    kb = _minimal_kb(tmp_path, kind="hub")
    (tmp_path / "hub" / ".kb").mkdir(parents=True)
    run_git(tmp_path, "init")
    real_load = config_mod.load_config

    def _boom(kb_dir, *a, **kw):
        if Path(kb_dir).resolve() != kb.resolve():
            raise OSError("permission denied")
        return real_load(kb_dir, *a, **kw)

    monkeypatch.setattr(config_mod, "load_config", _boom)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb)])

    # Block 2 (cli.py) reports the same condition as "could not read
    # .kb/config.yaml" (no "upstream") -- pin the upstream wording so this
    # cannot pass by coincidentally matching the wrong block.
    assert "could not read the upstream hub's" in result.output
    assert result.exit_code == 1, result.output


def test_doctor_reports_unreadable_own_config_instead_of_a_traceback(
    tmp_path, monkeypatch
):
    """Regression from the H1 reorder: check_kind now runs before
    _hub_or_exit, so an OSError reading the KB's own config.yaml is
    check_kind's to catch -- before the reorder, _hub_or_exit's broader
    (*_CONFIG_READ_ERRORS, OSError) guard caught it first; check_kind's
    narrower (yaml.YAMLError, ValidationError) clause let it escape."""
    from strata_kb import config as config_mod

    kb = _minimal_kb(tmp_path)

    def _boom(kb_dir, *a, **kw):
        raise OSError("permission denied")

    monkeypatch.setattr(config_mod, "load_config", _boom)
    result = runner.invoke(app, ["doctor", "--kb-dir", str(kb)])

    # isinstance is the load-bearing assertion here: CliRunner sets
    # exit_code to 1 for an unhandled exception too, and leaves an escaped
    # exception out of `output` -- only `result.exception` tells a clean
    # typer.Exit(1) apart from a traceback that got swallowed.
    assert isinstance(result.exception, SystemExit), result.exception
    assert "[error]" in result.output


@pytest.mark.parametrize(
    "model,payload",
    [
        pytest.param(models.Manifest, {"id": "d", "title": "T", "nope": 1}, id="Manifest"),
        pytest.param(models.IndexEntry, {"id": "d", "title": "T", "nope": 1}, id="IndexEntry"),
        pytest.param(models.KBIndex, {"docs": [], "nope": 1}, id="KBIndex"),
        pytest.param(
            models.SectionEntry,
            {"id": "1", "title": "S", "file": "ch1", "sumary": "oops"},
            id="SectionEntry",
        ),
    ],
)
def test_authored_model_rejects_an_unknown_key(model, payload):
    """M10: 'sumary:' (SectionEntry's case here) used to load cleanly, take
    the field's default, and publish an empty L1 summary. One case per
    authored model, each hitting that model's OWN model_config directly (not
    nested through another model) -- deleting any one's `extra="forbid"`
    line must fail exactly its case here, not just SectionEntry's.

    match="extra_forbidden" (not a bare ValidationError) so that if one of
    these models later grows a required field, the same payload starting to
    fail with "missing" instead still fails this test -- a bare
    pytest.raises(ValidationError) would stay green either way and stop
    guarding the thing Important 2 exists to catch."""
    with pytest.raises(ValidationError, match="extra_forbidden"):
        model.model_validate(payload)


def test_federation_index_still_accepts_unknown_keys():
    """Deliberate asymmetry: the federation index is the wire format between
    installs, and a future install version may add a field to it -- an older
    reader must not hard-error. Covers both levels an unknown key can land
    at: inside an entry (FedIndexEntry) and at the top of the index itself
    (FederationIndex has no model_config of its own to catch either)."""
    idx = models.FederationIndex.model_validate(
        {
            "docs": [{"repo_id": "r", "doc_id": "d", "future_field": "x"}],
            "future_top": 1,
        }
    )
    assert idx.docs[0].doc_id == "d"


def _doc_with(kb: Path, doc_id: str, manifest_yaml: str, md: str) -> None:
    d = kb / doc_id
    d.mkdir(parents=True)
    (d / "_manifest.yaml").write_text(manifest_yaml, encoding="utf-8", newline="\n")
    (d / "ch1.md").write_text(md, encoding="utf-8", newline="\n")
    (d / "ch1.raw.md").write_text(md, encoding="utf-8", newline="\n")
    (kb / "index.yaml").write_text(
        f"docs:\n  - id: {doc_id}\n    title: T\n", encoding="utf-8", newline="\n"
    )


def test_duplicate_section_id_across_files_within_a_doc_is_an_error(tmp_path):
    """Critical 3 ruling (fix round 1): repeated ids are legal WITHIN one
    file -- occurrence disambiguates (mdutils.heading_occurrences /
    slice_section(occurrence=)). The real ambiguity is a citation `doc#<id>`
    that cannot say which FILE it meant, so the illegal case needs two
    different `file:` values."""
    from strata_kb import doctor

    kb = _minimal_kb(tmp_path)
    d = kb / "d1"
    d.mkdir(parents=True)
    (d / "_manifest.yaml").write_text(
        "id: d1\ntitle: T\nsections:\n"
        "  - {id: '2.1', title: A, file: ch1, status: reviewed}\n"
        "  - {id: '2.1', title: B, file: ch2, status: reviewed}\n",
        encoding="utf-8",
        newline="\n",
    )
    for stem, body in (("ch1", "## 2.1 A\nbody a\n"), ("ch2", "## 2.1 B\nbody b\n")):
        (d / f"{stem}.md").write_text(body, encoding="utf-8", newline="\n")
        (d / f"{stem}.raw.md").write_text(body, encoding="utf-8", newline="\n")
    (kb / "index.yaml").write_text(
        "docs:\n  - id: d1\n    title: T\n", encoding="utf-8", newline="\n"
    )

    issues = doctor.check_kb(kb)

    assert any(
        i.level == "error" and "duplicate section id" in i.message for i in issues
    ), issues


def test_duplicate_section_id_in_the_same_file_is_legal_but_warns(tmp_path):
    """Same ruling, other direction: repeated ids in the SAME file are the
    spec-allowed "repeated numbering" mdutils.py documents -- must NOT be an
    ERROR. Final review item 5: the batch's own narrowing was half right --
    a citation `doc#<id>` can't name a FILE, but it can't name an
    OCCURRENCE either, and nothing on the read path (query.py, resolve.py,
    searchdb.py, diff.py, svcnote.py) is occurrence-aware. So the 2nd+
    occurrence of a within-file repeat is legal, builds, publishes, and is
    permanently unreachable by citation -- doctor now WARNS about that
    instead of staying silent."""
    from strata_kb import doctor

    kb = _minimal_kb(tmp_path)
    _doc_with(
        kb,
        "d1",
        "id: d1\ntitle: T\nsections:\n"
        "  - {id: '2.1', title: A, file: ch1, status: reviewed}\n"
        "  - {id: '2.1', title: B, file: ch1, status: reviewed}\n",
        "## 2.1 A\nbody a\n\n## 2.1 B\nbody b\n",
    )

    issues = doctor.check_kb(kb)

    assert not any(
        i.level == "error" and "duplicate section id" in i.message for i in issues
    ), issues
    assert any(
        i.level == "warning" and "2.1" in i.message and "unreachable" in i.message
        for i in issues
    ), issues


def test_titleless_l2_subheading_is_not_flagged_as_orphan(tmp_path):
    """Critical 2 ruling (fix round 1): the R16 exemption -- a human's
    free-form '## Ownership' subheading in L2 is not a scaffold heading --
    must hold for doctor's orphan-heading check too, not just kb build's.
    The title-less heading is only in the .md; .raw.md gets no exemption
    (it isn't tested here because it isn't the point of this test)."""
    from strata_kb import doctor

    kb = _minimal_kb(tmp_path)
    d = kb / "d1"
    d.mkdir(parents=True)
    (d / "_manifest.yaml").write_text(
        "id: d1\ntitle: T\nsections:\n"
        "  - {id: '2.1', title: A, file: ch1, status: reviewed}\n",
        encoding="utf-8",
        newline="\n",
    )
    (d / "ch1.md").write_text(
        "## 2.1 A\nbody a\n\n## Ownership\n\nTeam notes.\n",
        encoding="utf-8",
        newline="\n",
    )
    (d / "ch1.raw.md").write_text("## 2.1 A\nbody a\n", encoding="utf-8", newline="\n")
    (kb / "index.yaml").write_text(
        "docs:\n  - id: d1\n    title: T\n", encoding="utf-8", newline="\n"
    )

    issues = doctor.check_kb(kb)

    assert not any("Ownership" in i.message for i in issues), issues


def test_heading_absent_from_the_manifest_is_an_error(tmp_path):
    from strata_kb import doctor

    kb = _minimal_kb(tmp_path)
    _doc_with(
        kb,
        "d1",
        "id: d1\ntitle: T\nsections:\n"
        "  - {id: '2.1', title: A, file: ch1, status: reviewed}\n",
        "## 2.1 A\nbody a\n\n## 2.77 Orphan\nnot in the manifest\n",
    )

    issues = doctor.check_kb(kb)

    assert any(
        i.level == "error" and "2.77" in i.message and "not in _manifest.yaml" in i.message
        for i in issues
    ), issues


def test_stale_token_counts_are_a_warning(tmp_path):
    """Important 4 ruling (fix round 1): downgraded from error. svc_note and
    code-ingest routinely leave stale counts in place on purpose (fixed by
    the next `kb build`) -- error would turn doctor red after every routine
    `kb svc note`. Still reported (review row #9's actual drift case), just
    not at a level that fails a healthy day-to-day workflow."""
    from strata_kb import doctor

    kb = _minimal_kb(tmp_path)
    _doc_with(
        kb,
        "d1",
        "id: d1\ntitle: T\nsections:\n"
        "  - id: '2.1'\n    title: A\n    file: ch1\n    status: reviewed\n"
        "    tokens: {l2: 99999, l3: 1}\n",
        "## 2.1 A\nbody a\n",
    )

    issues = doctor.check_kb(kb)

    assert any(
        i.level == "warning" and "tokens.l2" in i.message and "kb build" in i.message
        for i in issues
    ), issues


def test_tampered_hub_content_is_an_error(tmp_path):
    """M9 row #18: editing a published L2 file in place used to pass."""
    from strata_kb import doctor, federation

    fed = tmp_path / "hub" / "federation"
    entry = fed / "child"
    (entry / "d1").mkdir(parents=True)
    (entry / "_meta.yaml").write_text(
        "repo_id: child\nsource_commit: abc123\npublished_at: '2026-09-17'\n",
        encoding="utf-8",
        newline="\n",
    )
    (entry / "index.yaml").write_text(
        "docs:\n  - id: d1\n    title: T\n", encoding="utf-8", newline="\n"
    )
    (entry / "d1" / "_manifest.yaml").write_text(
        "id: d1\ntitle: T\nsections: []\n", encoding="utf-8", newline="\n"
    )
    (entry / "d1" / "ch1.md").write_text(
        "## 2.1 A\nbody\n", encoding="utf-8", newline="\n"
    )
    federation.write_federation_index(fed)

    # tamper: rewrite published content in place, leave the index alone
    (entry / "d1" / "ch1.md").write_text(
        "## 2.1 A\nTAMPERED\n", encoding="utf-8", newline="\n"
    )

    issues = doctor.check_published_digests(fed)

    assert any(
        i.level == "error" and "child" in i.message and "digest" in i.message
        for i in issues
    ), issues


def test_tampered_leaf_index_yaml_is_detected(tmp_path):
    """Final review item 2: _FED_TOP_SKIP was written for the top of
    federation/ (its own aggregate index.yaml/registry.yaml/.gitkeep), but
    entry_content_digest's root IS a leaf entry -- so the skip-by-bare-name
    check also stripped federation/<rid>/index.yaml itself: the doc titles,
    revisions, tags and L0 summaries /api/docs, the /ui overview and search
    serve. Tamper only that file (leave doc content alone) and the digest
    must still move."""
    from strata_kb import doctor, federation

    fed = tmp_path / "hub" / "federation"
    entry = fed / "child"
    (entry / "d1").mkdir(parents=True)
    (entry / "_meta.yaml").write_text(
        "repo_id: child\nsource_commit: abc123\npublished_at: '2026-09-17'\n",
        encoding="utf-8",
        newline="\n",
    )
    (entry / "index.yaml").write_text(
        "docs:\n  - id: d1\n    title: T\n    summary: real summary\n",
        encoding="utf-8",
        newline="\n",
    )
    (entry / "d1" / "_manifest.yaml").write_text(
        "id: d1\ntitle: T\nsections: []\n", encoding="utf-8", newline="\n"
    )
    (entry / "d1" / "ch1.md").write_text(
        "## 2.1 A\nbody\n", encoding="utf-8", newline="\n"
    )
    federation.write_federation_index(fed)

    # tamper: rewrite the leaf's own index.yaml, leave doc content alone
    (entry / "index.yaml").write_text(
        "docs:\n  - id: d1\n    title: T\n    summary: ATTACKER SUMMARY\n",
        encoding="utf-8",
        newline="\n",
    )

    issues = doctor.check_published_digests(fed)

    assert any(
        i.level == "error" and "child" in i.message and "digest" in i.message
        for i in issues
    ), issues


def test_a_snapshot_without_a_stored_digest_is_skipped_with_a_note(tmp_path):
    """Pre-0.24 hubs stay green: absent field is not a failure."""
    from strata_kb import doctor, federation

    fed = tmp_path / "hub" / "federation"
    entry = fed / "child"
    entry.mkdir(parents=True)
    (entry / "_meta.yaml").write_text(
        "repo_id: child\nsource_commit: abc\npublished_at: '2026-09-17'\n",
        encoding="utf-8",
        newline="\n",
    )
    (entry / "index.yaml").write_text(
        "docs:\n  - id: d1\n    title: T\n", encoding="utf-8", newline="\n"
    )
    federation.write_federation_index(fed)
    # strip the digests the way a 0.23 hub would never have written them
    text = (fed / "index.yaml").read_text(encoding="utf-8")
    stripped = "\n".join(
        ln for ln in text.splitlines() if "content_sha256" not in ln
    )
    (fed / "index.yaml").write_text(stripped + "\n", encoding="utf-8", newline="\n")

    issues = doctor.check_published_digests(fed)

    assert all(i.level != "error" for i in issues), issues
    assert any("not verified" in i.message for i in issues), issues


def test_fed_tree_digest_ignores_line_ending_differences(tmp_path):
    """H3c: a legacy hub cache cloned before F-D10 still has a CRLF working
    tree (neutralize_line_endings runs on clone, never on pull) -- a
    byte-identical tree must not read as tamper drift just because its
    line endings differ from what was hashed at publish time."""
    from strata_kb import doctor

    lf_root = tmp_path / "lf"
    crlf_root = tmp_path / "crlf"
    (lf_root / "d1").mkdir(parents=True)
    (crlf_root / "d1").mkdir(parents=True)
    (lf_root / "d1" / "ch1.md").write_text(
        "## 2.1 A\nbody\n", encoding="utf-8", newline="\n"
    )
    (crlf_root / "d1" / "ch1.md").write_text(
        "## 2.1 A\r\nbody\r\n", encoding="utf-8", newline="\n"
    )

    assert doctor._fed_tree_digest(lf_root) == doctor._fed_tree_digest(crlf_root)


def test_kb_tree_digest_ignores_line_ending_differences(tmp_path):
    """Same H3c self-heal, other digest (_kb_tree_digest, the local-vs-
    published compare)."""
    from strata_kb import doctor

    lf_root = tmp_path / "lf" / ".kb"
    crlf_root = tmp_path / "crlf" / ".kb"
    (lf_root / "d1").mkdir(parents=True)
    (crlf_root / "d1").mkdir(parents=True)
    (lf_root / "d1" / "ch1.md").write_text(
        "## 2.1 A\nbody\n", encoding="utf-8", newline="\n"
    )
    (crlf_root / "d1" / "ch1.md").write_text(
        "## 2.1 A\r\nbody\r\n", encoding="utf-8", newline="\n"
    )

    assert doctor._kb_tree_digest(lf_root) == doctor._kb_tree_digest(crlf_root)


def test_fed_tree_digest_folds_in_string_sorted_order_not_path_order(tmp_path):
    """Fix round 1, Important 4: folding directly over sorted(root.rglob("*"))
    sorts by Path, which is case-folded on Windows and case-sensitive on
    POSIX -- a digest written on the publisher's machine and verified on the
    operator's must fold in a platform-independent order. Provable in one
    process on one OS: for a tree holding 'doc-a/' and 'DOC-B/', sorted(Path)
    on this box yields ['doc-a/ch1.md', 'DOC-B/ch1.md'] (case-folded) while
    sorted(str) yields ['DOC-B/ch1.md', 'doc-a/ch1.md'] (case-sensitive) --
    the two disagree, so a digest folded in Path order differs from one
    folded in string order, and this test pins the function to the latter."""
    import hashlib

    from strata_kb import doctor

    (tmp_path / "doc-a").mkdir()
    (tmp_path / "DOC-B").mkdir()
    (tmp_path / "doc-a" / "ch1.md").write_text(
        "a body\n", encoding="utf-8", newline="\n"
    )
    (tmp_path / "DOC-B" / "ch1.md").write_text(
        "b body\n", encoding="utf-8", newline="\n"
    )

    path_order = [
        p.relative_to(tmp_path).as_posix()
        for p in sorted(tmp_path.rglob("*"))
        if p.is_file()
    ]
    str_order = sorted(path_order)
    # Fix round 3: PurePath.__lt__ is case-folded on Windows (NTFS is
    # case-insensitive) and compares the raw string on POSIX -- this tree
    # only disproves Path-order where the two disagree (Windows). On POSIX,
    # path_order == str_order already, so skip rather than assert: a hard
    # assert here made every POSIX CI leg (t1-tests, ubuntu-latest) red.
    if path_order == str_order:
        pytest.skip(
            "Path and str sort agree on this platform; tree cannot "
            "disprove Path-order here"
        )

    manifest = {
        rel: hashlib.sha256((tmp_path / rel).read_bytes()).hexdigest()
        for rel in str_order
    }
    expected = hashlib.sha256()
    for rel in sorted(manifest):
        expected.update(rel.encode("utf-8"))
        expected.update(b"\0")
        expected.update(manifest[rel].encode("utf-8"))
        expected.update(b"\0")

    assert doctor._fed_tree_digest(tmp_path) == expected.hexdigest()
