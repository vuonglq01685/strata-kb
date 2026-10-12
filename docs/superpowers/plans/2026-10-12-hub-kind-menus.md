# Hub Kinds: Menus and Kind-Filtered Search — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every federation leaf has a kind (`kb | ba | dev`). The registry declares it and publish enforces it. Search filters by it. The hub UI splits into Document, Ticket and Code menus. A child hub sends only `kb` upward.

**Architecture:**
- A new leaf module, `strata_kb/kinds.py`, holds the kind vocabulary, the mapping and the inference rules. Every other layer imports it.
- Kind is stored as an optional field in `_meta.yaml` and in `registry.yaml`.
- Kind is resolved per leaf at load time (`FederatedRepo.kind`) and copied into the search DB's `repos` table. Search filters on it in SQL.
- The UI, CLI, MCP and REST layers only pass `kinds` through.

**Tech Stack:** Python 3, pydantic models, typer CLI, Starlette + Jinja web UI, SQLite FTS5 + sqlite-vec, pytest (+ xdist).

**Spec:** `docs/superpowers/specs/2026-10-12-hub-kind-menus-design.md`. Approved mockup: `docs/superpowers/specs/2026-10-12-hub-kind-menus-mockup.html`.

## Global Constraints

- Hub kinds are exactly `kb`, `ba`, `dev`.
- Repo-config to hub kind mapping: `hub` → `kb`, `child` → `kb`, `ba` → `ba`, `dev` → `dev`.
- Menus are labelled `Document` (`kb`), `Ticket` (`ba`) and `Code` (`dev`).
- Every new model field is optional with a default. An old `registry.yaml`, an old `_meta.yaml` and an old client without `kind` must keep loading and working.
- Unfiltered search (no kind given) returns exactly what it returns today.
- An unknown kind value is an error, never ignored.
  - `UnknownKindError` must **not** subclass `ValueError`. `api_search` and the UI map `ValueError` to "snapshot corrupt" (503).
- Never move or rename anything under `federation/`.
- Registry kind wins on a governed hub. The payload kind is only checked against it.
- Nested leaves (path-id contains `/`) must be `kb`. A non-`kb` nested leaf is ignored by readers (UI and search) and reported by `kb doctor`.
  - This is how "the parent rejects" is enforced. A hub-to-hub publish writes straight into the parent's clone, so the parent runs no code of its own at publish time.
- Tests: `uv run pytest -q -n auto` must pass. Lint: `uv run ruff check .` and `uv run pyright` (both pinned in dev deps).
- Version bump: `1.19.0` → `1.20.0` in `pyproject.toml`, plus a `CHANGELOG.md` entry in the existing style.

## Review Focus

1. **A hub upgraded before its children.**
   - Condition: registry entries have no `kind`, and old clients publish with no `kind` in the meta.
   - Expected: the publish is accepted and the leaf kind comes from inference. No 403, and nothing disappears from the UI.
   - Pinned by Task 2: `test_intake_publish_legacy_client_without_kind_is_accepted`.
2. **A ba/dev leaf left nested under a child hub after an old child hub published.**
   - Expected: it is absent from the Document, Ticket and Code menus and from search, and `kb doctor` on the parent names it.
   - Pinned by Task 1: `test_nested_non_kb_leaf_is_ignored`. Pinned by Task 7: `test_doctor_flags_nested_non_kb_leaf`.
3. **`kb doctor` on a child hub after the upward filter.**
   - Expected: the `fed_src` vs `dest` digest compare uses the filtered tree, so no permanent false drift is reported.
   - Pinned by Task 3: `test_doctor_federation_publish_ignores_filtered_leaves`.
4. **A search cache built before this change (schema `"2"`).**
   - Expected: it rebuilds itself on the first query and kind filters work. No crash from a missing `kind` column.
   - Pinned by Task 4: `test_schema_v2_cache_rebuilds_with_kind`.
5. **`?kind=` with a bad value, on REST and the UI.**
   - Expected: REST returns 400 `unknown_kind`, and the UI renders an empty state (not a 503).
   - Pinned by Task 5: `test_api_search_unknown_kind_400`. Pinned by Task 6: `test_ui_search_unknown_kind_empty_state`.

---

