# Restore `kb approve` + `/kb-approve` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring back the manual SME review step: `kb approve` flips section `status: summarized → reviewed` in `_manifest.yaml`, with `/kb-approve` slash-command wrappers scaffolded for both repo kinds.

**Architecture:** `review.py` + the `approve` CLI command + both test files are restored VERBATIM from git rev `6116566^` (the commit before removal) — every API they consume still exists unchanged. New work is only the four wrapper templates (COMMON), parity-test updates, and doc lines. No CI workflow is restored.

**Tech Stack:** Python 3.12, Typer, pytest (`git_kb` fixture at `tests/conftest.py:157` — unchanged since removal).

**Spec:** `docs/superpowers/specs/2026-07-15-kb-approve-restore-design.md`

## Global Constraints

- `review.py`, the `approve` command body, and both test files are restorations — byte-identical to `6116566^` except where a current-codebase conflict forces an edit; any such edit must be listed in the implementer report.
- No `kb-review.yml` workflow, no init template for it — the CI auto-flip stays dropped.
- Windows dev box: tests via `uv run pytest`. Lint gate: `uv run ruff check <touched files>` (whole-tree ruff has known pre-existing failures in unrelated files; black is NOT a project dependency — skip it).
- Conventional commits, no attribution footer.

---

### Task 1: Restore `review.py`, the `approve` CLI command, and both test suites

**Files:**
- Create: `src/center_kb/review.py` (restored)
- Modify: `src/center_kb/cli.py` (re-register the `approve` command)
- Create: `tests/test_review.py`, `tests/test_cli_approve.py` (restored)

