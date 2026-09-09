# E1 + E2 — PR description gate and named TDD exemptions: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a text-only linter (`kb pr lint`) plus the scaffolded PR
template, CI workflow and TDD-exemption document that turn "a PR description
carries its evidence" from reviewer goodwill into a required check.

**Architecture:** One new stdlib-only module holds the canonical list of
required PR sections and lints a description against it. A new `pr` CLI sub-app
exposes it; a new scaffolded workflow runs it on every `pull_request` for kind
`dev` repos. A new scaffolded document names the four TDD exemption categories,
and three dev skills learn to declare, honour and report an exemption. Nothing
touches the MCP surface or the SHARED-* wrapper canon.

**Tech Stack:** Python 3.12, typer (CLI), pytest, `importlib.resources`
(package templates), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-05-e-pr-gate-tdd-exemptions-design.md`

## Global Constraints

- **No MCP change.** No sixth tool, no schema or docstring edit to the five
  existing tools. `git diff main...HEAD -- tests-gate/golden src/center_kb/mcp.py`
  must be **empty** when the batch ends.
- **No new dependency.** `prlint.py` is standard library only, so `uv.lock` does
  not change and the T2 lock gate does not fire.
- **The SHARED-* wrapper blocks are untouched.** Every skill-text edit lands in
  wrapper *bodies*. `SHARED_BLOCK_TEXT` is not re-extracted;
  `test_dev_wrappers_carry_byte_identical_shared_blocks` and
  `test_shared_hard_rules_were_not_touched_by_the_c5_round` stay green as-is.
- **Canon section list, verbatim, in this order:** `Ticket`, `kb-context`,
  `AC→test map`, `Placeholder resolutions`, `Verification`, `TDD exemptions`,
  `Findings`, `Usage`.
- **Canon exemption slugs, verbatim:** `config`, `ci`, `docs`, `style`.
- **Scaffolding is kind `dev` only.** No new row for `hub`, `child` or `ba`.
- **Trip-wire bumps are deliberate:** `tests/test_init.py:1434` goes 45 → 48.
- Every task ends on a commit. Run the full suite (`pytest -q`) before the
  final commit of the batch.

---

### Task 1: The linter engine — `src/center_kb/prlint.py`

**Files:**
- Create: `src/center_kb/prlint.py`
- Test: `tests/test_prlint.py`

**Interfaces:**
- Consumes: nothing — this is the batch's root task.
- Produces, relied on by Tasks 2–5:
  - `REQUIRED_SECTIONS: tuple[str, ...]` — the canon, 8 names, in order.
  - `SENTINEL_SECTIONS: frozenset[str]` — `{"TDD exemptions", "Findings"}`.
  - `Finding` — frozen dataclass with `.section: str`, `.code: str`,
    `.message: str`.
  - `PRLintReport` — frozen dataclass with `.findings: tuple[Finding, ...]`,
    property `.passed: bool`, `.render() -> str`, `.to_json() -> dict`.
  - `lint_body(body: str) -> PRLintReport`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_prlint.py`:

```python
"""Tests for prlint — the PR description gate. Pure text, no fixtures."""

from __future__ import annotations

from center_kb.prlint import (
    REQUIRED_SECTIONS,
    SENTINEL_SECTIONS,
    lint_body,
)


def _body(**overrides: str) -> str:
    """A passing description; override one section to make it fail."""
    filled = {
        "Ticket": "open-new-flight — add the new-flight endpoint",
        "kb-context": "arinc-kb:arinc-424 §5.3 @ 4f2a91c",
        "AC→test map": "AC1 → tests/test_flight.py::test_rejects_bad_icao",
        "Placeholder resolutions": "<max-alt> → 45000 per ATM-STD §5.3",
        "Verification": "```\n12 passed in 0.4s\n```",
        "TDD exemptions": "none",
        "Findings": "none",
        "Usage": "| phase | cost |\n|---|---|\n| dev-execute | $1.20 |",
    }
    filled.update(overrides)
    return "\n\n".join(f"## {name}\n\n{filled[name]}" for name in REQUIRED_SECTIONS)


def _codes(body: str) -> set[tuple[str, str]]:
    return {(f.section, f.code) for f in lint_body(body).findings}


def test_canon_is_the_eight_sections_in_order():
    assert REQUIRED_SECTIONS == (
        "Ticket",
        "kb-context",
        "AC→test map",
        "Placeholder resolutions",
        "Verification",
        "TDD exemptions",
        "Findings",
        "Usage",
    )
    assert SENTINEL_SECTIONS == frozenset({"TDD exemptions", "Findings"})


def test_a_fully_filled_description_passes():
    report = lint_body(_body())
    assert report.passed, report.render()
    assert report.findings == ()


def test_an_empty_body_reports_every_section_missing():
    report = lint_body("")
    assert not report.passed
    assert _codes("") == {(name, "missing-section") for name in REQUIRED_SECTIONS}


def test_a_missing_heading_is_reported_by_name():
    body = _body().replace("## Usage", "## Notes")
    assert ("Usage", "missing-section") in _codes(body)


def test_a_section_holding_only_an_html_comment_is_empty():
    # The load-bearing rule: an untouched template is all comments, so
    # without this the shipped template would pass and the gate would be
    # decoration.
    body = _body(Ticket="<!-- the ticket id goes here -->")
    assert ("Ticket", "empty-section") in _codes(body)


def test_a_multiline_html_comment_is_stripped_too():
    body = _body(Ticket="<!--\nthe ticket id\ngoes here\n-->")
    assert ("Ticket", "empty-section") in _codes(body)


def test_an_unterminated_html_comment_fails_closed():
    body = _body(Ticket="<!-- the ticket id goes here")
    assert ("Ticket", "empty-section") in _codes(body)


def test_none_is_a_valid_answer_in_the_two_sentinel_sections():
    for section in SENTINEL_SECTIONS:
        assert lint_body(_body(**{section: "none"})).passed
        assert lint_body(_body(**{section: "`None`"})).passed
        assert lint_body(_body(**{section: "_none_"})).passed


def test_none_elsewhere_is_ordinary_content_not_an_error():
    # Nonsense, but not this linter's business: presence and non-emptiness
    # are all it checks outside `## Verification`.
    assert lint_body(_body(Ticket="none")).passed


