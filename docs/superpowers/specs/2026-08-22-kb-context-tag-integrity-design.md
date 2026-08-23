# kb-context tag integrity — design

Date: 2026-08-22
Scope: roadmap batch 1 (items A1, A2, A3, A5). Items A4 (skill text) and
everything in batches B–E are explicitly out of scope.

## Problem

`kb context new` writes a `kb-context:` block into a ticket or mission.
The block's `refs:` are validated strictly — `build_context_block()`
(`src/center_kb/kbcontext.py:139-167`) loads the hub federation, auto-qualifies
each ref's `repo_id`, checks that the document's `_manifest.yaml` exists and
that the section id is present in it, and raises `KBRefNotFoundError`
otherwise.

Its `tags:` are not validated at all. `kbcontext.py:176-180` takes whatever the
caller passed, applies `.strip()`, drops empties, and renders the result
verbatim. `lintcore.check_context_block()` (`src/center_kb/lintcore.py:393-418`)
parses the block, resolves refs, cross-checks inline citations — and never looks
at tags. The `ba-ticket-author` skill tells the BA to pass tags freely
(step 5: "passing exactly those confirmed refs (+ tags)") without saying where a
tag may come from.

So an agent can invent a tag and nothing stops it.

### Actual blast radius

Narrower than a first reading suggests, and worth stating precisely so the fix
is justified for the right reason.

`KBContext.tags` is a **write-only field**. The only code in `src/center_kb`
that reads it is the renderer, `kbcontext.py:114-115`. `kb resolve`,
`kb ticket lint`, `kb mission lint`, and the MCP `kb_resolve` tool never touch
it. Search's tag filter takes its tags from the query-time `--tags` option
(`cli.py:828` → `query.search(..., tags=tag_list)` → `searchdb.fts_search`),
not from any ticket's block.

The real harm is therefore:

1. **False grounding signal.** A block carrying tags that exist nowhere in the
   KB makes a ticket look grounded in a vocabulary it is not grounded in. A
   reviewer reading the block cannot tell a real tag from an invented one.
2. **Vocabulary drift.** Every new ticket is free to mint terms, so the set of
   words used to describe KB content diverges from the set of words the KB
   actually indexes.
3. **A latent trap.** The moment anything consumes these tags — a human copying
   them into `kb query --tags`, or any future feature reading the block — an
   invented tag silently returns nothing.

Not claimed: that search is broken today. It is not.

### Constraints established before design

