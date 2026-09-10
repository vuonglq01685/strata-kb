# Reviewer C — retrieval quality & the agent-facing contract (C6, C8, C9)

Repo `D:\Projects\AERO-KB` @ `4b47b4c` (v0.20.0). Repo untouched (read-only); every experiment ran in
`<scratch>/C/`.

---

## Scope & method

Built a real federation exactly as `scripts/demo-federation.sh` does, but publishing a **copy of the repo's
own `.kb/`** (arinc-424 + icao-annex-3, 325+4 sections) as repo id `aero`, plus a second child `beta`
carrying a colliding doc id `arinc-424`:

```
<scratch>/C/hub            local-path hub (git), federation/{aero,beta}
<scratch>/C/remotehub.git  bare clone of the same hub -> exercises the clone-into-cache path
<scratch>/C/aero, /beta    child repos with .kb/config.yaml {hub, repo_id}
CENTER_KB_HUB_CACHE=<scratch>/C/cache
```

What was run:

* **40-query retrieval battery** through `center_kb.query.search()` in-process (table below) + spot CLI runs.
* **Resolve mutation battery** (a)–(j): 10 mutations, each from a restored baseline, pin → mutate → commit →
  `kb publish` → `kb resolve` / `--status-only` / `kb doctor --context`, comparing returned bodies byte-wise
  against the pre-mutation resolve (`<scratch>/C/resolvecase.sh`, `mut-*.sh`).
* **MCP**: `tests-gate/regression/test_mcp_contract.py` **PASSED** in the foreground; the four
  `test_golden_output.py` cases could not complete (see F-C1 — they hang, which is itself the finding), so
  the goldens were verified by replicating the fixture (v0.9.0 `.kb` → bare hub → publish as `golden`) and
  diffing in-process; the tool schemas were diffed against `tests-gate/golden/mcp_tools.json` by
  instantiating the server in-process. 20 adversarial tool calls exercised in-process.
* **Index freshness / concurrency / perf**: cold build, warm latency, 8 threads, 5 concurrent processes,
  republish-vs-direct-hub-edit, `kb reindex`, `kb doctor`.
* **Semantic path**: `fastembed` is **not** installed in `.venv`; `sqlite_vec` **is**. Nothing was installed.
  The semantic leg was exercised with injected stub embedders (hash-bag and char-trigram) to prove which
  behaviours are reachable at all.

Both gate tests need `KB_VENV` pointing at a venv with the **installed wheel** (`tests-gate/conftest.py:86-92`
raises rather than skips). I ran them with `KB_VENV=D:/Projects/AERO-KB/.venv` (same sources, editable install).

---

## Verified good

1. **C9 tool surface is exact.** In-process `list_tools()` → exactly 5 tools, and
   `model_dump(by_alias=True, exclude_none=True)` is **byte-identical** to `tests-gate/golden/mcp_tools.json`.
   `tests-gate/regression/test_mcp_contract.py` passes (`1 passed in 6.99s`). The
   `_canonical_docstring`/`inspect.cleandoc` trick (`src/center_kb/mcp.py:72-86`) is a genuinely good fix for
   a real cross-interpreter wire-contract hazard.
2. **C7 holds empirically.** I added an unpublished doc `local-secret` (unique token `ZZUNPUBLISHEDMARKERZZ`)
   to `aero/.kb/` and pointed the MCP server's `--kb` at it. `kb_search` → "No matching section found";
   `kb_get_section local-secret 1.1` → "Not found … Available docs: aero:arinc-424, aero:icao-annex-3,
   beta:arinc-424". `create_server()` never touches `config.kb_dir`.
3. **Golden output contract holds.** Replicating the v0.9.0 fixture and diffing in-process:
   `kb_search_airspace`, `kb_search_restrictive`, `kb_get_section_5129_l2`, `kb_get_section_5129_l3` — all
   4 **MATCH**.
4. **Ambiguity handling is correct and helpful.** With `beta:arinc-424` published alongside `aero:arinc-424`:
   `kb get arinc-424 5.129` → exit 1, `doc 'arinc-424' exists in 2 federation repos — qualify the ref:
   aero:arinc-424, beta:arinc-424`; same for `kb context new` and the MCP tools; `--repo beta` and
   `aero:arinc-424` both work.
5. **Resolve returns the genuinely PINNED bytes.** In every stale case (a, d, e, f, g) the returned body is
   byte-identical to the pre-mutation resolve, i.e. the pin really is served from hub git history, not from
   the current worktree.
6. **Exit-code contract 0/1/2 is honoured** by `kb resolve`, `kb resolve --status-only` and
   `kb doctor --context` for ok / broken / stale, and the three "broken" paths (tampered `version`,
   gc-pruned hub history, legacy two-version block) all give a clear, actionable message.
7. **Windows CRLF trap avoided.** In a cloned hub the worktree L2 file is pure CRLF (2844 CRLF / 0 bare LF)
   while the git blob is LF — yet `kb resolve` still says `status=ok`, because `gitio.read_at` (`text=True`)
   and `Path.read_text` both normalise. A very easy way to make every citation look stale on Windows; it
   doesn't happen.
8. **Cache resilience.** Cache dir deleted between pin and resolve → transparently re-cloned, `status=ok`.
   Hub unreachable *and* no cache → clean message + exit 1, no traceback, no credentials leaked.
