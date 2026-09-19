# Independent review subagents across the dev flow — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the dev ticket flow a real second pair of eyes — author and
reviewer in separate subagent contexts at every phase, and a merge-risk review
that CI can block on.

**Architecture:** Nothing new is invented. The four dev phase skills gain one
shared dispatch-contract block plus one review section each; the review
criteria ship as a package-owned rubric with a create-once `.local.md`
override, exactly as `review-rubric.md` does on the BA side; review state is
recorded in files that already exist (design, plan, PR body); and
`kb pr lint` gains a ninth required section so the merge-risk verdict is
machine-checked instead of merely requested.

**Tech Stack:** Python 3.11+, pytest, `strata_kb.initcmd` / `strata_kb.prlint`,
Markdown templates under `src/strata_kb/templates/init/`.

**Spec:** `docs/superpowers/specs/2026-09-19-dev-review-subagents-design.md`

## Global Constraints

- Agent reviews are named **A1** (design), **A2** (plan), **A3** (per task),
  **A4** (branch, narrow), **A5** (merge-risk, wide). Human gates keep
  **GATE 1–4**. Never renumber or blur the two ladders.
- Severity ladder, verbatim, everywhere: **BLOCKER / SUGGESTED / NOTE / NITS**.
  No approval while a BLOCKER stands.
- Review loops: **at most 3 rounds**. A BLOCKER still standing after round 3
  stops the flow for the Dev.
- Review artefacts live under `docs/impl/<ticket-id>-review/` and are
  gitignored. Verdicts are recorded in committed files.
- Template text **never hard-codes a model id**. It says "a standard model" /
  "the most capable model available".
- Every dev phase skill ships in four wrapper variants —
  `claude-skill-<name>.md`, `claude-command-<name>.md`,
  `copilot-<name>.prompt.md`, `cursor-<name>.md` — and
  `tests/test_templates.py` compares shared blocks byte-for-byte. A block
  added to one wrapper lands in all four in the same commit.
- Files are written with `newline="\n"`.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/strata_kb/templates/init/pr-review-rubric.md` | NEW. Package-owned review criteria: pre-code axes (A1/A2) + merge-risk axes (A5). |
| `src/strata_kb/templates/init/pr-review-rubric-local-stub.md` | NEW. Create-once per-repo override. |
| `src/strata_kb/initcmd.py` | `DEV_TEMPLATES` gains the base rubric; new `DEV_LOCAL_OVERRIDES` + `scaffold_dev_local_overrides`, mirroring the BA pair. |
| `src/strata_kb/templates/init/impl-gitignore.txt` | Ignore `*-review/`. |
| 16 dev wrapper templates (4 skills × 4 variants) | Shared review-dispatch contract + the phase's own review section. |
| `src/strata_kb/templates/init/pull-request-template.md` | New `## Review` section. |
| `src/strata_kb/prlint.py` | `"Review"` in `REQUIRED_SECTIONS`; `Blocking:` verdict rule. |
| `docs/src/guide-dev.en.md`, `docs/src/guide-dev.vi.md` | §4.3 and §5.2 restated. |
| `tests/test_templates.py`, `tests/test_init.py`, `tests/test_prlint.py` | Canon pins for all of the above. |

---

### Task 1: Rubric document and its `kb init` wiring

**Files:**
- Create: `src/strata_kb/templates/init/pr-review-rubric.md`
- Create: `src/strata_kb/templates/init/pr-review-rubric-local-stub.md`
- Modify: `src/strata_kb/initcmd.py` (`DEV_TEMPLATES`, new `DEV_LOCAL_OVERRIDES` + scaffold function, call site at the `KIND_DEV` branch)
- Modify: `src/strata_kb/templates/init/impl-gitignore.txt`
- Test: `tests/test_templates.py`, `tests/test_init.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `initcmd.DEV_LOCAL_OVERRIDES: dict[str, str]` and
  `initcmd.scaffold_dev_local_overrides(target: Path, report: InitReport) -> None`.
  Scaffolded paths `docs/pr-review-rubric.md` and
  `docs/pr-review-rubric.local.md` — every later task's template text cites
  exactly these two paths.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
def test_pr_review_rubric_templates_exist_as_package_resources():
    base = resources.files("strata_kb").joinpath("templates/init")
    for name in ("pr-review-rubric.md", "pr-review-rubric-local-stub.md"):
        assert base.joinpath(name).is_file(), name


def test_pr_review_rubric_carries_both_halves_and_the_ladder():
    text = _read_init_template("pr-review-rubric.md")
    assert "## Pre-code axes" in text
    assert "## Merge-risk axes" in text
    for level in ("BLOCKER", "SUGGESTED", "NOTE", "NITS"):
        assert level in text, level
    # The wide reviewer's defining rule: the diff alone is not the review.
    assert "not the review" in _normalised(text)


def test_pr_review_rubric_names_every_merge_risk_axis():
    body = _normalised(_read_init_template("pr-review-rubric.md"))
    for axis in (
        "Security & authorization",
        "Data integrity",
        "Performance & scale",
        "Contract & backward compatibility",
        "Migration, rollout & rollback",
        "Observability",
        "Test adequacy",
        "Production readiness",
    ):
        assert axis in body, axis


def test_pr_review_rubric_is_wired_into_dev_kind_only():
    from strata_kb import initcmd

    assert initcmd.DEV_TEMPLATES["docs/pr-review-rubric.md"] == "pr-review-rubric.md"
    assert initcmd.DEV_LOCAL_OVERRIDES == {
        "docs/pr-review-rubric.local.md": "pr-review-rubric-local-stub.md",
    }
    for kind in ("hub", "child", "ba"):
        assert "docs/pr-review-rubric.md" not in initcmd.expected_files(kind), kind


def test_impl_gitignore_excludes_the_review_artefacts():
    text = _read_init_template("impl-gitignore.txt")
    assert "*-review/" in text
```

