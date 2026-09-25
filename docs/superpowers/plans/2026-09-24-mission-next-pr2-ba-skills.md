# `kb mission next` — PR 2 (BA skills, templates, docs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Teach the BA pipeline the greenfield habit (D-rows cited from the architecture document and flipped once, at mission time; a foundation-slice first story) and the "which ticket next" step (`ba-ticket-author` runs `kb mission next`), and document both.

**Architecture:** Text-only changes to the scaffolded skill wrappers (four per skill), the mission template, `QUICKSTART-ba.md`, both `guide-ba` sources and the CHANGELOG, each pinned by string tests in `tests/test_templates.py`. One small code task first: `kb mission next` derives the `-svc` document id from the grounded `-code` document so nested repo ids and unqualified `Grounded on:` lines resolve (PR 1 follow-up).

**Tech Stack:** Markdown templates under `src/strata_kb/templates/init/`, Python 3.12 (`missionnext.py`, `cli.py`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-24-mission-next-greenfield-design.md` — §4 (BA skills, templates, docs), §6 (tests), §7 PR 2. PR 1 (#68, branch `spec/mission-next-greenfield`) shipped the engine this plan documents; this branch is cut from that branch.

## Global Constraints

- Branch `ba-skills/mission-next`, cut from `spec/mission-next-greenfield` (PR 1). The PR targets that branch until #68 merges, then `main`.
- No version bump in `pyproject.toml` / `uv.lock`; CHANGELOG under `## Unreleased`.
- Wrapper invariants the tests pin (do not break them):
  - `ba-mission-plan`: the four wrappers (`claude-skill-`, `claude-command-`, `copilot-…prompt.md`, `cursor-`) are **byte-identical from `## Workflow` to end of file** (`tests/test_init.py::test_mission_wrapper_workflow_bodies_are_byte_identical`); the pipeline line `Intake → Ground → Draft → Split → Ground services → Pin → Lint → Maturity review → Review` stays as is (step 5b is a sub-step, not a pipeline stage).
  - `sa-ticket-ground`: `claude-skill-` == `cursor-` byte for byte; `copilot-` differs from `cursor-` only on frontmatter line 2; the `## Hard rules` block is byte-identical across those three and **is not edited** in this PR; `claude-command-` is a prose summary.
  - `ba-ticket-author`: `copilot-` and `cursor-` differ only on frontmatter line 2; `claude-skill-` keeps its own wording (subagent, IN PARALLEL); `claude-command-` is a prose summary.
  - `dev-handover`: the three SHARED-* blocks (`## Freshness re-check…`, `## Hard rules`, `## Next step…`) are byte-identical canon across 20 dev wrappers — **never edit them**; `copilot-` and `cursor-` differ only on frontmatter line 2; the file must still end with `  Flow order never hides a blocker.\n`.
  - `mission-template.md`: the D2 example row `| D2 | New svc.<name> — <one line> | OPEN | <SA / tech lead> | <US id> |` is pinned verbatim — add a D3 row for the cited form, do not edit D2.
- English template headings and skill text stay English; `guide-ba.vi.md` is written in Vietnamese.
- Every test runs in the foreground (`uv run pytest … -q`); never `run_in_background`. Scoped runs per task; the controller runs the full suite once at the end.
- Commit per task with explicit `git add <paths>` and `git commit -F <msgfile>`; never `git add -A` / `-a` / `.`.
- Before the final commit, run `mcp__gitnexus__detect_changes({scope: "all"})` and report it.
- Test commands: `uv run pytest tests/test_templates.py -q -k <needle>`; `uv run pytest tests/test_init.py -q -k mission_wrapper`; `uv run ruff check src tests`.

---

### Task 1: `kb mission next` derives the `-svc` doc id from the grounded `-code` doc

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/missionnext.py:105-112` (`grounded_repo_id`)
- Modify: `src/strata_kb/cli.py:2735-2740` (`mission_next`, repo id / doc id resolution)
- Modify: `README.md` (BA gates table, `kb mission next` row) and `CHANGELOG.md` (Unreleased bullet)
- Test: `tests/test_missionnext.py`, `tests/test_cli_mission.py`

**Interfaces:**
- Consumes: `ticketcheck.GROUNDED_ON_RE` (groups `repo`, `doc`, `rev`), `ticketcheck.load_from_hub(federation_dir, repo: str | None, doc)` (repo `None` = the unique holder), `ticketcheck.load_doc_dir`.
- Produces:
  - `missionnext.grounded_doc(text: str) -> tuple[str | None, str] | None` — `(repo qualifier or None, doc id)` of the first `- Grounded on:` line, `None` when there is none. Replaces `grounded_repo_id` (removed).
  - `missionnext.svc_doc_id(doc: str) -> str` — `"myflix-code"` → `"myflix-svc"`; a doc not ending in `-code` gets `-svc` appended.
  - CLI: `--repo-id X` → doc `X-svc`, repo `X`; else the first grounded doc → `svc_doc_id(doc)` with its repo qualifier (possibly `None`); neither → note `done: unknown (no repo id — pass --repo-id)` (unchanged text).

- [ ] **Step 1: Write the failing tests**

In `tests/test_missionnext.py`, replace `test_grounded_repo_id` with:

```python
def test_grounded_doc_returns_repo_and_doc():
    assert missionnext.grounded_doc(PLATFORM) == ("myflix", "myflix-code")
    assert missionnext.grounded_doc(CATALOG) is None
    assert missionnext.grounded_doc("- Grounded on: demo-code @ abc1234\n") == (None, "demo-code")
    assert missionnext.grounded_doc("- Grounded on: mid/repo-x:repo-x-code @ abc1234\n") == ("mid/repo-x", "repo-x-code")


def test_svc_doc_id_swaps_the_code_suffix():
    assert missionnext.svc_doc_id("myflix-code") == "myflix-svc"
    assert missionnext.svc_doc_id("repo-x-code") == "repo-x-svc"
    assert missionnext.svc_doc_id("odd") == "odd-svc"
```

Append to `tests/test_cli_mission.py`:

```python
def test_mission_next_nested_repo_id_derives_the_svc_doc_from_the_code_doc(tmp_path, fed_hub):
    root = _ba_layout(tmp_path)
    (root / "missions" / "M-platform.md").write_text(
        PLATFORM_NEXT.replace("demo:demo-code @ abc1234", "mid/repo-x:repo-x-code @ abc1234"),
        encoding="utf-8",
    )
    empty_kb = tmp_path / "ba-kb"
    empty_kb.mkdir()
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"),
        "--kb-dir", str(empty_kb), "--hub", str(fed_hub),
    ])
    assert result.exit_code == 0, result.output
    # the doc id is repo-x-svc, never mid/repo-x-svc
    assert "note: done: unknown (repo-x-svc not published" in result.output
    assert "mid/repo-x-svc" not in result.output


