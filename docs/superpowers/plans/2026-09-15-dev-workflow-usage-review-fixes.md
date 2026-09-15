# Dev workflow + usage review fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Dev side's three load-bearing promises — evidence in
the PR, state in files, pinned content in the cache — a machine anchor
each, price the model ids Claude Code actually writes, and make the
conventions pack scaffold on real repo layouts.

**Architecture:** `prlint.py` grows finding levels, exemption slugs and a
`cmd.test` check that reads the plan from the checkout; `resolve.py` gains a
CLI-owned context-cache writer/validator behind two new `kb resolve` flags;
the 20 dev wrappers' SHARED-FRESHNESS and SHARED-NEXT-STEP canon change
once and are re-pinned in `test_templates.py`; `usage/prices.py` resolves
aliases and point-release suffixes; `conventions.py` + `initcmd.py` add
depth-3 detection and `kb init --lang`; `review.py` skips `hist.*` on a
whole-doc approve.

**Tech Stack:** Python 3.11+, typer CLI, pydantic v2, jinja2, pytest (real
filesystem, real git, no mocks), ruff. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-15-dev-workflow-usage-review-fixes-design.md`

## Global Constraints

- **Environment first.** `.venv/Scripts/python.exe` currently points at a
  uv-managed interpreter that is missing. Task 0 runs `uv sync` (uv lives
  at `~/.local/bin/uv.exe`; in Git Bash call it by that path) and proves
  one suite green before any edit. Do not `pip install` anything.
- **Test command:** `.venv/Scripts/python -m pytest <file> -q` — foreground,
  never in the background (a subagent waiting on its own background task is
  never woken). Lint: `.venv/Scripts/python -m ruff check src tests`.
- **The full suite takes 10–19 minutes.** Run only the named files per
  task; the whole suite runs once, in Task 15.
- **No new dependencies.** `uv.lock` must be byte-identical at the end
  (`uv lock --check` is a CI gate).
- **Windows commit messages go through a file**: write the message to
  `$TMP/msg.txt` and `git commit -F "$TMP/msg.txt"`. A PowerShell here-string
  passed with `-m` through the Bash tool silently commits a `@` subject.
  No attribution trailer (disabled globally).
- **One task, one commit, `git add` by explicit path** — never `git add -A`.
- **Template canon is pinned by `tests/test_templates.py`.** SHARED-*
  blocks are byte-identical across the 20 dev wrappers
  (`claude-skill-`, `claude-command-`, `copilot-…prompt`, `cursor-` × the
  five `DEV_WORKFLOW_SKILLS`). Any change to a shared block is made in all
  20 files and in `SHARED_BLOCK_TEXT` in the same task. The SHARED-HARD-RULES
  block is never touched (its length 1531 / 14 bullets is pinned).
- **Message style.** Every new error names the section or file it is
  about and the edit that fixes it.
- **Target release 0.23.0.** `pyproject.toml:3` is `0.22.0`; Task 15 bumps
  it. The `{version}` placeholder in `kb-pr-lint.yml` renders from it.
- **Spec deviation, recorded here and in Task 2:** the spec says the
  scaffolded `kb-pr-lint.yml` "already checks out the branch". It does not
  (its header comment says "No checkout" on purpose). Task 2 adds a
  read-only `actions/checkout@v4` step and amends the spec sentence.

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/center_kb/prlint.py` | PR-body gate: levels, exemption slugs, `cmd.test` fence check | 1, 2 |
| `src/center_kb/cli.py` | `pr lint --plan-dir`; `resolve --write-cache/--cache`; `usage note` defaults; `usage report` hook count; `doctor` usage-log check; `init --lang`; `approve` note; hook log guard | 2, 4, 10, 11, 12, 14 |
| `src/center_kb/resolve.py` | stale hint (M1); cache render/parse/validate | 3 |
| `src/center_kb/templates/init/kb-pr-lint.yml` | checkout step | 2 |
| `src/center_kb/templates/init/*dev-*` (20 wrappers) | SHARED-FRESHNESS canon; SHARED-NEXT-STEP State line; skill-specific text | 5, 6, 7, 8 |
| `src/center_kb/templates/init/QUICKSTART-dev.md` | "What is enforced" split | 8 |
| `src/center_kb/templates/init/conventions-*.md` | presets M5/M6/M8 | 13 |
| `src/center_kb/usage/prices.py`, `templates/usage/usage-prices.yaml` | aliases + suffix fallback | 9 |
| `src/center_kb/usage/report.py`, `templates/usage/report.html.j2` | est/assistant/priced_as/hook_errors, md warning | 10 |
| `src/center_kb/usage/ledger.py` | hook error log readers | 11 |
| `src/center_kb/doctor.py` | `check_usage_log` | 11 |
| `src/center_kb/conventions.py`, `initcmd.py`, `config.py` | depth 3, forced langs, `langs:` persistence | 12 |
| `src/center_kb/review.py` | `hist.*` skip | 14 |
| `docs/superpowers/specs/2026-08-19-dev-agent-design.md` | amendment note | 7 |
| `CHANGELOG.md`, `pyproject.toml` | release | 15 |

---

### Task 0: Environment and baseline

**Files:** none changed.

- [ ] **Step 1: Restore the interpreter**

Run (PowerShell): `uv sync` — or in Git Bash: `~/.local/bin/uv.exe sync`.
Expected: exits 0; `.venv/Scripts/python.exe --version` prints `Python 3.1x`.

- [ ] **Step 2: Prove one suite green**

Run: `.venv/Scripts/python -m pytest tests/test_prlint.py tests/test_cli_prlint.py -q`
Expected: all pass (31 tests at the time of writing).

- [ ] **Step 3: Confirm the lockfile is untouched**

Run: `git status --short uv.lock`
Expected: no output. Nothing to commit for this task.

---

### Task 1: `prlint` — finding levels and exemption slugs

**Files:**
- Modify: `src/center_kb/prlint.py`
- Test: `tests/test_prlint.py`

**Interfaces:**
- Produces: `Finding(section, code, message, level="error"|"warning")`,
  `PRLintReport.errors`, `PRLintReport.warnings`, `PRLintReport.passed`
  (no error-level findings), `EXEMPTION_SLUGS`, finding code
  `unknown-exemption-class`. `to_json()` findings carry `level`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prlint.py`:

```python
from center_kb.prlint import EXEMPTION_SLUGS, Finding, PRLintReport


def test_the_four_exemption_slugs_are_the_canon():
    assert EXEMPTION_SLUGS == frozenset({"config", "ci", "docs", "style"})


def test_exemption_lines_naming_a_known_slug_pass():
    body = _body(**{"TDD exemptions": (
        "- config: ruff.toml — verified by running `ruff check .`\n"
        "- docs — README only, rendered locally\n"
        "Exempt: ci — verified by the workflow's own run on this PR\n"
        "- `style`: renames, suite green before and after"
    )})
    assert lint_body(body).passed


def test_none_still_passes_the_exemption_section():
    assert lint_body(_body(**{"TDD exemptions": "None."})).passed


def test_an_unknown_exemption_class_is_an_error():
    report = lint_body(_body(**{"TDD exemptions": "Exempt: deadline"}))
    assert not report.passed
    (f,) = [f for f in report.findings if f.section == "TDD exemptions"]
    assert f.code == "unknown-exemption-class"
    assert f.level == "error"
    for slug in ("config", "ci", "docs", "style"):
        assert slug in f.message


def test_prose_in_the_exemption_section_is_an_error():
    body = _body(**{"TDD exemptions": "we skipped tests because it was late"})
    assert ("TDD exemptions", "unknown-exemption-class") in _codes(body)


def test_a_warning_level_finding_does_not_fail_the_report():
    report = PRLintReport((Finding("Ticket", "x", "y", level="warning"),))
    assert report.passed
    assert report.warnings == report.findings
    assert report.errors == ()
    assert "warning" in report.render()
    assert report.to_json()["findings"][0]["level"] == "warning"


def test_findings_default_to_error_level():
    assert Finding("Ticket", "x", "y").level == "error"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_prlint.py -q`
Expected: ImportError on `EXEMPTION_SLUGS` / `Finding` (collection fails).

- [ ] **Step 3: Implement**

In `src/center_kb/prlint.py`, add after `SENTINEL_SECTIONS`:

```python
# The four exemption classes of `docs/tdd-exemptions.md`, mirrored here so
# `## TDD exemptions` cannot pass on `Exempt: deadline` (reviewer F, H1).
EXEMPTION_SLUGS: frozenset[str] = frozenset({"config", "ci", "docs", "style"})

# One exemption per line, in either the plan's shape
# (`Exempt: config — verified by …`) or a bullet (`- config: …`). The slug
# may be back-ticked; the separator is `:`, `—`, `–` or `-`.
_EXEMPTION_LINE = re.compile(
    r"^(?:-\s*)?(?:Exempt:\s*)?`?(?P<slug>[a-z]+)`?\s*(?::|—|–|-)\s*\S"
)
_NONE = re.compile(r"^none\.?$", re.IGNORECASE)

Level = Literal["error", "warning"]
```

Add `from typing import Literal` to the imports. Change `Finding` and
`PRLintReport`:

```python
@dataclass(frozen=True)
class Finding:
    section: str
    code: str
    message: str
    level: Level = "error"


@dataclass(frozen=True)
class PRLintReport:
    findings: tuple[Finding, ...]

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.level == "error")

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.level == "warning")

    @property
    def passed(self) -> bool:
        return not self.errors

    def render(self) -> str:
        if self.passed:
            lines = [
                f"PR description: PASS — all {len(REQUIRED_SECTIONS)} required "
                "sections present and filled."
            ]
        else:
            lines = [f"PR description: FAIL ({len(self.errors)} finding(s))"]
            lines.extend(
                f"  [{f.code}] ## {f.section}: {f.message}" for f in self.errors
            )
        if self.warnings:
            lines.append("warnings:")
            lines.extend(
                f"  [{f.code}] ## {f.section}: {f.message}" for f in self.warnings
            )
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {
            "passed": self.passed,
            "findings": [
                {
                    "section": f.section,
                    "code": f.code,
                    "message": f.message,
                    "level": f.level,
                }
                for f in self.findings
            ],
        }
```

Add the section check, placed before `lint_body`:

```python
def _exemption_finding(visible: str) -> Finding | None:
    """`none`, or every non-blank line names one of EXEMPTION_SLUGS."""
    if _NONE.match(visible.strip()):
        return None
    for line in visible.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        m = _EXEMPTION_LINE.match(stripped)
        if m is None or m["slug"] not in EXEMPTION_SLUGS:
            return Finding(
                "TDD exemptions",
                "unknown-exemption-class",
                f"line {stripped[:60]!r} names no exemption class — each line "
                "is `Exempt: <slug> — verified by <what>` (or `- <slug>: …`) "
                f"with <slug> one of {', '.join(sorted(EXEMPTION_SLUGS))}, or "
                "the whole section reads `none`",
            )
    return None
