# Short dev-repo PR body — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The PR body `dev-handover` writes, and `kb pr lint` requires, becomes Ticket / Changes / Testing (+ optional Notes).

**Architecture:** `prlint.REQUIRED_SECTIONS` shrinks to three; the fence/`cmd.test` and `Blocking:` checks move into `## Testing`; exemption/sentinel/alias code is deleted. The shipped PR template, the four `dev-handover` wrappers and every doc that names the old sections follow.

**Tech Stack:** Python 3.11+, pytest, Markdown templates under `src/strata_kb/templates/init/`.

**Spec:** `docs/superpowers/specs/2026-10-04-dev-pr-body-short-design.md`

## Global Constraints

- Canon: `REQUIRED_SECTIONS = ("Ticket", "Changes", "Testing")`; `## Notes` optional and never inspected.
- `kb-pr-lint.yml`: workflow file name and job name `pr-lint` stay frozen.
- `SHARED-*` blocks in the dev wrappers are not edited (`test_shared_hard_rules_were_not_touched_by_the_c5_round` pins length 1531).
- No version bump; CHANGELOG under `## Unreleased`, marked **Breaking** for dev repos on re-init.
- Python: `.venv/Scripts/python -m pytest`, `.venv/Scripts/python -m ruff check src tests`.
- Pre-existing failures on main, not ours: `test_mcp_setup_hidden_prompt_never_echoes_the_token`, `test_scaffolded_workflows_pin_the_scaffolding_version`.

---

### Task 1: `prlint` canon

**Files:**
- Modify: `src/strata_kb/prlint.py`
- Test: `tests/test_prlint.py`

**Interfaces:**
- Produces: `REQUIRED_SECTIONS: tuple[str, ...] = ("Ticket", "Changes", "Testing")`; `lint_body(body, *, plan_dir=None) -> PRLintReport` unchanged signature; finding codes `no-verification-output`, `verification-missing-cmd`, `plan-dir-unset`, `plan-missing`, `cmd-test-unset` now carry section `"Testing"`; `no-review-verdict`, `review-blocking` carry section `"Testing"`. Removed: `SENTINEL_SECTIONS`, `EXEMPTION_SLUGS`.

- [ ] **Step 1: Rewrite the test fixture and canon tests (RED)**

In `tests/test_prlint.py`:
- Import only `REQUIRED_SECTIONS, lint_body` at the top.
- `_body` fills:
  ```python
  filled = {
      "Ticket": "open-new-flight — add the new-flight endpoint",
      "Changes": "- flights/api.py: POST /flights",
      "Testing": "AC1 → test_rejects_bad_icao\n\n```\n12 passed in 0.4s\n```\n\nBlocking: No",
  }
  ```
- Canon test:
  ```python
  def test_canon_is_ticket_changes_testing():
      assert REQUIRED_SECTIONS == ("Ticket", "Changes", "Testing")
  ```
- Add:
  ```python
  def test_notes_is_optional_and_never_inspected():
      assert lint_body(_body()).passed
      assert lint_body(_body() + "\n\n## Notes\n\n<!-- nothing -->\n").passed

  def test_an_old_nine_section_body_fails_on_the_new_canon():
      old = "## Ticket\n\nATM-7\n\n## Verification\n\n```\nok\n```\n\n## Review\n\nBlocking: No"
      codes = _codes(old)
      assert ("Changes", "missing-section") in codes
      assert ("Testing", "missing-section") in codes
  ```
- Every remaining test that used `Verification=` / `Review=` now uses `Testing=` with the same content, and expects section `"Testing"` in the finding tuple. A `Testing` override that tests the fence must still carry `Blocking: No` (append `"\n\nBlocking: No"`) so only the fence check fails; a test of the verdict keeps a valid fence (prefix `"```\nok\n```\n\n"`).
- `.replace("## Usage", ...)`, `("Usage", ...)` and `## TDD exemptions` in the comment/fence/duplicate tests become `## Changes` / `("Changes", ...)` — the last section after Testing no longer exists, so the "swallows every later heading" tests assert on a section that follows the swallowing one: put the swallow in `Ticket` and assert `("Testing", "missing-section")`.
- `test_an_empty_body_reports_every_section_missing` expects `{(n, "missing-section") for n in REQUIRED_SECTIONS} | {("Testing", "plan-dir-unset")}`.
- Delete: `test_none_is_a_valid_answer_in_the_two_sentinel_sections`, `test_the_ascii_arrow_spelling_is_accepted`, `test_the_four_exemption_slugs_are_the_canon`, `test_exemption_lines_naming_a_known_slug_pass`, `test_none_still_passes_the_exemption_section`, `test_an_unknown_exemption_class_is_an_error`, `test_prose_in_the_exemption_section_is_an_error`, `test_none_does_not_satisfy_the_review_section` (replace with: `assert ("Testing", "no-review-verdict") in _codes(_body(Testing="```\nok\n```\n\nnone"))`).

