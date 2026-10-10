"""2026-10-10 review §6.2 F6: every publish re-hashed every entry of the hub
(4.8 s at 100 docs). A publish now hashes only what it wrote; every other
entry keeps the digest it was published with."""
from __future__ import annotations

import pytest

from strata_kb import federation, models
from tests.conftest import make_fed_entry


@pytest.fixture
def fed(tmp_path):
    root = tmp_path / "federation"
    for rid, doc in (("repo-a", "doc-a"), ("repo-b", "doc-b"), ("mid", "x")):
        make_fed_entry(root, rid, doc)
    federation.write_federation_index(root)
    return root


def _digests(root):
    index = models.load_yaml_model(root / "index.yaml", models.FederationIndex)
    return {d.repo_id: d.content_sha256 for d in index.docs}


def _hashed(monkeypatch):
    calls = []
    real = federation.entry_content_digest

    def spy(entry_dir):
        calls.append(entry_dir.name)
        return real(entry_dir)

    monkeypatch.setattr(federation, "entry_content_digest", spy)
    return calls


def test_a_publish_hashes_only_the_repo_it_wrote(fed, monkeypatch):
    before = _digests(fed)
    (fed / "repo-a" / "doc-a" / "ch1.md").write_text("## 1.1 Changed\n\nnew\n", encoding="utf-8")
    calls = _hashed(monkeypatch)
    federation.write_federation_index(fed, changed={"repo-a"})
    after = _digests(fed)
    assert calls == ["repo-a"]
    assert after["repo-a"] != before["repo-a"]
    assert after["repo-b"] == before["repo-b"]


def test_an_in_place_edit_elsewhere_is_not_re_recorded_by_a_publish(fed):
    """The recorded digest stays what repo-b published, so `kb doctor`
    still flags the edit instead of an unrelated publish laundering it."""
    before = _digests(fed)
    (fed / "repo-b" / "doc-b" / "ch1.md").write_text("tampered\n", encoding="utf-8")
    federation.write_federation_index(fed, changed={"repo-a"})
    assert _digests(fed)["repo-b"] == before["repo-b"]
    live = federation.entry_content_digest(fed / "repo-b")
    assert live != before["repo-b"]


def test_a_full_rebuild_recomputes_everything(fed, monkeypatch):
    calls = _hashed(monkeypatch)
    federation.write_federation_index(fed)
    assert sorted(calls) == ["mid", "repo-a", "repo-b"]


def test_a_new_entry_or_an_unreadable_index_is_hashed(fed, monkeypatch):
    make_fed_entry(fed, "repo-c", "doc-c")
    calls = _hashed(monkeypatch)
    federation.write_federation_index(fed, changed={"repo-a"})
    assert sorted(calls) == ["repo-a", "repo-c"]
    (fed / "index.yaml").write_text("docs: [unclosed\n", encoding="utf-8")
    calls.clear()
    federation.write_federation_index(fed, changed={"repo-a"})
    assert sorted(calls) == ["mid", "repo-a", "repo-b", "repo-c"]


def test_nested_entries_are_in_scope_of_their_hub():
    assert federation._in_scope("mid/repo-x", {"mid"})
    assert federation._in_scope("mid", {"mid"})
    assert not federation._in_scope("middle", {"mid"})
    assert not federation._in_scope("repo-a", {"mid"})
