# Shared Template Round Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land six deferred skill-text items (A4, B4, C2, C3, C4, C5) across the 8 BA wrappers and 20 dev-workflow wrappers in one round, so the four-dialect cost and the canon bump are paid once.

**Architecture:** Every change is text inside `src/center_kb/templates/init/`, plus assertions in `tests/test_templates.py`. No Python source, no CLI, no MCP tool, no schema, no new scaffold file. Task 1 rewrites the one SHARED-* block C5 still touches — the freshness block, byte-identical across 20 dev wrappers — and regenerates its canon entry; Tasks 2–6 edit wrapper-specific prose, which differs per dialect; Task 7 verifies the whole suite and ticks the roadmap.

**Tech Stack:** Markdown templates, Python 3.13, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-shared-template-round-design.md`

## Global Constraints

- **Test runner:** `.venv/Scripts/pytest.exe` from the repo root (Windows; the venv is uv-managed, no pip). Baseline before this plan: `tests/test_templates.py` = **99 passed in 0.64s**.
- **Full suite takes 10–19 minutes.** Run targeted files during tasks; run the whole suite exactly once, in Task 7.
- **The four dialects are not interchangeable.** `claude-skill-*` = full numbered procedure; `claude-command-*` = compressed prose (and `claude-command-ba-ticket-author.md` is the shortest of all — it has no Ground step, no Pin command, no maturity-review detail); `copilot-*.prompt.md` and `cursor-*.md` = full procedure with their own frontmatter, and their BA maturity step says "TWO sequential review passes yourself" where the skill wrapper says "TWO review subagents IN PARALLEL". Never paste a sentence across dialects without re-reading the surrounding prose — **except** the three SHARED-* blocks, which MUST stay byte-identical.
- **Wrap prose at ~72 columns**, matching each file. Needle tests match `_normalised` text, so wrapping is free.
- **Never touch** `SHARED-NEXT-STEP`, the four `dev-code-seed` wrappers, `QUICKSTART-ba.md:182` (already correct), `mcp.py`, or any MCP docstring — the golden `mcp_tools.json` must stay byte-identical.
- **`kb query "<text>" --tags <tags>` stays.** That flag filters a search. Only `kb context new --tags` and the `kb_context_new` `tags` argument are being retired from the skill text.
- Add tests to the END of `tests/test_templates.py`, reusing the existing helpers `_read_init_template`, `_normalised`, `_dev_wrapper_names`, `_dev_wrapper_body`, `BA_WRAPPERS` (line 1074), and `_ba_wrapper_text` (line 1087). Do not redefine them.
- Branch: `feat/shared-template-round`, created off `docs/template-round-spec` (which holds the spec commit).
- Conventional commit messages, one commit per task, with the footer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

### Task 1: C5 — shorter SHARED-FRESHNESS in all 20 dev wrappers

> **Scope note.** C5 as the roadmap wrote it also regrouped the 14 hard rules
> into 8. Measured against the canon on 2026-08-24, that saves 5% of the block
> (16% with the most aggressive rewording that still carries all 14
> constraints) — not worth a diff in which a rewritten rule and a deleted rule
> look the same. `SHARED-HARD-RULES` is therefore left byte-identical; see
> evidence 8 in the spec. This task changes ONE block.

**Files:**
- Modify (20): `src/center_kb/templates/init/{claude-skill,claude-command}-{dev-implement-ticket,dev-design,dev-plan,dev-execute,dev-handover}.md`, `src/center_kb/templates/init/copilot-{dev-implement-ticket,dev-design,dev-plan,dev-execute,dev-handover}.prompt.md`, `src/center_kb/templates/init/cursor-{dev-implement-ticket,dev-design,dev-plan,dev-execute,dev-handover}.md`
- Modify: `tests/test_templates.py:307` (`SHARED_BLOCK_TEXT['SHARED-FRESHNESS']` only)

**Interfaces:**
- Consumes: nothing.
- Produces: the new freshness text that every later task's edits must not disturb. Later tasks edit wrapper-specific prose only. Both boundary lines are unchanged — `## Freshness re-check (run this FIRST, every time)` and `- **ok** → continue.` — so `SHARED_BLOCKS` (line 286) needs no edit at all.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
# --- C5: a shorter freshness block, the hard rules left alone ---------------


def test_shared_freshness_keeps_the_kb_diff_trap_and_the_three_verdicts():
    block = _normalised(SHARED_BLOCK_TEXT["SHARED-FRESHNESS"])
    for needle in ("**broken**", "**stale**", "**ok**", "kb diff", "kb_resolve",
                   "re-pin", "--level l3"):
        assert needle in block, needle


def test_shared_freshness_shed_a_third_of_its_length():
    # 952 characters before the round, 598 after the rewrite. The ceiling
    # leaves room for a later clarifying sentence and still fails on a
    # silent re-expansion back to the old explanatory paragraph.
    assert len(SHARED_BLOCK_TEXT["SHARED-FRESHNESS"]) <= 660


