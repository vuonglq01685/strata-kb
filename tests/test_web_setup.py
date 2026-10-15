"""First-run admin setup: /ui/setup, gated by a one-time code printed to the log."""

from __future__ import annotations

import logging
import re

import anyio
import pytest

from strata_kb.serving.accounts import Accounts, hash_password
from strata_kb.serving.auth import COOKIE_NAME
from strata_kb.serving.ratelimit import LOGIN_MAX_ATTEMPTS
from strata_kb.web.ui import LOGIN_MAX_BODY

CODE_RE = re.compile(r"^[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}$")


def _config(hub_dir):
    from strata_kb.mcp import ServerConfig

    return ServerConfig(kb_dir=hub_dir / ".kb", hub=str(hub_dir))


def _make_app(hub_dir, token):
    from strata_kb.web.app import create_app

    return create_app(_config(hub_dir), token)


def _users(hub_dir) -> Accounts:
    return Accounts(hub_dir / ".kb-auth" / "users.db")


def _code(client) -> str:
    code = client.app.setup.code
    assert code is not None
    return code


def _post(client, code, username="boss", password="pw-1", confirm=None):
    return client.post(
        "/ui/setup",
        data={
            "username": username,
            "password": password,
            "confirm": password if confirm is None else confirm,
            "code": code,
        },
        follow_redirects=False,
    )


# --- routing -----------------------------------------------------------------


@pytest.mark.parametrize("path", ["/ui", "/ui/login", "/ui/docs", "/"])
def test_zero_users_ui_pages_redirect_to_setup(web_client, path):
    r = web_client.get(path, follow_redirects=True)
    assert r.url.path == "/ui/setup"
    first = web_client.get(path, follow_redirects=False)
    if path.startswith("/ui"):
        assert first.status_code == 303
        assert first.headers["location"] == "/ui/setup"


