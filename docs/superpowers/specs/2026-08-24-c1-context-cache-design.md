# C1 — Context cache for the Dev pipeline + `kb resolve --status-only`

**Status:** approved design, ready for an implementation plan
**Roadmap item:** batch 4 (C1) of
`docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md`.
**Approach:** option 1 as approved on 2026-08-24 — the agent writes the cache,
the CLI only gains a render flag. No MCP change, no schema change.

## Goal

A ticket run pulls the same pinned KB content up to five times: the freshness
re-check sits at the top of all five dev skills, and every `kb resolve` /
`kb_resolve` call returns the full text of every pinned section. C1 makes the
re-check cheap: resolve the full content **once**, park it in a per-ticket cache
file, and let every later check ask only for the verdict.

What it buys, per ticket: one full-content resolve instead of ~4–5. The
batch-2 measurement flagged this as the largest predicted saving in group C.

## Scope

**In:**

- `src/center_kb/resolve.py` — `render_resolved()` gains `include_content`.
- `src/center_kb/cli.py` — `kb resolve` gains `--status-only`.
- `src/center_kb/templates/init/` — the SHARED-FRESHNESS canon block (20 dev
  wrappers), the orchestrator's Resolve/Placeholders steps (4 wrappers), the
  handover's final re-check (4 wrappers), `QUICKSTART-dev.md`, and a new
  scaffold file `docs/impl/.gitignore`.
- `tests/test_cli_context.py`, `tests/test_resolve.py`,
  `tests/test_templates.py`, `tests/test_init.py`.

**Out, and deliberately so:**

- **MCP.** `kb_resolve` keeps its signature, docstring, and full-content
  output. The golden `tests-gate/golden/mcp_tools.json` stays byte-identical.
  An MCP-only environment (no shell) keeps paying full price on every
  re-check — stated cost, not a hidden one.
- **`resolve_refs()`.** The verdict is computed by comparing pinned content
  against the worktree, so the resolver must read content regardless. C1 saves
  agent-context tokens, not hub I/O.
- **The stale-reason `kb diff` hint** in `render_resolved` output
  (`resolve.py:163`). Pre-existing text, other tests pin it, not this batch.
- **C5's remaining half, C6, D, E** — untouched.
- **CLI-side cache** (approach 2) and **no-file** (approach 3) — rejected in
  brainstorming: the placeholder map is agent-verified against the codebase, so
  the CLI cannot own the file; and without a file nothing survives a session
  boundary.

## Evidence this design rests on

Read from the tree at `49b9ca5`, 2026-08-24. Each fact decided something.

**1. Full text is a render decision, not a resolve decision.**
`render_resolved()` (`resolve.py:154`) appends `r.content` for every ref;
`resolve_refs()` → `_resolve_one()` must read the pinned content anyway to
compute ok/stale against the worktree (`resolve.py:96–105`). So `--status-only`
is a rendering flag; the resolver is untouched.

**2. Exit codes are the CLI's verdict channel.** `cli.py:1488` `resolve()`
exits 1 on broken, 2 on stale (`cli.py:1517–1520`). `--status-only` keeps them
— skills already triage on them.

**3. The MCP tool cannot grow a parameter.** `kb_resolve` (`mcp.py:186`) is
pinned by the golden; any schema or docstring change breaks the byte-identity
gate. Hence: CLI flag only.

**4. SHARED-FRESHNESS is canon in 20 files.** Canon text at
`tests/test_templates.py:308`; sliced by first/last line anchors
(`test_templates.py:287–290`); byte-identity across all 20 wrappers enforced at
`test_templates.py:373`. The C5 length cap `<= 660` (`test_templates.py:1184`)
and the kb-diff-trap/three-verdicts needles (`test_templates.py:1166`) pin the
current text. The hard-rules-untouched test (`test_templates.py:1188`) must
keep passing — C1 does not touch SHARED-HARD-RULES.

**5. Handover's body needles.** `test_templates.py:627` requires "one final
time", "paste the real output", "completion claim without it is not accepted"
in the dev-handover body. The new block's `--status-only` output *is* real
output, so the needles survive; only surrounding wording may shift.

**6. There is no dev-kind `.gitignore` scaffold to extend.** The scaffold map
(`initcmd.py:102`) ships `docs/impl/.gitkeep`; the only gitignore handling is
dockersetup's `.env` append (`dockersetup.py:103`) and the hub-kind
`source/.gitignore` (`initcmd.py:17`). A new scaffold file
`docs/impl/.gitignore` is therefore the clean insertion point — no hand-merge
into a repo root `.gitignore` the dev may own.

**7. A5 is already shipped but not ticked.** `kb tags` exists at `cli.py:1461`.
Follow-up: tick A5 in the roadmap; no work in this batch.

## Design

### 1. Engine — `kb resolve --status-only`

- `render_resolved(results, include_content: bool = True)` — with
  `include_content=False` it emits, per ref, exactly the existing header line
  `--- [citation @ rev] status=... ~Ntk` plus the `!! reason` line(s) for
  stale/broken. No section content. Same function, no sibling renderer.
- `cli.py resolve()` gains `status_only: bool = typer.Option(False,
  "--status-only", ...)` and passes `include_content=not status_only`.