- [ ] **Step 2: Run, expect failures**

Run: `.venv/Scripts/python -m pytest tests/test_prlint.py -q`
Expected: FAIL (canon test, ImportError gone but section names differ).

- [ ] **Step 3: Implement in `src/strata_kb/prlint.py`**

- `REQUIRED_SECTIONS = ("Ticket", "Changes", "Testing")`.
- Delete `SENTINEL_SECTIONS`, `_HEADING_ALIASES` (and its use in `_split_sections`: `sections.append((name, []))`), `EXEMPTION_SLUGS`, `_EXEMPTION_LINE`, `_NONE`, `_exemption_finding`, and the comment block above `EXEMPTION_SLUGS`.
- In `lint_body`: empty-section hint becomes plain `"empty once HTML comments are stripped — fill it in"`; replace the three per-section branches with:
  ```python
  if section == "Testing":
      if not _has_fenced_output(visible):
          findings.append(Finding(
              section, "no-verification-output",
              "no fenced block holding real output — paste the cmd.test "
              "command and its summary lines; a claim is not evidence",
          ))
      finding = _check_review(visible)
      if finding is not None:
          findings.append(finding)
  ```
- `_check_review`: section `"Testing"` in both findings; messages unchanged.
- `_plan_findings`: every `"Verification"` → `"Testing"`; `first.get("Verification", "")` → `first.get("Testing", "")`.
- Module docstring: "the shipped PR template and the `dev-handover` wrappers are pinned against it" stays; nothing else names the count.

- [ ] **Step 4: Run, expect pass**

Run: `.venv/Scripts/python -m pytest tests/test_prlint.py tests/test_cli_prlint.py -q`
Expected: PASS. If `test_cli_prlint.py` builds a nine-section body, convert it to the three-section shape the same way.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/prlint.py tests/test_prlint.py tests/test_cli_prlint.py
git commit -m "feat: kb pr lint requires Ticket / Changes / Testing only"
```

### Task 2: PR template + `dev-handover` wrappers

**Files:**
- Modify: `src/strata_kb/templates/init/pull-request-template.md`
- Modify: `src/strata_kb/templates/init/claude-skill-dev-handover.md`, `claude-command-dev-handover.md`, `copilot-dev-handover.prompt.md`, `cursor-dev-handover.md`
- Test: `tests/test_templates.py`

**Interfaces:**
- Consumes: `REQUIRED_SECTIONS` from Task 1.

- [ ] **Step 1: Update template tests (RED)**

In `tests/test_templates.py`:
- `test_dev_handover_lists_the_pr_contents`: items `("Ticket", "Changes", "Testing", "Notes", "OPEN(", "KB gap")`; update its comment to say the bullet names the three required sections plus Notes.
- Replace `test_dev_handover_reports_usage_in_the_pr` with:
  ```python
  def test_dev_handover_keeps_usage_out_of_the_pr():
      for name in _dev_wrapper_names("dev-handover"):
          body = _dev_wrapper_body(name)
          assert "## Usage" not in body, name
          assert "the usage table" in body, name
  ```
- Replace `test_dev_handover_reports_the_exemptions_or_none` with:
  ```python
  def test_dev_handover_leaves_exemptions_in_the_plan():
      for name in DEV_HANDOVER_TEMPLATES:
          body = _dev_wrapper_body(name)
          assert "## TDD exemptions" not in body, name
          assert _normalised("TDD exemptions (the plan)") in body, name
  ```
- Replace the needle in `test_dev_handover_pr_assembly_adds_the_review_section` with `"`Blocking: No`, A5's verdict line, as the last line"` and rename it `test_dev_handover_pr_assembly_ends_testing_with_the_verdict`.
- Delete `test_tdd_exemptions_doc_names_every_slug_prlint_recognizes` (the hand-kept `EXEMPTION_SLUGS` tuple test above it still pins the doc).

Run: `.venv/Scripts/python -m pytest tests/test_templates.py -q -k "handover or pr_template or required_section"` — Expected: FAIL.

- [ ] **Step 2: Rewrite `pull-request-template.md`**

```markdown
<!--
Assembled by /dev-handover and checked in CI by `kb pr lint`. Ticket, Changes
and Testing are required; a section still holding only its comment counts as
empty and fails. Notes is optional — delete it when there is nothing to say.
Keep it short: the branch already carries the context cache, the plan and
the review files.

