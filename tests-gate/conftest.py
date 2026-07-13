"""Fixtures cho tầng T3 (e2e trên artifact đã cài).

QUY TẮC BẤT DI BẤT DỊCH: file này và mọi file dưới tests-gate/e2e/ KHÔNG được
import center_kb. Artifact chỉ được chạm tới qua subprocess.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

# kb publish tạo commit thật. Runner CI không có ~/.gitconfig, nên git sẽ từ
# chối commit nếu không có identity — cùng lý do release.yml đã set các biến
# này cho job test.
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "e2e",
    "GIT_AUTHOR_EMAIL": "e2e@local",
    "GIT_COMMITTER_NAME": "e2e",
    "GIT_COMMITTER_EMAIL": "e2e@local",
}

# Payload hợp lệ cho CẢ prompt section lẫn prompt doc của kb summarize.
# claude được gọi là: claude -p --model <m> --output-format json  (prompt qua
# stdin), và --output-format json bọc trả lời trong {"type":"result","result":…}
# — xem center_kb/llm.py:32 và :59.
_INNER = json.dumps(
    {
        "l2_summary": "Condensed via stub.",
        "l1_summary": "Stub line.",
        "summary": "Stub doc summary.",
    }
)
CLAUDE_ENVELOPE = json.dumps({"type": "result", "result": _INNER})


@dataclass(frozen=True)
class Artifact:
    venv: Path

    @property
    def kb(self) -> Path:
        return self.venv / "bin" / "kb"

    @property
    def python(self) -> Path:
        return self.venv / "bin" / "python"


@pytest.fixture(scope="session")
def artifact() -> Artifact:
    raw = os.environ.get("KB_VENV")
    if not raw:
        # RAISE, không skip. Một job CI xanh vì thu thập được 0 test là kiểu
        # hỏng nguy hiểm nhất của một cửa release — nó cho cảm giác an toàn giả.
        raise RuntimeError(
            "KB_VENV chưa được set. Tầng e2e/regression chạy trên WHEEL ĐÃ CÀI, "
            "không bao giờ trên source tree. Dùng: ./scripts/gate.sh"
        )
    venv = Path(raw)
    if not (venv / "bin" / "kb").exists():
        raise RuntimeError(f"KB_VENV={venv} không có bin/kb — wheel đã cài vào đó chưa?")
    return Artifact(venv=venv)


@pytest.fixture
def kb_run(artifact: Artifact):
    """Gọi binary kb thật bằng subprocess."""

    def _run(
        *args: str,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool = True,
        timeout: int = 180,
    ) -> subprocess.CompletedProcess[str]:
        full_env = {**os.environ, **GIT_IDENTITY, **(env or {})}
        proc = subprocess.run(
            [str(artifact.kb), *args],
            cwd=cwd,
            env=full_env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                f"kb {' '.join(args)} → exit {proc.returncode}\n"
                f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
            )
        return proc

    return _run


@pytest.fixture
def run_git():
    def _git(cwd: Path, *args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env={**os.environ, **GIT_IDENTITY},
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()

    return _git


@pytest.fixture
def stub_claude(tmp_path_factory) -> dict[str, str]:
    """Shell script tên `claude` đặt đầu PATH. center_kb/llm.py dùng
    shutil.which("claude") để dò runner, nên chỉ cần nó nằm trên PATH."""
    bindir = tmp_path_factory.mktemp("stub-bin")
    script = bindir / "claude"
    script.write_text(
        f"#!/bin/sh\ncat > /dev/null\necho '{CLAUDE_ENVELOPE}'\n", encoding="utf-8"
    )
    script.chmod(0o755)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}


@pytest.fixture
def bare_hub(tmp_path: Path, run_git) -> Path:
    """Hub bare git repo. PHẢI bare: `kb publish --direct` push vào main của
    hub, và git từ chối push vào branch đang được checkout của một repo thường."""
    work = tmp_path / "hub-work"
    (work / ".kb").mkdir(parents=True)
    (work / "federation").mkdir()
    (work / ".kb" / "index.yaml").write_text("docs: []\n", encoding="utf-8")
    (work / "federation" / "index.yaml").write_text("docs: []\n", encoding="utf-8")

    run_git(work, "init", "-b", "main")
    run_git(work, "add", "-A")
    run_git(work, "commit", "-m", "hub init")

    bare = tmp_path / "hub.git"
    run_git(tmp_path, "clone", "--bare", str(work), str(bare))
    return bare


@pytest.fixture
def free_port() -> int:
    """Xin một cổng trống thay vì hardcode 8321 — tránh đụng nhau khi chạy song song."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---- KB seed (fixture sinh bởi scripts/gen_e2e_fixture.py — xem Task 3) ----
