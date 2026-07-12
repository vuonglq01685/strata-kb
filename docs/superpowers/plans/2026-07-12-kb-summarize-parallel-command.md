# /kb-summarize Slash Command + Parallel Sub-Agent Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/kb-summarize` slash command (thin wrapper) and rewrite the kb-summarize skill into an orchestrator that dispatches read-only sub-agents in parallel (batches of ~5 sections, max 10 concurrent) and merges their JSON results itself.

**Architecture:** Canonical templates live in `src/center_kb/templates/init/` and are scaffolded by `kb init` via `TEMPLATE_MAP` in `initcmd.py`; the repo's own `.claude/` files are dogfood copies. Sub-agents never write files — they return JSON `{section_id, l2_summary, l1_summary, table_only}`; the orchestrator is the single writer (same pattern as `summarize.py`'s `ThreadPoolExecutor` + `_apply_results`).

**Tech Stack:** Python 3.13 (`.venv`), typer CLI, pytest, Claude Code skills/commands (markdown templates).

**Spec:** `docs/superpowers/specs/2026-07-12-kb-summarize-parallel-command-design.md`

## Global Constraints

- Templates are written in **English** (spec decision #10).
- Tests are hermetic: no LLM calls, no `claude` CLI dependency (repo constraint — the machine has a real `claude` on PATH).
- The rewritten skill MUST keep these exact strings (existing tests assert on them): `name: kb-summarize`, `VERBATIM`, `kb build`, `Summarize the prose ONLY`, `Table-only section:`.
- Writing rules content is unchanged — only its role changes (embedded verbatim into sub-agent prompts).
- Copilot files (`copilot-kb-summarize.instructions.md`) are OUT of scope — do not touch.
- CLI behavior (`summarize.py`, `cli.py`) is OUT of scope — do not touch.
- Test runner: `.venv/bin/python -m pytest` from the repo root.

---

### Task 1: Rewrite the canonical skill template as a parallel orchestrator

**Files:**
- Modify: `src/center_kb/templates/init/claude-skill-kb-summarize.md` (full rewrite)
- Test: `tests/test_init.py` (add one test; existing kb-summarize assertions must keep passing)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: the skill template text. Task 2's command template references the skill by name `kb-summarize`. Task 3 copies this file verbatim to `.claude/skills/kb-summarize/SKILL.md`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_init.py`:

```python
def test_kb_summarize_skill_is_parallel_orchestrator(tmp_path: Path):
    init_repo(tmp_path)
    skill = (
        tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "READ-ONLY" in skill                      # sub-agents never write
    assert '"table_only"' in skill                   # JSON output contract
    assert '"l2_summary"' in skill
    assert '"l1_summary"' in skill
    assert "batches of ~5" in skill                  # granularity
    assert "at most 10" in skill                     # concurrency cap
    assert "kb build --allow-pending" in skill       # per-wave verify
    assert "single message" in skill                 # concurrent dispatch
    assert "one retry only" in skill                 # error handling
    assert "Do not edit many files in parallel" not in skill  # old rule gone
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_init.py::test_kb_summarize_skill_is_parallel_orchestrator -v`
Expected: FAIL on `assert "READ-ONLY" in skill` (template still sequential).

- [ ] **Step 3: Replace the template content**

Overwrite `src/center_kb/templates/init/claude-skill-kb-summarize.md` with exactly:

````markdown
---
name: kb-summarize
description: Fill pending L0/L1/L2 summaries in .kb/ after `kb ingest`. Use when asked to summarize the KB or fill summaries, when the user invokes /kb-summarize, or right after ingesting a new document when auto-summarize was skipped or failed.
---

# KB Summarize — parallel fill of the .kb/ scaffold

You are the ORCHESTRATOR of the manual summarize pipeline. `kb ingest`
generated the scaffold; read-only sub-agents draft the summaries in
parallel; you are the ONLY writer that touches files.

Note: `kb ingest` normally does this automatically by calling a headless
LLM CLI (`kb summarize`). Use this manual workflow when auto-summarize was
disabled (`--no-summarize`, `runner: none`), no LLM CLI was available, or
some sections failed and you want to fix them.

An optional argument narrows the run to one document id; no argument =
every document with pending sections.

## Workflow

1. **Collect** — run `kb status`; list the pending sections as
   (doc-id, section-id, L2 file). Filter by the doc-id argument if given.
   Nothing pending → report that and stop.
2. **Partition** — group the sections into batches of ~5, preferring
   sections that share the same L2 file. Schedule waves of at most 10
   batches (= at most 10 concurrent sub-agents).
3. **Dispatch** — spawn ALL sub-agents of the wave in a single message so
   they run concurrently. Each sub-agent prompt MUST contain:
   - the list of assigned sections: doc-id, section-id, title;
   - the command to read each source:
     `kb get <doc-id> <section-id> --level l3`;
   - the full "Writing rules" block below, copied verbatim;
   - the output contract: reply with ONLY a JSON array —
     `[{"section_id": "...", "l2_summary": "...", "l1_summary": "...", "table_only": false}, ...]`
     For a section with no prose (heading + tables only) set
     `"table_only": true`, `"l2_summary": ""` and
     `"l1_summary": "Table-only section: <title>."`;
   - the hard restriction: the sub-agent is READ-ONLY — it must not
     write, edit, or create any file.
4. **Merge** — you apply the results yourself, sequentially, never in
   parallel. For each returned section:
   a. Validate: every assigned section present; `l1_summary` ≤ 25 words;
      `l2_summary` non-empty unless `table_only`.
   b. In the L2 file, replace the marker line
      `<!-- TODO:summarize <section-id> -->` with the l2_summary
      paragraph — or delete the marker line (leave nothing) when
      `table_only`. Do NOT touch the markdown tables already present in
      the section — the tooling copies them verbatim.
   c. In `.kb/<doc-id>/_manifest.yaml`, set that section's `summary:` to
      the l1_summary and change `status: pending` → `status: summarized`.
5. **Verify the wave** — run `kb build --allow-pending`; it must pass.
   If it fails on table integrity a table was modified: restore it
   verbatim from the `.raw.md` file and build again. Then continue with
   the next wave (repeat steps 3–5).
6. **Finalize** — when every section of a doc is done: open
   `.kb/index.yaml`, fill or fix that doc's `summary` (one sentence) and
   verify its `title`, `revision` and `tags`. Run `kb build` (strict) —
   it must PASS. Report: sections filled, sections still pending (with
   reasons), total L2 tokens (see `kb stats`).

## Error handling

- A sub-agent reply that fails validation (broken JSON, missing section,
  over-length summary) → do NOT respawn an agent. Summarize the failed
  section yourself, sequentially: read its L3 and apply the Writing
  rules — one retry only.
- A section that still fails → leave it `status: pending` and list it in
  the final report.
- Never end a wave with a failing `kb build --allow-pending`.

## Writing rules (mandatory — copy verbatim into every sub-agent prompt)

- Write in **English**.
- Summarize the prose ONLY. Never describe, list, or reconstruct table
  contents — the tables are already copied verbatim into the section.
- If a section has no prose (heading + tables only): delete the marker
  line (leave nothing) and set the manifest `summary` to
  `Table-only section: <title>.` — do NOT invent prose about the tables.
- Keep the L2 paragraph under ~35% of the original prose length. If your
  draft is longer, compress harder.
- L2 paragraph: condense the prose to ~20–30% of the original length and
  keep the logical structure.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...),
  numeric values, units, cross-references (§x.y). Never paraphrase
  technical terms.
