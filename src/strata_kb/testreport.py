"""Test report (`reports/<story>/R<n>.md`): parser and lint (spec D6)."""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass
from pathlib import Path

import typer

from strata_kb import buglint, planparents, testcases, testenv
from strata_kb.doctor import Issue
from strata_kb.lintcore import (
    LintReport,
    review_passed,
    section_body,
    table_column,
    table_rows,
)
from strata_kb.mdmask import visible_body

VERDICTS = ("PASS", "FAIL")
RESULTS = VERDICTS
REQUIRED_HEADINGS = (
    "## Summary",
    "## Results by AC",
    "## Defects",
    "## Regression",
    "## Regression defects",
    "## Review record",
)

_STORY_RE = re.compile(r"Story:\s*([^\s·]+)")
_ROUND_RE = re.compile(r"Round:\s*(\d+)")
_VERDICT_RE = re.compile(r"Verdict:\s*([^·\n]*)")
_DATE_RE = re.compile(r"Date:\s*(\S+)")
_COMMIT_SEG_RE = re.compile(r"^([\w./-]+)\s+([0-9A-Za-z]{4,64})$")
_DEFECT_HEAD_RE = re.compile(r"^### (D\d+)\s*[—-]\s*(.*)$", re.M)
_RD_HEAD_RE = re.compile(r"^### (RD\d+)\s*[—-]\s*(.*)$", re.M)
_GUILTY_RE = re.compile(r"Guilty:\s*([^\s·]+)")
_REGRESSION_RE = re.compile(r"Regression:\s*(\w+)")
_BROKEN_RE = re.compile(r"Broken TC:\s*([^·\n]+)")
_BASELINE_RE = re.compile(r"Baseline:\s*([^·\n]+)")
_OVERLAP_RE = re.compile(r"Overlap:\s*([^\n]+)")
_RD_STORY_RE = re.compile(r"Story:\s*([^\s·]+)\s*·?\s*(TC-\d+)?")
_KEY_RE = re.compile(r"[^\s,/]+/TC-\d+")
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*([^)\s]+)[^)]*\)")
_ENV_LINE_RE = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
# A 40/64-char lowercase hex run is a git/sha256 id, not a credential, but only
# in header lines, `Baseline:` segments and after `@ `.
_HASH_RE = re.compile(r"\b(?:[0-9a-f]{40}|[0-9a-f]{64})\b")
_AT_HASH_RE = re.compile(r"@ (?:[0-9a-f]{40}|[0-9a-f]{64})\b")
_BASELINE_HASH_RE = re.compile(r"Baseline:[^·\n]*")
_ENV_MIN_LEN = 8
_RUN_RE = re.compile(r"^\s*Run:\s*(yes|no)\b", re.I | re.M)
_LIST_LINE_RE = re.compile(r"^\s*(Failed|Known):(.*)$", re.I | re.M)
_FULL_KEY_RE = re.compile(r"[^\s,/]+/TC-\d+")
_BROKEN_KEY_RE = re.compile(r"^([^\s/]+)[\s/]+(TC-\d+)$")


@dataclass(frozen=True)
class Defect:
    defect_id: str
    symptom: str
    guilty: str
    regression: bool
    broken_tc: str = ""
    baseline: str = ""
    overlap: str = ""


@dataclass(frozen=True)
class RegressionDefect:
    rd_id: str
    symptom: str
    story: str
    tc: str

    @property
    def key(self) -> str:
        return f"{self.story}/{self.tc}"


@dataclass(frozen=True)
class Report:
    story: str
    round: int
    verdict: str
    env_name: str
    commits: dict[str, str]
    date: str
    results: tuple[tuple[str, str, str], ...]
    defects: tuple[Defect, ...]
    regression_ran: bool
    regression_failed: tuple[str, ...]  # `Failed:` ∪ RD keys ∪ Regression: yes keys
    known: tuple[str, ...]
    regression_defects: tuple[RegressionDefect, ...]
    review_passed: bool  # meaningful on the source file only: the hub copy drops it


