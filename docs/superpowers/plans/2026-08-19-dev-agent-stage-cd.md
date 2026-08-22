# Phase 5 Stages C+D — curated service knowledge (`dev-code-seed`, `kb svc note`) and closing the BA loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the generated structure a meaning layer. **Stage C:** a `dev-code-seed` skill that bootstraps `.kb/<repo_id>-svc/` for a project already in flight — LLM drafts each service's responsibility from deterministic code evidence, a human corrects it, `kb approve` gates it — plus `kb svc note` to accrue ticket↔service history at every handover. **Stage D:** teach the eight BA wrappers to read both code-knowledge documents, so `ba-ticket-author` and `ba-mission-plan` can fill all four arguments of `Container(alias, label, technology, description)` and stop emitting `%%TODO%%` over knowledge the hub now holds.

**Architecture:** No new engine. Stage C reuses `summarize.collect_pending()` / `summarize_kb()` / `review.approve_sections()` **unmodified** — `--scaffold-svc` (Stage B) already wrote `pending` sections whose L3 holds the code evidence, which is exactly the shape those functions expect for a domain document. The only new code is one CLI sub-app (`kb svc note`) that appends to `hist.*` sections. Stage D is template text plus tests.

**Tech Stack:** Python 3.11+, Typer, stdlib `re`, PyYAML, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-08-19-dev-agent-design.md`

**Prerequisites:** `2026-08-19-dev-agent-stage-a.md` and `2026-08-19-dev-agent-stage-b.md` complete and released. **Order is mandatory** (spec §14): Stage C needs the normalised `svc.<name>` ids the `services` extractor produces, and Stage D needs content from both B and C.

## Global Constraints

Copied verbatim from the spec; every task's requirements implicitly include this section.

- **Five MCP tools, unchanged.** `tests-gate/golden/mcp_tools.json` byte-identical; `tests-gate/regression/test_mcp_contract.py` green untouched (spec §3.1).
- **`models.py` is frozen** (spec §3.3); **`build.py` is frozen** (spec §3.7); **`summarize.py` and `review.py` are frozen** — Stage C reuses them as they are. If a change to either looks necessary, stop and raise it: the whole design rests on that reuse.
- **The curated document is the only place an LLM authors published content** (spec §3.6), and it must reach `reviewed` before it can publish.
- **`<repo>-svc` never sources a standard value** (spec §3.10) — responsibility text is for locating and cross-checking work; codes, formats, enums, and thresholds come verbatim from a pinned domain section.
- **`hist.*` is written only by `kb svc note`**, never by hand, and carries `status: summarized` so it cannot block `kb build`.
- **Never publish `pending` knowledge.** `kb build --allow-pending` is for the middle of a seed only.
- Hermetic tests: no network, no live hub, **no real LLM** — the summarize step is exercised with a stub runner.
- Windows dev box: `uv run pytest`; `uv run ruff check <touched files>` only.
- Estimated effort: C1 ≈ 1 d, C2 ≈ 0.75 d, C3 ≈ 0.5 d, D1 ≈ 0.75 d, D2 ≈ 0.5 d — **≈ 3.5 dev-days** (spec §14 range 2.5–3.5).

## File Structure

| File | Responsibility |
|---|---|
| `src/center_kb/templates/init/claude-skill-dev-code-seed.md` + 3 siblings | the one-time bootstrap skill |
| `src/center_kb/svcnote.py` | `add_note()` — parse, upsert, re-render `hist.*` |
| `src/center_kb/cli.py` | `svc` sub-app with the `note` command |
| `src/center_kb/initcmd.py` | `DEV_TEMPLATES` gains `dev-code-seed` + the reused summarize/approve/publish rows |
| `src/center_kb/templates/init/*dev-handover*`, `*dev-plan*`, `*dev-execute*` | drop the Stage-A interim fallbacks |
| `src/center_kb/templates/init/*ba-ticket-author*`, `*ba-mission-plan*` | Stage D: read code knowledge |
| `tests/test_svcnote.py` | the new command |
| `tests/test_devcodeseed.py` | the seed round-trip with a stub LLM runner |

---

## Task C1: `dev-code-seed` wrappers + the reused authoring wrappers on kind `dev`

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-dev-code-seed.md`
- Create: `src/center_kb/templates/init/claude-command-dev-code-seed.md`
- Create: `src/center_kb/templates/init/copilot-dev-code-seed.prompt.md`
- Create: `src/center_kb/templates/init/cursor-dev-code-seed.md`
- Modify: `src/center_kb/initcmd.py` (`DEV_TEMPLATES`)
- Modify: `tests/test_templates.py`
- Modify: `tests/test_init.py`
- Create: `tests/test_devcodeseed.py`

**Interfaces:**
- Consumes: `kb code-ingest --scaffold-svc` (Stage B Task B8), `summarize.collect_pending`/`summarize_kb`, `review.approve_sections`, `kb publish`.
- Produces: the `/dev-code-seed` entry point, and the twelve reused wrapper rows on kind `dev`.

- [ ] **Step 1: Write the failing template test**

Append to `tests/test_templates.py`:

```python
def _dev_code_seed_names() -> tuple[str, ...]:
    return (
        "claude-skill-dev-code-seed.md",
        "claude-command-dev-code-seed.md",
        "copilot-dev-code-seed.prompt.md",
        "cursor-dev-code-seed.md",
    )


def test_dev_code_seed_templates_exist_as_package_resources():
    base = resources.files("center_kb").joinpath("templates/init")
    for name in _dev_code_seed_names():
        assert base.joinpath(name).is_file(), name


def test_dev_code_seed_carries_the_seven_steps():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        for step in ("Preflight", "Extract", "Draft", "Review", "Approve",
                     "Flows", "Validate and publish"):
            assert step in text, f"{name} missing step {step}"


def test_dev_code_seed_uses_the_existing_commands_unchanged():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "kb code-ingest --scaffold-svc" in text, name
        assert "kb summarize" in text, name
        assert "kb approve" in text, name
        assert "kb publish" in text, name


def test_dev_code_seed_carries_the_draft_is_a_draft_rule():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "The LLM draft is a **draft**" in text, name
        assert "approving it unread defeats the gate" in text, name


def test_dev_code_seed_forbids_publishing_pending_and_warns_about_redo():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "never publish `pending` knowledge" in text, name
        assert "--redo" in text, name
        assert "resets the **whole** document" in text, name


def test_dev_code_seed_never_edits_the_generated_document():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "Never edit `-code`" in text, name


def test_dev_code_seed_ends_with_the_next_step_block():
    for name in _dev_code_seed_names():
        text = _read_init_template(name)
        assert "## Next step" in text, name
        assert "State:" in text, name


def test_claude_skill_dev_code_seed_has_expected_frontmatter():
    text = _read_init_template("claude-skill-dev-code-seed.md")
    assert "name: dev-code-seed\n" in text


def test_copilot_dev_code_seed_prompt_has_agent_mode():
    assert "mode: agent" in _read_init_template("copilot-dev-code-seed.prompt.md")
```

Append to `tests/test_init.py`:

```python
def test_init_kind_dev_scaffolds_dev_code_seed_and_the_reused_wrappers(tmp_path: Path):
    init_repo(tmp_path, "dev")
    assert (tmp_path / ".claude" / "skills" / "dev-code-seed" / "SKILL.md").is_file()
    assert (tmp_path / ".claude" / "commands" / "dev-code-seed.md").is_file()
    assert (tmp_path / ".github" / "prompts" / "dev-code-seed.prompt.md").is_file()
    assert (tmp_path / ".cursor" / "commands" / "dev-code-seed.md").is_file()
    # reused authoring wrappers the seed flow needs
    for name in ("kb-summarize", "kb-approve"):
        assert (tmp_path / ".claude" / "skills" / name / "SKILL.md").is_file(), name
        assert (tmp_path / ".claude" / "commands" / f"{name}.md").is_file(), name
        assert (tmp_path / ".cursor" / "commands" / f"{name}.md").is_file(), name
    assert (tmp_path / ".claude" / "skills" / "kb-publish" / "SKILL.md").is_file()
    assert (tmp_path / ".cursor" / "commands" / "kb-publish.md").is_file()
    assert (tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md").is_file()
    assert (tmp_path / ".cursor" / "rules" / "kb-summarize.mdc").is_file()


def test_init_kind_dev_still_excludes_ingest_and_the_child_publish_workflow(tmp_path: Path):
    init_repo(tmp_path, "dev")
    assert not (tmp_path / ".claude" / "skills" / "kb-ingest").exists()
    assert not (tmp_path / ".claude" / "skills" / "kb-docker-setup").exists()
    assert not (tmp_path / ".github" / "workflows" / "kb-publish.yml").exists()
    assert not (tmp_path / "source").exists()
    # kb-publish has no Claude command file anywhere in the package
    assert not (tmp_path / ".claude" / "commands" / "kb-publish.md").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k dev_code_seed tests/test_init.py -k dev_code_seed -v`
Expected: FAIL — missing resource `claude-skill-dev-code-seed.md`.

- [ ] **Step 3: Write the four wrappers**

Claude skill frontmatter:

```markdown
---
name: dev-code-seed
description: Bootstrap curated service knowledge for a repo adopting center-kb — extract structure, let the LLM draft each service's responsibility from code evidence, correct it, approve it, and publish. One-time per repo. Use when onboarding a project into the KB, or when invoked as /dev-code-seed.
---
```

Body, per spec §10, seven steps:

1. **Preflight** — confirm `.kb/config.yaml` has `hub:`, `repo_id:`, `intake:`; confirm the repo is allowlisted in the hub's `federation/registry.yaml` (or tell the Dev to request it); warn if the tree is dirty.
2. **Extract** — `kb code-ingest --scaffold-svc`. Report sections per extractor. On exit 1 (nothing but `tree` detected), **stop** and explain which artifact kinds were searched — a configuration problem (missing `--db` path, no compose file), never a reason to hand-write knowledge.
3. **Draft** — `kb summarize <repo_id>-svc`. State why the doc-id argument matters: it keeps the LLM off `-code`, which must stay deterministic.
4. **Review — the actual work, and it is a human's** — walk the drafted `svc.*` one at a time, showing each draft L2 beside its L3 code evidence, and ask the Dev to correct it. Say plainly that a draft may be wrong and that **approving it unread defeats the gate**. Where a responsibility derives from a standard, cite `doc-id §section` from the domain KB — never restate the rule from the draft.
5. **Approve** — `kb approve <repo_id>-svc` (or `--section <id>` for a subset), only for sections the Dev confirmed.
6. **Flows (optional)** — add `flow.<name>` sections for business flows crossing several services, when the Dev can describe them. Skipped freely: a missing flow beats a guessed one.
7. **Validate and publish** — `kb build` **without** `--allow-pending` must pass; anything still `pending` is either approved or removed. Then commit and `kb publish --pr` for BA/architect review on the hub.

Then the hard-rules block verbatim:

```markdown
## Hard rules

- The LLM draft is a **draft**. Never approve a section the Dev has not read and corrected — approving it unread defeats the gate.
- A responsibility that touches a standard cites `doc-id §section` from the domain KB. Never restate a rule from the draft as if it were the standard.
- Never invent a service, table, or flow the extractors did not find and the Dev did not confirm.
- `kb build --allow-pending` is for the middle of a seed only — never publish `pending` knowledge.
- Unsure about a service's responsibility → leave it `pending` and record an owned open question. A blank is honest; a guess is not.
- Never edit `-code`: it is regenerated and overwritten on the next merge.
- Never run `kb summarize --redo` to fix one service. It resets the **whole** document, `reviewed` sections included, and rebuilds every L2 from scaffold. Amend by hand.
```

Add the counterpart line (*"Counterpart in the superpowers plugin: none — this is center-kb's own onboarding flow"*), the note that `kb build` has no `--doc-id` so any `pending` section committed to the default branch fails CI **by design**, and the shared next-step block from the Stage A plan (option 1 after a successful seed = `kb publish --pr`).

Claude command file: the 2-line invoker shape, `description:` naming the one-time bootstrap. Copilot (`mode: agent`) and Cursor (`name: dev-code-seed`) variants with CLI-only paths.

- [ ] **Step 4: Register the rows on kind `dev`**

In `src/center_kb/initcmd.py`, extend `DEV_TEMPLATES` with `dev-code-seed`'s four rows (reuse the comprehension by adding `"dev-code-seed"` to the skill tuple) and the twelve reused rows — paths copied exactly from `COMMON_TEMPLATES` so both maps resolve to the same resources:

```python
    ".claude/skills/kb-summarize/SKILL.md": "claude-skill-kb-summarize.md",
    ".claude/commands/kb-summarize.md": "claude-command-kb-summarize.md",
    ".github/instructions/kb-summarize.instructions.md": "copilot-kb-summarize.instructions.md",
    ".cursor/commands/kb-summarize.md": "cursor-kb-summarize.md",
    ".cursor/rules/kb-summarize.mdc": "cursor-kb-summarize.mdc",
    ".claude/skills/kb-approve/SKILL.md": "claude-skill-kb-approve.md",
    ".claude/commands/kb-approve.md": "claude-command-kb-approve.md",
    ".github/prompts/kb-approve.prompt.md": "copilot-kb-approve.prompt.md",
    ".cursor/commands/kb-approve.md": "cursor-kb-approve.md",
    ".claude/skills/kb-publish/SKILL.md": "claude-skill-kb-publish.md",
    ".github/prompts/kb-publish.prompt.md": "copilot-kb-publish.prompt.md",
    ".cursor/commands/kb-publish.md": "cursor-kb-publish.md",
```

Note in a comment that `kb-publish` has **no** `.claude/commands/` resource in the package (verified: `COMMON_TEMPLATES` has none), so the dev map must not invent one.

- [ ] **Step 5: Write the seed round-trip test with a stub LLM runner**

Create `tests/test_devcodeseed.py` — this proves the reuse claim, which is the load-bearing assertion of Stage C:

```python
from pathlib import Path

from center_kb import models, review, summarize
from center_kb.build import build_kb
from center_kb.codeingest import core
from tests.fixtures_coderepo import build_code_repo


class _StubRunner:
    """Stands in for the LLM CLI: returns the JSON shape summarize expects."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, prompt: str) -> str:
        self.calls.append(prompt)
        return '{"summary": "Drafted responsibility for this service.", ' \
               '"l2": "Drafted responsibility for this service."}'


def _seed(tmp_path: Path) -> Path:
    root = build_code_repo(tmp_path)
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code",
            repo_id="demo", scaffold_svc=True,
        )
    )
    return root


def test_scaffolded_svc_sections_are_pending_and_visible_to_summarize(tmp_path):
    root = _seed(tmp_path)
    pending = summarize.collect_pending(root / ".kb", "demo-svc")
    assert pending
    assert all(p.doc_id == "demo-svc" for p in pending)


def test_the_prompt_material_is_the_l3_code_evidence(tmp_path):
    root = _seed(tmp_path)
    pending = summarize.collect_pending(root / ".kb", "demo-svc")
    section = next(p for p in pending if p.section_id == "svc.airspace-service")
    prompt = summarize.build_section_prompt(section)
    assert "airspace" in prompt.lower()


def test_summarize_then_approve_reaches_reviewed_and_builds_clean(tmp_path, monkeypatch):
    root = _seed(tmp_path)
    kb = root / ".kb"
    monkeypatch.setattr(summarize, "resolve_runner", lambda *a, **k: _StubRunner())
    summarize.summarize_kb(kb, doc_id="demo-svc")
    manifest_path = kb / "demo-svc" / "_manifest.yaml"
    assert all(
        s.status == "summarized" and s.summary
        for s in models.load_yaml_model(manifest_path, models.Manifest).sections
    )
    review.approve_sections(kb, "demo-svc", [])
    assert all(
        s.status == "reviewed"
        for s in models.load_yaml_model(manifest_path, models.Manifest).sections
    )
    assert build_kb(kb).ok


def test_summarize_leaves_the_generated_document_untouched(tmp_path, monkeypatch):
    root = _seed(tmp_path)
    kb = root / ".kb"
    before = {p.name: p.read_bytes() for p in sorted((kb / "demo-code").iterdir())}
    monkeypatch.setattr(summarize, "resolve_runner", lambda *a, **k: _StubRunner())
    summarize.summarize_kb(kb, doc_id="demo-svc")
    after = {p.name: p.read_bytes() for p in sorted((kb / "demo-code").iterdir())}
    assert after == before
```

Before writing this test, read `src/center_kb/summarize.py` to confirm the runner-resolution function's real name and the exact JSON keys `parse_json_reply` requires, and adjust the stub and the `monkeypatch.setattr` target to match. Do **not** change `summarize.py` to fit the test.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_devcodeseed.py tests/test_templates.py tests/test_init.py -v`
Expected: PASS.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/center_kb/initcmd.py tests/test_devcodeseed.py tests/test_templates.py tests/test_init.py
git add src/center_kb/templates/init/*dev-code-seed* src/center_kb/initcmd.py \
        tests/test_devcodeseed.py tests/test_templates.py tests/test_init.py
git commit -m "feat: dev-code-seed skill + reused summarize/approve/publish wrappers on kind dev (phase 5C)"
```

---

## Task C2: `kb svc note` — append-only ticket↔service history

**Files:**
- Create: `src/center_kb/svcnote.py`
- Modify: `src/center_kb/cli.py` (`svc` sub-app + `note` command)
- Create: `tests/test_svcnote.py`

**Interfaces:**
- Consumes: `models` (`Manifest`, `SectionEntry`, `KBIndex`), `mdutils.slice_section`, and the `-code` document (to validate the service exists).
- Produces:

```python
@dataclass(frozen=True)
class Note:
    ticket: str
    title: str
    refs: tuple[str, ...]

@dataclass
class SvcNoteReport:
    doc_id: str
    section_id: str
    action: str          # "created" | "added" | "updated"
    notes: int

class SvcNoteError(Exception): ...

def add_note(kb_dir: Path, repo_id: str, service: str, note: Note) -> SvcNoteReport: ...
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_svcnote.py`:

```python
from pathlib import Path

import pytest
from typer.testing import CliRunner

from center_kb import models, svcnote
from center_kb.build import build_kb
from center_kb.cli import app
from center_kb.codeingest import core
from tests.fixtures_coderepo import build_code_repo

runner = CliRunner()


@pytest.fixture
def seeded(tmp_path: Path) -> Path:
    root = build_code_repo(tmp_path)
    core.run(
        core.CodeIngestOptions(
            repo_root=root, kb_dir=root / ".kb", doc_id="demo-code",
            repo_id="demo", scaffold_svc=True,
        )
    )
    (root / ".kb" / "config.yaml").write_text(
        'kind: dev\nhub: ""\nrepo_id: "demo"\nintake: ""\n', encoding="utf-8"
    )
    return root


def _note(ticket="M-airspace-US4", title="Approve time-bound airspace",
          refs=("ATM-STD §5.3", "ATM-STD §5.7")) -> svcnote.Note:
    return svcnote.Note(ticket=ticket, title=title, refs=refs)


def test_creates_the_hist_section_on_first_note(seeded):
    report = svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    assert report.section_id == "hist.airspace-service"
    assert report.action == "created"
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert "## hist.airspace-service" in l2
    assert "M-airspace-US4" in l2
    assert "ATM-STD §5.3" in l2


def test_hist_section_is_summarized_so_build_stays_clean(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    manifest = models.load_yaml_model(
        seeded / ".kb" / "demo-svc" / "_manifest.yaml", models.Manifest
    )
    hist = next(s for s in manifest.sections if s.id == "hist.airspace-service")
    assert hist.status == "summarized"
    assert hist.summary
    # the svc.* sections are still pending, so strict build fails on THOSE only
    strict = build_kb(seeded / ".kb")
    assert all("hist." not in e for e in strict.errors)
    assert build_kb(seeded / ".kb", allow_pending=True).ok


def test_second_note_for_a_different_ticket_appends(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    report = svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(ticket="M-notify-US2", title="Notify on change", refs=("ATM-STD §9.1",)),
    )
    assert report.action == "added"
    assert report.notes == 2
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert "M-airspace-US4" in l2 and "M-notify-US2" in l2


def test_rerunning_the_same_ticket_updates_instead_of_duplicating(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    report = svcnote.add_note(
        seeded / ".kb", "demo", "airspace-service",
        _note(title="Approve time-bound airspace (revised)"),
    )
    assert report.action == "updated"
    assert report.notes == 1
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert l2.count("M-airspace-US4") == 1
    assert "(revised)" in l2


def test_rows_are_sorted_by_ticket_id(seeded):
    for ticket in ("M-zulu-US1", "M-alpha-US1", "M-mike-US1"):
        svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note(ticket=ticket))
    l2 = (seeded / ".kb" / "demo-svc" / "history.md").read_text(encoding="utf-8")
    assert l2.index("M-alpha-US1") < l2.index("M-mike-US1") < l2.index("M-zulu-US1")


def test_l3_has_no_pipe_table(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    l3 = (seeded / ".kb" / "demo-svc" / "history.raw.md").read_text(encoding="utf-8")
    assert "|" not in l3
    assert "```" in l3


def test_unknown_service_is_rejected(seeded):
    with pytest.raises(svcnote.SvcNoteError) as exc:
        svcnote.add_note(seeded / ".kb", "demo", "airspce-service", _note())
    assert "airspce-service" in str(exc.value)


def test_never_touches_the_svc_responsibility_sections(seeded):
    svc_l2 = seeded / ".kb" / "demo-svc" / "services.md"
    before = svc_l2.read_bytes()
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    assert svc_l2.read_bytes() == before


def test_two_identical_runs_are_byte_identical(seeded):
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    hist = seeded / ".kb" / "demo-svc" / "history.md"
    first = hist.read_bytes()
    svcnote.add_note(seeded / ".kb", "demo", "airspace-service", _note())
    assert hist.read_bytes() == first


def test_cli_svc_note_happy_path(seeded):
    result = runner.invoke(app, [
        "svc", "note", "airspace-service",
        "--kb-dir", str(seeded / ".kb"),
        "--ticket", "M-airspace-US4",
        "--title", "Approve time-bound airspace",
        "--refs", "ATM-STD §5.3, ATM-STD §5.7",
    ])
    assert result.exit_code == 0, result.output
    assert "hist.airspace-service" in result.output


def test_cli_svc_note_json_output(seeded):
    result = runner.invoke(app, [
        "svc", "note", "airspace-service",
        "--kb-dir", str(seeded / ".kb"),
        "--ticket", "M-airspace-US4", "--title", "T", "--refs", "D §1",
        "--json",
    ])
    assert result.exit_code == 0, result.output
    import json

    payload = json.loads(result.output)
    assert payload["section_id"] == "hist.airspace-service"
    assert payload["action"] == "created"


def test_cli_svc_note_unknown_service_exits_1(seeded):
    result = runner.invoke(app, [
        "svc", "note", "nope",
        "--kb-dir", str(seeded / ".kb"),
        "--ticket", "T-1", "--title", "T", "--refs", "D §1",
    ])
    assert result.exit_code == 1
    assert "nope" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_svcnote.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.svcnote'`.

- [ ] **Step 3: Write `svcnote.py`**

Create `src/center_kb/svcnote.py`:

- `ROW_RE = re.compile(r"^\|\s*(?P<ticket>[^|]+?)\s*\|\s*(?P<title>[^|]*?)\s*\|\s*(?P<refs>[^|]*?)\s*\|\s*$", re.M)` — used to parse existing rows back out of the L2 table so the operation is idempotent without a sidecar store.
- `add_note(kb_dir, repo_id, service, note)`:
  1. `svc_doc = kb_dir / f"{repo_id}-svc"`; raise `SvcNoteError` when it does not exist, naming `kb code-ingest --scaffold-svc` as the fix.
  2. Validate the service: the `-code` manifest (`kb_dir / f"{repo_id}-code" / "_manifest.yaml"`) must contain `svc.<service>`. Otherwise raise `SvcNoteError(f"unknown service '{service}' — no svc.{service} section in {repo_id}-code")`. A typo must not invent a service.
  3. Read `history.md` when present and parse existing rows for `hist.<service>` via `slice_section` + `ROW_RE`, skipping the header and separator rows.
  4. Upsert into a dict keyed by ticket; `action` is `"created"` when the section is new, `"updated"` when the ticket already had a row, `"added"` otherwise.
  5. Re-render **all** rows sorted by ticket id.
  6. **L2** body: the pipe table `| Ticket | Title | Domain refs |` with its separator row, refs joined with `", "`.
  7. **L3** body: a fenced block, one stanza per ticket (`ticket: …` / `title: …` / `refs: …` lines) — no pipe table anywhere, so the table-integrity invariant is satisfied by construction.
  8. Upsert the `SectionEntry`: `id=f"hist.{service}"`, `title=f"{service} — ticket history"`, `status="summarized"`, `summary=f"Tickets that touched {service}: {n} recorded."`, `file="history"`.
  9. Preserve every other section in the manifest untouched, and re-emit the other groups' files unchanged (only `history.md` / `history.raw.md` are rewritten).
  10. Write with `encoding="utf-8", newline="\n"`.

- [ ] **Step 4: Add the `svc` sub-app to the CLI**

In `src/center_kb/cli.py`, next to the existing sub-app declarations (`context_app`, `assets_app`, `ticket_app`, `mission_app`):

```python
svc_app = typer.Typer(help="Service knowledge: record which tickets touched which service.")
app.add_typer(svc_app, name="svc")
```

and the command:

```python
@svc_app.command("note")
def svc_note(
    service: str = typer.Argument(..., help="Service name, as in svc.<name> of <repo_id>-code"),
    ticket: str = typer.Option(..., "--ticket", help="Ticket / US id"),
    title: str = typer.Option(..., "--title", help="Ticket title"),
    refs: str = typer.Option("", "--refs", help="Domain refs, comma-separated"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    repo_id: str = typer.Option("", "--repo-id", help="Repo ID (default: config)"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable report"),
) -> None:
    """Append a ticket to <repo_id>-svc §hist.<service>. Idempotent per ticket."""
```

Body: resolve `repo_id` with `config.effective_repo_id`; split `refs` on commas and strip; build `svcnote.Note`; call `add_note`; catch `SvcNoteError` → red message + `raise typer.Exit(1)`; print the report or `json.dumps(asdict(report), indent=2)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_svcnote.py -v`
Expected: PASS (12 tests).

- [ ] **Step 6: Confirm the MCP tool count did not move**

Run: `uv run pytest tests-gate/regression/test_mcp_contract.py -v`
Expected: PASS — still exactly 5 tools. A CLI sub-app must never add an MCP tool (spec §3.1).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check src/center_kb/svcnote.py src/center_kb/cli.py tests/test_svcnote.py
git add src/center_kb/svcnote.py src/center_kb/cli.py tests/test_svcnote.py
git commit -m "feat: kb svc note — idempotent ticket<->service history in hist.* sections (phase 5C)"
```

---

## Task C3: retire the Stage-A interim fallbacks

**Files:**
- Modify: `src/center_kb/templates/init/*dev-handover*` (4 files)
- Modify: `src/center_kb/templates/init/*dev-plan*` (4 files)
- Modify: `src/center_kb/templates/init/*dev-execute*` (4 files)
- Modify: `tests/test_templates.py`

**Interfaces:**
- Consumes: `kb svc note` (C2) and the `cmd.*` sections (Stage B Task B5).
- Produces: wrappers with no interim language — the workflow now uses the real commands.

Stage A shipped two deliberate fallbacks because B and C did not exist yet: `dev-plan`/`dev-execute` asked the Dev for the test command, and `dev-handover` skipped `kb svc note` with a PR note. Both are now obsolete and must be removed, or the workflow will keep telling Devs to do the manual thing.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_dev_wrappers_no_longer_carry_the_stage_a_interim_fallbacks():
    for skill in ("dev-plan", "dev-execute", "dev-handover"):
        for name in _dev_wrapper_names(skill):
            text = _read_init_template(name)
            assert "until Stage B" not in text, name
            assert "until Stage C" not in text, name
            assert "this command does not exist yet" not in text, name


def test_dev_plan_and_execute_read_cmd_sections_as_the_primary_source():
    for skill in ("dev-plan", "dev-execute"):
        for name in _dev_wrapper_names(skill):
            text = _read_init_template(name)
            assert "cmd.test" in text, name
            assert "cmd.lint" in text, name


def test_dev_handover_runs_svc_note_unconditionally():
    for name in _dev_wrapper_names("dev-handover"):
        text = _read_init_template(name)
        assert "kb svc note" in text, name
        assert "skip the step" not in text, name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k interim -v` and `-k "cmd_sections or svc_note_unconditionally"`
Expected: FAIL — the Stage-A interim sentences are still present.

- [ ] **Step 3: Edit the twelve wrappers**

- `dev-plan`: delete the "until Stage B ships there is no `cmd.*` section" paragraph; keep the instruction to take build/test/lint commands from `-code §cmd.*` and add one sentence: if `kb_search` finds no `cmd.*` section, that is a signal the repo has not published code knowledge yet — say so and ask the Dev for the commands once, recording them at the top of the plan file. (This keeps the workflow usable on a repo whose CI has not run, without describing it as a temporary state.)
- `dev-execute`: same treatment on the verify sub-step.
- `dev-handover`: delete the "skip the step and say so" sentence; the `kb svc note` call is now unconditional, one invocation per service touched.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_templates.py -v`
Expected: PASS — including every Stage A assertion, which must stay green.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check tests/test_templates.py
git add src/center_kb/templates/init/*dev-plan* src/center_kb/templates/init/*dev-execute* \
        src/center_kb/templates/init/*dev-handover* tests/test_templates.py
git commit -m "refactor: retire the Stage-A interim fallbacks now that cmd.* and kb svc note exist (phase 5C)"
```

---

## Task D1: the eight BA wrappers read code knowledge

**Files:**
- Modify: `src/center_kb/templates/init/claude-skill-ba-ticket-author.md`
- Modify: `src/center_kb/templates/init/claude-command-ba-ticket-author.md`
- Modify: `src/center_kb/templates/init/copilot-ba-ticket-author.prompt.md`
- Modify: `src/center_kb/templates/init/cursor-ba-ticket-author.md`
- Modify: `src/center_kb/templates/init/claude-skill-ba-mission-plan.md`
- Modify: `src/center_kb/templates/init/claude-command-ba-mission-plan.md`
- Modify: `src/center_kb/templates/init/copilot-ba-mission-plan.prompt.md`
- Modify: `src/center_kb/templates/init/cursor-ba-mission-plan.md`
- Modify: `tests/test_templates.py`

**Interfaces:**
- Consumes: the `-code` and `-svc` documents on the hub (Stages B and C).
- Produces: BA wrappers that fill all four `Container(...)` arguments. No code changes; `kb ticket lint` and `kb mission lint` are untouched.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
BA_WRAPPERS = (
    "claude-skill-ba-ticket-author.md",
    "claude-command-ba-ticket-author.md",
    "copilot-ba-ticket-author.prompt.md",
    "cursor-ba-ticket-author.md",
    "claude-skill-ba-mission-plan.md",
    "claude-command-ba-mission-plan.md",
    "copilot-ba-mission-plan.prompt.md",
    "cursor-ba-mission-plan.md",
)


def test_ba_wrappers_prefer_code_knowledge_for_names_and_meaning():
    for name in BA_WRAPPERS:
        text = _read_init_template(name)
        assert "-code" in text, name
        assert "-svc" in text, name


def test_ba_wrappers_explain_the_division_of_the_two_documents():
    for name in BA_WRAPPERS:
        text = _read_init_template(name)
        assert "for names" in text, name
        assert "for meaning" in text, name


def test_ba_wrappers_only_fall_back_to_the_placeholder_when_neither_answers():
    for name in BA_WRAPPERS:
        text = _read_init_template(name)
        assert "%%TODO: verify against codebase%%" in text, name
        assert "neither document answers" in text, name


def test_ba_mission_wrappers_fill_all_four_container_arguments():
    for name in ("claude-skill-ba-mission-plan.md", "claude-command-ba-mission-plan.md",
                 "copilot-ba-mission-plan.prompt.md", "cursor-ba-mission-plan.md"):
        text = _read_init_template(name)
        assert "Container(alias, label, technology, description)" in text, name
        assert "Rel(" in text, name


def test_ba_wrappers_keep_svc_out_of_acceptance_criteria():
    for name in BA_WRAPPERS:
        text = _read_init_template(name)
        assert "never substitutes for a domain citation" in text, name


def test_ba_wrappers_still_carry_their_pre_phase5_rules():
    """Stage D adds; it must not remove anything Phase 4/4.1 established."""
    for name in ("claude-skill-ba-ticket-author.md", "claude-skill-ba-mission-plan.md"):
        text = _read_init_template(name)
        assert "kb_context_new" in text, name
        assert "Maturity review" in text, name
        assert "Never fabricate" in text or "never invent" in text.lower(), name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -k ba_wrappers -v`
Expected: FAIL on the first four tests; `test_ba_wrappers_still_carry_their_pre_phase5_rules` should already PASS (it is the regression guard).

- [ ] **Step 3: Edit the eight wrappers**

Insert this block next to the existing "never fabricate … service names" hard rule (`claude-skill-ba-mission-plan.md:118-120` and the equivalent spot in each sibling). Same wording in all eight so the tests hold:

```markdown
- **Ground code detail in the hub's code knowledge before reaching for a
  placeholder.** Two documents per product repo answer different questions:
  - `<repo>-code` **for names** — service/container names (`svc.*`), table
    names (`db.*`), endpoints (`api.*`), and detected technology
    (a `svc.<name>` table row, not `dep.*` — `dep.*` is repo-wide
    ecosystem detection, unrelated to any one container's technology).
  - `<repo>-svc` **for meaning** — what a container is responsible for
    (`svc.*`), and which services a business flow crosses (`flow.*`).

  Together they fill all four arguments of
  `Container(alias, label, technology, description)`: alias, label and
  technology from `-code`, description from `-svc`. Use `-svc` the same way
  for `Rel(...)` labels instead of leaving them empty.

  Write `%%TODO: verify against codebase%%` only when **neither document
  answers** — and then the existing rule stands: one owned row in
  `## Technology decisions`.

  `-svc` responsibility text grounds a diagram; it **never substitutes for a
  domain citation** in an Acceptance Criterion. Standard values stay verbatim
  from a pinned domain section.
```

In each file's Ground step, add one sentence: search results tagged `code` come from these generated/curated documents — present them alongside domain candidates, and note that a `-code` section is machine-extracted (trust it for names) while a `-svc` section is human-reviewed (trust it for responsibility).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_templates.py -v`
Expected: PASS, with every pre-existing BA assertion still green.

- [ ] **Step 5: Confirm the BA lint gates did not move**

Run: `uv run pytest tests/test_ticketlint.py tests/test_missionlint.py -q`
Expected: PASS unchanged — Stage D is wrapper text only; no lint rule was added.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check tests/test_templates.py
git add src/center_kb/templates/init/*ba-ticket-author* src/center_kb/templates/init/*ba-mission-plan* \
        tests/test_templates.py
git commit -m "feat: BA wrappers ground diagrams in <repo>-code and <repo>-svc (phase 5D)"
```

---

## Task D2: docs, QUICKSTART updates, release

**Files:**
- Modify: `src/center_kb/templates/init/QUICKSTART-dev.md`
- Modify: `src/center_kb/templates/init/QUICKSTART-ba.md`
- Modify: `README.md`
- Modify: `pyproject.toml`
- Modify: `tests/test_init.py`

**Interfaces:**
- Consumes: everything in Stages A–D.
- Produces: the released minor version that completes Phase 5.

- [ ] **Step 1: Write the failing docs test**

Append to `tests/test_init.py`:

```python
def test_quickstart_dev_documents_the_seed_and_service_history(tmp_path: Path):
    init_repo(tmp_path, "dev")
    text = (tmp_path / "QUICKSTART-DEV.md").read_text(encoding="utf-8")
    assert "/dev-code-seed" in text
    assert "kb svc note" in text
    assert "-code" in text and "-svc" in text
    assert "auto-merge" in text
    assert "10-15 min" in text or "10–15 min" in text


def test_quickstart_ba_points_at_code_knowledge(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = (tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8")
    assert "-code" in text
    assert "-svc" in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_init.py -k quickstart -v`
Expected: FAIL — the new strings are absent.

- [ ] **Step 3: Update `QUICKSTART-dev.md`**

Add two sections:

- **Onboarding an existing project (once)** — the seven-step seed: `/dev-code-seed`, what the LLM draft is and is not, the honest time cost (**10–15 min per service**), that `kb build` must be clean before publishing, and that the hub PR is reviewed by a BA/architect. State the hub-side policy split: `-code` PRs **may** be auto-merged by hub policy; `-svc` PRs are **never** auto-merged.
- **Keeping it current** — `kb-code.yml` republishes `-code` on every merge automatically; `kb svc note` records ticket history at handover automatically; a `stale-risk` line in a `kb code-ingest` report means a `reviewed` responsibility may no longer match the code — amend that section by hand, and never use `kb summarize --redo` for one service.

- [ ] **Step 4: Update `QUICKSTART-ba.md`**

Add a short "Code knowledge on the hub" section: `<repo>-code` for names, `<repo>-svc` for responsibilities and flows; both appear in `kb_search` results tagged `code`; use them to fill C4 container technology and description and `Rel(...)` labels, and only write `%%TODO: verify against codebase%%` when neither answers. One sentence of caution: `-svc` grounds diagrams but never replaces a domain citation in an AC.

- [ ] **Step 5: Update README**

Add: `kb svc note` to the CLI reference; the `dev-code-seed` flow in the kind-`dev` section; the full section-id prefix ownership table from spec §6.2 including `flow.*` and `hist.*`; the two-document division with the three reasons they are separate (overwrite-vs-accumulate, `pending`-vs-clean-build, auto-merge-vs-review); and the operational checklist from spec §14 (registry allowlist, auto-merge policy, the two env vars, the seed budget).

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Confirm nothing froze or drifted**

```bash
git status --short tests-gate/
uv run pytest tests-gate/regression/test_mcp_contract.py -q
```
Expected: empty output; PASS with exactly 5 tools.

- [ ] **Step 8: Bump the version and commit**

In `pyproject.toml`, bump the minor version (`0.17.0` → `0.18.0`).

```bash
git add src/center_kb/templates/init/QUICKSTART-dev.md \
        src/center_kb/templates/init/QUICKSTART-ba.md \
        README.md pyproject.toml tests/test_init.py
git commit -m "docs: curated service knowledge + BA code-knowledge grounding; chore: bump to 0.18.0"
```

---

## Self-review notes (spec coverage for Stages C+D)

| Spec section | Covered by |
|---|---|
| §3.6 curated document is LLM-drafted, human-gated | C1 Steps 3, 5 |
| §3.10 `-svc` never sources a standard value | C1 Step 3 hard rules, D1 Step 3, D1 test `keep_svc_out_of_acceptance_criteria` |
| §6.2 `flow.*` and `hist.*` prefix ownership | C2 Step 3, D2 Step 5 |
| §9 `kb svc note` contract (idempotent, sorted, no L3 pipe table, unknown service exits 1) | C2 |
| §10 `dev-code-seed` seven steps + hard rules | C1 |
| §10 the free build gate | C1 Step 3 (documented), C2 test `hist_section_is_summarized…` |
| §12 BA wrappers read code knowledge | D1 |
| §13 testing rows for Stage C/D | C1 Step 5, C2 Step 1, D1 Step 1, D2 Step 1 |
| §14 rollout + operational prerequisites | D2 |

**Reuse is the load-bearing claim of Stage C** and it is asserted, not assumed: C1 Step 5 proves `collect_pending` / `build_section_prompt` / `summarize_kb` / `approve_sections` work on the scaffolded `-svc` document **unmodified**, and that summarizing `-svc` leaves `-code` byte-identical. If any of those tests can only be made to pass by editing `summarize.py` or `review.py`, stop — that is a spec-level finding (spec §3.6 depends on the reuse), not a licence to change frozen modules.

**Two follow-ons deliberately not in this plan** (spec §15): `kb summarize --redo --section <id>` for per-section amends, and `kb code-ingest --check` for detecting hand-edited generated files.
