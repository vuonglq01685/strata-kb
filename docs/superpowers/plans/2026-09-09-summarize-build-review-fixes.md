# Summarize/build review fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the C2 quality rules into a shared `quality.py` enforced by `kb build` (warn by default, `--strict` fatal), make the table check two-way, pass the Copilot prompt through stdin, make `--redo` scoped and protective of reviewed rows, record provenance/hashes/review records in the manifest, gate `kb approve` on a strict build, warn in `kb publish`, and make the manual `/kb-summarize` path consume the engine's prompt.

**Architecture:** One new pure module `src/center_kb/quality.py` owns `prose_only()` (the single length measure), the thresholds, and every deterministic C2 check. `build.py` orchestrates (two-way tables, orphan headings, hash drift, quality findings, no-write-on-failure). `summarize.py` uses the same `prose_only()` for its budget and for the new "brief section" short-circuit, keys results by manifest row, records provenance. `llm.py` sends every prompt on stdin. `review.py`/`publish.py`/`cli.py` add the gates and flags. Manifest schema gains three optional fields, serialised with `exclude_none`.

**Tech Stack:** Python 3.11+, pydantic v2, typer, PyYAML, tiktoken, pytest (no mocks; real files in `tmp_path`; fake CLI executables via `tests/cli_stub.py`). Run tests with `uv run pytest` (or `pytest` inside the project venv). Windows is a first-class platform: the stubs are `.cmd` files there.

**Spec:** `docs/superpowers/specs/2026-09-09-summarize-build-review-fixes-design.md` — read it first; every task below cites the spec section it implements.

## Global Constraints

- Thresholds are module constants in `quality.py`, never config: `RATIO = 0.35`, `FLOOR_CHARS = 120`, `BRIEF_CHARS = 200`, `OVERLAP_MIN = 0.45`, `OVERLAP_MIN_WORDS = 20`, `CELLS_PER_SENTENCE = 4`, `L1_MAX_WORDS = 25`, `L0_MAX_WORDS = 30`.
- Fixed labels, byte-exact: `Table-only section: {title}.` and `Brief section: {title}.`
- Quality findings carry the suffix ` (quality)` in their message and are warnings unless `strict=True`.
- `kb build` never writes `_manifest.yaml` for a document that produced an error.
- No runner may put the prompt in argv; every runner sends it on stdin.
- The bundled `.kb/` is not re-summarized, re-approved, or edited by this plan. `kb build` on it must still exit 0 (warnings only); `kb build --strict` must exit 1.
- Code style: `from __future__ import annotations`, functions under 50 lines, files under 800 lines, no bare `except`, errors surfaced through `report.errors` / `RunnerError` / `ValueError`, never swallowed.
- Commit after every task with a conventional-commit subject (`feat:`, `fix:`, `test:`, `docs:`). Commit with `git commit -F <file>` (never a heredoc through PowerShell) and end the message with the session attribution line the executor's environment provides.
- Windows: write files with `encoding="utf-8", newline="\n"`; tests use `tmp_path`; never rely on `#!/bin/sh` stubs (use `tests/cli_stub.py`).

---

### Task 1: `quality.py` — `prose_only`, thresholds, budget, labels, `Finding`

**Files:**
- Create: `src/center_kb/quality.py`
- Create: `tests/test_quality.py`
- Modify: `src/center_kb/summarize.py:47` (`TABLE_PLACEHOLDER` moves to `quality.py`; summarize re-exports it)

**Interfaces:**
- Produces:
  - constants `RATIO`, `FLOOR_CHARS`, `BRIEF_CHARS`, `OVERLAP_MIN`, `OVERLAP_MIN_WORDS`, `CELLS_PER_SENTENCE`, `L1_MAX_WORDS`, `L0_MAX_WORDS`, `TABLE_PLACEHOLDER = "[table omitted]"`, `TABLE_ONLY_LABEL = "Table-only section: {title}."`, `BRIEF_LABEL = "Brief section: {title}."`
  - `prose_only(text: str) -> str`
  - `budget(prose_chars: int) -> int`
  - `is_table_only(prose_chars: int) -> bool`, `is_brief(prose_chars: int) -> bool`
  - `digest(text: str) -> str` (sha256 hex of UTF-8 bytes)
  - `@dataclass(frozen=True) Finding(code: str, ref: str, message: str, level: Literal["error", "quality"])` with property `text -> str` (= `message` plus ` (quality)` when level is quality)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_quality.py
from center_kb import quality
from center_kb.quality import Finding, budget, digest, is_brief, is_table_only, prose_only

SLICE = (
    "## 5.7 Route Type\n\n"
    "Prose line one.\n\n"
    "| Code | Meaning |\n|---|---|\n| O | Official |\n\n"
    "[table omitted]\n\n"
    "Figure: Holding pattern entry sectors\n\n"
    "![Holding](assets/" + "a" * 64 + ".png)\n\n"
    "<!-- TODO:summarize 5.7 -->\n\n"
    "Prose line two.\n"
)


def test_prose_only_keeps_prose_and_drops_everything_else():
    assert prose_only(SLICE) == "Prose line one.\n\nProse line two."


def test_prose_only_collapses_blank_runs_and_strips():
    assert prose_only("\n\nA\n\n\n\nB\n\n") == "A\n\nB"


def test_prose_only_empty_for_table_only_slice():
    assert prose_only("## 2 T\n\n| h |\n|---|\n| v |\n") == ""


def test_budget_floor_and_ratio():
    assert budget(201) == 120            # floor wins
    assert budget(2000) == 700           # 0.35 ratio wins
    assert budget(342) == 120            # int(0.35*342)=119 < floor


def test_brief_and_table_only_boundaries():
    assert is_table_only(0) and not is_brief(0)
    assert is_brief(1) and is_brief(200)
    assert not is_brief(201) and not is_table_only(201)


