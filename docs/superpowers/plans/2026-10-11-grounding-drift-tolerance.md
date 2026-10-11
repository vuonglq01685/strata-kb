# Grounding Drift Tolerance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `kb ticket check` stops failing on a moved `Grounded on:` revision alone; it fails only when a cited fact no longer holds, and then tells the reader to re-run `/sa-ticket-ground`.

**Architecture:** The engine (`ticketcheck.check`) runs the fact checks as today, then a new pure module `groundingdrift` classifies a revision mismatch into Tier 1 (note / diff warnings, exit 0) or Tier 2 (one re-ground error). The baseline sections come from an injected `load_drift` callable, implemented in the CLI on top of a new public `ticketstale.drift_refs`, so `ticketcheck` never imports `ticketstale`. Skills (BA ticket author, SA ground, dev implement ticket) and docs follow.

**Tech Stack:** Python 3.12, typer, pytest (`-n auto`), ruff, pyright; `difflib` from stdlib.

**Spec:** `docs/superpowers/specs/2026-10-11-grounding-drift-tolerance-design.md`

## Global Constraints

- No import of `ticketstale` from `ticketcheck` or `groundingdrift` (1.16.3: no import cycles, even function-level).
- `kb ticket stale` output, exit codes and `kb-doctor.yml` unchanged.
- Revision matches ⇒ `kb ticket check` output byte-identical to today.
- Exact copy:
  - Tier 1 note: `grounded @<old>, still valid at @<new> — cited sections unchanged`
  - Tier 1 note when some check was skipped: `grounded @<old>, still valid at @<new> — cited facts that could be checked still hold`
  - Tier 1 no-baseline warning: `grounded @<old>, now @<new> — no baseline to diff, cited facts still hold`
  - Tier 1 unverified warning: `some cited facts could not be verified since @<old> (see warnings above) — check them by hand`
  - Tier 2 error: `grounding drifted since @<old> (now @<new>) and no longer holds — re-run /sa-ticket-ground`
  - Local-fallback Tier 2 note: `checked against the local -code (hub unreachable) — your branch's own changes may cause this; re-run with the hub before sending it back`
- Diff: `difflib.unified_diff`, stripped baseline vs current section, `fromfile=<doc> §<id> @<old>`, `tofile=<doc> §<id> @<new>`, capped at 40 lines, then `… (<n> more lines)`.
- Version 1.18.0 (`pyproject.toml`, `CHANGELOG.md`; refresh `uv.lock` with `uv lock` if it pins the project version).
- Gate: `ruff check . && ruff format --check . && pyright && pytest -q -n auto`.

## Review Focus

1. A cited `db.<table>.<column>` whose column was dropped while `db.<table>` still exists — must be Tier 2 (column check error), not grey zone. Test in Task 2.
2. `load_drift` returns refs where a section is `broken` at the current revision but no fact check errors (id renamed but old id kept as alias) — must stay a grey-zone warning, never an error. Test in Task 2.
3. A ticket with both an open decision and a moved revision — open-decision errors must not trigger the re-ground line. Test in Task 2.
4. A mission plan (`--heading "## Services & order"`) with a moved revision — same tiers. Test in Task 3.
5. `load_drift` raising `GitError` mid-run — degrades to the no-baseline warning, no traceback. Tests in Tasks 2 and 3.

---

### Task 1: `ticketstale.drift_refs` — the baseline lookup as a public function

**Files:**
- Modify: `src/strata_kb/ticketstale.py` (near `architecture_refs`, ~line 208)
- Test: `tests/test_ticketstale.py`

**Interfaces:**
- Produces:
  - `ticketstale.cited_ids(text: str) -> list[str]` — rename of `_cited_ids` (update its one caller).
  - `ticketstale.drift_refs(hub: HubHandle, repo: str | None, doc: str, rev: str, ids: list[str]) -> list[ResolvedRef] | None` — `None` when `_holder` finds no unique holder or `_baseline_commit` finds no commit; otherwise `resolve_refs(hub, KBContext(version=<baseline commit>, refs=[KBRef(holder, doc, id) …]))`, every status included (`ok` too). Lets `gitio.GitError` propagate.
- `architecture_refs` keeps its behaviour; it may call `drift_refs` only if every existing test still passes unchanged.