_KNOWN_HEADINGS = sorted(
    (*REQUIRED_HEADINGS, "## Environment & data seeds"), key=len, reverse=True
)


def _cut_note(line: str) -> str:
    """`## Heading note` -> `## Heading`, whatever the gap width."""
    for h in _KNOWN_HEADINGS:
        if line == h or (line.startswith(h) and line[len(h)].isspace()):
            return h
    return line


def _norm(text: str) -> str:
    """Visible body with the note after each known `## Heading` cut off."""
    lines = visible_body(text).splitlines()
    return (
        "\n".join(_cut_note(ln) if ln.startswith("## ") else ln for ln in lines) + "\n"
    )


def _header_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if ln.startswith(">")]


def _env_line(lines: list[str]) -> tuple[str, dict[str, str], str]:
    name, date, commits = "", "", {}
    for ln in lines:
        if "Environment:" not in ln:
            continue
        for seg in (s.strip() for s in ln.lstrip("> ").split("·")):
            if seg.startswith("Environment:"):
                name = seg.removeprefix("Environment:").strip()
            elif m := _DATE_RE.match(seg):
                date = m.group(1)
            elif m := _COMMIT_SEG_RE.match(seg):
                commits[m.group(1)] = m.group(2)
    return name, commits, date


def _blocks(body: str | None, head_re: re.Pattern[str]):
    body = body or ""
    heads = list(head_re.finditer(body))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        yield m, body[m.start() : end]


def _grab(block: str, rx: re.Pattern[str]) -> str:
    return m.group(1).strip() if (m := rx.search(block)) else ""


def _defects(body: str | None) -> tuple[Defect, ...]:
    out = []
    for m, block in _blocks(body, _DEFECT_HEAD_RE):
        head = m.group(0)
        g, r = _GUILTY_RE.search(head), _REGRESSION_RE.search(head)
        grab = functools.partial(_grab, block)
        out.append(
            Defect(
                defect_id=m.group(1),
                symptom=re.split(r"\s+Guilty:", m.group(2))[0].strip(),
                guilty=g.group(1) if g else "",
                regression=bool(r) and r.group(1).lower() == "yes",
                broken_tc=grab(_BROKEN_RE),
                baseline=grab(_BASELINE_RE),
                overlap=grab(_OVERLAP_RE),
            )
        )
    return tuple(out)


def _regression_defects(body: str | None) -> tuple[RegressionDefect, ...]:
    out = []
    for m, _ in _blocks(body, _RD_HEAD_RE):
        s = _RD_STORY_RE.search(m.group(2))
        out.append(
            RegressionDefect(
                rd_id=m.group(1),
                symptom=re.split(r"\s+Story:", m.group(2))[0].strip(),
                story=s.group(1) if s else "",
                tc=(s.group(2) or "") if s else "",
            )
        )
    return tuple(out)


def _keys(body: str, label: str) -> tuple[str, ...]:
    for ln in body.splitlines():
        if ln.strip().lower().startswith(f"{label}:"):
            return tuple(_KEY_RE.findall(ln))
    return ()


def broken_key(broken_tc: str) -> str:
    """`ST-0 TC-3` (or `ST-0/TC-3`) -> `ST-0/TC-3`; "" when not that shape."""
    m = _BROKEN_KEY_RE.match(broken_tc.strip())
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def _failed_keys(
    listed: tuple[str, ...],
    defects: tuple[Defect, ...],
    rds: tuple[RegressionDefect, ...],
) -> tuple[str, ...]:
    keys = [
        *listed,
        *(d.key for d in rds if d.story and d.tc),
        *(broken_key(d.broken_tc) for d in defects if d.regression),
    ]
    return tuple(dict.fromkeys(k for k in keys if k))