9. **FTS input is safe.** `_fts_match` (`src/center_kb/searchdb.py:545-548`) tokenises then quotes, so
   `kb_search('runway" OR fts MATCH "airspace')` is a harmless keyword query, not FTS syntax.
10. **Tokenizer symmetry for the domain's punctuation.** `/`, `.`, `-`, `§` are separators on both the query
    side (`[a-z0-9]+`) and the index side (`unicode61`), so `CUST/AREA`, `S/T`, `ARPT/HELI IDENT`,
    `ARINC-424`, `§5.129` all retrieve correctly (verified with a probe FTS table).
11. **C6's ≥ 90 % token saving is comfortably met** (see §"Budget & output contract").
12. **Perf is fine at this scale**: cold build 1.05 s for 332 sections → 1.5 MB `search.db`; warm query 21 ms;
    8 in-process threads × 20 queries → 1.11 s, 0 errors.
13. **`--semantic` degrades honestly**: warning on stderr, keyword results on stdout, exit 0 —
    `semantic search requested but no embedder is available — keyword results only (enable with: pip install "center-kb[embed]")`.

---

## Findings

### F-C1 · HIGH · `kb_search` over MCP stdio hangs forever (the primary agent entry point is unusable)

`searchdb._load_vec()` does `import sqlite_vec` **lazily, at request time**
(`src/center_kb/searchdb.py:74-90`, the import at `:76`), and `sqlite_vec` transitively imports numpy's native
`_multiarray_umath`. FastMCP runs a sync tool function **inline on the asyncio event-loop thread**; that
native import deadlocks there on Windows.

Repro (reproduced 4×; `<scratch>/C/gold/raw3.py`):

```
$ python -u raw3.py            # raw JSON-RPC over stdio to `python -m center_kb.mcp`
elapsed 120.0s  poll=None  lines=1        # process ALIVE, no response, ever
--- server stderr ---
INFO:mcp.server.lowlevel.server:Processing request of type CallToolRequest
INFO:center_kb.embed:fastembed not installed — semantic search disabled, keyword search only
```

`faulthandler` stack of the hung server (`<scratch>/C/gold/fh.txt`):

```
File ".../numpy/_core/multiarray.py", line 11 in <module>      <-- stuck in create_module
File ".../sqlite_vec/__init__.py", line 35 in <module>
File "D:\Projects\AERO-KB\src\center_kb\searchdb.py", line 76 in _load_vec
File "D:\Projects\AERO-KB\src\center_kb\searchdb.py", line 110 in _raw_connect
File "D:\Projects\AERO-KB\src\center_kb\searchdb.py", line 194 in open_db
File "D:\Projects\AERO-KB\src\center_kb\searchdb.py", line 524 in open_fresh
File "D:\Projects\AERO-KB\src\center_kb\query.py", line 105 in _search_index
File "D:\Projects\AERO-KB\src\center_kb\mcp.py", line 120 in kb_search
File ".../mcp/server/fastmcp/tools/base.py", line 101 in run
File ".../mcp/server/lowlevel/server.py", line 541 in handler
File ".../asyncio/windows_events.py", line 321 in run_forever      <-- event loop thread
```

Proof of cause: with a `sitecustomize.py` that only does `import numpy` (or `import sqlite_vec`) at
interpreter start, the identical call returns in **0.0 s**:

```
elapsed 2.0s  poll=None  lines=2
  +0.0s {"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"No matching section found …
```

Scope: any environment where `sqlite-vec` is importable — which is **every `[embed]` install**, every `[dev]`
install, and this repo's own `.venv`. `kb_get_section` (no `_load_vec`) works; the CLI works (the import
happens on the main thread outside a running loop). It is also why
`tests-gate/regression/test_golden_output.py` fails/hangs here (`F` then no teardown), and it matches this
session's own `center-kb (CONNECTION_CLOSED): "Connection closed"`.
Violates **C9** (tools must work over stdio) and **C6**.
Fix: import `sqlite_vec`/numpy once at module import time (or behind a one-shot warm-up at server start),
and/or run sync tools via `anyio.to_thread`.

### F-C2 · HIGH · Concurrent cold index builds mis-diagnose an integrity error as corruption and delete the index

Five `kb query` processes started against a hub with no `search.db` (the normal state after a fresh clone, or
several agents starting at once):

```
$ rm -f hub/.kb-work/search.db*; for i in 1..5; do kb query "airspace" & done
trial 1 exits: 1:0 2:1 3:0 4:1 5:1
trial 2 exits: 1:0 2:1 3:0 4:1 5:1
trial 3 exits: 1:0 2:1 3:1 4:1 5:0        # 3/5 fail, every trial
```

The failing processes print a **raw rich traceback**, not a clean error:

```
search.db corrupt — rebuilding once: UNIQUE constraint failed: sections.repo_id, sections.doc_id, sections.section_id
...
PermissionError: [WinError 32] The process cannot access the file because it is being used by another
process: '...\hub\.kb-work\search.db'
```

Two distinct defects:
* `src/center_kb/searchdb.py:322-336` carries the comment *"losing the race must be idempotent and must not
  break UNIQUE (spec §5: losing the race only wastes work, never corrupts data)"* — demonstrably false. An
  `sqlite3.IntegrityError` is not a lock error (`is_lock_error`, `searchdb.py:93-103`, only recognises
  BUSY/LOCKED/PROTOCOL), so `src/center_kb/query.py:125-132` treats it as corruption and calls `delete_db`.
