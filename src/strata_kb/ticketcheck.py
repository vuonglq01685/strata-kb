"""`kb ticket check` engine — the SA grounding gate.

Verifies a ticket's `## Technical grounding` section against the real
`<repo>-code` document: every `svc.* / db.* / api.* / int.* / cmd.* / route.* /
page.* / job.* / sym.*` id must exist in the document's `_manifest.yaml` (or
carry `[NEW: <reason>]`), columns / routes / pages / jobs / symbols / commands
must match the document's own L2 tables, `Files:` must be listed in
`struct.tree` or `struct.files.*`, `Volumes:` / `Healthchecks:` / `Devices:`
must match the svc L2 rows, a `[NEW]` route / page / job / symbol / file needs
a fully scanned `struct.coverage` scope and must not already be listed, and
`Open decisions` must be empty.

No CLI/MCP imports here — `cli.py`'s `kb ticket check` is a thin wrapper, the
same split `ticketlint.py` has. Where the document comes from (local
`.kb/` or the hub federation) is the caller's `load_doc` callable, and
`[NEW: D<n>]` markers are verified against the parent mission's
`## Technology decisions` through a second injected callable, `load_decisions`,
so the engine stays free of filesystem/CLI imports.
"""

from __future__ import annotations

import functools
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import yaml
from pydantic import ValidationError

from strata_kb import groundingdrift, lintcore, mission, models, ticket
from strata_kb.codeingest.extractors._ts import LANG_BY_SUFFIX
from strata_kb.doctor import Issue
from strata_kb.errors import KbError
from strata_kb.lintcore import LintReport
from strata_kb.mdutils import slice_section
from strata_kb.resolve import ResolvedRef

HEADING = "## Technical grounding"

# `- Grounded on: [<repo>:]<doc> @ <rev>` — repo/doc classes as in
# kbcontext._REF_RE; rev is a 7..40 hex commit (core.run() writes 7).
GROUNDED_ON_RE = re.compile(
    r"^-\s*Grounded on:\s*"
    r"(?:(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*):)?"
    r"(?P<doc>[A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*(?P<rev>[0-9a-fA-F]{7,40})\s*$"
)

_GROUNDED_PREFIX_RE = re.compile(r"^-\s*Grounded on:\s*(?P<rest>.*)$")


def grounded_entries(line: str) -> list[tuple[str | None, str, str]]:
    """`(repo, doc, rev)` per comma-separated entry of a `- Grounded on:`
    line. The mission template shows one entry; the SA writes the `-code`
    and `-svc` docs on one line, so the list is accepted here. Any entry
    that is not `[<repo>:]<doc> @ <rev>` makes the whole line unparseable
    (`[]`) — a half-read line would silently ground on the wrong doc."""
    m = _GROUNDED_PREFIX_RE.match(line.strip())
    if m is None:
        return []
    out: list[tuple[str | None, str, str]] = []
    for part in m.group("rest").split(","):
        em = GROUNDED_ON_RE.match(f"- Grounded on: {part.strip()}")
        if em is None:
            return []
        out.append((em.group("repo"), em.group("doc"), em.group("rev").lower()))
    return out


# A framework file name is not a section id. Two guards: `route|page|job|sym`
# are not matched when glued to a path or file name (`app/api/route.ts`,
# `users.route.ts`, `+page.svelte`, `export.job.ts`); and for every prefix a
# bare `<prefix>.<source-extension>` that ends there (`route.ts`, `db.ts`,
# `api.js.`) is not an id, while `route.tsx-extra` or `db.json_events` still are.
_SOURCE_EXTS = (
    "ts|tsx|js|jsx|mjs|cjs|mts|cts|py|go|rs|java|kt|cs|php|swift|dart|vue|svelte"
    "|css|scss|sql|prisma|md|yaml|yml|json"
)
# `route|page|job|sym` behind the glue guard; shared with ticketstale.
GUARDED_KINDS = r"(?<![\w/.+-])(?:route|page|job|sym)"
ID_TAIL = (
    rf"\.(?!(?:{_SOURCE_EXTS})(?![A-Za-z0-9_-]|\.[A-Za-z0-9_]))"
    r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
)
ID_RE = re.compile(rf"\b(?:svc|db|api|int|cmd|dep|struct|{GUARDED_KINDS}){ID_TAIL}")
NEW_RE = re.compile(r"\[NEW(?::\s*(?P<reason>[^\]]*))?\]")
ROUTE_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S*)")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
# A top-level field line: `- Files:`, `- Verify with: ...` (column 0 only —
# sub-items are indented and may themselves contain a colon).
FIELD_RE = re.compile(r"^-\s*(?P<field>[A-Za-z][A-Za-z ]*?):\s*(?P<rest>.*)$")
SUBITEM_RE = re.compile(r"^\s+-\s*(?P<text>.*\S)\s*$")
PRIMARY_RE = re.compile(r"\*\*Primary:\*\*\s*`([^`]*)`")
TREE_CAP_RE = re.compile(
    r"^# … \d+ more entr(?:y|ies) omitted from `(?P<first>[^`]*)` onward"
)
TREE_DEPTH = 4  # codeingest.extractors.tree._L3_DEPTH

SERVICES_HEADING = "## Services & order"
DECISION_REF_RE = re.compile(r"^D\d+$")
# A full US id inside a table cell (`Blocks`, `Depends on`): the mission
# slug is lowercase kebab-case (mission.MISSION_ID_RE), n >= 1.
US_ID_IN_CELL_RE = re.compile(r"\bM-[a-z0-9]+(?:-[a-z0-9]+)*-US[1-9]\d*\b")
# A bare `US<n>` in a `Depends on` or `Blocks` cell — not preceded by a word
# character or '-', so the tail of a full `M-x-US2` never re-matches once
# the full ids are blanked out first (see missionnext.dep_ids, parse_decisions
# below).
BARE_US_RE = re.compile(r"(?<![\w-])US[1-9]\d*\b")

_NONE_WORDS = frozenset({"none", "n/a", "-"})

COMPOSE_FIELDS: tuple[str, ...] = ("Volumes", "Healthchecks", "Devices")
# `svc.<x> — <values>` groups on one compose line, `;`-separated. A
# backtick span is matched whole so a `;` inside it (a `CMD-SHELL`
# healthcheck like `` `sh -c 'pg_isready; exit 0'` ``) doesn't end the
# group early.
_COMPOSE_GROUP_RE = re.compile(
    r"(svc\.[A-Za-z0-9_][A-Za-z0-9_.-]*)\s*[—-]\s*(?P<values>(?:`[^`]*`|[^;])*)"
)
_COMPOSE_ROW = {
    "Volumes": "Volumes",
    "Healthchecks": "Healthcheck",
    "Devices": "Devices",
}
_COMPOSE_NOUN = {
    "Volumes": "volume",
    "Healthchecks": "healthcheck",
    "Devices": "device",
}


class DocLoadError(KbError):
    """The -code document exists but cannot be used: unreadable manifest,
    or the same doc id published by several repos with no qualifier."""


@dataclass(frozen=True)
class LoadedDoc:
    manifest: models.Manifest
    source: str  # human label for the [note] line, e.g. ".kb/demo-code"
    read_group: Callable[[str], str | None]  # group stem -> L2 text
    read_raw: Callable[[str], str | None]  # group stem -> L3 text


LoadDoc = Callable[[str | None, str], LoadedDoc | None]


@dataclass(frozen=True)
class Decision:
    id: str
    status: str
    owner: str
    blocks: tuple[str, ...] = ()  # US ids in the `Blocks` cell, as written
    supersedes: str | None = (
        None  # D-id named by `Supersedes D<n>` in the Decision cell
    )
    text: str = dc_field(default="", compare=False)  # Decision cell, for related rows


@dataclass(frozen=True)
class DecisionTable:
    source: str  # human label, e.g. "missions/M-demo.md" or "this mission"
    rows: dict[str, Decision]


SUPERSEDED = "SUPERSEDED"
# Issue.code of decision-type errors: a human decides, the code did not drift.
DECISION = groundingdrift.DECISION_CODE
# Issue.code of a warning for a fact check that could not run (unreadable
# doc, depth/line cap, ...): the drift judgement reports it as unverified.
UNVERIFIED = groundingdrift.UNVERIFIED_CODE
_COMPOSE_SKIP_NOTE = "compose-fact checks skipped"
_SUPERSEDES_RE = re.compile(r"\bSupersedes\s+(D\d+)\b")

