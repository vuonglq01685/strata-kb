from __future__ import annotations

import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

from center_kb import ghapp, intake


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


@pytest.fixture
def hub(tmp_path):
    """Hub = local clone with a bare origin — like the server's hub cache."""
    bare = tmp_path / "hub-origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@t")
    _git(seed, "config", "user.name", "t")
    (seed / ".kb").mkdir()
    (seed / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (seed / "federation").mkdir()
    (seed / "federation" / ".gitkeep").write_text("", encoding="utf-8")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "init")
    _git(tmp_path, "clone", "--bare", str(seed), str(bare))
    clone = tmp_path / "hub-clone"
    _git(tmp_path, "clone", str(bare), str(clone))
    _git(clone, "config", "user.email", "srv@t")
    _git(clone, "config", "user.name", "srv")
    return clone


def _kb_archive() -> bytes:
    buf = io.BytesIO()
    files = {
        "index.yaml": b"docs:\n- id: doc-a\n  title: Doc A\n",
        "doc-a/_manifest.yaml": b"id: doc-a\ntitle: Doc A\nsections: []\n",
    }
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


class FakeHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req):
        self.requests.append(req)
        status, body = self.responses.pop(0)
        return status, json.dumps(body).encode()


def _cfg(hub: Path, http) -> intake.IntakeConfig:
    return intake.IntakeConfig(
        hub_ref=str(hub),
        audience="https://kb.test",
        creds=ghapp.AppCreds(app_id="1", private_key_pem="unused-by-fake"),
        http=http,
        push_via_token_url=False,
    )


def test_intake_publish_creates_branch_and_pr(hub, monkeypatch):
    http = FakeHTTP(
        [
            (200, {"id": 9}),
            (201, {"token": "ghs_t"}),
            (201, {"html_url": "https://github.com/acme/hub/pull/7"}),
        ]
    )
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(
        intake.ghapp, "repo_full_from_url", lambda url: "acme/hub"
    )
    cfg = _cfg(hub, http)
    pr = intake.intake_publish(
        cfg, "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    assert pr.endswith("/pull/7")
    # branch publish/flight-docs exists on origin, contains snapshot + _meta + aggregate index
    _git(hub, "checkout", "publish/flight-docs")
    fed = hub / "federation" / "flight-docs"
    assert (fed / "index.yaml").exists()
    assert (fed / "_meta.yaml").exists()
    meta = (fed / "_meta.yaml").read_text(encoding="utf-8")
    assert "acme/flight-docs" in meta  # source_url from claims, not from payload
    assert (hub / "federation" / "index.yaml").exists()
    # back to main when done
    _git(hub, "checkout", "main")


def test_intake_publish_nothing_changed_returns_empty(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http1 = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    intake.intake_publish(
        _cfg(hub, http1), "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    # 2nd run with identical content → no GitHub API calls, returns ""
    http2 = FakeHTTP([])
    pr = intake.intake_publish(
        _cfg(hub, http2), "flight-docs", "abc1234", "acme/flight-docs", [], _kb_archive()
    )
    assert pr == ""
    assert http2.requests == []


def test_intake_publish_applies_deletes(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    responses = [
        (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"}),
        (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"}),
    ]
    http = FakeHTTP(responses)
    cfg = _cfg(hub, http)
    intake.intake_publish(
        cfg, "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    # publish 2: delete doc-a/_manifest.yaml
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"docs: []\n"
        info = tarfile.TarInfo("index.yaml")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    intake.intake_publish(
        cfg, "flight-docs", "bbb", "acme/flight-docs",
        ["doc-a/_manifest.yaml"], buf.getvalue(),
    )
    _git(hub, "checkout", "publish/flight-docs")
    assert not (hub / "federation" / "flight-docs" / "doc-a").exists()
    _git(hub, "checkout", "main")


def test_intake_publish_after_merge_resets_branch_from_main(hub, monkeypatch):
    """After the PR is merged, publishing again: the branch must reset from the new
    main (not reuse the old branch that diverged before the merge)."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http = FakeHTTP(
        [
            (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"}),
            (200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/2"}),
        ]
    )
    cfg = _cfg(hub, http)
    intake.intake_publish(
        cfg, "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    # --no-ff: real merge commit (like GitHub's default merge) — fast-forward would
    # make the merge-base assert meaningless (old branch still an ancestor of main)
    _git(hub, "merge", "--no-ff", "--no-edit", "publish/flight-docs")
    # publish 2 with content changing 1 file
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        content = b"docs:\n- id: doc-a\n  title: Doc A v2\n"
        info = tarfile.TarInfo("index.yaml")
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    pr = intake.intake_publish(
        cfg, "flight-docs", "bbb", "acme/flight-docs", [], buf.getvalue()
    )
    assert pr.endswith("/pull/2")
    # the new branch must sit on the merged main, not the old history
    merge_base = _git(hub, "merge-base", "publish/flight-docs", "main").strip()
    main_sha = _git(hub, "rev-parse", "main").strip()
    assert merge_base == main_sha


def test_intake_publish_after_merge_identical_content_is_noop(hub, monkeypatch):
    """After the PR is merged, republishing identical content: the branch resets from
    a main that already has the content so porcelain is clean → returns "", no GitHub
    API calls."""
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http1 = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    intake.intake_publish(
        _cfg(hub, http1), "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    _git(hub, "merge", "--no-ff", "--no-edit", "publish/flight-docs")
    http2 = FakeHTTP([])
    pr = intake.intake_publish(
        _cfg(hub, http2), "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    assert pr == ""
    assert http2.requests == []


def test_hub_manifest_excludes_meta(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    intake.intake_publish(
        _cfg(hub, http), "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    # the manifest is read from the main branch — not merged yet, so empty is correct;
    # reading the working tree after checking out the branch does show files.
    # hub_manifest reads the state of main (post-merge) — simulated by merging the
    # branch into main (--no-ff like GitHub's default merge):
    _git(hub, "merge", "--no-ff", "--no-edit", "publish/flight-docs")
    man = intake.hub_manifest(str(hub), "flight-docs")
    assert "index.yaml" in man
    assert "_meta.yaml" not in man
