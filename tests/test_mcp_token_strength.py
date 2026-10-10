"""2026-10-10 review §5.2 #5: the http server must refuse a token it cannot
defend -- the cookie is HMAC(token, issued), so a weak token falls to an
offline brute force of any copied cookie."""

from __future__ import annotations

import secrets

import pytest

from strata_kb import mcp


@pytest.mark.parametrize(
    "token",
    [
        "change-me",
        "x" * 31,
        "é" * 40,
        "a" * 39 + "\n",
        "a" * 20 + " " + "b" * 20,
    ],
)
def test_weak_or_unsendable_tokens_are_refused(token):
    with pytest.raises(SystemExit) as exc:
        mcp.check_http_token(token)
    msg = str(exc.value)
    assert "STRATA_KB_HTTP_TOKEN" in msg
    assert "kb docker-setup --force" in msg
    assert token.strip() not in msg or token == "change-me"


def test_a_generated_token_is_accepted():
    mcp.check_http_token(secrets.token_hex(24))
    mcp.check_http_token("x" * 32)


def test_the_shipped_env_example_placeholder_is_refused():
    from importlib.resources import files

    text = (files("strata_kb") / "templates" / "init" / "env.example").read_text(
        encoding="utf-8"
    )
    value = text.split("STRATA_KB_HTTP_TOKEN=", 1)[1].splitlines()[0]
    with pytest.raises(SystemExit):
        mcp.check_http_token(value)


def test_main_refuses_a_weak_token_before_starting_uvicorn(fed_hub, monkeypatch):
    import uvicorn

    started = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(1))
    monkeypatch.setattr("strata_kb.hub.start_auto_pull", lambda *a, **k: None)
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", "secret")
    with pytest.raises(SystemExit) as exc:
        mcp.main(["--hub", str(fed_hub), "--transport", "http"])
    assert "at least 32" in str(exc.value)
    assert started == []


def test_main_starts_with_a_strong_token(fed_hub, monkeypatch):
    import uvicorn

    started = []
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: started.append(1))
    monkeypatch.setattr("strata_kb.hub.start_auto_pull", lambda *a, **k: None)
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", secrets.token_hex(24))
    mcp.main(["--hub", str(fed_hub), "--transport", "http"])
    assert started == [1]
