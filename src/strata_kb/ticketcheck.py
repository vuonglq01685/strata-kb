"""`kb ticket check` engine — the SA grounding gate.

Verifies a ticket's `## Technical grounding` section (spec
2026-09-20-sa-grounding-design §3/§7) against the real `<repo>-code`
document: every `svc.* / db.* / api.* / int.* / cmd.*` id must exist in the
document's `_manifest.yaml` (or carry `[NEW: <reason>]`), columns / routes /
commands must match the document's own L2 tables, `Files:` must be listed in
`struct.tree`, `Volumes:` / `Healthchecks:` / `Devices:` must match the svc
L2 rows, and `Open decisions` must be empty.

No CLI/MCP imports here — `cli.py`'s `kb ticket check` is a thin wrapper, the
same split `ticketlint.py` has. Where the document comes from (local
`.kb/` or the hub federation) is the caller's `load_doc` callable, and
`[NEW: D<n>]` markers are verified against the parent mission's
`## Technology decisions` through a second injected callable, `load_decisions`,
so the engine stays free of filesystem/CLI imports.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml
from pydantic import ValidationError

from strata_kb import lintcore, models
from strata_kb.doctor import Issue
from strata_kb.errors import KbError
from strata_kb.lintcore import LintReport
from strata_kb.mdutils import slice_section
from strata_kb import mission, ticket

HEADING = "## Technical grounding"

# `- Grounded on: [<repo>:]<doc> @ <rev>` — repo/doc classes as in
# kbcontext._REF_RE; rev is a 7..40 hex commit (core.run() writes 7).
GROUNDED_ON_RE = re.compile(
    r"^-\s*Grounded on:\s*"
    r"(?:(?P<repo>[A-Za-z0-9][A-Za-z0-9._-]*(?:/[A-Za-z0-9][A-Za-z0-9._-]*)*):)?"
    r"(?P<doc>[A-Za-z0-9][A-Za-z0-9._-]*)\s*@\s*(?P<rev>[0-9a-fA-F]{7,40})\s*$"
)
ID_RE = re.compile(r"\b(?:svc|db|api|int|cmd|dep|struct)\.[A-Za-z0-9_][A-Za-z0-9_.-]*")
NEW_RE = re.compile(r"\[NEW(?::\s*(?P<reason>[^\]]*))?\]")
ROUTE_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/\S*)")
CODE_SPAN_RE = re.compile(r"`([^`]+)`")
# A top-level field line: `- Files:`, `- Verify with: ...` (column 0 only —
# sub-items are indented and may themselves contain a colon).
FIELD_RE = re.compile(r"^-\s*(?P<field>[A-Za-z][A-Za-z ]*?):\s*(?P<rest>.*)$")
SUBITEM_RE = re.compile(r"^\s+-\s*(?P<text>.*\S)\s*$")
PRIMARY_RE = re.compile(r"\*\*Primary:\*\*\s*`([^`]*)`")
TREE_CAP_RE = re.compile(r"^# … \d+ more entr(?:y|ies) omitted from `(?P<first>[^`]*)` onward")
TREE_DEPTH = 4  # codeingest.extractors.tree._L3_DEPTH

SERVICES_HEADING = "## Services & order"
DECISION_REF_RE = re.compile(r"^D\d+$")

_NONE_WORDS = frozenset({"none", "n/a", "-"})

COMPOSE_FIELDS: tuple[str, ...] = ("Volumes", "Healthchecks", "Devices")
# `svc.<x> — <values>` groups on one compose line, `;`-separated.
_COMPOSE_GROUP_RE = re.compile(r"(svc\.[A-Za-z0-9_][A-Za-z0-9_.-]*)\s*[—-]\s*(?P<values>[^;]*)")
_COMPOSE_ROW = {"Volumes": "Volumes", "Healthchecks": "Healthcheck", "Devices": "Devices"}
_COMPOSE_NOUN = {"Volumes": "volume", "Healthchecks": "healthcheck", "Devices": "device"}


class DocLoadError(KbError):
    """The -code document exists but cannot be used: unreadable manifest,
    or the same doc id published by several repos with no qualifier."""


@dataclass(frozen=True)
class LoadedDoc:
    manifest: models.Manifest
    source: str  # human label for the [note] line, e.g. ".kb/demo-code"
    read_group: Callable[[str], str | None]  # group stem -> L2 text
    read_raw: Callable[[str], str | None]    # group stem -> L3 text


LoadDoc = Callable[[str | None, str], LoadedDoc | None]


@dataclass(frozen=True)
class Decision:
    id: str
    status: str
    owner: str


@dataclass(frozen=True)
class DecisionTable:
    source: str  # human label, e.g. "missions/M-demo.md" or "this mission"
    rows: dict[str, Decision]


LoadDecisions = Callable[[str], DecisionTable | None]  # mission id -> table, None = file missing


def parse_decisions(text: str, source: str) -> DecisionTable:
    """The `## Technology decisions` table of `text` keyed by its `#` cell.
    Columns are found by header name, so a reordered table still parses;
    no section or no `#`/`Status` header -> empty rows."""
    body = lintcore.section_body(text, mission.TECH_DECISIONS_HEADING)
    rows = lintcore.table_rows(body) if body is not None else []
    if not rows:
        return DecisionTable(source, {})
    i_id = _table_column(rows, "#")
    i_status = _table_column(rows, "status")
    i_owner = _table_column(rows, "owner")
    if i_id is None or i_status is None:
        return DecisionTable(source, {})
    out: dict[str, Decision] = {}
    for r in rows[1:]:
        if len(r) <= max(i_id, i_status):
            continue
        owner = r[i_owner].strip() if i_owner is not None and len(r) > i_owner else ""
        out[r[i_id].strip()] = Decision(r[i_id].strip(), r[i_status].strip(), owner)
    return DecisionTable(source, out)


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
        r for r in load_federation(federation_dir)
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
    first_line: int                     # 1-based ticket line of the body's first line
    lines: list[str]                    # visible body lines (HTML comments blanked)
    field_of_line: list[str | None]     # the `- <Field>:` a line belongs to
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
    blanked = lintcore.HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), body)
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
                subitems.setdefault(current, []).append((first_line + i, m.group("text")))
        field_of_line.append(current)
    return _Section(first_line, lines, field_of_line, subitems)


@dataclass(frozen=True)
class _Decisions:
    table: DecisionTable | None
    mission_id: str | None  # the `> Parent mission:` id, or None


def _resolve_decisions(text: str, heading: str, load_decisions: LoadDecisions | None) -> _Decisions:
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


def _judge_new(label: str, new: re.Match, lineno: int, decisions: _Decisions,
               issues: list[Issue], notes: list[str]) -> None:
    """One `[NEW: …]` marker: free text -> note; `D<n>` -> verified against
    the decisions table. `label` is the id or path the marker exempts."""
    reason = (new.group("reason") or "").strip()
    if not reason:
        _issue_once(issues, Issue("warning", f"[NEW] without a reason for {label} (line {lineno})"))
        return
    if not DECISION_REF_RE.match(reason):
        notes.append(f"new: {label} — {reason} (line {lineno})")
        if decisions.table is not None and decisions.table.rows:
            _issue_once(
                issues,
                Issue("warning", f"{decisions.table.source} has Technology decisions — reference the row as [NEW: D<n>] (line {lineno})"),
            )
        return
    if decisions.table is None:
        if decisions.mission_id is None:
            _issue_once(
                issues,
                Issue("error", f"[NEW: {reason}] needs a parent mission to hold the decision — add `> Parent mission: M-<slug>` under the title, or write [NEW: <reason>] (line {lineno})"),
            )
        else:
            _issue_once(
                issues,
                Issue("error", f"parent mission '{decisions.mission_id}' not found under missions/ — pass --missions-dir, or write [NEW: <reason>] (line {lineno})"),
            )
        return
    row = decisions.table.rows.get(reason)
    if row is None:
        _issue_once(
            issues,
            Issue("error", f"decision {reason} not in {decisions.table.source}'s Technology decisions — append the row there first (line {lineno})"),
        )
        return
    if row.status.upper() != "DECIDED":
        _issue_once(
            issues,
            Issue("error", f"decision {reason} is {row.status} (owner: {row.owner or 'none'}) — a human decides before Dev (line {lineno})"),
        )
        return
    notes.append(f"new: {label} — {reason} (DECIDED, owner {row.owner or 'none'}) (line {lineno})")


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def check(text: str, *, load_doc: LoadDoc, heading: str = HEADING,
          load_decisions: LoadDecisions | None = None) -> LintReport:
    issues: list[Issue] = []
    notes: list[str] = []
    section = _parse_section(text, heading)
    if section is None:
        issues.append(Issue("error", f"missing '{heading}' — run /sa-ticket-ground"))
        return LintReport(issues, notes)

    grounded = _grounded_on(section, issues)
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
                f"{doc_id} not found under --kb-dir or on the hub ({where}) — "
                "is the -code document published, and is the id spelled as "
                f"`<repo-id>-code`? (line {line})",
            )
        )
        return LintReport(issues, notes)
    notes.append(f"{doc_id} read from {doc.source}")
    decisions = _resolve_decisions(text, heading, load_decisions)

    _check_revision(doc, doc_id, rev, line, issues)
    _check_ids(section, doc, decisions, issues, notes)
    _check_service_present(section, heading, issues)
    _check_open_decisions(section, issues)
    _check_tables_routes_commands(section, doc, issues)
    if heading != SERVICES_HEADING:
        _check_compose_facts(section, doc, decisions, issues, notes)
    _check_files(section, doc, decisions, issues, notes)
    return LintReport(issues, notes)


def _grounded_on(section: _Section, issues: list[Issue]) -> tuple[str | None, str, str, int] | None:
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] != "Grounded on" or line[:1].isspace():
            continue
        lineno = section.first_line + i
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


def _check_revision(doc: LoadedDoc, doc_id: str, rev: str, line: int, issues: list[Issue]) -> None:
    have = (doc.manifest.revision or "").lower()
    if not have:
        issues.append(
            Issue("warning", f"{doc_id} has no revision in its manifest — grounding revision not verified")
        )
        return
    if not (have.startswith(rev) or rev.startswith(have)):
        issues.append(
            Issue(
                "error",
                f"stale grounding: ticket says @{rev}, {doc_id} is @{have} — "
                f"re-run /sa-ticket-ground against the current document (line {line})",
            )
        )


def _known_ids(doc: LoadedDoc) -> set[str]:
    return {s.id for s in doc.manifest.sections}


def _id_lines(section: _Section):
    """(lineno, line) for every visible line that is scanned for ids — the
    `Grounded on:` line (a doc id, not a section id) and `Files:` lines
    (paths such as `src/api.py` would read as `api.py`) are skipped."""
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] in ("Grounded on", "Files"):
            continue
        if section.field_of_line[i] == "Healthchecks":
            line = CODE_SPAN_RE.sub("``", line)
        if line.strip():
            yield section.first_line + i, line


def _check_ids(section: _Section, doc: LoadedDoc, decisions: _Decisions, issues: list[Issue], notes: list[str]) -> None:
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
                        continue  # column verified in Task 3
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


def _check_service_present(section: _Section, heading: str, issues: list[Issue]) -> None:
    if heading == SERVICES_HEADING:
        return  # the mission table has no `- Service:` line by design
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Service" and any(
            sid.startswith("svc.") for sid in ID_RE.findall(line)
        ):
            return
    issues.append(Issue("warning", "no `svc.<name>` on the `Service:` line — which service does this ticket touch?"))


def _check_open_decisions(section: _Section, issues: list[Issue]) -> None:
    items: list[tuple[int, str]] = list(section.subitems.get("Open decisions", []))
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Open decisions" and not line[:1].isspace():
            m = FIELD_RE.match(line)
            if m is not None and m.group("rest").strip():
                items.insert(0, (section.first_line + i, m.group("rest").strip()))
    open_items = [(n, t) for n, t in items if t.strip().casefold() not in _NONE_WORDS]
    for lineno, item in open_items:
        issues.append(Issue("error", f"open decision: {item} (line {lineno})"))
    if open_items:
        issues.append(Issue("error", f"{len(open_items)} open decision(s) — resolve before Dev"))


def _l2_slice(doc: LoadedDoc, sid: str, unreadable: set[str], issues: list[Issue]) -> str | None:
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
            Issue("warning", f"could not read {group}.md of {doc.manifest.id} — column/route/command checks for its sections skipped")
        )
        return None
    body = slice_section(text, sid)
    if body is None:
        unreadable.add(sid)
        issues.append(
            Issue("warning", f"section {sid} not found in {group}.md of {doc.manifest.id} — its column/route/command checks skipped")
        )
    return body


def _table_column(rows: list[list[str]], name: str) -> int | None:
    header = [c.strip().lower() for c in rows[0]] if rows else []
    return header.index(name) if name in header else None


def _check_tables_routes_commands(section: _Section, doc: LoadedDoc, issues: list[Issue]) -> None:
    known = _known_ids(doc)
    unreadable: set[str] = set()
    for lineno, line in _id_lines(section):
        if NEW_RE.search(line):
            continue
        ids = [i for i in ID_RE.findall(line)]
        for raw in ids:
            raw = raw.rstrip(".")
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
                        Issue("error", f"column '{column}' is not in {table} ({', '.join(sorted(names)) or 'no columns'}) (line {lineno})")
                    )
            # api.<tag> — METHOD /path
            elif raw.startswith("api.") and raw in known:
                pairs = ROUTE_RE.findall(line)
                if not pairs:
                    continue
                body = _l2_slice(doc, raw, unreadable, issues)
                if body is None:
                    continue
                rows = lintcore.table_rows(body)
                mi, pi = _table_column(rows, "method"), _table_column(rows, "path")
                have = {(r[mi].upper(), r[pi]) for r in rows[1:] if mi is not None and pi is not None and len(r) > max(mi, pi)}
                valid = ", ".join(f"{m} {p}" for m, p in sorted(have)) or "no routes"
                for method, path in pairs:
                    path = path.rstrip(".,;:)`")
                    if (method.upper(), path) not in have:
                        issues.append(
                            Issue("error", f"route '{method} {path}' is not in {raw} — copy a row of its table ({valid}) (line {lineno})")
                        )
            # cmd.<x> — `command`
            elif raw.startswith("cmd.") and raw in known:
                spans = CODE_SPAN_RE.findall(line)
                if not spans:
                    issues.append(Issue("warning", f"{raw}: put the command in backticks so it can be verified (line {lineno})"))
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
                        Issue("error", f"command not in {raw} — copy the primary or an alternative verbatim (found: {found}; allowed: {', '.join(sorted(allowed))}) (line {lineno})")
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


def _property(rows: list[list[str]], name: str) -> str | None:
    """The `Value` cell of the L2 property row named `name`, pipes unescaped."""
    for r in rows[1:]:
        if len(r) >= 2 and r[0].strip() == name:
            return r[1].strip().replace("\\|", "|")
    return None


def _svc_facts(doc: LoadedDoc, sid: str, field: str, unreadable: set[str], issues: list[Issue]) -> set[str] | None:
    """The svc's values for one compose field as a set: `{"pgdata"}`,
    `{"curl -f …"}`, `set()` for `none`. None when unreadable or when the
    document predates the rows (caller skips with a note)."""
    body = _l2_slice(doc, sid, unreadable, issues)
    if body is None:
        return None
    cell = _property(lintcore.table_rows(body), _COMPOSE_ROW[field])
    if cell is None:
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


def _check_compose_facts(section: _Section, doc: LoadedDoc, decisions: _Decisions,
                         issues: list[Issue], notes: list[str]) -> None:
    present = [f for f in COMPOSE_FIELDS if _field_lines(section, f)]
    if len(present) < len(COMPOSE_FIELDS):
        issues.append(Issue("warning", "Volumes:/Healthchecks:/Devices: lines missing — re-ground on a -code revision that carries them"))
    if not present:
        return
    services = _service_ids(section)
    unreadable: set[str] = set()
    skipped = False
    for field in present:
        for lineno, rest in _field_lines(section, field):
            noun = _COMPOSE_NOUN[field]
            if rest.strip().casefold() in _NONE_WORDS:
                for sid in sorted(services):
                    facts = _svc_facts(doc, sid, field, unreadable, issues)
                    if facts is None:
                        skipped = True
                    elif facts:
                        issues.append(Issue("warning", f"{sid} has {noun}s the grounding omits: {', '.join(sorted(facts))} (line {lineno})"))
                continue
            for g in _COMPOSE_GROUP_RE.finditer(rest):
                sid = g.group(1).rstrip(".")
                if sid not in services:
                    issues.append(Issue("error", f"{sid} on the {field}: line is not on the Service: line (line {lineno})"))
                    continue
                facts = _svc_facts(doc, sid, field, unreadable, issues)
                if facts is None:
                    skipped = True
                    continue
                values_raw = g.group("values")
                if values_raw.strip().casefold() in _NONE_WORDS:
                    if facts:
                        issues.append(Issue("error", f"{noun} for {sid} is '{', '.join(sorted(facts))}', not 'none' (line {lineno})"))
                    continue
                for value in _split_values(field, values_raw):
                    new = NEW_RE.search(value)
                    if new is not None:
                        _judge_new(NEW_RE.sub("", value).strip(), new, lineno, decisions, issues, notes)
                        continue
                    if value in facts:
                        continue
                    have = ", ".join(sorted(facts)) or "none"
                    if field == "Healthchecks":
                        issues.append(Issue("error", f"healthcheck for {sid} is '{have}', not '{value}' (line {lineno})"))
                    else:
                        issues.append(Issue("error", f"{noun} '{value}' is not in {sid} (has: {have}) (line {lineno})"))
    if skipped:
        notes.append(f"{doc.manifest.id} has no Volumes/Healthcheck/Devices rows (pre-1.3.0 code-ingest) — compose-fact checks skipped")


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


def _check_files(section: _Section, doc: LoadedDoc, decisions: _Decisions, issues: list[Issue], notes: list[str]) -> None:
    entries = list(section.subitems.get("Files", []))
    for i, line in enumerate(section.lines):
        if section.field_of_line[i] == "Files" and not line[:1].isspace():
            m = FIELD_RE.match(line)
            if m is not None and m.group("rest").strip():
                entries.insert(0, (section.first_line + i, m.group("rest").strip()))
    if not entries:
        return
    group = next((s.file for s in doc.manifest.sections if s.id == "struct.tree"), None)
    raw = doc.read_raw(group) if group else None
    if raw is None:
        issues.append(
            Issue("warning", f"could not read {group or 'structure'}.raw.md of {doc.manifest.id} — file checks skipped")
        )
        return
    paths, first_dropped = _tree_paths(raw)
    for lineno, text in entries:
        new = NEW_RE.search(text)
        path = NEW_RE.sub("", text).strip().strip("`").rstrip("/")
        if new is not None:
            _judge_new(path, new, lineno, decisions, issues, notes)
            continue
        if path in paths:
            continue
        if path.count("/") >= TREE_DEPTH:
            issues.append(
                Issue("warning", f"cannot verify '{path}': beyond struct.tree's depth cap ({TREE_DEPTH}) — list the deepest directory the document shows (line {lineno})")
            )
        elif first_dropped is not None:
            # ponytail: the cap marker names a bare file name, so "does this
            # path sort after the cut" is not decidable from the document;
            # a capped tree makes every absent path unverifiable, never an
            # error. Upgrade path: a full-path marker in tree.py's renderer.
            issues.append(
                Issue("warning", f"cannot verify '{path}': struct.tree hit its line cap (listing stops at '{first_dropped}') — the document cannot prove absence (line {lineno})")
            )
        else:
            issues.append(
                Issue("error", f"file '{path}' not in struct.tree of {doc.manifest.id} — spell it as the document lists it, or mark [NEW: <reason>] (line {lineno})")
            )
