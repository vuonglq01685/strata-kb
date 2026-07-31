from pathlib import Path

import pytest

from center_kb import models
from center_kb.hub import HubHandle
from center_kb.models import Manifest, SectionEntry, SectionTokens
from center_kb.web import uidata
from tests.conftest import make_fed_entry


def _hub(fed_hub) -> HubHandle:
    return HubHandle(root=fed_hub)


@pytest.fixture
def mixed_status_hub(tmp_path: Path, run_git) -> Path:
    """Hub with a single federated doc whose 3 sections cover every status —
    exercises review_queue ordering/exclusion, catalog mixed counts, and a
    multi-valued status_map, none of which a uniformly-summarized fixture
    can assert."""
    from center_kb.federation import write_federation_index

    hub = tmp_path / "kb-hub"
    (hub / ".kb").mkdir(parents=True)
    models.save_yaml_model(hub / ".kb" / "index.yaml", models.KBIndex())
    fed = hub / "federation"
    entry = make_fed_entry(fed, "mix-kb", "mixed-doc", sec_id="1.1", sec_title="A")
    models.save_yaml_model(
        entry / "mixed-doc" / "_manifest.yaml",
        models.Manifest(
            id="mixed-doc",
            title="mixed-doc",
            sections=[
                models.SectionEntry(
                    id="1.1", title="A", summary="s", status="pending", file="ch1"
                ),
                models.SectionEntry(
                    id="1.2", title="B", summary="s", status="summarized", file="ch1"
                ),
                models.SectionEntry(
                    id="1.3", title="C", summary="s", status="reviewed", file="ch1"
                ),
            ],
        ),
    )
    write_federation_index(fed)
    run_git(hub, "init")
    run_git(hub, "config", "user.name", "test")
    run_git(hub, "config", "user.email", "test@test.local")
    run_git(hub, "add", "-A")
    run_git(hub, "commit", "-m", "hub v1")
    return hub


def test_catalog_counts_statuses(fed_hub):
    hub = _hub(fed_hub)
    docs = uidata.catalog(hub)
    assert docs, "fed_hub fixture must expose at least one doc"
    d = docs[0]
    assert d.total == d.reviewed + d.summarized + d.pending
    assert 0 <= d.done_pct <= 100


def test_all_tags_sorted_unique(fed_hub):
    tags = uidata.all_tags(_hub(fed_hub))
    assert tags == sorted(set(tags))


def test_review_queue_pending_first_and_excludes_reviewed(fed_hub):
    queue = uidata.review_queue(_hub(fed_hub), limit=50)
    assert all(item.status != "reviewed" for item in queue)
    statuses = [item.status for item in queue]
    if "summarized" in statuses and "pending" in statuses:
        assert statuses.index("pending") < statuses.index("summarized")


def test_mixed_status_queue_catalog_and_status_map(mixed_status_hub):
    hub = _hub(mixed_status_hub)

    queue = uidata.review_queue(hub, limit=50)
    assert [item.status for item in queue] == ["pending", "summarized"]

    docs = uidata.catalog(hub)
    assert len(docs) == 1
    d = docs[0]
    assert (d.total, d.reviewed, d.summarized, d.pending) == (3, 1, 1, 1)
    assert d.done_pct == round(100 * 2 / 3)

    smap = uidata.status_map(hub)
    assert smap == {
        ("mix-kb", "mixed-doc", "1.1"): "pending",
        ("mix-kb", "mixed-doc", "1.2"): "summarized",
        ("mix-kb", "mixed-doc", "1.3"): "reviewed",
    }


def test_store_stats_shapes(fed_hub):
    stats = uidata.store_stats(_hub(fed_hub))
    assert stats.docs >= 1
    assert stats.sections >= 1
    assert stats.repos >= 1
    assert stats.l0_tokens >= 0


def test_store_stats_docs_matches_catalog_when_manifest_broken(fed_hub):
    # store_stats() used to count docs off the federation index (repo.index.docs),
    # while catalog() counts manifest-backed docs via _iter_manifests. A broken
    # manifest made them disagree — Overview would claim 3 docs while Documents
    # lists 2. Both must now walk the same manifest source.
    broken_manifest = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "_manifest.yaml"
    broken_manifest.write_text("not: [valid, yaml: structure", encoding="utf-8")

    hub = _hub(fed_hub)
    stats = uidata.store_stats(hub)
    docs = uidata.catalog(hub)

    assert stats.docs == len(docs) == 1


def test_last_publish_no_git_is_empty_not_error(tmp_path: Path):
    # fed_hub (used elsewhere in this module) IS a git repo — this test's intent
    # is the *graceful-degrade* path, so build a hub without git init instead.
    hub_root = tmp_path / "no-git-hub"
    (hub_root / ".kb").mkdir(parents=True)
    models.save_yaml_model(hub_root / ".kb" / "index.yaml", models.KBIndex())
    make_fed_entry(hub_root / "federation", "icao-kb", "icao-annex-2")
    info = uidata.last_publish(HubHandle(root=hub_root))
    assert info.commit == ""
    assert isinstance(info.repos, list)


def test_last_publish_with_git_returns_short_commit(fed_hub):
    info = uidata.last_publish(_hub(fed_hub))
    assert len(info.commit) == 7
    assert isinstance(info.repos, list)


def test_last_publish_aggregates_repos_and_published_at(fed_hub):
    # fed_hub publishes icao-kb/icao-annex-2 and arinc-kb/arinc-424, both via
    # make_fed_entry's default published_at — pin the exact aggregation so a
    # regression in the sort/max logic shows up here, not just "is a list".
    info = uidata.last_publish(_hub(fed_hub))
    assert info.repos == ["arinc-kb", "icao-kb"]
    assert info.published_at == "2026-07-13T00:00:00+00:00"