def test_verification_prose_without_a_fence_is_rejected():
    body = _body(Verification="All tests pass and the linter is clean.")
    assert ("Verification", "no-verification-output") in _codes(body)


def test_verification_with_an_empty_fence_is_rejected():
    body = _body(Verification="```\n\n```")
    assert ("Verification", "no-verification-output") in _codes(body)


def test_verification_accepts_a_tilde_fence_and_an_info_string():
    body = _body(Verification="~~~text\n12 passed in 0.4s\n~~~")
    assert lint_body(body).passed
    body = _body(Verification="```console\n12 passed in 0.4s\n```")
    assert lint_body(body).passed


def test_output_hidden_inside_a_comment_does_not_count_as_evidence():
    body = _body(Verification="<!-- ```\n12 passed\n``` -->")
    assert ("Verification", "empty-section") in _codes(body)


def test_a_duplicate_heading_is_reported():
    body = _body() + "\n\n## Usage\n\nagain\n"
    assert ("Usage", "duplicate-section") in _codes(body)


def test_a_heading_inside_a_fence_is_content_not_a_section():
    # A PR that pastes markdown into its verification block must not have
    # that paste read as a second `## Usage` section.
    body = _body(Verification="```\n## Usage\n12 passed in 0.4s\n```")
    assert lint_body(body).passed


def test_an_unbalanced_fence_fails_closed_not_open():
    # A stray opening fence swallows the rest of the body, so the sections
    # after it read as missing. That is the safe direction — CI goes red and
    # the author fixes the fence; it can never let an unfilled description
    # through.
    body = _body(Verification="```\n12 passed in 0.4s")
    assert not lint_body(body).passed
    assert ("Usage", "missing-section") in _codes(body)


def test_crlf_input_is_handled():
    assert lint_body(_body().replace("\n", "\r\n")).passed


def test_trailing_whitespace_after_a_heading_is_tolerated():
    assert lint_body(_body().replace("## Ticket", "## Ticket   ")).passed


def test_a_deeper_heading_does_not_end_a_section():
    body = _body(Verification="### Suite\n\n```\n12 passed\n```")
    assert lint_body(body).passed


def test_the_ascii_arrow_spelling_is_accepted():
    body = _body().replace("## AC→test map", "## AC->test map")
    assert lint_body(body).passed