def parse(text: str) -> Report:
    text = _norm(text)
    head = _header_lines(text)
    joined = "\n".join(head)
    pick = lambda rx: m.group(1) if (m := rx.search(joined)) else ""  # noqa: E731
    name, commits, date = _env_line(head)
    rows = table_rows(section_body(text, "## Results by AC") or "")
    ci = table_column(rows, "Result") if rows else None
    tci = table_column(rows, "TC") if rows else None
    results = (
        tuple(
            (r[0], r[tci], r[ci].strip().upper())
            for r in rows[1:]
            if ci is not None and tci is not None and len(r) > max(ci, tci)
        )
        if rows
        else ()
    )
    reg = section_body(text, "## Regression") or ""
    defects = _defects(section_body(text, "## Defects"))
    rds = _regression_defects(section_body(text, "## Regression defects"))
    run = _RUN_RE.search(reg)
    return Report(
        story=pick(_STORY_RE),
        round=int(pick(_ROUND_RE) or 0),
        verdict=pick(_VERDICT_RE).strip(),
        env_name=name,
        commits=commits,
        date=date,
        results=results,
        defects=defects,
        regression_ran=bool(run) and run.group(1).lower() == "yes",
        regression_failed=_failed_keys(_keys(reg, "failed"), defects, rds),
        known=_keys(reg, "known"),
        regression_defects=rds,
        review_passed=review_passed(text),
    )


def _err(msg: str, code: str) -> Issue:
    return Issue(level="error", message=msg, code=code)


def _defect_issues(r: Report, children: tuple[str, ...]) -> list[Issue]:
    allowed = children or (r.story,)
    issues = []
    for d in r.defects:
        if d.guilty not in allowed:
            issues.append(
                _err(
                    f"{d.defect_id}: Guilty {d.guilty or '(missing)'} is not a child "
                    f"of {r.story} ({', '.join(allowed)})",
                    "rep-guilty",
                )
            )
        if d.regression:
            for label, val in (
                ("Broken TC", d.broken_tc),
                ("Baseline (or `no baseline`)", d.baseline),
                ("Overlap", d.overlap),
            ):
                if not val:
                    issues.append(
                        _err(
                            f"{d.defect_id}: Regression: yes needs {label}",
                            "rep-regression",
                        )
                    )
    for rd in r.regression_defects:
        if not rd.story or rd.story == r.story:
            issues.append(
                _err(
                    f"{rd.rd_id}: Story must be a closed story other than {r.story}",
                    "rep-rd-story",
                )
            )
    return issues


def _regression_issues(norm: str, r: Report) -> list[Issue]:
    """`## Regression` block (spec D6): `Run:`, `Failed:`, `Known:` lines."""
    reg = section_body(norm, "## Regression") or ""
    out = lambda m: _err(m, "rep-regression")  # noqa: E731
    issues = []
    if not _RUN_RE.search(reg):
        issues.append(out("Regression: needs `Run: yes` or `Run: no (<reason>)`"))
    elif r.verdict == "PASS" and not r.regression_ran:
        issues.append(out("a PASS report needs `Run: yes` under ## Regression"))
    lines = {m.group(1).lower(): m.group(2) for m in _LIST_LINE_RE.finditer(reg)}
    for label in ("failed", "known"):
        raw = lines.get(label)
        if raw is None:
            if r.regression_ran:
                issues.append(out(f"Regression: needs a `{label.title()}:` line"))
            continue
        items = [i.strip() for i in raw.split(",")]
        if items == ["none"]:
            continue
        bad = [i for i in items if not _FULL_KEY_RE.fullmatch(i)]
        if bad:
            issues.append(
                out(
                    f"Regression: `{label.title()}:` needs `<story>/TC-<k>` keys "
                    f"or `none`, got {', '.join(bad)}"
                )
            )
    listed = set(_keys(reg, "failed"))
    for rd in r.regression_defects:
        if rd.story and not rd.tc:
            issues.append(out(f"{rd.rd_id}: Story needs a TC (`Story: <id> · TC-<k>`)"))
    for d in (d for d in r.defects if d.regression and d.broken_tc):
        if not broken_key(d.broken_tc):
            issues.append(out(f"{d.defect_id}: Broken TC needs `<story> TC-<k>`"))
    for key in r.regression_failed:
        if key not in listed:
            issues.append(out(f"{key} is a regression failure but not in `Failed:`"))
    return issues


