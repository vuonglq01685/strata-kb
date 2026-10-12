"""Which open `kb-code-sync` issue is the hub job's work order (spec §6).

Issue text is never trusted. An issue counts only when its first line is the
job's identity marker and its last line a digest marker. Nothing is taken from
it to drive a scan: the baseline is always the one recorded in git
(`baseline.resolve`), and the issue is `current` only when its own baseline and
findings digest both agree with a local scan from that recorded baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from strata_kb import gitio
from strata_kb.codesync import baseline as baseline_mod
from strata_kb.codesync import scan

Kind = Literal["current", "stale", "foreign", "duplicate"]
USABLE: tuple[Kind, ...] = ("current", "stale")


@dataclass(frozen=True)
class IssueVerdict:
    """`baseline_sha` is the RECORDED baseline a usable issue is scanned from
    (None for other kinds, or when none is recorded); `issue_baseline_sha` is
    what the issue's own marker says, for information only."""

    number: int
    url: str
    created_at: str
    kind: Kind
    reason: str
    scan_sha: str | None
    baseline_sha: str | None
    issue_baseline_sha: str | None = None


def _verdict(
    issue: dict,
    kind: Kind,
    reason: str,
    scan_sha: str | None = None,
    baseline_sha: str | None = None,
    issue_baseline_sha: str | None = None,
) -> IssueVerdict:
    return IssueVerdict(
        issue["number"],
        issue.get("url") or "",
        issue.get("createdAt") or "",
        kind,
        reason,
        scan_sha,
        baseline_sha,
        issue_baseline_sha,
    )


def _parse(root: Path, tip: str, issue: dict) -> tuple[str, str, str] | str:
    """`(scan sha, baseline sha, digest)` of a job-written body, else the
    reason it is foreign. `tip` is the default branch's tip."""
    body = issue.get("body") or ""
    marker = scan.body_marker(body)
    if marker is None:
        return "no work-order marker"
    scan_sha, baseline = marker
    if baseline is None:
        return "work order has no baseline"
    if not gitio.rev_exists(root, baseline):
        return f"baseline {baseline[:12]} is not in this hub's history"
    if not gitio.is_ancestor(root, baseline, tip):
        return f"baseline {baseline[:12]} is not in the default branch's history"
    m = scan.DIGEST_RE.fullmatch(body.rstrip().splitlines()[-1].strip())
    if m is None:
        return "no digest marker"
    return scan_sha, baseline, m.group(1)


def _judge(
    root: Path, issue: dict, scan_sha: str, issue_base: str, digest: str
) -> IssueVerdict:
    local = scan.run_scan(root)
    recorded = local.baseline_sha
    args = (scan_sha, recorded, issue_base)
    if recorded is None:
        reason = "no recorded baseline — run kb code-sync baseline"
        return _verdict(issue, "stale", reason, *args)
    if gitio.resolve_commit(root, issue_base) != recorded:
        reason = f"issue baseline {issue_base[:12]} differs from the recorded {recorded[:12]}"
        return _verdict(issue, "stale", reason, *args)
    if scan.digest(local) != digest:
        return _verdict(issue, "stale", "findings differ from the local scan", *args)
    return _verdict(issue, "current", "matches the local scan", *args)


def classify(root: Path, issues: list[dict]) -> list[IssueVerdict]:
    """One verdict per issue (dicts with number, url, createdAt, body), by
    number. Only the newest valid work order is compared with a local scan."""
    out: list[IssueVerdict] = []
    valid: list[tuple[dict, str, str, str]] = []
    tip = baseline_mod.scan_ref(root) if issues else ""
    for issue in issues:
        parsed = _parse(root, tip, issue)
        if isinstance(parsed, str):
            out.append(_verdict(issue, "foreign", parsed))
        else:
            valid.append((issue, *parsed))
    valid.sort(key=lambda v: (v[0].get("createdAt") or "", v[0]["number"]))
    if valid:
        newest, scan_sha, base, digest = valid.pop()
        for issue, old_scan, old_base, _ in valid:
            reason = f"older than #{newest['number']}"
            out.append(_verdict(issue, "duplicate", reason, old_scan, None, old_base))
        out.append(_judge(root, newest, scan_sha, base, digest))
    return sorted(out, key=lambda v: v.number)
