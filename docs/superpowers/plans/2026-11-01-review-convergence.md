# A1/A2 Review Convergence and Readable Hub Q&A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A1/A2 end in at most two rounds with leftover gaps carried to execute, execute writes its deviations back into plan/design, and hub Q&A renders as readable, structured markdown.

**Architecture:** Part 1 is skill text only: the shipped skill bodies under `src/strata_kb/templates/init/bodies/` plus their full-copy wrappers (`claude-command-dev-*.md`, `claude-skill-dev-implement-ticket.md`), pinned by `tests/test_templates.py` and `tests/test_template_bodies.py`. Part 2 adds a `breaks` option to `web/gfmrender.render` and uses it on the Q&A ticket page; the Q&A skills get a fixed question/answer format.

**Tech Stack:** Python 3.13, markdown-it-py, Jinja2, Starlette, pytest, `uv`.

**Spec:** `docs/superpowers/specs/2026-11-01-review-convergence-design.md`

## Global Constraints

- Round 1 of A1/A2 (exhaustive matrix, slices, lead reviewer, class-wide fix, sweep) stays word-for-word.
- A3/A4/A5 caps unchanged; the shared contract bullet keeps "at most 3 rounds" and gains an A1/A2 exception.
- No refusal of unformatted Q&A: `ticketqa.ask_question` / `answer_question` and the MCP tools are not touched.
- Mission and ticket page rendering (`gfmrender.render` with no option) must not change output.
- Raw HTML stays off in every render.
- `lintcore.REVIEW_ROUND_CAP` is not touched.
- Q&A labels are fixed English: question `**Decision needed:**`, `**Background:**`, `**Options:**`, `**Dev recommends:**`, `**AC impact:**`; answer `**Decision:**`, `**Ticket changes (rev N):**`, `**Follow-ups:**`, `**Assumptions:**`. Content is in the ticket's language.
- Table headers, exact: `| Gap | Class | Severity | Raised in | Target task | Status |` under `## Carried gaps`; `| Task | Doc + section | What changed | Why |` under `## Execution deviations`.
- Every block that is byte-identical across wrappers today stays byte-identical: edit the body and its full copy in the same commit.
- When text before `## Auto mode` changes in a file listed in `AUTO_FILES` (`tests/test_template_bodies.py`), refresh its fixture in `tests/fixtures/bodies-pre-auto/` in the same commit with the snippet in **Fixture refresh** below. Never edit a fixture by hand.
- Test canons in `REVIEW_BLOCK_TEXT` (`tests/test_templates.py`) are re-extracted with `repr()` from the landed file, never retyped.
- Release: 1.34.0 (minor: behaviour change in shipped skills and the hub UI).

### Fixture refresh (used by Tasks 3-6)

```bash
uv run python - <<'EOF'
from pathlib import Path
base = Path("src/strata_kb/templates/init"); fx = Path("tests/fixtures/bodies-pre-auto")
from tests.test_template_bodies import AUTO_FILES, AUTO_HEADING
for tpl, fixture in AUTO_FILES.items():
    raw = (base / tpl).read_text(encoding="utf-8")
    (fx / fixture).write_text(raw[: raw.index(AUTO_HEADING)].rstrip("\n") + "\n", encoding="utf-8")
EOF
git diff --stat tests/fixtures/bodies-pre-auto
```

Expected: only the fixtures of files this task edited change.

### Canon refresh (Tasks 3-4)

```bash
uv run python -c "
from tests.test_templates import _review_block
print(repr(_review_block('claude-skill-dev-design.md','A1')))"
```

Paste the printed literal over the dict value (`A1`, `A2` or `REVIEW-CONTRACT`; for the contract use `_review_block('claude-skill-dev-design.md','REVIEW-CONTRACT')`).

## Review Focus

