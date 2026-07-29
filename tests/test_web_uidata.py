from pathlib import Path

from center_kb import models
from center_kb.hub import HubHandle
from center_kb.models import Manifest, SectionEntry, SectionTokens
from center_kb.web import uidata
from tests.conftest import make_fed_entry


def _hub(fed_hub) -> HubHandle:
    return HubHandle(root=fed_hub)


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


def test_store_stats_shapes(fed_hub):
    stats = uidata.store_stats(_hub(fed_hub))
    assert stats.docs >= 1
    assert stats.sections >= 1
    assert stats.repos >= 1
    assert stats.l0_tokens >= 0


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
