# Resolve and summarize perf Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-10-resolve-summarize-perf-design.md`

**Constraints:**
- Release **1.14.0**.
- Test command: `uv run pytest -q -p tikstub`.
- Every new test must fail on `main`.

## Deviations from the spec

- **Directories.** `BatchReader` returns `None` for a directory, while
  `read_at` returned `git show`'s tree listing. No caller reads a
  directory. Recorded in the docstring and pinned by a test.

---

- [x] **Task 1 (F8).**
  - `gitio.BatchReader`.
  - `resolve_refs` uses one reader.
  - `tests/test_gitio_batch.py`.
  - 5 refs: 22 git processes / 199 ms → 3 / 113 ms.
- [x] **Task 2 (F12, writes).**
  - `FLUSH_EVERY` in `summarize_kb`.
  - Parallel `_fill_doc_summaries`.
  - `tests/test_summarize_flush.py`.
- [x] **Task 3 (F12, budget).**
  - `llm.thinking_budget`.
  - `tests/test_llm_thinking.py`.
- [x] **Task 4.** CHANGELOG, version bump, full suite, ruff, PR.