1. An old Q&A question with single newlines and backticks: lines must stay separate and backticks become `<code>`, not one run-on line (Task 1 `test_old_plain_text_question_keeps_its_lines`).
2. `<script>` or `<img>` in question, context or answer stays escaped after the markdown switch (Task 1 keeps `test_script_in_question_and_answer_is_escaped` green unchanged).
3. A round-2 BLOCKER outside the diff must still stop the gate, while a round-2 SUGGESTED outside the diff must not (Task 4 needle tests pin both sentences).
4. A deviation in a parallel lane: the implementer may not edit `plan.md`, so its deviation must still reach `plan.md` (Task 5 pins the merge-back route).
5. A carried gap still open at handover must be visible to the PR reviewer (Task 5 pins `## Notes` in `dev-handover`).

---

### Task 1: Render hub Q&A as markdown with line breaks

**Files:**
- Modify: `src/strata_kb/web/gfmrender.py:70-110`
- Modify: `src/strata_kb/web/qaui.py:159-197`
- Modify: `src/strata_kb/templates/web/questions_ticket.html:18-31`
- Test: `tests/test_web_questions.py`

**Interfaces:**
- Produces: `gfmrender.render(md: str, *, breaks: bool = False) -> str`. `breaks=True` turns every single newline inside a paragraph into `<br>`; `breaks=False` is today's output, byte for byte.
- Produces: template context key `md` = `functools.partial(gfmrender.render, breaks=True)`, used as `{{ md(q.question) | safe }}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_web_questions.py`

```python
def test_old_plain_text_question_keeps_its_lines(web_client_logged_in, hub_with_ticket):
    hub = hub_with_ticket(rev=1)
    q = ask_question(hub, _store(hub), US1, "line one `S3_ENDPOINT`\nline two", "kb-auto",
                     context="design.md §9.3 — test T4")
    answer_question(hub, _store(hub), q.id, "**Decision:** A\n- Scope: x", "ba1", None, [])
    main = _main(web_client_logged_in.get(f"/ui/questions/ticket?repo={REPO}&ticket={US1}").text)
    assert "line one <code>S3_ENDPOINT</code><br" in main
    assert "<strong>Decision:</strong>" in main and "<li>Scope: x</li>" in main
    assert "pre-wrap" not in main

def test_formatted_question_renders_its_labels_and_options(web_client_logged_in, hub_with_ticket):
    hub = hub_with_ticket(rev=1)
    ask_question(hub, _store(hub), US1,
                 "**Decision needed:** pick one\n\n**Options:**\n1. A — fast\n2. B — safe", "dev1")
    main = _main(web_client_logged_in.get(f"/ui/questions/ticket?repo={REPO}&ticket={US1}").text)
    assert "<strong>Decision needed:</strong>" in main
    assert "<ol>" in main and "<li>A — fast</li>" in main
```

And in a gfmrender unit test (same file is fine):

```python
def test_render_default_output_is_unchanged_by_the_breaks_option():
    from strata_kb.web.gfmrender import render
    assert render("a\nb") == "<p>a\nb</p>\n"
    assert "<br" in render("a\nb", breaks=True)
```

- [ ] **Step 2: Run** `uv run pytest tests/test_web_questions.py -q` — Expected: the three new tests FAIL (`render() got an unexpected keyword argument 'breaks'` / missing `<code>`).

- [ ] **Step 3: Implement.** In `gfmrender.py` add a second module-level `MarkdownIt` built like `_MD` with `"breaks": True` and the same plugins/rules; `render(md, *, breaks=False)` picks the engine and keeps the `_line_breaks` / `_asset_srcs` / task post-processing for both. In `qaui.question_ticket_page` pass `md=partial(md_render, breaks=True)` to `_render_page` (import as `planui` does). In the template replace the three `<div style="white-space:pre-wrap">…</div>` for question, context and answer with `<div class="md-body">{{ md(…) | safe }}</div>`. `blocks` stays plain text.

- [ ] **Step 4: Run** `uv run pytest tests/test_web_questions.py tests/test_web*.py -q` — Expected: all PASS, including the unchanged `test_script_in_question_and_answer_is_escaped`.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/web/gfmrender.py src/strata_kb/web/qaui.py src/strata_kb/templates/web/questions_ticket.html tests/test_web_questions.py
git commit -m "feat(web): render hub Q&A as markdown with line breaks kept"
```

---

### Task 2: Execute-verifiable defect classes in the rubric

**Files:**
- Modify: `src/strata_kb/templates/init/pr-review-rubric.md` (end of `## Pre-code axes`, before `## Merge-risk axes`)
- Test: `tests/test_template_bodies.py`

