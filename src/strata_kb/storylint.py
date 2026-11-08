"""Parent-story format and parent/child consistency lint.

A parent story (`> Kind: parent story`) carries the business story and a
`## Split` table that names one child ticket per repo. It has no acceptance
criteria of its own: each AC lives in exactly one live child. This module
checks the parent's shape (`lint_parent`) and each child against its parent
row (`lint_child_against_parent`). A parent bug (`> Kind: parent bug`) uses
the same table with one extra row for the parent's own fix and no ACs; its
children are bugs (`lint_bug_child_against_parent`). It must not import
`ticketlint` (`ticketlint` calls it).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from strata_kb import lintcore, planrev, ticket
from strata_kb.doctor import Issue
from strata_kb.lintcore import LintReport

SPLIT_COLUMNS = ("Child", "Repo", "AC", "Blocked by", "Own fix", "Why")
_REQUIRED = ("## User Story", "## Split", "## Change log")
_FORBIDDEN = ("## Acceptance Criteria", "## Definition of Ready")
# The parent bug's other headings are buglint's (it is a bug ticket too).
_BUG_REQUIRED = ("## Split", "## Change log")

_AC_CELL_RE = re.compile(r"(AC\d+)(?:\s*\(\s*replaces\s+(AC\d+)\s*\))?", re.I)
_TOKEN_SPLIT_RE = re.compile(r"[\s,;()—–]+")
_NO_VALUE = {"", "-", "none", "n/a"}


@dataclass(frozen=True)
class SplitRow:
    child: str
    repo: str
    acs: tuple[str, ...]
    replaces: dict[str, str]  # new AC id -> the AC id it replaces
    blocked_by: tuple[str, ...]
    own_fix: str
    why: str
    ac_cell: str = ""  # the raw AC cell, to tell `-` (planned) from unparsable


def is_planned(row: SplitRow) -> bool:
    """A child planned at mission time: AC cell `-`, its file not written yet."""
    return row.acs == () and row.ac_cell.strip().lower() in _NO_VALUE


def own_row(rows: list[SplitRow], parent_id: str) -> SplitRow | None:
    """The parent bug's own-fix row: the row whose child is the parent id."""
    return next((r for r in rows if r.child == parent_id), None)


def _split_rows(text: str) -> list[list[str]]:
    body = lintcore.section_body(text, "## Split")
    return lintcore.table_rows(lintcore.visible_body(body)) if body else []


def parse_split(text: str) -> list[SplitRow]:
    """Data rows of the `## Split` table, columns found by name. Rows with an
    empty Child cell (the template's blank row) are skipped; a table missing
    a column yields no rows."""
    rows = _split_rows(text)
    cols = [lintcore.table_column(rows, name) for name in SPLIT_COLUMNS]
    if not rows or None in cols:
        return []
    out: list[SplitRow] = []
    for cells in rows[1:]:
        if len(cells) < len(rows[0]):
            continue  # reported by _check_split_table
        child, repo, ac, blocked, own_fix, why = (
            cells[c] for c in cols if c is not None
        )
        if not child:
            continue
        pairs = _AC_CELL_RE.findall(ac)
        out.append(
            SplitRow(
                child,
                repo,
                tuple(a.upper() for a, _ in pairs),
                {a.upper(): r.upper() for a, r in pairs if r},
                ()
                if blocked.strip().lower() in _NO_VALUE
                else tuple(t for t in _TOKEN_SPLIT_RE.split(blocked) if t),
                own_fix,
                why,
                ac,
            )
        )
    return out


def _find_cycle(graph: dict[str, tuple[str, ...]]) -> list[str] | None:
    state: dict[str, int] = {}  # 1 = on stack, 2 = done
    stack: list[str] = []

    def visit(node: str) -> list[str] | None:
        state[node] = 1
        stack.append(node)
        for nxt in graph.get(node, ()):
            if nxt not in graph:
                continue
            if state.get(nxt) == 1:
                return [*stack[stack.index(nxt) :], nxt]
            if nxt not in state and (found := visit(nxt)):
                return found
        stack.pop()
        state[node] = 2
        return None

    for node in graph:
        if node not in state and (found := visit(node)):
            return found
    return None