def _flag_issues(text: str) -> list[Issue]:
    issues = []
    for m, _ in _blocks(section_body(text, "## Defects"), _DEFECT_HEAD_RE):
        r = _REGRESSION_RE.search(m.group(0))
        if not r or r.group(1).lower() not in ("yes", "no"):
            issues.append(
                _err(f"{m.group(1)}: needs `Regression: yes|no`", "rep-regression")
            )
    return issues


def _results_issues(norm: str, r: Report) -> list[Issue]:
    rows = table_rows(section_body(norm, "## Results by AC") or "")
    if rows and (
        table_column(rows, "TC") is None or table_column(rows, "Result") is None
    ):
        return [
            _err("Results by AC: table needs `TC` and `Result` columns", "rep-result")
        ]
    if not r.results:
        return [_err("Results by AC: no result rows", "rep-result")]
    return []


def _verdict_issues(r: Report) -> list[Issue]:
    if r.verdict not in VERDICTS:
        return [
            _err(
                f"verdict '{r.verdict}' must be PASS or FAIL "
                "(INCOMPLETE and BLOCKED-ENV are never committed)",
                "rep-verdict",
            )
        ]
    bad = [x for _, _, x in r.results if x not in RESULTS]
    issues = [_err(f"result '{x}' must be PASS or FAIL", "rep-result") for x in bad]
    want = "FAIL" if r.defects or any(x == "FAIL" for _, _, x in r.results) else "PASS"
    if r.verdict != want:
        issues.append(
            _err(
                f"verdict {r.verdict} does not follow the evidence (expected {want}: "
                "any FAIL row or defect means FAIL)",
                "rep-verdict",
            )
        )
    return issues


def _uncovered_issues(r: Report, spec_tcs: tuple[str, ...] | None) -> list[Issue]:
    if spec_tcs is None:
        return []
    have = {tc.strip() for _, tc, _ in r.results}
    return [
        _err(f"Results by AC: {tc} of the test cases has no result row", "rep-result")
        for tc in spec_tcs
        if tc not in have
    ]


def _declared_env_vars(repo_root: Path) -> set[str] | None:
    """Env var names `.kb/test-env.yaml` references; None if absent/invalid."""
    try:
        env = testenv.load(repo_root)
    except testenv.TestEnvError:
        return None
    names = {env.db.url_env}
    for acct in env.accounts.values():
        names |= {acct.user_env, acct.password_env}
    return names


def _dotenv_issues(text: str, repo_root: Path) -> list[Issue]:
    """Error for each `.env` value (>= 8 chars) found in `text`; scoped to the
    vars test-env.yaml names, or every var when it does not load."""
    try:
        lines = (repo_root / ".env").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    declared = _declared_env_vars(repo_root)
    issues = []
    for line in lines:
        m = _ENV_LINE_RE.match(line.strip())
        if not m or (declared is not None and m.group(1) not in declared):
            continue
        value = m.group(2).strip().strip("'\"")
        if len(value) >= _ENV_MIN_LEN and value in text:
            issues.append(
                _err(
                    f"report contains the value of {m.group(1)} from .env", "rep-secret"
                )
            )
    return issues


def _without_commits(line: str) -> str:
    """`line` minus hex ids where commits legitimately appear: header lines,
    `Baseline:` segments and `@ <sha>`."""
    if line.startswith(">"):
        return _HASH_RE.sub("", line)
    line = _AT_HASH_RE.sub("@", line)
    return _BASELINE_HASH_RE.sub(lambda m: _HASH_RE.sub("", m.group(0)), line)


