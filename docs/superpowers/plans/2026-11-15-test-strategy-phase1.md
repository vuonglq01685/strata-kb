# Test Strategy — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Tester writes `docs/test-strategy.md` (scope, tools, a ranked Priority order of missions / stories / KB areas), lints it, publishes it as section `strategy` of `<repo_id>-test`, sees it on the hub's Test Report menu with the computed test order and coverage, and `kb test stale` reports drift on demand and on a schedule.

**Architecture:** A pure module `teststrategy.py` (parse, offline lint, story placement and ordering — text and dataclasses in, results out) and a hub-edge module `strategyhub.py` (reads published strategies and BA plan texts, builds the view, computes drift). `testingest` ships the file; `testui` renders it; `cli.py` adds `kb strategy lint` and `kb test stale`; templates add the file template, rubric axes, the `/tester-strategy` skill and the `kb-test-stale.yml` workflow.

**Tech Stack:** Python 3.12, typer, starlette + jinja2, pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-15-test-strategy-design.md` (phase 1 only; D8 machine order and auto are out).

## Global Constraints

- Version 1.37.0 → 1.37.1; CHANGELOG entry `## 1.37.1 — <release date>`.
- File path `docs/test-strategy.md`; template scaffolded as `docs/templates/test-strategy.md`; hub section id `strategy`, group `strategy`.
- Priority order header row verbatim: `| Rank | Target | Pin | Risk | Why | Types |`.
- Rank: integer ≥ 1 or `last`. Pin: `rev <N>` for an id target, `—` for a KB area. Risk: `High | Medium | Low`.
- Strategy change-log triggers: `kb-context`, `plan`, `coverage`, `priority`, `scope`.
- `> Plan:` is one BA repo id or `—`; with `—` only KB-area rows are allowed.
- Drift codes: `broken-target` (error), `pin-moved`, `kb-context` (stale = warning, broken = error), `coverage`, `tc-revision` (warnings).
- A strategy never gates testing: nothing in `/tester-test-story` or `kb testcase lint` reads it.
- `teststrategy.py` imports no hub, web or CLI module. `strategyhub.py` may import `planstatus`, `testflow`, `ticketstale`; `planstatus`/`testflow` must not import either new module.
- Menu label stays "Test Report".

## Review Focus

1. A strategy section whose text is unreadable or no longer parses on the hub → `/ui/tests` still renders the story list; the panel says the strategy could not be read (Task 8).
2. A story folder named `strategy` under `tests/` → skipped by `kb report-ingest` with a reason, never overwrites the strategy group (Task 5).
3. Dependency cycle between two stories of the same tier → ordering terminates and keeps both (Task 3).
4. `> Plan:` naming a BA repo not on the hub → every id row is `broken-target`, the hub page still renders (Task 4).
5. A KB-area row `[doc §4]` against a story citing `[doc §4.2]` and `[doc §40]` → covers `§4.2`, not `§40` (Task 3).

---

### Task 1: Parse the strategy and the template

**Files:**
- Create: `src/strata_kb/teststrategy.py`
- Create: `src/strata_kb/templates/init/test-strategy-template.md`
- Test: `tests/test_teststrategy.py`

**Interfaces:**
- Produces (all in `teststrategy`):
  - constants `STRATEGY_FILE = "docs/test-strategy.md"`, `SECTION_ID = "strategy"`, `ORDER_HEADING = "## Priority order"`, `ORDER_HEADER = ("Rank", "Target", "Pin", "Risk", "Why", "Types")`, `RISKS = ("High", "Medium", "Low")`, `LAST = "last"`, `TRIGGERS: frozenset[str]` (the five above), `HEADINGS: tuple[str, ...]` = `## Scope & objectives`, `## Test levels & types`, `## Priority order`, `## Environments & data`, `## Entry & exit criteria`, `## Regression policy`, `## Risks & mitigations`, `## Open questions`, `## KB context`, `## Change log`, `## Review record`.
  - `@dataclass(frozen=True) class Area: repo: str | None; doc: str; section: str` with `covers(self, other: Area) -> bool`.
  - `@dataclass(frozen=True) class Row: rank: int | None` (None = `last`) `; target: str; area: Area | None; pin: int | None; risk: str; why: str; types: str`.
  - `@dataclass(frozen=True) class Strategy: plan: str | None` (None for `—`/missing) `; revision: int; rows: tuple[Row, ...]`.
  - `parse(text: str) -> Strategy` — lenient: a row whose Rank is neither int nor `last`, or whose Pin is not `rev N`/`—`, still parses (`rank=None` only for `last`; unparseable rank rows are dropped — lint reports them).
  - `citations(text: str) -> frozenset[Area]` — every `BRACKET_CITE_RE` match in `lintcore.citation_scan_text(text)` plus every ref of a parseable kb-context block (`kbcontext.parse`; `KBContextError` → none).