**Interfaces:**
- Consumes: `models.load_yaml_model/save_yaml_model`, `models.Manifest`, `models.KBIndex`, `gitio.git_root/read_at/GitError`, `diff.diff_doc` — all present in the current tree.
- Produces: `review.approve_sections(kb_dir, doc_id, section_ids=None) -> ApproveReport`, `review.approve_all_changed(kb_dir, against, doc_id=None) -> list[ApproveReport]`, CLI command `kb approve` (Task 2's wrappers call it).

- [ ] **Step 1: Restore the three files verbatim from history**

```bash
git show 6116566^:src/center_kb/review.py > src/center_kb/review.py
git show 6116566^:tests/test_review.py > tests/test_review.py
git show 6116566^:tests/test_cli_approve.py > tests/test_cli_approve.py
```

- [ ] **Step 2: Run the restored tests — expect FAIL (command not registered)**

Run: `uv run pytest tests/test_review.py tests/test_cli_approve.py -v`
Expected: `tests/test_review.py` PASSES (pure module restore); every `tests/test_cli_approve.py` test FAILS with exit code 2 / "No such command 'approve'".

- [ ] **Step 3: Re-register the CLI command**

In `src/center_kb/cli.py`, insert the command verbatim from history. Extract it with:

```bash
git show 6116566^:src/center_kb/cli.py | sed -n '556,635p'
```

That range is the complete `@app.command()` / `def approve(...)` block (from the `@app.command()` decorator line through the final `raise typer.Exit(1)` of the "no summarized section to approve" branch). Insert it before the `doctor` command in the current `cli.py`, matching the file's two-blank-line spacing between commands. Verify the pasted block imports only inside the function body (`from center_kb import gitio`, `from center_kb.review import approve_all_changed, approve_sections`) — it does, so no top-of-file import edits are needed.

- [ ] **Step 4: Run the restored suites — expect PASS**

Run: `uv run pytest tests/test_review.py tests/test_cli_approve.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Full suite + lint**

Run: `uv run pytest -q`
Expected: previous count + restored tests, no new failures (1 pre-existing StarletteDeprecationWarning is known noise).
Run: `uv run ruff check src/center_kb/review.py src/center_kb/cli.py tests/test_review.py tests/test_cli_approve.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/review.py src/center_kb/cli.py tests/test_review.py tests/test_cli_approve.py
git commit -m "feat: restore kb approve — manual summarized→reviewed flip"
```

---

### Task 2: `/kb-approve` wrappers + docs

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-kb-approve.md`
- Create: `src/center_kb/templates/init/claude-command-kb-approve.md`
- Create: `src/center_kb/templates/init/copilot-kb-approve.prompt.md`
- Create: `src/center_kb/templates/init/cursor-kb-approve.md`
- Modify: `src/center_kb/initcmd.py` (4 new `COMMON_TEMPLATES` entries)
- Modify: `src/center_kb/templates/init/QUICKSTART-child.md`, `src/center_kb/templates/init/QUICKSTART-hub.md`, `README.md`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: the `kb approve` CLI from Task 1 (exact flags: `DOC_ID` optional, `--section` repeatable, `--all-changed --against <rev>`).
- Produces: both kinds scaffold `.claude/skills/kb-approve/SKILL.md`, `.claude/commands/kb-approve.md`, `.github/prompts/kb-approve.prompt.md`, `.cursor/commands/kb-approve.md`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_init.py`:

**(a)** In the assistant-parity test, add `"kb-approve"` to the common command list (same place `"kb-docker-setup"` was added — the list used for both kinds). Note for the `.cursor` layout: like the other commands, `kb-approve` has a Cursor command file but no `.mdc` rule, so no rule-filter change is needed; like `kb-summarize`/`kb-docker-setup` it HAS a Claude skill, so if the parity test's skill-check filter (`if n in ("kb-summarize", "kb-docker-setup")`) exists, extend it to include `"kb-approve"`.

**(b)** Add a content test:

```python
def test_init_scaffolds_kb_approve_both_kinds(tmp_path: Path):
    for kind in ("hub", "child"):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        skill = repo / ".claude" / "skills" / "kb-approve" / "SKILL.md"
        command = repo / ".claude" / "commands" / "kb-approve.md"
        prompt = repo / ".github" / "prompts" / "kb-approve.prompt.md"
        cursor = repo / ".cursor" / "commands" / "kb-approve.md"
        assert skill.exists() and command.exists() and prompt.exists(), kind
        assert cursor.exists(), kind
        skill_text = skill.read_text(encoding="utf-8")
        assert "name: kb-approve" in skill_text
        assert "mode: agent" in prompt.read_text(encoding="utf-8")
        for text in (
            skill_text,
            prompt.read_text(encoding="utf-8"),
            cursor.read_text(encoding="utf-8"),
        ):
            assert "kb approve" in text            # wraps the CLI
            assert "_manifest.yaml" in text        # forbids hand-editing rule
        assert "kb-approve" in command.read_text(encoding="utf-8")
```

Run: `uv run pytest tests/test_init.py -v -k approve`
Expected: FAIL (templates don't exist).

- [ ] **Step 2: Create the four templates**

`src/center_kb/templates/init/claude-skill-kb-approve.md`:

```markdown
---
name: kb-approve
description: Mark KB sections as reviewed (status summarized → reviewed) after an SME has checked the summaries. Use when asked to approve a document or sections, or when the user invokes /kb-approve.
---

# kb-approve — mark sections as reviewed

Thin wrapper around the `kb approve` CLI. Your job: show what is
approvable, confirm the scope with the user, run the command, relay its
output.

Hard rules:
- NEVER edit `_manifest.yaml` (or any `.kb/` file) by hand to change a
  status — the ONLY way to flip a status is the `kb approve` CLI.
- Approving is an SME judgment call. Do not run `kb approve` unless the
  user explicitly asked to approve, and never enlarge the scope they gave
  (doc/sections) on your own.
- Non-zero exit → show the error verbatim and stop. Do not retry with
  guessed fixes.

## Workflow

1. Run `kb status` and show the user the documents and how many sections
   are pending vs summarized. `pending` sections cannot be approved —
   point the user at `/kb-summarize` for those.
2. Confirm the scope: whole doc (`kb approve <doc-id>`), specific
   sections (`kb approve <doc-id> --section <id> --section <id>`), or
   everything changed since a rev
   (`kb approve --all-changed --against <rev>`).
3. Run the command and relay the output: which sections flipped to
   reviewed, which were skipped as pending, any missing-section errors.
4. Remind the user the change is local to `_manifest.yaml` — commit it
   (and `kb publish` when ready) to make it durable.
```

`src/center_kb/templates/init/claude-command-kb-approve.md`:

```markdown
---
description: Mark KB sections as reviewed (summarized → reviewed) via kb approve
---

Invoke the `kb-approve` skill with the Skill tool and follow its workflow
exactly.
```

`src/center_kb/templates/init/copilot-kb-approve.prompt.md`:

```markdown
---
mode: agent
description: Mark KB sections as reviewed (status summarized → reviewed) via the kb approve CLI.
---

# /kb-approve — mark sections as reviewed

Thin wrapper around the `kb approve` CLI. Show what is approvable, confirm
the scope with the user, run the command, relay its output.

Hard rules:
- NEVER edit `_manifest.yaml` (or any `.kb/` file) by hand to change a
  status — the ONLY way to flip a status is the `kb approve` CLI.
- Approving is an SME judgment call. Do not run `kb approve` unless the
  user explicitly asked to approve, and never enlarge the scope they gave.
- Non-zero exit → show the error verbatim and stop.

## Workflow

1. Run `kb status`; show documents with pending vs summarized counts
   (`pending` cannot be approved — use /kb-summarize first).
2. Confirm scope: `kb approve <doc-id>`, or
   `kb approve <doc-id> --section <id>` (repeatable), or
   `kb approve --all-changed --against <rev>`.
3. Run it and relay the output (flipped / skipped-pending / missing).
4. Remind the user to commit `_manifest.yaml` (and `kb publish` when
   ready) to make it durable.
```

`src/center_kb/templates/init/cursor-kb-approve.md` — same body as the Copilot prompt but with Cursor frontmatter:

```markdown
---
name: kb-approve
description: Mark KB sections as reviewed (status summarized → reviewed) via the kb approve CLI.
---

# /kb-approve — mark sections as reviewed

Thin wrapper around the `kb approve` CLI. Show what is approvable, confirm
the scope with the user, run the command, relay its output.

Hard rules:
- NEVER edit `_manifest.yaml` (or any `.kb/` file) by hand to change a
  status — the ONLY way to flip a status is the `kb approve` CLI.
- Approving is an SME judgment call. Do not run `kb approve` unless the
  user explicitly asked to approve, and never enlarge the scope they gave.
- Non-zero exit → show the error verbatim and stop.

## Workflow

1. Run `kb status`; show documents with pending vs summarized counts
   (`pending` cannot be approved — use /kb-summarize first).
2. Confirm scope: `kb approve <doc-id>`, or
   `kb approve <doc-id> --section <id>` (repeatable), or
   `kb approve --all-changed --against <rev>`.
3. Run it and relay the output (flipped / skipped-pending / missing).
4. Remind the user to commit `_manifest.yaml` (and `kb publish` when
   ready) to make it durable.
```

- [ ] **Step 3: Register in `COMMON_TEMPLATES`**

In `src/center_kb/initcmd.py`, add to `COMMON_TEMPLATES` (next to the other kb-* wrapper entries):

```python
    ".claude/skills/kb-approve/SKILL.md": "claude-skill-kb-approve.md",
    ".claude/commands/kb-approve.md": "claude-command-kb-approve.md",
    ".github/prompts/kb-approve.prompt.md": "copilot-kb-approve.prompt.md",
    ".cursor/commands/kb-approve.md": "cursor-kb-approve.md",
```

- [ ] **Step 4: Doc updates**

`src/center_kb/templates/init/QUICKSTART-child.md` — at the end of the Summarize step's text (the step that ends with "Then validate: `kb build`"), append:

```markdown
   After checking the summaries, mark them reviewed:
   `kb approve <doc-id>` (in your assistant: `/kb-approve`).
```

Both QUICKSTARTs — add to the CLI reference list (after the `kb summarize` line):

```markdown
- `kb approve <doc-id> [--section <id>]` — mark summarized sections as
  reviewed after SME check; `--all-changed --against <rev>` approves what
  changed since a rev (in your assistant: `/kb-approve`)
```

`README.md` — in the CLI overview area where `kb summarize`/`kb build` are described (grep for the command list), add one line in the same style:

```markdown
`kb approve` marks summarized sections as `reviewed` after an SME check
(slash command: `/kb-approve`).
```

Place it where the other command one-liners live; match surrounding formatting exactly.

- [ ] **Step 5: Run tests + lint**

Run: `uv run pytest tests/test_init.py tests/test_templates.py -q` then `uv run pytest -q`
Expected: ALL PASS.
Run: `uv run ruff check src/center_kb/initcmd.py tests/test_init.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init src/center_kb/initcmd.py tests/test_init.py README.md
git commit -m "feat: /kb-approve slash command wrappers on both kinds + docs"
```