* `delete_db` (`searchdb.py:166-172`) unlinks a file another process still holds → `PermissionError` escapes
  to the user. `hashsync._unlink_force` exists for exactly this Windows problem and is not used here.

Warm-index concurrency is fine (6 readers → 6× exit 0; a 324-section bulk resync with 6 concurrent readers →
6× exit 0), so this is specific to the cold build — i.e. exactly the first thing a new user or a fresh CI job
hits. Violates **C6**, **C15** (clean error, not traceback).

### F-C3 · HIGH · A change made directly in `federation/` on the hub is invisible to search forever

`_repo_fingerprint` (`src/center_kb/searchdb.py:226-230`) hashes only `_meta.yaml` and `index.yaml`.
`_meta.yaml` is only rewritten by `kb publish` when the *child* pushes changed content
(`src/center_kb/publish.py:_snapshot`). So any edit made on the hub side — the exact place README §7.9 calls
"the single review gate" — never invalidates the index.

```
# reviewer fixes a typo directly in federation/ and commits on the hub
$ kb query "ZZHUBFIXMARKERZZ"     -> No matching section found.
$ kb get aero:arinc-424 5.130     -> ## 5.130 Multiple Code
                                     ZZHUBFIXMARKERZZ typo fixed directly on the hub by a reviewer. (MULTI CD)
```

`kb query` and `kb get` permanently disagree about the same section. Worse, neither repair command helps:

```
$ kb reindex   -> kb reindex: search index — 0 updated, 0 removed, 0 embedded
                  kb reindex: index already consistent — nothing to do
$ kb doctor    -> kb doctor: OK
```

Only `rm hub/.kb-work/search.db` fixes it. Violates **C6** (search must reflect the hub) and undermines **C7**
(the hub is the single source of truth — but only for `kb get`).

### F-C4 · HIGH · `kb get --level <anything but exactly "l3">` silently returns the CONDENSED L2

`src/center_kb/query.py:261` — `suffix = ".raw.md" if level == "l3" else ".md"` — and the CLI
(`src/center_kb/cli.py:1134-1160`) does not validate `level` at all. Measured output size for the same
section:

| `--level` | exit | bytes | what you get |
|---|---|---|---|
| `l3` | 0 | 1310 | L3 verbatim ✔ |
| `L3` | 0 | 1219 | **L2 condensed**, no warning |
| `verbatim` | 0 | 1219 | **L2 condensed**, no warning |
| `raw` | 0 | 1219 | **L2 condensed**, no warning |
| `l1` | 0 | 1219 | **L2 condensed**, no warning |

The header is identical in every case (`--- [aero:arinc-424 §5.129 (Supplement 22)] ~253tk`), so a caller
asking for the untouched original and getting the AI-condensed text **cannot tell**. The MCP tool does
validate (`src/center_kb/mcp.py:138-139` rejects anything but `l2`/`l3`) — so the two surfaces disagree. In a
KB whose whole premise is "L3 is verbatim, L2 is not", this is the most dangerous silent substitution in the
CLI.

### F-C5 · HIGH · `kb_search`'s advertised "flags when the top two are close in score" never fires in the shipped default

README §7.8: *"…and flags when the top two are close in score"*. `_ambiguity_note`
(`src/center_kb/mcp.py:25-44`) requires **both** top hits to be `match_mode == "hybrid"` (present in *both*
legs) **or** an exact score tie.

* Default install (no `fastembed` → `default_embedder()` returns `None` → no KNN leg): every rowid appears in
  exactly one leg at exactly one rank, so RRF scores are always distinct (0.016393 vs 0.016129) and
  `both_hybrid` is always `False`. Measured: **0 / 14 queries fire**, including deliberately ambiguous ones
  ("Restrictive Airspace Designation" where `beta:arinc-424 §5.129` and `aero:arinc-424 §5.129` are the top
  two — precisely the case a BA must be warned about).
* With a stub embedder but the shipped `SEMANTIC_MIN_SCORE = 0.6`: still **0 / 10**.
* With both legs genuinely contributing (floor lowered to 0.0): **9 / 10 fire** — including on unambiguous
  queries.

So the flag is either never on or almost always on; it has no calibrated middle. The committed golden
`tests-gate/golden/mcp_outputs/kb_search_*.txt` contains no note either, so the gate freezes the
never-fires behaviour. Violates **C6** ("flags close top-2 scores").

### F-C6 · MEDIUM · A deleted section, a renumbered section and a deleted *document* all report `stale`, never `broken`

Mutation battery (all mutations applied to the child, committed, republished):

| case | mutation | status | exit | reason string | body == pinned? |
|---|---|---|---|---|---|
| a | L2 prose edit | stale | 2 | "L2 content has changed since the pinned version" | yes |
| b | L3-only edit | ok | 0 | — | yes |
| c | L1 summary-only edit | ok | 0 | — | yes |
| d | table row edited inside L2 | **stale** | 2 | "L2 content has changed…" | yes |
| e | section deleted | stale | 2 | "section unreadable in worktree (deleted, id changed, or manifest broken)" | yes |
| f | section renumbered 5.129→5.129a | stale | 2 | same as (e) | yes |
| g | **whole doc removed** | stale | 2 | same as (e) | yes |
| h | hub history rewritten (gc-pruned) | broken | 1 | "pinned commit … does not exist on the hub" | n/a |
| i | hand-tampered `version:` | broken | 1 | same | n/a |
| j | legacy two-version block | broken | 1 | same | n/a |