def test_mission_next_unqualified_grounded_on_resolves_locally(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_HUB", raising=False)
    root = _ba_layout(tmp_path, drafted=("M-platform-US1",))
    (root / "missions" / "M-platform.md").write_text(
        PLATFORM_NEXT.replace("demo:demo-code @ abc1234", "demo-code @ abc1234"), encoding="utf-8"
    )
    kb_dir = _svc_kb(tmp_path)
    result = runner.invoke(app, [
        "mission", "next", "--missions-dir", str(root / "missions"), "--kb-dir", str(kb_dir),
    ])
    assert result.exit_code == 0, result.output
    assert "| M-platform-US1 | M-platform | done |  |" in result.output
    assert "done: unknown" not in result.output
```

And extend `test_docs_name_the_next_command` with two assertions (append inside the function):

```python
    assert "`--kb-dir` is read first when it holds `<repo-id>-svc` (a dev machine), the hub second" in readme
    assert "derived from the grounded `-code` document" in changelog
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_missionnext.py tests/test_cli_mission.py -q -k "grounded_doc or svc_doc_id or nested_repo_id or unqualified_grounded or docs_name_the_next"`
Expected: FAIL — `AttributeError: … has no attribute 'grounded_doc'` and the two CLI/doc assertions.

- [ ] **Step 3: Replace `grounded_repo_id` in `missionnext.py`**

Replace lines 105-112 with:

```python
def grounded_doc(text: str) -> tuple[str | None, str] | None:
    """(repo qualifier, doc id) of the first `- Grounded on: [<repo>:]<doc>
    @ <rev>` line (the SA writes it in `## Services & order`), or None.
    The qualifier is None on an unqualified line; `load_from_hub` then
    resolves the doc by its unique holder."""
    for line in text.splitlines():
        m = GROUNDED_ON_RE.match(line.strip())
        if m is not None:
            return m.group("repo"), m.group("doc")
    return None


def svc_doc_id(doc: str) -> str:
    """The curated `-svc` document paired with a grounded `-code` document:
    `myflix-code` → `myflix-svc`. Derived from the doc, not the repo id —
    a nested federation id (`mid/repo-x`) is a path, not a doc prefix."""
    stem = doc[: -len("-code")] if doc.endswith("-code") else doc
    return f"{stem}-svc"
```

- [ ] **Step 4: Rewire `cli.py` `mission_next`**

Replace lines 2735-2740 (`rid = repo_id or next(...)` through `doc_id = f"{rid}-svc"`) with:

```python
    grounded = next((g for g in map(missionnext.grounded_doc, texts) if g), None)
    rid: str | None
    doc_id: str | None
    if repo_id:
        rid, doc_id = repo_id, f"{repo_id}-svc"
    elif grounded is not None:
        rid, doc_id = grounded[0], missionnext.svc_doc_id(grounded[1])
    else:
        rid = doc_id = None
    done: set[str] | None = None
    if doc_id is None:
        notes.append("done: unknown (no repo id — pass --repo-id)")
    else:
```

The rest of the `else:` branch is unchanged (it already uses `doc_id` and passes `rid` to `load_from_hub`, which accepts `None`). Update the `--repo-id` help text to: `"Product repo id whose <repo-id>-svc history marks stories done (default: derived from the missions' 'Grounded on:' line — <x>-code → <x>-svc)"`.

- [ ] **Step 5: README and CHANGELOG**

README, BA gates table, `kb mission next` row: replace the phrase
`` `--repo-id` defaults to the repo in the missions' `Grounded on:` line; without one, or when `-svc` is not on the hub, a note says done is unknown ``
with
`` the `-svc` document is derived from the missions' `Grounded on:` line (`<x>-code` → `<x>-svc`, `--repo-id` overrides); `--kb-dir` is read first when it holds `<repo-id>-svc` (a dev machine), the hub second; no `Grounded on:` line, an unconfigured or unreachable hub, a `-svc` not on the hub, and a missing tickets dir are each a `note:` line, never a red line ``.

CHANGELOG, `## Unreleased`, append to the existing `kb mission next` bullet: ` The `-svc` document id is derived from the grounded `-code` document (`mid/repo-x:repo-x-code` → `repo-x-svc`), so a nested federation repo id and an unqualified `Grounded on:` line both resolve.`

- [ ] **Step 6: Run the tests, lint**

Run: `uv run pytest tests/test_missionnext.py tests/test_cli_mission.py -q && uv run ruff check src tests`
Expected: all PASS, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add src/strata_kb/missionnext.py src/strata_kb/cli.py README.md CHANGELOG.md tests/test_missionnext.py tests/test_cli_mission.py
git commit -F <scratchpad>/msg-pr2-task1.txt
```
Message: `fix: kb mission next derives the -svc doc id from the grounded -code doc`

---

### Task 2: Mission template — cited D-row example, cross-mission `Depends on`, DoR item

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/templates/init/mission-template.md:36-47` (Technology decisions comment + rows), `:67-71` (Sequencing comment), `:105-111` (Definition of Ready)
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: the strings later wrappers and docs refer to: `[<arch-doc> §<section>]` in a D-row Decision cell; the DoR line `Every D-row blocking a story with no dependency is DECIDED (kb mission next shows it ready)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
# --- mission next (spec 2026-09-24 §4.5): templates ---------------------------


def test_mission_template_teaches_the_cited_decision_row():
    text = _read_init_template("mission-template.md")
    decisions = _normalised(lintcore.section_body(text, "## Technology decisions"))
    assert (
        "In a greenfield repo the SA cites the architecture document in the "
        "Decision cell ([<arch-doc> §<section>]); a cited row is a recorded "
        "decision the BA flips once, at mission time (step 5b), not ticket by ticket."
    ) in decisions
    assert (
        "| D3 | New svc.<name> — <one line> [<arch-doc> §<section>] | OPEN | <SA / tech lead> | <US id> |"
        in decisions
    )
    # D2 stays exactly as the earlier pin expects
    assert "| D2 | New svc.<name> — <one line> | OPEN | <SA / tech lead> | <US id> |" in decisions


def test_mission_template_sequencing_allows_cross_mission_dependencies():
    text = _read_init_template("mission-template.md")
    seq = _normalised(lintcore.section_body(text, "## Sequencing"))
    assert "`Depends on` may name a story of another mission (`M-<other>-US<n>`)" in seq
    assert "write `none` for a story that starts first" in seq
    assert "`kb mission next` reads this table" in seq


def test_mission_template_dor_names_the_decided_rows_gate():
    dor = _normalised(lintcore.section_body(_read_init_template("mission-template.md"), "## Definition of Ready"))
    assert "- [ ] Every D-row blocking a story with no dependency is DECIDED (kb mission next shows it ready)" in dor
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "cited_decision_row or cross_mission_dependencies or decided_rows_gate"`
Expected: 3 FAIL.

- [ ] **Step 3: Edit `mission-template.md`**

In the `## Technology decisions` HTML comment, after the sentence `Only a human flips OPEN to DECIDED.` insert:

```
In a greenfield repo the SA cites the architecture document in the
Decision cell ([<arch-doc> §<section>]); a cited row is a recorded
decision the BA flips once, at mission time (step 5b), not ticket by
ticket.
```

After the D2 row add:

```
| D3 | New svc.<name> — <one line> [<arch-doc> §<section>] | OPEN | <SA / tech lead> | <US id> |
```

In the `## Sequencing` HTML comment, after `'| US ID | Title |' is matched verbatim by lint — never add columns.` insert:

```
`Depends on` may name a story of another mission (`M-<other>-US<n>`) —
that is how cross-mission order is written; write `none` for a story
that starts first. `kb mission next` reads this table.
```

In `## Definition of Ready`, after `- [ ] Sequencing covers the whole backlog` insert:

```
- [ ] Every D-row blocking a story with no dependency is DECIDED (kb mission next shows it ready)
```

- [ ] **Step 4: Run the template and mission-lint suites**

Run: `uv run pytest tests/test_templates.py tests/test_missionlint.py tests/test_cli_mission.py -q`
Expected: all PASS (the earlier D2 pin, the Services & order ordering pin and the lint fixtures are unaffected).

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init/mission-template.md tests/test_templates.py
git commit -F <scratchpad>/msg-pr2-task2.txt
```
Message: `docs(templates): mission template teaches cited D-rows, cross-mission Depends on, the decided-rows DoR item`

---

### Task 3: `sa-ticket-ground` — greenfield D-rows cite the architecture document

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md:46-52` (Fill step, `[NEW: D<n>]` bullet), and identically `cursor-sa-ticket-ground.md`, `copilot-sa-ticket-ground.prompt.md`
- Modify: `src/strata_kb/templates/init/claude-command-sa-ticket-ground.md:16-20` (prose)
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: the D-row form from Task 2 (`[<arch-doc> §<section>]` in the Decision cell).
- Produces: the sentence `In a greenfield repo (` … `) every service, table or route the mission needs comes from the architecture document on the hub: cite it in the Decision cell` in the three full wrappers; `cites the architecture document` in all four.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
def test_sa_full_wrappers_cite_the_architecture_document_for_greenfield_rows():
    for name in SA_FULL_WRAPPERS:
        text = _normalised(_read_init_template(name))
        assert (
            "In a greenfield repo (`<repo>-code` has no `svc.*`) every service, "
            "table or route the mission needs comes from the architecture "
            "document on the hub: cite it in the Decision cell"
        ) in text, name
        assert "| D2 | New svc.api — REST gateway [myflix-arch §3.2] | OPEN | <SA / tech lead> | M-x-US1 |" in text, name
        assert "that absence is the BA's signal to keep the row `OPEN`" in text, name


def test_every_sa_wrapper_says_the_proposal_cites_the_architecture_document():
    for name in SA_WRAPPERS:
        assert "cites the architecture document" in _normalised(_read_init_template(name)), name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "cite_the_architecture or cites_the_architecture"`
Expected: 2 FAIL.

- [ ] **Step 3: Edit the three full wrappers identically**

In `claude-skill-sa-ticket-ground.md`, inside the `[NEW: D<n>]` bullet of step 3 **Fill**, after the line ending `never "TBD".` and before `Without a parent mission this degrades to …`, insert (same indentation as the bullet text):

```
     In a greenfield repo (`<repo>-code` has no `svc.*`) every service,
     table or route the mission needs comes from the architecture
     document on the hub: cite it in the Decision cell —
     `| D2 | New svc.api — REST gateway [myflix-arch §3.2] | OPEN | <SA / tech lead> | M-x-US1 |`.
     A proposal the architecture document does not support stays
     concrete and carries no citation; that absence is the BA's signal
     to keep the row `OPEN`.
```

Apply the identical insertion to `cursor-sa-ticket-ground.md` and `copilot-sa-ticket-ground.prompt.md` (their bodies are byte-identical to the skill's below the frontmatter — copy the edited skill body over both, keeping each file's own frontmatter).

- [ ] **Step 4: Edit the command wrapper prose**

In `claude-command-sa-ticket-ground.md`, after `human owner), never park "not built yet" under \`Open decisions\`;` insert ` in a greenfield repo the proposal cites the architecture document in the Decision cell so the BA can flip the row once, at mission time;`.