def test_digest_is_sha256_hex_of_utf8():
    assert digest("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_finding_text_marks_quality_level():
    q = Finding("ratio", "d §1", "d §1: too long", "quality")
    e = Finding("l0-empty", "d", "d: empty", "error")
    assert q.text == "d §1: too long (quality)"
    assert e.text == "d: empty"


def test_labels_are_exact():
    assert quality.TABLE_ONLY_LABEL.format(title="X") == "Table-only section: X."
    assert quality.BRIEF_LABEL.format(title="X") == "Brief section: X."
    assert quality.TABLE_PLACEHOLDER == "[table omitted]"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_quality.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.quality'`

- [ ] **Step 3: Write `quality.py` (part 1)**

```python
# src/center_kb/quality.py
"""Deterministic C2 quality rules shared by kb build, kb summarize and kb approve.

Pure functions only: no I/O, no manifest writes, no LLM. `prose_only()` is
the single unit of measure for every length rule in the pipeline — the
engine's budget and the build gate must never disagree on the denominator.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Literal

RATIO = 0.35            # L2 prose ≤ RATIO × L3 prose …
FLOOR_CHARS = 120       # … but never required below this many characters
BRIEF_CHARS = 200       # ≤ this much L3 prose: copy verbatim, no LLM
OVERLAP_MIN = 0.45      # share of L2 word-types that occur in the L3 slice
OVERLAP_MIN_WORDS = 20  # overlap is only measured on L2 prose this long
CELLS_PER_SENTENCE = 4  # distinct table cells quoted in one L2 sentence
L1_MAX_WORDS = 25
L0_MAX_WORDS = 30

TABLE_PLACEHOLDER = "[table omitted]"
TABLE_ONLY_LABEL = "Table-only section: {title}."
BRIEF_LABEL = "Brief section: {title}."

_IMAGE_LINE_RE = re.compile(r"^!\[[^\]]*\]\([^)]*\)\s*$")


def prose_only(text: str) -> str:
    """Prose lines of an L2/L3 slice: no tables, headings, placeholders,
    figure captions, image refs or HTML comments. Blank runs collapse to
    one; result is stripped. Applied identically to both levels."""
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            if out and out[-1] != "":
                out.append("")
            continue
        if (
            s.startswith(("|", "#", "<!--", "Figure: "))
            or s == TABLE_PLACEHOLDER
            or _IMAGE_LINE_RE.match(s)
        ):
            continue
        out.append(line.rstrip())
    return "\n".join(out).strip()


def budget(prose_chars: int) -> int:
    return max(FLOOR_CHARS, int(RATIO * prose_chars))


def is_table_only(prose_chars: int) -> bool:
    return prose_chars == 0


def is_brief(prose_chars: int) -> bool:
    return 0 < prose_chars <= BRIEF_CHARS


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Finding:
    code: str
    ref: str
    message: str
    level: Literal["error", "quality"]

    @property
    def text(self) -> str:
        return f"{self.message} (quality)" if self.level == "quality" else self.message
```

- [ ] **Step 4: Move `TABLE_PLACEHOLDER` in `summarize.py`**

Replace the line `TABLE_PLACEHOLDER = "[table omitted]"` in `src/center_kb/summarize.py` with:

```python
from center_kb.quality import TABLE_PLACEHOLDER  # noqa: F401 — re-exported for callers/tests
```

(keep it near the other imports; `_IGNORABLE_LINE_RE` below still references it and keeps working).

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_quality.py tests/test_summarize.py -q`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/quality.py tests/test_quality.py src/center_kb/summarize.py
git commit -F <msgfile>   # "feat(quality): prose_only, thresholds, budget and Finding"
```

---

### Task 2: `quality.py` — `check_section` and `check_doc`

**Files:**
- Modify: `src/center_kb/quality.py`
- Modify: `tests/test_quality.py`

**Interfaces:**
- Consumes: `mdutils.extract_tables`, `mdutils.normalize_table`, `models.SectionEntry`, `models.IndexEntry`
- Produces:
  - `check_section(ref: str, sec: models.SectionEntry, l2_slice: str, l3_slice: str) -> list[Finding]`
  - `check_doc(entry: models.IndexEntry) -> list[Finding]`
  - codes: `ratio`, `brief-verbatim`, `l2-empty`, `table-transcription`, `invented-code`, `lexical-overlap`, `l1-words`, `table-only-label`, `brief-label`, `l0-empty` (error), `l0-words`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_quality.py`:

```python
from center_kb import models
from center_kb.quality import check_doc, check_section

LONG_PROSE = " ".join(f"Sentence number {i} explains the record layout." for i in range(12))  # > 200 chars


def _sec(summary="Covers the record layout.", title="Route Type"):
    return models.SectionEntry(id="5.7", title=title, summary=summary, status="summarized", file="ch5")


def _codes(findings):
    return sorted(f.code for f in findings)


def test_clean_section_has_no_findings():
    l3 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n"
    l2 = "## 5.7 Route Type\n\nSentence number 1 explains the record layout.\n"
    assert check_section("d §5.7", _sec(), l2, l3) == []


def test_ratio_fires_when_l2_exceeds_budget():
    l3 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n"
    l2 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n"          # 1.0× — over 0.35
    f = check_section("d §5.7", _sec(), l2, l3)
    assert _codes(f) == ["ratio"] and f[0].level == "quality"
    assert f[0].text.endswith("(quality)")


def test_l2_empty_fires_when_prose_deleted():
    l3 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n"
    l2 = "## 5.7 Route Type\n"
    assert _codes(check_section("d §5.7", _sec(), l2, l3)) == ["l2-empty"]


def test_brief_section_must_be_verbatim_and_labelled():
    l3 = "## 5.320 HAL\n\nUsed On: PA\nLength: 3\n"
    ok_l2 = "## 5.320 HAL\n\nUsed On: PA\nLength: 3\n"
    good = _sec(summary="Brief section: HAL.", title="HAL")
    assert check_section("d §5.320", good, ok_l2, l3) == []
    bad_l2 = "## 5.320 HAL\n\nThis header contains only field usage metadata.\n"
    bad = _sec(summary="Explains HAL metadata.", title="HAL")
    assert _codes(check_section("d §5.320", bad, bad_l2, l3)) == ["brief-label", "brief-verbatim"]


def test_table_only_section_label_and_empty_prose():
    l3 = "## 5.9 T\n\n| h |\n|---|\n| v |\n"
    good = _sec(summary="Table-only section: T.", title="T")
    assert check_section("d §5.9", good, "## 5.9 T\n\n| h |\n|---|\n| v |\n", l3) == []
    bad = _sec(summary="Describes the table.", title="T")
    l2 = "## 5.9 T\n\nThe table lists v.\n\n| h |\n|---|\n| v |\n"
    assert "table-only-label" in _codes(check_section("d §5.9", bad, l2, l3))


def test_table_transcription_fires_on_four_cells_in_one_sentence():
    table = (
        "| Route type | Code |\n|---|---|\n"
        "| Officially Designated Airways | O |\n| Airline Airway | A |\n"
        "| Common Portion | C |\n| Non-common Portion | N |\n"
    )
    l3 = f"## 5.7 Route Type\n\n{LONG_PROSE}\n\n{table}"
    l2 = (
        "## 5.7 Route Type\n\nOfficially Designated Airways O, Airline Airway A, "
        f"Common Portion C, Non-common Portion N.\n\n{table}"
    )
    assert "table-transcription" in _codes(check_section("d §5.7", _sec(), l2, l3))


def test_table_transcription_ignores_short_and_numeric_cells():
    table = "| A | 1 |\n|---|---|\n| B | 2 |\n| C | 3 |\n| D | 4 |\n"
    l3 = f"## 5.7 T\n\n{LONG_PROSE}\n\n{table}"
    l2 = f"## 5.7 T\n\nA B C D 1 2 3 4 in one sentence.\n\n{table}"
    assert "table-transcription" not in _codes(check_section("d §5.7", _sec(), l2, l3))


def test_invented_code_fires_for_uppercase_token_absent_from_l3():
    l3 = f"## 5.99 Marker\n\n{LONG_PROSE} Column 18 holds I and column 19 holds M.\n"
    l2 = "## 5.99 Marker\n\nThe codes IM, MM, OM and BM mark the marker type.\n"
    f = [x for x in check_section("d §5.99", _sec(), l2, l3) if x.code == "invented-code"]
    assert len(f) == 1 and "BM" in f[0].message and "IM" in f[0].message


def test_invented_code_accepts_codes_that_live_in_a_table():
    table = "| Code | Meaning |\n|---|---|\n| CTAF | common frequency |\n"
    l3 = f"## 5.101 F\n\n{LONG_PROSE}\n\n{table}"
    l2 = f"## 5.101 F\n\nCTAF is listed.\n\n{table}"
    assert "invented-code" not in _codes(check_section("d §5.101", _sec(), l2, l3))


def test_lexical_overlap_fires_on_unrelated_or_translated_prose():
    l3 = f"## 5.263 HAL\n\n{LONG_PROSE}\n"
    l2 = (
        "## 5.263 HAL\n\nPhần này chỉ chứa siêu dữ liệu về cách dùng trường, "
        "không có định nghĩa hay ghi chú nguồn nào trong văn bản trích xuất, "
        "và vì vậy không thể tóm tắt thêm được nữa ở đây.\n"
    )
    assert "lexical-overlap" in _codes(check_section("d §5.263", _sec(), l2, l3))


def test_lexical_overlap_skipped_for_short_l2():
    l3 = f"## 5.1 A\n\n{LONG_PROSE}\n"
    l2 = "## 5.1 A\n\nTotally unrelated words here.\n"   # < 20 words
    assert "lexical-overlap" not in _codes(check_section("d §5.1", _sec(), l2, l3))


def test_l1_words_fires_above_25():
    l3 = f"## 5.1 A\n\n{LONG_PROSE}\n"
    l2 = "## 5.1 A\n\nSentence number 1 explains the record layout.\n"
    sec = _sec(summary=" ".join(["word"] * 26))
    assert _codes(check_section("d §5.1", sec, l2, l3)) == ["l1-words"]


def test_check_doc_empty_summary_is_an_error_and_long_summary_is_quality():
    empty = models.IndexEntry(id="d", title="D", summary="  ")
    long = models.IndexEntry(id="d", title="D", summary=" ".join(["w"] * 31))
    ok = models.IndexEntry(id="d", title="D", summary="One sentence.")
    assert [f.code for f in check_doc(empty)] == ["l0-empty"]
    assert check_doc(empty)[0].level == "error"
    assert [f.code for f in check_doc(long)] == ["l0-words"]
    assert check_doc(ok) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_quality.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_section'`

- [ ] **Step 3: Implement the checks**

Append to `src/center_kb/quality.py`:

```python
from center_kb import models  # noqa: E402  (placed with the other imports at the top)
from center_kb.mdutils import extract_tables, normalize_table  # noqa: E402

_CODE_RE = re.compile(r"\b[A-Z][A-Z0-9/]{1,7}\b")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _norm_ws(text: str) -> str:
    return " ".join(text.split())


def check_section(
    ref: str, sec: models.SectionEntry, l2_slice: str, l3_slice: str
) -> list[Finding]:
    l2, l3 = prose_only(l2_slice), prose_only(l3_slice)
    n3 = len(l3)
    findings: list[Finding] = []
    findings += _check_length(ref, l2, l3, n3)
    findings += _check_labels(ref, sec, l2, n3)
    findings += _check_l1_words(ref, sec)
    if l2:
        findings += _check_transcription(ref, l2, l3_slice)
        findings += _check_codes(ref, l2, l3_slice)
        findings += _check_overlap(ref, l2, l3_slice)
    return findings


def _q(code: str, ref: str, msg: str) -> Finding:
    return Finding(code, ref, f"{ref}: {msg}", "quality")


def _check_length(ref: str, l2: str, l3: str, n3: int) -> list[Finding]:
    if n3 > BRIEF_CHARS:
        if not l2:
            return [_q("l2-empty", ref, f"L2 prose is empty while L3 has {n3} chars of prose")]
        limit = budget(n3)
        if len(l2) > limit:
            return [_q("ratio", ref, f"L2 prose {len(l2)} chars > budget {limit} (35% of {n3})")]
        return []
    if is_brief(n3) and _norm_ws(l2) != _norm_ws(l3):
        return [_q("brief-verbatim", ref, f"brief section ({n3} chars of prose) must carry the L3 prose verbatim in L2")]
    return []


def _check_labels(ref: str, sec: models.SectionEntry, l2: str, n3: int) -> list[Finding]:
    if is_table_only(n3):
        want = TABLE_ONLY_LABEL.format(title=sec.title)
        if sec.summary != want or l2:
            return [_q("table-only-label", ref, f"table-only section must have L1 '{want}' and no L2 prose")]
    elif is_brief(n3):
        want = BRIEF_LABEL.format(title=sec.title)
        if sec.summary != want:
            return [_q("brief-label", ref, f"brief section must have L1 '{want}'")]
    return []


def _check_l1_words(ref: str, sec: models.SectionEntry) -> list[Finding]:
    n = len(sec.summary.split())
    if n > L1_MAX_WORDS:
        return [_q("l1-words", ref, f"L1 summary has {n} words > {L1_MAX_WORDS}")]
    return []


def _table_cells(l3_slice: str) -> set[str]:
    cells: set[str] = set()
    for table in extract_tables(l3_slice):
        for row in normalize_table(table).splitlines():
            for cell in row.split("|"):
                c = cell.strip()
                if len(c) >= 2 and not c.replace(".", "").isdigit():
                    cells.add(c)
    return cells


def _check_transcription(ref: str, l2: str, l3_slice: str) -> list[Finding]:
    cells = _table_cells(l3_slice)
    if len(cells) < CELLS_PER_SENTENCE:
        return []
    patterns = {c: re.compile(r"(?<!\w)" + re.escape(c) + r"(?!\w)") for c in cells}
    for sentence in _SENTENCE_SPLIT_RE.split(l2):
        hits = [c for c, p in patterns.items() if p.search(sentence)]
        if len(hits) >= CELLS_PER_SENTENCE:
            return [_q("table-transcription", ref,
                       f"L2 sentence quotes {len(hits)} cells of this section's table: '{sentence[:60]}…'")]
    return []


def _check_codes(ref: str, l2: str, l3_slice: str) -> list[Finding]:
    invented = sorted({t for t in _CODE_RE.findall(l2) if t not in l3_slice})
    if invented:
        return [_q("invented-code", ref, f"codes in L2 that do not occur in L3: {', '.join(invented)}")]
    return []


def _check_overlap(ref: str, l2: str, l3_slice: str) -> list[Finding]:
    words = _WORD_RE.findall(l2.lower())
    if len(words) < OVERLAP_MIN_WORDS:
        return []
    types = set(words)
    l3_types = set(_WORD_RE.findall(l3_slice.lower()))
    share = len(types & l3_types) / len(types)
    if share < OVERLAP_MIN:
        return [_q("lexical-overlap", ref, f"only {share:.0%} of L2 word-types occur in L3 (< {OVERLAP_MIN:.0%})")]
    return []


def check_doc(entry: models.IndexEntry) -> list[Finding]:
    if not entry.summary.strip():
        return [Finding("l0-empty", entry.id, f"{entry.id}: index.yaml summary is empty", "error")]
    n = len(entry.summary.split())
    if n > L0_MAX_WORDS:
        return [_q("l0-words", entry.id, f"index.yaml summary has {n} words > {L0_MAX_WORDS}")]
    return []
```

Move the two `import` lines to the import block at the top of the file (drop the `# noqa: E402`). Check there is no import cycle: `quality` imports `models` and `mdutils` only; neither imports `quality`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_quality.py -q`
Expected: all PASS. If `test_lexical_overlap_fires…` fails, confirm the Vietnamese L2 has ≥ 20 `\w+` tokens (it does: 30+) and that fewer than 45 % of them occur in `LONG_PROSE`.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/quality.py tests/test_quality.py
git commit -F <msgfile>   # "feat(quality): deterministic C2 section and doc checks"
```

---

### Task 3: Manifest schema — `Provenance`, `ReviewRecord`, new `SectionEntry` fields, `effort` Literal, `exclude_none`

**Files:**
- Modify: `src/center_kb/models.py`
- Modify: `tests/test_models.py`

**Interfaces:**
- Produces:
  - `class Provenance(BaseModel): runner: str; model: str = ""; effort: str = ""; prompt_sha: str = ""; at: str = ""`
  - `class ReviewRecord(BaseModel): by: str; at: str; l2_sha256: str`
  - `SectionEntry.l3_sha256: str = ""`, `SectionEntry.provenance: Provenance | None = None`, `SectionEntry.reviewed: ReviewRecord | None = None`
  - `LLMConfig.effort: Literal["low", "medium", "high"] = "high"`
  - `save_yaml_model` dumps with `exclude_none=True`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_models.py`:

```python
import yaml


def test_section_entry_new_fields_default_absent_and_roundtrip(tmp_path: Path):
    sec = models.SectionEntry(id="1", title="T", file="f")
    assert sec.l3_sha256 == "" and sec.provenance is None and sec.reviewed is None
    sec.provenance = models.Provenance(runner="claude", model="sonnet-5", effort="high",
                                       prompt_sha="abc123abc123", at="2026-09-09T10:00:00Z")
    sec.reviewed = models.ReviewRecord(by="d <d@x>", at="2026-09-09T11:00:00Z", l2_sha256="ff" * 32)
    sec.l3_sha256 = "aa" * 32
    m = models.Manifest(id="d", title="D", sections=[sec])
    path = tmp_path / "_manifest.yaml"
    models.save_yaml_model(path, m)
    loaded = models.load_yaml_model(path, models.Manifest)
    assert loaded == m
    assert loaded.sections[0].reviewed.by == "d <d@x>"


def test_save_omits_none_fields(tmp_path: Path):
    m = models.Manifest(id="d", title="D",
                        sections=[models.SectionEntry(id="1", title="T", file="f")])
    path = tmp_path / "_manifest.yaml"
    models.save_yaml_model(path, m)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "provenance" not in data["sections"][0]
    assert "reviewed" not in data["sections"][0]
    assert "ingested" not in data          # was already None → now omitted


def test_old_manifest_without_new_fields_loads(tmp_path: Path):
    path = tmp_path / "_manifest.yaml"
    path.write_text(
        "id: d\ntitle: D\nsections:\n- {id: '1', title: T, file: f, status: summarized, summary: s}\n",
        encoding="utf-8",
    )
    m = models.load_yaml_model(path, models.Manifest)
    assert m.sections[0].provenance is None and m.sections[0].l3_sha256 == ""


def test_llm_effort_typo_is_rejected():
    with pytest.raises(ValidationError):
        models.LLMConfig(effort="hgih")
    assert models.LLMConfig(effort="medium").effort == "medium"


def test_bundled_manifests_roundtrip_byte_identical():
    """exclude_none must not change how the shipped manifests serialise."""
    from pathlib import Path as _P
    for man in sorted(_P(".kb").glob("*/_manifest.yaml")):
        text = man.read_text(encoding="utf-8")
        obj = models.load_yaml_model(man, models.Manifest)
        dumped = yaml.safe_dump(obj.model_dump(mode="json", exclude_none=True),
                                allow_unicode=True, sort_keys=False)
        assert dumped == text, f"{man} would change on save"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL — `AttributeError: module 'center_kb.models' has no attribute 'Provenance'`

- [ ] **Step 3: Implement the schema**

In `src/center_kb/models.py`, add before `SectionEntry`:

```python
class Provenance(BaseModel):
    """Which runner/model/prompt wrote a section's summaries, and when.
    runner "none" = no LLM call (table-only / brief sections)."""

    runner: str
    model: str = ""
    effort: str = ""
    prompt_sha: str = ""
    at: str = ""


class ReviewRecord(BaseModel):
    """SME sign-off: who, when, and the sha256 of the L2 slice they approved."""

    by: str
    at: str
    l2_sha256: str
```

Extend `SectionEntry`:

```python
class SectionEntry(BaseModel):
    id: str
    title: str
    summary: str = ""
    status: Literal["pending", "summarized", "reviewed"] = "pending"
    file: str
    tokens: SectionTokens = Field(default_factory=SectionTokens)
    l3_sha256: str = ""
    provenance: Provenance | None = None
    reviewed: ReviewRecord | None = None
```

Change `LLMConfig.effort`:

```python
    effort: Literal["low", "medium", "high"] = "high"
```

Change `save_yaml_model`:

```python
    text = yaml.safe_dump(
        obj.model_dump(mode="json", exclude_none=True), allow_unicode=True, sort_keys=False
    )
```

- [ ] **Step 4: Run the tests, then the whole suite**

Run: `uv run pytest tests/test_models.py -q` → PASS.
Run: `uv run pytest -q -x` → PASS. If `test_bundled_manifests_roundtrip_byte_identical` fails because a shipped manifest carries an explicit `ingested: null` or similar, report it in the task summary — do **not** edit `.kb/`; instead relax that one test to compare `yaml.safe_load(dumped) == yaml.safe_load(text)` and note the `null` key in the commit message. If any other test breaks because `ingested`/`ingest` now serialise differently, fix the test expectation, not the model.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/models.py tests/test_models.py
git commit -F <msgfile>   # "feat(models): provenance, review record, l3_sha256; effort Literal; exclude_none"
```

---

### Task 4: `kb build` — two-way table check, one-line tables, orphan headings, no write on failure

**Files:**
- Modify: `src/center_kb/mdutils.py` (`extract_tables`, new `heading_ids`)
- Modify: `src/center_kb/build.py`
- Modify: `tests/test_mdutils.py`, `tests/test_build.py`

**Interfaces:**
- Produces:
  - `mdutils.heading_ids(md: str) -> list[str]` — the `<sid>` of every `## ` heading in order
  - `mdutils.extract_tables` returns one-line pipe blocks too
  - `build._check_tables(errors: list[str], ref: str, l2_slice: str, l3_slice: str) -> None`
  - `build_kb` writes the manifest only when no error was added for that document

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mdutils.py`:

```python
from center_kb.mdutils import extract_tables, heading_ids


def test_extract_tables_keeps_one_line_block():
    md = "## 1 T\n\n| only header |\n\ntext\n"
    assert extract_tables(md) == ["| only header |"]


def test_heading_ids_in_order_ignores_subheadings():
    md = "## 1.1 A\n\n### 1.1.1 child\n\n## 1.2 B\n\n## 1.3\n"
    assert heading_ids(md) == ["1.1", "1.2", "1.3"]
```

Append to `tests/test_build.py` (the fixture `fixture_kb` and `TABLE` come from `tests/conftest.py`):

```python
import pytest

from tests.conftest import TABLE

EXTRA_TABLE = "| X | Y |\n|---|---|\n| 1 | 2 |"


def _l2(fixture_kb):
    return fixture_kb / "demo-doc" / "ch1-records.md"


def _l3(fixture_kb):
    return fixture_kb / "demo-doc" / "ch1-records.raw.md"


def _errors(fixture_kb, **kw):
    return build_kb(fixture_kb, **kw).errors


def test_build_rejects_extra_table_in_l2(fixture_kb):          # case a
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(TABLE, TABLE + "\n\n" + EXTRA_TABLE), encoding="utf-8")
    errs = _errors(fixture_kb)
    assert any("not in L3" in e and "table" in e for e in errs)


def test_build_rejects_duplicated_table_in_l2(fixture_kb):     # case b
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(TABLE, TABLE + "\n\n" + TABLE), encoding="utf-8")
    assert any("duplicated" in e for e in _errors(fixture_kb))


def test_build_rejects_missing_single_row_table(fixture_kb):   # cases d, s
    one_row = "| Only | Header |"
    for p in (_l2(fixture_kb), _l3(fixture_kb)):
        p.write_text(p.read_text(encoding="utf-8").replace("## 1.2 Airway Records", f"{one_row}\n\n## 1.2 Airway Records"), encoding="utf-8")
    assert build_kb(fixture_kb).ok
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(one_row, "| Rewritten | Header |"), encoding="utf-8")
    assert any("missing or altered" in e for e in _errors(fixture_kb))


def test_build_rejects_tables_reordered_within_section(fixture_kb):   # case q
    for p in (_l2(fixture_kb), _l3(fixture_kb)):
        p.write_text(p.read_text(encoding="utf-8").replace(TABLE, TABLE + "\n\n" + EXTRA_TABLE), encoding="utf-8")
    assert build_kb(fixture_kb).ok
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(TABLE + "\n\n" + EXTRA_TABLE, EXTRA_TABLE + "\n\n" + TABLE), encoding="utf-8")
    assert any("reordered" in e for e in _errors(fixture_kb))


def test_build_rejects_orphan_heading(fixture_kb):             # case m
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8") + "\n## 1.9 Ghost\n\nInvented.\n", encoding="utf-8")
    assert any("heading '1.9'" in e and "not in the manifest" in e for e in _errors(fixture_kb))


def test_build_does_not_write_manifest_on_failure(fixture_kb):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    before = mpath.read_text(encoding="utf-8")
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace("| P | Prohibited |", "| P | Permitted |"), encoding="utf-8")
    assert not build_kb(fixture_kb).ok
    assert mpath.read_text(encoding="utf-8") == before        # tokens not persisted


@pytest.mark.parametrize("mutation", [
    ("| P | Prohibited |", "| P    | Prohibited |"),   # e2/e3 whitespace
    ("|---|---|", "|:--|--:|"),                          # e1 alignment
])
def test_build_folds_harmless_table_normalisation(fixture_kb, mutation):
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(*mutation), encoding="utf-8")
    assert build_kb(fixture_kb).ok
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_mdutils.py tests/test_build.py -q`
Expected: FAIL — `ImportError: cannot import name 'heading_ids'`, and the new build tests fail on assertions.

- [ ] **Step 3: Implement `mdutils` changes**

In `src/center_kb/mdutils.py`, change `extract_tables`'s `if len(current) >= 2:` to `if len(current) >= 1:` and add:

```python
def heading_ids(md: str) -> list[str]:
    """Section ids of every `## <id> …` heading, in file order."""
    out: list[str] = []
    for line in md.splitlines():
        m = _HEADING_RE.match(line)
        if m:
            out.append(m.group("sid"))
    return out
```

- [ ] **Step 4: Rewrite `build_kb`**

Replace the body of `src/center_kb/build.py` from `build_kb` through `_read_cached` with:

```python
from collections import Counter

from center_kb.mdutils import (
    count_tokens,
    extract_tables,
    heading_ids,
    normalize_table,
    slice_section,
)


def build_kb(kb_dir: Path, allow_pending: bool = False) -> BuildReport:
    report = BuildReport()
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        report.errors.append(f"not found: {index_path}")
        return report
    index = models.load_yaml_model(index_path, models.KBIndex)
    for entry in index.docs:
        _build_doc(kb_dir, entry, report, allow_pending)
    l0_tokens = count_tokens(index_path.read_text(encoding="utf-8"))
    if l0_tokens > 1000:
        report.warnings.append(
            f"L0 index.yaml = {l0_tokens} tokens (> 1000, review the spec target)"
        )
    return report