(b) and (c) returning `ok` is documented and correct (README §7.8: resolve watches L2, `kb diff` watches
L1/L3). (d) correctly catches a table edit — good.

The problem is **e/f/g**. `src/center_kb/resolve.py:96-100` collapses "the worktree copy is unreadable" into
`stale`, so CI (`kb doctor --context`, exit 2 = "flag for review") treats *the cited standard section no
longer exists* the same as *someone reworded a sentence*. Only the free-text reason distinguishes them. The
remediation hint is also a dead end after (g):

```
!! … — run `kb diff arinc-424 --against 6bc6918` to see the changes
$ kb diff arinc-424 --against 6bc6918
doc 'arinc-424' is not in the worktree (…\aero\.kb\arinc-424\_manifest.yaml)
```

Related nit: `hub_version` is parsed (`src/center_kb/kbcontext.py:190-191`) but never consulted — a legacy
block whose `version` happens to be a real hub commit resolves silently as `ok`, ignoring `hub_version`
entirely.

### F-C7 · MEDIUM · Recall is hard-capped at 50; "returns every relevant section found" is not true

`K_LEG = 50` (`src/center_kb/searchdb.py:29`) caps each leg before RRF, and nothing tells the caller results
were dropped:

| query | sections actually matching in FTS | returned with budget = 10^7 |
|---|---|---|
| `record` | 154 | **50** |
| `runway` | 63 | **50** |
| `airspace` | 42 | 42 |

The `kb_search` docstring — which agents read — says *"Returns every relevant section found, not just the best
match … show ALL returned sections … Citing more than one section for a single story is normal."* For a broad
BA query that is a false assurance. Violates **C6** / README §7.8.

### F-C8 · MEDIUM · `--budget` is advisory: the first hit is admitted whatever its size

`src/center_kb/query.py:173` (`if results and used + n_tokens > budget`) always admits result #1.

```
--budget 50     -> 1 result, 246 tokens   (4.9x over)
--budget 0      -> 1 result, 246 tokens
budget = -100   -> 1 result (MCP)          (negative budget honoured as "one section")
```

Defensible as "always return something", but it is undocumented, and on this corpus a single section can be
1488 tokens (`§5.77-x85`), so a caller asking for 50 can get ~30× that. Note this never cuts *inside* a
table — sections are all-or-nothing, so the "tables verbatim" promise survives budget truncation (good).

### F-C9 · MEDIUM · Non-ASCII queries are silently shredded and return confident wrong answers

`tokenize()` (`src/center_kb/searchdb.py:533-538`) is `re.findall(r"[a-z0-9]+", text.lower())` — ASCII only —
while the index is `unicode61` and *does* hold non-ASCII tokens:

```
tokenize("đường băng sân bay")  -> ['ng', 'b', 'ng', 's', 'n', 'bay']
_fts_match("đường băng")        -> "ng" OR "b" OR "ng"
index probe: MATCH "đường" -> 1 hit,  MATCH "duong" -> 0 hits
```

`kb query "đường băng sân bay"` returns 2 confident results (§5.91, §5.301) with citations and no warning;
`kb query "quản lý chất lượng"` returns 4. C2 requires L2 to be **in the source language**, so a
Vietnamese/CJK KB would be indexed but unsearchable — and, worse, would answer with junk rather than "no
match". The source comment acknowledges the gap ("Accepted: the corpus is English-language aviation specs")
but the failure mode is silent-wrong, not empty.

### F-C10 · MEDIUM · A client-controlled oversized `tags` list deletes the shared index

`tags` reaches `fts_search` as one `IN (?,?,…)` bind list (`src/center_kb/searchdb.py:566-573`) with no cap:

```
tags = 2000 entries   -> ok
tags = 20000 entries  -> ok
tags = 40000 entries  -> search.db corrupt — rebuilding once: too many SQL variables
                         OperationalError: too many SQL variables
```

`too many SQL variables` is an `OperationalError` that `is_lock_error` does not recognise, so
`src/center_kb/query.py:131` logs "corrupt" and `delete_db()`s the index that every user of that hub shares.
`tags` is agent-supplied on the MCP tool, so this is reachable from a malformed (or hostile) tool call.
Impact is a rebuild + one failed query, not permanent loss — but destroying shared state in response to a
client input error is the wrong reflex, and on Windows it can compound into F-C2's `PermissionError`.

### F-C11 · MEDIUM · The semantic leg is gated by an unvalidated magic constant

`src/center_kb/embed.py:10`: `SEMANTIC_MIN_SCORE = 0.6  # … tune once measured for real`. Score is
`1/(1+L2distance)`, so 0.6 demands L2 distance ≤ 0.667 — cosine similarity ≥ 0.778 for unit-norm vectors,
which is a high bar for bge-small-en-v1.5. Measured with a lexical-similarity stub embedder over the real
corpus:

```
raw knn distances for "Restrictive Airspace":
  (134, 0.767 -> 0.566), (330, 0.835 -> 0.545), (137, 0.840 -> 0.543), …
knn hits passing SEMANTIC_MIN_SCORE=0.6: 0
```