- [ ] **Step 5: Run the SA suites**

Run: `uv run pytest tests/test_templates.py tests/test_sa_ticket_ground.py tests/test_init.py -q -k "sa_ or SA or sa_ticket"`
Expected: all PASS — including `test_sa_hard_rules_are_byte_identical_across_the_full_wrappers`, `test_sa_claude_skill_and_cursor_wrappers_are_byte_identical` and `test_copilot_and_cursor_ba_sa_wrappers_differ_only_on_frontmatter_line_two`.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/templates/init/claude-skill-sa-ticket-ground.md src/strata_kb/templates/init/cursor-sa-ticket-ground.md src/strata_kb/templates/init/copilot-sa-ticket-ground.prompt.md src/strata_kb/templates/init/claude-command-sa-ticket-ground.md tests/test_templates.py
git commit -F <scratchpad>/msg-pr2-task3.txt
```
Message: `docs(skills): sa-ticket-ground cites the architecture document for greenfield D-rows`

---

### Task 4: `ba-mission-plan` — architecture doc at Intake, foundation slice, step 5b Decide, hard rule

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-ba-mission-plan.md` steps 1, 4, 5 and `## Hard rules`; identically (from `## Workflow` to EOF) `claude-command-ba-mission-plan.md`, `copilot-ba-mission-plan.prompt.md`, `cursor-ba-mission-plan.md`
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: Task 2's DoR wording; Task 3's citation form.
- Produces: the strings `foundation slice`, `5b. **Decide**`, `is a recorded decision` in all four wrappers.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
def test_ba_mission_wrappers_ask_for_the_architecture_document_at_intake():
    for name in BA_MISSION_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "Ask also for the doc-id of the architecture document on the hub" in text, name
        assert "Never ask whether the repo is greenfield" in text, name


