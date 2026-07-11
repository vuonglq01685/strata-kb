# Summarize Quality Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three root causes that make L2 summaries bloat past L3 (tables leaking into prompts, forced non-empty summaries for table-only sections, unenforced length target) and add `kb summarize --redo` to re-run existing KBs.

**Architecture:** All engine changes live in `src/center_kb/summarize.py` (input stripping, deterministic table-only path, char-budget guard, redo reset) plus one CLI flag in `src/center_kb/cli.py`. Template updates keep the manual path consistent. No `.kb/` format change.

**Tech Stack:** Python 3.13, Typer, pytest. Existing test files: `tests/test_summarize.py` (unit), `tests/test_summarize_cli.py`, `tests/test_summarize_e2e.py` (stub CLI).

**Spec:** `docs/superpowers/specs/2026-07-11-summarize-quality-design.md`

## Global Constraints

- LLM call budget per section stays ≤ 2 (1 try + 1 retry), as today.
- Table lines are lines whose `lstrip()` starts with `|` (same convention as `mdutils.extract_tables`).
- Table placeholder string is exactly `[table omitted]`.
- Char budget formula is exactly `max(300, int(0.35 * len(prose)))`.
- Deterministic L1 for table-only sections is exactly `f"Table-only section: {title}."`; deterministic L2 is the empty string `""`.
- Marker format is `<!-- TODO:summarize {section_id} -->` (existing).
- `--redo` resets BOTH `summarized` and `reviewed` sections to `pending` (warn with the reviewed count), clears `summary`, and rebuilds L2 files (headings + table blocks kept, prose replaced by markers).
- Existing tests must stay green: `.venv/bin/python -m pytest tests/ -q` from `/Users/vuonglq01685/Documents/Projects/AERO-KB`.
- Commit style: conventional commits, no attribution footer.

---

### Task 1: `strip_tables` + prose-only prompt input + `table_only` flag

**Files:**
- Modify: `src/center_kb/summarize.py` (imports, `PendingSection`, `collect_pending`, new helpers)
- Test: `tests/test_summarize.py`

**Interfaces:**
- Consumes: `mdutils.slice_section` (existing), `PendingSection` (existing frozen dataclass).
- Produces: `strip_tables(text: str) -> str`; `PendingSection` gains field `table_only: bool = False`; `collect_pending` now yields `l3_body` WITHOUT table lines (each table block replaced by `[table omitted]`). Tasks 2–3 rely on `section.table_only` and prose-only `section.l3_body`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_summarize.py`:

```python
from center_kb.summarize import strip_tables


def test_strip_tables_replaces_block_with_placeholder():
    text = "intro line\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\noutro line"
    out = strip_tables(text)
    assert "| a | b |" not in out
    assert out.count("[table omitted]") == 1
    assert "intro line" in out and "outro line" in out


def test_strip_tables_multiple_blocks_and_edges():
    text = "| t1 |\n| x |\nprose between\n| t2 |\n| y |"
    out = strip_tables(text)
    assert out.count("[table omitted]") == 2
    assert "prose between" in out
    assert "| t1 |" not in out and "| y |" not in out


def test_strip_tables_no_tables_is_identity_modulo_whitespace():
    text = "just prose\n\nmore prose"
    assert strip_tables(text) == text


def test_collect_pending_strips_tables_and_flags_table_only(tmp_path):
    kb = tmp_path / ".kb"
    (kb / "doc1").mkdir(parents=True)
    (kb / "index.yaml").write_text(
        "docs:\n- id: doc1\n  title: Doc One\n", encoding="utf-8"
    )
    raw = (
        "## 1 Prose Section\n\nSome prose here.\n\n| h |\n|---|\n| v |\n\n"
        "## 2 Table Only\n\n| h2 |\n|----|\n| v2 |\n"
    )
    (kb / "doc1" / "f1.raw.md").write_text(raw, encoding="utf-8")
    (kb / "doc1" / "_manifest.yaml").write_text(
        "id: doc1\ntitle: Doc One\nrevision: ''\n"
        "ingested: 2026-07-11\nsource_sha256: ''\n"
        "ingest: {chapter_pattern: x, appendix_pattern: y}\n"
        "sections:\n"
        "- {id: '1', title: Prose Section, file: f1, status: pending}\n"
        "- {id: '2', title: Table Only, file: f1, status: pending}\n",
        encoding="utf-8",
    )
    pending = collect_pending(kb)
    by_id = {p.section_id: p for p in pending}
    assert "| h |" not in by_id["1"].l3_body
    assert "[table omitted]" in by_id["1"].l3_body
    assert "Some prose here." in by_id["1"].l3_body
    assert by_id["1"].table_only is False
    assert by_id["2"].table_only is True
