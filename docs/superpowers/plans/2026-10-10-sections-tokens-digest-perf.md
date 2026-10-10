# Split once, count offline, hash incrementally Implementation Plan

**Spec:** `docs/superpowers/specs/2026-10-10-sections-tokens-digest-perf-design.md`

**Constraints:**
- Release **1.13.0**.
- Test command: `uv run pytest -q -p tikstub`.
- Every new test file must parse on Python 3.11 (no backslash inside
  f-string expressions).

## Deviations from the spec

None.

---

- [x] **Task 1 (F2).**
  - `mdutils.section_map`, with `slice_section` delegating to it.
  - The `searchdb._section_parts` per-document text cache.
  - `tests/test_section_map.py`.
- [x] **Task 2 (F4/F5).**
  - The lazy `_load_encoder`, the stable cache dir with the temp-dir retry,
    and the estimate with one warning.
  - `tests/test_token_fallback.py`.
- [x] **Task 3 (F6).**
  - `changed=` on `build/write_federation_index`, passed by publish
    (three paths) and intake.
  - The doc count without hashing.
  - `tests/test_federation_index_incremental.py`.
- [x] **Task 4.**
  - Measure before and after:
    - cold sync at 500 sections per file: 4,200 → 330 ms;
    - index after a one-repo publish, 10k sections: 139 → 75 ms.
  - CHANGELOG, version bump, full suite, ruff, PR.