- [ ] **Step 1: Write the template** `test-strategy-template.md`: `# Test strategy — <product>`, `> Revision: 1`, `> Plan: <ba-repo-id>`, every heading of `HEADINGS` in that order with a one-line HTML-comment hint, the Priority order table with the header row and one example row per target form (as in spec D1), a `Test levels & types` table `| Type | In scope | Tool | Runs on | Notes |`, the kb-context fenced block as in `ticket-template.md`, the planrev change-log table, and the Review record table copied from `test-cases-template.md`.

- [ ] **Step 2: Write the failing tests**

```python
def test_parse_three_target_forms():
    s = teststrategy.parse(STRATEGY)  # fixture text: M-checkout rev 3 rank 1, [acme:srs §4.2] rank 1, M-checkout-US5 rev 2 rank last
    assert s.plan == "ba-one" and s.revision == 1
    assert [(r.target, r.rank, r.pin) for r in s.rows] == [
        ("M-checkout", 1, 3), ("[acme:srs §4.2]", 1, None), ("M-checkout-US5", None, 2)]
    assert s.rows[1].area == teststrategy.Area("acme", "srs", "4.2")

def test_plan_dash_is_none():
    assert teststrategy.parse(STRATEGY.replace("> Plan: ba-one", "> Plan: —")).plan is None

def test_area_covers_ancestor_not_prefix():
    a = teststrategy.Area(None, "srs", "4")
    assert a.covers(teststrategy.Area("acme", "srs", "4.2"))
    assert a.covers(teststrategy.Area(None, "srs", "4"))
    assert not a.covers(teststrategy.Area(None, "srs", "40"))
    assert not teststrategy.Area("x", "srs", "4").covers(teststrategy.Area("y", "srs", "4"))

def test_citations_reads_body_and_kb_context():
    got = teststrategy.citations(TICKET_WITH_CITES)  # body cites [srs §4.2]; kb-context refs acme:srs §5
    assert teststrategy.Area(None, "srs", "4.2") in got
    assert teststrategy.Area("acme", "srs", "5") in got

def test_template_parses_with_example_rows():
    text = resources.files("strata_kb.templates.init").joinpath("test-strategy-template.md").read_text()
    assert len(teststrategy.parse(text).rows) == 3
```

- [ ] **Step 3: Run** `pytest tests/test_teststrategy.py -v` — FAIL (module missing).
- [ ] **Step 4: Implement** `parse`, `citations`, `Area.covers` (same doc; repos equal or either None; `other.section == section` or `other.section.startswith(section + ".")`). Tables via `lintcore.section_body` + `table_rows` + `table_column` (header by name); `> Plan:` / `> Revision:` via regex on `>` lines (`planrev.parse_revision`, default 1).
- [ ] **Step 5: Run** the tests — PASS.
- [ ] **Step 6: Commit** `feat: parse the tester test strategy`.

---

### Task 2: Offline lint and `kb strategy lint`

**Files:**
- Modify: `src/strata_kb/planrev.py` (`check_revision`)
- Modify: `src/strata_kb/teststrategy.py`
- Modify: `src/strata_kb/cli.py` (new `strategy_app`, name `strategy`)
- Modify: `src/strata_kb/templates/init/kb-test-lint.yml`
- Test: `tests/test_teststrategy.py`, `tests/test_planrev.py`

**Interfaces:**
- Consumes: Task 1 `parse`, `HEADINGS`, `TRIGGERS`.
- Produces: `planrev.check_revision(text: str, triggers: frozenset[str] = TRIGGERS) -> list[Issue]` (default keeps every current caller unchanged); `teststrategy.lint(text: str) -> LintReport` (offline only; hub checks live in Task 4). Issue codes: `st-heading`, `st-plan`, `st-row`, `st-duplicate`, `st-placeholder`, `st-kb-context`, `st-review`, plus planrev's messages.

