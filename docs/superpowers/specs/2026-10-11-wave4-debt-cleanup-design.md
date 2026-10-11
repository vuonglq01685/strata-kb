# Wave 4: the debt the review left after §8

**Status:** design, calls made by Claude on the owner's instruction ("chủ yếu dọn cho sạch, bạn tự chốt"), pending owner review
**Source:** §4.1 and §4.2 of
`docs/superpowers/reviews/2026-10-10-full-framework-review.vi.md`, plus the
"Out of scope" sections of the wave 3 specs
(`2026-10-11-source-hygiene-design.md` and the 1.14.1 tooling gate).
§8 of the review is done (1.10–1.16.2), except the sparse-worktree half of
item 6 (F7), which this spec moves to the backlog. Main is at **1.16.2**.

## Why

This wave is cleanup. No user has hit a bug from any of these items. The goal
is a codebase where:

- one rule lives in one place;
- the import graph has no cycle, even through function-level imports;
- `tests/` meets the same bar as `src/` (types and comments).

Success means each item below is either fixed with a guard test, or closed
with a written reason it is not a defect. Nothing is left as "still open"
without a reason.

## Ground rules (every batch)

- **No behaviour change.** Output, messages, exit codes and JSON shapes stay
  the same, except where a section below names a change.
- **Each batch adds a guard test** that fails if the defect comes back.
- **One batch = one PR = one patch release.** Each has a CHANGELOG entry and
  bumps the version in `pyproject.toml` and `uv.lock`.
- Each batch has its own plan in `docs/superpowers/plans/`, written from this
  spec.
- Gates: full suite (`pytest -n auto`) and T0 (`ruff check`,
  `ruff format --check`, `pyright`).

## Batches and order

| Batch | Release | Items | Why this order |
|---|---|---|---|
| **4a** | 1.16.3 | A (duplication) + B (import cycles) | B's fix creates the leaf module that A's dedupe needs. Both are small and touch `src/` only. |
| **4b** | 1.16.4 | C6 (pyright on `tests/`) + C7 (provenance in `tests/`, undated spec refs in `src/`) | Both are a sweep over `tests/`. Doing them together means one pass over each file. Comes after 4a so the tests it touches are final. |
| **4c** | 1.16.5 | C8 (web handlers as module-level functions) | Biggest structural change. It is isolated in `web/`, and the existing web tests are its safety net. |
| backlog | — | C9 (F7 sparse worktree for intake) | Performance, not cleanup. See "Backlog". |

The batches are sequential. Each starts from the main the previous one merged
into.

---

## Batch 4a — duplication and import cycles (1.16.3)

### Measured today

The numbers come from an AST walk over `src/strata_kb`. It ignores
`if TYPE_CHECKING:` blocks. An import of `a.b.c` also counts as an edge to
`a` and `a.b`, because importing it runs their `__init__`. The exception is a
module's own parent packages: `doctor.checks.hub` importing `doctor` is not an
edge, or every package that re-exports its submodules would count as a cycle.

- **Module-level imports only:** no cycles. The `codeingest.core ⇄ extractors`
  cycle the review named is already gone.
- **Function-level imports included:** one strongly connected component of 20
  modules, held together by 13 lazy edges.
- **Three edges are enough to break it.** With them removed, the graph is
  acyclic:
  1. `federation → doctor` (`federation.py:342`, which needs `_fed_tree_digest`)
  2. `kbcontext → query` (`kbcontext.py:344`, which needs `AmbiguousDocError`)
  3. `ticket → lintcore` (`ticket.py:121`, which needs `HTML_COMMENT_RE` and
     `_blank_invisible`)
- **`hub ⇄ searchdb` is not a runtime cycle.** `searchdb` imports `hub` only
  under `TYPE_CHECKING`. `hub.py:282` stays lazy, because it is there for
  startup cost, not to dodge a cycle.

### B. Break the cycle (decision: fix it for real, not just record it)

Three moves. Each old home re-exports the moved name, so every existing
import keeps working and the class `__module__` is the only thing that
changes.

1. **`_fed_tree_digest` and `_FED_TOP_SKIP`** move from
   `doctor/checks/hub.py` into `federation.py`. They need only `hashlib` and
   `Path`.
   - `doctor/checks/hub.py` and `doctor/__init__` import or re-export them
     from there. `tests/test_doctor_checks.py` uses the doctor path.
   - `federation.entry_content_digest` drops its lazy import and the comment
     explaining it.
   - `_ENTRY_SEGMENT_RE` is defined twice in a row, at `doctor/checks/hub.py`
     lines 553 and 556, right above `_FED_TOP_SKIP`. Delete the second copy
     in the same edit.