Scaffolded by `kb init --kind dev` and regenerated by a later `kb init`.
-->

## Ticket

<!-- The ticket id and what it asked for, one or two lines. -->

## Changes

<!-- One bullet per change a reviewer should know about. -->

## Testing

<!--
One line mapping each AC to its test. Then a fenced block with the cmd.test
command line itself and its summary lines only (e.g. `$ pytest -q` /
`212 passed in 8.1s`), plus the lint result — not the full log. Last line:
A5's verdict, `Blocking: No`.
-->

## Notes

<!-- Optional: out of scope, not handled, OPEN(...) / KB-gap findings, a
non-ok freshness result, `amend needed`. -->
```

Note: `_pr_template_headings()` must return exactly `REQUIRED_SECTIONS` — so `## Notes` breaks `test_pr_template_headings_are_the_canon_in_order`. Change that test to
`assert tuple(_pr_template_headings()) == REQUIRED_SECTIONS + ("Notes",)`.

- [ ] **Step 3: Rewrite the handover step in all four wrappers**

In `claude-skill-dev-handover.md`, `copilot-dev-handover.prompt.md`, `cursor-dev-handover.md` (same body text in all three):

a. Spike bullet: `under `## Findings` in the PR body` → `under `## Notes` in the PR body`.

b. Freshness bullet's last sentence → `Report it under `## Notes` only when it is not `ok` (the `--status-only` output when the cache path was taken).`

c. Full-suite bullet: keep `**paste the real output**` and `A completion claim without it is not accepted.`; append `Into the PR goes only the command line and its summary lines (see Testing below).`

d. `-svc` missing sentence: `say so in one line in the PR` → `say so in one line under `## Notes``.

e. Replace the whole "Assemble the PR description" bullet with:

```markdown
- **Assemble the PR description** using the repo's
  `.github/pull_request_template.md`, whose sections CI checks with
  `kb pr lint`. Keep it short: **Ticket** — the ticket id and what it
  asked for, one or two lines; **Changes** — one bullet per change a
  reviewer should know about; **Testing** — one line mapping each AC to
  its test, then a fenced block holding the `cmd.test` command line
  itself (e.g. `$ pytest -q`) and only its summary lines, never the full
  log, and `Blocking: No`, A5's verdict line, as the last line;
  **Notes** — only when there is something: out of scope, not handled,
  every `OPEN(...)`, KB gap, ambiguity or contradiction as a concrete
  feedback item on the owning repo. Leave out what the branch already
  carries: kb-context (the ticket), placeholder resolutions
  (`docs/impl/<ticket-id>-context.md`), TDD exemptions (the plan), the
  usage table (`kb usage report`), and A5's finding table
  (`docs/impl/<ticket-id>-review/merge-risk.md`). A section left as the
  template's comment counts as empty and fails the check.
```

f. Delete the "**Report the cost**" bullet entirely.

g. "Amend findings" bullet: `report ... as a PR finding` → `report ... under `## Notes``.

h. A5 section paragraph "Copy the table and the verdict line into the PR body's `## Review` section — …" → 

```markdown
Copy only the verdict line into the PR body, as the last line of
`## Testing` — `kb pr lint` fails the PR when it is missing and when it
reads `Blocking: Yes`. The table stays in `merge-risk.md`. NOTE and NITS
findings a reviewer should see go to `## Notes`, recorded rather than
fixed.
```

In `claude-command-dev-handover.md` (one long paragraph): apply a–h to the same clauses in prose form — spike `## Findings` → `## Notes`; "paste the freshness output … into the PR" → "report it under `## Notes` only when it is not `ok` (the `--status-only` output when the cache path was taken)"; the "assemble the PR description … and Review — A5's finding table and its `Blocking:` verdict line." span replaced by the text of (e) without the bullet marker; delete "Then run `kb usage report … instead of a table;`"; "as a PR finding" → "under `## Notes`"; the A5 paragraph as in (h).

- [ ] **Step 4: Run, expect pass**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py tests/test_init.py -q`
Expected: PASS except the pre-existing `test_scaffolded_workflows_pin_the_scaffolding_version`.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init/pull-request-template.md src/strata_kb/templates/init/*dev-handover* tests/test_templates.py
git commit -m "feat: dev-handover writes a short PR body (Ticket / Changes / Testing / Notes)"
```

