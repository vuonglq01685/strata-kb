# kb-context Tag Integrity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a `kb-context` block's `tags:` line impossible to fabricate — derived from the pinned refs' documents by default, validated against the hub's real tag vocabulary when passed explicitly, and rejected as a lint error when unknown.

**Architecture:** One rule with one home. Three new module-level helpers in `src/center_kb/kbcontext.py` (`tag_vocabulary`, `derive_tags`, `suggest_tags`) define what a valid tag is and what to suggest when one is not; `build_context_block` uses them to derive or validate, `lintcore.check_context_block` uses them to reject, and a new `kb tags` command uses them to list. No new module, no new import edge — `lintcore` already imports `kbcontext`. No MCP tool is added and no tool signature or docstring changes, so the `mcp_tools.json` golden must stay byte-identical.

**Tech Stack:** Python 3, pydantic v2 models, typer CLI, pytest. `difflib` (stdlib) for "did you mean" suggestions. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-22-kb-context-tag-integrity-design.md`

## Global Constraints

- Tags exist **only at document level**: `models.IndexEntry.tags` (`models.py:48`) and `models.FedIndexEntry.tags` (`models.py:70`). `SectionEntry` (`models.py:18-24`) and `Manifest` (`models.py:34-41`) have no `tags` field. Do not add one — that is explicitly out of scope.
- Tag comparison is **case-insensitive** everywhere, because `searchdb.py:350` indexes tags as `{t.strip().lower() for t in doc.tags}`. Output always uses the canonical spelling recorded in `index.yaml`, never the caller's spelling.
- `build_context_block(hub, refs, tags=None)` keeps its exact signature. `mcp.py:160`'s `kb_context_new(refs, tags=None)` keeps its exact signature **and docstring**. `tests/test_mcp.py` and its `mcp_tools.json` golden must pass untouched; a golden break is a defect signal, never a reason to regenerate the golden.
- `tests/test_init.py`'s pinned scaffold-file count and `tests/test_templates.py`'s canon assertions must pass untouched. This plan adds no scaffold file and edits no skill wrapper.
- New capability ships as CLI only. Do not add a sixth MCP tool.
- Only ever `.strip()` a tag. Do not invent further normalisation.
- Every new error message must name the real cause. "KB has no tags at all" and "hub cache is stale" are separate situations from "you made a typo" and must be said separately.
- Python: normal repo style — `from __future__ import annotations`, type hints, deferred imports inside functions where the module already does that.

---

### Task 1: Tag vocabulary and derivation helpers

Pure functions over an already-loaded federation. No caller is changed in this task, so the whole task is additive and cannot break existing behaviour.

**Files:**
- Modify: `src/center_kb/kbcontext.py` (add `import difflib` and `TYPE_CHECKING` import of `FederatedRepo`; add `UnknownTagError`, `tag_vocabulary`, `derive_tags`)
- Test: `tests/test_kbcontext.py`

**Interfaces:**
- Consumes: `federation.load_federation()` → `list[FederatedRepo]`, each with `.meta.repo_id: str` and `.index: models.KBIndex` whose `.docs` are `models.IndexEntry` with `.id: str` and `.tags: list[str]`. `KBRef` with `.doc_id: str`, `.section_id: str`, `.repo_id: str | None`.
- Produces:
  - `class UnknownTagError(KBContextError)`
  - `tag_vocabulary(repos: list[FederatedRepo]) -> dict[str, str]` — lowercase key → canonical spelling
  - `derive_tags(repos: list[FederatedRepo], refs: list[KBRef]) -> list[str]` — canonical spellings, sorted by lowercase key
  - `suggest_tags(tag: str, vocab: dict[str, str]) -> list[str]` — canonical spellings of the nearest vocabulary entries, at most 3. Both Task 2 and Task 3 build their "did you mean" hint from this one function; neither imports `difflib` itself.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_kbcontext.py`:

```python
# --- Task 1: tag vocabulary + derivation ---


def test_tag_vocabulary_is_every_tag_on_the_federation(fed_hub):
    from center_kb.federation import load_federation

    vocab = kbcontext.tag_vocabulary(load_federation(fed_hub / "federation"))

    # fed_hub publishes arinc-kb:arinc-424 (tags: arinc424) and
    # icao-kb:icao-annex-2 (tags: icao, airspace).
    assert vocab == {"arinc424": "arinc424", "icao": "icao", "airspace": "airspace"}


def test_tag_vocabulary_keeps_the_first_spelling_in_dfs_order(fed_hub):
    from center_kb.federation import load_federation

    # 'aaa-kb' sorts before 'icao-kb', so its spelling of the same tag wins:
    # iter_entry_dirs() walks the federation name-ascending.
    make_fed_entry(fed_hub / "federation", "aaa-kb", "aaa-doc", tags=["AIRSPACE"])

    vocab = kbcontext.tag_vocabulary(load_federation(fed_hub / "federation"))

    assert vocab["airspace"] == "AIRSPACE"


def test_tag_vocabulary_skips_blank_tags(fed_hub):
    from center_kb.federation import load_federation

    make_fed_entry(fed_hub / "federation", "blank-kb", "blank-doc", tags=["  ", ""])

    vocab = kbcontext.tag_vocabulary(load_federation(fed_hub / "federation"))

    assert "" not in vocab
    assert len(vocab) == 3


def test_derive_tags_takes_the_tags_of_the_refs_documents(fed_hub):
    from center_kb.federation import load_federation

    repos = load_federation(fed_hub / "federation")
    refs = [kbcontext.parse_ref("arinc-kb:arinc-424 §5.3")]

    assert kbcontext.derive_tags(repos, refs) == ["arinc424"]


def test_derive_tags_unions_across_repos_sorted_by_lowercase_key(fed_hub):
    from center_kb.federation import load_federation

    repos = load_federation(fed_hub / "federation")
    refs = [
        kbcontext.parse_ref("arinc-kb:arinc-424 §5.3"),
        kbcontext.parse_ref("icao-kb:icao-annex-2 §1.1"),
    ]

    assert kbcontext.derive_tags(repos, refs) == ["airspace", "arinc424", "icao"]


def test_derive_tags_is_independent_of_ref_order(fed_hub):
    from center_kb.federation import load_federation

    repos = load_federation(fed_hub / "federation")
    forward = [
        kbcontext.parse_ref("arinc-kb:arinc-424 §5.3"),
        kbcontext.parse_ref("icao-kb:icao-annex-2 §1.1"),
    ]

    assert kbcontext.derive_tags(repos, forward) == kbcontext.derive_tags(
        repos, list(reversed(forward))
    )


def test_derive_tags_dedupes_two_refs_into_one_document(fed_hub):
    from center_kb.federation import load_federation

    repos = load_federation(fed_hub / "federation")
    refs = [
        kbcontext.parse_ref("arinc-kb:arinc-424 §5.3"),
        kbcontext.parse_ref("arinc-kb:arinc-424 §5.3"),
    ]

    assert kbcontext.derive_tags(repos, refs) == ["arinc424"]


def test_derive_tags_ignores_a_document_absent_from_its_repo_index(fed_hub):
    from center_kb import models
    from center_kb.federation import load_federation

    # The document dir and its _manifest.yaml still exist, so the ref itself
    # resolves — but index.yaml no longer lists it, so it contributes no tag
    # and that is not an error.
    models.save_yaml_model(
        fed_hub / "federation" / "arinc-kb" / "index.yaml", models.KBIndex()
    )
    repos = load_federation(fed_hub / "federation")

    assert kbcontext.derive_tags(
        repos, [kbcontext.parse_ref("arinc-kb:arinc-424 §5.3")]
    ) == []


def test_derive_tags_ignores_an_unqualified_ref(fed_hub):
    from center_kb.federation import load_federation

    # A ref that has not been auto-qualified yet has repo_id None and cannot
    # be attributed to a repo. build_context_block always qualifies first;
    # this pins that derive_tags does not guess.
    repos = load_federation(fed_hub / "federation")

    assert kbcontext.derive_tags(repos, [kbcontext.parse_ref("arinc-424 §5.3")]) == []


def test_unknown_tag_error_is_a_kb_context_error():
    assert issubclass(kbcontext.UnknownTagError, KBContextError)


def test_suggest_tags_returns_the_nearest_canonical_spellings():
    vocab = {"airspace": "AirSpace", "arinc424": "arinc424", "icao": "icao"}

    assert kbcontext.suggest_tags("airspce", vocab) == ["AirSpace"]


def test_suggest_tags_is_case_and_whitespace_insensitive():
    vocab = {"airspace": "airspace"}

    assert kbcontext.suggest_tags("  AIRSPACE  ", vocab) == ["airspace"]


def test_suggest_tags_returns_empty_for_nothing_close():
    vocab = {"airspace": "airspace", "icao": "icao"}

    assert kbcontext.suggest_tags("zzzzzzzz", vocab) == []


def test_suggest_tags_on_an_empty_vocabulary_is_empty():
    assert kbcontext.suggest_tags("airspace", {}) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_kbcontext.py -k "tag_vocabulary or derive_tags or unknown_tag or suggest_tags" -v`
Expected: FAIL — `AttributeError: module 'center_kb.kbcontext' has no attribute 'tag_vocabulary'`

- [ ] **Step 3: Add the helpers**

In `src/center_kb/kbcontext.py`, add `import difflib` to the stdlib imports (before `import re`) and extend the `TYPE_CHECKING` block:

```python
if TYPE_CHECKING:
    from center_kb.federation import FederatedRepo
    from center_kb.hub import HubHandle
```

Add the exception next to the existing ones (after `KBRefNotFoundError`):

```python
class UnknownTagError(KBContextError):
    """A tag passed explicitly to `kb context new` is not published by any
    document on the hub federation."""
```

Add both helpers after `parse_ref` and before `_extract_block`:

```python
def tag_vocabulary(repos: list["FederatedRepo"]) -> dict[str, str]:
    """Every tag published anywhere on the federation: lowercase key ->
    canonical spelling as recorded in that repo's `index.yaml`.

    This IS the vocabulary a kb-context block may draw on. Tags live only at
    document level (`models.IndexEntry.tags`) — `SectionEntry` and `Manifest`
    have no tags field — so there is nothing finer to consult.

    Keyed lowercase because `searchdb.py:350` indexes tags as
    `{t.strip().lower() for t in doc.tags}`: casing has no downstream effect,
    so validation must not care about it either. The first spelling
    encountered wins; `federation.iter_entry_dirs()` walks entries in a
    deterministic name-ascending DFS, so two repos spelling one tag
    differently resolve the same way on every run.
    """
    vocab: dict[str, str] = {}
    for repo in repos:
        for doc in repo.index.docs:
            for tag in doc.tags:
                cleaned = tag.strip()
                if cleaned:
                    vocab.setdefault(cleaned.lower(), cleaned)
    return vocab


def derive_tags(repos: list["FederatedRepo"], refs: list[KBRef]) -> list[str]:
    """The tags of the documents these refs pin — the default content of a
    block's `tags:` line, so no agent ever chooses one.

    Granularity is the DOCUMENT, not the section, because that is the only
    level at which tags exist. A ref whose document publishes no tags, whose
    document is absent from its repo's `index.yaml`, or which has not been
    repo-qualified yet contributes nothing, and none of those is an error:
    `build_context_block` has already proved every ref resolves before
    calling this.

    Sorted by lowercase key so the rendered block is byte-stable regardless
    of the order the caller listed `--refs`. A derived block must not change
    because someone reordered their refs.
    """
    by_rid = {repo.meta.repo_id: repo for repo in repos}
    found: dict[str, str] = {}
    for ref in refs:
        repo = by_rid.get(ref.repo_id or "")
        if repo is None:
            continue
        for doc in repo.index.docs:
            if doc.id != ref.doc_id:
                continue
            for tag in doc.tags:
                cleaned = tag.strip()
                if cleaned:
                    found.setdefault(cleaned.lower(), cleaned)
    return [found[key] for key in sorted(found)]


def suggest_tags(tag: str, vocab: dict[str, str]) -> list[str]:
    """Canonical spellings of the vocabulary entries nearest to `tag` — the
    "did you mean" list behind BOTH `kb context new`'s rejection message and
    `kb ticket lint`'s.

    One home, deliberately. Writing the same `difflib` call in `kbcontext`
    and again in `lintcore` would reintroduce the duplicated-rule defect
    this codebase has already shipped three times (see the R5 note in
    `svcnote.py:190-196`) — the same reason the tag rule itself lives in
    exactly one module.
    """
    return [
        vocab[key]
        for key in difflib.get_close_matches(tag.strip().lower(), list(vocab), n=3)
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_kbcontext.py -v`
Expected: PASS — the new tests plus every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add tests/test_kbcontext.py src/center_kb/kbcontext.py
git commit -m "feat: tag vocabulary and derivation helpers in kbcontext"
```

---

### Task 2: Derive and validate tags in `build_context_block`

**Files:**
- Modify: `src/center_kb/kbcontext.py` (add `_unknown_tag_message`; replace the `ctx = KBContext(...)` construction at `kbcontext.py:176-180`)
- Test: `tests/test_kbcontext.py`
- Test: `tests/test_cli_context.py` — one existing test must change; see Step 1.

**Interfaces:**
- Consumes: `tag_vocabulary`, `derive_tags`, `suggest_tags`, `UnknownTagError` from Task 1. `HubHandle` with `.stale: bool` and `.age_seconds: float | None`.
- Produces: `build_context_block(hub, refs, tags=None) -> tuple[str, str | None]` — signature unchanged. Behaviour: derives tags when `tags` is empty or None; validates and canonicalises when non-empty; raises `UnknownTagError` on any unknown tag.

- [ ] **Step 1: Fix the one existing test this change invalidates**

`tests/test_cli_context.py:8-19` passes `--tags "demo,airspace"`. `demo` is a tag in the **local** `fixture_kb` index, not on the `fed_hub` federation, so it will now be rejected — correctly. The test's intent is "explicit tags are rendered", so change the tag set to two tags the federation really publishes, and assert the same shape:

```python
def test_context_new_prints_block_with_head_hash(fed_hub, fixture_kb, run_git):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    result = runner.invoke(
        app,
        ["context", "new", "--refs", "arinc-kb:arinc-424 §5.3",
         "--tags", "icao,airspace", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 0, result.output
    assert "kb-context:" in result.output
    assert f'version: "{hub_head}"' in result.output
    assert "- arinc-kb:arinc-424 §5.3" in result.output
    assert "tags: [icao, airspace]" in result.output
```

Do NOT weaken the assertion to a substring check — the exact rendered line is the contract.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_kbcontext.py`:

```python
# --- Task 2: build_context_block derives and validates ---


def test_build_block_derives_tags_when_none_are_passed(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"],
    )
    assert "tags: [airspace, arinc424, icao]" in block


def test_build_block_derived_tags_do_not_depend_on_ref_order(fed_hub):
    forward, _ = build_context_block(
        HubHandle(root=fed_hub),
        ["arinc-kb:arinc-424 §5.3", "icao-kb:icao-annex-2 §1.1"],
    )
    reverse, _ = build_context_block(
        HubHandle(root=fed_hub),
        ["icao-kb:icao-annex-2 §1.1", "arinc-kb:arinc-424 §5.3"],
    )
    assert parse(forward).tags == parse(reverse).tags


def test_build_block_omits_tags_line_when_nothing_is_derivable(fed_hub):
    from center_kb import models

    models.save_yaml_model(
        fed_hub / "federation" / "arinc-kb" / "index.yaml", models.KBIndex()
    )
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"]
    )
    assert "tags:" not in block
    assert parse(block).tags == []


def test_build_block_explicit_tag_is_rendered_in_canonical_spelling(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["ICAO"]
    )
    assert "tags: [icao]" in block


def test_build_block_explicit_tags_replace_rather_than_extend_derived(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["icao"]
    )
    # 'arinc424' would be derived from arinc-424's own document; an explicit
    # list replaces the derived set outright so a block is either fully
    # derived or fully caller-chosen, never an unattributable mix.
    assert parse(block).tags == ["icao"]


def test_build_block_explicit_tags_dedupe_by_case(fed_hub):
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["icao", "ICAO"]
    )
    assert parse(block).tags == ["icao"]


def test_build_block_unknown_tag_raises(fed_hub):
    with pytest.raises(kbcontext.UnknownTagError) as exc:
        build_context_block(
            HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["ghost-tag"]
        )
    assert "ghost-tag" in str(exc.value)
    assert "kb tags" in str(exc.value)


def test_build_block_unknown_tag_suggests_the_nearest_real_tag(fed_hub):
    with pytest.raises(kbcontext.UnknownTagError) as exc:
        build_context_block(
            HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["airspce"]
        )
    assert "airspace" in str(exc.value)


def test_build_block_empty_vocabulary_names_the_real_cause(fed_hub):
    from center_kb import models

    for rid in ("arinc-kb", "icao-kb"):
        models.save_yaml_model(
            fed_hub / "federation" / rid / "index.yaml", models.KBIndex()
        )
    with pytest.raises(kbcontext.UnknownTagError) as exc:
        build_context_block(
            HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["airspace"]
        )
    message = str(exc.value)
    assert "no tags at all" in message
    assert "drop --tags" in message


def test_build_block_unknown_tag_on_a_stale_hub_says_so(fed_hub):
    handle = HubHandle(root=fed_hub, stale=True, age_seconds=120.0)
    with pytest.raises(kbcontext.UnknownTagError) as exc:
        build_context_block(handle, ["arinc-kb:arinc-424 §5.3"], tags=["ghost-tag"])
    assert "stale" in str(exc.value)


def test_build_block_reports_a_bad_ref_before_a_bad_tag(fed_hub):
    # Ref validation must run first: a broken ref is the more fundamental
    # problem and must not be masked by a tag complaint.
    with pytest.raises(KBRefNotFoundError):
        build_context_block(
            HubHandle(root=fed_hub), ["arinc-424 §9.9"], tags=["ghost-tag"]
        )


def test_build_block_blank_explicit_tags_fall_back_to_derivation(fed_hub):
    # `kb context new` without --tags hands build_context_block an empty
    # list (cli.py:1160), not None — both must derive.
    block, _ = build_context_block(
        HubHandle(root=fed_hub), ["arinc-kb:arinc-424 §5.3"], tags=["", "  "]
    )
    assert parse(block).tags == ["arinc424"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_kbcontext.py tests/test_cli_context.py -v`
Expected: FAIL — the derivation tests fail with `assert 'tags: [...]' in block` (no tags line is produced), and the rejection tests fail with `DID NOT RAISE`.

- [ ] **Step 4: Implement**

In `src/center_kb/kbcontext.py`, add the message builder just above `build_context_block`:

```python
def _unknown_tag_message(
    unknown: list[str], vocab: dict[str, str], hub: "HubHandle"
) -> str:
    """One message naming every unknown tag with its nearest real neighbours,
    plus — stated separately, never implied — the two situations that are not
    a typo at all: a KB that publishes no tags yet, and a hub cache lagging
    behind a tag that really was published."""
    parts = []
    for tag in unknown:
        close = suggest_tags(tag, vocab)
        hint = f" (did you mean {', '.join(close)}?)" if close else ""
        parts.append(f"'{tag}'{hint}")
    msg = "tag not published by any document on the hub federation: " + "; ".join(parts)
    if not vocab:
        msg += (
            " — the KB has no tags at all yet: drop --tags to have them derived "
            "from the pinned refs' documents, or ingest with `kb ingest --tags` first"
        )
    else:
        msg += " — list the real ones with `kb tags`"
    if hub.stale:
        age = f"~{hub.age_seconds:.0f}s" if hub.age_seconds else "unknown age"
        msg += (
            f" [the hub cache is stale ({age}), so a tag published very recently "
            "may be missing from it — this may not be a typo]"
        )
    return msg
```

Then replace the final `ctx = KBContext(...)` block (`kbcontext.py:176-180`) with:

```python
    explicit = [t.strip() for t in (tags or []) if t.strip()]
    if explicit:
        # Caller override: validated, never trusted. Canonical spelling from
        # the index, deduped by lowercase key, caller order preserved.
        vocab = tag_vocabulary(repos)
        unknown = [t for t in explicit if t.lower() not in vocab]
        if unknown:
            raise UnknownTagError(_unknown_tag_message(unknown, vocab, hub))
        block_tags = list(dict.fromkeys(vocab[t.lower()] for t in explicit))
    else:
        # The default: derived from what the refs actually pin, so no agent
        # ever picks a tag.
        block_tags = derive_tags(repos, ref_list)
    ctx = KBContext(version=version, refs=ref_list, tags=block_tags)
    return render(ctx), warning
```

This sits after the ref-validation loop (`kbcontext.py:164-167`) and after `version` / `warning` are computed, both deliberately: a bad ref must be reported as a bad ref, and `derive_tags` needs `ref.repo_id` already auto-qualified by `kbcontext.py:154`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_kbcontext.py tests/test_cli_context.py -v`
Expected: PASS, all tests in both files.

- [ ] **Step 6: Verify the frozen trip-wires did not move**

Run: `python -m pytest tests/test_mcp.py tests/test_ticketlint.py tests/test_missionlint.py -v`
Expected: PASS with no change to `mcp_tools.json`. `tests/test_ticketlint.py` and `tests/test_missionlint.py` both build their golden block with `tags=["airspace"]`, which the federation really publishes, so they must still pass untouched. If `tests/test_mcp.py` fails, a tool signature or docstring was changed — revert that, do not regenerate the golden.

- [ ] **Step 7: Commit**

```bash
git add tests/test_kbcontext.py tests/test_cli_context.py src/center_kb/kbcontext.py
git commit -m "feat: derive kb-context tags from pinned refs, validate explicit ones"
```

---

### Task 3: Reject an unknown tag in ticket and mission lint

**Files:**
- Modify: `src/center_kb/lintcore.py` (add `check_context_tags`, which calls `kbcontext.suggest_tags`; call it from `check_context_block`'s `else` branch at `lintcore.py:414-416`). Add no new stdlib import — `lintcore` must not import `difflib`.
- Test: `tests/test_lintcore.py`
- Test: `tests/test_ticketlint.py`
- Test: `tests/test_missionlint.py`

**Interfaces:**
- Consumes: `kbcontext.tag_vocabulary` and `kbcontext.suggest_tags` from Task 1; `federation.load_federation`; `doctor.Issue(level: Literal["error", "warning"], message: str)`; `KBContext.tags: list[str]`. `lintcore` must NOT import `difflib` — the suggestion rule has one home, in `kbcontext.suggest_tags`.
- Produces: `check_context_tags(ctx: KBContext, hub: HubHandle) -> list[Issue]`, one `error` per unknown tag. `check_context_block` keeps its existing signature `(text, hub) -> tuple[list[Issue], KBContext | None]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_lintcore.py`:

```python
# --- Task 3: kb-context tags must exist on the federation ---


def test_check_context_tags_rejects_a_tag_no_document_publishes(fed_hub):
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["ghost-tag"],
    )

    issues = lintcore.check_context_tags(ctx, HubHandle(root=fed_hub))

    assert [i.level for i in issues] == ["error"]
    assert "ghost-tag" in issues[0].message
    assert "kb tags" in issues[0].message


def test_check_context_tags_accepts_a_published_tag(fed_hub):
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["airspace", "arinc424"],
    )

    assert lintcore.check_context_tags(ctx, HubHandle(root=fed_hub)) == []