```

In `lint_body`, after the `Verification` check inside the loop, add:

```python
        if section == "TDD exemptions":
            bad = _exemption_finding(visible)
            if bad is not None:
                findings.append(bad)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_prlint.py tests/test_cli_prlint.py -q`
Expected: all pass. (`test_render_names_the_failing_sections_and_to_json_round_trips`
may assert the exact JSON keys — if it compares whole dicts, add `"level":
"error"` to its expected value; that is the only permitted edit to an
existing test in this task.)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/prlint.py tests/test_prlint.py
printf '%s\n' "feat(prlint): finding levels and the four exemption slugs (F-H1)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 2: `prlint` — `cmd.test` must appear in the Verification fence

**Files:**
- Modify: `src/center_kb/prlint.py`
- Modify: `src/center_kb/cli.py:2176-2215` (`pr_lint`)
- Modify: `src/center_kb/templates/init/kb-pr-lint.yml`
- Modify: `docs/superpowers/specs/2026-09-15-dev-workflow-usage-review-fixes-design.md` (one sentence)
- Test: `tests/test_prlint.py`, `tests/test_cli_prlint.py`, `tests/test_templates.py`

**Interfaces:**
- Consumes: `Finding(level=...)` from Task 1.
- Produces: `lint_body(body, *, plan_dir: Path | None = None)`;
  `plan_cmd_test(plan_dir, ticket_id) -> str | None`;
  `ticket_id_of(visible_ticket_section) -> str | None`; finding codes
  `verification-missing-cmd` (error), `plan-dir-unset`,
  `ticket-id-unparsed`, `plan-missing`, `cmd-test-unset` (warnings).
  CLI flag `kb pr lint --plan-dir PATH` (default `docs/impl`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prlint.py`:

```python
from pathlib import Path

from center_kb.prlint import plan_cmd_test, ticket_id_of


def _plan(tmp_path: Path, ticket: str = "ATM-7", cmd: str = "pytest -q") -> Path:
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / f"{ticket}-plan.md").write_text(
        f"# {ticket} plan\n\ncmd.test: `{cmd}`\ncmd.lint: ruff check .\nstatus: approved\n",
        encoding="utf-8",
    )
    return d


def _ticket_body(**overrides: str) -> str:
    return _body(Ticket="ATM-7 — add the new-flight endpoint", **overrides)


def test_ticket_id_is_the_first_upper_dash_number_token():
    assert ticket_id_of("ATM-7 — add the endpoint") == "ATM-7"
    assert ticket_id_of("see PROJ-10 and PROJ-2") == "PROJ-10"
    assert ticket_id_of("open-new-flight — no id here") is None


def test_plan_cmd_test_reads_the_header_line_and_strips_backticks(tmp_path: Path):
    d = _plan(tmp_path)
    assert plan_cmd_test(d, "ATM-7") == "pytest -q"
    assert plan_cmd_test(d, "ATM-8") is None


def test_verification_fence_holding_cmd_test_passes(tmp_path: Path):
    d = _plan(tmp_path)
    body = _ticket_body(Verification="```\n$ pytest -q\n12 passed in 0.4s\n```")
    report = lint_body(body, plan_dir=d)
    assert report.passed, report.render()
    assert report.warnings == ()


def test_verification_fence_without_cmd_test_is_an_error(tmp_path: Path):
    d = _plan(tmp_path)
    body = _ticket_body(Verification="```\n12 passed in 0.4s\n```")
    report = lint_body(body, plan_dir=d)
    assert not report.passed
    (f,) = [f for f in report.errors if f.code == "verification-missing-cmd"]
    assert "pytest -q" in f.message and "ATM-7-plan.md" in f.message


def test_cmd_test_in_prose_outside_the_fence_does_not_count(tmp_path: Path):
    d = _plan(tmp_path)
    body = _ticket_body(Verification="ran pytest -q\n\n```\n12 passed\n```")
    assert not lint_body(body, plan_dir=d).passed


def test_no_plan_dir_is_a_warning_not_a_failure():
    report = lint_body(_ticket_body())
    assert report.passed
    assert [f.code for f in report.warnings] == ["plan-dir-unset"]


def test_unparsed_ticket_id_is_a_warning(tmp_path: Path):
    report = lint_body(_body(), plan_dir=_plan(tmp_path))
    assert report.passed
    assert [f.code for f in report.warnings] == ["ticket-id-unparsed"]


def test_missing_plan_file_is_a_warning(tmp_path: Path):
    report = lint_body(_ticket_body(), plan_dir=tmp_path / "nowhere")
    assert report.passed
    assert [f.code for f in report.warnings] == ["plan-missing"]


def test_plan_without_a_cmd_test_line_is_a_warning(tmp_path: Path):
    d = tmp_path / "docs" / "impl"
    d.mkdir(parents=True)
    (d / "ATM-7-plan.md").write_text("# plan\n\nstatus: draft\n", encoding="utf-8")
    report = lint_body(_ticket_body(), plan_dir=d)
    assert report.passed
    assert [f.code for f in report.warnings] == ["cmd-test-unset"]
```

Append to `tests/test_cli_prlint.py`:

```python
def test_plan_dir_defaults_to_docs_impl_and_warns_when_absent(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    body = tmp_path / "body.md"
    body.write_text(GOOD.replace("## Ticket\n\nfilled", "## Ticket\n\nATM-7 x"), encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body)])
    assert result.exit_code == 0, result.output
    assert "plan-missing" in result.output


def test_plan_dir_flag_enforces_cmd_test(tmp_path: Path):
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "ATM-7-plan.md").write_text("# p\n\ncmd.test: pytest -q\n", encoding="utf-8")
    body = tmp_path / "body.md"
    body.write_text(GOOD.replace("## Ticket\n\nfilled", "## Ticket\n\nATM-7 x"), encoding="utf-8")
    result = runner.invoke(app, ["pr", "lint", str(body), "--plan-dir", str(plans)])
    assert result.exit_code == 1
    assert "verification-missing-cmd" in result.output
```

Append to `tests/test_templates.py` (next to the other `kb-pr-lint.yml` tests):

```python
def test_pr_workflow_checks_out_the_branch_read_only_for_the_plan_file():
    import yaml

    wf = yaml.safe_load(_read_init_template("kb-pr-lint.yml"))
    steps = wf["jobs"]["pr-lint"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    assert steps.index(checkout) < steps.index(next(s for s in steps if "Check the PR" in s.get("name", "")))
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_prlint.py tests/test_cli_prlint.py -q -k "cmd_test or plan or ticket_id or warning"`
Expected: ImportError / TypeError on `plan_dir`.

- [ ] **Step 3: Implement**

In `src/center_kb/prlint.py` add `from pathlib import Path` and:

```python
_TICKET_ID = re.compile(r"\b[A-Z][A-Z0-9]*-\d+\b")
_CMD_TEST = re.compile(r"^cmd\.test:\s*(?P<cmd>\S.*?)\s*$", re.MULTILINE)


def ticket_id_of(visible_ticket_section: str) -> str | None:
    """First `ABC-12`-shaped token in the visible `## Ticket` text."""
    m = _TICKET_ID.search(visible_ticket_section)
    return m.group(0) if m else None


def plan_cmd_test(plan_dir: Path, ticket_id: str) -> str | None:
    """The plan's `cmd.test:` header value, back-ticks stripped; None when the
    plan or the line is absent (an unreadable plan reads as absent)."""
    try:
        text = (plan_dir / f"{ticket_id}-plan.md").read_text(encoding="utf-8")
    except OSError:
        return None
    m = _CMD_TEST.search(text)
    return m["cmd"].strip("`").strip() if m else None


def _fenced_blocks(text: str) -> list[str]:
    """The bodies of every balanced fenced block, in order."""
    blocks: list[str] = []
    open_fence = ""
    current: list[str] = []
    for line in text.split("\n"):
        marker = _is_fence(line)
        if not open_fence:
            if marker:
                open_fence = marker
                current = []
            continue
        if marker == open_fence:
            blocks.append("\n".join(current))
            open_fence = ""
            continue
        current.append(line)
    return blocks


def _plan_findings(first: dict[str, str], plan_dir: Path | None) -> list[Finding]:
    """The cmd.test check, or the one warning saying why it did not run."""
    if plan_dir is None:
        return [Finding("Verification", "plan-dir-unset",
                        "no plan directory given — the cmd.test check did not run",
                        level="warning")]
    ticket_id = ticket_id_of(_visible(first.get("Ticket", "")))
    if ticket_id is None:
        return [Finding("Ticket", "ticket-id-unparsed",
                        "no ABC-12-shaped ticket id found, so the plan's cmd.test "
                        "could not be checked — start the section with the id",
                        level="warning")]
    plan_path = plan_dir / f"{ticket_id}-plan.md"
    if not plan_path.is_file():
        return [Finding("Verification", "plan-missing",
                        f"{plan_path} not found — the cmd.test check did not run "
                        "(spike or no plan yet)",
                        level="warning")]
    cmd = plan_cmd_test(plan_dir, ticket_id)
    if cmd is None:
        return [Finding("Verification", "cmd-test-unset",
                        f"{plan_path} has no `cmd.test:` header line — the "
                        "cmd.test check did not run",
                        level="warning")]
    fences = _fenced_blocks(_visible(first.get("Verification", "")))
    if any(cmd in block for block in fences):
        return []
    return [Finding("Verification", "verification-missing-cmd",
                    f"no fenced block contains the plan's cmd.test `{cmd}` "
                    f"(from {plan_path}) — paste that command's real run")]
```

Change `_has_fenced_output` to reuse `_fenced_blocks`:

```python
def _has_fenced_output(text: str) -> bool:
    """True when a fenced block holds at least one non-blank line."""
    return any(block.strip() for block in _fenced_blocks(text))
```

Change `lint_body`'s signature and tail:

```python
def lint_body(body: str, *, plan_dir: Path | None = None) -> PRLintReport:
    ...
    # (existing loop unchanged)
    findings.extend(_plan_findings(first, plan_dir))
    return PRLintReport(tuple(findings))
```

In `cli.py` `pr_lint`, add the option and pass it:

```python
    plan_dir: Path = typer.Option(
        Path("docs/impl"),
        "--plan-dir",
        help="Where docs/impl/<ticket-id>-plan.md lives; its `cmd.test:` line "
        "must appear inside a Verification fence. Absent plan = warning.",
    ),
```
and `report = lint_body(text, plan_dir=plan_dir)`.

In `kb-pr-lint.yml`, replace the paragraph starting `# No checkout, no hub
URL, no token:` with:

```yaml
# Read-only checkout, no hub URL, no token: `kb pr lint` reads the PR body
# plus `docs/impl/<ticket-id>-plan.md` from the branch (its `cmd.test:` must
# appear inside the Verification fence). `persist-credentials: false` keeps
# the job green and inert on pull requests from forks.
```
and insert as the first step of `pr-lint`:

```yaml
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
```

In the spec (§1, "CLI" paragraph) replace "The scaffolded `kb-pr-lint.yml`
already checks out the branch, so the default finds the plan without a
workflow change." with "The scaffolded `kb-pr-lint.yml` gains a read-only
`actions/checkout@v4` step (`persist-credentials: false`) so the plan file
is present; the job stays green on fork PRs."

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_prlint.py tests/test_cli_prlint.py tests/test_templates.py -q -k "prlint or pr_workflow or pr_lint or plan or ticket_id or exemption"`
Expected: all pass, including the pre-existing `test_pr_workflow_never_interpolates_the_body_into_the_script`.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/prlint.py src/center_kb/cli.py src/center_kb/templates/init/kb-pr-lint.yml tests/test_prlint.py tests/test_cli_prlint.py tests/test_templates.py docs/superpowers/specs/2026-09-15-dev-workflow-usage-review-fixes-design.md
printf '%s\n' "feat(prlint): Verification fence must hold the plan's cmd.test; --plan-dir; read-only checkout in kb-pr-lint.yml (F-H1)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 3: `resolve.py` — stale hint (M1) and the cache render/parse/validate primitives

