# Wave 4a: duplication and import cycles — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The `strata_kb` import graph has no cycle, counting function-level
imports too. One duplicated lint rule and one hand-rolled heading parse are
removed. Release 1.16.3.

**Architecture:** Three symbols move to acyclic homes:

| Symbol | New home |
|---|---|
| Markdown masking primitives | new leaf `mdmask.py` |
| `_fed_tree_digest` | `federation.py` |
| `AmbiguousDocError` | `errors.py` |

Old homes re-export, so callers keep working. A new layering test walks the
AST and fails on any cycle.

**Tech Stack:** Python 3.11+, pytest (`-n auto`), ruff, pyright basic, uv.

**Spec:** `docs/superpowers/specs/2026-10-11-wave4-debt-cleanup-design.md`, section "Batch 4a".

## Global Constraints

- **No behaviour change.** Output, messages, exit codes and JSON shapes stay
  the same. The two named `hublag` changes in Task 6 are the only exception.
- **Old import paths keep working.** These must all still resolve:
  - `lintcore.FENCE_RE`, `lintcore.HTML_COMMENT_RE`, `lintcore.visible_body`,
    `lintcore._visible_text`, `lintcore._blank_invisible`
  - `doctor._fed_tree_digest`
  - `query.AmbiguousDocError`
- **Lazy imports kept for startup cost stay lazy.** That covers `hub.py:282`,
  every lazy import in `cli.py`, and third-party imports.
- **Gates before the last commit:**
  - `uv run pytest -n auto -q`
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pyright --pythonpath .venv/bin/python`
- **Comments follow the 1.16.1 hygiene rule.** No review, wave or round tags.
  Keep the reason, drop the history.
- **Commits end with the session's attribution trailer.**
- **Branch:** `wave4a-dedupe-cycles`, cut from latest `origin/main`.

## Review Focus

1. **A module imported first, in a fresh interpreter, must still import.** A
   lazy import made module-level can create an import-order failure the full
   suite hides, because by then everything is already loaded. Task 4 adds a
   one-subprocess sweep that imports every module from a clean
   `sys.modules`.
2. **`except AmbiguousDocError` in `cli.py`, `mcp.py` and `web/ui.py` must
   still catch the error `query` raises.** That needs identity, not a copy.
   Pinned in Task 3: `query.AmbiguousDocError is errors.AmbiguousDocError`.
3. **The federation entry digest must not change**, or every published hub
   would read as drifted. Pinned in Task 2 by identity, and by the existing
   `test_fed_tree_digest_*` tests that run through `doctor._fed_tree_digest`.
4. **`kb ticket export` with HTML comments and fences** must give the same
   body after `ticket` switches to `mdmask`. The existing `export_body` tests
   cover it; Task 1 re-runs them by name.
5. **`kb pr lint` with an unterminated `<!--`** must still hide the rest of
   the text. prlint keeps `_UNTERMINATED_COMMENT`. Task 1 re-runs
   `tests/test_prlint.py`.

---

### Task 1: `mdmask` leaf module

**Files:**
- Create: `src/strata_kb/mdmask.py`
- Modify: `src/strata_kb/lintcore.py:22-54` and `:156-204`. Move the five
  definitions out and import them back.
- Modify: `src/strata_kb/ticket.py:121`. Drop the lazy `lintcore` import and
  use `mdmask` at module level.
- Modify: `src/strata_kb/kbcontext.py:57-60` and `:191`. Delete
  `_HTML_COMMENT_RE` and its comment, and use `mdmask.HTML_COMMENT_RE`.
- Modify: `src/strata_kb/prlint.py:35`, `:208` and the docstring at `:3-6`.
- Test: `tests/test_mdmask.py`

**Interfaces:**
- Produces, in `strata_kb.mdmask`, with the same names, regexes, bodies and
  docstrings as today in `lintcore`:
  - `FENCE_RE`
  - `HTML_COMMENT_RE`
  - `visible_body(body: str) -> str`
  - `_visible_text(text: str) -> str`
  - `_blank_invisible(text: str) -> str`
- `mdmask` imports only `re`. Its module docstring starts with
  `mdmask — …` (house style). It names the module as the one home for "what a
  reader sees" in a Markdown body, with comments masked before fences.

- [ ] **Step 1: Write the failing tests** in `tests/test_mdmask.py`:

```python
from strata_kb import lintcore, mdmask