def test_shared_hard_rules_were_not_touched_by_the_c5_round():
    """C5 shrinks the freshness block only.

    Measured 2026-08-24: regrouping the 14 hard rules into 8 saves 5% of
    the block, 16% under the most aggressive rewording that still carries
    all 14 constraints. Both are too little to justify a diff in which a
    rewritten rule and a deleted rule look identical. This test pins the
    decision: the block's length and bullet count stay where they are, so
    a later "tidy-up" has to argue with the numbers first.
    """
    block = SHARED_BLOCK_TEXT["SHARED-HARD-RULES"]
    bullets = [line for line in block.splitlines() if line.startswith("- ")]
    assert len(bullets) == 14, len(bullets)
    assert len(block) == 1531, len(block)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -k "shared_freshness or hard_rules_were_not_touched" -q`

Expected: FAIL — `test_shared_freshness_shed_a_third_of_its_length` reports `952 <= 660` false. The other two pass already, and must stay green: one guards what the trimmed block still has to say, the other guards the hard rules against being trimmed at all.

- [ ] **Step 3: Write the rewriter to a scratch file**

Create `C:/Users/VuongLQ4/AppData/Local/Temp/claude/C--Users-VuongLQ4-OneDrive---FPT-Corporation-Documents-SIA-Champion-CENTER-KB/69be3358-ac35-49e2-bf02-f867ac942ed6/scratchpad/c5_freshness.py` (scratchpad only — never committed):

```python
"""One-shot rewriter for the shrunk SHARED-FRESHNESS block.

Byte-identity across 20 files is produced by writing the same string 20
times, not by 20 hand edits. Run from the repo root.
"""
from pathlib import Path

BASE = Path("src/center_kb/templates/init")

SKILLS = (
    "dev-implement-ticket", "dev-design", "dev-plan", "dev-execute", "dev-handover",
)


def wrappers() -> list[Path]:
    out = []
    for skill in SKILLS:
        out += [
            BASE / f"claude-skill-{skill}.md",
            BASE / f"claude-command-{skill}.md",
            BASE / f"copilot-{skill}.prompt.md",
            BASE / f"cursor-{skill}.md",
        ]
    return out


OLD_FRESHNESS = """## Freshness re-check (run this FIRST, every time)

Before anything else, re-resolve the ticket's `kb-context`: call the MCP tool
`kb_resolve` when available, otherwise `kb resolve <ticket-file>` (or
`kb resolve - < ticket.md`). The hub may have published since the last session,
so a ref that was `ok` yesterday can be `stale` today — checking only at
handover is too late, because the plan may already rest on changed content.

- **broken** → STOP. This is a blocker: report to the BA that the ticket needs
  re-pinning. Never implement around a citation that no longer resolves.
- **stale** → show BOTH versions and let the humans decide: `kb resolve` returns
  the pinned content plus the reason; `kb get <doc-id> <section> [--level l3]`
  returns the CURRENT hub version. Do NOT use `kb diff` — it compares the local
  `.kb/` worktree against a local git rev, and this repo holds no local copy of
  the cited domain document.
- **ok** → continue.
"""

NEW_FRESHNESS = """## Freshness re-check (run this FIRST, every time)

Re-resolve the ticket's `kb-context` first: `kb_resolve`, else
`kb resolve <ticket-file>`. The hub may have published since last session.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a
  citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: `kb resolve` gives the pinned
  content and the reason, `kb get <doc-id> <section> [--level l3]` the current
  hub version. NOT `kb diff` — it compares the local `.kb/` worktree to a local
  git rev, not this repo to the hub.
- **ok** → continue.
"""

def main() -> None:
    for path in wrappers():
        text = path.read_text(encoding="utf-8")
        assert text.count(OLD_FRESHNESS) == 1, f"{path}: freshness block not found once"
        text = text.replace(OLD_FRESHNESS, NEW_FRESHNESS)
        path.write_text(text, encoding="utf-8", newline="\n")
        print("rewrote", path.name)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the rewriter**

Run: `.venv/Scripts/python.exe "C:/Users/VuongLQ4/AppData/Local/Temp/claude/C--Users-VuongLQ4-OneDrive---FPT-Corporation-Documents-SIA-Champion-CENTER-KB/69be3358-ac35-49e2-bf02-f867ac942ed6/scratchpad/c5_freshness.py"`

Expected: 20 `rewrote …` lines and no assertion error. An assertion here means a wrapper's copy was not byte-identical before the round — stop and report, do not hand-patch.

- [ ] **Step 5: Regenerate the canon entry from a rewritten wrapper**

Never retype the canon (`tests/test_templates.py:303` says so). Write this to the scratchpad as `dump_canon.py` rather than passing it as a `-c` one-liner — the block contains `→` and `—`, and quoting those through the shell is how a canon gets corrupted:

```python
import pathlib

t = pathlib.Path(
    "src/center_kb/templates/init/claude-skill-dev-execute.md"
).read_text(encoding="utf-8")
end = "- **ok** \u2192 continue.\n"
block = t[t.index("## Freshness re-check") : t.index(end) + len(end)]
print(repr(block))
```

Run it and paste the single `repr()` output into `SHARED_BLOCK_TEXT` as the value for `'SHARED-FRESHNESS'`. Leave `'SHARED-HARD-RULES'` and `'SHARED-NEXT-STEP'` untouched, and leave `SHARED_BLOCKS` untouched — the freshness block's first and last lines did not change.

- [ ] **Step 6: Run the template tests**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -q`

Expected: all pass, including `test_dev_wrappers_carry_byte_identical_shared_blocks` and the three new C5 tests. If a pre-existing needle test now fails, read it: a needle that matched through the freshness block's cut prose (for instance the phrase "checking only at handover is too late") must be re-pointed or retired deliberately; a needle that matched real skill prose means the rewriter over-reached — restore it.

- [ ] **Step 7: Confirm the round changed one block and nothing else**

Run: `git diff --stat src/center_kb/templates/init/`

Expected: exactly 20 files changed, every file showing the same insertion and deletion counts (the same single block in each). A file with a different count means an extra edit slipped in.

Then: `git diff -U0 src/center_kb/templates/init/ | grep -c "^-.*Hard rules\|^-.*violates DoD"`

Expected: `0` — the hard rules were not touched.

- [ ] **Step 8: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
git commit -m "refactor(templates): cut the dev freshness block by a third"
```

