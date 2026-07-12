# MCP citation confirmation for BA-authored User Stories

**Date:** 2026-07-12
**Status:** Approved for planning

## Problem

Phase 2 already has a BA → Jira → Dev workflow: a BA runs `kb context new
--refs "<doc> §<section>"` (CLI) to generate a `kb-context` block pinned at
the current KB commit, pastes it into a Jira ticket, and later `kb_resolve`
/ `kb doctor --context` detect staleness if the KB changed since. That
workflow assumes the BA operates the CLI directly.

In practice, a BA is expected to interact with the KB by chatting with an
AI assistant (Claude Desktop, Claude Code, GitHub Copilot) that has the
`center-kb` MCP server's tools available — not a terminal. Two gaps follow:

1. **No way to pin a citation from chat.** `kb context new` only exists as
   a CLI command. An AI assistant with only the 3 declared MCP tools
   (`kb_search`, `kb_get_section`, `kb_resolve`) has no way to produce a
   `kb-context` block, so the BA → Jira → Dev pinning workflow is
   unreachable for a BA who never opens a terminal.
2. **Nothing pushes the AI to show its work.** `kb_search` already returns
   multiple ranked, budget-filled candidate sections (not just the top
   hit), but nothing in the tool contract makes an AI assistant surface
   all of them to the BA before drafting story content — an assistant can
   silently anchor a User Story on the wrong section, or the right doc but
   a stale/wrong revision, and the BA (non-technical, no habit of
   cross-checking) would not know to be suspicious.

No MCP tool design can force an LLM to actually show its work to the human
— that is a matter of whether the assistant follows instructions, not a
protocol guarantee. The design below aims for the two levers that
realistically work: making the correct behavior the path of least
resistance (tool descriptions, since those are read by *any* MCP client
regardless of whether it supports Claude Skills), and closing the concrete
tool gap that blocks the correct behavior outright (no MCP-callable way to
pin a citation).

## Goals

- Any MCP client (Desktop, Code, Copilot) can pin a `kb-context` citation
  block from within a chat session, without the BA opening a terminal.
- `kb_search`'s tool contract nudges assistants to present every returned
  candidate to the BA (not just the top match) before citing, and to cite
  as many sections as the story genuinely needs (1..N — citing 2-3
  sections for one story is the normal case, not an edge case requiring
  special handling, since `kb_search` already returns multiple ranked hits
  and `kb context new` already accepts multiple refs).
- No regression to the existing CLI-driven `kb context new` behavior or
  its test coverage.

## Non-goals

- Enforcing (at the protocol level) that an assistant actually shows
  citations to the BA — out of scope, and not achievable by MCP tool
  design alone.
- Changing `kb_search`'s ranking algorithm (BM25 / semantic fallback) or
  its `search()` return type in `query.py`.
- A hard "ambiguous" gate that blocks tool output based on score gap
  between the top two candidates. Considered and rejected: a score-gap
  heuristic cannot distinguish "two sections are mutually exclusive
  choices, picking the wrong one silently misinforms the AC" from "two
  sections are both genuinely needed together for this story" — both
  produce a close score. A soft annotation is kept (see below) but is not
  a blocking condition.

## Design

### 1. `kb_context_new` — new MCP tool

Thin MCP wrapper around the existing `kb context new` CLI logic
(`cli.py:474-540`), which is already pure (no LLM call, no file writes):
validate each ref resolves in the local KB (or hub, if `repo:doc §section`
syntax is used and the server has `--hub`), read the git HEAD commit via
`gitio`, build a `KBContext`, render it to text.

**Refactor:** extract the validate → resolve-HEAD → build → render logic
out of `cli.py`'s `context_new` command body into a shared function (e.g.
in `kbcontext.py`), so both the CLI command and the new MCP tool call the
same code path. `cli.py`'s command becomes a thin argument-parsing /
`typer.Exit` wrapper around it, matching the existing separation between
`query.py`'s `search()`/`get_section()` and their CLI/MCP callers.

**Signature (MCP tool):**

```python
@mcp.tool()
def kb_context_new(refs: list[str], tags: list[str] | None = None) -> str:
    """Pin a kb-context citation block at the current KB commit, from 1+
    refs like 'arinc-424 §5.129'. Call this only after the user has
    confirmed which section(s) — out of everything kb_search returned —
    actually belong in the story; paste the returned block into the
    ticket. Citing 2-3 sections for one story is normal — pass every
    confirmed ref in one call."""
```