Every nearest neighbour, including the correct §5.126/§5.129, was discarded. I could not measure the real
fastembed distribution (extra not installed, and I did not install it), so this is flagged as *unvalidated*
rather than *proven wrong* — but the constant is the single control on whether C6's hybrid half exists at
all, and the code says it was never measured.

### F-C12 · MEDIUM · Retrieval quality gaps on bare section numbers and natural-language questions

See the battery table. Because `5.7` tokenises to `["5","7"]` under OR semantics, a bare section number only
works when its numeric part is rare: `5.129` → §5.129 rank 1 ✔, but `5.7` → §5.7 **not in the top 3**
(returns §5.250, §5.258, §5.196). Natural-language questions are hit-or-miss with no semantic leg to rescue
them: *"what is the length of the runway identifier field"* returns §5.201/§5.199/§5.289 — §5.46
*Runway Identifier* is absent from the top 3, even though the exact-phrase query finds it at rank 1. There is
no typo tolerance (`restictive airspace` → §5.215/§5.216/§5.126; the correct §5.129 is absent).

### F-C13 · LOW · README §7.5's sample output no longer matches reality; the citation is *always* repo-qualified

README §7.5 shows `--- [arinc-424 §5.129 (Supplement 22)] score=17.19 ~246tk` and states *"Results always
include a clear citation of the form `<doc-id> §<section> (<revision>)`"*. Actual output:
`--- [aero:arinc-424 §5.129 (Supplement 22)] match=keyword ~246tk`. `_citation`
(`src/center_kb/query.py:47-49`) unconditionally prefixes `repo_id:` — there is no "only on ambiguity" branch
(the committed golden agrees: `[golden:arinc-424 §5.215 …]`). Always-qualified is arguably the better
behaviour; the docs and C6's wording are what is stale. `score=` was removed in the hybrid rework and never
updated in README.

### F-C14 · LOW · Two different tag vocabularies

`src/center_kb/searchdb.py:350` indexes `doc.id.lower()` as a synthetic tag, so
`kb query --tags arinc-424` works. `kbcontext.tag_vocabulary` (the source for both `kb tags` and
`kb context new` validation) reads only `IndexEntry.tags`, so:

```
$ kb context new --refs "arinc-424 §5.129" --tags "arinc-424"
tag not published by any document on the hub federation: 'arinc-424' (did you mean arinc424?)   [exit 1]
```

Answer to Q8: `kb tags` and context validation **do** share one source (`tag_vocabulary`) — that part is
clean and well documented. The divergence is on the *query* side.

### F-C15 · LOW · A1 tag derivation is document-granular, so blocks carry the whole vocabulary

`derive_tags` (`src/center_kb/kbcontext.py:102-137`) is explicit that sections have no tags
(`SectionEntry`/`Manifest` have no `tags` field) so it derives from `IndexEntry.tags`. Consequence:

```
--refs "arinc-424 §5.129"                       -> tags: [airport, airspace, airway, arinc424, navaid, navdata]
--refs "arinc-424 §5.129,icao-annex-3 §2.2"     -> tags: [airport, airspace, airway, annex3, arinc424, icao,
                                                          met, meteorology, navaid, navdata]   # = ALL 10
```

A two-doc block reproduces the entire federation vocabulary, so the `tags:` line carries no information. C8's
"tags auto-derived from the pinned **sections'** tags" is unreachable as specified. Bogus explicit tags are
rejected well (`'airspce' (did you mean airspace?)`, exit 1) and valid ones are canonicalised — that part
works.

### F-C16 · LOW · `raw match:` L3 snippets can start mid-table

`_l3_snippet` (`src/center_kb/query.py:62-88`) slices a ±150-char window out of L3. Forced repro on the
`beta` doc:

```
raw match: …---------|-------------------|
| AAA  | First row filler text to push the window boundaries  | note one          |
| BBB  | Second row containing the QQUNIQUETOKENQQ marker val | note two          |
```

A markdown renderer sees a headerless, malformed table. It is honestly marked (`raw match:` + `…`), and on
the bundled KB the path is unreachable at all (0/7 attempts — a side effect of F-A: L2 ≈ L3, so every matched
term is already in L2), so severity is low.

### F-C17 · LOW · Hub hygiene / test-harness nits

* The index lives at `<hub>/.kb-work/search.db` and shows up as an **untracked** `?? .kb-work/` in the hub
  worktree. `publish` correctly uses path-scoped `commit_paths(["federation"])`, but no `kb init` scaffold
  ships a `.gitignore` covering it (`src/center_kb/templates/init/` has only `impl-gitignore.txt` and
  `source-gitignore.txt`), so a hub maintainer running `git add -A` commits a multi-MB binary.
* `tests-gate/regression/test_golden_output.py:52` masks only `/tmp/[^\s"']+` — Windows temp paths
  (`C:\Users\…\Temp\…`) are not masked, so the goldens are POSIX-shaped by construction.

---

## Retrieval quality battery (40 queries, `budget=2000` unless noted)

Correctness judged against `_manifest.yaml` titles/summaries. ✔ = the right section is rank 1; ~ = right
section in the top 3; ✘ = absent from the top 3.