def _credential_issues(text: str) -> list[Issue]:
    return [
        _err(f"line {n} looks like a credential — remove it", "rep-secret")
        for n, ln in enumerate(text.splitlines(), 1)
        if testenv.secret_like(_without_commits(ln))
    ]


def _image_issues(text: str, report_dir: Path) -> list[Issue]:
    problems: list[str] = []
    for src in _IMAGE_RE.findall(visible_body(text)):
        problems += buglint.image_problems(src, "assets", report_dir)
    return [_err(p, "rep-image") for p in dict.fromkeys(problems)]


def lint(
    text: str,
    *,
    report_dir: Path,
    story_children: tuple[str, ...],
    repo_root: Path,
    spec_tcs: tuple[str, ...] | None = None,
) -> LintReport:
    """`spec_tcs` (the TC ids of the story's test cases) makes a missing result
    row an error; None skips that check."""
    norm = _norm(text)
    r = parse(text)
    issues = [
        _err(f"missing heading: {h}", "rep-heading")
        for h in REQUIRED_HEADINGS
        if section_body(norm, h) is None
    ]
    if not re.search(r"^## Environment", norm, re.M):
        issues.append(_err("missing heading: ## Environment", "rep-heading"))
    if not r.story or not r.round:
        issues.append(_err("header: Story and Round are required", "rep-header"))
    if not r.env_name or not r.date:
        issues.append(_err("header: Environment and Date are required", "rep-header"))
    issues += _results_issues(norm, r)
    issues += _verdict_issues(r)
    issues += _uncovered_issues(r, spec_tcs)
    issues += _flag_issues(norm)
    issues += _regression_issues(norm, r)
    issues += _defect_issues(r, story_children)
    issues += _image_issues(text, report_dir)
    issues += _dotenv_issues(text, repo_root) + _credential_issues(text)
    if not r.review_passed:
        issues.append(_err("Q2 has not passed", "rep-review"))
    return LintReport(issues=issues)


def story_children(spec: Path, story: str) -> tuple[str, ...]:
    """Spec header `Children:`; when empty, the split table of the `ticket.md`
    next to the spec."""
    try:
        kids = testcases.parse(spec.read_text(encoding="utf-8")).children
    except (OSError, UnicodeDecodeError):
        kids = ()
    if kids:
        return kids
    try:
        ticket = (spec.parent / "ticket.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ()
    return tuple(r.child for r in planparents.children(ticket, story))


def spec_tcs(spec: Path) -> tuple[str, ...] | None:
    """TC ids of `spec`; None when it cannot be read (nothing to compare)."""
    try:
        cases = testcases.parse(spec.read_text(encoding="utf-8")).cases
    except (OSError, UnicodeDecodeError):
        return None
    return tuple(c.tc_id for c in cases)


def lint_file(file: Path, repo_root: Path, json_output: bool) -> int:
    """`kb report lint`: exit 0 PASS, 1 FAIL or unreadable."""
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        typer.secho(f"cannot read {file}: {type(exc).__name__}", fg="red", err=True)
        return 1
    story = parse(text).story
    spec = repo_root / "tests" / story / "test-cases.md"
    children = story_children(spec, story)
    report = lint(
        text,
        report_dir=file.resolve().parent,
        story_children=children,
        repo_root=repo_root,
        spec_tcs=spec_tcs(spec),
    )
    if story and file.resolve().parent.name != story:
        report.issues.append(
            _err(
                f"header Story {story} does not match its folder "
                f"reports/{file.resolve().parent.name}/",
                "rep-header",
            )
        )
    typer.echo(json.dumps(report.to_json()) if json_output else report.render("REPORT"))
    return 0 if report.passed else 1