# (repo, doc id, grounded rev) -> the cited sections at that rev, None = no baseline
LoadDrift = Callable[[str | None, str, str], list[ResolvedRef] | None]

LoadDecisions = Callable[
    [str], DecisionTable | None
]  # mission id -> table, None = file missing

# every mission the caller can see: mission id -> its text
LoadMissions = Callable[[], dict[str, str]]

# (repo, doc id, grounded rev, section ids) -> those sections as they stood at
# the grounded revision, None = no baseline
LoadAt = Callable[[str | None, str, str, list[str]], list[ResolvedRef] | None]


def parse_decisions(text: str, source: str) -> DecisionTable:
    """The `## Technology decisions` table of `text` keyed by its `#` cell.
    Columns are found by header name, so a reordered table still parses;
    no section or no `#`/`Status` header -> empty rows. `blocks` carries the
    US ids of the `Blocks` cell — full ids as written, then bare `US<n>`
    tokens as written (this function has no mission id to prefix them with;
    `missionnext.statuses` resolves them via `dep_ids`) — empty when the
    column is absent."""
    body = lintcore.section_body(text, mission.TECH_DECISIONS_HEADING)
    rows = lintcore.table_rows(body) if body is not None else []
    if not rows:
        return DecisionTable(source, {})
    i_id = _table_column(rows, "#")
    i_status = _table_column(rows, "status")
    i_owner = _table_column(rows, "owner")
    i_blocks = _table_column(rows, "blocks")
    i_decision = _table_column(rows, "decision")
    if i_id is None or i_status is None:
        return DecisionTable(source, {})
    out: dict[str, Decision] = {}
    for r in rows[1:]:
        if len(r) <= max(i_id, i_status):
            continue
        owner = r[i_owner].strip() if i_owner is not None and len(r) > i_owner else ""
        blocks_cell = r[i_blocks] if i_blocks is not None and len(r) > i_blocks else ""
        full_blocks = US_ID_IN_CELL_RE.findall(blocks_cell)
        bare_blocks = BARE_US_RE.findall(US_ID_IN_CELL_RE.sub(" ", blocks_cell))
        blocks = tuple(dict.fromkeys(full_blocks + bare_blocks))
        cell = r[i_decision] if i_decision is not None and len(r) > i_decision else ""
        sup = _SUPERSEDES_RE.search(cell)
        out[r[i_id].strip()] = Decision(
            r[i_id].strip(),
            r[i_status].strip(),
            owner,
            blocks,
            sup.group(1) if sup else None,
            cell.strip(),
        )
    return DecisionTable(source, out)


_ANCHOR_SPAN_RE = re.compile(r"`([^`\s]+)`")
_ANCHOR_SHAPE_RE = re.compile(r"[/.]|[a-z][A-Z]")
_NEW_DECISION_RE = re.compile(r"\[NEW:\s*(D\d+)\s*\]")


def decision_anchors(cell: str) -> set[str]:
    """The files and symbols a Decision cell names: back-ticked spans shaped
    like a path, a dotted name or a camelCase/PascalCase identifier (plain
    words, CONSTANTS and commands are too generic to tie two rows), plus
    each path's file name, since rows spell the same file at different
    depths."""
    out: set[str] = set()
    for span in _ANCHOR_SPAN_RE.findall(cell):
        span = span.removesuffix("()")
        if not _ANCHOR_SHAPE_RE.search(span):
            continue
        out.add(span)
        if "/" in span.rstrip("/"):
            out.add(span.rstrip("/").rsplit("/", 1)[1])
    return out


def _names_row(cell: str, row_id: str, mission_id: str, own_mission: str) -> bool:
    """`cell` already cites D<n> of `mission_id` — the SA weighed that row."""
    if not re.search(rf"\b{row_id}\b", cell):
        return False
    return mission_id == own_mission or mission_id in cell


def related_decided(
    row: Decision, own_mission: str, missions: dict[str, str]
) -> list[str]:
    """`<mission> D<n> (`anchor`, …)` for every DECIDED row of every mission
    that names a file or symbol `row` names too, minus the rows `row`
    already cites."""
    mine = decision_anchors(row.text)
    if not mine:
        return []
    out: list[str] = []
    for mission_id in sorted(missions):
        table = parse_decisions(missions[mission_id], mission_id)
        for other in table.rows.values():
            if mission_id == own_mission and other.id == row.id:
                continue
            if other.status.upper() != "DECIDED":
                continue
            shared = sorted(mine & decision_anchors(other.text))
            if not shared or _names_row(row.text, other.id, mission_id, own_mission):
                continue
            spans = ", ".join(f"`{a}`" for a in shared[:3])
            out.append(f"{mission_id} {other.id} ({spans})")
    return out


def _check_related_decisions(
    section: _Section,
    decisions: _Decisions,
    own_mission: str | None,
    load_missions: LoadMissions | None,
    issues: list[Issue],
) -> None:
    """A D-row the section cites that names a file or symbol a DECIDED row
    already binds (in any mission) gets one warning listing those rows:
    the gate cannot judge a contradiction, the SA reads them."""
    if load_missions is None or decisions.table is None or own_mission is None:
        return
    first_line: dict[str, int] = {}
    for offset, line in enumerate(section.lines):
        for m in _NEW_DECISION_RE.finditer(line):
            first_line.setdefault(m.group(1), section.first_line + offset)
    if not first_line:
        return
    missions = load_missions()
    for row_id, lineno in first_line.items():
        row = decisions.table.rows.get(row_id)
        if row is None:
            continue
        related = related_decided(row, own_mission, missions)
        if related:
            issues.append(
                Issue(
                    "warning",
                    f"decision {row_id} names files or symbols that DECIDED rows "
                    f"already bind: {'; '.join(related)} — confirm {row_id} agrees "
                    f"with each and cite them in its Decision cell (line {lineno})",
                )
            )


def load_doc_dir(doc_dir: Path, source: str) -> LoadedDoc:
    manifest_path = doc_dir / "_manifest.yaml"
    try:
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
    except (yaml.YAMLError, OSError, UnicodeDecodeError, ValidationError) as exc:
        raise DocLoadError(f"could not read {manifest_path} ({exc})") from exc

    def _read(name: str) -> str | None:
        try:
            return (doc_dir / name).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    return LoadedDoc(
        manifest=manifest,
        source=source,
        read_group=lambda group: _read(f"{group}.md"),
        read_raw=lambda group: _read(f"{group}.raw.md"),
    )


def load_from_hub(federation_dir: Path, repo: str | None, doc: str) -> LoadedDoc | None:
    """The -code document from the hub's federation mirror. Same holder
    rule as `resolve.resolve_refs`: with a qualifier, that repo; without,
    exactly one repo may publish the doc id, otherwise the caller must
    qualify it."""
    from strata_kb.federation import load_federation

    holders = [
        r
        for r in load_federation(federation_dir)
        if (repo is None or r.meta.repo_id == repo)
        and (r.kb_dir / doc / "_manifest.yaml").exists()
    ]
    if not holders:
        return None
    if len(holders) > 1:
        names = ", ".join(sorted(r.meta.repo_id for r in holders))
        raise DocLoadError(
            f"{doc} is published by several repos ({names}) — qualify it: "
            f"`Grounded on: <repo-id>:{doc} @ <revision>`"
        )
    holder = holders[0]
    return load_doc_dir(holder.kb_dir / doc, f"hub federation/{holder.meta.repo_id}")


# ---------------------------------------------------------------------------
# section parsing
# ---------------------------------------------------------------------------


@dataclass
class _Section:
    first_line: int  # 1-based ticket line of the body's first line
    lines: list[str]  # visible body lines (HTML comments blanked)
    field_of_line: list[str | None]  # the `- <Field>:` a line belongs to
    subitems: dict[str, list[tuple[int, str]]]  # field -> [(lineno, text)]


def _heading_line_index(text: str, heading: str) -> int:
    """0-based index of the heading line, judged on the same blanked view
    `lintcore.section_body` uses (a fenced/commented heading never counts)."""
    scan = lintcore._blank_invisible(text).splitlines()
    for i, line in enumerate(scan):
        if line.strip() == heading:
            return i
    return -1