def test_check_context_tags_ignores_casing(fed_hub):
    from center_kb.hub import HubHandle

    # searchdb lowercases tags when indexing, so a casing difference has no
    # downstream effect and must not cost a BA an edit.
    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["AirSpace"],
    )

    assert lintcore.check_context_tags(ctx, HubHandle(root=fed_hub)) == []


def test_check_context_tags_suggests_the_nearest_real_tag(fed_hub):
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["airspce"],
    )

    issues = lintcore.check_context_tags(ctx, HubHandle(root=fed_hub))

    assert "airspace" in issues[0].message


def test_check_context_tags_reports_every_unknown_tag(fed_hub):
    from center_kb.hub import HubHandle

    ctx = KBContext(
        version="abc1234",
        refs=[KBRef(doc_id="arinc-424", section_id="5.3", repo_id="arinc-kb")],
        tags=["ghost-one", "airspace", "ghost-two"],
    )

    issues = lintcore.check_context_tags(ctx, HubHandle(root=fed_hub))

    assert len(issues) == 2
    assert "ghost-one" in issues[0].message
    assert "ghost-two" in issues[1].message


def test_check_context_block_skips_the_tag_check_without_a_hub():
    # No hub means no vocabulary, so no conclusion about a tag is possible.
    # The unreachable hub is already its own error; do not pile on.
    text = (
        'kb-context:\n  version: "abc1234"\n  refs:\n'
        "    - arinc-kb:arinc-424 §5.3\n  tags: [ghost-tag]\n"
    )

    issues, ctx = lintcore.check_context_block(text, None)

    assert ctx is not None and ctx.tags == ["ghost-tag"]
    assert all("ghost-tag" not in i.message for i in issues)