---

### Task 2: C3 — a task's implementer sees only its own task

**Files:**
- Modify: `src/center_kb/templates/init/claude-skill-dev-execute.md:44-45`
- Modify: `src/center_kb/templates/init/copilot-dev-execute.prompt.md:44-45`
- Modify: `src/center_kb/templates/init/cursor-dev-execute.md:44-45`
- Modify: `src/center_kb/templates/init/claude-command-dev-execute.md:39-40`
- Modify: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: Task 1's rewritten blocks (do not re-edit them).
- Produces: the literal needles `task block` and `the plan is incomplete` in all four `dev-execute` wrappers, outside the SHARED-* blocks.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
# --- C3: the per-task subagent gets its task, not the whole plan ------------


def test_dev_execute_hands_the_subagent_only_its_own_task():
    for name in _dev_wrapper_names("dev-execute"):
        text = _dev_wrapper_body(name)
        assert "task block" in text, name
        assert "Interfaces" in text, name
        assert "the plan is incomplete" in text, name
        assert "dev-plan" in text, name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py::test_dev_execute_hands_the_subagent_only_its_own_task -q`

Expected: FAIL on `claude-skill-dev-execute.md` at `assert "task block" in text`.

- [ ] **Step 3: Edit the three full-procedure wrappers**

In `claude-skill-dev-execute.md`, `copilot-dev-execute.prompt.md`, and `cursor-dev-execute.md`, replace:

```markdown
- **Per unticked task**, in its own subagent where the runtime supports
  it (sequential passes otherwise):
```

with:

```markdown
- **Per unticked task**, in its own subagent where the runtime supports
  it (sequential passes otherwise). Hand that subagent exactly three
  things: its own task block from the plan, the **Interfaces** entry of
  that task, and the `cmd.test` / `cmd.lint` commands — not the rest of
  the plan, and not the ticket. If the task block does not carry
  something the implementer needs, the plan is incomplete: stop and send
  it back to `dev-plan`. Never read wider to paper over a gap in the
  plan.
```

The numbered sub-steps 1–5 that follow are unchanged.

- [ ] **Step 4: Edit the compressed command wrapper**

In `claude-command-dev-execute.md`, the same instruction is prose. Replace:

```markdown
passes otherwise): write the test, run it, and observe it fail — a test
```

with:

```markdown
passes otherwise), handed exactly its own task block from the plan, that
task's **Interfaces** entry, and the `cmd.test` / `cmd.lint` commands —
not the rest of the plan and not the ticket; when the task block does
not carry something the implementer needs, the plan is incomplete, so
stop and send it back to `dev-plan` rather than reading wider: write the
test, run it, and observe it fail — a test
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
git commit -m "feat(templates): dev-execute subagents receive only their own task block"
```

---

### Task 3: C4 — the search budget is a number

**Files:**
- Modify (8 BA): `claude-skill-ba-ticket-author.md:31`, `claude-command-ba-ticket-author.md:18`, `copilot-ba-ticket-author.prompt.md:27`, `cursor-ba-ticket-author.md:27`, `claude-skill-ba-mission-plan.md:27`, `claude-command-ba-mission-plan.md:21`, `copilot-ba-mission-plan.prompt.md:24`, `cursor-ba-mission-plan.md:24` (all under `src/center_kb/templates/init/`)
- Modify (4 dev): `claude-skill-dev-implement-ticket.md:46`, `claude-command-dev-implement-ticket.md:40`, `copilot-dev-implement-ticket.prompt.md:46`, `cursor-dev-implement-ticket.md:46`
- Modify: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the literals `500` and `800` in all 12 wrappers; the phrase `within the token budget` removed everywhere.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
# --- C4: search budget discipline ------------------------------------------

SEARCH_BUDGET_WRAPPERS = BA_WRAPPERS + _dev_wrapper_names("dev-implement-ticket")


def test_search_budget_is_a_number_not_a_gesture():
    for name in SEARCH_BUDGET_WRAPPERS:
        text = _normalised(_read_init_template(name))
        assert "500" in text, name
        assert "800" in text, name
        assert "within the token budget" not in text, name


def test_search_budget_names_what_the_budget_buys():
    for name in SEARCH_BUDGET_WRAPPERS:
        text = _normalised(_read_init_template(name))
        assert "kb_get_section" in text, name
        assert "encoded in code" in text, name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -k search_budget -q`

Expected: FAIL on `claude-skill-ba-ticket-author.md` at `assert "500" in text`.

- [ ] **Step 3: Edit the two `ba-ticket-author` full wrappers**

In `claude-skill-ba-ticket-author.md`, replace:

```markdown
3. **Ground** — call the MCP tool `kb_search` within the token budget
   when it is available; otherwise fall back to `kb query "<text>"
   --tags <tags>` (CLI). Present **ALL** returned candidates to the BA
```

with:

```markdown
3. **Ground** — call the MCP tool `kb_search` when it is available;
   otherwise fall back to `kb query "<text>" --tags <tags>` (CLI).
   **Budget the search:** 500–800 tokens for broad discovery — enough
   for the citation plus a summary to choose from; `kb_get_section`
   only for a section already chosen; L3 only for a value that will be
   encoded in code or a test. Present **ALL** returned candidates to the BA
```