```

(`collect_pending` is already imported at the top of the file; keep existing imports.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -v -k "strip_tables or table_only"`
Expected: FAIL — `ImportError: cannot import name 'strip_tables'`.

- [ ] **Step 3: Implement**

In `src/center_kb/summarize.py`, add near the top (after imports; add `import re`):

```python
TABLE_PLACEHOLDER = "[table omitted]"

_IGNORABLE_LINE_RE = re.compile(
    r"^(#{1,6} .*|" + re.escape(TABLE_PLACEHOLDER) + r"|\s*)$"
)


def strip_tables(text: str) -> str:
    """Replace each contiguous table block with the placeholder.

    A table line is any line whose lstrip() starts with '|' (same
    convention as mdutils.extract_tables).
    """
    out: list[str] = []
    in_table = False
    for line in text.splitlines():
        if line.lstrip().startswith("|"):
            if not in_table:
                out.append(TABLE_PLACEHOLDER)
                in_table = True
            continue
        in_table = False
        out.append(line)
    return "\n".join(out).strip()


def _is_table_only(prose: str) -> bool:
    """True when nothing but headings, placeholders and blanks remain."""
    return all(_IGNORABLE_LINE_RE.match(line) for line in prose.splitlines())
```

Change `PendingSection`:

```python
@dataclass(frozen=True)
class PendingSection:
    doc_id: str
    section_id: str
    title: str
    file: str  # stem without extension
    l3_body: str  # prose only — tables replaced by TABLE_PLACEHOLDER
    table_only: bool = False
```

In `collect_pending`, replace the two lines that build `body` and append:

```python
            body = slice_section(raw_cache[sec.file], sec.id) or ""
            prose = strip_tables(body)
            out.append(
                PendingSection(
                    entry.id, sec.id, sec.title, sec.file, prose,
                    table_only=_is_table_only(prose),
                )
            )
```

- [ ] **Step 4: Run the summarize test files**

Run: `.venv/bin/python -m pytest tests/test_summarize.py tests/test_summarize_cli.py tests/test_summarize_e2e.py -q`
Expected: ALL PASS. (Existing tests feed prose-only fixtures, so stripping is a no-op for them; if an existing fixture asserts table text inside a prompt, that assertion must now be updated to expect the placeholder — report any such change in the commit message body.)

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/summarize.py tests/test_summarize.py
git commit -m "feat: strip tables from summarize prompt input, flag table-only sections"
```

---

### Task 2: deterministic path for table-only sections (no LLM call)

**Files:**
- Modify: `src/center_kb/summarize.py` (`_summarize_one`)
- Test: `tests/test_summarize.py`

**Interfaces:**
- Consumes: `PendingSection.table_only` from Task 1; `replace_marker` (existing — replacing with `""` is valid).
- Produces: `_summarize_one(runner, section)` returns `{"l2_summary": "", "l1_summary": f"Table-only section: {section.title}."}` WITHOUT calling `runner.run` when `section.table_only` is True.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_summarize.py`:

```python
from center_kb.summarize import PendingSection, _summarize_one


class _ExplodingRunner:
    name = "exploding"

    def run(self, prompt: str) -> str:  # pragma: no cover - must not be called
        raise AssertionError("runner.run must not be called for table-only sections")


def test_table_only_section_skips_llm():
    sec = PendingSection(
        "doc1", "2", "Table Only", "f1", "[table omitted]", table_only=True
    )
    result = _summarize_one(_ExplodingRunner(), sec)
    assert result == {
        "l2_summary": "",
        "l1_summary": "Table-only section: Table Only.",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_summarize.py::test_table_only_section_skips_llm -v`
Expected: FAIL — `AssertionError: runner.run must not be called...` (or JSON parse error), because `_summarize_one` currently always calls the runner.

- [ ] **Step 3: Implement**

At the top of `_summarize_one`, before building the prompt:

```python
def _summarize_one(runner, section: PendingSection) -> dict[str, str]:
    if section.table_only:
        return {
            "l2_summary": "",
            "l1_summary": f"Table-only section: {section.title}.",
        }
    ...  # existing body unchanged (Task 3 rewrites the rest)
```