Append to `tests/test_init.py`:

```python
def test_init_kind_dev_scaffolds_the_review_rubric_and_its_override(tmp_path: Path):
    init_repo(tmp_path, "dev")
    assert (tmp_path / "docs" / "pr-review-rubric.md").is_file()
    assert (tmp_path / "docs" / "pr-review-rubric.local.md").is_file()


def test_the_dev_rubric_override_is_never_refreshed(tmp_path: Path):
    init_repo(tmp_path, "dev")
    local = tmp_path / "docs" / "pr-review-rubric.local.md"
    local.write_text("# mine\n", encoding="utf-8")
    report = init_repo(tmp_path, "dev")
    assert local.read_text(encoding="utf-8") == "# mine\n"
    assert any(
        "local overrides — never refreshed" in entry for entry in report.skipped
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k "rubric or impl_gitignore" tests/test_init.py -k "rubric" -v`
Expected: FAIL — `FileNotFoundError` on the missing template resources and
`AttributeError: module 'strata_kb.initcmd' has no attribute 'DEV_LOCAL_OVERRIDES'`.

- [ ] **Step 3: Write `pr-review-rubric.md`**

```markdown
# PR review rubric — dev repo

Read by the review subagents of the dev ticket flow. `docs/pr-review-rubric.local.md`
is read after this file and wins where the two disagree.

Severity ladder, used by every review in the flow:

| Level | Meaning |
|---|---|
| **BLOCKER** | Ships a production incident, a security or permission hole, data corruption or loss, or a broken contract. No approval while one stands. |
| **SUGGESTED** | Should be fixed now: maintainability, missing monitoring, a fragile construction. |
| **NOTE** | Worth improving later. Record it; do not block. |
| **NITS** | Naming, formatting, dead code. |

## Pre-code axes

Used by A1 (design review) and A2 (plan review), before any human gate.

- [ ] Every acceptance criterion of the ticket is addressed — none dropped,
      nothing extra designed that no AC asked for (YAGNI). **BLOCKER**
- [ ] Every standard-derived value (format, enum, threshold, field length) is
      verbatim from the resolved section at the pinned version and carries a
      citation comment — never remembered, never rounded. **BLOCKER**
- [ ] The work classification (spike / bounded / architectural) matches what
      the ticket actually asks for. **SUGGESTED**
- [ ] (A2) Exactly one task per AC, and every task states its failing test
      before its implementation. **BLOCKER**
- [ ] (A2) Each task's **Interfaces** entry names every signature, path and
      value its implementer needs, so no implementer has to read wider than
      its own task block. **BLOCKER**
- [ ] (A2) Any task with no test declares `Exempt: <config|ci|docs|style>` and
      names its verification — see `docs/tdd-exemptions.md`. **BLOCKER**
- [ ] An ambiguity is carried as `OPEN(BA)`, never resolved by guessing. **BLOCKER**

## Merge-risk axes

Used by A5 in `dev-handover`, reviewing the whole branch as a tech lead would
before a production deploy: assume real traffic, concurrent requests, retries,
and more than one running instance.

**The diff alone is not the review.** Open the files the change reaches —
callers, siblings, migrations, permission declarations, contracts, tests — and
trace the affected flow end to end before judging. A finding states *why* it is
dangerous by tracing the concrete logic, not by naming a category.

### Security & authorization

- [ ] Every new or changed entry point authenticates and authorizes, and the
      permission matches the business action. **BLOCKER**
- [ ] No data is returned outside the caller's scope, and no scope can be
      widened from a query parameter or request body. **BLOCKER**
- [ ] All external input is validated at the boundary; nothing trusts the
      client. **BLOCKER**
- [ ] No injection path (query, command, path traversal, server-side request
      forgery) is introduced. **BLOCKER**
- [ ] No secret is hardcoded; secrets come from configuration. **BLOCKER**
- [ ] No credential, token, or personal data reaches a log or an error
      response. **BLOCKER**

### Data integrity

- [ ] Duplicate submissions and retries cannot create duplicate records. **BLOCKER**
- [ ] Concurrent requests cannot interleave into an invalid state. **BLOCKER**
- [ ] Writes that must succeed together are in one transaction, and no
      external call is made inside it. **BLOCKER**
- [ ] Consumers of queued or emitted messages are idempotent. **BLOCKER**

### Performance & scale

- [ ] No query or external call inside a loop; no N+1. **BLOCKER**
- [ ] Every list endpoint or query is bounded — pagination or an explicit
      limit. **BLOCKER**
- [ ] Filters and sorts a datastore can do are not done in memory over a
      large set. **BLOCKER**
- [ ] No unbounded in-memory accumulation, and no quadratic-or-worse work on
      user-sized input. **BLOCKER**
- [ ] Every external call has a timeout. **BLOCKER**

### Contract & backward compatibility

- [ ] No existing client breaks: field removals, type changes, renames,
      changed status codes or error shapes. **BLOCKER**
- [ ] Emitted message or event schemas stay backward compatible. **BLOCKER**

### Migration, rollout & rollback

- [ ] Every schema change ships its migration, and the migration can be
      rolled back. **BLOCKER**
- [ ] The migration does not lock a large table for long. **BLOCKER**
- [ ] The change can be disabled or reverted without a code rollback where the
      repo has that mechanism. **SUGGESTED**

### Observability

- [ ] Failures are logged with enough context to diagnose them in production,
      and errors are never silently swallowed. **SUGGESTED**
- [ ] Correlation identifiers survive the new code path. **NOTE**

### Test adequacy

- [ ] Every new behaviour has a test that fails without the change. **BLOCKER**
- [ ] Error, permission, and empty/edge paths are covered. **SUGGESTED**

### Production readiness

- [ ] The failure of any external dependency is handled, not assumed away. **BLOCKER**
- [ ] The change's effect under retry and under multiple instances is
      considered explicitly. **BLOCKER**

## Report format

A review returns a table and a verdict line, nothing else:

| Severity | File | Line | Why it is dangerous | Fix |
|---|---|---|---|---|
| BLOCKER | `src/orders/service.py` | 118 | … | … |

    Blocking: Yes|No   (Yes while any BLOCKER stands)
```

