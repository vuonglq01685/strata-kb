# One git process per resolve, summarize that keeps what it paid for

**Status:** approved design (decisions taken 2026-10-10)
**Source:** §6.2 F8 and F12, §8 đợt 2 items 6 (F8) and 7 of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`. This is
batch 2c, the last of wave 2. 2a (#83) did F1 + F3, and 2b (#84) did F2,
F4/F5 and F6.
**Approach:** as chosen on 2026-10-10:
- `gitio.BatchReader`, one `git cat-file --batch` per resolve.
- summarize writes every 25 sections and runs the doc summaries in
  parallel.
- `effort=high` keeps a thinking budget, now scaled to the prompt.
- **F7 is deferred** (see Out of scope).

## Goal

| Finding | Before | Cause |
|---|---|---|
| F8 | `kb resolve` with 5 refs: 22 git processes, 199 ms (2k bench hub). | `gitio.read_at` runs `rev_exists` again, though `resolve_refs` already checked it, then `git show`. That is twice per ref. |
| F12 | A crash or Ctrl-C in an hours-long `kb summarize` loses every call already paid for. | Results are written only after the last future finishes. |
| F12 | Doc (L0) summaries run one after another after the pool. | `_fill_doc_summaries` loops sequentially. |
| F12 | `MAX_THINKING_TOKENS=31999` for every section at the default `effort=high`, a two-line section included. | The budget is a constant. |

## Design

### 1. `gitio.BatchReader` (F8)

- **One process.** It is a context manager around one lazily started
  `git cat-file --batch` process. `read_at(rev, path)` keeps
  `gitio.read_at`'s contract for files:
  - the text, with newlines normalised the way text-mode `git show` did
    (`\r\n` and `\r` become `\n`);
  - `None` when the path is absent;
  - `GitError` when the rev does not exist.
- **Memoisation.** Results are memoised per `(rev, path)`, and
  `rev_exists` per rev. `mark_rev_exists` lets a caller that already
  checked skip the repeat.
- **Directories.** A directory reads as `None`. `git show` printed a tree
  listing, and no caller reads one.
- **Callers.** `resolve.resolve_refs` opens one reader for all refs.
  `_resolve_one` takes it (optional, so direct callers keep working).

### 2. Summarize writes as it goes (F12)

- `summarize_kb` calls `_apply_results` every `FLUSH_EVERY = 25` completed
  sections, and once at the end. It is still on the main thread, so
  "workers only call the LLM" holds.
- Each flush re-reads the manifest. `_pending_marker_index` then counts
  only the markers still in the file, and repeated section ids stay
  correct across flushes (tested with an id that repeats every fourth
  section).
- `_fill_doc_summaries` collects the eligible docs, runs their LLM calls in
  a pool of `max_workers`, and writes `index.yaml` once.

### 3. Thinking budget (F12)

- `llm.thinking_budget(prompt) = clamp(len(prompt) // 2, 4000, 31999)`.
  That is roughly twice the prompt's tokens.
- `Runner.run` sends it as `MAX_THINKING_TOKENS` for claude at
  `effort=high`, as before. Medium and low still send none, and nor does
  copilot.
- The default effort stays `high`. Short sections, the common case, now
  get a smaller budget.

## Out of scope

- **F7, the sparse intake worktree.** Deferred. The intake rebuilds
  `federation/index.yaml` in its worktree, and that rebuild needs every
  entry's `_meta.yaml`, `index.yaml` and empty-revision manifests. When
  the recorded index is unreadable, it also hashes every entry. A
  `federation/<rid>`-only sparse checkout would silently drop entries or
  record wrong digests. It needs its own pattern design and a full-tree
  fallback. Today it costs 80–260 ms per publish at 1k files.
- **F9** (L2/L3 read per hit) and **F10/F11** (CJK trigram, asset map).

## Testing

- **`tests/test_gitio_batch.py`.**
  - It matches `read_at` for files, CRLF and missing paths at two revs.
  - A directory reads as `None`, and an unknown rev raises.
  - It runs one cat-file process for every read.
  - `resolve_refs` on six refs uses one cat-file and at most three git
    processes.
- **`tests/test_llm_thinking.py`.**
  - The budget scales and clamps.
  - Claude at high effort sends the scaled value.
  - Medium, and copilot, send none.
- **`tests/test_summarize_flush.py`.**
  - Batched flushes write byte-identical L2 and manifests to one final
    write, with repeating ids.
  - A crash after 12 calls keeps the 10 sections already flushed.

## Delivery

One PR, release **1.14.0**.