def _build_doc(
    kb_dir: Path, entry: models.IndexEntry, report: BuildReport, allow_pending: bool
) -> None:
    manifest_path = kb_dir / entry.id / "_manifest.yaml"
    if not manifest_path.exists():
        report.errors.append(f"{entry.id}: missing _manifest.yaml")
        return
    manifest = models.load_yaml_model(manifest_path, models.Manifest)
    errors_before = len(report.errors)
    file_cache: dict[str, str] = {}
    _check_orphan_headings(report, kb_dir, entry.id, manifest, file_cache)
    tokens: dict[int, models.SectionTokens] = {}
    for row, sec in enumerate(manifest.sections):
        l2_text = _read_cached(kb_dir / entry.id / f"{sec.file}.md", file_cache)
        l3_text = _read_cached(kb_dir / entry.id / f"{sec.file}.raw.md", file_cache)
        ref = f"{entry.id} §{sec.id}"
        l2_slice = slice_section(l2_text, sec.id) if l2_text else None
        l3_slice = slice_section(l3_text, sec.id) if l3_text else None
        if l2_slice is None or l3_slice is None:
            report.errors.append(f"{ref}: section not found in the L2/L3 file")
            continue
        if TODO_MARKER in l2_slice or not sec.summary.strip():
            msg = f"{ref}: still has a TODO marker or an empty summary"
            (report.warnings if allow_pending else report.errors).append(msg)
        _check_tables(report.errors, ref, l2_slice, l3_slice)
        tokens[row] = models.SectionTokens(
            l2=count_tokens(l2_slice), l3=count_tokens(l3_slice)
        )
    if len(report.errors) != errors_before:
        return  # a validate command must not persist state it just rejected
    for row, tk in tokens.items():
        manifest.sections[row].tokens = tk
    models.save_yaml_model(manifest_path, manifest)


def _check_orphan_headings(
    report: BuildReport, kb_dir: Path, doc_id: str, manifest: models.Manifest,
    cache: dict[str, str],
) -> None:
    ids = {s.id for s in manifest.sections}
    for stem in sorted({s.file for s in manifest.sections}):
        for suffix in (".md", ".raw.md"):
            text = _read_cached(kb_dir / doc_id / f"{stem}{suffix}", cache)
            for sid in heading_ids(text):
                if sid not in ids:
                    report.errors.append(
                        f"{doc_id}: heading '{sid}' in {stem}{suffix} is not in the manifest"
                    )


def _check_tables(errors: list[str], ref: str, l2_slice: str, l3_slice: str) -> None:
    """L2 tables must be exactly the L3 tables: same multiset, same order."""
    l2 = [normalize_table(t) for t in extract_tables(l2_slice)]
    l3 = [normalize_table(t) for t in extract_tables(l3_slice)]
    if l2 == l3:
        return
    c2, c3 = Counter(l2), Counter(l3)
    if c2 == c3:
        errors.append(f"{ref}: tables reordered within the section (table integrity fail)")
        return
    missing = sum((c3 - c2).values())
    surplus = c2 - c3
    extra = sum(n for t, n in surplus.items() if t not in c3)
    dup = sum(n for t, n in surplus.items() if t in c3)
    parts = []
    if missing:
        parts.append(f"{missing} L3 table(s) missing or altered in L2")
    if extra:
        parts.append(f"{extra} table(s) in L2 that are not in L3")
    if dup:
        parts.append(f"{dup} table(s) duplicated in L2")
    errors.append(f"{ref}: {'; '.join(parts)} (table integrity fail)")


def _read_cached(path: Path, cache: dict[str, str]) -> str:
    key = str(path)
    if key not in cache:
        cache[key] = path.read_text(encoding="utf-8") if path.exists() else ""
    return cache[key]
```

Keep `TODO_MARKER`, `BuildReport`, `DocStats`, `kb_stats` as they are.

- [ ] **Step 5: Run the tests, then the whole suite**

Run: `uv run pytest tests/test_mdutils.py tests/test_build.py -q` → PASS.
Run: `uv run pytest -q -x` → PASS. `tests/test_summarize.py::test_replace_marker_replaces_only_target_and_keeps_tables` and the scaffold tests are unaffected; if a test relied on `extract_tables` dropping a lone pipe line, update that test's fixture to a two-line table and say so in the commit message.

- [ ] **Step 6: Baseline on the bundled KB**

Run: `uv run kb build --kb-dir .kb`
Expected: `kb build: OK` (no table errors; one-line blocks measured at 0 by the review). If it reports a table error, stop and report — do not edit `.kb/`.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/mdutils.py src/center_kb/build.py tests/test_mdutils.py tests/test_build.py
git commit -F <msgfile>   # "fix(build): two-way table check with multiplicity and order, orphan headings, no write on failure"
```

---

### Task 5: `kb build` — quality findings, hash drift, `--strict`, L0 check, `kb stats` hint

**Files:**
- Modify: `src/center_kb/build.py`
- Modify: `src/center_kb/cli.py:632-650` (`build`), `cli.py:1163-1180` (`stats`)
- Modify: `tests/test_build.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `quality.check_section`, `quality.check_doc`, `quality.digest`, `SectionEntry.l3_sha256`, `SectionEntry.reviewed`
- Produces:
  - `build_kb(kb_dir, allow_pending=False, strict=False) -> BuildReport`
  - `BuildReport.quality: list[str]` (quality warnings when not strict)
  - CLI `kb build --strict`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_build.py`:

```python
from center_kb import quality

LONG = " ".join(f"Sentence number {i} explains the record layout in detail." for i in range(10))


def _make_long_l3(fixture_kb):
    """Turn §1.2 into a > 200-char prose section so ratio/overlap rules apply."""
    p = _l3(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(
        "Full raw text about airway records and route identifiers.", LONG), encoding="utf-8")


def test_quality_findings_are_warnings_by_default(fixture_kb):
    _make_long_l3(fixture_kb)
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(
        "Condensed: airway record structure, route identifiers.", LONG), encoding="utf-8")   # 1.0×
    report = build_kb(fixture_kb)
    assert report.ok
    assert any("§1.2" in q and "budget" in q and q.endswith("(quality)") for q in report.quality)


def test_quality_findings_are_errors_under_strict_and_block_the_write(fixture_kb):
    _make_long_l3(fixture_kb)
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(
        "Condensed: airway record structure, route identifiers.", LONG), encoding="utf-8")
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    before = mpath.read_text(encoding="utf-8")
    report = build_kb(fixture_kb, strict=True)
    assert not report.ok and any("(quality)" in e for e in report.errors)
    assert mpath.read_text(encoding="utf-8") == before


def test_pending_sections_are_not_quality_checked(fixture_kb):
    p = _l2(fixture_kb)
    p.write_text(p.read_text(encoding="utf-8").replace(
        "Condensed: airway record structure, route identifiers.", "<!-- TODO:summarize 1.2 -->"), encoding="utf-8")
    report = build_kb(fixture_kb, allow_pending=True, strict=True)
    assert not any("§1.2" in e and "(quality)" in e for e in report.errors)


def test_l3_hash_drift_is_an_error(fixture_kb):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    m.sections[1].l3_sha256 = quality.digest("something else")
    models.save_yaml_model(mpath, m)
    errs = build_kb(fixture_kb).errors
    assert any("§1.2" in e and "L3 changed since it was summarized" in e for e in errs)


def test_l3_hash_matching_is_silent(fixture_kb):
    from center_kb.mdutils import slice_section
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    l3 = _l3(fixture_kb).read_text(encoding="utf-8")
    m.sections[1].l3_sha256 = quality.digest(slice_section(l3, "1.2"))
    models.save_yaml_model(mpath, m)
    assert build_kb(fixture_kb).ok


def test_reviewed_l2_hash_drift_is_an_error(fixture_kb):
    mpath = fixture_kb / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    m.sections[0].status = "reviewed"
    m.sections[0].reviewed = models.ReviewRecord(by="x", at="t", l2_sha256=quality.digest("old"))
    models.save_yaml_model(mpath, m)
    assert any("L2 changed after review" in e for e in build_kb(fixture_kb).errors)


def test_empty_l0_summary_is_an_error(fixture_kb):
    ipath = fixture_kb / "index.yaml"
    idx = models.load_yaml_model(ipath, models.KBIndex)
    idx.docs[0].summary = ""
    models.save_yaml_model(ipath, idx)
    assert any("index.yaml summary is empty" in e for e in build_kb(fixture_kb).errors)
```

Append to `tests/test_cli.py` (it already imports `CliRunner`, `app`, and uses `fixture_kb`):

```python
def test_build_strict_flag_and_quality_warn_rendering(fixture_kb):
    long = " ".join(f"Sentence number {i} explains the record layout in detail." for i in range(10))
    l3 = fixture_kb / "demo-doc" / "ch1-records.raw.md"
    l3.write_text(l3.read_text(encoding="utf-8").replace(
        "Full raw text about airway records and route identifiers.", long), encoding="utf-8")
    l2 = fixture_kb / "demo-doc" / "ch1-records.md"
    l2.write_text(l2.read_text(encoding="utf-8").replace(
        "Condensed: airway record structure, route identifiers.", long), encoding="utf-8")
    soft = runner.invoke(app, ["build", "--kb-dir", str(fixture_kb)])
    assert soft.exit_code == 0 and "[warn]" in soft.output and "(quality)" in soft.output
    hard = runner.invoke(app, ["build", "--strict", "--kb-dir", str(fixture_kb)])
    assert hard.exit_code == 1 and "[error]" in hard.output and "(quality)" in hard.output


def test_stats_hints_when_tokens_never_built(fixture_kb):
    result = runner.invoke(app, ["stats", "--kb-dir", str(fixture_kb)])
    assert result.exit_code == 0
    assert "run kb build to refresh token counts" in result.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_build.py tests/test_cli.py -q -k "quality or hash or l0 or strict or stats_hints"`
Expected: FAIL — `TypeError: build_kb() got an unexpected keyword argument 'strict'`, etc.

- [ ] **Step 3: Implement in `build.py`**

Add `quality: list[str] = field(default_factory=list)` to `BuildReport`. Change signatures: `build_kb(kb_dir, allow_pending=False, strict=False)` and `_build_doc(kb_dir, entry, report, allow_pending, strict)`. In `build_kb`, before the loop over docs is fine; inside `_build_doc` right after loading the manifest add:

```python
    _add_findings(report, quality.check_doc(entry), strict)
```

Inside the per-section loop, replace the pending block and add hash + quality checks:

```python
        is_pending = TODO_MARKER in l2_slice or not sec.summary.strip()
        if is_pending:
            msg = f"{ref}: still has a TODO marker or an empty summary"
            (report.warnings if allow_pending else report.errors).append(msg)
        _check_tables(report.errors, ref, l2_slice, l3_slice)
        _check_hashes(report.errors, ref, sec, l2_slice, l3_slice)
        if not is_pending:
            _add_findings(report, quality.check_section(ref, sec, l2_slice, l3_slice), strict)
```

Add the helpers:

```python
def _add_findings(report: BuildReport, findings: list[quality.Finding], strict: bool) -> None:
    for f in findings:
        if f.level == "error" or strict:
            report.errors.append(f.text)
        else:
            report.quality.append(f.text)


def _check_hashes(
    errors: list[str], ref: str, sec: models.SectionEntry, l2_slice: str, l3_slice: str
) -> None:
    if sec.l3_sha256 and sec.l3_sha256 != quality.digest(l3_slice):
        errors.append(
            f"{ref}: L3 changed since it was summarized; run "
            f"kb summarize --redo <doc> --section {sec.id}"
        )
    if sec.reviewed is not None and sec.reviewed.l2_sha256 != quality.digest(l2_slice):
        errors.append(f"{ref}: L2 changed after review; approve again or redo the section")
```

Import `from center_kb import models, quality`.

- [ ] **Step 4: CLI**

In `cli.py` `build`:

```python
    strict: bool = typer.Option(
        False, "--strict", help="Treat quality findings (C2 rules) as errors"
    ),
) -> None:
    """Validate KB: no TODOs left, table integrity, C2 quality rules, updated token counts."""
    from center_kb.build import build_kb

    report = build_kb(kb_dir, allow_pending=allow_pending, strict=strict)
    for warning in report.warnings + report.quality:
        typer.secho(f"[warn] {warning}", fg=typer.colors.YELLOW)
    for error in report.errors:
        typer.secho(f"[error] {error}", fg=typer.colors.RED)
    if not report.ok:
        raise typer.Exit(1)
    typer.echo("kb build: OK")
```

In `stats`, after the per-doc lines:

```python
    if all(d.l2_tokens == 0 and d.l3_tokens == 0 for d in docs):
        typer.echo("run kb build to refresh token counts")
```

- [ ] **Step 5: Run the tests, the suite, and the baseline**

Run: `uv run pytest tests/test_build.py tests/test_cli.py tests/test_quality.py -q` → PASS.
Run: `uv run pytest -q -x` → PASS.
Run: `uv run kb build --kb-dir .kb` → exit 0; count the `(quality)` lines and put the number in the commit message body (expected a few hundred: `ratio`, `brief-verbatim`, `brief-label`, `table-transcription`, `invented-code`, `lexical-overlap`).
Run: `uv run kb build --strict --kb-dir .kb` → exit 1.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/build.py src/center_kb/cli.py tests/test_build.py tests/test_cli.py
git commit -F <msgfile>   # "feat(build): C2 quality findings (warn / --strict), hash drift, L0 check, stats hint"
```

---

### Task 6: Summarize engine — prose-based budget, brief/table-only kinds, row keying, provenance + `l3_sha256`

**Files:**
- Modify: `src/center_kb/summarize.py`
- Modify: `tests/test_summarize.py`, `tests/test_summarize_cli.py`, `tests/test_codeingest_scaffold.py:1267-1281` (only if it breaks — see step 5)

**Interfaces:**
- Consumes: `quality.prose_only/budget/is_brief/is_table_only/digest/TABLE_ONLY_LABEL/BRIEF_LABEL`, `models.Provenance`
- Produces:
  - `PendingSection(doc_id, section_id, title, file, l3_body, row: int = 0, l3_sha256: str = "")` with properties `prose_chars -> int`, `kind -> Literal["table_only","brief","llm"]`, `table_only -> bool`
  - `PROMPT_SHA: str` (first 12 hex of sha256 of `SECTION_PROMPT`)
  - `_summarize_one(runner, section) -> dict[str, str]` unchanged contract
  - `summarize_kb(...)` keys results on `(doc_id, row)`; `_apply_results(kb_dir, results, sections, runner, report)` writes `provenance` and `l3_sha256`
  - `RETRY_PAUSE_SECONDS = 1.0` module constant (tests set it to 0)

- [ ] **Step 1: Update and add tests**

In `tests/test_summarize.py`:

1. Replace `test_collect_pending_strips_tables_and_flags_table_only`'s last two asserts with:

```python
    assert by_id["1"].kind == "brief" and by_id["1"].table_only is False
    assert by_id["2"].kind == "table_only" and by_id["2"].table_only is True
    assert by_id["1"].row == 0 and by_id["2"].row == 1
    assert len(by_id["1"].l3_sha256) == 64
```

2. Replace `test_table_only_section_skips_llm`, `_prose_section`, `test_max_chars_floor_and_ratio`:

```python
def test_table_only_section_skips_llm():
    sec = PendingSection("doc1", "2", "Table Only", "f1", "## 2 Table Only\n\n[table omitted]")
    result = _summarize_one(_ExplodingRunner(), sec)
    assert result == {"l2_summary": "", "l1_summary": "Table-only section: Table Only."}


def test_brief_section_copies_prose_verbatim_without_llm():
    body = "## 5.320 HAL\n\nUsed On: PA\nLength: 3\n\n[table omitted]"
    sec = PendingSection("doc1", "5.320", "HAL", "f1", body)
    assert sec.kind == "brief"
    result = _summarize_one(_ExplodingRunner(), sec)
    assert result == {"l2_summary": "Used On: PA\nLength: 3", "l1_summary": "Brief section: HAL."}


from center_kb.summarize import build_section_prompt


def _prose_section(prose: str) -> PendingSection:
    return PendingSection("doc1", "1", "Prose", "f1", prose)


