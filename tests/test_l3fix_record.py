from __future__ import annotations

from strata_kb import models, pubgate
from strata_kb.cli import app
from strata_kb.l3check import fixrecord, fixswitch, report
from strata_kb.l3check.fixrecord import BaselineUnit, FixEntry, L3Fix
from strata_kb.l3check.report import Confirmation
from tests.test_ingest_cli import _ingest_args, _stub_parser, _write_pdf
from tests.test_l3check_report import _kb
from tests.test_l3fix_spans import NOISY_ITEMS, runner


def _rec(baseline=None, entries=None) -> L3Fix:
    return L3Fix(
        baseline={
            k: BaselineUnit(file=f, l3_sha256=h)
            for k, (f, h) in (baseline or {}).items()
        },
        sections=entries or [],
    )


def _entry(sid="4.2", sha="h2", file="a", **kw) -> FixEntry:
    return FixEntry(id=sid, file=file, l3_sha256=sha, by="cursor", at="t", **kw)


def test_baseline_matching_is_not_blocked():
    rec = _rec(baseline={"1": ("a", "h1")})
    assert fixrecord.blocked(rec, {"1": "h1"}) == []


def test_direct_edit_blocks():
    rec = _rec(baseline={"1": ("a", "h1")})
    assert fixrecord.blocked(rec, {"1": "h2"}) == [
        ("1", "edited outside kb l3 fix apply")
    ]


def test_removed_unit_blocks():
    rec = _rec(baseline={"x1": ("a", "h1")})
    assert fixrecord.blocked(rec, {}) == [("x1", "removed outside kb l3 fix apply")]


def test_ai_fix_unconfirmed_then_confirmed():
    rec = _rec(entries=[_entry()])
    assert fixrecord.blocked(rec, {"4.2": "h2"}) == [("4.2", "ai-fix awaiting review")]
    rec.sections[0].confirmed = Confirmation(by="r", at="t", l3_sha256="h2")
    assert fixrecord.blocked(rec, {"4.2": "h2"}) == []


def test_edit_after_ai_fix_blocks_as_outside():
    rec = _rec(baseline={"4.2": ("a", "h1")}, entries=[_entry()])
    assert fixrecord.blocked(rec, {"4.2": "h3"}) == [
        ("4.2", "edited outside kb l3 fix apply")
    ]


def test_newest_entry_wins():
    rec = _rec(entries=[_entry(sha="h2"), _entry(sha="h3")])
    assert fixrecord.blocked(rec, {"4.2": "h3"}) == [("4.2", "ai-fix awaiting review")]


def test_reset_drops_reingested_files_and_rebaselines(tmp_path):
    for stem in ("a", "b"):
        (tmp_path / f"{stem}.raw.md").write_text("x", encoding="utf-8")
    fixrecord.save(
        tmp_path,
        _rec(
            baseline={"1": ("a", "old"), "2": ("b", "keep")},
            entries=[_entry("1", file="a"), _entry("2", file="b")],
        ),
    )
    fresh = {"1": BaselineUnit(file="a", l3_sha256="new")}
    fixrecord.reset_on_ingest(tmp_path, {"a"}, fresh, switch_on=True)
    rec = fixrecord.load(tmp_path)
    assert {k: v.l3_sha256 for k, v in rec.baseline.items()} == {
        "1": "new",
        "2": "keep",
    }
    assert [e.id for e in rec.sections] == ["2"]


def test_reset_drops_files_gone_from_disk(tmp_path):
    (tmp_path / "b.raw.md").write_text("x", encoding="utf-8")
    fixrecord.save(tmp_path, _rec(baseline={"1": ("a", "h"), "2": ("b", "h")}))
    fixrecord.reset_on_ingest(tmp_path, set(), {}, switch_on=False)
    assert list(fixrecord.load(tmp_path).baseline) == ["2"]


def test_reset_switch_off_with_nothing_left_deletes_file(tmp_path):
    (tmp_path / "a.raw.md").write_text("x", encoding="utf-8")
    fixrecord.save(tmp_path, _rec(baseline={"1": ("a", "h")}))
    fixrecord.reset_on_ingest(tmp_path, {"a"}, {}, switch_on=False)
    assert not (tmp_path / fixrecord.FILE_NAME).exists()


