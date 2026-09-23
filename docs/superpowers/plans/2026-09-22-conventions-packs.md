# Conventions packs — a five-file pack per language, on the ECC rules shape

Branch: `feat/ticket-size-gates` (HEAD `d4c1606`) — this work is **appended**
to that branch and to PR #65. No new branch, no version bump.

Repo: strata-kb, Python 3.11+, tests via `uv run pytest`.

---

## 1. What ships

`kb init --kind dev` today writes, per detected-or-forced language:

```
docs/conventions/<lang>.md                     # base, package-owned
docs/conventions/<lang>.local.md               # create-once, never refreshed
.cursor/rules/coding-<lang>.mdc                # pointer
.github/instructions/coding-<lang>.instructions.md  # pointer
CLAUDE.md                                      # append-only marker block
```

After this change it also writes a **conventions pack**:

```
docs/conventions/
├── common/                      # written once per dev repo
│   ├── coding-style.md
│   ├── patterns.md
│   ├── security.md
│   ├── testing.md
│   └── hooks.md
├── <lang>/                      # written per scaffolded language
│   ├── coding-style.md          # "> This file extends [common/coding-style.md](../common/coding-style.md) with <Language>-specific content."
│   ├── patterns.md
│   ├── security.md
│   ├── testing.md
│   └── hooks.md
├── <lang>.md                    # RESHAPED: entry file / index
└── <lang>.local.md              # unchanged
```

`docs/conventions/<lang>.md` becomes the **entry file**: title, ownership
paragraph, a `## Conventions pack` table linking the ten pack files, and the
two sections that stay put — `## Citation comments` and
`## Linting (preset)`. Its `## Naming`, `## Module structure`,
`## Error handling` and `## Logging` sections move into
`<lang>/coding-style.md`; its `## Testing` section moves into
`<lang>/testing.md`.

`## Linting (preset)` must stay in the entry file: the dev-plan wrappers
point at "the *Linting* section of `docs/conventions/<lang>.md`" by name
and `tests/test_templates.py` pins that phrase
(`test_dev_plan_refuses_a_draft_design_and_writes_the_cmd_headers`,
line 1975).

New package templates, flat names in `src/strata_kb/templates/init/`:

- `conventions-common-<part>.md` — 5 files
- `conventions-<lang>-<part>.md` — 10 languages × 5 parts = 50 files

where `<part> ∈ {coding-style, patterns, security, testing, hooks}` and
`<lang> ∈ conventions.LANG_IDS = (dotnet, go, java, php, python, ts, rust,
swift, dart, e2e-playwright)`.

`pyproject.toml` needs no change: `only-include = ["src"]` already ships
everything under `src/strata_kb/templates/init/`.

---

## 2. Global constraints — binding on every task

### 2.1 Process

- **No version bump.** `pyproject.toml` stays at `1.1.0`.
- **CHANGELOG**: exactly one bullet, appended at the end of the existing
  `## Unreleased` list, in T12 only. No new heading.
- **No new dependency.** No `pyproject.toml` edit at all.
- **`src/strata_kb/mdutils.py` is frozen.** Do not open it.
- **Templates are English.** The Vietnamese guide (`docs/src/guide-dev.vi.md`)
  is not touched by this plan (see §9, resolved ambiguity A3).
- **Green gate after every task**, before the commit:
  ```
  uv run pytest tests/test_conventions.py tests/test_init.py tests/test_templates.py -q
  ```
  Expected: `447 passed` for T1's pre-check, then the count rises as tests are
  added. Every task must end on `N passed` with **zero** failures and zero
  errors. Skips are expected in T1–T11 (the lenient pack tests) and must be
  **zero** after T12.
- **Full suite before the last commit** (T12 only):
  ```
  uv run pytest -q
  ```
- **GitNexus** (per `CLAUDE.md`): run `impact` on `scaffold_conventions`,
  `ensure_claude_block` and `init_repo` **before** editing
  `src/strata_kb/conventions.py` (T1 and T12 only — T2–T11 touch no Python).
  Run `detect_changes()` before each commit. If the `gitnexus` MCP server is
  down, write one line in the commit body —
  `GitNexus MCP unavailable; impact/detect_changes skipped.` — and continue.
- **Commit trailer** on every commit in this plan (the repo's own convention,
  see `git log`):
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01NtdRAkmyTshnfR99NbY5Li
  ```
- **T2–T11 must not edit any file under `tests/`.** They are template-only
  tasks and may be run in parallel worktrees.

### 2.2 Content source

The pack text is derived from the local rules tree at `~/.claude/rules/ecc/`:

| Our `<lang>` | Source directory |
|---|---|
| `python` | `~/.claude/rules/ecc/python/` |
| `ts` | `~/.claude/rules/ecc/typescript/` |
| `go` | `~/.claude/rules/ecc/golang/` |
| `java` | `~/.claude/rules/ecc/java/` |
| `dotnet` | `~/.claude/rules/ecc/csharp/` |
| `php` | `~/.claude/rules/ecc/php/` |
| `rust` | `~/.claude/rules/ecc/rust/` |
| `swift` | `~/.claude/rules/ecc/swift/` |
| `dart` | `~/.claude/rules/ecc/dart/` |
| `e2e-playwright` | no source directory — see T11 |
| `common/` | `~/.claude/rules/ecc/common/` — only `coding-style.md`, `patterns.md`, `security.md`, `testing.md`, `hooks.md`. `agents.md`, `code-review.md`, `development-workflow.md`, `git-workflow.md`, `performance.md` are **not** used. |

The source is a starting point, not a thing to copy. Every derived file is
**ours**: no trace of where it came from survives. The substitution table
below is exhaustive for these sources — it was built by grepping them:

```
grep -rn -i "ecc\|everything-claude\|~/\.claude\|See skill\|skill:\|agent" \
  ~/.claude/rules/ecc/{common,typescript,python,golang,java,csharp,php,rust,swift,dart,web}
```

### 2.3 Substitution table (14 rules — apply all of them, every file)

| # | Find | Replace with |
|---|---|---|
| **S1** | The YAML frontmatter at the top of a per-language source (`---` … `---`, plus the blank line after it) | delete |
| **S2** | The source's own `> This file extends …` line, wherever it sits | delete; our own extends line is written as **line 1** instead (see §2.4) |
| **S3** | A trailing `## Reference` or `## References` section (heading through end of file) | delete the whole section |
| **S4** | A `## Agent Support` section (`common/testing.md`, `typescript/testing.md`, `typescript/security.md`) | delete the whole section |
| **S5** | `~/.claude/settings.json` (9 `hooks.md` sources) | `` `.claude/settings.json` (this repo's, committed) `` |
| **S6** | `` Configure `allowedTools` in `~/.claude.json` instead `` (`common/hooks.md`) | `` Configure `permissions.allow` in this repo's `.claude/settings.json` instead `` |
| **S7** | Any other `~/.claude/…` path | delete the bullet or sentence that contains it |
| **S8** | `` Use **tdd-guide** agent `` (`common/testing.md:22`) | `Re-read the task block in the plan: the failing test must exercise the AC it names, nothing wider` |
| **S9** | `` Use **security-reviewer** agent `` (`common/security.md:26`) | `` Raise it as a BLOCKER in the task review (A3, `/dev-execute`) or the merge-risk review (A5, `/dev-handover`) `` |
| **S10** | `## Skeleton Projects` section, whose body is `Use parallel agents to evaluate options:` (`common/patterns.md:3-13`) | delete the whole section |
| **S11** | `## TodoWrite Best Practices` section (`common/hooks.md:17-30`) | delete the whole section — it describes an agent tool, not a repo convention |
| **S12** | Any `See skill: \`<name>\`` sentence not already removed by S3/S4 | delete the sentence |
| **S13** | Any remaining agent name — `tdd-guide`, `code-reviewer`, `planner`, `architect`, `security-reviewer`, `build-error-resolver`, `e2e-runner`, `refactor-cleaner`, `doc-updater`, `<lang>-reviewer` | replace with the matching strata-kb dev skill where one fits, else delete the sentence. Mapping: design/architecture → `` `/dev-design` ``; planning → `` `/dev-plan` ``; write-tests-first / implement → `` `/dev-execute` ``; per-task code review → `the A3 task review in /dev-execute`; security / merge risk → `the A5 merge-risk review in /dev-handover`; full ticket pipeline → `` `/dev-implement-ticket` ``; service-knowledge bootstrap → `` `/dev-code-seed` ``; ticket close-out → `` `/dev-handover` ``. `build-error-resolver`, `e2e-runner`, `refactor-cleaner`, `doc-updater` have no counterpart: delete. |
| **S14** | A relative link whose target is not one of the ten pack files — e.g. `[performance.md](performance.md)` in `web/testing.md` | rewrite to the pack-relative path if the target is in the pack, else inline the value and drop the link |

The words `ECC`, `everything-claude-code`, `~/.claude`, `See skill:` must not
appear in any file this plan creates. T1's test asserts exactly that.

### 2.4 File shape (every pack file)

Line 1 is the extends line, on **one source line** (it is a test needle; do
not wrap it):

```
> This file extends [common/<part>.md](../common/<part>.md) with <Language>-specific content.
```

`<Language>` per language id:

| `<lang>` | `<Language>` | Entry-file title (unchanged) |
|---|---|---|
| `python` | `Python` | `# Python coding conventions` |
| `ts` | `TypeScript / JavaScript` | `# TypeScript / JavaScript coding conventions` |
| `java` | `Java` | `# Java coding conventions` |
| `go` | `Go` | `# Go coding conventions` |
| `dotnet` | `C# / .NET` | `# C# / .NET coding conventions` |
| `php` | `PHP` | `# PHP coding conventions` |
| `rust` | `Rust` | `# Rust coding conventions` |
| `swift` | `Swift` | `# Swift coding conventions` |
| `dart` | `Dart / Flutter` | `# Dart / Flutter coding conventions` |
| `e2e-playwright` | `Playwright e2e` | `# Playwright e2e conventions` |

Then, in order:

```

# <Language> <part title>

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/<lang>.local.md`.

<sections>
```

`<part title>` is `coding style`, `patterns`, `security`, `testing`,
`hooks` — lower case, e.g. `# Python coding style`, `# Go testing`.

The five `common/` files have **no** extends line. They start at the title:

```
# <Part title> — shared

Language-agnostic rules, scaffolded into every dev repo. A file under
`docs/conventions/<lang>/` extends its counterpart here; where the two
disagree, the language file wins. Record repo-specific deviations in the
relevant `docs/conventions/<lang>.local.md`.

<sections>
```

`<Part title>`: `Coding style`, `Patterns`, `Security`, `Testing`, `Hooks`.

### 2.5 Merge and conflict rules

- **M1 — same heading on both sides.** When a source section's heading
  matches a section moved out of the entry file (`## Naming`,
  `## Error handling`, `## Module structure` ≈ source's
  `## Module Organization`), keep **one** heading: the entry file's bullets
  come first, then the source's bullets and code blocks, with any source
  bullet that merely restates an entry-file bullet dropped. See the worked
  fragment in §4.2.
- **M2 — heading case.** Source headings are Title Case
  (`## Error Handling`, `## Secret Management`). Rewrite every heading to
  sentence case to match our existing templates (`## Error handling`,
  `## Secret management`). Proper nouns keep their case
  (`## Null safety`, `## ASP.NET Core integration tests`).
- **C1 — the Linting preset wins.** Where a source names a formatter or
  linter that contradicts the entry file's `## Linting (preset)`, the preset
  wins. Replace the source's tool list with one bullet:
  `` The formatter and linter are fixed by the `## Linting (preset)` section of `docs/conventions/<lang>.md`; that preset wins over any tool named here. ``
  (Fires for: python — source says black+isort+ruff, preset is ruff only;
  php — source says PHP-CS-Fixer *or* Pint, preset is PHP-CS-Fixer; java, go,
  dotnet, rust, swift, dart, ts.)
- **C2 — coverage numbers.** `common/testing.md` states 80% minimum. Keep it
  in `common/testing.md` only; never repeat a coverage number in a language
  `testing.md` unless the source gives a language-specific command for
  measuring it.
- **C3 — no cross-repo paths.** Every path named in a pack file is either
  relative inside `docs/conventions/`, or a real path in the scaffolded repo
  (`.claude/settings.json`, `docs/impl/…`). Never an absolute home path.

### 2.6 Section order in `<lang>/coding-style.md`

1. extends line, blank, title, blank, ownership paragraph
2. the entry file's `## Naming`, verbatim
3. the entry file's `## Module structure`, verbatim (skip if the entry file
   has none — `e2e-playwright`)