def _parse_section(text: str, heading: str) -> _Section | None:
    body = lintcore.section_body(text, heading)
    if body is None:
        return None
    first_line = _heading_line_index(text, heading) + 2
    blanked = lintcore.HTML_COMMENT_RE.sub(
        lambda m: "\n" * m.group(0).count("\n"), body
    )
    lines = blanked.splitlines()
    field_of_line: list[str | None] = []
    subitems: dict[str, list[tuple[int, str]]] = {}
    current: str | None = None
    for i, line in enumerate(lines):
        if line and not line[0].isspace():
            m = FIELD_RE.match(line)
            current = m.group("field").strip() if m else None
        elif current is not None:
            m = SUBITEM_RE.match(line)
            if m:
                subitems.setdefault(current, []).append(
                    (first_line + i, m.group("text"))
                )
        field_of_line.append(current)
    return _Section(first_line, lines, field_of_line, subitems)


@dataclass(frozen=True)
class _Decisions:
    table: DecisionTable | None
    mission_id: str | None  # the `> Parent mission:` id, or None


def _resolve_decisions(
    text: str, heading: str, load_decisions: LoadDecisions | None
) -> _Decisions:
    """Mission heading: the table is in the checked text itself. Ticket
    heading: via the back-link; `table is None` with a `mission_id` means
    the mission file could not be loaded."""
    if heading == SERVICES_HEADING:
        return _Decisions(parse_decisions(text, "this mission"), None)
    m = ticket.PARENT_MISSION_RE.search(text)
    if m is None:
        return _Decisions(None, None)
    mission_id = m.group(1)
    table = load_decisions(mission_id) if load_decisions is not None else None
    return _Decisions(table, mission_id)


def _issue_once(issues: list[Issue], issue: Issue) -> None:
    """Append `issue` unless an identical one is already collected. A line
    with two+ unknown ids under one shared `[NEW: …]` marker calls
    `_judge_new` once per id, but the marker's own verdict (its error or
    warning, which never names the id) is per-line, not per-id — only the
    notes, which do name the id, are meant to repeat."""
    if issue not in issues:
        issues.append(issue)


def _judge_new(
    label: str,
    new: re.Match,
    lineno: int,
    decisions: _Decisions,
    issues: list[Issue],
    notes: list[str],
) -> None:
    """One `[NEW: …]` marker: free text -> note; `D<n>` -> verified against
    the decisions table. `label` is the id or path the marker exempts."""
    reason = (new.group("reason") or "").strip()
    if not reason:
        _issue_once(
            issues,
            Issue("warning", f"[NEW] without a reason for {label} (line {lineno})"),
        )
        return
    if not DECISION_REF_RE.match(reason):
        notes.append(f"new: {label} — {reason} (line {lineno})")
        if decisions.table is not None and decisions.table.rows:
            _issue_once(
                issues,
                Issue(
                    "warning",
                    f"{decisions.table.source} has Technology decisions — reference the row as [NEW: D<n>] (line {lineno})",
                ),
            )
        return
    if decisions.table is None:
        if decisions.mission_id is None:
            _issue_once(
                issues,
                Issue(
                    "error",
                    f"[NEW: {reason}] needs a parent mission to hold the decision — add `> Parent mission: M-<slug>` under the title, or write [NEW: <reason>] (line {lineno})",
                    code=DECISION,
                ),
            )
        else:
            _issue_once(
                issues,
                Issue(
                    "error",
                    f"parent mission '{decisions.mission_id}' not found under missions/ or in the hub's plan — pass the mission (CLI --missions-dir, MCP mission_markdown), or write [NEW: <reason>] (line {lineno})",
                    code=DECISION,
                ),
            )
        return
    row = decisions.table.rows.get(reason)
    if row is None:
        _issue_once(
            issues,
            Issue(
                "error",
                f"decision {reason} not in {decisions.table.source}'s Technology decisions — append the row there first (line {lineno})",
                code=DECISION,
            ),
        )
        return
    if row.status.upper() == SUPERSEDED:
        successor = next(
            (r for r in decisions.table.rows.values() if r.supersedes == row.id), None
        )
        if successor is not None:
            _issue_once(
                issues,
                Issue(
                    "error",
                    f"decision {reason} is {SUPERSEDED} by {successor.id} — cite {successor.id} (line {lineno})",
                    code=DECISION,
                ),
            )
            return
    if row.status.upper() != "DECIDED":
        _issue_once(
            issues,
            Issue(
                "error",
                f"decision {reason} is {row.status} (owner: {row.owner or 'none'}) — a human decides before Dev (line {lineno})",
                code=DECISION,
            ),
        )
        return
    notes.append(
        f"new: {label} — {reason} (DECIDED, owner {row.owner or 'none'}) (line {lineno})"
    )


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def check(
    text: str,
    *,
    load_doc: LoadDoc,
    heading: str = HEADING,
    load_decisions: LoadDecisions | None = None,
    load_drift: LoadDrift | None = None,
    load_at: LoadAt | None = None,
    load_missions: LoadMissions | None = None,
) -> LintReport:
    issues: list[Issue] = []
    notes: list[str] = []
    # An SA that appends a second copy of the section instead of replacing
    # it leaves this gate reading the stale first copy — fail before that.
    duplicates = lintcore.check_duplicate_headings(text)
    if duplicates:
        return LintReport(duplicates, notes)
    section = _parse_section(text, heading)
    if section is None:
        issues.append(Issue("error", f"missing '{heading}' — run /sa-ticket-ground"))
        return LintReport(issues, notes)

    grounded = _grounded_on(section, heading, issues)
    if grounded is None:
        return LintReport(issues, notes)
    repo, doc_id, rev, line = grounded

    try:
        doc = load_doc(repo, doc_id)
    except DocLoadError as exc:
        issues.append(Issue("error", str(exc)))
        return LintReport(issues, notes)
    if doc is None:
        where = f"repo '{repo}'" if repo else "any repo"
        issues.append(
            Issue(
                "error",
                f"{doc_id} not found on the hub or under --kb-dir ({where}) — "
                "is the -code document published, and is the id spelled as "
                f"`<repo-id>-code`? (line {line})",
            )
        )
        return LintReport(issues, notes)
    notes.append(f"{doc_id} read from {doc.source}")
    decisions = _resolve_decisions(text, heading, load_decisions)

    have = (doc.manifest.revision or "").lower()
    moved = bool(have) and not (have.startswith(rev) or rev.startswith(have))
    _check_revision(doc_id, have, issues)
    start, notes_start = len(issues), len(notes)
    _check_ids(section, doc, decisions, issues, notes)
    _check_service_present(section, heading, issues)
    _check_open_decisions(section, issues)
    _check_tables_routes_commands(section, doc, issues)
    if heading != SERVICES_HEADING:
        _check_compose_facts(section, doc, decisions, issues, notes)

    @functools.cache
    def structure() -> _Structure:  # structure.raw.md: read and parsed at most once
        return _read_structure(doc)

    new_entries = _new_entries(section)
    _check_files(section, doc, decisions, issues, notes, structure)
    _judge_new_entries(new_entries, doc, decisions, issues, notes)
    _check_new_coverage(new_entries, doc, issues)
    own_mission = decisions.mission_id
    if heading == SERVICES_HEADING:
        m = mission.MISSION_LINE_RE.search(text)
        own_mission = m.group(1) if m else None
    _check_related_decisions(section, decisions, own_mission, load_missions, issues)
    _check_new_exists(
        new_entries, doc, issues, notes, moved, load_at, structure, repo, rev
    )
    if moved:
        fact_issues = issues[start:]
        skipped = any(i.code == UNVERIFIED for i in fact_issues) or any(
            _COMPOSE_SKIP_NOTE in n for n in notes[notes_start:]
        )
        _judge_drift(
            doc,
            repo,
            doc_id,
            rev,
            have,
            load_drift,
            fact_issues,
            skipped,
            issues,
            notes,
        )
    return LintReport(issues, notes)


def _judge_drift(
    doc: LoadedDoc,
    repo: str | None,
    doc_id: str,
    rev: str,
    have: str,
    load_drift: LoadDrift | None,
    fact_issues: list[Issue],
    skipped: bool,
    issues: list[Issue],
    notes: list[str],
) -> None:
    """The ticket is grounded on an older revision than the document's:
    the fact checks already ran against the current document — judge them."""
    try:
        drift = load_drift(repo, doc_id, rev) if load_drift is not None else None
    except (KbError, OSError, ValueError):
        # No baseline, not a failure: KbError incl. gitio.GitError, plus what
        # drift_refs can raise past it (OSError; ValueError incl. UnicodeDecodeError).
        drift = None

    def current_section(sid: str) -> str | None:
        group = next((s.file for s in doc.manifest.sections if s.id == sid), None)
        text = doc.read_group(group) if group is not None else None
        return slice_section(text, sid) if text is not None else None

    new_issues, new_notes = groundingdrift.judge(
        doc_id,
        rev,
        have,
        drift,
        current_section,
        fact_issues,
        local_fallback="local fallback" in doc.source,
        skipped=skipped,
    )
    issues.extend(new_issues)
    notes.extend(new_notes)