```

Append to `tests/test_ticketlint.py`:

```python
def test_fabricated_kb_context_tag_errors(fed_hub: Path, golden_block: str):
    """`ticketlint` and `missionlint` share one `check_context_block`, so this
    proves the tag check reaches the ticket entry point specifically."""
    text = _build_ticket(golden_block.replace("tags: [airspace]", "tags: [ghost-tag]"))

    report = ticketlint.lint(text, _hub(fed_hub))

    assert any("ghost-tag" in e for e in _errors(report)), _errors(report)
```

Append to `tests/test_missionlint.py`:

```python
def test_fabricated_kb_context_tag_errors(fed_hub: Path, golden_block: str):
    """Same check as the ticket suite's, through the mission entry point —
    one shared implementation, two call paths, both proved."""
    text = _build_mission(golden_block.replace("tags: [airspace]", "tags: [ghost-tag]"))

    report = missionlint.lint(text, _hub(fed_hub))

    assert any("ghost-tag" in e for e in _errors(report)), _errors(report)
```

Before running, confirm the two suite-local helpers you are calling exist with these exact names and read their signatures: `_build_ticket`, `_errors`, `_hub` in `tests/test_ticketlint.py`; `_build_mission`, `_errors`, `_hub` and the `missionlint.lint` call form in `tests/test_missionlint.py` (see its existing `test_mission_id_extracted_from_body`, which calls `missionlint.lint(_build_mission(golden_block), None)`). Match the local call convention exactly — pass `_hub(fed_hub)` where the ticket suite does, and pass the hub positionally the way the mission suite's own hub-using tests do.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_lintcore.py tests/test_ticketlint.py::test_fabricated_kb_context_tag_errors tests/test_missionlint.py::test_fabricated_kb_context_tag_errors -v`
Expected: FAIL — `AttributeError: module 'center_kb.lintcore' has no attribute 'check_context_tags'` for the lintcore tests, and the two entry-point tests fail their `assert any(...)`.

