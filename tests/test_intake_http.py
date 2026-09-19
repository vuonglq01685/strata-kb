# tests/test_intake_http.py
from __future__ import annotations

import asyncio
import gzip
import io
import string
import json
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.testclient import TestClient

from strata_kb import ghapp, intake
from strata_kb.web import intake_routes

AUD = "https://kb.test"


def _request(client_host="10.0.0.1", xff=None, xff_lines=None):
    """A real starlette.requests.Request built from a raw ASGI scope --
    more faithful than a hand-rolled double: real Headers (case-insensitive,
    supports getlist() for repeated header lines, which a plain dict
    cannot represent) and a real client-less path via client_host=None.

    xff: a single X-Forwarded-For header line (comma-joined hops).
    xff_lines: multiple SEPARATE X-Forwarded-For header lines -- the shape
    a proxy that appends rather than extends produces (Traefik and several
    CDNs/ALBs; nginx's $proxy_add_x_forwarded_for does not).
    """
    if xff_lines is None:
        xff_lines = [xff] if xff else []
    headers = [(b"x-forwarded-for", v.encode()) for v in xff_lines]
    scope = {
        "type": "http",
        "headers": headers,
        "client": (client_host, 1234) if client_host else None,
    }
    return Request(scope)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


@pytest.fixture
def hub_with_registry(tmp_path):
    """Local hub with a registry mapping acme/flight-docs → flight-docs."""
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    fed = seed / "federation"
    fed.mkdir()
    (fed / "registry.yaml").write_text(
        "repos:\n  acme/flight-docs: flight-docs\n", encoding="utf-8"
    )
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(bare), str(clone))
    _git(clone, "config", "user.email", "srv@t")
    _git(clone, "config", "user.name", "srv")
    return clone


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, req):
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()


@pytest.fixture
def client(hub_with_registry, keypair, tmp_path, monkeypatch):
    pem, pub = keypair
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = intake.IntakeConfig(
        hub_ref=str(hub_with_registry),
        audience=AUD,
        creds=ghapp.AppCreds("1", "unused"),
        key_resolver=lambda t: pub,
        http=FakeHTTP(
            [(200, {"id": 1}), (201, {"token": "t"}), (201, {"html_url": "u/pull/9"})]
        ),
        push_via_token_url=False,
        status_path=tmp_path / "status.json",
    )
    store = intake.StatusStore(cfg.status_path)
    app = Starlette(routes=intake_routes.build_intake_routes(cfg, store))
    return TestClient(app), pem


@pytest.fixture
def intake_cfg(hub_with_registry, keypair, tmp_path, monkeypatch):
    """Same shape as `client`, but hands back the mutable IntakeConfig itself
    (e.g. to lower max_tar_bytes from within a test) rather than a client+pem
    tuple. build_intake_routes captures `cfg` by reference, so mutating an
    attribute after this fixture runs is visible to the next request."""
    pem, pub = keypair
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    return intake.IntakeConfig(
        hub_ref=str(hub_with_registry),
        audience=AUD,
        creds=ghapp.AppCreds("1", "unused"),
        key_resolver=lambda t: pub,
        http=FakeHTTP(
            [(200, {"id": 1}), (201, {"token": "t"}), (201, {"html_url": "u/pull/9"})]
        ),
        push_via_token_url=False,
        status_path=tmp_path / "status.json",
    )


@pytest.fixture
def intake_client(intake_cfg):
    store = intake.StatusStore(intake_cfg.status_path)
    app = Starlette(routes=intake_routes.build_intake_routes(intake_cfg, store))
    return TestClient(app)


def _jwt(pem, **overrides):
    now = int(time.time())
    claims = {
        "iss": intake.GITHUB_ISSUER, "aud": AUD, "iat": now, "exp": now + 300,
        "repository": "acme/flight-docs",
        "ref": "refs/tags/kb-publish/20260715-010101",
    }
    claims.update(overrides)
    return pyjwt.encode(claims, pem, algorithm="RS256")


def _archive() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"docs:\n- id: doc-a\n  title: A\n"
        info = tarfile.TarInfo("index.yaml")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _post(client, token, commit="abc1234", deletes=()):
    return client.post(
        "/intake/publish",
        headers={"Authorization": f"Bearer {token}"},
        data={"meta": json.dumps({"source_commit": commit, "deletes": list(deletes)})},
        files={"archive": ("kb.tar.gz", _archive(), "application/gzip")},
    )


def test_publish_happy_path_and_status(client):
    c, pem = client
    resp = _post(c, _jwt(pem))
    assert resp.status_code == 200, resp.text
    assert resp.json()["pr_url"].endswith("/pull/9")
    st = _get_status(c, _jwt(pem))
    assert st.status_code == 200
    assert st.json()["state"] == "done"


def test_publish_no_token_401(client):
    c, _ = client
    resp = c.post("/intake/publish")
    assert resp.status_code == 401


def test_publish_unregistered_repo_403(client):
    c, pem = client
    resp = _post(c, _jwt(pem, repository="evil/other"))
    assert resp.status_code == 403
    assert "registry" in resp.json()["detail"]


def test_publish_bad_ref_403(client):
    c, pem = client
    resp = _post(c, _jwt(pem, ref="refs/heads/main"))
    assert resp.status_code == 403


def _get_manifest(client, token, rid="flight-docs"):
    return client.get(
        "/intake/manifest",
        params={"repo_id": rid},
        headers={"Authorization": f"Bearer {token}"},
    )


def _get_status(client, token, rid="flight-docs", commit="abc1234"):
    return client.get(
        "/intake/status",
        params={"repo_id": rid, "commit": commit},
        headers={"Authorization": f"Bearer {token}"},
    )


def test_manifest_unknown_repo_returns_empty(client):
    c, pem = client
    resp = _get_manifest(c, _jwt(pem))
    assert resp.status_code == 200
    assert resp.json() == {"files": {}}


def test_manifest_no_token_401(client):
    c, _ = client
    resp = c.get("/intake/manifest", params={"repo_id": "flight-docs"})
    assert resp.status_code == 401


def test_manifest_repo_id_of_another_tenant_403(client):
    """Valid OIDC for acme/flight-docs must not read another repo's manifest."""
    c, pem = client
    resp = _get_manifest(c, _jwt(pem), rid="other-tenant")
    assert resp.status_code == 403


def test_manifest_bad_ref_403(client):
    c, pem = client
    resp = _get_manifest(c, _jwt(pem, ref="refs/heads/main"))
    assert resp.status_code == 403


def test_status_unknown_404(client):
    c, pem = client
    # LOW-1: status now requires the caller's own OIDC bearer token, the
    # same as manifest -- query the caller's OWN repo-id (a mismatched one
    # is a 403, tested separately) for a commit that was never published.
    resp = _get_status(c, _jwt(pem), commit="never-published")
    assert resp.status_code == 404


def test_status_no_token_401(client):
    c, _ = client
    resp = c.get("/intake/status", params={"repo_id": "flight-docs", "commit": "y"})
    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_token"


def test_status_repo_id_of_another_tenant_403(client):
    """LOW-1: valid OIDC for acme/flight-docs must not read another repo's
    publish status -- it echoes internal detail (e.g. raw git stderr) that
    is not this caller's to see."""
    c, pem = client
    resp = _get_status(c, _jwt(pem), rid="other-tenant", commit="y")
    assert resp.status_code == 403


