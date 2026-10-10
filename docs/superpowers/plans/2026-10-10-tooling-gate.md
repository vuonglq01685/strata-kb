# Tooling gate Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-10-tooling-gate-design.md`

**Constraints:**
- Release **1.14.1**: bump `pyproject.toml` and the `strata-kb` entry in
  `uv.lock`, and add a CHANGELOG heading.
- Test command: `uv run pytest -q -p tikstub`. `tikstub` is a scratchpad
  plugin that stands in for `cl100k_base`, because the egress proxy blocks
  its download. See review §4.3.
- The suite stays green after every commit that touches code.
- The format commit carries nothing but `ruff format .`.

## Deviations from the spec

Recorded during implementation.

---

- [ ] **Task 1. ruff config and safe autofixes.**
  - `select += B, I, UP, SIM`, `ignore = ["B008"]`.
  - `ruff check --fix .`
- [ ] **Task 2. Hand fixes.**
  - B904: `from None` for `typer.Exit`, `from exc` in the library.
  - B905: `strict=` per site.
  - UP042: `StrEnum`, with a CLI test.
  - SIM105/102/115/117, B017, B007.
- [ ] **Task 3. pyright basic on `src/`.**
  - `[tool.pyright]`, and `pyright==1.1.414` in the `dev` extra.
  - Fix the 41 errors in code.
  - Name the rule on the 11 optional-extra import ignores.
- [ ] **Task 4. `ruff format .`** as its own commit.
- [ ] **Task 5. Gate and docs.**
  - `_gate.yml` T0 and `scripts/gate.sh` run ruff check, ruff format and
    pyright.
  - README §19.
  - CHANGELOG 1.14.1 and the version bump.
  - Full suite, push.
