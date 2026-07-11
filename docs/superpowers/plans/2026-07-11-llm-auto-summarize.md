# LLM Auto-Summarize + AI-Integration Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb ingest` auto-fills L1/L2 summaries by calling a headless LLM CLI (claude → copilot fallback, max 5 parallel workers), plus `kb init` ships the Claude skill and Copilot instructions (English) to target repos.

**Architecture:** kb orchestrates, the LLM only generates text: each pending section becomes one headless subprocess call returning JSON `{l2_summary, l1_summary}`; kb validates and writes files itself (marker replacement + manifest flip on the main thread — no locks needed). New modules `llm.py` (runner detection/adapters) and `summarize.py` (orchestrator); new CLI command `kb summarize`; ingest gains `--no-summarize` / `--llm`.

**Tech Stack:** Python 3.10+, typer, pydantic, PyYAML, `concurrent.futures.ThreadPoolExecutor`, `subprocess`. Tests: pytest + `typer.testing.CliRunner`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-11-llm-auto-summarize-design.md`

## Global Constraints

- All scaffolded/template content (SKILL.md, Copilot instructions, prompts) is **English**.
- LLM config defaults (spec §3.4): `runner: auto`, `model: sonnet-5`, `effort: high`, `max_workers: 5`, `timeout: 300` (seconds per section).
- Section fail (timeout / bad JSON after exactly 1 retry) → stays `pending`, warning printed; `kb ingest` still exits 0; `kb summarize` exits 1 if any section remains failed/pending.
- No runner found → guidance message, sections stay pending, `kb ingest` exit 0.
- LLM must never edit files — kb owns all writes; tables live outside the `<!-- TODO:summarize <id> -->` marker and must be untouched.
- Existing `index.yaml` files without an `llm:` block must keep loading (pydantic default).
- Tests must be hermetic: no test may ever invoke a real `claude`/`copilot` binary (dev machines have them installed!). Every ingest-CLI test passes `--llm none` or monkeypatches detection; subprocess tests use stub scripts in a temp PATH.
- Run tests with the project venv: `.venv/bin/python -m pytest …` (repo uses python 3.13 venv).
- Commit format: `<type>: <description>`, no attribution footer.

---

### Task 1: `LLMConfig` model + init index template

**Files:**
- Modify: `src/center_kb/models.py` (KBIndex is at line ~50)
- Modify: `src/center_kb/templates/init/index.yaml` (currently just `docs: []`)
- Test: `tests/test_models.py` (append)

**Interfaces:**
- Produces: `models.LLMConfig` (fields: `runner: Literal["auto","claude","copilot","none"]="auto"`, `model: str="sonnet-5"`, `effort: str="high"`, `max_workers: int=5`, `timeout: int=300`) and `KBIndex.llm: LLMConfig`. All later tasks consume this.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_models.py`)

```python
def test_kbindex_without_llm_block_gets_defaults(tmp_path):
    p = tmp_path / "index.yaml"
    p.write_text("docs: []\n", encoding="utf-8")
    index = models.load_yaml_model(p, models.KBIndex)
    assert index.llm.runner == "auto"
    assert index.llm.model == "sonnet-5"
    assert index.llm.effort == "high"
    assert index.llm.max_workers == 5
    assert index.llm.timeout == 300


def test_kbindex_llm_block_roundtrip(tmp_path):
    p = tmp_path / "index.yaml"
    p.write_text(
        "docs: []\nllm:\n  runner: copilot\n  model: gpt-5\n  max_workers: 2\n",
        encoding="utf-8",
    )
    index = models.load_yaml_model(p, models.KBIndex)
    assert index.llm.runner == "copilot"
    assert index.llm.model == "gpt-5"
    assert index.llm.max_workers == 2
    models.save_yaml_model(p, index)
    assert "runner: copilot" in p.read_text(encoding="utf-8")
```

