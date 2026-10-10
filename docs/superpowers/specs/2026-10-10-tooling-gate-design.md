# Tooling gate: ruff B/I/UP/SIM, ruff format, pyright on src

**Status:** approved design (decisions taken 2026-10-10)
**Source:** §4.1 and §8 đợt 3 item 10 of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`. This is
batch 3a, the first of wave 3.
**Wave 3 order** (chosen 2026-10-10): tooling first, so every later
refactor lands already formatted and type-checked.
- 3a: this batch.
- 3b: item 8, part 1 (the `KbError` family, `_cli_guard`, `publish.plan()`,
  `doctor.run()`).
- 3c: item 8, part 2 (`codeingest/types.py`, `serving/`, `doctor/checks/`).
- 3d: item 9 (one template body per skill).
- 3e: item 11, plus item 10's docstrings and provenance comments.

## Goal

Measured on `main` at 1.14.0:

| Check | Today | Problem |
|---|---|---|
| `ruff check --select B,I,UP,SIM` | 239 findings | Rules are off. B904 ×61 drops the exception chain, against `errors.py`'s "one line naming the cause". |
| `ruff format --check` | 231 of 261 files would change | No formatter, so style is held by review. |
| pyright, basic mode, `src/` | 52 errors | No type checker at all; annotations are 88.6% but never checked. |

After this batch, T0 runs all three and all three are clean.

## Design

### 1. ruff lint

- `select` adds `B`, `I`, `UP`, `SIM`. `ignore = ["B008"]`: typer
  options are function calls in defaults by design (53 sites).
- The safe fixes (`ruff check --fix`, no unsafe fixes) are applied as-is.
- **B904.**
  - `raise typer.Exit(...)` inside `except` becomes `from None`. The CLI
    has already printed the one-line cause; typer never shows a chain, so
    the chain was noise.
  - A library `raise` inside `except` becomes `from exc`, so the cause
    survives into logs and tracebacks.
- **B905.** Each `zip()` gets an explicit `strict=`, decided per site:
  - `strict=True` where unequal lengths would be a bug.
  - `strict=False` where truncation is the intent, with a comment saying
    why.
- **UP042.** `class X(str, Enum)` becomes `StrEnum`. A test pins that the
  typer option still parses and prints the same values.
- SIM105, SIM102, SIM115, SIM117, B017 and B007 are fixed by hand.

### 2. ruff format

- Line length 88, ruff's default, so nothing is configured.
- `ruff format .` runs once, on the whole repo, as its own commit with no
  other change.
- The repo squash-merges, so that commit's SHA will not survive. 3b's
  first commit adds `.git-blame-ignore-revs` naming this PR's squash SHA.

### 3. pyright, basic mode, `src/` only

- `[tool.pyright]`: `typeCheckingMode = "basic"`, `pythonVersion =
  "3.11"`, `include = ["src"]`.
- Pinned exactly: `pyright==1.1.414` in the `dev` extra, like ruff's
  upper bound, so a new release cannot turn `main` red.
- **Fixes.** The 41 errors in code are fixed by narrowing or a small
  restructure (an early `return`, a local variable, a `TypedDict` or
  `cast` at an untyped JSON boundary).
- **Ignores.** The 11 `reportMissingImports` are lazy imports of optional
  extras (docling, fastembed, boto3, rapidocr, pypdfium2) that T0 does not
  install. Each gets `# pyright: ignore[reportMissingImports]`.
  - There is no bare `# type: ignore`.
  - Every ignore names its rule.
- Any error that turns out to be a real bug is fixed with a test and a
  CHANGELOG line.

### 4. Gate

- `_gate.yml` T0 runs three steps:
  1. `ruff check .`
  2. `ruff format --check .`
  3. `pyright`, after `pip install -e .` and the pinned pyright, so
     imports resolve.
- `scripts/gate.sh` T0 runs the same three.
- README §19 lists T0 as those three.
- The pyproject comment that said B/I/UP/SIM were "deliberately NOT here
  yet" is replaced.

## Out of scope

- **pyright on `tests/`.** It has 157 errors, mostly Optional member
  access after an assert. It needs its own batch.
- **Item 10's docstrings and comments.** The 37 module docstrings, and
  moving the 402 provenance comments to CHANGELOG/ADR, are batch 3e.
- **Stricter modes.** Standard or strict pyright and `reportUnknown*`
  stay off.

## Testing

- The full suite passes (`uv run pytest -q -p tikstub`) after every
  commit that changes code. The format commit changes no behaviour, and
  the suite proves it.
- `StrEnum`: a CLI test passes each `RepoKind` and `AssetsMode` value
  through typer and checks the value it receives and prints.
- Every `zip(strict=True)` site that a test reaches stays green. A site
  that no test reaches gets one.

## Delivery

One PR, release **1.14.1**. There is no user-facing feature. Lint, format
and type fixes only, plus any real bug pyright finds, each named in the
CHANGELOG.