- Exit codes unchanged: ok=0, broken=1, stale=2.

### 2. Cache file — `docs/impl/<ticket-id>-context.md`

Agent-written; the CLI never reads or writes it. `<ticket-id>` is the same stem
used by `<ticket-id>-design.md` / `<ticket-id>-plan.md`. Format:

```markdown
# Context cache — <ticket-id>
> Generated by dev-implement-ticket — do not hand-edit; regenerated on full
> re-resolve. Gitignored.

version: <pinned hub commit from the ticket's block>
resolved: <YYYY-MM-DD>

## Resolved sections
<full `kb resolve` output, verbatim>

## Placeholder map
| placeholder | verified value | evidence (file:line or ref) |
```

*Superseded 2026-09-15 by
`2026-09-15-dev-workflow-usage-review-fixes-design.md` §2: the CLI writes
everything above `<!-- kb:placeholder-map -->` (`kb resolve --write-cache`)
and validates it (`--status-only --cache`); the agent owns the map below.*

Rules:

- Written once by the orchestrator after its Resolve + Placeholders steps.
- Whoever performs a full re-resolve (no cache, `version:` mismatch, non-ok
  verdict) rewrites the cache. One sentence, no per-phase permissions.
- Gitignored via the scaffolded `docs/impl/.gitignore` containing
  `*-context.md` (decision 2026-08-24: the file is derivable from one full
  resolve — same reasoning that kept `report.html` out of git — and committing
  it would copy hub content verbatim into the dev repo's history and PR diffs).
- Not a re-entry state marker: the orchestrator's state detection still reads
  only design/plan/branch/PR. A gitignored file may legitimately be absent.

### 3. SHARED-FRESHNESS — new canon text

Replaces the block in all 20 dev wrappers. First and last lines are unchanged,
so the `SHARED_BLOCKS` anchors keep slicing:

```markdown
## Freshness re-check (run this FIRST, every time)

Cheap check first: when `docs/impl/<ticket-id>-context.md` exists and its
`version:` matches the ticket's block, run `kb resolve --status-only
<ticket-file>` (no CLI → `kb_resolve`, full output). All **ok** → use the
cache; do NOT re-pull pinned content. No cache, version mismatch, or a
non-ok verdict → full `kb resolve <ticket-file>` (else `kb_resolve`),
then rewrite the cache.

- **broken** → STOP. Blocker: the BA must re-pin. Never implement around a
  citation that no longer resolves.
- **stale** → show BOTH versions, humans decide: the resolve gives the
  pinned content and the reason, `kb get <doc-id> <section> [--level l3]`
  the current hub version. Do NOT use `kb diff` — it compares the local
  `.kb/` worktree to a local git rev, not this repo to the hub.
- **ok** → continue.
```

Kept on purpose: the three verdicts, "Never implement around a citation that
no longer resolves", and the `kb diff` trap — the existing needle tests pass
unchanged. The block grows from ~605 to ~950 characters; the C5 cap is bumped
consciously with a comment saying C1 changed the check's *algorithm*, not its
wordiness.

### 4. Wrapper bodies (outside the shared block)

- **dev-implement-ticket** (4 wrappers): the **Resolve** step gains one
  sentence — after a full resolve, write `docs/impl/<ticket-id>-context.md`
  (version + resolved output); the **Placeholders** step gains "record the map
  in the cache file". State detection is not extended.
- **dev-handover** (4 wrappers): the final re-check pastes the
  `--status-only` output. The three pinned needle phrases stay verbatim.
- **dev-design / dev-plan / dev-execute**: body untouched — the shared block
  carries the change.
- **QUICKSTART-dev.md**: the `docs/impl/` file list gains one line for
  `<ticket-id>-context.md` (gitignored cache).

### 5. Tests and trip-wires

- `tests/test_resolve.py`: unit test for
  `render_resolved(results, include_content=False)` — headers and reasons
  present, section content absent.
- `tests/test_cli_context.py`: three CLI tests — `--status-only` on an ok
  block (exit 0, no section content in stdout), on a stale block (exit 2,
  reason shown), on a broken block (exit 1).
- `tests/test_templates.py`: new canon for `SHARED_BLOCK_TEXT
  ['SHARED-FRESHNESS']`, extracted via `repr()` from a landed wrapper (house
  rule: never hand-retyped); length-cap test bumped with a comment; one new
  needle test asserting the shared block mentions `--status-only` and
  `-context.md`; the hard-rules-untouched test passes as-is.
- `tests/test_init.py`: pinned scaffold count +1 for `docs/impl/.gitignore`;
  content assertion for `*-context.md`.
- Golden `mcp_tools.json`: untouched — the existing byte-identity test is the
  proof.
- E2E gate: untouched; `--status-only` does not change the journey.

Build order: engine + engine tests first (TDD), then the 20-file template round
with its canon bump, then the scaffold file with its `test_init.py` bump.

## Follow-ups recorded, not done here

- Tick **A5** in the roadmap (`kb tags` already shipped, `cli.py:1461`).
- After 1–2 weeks of B-dashboard data: measure C1's actual saving; decide
  whether the rest of C5 is still worth anything.