@pytest.mark.skipif(
    sys.platform != "win32",
    reason="reproduces a locked-cache GitError via an open file handle "
    "shutil.rmtree cannot remove -- POSIX permits deleting an open file, "
    "so this shape does not reproduce there; nothing to pin on Linux "
    "without a different locking mechanism",
)
def test_manifest_and_status_503_not_500_on_a_locked_hub_cache(
    keypair, tmp_path, monkeypatch
):
    """Appended-section fix (round 4): _load_registry (build_intake_routes,
    intake_routes.py) used to call hub_mod.resolve_hub directly and only
    guard its `None` return -- resolve_hub can also RAISE gitio.GitError
    (a stale/legacy cache it cannot discard, e.g. because another process
    still has a file in it open -- the common Windows cause), which
    reached these two routes as an uncaught 500 instead of the degraded
    503 every other resolve_hub call site in this codebase already gives.
    Same locked-cache construction as
    test_resolve_hub_or_503_converts_a_locked_cache_into_a_503_not_a_500
    in test_intake_core.py, driven through the real HTTP routes instead."""
    pem, pub = keypair
    bare = tmp_path / "hub.git"
    _git(tmp_path, "init", "--bare", str(bare))
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    _git(seed, "remote", "add", "origin", str(bare))
    _git(seed, "push", "-u", "origin", "HEAD")

    cache_base = tmp_path / "cache"
    monkeypatch.setenv("STRATA_KB_HUB_CACHE", str(cache_base))
    from strata_kb import hub as hub_mod

    key = hub_mod.cache_key(str(bare))
    legacy = cache_base / key
    _git(tmp_path, "clone", str(bare), str(legacy))
    _git(legacy, "config", "core.autocrlf", "true")  # legacy -- needs re-clone

    locked = legacy / "locked.txt"
    locked.write_text("x", encoding="utf-8")
    fp = open(locked, "r", encoding="utf-8")
    try:
        monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
        monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
        cfg = intake.IntakeConfig(
            hub_ref=str(bare),
            audience=AUD,
            creds=ghapp.AppCreds("1", "unused"),
            key_resolver=lambda t: pub,
            http=None,
            push_via_token_url=False,
            status_path=tmp_path / "status.json",
        )
        store = intake.StatusStore(cfg.status_path)
        c = TestClient(Starlette(routes=intake_routes.build_intake_routes(cfg, store)))
        token = _jwt(pem)
        manifest_resp = _get_manifest(c, token)
        assert manifest_resp.status_code == 503, manifest_resp.text
        status_resp = _get_status(c, token)
        assert status_resp.status_code == 503, status_resp.text
    finally:
        fp.close()


def _slow_fake_publish_factory(intervals, lock, sleep_seconds=0.3):
    """A stand-in for intake.intake_publish that records its own
    [start, end) wall-clock interval instead of doing any real work --
    lets a concurrency test assert on overlap/non-overlap of the SAME
    call shape run_in_threadpool actually makes, without needing a real
    git worktree per concurrent call."""
    import time as time_mod

    def fake_publish(cfg, rid, source_commit, source_repo_full, deletes, archive):
        start = time_mod.monotonic()
        time_mod.sleep(sleep_seconds)
        end = time_mod.monotonic()
        with lock:
            intervals.append((start, end))
        return "http://pr/1"

    return fake_publish


def _run_two_publishes_concurrently(app, pem, monkeypatch):
    """Fires two /intake/publish requests at the same time and returns
    their [start, end) intervals (see _slow_fake_publish_factory).

    Deliberately NOT starlette.testclient.TestClient + two real OS
    threads: measured (testclient_concurrency_probe2.py, round-4
    scratchpad) that combination reliably HANGS one of the two threads
    once the request carries a real multipart file upload (works fine for
    a bodyless GET, reproduced the hang with a minimal Starlette app with
    no strata_kb code at all, so this is a TestClient/threading fragility,
    not a bug in the routes under test). httpx.AsyncClient over
    httpx.ASGITransport, driven from one anyio task group in a single
    event loop, exercises the exact same ASGI app and ran the same
    two-concurrent-uploads shape cleanly in that probe."""
    import threading

    import anyio
    import httpx

    intervals: list[tuple[float, float]] = []
    lock = threading.Lock()
    monkeypatch.setattr(
        intake, "intake_publish", _slow_fake_publish_factory(intervals, lock)
    )
    results: list = []

    async def one(commit):
        token = _jwt(pem)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/intake/publish",
                headers={"Authorization": f"Bearer {token}"},
                data={"meta": json.dumps({"source_commit": commit, "deletes": []})},
                files={"archive": ("kb.tar.gz", _archive(), "application/gzip")},
            )
            results.append(resp)

    async def main():
        with anyio.fail_after(15):
            async with anyio.create_task_group() as tg:
                tg.start_soon(one, "c1")
                tg.start_soon(one, "c2")

    anyio.run(main)

    assert len(results) == 2, "one or both publish requests did not complete"
    for resp in results:
        assert resp.status_code == 200, resp.text
    assert len(intervals) == 2
    return intervals


def test_publish_concurrency_is_capped_by_the_capacity_limiter(
    hub_with_registry, keypair, tmp_path, monkeypatch
):
    """HIGH-1 blast-radius containment (round 4): with
    publish_concurrency_limiter set to capacity 1, two /intake/publish
    requests started at the same time must not run intake_publish
    overlapping in wall-clock time -- the second must wait for the first
    to fully finish. Uses a fake intake_publish (see
    _slow_fake_publish_factory) that just records its own interval,
    isolating the ASSERTION to the concurrency gate itself rather than
    real git worktree timing noise."""
    import anyio

    pem, pub = keypair
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = intake.IntakeConfig(
        hub_ref=str(hub_with_registry), audience=AUD,
        creds=ghapp.AppCreds("1", "unused"), key_resolver=lambda t: pub,
        http=None, push_via_token_url=False, status_path=tmp_path / "status.json",
    )
    store = intake.StatusStore(cfg.status_path)
    app = Starlette(
        routes=intake_routes.build_intake_routes(
            cfg, store, publish_concurrency_limiter=anyio.CapacityLimiter(1)
        )
    )
    (s1, e1), (s2, e2) = _run_two_publishes_concurrently(app, pem, monkeypatch)
    # Serialized: one interval must fully precede the other -- no overlap.
    assert e1 <= s2 or e2 <= s1, f"intervals overlapped: {(s1, e1)} vs {(s2, e2)}"


def test_publish_concurrency_control_overlaps_when_the_limiter_allows_it(
    hub_with_registry, keypair, tmp_path, monkeypatch
):
    """No-op control for the test above: same two-concurrent-publishes
    setup, but with a capacity of 10 (never binding for 2 calls) --
    proves the harness itself is capable of showing overlap (nothing else
    in the stack -- run_in_threadpool's own worker limiter, the
    SlidingWindowLimiter, TestClient's portal -- is silently serializing
    these two calls), so the capped test above is pinning the
    CapacityLimiter specifically, not some other accidental
    serialization."""
    import anyio

    pem, pub = keypair
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = intake.IntakeConfig(
        hub_ref=str(hub_with_registry), audience=AUD,
        creds=ghapp.AppCreds("1", "unused"), key_resolver=lambda t: pub,
        http=None, push_via_token_url=False, status_path=tmp_path / "status.json",
    )
    store = intake.StatusStore(cfg.status_path)
    app = Starlette(
        routes=intake_routes.build_intake_routes(
            cfg, store, publish_concurrency_limiter=anyio.CapacityLimiter(10)
        )
    )
    (s1, e1), (s2, e2) = _run_two_publishes_concurrently(app, pem, monkeypatch)
    assert s2 < e1 and s1 < e2, f"expected overlap, got: {(s1, e1)} vs {(s2, e2)}"


def test_auth_middleware_exempts_exact_intake_paths_only():
    """No prefix wildcard: a future /intake/* route must not be exposed by accident."""
    from strata_kb.web import auth

    assert all(not p.startswith("/intake") for p in auth.EXEMPT_PREFIXES)
    for path in ("/intake/publish", "/intake/manifest", "/intake/status"):
        assert path in auth.EXEMPT_PATHS


def test_publish_archive_as_text_field_400(client):
    """archive sent as plain form text (no file upload) -> 400, not 500."""
    c, pem = client
    resp = c.post(
        "/intake/publish",
        headers={"Authorization": f"Bearer {_jwt(pem)}"},
        data={
            "meta": json.dumps({"source_commit": "abc1234", "deletes": []}),
            "archive": "not-a-file",
        },
    )
    assert resp.status_code == 400
    assert "file upload" in resp.json()["detail"]