- [ ] **Step 1: Failing tests**

```python
def test_check_revision_custom_triggers():
    text = MISSION_REV2.replace("| scope |", "| priority |")
    assert planrev.check_revision(text) != []           # priority unknown to BA set
    assert planrev.check_revision(text, frozenset({"priority"})) == []

def test_clean_strategy_passes():
    assert teststrategy.lint(STRATEGY).passed

@pytest.mark.parametrize("edit, code", [
    (("| 1 | M-checkout | rev 3 |", "| one | M-checkout | rev 3 |"), "st-row"),     # bad rank
    (("| M-checkout | rev 3 |", "| M-checkout | — |"), "st-row"),                     # id needs rev N
    (("[acme:srs §4.2] | — |", "[acme:srs §4.2] | rev 1 |"), "st-row"),               # area needs —
    (("| High | payment", "| Severe | payment"), "st-row"),                          # risk vocabulary
    (("M-checkout-US5 | rev 2", "M-checkout | rev 3"), "st-duplicate"),
    (("> Plan: ba-one", "> Plan: —"), "st-plan"),                                     # id rows without a plan
    (("    - acme:srs §4.2\n", ""), "st-kb-context"),                                # area not in refs
    (("| pass |", "| fail |"), "st-review"),
])
def test_lint_errors(edit, code):
    report = teststrategy.lint(STRATEGY.replace(*edit))
    assert not report.passed and code in {i.code for i in report.issues}

def test_template_fails_on_placeholders():
    assert "st-placeholder" in {i.code for i in teststrategy.lint(TEMPLATE).issues}

def test_cli_strategy_lint_exit_codes(tmp_path):  # CliRunner: 0 on STRATEGY, 1 on TEMPLATE, --json is JSON
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** `check_revision(..., triggers)`; `lint`: `lintcore.check_title`, `check_headings(text, HEADINGS)`, exact header row, each row's Rank/Target (`BRACKET_CITE_RE.fullmatch` or `planstatus`-style safe name — copy the `[A-Za-z0-9][A-Za-z0-9._-]*` rule, do not import `planstatus`)/Pin/Risk/Why non-empty, duplicates, placeholder regex as in `testcases._PLACEHOLDER_RE`, `> Plan:` present (`st-plan` when missing, or `—` with id rows), kb-context parse + every area target matched by `lintcore.cite_matches_ref` on some ref, `review_passed` (`st-review`), `planrev.check_revision(text, TRIGGERS)`. Run on `visible_body(text)` as `testcases.lint` does.
- [ ] **Step 4: Implement** `kb strategy lint [FILE=docs/test-strategy.md] [--json]` beside `testcase lint` (offline; Task 4 adds `--hub`). Output `report.render("ST")`, exit 0 PASS / 1 FAIL.
- [ ] **Step 5: Workflow** `kb-test-lint.yml`: add `'docs/test-strategy.md'` to the diff pathspec and the case arm `docs/test-strategy.md) cmd="kb strategy lint" ; flags="--hub" ;;`.
- [ ] **Step 6: Run** `pytest tests/test_teststrategy.py tests/test_planrev.py tests/test_init_tester.py -v` — PASS.
- [ ] **Step 7: Commit** `feat: kb strategy lint`.

---

### Task 3: Placement and test order (pure)

**Files:**
- Modify: `src/strata_kb/teststrategy.py`
- Test: `tests/test_teststrategy.py`

**Interfaces:**
- Consumes: Task 1 `Strategy`, `Row`, `Area`.
- Produces:
  - `@dataclass(frozen=True) class StoryInfo: us_id: str; mission_id: str` ("" when unparented) `; depends_on: tuple[str, ...]; retest: bool; citations: frozenset[Area]; mission_citations: frozenset[Area]; plan_pos: int`.
  - `@dataclass(frozen=True) class Placement: story: str; row: Row | None; how: str` (`"id" | "mission" | "area" | "outside"`) `; tier: int` (0 retest, 1 ranked, 2 unranked/outside, 3 `last`).
  - `place(strategy: Strategy | None, story: StoryInfo) -> Placement`.
  - `order(strategy: Strategy | None, stories: list[StoryInfo]) -> list[Placement]`.
  - `empty_rows(strategy: Strategy, stories: list[StoryInfo]) -> list[Row]` (rows no story places on).

- [ ] **Step 1: Failing tests** (build `StoryInfo`s inline with a small helper)

```python
def test_most_specific_match_wins():
    # mission M-checkout rank 1, story M-checkout-US5 rank last, area [srs §4] rank 2
    p = teststrategy.place(S, info("M-checkout-US5", "M-checkout", cites={A("srs", "4.1")}))
    assert (p.how, p.row.target, p.tier) == ("id", "M-checkout-US5", 3)
    assert teststrategy.place(S, info("M-checkout-US1", "M-checkout")).how == "mission"