- [ ] **Step 4: Write `pr-review-rubric-local-stub.md`**

```markdown
# PR review rubric — local overrides

Your repo's own review criteria. `kb init` creates this file once and never
rewrites it, so anything you put here survives every upgrade — unlike
`docs/pr-review-rubric.md`, which is refreshed with the CLI.

The review subagents read `docs/pr-review-rubric.md` first, then this file;
where the two disagree, this file wins.

This is where stack-specific rules belong — the base file is deliberately
framework-agnostic.

## Pre-code axes — extra checklist items

<!-- e.g. - [ ] Every new endpoint names the feature flag that gates it. -->

## Merge-risk axes — extra checklist items

<!-- e.g. - [ ] (Security) Every controller declares its permission decorator. -->
<!-- e.g. - [ ] (Contract) Every user-facing message has an EN and a VI key. -->

## Base items we do not apply

<!-- e.g. - [ ] (Migration) "rolled back" — we ship forward-only migrations by
     policy; this criterion never applies here. -->
```

- [ ] **Step 5: Wire both into `kb init`**

In `src/strata_kb/initcmd.py`, add to `DEV_TEMPLATES` (next to
`"docs/tdd-exemptions.md"`):

```python
    "docs/pr-review-rubric.md": "pr-review-rubric.md",
```

After `BA_LOCAL_OVERRIDES` / `scaffold_ba_local_overrides`, add the dev pair:

```python
# Created once, never refreshed — the dev repo's own merge-risk criteria.
# Same contract as BA_LOCAL_OVERRIDES: the BASE rubric stays package-owned
# and keeps being refreshed, so a repo gets improved criteria on upgrade
# without losing the stack-specific ones it wrote.
DEV_LOCAL_OVERRIDES: dict[str, str] = {
    "docs/pr-review-rubric.local.md": "pr-review-rubric-local-stub.md",
}


def scaffold_dev_local_overrides(target: Path, report: InitReport) -> None:
    """Create the dev repo's `.local.md` override once, then never touch it."""
    for rel, resource_name in DEV_LOCAL_OVERRIDES.items():
        dest = target / rel
        if dest.exists():
            report.skipped.append(f"{rel} (local overrides — never refreshed)")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            _init_template_text(resource_name), encoding="utf-8", newline="\n"
        )
        report.created.append(rel)
```

In the `if kind == KIND_DEV:` branch of `init_repo`, as its first statement:

```python
        scaffold_dev_local_overrides(target, report)
```

Append to `src/strata_kb/templates/init/impl-gitignore.txt`:

```
# Review artefacts (diffs, reviewer reports) are derivable from git and the
# review records in the design/plan files — never committed.
*-review/
```

- [ ] **Step 6: Fix the pinned dev file count**

`tests/test_init.py:1744` pins the map size and compares `report.created`
against it. The base rubric raises the count by one; the `.local.md` is
created outside the map, exactly as on the BA side. Replace both lines with:

```python
    assert len(expected_files("dev")) == 54
    assert sorted(report.created) == sorted(
        expected_files("dev") + list(initcmd.DEV_LOCAL_OVERRIDES)
    )
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/strata_kb/templates/init/pr-review-rubric.md \
        src/strata_kb/templates/init/pr-review-rubric-local-stub.md \
        src/strata_kb/templates/init/impl-gitignore.txt \
        src/strata_kb/initcmd.py tests/test_templates.py tests/test_init.py
git commit -m "feat(dev): ship a PR review rubric with a create-once local override"
```

---

### Task 2: The shared review-dispatch contract, in all 16 wrappers

**Files:**
- Modify: `src/strata_kb/templates/init/{claude-skill,claude-command,copilot,cursor}-dev-{design,plan,execute,handover}.md` — note the copilot variants are named `copilot-dev-<phase>.prompt.md` (16 files)
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: the rubric paths from Task 1.
- Produces: canon block `SHARED-REVIEW-CONTRACT`, keyed in
  `tests/test_templates.py` by first line
  `"## Review dispatch contract (every review in this flow)\n"` and last line
  `"  itself is a weaker substitute, not an equivalent.\n"`. Tasks 3–6 add
  their phase sections *after* this block.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
REVIEW_CONTRACT_SKILLS = ("dev-design", "dev-plan", "dev-execute", "dev-handover")

REVIEW_CONTRACT_BOUNDS = (
    "## Review dispatch contract (every review in this flow)\n",
    "  itself is a weaker substitute, not an equivalent.\n",
)


