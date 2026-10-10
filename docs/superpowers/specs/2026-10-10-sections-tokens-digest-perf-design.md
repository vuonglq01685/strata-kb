# Split each file once, count tokens offline, hash only what a publish wrote

**Status:** approved design (decisions taken 2026-10-10)
**Source:** §6.2 F2, F4/F5 and F6, §8 đợt 2 items 5 and 6 (part) of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`. This is
batch 2b of wave 2. 2a (#83) did F1 + F3. Batch 2c will cover F7
(sparse intake worktree), F8 (resolve git) and F12 (summarize).
**Approach:** as chosen on 2026-10-10:
- `section_map` splits a file once, and `slice_section` reads from it.
- tiktoken is imported lazily and cached in `~/.strata-kb/tiktoken`.
  When it cannot load, counts are estimated and one warning is printed.
- A publish re-hashes only the repo it wrote.

## Goal

| Finding | Before | Cause |
|---|---|---|
| F2 | Cold index sync of 2,000 sections at 500 per file: 4.2 s on the bench (review: 20 s). `kb build` on 1,000 sections in 2 files: 9.2 s. | `slice_section` splits the whole file again for every section. `searchdb._section_parts` also re-reads the file for every section. |
| F4/F5 | `ProxyError` traceback on the first token count without Internet. 648 tests fail offline. | `import tiktoken` at module import. The BPE is cached in the system temp dir, which reboots and containers empty. |
| F6 | Every publish runs `entry_content_digest` (sha256 of every file) for **every** entry of the hub: 4.8 s at 100 docs / 27 MB. | `write_federation_index` rebuilds every digest. |

## Design

### 1. `mdutils.section_map` (F2)

- **`section_map(md) -> dict[str, tuple[str, ...]]`.** One `splitlines` and
  one pass over the `## ` boundary lines. It maps each heading id to its
  slices in file order. A slice runs from its heading to the next line
  starting with `## `, stripped, which are exactly the old boundaries.
  It is memoised with `functools.lru_cache(maxsize=16)` on the text itself.
  The same `str` object hits without re-hashing, and callers that already
  cache the text per file (`build`, `summarize`, `review`) hit every time.
- **`slice_section(md, id, occurrence)`** becomes a lookup into that map.
  It returns the same text for every input, including a negative or
  out-of-range occurrence, which returns `None`.
- **`searchdb._section_parts`** takes the per-document `texts` dict that
  `_sync_repo` creates, so each `.md` and `.raw.md` is read once per
  document.

### 2. Token counting offline (F4/F5)

- `mdutils` no longer imports tiktoken at module level. `_load_encoder()`
  imports it on the first count.
- When neither `TIKTOKEN_CACHE_DIR` nor `DATA_GYM_CACHE_DIR` is set, it sets
  `TIKTOKEN_CACHE_DIR=~/.strata-kb/tiktoken`. On failure it retries once
  from tiktoken's own default (temp dir), so a machine that cached the file
  there before this release still works offline.
- If both attempts fail, `count_tokens` returns `(len + 3) // 4` and logs
  **one** warning (stderr). The warning names the cause, the cache dir and
  `TIKTOKEN_CACHE_DIR`. It never raises.
- Counts feed `~Ntk`, budgets, `kb stats` and the ingest token report.
  They never decide content, so an estimate degrades display, not
  correctness.
- Vendoring the BPE into the wheel is out of scope. The file cannot be
  fetched from this build environment, and the stable cache dir plus the
  fallback cover the failure.

### 3. Incremental federation digest (F6)

- **Signatures.** `build_federation_index(fed, changed=None)` and
  `write_federation_index(fed, changed=None)`.
- **Behaviour with `changed`.** Every entry whose path-id is not in
  `changed` (or nested under one, for multi-tier `mid/<x>`) keeps the
  `content_sha256` recorded in the current `federation/index.yaml`. Entries
  missing from it, or every entry when it is unreadable, are hashed.
- **Callers.** The three publish paths and intake pass `changed={rid}`.
  `kb reindex` and `kb doctor` pass nothing, so they recompute everything.
- **Integrity.** This is the stronger rule. The recorded digest stays
  what that repo published, so an in-place edit to another entry stays
  visible to `kb doctor`. Before, an unrelated publish re-recorded it.
- **Hub-to-hub doc count.** `publish.py`'s doc count no longer builds the
  whole index (digests included) just to count documents.

## Testing

- **Slicing.**
  - `tests/test_section_map.py` keeps the old implementation as a
    reference. It runs the edge cases (repeated ids, a `## ` that is not a
    heading, `###`, CRLF, a trailing newline, occurrences −1 to 2) and 200
    seeded random documents, all equal to the reference.
  - Slicing all 500 sections of a 1 MB file takes under 0.25 s.
  - `_section_parts` reads each file once per document.
- **Tokens.** `tests/test_token_fallback.py`:
  - an unloadable encoding gives an estimate and exactly one warning;
  - the stable dir is tried first;
  - the old temp-dir cache is still used;
  - an operator's `TIKTOKEN_CACHE_DIR` wins;
  - `mdutils` has no top-level tiktoken import.
- **Digest.** `tests/test_federation_index_incremental.py`:
  - only the changed repo is hashed;
  - an in-place edit elsewhere is not re-recorded;
  - a full rebuild hashes all;
  - a new entry and an unreadable index are hashed;
  - nested scope.

## Delivery

One PR, release **1.13.0**.