def test_publish_invalid_registry_503(client, hub_with_registry):
    """Corrupt registry.yaml on the hub -> intake fails closed with 503."""
    c, pem = client
    (hub_with_registry / "federation" / "registry.yaml").write_text(
        "repos: [unclosed, sequence\n", encoding="utf-8"
    )
    resp = _post(c, _jwt(pem))
    assert resp.status_code == 503
    assert resp.json()["error"] == "intake_rejected"


def test_publish_rate_limited_429(hub_with_registry, keypair, tmp_path, monkeypatch):
    from strata_kb.web.ratelimit import SlidingWindowLimiter

    pem, pub = keypair
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = intake.IntakeConfig(
        hub_ref=str(hub_with_registry),
        audience=AUD,
        creds=ghapp.AppCreds("1", "unused"),
        key_resolver=lambda t: pub,
        http=FakeHTTP([(200, {"id": 1}), (201, {"token": "t"}), (201, {"html_url": "u/pull/9"})]),
        push_via_token_url=False,
        status_path=tmp_path / "status.json",
    )
    store = intake.StatusStore(cfg.status_path)
    routes = intake_routes.build_intake_routes(
        cfg, store, publish_limiter=SlidingWindowLimiter(max_attempts=1, window_seconds=60)
    )
    c = TestClient(Starlette(routes=routes))
    assert _post(c, _jwt(pem)).status_code == 200
    limited = _post(c, _jwt(pem))
    assert limited.status_code == 429


def test_route_wires_trusted_proxies_into_the_rate_limit_key(
    hub_with_registry, keypair, tmp_path, monkeypatch
):
    """Item 3: cfg.trusted_proxies must actually reach client_key through the
    route, not just be exercised by client_key's own unit tests. A revert to
    request.client.host (or a getattr/typo pinning the count at 0) would
    still pass a test that only checked "the second identical request is
    429" -- both requests reuse the same TestClient, so either
    implementation keys them alike. What only correct wiring passes: two
    requests differing ONLY in the X-Forwarded-For real-client tail land in
    the SAME bucket (429 on repeat) when trusted_proxies=1, and a request
    with a DIFFERENT real tail gets its own bucket instead of also being
    blocked."""
    from strata_kb.web.ratelimit import SlidingWindowLimiter

    pem, pub = keypair
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = intake.IntakeConfig(
        hub_ref=str(hub_with_registry),
        audience=AUD,
        creds=ghapp.AppCreds("1", "unused"),
        key_resolver=lambda t: pub,
        http=FakeHTTP([(200, {"id": 1}), (201, {"token": "t"}), (201, {"html_url": "u/pull/9"})]),
        push_via_token_url=False,
        status_path=tmp_path / "status.json",
        trusted_proxies=1,
    )
    store = intake.StatusStore(cfg.status_path)
    routes = intake_routes.build_intake_routes(
        cfg, store, publish_limiter=SlidingWindowLimiter(max_attempts=1, window_seconds=60)
    )
    c = TestClient(Starlette(routes=routes))

    def post_with_xff(xff, commit):
        return c.post(
            "/intake/publish",
            headers={"Authorization": f"Bearer {_jwt(pem)}", "X-Forwarded-For": xff},
            data={"meta": json.dumps({"source_commit": commit, "deletes": []})},
            files={"archive": ("kb.tar.gz", _archive(), "application/gzip")},
        )

    first = post_with_xff("9.9.9.9, 1.1.1.1", "commit-a")
    assert first.status_code == 200, first.text
    same_real_tail = post_with_xff("8.8.8.8, 1.1.1.1", "commit-b")
    assert same_real_tail.status_code == 429

    different_real_tail = post_with_xff("7.7.7.7, 2.2.2.2", "commit-c")
    assert different_real_tail.status_code == 200, different_real_tail.text


def test_publish_traversal_delete_maps_400_not_500(client):
    """A crafted deletes path is rejected fail-closed — must be a clean 4xx."""
    c, pem = client
    resp = _post(c, _jwt(pem), deletes=["../../outside.txt"])
    assert resp.status_code == 400
    assert resp.json()["error"] == "intake_rejected"
    st = _get_status(c, _jwt(pem))
    assert st.status_code == 200
    assert st.json()["state"] == "error"


def test_publish_unexpected_crash_still_reaches_a_terminal_status(client, monkeypatch):
    """MEDIUM-2 backstop: intake_publish's own translation of OS/parse
    errors covers everything the security review measured, but the route
    must guarantee the terminal-state property itself, not bet every
    future failure mode was anticipated -- an outright unexpected
    exception must still move the job out of "processing", never leave it
    stuck there forever."""

    def boom(*args, **kwargs):
        raise RuntimeError("unexpected crash")

    c, pem = client
    monkeypatch.setattr(intake, "intake_publish", boom)
    resp = _post(c, _jwt(pem))
    assert resp.status_code == 500
    assert resp.json()["error"] == "publish_failed"
    st = _get_status(c, _jwt(pem))
    assert st.status_code == 200
    assert st.json()["state"] == "error"


def test_publish_cancelled_mid_publish_still_reaches_a_terminal_status(
    client, monkeypatch
):
    """N-6: `except Exception` does not catch asyncio.CancelledError -- a
    BaseException since Python 3.8, deliberately, so a generic `except
    Exception` cannot swallow real task cancellation. A client disconnect
    mid-publish raises exactly this into the route past every `except`
    clause, which used to leave the job at "processing" forever --
    MEDIUM-2's exact symptom, by a different route. The outer try/finally
    must promote it to "error" regardless of how the coroutine exits."""

    def boom(*args, **kwargs):
        raise asyncio.CancelledError()

    c, pem = client
    monkeypatch.setattr(intake, "intake_publish", boom)
    with pytest.raises(BaseException):  # B017 once B is enabled -- CancelledError itself, intentional
        _post(c, _jwt(pem))
    st = _get_status(c, _jwt(pem))
    assert st.status_code == 200
    assert st.json()["state"] == "error"


def test_publish_git_error_maps_502_and_records_error(client, monkeypatch):
    from strata_kb import gitio

    def boom(*args, **kwargs):
        raise gitio.GitError("boom")

    c, pem = client
    monkeypatch.setattr(intake, "intake_publish", boom)
    resp = _post(c, _jwt(pem))
    assert resp.status_code == 502
    assert resp.json()["error"] == "publish_failed"
    st = _get_status(c, _jwt(pem))
    assert st.status_code == 200
    assert st.json()["state"] == "error"


# ---- integration: production-shaped stack (TokenAuthMiddleware + routes) ----


@pytest.fixture
def full_stack(hub_with_registry, keypair, tmp_path, monkeypatch):
    """Mount /intake/* behind TokenAuthMiddleware exactly as create_app does,
    plus one non-intake route to bound the exemption's blast radius."""
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from strata_kb.web.auth import TokenAuthMiddleware

    pem, pub = keypair
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = intake.IntakeConfig(
        hub_ref=str(hub_with_registry),
        audience=AUD,
        creds=ghapp.AppCreds("1", "unused"),
        key_resolver=lambda t: pub,
        http=FakeHTTP(
            [(200, {"id": 1}), (201, {"token": "t"}), (201, {"html_url": "u/pull/9"})]
        ),
        push_via_token_url=False,
        status_path=tmp_path / "status.json",
    )
    store = intake.StatusStore(cfg.status_path)

    async def dummy(request):
        return JSONResponse({"ok": True})

    routes = intake_routes.build_intake_routes(cfg, store)
    routes.append(Route("/api/dummy", dummy, methods=["GET"]))
    app = TokenAuthMiddleware(Starlette(routes=routes), token="secret-mcp-token")
    return TestClient(app), pem