def _review_contract(name: str) -> str:
    first, last = REVIEW_CONTRACT_BOUNDS
    text = _read_init_template(name)
    assert text.count(first) == 1, f"{name}: contract opening line not found once"
    assert text.count(last) == 1, f"{name}: contract closing line not found once"
    start = text.index(first)
    return text[start : text.index(last, start) + len(last)]


def test_review_contract_is_byte_identical_across_the_four_phase_skills():
    """1 block x 16 files. The four phases dispatch reviewers; the two
    remaining dev wrappers (dev-implement-ticket, dev-code-seed) dispatch
    none, so the contract deliberately does not live there."""
    names = [
        name for skill in REVIEW_CONTRACT_SKILLS for name in _dev_wrapper_names(skill)
    ]
    assert len(names) == 16
    canon = _review_contract(names[0])
    for name in names[1:]:
        assert _review_contract(name) == canon, name


def test_review_contract_pins_the_rules_that_make_it_independent():
    body = _normalised(_review_contract("claude-skill-dev-design.md"))
    assert "NEVER the same subagent" in body
    assert "no conversation history" in body
    assert "FILE PATHS, never pasted" in body
    assert "never rates a finding's severity for it" in body
    assert "at most 3 rounds" in body
    assert "most capable one available" in body


def test_the_contract_is_absent_from_the_non_dispatching_wrappers():
    first = REVIEW_CONTRACT_BOUNDS[0]
    for skill in ("dev-implement-ticket", "dev-code-seed"):
        for name in _dev_wrapper_names(skill):
            assert first not in _read_init_template(name), name
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_templates.py -k review_contract -v`
Expected: FAIL — `AssertionError: claude-skill-dev-design.md: contract opening line not found once`.

- [ ] **Step 3: Insert the block in all 16 wrappers**

Insert this block verbatim, immediately **before** the `## Hard rules`
heading, in each of the 16 files. Byte-identical everywhere — copy, never
retype:

```markdown
## Review dispatch contract (every review in this flow)

- The author and the reviewer are NEVER the same subagent. A self-review
  never satisfies a review step.
- A reviewer starts from a fresh context and gets no conversation history —
  hand it only the paths it must read and the constraints that bind it.
- Artefacts move as FILE PATHS, never pasted into the dispatch prompt: the
  draft, the diff, the report. Whatever you paste stays in your context for
  the rest of the session.
- Never pre-judge: a dispatch prompt never tells a reviewer what not to flag
  and never rates a finding's severity for it.
- Name the model on every dispatch — a standard model for authors and
  implementers, the most capable one available for reviewers. Never inherit
  the session default silently.
- Findings → fix subagent → re-review, at most 3 rounds. A BLOCKER still
  standing after round 3 stops the flow and goes to the Dev.
- A finding that contradicts the approved design or plan is never auto-fixed:
  show the finding beside the text that mandates it and let the Dev choose.
- Criteria come from `docs/pr-review-rubric.md`, then
  `docs/pr-review-rubric.local.md` — the local file wins. Severity is always
  BLOCKER / SUGGESTED / NOTE / NITS.
- Where the runtime cannot dispatch subagents, run the review as its own pass
  that reads ONLY the paths it was handed and reuses nothing it remembers from
  drafting — and say so in the report: one context reviewing
  itself is a weaker substitute, not an equivalent.
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_templates.py -q`
Expected: PASS — including the pre-existing
`test_dev_wrappers_carry_byte_identical_shared_blocks`, which is unaffected
because the three SHARED-* blocks are untouched.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init tests/test_templates.py
git commit -m "feat(dev): shared review-dispatch contract in the four phase skills"
```

---

### Task 3: A1 — independent design review in `dev-design`

**Files:**
- Modify: `claude-skill-dev-design.md`, `claude-command-dev-design.md`, `copilot-dev-design.prompt.md`, `cursor-dev-design.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: the contract block (Task 2); `docs/pr-review-rubric.md` §`Pre-code axes` (Task 1).
- Produces: the `## Review record` table shape
  `| Date | Round | Verdict | Reviewer | Open gaps |`, reused verbatim by
  Task 4 in the plan file.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_dev_design_dispatches_an_independent_reviewer_before_gate_one():
    for name in _dev_wrapper_names("dev-design"):
        body = _normalised(_dev_wrapper_body(name))
        assert "A1" in body, name
        assert "design-author" in body, name
        assert "design-reviewer" in body, name
        assert "Pre-code axes" in body, name
        assert "## Review record" in body, name
        assert "GATE 1 is offered only after A1 comes back clean" in body, name
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_templates.py -k dev_design_dispatches -v`
Expected: FAIL — `AssertionError: claude-skill-dev-design.md`.

- [ ] **Step 3: Insert the A1 section in all four wrappers**

Insert verbatim, immediately **before** the `## GATE 1` heading (which stays
exactly as it is) in all four wrappers:

```markdown
## A1 — independent design review (before GATE 1)

Write the design in its own context: dispatch a `design-author` subagent with
the resolved context cache path, the ticket's acceptance criteria and the
conventions paths, and let it write `docs/impl/<ticket-id>-design.md` with
`status: draft`. You orchestrate; you do not draft and then judge your own
draft.

That design is a draft until a reviewer that never saw it being written
says otherwise. Dispatch a `design-reviewer` subagent and hand it exactly
three things: the path `docs/impl/<ticket-id>-design.md`, the ticket's
acceptance criteria, and the `## Pre-code axes` of the rubric. Not your
reasoning, not this conversation.

It returns pass/fail per axis plus a gap list in which every gap names the
section it lives in, its severity, and a proposed fix. Apply Critical and
Important gaps through a fix subagent, then re-review — at most 3 rounds.