If `tests/test_models.py` does not already import `models`/`tmp_path` helpers, match its existing imports (`from center_kb import models`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_models.py -v -k llm`
Expected: FAIL — `AttributeError: ... object has no attribute 'llm'` (or pydantic ValidationError for unknown field).

- [ ] **Step 3: Implement** — in `src/center_kb/models.py`, above `KBIndex`:

```python
class LLMConfig(BaseModel):
    runner: Literal["auto", "claude", "copilot", "none"] = "auto"
    model: str = "sonnet-5"
    effort: str = "high"
    max_workers: int = 5
    timeout: int = 300


class KBIndex(BaseModel):
    docs: list[IndexEntry] = Field(default_factory=list)
    llm: LLMConfig = Field(default_factory=LLMConfig)
```

Replace `src/center_kb/templates/init/index.yaml` content with:

```yaml
docs: []
llm:
  runner: auto        # auto | claude | copilot | none
  model: sonnet-5
  effort: high
  max_workers: 5
  timeout: 300
```

- [ ] **Step 4: Run the full test suite** (init/doctor tests read the template)

Run: `.venv/bin/python -m pytest tests/ -x -q`
Expected: PASS (note: `test_init.py::test_kb_doctor_passes_on_fresh_skeleton` must still pass with the new template).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/models.py src/center_kb/templates/init/index.yaml tests/test_models.py
git commit -m "feat: LLMConfig model + llm block in index.yaml template"
```

---

### Task 2: `llm.py` — runner detection + subprocess adapters

**Files:**
- Create: `src/center_kb/llm.py`
- Test: `tests/test_llm.py` (new)

**Interfaces:**
- Consumes: `models.LLMConfig` (Task 1).
- Produces:
  - `llm.Runner` frozen dataclass: fields `name: str`, `executable: str`, `model: str`, `effort: str`, `timeout: int`; method `run(prompt: str) -> str` (returns model reply text, raises `RunnerError`).
  - `llm.RunnerError(Exception)`.
  - `llm.detect_runner(cli_choice: str | None, config: LLMConfig) -> Runner | None` — priority: cli_choice → config.runner → auto-detect claude then copilot; `"none"` or nothing installed → `None`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_llm.py`:

```python
import json
import stat
from pathlib import Path

import pytest

from center_kb import llm
from center_kb.models import LLMConfig


def make_stub(tmp_path: Path, name: str, body: str) -> str:
    """Create an executable shell script standing in for a real CLI."""
    script = tmp_path / name
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


# --- detect_runner -----------------------------------------------------------

def test_detect_prefers_claude_then_copilot(monkeypatch):
    monkeypatch.setattr(
        llm.shutil, "which",
        lambda n: f"/bin/{n}" if n in ("claude", "copilot") else None,
    )
    runner = llm.detect_runner(None, LLMConfig())
    assert runner is not None and runner.name == "claude"


def test_detect_falls_back_to_copilot(monkeypatch):
    monkeypatch.setattr(
        llm.shutil, "which", lambda n: "/bin/copilot" if n == "copilot" else None
    )
    runner = llm.detect_runner(None, LLMConfig())
    assert runner is not None and runner.name == "copilot"


def test_detect_returns_none_when_nothing_installed(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: None)
    assert llm.detect_runner(None, LLMConfig()) is None


def test_cli_choice_overrides_config(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: f"/bin/{n}")
    runner = llm.detect_runner("copilot", LLMConfig(runner="claude"))
    assert runner.name == "copilot"


def test_config_runner_none_disables():
    assert llm.detect_runner(None, LLMConfig(runner="none")) is None


def test_runner_carries_config_values(monkeypatch):
    monkeypatch.setattr(llm.shutil, "which", lambda n: f"/bin/{n}")
    cfg = LLMConfig(model="sonnet-5", effort="high", timeout=42)
    runner = llm.detect_runner("claude", cfg)
    assert (runner.model, runner.effort, runner.timeout) == ("sonnet-5", "high", 42)


# --- Runner.run --------------------------------------------------------------

def test_claude_run_unwraps_json_envelope(tmp_path):
    inner = json.dumps({"l2_summary": "x", "l1_summary": "y"})
    envelope = json.dumps({"type": "result", "result": inner})
    exe = make_stub(tmp_path, "claude", f"cat > /dev/null\necho '{envelope}'")
    runner = llm.Runner("claude", exe, "sonnet-5", "high", 30)
    assert json.loads(runner.run("prompt")) == {"l2_summary": "x", "l1_summary": "y"}


def test_copilot_run_returns_plain_stdout(tmp_path):
    exe = make_stub(tmp_path, "copilot", 'echo \'{"l2_summary": "a", "l1_summary": "b"}\'')
    runner = llm.Runner("copilot", exe, "gpt-5", "high", 30)
    assert '"l2_summary"' in runner.run("prompt")


def test_run_raises_on_nonzero_exit(tmp_path):
    exe = make_stub(tmp_path, "claude", "cat > /dev/null\nexit 3")
    runner = llm.Runner("claude", exe, "sonnet-5", "high", 30)
    with pytest.raises(llm.RunnerError):
        runner.run("prompt")


def test_run_raises_on_timeout(tmp_path):
    exe = make_stub(tmp_path, "claude", "cat > /dev/null\nsleep 5")
    runner = llm.Runner("claude", exe, "sonnet-5", "high", 1)
    with pytest.raises(llm.RunnerError):
        runner.run("prompt")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.llm'`.

- [ ] **Step 3: Implement** — create `src/center_kb/llm.py`:

```python
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass

from center_kb.models import LLMConfig

# `claude -p` has no public effort flag; a large thinking budget is the
# closest supported knob for effort=high (spec §6 — best-effort).
HIGH_EFFORT_THINKING_TOKENS = "31999"


class RunnerError(Exception):
    """LLM CLI call failed: non-zero exit, timeout, or unusable output."""


@dataclass(frozen=True)
class Runner:
    name: str  # "claude" | "copilot"
    executable: str
    model: str
    effort: str
    timeout: int

    def run(self, prompt: str) -> str:
        """One headless call; returns the model's reply text."""
        if self.name == "claude":
            # prompt via stdin: avoids ARG_MAX limits on long L3 bodies
            cmd = [self.executable, "-p", "--model", self.model,
                   "--output-format", "json"]
            stdin: str | None = prompt
        else:
            # copilot CLI takes the prompt as an argument, not stdin
            cmd = [self.executable, "-p", prompt, "--model", self.model]
            stdin = None
        env = None
        if self.name == "claude" and self.effort == "high":
            env = os.environ | {"MAX_THINKING_TOKENS": HIGH_EFFORT_THINKING_TOKENS}
        try:
            proc = subprocess.run(
                cmd, input=stdin, capture_output=True, text=True,
                timeout=self.timeout, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"{self.name}: timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            raise RunnerError(
                f"{self.name}: exit {proc.returncode}: {proc.stderr.strip()[:500]}"
            )
        return _extract_reply(self.name, proc.stdout)


def _extract_reply(name: str, stdout: str) -> str:
    if name != "claude":
        return stdout.strip()
    # claude --output-format json wraps the reply: {"type":"result","result":"…"}
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()
    if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
        return envelope["result"].strip()
    return stdout.strip()


def detect_runner(cli_choice: str | None, config: LLMConfig) -> Runner | None:
    """Resolve the runner: CLI flag > index.yaml config > auto-detect.

    Returns None when disabled ("none") or no supported CLI is installed.
    """
    choice = cli_choice or config.runner
    if choice == "none":
        return None
    candidates = [choice] if choice in ("claude", "copilot") else ["claude", "copilot"]
    for name in candidates:
        path = shutil.which(name)
        if path:
            return Runner(name=name, executable=path, model=config.model,
                          effort=config.effort, timeout=config.timeout)
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/llm.py tests/test_llm.py
git commit -m "feat: llm runner detection + claude/copilot subprocess adapters"
```

---

### Task 3: `summarize.py` — collect, prompt, parse, marker replace

**Files:**
- Create: `src/center_kb/summarize.py`
- Test: `tests/test_summarize.py` (new)

**Interfaces:**
- Consumes: `models.Manifest`/`KBIndex` (Task 1), `mdutils.slice_section(md, section_id) -> str | None`.
- Produces (Task 4/5/6 rely on these exact names):
  - `PendingSection` frozen dataclass: `doc_id: str, section_id: str, title: str, file: str, l3_body: str`.
  - `collect_pending(kb_dir: Path, doc_id: str | None = None) -> list[PendingSection]`.
  - `build_section_prompt(section: PendingSection) -> str` and `build_doc_prompt(title: str, l1_summaries: list[str]) -> str`.
  - `parse_json_reply(text: str, required: tuple[str, ...]) -> dict[str, str]` — raises `ValueError`.
  - `replace_marker(l2_text: str, section_id: str, summary: str) -> str` — raises `ValueError` if marker absent.

- [ ] **Step 1: Write the failing tests** — create `tests/test_summarize.py`:

```python
from pathlib import Path

import pytest

from center_kb import models, summarize


def make_kb(tmp_path: Path, statuses: dict[str, str]) -> Path:
    """One doc 'd1', sections 1.1/1.2 in file ch1, with given statuses."""
    kb = tmp_path / ".kb"
    doc = kb / "d1"
    doc.mkdir(parents=True)
    (doc / "ch1.raw.md").write_text(
        "## 1.1 Alpha\n\nAlpha body text §2.3 code P.\n\n"
        "## 1.2 Beta\n\nBeta body text.\n",
        encoding="utf-8",
    )
    (doc / "ch1.md").write_text(
        "## 1.1 Alpha\n\n<!-- TODO:summarize 1.1 -->\n\n"
        "| Code | Meaning |\n|---|---|\n| P | Prohibited |\n\n"
        "## 1.2 Beta\n\n<!-- TODO:summarize 1.2 -->\n",
        encoding="utf-8",
    )
    manifest = models.Manifest(
        id="d1", title="Doc One",
        sections=[
            models.SectionEntry(id="1.1", title="Alpha", file="ch1",
                                status=statuses.get("1.1", "pending")),
            models.SectionEntry(id="1.2", title="Beta", file="ch1",
                                status=statuses.get("1.2", "pending")),
        ],
    )
    models.save_yaml_model(doc / "_manifest.yaml", manifest)
    index = models.KBIndex(docs=[models.IndexEntry(id="d1", title="Doc One")])
    models.save_yaml_model(kb / "index.yaml", index)
    return kb


def test_collect_pending_returns_only_pending_with_l3_body(tmp_path):
    kb = make_kb(tmp_path, {"1.2": "summarized"})
    pending = summarize.collect_pending(kb)
    assert [p.section_id for p in pending] == ["1.1"]
    assert pending[0].doc_id == "d1"
    assert pending[0].file == "ch1"
    assert "Alpha body text" in pending[0].l3_body


def test_collect_pending_filters_by_doc_id(tmp_path):
    kb = make_kb(tmp_path, {})
    assert summarize.collect_pending(kb, doc_id="other") == []
    assert len(summarize.collect_pending(kb, doc_id="d1")) == 2


def test_section_prompt_contains_body_rules_and_json_contract(tmp_path):
    kb = make_kb(tmp_path, {})
    section = summarize.collect_pending(kb)[0]
    prompt = summarize.build_section_prompt(section)
    assert "Alpha body text" in prompt
    assert "l2_summary" in prompt and "l1_summary" in prompt
    assert "20" in prompt and "30%" in prompt  # length target
    assert "25 words" in prompt
    assert "VERBATIM" in prompt


def test_parse_json_reply_accepts_clean_and_fenced_json():
    good = '{"l2_summary": "long text", "l1_summary": "short"}'
    keys = ("l2_summary", "l1_summary")
    assert summarize.parse_json_reply(good, keys)["l1_summary"] == "short"
    fenced = f"Here you go:\n```json\n{good}\n```\nDone."
    assert summarize.parse_json_reply(fenced, keys)["l2_summary"] == "long text"


@pytest.mark.parametrize("bad", [
    "no json at all",
    '{"l2_summary": "only one key"}',
    '{"l2_summary": "", "l1_summary": "x"}',
    '{"l2_summary": 5, "l1_summary": "x"}',
])
def test_parse_json_reply_rejects_bad_replies(bad):
    with pytest.raises(ValueError):
        summarize.parse_json_reply(bad, ("l2_summary", "l1_summary"))


def test_replace_marker_replaces_only_target_and_keeps_tables(tmp_path):
    kb = make_kb(tmp_path, {})
    l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    out = summarize.replace_marker(l2, "1.1", "Condensed alpha.")
    assert "Condensed alpha." in out
    assert "<!-- TODO:summarize 1.1 -->" not in out
    assert "<!-- TODO:summarize 1.2 -->" in out          # untouched
    assert "| P | Prohibited |" in out                   # table intact


def test_replace_marker_raises_when_marker_missing():
    with pytest.raises(ValueError):
        summarize.replace_marker("## 1.1 Alpha\n\ntext\n", "1.1", "s")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.summarize'`.

- [ ] **Step 3: Implement** — create `src/center_kb/summarize.py`:

```python
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from center_kb import models
from center_kb.mdutils import slice_section

SECTION_PROMPT = """You are filling in summaries for a knowledge-base section.

Section {section_id} — {title}

<source>
{l3_body}
</source>

Write two summaries of the source text, following ALL rules:
- Write in English.
- l2_summary: condense the prose to ~20-30% of the original length, keep the \
logical structure.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...), \
numeric values, units, cross-references (§x.y). Never paraphrase technical terms.
- Do not invent anything that is not in the source. When unsure, keep the \
original sentence.
- Do not summarize, create, or delete tables (tables are handled separately).
- l1_summary: one sentence, max 25 words, stating what the section covers and \
what kind of data it contains.

Reply with ONLY a JSON object, no markdown fences, no commentary:
{{"l2_summary": "...", "l1_summary": "..."}}"""

DOC_PROMPT = """These are the one-line summaries of every section in the \
document "{title}":

{l1_lines}

Write ONE English sentence (max 30 words) summarizing what the whole document \
covers. Reply with ONLY a JSON object:
{{"summary": "..."}}"""


@dataclass(frozen=True)
class PendingSection:
    doc_id: str
    section_id: str
    title: str
    file: str  # stem without extension
    l3_body: str


def collect_pending(kb_dir: Path, doc_id: str | None = None) -> list[PendingSection]:
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    out: list[PendingSection] = []
    for entry in index.docs:
        if doc_id and entry.id != doc_id:
            continue
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        raw_cache: dict[str, str] = {}
        for sec in manifest.sections:
            if sec.status != "pending":
                continue
            if sec.file not in raw_cache:
                raw_path = kb_dir / entry.id / f"{sec.file}.raw.md"
                raw_cache[sec.file] = (
                    raw_path.read_text(encoding="utf-8") if raw_path.exists() else ""
                )
            body = slice_section(raw_cache[sec.file], sec.id) or ""
            out.append(PendingSection(entry.id, sec.id, sec.title, sec.file, body))
    return out


def build_section_prompt(section: PendingSection) -> str:
    return SECTION_PROMPT.format(
        section_id=section.section_id, title=section.title, l3_body=section.l3_body
    )


def build_doc_prompt(title: str, l1_summaries: list[str]) -> str:
    return DOC_PROMPT.format(title=title, l1_lines="\n".join(f"- {s}" for s in l1_summaries))


def parse_json_reply(text: str, required: tuple[str, ...]) -> dict[str, str]:
    """Extract the first JSON object; every required key must be a non-empty str."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("reply is not a JSON object")
    out: dict[str, str] = {}
    for key in required:
        value = data.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"missing or empty key: {key}")
        out[key] = value.strip()
    return out


def replace_marker(l2_text: str, section_id: str, summary: str) -> str:
    marker = f"<!-- TODO:summarize {section_id} -->"
    if marker not in l2_text:
        raise ValueError(f"marker not found: {marker}")
    return l2_text.replace(marker, summary, 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/summarize.py tests/test_summarize.py
git commit -m "feat: summarize primitives — collect pending, prompts, parse, marker replace"
```

---

### Task 4: `summarize_kb` orchestrator (parallel workers, apply, doc summary)

**Files:**
- Modify: `src/center_kb/summarize.py` (append)
- Test: `tests/test_summarize.py` (append)

**Interfaces:**
- Consumes: everything from Task 3; a runner object exposing `.run(prompt: str) -> str` and `.name` (duck-typed — `llm.Runner` in prod, `FakeRunner` in tests); `llm.RunnerError`.
- Produces:
  - `SummarizeReport` dataclass: `summarized: list[str]`, `failed: list[str]` (both `"doc-id/section-id"`), property `ok: bool` (no failures).
  - `summarize_kb(kb_dir: Path, runner, doc_id: str | None = None, max_workers: int = 5, on_progress: Callable[[str], None] | None = None) -> SummarizeReport`.

Behavior contract: workers only run the LLM call (`_summarize_one`: 1 try + exactly 1 retry on `RunnerError`/`ValueError`); all file/manifest writes happen sequentially on the main thread after the pool drains. Marker-replace failure moves the section from summarized to failed. After sections are applied, every doc with zero remaining `pending` sections gets one doc-summary call written to `index.yaml` (failure → progress warning only, never touches `report.failed`).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_summarize.py`)

```python
import json as _json

from center_kb.llm import RunnerError


class FakeRunner:
    """Duck-typed stand-in for llm.Runner. Scripted replies per call order."""
    name = "fake"

    def __init__(self, reply=None, fail_ids=(), fail_times=2):
        self._reply = reply
        self._fail_ids = set(fail_ids)
        self._fail_times = fail_times
        self._fail_count: dict[str, int] = {}
        self.calls: list[str] = []

    def run(self, prompt: str) -> str:
        self.calls.append(prompt)
        for sid in self._fail_ids:
            if f"Section {sid} " in prompt:
                n = self._fail_count.get(sid, 0)
                if n < self._fail_times:
                    self._fail_count[sid] = n + 1
                    raise RunnerError("boom")
        if "one-line summaries" in prompt:  # doc-summary call
            return _json.dumps({"summary": "Doc-level summary."})
        return self._reply or _json.dumps(
            {"l2_summary": "Condensed text.", "l1_summary": "One line."}
        )


def test_summarize_kb_fills_l2_manifest_and_doc_summary(tmp_path):
    kb = make_kb(tmp_path, {})
    report = summarize.summarize_kb(kb, FakeRunner(), max_workers=2)
    assert sorted(report.summarized) == ["d1/1.1", "d1/1.2"]
    assert report.failed == [] and report.ok
    l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    assert "TODO:summarize" not in l2
    assert "Condensed text." in l2
    assert "| P | Prohibited |" in l2  # table survived
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" for s in manifest.sections)
    assert all(s.summary == "One line." for s in manifest.sections)
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == "Doc-level summary."


def test_summarize_kb_failed_section_stays_pending(tmp_path):
    kb = make_kb(tmp_path, {})
    report = summarize.summarize_kb(kb, FakeRunner(fail_ids={"1.2"}), max_workers=2)
    assert report.summarized == ["d1/1.1"]
    assert report.failed == ["d1/1.2"] and not report.ok
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    by_id = {s.id: s for s in manifest.sections}
    assert by_id["1.1"].status == "summarized"
    assert by_id["1.2"].status == "pending"
    l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    assert "<!-- TODO:summarize 1.2 -->" in l2
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == ""  # doc not complete → no doc summary


def test_summarize_kb_retries_once_then_succeeds(tmp_path):
    kb = make_kb(tmp_path, {})
    runner = FakeRunner(fail_ids={"1.1"}, fail_times=1)  # fails once, retry OK
    report = summarize.summarize_kb(kb, runner, max_workers=1)
    assert report.ok and sorted(report.summarized) == ["d1/1.1", "d1/1.2"]


def test_summarize_kb_no_pending_is_noop(tmp_path):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    runner = FakeRunner()
    report = summarize.summarize_kb(kb, runner)
    assert report.summarized == [] and report.failed == []
    assert runner.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -v -k summarize_kb`
Expected: FAIL — `AttributeError: module ... has no attribute 'summarize_kb'`.

- [ ] **Step 3: Implement** (append to `src/center_kb/summarize.py`; extend imports at top of file accordingly):

```python
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import field

from center_kb.llm import RunnerError


@dataclass
class SummarizeReport:
    summarized: list[str] = field(default_factory=list)  # "doc-id/section-id"
    failed: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed


def _summarize_one(runner, section: PendingSection) -> dict[str, str]:
    prompt = build_section_prompt(section)
    last: Exception | None = None
    for _ in range(2):  # 1 try + exactly 1 retry (spec §3.3)
        try:
            return parse_json_reply(
                runner.run(prompt), ("l2_summary", "l1_summary")
            )
        except (RunnerError, ValueError) as exc:
            last = exc
    raise RunnerError(str(last))


def summarize_kb(
    kb_dir: Path,
    runner,
    doc_id: str | None = None,
    max_workers: int = 5,
    on_progress: Callable[[str], None] | None = None,
) -> SummarizeReport:
    """Fill pending sections via the runner. Workers only call the LLM;
    all file writes happen sequentially on the main thread."""
    say = on_progress or (lambda _msg: None)
    pending = collect_pending(kb_dir, doc_id)
    report = SummarizeReport()
    if not pending:
        return report

    results: dict[tuple[str, str], dict[str, str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_summarize_one, runner, s): s for s in pending}
        for fut in as_completed(futures):
            s = futures[fut]
            key = f"{s.doc_id}/{s.section_id}"
            try:
                results[(s.doc_id, s.section_id)] = fut.result()
            except RunnerError as exc:
                report.failed.append(key)
                say(f"[fail] {key}: {exc}")
            else:
                say(f"[ok] {key}")

    _apply_results(kb_dir, results, report)
    _fill_doc_summaries(kb_dir, runner, {s.doc_id for s in pending}, say)
    report.summarized.sort()
    report.failed.sort()
    return report


def _apply_results(
    kb_dir: Path,
    results: dict[tuple[str, str], dict[str, str]],
    report: SummarizeReport,
) -> None:
    by_doc: dict[str, dict[str, dict[str, str]]] = {}
    for (doc, sid), pair in results.items():
        by_doc.setdefault(doc, {})[sid] = pair
    for doc, pairs in by_doc.items():
        manifest_path = kb_dir / doc / "_manifest.yaml"
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        l2_cache: dict[str, str] = {}
        for sec in manifest.sections:
            pair = pairs.get(sec.id)
            if pair is None:
                continue
            key = f"{doc}/{sec.id}"
            if sec.file not in l2_cache:
                l2_cache[sec.file] = (kb_dir / doc / f"{sec.file}.md").read_text(
                    encoding="utf-8"
                )
            try:
                l2_cache[sec.file] = replace_marker(
                    l2_cache[sec.file], sec.id, pair["l2_summary"]
                )
            except ValueError:
                report.failed.append(key)
                continue
            sec.summary = pair["l1_summary"]
            sec.status = "summarized"
            report.summarized.append(key)
        for stem, text in l2_cache.items():
            (kb_dir / doc / f"{stem}.md").write_text(text, encoding="utf-8")
        models.save_yaml_model(manifest_path, manifest)


def _fill_doc_summaries(
    kb_dir: Path, runner, doc_ids: set[str], say: Callable[[str], None]
) -> None:
    index_path = kb_dir / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    changed = False
    for entry in index.docs:
        if entry.id not in doc_ids:
            continue
        manifest = models.load_yaml_model(
            kb_dir / entry.id / "_manifest.yaml", models.Manifest
        )
        if any(s.status == "pending" for s in manifest.sections):
            continue  # doc not complete yet
        prompt = build_doc_prompt(entry.title, [s.summary for s in manifest.sections])
        try:
            reply = parse_json_reply(runner.run(prompt), ("summary",))
        except (RunnerError, ValueError) as exc:
            say(f"[warn] doc summary failed for {entry.id}: {exc}")
            continue
        entry.summary = reply["summary"]
        changed = True
    if changed:
        models.save_yaml_model(index_path, index)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_summarize.py -v`
Expected: PASS (all Task 3 + Task 4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/summarize.py tests/test_summarize.py
git commit -m "feat: summarize_kb orchestrator — parallel LLM calls, sequential writes, doc summaries"
```

---

### Task 5: CLI command `kb summarize`

**Files:**
- Modify: `src/center_kb/cli.py` (add command after `ingest`, ~line 140)
- Test: `tests/test_summarize_cli.py` (new)

**Interfaces:**
- Consumes: `llm.detect_runner`, `summarize.summarize_kb`, `models.KBIndex.llm`, `build.build_kb(kb_dir, allow_pending) -> BuildReport` (`.ok`, `.errors`, `.warnings`).
- Produces: `kb summarize [DOC_ID] --llm --max-workers --kb-dir`. Exit 0 = every pending section processed; exit 1 = runner unavailable/disabled or sections still failed; exit 2 = bad `--llm` value.

- [ ] **Step 1: Write the failing tests** — create `tests/test_summarize_cli.py`:

```python
from pathlib import Path

from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app
from tests.test_summarize import FakeRunner, make_kb

runner = CliRunner()


def _patch_detect(monkeypatch, fake):
    import center_kb.llm as llm_mod

    # cli._run_summarize looks detect_runner up on the module at call time,
    # so patching the module attribute is enough.
    monkeypatch.setattr(llm_mod, "detect_runner", lambda choice, cfg: fake)


def test_summarize_success_exit_0(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "2 summarized" in result.output
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" for s in manifest.sections)


def test_summarize_failed_section_exit_1(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _patch_detect(monkeypatch, FakeRunner(fail_ids={"1.2"}))
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "1 failed" in result.output
    assert "kb summarize" in result.output  # re-run hint


def test_summarize_no_runner_exit_1(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _patch_detect(monkeypatch, None)
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "claude" in result.output and "copilot" in result.output


def test_summarize_runner_none_exit_1(tmp_path: Path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "none"])
    assert result.exit_code == 1
    assert "none" in result.output


def test_summarize_bad_llm_value_exit_2(tmp_path: Path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "gemini"])
    assert result.exit_code == 2


def test_summarize_nothing_pending_exit_0(tmp_path: Path, monkeypatch):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb)])
    assert result.exit_code == 0
    assert "0" in result.output
```

Note: `make_kb`/`FakeRunner` are imported from `tests/test_summarize.py` — keep them module-level there (they already are).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_summarize_cli.py -v`
Expected: FAIL — `No such command 'summarize'` (exit code 2 mismatch on the success tests).

- [ ] **Step 3: Implement** — add to `src/center_kb/cli.py`. A shared helper (also used by Task 6) plus the command:

```python
_LLM_CHOICES = ("", "claude", "copilot", "none")


def _validate_llm_choice(llm_choice: str) -> None:
    if llm_choice not in _LLM_CHOICES:
        typer.secho(
            f"--llm must be one of: claude, copilot, none (got '{llm_choice}')",
            fg=typer.colors.RED,
        )
        raise typer.Exit(2)


def _run_summarize(
    kb_dir: Path, llm_choice: str, doc_id: str | None, max_workers: int
):
    """Shared engine for `kb summarize` and `kb ingest`.

    Returns (report | None, reason): report is None when no runner ran;
    reason is "disabled" | "missing" | "" accordingly.
    """
    import center_kb.llm as llm_mod
    from center_kb.summarize import summarize_kb

    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    effective = llm_choice or index.llm.runner
    if effective == "none":
        return None, "disabled"
    runner = llm_mod.detect_runner(llm_choice or None, index.llm)
    if runner is None:
        return None, "missing"
    workers = max_workers or index.llm.max_workers
    typer.echo(f"Summarizing with {runner.name} ({runner.model}), {workers} workers…")
    report = summarize_kb(
        kb_dir, runner, doc_id=doc_id, max_workers=workers,
        on_progress=lambda msg: typer.echo(f"  {msg}"),
    )
    return report, ""


def _echo_no_runner(reason: str) -> None:
    if reason == "disabled":
        typer.echo("LLM summarize is disabled (runner: none).")
    else:
        typer.secho(
            "No LLM CLI found (tried: claude, copilot).", fg=typer.colors.YELLOW
        )
    typer.echo(
        "Sections stay pending. Install Claude Code or GitHub Copilot CLI and "
        "run `kb summarize`, or use the kb-summarize skill in Claude Code."
    )


@app.command()
def summarize(
    doc_id: str = typer.Argument("", help="Limit to one document (empty = all)"),
    llm: str = typer.Option(
        "", "--llm", help="Runner: claude | copilot | none (default: auto-detect)"
    ),
    max_workers: int = typer.Option(
        0, help="Parallel LLM calls (default: llm.max_workers in index.yaml)"
    ),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
) -> None:
    """Fill pending L1/L2 summaries by calling a headless LLM CLI (claude/copilot)."""
    _validate_llm_choice(llm)
    if not (kb_dir / "index.yaml").exists():
        typer.secho(f"not found: {kb_dir / 'index.yaml'}", fg=typer.colors.RED)
        raise typer.Exit(1)
    report, reason = _run_summarize(kb_dir, llm, doc_id or None, max_workers)
    if report is None:
        _echo_no_runner(reason)
        raise typer.Exit(1)
    typer.echo(f"{len(report.summarized)} summarized, {len(report.failed)} failed.")
    if report.failed:
        typer.secho(
            "Some sections stay pending — re-run with: kb summarize",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_summarize_cli.py tests/test_summarize.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py tests/test_summarize_cli.py
git commit -m "feat: kb summarize command — headless LLM fill for pending sections"
```

---

### Task 6: `kb ingest` integration (default-on, `--no-summarize`, `--llm`)

**Files:**
- Modify: `src/center_kb/cli.py` — `ingest` command (~lines 80-140)
- Modify: `tests/test_ingest_cli.py` — existing tests get `--llm none` (hermeticity!)
- Test: `tests/test_ingest_cli.py` (append)

**Interfaces:**
- Consumes: `_run_summarize`, `_echo_no_runner`, `_validate_llm_choice` (Task 5), `build.build_kb`.
- Produces: `kb ingest … [--no-summarize] [--llm X]`. Ingest always exits 0 when scaffolding succeeded, regardless of summarize outcome (spec decision #6). After a summarize run it executes `build_kb(kb_dir, allow_pending=bool(report.failed))` and prints errors/warnings as text (still exit 0).

- [ ] **Step 1: Update existing tests for hermeticity** — in `tests/test_ingest_cli.py`, add `"--llm", "none"` to BOTH existing `runner.invoke(app, ["ingest", …])` argument lists (lines ~33 and ~56). Also check `tests/test_parser.py`'s single `"ingest"` reference — if it invokes the CLI, add `"--llm", "none"` there too; if it's not a CLI invocation, leave it. **Without this, running tests on a machine with `claude` installed would invoke the real CLI.**

- [ ] **Step 2: Write the failing tests** (append to `tests/test_ingest_cli.py`)

```python
def _ingest_args(tmp_path, extra=()):
    return [
        "ingest", str(tmp_path / "doc.pdf"),
        "--id", "arinc-424",
        "--kb-dir", str(tmp_path / ".kb"),
        "--work-dir", str(tmp_path / ".kb-work"),
        *extra,
    ]


def _write_pdf(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-fake")


def test_ingest_auto_summarizes_by_default(tmp_path, monkeypatch):
    _fake_parse(monkeypatch)
    _write_pdf(tmp_path)
    from tests.test_summarize import FakeRunner
    import center_kb.llm as llm_mod
    monkeypatch.setattr(llm_mod, "detect_runner", lambda c, cfg: FakeRunner())
    # index.yaml is created by scaffold during ingest; default runner=auto
    result = runner.invoke(app, _ingest_args(tmp_path))
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert all(s.status == "summarized" for s in manifest.sections)
    assert "summarized" in result.output


def test_ingest_no_summarize_flag_skips_llm(tmp_path, monkeypatch):
    _fake_parse(monkeypatch)
    _write_pdf(tmp_path)
    import center_kb.llm as llm_mod
    monkeypatch.setattr(
        llm_mod, "detect_runner",
        lambda c, cfg: (_ for _ in ()).throw(AssertionError("must not be called")),
    )
    result = runner.invoke(app, _ingest_args(tmp_path, ["--no-summarize"]))
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert all(s.status == "pending" for s in manifest.sections)
    assert "kb-summarize" in result.output  # manual-path hint preserved


def test_ingest_without_runner_stays_pending_exit_0(tmp_path, monkeypatch):
    _fake_parse(monkeypatch)
    _write_pdf(tmp_path)
    import center_kb.llm as llm_mod
    monkeypatch.setattr(llm_mod, "detect_runner", lambda c, cfg: None)
    result = runner.invoke(app, _ingest_args(tmp_path))
    assert result.exit_code == 0, result.output
    assert "No LLM CLI found" in result.output
    manifest = models.load_yaml_model(
        tmp_path / ".kb" / "arinc-424" / "_manifest.yaml", models.Manifest
    )
    assert all(s.status == "pending" for s in manifest.sections)


def test_ingest_failed_sections_still_exit_0(tmp_path, monkeypatch):
    _fake_parse(monkeypatch)
    _write_pdf(tmp_path)
    from tests.test_summarize import FakeRunner
    import center_kb.llm as llm_mod
    monkeypatch.setattr(
        llm_mod, "detect_runner", lambda c, cfg: FakeRunner(fail_ids={"5.3"})
    )
    result = runner.invoke(app, _ingest_args(tmp_path))
    assert result.exit_code == 0, result.output
    assert "failed" in result.output
    assert "kb summarize" in result.output  # re-run hint
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_ingest_cli.py -v`
Expected: new tests FAIL (`--no-summarize`/`--llm` unknown option → exit 2); the two updated pre-existing tests FAIL for the same reason (`--llm none` not yet accepted).

- [ ] **Step 4: Implement** — in `src/center_kb/cli.py`:

Add two parameters to `ingest(…)`:

```python
    no_summarize: bool = typer.Option(
        False, "--no-summarize", help="Skip the automatic LLM summarize step"
    ),
    llm: str = typer.Option(
        "", "--llm", help="Runner: claude | copilot | none (default: auto-detect)"
    ),
```

At the top of the ingest body add `_validate_llm_choice(llm)`. Then replace the final line

```python
    typer.echo("Next: open Claude Code and run the kb-summarize skill, then `kb build`.")
```

with:

```python
    if no_summarize or llm == "none":
        typer.echo(
            "Summarize skipped. Next: run `kb summarize` (or the kb-summarize "
            "skill in Claude Code), then `kb build`."
        )
        return
    report_s, reason = _run_summarize(kb_dir, llm, doc_id, max_workers=0)
    if report_s is None:
        _echo_no_runner(reason)
        return
    typer.echo(
        f"{len(report_s.summarized)} summarized, {len(report_s.failed)} failed."
    )
    if report_s.failed:
        typer.secho(
            "Failed sections stay pending — re-run with: kb summarize",
            fg=typer.colors.YELLOW,
        )
    from center_kb.build import build_kb

    build_report = build_kb(kb_dir, allow_pending=bool(report_s.failed))
    for err in build_report.errors:
        typer.secho(f"  [build] {err}", fg=typer.colors.RED)
    for warn in build_report.warnings:
        typer.secho(f"  [build] {warn}", fg=typer.colors.YELLOW)
    if build_report.ok:
        typer.echo("kb build: OK")
```

(Note: ingest deliberately never raises `typer.Exit(1)` for summarize/build issues — spec decision #6. `llm == "none"` short-circuits before `_run_summarize` so the message matches the `--no-summarize` path.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_ingest_cli.py tests/test_summarize_cli.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full suite** (guard against regressions in e2e tests that go through ingest)

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: PASS. If any other test invokes `["ingest", …]` via CliRunner without `--llm none`, add the flag there too (search: `grep -rn '"ingest"' tests/`).

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/cli.py tests/test_ingest_cli.py
git commit -m "feat: kb ingest auto-summarize by default (--no-summarize / --llm opt-out)"
```

---

### Task 7: F2 — English SKILL.md + Copilot instructions in `kb init` scaffold

**Files:**
- Create: `src/center_kb/templates/init/claude-skill-kb-summarize.md`
- Create: `src/center_kb/templates/init/copilot-kb-summarize.instructions.md`
- Modify: `src/center_kb/initcmd.py:8-17` (TEMPLATE_MAP)
- Modify: `.claude/skills/kb-summarize/SKILL.md` (replace with English canonical content — dogfood, spec decision #8)
- Test: `tests/test_init.py` (append; `tests/test_templates.py` covers resource existence automatically via TEMPLATE_MAP)

**Interfaces:**
- Consumes: `initcmd.TEMPLATE_MAP`, `EXPECTED_FILES` (derived from the map — existing tests pick the new entries up automatically).
- Produces: two new scaffold targets: `.claude/skills/kb-summarize/SKILL.md` and `.github/instructions/kb-summarize.instructions.md`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_init.py`)

```python
def test_init_scaffolds_ai_integration_files(tmp_path: Path):
    init_repo(tmp_path)
    skill = tmp_path / ".claude" / "skills" / "kb-summarize" / "SKILL.md"
    copilot = tmp_path / ".github" / "instructions" / "kb-summarize.instructions.md"
    assert skill.is_file() and copilot.is_file()
    skill_text = skill.read_text(encoding="utf-8")
    assert "name: kb-summarize" in skill_text
    assert "VERBATIM" in skill_text            # writing rules present
    assert "kb build" in skill_text
    copilot_text = copilot.read_text(encoding="utf-8")
    assert 'applyTo: ".kb/**"' in copilot_text
    assert "25 words" in copilot_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_init.py -v`
Expected: `test_init_scaffolds_ai_integration_files` FAILS (files missing).

- [ ] **Step 3: Create the templates.**

`src/center_kb/templates/init/claude-skill-kb-summarize.md`:

````markdown
---
name: kb-summarize
description: Fill pending L0/L1/L2 summaries in .kb/ after `kb ingest`. Use when asked to summarize the KB or fill summaries, or right after ingesting a new document when auto-summarize was skipped or failed.
---

# KB Summarize — fill knowledge into the .kb/ scaffold

You are the "LLM half" of the CENTER-KB pipeline. `kb ingest` generated the
scaffold; your job is to fill in the summaries. Do NOT edit anything outside
the locations listed below.

Note: `kb ingest` normally does this automatically by calling a headless LLM
CLI (`kb summarize`). Use this manual workflow when auto-summarize was
disabled (`--no-summarize`, `runner: none`), no LLM CLI was available, or
some sections failed and you want to fix them by hand.

## Workflow

1. Run `kb status` — list the pending sections (doc, section id, file).
2. For EACH pending section:
   a. Read the original text: `kb get <doc-id> <section-id> --level l3`
   b. Open the L2 file (`.kb/<doc-id>/<file>.md`) and find the marker
      `<!-- TODO:summarize <section-id> -->` inside that section.
   c. Replace the marker with a condensed paragraph (see Writing rules).
      Do NOT touch the markdown tables already present in the section —
      the tooling copies them verbatim.
   d. Open `.kb/<doc-id>/_manifest.yaml`, fill `summary` (one sentence,
      ≤ 25 words) for that section and change `status: pending` →
      `status: summarized`.
3. When every section of a doc is done: open `.kb/index.yaml`, fill or fix
   that doc's `summary` (one sentence) and verify its `title`, `revision`
   and `tags`.
4. Run `kb build` — it must PASS. If it fails on table integrity you have
   edited a table; restore it verbatim from the `.raw.md` file.
5. Report: number of sections filled, total L2 tokens (see `kb stats`).

## Writing rules (mandatory)

- Write in **English**.
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

## Work in batches

Fill sections one at a time; every 5–10 sections re-run
`kb build --allow-pending` to catch mistakes early. Do not edit many files
in parallel.
````

`src/center_kb/templates/init/copilot-kb-summarize.instructions.md`:

````markdown
---
applyTo: ".kb/**"
---

# CENTER-KB summarize instructions

Files under `.kb/` belong to a CENTER-KB knowledge base. When editing them
to fill in summaries (after `kb ingest`), follow these rules exactly.

## What to edit

- In `.kb/<doc-id>/<file>.md` (L2): replace each
  `<!-- TODO:summarize <section-id> -->` marker with a condensed paragraph.
  Never touch the markdown tables — they are verbatim copies.
- In `.kb/<doc-id>/_manifest.yaml` (L1): set `summary` (one sentence,
  ≤ 25 words) per section and flip `status: pending` → `status: summarized`.
- In `.kb/index.yaml`: when every section of a doc is summarized, fill the
  doc's one-sentence `summary`.
- Nothing else. `.raw.md` files (L3) are read-only source text.

## Writing rules (mandatory)

- Write in English.
- L2 paragraph: ~20–30% of the original length, keep the logical structure.
- Preserve VERBATIM: codes (P, R, D...), record/field names (UR, PA...),
  numeric values, units, cross-references (§x.y). Never paraphrase
  technical terms.
- Do NOT infer beyond the source text. When unsure, keep the original
  sentence.
- Do NOT summarize, create, or delete tables.

## Validate

After editing, run `kb build` — it must pass. If it reports a table
integrity error, restore the table verbatim from the `.raw.md` file.
````

- [ ] **Step 4: Wire into TEMPLATE_MAP** — in `src/center_kb/initcmd.py` add to `TEMPLATE_MAP`:

```python
    ".claude/skills/kb-summarize/SKILL.md": "claude-skill-kb-summarize.md",
    ".github/instructions/kb-summarize.instructions.md": "copilot-kb-summarize.instructions.md",
```

- [ ] **Step 5: Dogfood** — replace the content of this repo's `.claude/skills/kb-summarize/SKILL.md` with the exact content of `claude-skill-kb-summarize.md`:

```bash
cp src/center_kb/templates/init/claude-skill-kb-summarize.md .claude/skills/kb-summarize/SKILL.md
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_init.py tests/test_templates.py -v`
Expected: PASS — including the pre-existing `test_init_creates_all_files` (EXPECTED_FILES grows automatically) and `test_all_init_templates_exist_as_package_resources`.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/templates/init/ src/center_kb/initcmd.py .claude/skills/kb-summarize/SKILL.md tests/test_init.py
git commit -m "feat: kb init scaffolds Claude skill + Copilot instructions (English)"
```

---

### Task 8: End-to-end stub test + docs sync

**Files:**
- Test: `tests/test_summarize_e2e.py` (new)
- Modify: `src/center_kb/templates/init/QUICKSTART.md` (step 3, lines ~11-12)
- Modify: `README.md` (lines ~98, ~229, ~273, ~425, ~510 — the manual-skill flow mentions)

**Interfaces:**
- Consumes: everything shipped in Tasks 1-7. No new production code.

- [ ] **Step 1: Write the e2e test** — create `tests/test_summarize_e2e.py`. This is the only test exercising the real subprocess path end-to-end, using a stub `claude` on PATH:

```python
import json
import stat
from pathlib import Path

from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app
from tests.test_summarize import make_kb

runner = CliRunner()

INNER = json.dumps({"l2_summary": "Condensed via stub.", "l1_summary": "Stub line."})
ENVELOPE = json.dumps({"type": "result", "result": INNER})
DOC_INNER = json.dumps(
    {"l2_summary": "Condensed via stub.", "l1_summary": "Stub line.",
     "summary": "Stub doc summary."}
)
DOC_ENVELOPE = json.dumps({"type": "result", "result": DOC_INNER})


def _install_stub_claude(tmp_path: Path, monkeypatch, body: str) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    script = bindir / "claude"
    script.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(bindir), prepend=":")


def test_kb_summarize_end_to_end_with_stub_claude(tmp_path, monkeypatch):
    kb = make_kb(tmp_path, {})
    # stub replies with a payload valid for BOTH section and doc prompts
    _install_stub_claude(tmp_path, monkeypatch, f"cat > /dev/null\necho '{DOC_ENVELOPE}'")
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "claude"])
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" for s in manifest.sections)
    l2 = (kb / "d1" / "ch1.md").read_text(encoding="utf-8")
    assert "Condensed via stub." in l2 and "TODO:summarize" not in l2
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == "Stub doc summary."


def test_kb_summarize_end_to_end_garbage_reply_fails_cleanly(tmp_path, monkeypatch):
    kb = make_kb(tmp_path, {})
    _install_stub_claude(tmp_path, monkeypatch, "cat > /dev/null\necho 'not json'")
    result = runner.invoke(app, ["summarize", "--kb-dir", str(kb), "--llm", "claude"])
    assert result.exit_code == 1
    assert "2 failed" in result.output
    manifest = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "pending" for s in manifest.sections)


def test_kb_summarize_parallel_many_sections_manifest_consistent(tmp_path, monkeypatch):
    kb = tmp_path / ".kb"
    doc = kb / "big"
    doc.mkdir(parents=True)
    n = 12
    raw, l2, sections = [], [], []
    for i in range(1, n + 1):
        raw += [f"## {i}.0 Sec{i}", "", f"Body {i}.", ""]
        l2 += [f"## {i}.0 Sec{i}", "", f"<!-- TODO:summarize {i}.0 -->", ""]
        sections.append(models.SectionEntry(id=f"{i}.0", title=f"Sec{i}", file="ch"))
    (doc / "ch.raw.md").write_text("\n".join(raw), encoding="utf-8")
    (doc / "ch.md").write_text("\n".join(l2), encoding="utf-8")
    models.save_yaml_model(
        doc / "_manifest.yaml", models.Manifest(id="big", title="Big", sections=sections)
    )
    models.save_yaml_model(
        kb / "index.yaml",
        models.KBIndex(docs=[models.IndexEntry(id="big", title="Big")]),
    )
    _install_stub_claude(tmp_path, monkeypatch, f"cat > /dev/null\necho '{DOC_ENVELOPE}'")
    result = runner.invoke(
        app, ["summarize", "--kb-dir", str(kb), "--llm", "claude", "--max-workers", "5"]
    )
    assert result.exit_code == 0, result.output
    manifest = models.load_yaml_model(doc / "_manifest.yaml", models.Manifest)
    assert sum(1 for s in manifest.sections if s.status == "summarized") == n
    assert "TODO:summarize" not in (doc / "ch.md").read_text(encoding="utf-8")
```

Note on `monkeypatch.setenv(..., prepend=":")`: this prepends `bindir` to PATH so `shutil.which("claude")` finds the stub before any real installation.

- [ ] **Step 2: Run the e2e tests**

Run: `.venv/bin/python -m pytest tests/test_summarize_e2e.py -v`
Expected: PASS (all production code already exists; if anything fails, fix the integration — these tests validate real subprocess + PATH detection wiring).

- [ ] **Step 3: Sync docs.**

In `src/center_kb/templates/init/QUICKSTART.md` replace the step-3 lines (~11-12):

```markdown
3. **Summarize** — `kb ingest` does this automatically when the Claude Code or
   GitHub Copilot CLI is installed (config: `llm:` in `.kb/index.yaml`).
   Manual fallback: run the `kb-summarize` skill in Claude Code, or
   `kb summarize` later. Then validate: `kb build`
```

In `README.md`, update the manual-flow mentions (lines ~98, ~229, ~273, ~425, ~510): state that step 2 runs automatically inside `kb ingest` via a headless LLM CLI (claude → copilot auto-detect, `--no-summarize` to skip, `kb summarize` to re-run/retry), and that the `kb-summarize` skill remains the manual fallback. Keep the existing table/diagram structure; only amend the wording of those rows/paragraphs.

- [ ] **Step 4: Full suite + lint gate**

Run: `.venv/bin/python -m pytest tests/ -q && .venv/bin/python -m ruff check src tests && .venv/bin/python -m mypy src`
Expected: all PASS (match whatever lint/type commands CI uses — see `.github/workflows/`).

- [ ] **Step 5: Commit**

```bash
git add tests/test_summarize_e2e.py src/center_kb/templates/init/QUICKSTART.md README.md
git commit -m "test: e2e stub-CLI summarize coverage + docs sync for auto-summarize"
```

---

## Self-Review Notes

- Spec coverage: §3.1 llm.py+summarize.py (Tasks 2-4), §3.2 CLI (Tasks 5-6, exit codes per spec), §3.3 prompt contract (Task 3 — l1 ≤ 25 words is stated in the prompt; soft-check only, no hard reject, per spec), §3.4 config (Task 1), §4 scaffold (Task 7), §5 testing incl. concurrency + stub e2e (Tasks 2-8), §6 effort best-effort (Task 2 `MAX_THINKING_TOKENS` + comment).
- Deliberate simplifications vs spec wording: "verify real CLI flags at implement time" (spec §6) — Task 2 encodes the currently documented flags (`claude -p --model --output-format json` stdin; `copilot -p <prompt> --model`); the implementer must sanity-check against `claude --help` / `copilot --help` on the dev machine before committing Task 2 and adjust `Runner.run` if flags moved. The parse/envelope layers are defensive either way.
- Type consistency verified: `PendingSection`, `SummarizeReport`, `detect_runner`, `_run_summarize` signatures match across Tasks 3-6.
