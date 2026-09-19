from pathlib import Path

import pytest
from typer.testing import CliRunner

from strata_kb.cli import app
from strata_kb.initcmd import init_repo
from tests.test_cli_errors import _assert_no_propagated_exception

runner = CliRunner()

HUB = "http://kb-hub.example.com:8321"
TOKEN = "deadbeef" * 6


def _ok_probe(monkeypatch, warning: str = ""):
    """Replace the probe; record the (url, token) it was called with."""
    from strata_kb import mcpsetup

    seen: dict = {}

    def fake(hub_url, token, http=None):
        seen["url"] = hub_url
        seen["token"] = token
        return mcpsetup.ProbeResult(True, "hub reached — token accepted", warning)

    monkeypatch.setattr(mcpsetup, "probe", fake)
    return seen


def _failing_probe(monkeypatch, message: str = "cannot reach the hub"):
    from strata_kb import mcpsetup

    calls: list = []

    def fake(hub_url, token, http=None):
        calls.append((hub_url, token))
        return mcpsetup.ProbeResult(False, message)

    monkeypatch.setattr(mcpsetup, "probe", fake)
    return calls


def _never_probe(monkeypatch):
    from strata_kb import mcpsetup

    calls: list = []

    def fake(hub_url, token, http=None):
        calls.append((hub_url, token))
        raise AssertionError("probe must not run under --no-verify")

    monkeypatch.setattr(mcpsetup, "probe", fake)
    return calls


@pytest.mark.parametrize("kind", ["child", "ba", "dev"])
def test_mcp_setup_writes_env_and_verifies(tmp_path: Path, monkeypatch, kind):
    init_repo(tmp_path, kind)
    seen = _ok_probe(monkeypatch)
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", f"{HUB}/", "--token", TOKEN]
    )
    assert result.exit_code == 0, result.output
    env = (tmp_path / ".env").read_text(encoding="utf-8")
    assert f"STRATA_KB_HUB_URL={HUB}" in env  # trailing slash stripped
    assert f"STRATA_KB_HTTP_TOKEN={TOKEN}" in env
    assert seen == {"url": HUB, "token": TOKEN}
    assert "token accepted" in result.output
    assert "Restart" in result.output


def test_mcp_setup_never_prints_the_token(tmp_path: Path, monkeypatch):
    init_repo(tmp_path, "dev")
    _ok_probe(monkeypatch)
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    assert result.exit_code == 0
    assert TOKEN not in result.output


def test_mcp_setup_warns_that_token_flag_hits_shell_history(
    tmp_path: Path, monkeypatch
):
    init_repo(tmp_path, "ba")
    _ok_probe(monkeypatch)
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    assert "shell history" in result.output


def test_mcp_setup_creates_gitignore_on_a_ba_repo(tmp_path: Path, monkeypatch):
    init_repo(tmp_path, "ba")
    _ok_probe(monkeypatch)
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    assert result.exit_code == 0
    assert ".env" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".gitignore updated" in result.output


def test_mcp_setup_refuses_the_hub_kind(tmp_path: Path):
    init_repo(tmp_path, "hub")
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "stdio" in result.output
    assert not (tmp_path / ".env").exists()


def test_mcp_setup_refuses_an_uninitialized_repo(tmp_path: Path):
    # A bare directory: load_config returns defaults, so kind is "".
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "kb init" in result.output
    assert not (tmp_path / ".env").exists()


def test_mcp_setup_prints_how_to_load_the_env(tmp_path: Path, monkeypatch):
    init_repo(tmp_path, "child")
    _ok_probe(monkeypatch)
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    assert result.exit_code == 0
    assert "set -a; source .env; set +a" in result.output
    assert "PowerShell" in result.output
    assert "direnv" in result.output


def test_mcp_setup_refuses_a_non_http_url(tmp_path: Path):
    init_repo(tmp_path, "child")
    result = runner.invoke(
        app,
        ["mcp-setup", str(tmp_path), "--hub-url", "file:///etc/passwd",
         "--token", TOKEN],
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "http://" in result.output
    assert not (tmp_path / ".env").exists()


def test_mcp_setup_no_verify_skips_the_probe(tmp_path: Path, monkeypatch):
    init_repo(tmp_path, "dev")
    _never_probe(monkeypatch)
    result = runner.invoke(
        app,
        ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN,
         "--no-verify"],
    )
    assert result.exit_code == 0
    assert "STRATA_KB_HUB_URL" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_mcp_setup_keeps_env_written_when_the_probe_fails(
    tmp_path: Path, monkeypatch
):
    init_repo(tmp_path, "child")
    _failing_probe(monkeypatch)
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "cannot reach the hub" in result.output
    assert ".env is written" in result.output
    assert f"STRATA_KB_HTTP_TOKEN={TOKEN}" in (
        tmp_path / ".env"
    ).read_text(encoding="utf-8")


def test_mcp_setup_exits_zero_on_the_503_warning(tmp_path: Path, monkeypatch):
    init_repo(tmp_path, "ba")
    _ok_probe(monkeypatch, warning="the hub reports its own KB is not ready (503)")
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    assert result.exit_code == 0
    assert "503" in result.output


