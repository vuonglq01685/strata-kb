# Search / MCP / kb-context review fixes — a reachable tool surface, an index that tells the truth, no silent substitutions

**Status:** approved design, ready for an implementation plan
**Source:** reviewer C of the 2026-09-08 full framework review,
`docs/superpowers/reviews/2026-09-08-full-framework-review/C-search-mcp-context.md`
(findings F-C1–F-C17), and §5 đợt 1 items 8–9, đợt 2 item 10 and đợt 3
item 7 of `docs/superpowers/reviews/2026-09-08-full-framework-review.vi.md`.
**Predecessor:** `2026-09-09-summarize-build-review-fixes-design.md`
(reviewer B, merged as PR #47). That batch made the content pipeline keep
its C2 promise; this batch makes the retrieval and citation layer keep C6,
C8 and C9.
**Approach:** as approved on 2026-09-10 — warm the native import once at
server start and run sync MCP tools off the event loop; make the index
freshness key cover the bytes it indexes; stop treating client input errors
as index corruption; and close every path where an agent asks for one thing
and silently receives another.

## Goal

Reviewer C built a real two-child federation from the repo's own `.kb/`
and ran a 40-query retrieval battery, a 10-case resolve mutation battery,
20 adversarial MCP calls, and cold/warm concurrency probes. The verdict:
the contract is byte-perfect where it is written down, and unreachable or
untrue in several places where it matters.

- `kb_search` — the first tool every agent calls — **hangs forever over
  stdio** in any environment where `sqlite-vec` is importable, which is
  every `[embed]` install, every `[dev]` install and this repo's own
  `.venv`. `searchdb._load_vec()` imports `sqlite_vec` (and transitively
  numpy's native `_multiarray_umath`) at request time, on the asyncio
  event-loop thread, where the native import deadlocks on Windows
  (F-C1, HIGH; reproduced 4×, 120 s with no response, `faulthandler` stack
  stuck in `numpy/_core/multiarray.py` `create_module`).
- Five `kb query` processes against a hub with no `search.db` — the normal
  state after a fresh clone — give 3/5 failures on every trial, each with a
  raw rich traceback. A lost UNIQUE race is an `IntegrityError`, which
  `is_lock_error` does not recognise, so `query.py` calls it corruption and
  `delete_db()`s the shared index; on Windows the unlink then raises
  `PermissionError` at the user (F-C2, HIGH).
- A fix made directly in `federation/` on the hub — the place README §7.9
  calls "the single review gate" — is invisible to `kb query` forever,
  while `kb get` returns it. `_repo_fingerprint` hashes only `_meta.yaml`
  and `index.yaml`, and neither `kb reindex` nor `kb doctor` repairs it
  (F-C3, HIGH).
- `kb get --level L3` (or `verbatim`, or `raw`, or `l1`) returns the
  AI-condensed L2 with a byte-identical header and no warning. The MCP tool
  validates; the CLI does not (F-C4, HIGH).
- README §7.8 promises `kb_search` "flags when the top two are close in
  score". `_ambiguity_note` requires both hits to be `hybrid`, which cannot
  happen without an embedder — 0 fires in 14 queries on the shipped
  default, including the case where `aero:arinc-424 §5.129` and
  `beta:arinc-424 §5.129` are ranks 1 and 2 (F-C5, HIGH).
- A deleted section, a renumbered section and a deleted *document* all
  resolve as `stale`/exit 2 — the same signal as "someone reworded a
  sentence" — so CI cannot block on a citation whose target no longer
  exists, and the remediation hint it prints (`kb diff <doc>`) errors out
  (F-C6, MEDIUM).
- Recall is hard-capped at `K_LEG = 50` per leg with no signal to the
  caller, under a docstring that tells agents it "returns every relevant
  section found" — `record` matches 154 sections and returns 50 (F-C7).
- `tokenize()` is ASCII-only while the index is `unicode61` and holds
  non-ASCII tokens, so `đường băng sân bay` is shredded into `['ng', 'b',
  'ng', 's', 'n', 'bay']` and answers confidently with junk. C2 requires L2
  in the source language, so a Vietnamese KB would be indexed and
  unsearchable (F-C9).
- A client-supplied `tags` list of 40 000 entries produces `too many SQL
  variables`, an `OperationalError` that `is_lock_error` does not recognise
  — so a malformed tool call deletes the index every user of that hub
  shares (F-C10).

After this batch:

- `kb_search` answers over stdio and over HTTP in an environment with
  `sqlite-vec` installed, and a test in `tests/` proves it on every run
  without needing a built wheel;
- five concurrent cold builds all exit 0, and no client input — a bad tag
  list, a lost race — can delete the shared index or surface a traceback;
- an edit committed directly on the hub is visible to the next `kb query`,
  and `kb reindex --force` drops and rebuilds;
- every level, tag and ref an agent passes is either honoured exactly or
  refused with a message; nothing is silently substituted;
- the caller is told when results were truncated at the leg cap, when the
  top two are genuinely hard to separate, and when a query tokenised to
  nothing;
- a citation whose section or document no longer exists is `broken`/exit 1,
  distinguishable in CI from an amendment;
- a Vietnamese or CJK KB is searchable, and the README describes the output
  the code actually produces.

## Decisions taken during brainstorming (2026-09-10)

1. **Scope: reviewer C's own top-3 recommendations, plus the cheap
   contract and hygiene items.** In: F-C1, F-C2, F-C3, F-C4, F-C5, F-C6,
   F-C7, F-C9, F-C10, F-C13, F-C14, F-C17. F-C8 is documentation only.
   Out: F-C11 (measuring `SEMANTIC_MIN_SCORE` needs a real `fastembed`
   install and a measured distribution), F-C12 (retrieval quality on bare
   section numbers and natural-language questions — the absent semantic leg
   was supposed to cover it, so it waits on F-C11), F-C15 (section-granular
   tags need a `tags` field on `SectionEntry`, a manifest schema change and
   a re-ingest), F-C16 (unreachable on the bundled KB, 0/7 attempts).
   Rejected: the narrower "đợt 1 items 8–9 only" cut (leaves the index able
   to serve permanently wrong results, F-C3), and "all 17" (drags a schema
   change and an embedder install into a batch that is otherwise
   self-contained).
2. **F-C1: warm the import at server start, and additionally run sync tools
   off the loop.** Two independent layers — the warm-up removes the import
   from the loop, `anyio.to_thread.run_sync` removes every blocking call
   from it. The CLI does not warm, so `kb` keeps its startup time.
   Rejected: a module-scope `import sqlite_vec` in `searchdb.py` (simplest
   and unforgettable, but every `kb` command then pays the numpy import
   even when it never searches); `to_thread` alone (the only proof in the
   report is that pre-importing turns 120 s into 0.0 s — `to_thread` is
   plausible but unproven, and this is the finding that makes the product
   unusable).
3. **The F-C1 regression test lives at both tiers.** `tests/` spawns the
   server with `sys.executable` and talks real JSON-RPC with a hard
   timeout, so a dev machine catches it; `tests-gate` keeps the golden test
   on the installed wheel. `tests-gate/conftest.py:86-92` raises rather
   than skips when `KB_VENV` is unset — deliberately, and it stays that
   way; the point is that the gate must not be the *only* place this is
   covered.
4. **The freshness key is a stat manifest, not a content hash.**
   `_repo_fingerprint` runs on every query, so its cost is permanent.
   Hashing `relpath\0size\0mtime_ns` over the entry directory is O(files)
   syscalls with no reads and catches both committed and uncommitted
   hub-side edits. Rejected: `hashsync.build_manifest` (correct in every
   case, but reads every byte of the federation on every query — tolerable
   at 1.5 MB, not at 100 MB); a hub commit sha (O(1) in KB size but spawns
   a git subprocess per query, which on Windows costs more than the stats,
   and misses uncommitted worktree edits).
5. **F-C5: raw BM25 distance plus a structural rule, with the threshold
   measured before it ships.** RRF scores carry no magnitude — adjacent
   ranks within one leg always sit ~1.6 % apart — so any ratio test on RRF
   either never fires or always fires, which is exactly the failure the
   report documents (0/14 shipped, 9/10 with the floor lowered). BM25 does
   carry magnitude. The structural rule (same `doc_id` + `section_id`,
   different `repo_id`) needs no constant at all and covers the case a BA
   must never miss. Rejected: dropping the promise from README (the
   federation collision case is real and cheap to detect); the structural
   rule alone (says nothing about two genuinely close but different
   sections).
6. **F-C6: reclassify as `broken`, keep exactly three statuses.** C8 states
   the contract as ok/stale/broken with exits 0/1/2, and the golden and
   contract tests freeze it. A fourth status would change every downstream
   parser for no gain that a distinct reason string cannot deliver.
   Rejected: a new `removed` status; keeping `stale` behind an opt-in
   `--fail-on-removed` flag (leaves the dangerous default in place, which
   is the thing being reported).
7. **F-C9: make `tokenize` symmetric with `unicode61` rather than warn
   about the asymmetry.** The index already holds the non-ASCII tokens
   (`MATCH "đường"` → 1 hit); only the query side drops them. `[^\W_]+`
   with `re.UNICODE` matches unicode61's alphanumeric rule — underscore
   included as a separator, because unicode61 treats it as one. The warning
   stays for the residual case where a non-empty query yields no tokens.
   Rejected: warn-only (leaves a whole language class indexed and
   unsearchable, against C2's "L2 in the source language").
8. **F-C7: keep `K_LEG = 50`, tell the caller, fix the wording.** The
   budget is what actually bounds the answer, so raising the leg cap mostly
   buys fusion and load work. Rejected: raising or auto-sizing `K_LEG`
   (another unmeasured constant, which is the F-C11 complaint); fixing the
   docs alone (agents read the docstring, and neither says which call was
   truncated).
9. **F-C14: keep the synthetic doc-id tag on the query side, document it,
   and do not merge it into the kb-context vocabulary.** `kb tags` and
   `kb context new` already share one source (`kbcontext.tag_vocabulary`)
   and that part is clean; the divergence is that `searchdb` also indexes
   `doc.id.lower()`. Adding doc ids to the context vocabulary would make
   the `tags:` line of a context block noisier, and F-C15 already shows it
   carries little information. Rejected: removing the synthetic tag (breaks
   `--tags arinc-424`, which works today); merging the vocabularies.
10. **F-C4: one shared `normalize_level`, case-insensitive.** Two surfaces
    disagreeing is the bug; a single function they both call is the fix.
    Normalising case means MCP now accepts `level="L2"` where it used to
    refuse — a deliberate, small widening, frozen by no golden — while the
    CLI stops returning L2 to a caller who asked for `L3`.

## Scope

**In.** `src/center_kb/searchdb.py`, `query.py`, `mcp.py`, `cli.py`,
`resolve.py`, `kbcontext.py`, `hashsync.py`, `web/api.py`, `web/ui.py`,
`web/app.py`, `templates/init/`, `README.md`, plus tests in `tests/` and
`tests-gate/`.

**Out.** F-C8 beyond one README sentence, F-C11, F-C12, F-C15, F-C16.
No re-ingest and no re-summarize: the bundled `.kb/` is unchanged, and the
search index rebuilds itself.

## Design

### 1. `searchdb.warm_vec()` and the three transports

`searchdb` gains a module-level warm-up:

```python
_VEC_MODULE: object | None = None
_VEC_WARMED = False

def warm_vec() -> bool:
    """Import sqlite_vec once, off any event loop. Idempotent."""
```

`warm_vec()` performs the `import sqlite_vec` exactly once and caches the
module (or the failure). `_load_vec(conn)` (`searchdb.py:74-90`) no longer
imports; it calls `warm_vec()` if needed and then loads the extension into
the connection. Degradation when `sqlite_vec` is absent is unchanged: log
once, return `False`, keyword-only search.

Callers that own an event loop warm before it starts:

- `mcp.create_server()` (`mcp.py:89`) — covers `--transport stdio` and,
  through `create_http_app` (`mcp.py:222`), the HTTP transport;
- `web.app.create_app()` (`web/app.py:14`), at the top of the function —
  covers an app constructed without going through `create_server`.
  Not the `lifespan`: `web/app.py:36` leaves it `None` when `mcp_server is
  None`, so that hook does not run on the API-only path. `create_app` runs
  before uvicorn starts its loop, which is what the warm-up needs.

The CLI does not warm: `kb` keeps its current startup cost and only pays
for numpy when a query actually reaches the semantic leg.

The five tools registered in `create_server` become `async def` and run
their bodies through `anyio.to_thread.run_sync`. **Constraint:**
`tests-gate/golden/mcp_tools.json` is compared byte-identical, and FastMCP
derives each schema from the function signature plus `__doc__` (see
`_canonical_docstring`, `mcp.py:72-86`). Parameter names, annotations,
defaults and docstrings must not change — only `def` → `async def` and the
body. The golden schema test is what proves it.

Reviewer C tested stdio only, but the same deadlock is reachable over
HTTP: `web/api.py:147 async def api_search` and `web/ui.py:236 async def
_search_screen` call `query.search()` directly on the loop. Both move the
search call into `starlette.concurrency.run_in_threadpool`.

### 2. Error classification and the cold-build race (F-C2, F-C10)

`searchdb` gains, beside `is_lock_error` (`searchdb.py:93-103`):

```python
def classify_db_error(exc: sqlite3.Error) -> Literal["lock", "client", "corrupt"]
```

- `lock` — BUSY / LOCKED / PROTOCOL, as `is_lock_error` decides today.
- `client` — `sqlite3.IntegrityError` (a lost UNIQUE race), and
  `sqlite3.OperationalError` carrying `too many SQL variables`.
- `corrupt` — every other `sqlite3.DatabaseError`.

`query.py:125-132` calls `delete_db()` only in the `corrupt` branch. The
`lock` branch keeps serving the existing index (`query.py:105-112`,
unchanged). The `client` branch raises a clean caller-facing error and
never touches the file.

The cold build in `searchdb.sync` takes `BEGIN IMMEDIATE` around
`_create_schema` plus the first bulk insert, so exactly one process builds
and the losers block on `busy_timeout` and then find the schema present.
The comment at `searchdb.py:322-336` ("losing the race must be idempotent
and must not break UNIQUE") becomes true: five concurrent cold `kb query`
processes must all exit 0.

`hashsync._unlink_force` (`hashsync.py:53`) is promoted to a public
`unlink_force` and used by `searchdb.delete_db` (`searchdb.py:166-172`).
If the file is still held, the message is a clean one-liner and exit 1, not
a `PermissionError` traceback.

`_norm_tags` (`searchdb.py:541`) enforces `MAX_TAGS = 100`, far below any
SQLite bind limit, and **rejects** an over-cap list with a clear message
rather than silently truncating it. The published federation vocabulary is
10 tags today, so the cap is not a limit any real caller meets. The CLI and the MCP tool
both surface that message. No client-supplied value can reach the
`IN (?,?,…)` expansion at `searchdb.py:566-573` in a size SQLite refuses.

### 3. Freshness key and `kb reindex --force` (F-C3)

`_repo_fingerprint(repo_dir)` (`searchdb.py:226-230`) becomes a stat
manifest: walk every regular file under the entry directory in sorted
order and hash `relpath\0size\0mtime_ns` for each. Symlinks are skipped, as
in `hashsync.build_manifest`. `search.db` lives at `<hub>/.kb-work/`,
outside `federation/`, so the index cannot fingerprint itself.

`kb reindex` (`cli.py:1598`) gains `--force`: close every connection,
`delete_db`, then rebuild from scratch. The existing "index already
consistent — nothing to do" message stays for the non-forced path.

The implementation must **measure and record** the new fingerprint cost on
the bundled KB (332 sections) against today's 21 ms warm query, and the
number goes into the plan's task notes. A stat manifest that doubles warm
latency is a different decision from one that adds a millisecond.

### 4. `normalize_level` (F-C4)

`query.py` gains:

```python
def normalize_level(value: str) -> str:
    """'l2' | 'l3', case-insensitive. Anything else raises."""
```

The error text is the one MCP already uses: `level '<value>' is invalid —
use 'l2' or 'l3'`. `cli.py:1365` and `mcp.py:138-139` both call it;
`query.py:261` keeps `suffix = ".raw.md" if level == "l3" else ".md"` but
now only ever sees a normalised value. `kb get --level L3` exits 1 instead
of returning condensed L2 under an identical header.

### 5. The ambiguity note (F-C5)

`rrf_merge` (`searchdb.py:626-648`) carries each leg's raw score through
the fusion, so a consumer can see the BM25 magnitude that RRF discards.
The note is computed in `query.py` (both surfaces need it) and fires when
any of:

1. the top two share `doc_id` and `section_id` but differ in `repo_id` —
   a federation collision, no constant involved;
2. both come from the keyword leg and their raw BM25 scores are within a
   measured threshold;
3. the existing rule: both `hybrid` and RRF-close, or an exact score tie
   (`mcp.py:25-44`, preserved).

The threshold in (2) is chosen by running the battery in
`C-search-mcp-context.md` against the bundled KB and is recorded in the
implementation plan with its measurements. Acceptance: it does not fire on
the queries reviewer C scored ✔ rank-1, and it does fire on the documented
ambiguous pairs. `mcp.py` renders it in-band (an agent never sees stderr);
the CLI renders it on stderr.

### 6. The truncation flag (F-C7)

`fts_search` and `knn_search` report whether they filled `K_LEG` rows,
which means the leg was cut. The signal is deliberately conservative: a
query with exactly 50 matches reports truncation it did not suffer, which
costs a caller one extra sentence and never hides a real cut.
`query.search()` propagates it. MCP
adds an in-band note; the CLI writes to stderr. `kb_search`'s docstring
loses "Returns every relevant section found, not just the best match" in
favour of wording that matches the code, and README §7.8 follows.
`K_LEG = 50` (`searchdb.py:29`) is unchanged.

### 7. The tokenizer (F-C9)

`tokenize` (`searchdb.py:533-538`) becomes
`re.findall(r"[^\W_]+", text.lower(), re.UNICODE)`. Underscore stays a
separator because `unicode61` treats it as one; the `§`, `/`, `.`, `-`
behaviour that the report verified as symmetric is unaffected. A test
probes a Vietnamese term end to end: indexed, then retrieved by a query
containing it. When a non-empty query still yields zero tokens (punctuation
only), the CLI warns on stderr and MCP says so in-band instead of returning
a bare "No matching section found."

### 8. Resolve status classification (F-C6)

`resolve.py:96-100` splits one `stale` reason into three `broken` ones,
each with its own message and each exit 1:

- the section is absent from the worktree manifest — *the cited section no
  longer exists in `<doc>` at the current revision*;
- the document is absent from the worktree — *the cited document no longer
  exists*;
- the manifest cannot be read or parsed — *manifest unreadable*.

A genuine content change stays `stale`/exit 2 (cases a and d of the
mutation battery), and `ok` stays `ok` for L3-only and L1-only edits
(cases b and c). `kb doctor --context` maps the same codes.

The remediation hint must name a command that works: after a document is
removed, `kb diff <doc> --against <rev>` errors, so the hint for the
document-removed case points at the pin and the hub revision instead.

`hub_version`, parsed at `kbcontext.py:190-191` and never consulted,
becomes load-bearing: when present it must agree with the resolved hub
commit, and a disagreement is `broken`.

### 9. Tags: cap, vocabulary and the unknown-tag hint (F-C10, F-C14)

The cap is in §2. The synthetic document-id tag indexed at
`searchdb.py:350` stays and is documented in README §7.8 as a supported
filter. `kbcontext.tag_vocabulary` is unchanged, so `kb context new
--tags arinc-424` keeps refusing a document id as a content tag.
`kb query --tags <unknown>` stops returning a silent zero-result and prints
the published tags instead (battery case #32), listing content tags and
noting that document ids are also accepted.

### 10. Hub hygiene (F-C17)

A new `src/center_kb/templates/init/hub-gitignore.txt` containing
`.kb-work/` joins `impl-gitignore.txt` and `source-gitignore.txt`;
`kb init --kind hub` writes it. For hubs that already exist, `kb doctor`
warns when `.kb-work/` is present, untracked and not ignored — a hub
maintainer running `git add -A` must not commit a multi-MB binary.
`tests-gate/regression/test_golden_output.py:52` masks Windows temp paths
alongside `/tmp/...`, so the goldens stop being POSIX-shaped by
construction.

### 11. Docs

- README §7.5: the sample output becomes the real one —
  `--- [aero:arinc-424 §5.129 (Supplement 22)] match=keyword ~246tk` — and
  the claim that the citation is repo-qualified only on ambiguity is
  corrected to *always* (F-C13). `score=` is gone from the output and goes
  from the README too.
- README §7.8: drop "returns every relevant section found" (F-C7);
  restate the close-top-2 flag as what §5 now implements (F-C5); document
  `--tags <doc-id>` (F-C14); add one sentence saying `--budget` is
  advisory — the first result is admitted whatever its size, so a caller
  asking for 50 tokens can receive a 1488-token section (F-C8,
  documentation only, no code change).
- `kb_search` / `kb_get_section` docstrings track the README changes.
  Every docstring edit re-freezes `tests-gate/golden/mcp_tools.json`, which
  is expected and must be a deliberate, reviewed part of the diff.

## Error handling

- No client input reaches `delete_db()`. A bad tag list, a lost race and a
  malformed level are all caller errors with a message and a non-zero exit,
  and the index file is untouched.
- No `PermissionError`, `IntegrityError` or rich traceback reaches the user
  from the search path. Windows unlink failures degrade to a clean message.
- Absent `sqlite_vec` or `fastembed` still degrades to keyword-only with
  the existing warning on stderr and exit 0.
- A hung or unreachable transport fails a test rather than hanging it:
  every new subprocess test carries a hard timeout.

## Testing

TDD: each finding gets a failing test before its fix. Reviewer C's tables
become the test tables.

- `tests/test_mcp_stdio.py` (new): spawn `python -m center_kb.mcp
  --transport stdio` with `sys.executable`, send `initialize` then
  `tools/call kb_search`, assert a response inside a hard 30 s timeout.
  Skipped when `sqlite_vec` cannot be imported, since the bug only exists
  when it can. This test fails today (F-C1).
- `tests-gate/regression/test_golden_output.py`: a hard per-case timeout so
  the four cases fail instead of hanging with no teardown.
- `tests/test_searchdb_concurrency.py` (new): five concurrent cold `kb
  query` processes against a hub with no `search.db` → five exit 0, no
  traceback on stderr (today: 3/5 fail on every trial).
- `tests/test_searchdb.py`: `classify_db_error` over `IntegrityError`,
  `OperationalError("too many SQL variables")`, `OperationalError` BUSY and
  a `DatabaseError`; `delete_db` on a read-only file; over-cap `tags`
  rejected **and** `search.db` still present afterwards (the assertion
  reviewer C's F-C10 needs).
- `tests/test_query_freshness.py` (new): edit and commit a file directly in
  `federation/<repo>/` on the hub → the next `kb query` sees it and `kb
  get` agrees; `kb reindex --force` drops and rebuilds; the fingerprint
  cost on the bundled KB is measured and recorded.
- `tests/test_query_level.py` (new): the parametrised table `l3 / L3 /
  verbatim / raw / l1 / l2 / L2` across CLI and MCP, asserting the exit
  code and, for the valid levels, that L3 output is byte-longer than L2 for
  §5.129 — the report's own measurement (1310 vs 1219 bytes).
- `tests/test_query_ambiguity.py` (new): the note fires on the
  `aero:arinc-424 §5.129` vs `beta:arinc-424 §5.129` collision; it does not
  fire on the battery queries scored ✔ rank-1.
- `tests/test_query_truncation.py` (new): `record` (154 matches) carries the
  truncation note; `airspace` (42 matches) does not.
- `tests/test_searchdb_tokenize.py` (new): a Vietnamese term round-trips
  index ↔ query; a punctuation-only query warns instead of returning a bare
  no-match.
- `tests/test_resolve.py`: mutation cases (a)–(j) from the report — e, f, g
  become `broken`/1; a, d stay `stale`/2; b, c stay `ok`/0; h, i, j stay
  `broken`/1; the document-removed hint names a command that works;
  `hub_version` disagreement is `broken`.
- `tests/test_templates.py` / `test_init.py`: `kb init --kind hub` writes a
  `.gitignore` containing `.kb-work/`; `kb doctor` warns on a hub where it
  is untracked and unignored.
- `tests-gate/golden/mcp_tools.json` is regenerated once, deliberately, in
  the docstring task, and `test_mcp_contract.py` stays green.

The full suite runs 10–19 minutes, so it runs once at the end of the batch,
not per task.

## Acceptance

- `kb_search` over real stdio returns within the test's timeout in a venv
  with `sqlite-vec` installed; `test_mcp_contract.py` and all four golden
  cases pass on the wheel.
- Five concurrent cold `kb query` processes: five exit 0, no traceback.
- 40 000 tags: clean refusal, `search.db` still on disk.
- A commit made directly in `federation/` on the hub is returned by the
  next `kb query`, and `kb get` and `kb query` agree.
- `kb get --level L3` exits 1; `kb get --level l3` returns the verbatim L3.
- Resolve mutation cases e, f, g exit 1; a and d exit 2; b and c exit 0.
- A Vietnamese query retrieves the section containing the Vietnamese term.
- `kb init --kind hub` produces a hub whose `git status` is clean after a
  query has built the index.
- README §7.5 and §7.8 match the output of the shipped code.
