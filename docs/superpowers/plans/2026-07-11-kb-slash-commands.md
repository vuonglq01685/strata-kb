# /kb-ingest + /kb-publish Slash Command Scaffold — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb init` scaffolds two agent slash commands — `/kb-ingest` (interview for id/tags/revision, then run `kb ingest`) and `/kb-publish` (diff → approve → publish with a confirmation gate) — for both Claude Code and GitHub Copilot, plus a CLI reference so agents know the remaining `kb` commands.

**Architecture:** Pure template work. Four new template files under `src/center_kb/templates/init/`, four new entries in `TEMPLATE_MAP` in `initcmd.py` (the single source of truth — `EXPECTED_FILES` and the idempotency tests derive from it automatically). Two existing templates get a CLI-reference section. Finally the four rendered files are copied into this repo itself (dogfood). No CLI behavior changes.

**Tech Stack:** Python 3.13, Typer CLI, pytest (`tests/test_init.py` pattern: `init_repo(tmp_path)` + content-marker asserts).

**Spec:** `docs/superpowers/specs/2026-07-11-kb-slash-commands-design.md`

## Global Constraints

- All template content is **English** (spec decision #8).
- Default source folder referenced by templates is **`source/`** (singular — spec decision #1). Never write `sources/` in any template.
- `/kb-ingest` HARD RULE: the agent must never run `kb ingest` until the user explicitly confirmed **id, tags, and revision**; "none" is a valid answer for tags/revision (spec decision #2).
- `/kb-publish` HARD RULE: the agent must never run `kb approve` or `kb publish` until the user explicitly confirmed after seeing the diff; hub comes from `CENTER_KB_HUB` or is asked — never guessed (spec decision #7).
- Claude side = skill (`.claude/skills/<name>/SKILL.md` with `name:` + `description:` frontmatter). Copilot side = prompt file (`.github/prompts/<name>.prompt.md` with `mode: agent` + `description:` frontmatter). The existing `.github/instructions/` file stays as-is except for the CLI-reference addition.
- `kb init` must remain idempotent: never overwrite existing files unless `force=True` (already guaranteed by `init_repo`; the new files just ride along).
- Test command: `.venv/bin/python -m pytest tests/test_init.py -v` from the repo root `/Users/vuonglq01685/Documents/Projects/AERO-KB`.
- Commit style: conventional commits (`feat:`, `test:`, `docs:`), no attribution footer.

---

### Task 1: /kb-ingest templates + TEMPLATE_MAP entries

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-kb-ingest.md`
- Create: `src/center_kb/templates/init/copilot-kb-ingest.prompt.md`
- Modify: `src/center_kb/initcmd.py:8-19` (TEMPLATE_MAP)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `init_repo(target: Path, force: bool = False) -> InitReport` and `TEMPLATE_MAP: dict[str, str]` from `center_kb.initcmd` (existing).
- Produces: scaffolded files `.claude/skills/kb-ingest/SKILL.md` and `.github/prompts/kb-ingest.prompt.md` in any `kb init` target. Task 4 copies these rendered files into this repo.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_init.py`:

```python
def test_init_scaffolds_kb_ingest_slash_command(tmp_path: Path):
    init_repo(tmp_path)
    skill = tmp_path / ".claude" / "skills" / "kb-ingest" / "SKILL.md"
    prompt = tmp_path / ".github" / "prompts" / "kb-ingest.prompt.md"
    assert skill.is_file() and prompt.is_file()
    skill_text = skill.read_text(encoding="utf-8")
    prompt_text = prompt.read_text(encoding="utf-8")
    assert "name: kb-ingest" in skill_text
    assert "mode: agent" in prompt_text
    for text in (skill_text, prompt_text):
        assert "source/" in text                     # default folder
        assert "sources/" not in text                # spec: singular only
        assert "NEVER run `kb ingest`" in text       # hard rule present
        assert "revision" in text and "tags" in text
        assert '"none" is a valid answer' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_init.py::test_init_scaffolds_kb_ingest_slash_command -v`
Expected: FAIL — `AssertionError` on `skill.is_file()` (file not scaffolded yet).

- [ ] **Step 3: Create the Claude skill template**

Create `src/center_kb/templates/init/claude-skill-kb-ingest.md` with exactly this content:

````markdown
---
name: kb-ingest
description: Ingest a source PDF into the .kb/ knowledge base. Use when asked to ingest, add, or import a document into the KB, or when the user invokes /kb-ingest with a file name.
---

# KB Ingest — interview first, then run `kb ingest`

You drive the first step of the CENTER-KB pipeline: turning a source PDF
into `.kb/` scaffolding. The CLI does the heavy lifting — your job is to
resolve the file, confirm the metadata with the user, and run the command.

<HARD-RULE>
NEVER run `kb ingest` until the user has explicitly confirmed all three
values: document id, tags, and revision — even when they look obvious from
the file name. If the user already provided some of them, ask only for the
missing ones. "none" is a valid answer for tags and revision.
</HARD-RULE>

## Workflow

1. **Resolve the file.** The argument is a file name (no path needed) —
   look for it in `source/`. If that directory does not exist, list the
   repository root to find the actual source folder before giving up.
   - No argument given → list the PDFs in `source/` and ask which one.
   - File not found → say so, show the files that ARE present, and ask
     again. Never silently pick a different file.
2. **Propose metadata, then ask.** Derive suggestions from the file name:
   - `id`: short, stable, kebab-case (e.g. `ARINC424-22.pdf` → `arinc-424`)
   - `revision`: edition/supplement hints in the name (e.g. `Supplement 22`)
   - `tags`: 2–4 lowercase topical keywords
   Present all three suggestions and ask the user to confirm or correct
   each one. Wait for the answer before doing anything else.
3. **Run the command** (only after confirmation):
   `kb ingest source/<file>.pdf --id <id> --tags "<tags>" --revision "<revision>"`
   Omit `--tags` / `--revision` when the user answered "none".
4. **Report the outcome.** Relay the CLI output: number of sections,
   summarize result, `kb build` status.
   - Some sections failed to summarize → tell the user to run
     `kb summarize` (or the kb-summarize skill) and stop.
   - Non-zero exit → show the error output verbatim. Do NOT retry with
     guessed parameters; ask the user how to proceed.
````

- [ ] **Step 4: Create the Copilot prompt-file template**

Create `src/center_kb/templates/init/copilot-kb-ingest.prompt.md` with exactly this content:

````markdown
---
mode: agent
description: Ingest a source PDF into the .kb/ knowledge base — interview for id/tags/revision, then run kb ingest
---

# /kb-ingest — ingest a PDF into CENTER-KB

Turn a source PDF into `.kb/` scaffolding via the `kb ingest` CLI. Your
job: resolve the file, confirm metadata with the user, run the command.

NEVER run `kb ingest` until the user has explicitly confirmed all three
values: document id, tags, and revision — even when they look obvious from
the file name. If the user already provided some of them, ask only for the
missing ones. "none" is a valid answer for tags and revision.

## Workflow

1. **Resolve the file.** The argument is a file name — look for it in
   `source/`. If that directory does not exist, list the repository root
   to find the actual source folder before giving up.
   - No argument given → list the PDFs in `source/` and ask which one.
   - File not found → say so, show the files that ARE present, and ask
     again. Never silently pick a different file.
2. **Propose metadata, then ask.** Derive suggestions from the file name:
   - `id`: short, stable, kebab-case (e.g. `ARINC424-22.pdf` → `arinc-424`)
   - `revision`: edition/supplement hints in the name (e.g. `Supplement 22`)
   - `tags`: 2–4 lowercase topical keywords
   Present all three suggestions and ask the user to confirm or correct
   each one. Wait for the answer before doing anything else.
3. **Run the command** (only after confirmation):
   `kb ingest source/<file>.pdf --id <id> --tags "<tags>" --revision "<revision>"`
   Omit `--tags` / `--revision` when the user answered "none".
4. **Report the outcome.** Relay the CLI output: number of sections,
   summarize result, `kb build` status.
   - Some sections failed to summarize → tell the user to run
     `kb summarize` and stop.
   - Non-zero exit → show the error output verbatim. Do NOT retry with
     guessed parameters; ask the user how to proceed.
````

- [ ] **Step 5: Register both templates in TEMPLATE_MAP**

In `src/center_kb/initcmd.py`, extend `TEMPLATE_MAP` (after the two existing kb-summarize entries):

```python
TEMPLATE_MAP: dict[str, str] = {
    ".kb/index.yaml": "index.yaml",
    "federation/README.md": "federation-README.md",
    "source/.gitignore": "source-gitignore.txt",
    ".mcp.json": "mcp.json",
    ".github/workflows/kb-review.yml": "kb-review.yml",
    "docker-compose.yml": "docker-compose.yml",
    ".env.example": "env.example",
    "QUICKSTART.md": "QUICKSTART.md",
    ".claude/skills/kb-summarize/SKILL.md": "claude-skill-kb-summarize.md",
    ".github/instructions/kb-summarize.instructions.md": "copilot-kb-summarize.instructions.md",
    ".claude/skills/kb-ingest/SKILL.md": "claude-skill-kb-ingest.md",
    ".github/prompts/kb-ingest.prompt.md": "copilot-kb-ingest.prompt.md",
}
```

- [ ] **Step 6: Run the new test and the whole init suite**

Run: `.venv/bin/python -m pytest tests/test_init.py -v`
Expected: ALL PASS — including the pre-existing `test_init_creates_all_files` / idempotency / force tests, which pick up the new entries automatically via `EXPECTED_FILES`.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/templates/init/claude-skill-kb-ingest.md src/center_kb/templates/init/copilot-kb-ingest.prompt.md src/center_kb/initcmd.py tests/test_init.py
git commit -m "feat: kb init scaffolds /kb-ingest slash command (Claude skill + Copilot prompt)"
```

---

### Task 2: /kb-publish templates + TEMPLATE_MAP entries

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-kb-publish.md`
- Create: `src/center_kb/templates/init/copilot-kb-publish.prompt.md`
- Modify: `src/center_kb/initcmd.py:8-21` (TEMPLATE_MAP — as left by Task 1)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `init_repo` / `TEMPLATE_MAP` from `center_kb.initcmd`; Task 1 must be complete (its two entries are already in the map).
- Produces: scaffolded files `.claude/skills/kb-publish/SKILL.md` and `.github/prompts/kb-publish.prompt.md`. Task 4 copies the rendered files into this repo.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_init.py`:

```python
def test_init_scaffolds_kb_publish_slash_command(tmp_path: Path):
    init_repo(tmp_path)
    skill = tmp_path / ".claude" / "skills" / "kb-publish" / "SKILL.md"
    prompt = tmp_path / ".github" / "prompts" / "kb-publish.prompt.md"
    assert skill.is_file() and prompt.is_file()
    skill_text = skill.read_text(encoding="utf-8")
    prompt_text = prompt.read_text(encoding="utf-8")
    assert "name: kb-publish" in skill_text
    assert "mode: agent" in prompt_text
    for text in (skill_text, prompt_text):
        assert "NEVER run `kb approve` or `kb publish`" in text  # hard rule
        assert "kb diff" in text
        assert "kb status" in text
        assert "CENTER_KB_HUB" in text
        assert "kb doctor" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_init.py::test_init_scaffolds_kb_publish_slash_command -v`
Expected: FAIL — `AssertionError` on `skill.is_file()`.

- [ ] **Step 3: Create the Claude skill template**

Create `src/center_kb/templates/init/claude-skill-kb-publish.md` with exactly this content:

````markdown
---
name: kb-publish
description: Review and publish KB changes to the federation hub — diff changed sections, approve after user confirmation, then kb publish. Use when asked to publish the KB, push to the hub, or approve reviewed sections.
---

# KB Publish — review → approve → publish

You drive the federation step of the CENTER-KB pipeline. Approving a
section is a human review verdict; publishing is outward-facing. You
execute both — the user decides both.

<HARD-RULE>
NEVER run `kb approve` or `kb publish` until the user has explicitly
confirmed, after seeing the diff, which sections to approve and which hub
to publish to. One explicit confirmation covers both — state clearly what
will happen before asking.
</HARD-RULE>

## Workflow

1. **Check state.** Run `kb status`. If any section is still `pending`,
   stop and tell the user to summarize first (`kb summarize`, or the
   kb-summarize skill).
2. **Show the diff.** For each doc with changes, run
   `kb diff <doc-id> --against HEAD` (use another git rev if the user
   names one) and present the added/changed sections for review.
3. **Confirm — the gate.** State exactly which sections will be approved
   and which hub will receive the publish. The hub is `CENTER_KB_HUB` if
   set; if not set, ask for the hub URL/path — never guess. Then ask for
   one explicit go/no-go and wait.
4. **Execute** (only after confirmation):
   `kb approve <doc-id> --section <id>` (repeat `--section` per section),
   then `kb publish --hub <hub>`. Relay the result: repo-id, source
   commit, doc count, push vs commit-only.
5. **Errors.**
   - `kb approve` warnings about pending or missing sections → show them
     verbatim; NEVER edit `_manifest.yaml` by hand to force a status.
   - `kb publish` git/hub errors → show the stderr and suggest
     `kb doctor`.
````

- [ ] **Step 4: Create the Copilot prompt-file template**

Create `src/center_kb/templates/init/copilot-kb-publish.prompt.md` with exactly this content:

````markdown
---
mode: agent
description: Review and publish KB changes to the federation hub — diff, approve after confirmation, kb publish
---

# /kb-publish — review → approve → publish

Drive the federation step of the CENTER-KB pipeline. Approving a section
is a human review verdict; publishing is outward-facing. You execute both
— the user decides both.

NEVER run `kb approve` or `kb publish` until the user has explicitly
confirmed, after seeing the diff, which sections to approve and which hub
to publish to. One explicit confirmation covers both — state clearly what
will happen before asking.

## Workflow

1. **Check state.** Run `kb status`. If any section is still `pending`,
   stop and tell the user to summarize first (`kb summarize`).
2. **Show the diff.** For each doc with changes, run
   `kb diff <doc-id> --against HEAD` (use another git rev if the user
   names one) and present the added/changed sections for review.
3. **Confirm — the gate.** State exactly which sections will be approved
   and which hub will receive the publish. The hub is `CENTER_KB_HUB` if
   set; if not set, ask for the hub URL/path — never guess. Then ask for
   one explicit go/no-go and wait.
4. **Execute** (only after confirmation):
   `kb approve <doc-id> --section <id>` (repeat `--section` per section),
   then `kb publish --hub <hub>`. Relay the result: repo-id, source
   commit, doc count, push vs commit-only.
5. **Errors.**
   - `kb approve` warnings about pending or missing sections → show them
     verbatim; NEVER edit `_manifest.yaml` by hand to force a status.
   - `kb publish` git/hub errors → show the stderr and suggest
     `kb doctor`.
````

- [ ] **Step 5: Register both templates in TEMPLATE_MAP**

In `src/center_kb/initcmd.py`, add two entries at the end of `TEMPLATE_MAP` (after the kb-ingest entries from Task 1):

```python
    ".claude/skills/kb-publish/SKILL.md": "claude-skill-kb-publish.md",
    ".github/prompts/kb-publish.prompt.md": "copilot-kb-publish.prompt.md",
```

- [ ] **Step 6: Run the whole init suite**

Run: `.venv/bin/python -m pytest tests/test_init.py -v`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/templates/init/claude-skill-kb-publish.md src/center_kb/templates/init/copilot-kb-publish.prompt.md src/center_kb/initcmd.py tests/test_init.py
git commit -m "feat: kb init scaffolds /kb-publish slash command (Claude skill + Copilot prompt)"
```

---

### Task 3: CLI reference in QUICKSTART + Copilot instructions

**Files:**
- Modify: `src/center_kb/templates/init/QUICKSTART.md`
- Modify: `src/center_kb/templates/init/copilot-kb-summarize.instructions.md`
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: `init_repo` from `center_kb.initcmd`; existing template content (do not change existing sections — append only).
- Produces: a `## CLI reference` section in both rendered files; QUICKSTART step 2 mentions `/kb-ingest`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_init.py`:

```python
def test_quickstart_and_instructions_have_cli_reference(tmp_path: Path):
    init_repo(tmp_path)
    quick = (tmp_path / "QUICKSTART.md").read_text(encoding="utf-8")
    instr = (
        tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    ).read_text(encoding="utf-8")
    for text in (quick, instr):
        assert "## CLI reference" in text
        # every kb command appears
        for cmd in (
            "kb init", "kb ingest", "kb summarize", "kb status", "kb build",
            "kb query", "kb get", "kb stats", "kb diff", "kb approve",
            "kb publish", "kb resolve", "kb doctor",
        ):
            assert cmd in text, cmd
    assert "/kb-ingest" in quick
    assert "/kb-publish" in quick
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_init.py::test_quickstart_and_instructions_have_cli_reference -v`
Expected: FAIL — `AssertionError` on `"## CLI reference" in text`.

- [ ] **Step 3: Append the CLI reference to QUICKSTART.md and mention the slash commands**

In `src/center_kb/templates/init/QUICKSTART.md`, change step 2's second line to mention the slash command, so the step reads:

```markdown
2. **Ingest the first document** — put the PDF in `source/`, then:
   `kb ingest source/my-doc.pdf --id my-doc --tags "tag1,tag2"`
   In Claude Code or Copilot Chat, prefer the `/kb-ingest` slash command —
   it asks for the id/tags/revision so you don't have to remember flags.
   (needs the ingest extra: `pip install "center-kb[ingest]"` — or run it
   inside Docker: `docker compose run --rm hub kb ingest source/my-doc.pdf --id my-doc`)
```

Then append this section at the end of the file:

```markdown

## CLI reference

- `kb init` — scaffold a KB repo (this skeleton)
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (in Claude Code / Copilot Chat: `/kb-ingest`)
- `kb summarize` — fill pending summaries via a headless LLM CLI
- `kb status` — list docs and their pending sections
- `kb build` — validate the KB (manifests, tables, tokens)
- `kb query "<question>"` — BM25 search over the summaries
- `kb get <doc> <section> [--level l1|l2|l3]` — read one section
- `kb stats` — token counts per level
- `kb diff <doc> --against <rev>` — changed sections vs a git rev
- `kb approve <doc> --section <id>` — mark sections reviewed
  (in Claude Code / Copilot Chat: `/kb-publish` runs diff → approve → publish)
- `kb publish --hub <hub>` — push the L0+L1 snapshot to the federation hub
- `kb resolve <file>` — resolve a kb-context block and check freshness
- `kb doctor` — sanity-check the setup
```

- [ ] **Step 4: Append the same CLI reference to the Copilot instructions template**

Append to `src/center_kb/templates/init/copilot-kb-summarize.instructions.md` (at the end of the file):

```markdown

## CLI reference

- `kb init` — scaffold a KB repo
- `kb ingest <pdf> --id <id>` — parse a PDF into `.kb/` sections
  (prefer the `/kb-ingest` prompt in Copilot Chat)
- `kb summarize` — fill pending summaries via a headless LLM CLI
- `kb status` — list docs and their pending sections
- `kb build` — validate the KB (manifests, tables, tokens)
- `kb query "<question>"` — BM25 search over the summaries
- `kb get <doc> <section> [--level l1|l2|l3]` — read one section
- `kb stats` — token counts per level
- `kb diff <doc> --against <rev>` — changed sections vs a git rev
- `kb approve <doc> --section <id>` — mark sections reviewed
  (prefer the `/kb-publish` prompt in Copilot Chat)
- `kb publish --hub <hub>` — push the L0+L1 snapshot to the federation hub
- `kb resolve <file>` — resolve a kb-context block and check freshness
- `kb doctor` — sanity-check the setup
```

- [ ] **Step 5: Run the whole init suite**

Run: `.venv/bin/python -m pytest tests/test_init.py -v`
Expected: ALL PASS — note `test_quickstart_uses_correct_ingest_flag` still passes (`--id` present, `--doc-id` absent).

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/QUICKSTART.md src/center_kb/templates/init/copilot-kb-summarize.instructions.md tests/test_init.py
git commit -m "docs: CLI reference in QUICKSTART + Copilot instructions templates"
```

---

### Task 4: Dogfood — install the new files into this repo, full test run

**Files:**
- Create: `.claude/skills/kb-ingest/SKILL.md` (copy of template)
- Create: `.claude/skills/kb-publish/SKILL.md` (copy of template)
- Create: `.github/prompts/kb-ingest.prompt.md` (copy of template)
- Create: `.github/prompts/kb-publish.prompt.md` (copy of template)

**Interfaces:**
- Consumes: the four template files from Tasks 1–2 (canonical source — spec decision #9: repo copies must be byte-identical to `templates/init/`).
- Produces: working `/kb-ingest` and `/kb-publish` slash commands in this repo's Claude Code and Copilot sessions.

- [ ] **Step 1: Copy the rendered files from the canonical templates**

```bash
mkdir -p .claude/skills/kb-ingest .claude/skills/kb-publish .github/prompts
cp src/center_kb/templates/init/claude-skill-kb-ingest.md .claude/skills/kb-ingest/SKILL.md
cp src/center_kb/templates/init/claude-skill-kb-publish.md .claude/skills/kb-publish/SKILL.md
cp src/center_kb/templates/init/copilot-kb-ingest.prompt.md .github/prompts/kb-ingest.prompt.md
cp src/center_kb/templates/init/copilot-kb-publish.prompt.md .github/prompts/kb-publish.prompt.md
```

- [ ] **Step 2: Verify the copies are byte-identical to the templates**

```bash
diff src/center_kb/templates/init/claude-skill-kb-ingest.md .claude/skills/kb-ingest/SKILL.md
diff src/center_kb/templates/init/claude-skill-kb-publish.md .claude/skills/kb-publish/SKILL.md
diff src/center_kb/templates/init/copilot-kb-ingest.prompt.md .github/prompts/kb-ingest.prompt.md
diff src/center_kb/templates/init/copilot-kb-publish.prompt.md .github/prompts/kb-publish.prompt.md
```

Expected: no output from any `diff` (identical).

- [ ] **Step 3: Run the FULL test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: ALL PASS (no regressions anywhere, not just test_init).

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/kb-ingest/SKILL.md .claude/skills/kb-publish/SKILL.md .github/prompts/kb-ingest.prompt.md .github/prompts/kb-publish.prompt.md
git commit -m "feat: dogfood /kb-ingest + /kb-publish slash commands in this repo"
```

---

## Out of scope (from the spec)

- Renaming this repo's `sources/` → `source/`.
- Skills for `kb resolve` / `kb context new` (consumer side of federation).
- Wrapping the remaining 8 CLI commands as slash commands.
- Any `kb` CLI behavior change.
