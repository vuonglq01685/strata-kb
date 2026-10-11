"""Pure tests for `groundingdrift.judge` / `section_diff`."""

from __future__ import annotations

from strata_kb import groundingdrift
from strata_kb.doctor import Issue
from strata_kb.kbcontext import KBRef
from strata_kb.resolve import ResolvedRef

OLD, NEW = "aaaaaaa", "bbbbbbb"
TIER2 = (
    f"grounding drifted since @{OLD} (now @{NEW}) and no longer holds "
    "— re-run /sa-ticket-ground"
)
UNCHANGED = f"grounded @{OLD}, still valid at @{NEW} — cited sections unchanged"
CHECKABLE = (
    f"grounded @{OLD}, still valid at @{NEW} — cited facts that could be checked "
    "still hold"
)
NO_BASELINE = (
    f"grounded @{OLD}, now @{NEW} — no baseline to diff, cited facts still hold"
)
UNVERIFIED = (
    f"some cited facts could not be verified since @{OLD} (see warnings above) "
    "— check them by hand"
)
LOCAL = (
    "checked against the local -code (hub unreachable) — your branch's own "
    "changes may cause this; re-run with the hub before sending it back"
)


def ref(sid: str, status="ok", content="") -> ResolvedRef:
    return ResolvedRef(
        ref=KBRef(repo_id="demo", doc_id="demo-code", section_id=sid),
        status=status,
        citation=f"demo-code §{sid}",
        content=content,
        tokens=0,
    )


def judge(drift, facts=(), current=None, local=False):
    return groundingdrift.judge(
        "demo-code",
        OLD,
        NEW,
        drift,
        lambda sid: (current or {}).get(sid),
        list(facts),
        local,
    )


def test_tier2_on_fact_error():
    issues, _ = judge([ref("db.orders")], [Issue("error", "unknown id")])
    assert [(i.level, i.message) for i in issues] == [("error", TIER2)]


def test_decision_errors_are_not_drift():
    issues, _ = judge(
        [ref("db.orders")], [Issue("error", "decision D2 is OPEN", code="decision")]
    )
    assert not [i for i in issues if i.level == "error"]


def test_tier1_unchanged_note():
    issues, notes = judge([ref("a"), ref("b")])
    assert issues == []
    assert notes == [UNCHANGED]


def test_tier1_changed_section_warns_with_diff():
    drift = [ref("db.orders", "stale", "| a |\n")]
    issues, notes = judge(drift, current={"db.orders": "| a |\n| b |\n"})
    assert notes == []
    assert len(issues) == 1 and issues[0].level == "warning"
    msg = issues[0].message
    assert "§db.orders changed" in msg
    assert "+| b |" in msg
    assert "demo-code §db.orders @aaaaaaa" in msg


def test_broken_ref_without_fact_error_is_grey_zone():
    issues, _ = judge([ref("db.orders", "broken")])
    assert [i.level for i in issues] == ["warning"]


def test_no_baseline_warns():
    issues, notes = judge(None)
    assert [(i.level, i.message) for i in issues] == [("warning", NO_BASELINE)]
    assert notes == []


def test_skipped_check_adds_unverified_warning():
    issues, notes = judge([ref("a")], [Issue("warning", "could not read x.md")])
    assert notes == [CHECKABLE]
    assert [i.message for i in issues] == [UNVERIFIED]


def test_local_fallback_note_only_on_tier2():
    _, notes = judge([ref("a")], [Issue("error", "x")], local=True)
    assert notes == [LOCAL]
    _, notes = judge([ref("a")], [], local=True)
    assert LOCAL not in notes


def test_diff_capped_at_40_lines():
    before = "\n".join(f"old{i}" for i in range(100))
    after = "\n".join(f"new{i}" for i in range(100))
    diff = groundingdrift.section_diff("demo-code", "s", OLD, NEW, before, after)
    lines = diff.splitlines()
    assert len(lines) == 41
    assert lines[-1].startswith("… (")
