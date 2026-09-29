"""Standard ticket template contract (Phase 4 — BA agent).

Single source of truth for the required-heading list and the User Story
format that `ticketlint.py` enforces. `REQUIRED_HEADINGS` is a
compatibility contract between the BA's local install, the shared MCP
server, and CI — changing it is a breaking change (minor/major release
only, changelog entry mandatory; see spec §3.6).

English headings are fixed (the lint contract); ticket body text follows
the BA's working language.
"""

from __future__ import annotations

import re

REQUIRED_HEADINGS: tuple[str, ...] = (
    "## Summary",
    "## User Story",
    "## Background / Business context",
    "## Acceptance Criteria",
    "## Use cases",
    "## Business flow",
    "## KB context",
    "## Definition of Ready",
)

# Core sections every ticket carries. Deliberately NOT merged into
# REQUIRED_HEADINGS: that tuple is a compatibility contract and every
# pre-existing ticket must keep passing without an edit. Lint reports a
# missing/empty recommended section as a WARNING only.
RECOMMENDED_HEADINGS: tuple[str, ...] = (
    "## Dependencies",
    "## Out of scope",
    "## Technical grounding",   # SA-owned (spec 2026-09-20-sa-grounding-design §3)
    "## Open questions",
)

# Extended sections — present only when the story needs them. Absent is
# fine; present-but-empty is a warning (same as RECOMMENDED); absent while
# the story's own words call for it (EXTENDED_TRIGGERS) is a warning too.
# '## Sequence diagram' left REQUIRED_HEADINGS in 1.5.0: it is a design
# artifact (actors, services, messages) the Dev draws at dev-design when
# the interaction spans more than one system — a BA drawing it before the
# SA grounds the ticket either invents participants or fills it with
# %%TODO%%.
EXTENDED_HEADINGS: tuple[str, ...] = (
    "## Sequence diagram",
    "## Non-functional requirements",
    "## UI / presentation spec",
    "## Test data & verification",
)

# What in the BA's own words (Summary, User Story, ACs, Use cases) says an
# extended section is needed. Bilingual; warning-level, so a false hit
# costs one line the BA answers with 'N/A — <reason>'.
EXTENDED_TRIGGERS: dict[str, re.Pattern[str]] = {
    "## Sequence diagram": re.compile(
        r"\b(?:integrat|external system|third[- ]party|webhook|callback"
        r"|hệ thống ngoài|bên thứ ba|tích hợp)",
        re.I,
    ),
    "## Non-functional requirements": re.compile(
        r"\b(?:load|bulk|batch|concurren|latenc|throughput|timeout"
        r"|real[- ]?time|within \d|per second|hàng loạt|đồng thời"
        r"|thời gian thực|trong vòng \d|độ trễ)",
        re.I,
    ),
    "## UI / presentation spec": re.compile(
        r"\b(?:screen|page|panel|button|dialog|form|dropdown|column"
        r"|display|shown?|màn hình|trang|nút|hiển thị|bảng|cột)\b",
        re.I,
    ),
    "## Test data & verification": re.compile(
        r"\b(?:record|import|ingest|parse|file|dataset|field|format"
        r"|bản ghi|tập tin|trường|định dạng|nhập liệu)\b",
        re.I,
    ),
}

# BA-only sections that never reach the tracker: `export_body` drops them.
INTERNAL_HEADINGS: tuple[str, ...] = (
    "## Definition of Ready",
    "## Review record",
)

# "As a <role>, I want <capability>, so that <value>." — case-insensitive,
# multiline (the story text may wrap).
STORY_RE = re.compile(r"as an?\s+.+?i want\s+.+?so that\s+", re.I | re.S)

# The same story shape, with each part captured, so the gate can ask
# whether the parts say anything. STORY_RE stays the shape check.
STORY_PARTS_RE = re.compile(
    r"as an?\s+(?P<role>.+?)\s*,?\s*i want\s+(?P<capability>.+?)"
    r"\s*,?\s*so that\s+(?P<value>.+)",
    re.I | re.S,
)

# '> Parent mission: M-<slug>' — an OPTIONAL back-link to a mission plan,
# placed directly under the H1 title. Deliberately not a required
# heading: REQUIRED_HEADINGS is a compatibility contract, so every
# pre-existing ticket must keep passing without an edit (spec §4.4).
PARENT_MISSION_RE = re.compile(r"^>\s*Parent mission:\s*(\S+)\s*$", re.M)

# Detects the '> Parent mission:' line regardless of whether it has a
# usable value after the colon. PARENT_MISSION_RE requires >= 1 non-space
# character in the value, so a half-written line ('> Parent mission:' with
# nothing, or only whitespace, after the colon) does not match it at all —
# this regex is how `check_parent_mission` tells "line absent" apart from
# "line present but blank" so the latter can be flagged instead of silently
# read as "no parent mission".
PARENT_MISSION_LINE_RE = re.compile(r"^>\s*Parent mission:\s*(.*)$", re.M)


def export_body(text: str) -> str:
    """The ticket as it goes into the tracker: guidance comments gone and
    the BA-internal sections (`INTERNAL_HEADINGS`) dropped. Everything the
    Dev reads stays — `## KB context` (the pin `kb resolve` needs),
    `## Dependencies`, `## Technical grounding`. Fence-aware: a `##` line
    inside a mermaid or yaml fence never opens or closes a section."""
    from strata_kb import lintcore  # local: lintcore has no ticket import

    lines = lintcore.HTML_COMMENT_RE.sub("", text).splitlines()
    scan = lintcore._blank_invisible("\n".join(lines)).splitlines()
    scan += [""] * (len(lines) - len(scan))
    kept: list[str] = []
    dropping = False
    for line, probe in zip(lines, scan):
        if probe.startswith("## ") or probe.startswith("# "):
            dropping = probe.strip() in INTERNAL_HEADINGS
        if not dropping:
            kept.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip() + "\n"
