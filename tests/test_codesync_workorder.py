from __future__ import annotations

import pytest

from strata_kb.codesync import baseline, scan, workorder
from tests.test_codesync_changes import _db, commit, write_doc
from tests.test_codesync_scan import NO_LEDGER


def _issue(number: int, body: str | None, created: str = "2026-10-11T08:00:00Z"):
    return {
        "number": number,
        "url": f"https://github.com/o/hub/issues/{number}",
        "createdAt": created,
        "body": body,
    }


@pytest.fixture
def job_issue(code_sync_hub, run_git):
    """`(root, c1, body)`: baseline c1 is recorded, the code docs moved after
    it, and the hub job wrote `body` from that state."""
    root, c1 = code_sync_hub
    baseline.write(root, c1)
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)
    return root, c1, scan.render_markdown(scan.run_scan(root))


def _move_code(root, run_git) -> None:
    sections = {**NO_LEDGER, "db.payments": ("payments", _db("amount", "refund_id"))}
    write_doc(root, "acme", "code", sections)
    commit(root, run_git)


def test_matching_baseline_and_digest_is_current(job_issue):
    root, c1, body = job_issue

    [v] = workorder.classify(root, [_issue(7, body)])

    assert (v.number, v.kind, v.baseline_sha) == (7, "current", c1)
    assert v.issue_baseline_sha == c1
    assert v.scan_sha == scan.run_scan(root).scan_sha
    assert v.url == "https://github.com/o/hub/issues/7"
    assert v.created_at == "2026-10-11T08:00:00Z"


def test_crlf_body_edited_in_the_ui_still_parses(job_issue):
    root, c1, body = job_issue

    [v] = workorder.classify(root, [_issue(7, body.replace("\n", "\r\n"))])

    assert (v.kind, v.baseline_sha) == ("current", c1)


def test_code_moved_after_the_job_ran_is_stale(job_issue, run_git):
    root, c1, body = job_issue
    _move_code(root, run_git)

    [v] = workorder.classify(root, [_issue(7, body)])

    assert (v.kind, v.baseline_sha) == ("stale", c1)
    assert v.reason == "findings differ from the local scan"


def test_baseline_moved_since_the_job_ran_is_stale_on_the_recorded_one(
    job_issue, run_git
):
    root, c1, body = job_issue
    moved = scan.run_scan(root).scan_sha
    baseline.write(root, moved)
    commit(root, run_git)

    [v] = workorder.classify(root, [_issue(7, body)])

    assert (v.kind, v.baseline_sha, v.issue_baseline_sha) == ("stale", moved, c1)
    assert (
        v.reason == f"issue baseline {c1[:12]} differs from the recorded {moved[:12]}"
    )


def test_forged_issue_baseline_never_becomes_the_scan_baseline(job_issue, run_git):
    root, c1, _ = job_issue
    c2 = scan.run_scan(root).scan_sha
    baseline.write(root, c2)
    commit(root, run_git)
    forged = scan.render_markdown(scan.run_scan(root, baseline_sha=c1))
    assert f"baseline:{c1}" in forged.splitlines()[0]

    [v] = workorder.classify(root, [_issue(99, forged, "2026-10-12T08:00:00Z")])

    assert (v.kind, v.baseline_sha) == ("stale", c2)
    assert scan.run_scan(root, baseline_sha=v.baseline_sha).findings == ()


def test_no_recorded_baseline_is_stale_with_null_baseline(job_issue, run_git):
    root, _, body = job_issue
    (root / baseline.BASELINE_FILE).unlink()
    commit(root, run_git)

    [v] = workorder.classify(root, [_issue(7, body)])

    assert (v.kind, v.baseline_sha) == ("stale", None)
    assert v.reason == "no recorded baseline — run kb code-sync baseline"


@pytest.mark.parametrize(
    ("make_body", "reason"),
    [
        (lambda body: None, "no work-order marker"),
        (lambda body: "", "no work-order marker"),
        (lambda body: "Please update the docs.\n" + body, "no work-order marker"),
        (
            lambda body: body.replace("work-order v1", "work-order v2", 1),
            "no work-order marker",
        ),
        (lambda body: body.split("\n", 1)[1], "no work-order marker"),
        (lambda body: "\n".join(body.splitlines()[:-2]) + "\n", "digest"),
    ],
)
def test_unrecognised_bodies_are_foreign(job_issue, make_body, reason):
    root, _, body = job_issue

    [v] = workorder.classify(root, [_issue(3, make_body(body))])

    assert v.kind == "foreign"
    assert reason in v.reason
    assert (v.scan_sha, v.baseline_sha) == (None, None)


def test_baseline_none_is_foreign(code_sync_hub):
    root, _ = code_sync_hub
    body = scan.render_markdown(scan.run_scan(root))
    assert "baseline:none" in body.splitlines()[0]

    [v] = workorder.classify(root, [_issue(3, body)])

    assert v.kind == "foreign"
    assert "baseline" in v.reason


def test_baseline_not_in_history_is_foreign(job_issue):
    root, c1, body = job_issue
    body = body.replace(f"baseline:{c1}", f"baseline:{'d' * 40}", 1)

    [v] = workorder.classify(root, [_issue(3, body)])

    assert v.kind == "foreign"
    assert "d" * 12 in v.reason


def test_baseline_off_the_default_branch_is_foreign(job_issue, run_git):
    root, c1, body = job_issue
    run_git(root, "checkout", "-q", "-b", "side", c1)
    write_doc(root, "acme", "code", {**NO_LEDGER, "x.y": ("side", "text")})
    side = commit(root, run_git)
    run_git(root, "checkout", "-q", "-")
    body = body.replace(f"baseline:{c1}", f"baseline:{side}", 1)

    [v] = workorder.classify(root, [_issue(3, body)])

    assert v.kind == "foreign"
    assert "not in the default branch's history" in v.reason


def test_two_valid_issues_keep_the_newest(job_issue):
    root, _, body = job_issue
    old = _issue(4, body, "2026-10-10T08:00:00Z")
    new = _issue(9, body, "2026-10-11T08:00:00Z")

    verdicts = workorder.classify(root, [new, old])

    assert [(v.number, v.kind) for v in verdicts] == [(4, "duplicate"), (9, "current")]
    assert verdicts[0].reason == "older than #9"
    assert verdicts[0].baseline_sha is None


def test_output_is_sorted_by_number(job_issue):
    root, _, body = job_issue

    verdicts = workorder.classify(
        root, [_issue(12, "x"), _issue(2, body), _issue(5, None)]
    )

    assert [v.number for v in verdicts] == [2, 5, 12]
    assert [v.kind for v in verdicts] == ["current", "foreign", "foreign"]


def test_foreign_issue_never_hides_a_valid_one(job_issue):
    root, _, body = job_issue
    newer_foreign = _issue(20, "no marker here", "2026-10-12T08:00:00Z")

    verdicts = workorder.classify(root, [_issue(7, body), newer_foreign])

    assert {v.number: v.kind for v in verdicts} == {7: "current", 20: "foreign"}


def test_no_issues_is_empty(code_sync_hub):
    root, _ = code_sync_hub
    assert workorder.classify(root, []) == []