def test_area_match_uses_ticket_then_mission_cites_best_rank():
    p = teststrategy.place(S2, info("M-x-US1", "M-x", cites=set(), mission_cites={A("srs", "4.2"), A("srs", "7")}))
    assert p.how == "area" and p.row.rank == 1   # §7 row rank 1 beats §4 row rank 2

def test_ticket_cites_shadow_mission_cites():
    p = teststrategy.place(S2, info("M-x-US1", "M-x", cites={A("srs", "4.2")}, mission_cites={A("srs", "7")}))
    assert p.row.rank == 2

def test_order_retest_ranked_unranked_last():
    got = [p.story for p in teststrategy.order(S, [ranked2, outside, retest_unranked, last_one, ranked1])]
    assert got == ["RETEST", "R1", "R2", "OUT", "LAST"]

def test_depends_on_inside_tier_only():
    # A rank 1 depends on B rank 1 -> B first; C rank 1 depends on D rank 3 -> C stays before D
    assert [p.story for p in teststrategy.order(S3, [A_, B_, C_, D_])] == ["B", "A", "C", "D"]

def test_dependency_cycle_terminates():
    got = teststrategy.order(S3, [cyc1, cyc2])
    assert sorted(p.story for p in got) == ["X", "Y"]

def test_no_strategy_is_plan_order():
    assert [p.story for p in teststrategy.order(None, [b_pos1, a_pos0])] == ["a", "b"]

