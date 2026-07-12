# MCP Citation Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an AI assistant chatting with a BA (Claude Desktop/Code, GitHub Copilot — no terminal access) pin a `kb-context` citation block directly via MCP, and nudge that assistant to surface every `kb_search` candidate (not just the top hit) to the BA before citing.

**Architecture:** Extract the existing `kb context new` CLI command's pure validate/pin/render logic into a shared function in `kbcontext.py`, reused by both the CLI (regression-only refactor) and a new 4th MCP tool `kb_context_new`. Add a presentation-layer-only "scores are close" annotation to the existing `kb_search` MCP tool (no change to the underlying `search()` ranking). Enforcement of "show the BA all candidates before citing" is carried entirely by MCP tool docstrings — the only artifact every MCP client (including Copilot, which has no Claude Skills support) reads before calling a tool.

**Tech Stack:** Python 3.13, `mcp` SDK v1 (`FastMCP`), `typer` (CLI), `pytest` + `mcp.shared.memory.create_connected_server_and_client_session` (in-memory MCP test client).

Reference design: `docs/superpowers/specs/2026-07-12-mcp-citation-confirmation-design.md`.

## Global Constraints

- MCP tool functions must never raise across the MCP boundary — always return a descriptive error string, matching the existing pattern in `kb_get_section`/`kb_resolve` (`src/center_kb/mcp.py`).
- `.kb/`-dirty and "ref not found" warnings must go through the shared `kbcontext.build_context_block()` function so CLI and MCP present the same underlying information (only *where* it's surfaced differs — CLI stderr vs. inline MCP text).
- No change to `search()`'s signature or return type in `src/center_kb/query.py` — the ambiguity annotation is computed by the `kb_search` MCP tool body only.
- Every existing test in `tests/test_cli_context.py`, `tests/test_cli_hub.py`, `tests/test_kbcontext.py`, and `tests/test_mcp.py` must still pass unmodified (except the one intentional update: `test_lists_exactly_three_tools` → `test_lists_exactly_four_tools`, since the tool count is genuinely changing).
- No hardcoded magic numbers — the ambiguity threshold is a named module-level constant.

---

### Task 1: `build_context_block()` shared function in `kbcontext.py`

**Files:**
- Modify: `src/center_kb/kbcontext.py`
- Test: `tests/test_kbcontext.py`

**Interfaces:**
- Consumes: `center_kb.gitio.git_root(start: Path) -> Path`, `gitio.head_commit(root: Path) -> str`, `gitio.is_dirty(root: Path, subpath: Path) -> bool`, `gitio.GitError`; `center_kb.query.get_section(kb_dir, doc_id, section_id, level="l2", hub=None) -> QueryResult | None`; `center_kb.hub.HubHandle` (`.federation_dir`, `.root`, `.kb_dir` — `TYPE_CHECKING`-only import, matches the existing pattern in `query.py`).
- Produces: `kbcontext.KBRefNotFoundError` (subclass of `kbcontext.KBContextError`); `kbcontext.build_context_block(kb_dir: Path, refs: list[str], tags: list[str] | None = None, hub: "HubHandle | None" = None) -> tuple[str, str | None]` — returns `(block_text, dirty_warning_or_None)`. Raises `KBRefNotFoundError` (ref doesn't resolve), `KBContextError` (empty refs or malformed ref), or `gitio.GitError` (not a git repo / no HEAD).

- [ ] **Step 1: Write the failing tests**

Add to the end of `tests/test_kbcontext.py`:

```python
# --- build_context_block() ---


def test_build_context_block_single_ref_pins_head(git_kb):
    block, warning = kbcontext.build_context_block(
        git_kb["kb"], ["demo-doc §1.1"]
    )
    assert warning is None
    assert "kb-context:" in block
    assert f'version: "{git_kb["rev2"]}"' in block
    assert "- demo-doc §1.1" in block


def test_build_context_block_multi_ref(git_kb):
    block, _ = kbcontext.build_context_block(
        git_kb["kb"], ["demo-doc §1.1", "demo-doc §1.2"], tags=["demo", "airspace"]
    )
    assert "- demo-doc §1.1" in block
    assert "- demo-doc §1.2" in block
    assert "tags: [demo, airspace]" in block


def test_build_context_block_rejects_unresolvable_ref(git_kb):
    with pytest.raises(kbcontext.KBRefNotFoundError, match="9.9"):
        kbcontext.build_context_block(git_kb["kb"], ["demo-doc §9.9"])


def test_build_context_block_rejects_empty_refs(git_kb):
    with pytest.raises(kbcontext.KBContextError, match="is empty"):
        kbcontext.build_context_block(git_kb["kb"], [])


def test_build_context_block_dirty_warning(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Airspace Records\n\nuncommitted edit\n\n## 1.2 Airway Records\n\nx\n",
        encoding="utf-8",
    )
    block, warning = kbcontext.build_context_block(git_kb["kb"], ["demo-doc §1.1"])
    assert warning is not None
    assert "uncommitted changes" in warning
    assert "kb-context:" in block  # block is still produced alongside the warning


def test_build_context_block_with_hub_ref_pins_hub_version(
    git_kb, hub_worktree, run_git
):
    from center_kb.hub import HubHandle

    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    block, _ = kbcontext.build_context_block(
        git_kb["kb"], ["arinc-424 §5.3"], hub=HubHandle(root=hub_worktree)
    )
    assert f'hub_version: "{hub_head}"' in block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_kbcontext.py -k build_context_block -v`
Expected: FAIL — `AttributeError: module 'center_kb.kbcontext' has no attribute 'build_context_block'` (and `KBRefNotFoundError`).

- [ ] **Step 3: Implement `build_context_block()` and `KBRefNotFoundError`**

In `src/center_kb/kbcontext.py`, add near the top (after the `import re` block, before `class KBContextError`):

```python
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from center_kb.hub import HubHandle
```

Add right after the existing `class KBContextError(ValueError):` block:

```python
class KBRefNotFoundError(KBContextError):
    """A ref does not resolve to any known section in the local KB or hub."""
```

Add at the end of the file (after `render()`):

```python
def build_context_block(
    kb_dir: Path,
    refs: list[str],
    tags: list[str] | None = None,
    hub: "HubHandle | None" = None,
) -> tuple[str, str | None]:
    """Validate refs, pin at the current git HEAD, and render a kb-context block.

    Returns (block_text, dirty_warning). dirty_warning is a one-line string
    when kb_dir has uncommitted changes, else None — callers decide where to
    surface it (CLI: stderr; MCP: inline in the tool's text output, since it
    has only one output channel).
    """
    from center_kb import gitio
    from center_kb.query import get_section

    ref_list = [parse_ref(r) for r in refs if r.strip()]
    if not ref_list:
        raise KBContextError(
            "--refs is empty — need at least 1 ref, e.g. 'arinc-424 §5.3'"
        )

    root = gitio.git_root(kb_dir.resolve())
    version = gitio.head_commit(root)

    bad: list[str] = []
    needs_hub = False
    for r in ref_list:
        if r.repo_id:
            found = hub is not None and (
                hub.federation_dir / r.repo_id / "manifests" / f"{r.doc_id}.yaml"
            ).exists()
            needs_hub = True
        else:
            found = get_section(kb_dir, r.doc_id, r.section_id) is not None
            if not found and hub is not None:
                found = (
                    get_section(kb_dir, r.doc_id, r.section_id, hub=hub) is not None
                )
                needs_hub = needs_hub or found
        if not found:
            bad.append(str(r))
    if bad:
        raise KBRefNotFoundError(
            f"Ref could not be resolved in worktree: {', '.join(bad)}"
        )

    hub_version = None
    if needs_hub and hub is not None:
        hub_version = gitio.head_commit(gitio.git_root(hub.root))

    dirty_warning = None
    if gitio.is_dirty(root, kb_dir.resolve()):
        dirty_warning = (
            "[warn] .kb/ has uncommitted changes — "
            "the pinned hash will not include them"
        )

    ctx = KBContext(
        version=version,
        hub_version=hub_version,
        refs=ref_list,
        tags=[t.strip() for t in (tags or []) if t.strip()],
    )
    return render(ctx), dirty_warning
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_kbcontext.py -v`
Expected: PASS — all tests in the file, including the 6 new ones.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/kbcontext.py tests/test_kbcontext.py
git commit -m "feat: add build_context_block() shared kb-context pinning logic"
```

---

### Task 2: Refactor `cli.py`'s `context new` command onto `build_context_block()`

**Files:**
- Modify: `src/center_kb/cli.py:473-540` (the `context_new` command)
- Test: `tests/test_cli_context.py`, `tests/test_cli_hub.py` (no new test code — regression check only)

**Interfaces:**
- Consumes: `kbcontext.build_context_block(...)`, `kbcontext.KBContextError`, `kbcontext.KBRefNotFoundError` from Task 1; existing `_resolve_hub_option(hub: str, quiet: bool = False)` (`cli.py:64`).
- Produces: no new public interface — this task changes `context_new`'s internals only, not its CLI-visible behavior.

- [ ] **Step 1: Confirm the pre-refactor baseline passes**

Run: `pytest tests/test_cli_context.py tests/test_cli_hub.py -v`
Expected: PASS (all tests green before touching `cli.py` — this is the safety net for the refactor).

- [ ] **Step 2: Replace `context_new`'s body**

In `src/center_kb/cli.py`, replace the full `context_new` function body (lines 473-540) with:

```python
@context_app.command("new")
def context_new(
    refs: str = typer.Option(
        ..., "--refs", help="Comma-separated refs, e.g. 'arinc-424 §5.3,arinc-424 §5.3.2'"
    ),
    tags: str = typer.Option("", help="Tags, comma-separated"),
    kb_dir: Path = typer.Option(Path(".kb"), help="KB directory"),
    hub: str = typer.Option(
        "", "--hub", envvar="CENTER_KB_HUB", help="kb-hub URL/path (empty = don't use)"
    ),
) -> None:
    """Generate a kb-context block pinned at HEAD — paste into a Jira ticket."""
    from center_kb import gitio, kbcontext

    handle = _resolve_hub_option(hub)
    ref_strs = [r for r in refs.split(",") if r.strip()]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    try:
        block, dirty_warning = kbcontext.build_context_block(
            kb_dir, ref_strs, tags=tag_list, hub=handle
        )
    except (kbcontext.KBContextError, gitio.GitError) as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(1)
    if dirty_warning:
        typer.secho(dirty_warning, fg=typer.colors.YELLOW, err=True)
    typer.echo(block)
```

- [ ] **Step 3: Run tests to verify no regression**

Run: `pytest tests/test_cli_context.py tests/test_cli_hub.py -v`
Expected: PASS — same tests as Step 1, still all green, now against the refactored implementation.

- [ ] **Step 4: Commit**

```bash
git add src/center_kb/cli.py
git commit -m "refactor: cli context_new delegates to kbcontext.build_context_block"
```

---

### Task 3: `kb_context_new` MCP tool

**Files:**
- Modify: `src/center_kb/mcp.py`
- Modify: `README.md` (§7.8 tool table + BA → Jira → Dev flow)
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `kbcontext.build_context_block(...)`, `kbcontext.KBRefNotFoundError`, `kbcontext.KBContextError` from Task 1 (both already imported at module level in `mcp.py` via `from center_kb import gitio, kbcontext, models`); existing `_known_docs(kb_dir: Path) -> str` (`mcp.py:28`) and the `_hub()` closure defined inside `create_server` (`mcp.py:39`).
- Produces: MCP tool `kb_context_new(refs: list[str], tags: list[str] | None = None) -> str`, registered on the server alongside the existing 3 tools.

- [ ] **Step 1: Write the failing tests**

In `tests/test_mcp.py`, replace `test_lists_exactly_three_tools` (the whole function) with:

```python
@pytest.mark.anyio
async def test_lists_exactly_four_tools(fixture_kb):
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert sorted(t.name for t in tools.tools) == [
            "kb_context_new", "kb_get_section", "kb_resolve", "kb_search",
        ]
```

Then append these new tests to the end of `tests/test_mcp.py`:

```python
# --- kb_context_new ---


@pytest.mark.anyio
async def test_kb_context_new_single_ref(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new", {"refs": ["demo-doc §1.1"]}
        )
        text = _text(result)
        assert "kb-context:" in text
        assert f'version: "{git_kb["rev2"]}"' in text
        assert "- demo-doc §1.1" in text


@pytest.mark.anyio
async def test_kb_context_new_multi_ref(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new",
            {"refs": ["demo-doc §1.1", "demo-doc §1.2"], "tags": ["demo"]},
        )
        text = _text(result)
        assert "- demo-doc §1.1" in text
        assert "- demo-doc §1.2" in text
        assert "tags: [demo]" in text


@pytest.mark.anyio
async def test_kb_context_new_unresolvable_ref_returns_error_text(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new", {"refs": ["demo-doc §9.9"]}
        )
        text = _text(result)
        assert "9.9" in text
        assert "demo-doc" in text  # known-docs hint


@pytest.mark.anyio
async def test_kb_context_new_empty_refs_returns_error_text(git_kb):
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool("kb_context_new", {"refs": []})
        assert "is empty" in _text(result)


@pytest.mark.anyio
async def test_kb_context_new_dirty_warning_inline(git_kb):
    (git_kb["kb"] / "demo-doc" / "ch1-records.md").write_text(
        "## 1.1 Airspace Records\n\nuncommitted edit\n\n## 1.2 Airway Records\n\nx\n",
        encoding="utf-8",
    )
    server = create_server(ServerConfig(kb_dir=git_kb["kb"]))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new", {"refs": ["demo-doc §1.1"]}
        )
        text = _text(result)
        assert "uncommitted changes" in text
        assert "kb-context:" in text


@pytest.mark.anyio
async def test_kb_context_new_with_hub_ref_pins_hub_version(
    git_kb, hub_worktree, run_git
):
    hub_head = run_git(hub_worktree, "rev-parse", "--short", "HEAD")
    server = create_server(
        ServerConfig(kb_dir=git_kb["kb"], hub=str(hub_worktree))
    )
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_context_new", {"refs": ["arinc-424 §5.3"]}
        )
        assert f'hub_version: "{hub_head}"' in _text(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp.py -k "context_new or four_tools" -v`
Expected: FAIL — `test_lists_exactly_four_tools` fails (only 3 tools registered); the `kb_context_new` tests fail with an unknown-tool error from the client (`kb_context_new` is not a registered tool).

- [ ] **Step 3: Implement the `kb_context_new` tool**

In `src/center_kb/mcp.py`, add this tool inside `create_server()`, right after the `kb_get_section` tool definition and before `kb_resolve`:

```python
    @mcp.tool()
    def kb_context_new(refs: list[str], tags: list[str] | None = None) -> str:
        """Pin a kb-context citation block at the current KB commit, from 1+
        refs like 'arinc-424 §5.129'. Call this only after the user has
        confirmed which section(s) — out of everything kb_search returned —
        actually belong in the story; paste the returned block into the
        ticket. Citing 2-3 sections for one story is normal — pass every
        confirmed ref in one call."""
        try:
            block, dirty_warning = kbcontext.build_context_block(
                config.kb_dir, refs, tags=tags, hub=_hub()
            )
        except kbcontext.KBRefNotFoundError as exc:
            known = _known_docs(config.kb_dir)
            hint = f" Available docs: {known}." if known else ""
            return f"{exc}{hint}"
        except kbcontext.KBContextError as exc:
            return str(exc)
        except gitio.GitError as exc:
            return str(exc)
        if dirty_warning:
            return f"{dirty_warning}\n\n{block}"
        return block
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp.py -v`
Expected: PASS — full file, including all `kb_context_new` tests and `test_lists_exactly_four_tools`.

- [ ] **Step 5: Update README §7.8**

In `README.md`, change line 378 from:

```
#### MCP server — 3 tools
```

to:

```
#### MCP server — 4 tools
```

Replace the table at lines 382-386:

```
| Tool | Purpose | Main params |
|---|---|---|
| `kb_search` | Find sections by natural language (tag match + BM25), return L2 within a token budget | `query`, `tags`, `budget` |
| `kb_get_section` | Fetch exactly one section by id | `doc`, `section`, `level` (`l2`/`l3`) |
| `kb_resolve` | Accept a `kb-context` block (or a ticket containing one) — return the section at the **pinned version**, plus freshness `ok`/`stale`/`broken` | `kb_context` |
```

with:

```
| Tool | Purpose | Main params |
|---|---|---|
| `kb_search` | Find sections by natural language (tag match + BM25), return L2 within a token budget | `query`, `tags`, `budget` |
| `kb_get_section` | Fetch exactly one section by id | `doc`, `section`, `level` (`l2`/`l3`) |
| `kb_context_new` | Pin a `kb-context` citation block at the current KB commit, from 1+ confirmed refs — lets an agent do this from chat, without the BA opening a terminal | `refs`, `tags` |
| `kb_resolve` | Accept a `kb-context` block (or a ticket containing one) — return the section at the **pinned version**, plus freshness `ok`/`stale`/`broken` | `kb_context` |
```

Replace the BA → Jira → Dev flow's step 1 (line 401):

```
1. BA runs `kb context new --refs "<doc> §<section>"` after reading the relevant spec passage.
```

with:

```
1. BA asks an AI assistant (chat, via MCP) to draft the story; the assistant calls `kb_search`, shows the BA every returned candidate section (not just the best match), and — once the BA confirms which one(s) apply — calls `kb_context_new` with those refs. (Or, working at a terminal: `kb context new --refs "<doc> §<section>"` does the same thing directly.)
```

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/mcp.py tests/test_mcp.py README.md
git commit -m "feat: add kb_context_new MCP tool so citations can be pinned from chat"
```

---

### Task 4: `kb_search` ambiguity annotation + docstring rewrite

**Files:**
- Modify: `src/center_kb/mcp.py`
- Modify: `README.md` (§7.8 tool table, `kb_search` row)
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: `QueryResult.score: float`, `QueryResult.citation: str` (`src/center_kb/query.py`, unchanged); Task 3's `kb_context_new` tool (referenced by name in the rewritten `kb_search` docstring).
- Produces: module-level constant `AMBIGUOUS_SCORE_GAP: float = 0.20` in `mcp.py`; updated `kb_search` tool text output (an optional leading `Note: ...` line) and docstring.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp.py`:

```python
# --- kb_search ambiguity annotation ---


@pytest.mark.anyio
async def test_kb_search_notes_close_scores(fixture_kb):
    # "records structure" scores demo-doc §1.1 and §1.2 exactly tied under
    # BM25Plus on this fixture — the clearest possible ambiguous case.
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "records structure"}
        )
        text = _text(result)
        assert "Note:" in text
        assert "demo-doc §1.1" in text
        assert "demo-doc §1.2" in text


