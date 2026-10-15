"""Username/password login, user sessions, and what the middleware attaches."""

from __future__ import annotations

import hashlib
import hmac

from strata_kb.serving.accounts import Accounts, User
from strata_kb.serving.auth import COOKIE_NAME, current_user, make_user_session


def _login(client, username, password):
    return client.post(
        "/ui/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def test_login_with_username_password_sets_cookie(web_client, admin_user):
    u, pw = admin_user
    r = _login(web_client, u, pw)
    assert r.status_code == 303 and COOKIE_NAME in r.cookies


def test_wrong_password_and_unknown_user_same_message(web_client, admin_user):
    a = _login(web_client, admin_user[0], "x")
    b = _login(web_client, "ghost", "x")
    assert "Wrong username or password" in a.text
    assert "Wrong username or password" in b.text
    assert COOKIE_NAME not in a.cookies and COOKIE_NAME not in b.cookies


def test_token_in_login_form_no_longer_logs_in(web_client, admin_user, token):
    r = _login(web_client, "", token)
    assert COOKIE_NAME not in r.cookies
    r = _login(web_client, admin_user[0], token)
    assert COOKIE_NAME not in r.cookies
    assert web_client.get("/ui", follow_redirects=False).status_code == 302


def test_empty_accounts_login_redirects_to_setup(web_client):
    r = web_client.get("/ui/login", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/ui/setup"


def test_login_page_hides_bootstrap_hint_once_an_account_exists(web_client, admin_user):
    assert "kb user add" not in web_client.get("/ui/login").text


def test_cookie_signed_with_bearer_token_is_rejected(web_client, admin_user, token):
    forged = make_user_session(
        token.encode(), User(admin_user[0], "admin", "h", "", "")
    )
    web_client.cookies.set(COOKIE_NAME, forged)
    assert web_client.get("/ui", follow_redirects=False).status_code == 302


def test_password_change_ends_session(web_client_logged_in, hub_dir, admin_user):
    Accounts(hub_dir / ".kb-auth/users.db").set_password(admin_user[0], "new-pw")
    assert web_client_logged_in.get("/ui", follow_redirects=False).status_code == 302


def test_removed_user_session_ends(web_client, hub_dir, admin_user):
    accounts = Accounts(hub_dir / ".kb-auth/users.db")
    accounts.add("second", "pw-2", "admin")
    assert _login(web_client, "second", "pw-2").status_code == 303
    assert web_client.get("/ui", follow_redirects=False).status_code == 200
    accounts.remove("second")
    assert web_client.get("/ui", follow_redirects=False).status_code == 302


def test_bearer_request_has_no_user(web_client, token, admin_user):
    r = web_client.get("/ui", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.url.path == "/ui"
    assert 'href="/ui/registry"' not in r.text


def test_admin_sees_registry_nav(web_client_logged_in):
    assert 'href="/ui/registry"' in web_client_logged_in.get("/ui").text


def test_non_admin_does_not_see_registry_nav(web_client, hub_dir):
    Accounts(hub_dir / ".kb-auth/users.db").add("dana", "pw-d", "dev")
    assert _login(web_client, "dana", "pw-d").status_code == 303
    r = web_client.get("/ui")
    assert r.status_code == 200 and 'href="/ui/registry"' not in r.text


def test_old_format_cookie_rejected(web_client, token, admin_user):
    # The pre-1.26 value: `<issued>.<hmac_sha256(token, issued)>`.
    issued = "1700000000"
    sig = hmac.new(token.encode(), issued.encode(), hashlib.sha256).hexdigest()
    web_client.cookies.set(COOKIE_NAME, f"{issued}.{sig}")
    assert web_client.get("/ui", follow_redirects=False).status_code == 302


def test_middleware_attaches_user_to_request_state(admin_user, hub_dir):
    """A cookie session sets request.state.user; a bearer request does not."""
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    from strata_kb.serving.accounts import load_or_create_session_key
    from strata_kb.serving.auth import SessionAuth, TokenAuthMiddleware

    async def whoami(request):
        user = current_user(request)
        return PlainTextResponse(f"{user.username}/{user.role}" if user else "-")

    auth_dir = hub_dir / ".kb-auth"
    accounts = Accounts(auth_dir / "users.db")
    session = SessionAuth(load_or_create_session_key(auth_dir), accounts)
    app = TokenAuthMiddleware(
        Starlette(routes=[Route("/api/whoami", whoami)]), "tok", session=session
    )
    c = TestClient(app)
    assert c.get("/api/whoami", headers={"Authorization": "Bearer tok"}).text == "-"
    user = accounts.get(admin_user[0])
    assert user is not None
    c.cookies.set(COOKIE_NAME, make_user_session(session.key, user))
    assert c.get("/api/whoami").text == "admin/admin"


def test_role_change_hides_registry_nav_on_next_request(web_client, hub_dir):
    accounts = Accounts(hub_dir / ".kb-auth/users.db")
    accounts.add("boss", "pw-b", "admin")
    accounts.add("other", "pw-o", "admin")  # keeps an admin after the demotion
    assert _login(web_client, "boss", "pw-b").status_code == 303
    assert 'href="/ui/registry"' in web_client.get("/ui").text
    accounts.set_role("boss", "dev")
    r = web_client.get("/ui")
    assert r.status_code == 200 and 'href="/ui/registry"' not in r.text


def test_bearer_request_after_cookie_request_has_no_registry_nav(
    web_client_logged_in, token
):
    assert 'href="/ui/registry"' in web_client_logged_in.get("/ui").text
    r = web_client_logged_in.get("/ui", headers={"Authorization": f"Bearer {token}"})
    # The cookie jar still sends the session cookie, but a valid bearer wins
    # and carries no account.
    assert r.status_code == 200 and 'href="/ui/registry"' not in r.text


def test_sqlite_error_during_login_is_a_failed_login_not_a_500(
    web_client, admin_user, monkeypatch
):
    import sqlite3

    def boom(self, username, password):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Accounts, "verify", boom)
    r = _login(web_client, *admin_user)
    assert r.status_code == 200 and COOKIE_NAME not in r.cookies
    assert "Wrong username or password" in r.text


def test_sqlite_error_during_session_lookup_is_logged_out_not_a_500(
    web_client_logged_in, monkeypatch
):
    import sqlite3

    def boom(self, username):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(Accounts, "get", boom)
    r = web_client_logged_in.get("/ui", follow_redirects=False)
    assert r.status_code == 302