In `copilot-ba-ticket-author.prompt.md` and `cursor-ba-ticket-author.md`, replace:

```markdown
3. **Ground** — use the MCP tool `kb_search` when it is available;
   otherwise fall back to `kb query "<text>" --tags <tags>` (CLI). Present
```

with:

```markdown
3. **Ground** — use the MCP tool `kb_search` when it is available;
   otherwise fall back to `kb query "<text>" --tags <tags>` (CLI).
   **Budget the search:** 500–800 tokens for broad discovery — enough
   for the citation plus a summary to choose from; `kb_get_section`
   only for a section already chosen; L3 only for a value that will be
   encoded in code or a test. Present
```

- [ ] **Step 4: Edit the three `ba-mission-plan` full wrappers**

In `claude-skill-ba-mission-plan.md`, `copilot-ba-mission-plan.prompt.md`, and `cursor-ba-mission-plan.md`, replace:

```markdown
2. **Ground** — use the MCP tool `kb_search`, within the token budget,
   when it is available; otherwise fall back to `kb query "<text>"
   --tags <tags>` (CLI). Present **ALL** returned candidates with their
```

with:

```markdown
2. **Ground** — use the MCP tool `kb_search` when it is available;
   otherwise fall back to `kb query "<text>" --tags <tags>` (CLI).
   **Budget the search:** 500–800 tokens for broad discovery — enough
   for the citation plus a summary to choose from; `kb_get_section`
   only for a section already chosen; L3 only for a value that will be
   encoded in code or a test. Present **ALL** returned candidates with their
```

`claude-command-ba-mission-plan.md` carries the same three lines at 21–23; apply the identical replacement there.

- [ ] **Step 5: Edit `claude-command-ba-ticket-author.md`**

This wrapper has no Ground step — the rules live in one compressed sentence. Replace:

```markdown
for standard claims; present ALL `kb_search` candidates and let the BA
choose — mandatory when the ambiguity note fires, never auto-pick; pin
```

with:

```markdown
for standard claims; budget `kb_search` at 500–800 tokens for broad
discovery, call `kb_get_section` only for a section already chosen, and
escalate to L3 only for a value that will be encoded in code or a test;
present ALL `kb_search` candidates and let the BA
choose — mandatory when the ambiguity note fires, never auto-pick; pin
```

- [ ] **Step 6: Edit the four `dev-implement-ticket` wrappers**

These already carry the L3 half. In `claude-skill-dev-implement-ticket.md`, replace:

```markdown
- **Ground** — read resolved L2; escalate to L3 via `kb_get_section … l3`
  (or `kb get <doc> <section> --level l3`) for any value that will be
  encoded in code or tests; then `kb_search` both own-repo documents —
```

with:

```markdown
- **Ground** — read resolved L2; escalate to L3 via `kb_get_section … l3`
  (or `kb get <doc> <section> --level l3`) only for a value that will be
  encoded in code or tests, and call `kb_get_section` only for a section
  already chosen; then `kb_search` both own-repo documents, budgeted at
  500–800 tokens for broad discovery —
```

In `copilot-dev-implement-ticket.prompt.md` and `cursor-dev-implement-ticket.md`, replace:

```markdown
- **Ground** — read resolved L2; escalate to L3 via
  `kb get <doc> <section> --level l3` (or the `kb_get_section` MCP tool
  when your client exposes it) for any value that will be encoded in code
  or tests; then `kb query` both own-repo documents — `<repo_id>-code` for
```

with:

```markdown
- **Ground** — read resolved L2; escalate to L3 via
  `kb get <doc> <section> --level l3` (or the `kb_get_section` MCP tool
  when your client exposes it) only for a value that will be encoded in
  code or tests, and only for a section already chosen; then `kb query`
  both own-repo documents, budgeted at 500–800 tokens for broad
  discovery — `<repo_id>-code` for
```

In `claude-command-dev-implement-ticket.md`, replace:

```markdown
Freshness re-check above; **Ground** reads resolved L2, escalating to L3
for any value that will be encoded in code or tests, then searches
```

with:

```markdown
Freshness re-check above; **Ground** reads resolved L2, calling
`kb_get_section` only for a section already chosen and escalating to L3
only for a value that will be encoded in code or tests, then searches
within a 500–800 token budget for broad discovery
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -q`

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
git commit -m "feat(templates): give kb_search a 500-800 token budget instead of a gesture"
```

---

### Task 4: B4 — every handover reports its cost

**Files:**
- Modify (4 dev): `claude-skill-dev-handover.md:53`, `copilot-dev-handover.prompt.md:53`, `cursor-dev-handover.md:53`, `claude-command-dev-handover.md:47`
- Modify (4 BA): `claude-skill-ba-ticket-author.md:101-104`, `copilot-ba-ticket-author.prompt.md:90-94`, `cursor-ba-ticket-author.md` (same paragraph), `claude-command-ba-ticket-author.md:22`
- Modify: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: the literal `kb usage report` in the 4 `dev-handover` wrapper bodies and the 4 `ba-ticket-author` wrappers.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
# --- B4: the handover carries the ticket's measured cost --------------------
#
# The four ba-ticket-author wrappers are already enumerated at the top of
# this file as BA_TICKET_AUTHOR_TEMPLATES (line 14) — reuse it rather than
# spelling the names a second time.


def test_dev_handover_reports_usage_in_the_pr():
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "kb usage report" in text, name
        assert "## Usage" in text, name
        # An empty ledger is a finding, not a reason to drop the section.
        assert "no usage recorded yet" in text, name


def test_ba_ticket_author_reports_usage_at_handover():
    for name in BA_TICKET_AUTHOR_TEMPLATES:
        text = _ba_wrapper_text(name)
        assert "kb usage report" in text, name
        # The BA repo's ledger is only half the ticket's lifetime cost.
        assert "authoring" in text, name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -k "reports_usage" -q`

