# D Conventions Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the conventions pack (roadmap D1–D5): per-language conventions files scaffolded by `kb init --kind dev` via manifest detection, with base + never-touch local override, assistant pointer rules, linter presets embedded in the base files, and dev-plan/dev-execute skill text that points at them.

**Architecture:** A new standalone module `src/center_kb/conventions.py` provides language detection (manifest presence, root + two levels) and a scaffold post-step that `init_repo()` calls for kind `dev` only — the static `template_map()` is untouched. Nine new package template resources carry the content. Two skill-text edits (dev-plan, dev-execute) land in all four wrappers each.

**Tech Stack:** Python ≥3.11, stdlib only (pathlib, importlib.resources), pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-08-24-d-conventions-pack-design.md` — the plan argues from the spec; executors read both.

## Global Constraints

- **No MCP change of any kind.** Never touch `src/center_kb/mcp.py` or anything under `tests-gate/golden/`. At the end, `git diff main...HEAD -- tests-gate/golden src/center_kb/mcp.py` must print nothing.
- **`template_map()` / `expected_files()` in `src/center_kb/initcmd.py` stay untouched.** Conventions files are written by a post-step, never added to the static maps. Do not modify `COMMON_TEMPLATES`, `HUB_TEMPLATES`, `CHILD_TEMPLATES`, `BA_TEMPLATES`, `DEV_TEMPLATES`, or `PROTECTED_FILES`.
- **Never edit the SHARED-\* regions of any dev wrapper** (the `## Freshness re-check`, `## Hard rules`, and `## Next step` blocks). `tests/test_templates.py::test_dev_wrappers_carry_byte_identical_shared_blocks` compares them byte-for-byte against canon.
- **Preserve pinned needles** in the wrappers you edit: the exact substring `` `kb code-ingest` not yet run `` (dev-plan, all four wrappers), `cmd.test` and `cmd.lint`, and every wrapper file must still end with the exact bytes `  Flow order never hides a blocker.\n`.
- **Every file write uses `encoding="utf-8", newline="\n"`** — same as the rest of `initcmd.py`.
- **No new dependencies, no `pyproject.toml` change** (therefore no `uv.lock` regeneration).
- Commands: single test `uv run pytest <path>::<name> -v`; full suite `uv run pytest`; lint `uv run ruff check .`.
- Commit messages: conventional commits (`feat:` / `test:` / `docs:`), no attribution.

## File map (whole batch)

| File | Action | Task |
|---|---|---|
| `src/center_kb/conventions.py` | create | 1, 6, 7 |
| `tests/test_conventions.py` | create | 1, 6, 7 |
| `src/center_kb/templates/init/conventions-python.md` | create | 2 |
| `src/center_kb/templates/init/conventions-ts.md` | create | 2 |
| `src/center_kb/templates/init/conventions-java.md` | create | 3 |
| `src/center_kb/templates/init/conventions-go.md` | create | 3 |
| `src/center_kb/templates/init/conventions-php.md` | create | 4 |
| `src/center_kb/templates/init/conventions-dotnet.md` | create | 4 |
| `src/center_kb/templates/init/conventions-local-stub.md` | create | 5 |
| `src/center_kb/templates/init/conventions-pointer.mdc` | create | 5 |
| `src/center_kb/templates/init/conventions-pointer.instructions.md` | create | 5 |
| `tests/test_templates.py` | modify (append tests) | 2, 3, 4, 5, 9, 10 |
| `src/center_kb/initcmd.py` | modify (wire post-step) | 8 |
| `tests/test_init.py` | modify (append tests) | 8 |
| `src/center_kb/templates/init/claude-skill-dev-plan.md`, `copilot-dev-plan.prompt.md`, `cursor-dev-plan.md`, `claude-command-dev-plan.md` | modify | 9 |
| `src/center_kb/templates/init/claude-skill-dev-execute.md`, `copilot-dev-execute.prompt.md`, `cursor-dev-execute.md`, `claude-command-dev-execute.md` | modify | 10 |

---

### Task 1: Language detection — `detect_langs`

**Files:**
- Create: `src/center_kb/conventions.py`
- Test: `tests/test_conventions.py`

**Interfaces:**
- Consumes: nothing from this batch.
- Produces (later tasks rely on these exact names):
  - `LANG_MANIFESTS: tuple[tuple[str, tuple[str, ...]], ...]` — `(lang_id, manifest_patterns)` pairs, sorted by lang_id.
  - `detect_langs(root: Path) -> list[str]` — sorted, de-duplicated language ids among `"dotnet" | "go" | "java" | "php" | "python" | "ts"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_conventions.py`:

```python
"""Conventions pack — detection + scaffold step (spec
docs/superpowers/specs/2026-08-24-d-conventions-pack-design.md)."""
from pathlib import Path

import pytest

from center_kb.conventions import detect_langs


def _touch(root: Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("rel", "lang"),
    [
        ("pyproject.toml", "python"),
        ("setup.cfg", "python"),
        ("requirements-dev.txt", "python"),
        ("package.json", "ts"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
        ("build.gradle.kts", "java"),
        ("go.mod", "go"),
        ("composer.json", "php"),
        ("App.csproj", "dotnet"),
    ],
)
def test_detects_each_manifest_at_root(tmp_path: Path, rel: str, lang: str):
    _touch(tmp_path, rel)
    assert detect_langs(tmp_path) == [lang]


def test_detects_manifests_up_to_two_levels_below_root(tmp_path: Path):
    _touch(tmp_path, "web/package.json")        # depth 1
    _touch(tmp_path, "services/api/go.mod")     # depth 2
    assert detect_langs(tmp_path) == ["go", "ts"]


def test_ignores_manifests_below_depth_two(tmp_path: Path):
    _touch(tmp_path, "a/b/c/pyproject.toml")    # depth 3
    assert detect_langs(tmp_path) == []


def test_multi_language_repo_is_sorted_and_deduped(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    _touch(tmp_path, "requirements.txt")        # second python manifest: no dupe
    _touch(tmp_path, "web/package.json")
    assert detect_langs(tmp_path) == ["python", "ts"]


def test_skips_vendored_and_internal_directories(tmp_path: Path):
    _touch(tmp_path, "node_modules/left-pad/package.json")
    _touch(tmp_path, "vendor/acme/composer.json")
    _touch(tmp_path, ".kb/demo/go.mod")
    _touch(tmp_path, "docs/samples/pom.xml")
    _touch(tmp_path, ".git/pyproject.toml")
    assert detect_langs(tmp_path) == []


def test_empty_repo_detects_nothing(tmp_path: Path):
    assert detect_langs(tmp_path) == []


def test_directory_named_like_a_manifest_does_not_count(tmp_path: Path):
    (tmp_path / "go.mod").mkdir()
    assert detect_langs(tmp_path) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_conventions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'center_kb.conventions'`.

- [ ] **Step 3: Write the implementation**

Create `src/center_kb/conventions.py`:

```python
"""Conventions pack — language detection + scaffold step for `kb init` (kind dev).

Spec: docs/superpowers/specs/2026-08-24-d-conventions-pack-design.md.

Deliberately standalone: `codeingest.extractors.deps` parses manifest
*contents* (it needs dependency names); this module needs only manifest
*presence*, and must not pull codeingest machinery into the init path.
"""
from __future__ import annotations

from pathlib import Path

LANG_MANIFESTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("dotnet", ("*.csproj",)),
    ("go", ("go.mod",)),
    ("java", ("pom.xml", "build.gradle", "build.gradle.kts")),
    ("php", ("composer.json",)),
    ("python", ("pyproject.toml", "setup.cfg", "requirements*.txt")),
    ("ts", ("package.json",)),
)

# Directories whose contents are someone else's code or generated output —
# a manifest inside them says nothing about what THIS repo is written in.
_SKIP_DIRS = frozenset({".git", ".kb", "docs", "node_modules", "vendor"})


def detect_langs(root: Path) -> list[str]:
    """Language ids whose manifest exists at root or up to two levels below.

    Root is depth 0 (`web/package.json` is depth 1) — the depth the
    codeingest node reader searches. Defensive: unreadable directories are
    skipped, never raised, so a permission error cannot fail `kb init`.
    """
    found: set[str] = set()
    for lang, patterns in LANG_MANIFESTS:
        for pattern in patterns:
            for prefix in ("", "*/", "*/*/"):
                try:
                    hits = list(root.glob(prefix + pattern))
                except OSError:
                    continue
                for hit in hits:
                    parents = hit.relative_to(root).parts[:-1]
                    if any(part in _SKIP_DIRS for part in parents):
                        continue
                    if hit.is_file():
                        found.add(lang)
                        break
    return sorted(found)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_conventions.py -v`
Expected: PASS (all 16).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/center_kb/conventions.py tests/test_conventions.py
git add src/center_kb/conventions.py tests/test_conventions.py
git commit -m "feat: conventions language detection via manifest presence (D2 engine, part 1)"
```

---

### Task 2: Base conventions templates — python + ts

**Files:**
- Create: `src/center_kb/templates/init/conventions-python.md`
- Create: `src/center_kb/templates/init/conventions-ts.md`
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: nothing (pure content).
- Produces: package resources named exactly `conventions-python.md`, `conventions-ts.md` (Task 6 reads them as `conventions-<lang>.md`); a module-level tuple `CONVENTIONS_SECTION_HEADINGS` in `tests/test_templates.py` that Tasks 3–4 reuse.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py` (after the dev-wrapper test section, before EOF):

```python
# --- Batch 5 (D conventions pack): base conventions templates ---------------

CONVENTIONS_SECTION_HEADINGS = (
    "## Naming",
    "## Module structure",
    "## Error handling",
    "## Logging",
    "## Citation comments",
    "## Testing",
    "## Linting (preset)",
)


def test_conventions_python_and_ts_templates_carry_the_full_skeleton():
    for name, needles in (
        (
            "conventions-python.md",
            ("ruff.toml", "ruff check . && ruff format --check .", "logging.getLogger"),
        ),
        (
            "conventions-ts.md",
            ("eslint.config.mjs", "npx eslint . && npx prettier --check .", ".prettierrc.json"),
        ),
    ):
        text = _read_init_template(name)
        for heading in CONVENTIONS_SECTION_HEADINGS:
            assert heading in text, f"{name}: missing {heading!r}"
        for needle in needles:
            assert needle in text, f"{name}: missing {needle!r}"
        assert ".local.md" in text, name          # override pointer in the header
        assert ".editorconfig" in text, name      # editorconfig block present
        assert "per ATM-STD §5.3" in text, name   # citation-comment example
        assert "cmd.lint" in text, name           # preset names the recorded command
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_templates.py::test_conventions_python_and_ts_templates_carry_the_full_skeleton -v`
Expected: FAIL — `FileNotFoundError` for `conventions-python.md`.

- [ ] **Step 3: Create `src/center_kb/templates/init/conventions-python.md`**

Exact content:

````markdown
# Python coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/python.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Modules and packages: `snake_case`, short, no hyphens.
- Functions, methods, variables: `snake_case`, descriptive; booleans read
  as predicates (`is_ready`, `has_pending`, `should_retry`).
- Classes and exceptions: `PascalCase`; exception names end in `Error`.
- Constants: `UPPER_SNAKE_CASE` at module level.
- No abbreviations the codebase does not already use.

## Module structure

- Organise by feature/domain, not by technical layer.
- One clear responsibility per module; ~200–400 lines typical, 800 max —
  extract helpers before crossing it.
- Public surface first: module docstring, constants, then the functions
  and classes callers import; `_`-prefixed helpers below them.
- Imports at the top, grouped stdlib → third-party → local; no wildcard
  imports.

## Error handling

- Raise specific exceptions; never bare `except:` and never
  `except Exception: pass` — a silently swallowed error is a bug.
- Fail fast at boundaries: validate input where data enters the system
  and raise with a message naming the offending value.
- Catch only what the code can actually handle; otherwise re-raise with
  context: `raise NewError(...) from err`.

## Logging

- Use the `logging` module; never `print()` in committed code.
- One logger per module: `logger = logging.getLogger(__name__)`.
- Log where the error is handled, with enough context to act on. DEBUG
  for flow detail, INFO for state changes, WARNING for recoverable
  oddities, ERROR for failures.

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```python
MAX_ALTITUDE_FT = 60_000  # per ATM-STD §5.3 @ v2.1
```

## Testing

- pytest, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `test_rejects_expired_token`, not
  `test_token_2`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

When this repo has no linter, the first task of a dev plan creates the
files below exactly as shown and records the command as `cmd.lint`.

`ruff.toml`:

```toml
target-version = "py311"
line-length = 88

[lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM"]

[format]
quote-style = "double"
```

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.py]
indent_size = 4
```

Install and run:

```
pip install ruff
ruff check . && ruff format --check .
```

Record as `cmd.lint`: `ruff check . && ruff format --check .`
````

- [ ] **Step 4: Create `src/center_kb/templates/init/conventions-ts.md`**

Exact content:

````markdown
# TypeScript / JavaScript coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/ts.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Variables and functions: `camelCase`, descriptive; booleans read as
  predicates (`isReady`, `hasPending`, `shouldRetry`).
- Types, interfaces, classes, enums, React components: `PascalCase`.
- Constants: `UPPER_SNAKE_CASE` for true module-level constants.
- Files: follow the repo's dominant style; when there is none,
  `kebab-case.ts` for modules, `PascalCase.tsx` for components.

## Module structure

- Organise by feature/domain, not by technical layer.
- One clear responsibility per file; ~200–400 lines typical, 800 max —
  extract before crossing it.
- Prefer named exports; a default export only for the file's single main
  artifact (e.g. a component).
- No deep relative import chains (`../../../`) — use the repo's path
  aliases when it has them.

## Error handling

- Throw `Error` subclasses, never strings; never swallow a rejection —
  every promise is awaited, returned, or explicitly `.catch`-handled.
- Fail fast at boundaries: validate external data (API responses, user
  input, file content) before it crosses into typed code.
- `catch` only what the code can handle; rethrow with cause otherwise:
  `throw new AppError("...", { cause: err })`.

## Logging

- Use the repo's logging facility; never `console.log` in committed
  code (a structured logger, or nothing).
- Log where the error is handled, with enough context to act on.

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```ts
const MAX_ALTITUDE_FT = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- The repo's test runner (vitest/jest), AAA shape, one behaviour per
  test.