def test_render_names_the_failing_sections_and_to_json_round_trips():
    report = lint_body("")
    text = report.render()
    assert "FAIL" in text
    for name in REQUIRED_SECTIONS:
        assert name in text
    payload = report.to_json()
    assert payload["passed"] is False
    assert len(payload["findings"]) == len(REQUIRED_SECTIONS)
    assert payload["findings"][0]["code"] == "missing-section"
    assert lint_body(_body()).to_json() == {"passed": True, "findings": []}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_prlint.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'center_kb.prlint'`.

- [ ] **Step 3: Write the implementation**

Create `src/center_kb/prlint.py`:

```python
"""Lint a pull-request description against the required-section canon.

Pure text: no hub access, no git, no network, standard library only — so the
CI job that runs it needs no checkout, no token, and works on fork PRs.

`REQUIRED_SECTIONS` below is the single source of truth for the section list.
The shipped PR template and the `dev-handover` wrappers are pinned against it
in tests/test_templates.py; change it here and those tests tell you what else
has to move.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

REQUIRED_SECTIONS: tuple[str, ...] = (
    "Ticket",
    "kb-context",
    "AC→test map",
    "Placeholder resolutions",
    "Verification",
    "TDD exemptions",
    "Findings",
    "Usage",
)

# The two sections that legitimately have nothing to report. `none` there is
# an explicit answer; everywhere else it is ordinary content.
SENTINEL_SECTIONS: frozenset[str] = frozenset({"TDD exemptions", "Findings"})

# `AC→test map` carries the vocabulary's only non-ASCII character, and a
# hand-typed body will spell it with an ASCII arrow. Accept both; the
# template ships the real arrow.
_HEADING_ALIASES: dict[str, str] = {"AC->test map": "AC→test map"}

# Level 1 and 2 headings both end a section; `###` and deeper are content, so
# a sub-heading inside `## Verification` cannot truncate it.
_HEADING = re.compile(r"^(?P<hashes>#{1,2})[ \t]+(?P<name>.+?)[ \t]*$")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# An unterminated `<!--` is treated as commented through the end of the
# section: it reads as empty and fails, rather than passing on text that
# nobody reviewing the PR can actually see.
_UNTERMINATED_COMMENT = re.compile(r"<!--.*\Z", re.DOTALL)

# There is deliberately no `none` matcher. `none` is ordinary non-empty text,
# so the emptiness check already accepts it in the two sentinel sections, and
# `## Verification` still needs a fence whatever it says. SENTINEL_SECTIONS
# exists to word the error message, not to branch the logic.


@dataclass(frozen=True)
class Finding:
    section: str
    code: str
    message: str


@dataclass(frozen=True)
class PRLintReport:
    findings: tuple[Finding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings

    def render(self) -> str:
        if self.passed:
            return (
                f"PR description: PASS — all {len(REQUIRED_SECTIONS)} required "
                "sections present and filled."
            )
        lines = [f"PR description: FAIL ({len(self.findings)} finding(s))"]
        lines.extend(
            f"  [{f.code}] ## {f.section}: {f.message}" for f in self.findings
        )
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "passed": self.passed,
            "findings": [
                {"section": f.section, "code": f.code, "message": f.message}
                for f in self.findings
            ],
        }


def _is_fence(line: str) -> str:
    """The fence marker opening/closing on this line, or '' if none."""
    stripped = line.lstrip()
    for marker in ("```", "~~~"):
        if stripped.startswith(marker):
            return marker
    return ""


def _split_sections(body: str) -> list[tuple[str, str]]:
    """Every heading in the body, paired with the text under it.

    Fenced regions are skipped when looking for headings: a PR that pastes
    markdown into its verification block must not have that paste read as a
    second copy of a required section.

    An unbalanced fence therefore swallows everything after it, and those
    sections report as missing. That is the safe direction: the check goes
    red and the author fixes the fence. It can never turn an unfilled
    description into a passing one.
    """
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    sections: list[tuple[str, list[str]]] = []
    open_fence = ""
    for line in text.split("\n"):
        marker = _is_fence(line)
        if open_fence:
            if marker == open_fence:
                open_fence = ""
            if sections:
                sections[-1][1].append(line)
            continue
        if marker:
            open_fence = marker
            if sections:
                sections[-1][1].append(line)
            continue
        match = _HEADING.match(line)
        if match:
            name = match.group("name").strip()
            sections.append((_HEADING_ALIASES.get(name, name), []))
            continue
        if sections:
            sections[-1][1].append(line)
    return [(name, "\n".join(lines)) for name, lines in sections]


def _visible(content: str) -> str:
    """The section's content with HTML comments removed."""
    text = _COMMENT.sub("", content)
    text = _UNTERMINATED_COMMENT.sub("", text)
    return text.strip()


def _has_fenced_output(text: str) -> bool:
    """True when a fenced block holds at least one non-blank line."""
    open_fence = ""
    for line in text.split("\n"):
        marker = _is_fence(line)
        if not open_fence:
            if marker:
                open_fence = marker
            continue
        if marker == open_fence:
            open_fence = ""
            continue
        if line.strip():
            return True
    return False


def lint_body(body: str) -> PRLintReport:
    """Check a PR description against REQUIRED_SECTIONS."""
    found = _split_sections(body)
    counts = Counter(name for name, _ in found)
    first: dict[str, str] = {}
    for name, content in found:
        first.setdefault(name, content)

    findings: list[Finding] = []
    for section in REQUIRED_SECTIONS:
        seen = counts.get(section, 0)
        if seen == 0:
            findings.append(
                Finding(
                    section,
                    "missing-section",
                    f"no '## {section}' heading in the description",
                )
            )
            continue
        if seen > 1:
            findings.append(
                Finding(
                    section,
                    "duplicate-section",
                    f"appears {seen} times; keep exactly one",
                )
            )
        visible = _visible(first[section])
        if not visible:
            hint = (
                " ('none' is a valid answer here)"
                if section in SENTINEL_SECTIONS
                else ""
            )
            findings.append(
                Finding(
                    section,
                    "empty-section",
                    "empty once HTML comments are stripped — fill it in" + hint,
                )
            )
            continue
        if section == "Verification" and not _has_fenced_output(visible):
            findings.append(
                Finding(
                    section,
                    "no-verification-output",
                    "no fenced block holding real output — paste the cmd.test "
                    "and cmd.lint output; a claim is not evidence",
                )
            )
    return PRLintReport(tuple(findings))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_prlint.py -q`
Expected: all pass. The `none` cases pass with no code of their own, because
`none` is ordinary non-empty text — that is why there is no sentinel matcher.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/prlint.py tests/test_prlint.py
git commit -m "feat(prlint): the PR description gate engine (roadmap E1)"
```

---

### Task 2: The CLI — `kb pr lint`