Expected: FAIL on `claude-skill-dev-handover.md` at `assert "kb usage report" in text`.

- [ ] **Step 3: Edit the three full `dev-handover` wrappers**

In `claude-skill-dev-handover.md`, `copilot-dev-handover.prompt.md`, and `cursor-dev-handover.md`, insert this bullet immediately AFTER the `- **Assemble the PR description**, …` bullet and BEFORE `- **Amend findings** …`:

```markdown
- **Report the cost** — run `kb usage report --ticket <id> --md`
  and paste the table into the PR under a `## Usage` heading, so
  the PR carries the ticket's own token cost. When the command
  answers `no usage recorded yet` instead of a table, keep the
  heading and say in one line that the ledger is empty for this
  ticket and why — the `Stop` hook is not wired, or no transcript
  has been ingested. An empty measurement is a finding, not a
  reason to drop the section.
```

- [ ] **Step 4: Edit `claude-command-dev-handover.md`**

Replace:

```markdown
contradiction found as a concrete feedback item (issue or PR on
the owning child repo / hub); if the ticket changed what a service
```

with:

```markdown
contradiction found as a concrete feedback item (issue or PR on
the owning child repo / hub); run `kb usage report --ticket <id>
--md` and paste the table into the PR under a `## Usage` heading,
keeping the heading with a one-line reason when the command
answers `no usage recorded yet` instead of a table; if the ticket
changed what a service
```

- [ ] **Step 5: Edit the three full `ba-ticket-author` wrappers**

In `claude-skill-ba-ticket-author.md`, `copilot-ba-ticket-author.prompt.md`, and `cursor-ba-ticket-author.md`, the maturity-review step ends with `Report both scores and the remaining owned gaps to the BA in the handover summary.` Replace that sentence with:

```markdown
   Report both scores and the remaining owned gaps to the BA in the
   handover summary, together with the output of `kb usage report
   --ticket <ticket-id> --md` — the authoring cost of this ticket in
   this repo. Say so in the same breath: the Dev repo's ledger holds
   the implementation half, and the two are joined by the shared
   ticket id. When the command answers `no usage recorded yet`, report
   that instead of guessing a number.
```

- [ ] **Step 6: Edit `claude-command-ba-ticket-author.md`**

Replace:

```markdown
never invented; `kb ticket lint` must report `DoR: PASS` before handover;
```

with:

```markdown
never invented; `kb ticket lint` must report `DoR: PASS` before handover;
report the authoring cost at handover with `kb usage report --ticket
<ticket-id> --md`, reporting `no usage recorded yet` as-is rather than
guessing a number;
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -q`

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
git commit -m "feat(templates): dev-handover and ba-ticket-author report measured token cost"
```

---

### Task 5: A4 — tags are derived, never authored

**Files:**
- Modify (8 BA wrappers under `src/center_kb/templates/init/`): the Pin step of `claude-skill-ba-ticket-author.md:73-75`, `copilot-ba-ticket-author.prompt.md:66-68`, `cursor-ba-ticket-author.md:66-68`, `claude-skill-ba-mission-plan.md:86-88`, `claude-command-ba-mission-plan.md:80-82`, `copilot-ba-mission-plan.prompt.md:83-85`, `cursor-ba-mission-plan.md:83-85`; and the compressed rules line of `claude-command-ba-ticket-author.md:20`
- Modify: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: Task 3's edits to the same files' Ground steps (different paragraphs — no overlap).
- Produces: the literal sentence `Tags are NOT yours to set` in all 8 BA wrappers; `--tags "<tags>"` gone from all of them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
# --- A4: kb-context tags are derived by the engine, never authored ----------


def test_ba_wrappers_never_pass_tags_to_kb_context_new():
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert 'kb context new --refs "<refs>" --tags' not in text, name
        assert "(+ tags)" not in text, name


def test_ba_wrappers_say_who_owns_the_tags():
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "Tags are NOT yours to set" in text, name
        assert "hub vocabulary" in text, name


def test_ba_wrappers_keep_tags_as_a_search_filter():
    """`kb query --tags` filters a search; only the pin path lost tags."""
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "kb query" in text, name
        assert "--tags" in text, name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -k "tags" -q`

Expected: FAIL — `test_ba_wrappers_never_pass_tags_to_kb_context_new` on `claude-skill-ba-ticket-author.md`, and `test_ba_wrappers_say_who_owns_the_tags` on all eight.

- [ ] **Step 3: Edit the `ba-ticket-author` Pin step**

In `claude-skill-ba-ticket-author.md`, replace:

```markdown
   `kb context new --refs "<refs>" --tags "<tags>"` (CLI), passing
   exactly those confirmed refs (+ tags). Embed the block it returns
   verbatim under `## KB context`.
```

with:

```markdown
   `kb context new --refs "<refs>"` (CLI), passing exactly those
   confirmed refs. Embed the block it returns verbatim under
   `## KB context`. **Tags are NOT yours to set:** the engine derives
   them from the pinned sections' own tags. Leave the tool's `tags`
   argument unset and the CLI's `--tags` off — a tag passed by hand is
   validated against the hub vocabulary and an unknown one is an error.
   The tags the BA gave at Intake are search keywords for
   `kb query --tags`, nothing more.
