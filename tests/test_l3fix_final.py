"""Final whole-branch review fixes: apply cannot launder, summarize gate, links."""

from __future__ import annotations

import pytest

from strata_kb.l3check import fixrecord, report
from tests.test_l3fix_apply import (
    FIXED_42,
    IMAGE,
    NOTE,
    _apply,
    _build,
    _draft,
    _raw_path,
    _read,
)

KB_BODY = "được nghỉ phép năm"
HAND = "không được nghỉ phép năm"


@pytest.fixture
def kb(tmp_path):
    return _build(tmp_path)


def test_apply_refuses_unit_edited_outside_apply(kb):
    raw = _raw_path(kb)
    raw.write_text(_read(raw).replace(KB_BODY, HAND), encoding="utf-8")
    assert fixrecord.blocked_ids(kb, "doc") == [("x1", fixrecord.EDITED)]
    _draft(kb, "x1", FIXED_42.replace(KB_BODY, HAND))

    [r] = _apply(kb)

    assert r.status == "rejected"
    assert r.reason == (
        "status: §x1 was edited outside kb l3 fix apply "
        "— run kb l3 confirm or restore it first"
    )
    assert fixrecord.blocked_ids(kb, "doc") == [("x1", fixrecord.EDITED)]


def test_unverified_flag_survives_a_chained_fix(kb):
    bad = FIXED_42.replace(KB_BODY, HAND)
    _draft(kb, "x1", bad)
    assert _apply(kb, pdf_pages={}, from_image={"x1"})[0].status == "applied"
    assert [e.verified for e in fixrecord.load(kb / "doc").sections] == [False]
    joined = bad.replace("theo hợp đồng.\n\nNghỉ phép", "theo hợp đồng. Nghỉ phép")
    _draft(kb, "4.2", joined)

    [r] = _apply(kb)

    assert r.status == "applied", r.reason
    rec = fixrecord.load(kb / "doc")
    assert [(e.id, e.verified) for e in rec.sections] == [("4.2", False)]


def test_confirmed_unverified_entry_does_not_taint_the_next_fix(kb):
    bad = FIXED_42.replace(KB_BODY, HAND)
    _draft(kb, "x1", bad)
    _apply(kb, pdf_pages={}, from_image={"x1"})
    rec = fixrecord.load(kb / "doc")
    fixrecord.confirm(kb / "doc", ["4.2"], "human", "t", report.current_digests(kb, "doc"))
    assert fixrecord.blocked_ids(kb, "doc") == []
    _draft(kb, "4.2", bad.replace("theo hợp đồng.\n\nNghỉ phép", "theo hợp đồng. Nghỉ phép"))

    [r] = _apply(kb, pdf_pages={}, from_image={"4.2"})

    assert r.status == "applied", r.reason
    assert report.blocked_docs(kb) == [("doc", ["4.2"])]