2. **`AmbiguousDocError`** moves from `query.py` to `errors.py`. `query`
   re-exports it.
   - Today `errors.py` holds only the `KbError` family. `AmbiguousDocError`
     is a `LookupError`, outside that family on purpose. Update the
     `errors.py` docstring to say the module also holds error classes shared
     across modules that are outside `KbError` (Claude's call: a leaf home
     beats a one-class module). `InvalidLevelError` stays in `query`.
   - `kbcontext` imports it from `errors` at module level.
   - The lazy `query → kbcontext` import at `query.py:300` may stay lazy or
     go module-level. Builder's call; both are acyclic.
   - `tests/test_cli_errors.py` allowlists the class as
     `"strata_kb.query.AmbiguousDocError"`. Its sweep keys on
     `cls.__module__`, so re-key the entry to `strata_kb.errors`. The CLI's
     error mapping for the class must not change.
3. **New leaf module `strata_kb/mdmask.py`** holds the Markdown masking
   primitives. It imports nothing but `re`:
   - `FENCE_RE`
   - `HTML_COMMENT_RE`
   - `visible_body`
   - `_visible_text`
   - `_blank_invisible`

   Wiring:
   - `lintcore` imports them from `mdmask` and keeps its names, so
     `lintcore.visible_body` and the rest still work for every `src` caller
     and `tests/test_lintcore.py`.
   - `ticket.export_body` imports `mdmask` at module level. Its lazy import
     goes.
   - `kbcontext.py:57` keeps its own copy of the HTML-comment regex only
     because of the cycle. It switches to `mdmask.HTML_COMMENT_RE`, and the
     comment explaining the copy goes.

**Guard.** Add a test to `tests/test_layering.py`: **no import cycle among
`strata_kb` modules, counting function-level imports and parent packages,
ignoring `TYPE_CHECKING`.**

- It uses the edge rules from "Measured today", including the exclusion for
  a module's own parent packages.
- On failure it prints the cycle.
- Lazy imports kept for startup cost are fine. They add edges, not cycles.
- The scanner in `test_layering.py` already walks the AST. Extend it rather
  than adding a second walker.
- Also add a rule: **`prlint` and `mdmask` import only the standard library,
  plus `strata_kb.mdmask` for prlint.** `prlint`'s docstring promises this,
  but no test checks it today.

### A. Duplication

| # | Item | Decision |
|---|---|---|
| A1 | `_check_required_filled` in `ticketlint.py:185` and `missionlint.py:38` | **Fix.** Add `lintcore.check_required_filled(text, headings, exempt)`. Both linters call it with their own `REQUIRED_*` tuple and `_FILL_EXEMPT`. The message text stays as is. Keep `ticketlint`'s docstring rationale (why presence alone is not enough) on the shared function. |
| A2 | `prlint.py` re-implements fence, comment and section scanning | **Mostly closed as intended.** prlint must stay standard-library only, and `lintcore` pulls in `doctor`, `kbcontext` and pydantic. Its scanner also does things lintcore does not: `~~~` fences, indented fences, unclosed fences, unterminated `<!--`, `#` and `##` headings with tab separators, duplicate counting, CRLF and BOM handling. Switching would change behaviour. **The one identical piece moves:** `prlint._COMMENT` becomes `mdmask.HTML_COMMENT_RE`. Add 2–3 lines to prlint's module docstring saying why it keeps its own scanner. |
| A3 | `startswith("## ")` instead of `mdutils._iter_headings` | **Mostly closed as intended.** Five of the seven code sites are *section-boundary* checks: "any `## ` line ends a section". Those are `mdutils.section_map`, `mdutils.slice_subsection`, `summarize`, `lintcore.section_body` and `ticket.export_body`. Some of them run on ticket headings (`## User Story`), which are not the `## <sid> <title>` grammar. `_iter_headings` parses that grammar, so it is the wrong tool for them. `lintcore.check_duplicate_headings` counts every `## ` line on purpose. The two hits in `codeingest/core.py` are prose in docstrings. **One real re-derivation:** `codeingest/hublag.l3_sections` parses the section id by hand (`line[3:].split(" ", 1)[0]`). It switches to `mdutils.HEADING_RE.match(line)` and `group("sid")`, not fence-aware, matching today. **Named behaviour changes:** (1) a `## ` line that does not match `HEADING_RE` (for example an empty id) no longer starts a section; it becomes body text of the section before it. (2) `## svc.a<TAB>Title` reads as id `svc.a`, not `svc.a\tTitle`. `kb code-ingest` writes neither shape. |
| A4 | Heading regexes in `web/mdrender.py`, `prlint.py`, `planwaves.py` | **Closed: different grammars on purpose.** The four regexes are generic ATX h1–h6 for rendering, h1/h2 with free text for PR sections, `#{2,4} Task N` for plan tasks, and `## <sid>` for KB sections. No change. |
| A5 | Three result types (`prlint.Finding`, `doctor.issues.Issue`, `quality.Finding`) | **Decision: keep three types. Do not unify, do not add a shared protocol.** Their level sets differ (`warning` vs `quality`). Their keys differ (section, code, ref). Two of them back pinned, different `--json` contracts: `kb pr lint` uses `passed`/`findings`, the ticket and mission linters use `pass`/`errors`/`warnings`. A shared type would also pull `doctor` into standard-library-only prlint. A protocol nobody calls through is speculative. Record the reason in each type's docstring, one line each. |