def test_lintcore_names_are_the_mdmask_objects():
    for name in ("FENCE_RE", "HTML_COMMENT_RE", "visible_body",
                 "_visible_text", "_blank_invisible"):
        assert getattr(lintcore, name) is getattr(mdmask, name)


def test_blank_invisible_keeps_line_count_and_blanks_comment_then_fence():
    text = "a\n<!-- x\n``` -->\nb\n```py\ncode\n```\nc\n"
    out = mdmask._blank_invisible(text)
    assert out.count("\n") == text.count("\n")
    assert out.splitlines()[0] == "a" and "c" in out and "code" not in out


def test_visible_body_strips_comments_and_outer_space():
    assert mdmask.visible_body("  <!-- hint -->\n real \n") == "real"
```

- [ ] **Step 2: Run them and check they fail.**
  - Run: `uv run pytest tests/test_mdmask.py -q`
  - Expected: FAIL with `ImportError: cannot import name 'mdmask'`.

- [ ] **Step 3: Create `mdmask.py`.** Move the five definitions with their
  comments and docstrings, unchanged. Then:
  - `lintcore` adds `from strata_kb.mdmask import FENCE_RE, HTML_COMMENT_RE, _blank_invisible, _visible_text, visible_body` with `# noqa: F401 -- re-exported`, the same style as `doctor/__init__.py:23`.
  - `ticket.py` adds `from strata_kb import mdmask` at the top and calls `mdmask.HTML_COMMENT_RE` and `mdmask._blank_invisible`.
  - `kbcontext.py:191` uses `mdmask.HTML_COMMENT_RE`.
  - `prlint` replaces `_COMMENT` with `from strata_kb.mdmask import HTML_COMMENT_RE`. The regex is the same: `re.S` is `re.DOTALL`.
  - `prlint`'s docstring changes "standard library only" to "standard library plus the leaf `strata_kb.mdmask`". Add two or three lines on why it keeps its own fence, comment and section scanner:
    - it handles `~~~` fences, indented fences and unclosed fences;
    - it handles an unterminated `<!--`;
    - it handles `#` and `##` headings with tabs, and counts duplicates;
    - it must not import `lintcore`'s dependencies.

- [ ] **Step 4: Run the new tests and the affected suites. All must pass.**
  - Run: `uv run pytest tests/test_mdmask.py tests/test_lintcore.py tests/test_ticketlint.py tests/test_missionlint.py tests/test_prlint.py tests/test_cli_prlint.py tests/test_kbcontext.py -q -n auto`
  - Also run `uv run pytest -q -n auto -k "export"` to cover `ticket.export_body`.

- [ ] **Step 5: Commit.**
  - Message: `refactor: mdmask leaf for Markdown masking, cut ticket→lintcore lazy import`

---

### Task 2: `_fed_tree_digest` moves to `federation`

**Files:**
- Modify: `src/strata_kb/doctor/checks/hub.py:553-609`.
  - Delete the duplicate `_ENTRY_SEGMENT_RE`, the second of the two
    identical lines at 553 and 556.
  - Move `_FED_TOP_SKIP` and `_fed_tree_digest` out, with their comments and
    docstring, and import them back.
- Modify: `src/strata_kb/federation.py:330-344`. Add the two definitions.
  `entry_content_digest` calls `_fed_tree_digest` directly. Delete the lazy
  import and its "would be circular" comment.
- Keep: `src/strata_kb/doctor/__init__.py:24` re-exports it unchanged. It now
  imports through `checks.hub`, which imports from `federation`.
- Test: `tests/test_doctor_checks.py`. Add one test.

**Interfaces:**
- Produces:
  - `federation._FED_TOP_SKIP: set[str]`, the same value as today:
    `{"index.yaml", "registry.yaml", ".gitkeep"}`.
  - `federation._fed_tree_digest(root: Path, skip: frozenset[str] | set[str] = _FED_TOP_SKIP) -> str`
- If the moved function needs a helper that only `checks/hub.py` has, move
  that helper too. Never import `doctor` from `federation`.

- [ ] **Step 1: Write the failing test.**

```python
def test_fed_tree_digest_has_one_home_in_federation():
    from strata_kb import federation
    from strata_kb.doctor.checks import hub as hub_checks
    assert doctor._fed_tree_digest is federation._fed_tree_digest
    assert hub_checks._FED_TOP_SKIP is federation._FED_TOP_SKIP
```