Note: `_apply_results` already handles an empty `l2_summary` — `replace_marker` substitutes `""` for the marker, leaving the heading + tables. No change needed there.

- [ ] **Step 4: Run the summarize test file**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -q`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/summarize.py tests/test_summarize.py
git commit -m "feat: table-only sections skip the LLM — empty L2, deterministic L1"
```

---

### Task 3: char budget in prompt + length guard + strict retry

**Files:**
- Modify: `src/center_kb/summarize.py` (`SECTION_PROMPT`, `build_section_prompt`, `_summarize_one`, new `_max_chars`)
- Test: `tests/test_summarize.py`

**Interfaces:**
- Consumes: prose-only `l3_body` (Task 1), table-only early return (Task 2).
- Produces: `_max_chars(prose: str) -> int` = `max(300, int(0.35 * len(prose)))`; `build_section_prompt(section)` embeds the budget; `_summarize_one` rejects `l2_summary` longer than the budget, retries once with a stricter prompt, then raises `RunnerError`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_summarize.py`:

```python
import json

import pytest

from center_kb.llm import RunnerError
from center_kb.summarize import _max_chars, build_section_prompt


def _prose_section(prose: str) -> PendingSection:
    return PendingSection("doc1", "1", "Prose", "f1", prose, table_only=False)


def test_max_chars_floor_and_ratio():
    assert _max_chars("x" * 100) == 300          # floor wins
    assert _max_chars("x" * 2000) == 700         # 0.35 ratio wins


def test_prompt_contains_budget_and_table_rules():
    sec = _prose_section("p" * 2000)
    prompt = build_section_prompt(sec)
    assert "at most 700 characters" in prompt
    assert "[table omitted]" in prompt           # rule mentions the marker
    assert "Never describe, list, or reconstruct table contents" in prompt


class _ScriptedRunner:
    """Returns queued replies; records prompts."""

    name = "scripted"

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def _reply(l2: str) -> str:
    return json.dumps({"l2_summary": l2, "l1_summary": "One line."})


def test_length_guard_passes_short_reply():
    runner = _ScriptedRunner([_reply("short summary")])
    result = _summarize_one(runner, _prose_section("p" * 2000))
    assert result["l2_summary"] == "short summary"
    assert len(runner.prompts) == 1


def test_length_guard_retries_then_accepts():
    runner = _ScriptedRunner([_reply("x" * 800), _reply("y" * 100)])
    result = _summarize_one(runner, _prose_section("p" * 2000))  # limit 700
    assert result["l2_summary"] == "y" * 100
    assert len(runner.prompts) == 2
    assert "over the 700-character hard limit" in runner.prompts[1]


def test_length_guard_fails_after_two_long_replies():
    runner = _ScriptedRunner([_reply("x" * 800), _reply("z" * 800)])
    with pytest.raises(RunnerError, match="too long"):
        _summarize_one(runner, _prose_section("p" * 2000))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -v -k "max_chars or budget or length_guard"`
Expected: FAIL — `ImportError: cannot import name '_max_chars'`.

- [ ] **Step 3: Implement**

Replace `SECTION_PROMPT` with:

```python
SECTION_PROMPT = """You are filling in summaries for a knowledge-base section.

Section {section_id} — {title}

The source below is prose only — tables were removed and replaced with
[table omitted] markers. The tables are preserved verbatim elsewhere; they
are NOT your concern.

<source>
{l3_body}
</source>

Write two summaries of the source text, following ALL rules:
- Write in English.
- l2_summary: condense the prose to ~20-30% of the original length, keep the \
logical structure. HARD LIMIT: l2_summary must be at most {max_chars} \
characters — if your draft is longer, compress harder before replying.
- Never describe, list, or reconstruct table contents; ignore \
[table omitted] markers entirely.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...), \
numeric values, units, cross-references (§x.y). Never paraphrase technical terms.
- Do not invent anything that is not in the source. When unsure, keep the \
original sentence.
- l1_summary: one sentence, max 25 words, stating what the section covers and \
what kind of data it contains.

Reply with ONLY a JSON object, no markdown fences, no commentary:
{{"l2_summary": "...", "l1_summary": "..."}}"""
```

Add and rewrite:

```python
def _max_chars(prose: str) -> int:
    return max(300, int(0.35 * len(prose)))


def build_section_prompt(section: PendingSection) -> str:
    return SECTION_PROMPT.format(
        section_id=section.section_id,
        title=section.title,
        l3_body=section.l3_body,
        max_chars=_max_chars(section.l3_body),
    )


