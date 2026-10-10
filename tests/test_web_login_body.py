"""2026-10-10 review §5.2 #2 / #3: `POST /ui/login` is reachable without a
token, so its body must be bounded however it is framed, and no submitted
value may turn into a 500."""

from __future__ import annotations

import anyio
import pytest

from strata_kb.web.ratelimit import LOGIN_MAX_ATTEMPTS
from strata_kb.web.ui import LOGIN_MAX_BODY


def _asgi_app(hub_dir, token):
    from strata_kb.mcp import ServerConfig
    from strata_kb.web.app import create_app

    return create_app(ServerConfig(kb_dir=hub_dir / ".kb", hub=str(hub_dir)), token)


def test_a_chunked_login_body_is_refused_at_the_cap(hub_dir, token):
    """No Content-Length, 10 MiB offered in 1 KiB chunks: the server must
    stop reading at LOGIN_MAX_BODY, not buffer the lot (the PoC sent 120
    1 MiB fields for +123 MiB RSS)."""
    app = _asgi_app(hub_dir, token)
    chunk = b"token=" + b"x" * 1018  # 1 KiB
    total_chunks = 10 * 1024
    pulled = 0
    sent: list[dict] = []

    async def receive():
        nonlocal pulled
        pulled += 1
        return {
            "type": "http.request",
            "body": chunk,
            "more_body": pulled < total_chunks,
        }

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/ui/login",
        "raw_path": b"/ui/login",
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"host", b"testserver"),
            (b"content-type", b"application/x-www-form-urlencoded"),
            (b"transfer-encoding", b"chunked"),
        ],
        "client": ("10.9.9.9", 1234),
        "server": ("testserver", 80),
    }
    anyio.run(app, scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert start["status"] == 413
    assert pulled <= LOGIN_MAX_BODY // len(chunk) + 2


def test_many_small_fields_are_a_client_error_not_a_500(web_client):
    data = {f"f{i}": "x" for i in range(50)}
    resp = web_client.post("/ui/login", data=data, follow_redirects=False)
    assert resp.status_code in (400, 413)


def test_a_multipart_file_part_on_login_is_refused(web_client):
    resp = web_client.post(
        "/ui/login", files={"token": ("t.txt", b"abc")}, follow_redirects=False
    )
    assert resp.status_code in (400, 413)


@pytest.mark.parametrize("guess", ["héllo", "токен", "🔑" * 3])
def test_a_non_ascii_guess_is_a_failed_login_not_a_500(web_client, guess):
    resp = web_client.post("/ui/login", data={"token": guess}, follow_redirects=False)
    assert resp.status_code == 200
    assert "Invalid token" in resp.text


def test_non_ascii_guesses_spend_the_lockout(web_client):
    codes = [
        web_client.post(
            "/ui/login", data={"token": "ñ"}, follow_redirects=False
        ).status_code
        for _ in range(LOGIN_MAX_ATTEMPTS + 1)
    ]
    assert codes[:LOGIN_MAX_ATTEMPTS] == [200] * LOGIN_MAX_ATTEMPTS
    assert codes[-1] == 429


def test_the_right_token_still_logs_in(web_client, token):
    resp = web_client.post("/ui/login", data={"token": token}, follow_redirects=False)
    assert resp.status_code == 303