- [ ] **Step 2: Run it and check it fails.**
  - Run: `uv run pytest tests/test_doctor_checks.py::test_fed_tree_digest_has_one_home_in_federation -q`
  - Expected: FAIL with `AttributeError: module 'strata_kb.federation' has no attribute '_fed_tree_digest'`.

- [ ] **Step 3: Move the code** as listed under Files.

- [ ] **Step 4: Run the tests. All must pass.**
  - Run: `uv run pytest tests/test_doctor_checks.py tests/test_federation*.py tests/test_publish*.py -q -n auto`

- [ ] **Step 5: Commit.**
  - Message: `refactor: _fed_tree_digest lives in federation, cut federation→doctor lazy import`

---

### Task 3: `AmbiguousDocError` moves to `errors`

**Files:**
- Modify: `src/strata_kb/errors.py`.
  - Add the class, unchanged from `query.py:29-39`.
  - Add one docstring paragraph: the module also holds error classes shared
    across modules that sit outside the `KbError` family on purpose. Today
    that is `AmbiguousDocError`, a `LookupError`.
- Modify: `src/strata_kb/query.py:29-39`. Replace the class with
  `from strata_kb.errors import AmbiguousDocError  # noqa: F401 -- re-exported`.
- Modify: `src/strata_kb/kbcontext.py:344`. Import from `strata_kb.errors` at
  module level and delete the lazy import.
- Optional, builder's call: `query.py:300` may import `kbcontext` at module
  level. Both forms are acyclic.
- Modify: `tests/test_cli_errors.py:662`. Re-key the allowlist entry from
  `strata_kb.query.AmbiguousDocError` to `strata_kb.errors.AmbiguousDocError`,
  with the same reason text.
- Test: `tests/test_query.py`. Add one test.

**Interfaces:**
- Produces: `strata_kb.errors.AmbiguousDocError(doc_id: str, repo_ids: list[str])`.
  - It is a `LookupError` with the attributes `.doc_id` and `.repo_ids`.
  - Its message is the same as today.
  - `query.AmbiguousDocError` is the same object.

- [ ] **Step 1: Write the failing test.**

```python
def test_ambiguous_doc_error_is_one_class_with_the_same_message():
    from strata_kb import errors, query
    assert query.AmbiguousDocError is errors.AmbiguousDocError
    err = errors.AmbiguousDocError("d", ["a", "b"])
    assert isinstance(err, LookupError)
    assert str(err) == (
        "doc 'd' exists in 2 federation repos — qualify the ref: a:d, b:d"
    )
```

- [ ] **Step 2: Run it and check it fails.**
  - Run: `uv run pytest tests/test_query.py::test_ambiguous_doc_error_is_one_class_with_the_same_message -q`
  - Expected: FAIL with `AttributeError` on `errors.AmbiguousDocError`.

- [ ] **Step 3: Move the class** as listed under Files.

- [ ] **Step 4: Run the tests. All must pass.**
  - Run: `uv run pytest tests/test_query.py tests/test_cli_errors.py tests/test_kbcontext.py tests/test_mcp*.py tests/test_web*.py -q -n auto`

- [ ] **Step 5: Commit.**
  - Message: `refactor: AmbiguousDocError lives in errors, cut kbcontext→query lazy import`

---

### Task 4: Layering guard — no import cycle, `prlint` and `mdmask` stay stdlib

**Files:**
- Modify: `tests/test_layering.py`.
  - Extend `_imports`. Do not add a second AST walker.
  - Update the module docstring to name the new rules.

**Interfaces:**
- Consumes: Tasks 1–3 must be merged into the branch. The guard is red
  without them.
- Produces, as test-local helpers:
  - `_import_graph() -> dict[str, set[str]]`
  - `_find_cycle(graph: dict[str, set[str]]) -> list[str] | None`

The edge rules are where a wrong guess either misses cycles or flags every
package. They are fixed as follows:

```python
# Module names: path under src/ with "/" → "." and "__init__" dropped.
# Edges: every `import strata_kb.x` / `from strata_kb.x import y` anywhere in
# the file (function bodies included), resolved to the longest name that is
# a module ("strata_kb.x.y" if y is a submodule, else "strata_kb.x"),
# EXCEPT imports nested under `if TYPE_CHECKING:` (skip that whole subtree).
# Each edge to a.b.c also adds edges to the packages a.b and a, because
# importing a.b.c runs their __init__ — but never to the importer's OWN
# parent packages (doctor.checks.hub → doctor is not an edge), or every
# package that re-exports its submodules would be a cycle.
```