- [ ] **Step 1: Write failing tests** (reuse `_publish` in the same file)
  - `test_drift_refs_returns_every_status`: publish `rev1` with `svc_a="A"`, `svc_b="B"`; publish `rev2` with `svc_a="A"`, `svc_b="B2"`. `drift_refs(HubHandle(root=fed_hub), "demo", "demo-code", "rev1", ["svc.a", "svc.b"])` → statuses `{"svc.a": "ok", "svc.b": "stale"}`; the `svc.b` ref's `content.strip()` ends with `"B"`.
  - `test_drift_refs_none_when_baseline_missing`: only `rev2` published → `drift_refs(..., "rev1", ["svc.a"]) is None`.
  - `test_drift_refs_none_without_unique_holder`: `repo=None` and doc id held by no repo → `None`.
- [ ] **Step 2: Run** `pytest tests/test_ticketstale.py -q -k drift_refs` → FAIL (`AttributeError: drift_refs`).
- [ ] **Step 3: Implement** `drift_refs` and the `cited_ids` rename.
- [ ] **Step 4: Run** `pytest tests/test_ticketstale.py -q` → all PASS.
- [ ] **Step 5: Commit** `feat: ticketstale.drift_refs exposes the grounding baseline lookup`

---

### Task 2: Engine — tiered revision judgement

**Files:**
- Create: `src/strata_kb/groundingdrift.py`
- Modify: `src/strata_kb/ticketcheck.py` (`check()` ~408-459, `_check_revision` 510-529, `_judge_new`, `_check_open_decisions`)
- Test: `tests/test_ticketcheck.py`, new `tests/test_groundingdrift.py`

**Interfaces:**
- Consumes: `resolve.ResolvedRef` (`ref.section_id`, `status`, `content`).
- Produces:
  - `ticketcheck.LoadDrift = Callable[[str | None, str, str], list[ResolvedRef] | None]` — `(repo, doc_id, rev)`.
  - `ticketcheck.check(text, *, load_doc, heading=HEADING, load_decisions=None, load_drift: LoadDrift | None = None) -> LintReport`.
  - `ticketcheck.DECISION = "decision"` — `Issue.code` on every error raised by `_judge_new` and `_check_open_decisions` (they are not drift).
  - `groundingdrift.judge(doc_id: str, old: str, new: str, drift: list[ResolvedRef] | None, current_section: Callable[[str], str | None], fact_issues: list[Issue], local_fallback: bool) -> tuple[list[Issue], list[str]]` — returns `(issues, notes)` to append. `current_section(section_id)` returns the current L2 text of that section or `None`.
  - `groundingdrift.section_diff(doc_id: str, sid: str, old: str, new: str, before: str, after: str) -> str` — the capped unified diff.

**Behaviour of `check()`:** compute `have`/`rev` as `_check_revision` does. Matching (or empty manifest revision) ⇒ today's path exactly. Mismatch ⇒ no `stale grounding` error; remember `start = len(issues)` before the fact checks, run them unchanged, then call `load_drift` (catch `KbError` ⇒ `None`; `gitio.GitError` is a `KbError`) and `groundingdrift.judge(..., fact_issues=issues[start:], local_fallback="local fallback" in doc.source)` and append its results.

**Behaviour of `judge()`:**
- Drift error = any `fact_issues` item with `level == "error"` and `code != DECISION` (pass the constant in or compare to `"decision"`; `groundingdrift` must not import `ticketcheck`).
- Drift errors present ⇒ one error (Tier 2 copy) + local-fallback note when `local_fallback`. Nothing else.
- Else Tier 1: `skipped = any(i.level == "warning" for i in fact_issues)`.
  - `drift is None` ⇒ no-baseline warning.
  - else for each ref with `status != "ok"`: warning `f"grounded @{old}, now @{new} — §{sid} changed; cited names still hold, review the diff:\n{diff}"` (current text `""` when `current_section` is `None`).
  - every ref `ok` ⇒ note: "cited sections unchanged" copy, or the "could be checked" copy when `skipped`.
  - `skipped` ⇒ also the unverified warning.