def test_budget_is_measured_on_prose_not_on_headings_or_placeholders():
    body = "## 1 Prose\n\n[table omitted]\n\n" + "p" * 2000 + "\n\n[table omitted]"
    sec = _prose_section(body)
    assert sec.prose_chars == 2000
    assert "at most 700 characters" in build_section_prompt(sec)
```

3. The existing `test_prompt_contains_budget_and_table_rules`, `test_length_guard_*` keep working because `"p" * 2000` is pure prose (budget 700).

4. Add at module level near `FakeRunner`:

```python
@pytest.fixture(autouse=True)
def _no_retry_pause(monkeypatch):
    monkeypatch.setattr(summarize, "RETRY_PAUSE_SECONDS", 0.0)
```

5. Add tests:

```python
def test_retry_pauses_before_second_attempt(monkeypatch):
    monkeypatch.setattr(summarize, "RETRY_PAUSE_SECONDS", 1.0)
    slept: list[float] = []
    monkeypatch.setattr(summarize.time, "sleep", lambda s: slept.append(s))
    class Boom:
        name = "boom"
        def __init__(self): self.n = 0
        def run(self, prompt):
            self.n += 1
            if self.n == 1:
                raise RunnerError("529 overloaded")
            return _reply("fine")
    result = _summarize_one(Boom(), _prose_section("p" * 2000))
    assert result["l2_summary"] == "fine"
    assert len(slept) == 1 and 1.0 <= slept[0] <= 1.5


def test_length_guard_retry_does_not_pause(monkeypatch):
    monkeypatch.setattr(summarize, "RETRY_PAUSE_SECONDS", 1.0)
    slept: list[float] = []
    monkeypatch.setattr(summarize.time, "sleep", lambda s: slept.append(s))
    runner = _ScriptedRunner([_reply("x" * 800), _reply("y" * 100)])
    _summarize_one(runner, _prose_section("p" * 2000))
    assert slept == []


def test_duplicate_ids_each_get_their_own_summary(tmp_path):
    kb = tmp_path / ".kb"
    (kb / "d").mkdir(parents=True)
    (kb / "index.yaml").write_text("docs:\n- id: d\n  title: D\n  summary: s\n", encoding="utf-8")
    long_a = "AAAA " * 60
    long_b = "BBBB " * 60
    (kb / "d" / "f.raw.md").write_text(
        f"## 1.1 Part A\n\n{long_a}\n\n## 1.1 Part B\n\n{long_b}\n", encoding="utf-8")
    (kb / "d" / "f.md").write_text(
        "## 1.1 Part A\n\n<!-- TODO:summarize 1.1 -->\n\n## 1.1 Part B\n\n<!-- TODO:summarize 1.1 -->\n",
        encoding="utf-8")
    (kb / "d" / "_manifest.yaml").write_text(
        "id: d\ntitle: D\nsections:\n"
        "- {id: '1.1', title: Part A, file: f, status: pending}\n"
        "- {id: '1.1', title: Part B, file: f, status: pending}\n", encoding="utf-8")

    class Echo:
        name = "echo"
        def run(self, prompt):
            if "one-line summaries" in prompt:
                return _json.dumps({"summary": "doc"})
            tag = "A" if "AAAA" in prompt else "B"
            return _json.dumps({"l2_summary": f"SUM-{tag}", "l1_summary": f"L1-{tag}"})

    report = summarize.summarize_kb(kb, Echo(), max_workers=2)
    assert report.ok
    l2 = (kb / "d" / "f.md").read_text(encoding="utf-8")
    assert l2.index("SUM-A") < l2.index("SUM-B")
    m = models.load_yaml_model(kb / "d" / "_manifest.yaml", models.Manifest)
    assert [s.summary for s in m.sections] == ["L1-A", "L1-B"]


def test_apply_results_records_provenance_and_l3_hash(tmp_path):
    kb = make_kb(tmp_path, {}, short=True)   # ~30-char bodies → brief → no LLM call
    fake = FakeRunner()
    fake.model, fake.effort = "sonnet-5", "high"
    summarize.summarize_kb(kb, fake, max_workers=1)
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    for sec in m.sections:
        assert len(sec.l3_sha256) == 64
        assert sec.provenance is not None
        assert sec.provenance.prompt_sha == summarize.PROMPT_SHA
        assert sec.provenance.at.endswith("Z")
    # make_kb's sections are brief (< 200 chars of prose) → no LLM call → runner "none"
    assert {s.provenance.runner for s in m.sections} == {"none"}
    assert all(s.provenance.model == "" for s in m.sections)


def test_llm_section_provenance_names_the_runner(tmp_path):
    kb = make_kb(tmp_path, {})               # long bodies → llm kind
    fake = FakeRunner()
    fake.model, fake.effort = "sonnet-5", "high"
    summarize.summarize_kb(kb, fake, max_workers=1)
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].provenance.runner == "fake"
    assert m.sections[0].provenance.model == "sonnet-5"
```

Note for the implementer: `make_kb`'s L3 bodies are ~30 chars, so with the new `brief` kind those sections would no longer call the LLM. Give `make_kb` a `short: bool = False` parameter: by default write `"Alpha body text §2.3 code P. " * 12` and `"Beta body text. " * 20` (both > 200 chars, so every section is an `llm` section and the existing assertions `"Condensed text." in l2` / `"One line."` keep holding); with `short=True` write the original one-liners (used only by `test_apply_results_records_provenance_and_l3_hash`). `FakeRunner.name` stays `"fake"`. `tests/test_summarize_cli.py` imports `make_kb` and needs no change.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_summarize.py -q`
Expected: FAIL on `kind`, `row`, `PROMPT_SHA`, `RETRY_PAUSE_SECONDS`.

- [ ] **Step 3: Implement in `summarize.py`**

Imports: add `import hashlib, random, time`, `from datetime import datetime, timezone`, `from center_kb import quality`, `from center_kb.quality import BRIEF_LABEL, TABLE_ONLY_LABEL, TABLE_PLACEHOLDER`.

Delete `_IGNORABLE_LINE_RE` and `_is_table_only`. Add after the prompts:

```python
PROMPT_SHA = hashlib.sha256(SECTION_PROMPT.encode("utf-8")).hexdigest()[:12]
RETRY_PAUSE_SECONDS = 1.0  # pause before the retry after a RunnerError (tests set 0)
```

Replace `PendingSection`:

```python
@dataclass(frozen=True)
class PendingSection:
    doc_id: str
    section_id: str
    title: str
    file: str  # stem without extension
    l3_body: str  # prose only — tables replaced by TABLE_PLACEHOLDER
    row: int = 0  # index in manifest.sections — ids are not unique
    l3_sha256: str = ""  # digest of the L3 slice that was summarized

    @property
    def prose_chars(self) -> int:
        return len(quality.prose_only(self.l3_body))

    @property
    def kind(self) -> str:
        if quality.is_table_only(self.prose_chars):
            return "table_only"
        if quality.is_brief(self.prose_chars):
            return "brief"
        return "llm"

    @property
    def table_only(self) -> bool:
        return self.kind == "table_only"
```

In `collect_pending`, change the loop to `for row, sec in enumerate(manifest.sections):` and build:

```python
            body = slice_section(raw_cache[sec.file], sec.id) or ""
            out.append(
                PendingSection(
                    entry.id, sec.id, sec.title, sec.file, strip_tables(body),
                    row=row, l3_sha256=quality.digest(body),
                )
            )
```

Replace `_max_chars` and `build_section_prompt`:

```python
def build_section_prompt(section: PendingSection) -> str:
    return SECTION_PROMPT.format(
        section_id=section.section_id,
        title=section.title,
        l3_body=section.l3_body,
        max_chars=quality.budget(section.prose_chars),
    )
```

Replace `_summarize_one`:

```python
def _summarize_one(runner, section: PendingSection) -> dict[str, str]:
    if section.kind == "table_only":
        return {"l2_summary": "", "l1_summary": TABLE_ONLY_LABEL.format(title=section.title)}
    if section.kind == "brief":
        return {
            "l2_summary": quality.prose_only(section.l3_body),
            "l1_summary": BRIEF_LABEL.format(title=section.title),
        }
    limit = quality.budget(section.prose_chars)
    prompt = build_section_prompt(section)
    last: Exception | None = None
    for attempt in range(2):  # 1 try + exactly 1 retry (spec §3.3)
        try:
            reply = parse_json_reply(runner.run(prompt), ("l2_summary", "l1_summary"))
        except (RunnerError, ValueError) as exc:
            last = exc
            if attempt == 0 and RETRY_PAUSE_SECONDS:
                time.sleep(RETRY_PAUSE_SECONDS + random.random() * RETRY_PAUSE_SECONDS / 2)
            continue
        if len(reply["l2_summary"]) <= limit:
            return reply
        last = ValueError(
            f"l2_summary too long: {len(reply['l2_summary'])} chars > limit {limit}"
        )
        prompt = (
            build_section_prompt(section)
            + f"\n\nYour previous l2_summary was {len(reply['l2_summary'])}"
            f" characters — over the {limit}-character hard limit."
            " Reply again, compressed to fit."
        )
    raise RunnerError(str(last))
```

In `summarize_kb`, key by row and pass sections through:

```python
    results: dict[tuple[str, int], dict[str, str]] = {}
    sections = {(s.doc_id, s.row): s for s in pending}
    ...
            try:
                results[(s.doc_id, s.row)] = fut.result()
    ...
    _apply_results(kb_dir, results, sections, runner, report)
```

Replace `_apply_results`:

```python
def _provenance(runner, section: PendingSection) -> models.Provenance:
    at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if section.kind != "llm":
        return models.Provenance(runner="none", prompt_sha=PROMPT_SHA, at=at)
    return models.Provenance(
        runner=getattr(runner, "name", ""), model=getattr(runner, "model", ""),
        effort=getattr(runner, "effort", ""), prompt_sha=PROMPT_SHA, at=at,
    )


def _apply_results(
    kb_dir: Path,
    results: dict[tuple[str, int], dict[str, str]],
    sections: dict[tuple[str, int], PendingSection],
    runner,
    report: SummarizeReport,
) -> None:
    by_doc: dict[str, dict[int, dict[str, str]]] = {}
    for (doc, row), result in results.items():
        by_doc.setdefault(doc, {})[row] = result
    for doc, rows in by_doc.items():
        manifest_path = kb_dir / doc / "_manifest.yaml"
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        l2_cache: dict[str, str] = {}
        for row, sec in enumerate(manifest.sections):
            pair = rows.get(row)
            if pair is None:
                continue
            key = f"{doc}/{sec.id}"
            if sec.file not in l2_cache:
                l2_cache[sec.file] = (kb_dir / doc / f"{sec.file}.md").read_text(encoding="utf-8")
            try:
                l2_cache[sec.file] = replace_marker(l2_cache[sec.file], sec.id, pair["l2_summary"])
            except ValueError:
                report.failed.append(key)
                continue
            pending = sections[(doc, row)]
            sec.summary = pair["l1_summary"]
            sec.status = "summarized"
            sec.l3_sha256 = pending.l3_sha256
            sec.provenance = _provenance(runner, pending)
            sec.reviewed = None
            report.summarized.append(key)
        for stem, text in l2_cache.items():
            (kb_dir / doc / f"{stem}.md").write_text(text, encoding="utf-8", newline="\n")
        models.save_yaml_model(manifest_path, manifest)
```

`replace_marker` replaces the **first** occurrence of the marker, and rows are applied in manifest order, so two rows sharing an id fill their markers in file order — that is what the duplicate-id test asserts.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_summarize.py tests/test_summarize_cli.py tests/test_summarize_e2e.py -q`
Expected: PASS after the fixture adjustments described in step 1.

- [ ] **Step 5: Whole suite**

Run: `uv run pytest -q -x`. `tests/test_codeingest_scaffold.py::test_summarize_redo_with_no_doc_id_does_not_lock_code_ingest_out_of_itself` still calls the old `redo_reset(kb)` — that API changes in Task 9; it is untouched here and must still pass.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/summarize.py tests/test_summarize.py tests/test_summarize_cli.py
git commit -F <msgfile>   # "feat(summarize): prose-based budget, brief sections verbatim, row keying, provenance"
```

---

### Task 7: Summarize engine — balanced-brace JSON parse, L0 refresh and failure accounting

**Files:**
- Modify: `src/center_kb/summarize.py`
- Modify: `tests/test_summarize.py`

**Interfaces:**
- Produces:
  - `parse_json_reply(text, required) -> dict[str, str]` — tries ```` ```json ```` fences first, then every balanced `{…}` span left to right
  - `_fill_doc_summaries(kb_dir, runner, doc_ids, say, report)` appends `<doc>/<doc-summary>` to `report.failed` on failure
  - `summarize_kb` refreshes L0 for in-scope docs with an empty `summary` even when nothing is pending

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_summarize.py`:

```python
OBJ = '{"l2_summary": "long text", "l1_summary": "short"}'


@pytest.mark.parametrize("reply", [
    f"```json\n{OBJ}\n```",
    f"Sure! Here is the JSON:\n{OBJ}",
    f"{OBJ}\nHope that helps!",
    f"{OBJ}\nNote: use {{curly}} braces carefully.",
    f"Analysis {{of the section}}\n{OBJ}",
    f"{OBJ}\n{OBJ}",
    '{"l2_summary": "has {5.3} inside", "l1_summary": "esc \\"q\\""}',
    f"[{OBJ}]",
])
def test_parse_json_reply_survives_realistic_wrappers(reply):
    out = summarize.parse_json_reply(reply, ("l2_summary", "l1_summary"))
    assert out["l1_summary"] in ("short", 'esc "q"')


@pytest.mark.parametrize("bad", [
    '{"l2_summary": "x", "l1_summary": "y",}',            # trailing comma
    "{'l2_summary': 'x', 'l1_summary': 'y'}",             # single quotes
])
def test_parse_json_reply_still_rejects_invalid_json(bad):
    with pytest.raises(ValueError, match="no JSON object"):
        summarize.parse_json_reply(bad, ("l2_summary", "l1_summary"))


def test_no_pending_but_empty_l0_refreshes_doc_summary(tmp_path):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    runner = FakeRunner()
    report = summarize.summarize_kb(kb, runner)
    assert report.ok and report.summarized == []
    assert len(runner.calls) == 1 and "one-line summaries" in runner.calls[0]
    index = models.load_yaml_model(kb / "index.yaml", models.KBIndex)
    assert index.docs[0].summary == "Doc-level summary."


def test_no_pending_and_l0_present_is_noop(tmp_path):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})
    ipath = kb / "index.yaml"
    idx = models.load_yaml_model(ipath, models.KBIndex)
    idx.docs[0].summary = "Already there."
    models.save_yaml_model(ipath, idx)
    runner = FakeRunner()
    summarize.summarize_kb(kb, runner)
    assert runner.calls == []


def test_doc_summary_failure_is_counted(tmp_path):
    kb = make_kb(tmp_path, {})

    class DocFails(FakeRunner):
        def run(self, prompt):
            if "one-line summaries" in prompt:
                raise RunnerError("529")
            return super().run(prompt)

    report = summarize.summarize_kb(kb, DocFails(), max_workers=1)
    assert report.failed == ["d1/<doc-summary>"] and not report.ok
```

Replace the old `test_summarize_kb_no_pending_is_noop` with the two `no_pending` tests above (its premise — no call at all when L0 is empty — is what B-14 rejects).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_summarize.py -q -k "parse_json or no_pending or doc_summary_failure"`
Expected: FAIL (`Note: use {curly}` case raises; noop test sees no call; failure not counted).

- [ ] **Step 3: Implement**

Replace `parse_json_reply`:

```python
_FENCE_RE = re.compile(r"```(?:json)?\s*\n(.*?)```", re.DOTALL)


def _balanced_spans(text: str):
    """Every top-level `{…}` span, left to right, string- and escape-aware."""
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth, in_str, esc = 0, False, False
        for j in range(i, n):
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    yield text[i : j + 1]
                    i = j
                    break
        i += 1


def _candidates(text: str):
    for m in _FENCE_RE.finditer(text):
        yield m.group(1)
    yield from _balanced_spans(text)


def parse_json_reply(text: str, required: tuple[str, ...]) -> dict[str, str]:
    """First JSON object (fenced or balanced) whose required keys are all
    non-empty strings. ValueError otherwise — never a crash path."""
    saw_object = False
    for cand in _candidates(text):
        try:
            data = json.loads(cand)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        saw_object = True
        out = {k: data.get(k) for k in required}
        if all(isinstance(v, str) and v.strip() for v in out.values()):
            return {k: v.strip() for k, v in out.items()}
    if saw_object:
        raise ValueError(f"missing or empty key among: {', '.join(required)}")
    raise ValueError("no JSON object in reply")
