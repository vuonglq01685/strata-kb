from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from center_kb import cipublish, gitio
from center_kb import publish as publish_mod


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def child(tmp_path):
    root = tmp_path / "child"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@t")
    _git(root, "config", "user.name", "t")
    kb = root / ".kb"
    kb.mkdir()
    (kb / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "init")
    bare = tmp_path / "child-origin.git"
    _git(tmp_path, "clone", "--bare", str(root), str(bare))
    _git(root, "remote", "add", "origin", str(bare))
    return root, bare


class TestPublishViaIntake:
    def test_dirty_kb_raises_before_tagging(self, child):
        root, _ = child
        (root / ".kb" / "new.md").write_text("x", encoding="utf-8")
        with pytest.raises(publish_mod.PublishError) as exc:
            publish_mod.publish_via_intake(root / ".kb", "https://kb.test", "child")
        assert "commit" in str(exc.value).lower()
        assert "kb-publish/" not in _git(root, "tag", "--list")

    def test_happy_path_tags_pushes_polls(self, child):
        root, bare = child
        calls = []

        def fake_get(url):
            calls.append(url)
            return 200, {"state": "done", "pr_url": "https://gh/pull/4", "detail": ""}

        pr = publish_mod.publish_via_intake(
            root / ".kb", "https://kb.test", "child-a",
            poll_interval=0, timeout=5, http_get_json=fake_get,
        )
        assert pr == "https://gh/pull/4"
        tags = _git(bare, "tag", "--list")
        assert "kb-publish/" in tags
        assert "repo_id=child-a" in calls[0]
        commit = gitio.head_commit(root)
        assert f"commit={commit}" in calls[0]

    def test_error_state_raises_with_detail(self, child):
        root, _ = child

        def fake_get(url):
            return 200, {"state": "error", "pr_url": "", "detail": "boom"}

        with pytest.raises(publish_mod.PublishError) as exc:
            publish_mod.publish_via_intake(
                root / ".kb", "https://kb.test", "child-a",
                poll_interval=0, timeout=5, http_get_json=fake_get,
            )
        assert "boom" in str(exc.value)

    def test_timeout_raises_actionable(self, child):
        root, _ = child

        def fake_get(url):
            return 404, {"state": "unknown"}

        with pytest.raises(publish_mod.PublishError) as exc:
            publish_mod.publish_via_intake(
                root / ".kb", "https://kb.test", "child-a",
                poll_interval=0, timeout=0.1, http_get_json=fake_get,
            )
        assert "Actions" in str(exc.value)


class FakeHTTP:
    """(method, url) → (status, json-dict). Ghi lại body POST."""

    def __init__(self, table):
        self.table = table
        self.posted = []

    def __call__(self, method, url, headers, body):
        if method == "POST":
            self.posted.append((url, headers, body))
        for prefix, resp in self.table.items():
            if url.startswith(prefix):
                return resp[0], json.dumps(resp[1]).encode()
        raise AssertionError(f"unexpected url {url}")


class TestCIPublish:
    def _env(self, monkeypatch):
        monkeypatch.setenv(
            "ACTIONS_ID_TOKEN_REQUEST_URL", "https://actions.local/token?x=1"
        )
        monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "req-tok")

    def test_nothing_to_publish_when_manifest_matches(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        from center_kb import hashsync

        local = hashsync.build_manifest(root / ".kb")
        http = FakeHTTP({"https://kb.test/intake/manifest": (200, {"files": local})})
        out = cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert out == ""
        assert http.posted == []

    def test_posts_changed_files_and_returns_pr(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        http = FakeHTTP(
            {
                "https://kb.test/intake/manifest": (200, {"files": {}}),
                "https://actions.local/token": (200, {"value": "oidc-jwt"}),
                "https://kb.test/intake/publish": (
                    200, {"repo_id": "child-a", "pr_url": "https://gh/pull/8"},
                ),
            }
        )
        out = cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert out == "https://gh/pull/8"
        url, headers, body = http.posted[0]
        assert headers["Authorization"] == "Bearer oidc-jwt"
        # body multipart chứa index.yaml trong archive
        assert b"index.yaml" in body

    def test_manifest_endpoint_down_falls_back_to_full_upload(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        http = FakeHTTP(
            {
                "https://kb.test/intake/manifest": (503, {"detail": "down"}),
                "https://actions.local/token": (200, {"value": "oidc-jwt"}),
                "https://kb.test/intake/publish": (
                    200, {"repo_id": "child-a", "pr_url": "https://gh/pull/8"},
                ),
            }
        )
        out = cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert out == "https://gh/pull/8"  # vẫn publish, upload full
