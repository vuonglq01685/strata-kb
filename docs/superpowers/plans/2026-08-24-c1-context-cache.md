# C1 Context Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One full-content resolve per ticket instead of ~4–5 — `kb resolve
--status-only` for cheap freshness re-checks plus an agent-written per-ticket
cache file `docs/impl/<ticket-id>-context.md`.

**Architecture:** The verdict (ok/stale/broken) is computed by comparing pinned
content to the worktree, so the resolver already reads everything — the saving
is a *render* flag, not a resolver change. The cache file is written by the
agent per skill instruction; the CLI never reads or writes it. The freshness
algorithm lives in the SHARED-FRESHNESS canon block repeated byte-identically
in 20 dev wrappers.

**Tech Stack:** Python 3.11+, typer CLI, pytest, package templates under
`src/center_kb/templates/init/`, canon tests in `tests/test_templates.py`.

**Spec:** `docs/superpowers/specs/2026-08-24-c1-context-cache-design.md`

## Global Constraints

- **No MCP change.** `src/center_kb/mcp.py` is not edited; the golden
  `tests-gate/golden/mcp_tools.json` stays byte-identical.
- **SHARED-HARD-RULES and SHARED-NEXT-STEP untouched.**
  `test_shared_hard_rules_were_not_touched_by_the_c5_round` pins
  `len == 1531` and 14 bullets; keep it passing without edits.
- **Canon is never hand-retyped.** `SHARED_BLOCK_TEXT` values are extracted
  via `repr()` from a landed wrapper file (house rule, see the comment at
  `tests/test_templates.py:302`).
- **Copilot and cursor wrappers carry identical bodies**, differing only on
  line 2 of the frontmatter (`test_copilot_and_cursor_wrappers_differ_only_in
  _their_frontmatter_name`). Any body edit to a `copilot-*.prompt.md` must be
  applied character-identically to the matching `cursor-*.md`.
- **Every dev wrapper ends with** `  Flow order never hides a blocker.\n` —
  edits must not disturb the file ending.
- Template prose hard-wraps at ~72 columns. Needle tests match
  whitespace-normalised text, so re-wrapping is free.
- Trip-wire bumps (`test_init.py` pinned count, freshness length ceiling) are
  deliberate, each with a comment saying C1 did it and why.
- Conventional commits (`feat:`/`test:`/`docs:`), no attribution footer.
- Run tests with `uv run pytest <path> -v`. Full suite: `uv run pytest tests`.
- Work happens on the existing branch `feat/c1-context-cache`.

---

### Task 1: `render_resolved(include_content=False)`

**Files:**
- Modify: `src/center_kb/resolve.py:154-169` (`render_resolved`)
- Test: `tests/test_resolve.py`

**Interfaces:**
- Consumes: existing `ResolvedRef`, `resolve_refs()` — unchanged.
- Produces: `render_resolved(results: list[ResolvedRef], include_content:
  bool = True) -> str`. With `include_content=False` the output per ref is
  exactly the existing header line `--- [{citation} @ {rev}] status={status}
  ~{tokens}tk` plus the existing `!! {reason}` line(s) for stale/broken —
  section content omitted. Task 2 calls this signature.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_resolve.py` (fixtures `fed_hub`, `run_git` come from
`tests/conftest.py`; `_ctx_for` and the imports already exist at the top of
the file):

```python
def test_render_resolved_status_only_omits_content(fed_hub):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    text = render_resolved(resolve_refs(handle, ctx), include_content=False)
    assert "status=ok" in text
    # the pinned section body must NOT be rendered
    assert "Condensed: restrictive airspace" not in text


def test_render_resolved_status_only_keeps_the_stale_reason(fed_hub, run_git):
    handle = HubHandle(root=fed_hub)
    ctx = _ctx_for(fed_hub, ["arinc-kb:arinc-424 §5.3"])
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"),
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "republish")
    text = render_resolved(resolve_refs(handle, ctx), include_content=False)
    assert "status=stale" in text
    assert "!!" in text  # the reason line survives — triage needs it
    assert "NEW codes" not in text and "designation codes" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_resolve.py -v -k status_only`