# Hằng số + fixture đặt ở đây (conftest chung) thay vì trong test_journey.py, để
# fixture `published_repo` (Task 5) dùng được mà không cần import chéo giữa các
# test module.
SEED_FIXTURE = Path(__file__).parent / "fixtures" / "pending-kb"


@pytest.fixture
def seed_kb():
    """Đổ KB ở trạng thái 'ingest vừa xong' vào repo, và trỏ config.yaml vào hub."""

    def _seed(repo: Path, hub: Path) -> Path:
        kb = repo / ".kb"
        for src in SEED_FIXTURE.rglob("*"):
            if src.is_file():
                dest = kb / src.relative_to(SEED_FIXTURE)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        (kb / "config.yaml").write_text(
            f'hub: "{hub}"\nrepo_id: "e2e-repo"\n', encoding="utf-8"
        )
        return kb

    return _seed


@pytest.fixture
def published_repo(
    tmp_path: Path, kb_run, seed_kb, stub_claude, bare_hub: Path, run_git
) -> dict:
    """Một repo đã đi trọn: init → seed → summarize → build → publish lên hub.

    Trả về {"repo", "kb", "hub"}. Đây là trạng thái mà mọi lệnh đọc (query,
    get, context, resolve, doctor) cần — vì từ v0.9 chúng chỉ đọc từ hub.
    Dùng chung ở đây (không phải test_journey.py) vì Task 6
    (tests-gate/e2e/test_server.py) cũng cần trạng thái này.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    kb_run("init", cwd=repo)
    kb = seed_kb(repo, bare_hub)
    kb_run("summarize", "--llm", "claude", "--kb-dir", str(kb),
           cwd=repo, env=stub_claude)
    kb_run("build", "--kb-dir", str(kb), cwd=repo)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "kb v1")
    kb_run("publish", "--direct", "--hub", str(bare_hub), "--repo-id", "e2e-repo",
           "--kb-dir", str(kb), cwd=repo)
    return {"repo": repo, "kb": kb, "hub": bare_hub}


@pytest.fixture
def mcp_stdio_params(artifact: Artifact, published_repo: dict):
    """StdioServerParameters trỏ vào `python -m center_kb.mcp` của venv ARTIFACT
    (không phải venv runner) — không có lệnh `kb serve`, server chạy đúng như
    CMD của Dockerfile. Dùng chung ở đây (không phải test_server.py) để Task
    9/10 tái dùng qua tests-gate/conftest.py mà không cần import chéo giữa
    các test module.

    `mcp` (gói SDK client) là dependency của RUNNER (requirements-gate.txt),
    import nó ở đây KHÔNG vi phạm quy tắc "không import center_kb".
    """
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=str(artifact.python),
        args=[
            "-m", "center_kb.mcp",
            "--kb", str(published_repo["kb"]),
            "--hub", str(published_repo["hub"]),
        ],
        cwd=str(published_repo["repo"]),
        env={**os.environ},
    )


# ---- Regression fixtures (Task 8): .kb/ đúng như nó tồn tại ở một tag cũ ----

LEGACY_TAGS = ["v0.7.0", "v0.8.0", "v0.9.0"]

# tests-gate/conftest.py → lùi 1 cấp là gốc repo.
REPO_ROOT = Path(__file__).parent.parent


def _materialize_kb_at_tag(tag: str, dest_repo: Path, tmp_path: Path) -> Path:
    """Bung .kb/ đúng như nó tồn tại ở một git tag, vào một repo trống.

    Cần `fetch-depth: 0` trên CI để tag tồn tại."""
    archive = tmp_path / f"{tag}.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), tag, ".kb"],
        cwd=REPO_ROOT, check=True, capture_output=True,
    )
    subprocess.run(["tar", "-xf", str(archive)], cwd=dest_repo, check=True)
    kb = dest_repo / ".kb"
    assert (kb / "index.yaml").exists(), f"{tag} không có .kb/index.yaml"
    return kb


@pytest.fixture(params=LEGACY_TAGS, ids=LEGACY_TAGS)
def legacy_kb(request, tmp_path: Path, run_git, bare_hub) -> dict:
    """Materialize .kb/ như nó tồn tại ở một tag cũ, trong một git repo trỏ vào hub.

    Mô phỏng đúng thứ user làm sau khi `pip install -U`: họ có .kb/ cũ trong repo,
    và chạy version MỚI lên nó."""
    tag = request.param
    repo = tmp_path / f"legacy-{tag}"
    repo.mkdir()
    kb = _materialize_kb_at_tag(tag, repo, tmp_path)

    (kb / "config.yaml").write_text(
        f'hub: "{bare_hub}"\nrepo_id: "legacy"\n', encoding="utf-8"
    )
    run_git(repo, "init", "-b", "main")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", f"legacy kb from {tag}")

    return {"tag": tag, "repo": repo, "kb": kb, "hub": bare_hub}