- `SectionEntry` (`models.py:18-24`) has **no** `tags` field. `Manifest`
  (`models.py:34-41`) has none either. Tags exist only at document level:
  `IndexEntry.tags` (`models.py:48`, in a repo's `.kb/index.yaml`) and
  `FedIndexEntry.tags` (`models.py:70`, in the hub's aggregate
  `federation/index.yaml`, built from the former by
  `federation.py:148-162`). Tags are set at ingest time — `kb ingest --tags`
  (`cli.py:393`), `kb code-ingest --tags` (`cli.py:652`).
- Consequently a derived tag's granularity is the **document** of a pinned ref,
  never the section.
- `load_federation()` (`federation.py:116-137`) already returns each
  `FederatedRepo` with its full `index: KBIndex`, and `build_context_block()`
  already calls it at `kbcontext.py:139`. The tags needed for both derivation
  and validation are therefore already in hand — no new I/O.
- Search lowercases tags when indexing:
  `searchdb.py:350` builds `{t.strip().lower() for t in doc.tags}`. Tag
  matching is case-insensitive downstream, so validation must be too.
- The five MCP tools' signatures and docstrings are frozen; the
  `mcp_tools.json` golden must stay byte-identical. New capability ships as
  CLI only.

## Decisions

| Question | Decision |
|---|---|
| What are `kb-context` tags? | Auto-derived from the pinned refs' documents. The agent never chooses them. |
| Explicit `--tags`? | Still accepted, still validated — and it **replaces** the derived set rather than adding to it. |
| Where does the tag rule live? | Module-level helpers in `kbcontext.py`. One definition, three callers. |
| Lint severity for an unknown tag? | `error`, in this batch. No warning grace period. |
| `kb tags` CLI? | In this batch. Plain vocabulary listing, no per-doc breakdown. |
| Backlog scan (A3)? | In this batch, as an operations step against a real BA repo. |

`--tags` replacing rather than unioning the derived set keeps a block
interpretable: it is either fully derived or fully caller-chosen, never a mix
whose provenance cannot be recovered by reading it.

Placing the rule inside `kbcontext.py` rather than a new module avoids a new
import edge — `lintcore` already imports `kbcontext` — and keeps a 182-line
file cohesive at ~220 lines. The rule must have exactly one home: this codebase
has shipped the same duplicated-rule defect three times (see the Ruling R5 note
in `svcnote.py:190-196`), so deriving in one module and validating in another is
rejected outright.

## The tag rule

**Vocabulary.** The union of `IndexEntry.tags` across every repo returned by
`load_federation()`. Held as a `dict[str, str]` mapping lowercase key to
canonical spelling, so validation compares case-insensitively while output keeps
the spelling recorded in `index.yaml`. When two repos spell the same tag
differently (`ARINC424` vs `arinc424`), the first one encountered wins;
`iter_entry_dirs()` (`federation.py:50-90`) is already a deterministic
name-ascending DFS, so this is stable across runs.

**Derivation.** For each ref, after its `repo_id` has been auto-qualified: look
up the `IndexEntry` whose `id` equals the ref's `doc_id` in that repo's index,
and union its tags. Deduplicate by lowercase key, keep canonical spelling, and
**sort by lowercase key**. The block is derived data, so its bytes must not
depend on the order the caller happened to list `--refs`.

**Documents that contribute nothing.** A document with no tags, or one that has
a `_manifest.yaml` but no entry in its repo's `index.yaml`, contributes zero
tags and is not an error — ref validation has already proven the ref resolves,
and a KB ingested without `--tags` is a legitimate state. If no ref contributes
anything, the block omits the `tags:` line entirely; `render()`
(`kbcontext.py:114-115`) already skips an empty list.

**Explicit tags.** Every tag the caller passes must be in the vocabulary,
compared by lowercase key. The block records the canonical spelling, not the
caller's. An unknown tag raises `UnknownTagError`, a subclass of
`KBContextError`, carrying the nearest matches from
`difflib.get_close_matches` against the vocabulary keys.

**Empty vocabulary plus explicit tags.** Fails closed — every tag is unknown, so
the call errors. The message must name the real cause rather than implying a
typo: the KB has no tags at all, so either drop `--tags` and let them be
derived, or ingest with `--tags` first.

**Stale hub.** No new behaviour: `build_context_block()` already returns a
stale-cache warning (`kbcontext.py:170-175`). But an unknown-tag error raised
while `hub.stale` is set appends a line naming the staleness and its age, so a
BA is not sent hunting for a typo when the real cause is a lagging cache.

**Normalisation.** `.strip()` and drop empties — exactly what the code does
today. No further normalisation is invented; `searchdb.py:350` does no more than
`strip().lower()`, and the two must not disagree.

## A1 — derive and validate in `build_context_block()`

Two new module-level functions in `kbcontext.py`:

```python
def tag_vocabulary(repos: list[FederatedRepo]) -> dict[str, str]:
    """lowercase key -> canonical spelling, first spelling wins in DFS order."""

def derive_tags(repos: list[FederatedRepo], refs: list[KBRef]) -> list[str]:
    """Canonical tags of the refs' documents, deduped by key, sorted by key."""
```

Both take an already-loaded `repos` list rather than loading the federation
themselves. Loading twice inside one call would be wasted I/O and would let two
reads observe two different states; each caller loads once and passes it down.

`build_context_block()` changes only its final block, which currently reads:

```python
ctx = KBContext(
    version=version,
    refs=ref_list,
    tags=[t.strip() for t in (tags or []) if t.strip()],
)
```

The replacement, placed after the ref-validation loop and after the `version` /
`warning` computation:

- If the caller passed any non-empty tag: validate each against
  `tag_vocabulary(repos)`; on any unknown tag raise `UnknownTagError` listing
  every unknown tag with its suggestions, plus the stale-hub line when
  applicable; otherwise use the canonical spellings.
- Otherwise: use `derive_tags(repos, ref_list)`.

It must sit after the ref loop for two reasons: a bad ref should be reported as
a bad ref, not as a tag problem; and `derive_tags` depends on `ref.repo_id`
having been auto-qualified at `kbcontext.py:154`.

Because `UnknownTagError` subclasses `KBContextError`, both existing call sites
already handle it — `cli.py:1165` catches `(kbcontext.KBContextError,
gitio.GitError)`, and `mcp.py:171` wraps the same call. No call site changes.

The signature `build_context_block(hub, refs, tags=None)` is unchanged, and the
MCP tool `kb_context_new(refs, tags=None)` (`mcp.py:160`) keeps its signature
and docstring, so the `mcp_tools.json` golden stays byte-identical.

## A2 — reject unknown tags in lint

`lintcore.check_context_block()` gains a tag check inside its existing
`else:` branch (the `hub is not None` path, `lintcore.py:414-416`):

- Load the federation, build the vocabulary, and emit one
  `Issue("error", ...)` per tag in `ctx.tags` whose lowercase key is absent —
  each with `difflib` suggestions.
- Comparison is by lowercase key only. A ticket written as `ARINC424` against
  an index recording `arinc424` passes; search lowercases anyway, so there is no
  real defect to report and no reason to make a BA edit casing.

When `hub is None` the function already emits `"hub unreachable — cannot resolve
kb-context refs without a hub"`; the tag check is skipped there, because without
a vocabulary no conclusion about a tag is possible.

`ticketlint.py:247` and `missionlint.py:334` both call this one function, so a
single change covers `kb ticket lint` and `kb mission lint`.

**Fail-open on an empty vocabulary.** `check_context_tags` returns no issues
at all when `tag_vocabulary()` comes back empty (`if not vocab: return []`),
even though every tag in the block is then, strictly, "not in the
vocabulary." This is deliberate, not an oversight: an empty vocabulary means
the federation mirror is absent or unreadable, not that every tag was
invented. `federation.load_federation()` returns no repos at all when
`federation/` is missing, and silently skips (`logger.warning` only) any
repo whose `index.yaml` fails to parse (`federation.py:69-129`) — so a
completely empty vocabulary is at least as likely to be a broken or absent
mirror as a genuinely tagless KB. The trade-off this accepts: a federation
that is genuinely, correctly tagless lets a fabricated tag pass lint
uncaught, because there is nothing to validate against. This mirrors the
epistemic position the `hub is None` branch already takes one step earlier —
without a vocabulary, no conclusion about any individual tag is possible.

## A5 — `kb tags`

```
kb tags [--kb-dir .kb] [--hub <spec>]
```

A top-level command beside `kb query`, not a subgroup. It resolves the hub with
the existing `_hub_or_exit(hub, kb_dir)` helper, loads the federation, builds
the vocabulary, and prints one canonical tag per line sorted by lowercase key.

An empty vocabulary prints a single line saying the KB has no tags yet and
suggesting `kb ingest --tags`, and exits 0 — empty is a valid state, not a
failure.

No sixth MCP tool. An agent that hits an unknown-tag error already receives
suggestions in the error itself; `kb tags` exists for a human.

## A3 — scan the existing backlog

An operations step, not code. The operator names the BA repository to scan at
execution time.

Order matters: ship A1, A2 and A5 first and install the build, because the old
lint cannot see a bad tag. Then run `kb ticket lint` over every file in that
repo's `tickets/` and `kb mission lint` over `missions/`, collect the unknown
tags reported, fix them, and commit that repo.

**How to fix an old ticket:** delete the offending tag from the block's `tags:`
line by hand. Do **not** re-run `kb context new`. Re-running rewrites
`version:` to today's HEAD, which falsifies the record — the block states the
commit at which the BA grounded the ticket, and changing it is a lie about when
grounding happened. Refs and the version pin must not be touched. Tags are read
by nothing, so removing one is safe. Removing a ticket's last tag drops the
`tags:` line entirely, which parses fine: tags are optional
(`kbcontext.py:99-105`).

## Tests

Test-driven: each test is written failing first, against the existing files.

`tests/test_kbcontext.py`
- Derivation: one ref; several refs in one document; refs spanning two repos; a
  document with no tags; a document with a `_manifest.yaml` but no `index.yaml`
  entry; and the same refs passed in reversed order producing a byte-identical
  block.
- Explicit tags: a valid tag rendered in the index's canonical spelling rather
  than the caller's; an unknown tag raising `UnknownTagError` with the expected
  suggestion; an empty vocabulary plus explicit tags producing the
  "KB has no tags" message; `hub.stale` adding the staleness line to the error.
- Vocabulary: two repos spelling one tag differently resolving to the DFS-first
  canonical form.

`tests/test_lintcore.py`
- An unknown tag yields `Issue("error", ...)`; a derived tag yields no issue;
  `hub=None` yields no tag issue; a case-mismatched tag yields no issue.

`tests/test_ticketlint.py` and `tests/test_missionlint.py`
- One test each proving the error surfaces through both entry points. One shared
  implementation, two call paths — both must be demonstrated.

`tests/test_cli_context.py`
- Not added as new cases. Both behaviours are covered indirectly instead:
  `cli.py:1164-1166` catches `(kbcontext.KBContextError, gitio.GitError)` and
  reports exit code 1 with the message in `result.output`; `UnknownTagError`
  is a `KBContextError` subclass, so it hits the exact same `except` clause
  that `test_context_new_rejects_unresolvable_ref` already exercises via
  `KBRefNotFoundError`. A CLI test for "unknown `--tags` exits 1" would prove
  nothing about the CLI layer beyond what that test already proves — the
  derivation and validation logic itself is `test_kbcontext.py`'s job. The
  CLI error lands on **stdout**, not stderr: `cli.py:1165` calls
  `typer.secho(str(exc), fg=typer.colors.RED)` without `err=True`.

`tests/test_cli.py`
- `kb tags` prints the vocabulary in sorted order; a tagless KB exits 0 with the
  guidance line.

## Trip-wires expected NOT to move

- `tests/test_mcp.py` and its `mcp_tools.json` golden must pass untouched. A
  golden break means the implementation wrongly altered a tool signature or
  docstring — it is a defect signal, never a reason to regenerate the golden.
- `tests/test_init.py`'s pinned scaffold-file count and
  `tests/test_templates.py`'s canon assertions must pass untouched. This batch
  adds no scaffold file and edits no skill text; A4 is deferred to the shared
  template batch.

## Risk: this batch breaks the compatibility contract

Making an unknown tag an `error` rather than a `warning` means any BA repo that
upgrades the package before its backlog is scanned will fail both
`kb ticket lint` and `kb mission lint` immediately. This is a deliberate choice,
taken with the trade-off stated, not an oversight.

**A grading asymmetry this design never argued for.** A tag legitimately
derived at pin time, then later removed from the hub (the document was
re-ingested without it, or the whole document was withdrawn), becomes a hard
`error` under this design. The analogous drift on the `refs:` side —
a pinned section whose L2 content has since changed — is graded a `warning`
(`resolve.py:100-105` classifies it "stale", and `doctor.py:193` renders
"stale" as a warning, never an error). The same historical fact — "this was
true when the BA pinned it, it is not true now" — is graded two different
ways depending on which field drifted. This is accepted for now because a
fabricated tag and a legitimately-withdrawn tag are indistinguishable after
the fact: nothing in a `kb-context` block records which one happened, so
treating both as an error is the only sound default. The cost this accepts
is real: the prescribed remedy for a withdrawn tag is the same as for a
fabricated one — edit the block and remove it — which mutates the very
historical record `version:` exists to protect, for a tag that was never
wrong when it was written.

Mitigation, shipped with the same change:

- A release-notes entry stating that an unknown `kb-context` tag is now a lint
  error.
- A QUICKSTART paragraph covering three things: the new error, the fix (delete
  the unknown tag by hand; never re-pin), and `kb tags` for looking up what is
  valid.

## Out of scope

- A4 — `ba-ticket-author` and `ba-mission-plan` skill text. Deferred to the
  shared template batch, where the 4-wrapper and canon cost is paid once.
- Any change to a document's own tags, to `kb ingest --tags`, or to how search
  filters by tag.
- Giving `SectionEntry` a `tags` field. Section-level tags would make derivation
  precise instead of document-coarse, but that is a KB-model change with its own
  ingest, publish, and federation consequences — a separate design.
- Batches B through E.
