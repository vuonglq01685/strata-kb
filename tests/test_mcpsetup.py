from pathlib import Path

import pytest

from strata_kb.initcmd import init_repo

HUB = "http://kb-hub.example.com:8321"
TOKEN = "deadbeef" * 6


def _scripted(*responses):
    """An `http` seam returning the given (status, body) pairs in order.

    The returned function records each call as (method, url, headers).
    """
    calls: list[tuple[str, str, dict]] = []
    queue = list(responses)

    def fake(method, url, headers, body):
        calls.append((method, url, headers))
        return queue.pop(0)

    fake.calls = calls
    return fake


# --- normalize_hub_url -----------------------------------------------------


def test_normalize_hub_url_strips_a_trailing_slash():
    from strata_kb.mcpsetup import normalize_hub_url

    assert normalize_hub_url(f"{HUB}/") == HUB
    assert normalize_hub_url(f"  {HUB}  ") == HUB
    assert normalize_hub_url("https://kb.example.com") == "https://kb.example.com"


def test_normalize_hub_url_rejects_a_non_http_scheme():
    from strata_kb.mcpsetup import McpSetupError, normalize_hub_url

    for raw in ("file:///etc/passwd", "ftp://h/x", "kb-hub.example.com:8321"):
        with pytest.raises(McpSetupError, match="http"):
            normalize_hub_url(raw)


def test_normalize_hub_url_rejects_empty():
    from strata_kb.mcpsetup import McpSetupError, normalize_hub_url

    with pytest.raises(McpSetupError, match="empty"):
        normalize_hub_url("   ")


# --- require_client_kind ---------------------------------------------------


def test_require_client_kind_accepts_child_ba_dev(tmp_path: Path):
    from strata_kb.mcpsetup import require_client_kind

    for kind in ("child", "ba", "dev"):
        repo = tmp_path / kind
        repo.mkdir()
        init_repo(repo, kind)
        assert require_client_kind(repo) == kind


def test_require_client_kind_rejects_hub(tmp_path: Path):
    from strata_kb.mcpsetup import McpSetupError, require_client_kind

    init_repo(tmp_path, "hub")
    with pytest.raises(McpSetupError, match="stdio"):
        require_client_kind(tmp_path)


# --- write_env / read_env_value -------------------------------------------


def test_write_env_creates_env_and_gitignore(tmp_path: Path):
    from strata_kb.mcpsetup import HUB_URL_VAR, TOKEN_VAR, write_env

    init_repo(tmp_path, "ba")  # a ba repo gets no root .gitignore from kb init
    assert not (tmp_path / ".gitignore").exists()
    report = write_env(tmp_path, HUB, TOKEN)
    assert report.env_created is True
    assert report.gitignore_updated is True
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"{HUB_URL_VAR}={HUB}" in env
    assert f"{TOKEN_VAR}={TOKEN}" in env
    assert ".env" in (tmp_path / ".gitignore").read_text(encoding="utf-8")


def test_write_env_merges_without_destroying_other_lines(tmp_path: Path):
    from strata_kb.mcpsetup import HUB_URL_VAR, write_env

    init_repo(tmp_path, "child")
    (tmp_path / ".env").write_text(
        "# comment\nOTHER=keep-me\nSTRATA_KB_HUB_URL=http://old:1\n",
        encoding="utf-8",
    )
    report = write_env(tmp_path, HUB, TOKEN)
    assert report.env_created is False
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "# comment" in env
    assert "OTHER=keep-me" in env
    assert f"{HUB_URL_VAR}={HUB}" in env
    assert "http://old:1" not in env


def test_read_env_value_reads_back_what_write_env_wrote(tmp_path: Path):
    from strata_kb.mcpsetup import HUB_URL_VAR, TOKEN_VAR, read_env_value, write_env

    init_repo(tmp_path, "dev")
    write_env(tmp_path, HUB, TOKEN)
    assert read_env_value(tmp_path, HUB_URL_VAR) == HUB
    assert read_env_value(tmp_path, TOKEN_VAR) == TOKEN


def test_read_env_value_returns_empty_without_env(tmp_path: Path):
    from strata_kb.mcpsetup import HUB_URL_VAR, read_env_value

    assert read_env_value(tmp_path, HUB_URL_VAR) == ""


# --- write_env input validation (carried finding 1) ------------------------
#
# dockersetup.set_env_line does not validate its `value` -- a newline inside
# it would inject arbitrary extra lines into `.env`. That was harmless while
# its only caller fed it secrets.token_hex(24), but write_env pipes a
# user-supplied hub URL and a user-supplied token through that exact seam.
# The validation belongs here, at the mcpsetup boundary, not inside the
# shared helper.


def test_write_env_rejects_a_token_with_an_interior_newline(tmp_path: Path):
    from strata_kb.mcpsetup import McpSetupError, write_env

    init_repo(tmp_path, "child")
    malicious = "realtoken\nEVIL=1"
    with pytest.raises(McpSetupError, match="newline"):
        write_env(tmp_path, HUB, malicious)
    # Nothing was written -- rejection happens before any file touch.
    assert not (tmp_path / ".env").exists()


def test_write_env_rejects_a_hub_url_with_an_interior_newline(tmp_path: Path):
    from strata_kb.mcpsetup import McpSetupError, write_env

    init_repo(tmp_path, "child")
    malicious = f"{HUB}\nEVIL=1"
    with pytest.raises(McpSetupError, match="newline"):
        write_env(tmp_path, malicious, TOKEN)
    assert not (tmp_path / ".env").exists()


def test_write_env_rejects_an_interior_carriage_return_in_a_value(tmp_path: Path):
    from strata_kb.mcpsetup import McpSetupError, write_env

    init_repo(tmp_path, "child")
    with pytest.raises(McpSetupError, match="newline"):
        write_env(tmp_path, HUB, "token\rEVIL=1")