### Task 3: Other references, docs, CHANGELOG

**Files:**
- Modify: `src/strata_kb/templates/init/{claude-skill,copilot,cursor}-dev-plan*.md`, `claude-command-dev-plan.md` — `## Findings` → `## Notes`.
- Modify: `src/strata_kb/templates/init/{claude-skill,copilot,cursor}-dev-execute*.md` — `NITS findings go to the PR's `## Findings`` → `## Notes`.
- Modify: `src/strata_kb/templates/init/tdd-exemptions.md`, `QUICKSTART-dev.md`, `kb-pr-lint.yml` (header comment), `src/strata_kb/initcmd.py:197` comment.
- Modify: `docs/src/guide-dev.en.md`, `docs/src/guide-dev.vi.md`, `CHANGELOG.md`.

- [ ] **Step 1: Templates**

- `tdd-exemptions.md` last paragraph →
  `Every exemption taken during a ticket is declared in the plan as an `Exempt:` line, and reviewed there at GATE 2 (A2). It is not repeated in the PR description.`
- `QUICKSTART-dev.md` Machine-enforced first bullet: replace "It fails when … `style`." with "It fails when Ticket, Changes or Testing is missing or still holds the template's comment, when Testing has no fenced output, when no fence holds the plan's `cmd.test:` command, or when Testing carries no `Blocking: No` line." Last Machine-enforced bullet: "`## Review` section" → "`## Testing` section". A1–A4 bullet: "reads the PR's `## Review` section" → "reads the `Blocking:` line in the PR's `## Testing` section". Line ~375 "a Markdown table for a PR body" → "a Markdown table". Line ~455 "(it now carries A5's finding table)" → delete the parenthesis.
- `kb-pr-lint.yml` first two comment lines → `# CI evidence gate: every pull request must carry the short description `dev-handover` assembles — Ticket, Changes, Testing (pasted test run + A5 verdict).`
- `initcmd.py:197` comment: rename the `## TDD exemptions` mention to `## Testing`.

- [ ] **Step 2: Guides**

- `guide-dev.en.md` §5.1 table row: "`## Review` section must carry" → "`## Testing` section must carry"; paragraph below →
  "`kb pr lint` fails when Ticket, Changes or Testing is missing or still holds the template's comment, when Testing has no pasted output or no fence containing the plan's test command, or when its `Blocking:` line is missing or reads `Yes`."
  §5.2 A1–A4: "reads the PR's `## Review` section" → "reads the `Blocking:` line in the PR's `## Testing` section". Troubleshooting rows `no-review-verdict` / `review-blocking`: "`## Review` section" → "`## Testing` section".
- `guide-dev.vi.md` same edits: "mục `## Review`" → "mục `## Testing`"; paragraph →
  "`kb pr lint` fail khi thiếu Ticket, Changes hoặc Testing, hoặc mục đó còn nguyên dòng chú thích mẫu, khi Testing không có output đã dán hay không có khối nào chứa lệnh test của kế hoạch, hoặc khi dòng `Blocking:` thiếu hay ghi `Yes`."

- [ ] **Step 3: CHANGELOG** — under `## Unreleased`, add:
  "- **Breaking for dev repos on re-init.** The PR body `dev-handover` writes, and `kb pr lint` requires, is now `## Ticket` / `## Changes` / `## Testing` (+ optional `## Notes`). Testing carries the AC→test line, a fence with the `cmd.test` command and its summary lines, and A5's `Blocking: No`. kb-context, placeholder resolutions, TDD exemptions, the usage table and A5's finding table leave the PR — the branch already carries them. `kb-pr-lint.yml` pins the strata-kb version, so a dev repo keeps the old nine-section lint until `kb init --kind dev` re-scaffolds the template, wrappers and pin together; an open PR written against the old template must be rewritten."

- [ ] **Step 4: Verify**

Run: `.venv/Scripts/python -m pytest tests/test_templates.py tests/test_prlint.py tests/test_cli_prlint.py tests/test_init.py -q` and `.venv/Scripts/python -m ruff check src tests`
Expected: PASS (bar the pre-existing init failure); ruff clean. Then the full suite.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init src/strata_kb/initcmd.py docs/src/guide-dev.en.md docs/src/guide-dev.vi.md CHANGELOG.md
git commit -m "docs: dev templates and guides follow the short PR body"
```