**Interfaces:**
- Produces: the tag name `execute-verifiable` and the class list, cited by Tasks 4-5.

- [ ] **Step 1: Write the failing test**

```python
def test_pr_review_rubric_names_execute_verifiable_classes():
    text = " ".join(read_template("pr-review-rubric.md").split())
    pre = text[text.index("## Pre-code axes"): text.index("## Merge-risk axes")]
    assert "`execute-verifiable`" in pre
    for cls in ("verification command that fails as written", "expected red mis-stated",
                "line-number pin", "e2e timeout or margin not measured",
                "fixture assumption a run checks"):
        assert cls in pre, cls
    assert "never blocks a gate" in pre and "never fixed on paper" in pre
```

- [ ] **Step 2: Run** `uv run pytest tests/test_template_bodies.py -k execute_verifiable -q` — Expected: FAIL.

- [ ] **Step 3: Implement.** Add a short paragraph plus bullet list with the five classes verbatim as in the test, saying a reviewer tags such a gap `execute-verifiable`, it goes to the `## Carried gaps` table with a target task, it never blocks a gate and is never fixed on paper; TDD and CI check it in that task.

- [ ] **Step 4: Run** `uv run pytest tests/test_template_bodies.py tests/test_init.py tests/test_doctor_remote.py -q` — Expected: PASS.

- [ ] **Step 5: Commit** `git commit -m "feat(templates): execute-verifiable defect classes in the PR rubric"`

---

### Task 3: A1/A2 exception in the shared review contract

**Files:**
- Modify: the `## Review dispatch contract` block in `bodies/dev-design.md`, `bodies/dev-plan.md`, `bodies/dev-execute.md`, `bodies/dev-handover.md` and in `claude-command-dev-{design,plan,execute,handover}.md` (8 files, 16 rendered wrappers)
- Test: `tests/test_templates.py` (`REVIEW_BLOCK_TEXT["REVIEW-CONTRACT"]`, `test_review_contract_pins_the_rules_that_make_it_independent`), fixtures

**Interfaces:**
- Produces: the contract sentence `A1 and A2 stop after round 1 plus one verification round; see their **Stop.** rule.` placed right after the "at most 3 rounds" bullet.

- [ ] **Step 1: Write the failing test** — add to `test_review_contract_pins_the_rules_that_make_it_independent`:

```python
    assert "A1 and A2 stop after round 1 plus one verification round" in body
```

- [ ] **Step 2: Run** `uv run pytest tests/test_templates.py -k review_contract -q` — Expected: FAIL.
- [ ] **Step 3: Implement** — insert the sentence as its own bullet after `- Findings → fix subagent → re-review, at most 3 rounds. …` in all 8 files.
- [ ] **Step 4: Canon refresh** for `REVIEW-CONTRACT`, then **Fixture refresh**.
- [ ] **Step 5: Run** `uv run pytest tests/test_templates.py tests/test_template_bodies.py -q` — Expected: PASS.
- [ ] **Step 6: Commit** `git commit -m "feat(templates): review contract points A1/A2 at their two-round stop"`

---

### Task 4: A1 and A2 — two rounds, carried gaps

One task: both phases share `test_a1_a2_review_loop_converges`, so they change together.

**Files:**
- Modify: `bodies/dev-design.md` (A1 section ~154-257; Auto bullets for GATE 1, the stop rule, the round-3 contract) and the same text in `claude-command-dev-design.md`
- Modify: `bodies/dev-plan.md` (A2 section ~189-302; plan-author dispatch and self-check; Auto bullets ~391-397) and `claude-command-dev-plan.md`
- Test: `tests/test_templates.py` (`REVIEW_BLOCK_TEXT["A1"]`, `["A2"]`, `test_a1_a2_review_loop_converges`), `tests/test_template_bodies.py` (`_DEV_GATES` for both bodies), fixtures

