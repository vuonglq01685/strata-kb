"""Tiered judgement of a ticket whose `Grounded on: … @ <rev>` differs from
the current -code manifest revision (`kb ticket check`).

A moved revision alone never fails: the fact checks decide. A failed fact
check means the grounding no longer holds (Tier 2, error). Otherwise the
cited names still hold (Tier 1): the cited sections are diffed against the
baseline at the grounded revision, and changed ones are shown as a warning.

Pure: the caller (`ticketcheck.check`) supplies the baseline refs and the
current section text. Must not import `ticketcheck` or `ticketstale`.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable

from strata_kb.doctor import Issue
from strata_kb.resolve import ResolvedRef

# Issue.code of decision-type errors (ticketcheck.DECISION): not drift.
DECISION_CODE = "decision"
# Issue.code of a warning for a fact check that could not run.
UNVERIFIED_CODE = "unverified"
DIFF_CAP = 40


def section_diff(
    doc_id: str, sid: str, old: str, new: str, before: str, after: str
) -> str:
    lines = list(
        difflib.unified_diff(
            before.strip().splitlines(),
            after.strip().splitlines(),
            fromfile=f"{doc_id} §{sid} @{old}",
            tofile=f"{doc_id} §{sid} @{new}",
            lineterm="",
        )
    )
    if len(lines) > DIFF_CAP:
        rest = len(lines) - DIFF_CAP
        lines = [*lines[:DIFF_CAP], f"… ({rest} more lines)"]
    return "\n".join(lines)


def judge(
    doc_id: str,
    old: str,
    new: str,
    drift: list[ResolvedRef] | None,
    current_section: Callable[[str], str | None],
    fact_issues: list[Issue],
    local_fallback: bool,
    skipped: bool,
) -> tuple[list[Issue], list[str]]:
    """`(issues, notes)` to append for a ticket grounded @`old` while the
    document is @`new`. `fact_issues` are those the fact checks just raised;
    `skipped` = some fact check could not run (ticketcheck.UNVERIFIED)."""
    if any(i.level == "error" and i.code != DECISION_CODE for i in fact_issues):
        notes = (
            [
                "checked against the local -code (hub unreachable) — your "
                "branch's own changes may cause this; re-run with the hub "
                "before sending it back"
            ]
            if local_fallback
            else []
        )
        error = Issue(
            "error",
            f"grounding drifted since @{old} (now @{new}) and no longer holds "
            "— re-run /sa-ticket-ground",
        )
        return [error], notes

    issues: list[Issue] = []
    notes = []
    if drift is None:
        issues.append(
            Issue(
                "warning",
                f"grounded @{old}, now @{new} — no baseline to diff, cited "
                "facts still hold",
            )
        )
    else:
        for r in drift:
            if r.status == "ok":
                continue
            sid = r.ref.section_id
            diff = section_diff(
                doc_id, sid, old, new, r.content, current_section(sid) or ""
            )
            issues.append(
                Issue(
                    "warning",
                    f"grounded @{old}, now @{new} — §{sid} changed; cited "
                    f"names still hold, review the diff:\n{diff}",
                )
            )
        if not issues:
            what = (
                "cited facts that could be checked still hold"
                if skipped
                else "cited sections unchanged"
            )
            notes.append(f"grounded @{old}, still valid at @{new} — {what}")
    if skipped:
        issues.append(
            Issue(
                "warning",
                f"some cited facts could not be verified since @{old} (see "
                "warnings above) — check them by hand",
            )
        )
    return issues, notes