- [ ] **Step 3: Implement**

In `src/center_kb/lintcore.py`, add the new function immediately above `check_context_block`. Add no new stdlib import: the suggestion rule is `kbcontext.suggest_tags`, and `kbcontext` is already imported at `lintcore.py:15`.

```python
def check_context_tags(ctx: KBContext, hub: "HubHandle") -> list[Issue]:
    """Every tag in the block must be one some document on the federation
    actually publishes. An invented tag makes a ticket look grounded in a
    vocabulary it is not grounded in, and drifts the words used to describe
    KB content away from the words the KB indexes.

    Compared by lowercase key only: `searchdb.py:350` indexes tags as
    `{t.strip().lower() for t in doc.tags}`, so a casing difference has no
    downstream effect and is not worth an edit.

    Not called when the hub is unreachable — without a vocabulary there is
    nothing to conclude, and `check_context_block` already reports the
    unreachable hub as its own error.
    """
    from center_kb.federation import load_federation

    vocab = kbcontext.tag_vocabulary(load_federation(hub.federation_dir))
    issues: list[Issue] = []
    for tag in ctx.tags:
        key = tag.strip().lower()
        if key in vocab:
            continue
        close = kbcontext.suggest_tags(tag, vocab)
        hint = f" (did you mean {', '.join(close)}?)" if close else ""
        issues.append(
            Issue(
                "error",
                f"kb-context tag '{tag}' is not published by any document on "
                f"the hub federation{hint} — list the real ones with `kb tags`. "
                "Fix by deleting the tag from the block; never by re-running "
                "`kb context new`, which would rewrite the pinned version and "
                "falsify when the ticket was grounded",
            )
        )
    return issues
```

Then extend `check_context_block`'s `else` branch (`lintcore.py:414-416`) to:

```python
    else:
        ctx_issues, _results = check_context(text, hub)
        issues += ctx_issues
        issues += check_context_tags(ctx, hub)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_lintcore.py tests/test_ticketlint.py tests/test_missionlint.py -v`
Expected: PASS — the new tests plus every pre-existing test in all three files.

- [ ] **Step 5: Commit**

```bash
git add tests/test_lintcore.py tests/test_ticketlint.py tests/test_missionlint.py src/center_kb/lintcore.py
git commit -m "feat: kb ticket/mission lint rejects an unpublished kb-context tag"
```

---

### Task 4: `kb tags`

The escape hatch the error messages point at. A BA whose tag was just rejected needs to see the real vocabulary.

