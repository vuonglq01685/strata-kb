# tests/test_intake_http.py
from __future__ import annotations

import io
import json
import subprocess
import tarfile
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.testclient import TestClient

from center_kb import ghapp, intake
from center_kb.web import intake_routes

AUD = "https://kb.test"


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
    st = c.get("/intake/status", params={"repo_id": "flight-docs", "commit": "abc1234"})
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
    c, _ = client
    resp = c.get("/intake/status", params={"repo_id": "x", "commit": "y"})
    assert resp.status_code == 404


def test_auth_middleware_exempts_exact_intake_paths_only():
    """No prefix wildcard: a future /intake/* route must not be exposed by accident."""
    from center_kb.web import auth

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
    from center_kb.web.ratelimit import SlidingWindowLimiter

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


def test_publish_traversal_delete_maps_400_not_500(client):
    """A crafted deletes path is rejected fail-closed — must be a clean 4xx."""
    c, pem = client
    resp = _post(c, _jwt(pem), deletes=["../../outside.txt"])
    assert resp.status_code == 400
    assert resp.json()["error"] == "intake_rejected"
    st = c.get("/intake/status", params={"repo_id": "flight-docs", "commit": "abc1234"})
    assert st.status_code == 200
    assert st.json()["state"] == "error"


def test_publish_git_error_maps_502_and_records_error(client, monkeypatch):
    from center_kb import gitio

    def boom(*args, **kwargs):
        raise gitio.GitError("boom")

    c, pem = client
    monkeypatch.setattr(intake, "intake_publish", boom)
    resp = _post(c, _jwt(pem))
    assert resp.status_code == 502
    assert resp.json()["error"] == "publish_failed"
    st = c.get("/intake/status", params={"repo_id": "flight-docs", "commit": "abc1234"})
    assert st.status_code == 200
    assert st.json()["state"] == "error"


# ---- integration: production-shaped stack (TokenAuthMiddleware + routes) ----


@pytest.fixture
def full_stack(hub_with_registry, keypair, tmp_path, monkeypatch):
    """Mount /intake/* behind TokenAuthMiddleware exactly as create_app does,
    plus one non-intake route to bound the exemption's blast radius."""
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from center_kb.web.auth import TokenAuthMiddleware

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
    # status: public by design (zero-secret dev polling, keyed by rid+commit);
    # 404 from the route handler, not 401 from the middleware
    st = c.get("/intake/status", params={"repo_id": "x", "commit": "y"})
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
    monkeypatch.delenv("CENTER_KB_GH_APP_ID", raising=False)
    assert intake.intake_config_from_env("hub") is None
    pem_path = tmp_path / "app.pem"
    pem_path.write_text("PEM", encoding="utf-8")
    monkeypatch.setenv("CENTER_KB_GH_APP_ID", "1234")
    monkeypatch.setenv("CENTER_KB_GH_APP_KEY", str(pem_path))
    monkeypatch.setenv("CENTER_KB_INTAKE_AUDIENCE", AUD)
    cfg = intake.intake_config_from_env("hub")
    assert cfg is not None
    assert cfg.creds.app_id == "1234"
    assert cfg.creds.private_key_pem == "PEM"
    assert cfg.audience == AUD
    # broken PEM path → None (fail closed), no raise
    monkeypatch.setenv("CENTER_KB_GH_APP_KEY", str(tmp_path / "missing.pem"))
    assert intake.intake_config_from_env("hub") is None