### Task 1: Kind vocabulary, models, leaf resolution

**Files:**
- Create: `src/strata_kb/kinds.py`
- Modify: `src/strata_kb/federation.py` (`FederationMeta` :79, `FederatedRepo` :87, `_load_entry` :288)
- Modify: `src/strata_kb/models.py` (`RegistryEntry` ~:190)
- Test: `tests/test_kinds.py` (new), `tests/test_federation_registry.py`, `tests/test_federation_nested.py`

**Interfaces:**
- Produces, in `kinds.py`:
  - `KB = "kb"`, `BA = "ba"`, `DEV = "dev"`, `HUB_KINDS = (KB, BA, DEV)`
  - `MENU: dict[str, str] = {KB: "Document", BA: "Ticket", DEV: "Code"}`
  - `class UnknownKindError(Exception)` (not a `ValueError`)
  - `class KindMismatchError(Exception)` with attributes `registry_kind` and `repo_kind`
  - `hub_kind(repo_kind: str) -> str` — maps a config kind. `""` raises `UnknownKindError("repo kind is not recorded …")`.
  - `normalize_kinds(values: Iterable[str] | None) -> list[str]` — strips, lowercases, dedupes and sorts. Raises `UnknownKindError` on anything outside `HUB_KINDS`. Empty or None returns `[]`.
  - `infer_kind(docs: Iterable[models.DocEntry]) -> str` — returns `BA` if any doc satisfies `planstatus.is_plan(title, tags)`; else `DEV` if any doc id ends with `-code` or `-svc`; else `KB`.
  - `check_publish_kind(registry_kind: str, repo_kind: str) -> str` — returns the kind to record:
    - Neither set: return `""` (inferred at read time).
    - Only one set: return that one.
    - Both set and they differ: raise `KindMismatchError`.
    - `repo_kind` is a hub kind, already mapped by the caller.
- Produces, on models:
  - `RegistryEntry.kind: str = ""`. A validator accepts `""` or `HUB_KINDS`.
  - `federation.FederationMeta.kind: str = ""`.
  - `federation.FederatedRepo.kind: str` — resolved as `meta.kind or infer_kind(index.docs)`.
  - `federation.registry_kinds(registry: models.Registry) -> dict[str, str]` — maps repo_id to kind and skips empty kinds.
- Behaviour change: `_load_entry` returns `None` and logs a warning when `"/" in path_id` and the resolved kind is not `kb`.

- [ ] **Step 1: Write failing tests** in `tests/test_kinds.py`:
  - `test_hub_kind_maps_config_kinds`: `hub_kind("hub")=="kb"`, `hub_kind("child")=="kb"`, `hub_kind("ba")=="ba"`, `hub_kind("dev")=="dev"`, and `pytest.raises(UnknownKindError)` for `""` and for `"x"`.
  - `test_normalize_kinds`: `normalize_kinds([" Dev","kb","dev"])==["dev","kb"]`, `normalize_kinds(None)==[]`, and `UnknownKindError` for `["code"]`.
  - `test_infer_kind`:
    - a doc titled with `planstatus.TITLE_SUFFIX` and tagged `["plan","generated"]` gives `"ba"`;
    - a doc `x-code` gives `"dev"`, and a doc `x-svc` gives `"dev"`;
    - a doc `release-plan` with no plan tags gives `"kb"`.
  - `test_check_publish_kind`: `("", "")→""`, `("dev","")→"dev"`, `("","ba")→"ba"`, `("kb","kb")→"kb"`, and `("ba","dev")` raises `KindMismatchError`.
  - `test_unknown_kind_error_is_not_value_error`: `assert not issubclass(UnknownKindError, ValueError)`.
- [ ] **Step 2: Write failing tests** for the models:
  - In `tests/test_federation_registry.py`:
    - `test_registry_entry_kind_optional`: `repos: {a/x: x, a/y: {repo_id: y, kind: dev}}` loads; `resolve("a/x").kind==""`; `resolve("a/y").kind=="dev"`; `registry_kinds(...)=={"y":"dev"}`.
    - `test_registry_entry_rejects_bad_kind`: `kind: code` raises `ValidationError`.
  - In `tests/test_federation_nested.py`:
    - `test_leaf_kind_recorded_beats_inferred`: `_meta.yaml` with `kind: kb` and doc `x-code` gives `kind=="kb"`.
    - `test_nested_non_kb_leaf_is_ignored`: `federation/mid/d1/` holds a `-code` doc; `load_federation` does not contain `mid/d1`, while `mid/k1` (a kb doc) is present.