- Do NOT infer beyond the source text. When unsure, keep the original
  sentence.
- Do NOT summarize tables, create new tables, or delete tables.
- L1 summary (manifest): one sentence ≤ 25 words stating what the section
  covers and what kind of data it contains (so BM25 matches technical
  keywords).
````

- [ ] **Step 4: Run the full init/template test files to verify everything passes**

Run: `.venv/bin/python -m pytest tests/test_init.py tests/test_templates.py -v`
Expected: ALL PASS — including the pre-existing
`test_init_scaffolds_ai_integration_files` and
`test_kb_summarize_templates_have_prose_only_rules` (the required strings
`name: kb-summarize`, `VERBATIM`, `kb build`, `Summarize the prose ONLY`,
`Table-only section:` are all still present in the new text).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init/claude-skill-kb-summarize.md tests/test_init.py
git commit -m "feat: kb-summarize skill template — parallel read-only sub-agents, orchestrator merges"
```

---

### Task 2: Command template + TEMPLATE_MAP entry

**Files:**
- Create: `src/center_kb/templates/init/claude-command-kb-summarize.md`
- Modify: `src/center_kb/initcmd.py:8-23` (add one TEMPLATE_MAP entry)
- Test: `tests/test_init.py` (add one test)

**Interfaces:**
- Consumes: skill name `kb-summarize` from Task 1.
- Produces: scaffolded file `.claude/commands/kb-summarize.md`; new
  `TEMPLATE_MAP` key `".claude/commands/kb-summarize.md"`. Task 3 copies
  the template to the repo's own `.claude/commands/`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_init.py`:

```python
def test_init_scaffolds_kb_summarize_slash_command(tmp_path: Path):
    init_repo(tmp_path)
    command = tmp_path / ".claude" / "commands" / "kb-summarize.md"
    assert command.is_file()
    text = command.read_text(encoding="utf-8")
    assert "kb-summarize" in text          # invokes the skill by name
    assert "$ARGUMENTS" in text            # forwards the doc-id filter
    assert "argument-hint" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_init.py::test_init_scaffolds_kb_summarize_slash_command -v`
Expected: FAIL on `assert command.is_file()`.

- [ ] **Step 3: Create the command template**

Create `src/center_kb/templates/init/claude-command-kb-summarize.md` with exactly:

```markdown
---
description: Fill pending KB summaries with parallel sub-agents (manual fallback after kb ingest)
argument-hint: "[doc-id]"
---

Invoke the `kb-summarize` skill with the Skill tool and follow its
workflow exactly. Pass "$ARGUMENTS" as the doc-id filter; when it is
empty, process every document that has pending sections.
```

- [ ] **Step 4: Register it in TEMPLATE_MAP**

In `src/center_kb/initcmd.py`, add one line to `TEMPLATE_MAP` after the
`.claude/skills/kb-summarize/SKILL.md` entry:

```python
    ".claude/skills/kb-summarize/SKILL.md": "claude-skill-kb-summarize.md",
    ".claude/commands/kb-summarize.md": "claude-command-kb-summarize.md",
    ".github/instructions/kb-summarize.instructions.md": "copilot-kb-summarize.instructions.md",
```

(`EXPECTED_FILES = list(TEMPLATE_MAP)` picks it up automatically —
`test_init_creates_all_files` and idempotency tests need no edits.)

- [ ] **Step 5: Run the init/template test files to verify all pass**

Run: `.venv/bin/python -m pytest tests/test_init.py tests/test_templates.py -v`
Expected: ALL PASS (including `test_all_init_templates_exist_as_package_resources`, which iterates TEMPLATE_MAP values).

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/claude-command-kb-summarize.md src/center_kb/initcmd.py tests/test_init.py
git commit -m "feat: scaffold /kb-summarize slash command wrapper in kb init"
```

---

### Task 3: Dogfood copies into the AERO-KB repo

**Files:**
- Modify: `.claude/skills/kb-summarize/SKILL.md` (overwrite with Task 1 template)
- Create: `.claude/commands/kb-summarize.md` (copy of Task 2 template)

**Interfaces:**
- Consumes: the two template files from Tasks 1–2 (copied byte-for-byte).
- Produces: working `/kb-summarize` in this repo's Claude Code sessions.

- [ ] **Step 1: Copy templates over the dogfood files**

```bash
cp src/center_kb/templates/init/claude-skill-kb-summarize.md .claude/skills/kb-summarize/SKILL.md
mkdir -p .claude/commands
cp src/center_kb/templates/init/claude-command-kb-summarize.md .claude/commands/kb-summarize.md
```

- [ ] **Step 2: Verify the copies are identical**

Run: `diff src/center_kb/templates/init/claude-skill-kb-summarize.md .claude/skills/kb-summarize/SKILL.md && diff src/center_kb/templates/init/claude-command-kb-summarize.md .claude/commands/kb-summarize.md && echo IDENTICAL`
Expected: `IDENTICAL`

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/kb-summarize/SKILL.md .claude/commands/kb-summarize.md
git commit -m "chore: dogfood parallel kb-summarize skill + /kb-summarize command"
```

---

### Task 4: Documentation — QUICKSTART template + README

**Files:**
- Modify: `src/center_kb/templates/init/QUICKSTART.md` (step 3 + CLI reference line)
- Modify: `README.md` (kb-summarize mentions at lines ~100, ~231, ~281, ~437, ~521)
- Test: `tests/test_init.py` (extend the existing CLI-reference test)