- Names describe the behaviour: `test("rejects expired token")`, not
  `test("token 2")`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

When this repo has no linter, the first task of a dev plan creates the
files below exactly as shown and records the command as `cmd.lint`.

`eslint.config.mjs`:

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
);
```

`.prettierrc.json`:

```json
{
  "singleQuote": false,
  "trailingComma": "all"
}
```

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space
indent_size = 2
```

Install and run:

```
npm install --save-dev eslint @eslint/js typescript-eslint prettier
npx eslint . && npx prettier --check .
```

Record as `cmd.lint`: `npx eslint . && npx prettier --check .`
````

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_templates.py::test_conventions_python_and_ts_templates_carry_the_full_skeleton -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/conventions-python.md src/center_kb/templates/init/conventions-ts.md tests/test_templates.py
git commit -m "feat: python + ts base conventions templates (D2 content)"
```

---

### Task 3: Base conventions templates — java + go

**Files:**
- Create: `src/center_kb/templates/init/conventions-java.md`
- Create: `src/center_kb/templates/init/conventions-go.md`
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: `CONVENTIONS_SECTION_HEADINGS` from `tests/test_templates.py` (defined in Task 2 — a tuple of the seven `## ` headings every base file carries).
- Produces: package resources `conventions-java.md`, `conventions-go.md`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_conventions_java_and_go_templates_carry_the_full_skeleton():
    for name, needles in (
        (
            "conventions-java.md",
            ("spotless", "checkstyle", "googleJavaFormat", "spotlessCheck"),
        ),
        (
            "conventions-go.md",
            (".golangci.yml", "golangci-lint run", "gofmt"),
        ),
    ):
        text = _read_init_template(name)
        for heading in CONVENTIONS_SECTION_HEADINGS:
            assert heading in text, f"{name}: missing {heading!r}"
        for needle in needles:
            assert needle in text, f"{name}: missing {needle!r}"
        assert ".local.md" in text, name
        assert ".editorconfig" in text, name
        assert "per ATM-STD §5.3" in text, name
        assert "cmd.lint" in text, name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_templates.py::test_conventions_java_and_go_templates_carry_the_full_skeleton -v`
Expected: FAIL — `FileNotFoundError` for `conventions-java.md`.

- [ ] **Step 3: Create `src/center_kb/templates/init/conventions-java.md`**

Exact content:

````markdown
# Java coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/java.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Packages: all-lowercase, no underscores (`com.acme.billing`).
- Classes, interfaces, enums, records: `PascalCase`; exceptions end in
  `Exception`.
- Methods and fields: `camelCase`; booleans read as predicates
  (`isReady`, `hasPending`).
- Constants (`static final`): `UPPER_SNAKE_CASE`.

## Module structure

- Organise packages by feature/domain, not by technical layer alone.
- One top-level type per file; keep classes focused — extract before a
  class grows past ~400 lines.
- Depend on interfaces at boundaries; keep constructors injectable (no
  hidden `new` of collaborators in business logic).

## Error handling

- Throw specific exceptions; never `catch (Exception e) {}` — a
  swallowed exception is a bug.
- Fail fast at boundaries: validate arguments where data enters
  (`Objects.requireNonNull`, explicit checks with messages naming the
  offending value).
- Catch only what the code can handle; otherwise wrap and rethrow with
  the original as cause.

## Logging

- Use SLF4J (`LoggerFactory.getLogger(X.class)`); never
  `System.out.println` in committed code.
- Use parameterised messages (`log.info("user {} created", id)`), not
  string concatenation.

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```java
static final int MAX_ALTITUDE_FT = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- JUnit 5, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `rejectsExpiredToken()`, not `test2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

When this repo has no linter, the first task of a dev plan wires the
preset below into the repo's build tool and records the command as
`cmd.lint`. Format = spotless (google-java-format); lint = checkstyle
with the built-in Google ruleset.

Gradle (`build.gradle`):

```groovy
plugins {
    id "com.diffplug.spotless" version "7.0.2"
    id "checkstyle"
}

spotless {
    java { googleJavaFormat() }
}

checkstyle {
    toolVersion = "10.21.0"
    // uses config/checkstyle/checkstyle.xml; start from Google's
    // google_checks.xml shipped with checkstyle
}
```

Maven (`pom.xml`, inside `<build><plugins>`):

```xml
<plugin>
  <groupId>com.diffplug.spotless</groupId>
  <artifactId>spotless-maven-plugin</artifactId>
  <version>2.44.0</version>
  <configuration>
    <java><googleJavaFormat/></java>
  </configuration>
</plugin>
```

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.java]
indent_size = 4
```

Run:

```
./gradlew spotlessCheck checkstyleMain    # Gradle
mvn spotless:check                        # Maven
```

Record as `cmd.lint`: `./gradlew spotlessCheck checkstyleMain` (Gradle)
or `mvn spotless:check` (Maven).
````

- [ ] **Step 4: Create `src/center_kb/templates/init/conventions-go.md`**

Exact content:

````markdown
# Go coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/go.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Packages: short, all-lowercase, no underscores; the package name is
  part of the caller's vocabulary (`bytes.Buffer`, not
  `bytesutil.BytesBuffer`).
- Exported identifiers: `PascalCase`; unexported: `camelCase`.
- No `Get` prefix on getters (`user.Name()`, not `user.GetName()`).
- Interfaces with one method end in `-er` (`Reader`, `Resolver`).

## Module structure

- Organise packages by feature/domain; avoid catch-all `util` packages.
- Keep packages small and cohesive; a file past ~400 lines is a signal
  to split.
- Accept interfaces, return concrete types.

## Error handling

- Errors are values: return `error` as the last result, check it at
  every call site; never `_ =` an error away.
- Wrap with context: `fmt.Errorf("resolving ref: %w", err)`; match with
  `errors.Is` / `errors.As`, not string comparison.
- Fail fast at boundaries: validate input where data enters and return
  an error naming the offending value. `panic` only for programmer
  errors.

## Logging

- Use `log/slog` (structured); never `fmt.Println` for diagnostics in
  committed code.
- Log where the error is handled, with key-value context
  (`slog.Error("resolve failed", "ref", ref, "err", err)`).

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```go
const MaxAltitudeFt = 60000 // per ATM-STD §5.3 @ v2.1
```

## Testing

- Standard `testing` package; table-driven tests for behaviour families;
  AAA shape inside each case.
- Names describe the behaviour: `TestRejectsExpiredToken`, subtests via
  `t.Run("expired token", ...)`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

When this repo has no linter, the first task of a dev plan creates the
file below exactly as shown and records the command as `cmd.lint`.
gofmt runs as a golangci-lint linter, so one command covers both.

`.golangci.yml`:

```yaml
run:
  timeout: 5m
linters:
  enable:
    - govet
    - staticcheck
    - errcheck
    - gofmt
```

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.go]
indent_style = tab
```

Install and run:

```
go install github.com/golangci/golangci-lint/cmd/golangci-lint@latest
golangci-lint run
```

Record as `cmd.lint`: `golangci-lint run`
````

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_templates.py::test_conventions_java_and_go_templates_carry_the_full_skeleton -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/conventions-java.md src/center_kb/templates/init/conventions-go.md tests/test_templates.py
git commit -m "feat: java + go base conventions templates (D2 content)"
```

---

### Task 4: Base conventions templates — php + dotnet

**Files:**
- Create: `src/center_kb/templates/init/conventions-php.md`
- Create: `src/center_kb/templates/init/conventions-dotnet.md`
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: `CONVENTIONS_SECTION_HEADINGS` from `tests/test_templates.py` (Task 2).
- Produces: package resources `conventions-php.md`, `conventions-dotnet.md`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_conventions_php_and_dotnet_templates_carry_the_full_skeleton():
    for name, needles in (
        (
            "conventions-php.md",
            (".php-cs-fixer.dist.php", "@PSR12", "php-cs-fixer check"),
        ),
        (
            "conventions-dotnet.md",
            ("dotnet format --verify-no-changes", "dotnet_diagnostic", "EnforceCodeStyleInBuild"),
        ),
    ):
        text = _read_init_template(name)
        for heading in CONVENTIONS_SECTION_HEADINGS:
            assert heading in text, f"{name}: missing {heading!r}"
        for needle in needles:
            assert needle in text, f"{name}: missing {needle!r}"
        assert ".local.md" in text, name
        assert ".editorconfig" in text, name
        assert "per ATM-STD §5.3" in text, name
        assert "cmd.lint" in text, name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_templates.py::test_conventions_php_and_dotnet_templates_carry_the_full_skeleton -v`
Expected: FAIL — `FileNotFoundError` for `conventions-php.md`.

- [ ] **Step 3: Create `src/center_kb/templates/init/conventions-php.md`**

Exact content:

````markdown
# PHP coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/php.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Classes, interfaces, traits, enums: `PascalCase`; one per file, file
  named after it (PSR-4).
- Methods and properties: `camelCase`; booleans read as predicates
  (`isReady`, `hasPending`).
- Constants: `UPPER_SNAKE_CASE`.
- Namespaces mirror the directory layout (PSR-4 autoloading).

## Module structure

- Organise by feature/domain, not by technical layer alone.
- One class per file; keep classes focused — extract before ~400 lines.
- Depend on interfaces at boundaries; constructor injection over global
  state and static calls.

## Error handling

- Throw specific exception classes; never empty `catch` blocks — a
  swallowed exception is a bug.
- Fail fast at boundaries: validate input where data enters and throw
  with a message naming the offending value.
- Catch only what the code can handle; otherwise wrap and rethrow with
  `previous:` set to the original.

## Logging

- Use a PSR-3 logger; never `echo`/`var_dump`/`print_r` for diagnostics
  in committed code.
- Log where the error is handled, with context array
  (`$logger->error('resolve failed', ['ref' => $ref])`).

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```php
const MAX_ALTITUDE_FT = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- PHPUnit, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `testRejectsExpiredToken()`, not
  `testToken2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

When this repo has no linter, the first task of a dev plan creates the
file below exactly as shown and records the command as `cmd.lint`.

`.php-cs-fixer.dist.php`:

```php
<?php

$finder = PhpCsFixer\Finder::create()
    ->in(__DIR__)
    ->exclude('vendor');

return (new PhpCsFixer\Config())
    ->setRules([
        '@PSR12' => true,
    ])
    ->setFinder($finder);
```

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.php]
indent_size = 4
```

Install and run:

```
composer require --dev friendsofphp/php-cs-fixer
vendor/bin/php-cs-fixer check --diff
```

Record as `cmd.lint`: `vendor/bin/php-cs-fixer check --diff`
````

- [ ] **Step 4: Create `src/center_kb/templates/init/conventions-dotnet.md`**

Exact content:

````markdown
# C# / .NET coding conventions

Base file — owned by the center-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/dotnet.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Naming

- Namespaces, classes, records, structs, enums, methods, properties:
  `PascalCase`; interfaces prefixed `I` (`IResolver`).
- Locals and parameters: `camelCase`; private fields `_camelCase`.
- Constants: `PascalCase` (`MaxAltitudeFt`).
- Async methods end in `Async`.

## Module structure

- Organise by feature/domain, not by technical layer alone.
- One top-level type per file, file named after it; extract before a
  class grows past ~400 lines.
- Depend on interfaces at boundaries; use the built-in DI container,
  no service-locator calls in business logic.

## Error handling

- Throw specific exception types; never `catch (Exception) {}` — a
  swallowed exception is a bug.
- Fail fast at boundaries: validate arguments where data enters
  (`ArgumentNullException.ThrowIfNull`, explicit checks naming the
  offending value).
- Catch only what the code can handle; otherwise wrap and rethrow with
  the original as `InnerException`.

## Logging

- Use `Microsoft.Extensions.Logging` (`ILogger<T>`); never
  `Console.WriteLine` for diagnostics in committed code.
- Use structured message templates
  (`_logger.LogError("resolve failed for {Ref}", reference)`), not
  string interpolation.

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```csharp
const int MaxAltitudeFt = 60_000; // per ATM-STD §5.3 @ v2.1
```

## Testing

- xUnit, AAA shape (Arrange–Act–Assert), one behaviour per test.
- Names describe the behaviour: `RejectsExpiredToken()`, not `Test2()`.
- Every bug fix lands together with the test that would have caught it.
- Never edit a test to make it pass — diagnose the cause.

## Linting (preset)

When this repo has no linter, the first task of a dev plan creates the
`.editorconfig` below (format AND analyzer severities live there),
enables analyzers in the project file, and records the command as
`cmd.lint`.

`.editorconfig`:

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true
indent_style = space

[*.cs]
indent_size = 4
dotnet_analyzer_diagnostic.category-Style.severity = warning
dotnet_diagnostic.IDE0005.severity = warning
```

Project file (inside `<PropertyGroup>`):

```xml
<EnableNETAnalyzers>true</EnableNETAnalyzers>
<EnforceCodeStyleInBuild>true</EnforceCodeStyleInBuild>
```

Run:

```
dotnet format --verify-no-changes
```

Record as `cmd.lint`: `dotnet format --verify-no-changes`
````

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_templates.py::test_conventions_php_and_dotnet_templates_carry_the_full_skeleton -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/conventions-php.md src/center_kb/templates/init/conventions-dotnet.md tests/test_templates.py
git commit -m "feat: php + dotnet base conventions templates (D2 content)"
```

---

### Task 5: Local stub + pointer templates

