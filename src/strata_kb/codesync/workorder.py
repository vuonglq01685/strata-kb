"""Which open `kb-code-sync` issue is the hub job's work order (spec §6).

Issue text is never trusted: an issue counts only when its first line is the
job's identity marker and its last line a digest marker. The one value taken
from it is the baseline sha (validated hex, present in the hub's history); the
work order itself is always recomputed locally and compared by digest.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from strata_kb import gitio
from strata_kb.codesync import scan

Kind = Literal["current", "stale", "foreign", "duplicate"]
USABLE: tuple[Kind, ...] = ("current", "stale")


@dataclass(frozen=True)
class IssueVerdict:
    number: int
    url: str
    created_at: str
    kind: Kind
    reason: str
    scan_sha: str | None
    baseline_sha: str | None


def _verdict(
    issue: dict,
    kind: Kind,
    reason: str,
    scan_sha: str | None = None,
    baseline_sha: str | None = None,
) -> IssueVerdict:
    return IssueVerdict(
        issue["number"],
        issue.get("url") or "",
        issue.get("createdAt") or "",
        kind,
        reason,
        scan_sha,
        baseline_sha,
    )


def _parse(root: Path, issue: dict) -> tuple[str, str, str] | str:
    """`(scan sha, baseline sha, digest)` of a job-written body, else the
    reason it is foreign."""
    lines = (issue.get("body") or "").strip().splitlines()
    marker = scan.parse_work_order_marker(lines[0]) if lines else None
    if marker is None:
        return "no work-order marker"
    scan_sha, baseline = marker
    if baseline is None:
        return "work order has no baseline"
    if not gitio.rev_exists(root, baseline):
        return f"baseline {baseline[:12]} is not in this hub's history"
    m = scan.DIGEST_RE.fullmatch(lines[-1].strip())
    if m is None:
        return "no digest marker"
    return scan_sha, baseline, m.group(1)


def classify(root: Path, issues: list[dict]) -> list[IssueVerdict]:
    """One verdict per issue (dicts with number, url, createdAt, body), by
    number. Only the newest valid work order is checked against a local scan."""
    out: list[IssueVerdict] = []
    valid: list[tuple[dict, str, str, str]] = []
    for issue in issues:
        parsed = _parse(root, issue)
        if isinstance(parsed, str):
            out.append(_verdict(issue, "foreign", parsed))
        else:
            valid.append((issue, *parsed))
    valid.sort(key=lambda v: (v[0].get("createdAt") or "", v[0]["number"]))
    if valid:
        newest, scan_sha, baseline, digest = valid.pop()
        for issue, old_scan, old_base, _ in valid:
            reason = f"older than #{newest['number']}"
            out.append(_verdict(issue, "duplicate", reason, old_scan, old_base))
        local = scan.run_scan(root, baseline_sha=baseline)
        if scan.digest(local) == digest:
            out.append(
                _verdict(
                    newest, "current", "matches the local scan", scan_sha, baseline
                )
            )
        else:
            reason = "code moved since the job ran; the local scan is newer"
            out.append(_verdict(newest, "stale", reason, scan_sha, baseline))
    return sorted(out, key=lambda v: v.number)
