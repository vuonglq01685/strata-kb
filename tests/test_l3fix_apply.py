from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb import models
from strata_kb.cli import app
from strata_kb.config import set_block_enabled
from strata_kb.ingest.scaffold import scaffold_doc
from strata_kb.ingest.sectioner import SectionUnit
from strata_kb.l3check import fix, fixrecord, lint, report, spans
from strata_kb.l3check.fixrecord import BaselineUnit, L3Fix
from strata_kb.l3check.report import Finding, L3Check, SectionCheck
from strata_kb.l3check.spans import SpansFile, UnitSpan
from strata_kb.mdutils import extract_tables

runner = CliRunner()

FOOTER = "Quy chế nhân sự · Phiên bản 2026 · Trang 12/40"
FURNITURE = {12: [FOOTER]}
SENTENCE = (
    "Người lao động làm việc đủ 12 tháng được nghỉ phép năm hưởng nguyên lương "
    "theo hợp đồng."
)
PDF_PAGES = {
    11: "4.1 PHẠM VI ÁP DỤNG Quy chế này áp dụng cho mọi nhân viên chính thức.",
    12: (
        f"4.2 NGHỈ PHÉP NĂM {SENTENCE} Nghỉ phép được tính theo năm dương lịch. "
        "4.2.1 Số ngày nghỉ Thâm niên Số ngày Dưới 5 năm 12 ngày Từ 5 năm 15 ngày "
        f"{FOOTER}"
    ),
    13: "Ghi chú: ngày nghỉ phép chưa dùng được chuyển sang năm sau tối đa 5 ngày.",
}
BODY_41 = "Quy chế này áp dụng cho mọi nhân viên chính thức."
TABLE = (
    "| Thâm niên | Số ngày |\n| --- | --- |\n"
    "| Dưới 5 năm | 12 ngày |\n| Từ 5 năm | 15 ngày |"
)
IMAGE = "![Sơ đồ phê duyệt](assets/" + "a" * 64 + ".png)"
NOTE = "Ghi chú: ngày nghỉ phép chưa dùng được chuyển sang năm sau tối đa 5 ngày."
BROKEN_BODY = (
    "Người lao động làm việc đủ 12 tháng được nghỉ phép năm hưởng nguyên lương theo\n\n"
    "hợp đồng. Nghỉ phép được tính theo năm dương lịch.\n\n"
    f"#### 4.2.1 Số ngày nghỉ\n\n{IMAGE}\n\n{TABLE}\n\n{NOTE}"
)
BROKEN_42 = f"## x1 4.2 NGHỈ PHÉP NĂM\n\n{BROKEN_BODY}"
FIXED_BODY = (
    f"{SENTENCE}\n\nNghỉ phép được tính theo năm dương lịch.\n\n"
    f"### 4.2.1 Số ngày nghỉ\n\n{IMAGE}\n\n{TABLE}\n\n{NOTE}"
)
FIXED_42 = f"## 4.2 NGHỈ PHÉP NĂM\n\n{FIXED_BODY}"


def _work(kb: Path) -> Path:
    return kb.parent / ".kb-work"


def _draft_path(kb: Path, name: str) -> Path:
    return _work(kb) / "doc" / fix.DRAFT_DIR / f"{name}.md"


def _draft(kb: Path, name: str, text: str, raw: bytes | None = None) -> None:
    path = _draft_path(kb, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw if raw is not None else text.encode("utf-8"))


def _manifest(kb: Path) -> models.Manifest:
    return models.load_yaml_model(kb / "doc" / "_manifest.yaml", models.Manifest)


def _stem(kb: Path) -> str:
    return _manifest(kb).sections[0].file


def _raw_path(kb: Path) -> Path:
    return kb / "doc" / f"{_stem(kb)}.raw.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _units() -> list[SectionUnit]:
    return [
        SectionUnit("4.1", "PHẠM VI ÁP DỤNG", "4", BODY_41, []),
        SectionUnit(
            "x1", "4.2 NGHỈ PHÉP NĂM", "4", BROKEN_BODY, extract_tables(BROKEN_BODY)
        ),
    ]


