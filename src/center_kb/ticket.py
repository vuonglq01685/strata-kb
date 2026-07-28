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

# "As a <role>, I want <capability>, so that <value>." — case-insensitive,
# multiline (the story text may wrap).
STORY_RE = re.compile(r"as an?\s+.+?i want\s+.+?so that\s+", re.I | re.S)