Record every round in the design file's `## Review record` table, creating it
below the design body on round 1:

    | Date | Round | Verdict | Reviewer | Open gaps |
    |---|---|---|---|---|
    | 2026-09-19 | 1 | BLOCKER x1 | design-reviewer | AC3 not addressed |

GATE 1 is offered only after A1 comes back clean. A BLOCKER surviving round 3
goes to the Dev with the reviewer's text and yours, and the flow stops there.
```

In `claude-command-dev-design.md` the same block goes in the same place —
these wrappers carry rule sections verbatim, only the procedure paragraph is
compressed.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_templates.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init tests/test_templates.py
git commit -m "feat(dev-design): A1 independent design review before GATE 1"
```

---

### Task 4: A2 — independent plan review in `dev-plan`

**Files:**
- Modify: `claude-skill-dev-plan.md`, `claude-command-dev-plan.md`, `copilot-dev-plan.prompt.md`, `cursor-dev-plan.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: the contract block; the `## Review record` table shape from Task 3.
- Produces: the plan-file marker `Review: ✅ r<n>`, written per task by Task 5.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_dev_plan_dispatches_an_independent_reviewer_before_gate_two():
    for name in _dev_wrapper_names("dev-plan"):
        body = _normalised(_dev_wrapper_body(name))
        assert "A2" in body, name
        assert "plan-author" in body, name
        assert "plan-reviewer" in body, name
        assert "Pre-code axes" in body, name
        assert "one task per AC" in body, name
        assert "GATE 2 is offered only after A2 comes back clean" in body, name
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_templates.py -k dev_plan_dispatches -v`
Expected: FAIL — `AssertionError: claude-skill-dev-plan.md`.

- [ ] **Step 3: Insert the A2 section in all four wrappers**

Insert verbatim, immediately **before** the review-dispatch contract block
added in Task 2 (so the order reads: Steps, A2, contract, Hard rules — the
same order every other phase uses):

```markdown
## A2 — independent plan review (before GATE 2)

Dispatch a `plan-author` subagent to turn the approved design into the plan —
it gets the design file path, the ticket's acceptance criteria and the
`cmd.test` / `cmd.lint` commands, and nothing else. Then review it with a
different context.

Dispatch a `plan-reviewer` subagent with a fresh context. Hand it exactly: the
path `docs/impl/<ticket-id>-plan.md`, the ticket's acceptance criteria, and the
`## Pre-code axes` of the rubric. It answers four questions and nothing else:

- Is there exactly one task per AC — none missing, none invented?
- Does every task state its failing test before its implementation?
- Is each task's **Interfaces** entry complete enough that its implementer
  never has to read outside its own task block? An incomplete entry is a
  BLOCKER: it is what forces an implementer to read wider and guess.
- Does every task with no test declare `Exempt: <config|ci|docs|style>` and
  name its verification?

Fix subagent, re-review, at most 3 rounds. Record each round in the plan file's
`## Review record` table, same shape as the design file's. GATE 2 is offered
only after A2 comes back clean.
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_templates.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init tests/test_templates.py
git commit -m "feat(dev-plan): A2 independent plan review before GATE 2"
```

---

### Task 5: A3 per task and A4 per branch in `dev-execute`

**Files:**
- Modify: `claude-skill-dev-execute.md`, `copilot-dev-execute.prompt.md`, `cursor-dev-execute.md` (same numbered list), `claude-command-dev-execute.md` (compressed prose)
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: the contract block; the plan file written by Task 4.
- Produces: the artefact paths `docs/impl/<ticket-id>-review/task-<n>.diff`,
  `…/task-<n>-report.md`, `…/branch.diff` — Task 6 reads `branch.diff`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_dev_execute_reviews_each_task_in_a_separate_context():
    for name in _dev_wrapper_names("dev-execute"):
        body = _normalised(_dev_wrapper_body(name))
        assert "task-reviewer" in body, name
        # The self-review stays, but it is no longer the gate.
        assert "review checkpoint" in body, name
        assert "never satisfies A3" in body, name
        assert "docs/impl/<ticket-id>-review/task-<n>.diff" in body, name
        assert "never `HEAD~1`" in body, name
        assert "two verdicts" in body, name
        assert "Review: ✅ r" in body, name


def test_dev_execute_closes_the_branch_with_a_narrow_review():
    for name in _dev_wrapper_names("dev-execute"):
        body = _normalised(_dev_wrapper_body(name))
        assert "A4" in body, name
        assert "branch-reviewer" in body, name
        assert "branch.diff" in body, name
        # A4's lens is ticket fulfilment; merge risk is A5's job in handover.
        assert "merge risk is A5" in body, name
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_templates.py -k "dev_execute_reviews or dev_execute_closes" -v`
Expected: FAIL — `AssertionError: claude-skill-dev-execute.md`.

- [ ] **Step 3: Rewrite the per-task loop in the three list-shaped wrappers**

In `claude-skill-dev-execute.md`, `copilot-dev-execute.prompt.md` and
`cursor-dev-execute.md`, replace list items 3 through 5 of the **Per unticked
task** step — currently `3. **review checkpoint** …` through
`5. **commit the task's changes.** …` — with:

```markdown
  3. **self-review checkpoint** — pass/fail, not a score: does the test
     actually exercise that AC; is every standard-derived value verbatim
     with a citation comment; does the change follow
     `docs/conventions/<lang>.md` plus `docs/conventions/<lang>.local.md`
     overrides (local wins; where either conflicts with the repo's
     existing dominant style, the repo wins locally — record the
     conflict as a finding for the PR body); did anything else break.
     This is the implementer checking its own work: it catches slips
     early and **never satisfies A3**.
  4. **verify** — run `cmd.test` and `cmd.lint` (the commands you were
     handed) and **show the output**.
  5. **commit the task's changes**, then write the full report to
     `docs/impl/<ticket-id>-review/task-<n>-report.md` and return only
     status, commits, a one-line test summary, and concerns.

  Then, back in the orchestrator — never inside the implementer:

  6. **A3 — independent task review.** Write the diff to a file:
     `git diff <BASE>..HEAD > docs/impl/<ticket-id>-review/task-<n>.diff`,
     where `<BASE>` is the commit you recorded **before** dispatching the
     implementer — never `HEAD~1`, which silently drops every commit of a
     multi-commit task but the last. Dispatch a `task-reviewer` subagent
     with a fresh context and exactly three paths — the task block it was
     given, the report file, the diff file — plus the constraints that bind
     this task, copied verbatim from the plan. It returns **two verdicts,
     both required**: spec compliance (nothing missing, nothing extra) and
     code quality. A report carrying one verdict is not a review; send it
     back. Fix subagent for BLOCKER and SUGGESTED findings, then re-review,
     at most 3 rounds.
  7. **Only once A3 is clean**, tick the task's checkboxes in the plan file
     and append `Review: ✅ r<n>` under the task. A ticked box means
     reviewed, so a later session — or a session after compaction — resumes
     at the first unticked task and never re-runs finished work. NOTE and
     NITS findings go to the PR's `## Findings` instead of a fix round.
```

- [ ] **Step 4: Rewrite the compressed paragraph in the command wrapper**

In `claude-command-dev-execute.md`, the procedure paragraph currently ends:

> … then commit the task's changes — ticking its checkboxes in the plan file
> happens next, back in the orchestrator, since the plan file itself is never
> handed to the subagent.

Replace that clause with:

```markdown
then commit the task's changes and write the full report to
`docs/impl/<ticket-id>-review/task-<n>-report.md`. The self-review
**never satisfies A3**: back in the orchestrator, write
`git diff <BASE>..HEAD` — `<BASE>` recorded before the dispatch, never
`HEAD~1` — to `docs/impl/<ticket-id>-review/task-<n>.diff` and dispatch a
`task-reviewer` subagent with a fresh context and exactly three paths (task
block, report file, diff file) plus the constraints copied verbatim from the
plan; it returns **two verdicts**, spec compliance and code quality, both
required. Fix subagent, re-review, at most 3 rounds. Only once A3 is clean
does the orchestrator tick the checkboxes and append `Review: ✅ r<n>` under
the task — the plan file itself is never handed to a subagent.
```

- [ ] **Step 5: Add the A4 section to all four wrappers**

Insert verbatim, immediately **before** the review-dispatch contract block:

```markdown
## A4 — narrow branch review (after the last task)

Every box ticked is not the same as the ticket being done. Write the branch
diff to `docs/impl/<ticket-id>-review/branch.diff`
(`git diff $(git merge-base <default-branch> HEAD)..HEAD`) and dispatch a
`branch-reviewer` subagent with that path, the plan, and the ticket. One
question only: does this branch fulfil the ticket — every AC covered by a
test, nothing built that no AC asked for, and no later task quietly breaking
an earlier one?

Keep the lens narrow here; merge risk is A5's job in `dev-handover`, against a
different rubric. Fix subagent, re-review, at most 3 rounds. Then option 1 is
`/dev-handover <ticket-id>`.
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_templates.py -q`
Expected: PASS — including the pre-existing
`test_dev_execute_has_a_review_checkpoint_and_shown_verification` and
`test_dev_execute_review_checkpoint_points_at_the_conventions_files`, whose
needles ("review checkpoint", the conventions paths) survive the rewrite.

- [ ] **Step 7: Commit**

```bash
git add src/strata_kb/templates/init tests/test_templates.py
git commit -m "feat(dev-execute): A3 per-task review in its own context, A4 branch review"
```

---

### Task 6: A5 — merge-risk review in `dev-handover`

**Files:**
- Modify: `claude-skill-dev-handover.md`, `claude-command-dev-handover.md`, `copilot-dev-handover.prompt.md`, `cursor-dev-handover.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: `docs/impl/<ticket-id>-review/branch.diff` (Task 5); the rubric's
  `## Merge-risk axes` (Task 1).
- Produces: the PR body section `## Review` carrying the finding table and a
  `Blocking: Yes|No` line — Task 7 makes `kb pr lint` check exactly that.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_dev_handover_runs_a_merge_risk_review_before_gate_three():
    for name in _dev_wrapper_names("dev-handover"):
        body = _normalised(_dev_wrapper_body(name))
        assert "A5" in body, name
        assert "merge-risk-reviewer" in body, name
        assert "Merge-risk axes" in body, name
        assert "The diff alone is not the review" in body, name
        assert "Blocking: No" in body, name
        assert "never reaches GATE 3" in body, name
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_templates.py -k dev_handover_runs -v`
Expected: FAIL — `AssertionError: claude-skill-dev-handover.md`.

- [ ] **Step 3: Insert the A5 section in all four wrappers**

Insert verbatim, immediately **before** the review-dispatch contract block:

```markdown
## A5 — merge-risk review (before GATE 3)

A4 asked whether the branch does what the ticket said. A5 asks a different
question, in a different context: is this safe to merge into the default
branch?