def _build(tmp_path: Path, switch: bool = True) -> Path:
    kb = tmp_path / ".kb"
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-source")
    scaffold_doc(
        _units(),
        doc_id="doc",
        title="Doc",
        tags=[],
        revision="1",
        source_path=pdf,
        kb_dir=kb,
    )
    stem = _stem(kb)
    spans.save(
        _work(kb),
        "doc",
        SpansFile(
            doc_id="doc",
            units=[
                UnitSpan(id="4.1", file=stem, chapter="4", page=11, end_page=11),
                UnitSpan(id="x1", file=stem, chapter="4", page=12, end_page=13),
            ],
            fallback_units=["x1"],
        ),
    )
    digests = report.current_digests(kb, "doc")
    report.save(
        kb / "doc",
        L3Check(
            checked_at="t",
            sections=[
                SectionCheck(
                    id="x1",
                    l3_sha256=digests["x1"],
                    findings=[Finding(kind="fallback", page=12)],
                )
            ],
        ),
    )
    fixrecord.save(
        kb / "doc",
        L3Fix(
            baseline={
                s: BaselineUnit(file=stem, l3_sha256=d) for s, d in digests.items()
            }
        ),
    )
    if switch:
        set_block_enabled(kb / "config.yaml", "l3_fix", True)
    return kb


@pytest.fixture
def kb(tmp_path: Path) -> Path:
    return _build(tmp_path)


def _apply(kb: Path, only=None, **kw) -> list[fix.ApplyResult]:
    drafts = fix.load_drafts(_work(kb), "doc", only)
    return fix.apply_drafts(
        kb,
        _work(kb),
        "doc",
        drafts,
        kw.get("pdf_pages", PDF_PAGES),
        kw.get("furniture", FURNITURE),
        assistant=kw.get("assistant", "cursor"),
        from_image=kw.get("from_image", set()),
    )


def test_fixed_draft_applies_and_records(kb):
    _draft(kb, "x1", FIXED_42)

    [r] = _apply(kb)

    assert r.status == "applied" and r.new_ids == ("4.2",), r.reason
    raw = _read(_raw_path(kb))
    assert "## 4.2 NGHỈ PHÉP NĂM" in raw and "## x1" not in raw
    assert [s.id for s in _manifest(kb).sections] == ["4.1", "4.2"]
    assert "<!-- TODO:summarize 4.2 -->" in _read(kb / "doc" / f"{_stem(kb)}.md")
    rec = fixrecord.load(kb / "doc")
    assert rec is not None
    assert (rec.sections[0].was, rec.sections[0].by, rec.sections[0].verified) == (
        "x1",
        "cursor",
        True,
    )
    assert set(rec.baseline) == {"4.1"}
    assert {"re-id", "heading-level"} <= set(rec.sections[0].changes)
    assert report.blocked_docs(kb) == [("doc", ["4.2"])]
    assert not _draft_path(kb, "x1").exists()
    data = spans.load(_work(kb), "doc")
    assert data is not None
    assert [(u.id, u.page, u.end_page) for u in data.units] == [
        ("4.1", 11, 11),
        ("4.2", 12, 13),
    ]
    assert data.fallback_units == []


@pytest.mark.parametrize(
    ("mutate", "check"),
    [
        (lambda t: t.replace("được nghỉ", "không được nghỉ"), "words"),
        (lambda t: t.replace("12 ngày", "13 ngày", 1), "tables"),
        (lambda t: t.replace(SENTENCE + "\n\n", ""), "words"),
        (lambda t: t.replace("### 4.2.1", "##### 4.2.1"), "contract"),
    ],
)
def test_bad_drafts_rejected_and_l3_untouched(kb, mutate, check):
    before = _raw_path(kb).read_bytes()
    manifest_before = (kb / "doc" / "_manifest.yaml").read_bytes()
    _draft(kb, "x1", mutate(FIXED_42))

    [r] = _apply(kb)

    assert r.status == "rejected" and r.reason.startswith(f"{check}: "), r.reason
    assert _raw_path(kb).read_bytes() == before
    assert (kb / "doc" / "_manifest.yaml").read_bytes() == manifest_before
    assert _draft_path(kb, "x1").exists()
    assert fixrecord.load(kb / "doc").sections == []