@pytest.mark.anyio
async def test_kb_search_no_note_when_one_result_dominates(fixture_kb):
    # "airspace designation" scores §1.1 well above §1.2 (~55% relative gap)
    # on this fixture — not ambiguous.
    server = create_server(ServerConfig(kb_dir=fixture_kb))
    async with connect_client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "kb_search", {"query": "airspace designation"}
        )
        assert "Note:" not in _text(result)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp.py -k "close_scores or one_result_dominates" -v`
Expected: FAIL — `test_kb_search_notes_close_scores` fails because no `"Note:"` is present yet.

- [ ] **Step 3: Implement the annotation and docstring rewrite**

In `src/center_kb/mcp.py`, add near the top of the file (after the imports, before `@dataclass class ServerConfig`):

```python
# Below this relative score gap between the top 2 kb_search results, both
# are surfaced with a note instead of letting the top hit look unambiguous.
AMBIGUOUS_SCORE_GAP = 0.20
```

Replace the existing `kb_search` tool (inside `create_server()`) — currently:

```python
    @mcp.tool()
    def kb_search(
        query: str, tags: list[str] | None = None, budget: int = 2000
    ) -> str:
        """Find sections by tag match + BM25; return L2 content within the token budget, with citations."""
        results = search(config.kb_dir, query, tags=tags, budget=budget, hub=_hub())
        if not results:
            return "No matching section found — try dropping tags or changing keywords."
        return "\n\n".join(
            f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk\n{r.content}"
            for r in results
        )