Dispatch a `merge-risk-reviewer` subagent on the most capable model available.
Give it the persona plainly: a tech lead reviewing before a production deploy,
assuming real traffic, concurrent requests, retries, and more than one running
instance. Hand it `docs/impl/<ticket-id>-review/branch.diff`, the ticket, and
the `## Merge-risk axes` of `docs/pr-review-rubric.md` plus
`docs/pr-review-rubric.local.md`.

**The diff alone is not the review.** Say so in the dispatch: the reviewer
opens the files the change reaches — callers, siblings, migrations, permission
declarations, contracts, tests — and traces the affected flow end to end before
judging. A finding that only names a category is not a finding; it states why
this code, on this path, is dangerous.

It writes `docs/impl/<ticket-id>-review/merge-risk.md`: one row per finding
(severity, file, line, why it is dangerous, proposed fix), then the verdict
line `Blocking: Yes` while any BLOCKER stands, `Blocking: No` otherwise. Fix
subagent, re-review, at most 3 rounds.

Copy the table and the verdict line into the PR body's `## Review` section —
`kb pr lint` fails the PR when the verdict line is missing and when it reads
`Blocking: Yes`. NOTE and NITS findings go to `## Findings` as feedback items.

A branch whose A5 still reports `Blocking: Yes` never reaches GATE 3. Option 1
becomes the fix, not the PR.
```

- [ ] **Step 4: Add `## Review` to the PR assembly step**

In the same four wrappers, the PR-assembly step lists the required sections
("**Ticket**; **kb-context** …; and the **Usage** table"). Extend that
sentence so the skill names every section the gate will demand:

```markdown
…and the **Usage** table; and **Review** — A5's finding table and its
`Blocking:` verdict line.
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_templates.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/templates/init tests/test_templates.py
git commit -m "feat(dev-handover): A5 merge-risk review before GATE 3"
```

---

### Task 7: `kb pr lint` gains the `## Review` section and the `Blocking:` rule

**Files:**
- Modify: `src/strata_kb/prlint.py`
- Modify: `src/strata_kb/templates/init/pull-request-template.md`
- Test: `tests/test_prlint.py`

**Interfaces:**
- Consumes: the PR section produced by Task 6.
- Produces: `REQUIRED_SECTIONS` with `"Review"` as its ninth and last entry;
  finding codes `no-review-verdict` and `review-blocking`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_prlint.py`, extend the `_body` helper's `filled` dict with:

```python
        "Review": "| Severity | File | Line | Why | Fix |\n|---|---|---|---|---|\n\nBlocking: No",
```

Update `test_canon_is_the_eight_sections_in_order` — rename it to
`test_canon_is_the_nine_sections_in_order` and append `"Usage"` and
`"Review"` to its expected tuple in that order. Then append:

```python
def test_a_clean_review_passes():
    assert lint_body(_body()).passed


def test_review_without_a_verdict_line_fails():
    body = _body(Review="Looks fine to me.")
    assert ("Review", "no-review-verdict") in _codes(body)


def test_none_does_not_satisfy_the_review_section():
    # Review is deliberately NOT a sentinel section: a clean review still
    # states its verdict.
    assert "Review" not in SENTINEL_SECTIONS
    assert ("Review", "no-review-verdict") in _codes(_body(Review="none"))


def test_a_blocking_review_fails_the_pr():
    body = _body(Review="| BLOCKER | a.py | 1 | leaks | fix |\n\nBlocking: Yes")
    assert ("Review", "review-blocking") in _codes(body)
    assert not lint_body(body).passed


def test_the_verdict_line_is_case_insensitive():
    assert lint_body(_body(Review="blocking: no")).passed
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_prlint.py -q`
Expected: FAIL — the canon test reports the eight-tuple, and the new tests
report an empty findings set for `Review`.

- [ ] **Step 3: Implement the rule**

In `src/strata_kb/prlint.py`, append `"Review"` to `REQUIRED_SECTIONS` after
`"Usage"`, leave `SENTINEL_SECTIONS` untouched, and add next to the other
module-level patterns:

```python
# The merge-risk review's verdict line (A5). Anchored at line start so a
# sentence mentioning the word cannot pass for a verdict.
_BLOCKING = re.compile(
    r"^Blocking:[ \t]*(?P<verdict>Yes|No)\b", re.IGNORECASE | re.MULTILINE
)
```

Add the checker beside `_check_exemptions`:

```python
def _check_review(visible: str) -> Finding | None:
    """A5's verdict: recorded at all, and what it says."""
    match = _BLOCKING.search(visible)
    if match is None:
        return Finding(
            "Review",
            "no-review-verdict",
            "no `Blocking: Yes|No` line — the merge-risk review's verdict was "
            "never recorded; a clean review still states `Blocking: No`",
        )
    if match.group("verdict").lower() == "yes":
        return Finding(
            "Review",
            "review-blocking",
            "the merge-risk review still reports blocking findings — fix them "
            "and re-review; `Blocking: Yes` never merges",
        )
    return None
```

In `lint_body`, after the `TDD exemptions` branch:

```python
        if section == "Review":
            finding = _check_review(visible)
            if finding is not None:
                findings.append(finding)
```

- [ ] **Step 4: Add the section to the shipped PR template**

Append to `src/strata_kb/templates/init/pull-request-template.md`:

```markdown
## Review

<!--
A5, the merge-risk review from /dev-handover: one row per finding, then the
verdict line. `kb pr lint` fails when the verdict line is missing and when it
reads `Blocking: Yes`. `none` does not answer this section — a clean review
still states `Blocking: No`.