@pytest.mark.parametrize(
    "variant",
    [
        lambda t: t,
        lambda t: t.replace("\n", "\r\n"),
        lambda t: t.replace("\n\n", " \n\n") + "  \n\n",
    ],
)
def test_unchanged_draft_is_noop(kb, variant):
    before = _raw_path(kb).read_bytes()
    record_before = (kb / "doc" / fixrecord.FILE_NAME).read_bytes()
    _draft(kb, "x1", "", raw=variant(BROKEN_42).encode("utf-8"))

    [r] = _apply(kb)

    assert (r.section, r.status, r.new_ids) == ("x1", "unchanged", ())
    assert _raw_path(kb).read_bytes() == before
    assert (kb / "doc" / fixrecord.FILE_NAME).read_bytes() == record_before
    assert not _draft_path(kb, "x1").exists()
    assert [s.id for s in _manifest(kb).sections] == ["4.1", "x1"]


def test_first_apply_without_record_baselines_other_units(kb):
    (kb / "doc" / fixrecord.FILE_NAME).unlink()
    _draft(kb, "x1", FIXED_42)

    assert _apply(kb)[0].status == "applied"

    rec = fixrecord.load(kb / "doc")
    assert rec is not None and set(rec.baseline) == {"4.1"}
    assert fixrecord.blocked_ids(kb, "doc") == [("4.2", fixrecord.AWAITING)]


def test_chained_fix_records_was(kb):
    _draft(kb, "x1", FIXED_42)
    assert _apply(kb)[0].status == "applied"
    joined = FIXED_42.replace("theo hợp đồng.\n\nNghỉ phép", "theo hợp đồng. Nghỉ phép")
    _draft(kb, "4.2", joined)

    [r] = _apply(kb)

    assert r.status == "applied", r.reason
    rec = fixrecord.load(kb / "doc")
    assert rec is not None and [e.id for e in rec.sections] == ["4.2"]
    assert rec.sections[0].was == "4.2" and "join" in rec.sections[0].changes
    digest = report.current_digests(kb, "doc")["4.2"]
    assert rec.sections[0].l3_sha256 == digest
    assert fixrecord.blocked_ids(kb, "doc") == [("4.2", fixrecord.AWAITING)]


MERGED = (
    "<!-- replaces: 4.1 x1 -->\n"
    f"## 4.1 PHẠM VI ÁP DỤNG\n\n{BODY_41}\n\n"
    f"### 4.2 NGHỈ PHÉP NĂM\n\n{FIXED_BODY.replace('### 4.2.1', '#### 4.2.1')}"
)


def test_merge_with_replaces_header(kb):
    _draft(kb, "merge", MERGED)

    [r] = _apply(kb)

    assert r.status == "applied" and r.new_ids == ("4.1",), r.reason
    assert [s.id for s in _manifest(kb).sections] == ["4.1"]
    rec = fixrecord.load(kb / "doc")
    assert rec is not None
    assert rec.sections[0].was == "4.1,x1" and "merge" in rec.sections[0].changes
    assert rec.baseline == {}
    data = spans.load(_work(kb), "doc")
    assert data is not None
    assert [(u.id, u.page, u.end_page) for u in data.units] == [("4.1", 11, 13)]
    assert report.load(kb / "doc") is None  # x1's fallback entry is gone


def test_split_creates_two_units(kb):
    split = (
        f"## 4.2 NGHỈ PHÉP NĂM\n\n{SENTENCE}\n\nNghỉ phép được tính theo năm dương lịch.\n\n"
        f"## 4.2.1 Số ngày nghỉ\n\n{IMAGE}\n\n{TABLE}\n\n{NOTE}"
    )
    _draft(kb, "x1", split)

    [r] = _apply(kb)

    assert r.status == "applied" and r.new_ids == ("4.2", "4.2.1"), r.reason
    assert [s.id for s in _manifest(kb).sections] == ["4.1", "4.2", "4.2.1"]
    rec = fixrecord.load(kb / "doc")
    assert rec is not None
    assert [(e.id, e.was) for e in rec.sections] == [("4.2", "x1"), ("4.2.1", "x1")]
    assert "split" in rec.sections[0].changes