- [ ] **Step 1: Write failing tests in `tests/test_groundingdrift.py`** (pure, build `ResolvedRef`/`Issue` by hand)
  - `test_tier2_on_fact_error`: one error `code=""` ⇒ exactly one error, message equals the Tier 2 copy with `old="aaaaaaa"`, `new="bbbbbbb"`.
  - `test_decision_errors_are_not_drift`: only an error with `code="decision"` ⇒ no error returned.
  - `test_tier1_unchanged_note`: two `ok` refs ⇒ no issues, notes == [unchanged copy].
  - `test_tier1_changed_section_warns_with_diff`: one `stale` ref, `content="| a |\n"`, current `"| a |\n| b |\n"` ⇒ one warning containing `"§db.orders changed"`, `"+| b |"`, and `"demo-code §db.orders @aaaaaaa"`.
  - `test_broken_ref_without_fact_error_is_grey_zone`: `status="broken"`, no fact errors ⇒ warning, no error.
  - `test_no_baseline_warns`: `drift=None` ⇒ warning == no-baseline copy.
  - `test_skipped_check_adds_unverified_warning`: fact warning present, all refs ok ⇒ note is the "could be checked" copy and the unverified warning is present.
  - `test_local_fallback_note_only_on_tier2`: `local_fallback=True` with fact error ⇒ note == local-fallback copy; without fact error ⇒ no such note.
  - `test_diff_capped_at_40_lines`: 100-line change ⇒ diff has 41 lines, last starts with `"… ("`.
- [ ] **Step 2: Rewrite engine tests in `tests/test_ticketcheck.py`**
  - Replace `test_revision_mismatch_is_stale_grounding` with `test_revision_mismatch_alone_passes`: `run(ticket(grounding("deadbee")), kb_dir)` ⇒ `errors == []`, a warning equals the no-baseline copy with `old="deadbee"`.
  - `test_revision_mismatch_with_unknown_id_is_tier2`: `grounding("deadbee", Service="svc.gone")` ⇒ errors contain `"unknown id 'svc.gone'"` and the Tier 2 copy.
  - `test_revision_mismatch_with_dropped_column_is_tier2` (Review Focus 1): `Tables="db.restrictive_airspace.no_such_col"`, rev `deadbee` ⇒ column error + Tier 2 copy.
  - `test_open_decision_with_moved_revision_has_no_reground_line` (Review Focus 3): `**{"Open decisions": ["pick a queue"]}`, rev `deadbee` ⇒ open-decision errors present, Tier 2 copy absent.
  - `test_load_drift_used_on_mismatch`: extend `run()` with `load_drift=None` passthrough; a stub returning `[ResolvedRef(... section_id="svc.airspace-service", status="ok" ...)]` ⇒ note == unchanged copy.
  - `test_load_drift_error_degrades` (Review Focus 5): stub raises `gitio.GitError("boom")` ⇒ no-baseline warning, `report.passed`.
  - `test_matching_revision_unchanged`: existing golden test still asserts no note starting with `"grounded @"`.
- [ ] **Step 3: Run** `pytest tests/test_groundingdrift.py tests/test_ticketcheck.py -q` → new tests FAIL.
- [ ] **Step 4: Implement** `groundingdrift.py`, the `DECISION` codes, and the `check()` changes. `current_section` in `check()`: find the section's `file` in `doc.manifest.sections`, `doc.read_group(file)`, `slice_section(text, sid)`.
- [ ] **Step 5: Run** `pytest tests/test_groundingdrift.py tests/test_ticketcheck.py -q` → PASS; `pyright src/strata_kb/groundingdrift.py src/strata_kb/ticketcheck.py` → 0 errors.
- [ ] **Step 6: Commit** `feat: kb ticket check judges a moved grounding revision by its cited facts`

---

### Task 3: CLI wiring — `load_drift` and the parent mission from the hub

**Files:**
- Modify: `src/strata_kb/cli.py` (`ticket check` command, ~2947-3006)
- Test: `tests/test_cli_ticket_check.py`

**Interfaces:**
- Consumes: `ticketstale.drift_refs`, `ticketstale.cited_ids` (Task 1); `ticketcheck.check(..., load_drift=)` (Task 2); `ticketfetch.render(hub, ref) -> str`, `ticketfetch.TicketFetchError`.
- Produces: no new public names.