**Tests for A:** the existing linter suites cover A1 and A2 unchanged. Add one
`hublag` test that pins both A3 changes: a `## <id> <title>` heading is read;
a `## ` line with an empty id is kept as body text of the previous section;
a tab-separated title is not part of the id.

### Delivery

One PR, release **1.16.3**. The CHANGELOG lists the three moves, the new
`mdmask` module, the A3 named change, and the decisions closing A2, A4 and A5. The PR also adds one line to item 6
of the review's §8 saying the sparse-worktree half (F7) is deferred to this
spec's backlog.

---

## Batch 4b — `tests/` meets the `src/` bar (1.16.4)

### C6. pyright on `tests/`

Measured today: `pyright tests` in basic mode reports **158 errors** after
`uv sync --extra dev`. Run it with the project venv, for example
`pyright --pythonpath .venv/bin/python tests`. Without the venv about 330
errors show, because pytest and the other imports cannot be found.

| Rule | Errors |
|---|---|
| `reportArgumentType` | 54 |
| `reportOptionalMemberAccess` | 51 |
| `reportOperatorIssue` | 21 |
| `reportAttributeAccessIssue` | 21 |
| `reportGeneralTypeIssues` | 4 |
| other | 7 |

They are spread over 37 files. The largest are `test_usage_ledger.py`
(21), `test_codeingest_scaffold.py` (14) and `test_summarize.py` (13).

**Decision: fix all of them in one pass, then set
`include = ["src", "tests"]`.** Turning the check on per directory or per rule
needs config that has to be unwound later. The errors are mechanical, so a
single sweep is cheaper.

How:

- **Narrow `Optional`s** with `assert x is not None` before use. That is a real
  test assertion, not noise.
- **Missing imports.** `test_check_package.py` imports `check_package` and
  `test_ingest_seam.py` imports `gen_e2e_fixture`, both from `scripts/`. Fix
  them with `extraPaths`, or with whatever path the tests already use at
  runtime. Builder's call.
- **A targeted `# pyright: ignore[<rule>]` with a few words of reason is
  allowed** where the test is right and the checker cannot see it. Never a
  bare `# type: ignore`. Never a file-level or rule-level downgrade. This
  covers:
  - tests that pass a wrong type on purpose, to test validation;
  - platform-only names, such as `subprocess.CREATE_NO_WINDOW` in
    `test_gitio.py`;
  - private stdlib APIs, such as `TarInfo._create_pax_generic_header` in
    `test_intake_core.py`;
  - attributes set on stub modules or fakes, as in `test_parser.py`,
    `test_images.py` and `test_summarize.py`. Prefer typing the fake properly
    when that is a one-line change.
- **If an error exposes a wrong annotation in `src/`, fix the annotation.**
- **If an error exposes a real bug, do not fix it in this batch and do not
  block on it.** Give it a targeted ignore whose reason says
  "real bug, tracked", report it in the PR description, and open a
  follow-up. The release numbering does not move.
- `reportUnusedExpression` in `test_hashsync.py:80` is a warning today. Fix it
  anyway.

**Guard:** T0's `pyright` now covers `tests/`. Update the comment in
`pyproject.toml` that says "tests/ is not checked yet".

### C7. Provenance in `tests/`, undated spec refs in `src/`

Measured today:

- `_PROVENANCE_RE` from `tests/test_source_hygiene.py` matches **680 lines in
  80 test files**. That is more than the 430 the review counted. Some matches
  may be test *data*, such as fixture strings.
- Undated spec references ("spec A", "spec §5", "Stage B") appear on **23 lines
  in `src/`** and **43 in `tests/`**. The current guard misses this shape.

**Rule:** unchanged from 1.16.1. The tag goes and the reason stays. History
becomes a present-tense warning, or goes.

**Guard changes in `tests/test_source_hygiene.py`:**

- Scan `tests/` too, but only **comments and docstrings**, found with
  `tokenize` and the AST. String literals are test data and must not be
  flagged. `src/` keeps its current every-line scan.
