"""Test case spec (`docs/templates/test-cases.md`): parser and lint.

`lint` always checks structure (headings, fields, placeholders, scripts
on disk). With a ticket it also checks coverage and traceability against
the ticket's ACs, alternate flows and revision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from strata_kb import planrev, ticket
from strata_kb.doctor import Issue
from strata_kb.lintcore import (
    AC_ID_RE,
    LintReport,
    ac_items,
    review_passed,
    section_body,
    table_column,
    table_rows,
)
from strata_kb.mdmask import visible_body

FIELDS: tuple[str, ...] = (
    "Objective",
    "Type",
    "Priority",
    "Technique",
    "Polarity",
    "Preconditions",
    "Test data",
    "Steps",
    "Expected result",
    "Script",
    "Automation",
)
POLARITIES = ("positive", "negative", "boundary")
REQUIRED_HEADINGS = ("## Scope & traceability", "## Change log", "## Review record")
FLOWS_HEADING = "## Alternate flows coverage"

_STORY_RE = re.compile(r"Story:\s*([^\s·]+)")
_CHILDREN_RE = re.compile(r"Children:\s*([^·]*)")
_REV_RE = re.compile(r"Ticket revision:\s*(\d+)")
_TC_HEAD_RE = re.compile(r"^## (TC-\d+)\s*[—-]\s*(.*)$", re.M)
_TC_ID_RE = re.compile(r"TC-\d+")
_PLACEHOLDER_RE = re.compile(r"<(?!br\b)[a-z][\w .-]*>|(?<!\w)…(?!\w)")
_NO_SCRIPT = {"", "-", "—", "n/a", "none"}


@dataclass(frozen=True)
class TestCase:
    __test__ = False  # not a pytest class
    tc_id: str
    title: str
    fields: dict[str, str]


@dataclass(frozen=True)
class CaseSpec:
    story: str
    children: tuple[str, ...]
    revision: int | None
    trace: dict[str, tuple[str, ...]]
    cases: tuple[TestCase, ...]
    flows: dict[str, tuple[str, ...]]


def _split(cell: str) -> tuple[str, ...]:
    return tuple(_TC_ID_RE.findall(cell))


def _header(text: str) -> str:
    for line in text.splitlines():
        if line.startswith(">"):
            return line
    return ""


def _trace_rows(text: str, heading: str) -> dict[str, tuple[str, ...]]:
    rows = table_rows(section_body(text, heading) or "")
    if not rows:
        return {}
    ci = table_column(rows, "Test cases")
    if ci is None:
        return {}
    return {r[0]: _split(r[ci]) for r in rows[1:] if len(r) > ci and r[0]}


def _case_blocks(text: str) -> list[tuple[str, str, str]]:
    heads = list(_TC_HEAD_RE.finditer(text))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end() : end]
        cut = re.search(r"^## ", body, re.M)
        out.append(
            (m.group(1), m.group(2).strip(), body[: cut.start()] if cut else body)
        )
    return out


def parse(text: str) -> CaseSpec:
    head = _header(text)
    story = m.group(1) if (m := _STORY_RE.search(head)) else ""
    kids = m.group(1) if (m := _CHILDREN_RE.search(head)) else ""
    children = tuple(c for c in (s.strip() for s in kids.split(",")) if c and c != "…")
    rev = int(m.group(1)) if (m := _REV_RE.search(head)) else None
    cases = []
    for tc_id, title, body in _case_blocks(text):
        fields: dict[str, str] = {}
        for row in table_rows(body)[1:]:
            if len(row) >= 2:
                fields[row[0]] = row[1]
        cases.append(TestCase(tc_id, title, fields))
    return CaseSpec(
        story=story,
        children=children,
        revision=rev,
        trace=_trace_rows(text, "## Scope & traceability"),
        cases=tuple(cases),
        flows=_trace_rows(text, FLOWS_HEADING),
    )


def _err(msg: str, code: str) -> Issue:
    return Issue(level="error", message=msg, code=code)


def _placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value))


def _structure(text: str, spec: CaseSpec) -> list[Issue]:
    issues = [
        _err(f"missing heading: {h}", "tc-heading")
        for h in REQUIRED_HEADINGS
        if section_body(text, h) is None
    ]
    if not spec.story or _placeholder(spec.story) or _placeholder(_header(text)):
        issues.append(
            _err(
                "header: story/children/revision left as placeholder", "tc-placeholder"
            )
        )
    if not spec.cases:
        issues.append(_err("no `## TC-NN — title` sections", "tc-heading"))
    if not review_passed(text):
        issues.append(_err("Q1 has not passed", "tc-review"))
    for tc in spec.cases:
        if _placeholder(tc.title):
            issues.append(
                _err(f"{tc.tc_id}: title left as placeholder", "tc-placeholder")
            )
        for name in FIELDS:
            val = tc.fields.get(name)
            if val is None or not val.strip():
                issues.append(_err(f"{tc.tc_id}: missing field {name}", "tc-field"))
            elif _placeholder(val):
                issues.append(
                    _err(
                        f"{tc.tc_id}: field {name} left as placeholder",
                        "tc-placeholder",
                    )
                )
        pol = tc.fields.get("Polarity", "").strip().lower()
        if pol and pol not in POLARITIES and not _placeholder(pol):
            issues.append(
                _err(
                    f"{tc.tc_id}: Polarity must be one of {', '.join(POLARITIES)}",
                    "tc-field",
                )
            )
    return issues


def _script_issues(spec: CaseSpec, spec_dir: Path) -> list[Issue]:
    issues: list[Issue] = []
    prefix = f"tests/{spec_dir.name}/"
    named: set[Path] = set()
    for tc in spec.cases:
        raw = tc.fields.get("Script", "").strip().strip("`")
        manual = tc.fields.get("Automation", "").strip().lower().startswith("manual")
        if raw.lower() in _NO_SCRIPT or _placeholder(raw):
            if not manual and not raw:
                continue  # already reported as a missing field
            if not manual and raw.lower() in _NO_SCRIPT:
                issues.append(
                    _err(f"{tc.tc_id}: automated case has no Script", "tc-script")
                )
            continue
        rel = raw.removeprefix(prefix) if raw.startswith(prefix) else None
        target = (spec_dir / rel).resolve() if rel else None
        if target is None or not target.is_relative_to(spec_dir.resolve()):
            issues.append(
                _err(f"{tc.tc_id}: Script {raw} is not under {prefix}", "tc-script")
            )
        elif not target.is_file():
            issues.append(_err(f"{tc.tc_id}: Script {raw} does not exist", "tc-script"))
        else:
            named.add(target)
    if spec_dir.is_dir():
        for f in sorted(spec_dir.rglob("*")):
            is_script = f.is_file() and (
                ".spec." in f.name or ".test." in f.name or f.name.startswith("test_")
            )
            if is_script and f.resolve() not in named:
                issues.append(
                    _err(
                        f"script {f.relative_to(spec_dir)} is named by no TC",
                        "tc-orphan",
                    )
                )
    return issues


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _ticket_issues(spec: CaseSpec, ticket_text: str) -> list[Issue]:
    issues: list[Issue] = []
    acs = {
        m.group(1).upper(): item
        for item in ac_items(ticket_text)
        if (m := AC_ID_RE.match(item))
    }
    pol = {tc.tc_id: tc.fields.get("Polarity", "").strip().lower() for tc in spec.cases}
    trace = {k.upper(): v for k, v in spec.trace.items()}
    for ac, item in acs.items():
        tcs = trace.get(ac, ())
        if not tcs:
            issues.append(_err(f"{ac} has no test case", "tc-uncovered"))
            continue
        pols = {pol.get(t) for t in tcs}
        if "positive" not in pols:
            issues.append(_err(f"{ac} has no positive test case", "tc-no-positive"))
        if re.search(r"\d", AC_ID_RE.sub("", item, count=1)) and not pols & {
            "negative",
            "boundary",
        }:
            issues.append(
                Issue(
                    level="warning",
                    message=f"{ac} mentions a number but has no negative/boundary test case",
                    code="tc-no-boundary",
                )
            )
    for ac in trace:
        if ac not in acs:
            issues.append(
                _err(
                    f"traceability cites {ac}, not an AC of the ticket", "tc-unknown-ac"
                )
            )
    covered = {_norm(f) for f, tcs in spec.flows.items() if tcs}
    for flow in ticket.alternate_flows(ticket_text):
        if _norm(flow) not in covered:
            issues.append(
                _err(
                    f"alternate flow has no test case: {flow} "
                    '(add "| <flow> | TC-NN |" under ## Alternate flows coverage)',
                    "tc-flow",
                )
            )
    want = planrev.parse_revision(ticket_text)
    if want is not None and spec.revision != want:
        issues.append(
            _err(
                f"Ticket revision {spec.revision} does not match ticket revision {want}",
                "tc-revision",
            )
        )
    return issues


def lint(text: str, ticket_text: str | None, *, spec_dir: Path) -> LintReport:
    text = visible_body(text) + "\n"
    spec = parse(text)
    issues = _structure(text, spec)
    issues += _script_issues(spec, spec_dir)
    notes: list[str] = []
    if ticket_text is None:
        notes.append("no ticket: AC coverage, flows and revision not checked")
    else:
        issues += _ticket_issues(spec, ticket_text)
        for tc_id in {t for ts in spec.trace.values() for t in ts}:
            if tc_id not in {c.tc_id for c in spec.cases}:
                issues.append(
                    _err(
                        f"traceability cites {tc_id}, which has no section",
                        "tc-unknown-tc",
                    )
                )
    return LintReport(issues=issues, notes=notes)