# --- write_env / read_env_value strip symmetry (fix wave 1, finding 1) -----
#
# read_env_value already strips its match; write_env did not strip on the
# way in, so a padded or newline-terminated paste survived to disk exactly
# as pasted while the re-verify path silently checked a stripped copy that
# was never what .env actually held.


def test_write_env_strips_leading_and_trailing_whitespace_from_both_values(
    tmp_path: Path,
):
    from strata_kb.mcpsetup import HUB_URL_VAR, TOKEN_VAR, read_env_value, write_env

    init_repo(tmp_path, "child")
    write_env(tmp_path, f"  {HUB}  ", f" {TOKEN} ")
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"{HUB_URL_VAR}={HUB}" in env
    assert f"{TOKEN_VAR}={TOKEN}" in env
    assert read_env_value(tmp_path, HUB_URL_VAR) == HUB
    assert read_env_value(tmp_path, TOKEN_VAR) == TOKEN


def test_write_env_accepts_a_token_with_a_trailing_newline(tmp_path: Path):
    """A trailing newline is the most common artefact of pasting a token out
    of chat or email -- it must be stripped, not rejected as injection."""
    from strata_kb.mcpsetup import TOKEN_VAR, read_env_value, write_env

    init_repo(tmp_path, "child")
    write_env(tmp_path, HUB, f"{TOKEN}\n")
    assert read_env_value(tmp_path, TOKEN_VAR) == TOKEN
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"{TOKEN_VAR}={TOKEN}\n" in env
    # Exactly one line for the token var -- no injected blank/extra line.
    assert env.count(f"{TOKEN_VAR}=") == 1


# --- probe -----------------------------------------------------------------


def test_probe_reports_success_with_a_document_count():
    from strata_kb.mcpsetup import probe

    http = _scripted((200, b"{}"), (200, b'{"docs": [1, 2, 3]}'))
    result = probe(HUB, TOKEN, http=http)
    assert result.ok is True
    assert "3 documents" in result.message
    assert result.warning == ""
    assert http.calls[0][1] == f"{HUB}/api/health"
    assert http.calls[0][2] == {}  # health is auth-exempt; send no token
    assert http.calls[1][1] == f"{HUB}/api/docs"
    # Carried finding 2: the Bearer token must genuinely reach the http
    # seam -- a dropped `headers=` would be a silent auth failure.
    assert http.calls[1][2] == {"Authorization": f"Bearer {TOKEN}"}


def test_probe_succeeds_without_a_count_when_the_body_is_unexpected():
    from strata_kb.mcpsetup import probe

    for body in (b"not json", b"[]", b'{"items": []}'):
        result = probe(HUB, TOKEN, http=_scripted((200, b"{}"), (200, body)))
        assert result.ok is True, body
        assert "documents" not in result.message, body


def test_probe_reports_an_unreachable_hub():
    from strata_kb.mcpsetup import probe

    result = probe(HUB, TOKEN, http=_scripted((0, b"Connection refused")))
    assert result.ok is False
    assert "cannot reach" in result.message
    assert "Connection refused" in result.message


def test_probe_reports_a_url_that_is_not_a_hub():
    from strata_kb.mcpsetup import probe

    result = probe(HUB, TOKEN, http=_scripted((404, b"")))
    assert result.ok is False
    assert "does not look like a Strata KB hub" in result.message


@pytest.mark.parametrize("status", [401, 403])
def test_probe_reports_a_rejected_token(status: int):
    from strata_kb.mcpsetup import probe

    result = probe(HUB, TOKEN, http=_scripted((200, b"{}"), (status, b"")))
    assert result.ok is False
    assert "token was rejected" in result.message
    assert str(status) in result.message


def test_probe_treats_503_as_a_valid_token_with_a_warning():
    from strata_kb.mcpsetup import probe

    result = probe(HUB, TOKEN, http=_scripted((200, b"{}"), (503, b"")))
    # 503 from /api/docs can only arrive after the auth middleware passed
    # the request, so it proves the token is good.
    assert result.ok is True
    assert "token accepted" in result.message
    assert "503" in result.warning


def test_probe_reports_an_unexpected_docs_status():
    from strata_kb.mcpsetup import probe

    result = probe(HUB, TOKEN, http=_scripted((200, b"{}"), (500, b"")))
    assert result.ok is False
    assert "unexpected 500" in result.message


def test_probe_reports_a_connection_lost_between_the_two_checks():
    from strata_kb.mcpsetup import probe

    result = probe(HUB, TOKEN, http=_scripted((200, b"{}"), (0, b"timed out")))
    assert result.ok is False
    assert "timed out" in result.message


# --- _default_http (fix wave 1, finding 2) ----------------------------------
#
# probe()'s own tests only ever exercise the injected `http` seam, so they
# never touch _default_http itself. That left the _default_http -> httpio
# .request -> urllib.Request chain unpinned: a mutant that forwards {}
# instead of `headers` passed the whole suite. Pin it directly.


def test_default_http_forwards_headers_and_the_probe_timeout(monkeypatch):
    from strata_kb import httpio
    from strata_kb.mcpsetup import PROBE_TIMEOUT, _default_http

    calls = []

    def fake_request(method, url, headers, body, timeout=60):
        calls.append((method, url, headers, body, timeout))
        return 200, b"{}"

    monkeypatch.setattr(httpio, "request", fake_request)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    _default_http("GET", f"{HUB}/api/docs", headers, None)

    assert len(calls) == 1
    _, _, sent_headers, _, sent_timeout = calls[0]
    assert sent_headers == headers
    assert sent_timeout == PROBE_TIMEOUT