def test_zero_users_api_and_health_are_unaffected(web_client, token):
    assert web_client.get("/api/health").status_code == 200
    assert web_client.get("/api/docs").status_code == 401
    ok = web_client.get("/api/docs", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200


def test_zero_users_static_assets_still_load(web_client):
    assert web_client.get("/ui/static/style.css").status_code == 200


def test_setup_form_renders_fields_and_hint(web_client):
    r = web_client.get("/ui/setup")
    assert r.status_code == 200
    for name in ("username", "password", "confirm", "code"):
        assert f'name="{name}"' in r.text
    assert "docker compose logs hub" in r.text
    assert _code(web_client) not in r.text


def test_once_a_user_exists_login_shows_and_setup_is_404(web_client, admin_user):
    assert web_client.get("/ui/login").status_code == 200
    assert web_client.get("/ui/setup").status_code == 404
    assert web_client.post("/ui/setup", data={}).status_code == 404


def test_setup_is_404_for_a_logged_in_user_too(web_client_logged_in):
    assert web_client_logged_in.get("/ui/setup").status_code == 404


def test_login_page_no_longer_carries_the_empty_accounts_hint(web_client, admin_user):
    assert "kb user add" not in web_client.get("/ui/login").text


# --- the code ----------------------------------------------------------------


def test_code_is_logged_once_at_startup_when_no_users(hub_dir, token, caplog):
    with caplog.at_level(logging.WARNING):
        app = _make_app(hub_dir, token)
    lines = [r.getMessage() for r in caplog.records if "/ui/setup" in r.getMessage()]
    assert len(lines) == 1
    code = app.setup.code
    assert code is not None and CODE_RE.match(code)
    assert lines[0] == (
        f"No hub account yet — open /ui/setup and enter setup code: {code}"
    )


def test_code_is_not_logged_when_users_exist(hub_dir, token, caplog):
    _users(hub_dir).add("boss", "pw", "admin")
    with caplog.at_level(logging.DEBUG):
        app = _make_app(hub_dir, token)
    assert app.setup.code is None
    assert "setup code" not in caplog.text


def test_code_is_not_logged_when_env_bootstrap_made_the_admin(
    hub_dir, token, caplog, monkeypatch
):
    monkeypatch.setenv("STRATA_KB_BOOTSTRAP_ADMIN", "envadmin")
    monkeypatch.setenv("STRATA_KB_BOOTSTRAP_PASSWORD_HASH", hash_password("pw"))
    with caplog.at_level(logging.DEBUG):
        app = _make_app(hub_dir, token)
    assert app.setup.code is None
    assert "setup code" not in caplog.text
    assert _users(hub_dir).get("envadmin") is not None


def test_each_start_gets_a_fresh_code(hub_dir, token):
    a, b = _make_app(hub_dir, token), _make_app(hub_dir, token)
    assert a.setup.code != b.setup.code


def test_the_code_never_touches_disk(hub_dir, token):
    app = _make_app(hub_dir, token)
    code = app.setup.code
    assert code is not None
    for path in hub_dir.rglob("*"):
        if path.is_file() and ".git/" not in path.as_posix():
            assert code.encode() not in path.read_bytes(), path


# --- submit: failures --------------------------------------------------------


def test_wrong_code_shows_form_with_message_and_creates_nothing(web_client, hub_dir):
    r = _post(web_client, "AAAA-AAAA")
    assert r.status_code == 200
    assert "Wrong setup code — copy it from the hub log." in r.text
    assert _users(hub_dir).count() == 0
    assert COOKIE_NAME not in r.cookies


def test_wrong_code_does_not_reveal_other_fields_validity(web_client):
    r = _post(web_client, "AAAA-AAAA", username="", password="a", confirm="b")
    assert "Wrong setup code" in r.text
    assert "match" not in r.text and "username" not in r.text.split("<form")[0]


def test_mismatched_passwords_error_no_user_no_echo(web_client, hub_dir):
    code = _code(web_client)
    r = _post(web_client, code, password="pw-one-xyz", confirm="pw-two-xyz")
    assert r.status_code == 200
    assert "Passwords do not match" in r.text
    assert "pw-one-xyz" not in r.text and "pw-two-xyz" not in r.text
    assert code not in r.text
    assert _users(hub_dir).count() == 0


def test_empty_password_is_refused(web_client, hub_dir):
    r = _post(web_client, _code(web_client), password="")
    assert r.status_code == 200 and "Password must not be empty" in r.text
    assert _users(hub_dir).count() == 0


@pytest.mark.parametrize("username", ["", " boss", "boss "])
def test_invalid_username_is_refused(web_client, hub_dir, username):
    r = _post(web_client, _code(web_client), username=username)
    assert r.status_code == 200
    assert "username must be non-empty without surrounding whitespace" in r.text
    assert _users(hub_dir).count() == 0


def test_unbindable_username_is_a_message_not_an_exception(hub_dir):
    from strata_kb.serving.auth import SessionAuth
    from strata_kb.web.ui import _create_first_admin

    accts = _users(hub_dir)
    msg = _create_first_admin(SessionAuth(b"k" * 32, accts), "a\udcffb", "pw")
    assert msg == "Could not create the account."
    assert accts.count() == 0


def test_non_ascii_code_is_a_wrong_code_not_a_500(web_client):
    r = _post(web_client, "ÀÀÀÀ-ÀÀÀÀ")
    assert r.status_code == 200 and "Wrong setup code" in r.text


# --- submit: success ---------------------------------------------------------


def test_correct_submit_creates_admin_sets_cookie_and_redirects(web_client, hub_dir):
    code = _code(web_client)
    r = _post(web_client, code, username="boss", password="pw-1")
    assert r.status_code == 303 and r.headers["location"] == "/ui"
    assert COOKIE_NAME in r.cookies
    user = _users(hub_dir).get("boss")
    assert user is not None and user.role == "admin"
    assert web_client.get("/ui", follow_redirects=False).status_code == 200


def test_code_is_accepted_lowercase_and_padded(web_client, hub_dir):
    code = _code(web_client)
    r = _post(web_client, f"  {code.lower()} ")
    assert r.status_code == 303
    assert _users(hub_dir).count() == 1


def test_after_success_setup_is_404_and_code_is_dead(web_client, hub_dir):
    code = _code(web_client)
    assert _post(web_client, code).status_code == 303
    assert web_client.app.setup.code is None
    web_client.cookies.clear()
    assert web_client.get("/ui/setup").status_code == 404
    assert _post(web_client, code, username="second").status_code == 404
    assert _users(hub_dir).count() == 1
    assert web_client.get("/ui/login").status_code == 200


def test_user_created_after_page_load_closes_setup(web_client, hub_dir):
    code = _code(web_client)
    _users(hub_dir).add("winner", "pw", "admin")  # lands between page load and submit
    r = _post(web_client, code, username="loser")
    assert r.status_code == 404  # users exist now: setup is closed


def test_race_inside_the_transaction_redirects_to_login(
    web_client, hub_dir, monkeypatch
):
    code = _code(web_client)
    real = Accounts.add_first_admin

    def lose(self, username, password):
        self.add("winner", "pw", "admin")  # the other request commits first
        return real(self, username, password)

    monkeypatch.setattr(Accounts, "add_first_admin", lose)
    r = _post(web_client, code, username="loser")
    assert r.status_code == 303 and r.headers["location"] == "/ui/login"
    assert COOKIE_NAME not in r.cookies
    assert _users(hub_dir).get("loser") is None


def test_no_code_active_page_says_so_and_does_not_crash(web_client, hub_dir):
    web_client.app.setup.consume()
    r = web_client.get("/ui/setup")
    assert r.status_code == 200
    assert "no setup code is active" in r.text.lower()
    assert "kb user add" in r.text
    r = _post(web_client, "AAAA-AAAA")
    assert r.status_code == 200 and _users(hub_dir).count() == 0


# --- abuse limits ------------------------------------------------------------


def test_bad_setup_posts_and_login_share_one_bucket(web_client, hub_dir):
    for _ in range(LOGIN_MAX_ATTEMPTS):
        assert _post(web_client, "AAAA-AAAA").status_code == 200
    assert _post(web_client, _code(web_client)).status_code == 429
    assert _users(hub_dir).count() == 0
    _users(hub_dir).add("boss", "pw", "admin")
    locked = web_client.post(
        "/ui/login",
        data={"username": "boss", "password": "pw"},
        follow_redirects=False,
    )
    assert locked.status_code == 429


def test_login_failures_lock_setup(web_client, hub_dir):
    for _ in range(LOGIN_MAX_ATTEMPTS):
        web_client.post(
            "/ui/login", data={"username": "x", "password": "y"}, follow_redirects=False
        )
    assert _post(web_client, _code(web_client)).status_code == 429


def test_oversized_content_length_is_413(web_client, hub_dir):
    r = web_client.post(
        "/ui/setup",
        content=b"password=" + b"x" * (LOGIN_MAX_BODY + 1),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 413
    assert _users(hub_dir).count() == 0


def test_a_chunked_setup_body_is_refused_at_the_cap(hub_dir, token):
    app = _make_app(hub_dir, token)
    chunk = b"password=" + b"x" * 1015
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
        "path": "/ui/setup",
        "raw_path": b"/ui/setup",
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


def test_many_small_fields_are_a_client_error(web_client):
    data = {f"f{i}": "x" for i in range(50)}
    resp = web_client.post("/ui/setup", data=data, follow_redirects=False)
    assert resp.status_code in (400, 413)


def test_a_multipart_file_part_is_refused(web_client, hub_dir):
    resp = web_client.post(
        "/ui/setup", files={"password": ("t.txt", b"abc")}, follow_redirects=False
    )
    assert resp.status_code in (400, 413)
    assert _users(hub_dir).count() == 0


# --- logs --------------------------------------------------------------------


def test_submitted_password_and_code_never_reach_the_logs(web_client, caplog):
    code = _code(web_client)
    with caplog.at_level(logging.DEBUG):
        _post(web_client, "ZZZZ-ZZZZ", password="hunter2-secret")
        _post(web_client, code, password="hunter2-other", confirm="mismatch-pw")
        _post(web_client, code, username=" bad", password="hunter2-third")
    assert "hunter2" not in caplog.text and "mismatch-pw" not in caplog.text
    assert "ZZZZ-ZZZZ" not in caplog.text
    assert code not in caplog.text