**Files:**
- Create: `src/center_kb/templates/init/conventions-local-stub.md`
- Create: `src/center_kb/templates/init/conventions-pointer.mdc`
- Create: `src/center_kb/templates/init/conventions-pointer.instructions.md`
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: the three package resources above. The two pointer templates contain the literal placeholders `{lang}` and `{globs}` — Task 6's `_render_pointer` substitutes them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_conventions_local_stub_and_pointer_templates():
    stub = _read_init_template("conventions-local-stub.md")
    assert "never rewrites it" in stub
    assert "OVERRIDE" in stub

    mdc = _read_init_template("conventions-pointer.mdc")
    assert "globs: {globs}" in mdc
    assert "alwaysApply: false" in mdc

    instr = _read_init_template("conventions-pointer.instructions.md")
    assert 'applyTo: "{globs}"' in instr

    for text in (mdc, instr):
        assert "docs/conventions/{lang}.md" in text
        assert "docs/conventions/{lang}.local.md" in text
        # raw-text needle kept to one source line — the phrase wraps
        assert "wins locally" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_templates.py::test_conventions_local_stub_and_pointer_templates -v`
Expected: FAIL — `FileNotFoundError` for `conventions-local-stub.md`.

- [ ] **Step 3: Create the three templates**

`src/center_kb/templates/init/conventions-local-stub.md` — exact content:

```markdown
# Local conventions overrides

This file belongs to this repository: `kb init` never rewrites it.

Rules recorded here OVERRIDE the base conventions file
(`docs/conventions/<lang>.md`) where the two conflict. Record local
deviations from the base conventions here — one bullet per rule, with a
short reason.
```

`src/center_kb/templates/init/conventions-pointer.mdc` — exact content:

```markdown
---
description: Coding conventions for {lang} files
globs: {globs}
alwaysApply: false
---

Before writing or reviewing {lang} code, read `docs/conventions/{lang}.md`.
If `docs/conventions/{lang}.local.md` exists it overrides the base file.
Where either conflicts with the repo's existing dominant style, the repo
wins locally — record the conflict as a finding in the PR.
```

`src/center_kb/templates/init/conventions-pointer.instructions.md` — exact content:

```markdown
---
applyTo: "{globs}"
---

Before writing or reviewing {lang} code, read `docs/conventions/{lang}.md`.
If `docs/conventions/{lang}.local.md` exists it overrides the base file.
Where either conflicts with the repo's existing dominant style, the repo
wins locally — record the conflict as a finding in the PR.
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_templates.py::test_conventions_local_stub_and_pointer_templates -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/templates/init/conventions-local-stub.md src/center_kb/templates/init/conventions-pointer.mdc src/center_kb/templates/init/conventions-pointer.instructions.md tests/test_templates.py
git commit -m "feat: conventions local stub + pointer templates (D2/D3 content)"
```

---

### Task 6: Scaffold step — `scaffold_conventions`

**Files:**
- Modify: `src/center_kb/conventions.py` (append)
- Test: `tests/test_conventions.py` (append)

**Interfaces:**
- Consumes: `detect_langs` (Task 1); template resources `conventions-<lang>.md` (Tasks 2–4), `conventions-local-stub.md`, `conventions-pointer.mdc`, `conventions-pointer.instructions.md` (Task 5); `center_kb.initcmd.InitReport` (existing: dataclass with `created: list[str]`, `updated: list[str]`, `skipped: list[str]`, `notes: list[str]`).
- Produces (Task 8 relies on these exact names):
  - `LANG_GLOBS: dict[str, str]`
  - `scaffold_conventions(target: Path, report: InitReport) -> list[str]` — returns the detected language ids (empty list ⇒ nothing scaffolded, note appended).

- [ ] **Step 1: Write the failing tests**

Change the import line at the TOP of `tests/test_conventions.py` (mid-file imports trip ruff E402) from `from center_kb.conventions import detect_langs` to:

```python
from center_kb.conventions import LANG_GLOBS, detect_langs, scaffold_conventions
from center_kb.initcmd import InitReport
```

Then append to the end of the file:

```python
def _scaffold(tmp_path: Path) -> InitReport:
    report = InitReport()
    scaffold_conventions(tmp_path, report)
    return report