**Files:**
- Modify: `src/center_kb/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Produces: `CACHE_MARKER = "<!-- kb:placeholder-map -->"`,
  `refs_of(results) -> frozenset[str]`, `cache_digest(segment: str) -> str`,
  `render_cache(ctx_version, results, *, today, stem, previous) -> str`,
  `read_cache_header(text) -> CacheHeader | None`,
  `cache_problem(text, ctx_version, results) -> str` ('' when valid).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resolve.py`:

```python
from center_kb.resolve import (
    CACHE_MARKER,
    cache_digest,
    cache_problem,
    read_cache_header,
    refs_of,
    render_cache,
)


def _results(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    return ctx, resolve_refs(handle, ctx)


def test_stale_hint_names_kb_get_never_kb_diff(fed_hub, run_git):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"), encoding="utf-8")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "republish")
    text = render_resolved(resolve_refs(handle, ctx), include_content=False)
    assert "kb diff" not in text
    assert "run `kb get arinc-424 5.3 --level l3` for the current hub version" in text


def test_render_cache_layout_and_header(fed_hub):
    ctx, results = _results(fed_hub)
    text = render_cache(ctx.version, results, today="2026-09-15", stem="T-7", previous=None)
    assert text.startswith("# Context cache — T-7\n")
    hdr = read_cache_header(text)
    assert hdr is not None
    assert hdr.version == ctx.version
    assert hdr.refs == refs_of(results) == frozenset({"arinc-kb:arinc-424 §5.3"})
    assert "## Resolved sections\n" in text
    assert "Condensed: restrictive airspace" in text
    assert text.index(CACHE_MARKER) > text.index("## Resolved sections")
    assert text.rstrip().endswith("|---|---|---|")
    assert cache_problem(text, ctx.version, results) == ""


def test_render_cache_carries_the_placeholder_map_over_byte_for_byte(fed_hub):
    ctx, results = _results(fed_hub)
    first = render_cache(ctx.version, results, today="2026-09-15", stem="T-7", previous=None)
    edited = first + "| <max-alt> | 45000 | src/limits.py:12 |\n"
    second = render_cache(ctx.version, results, today="2026-09-16", stem="T-7", previous=edited)
    assert second[second.index(CACHE_MARKER):] == edited[edited.index(CACHE_MARKER):]
    assert cache_problem(second, ctx.version, results) == ""


def test_editing_above_the_marker_is_detected(fed_hub):
    ctx, results = _results(fed_hub)
    text = render_cache(ctx.version, results, today="2026-09-15", stem="T-7", previous=None)
    tampered = text.replace("Condensed: restrictive airspace", "Condensed: whatever I remember")
    assert cache_problem(tampered, ctx.version, results) == "resolved block edited since written"


def test_editing_below_the_marker_is_allowed(fed_hub):
    ctx, results = _results(fed_hub)
    text = render_cache(ctx.version, results, today="2026-09-15", stem="T-7", previous=None)
    assert cache_problem(text + "| x | y | z |\n", ctx.version, results) == ""


def test_a_foreign_cache_is_detected_by_its_ref_set(fed_hub):
    ctx, results = _results(fed_hub)
    other_ctx = _ctx_for(fed_hub, ["icao-kb:icao-annex-2 §1.1"])
    other = render_cache(other_ctx.version, resolve_refs(HubHandle(root=fed_hub), other_ctx),
                         today="2026-09-15", stem="T-8", previous=None)
    problem = cache_problem(other, ctx.version, results)
    assert problem.startswith("refs differ")
    assert "arinc-kb:arinc-424 §5.3" in problem


def test_a_version_mismatch_is_detected(fed_hub):
    ctx, results = _results(fed_hub)
    text = render_cache("deadbeef", results, today="2026-09-15", stem="T-7", previous=None)
    assert cache_problem(text, ctx.version, results) == f"version deadbeef != ticket {ctx.version}"


def test_a_headerless_file_is_invalid(fed_hub):
    ctx, results = _results(fed_hub)
    assert read_cache_header("just prose\n") is None
    assert cache_problem("just prose\n", ctx.version, results) == "header"


def test_cache_digest_is_sha256_of_the_segment():
    import hashlib
    assert cache_digest("abc\n") == hashlib.sha256(b"abc\n").hexdigest()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_resolve.py -q`
Expected: ImportError on `CACHE_MARKER`.

- [ ] **Step 3: Implement**

In `resolve.py`, add `import hashlib`, `import re` to the imports and, after
`render_resolved`, replace the stale line and add the cache primitives:

```python
        elif r.status == "stale":
            parts.append(
                f"!! {r.reason} — run `kb get {r.ref.doc_id} {r.ref.section_id} "
                "--level l3` for the current hub version"
            )
```

```python
# --- Context cache (docs/impl/<ticket-id>-context.md), reviewer F H3 --------
# The CLI owns everything above CACHE_MARKER (header + resolved sections);
# the agent owns the `## Placeholder map` below it. The sha256 covers the
# bytes between the "## Resolved sections" heading line and the marker line,
# so a hand-edit of pinned content is detected and an edit of the map is not.

CACHE_MARKER = "<!-- kb:placeholder-map -->"
_RESOLVED_HEADING = "## Resolved sections\n"
_PLACEHOLDER_STUB = (
    "## Placeholder map\n"
    "| placeholder | verified value | evidence (file:line or ref) |\n"
    "|---|---|---|\n"
)
_HEADER_FIELDS = {
    key: re.compile(rf"^{key}:[ \t]*(?P<v>.*?)[ \t]*$", re.MULTILINE)
    for key in ("version", "refs", "sha256")
}


@dataclass(frozen=True)
class CacheHeader:
    version: str
    refs: frozenset[str]
    sha256: str


def refs_of(results: list[ResolvedRef]) -> frozenset[str]:
    """The resolved ref set in citation form (`repo:doc §sec`), post-
    disambiguation, so writer and checker compare the same strings."""
    return frozenset(str(r.ref) for r in results)


def cache_digest(segment: str) -> str:
    return hashlib.sha256(segment.encode("utf-8")).hexdigest()


def render_cache(
    ctx_version: str,
    results: list[ResolvedRef],
    *,
    today: str,
    stem: str,
    previous: str | None,
) -> str:
    """The whole cache file. `previous` (the current file text, if any)
    contributes everything from CACHE_MARKER down, byte for byte."""
    segment = render_resolved(results) + "\n\n"
    if previous is not None and CACHE_MARKER in previous:
        tail = previous[previous.index(CACHE_MARKER):]
    else:
        tail = CACHE_MARKER + "\n" + _PLACEHOLDER_STUB
    header = (
        f"# Context cache — {stem}\n"
        "> Written by `kb resolve --write-cache`. Do not hand-edit above the\n"
        "> marker; regenerated on every full resolve. Gitignored.\n\n"
        f"version: {ctx_version}\n"
        f"refs: {', '.join(sorted(refs_of(results)))}\n"
        f"sha256: {cache_digest(segment)}\n"
        f"resolved: {today}\n\n"
    )
    return header + _RESOLVED_HEADING + segment + tail


def read_cache_header(text: str) -> CacheHeader | None:
    if _RESOLVED_HEADING not in text or CACHE_MARKER not in text:
        return None
    head = text[: text.index(_RESOLVED_HEADING)]
    values: dict[str, str] = {}
    for key, rx in _HEADER_FIELDS.items():
        m = rx.search(head)
        if m is None:
            return None
        values[key] = m["v"]
    refs = frozenset(s.strip() for s in values["refs"].split(",") if s.strip())
    return CacheHeader(values["version"], refs, values["sha256"])


def cache_problem(text: str, ctx_version: str, results: list[ResolvedRef]) -> str:
    """'' when the cache belongs to this ticket and is untouched above the
    marker; otherwise the one-line reason for `!! cache-invalid:`."""
    hdr = read_cache_header(text)
    if hdr is None:
        return "header"
    if hdr.version != ctx_version:
        return f"version {hdr.version} != ticket {ctx_version}"
    want = refs_of(results)
    if hdr.refs != want:
        missing = ", ".join(sorted(want - hdr.refs)) or "-"
        extra = ", ".join(sorted(hdr.refs - want)) or "-"
        return f"refs differ — missing {missing}; extra {extra}"
    start = text.index(_RESOLVED_HEADING) + len(_RESOLVED_HEADING)
    segment = text[start : text.index(CACHE_MARKER)]
    if cache_digest(segment) != hdr.sha256:
        return "resolved block edited since written"
    return ""
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_resolve.py tests/test_cli_context.py -q`
Expected: all pass except any pre-existing test pinning the `kb diff`
wording (`test_removed_document_is_broken_and_hints_a_command_that_works`
checks the *broken* path and is unaffected; if another test asserts
`kb diff` in a stale line, update that assertion to the new `kb get` text).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/resolve.py tests/test_resolve.py
printf '%s\n' "feat(resolve): context-cache render/parse/validate primitives; stale hint names kb get, not kb diff (F-H3, F-M1)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 4: `kb resolve --write-cache` and `--status-only --cache`

**Files:**
- Modify: `src/center_kb/cli.py:2038-2076` (`resolve`)
- Test: `tests/test_cli_context.py`

**Interfaces:**
- Consumes: `render_cache`, `cache_problem`, `CACHE_MARKER` (Task 3).
- Produces: `kb resolve --write-cache PATH` (side effect only; stdout
  unchanged); `kb resolve --status-only --cache PATH` appends
  `!! cache-missing: <path>` or `!! cache-invalid: <reason>` and exits 1.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_context.py`:

```python
def _block(fed_hub, run_git, ref="arinc-kb:arinc-424 §5.3"):
    head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    return f'kb-context:\n  version: "{head}"\n  refs:\n    - {ref}\n'


def _resolve(args, fixture_kb, fed_hub, block):
    return runner.invoke(
        app, ["resolve", "-", *args, "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
        input=block,
    )


def test_write_cache_writes_the_file_and_leaves_stdout_unchanged(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "docs" / "impl" / "T-7-context.md"
    block = _block(fed_hub, run_git)
    plain = _resolve([], fixture_kb, fed_hub, block)
    result = _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    assert result.exit_code == 0, result.output
    assert result.output == plain.output
    text = cache.read_text(encoding="utf-8")
    assert text.startswith("# Context cache — T-7\n")
    assert "<!-- kb:placeholder-map -->" in text
    assert "Condensed: restrictive airspace" in text


def test_status_only_cache_round_trip_exits_zero(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    block = _block(fed_hub, run_git)
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    result = _resolve(["--status-only", "--cache", str(cache)], fixture_kb, fed_hub, block)
    assert result.exit_code == 0, result.output
    assert "cache-" not in result.output
    assert "Condensed" not in result.output


def test_status_only_cache_missing_exits_one(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    result = _resolve(["--status-only", "--cache", str(cache)], fixture_kb, fed_hub, _block(fed_hub, run_git))
    assert result.exit_code == 1
    assert f"!! cache-missing: {cache}" in result.output


def test_status_only_cache_edited_above_the_marker_exits_one(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    block = _block(fed_hub, run_git)
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    cache.write_text(cache.read_text(encoding="utf-8").replace("restrictive", "permissive"), encoding="utf-8")
    result = _resolve(["--status-only", "--cache", str(cache)], fixture_kb, fed_hub, block)
    assert result.exit_code == 1
    assert "!! cache-invalid: resolved block edited since written" in result.output


def test_status_only_cache_of_another_ticket_exits_one(fed_hub, fixture_kb, run_git, tmp_path):
    other = tmp_path / "T-8-context.md"
    _resolve(["--write-cache", str(other)], fixture_kb, fed_hub, _block(fed_hub, run_git, "icao-kb:icao-annex-2 §1.1"))
    result = _resolve(["--status-only", "--cache", str(other)], fixture_kb, fed_hub, _block(fed_hub, run_git))
    assert result.exit_code == 1
    assert "!! cache-invalid: refs differ" in result.output


def test_status_only_cache_placeholder_map_edits_are_fine(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    block = _block(fed_hub, run_git)
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    with cache.open("a", encoding="utf-8") as fh:
        fh.write("| <max-alt> | 45000 | src/limits.py:12 |\n")
    result = _resolve(["--status-only", "--cache", str(cache)], fixture_kb, fed_hub, block)
    assert result.exit_code == 0, result.output


def test_write_cache_preserves_the_map_on_regeneration(fed_hub, fixture_kb, run_git, tmp_path):
    cache = tmp_path / "T-7-context.md"
    block = _block(fed_hub, run_git)
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    with cache.open("a", encoding="utf-8") as fh:
        fh.write("| <max-alt> | 45000 | src/limits.py:12 |\n")
    _resolve(["--write-cache", str(cache)], fixture_kb, fed_hub, block)
    assert "| <max-alt> | 45000 |" in cache.read_text(encoding="utf-8")


def test_stale_ticket_with_a_bad_cache_exits_one_not_two(fed_hub, fixture_kb, run_git, tmp_path):
    block = _block(fed_hub, run_git)
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"), encoding="utf-8")
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "amend")
    result = _resolve(["--status-only", "--cache", str(tmp_path / "none.md")], fixture_kb, fed_hub, block)
    assert result.exit_code == 1
    assert "status=stale" in result.output and "cache-missing" in result.output


def test_cache_flag_combinations_are_usage_errors(fed_hub, fixture_kb, run_git, tmp_path):
    block = _block(fed_hub, run_git)
    p = str(tmp_path / "c.md")
    assert _resolve(["--cache", p], fixture_kb, fed_hub, block).exit_code == 1
    assert _resolve(["--status-only", "--write-cache", p], fixture_kb, fed_hub, block).exit_code == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_cli_context.py -q -k cache`
Expected: `No such option: --write-cache`, exit code 2 assertions fail.

- [ ] **Step 3: Implement**

In `cli.py` `resolve`, add two options after `status_only`:

```python
    write_cache: Path | None = typer.Option(
        None,
        "--write-cache",
        help="Also write docs/impl/<ticket-id>-context.md: header (version, "
        "refs, sha256) + the resolved sections; everything below the "
        "`<!-- kb:placeholder-map -->` marker is kept from the existing file.",
    ),
    cache: Path | None = typer.Option(
        None,
        "--cache",
        help="With --status-only: validate this context cache against the "
        "ticket (version, ref set, sha256 of the resolved block); a bad or "
        "missing cache exits 1.",
    ),
```

Right after the `from center_kb.resolve import …` line, extend the import
to `render_cache, cache_problem` and add the flag-combination guards
before any hub access:

```python
    if write_cache is not None and status_only:
        typer.secho("--write-cache needs a full resolve; drop --status-only", fg=typer.colors.RED)
        raise typer.Exit(1)
    if cache is not None and not status_only:
        typer.secho("--cache only makes sense with --status-only", fg=typer.colors.RED)
        raise typer.Exit(1)
```

Replace the tail (from `typer.echo(render_resolved(...))` to the end) with:

```python
    typer.echo(render_resolved(results, include_content=not status_only))
    if write_cache is not None:
        from datetime import date

        previous = (
            write_cache.read_text(encoding="utf-8") if write_cache.exists() else None
        )
        stem = write_cache.stem.removesuffix("-context")
        try:
            write_cache.parent.mkdir(parents=True, exist_ok=True)
            write_cache.write_text(
                render_cache(ctx.version, results, today=date.today().isoformat(),
                             stem=stem, previous=previous),
                encoding="utf-8", newline="\n",
            )
        except OSError as exc:
            typer.secho(f"could not write cache '{write_cache}': {exc}", fg=typer.colors.RED)
            raise typer.Exit(1)
    cache_bad = False
    if cache is not None:
        if not cache.is_file():
            typer.echo(f"!! cache-missing: {cache}")
            cache_bad = True
        else:
            try:
                cache_text = cache.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                cache_text = ""
            problem = cache_problem(cache_text, ctx.version, results) if cache_text else "header"
            if problem:
                typer.echo(f"!! cache-invalid: {problem}")
                cache_bad = True
    if cache_bad or any(r.status == "broken" for r in results):
        raise typer.Exit(1)
    if any(r.status == "stale" for r in results):
        raise typer.Exit(2)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_cli_context.py tests/test_resolve.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py tests/test_cli_context.py
printf '%s\n' "feat(resolve): --write-cache and --status-only --cache give the context cache a machine anchor (F-H3)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 5: SHARED-FRESHNESS canon — the cache is CLI-written and CLI-checked

**Files:**
- Modify: all 20 dev wrappers in `src/center_kb/templates/init/` —
  `claude-skill-`, `claude-command-`, `copilot-…prompt.md`, `cursor-` for
  `dev-implement-ticket`, `dev-design`, `dev-plan`, `dev-execute`,
  `dev-handover` (list them with `ls src/center_kb/templates/init | grep -E '^(claude-skill|claude-command|copilot|cursor)-dev-(implement-ticket|design|plan|execute|handover)'`).
- Modify: `src/center_kb/templates/init/{claude-skill,copilot,cursor,claude-command}-dev-implement-ticket*` Resolve + Placeholders steps.
- Modify: `docs/superpowers/specs/2026-08-24-c1-context-cache-design.md` (one dated line under §2).
- Test: `tests/test_templates.py` (`SHARED_BLOCK_TEXT["SHARED-FRESHNESS"]`, the two C1 needle tests, the ceiling).

**Interfaces:**
- Consumes: the CLI flags from Task 4 (names only).

- [ ] **Step 1: Update the canon and needles in the test first**

In `tests/test_templates.py` replace the `'SHARED-FRESHNESS':` value in
`SHARED_BLOCK_TEXT` with the repr of exactly this text (write the block to
the first wrapper, then copy it with `python -c "print(repr(open(...).read()[start:end]))"` — never hand-retype):

```markdown
## Freshness re-check (run this FIRST, every time)

Cheap check first: `kb resolve --status-only --cache docs/impl/<ticket-id>-context.md <ticket-file>` (no CLI → `kb_resolve`; check the cache `version:` yourself). Exit 0 → use the cache, do NOT re-pull pinned content. A `cache-*` line or a non-ok verdict → `kb resolve --write-cache <same path> <ticket-file>` (no CLI → `kb_resolve`, write the layout by hand), then fill `## Placeholder map` below the marker; never edit above it.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a
  citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: the resolve gives the
  pinned content and the reason, `kb get <doc-id> <section> [--level l3]`
  the current hub version. Do NOT use `kb diff` — it compares the local
  `.kb/` worktree to a local git rev, not this repo to the hub.
- **ok** → continue.
```

The paragraph may be hard-wrapped at ~76 columns (needle tests normalise
whitespace). Replace `test_shared_freshness_prefers_the_cache_and_status_only`:

```python
def test_shared_freshness_prefers_the_cache_and_status_only():
    block = _normalised(SHARED_BLOCK_TEXT["SHARED-FRESHNESS"])
    for needle in ("--status-only --cache", "-context.md", "--write-cache",
                   "below the marker", "never edit above it", "`cache-*`"):
        assert needle in block, needle
```

Keep `test_shared_freshness_keeps_the_kb_diff_trap_and_the_three_verdicts`
as is. Measure `len(SHARED_BLOCK_TEXT["SHARED-FRESHNESS"])`; if it exceeds
900, raise the ceiling in `test_shared_freshness_stays_within_the_c1_ceiling`
to `<= 950` and extend its comment: "F-H3 (2026-09-15) grew it again
because the algorithm changed: the CLI now writes and validates the cache."

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q -k "shared or freshness"`
Expected: byte-identity tests fail (wrappers still carry the old block).

- [ ] **Step 3: Replace the block in all 20 wrappers**

The block is delimited by the first line `## Freshness re-check (run this
FIRST, every time)` and the last line `- **ok** → continue.` in every
wrapper. Replace it in all 20 with the new text (a small Python script over
the file list is fine; each wrapper contains the block exactly once).

In the four `dev-implement-ticket` wrappers, rewrite the **Resolve** and
**Placeholders** bullets (skill/copilot/cursor form):

```markdown
- **Resolve** — triage exactly as in the Freshness re-check above:
  `broken` → stop and report to the BA; `stale` → show both versions and
  let the Dev decide; `ok` → continue. A full resolve is
  `kb resolve --write-cache docs/impl/<ticket-id>-context.md <ticket-file>`:
  the command writes the header and the resolved sections; you never
  edit above the `<!-- kb:placeholder-map -->` marker.
- **Placeholders** — for each `%%TODO: verify against codebase%%`, verify
  the real name against the codebase and record `placeholder → verified
  value (file:line or code-knowledge ref)`; report the list to the BA;
  **never edit the ticket**; unverifiable here → `OPEN(BA)`. Record the
  map in the cache file's `## Placeholder map` table below the marker
  (`| placeholder | verified value | evidence (file:line or ref) |`).
```

The `claude-command` variant condenses the same two facts into its
paragraph ("the full resolve is `kb resolve --write-cache …`; the map goes
below the marker"). Keep `docs/impl/<ticket-id>-context.md` and
`Placeholder map` verbatim somewhere in every variant's body
(`test_dev_implement_ticket_writes_the_context_cache` pins them).

In `docs/superpowers/specs/2026-08-24-c1-context-cache-design.md` §2, add
under the format block: *"Superseded 2026-09-15 by
`2026-09-15-dev-workflow-usage-review-fixes-design.md` §2: the CLI writes
everything above `<!-- kb:placeholder-map -->` (`kb resolve --write-cache`)
and validates it (`--status-only --cache`); the agent owns the map below."*

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py docs/superpowers/specs/2026-08-24-c1-context-cache-design.md
printf '%s\n' "docs(templates): SHARED-FRESHNESS canon uses --write-cache / --status-only --cache (F-H3)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 6: `dev-design` and `dev-plan` — a design file on every path, `status:` and `cmd.*` headers

**Files:**
- Modify: `claude-skill-dev-design.md`, `copilot-dev-design.prompt.md`,
  `cursor-dev-design.md`, `claude-command-dev-design.md`
- Modify: `claude-skill-dev-plan.md`, `copilot-dev-plan.prompt.md`,
  `cursor-dev-plan.md`, `claude-command-dev-plan.md`
- Test: `tests/test_templates.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
def test_dev_design_writes_a_file_on_every_path_with_a_status_header():
    for name in _dev_wrapper_names("dev-design"):
        body = _dev_wrapper_body(name)
        assert "Every path writes `docs/impl/<ticket-id>-design.md`" in body, name
        assert "`path: <spike|bounded|architectural>`" in body, name
        assert "`status: draft`" in body, name
        assert "`status: approved`" in body, name
        assert "in chat" not in body, name
        assert "architectural path only" not in body, name