def _err(message: str) -> Issue:
    return Issue("error", message)


def _check_shape(text: str, *, bug: bool = False) -> list[Issue]:
    if bug:  # title, revision and the rest are buglint's
        return lintcore.check_headings(text, _BUG_REQUIRED) + _split_decision(text)
    issues = lintcore.check_title(text) + lintcore.check_headings(text, _REQUIRED)
    issues += [
        _err(f"a parent story has no '{h}' — the ACs live in its children")
        for h in _FORBIDDEN
        if lintcore.section_body(text, h) is not None
    ]
    if planrev.parse_revision(text) is None:
        issues.append(_err("'> Revision: <N>' line missing on the parent story"))
        issues += [
            i for i in planrev.check_revision(text) if "line missing" not in i.message
        ]
    else:
        issues += planrev.check_revision(text)
    return issues + _split_decision(text)


def _split_decision(text: str) -> list[Issue]:
    log = lintcore.section_body(text, "## Change log") or ""
    if any(
        ln.startswith("**Split decision:**")
        for ln in lintcore.visible_body(log).splitlines()
    ):
        return []
    return [
        Issue(
            "warning",
            "no '**Split decision:**' line under '## Change log' — "
            "record who accepted the split",
        )
    ]


def _check_split_table(rows: list[SplitRow], parent_id: str, text: str) -> list[Issue]:
    header_rows = _split_rows(text)
    header = header_rows[:1]
    if not rows and header and tuple(header[0]) == SPLIT_COLUMNS:
        return [_err("'## Split' has no child rows")]
    issues: list[Issue] = []
    if not header or tuple(header[0]) != SPLIT_COLUMNS:
        issues.append(
            _err(f"'## Split' columns must be exactly: {' | '.join(SPLIT_COLUMNS)}")
        )
        return issues
    for n, cells in enumerate(header_rows[1:], 1):
        if len(cells) < len(SPLIT_COLUMNS):
            issues.append(
                _err(
                    f"split row {n} has {len(cells)} cells, expected {len(SPLIT_COLUMNS)}"
                )
            )
    seen: set[str] = set()
    for row in rows:
        m = ticket.CHILD_ID_RE.match(row.child)
        if m is None and "." in row.repo:
            issues.append(
                _err(
                    f"split child '{row.child}': repo ids containing '.' cannot "
                    "be split targets"
                )
            )
        elif m is None or m.group("parent") != parent_id:
            issues.append(
                _err(
                    f"split child '{row.child}' is not '{parent_id}.<repo>' "
                    f"or '{parent_id}.<repo>.<n>' (n >= 2)"
                )
            )
        elif m.group("repo") != row.repo:
            issues.append(
                _err(
                    f"split child '{row.child}': Repo '{row.repo}' differs from its id"
                )
            )
        if row.child in seen:
            issues.append(_err(f"split child '{row.child}' is listed twice"))
        seen.add(row.child)
    return issues


def _check_acs_unique(rows: list[SplitRow]) -> list[Issue]:
    owners: dict[str, list[str]] = {}
    for row in rows:
        for ac in row.acs:
            owners.setdefault(ac, []).append(row.child)
    return [
        _err(f"{ac} is in more than one split child: {', '.join(kids)}")
        for ac, kids in owners.items()
        if len(kids) > 1
    ]


def _check_blocked_by(rows: list[SplitRow]) -> list[Issue]:
    ids = {r.child for r in rows}
    issues = [
        _err(f"split child '{r.child}': Blocked by '{b}' is not a child in the split")
        for r in rows
        for b in r.blocked_by
        if b not in ids
    ]
    cycle = _find_cycle({r.child: r.blocked_by for r in rows})
    if cycle:
        issues.append(_err(f"dependency cycle: {' → '.join(cycle)}"))
    return issues