**Interfaces:**
- Consumes: `execute-verifiable` (Task 2), contract sentence (Task 3).
- Produces: `## Carried gaps` in `design.md`; `## Carried gaps` in `plan.md` where every row has a task number in `Target task` (read by Task 5).

- [ ] **Step 1: Write the failing tests.** In `test_a1_a2_review_loop_converges` replace the needle `"not lower than the round before, stop at once"` with:

```python
"round 1 plus one verification round",
"does not block, unless it is a BLOCKER",
"`## Carried gaps`",
"| Gap | Class | Severity | Raised in | Target task | Status |",
"`execute-verifiable`",
"no BLOCKER is open and every open SUGGESTED gap is in `## Carried gaps` with a target task",
```

Add:

```python
@pytest.mark.parametrize("skill", ["dev-design", "dev-plan"])
def test_a1_a2_have_no_third_round(skill):
    for name in _dev_wrapper_names(skill):
        body = " ".join(_dev_wrapper_body(name).split())
        for gone in ("cap of 3 rounds", "hand the Dev the trend", "beyond cap",
                     "it still reports any other defect it sees"):
            assert gone not in body, (name, gone)


def test_plan_author_gives_every_design_carried_gap_a_task():
    for name in _dev_wrapper_names("dev-plan"):
        body = " ".join(_dev_wrapper_body(name).split())
        assert "the design's `## Carried gaps`" in body, name
        assert "names a target task for each" in body, name
```

- [ ] **Step 2: Run** `uv run pytest tests/test_templates.py -k "converges or third_round or carried" -q` — Expected: FAIL.

- [ ] **Step 3: Implement** in all four files (A1 wording shown; A2 is the same with GATE 2 and `failed plan-review`):
  - **Verification rounds.** keep the inputs; it checks round-1 gaps closed, the diff for regressions, and spot-checks per class; a new gap outside the diff is recorded as `round-1 coverage miss` and does not block, unless it is a BLOCKER: it goes to `## Carried gaps`.
  - **Stop.** cap = round 1 plus one verification round; delete the trend rule and "cap of 3 rounds"; a BLOCKER open after the verification round stops the flow and goes to the Dev; NOTE/NITS recorded as today.
  - Add the `## Carried gaps` table (exact header) below `## Review record`, naming which rows go in: `execute-verifiable` gaps from any round, and round-2 SUGGESTED gaps outside the diff.
  - Gate sentence: keep "GATE 1 is offered only after A1 comes back clean" (pinned by `test_dev_design_dispatches_an_independent_reviewer_before_gate_one`) and define clean as: no BLOCKER is open and every open SUGGESTED gap is in `## Carried gaps` with a target task. In a design the target task reads `plan` until the plan names one.
  - dev-plan only: the plan author's inputs add the design's `## Carried gaps`; it names a target task for each and copies each row into the plan's `## Carried gaps`; its self-check verifies every row has a task number.
  - Auto mode: the GATE bullet states the two-round rule (keep the substring "at most 2", pinned by `test_dev_phases_decide_review_gates_with_two_fix_rounds`); delete the "Stop rule: … trend" bullet; rewrite the "round 3 stops the flow" bullet to the two-round rule; a BLOCKER after round 2 ends `AUTO-RESULT: failed design-review` / `failed plan-review`.
  - Remove `"hand the Dev the trend"` from `_DEV_GATES["bodies/dev-design.md"]` and `_DEV_GATES["bodies/dev-plan.md"]`.

- [ ] **Step 4: Canon refresh** for `A1` (from `claude-skill-dev-design.md`) and `A2` (from `claude-skill-dev-plan.md`), then **Fixture refresh**.
- [ ] **Step 5: Run** `uv run pytest tests/test_templates.py tests/test_template_bodies.py -q` — Expected: PASS.
- [ ] **Step 6: Commit** `git commit -m "feat(dev-design,dev-plan): A1/A2 stop after two rounds; leftover gaps carried"`

---

### Task 5: Execute checks carried gaps and writes deviations back

