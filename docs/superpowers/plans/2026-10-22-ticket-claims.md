# Ticket Claims Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Several Devs (mostly `kb auto run` loops) on one dev repo, on different machines, work the hub's `ready` tickets in parallel without picking the same one, with the claim visible and admin-releasable on the hub's Ticket menu.

**Architecture:** A SQLite claim store on the hub beside the Q&A store, a bearer-auth JSON API over it, a `kb claim` CLI client (holding each claim's secret token in `.kb/auto/claims.json`), the dev runner claiming before it works and heartbeating from a side thread, the dev skills calling `kb claim`, the Ticket pages rendering claims with an admin-only Release, and a `kb publish` guard so concurrent publishes never drop a `hist.*` row.

**Tech Stack:** Python 3, SQLite (`sqlite3`), Starlette routes + Jinja templates (existing web app), typer CLI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-22-ticket-claims-design.md`

## Global Constraints

- Claim TTL default **14400 s (4 h)**, hub env `STRATA_KB_CLAIM_TTL`; runner heartbeat default **900 s**, `auto.claim_heartbeat` in `.kb/config.yaml`.
- All claim timestamps come from the **hub clock**; clients never send times.
- One held claim per `(repo, ticket)`; the grant is atomic (`BEGIN IMMEDIATE` + partial unique index).
- Held = `closed_at IS NULL` and (`state = 'stopped'` or (`phase IN ('review','publishing')` and `pr != ''`) or `last_seen > now - ttl`).
- Phases, exactly: `claimed`, `design`, `plan`, `execute`, `handover`, `review`, `publishing`, `waiting-qa`. States: `active`, `stopped`.
- Claims are keyed like Q&A: `repo` = the BA plan repo from `ticketfetch.find`, `ticket` = the id.
- Holder default `<git config user.name>@<hostname>`; env `STRATA_KB_CLAIM_AS` or `--as` overrides.
- Only the `admin` role may release another holder's claim from the web; POSTs carry CSRF.
- Old hub (bare 404 on `/api/claims`): `hub server has no /api/claims — upgrade it to strata-kb 1.31.0 or later`; the runner stops, never falls back.
- Publish guard message, exactly: `behind origin/<default> — pull, then kb publish`.
- CLI exit codes: `0` ok, `1` error, `3` taken or lost.
- Release version **1.31.0**.
- BA repos get no claims; `dev-test-workflow` tasks carry no claim.

## Review Focus

1. Two machines claim the same ticket in the same instant → exactly one gets it, the other gets `taken` with the winner's holder (Task 1 `test_concurrent_take_has_one_winner`).
2. A claim whose `last_seen` is exactly `now - ttl` → expired, not held (Task 1 `test_expiry_boundary`).
3. A ticket id published by two BA repos (`US1` in both) → API answers 400 `ambiguous` telling the caller to pass `<repo>:<id>`, never claims one at random (Task 2 `test_take_ambiguous_ticket`).
4. A machine with no `.kb/auto/claims.json` entry (fresh clone, other machine) runs `kb claim update` → `no claim held for <id> on this machine — run kb claim take <id>`, exit 1, no traceback (Task 3 `test_update_without_local_claim`).
5. The hub is unreachable for one heartbeat → warning logged, claim **not** marked lost; only a `lost` answer marks it lost (Task 4 `test_beat_transient_error_is_not_lost`).

---

### Task 1: Claim store

**Files:**
- Create: `src/strata_kb/ticketclaim.py`
- Test: `tests/test_ticketclaim.py`

**Interfaces:**
- Produces:
  - `PHASES: tuple[str, ...]` (the 8 phases), `WORKING_PHASES = ("claimed","design","plan","execute","handover","waiting-qa")`, `STATES = ("active","stopped")`, `DEFAULT_TTL = 14400`.
  - `@dataclass(frozen=True) Claim(id: int, repo: str, ticket: str, holder: str, phase: str, state: str, pr: str, stop_reason: str, claimed_at: str, last_seen: str, closed_at: str | None, closed_by: str | None, close_reason: str | None)` — no token field.
  - `class ClaimError(KbError)`; `class ClaimTaken(ClaimError)` with `.claim: Claim`; `class ClaimLost(ClaimError)` with `.close_reason: str`, `.closed_by: str`; `class BadClaimToken(ClaimError)`; `class UnknownClaim(ClaimError)`.
  - `claims_db_path(hub_root: Path) -> Path` → `hub_root / ".kb-qa" / "claims.db"`.
  - `class ClaimStore(db_path: Path, ttl: int = DEFAULT_TTL, now: Callable[[], datetime] = <utc now>)` with:
    - `take(repo: str, ticket: str, holder: str, token: str | None = None) -> tuple[Claim, str]` — new claim → fresh token; held claim with a matching `token` → that claim and the same token; held by another token → `ClaimTaken`.
    - `update(claim_id: int, token: str, *, phase: str | None = None, pr: str | None = None, state: str | None = None, stop_reason: str | None = None) -> Claim` — bumps `last_seen`; closed or no longer held → closes it (`expired`) if needed and raises `ClaimLost`.
    - `release(claim_id: int, token: str, reason: str) -> None` — `closed_by = holder`, `close_reason = "released: <reason>"`.
    - `admin_release(claim_id: int, admin: str, reason: str) -> None` — `closed_by = admin`, `close_reason = "admin: <reason>"`.
    - `pr_closed(claim_id: int, pr: str) -> Claim` — only when `pr` equals the claim's `pr` (else `ClaimError("pr_mismatch")`); sets `phase = "execute"`, `pr = ""`, `last_seen = now`.
    - `held(repo: str = "", ticket: str = "") -> list[Claim]` — closes unheld open rows with `close_reason = "expired"` first.
    - `close_done(done: set[tuple[str, str]]) -> None` — closes held claims for those `(repo, ticket)` with `close_reason = "done"`, `closed_by = "hub"`.
    - `last_closed(repo: str, ticket: str) -> Claim | None`.

- [ ] **Step 1: Write the failing tests** (clock injected as a mutable `now` fixture; store at `tmp_path / "claims.db"`, `ttl=100`)

```python
def test_take_then_taken(store):
    claim, token = store.take("ba-one", "US1", "a@m1")
    assert (claim.phase, claim.state, claim.holder) == ("claimed", "active", "a@m1")
    with pytest.raises(ClaimTaken) as exc:
        store.take("ba-one", "US1", "b@m2")
    assert exc.value.claim.holder == "a@m1"

def test_retake_with_own_token_is_same_claim(store):
    claim, token = store.take("ba-one", "US1", "a@m1")
    again, token2 = store.take("ba-one", "US1", "a@m1", token=token)
    assert (again.id, token2) == (claim.id, token)

def test_concurrent_take_has_one_winner(tmp_path):
    # 8 threads, each its own ClaimStore on the same file, all take US1
    ...
    assert len(winners) == 1 and len(taken) == 7

def test_expiry_boundary(store, clock):
    claim, _ = store.take("ba-one", "US1", "a@m1")
    clock.advance(99); assert store.held()
    clock.advance(1); assert store.held() == []
    assert store.last_closed("ba-one", "US1").close_reason == "expired"

def test_update_bumps_last_seen_and_keeps_alive(store, clock): ...  # advance 90, update, advance 90 → still held
def test_update_after_expiry_raises_lost(store, clock): ...         # ClaimLost(close_reason="expired")
def test_update_bad_token(store): ...                               # BadClaimToken
def test_review_with_pr_never_expires(store, clock): ...            # phase review + pr, advance 10_000 → held
def test_publishing_with_pr_never_expires(store, clock): ...
def test_stopped_never_expires(store, clock): ...                   # state stopped, stop_reason "ci-red x"
def test_stopped_resumed_to_active(store, clock): ...               # update(state="active") → state active, ttl applies again
def test_pr_closed_restarts_clock(store, clock): ...                # review+pr → pr_closed → phase execute, pr "", expires 100 s later
def test_pr_closed_wrong_pr(store): ...                             # ClaimError, message contains "pr_mismatch"
def test_release_frees_ticket(store): ...                           # release → take by b@m2 succeeds
def test_admin_release(store): ...                                  # last_closed: closed_by "root", close_reason "admin: gone home"
def test_close_done(store): ...                                     # close_done({("ba-one","US1")}) → held() == [], reason "done"
def test_rejects_bad_input(store): ...                              # phase "coding", state "paused", holder "" / 101 chars, pr "ftp://x" → ClaimError
def test_token_not_stored_in_clear(store, tmp_path): ...            # raw token bytes absent from the db file
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ticketclaim.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'strata_kb.ticketclaim'`

- [ ] **Step 3: Implement `ticketclaim.py`** in the `ticketqa.QaStore` style (one short-lived connection per call, `closing(...)`, `BEGIN IMMEDIATE` around read-then-write). Schema: `claims` table with the `Claim` columns plus `token_hash TEXT NOT NULL` (sha256 hex of the token; compare with `hmac.compare_digest`), and `CREATE UNIQUE INDEX IF NOT EXISTS one_open_claim ON claims(repo, ticket) WHERE closed_at IS NULL`. Token: `secrets.token_urlsafe(32)`. Timestamps ISO-8601 UTC seconds, like `ticketqa._now`. Limits: holder ≤ 100 chars non-empty, reasons ≤ 1000, `pr` empty or `https://…` ≤ 500.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ticketclaim.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/ticketclaim.py tests/test_ticketclaim.py
git commit -m "feat(claims): hub claim store with atomic grant and lazy expiry"
```

---

### Task 2: Hub claims API

**Files:**
- Create: `src/strata_kb/web/claim_api.py`
- Modify: `src/strata_kb/web/app.py:90-102` (add `routes += claim_api.build_claim_routes(config)`)
- Test: `tests/test_api_claims.py` (fixtures `web_client`, `hub_with_ticket`, `token` from `tests/conftest.py`, as in `tests/test_api_questions.py`)

**Interfaces:**
- Consumes: Task 1 `ClaimStore`, `claims_db_path`, errors; `ticketfetch.find(hub, ref) -> (repo, doc, l3)`, `ticketfetch.split_ref`; `planstatus.next_from_hub(hub)`; `api.hub_handle`, `api._error`, `hub_serves_own_checkout`, `QA_NEEDS_HUB_DETAIL` (as `questions` in `web/api.py` uses them).
- Produces: `build_claim_routes(config: ServerConfig) -> list[Route]`; `claim_ttl_from_env() -> int` (reads `STRATA_KB_CLAIM_TTL`, default 14400, non-positive or non-integer → default with a logged warning). Wire format, used by Task 3:
  - `POST /api/claims` `{"ticket", "holder", "token"?}` → `201 {"claim": {...}, "token": "..."}` new, `200` same body for a re-claim; `409 {"error": "taken", "claim": {...}}`; `404 {"error": "unknown_ticket"}`; `400 {"error": "ambiguous", "detail": "..."}`.
  - `GET /api/claims?repo=&ticket=` → `200 {"claims": [...]}` (runs `close_done` with every `done` id from `next_from_hub` first; a plan read failure skips that step, never fails the GET).
  - `PATCH /api/claims/{id}` `{"token", "phase"?, "pr"?, "state"?, "stop_reason"?}` → `200 {"claim"}`; `409 {"error": "lost", "close_reason", "closed_by"}`; `403 {"error": "bad_token"}`; `404 {"error": "unknown_claim"}`.
  - `DELETE /api/claims/{id}` `{"token", "reason"}` → `200 {}`.
  - `POST /api/claims/{id}/pr-closed` `{"pr"}` → `200 {"claim"}`; `409 {"error": "pr_mismatch"}`.
  - A claim JSON object = `dataclasses.asdict(Claim)`. Bodies are JSON, capped at 8192 bytes (`413`), bad JSON or bad field → `400 {"error": "bad_request", "detail"}`. Hub not serving its own checkout → `503 qa_needs_hub_server`; hub unreachable → `503 hub_unreachable`.

- [ ] **Step 1: Write the failing tests**

```python
def test_requires_auth(web_client):
    assert web_client.post("/api/claims", json={}).status_code == 401

def test_take_list_update_release(web_client, hub_with_ticket, auth):
    hub_with_ticket(rev=1)
    r = web_client.post("/api/claims", json={"ticket": US1, "holder": "a@m1"}, headers=auth)
    assert r.status_code == 201
    cid, tok = r.json()["claim"]["id"], r.json()["token"]
    (c,) = web_client.get("/api/claims", headers=auth).json()["claims"]
    assert (c["repo"], c["ticket"], c["holder"], c["phase"]) == ("ba-one", US1, "a@m1", "claimed")
    assert "token" not in c and "token_hash" not in c
    r = web_client.patch(f"/api/claims/{cid}", json={"token": tok, "phase": "design"}, headers=auth)
    assert r.json()["claim"]["phase"] == "design"
    assert web_client.request("DELETE", f"/api/claims/{cid}", json={"token": tok, "reason": "x"}, headers=auth).status_code == 200
    assert web_client.get("/api/claims", headers=auth).json()["claims"] == []

def test_second_take_is_409_with_holder(...): ...      # 409, body["claim"]["holder"] == "a@m1"
def test_retake_with_token_is_200(...): ...
def test_take_unknown_ticket_404(...): ...              # error "unknown_ticket"
def test_take_ambiguous_ticket(...): ...                # US1 published by two BA repos → 400 "ambiguous", detail names "<repo>:<id>"
def test_patch_lost_after_expiry(..., monkeypatch): ... # STRATA_KB_CLAIM_TTL=1 + store clock → 409 "lost", close_reason "expired"
def test_patch_bad_token_403(...): ...
def test_pr_closed_route(...): ...                      # review+pr → pr-closed → phase "execute"; other pr → 409 "pr_mismatch"
def test_get_closes_done_ticket(...): ...               # ticket done on hub (hist row in -svc) → claims [] and last_closed reason "done"
def test_body_too_large_413(...): ...
def test_bad_ttl_env_falls_back(monkeypatch): ...       # "abc", "0" → 14400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api_claims.py -v`
Expected: FAIL (404 on `/api/claims`)

- [ ] **Step 3: Implement `web/claim_api.py`** and wire it in `web/app.py`. Store access runs in the threadpool like the other sync routes; the body cap follows `api_resolve` in `web/api.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api_claims.py tests/test_api_questions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/web/claim_api.py src/strata_kb/web/app.py tests/test_api_claims.py
git commit -m "feat(claims): hub /api/claims routes"
```

---

### Task 3: Claim client and `kb claim` CLI

**Files:**
- Create: `src/strata_kb/claimclient.py`, `src/strata_kb/claimcmd.py`
- Modify: `src/strata_kb/cli.py` (a `claim_app = typer.Typer(help="Ticket claims on the hub: who is working on what.")`, `app.add_typer(claim_app, name="claim")`, thin commands calling `claimcmd`), `src/strata_kb/templates/init/claude-settings-auto.json` (add `"Bash(kb claim *)"` after `"Bash(kb pr *)"`)
- Test: `tests/test_claimclient.py`, `tests/test_cli_claim.py`

**Interfaces:**
- Consumes: Task 2 wire format; `httpio.request`; `mcpsetup.HUB_URL_VAR`, `dockersetup.TOKEN_VAR`; `gitio.config_value`; `autostate.log_dir`.
- Produces:
  - `class ClaimClient(base_url: str, token: str, http: Http = httpio.request)`: `take(ticket: str, holder: str, claim_token: str | None = None) -> tuple[dict, str]`; `update(claim_id: int, claim_token: str, **fields: str) -> dict`; `release(claim_id: int, claim_token: str, reason: str) -> None`; `held(repo: str = "", ticket: str = "") -> list[dict]`; `pr_closed(claim_id: int, pr: str) -> dict`.
  - Errors: `class ClaimTakenError(KbError)` with `.claim: dict`; `class ClaimLostError(KbError)` with `.close_reason`, `.closed_by`; `class ClaimRouteMissing(KbError)` (bare 404 → the upgrade message in Global Constraints); other non-2xx → `KbError("hub /api/claims returned <code>: <error>")`; `code == 0` → `KbError("hub unreachable: …")`.
  - `from_env() -> ClaimClient` (same env and messages as `autorun/qa.py:from_env`).
  - `holder_name(root: Path) -> str`.
  - `class LocalClaims(kb_dir: Path)`: file `autostate.log_dir(kb_dir).parent / "claims.json"`, `{ticket: {"id": int, "token": str}}`; `get(ticket) -> tuple[int, str] | None`, `put(ticket, claim_id, token) -> None`, `drop(ticket) -> None`. A missing or unparsable file reads as empty; writes are atomic (temp file + `os.replace`).
  - `claimcmd.take(kb_dir, root, ticket, as_name) -> int`, `update(kb_dir, ticket, phase, pr, stopped, active) -> int`, `release(kb_dir, ticket, reason) -> int`, `list_(kb_dir, as_json) -> int` (returns the exit code; prints the messages below).
  - CLI: `kb claim take <ticket> [--as NAME]`, `kb claim update <ticket> [--phase P] [--pr URL] [--stopped REASON | --active]`, `kb claim release <ticket> [--reason TEXT]`, `kb claim list [--json]`.
  - Messages: take ok → `claimed <ticket> as <holder>`; taken → `taken by <holder> (<phase>, updated <x> ago)` exit 3; lost → `lost: <close_reason> by <closed_by>` exit 3 (and drops the local entry); no local entry → `no claim held for <ticket> on this machine — run kb claim take <ticket>` exit 1.

- [ ] **Step 1: Write the failing tests** (fake `http` callable recording `(method, url, headers, body)`, returning canned `(code, bytes)`)

```python
def test_take_sends_bearer_and_body(): ...            # POST {base}/api/claims, Authorization "Bearer t", JSON {"ticket","holder"}
def test_take_409_raises_taken_with_claim(): ...
def test_update_409_lost(): ...                       # ClaimLostError.close_reason == "expired"
def test_bare_404_is_route_missing(): ...             # str(exc) == "hub server has no /api/claims — upgrade it to strata-kb 1.31.0 or later"
def test_404_with_error_code_is_not_route_missing(): ...  # {"error":"unknown_ticket"} → KbError mentioning unknown_ticket
def test_unreachable(): ...                           # code 0 → "hub unreachable"
def test_holder_name_default(monkeypatch, tmp_path): ...  # user.name "vuong", hostname "laptop-2" → "vuong@laptop-2"
def test_holder_name_env_override(monkeypatch): ...   # STRATA_KB_CLAIM_AS="ci-bot" → "ci-bot"
def test_local_claims_roundtrip_and_corrupt_file(tmp_path): ...

# tests/test_cli_claim.py (CliRunner, ClaimClient patched)
def test_take_prints_holder_and_stores_token(...): ...
def test_take_taken_exit_3(...): ...                  # output contains "taken by a@m1 (design, updated"
def test_update_without_local_claim(...): ...         # exit 1, exact message above, no traceback
def test_update_lost_exit_3_drops_local(...): ...
def test_release_drops_local(...): ...
def test_list_json(...): ...
def test_auto_settings_allow_kb_claim(): ...          # "Bash(kb claim *)" in claude-settings-auto.json allow list
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_claimclient.py tests/test_cli_claim.py -v`
Expected: FAIL (`ModuleNotFoundError: strata_kb.claimclient`)

- [ ] **Step 3: Implement `claimclient.py`, `claimcmd.py`, the `claim_app` commands and the allowlist line.** "updated <x> ago" is computed client-side from the claim's `last_seen` (hub time) against the local UTC clock, rounded to minutes.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_claimclient.py tests/test_cli_claim.py tests/test_cli.py tests/test_templates.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/claimclient.py src/strata_kb/claimcmd.py src/strata_kb/cli.py src/strata_kb/templates/init/claude-settings-auto.json tests/test_claimclient.py tests/test_cli_claim.py
git commit -m "feat(claims): kb claim take|update|release|list"
```

---

### Task 4: Runner claims, heartbeat and pick

**Files:**
- Create: `src/strata_kb/autorun/claims.py`, `src/strata_kb/autorun/claimbeat.py`
- Modify: `src/strata_kb/autorun/picker.py` (`dev_candidates`, `pick_dev` gains `held`), `src/strata_kb/autorun/runner.py` (`_task_for`, `run_once`, `_stop` callers, `run_loop`), `src/strata_kb/config.py:54-61` (`AutoConfig.claim_heartbeat: int = 900`)
- Test: `tests/test_autorun_claims.py`, extend `tests/test_autorun_picker.py`, `tests/test_autorun_runner.py`

**Interfaces:**
- Consumes: Task 3 `ClaimClient`, errors, `LocalClaims`, `holder_name`; `ghrest.view_pr(root, ref) -> dict` (its `state` / `merged` fields) for PR-closed detection.
- Produces:
  - `picker.dev_candidates(hub, root, skip: Collection[str] = (), held: Collection[str] = ()) -> list[Task]` — today's `_dev_tasks` order, minus tasks whose `arg` is in `held`; `pick_dev(hub, root, skip=(), held=())` returns its first (the `dev-test-workflow` rule unchanged).
  - `class RunnerClaims(root: Path, kb_dir: Path, client: ClaimClient, holder: str)`:
    - `held_by_others(mine: str | None) -> set[str]` — ticket ids of every held claim except `mine`'s (own `publishing`/`review` claims of earlier tasks included). For each held `review` claim with a `pr`, if `view_pr` says closed and not merged, calls `client.pr_closed` (best effort; errors logged).
    - `claim(ticket: str) -> bool` — re-claim with the stored token if any, else take; stores the token; a held `stopped` claim of ours is set back to `state="active"`. `ClaimTakenError` → `False` (logged with the holder).
    - `phase(ticket: str, phase: str) -> bool`, `stop(ticket: str, reason: str) -> None`, `release_if_working(ticket: str, reason: str) -> None` (only when its last known phase is in `WORKING_PHASES`), `beat(ticket: str) -> bool` — `False` only on `ClaimLostError` (drops the local entry); any other `KbError` → warning, `True`.
  - `class ClaimBeat(claims: RunnerClaims, interval: int)`: `start(ticket: str)`, `stop()`, `.lost: bool`; daemon thread on `threading.Event().wait(interval)`, `QaThread` style.
  - Runner behaviour (dev kind only; `cfg.kind == "ba"` untouched):
    - `build_deps` / `run_loop` build `RunnerClaims` from `claimclient.from_env()` and `holder_name(root)`; tests inject a fake through `deps["claims"]`.
    - Pick: `held = claims.held_by_others(mine)`, `mine` = the stored task's arg (`state.task.partition(":")[2]`) or `None`; walk `dev_candidates(...)`, `claims.claim(t.arg)` until one is `True`; none → `"idle"`. `ClaimRouteMissing` → `_stop(...)` with its message.
    - Stored task: `claims.claim(ticket)`; `False` → clear `state.task`, log `"<ticket> is now held by another Dev; picking again"`, return `"ran"`.
    - Around `run_task`: `ClaimBeat.start(ticket)` / `stop()`; `claims.phase(ticket, "claimed")` before.
    - After: `done` → `claims.phase(ticket, "publishing")`; `blocked-qa` → `claims.phase(ticket, "waiting-qa")` and the existing waiting loop calls `claims.beat` each pass; beat `.lost` during the task → clear `state.task`, no attempt counted, log `"claim on <ticket> lost: …"`, return `"ran"`.
    - Every `_stop` for a ticket task → `claims.stop(ticket, reason)` (state kept, task kept, as today).
    - `run_loop` `finally` → `claims.release_if_working(ticket, "runner stopped")`.
    - `state.last_done` / `_repicked` still work; a `publishing` claim is in `held` so it is no longer re-picked.

- [ ] **Step 1: Write the failing tests** (fake claims recording calls; fake hub returning plan stories as in `tests/test_autorun_picker.py`)

```python
def test_dev_candidates_skip_held(): ...                    # US1 held → first candidate US2
def test_pick_moves_on_after_lost_race(): ...               # claim(US1) False, claim(US2) True → task arg US2
def test_all_candidates_taken_is_idle(): ...
def test_stored_task_taken_by_other_drops_task(): ...       # state.task cleared, outcome "ran"
def test_done_sets_publishing_not_release(): ...            # calls == [("phase","US1","claimed"), ("phase","US1","publishing")]
def test_blocked_qa_sets_waiting_qa_and_beats(): ...
def test_stop_marks_stopped(): ...                          # ci-red → ("stop","US1","ci-red <url>")
def test_resume_reactivates_own_stopped_claim(): ...        # RunnerClaims.claim on own stopped → update(state="active")
def test_route_missing_stops_run(): ...                     # stop_reason contains "upgrade it to strata-kb 1.31.0"
def test_lost_during_task_counts_no_attempt(): ...
def test_loop_exit_releases_working_claim_only(): ...       # phase execute → release; phase publishing → no release
def test_beat_transient_error_is_not_lost(): ...            # client.update raises KbError("hub unreachable") → beat True, warning logged
def test_claimbeat_beats_on_interval(): ...                 # interval tiny; ≥2 beats; stop() joins
def test_held_by_others_reports_closed_pr(): ...            # review claim, view_pr {"state":"closed","merged":False} → client.pr_closed called
def test_ba_runner_makes_no_claims(): ...
def test_test_workflow_task_makes_no_claim(): ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_autorun_claims.py tests/test_autorun_picker.py tests/test_autorun_runner.py -v`
Expected: new tests FAIL, existing ones PASS

- [ ] **Step 3: Implement** `autorun/claims.py`, `autorun/claimbeat.py`, the picker change, `AutoConfig.claim_heartbeat`, and the runner wiring above. Keep `run_once` readable: put the claim steps in small helpers (`_claim_pick`, `_after_task`) rather than growing its body.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_autorun_*.py tests/test_cli_auto.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/autorun/claims.py src/strata_kb/autorun/claimbeat.py src/strata_kb/autorun/picker.py src/strata_kb/autorun/runner.py src/strata_kb/config.py tests/test_autorun_claims.py tests/test_autorun_picker.py tests/test_autorun_runner.py
git commit -m "feat(auto): claim before work, heartbeat, publishing and stopped claims"
```

---

### Task 5: Ticket menu — badges, holder line, admin Release

**Files:**
- Modify: `src/strata_kb/web/planui.py` (`plan_routes(config, session)`; ticket page context; list badges; `POST /ui/tickets/{mission}/{story}/release`), `src/strata_kb/web/app.py:100` (pass `session`), `src/strata_kb/templates/web/plan_ticket.html`, `src/strata_kb/templates/web/plan_mission.html`, `src/strata_kb/templates/web/plan_repo.html` (wherever ticket rows render a status)
- Test: `tests/test_web_claims.py` (fixtures from `tests/test_web_registry.py`: `make_client`, `_login`, `csrf_of`, `post`, `admin_user`)

**Interfaces:**
- Consumes: Task 1 `ClaimStore`, `claims_db_path`, `WORKING_PHASES`; Task 2 `claim_ttl_from_env`; `serving.auth.current_user`; `registry_routes.csrf_token` / `_csrf_ok` pattern.
- Produces: `claim_badge(claim: Claim | None) -> str | None` in `planui.py` → working phase `"In progress"`, `review` `"In review"`, `publishing` `"Publishing"`, stopped `"Stopped: <stop_reason>"`, `None` without a claim. Ticket page context adds `claim`, `claim_badge`, `last_closed`, `can_release` (admin only), `csrf`.

- [ ] **Step 1: Write the failing tests**

```python
def test_ticket_page_shows_holder_line(...): ...     # "In progress", "Taken by a@m1", "design", "updated"
def test_review_badge_links_pr(...): ...             # "In review" and the PR URL as a link
def test_stopped_badge(...): ...                     # "Stopped: ci-red"
def test_list_page_badges(...): ...                  # mission/repo page row for US1 shows "In progress"
def test_admin_sees_release_and_releases(...): ...   # button present; POST with csrf + reason → 303; store.held() == []; last_closed closed_by == admin username
def test_release_requires_reason(...): ...           # empty reason → 400, claim still held
def test_dev_role_no_button_and_403(...): ...        # dev account: no button; POST → 403
def test_bearer_post_403(...): ...
def test_bad_csrf_403(...): ...
def test_last_closed_shown(...): ...                 # after release: "Released by <admin> — <reason>"
def test_broken_claim_store_renders_notice(...): ... # claims.db is a directory → 200 with notice, no 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_web_claims.py -v`
Expected: FAIL

- [ ] **Step 3: Implement** the context, badges, templates and the release route (`admin_or_403` + CSRF exactly as `registry_routes`; reason ≤ 1000 chars; redirect back to the ticket page with 303). A store read error logs and renders the page with "Claim info is unavailable right now." (`qaui` pattern).

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_web_claims.py tests/test_web_ui.py tests/test_web_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/web/planui.py src/strata_kb/web/app.py src/strata_kb/templates/web/plan_*.html tests/test_web_claims.py
git commit -m "feat(web): claim badges and admin Release on the Ticket menu"
```

---

### Task 6: Safe concurrent publish (dev repos)

**Files:**
- Modify: `src/strata_kb/publish.py` (call the guard where the plan's `repo_kind == "dev"`, before the snapshot or intake route sends anything)
- Test: `tests/test_publish_behind.py` (git fixtures from `tests/conftest.py`: `run_git`, a dev repo with an `origin`)

**Interfaces:**
- Consumes: `gitio.fetch_branch(root, branch)`, `gitio.default_branch(root)`, `gitio.is_ancestor(root, ancestor, descendant)`, `gitio.has_remote(root)`.
- Produces: `publish.ensure_current(root: Path) -> None` — raises `PublishError` with: no remote → `no origin remote — kb publish in a dev repo needs one to check it is current`; fetch failure → `could not fetch origin/<default>: <reason>`; behind → `behind origin/<default> — pull, then kb publish`.

- [ ] **Step 1: Write the failing tests**

```python
def test_dev_publish_refuses_when_behind(...): ...      # another clone pushes a hist row; kb publish → PublishError, exact message
def test_dev_publish_ok_when_current(...): ...          # after git pull → publish proceeds
def test_dev_publish_ok_when_ahead(...): ...            # local commit on top of origin/<default> → proceeds
def test_dev_publish_no_remote_refuses(...): ...
def test_child_publish_unchanged(...): ...              # kind child, behind origin → no guard
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_publish_behind.py -v`
Expected: FAIL

- [ ] **Step 3: Implement `ensure_current`** and call it for `repo_kind == "dev"`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_publish_behind.py tests/test_publish*.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/publish.py tests/test_publish_behind.py
git commit -m "fix(publish): dev repos refuse to publish behind origin"
```

---

### Task 7: Dev skills, docs, release notes

**Files:**
- Modify: `src/strata_kb/templates/init/bodies/dev-implement-ticket.md` (Intake), `dev-fix-bug.md` (Intake), `dev-design.md`, `dev-plan.md`, `dev-execute.md`, `dev-handover.md` (normal flow and Auto mode branch rule), `src/strata_kb/templates/init/QUICKSTART-dev.md`, `README.md` §13, the Dev guide Markdown sources under `docs/src/` (EN and VI), `CHANGELOG.md`, `pyproject.toml` (`version = "1.31.0"`), `uv.lock` (the `strata-kb` package `version`, regenerated with `uv lock`, not by hand)
- Test: extend `tests/test_template_bodies.py`

**Interfaces:**
- Consumes: Task 3 CLI and messages; Task 6 refusal message.

Skill text to add (wording may be tightened; meaning fixed):
- `dev-implement-ticket` / `dev-fix-bug` Intake, after the ticket id is known: run `kb claim take <id>`. Exit `3` → STOP: "`<id>` is taken by `<holder>` (`<phase>`, updated `<x>` ago). Pick another ticket, or ask a hub admin to release it." Exit `1` from a missing route → STOP with its message. New claim and the ticket's branch exists on `origin` (`auto/<id>`, `<id>`, `fix/<BUG-id>`, `hotfix/<BUG-id>`) → fetch it and continue there under the existing re-entry rules; log whose work was taken over.
- `dev-design`, `dev-plan`, `dev-execute`, `dev-handover` on entry: `kb claim update <id> --phase <design|plan|execute|handover>`; `dev-execute` also after each task commit. Exit `3` (lost) → STOP: "your claim on `<id>` was released by `<closed_by>` (`<reason>`); re-run `/dev-implement-ticket <id>` to claim it again." No push after a lost claim.
- `dev-handover`: after the PR opens, `kb claim update <id> --phase review --pr <url>`; before `kb publish`, `git pull` the default branch; on `behind origin/<default>` pull once more and retry once; after the publish, `kb claim update <id> --phase publishing`.
- `QUICKSTART-dev.md` + README §13: a "Several Devs on one repo" subsection — claims, 4 h expiry, held through review and publishing, `stopped`, `kb claim list|release`, admin Release on the ticket page, `STRATA_KB_CLAIM_TTL`, `auto.claim_heartbeat`, the publish guard, and that the hub must be upgraded first.
- `CHANGELOG.md`: `## 1.31.0 — <date>` in the existing style, with an **Upgrade** bullet: upgrade the hub first (new `/api/claims`), then the CLI, then re-run `kb init --kind dev`.

- [ ] **Step 1: Write the failing tests**

```python
def test_intake_claims_ticket(): ...         # "kb claim take" in dev-implement-ticket.md and dev-fix-bug.md bodies
def test_phase_skills_update_claim(): ...    # "kb claim update" + "--phase design|plan|execute|handover" in each body
def test_handover_review_and_publishing(): ...  # "--phase review --pr" and "--phase publishing" in dev-handover.md
def test_handover_pulls_before_publish(): ...   # "behind origin/" mentioned in dev-handover.md
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_template_bodies.py -v`
Expected: new tests FAIL

- [ ] **Step 3: Edit the skill bodies, docs, CHANGELOG and version.**

- [ ] **Step 4: Run the full suite and the repo's checks**

Run: `pytest -q` then the repo's lint/format/type commands (see `pyproject.toml` / `tests-gate/`).
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/strata_kb/templates/init docs/src README.md CHANGELOG.md pyproject.toml uv.lock tests/test_template_bodies.py
git commit -m "docs(claims): dev skills claim tickets; 1.31.0"
```