- [ ] **Step 3: Run** `uv run pytest tests/test_kinds.py tests/test_federation_registry.py tests/test_federation_nested.py -q`. Expected: FAIL (`ModuleNotFoundError: strata_kb.kinds` and missing fields).
- [ ] **Step 4: Implement** `kinds.py` and the model fields per the Interfaces above.
  - `kinds.py` imports `planstatus` lazily inside `infer_kind`. This avoids an import cycle; check `tests/test_layering.py`.
- [ ] **Step 5: Run** the same tests, then `uv run pytest tests/test_layering.py tests/test_federation*.py -q`. Expected: PASS.
- [ ] **Step 6: Commit** `feat: kinds vocabulary, optional kind on registry and _meta`.

---

### Task 2: Publish records and enforces kind (snapshot and intake routes)

**Files:**
- Modify: `src/strata_kb/publish.py`:
  - `_snapshot` :452 (gains `kind: str = ""` and writes `FederationMeta(kind=…)`)
  - `publish()` snapshot path, using `_governed_registry` :1150 and `registry_kinds`
  - `plan()` :1200 (refuses when `cfg.kind` is empty)
- Modify: `src/strata_kb/cipublish.py` `run` :138 (adds `"kind": kinds.hub_kind(cfg.kind)` to the meta at :185)
- Modify: `src/strata_kb/web/intake_routes.py` :315-375 (reads optional `meta["kind"]`, checks it against the registry entry, passes it on)
- Modify: `src/strata_kb/intake.py`:
  - `intake_publish` :1546 and `_publish_in_worktree` :1691 gain a `kind: str = ""` param, written into `FederationMeta` at :1800.
  - New `registry_entry_kind(claims: dict, registry: models.Registry) -> str`.
- Modify: `src/strata_kb/cli.py` `publish` :2247 (prints the kind line before any write)
- Test: `tests/test_publish.py`, `tests/test_publish_registry.py`, `tests/test_intake_publish.py`, `tests/test_intake_http.py`, `tests/test_publish_intake_cli.py`

**Interfaces:**
- Consumes: `kinds.hub_kind`, `kinds.check_publish_kind`, `kinds.KindMismatchError`, `kinds.MENU` and `federation.registry_kinds` from Task 1.
- Produces:
  - `publish.kind_line(repo_kind: str) -> str`, returning `"kind: {hub_kind} → hub menu: {MENU[hub_kind]}"`.
  - Intake error on mismatch: `IntakeError(403, "kind mismatch: registry says '<r>' for <repo>, this repo publishes as '<p>' — fix kind: in federation/registry.yaml or the repo's .kb/config.yaml")`.

- [ ] **Step 1: Write failing tests:**
  - `tests/test_publish.py::test_snapshot_records_kind`: a child repo (`kind: dev`) publishing into a local hub gets `_meta.yaml` `kind: dev`.
  - `tests/test_publish.py::test_publish_refuses_unrecorded_kind`: config with no `kind:` makes `plan()` raise `PublishError`, and the message contains `kb init --kind`.
  - `tests/test_publish_registry.py::test_snapshot_kind_mismatch_refused`: registry `{repo_id: x, kind: ba}`, repo `kind: dev`, raises `PublishError` with `"kind mismatch"`. Nothing is written under `federation/x`.
  - `tests/test_publish_registry.py::test_snapshot_registry_kind_recorded`: registry `kind: kb`, repo `kind: child`, gives `_meta.yaml` `kind: kb`.
  - `tests/test_intake_http.py::test_intake_kind_mismatch_403`: registry entry `kind: ba` with meta `{"source_commit":…, "kind":"dev"}` returns 403 whose body contains `kind mismatch`.
  - `tests/test_intake_publish.py::test_intake_publish_legacy_client_without_kind_is_accepted`: meta without `kind` and registry without `kind` gives a PR, and `_meta.yaml` has no `kind` (or `kind: ""`).
  - `tests/test_publish_intake_cli.py::test_ci_publish_sends_kind`: the captured multipart meta has `"kind": "dev"`.
  - `tests/test_cli.py::test_publish_prints_kind_line`: output contains `kind: dev → hub menu: Code` before any `published` line.