`refs` is a list (not a comma-joined string like the CLI flag) — cleaner
MCP surface, and avoids re-parsing a delimiter inside the tool body.

**Error handling** (mirrors existing `kb_get_section`/`kb_resolve` pattern
— always return descriptive text, never raise across the MCP boundary):

| Situation | Output |
|---|---|
| A ref fails to parse (`kbcontext.parse_ref` raises) | Error text naming the malformed ref and the expected format |
| A ref doesn't resolve in the local KB (or hub, if `repo:` prefixed and no `--hub` configured) | `"Ref could not be resolved: <ref>."` + known-docs hint (reuse `_known_docs`, already in `mcp.py`) |
| `refs` is empty | `"--refs is empty — need at least 1 ref, e.g. 'arinc-424 §5.3'"` |
| `.kb/` has uncommitted changes | Prepend `"[warn] .kb/ has uncommitted changes — pinned hash excludes them"` to the returned block text (the CLI writes this to stderr; the MCP tool has one text channel, so it goes inline instead) |
| Not a git repo / no commits yet | Catch `gitio.GitError`, return its message as text |

### 2. `kb_search` — soft ambiguity annotation + docstring rewrite

No change to `search()` in `query.py`. Purely a presentation-layer addition
in the `kb_search` MCP tool body: after getting `results` back, if there
are ≥ 2 results and the top two scores are within a relative gap (default
20% — `(top - second) / top < 0.20`), prepend one note line to the
returned text, e.g.:

```
Note: [arinc-424 §5.129] and [arinc-424 §5.126] score closely — both may
be relevant to your question; review each before citing.
```

This is informational only — it does not remove or reorder any result.

**Docstring rewrite** (both tools), since this is the primary, portable
enforcement lever (read by any MCP client, unlike `.claude/skills/`):

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
```

### 3. Out of scope: Claude Skill

A `.claude/skills/` file restating the same "show all candidates, confirm,
then pin" guidance was considered as a supplementary layer for Claude
Code/Desktop users specifically. Not included in this design — the tool
docstrings above are the primary lever and work for every MCP client
including Copilot, where a Claude Skill would have no effect. Can be added
later as a low-cost addition if Claude-specific reinforcement proves
useful in practice; not blocking for this design.

## Data flow (happy path, multi-section)

```
1. BA asks the assistant to draft a User Story for some topic.
2. Assistant calls kb_search(query, tags?, budget?).
3. Tool returns N candidate sections (existing behavior) — each with
   citation, score, L2 content, match_mode; a soft note is prepended if
   the top two scores are close.
4. Assistant presents every returned section (not just the top one) to
   the BA with its citation — pushed by the kb_search docstring.
5. BA confirms which subset (1..N) actually belongs in this story.
6. Assistant calls kb_context_new(refs=[...confirmed refs...], tags=[...]).
7. Tool validates, pins at HEAD, returns the rendered kb-context block
   (with a dirty-worktree warning inline if applicable).
8. Assistant pastes the block + drafted story/AC text into the Jira
   ticket (BA can also paste manually).
9. (Unchanged) Dev opens the ticket; kb_resolve / kb doctor --context
   detect staleness later if the KB has since changed.
```

## Testing

Existing coverage to preserve as a refactor safety net:
`tests/test_cli_context.py` (parses/resolves refs, dirty warning to
stderr, empty refs, unresolvable ref) and `tests/test_cli_hub.py`
(hub-qualified refs). These must pass unchanged after extracting the
shared logic out of `cli.py`.

New coverage in `tests/test_mcp.py` (pattern: `create_connected_server_and_client_session`,
`fixture_kb`, `git_kb`):

- `kb_context_new` returns a correct block for 1 ref and for 2-3 refs.
- Unresolvable ref → descriptive error text, no exception.
- Empty `refs` → descriptive error text.
- Dirty `.kb/` → warning present in the returned text.
- Hub-qualified ref (`repo:doc §sec`) with no `--hub` on the server →
  descriptive error text.
- `test_lists_exactly_three_tools` → updated to expect 4 tools.
- `kb_search` soft annotation: a fixture with two closely-scored sections
  asserts the note appears; a control fixture with one dominant result
  asserts it does not.

**Known untestable gap:** whether an assistant actually follows the
docstring instruction to show all candidates before citing cannot be unit
tested — it depends on the calling LLM's instruction-following, not on
this repo's code. Documented here as an accepted limitation, not silently
assumed to be solved.
