from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from strata_kb import cipublish, gitio
from strata_kb import publish as publish_mod


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_cipublish_default_http_rejects_non_http_scheme():
    """Fix round 1, Important 2: pin the scheme guard so a future refactor
    that drops it goes red instead of silently re-opening the file:// read."""
    status, raw = cipublish._default_http("GET", "file:///etc/passwd", {}, None)
    assert status == 0
    assert b"non-http" in raw


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

    def test_bad_scheme_raises_before_tagging(self, child):
        """Fix round 1, Important 1/2: a bad intake scheme must fail loudly,
        before anything is tagged or pushed -- not silently poll to timeout."""
        root, _ = child
        with pytest.raises(publish_mod.PublishError) as exc:
            publish_mod.publish_via_intake(root / ".kb", "file:///etc/passwd", "child")
        assert "http" in str(exc.value).lower()
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
    """(method, url) -> (status, json-encoded dict or raw bytes). Records POST bodies."""

    def __init__(self, table):
        self.table = table
        self.posted = []
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers))
        if method == "POST":
            self.posted.append((url, headers, body))
        for prefix, resp in self.table.items():
            if url.startswith(prefix):
                if isinstance(resp[1], bytes):
                    return resp[0], resp[1]
                return resp[0], json.dumps(resp[1]).encode()
        raise AssertionError(f"unexpected url {url}")


def _archive_from_multipart(body: bytes) -> bytes:
    """Pull the raw tar.gz bytes out of the multipart POST body."""
    marker = b"Content-Type: application/gzip\r\n\r\n"
    start = body.index(marker) + len(marker)
    end = body.rindex(b"\r\n--kb-")
    return body[start:end]


class TestCIPublish:
    def _env(self, monkeypatch):
        monkeypatch.setenv(
            "ACTIONS_ID_TOKEN_REQUEST_URL", "https://actions.local/token?x=1"
        )
        monkeypatch.setenv("ACTIONS_ID_TOKEN_REQUEST_TOKEN", "req-tok")

    def test_nothing_to_publish_when_manifest_matches(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        from strata_kb import hashsync

        local = hashsync.build_manifest(root / ".kb")
        http = FakeHTTP(
            {
                "https://actions.local/token": (200, {"value": "oidc-jwt"}),
                "https://kb.test/intake/manifest": (200, {"files": local}),
            }
        )
        out = cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert out == ""
        assert http.posted == []

    def test_a_child_with_config_yaml_short_circuits_when_hub_snapshot_matches(
        self, child, monkeypatch
    ):
        """Finding 4: `kb init` always writes .kb/config.yaml, but the hub is
        allowlist-filtered on every path that writes federation/<rid>/ (F-D6)
        so it can never hold a copy of it -- before the fix, local_man was
        built raw (unfiltered) so config.yaml always showed up as "changed"
        against remote_man, the "nothing to publish" fast path below was
        unreachable for every child, and config.yaml (which can hold a hub
        token) was archived and POSTed to the intake server on every run."""
        root, _ = child
        self._env(monkeypatch)
        from strata_kb import hashsync

        (root / ".kb" / "config.yaml").write_text(
            'hub: "https://x-access-token:ghs_SECRET@github.com/org/kb-hub.git"\n',
            encoding="utf-8",
        )
        local = hashsync.build_manifest(root / ".kb")
        local.pop("config.yaml", None)  # the hub can never hold this file
        http = FakeHTTP(
            {
                "https://actions.local/token": (200, {"value": "oidc-jwt"}),
                "https://kb.test/intake/manifest": (200, {"files": local}),
            }
        )
        out = cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert out == ""
        assert http.posted == []

    def test_manifest_request_carries_oidc_token(self, child, monkeypatch):
        """/intake/manifest is OIDC-gated on the hub — the diff GET must authenticate."""
        root, _ = child
        self._env(monkeypatch)
        http = FakeHTTP(
            {
                "https://actions.local/token": (200, {"value": "oidc-jwt"}),
                "https://kb.test/intake/manifest": (200, {"files": {}}),
                "https://kb.test/intake/publish": (
                    200, {"repo_id": "child-a", "pr_url": "https://gh/pull/8"},
                ),
            }
        )
        cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        manifest_calls = [c for c in http.calls if "/intake/manifest" in c[1]]
        assert manifest_calls
        assert manifest_calls[0][2].get("Authorization") == "Bearer oidc-jwt"

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
        # the multipart body's archive part is a gzip tar containing index.yaml
        archive = _archive_from_multipart(body)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
            assert "index.yaml" in tf.getnames()

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
        assert out == "https://gh/pull/8"  # still publishes: full upload

    def test_manifest_connection_down_falls_back_to_full_upload(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        http = FakeHTTP(
            {
                "https://kb.test/intake/manifest": (0, b"connection refused"),
                "https://actions.local/token": (200, {"value": "oidc-jwt"}),
                "https://kb.test/intake/publish": (
                    200, {"repo_id": "child-a", "pr_url": "https://gh/pull/9"},
                ),
            }
        )
        out = cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert out == "https://gh/pull/9"
        assert len(http.posted) == 1

    def test_post_connection_down_raises_clean_error(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        http = FakeHTTP(
            {
                "https://kb.test/intake/manifest": (200, {"files": {}}),
                "https://actions.local/token": (200, {"value": "oidc-jwt"}),
                "https://kb.test/intake/publish": (0, b"connection refused"),
            }
        )
        with pytest.raises(cipublish.CIPublishError) as exc:
            cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert "unreachable" in str(exc.value)
        assert "connection refused" in str(exc.value)

    def test_token_endpoint_down_raises_clean_error(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        http = FakeHTTP(
            {
                "https://kb.test/intake/manifest": (200, {"files": {}}),
                "https://actions.local/token": (0, b"connection refused"),
            }
        )
        with pytest.raises(cipublish.CIPublishError) as exc:
            cipublish.run(root / ".kb", "https://kb.test", "child-a", http=http)
        assert "unreachable" in str(exc.value)
        assert "connection refused" in str(exc.value)

    def _add_unreviewed_doc(self, kb_dir: Path) -> None:
        """One doc with one `summarized` (not `reviewed`) section — the
        unreviewed gate (R18) must see it via publish_mod.unreviewed_gate."""
        doc = kb_dir / "doc-a"
        doc.mkdir(parents=True, exist_ok=True)
        (doc / "ch1.md").write_text("## 1.1 T\n\nBody.\n", encoding="utf-8")
        (doc / "_manifest.yaml").write_text(
            "id: doc-a\ntitle: doc-a\nsections:\n"
            "  - id: '1.1'\n    title: T\n    summary: s\n    status: summarized\n"
            "    file: ch1\n",
            encoding="utf-8",
        )

    def test_run_warns_about_unreviewed_sections_but_still_publishes(
        self, child, monkeypatch, capsys
    ):
        root, _ = child
        self._env(monkeypatch)
        self._add_unreviewed_doc(root / ".kb")
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
        assert http.posted  # the warn does not block the upload
        printed = capsys.readouterr().out
        assert "[warn] 1 section(s) in 1 doc(s) are published without SME review" in printed

    def test_run_require_reviewed_refuses_before_any_upload(self, child, monkeypatch):
        root, _ = child
        self._env(monkeypatch)
        self._add_unreviewed_doc(root / ".kb")
        http = FakeHTTP({})  # any HTTP call at all is a bug for this path
        with pytest.raises(cipublish.CIPublishError) as exc:
            cipublish.run(
                root / ".kb", "https://kb.test", "child-a",
                require_reviewed=True, http=http,
            )
        assert "without SME review" in str(exc.value)
        assert http.calls == []