4. every kept source section, in source order, with M1 and M2 applied
5. the entry file's `## Error handling`, verbatim (skip if none)
6. the entry file's `## Logging`, verbatim (skip if none)

Steps 2/3/5/6 move text **out of** the entry file. The entry file must no
longer contain those headings when the task is done.

### 2.7 Section order in `<lang>/testing.md`

1. extends line, blank, title, blank, ownership paragraph
2. the entry file's `## Testing` section, moved here under the heading
   `## Ground rules` (renamed: a bare `## Testing` inside `testing.md` reads
   as a stutter)
3. every kept source section, in source order, with M2 applied

### 2.8 Length ceilings

A pack file must not exceed:

- `coding-style.md`: source line count + 45
- `patterns.md`, `security.md`, `testing.md`, `hooks.md`: source line count + 15
- and never more than **300 lines** whatever the arithmetic says.

Exact ceilings are in each task's recipe table. If a file would exceed its
ceiling, cut the longest code block in the source rather than cutting a rule.

---

## 3. Task list

| Task | Scope | Touches tests? |
|---|---|---|
| **T1** | `conventions.py` (`CONVENTION_PARTS` + the `common/` loop), the 5 `conventions-common-*.md` templates, both pointer templates, `_CLAUDE_BLOCK`, the lenient tests | yes |
| **T2** | `python` pack (5 templates) + reshape `conventions-python.md` | no |
| **T3** | `ts` pack + entry file | no |
| **T4** | `java` pack + entry file | no |
| **T5** | `go` pack + entry file | no |
| **T6** | `dotnet` pack + entry file | no |
| **T7** | `php` pack + entry file | no |
| **T8** | `rust` pack + entry file | no |
| **T9** | `swift` pack + entry file | no |
| **T10** | `dart` pack + entry file | no |
| **T11** | `e2e-playwright` pack + entry file | no |
| **T12** | `conventions.py` per-language loop, dev wrappers, canon regen, CHANGELOG, flip the tests to strict, full suite | yes |

T2–T11 are independent of each other and of T12. They may run in parallel
worktrees. **The per-language `docs/conventions/<lang>/` loop in
`scaffold_conventions` lands in T12, not T1** — see §9, resolved ambiguity A1.

---

## 4. The worked example (the register every other file must match)

### 4.1 `src/strata_kb/templates/init/conventions-python-coding-style.md`

Derived from `~/.claude/rules/ecc/python/coding-style.md` (42 lines, S1 strips
its frontmatter, S2 its extends line, S3 its `## Reference` section) plus the
`## Naming`, `## Module structure`, `## Error handling` and `## Logging`
sections moved verbatim out of `conventions-python.md`. C1 fires: the source's
black/isort/ruff list is replaced by the deferral bullet.

Final text, exactly:

```markdown
> This file extends [common/coding-style.md](../common/coding-style.md) with Python-specific content.

# Python coding style

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/python.local.md`.

## Standards

- Follow **PEP 8**.
- Use **type annotations** on every function signature.
- The formatter and linter are fixed by the `## Linting (preset)` section of
  `docs/conventions/python.md`; that preset wins over any tool named here.

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

## Immutability

Prefer immutable data structures — a new object, never a mutated one:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class User:
    name: str
    email: str
```

```python
from typing import NamedTuple


class Point(NamedTuple):
    x: float
    y: float
```

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
```

Notes an implementer must carry to every other file:

- Line 1 is the extends line and is **not wrapped**, even though it is 104
  characters — it is a `startswith` needle in the test.
- Prose wraps at 72–76 columns, like every other template in this directory.
- Source headings were Title Case (`## Formatting`); the output is sentence
  case (M2). The source's `## Formatting` section disappeared into the C1
  bullet under `## Standards`.
- The source's `## Reference` section (`See skill: \`python-patterns\` …`) is
  gone (S3), and nothing replaces it.

### 4.2 M1 demonstrated — `conventions-go-coding-style.md`, `## Error handling`

`~/.claude/rules/ecc/golang/coding-style.md` has its own `## Error Handling`;
so does `conventions-go.md`. One heading survives. The entry file's three
bullets come first; the source's sentence "Always wrap errors with context:"
is dropped because bullet 2 already states it; the source's code block is
kept as the illustration:

```markdown
## Error handling

- Errors are values: return `error` as the last result, check it at
  every call site; never `_ =` an error away.
- Wrap with context: `fmt.Errorf("resolving ref: %w", err)`; match with
  `errors.Is` / `errors.As`, not string comparison.
- Fail fast at boundaries: validate input where data enters and return
  an error naming the offending value. `panic` only for programmer
  errors.

```go
if err != nil {
    return fmt.Errorf("failed to create user: %w", err)
}
```
```

---

## 5. The entry files

### 5.1 `src/strata_kb/templates/init/conventions-python.md` — final text, exactly

```markdown
# Python coding conventions

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/python.local.md`; that file is never touched by `kb init`
and OVERRIDES this one where they conflict. Where either file conflicts
with the repo's existing dominant style, the repo wins locally — record
the conflict as a finding in the PR.

## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/python.local.md` wins over both.

