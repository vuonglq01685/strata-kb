"""Credentials embedded in hub URLs (x-access-token:...@) must never reach
logs, exceptions, or CLI output — CI templates pass token-bearing URLs and
Actions logs are readable by every collaborator."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from center_kb import gitio
from center_kb.hub import resolve_hub

SECRET = "sekret123"
# localhost:1 — connection refused instantly, no network dependency
CRED_URL = f"https://x-access-token:{SECRET}@localhost:1/hub.git"


def _git(cwd: Path, *args: str) -> None:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("x", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    return root


def test_redact_url_strips_x_access_token():
    assert SECRET not in gitio.redact_url(CRED_URL)
    assert "<redacted>" in gitio.redact_url(CRED_URL)


def test_redact_url_strips_user_pass():
    assert "hunter2" not in gitio.redact_url("https://bob:hunter2@example.com/x.git")


def test_redact_url_leaves_clean_url_unchanged():
    clean = "https://github.com/org/hub.git"
    assert gitio.redact_url(clean) == clean


def test_redact_url_handles_url_inside_text():
    text = f"fatal: unable to access '{CRED_URL}': refused"
    assert SECRET not in gitio.redact_url(text)


def test_clone_error_scrubs_credential(tmp_path):
    with pytest.raises(gitio.GitError) as exc:
        gitio.clone(CRED_URL, tmp_path / "dest")
    assert SECRET not in str(exc.value)


def test_pull_error_scrubs_credential(repo):
    _git(repo, "remote", "add", "origin", CRED_URL)
    with pytest.raises(gitio.GitError) as exc:
        gitio.pull(repo)
    assert SECRET not in str(exc.value)


def test_resolve_hub_clone_warning_scrubs_credential(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("CENTER_KB_HUB_CACHE", str(tmp_path / "cache"))
    with caplog.at_level(logging.WARNING, logger="center_kb.hub"):
        handle = resolve_hub(CRED_URL)
    assert handle is None
    assert SECRET not in caplog.text


def test_publish_error_scrubs_credential(repo, monkeypatch):
    from center_kb import publish as publish_mod

    kb_dir = repo / ".kb"
    kb_dir.mkdir()
    monkeypatch.setattr(publish_mod.hub_mod, "resolve_hub", lambda ref: None)
    with pytest.raises(publish_mod.PublishError) as exc:
        publish_mod.publish(kb_dir, CRED_URL)
    assert SECRET not in str(exc.value)