- [ ] **Step 2: Run** these tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - In `publish()`, after `rid` is resolved: `kind = kinds.check_publish_kind(registry_kinds.get(rid, ""), kinds.hub_kind(cfg.kind))`, then pass it to `_snapshot`. Map `KindMismatchError` to `PublishError` using the same wording as the intake 403.
  - In the intake route: take `registry_kind` from the registry already loaded in `_caller_rid` (extend it to return the entry kind, or call `intake.registry_entry_kind`). Then `kind = check_publish_kind(registry_kind, kinds.normalize_kinds([meta.get("kind")])[0] if meta.get("kind") else "")`.
    - An `UnknownKindError` on the payload becomes `IntakeError(400, "unknown kind …")`.
    - A `KindMismatchError` becomes the 403 above.
- [ ] **Step 4: Run** the step 1 tests plus `uv run pytest tests/test_publish*.py tests/test_intake*.py -q -n auto`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: publish records kind, refuses registry mismatch`.

---

### Task 3: Child hub sends only `kb` upward

**Files:**
- Modify: `src/strata_kb/publish.py`:
  - `_prepare_hub_to_hub_manifests` :570, or the start of `_snapshot_federation` :950: drop source paths under non-`kb` leaves.
  - `PublishReport` :49: add `skipped_leaves: list[str] = field(default_factory=list)`.
  - `publish_federation` :1357: fills `skipped_leaves`.
- Modify: `src/strata_kb/cli.py`: print `  skipped  <path-id> (kind <k> stays on this hub)` for each skipped leaf.
- Modify: `src/strata_kb/federation.py`: new `kb_only_fed_digest(fed_root: Path) -> str`.
- Modify: `src/strata_kb/doctor/checks/hub.py` `check_federation_publish` :616-655: use the filtered digest on the source side.
- Test: `tests/test_publish_hub.py`, `tests/test_doctor_hub.py`

**Interfaces:**
- Consumes: `FederatedRepo.kind` and `iter_entry_dirs` from Task 1.
- Produces:
  - `federation.non_kb_leaves(fed_root: Path) -> list[str]` — sorted path-ids of leaves whose resolved kind is not `kb`.
  - `federation.kb_only_fed_digest(fed_root: Path) -> str` — same as `_fed_tree_digest` but excludes files under `non_kb_leaves`.

- [ ] **Step 1: Write failing tests:**
  - `test_publish_federation_sends_only_kb`: the source hub has `federation/{k1 (kb), b1 (-plan), d1 (-code)}`. After `publish_federation` to the parent, the parent has `federation/<mid>/k1` and has neither `<mid>/b1` nor `<mid>/d1`. Also `report.skipped_leaves == ["b1","d1"]`.
  - `test_publish_federation_removes_previously_pushed_non_kb`: the parent already has `federation/<mid>/d1` from an earlier publish. After a new publish it is gone and the commit deletes it.
  - `test_publish_federation_all_non_kb_with_existing_dest_refuses`: the source has only `d1` and the parent has `<mid>/k1`. The existing "source federation/ is empty … refusing to wipe" `PublishError` is raised.
  - `test_doctor_federation_publish_ignores_filtered_leaves`: after `test_publish_federation_sends_only_kb`'s publish, `check_federation_publish` on the source hub reports no drift.
- [ ] **Step 2: Run** these tests. Expected: FAIL.
- [ ] **Step 3: Implement** the filter. Use `non_kb_leaves(fed_src)` and remove every `src_man` key that starts with `f"{leaf}/"`, before the diff. The existing deletion path then removes them from `dest`.
- [ ] **Step 4: Run** `uv run pytest tests/test_publish_hub.py tests/test_doctor_hub.py tests/test_federation_nested.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: child hub publishes only kb leaves upward`.

---

### Task 4: Kind in the search index and `query.search`

**Files:**
- Modify: `src/strata_kb/searchdb.py`:
  - `SCHEMA_VERSION` :56 → `"3"`
  - `repos` table :207 gains `kind TEXT NOT NULL DEFAULT ''`
  - the repos upsert in `_sync_conn` :675 writes `repo.kind`
  - `SectionRow` :70 gains `kind: str`, filled by `load_sections` :929 through a join on `repos`
  - `fts_search` :829 and `knn_search` :873 gain `kinds: list[str] | None = None`
- Modify: `src/strata_kb/query.py`:
  - `QueryResult` :48 gains `kind: str = ""`
  - `_search_index` :131, `search_detailed` :327 and `search` :417 gain `kinds: list[str] | None = None`, normalised through `kinds.normalize_kinds`
- Test: `tests/test_searchdb.py`, `tests/test_query.py`

**Interfaces:**
- Consumes: `FederatedRepo.kind` and `kinds.normalize_kinds` from Task 1.
- Produces: `query.search(hub, text, tags=None, budget=2000, semantic=False, use_semantic=True, embedder=None, kinds=None) -> list[QueryResult]` and the same `kinds` kwarg on `search_detailed`. `QueryResult.kind` is in `{"kb","ba","dev"}`.
- SQL filter (fts and the knn post-filter): `AND s.repo_id IN (SELECT repo_id FROM repos WHERE kind IN (?,…))`.

- [ ] **Step 1: Write failing tests:**
  - `tests/test_query.py::test_search_kind_filter`: the fixture hub has a kb doc, a `-plan` doc and a `-code` doc, all containing the word "refund".
    - `search(hub,"refund",kinds=["dev"])` returns only `kind=="dev"` results.
    - `kinds=["kb","ba"]` returns no `dev` result.
    - `kinds=None` returns all three kinds.
  - `tests/test_query.py::test_search_unknown_kind_raises`: `pytest.raises(UnknownKindError)` for `kinds=["code"]`.
  - `tests/test_query.py::test_search_nested_non_kb_never_returned`: a nested `mid/d1` holding a `-code` doc gives no result with `source=="mid/d1"`.
  - `tests/test_searchdb.py::test_schema_v2_cache_rebuilds_with_kind`: create a DB, set `meta.schema_version='2'`, drop the `kind` column by rebuilding `repos` without it, then call `open_fresh`. No error, and a kind-filtered `fts_search` works.
  - `tests/test_searchdb.py::test_kind_change_resyncs`: edit `_meta.yaml` `kind`, then re-query. The fingerprint changes, so the repos row kind updates.
- [ ] **Step 2: Run** these tests. Expected: FAIL.
- [ ] **Step 3: Implement** per the Interfaces above. In the knn leg, over-fetch when `kinds` is set, the same as for tags (`_KNN_OVERFETCH`).
- [ ] **Step 4: Run** `uv run pytest tests/test_searchdb*.py tests/test_query*.py -q -n auto`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: kind-filtered search`.