def _grounded_on(
    section: _Section, heading: str, issues: list[Issue]
) -> tuple[str | None, str, str, int] | None:
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] != "Grounded on" or line[:1].isspace():
            continue
        lineno = section.first_line + i
        if heading == SERVICES_HEADING:
            # Mission section: the SA may list several `<repo>:<doc> @ <rev>`
            # entries on one line (the -code and -svc docs); ground on the
            # -code entry, else the first — same rule as missionnext.grounded_doc.
            entries = grounded_entries(line)
            if not entries:
                issues.append(
                    Issue(
                        "error",
                        "'Grounded on:' must read `Grounded on: <repo-id>:<doc-id> @ "
                        f"<revision>` (revision = the -code manifest's `revision`) "
                        f"(line {lineno})",
                    )
                )
                return None
            repo, doc, rev = next(
                (e for e in entries if e[1].endswith("-code")), entries[0]
            )
            return repo, doc, rev, lineno
        m = GROUNDED_ON_RE.match(line.strip())
        if m is None:
            issues.append(
                Issue(
                    "error",
                    "'Grounded on:' must read `Grounded on: <repo-id>:<doc-id> @ "
                    f"<revision>` (revision = the -code manifest's `revision`) "
                    f"(line {lineno})",
                )
            )
            return None
        return m.group("repo"), m.group("doc"), m.group("rev").lower(), lineno
    issues.append(
        Issue(
            "error",
            "missing 'Grounded on: <repo-id>:<doc-id> @ <revision>' — the first "
            "line of the section; copy the revision from the -code manifest",
        )
    )
    return None


def _check_revision(doc_id: str, have: str, issues: list[Issue]) -> None:
    if not have:
        issues.append(
            Issue(
                "warning",
                f"{doc_id} has no revision in its manifest — grounding revision not verified",
            )
        )


def _known_ids(doc: LoadedDoc) -> set[str]:
    return {s.id for s in doc.manifest.sections}


def _id_lines(section: _Section):
    """(lineno, line) for every visible line that is scanned for ids — the
    `Grounded on:` line (a doc id, not a section id) and `Files:` lines
    (paths such as `src/api.py` would read as `api.py`) are skipped. On a
    `Healthchecks` line, every `svc.<x> — <value>` value is blanked —
    backticked or bare, matching both forms `_split_values` accepts — so a
    URL or command inside it (`curl -f http://api.internal/health`) is never
    read as a section id; the `svc.<x>` id itself stays visible, and any
    `[NEW: …]` marker in the value survives the blanking so `_check_ids`
    still sees it."""
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] in ("Grounded on", "Files"):
            continue
        if section.field_of_line[i] == "Healthchecks":
            line = _COMPOSE_GROUP_RE.sub(
                lambda m: (
                    m.string[m.start() : m.start("values")]
                    + " ".join(n.group(0) for n in NEW_RE.finditer(m.group("values")))
                ),
                line,
            )
        if line.strip():
            yield section.first_line + i, line


def _check_ids(
    section: _Section,
    doc: LoadedDoc,
    decisions: _Decisions,
    issues: list[Issue],
    notes: list[str],
) -> None:
    known = _known_ids(doc)
    for lineno, line in _id_lines(section):
        new = NEW_RE.search(line)
        for raw in ID_RE.findall(line):
            sid = raw.rstrip(".")
            if sid in known:
                continue
            # db.<table>.<column>: the table half is the section id.
            if sid.startswith("db.") and sid.count(".") >= 2:
                table = sid.rsplit(".", 1)[0]
                if table in known:
                    if new is None:
                        continue  # the column was verified above
                    # else: fall through with sid = full column id so the
                    # [NEW] branch below can note/warn on it.
                else:
                    sid = table
            if new is not None:
                _judge_new(sid, new, lineno, decisions, issues, notes)
                continue
            issues.append(
                Issue(
                    "error",
                    f"unknown id '{sid}' — not a section of {doc.manifest.id}; copy the "
                    f"id from the document or mark the line [NEW: <reason>] (line {lineno})",
                )
            )


def _check_service_present(
    section: _Section, heading: str, issues: list[Issue]
) -> None:
    if heading == SERVICES_HEADING:
        return  # the mission table has no `- Service:` line by design
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Service" and any(
            sid.startswith("svc.") for sid in ID_RE.findall(line)
        ):
            return
    issues.append(
        Issue(
            "warning",
            "no `svc.<name>` on the `Service:` line — which service does this ticket touch?",
        )
    )


def _check_open_decisions(section: _Section, issues: list[Issue]) -> None:
    items: list[tuple[int, str]] = list(section.subitems.get("Open decisions", []))
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Open decisions" and not line[:1].isspace():
            m = FIELD_RE.match(line)
            if m is not None and m.group("rest").strip():
                items.insert(0, (section.first_line + i, m.group("rest").strip()))
    open_items = [(n, t) for n, t in items if t.strip().casefold() not in _NONE_WORDS]
    for lineno, item in open_items:
        issues.append(
            Issue("error", f"open decision: {item} (line {lineno})", code=DECISION)
        )
    if open_items:
        issues.append(
            Issue(
                "error",
                f"{len(open_items)} open decision(s) — resolve before Dev",
                code=DECISION,
            )
        )


def _l2_slice(
    doc: LoadedDoc, sid: str, unreadable: set[str], issues: list[Issue]
) -> str | None:
    """The `## <sid> …` L2 section text, or None — memoised in `unreadable`
    (by group stem for an unreadable file, by `sid` for a missing heading;
    the two id shapes never collide) so either failure warns once, not
    once per line that references it, and the sub-check is skipped."""
    group = next((s.file for s in doc.manifest.sections if s.id == sid), None)
    if group is None or group in unreadable or sid in unreadable:
        return None
    text = doc.read_group(group)
    if text is None:
        unreadable.add(group)
        issues.append(
            Issue(
                "warning",
                f"could not read {group}.md of {doc.manifest.id} — column/route/command checks for its sections skipped",
                code=UNVERIFIED,
            )
        )
        return None
    body = slice_section(text, sid)
    if body is None:
        unreadable.add(sid)
        issues.append(
            Issue(
                "warning",
                f"section {sid} not found in {group}.md of {doc.manifest.id} — its column/route/command checks skipped",
                code=UNVERIFIED,
            )
        )
    return body


_table_column = lintcore.table_column

# Job names the extractors emit when the real name is not recoverable; they
# can repeat in one section and must never match a cited name.
_PLACEHOLDER_NAMES = frozenset({"(anonymous)", "(dynamic)", "(exec)", "(unnamed)"})
MIDDLEWARE_PREFIX = "Middleware matcher:"
# A route parameter in any of the supported frameworks' spellings.
_PARAM_RE = re.compile(
    r"\{[^{}/]*\}|<[^<>/]*>|\[{1,2}[^\[\]/]*\]{1,2}|(?<=/):[A-Za-z_]\w*"
)
# A path in prose: starts with `/`, not glued to a word (`apps/web` is not one).
_CITED_PATH_RE = re.compile(r"(?<![\w/.\-])(/[^\s`,;]*)")
# A dash separator: an em/en dash, or hyphens followed by a space (`-`, `--`) --
# never the leading `--` of a CSS custom property.
_SEPARATOR_RE = re.compile(r"^\s*(?:[—–]|-+(?=\s))+\s*")
_FIELD_PREFIX_RE = re.compile(r"^\s*-\s*(?:[A-Za-z][A-Za-z ]*?:)?")


def normalise_path(p: str) -> str:
    """A route/page path with every parameter (`:id`, `{id}`, `{id:int}`,
    `<int:id>`, `<id>`, `[id]`, `[...slug]`) spelled `{}` and a trailing `/`
    dropped (except at the root), so framework spellings compare equal."""
    return _PARAM_RE.sub("{}", p).rstrip("/") or "/"


def _table_values(body: str, *columns: str) -> list[tuple[str, ...]]:
    """The named columns of every data row of `body`'s table(s), header-name
    addressed; rows too short for a column are dropped."""
    rows = lintcore.table_rows(body)
    idx = [_table_column(rows, c) for c in columns]
    if any(i is None for i in idx):
        return []
    cols = [i for i in idx if i is not None]
    return [tuple(r[i] for i in cols) for r in rows[1:] if len(r) > max(cols)]