**Interfaces:**
- Consumes: command name `/kb-summarize` from Task 2.
- Produces: docs only — nothing downstream.

- [ ] **Step 1: Write the failing test**

In `tests/test_init.py`, extend `test_quickstart_and_instructions_have_cli_reference` — after the existing `assert "/kb-publish" in quick` line, add:

```python
    assert "/kb-summarize" in quick
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_init.py::test_quickstart_and_instructions_have_cli_reference -v`
Expected: FAIL on the new assert.

- [ ] **Step 3: Update the QUICKSTART template**

In `src/center_kb/templates/init/QUICKSTART.md`:

Replace step 3's manual-fallback sentence:

```markdown
   Manual fallback: run the `kb-summarize` skill in Claude Code, or
   `kb summarize` later. Then validate: `kb build`
```

with:

```markdown
   Manual fallback: run `/kb-summarize` in Claude Code (parallel
   sub-agents fill the sections), or `kb summarize` later.
   Then validate: `kb build`
```

Replace the CLI-reference line:

```markdown
- `kb summarize` — fill pending summaries via a headless LLM CLI
```

with:

```markdown
- `kb summarize` — fill pending summaries via a headless LLM CLI
  (in Claude Code: `/kb-summarize`)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_init.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Update README mentions**

In `README.md`, update the five kb-summarize mentions so the slash command
is the named entry point (the skill remains the mechanism):

- Line ~100 (pipeline diagram note): `kb-summarize skill = manual fallback` → `/kb-summarize = manual fallback`
- Line ~231 (step table, row 3, last cell): `or use the `kb-summarize` skill in Claude Code as manual fallback when no LLM CLI is installed` → `or run `/kb-summarize` in Claude Code as manual fallback when no LLM CLI is installed (parallel sub-agents draft, the orchestrator writes)`
- Line ~281 (prose paragraph): `open Claude Code and run the `kb-summarize` skill (at `.claude/skills/kb-summarize/SKILL.md`) as the manual fallback: it runs `kb status`, reads each section, writes summaries under fixed style rules (keep every code/number, no invention), and saves.` → `open Claude Code and run `/kb-summarize` (skill at `.claude/skills/kb-summarize/SKILL.md`) as the manual fallback: it runs `kb status`, fans the pending sections out to parallel read-only sub-agents (~5 sections each, max 10 at a time), then merges their summaries itself under fixed style rules (keep every code/number, no invention).`
- Line ~437: `the kb-summarize skill as the manual fallback (self-checks every 5–10` → keep the sentence but rename to `/kb-summarize` (the per-wave `kb build --allow-pending` still self-checks every ~5–10 sections).
- Line ~521 (troubleshooting table): `back to Claude Code with the `kb-summarize` skill` → `back to Claude Code with `/kb-summarize``

Exact surrounding wording may have drifted — locate each with `grep -n "kb-summarize" README.md` and apply the same rename pattern.

- [ ] **Step 6: Run the whole test suite**

Run: `.venv/bin/python -m pytest`
Expected: ALL PASS (notably `tests/test_ingest_cli.py::…` line 152 asserts the literal `kb-summarize` in CLI output — untouched by this task).

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/templates/init/QUICKSTART.md README.md tests/test_init.py
git commit -m "docs: /kb-summarize slash command in QUICKSTART template and README"
```

---

### Task 5: Manual dogfood verification (no code)

**Files:** none (verification only)

**Interfaces:**
- Consumes: everything above.
- Produces: confidence + any follow-up fixes.

- [ ] **Step 1: Check for pending sections**

Run: `.venv/bin/kb status` (or `kb status` if the venv is active)
Expected: list of docs; note whether any section is `pending`. If none are
pending, this task ends here — report that the live run must wait for the
next ingest.

- [ ] **Step 2: Live run (only if pending sections exist)**

In a Claude Code session in this repo, run `/kb-summarize <doc-id>` and
observe: sub-agents spawned concurrently in waves (≤ 10), no sub-agent
edits files, orchestrator merges, `kb build --allow-pending` after each
wave, final `kb build` PASS, report includes filled/failed counts.

- [ ] **Step 3: Report results to the user**

State plainly what was verified and anything that failed.