**Files:**
- Modify: `src/center_kb/cli.py` (new top-level command, inserted immediately before the `resolve` command at `cli.py:1173`)
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `_hub_or_exit(hub_flag: str, kb_dir: Path) -> HubHandle` (`cli.py:362`); `kbcontext.tag_vocabulary`; `federation.load_federation`.
- Produces: CLI command `kb tags [--kb-dir <path>] [--hub <spec>]`. Exits 0 always when the hub resolves — one canonical tag per line sorted by lowercase key, or one guidance line when the vocabulary is empty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`, which already defines `runner = CliRunner()` and imports `app` from `center_kb.cli` at module level:

```python
def test_tags_lists_the_federation_vocabulary(fed_hub, fixture_kb):
    result = runner.invoke(
        app, ["tags", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0, result.output
    assert result.output.split() == ["airspace", "arinc424", "icao"]


def test_tags_on_a_kb_with_no_tags_exits_zero_with_guidance(fed_hub, fixture_kb):
    from center_kb import models

    for rid in ("arinc-kb", "icao-kb"):
        models.save_yaml_model(
            fed_hub / "federation" / rid / "index.yaml", models.KBIndex()
        )
    result = runner.invoke(
        app, ["tags", "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)]
    )
    assert result.exit_code == 0, result.output
    assert "no tags" in result.output
    assert "kb ingest --tags" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -k tags -v`
Expected: FAIL with exit code 2 — typer reports `No such command 'tags'`.

- [ ] **Step 3: Implement**

Insert into `src/center_kb/cli.py`, immediately before `@app.command()` / `def resolve(...)` at `cli.py:1173`:

```python
@app.command()
def tags(
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = don't use)"
    ),
) -> None:
    """List every tag published on the hub federation — the vocabulary a
    kb-context block may use."""
    from center_kb import kbcontext
    from center_kb.federation import load_federation

    handle = _hub_or_exit(hub, kb_dir)
    vocab = kbcontext.tag_vocabulary(load_federation(handle.federation_dir))
    if not vocab:
        # An empty vocabulary is a valid state, not a failure: a KB whose
        # documents were ingested without --tags simply has none yet.
        typer.echo(
            "no tags published on the hub yet — ingest with `kb ingest --tags` "
            "to create some"
        )
        return
    for key in sorted(vocab):
        typer.echo(vocab[key])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS, including every pre-existing test in the file.

- [ ] **Step 5: Commit**

```bash
git add tests/test_cli.py src/center_kb/cli.py
git commit -m "feat: kb tags lists the federation tag vocabulary"
```

---

### Task 5: Migration guidance in the scaffolded QUICKSTARTs

Making an unknown tag an error breaks any BA repo that upgrades before its backlog is clean. That is a deliberate choice from the spec, so it ships with the guidance that makes it survivable.

Assume this ships in **v0.19.0** — a behaviour break is a minor bump, and `pyproject.toml` currently reads `0.18.0`. Do not bump `pyproject.toml` in this task; the release step owns that. If the release version turns out different, the version string in these notes is the only thing to correct.

The spec asks for a release-notes entry as well as QUICKSTART guidance. This repository has no `CHANGELOG.md` — its release notes ARE the versioned "Upgrading an existing BA repo" paragraphs in the scaffolded QUICKSTARTs (see the two `v0.13.0` paragraphs already there). So the QUICKSTART note below satisfies both, and no new file is created.

**Files:**
- Modify: `src/center_kb/templates/init/QUICKSTART-ba.md` (upgrade note after the v0.13.0 paragraphs ending at line 175; `kb tags` in the CLI reference after line 183)
- Modify: `src/center_kb/templates/init/QUICKSTART-child.md` (`kb tags` in the CLI reference after line 84)
- Modify: `src/center_kb/templates/init/QUICKSTART-hub.md` (`kb tags` in the CLI reference, next to the `kb query` line at line 89)
- Test: `tests/test_init.py`

**Interfaces:**
- Consumes: the `kb tags` command from Task 4 and the lint error from Task 3 — both must already exist, or the documentation describes something that is not there.
- Produces: no code interface. Scaffolded prose only.

`QUICKSTART-dev.md` is deliberately untouched: a dev repo resolves blocks, it never authors tags.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_init.py`, following the file's existing pattern of `init_repo(tmp_path, kind)` then reading the scaffolded file (see `test_quickstart_ba_content` at line 771 for the exact helper call and the scaffolded filename `QUICKSTART-BA.md`):

```python
def test_quickstart_ba_documents_the_tag_lint_break(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = " ".join((tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8").split())
    # The break itself, the fix, and the lookup — all three, or a BA hits a
    # red lint with no way out.
    assert "v0.19.0 makes an unknown `kb-context` tag a lint error" in text
    assert "delete the tag from the block" in text
    assert "never re-run `kb context new`" in text
    assert "kb tags" in text


def test_quickstart_ba_documents_that_tags_are_derived(tmp_path: Path):
    init_repo(tmp_path, "ba")
    text = " ".join((tmp_path / "QUICKSTART-BA.md").read_text(encoding="utf-8").split())
    assert "tags are derived from the documents your refs pin" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_init.py -k "tag_lint_break or tags_are_derived" -v`
Expected: FAIL on the first assertion — the phrase is not in the template yet.

- [ ] **Step 3: Write the guidance**

In `src/center_kb/templates/init/QUICKSTART-ba.md`, insert after the second v0.13.0 paragraph (the one ending "...move the real heading out of the code fence.", line 175) and before `## CLI reference`:

```markdown
v0.19.0 makes an unknown `kb-context` tag a lint error. A block's tags are
derived from the documents your refs pin — `kb context new` fills them in
itself, so you never choose one. Passing `--tags` still works, but every tag
must already be published by some document on the hub; run `kb tags` to see
the real list.

If lint now rejects a ticket or mission that used to pass, **delete the tag
from the block's `tags:` line** — tags are read by nothing, so removing one
is safe, and removing the last one drops the line entirely, which parses
fine. **Never re-run `kb context new`** to fix it: that rewrites `version:`
to today's HEAD and falsifies when the ticket was grounded. Leave `refs:`
and `version:` exactly as they are.
```

Add to that file's CLI reference, after the `kb mission lint` entry (line 182-183):

```markdown
- `kb tags [--hub <url>]` — list every tag published on the hub, i.e. the
  tags a `kb-context` block may carry
```

In `src/center_kb/templates/init/QUICKSTART-child.md`, add after the `kb ticket lint` entry (line 83-84):

```markdown
- `kb tags` — list every tag published on the hub federation
```

In `src/center_kb/templates/init/QUICKSTART-hub.md`, add immediately after the `kb query` entry (line 89):

```markdown
- `kb tags` — list every tag published on the hub federation
```

Note the exact phrase `never re-run \`kb context new\`` must appear verbatim — the test pins it, because that is the instruction that stops someone destroying a ticket's provenance while "fixing" a tag.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_init.py -v`
Expected: PASS — the two new tests plus every pre-existing test, including the pinned scaffold-file count (no file was added) and `test_quickstart_and_instructions_have_cli_reference` (which asserts presence, never absence, so extra entries are fine).

- [ ] **Step 5: Run the whole suite**

Run: `python -m pytest -q`
Expected: PASS. In particular `tests/test_templates.py` (skill-wrapper canon) and `tests/test_mcp.py` (`mcp_tools.json` golden) must pass untouched.

- [ ] **Step 6: Commit**

```bash
git add tests/test_init.py src/center_kb/templates/init/QUICKSTART-ba.md src/center_kb/templates/init/QUICKSTART-child.md src/center_kb/templates/init/QUICKSTART-hub.md
git commit -m "docs: document the kb-context tag lint break and kb tags"
```

---

### Task 6: Scan the existing BA backlog (operations, no code)

This is item A3. It has no test cycle — its deliverable is a clean lint run over real content, in a different repository.

**Files:**
- Modify: none in this repository. Files edited are tickets and missions in the BA repo being scanned.

**Interfaces:**
- Consumes: the installed build from Tasks 1–5. Running this against an older build finds nothing, because the old lint cannot see a bad tag.
- Produces: a clean `kb ticket lint` / `kb mission lint` run over that repo, committed there.

- [ ] **Step 1: Get the target**

The operator names the BA repository to scan. If you were not given a path, stop and ask for it — do not guess, and do not skip the task.

Set `BA_REPO` to that path and `HUB` to the hub URL or path that repo's `.kb/config.yaml` already uses (or pass `--hub` explicitly).

- [ ] **Step 2: Install this branch's build into the environment that repo uses**

```bash
python -m pip install -e .
kb tags --hub "$HUB"
```

Expected: the tag vocabulary prints. If `kb tags` is not a known command, the wrong build is installed — fix that before scanning, or the scan is meaningless.

- [ ] **Step 3: Scan every ticket and mission**

```bash
cd "$BA_REPO"
for f in tickets/*.md; do echo "== $f"; kb ticket lint "$f" --hub "$HUB"; done
for f in missions/*.md; do echo "== $f"; kb mission lint "$f" --hub "$HUB"; done
```

Collect every line containing `is not published by any document on the hub federation`. That list is the whole job.

- [ ] **Step 4: Fix each unknown tag**

For each reported file, edit the `kb-context` block's `tags:` line and delete the unknown tag. Keep the tags that are real.

Do not touch `refs:`, `version:`, or `hub_version:`. Do not re-run `kb context new` — it would rewrite `version:` to today's HEAD and falsify when the ticket was grounded.

If a block's last tag is removed, delete the whole `tags:` line; tags are optional (`kbcontext.py:99-105`) and the block still parses.

- [ ] **Step 5: Re-run to verify the scan is clean**

Run Step 3's two loops again.
Expected: no line mentioning `is not published by any document on the hub federation`. Pre-existing warnings and errors unrelated to tags may remain — those are that repo's own backlog, not this task's scope; report them, do not fix them here.

- [ ] **Step 6: Commit in the BA repo**

```bash
cd "$BA_REPO"
git add tickets missions
git commit -m "fix: remove kb-context tags that no hub document publishes"
```

- [ ] **Step 7: Report**

State plainly: how many files were scanned, how many carried an unknown tag, which tags were removed, and any unrelated lint findings left in place.

---

## Verification before claiming done

Run and paste the output — do not summarise:

```bash
python -m pytest -q
```

Expected: all tests pass. Specifically confirm:
- `tests/test_mcp.py` passed and `git status` shows `mcp_tools.json` unmodified.
- `tests/test_templates.py` passed with no canon edit.
- `tests/test_init.py` passed with no change to its pinned scaffold-file count.