- [ ] **Step 1: Write the tests.**
  - `test_find_cycle_reports_a_cycle_and_none_for_a_dag` runs on synthetic
    dicts:
    - `{"a": {"b"}, "b": {"a"}}` → a list holding both `a` and `b`;
    - `{"a": {"b"}, "b": set()}` → `None`.
  - `test_no_import_cycle_even_through_function_level_imports`:
    `assert _find_cycle(_import_graph()) is None`. On failure, the message
    shows the cycle as `" → ".join(cycle)`.
  - `test_prlint_and_mdmask_import_only_the_standard_library`:
    - every module-level and nested import in `prlint.py` and `mdmask.py`
      has a top-level name in `sys.stdlib_module_names`;
    - the one exception: `prlint` may import `strata_kb.mdmask`.
  - `test_every_module_imports_first_in_a_fresh_interpreter`. This is Review
    Focus 1. One `subprocess.run([sys.executable, "-c", SCRIPT])` call, where
    `SCRIPT` loops over every module name. For each one it:
    - deletes every `strata_kb*` key from `sys.modules`;
    - runs `importlib.import_module(name)`;
    - prints the failures.

    The test asserts return code 0 and empty output. Skip modules whose import
    fails only on an optional extra that T0 does not install: `ImportError`
    naming `docling`, `fastembed`, `boto3`, `rapidocr` or `pypdfium2`.

- [ ] **Step 2: Run them. All must pass on this branch.**
  - Run: `uv run pytest tests/test_layering.py -q`

- [ ] **Step 3: Prove the guard bites.**
  - Temporarily add `from strata_kb.query import tokenize` inside any
    function in `kbcontext.py`.
  - Run the cycle test. It must FAIL with a message containing
    `strata_kb.kbcontext` and `strata_kb.query`.
  - Revert the change, then check that `git diff --stat src/` is empty.

- [ ] **Step 4: Commit.**
  - Message: `test: layering guard against import cycles, prlint/mdmask stdlib-only`

---

### Task 5: One `check_required_filled` (A1)

**Files:**
- Modify: `src/strata_kb/lintcore.py`. Add the shared function next to
  `check_headings`.
- Modify: `src/strata_kb/ticketlint.py:185-203` and `:651`.
- Modify: `src/strata_kb/missionlint.py:38-54` and `:374`.
- Test: `tests/test_lintcore.py`

**Interfaces:**
- Produces:
  `lintcore.check_required_filled(text: str, headings: tuple[str, ...], exempt: frozenset[str]) -> list[Issue]`.
  - The body is today's loop.
  - The error message is unchanged:
    `f"'{heading}' is empty or only placeholder text — fill it in"`.
  - The docstring keeps ticketlint's reason, without the "NT1" tag: presence
    alone was the whole contract, so a document of headings over "TBD"s
    passed.
- Callers:
  - `ticketlint`: `lintcore.check_required_filled(text, ticket.REQUIRED_HEADINGS, _FILL_EXEMPT)`
  - `missionlint`: `lintcore.check_required_filled(text, mission.REQUIRED_MISSION_HEADINGS, _FILL_EXEMPT)`
  - Each module keeps its own `_FILL_EXEMPT`.
  - Delete both private `_check_required_filled` functions. If a test calls
    one by name, point it at the shared function.

- [ ] **Step 1: Write the failing test.**

```python
def test_check_required_filled_flags_placeholder_and_skips_exempt_and_missing():
    text = "## A\nTBD\n\n## B\n<!-- hint -->\n\n## C\nreal text here\n"
    issues = lintcore.check_required_filled(
        text, ("## A", "## B", "## C", "## Missing"), frozenset({"## B"})
    )
    assert [i.message for i in issues] == [
        "'## A' is empty or only placeholder text — fill it in"
    ]
    assert all(i.level == "error" for i in issues)
```

- [ ] **Step 2: Run it and check it fails.**
  - Run: `uv run pytest tests/test_lintcore.py::test_check_required_filled_flags_placeholder_and_skips_exempt_and_missing -q`
  - Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Add the shared function and switch both callers.**