```

Replace the early return and the doc-summary call in `summarize_kb`:

```python
    pending = collect_pending(kb_dir, doc_id)
    report = SummarizeReport()
    results: dict[tuple[str, int], dict[str, str]] = {}
    sections = {(s.doc_id, s.row): s for s in pending}
    if pending:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            ...  # unchanged
        _apply_results(kb_dir, results, sections, runner, report)
    touched = {s.doc_id for s in pending}
    _fill_doc_summaries(kb_dir, runner, doc_id, touched, say, report)
```

Replace `_fill_doc_summaries`:

```python
def _fill_doc_summaries(
    kb_dir: Path, runner, doc_id: str | None, touched: set[str],
    say: Callable[[str], None], report: SummarizeReport,
) -> None:
    """Write the L0 sentence for every in-scope doc that has no pending
    section and either was touched in this run or has an empty summary."""
    index_path = kb_dir / "index.yaml"
    index = models.load_yaml_model(index_path, models.KBIndex)
    changed = False
    for entry in index.docs:
        if doc_id and entry.id != doc_id:
            continue
        if entry.id not in touched and entry.summary.strip():
            continue
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        if any(s.status == "pending" for s in manifest.sections):
            continue  # doc not complete yet
        prompt = build_doc_prompt(entry.title, [s.summary for s in manifest.sections])
        try:
            reply = parse_json_reply(runner.run(prompt), ("summary",))
        except (RunnerError, ValueError) as exc:
            report.failed.append(f"{entry.id}/<doc-summary>")
            say(f"[fail] {entry.id}/<doc-summary>: {exc}")
            continue
        entry.summary = reply["summary"]
        changed = True
    if changed:
        models.save_yaml_model(index_path, index)
```

Keep `report.summarized.sort(); report.failed.sort()` at the end of `summarize_kb`.

- [ ] **Step 4: Run the tests and the suite**

Run: `uv run pytest tests/test_summarize.py tests/test_summarize_cli.py tests/test_summarize_e2e.py -q` → PASS.
`tests/test_summarize_cli.py::test_summarize_nothing_pending_exit_0` uses `make_kb` whose index summary is empty: it now makes one doc-summary call through the patched `FakeRunner` and still exits 0 — if it asserts "0 summarized", that still holds.
Run: `uv run pytest -q -x` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/summarize.py tests/test_summarize.py tests/test_summarize_cli.py
git commit -F <msgfile>   # "fix(summarize): balanced-brace JSON parse; refresh empty L0; count doc-summary failures"
```

---

### Task 8: Runner — Copilot on stdin, prompt never in argv, envelope errors, full-prompt test

**Files:**
- Modify: `src/center_kb/llm.py`
- Modify: `tests/cli_stub.py`, `tests/test_llm.py`

**Interfaces:**
- Produces:
  - `Runner.run` sends the prompt on stdin for both runners; asserts `prompt not in cmd`
  - `_extract_reply("claude", stdout)` raises `RunnerError` on `is_error` / `subtype` starting with `error` / missing `result`
  - `tests/cli_stub.py`: `echo(payload)` now consumes stdin too (kept as an alias of `echo_after_stdin`); new `echo_stdin_length()` stub body that prints `len(stdin)` and the last 30 chars

- [ ] **Step 1: Write the failing tests**

In `tests/cli_stub.py` add:

```python
def echo_stdin_length() -> str:
    """Print '<n chars>|<last 30 chars>' of what arrived on stdin."""
    return (
        "import sys\n"
        "data = sys.stdin.read()\n"
        "sys.stdout.write(str(len(data)) + '|' + data[-30:] + '\\n')\n"
    )
```

and make `echo` consume stdin: `def echo(payload): return echo_after_stdin(payload)` (update its docstring: every runner now pipes the prompt).

In `tests/test_llm.py` replace `test_copilot_run_returns_plain_stdout` and add:

```python
from center_kb.summarize import PendingSection, build_section_prompt
from tests.cli_stub import echo_stdin_length


def test_copilot_run_pipes_prompt_on_stdin(tmp_path):
    exe = write_cli_stub(tmp_path, "copilot", echo_stdin_length())
    runner = llm.Runner("copilot", str(exe), "gpt-5", "high", 30)
    prompt = "line one\nline two %PATH% & | > ^ !x!"
    n, tail = runner.run(prompt).split("|", 1)
    assert int(n) == len(prompt) and tail == prompt[-30:]


@pytest.mark.parametrize("name", ["claude", "copilot"])
def test_full_section_prompt_arrives_intact(tmp_path, name):
    """B-1: a real multi-line ~3.5 kB prompt with shell metacharacters must
    reach the CLI byte for byte — through the .cmd shim on Windows."""
    body = ("## 5.7 Route Type\n\n" + "Route type codes & their meaning | see %PATH% ^ !x! > 0.\n" * 60)
    prompt = build_section_prompt(PendingSection("d", "5.7", "Route Type", "f", body))
    assert "\n" in prompt and len(prompt) > 3000
    if name == "claude":
        stub = (
            "import sys, json\n"
            "data = sys.stdin.read()\n"
            "print(json.dumps({'type': 'result', 'result': str(len(data)) + '|' + data[-30:]}))\n"
        )
    else:
        stub = echo_stdin_length()
    exe = write_cli_stub(tmp_path, name, stub)
    runner = llm.Runner(name, str(exe), "m", "high", 30)
    n, tail = runner.run(prompt).split("|", 1)
    assert int(n) == len(prompt) and tail == prompt[-30:]


def test_run_never_puts_the_prompt_in_argv(tmp_path, monkeypatch):
    seen = {}
    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw.get("input")
        class P: returncode, stdout, stderr = 0, '{"type": "result", "result": "ok"}', ""
        return P()
    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    for name in ("claude", "copilot"):
        llm.Runner(name, "x", "m", "high", 1).run("the prompt")
        assert "the prompt" not in seen["cmd"] and seen["input"] == "the prompt"


@pytest.mark.parametrize("envelope", [
    {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "API Error: 500"},
    {"type": "result", "subtype": "error_max_turns", "is_error": True, "result": ""},
    {"type": "result", "subtype": "success"},           # no result key at all
])
def test_claude_envelope_errors_raise(tmp_path, envelope):
    exe = write_cli_stub(tmp_path, "claude", echo_after_stdin(json.dumps(envelope)))
    runner = llm.Runner("claude", str(exe), "sonnet-5", "high", 30)
    with pytest.raises(llm.RunnerError) as ei:
        runner.run("prompt")
    if envelope.get("result"):
        assert "API Error: 500" in str(ei.value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_llm.py -q`
Expected: FAIL — copilot stub receives 0 stdin chars; argv test sees the prompt in `cmd`; envelope test returns a string instead of raising.

- [ ] **Step 3: Implement**

Replace `Runner.run` and `_extract_reply` in `src/center_kb/llm.py`:

```python
    def run(self, prompt: str) -> str:
        """One headless call; returns the model's reply text.

        The prompt ALWAYS travels on stdin: an argv prompt is cut at the
        first newline and %VAR%-expanded by cmd.exe when the executable is
        an npm `.cmd` shim on Windows (review B-1), and hits ARG_MAX on
        every platform for long sections."""
        if self.name == "claude":
            cmd = [self.executable, "-p", "--model", self.model, "--output-format", "json"]
        else:
            # copilot: bare -p reads the prompt from stdin; -s drops metadata
            cmd = [self.executable, "-p", "--model", self.model, "-s"]
        assert prompt not in cmd, "prompt must never be an argv element"
        env = None
        if self.name == "claude" and self.effort == "high":
            env = os.environ | {"MAX_THINKING_TOKENS": HIGH_EFFORT_THINKING_TOKENS}
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=self.timeout, env=env,
            )
        except subprocess.TimeoutExpired as exc:
            raise RunnerError(f"{self.name}: timed out after {self.timeout}s") from exc
        if proc.returncode != 0:
            raise RunnerError(f"{self.name}: exit {proc.returncode}: {proc.stderr.strip()[:500]}")
        return _extract_reply(self.name, proc.stdout)


def _extract_reply(name: str, stdout: str) -> str:
    if name != "claude":
        return stdout.strip()
    # claude --output-format json wraps the reply: {"type":"result","result":"…"}
    try:
        envelope = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()  # older CLI: plain text
    if not isinstance(envelope, dict):
        return stdout.strip()
    subtype = str(envelope.get("subtype", ""))
    if envelope.get("is_error") or subtype.startswith("error"):
        raise RunnerError(f"claude: {envelope.get('result') or subtype or 'error'}")
    result = envelope.get("result")
    if not isinstance(result, str):
        raise RunnerError("claude: no result in envelope")
    return result.strip()
```

- [ ] **Step 4: Run the tests and the suite**

Run: `uv run pytest tests/test_llm.py tests/test_summarize_e2e.py -q` → PASS (the e2e stubs use `echo`, which now drains stdin).
Run: `uv run pytest -q -x` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/llm.py tests/cli_stub.py tests/test_llm.py
git commit -F <msgfile>   # "fix(llm): pipe the Copilot prompt on stdin; honour claude error envelopes"
```

---

### Task 9: `--redo` — plan/preview, scoped reset, reviewed protection, `Figure:` lines, CLI flags

**Files:**
- Modify: `src/center_kb/summarize.py` (`rebuild_l2_scaffold`, new `reset_section_prose`, `RedoItem`, `RedoPlan`, `plan_redo`, `redo_reset(kb_dir, plan)`)
- Modify: `src/center_kb/cli.py:555-605` (`summarize` command)
- Modify: `tests/test_summarize.py`, `tests/test_summarize_cli.py`, `tests/test_codeingest_scaffold.py:1267-1281`, `src/center_kb/codeingest/core.py:560-570` (docstring only)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) RedoItem(doc_id: str, row: int, section_id: str, status: str, reviewed: models.ReviewRecord | None)`
  - `@dataclass RedoPlan(items: list[RedoItem], skipped_reviewed: list[RedoItem])` with property `reviewed_items -> list[RedoItem]`
  - `plan_redo(kb_dir, doc_id: str | None, section_ids: list[str] | None = None, include_reviewed: bool = False) -> RedoPlan` (raises `ValueError` on unknown doc / section id)
  - `redo_reset(kb_dir, plan: RedoPlan) -> RedoReport` (`reset: list[str]`, `reviewed_reset: int`)
  - `reset_section_prose(l2_text: str, section_id: str) -> str`
  - `rebuild_l2_scaffold` keeps `Figure: ` lines
  - CLI: `kb summarize [DOC_ID] --redo [--all] [--include-reviewed] [--yes] [--dry-run] [--section ID]...`

- [ ] **Step 1: Write the failing tests**

In `tests/test_summarize.py`, replace `test_redo_reset_flips_statuses_and_rewrites_l2` and add:

```python
from center_kb.summarize import plan_redo, reset_section_prose

L2_WITH_FIGURE = (
    "## 1 Prose Section\n\nAn old summary paragraph.\n\n"
    "| h |\n|---|\n| v |\n\nFigure: Holding pattern entry sectors\n\n"
    "## 2 Table Only\n\n| h2 |\n|----|\n| v2 |\n"
)
SCAFFOLD_WITH_FIGURE = (
    "## 1 Prose Section\n\n<!-- TODO:summarize 1 -->\n\n"
    "| h |\n|---|\n| v |\n\nFigure: Holding pattern entry sectors\n\n"
    "## 2 Table Only\n\n<!-- TODO:summarize 2 -->\n\n| h2 |\n|----|\n| v2 |\n"
)


def test_rebuild_l2_scaffold_keeps_figure_lines_round_trip():
    assert rebuild_l2_scaffold(L2_WITH_FIGURE).rstrip("\n") == SCAFFOLD_WITH_FIGURE.rstrip("\n")
    assert rebuild_l2_scaffold(SCAFFOLD_WITH_FIGURE).rstrip("\n") == SCAFFOLD_WITH_FIGURE.rstrip("\n")


def test_reset_section_prose_touches_only_that_section():
    out = reset_section_prose(L2_WITH_FIGURE, "1")
    assert "<!-- TODO:summarize 1 -->" in out
    assert "An old summary paragraph." not in out
    assert "Figure: Holding pattern entry sectors" in out
    assert out.endswith("## 2 Table Only\n\n| h2 |\n|----|\n| v2 |")   # §2 untouched
    assert "<!-- TODO:summarize 2 -->" not in out


def _redo_kb(tmp_path):
    kb = tmp_path / ".kb"
    (kb / "doc1").mkdir(parents=True)
    (kb / "index.yaml").write_text("docs:\n- id: doc1\n  title: Doc One\n", encoding="utf-8")
    (kb / "doc1" / "f1.md").write_text(L2_WITH_SUMMARIES, encoding="utf-8")
    (kb / "doc1" / "_manifest.yaml").write_text(
        "id: doc1\ntitle: Doc One\nsections:\n"
        "- {id: '1', title: Prose Section, file: f1, status: summarized, summary: old}\n"
        "- {id: '2', title: Table Only, file: f1, status: reviewed, summary: old2,\n"
        "   reviewed: {by: sme, at: '2026-09-01T00:00:00Z', l2_sha256: abc}}\n",
        encoding="utf-8",
    )
    return kb


def test_plan_redo_skips_reviewed_by_default(tmp_path):
    plan = plan_redo(_redo_kb(tmp_path), "doc1")
    assert [i.section_id for i in plan.items] == ["1"]
    assert [i.section_id for i in plan.skipped_reviewed] == ["2"]
    assert plan.reviewed_items == []


def test_plan_redo_include_reviewed_lists_the_record(tmp_path):
    plan = plan_redo(_redo_kb(tmp_path), "doc1", include_reviewed=True)
    assert [i.section_id for i in plan.items] == ["1", "2"]
    assert plan.reviewed_items[0].reviewed.by == "sme"


def test_plan_redo_section_filter_and_unknown_ids(tmp_path):
    kb = _redo_kb(tmp_path)
    plan = plan_redo(kb, "doc1", section_ids=["1"])
    assert [i.section_id for i in plan.items] == ["1"]
    with pytest.raises(ValueError, match="9"):
        plan_redo(kb, "doc1", section_ids=["9"])
    with pytest.raises(ValueError, match="nope"):
        plan_redo(kb, "nope")


def test_plan_redo_writes_nothing(tmp_path):
    kb = _redo_kb(tmp_path)
    before = (kb / "doc1" / "_manifest.yaml").read_text(encoding="utf-8")
    plan_redo(kb, "doc1", include_reviewed=True)
    assert (kb / "doc1" / "_manifest.yaml").read_text(encoding="utf-8") == before


def test_redo_reset_applies_the_plan_only(tmp_path):
    kb = _redo_kb(tmp_path)
    report = redo_reset(kb, plan_redo(kb, "doc1"))
    assert report.reset == ["doc1/1"] and report.reviewed_reset == 0
    m = models.load_yaml_model(kb / "doc1" / "_manifest.yaml", models.Manifest)
    assert m.sections[0].status == "pending" and m.sections[0].summary == ""
    assert m.sections[0].provenance is None and m.sections[0].l3_sha256 == ""
    assert m.sections[1].status == "reviewed" and m.sections[1].reviewed.by == "sme"
    l2 = (kb / "doc1" / "f1.md").read_text(encoding="utf-8")
    assert "<!-- TODO:summarize 1 -->" in l2 and "<!-- TODO:summarize 2 -->" not in l2


def test_redo_reset_include_reviewed_clears_the_record(tmp_path):
    kb = _redo_kb(tmp_path)
    report = redo_reset(kb, plan_redo(kb, "doc1", include_reviewed=True))
    assert sorted(report.reset) == ["doc1/1", "doc1/2"] and report.reviewed_reset == 1
    m = models.load_yaml_model(kb / "doc1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "pending" and s.reviewed is None for s in m.sections)
```

In `tests/test_summarize_cli.py` replace the two `redo` tests with:

```python
def _reviewed_kb(tmp_path):
    return make_kb(tmp_path, {"1.1": "summarized", "1.2": "reviewed"})


def test_redo_without_doc_or_all_is_refused(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "--redo", "--kb-dir", str(kb)])
    assert result.exit_code == 1 and "--all" in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert [s.status for s in m.sections] == ["summarized", "reviewed"]


def test_redo_doc_skips_reviewed_and_says_so(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "redo: 1 section(s) in d1 will be reset (1 reviewed skipped)" in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert [s.status for s in m.sections] == ["summarized", "reviewed"]


def test_redo_include_reviewed_needs_yes_on_non_tty(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--include-reviewed", "--kb-dir", str(kb)])
    assert result.exit_code == 1
    assert "d1/1.2 reviewed by" in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert m.sections[1].status == "reviewed"


def test_redo_include_reviewed_with_yes_resets_and_resummarizes(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--include-reviewed", "--yes", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    assert "2 summarized, 0 failed." in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" and s.reviewed is None for s in m.sections)


def test_redo_dry_run_writes_nothing(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    before = (kb / "d1" / "_manifest.yaml").read_text(encoding="utf-8")
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--dry-run", "--kb-dir", str(kb)])
    assert result.exit_code == 0 and "will be reset" in result.output
    assert (kb / "d1" / "_manifest.yaml").read_text(encoding="utf-8") == before


def test_redo_all_with_doc_id_is_refused(tmp_path, monkeypatch):
    kb = _reviewed_kb(tmp_path)
    _patch_detect(monkeypatch, FakeRunner())
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--all", "--kb-dir", str(kb)])
    assert result.exit_code == 1


def test_redo_no_runner_does_not_reset(tmp_path, monkeypatch):
    kb = make_kb(tmp_path, {"1.1": "summarized", "1.2": "summarized"})
    _patch_detect(monkeypatch, None)
    result = runner.invoke(app, ["summarize", "d1", "--redo", "--kb-dir", str(kb)])
    assert result.exit_code == 1 and "redo:" not in result.output
    m = models.load_yaml_model(kb / "d1" / "_manifest.yaml", models.Manifest)
    assert all(s.status == "summarized" for s in m.sections)
```

Update `tests/test_codeingest_scaffold.py::test_summarize_redo_with_no_doc_id_does_not_lock_code_ingest_out_of_itself`: replace the `redo_reset(root / ".kb")` line with

```python
    from center_kb.summarize import plan_redo
    redo_reset(root / ".kb", plan_redo(root / ".kb", None))  # --all: every doc, including demo-code
```

and update the docstring at `src/center_kb/codeingest/core.py:565` to say `kb summarize --redo --all`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_summarize.py tests/test_summarize_cli.py -q -k "redo or figure or reset_section"`
Expected: FAIL — `ImportError: cannot import name 'plan_redo'`.

- [ ] **Step 3: Implement in `summarize.py`**

Replace `rebuild_l2_scaffold`, `RedoReport`, `redo_reset` with:

```python
def _scaffold_lines(lines: list[str]) -> list[str]:
    """Headings, tables and Figure: lines survive; every section's prose
    (old summaries, leftover markers) becomes its marker."""
    out: list[str] = []
    for line in lines:
        m = _SECTION_HEAD_RE.match(line)
        if m:
            out += [line, "", f"<!-- TODO:summarize {m.group('sid')} -->", ""]
            continue
        if line.lstrip().startswith("|") or line.startswith("Figure: "):
            out.append(line)
            continue
        if line.strip() == "" and out and (
            out[-1].lstrip().startswith("|") or out[-1].startswith("Figure: ")
        ):
            out.append("")  # the single blank that closes a table/figure block
    return out


def rebuild_l2_scaffold(l2_text: str) -> str:
    """Whole-file form — deterministic and idempotent (used by a whole-doc redo)."""
    return "\n".join(_scaffold_lines(l2_text.splitlines()))


def reset_section_prose(l2_text: str, section_id: str) -> str:
    """Restore the marker in ONE section; every other section is byte-identical."""
    lines = l2_text.splitlines()
    start = next(
        (i for i, ln in enumerate(lines)
         if (m := _SECTION_HEAD_RE.match(ln)) and m.group("sid") == section_id),
        None,
    )
    if start is None:
        raise ValueError(f"section not found in L2: {section_id}")
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    block = _scaffold_lines(lines[start:end])
    if end < len(lines) and block and block[-1] != "":
        block.append("")
    return "\n".join(lines[:start] + block + lines[end:])


@dataclass(frozen=True)
class RedoItem:
    doc_id: str
    row: int
    section_id: str
    status: str
    reviewed: models.ReviewRecord | None


@dataclass
class RedoPlan:
    items: list[RedoItem] = field(default_factory=list)
    skipped_reviewed: list[RedoItem] = field(default_factory=list)

    @property
    def reviewed_items(self) -> list[RedoItem]:
        return [i for i in self.items if i.status == "reviewed"]


def plan_redo(
    kb_dir: Path,
    doc_id: str | None,
    section_ids: list[str] | None = None,
    include_reviewed: bool = False,
) -> RedoPlan:
    """Pure: which rows a redo would reset. doc_id=None means every doc."""
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    known = {e.id for e in index.docs}
    if doc_id and doc_id not in known:
        raise ValueError(f"unknown document: {doc_id}")
    wanted = set(section_ids or [])
    plan = RedoPlan()
    seen: set[str] = set()
    for entry in index.docs:
        if doc_id and entry.id != doc_id:
            continue
        manifest_path = kb_dir / entry.id / "_manifest.yaml"
        if not manifest_path.exists():
            continue
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        for row, sec in enumerate(manifest.sections):
            if wanted and sec.id not in wanted:
                continue
            seen.add(sec.id)
            item = RedoItem(entry.id, row, sec.id, sec.status, sec.reviewed)
            if sec.status == "reviewed" and not include_reviewed:
                plan.skipped_reviewed.append(item)
            else:
                plan.items.append(item)
    missing = sorted(wanted - seen)
    if missing:
        raise ValueError(f"section(s) not found: {', '.join(missing)}")
    return plan


@dataclass
class RedoReport:
    reset: list[str] = field(default_factory=list)  # "doc-id/section-id"
    reviewed_reset: int = 0


def redo_reset(kb_dir: Path, plan: RedoPlan) -> RedoReport:
    """Apply a printed plan: reset the planned rows only, restore their markers."""
    report = RedoReport()
    by_doc: dict[str, list[RedoItem]] = {}
    for item in plan.items:
        by_doc.setdefault(item.doc_id, []).append(item)
    for doc, items in by_doc.items():
        manifest_path = kb_dir / doc / "_manifest.yaml"
        manifest = models.load_yaml_model(manifest_path, models.Manifest)
        l2_cache: dict[str, str] = {}
        for item in items:
            sec = manifest.sections[item.row]
            if sec.status == "reviewed":
                report.reviewed_reset += 1
            if sec.status != "pending":
                report.reset.append(f"{doc}/{sec.id}")
            sec.status, sec.summary, sec.l3_sha256 = "pending", "", ""
            sec.provenance, sec.reviewed = None, None
            path = kb_dir / doc / f"{sec.file}.md"
            if sec.file not in l2_cache and path.exists():
                l2_cache[sec.file] = path.read_text(encoding="utf-8")
            if sec.file in l2_cache and f"<!-- TODO:summarize {sec.id} -->" not in l2_cache[sec.file]:
                l2_cache[sec.file] = reset_section_prose(l2_cache[sec.file], sec.id)
        for stem, text in l2_cache.items():
            (kb_dir / doc / f"{stem}.md").write_text(text, encoding="utf-8", newline="\n")
        models.save_yaml_model(manifest_path, manifest)
    return report