def test_stack_intake_gets_pass_middleware_without_mcp_token(full_stack):
    c, pem = full_stack
    # manifest: middleware lets it through, the route itself enforces OIDC
    resp = _get_manifest(c, _jwt(pem))
    assert resp.status_code == 200
    assert resp.json() == {"files": {}}
    no_token = c.get("/intake/manifest", params={"repo_id": "flight-docs"})
    assert no_token.status_code == 401
    assert no_token.json()["error"] == "missing_token"
    # status: middleware still lets it through (exempt path), but the route
    # itself now enforces the same OIDC + rid==caller check manifest does
    # (LOW-1) -- a request with no token is a 401 from the ROUTE, not the
    # middleware, and one with the caller's own token but an unpublished
    # commit is a genuine 404 from the store lookup.
    no_token_status = c.get("/intake/status", params={"repo_id": "flight-docs", "commit": "y"})
    assert no_token_status.status_code == 401
    st = _get_status(c, _jwt(pem), commit="y")
    assert st.status_code == 404
    assert st.json() == {"state": "unknown"}


def test_stack_unknown_intake_path_still_requires_mcp_token(full_stack):
    c, _ = full_stack
    resp = c.get("/intake/other")
    assert resp.status_code == 401


def test_stack_publish_no_bearer_401(full_stack):
    c, _ = full_stack
    resp = c.post("/intake/publish")
    assert resp.status_code == 401
    assert resp.json()["error"] == "missing_token"


def test_stack_publish_garbage_jwt_401(full_stack):
    c, _ = full_stack
    resp = _post(c, "not.a.valid.jwt")
    assert resp.status_code == 401
    assert "OIDC token rejected" in resp.json()["detail"]


def test_stack_non_intake_route_still_requires_mcp_token(full_stack):
    c, _ = full_stack
    resp = c.get("/api/dummy")
    assert resp.status_code == 401
    ok = c.get("/api/dummy", headers={"Authorization": "Bearer secret-mcp-token"})
    assert ok.status_code == 200


def test_intake_config_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATA_KB_GH_APP_ID", raising=False)
    assert intake.intake_config_from_env("hub") is None
    pem_path = tmp_path / "app.pem"
    pem_path.write_text("PEM", encoding="utf-8")
    monkeypatch.setenv("STRATA_KB_GH_APP_ID", "1234")
    monkeypatch.setenv("STRATA_KB_GH_APP_KEY", str(pem_path))
    monkeypatch.setenv("STRATA_KB_INTAKE_AUDIENCE", AUD)
    cfg = intake.intake_config_from_env("hub")
    assert cfg is not None
    assert cfg.creds.app_id == "1234"
    assert cfg.creds.private_key_pem == "PEM"
    assert cfg.audience == AUD
    assert cfg.trusted_proxies == 0  # default -- X-Forwarded-For ignored
    # broken PEM path → None (fail closed), no raise
    monkeypatch.setenv("STRATA_KB_GH_APP_KEY", str(tmp_path / "missing.pem"))
    assert intake.intake_config_from_env("hub") is None


def _env_for_trusted_proxies(tmp_path, monkeypatch):
    """Shared valid GH App env so only STRATA_KB_TRUSTED_PROXIES varies."""
    pem_path = tmp_path / "app.pem"
    pem_path.write_text("PEM", encoding="utf-8")
    monkeypatch.setenv("STRATA_KB_GH_APP_ID", "1234")
    monkeypatch.setenv("STRATA_KB_GH_APP_KEY", str(pem_path))
    monkeypatch.setenv("STRATA_KB_INTAKE_AUDIENCE", AUD)


def test_trusted_proxies_env_valid_value_is_parsed(tmp_path, monkeypatch):
    _env_for_trusted_proxies(tmp_path, monkeypatch)
    monkeypatch.setenv("STRATA_KB_TRUSTED_PROXIES", "2")
    cfg = intake.intake_config_from_env("hub")
    assert cfg is not None
    assert cfg.trusted_proxies == 2


def test_trusted_proxies_env_non_numeric_exits_loudly(tmp_path, monkeypatch):
    """Item 7: a malformed value must fail startup (SystemExit, no
    traceback -- matching mcp.py's other operator-config errors), never
    silently fall back to 0 -- a silent fallback would silently defeat an
    operator's declared trusted-proxy count."""
    _env_for_trusted_proxies(tmp_path, monkeypatch)
    monkeypatch.setenv("STRATA_KB_TRUSTED_PROXIES", "not-a-number")
    with pytest.raises(SystemExit) as exc:
        intake.intake_config_from_env("hub")
    assert "STRATA_KB_TRUSTED_PROXIES" in str(exc.value)
    assert "not-a-number" in str(exc.value)


def test_trusted_proxies_env_negative_exits_loudly(tmp_path, monkeypatch):
    """A negative value parses fine under plain int() but client_key treats
    it the same as 0 (header ignored) -- the same silent defeat the loud
    failure exists to prevent, so it must be rejected too, not just
    non-numeric garbage."""
    _env_for_trusted_proxies(tmp_path, monkeypatch)
    monkeypatch.setenv("STRATA_KB_TRUSTED_PROXIES", "-1")
    with pytest.raises(SystemExit) as exc:
        intake.intake_config_from_env("hub")
    assert "STRATA_KB_TRUSTED_PROXIES" in str(exc.value)


def test_oversized_upload_is_refused_without_buffering_the_whole_body():
    """F-D12: archive = await upload.read() buffered the entire body before
    safe_extract ever compared it to the cap."""
    reads = []

    class CountingUpload:
        def __init__(self, data):
            self._buf = io.BytesIO(data)

        async def read(self, size=-1):
            chunk = self._buf.read(size if size and size > 0 else None)
            reads.append(len(chunk))
            return chunk

    upload = CountingUpload(b"x" * (5 * 1024 * 1024))
    with pytest.raises(intake.IntakeError) as exc:
        asyncio.run(intake_routes.read_capped(upload, 1024))
    assert exc.value.status == 413
    assert sum(reads) < 5 * 1024 * 1024


def test_content_length_over_the_cap_is_refused_before_reading(intake_client, intake_cfg):
    intake_cfg.max_tar_bytes = 1024
    resp = intake_client.post(
        "/intake/publish",
        headers={"authorization": "Bearer t", "content-length": str(10 * 1024 * 1024)},
    )
    assert resp.status_code == 413


def test_chunked_oversized_body_with_no_content_length_is_still_capped(
    intake_client, intake_cfg, keypair
):
    """Item 5 (round 1): a chunked body declares no Content-Length at all,
    so the pre-check at the top of `publish` has nothing to compare against
    and cannot catch it -- only the capped receive channel wrapping
    request.form() bounds this case. Also asserts the refusal renders
    through the _err() envelope, not Starlette's bare 400/plain text
    (item 10) or an uncaught 500.

    Round 2 item 3: the receive channel's cap is `max_tar_bytes +
    _ENVELOPE_ALLOWANCE` (the whole multipart envelope, not the archive
    alone), and its wording says "request body" now -- this 2 MiB body
    (well over the ~1 MiB-plus cap either way) still trips it, but the
    detail text and the numeric cap both changed from round 1's version of
    this test.
    """
    from strata_kb.web import intake_routes

    pem, _ = keypair
    intake_cfg.max_tar_bytes = 1024
    boundary = "----chunkedcap"
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="meta"\r\n\r\n'
        '{"source_commit": "abc1234"}\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="archive"; filename="kb.tar.gz"\r\n'
        "Content-Type: application/gzip\r\n\r\n"
    ).encode()
    suffix = f"\r\n--{boundary}--\r\n".encode()
    body = prefix + b"x" * (2 * 1024 * 1024) + suffix

    def stream():
        for i in range(0, len(body), 65536):
            yield body[i : i + 65536]

    resp = intake_client.post(
        "/intake/publish",
        headers={
            "authorization": f"Bearer {_jwt(pem)}",
            "content-type": f"multipart/form-data; boundary={boundary}",
        },
        content=stream(),
    )
    body_cap = intake_cfg.max_tar_bytes + intake_routes._ENVELOPE_ALLOWANCE
    assert resp.status_code == 413, resp.text
    assert resp.json() == {
        "error": "intake_rejected",
        "detail": f"request body exceeds {body_cap} bytes",
    }


