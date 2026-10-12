from __future__ import annotations

import pytest

from strata_kb.codesync import scan, workorder
from tests.test_codesync_changes import SCAN_SECTIONS, _db, commit, write_doc
from tests.test_codesync_scan import NO_LEDGER


def _issue(number: int, body: str | None, created: str = "2026-10-11T08:00:00Z"):
    return {
        "number": number,
        "url": f"https://github.com/o/hub/issues/{number}",
        "createdAt": created,
        "body": body,
    }


def _order(root, baseline: str) -> str:
    return scan.render_markdown(scan.run_scan(root, baseline_sha=baseline))


@pytest.fixture
def job_issue(code_sync_hub, run_git):
    """`(root, c1, body)`: the hub moved after c1, and the job wrote `body`."""
    root, c1 = code_sync_hub
    write_doc(root, "acme", "code", NO_LEDGER)
    commit(root, run_git)
    return root, c1, _order(root, c1)


def test_matching_digest_is_current(job_issue):
    root, c1, body = job_issue

    [v] = workorder.classify(root, [_issue(7, body)])

    assert (v.number, v.kind, v.baseline_sha) == (7, "current", c1)
    assert v.scan_sha == scan.run_scan(root, baseline_sha=c1).scan_sha
    assert v.url == "https://github.com/o/hub/issues/7"
    assert v.created_at == "2026-10-11T08:00:00Z"


def test_code_moved_after_the_job_ran_is_stale(job_issue, run_git):
    root, c1, body = job_issue
    sections = {**NO_LEDGER, "db.payments": ("payments", _db("amount", "refund_id"))}
    write_doc(root, "acme", "code", sections)
    commit(root, run_git)

    [v] = workorder.classify(root, [_issue(7, body)])

    assert (v.kind, v.baseline_sha) == ("stale", c1)
    assert "local scan is newer" in v.reason


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
        (
            lambda body: body.split("\n", 1)[1],
            "no work-order marker",
        ),
        (
            lambda body: "\n".join(body.splitlines()[:-2]) + "\n",
            "digest",
        ),
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


def test_two_valid_issues_keep_the_newest(job_issue):
    root, _, body = job_issue
    old = _issue(4, body, "2026-10-10T08:00:00Z")
    new = _issue(9, body, "2026-10-11T08:00:00Z")

    verdicts = workorder.classify(root, [new, old])

    assert [(v.number, v.kind) for v in verdicts] == [(4, "duplicate"), (9, "current")]
    assert verdicts[0].reason == "older than #9"


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
    assert SCAN_SECTIONS  # fixture module import guard