def test_empty_rows_lists_rows_without_stories():
    assert [r.target for r in teststrategy.empty_rows(S, [])] == [r.target for r in S.rows]
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement.** `place`: id row → mission row → area rows over `citations` if any area row covers one of them, else over `mission_citations`; best (lowest) rank, `last` worst; no row → `outside`. Tier: `retest` → 0; else `last` row → 3; ranked → 1; else 2. `order`: group by tier; inside a tier, a priority topological pass — repeatedly emit the lowest `(rank or 0, plan_pos, us_id)` story whose same-tier dependencies are all emitted; when none is free (a cycle), emit the lowest remaining one.
- [ ] **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: test order from the strategy`.

---

### Task 4: Hub edge — plan view, published strategies, drift

**Files:**
- Create: `src/strata_kb/strategyhub.py`
- Modify: `src/strata_kb/testflow.py` (add `strategy_texts`)
- Modify: `src/strata_kb/cli.py` (`kb strategy lint --hub`)
- Test: `tests/test_strategyhub.py`

**Interfaces:**
- Consumes: Tasks 1–3; `planstatus.hub_plans`, `planstatus.plan_docs`, `planstatus._l3_section`, `planstatus._restore` (the same private use `ticketfetch.missions` makes), `ticketstale._kb_context_refs`, `planrev.parse_revision`.
- Produces:
  - `testflow.strategy_texts(hub) -> dict[str, str]` — tester repo id (`doc_id` minus `-test`) → markdown of its `strategy` section (`_section_text`), unreadable skipped.
  - `@dataclass(frozen=True) class PlanView: stories: list[StoryInfo]` (every top-level story: missions' rows with `parent == ""`, plus `unparented`) `; status: dict[str, str]` (us_id → `test_status or status`) `; testable: frozenset[str]; texts: dict[str, str]` (mission and ticket id → restored markdown) `; missions: frozenset[str]`.
  - `plan_view(hub, ba_repo: str | None) -> PlanView` — `None` → empty view.
  - `testable(row: StoryStatus, kids: list[StoryStatus]) -> bool` — False when `row.test_status` is `testing`, `closed` or `reopened`; with kids, every kid has `status == "done"` and no kid `test_status == "reopened"`; without kids, `row.status == "done"`.
  - `@dataclass(frozen=True) class Finding: code: str; level: str; subject: str; message: str`.
  - `strategy_findings(text: str, strategy: Strategy, plan: PlanView, hub) -> list[Finding]` — `broken-target`, `pin-moved`, `kb-context`, `coverage` (testable, not `BUG-`, placed `outside`).
  - `case_findings(tests_dir: Path, plan: PlanView) -> list[Finding]` — `tc-revision` for each `tests/*/test-cases.md` whose `Ticket revision` ≠ `parse_revision(plan.texts[story])`; a story not in `texts` is skipped.
  - `lint_against_hub(text: str, hub) -> list[Issue]` — `broken-target` as error, `pin-moved` as warning (codes `st-broken-target`, `st-pin-moved`).
  - `@dataclass(frozen=True) class StrategyView: tester_repo: str; text: str; strategy: Strategy; order: list[Placement]` (testable only) `; rows: list[tuple[Row, list[tuple[str, str]]]]` (row → (story, status) placed on it, all plan stories) `; empty_rows: list[Row]; outside: list[str]; findings: list[Finding]`.
  - `views(hub) -> list[StrategyView]` — one per published strategy, sorted by tester repo; a strategy whose text raises in parsing is skipped and logged.
  - `story_info` building: `retest` = row or a kid `test_status == "fix-done"`, or `us_id` starts `BUG-`; `citations` = `teststrategy.citations(texts[us_id])`; `mission_citations` from `texts[mission_id]`; `plan_pos` = enumeration order of `hub_plans`.

- [ ] **Step 1: Failing tests** on the `plan_hub` fixture (`tests/conftest.py`; its BA repo is `ba-one`, mission `MISSION_ID`, published ticket `STORY`, first story done in `dev-svc`) with `publish_tests` from `tests/test_testflow.py` extended by a helper `publish_strategy(hub, repo, text)` that adds a `strategy` group to the `<repo>-test` doc.

```python
def test_strategy_texts_reads_published_section(plan_hub):
    publish_strategy(plan_hub, "tester-one", STRATEGY_FOR_PLAN_HUB)
    assert "Priority order" in testflow.strategy_texts(plan_hub)["tester-one"]

def test_plan_view_has_texts_and_testable(plan_hub):
    v = strategyhub.plan_view(plan_hub, "ba-one")
    assert MISSION_ID in v.missions and STORY in v.texts
    assert f"{MISSION_ID}-US1" in v.testable      # done in dev-svc, no report

def test_unknown_plan_repo_makes_every_id_row_broken(plan_hub):
    v = strategyhub.plan_view(plan_hub, "nope")
    found = strategyhub.strategy_findings(TEXT, teststrategy.parse(TEXT), v, plan_hub)
    assert {f.code for f in found} >= {"broken-target"}

def test_pin_moved_when_mission_revision_differs(plan_hub):
    text = TEXT.replace(f"{MISSION_ID} | rev 1", f"{MISSION_ID} | rev 9")
    codes = {f.code for f in strategyhub.strategy_findings(text, teststrategy.parse(text), strategyhub.plan_view(plan_hub, "ba-one"), plan_hub)}
    assert "pin-moved" in codes

def test_coverage_for_testable_story_outside_strategy(plan_hub):
    # a strategy with only a KB-area row nothing cites -> US1 is outside
    ...assert any(f.code == "coverage" and f.subject == f"{MISSION_ID}-US1" for f in found)

def test_case_findings_tc_revision(plan_hub, tmp_path):
    # tests/<STORY>/test-cases.md with "Ticket revision: 7" -> one tc-revision finding
    ...

def test_views_skip_unparseable_strategy(plan_hub):
    publish_strategy(plan_hub, "tester-one", "# nothing\n")
    assert strategyhub.views(plan_hub) == [] or strategyhub.views(plan_hub)[0].strategy.rows == ()
```

- [ ] **Step 2: Run** `pytest tests/test_strategyhub.py -v` — FAIL.
- [ ] **Step 3: Implement** `strategy_texts`, then `strategyhub` per the Interfaces. kb-context drift: `ticketstale._kb_context_refs(text, hub)` → each `StaleRef` → `Finding("kb-context", "error" if broken else "warning", ref.citation, ref.reason)`. Hub `revision` of an id target: `planrev.parse_revision(texts[id]) or 1`.
- [ ] **Step 4: Wire** `kb strategy lint --hub HUB`: `_hub_or_exit(hub, kb_dir)` then append `lint_against_hub` issues to the report.
- [ ] **Step 5: Run** `pytest tests/test_strategyhub.py tests/test_teststrategy.py tests/test_testflow.py -v` — PASS.
- [ ] **Step 6: Commit** `feat: strategy view and drift on the hub`.

---

### Task 5: Ship the strategy in `kb report-ingest`

**Files:**
- Modify: `src/strata_kb/testingest.py` (`run`)
- Test: `tests/test_testingest.py`

**Interfaces:**
- Consumes: `teststrategy.STRATEGY_FILE`, `SECTION_ID`, `lint`.
- Produces: `run(...)` signature unchanged; it reads `repo_root / STRATEGY_FILE` when present.

- [ ] **Step 1: Failing tests**

```python
def test_strategy_section_ships_first(tmp_path):
    write_repo(tmp_path, spec=SPEC, report=REPORT); write_strategy(tmp_path, STRATEGY)
    rep = run_tests(tmp_path)
    assert rep.published[0] == "strategy"

def test_lint_failing_strategy_is_skipped_stories_still_ship(tmp_path):
    write_repo(tmp_path, spec=SPEC); write_strategy(tmp_path, TEMPLATE)
    rep = run_tests(tmp_path)
    assert "strategy" not in rep.published and any(f == "docs/test-strategy.md" for f, _ in rep.skipped)
    assert rep.published  # the story's cases

def test_strategy_alone_publishes_a_doc(tmp_path):
    (tmp_path / "tests").mkdir(); write_strategy(tmp_path, STRATEGY)
    assert run_tests(tmp_path).published == ["strategy"]

def test_story_folder_named_strategy_is_skipped(tmp_path):
    # tests/strategy/test-cases.md -> skipped with reason "reserved name", no group clash
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement**: before the story loop, if the file exists, `teststrategy.lint` it (`planingest.lint_reason` / `fence_reason` as for cases); clean → `_section(SECTION_ID, SECTION_ID, text, f"{len(rows)} priority rows")`, else `out.skipped.append(("docs/test-strategy.md", reason))`. In the loop, skip a folder named `SECTION_ID` with reason `"reserved name 'strategy'"`.
- [ ] **Step 4: Run** `pytest tests/test_testingest.py -v` — PASS (existing determinism test included).
- [ ] **Step 5: Commit** `feat: publish the test strategy with report-ingest`.

---

### Task 6: `kb test stale` and its scheduled workflow

**Files:**
- Modify: `src/strata_kb/cli.py` (new `test_app`, name `test`, command `stale`)
- Create: `src/strata_kb/templates/init/kb-test-stale.yml`
- Modify: `src/strata_kb/initcmd.py` (`TESTER_TEMPLATES`)
- Test: `tests/test_strategyhub.py` (CLI), `tests/test_init_tester.py`

**Interfaces:**
- Consumes: Task 4 `plan_view`, `strategy_findings`, `case_findings`; `teststrategy.parse`.
- Produces: `kb test stale [--file docs/test-strategy.md] [--tests-dir tests] [--hub HUB] [--json | --md]`. Exit **0** no finding, **2** warnings only, **1** any error — the same contract as `kb ticket stale`, so the workflow copies its logic. No strategy file: only `tc-revision` findings, plus one note line. `--md` prints a markdown issue body (heading, one table `| Code | Subject | Message |`).

- [ ] **Step 1: Failing tests**

```python
def test_cli_test_stale_exit_codes(plan_hub, tmp_path, monkeypatch):
    # clean strategy against plan_hub -> 0; pin moved -> 2; unknown target -> 1; --json lists codes

def test_tester_scaffold_has_stale_workflow(tmp_path):
    # kb init --kind tester writes .github/workflows/kb-test-stale.yml containing "kb test stale --md"
```

- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Implement** the command (`_hub_or_exit`; strategy from the working tree, `plan_view(hub, strategy.plan)`).
- [ ] **Step 4: Workflow** `kb-test-stale.yml`: copy `kb-doctor.yml`'s `stale-citations` job (schedule, `issues: write`, pip install, hub env, keep-one-issue step), label `kb-test-stale`, command `kb test stale --md --hub "$STRATA_KB_HUB"`; add it to `TESTER_TEMPLATES`.
- [ ] **Step 5: Run** `pytest tests/test_strategyhub.py tests/test_init_tester.py tests/test_scaffold.py -v` — PASS.
- [ ] **Step 6: Commit** `feat: kb test stale with a scheduled issue`.

---

### Task 7: Scaffold template, rubric axes and `/tester-strategy`

**Files:**
- Modify: `src/strata_kb/initcmd.py` (`TESTER_TEMPLATES`: `docs/templates/test-strategy.md`; skill loop gains `tester-strategy`)
- Modify: `src/strata_kb/templates/init/test-review-rubric.md` (new `## Strategy axes` section)
- Create: `src/strata_kb/templates/init/bodies/tester-strategy.md`, `claude-skill-tester-strategy.md`, `claude-command-tester-strategy.md`, `copilot-tester-strategy.prompt.md`, `cursor-tester-strategy.md`
- Modify: `src/strata_kb/templates/init/QUICKSTART-tester.md`
- Test: `tests/test_tester_skills.py`, `tests/test_init_tester.py`

**Interfaces:**
- Consumes: Tasks 1, 2, 4, 6 (commands the skill runs).
- Produces: the skill, copied by `kb init --kind tester` and `kb upgrade` like the other tester skills.

- [ ] **Step 1: Failing tests** — follow the existing pattern in `tests/test_tester_skills.py`: the four client files exist and include `bodies/tester-strategy.md`; the body names `kb strategy lint`, `kb test stale --json`, `kb context new`, `kb report-ingest`, and the `--amend` mode; the rubric has `## Strategy axes` with the five spec D5 axes, the High-risk-row and evidence axes marked **BLOCKER**; `kb init --kind tester` writes `docs/templates/test-strategy.md` and `.claude/skills/tester-strategy/SKILL.md`.
- [ ] **Step 2: Run** — FAIL.
- [ ] **Step 3: Write** the rubric section (spec D5 list, severity per line) and the skill body, two modes:
  - **New** (spec D9): copy the template to `docs/test-strategy.md`; ask scope and `> Plan:` (`—` when no BA repo); ground with `kb_search` `kinds=["kb","ba"]` presenting all candidates as `ba-mission-plan` step 2 does; read hub status (`kb mission next --from-hub --json`) to see which stories exist and which are `done` with no report; rows by case — docs only: KB areas; plan exists: mission/story rows, KB areas for scope no mission covers; joining late: the untested `done` backlog first by risk. `kb context new` for the block; `kb strategy lint --hub`; Q1 with the Strategy axes in a fresh-context subagent; branch, commit, PR. Never commit `.env`.
  - **`--amend`**: `kb test stale --json`; one proposed change per finding (re-pin, re-point, add row or `last` row, rank change with the evidence), the Tester approves each; bump `> Revision:`, append the change-log row with the trigger set, lint, Q1, PR. State that Auto mode is not available yet.
  - Hard rule: the strategy never blocks `/tester-test-story`.
- [ ] **Step 4: QUICKSTART-tester.md**: one step "Write the test strategy: `/tester-strategy`" before the first `/tester-test-story`, and `/tester-strategy --amend` when the stale issue opens.
- [ ] **Step 5: Run** `pytest tests/test_tester_skills.py tests/test_init_tester.py tests/test_scaffold.py -v` — PASS.
- [ ] **Step 6: Commit** `feat: /tester-strategy skill and strategy review axes`.

---

### Task 8: Hub — Strategy panel, strategy page, story rank

**Files:**
- Modify: `src/strata_kb/web/testui.py`
- Modify: `src/strata_kb/templates/web/tests.html`, `tests_story.html`
- Create: `src/strata_kb/templates/web/tests_strategy.html`
- Test: `tests/test_web_tests.py`

**Interfaces:**
- Consumes: Task 4 `strategyhub.views(hub) -> list[StrategyView]`; `publish_strategy` test helper.
- Produces: route `GET /ui/tests/strategy` (registered **before** `/ui/tests/{story}`), query `repo=<tester-repo-id>`; without `repo` and exactly one view → that view; otherwise 404 "Unknown strategy". `screen="tests"`.

- [ ] **Step 1: Failing tests**

```python
def test_panel_lists_strategy_with_rank_and_badge(web_client_logged_in, plan_hub):
    publish_strategy(plan_hub, REPO, STRATEGY_FOR_PLAN_HUB)
    main = _main(web_client_logged_in.get("/ui/tests").text)
    assert "Strategy" in main and 'href="/ui/tests/strategy?repo=tester-one"' in main

def test_needs_regrounding_badge_on_pin_moved(web_client_logged_in, plan_hub):
    publish_strategy(plan_hub, REPO, STRATEGY_FOR_PLAN_HUB.replace("rev 1", "rev 9"))
    assert "needs re-grounding" in web_client_logged_in.get("/ui/tests").text

def test_strategy_page_shows_order_gaps_and_findings(web_client_logged_in, plan_hub):
    publish_strategy(plan_hub, REPO, STRATEGY_FOR_PLAN_HUB)
    page = _main(web_client_logged_in.get("/ui/tests/strategy").text)
    assert f"{MISSION_ID}-US1" in page          # in the order table
    assert "no ticket yet" in page              # a KB-area row nothing cites

def test_strategy_page_unknown_repo_is_404(web_client_logged_in, plan_hub):
    assert web_client_logged_in.get("/ui/tests/strategy?repo=nope").status_code == 404

def test_no_strategy_keeps_story_list(web_client_logged_in, plan_hub):
    _publish(plan_hub, STORY, _text(STORY, 1))
    page = web_client_logged_in.get("/ui/tests").text
    assert "No test strategy published" in page and STORY in page

def test_story_page_shows_rank(web_client_logged_in, plan_hub):
    # STORY with a report and a strategy ranking its mission 1 -> "Rank 1" and the row target on /ui/tests/<STORY>

def test_unreadable_strategy_does_not_break_list(web_client_logged_in, plan_hub, monkeypatch):
    monkeypatch.setattr(strategyhub, "views", lambda hub: (_ for _ in ()).throw(ValueError("bad")))
    resp = web_client_logged_in.get("/ui/tests")
    assert resp.status_code == 200 and "could not be read" in resp.text
```

- [ ] **Step 2: Run** `pytest tests/test_web_tests.py -v` — FAIL.
- [ ] **Step 3: Implement** in `testui`: `tests_page` adds `strategies=` (each: repo, plan, revision, top 5 ranked rows with matched-story count, `regrounding=bool(findings)`), and `strategy_error=` when `views` raises (catch `KbError`, `ValueError`, `OSError`, log). `strategy_page` renders `tests_strategy.html`: `md_render(view.text)`, then tables Order (tier, rank, story, status, how), Rows (rank → target → stories), "no ticket yet" rows, "outside the strategy" stories, Findings. `story_page` passes `placement` of that story from the first view that holds it. Templates follow `tests.html` panel/queue-row markup and the `badge` classes already used.
- [ ] **Step 4: Run** `pytest tests/test_web_tests.py tests/test_web_mobile_shell.py -v` — PASS.
- [ ] **Step 5: Commit** `feat: test strategy on the Test Report menu`.

---

### Task 9: Release 1.37.1

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (own package version), `CHANGELOG.md`, `README.md` (tester row + command table: `kb strategy lint`, `kb test stale`, `/tester-strategy`), `tests/test_readme.py` (version asserts)
- Test: `tests/test_readme.py`

- [ ] **Step 1:** Update the three version asserts in `tests/test_readme.py` to `1.37.1` and the CHANGELOG first-line date — FAIL.
- [ ] **Step 2:** Bump `pyproject.toml` and the strata-kb entry in `uv.lock`; write the CHANGELOG `## 1.37.1 — <date>` entry (one lead line, bullets: strategy file and `/tester-strategy`, `kb strategy lint`, `kb report-ingest` ships `strategy`, hub panel and page, `kb test stale` + `kb-test-stale.yml`, upgrade note: `kb upgrade` in tester repos adds the template, skill and workflow; no new dependency); README rows.
- [ ] **Step 3: Run** the full suite `pytest -q` — PASS.
- [ ] **Step 4: Commit** `chore: release 1.37.1`.
