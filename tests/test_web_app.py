from starlette.testclient import TestClient

from strata_kb import ghapp, intake
from strata_kb.mcp import ServerConfig, create_http_app
from strata_kb.web.app import create_app

TOKEN = "secret-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def _config(fed_hub) -> ServerConfig:
    return ServerConfig(kb_dir=fed_hub / ".kb", hub=str(fed_hub))


def test_root_redirects_to_ui(fed_hub):
    client = TestClient(create_app(_config(fed_hub), TOKEN))
    resp = client.get("/", headers=AUTH, follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/ui"


def test_api_and_ui_reachable_through_one_app(fed_hub):
    client = TestClient(create_app(_config(fed_hub), TOKEN))
    assert client.get("/api/docs", headers=AUTH).status_code == 200
    assert client.get("/ui", headers=AUTH).status_code == 200


def test_unauthenticated_api_401_ui_redirect(fed_hub):
    client = TestClient(create_app(_config(fed_hub), TOKEN))
    assert client.get("/api/docs").status_code == 401
    resp = client.get("/ui", follow_redirects=False)
    assert resp.status_code == 302


def test_create_app_warns_at_startup_when_the_hub_clone_is_stuck_off_default(
    hub_worktree, run_git, tmp_path, caplog
):
    """I-2: create_app's startup block (resolve the hub, call
    check_serving_clone, log each warning) had no test proving the APP
    itself ever calls check_serving_clone -- replacing that whole block
    with a comment left tests/test_intake_startup.py (which calls
    check_serving_clone directly) and this module's suite fully green.
    Builds a real IntakeConfig pointing at a hub clone stuck on
    publish/alpha and asserts the warning is emitted by create_app, not
    just by check_serving_clone called in isolation."""
    origin = tmp_path / "origin.git"
    run_git(tmp_path, "init", "--bare", str(origin))
    run_git(hub_worktree, "remote", "add", "origin", str(origin))
    run_git(hub_worktree, "push", "-u", "origin", "HEAD")
    run_git(hub_worktree, "remote", "set-head", "origin", "-a")
    run_git(hub_worktree, "checkout", "-b", "publish/alpha")

    config = ServerConfig(kb_dir=hub_worktree / ".kb", hub=str(hub_worktree))
    intake_cfg = intake.IntakeConfig(
        hub_ref=str(hub_worktree),
        audience="https://kb.test",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused"),
    )
    with caplog.at_level("WARNING", logger="strata_kb.web.app"):
        create_app(config, TOKEN, intake_cfg=intake_cfg)
    warnings = "\n".join(r.message for r in caplog.records)
    assert "publish/alpha" in warnings


def test_full_http_app_serves_mcp_and_api_together(fed_hub):
    """create_http_app: MCP handshake still works AND /api works on the same app."""
    app = create_http_app(_config(fed_hub), TOKEN)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    }
    headers = {
        **AUTH,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    with TestClient(app, base_url="http://localhost:8321") as client:
        resp = client.post("/mcp", json=payload, headers=headers)
        assert resp.status_code == 200
        assert "serverInfo" in resp.text
        assert client.get("/api/health").status_code == 200
        assert client.get("/ui", headers=AUTH).status_code == 200


def test_hub_locked_cache_returns_503_not_a_crash(
    monkeypatch, tmp_path, hub_worktree, run_git, caplog, undiscardable_hub_cache
):
    """api.hub_handle: resolve_hub can raise gitio.GitError (hub.py's
    _discard_cache) when a stale cache cannot be removed -- e.g. Windows
    holding a lock on <cache>/.kb-work/search.sqlite3, and a serving web
    process is exactly the kind of process that would be holding it open.
    Before the guard, that GitError escaped hub_handle raw and turned every
    route's contractual 503 (see list_docs' "None = hub unreachable"
    docstring) into an unhandled 500. Same shape as mcp._hub (Wave G fix
    round 3). Drives the real mechanism, not a faked resolve_hub: a genuine
    legacy git clone (needs re-clone) whose removal is blocked by a real
    open file handle -- same recipe as
    test_hub.test_discard_cache_failure_names_the_cache_and_the_fix.

    N-6 (Wave G fix round 4 re-review): the guard used to swallow the
    GitError with no log record -- pin that it now reaches the log at
    warning, the same shape as mcp._hub's identical fix.

    Ruling P49 (round 5): round 4 skipped this test off Windows with a
    reason that called the POSIX outcome a "false-green" (measured, it is a
    hard failure) and named test_mcp as a fellow sufferer (it is not -- it
    fakes resolve_hub and shares none of the gap). Both are gone: the
    undiscardable-cache recipe now comes from the shared
    `undiscardable_hub_cache` fixture, which has a real POSIX mechanism, so
    this runs on Linux. See tests/conftest.py."""
    from strata_kb import hub as hub_mod

    cache_base = tmp_path / "hub-cache"
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(cache_base))
    bare = tmp_path / "hub.git"
    bare.mkdir()
    run_git(bare, "init", "--bare")
    run_git(hub_worktree, "remote", "add", "origin", str(bare))
    run_git(hub_worktree, "push", "origin", "HEAD")

    key = hub_mod.cache_key(str(bare))
    legacy = cache_base / key
    run_git(tmp_path, "clone", str(bare), str(legacy))
    run_git(legacy, "config", "core.autocrlf", "true")  # legacy -- forces re-clone

    with undiscardable_hub_cache(legacy):
        config = ServerConfig(kb_dir=tmp_path / ".kb", hub=str(bare))
        client = TestClient(create_app(config, TOKEN))
        with caplog.at_level("WARNING", logger="strata_kb.web.api"):
            resp = client.get("/api/docs", headers=AUTH)
            assert resp.status_code == 503
            assert resp.json()["error"] == "hub_unreachable"
        assert any(
            r.name == "strata_kb.web.api" and str(legacy) in r.message
            for r in caplog.records
        ), caplog.records


def test_sweep_drops_expired_keys(monkeypatch):
    from strata_kb.web import ratelimit

    monkeypatch.setattr(ratelimit, "_SWEEP_THRESHOLD", 2)
    clock = [1000.0]
    limiter = ratelimit.SlidingWindowLimiter(5, 60.0, clock=lambda: clock[0])
    for i in range(3):
        limiter.allow(f"ip-{i}")
    assert len(limiter._hits) == 3

    clock[0] += 61.0
    limiter.allow("ip-new")

    assert set(limiter._hits) == {"ip-new"}
