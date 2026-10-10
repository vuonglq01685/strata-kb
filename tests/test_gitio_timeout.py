"""2026-10-10 review §5.2 #9: intake's network git calls run under
repo_lock(rid) + the hub write lock, so each one needs a timeout and no
prompt. CLI callers pass no timeout and keep git's interactive prompt."""
from __future__ import annotations

import subprocess

import pytest

from strata_kb import gitio


@pytest.fixture
def hung(monkeypatch):
    seen: dict = {}

    def fake(root, env_extra, *args, timeout=None):
        seen.update(env=env_extra, timeout=timeout, args=args)
        if timeout is not None:
            raise subprocess.TimeoutExpired(["git", *args], timeout)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(gitio, "_run_env", fake)
    monkeypatch.setattr(gitio, "remote_url", lambda root: "https://example.test/hub.git")
    return seen


@pytest.mark.parametrize(
    ("call", "what"),
    [
        (lambda: gitio.push_branch(None, "publish/x", "tok", timeout=7), "push branch"),
        (
            lambda: gitio.push_branch_with_token(
                None, "https://example.test/hub.git", "tok", "publish/x", timeout=7
            ),
            "push branch",
        ),
        (lambda: gitio.pull(None, token="tok", timeout=7), "pull"),
    ],
)
def test_a_timed_network_call_never_prompts_and_times_out_as_git_error(hung, call, what):
    with pytest.raises(gitio.GitError, match=f"{what}.*timed out after 7s"):
        call()
    assert hung["timeout"] == 7
    assert hung["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert hung["env"]["GCM_INTERACTIVE"] == "never"


def test_without_a_timeout_the_cli_keeps_gits_prompt(hung):
    gitio.push_branch(None, "publish/x", "tok")
    assert hung["timeout"] is None
    assert "GIT_TERMINAL_PROMPT" not in hung["env"]