def _check_written_children(
    rows: list[SplitRow],
    children: dict[str, str | None],
    parent_text: str,
    parent_id: str,
) -> list[Issue]:
    """Each written child must agree with its split row, so a parent-only
    edit cannot publish a split its children contradict. A child demoted by a
    later change-log row (pin behind the parent, row lists the child) is
    waiting for its own amendment and is skipped."""
    current = planrev.parse_revision(parent_text) or 1
    issues: list[Issue] = []
    for row in rows:
        text = children.get(row.child)
        if text is None:
            continue
        pin = ticket.parent_story_pin(text)
        if (
            pin is not None
            and pin[0] == parent_id
            and pin[1] < current
            and planrev.later_row_lists(parent_text, pin[1], row.child)
        ):
            continue
        if ticket.ticket_kind(parent_text) == "parent bug":
            issues += lint_bug_child_against_parent(
                text, row.child, parent_text, parent_id
            )
        else:
            issues += lint_child_against_parent(
                text, row.child, parent_text, parent_id, check_ac_count=False
            )
    return issues


def lint_parent(
    parent_text: str, children: dict[str, str | None], *, parent_id: str
) -> LintReport:
    """Shape and split-table checks for a parent story. `children` maps each
    split child id to its text, or None when the file is missing."""
    kind = ticket.ticket_kind(parent_text)
    bug = kind == "parent bug"
    issues: list[Issue] = []
    if kind != "parent story" and not bug:
        issues.append(_err("'> Kind: parent story' line missing in the header"))
    issues += _check_shape(parent_text, bug=bug)
    all_rows = parse_split(parent_text)
    if bug:
        issues += _check_own_rows(all_rows, parent_id)
    # the own-fix row is not a child: no child id, no ticket file
    rows = [r for r in all_rows if not (bug and r.child == parent_id)]
    issues += _check_split_table(rows, parent_id, parent_text)
    # every ACs cell of a parent bug is `-`, so its children are never 'planned'
    issues += [
        _err(f"split child '{r.child}' has no ticket file")
        for r in rows
        if children.get(r.child) is None and (bug or not is_planned(r))
    ]
    issues += _check_acs_unique(rows) + _check_blocked_by(all_rows if bug else rows)
    issues += _check_written_children(rows, children, parent_text, parent_id)
    issues += _check_change_log_affected(all_rows, parent_text)
    return LintReport(issues)


def _check_own_rows(rows: list[SplitRow], parent_id: str) -> list[Issue]:
    own = [r for r in rows if r.child == parent_id]
    issues: list[Issue] = []
    if len(own) != 1:
        issues.append(
            _err(
                f"parent bug needs exactly one split row for {parent_id} itself "
                "(its own fix)"
            )
        )
    issues += [
        _err(f"split row {r.child}: Own fix must be yes or no")
        for r in own
        if r.own_fix.strip().lower() not in ("yes", "no")
    ]
    issues += [
        _err(f"split child '{r.child}': Own fix must be -")
        for r in rows
        if r.child != parent_id and r.own_fix.strip() != "-"
    ]
    if not all(is_planned(r) for r in rows):
        issues.append(_err("a parent bug's split has no ACs"))
    return issues


def _check_change_log_affected(rows: list[SplitRow], text: str) -> list[Issue]:
    """A parent change-log row's `Affected` names only split children. Only the
    newest row is an error: the log is append-only, so an older row may name a
    child that was cancelled since."""
    ids = {r.child for r in rows}
    log = [c for c in planrev.parse_change_log(text) if c.rev >= 2]
    newest = max((c.rev for c in log), default=0)
    return [
        Issue(
            "error" if c.rev == newest else "warning",
            f"change-log row {c.rev}: Affected '{a}' is not a child in the split",
        )
        for c in log
        for a in c.affected
        if a not in ids
    ]


def _ac_ids(text: str) -> tuple[list[str], int]:
    """AC ids (upper-case) and the count of visible AC items."""
    items = lintcore.ac_items(text)
    ids = [
        m.group(1).upper() for it in items if (m := lintcore.AC_ID_RE.match(it.strip()))
    ]
    return ids, len(items)