def test_ba_mission_wrappers_teach_the_foundation_slice():
    for name in BA_MISSION_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "the first story is the **foundation slice**" in text, name
        assert "every other story `Depends on` it in `## Sequencing`" in text, name
        assert "`Depends on` may name a story of another mission (`M-<other>-US<n>`)" in text, name


def test_ba_mission_wrappers_carry_step_5b_decide():
    for name in BA_MISSION_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "5b. **Decide**" in text, name
        assert "present the whole `## Technology decisions` table to the BA once" in text, name
        assert "You never flip a status." in text, name
        assert "what `kb mission next` reports as `ready`" in text, name


def test_ba_mission_wrappers_carry_the_recorded_decision_hard_rule():
    for name in BA_MISSION_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert (
            "A `[NEW: D<n>]` proposal that cites an architecture section on the "
            "hub is a recorded decision: the BA flips it at mission time, in step "
            "5b, not ticket by ticket. A proposal without a citation stays `OPEN` "
            "with a human owner."
        ) in text, name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "architecture_document_at_intake or foundation_slice or step_5b or recorded_decision"`
Expected: 4 FAIL.

- [ ] **Step 3: Edit `claude-skill-ba-mission-plan.md`, then copy the Workflow body to the other three**

Step 1 **Intake** — after `Ask for target tags (e.g. \`#arinc424 #airspace\`) or an explicit doc-id. Ask, don't guess.` append:

```
   Ask also for the doc-id of the architecture document on the hub, when
   one exists — the SA cites it for every service the mission will
   create. Never ask whether the repo is greenfield; the SA sees that in
   `-code`.
```

Step 4 **Split** — after the paragraph ending `fill \`## Sequencing\` (US ID / Depends on / Size / Notes) — Devs never infer ordering.` append a new paragraph:

```

   **Greenfield:** when the BA says the repo is a skeleton, or step 5
   comes back with no existing `svc.*` (revisit the split then), the
   first story is the **foundation slice** — what the architecture
   document says must exist before any feature story (services,
   database, API skeleton), cited `[<arch-doc> §x]`, outcome-level ACs,
   still at most 10; every other story `Depends on` it in `## Sequencing`.
   The story-size heuristic applies: the foundation may be two stories.
   `Depends on` may name a story of another mission (`M-<other>-US<n>`)
   — that is how cross-mission order is written.
```

After step 5 **Ground services** (after the line `is the BA's to close, never the SA's.`) insert:

```
5b. **Decide** — present the whole `## Technology decisions` table to
   the BA once. The BA flips to `DECIDED` the rows whose citation they
   confirm; a row with no citation keeps `OPEN` and a named owner. You
   never flip a status. A story whose blocking rows are all `DECIDED`
   and whose dependencies are done is what `kb mission next` reports as
   `ready` — the Definition of Ready's decided-rows item is this step.
```

`## Hard rules` — append as the last bullet:

```
- A `[NEW: D<n>]` proposal that cites an architecture section on the
  hub is a recorded decision: the BA flips it at mission time, in step
  5b, not ticket by ticket. A proposal without a citation stays `OPEN`
  with a human owner.
```

Then make the other three wrappers' text from `## Workflow` to end of file byte-identical to the skill's (copy that slice over each; keep each file's own preamble above `## Workflow`).

- [ ] **Step 4: Run the mission wrapper suites**

Run: `uv run pytest tests/test_templates.py -q -k "mission" && uv run pytest tests/test_init.py -q -k "mission_wrapper or mission_plan"`
Expected: all PASS — including `test_mission_wrapper_workflow_bodies_are_byte_identical`, `test_ba_mission_pipeline_line_names_the_new_step` (pipeline line untouched) and `test_no_ba_wrapper_gates_a_later_step_on_grounding_pass`.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init/claude-skill-ba-mission-plan.md src/strata_kb/templates/init/claude-command-ba-mission-plan.md src/strata_kb/templates/init/copilot-ba-mission-plan.prompt.md src/strata_kb/templates/init/cursor-ba-mission-plan.md tests/test_templates.py
git commit -F <scratchpad>/msg-pr2-task4.txt
```
Message: `docs(skills): ba-mission-plan — architecture doc at Intake, foundation slice, step 5b Decide`

---

### Task 5: `ba-ticket-author` — Intake runs `kb mission next`

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-ba-ticket-author.md:19-22` (step 1), `copilot-ba-ticket-author.prompt.md:15-17`, `cursor-ba-ticket-author.md:15-17` (step 1), `claude-command-ba-ticket-author.md:6-8` (prose)
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: `kb mission next` output vocabulary (`ready`, `drafted`, `blocked`).
- Produces: `kb mission next` and `first \`ready\` story` in all four wrappers.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
def test_ba_ticket_wrappers_run_kb_mission_next_at_intake():
    for name in BA_TICKET_WRAPPERS:
        text = _ba_wrapper_text(name)
        assert "run `kb mission next` first" in text, name
        assert "propose the first `ready` story" in text, name
        assert "A `blocked` story may be drafted only with its reasons acknowledged by the BA" in text, name


def test_ba_ticket_full_wrappers_point_a_drafted_story_at_its_file():
    for name in BA_TICKET_AUTHOR_FULL_TEMPLATES:
        assert "A `drafted` story points at its existing file." in _ba_wrapper_text(name), name
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "kb_mission_next_at_intake or drafted_story_at_its_file"`
Expected: 2 FAIL.

- [ ] **Step 3: Edit the three full wrappers**

`claude-skill-ba-ticket-author.md`, step 1 — after `Ask, don't guess — a vague need gets a clarifying question, not a search.` append:

```
   With no business need given and a `missions/` directory present, run
   `kb mission next` first and show its table: propose the first `ready`
   story; the BA may pick another. A `drafted` story points at its
   existing file. A `blocked` story may be drafted only with its reasons
   acknowledged by the BA — carry those reasons into the handover
   verbatim.
```

`copilot-ba-ticket-author.prompt.md` and `cursor-ba-ticket-author.md`, step 1 — after `Ask, don't guess.` append the same six lines (identical text in both files, same indentation as the step).

- [ ] **Step 4: Edit the command wrapper**

`claude-command-ba-ticket-author.md` — replace `when empty, ask for it during Intake.` with:

```
when empty, ask for it during Intake — and, with a `missions/` directory
present, run `kb mission next` first and propose the first `ready` story;
a `blocked` story may be drafted only with its reasons acknowledged by
the BA and carried into the handover.
```

- [ ] **Step 5: Run the ticket-author suites**

Run: `uv run pytest tests/test_templates.py -q -k "ticket_author or ba_ticket or copilot_and_cursor" && uv run pytest tests/test_init.py -q -k "ticket_wrappers"`
Expected: all PASS — including `test_ba_ticket_author_templates_carry_the_nine_pipeline_steps`, `test_ba_ticket_pipeline_line_names_the_new_step` and the copilot/cursor line-2 guard.

- [ ] **Step 6: Commit**

```bash
git add src/strata_kb/templates/init/claude-skill-ba-ticket-author.md src/strata_kb/templates/init/copilot-ba-ticket-author.prompt.md src/strata_kb/templates/init/cursor-ba-ticket-author.md src/strata_kb/templates/init/claude-command-ba-ticket-author.md tests/test_templates.py
git commit -F <scratchpad>/msg-pr2-task5.txt
```
Message: `docs(skills): ba-ticket-author runs kb mission next at Intake`

---

### Task 6: `dev-handover` — `kb svc note` is what makes the story read as done

**Depends on:** none

**Files:**
- Modify: `src/strata_kb/templates/init/claude-skill-dev-handover.md:50-58` (**Record service history** bullet), identically `copilot-dev-handover.prompt.md`, `cursor-dev-handover.md`; `claude-command-dev-handover.md:42-49` (prose)
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: the sentence in every `dev-handover` wrapper body (outside the SHARED-* blocks).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_templates.py`:

```python
def test_dev_handover_says_svc_note_is_what_marks_the_story_done():
    for name in _dev_wrapper_names("dev-handover"):
        body = _dev_wrapper_body(name)
        assert "`kb svc note` is what makes `kb mission next` on the BA side see this story as done" in body, name
        assert "stays `drafted` forever" in body, name
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_templates.py -q -k svc_note_is_what_marks`
Expected: FAIL.

- [ ] **Step 3: Edit the wrappers**

In `claude-skill-dev-handover.md`, `copilot-dev-handover.prompt.md` and `cursor-dev-handover.md`, inside the **Record service history** bullet, after `say so in one line in the PR and record the history there instead.` append (same indentation as the bullet text):

```
  `kb svc note` is what makes `kb mission next` on the BA side see this
  story as done; a ticket that skips it stays `drafted` forever.
```

In `claude-command-dev-handover.md`, after `record the history there instead);` insert ` \`kb svc note\` is what makes \`kb mission next\` on the BA side see this story as done, and a ticket that skips it stays \`drafted\` forever;`.

Do not touch anything under `## Freshness re-check`, `## Hard rules` or `## Next step`.

- [ ] **Step 4: Run the dev wrapper suites**

Run: `uv run pytest tests/test_templates.py -q -k "dev_handover or shared or copilot_and_cursor or next_step"`
Expected: all PASS — including `test_dev_wrappers_carry_byte_identical_shared_blocks`, `test_every_dev_workflow_wrapper_ends_on_the_next_step_block` and `test_copilot_and_cursor_wrappers_differ_only_in_their_frontmatter_name`.

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init/claude-skill-dev-handover.md src/strata_kb/templates/init/copilot-dev-handover.prompt.md src/strata_kb/templates/init/cursor-dev-handover.md src/strata_kb/templates/init/claude-command-dev-handover.md tests/test_templates.py
git commit -F <scratchpad>/msg-pr2-task6.txt
```
Message: `docs(skills): dev-handover names kb svc note as what marks a story done`

---

### Task 7: QUICKSTART-ba, guide-ba (en, vi), CHANGELOG, full suite, graph check

**Depends on:** task 1, task 2, task 3, task 4, task 5, task 6

**Files:**
- Modify: `src/strata_kb/templates/init/QUICKSTART-ba.md` (after the `### Greenfield repos: what \`[NEW: D<n>]\` means` section, ~line 104; a new `## Which ticket next` section before `## Code knowledge on the hub`, ~line 140; the CLI reference list, ~line 428)
- Modify: `docs/src/guide-ba.en.md` (§4.3 end, ~line 270; new §4.4), `docs/src/guide-ba.vi.md` (§4.3 end, ~line 264; new §4.4)
- Modify: `CHANGELOG.md` (`## Unreleased`, new BA-repos bullet)
- Test: `tests/test_templates.py` (append)

**Interfaces:**
- Consumes: everything above.
- Produces: documentation only.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_templates.py`:

```python
def test_quickstart_ba_documents_which_ticket_next_and_the_bulk_decide():
    text = _normalised(_read_init_template("QUICKSTART-ba.md"))
    assert "## Which ticket next" in text
    assert "`kb mission next`" in text
    assert "### Greenfield: decide the D-rows once" in text
    assert "- `kb mission next [--missions-dir <dir>] [--tickets-dir <dir>] [--repo-id <id>] [--hub <url>] [--json]`" in text
    for word in ("`done`", "`drafted`", "`ready`", "`blocked`", "Next:"):
        assert word in text, word


def test_changelog_names_the_ba_side_of_mission_next():
    from pathlib import Path as _P

    changelog = (_P(__file__).resolve().parents[1] / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog[changelog.index("## Unreleased"):changelog.index("## 1.3.0")]
    assert "BA repos:" in unreleased
    assert "step 5b" in unreleased
    assert "foundation slice" in unreleased
    assert "Re-run `kb init --kind ba`" in unreleased
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_templates.py -q -k "which_ticket_next or ba_side_of_mission_next"`
Expected: 2 FAIL.

- [ ] **Step 3: QUICKSTART-ba.md**

After the paragraph ending `keeps a free-text \`[NEW: <reason>]\`: the gate accepts it, but the decision then has no owner.` insert:

```markdown

### Greenfield: decide the D-rows once

In a skeleton repo the SA proposes every D-row from the architecture
document on the hub and cites it in the Decision cell
(`[<arch-doc> §<section>]`). `/ba-mission-plan` then stops at step 5b
(**Decide**) and shows you the whole `## Technology decisions` table once:
flip to `DECIDED` the rows whose citation you confirm; leave a row with no
citation `OPEN` with a named owner. That is the only time you decide —
tickets reference the rows as `[NEW: D<n>]` and `kb ticket check` passes on
them straight away. The first story of such a mission is the **foundation
slice**: what the architecture document says must exist before any feature
story, with every other story depending on it in `## Sequencing`.
```

After the `## Mission plans — for large features` section (before `## Code knowledge on the hub`) insert:

```markdown
## Which ticket next

```bash
kb mission next
```

Read-only. Every backlog story across `missions/*.md` is reported as one
of four states, and the report ends with `Next: <us-id> — <title>`:

| State | Means |
|---|---|
| `done` | the ticket id is in a `hist.*` row of the hub's `<repo-id>-svc` — the Dev ran `kb svc note` at handover and CI published it on merge |
| `drafted` | `tickets/<us-id>.md` exists but the story is not merged yet |
| `ready` | no ticket yet, every `Depends on` story is `done`, every D-row that `Blocks` it is `DECIDED` |
| `blocked` | the reasons are named: `US <id> not done`, `US <id> unknown`, `D<n> OPEN (owner: <x>)` |

`/ba-ticket-author` with no argument runs it first and proposes the first
`ready` story. A story whose dependency is only `drafted` stays `blocked`:
`done` means merged, because only merged code reaches `<repo>-code`.
Cross-mission order is written in `## Sequencing` by naming another
mission's story (`M-<other>-US<n>`) in `Depends on`.

The `-svc` document is found from the missions' `Grounded on:` line
(`<x>-code` → `<x>-svc`, `--repo-id` overrides). A hub that is not
configured or reachable, a `-svc` that is not published yet, or no
`Grounded on:` line at all is a `note:` line above the table — the report
still prints, with nothing marked `done`.

```

In the `## CLI reference` list, after the `kb ticket check …` bullet insert:

```markdown
- `kb mission next [--missions-dir <dir>] [--tickets-dir <dir>] [--repo-id <id>] [--hub <url>] [--json]`
  — which story is `done` / `drafted` / `ready` / `blocked` across
  `missions/`, ending with `Next: <us-id> — <title>`; read-only, exit 0
```

- [ ] **Step 4: guide-ba.en.md**

At the end of `## 4.3 SA grounds the service list` (after `filled later at §3.8.`) append:

```markdown

In a skeleton repo every row the SA appends cites the architecture document
in its Decision cell (`[<arch-doc> §<section>]`), and the agent stops at step
5b — **Decide** — to show you the whole table once. Flip the cited rows you
confirm to `DECIDED`; leave an uncited row `OPEN` with a named owner. You
decide here, once, not ticket by ticket. The first story of such a mission is
the **foundation slice**: what the architecture document says must exist
before any feature story, with every other story depending on it in
`## Sequencing`.

## 4.4 Which ticket next

```bash
kb mission next
```

Every backlog story across `missions/` comes back as `done` (its id is in a
`hist.*` row of the hub's `<repo>-svc`, which `kb svc note` writes at the
developer's handover and CI publishes on merge), `drafted` (the ticket file
exists), `ready` (no ticket, every `Depends on` story done, every D-row that
`Blocks` it `DECIDED`) or `blocked` (with its reasons named). The report ends
with `Next: <us-id> — <title>`; `/ba-ticket-author` with no argument runs it
first and proposes that story. A dependency that is only `drafted` still
blocks: done means merged. Cross-mission order is a `Depends on` cell naming
another mission's story (`M-<other>-US<n>`).

The command is read-only and exits 0 after its report. A hub that is not
configured or reachable, a `-svc` not yet published, or a mission without a
`Grounded on:` line becomes a `note:` line, never a failure — nothing is
marked `done` until the hub can answer.
```

- [ ] **Step 5: guide-ba.vi.md**

At the end of `## 4.3 SA điền danh sách service` (after `điền sau ở mục 3.8.`) append:

```markdown

Ở repo skeleton, mỗi dòng SA thêm vào đều trích dẫn tài liệu architecture
ngay trong ô Decision (`[<arch-doc> §<section>]`), và agent dừng ở bước 5b —
**Decide** — để trình cả bảng cho bạn một lần. Bạn chuyển những dòng có trích
dẫn mà bạn xác nhận sang `DECIDED`; dòng không có trích dẫn giữ `OPEN` kèm
chủ sở hữu. Bạn quyết định ở đây, một lần, không phải từng ticket. Story đầu
tiên của mission như vậy là **foundation slice**: những gì tài liệu
architecture nói phải có trước mọi story tính năng, và mọi story khác phụ
thuộc vào nó trong `## Sequencing`.

## 4.4 Ticket kế tiếp

```bash
kb mission next
```

Mọi story trong backlog của toàn bộ `missions/` được báo là `done` (id của nó
nằm trong một dòng `hist.*` của `<repo>-svc` trên hub — thứ `kb svc note` ghi
lúc lập trình viên bàn giao và CI publish khi merge), `drafted` (đã có file
ticket), `ready` (chưa có ticket, mọi story trong `Depends on` đã done, mọi
dòng D chặn nó đã `DECIDED`) hoặc `blocked` (nêu rõ lý do). Báo cáo kết thúc
bằng `Next: <us-id> — <title>`; `/ba-ticket-author` không kèm tham số sẽ chạy
lệnh này trước và đề xuất đúng story đó. Một phụ thuộc mới chỉ `drafted` vẫn
chặn: done nghĩa là đã merge. Thứ tự giữa các mission được ghi trong ô
`Depends on` bằng story của mission khác (`M-<other>-US<n>`).

Lệnh chỉ đọc và thoát 0 sau khi in báo cáo. Hub chưa cấu hình hoặc không
kết nối được, `-svc` chưa publish, hay mission không có dòng `Grounded on:`
đều thành một dòng `note:`, không bao giờ là lỗi — không story nào được đánh
`done` chừng nào hub chưa trả lời được.
```

- [ ] **Step 6: CHANGELOG**

Under `## Unreleased`, after the existing `kb mission next` bullet, add:

```markdown
- BA repos: `ba-mission-plan` asks for the architecture document's doc-id at Intake, makes the first story of a skeleton repo the **foundation slice**, and stops at a new step 5b (**Decide**) to show the whole `## Technology decisions` table once — the SA now cites the architecture document in every greenfield D-row, and the BA flips the cited rows to `DECIDED` there, not ticket by ticket; `ba-ticket-author` with no argument runs `kb mission next` first and proposes the first `ready` story; `dev-handover` says `kb svc note` is what marks a story done on the BA side. Mission template: cited D-row example, cross-mission `Depends on`, a decided-rows Definition of Ready item. `QUICKSTART-ba.md` and both BA guides gain *Which ticket next* and *decide the D-rows once*. Re-run `kb init --kind ba` (and `--kind dev` for the handover wrapper) to pick up the new text.
```

- [ ] **Step 7: Doc tests, then the full suite and lint in the foreground**

Run: `uv run pytest tests/test_templates.py tests/test_init.py -q`
Expected: PASS.

Run: `uv run pytest -q` (about 20 minutes here; let it block, Bash `timeout: 1500000`) and `uv run ruff check src tests`
Expected: all PASS, ruff clean.

- [ ] **Step 8: Graph change analysis, then commit**

Call `mcp__gitnexus__detect_changes({scope: "all"})` and paste its summary into the task report; re-run on `partial` / `truncated`.

```bash
git add src/strata_kb/templates/init/QUICKSTART-ba.md docs/src/guide-ba.en.md docs/src/guide-ba.vi.md CHANGELOG.md tests/test_templates.py
git commit -F <scratchpad>/msg-pr2-task7.txt
```
Message: `docs: which ticket next and greenfield decide-once in QUICKSTART-ba, both BA guides and the CHANGELOG`

---

## Self-review

- **Spec coverage (§4):** 4.1 `ba-mission-plan` Intake / Split / 5b / hard rule — Task 4; 4.2 `sa-ticket-ground --mission` cited D-rows — Task 3; 4.3 `ba-ticket-author` Intake — Task 5; 4.4 `dev-handover` sentence — Task 6; 4.5 mission template, QUICKSTART, guides, README row — Tasks 2, 7 and (README) Task 1; §6 template needles — each task; PR 1 follow-ups (nested repo id, unqualified `Grounded on:`, README local-first note) — Task 1.
- **Placeholders:** none; every edit carries its exact text and anchor.
- **Invariants:** Task 4 copies the Workflow slice to all four mission wrappers (byte-identity test); Task 3 leaves `## Hard rules` untouched and copies the body to cursor/copilot; Task 6 stays outside the SHARED-* blocks and keeps the closing line; Task 2 adds D3 instead of editing the pinned D2 row.
- **Type consistency:** `grounded_doc -> tuple[str | None, str] | None` and `svc_doc_id(doc) -> str` are used with those signatures in Task 1's CLI hunk and tests; `_ba_wrapper_text`, `_dev_wrapper_body`, `_normalised`, `SA_WRAPPERS`, `SA_FULL_WRAPPERS`, `BA_MISSION_WRAPPERS`, `BA_TICKET_WRAPPERS`, `BA_TICKET_AUTHOR_FULL_TEMPLATES`, `_dev_wrapper_names` all already exist in `tests/test_templates.py`.