| Severity | File | Line | Why it is dangerous | Fix |
|---|---|---|---|---|
| BLOCKER | src/orders/service.py | 118 | ... | ... |

Blocking: No
-->
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_prlint.py tests/test_cli_prlint.py tests/test_templates.py tests/test_init.py -q`
Expected: PASS. Three canon pins move together here:
`test_pr_template_headings_are_the_canon_in_order` (template order),
`test_every_required_section_is_named_in_the_dev_handover_wrappers` (satisfied
by Task 6), and `test_the_shipped_pr_template_fails_the_linter`, which still
sees only `empty-section` because the new section ships as a comment.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/prlint.py src/strata_kb/templates/init/pull-request-template.md tests/test_prlint.py
git commit -m "feat(prlint): require the merge-risk review verdict and fail on Blocking: Yes"
```

---

### Task 8: Restate the guide and the changelog

**Files:**
- Modify: `docs/src/guide-dev.en.md`, `docs/src/guide-dev.vi.md` (§4 diagram, §4.3, §5.1, §5.2)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything above. Produces: no code.

- [ ] **Step 1: Update the flow diagram in §4**

Both language files draw the five-command flow. Add the agent reviews beside
the human gates, e.g. in the Vietnamese file:

```
/dev-implement-ticket <ticket>     intake · resolve · ground · placeholders
        │
        ├─► dev-design       ── A1: reviewer độc lập ── GATE 1: bạn duyệt thiết kế
        ├─► dev-plan         ── A2: reviewer độc lập ── GATE 2: bạn duyệt kế hoạch
        ├─► dev-execute         A3 mỗi task · A4 cuối nhánh  (lặp lại được)
        └─► dev-handover     ── A5: merge-risk ── GATE 3: bạn mở PR
                                GATE 4: bạn merge
```

- [ ] **Step 2: Rewrite §4.3**

Replace the "Bốn cổng" / "Four gates" section so it states both ladders and
which is which. Vietnamese:

```markdown
## 4.3 Bốn cổng người, năm vòng review agent

Không gì trong quy trình này merge hay ship mà không có con người.

1. **Thiết kế được duyệt** — bạn ký duyệt trước khi viết bất kỳ kế hoạch nào.
2. **Kế hoạch được duyệt** — bạn ký duyệt trước khi viết bất kỳ dòng code nào.
3. **PR được mở** — agent viết nội dung; bạn mở PR.
4. **Merge** — bạn review và merge.

Agent không tự làm hai việc cuối.

Trước mỗi cổng, một agent khác đã đọc lại công việc trong một ngữ cảnh riêng —
không phải chính agent đã làm ra nó:

| | Ở đâu | Nhìn cái gì |
|---|---|---|
| A1 | `dev-design`, trước GATE 1 | thiết kế có khớp ticket không |
| A2 | `dev-plan`, trước GATE 2 | kế hoạch có chạy được, có test-first không |
| A3 | `dev-execute`, mỗi task | diff này có đúng spec của task, và viết có tốt không |
| A4 | `dev-execute`, sau task cuối | nhánh có làm tròn ticket không |
| A5 | `dev-handover`, trước GATE 3 | merge vào nhánh chính có an toàn không |

Tiêu chí ở `docs/pr-review-rubric.md`, ghi đè bằng
`docs/pr-review-rubric.local.md`. Mỗi vòng tối đa 3 lượt fix/review; còn
BLOCKER sau lượt 3 thì dừng lại và hỏi bạn.
```

Mirror the same structure in the English file.

- [ ] **Step 3: Move the `## Review` rule from §5.2 to §5.1**

In §5.1 (machine-guaranteed), add a row:

```markdown
| Merge-risk review đã chạy và không còn BLOCKER | `kb pr lint` — mục `## Review` phải có dòng `Blocking: No` |
```

In §5.2 (prompt-only), add this bullet to the list of things nothing measures:

```markdown
- **A1–A4.** Bốn vòng review agent trước GATE 3 là kỷ luật trong prompt.
  Không có gì trong `kb` đo được rằng chúng đã chạy. Chỉ A5 có răng: `kb pr
  lint` đọc mục `## Review` của PR. Một agent bỏ qua A1–A4 rồi viết một dòng
  `Blocking: No` trung thực vẫn qua cổng — cổng nằm ở chỗ merge thật sự xảy
  ra, không phải ở mọi bước trước đó.
```

English file, same bullet:

```markdown
- **A1–A4.** The four agent reviews before GATE 3 are prompt discipline.
  Nothing in `kb` measures whether they ran. Only A5 has teeth: `kb pr lint`
  reads the PR's `## Review` section. An agent that skips A1–A4 and writes an
  honest `Blocking: No` still passes — the gate sits where the merge actually
  happens, not at every step before it.
```

- [ ] **Step 4: Add the changelog entry**

Under the unreleased heading in `CHANGELOG.md`:

```markdown
### Added
- Dev flow: independent review subagents at every phase — A1 (design), A2
  (plan), A3 (per task), A4 (branch), A5 (merge-risk) — with a shared
  dispatch contract that keeps author and reviewer in separate contexts.
- `docs/pr-review-rubric.md` and its create-once `docs/pr-review-rubric.local.md`
  override, scaffolded by `kb init --kind dev`.
- `kb pr lint` requires a ninth section, `## Review`, and fails on a missing
  verdict line or `Blocking: Yes`.
```

- [ ] **Step 5: Verify the whole suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add docs/src/guide-dev.en.md docs/src/guide-dev.vi.md CHANGELOG.md
git commit -m "docs: the dev flow's five agent reviews beside its four human gates"
```