def _child_blocked_by(text: str, split_ids: set[str]) -> set[str]:
    """Tokens on the child's `- Blocked by:` bullet that are exact split
    child ids; prose and other words are ignored."""
    tokens = (
        t.rstrip(".:")
        for t in _TOKEN_SPLIT_RE.split(" ".join(lintcore.blocked_by_cells(text)))
    )
    return {t for t in tokens if t in split_ids}


def _norm(text: str | None) -> str:
    return " ".join(lintcore.visible_body(text or "").split())


def lint_child_against_parent(
    child_text: str,
    child_id: str,
    parent_text: str | None,
    parent_id: str,
    *,
    check_ac_count: bool = True,
) -> list[Issue]:
    """Errors for a child ticket that disagrees with its parent's split row."""
    if parent_text is None:
        return [
            _err(
                f"parent story {parent_id} not found — pass its text "
                "or keep it in the same folder"
            )
        ]
    issues: list[Issue] = []
    pin = ticket.parent_story_pin(child_text)
    if pin is None or pin[0] != parent_id:
        issues.append(
            _err(f"child '{child_id}' needs '> Parent story: {parent_id} @ rev <N>'")
        )
    rows = parse_split(parent_text)
    row = next((r for r in rows if r.child == child_id), None)
    if row is None:
        return [
            *issues,
            _err(f"child '{child_id}' is not listed in the split of {parent_id}"),
        ]
    ids, count = _ac_ids(child_text)
    if check_ac_count and count < 2:
        issues.append(
            _err(
                f"Acceptance Criteria must have at least 2 '- [ ]' items — found {count}"
            )
        )
    if set(ids) != set(row.acs):
        issues.append(
            _err(
                f"child '{child_id}' AC ids {sorted(set(ids))} differ from its "
                f"split row in {parent_id} {sorted(row.acs)}"
            )
        )
    got_blocked = _child_blocked_by(child_text, {r.child for r in rows})
    if got_blocked != set(row.blocked_by):
        issues.append(
            _err(
                f"child '{child_id}' Blocked by {sorted(got_blocked)} "
                f"differs from its split row in {parent_id} {sorted(row.blocked_by)}"
            )
        )
    if ticket.target_header(child_text) != row.repo:
        issues.append(
            _err(
                f"child '{child_id}' '> Target repo:' differs from split Repo '{row.repo}'"
            )
        )
    story = "## User Story"
    if _norm(lintcore.section_body(child_text, story)) != _norm(
        lintcore.section_body(parent_text, story)
    ):
        issues.append(
            _err(f"child '{child_id}' '## User Story' differs from {parent_id}'s")
        )
    return issues


def lint_bug_child_against_parent(
    child_text: str, child_id: str, parent_text: str | None, parent_id: str
) -> list[Issue]:
    """Errors for a child bug that disagrees with its parent bug's split row:
    the pin, `> Target repo:` and `- Blocked by:` must match."""
    if parent_text is None:
        return [
            _err(
                f"parent bug {parent_id} not found — pass its text "
                "or keep it in the same folder"
            )
        ]
    issues: list[Issue] = []
    pin = ticket.parent_story_pin(child_text)
    if pin is None or pin[0] != parent_id:
        issues.append(
            _err(f"child '{child_id}' needs '> Parent bug: {parent_id} @ rev <N>'")
        )
    rows = parse_split(parent_text)
    row = next((r for r in rows if r.child == child_id), None)
    if row is None:
        return [
            *issues,
            _err(f"child '{child_id}' is not listed in the split of {parent_id}"),
        ]
    if ticket.target_header(child_text) != row.repo:
        issues.append(
            _err(
                f"child '{child_id}' '> Target repo:' differs from split Repo '{row.repo}'"
            )
        )
    got_blocked = _child_blocked_by(child_text, {r.child for r in rows})
    if got_blocked != set(row.blocked_by):
        issues.append(
            _err(
                f"child '{child_id}' Blocked by {sorted(got_blocked)} "
                f"differs from its split row in {parent_id} {sorted(row.blocked_by)}"
            )
        )
    return issues