**Files:**
- Modify: `bodies/dev-execute.md` (Steps: implementer dispatch, step 6 A3, step 7 tick, lanes bullets ~85-115, Auto bullets) and `claude-command-dev-execute.md`
- Modify: `bodies/dev-handover.md` and `claude-command-dev-handover.md` (PR `## Notes` content)
- Test: `tests/test_template_bodies.py`, fixtures; `tests/test_templates.py` A4 canon only if the A4 block text moves (it should not)

**Interfaces:**
- Consumes: plan `## Carried gaps` (Task 4).
- Produces: `## Execution deviations` table in `plan.md`; carried rows set to `closed task <n>`.

- [ ] **Step 1: Write the failing tests**

```python
@pytest.mark.parametrize("name", ["bodies/dev-execute.md", "claude-command-dev-execute.md"])
def test_execute_carries_gaps_and_writes_deviations_back(name):
    t = _normal(_raw(name))
    for needle in (
        "the `## Carried gaps` rows that name this task",
        "`closed task <n>`",
        "in the same task commit",
        "`## Execution deviations`",
        "| Task | Doc + section | What changed | Why |",
        "the plan/design text matches the code of this task",
        "changes the meaning of an AC or a public contract or interface",
        "one delta review",
        "the doc diff of that commit only",
        "applies them to `plan.md` and `design.md` at merge-back, before A3",
    ):
        assert needle in t, (name, needle)

@pytest.mark.parametrize("name", ["bodies/dev-handover.md", "claude-command-dev-handover.md"])
def test_handover_lists_open_carried_gaps_in_pr_notes(name):
    t = _normal(_raw(name))
    assert "open `## Carried gaps` row" in t and "`## Notes`" in t
```

- [ ] **Step 2: Run** `uv run pytest tests/test_template_bodies.py -k "carries_gaps or carried_gaps" -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per spec section 3 and 4:
  - implementer dispatch: also hand it the `## Carried gaps` rows that name this task;
  - implementer rule: when the code differs from its task or a design section, edit that text in the same task commit and add an `## Execution deviations` row (exact header; create the heading in `plan.md` on first row);
  - A3 spec-compliance verdict adds: each carried row of the task is resolved, and the plan/design text matches the code of this task with every difference in a deviation row; a miss is SUGGESTED, fixed in A3's own rounds;
  - step 7: on tick, set each resolved carried row's `Status` to `closed task <n>`;
  - lanes: the lane implementer writes deviation rows and doc edits into its task report; the orchestrator applies them to `plan.md` and `design.md` at merge-back, before A3;
  - delta review: a deviation that changes the meaning of an AC or a public contract or interface gets one delta review — a fresh `design-reviewer` or `plan-reviewer` on the doc diff of that commit only, one round; BLOCKER → Dev, SUGGESTED → carried gap; a changed AC meaning still takes the existing "AC not implementable as written" route to the BA;
  - Auto mode: one bullet: delta-review BLOCKER → `AUTO-RESULT: failed design-review` or `failed plan-review`, open classes in the reply (add its off-path fragment to `_DEV_GATES["bodies/dev-execute.md"]` only if the fragment is a human gate, i.e. "goes to the Dev");
  - `dev-handover`: every open `## Carried gaps` row of the plan is listed in the PR's `## Notes`.
- [ ] **Step 4: Fixture refresh**.
- [ ] **Step 5: Run** `uv run pytest tests/test_templates.py tests/test_template_bodies.py -q` — Expected: PASS.
- [ ] **Step 6: Commit** `git commit -m "feat(dev-execute): carried gaps per task; deviations written back to plan/design"`

---

### Task 6: Q&A question and answer format in the skills

**Files:**
- Modify (asker side, the `kb_question_ask` instructions): `bodies/dev-design.md` and `bodies/dev-plan.md` (the **business** bullet), `bodies/dev-implement-ticket.md` and `bodies/dev-fix-bug.md` ("A real blocker is a BA question" paragraph), and their full copies `claude-command-dev-design.md`, `claude-command-dev-plan.md`, `claude-skill-dev-implement-ticket.md`, `claude-command-dev-implement-ticket.md`
- Modify (answer side): `bodies/ba-answer-questions.md` (steps that show questions to the BA, and step 4 **Record**)
- Test: `tests/test_template_bodies.py`, fixtures