def test_last_publish_missing_hub_root_is_empty_not_error(tmp_path: Path):
    # hub.root vanished (or was never created): gitio.head_commit's subprocess
    # call raises FileNotFoundError/OSError, not gitio.GitError — this must
    # degrade gracefully like every other git-metadata failure, never 500.
    missing_root = tmp_path / "does-not-exist"
    info = uidata.last_publish(HubHandle(root=missing_root))
    assert info.commit == ""
    assert info.repos == []
    assert info.published_at == ""


def test_last_publish_unreadable_federation_index_is_empty_not_error(
    tmp_path: Path, run_git
):
    # federation/index.yaml exists but fails to parse (hand-edited, disk
    # corruption, a bad merge...) — models.load_yaml_model raises, and the
    # `except Exception` branch in last_publish must degrade to empty
    # repos/published_at rather than propagate a 500 up through the overview
    # screen.
    hub_root = tmp_path / "bad-index-hub"
    (hub_root / ".kb").mkdir(parents=True)
    models.save_yaml_model(hub_root / ".kb" / "index.yaml", models.KBIndex())
    fed = hub_root / "federation"
    fed.mkdir()
    (fed / "index.yaml").write_text("docs: [unterminated", encoding="utf-8")
    run_git(hub_root, "init")
    run_git(hub_root, "config", "user.name", "test")
    run_git(hub_root, "config", "user.email", "test@test.local")
    run_git(hub_root, "add", "-A")
    run_git(hub_root, "commit", "-m", "hub v1")

    info = uidata.last_publish(HubHandle(root=hub_root))

    assert info.repos == []
    assert info.published_at == ""


def test_doc_coverage_and_prev_next():
    m = Manifest(
        id="d", title="D",
        sections=[
            SectionEntry(id="1", title="A", file="a.md", status="reviewed",
                         tokens=SectionTokens(l2=10, l3=20)),
            SectionEntry(id="2", title="B", file="b.md", status="pending"),
            SectionEntry(id="3", title="C", file="c.md", status="summarized"),
        ],
    )
    cov = uidata.doc_coverage(m)
    assert (cov.total, cov.reviewed, cov.summarized, cov.pending) == (3, 1, 1, 1)
    prev, nxt = uidata.prev_next(m, "2")
    assert prev.id == "1" and nxt.id == "3"
    prev, nxt = uidata.prev_next(m, "1")
    assert prev is None and nxt.id == "2"
    prev, nxt = uidata.prev_next(m, "3")
    assert prev.id == "2" and nxt is None
    assert uidata.prev_next(m, "zz") == (None, None)


def test_status_map_keys(fed_hub):
    smap = uidata.status_map(_hub(fed_hub))
    assert all(len(k) == 3 for k in smap)
    assert all(v in ("pending", "summarized", "reviewed") for v in smap.values())


def test_section_tree_single_file_has_no_chapter_rows():
    m = models.Manifest(id="d", title="D", sections=[
        models.SectionEntry(id="1", title="One", file="ch1-intro.md"),
        models.SectionEntry(id="2", title="Two", file="ch1-intro.md"),
    ])
    tree = uidata.section_tree(m)
    assert [n.kind for n in tree] == ["section", "section"]
    assert [n.id for n in tree] == ["1", "2"]


def test_section_tree_groups_by_file_with_chapter_headers():
    m = models.Manifest(id="d", title="D", sections=[
        models.SectionEntry(id="1", title="One", file="ch1-intro.md",
                            status="reviewed"),
        models.SectionEntry(id="1.2", title="One-two", file="ch1-intro.md"),
        models.SectionEntry(id="2", title="Two", file="ch2-data.md"),
    ])
    tree = uidata.section_tree(m)
    assert [(n.kind, n.label) for n in tree] == [
        ("chapter", "ch1 intro"), ("section", "One"), ("section", "One-two"),
        ("chapter", "ch2 data"), ("section", "Two"),
    ]
    assert tree[1].status == "reviewed"


def test_section_tree_empty_manifest():
    assert uidata.section_tree(models.Manifest(id="d", title="D")) == []


def test_inject_heading_anchors_adds_ids_and_toc():
    html_in = "<h2>5.129 Restrictive Airspace</h2><p>x</p><h3>Field notes</h3>"
    out, toc = uidata.inject_heading_anchors(html_in)
    assert '<h2 id="5-129-restrictive-airspace">' in out
    assert '<h3 id="field-notes">' in out
    assert [(t.anchor, t.label) for t in toc] == [
        ("5-129-restrictive-airspace", "5.129 Restrictive Airspace"),
        ("field-notes", "Field notes"),
    ]


def test_inject_heading_anchors_dedupes_slugs():
    out, toc = uidata.inject_heading_anchors("<h2>Same</h2><h2>Same</h2>")
    assert [t.anchor for t in toc] == ["same", "same-2"]
    assert 'id="same-2"' in out


def test_inject_heading_anchors_no_headings():
    out, toc = uidata.inject_heading_anchors("<p>plain</p>")
    assert out == "<p>plain</p>"
    assert toc == []


def test_inject_heading_anchors_unescapes_label():
    out, toc = uidata.inject_heading_anchors("<h2>A &amp; B</h2>")
    assert toc[0].label == "A & B"
    assert toc[0].anchor == "a-b"