def test_mcp_setup_rerun_reuses_the_values_from_env(tmp_path: Path, monkeypatch):
    """The wrapper's step 4: a bare re-run re-verifies and asks nothing."""
    init_repo(tmp_path, "dev")
    seen = _ok_probe(monkeypatch)
    runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    seen.clear()
    monkeypatch.delenv("STRATA_KB_HUB_URL", raising=False)
    monkeypatch.delenv("STRATA_KB_HTTP_TOKEN", raising=False)
    result = runner.invoke(app, ["mcp-setup", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert seen == {"url": HUB, "token": TOKEN}


def test_mcp_setup_reads_the_token_from_the_environment(
    tmp_path: Path, monkeypatch
):
    init_repo(tmp_path, "child")
    seen = _ok_probe(monkeypatch)
    monkeypatch.setenv("STRATA_KB_HTTP_TOKEN", TOKEN)
    result = runner.invoke(app, ["mcp-setup", str(tmp_path), "--hub-url", HUB])
    assert result.exit_code == 0, result.output
    assert seen["token"] == TOKEN
    assert "shell history" not in result.output


def test_mcp_setup_fails_without_a_token_and_without_a_tty(
    tmp_path: Path, monkeypatch
):
    from strata_kb import cli

    init_repo(tmp_path, "ba")
    monkeypatch.delenv("STRATA_KB_HTTP_TOKEN", raising=False)
    monkeypatch.setattr(cli, "_stdin_isatty", lambda: False)
    result = runner.invoke(app, ["mcp-setup", str(tmp_path), "--hub-url", HUB])
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "STRATA_KB_HTTP_TOKEN" in result.output
    assert not (tmp_path / ".env").exists()


# --- carried finding: guard the empty/whitespace-only token at the prompt --
#
# write_env(root, hub, "") writes STRATA_KB_HTTP_TOKEN= and clobbers an
# existing good token; the probe then degrades safely (401 -> "token was
# rejected") but the good value on disk is already gone. The guard belongs
# where the CLI collects the value, before write_env ever runs.


def test_mcp_setup_refuses_a_whitespace_only_token(tmp_path: Path, monkeypatch):
    init_repo(tmp_path, "child")
    monkeypatch.delenv("STRATA_KB_HTTP_TOKEN", raising=False)
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", "   "]
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "STRATA_KB_HTTP_TOKEN" in result.output
    assert not (tmp_path / ".env").exists()


def test_mcp_setup_refuses_a_whitespace_only_token_and_does_not_clobber_env(
    tmp_path: Path, monkeypatch
):
    init_repo(tmp_path, "child")
    _ok_probe(monkeypatch)
    runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    monkeypatch.delenv("STRATA_KB_HTTP_TOKEN", raising=False)
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", "   "]
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert f"STRATA_KB_HTTP_TOKEN={TOKEN}" in (
        tmp_path / ".env"
    ).read_text(encoding="utf-8")


# --- Fix wave 1 -------------------------------------------------------------


def test_mcp_setup_catches_write_env_oserror_without_a_traceback(
    tmp_path: Path, monkeypatch
):
    """Important 1: write_env's OSError (e.g. an unwritable repo dir) must
    exit 1 with a one-line message, not propagate to Typer's exception hook
    -- where, on some typer versions, it would print local variables
    including the token."""
    from strata_kb import mcpsetup

    init_repo(tmp_path, "child")

    def boom(root, hub, token):
        raise OSError("Read-only file system")

    monkeypatch.setattr(mcpsetup, "write_env", boom)
    result = runner.invoke(
        app, ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", TOKEN]
    )
    assert result.exit_code == 1
    _assert_no_propagated_exception(result)
    assert "Read-only file system" in result.output
    assert TOKEN not in result.output


def test_mcp_setup_probes_the_same_value_it_writes_to_env(
    tmp_path: Path, monkeypatch
):
    """Important 2: a trailing space on the pasted token must not make the
    probe see a different value than what write_env stripped onto disk."""
    init_repo(tmp_path, "child")
    seen = _ok_probe(monkeypatch)
    result = runner.invoke(
        app,
        ["mcp-setup", str(tmp_path), "--hub-url", HUB, "--token", f" {TOKEN} "],
    )
    assert result.exit_code == 0, result.output
    assert seen["token"] == TOKEN
    assert f"STRATA_KB_HTTP_TOKEN={TOKEN}" in (
        tmp_path / ".env"
    ).read_text(encoding="utf-8")


def test_mcp_setup_hidden_prompt_never_echoes_the_token(tmp_path: Path, monkeypatch):
    """Minor 3: the recommended path (hidden prompt, no --token) must write
    the typed value without ever echoing it to the terminal."""
    from strata_kb import cli

    init_repo(tmp_path, "dev")
    _ok_probe(monkeypatch)
    monkeypatch.setattr(cli, "_stdin_isatty", lambda: True)
    result = runner.invoke(
        app,
        ["mcp-setup", str(tmp_path), "--hub-url", HUB],
        input=f"{TOKEN}\n",
    )
    assert result.exit_code == 0, result.output
    assert TOKEN not in result.output
    assert f"STRATA_KB_HTTP_TOKEN={TOKEN}" in (
        tmp_path / ".env"
    ).read_text(encoding="utf-8")