def test_dev_plan_refuses_a_draft_design_and_writes_the_cmd_headers():
    for name in _dev_wrapper_names("dev-plan"):
        body = _dev_wrapper_body(name)
        assert "`status: approved`" in body, name
        assert "`cmd.test: <command>`" in body, name
        assert "`cmd.lint: <command>`" in body, name
        assert "`status: draft`" in body, name
        assert "path: spike" in body, name
        assert "in chat" not in body, name
        assert "untouched tree" not in body, name
        assert "Linting* section of `docs/conventions/<lang>.md`" in body, name
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q -k "dev_design_writes or dev_plan_refuses"`
Expected: FAIL on the new needles.

- [ ] **Step 3: Edit the eight wrappers**

`dev-design` skill/copilot/cursor: replace the three classification bullets
and add a paragraph:

```markdown
- **spike** — a feasibility question the ticket itself raises; the output
  is an answer plus a recommendation, and anything built to get there is
  labelled throwaway.
- **bounded** — changes a flow that already exists in this repo; the
  design is a few sentences to a few short paragraphs.
- **architectural** — a new service, a new table, a new interface, or a
  change to how components fit; the design covers every item under
  *Design content* below.

Every path writes `docs/impl/<ticket-id>-design.md` — one paragraph on
the bounded path is not ceremony, it is the resume point the orchestrator
reads. The file opens with two header lines under its title:
`path: <spike|bounded|architectural>` and `status: draft`. A spike's body
is the question, what was tried, the recommendation, and the sentence
"anything built for this is throwaway"; a spike ends here — no plan, no
execute — and its next step is `dev-handover`, which puts the
recommendation under `## Findings`.
```

Under `## GATE 1` add: *"When the Dev approves, flip the header to
`status: approved` before anything else — `dev-plan` refuses a `draft`
design. A file's existence is not approval; its `status:` line is."*

`claude-command-dev-design.md`: rewrite the condensed classification
paragraph so it says the same things (every path writes the file with
`path:` and `status: draft`; GATE 1 flips `status: approved`; spike ends at
the file) — the needles above must be present verbatim.

`dev-plan` skill/copilot/cursor, the **Steps** list:

- *Read the design* bullet → "read `docs/impl/<ticket-id>-design.md`. Its
  header must say `status: approved`; a `draft` design means GATE 1 has
  not passed — say so in one line and stop. A `path: spike` design has no
  plan: say so and point at `dev-handover`."