- [ ] **Step 4: Run the tests. All must pass.**
  - Run: `uv run pytest tests/test_lintcore.py tests/test_ticketlint.py tests/test_missionlint.py tests/test_cli_ticket*.py tests/test_cli_mission.py -q -n auto`

- [ ] **Step 5: Commit.**
  - Message: `refactor: one check_required_filled for ticket and mission lint`

---

### Task 6: `hublag.l3_sections` uses `HEADING_RE` (A3)

**Files:**
- Modify: `src/strata_kb/codeingest/hublag.py:45-48`.
- Test: `tests/test_codeingest_hublag.py`

**Interfaces:**
- Consumes: `mdutils.HEADING_RE`. The id is in `group("sid")`.
- The loop's shape is fixed:
  - when `HEADING_RE.match(line)` matches, close the current section and open
    a new one;
  - otherwise, when a section is open, append the line to its body;
  - the scan is not fence-aware, the same as today.

- [ ] **Step 1: Write the failing test.** Keep the existing
  `test_l3_sections_split_by_heading_and_drop_the_banner` unchanged.

```python
def test_l3_sections_reads_ids_with_the_section_heading_grammar(tmp_path):
    doc = tmp_path / "doc"
    doc.mkdir()
    (doc / "services.raw.md").write_text(
        "## svc.a\tService a\n\nbody a\n## \nstill a\n\n## svc.b Service b\n\nbody b\n",
        encoding="utf-8",
    )
    assert hublag.l3_sections(doc) == {
        "svc.a": "body a\n## \nstill a",
        "svc.b": "body b",
    }
```

- [ ] **Step 2: Run it and check it fails.**
  - Run: `uv run pytest tests/test_codeingest_hublag.py -q`
  - Expected: FAIL. Today the first id reads `svc.a\tService`, and `## ` opens
    an empty-id section.

- [ ] **Step 3: Switch the parse** to `mdutils.HEADING_RE`.

- [ ] **Step 4: Run the tests. All must pass.**
  - Run: `uv run pytest tests/test_codeingest_hublag.py tests/test_doctor_checks.py -q -n auto`

- [ ] **Step 5: Commit.**
  - Message: `refactor: hublag reads section ids with mdutils.HEADING_RE`

---

### Task 7: Closing notes and release 1.16.3

**Files:**
- Modify: one docstring line each, to record the A5 decision. Each line says
  why the type is separate:
  - `prlint.Finding`: the shape of `kb pr lint --json`, standard library only;
  - `doctor/issues.py` `Issue`: the doctor, ticket and mission lint level
    set;
  - `quality.Finding`: the build-only `quality` level.
- Modify: `docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`
  §8, item 6. Append one sentence in Vietnamese: the sparse worktree for
  intake (F7) is deferred to the Backlog section of
  `docs/superpowers/specs/2026-10-11-wave4-debt-cleanup-design.md`.
- Modify: `CHANGELOG.md`. Add a new `## 1.16.3 — <date>` section at the top,
  in the style of 1.16.2. Cover:
  - no behaviour change except the two `hublag` heading cases;
  - the import graph has no cycle, even through lazy imports, and a guard
    test enforces it;
  - the new `mdmask` module;
  - `_fed_tree_digest` and `AmbiguousDocError` have new homes, and the old
    paths still work;
  - one shared required-section check;
  - A2, A4 and A5 closed by design, one line each.
- Modify: `pyproject.toml` (`version = "1.16.3"`), then run `uv lock` so the
  `strata-kb` entry in `uv.lock` reads `1.16.3`.

- [ ] **Step 1: Make the edits above.**

- [ ] **Step 2: Run the full gates.** Every command must exit 0.
  - `uv run ruff check .`
  - `uv run ruff format --check .`
  - `uv run pyright --pythonpath .venv/bin/python`
  - `uv run pytest -n auto -q`

- [ ] **Step 3: Check that the old lazy imports are gone.**
  - Run: `grep -n "from strata_kb.doctor import _fed_tree_digest\|from strata_kb.query import AmbiguousDocError\|from strata_kb import lintcore  # local" src -r`
  - Expected: no output.

- [ ] **Step 4: Commit and open the PR.**
  - Message: `chore: release 1.16.3`
  - Push `wave4a-dedupe-cycles`.
  - Open the PR titled `refactor: no import cycles, lint dedupe — 1.16.3`.
  - When CI is green, squash-merge.