| # | class | query | top-3 (doc §id) | verdict |
|---|---|---|---|---|
| 1 | exact field | `Restrictive Airspace Designation` | 5.129 · 5.213 · 5.126 | ✔ |
| 2 | exact field | `Runway Identifier` | 5.46 · 5.11 | ✔ |
| 3 | exact field | `Magnetic Variation` | 5.39 · 5.290 · 5.291 | ✔ |
| 4 | abbrev `/` | `CUST/AREA` | 5.3 · 5.281 · 5.280 | ✔ |
| 5 | abbrev `/` | `S/T` | 5.2 · 5.138 · 5.205 | ✔ |
| 6 | abbrev `/` | `ARPT/HELI IDENT` | 5.6 · 5.87 · 5.77-x85 | ✔ |
| 7 | abbrev | `RT TYPE` | 5.7 · 5.223 · 5.99 | ✔ |
| 8 | abbrev | `IFR CAP` | 5.108 · 5.140 · 5.151 | ✔ |
| 9 | bare § no. | `5.129` | 5.129 · 5.318 · 5.10 | ✔ |
| 10 | § prefix | `§5.129` | 5.129 · 5.318 · 5.10 | ✔ (§ stripped) |
| 11 | worded | `section 5.4` | 5.4 · 5.174 · 5.296 | ✔ |
| 12 | bare § no. | `5.7` | 5.250 · 5.258 · 5.196 | **✘** (§5.7 exists) |
| 13 | table ask | `Section Code table 5-1 subsection codes` | 5.5 · 5.3 | ~ (5.4 *Section Code* missing) |
| 14 | table ask | `table of continuation record numbers` | 5.12 · 5.244 · 5.31 | **✘** (5.16 is the answer) |
| 15 | ICAO | `quality management meteorological service` | a3 §2.2 · 2.1 · 2.3 | ✔ |
| 16 | ICAO | `notification operators` | a3 §2.3 · 2.1 | ✔ |
| 17 | ICAO | `aeronautical meteorological station observations` | a3 §2.2 · 2.1 · 5.106 | ✔ |
| 18 | natural | `which field says whether a record is standard or tailored` | 5.2 · 5.3 · 5.230 | ✔ |
| 19 | natural | `how do I know if an airport supports IFR` | 5.108 · 5.202 · 5.140 | ✔ |
| 20 | natural | `what is the length of the runway identifier field` | 5.201 · 5.199 · 5.289 | **✘** (5.46) |
| 21 | misspell | `restictive airspace` | 5.215 · 5.216 · 5.126 | **✘** (no fuzzy) |
| 22 | misspell | `runway idenifier` | 5.59 · 5.57 · 5.109 | **✘** (5.46) |
| 23 | stopwords | `what is the purpose of the record` | 5.221 · 5.2 · 5.201 | n/a (no target) |
| 24 | stopwords | `the of and to a in` | a3 §2.2 · 5.204 · 5.274 | ✘ noise, 6 results returned |
| 25 | Vietnamese | `đường băng sân bay` | 5.91 · 5.301 | **✘** shredded query, silent |
| 26 | Vietnamese | `quản lý chất lượng` | 5.91 · 5.196 · 5.10 | **✘** shredded query, silent |
| 27 | empty | `""` | — | ✔ 0 results, "No matching section found." exit 0 |
| 28 | 1 char | `a` | 5.91 · 5.271 · 5.187 | ✘ noise, 10 results |
| 29 | 1 char | `5` | 5.318 · 5.10 · 5.296 | ✘ noise |
| 30 | tag (1 doc) | `quality management` `--tags icao` | a3 §2.2 · 2.1 (only icao doc) | ✔ filter works |
| 31 | tag | `runway` `--tags navdata` | 5.59 · 5.57 · 5.109 | ✔ |
| 32 | bad tag | `runway` `--tags nonexistent-tag` | — | ~ 0 results, but no "unknown tag" hint |
| 33 | doc-id tag | `runway` `--tags arinc-424` | 5.59 · 5.57 · 5.109 | works (undocumented, cf. F-C14) |
| 34 | budget 50 | `Restrictive Airspace Designation` | 5.129 (246 tk) | ✘ 4.9× over budget (F-C8) |
| 35 | budget 100000 | same | 5.129 · 5.213 · 5.126, n=49 | capped by K_LEG (F-C7) |
| 36 | budget 0 | same | 5.129 (246 tk) | ✘ (F-C8) |
| 37 | mixed | `5.129 designation` | 5.129 · 5.213 · 5.236 | ✔ |
| 38 | dash | `ARINC-424` | 5.211 · 5.32 · 5.91 | n/a (no doc-level target) |
| 39 | case | `RESTRICTIVE AIRSPACE DESIGNATION` | 5.129 · 5.213 · 5.126 | ✔ case-insensitive |
| 40 | phrase | `Continuation Record Number` | 5.16 · 5.12 · 5.32 | ✔ |

**Score: 21 ✔ rank-1, 2 ~, 9 ✘, 8 n/a/noise-probes.** Exact field names and punctuated abbreviations are
excellent; bare section numbers, table-oriented asks, natural-language questions, misspellings and any
non-ASCII language are weak — all of which the (absent) semantic leg was supposed to cover.