```

In `copilot-ba-ticket-author.prompt.md` and `cursor-ba-ticket-author.md`, replace:

```markdown
   `kb context new --refs "<refs>" --tags "<tags>"` (CLI), passing exactly
   the confirmed refs. Embed the returned block verbatim under
   `## KB context`.
```

with:

```markdown
   `kb context new --refs "<refs>"` (CLI), passing exactly the confirmed
   refs. Embed the returned block verbatim under `## KB context`.
   **Tags are NOT yours to set:** the engine derives them from the
   pinned sections' own tags. Leave the tool's `tags` argument unset and
   the CLI's `--tags` off — a tag passed by hand is validated against the
   hub vocabulary and an unknown one is an error. The tags the BA gave at
   Intake are search keywords for `kb query --tags`, nothing more.
```

- [ ] **Step 4: Edit the four `ba-mission-plan` Pin steps**

In `claude-skill-ba-mission-plan.md`, `claude-command-ba-mission-plan.md`, `copilot-ba-mission-plan.prompt.md`, and `cursor-ba-mission-plan.md`, replace:

```markdown
   `kb context new --refs "<refs>" --tags "<tags>"` (CLI), passing exactly
   those confirmed refs (+ tags). Embed the block it returns verbatim
   under `## KB context`.
```

with:

```markdown
   `kb context new --refs "<refs>"` (CLI), passing exactly those
   confirmed refs. Embed the block it returns verbatim under
   `## KB context`. **Tags are NOT yours to set:** the engine derives
   them from the pinned sections' own tags. Leave the tool's `tags`
   argument unset and the CLI's `--tags` off — a tag passed by hand is
   validated against the hub vocabulary and an unknown one is an error.
   The tags the BA gave at intake are search keywords for
   `kb query --tags`, nothing more.
```

- [ ] **Step 5: Edit `claude-command-ba-ticket-author.md`**

This wrapper never carried a Pin command. Replace:

```markdown
only BA-confirmed refs via `kb_context_new`;
```

with:

```markdown
only BA-confirmed refs via `kb_context_new` — **Tags are NOT yours to
set**: the engine derives them from the pinned sections' own tags, a tag
passed by hand is validated against the hub vocabulary and an unknown one
is an error, and the BA's intake tags are search keywords for
`kb query --tags`, nothing more;
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -q`

Expected: all pass.

- [ ] **Step 7: Verify the engine actually behaves as the text now claims**

Run: `.venv/Scripts/pytest.exe tests/test_kbcontext.py tests/test_ticketlint.py -q`

Expected: all pass. These are batch 1's tests for tag derivation and the lint tag check; the skill text is only correct while they are green.

- [ ] **Step 8: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
git commit -m "docs(templates): stop telling BA agents to author kb-context tags"
```

---

### Task 6: C2 — rounds 2–3 verify gaps instead of re-reading the draft

**Files:**
- Modify (7 BA wrappers under `src/center_kb/templates/init/`): the maturity-review round paragraph and the review-record paragraph of `claude-skill-ba-ticket-author.md:95-104`, `copilot-ba-ticket-author.prompt.md:85-94`, `cursor-ba-ticket-author.md` (same paragraph), `claude-skill-ba-mission-plan.md:110-119`, `claude-command-ba-mission-plan.md:103-112`, `copilot-ba-mission-plan.prompt.md` and `cursor-ba-mission-plan.md` (same paragraphs)
- Modify: `claude-command-ba-ticket-author.md:22` (compressed rules line)
- Modify: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: Task 4's edit to the same "Report both scores…" sentence in the three full `ba-ticket-author` wrappers — that sentence is now longer; match it as it stands after Task 4.
- Produces: the literal `gap-verifier` in all 8 BA wrappers.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
# --- C2: review rounds 2-3 verify gaps, they do not re-read the draft -------


def test_ba_wrappers_use_a_single_gap_verifier_for_rounds_two_and_three():
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "gap-verifier" in text, name


def test_ba_wrappers_keep_round_one_two_perspective():
    """C2 shrinks rounds 2-3 only; round 1 keeps both reviewers."""
    for name in BA_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "Business-coverage reviewer" in text, name
        assert "Dev-implementability reviewer" in text, name


def test_ba_wrappers_do_not_let_the_gap_verifier_invent_a_score():
    for name in ("claude-skill-ba-ticket-author.md", "claude-skill-ba-mission-plan.md",
                 "copilot-ba-ticket-author.prompt.md", "cursor-ba-ticket-author.md",
                 "copilot-ba-mission-plan.prompt.md", "cursor-ba-mission-plan.md",
                 "claude-command-ba-mission-plan.md"):
        text = _ba_wrapper_text(name)
        assert "does not score an axis" in text, name
        assert "carry the previous round's score forward" in text, name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -k "gap_verifier or round_one or invent_a_score" -q`

Expected: FAIL on the first wrapper at `assert "gap-verifier" in text`. `test_ba_wrappers_keep_round_one_two_perspective` passes already — it is the guard that round 1 survives.

- [ ] **Step 3: Edit the rounds paragraph in the three `ba-ticket-author` full wrappers**

In `claude-skill-ba-ticket-author.md`, `copilot-ba-ticket-author.prompt.md`, and `cursor-ba-ticket-author.md`, replace:

```markdown
   Apply the fixes, re-run `kb ticket lint`, and review again — at most
   3 rounds total; stop early when both axes score ≥ 4. A gap you
   cannot close yourself (a missing business decision, missing input)
   is NEVER invented: write `OPEN(<owner>)` at the spot and add an
   `## Open questions` row.