```

Note: two rows sharing an id reset the same block twice; `reset_section_prose` on a block that already carries the marker is a no-op because `_scaffold_lines` is idempotent, and the `not in` guard skips it anyway.

- [ ] **Step 4: CLI**

Replace the `summarize` command in `cli.py`:

```python
@app.command()
def summarize(
    doc_id: str = typer.Argument("", help="Limit to one document (empty = all)"),
    llm: str = typer.Option("", "--llm", help="Runner: claude | copilot | none (default: auto-detect)"),
    max_workers: int = typer.Option(0, help="Parallel LLM calls (default: llm.max_workers in index.yaml)"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    redo: bool = typer.Option(False, "--redo", help="Reset summaries of DOC_ID (or --all) to pending and re-summarize"),
    all_docs: bool = typer.Option(False, "--all", help="With --redo: reset every document in the KB"),
    include_reviewed: bool = typer.Option(False, "--include-reviewed", help="With --redo: also reset reviewed sections (asks for confirmation)"),
    yes: bool = typer.Option(False, "--yes", help="With --redo: skip the confirmation prompt"),
    dry_run: bool = typer.Option(False, "--dry-run", help="With --redo: print what would be reset and stop"),
    section: list[str] = typer.Option([], "--section", help="With --redo: only these section ids (repeatable)"),
) -> None:
    """Fill pending L1/L2 summaries by calling a headless LLM CLI (claude/copilot)."""
    _validate_llm_choice(llm)
    if not (kb_dir / "index.yaml").exists():
        typer.secho(f"not found: {kb_dir / 'index.yaml'}", fg=typer.colors.RED)
        raise typer.Exit(1)
    if redo:
        _redo_or_exit(kb_dir, llm, max_workers, doc_id, all_docs, include_reviewed, yes, dry_run, list(section))
        if dry_run:
            return
    report, reason = _run_summarize(kb_dir, llm, doc_id or None, max_workers)
    if report is None:
        _echo_no_runner(reason)
        raise typer.Exit(1)
    typer.echo(f"{len(report.summarized)} summarized, {len(report.failed)} failed.")
    if report.failed:
        typer.secho("Some sections stay pending — re-run with: kb summarize", fg=typer.colors.YELLOW)
        raise typer.Exit(1)


def _redo_or_exit(kb_dir, llm, max_workers, doc_id, all_docs, include_reviewed, yes, dry_run, sections):
    from center_kb.summarize import plan_redo, redo_reset

    if not doc_id and not all_docs:
        typer.secho("--redo resets every summary; name a document, or pass --all to reset the whole KB.", fg=typer.colors.RED)
        raise typer.Exit(1)
    if doc_id and all_docs:
        typer.secho("--all cannot be combined with a DOC_ID", fg=typer.colors.RED)
        raise typer.Exit(1)
    if sections and not doc_id:
        typer.secho("--section requires a DOC_ID", fg=typer.colors.RED)
        raise typer.Exit(1)
    # Resolve the runner BEFORE resetting: a redo must never wipe summaries
    # when the subsequent run can't happen anyway.
    runner_probe, reason, _ = _resolve_runner(kb_dir, llm, max_workers)
    if runner_probe is None:
        _echo_no_runner(reason)
        raise typer.Exit(1)
    try:
        plan = plan_redo(kb_dir, doc_id or None, sections or None, include_reviewed)
    except ValueError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    scope = doc_id or "the whole KB"
    typer.echo(f"redo: {len(plan.items)} section(s) in {scope} will be reset ({len(plan.skipped_reviewed)} reviewed skipped)")
    for item in plan.reviewed_items:
        rec = item.reviewed
        who = f"{rec.by} at {rec.at}" if rec else "(no record)"
        typer.echo(f"  {item.doc_id}/{item.section_id} reviewed by {who}")
    if dry_run:
        return
    if plan.reviewed_items and not yes:
        try:
            ok = typer.confirm(
                "Reset these reviewed sections? Their L2 text and sign-off will be "
                "removed (recoverable with git checkout).", default=False,
            )
        except typer.Abort:
            ok = False
        if not ok:
            typer.secho("redo aborted — nothing written", fg=typer.colors.YELLOW)
            raise typer.Exit(1)
    rr = redo_reset(kb_dir, plan)
    typer.echo(f"redo: {len(rr.reset)} section(s) reset to pending")
```

The `--print-prompt` option and `_print_prompts` are added in Task 10, not here.

- [ ] **Step 5: Run the tests and the suite**

Run: `uv run pytest tests/test_summarize.py tests/test_summarize_cli.py tests/test_codeingest_scaffold.py -q` → PASS.
Run: `uv run pytest -q -x` → PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/summarize.py src/center_kb/cli.py src/center_kb/codeingest/core.py tests/test_summarize.py tests/test_summarize_cli.py tests/test_codeingest_scaffold.py
git commit -F <msgfile>   # "feat(summarize): scoped --redo with preview, reviewed protection, --dry-run/--section; keep Figure lines"
```

---

### Task 10: `kb summarize --print-prompt`

**Files:**
- Modify: `src/center_kb/cli.py` (`_print_prompts`)
- Modify: `tests/test_summarize_cli.py`

**Interfaces:**
- Consumes: `summarize.collect_pending`, `summarize.build_section_prompt`, `PendingSection.kind`
- Produces: `_print_prompts(kb_dir: Path, doc_id: str, sections: list[str]) -> None` — prints `=== <doc>/<id> ===` blocks; exit 0 with `nothing pending` when none

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_summarize_cli.py`:

```python
from center_kb.summarize import build_section_prompt, collect_pending


def test_print_prompt_emits_the_engine_prompt_verbatim(tmp_path):
    kb = make_kb(tmp_path, {})
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--kb-dir", str(kb)])
    assert result.exit_code == 0, result.output
    expected = {s.section_id: build_section_prompt(s) for s in collect_pending(kb, "d1")}
    for sid, prompt in expected.items():
        assert f"=== d1/{sid} ===" in result.output
        assert prompt in result.output


def test_print_prompt_marks_brief_and_table_only(tmp_path):
    kb = make_kb(tmp_path, {})
    raw = kb / "d1" / "ch1.raw.md"
    raw.write_text("## 1.1 Alpha\n\nShort.\n\n## 1.2 Beta\n\n| h |\n|---|\n| v |\n", encoding="utf-8")
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--kb-dir", str(kb)])
    assert "=== d1/1.1 === [no LLM needed: brief" in result.output
    assert "=== d1/1.2 === [no LLM needed: table-only" in result.output


def test_print_prompt_section_filter_and_nothing_pending(tmp_path):
    kb = make_kb(tmp_path, {"1.2": "summarized"})
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--section", "1.1", "--kb-dir", str(kb)])
    assert result.exit_code == 0 and "=== d1/1.1 ===" in result.output and "d1/1.2" not in result.output
    done = make_kb(tmp_path / "b", {"1.1": "summarized", "1.2": "summarized"})
    result = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--kb-dir", str(done)])
    assert result.exit_code == 0 and "nothing pending" in result.output


def test_print_prompt_requires_doc_id_and_known_section(tmp_path):
    kb = make_kb(tmp_path, {})
    assert runner.invoke(app, ["summarize", "--print-prompt", "--kb-dir", str(kb)]).exit_code == 1
    bad = runner.invoke(app, ["summarize", "d1", "--print-prompt", "--section", "9.9", "--kb-dir", str(kb)])
    assert bad.exit_code == 1 and "9.9" in bad.output
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_summarize_cli.py -q -k print_prompt`
Expected: FAIL (`NameError`/`NotImplementedError` for `_print_prompts`, or unknown option).

- [ ] **Step 3: Implement `_print_prompts` in `cli.py`**

Add the option to the `summarize` command signature and the branch right after the `index.yaml` existence check (before the `--redo` branch):

```python
    print_prompt: bool = typer.Option(False, "--print-prompt", help="Print the engine's prompt for each pending section of DOC_ID and exit"),
```

```python
    if print_prompt:
        _print_prompts(kb_dir, doc_id, list(section))
        return
```

(and widen the `--section` help text to "With --redo/--print-prompt: …"). Then:

```python
def _print_prompts(kb_dir: Path, doc_id: str, sections: list[str]) -> None:
    from center_kb.summarize import build_section_prompt, collect_pending

    if not doc_id:
        typer.secho("--print-prompt requires a DOC_ID", fg=typer.colors.RED)
        raise typer.Exit(1)
    pending = collect_pending(kb_dir, doc_id)
    if sections:
        known = {s.section_id for s in pending}
        missing = [s for s in sections if s not in known]
        if missing:
            typer.secho(f"not pending or not found in {doc_id}: {', '.join(missing)}", fg=typer.colors.RED)
            raise typer.Exit(1)
        pending = [s for s in pending if s.section_id in sections]
    if not pending:
        typer.echo("nothing pending")
        return
    for s in pending:
        head = f"=== {s.doc_id}/{s.section_id} ==="
        if s.kind == "llm":
            typer.echo(head)
            typer.echo(build_section_prompt(s))
        else:
            label = "brief" if s.kind == "brief" else "table-only"
            typer.echo(f"{head} [no LLM needed: {label} — run kb summarize to fill it]")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_summarize_cli.py -q` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py tests/test_summarize_cli.py
git commit -F <msgfile>   # "feat(summarize): --print-prompt for the manual /kb-summarize path"
```

---

### Task 11: `kb approve` — clean-tree gate, strict-build gate, reviewer identity, review record; `kb diff` shows it

**Files:**
- Modify: `src/center_kb/review.py`, `src/center_kb/gitio.py` (new `config_value`), `src/center_kb/diff.py`, `src/center_kb/cli.py` (`approve`)
- Modify: `tests/conftest.py:63-83` (`L3_CONTENT` prose > 200 chars; rev2 text lowercase), `tests/test_gitio.py:31`, `tests/test_review.py`, `tests/test_cli_approve.py`, `tests/test_diff.py`

**Interfaces:**
- Consumes: `build.build_kb(strict=True)`, `gitio.git_root/is_dirty`, `quality.digest`, `models.ReviewRecord`
- Produces:
  - `gitio.config_value(root: Path, key: str) -> str` ("" when unset)
  - `review.check_approvable(kb_dir: Path, doc_id: str) -> list[str]` (errors; empty = OK)
  - `review.resolve_reviewer(root: Path, by: str | None) -> str` (raises `ValueError` when nothing identifies the reviewer)
  - `review.approve_sections(kb_dir, doc_id, section_ids=None, *, by: str) -> ApproveReport`
  - `review.approve_all_changed(kb_dir, against, doc_id=None, *, by: str) -> list[ApproveReport]`
  - `diff.render_diff` line `~ §id title (kinds) — reviewed by <by> at <at>` when a record exists
  - CLI `kb approve … --by "name <email>"`

- [ ] **Step 1: Fixture change so the demo KB passes a strict build**

In `tests/conftest.py` replace `L3_CONTENT`:

```python
L3_CONTENT = f"""## 1.1 Airspace Records

Full raw text about airspace records. Designation, type, multiple code, level. Each airspace record carries the designation of the airspace, its type code from the table below, a multiple code that separates overlapping volumes, and the lower and upper level fields that bound it vertically. The structure is fixed-width and every field is mandatory unless noted.

{TABLE}

## 1.2 Airway Records

Full raw text about airway records and route identifiers. An airway record names the route identifier, the sequence number of each fix along the route, the level and direction restrictions that apply between consecutive fixes, and the cruising table used along the segment. Records are ordered by route identifier then sequence number.
"""
```

In `git_kb`, change the rev2 replacement text `"airspace record structure with NEW multiple code field."` to `"airspace record structure with an amended multiple code field."` (an uppercase `NEW` would be an invented code). Update `tests/test_gitio.py:31` to `assert "amended multiple code field" in new`. Grep `tests/` for any other `"NEW multiple"` and update the same way.

Run: `uv run pytest -q -x` → PASS before touching approve (this isolates fixture fallout: search/diff/web tests that assert on L3 wording must still pass; the first sentence of each section is unchanged on purpose).

- [ ] **Step 2: Write the failing tests**

`tests/test_review.py` — update every `approve_sections(...)` / `approve_all_changed(...)` call to pass `by="sme <sme@x>"`, then add:

```python
from center_kb import quality
from center_kb.review import check_approvable, resolve_reviewer


def test_check_approvable_clean_kb_is_ok(git_kb):
    assert check_approvable(git_kb["kb"], "demo-doc") == []


def test_check_approvable_refuses_dirty_tree(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text("## 1.1 Airspace Records\n\nx\n", encoding="utf-8")
    errs = check_approvable(git_kb["kb"], "demo-doc")
    assert errs and "commit .kb/demo-doc before approving" in errs[0]


def test_check_approvable_refuses_strict_build_errors(git_kb, run_git):
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(l2.read_text(encoding="utf-8") + "\n| X | Y |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "fabricated table")
    errs = check_approvable(git_kb["kb"], "demo-doc")
    assert any("table" in e for e in errs)


def test_check_approvable_only_reports_this_doc(git_kb, run_git):
    other = git_kb["kb"] / "other"
    other.mkdir()
    (other / "f.md").write_text("## 1 A\n\n<!-- TODO:summarize 1 -->\n", encoding="utf-8")
    (other / "f.raw.md").write_text("## 1 A\n\nprose\n", encoding="utf-8")
    models.save_yaml_model(other / "_manifest.yaml", models.Manifest(
        id="other", title="O", sections=[models.SectionEntry(id="1", title="A", file="f")]))
    ipath = git_kb["kb"] / "index.yaml"
    idx = models.load_yaml_model(ipath, models.KBIndex)
    idx.docs.append(models.IndexEntry(id="other", title="O", summary="s"))
    models.save_yaml_model(ipath, idx)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "other doc pending")
    assert check_approvable(git_kb["kb"], "demo-doc") == []


def test_resolve_reviewer_flag_then_git_config(git_kb):
    assert resolve_reviewer(git_kb["root"], "Ada <ada@x>") == "Ada <ada@x>"
    assert resolve_reviewer(git_kb["root"], None) == "test <test@test.local>"


def test_resolve_reviewer_fails_without_identity(tmp_path, run_git):
    run_git(tmp_path, "init")
    run_git(tmp_path, "config", "--local", "user.name", "")
    run_git(tmp_path, "config", "--local", "user.email", "")
    import os
    os.environ.pop("GIT_AUTHOR_NAME", None)
    with pytest.raises(ValueError, match="--by"):
        resolve_reviewer(tmp_path, None)


def test_approve_writes_review_record(git_kb):
    from center_kb.mdutils import slice_section
    approve_sections(git_kb["kb"], "demo-doc", ["1.1"], by="sme <sme@x>")
    m = models.load_yaml_model(git_kb["kb"] / "demo-doc" / "_manifest.yaml", models.Manifest)
    rec = m.sections[0].reviewed
    l2 = (git_kb["kb"] / "demo-doc" / "ch1-records.md").read_text(encoding="utf-8")
    assert rec.by == "sme <sme@x>" and rec.at.endswith("Z")
    assert rec.l2_sha256 == quality.digest(slice_section(l2, "1.1"))
    assert m.sections[1].reviewed is None
```

(The `resolve_reviewer_fails_without_identity` test depends on the machine's global git config; if `git config user.name` still resolves globally, mark that test `@pytest.mark.skipif(bool(subprocess.run(["git","config","--global","user.name"],capture_output=True,text=True).stdout.strip()), reason="global git identity set")`.)

`tests/test_cli_approve.py` — add:

```python
def test_approve_refuses_dirty_tree(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text("## 1.1 Airspace Records\n\nx\n", encoding="utf-8")
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1 and "commit .kb/demo-doc before approving" in result.output
    assert _statuses(git_kb["kb"]) == {"1.1": "summarized", "1.2": "summarized"}


def test_approve_refuses_when_strict_build_fails(git_kb, run_git):
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(l2.read_text(encoding="utf-8") + "\n| X | Y |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "fabricated table")
    result = runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 1 and "table" in result.output
    assert _statuses(git_kb["kb"]) == {"1.1": "summarized", "1.2": "summarized"}


def test_approve_by_flag_is_recorded(git_kb):
    result = runner.invoke(app, ["approve", "demo-doc", "--by", "Ada <ada@x>", "--kb-dir", str(git_kb["kb"])])
    assert result.exit_code == 0, result.output
    m = models.load_yaml_model(git_kb["kb"] / "demo-doc" / "_manifest.yaml", models.Manifest)
    assert {s.reviewed.by for s in m.sections} == {"Ada <ada@x>"}


def test_build_fails_after_l2_edit_post_approval(git_kb, run_git):
    from center_kb.build import build_kb
    assert runner.invoke(app, ["approve", "demo-doc", "--kb-dir", str(git_kb["kb"])]).exit_code == 0
    l2 = git_kb["kb"] / "demo-doc" / "ch1-records.md"
    l2.write_text(l2.read_text(encoding="utf-8").replace("Condensed: airway", "Condensed: AIRWAY"), encoding="utf-8")
    assert any("L2 changed after review" in e for e in build_kb(git_kb["kb"]).errors)
```

`tests/test_diff.py` — add:

```python
def test_render_diff_shows_review_record(git_kb):
    from center_kb.diff import diff_doc, render_diff
    from center_kb.review import approve_sections
    approve_sections(git_kb["kb"], "demo-doc", ["1.1"], by="sme <sme@x>")
    out = render_diff(diff_doc(git_kb["kb"], "demo-doc", against=git_kb["rev1"]))
    assert "~ §1.1 Airspace Records" in out and "reviewed by sme <sme@x> at " in out
```

(`diff_doc` reads the worktree manifest, which now carries the record; the section is "changed" vs rev1 because rev2 amended it.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_review.py tests/test_cli_approve.py tests/test_diff.py -q`
Expected: FAIL — `ImportError: cannot import name 'check_approvable'`, `TypeError: unexpected keyword 'by'`.

- [ ] **Step 4: Implement**

`src/center_kb/gitio.py`:

```python
def config_value(root: Path, key: str) -> str:
    """`git config --get <key>` or "" when unset."""
    proc = _run(root, "config", "--get", key)
    return proc.stdout.strip() if proc.returncode == 0 else ""
```

`src/center_kb/review.py` — add imports `from datetime import datetime, timezone`, `from center_kb import quality`, `from center_kb.build import build_kb`, `from center_kb.mdutils import slice_section`, and:

```python
def check_approvable(kb_dir: Path, doc_id: str) -> list[str]:
    """Approval signs committed content that passes the strict build."""
    kb_abs = kb_dir.resolve()
    root = gitio.git_root(kb_abs)
    if gitio.is_dirty(root, kb_abs / doc_id):
        return [f"commit .kb/{doc_id} before approving; approval signs the committed content"]
    report = build_kb(kb_dir, strict=True)
    prefixes = (f"{doc_id} §", f"{doc_id}:")
    return [e for e in report.errors if e.startswith(prefixes)]


def resolve_reviewer(root: Path, by: str | None) -> str:
    if by and by.strip():
        return by.strip()
    name = gitio.config_value(root, "user.name")
    email = gitio.config_value(root, "user.email")
    if not name and not email:
        raise ValueError("no reviewer identity: pass --by 'name <email>' or set git user.name/user.email")
    return f"{name} <{email}>" if name and email else (name or email)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
```

In `approve_sections(kb_dir, doc_id, section_ids=None, *, by: str)`, read the L2 files once and record on flip:

```python
    l2_cache: dict[str, str] = {}
    at = _now()
    for sec in manifest.sections:
        if wanted is not None and sec.id not in wanted:
            continue
        if sec.status == "summarized":
            if sec.file not in l2_cache:
                l2_cache[sec.file] = (kb_dir / doc_id / f"{sec.file}.md").read_text(encoding="utf-8")
            l2_slice = slice_section(l2_cache[sec.file], sec.id) or ""
            sec.status = "reviewed"
            sec.reviewed = models.ReviewRecord(by=by, at=at, l2_sha256=quality.digest(l2_slice))
            report.flipped.append(sec.id)
        elif sec.status == "pending":
            report.skipped_pending.append(sec.id)
```

`approve_all_changed(kb_dir, against, doc_id=None, *, by: str)` passes `by=by` through.

`src/center_kb/diff.py` — `SectionChange` gains `reviewed_by: str = ""`, `reviewed_at: str = ""`; in `diff_doc` set them from `sec.reviewed` for added and changed sections; in `render_diff` append `f" — reviewed by {c.reviewed_by} at {c.reviewed_at}"` when `c.reviewed_by`.

`cli.py` `approve` — add `by: str = typer.Option("", "--by", help="Reviewer identity 'name <email>' (default: git user.name/email)")`; before the existing `try:` block:

```python
    from center_kb.review import check_approvable, resolve_reviewer
    targets = [doc_id] if doc_id else _doc_ids_with_manifest(kb_dir)
    try:
        root = gitio.git_root(kb_dir.resolve())
        reviewer = resolve_reviewer(root, by or None)
        for did in targets:
            problems = check_approvable(kb_dir, did)
            for p in problems:
                typer.secho(f"[error] {p}", fg=typer.colors.RED)
            if problems:
                typer.secho(f"kb approve: {did} is not approvable — fix the errors above", fg=typer.colors.RED)
                raise typer.Exit(1)
    except (ValueError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
```

and pass `by=reviewer` into `approve_all_changed` / `approve_sections`. Add the helper:

```python
def _doc_ids_with_manifest(kb_dir: Path) -> list[str]:
    index = models.load_yaml_model(kb_dir / "index.yaml", models.KBIndex)
    return [e.id for e in index.docs if (kb_dir / e.id / "_manifest.yaml").exists()]
```

Also update the `kb-approve` skill/command templates (`src/center_kb/templates/init/claude-skill-kb-approve.md`, `copilot-kb-approve.prompt.md`, `cursor-kb-approve.md`, and the repo's `.claude/skills/kb-approve/SKILL.md` if it exists) with one bullet under "Hard rules": *"`kb approve` refuses a dirty `.kb/<doc>` tree and any doc whose `kb build --strict` fails; it records `reviewed: {by, at, l2_sha256}` — pass `--by 'name <email>'` when git has no identity."*

- [ ] **Step 5: Run the tests and the suite**

Run: `uv run pytest tests/test_review.py tests/test_cli_approve.py tests/test_diff.py tests/test_gitio.py -q` → PASS.
Run: `uv run pytest -q -x` → PASS (`test_init.py`/`test_templates.py` may pin approve-template text; update the pins if they assert an exact body).

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/review.py src/center_kb/gitio.py src/center_kb/diff.py src/center_kb/cli.py src/center_kb/templates/init/*kb-approve* .claude/skills/kb-approve tests/conftest.py tests/test_gitio.py tests/test_review.py tests/test_cli_approve.py tests/test_diff.py
git commit -F <msgfile>   # "feat(approve): strict-build + clean-tree gate, reviewer record, kb diff shows sign-off"
```

---

### Task 12: `kb publish` — unreviewed count warning and `--require-reviewed`

**Files:**
- Modify: `src/center_kb/publish.py` (new `unreviewed_sections`), `src/center_kb/cli.py` (`publish`)
- Modify: `tests/test_publish.py`, `tests/test_cli_hub.py` (or a new `tests/test_publish_require_reviewed.py`)

**Interfaces:**
- Produces:
  - `publish.unreviewed_sections(kb_dir: Path) -> tuple[int, int]` — (sections not `reviewed`, docs containing them)
  - CLI `kb publish --require-reviewed` exits 1 before any hub write when the count is > 0; otherwise prints `[warn] N section(s) in M doc(s) are published without SME review` when N > 0

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_publish.py`:

```python
from center_kb.publish import unreviewed_sections


def test_unreviewed_sections_counts_non_reviewed_rows(git_kb):
    assert unreviewed_sections(git_kb["kb"]) == (2, 1)
    mpath = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    m.sections[0].status = "reviewed"
    models.save_yaml_model(mpath, m)
    assert unreviewed_sections(git_kb["kb"]) == (1, 1)
```

Create `tests/test_publish_require_reviewed.py`:

```python
from typer.testing import CliRunner

from center_kb import models
from center_kb.cli import app

runner = CliRunner()


def _args(git_kb, hub_worktree, *extra):
    return ["publish", "--hub", str(hub_worktree), "--repo-id", "demo-kb",
            "--kb-dir", str(git_kb["kb"]), "--direct", *extra]


def test_publish_warns_about_unreviewed_sections(git_kb, hub_worktree):
    result = runner.invoke(app, _args(git_kb, hub_worktree))
    assert result.exit_code == 0, result.output
    assert "[warn] 2 section(s) in 1 doc(s) are published without SME review" in result.output


def test_publish_require_reviewed_refuses_before_any_hub_write(git_kb, hub_worktree):
    result = runner.invoke(app, _args(git_kb, hub_worktree, "--require-reviewed"))
    assert result.exit_code == 1
    assert "without SME review" in result.output
    assert not (hub_worktree / "federation" / "demo-kb").exists()


def test_publish_require_reviewed_passes_when_all_reviewed(git_kb, hub_worktree, run_git):
    mpath = git_kb["kb"] / "demo-doc" / "_manifest.yaml"
    m = models.load_yaml_model(mpath, models.Manifest)
    for s in m.sections:
        s.status = "reviewed"
    models.save_yaml_model(mpath, m)
    run_git(git_kb["root"], "add", "-A")
    run_git(git_kb["root"], "commit", "-m", "reviewed")
    result = runner.invoke(app, _args(git_kb, hub_worktree, "--require-reviewed"))
    assert result.exit_code == 0, result.output
    assert "without SME review" not in result.output
```

If the `publish` command's `hub`/`config` resolution needs a `.kb/config.yaml` for a `child` kind, follow whatever `tests/test_cli_hub.py` does today to invoke `publish` against `hub_worktree` and reuse that setup here.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_publish.py tests/test_publish_require_reviewed.py -q -k "reviewed"`
Expected: FAIL — `ImportError: cannot import name 'unreviewed_sections'`; unknown option `--require-reviewed`.

- [ ] **Step 3: Implement**

`src/center_kb/publish.py`:

```python
def unreviewed_sections(kb_dir: Path) -> tuple[int, int]:
    """(sections whose status is not `reviewed`, docs that contain one)."""
    n_sections = n_docs = 0
    for man_path in sorted(kb_dir.glob("*/_manifest.yaml")):
        manifest = models.load_yaml_model(man_path, models.Manifest)
        n = sum(1 for s in manifest.sections if s.status != "reviewed")
        if n:
            n_sections += n
            n_docs += 1
    return n_sections, n_docs
```

`cli.py` `publish`: add `require_reviewed: bool = typer.Option(False, "--require-reviewed", help="Fail when any section is not reviewed")`. Right after the `--pr/--direct` exclusivity check and before any hub resolution:

```python
    n_sec, n_docs = publish_mod.unreviewed_sections(kb_dir)
    if n_sec:
        msg = f"{n_sec} section(s) in {n_docs} doc(s) are published without SME review"
        if require_reviewed:
            typer.secho(f"[error] {msg} — approve them or drop --require-reviewed", fg=typer.colors.RED)
            raise typer.Exit(1)
        typer.secho(f"[warn] {msg}", fg=typer.colors.YELLOW)
```

- [ ] **Step 4: Run the tests and the suite**

Run: `uv run pytest tests/test_publish.py tests/test_publish_require_reviewed.py tests/test_cli_hub.py tests/test_publish_intake_cli.py -q` → PASS (existing CLI publish tests will now print the warning; if one asserts on exact full output, loosen it to a substring).
Run: `uv run pytest -q -x` → PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/publish.py src/center_kb/cli.py tests/test_publish.py tests/test_publish_require_reviewed.py
git commit -F <msgfile>   # "feat(publish): warn on unreviewed sections; --require-reviewed"
```

---

### Task 13: Manual path — skill and templates consume `--print-prompt`; content pins

**Files:**
- Modify: `.claude/skills/kb-summarize/SKILL.md`, `src/center_kb/templates/init/claude-skill-kb-summarize.md` (identical content), `copilot-kb-summarize.instructions.md`, `cursor-kb-summarize.md`, `cursor-kb-summarize.mdc`
- Modify: `tests/test_templates.py`, `tests/test_init.py:503-515`

**Interfaces:**
- Consumes: `kb summarize <doc> --print-prompt [--section …]`, `kb build --strict`
- Produces: templates whose dispatch step never reads L3 directly; a `SUMMARIZE_CANON` pin in `tests/test_templates.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
from importlib import resources

SUMMARIZE_WRAPPERS = [
    "claude-skill-kb-summarize.md",
    "copilot-kb-summarize.instructions.md",
    "cursor-kb-summarize.md",
    "cursor-kb-summarize.mdc",
]


def _tpl(name: str) -> str:
    return resources.files("center_kb.templates.init").joinpath(name).read_text(encoding="utf-8")


def test_repo_kb_summarize_skill_is_the_shipped_template():
    repo = Path(".claude/skills/kb-summarize/SKILL.md").read_text(encoding="utf-8")
    assert repo == _tpl("claude-skill-kb-summarize.md")


@pytest.mark.parametrize("name", SUMMARIZE_WRAPPERS)
def test_summarize_wrappers_use_print_prompt_not_l3(name):
    text = _tpl(name)
    assert "kb summarize <doc-id> --print-prompt" in text
    assert "--level l3" not in text
    assert "kb build --strict" in text
    assert "Table-only section:" not in text or "engine" in text   # engine decides table-only


def test_claude_skill_summarize_contract_and_validation():
    text = _tpl("claude-skill-kb-summarize.md")
    assert '[{"section_id": "...", "l2_summary": "...", "l1_summary": "..."}, ...]' in text
    assert '"table_only"' not in text
    assert "max_chars" in text and "≤ 25 words" in text
    assert "kb build --allow-pending --strict" in text
    assert "max 30 words" in text
```

In `tests/test_init.py::test_kb_summarize_skill_is_parallel_orchestrator` replace `assert '"table_only"' in skill` with `assert "--print-prompt" in skill` and `"kb build --allow-pending"` with `"kb build --allow-pending --strict"`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q -k summarize`
Expected: FAIL on the new assertions.

- [ ] **Step 3: Rewrite `claude-skill-kb-summarize.md` (and copy it byte-for-byte to `.claude/skills/kb-summarize/SKILL.md`)**

```markdown
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

The engine and this workflow send the model the SAME prompt: you never
read L3 yourself and never restate the writing rules — `kb summarize
<doc-id> --print-prompt` prints, per pending section, the exact prompt
the engine would send (tables already removed, an integer `max_chars`
budget, the JSON contract). Sections that need no LLM (table-only or
brief prose) are marked `[no LLM needed: …]` — leave them to
`kb summarize`, which fills them deterministically.

## Workflow

1. **Collect** — run `kb status`; list the pending sections as
   (doc-id, section-id, L2 file). Filter by the doc-id argument if given.
   Nothing pending → report that and stop.
2. **Print prompts** — run `kb summarize <doc-id> --print-prompt` (add
   `--section <id>` to narrow). Keep each `=== <doc-id>/<id> ===` block
   with its `max_chars` value; skip the `[no LLM needed: …]` blocks.
3. **Partition** — group the printed prompts into batches of ~5,
   preferring sections that share the same L2 file. Schedule waves of at
   most 10 batches (= at most 10 concurrent sub-agents).
4. **Dispatch** — spawn ALL sub-agents of the wave in a single message so
   they run concurrently. Each sub-agent prompt MUST contain:
   - the printed prompt blocks for its sections, verbatim;
   - the output contract: reply with ONLY a JSON array —
     `[{"section_id": "...", "l2_summary": "...", "l1_summary": "..."}, ...]`;
   - the hard restriction: the sub-agent is READ-ONLY — it must not
     write, edit, or create any file, and must not run `kb get`.
5. **Merge** — you apply the results yourself, sequentially, never in
   parallel. For each returned section:
   a. Validate: every assigned section present; `l1_summary` ≤ 25 words;
      `len(l2_summary)` ≤ the `max_chars` printed in that section's prompt
      (count characters, not words).
   b. In the L2 file, replace the marker line
      `<!-- TODO:summarize <section-id> -->` with the l2_summary
      paragraph. Do NOT touch the markdown tables or `Figure:` lines
      already present in the section — the tooling copies them verbatim.
   c. In `.kb/<doc-id>/_manifest.yaml`, set that section's `summary:` to
      the l1_summary and change `status: pending` → `status: summarized`.
6. **Verify the wave** — run `kb build --allow-pending --strict`; it must
   pass. A table-integrity error means a table was modified: restore it
   verbatim from the `.raw.md` file. A `(quality)` error names the rule
   the summary broke (ratio, invented code, table transcription, lexical
   overlap): redo that section yourself, sequentially — one retry only.
   Then continue with the next wave (repeat steps 4–6).
7. **Fill the rest** — run `kb summarize <doc-id>` so the engine fills the
   `[no LLM needed: …]` sections (no LLM CLI is required for those).
8. **Finalize** — when every section of a doc is done: open
   `.kb/index.yaml`, fill or fix that doc's `summary` (one sentence, max
   30 words, same language as the section summaries) and verify its
   `title`, `revision` and `tags`. Run `kb build --strict` — it must
   PASS. Report: sections filled, sections still pending (with reasons),
   total L2 tokens (see `kb stats`).

## Error handling

- A sub-agent reply that fails validation (broken JSON, missing section,
  over-length summary) → do NOT respawn an agent. Summarize the failed
  section yourself, sequentially, from its printed prompt — one retry only.
- A section that still fails → leave it `status: pending` and list it in
  the final report.
- Never end a wave with a failing `kb build --allow-pending --strict`.
```

- [ ] **Step 4: Rewrite the Copilot and Cursor wrappers**

`copilot-kb-summarize.instructions.md` and `cursor-kb-summarize.mdc` keep their front matter and "What to edit" section; replace "Writing rules (mandatory)" and "Validate" with:

```markdown
## How to write a summary

Never read the `.raw.md` file to write a summary. Run
`kb summarize <doc-id> --print-prompt` (add `--section <id>` to narrow):
it prints, per pending section, the exact prompt the `kb summarize`
engine sends — tables already removed, an integer `max_chars` budget and
the JSON contract. Answer that prompt and nothing else; keep
`l2_summary` at or under `max_chars` characters and `l1_summary` at or
under 25 words. Sections marked `[no LLM needed: …]` are filled by
`kb summarize <doc-id>` deterministically — leave their markers alone and
run that command.

## Validate

After editing, run `kb build --strict` — it must pass. A table integrity
error means a table was modified: restore it verbatim from the `.raw.md`
file. A `(quality)` error names the rule the summary broke — rewrite that
section from its printed prompt.
```

`cursor-kb-summarize.md` workflow step 2 becomes: *"Run `kb summarize <doc-id> --print-prompt` and, for each printed prompt, write the two summaries it asks for (respecting its `max_chars`), then: in the L2 `.md` file replace the marker …; in `_manifest.yaml` set …"*; step 4 becomes `kb build --strict`; add a step: *"Run `kb summarize <doc-id>` to fill the `[no LLM needed: …]` sections."* Keep the CLI reference list in the Copilot file; add `kb build --strict` and `kb summarize <doc> --print-prompt` rows to it.

- [ ] **Step 5: Run the tests and the suite**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q` → PASS.
Run: `uv run pytest -q -x` → PASS.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills/kb-summarize/SKILL.md src/center_kb/templates/init/*kb-summarize* tests/test_templates.py tests/test_init.py
git commit -F <msgfile>   # "docs(templates): manual kb-summarize path consumes --print-prompt; pin wrappers"
```

---

### Task 14: Docs, spec note, baseline numbers, full verification

**Files:**
- Modify: `README.md` (§4 C1 sentence at line ~78, §7 command table row 4, §7.4, §7.7 approve mention, §10, §11 `reviewed` bullet, troubleshooting table)
- Modify: `docs/superpowers/specs/2026-07-11-summarize-quality-design.md` §3
- Modify: `docs/superpowers/specs/2026-09-09-summarize-build-review-fixes-design.md` (fill the baseline numbers)

- [ ] **Step 1: README edits**

1. Line ~78: replace `if even one character differs, `kb build` fails and blocks the change.` with `if anything differs after whitespace/alignment normalization (NBSP, tabs, trailing spaces, `:--` alignment and extra separator rows are folded; everything else is byte-compared), `kb build` fails and blocks the change — in both directions: a table missing from L2, altered, duplicated, reordered, or invented is rejected.`
2. Command table row 4: `Validate the whole store: no blanks left, tables match both ways, C2 quality rules (warn; `--strict` = error)`.
3. §7.4: after the two PASS conditions add:

```markdown
3. **C2 quality rules** — L2 prose ≤ 35 % of L3 prose (floor 120 chars), no L2 sentence quoting ≥ 4 cells of its own table, no uppercase code in L2 that is absent from L3, ≥ 45 % of L2 words present in L3, L1 ≤ 25 words, table-only / brief sections carry their fixed labels, every `index.yaml` summary filled. Reported as `[warn] … (quality)` by default; `kb build --strict` turns them into errors and is what `kb approve` runs.

`kb build` also fails when a section's L3 changed after it was summarized (`l3_sha256`) or its L2 changed after it was approved (`reviewed.l2_sha256`), and it never writes `_manifest.yaml` while reporting an error.
```

4. §7.4 approve paragraph: `kb approve` requires a clean `.kb/<doc>` tree and a passing `kb build --strict`, records `reviewed: {by, at, l2_sha256}` per section (`--by 'name <email>'` overrides the git identity), and `kb publish` warns how many sections ship unreviewed (`--require-reviewed` makes that fatal).
5. Add to §7.3 (or wherever `kb summarize --redo` is described; if nowhere, add under §7.4 tip): `kb summarize <doc> --redo [--section <id>] [--include-reviewed --yes] [--dry-run]`; `--redo --all` for the whole KB; reviewed sections are skipped unless `--include-reviewed`; sections with ≤ 200 chars of prose are copied verbatim (`Brief section: <title>.`) without an LLM call. Add `kb summarize <doc> --print-prompt` as the manual path's source of prompts.
6. §10: after the `kb stats` table add: `The 11.1 % above was measured before the 2026-09 quality gate (`kb build` now reports it as 325/325 sections over budget); the re-summarize batch replaces this number.`
7. §11 `reviewed` bullet: replace `CENTER-KB does not enforce it.` with `\`kb approve\` now gates on a strict build and records who approved what; \`kb publish --require-reviewed\` enforces it per repo.`
8. Troubleshooting row "table mismatch": add `— or a table was added/duplicated/reordered in L2; \`kb build\` names which.`

- [ ] **Step 2: Spec note**

Append to `docs/superpowers/specs/2026-07-11-summarize-quality-design.md` §3:

```markdown
> **2026-09-09 amendment** (spec `2026-09-09-summarize-build-review-fixes-design.md`):
> the budget is `max(120, 0.35 × prose)` measured on `quality.prose_only()`
> (headings, `[table omitted]`, `Figure:` lines excluded) — the 300-char floor
> made it a 0.45× guard in aggregate; sections with ≤ 200 chars of prose are
> copied verbatim into L2 with the label `Brief section: <title>.` and no LLM
> call; the same rules are enforced by `kb build` (warn / `--strict`).
> Decision #6 (re-run the shipped KB) is still outstanding.
```

- [ ] **Step 3: Baseline numbers into the new spec**

Run on the bundled KB and paste the counts into the spec's "Testing" section, replacing the "expected ≈ …" sentence:

```bash
uv run kb build --kb-dir .kb | grep -c "(quality)"
uv run kb build --kb-dir .kb | sed -n 's/.*: \(.*\) (quality)/\1/p' | awk '{print $1,$2}' | sort | uniq -c | sort -rn | head
uv run kb build --strict --kb-dir .kb; echo "exit=$?"
```

Record: total `(quality)` warnings, top codes by count, and that `--strict` exits 1. `.kb/` itself must remain unmodified (`git status --short .kb` prints nothing).

- [ ] **Step 4: Full verification**

Run: `uv run pytest -q` → all pass (report the count).
Run: `uv run ruff check src tests` (or the project's lint entry in `gate.sh`) → clean.
Run: `uv run kb build --kb-dir .kb` → exit 0; `uv run kb build --strict --kb-dir .kb` → exit 1.
Run: `uv run kb summarize --redo --kb-dir .kb` → exit 1, output mentions `--all`, `git status --short .kb` empty.
On Windows only: `uv run pytest tests/test_llm.py -q` proves the `.cmd` path (it runs there through `write_cli_stub`).

- [ ] **Step 5: Commit**

```bash
git add README.md docs/superpowers/specs/2026-07-11-summarize-quality-design.md docs/superpowers/specs/2026-09-09-summarize-build-review-fixes-design.md
git commit -F <msgfile>   # "docs: kb build quality gate, approve/publish gates, --redo flags; baseline numbers"
```

---

## Parallelism notes for subagent-driven execution

- Tasks 1 → 2 are sequential. Task 3 is independent of 1–2.
- Task 4 depends on nothing new (uses `mdutils` only) but shares `build.py` with Task 5 → run 4 then 5.
- Task 5 depends on 2 and 3. Task 6 depends on 1–3. Tasks 5 and 6 touch disjoint files and can run in parallel (commit with pathspecs — see the memory note on same-checkout commit races).
- Task 7 after 6. Task 8 is independent of everything but shares `tests/cli_stub.py` with `test_summarize_e2e` — run after 6 to avoid fixture churn.
- Task 9 after 7 (it edits `summarize.py` and `cli.py`); Task 10 after 9 (same `cli.py` function).
- Task 11 after 5 (needs strict build) — it changes `tests/conftest.py`, so run it alone, not alongside another task.
- Task 12 after 11. Task 13 after 10. Task 14 last.