Expected: FAIL — `TypeError: render_resolved() got an unexpected keyword
argument 'include_content'`

- [ ] **Step 3: Implement**

In `src/center_kb/resolve.py`, change the signature and the content append:

```python
def render_resolved(
    results: list[ResolvedRef], include_content: bool = True
) -> str:
    parts: list[str] = []
    for r in results:
        rev = r.pinned_rev or "?"
        parts.append(f"--- [{r.citation} @ {rev}] status={r.status} ~{r.tokens}tk")
        if r.status == "broken":
            parts.append(f"!! {r.reason}")
        elif r.status == "stale":
            parts.append(
                f"!! {r.reason} — run `kb diff {r.ref.doc_id} --against {rev}` "
                "to see the changes"
            )
        if include_content and r.content:
            parts.append(r.content)
        parts.append("")
    return "\n".join(parts).strip()
```

(Only the signature line and the `if include_content and r.content:` line
change; everything else is verbatim the current body.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_resolve.py -v`
Expected: all PASS (the two new tests plus the six existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/resolve.py tests/test_resolve.py
git commit -m "feat: render_resolved learns include_content=False (C1)"
```

---

### Task 2: CLI flag `kb resolve --status-only`

**Files:**
- Modify: `src/center_kb/cli.py:1487-1520` (the `resolve` command)
- Test: `tests/test_cli_context.py`

**Interfaces:**
- Consumes: `render_resolved(results, include_content=...)` from Task 1.
- Produces: `kb resolve <source> --status-only` — same exit codes as today
  (ok=0, broken=1, stale=2), stdout carries only header + reason lines. The
  SHARED-FRESHNESS block written in Task 3 names this exact flag.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli_context.py` (module-level `runner` and `app`
already imported there):

```python
def test_resolve_status_only_ok_prints_no_content(fed_hub, fixture_kb, run_git):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    block = (
        f'kb-context:\n  version: "{hub_head}"\n  refs:\n'
        "    - arinc-kb:arinc-424 §5.3\n"
    )
    result = runner.invoke(
        app,
        ["resolve", "-", "--status-only",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
        input=block,
    )
    assert result.exit_code == 0
    assert "status=ok" in result.output
    assert "Condensed: restrictive airspace" not in result.output


def test_resolve_status_only_stale_exits_2_with_reason(
    fed_hub, fixture_kb, run_git, tmp_path_factory
):
    rev1 = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    l2 = fed_hub / "federation" / "arinc-kb" / "arinc-424" / "ch1.md"
    l2.write_text(
        l2.read_text(encoding="utf-8").replace("designation codes", "NEW codes"),
        encoding="utf-8",
    )
    run_git(fed_hub, "add", "-A")
    run_git(fed_hub, "commit", "-m", "amend arinc-424 5.3")
    ticket = tmp_path_factory.mktemp("ticket") / "tal-3.md"
    ticket.write_text(
        f'kb-context:\n  version: "{rev1}"\n  refs:\n'
        "    - arinc-kb:arinc-424 §5.3\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["resolve", str(ticket), "--status-only",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 2
    assert "status=stale" in result.output
    assert "!!" in result.output
    assert "NEW codes" not in result.output
    assert "designation codes" not in result.output


def test_resolve_status_only_broken_exits_1(
    fed_hub, fixture_kb, run_git, tmp_path_factory
):
    hub_head = run_git(fed_hub, "rev-parse", "--short", "HEAD")
    ticket = tmp_path_factory.mktemp("ticket") / "tal-4.md"
    ticket.write_text(
        f'kb-context:\n  version: "{hub_head}"\n  refs:\n'
        "    - arinc-kb:arinc-424 §9.9\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["resolve", str(ticket), "--status-only",
         "--kb-dir", str(fixture_kb), "--hub", str(fed_hub)],
    )
    assert result.exit_code == 1
    assert "status=broken" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli_context.py -v -k status_only`
Expected: FAIL — typer reports `No such option: --status-only` (exit code 2
from typer's parser, so the assertions on output/exit codes fail).

- [ ] **Step 3: Implement**

In `src/center_kb/cli.py`, `resolve()`: add the option after the `hub`
parameter and thread it into the render call.

```python
    status_only: bool = typer.Option(
        False,
        "--status-only",
        help="Print only the citation + freshness verdict per ref, no "
        "section content — for cheap re-checks against a context cache.",
    ),
```

and change the echo line:

```python
    typer.echo(render_resolved(results, include_content=not status_only))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_context.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/center_kb/cli.py tests/test_cli_context.py
git commit -m "feat: kb resolve --status-only — verdicts without content (C1)"
```

---

### Task 3: SHARED-FRESHNESS canon round — 20 wrappers + canon tests

**Files:**
- Modify: all 20 dev wrappers in `src/center_kb/templates/init/` —
  `{claude-skill,claude-command,cursor}-{dev-implement-ticket,dev-design,dev-plan,dev-execute,dev-handover}.md`
  and `copilot-<skill>.prompt.md` for the same five skills.
- Modify: `tests/test_templates.py:308` (`SHARED_BLOCK_TEXT`),
  `tests/test_templates.py:1179-1184` (length-ceiling test), plus one new
  needle test.

**Interfaces:**
- Consumes: the `--status-only` flag name from Task 2 (text only).
- Produces: the new SHARED-FRESHNESS canon text (below). Task 4's body edits
  and needle tests assume this block is already in place in all 20 files.

**The new block, verbatim** (first and last lines are unchanged, so the
`SHARED_BLOCKS` first/last-line anchors at `test_templates.py:287-290` keep
slicing without edits):

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

This keeps every needle the existing tests pin: `**broken** → STOP`,
`show BOTH versions` (`test_templates.py:757`), the three verdicts,
`kb_resolve`, `re-pin`, `--level l3`, and the full phrase
``Do NOT use `kb diff` `` (`test_templates.py:1166`).

- [ ] **Step 1: Script-replace the block in all 20 wrappers**

Write this to the scratchpad (NOT into the repo) as `c1_block_swap.py`, with
`OLD` copied verbatim from the current canon at `tests/test_templates.py:308`
(it is a Python string literal — paste its value) and `NEW` being the block
above as a Python string (ending with `"- **ok** → continue.\n"`):

```python
from pathlib import Path

OLD = (
    "## Freshness re-check (run this FIRST, every time)\n\nRe-resolve the "
    "ticket's `kb-context` first: `kb_resolve`, else\n`kb resolve "
    "<ticket-file>`. The hub may have published since last session.\n\n- "
    "**broken** → STOP. Blocker: the BA must re-pin. Never implement around a\n"
    "  citation that no longer resolves.\n- **stale** → show BOTH versions, "
    "humans decide: `kb resolve` gives the pinned\n  content and the reason, "
    "`kb get <doc-id> <section> [--level l3]` the current\n  hub version. Do "
    "NOT use `kb diff` — it compares the local `.kb/` worktree to\n  a local "
    "git rev, not this repo to the hub.\n- **ok** → continue.\n"
)

NEW = (
    "## Freshness re-check (run this FIRST, every time)\n\nCheap check "
    "first: when `docs/impl/<ticket-id>-context.md` exists and its\n"
    "`version:` matches the ticket's block, run `kb resolve --status-only\n"
    "<ticket-file>` (no CLI → `kb_resolve`, full output). All **ok** → use "
    "the\ncache; do NOT re-pull pinned content. No cache, version mismatch, "
    "or a\nnon-ok verdict → full `kb resolve <ticket-file>` (else "
    "`kb_resolve`),\nthen rewrite the cache.\n\n- **broken** → STOP. "
    "Blocker: the BA must re-pin. Never implement around a\n  citation that "
    "no longer resolves.\n- **stale** → show BOTH versions, humans decide: "
    "the resolve gives the\n  pinned content and the reason, `kb get "
    "<doc-id> <section> [--level l3]`\n  the current hub version. Do NOT "
    "use `kb diff` — it compares the local\n  `.kb/` worktree to a local "
    "git rev, not this repo to the hub.\n- **ok** → continue.\n"
)

base = Path("src/center_kb/templates/init")
skills = ["dev-implement-ticket", "dev-design", "dev-plan",
          "dev-execute", "dev-handover"]
names = (
    [f"claude-skill-{s}.md" for s in skills]
    + [f"claude-command-{s}.md" for s in skills]
    + [f"copilot-{s}.prompt.md" for s in skills]
    + [f"cursor-{s}.md" for s in skills]
)
for n in names:
    p = base / n
    text = p.read_text(encoding="utf-8")
    assert text.count(OLD) == 1, f"{n}: expected exactly one OLD block"
    p.write_text(text.replace(OLD, NEW), encoding="utf-8", newline="\n")
    print("swapped", n)
```

Before running, verify `OLD` against the real canon: open
`tests/test_templates.py:308` and confirm the literal matches (if it does
not, copy the file's literal — the file wins). Run from the repo root:
`uv run python <scratchpad>/c1_block_swap.py`
Expected: 20 `swapped ...` lines, no assertion error.

- [ ] **Step 2: Re-extract the canon via repr() and update SHARED_BLOCK_TEXT**

House rule: canon is extracted from a landed wrapper, never hand-retyped.

Run:

```bash
uv run python -c "from pathlib import Path; t = Path('src/center_kb/templates/init/claude-skill-dev-design.md').read_text(encoding='utf-8'); first = '## Freshness re-check (run this FIRST, every time)\n'; last = '- **ok** → continue.\n'; s = t[t.index(first):t.index(last) + len(last)]; print(repr(s))"
```

Paste the printed literal as the new value of
`SHARED_BLOCK_TEXT['SHARED-FRESHNESS']` at `tests/test_templates.py:308`.

- [ ] **Step 3: Update the length-ceiling test**

Replace `test_shared_freshness_shed_a_third_of_its_length`
(`tests/test_templates.py:1179-1184`) with:

```python
def test_shared_freshness_stays_within_the_c1_ceiling():
    # C5 shrank the block to 605 characters; C1 (context cache) grew it
    # back to ~950 because the *algorithm* changed — cache + --status-only
    # first, full resolve only on miss — not because the wording got loose.
    # The ceiling still fails on a silent re-expansion into explanatory
    # paragraphs.
    assert len(SHARED_BLOCK_TEXT["SHARED-FRESHNESS"]) <= 1000
```

- [ ] **Step 4: Add the C1 canon needle test**

Add next to the other C-round tests (after
`test_shared_freshness_keeps_the_kb_diff_trap_and_the_three_verdicts`):

```python
# --- C1: the freshness re-check reuses the context cache --------------------


def test_shared_freshness_prefers_the_cache_and_status_only():
    block = _normalised(SHARED_BLOCK_TEXT["SHARED-FRESHNESS"])
    for needle in ("--status-only", "-context.md", "`version:`",
                   "rewrite the cache"):
        assert needle in block, needle
```

- [ ] **Step 5: Run the template suite**

Run: `uv run pytest tests/test_templates.py -v`
Expected: all PASS — in particular
`test_dev_wrappers_carry_byte_identical_shared_blocks` (20 × 3 blocks),
`test_shared_hard_rules_were_not_touched_by_the_c5_round` (untouched),
`test_copilot_and_cursor_wrappers_differ_only_in_their_frontmatter_name`,
and `test_dev_wrappers_end_with_the_next_step_block`.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
git commit -m "feat(templates): SHARED-FRESHNESS checks the context cache first (C1)"
```

---

### Task 4: Orchestrator + handover body edits (8 wrappers)

**Files:**
- Modify: `claude-skill-dev-implement-ticket.md`,
  `claude-command-dev-implement-ticket.md`,
  `copilot-dev-implement-ticket.prompt.md`,
  `cursor-dev-implement-ticket.md`,
  `claude-skill-dev-handover.md`, `claude-command-dev-handover.md`,
  `copilot-dev-handover.prompt.md`, `cursor-dev-handover.md`
  (all under `src/center_kb/templates/init/`)
- Test: `tests/test_templates.py` (two new body-needle tests)

**Interfaces:**
- Consumes: the SHARED-FRESHNESS block from Task 3 (already landed in these
  files); the cache-file format from the spec §2.
- Produces: orchestrator wrappers whose **Resolve** and **Placeholders**
  steps write/fill `docs/impl/<ticket-id>-context.md`; handover wrappers that
  paste the `--status-only` output. Needle tests pin both.

- [ ] **Step 1: Write the failing body-needle tests**

Add to `tests/test_templates.py` after the C1 canon needle test from Task 3.
These assert against `_dev_wrapper_body` (shared blocks stripped), so the
needles must come from the wrappers' own prose, not the shared block:

```python
def test_dev_implement_ticket_writes_the_context_cache():
    for name in _dev_wrapper_names("dev-implement-ticket"):
        text = _dev_wrapper_body(name)
        assert "docs/impl/<ticket-id>-context.md" in text, name
        assert "Placeholder map" in text, name


def test_dev_handover_pastes_the_status_only_output():
    for name in _dev_wrapper_names("dev-handover"):
        text = _dev_wrapper_body(name)
        assert "--status-only" in text, name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -v -k "context_cache or status_only_output"`
Expected: both FAIL (needles absent from every body).

- [ ] **Step 3: Edit the four orchestrator wrappers**

In each `*-dev-implement-ticket*` wrapper, find the **Resolve** step bullet
and append this sentence (re-wrapped at ~72 columns to match the file):

> After a full resolve, write the cache file
> `docs/impl/<ticket-id>-context.md`: the block's `version:`, the resolve
> output verbatim, and a `## Placeholder map` section.

Find the **Placeholders** step bullet and append:

> Record the map in the cache file's `## Placeholder map` table
> (`| placeholder | verified value | evidence (file:line or ref) |`).

Each variant words its steps differently — append the sentences to that
variant's own bullet without rewriting the existing prose. The copilot and
cursor files must receive character-identical bodies (only frontmatter
line 2 differs).

- [ ] **Step 4: Edit the four handover wrappers**

In each `*-dev-handover*` wrapper, find the **Re-check freshness one final
time** step and append:

> Paste the `--status-only` output into the PR's verification section.

Keep the three pinned phrases intact and verbatim: "one final time",
"paste the real output", "completion claim without it is not accepted".
Copilot and cursor bodies stay character-identical.

- [ ] **Step 5: Run the template suite**

Run: `uv run pytest tests/test_templates.py -v`
Expected: all PASS, including the two new needle tests,
`test_dev_handover_rechecks_freshness_and_pastes_real_output`, and the
copilot/cursor body-identity test.

- [ ] **Step 6: Commit**

```bash
git add src/center_kb/templates/init tests/test_templates.py
git commit -m "feat(templates): orchestrator writes the context cache, handover pastes --status-only (C1)"
```

---

### Task 5: Scaffold `docs/impl/.gitignore` + QUICKSTART

**Files:**
- Create: `src/center_kb/templates/init/impl-gitignore.txt`
- Modify: `src/center_kb/initcmd.py:102` (`DEV_TEMPLATES`)
- Modify: `src/center_kb/templates/init/QUICKSTART-dev.md:137-147`
- Test: `tests/test_init.py:1426-1437`, `tests/test_templates.py`

**Interfaces:**
- Consumes: nothing from other tasks (independent).
- Produces: `kb init --kind dev` scaffolds `docs/impl/.gitignore` containing
  `*-context.md`; the dev pinned scaffold count becomes 45.

- [ ] **Step 1: Write the failing tests**

In `tests/test_init.py`, next to
`test_init_kind_dev_scaffolds_exactly_the_stage_a_set`, add:

```python
def test_init_kind_dev_gitignores_the_context_cache(tmp_path: Path):
    init_repo(tmp_path, "dev")
    gi = (tmp_path / "docs" / "impl" / ".gitignore").read_text(encoding="utf-8")
    assert "*-context.md" in gi
```

In `tests/test_templates.py`, add:

```python
def test_quickstart_dev_documents_the_context_cache():
    text = _read_init_template("QUICKSTART-dev.md")
    assert "<ticket-id>-context.md" in text
    assert "docs/impl/.gitignore" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_init.py -v -k gitignores_the_context_cache`
and `uv run pytest tests/test_templates.py -v -k quickstart_dev_documents`
Expected: both FAIL (file not scaffolded; QUICKSTART silent).

- [ ] **Step 3: Create the template resource and register it**

Create `src/center_kb/templates/init/impl-gitignore.txt` with exactly:

```text
# The per-ticket context cache is derivable from one full `kb resolve` —
# never committed (C1). Design and plan files ARE committed.
*-context.md
```

In `src/center_kb/initcmd.py`, `DEV_TEMPLATES`, directly under the
`"docs/impl/.gitkeep": "gitkeep.txt",` row add:

```python
    "docs/impl/.gitignore": "impl-gitignore.txt",
```

- [ ] **Step 4: Bump the pinned scaffold count deliberately**

In `tests/test_init.py:1426-1433`, update the comment and count:

```python
    # 27 (Stage A) + 4 (dev-code-seed's own four-way wrappers) + 12 (the
    # reused kb-summarize/kb-approve/kb-publish rows the seed flow needs,
    # Stage C) + 1 (.claude/settings.json, the usage Stop hook) + 1
    # (docs/impl/.gitignore — C1 keeps the context cache out of git) = 45.
    assert len(expected_files("dev")) == 45
```

- [ ] **Step 5: Update QUICKSTART-dev.md**

In the "Where work lives" list (`QUICKSTART-dev.md:139-141`), add a third
bullet after the plan bullet:

```markdown
- `docs/impl/<ticket-id>-context.md` — the resolved-context cache written
  by `dev-implement-ticket`; gitignored, regenerated by any full
  re-resolve. Not a state marker — it may legitimately be absent.
```

And update the closing sentence of the paragraph below it, which currently
ends "it only ever adds `docs/impl/.gitkeep` so the directory exists before
your first ticket does." → replace that clause with:

```markdown
it only ever adds `docs/impl/.gitkeep` (so the directory exists before your
first ticket does) and `docs/impl/.gitignore` (so the context cache never
lands in a PR).
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_init.py tests/test_templates.py -v`
Expected: all PASS, including the pinned-count test at 45.

- [ ] **Step 7: Commit**

```bash
git add src/center_kb/templates/init/impl-gitignore.txt src/center_kb/initcmd.py src/center_kb/templates/init/QUICKSTART-dev.md tests/test_init.py tests/test_templates.py
git commit -m "feat: scaffold docs/impl/.gitignore — context cache stays out of git (C1)"
```

---

### Task 6: Roadmap bookkeeping + full verification

**Files:**
- Modify: `docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md`

**Interfaces:**
- Consumes: everything landed in Tasks 1–5.
- Produces: the roadmap reflects reality; the whole suite is green.

- [ ] **Step 1: Run the full suite and linters**

Run: `uv run pytest tests`
Expected: all PASS.
Run: `uv run ruff check src tests` (and `uv run ruff format --check src tests`
if the repo config enables it — follow whatever CI runs).
Expected: clean.

- [ ] **Step 2: Update the roadmap**

In `docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md`:

- Tick `- [x]` on **C1** and add a one-line note under it: batch 4 landed
  <date>, spec `2026-08-24-c1-context-cache-design.md`; deviations if any.
- Tick `- [x]` on **A5** with the note: `kb tags` đã tồn tại từ trước tại
  `cli.py` (phát hiện 2026-08-24 khi khảo sát C1) — không tốn effort mới.

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/reviews/2026-08-22-next-steps-roadmap.vi.md
git commit -m "docs: tick C1 (batch 4) and A5 in the roadmap"
```

- [ ] **Step 4: Verify the golden is untouched**

Run: `git diff main...HEAD --stat -- tests-gate/golden src/center_kb/mcp.py`
Expected: empty output — no MCP or golden change anywhere on the branch.