```

with:

```markdown
   Apply the fixes, re-run `kb ticket lint`, then review again — at most
   3 rounds total; stop early when both axes score ≥ 4.

   **Rounds 2 and 3 are not a re-read.** Run ONE `gap-verifier` pass
   that receives only three things: the gaps still open, the current
   text of the sections that changed in response, and the rubric items
   those gaps map to — never the whole draft. It returns pass/fail per
   gap with a one-line reason; it does not score an axis, having not
   read enough of the draft to score one. An axis's score rises only
   when every gap of that axis passes; otherwise carry the previous
   round's score forward unchanged.

   A gap you cannot close yourself (a missing business decision,
   missing input) is NEVER invented: write `OPEN(<owner>)` at the spot
   and add an `## Open questions` row.
```

Note the wrapper-specific line: `claude-skill-ba-ticket-author.md` says "review again" after two PARALLEL subagents, while the copilot/cursor forms ran two SEQUENTIAL passes. The replacement text above fits both, because it names what rounds 2–3 do, not how round 1 was dispatched. Leave each file's round-1 wording untouched.

- [ ] **Step 4: Edit the rounds paragraph in the four `ba-mission-plan` wrappers**

In `claude-skill-ba-mission-plan.md`, `claude-command-ba-mission-plan.md`, `copilot-ba-mission-plan.prompt.md`, and `cursor-ba-mission-plan.md`, replace:

```markdown
   Apply the fixes, re-run `kb mission lint`, and review again — at
   most 3 rounds total; stop early when both axes score ≥ 4. A gap you
   cannot close yourself (a missing business decision, missing input)
   is NEVER invented: write `OPEN(<owner>)` at the spot and add an
   `## Open questions` row.
```

with:

```markdown
   Apply the fixes, re-run `kb mission lint`, then review again — at
   most 3 rounds total; stop early when both axes score ≥ 4.

   **Rounds 2 and 3 are not a re-read.** Run ONE `gap-verifier` pass
   that receives only three things: the gaps still open, the current
   text of the sections that changed in response, and the rubric items
   those gaps map to — never the whole draft. It returns pass/fail per
   gap with a one-line reason; it does not score an axis, having not
   read enough of the draft to score one. An axis's score rises only
   when every gap of that axis passes; otherwise carry the previous
   round's score forward unchanged.

   A gap you cannot close yourself (a missing business decision,
   missing input) is NEVER invented: write `OPEN(<owner>)` at the spot
   and add an `## Open questions` row.
```

- [ ] **Step 5: Name the reviewer in the record paragraph (7 wrappers)**

In the same seven files, the record paragraph says:

```markdown
   (`| Date | Round | Business | Dev | Reviewer |`) and list the
```

Replace it with:

```markdown
   (`| Date | Round | Business | Dev | Reviewer |`) — the `Reviewer`
   cell reads `gap-verifier` for rounds 2 and 3 — and list the
```

- [ ] **Step 6: Edit `claude-command-ba-ticket-author.md`**

Replace:

```markdown
never push to Jira — the BA publishes; never tick a Definition of Ready
```

with:

```markdown
review rounds 2 and 3 are a single `gap-verifier` pass over the still-open
gaps and the sections that changed, never a re-read of the whole draft;
never push to Jira — the BA publishes; never tick a Definition of Ready
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv/Scripts/pytest.exe tests/test_templates.py -q`

Expected: all pass.

- [ ] **Step 8: Check the lint contract still holds**

Run: `.venv/Scripts/pytest.exe tests/test_ticketlint.py tests/test_missionlint.py -q`

Expected: all pass. `check_review_record` only inspects the placeholder, so a changed `Reviewer` cell must not move it.

- [ ] **Step 9: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
git commit -m "feat(templates): review rounds 2-3 verify gaps instead of re-reading the draft"
```

---

### Task 7: Whole-suite verification, roadmap tick, version bump

**Files:**
- Modify: `docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md` (tick A4, B4, C2, C3, C4, C5; add the batch-3 result note)
- Modify: `pyproject.toml:3`

**Interfaces:**
- Consumes: every earlier task.
- Produces: nothing code-facing.

- [ ] **Step 1: Run the whole suite**

Run: `.venv/Scripts/pytest.exe -q`

Expected: all pass. This takes 10–19 minutes and is the only full run in the plan. Paste the final summary line into the task report — a completion claim without it is not accepted.

- [ ] **Step 2: Verify the scaffold still writes what `kb init` promises**

Run: `.venv/Scripts/pytest.exe tests/test_init.py tests/test_check_package.py -q`

Expected: all pass with no change to the pinned scaffold-file count — this round added no file.

- [ ] **Step 3: Confirm the MCP golden is untouched**

Run: `git diff --stat main -- src/center_kb/mcp.py tests/`

Expected: `src/center_kb/mcp.py` absent from the output; the only test file listed is `tests/test_templates.py`. Anything else means a tool docstring moved and the golden is at risk.

- [ ] **Step 4: Tick the roadmap**