def _summarize_one(runner, section: PendingSection) -> dict[str, str]:
    if section.table_only:
        return {
            "l2_summary": "",
            "l1_summary": f"Table-only section: {section.title}.",
        }
    limit = _max_chars(section.l3_body)
    prompt = build_section_prompt(section)
    last: Exception | None = None
    for _ in range(2):  # 1 try + exactly 1 retry (spec §3.3)
        try:
            reply = parse_json_reply(
                runner.run(prompt), ("l2_summary", "l1_summary")
            )
        except (RunnerError, ValueError) as exc:
            last = exc
            continue
        if len(reply["l2_summary"]) <= limit:
            return reply
        last = ValueError(
            f"l2_summary too long: {len(reply['l2_summary'])} chars"
            f" > limit {limit}"
        )
        prompt = (
            build_section_prompt(section)
            + f"\n\nYour previous l2_summary was {len(reply['l2_summary'])}"
            f" characters — over the {limit}-character hard limit."
            " Reply again, compressed to fit."
        )
    raise RunnerError(str(last))
```

- [ ] **Step 4: Run all summarize tests**

Run: `.venv/bin/python -m pytest tests/test_summarize.py tests/test_summarize_cli.py tests/test_summarize_e2e.py -q`
Expected: ALL PASS. If an existing test's stub reply now trips the length guard (reply longer than 35% of its fixture prose), extend that fixture's prose or shorten the stub reply — report the adjustment in the commit body.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/summarize.py tests/test_summarize.py
git commit -m "feat: explicit char budget in summarize prompt + length guard with strict retry"
```

---

### Task 4: `kb summarize --redo` — rebuild L2 scaffold + reset manifest

**Files:**
- Modify: `src/center_kb/summarize.py` (new `rebuild_l2_scaffold`, `RedoReport`, `redo_reset`)
- Modify: `src/center_kb/cli.py` (`summarize` command — add `--redo`)
- Test: `tests/test_summarize.py`, `tests/test_summarize_cli.py`

**Interfaces:**
- Consumes: `models.Manifest` / `models.KBIndex` (existing), marker format `<!-- TODO:summarize {sid} -->`.
- Produces: `rebuild_l2_scaffold(l2_text: str) -> str`; `redo_reset(kb_dir: Path, doc_id: str | None = None) -> RedoReport` with `reset: list[str]` ("doc/section") and `reviewed_reset: int`; CLI flag `kb summarize --redo`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_summarize.py`:

```python
from center_kb.summarize import rebuild_l2_scaffold, redo_reset


L2_WITH_SUMMARIES = (
    "## 1 Prose Section\n\nAn old summary paragraph.\nSecond line of it.\n\n"
    "| h |\n|---|\n| v |\n\n"
    "## 2 Table Only\n\n| h2 |\n|----|\n| v2 |\n"
)


def test_rebuild_l2_scaffold_restores_markers_keeps_tables():
    out = rebuild_l2_scaffold(L2_WITH_SUMMARIES)
    assert "<!-- TODO:summarize 1 -->" in out
    assert "<!-- TODO:summarize 2 -->" in out
    assert "An old summary paragraph." not in out
    assert "| h |" in out and "| v2 |" in out
    # headings preserved
    assert "## 1 Prose Section" in out and "## 2 Table Only" in out


def test_rebuild_l2_scaffold_is_idempotent():
    once = rebuild_l2_scaffold(L2_WITH_SUMMARIES)
    assert rebuild_l2_scaffold(once) == once


def test_redo_reset_flips_statuses_and_rewrites_l2(tmp_path):
    kb = tmp_path / ".kb"
    (kb / "doc1").mkdir(parents=True)
    (kb / "index.yaml").write_text(
        "docs:\n- id: doc1\n  title: Doc One\n", encoding="utf-8"
    )
    (kb / "doc1" / "f1.md").write_text(L2_WITH_SUMMARIES, encoding="utf-8")
    (kb / "doc1" / "_manifest.yaml").write_text(
        "id: doc1\ntitle: Doc One\nrevision: ''\n"
        "ingested: 2026-07-11\nsource_sha256: ''\n"
        "ingest: {chapter_pattern: x, appendix_pattern: y}\n"
        "sections:\n"
        "- {id: '1', title: Prose Section, file: f1, status: summarized, summary: old}\n"
        "- {id: '2', title: Table Only, file: f1, status: reviewed, summary: old2}\n",
        encoding="utf-8",
    )
    report = redo_reset(kb)
    assert sorted(report.reset) == ["doc1/1", "doc1/2"]
    assert report.reviewed_reset == 1
    manifest_text = (kb / "doc1" / "_manifest.yaml").read_text(encoding="utf-8")
    assert "summarized" not in manifest_text and "reviewed" not in manifest_text
    l2 = (kb / "doc1" / "f1.md").read_text(encoding="utf-8")
    assert "<!-- TODO:summarize 1 -->" in l2
    assert "An old summary paragraph." not in l2