def test_scaffold_creates_base_local_and_pointers_for_detected_lang(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    report = _scaffold(tmp_path)
    base = tmp_path / "docs" / "conventions" / "python.md"
    local = tmp_path / "docs" / "conventions" / "python.local.md"
    mdc = tmp_path / ".cursor" / "rules" / "coding-python.mdc"
    instr = tmp_path / ".github" / "instructions" / "coding-python.instructions.md"
    for f in (base, local, mdc, instr):
        assert f.is_file(), f
    assert "# Python coding conventions" in base.read_text(encoding="utf-8")
    assert "OVERRIDE" in local.read_text(encoding="utf-8")
    mdc_text = mdc.read_text(encoding="utf-8")
    assert "globs: **/*.py" in mdc_text            # {globs} substituted
    assert "docs/conventions/python.md" in mdc_text  # {lang} substituted
    assert "{lang}" not in mdc_text and "{globs}" not in mdc_text
    instr_text = instr.read_text(encoding="utf-8")
    assert 'applyTo: "**/*.py"' in instr_text
    assert "{lang}" not in instr_text and "{globs}" not in instr_text
    assert "docs/conventions/python.md" in report.created
    assert "docs/conventions/python.local.md" in report.created
    assert ".cursor/rules/coding-python.mdc" in report.created
    assert ".github/instructions/coding-python.instructions.md" in report.created
    # only the detected language
    assert not (tmp_path / "docs" / "conventions" / "ts.md").exists()


def test_scaffold_returns_detected_langs_and_covers_multi_lang(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    _touch(tmp_path, "web/package.json")
    report = InitReport()
    assert scaffold_conventions(tmp_path, report) == ["python", "ts"]
    assert (tmp_path / "docs" / "conventions" / "ts.md").is_file()
    assert (tmp_path / ".cursor" / "rules" / "coding-ts.mdc").is_file()


def test_scaffold_refreshes_stale_base_but_never_touches_local(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    _scaffold(tmp_path)
    base = tmp_path / "docs" / "conventions" / "python.md"
    local = tmp_path / "docs" / "conventions" / "python.local.md"
    base.write_text("stale\n", encoding="utf-8")
    local.write_text("my overrides\n", encoding="utf-8")
    report = _scaffold(tmp_path)
    assert "stale" not in base.read_text(encoding="utf-8")
    assert local.read_text(encoding="utf-8") == "my overrides\n"
    assert "docs/conventions/python.md" in report.updated
    assert "docs/conventions/python.local.md" in report.skipped


def test_scaffold_is_idempotent_when_current(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    _scaffold(tmp_path)
    report = _scaffold(tmp_path)
    assert report.created == []
    assert report.updated == []
    assert report.skipped == ["docs/conventions/python.local.md"]


def test_scaffold_without_manifests_notes_and_writes_nothing(tmp_path: Path):
    report = InitReport()
    assert scaffold_conventions(tmp_path, report) == []
    assert not (tmp_path / "docs" / "conventions").exists()
    assert any("no language manifests detected" in n for n in report.notes)


def test_lang_globs_covers_every_manifest_lang():
    from center_kb.conventions import LANG_MANIFESTS

    assert sorted(LANG_GLOBS) == sorted(lang for lang, _ in LANG_MANIFESTS)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_conventions.py -v`
Expected: the new tests FAIL with `ImportError: cannot import name 'LANG_GLOBS'`; Task 1's tests still PASS.

- [ ] **Step 3: Write the implementation**

Append to `src/center_kb/conventions.py` (and add the imports shown to the top of the file — `TYPE_CHECKING` avoids a runtime import cycle, because `initcmd` will import this module in Task 8):

```python
# add to the top of the file, below `from pathlib import Path`:
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # runtime import would be circular: initcmd imports us
    from center_kb.initcmd import InitReport
```

```python
# file-extension globs per language id, used in the pointer wrappers'
# frontmatter (`globs:` for Cursor, `applyTo:` for Copilot).
LANG_GLOBS: dict[str, str] = {
    "dotnet": "**/*.cs",
    "go": "**/*.go",
    "java": "**/*.java",
    "php": "**/*.php",
    "python": "**/*.py",
    "ts": "**/*.ts,**/*.tsx,**/*.js,**/*.jsx",
}


def _template_text(name: str) -> str:
    return (
        resources.files("center_kb")
        .joinpath(f"templates/init/{name}")
        .read_text(encoding="utf-8")
    )


def _write(dest: Path, text: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8", newline="\n")


def _render_pointer(text: str, lang: str) -> str:
    # plain substring replace, same rationale as initcmd._render: template
    # text may legitimately contain other `{`/`}` characters.
    return text.replace("{lang}", lang).replace("{globs}", LANG_GLOBS[lang])


def _sync(target: Path, rel: str, text: str, report: InitReport) -> None:
    """Create-or-refresh with the same semantics as init_repo's main loop."""
    dest = target / rel
    if dest.exists():
        if dest.read_text(encoding="utf-8") == text:
            return
        dest.write_text(text, encoding="utf-8", newline="\n")
        report.updated.append(rel)
        return
    _write(dest, text)
    report.created.append(rel)


def scaffold_conventions(target: Path, report: InitReport) -> list[str]:
    """Scaffold conventions files for every detected language.

    Base + pointer files are package-owned (create-or-refresh); the
    `.local.md` stub is user data — created once, then never compared,
    never rewritten, not even with ``--force`` (its path is dynamic, so it
    cannot sit in PROTECTED_FILES; this function enforces the skip
    itself). Returns the detected language ids.
    """
    langs = detect_langs(target)
    if not langs:
        report.notes.append(
            "no language manifests detected — conventions skipped; "
            "re-run kb init after adding code"
        )
        return []
    stub = _template_text("conventions-local-stub.md")
    mdc = _template_text("conventions-pointer.mdc")
    instr = _template_text("conventions-pointer.instructions.md")
    for lang in langs:
        _sync(
            target,
            f"docs/conventions/{lang}.md",
            _template_text(f"conventions-{lang}.md"),
            report,
        )
        local_rel = f"docs/conventions/{lang}.local.md"
        local = target / "docs" / "conventions" / f"{lang}.local.md"
        if local.exists():
            report.skipped.append(local_rel)
        else:
            _write(local, stub)
            report.created.append(local_rel)
        _sync(
            target,
            f".cursor/rules/coding-{lang}.mdc",
            _render_pointer(mdc, lang),
            report,
        )
        _sync(
            target,
            f".github/instructions/coding-{lang}.instructions.md",
            _render_pointer(instr, lang),
            report,
        )
    return langs
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_conventions.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/center_kb/conventions.py tests/test_conventions.py
git add src/center_kb/conventions.py tests/test_conventions.py
git commit -m "feat: conventions scaffold step — base refresh, local never-touch, pointer render (D2/D3 engine)"
```

---

### Task 7: `ensure_claude_block`

**Files:**
- Modify: `src/center_kb/conventions.py` (append)
- Test: `tests/test_conventions.py` (append)

**Interfaces:**
- Consumes: `_write` helper and `InitReport` typing from Task 6.
- Produces (Task 8 relies on these exact names):
  - `CLAUDE_MARKER: str` — `"<!-- kb:conventions -->"`
  - `ensure_claude_block(target: Path, report: InitReport) -> None`

- [ ] **Step 1: Write the failing tests**

Change the conventions import line at the TOP of `tests/test_conventions.py` (mid-file imports trip ruff E402) to:

```python
from center_kb.conventions import (
    CLAUDE_MARKER,
    LANG_GLOBS,
    detect_langs,
    ensure_claude_block,
    scaffold_conventions,
)
```

Then append to the end of the file:

```python
def test_claude_block_created_when_file_missing(tmp_path: Path):
    report = InitReport()
    ensure_claude_block(tmp_path, report)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith(CLAUDE_MARKER)
    assert "docs/conventions/<lang>.md" in text
    assert "docs/conventions/<lang>.local.md" in text
    # raw-text needle kept to one source line — the phrase wraps
    assert "repo wins locally" in text
    assert "CLAUDE.md" in report.created


def test_claude_block_appended_preserving_user_bytes(tmp_path: Path):
    user = "# My project notes\n\nno trailing newline here"
    (tmp_path / "CLAUDE.md").write_text(user, encoding="utf-8")
    report = InitReport()
    ensure_claude_block(tmp_path, report)
    text = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert text.startswith(user)          # user content byte-preserved as prefix
    assert CLAUDE_MARKER in text
    assert "CLAUDE.md (conventions block appended)" in report.updated


def test_claude_block_untouched_when_marker_present(tmp_path: Path):
    report = InitReport()
    ensure_claude_block(tmp_path, report)
    first = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    report2 = InitReport()
    ensure_claude_block(tmp_path, report2)
    assert (tmp_path / "CLAUDE.md").read_text(encoding="utf-8") == first
    assert report2.created == [] and report2.updated == []
    assert first.count(CLAUDE_MARKER) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_conventions.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'CLAUDE_MARKER'`.

- [ ] **Step 3: Write the implementation**

Append to `src/center_kb/conventions.py`:

```python
CLAUDE_MARKER = "<!-- kb:conventions -->"

# Generic on purpose: it points at docs/conventions/ as a directory
# convention rather than naming languages, so detecting a new language
# later never requires editing an already-appended block.
_CLAUDE_BLOCK = (
    f"{CLAUDE_MARKER}\n"
    "**Coding conventions.**\n"
    "For each language you touch, read `docs/conventions/<lang>.md`; if\n"
    "`docs/conventions/<lang>.local.md` exists it overrides the base file.\n"
    "Where either conflicts with the repo's existing dominant style, the\n"
    "repo wins locally — record the conflict as a finding in the PR.\n"
)


def ensure_claude_block(target: Path, report: InitReport) -> None:
    """Append-only marker block, modelled on initcmd._record_kind.

    Missing file → create with the block; present without the marker →
    append, preserving existing bytes; marker present → do nothing. User
    content is never rewritten.
    """
    dest = target / "CLAUDE.md"
    if not dest.exists():
        _write(dest, _CLAUDE_BLOCK)
        report.created.append("CLAUDE.md")
        return
    text = dest.read_text(encoding="utf-8")
    if CLAUDE_MARKER in text:
        return
    if text and not text.endswith("\n"):
        text += "\n"
    dest.write_text(
        text + "\n" + _CLAUDE_BLOCK, encoding="utf-8", newline="\n"
    )
    report.updated.append("CLAUDE.md (conventions block appended)")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_conventions.py -v`
Expected: PASS (all).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/center_kb/conventions.py tests/test_conventions.py
git add src/center_kb/conventions.py tests/test_conventions.py
git commit -m "feat: CLAUDE.md append-only conventions marker block (D2 engine)"
```

---

### Task 8: Wire the post-step into `init_repo` (kind dev only)

**Files:**
- Modify: `src/center_kb/initcmd.py` (import + 4 lines in `init_repo`)
- Test: `tests/test_init.py` (append)

**Interfaces:**
- Consumes: `scaffold_conventions(target, report) -> list[str]` and `ensure_claude_block(target, report)` from `center_kb.conventions` (Tasks 6–7); `KIND_DEV`, `InitReport`, `init_repo`, `expected_files` (existing in `initcmd.py`).
- Produces: `kb init --kind dev` scaffolds conventions as a post-step. No signature changes anywhere.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_init.py`:

```python
# --- Batch 5 (D conventions pack): dev-kind post-step -----------------------


def test_init_dev_scaffolds_conventions_for_detected_language(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    report = init_repo(tmp_path, "dev")
    assert (tmp_path / "docs" / "conventions" / "python.md").is_file()
    assert (tmp_path / "docs" / "conventions" / "python.local.md").is_file()
    assert (tmp_path / ".cursor" / "rules" / "coding-python.mdc").is_file()
    assert (
        tmp_path / ".github" / "instructions" / "coding-python.instructions.md"
    ).is_file()
    claude = (tmp_path / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude.startswith("<!-- kb:conventions -->")
    assert "docs/conventions/python.md" in report.created
    assert "CLAUDE.md" in report.created
    # only the detected language
    assert not (tmp_path / "docs" / "conventions" / "ts.md").exists()


def test_init_dev_reinit_preserves_local_conventions_and_user_claude_md(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    init_repo(tmp_path, "dev")
    local = tmp_path / "docs" / "conventions" / "python.local.md"
    local.write_text("my overrides\n", encoding="utf-8")
    claude = tmp_path / "CLAUDE.md"
    user_text = "# My notes\n" + claude.read_text(encoding="utf-8")
    claude.write_text(user_text, encoding="utf-8")
    base = tmp_path / "docs" / "conventions" / "python.md"
    base.write_text("stale\n", encoding="utf-8")
    # --force must refresh the base but STILL not touch local or CLAUDE.md
    report = init_repo(tmp_path, "dev", force=True)
    assert local.read_text(encoding="utf-8") == "my overrides\n"
    assert claude.read_text(encoding="utf-8") == user_text  # marker present
    assert "stale" not in base.read_text(encoding="utf-8")
    assert "docs/conventions/python.local.md" in report.skipped


def test_init_dev_without_manifests_notes_and_skips_conventions(tmp_path: Path):
    report = init_repo(tmp_path, "dev")
    assert not (tmp_path / "docs" / "conventions").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert any("no language manifests detected" in n for n in report.notes)


def test_expected_files_unchanged_by_conventions_pack():
    # conventions are a post-step, never template-map rows (spec: Scope/Out)
    for kind in ("hub", "child", "ba", "dev"):
        assert not any("conventions" in rel for rel in expected_files(kind))
        assert "CLAUDE.md" not in expected_files(kind)


def test_init_non_dev_kinds_gain_no_conventions(tmp_path: Path):
    for kind in ("hub", "child", "ba"):
        repo = tmp_path / kind
        repo.mkdir()
        (repo / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        init_repo(repo, kind)
        assert not (repo / "docs" / "conventions").exists(), kind
        assert not (repo / "CLAUDE.md").exists(), kind
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_init.py -k conventions -v`
Expected: the first three FAIL (no conventions files scaffolded); the `expected_files` and non-dev tests may already PASS — that is fine, they are trip-wires.

- [ ] **Step 3: Wire the post-step**

In `src/center_kb/initcmd.py`, add the import near the top (after the existing imports; safe because `conventions.py` imports `initcmd` only under `TYPE_CHECKING`):

```python
from center_kb import conventions
```

In `init_repo()`, insert after the `_record_kind` block and before the `if assets is not None:` block:

```python
    if kind == KIND_DEV:
        langs = conventions.scaffold_conventions(target, report)
        if langs:
            conventions.ensure_claude_block(target, report)
```

- [ ] **Step 4: Run the new tests, then the whole init + templates suites**

Run: `uv run pytest tests/test_init.py -k conventions -v`
Expected: PASS (all five).

Run: `uv run pytest tests/test_init.py tests/test_templates.py tests/test_conventions.py`
Expected: PASS. If any pre-existing dev-kind test fails on the new report rows or the new note (e.g. an exact `report.notes == []` or exact-output assertion), update that assertion **deliberately** and say why in the commit body — that is the D5 trip-wire discipline, mirroring how `tests/test_init.py` pins were bumped in earlier batches. Do not weaken the new behaviour to avoid the bump.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check src/center_kb/initcmd.py tests/test_init.py
git add src/center_kb/initcmd.py tests/test_init.py
git commit -m "feat: kb init (kind dev) runs the conventions post-step (D2 engine wiring)"
```

---

### Task 9: D1 — dev-plan: no linter → first task sets one up

**Files:**
- Modify: `src/center_kb/templates/init/claude-skill-dev-plan.md`
- Modify: `src/center_kb/templates/init/copilot-dev-plan.prompt.md`
- Modify: `src/center_kb/templates/init/cursor-dev-plan.md`
- Modify: `src/center_kb/templates/init/claude-command-dev-plan.md`
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: `_dev_wrapper_names`, `_dev_wrapper_text`, `_dev_wrapper_body` helpers (existing in `tests/test_templates.py`).
- Produces: all four dev-plan wrappers carry the no-linter rule. The pinned needle `` `kb code-ingest` not yet run `` must survive (it is asserted by the existing `test_dev_plan_and_dev_implement_ticket_caveat_the_code_document_by_repo_state`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
# --- Batch 5 (D conventions pack): skill-text round -------------------------


def test_dev_plan_first_task_sets_up_the_linter_when_the_repo_has_none():
    # D1: the existing bullet only handles "no -code document" by asking for
    # commands; a repo with NO linter at all had nothing to record and no
    # guidance. The preset lives in the Linting section of the scaffolded
    # conventions base file.
    for name in _dev_wrapper_names("dev-plan"):
        text = _dev_wrapper_text(name)
        assert "no linter at all" in text, name
        assert "docs/conventions/<lang>.md" in text, name
        assert "*Linting* section" in text, name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_templates.py::test_dev_plan_first_task_sets_up_the_linter_when_the_repo_has_none -v`
Expected: FAIL on `claude-skill-dev-plan.md` (first wrapper checked).

- [ ] **Step 3: Edit the three body-identical wrappers**

The skill/copilot/cursor wrappers carry the bullet byte-identically. Apply this exact replacement to **each** of `claude-skill-dev-plan.md`, `copilot-dev-plan.prompt.md`, `cursor-dev-plan.md`:

Old:

```markdown
- **No `-code` document yet** — when `-code §cmd.*` has not been generated
  in this repo (`kb code-ingest` not yet run), ask the Dev once for the
  build/test/lint commands and record them at the top of the plan file, so
  this closing task, `dev-execute`, and `dev-handover` all have something
  to run.
```

New:

```markdown
- **No `-code` document yet** — when `-code §cmd.*` has not been generated
  in this repo (`kb code-ingest` not yet run), ask the Dev once for the
  build/test/lint commands and record them at the top of the plan file, so
  this closing task, `dev-execute`, and `dev-handover` all have something
  to run.
- **No linter in the repo** — when there is no linter at all to record as
  `cmd.lint`, make the plan's first task setting one up from the
  *Linting* section of `docs/conventions/<lang>.md` (plus
  `docs/conventions/<lang>.local.md` overrides), and record the command
  it establishes as `cmd.lint`.
```

- [ ] **Step 4: Edit the claude-command wrapper**

`claude-command-dev-plan.md` compresses the steps into one paragraph. Apply this exact replacement:

Old:

```markdown
asks the Dev once for the build/test/lint commands and records them at
the top of the plan file so this closing task, `dev-execute`, and
`dev-handover` all have something to run. Ends at **GATE 2**: the
```

New:

```markdown
asks the Dev once for the build/test/lint commands and records them at
the top of the plan file so this closing task, `dev-execute`, and
`dev-handover` all have something to run; and when the repo has no
linter at all to record as `cmd.lint`, the plan's first task sets one
up from the *Linting* section of `docs/conventions/<lang>.md` (plus
`docs/conventions/<lang>.local.md` overrides) and records the command
it establishes as `cmd.lint`. Ends at **GATE 2**: the
```

- [ ] **Step 5: Run the test and the full templates suite**

Run: `uv run pytest tests/test_templates.py -v`
Expected: PASS — including `test_dev_wrappers_carry_byte_identical_shared_blocks` (the edit is outside the SHARED-* regions) and `test_dev_plan_and_dev_implement_ticket_caveat_the_code_document_by_repo_state` (the needle survived).

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/claude-skill-dev-plan.md src/center_kb/templates/init/copilot-dev-plan.prompt.md src/center_kb/templates/init/cursor-dev-plan.md src/center_kb/templates/init/claude-command-dev-plan.md tests/test_templates.py
git commit -m "feat: dev-plan makes linter setup the first task when the repo has none (D1)"
```

---

### Task 10: D4 — dev-execute checkpoint points at the conventions files

**Files:**
- Modify: `src/center_kb/templates/init/claude-skill-dev-execute.md`
- Modify: `src/center_kb/templates/init/copilot-dev-execute.prompt.md`
- Modify: `src/center_kb/templates/init/cursor-dev-execute.md`
- Modify: `src/center_kb/templates/init/claude-command-dev-execute.md`
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: `_dev_wrapper_names`, `_dev_wrapper_text`, `_dev_wrapper_body` helpers (existing in `tests/test_templates.py`).
- Produces: all four dev-execute wrappers replace "the repo's existing conventions" with the explicit base + local pointer and the repo-wins-locally conflict rule.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_dev_execute_review_checkpoint_points_at_the_conventions_files():
    # D4: "the repo's existing conventions" was unactionable — the checkpoint
    # now names the scaffolded files, the local-wins order, and the
    # conflict-becomes-a-finding rule.
    for name in _dev_wrapper_names("dev-execute"):
        text = _dev_wrapper_text(name)
        assert "docs/conventions/<lang>.md" in text, name
        assert "docs/conventions/<lang>.local.md" in text, name
        assert "the repo wins locally" in text, name
        assert "the repo's existing conventions" not in _dev_wrapper_body(name), name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_templates.py::test_dev_execute_review_checkpoint_points_at_the_conventions_files -v`
Expected: FAIL on `claude-skill-dev-execute.md`.

- [ ] **Step 3: Edit the three body-identical wrappers**

Apply this exact replacement to **each** of `claude-skill-dev-execute.md`, `copilot-dev-execute.prompt.md`, `cursor-dev-execute.md`:

Old:

```markdown
  3. **review checkpoint** — pass/fail, not a score: does the test
     actually exercise that AC; is every standard-derived value
     verbatim with a citation comment; does the change follow the
     repo's existing conventions; did anything else break.
```

New:

```markdown
  3. **review checkpoint** — pass/fail, not a score: does the test
     actually exercise that AC; is every standard-derived value
     verbatim with a citation comment; does the change follow
     `docs/conventions/<lang>.md` plus `docs/conventions/<lang>.local.md`
     overrides (local wins; where either conflicts with the repo's
     existing dominant style, the repo wins locally — record the
     conflict as a finding for the PR body); did anything else break.
```

- [ ] **Step 4: Edit the claude-command wrapper**

Apply this exact replacement to `claude-command-dev-execute.md`:

Old:

```markdown
AC, every standard-derived value is verbatim with a citation comment,
the change follows the repo's existing conventions, and nothing else
broke; then **verify** by running `cmd.test` and `cmd.lint` (the
```

New:

```markdown
AC, every standard-derived value is verbatim with a citation comment,
the change follows `docs/conventions/<lang>.md` plus
`docs/conventions/<lang>.local.md` overrides (local wins; where either
conflicts with the repo's existing dominant style, the repo wins
locally — the conflict is recorded as a finding for the PR body), and
nothing else broke; then **verify** by running `cmd.test` and `cmd.lint` (the
```

- [ ] **Step 5: Run the test and the full templates suite**

Run: `uv run pytest tests/test_templates.py -v`
Expected: PASS — including the SHARED-* byte-identity test (the edit is outside those regions) and `test_every_dev_workflow_wrapper_ends_on_the_next_step_block`.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init/claude-skill-dev-execute.md src/center_kb/templates/init/copilot-dev-execute.prompt.md src/center_kb/templates/init/cursor-dev-execute.md src/center_kb/templates/init/claude-command-dev-execute.md tests/test_templates.py
git commit -m "feat: dev-execute checkpoint points at the conventions files, repo wins locally (D4)"
```

---

### Task 11: Closing — cross-cutting verification

**Files:**
- Modify: none (verification only; `docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md` may be ticked in a follow-up docs commit after merge, not in this task).

**Interfaces:**
- Consumes: everything above.
- Produces: a green branch ready for `dev-handover`-style review.

- [ ] **Step 1: Run the full suite**

Run: `uv run pytest`
Expected: PASS (baseline before this batch was 1828 passed, 5 skipped; this batch adds ~30 tests). Any failure is investigated and fixed at its cause — never by weakening a test.

- [ ] **Step 2: Lint the whole tree**

Run: `uv run ruff check .`
Expected: clean.

- [ ] **Step 3: Verify the golden gate**

Run: `git diff main...HEAD -- tests-gate/golden src/center_kb/mcp.py`
Expected: empty output — the MCP surface and golden files are untouched (Global Constraints).

- [ ] **Step 4: Show the outputs**

Paste the pytest tail (counts line), the ruff output, and the empty golden diff into the task report — never claim done without showing the verification output.