def _route_keys(body: str) -> dict[tuple[str, str], str]:
    """`(METHOD, normalised path)` -> `METHOD path` as the document spells it."""
    return {
        (m.upper(), normalise_path(p)): f"{m.upper()} {p}"
        for m, p in _table_values(body, "method", "path")
    }


def _page_keys(body: str) -> dict[str, str]:
    """normalised page path -> the path as written; the middleware-matcher
    row is not a page."""
    return {
        normalise_path(p): p
        for (p,) in _table_values(body, "path")
        if not p.startswith(MIDDLEWARE_PREFIX)
    }


def _name_keys(body: str) -> dict[str, str]:
    return {n: n for (n,) in _table_values(body, "name") if n not in _PLACEHOLDER_NAMES}


def _id_segments(line: str) -> tuple[str, list[tuple[str, str]]]:
    """`(preamble, [(id, segment)])`: the line split at EVERY section id
    occurrence; the text before the first id is the preamble, each later
    stretch belongs to the id that starts it."""
    ms = list(ID_RE.finditer(line))
    if not ms:
        return line, []
    segments = [
        (
            m.group(0).rstrip("."),
            line[m.end() : ms[i + 1].start() if i + 1 < len(ms) else None],
        )
        for i, m in enumerate(ms)
    ]
    return line[: ms[0].start()], segments


def _unattached_citation(first_id: str, preamble: str) -> str | None:
    """The citation written before the line's first id (so owned by none), judged
    by the kind of that id: a route for `api.`/`route.`, a path for `page.`, a
    backticked name for `job.`/`sym.`; None when there is none."""
    text = _FIELD_PREFIX_RE.sub("", preamble, count=1)
    if first_id.startswith(("api.", "route.")):
        m = ROUTE_RE.search(text)
        return f"{m.group(1)} {m.group(2).rstrip('.,;:)`')}" if m else None
    if first_id.startswith("page."):
        m = _CITED_PATH_RE.search(text)
        return m.group(1).rstrip(".,;:)`") if m else None
    if first_id.startswith(("job.", "sym.")):
        m = CODE_SPAN_RE.search(text)
        return m.group(1).strip() if m else None
    return None


def _cited_name(text: str) -> str:
    """The name a `job.*`/`sym.*` line cites: its first code span, else the
    first word after the dash."""
    span = CODE_SPAN_RE.search(text)
    if span:
        return span.group(1).strip()
    words = _SEPARATOR_RE.sub("", text).split()
    return words[0].rstrip(".,;:") if words else ""


def _split_items(text: str) -> list[str]:
    """Split at commas outside backticks and parentheses."""
    items: list[str] = []
    depth, ticks, start = 0, False, 0
    for i, ch in enumerate(text):
        if ch == "`":
            ticks = not ticks
        elif ticks:
            continue
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            items.append(text[start:i])
            start = i + 1
    items.append(text[start:])
    return items


def _cited_names(text: str) -> list[str]:
    """Every name a `job.*`/`sym.*` segment cites: the first item as
    `_cited_name` reads it, each later comma item only when it is one token or
    a code span (an item with spaces is prose, never a name)."""
    names: list[str] = []
    for n, item in enumerate(_split_items(text)):
        if n and not CODE_SPAN_RE.search(item):
            item = _SEPARATOR_RE.sub("", item).strip().rstrip(".,;:")
            if not item or " " in item:
                continue
        if name := _cited_name(item):
            names.append(name)
    return names


def _check_route_citation(
    sid: str,
    text: str,
    lineno: int,
    doc: LoadedDoc,
    unreadable: set[str],
    issues: list[Issue],
) -> None:
    pairs = ROUTE_RE.findall(text)
    if not pairs:
        return
    body = _l2_slice(doc, sid, unreadable, issues)
    if body is None:
        return
    keys = _route_keys(body)
    valid = ", ".join(sorted(keys.values())) or "no routes"
    for method, path in pairs:
        path = path.rstrip(".,;:)`")
        if (method.upper(), normalise_path(path)) not in keys:
            issues.append(
                Issue(
                    "error",
                    f"route '{method} {path}' is not in {sid} — copy a row of its table ({valid}) (line {lineno})",
                )
            )


def _check_listed_citation(
    sid: str,
    text: str,
    lineno: int,
    doc: LoadedDoc,
    unreadable: set[str],
    issues: list[Issue],
) -> None:
    """`page.*` -> the cited path(s), `job.*` / `sym.*` -> the cited name,
    against the section's Path / Name column."""
    kind = sid.split(".", 1)[0]
    if kind == "page":
        cited = [p.rstrip(".,;:)`") for p in _CITED_PATH_RE.findall(text)]
    else:
        cited = _cited_names(text)
    if not cited:
        return
    body = _l2_slice(doc, sid, unreadable, issues)
    if body is None:
        return
    keys = _page_keys(body) if kind == "page" else _name_keys(body)
    valid = ", ".join(sorted(keys.values())) or "none"
    noun, column = {"page": ("page", "Path"), "job": ("job", "Name")}.get(
        kind, ("symbol", "Name")
    )
    for name in cited:
        if (normalise_path(name) if kind == "page" else name) not in keys:
            issues.append(
                Issue(
                    "error",
                    f"{noun} '{name}' is not in {sid} — copy a {column} of its table ({valid}) (line {lineno})",
                )
            )


_LISTED_PREFIXES = ("api.", "route.", "page.", "job.", "sym.")


def _cites_listed(text: str, known: set[str]) -> bool:
    """True when `text` cites an existing route/page/job/symbol section id."""
    return any(
        (sid := m.rstrip(".")) in known and sid.startswith(_LISTED_PREFIXES)
        for m in ID_RE.findall(text)
    )


def _mixes_new_with_citation(text: str, known: set[str]) -> bool:
    """A `[NEW]` line that also cites a listed id -- an error only for a
    document with `struct.coverage`; tickets grounded before it keep passing."""
    return "struct.coverage" in known and _cites_listed(text, known)


def _check_tables_routes_commands(
    section: _Section, doc: LoadedDoc, issues: list[Issue]
) -> None:
    known = _known_ids(doc)
    unreadable: set[str] = set()
    for lineno, line in _id_lines(section):
        if NEW_RE.search(line):
            if _mixes_new_with_citation(line, known):
                issues.append(
                    Issue(
                        "error",
                        f"a line cannot cite an id and carry [NEW] — put the [NEW] item on its own sub-bullet (line {lineno})",
                    )
                )
            continue
        preamble, segments = _id_segments(line)
        if segments:
            stray = _unattached_citation(segments[0][0], preamble)
            if stray is not None:
                issues.append(
                    Issue(
                        "error",
                        f"citation '{stray}' is not attached to a section id — write `<id> — <citation>` (line {lineno})",
                    )
                )
        for raw, segment in segments:
            # db.<table>.<column>
            if raw.startswith("db.") and raw.count(".") >= 2 and raw not in known:
                table, column = raw.rsplit(".", 1)
                if table not in known:
                    continue  # reported by _check_ids
                body = _l2_slice(doc, table, unreadable, issues)
                if body is None:
                    continue
                rows = lintcore.table_rows(body)
                col = _table_column(rows, "column")
                names = {r[col] for r in rows[1:] if col is not None and len(r) > col}
                if column not in names:
                    issues.append(
                        Issue(
                            "error",
                            f"column '{column}' is not in {table} ({', '.join(sorted(names)) or 'no columns'}) (line {lineno})",
                        )
                    )
            # api.<tag> / route.<slug> — METHOD /path
            elif raw.startswith(("api.", "route.")) and raw in known:
                _check_route_citation(raw, segment, lineno, doc, unreadable, issues)
            # page.<slug> — /path, job.<slug> — name, sym.<slug> — Name
            elif raw.startswith(("page.", "job.", "sym.")) and raw in known:
                _check_listed_citation(raw, segment, lineno, doc, unreadable, issues)
            # cmd.<x> — `command`
            elif raw.startswith("cmd.") and raw in known:
                spans = CODE_SPAN_RE.findall(line)
                if not spans:
                    issues.append(
                        Issue(
                            "warning",
                            f"{raw}: put the command in backticks so it can be verified (line {lineno})",
                            code=UNVERIFIED,
                        )
                    )
                    continue
                body = _l2_slice(doc, raw, unreadable, issues)
                if body is None:
                    continue
                allowed: set[str] = set()
                m = PRIMARY_RE.search(body)
                if m:
                    allowed.add(m.group(1))
                rows = lintcore.table_rows(body)
                ci = _table_column(rows, "command")
                allowed |= {r[ci] for r in rows[1:] if ci is not None and len(r) > ci}
                if not any(s in allowed for s in spans):
                    found = ", ".join(f"`{s}`" for s in spans)
                    issues.append(
                        Issue(
                            "error",
                            f"command not in {raw} — copy the primary or an alternative verbatim (found: {found}; allowed: {', '.join(sorted(allowed))}) (line {lineno})",
                        )
                    )


