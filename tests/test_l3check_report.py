from pathlib import Path

import pytest

from strata_kb import models
from strata_kb.l3check import report
from strata_kb.l3check.report import (
    AgentVerdict,
    Finding,
    FindingKind,
    L3Check,
    SectionCheck,
)

RAW = "## 1 A\n\nalpha body\n\n## 2 B\n\nbeta body\n"


def _kb(tmp_path: Path) -> Path:
    kb = tmp_path / ".kb"
    doc = kb / "doc"
    doc.mkdir(parents=True)
    models.save_yaml_model(
        kb / "index.yaml", models.KBIndex(docs=[models.IndexEntry(id="doc", title="D")])
    )
    sections = [
        models.SectionEntry(id=i, title=t, file="a")
        for i, t in (("1", "A"), ("2", "B"))
    ]
    models.save_yaml_model(
        doc / "_manifest.yaml", models.Manifest(id="doc", title="D", sections=sections)
    )
    (doc / "a.raw.md").write_text(RAW, encoding="utf-8")
    return kb


def _sec(sid: str, sha: str = "h", kind: FindingKind = "content", **kw) -> SectionCheck:
    return SectionCheck(
        id=sid, l3_sha256=sha, findings=[Finding(kind=kind, page=1)], **kw
    )


def _flag(kb: Path, *sids: str) -> None:
    digests = report.current_digests(kb, "doc")
    check = L3Check(checked_at="t", sections=[_sec(s, digests[s]) for s in sids])
    report.save(kb / "doc", check)


def test_roundtrip_and_empty_deletes_file(tmp_path):
    kb = _kb(tmp_path)
    check = L3Check(
        checked_at="2026-01-01T00:00:00Z",
        source_sha256="abc",
        sections=[
            SectionCheck(
                id="1",
                l3_sha256="h",
                findings=[
                    Finding(
                        kind="order",
                        page=3,
                        evidence={"l3": "x"},
                        agent=AgentVerdict(verdict="unsure", reason="r"),
                    )
                ],
            )
        ],
    )
    report.save(kb / "doc", check)
    assert report.load(kb / "doc") == check
    report.save(kb / "doc", L3Check(checked_at="t"))
    assert not (kb / "doc" / report.FILE_NAME).exists()
    assert report.load(kb / "doc") is None


def test_unconfirmed_until_confirmed(tmp_path):
    kb = _kb(tmp_path)
    _flag(kb, "1")
    assert report.blocked_docs(kb) == [("doc", ["1"])]
    assert report.confirm(kb, "doc", ["1"], by="r") == ["1"]
    assert report.blocked_docs(kb) == []


def test_confirm_all_when_ids_none(tmp_path):
    kb = _kb(tmp_path)
    _flag(kb, "1", "2")
    assert report.confirm(kb, "doc", None, by="r") == ["1", "2"]
    assert report.blocked_docs(kb) == []


def test_hand_edit_reblocks(tmp_path):
    kb = _kb(tmp_path)
    _flag(kb, "1")
    report.confirm(kb, "doc", ["1"], by="r")
    raw = kb / "doc" / "a.raw.md"
    raw.write_text(RAW.replace("alpha", "ALPHA"), encoding="utf-8")
    assert report.blocked_docs(kb) == [("doc", ["1"])]


def test_vanished_slice_counts_as_unconfirmed(tmp_path):
    kb = _kb(tmp_path)
    _flag(kb, "1")
    report.confirm(kb, "doc", ["1"], by="r")
    (kb / "doc" / "a.raw.md").unlink()
    assert report.blocked_docs(kb) == [("doc", ["1"])]


def test_merge_keeps_confirmation_when_unchanged():
    conf = report.Confirmation(by="r", at="t", l3_sha256="h")
    prev = L3Check(checked_at="old", sections=[_sec("1", confirmed=conf)])
    verdict = AgentVerdict(verdict="spurious", reason="ocr")
    fresh_sec = _sec("1")
    fresh_sec.findings[0].agent = verdict
    fresh = L3Check(checked_at="new", source_sha256="s", sections=[fresh_sec])
    out = report.merge(prev, fresh, {"1"})
    assert out.checked_at == "new" and out.source_sha256 == "s"
    assert out.sections[0].confirmed == conf