**Files:**
- Modify: `src/center_kb/cli.py` (sub-app registration near `:41`; the command
  itself after the `ticket_lint` command, which ends at `:1605`)
- Test: `tests/test_cli_prlint.py`

**Interfaces:**
- Consumes: `center_kb.prlint.lint_body`, `PRLintReport.passed`, `.render()`,
  `.to_json()` (Task 1).
- Produces: the command line `kb pr lint <source> [--json]`, used verbatim by
  the workflow in Task 3. Exit 0 clean, 1 on findings or an unreadable source.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_cli_prlint.py`:

```python
"""Tests for `kb pr lint` — the CLI wrapper over prlint.lint_body."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from center_kb.cli import app
from center_kb.prlint import REQUIRED_SECTIONS

runner = CliRunner()

GOOD = "\n\n".join(
    f"## {name}\n\nfilled" if name != "Verification"
    else "## Verification\n\n```\n12 passed in 0.4s\n```"
    for name in REQUIRED_SECTIONS
)


def test_a_filled_description_exits_zero(tmp_path: Path):
    body = tmp_path / "body.md"
    body.write_text(GOOD, encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body)])
    assert result.exit_code == 0, result.output
    assert "PASS" in result.output


def test_a_missing_section_exits_one_and_names_it(tmp_path: Path):
    body = tmp_path / "body.md"
    body.write_text(GOOD.replace("## Usage", "## Notes"), encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body)])
    assert result.exit_code == 1
    assert "Usage" in result.output
    assert "missing-section" in result.output


def test_stdin_source(tmp_path: Path):
    result = runner.invoke(app, ["pr", "lint", "-"], input=GOOD)
    assert result.exit_code == 0, result.output


def test_json_output(tmp_path: Path):
    body = tmp_path / "body.md"
    body.write_text(GOOD, encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output) == {"passed": True, "findings": []}


def test_a_missing_file_exits_nonzero_with_the_path(tmp_path: Path):
    result = runner.invoke(app, ["pr", "lint", str(tmp_path / "nope.md")])
    assert result.exit_code != 0
    assert "nope.md" in result.output


def test_a_non_utf8_file_is_reported_as_such(tmp_path: Path):
    body = tmp_path / "body.md"
    body.write_bytes(b"## Ticket\n\n\xff\xfe not utf-8\n")
    result = runner.invoke(app, ["pr", "lint", str(body)])
    assert result.exit_code == 1
    assert "not valid UTF-8" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_cli_prlint.py -q`
Expected: FAIL — typer reports `No such command 'pr'` (exit code 2).

- [ ] **Step 3: Register the sub-app**

In `src/center_kb/cli.py`, immediately after
`app.add_typer(usage_app, name="usage")` (line 41):

```python
pr_app = typer.Typer(
    help="Pull-request gate: check a PR description carries its evidence."
)
app.add_typer(pr_app, name="pr")
```

- [ ] **Step 4: Add the command**

In `src/center_kb/cli.py`, after the `ticket_lint` command (which ends at
line 1605), following its shape exactly:

```python
@pr_app.command("lint")
def pr_lint(
    source: str = typer.Argument(
        ..., help="File holding the PR description (or '-' to read from stdin)"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Emit the report as JSON instead of text"
    ),
) -> None:
    """Gate: every required PR section is present and actually filled in.

    Takes a file or stdin and never a string option: a PR description is
    attacker-controlled text, and keeping it out of argv is what stops a
    caller from interpolating it into a shell command.
    """
    from center_kb.prlint import lint_body

    if source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            typer.secho(
                f"file '{source}' is not valid UTF-8: {exc}", fg=typer.colors.RED
            )
            raise typer.Exit(1)
        except OSError as exc:
            typer.secho(f"could not read file '{source}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)

    report = lint_body(text)
    if json_output:
        typer.echo(json.dumps(report.to_json()))
    else:
        typer.echo(report.render())
    if not report.passed:
        raise typer.Exit(1)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_cli_prlint.py -q`
Expected: all pass. If `test_a_missing_file_exits_nonzero_with_the_path` fails
on the message, check the `OSError` branch is reached — `Path.read_text` on a
missing file raises `FileNotFoundError`, a subclass of `OSError`.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/cli.py tests/test_cli_prlint.py
git commit -m "feat(cli): kb pr lint (roadmap E1)"
```

---

### Task 3: The three scaffolded resources + `DEV_TEMPLATES`

**Files:**
- Create: `src/center_kb/templates/init/pull-request-template.md`
- Create: `src/center_kb/templates/init/kb-pr-lint.yml`
- Create: `src/center_kb/templates/init/tdd-exemptions.md`
- Modify: `src/center_kb/initcmd.py:98-147` (`DEV_TEMPLATES`)
- Test: `tests/test_init.py:1426-1438`

**Interfaces:**
- Consumes: `REQUIRED_SECTIONS` and `lint_body` (Task 1) — used by the test
  that asserts the shipped template fails the linter; the CLI line
  `kb pr lint <file>` (Task 2) — used verbatim inside the workflow.
- Produces, relied on by Tasks 4–5: the three deployed paths
  `.github/pull_request_template.md`, `.github/workflows/kb-pr-lint.yml`,
  `docs/tdd-exemptions.md`, and the resource names above.

- [ ] **Step 1: Write the failing tests**

In `tests/test_init.py`, change the pinned count and extend the assertions in
`test_init_kind_dev_scaffolds_exactly_the_stage_a_set` (line 1426):

```python
def test_init_kind_dev_scaffolds_exactly_the_stage_a_set(tmp_path: Path):
    report = init_repo(tmp_path, "dev")
    # Pin the count too: comparing expected_files("dev") to itself lets a
    # premature extra row slip in unnoticed on both sides of the equality.
    # 27 (Stage A) + 4 (dev-code-seed's own four-way wrappers) + 12 (the
    # reused kb-summarize/kb-approve/kb-publish rows the seed flow needs,
    # Stage C) + 1 (.claude/settings.json, the usage Stop hook) + 1
    # (docs/impl/.gitignore — C1 keeps the context cache out of git) + 3
    # (batch 7: the PR template, its workflow, and the TDD exemption doc) = 48.
    assert len(expected_files("dev")) == 48
    assert sorted(report.created) == sorted(expected_files("dev"))
    assert report.skipped == []
    for rel in _DEV_STAGE_A_PATHS:
        assert (tmp_path / rel).is_file(), rel
```

Append to `tests/test_init.py`:

```python
# --- Batch 7 (E1 + E2): the PR gate is scaffolded for kind dev only --------

_BATCH7_DEV_PATHS = (
    ".github/pull_request_template.md",
    ".github/workflows/kb-pr-lint.yml",
    "docs/tdd-exemptions.md",
)


def test_init_kind_dev_scaffolds_the_pr_gate(tmp_path: Path):
    init_repo(tmp_path, "dev")
    for rel in _BATCH7_DEV_PATHS:
        assert (tmp_path / rel).is_file(), rel


def test_the_pr_gate_is_not_scaffolded_for_other_kinds():
    for kind in ("hub", "child", "ba"):
        for rel in _BATCH7_DEV_PATHS:
            assert rel not in expected_files(kind), f"{kind}: {rel}"


def test_the_shipped_pr_template_fails_the_linter(tmp_path: Path):
    # The proof that the comment-stripping rule is real. An author who
    # deletes nothing and writes nothing must get a red check, not a green
    # one — if this ever passes, the gate has become decoration.
    from center_kb.prlint import lint_body

    init_repo(tmp_path, "dev")
    text = (tmp_path / ".github" / "pull_request_template.md").read_text(
        encoding="utf-8"
    )
    report = lint_body(text)
    assert not report.passed
    assert {f.code for f in report.findings} == {"empty-section"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_init.py -q -k "dev_scaffolds or pr_gate or shipped_pr_template"`
Expected: FAIL — the count is 45 not 48, and the three files do not exist.

- [ ] **Step 3: Write the PR template resource**

Create `src/center_kb/templates/init/pull-request-template.md`:

```markdown
<!--
Assembled by /dev-handover. Every heading below is required and is checked in
CI by `kb pr lint`: a section still holding only this comment counts as EMPTY
and fails the check. Replace each comment with real content. `none` is a valid
answer only under `## TDD exemptions` and `## Findings`.
-->

## Ticket

<!-- The ticket id and a one-line summary of what it asked for. -->

## kb-context

<!-- The pinned refs, so a reviewer can run `kb resolve` on this PR's ticket. -->

## AC→test map

<!-- One line per acceptance criterion: the AC, and the test that proves it. -->

## Placeholder resolutions

<!-- Every placeholder the ticket carried, and the value it resolved to, cited. -->

## Verification

<!--
The real output of cmd.test and cmd.lint, plus the freshness re-check, inside a
fenced code block. A completion claim with no pasted output does not pass.
-->

## TDD exemptions

<!--
Every task that shipped without a failing test observed first, one line each,
copied from the plan:

    Exempt: <config|ci|docs|style> — verified by <what>

See docs/tdd-exemptions.md. Write `none` when every task was test-first.
-->

## Findings

<!--
Every OPEN(...) finding, KB gap, ambiguity or contradiction found while
implementing, each as a concrete feedback item on the repo that owns it.
Write `none` when there were none.
-->

## Usage

<!-- The table from `kb usage report --ticket <id> --md`. -->
```

- [ ] **Step 4: Write the workflow resource**

Create `src/center_kb/templates/init/kb-pr-lint.yml`:

```yaml
# CI evidence gate: every pull request must carry a description with the
# sections `dev-handover` assembles — ticket, refs, AC→test map, placeholder
# resolutions, pasted verification output, TDD exemptions, findings, usage.
#
# The workflow file name and the job name are deliberately FROZEN as
# 'kb-pr-lint' / 'pr-lint': branch protection on already-provisioned dev
# repos keys on the job name, and renaming it would leave those repos waiting
# forever on a required check that never runs again.
#
# `types:` is spelled out because the default set for `pull_request` is
# opened/synchronize/reopened and does NOT include `edited` — and editing the
# description is exactly the event this check exists to re-run.
#
# Deliberately NOT `paths`-filtered, for the reason frozen into
# kb-ticket-lint.yml: GitHub never synthesizes a passing status for a job that
# never started, so a `paths:` filter on a trigger backing a *required* check
# leaves any PR outside the filter waiting forever.
#
# No checkout, no hub URL, no token: `kb pr lint` is pure text, so this job
# also runs green on pull requests from forks, where a hub credential would
# not be available.
name: kb-pr-lint
on:
  pull_request:
    types: [opened, edited, synchronize, reopened]
permissions:
  contents: read
jobs:
  pr-lint:
    runs-on: ubuntu-latest
    env:
      # The description reaches the script through the environment and NEVER
      # through `${{ ... }}` inside `run:`. A PR body is attacker-controlled
      # text; interpolating it into a shell script is script injection with a
      # payload the attacker chooses. tests/test_templates.py pins this.
      PR_BODY: ${{ github.event.pull_request.body }}
    steps:
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install center-kb
      - name: Check the PR description
        run: |
          printf '%s' "$PR_BODY" > "$RUNNER_TEMP/body.md"
          kb pr lint "$RUNNER_TEMP/body.md"
```

- [ ] **Step 5: Write the TDD exemption document**

Create `src/center_kb/templates/init/tdd-exemptions.md`:

```markdown
# TDD exemptions — the only changes that may ship without a red test first

The rule this document bounds, from every dev skill's hard rules:

> No production code without a failing test observed first. No exception for
> small tickets, deadlines, or "obvious" changes.

That rule is absolute. This document does not carve holes in it; it defines
what counts as production code.

**The boundary.** An exemption is a property of a **change class with no
observable behaviour** — never of a ticket's size, a deadline, or how obvious
the change looks. The moment a change alters behaviour an acceptance criterion
can see, no exemption applies, whatever the file extension.

**When it is decided.** An exemption is declared **when the plan is written**,
as one line inside the task block:

    Exempt: <config|ci|docs|style> — verified by <what>

It is never a decision taken mid-implementation. An implementer holding a task
with no `Exempt:` line who believes no test is possible **stops and returns the
task to `dev-plan`** — the same route an unimplementable AC takes. Deciding it
alone, with the code half-written, is the failure this document exists to
prevent.

**The four categories.** The slug is one of exactly these; a change that fits
none of them is not exempt.

| Slug | Covers | What you owe instead |
|---|---|---|
| `config` | config files, dependency bumps, scaffold changes | run the thing you just configured and paste the output — the build, `kb doctor`, the service starting |
| `ci` | workflow, job and gate definitions | that workflow's own run on this PR: link and status |
| `docs` | README, QUICKSTART, prose, skill text | paste the diff and any link/render check |
| `style` | formatting, renames, file moves with no behaviour change | the existing suite green **before and after**, plus the command showing behaviour is unchanged |

**`docs` is not an extension whitelist.** Where a repo pins document content
with a test — canon tests over template text, snapshot tests over generated
docs — a documentation change still owes a test, and is not exempt. The
question is always *"is there a test that can observe this?"*, never *"what is
this file's extension?"*.

Every exemption taken during a ticket is reported in the PR description under
`## TDD exemptions`, one line each, copied from the plan. The CI gate
(`kb pr lint`) requires that section to be present and non-empty; write `none`
when every task was test-first.
```

- [ ] **Step 6: Add the three rows to `DEV_TEMPLATES`**

In `src/center_kb/initcmd.py`, inside `DEV_TEMPLATES` (after the
`".github/workflows/kb-code.yml"` row at line 107):

```python
    # Batch 7 (E1 + E2): the PR evidence gate. The template is the section
    # list dev-handover already assembles; the workflow makes it a required
    # check; the document names the four TDD exemption categories the
    # `## TDD exemptions` section reports.
    ".github/pull_request_template.md": "pull-request-template.md",
    ".github/workflows/kb-pr-lint.yml": "kb-pr-lint.yml",
    "docs/tdd-exemptions.md": "tdd-exemptions.md",
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/test_init.py -q`
Expected: all pass, including the count at 48.

- [ ] **Step 8: Commit**

```bash
git add src/center_kb/templates/init/pull-request-template.md \
        src/center_kb/templates/init/kb-pr-lint.yml \
        src/center_kb/templates/init/tdd-exemptions.md \
        src/center_kb/initcmd.py tests/test_init.py
git commit -m "feat(init): scaffold the PR evidence gate for kind dev (roadmap E1+E2)"
```

---

### Task 4: Trip-wires over the templates, the workflow and the document

**Files:**
- Modify: `tests/test_templates.py` (append a new section at the end)

**Interfaces:**
- Consumes: `REQUIRED_SECTIONS` (Task 1), the three resources (Task 3), the
  existing `_read_init_template` helper (`tests/test_templates.py:39-41`).
- Produces: the canon pins that make Task 5's wrapper edits verifiable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
# --- Batch 7 (E1 + E2): the PR evidence gate --------------------------------

import re as _re

from center_kb.prlint import REQUIRED_SECTIONS

DEV_HANDOVER_TEMPLATES = _dev_wrapper_names("dev-handover")
EXEMPTION_SLUGS = ("config", "ci", "docs", "style")


def _pr_template_headings() -> list[str]:
    text = _read_init_template("pull-request-template.md")
    return [
        m.group(1).strip()
        for m in _re.finditer(r"^##[ \t]+(.+?)[ \t]*$", text, _re.MULTILINE)
    ]


def test_pr_template_headings_are_the_canon_in_order():
    # Canon pin, place 1 of 3: the shipped template against the module.
    assert tuple(_pr_template_headings()) == REQUIRED_SECTIONS


def test_every_required_section_is_named_in_the_dev_handover_wrappers():
    # Canon pin, place 2 of 3: the skill that assembles the body must name
    # every section the gate demands, or the gate fails PRs the skill wrote.
    for name in DEV_HANDOVER_TEMPLATES:
        body = _dev_wrapper_body(name)
        for section in REQUIRED_SECTIONS:
            assert _normalised(section) in body, f"{name}: {section}"


def test_pr_workflow_triggers_include_edited_and_have_no_paths_filter():
    text = _read_init_template("kb-pr-lint.yml")
    assert "types: [opened, edited, synchronize, reopened]" in text
    assert "\npaths:" not in text and "\n    paths:" not in text
    assert "\n  pr-lint:" in text, "the job name is frozen for branch protection"


def test_pr_workflow_never_interpolates_the_body_into_the_script():
    # The injection mitigation pinned as a test rather than left as an
    # intention: the body may reach the script only through `env:`.
    text = _read_init_template("kb-pr-lint.yml")
    assert "PR_BODY: ${{ github.event.pull_request.body }}" in text
    run_blocks = text.split("run: |")[1:]
    for block in run_blocks:
        assert "github.event.pull_request.body" not in block
    assert 'kb pr lint "$RUNNER_TEMP/body.md"' in text


def test_tdd_exemptions_doc_carries_the_four_slugs_and_the_boundary():
    text = _read_init_template("tdd-exemptions.md")
    for slug in EXEMPTION_SLUGS:
        assert f"`{slug}`" in text, slug
    assert "no observable behaviour" in text
    assert "when the plan is written" in text
    assert "Exempt: <config|ci|docs|style> — verified by <what>" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_templates.py -q -k "pr_template or dev_handover_wrappers or pr_workflow or tdd_exemptions"`
Expected: the template/workflow/document tests PASS already (Task 3 shipped
them); `test_every_required_section_is_named_in_the_dev_handover_wrappers`
FAILS — today's wrappers name no `TDD exemptions` section at all, and spell the
others in prose (`the ticket id`, `every OPEN(...) finding`) rather than in the
canon's capitalisation. That single red test is the handoff into Task 5, whose
step 5 rewrites the bullet to the canon names.

- [ ] **Step 3: Commit the trip-wires**

Commit them red-for-one — the failing test is Task 5's specification.

```bash
git add tests/test_templates.py
git commit -m "test: pin the PR gate canon in all three places (roadmap E1)"
```

Note: if the repository forbids committing a failing test, run Task 5 first and
commit Tasks 4 and 5 together. The suite must be green at the end of Task 5
either way.

---

### Task 5: Skill text — declare, honour, report an exemption

**Files:**
- Modify (4): `claude-skill-dev-plan.md`, `claude-command-dev-plan.md`,
  `copilot-dev-plan.prompt.md`, `cursor-dev-plan.md`
- Modify (4): `claude-skill-dev-execute.md`, `claude-command-dev-execute.md`,
  `copilot-dev-execute.prompt.md`, `cursor-dev-execute.md`
- Modify (4): `claude-skill-dev-handover.md`, `claude-command-dev-handover.md`,
  `copilot-dev-handover.prompt.md`, `cursor-dev-handover.md`
- Modify: `src/center_kb/templates/init/QUICKSTART-dev.md:165-177`
- Test: `tests/test_templates.py` (extend the batch-7 section)

All twelve wrapper files live in `src/center_kb/templates/init/`.

**Interfaces:**
- Consumes: `docs/tdd-exemptions.md` and the PR template (Task 3);
  `REQUIRED_SECTIONS` (Task 1); the red test from Task 4.
- Produces: nothing later tasks consume — this is the batch's leaf.

- [ ] **Step 1: Write the remaining failing tests**

Append to the batch-7 section of `tests/test_templates.py`:

```python
DEV_PLAN_TEMPLATES = _dev_wrapper_names("dev-plan")
DEV_EXECUTE_TEMPLATES = _dev_wrapper_names("dev-execute")


def test_dev_plan_requires_an_exemption_line_for_a_task_with_no_test():
    for name in DEV_PLAN_TEMPLATES:
        body = _dev_wrapper_body(name)
        assert "docs/tdd-exemptions.md" in body, name
        assert _normalised("Exempt: <config|ci|docs|style>") in body, name


def test_dev_execute_honours_a_declared_exemption_and_refuses_an_undeclared_one():
    for name in DEV_EXECUTE_TEMPLATES:
        body = _dev_wrapper_body(name)
        assert "docs/tdd-exemptions.md" in body, name
        assert "Exempt:" in body, name
        # The undeclared case returns to dev-plan; it is never the
        # implementer's call.
        assert _normalised("return the task to `dev-plan`") in body, name


def test_dev_handover_reports_the_exemptions_or_none():
    for name in DEV_HANDOVER_TEMPLATES:
        body = _dev_wrapper_body(name)
        assert _normalised("## TDD exemptions") in body, name
        assert _normalised("`none`") in body, name


def test_quickstart_dev_names_the_pr_gate_and_the_required_check():
    text = _read_init_template("QUICKSTART-dev.md")
    assert "kb pr lint" in text
    assert "docs/tdd-exemptions.md" in text
    assert "required check" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_templates.py -q -k "batch or exempt or quickstart_dev or dev_handover_wrappers"`
Expected: the four new tests FAIL, plus the one left red from Task 4.

- [ ] **Step 3: Edit the four `dev-plan` wrappers**

In each of the four files, in the section that describes writing a task (the
one that already requires one task per AC with a test), add this paragraph.
Keep it outside every `## Freshness re-check`, `## Hard rules` and
`## Next step` block. Hard-wrap at ~72 columns to match the file:

```markdown
- **A task with no test declares its exemption.** Every task's first step is
  a failing test, with exactly four exceptions — config, CI, docs and style
  changes, defined in `docs/tdd-exemptions.md`. A task in one of those
  classes carries one line instead, and no other shape is accepted:
  `Exempt: <config|ci|docs|style> — verified by <what>`. The slug comes from
  that document; a change that fits none of the four is not exempt, and a
  change that alters behaviour an AC can see is never exempt whatever its
  file extension.
```

- [ ] **Step 4: Edit the four `dev-execute` wrappers**

In the per-task numbered loop (step 1 of which is "write the test → run it →
observe it fail"), add immediately after that numbered list:

```markdown
  A task block carrying an `Exempt:` line skips step 1 and runs the
  verification that line names instead, showing its output like any other.
  A task block with **no** `Exempt:` line whose implementer believes no test
  is possible does not decide that: stop and return the task to `dev-plan`,
  the same route an unimplementable AC takes. See `docs/tdd-exemptions.md`.
```

- [ ] **Step 5: Edit the four `dev-handover` wrappers**

Replace the **Assemble the PR description** bullet's contents so the eight
canon sections are named in canon order, and add the exemptions sentence:

```markdown
- **Assemble the PR description** using the repo's
  `.github/pull_request_template.md`, whose eight sections CI checks with
  `kb pr lint`: **Ticket**; **kb-context** refs so the reviewer can
  `kb resolve` them; the **AC→test map**; the **Placeholder resolutions**
  list; the **Verification** output, pasted inside a fenced block, not
  claimed; the **TDD exemptions** — every `Exempt:` line from the plan, or
  `none`; the **Findings**, every `OPEN(...)`, KB gap, ambiguity or
  contradiction as a concrete feedback item on the owning repo, or `none`;
  and the **Usage** table. A section left as the template's comment counts
  as empty and fails the check.
```

Keep the existing separate **Report the cost** bullet — it explains how to
produce the Usage table and what to write when the ledger is empty.

- [ ] **Step 6: Edit `QUICKSTART-dev.md`**

Under `## What is enforced` (line 165), amend the TDD bullet and add one:

```markdown
- **TDD** — no production code without a failing test observed first, at
  every step of `dev-execute`. No exception for a small ticket, a
  deadline, or an "obvious" change. The only exempt change classes —
  config, CI, docs, style — are named in `docs/tdd-exemptions.md`, are
  declared in the plan, and each owes a substitute verification.
- **The PR carries its evidence** — `.github/workflows/kb-pr-lint.yml`
  runs `kb pr lint` on every pull request and fails it when a required
  section of the description is missing, still holds the template's
  comment, or claims verification with no pasted output. Add **`pr-lint`
  to the branch's required checks** once: `kb init` writes the workflow
  but cannot turn on branch protection for you.
```

- [ ] **Step 7: Run the full suite**

Run: `pytest -q`
Expected: everything green — the batch-7 tests, the unchanged
`test_dev_wrappers_carry_byte_identical_shared_blocks` (20 files × 3 blocks),
and `test_shared_hard_rules_were_not_touched_by_the_c5_round`. If either canon
test fails, an edit landed inside a SHARED-* block: move it into the wrapper
body.

- [ ] **Step 8: Verify the MCP surface never moved**

Run: `git diff main...HEAD -- tests-gate/golden src/center_kb/mcp.py`
Expected: **empty output**.

- [ ] **Step 9: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
git commit -m "feat(skills): declare, honour and report TDD exemptions (roadmap E2)"
```

---

## Batch exit criteria

- `pytest -q` green; the count is the pre-batch 1873 passed / 5 skipped plus the
  new tests.
- `git diff main...HEAD -- tests-gate/golden src/center_kb/mcp.py` empty.
- `git diff main...HEAD -- uv.lock` empty (no new dependency).
- `kb init --kind dev` in a scratch directory produces all three new files, and
  `kb pr lint .github/pull_request_template.md` on that scratch repo **exits 1** —
  the untouched template is not a passing description.
- The roadmap's E1 and E2 checkboxes are ticked in
  `docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md`, with a
  short "đợt 7" note recording anything that shipped differently from this
  plan, in the style of the batch 2/3/4/5 notes already there.
