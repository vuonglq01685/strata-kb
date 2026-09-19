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
    "## Sequence diagram",
    "## Business flow",
    "## KB context",
    "## Definition of Ready",
)

# New-template sections (BA upgrade v2). Deliberately NOT merged into
# REQUIRED_HEADINGS: that tuple is a compatibility contract and every
# pre-existing ticket must keep passing without an edit. Lint reports a
# missing/empty recommended section as a WARNING only. Order matches the
# template (all inserted before '## KB context').
RECOMMENDED_HEADINGS: tuple[str, ...] = (
    "## Dependencies",
    "## Non-functional requirements",
    "## UI / presentation spec",
    "## Out of scope",
    "## Test data & verification",
    "## Open questions",
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
