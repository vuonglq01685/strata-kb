"""`kb ticket lint` engine — the Definition-of-Ready gate for BA tickets.

No CLI/MCP dependencies here: `cli.py`'s `kb ticket lint` command and the
`kb_ticket_lint` MCP tool are both thin wrappers over `lint()`. Shared
primitives live in `lintcore`; this module holds only what is specific to
the ticket contract.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import TYPE_CHECKING

from strata_kb import acquality, lintcore, mission, missionlint, ticket
from strata_kb.doctor import Issue
from strata_kb.lintcore import LintReport

if TYPE_CHECKING:
    from strata_kb.hub import HubHandle

# A '- [ ]' / '- [x]' checkbox list item.
_AC_ITEM_RE = re.compile(r"^-\s*\[[ xX]\]\s*(.+)$")

# An AC is an observable outcome, never a shell command (docs/ac-quality.md,
# spec 2026-09-23 §6). A backticked span whose first word — after skipping
# a leading `sudo`, a `$` prompt marker, or a `VAR=value` assignment — is
# one of these, or that chains two command-like words with `&&`, is the
# command a Dev would run — it belongs in `## Test data & verification` or
# the plan. `git`, `make`, `python` and `sed` are deliberately absent: they
# collide too often with ordinary AC nouns (`` `git SHA` ``, `` `python
# 3.13` ``, `` `make build` ``) for a BA-facing lint to warn on the bare
# word.
SHELL_COMMANDS: frozenset[str] = frozenset({
    "docker", "docker-compose", "curl", "wget", "grep", "psql", "redis-cli",
    "ffmpeg", "ffprobe", "mc", "kubectl", "npm", "pnpm", "npx", "prisma",
    "ls", "cat", "find", "nvidia-smi", "sh", "bash",
    "kb", "uv", "pytest", "jq", "ssh",
})
_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
# `&&` alone is a command chain — nobody backticks `` `active && inactive` ``
# — so it fires unqualified. `|`, `||` and `;` collide with a value union
# (`` `active | inactive` ``), a type union (`` `string | null` ``), or a
# semicolon-separated value list, so each of those three still needs
# command evidence on top of the operator.
_UNGATED_OPERATOR_RE = re.compile(r"\S\s+(&&)\s+\S")
_GATED_OPERATOR_RE = re.compile(r"\S\s+(\|\||\||;)\s+\S")
# A flag (`-x`, `--xyz`) or path (`./x`, `/x/y`) token — the second signal
# that lets a gated operator fire on a real command line rather than a
# value union or type union.
_SHELL_EVIDENCE_RE = re.compile(r"(?:^|\s)(-{1,2}[A-Za-z][\w-]*|\.{1,2}/\S+|/\S+)")
# A leading `sudo`, a `$` shell-prompt marker, or a `VAR=value`
# assignment — none names the command being run, so each is skipped
# before a span's first word is judged.
_LEADING_PREFIX_RE = re.compile(r"^(?:sudo|\$|[A-Za-z_]\w*=\S*)\s+")

# Required sections whose body is checked by a stronger, section-specific
# check — a second "is it filled" error would only duplicate it.
_FILL_EXEMPT: frozenset[str] = frozenset(
    {
        "## KB context",          # parsed by check_context_block
        "## Sequence diagram",    # check_diagram
        "## Business flow",       # check_diagram
        "## Definition of Ready", # _check_dor_checklist, below
    }
)


def _check_required_filled(text: str) -> list[Issue]:
    """NT1 — a required section that says nothing is not a section.
    Presence was the whole contract before 0.22.0, so a ticket of nine
    headings over nine 'TBD's passed the gate (reviewer E's T1)."""
    issues: list[Issue] = []
    for heading in ticket.REQUIRED_HEADINGS:
        if heading in _FILL_EXEMPT:
            continue
        body = lintcore.section_body(text, heading)
        if body is None:
            continue  # missing heading — already reported by check_headings
        if acquality.is_unfilled(lintcore.visible_body(body)):
            issues.append(
                Issue(
                    "error",
                    f"'{heading}' is empty or only placeholder text — "
                    "fill it in",
                )
            )
    return issues


def _check_story(text: str) -> list[Issue]:
    body = lintcore.section_body(text, "## User Story")
    if body is None:
        return []  # heading missing — already reported by check_headings
    if not ticket.STORY_RE.search(body):
        return [
            Issue(
                "error",
                "User Story does not match 'As a <role>, I want "
                "<capability>, so that <value>.'",
            )
        ]
    match = ticket.STORY_PARTS_RE.search(body)
    if match is None:  # shape matched but parts did not — treat as unfilled
        return []
    issues: list[Issue] = []
    for name in ("role", "capability", "value"):
        part = match.group(name).strip().rstrip(".")
        letters = re.sub(r"[\W_]+", "", part, flags=re.UNICODE)
        if len(letters) < 2 or acquality.is_unfilled(part):
            issues.append(
                Issue(
                    "error",
                    f"User Story part <{name}> says nothing: '{part}' — "
                    "name the actual role, capability and value",
                )
            )
    return issues


def _check_story_count(text: str) -> list[Issue]:
    """One ticket, one story. Two stories under one heading make every AC
    ambiguous about which story accepts it, and the split the BA avoided
    lands on the dev instead.

    `STORY_RE.findall` is a sound count for well-formed stories: the
    pattern is lazy under `re.S` and ends at 'so that', so each match
    consumes exactly one
    story and the scan resumes past it. A single comma-rich story — even
    one saying 'shown as a side panel' after 'I want' — yields 1, because
    the incidental 'as a' sits inside the first match's span.
    """
    body = lintcore.section_body(text, "## User Story")
    if body is None:
        return []  # heading missing — already reported by check_headings
    # Comments carry template guidance and drafts; count only what shows.
    found = len(ticket.STORY_RE.findall(lintcore.visible_body(body)))
    if found <= 1:
        return []
    return [
        Issue(
            "error",
            f"User Story has {found} stories — one ticket per story, "
            "split the ticket",
        )
    ]


def _check_ac_present(text: str) -> tuple[list[Issue], list[str]]:
    body = lintcore.section_body(text, "## Acceptance Criteria")
    if body is None:
        return [], []
    # Visible items only: an AC parked in a comment is neither a real
    # criterion (floor) nor scope (ceiling).
    items = [
        m.group(1)
        for line in lintcore.visible_body(body).splitlines()
        if (m := _AC_ITEM_RE.match(line.strip()))
    ]
    if len(items) < 2:
        return [
            Issue(
                "error",
                "Acceptance Criteria must have at least 2 '- [ ]' items — "
                f"found {len(items)}",
            )
        ], items
    return [], items


# Upper bound on acceptance criteria. Deliberately NOT a config key: the
# only real ticket measured so far carried 27 AC — six natural clusters
# that should have been six tickets — and a threshold tuned
# on a single sample is a guess, not a policy. Revisit when ~20 real
# tickets exist and the p90 is known.
MAX_AC = 10


def _check_ac_count(ac_items: list[str]) -> list[Issue]:
    """The ceiling that `_check_ac_present`'s 'at least 2' has no opinion
    about. More AC than a reviewer can hold in one pass is a scope
    problem, not a formatting one — the fix is a second ticket, never two
    conditions merged into one AC to duck the cap."""
    if len(ac_items) <= MAX_AC:
        return []
    return [
        Issue(
            "error",
            f"Acceptance Criteria has {len(ac_items)} items "
            f"(max {MAX_AC}) — split the ticket, one user story per "
            "ticket",
        )
    ]


_AC_ID_RE = re.compile(r"^(AC\d+)\b", re.I)


def _check_ac_ids(ac_items: list[str]) -> list[Issue]:
    """Two ACs sharing an id make every downstream reference ambiguous —
    the AC→test map in the PR template names ids."""
    seen: set[str] = set()
    issues: list[Issue] = []
    for item in ac_items:
        m = _AC_ID_RE.match(item.strip())
        if m is None:
            continue
        key = m.group(1).upper()
        if key in seen:
            issues.append(
                Issue(
                    "error",
                    f"duplicate Acceptance Criterion id '{m.group(1)}' — "
                    "give every AC its own id",
                )
            )
        seen.add(key)
    return issues


def _check_ac_substance(ac_items: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for item in ac_items:
        reason = acquality.ac_substance(item)
        if reason is not None:
            issues.append(
                Issue("error", f"AC {reason}: '{item.strip()}'")
            )
    return issues


def _check_ac_citations(ac_items: list[str]) -> list[Issue]:
    return [
        Issue(
            "warning",
            "Acceptance Criterion has no '[doc-id §section]' citation: "
            f"'{item.strip()}'",
        )
        for item in ac_items
        if not lintcore.BRACKET_CITE_RE.search(item)
    ]


def _check_ac_weasel(ac_items: list[str]) -> list[Issue]:
    """NT2 — an AC that cannot be acceptance-tested does not exist.
    Warning per banned phrase (docs/ac-quality.md). Since 0.22.0 an
    OPEN(<owner>) marker suppresses only the phrase(s) sitting INSIDE its
    own parentheses, and only when the owner is real — a marker whose
    owner is TBD/?/empty (declared but unowned vagueness) suppresses
    nothing at all (see acquality.weasel_hits)."""
    return [
        Issue(
            "warning",
            f"AC uses banned weasel phrase '{phrase}' outside any owned "
            f"OPEN(<owner>): '{item.strip()}' — see docs/ac-quality.md",
        )
        for item in ac_items
        for phrase in acquality.weasel_hits(item)
    ]


def _leading_word(text: str) -> str:
    """The first shell-relevant word in `text`, skipping a leading
    `sudo`, `$` prompt marker, or `VAR=value` assignment token."""
    remaining = text.strip()
    while True:
        m = _LEADING_PREFIX_RE.match(remaining)
        if m is None:
            return remaining.split(maxsplit=1)[0] if remaining else ""
        remaining = remaining[m.end() :]


def _is_shell_span(span: str) -> bool:
    if _leading_word(span) in SHELL_COMMANDS:
        return True
    if _UNGATED_OPERATOR_RE.search(span) is not None:
        return True
    m = _GATED_OPERATOR_RE.search(span)
    if m is None:
        return False
    sides = (span[: m.start(1)], span[m.end(1) :])
    if any(_leading_word(side) in SHELL_COMMANDS for side in sides):
        return True
    return _SHELL_EVIDENCE_RE.search(span) is not None


def _check_ac_shell(ac_items: list[str]) -> list[Issue]:
    """An AC that prescribes a shell command shifts the guess about the
    real image/tool/path onto the BA, who cannot run it. Warning per AC
    (first offending span). An `OPEN(<owner>)` anywhere on the line
    suppresses the WHOLE line — line-level, unlike acquality.weasel_hits,
    which mutes only the text inside an owned marker's own parentheses —
    but only when the owner is real: this reuses
    acquality._marker_is_owned's before-the-colon ownership split, so
    `OPEN(TBD)` and `OPEN(TBD: Dev to confirm)` both still warn."""
    issues: list[Issue] = []
    for item in ac_items:
        if any(
            acquality._marker_is_owned(m.group(1))
            for m in acquality.OPEN_OWNER_RE.finditer(item)
        ):
            continue
        span = next(
            (s for s in _CODE_SPAN_RE.findall(item) if _is_shell_span(s)), None
        )
        if span is None:
            continue
        m = _AC_ID_RE.match(item.strip())
        label = m.group(1) if m else "AC"
        issues.append(Issue(
            "warning",
            f"{label} prescribes a shell command (`{span}`) — state the observable "
            "outcome here; the command belongs in ## Test data & verification or "
            "the Dev's plan — see docs/ac-quality.md",
        ))
    return issues


def _unknown_count(text: str) -> int:
    """OPEN(...) + %%TODO%% markers, guidance comments stripped so the
    templates' own '<!-- ... OPEN(<owner>) ... -->' examples never count."""
    clean = lintcore.HTML_COMMENT_RE.sub("", text)
    return len(acquality.OPEN_RE.findall(clean)) + clean.count(
        mission.PLACEHOLDER
    )


def _check_owned_unknowns(text: str) -> list[Issue]:
    """NT3 — 'unknown' is valid; 'unknown without an owner' is not. Every
    OPEN(...)/%%TODO%% outside '## Open questions' needs an owned row
    there. Count-based: exact marker-to-row matching is not decidable, so
    the check demands at least as many rows as markers."""
    rows = lintcore.open_question_rows(text) or []
    oq_body = lintcore.section_body(
        text, lintcore.OPEN_QUESTIONS_HEADING
    )
    outside = _unknown_count(text) - _unknown_count(oq_body or "")
    issues: list[Issue] = []
    if outside > len(rows):
        issues.append(
            Issue(
                "warning",
                f"{outside} OPEN(...)/'{mission.PLACEHOLDER}' marker(s) "
                f"but only {len(rows)} row(s) in '## Open questions' — "
                "every unknown needs an owned row",
            )
        )
    issues += lintcore.check_open_question_owners(rows)
    return issues


_NFR_HEADING = "## Non-functional requirements"


def _check_nfr_targets(text: str) -> list[Issue]:
    """Every NFR row needs a number or an owned unknown in Target. The
    section itself is RECOMMENDED — its absence stays a warning from
    check_recommended_sections; a table of moods is an error."""
    body = lintcore.section_body(text, _NFR_HEADING)
    if body is None:
        return []
    rows = lintcore.table_rows(lintcore.visible_body(body))
    if len(rows) < 2:
        return []  # header only, or no table — emptiness is warned elsewhere
    header = [c.strip().lower() for c in rows[0]]
    target = header.index("target") if "target" in header else 1
    issues: list[Issue] = []
    for cells in rows[1:]:
        if len(cells) <= target:
            continue
        if not acquality.nfr_target_ok(cells[target]):
            concern = cells[0] if cells else "?"
            issues.append(
                Issue(
                    "error",
                    f"NFR row '{concern}' has no measurable Target "
                    f"('{cells[target]}') — give a number or OPEN(<owner>)",
                )
            )
    return issues


_DOR_HEADING = "## Definition of Ready"


def _check_dor_checklist(text: str) -> list[Issue]:
    """The checklist must exist; ticking it is the BA's job at review
    time, so an unticked box is a warning — the wrappers forbid the agent
    from ticking one itself."""
    body = lintcore.section_body(text, _DOR_HEADING)
    if body is None:
        return []
    rows = [
        m
        for line in body.splitlines()
        if (m := lintcore.CHECKBOX_STATE_RE.match(line.strip()))
    ]
    if not rows:
        return [
            Issue(
                "error",
                f"'{_DOR_HEADING}' has no '- [ ]' checklist rows — keep the "
                "template's checklist",
            )
        ]
    return [
        Issue(
            "warning",
            f"Definition of Ready item is not ticked: "
            f"'{m.group('text').strip()}'",
        )
        for m in rows
        if m.group("mark") == " "
    ]


def check_parent_mission(
    text: str, path: Path | None, missions_dir: Path | None
) -> tuple[list[Issue], list[str]]:
    """Check 10. Only fires when the OPTIONAL '> Parent mission:' line is
    present — pre-existing tickets carry no such line and are unaffected.

    Traceability is enforced here rather than at mission lint because this
    is the point where both artifacts exist: a mission is authored before
    its tickets, so a mission-side existence check would fail every
    freshly written mission (spec §5.2).
    """
    m = ticket.PARENT_MISSION_RE.search(text)
    if m is None:
        if ticket.PARENT_MISSION_LINE_RE.search(text) is not None:
            # The line is present but the value after the colon is blank
            # or whitespace-only — a BA started the back-link and never
            # filled it in. Without this check the line simply fails to
            # match PARENT_MISSION_RE and reads as "no parent mission at
            # all", which is a silent PASS on a half-written back-link.
            return [
                Issue(
                    "error",
                    "'> Parent mission:' back-link is present but has no "
                    "mission id — fill in 'M-<slug>' after the colon",
                )
            ], []
        return [], []

    mission_id = m.group(1)
    if not mission.MISSION_ID_RE.match(mission_id):
        return [
            Issue(
                "error",
                f"malformed parent mission id '{mission_id}' — expected "
                "'M-<slug>' in lowercase kebab-case",
            )
        ], []

    if path is None or missions_dir is None:
        return [], [
            "parent-mission existence and backlog checks skipped — no repo "
            "paths supplied"
        ]

    mission_path = missions_dir / f"{mission_id}.md"
    if not mission_path.is_file():
        return [
            Issue(
                "error",
                f"mission file not found: '{mission_path}' — the ticket "
                f"declares parent mission '{mission_id}'",
            )
        ], []

    us_id = path.stem
    try:
        mission_text = mission_path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        # Unreachable from the MCP tool (kb_ticket_lint): it never passes
        # `path`/`missions_dir`, so execution already returned at the "no
        # repo paths supplied" branch above, well before this read. Keep
        # the guard anyway — this is the first engine code to read a
        # cross-referenced artifact (missionlint.check_coverage only ever
        # probes with `.is_file()`), so a bad mission file (e.g. saved as
        # cp1252 after a pasted smart quote, or a permission/race error)
        # must produce an [error] line, not a raw traceback.
        return [
            Issue(
                "error",
                f"could not read mission file '{mission_path}': {exc}",
            )
        ], []
    backlog_issues, backlog_ids = missionlint.check_backlog(
        mission_text, mission_id
    )
    if us_id not in backlog_ids:
        return [
            Issue(
                "error",
                f"'{us_id}' is not in the backlog of mission "
                f"'{mission_id}' — add the row, fix the ticket filename, "
                f"or run 'kb mission lint {mission_path}' if the mission's "
                "backlog table is malformed",
            )
        ], []
    if backlog_issues:
        # `check_backlog` found membership (the id string is in the table)
        # but the backlog table itself has OTHER errors — e.g. a
        # zero-padded id like 'M-demo-US01' fails mission lint's
        # `us_id_re` pattern check yet still lands in `backlog_ids`
        # verbatim, so a ticket named 'M-demo-US01.md' would otherwise
        # pass here while `kb mission lint` rejects the same id as
        # malformed. Surface a single warning rather than the mission's
        # own issue list — this check only vouches for "the id string
        # appears in the table", not for the table's own validity, which
        # is mission lint's job.
        return [
            Issue(
                "warning",
                f"parent mission '{mission_id}' backlog has errors; "
                "back-link membership may be unreliable — run "
                f"'kb mission lint {mission_path}'",
            )
        ], []
    return [], []


def lint(
    text: str,
    hub: "HubHandle | None",
    *,
    path: Path | None = None,
    missions_dir: Path | None = None,
    fail_on_stale: bool = False,
) -> LintReport:
    # NFC-normalize once, at the one entry point every check reads from:
    # `acquality`'s bilingual regexes (GWT_RE, _WEASEL_RE, _PLACEHOLDER_RE,
    # _UNOWNED via owned_open_markers) match NFC only, and an NFD-encoded
    # Vietnamese AC (macOS/IMEs spell an accented letter as base + combining
    # mark) would otherwise mismatch every one of them — see
    # `searchdb.tokenize`'s identical rationale and its test's NFD fixture.
    text = unicodedata.normalize("NFC", text)
    issues: list[Issue] = []
    notes: list[str] = []
    issues += lintcore.check_title(text)
    issues += lintcore.check_headings(text, ticket.REQUIRED_HEADINGS)
    issues += _check_required_filled(text)
    issues += _check_story(text)
    issues += _check_story_count(text)

    ac_issues, ac_items = _check_ac_present(text)
    issues += ac_issues
    issues += _check_ac_count(ac_items)
    issues += _check_ac_ids(ac_items)
    issues += _check_ac_substance(ac_items)

    issues += lintcore.check_diagram(
        text, "## Sequence diagram", ("sequenceDiagram",)
    )
    issues += lintcore.check_diagram(text, "## Business flow", ("flowchart",))

    ctx_issues, _ctx = lintcore.check_context_block(
        text, hub, fail_on_stale=fail_on_stale
    )
    issues += ctx_issues

    issues += _check_ac_citations(ac_items)

    issues += _check_ac_weasel(ac_items)
    issues += _check_ac_shell(ac_items)
    issues += lintcore.check_recommended_sections(
        text, ticket.RECOMMENDED_HEADINGS
    )
    issues += _check_owned_unknowns(text)
    issues += _check_nfr_targets(text)
    issues += _check_dor_checklist(text)
    issues += lintcore.check_review_record(text)

    pm_issues, pm_notes = check_parent_mission(text, path, missions_dir)
    issues += pm_issues
    notes += pm_notes

    return LintReport(issues=issues, notes=notes)