def test_reset_switch_off_creates_nothing(tmp_path):
    fixrecord.reset_on_ingest(tmp_path, {"a"}, {}, switch_on=False)
    assert not (tmp_path / fixrecord.FILE_NAME).exists()


def test_blocked_docs_includes_l3fix_only_doc(tmp_path):
    kb = _kb(tmp_path)
    fixrecord.save(
        kb / "doc", L3Fix(baseline={"1": BaselineUnit(file="a", l3_sha256="stale")})
    )
    assert report.blocked_docs(kb) == [("doc", ["1"])]


def test_blocked_docs_unions_l3check_then_fix_ids(tmp_path):
    kb = _kb(tmp_path)
    digests = report.current_digests(kb, "doc")
    check = report.L3Check(
        checked_at="t",
        sections=[
            report.SectionCheck(
                id="2",
                l3_sha256=digests["2"],
                findings=[report.Finding(kind="content", page=1)],
            )
        ],
    )
    report.save(kb / "doc", check)
    fixrecord.save(
        kb / "doc",
        L3Fix(
            baseline={
                "1": BaselineUnit(file="a", l3_sha256="stale"),
                "2": BaselineUnit(file="a", l3_sha256="stale"),
            }
        ),
    )
    assert report.blocked_docs(kb) == [("doc", ["2", "1"])]


def test_switch_off_keeps_gate(tmp_path):
    kb = _kb(tmp_path)
    fixswitch.turn_on(kb)
    digest = report.current_digests(kb, "doc")["1"]
    fixrecord.save(kb / "doc", _rec(entries=[_entry("1", digest)]))
    before = report.blocked_docs(kb)
    fixswitch.turn_off(kb)
    assert before == [("doc", ["1"])]
    assert report.blocked_docs(kb) == before


def test_l3fix_file_is_local_only():
    manifest = {"demo-doc/_l3fix.yaml": "h1", "demo-doc/_manifest.yaml": "h2"}
    kept, skipped = pubgate.split_allowlist(manifest, keep_records=False)
    assert "demo-doc/_l3fix.yaml" not in kept
    assert skipped == []
    assert fixrecord.FILE_NAME in pubgate._LOCAL_ONLY_BASENAMES


def _ingest(tmp_path, monkeypatch, *, switch_on):
    from strata_kb.ingest import parser, pdftext

    _stub_parser(monkeypatch, NOISY_ITEMS)
    monkeypatch.setattr(parser, "furniture_by_page", lambda doc: {})
    monkeypatch.setattr(
        pdftext, "page_texts", lambda pdf: {1: "intro", 2: "field", 3: "value"}
    )
    _write_pdf(tmp_path)
    kb = tmp_path / ".kb"
    kb.mkdir()
    if switch_on:
        fixswitch.turn_on(kb)
    result = runner.invoke(app, _ingest_args(tmp_path, ["--llm", "none"]))
    assert result.exit_code == 0, result.output
    return result, kb / "arinc-424"


def test_ingest_with_switch_on_writes_baseline(tmp_path, monkeypatch):
    result, doc_dir = _ingest(tmp_path, monkeypatch, switch_on=True)

    manifest = models.load_yaml_model(doc_dir / "_manifest.yaml", models.Manifest)
    digests = report.current_digests(tmp_path / ".kb", "arinc-424")
    rec = fixrecord.load(doc_dir)
    assert rec is not None and rec.sections == []
    assert {k: v.l3_sha256 for k, v in rec.baseline.items()} == digests
    assert {k: v.file for k, v in rec.baseline.items()} == {
        s.id: s.file for s in manifest.sections
    }
    assert set(digests) == {s.id for s in manifest.sections}
    assert (
        "AI fix: on — run the kb-l3-fix skill (or /kb-l3-fix), then kb l3 report <id>"
        in result.output
    )


def test_ingest_with_switch_off_writes_no_l3fix(tmp_path, monkeypatch):
    result, doc_dir = _ingest(tmp_path, monkeypatch, switch_on=False)

    assert not (doc_dir / fixrecord.FILE_NAME).exists()
    assert "AI fix" not in result.output