def test_summarized_file_refused(kb):
    manifest = _manifest(kb)
    manifest.sections[0].status = "summarized"
    models.save_yaml_model(kb / "doc" / "_manifest.yaml", manifest)
    _draft(kb, "x1", FIXED_42)

    [r] = _apply(kb)

    assert r.status == "rejected" and r.reason.startswith("status: "), r.reason
    assert "4.1" in r.reason


def test_id_clash_refused(kb):
    manifest = _manifest(kb)
    manifest.sections.append(models.SectionEntry(id="5.1", title="T", file="ch5"))
    models.save_yaml_model(kb / "doc" / "_manifest.yaml", manifest)
    (kb / "doc" / "ch5.raw.md").write_text("## 5.1 T\n\nbody\n", encoding="utf-8")
    _draft(kb, "x1", FIXED_42.replace("## 4.2 ", "## 5.1 "))

    [r] = _apply(kb, pdf_pages={}, from_image={"x1"})

    assert r.status == "rejected" and r.reason.startswith("ids: "), r.reason
    assert "5.1" in r.reason


def test_unknown_or_unordered_replaces_refused(kb):
    _draft(kb, "nope", FIXED_42)
    _draft(kb, "order", "<!-- replaces: x1 4.1 -->\n" + FIXED_42)

    results = {r.section: r for r in _apply(kb)}

    assert results["nope"].reason == "replaces: no section nope"
    assert results["order"].reason.startswith("replaces: ")


def test_from_image_only_where_allowed(kb):
    _draft(kb, "x1", FIXED_42)

    [r] = _apply(kb, from_image={"x1"})
    assert r.status == "rejected"
    assert r.reason.startswith("words: --from-image not allowed for x1")

    [r] = _apply(kb, pdf_pages={}, from_image={"x1"})
    assert r.status == "applied", r.reason
    rec = fixrecord.load(kb / "doc")
    assert rec is not None and rec.sections[0].verified is False


def test_from_image_multi_unit_needs_every_unit_scanned(kb):
    _draft(kb, "merge", MERGED)
    only_first_scanned = {**PDF_PAGES, 11: ""}

    [r] = _apply(kb, pdf_pages=only_first_scanned, from_image={"4.1"})

    assert r.status == "rejected"
    assert r.reason.startswith("words: --from-image not allowed for x1"), r.reason
    assert [s.id for s in _manifest(kb).sections] == ["4.1", "x1"]

    [r] = _apply(kb, pdf_pages={}, from_image={"4.1"})

    assert r.status == "applied", r.reason
    rec = fixrecord.load(kb / "doc")
    assert rec is not None and rec.sections[0].verified is False


def test_from_image_allowed_by_unverifiable_finding(kb):
    digest = report.current_digests(kb, "doc")["x1"]
    report.save(
        kb / "doc",
        L3Check(
            checked_at="t",
            sections=[
                SectionCheck(
                    id="x1",
                    l3_sha256=digest,
                    findings=[Finding(kind="unverifiable", page=12)],
                )
            ],
        ),
    )
    _draft(kb, "x1", FIXED_42)

    [r] = _apply(kb, from_image={"x1"})  # the text layer looks usable

    assert r.status == "applied", r.reason
    rec = fixrecord.load(kb / "doc")
    assert rec is not None and rec.sections[0].verified is False


@pytest.mark.parametrize("record", [True, False])
@pytest.mark.parametrize("failing", ["_write_spans", "raw"])
def test_crash_after_check_leaves_gate_shut(kb, monkeypatch, failing, record):
    if not record:
        (kb / "doc" / fixrecord.FILE_NAME).unlink()
        (kb / "doc" / report.FILE_NAME).unlink()  # nothing else gates the doc
    _draft(kb, "x1", FIXED_42)
    if failing == "_write_spans":
        monkeypatch.setattr(fix, "_write_spans", _boom)
    else:
        real = fix._atomic
        monkeypatch.setattr(
            fix,
            "_atomic",
            lambda path, text: (
                _boom() if path.name.endswith(".raw.md") else real(path, text)
            ),
        )

    with pytest.raises(RuntimeError, match="disk full"):
        _apply(kb)

    assert report.blocked_docs(kb)  # AI text or not, a human must look
    assert _draft_path(kb, "x1").exists()