def test_forwarded_for_is_ignored_by_default():
    from strata_kb.web import ratelimit

    request = _request(client_host="10.0.0.1", xff="1.2.3.4, 10.0.0.9")
    assert ratelimit.client_key(request, trusted_proxies=0) == "10.0.0.1"


def test_forwarded_for_is_honoured_behind_a_declared_proxy():
    """With 1 trusted proxy, only the RIGHTMOST entry was appended by
    infrastructure we trust -- the sole hop appends the true peer address it
    observed. Anything to its left (here "1.2.3.4") is whatever the client
    itself put in the header before the proxy ever saw the request, i.e.
    attacker-controlled. Picking the leftmost entry here would be exactly
    the spoofable mistake F-D12 closes -- the client could forge its own
    X-Forwarded-For prefix and have it trusted as the rate-limit key.

    NOTE: with exactly two entries, hops[-1] == hops[1], so this alone
    cannot distinguish right-indexing from an off-by-one left-indexed
    implementation -- see the three-entry case below, which does."""
    from strata_kb.web import ratelimit

    request = _request(client_host="10.0.0.1", xff="1.2.3.4, 10.0.0.9")
    assert ratelimit.client_key(request, trusted_proxies=1) == "10.0.0.9"


def test_forwarded_for_shorter_than_the_proxy_chain_falls_back_to_the_peer():
    from strata_kb.web import ratelimit

    request = _request(client_host="10.0.0.1", xff="1.2.3.4")
    assert ratelimit.client_key(request, trusted_proxies=3) == "10.0.0.1"


def test_forwarded_for_three_entries_separates_right_from_left_indexing():
    """A three-hop chain is the minimum that tells right-indexing
    (hops[-trusted_proxies]) apart from a left-indexed off-by-one
    (hops[trusted_proxies]) AND from the naive leftmost (hops[0]):

        hops = [1.1.1.1, 2.2.2.2, 3.3.3.3], trusted_proxies=1
        correct (right-indexed) -> 3.3.3.3
        left-indexed hops[tp]   -> 2.2.2.2  (would pass here)
        leftmost hops[0]        -> 1.1.1.1  (would also pass here)

    The two-entry test above cannot tell these apart (hops[-1] == hops[1]
    when there are only two hops); this one can, and is the case a
    well-meaning "simplify the indexing" refactor would actually break."""
    from strata_kb.web import ratelimit

    request = _request(client_host="10.0.0.1", xff="1.1.1.1, 2.2.2.2, 3.3.3.3")
    assert ratelimit.client_key(request, trusted_proxies=1) == "3.3.3.3"


def test_forwarded_for_multiple_header_lines_are_joined_before_indexing():
    """F-D12 in its actual deployment shape: a proxy that APPENDS a
    separate X-Forwarded-For header line (Traefik, several CDNs/ALBs)
    rather than extending the client's existing one. request.headers.get()
    would return only the client's forged first line and never see the
    proxy's line at all; getlist() + per-line split collects both before
    indexing from the right."""
    from strata_kb.web import ratelimit

    request = _request(client_host="10.0.0.1", xff_lines=["1.1.1.1", "2.2.2.2, 9.9.9.9"])
    assert ratelimit.client_key(request, trusted_proxies=1) == "9.9.9.9"


@pytest.mark.parametrize(
    "xff_lines",
    [
        [],  # header absent entirely
        [""],  # present but empty
        ["   "],  # present but blank
        [",,,"],  # present but only separators
    ],
)
def test_forwarded_for_degenerate_header_falls_back_to_the_peer(xff_lines):
    from strata_kb.web import ratelimit

    request = _request(client_host="10.0.0.1", xff_lines=xff_lines)
    assert ratelimit.client_key(request, trusted_proxies=1) == "10.0.0.1"


def test_forwarded_for_negative_trusted_proxies_falls_back_to_the_peer():
    """Mirrors the `trusted_proxies <= 0` guard -- a negative value must be
    as inert as 0, never trust the header, and never raise (e.g. from a
    negative list index)."""
    from strata_kb.web import ratelimit

    request = _request(client_host="10.0.0.1", xff="1.1.1.1, 2.2.2.2")
    assert ratelimit.client_key(request, trusted_proxies=-1) == "10.0.0.1"


def test_forwarded_for_non_ip_hop_falls_back_to_the_peer():
    """The selected hop becomes an unvalidated dict key logged verbatim for
    an unauthenticated caller -- a hop that isn't even a parseable IP is
    malformed by definition and must not be trusted as the rate-limit key."""
    from strata_kb.web import ratelimit

    request = _request(client_host="10.0.0.1", xff="<script>alert(1)</script>")
    assert ratelimit.client_key(request, trusted_proxies=1) == "10.0.0.1"


def test_client_key_no_socket_peer_returns_unknown():
    """request.client is None (e.g. a raw ASGI test double, or certain
    embedded transports) must not raise -- falls back to the sentinel."""
    from strata_kb.web import ratelimit

    request = _request(client_host=None)
    assert ratelimit.client_key(request, trusted_proxies=0) == "unknown"


# ---- F-D12 fix round 2 ----------------------------------------------------


def _raw_multipart(boundary: str, parts: list[bytes]) -> bytes:
    """Assemble a raw multipart/form-data body from part blobs, each already
    `<headers>\\r\\n\\r\\n<data>` with no leading boundary line and no
    trailing CRLF. Used where TestClient's own files=/data= helpers cannot
    produce the shape under test (a part missing `name=`, a boundary-less
    Content-Type, 1001 file parts, a header line too long)."""
    out = bytearray()
    for part in parts:
        out += f"--{boundary}\r\n".encode() + part + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out)


