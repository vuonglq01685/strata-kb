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
    """Hub = local clone có origin bare — giống hub cache của server."""
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
    # branch publish/flight-docs tồn tại trên origin, chứa snapshot + _meta + index tổng
    _git(hub, "checkout", "publish/flight-docs")
    fed = hub / "federation" / "flight-docs"
    assert (fed / "index.yaml").exists()
    assert (fed / "_meta.yaml").exists()
    meta = (fed / "_meta.yaml").read_text(encoding="utf-8")
    assert "acme/flight-docs" in meta  # source_url từ claims, không từ payload
    assert (hub / "federation" / "index.yaml").exists()
    # về lại main sau khi xong
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
    # lần 2 nội dung y hệt → không gọi GitHub API nào, trả ""
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
    # publish 2: xoá doc-a/_manifest.yaml
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


def test_hub_manifest_excludes_meta(hub, monkeypatch):
    monkeypatch.setattr(intake.ghapp, "_app_jwt", lambda creds: "fake-app-jwt")
    monkeypatch.setattr(intake.ghapp, "repo_full_from_url", lambda url: "acme/hub")
    http = FakeHTTP(
        [(200, {"id": 9}), (201, {"token": "t"}), (201, {"html_url": "u/pull/1"})]
    )
    intake.intake_publish(
        _cfg(hub, http), "flight-docs", "aaa", "acme/flight-docs", [], _kb_archive()
    )
    # manifest đọc từ branch main — chưa merge nên rỗng là đúng;
    # đọc từ working tree sau checkout branch thì có file. hub_manifest đọc
    # trạng thái main (đã merge) — mô phỏng bằng merge branch vào main:
    _git(hub, "merge", "publish/flight-docs")
    man = intake.hub_manifest(str(hub), "flight-docs")
    assert "index.yaml" in man
    assert "_meta.yaml" not in man