**Behaviour:**
- `load_drift(repo, doc, rev)`: reuse the hub handle `load_doc` obtained (`_hub_or_reason(hub, kb_dir)`); no hub ⇒ `None`; else `ticketstale.drift_refs(handle, repo, doc, rev, ticketstale.cited_ids(text))`. Import `ticketstale` inside the command body (the CLI already imports lazily).
- `load_decisions(mission_id)`: local `missions/` first (today). Not found locally and a hub is reachable ⇒ `ticketcheck.parse_decisions(ticketfetch.render(handle, mission_id), f"hub:{mission_id}")`; `TicketFetchError` ⇒ `None` (today's behaviour).

- [ ] **Step 1: Write failing tests** (reuse `_publish_to_hub`, `fed_hub`, `run_git`, `code_doc`; publish `demo-code` twice so the hub history holds the baseline: first with the ingested manifest, then with `revision` changed and one cited section's L2 text edited)
  - `test_moved_revision_unchanged_sections_exit_0`: ticket pinned at first revision, second publish changes only `revision` and an uncited section ⇒ exit 0, stdout contains `"cited sections unchanged"`.
  - `test_moved_revision_changed_section_shows_diff`: second publish appends a line to the cited `svc.airspace-service` L2 section ⇒ exit 0, stdout contains `"[warn] grounded @"` and `"+"` diff line.
  - `test_moved_revision_missing_fact_exit_1`: second publish removes a cited route ⇒ exit 1, stdout contains `"re-run /sa-ticket-ground"`.
  - `test_mission_heading_moved_revision` (Review Focus 4): `--heading "## Services & order"` mission citing `svc.airspace-service`, revision moved, section unchanged ⇒ exit 0.
  - `test_parent_mission_read_from_hub_plan`: ticket at `docs/impl/T-1/ticket.md` (no `missions/`), `> Parent mission: M-demo`, `[NEW: D1]` line; hub holds a `<ba>-plan` with `M-demo` whose `D1` is `DECIDED` (build it with `tests/test_ticketfetch.publish_plan`) ⇒ exit 0, no `"parent mission 'M-demo' not found"`.
- [ ] **Step 2: Run** `pytest tests/test_cli_ticket_check.py -q` → new tests FAIL.
- [ ] **Step 3: Implement** the two callables and pass `load_drift=load_drift` to `ticketcheck.check`.
- [ ] **Step 4: Run** `pytest tests/test_cli_ticket_check.py tests/test_ticketstale.py tests/test_ticketcheck.py -q` → PASS.
- [ ] **Step 5: Commit** `feat: kb ticket check reads the grounding baseline and parent mission from the hub`

---

### Task 4: Skills, docs, release

**Files:**
- Modify (BA ticket author — drop "skip `kb ticket check`" for non-`architecture` triggers; run it on every amend, SA only on FAIL; line ~269 "only when `-code` moves after handover" ⇒ "only when `kb ticket check` fails"): `src/strata_kb/templates/init/bodies/ba-ticket-author.md`, `claude-skill-ba-ticket-author.md`, `claude-command-ba-ticket-author.md`, `QUICKSTART-ba.md` (~346). Leave `ba-mission-plan` rules as they are.
- Modify (SA gate step ~116): `bodies/sa-ticket-ground.md` and its flavours — a `[warn] grounded @…` is a PASS; a FAIL carrying `re-run /sa-ticket-ground` means re-ground on the current `-code`.
- Modify (dev step right after **Intake**): `bodies/dev-implement-ticket.md` and every flavour (`claude-skill-`, `claude-command-`, `copilot-dev-implement-ticket.prompt.md`, `cursor-`), plus `QUICKSTART-dev.md` where it lists steps. Step text: run `kb ticket check docs/impl/<id>/ticket.md`; PASS with `[warn]` diff ⇒ show it, the Dev decides, continue; FAIL with `re-run /sa-ticket-ground` ⇒ STOP, blocker for the BA (SA re-grounds), unless the run also printed the local-fallback note ⇒ retry with the hub first; FAIL without it ⇒ report errors to the BA, STOP; no `## Technical grounding` ⇒ skip with a note.
- Modify: `README.md` (`kb ticket check` table row, near line 843-844 and the command list), `CHANGELOG.md` (new `## 1.18.0 — 2026-10-11` section), `pyproject.toml` (`version = "1.18.0"`), `uv.lock` if it carries the version.
- Test: existing template/docs tests (`tests/test_cli_ticket_check.py::test_docs_name_the_check_command`, template-body consistency tests found by `grep -rln "bodies" tests/`).

- [ ] **Step 1: Add a failing test** `test_dev_implement_ticket_runs_ticket_check` in the template test module that already checks skill bodies: every `dev-implement-ticket` flavour contains `kb ticket check docs/impl/<id>/ticket.md` and `re-run /sa-ticket-ground`.
- [ ] **Step 2: Run** it → FAIL.
- [ ] **Step 3: Edit** the files above, keeping flavours word-identical where the existing consistency tests require it.
- [ ] **Step 4: Run the gate** `ruff check . && ruff format --check . && pyright && pytest -q -n auto` → all green.
- [ ] **Step 5: Commit** `docs: skills and README follow the tiered grounding check — 1.18.0`