---

### Task 5: `--kind` on CLI, MCP and REST

**Files:**
- Modify: `src/strata_kb/cli.py` `query` :2102
- Modify: `src/strata_kb/mcp.py` `kb_search` :148
- Modify: `src/strata_kb/web/api.py` `api_search` :227
- Test: `tests/test_cli.py`, `tests/test_mcp.py`, `tests/test_web_api.py`

**Interfaces:**
- Consumes: the `kinds` kwarg on `search_detailed` / `search` from Task 4.
- Produces:
  - CLI: `kb query TEXT --kind kb --kind dev`. The option is `list[str]` and repeatable; an empty list means all kinds. An unknown kind prints the error in red and exits 1.
  - MCP: `kb_search(query: str, tags: list[str] | None = None, budget: int = 2000, kinds: list[str] | None = None)`. The docstring gains one sentence: "`kinds` limits results to `kb` (Document), `ba` (Ticket) or `dev` (Code); omit for all." An unknown kind returns the error text as the tool result, the same way `TooManyTagsError` is handled today.
  - REST: `/api/search?q=…&kind=dev&kind=kb`, read with `getlist`. An unknown kind returns 400 `{"error":"unknown_kind"}`. Each result JSON gains `"kind"`.

- [ ] **Step 1: Write failing tests:**
  - `test_cli_query_kind_filter`: output citations only from the dev doc.
  - `test_cli_query_unknown_kind_exit_1`.
  - `test_mcp_kb_search_kinds`.
  - `test_api_search_kind_filter`: every result has `kind=="ba"`.
  - `test_api_search_unknown_kind_400`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** the three pass-throughs.