def _boom(*_a, **_k):
    raise RuntimeError("disk full")


def test_l3check_rerun_on_new_unit(kb):
    _draft(kb, "x1", FIXED_42)
    assert _apply(kb)[0].status == "applied"
    assert report.load(kb / "doc") is None  # x1 gone, nothing found on 4.2


def test_l3check_flags_new_unit_without_text_layer(kb):
    _draft(kb, "x1", FIXED_42)

    [r] = _apply(kb, pdf_pages={12: "", 13: ""}, from_image={"x1"})

    assert r.status == "applied", r.reason
    check = report.load(kb / "doc")
    assert check is not None
    assert [(s.id, [f.kind for f in s.findings]) for s in check.sections] == [
        ("4.2", ["unverifiable"])
    ]
    assert check.sections[0].l3_sha256 == report.current_digests(kb, "doc")["4.2"]


def test_l2_rebuild_matches_scaffold(kb, tmp_path):
    _draft(kb, "x1", FIXED_42)
    assert _apply(kb)[0].status == "applied"
    other = tmp_path / "ref" / ".kb"
    fixed = [
        SectionUnit("4.1", "PHẠM VI ÁP DỤNG", "4", BODY_41, []),
        SectionUnit(
            "4.2", "NGHỈ PHÉP NĂM", "4", FIXED_BODY, extract_tables(FIXED_BODY)
        ),
    ]
    scaffold_doc(
        fixed,
        doc_id="doc",
        title="Doc",
        tags=[],
        revision="1",
        source_path=None,
        kb_dir=other,
    )

    for suffix in (".md", ".raw.md"):
        mine = _read(kb / "doc" / f"{_stem(kb)}{suffix}")
        assert mine == _read(other / "doc" / f"{_stem(kb)}{suffix}")
    ref = models.load_yaml_model(other / "doc" / "_manifest.yaml", models.Manifest)
    assert [(s.id, s.title, s.file, s.tokens.l3) for s in _manifest(kb).sections] == [
        (s.id, s.title, s.file, s.tokens.l3) for s in ref.sections
    ]
    assert "Figure: Sơ đồ phê duyệt" in _read(kb / "doc" / f"{_stem(kb)}.md")


def test_load_drafts_header_and_normalisation(kb):
    _draft(kb, "b", "", raw=b"<!-- replaces: 4.1 x1 -->\r\n## 4.1 A  \r\n\r\nx  \r\n")
    _draft(kb, "a", "## 4.1 A\n")

    drafts = fix.load_drafts(_work(kb), "doc", None)

    assert [(d.name, d.replaces) for d in drafts] == [
        ("a", ["a"]),
        ("b", ["4.1", "x1"]),
    ]
    assert drafts[1].text == "## 4.1 A\n\nx"
    assert [d.name for d in fix.load_drafts(_work(kb), "doc", {"b"})] == ["b"]
    assert fix.load_drafts(_work(kb), "other", None) == []


# --- CLI ---


def _cli(kb, *args, extra=()):
    return runner.invoke(
        app,
        [
            "l3",
            "fix",
            *args,
            "doc",
            "--kb-dir",
            str(kb),
            "--work-dir",
            str(_work(kb)),
            *extra,
        ],
    )


def _apply_args(kb, assistant="cursor"):
    return ("--pdf", str(kb.parent / "doc.pdf"), "--assistant", assistant)


def test_cli_refuses_when_switch_off(tmp_path):
    kb = _build(tmp_path, switch=False)
    _draft(kb, "x1", FIXED_42)

    result = _cli(kb, "apply", extra=_apply_args(kb))

    assert result.exit_code == 1
    assert "L3 fix is off — run: kb l3 fix on" in result.output
    assert _draft_path(kb, "x1").exists()


