"""`kb ticket check` engine — the SA grounding gate.

Verifies a ticket's `## Technical grounding` section (spec
2026-09-20-sa-grounding-design §3/§7) against the real `<repo>-code`
document: every `svc.* / db.* / api.* / int.* / cmd.*` id must exist in the
document's `_manifest.yaml` (or carry `[NEW: <reason>]`), columns / routes /
commands must match the document's own L2 tables, `Files:` must be listed in
`struct.tree`, and `Open decisions` must be empty.

No CLI/MCP imports here — `cli.py`'s `kb ticket check` is a thin wrapper, the
same split `ticketlint.py` has. Where the document comes from (local
`.kb/` or the hub federation) is the caller's `load_doc` callable.
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
from strata_kb.lintcore import LintReport

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

_NONE_WORDS = frozenset({"none", "n/a", "-"})


class DocLoadError(Exception):
    """The -code document exists but cannot be used: unreadable manifest,
    or the same doc id published by several repos with no qualifier."""


@dataclass(frozen=True)
class LoadedDoc:
    manifest: models.Manifest
    source: str  # human label for the [note] line, e.g. ".kb/demo-code"
    read_group: Callable[[str], str | None]  # group stem -> L2 text
    read_raw: Callable[[str], str | None]    # group stem -> L3 text


LoadDoc = Callable[[str | None, str], LoadedDoc | None]


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


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def check(text: str, *, load_doc: LoadDoc, heading: str = HEADING) -> LintReport:
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

    _check_revision(doc, doc_id, rev, line, issues)
    _check_ids(section, doc, issues, notes)
    _check_service_present(section, issues)
    _check_open_decisions(section, issues)
    # Task 3 adds:  _check_tables_routes_commands(section, doc, issues)
    # Task 4 adds:  _check_files(section, doc, issues, notes)
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
        if line.strip():
            yield section.first_line + i, line


def _check_ids(section: _Section, doc: LoadedDoc, issues: list[Issue], notes: list[str]) -> None:
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
                    continue  # column verified in Task 3
                sid = table
            if new is not None:
                reason = (new.group("reason") or "").strip()
                if reason:
                    notes.append(f"new: {sid} — {reason} (line {lineno})")
                else:
                    issues.append(Issue("warning", f"[NEW] without a reason for {sid} (line {lineno})"))
                continue
            issues.append(
                Issue(
                    "error",
                    f"unknown id '{sid}' — not a section of {doc.manifest.id}; copy the "
                    f"id from the document or mark the line [NEW: <reason>] (line {lineno})",
                )
            )


def _check_service_present(section: _Section, issues: list[Issue]) -> None:
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
            rest = FIELD_RE.match(line).group("rest").strip()
            if rest:
                items.insert(0, (section.first_line + i, rest))
    open_items = [(n, t) for n, t in items if t.strip().casefold() not in _NONE_WORDS]
    for lineno, item in open_items:
        issues.append(Issue("error", f"open decision: {item} (line {lineno})"))
    if open_items:
        issues.append(Issue("error", f"{len(open_items)} open decision(s) — resolve before Dev"))