- [ ] **Step 4: Run** `uv run pytest tests/test_cli.py tests/test_mcp*.py tests/test_web_api.py -q -n auto`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb query --kind, kb_search kinds, /api/search kind`.

---

### Task 6: Web UI — Document / Ticket / Code menus and search

**Files:**
- Modify: `src/strata_kb/templates/web/_partials/left_rail.html`:
  - nav becomes Overview · Document · Ticket · Code; the "Search" item is removed;
  - the tag cloud uses `shell.tags`, already scoped by the route.
- Modify: `src/strata_kb/web/ui.py`:
  - `_search_screen` :394 adds kind badges and kind chips (`?kind=`);
  - `docs_page` :529 lists `kb` only and does menu search;
  - new `code_page` for `/ui/code`;
  - `home` :489 passes per-kind counts to the overview;
  - `_shell_ctx` :138 scopes the tag cloud to the active menu.
- Modify: `src/strata_kb/web/planui.py` :114-118:
  - routes become `/ui/tickets`, `/ui/tickets/{mission}`, `/ui/tickets/{mission}/{story}`;
  - `/ui/plans…` returns a 301 to the same path under `/ui/tickets`;
  - page titles change from "Plans" to "Tickets";
  - `/ui/tickets?q=` does menu search.
- Modify: `src/strata_kb/web/uidata.py` `store_stats` :166: per-kind doc counts.
- Modify templates: `search.html` (badge per hit, chips row), `docs.html` (menu search box; reused by Code with `menu="code"`), `plans.html` (menu search box), `overview.html` (per-kind counts), and `static/style.css` (`.badge-kb/.badge-ba/.badge-dev` and `.kind-chip`, following the mockup).
- Modify: `src/strata_kb/planstatus.py` `hit_href` — still used for `ba` hits. `without_plans` is replaced at its call sites by a filter on `kind`.
- Test: `tests/test_web_ui.py`, `tests/test_web_plans.py`, `tests/test_web_uidata.py`

**Interfaces:**
- Consumes: `QueryResult.kind`, the `kinds` kwarg on `search`, `FederatedRepo.kind`, `kinds.MENU`.
- Produces:
  - `api.list_docs` dicts gain `"kind"`.
  - `uidata.StoreStats` gains `by_kind: dict[str, int]` (doc counts), default `{}`.
  - Menu search URL shape: `/ui/docs?q=`, `/ui/tickets?q=`, `/ui/code?q=`. Each calls `search(hub, q, kinds=[<menu kind>], …)` and renders hits inside that menu's template.
  - Top search: `/ui?q=…&kind=dev`.
    - The chips are "All n", then one chip per kind with its count from the *unfiltered* result set.
    - With a `kind` set, only that kind is listed.
    - Each hit carries `kind` and `kind_label` (`MENU[kind]`).

- [ ] **Step 1: Write failing tests:**
  - `test_rail_has_document_ticket_code`: `/ui` HTML has links `/ui/docs`, `/ui/tickets` and `/ui/code` with labels `Document`, `Ticket` and `Code`, and has no `href="/ui?q="` nav item.
  - `test_docs_menu_lists_kb_only`: a fixture hub with kb, `-plan` and `-code` docs. `/ui/docs` shows the kb doc only, and `/ui/code` shows the `-code` and `-svc` docs only.
  - `test_menu_search_scoped`: `/ui/code?q=refund` has only dev hits; `/ui/docs?q=refund` has only kb hits.
  - `test_top_search_badges_and_chips`: `/ui?q=refund` shows chips `All 3`, `Document 1`, `Ticket 1` and `Code 1`, and each hit has a badge. `/ui?q=refund&kind=dev` lists only the dev hit and keeps the chip counts.
  - `test_plans_redirects_to_tickets`: `/ui/plans/M-1` returns 301 with `Location: /ui/tickets/M-1`.
  - `test_ui_search_unknown_kind_empty_state`: `/ui?q=refund&kind=code` returns 200 with the empty state.
  - `test_overview_counts_per_kind`.
  - `test_tag_cloud_scoped_to_menu`: a tag that exists only on the `-code` doc is absent from `/ui/docs` and present on `/ui/code`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement.** Follow the approved mockup:
  - section 1 for the rail and the menu search box;
  - section 2 option A for the top-search list, badges and chips.
  - Keep `doc_page` and `section_page` shared. Their "← all documents" back-link points to the menu of the doc's kind.
- [ ] **Step 4: Run** `uv run pytest tests/test_web*.py -q -n auto`. Expected: PASS. Then render `/ui`, `/ui/code` and `/ui?q=…` with the `run` skill and take screenshots against the mockup.
- [ ] **Step 5: Commit** `feat(web): Document / Ticket / Code menus, scoped search, kind chips`.

---

### Task 7: `kb doctor` kind checks (child and hub side)

**Files:**
- Modify: `src/strata_kb/doctor/checks/local.py` `check_kind` :192 — message lists `hub|child|ba|dev`.
- Modify: `src/strata_kb/doctor/checks/hub.py`:
  - new `check_registry_kinds(hub_root: Path) -> list[Issue]` (hub side)
  - new `check_published_kind(kb_dir: Path, handle) -> list[Issue]` (child side)
- Modify: `src/strata_kb/doctor/__init__.py` :113-170 — register both checks in the existing kind dispatch.
- Test: `tests/test_doctor_hubkind.py`, `tests/test_doctor_hub.py`

**Interfaces:**
- Consumes: `registry_kinds`, `FederatedRepo.kind`, `non_kb_leaves` and `hub_kind`.
- Produces these issues (severity per the existing `Issue` levels):
  - hub, warn: `registry entry <repo> has no kind — run kb init --kind hub to fill it`
  - hub, error: `federation/<rid> recorded kind '<a>' but registry says '<b>'`
  - hub, error: `federation/<mid>/<rid> is a nested '<k>' leaf — only kb may be published hub-to-hub; delete it or republish from an upgraded child hub`
  - child, info: `kind: <k> → hub menu: <Menu>`
  - child, warn: `hub registry has no kind for this repo`
  - child, error: `hub registry says '<b>' but this repo is '<a>' — publishing will be refused`

- [ ] **Step 1: Write failing tests:** one test per issue line above, plus:
  - `test_doctor_flags_nested_non_kb_leaf`
  - `test_doctor_registry_kind_clean_when_all_set`
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** both checks.
- [ ] **Step 4: Run** `uv run pytest tests/test_doctor*.py -q -n auto`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(doctor): registry and published kind checks`.