def test_cli_refuses_wrong_pdf(kb, tmp_path, monkeypatch):
    other = tmp_path / "other.pdf"
    other.write_bytes(b"%PDF-another")
    _draft(kb, "x1", FIXED_42)
    monkeypatch.setattr(
        fix, "load_drafts", lambda *a, **k: pytest.fail("drafts read before sha check")
    )

    result = _cli(kb, "apply", extra=("--pdf", str(other), "--assistant", "cursor"))

    assert result.exit_code == 1
    assert f"{other} is not the PDF doc was ingested from" in result.output.replace(
        "\n", ""
    )
    assert _draft_path(kb, "x1").exists()


def test_cli_refuses_missing_sections_json(kb):
    (_work(kb) / "doc" / spans.FILE_NAME).unlink()

    result = _cli(kb, "apply", extra=_apply_args(kb))

    assert result.exit_code == 1 and "no sections.json for doc" in result.output


def test_cli_no_drafts_exits_0(kb):
    result = _cli(kb, "apply", extra=_apply_args(kb))

    assert result.exit_code == 0
    assert f"no drafts in {_work(kb) / 'doc' / fix.DRAFT_DIR}" in result.output.replace(
        "\n", ""
    )


def test_cli_apply_output_and_exit(kb, monkeypatch):
    monkeypatch.setattr(
        lint, "load_pdf_context", lambda pdf, work, doc: (PDF_PAGES, FURNITURE)
    )
    _draft(kb, "x1", FIXED_42)
    _draft(kb, "4.1", f"## 4.1 PHẠM VI ÁP DỤNG\n\n{BODY_41}\n")

    ok = _cli(kb, "apply", extra=_apply_args(kb, "claude-code"))

    assert ok.exit_code == 0, ok.output
    assert "§4.1 unchanged" in ok.output and "§x1 applied → 4.2" in ok.output
    rec = fixrecord.load(kb / "doc")
    assert rec is not None and rec.sections[0].by == "claude-code"

    _draft(kb, "4.2", FIXED_42.replace("12 ngày", "13 ngày", 1))
    bad = _cli(kb, "apply", extra=(*_apply_args(kb), "--section", "4.2"))

    assert bad.exit_code == 1
    assert "§4.2 rejected: tables: " in bad.output


def test_cli_section_filter(kb, monkeypatch):
    monkeypatch.setattr(
        lint, "load_pdf_context", lambda pdf, work, doc: (PDF_PAGES, FURNITURE)
    )
    _draft(kb, "x1", FIXED_42)
    _draft(kb, "4.1", f"## 4.1 PHẠM VI ÁP DỤNG\n\n{BODY_41}\n")

    result = _cli(kb, "apply", extra=(*_apply_args(kb), "--section", "4.1"))

    assert result.exit_code == 0 and "§x1" not in result.output
    assert _draft_path(kb, "x1").exists()


def test_cli_pages_prints_paths(kb, monkeypatch, tmp_path):
    seen = {}

    def fake(pdf, work_dir, doc_id, pages):
        seen["args"] = (pdf, doc_id, pages)
        return [work_dir / doc_id / "pages" / f"p{p}.png" for p in pages]

    monkeypatch.setattr(fix, "render_pages", fake)

    result = runner.invoke(
        app,
        [
            "l3", "fix", "pages", "doc",
            "--pdf", str(kb.parent / "doc.pdf"),
            "--page", "12", "--page", "13",
            "--work-dir", str(_work(kb)),
        ],
    )  # fmt: skip

    assert result.exit_code == 0, result.output
    assert seen["args"][2] == [12, 13]
    assert [Path(line).name for line in result.output.split()] == ["p12.png", "p13.png"]


def test_render_pages_writes_png(tmp_path):
    pytest.importorskip("pypdfium2")
    pdf = Path(__file__).parent / "fixtures" / "mono-diagram.pdf"

    [png] = fix.render_pages(pdf, tmp_path, "doc", [1])

    assert png == tmp_path / "doc" / "pages" / "p1.png"
    assert png.is_file() and png.read_bytes()[:4] == b"\x89PNG"
