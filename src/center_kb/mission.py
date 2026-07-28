"""Mission Plan template contract (Phase 4.1 — BA mission plan).

Single source of truth for the mission heading list, the id formats, and
the backlog table shape that `missionlint.py` enforces.
`REQUIRED_MISSION_HEADINGS` is a compatibility contract between the BA's
local install and CI — changing it is a breaking change (minor/major
release only, changelog entry mandatory; see spec §3.6).

English headings are fixed (the lint contract); mission body text follows
the BA's working language.
"""

from __future__ import annotations

import re

REQUIRED_MISSION_HEADINGS: tuple[str, ...] = (
    "## Summary",
    "## Business goal",
    "## Scope",
    "## System context (C4 L1)",
    "## Containers (C4 L2)",
    "## Constraints & assumptions",
    "## US backlog",
    "## KB context",
    "## Definition of Ready",
)

# C4 Level 3 is deliberately OPTIONAL: grounding components in real code
# needs Phase 5 code-knowledge, so L3 here is only drawn from component
# detail the BA supplies directly. Lint checks the section when present
# and stays silent when absent.
COMPONENT_HEADING = "## Components (C4 L3)"

# Accepted mermaid diagram keywords per level — C4-native OR flowchart.
# Mermaid documents its C4 diagram type as experimental with "syntax and
# properties subject to change"; binding a breaking-change-class lint
# contract to that would let an upstream release fail every team's DoR
# gate. The check asks "is there a diagram at this level", not "is this
# diagram syntactically C4" (spec §5.1).
L1_KEYWORDS: tuple[str, ...] = ("C4Context", "flowchart")
L2_KEYWORDS: tuple[str, ...] = ("C4Container", "flowchart")
L3_KEYWORDS: tuple[str, ...] = ("C4Component", "flowchart")

# '> Mission: M-<slug>' — the mission id lives INSIDE the document, not
# only in the filename, because lint also runs over stdin.
MISSION_LINE_RE = re.compile(r"^>\s*Mission:\s*(\S+)\s*$", re.M)

# A mission id: 'M-' followed by lowercase kebab-case.
MISSION_ID_RE = re.compile(r"^M-[a-z0-9]+(?:-[a-z0-9]+)*$")

# The US backlog table header, exactly. Fixing the header keeps the
# parser from guessing which column holds the id.
BACKLOG_HEADER_RE = re.compile(r"^\|\s*US ID\s*\|\s*Title\s*\|\s*$")

# The markdown separator row under the header: '|---|---|'.
BACKLOG_SEP_RE = re.compile(r"^\|[\s:|-]+\|$")

# A backlog data row: '| <us-id> | <title> |'.
BACKLOG_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(.*?)\s*\|$")

# The placeholder convention inherited from Phase 4 (spec §12): detail
# that would need code knowledge is marked, never invented. Phase 5
# agents find and resolve these.
PLACEHOLDER = "%%TODO: verify against codebase%%"


def us_id_re(mission_id: str) -> re.Pattern[str]:
    """US ids are derived from the mission id: '<mission-id>-US<n>', n >= 1.

    Numbering gaps are allowed — a story dropped during review leaves its
    number retired rather than forcing a renumber that would break
    already-drafted ticket filenames. Callers check format and uniqueness,
    never contiguity.
    """
    return re.compile(rf"^{re.escape(mission_id)}-US[1-9]\d*$")