| Topic | Python | Shared |
|---|---|---|
| Coding style | [python/coding-style.md](python/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [python/patterns.md](python/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [python/security.md](python/security.md) | [common/security.md](common/security.md) |
| Testing | [python/testing.md](python/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [python/hooks.md](python/hooks.md) | [common/hooks.md](common/hooks.md) |

## Citation comments

Every standard-derived value (code, format, enum, threshold) is verbatim
from the resolved KB section at the pinned version and carries a citation
comment on the same line or the line above:

```python
MAX_ALTITUDE_FT = 60_000  # per ATM-STD §5.3 @ v2.1
```

## Linting (preset)

The preset below is the target strength. When this repo has no linter, the
first task of a dev plan creates these files and records the command as
`cmd.lint`. Where `cmd.lint` fails on the untouched tree, narrow `select` /
rules / warning caps to what passes, and list each narrowed rule under
`## Findings` in the PR body as a tightening still owed.

`ruff.toml`:

```toml
target-version = "py311"
line-length = 88

[lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "T20", "N"]

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
```

Diff against today's file, stated plainly: the opening block is byte-identical;
`## Conventions pack` is inserted after it; `## Naming`, `## Module structure`,
`## Error handling`, `## Logging` and `## Testing` are deleted (their text
moved into the pack); `## Citation comments` and `## Linting (preset)` are
byte-identical to today's.

### 5.2 Per-language rule for the other nine entry files

Apply exactly the same transform. Only three things vary:

1. The **column header** of the middle table column is `<Language>` from the
   table in §2.4 (`TypeScript / JavaScript`, `Java`, `Go`, `C# / .NET`, `PHP`,
   `Rust`, `Swift`, `Dart / Flutter`, `Playwright e2e`).
2. The **link paths** use the language id: `[ts/coding-style.md](ts/coding-style.md)`,
   `[e2e-playwright/testing.md](e2e-playwright/testing.md)`, and so on. The
   `common/` column is identical in all ten files.
3. The `.local.md` path in the intro sentence is `docs/conventions/<lang>.local.md`.

The `## Conventions pack` block, filled for `<lang>` / `<Language>`:

```markdown
## Conventions pack

Read this file first, then the pack. Each language file extends its
`common/` counterpart; where the two disagree, the language file wins, and
`docs/conventions/<lang>.local.md` wins over both.

| Topic | <Language> | Shared |
|---|---|---|
| Coding style | [<lang>/coding-style.md](<lang>/coding-style.md) | [common/coding-style.md](common/coding-style.md) |
| Patterns | [<lang>/patterns.md](<lang>/patterns.md) | [common/patterns.md](common/patterns.md) |
| Security | [<lang>/security.md](<lang>/security.md) | [common/security.md](common/security.md) |
| Testing | [<lang>/testing.md](<lang>/testing.md) | [common/testing.md](common/testing.md) |
| Hooks | [<lang>/hooks.md](<lang>/hooks.md) | [common/hooks.md](common/hooks.md) |
```

It is inserted immediately after the ownership paragraph and immediately
before `## Citation comments`.

Sections deleted from each entry file (those that exist in it):
`## Naming`, `## Module structure`, `## Error handling`, `## Logging`,
`## Testing`. For `e2e-playwright` also `## Test structure`,
`## Flakiness and timing`, `## Diagnostics` — see T11. Nothing else is
touched; in particular the `this file covers e2e on top of the app's
language conventions` paragraph in `conventions-e2e-playwright.md` stays.

---

## 6. T1 — scaffold, `common/`, pointers, CLAUDE block, lenient tests

### 6.1 Pre-flight

```
cd /Users/vuonglq01685/Documents/Projects/AERO-KB
git status --short          # expect only the untracked .claude/skills/*, .coverage, AGENTS.md, CLAUDE.md
git log --oneline -1        # expect d4c1606
uv run pytest tests/test_conventions.py tests/test_init.py tests/test_templates.py -q
```
Expected: `447 passed`.

GitNexus, before touching `conventions.py`:
```
impact({target: "scaffold_conventions", direction: "upstream"})
impact({target: "ensure_claude_block", direction: "upstream"})
impact({target: "init_repo", direction: "upstream"})
```
Report the blast radius. `init_repo` is expected to be HIGH or CRITICAL (it is
the CLI entry point for every `kb init`); say so before editing, and note that
the edit is additive — no signature changes, no removals.

### 6.2 `src/strata_kb/conventions.py` — edit 1 of 3

Insert after `LANG_GLOBS` (i.e. after the closing `}` on line 90, before
`def _template_text`), separated by two blank lines:

```python
# The five topics of a conventions pack. One `docs/conventions/common/<part>.md`
# per repo plus one `docs/conventions/<lang>/<part>.md` per scaffolded
# language; the language file extends the common one, and
# `docs/conventions/<lang>.md` is the entry file that links both.
CONVENTION_PARTS: tuple[str, ...] = (
    "coding-style",
    "patterns",
    "security",
    "testing",
    "hooks",
)
```

### 6.3 `src/strata_kb/conventions.py` — edit 2 of 3

In `scaffold_conventions`, insert the shared-pack loop between the three
`_template_text` reads and the `for lang in langs:` loop.

Old:
```python
    stub = _template_text("conventions-local-stub.md")
    mdc = _template_text("conventions-pointer.mdc")
    instr = _template_text("conventions-pointer.instructions.md")
    for lang in langs:
```

New:
```python
    stub = _template_text("conventions-local-stub.md")
    mdc = _template_text("conventions-pointer.mdc")
    instr = _template_text("conventions-pointer.instructions.md")
    # Language-agnostic half of the pack: one copy per repo, not per
    # language. Written after the no-language early return above, so a repo
    # with nothing detected still gets no docs/conventions/ directory.
    for part in CONVENTION_PARTS:
        _sync(
            target,
            f"docs/conventions/common/{part}.md",
            _template_text(f"conventions-common-{part}.md"),
            report,
        )
    for lang in langs:
```

Also extend the docstring's first paragraph. Old:

```python
    """Scaffold conventions files for every detected-or-forced language.

    Base + pointer files are package-owned (create-or-refresh); the
```

New:

```python
    """Scaffold conventions files for every detected-or-forced language.

    Also writes the language-agnostic half of the conventions pack,
    `docs/conventions/common/<part>.md`, once per repo.

    Base + pointer files are package-owned (create-or-refresh); the
```

### 6.4 `src/strata_kb/conventions.py` — edit 3 of 3 (`_CLAUDE_BLOCK`)

Old:
```python
_CLAUDE_BLOCK = (
    f"{CLAUDE_MARKER}\n"
    "**Coding conventions.**\n"
    "For each language you touch, read `docs/conventions/<lang>.md`; if\n"
    "`docs/conventions/<lang>.local.md` exists it overrides the base file.\n"
    "Where either conflicts with the repo's existing dominant style, the\n"
    "repo wins locally — record the conflict as a finding in the PR.\n"
)
```

New:
```python
_CLAUDE_BLOCK = (
    f"{CLAUDE_MARKER}\n"
    "**Coding conventions.**\n"
    "For each language you touch, read `docs/conventions/<lang>.md` and the\n"
    "five pack files it links under `docs/conventions/<lang>/` and\n"
    "`docs/conventions/common/`; if `docs/conventions/<lang>.local.md`\n"
    "exists it overrides them all. Where any of them conflicts with the\n"
    "repo's existing dominant style, the\n"
    "repo wins locally — record the conflict as a finding in the PR.\n"
)
```

The last two lines keep their exact split: `tests/test_conventions.py:258`
matches the raw needle `"repo wins locally"` on one source line.
`test_claude_block_created_when_file_missing` also needs
`docs/conventions/<lang>.md` and `docs/conventions/<lang>.local.md` — both
still present. No test edit required here.

### 6.5 `src/strata_kb/templates/init/conventions-pointer.mdc`

Old (body, lines 6-10):
```
Before writing or reviewing {lang} code, read `docs/conventions/{lang}.md`.
If `docs/conventions/{lang}.local.md` exists it overrides the base file.
Where either conflicts with the repo's existing dominant style, the repo
wins locally — record the conflict as a finding in the PR.
```

New:
```
Before writing or reviewing {lang} code, read `docs/conventions/{lang}.md`
and the five pack files it links under `docs/conventions/{lang}/` and
`docs/conventions/common/`. If `docs/conventions/{lang}.local.md` exists it
overrides them all. Where any of them conflicts with the repo's existing
dominant style, the repo wins locally — record the conflict as a finding in
the PR.
```

### 6.6 `src/strata_kb/templates/init/conventions-pointer.instructions.md`

Its body is byte-identical to the `.mdc` body. Apply the **same** replacement,
verbatim. Do not retype it — derive:

```
python - <<'PY'
from pathlib import Path
old = """Before writing or reviewing {lang} code, read `docs/conventions/{lang}.md`.
If `docs/conventions/{lang}.local.md` exists it overrides the base file.
Where either conflicts with the repo's existing dominant style, the repo
wins locally — record the conflict as a finding in the PR.
"""
new = """Before writing or reviewing {lang} code, read `docs/conventions/{lang}.md`
and the five pack files it links under `docs/conventions/{lang}/` and
`docs/conventions/common/`. If `docs/conventions/{lang}.local.md` exists it
overrides them all. Where any of them conflicts with the repo's existing
dominant style, the repo wins locally — record the conflict as a finding in
the PR.
"""
for p in (
    Path("src/strata_kb/templates/init/conventions-pointer.mdc"),
    Path("src/strata_kb/templates/init/conventions-pointer.instructions.md"),
):
    t = p.read_text(encoding="utf-8")
    assert t.count(old) == 1, p
    p.write_text(t.replace(old, new), encoding="utf-8", newline="\n")
    print("patched", p)
PY
```
Expected output: two `patched …` lines.

`tests/test_templates.py::test_conventions_local_stub_and_pointer_templates`
needs `docs/conventions/{lang}.md`, `docs/conventions/{lang}.local.md` and the
raw one-line needle `wins locally` — all three survive. No test edit here.

### 6.7 The five `common/` templates — recipes

Every one gets the §2.4 `common/` header. Substitutions S1–S14 apply
throughout; M2 (sentence-case headings) applies throughout.

| Target `src/strata_kb/templates/init/…` | Source | Keep (sentence-cased) | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-common-coding-style.md` | `common/coding-style.md` (90 L) | `## Immutability (critical)`, `## Core principles` (KISS / DRY / YAGNI), `## File organization`, `## Error handling`, `## Input validation`, `## Naming conventions`, `## Code smells to avoid`, `## Code quality checklist` | Nothing dropped. In `## Naming conventions`, delete the `Custom hooks: camelCase with a use prefix` bullet — it is React-specific and belongs in `ts/`. | 105 |
| `conventions-common-patterns.md` | `common/patterns.md` (31 L) | `## Design patterns` → promote its two children to `## Repository pattern` and `## API response format` | Delete `## Skeleton Projects` whole (S10). | 30 |
| `conventions-common-security.md` | `common/security.md` (29 L) | `## Mandatory security checks`, `## Secret management`, `## Security response protocol` | S9 on step 2 of the protocol. Retitle the first section's lead-in from `Before ANY commit:` to `` Before any commit — this is the A5 merge-risk checklist in `/dev-handover`: `` | 35 |
| `conventions-common-testing.md` | `common/testing.md` (57 L) | `## Minimum test coverage: 80%`, `## Test-driven development`, `## Troubleshooting test failures`, `## Test structure (AAA pattern)` incl. its TypeScript example and the `### Test naming` examples | Delete `## Agent Support` whole (S4). S8 on step 1 of Troubleshooting. | 60 |
| `conventions-common-hooks.md` | `common/hooks.md` (30 L) | `## Hook types`, `## Auto-accept permissions` | Delete `## TodoWrite Best Practices` whole (S11). S6 on the `allowedTools` bullet. Add one lead sentence under the title: `` Hooks are configured per repo in `.claude/settings.json`, committed with the code. Nothing here refers to a user-level configuration. `` | 30 |

### 6.8 Tests — `tests/test_templates.py`

**(a)** Add to the import block at the top of the file, after
`from strata_kb.initcmd import COMMON_TEMPLATES, HUB_TEMPLATES, CHILD_TEMPLATES`:

```python
from strata_kb.conventions import CONVENTION_PARTS, LANG_IDS
```

**(b)** Replace the `CONVENTIONS_SECTION_HEADINGS` tuple (lines 1517-1525).

Old:
```python
CONVENTIONS_SECTION_HEADINGS = (
    "## Naming",
    "## Module structure",
    "## Error handling",
    "## Logging",
    "## Citation comments",
    "## Testing",
    "## Linting (preset)",
)
```

New:
```python
# The two sections that stay in the entry file whatever else moves: the
# citation rule and the lint preset. `## Linting (preset)` in particular is
# named by the dev-plan wrappers, which is pinned below in
# test_dev_plan_refuses_a_draft_design_and_writes_the_cmd_headers.
CONVENTIONS_SECTION_HEADINGS = (
    "## Citation comments",
    "## Linting (preset)",
)

# Moved into `<lang>/coding-style.md` (the first four) and
# `<lang>/testing.md` (the last) when a language's pack lands.
CONVENTIONS_MOVED_HEADINGS = (
    "## Naming",
    "## Module structure",
    "## Error handling",
    "## Logging",
    "## Testing",
)
# The two of those that every entry file carries today — e2e-playwright has
# no `## Module structure`, `## Error handling` or `## Logging`, so only
# these two can be asserted present on an un-reshaped file.
CONVENTIONS_UNIVERSAL_MOVED = ("## Naming", "## Testing")

CONVENTIONS_PACK_MARKER = "## Conventions pack"
```

**(c)** Add, immediately after
`test_conventions_local_stub_and_pointer_templates` (which ends at line 1607
today):

```python
@pytest.mark.parametrize("lang", LANG_IDS)
def test_conventions_entry_file_links_its_pack(lang):
    """Lenient during the per-language rollout.

    A language whose entry file has not been reshaped yet must still carry
    the headings that are about to move; a reshaped one must carry the pack
    table and none of them. Task 12 deletes the lenient branch, so an entry
    file that is never reshaped fails there instead of passing silently.
    """
    text = _read_init_template(f"conventions-{lang}.md")
    if CONVENTIONS_PACK_MARKER not in text:
        for heading in CONVENTIONS_UNIVERSAL_MOVED:
            assert heading in text, f"{lang}: un-reshaped entry file lost {heading!r}"
        return
    for part in CONVENTION_PARTS:
        assert f"({lang}/{part}.md)" in text, f"{lang}: no link to {lang}/{part}.md"
        assert f"(common/{part}.md)" in text, f"{lang}: no link to common/{part}.md"
    for heading in CONVENTIONS_MOVED_HEADINGS:
        assert heading not in text, f"{lang}: {heading!r} should have moved into the pack"


@pytest.mark.parametrize("lang", LANG_IDS)
def test_language_pack_templates_exist_and_extend_their_common_file(lang):
    """Lenient during the per-language rollout: a language with none of its
    five pack templates yet is skipped by name. Task 12 deletes the skip."""
    base = resources.files("strata_kb").joinpath("templates/init")
    names = {part: f"conventions-{lang}-{part}.md" for part in CONVENTION_PARTS}
    if not any(base.joinpath(n).is_file() for n in names.values()):
        pytest.skip(f"{lang}: conventions pack templates not written yet")
    for part, name in names.items():
        assert base.joinpath(name).is_file(), name
        text = _read_init_template(name)
        assert text.startswith(
            f"> This file extends [common/{part}.md](../common/{part}.md) with "
        ), name
        for banned in ("ECC", "everything-claude", "~/.claude", "See skill:"):
            assert banned not in text, f"{name}: {banned!r} survived"


def test_common_pack_templates_exist_and_carry_no_extends_line():
    base = resources.files("strata_kb").joinpath("templates/init")
    for part in CONVENTION_PARTS:
        name = f"conventions-common-{part}.md"
        assert base.joinpath(name).is_file(), name
        text = _read_init_template(name)
        assert text.startswith("# "), name
        assert "This file extends" not in text, name
        for banned in ("ECC", "everything-claude", "~/.claude", "See skill:"):
            assert banned not in text, f"{name}: {banned!r} survived"
```

### 6.9 Tests — `tests/test_conventions.py`

Add `CONVENTION_PARTS` to the existing import block:

Old:
```python
from strata_kb.conventions import (
    CLAUDE_MARKER,
    LANG_GLOBS,
    detect_langs,
    ensure_claude_block,
    scaffold_conventions,
)
```
New:
```python
from strata_kb.conventions import (
    CLAUDE_MARKER,
    CONVENTION_PARTS,
    LANG_GLOBS,
    detect_langs,
    ensure_claude_block,
    scaffold_conventions,
)
```

Add, immediately after
`test_scaffold_creates_base_local_and_pointers_for_detected_lang`:

```python
def test_scaffold_writes_the_shared_common_pack_once(tmp_path: Path):
    # Task 12 extends this with the per-language half
    # (docs/conventions/<lang>/<part>.md), which lands with the loop that
    # writes it.
    _touch(tmp_path, "pyproject.toml")
    report = _scaffold(tmp_path)
    for part in CONVENTION_PARTS:
        dest = tmp_path / "docs" / "conventions" / "common" / f"{part}.md"
        assert dest.is_file(), part
        assert f"docs/conventions/common/{part}.md" in report.created
        assert "~/.claude" not in dest.read_text(encoding="utf-8"), part


def test_scaffold_writes_common_once_for_a_multi_language_repo(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    _touch(tmp_path, "web/package.json")
    report = _scaffold(tmp_path)
    created = [r for r in report.created if r.startswith("docs/conventions/common/")]
    assert len(created) == len(CONVENTION_PARTS), created
```

`test_scaffold_is_idempotent_when_current` and
`test_scaffold_without_manifests_notes_and_writes_nothing` still hold: the
common loop runs after the no-language early return, and `_sync` is a no-op on
an unchanged file.

### 6.10 Verify and commit

```
uv run pytest tests/test_conventions.py tests/test_init.py tests/test_templates.py -q
```
Expected: `468 passed, 10 skipped` — 447 existing, plus 10 entry-file params
(all taking the lenient branch), plus 10 pack params (all skipped), plus the
common-template test, plus 2 scaffold tests. Zero failures.

Smoke test in a throwaway directory:
```
mkdir -p /tmp/kbsmoke-t1 && cd /tmp/kbsmoke-t1 && git init -q .
uv --project /Users/vuonglq01685/Documents/Projects/AERO-KB run kb init . --kind dev --lang python
ls docs/conventions/common/
```
Expected: `coding-style.md  hooks.md  patterns.md  security.md  testing.md`.
Then `rm -rf /tmp/kbsmoke-t1`.

GitNexus: `detect_changes()`. Expect `scaffold_conventions` and
`ensure_claude_block` as the only changed symbols.

```
cd /Users/vuonglq01685/Documents/Projects/AERO-KB
git add src/strata_kb/conventions.py \
        src/strata_kb/templates/init/conventions-common-*.md \
        src/strata_kb/templates/init/conventions-pointer.mdc \
        src/strata_kb/templates/init/conventions-pointer.instructions.md \
        tests/test_conventions.py tests/test_templates.py
git commit -m "feat(conventions): scaffold the shared docs/conventions/common/ pack

Five language-agnostic files — coding style, patterns, security, testing,
hooks — written once per dev repo next to the existing per-language base
file. The Cursor and Copilot pointers and the CLAUDE.md block now name the
pack directory as well as the entry file.

The pack tests are deliberately lenient: an entry file without the
\`## Conventions pack\` table still has to carry the headings that are about
to move, and a language with no pack templates yet is skipped by name. Task
12 removes both escape hatches once all ten languages have landed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NtdRAkmyTshnfR99NbY5Li"
```

---

## 7. T2–T11 — one task per language

### 7.1 The shape of every one of these tasks

1. Read the source directory (§2.2) and `src/strata_kb/templates/init/conventions-<lang>.md`.
2. Write the five `src/strata_kb/templates/init/conventions-<lang>-<part>.md`
   files from the task's recipe table, applying §2.3 (S1–S14), §2.4 (shape),
   §2.5 (M1, M2, C1–C3), §2.6/§2.7 (section order) and §2.8 (ceilings).
3. Reshape `src/strata_kb/templates/init/conventions-<lang>.md` per §5.2.
4. Verify:
   ```
   uv run pytest tests/test_conventions.py tests/test_init.py tests/test_templates.py -q
   ```
   Expected: the same total as the previous task with **one fewer skip**
   (this language's pack param now runs). Zero failures.
   ```
   uv run pytest "tests/test_templates.py::test_language_pack_templates_exist_and_extend_their_common_file[<lang>]" \
                 "tests/test_templates.py::test_conventions_entry_file_links_its_pack[<lang>]" -q
   ```
   Expected: `2 passed` (no skips).
5. Smoke:
   ```
   mkdir -p /tmp/kbsmoke-<lang> && cd /tmp/kbsmoke-<lang> && git init -q .
   uv --project /Users/vuonglq01685/Documents/Projects/AERO-KB run kb init . --kind dev --lang <lang>
   grep -c "Conventions pack" docs/conventions/<lang>.md
   rm -rf /tmp/kbsmoke-<lang>
   ```
   Expected: `1`. (`docs/conventions/<lang>/` does not exist yet — that loop
   lands in T12; this smoke only proves the reshaped entry file ships.)
6. Commit:
   ```
   git add src/strata_kb/templates/init/conventions-<lang>*.md
   git commit -m "feat(conventions): <Language> conventions pack

   Five pack files under docs/conventions/<lang>/ extending their common/
   counterparts. conventions-<lang>.md becomes the entry file: it keeps
   Citation comments and Linting (preset), links the ten pack files, and
   hands its Naming / Module structure / Error handling / Logging sections
   to <lang>/coding-style.md and its Testing section to <lang>/testing.md.

   Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
   Claude-Session: https://claude.ai/code/session_01NtdRAkmyTshnfR99NbY5Li"
   ```

No test file is edited in T2–T11. No Python file is edited in T2–T11.

### 7.2 T2 — `python`

`coding-style` is written out in full in §4.1 — copy it exactly. The other four:

| Target | Source (lines) | Keep | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-python-coding-style.md` | `python/coding-style.md` (42) + entry sections | **See §4.1 — exact text given** | — | 90 |
| `conventions-python-patterns.md` | `python/patterns.md` (39) | `## Protocol (duck typing)`, `## Dataclasses as DTOs`, `## Context managers and generators` (spell out the `&`) | S3 on `## Reference` | 50 |
| `conventions-python-security.md` | `python/security.md` (30) | `## Secret management` (the `os.environ[...]` example, kept because it raises rather than defaulting), `## Security scanning` (bandit) | S3 on `## Reference` (django-security). Drop the `from dotenv import load_dotenv` / `load_dotenv()` lines: `python-dotenv` is a dependency this repo does not assume (§2.1 "no new dependency" applies to what we tell readers to install too). Keep `api_key = os.environ["OPENAI_API_KEY"]  # KeyError if missing` with the comment rewritten to `# raises KeyError if missing — never .get()`. | 40 |
| `conventions-python-testing.md` | `python/testing.md` (38) + entry `## Testing` | Entry `## Testing` → `## Ground rules`; then `## Framework` (pytest), `## Coverage` (`pytest --cov=src --cov-report=term-missing`), `## Test organization` (the `pytest.mark` example) | S3 on `## Reference` | 55 |
| `conventions-python-hooks.md` | `python/hooks.md` (19) | `## PostToolUse hooks`, `## Warnings` | S5 on `~/.claude/settings.json`. Rewrite the black/ruff bullet per C1 to name only what the entry-file preset names: `` **ruff**: `ruff format` then `ruff check --fix` on the edited `.py` file. `` Keep the mypy/pyright bullet as `` **mypy** or **pyright**: type-check after editing a `.py` file, if the repo has either configured. `` | 34 |

### 7.3 T3 — `ts`

| Target | Source (lines) | Keep | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-ts-coding-style.md` | `typescript/coding-style.md` (199) + entry sections | `## Types and interfaces` with its three children (`### Public APIs`, `### Interfaces vs. type aliases`, `### Avoid any`, `### React props`), `## Immutability`, `## Input validation`, `## Console.log` | S1, S2. M1 on `## Error handling` (entry bullets first, then the source's `Result`/try-catch material, dropping any bullet the entry file already states). C1: no tool list survives — the entry file's ESLint preset governs. The file is long: if it exceeds the ceiling, cut the **longest** code block under `### Public APIs` first. | 245 |
| `conventions-ts-patterns.md` | `typescript/patterns.md` (52) | `## API response format`, `## Custom hooks pattern`, `## Repository pattern` | S1, S2 | 60 |
| `conventions-ts-security.md` | `typescript/security.md` (28) | `## Secret management` | S1, S2, S4 on `## Agent Support` (which contains `Use **security-reviewer** skill`) | 30 |
| `conventions-ts-testing.md` | `typescript/testing.md` (18) + entry `## Testing` | Entry `## Testing` → `## Ground rules`; then `## E2E testing` (Playwright), with a pointer sentence added: `` A repo with a Playwright suite also scaffolds `docs/conventions/e2e-playwright.md` and its pack — the e2e conventions live there. `` | S1, S2, S4 on `## Agent Support` | 40 |
| `conventions-ts-hooks.md` | `typescript/hooks.md` (22) | `## PostToolUse hooks`, `## Stop hooks` | S1, S2, S5 | 32 |

### 7.4 T4 — `java`

| Target | Source (lines) | Keep | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-java-coding-style.md` | `java/coding-style.md` (114) + entry sections | `## Immutability`, `## Modern Java features`, `## Optional usage`, `## Streams` | S1, S2, S3 (`## References` → springboot/jpa skills). M1 on `## Naming` and `## Error handling`. C1: drop `## Formatting`'s tool list — the entry file's spotless/checkstyle preset governs. | 175 |
| `conventions-java-patterns.md` | `java/patterns.md` (147) | `## Repository pattern`, `## Service layer`, `## Constructor injection`, `## DTO mapping`, `## Builder pattern`, `## Sealed types for domain models`, `## API response envelope` | S1, S2, S3. Every Spring/Quarkus-specific note stays but is prefixed `Spring Boot:` / `Quarkus:` rather than pointing at a skill. | 160 |
| `conventions-java-security.md` | `java/security.md` (101) | `## Secrets management`, `## SQL injection prevention`, `## Input validation`, `## Authentication and authorization`, `## Dependency security`, `## Error messages` | S1, S2, S3 | 112 |
| `conventions-java-testing.md` | `java/testing.md` (133) + entry `## Testing` | Entry `## Testing` → `## Ground rules`; then `## Test framework`, `## Test organization`, `## Unit test pattern`, `## Parameterized tests`, `## Integration tests`, `## Test naming`, `## Coverage` | S1, S2, S3. Lines 114-115 (`see skill: springboot-tdd` / `quarkus-tdd`) are deleted (S12); the surrounding paragraph stays. | 150 |
| `conventions-java-hooks.md` | `java/hooks.md` (18) | `## PostToolUse hooks` | S1, S2, S5 | 30 |

### 7.5 T5 — `go`

| Target | Source (lines) | Keep | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-go-coding-style.md` | `golang/coding-style.md` (32) + entry sections | `## Design principles` (accept interfaces, return structs; small interfaces) | S1, S2, S3. M1 on `## Error handling` — **exact merged text given in §4.2**. C1: `## Formatting`'s gofmt/goimports line is replaced by the C1 deferral bullet, placed under a new `## Standards` heading at the top. | 80 |
| `conventions-go-patterns.md` | `golang/patterns.md` (45) | `## Functional options`, `## Small interfaces`, `## Dependency injection` | S1, S2, S3 | 50 |
| `conventions-go-security.md` | `golang/security.md` (34) | `## Secret management`, `## Security scanning` (gosec), `## Context and timeouts` (spell out the `&`) | S1, S2 | 45 |
| `conventions-go-testing.md` | `golang/testing.md` (31) + entry `## Testing` | Entry `## Testing` → `## Ground rules`; then `## Framework` (table-driven), `## Race detection`, `## Coverage` | S1, S2, S3 | 48 |
| `conventions-go-hooks.md` | `golang/hooks.md` (17) | `## PostToolUse hooks` | S1, S2, S5 | 30 |

### 7.6 T6 — `dotnet`

| Target | Source (lines) | Keep | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-dotnet-coding-style.md` | `csharp/coding-style.md` (72) + entry sections | `## Standards`, `## Types and models`, `## Immutability`, `## Async and error handling` | S1, S2. M1 on `## Error handling` — the entry file's bullets lead, the source's async material follows under the same heading, and the source's `## Async and error handling` heading becomes `## Async`. C1 on `## Formatting`. | 130 |
| `conventions-dotnet-patterns.md` | `csharp/patterns.md` (50) | `## API response pattern`, `## Repository pattern`, `## Options pattern`, `## Dependency injection` | S1, S2 | 60 |
| `conventions-dotnet-security.md` | `csharp/security.md` (58) | `## Secret management`, `## SQL injection prevention`, `## Input validation`, `## Authentication and authorization`, `## Error handling` | S1, S2, S3 (`## References`) | 65 |
| `conventions-dotnet-testing.md` | `csharp/testing.md` (46) + entry `## Testing` | Entry `## Testing` → `## Ground rules`; then `## Test framework`, `## Test organization`, `## ASP.NET Core integration tests`, `## Coverage` | S1, S2 | 62 |
| `conventions-dotnet-hooks.md` | `csharp/hooks.md` (25) | `## PostToolUse hooks`, `## Stop hooks` | S1, S2, S5 | 36 |

### 7.7 T7 — `php`

| Target | Source (lines) | Keep | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-php-coding-style.md` | `php/coding-style.md` (40) + entry sections | `## Standards` (PSR-12, strict types), `## Immutability`, `## Imports` | S1, S2, S3. M1 on `## Error handling`. C1 on `## Formatting` — the entry file's `.php-cs-fixer.dist.php` preset governs; the PHPStan/Psalm bullet is kept, reworded to `` Static analysis (PHPStan or Psalm) if the repo has one configured; the level is the repo's, not this file's. `` | 88 |
| `conventions-php-patterns.md` | `php/patterns.md` (33) | `## Thin controllers, explicit services`, `## DTOs and value objects`, `## Dependency injection`, `## Boundaries` | S1, S2, S3 (api-design / laravel-patterns skills) | 40 |
| `conventions-php-security.md` | `php/security.md` (37) | `## Input and output`, `## Database safety`, `## Secrets and dependencies`, `## Auth and session safety` | S1, S2, S3 | 42 |
| `conventions-php-testing.md` | `php/testing.md` (39) + entry `## Testing` | Entry `## Testing` → `## Ground rules`; then `## Framework` (PHPUnit, Pest if configured — do not mix), `## Coverage`, `## Test organization`, `## Inertia` | S1, S2, S3 (lines 38-39, tdd-workflow / laravel-tdd) | 55 |
| `conventions-php-hooks.md` | `php/hooks.md` (24) | `## PostToolUse hooks`, `## Warnings` | S1, S2, S5 | 34 |

### 7.8 T8 — `rust`

| Target | Source (lines) | Keep | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-rust-coding-style.md` | `rust/coding-style.md` (151) + entry sections | `## Immutability`, `## Ownership and borrowing`, `## Iterators over loops`, `## Module organization` (M1 against the entry's `## Module structure` — keep the entry heading), `## Visibility` | S1, S2, S3. M1 on `## Naming` and `## Error handling`. C1 on `## Formatting` (the entry file's rustfmt/clippy preset governs). | 215 |
| `conventions-rust-patterns.md` | `rust/patterns.md` (168) | `## Repository pattern with traits`, `## Service layer`, `## Newtype pattern for type safety`, `## Enum state machines`, `## Builder pattern`, `## Sealed traits for extensibility control`, `## API response envelope` | S1, S2, S3 | 180 |
| `conventions-rust-security.md` | `rust/security.md` (141) | `## Secrets management`, `## SQL injection prevention`, `## Input validation`, `## Unsafe code`, `## Dependency security`, `## Error messages` | S1, S2, S3 | 152 |
| `conventions-rust-testing.md` | `rust/testing.md` (154) + entry `## Testing` | Entry `## Testing` → `## Ground rules`; then `## Test framework`, `## Test organization`, `## Unit test pattern`, `## Parameterized tests`, `## Async tests`, `## Mocking with mockall`, `## Test naming`, `## Coverage`, `## Testing commands` | S1, S2, S3 | 172 |
| `conventions-rust-hooks.md` | `rust/hooks.md` (16) | `## PostToolUse hooks` | S1, S2, S5 | 28 |

### 7.9 T9 — `swift`

| Target | Source (lines) | Keep | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-swift-coding-style.md` | `swift/coding-style.md` (47) + entry sections | `## Immutability`, `## Concurrency` | S1, S2. M1 on `## Naming` and `## Error handling`. C1 on `## Formatting` (SwiftFormat/SwiftLint are the entry preset's business). | 95 |
| `conventions-swift-patterns.md` | `swift/patterns.md` (66) | `## Protocol-oriented design`, `## Value types`, `## Actor pattern`, `## Dependency injection` | S1, S2, S3 (`## References`) | 72 |
| `conventions-swift-security.md` | `swift/security.md` (33) | `## Secret management` (Keychain, never `UserDefaults`), `## Transport security`, `## Input validation` | S1, S2 | 40 |
| `conventions-swift-testing.md` | `swift/testing.md` (45) + entry `## Testing` | Entry `## Testing` → `## Ground rules`; then `## Framework` (Swift Testing, `@Test` / `#expect`), `## Test isolation`, `## Parameterized tests`, `## Coverage` | S1, S2, S3 | 60 |
| `conventions-swift-hooks.md` | `swift/hooks.md` (20) | `## PostToolUse hooks`, `## Warning` → `## Warnings` | S1, S2, S5 | 32 |

### 7.10 T10 — `dart`

| Target | Source (lines) | Keep | Drop / change | Ceiling |
|---|---|---|---|---|
| `conventions-dart-coding-style.md` | `dart/coding-style.md` (159) + entry sections | `## Immutability`, `## Null safety`, `## Sealed types and pattern matching (Dart 3+)`, `## Async / futures`, `## Imports`, `## Code generation` | S1, S2. M1 on `## Naming` and `## Error handling`. C1 on `## Formatting`. | 220 |
| `conventions-dart-patterns.md` | `dart/patterns.md` (261) | `## Repository pattern`, `## State management: BLoC/Cubit`, `## State management: Riverpod`, `## Dependency injection`, `## ViewModel pattern (without BLoC/Riverpod)`, `## UseCase pattern`, `## Immutable state with freezed`, `## Clean architecture layer boundaries`, `## Navigation (GoRouter)` | S1, S2, S3. At 261 lines this is the longest source: if the ceiling is exceeded, cut the **Riverpod** section's second code block first, then the GoRouter one. | 276 |
| `conventions-dart-security.md` | `dart/security.md` (135) | `## Secrets management`, `## Network security`, `## Input validation`, `## Data protection`, `## Android-specific`, `## iOS-specific`, `## WebView security`, `## Obfuscation and build security` | S1, S2 | 148 |
| `conventions-dart-testing.md` | `dart/testing.md` (215) + entry `## Testing` | Entry `## Testing` → `## Ground rules`; then `## Test framework`, `## Test types`, `## Unit tests: state managers`, `## Widget tests`, `## Fakes over mocks`, `## Async testing`, `## Golden tests`, `## Test naming`, `## Test organization`, `## Coverage` | S1, S2 | 232 |
| `conventions-dart-hooks.md` | `dart/hooks.md` (66) | `## PostToolUse hooks`, `## Recommended hook configuration`, `## Pre-commit checks`, `## Useful one-liners` | S1, S2, S5 — the `## Recommended hook configuration` JSON block is a `~/.claude/settings.json` snippet: keep the JSON, retitle the sentence above it to `` Put this in this repo's `.claude/settings.json`: `` | 80 |

### 7.11 T11 — `e2e-playwright` (no source directory)

Source material: `~/.claude/rules/ecc/web/testing.md` (55 lines, Playwright
parts only) plus the existing `conventions-e2e-playwright.md`. `security.md`
and `hooks.md` have no source at all, so their **exact final text is given
below**; the other three are recipes.

Entry-file sections deleted here (beyond §5.2): `## Test structure`,
`## Flakiness and timing`, `## Diagnostics`. What remains in
`conventions-e2e-playwright.md`: the title, the ownership paragraph, the
"this file covers e2e on top of whatever language convention already
governs the app under test" paragraph, the `## Conventions pack` table, then
`## Citation comments` and `## Linting (preset)` unchanged.

| Target | Source | Keep | Ceiling |
|---|---|---|---|
| `conventions-e2e-playwright-coding-style.md` | entry `## Naming` + entry `## Diagnostics` | `## Naming` verbatim, then `## Diagnostics` verbatim (trace/screenshot/video on CI; no `page.pause()` or debug `console.log` in committed specs — that is a style rule) | 45 |
| `conventions-e2e-playwright-patterns.md` | entry `## Test structure` | `## Test structure` verbatim (page objects, fixtures, role/text/testid locators) | 30 |
| `conventions-e2e-playwright-testing.md` | entry `## Testing` + entry `## Flakiness and timing` + `web/testing.md` | `## Ground rules` (entry `## Testing`), `## Flakiness and timing` (entry, verbatim), `## E2E shape` (the `web/testing.md` code block and its two bullets), `## Cross-browser` (Chrome, Firefox, Safari minimum), `## Responsive` (320, 375, 768, 1024, 1440, 1920; no overflow; touch interactions). S14: delete `web/testing.md`'s `[performance.md](performance.md)` link — no such file in the pack. | 80 |

`src/strata_kb/templates/init/conventions-e2e-playwright-security.md`, in full:

```markdown
> This file extends [common/security.md](../common/security.md) with Playwright e2e-specific content.

# Playwright e2e security

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/e2e-playwright.local.md`.

## Test credentials

- Never commit a real credential to a spec, a fixture, or a
  `playwright.config.*`. Read them from the environment:
  `process.env.E2E_PASSWORD`, and fail loudly when the variable is unset.
- Test accounts are test accounts: never reuse a staff, admin or customer
  login that exists outside the test environment.
- A recorded `storageState.json` holds live session cookies. Write it to a
  gitignored path and never check it in.

## Target environment

- e2e runs against a disposable environment. Never point a suite at
  production, and never at a database whose contents someone else depends
  on.
- Seed and tear down the data a spec needs; a spec that only works against
  a hand-prepared account is not reproducible.

## Trace artefacts

- Traces, videos and screenshots capture whatever was on the page,
  including tokens and personal data. Upload them to the CI run's private
  artefacts, never to a public bucket or a PR comment.
- Redact or avoid asserting on real personal data; use generated fixtures.
```

`src/strata_kb/templates/init/conventions-e2e-playwright-hooks.md`, in full:

```markdown
> This file extends [common/hooks.md](../common/hooks.md) with Playwright e2e-specific content.

# Playwright e2e hooks

Base file — owned by the strata-kb package: `kb init` refreshes it when the
package updates, so do not hand-edit. Record repo-specific deviations in
`docs/conventions/e2e-playwright.local.md`.

Hooks are configured per repo in `.claude/settings.json`, committed with
the code. Nothing here refers to a user-level configuration.

## PostToolUse hooks

- Lint the edited spec with the Playwright ESLint config the
  `## Linting (preset)` section of `docs/conventions/e2e-playwright.md`
  sets up — match on `Write|Edit` and run it on the edited file only.
- Never run the whole suite from a hook: a full Playwright run is minutes
  long, and a hook that slow gets disabled rather than fixed. Run one spec
  or nothing.

## Stop hooks

- A Stop hook may run the suite once, at the end of a session, and only
  when the repo's own `cmd.test.e2e` command is cheap enough to finish
  unattended. Otherwise leave it to CI.
```

---

## 8. T12 — the per-language loop, the wrappers, strict tests, CHANGELOG

### 8.1 Pre-flight

```
uv run pytest tests/test_conventions.py tests/test_init.py tests/test_templates.py -q
```
Expected: `468 passed`, **zero skipped** (all ten languages have landed).
If any skip remains, a language task is missing — stop and say which.

GitNexus: `impact({target: "scaffold_conventions", direction: "upstream"})`
again before editing.

### 8.2 `src/strata_kb/conventions.py` — the per-language loop

In `scaffold_conventions`'s `for lang in langs:` body, insert the pack loop
immediately after the entry-file `_sync` and before the `.local.md` handling.

Old:
```python
    for lang in langs:
        _sync(
            target,
            f"docs/conventions/{lang}.md",
            _template_text(f"conventions-{lang}.md"),
            report,
        )
        local_rel = f"docs/conventions/{lang}.local.md"
```

New:
```python
    for lang in langs:
        _sync(
            target,
            f"docs/conventions/{lang}.md",
            _template_text(f"conventions-{lang}.md"),
            report,
        )
        for part in CONVENTION_PARTS:
            _sync(
                target,
                f"docs/conventions/{lang}/{part}.md",
                _template_text(f"conventions-{lang}-{part}.md"),
                report,
            )
        local_rel = f"docs/conventions/{lang}.local.md"
```

Deliberately not guarded: a language id in `LANG_MANIFESTS` without its five
pack templates must raise `FileNotFoundError` in the suite — that is exactly
what `test_scaffold_produces_four_files_for_every_manifest_lang`'s comment
asks for, and why this loop lands after all ten template sets exist rather
than in T1.

Also extend the docstring line added in §6.3:

Old:
```python
    Also writes the language-agnostic half of the conventions pack,
    `docs/conventions/common/<part>.md`, once per repo.
```
New:
```python
    Also writes the conventions pack: `docs/conventions/common/<part>.md`
    once per repo, and `docs/conventions/<lang>/<part>.md` per language.
```

### 8.3 Dev wrapper edits

Three phrase replacements, applied mechanically across every copy so the
byte-identical blocks stay byte-identical. **Do not hand-edit any wrapper.**

```
cd /Users/vuonglq01685/Documents/Projects/AERO-KB
python - <<'PY'
from pathlib import Path

INIT = Path("src/strata_kb/templates/init")

# --- E1: the REVIEW-CONTRACT criteria bullet (16 wrappers) ------------------
E1_OLD = """  `docs/conventions/<lang>.md` for A3 and A4 — each one's own `.local.md`
  override wins over its base file. Severity is always
  BLOCKER / SUGGESTED / NOTE / NITS.
"""
E1_NEW = """  `docs/conventions/<lang>.md` — plus the five pack files it links under
  `docs/conventions/<lang>/` and `docs/conventions/common/` — for A3 and A4.
  Each one's own `.local.md` override wins over its base file. Severity is
  always BLOCKER / SUGGESTED / NOTE / NITS.
"""

# --- E2: the A4 dispatch line (4 dev-execute wrappers) ----------------------
E2_OLD = """`branch-reviewer` subagent with that path, the plan, the ticket, and
`docs/conventions/<lang>.md` plus its `.local.md` override. One question
"""
E2_NEW = """`branch-reviewer` subagent with that path, the plan, the ticket, and
`docs/conventions/<lang>.md`, the five pack files it links, and its
`.local.md` override. One question
"""

# --- E3: dev-execute step 3, the self-review checkpoint (3 wrappers) --------
E3_OLD = """     `docs/conventions/<lang>.md` plus `docs/conventions/<lang>.local.md`
     overrides (local wins; where either conflicts with the repo's
"""
E3_NEW = """     `docs/conventions/<lang>.md`, the five pack files it links under
     `docs/conventions/<lang>/` and `docs/conventions/common/`, plus
     `docs/conventions/<lang>.local.md` overrides (local wins; where any of
     them conflicts with the repo's
"""

# --- E4: dev-execute step 6, the A3 dispatch (3 wrappers) -------------------
E4_OLD = """     `docs/conventions/<lang>.md` plus its `.local.md` override. It
"""
E4_NEW = """     `docs/conventions/<lang>.md`, the five pack files it links, and its
     `.local.md` override. It
"""

# --- E5: the compressed command wrapper (1 file, 2 spots) -------------------
E5A_OLD = """`docs/conventions/<lang>.md` plus `docs/conventions/<lang>.local.md`
overrides (local wins; where either conflicts with the repo's existing
"""
E5A_NEW = """`docs/conventions/<lang>.md`, the five pack files it links under
`docs/conventions/<lang>/` and `docs/conventions/common/`, plus
`docs/conventions/<lang>.local.md` overrides (local wins; where any of them
conflicts with the repo's existing
"""
E5B_OLD = """constraints copied verbatim from the plan, and `docs/conventions/<lang>.md`
plus its `.local.md` override; it returns **two verdicts**, spec compliance
"""
E5B_NEW = """constraints copied verbatim from the plan, and `docs/conventions/<lang>.md`,
the five pack files it links, plus its `.local.md` override; it returns
**two verdicts**, spec compliance
"""

FORMS = ("claude-skill-{s}.md", "claude-command-{s}.md",
         "copilot-{s}.prompt.md", "cursor-{s}.md")
CONTRACT_SKILLS = ("dev-design", "dev-plan", "dev-execute", "dev-handover")

jobs = []
jobs += [(INIT / f.format(s=s), E1_OLD, E1_NEW)
         for s in CONTRACT_SKILLS for f in FORMS]
jobs += [(INIT / f.format(s="dev-execute"), E2_OLD, E2_NEW) for f in FORMS]
jobs += [(INIT / f.format(s="dev-execute"), E3_OLD, E3_NEW)
         for f in FORMS if "command" not in f]
jobs += [(INIT / f.format(s="dev-execute"), E4_OLD, E4_NEW)
         for f in FORMS if "command" not in f]
jobs += [(INIT / "claude-command-dev-execute.md", E5A_OLD, E5A_NEW),
         (INIT / "claude-command-dev-execute.md", E5B_OLD, E5B_NEW)]

for path, old, new in jobs:
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"{path.name}: {old.splitlines()[0][:50]!r} x{text.count(old)}"
    path.write_text(text.replace(old, new), encoding="utf-8", newline="\n")
print(f"patched {len(jobs)} sites across {len({p for p, _, _ in jobs})} files")
PY
```
Expected output: `patched 28 sites across 16 files` — 16 (E1: four phase
skills × four wrapper forms) + 4 (E2) + 3 (E3) + 3 (E4) + 2 (E5). Verified as
a dry run against `d4c1606`: every one of the 28 `old` strings occurs exactly
once in its file.

If any assertion fires, the wrapper text has drifted from what this plan read
at `d4c1606` — stop, print the offending file, and reconcile before
continuing. Do not loosen the `count(old) == 1` guard.

**Not edited:** the dev-plan wrappers' "*Linting* section of
`docs/conventions/<lang>.md`" sentences. That section stays in the entry
file, so pointing it at the pack would be a false pointer, and
`test_dev_plan_refuses_a_draft_design_and_writes_the_cmd_headers` pins the
phrase as it is. See §9, resolved ambiguity A2.

### 8.4 Regenerate the two canon strings in `tests/test_templates.py`

`REVIEW_BLOCK_TEXT["REVIEW-CONTRACT"]` and `REVIEW_BLOCK_TEXT["A4"]` are
literal copies of the blocks just edited. They are extracted by `repr()` from
a landed wrapper, never hand-retyped — same discipline the dict's own comment
states. Print the new values:

```
python - <<'PY'
from pathlib import Path
INIT = Path("src/strata_kb/templates/init")
BOUNDS = {
    "REVIEW-CONTRACT": ("## Review dispatch contract (every review in this flow)\n",
                        "  `Review: ✅ r<n> (fallback, Dev-approved)`.\n"),
    "A4": ("## A4 — narrow branch review (after the last task)\n",
           "`/dev-handover <ticket-id>`.\n"),
}
SRC = {"REVIEW-CONTRACT": "claude-skill-dev-design.md",
       "A4": "claude-skill-dev-execute.md"}
for block, (first, last) in BOUNDS.items():
    text = (INIT / SRC[block]).read_text(encoding="utf-8")
    start = text.index(first)
    print(f'    "{block}": {text[start:text.index(last, start) + len(last)]!r},')
PY
```

Paste each printed line over the matching entry in `REVIEW_BLOCK_TEXT`
(lines 2094-2099 today), replacing the whole value. Change nothing else in
that dict.

Run the two byte-identity tests on their own to confirm:
```
uv run pytest tests/test_templates.py -q -k "byte_identical or review_contract"
```
Expected: all selected tests pass (`test_dev_wrappers_carry_byte_identical_shared_blocks`,
`test_review_contract_is_byte_identical_across_the_four_phase_skills`,
`test_a_block_is_byte_identical_across_its_four_wrapper_forms[A1..A5]`,
`test_dev_code_seed_wrappers_are_byte_identical_from_steps_onward`,
`test_sa_*`).

### 8.5 Flip the tests to strict — `tests/test_templates.py`

**(a)** In `test_conventions_entry_file_links_its_pack`, delete the lenient
branch and its docstring paragraph.

Old:
```python
    text = _read_init_template(f"conventions-{lang}.md")
    if CONVENTIONS_PACK_MARKER not in text:
        for heading in CONVENTIONS_UNIVERSAL_MOVED:
            assert heading in text, f"{lang}: un-reshaped entry file lost {heading!r}"
        return
    for part in CONVENTION_PARTS:
```
New:
```python
    text = _read_init_template(f"conventions-{lang}.md")
    assert CONVENTIONS_PACK_MARKER in text, f"{lang}: entry file has no pack table"
    for part in CONVENTION_PARTS:
```

Also rewrite the docstring to:
```python
    """Every entry file is an index: it links its five language pack files
    and the five shared ones, and none of the moved headings survives in
    it. Naming / Module structure / Error handling / Logging now live in
    `<lang>/coding-style.md`, Testing in `<lang>/testing.md`."""
```

Then delete the now-unused `CONVENTIONS_UNIVERSAL_MOVED` tuple and its
comment.

**(b)** In `test_language_pack_templates_exist_and_extend_their_common_file`,
delete the skip.

Old:
```python
    """Lenient during the per-language rollout: a language with none of its
    five pack templates yet is skipped by name. Task 12 deletes the skip."""
    base = resources.files("strata_kb").joinpath("templates/init")
    names = {part: f"conventions-{lang}-{part}.md" for part in CONVENTION_PARTS}
    if not any(base.joinpath(n).is_file() for n in names.values()):
        pytest.skip(f"{lang}: conventions pack templates not written yet")
    for part, name in names.items():
```
New:
```python
    """Every language in LANG_IDS has all five pack templates, each opening
    with the extends line that names its common counterpart."""
    base = resources.files("strata_kb").joinpath("templates/init")
    names = {part: f"conventions-{lang}-{part}.md" for part in CONVENTION_PARTS}
    for part, name in names.items():
```

### 8.6 Extend the scaffold test — `tests/test_conventions.py`

Old (the test added in §6.9):
```python
def test_scaffold_writes_the_shared_common_pack_once(tmp_path: Path):
    # Task 12 extends this with the per-language half
    # (docs/conventions/<lang>/<part>.md), which lands with the loop that
    # writes it.
    _touch(tmp_path, "pyproject.toml")
    report = _scaffold(tmp_path)
    for part in CONVENTION_PARTS:
        dest = tmp_path / "docs" / "conventions" / "common" / f"{part}.md"
        assert dest.is_file(), part
        assert f"docs/conventions/common/{part}.md" in report.created
        assert "~/.claude" not in dest.read_text(encoding="utf-8"), part
```

New:
```python
def test_scaffold_writes_the_shared_common_pack_once(tmp_path: Path):
    _touch(tmp_path, "pyproject.toml")
    report = _scaffold(tmp_path)
    for part in CONVENTION_PARTS:
        dest = tmp_path / "docs" / "conventions" / "common" / f"{part}.md"
        assert dest.is_file(), part
        assert f"docs/conventions/common/{part}.md" in report.created
        assert "~/.claude" not in dest.read_text(encoding="utf-8"), part


def test_scaffold_writes_the_language_pack_and_the_entry_file_links_it(
    tmp_path: Path,
):
    report = InitReport()
    assert scaffold_conventions(tmp_path, report, forced=["python"]) == ["python"]
    entry = (tmp_path / "docs" / "conventions" / "python.md").read_text(
        encoding="utf-8"
    )
    assert "## Conventions pack" in entry
    for part in CONVENTION_PARTS:
        dest = tmp_path / "docs" / "conventions" / "python" / f"{part}.md"
        assert dest.is_file(), part
        assert f"docs/conventions/python/{part}.md" in report.created
        text = dest.read_text(encoding="utf-8")
        assert text.startswith(
            f"> This file extends [common/{part}.md](../common/{part}.md) with "
        ), part
        assert f"({part}.md)" in entry, part
    # the entry file handed its movable sections to the pack
    for heading in ("## Naming", "## Module structure", "## Error handling",
                    "## Logging", "## Testing"):
        assert heading not in entry, heading
    assert "## Citation comments" in entry and "## Linting (preset)" in entry
```

### 8.7 CHANGELOG

Append one bullet at the end of the existing `## Unreleased` list (after the
`kb ticket lint` bullet, before the blank line and `## 1.1.0 — 2026-09-21`):

```markdown
- `kb init --kind dev` scaffolds a **conventions pack** alongside each `docs/conventions/<lang>.md`: five language-agnostic files under `docs/conventions/common/` (coding style, patterns, security, testing, hooks) and five language-specific ones under `docs/conventions/<lang>/` that extend them. `docs/conventions/<lang>.md` becomes the entry file — it keeps **Citation comments** and **Linting (preset)** and links the ten pack files; its Naming / Module structure / Error handling / Logging sections now live in `<lang>/coding-style.md` and its Testing section in `<lang>/testing.md`. `docs/conventions/<lang>.local.md` still overrides everything and is still never rewritten. The dev wrappers, the Cursor `.mdc` and Copilot `.instructions.md` pointers, and the `CLAUDE.md` block all name the pack. Re-run `kb init --kind dev` to pick it up.
```

### 8.8 Verify and commit

```
uv run pytest tests/test_conventions.py tests/test_init.py tests/test_templates.py -q
```
Expected: `469 passed`, **zero skipped** (one more than T11's total: the new
scaffold test in §8.6).

```
uv run pytest -q
```
Expected: the whole suite green, zero failures, zero errors.

Smoke, the full pack this time:
```
mkdir -p /tmp/kbsmoke-t12 && cd /tmp/kbsmoke-t12 && git init -q .
uv --project /Users/vuonglq01685/Documents/Projects/AERO-KB run kb init . --kind dev --lang python
find docs/conventions -type f | sort
```
Expected, exactly:
```
docs/conventions/common/coding-style.md
docs/conventions/common/hooks.md
docs/conventions/common/patterns.md
docs/conventions/common/security.md
docs/conventions/common/testing.md
docs/conventions/python.local.md
docs/conventions/python.md
docs/conventions/python/coding-style.md
docs/conventions/python/hooks.md
docs/conventions/python/patterns.md
docs/conventions/python/security.md
docs/conventions/python/testing.md
```
Then:
```
grep -rn "ECC\|everything-claude\|~/.claude\|See skill:" docs/conventions/ ; echo "exit=$?"
rm -rf /tmp/kbsmoke-t12
```
Expected: no output, `exit=1`.

GitNexus: `detect_changes({scope: "compare", base_ref: "main"})`. Expect the
changed symbols to be `scaffold_conventions` plus the test functions — nothing
in `initcmd.py`, `cli.py`, `mdutils.py`.

```
cd /Users/vuonglq01685/Documents/Projects/AERO-KB
git add -A src/strata_kb tests CHANGELOG.md
git commit -m "feat(conventions): scaffold the per-language pack; wrappers and docs name it

scaffold_conventions now writes docs/conventions/<lang>/<part>.md for every
scaffolded language, next to the shared common/ half from the first commit
of this series. No guard on the template lookup: a language id without its
five pack files must raise FileNotFoundError in the suite, which is why
this loop lands after all ten template sets rather than with the common one.

The dev wrappers' three conventions sentences — the review dispatch
contract, the A4 branch-review dispatch and dev-execute's self-review
checkpoint — now name the pack as well as the entry file. Applied by script
across all 28 sites so the byte-identical REVIEW-CONTRACT and A4 blocks stay
byte-identical; the two canon strings in tests/test_templates.py were
re-extracted by repr() from a landed wrapper, not retyped. The dev-plan
wrappers' *Linting* sentences are untouched: that section stays in the entry
file.

The pack tests are strict from here: every language has five templates, and
every entry file is an index with no moved headings left in it.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01NtdRAkmyTshnfR99NbY5Li"
```

---

## 9. Self-review

### Decisions → tasks

| Decision | Where it is honoured |
|---|---|
| **1** — today's shape (one `<lang>.md` per language, `.local.md` stub, `.mdc` / `.instructions.md` pointers, CLAUDE block, `LANG_IDS`) | §1 (before/after), §5.1 (the entry file's opening block is byte-identical to today's), §6.5/§6.6 (pointers keep their existing needles), §6.4 (CLAUDE block keeps `repo wins locally` on one source line). Nothing in today's contract is removed. |
| **2** — new layout, `common/` + `<lang>/`, five parts, the extends line, the entry file keeps Citation comments + Linting | §1, §2.4, §5.1, §5.2. The `Linting` grep was run: only the four dev-plan wrappers and `tests/test_templates.py:1975` name it, and all of them keep pointing at the entry file. |
| **3** — content from `~/.claude/rules/ecc/`, made ours | §2.2 (source map, including `e2e-playwright` having none), §2.3 (the 14-rule table, built from the grep the decision specified), §2.5 (merge/conflict rules). The banned strings are asserted by `test_language_pack_templates_exist_and_extend_their_common_file` and `test_common_pack_templates_exist_and_carry_no_extends_line`, and re-checked on real scaffold output in §8.8. |
| **4** — plan format: one worked example, recipes for the rest, exact text for everything not ECC-derived | §4.1 (`python/coding-style.md` in full), §4.2 (the M1 merge demonstrated on `go`), §7.2–§7.11 (54 recipe rows), §5.1 (`conventions-python.md` in full) + §5.2 (the per-language rule), §6.2–§6.4 + §8.2 (scaffold code), §6.5/§6.6 (pointers), §6.8/§6.9/§8.5/§8.6 (tests), §7.11 (`e2e-playwright`'s `security.md` and `hooks.md` in full — they have no source), §8.3 (wrapper old/new), §8.7 (CHANGELOG). No `TBD`, no "similar to", no "add appropriate". |
| **5** — scaffold mechanics, flat template names, pointers and CLAUDE block mention the directory, existing tests are the pin | §6.2–§6.6, §8.2. Every existing assertion in `tests/test_conventions.py` and `tests/test_init.py` was read and checked: no `InitReport` count assertion exists (the only `report.created == []` lines are idempotence checks, unaffected), and `test_expected_files_unchanged_by_conventions_pack` still holds because conventions stay a post-step. The only existing test constant that had to change is `CONVENTIONS_SECTION_HEADINGS` (§6.8b) — see deviation D2. |
| **6** — dev wrappers name the pack; the shared-block caution | §8.3. The grep found the sentence in two byte-identical families: `REVIEW-CONTRACT` (16 wrappers, canon at `tests/test_templates.py:2094`) and `A4` (4 wrappers, canon at 2098) — **not** in the three `SHARED-*` blocks, whose canon text contains no `docs/conventions` at all. The edit is scripted across all copies with a `count(old) == 1` guard per file, and the two canon strings are regenerated by `repr()` (§8.4), never retyped. |
| **7** — parametrized lenient test, flipped strict last; per-language tasks touch no test file; the scaffold test | §6.8c (two `@pytest.mark.parametrize("lang", LANG_IDS)` tests, lenient), §8.5 (flip), §6.9 + §8.6 (scaffold test, common half in T1 and language half in T12). §3 and §7.1 state that T2–T11 edit no test and no Python file. |
| **8** — global constraints | §2.1, verbatim: no version bump, one appended `## Unreleased` bullet, no new dependency, `mdutils.py` frozen, English templates, the three-file green gate after every task, the full suite before the last commit, the GitNexus `impact`/`detect_changes` calls with the MCP-down fallback. |

### Deviations from the brief, and why

- **D1 — the per-language `docs/conventions/<lang>/` loop moved from T1 to
  T12.** Decision 5 puts all scaffold mechanics in T1. If T1 landed that loop,
  `_template_text("conventions-dotnet-coding-style.md")` would raise
  `FileNotFoundError` for all ten languages until T11 finished, so every T1–T11
  commit would ship a broken `kb init --kind dev` and a red
  `test_scaffold_produces_four_files_for_every_manifest_lang`. The alternatives
  were a temporary existence guard (throwaway code, and it contradicts that
  test's stated intent that a missing template resource raise in the suite) or
  a registry tuple each language task appends to (also throwaway). Moving four
  lines to T12 keeps every commit green, keeps fail-fast, and keeps T2–T11
  parallel-safe. T1 still lands everything else: `CONVENTION_PARTS`, the
  `common/` loop, the pointers, the CLAUDE block and both tests.
- **D2 — `CONVENTIONS_SECTION_HEADINGS` is narrowed in T1, not T12.** It
  requires `## Naming`, `## Module structure`, `## Error handling`,
  `## Logging` and `## Testing` in every entry file, which is precisely what
  T2–T11 remove. Since T2–T11 may not edit tests, the narrowing has to land in
  T1. The lost coverage is replaced immediately, and more strictly, by
  `test_conventions_entry_file_links_its_pack`.

### Ambiguities resolved

- **A1 — which wrapper sentences gain the pack.** Only the three that tell a
  reader or a reviewer to *read the conventions as the standard to follow*:
  the `REVIEW-CONTRACT` criteria bullet, the `A4` branch-review dispatch, and
  `dev-execute`'s self-review checkpoint plus its A3 dispatch. 28 sites, 16
  files.
- **A2 — the dev-plan *Linting* sentences are not edited.** They point at the
  `## Linting (preset)` section, which stays in the entry file; adding "and
  the five files under `docs/conventions/<lang>/`" there would send a reader
  looking for a lint preset that is not in any pack file, and
  `tests/test_templates.py:1975` pins the phrase as it stands.
- **A3 — `QUICKSTART-dev.md`, `docs/src/guide-dev.en.md`,
  `docs/src/guide-dev.vi.md` and `README.md` are not edited.**
  `grep -rn -i "convention"` across all four returns nothing: they have never
  mentioned `docs/conventions/` at all. Decision 6 describes extending an
  existing sentence; there is no sentence to extend, and writing new
  conventions documentation into four surfaces (two of them a translated
  pair) is a different change. The CHANGELOG bullet in §8.7 is where a user
  learns about the pack. Flagging this explicitly: if you want those four
  surfaces to describe the pack, it is a separate task, and the Vietnamese
  guide needs a translated paragraph, not an English one.
- **A4 — the extends line is line 1, not line 3.** Decision 2 says each pack
  file "starts with" the extends line. The source files put a title first;
  ours put the `>` line first so `startswith` is a real assertion. The title
  follows on line 3.
- **A5 — the entry file's `## Testing` heading is renamed to
  `## Ground rules` inside `<lang>/testing.md`.** A `## Testing` section
  inside `testing.md` reads as a stutter, and it would collide with the
  source's own section names. §2.7 states the rule; the strict entry-file test
  asserts `## Testing` is gone from the entry file, which the rename satisfies.
- **A6 — heading collisions between a source section and a moved entry
  section.** Rule M1 (§2.5): one heading survives, entry-file bullets lead,
  source bullets and code blocks follow, restatements dropped. Demonstrated
  in full on `go`'s `## Error handling` in §4.2. This fires for `go`, `ts`,
  `java`, `dotnet`, `php`, `rust`, `swift`, `dart`.
- **A7 — tool recommendations that contradict the Linting preset.** Rule C1
  (§2.5): the preset wins, and the pack file defers to it in one bullet
  rather than naming a competing tool. Fires in all ten `coding-style.md`
  files.
- **A8 — `## Standards` (C1) is the first section of every language
  `coding-style.md`, except `e2e-playwright`.** `e2e-playwright`'s own
  `hooks.md` already names the preset, and §7.11 never asked for the C1
  bullet there. `dart`'s `## Formatting` section was renamed to
  `## Standards` and moved first; `ts` gained the section in the final fix
  wave, after review found it missing.