**How ranking works** (for the record): index = one FTS5 table, `tokenize='unicode61'`
(`searchdb.py:148-151`), four columns — `title`, `summary` (the L1 line), `body_l2` (full L2 slice **including
tables**), `body_l3` (full L3 slice). Title/id boost is via BM25 column weights `4.0, 2.0, 1.5, 1.0`
(`searchdb.py:37`) — title strongest, L3 weakest. Section *ids* are not a separate column; they are found only
because the `## 5.129 …` heading is inside `body_l2`/`body_l3`. Tags pre-filter at document level via
`doc_tags` (`EXISTS` sub-select, `searchdb.py:566-573`). Query text → `" OR ".join('"tok"')` over
`[a-z0-9]+` tokens. Fusion is textbook RRF, `score = Σ 1/(60 + rank)` per leg (`searchdb.py:626-648`,
`RRF_K = 60` at `:30`), ties broken by ascending rowid. Semantic leg = `vec0` KNN,
`score = 1/(1+distance)`, floor 0.6, over-fetch ×4 when tags are present because vec0 cannot pre-filter.
Embedding text is `title\nsummary\nbody_l2[:500]` (`_L2_HEAD_CHARS`, `embed.py:12`) — L3 is never embedded.
No hit → CLI prints `No matching section found.` (exit **0**); MCP returns
`No matching section found — try dropping tags or changing keywords.`

## Budget & output contract

* **Tables are never cut by budget.** `search()` admits whole sections only, so a table is either fully
  present or the section is not returned at all — the "tables verbatim" promise survives at the reader's end.
  The one place a table can be sliced is the `raw match:` L3 snippet (F-C16), which is explicitly marked.
* **Citation** is `<repo>:<doc> §<sec> (<rev>)` — always present, always repo-qualified (F-C13).
* **Close top-2 flag**: 0 fires in 14 real queries on the shipped default; 9/10 fires when both legs are live
  (F-C5). Two examples that fire (floor lowered so the KNN leg contributes):
  `"Restrictive Airspace"` → `[aero:arinc-424 §5.126]` vs `[beta:arinc-424 §5.129]`, both `hybrid`, exact tie
  0.032522; `"Controlled Airspace Name"` → §5.216 (0.032787) vs §5.217 (0.031054), ratio 0.947.
  Two that do not: `"quality management"` (only one result survives the budget → `len<2`), and
  `"Restrictive Airspace Designation"` with the default floor (top is `hybrid`, #2 is `keyword`-only).
* **Token saving vs the full L3 file** (arinc-424 L3 = 85 926 tokens, L2 = 76 126):

| query | results | tokens returned | saving vs L3 | vs L2 |
|---|---|---|---|---|
| Restrictive Airspace Designation | 12 | 1859 | **97.84 %** | 97.56 % |
| Runway Identifier | 2 | 1061 | **98.77 %** | 98.61 % |
| Magnetic Variation | 7 | 1956 | **97.72 %** | 97.43 % |
| Continuation Record Number | 7 | 1605 | **98.13 %** | 97.89 % |
| Section Code | 8 | 1872 | **97.82 %** | 97.54 % |

C6's **≥ 90 % is met** with margin; the *claimed* ≥ 99 % only holds at small budgets (a single-section answer
is 99.4–99.97 %).

## Index freshness (answers to Q3)

* **Location** `<hub-root>/.kb-work/search.db` (`searchdb.db_path`) — for a remote hub, inside the cache
  clone; untracked by git.
* **Rebuild trigger** two levels: per-repo `_repo_fingerprint` = `sha256(_meta.yaml || index.yaml)`
  (`searchdb.py:226-230`) to skip untouched repos, then per-section
  `content_hash = sha256(title\nsummary\nbody_l2\nbody_l3)`. Schema-version mismatch / `DatabaseError` /
  `vec_sections` present without sqlite-vec → delete + rebuild once.
* **Federation change between two queries**: a normal child republish is picked up correctly
  (`ZZFRESHMARKERZZ` visible on the very next query). A **hub-side edit is never picked up** — F-C3.
* **Concurrent readers**: warm = clean (8 threads × 20, 6 processes); cold = F-C2.
* **Size / time**: 1.5 MB and 1.05 s cold for 332 sections; 21 ms warm.

## Semantic path (answers to Q4)

`fastembed` **not** installed, `sqlite_vec` **is** (via the `dev` extra). `default_embedder()` logs
`fastembed not installed — semantic search disabled, keyword search only …` at INFO and caches `None` for the
process lifetime. `kb query --semantic` prints the warning on **stderr**, returns keyword results on stdout,
exit **0** — honest, no silent fallback in the *messaging*. The silent parts are: (i) `match=keyword` is the
only surviving signal that half the pipeline is off, (ii) the close-top-2 flag disappears entirely (F-C5) with
no note saying so, and (iii) `SEMANTIC_MIN_SCORE` can suppress the leg even when it *is* installed (F-C11).
With an injected stub embedder the KNN leg does change top-3 on lexically-similar queries and `match=hybrid`
appears, so the plumbing itself is correct.

## MCP contract (answers to Q5)

`test_mcp_contract.py` **passes**. `test_golden_output.py` cannot run here — it needs `KB_VENV` (installed
wheel) *and* it trips F-C1, hanging after the first failure. Replicated in-process: all 4 goldens match, and
the live tool snapshot is byte-identical to `tests-gate/golden/mcp_tools.json`.

Docstrings vs README §7.8: substantively aligned; three drifts — README omits `kb_get_section`'s `repo`
parameter; README's `kb_search` row promises the close-top-2 flag (F-C5) and "every relevant section"
(F-C7); the `kb_ticket_lint` MCP-only caveat (back-link checks skipped) is in the docstring but not in §7.8's
table.