---

### Task 8: Hub upgrade — `kb init --kind hub` fills registry kinds

**Files:**
- Create: `src/strata_kb/registrykind.py`
- Modify: `src/strata_kb/cli.py` `init` :233 — after `init_repo` for `kind == "hub"`, run the upgrade. Add a `--yes` flag to the `init` command.
- Modify: `src/strata_kb/templates/init/QUICKSTART-hub.md` :30-35 — document `{repo_id, kind}` entries.
- Test: `tests/test_registrykind.py` (new), `tests/test_init.py`

**Interfaces:**
- Consumes: `load_registry`, `registry_kinds`, `load_federation`, `FederatedRepo.kind`.
- Produces:
  - `registrykind.propose(federation_dir: Path) -> dict[str, str]` — maps each registry key without a kind to its proposed kind. The proposal is the resolved kind of `federation/<repo_id>`. A container with nested leaves → `kb`. No leaf, or leaves of mixed kinds → `""`, which means ask.
  - `registrykind.apply(registry_text: str, kinds_by_key: dict[str, str]) -> str` — a line-level rewrite:
    - `key: rid` becomes `key: {repo_id: rid, kind: k}`;
    - a mapping entry gains `kind: k` as an indented line;
    - every other line, comments included, is unchanged.
  - CLI flow:
    - print the proposed diff;
    - ask `Write these kinds to federation/registry.yaml? [y/N]`, skipped with `--yes`;
    - ask per entry when the proposal is `""`; in non-interactive mode without `--yes`, exit 1 naming those entries;
    - never commit;
    - print `next: commit federation/registry.yaml and open a PR`.