**Interfaces:**
- Consumes: the label lists in Global Constraints.

- [ ] **Step 1: Write the failing tests**

```python
QA_Q_LABELS = ("**Decision needed:**", "**Background:**", "**Options:**",
               "**Dev recommends:**", "**AC impact:**")
QA_A_LABELS = ("**Decision:**", "**Ticket changes (rev N):**", "**Follow-ups:**", "**Assumptions:**")

@pytest.mark.parametrize("name", ["bodies/dev-design.md", "bodies/dev-plan.md",
    "bodies/dev-implement-ticket.md", "bodies/dev-fix-bug.md", "claude-command-dev-design.md",
    "claude-command-dev-plan.md", "claude-skill-dev-implement-ticket.md",
    "claude-command-dev-implement-ticket.md"])
def test_asker_skills_state_the_question_format(name):
    t = _raw(name)
    for label in QA_Q_LABELS:
        assert label in t, (name, label)
    n = _normal(t)
    assert "one decision per question" in n
    assert "a place a reader can open" in n

def test_ba_answer_questions_formats_answers_and_restates_old_questions():
    t = _raw("bodies/ba-answer-questions.md")
    for label in QA_A_LABELS:
        assert label in t, label
    n = _normal(t)
    assert "in chat only" in n and "never edited" in n
    assert "the BA's own words go in **Decision**" in n
```

- [ ] **Step 2: Run** `uv run pytest tests/test_template_bodies.py -k "question_format or formats_answers" -q` — Expected: FAIL.
- [ ] **Step 3: Implement** per spec 5b-5d: the `question` template block (5b) and its three rules (one decision per question, no unexplained internal id, `context` names a place a reader can open such as `design.md §9.3 — test T4`); in `ba-answer-questions` the answer template (5c), "the BA's own words go in **Decision**", and 5d: an open question not in the 5b format is restated in that format in chat only; the stored question is never edited. Keep `"never answer a question yourself"` and the other `_BA_GATES` fragments intact.
- [ ] **Step 4: Fixture refresh**.
- [ ] **Step 5: Run** `uv run pytest tests/test_template_bodies.py tests/test_templates.py tests/test_mcp_qa.py -q` — Expected: PASS.
- [ ] **Step 6: Commit** `git commit -m "feat(templates): structured Q&A question and answer format"`

---

### Task 7: Guides, PDFs, changelog, version

**Files:**
- Modify: `docs/src/guide-dev.en.md` (§ around line 360-380: the "at most 3 fix/review passes" and trend text for A1/A2; add carried gaps, execution deviations, Q&A format) and `docs/src/guide-dev.vi.md` (same, ~lines 345-385)
- Modify: `docs/src/guide-ba.en.md` / `guide-ba.vi.md` only where they describe answering hub Q&A (add the answer format, one paragraph)
- Rebuild: `docs/strata-guide-dev.{en,vi}.pdf`, `docs/strata-guide-ba.{en,vi}.pdf`
- Modify: `CHANGELOG.md` (new `## 1.34.0 — <date>` at top), `pyproject.toml` `version = "1.34.0"`, `uv.lock` if it pins the project version
- Test: `tests/test_readme.py` and any version test

- [ ] **Step 1: Edit guides.** A3/A4/A5 keep "at most 3"; A1/A2 text says round 1 plus one verification round, carried gaps, back-update during execute; Q&A format with the label lists.
- [ ] **Step 2: Rebuild PDFs** — Run: `uv run python docs/src/build_pdf.py guide-dev.en guide-dev.vi guide-ba.en guide-ba.vi` (check `--help`/usage line for exact names). Expected: the four PDFs change, no error.
- [ ] **Step 3: CHANGELOG + version.** One-line intent, then bullets: two-round A1/A2, carried gaps, execution deviations + delta review, rendered Q&A, Q&A format. Note: run `kb init` to get the new skills.
- [ ] **Step 4: Run the full suite** — `uv run pytest -q` and the repo gate `bash scripts/gate.sh` (if it needs network or Docker and cannot run here, say so). Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "docs: guides and changelog for 1.34.0"`