def test_merge_inherits_agent_verdict_when_unchanged():
    verdict = AgentVerdict(verdict="intentional", reason="why")
    prev_sec = _sec("1")
    prev_sec.findings[0].agent = verdict
    out = report.merge(
        L3Check(checked_at="o", sections=[prev_sec]),
        L3Check(checked_at="n", sections=[_sec("1")]),
        {"1"},
    )
    assert out.sections[0].findings[0].agent == verdict


def test_merge_drops_confirmation_when_findings_change():
    conf = report.Confirmation(by="r", at="t", l3_sha256="h")
    prev = L3Check(checked_at="o", sections=[_sec("1", confirmed=conf)])
    fresh = L3Check(checked_at="n", sections=[_sec("1", kind="order")])
    assert report.merge(prev, fresh, {"1"}).sections[0].confirmed is None


def test_merge_drops_confirmation_when_l3_changes():
    conf = report.Confirmation(by="r", at="t", l3_sha256="h")
    prev = L3Check(checked_at="o", sections=[_sec("1", confirmed=conf)])
    fresh = L3Check(checked_at="n", sections=[_sec("1", sha="h2")])
    assert report.merge(prev, fresh, {"1"}).sections[0].confirmed is None


def test_merge_partial_reingest_keeps_other_sections():
    prev = L3Check(checked_at="o", sections=[_sec("1"), _sec("2")])
    fresh = L3Check(checked_at="n", sections=[_sec("2", sha="h2")])
    out = report.merge(prev, fresh, {"2"})
    assert [(s.id, s.l3_sha256) for s in out.sections] == [("1", "h"), ("2", "h2")]


def test_merge_without_previous_is_fresh():
    fresh = L3Check(checked_at="n", sections=[_sec("1")])
    assert report.merge(None, fresh, {"1"}) == fresh


def test_confirm_unknown_id_raises(tmp_path):
    kb = _kb(tmp_path)
    _flag(kb, "1")
    with pytest.raises(ValueError, match="1"):
        report.confirm(kb, "doc", ["9"], by="r")


def test_confirm_without_file_raises(tmp_path):
    kb = _kb(tmp_path)
    with pytest.raises(ValueError, match="doc"):
        report.confirm(kb, "doc", None, by="r")


def test_doc_without_file_not_blocked(tmp_path):
    assert report.blocked_docs(_kb(tmp_path)) == []


def test_repeated_id_edit_of_earlier_occurrence_reblocks(tmp_path):
    kb = _kb(tmp_path)
    doc = kb / "doc"
    sections = [models.SectionEntry(id="1", title="A", file="a") for _ in range(2)]
    models.save_yaml_model(
        doc / "_manifest.yaml", models.Manifest(id="doc", title="D", sections=sections)
    )
    raw = doc / "a.raw.md"
    text = "## 1 A\n\nfirst body\n\n## 1 A again\n\nsecond body\n"
    raw.write_text(text, encoding="utf-8")
    _flag(kb, "1")
    report.confirm(kb, "doc", ["1"], by="r")
    assert report.blocked_docs(kb) == []
    raw.write_text(text.replace("first", "FIRST"), encoding="utf-8")
    assert report.blocked_docs(kb) == [("doc", ["1"])]


def test_confirm_section_gone_from_l3_raises(tmp_path):
    kb = _kb(tmp_path)
    _flag(kb, "1")
    (kb / "doc" / "a.raw.md").unlink()
    with pytest.raises(ValueError, match="re-ingest doc"):
        report.confirm(kb, "doc", ["1"], by="r")
    assert report.load(kb / "doc").sections[0].confirmed is None  # type: ignore[union-attr]