def _service_ids(section: _Section) -> set[str]:
    ids: set[str] = set()
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Service":
            ids |= {s for s in ID_RE.findall(line) if s.startswith("svc.")}
    return ids


def _field_lines(section: _Section, name: str) -> list[tuple[int, str]]:
    """(lineno, rest) for the `- <name>: <rest>` line plus its sub-bullets."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == name and not line[:1].isspace():
            m = FIELD_RE.match(line)
            if m is not None and m.group("rest").strip():
                out.append((section.first_line + i, m.group("rest").strip()))
    out += section.subitems.get(name, [])
    return out


# A `|` not preceded by `\` -- the same split `lintcore.table_rows` uses.
_ESCAPED_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")


def _property(body: str, name: str) -> str | None:
    """The `Value` cell of the L2 property row named `name`, pipes unescaped.

    Re-splits each raw `| Property | Value |` line itself on escape-aware
    `|` boundaries (an `escape_cell`-escaped `\\|` inside the Value cell, e.g.
    a `CMD-SHELL "... | ..."` healthcheck, stays in the cell).
    """
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in _ESCAPED_CELL_SPLIT_RE.split(line[1:-1])]
        if len(cells) >= 2 and cells[0] == name:
            return cells[1].replace("\\|", "|")
    return None


def _svc_facts(
    doc: LoadedDoc,
    sid: str,
    field: str,
    unreadable: set[str],
    issues: list[Issue],
    row_absent: set[str],
) -> set[str] | None:
    """The svc's values for one compose field as a set: `{"pgdata"}`,
    `{"curl -f …"}`, `set()` for `none`. None when the section is unreadable
    or missing (`_l2_slice` already warned about that) or when its L2
    section has no `field` property row at all — the pre-1.3.0 code-ingest
    case, which adds `sid` to `row_absent` to trigger the caller's one
    document-scoped note (its text is not per-sid; do not read it as one).
    Callers must not call this for a `sid` outside the document's manifest —
    that's a different failure (an unresolved or `[NEW]` id), already
    reported by `_check_ids`."""
    body = _l2_slice(doc, sid, unreadable, issues)
    if body is None:
        return None
    cell = _property(body, _COMPOSE_ROW[field])
    if cell is None:
        row_absent.add(sid)
        return None
    if cell.casefold() == "none":
        return set()
    if field == "Healthchecks":
        return {cell}
    return {v.strip() for v in cell.split(",") if v.strip()}


def _split_values(field: str, raw: str) -> list[str]:
    raw = raw.strip()
    if field == "Healthchecks":
        spans = CODE_SPAN_RE.findall(raw)
        return spans if spans else [raw]
    return [v.strip().strip("`") for v in raw.split(",") if v.strip()]


def _check_compose_facts(
    section: _Section,
    doc: LoadedDoc,
    decisions: _Decisions,
    issues: list[Issue],
    notes: list[str],
) -> None:
    present = [f for f in COMPOSE_FIELDS if _field_lines(section, f)]
    if len(present) < len(COMPOSE_FIELDS):
        issues.append(
            Issue(
                "warning",
                "Volumes:/Healthchecks:/Devices: lines missing — re-ground on a -code revision that carries them",
                code=UNVERIFIED,
            )
        )
    if not present:
        return
    services = _service_ids(section)
    known = _known_ids(doc)
    unreadable: set[str] = set()
    row_absent: set[str] = set()
    for field in present:
        for lineno, rest in _field_lines(section, field):
            noun = _COMPOSE_NOUN[field]
            if rest.strip().casefold() in _NONE_WORDS:
                for sid in sorted(services):
                    if sid not in known:
                        continue  # not in this document (e.g. a [NEW] service) — _check_ids already reported it
                    facts = _svc_facts(doc, sid, field, unreadable, issues, row_absent)
                    if facts:
                        issues.append(
                            Issue(
                                "warning",
                                f"{sid} has {noun}s the grounding omits: {', '.join(sorted(facts))} (line {lineno})",
                            )
                        )
                continue
            matches = list(_COMPOSE_GROUP_RE.finditer(rest))
            if not matches:
                issues.append(
                    Issue(
                        "warning",
                        f"{field}: line does not parse — expected `svc.<name> — <values>` (got: {rest}) (line {lineno})",
                        code=UNVERIFIED,
                    )
                )
                continue
            for g in matches:
                sid = g.group(1).rstrip(".")
                if sid not in services:
                    issues.append(
                        Issue(
                            "error",
                            f"{sid} on the {field}: line is not on the Service: line (line {lineno})",
                        )
                    )
                    continue
                if sid not in known:
                    continue  # not in this document (e.g. a [NEW] service) — _check_ids already reported it
                facts = _svc_facts(doc, sid, field, unreadable, issues, row_absent)
                if facts is None:
                    continue
                values_raw = g.group("values")
                if values_raw.strip().casefold() in _NONE_WORDS:
                    if facts:
                        issues.append(
                            Issue(
                                "error",
                                f"{noun} for {sid} is '{', '.join(sorted(facts))}', not 'none' (line {lineno})",
                            )
                        )
                    continue
                # A Healthchecks `[NEW: …]` marker sits outside the backtick
                # span, so `_split_values` never returns it as part of
                # `value` — search the whole group's raw text for it too.
                # Only fall back to it for a single-value group: with two+
                # values on one line (`` `x`, `y` [NEW: D1]``) the marker
                # sits on one of them, not on both, and `_split_values` has
                # no way to say which — spreading it to every value would
                # exempt values the marker was never written for.
                split_values = _split_values(field, values_raw)
                raw_new = (
                    NEW_RE.search(values_raw)
                    if field == "Healthchecks" and len(split_values) == 1
                    else None
                )
                for value in split_values:
                    new = NEW_RE.search(value) or raw_new
                    if new is not None:
                        _judge_new(
                            NEW_RE.sub("", value).strip(),
                            new,
                            lineno,
                            decisions,
                            issues,
                            notes,
                        )
                        continue
                    if value in facts:
                        continue
                    have = ", ".join(sorted(facts)) or "none"
                    if field == "Healthchecks":
                        issues.append(
                            Issue(
                                "error",
                                f"healthcheck for {sid} is '{have}', not '{value}' (line {lineno})",
                            )
                        )
                    else:
                        issues.append(
                            Issue(
                                "error",
                                f"{noun} '{value}' is not in {sid} (has: {have}) (line {lineno})",
                            )
                        )
    if row_absent:
        notes.append(
            f"{doc.manifest.id} has no Volumes/Healthcheck/Devices rows (pre-1.3.0 code-ingest) — compose-fact checks skipped"
        )


def _tree_paths(l3_text: str) -> tuple[set[str], str | None]:
    """(every path listed in struct.tree's fence, first entry dropped by the
    line cap or None). Directory lines end with `/` and carry their full
    relative path; a file line's directory is the nearest preceding
    directory line with a smaller indent (root files have none)."""
    paths: set[str] = set()
    first_dropped: str | None = None
    stack: list[tuple[int, str]] = []
    in_fence = False
    for raw in l3_text.splitlines():
        if raw.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            continue
        cap = TREE_CAP_RE.match(raw)
        if cap:
            first_dropped = cap.group("first")
            continue
        m = re.match(r"^( *)- (.+)$", raw)
        if not m:
            continue
        indent, name = len(m.group(1)), m.group(2)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        if name.endswith("/"):
            d = name[:-1]
            stack.append((indent, d))
            paths.add(d)
        else:
            parent = stack[-1][1] if stack else ""
            paths.add(f"{parent}/{name}" if parent else name)
    return paths, first_dropped


FILES_HEADING_RE = re.compile(r"^## (?P<sid>struct\.files\.\S+)")


def _files_by_section(l3_text: str) -> dict[str, set[str]]:
    """The paths of each `struct.files.*` fence of one raw group file, keyed
    by section id: one full repo-relative path per line, no cap."""
    out: dict[str, set[str]] = {}
    current: str | None = None
    in_fence = False
    for raw in l3_text.splitlines():
        if raw.startswith("```"):
            in_fence = not in_fence
        elif in_fence:
            if current is not None and raw:
                out[current].add(raw)
        elif raw.startswith("## "):
            m = FILES_HEADING_RE.match(raw)
            current = m.group("sid") if m else None
            if current is not None:
                out.setdefault(current, set())
    return out


def _files_groups(doc: LoadedDoc) -> list[str]:
    return sorted(
        {s.file for s in doc.manifest.sections if s.id.startswith("struct.files.")}
    )


@dataclass(frozen=True)
class _Structure:
    """What `structure.raw.md` can vouch for, read and parsed once."""

    tree: set[str]  # struct.tree's listed paths
    paths: set[str]  # tree + struct.files.* + every directory prefix
    owners: dict[str, str]  # struct.files.* path -> its section id
    first_dropped: str | None  # first struct.tree entry lost to the line cap
    complete: bool  # struct.files.* present: absence is provable
    group: str | None  # the struct.tree group stem
    tree_readable: bool


def _read_structure(doc: LoadedDoc) -> _Structure:
    raws: dict[str, str | None] = {}

    def raw(group: str) -> str | None:
        if group not in raws:
            raws[group] = doc.read_raw(group)
        return raws[group]

    tree_group = next(
        (s.file for s in doc.manifest.sections if s.id == "struct.tree"), None
    )
    tree_raw = raw(tree_group) if tree_group else None
    tree, first_dropped = (
        _tree_paths(tree_raw) if tree_raw is not None else (set(), None)
    )
    owners: dict[str, str] = {}
    groups = _files_groups(doc)
    for group in groups:
        text = raw(group)
        if text is None:
            continue
        for sid, listed in _files_by_section(text).items():
            for path in listed:
                owners.setdefault(path, sid)
    paths = tree | owners.keys()
    for path in list(paths):
        parts = path.split("/")
        paths.update("/".join(parts[:i]) for i in range(1, len(parts)))
    return _Structure(
        tree=tree,
        paths=paths,
        owners=owners,
        first_dropped=first_dropped,
        complete=bool(groups),
        group=tree_group,
        tree_readable=tree_raw is not None,
    )


def _check_files(
    section: _Section,
    doc: LoadedDoc,
    decisions: _Decisions,
    issues: list[Issue],
    notes: list[str],
    structure: Callable[[], _Structure],
) -> None:
    entries = list(section.subitems.get("Files", []))
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Files" and not line[:1].isspace():
            m = FIELD_RE.match(line)
            if m is not None and m.group("rest").strip():
                entries.insert(0, (section.first_line + i, m.group("rest").strip()))
    if not entries:
        return
    struct = structure()
    if not struct.tree_readable:
        issues.append(
            Issue(
                "warning",
                f"could not read {struct.group or 'structure'}.raw.md of {doc.manifest.id} — file checks skipped",
                code=UNVERIFIED,
            )
        )
        return
    paths = struct.paths
    # struct.files.* lists every file, so a path missing from the union is
    # provably absent however deep it is or however capped struct.tree is.
    complete = struct.complete
    first_dropped = struct.first_dropped
    for lineno, text in entries:
        new = NEW_RE.search(text)
        path = NEW_RE.sub("", text).strip().strip("`").rstrip("/")
        if new is not None and _IN_RE.search(path):
            issues.append(
                Issue(
                    "error",
                    f"a Files entry is its own path — write `{_IN_RE.split(path)[-1].strip()} [NEW: D<n>]`, not '<thing> in <path>' (line {lineno})",
                )
            )
            continue
        if new is not None:
            _judge_new(path, new, lineno, decisions, issues, notes)
            continue
        if path in paths:
            continue
        if not complete and path.count("/") >= TREE_DEPTH:
            issues.append(
                Issue(
                    "warning",
                    f"cannot verify '{path}': beyond struct.tree's depth cap ({TREE_DEPTH}) — list the deepest directory the document shows (line {lineno})",
                    code=UNVERIFIED,
                )
            )
        elif not complete and first_dropped is not None:
            # ponytail: the cap marker names a bare file name, so "does this
            # path sort after the cut" is not decidable from the document;
            # a capped tree makes every absent path unverifiable, never an
            # error. Upgrade path: a full-path marker in tree.py's renderer.
            issues.append(
                Issue(
                    "warning",
                    f"cannot verify '{path}': struct.tree hit its line cap (listing stops at '{first_dropped}') — the document cannot prove absence (line {lineno})",
                    code=UNVERIFIED,
                )
            )
        else:
            where = "struct.tree or struct.files" if complete else "struct.tree"
            issues.append(
                Issue(
                    "error",
                    f"file '{path}' not in {where} of {doc.manifest.id} — spell it as the document lists it, or mark [NEW: <reason>] (line {lineno})",
                )
            )


# ---------------------------------------------------------------------------
# [NEW] route / page / job / symbol / file: judged, coverage-gated, existence
# ---------------------------------------------------------------------------

_NEW_AREA = {
    "Tables": "schema",
    "Routes": "routes",
    "Pages": "pages",
    "Jobs": "jobs",
    "Symbols": "symbols",
    "Files": "files",
}
_NEW_NOUN = {
    "Tables": "index",
    "Routes": "route",
    "Pages": "page",
    "Jobs": "job",
    "Symbols": "symbol",
    "Files": "file",
}
_LISTING_PREFIXES = {
    "Routes": ("route.", "api."),
    "Pages": ("page.",),
    "Jobs": ("job.",),
    "Symbols": ("sym.",),
}
_NOT_SCANNED = "not scanned"
_PARTIAL = "partial"
_COMPLETE = "complete"
_STATUS_RANK = {_COMPLETE: 0, _PARTIAL: 1, _NOT_SCANNED: 2}
_IN_RE = re.compile(r"\s+in\s+")
# A `Tables:` [NEW] is gated only when it adds an index, a partition or a
# primary key; a whole new table or a new column keeps the ungated rule.
_SCHEMA_NEW_RE = re.compile(r"\b(?:index(?:es)?|partition|primary key)\b", re.I)


@dataclass(frozen=True)
class _NewEntry:
    field: str  # Tables | Routes | Pages | Jobs | Symbols | Files
    lineno: int
    text: str  # the field line / sub-bullet as written
    thing: str  # what is new, no code-span backticks: `GET /x`, `/page`, a name, a path
    target: str | None  # the repo-relative file it will live in
    marker: re.Match[str]


def _split_target(clean: str) -> tuple[str, str | None]:
    """`<thing> in <path>` -> (thing, path); no ` in ` or no path -> (clean, None)."""
    parts = _IN_RE.split(clean)
    if len(parts) < 2:
        return clean, None
    head, tail = " in ".join(parts[:-1]).strip(), parts[-1].strip()
    span = CODE_SPAN_RE.search(tail)
    words = [span.group(1).strip()] if span else tail.split()
    path = words[0].rstrip(".,;:)").removeprefix("./") if words else ""
    return head, path or None


def _new_entries(section: _Section) -> list[_NewEntry]:
    out: list[_NewEntry] = []
    for field in _NEW_AREA:
        for lineno, text in _field_lines(section, field):
            marker = NEW_RE.search(text)
            if marker is None:
                continue
            clean = NEW_RE.sub("", text).strip()
            if field == "Files":
                path = clean.strip("`").rstrip("/")
                if _IN_RE.search(path):
                    continue  # reported by _check_files
                out.append(_NewEntry(field, lineno, text, path, path, marker))
                continue
            thing, target = _split_target(clean)
            if field == "Tables" and not _SCHEMA_NEW_RE.search(ID_RE.sub("", thing)):
                continue
            thing = (
                _cited_name(thing) or thing
                if field in ("Jobs", "Symbols")
                else thing.replace("`", "")
            )
            out.append(_NewEntry(field, lineno, text, thing, target, marker))
    return out


def _judge_new_entries(
    entries: list[_NewEntry],
    doc: LoadedDoc,
    decisions: _Decisions,
    issues: list[Issue],
    notes: list[str],
) -> None:
    """Judge the `[NEW: …]` marker of a Tables/Routes/Pages/Jobs/Symbols line. `Files`
    lines are judged by `_check_files`; a line carrying an unknown section id is
    judged by `_check_ids`."""
    known = _known_ids(doc)
    for e in entries:
        if e.field == "Files":
            continue
        if any(sid.rstrip(".") not in known for sid in ID_RE.findall(e.text)):
            continue
        if _mixes_new_with_citation(e.text, known):
            continue  # reported once by _check_tables_routes_commands
        _judge_new(e.thing, e.marker, e.lineno, decisions, issues, notes)


@dataclass(frozen=True)
class _CovRow:
    framework: str  # the Framework/language cell
    status: str


def _rank(row: _CovRow) -> int:
    return _STATUS_RANK.get(row.status, 1)


def _coverage(
    doc: LoadedDoc, issues: list[Issue]
) -> dict[str, dict[str, list[_CovRow]]] | None:
    """`{area: {scope: rows}}` from `struct.coverage`; None for a pre-release
    document (no such section) or one that cannot be read."""
    if "struct.coverage" not in _known_ids(doc):
        return None
    body = _l2_slice(doc, "struct.coverage", set(), issues)
    if body is None:
        return None
    out: dict[str, dict[str, list[_CovRow]]] = {}
    for area, scope, framework, status in _table_values(
        body, "area", "scope", "framework/language", "status"
    ):
        out.setdefault(area, {}).setdefault(scope, []).append(
            _CovRow(framework, status)
        )
    return out


def _scope_status(
    cov: dict[str, dict[str, list[_CovRow]]], area: str, path: str
) -> tuple[str, str, str]:
    """`(scope label, status, deciding framework/language)` for `path`. `files`
    scopes are top-level directories (`.` for root files). The other areas use
    package scopes: the deepest scope listed for ANY of them (`jobs` and
    `symbols` list every package) that prefixes the path -- an adapter reads a
    file only through its nearest package, so a nested package with no row for
    `area` was never scanned for it, whatever an ancestor says. No row = `not
    scanned`, labelled with the scope (the path when only `.` covers it). A
    scope with several rows for the area is judged by the row whose language
    matches the file's, else by its worst row; the deciding framework is
    returned only then."""
    scopes = cov.get(area, {})
    if area == "files":
        top = path.split("/")[0] if "/" in path else "."
        if top not in scopes:
            return top, _NOT_SCANNED, ""
        best = top
    else:
        listed = {s for a, rows in cov.items() if a != "files" for s in rows}
        covering = [
            s for s in listed if s == "." or path == s or path.startswith(f"{s}/")
        ]
        if not covering:
            return path, _NOT_SCANNED, ""
        best = max(covering, key=len)
        if best not in scopes:
            return (path if best == "." else best), _NOT_SCANNED, ""
    rows = scopes[best]
    language = LANG_BY_SUFFIX.get(posixpath.splitext(path)[1].lower())
    matching = [r for r in rows if language and r.framework.lower() == language]
    deciding = max(matching or rows, key=_rank)
    framework = (
        deciding.framework if len(rows) > 1 and deciding.framework != "-" else ""
    )
    return best, deciding.status, framework


def _check_new_coverage(
    entries: list[_NewEntry], doc: LoadedDoc, issues: list[Issue]
) -> None:
    """A `[NEW]` route/page/job/symbol/file is only believable when the code
    scan of its scope was complete -- otherwise the thing may already exist
    where the scan could not see. Jobs never complete, so a new job is always
    refused. A document without `struct.coverage` (pre-release) is not gated,
    except for Jobs."""
    if not entries:
        return
    cov = _coverage(doc, issues)
    known = _known_ids(doc)
    for e in entries:
        if cov is None and e.field != "Jobs":
            continue
        if e.field == "Tables" and _names_unknown_table(e.text, known):
            continue  # an index of a whole new table: the table's own [NEW] rule
        if e.target is None:
            issues.append(
                Issue(
                    "error",
                    f"[NEW] in {e.field} must name the file it will live in (… in <path> [NEW: D<n>]) (line {e.lineno})",
                    code=DECISION,
                )
            )
            continue
        area = _NEW_AREA[e.field]
        scope, status, framework = _scope_status(cov or {}, area, e.target)
        if e.field == "Jobs" and (cov is None or status == _COMPLETE):
            status = _PARTIAL
        if status != _COMPLETE:
            what = f"{area}, {framework}" if framework else area
            issues.append(
                Issue(
                    "error",
                    f"cannot claim new: coverage of {scope} ({what}) is {status}; move it to Open decisions (line {e.lineno})",
                    code=DECISION,
                )
            )


def _names_unknown_table(text: str, known: set[str]) -> bool:
    return any(
        (sid := m.rstrip(".")).startswith("db.")
        and sid.count(".") == 1
        and sid not in known
        for m in ID_RE.findall(text)
    )


def _listed_in(field: str, thing: str, body: str) -> bool:
    """Is the `[NEW]` `thing` a row (or, for a file, a line) of `body`?"""
    if field == "Routes":
        m = ROUTE_RE.search(thing)
        return m is not None and (
            m.group(1).upper(),
            normalise_path(m.group(2).rstrip(".,;:)`")),
        ) in _route_keys(body)
    if field == "Pages":
        paths = [p.rstrip(".,;:)`") for p in _CITED_PATH_RE.findall(thing)]
        return bool(paths) and normalise_path(paths[0]) in _page_keys(body)
    if field == "Files":
        return (
            re.search(rf"(?<![\w/.-]){re.escape(thing)}(?![\w/.-])", body) is not None
        )
    return thing in _name_keys(body)


def _existing_section(
    e: _NewEntry,
    doc: LoadedDoc,
    bodies: dict[str, str | None],
    unreadable: set[str],
    issues: list[Issue],
) -> str | None:
    """Id of the current-document section that already lists `e`, if any."""
    for s in doc.manifest.sections:
        if not s.id.startswith(_LISTING_PREFIXES[e.field]):
            continue
        if s.id not in bodies:
            bodies[s.id] = _l2_slice(doc, s.id, unreadable, issues)
        body = bodies[s.id]
        if body is not None and _listed_in(e.field, e.thing, body):
            return s.id
    return None


def _existing_file_section(structure: _Structure, path: str) -> str | None:
    owner = structure.owners.get(path)
    if owner is not None:
        return owner
    if path in structure.tree:
        return "struct.tree"
    prefix = f"{path}/"
    return next(
        (sid for p, sid in sorted(structure.owners.items()) if p.startswith(prefix)),
        None,
    )


def _check_new_exists(
    entries: list[_NewEntry],
    doc: LoadedDoc,
    issues: list[Issue],
    notes: list[str],
    moved: bool,
    load_at: LoadAt | None,
    structure: Callable[[], _Structure],
    repo: str | None = None,
    rev: str = "",
) -> None:
    """A `[NEW]` thing the current document already lists is an error. When
    the ticket is grounded on an older revision (`moved`), the thing may have
    been built since: it is an error only if it was already listed at the
    grounded revision, otherwise a note (also when that revision cannot be
    read back). `load_at` returns L2 text, which lists no file paths, so a
    moved-revision Files `[NEW]` is always a note."""
    bodies: dict[str, str | None] = {}
    unreadable: set[str] = set()
    found: list[Issue] = []
    known = _known_ids(doc)
    for e in entries:
        if e.field == "Tables":
            continue  # no listing to compare an index against
        if e.field == "Files":
            sid = _existing_file_section(structure(), e.thing)
        elif _cites_listed(e.text, known):
            continue  # mixed line: reported by _check_tables_routes_commands (new docs only)
        else:
            sid = _existing_section(e, doc, bodies, unreadable, found)
        if sid is None:
            continue
        label = f"{_NEW_NOUN[e.field]} '{e.thing}'"
        if moved and not _listed_at(doc, repo, rev, sid, e, load_at):
            notes.append(f"{label} now exists in {sid} — built since grounding")
            continue
        issues.append(
            Issue(
                "error",
                f"{label} already exists in {sid}; cite it instead (line {e.lineno})",
                code=DECISION,
            )
        )
    for issue in found:
        _issue_once(issues, issue)


def _listed_at(
    doc: LoadedDoc,
    repo: str | None,
    rev: str,
    sid: str,
    e: _NewEntry,
    load_at: LoadAt | None,
) -> bool:
    """Was `e` already listed in section `sid` when `rev` was current?"""
    try:
        refs = load_at(repo, doc.manifest.id, rev, [sid]) if load_at else None
    except (KbError, OSError, ValueError):
        return False
    return any(
        r.ref.section_id == sid
        and r.status != "broken"
        and _listed_in(e.field, e.thing, r.content)
        for r in refs or []
    )
