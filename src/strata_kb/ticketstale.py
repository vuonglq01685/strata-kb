"""Scan every ticket and mission for citations the hub has moved since they
were pinned.

`kb ticket lint` checks citations when a PR touches a ticket. A ticket that
merged last month is never looked at again, though the hub keeps
publishing. `kb ticket stale` walks them all, and `kb-doctor.yml` runs it on
a schedule and keeps one issue up to date.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb import gitio, kbcontext
from strata_kb.resolve import resolve_refs

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle

DEFAULT_DIRS = ("tickets", "missions")


@dataclass
class StaleRef:
    citation: str
    status: str  # "stale" | "broken"
    reason: str


@dataclass
class StaleFile:
    path: str
    refs: list[StaleRef] = field(default_factory=list)


def _files(paths: Iterable[Path]) -> list[Path]:
    found: set[Path] = set()
    for path in paths:
        if path.is_dir():
            found.update(p for p in path.rglob("*.md") if p.is_file())
        elif path.is_file():
            found.add(path)
    return sorted(found)


def scan(paths: Iterable[Path], hub: HubHandle) -> list[StaleFile]:
    """Files whose kb-context block cites something stale or broken.

    A file without a block, or whose block does not parse, is skipped:
    `kb ticket lint` is the gate that reports those, and a scheduled sweep
    that failed on a half-written draft would hide every real finding."""
    findings: list[StaleFile] = []
    for path in _files(paths):
        try:
            text = path.read_text(encoding="utf-8")
            ctx = kbcontext.parse(text)
        except (OSError, UnicodeDecodeError, kbcontext.KBContextError):
            continue
        try:
            results = resolve_refs(hub, ctx)
        except gitio.GitError as exc:
            findings.append(
                StaleFile(path.as_posix(), [StaleRef(ctx.version, "broken", str(exc))])
            )
            continue
        refs = [
            StaleRef(r.citation, r.status, r.reason)
            for r in results
            if r.status in ("stale", "broken")
        ]
        if refs:
            findings.append(StaleFile(path.as_posix(), refs))
    return findings


def exit_code(findings: list[StaleFile]) -> int:
    """0 when everything is current, 2 when only staleness was found (as
    `kb resolve` does), 1 when any citation is broken."""
    statuses = {ref.status for f in findings for ref in f.refs}
    if "broken" in statuses:
        return 1
    return 2 if statuses else 0


def render_markdown(findings: list[StaleFile]) -> str:
    """The issue body `kb-doctor.yml` keeps up to date."""
    if not findings:
        return "Every ticket and mission cites current hub content.\n"
    total = sum(len(f.refs) for f in findings)
    lines = [
        f"{total} citation(s) in {len(findings)} file(s) no longer match the hub.",
        "",
        "A **stale** citation still resolves, but the cited content changed after "
        "it was pinned: review the amendment (`kb diff <doc> --against <pin>`), "
        "then re-pin with `kb context new`. A **broken** one no longer resolves.",
        "",
        "| File | Citation | Status | Reason |",
        "| --- | --- | --- | --- |",
    ]
    for f in findings:
        for ref in f.refs:
            reason = ref.reason.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{f.path}` | {ref.citation} | {ref.status} | {reason} |")
    return "\n".join(lines) + "\n"


def to_json(findings: list[StaleFile]) -> list[dict]:
    return [{"path": f.path, "refs": [vars(ref) for ref in f.refs]} for f in findings]