- [ ] **Step 1: Write failing tests:**
  - `test_apply_preserves_comments`: input with `# owner: team-x` comments, a plain entry and a `{repo_id, workflow}` entry. The output re-parses through `models.Registry` with the right kinds, and every comment line is byte-identical.
  - `test_propose_from_published`: `federation/x` with `-code` → `dev`; `federation/p` with `-plan` → `ba`; `federation/k` with a kb doc → `kb`; `federation/mid/…` nested → `kb`; an unpublished entry → `""`.
  - `test_init_hub_upgrade_yes_writes`: `kb init --kind hub --yes` on a hub with a kind-less registry writes the kinds. Running it again is a no-op.
  - `test_init_hub_upgrade_noninteractive_needs_yes`: exit 1, and the file is unchanged.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** per the Interfaces above. `apply` must round-trip through `models.Registry`. Assert this in the code and abort the write on failure.
- [ ] **Step 4: Run** `uv run pytest tests/test_registrykind.py tests/test_init.py tests/test_cli_hub.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: kb init --kind hub fills registry kinds`.

---

### Task 9: Skills pass the right kind

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/ba-mission-plan.md` :13-16 and `ba-ticket-author.md` :42-50 — search with `--kind kb --kind dev` (MCP: `kinds=["kb","dev"]`).
- Modify: `bodies/dev-implement-ticket.md` :68-75:
  - the own-repo search becomes `--kind dev` plus the existing `--tags <repo_id>-code` / `<repo_id>-svc` restriction;
  - add one `--kind ba` lookup (ticket/mission) and one `--kind kb` lookup (knowledge), each its own query.
- Modify: `bodies/sa-ticket-ground.md` :26-29 — `--kind dev` plus the existing restriction to `<repo-id>-code`.
- Modify: `bodies/kb-code-sync.md` :180 — `kb query … --kind kb`.
- Modify: `templates/init/claude-skill-kb-publish.md`, `cursor-kb-publish.md`, `copilot-kb-publish.prompt.md` — the confirm step shows the `kind: … → hub menu: …` line from `kb publish` and stops if it says unrecorded.
- Test: `tests/test_template_bodies.py`, `tests/test_templates.py`

**Interfaces:**
- Consumes: the CLI and MCP forms from Task 5, and the publish line from Task 2.

- [ ] **Step 1: Write failing tests** in `tests/test_template_bodies.py`. Assert these literal substrings:
  - `--kind kb --kind dev` in both BA bodies;
  - `--kind dev`, `--kind ba` and `--kind kb` in `dev-implement-ticket`;
  - `--kind dev` in `sa-ticket-ground`;
  - `--kind kb` in `kb-code-sync`;
  - `hub menu` in the three kb-publish skill files;
  - no `--kind` in `dev-design`, `dev-plan` or `dev-execute`.
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Edit** the bodies, keeping each body's structure. Regenerate any rendered copies with the repo's tooling if `test_templates.py` checks parity.
- [ ] **Step 4: Run** `uv run pytest tests/test_template*.py tests/test_sa_ticket_ground.py -q`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(skills): agents pass the kind they need`.

---

### Task 10: Docs, changelog, version

**Files:**
- Modify: `README.md` — hub menus; `--kind` on `kb query`; registry `kind`; child-hub upward rule; upgrade steps.
- Modify: `CHANGELOG.md` — new `## 1.20.0 — <date>` entry in the 1.19.0 style. It includes an **Upgrade** bullet:
  - upgrade the hub first;
  - run `kb init --kind hub` and commit the registry;
  - upgrade child hubs; their next publish removes `ba`/`dev` from the parent;
  - old clients keep publishing.
- Modify: `pyproject.toml` version → `1.20.0`; refresh `uv.lock` (it pins `strata-kb` 1.19.0 at its own entry) with `uv lock`.
- Test: `tests/test_readme.py`

- [ ] **Step 1: Run** `uv run pytest tests/test_readme.py -q` after the edits. Expected: PASS.
- [ ] **Step 2: Run** the full suite, `uv run pytest -q -n auto`, and `uv run ruff check .`. Expected: all pass.
- [ ] **Step 3: Commit** `docs: hub kinds — 1.20.0`.