In `docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md`, change `- [ ]` to `- [x]` for **A4**, **B4**, **C2**, **C3**, **C4**, and **C5**, and add this note directly under the "ĐỢT TEMPLATE CHUNG" heading (Vietnamese, matching the file's language):

```markdown
> **Đợt 3 xong 2026-08-24.** Gồm A4 + B4 + C2 + C3 + C4 **+ C5 một phần**.
> Lệch so với mô tả, đều do đo được chứ không do đổi ý:
>
> - **C5 chỉ làm freshness block** (952 → 598 ký tự, −37%). Phần gộp 14 hard
>   rule thành 8 bị bỏ: đo trên canon cho thấy gộp chỉ tiết kiệm **5%** khối
>   (16% nếu nén chữ mạnh tay nhất mà vẫn giữ đủ 14 ràng buộc) — số bullet
>   không phải thứ tốn token, chữ mới là, mà chữ chính là guardrail. Đổi lại
>   là một diff trong đó "viết lại rule" và "xoá rule" trông giống hệt nhau.
>   Test `test_shared_hard_rules_were_not_touched_by_the_c5_round` chốt quyết
>   định này.
> - **`ba-mission-plan` không báo usage** (roadmap chỉ nêu `ba-ticket-author`)
>   — ghi lại làm việc tiếp, không tự nới scope.
> - **D4 vẫn đứng ngoài** vì nội dung conventions (D1–D3) chưa có.
>
> Nhắc cho nhóm C: khoản tiết kiệm thật của đợt này nhỏ. Item mà số liệu
> batch 2 vẫn trỏ vào là **C1** (`kb resolve` trả toàn văn 4–5 lần/ticket).
```

- [ ] **Step 5: Bump the version**

In `pyproject.toml`, change `version = "0.19.0"` to `version = "0.20.0"`. Adopting repos pick up the new skill text only through a package upgrade, so the round needs its own version.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/reviews pyproject.toml
git commit -m "chore: tick roadmap batch 3 and bump to 0.20.0"
```

- [ ] **Step 7: Open the PR**

Body must carry: the six roadmap items; the measurement that cut C5 down to the freshness block (952 → 605 characters as shipped, versus 5–16% for the hard-rules regrouping); the full-suite output from Step 1; and the three deliberate deviations (hard rules left alone, no `ba-mission-plan` usage reporting, D4 deferred).

---

## Notes for the reviewer of this round

- **The one thing worth reading closely** is Task 1's `NEW_FRESHNESS`. What it drops is explanation; what it must keep is the three verdicts, the `kb get … --level l3` escape hatch, and the `kb diff` warning. If a verdict or the warning is thinner than before, reject. The hard rules are deliberately untouched this round — a diff against them is a mistake, and `test_shared_hard_rules_were_not_touched_by_the_c5_round` should catch it.
- **`claude-command-ba-ticket-author.md` is the odd file out** in four of the six tasks — it is a short pointer wrapper with no Ground step, no Pin command, and no maturity detail, so every item reaches it as a clause on an existing compressed line rather than as a step.
- **Byte-identity is produced, not maintained.** If a later fix touches a SHARED-* block, it goes through a script over all 20 files and a `repr()` regeneration of the canon — never a hand edit of one file.

## Deviations during execution

Recorded after the fact, against the final whole-branch review (F9). The
task bodies above are left as written; this section notes where the
landed test differs from the plan's draft and why. Four spots, all in
Task 5 (B4) and Task 3 (C2):

1. **`:537`** — the plan's draft asserted `assert "authoring" in text,
   name`. Shipped as `assert "authoring cost" in text, name` instead: the
   looser needle was satisfiable by unrelated prose (e.g. any sentence
   using the word "authoring"), so it never guarded the B4 sentence it
   was written to pin. Landed in `fix(tests): tighten the B4
   authoring-cost needle so it actually guards` (832719a).

2. **`:663`** — the plan's draft asserted `assert "kb query" in text,
   name` (paired with a separate `assert "--tags" in text, name`).
   Shipped as a single assertion on the literal command, `assert 'kb
   query "<text>" --tags <tags>' in text, name`: the two-piece form
   was satisfiable by Task 5's own added sentence ("...are search
   keywords for `kb query --tags`, nothing more."), which contains
   both needles without the command actually surviving. Landed in
   `fix(tests): tighten the A4 search-filter needle so it actually
   guards` (ba92a12).

3. **`:803-805`** — `test_ba_wrappers_keep_round_one_two_perspective`
   was drafted as `for name in BA_WRAPPERS` (all 8 wrappers). Shipped
   scoped to the 7 full-shaped wrappers, excluding
   `claude-command-ba-ticket-author.md`: that file never named either
   reviewer role by the exact phrase "Business-coverage reviewer" /
   "Dev-implementability reviewer" — it is the short wrapper with "no
   maturity detail" noted above, and C2's edit for that file adds only
   the `gap-verifier` clause, not these two phrases.

4. **`:825`** — the claim `test_ba_wrappers_keep_round_one_two_perspective`
   "passes already" was false for the unscoped, 8-file form the plan
   drafted: `claude-command-ba-ticket-author.md` never carried the two
   reviewer-role phrases, at any point before or after this round, so
   the 8-file assertion was permanently unsatisfiable rather than
   already passing. It became true only once scoped to 7 wrappers, per
   deviation 3 above.

5. **Task 1's block text** — the shipped `SHARED-FRESHNESS` is 605 characters,
   not the 598 this task drafted. The final whole-branch review found that
   trimming the `Do NOT use` imperative off the block's `kb diff` warning
   turned its most consequential instruction into something that reads as a
   label, and the imperative was restored across all 20 wrappers with the
   canon regenerated (commit `6e39b43`). Task 1's `NEW_FRESHNESS` literal above is
   left as drafted, so it no longer matches the shipped text; the canon in
   `tests/test_templates.py` is the authority. The 660-character ceiling was
   chosen wide enough to absorb exactly this kind of correction.