async def _drive_asgi_raw(app, headers: list[tuple[bytes, bytes]], chunks):
    """POST /intake/publish to `app` as SEPARATE ASGI `http.request`
    messages -- `chunks` is a list of (bytes, more_body) pairs, the shape a
    real streamed/chunked upload arrives in.

    TestClient cannot produce this: httpx's `request.read()` (called from
    testclient.py's own `receive()` closure) buffers the whole body into
    ONE message before the ASGI app ever sees it, and it also refuses to
    send a header value that isn't valid latin-1-encodable text -- so a raw
    invalid Content-Length byte, or a genuinely separate multi-chunk body,
    can only be driven by calling the ASGI callable directly, the way a
    real uvicorn deployment (not TestClient) would present it.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/intake/publish",
        "raw_path": b"/intake/publish",
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("10.0.0.1", 12345),
        "server": ("testserver", 80),
        "state": {},
    }
    remaining = list(chunks)
    sent: list[dict] = []

    async def receive():
        if remaining:
            chunk_body, more_body = remaining.pop(0)
            return {"type": "http.request", "body": chunk_body, "more_body": more_body}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)

    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    resp_body = b"".join(
        m.get("body", b"") for m in sent if m["type"] == "http.response.body"
    )
    return status, resp_body


def _intake_app(intake_cfg):
    store = intake.StatusStore(intake_cfg.status_path)
    return Starlette(routes=intake_routes.build_intake_routes(intake_cfg, store))


# ---- Item 1: MultiPartException is converted to HTTPException(400) by
# Starlette whenever "app" is in scope (always true under web/app.py's real
# app) -- _parse_capped_form must catch HTTPException, not just the bare
# MultiPartException that never actually surfaces under a mounted app. Each
# of the four cases below reproduces one of round 1's measured "still bare
# 400 text" failures.


def test_too_many_file_parts_renders_json_400_under_the_real_app(
    intake_client, intake_cfg, keypair
):
    """Before this fix: bare 400 text/plain, bypassing _err() entirely --
    the exact case that motivated item 10/1. `intake_client` is a real
    Starlette app (TestClient(Starlette(routes=...))), so "app" is in
    scope exactly as it is in production (web/app.py:57)."""
    pem, _ = keypair
    boundary = "----files1001"
    part = (
        'Content-Disposition: form-data; name="f"; filename="x"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body = _raw_multipart(boundary, [part] * 1001)
    resp = intake_client.post(
        "/intake/publish",
        headers={
            "authorization": f"Bearer {_jwt(pem)}",
            "content-type": f"multipart/form-data; boundary={boundary}",
        },
        content=body,
    )
    assert resp.status_code == 400, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {
        "error": "intake_rejected",
        "detail": "Too many files. Maximum number of files is 1000.",
    }


def test_missing_boundary_renders_json_400_under_the_real_app(
    intake_client, intake_cfg, keypair
):
    pem, _ = keypair
    resp = intake_client.post(
        "/intake/publish",
        headers={
            "authorization": f"Bearer {_jwt(pem)}",
            "content-type": "multipart/form-data",  # no boundary=
        },
        content=b"irrelevant",
    )
    assert resp.status_code == 400, resp.text
    assert resp.json() == {
        "error": "intake_rejected",
        "detail": "Missing boundary in multipart.",
    }


def test_oversized_non_file_part_renders_json_400_under_the_real_app(
    intake_client, intake_cfg, keypair
):
    """A plain (non-file) field over Starlette's own max_part_size (1 MiB,
    unrelated to max_tar_bytes/_ENVELOPE_ALLOWANCE) trips MultiPartException
    from formparsers.py's non-file branch."""
    pem, _ = keypair
    boundary = "----bigfield"
    part = (
        'Content-Disposition: form-data; name="junk"\r\n\r\n'
    ).encode() + b"x" * (2 * 1024 * 1024)
    body = _raw_multipart(boundary, [part])
    resp = intake_client.post(
        "/intake/publish",
        headers={
            "authorization": f"Bearer {_jwt(pem)}",
            "content-type": f"multipart/form-data; boundary={boundary}",
        },
        content=body,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json() == {
        "error": "intake_rejected",
        "detail": "Part exceeded maximum size of 1024KB.",
    }


def test_part_with_no_name_renders_json_400_under_the_real_app(
    intake_client, intake_cfg, keypair
):
    pem, _ = keypair
    boundary = "----noname"
    part = ("Content-Disposition: form-data\r\n\r\n").encode() + b"somevalue"
    body = _raw_multipart(boundary, [part])
    resp = intake_client.post(
        "/intake/publish",
        headers={
            "authorization": f"Bearer {_jwt(pem)}",
            "content-type": f"multipart/form-data; boundary={boundary}",
        },
        content=body,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json() == {
        "error": "intake_rejected",
        "detail": 'The Content-Disposition header field "name" must be provided.',
    }


# ---- Item 2: the round's most valuable fix (the capped receive channel)
# had no test that could tell it apart from a no-op -- these instrument the
# actual SpooledTemporaryFile Starlette spools file parts into.


class RecordingSpooledFile(tempfile.SpooledTemporaryFile):
    """A REAL SpooledTemporaryFile (no mocking library is used in this
    project) that also records every write -- monkeypatched in for
    starlette.formparsers.SpooledTemporaryFile so a test can observe bytes
    actually reaching a file, not just the HTTP status/detail the route
    returns (which is identical whether the cap fired or not -- see the
    module docstring above `read_capped`)."""

    def __init__(self, *args, log: list[int], instances: list, **kwargs):
        super().__init__(*args, **kwargs)
        self._log = log
        instances.append(self)

    def write(self, data):
        n = super().write(data)
        self._log.append(len(data) if isinstance(data, (bytes, bytearray)) else n)
        return n


def _install_recording_spool(monkeypatch):
    from starlette import formparsers

    written: list[int] = []
    instances: list = []

    def factory(*args, **kwargs):
        return RecordingSpooledFile(*args, log=written, instances=instances, **kwargs)

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", factory)
    return written, instances


def test_oversized_first_chunk_writes_zero_bytes_to_any_spool_file(
    intake_cfg, keypair, monkeypatch
):
    """F-D12 item 2: the property that actually changed is bytes reaching a
    file, not the HTTP status -- read_capped alone still produces an
    identical 413 with an identical detail string even with the capped
    receive channel deleted entirely (see the mutation table in the round 2
    brief). Here the first ASGI message alone already exceeds the body cap
    (1024 + 1 MiB), so `_capped_receive` raises before python_multipart
    reads a single byte of it -- not even the archive part's headers get
    parsed, so no SpooledTemporaryFile is created at all. (This is the
    narrow, accurate version of round 1's "0 bytes ever reach a file"
    claim: it holds only when the first ASGI message alone already exceeds
    the cap -- see the round 2 brief's "Not in scope" section.)"""
    pem, _ = keypair
    intake_cfg.max_tar_bytes = 1024
    written, instances = _install_recording_spool(monkeypatch)

    boundary = "----overcap"
    prefix = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="meta"\r\n\r\n'
        '{"source_commit": "abc1234"}\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="archive"; filename="kb.tar.gz"\r\n'
        "Content-Type: application/gzip\r\n\r\n"
    ).encode()
    # One message, already over the 1024 + 1 MiB = 1049600-byte body cap.
    first_chunk = prefix + b"x" * (2 * 1024 * 1024)
    suffix = f"\r\n--{boundary}--\r\n".encode()

    app = _intake_app(intake_cfg)
    status, resp_body = asyncio.run(
        _drive_asgi_raw(
            app,
            headers=[
                (b"authorization", f"Bearer {_jwt(pem)}".encode()),
                (
                    b"content-type",
                    f"multipart/form-data; boundary={boundary}".encode(),
                ),
            ],
            chunks=[(first_chunk, True), (suffix, False)],
        )
    )
    assert status == 413
    body_cap = intake_cfg.max_tar_bytes + intake_routes._ENVELOPE_ALLOWANCE
    assert json.loads(resp_body) == {
        "error": "intake_rejected",
        "detail": f"request body exceeds {body_cap} bytes",
    }
    assert written == []
    assert instances == []


def test_legitimate_under_cap_upload_still_spools_and_succeeds(
    intake_client, intake_cfg, keypair, monkeypatch
):
    """A cap that refuses valid traffic is worse than the gap it closes --
    the same instrumentation must show a legitimate under-cap upload still
    reaches the spool file and the publish still succeeds end to end.

    max_tar_bytes is deliberately tight (archive is 130 bytes, the
    surrounding multipart envelope ~248) so this also re-proves item 3: a
    regression back to measuring the whole envelope against max_tar_bytes
    with no _ENVELOPE_ALLOWANCE headroom would turn this legitimate upload
    into a 413, not just fail a status-code assertion -- real bytes would
    stop reaching the spool file too.

    HIGH-2 (Wave H) layered a second, independent budget onto this same
    number: safe_extract's per-member content total now also charges one
    tarfile.BLOCKSIZE per member (so an all-headers archive cannot exhaust
    the service on member count alone), and _archive() has one member.

    HIGH-1 (round 3): safe_extract now bounds the DECOMPRESSED stream
    itself (_BoundedTarStream), which charges every real byte tarfile
    reads from it -- the header block, the content block (content +
    inter-member padding skip + verification byte, together exactly one
    BLOCKSIZE here), and the trailing block tarfile reads to recognize
    end-of-archive. Three blocks is the new tight minimum (see
    test_archive_exactly_at_max_tar_bytes_succeeds); this test's whole
    point is a legitimate upload succeeding, not exact-boundary tightness,
    so it keeps the same three-block floor.
    """
    pem, _ = keypair
    intake_cfg.max_tar_bytes = 3 * tarfile.BLOCKSIZE
    written, instances = _install_recording_spool(monkeypatch)
    resp = _post(intake_client, _jwt(pem))
    assert resp.status_code == 200, resp.text
    assert len(instances) >= 1
    assert sum(written) > 0


def test_capped_request_is_closed_exactly_once_on_bad_meta_400(
    intake_client, intake_cfg, keypair, monkeypatch
):
    """F-D12 item 2: the deterministic `finally: await capped.close()`
    (round 1) had no test either -- deleting it kept the suite green. This
    substitutes the `Request` class `_parse_capped_form` calls (module-level
    name in intake_routes, not the original inbound request's own class) so
    only the CAPPED request's close() is counted."""
    from strata_kb.web import intake_routes as ir

    close_calls: list[int] = []

    class CountingRequest(Request):
        async def close(self):
            close_calls.append(1)
            await super().close()

    monkeypatch.setattr(ir, "Request", CountingRequest)
    pem, _ = keypair
    resp = intake_client.post(
        "/intake/publish",
        headers={"authorization": f"Bearer {_jwt(pem)}"},
        data={"meta": "not-json", "archive": "not-a-file"},
    )
    assert resp.status_code == 400, resp.text
    assert close_calls == [1]


def test_capped_request_is_closed_exactly_once_on_success(
    hub_with_registry, keypair, tmp_path, monkeypatch
):
    from strata_kb.web import intake_routes as ir

    close_calls: list[int] = []

    class CountingRequest(Request):
        async def close(self):
            close_calls.append(1)
            await super().close()

    monkeypatch.setattr(ir, "Request", CountingRequest)
    pem, pub = keypair
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    cfg = intake.IntakeConfig(
        hub_ref=str(hub_with_registry),
        audience=AUD,
        creds=ghapp.AppCreds("1", "unused"),
        key_resolver=lambda t: pub,
        http=FakeHTTP(
            [(200, {"id": 1}), (201, {"token": "t"}), (201, {"html_url": "u/pull/9"})]
        ),
        push_via_token_url=False,
        status_path=tmp_path / "status.json",
    )
    store = intake.StatusStore(cfg.status_path)
    c = TestClient(Starlette(routes=intake_routes.build_intake_routes(cfg, store)))
    resp = _post(c, _jwt(pem))
    assert resp.status_code == 200, resp.text
    assert close_calls == [1]


def test_oversized_filename_header_renders_json_400_not_500(
    intake_client, intake_cfg, keypair
):
    """python_multipart's FormParserError (base MultipartParseError) is NOT
    intercepted by Starlette either way (unlike MultiPartException) -- this
    surfaced as an uncaught 500 before item 10/1's fix. DEFAULT_MAX_HEADER_SIZE
    is 4096+128 bytes per header LINE; a 100 KiB filename blows well past
    that."""
    pem, _ = keypair
    boundary = "----hugefilename"
    huge_name = "x" * (100 * 1024)
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="archive"; filename="{huge_name}"\r\n'
        "Content-Type: application/gzip\r\n\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    resp = intake_client.post(
        "/intake/publish",
        headers={
            "authorization": f"Bearer {_jwt(pem)}",
            "content-type": f"multipart/form-data; boundary={boundary}",
        },
        content=body,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json() == {
        "error": "intake_rejected",
        "detail": "Maximum header size exceeded",
    }


def test_invalid_content_length_byte_is_skipped_not_a_500(intake_cfg, keypair):
    """F-D12 item 2 mutation table: reverting the Content-Length pre-check
    from `int(declared)` (wrapped in try/except ValueError) back to
    `declared.isdigit()` survived the round 1 suite. `\\xb2` decodes (latin-1,
    per RFC 9110) to U+00B2 SUPERSCRIPT TWO, for which `str.isdigit()` is
    True but `int()` raises ValueError -- the old `.isdigit()` gate would
    have let it through into a bare `int()` call with no try/except around
    it, crashing with an uncaught exception. TestClient/httpx refuse to
    send a header value that isn't valid latin-1 text, so this has to go
    through raw ASGI, matching the brief's own note."""
    pem, _ = keypair
    app = _intake_app(intake_cfg)
    status, resp_body = asyncio.run(
        _drive_asgi_raw(
            app,
            headers=[
                (b"authorization", f"Bearer {_jwt(pem)}".encode()),
                (b"content-length", b"\xb2"),
            ],
            chunks=[(b"", False)],
        )
    )
    # No Content-Type header at all -> Starlette's _get_form() returns an
    # empty FormData with no exception; the route's own field == 400 on the
    # missing 'meta' field is what proves the pre-check didn't crash.
    assert status == 400, resp_body
    assert json.loads(resp_body) == {
        "error": "intake_rejected",
        "detail": "field 'meta' must be JSON with source_commit (+ optional deletes)",
    }


# ---- Item 3: two caps, two names -- the receive channel bounds the WHOLE
# multipart envelope (max_tar_bytes + _ENVELOPE_ALLOWANCE); read_capped
# bounds the archive part alone (max_tar_bytes, unchanged wording).


def _post_with_archive(client, token, archive_bytes, commit="abc1234"):
    return client.post(
        "/intake/publish",
        headers={"Authorization": f"Bearer {token}"},
        data={"meta": json.dumps({"source_commit": commit, "deletes": []})},
        files={"archive": ("kb.tar.gz", archive_bytes, "application/gzip")},
    )


def test_archive_exactly_at_max_tar_bytes_succeeds(intake_client, intake_cfg, keypair):
    """The direct regression case for item 3: _archive()'s tar.gz is exactly
    130 bytes, sitting inside a ~248-byte multipart envelope. Before this
    fix, max_tar_bytes=130 refused this at the envelope-measuring capped
    receive channel (and, independently, at the declared-Content-Length
    pre-check) even though the archive itself is exactly at the documented
    limit.

    HIGH-2 (Wave H) layered a second, independent budget onto max_tar_bytes:
    safe_extract's per-member content total now also charges one
    tarfile.BLOCKSIZE per member (so an all-headers archive cannot exhaust
    the service on member count alone), and _archive() has one member.

    HIGH-1 (round 3): safe_extract now bounds the DECOMPRESSED stream
    itself (_BoundedTarStream), which charges every real byte tarfile
    reads from it, not just the old size + header-span estimate --
    measured, for this exact one-member archive: the ustar header block
    (BLOCKSIZE), the content block (29 content bytes + the padding
    tarfile's own iterator skips past + the one verification byte it reads
    after seeking, which together always sum to exactly one BLOCKSIZE for
    content shorter than it), and the trailing all-zero block tarfile
    reads to recognize end-of-archive (BLOCKSIZE) -- three blocks, the new
    tightest cap that lets this exact archive through end to end.
    """
    pem, _ = keypair
    intake_cfg.max_tar_bytes = 3 * tarfile.BLOCKSIZE
    resp = _post_with_archive(intake_client, _jwt(pem), _archive())
    assert resp.status_code == 200, resp.text


def test_archive_one_byte_over_cap_is_refused_by_read_capped(
    intake_client, intake_cfg, keypair
):
    pem, _ = keypair
    intake_cfg.max_tar_bytes = 130
    resp = _post_with_archive(intake_client, _jwt(pem), _archive() + b"x")
    assert resp.status_code == 413, resp.text
    assert resp.json() == {
        "error": "intake_rejected",
        "detail": "archive exceeds 130 bytes",
    }



# Item 3's third boundary case -- a body over the body cap (not just the
# archive cap) refused by _capped_receive with the body wording, not
# read_capped's archive wording -- is already exercised above by
# test_chunked_oversized_body_with_no_content_length_is_still_capped
# (same shape: a file part whose data alone dwarfs max_tar_bytes +
# _ENVELOPE_ALLOWANCE, streamed with no Content-Length so the
# declared-length pre-check cannot be the one that catches it). A second
# copy of that scenario here would just be duplication.


# ---- HIGH-1 round 5 (P43): the DECODED pax-header population bound --------
#
# The natural unit home for these is tests/test_intake_core.py, next to the
# other safe_extract bounds; that file is held by another implementer this
# round, so they live here instead -- which is not a bad home: the input is a
# sub-megabyte upload from an authorized publisher, so the HTTP boundary is
# where the denial-of-service it causes actually lands, and _post_with_archive
# exercises the whole route -> intake_publish -> safe_extract path rather than
# safe_extract alone.

_PAX_ALPHABET = string.digits + string.ascii_lowercase + string.ascii_uppercase


def _pax_key(i: int) -> str:
    """Fixed-width 3-character base62 record key (238,328 distinct keys).

    Fixed width matters: with a key whose length grows with the index, a
    header carrying a constant number of records eventually spills past one
    tarfile.BLOCKSIZE, the stream's metadata charge starts firing, and the
    test stops measuring what it claims to measure.
    """
    a = _PAX_ALPHABET
    return a[i // 3844 % 62] + a[i // 62 % 62] + a[i % 62]


def _pax_global(records: dict) -> bytes:
    """A pax-GLOBAL ('g') header block plus its padded body."""
    return tarfile.TarInfo.create_pax_global_header(records)


def _raw_member(name: str, content: bytes = b"") -> bytes:
    info = tarfile.TarInfo(name)
    info.size = len(content)
    info.mtime = 0
    buf = info.tobuf(tarfile.GNU_FORMAT)
    if content:
        buf += content + b"\0" * ((tarfile.BLOCKSIZE - len(content) % tarfile.BLOCKSIZE)
                                  % tarfile.BLOCKSIZE)
    return buf


def _gz_tar(parts: list[bytes]) -> bytes:
    raw = b"".join(parts) + b"\0" * (tarfile.BLOCKSIZE * 2)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        gz.write(raw)
    return buf.getvalue()


def test_many_small_pax_global_headers_are_refused_by_the_population_bound(
    intake_client, keypair
):
    """HIGH-1 / P43: the round-4 bound charged the header READ, and
    `_charge_metadata` returns early on `n <= tarfile.BLOCKSIZE` -- so a pax
    GLOBAL header whose body fits in one 512-byte block is fetched by exactly
    one `read(512)` and costs nothing against it. Interleave many of those
    with real members (a bare chain of globals hits the RecursionError guard
    instead) and CPython accumulates every record into the shared, retained
    `TarFile.pax_headers`, which EVERY member then copies -- O(members^2)
    retained dict entries, none of them charged.

    Measured against this repo before the population bound: 2,000
    (global, member) pairs, a 239 KB upload, ACCEPTED at 2,853 MB peak RSS
    (3,000 pairs: 6,703 MB) against a 35 MB do-nothing baseline, with ZERO
    bytes charged against MAX_PAX_METADATA_BYTES. After: refused at 42 MB.

    This test deliberately asserts the *mechanism* as well as the refusal --
    if a future change makes these headers larger than one block, the
    metadata charge would catch them and the test would go on passing while
    no longer covering the hole it exists for.
    """
    pem, _ = keypair
    parts: list[bytes] = []
    k = 0
    for p in range(40):
        records = {}
        for _ in range(intake.MAX_PAX_RECORDS):
            records[_pax_key(k)] = "1"
            k += 1
        header = _pax_global(records)
        # the mechanism assertion: header block + body block, nothing more,
        # so every read tarfile makes for it is exactly one BLOCKSIZE
        assert len(header) == 2 * tarfile.BLOCKSIZE, len(header)
        parts.append(header)
        parts.append(_raw_member(f"d/f{p}.md"))
    archive = _gz_tar(parts)
    assert len(archive) < 64 * 1024, len(archive)

    resp = _post_with_archive(intake_client, _jwt(pem), archive)
    assert resp.status_code == 413, resp.text
    detail = resp.json()["detail"]
    assert "pax header records" in detail
    assert str(intake.MAX_PAX_RECORDS) in detail
    assert "--format=gnu" in detail


def test_a_pax_global_header_at_the_record_limit_still_publishes(intake_client, keypair):
    """The bound must not refuse a legitimate pax archive. POSIX defines
    twelve pax keywords and the vendor extensions seen in the wild keep a
    real header under twenty, so a single global header at the full
    MAX_PAX_RECORDS is already far past anything real -- and it publishes."""
    pem, _ = keypair
    records = {_pax_key(i): "1" for i in range(intake.MAX_PAX_RECORDS)}
    content = b"docs:\n- id: doc-a\n  title: A\n"
    archive = _gz_tar([_pax_global(records), _raw_member("index.yaml", content)])
    resp = _post_with_archive(intake_client, _jwt(pem), archive)
    assert resp.status_code == 200, resp.text


def test_one_pax_record_over_the_population_limit_is_refused(intake_client, keypair):
    """Off-by-one: MAX_PAX_RECORDS records publish (above), one more does
    not -- and it is refused on the very first member, before any of the
    per-character scans run."""
    pem, _ = keypair
    records = {_pax_key(i): "1" for i in range(intake.MAX_PAX_RECORDS + 1)}
    content = b"docs:\n- id: doc-a\n  title: A\n"
    archive = _gz_tar([_pax_global(records), _raw_member("index.yaml", content)])
    resp = _post_with_archive(intake_client, _jwt(pem), archive)
    assert resp.status_code == 413, resp.text
    assert f"inherits {intake.MAX_PAX_RECORDS + 1} pax header records" in resp.json()["detail"]


def test_pax_records_over_the_decoded_byte_limit_are_refused(intake_client, keypair):
    """The summed-decoded-length half of P43. Few enough records to pass the
    count bound, each carrying a value large enough that their total decoded
    size crosses MAX_PAX_RECORD_BYTES -- and small enough in total that
    MAX_PAX_METADATA_BYTES (1 MiB against the header READ) is not what
    refuses it, so this pins the population byte bound specifically."""
    pem, _ = keypair
    value = "v" * 4096
    records = {_pax_key(i): value for i in range(20)}
    header = _pax_global(records)
    assert len(header) < intake.MAX_PAX_METADATA_BYTES, len(header)
    content = b"docs:\n- id: doc-a\n  title: A\n"
    archive = _gz_tar([header, _raw_member("index.yaml", content)])
    resp = _post_with_archive(intake_client, _jwt(pem), archive)
    assert resp.status_code == 413, resp.text
    detail = resp.json()["detail"]
    assert "decoded pax header records" in detail
    assert str(intake.MAX_PAX_RECORD_BYTES) in detail


def test_an_emoji_tag_sequence_is_refused_while_a_variation_selector_publishes(
    intake_client, keypair
):
    """L1 (round 5, P44): both halves of a documented asymmetry, so it stays
    a decision rather than drifting into an accident.

    U+E0100..U+E01EF (variation selectors, supplement) is exempted from the
    Default_Ignorable refusal; the TAG characters U+E0020..U+E007F, which sit
    in the same Default_Ignorable block and spell emoji subdivision flags,
    are not. See _VARIATION_SELECTORS's comment for why. If a future change
    exempts the whole block, this fails; if a future change drops the
    variation-selector exemption, `❤️.md` stops publishing and this fails too.
    """
    pem, _ = keypair
    england = "\U0001f3f4" + "".join(
        chr(0xE0000 + ord(c)) for c in "gbeng"
    ) + "\U000e007f"
    content = b"docs:\n- id: doc-a\n  title: A\n"
    resp = _post_with_archive(
        intake_client, _jwt(pem), _gz_tar([_raw_member(f"{england}.md", content)])
    )
    assert resp.status_code == 400, resp.text

    heart = "\u2764\ufe0f.md"  # U+2764 + VS16 -- spelling, not a spoof
    resp = _post_with_archive(
        intake_client, _jwt(pem), _gz_tar([_raw_member(heart, content)])
    )
    assert resp.status_code == 200, resp.text