```

Append to `tests/test_summarize_cli.py` (it already has a stubbed-runner/CliRunner setup — follow the file's existing fixture pattern for invoking `kb summarize`; the essential new assertions):

```python
def test_summarize_redo_flag_resets_then_summarizes(tmp_path, ...):
    # Arrange a KB whose sections are already 'summarized' (reuse the file's
    # existing KB fixture, then flip statuses to summarized in the manifest).
    # Act: invoke ["summarize", "--redo", "--kb-dir", str(kb_dir)] with the
    # file's stub runner.
    # Assert: output contains "redo:" and the run summarizes the sections
    # again (report line "N summarized, 0 failed.").
```

(The implementer writes this test concretely against the file's existing fixtures — the fixture names are visible in `tests/test_summarize_cli.py`; do not invent new stub infrastructure.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -v -k "rebuild_l2 or redo_reset"`
Expected: FAIL — `ImportError: cannot import name 'rebuild_l2_scaffold'`.

- [ ] **Step 3: Implement in summarize.py**

```python
_SECTION_HEAD_RE = re.compile(r"^## (?P<sid>\S+)(\s|$)")


def rebuild_l2_scaffold(l2_text: str) -> str:
    """Rebuild the pre-summarize L2 scaffold from a filled L2 file.

    Keeps `## <id> <title>` headings and table blocks; every section's
    prose (old summaries, leftover markers) is replaced by its marker.
    Deterministic and idempotent — used by `kb summarize --redo`.
    """
    out: list[str] = []
    for line in l2_text.splitlines():
        m = _SECTION_HEAD_RE.match(line)
        if m:
            out += [line, "", f"<!-- TODO:summarize {m.group('sid')} -->", ""]
            continue
        if line.lstrip().startswith("|"):
            out.append(line)
            continue
        if line.strip() == "" and out and out[-1].lstrip().startswith("|"):
            out.append("")  # keep the single blank that closes a table block
        # anything else is prose/old summary/old marker -> dropped
    return "\n".join(out)


@dataclass
class RedoReport:
    reset: list[str] = field(default_factory=list)  # "doc-id/section-id"
    reviewed_reset: int = 0


def redo_reset(kb_dir: Path, doc_id: str | None = None) -> RedoReport:
    """Reset summarized/reviewed sections to pending and restore L2 markers."""
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    report = RedoReport()
    for entry in index.docs:
        if doc_id and entry.id != doc_id:
            continue
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        stems: set[str] = set()
        for sec in manifest.sections:
            if sec.status == "reviewed":
                report.reviewed_reset += 1
            if sec.status != "pending":
                report.reset.append(f"{entry.id}/{sec.id}")
            sec.status = "pending"
            sec.summary = ""
            stems.add(sec.file)
        for stem in stems:
            path = kb_dir / entry.id / f"{stem}.md"
            if path.exists():
                path.write_text(
                    rebuild_l2_scaffold(path.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )
        models.save_yaml_model(manifest_path, manifest)
    return report
```

- [ ] **Step 4: Wire the CLI flag**

In `src/center_kb/cli.py`, `summarize` command — add the option and the pre-run reset (after the index-exists check, before `_run_summarize`):

```python
    redo: bool = typer.Option(
        False,
        "--redo",
        help="Reset summarized/reviewed sections to pending (restoring L2 "
        "markers) and re-summarize from scratch",
    ),
```

```python
    if redo:
        from center_kb.summarize import redo_reset

        rr = redo_reset(kb_dir, doc_id or None)
        typer.echo(f"redo: {len(rr.reset)} section(s) reset to pending")
        if rr.reviewed_reset:
            typer.secho(
                f"[warn] {rr.reviewed_reset} reviewed section(s) were reset",
                fg=typer.colors.YELLOW,
            )
```

- [ ] **Step 5: Run all summarize + CLI tests**

Run: `.venv/bin/python -m pytest tests/test_summarize.py tests/test_summarize_cli.py tests/test_summarize_e2e.py -q`
Expected: ALL PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/summarize.py src/center_kb/cli.py tests/test_summarize.py tests/test_summarize_cli.py
git commit -m "feat: kb summarize --redo — rebuild L2 markers and reset manifests"
```

---

### Task 5: manual-path templates aligned with the new rules

**Files:**
- Modify: `src/center_kb/templates/init/claude-skill-kb-summarize.md`
- Modify: `src/center_kb/templates/init/copilot-kb-summarize.instructions.md`
- Re-sync: `.claude/skills/kb-summarize/SKILL.md` (byte-identical copy of the template)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: existing template content (Writing rules sections).
- Produces: both templates carry the new rules; existing test markers (`VERBATIM`, `25 words`, `applyTo: ".kb/**"`, `name: kb-summarize`, `kb build`) survive.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_init.py`:

```python
def test_kb_summarize_templates_have_prose_only_rules(tmp_path: Path):
    init_repo(tmp_path)
    skill = (
        tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    ).read_text(encoding="utf-8")
    instr = (
        tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    ).read_text(encoding="utf-8")
    for text in (skill, instr):
        assert "Summarize the prose ONLY" in text
        assert "Table-only section:" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_init.py::test_kb_summarize_templates_have_prose_only_rules -v`
Expected: FAIL on the `"Summarize the prose ONLY"` assertion.

- [ ] **Step 3: Edit the Claude skill template**

In `src/center_kb/templates/init/claude-skill-kb-summarize.md`, in the "## Writing rules (mandatory)" list, insert after the first bullet (`- Write in **English**.`):

```markdown
- Summarize the prose ONLY. Never describe, list, or reconstruct table
  contents — the tables are already copied verbatim into the section.
- If a section has no prose (heading + tables only): delete the marker
  line (leave nothing) and set the manifest `summary` to
  `Table-only section: <title>.` — do NOT invent prose about the tables.
- Keep the L2 paragraph under ~35% of the original prose length. If your
  draft is longer, compress harder.
```

- [ ] **Step 4: Edit the Copilot instructions template**

In `src/center_kb/templates/init/copilot-kb-summarize.instructions.md`, in "## Writing rules (mandatory)", insert the same three bullets after `- Write in English.` (unbolded "English" — match the file's existing style).

- [ ] **Step 5: Re-sync the dogfood copy and verify**

```bash
cp src/center_kb/templates/init/claude-skill-kb-summarize.md .claude/skills/kb-summarize/SKILL.md
diff src/center_kb/templates/init/claude-skill-kb-summarize.md .claude/skills/kb-summarize/SKILL.md
```

Expected: empty diff.

- [ ] **Step 6: Run the init test file**

Run: `.venv/bin/python -m pytest tests/test_init.py -q`
Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/templates/init/claude-skill-kb-summarize.md src/center_kb/templates/init/copilot-kb-summarize.instructions.md .claude/skills/kb-summarize/SKILL.md tests/test_init.py
git commit -m "docs: kb-summarize templates — prose-only rules, table-only sections, 35% cap"
```

---

### Task 6: full suite + operational re-run on CENTER-KB (controller-run)

**Files:** none in this repo (operational).

- [ ] **Step 1: Full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: ALL PASS.

- [ ] **Step 2 (controller, NOT a subagent):** capture before-stats, then re-run the real KB:

```bash
cd /Users/vuonglq01685/Documents/Projects/CENTER-KB
/Users/vuonglq01685/Documents/Projects/AERO-KB/.venv/bin/kb stats   # before
/Users/vuonglq01685/Documents/Projects/AERO-KB/.venv/bin/kb summarize --redo arinc-424
/Users/vuonglq01685/Documents/Projects/AERO-KB/.venv/bin/kb build
/Users/vuonglq01685/Documents/Projects/AERO-KB/.venv/bin/kb stats   # after
```

Verify first that the venv `kb` is an editable install (`pip show center-kb` → editable); if not, `pip install -e /Users/vuonglq01685/Documents/Projects/AERO-KB` first. Expected: saving improves from 17% to ≥50% (table-heavy ceiling ~20–25% applies per-file for ch4/ch6-class files; doc-wide the prose-dominated files pull the average up). Long-running (449 sections, 5 workers) — run in background.

---

## Out of scope (from the spec)

- Changing the copy-tables-verbatim L2 design.
- Summarizing table contents in any form.
- Model/effort default changes.