- Add the undated-spec shapes to `_PROVENANCE_RE`: `spec [A-Z]\b`,
  `spec §\d`, `Stage [A-Z]\b`.
  - Extend both parametrized pins: shapes it catches, and prose it leaves
    alone.
  - Check that `Stage` does not hit ordinary prose in `src/`. Narrow it if it
    does.
- The guard file is exempt from its own scan, as it is today.

**Named message change:** three `cli.py` help strings carry these tags:

- line 174: "from Stage B on"
- line 245: "(object store — spec B)"
- line 344: "prep for Stage B"

They are reworded to say what they mean, for example "object store". This
changes `kb --help` text and nothing else. Any test that pins the old text is
updated.

### Delivery

One PR, release **1.16.4**, as two commits (C6, then C7) so review can read
them apart.

---

## Batch 4c — web handlers at module level (1.16.5)

### Today

`build_routes` in `web/ui.py` (`ui.py:284` to the end of the file, about 500
lines, 13 nested handlers and helpers),
`web/api.py` and `web/intake_routes.py` define their handlers as closures. The
closures capture `config`, `token`, the store factory, the login limiter and
the proxy count.

The nested handlers cannot be read, tested or imported one at a time, and
`ui.py` is 786 lines, at the soft 800 ceiling.

### Design

- **One frozen dataclass per route module** holds what the closures capture
  today. Name it after what it holds, for example `UIContext` in `ui.py`.
  - The task said one shared `Context`. That is not quite right: the three
    modules capture different things. `intake_routes` needs `IntakeConfig`
    and a store, and `api` needs only `ServerConfig`.
  - Builder's call: if a field set is truly shared, one dataclass may serve
    more than one module.
- **Handlers become module-level functions** that take the context as their
  first argument.
- **`build_routes` binds the context with `functools.partial`.** Starlette's
  `is_async_callable` unwraps `partial`, so sync handlers still run in the
  threadpool and async ones still run on the loop. Prefer this over
  `request.app.state`: it keeps handlers callable without an app and keeps
  `build_routes`' signature unchanged.
- **Pass `name=` to every `Route`.** Starlette names a route after its
  endpoint's `__name__`, and a `partial` has none of its own, so every route
  would be named `"partial"`. Nothing calls `url_for` today, but the names
  should stay what they are.
- **Helpers that read only the context**, such as `_budget`, `_store_for`,
  `_disk_cache_dir` and `_find_asset`, become module-level functions that take
  the context.
- **Mutable state stays exactly where it lives today.** Examples are the login
  limiter's window and any cache. A frozen dataclass may hold a mutable
  object, but no new sharing is introduced.
- `ui.py` may be split into two files if it is still over about 600 lines
  afterwards, for example login and asset handlers into their own module.
  Builder's call.

**Guard:** a test that walks `web/*.py` and fails if any `build_routes`, or
`build_intake_routes`, body contains a nested `def` or `async def`. The
existing web, UI and intake suites are the behaviour guard.

### Delivery

One PR, release **1.16.5**. Pure refactor; there is no behaviour change.

---

## Backlog — C9 / F7 sparse worktree for intake

**Decision: do not build it now.** It is a performance fix, and this wave is
cleanup.

The review measured a cost of 79 ms at 459 files and 257 ms at 1,143 files.
The worst case is a whole-hub write per publish on a 1 GB hub. Nobody runs a
hub that size today.

This section is the record of the open item (4a also points §8 item 6 of the
review here). The trigger:

> build it when a real hub passes about 5,000 files or 200 MB checked out,
> **or** p95 intake publish latency passes 2 s.

The fix is already known: `worktree add --no-checkout` plus
`sparse-checkout set federation/<rid>`, and streaming the upload to a temp
file.

## Non-goals

- No new features or CLI options.
- No unified lint-result type (see A5).
- No rewrite of prlint onto lintcore (see A2).
- No change to which imports are lazy for startup speed.
- No ADR files.
- pyright on `tests-gate/` (6 errors) and `scripts/`. Only `tests/` joins.
- **Other §4.1/§4.2 findings that the owner's wave 4 list does not name**
  stay out of this wave. They are candidates for a later wave, not closed:
  - git calls outside `gitio` (`codeingest/localgit.py`, `publish.py`);
  - 21 direct `yaml.safe_load` sites in 12 modules;
  - business logic left in `cli.py`;
  - about 56 functions over 80 lines (4c fixes only `ui.build_routes`).

## Left to the builder

- Exact names: `UIContext` and the others, and the shared lint helper's
  signature.
- Whether `query → kbcontext` goes module-level after 4a.
- How to resolve `scripts/` imports for pyright.
- Whether `ui.py` is split.
- The wording of each rewritten comment, under the rule above.