```

with:

```python
    @mcp.tool()
    def kb_search(
        query: str, tags: list[str] | None = None, budget: int = 2000
    ) -> str:
        """Find sections by tag match + BM25 (falls back to semantic search);
        return L2 content within the token budget, with citations. Returns
        every relevant section found, not just the best match — when using
        this to draft a User Story, show ALL returned sections (with their
        citations) to the user and confirm which ones actually apply before
        writing story content from them. Citing more than one section for a
        single story is normal. Once confirmed, call kb_context_new with the
        confirmed refs to pin them for the ticket."""
        results = search(config.kb_dir, query, tags=tags, budget=budget, hub=_hub())
        if not results:
            return "No matching section found — try dropping tags or changing keywords."
        note = ""
        if len(results) >= 2 and results[0].score > 0:
            gap = (results[0].score - results[1].score) / results[0].score
            if gap < AMBIGUOUS_SCORE_GAP:
                note = (
                    f"Note: [{results[0].citation}] and [{results[1].citation}] "
                    "score closely — both may be relevant to your question; "
                    "review each before citing.\n\n"
                )
        return note + "\n\n".join(
            f"--- [{r.citation}] score={r.score:.2f} ~{r.tokens}tk\n{r.content}"
            for r in results
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp.py -v`
Expected: PASS — full file, all tests including the 2 new ones and everything from Task 3.

- [ ] **Step 5: Update README's `kb_search` row**

In `README.md`, in the tool table updated in Task 3, change the `kb_search` row from:

```
| `kb_search` | Find sections by natural language (tag match + BM25), return L2 within a token budget | `query`, `tags`, `budget` |
```

to:

```
| `kb_search` | Find sections by natural language (tag match + BM25), return L2 within a token budget — returns every relevant section found, not just the best match, and flags when the top two are close in score | `query`, `tags`, `budget` |
```

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: PASS — no regressions anywhere in the repo from this change set.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/mcp.py tests/test_mcp.py README.md
git commit -m "feat: kb_search flags closely-scored candidates, docstring points to kb_context_new"
```