- *Write the plan* bullet → add one sentence: "The file opens with three
  header lines under its title: `cmd.test: <command>`, `cmd.lint:
  <command>` (from `-code §cmd.*`, or the Dev's answer) and `status:
  draft` — `kb pr lint` reads `cmd.test:` from this file and requires it
  inside the PR's Verification fence."
- *No `-code` document yet* bullet → "…and record them in the `cmd.test:`
  / `cmd.lint:` header lines, so…"
- *No linter in the repo* bullet → keep up to "…record the command it
  establishes as `cmd.lint`. Its red step is running that command and
  watching it fail because no linter is configured." then replace the
  rest with: "Whether the preset applies at full strength or is narrowed
  so it passes on the current tree is decided by the *Linting* section
  of `docs/conventions/<lang>.md` — follow it, and carry every narrowed
  rule into the PR's `## Findings`."
- *GATE 2* bullet → "the Dev approves the plan before any code is written;
  once approved, flip the plan header to `status: approved` and option 1
  in the Next-step block below is `/dev-execute <ticket-id>`. …"

`claude-command-dev-plan.md`: same facts in its condensed paragraph
(needles verbatim).

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q`
Expected: all pass. `test_dev_plan_and_dev_implement_ticket_caveat_the_code_document_by_repo_state`
pins a `-code` sentence in dev-plan — keep that sentence intact.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
printf '%s\n' "docs(templates): design file on every path; status: and cmd.* headers carry the gates (F-H2, F-M8)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 7: State vocabulary and the re-entry table

**Files:**
- Modify: the 20 dev wrappers (SHARED-NEXT-STEP `State:` line)
- Modify: the four `dev-implement-ticket` wrappers ("Run the phases" bullet)
- Modify: `docs/superpowers/specs/2026-08-19-dev-agent-design.md:540`
- Test: `tests/test_templates.py`

- [ ] **Step 1: Update the canon and add the needle test**

In `SHARED_BLOCK_TEXT['SHARED-NEXT-STEP']` replace the `State:` line with:

```
    State: design <✅ approved|📝 draft|⬜ not written> · plan <✅ approved|📝 draft|⬜ not written|⚠ missing, N commits|n/a (spike)> · tasks <n>/<m> · PR <✅ opened|✅ merged|❌ closed|⬜ not opened|? unknown>
```
(everything else in that block byte-identical). Append:

```python
def test_dev_implement_ticket_names_every_re_entry_case():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        body = _dev_wrapper_body(name)
        for needle in ("status: draft", "N commits on branch", "--state merged",
                       "--state closed", "two tickets in flight",
                       "git switch -c <ticket-id>", "gh not installed"):
            assert needle in body, f"{name}: {needle}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q -k "next_step or shared or re_entry"`
Expected: FAIL.

- [ ] **Step 3: Edit the wrappers and the old spec**

Replace the `State:` line in all 20 wrappers with the new one (same line
in every file). In the four `dev-implement-ticket` wrappers, replace the
"Run the phases" bullet's re-entry sentence ("On re-entry, detect state
from … offer the next one.") with:

```markdown
  On re-entry, derive the state — never store it — and name the case:
  - `docs/impl/<ticket-id>-design.md` with `status: draft` →
    `design 📝 draft`, offer GATE 1; `status: approved` → `design ✅`.
  - design approved, plan absent, and `git log --oneline <default>..HEAD`
    non-empty → `plan ⚠ missing, N commits on branch`: ask before running
    `dev-plan` — work may already be committed.
  - plan with `status: draft` → `plan 📝 draft`, offer GATE 2; approved →
    tasks = ticked/total checkboxes.
  - `gh pr list --head <branch> --state merged` non-empty → `PR ✅ merged`,
    flow done; `--state closed` non-empty → `PR ❌ closed`, next step is
    re-handover or reopen — never end the flow silently; `gh` absent →
    `PR ? unknown (gh not installed)`.
  - no branch matches `git branch --list "*<ticket-id>*"` and HEAD is the
    default branch → offer `git switch -c <ticket-id>`.
  - the current branch names a *different* `ABC-12` ticket id → STOP:
    "two tickets in flight; switch branches first".
  Then skip finished phases and offer the next one.
```

`claude-command-dev-implement-ticket.md`: the same cases in its condensed
form, needles verbatim.

In `docs/superpowers/specs/2026-08-19-dev-agent-design.md` line 540, append
to the cell: *" — **Superseded 2026-09-15** by
`2026-09-15-dev-workflow-usage-review-fixes-design.md` §3: every path
writes the file; `status:` carries the gate, not existence."*

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py docs/superpowers/specs/2026-08-19-dev-agent-design.md
printf '%s\n' "docs(templates): State line vocabulary and the re-entry case table (F-H2)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 8: QUICKSTART "What is enforced" and the Ground step (M2)

**Files:**
- Modify: `src/center_kb/templates/init/QUICKSTART-dev.md:165-190`
- Modify: the four `dev-implement-ticket` wrappers (Ground bullet)
- Test: `tests/test_templates.py`

- [ ] **Step 1: Write the failing tests**

Replace the needle in `test_dev_implement_ticket_…` at
`tests/test_templates.py:735` ("is missing whenever this repo has not run
`dev-code-seed`") with `"generated, unpublished: run `kb publish`"` and the
`-code` needle in the sibling test (`…caveat_the_code_document_by_repo_state`,
implement-ticket half only) with `"`kb code-ingest` for `<repo_id>-code`"`.
Append:

```python
def test_quickstart_dev_separates_machine_enforced_from_prompt_only():
    text = _read_init_template("QUICKSTART-dev.md")
    _, _, rest = text.partition("## What is enforced")
    machine, _, prompt_only = rest.partition("### Prompt-only")
    assert "### Machine-enforced" in machine
    assert "`kb pr lint`" in machine and "`kb build`" in machine
    for rule in ("TDD", "verbatim", "read-only", "GATE 1", "OPEN(BA)"):
        assert rule in prompt_only, rule
    assert "nothing in `kb` enforces or measures" in prompt_only
    assert "No such command 'pr'" not in text


def test_dev_implement_ticket_ground_step_tells_generated_from_published():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        body = _dev_wrapper_body(name)
        assert ".kb/<repo_id>-code/" in body, name
        assert "generated, unpublished: run `kb publish`" in body, name
        assert "is missing whenever" not in body, name
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q -k "quickstart_dev_separates or ground_step_tells or caveat"`
Expected: FAIL.

- [ ] **Step 3: Edit**

`QUICKSTART-dev.md`: replace the whole `## What is enforced` section with:

```markdown
## What is enforced

### Machine-enforced

- **The PR carries its evidence** — `.github/workflows/kb-pr-lint.yml`
  checks out the branch read-only and runs `kb pr lint` on every pull
  request. It fails when a required section is missing, still holds the
  template's comment, claims verification with no pasted output, when no
  Verification fence contains the plan's `cmd.test:` command, or when
  `## TDD exemptions` names a class outside `config`, `ci`, `docs`,
  `style`. Add **`pr-lint` to the branch's required checks** once:
  `kb init` writes the workflow but cannot turn on branch protection for
  you. Unlike `kb-ticket-lint`, this gate never self-skips — once
  required, it blocks **every** PR without the eight sections, bot PRs
  (a Dependabot bump, a revert) included, so make that required-check
  decision knowingly.
- **Unreviewed knowledge cannot reach the hub** — `kb build` (run by
  `kb-code.yml` on push and PR) exits 1 while any `<repo_id>-svc`
  section is `pending`.
- **The context cache is CLI-owned** — `kb resolve --status-only --cache`
  refuses a cache whose version, ref set or resolved block differs from
  the ticket's.

### Prompt-only — stated in every wrapper, measured by nothing

A recommendation the skills repeat as a rule; nothing in `kb` enforces or
measures compliance with it. The only check is the human at the gate.

- **TDD** — no production code without a failing test observed first, at
  every step of `dev-execute`; exempt classes are named in
  `docs/tdd-exemptions.md` and declared in the plan.
- **Shown verification** — a completion claim without the real command
  output; `kb pr lint` checks the PR body, not the session.
- **Pinned values, verbatim** — every standard-derived value comes from
  the resolved section at its pinned hub version with a citation comment.
- **The ticket is read-only** — findings go back to the BA; the agent
  never edits the ticket.
- **GATE 1 and GATE 2** — design and plan approved before the next phase;
  the `status:` header records it, a human grants it.
- **`OPEN(BA)`** — an ambiguous AC is escalated, never reinterpreted.
```

In the four `dev-implement-ticket` wrappers' **Ground** bullet, replace
from "State the rule: *knowledge orients, code decides*" to the end of
the bullet with:

```markdown
State the rule: *knowledge orients, code decides* — skip whichever
document is missing and read the code directly for that half. A document
missing from the hub means either not yet generated (`kb code-ingest`
for `<repo_id>-code`, `dev-code-seed` for `<repo_id>-svc`) or generated
and not yet published — check `.kb/<repo_id>-code/` and
`.kb/<repo_id>-svc/` locally: present → say "generated, unpublished: run
`kb publish`" in one line; absent → "not generated". Reads stay hub-only
either way; never report it as a KB gap.
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q`
Expected: all pass (the QUICKSTART test at :1698 partitions on a different
heading and is untouched).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
printf '%s\n' "docs(quickstart,templates): machine-enforced vs prompt-only; Ground step tells unpublished from ungenerated (F-H1, F-M2)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 9: Price aliases and point-release fallback (M3)

**Files:**
- Modify: `src/center_kb/usage/prices.py`
- Modify: `src/center_kb/templates/usage/usage-prices.yaml`
- Test: `tests/test_usage_prices.py`

**Interfaces:**
- Produces: `PriceTable.aliases: dict[str, str]`,
  `resolve_model(table, model) -> str | None`. `cost_of` unchanged in
  signature.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_usage_prices.py`:

```python
def test_a_point_release_id_falls_back_to_its_family_row(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert prices.resolve_model(table, "claude-fable-5-1") == "claude-fable-5"
    assert prices.resolve_model(table, "claude-opus-5-2-1") == "claude-opus-5"
    assert prices.cost_of(row("u1", model="claude-fable-5-1", tokens_out=1_000_000,
                              tokens_in=0, cache_read=0, cache_write_5m=0, cache_write_1h=0),
                          table) == 50.0


def test_the_packaged_aliases_price_the_bare_family_names(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert table.aliases == {"opus": "claude-opus-5", "sonnet": "claude-sonnet-5",
                             "haiku": "claude-haiku-4-5"}
    assert prices.resolve_model(table, "opus") == "claude-opus-5"


def test_a_genuinely_unknown_model_still_resolves_to_none(tmp_path: Path):
    table = prices.load_prices(tmp_path)
    assert prices.resolve_model(table, "gpt-9") is None
    assert prices.resolve_model(table, "claude-sonnet-4") is None


def test_an_override_merges_aliases_per_key(tmp_path: Path):
    (tmp_path / "usage-prices.yaml").write_text(
        "aliases:\n  opus: claude-opus-4-8\n", encoding="utf-8"
    )
    table = prices.load_prices(tmp_path)
    assert table.aliases["opus"] == "claude-opus-4-8"
    assert table.aliases["sonnet"] == "claude-sonnet-5"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_usage_prices.py -q`
Expected: AttributeError `resolve_model`.

- [ ] **Step 3: Implement**

`prices.py`: add `import re`; in `PriceTable` add `aliases: dict[str, str] = {}`;
in `load_prices` merge aliases beside models:

```python
        models = dict(data.get("models") or {})
        models.update(override.get("models") or {})
        aliases = dict(data.get("aliases") or {})
        aliases.update(override.get("aliases") or {})
        data = {**data, **override, "models": models, "aliases": aliases}
```

Add and use `resolve_model`:

```python
_POINT_RELEASE = re.compile(r"-\d+$")


def resolve_model(table: PriceTable, model: str) -> str | None:
    """The table row that prices `model`: exact id, then an alias, then the
    family row after stripping trailing `-<digits>` segments one at a time
    (`claude-fable-5-1` → `claude-fable-5`). None when nothing matches."""
    candidate = model
    while True:
        if candidate in table.models:
            return candidate
        alias = table.aliases.get(candidate)
        if alias in table.models:
            return alias
        stripped = _POINT_RELEASE.sub("", candidate)
        if stripped == candidate:
            return None
        candidate = stripped


def cost_of(row: UsageRow, table: PriceTable) -> float | None:
    """USD for one row, or None when the model has no rates."""
    key = resolve_model(table, row.model)
    if key is None:
        return None
    rates = table.models[key]
    return (
        row.tokens_in * rates.input
        + row.tokens_out * rates.output
        + row.cache_read * rates.cache_read
        + row.cache_write_5m * rates.cache_write_5m
        + row.cache_write_1h * rates.cache_write_1h
    ) / _MTOK
```

`usage-prices.yaml`: after the `models:` block append:

```yaml
# Bare family names Claude Code writes on some calls. A trailing
# point-release suffix (`claude-fable-5-1`) needs no row: it falls back to
# its family (`claude-fable-5`) and the report lists it under "priced as".
aliases:
  opus: claude-opus-5
  sonnet: claude-sonnet-5
  haiku: claude-haiku-4-5
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_usage_prices.py tests/test_usage_report.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/usage/prices.py src/center_kb/templates/usage/usage-prices.yaml tests/test_usage_prices.py
printf '%s\n' "feat(usage): price aliases and point-release fallback — claude-fable-5-1, opus, sonnet are no longer unpriced (F-M3)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 10: Report `est`/`assistant`/`priced_as`, markdown warning, `kb usage note` defaults (M4, L4)

**Files:**
- Modify: `src/center_kb/usage/report.py`
- Modify: `src/center_kb/templates/usage/report.html.j2`
- Modify: `src/center_kb/cli.py:1236-1282` (`usage_note`)
- Test: `tests/test_usage_report.py`, `tests/test_cli_usage.py`

**Interfaces:**
- Consumes: `resolve_model` (Task 9).
- Produces: `Bucket.est_rows`, `Aggregate.by_assistant`,
  `Aggregate.priced_as: dict[str, str]`, `Aggregate.hook_errors: int`
  (set by the CLI in Task 11; rendered here).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_usage_report.py`:

```python
def test_estimated_rows_are_counted_and_shown(tmp_path: Path):
    rows = [row("u1"), row("u2", est=True, assistant="copilot")]
    agg = agg_of(rows, tmp_path)
    assert agg.total.est_rows == 1
    assert {b.key: b.rows for b in agg.by_assistant} == {"claude-code": 1, "copilot": 1}
    md = report.render_markdown(agg)
    assert "(1 estimated)" in md
    assert "| assistant: copilot |" in md
    html = report.render_html(agg)
    assert "By assistant" in html and "copilot" in html and "1 estimated" in html
    assert agg.model_dump()["total"]["est_rows"] == 1


def test_priced_as_lists_ids_priced_at_a_family_rate(tmp_path: Path):
    agg = agg_of([row("u1", model="claude-fable-5-1")], tmp_path)
    assert agg.priced_as == {"claude-fable-5-1": "claude-fable-5"}
    assert agg.unpriced_models == []
    assert "claude-fable-5-1 priced as claude-fable-5" in report.render_markdown(agg)
    assert "priced as" in report.render_html(agg)


def test_markdown_warns_when_the_price_table_is_old(tmp_path: Path):
    (tmp_path / "usage-prices.yaml").write_text("effective_date: '2026-01-01'\n", encoding="utf-8")
    md = report.render_markdown(agg_of([row("u1")], tmp_path))
    assert md.startswith("**Warning: price table is 234 days old")


def test_markdown_and_html_mention_hook_errors_when_present(tmp_path: Path):
    agg = agg_of([row("u1")], tmp_path)
    agg.hook_errors = 3
    assert "3 hook ingest error(s) logged" in report.render_markdown(agg)
    assert "3 hook ingest error(s)" in report.render_html(agg)
```

In `tests/test_cli_usage.py` change `test_note_appends_a_row_by_hand` to
pass `"--assistant", "copilot"` and expect `row.est is True`, and append:

```python
def test_note_requires_an_assistant(tmp_path: Path):
    d = kb_dir(tmp_path)
    result = runner.invoke(
        app,
        ["usage", "note", "--ticket", "ATM-7", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "1", "--tokens-out", "2",
         "--kb-dir", str(d)],
    )
    assert result.exit_code != 0
    assert "--assistant" in result.output


def test_note_measured_overrides_the_estimate_default(tmp_path: Path):
    d = kb_dir(tmp_path)
    runner.invoke(
        app,
        ["usage", "note", "--ticket", "ATM-7", "--phase", "dev-plan",
         "--model", "claude-opus-5", "--tokens-in", "1", "--tokens-out", "2",
         "--measured", "--assistant", "cursor", "--kb-dir", str(d)],
    )
    (row,) = ledger.read_rows(d)
    assert (row.est, row.assistant) == (False, "cursor")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_usage_report.py tests/test_cli_usage.py -q -k "estimated or priced_as or warns or hook_errors or note"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`report.py`:

```python
from center_kb.usage.prices import PriceTable, cost_of, resolve_model, stale_days


class Bucket(BaseModel):
    ...
    unpriced_rows: int = 0
    est_rows: int = 0


class Aggregate(BaseModel):
    ...
    by_actor: list[Bucket] = []
    by_assistant: list[Bucket] = []
    ...
    unpriced_models: list[str] = []
    priced_as: dict[str, str] = {}
    hook_errors: int = 0
    ...
```

In `_add` add `if row.est: bucket.est_rows += 1`. In `aggregate`:

```python
    assistants: dict[str, Bucket] = defaultdict(Bucket)
    unpriced: set[str] = set()
    priced_as: dict[str, str] = {}
    for row in rows:
        cost = cost_of(row, table)
        key = resolve_model(table, row.model)
        if key is None:
            unpriced.add(row.model)
        elif key != row.model:
            priced_as[row.model] = key
        ...
        for store, key_ in ((phases, row.phase), (models, row.model),
                            (actors, row.actor), (assistants, row.assistant)):
            store[key_].key = key_
            _add(store[key_], row, cost)
    ...
    agg.by_assistant = _ranked(assistants)
    agg.priced_as = dict(sorted(priced_as.items()))
```

`render_markdown`:

```python
def render_markdown(agg: Aggregate) -> str:
    """A PR-body table: what it cost, and where the cost went."""
    lines: list[str] = []
    if agg.stale:
        lines += [f"**Warning: price table is {agg.stale_days} days old — update "
                  ".kb/usage-prices.yaml.**", ""]
    total_key = "total" + (f" ({agg.total.est_rows} estimated)" if agg.total.est_rows else "")
    lines += [
        "| scope | calls | output tokens | cache read | cost |",
        "|---|---|---|---|---|",
        _md_row(Bucket(**{**agg.total.model_dump(), "key": total_key}), agg.currency),
    ]
    for bucket in agg.by_ticket:
        lines.append(_md_row(bucket, agg.currency))
    for bucket in agg.by_phase:
        lines.append(_md_row(Bucket(**{**bucket.model_dump(), "key": f"phase: {bucket.key}"}), agg.currency))
    for bucket in agg.by_assistant:
        lines.append(_md_row(Bucket(**{**bucket.model_dump(), "key": f"assistant: {bucket.key}"}), agg.currency))
    lines.append("")
    if agg.priced_as:
        lines.append("Priced as: " + "; ".join(f"{raw} priced as {key}" for raw, key in agg.priced_as.items()) + ".")
    if agg.hook_errors:
        lines.append(f"{agg.hook_errors} hook ingest error(s) logged — see .kb/usage/ingest-errors.log.")
    lines.append(
        f"Prices effective {agg.effective_date} ({agg.stale_days} days old); "
        f"generated {agg.generated}."
    )
    return "\n".join(lines)
```
(Keep the existing header row text exactly; check
`test_markdown_is_a_compact_table_for_a_pr_body` still matches — it asserts
substrings of the table.)

`report.html.j2`: after the unpriced `{% endif %}` add:

```html
{% if agg.priced_as %}
<p class="meta">Priced as a family rate:
{% for raw, key in agg.priced_as.items() %}{{ raw }} priced as {{ key }}{% if not loop.last %}; {% endif %}{% endfor %}.</p>
{% endif %}

{% if agg.hook_errors %}
<p class="warn">{{ agg.hook_errors }} hook ingest error(s) logged in
<code>.kb/usage/ingest-errors.log</code> — some turns may be missing below.</p>
{% endif %}

{% if agg.total.est_rows %}
<p class="meta">{{ agg.total.est_rows }} estimated: self-reported rows from
<code>kb usage note</code>, not measurements.</p>
{% endif %}
```
and after the "By actor" table:

```html
<h2>By assistant</h2>
{{ rows(agg.by_assistant, "assistant", agg.currency) }}
```

`cli.py` `usage_note` options:

```python
    est: bool = typer.Option(
        True, "--est/--measured",
        help="A hand-entered row is a self-reported estimate (default); "
        "--measured marks a figure read from the assistant's own meter",
    ),
    assistant: str = typer.Option(
        ..., "--assistant", help="Which assistant made the calls, e.g. copilot, cursor"
    ),
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_usage_report.py tests/test_cli_usage.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/usage/report.py src/center_kb/templates/usage/report.html.j2 src/center_kb/cli.py tests/test_usage_report.py tests/test_cli_usage.py
printf '%s\n' "feat(usage): report est/assistant/priced-as, markdown staleness warning; note defaults to --est and requires --assistant (F-M4, F-L4)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 11: Hook log — no ghost directory, surfaced by `doctor` and `usage report` (L2, L3)

**Files:**
- Modify: `src/center_kb/cli.py:1074-1092` (`_usage_log_error`), `usage_report`, `doctor`
- Modify: `src/center_kb/usage/ledger.py`
- Modify: `src/center_kb/doctor.py`
- Test: `tests/test_cli_usage.py`, `tests/test_doctor.py`

**Interfaces:**
- Produces: `ledger.hook_errors(kb_dir) -> tuple[int, str]` (count, last
  line); `doctor.check_usage_log(kb_dir) -> list[Issue]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli_usage.py` change the last assertion of
`test_hook_mode_skips_a_kb_dir_with_no_config_and_writes_no_ledger` to
`assert not (d / "usage").exists()` and append:

```python
def test_report_footer_counts_hook_errors(tmp_path: Path):
    d = kb_dir(tmp_path)
    t = write_transcript(tmp_path, [user_row("tickets/open-new-flight.md"), usage_row("a1")])
    runner.invoke(app, ["usage", "ingest-transcript", str(t), "--kb-dir", str(d)])
    (d / "usage" / "ingest-errors.log").write_text("t1 boom\nt2 bang\n", encoding="utf-8")
    result = runner.invoke(app, ["usage", "report", "--md", "--kb-dir", str(d)])
    assert "2 hook ingest error(s) logged" in result.output
    as_json = json.loads(runner.invoke(app, ["usage", "report", "--json", "--kb-dir", str(d)]).output)
    assert as_json["hook_errors"] == 2
```

Append to `tests/test_doctor.py`:

```python
def test_check_usage_log_warns_with_the_count_and_last_line(tmp_path: Path):
    log = tmp_path / "usage" / "ingest-errors.log"
    log.parent.mkdir()
    log.write_text("t1 boom\nt2 bang\n", encoding="utf-8")
    (issue,) = doctor.check_usage_log(tmp_path)
    assert issue.level == "warning"
    assert "2 hook ingest error(s)" in issue.message and "t2 bang" in issue.message


def test_check_usage_log_is_silent_without_a_log(tmp_path: Path):
    assert doctor.check_usage_log(tmp_path) == []
    (tmp_path / "usage").mkdir()
    (tmp_path / "usage" / "ingest-errors.log").write_text("", encoding="utf-8")
    assert doctor.check_usage_log(tmp_path) == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_cli_usage.py tests/test_doctor.py -q -k "hook_errors or usage_log or skips_a_kb_dir"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`ledger.py`:

```python
def hook_errors(kb_dir: Path) -> tuple[int, str]:
    """(number of logged hook failures, last log line) — (0, '') without a log."""
    path = usage_dir(kb_dir) / "ingest-errors.log"
    try:
        lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return 0, ""
    return len(lines), (lines[-1] if lines else "")
```

`cli.py` `_usage_log_error`: replace the `mkdir` line with a guard that
uses the same evidence the hook uses —

```python
        if not (kb_dir / "config.yaml").is_file():
            return  # wrong directory: nowhere correct to write (reviewer F L2)
        path.parent.mkdir(parents=True, exist_ok=True)
```

`cli.py` `usage_report`, after `agg = report_mod.aggregate(...)`:

```python
    agg.hook_errors, _ = ledger.hook_errors(kb_dir)
```

`doctor.py`:

```python
def check_usage_log(kb_dir: Path) -> list[Issue]:
    """The Stop hook swallows every failure into ingest-errors.log; this is
    the one place a human hears about it (reviewer F L3)."""
    from center_kb.usage.ledger import hook_errors

    count, last = hook_errors(kb_dir)
    if not count:
        return []
    return [
        Issue(
            "warning",
            f"{count} hook ingest error(s) logged in {kb_dir / 'usage' / 'ingest-errors.log'} "
            f"— last: {last}; truncate the file once handled",
        )
    ]
```

`cli.py` `doctor`: import `check_usage_log` and, right after `cfg_kind` is
read, add `if cfg_kind in ("ba", "dev"): issues += check_usage_log(kb_dir)`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_cli_usage.py tests/test_doctor.py tests/test_doctor_hubkind.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py src/center_kb/usage/ledger.py src/center_kb/doctor.py tests/test_cli_usage.py tests/test_doctor.py
printf '%s\n' "fix(usage): hook log never creates a ghost .kb; doctor and usage report surface its count (F-L2, F-L3)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 12: Depth-3 detection and `kb init --lang` (M7)

**Files:**
- Modify: `src/center_kb/conventions.py`
- Modify: `src/center_kb/initcmd.py` (`init_repo`, new `record_langs`)
- Modify: `src/center_kb/config.py` (`KBConfig.langs`)
- Modify: `src/center_kb/cli.py:153-186` (`init`)
- Test: `tests/test_conventions.py`, `tests/test_init.py`

**Interfaces:**
- Produces: `conventions.LANG_IDS`,
  `scaffold_conventions(target, report, forced: Iterable[str] = ())`,
  `initcmd.init_repo(..., langs: Sequence[str] = ())`,
  `initcmd.record_langs(config_path, langs) -> bool`, `KBConfig.langs`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_conventions.py` replace `test_ignores_manifests_below_depth_two` with:

```python
def test_detects_manifests_three_levels_below_root(tmp_path: Path):
    _touch(tmp_path, "apps/web/frontend/package.json")   # depth 3
    assert detect_langs(tmp_path) == ["ts"]


def test_ignores_manifests_below_depth_three(tmp_path: Path):
    _touch(tmp_path, "a/b/c/d/pyproject.toml")           # depth 4
    assert detect_langs(tmp_path) == []


def test_forced_langs_union_with_detected(tmp_path: Path):
    _touch(tmp_path, "package.json")
    report = InitReport()
    assert scaffold_conventions(tmp_path, report, forced=["python"]) == ["python", "ts"]
    assert (tmp_path / "docs" / "conventions" / "python.md").is_file()


def test_the_no_manifest_note_names_the_lang_flag(tmp_path: Path):
    report = InitReport()
    scaffold_conventions(tmp_path, report)
    assert any("--lang" in n for n in report.notes)
```

Append to `tests/test_init.py`:

```python
def test_init_dev_lang_scaffolds_the_pack_records_it_and_reinit_reuses_it(tmp_path: Path):
    init_repo(tmp_path, "dev", langs=["python"])
    assert (tmp_path / "docs" / "conventions" / "python.md").is_file()
    assert (tmp_path / "CLAUDE.md").is_file()
    assert "langs: [python]" in (tmp_path / ".kb" / "config.yaml").read_text(encoding="utf-8")
    (tmp_path / "docs" / "conventions" / "python.md").unlink()
    report = init_repo(tmp_path, "dev")   # plain re-init, no flag
    assert "docs/conventions/python.md" in report.created


def test_init_cli_rejects_an_unknown_lang(tmp_path: Path):
    from typer.testing import CliRunner

    from center_kb.cli import app

    result = CliRunner().invoke(app, ["init", str(tmp_path), "--kind", "dev", "--lang", "cobol"])
    assert result.exit_code == 1
    assert "cobol" in result.output and "python" in result.output
    assert not (tmp_path / ".kb").exists()
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_conventions.py tests/test_init.py -q -k "depth or forced or lang"`
Expected: FAIL.

- [ ] **Step 3: Implement**

`conventions.py`: prefixes `("", "*/", "*/*/", "*/*/*/")`; add
`LANG_IDS: tuple[str, ...] = tuple(lang for lang, _ in LANG_MANIFESTS)`;
change `scaffold_conventions`:

```python
def scaffold_conventions(
    target: Path, report: InitReport, forced: Iterable[str] = ()
) -> list[str]:
    """… Returns the scaffolded language ids: detected ∪ forced."""
    langs = sorted(set(detect_langs(target)) | set(forced))
    if not langs:
        report.notes.append(
            "no language manifests detected — conventions skipped; re-run "
            "kb init after adding code, or pass --lang <id> (one of "
            f"{', '.join(LANG_IDS)})"
        )
        return []
```
(`from collections.abc import Iterable` at the top.) Update the docstring
of `detect_langs` to say "up to three levels below".

`config.py` `KBConfig`: add `langs: list[str] = []`.

`initcmd.py`: add `_LANGS_LINE = re.compile(r"^langs:", re.MULTILINE)` and

```python
def record_langs(config_path: Path, langs: Sequence[str]) -> bool:
    """Append `langs: [a, b]` to a config.yaml that lacks the key — append-
    only, like _record_kind; an existing line is the operator's data."""
    if not langs or not config_path.exists():
        return False
    text = config_path.read_text(encoding="utf-8")
    if _LANGS_LINE.search(text):
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    config_path.write_text(
        text + f"langs: [{', '.join(sorted(set(langs)))}]\n", encoding="utf-8", newline="\n"
    )
    return True


def _recorded_langs(config_path: Path) -> list[str]:
    from center_kb.config import load_config

    try:
        return list(load_config(config_path.parent).langs)
    except Exception:  # a broken config is doctor's job, not init's
        return []
```

`init_repo` signature gains `langs: Sequence[str] = ()`; the dev branch becomes:

```python
    if kind == KIND_DEV:
        cfg_path = target / ".kb" / "config.yaml"
        forced = sorted(set(langs) | set(_recorded_langs(cfg_path)))
        scaffolded = conventions.scaffold_conventions(target, report, forced=forced)
        if scaffolded:
            conventions.ensure_claude_block(target, report)
        if langs and record_langs(cfg_path, forced):
            report.updated.append(".kb/config.yaml (langs recorded)")
```

`cli.py` `init`: add

```python
    lang: list[str] = typer.Option(
        [], "--lang",
        help="Force a conventions pack for a language whose manifest is not "
        "detectable (repeatable): python, ts, java, go, dotnet, php. Dev kind only; "
        "recorded in .kb/config.yaml so a plain re-init keeps it.",
    ),
```
and, after the `--assets` guard:

```python
    if lang:
        from center_kb.conventions import LANG_IDS

        unknown = [l for l in lang if l not in LANG_IDS]
        if unknown:
            typer.secho(
                f"unknown --lang {', '.join(unknown)} — choose from {', '.join(LANG_IDS)}",
                fg=typer.colors.RED,
            )
            raise typer.Exit(1)
        if resolved != "dev":
            typer.secho("--lang applies to dev repos only", fg=typer.colors.RED)
            raise typer.Exit(2)
    report = init_repo(path, resolved, force=force,
                       assets=assets.value if assets else None, langs=lang)
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_conventions.py tests/test_init.py -q`
Expected: all pass, including the 49-file trip-wire (no new scaffold files).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/conventions.py src/center_kb/initcmd.py src/center_kb/config.py src/center_kb/cli.py tests/test_conventions.py tests/test_init.py
printf '%s\n' "feat(init): depth-3 manifest detection and --lang for manifest-less repos (F-M7)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 13: Presets — Java indent, T20/N, no-console, one tightening rule (M5, M6, M8)

**Files:**
- Modify: `src/center_kb/templates/init/conventions-{python,ts,java,go,dotnet,php}.md`
- Test: `tests/test_templates.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
TIGHTENING_RULE = "The preset below is the target strength."


def test_every_conventions_preset_carries_the_one_tightening_rule():
    for lang in ("python", "ts", "java", "go", "dotnet", "php"):
        text = _normalised(_read_init_template(f"conventions-{lang}.md"))
        assert TIGHTENING_RULE in text, lang
        assert "narrow" in text and "## Findings" in text, lang
        assert "exactly as shown" not in text, lang


def test_presets_lint_the_rules_their_prose_states():
    py = _read_init_template("conventions-python.md")
    assert '"T20"' in py and '"N"' in py
    ts = _read_init_template("conventions-ts.md")
    assert '"no-console": "error"' in ts
    java = _read_init_template("conventions-java.md")
    assert "[*.java]\nindent_size = 2" in java
    assert "maxWarnings = 0" not in java.split("```groovy")[1].split("```")[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q -k "tightening or presets_lint"`
Expected: FAIL.

- [ ] **Step 3: Edit the six presets**

In every `conventions-<lang>.md` Linting section, replace the sentence(s)
"When this repo has no linter, the first task of a dev plan creates the
file(s) below exactly as shown and records the command as `cmd.lint`."
(Java: "…wires the preset below into the repo's build tool and records…")
with:

```markdown
The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates these files and records the command as
`cmd.lint`. Where `cmd.lint` fails on the untouched tree, narrow `select` /
rules / warning caps to what passes, and list each narrowed rule under
`## Findings` in the PR body as a tightening still owed.
```
(Java keeps its "wires the preset into the build tool" phrasing after the
first sentence; go keeps "gofmt runs as a golangci-lint linter…".)

`conventions-python.md`: `select = ["E", "F", "W", "I", "B", "UP", "SIM", "T20", "N"]`.

`conventions-ts.md` eslint block:

```js
export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { rules: { "no-console": "error" } },
);
```

`conventions-java.md`: `.editorconfig` `[*.java]` → `indent_size = 2`;
remove the `maxWarnings = 0` line from the checkstyle block and add after
the block: "Set `maxWarnings = 0` once the tree is clean — with
`google_checks.xml` at severity `warning`, a pre-existing repo fails on
day one otherwise."

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py tests/test_conventions.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
printf '%s\n' "docs(conventions): Java 2-space, ruff T20/N, eslint no-console, one tightening rule in every preset (F-M5, F-M6, F-M8)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 14: `kb approve` skips `hist.*` unless named (L7)

**Files:**
- Modify: `src/center_kb/review.py`
- Modify: `src/center_kb/cli.py:2357-2425` (`approve`)
- Test: `tests/test_review.py`

**Interfaces:**
- Produces: `ApproveReport.skipped_machine: list[str]`,
  `review.MACHINE_SECTION_PREFIX = "hist."`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review.py`:

```python
def _add_hist_section(kb):
    manifest_path = kb / "demo-doc" / "_manifest.yaml"
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    src = manifest.sections[0]
    manifest.sections.append(models.SectionEntry(
        id="hist.api", title="api — ticket history", summary="Tickets: 1.",
        status="summarized", file=src.file,
    ))
    models.save_yaml_model(manifest_path, manifest)
    l2 = kb / "demo-doc" / f"{src.file}.md"
    with l2.open("a", encoding="utf-8") as fh:
        fh.write("\n## hist.api api — ticket history\n\n```text\nT-1 | x\n```\n")


def test_whole_doc_approve_skips_machine_authored_hist_sections(git_kb):
    _add_hist_section(git_kb["kb"])
    report = approve_sections(git_kb["kb"], "demo-doc", by="sme <sme@x>")
    assert "hist.api" not in report.flipped
    assert report.skipped_machine == ["hist.api"]
    assert _statuses(git_kb["kb"])["hist.api"] == "summarized"


def test_naming_a_hist_section_still_approves_it(git_kb):
    _add_hist_section(git_kb["kb"])
    report = approve_sections(git_kb["kb"], "demo-doc", ["hist.api"], by="sme <sme@x>")
    assert report.flipped == ["hist.api"]
    assert report.skipped_machine == []
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python -m pytest tests/test_review.py -q -k hist`
Expected: AttributeError `skipped_machine` / `hist.api` in `flipped`.

- [ ] **Step 3: Implement**

`review.py`:

```python
# `hist.*` rows are written by `kb svc note` (Hard rule 12: never hand-
# edited), so a whole-document approve has nothing to sign off there;
# naming one explicitly still works (reviewer F L7).
MACHINE_SECTION_PREFIX = "hist."


@dataclass
class ApproveReport:
    doc_id: str
    flipped: list[str] = field(default_factory=list)
    skipped_pending: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    skipped_machine: list[str] = field(default_factory=list)
```

`_flip_summarized_sections` returns a triple; inside the loop, before the
`status == "summarized"` branch:

```python
        if wanted is None and sec.id.startswith(MACHINE_SECTION_PREFIX):
            if sec.id not in skipped_machine:
                skipped_machine.append(sec.id)
            continue
```
and `return flipped, skipped_pending, skipped_machine`; `approve_sections`
unpacks all three into the report. Grep for other callers of
`_flip_summarized_sections` (`approve_all_changed`) and unpack there too.

`cli.py` `approve`, in the per-report loop:

```python
        for sid in rep.skipped_machine:
            typer.secho(
                f"[note] {rep.doc_id} §{sid} is machine-authored — skipped "
                "(pass --section to force)",
                fg=typer.colors.YELLOW, err=True,
            )
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python -m pytest tests/test_review.py tests/test_devcodeseed.py tests/test_svcnote.py -q`
Expected: all pass (`test_summarize_then_approve_reaches_reviewed_and_builds_clean`
approves a `-svc` doc whose sections are `svc.*`, so it is unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/review.py src/center_kb/cli.py tests/test_review.py
printf '%s\n' "fix(approve): whole-doc approve skips machine-authored hist.* sections (F-L7)" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

### Task 15: Release 0.23.0 — version, changelog, full suite, lint

**Files:**
- Modify: `pyproject.toml:3`, `CHANGELOG.md`

- [ ] **Step 1: Bump and write the changelog**

`pyproject.toml`: `version = "0.23.0"`. Insert at the top of `CHANGELOG.md`
after the intro paragraph:

```markdown
## 0.23.0

### Breaking — `kb pr lint` checks more, `kb usage note` asks more

- `## TDD exemptions` must read `none` or name only `config`, `ci`, `docs`,
  `style` (one per line). Anything else fails the PR.
- A `## Verification` fence must contain the plan's `cmd.test:` command
  when `docs/impl/<ticket-id>-plan.md` carries one; the scaffolded
  `kb-pr-lint.yml` now checks out the branch read-only to read it. No plan
  or no id is a warning, not a failure. New flag `--plan-dir`.
- `kb usage note` requires `--assistant` and records rows as estimates by
  default (`--measured` to override).

### Added

- `kb resolve --write-cache PATH` writes `docs/impl/<ticket-id>-context.md`
  (header with version, ref set and sha256 + the resolved sections) and
  keeps everything below `<!-- kb:placeholder-map -->`; `kb resolve
  --status-only --cache PATH` refuses a cache whose version, ref set or
  resolved block differs (exit 1). The 20 dev wrappers use both.
- `kb init --lang <id>` forces a conventions pack; manifests are now found
  up to three levels deep. `langs:` is recorded in `.kb/config.yaml`.
- Usage report: `(N estimated)`, per-assistant rows, "priced as" for
  point-release ids (`claude-fable-5-1` → `claude-fable-5`) and the bare
  `opus` / `sonnet` / `haiku` aliases, a markdown staleness warning, and a
  hook-error count that `kb doctor` also reports.
- `dev-design` writes `docs/impl/<ticket-id>-design.md` on every path with
  `path:` / `status:` headers; GATE 1 and GATE 2 flip `status: approved`.
  The State line and the orchestrator's re-entry table name draft, merged,
  closed, missing-plan-with-commits and two-tickets-in-flight.

### Fixed

- The stale hint in `kb resolve` names `kb get … --level l3`, not the
  forbidden `kb diff`.
- The usage hook never creates a ghost `.kb/usage/` in the wrong directory.
- `kb approve <doc>` without `--section` skips machine-authored `hist.*`.
- Java preset: 2-space indent to match google-java-format; `maxWarnings = 0`
  is a tightening step, not the starting point. Python preset lints `T20`
  and `N`; TS preset sets `no-console: error`. Every preset carries the one
  tightening rule that `dev-plan` now points at.
- QUICKSTART-dev separates what `kb` enforces from what the wrappers only
  state.
```

- [ ] **Step 2: Lint**

Run: `.venv/Scripts/python -m ruff check src tests`
Expected: no findings. Fix any before continuing.

- [ ] **Step 3: Full suite (foreground, once)**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all pass; `uv lock --check` → unchanged.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml CHANGELOG.md
printf '%s\n' "chore(release): 0.23.0 — reviewer F batch" > "$TMP/msg.txt"
git commit -F "$TMP/msg.txt"
```

---

## Self-review against the spec

- §1 prlint: Tasks 1, 2, 8 (QUICKSTART). ✔
- §2 cache + M1: Tasks 3, 4, 5. ✔ (spec's checkout sentence corrected in Task 2)
- §3 state derivation: Tasks 6, 7. Spec amendment note: Task 7. ✔
- §4 usage M3/M4/L2/L3/L4: Tasks 9, 10, 11. ✔
- §5 conventions M5–M8: Tasks 12, 13. ✔
- §6 Ground wording: Task 8. ✔
- §7 approve hist: Task 14. ✔
- §8 release: Task 15. ✔
- Type consistency: `Finding.level` (T1) used by T2; `refs_of`/`render_cache`/`cache_problem` (T3) used by T4; `resolve_model` (T9) used by T10; `ledger.hook_errors` (T11) used by `usage_report` and `doctor` in T11; `scaffold_conventions(forced=)` (T12) used by `init_repo` in T12; `ApproveReport.skipped_machine` (T14) used by CLI in T14.
