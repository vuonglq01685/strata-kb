"""`kb ticket lint` for bug and hotfix tickets.

`ticketlint.lint` dispatches here when the ticket carries `> Type: bug` or
`> Type: hotfix`; the CLI and MCP wrappers need no change. Heading, fill,
context, revision and DoR checks are `lintcore` / `planrev` /
`ticketlint` primitives; this module holds what is specific to the bug
contract (docs/superpowers/specs/2026-10-14-bug-hotfix-ticket-design.md).

`attachment_images` and `image_problems` are public: `kb ticket publish`
validates the same images before copying them.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb import lintcore, mdmask, planrev, ticket
from strata_kb.doctor import Issue
from strata_kb.lintcore import LintReport

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle

ATTACHMENTS_HEADING = "## Attachments"

# Sections with a stronger check of their own.
_FILL_EXEMPT: frozenset[str] = frozenset(
    {ATTACHMENTS_HEADING, lintcore.DOR_HEADING, "## Steps to reproduce"}
)

# Same id rule as planstatus.safe_name (it becomes a path segment).
# Duplicated: importing planstatus would drag the whole plan stack in.
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)[^)]*\)")
_NA_REASON_RE = re.compile(r"^[ \t]*n/?a[ \t]*[—–-][ \t]*\S", re.I | re.M)
_NUMBERED_RE = re.compile(r"^[ \t]*\d+[.)][ \t]+\S", re.M)
_URL_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.I)
_DRIVE_RE = re.compile(r"^[A-Za-z]:")

# shortcut: PNG/WebP only (the hub's asset convention); widen
# assetstore._ASSET_NAME_RE and the content types when a BA needs JPEG.
_IMAGE_SUFFIXES = (".png", ".webp")


def attachment_images(text: str) -> list[str]:
    """Raw `src` of every markdown image in `## Attachments`, in order."""
    body = lintcore.section_body(text, ATTACHMENTS_HEADING)
    if body is None:
        return []
    return _IMAGE_RE.findall(mdmask._visible_text(body))


def image_problems(src: str, stem: str | None, base_dir: Path | None) -> list[str]:
    """Why `src` is not an acceptable attachment ([] when it is). `stem` is
    the bug's id (its folder name); None skips the folder check. `base_dir`
    is the ticket's directory; None skips the existence check."""
    if _URL_RE.match(src):
        return [
            f"image '{src}' is an external URL — save it as PNG into the bug's folder"
        ]
    if src.startswith(("/", "\\")) or _DRIVE_RE.match(src):
        return [
            f"image '{src}' is an absolute path — use a path relative to the ticket"
        ]
    if ".." in re.split(r"[/\\]", src):
        return [f"image '{src}' contains '..' — keep it inside the bug's own folder"]
    problems: list[str] = []
    if stem is not None and not src.startswith(f"{stem}/"):
        problems.append(f"image '{src}' is not under '{stem}/' — move it there")
    if not src.lower().endswith(_IMAGE_SUFFIXES):
        problems.append(f"image '{src}' is not PNG or WebP — save it as PNG")
    if not problems and base_dir is not None and not (base_dir / src).is_file():
        problems.append(f"image '{src}' not found next to the ticket")
    return problems


def _check_attachments(
    text: str, stem: str | None, base_dir: Path | None
) -> list[Issue]:
    body = lintcore.section_body(text, ATTACHMENTS_HEADING)
    if body is None:
        return []  # missing heading — check_headings reports it
    images = attachment_images(text)
    if not images and not _NA_REASON_RE.search(mdmask._visible_text(body)):
        return [
            Issue(
                "error",
                f"'{ATTACHMENTS_HEADING}' needs an image "
                "(`![caption](BUG-<n>/<file>.png)`) or 'N/A — <reason>'",
            )
        ]
    return [
        Issue("error", problem)
        for src in images
        for problem in image_problems(src, stem, base_dir)
    ]


def _check_steps(text: str) -> list[Issue]:
    body = lintcore.section_body(text, "## Steps to reproduce")
    if body is None or _NUMBERED_RE.search(mdmask.visible_body(body)):
        return []
    return [
        Issue(
            "error",
            "'## Steps to reproduce' needs a numbered list — at least one '1.' step",
        )
    ]


def _check_headers(text: str) -> list[Issue]:
    visible = mdmask._visible_text(text)
    issues: list[Issue] = []
    sev = ticket.SEVERITY_RE.search(visible)
    if sev is None or sev.group(1) not in ticket.SEVERITIES:
        got = f" (got '{sev.group(1)}')" if sev and sev.group(1) else ""
        issues.append(
            Issue(
                "error",
                "missing or invalid '> Severity:' line — use one of: "
                f"{', '.join(ticket.SEVERITIES)}{got}",
            )
        )
    rel = ticket.RELATED_TICKET_RE.search(visible)
    if rel is not None and rel.group(1) != "none":
        value = rel.group(1)
        if _SAFE_ID_RE.fullmatch(value) is None:
            issues.append(
                Issue(
                    "error",
                    f"'> Related ticket:' must be a ticket id or `none` (got '{value}')",
                )
            )
    if ticket.PARENT_MISSION_LINE_RE.search(visible):
        issues.append(
            Issue(
                "error",
                "a bug links with `> Related ticket:`, not a parent mission",
            )
        )
    return issues


def lint(
    text: str,
    hub: HubHandle | None,
    *,
    path: Path | None = None,
    missions_dir: Path | None = None,
    fail_on_stale: bool = False,
    ticket_id: str | None = None,
    load_mission: Callable[[str], str | None] | None = None,
) -> LintReport:
    # missions_dir / load_mission are accepted for call-compatibility with
    # ticketlint.lint: a bug has no parent mission to resolve.
    del missions_dir, load_mission
    text = unicodedata.normalize("NFC", text)
    stem = path.stem if path is not None else ticket_id
    base_dir = path.parent if path is not None else None
    issues: list[Issue] = []
    issues += lintcore.check_title(text)
    issues += lintcore.check_headings(text, ticket.BUG_REQUIRED_HEADINGS)
    issues += lintcore.check_duplicate_headings(text)
    issues += lintcore.check_required_filled(
        text, ticket.BUG_REQUIRED_HEADINGS, _FILL_EXEMPT
    )
    issues += _check_headers(text)
    issues += _check_steps(text)
    issues += _check_attachments(text, stem, base_dir)
    if lintcore.section_body(text, "## KB context") is not None:
        ctx_issues, _ctx = lintcore.check_context_block(
            text, hub, fail_on_stale=fail_on_stale
        )
        issues += ctx_issues
    issues += lintcore.check_recommended_sections(text, ticket.BUG_RECOMMENDED_HEADINGS)
    issues += lintcore.check_dor_checklist(text)
    issues += planrev.check_revision(text)
    return LintReport(issues=issues)