Adversarial calls (all clean strings, no tracebacks): unknown doc / unknown section → `Not found: … Available
docs: …`; ambiguous doc id → qualified options; `level='l1'` and `level='L2'` → `level '…' is invalid — use
'l2' or 'l3'.`; empty & whitespace query → "No matching section found…"; budget 0 / −100 → one section
(F-C8); 2000 tags → no hit, no crash (40 000 → F-C10); FTS injection → neutralised; `kb_context_new` with
`refs: []` → "--refs is empty…"; `kb_resolve` with garbage → "kb-context error: no 'kb-context:' block found".

## kb-context (answers to Q6)

Block format is stable and byte-deterministic:

```
kb-context:
  version: "6bc6918"
  refs:
    - aero:arinc-424 §5.129
  tags: [airport, airspace, airway, arinc424, navaid, navdata]
```

`version` = hub HEAD short sha (`gitio.head_commit(gitio.git_root(hub.root))`); refs are auto-qualified with
the repo id; tags are derived (F-C15) and sorted by lowercase key. Explicit bogus tag → exit 1 with a
`difflib` suggestion; explicit valid tag → canonicalised spelling only; repo-qualified refs accepted verbatim;
ambiguous doc id refused with both options; a ref to a heading that exists in L3 but not in the manifest
(`§5.6.1`, `§5.115-x87-x88`) is refused for pinning (exit 1) although `kb get --level l3` *can* fetch it via
the folded-parent path — a small asymmetry, correctly conservative. Multi-doc refs work in one call.

---

## Criteria scorecard

| Criterion | Verdict | Why (one line) |
|---|---|---|
| **C6** — tag pre-filter → hybrid FTS5+KNN → RRF → budget; no AI call; citation format; every relevant section; close-top-2 flag; ≥ 90 % saving | **partially met** | Pipeline, RRF, tag pre-filter, no-AI and ≥ 90 % saving (97.7–98.8 %) all verified; but the close-top-2 flag never fires by default (F-C5), recall is capped at 50 (F-C7), budget is advisory (F-C8), the citation is always repo-qualified rather than "on ambiguity" (F-C13), the semantic half is off by default and gated by an unvalidated floor (F-C11), non-ASCII queries silently return junk (F-C9), and the index goes permanently stale on hub-side edits (F-C3). |
| **C8** — pin one hub commit; refs validated; tags auto-derived + validated; pinned content returned; ok/stale/broken; exit 0/1/2; `kb doctor --context` parity; `kb diff` for L1/L3 | **met, with two caveats** | 10/10 mutation cases behave, returned bodies are byte-identical to the pin, exit codes and doctor parity are exact, ref validation and ambiguity refusal are correct. Caveats: deleted / renumbered / removed-doc all land in `stale` rather than `broken` (F-C6), and tag derivation is document-granular, not section-granular as C8 words it (F-C15). |
| **C9** — exactly 5 tools; schemas/docstrings byte-identical to golden; stdio + HTTP transports | **partially met** | Exactly 5 tools and a byte-identical golden snapshot (verified two ways, plus `test_mcp_contract.py` green). But `kb_search` — the tool every agent starts with — **hangs forever over stdio** whenever sqlite-vec/numpy is importable (F-C1), which is this repo's own `.venv` and every `[embed]` install. A contract that is byte-perfect but does not respond is not met. |

---

## Top 3 recommendations

1. **Fix F-C1 first — it is the difference between "the MCP server works" and "it doesn't."** Move
   `import sqlite_vec` out of `searchdb._load_vec()` to module scope (or warm it once in
   `mcp.main()` / `create_server()` before the loop starts), and run FastMCP sync tools off the event loop
   (`anyio.to_thread.run_sync`). Add a gate test that calls `kb_search` over real stdio with a hard timeout —
   the existing golden test would have caught this if it did not need an installed wheel to run at all.
2. **Make the index's freshness key cover the content it indexes, and stop treating client errors as
   corruption.** Extend `_repo_fingerprint` to the whole entry directory (`hashsync.build_manifest` already
   computes exactly that, cheaply) or add a commit/mtime component, and make `kb reindex --force` actually
   drop and rebuild (F-C3). Separately, in `query.py:125-132` only `delete_db()` on a `sqlite3.DatabaseError`
   that is *not* `IntegrityError` / "too many SQL variables", use a force-unlink on Windows, cap `tags` at
   the bind limit, and take an `IMMEDIATE` transaction for the cold build so losing the race really is
   idempotent (F-C2, F-C10).
3. **Close the silent-substitution gaps in the agent-facing contract.** Validate `--level` in `cli.py` the
   way `mcp.py:138` already does — returning condensed L2 to someone who asked for `--level L3` is the single
   most damaging behaviour I found in a KB whose premise is "L3 is verbatim" (F-C4). In the same pass: warn
   when `kb_search` truncated at `K_LEG` instead of claiming "every relevant section" (F-C7); warn when a
   query tokenises to nothing meaningful because it was non-ASCII (F-C9); either fix `_ambiguity_note` to
   work on the keyword-only path or stop advertising it in README §7.8 (F-C5); and promote "the cited
   section/document no longer exists" from `stale` to `broken` so CI can block on it (F-C6).
