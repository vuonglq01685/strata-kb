"""Fixtures for tier T3 (e2e against the installed artifact).

INVIOLABLE RULE: this file and every file under tests-gate/e2e/ MUST NOT import
center_kb. The artifact is only ever touched through subprocess.
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

# kb publish creates a real commit. The CI runner has no ~/.gitconfig, so git
# refuses to commit without an identity — the same reason release.yml already
# sets these variables for the test job.
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "e2e",
    "GIT_AUTHOR_EMAIL": "e2e@local",
    "GIT_COMMITTER_NAME": "e2e",
    "GIT_COMMITTER_EMAIL": "e2e@local",
}

# A payload valid for BOTH the section prompt and the doc prompt of kb summarize.
# claude is invoked as: claude -p --model <m> --output-format json  (prompt via
# stdin), and --output-format json wraps the reply in {"type":"result","result":…}
# — see center_kb/llm.py:32 and :59.
_INNER = json.dumps(
    {
        "l2_summary": "Condensed via stub.",
        "l1_summary": "Stub line.",
        "summary": "Stub doc summary.",
    }
)
CLAUDE_ENVELOPE = json.dumps({"type": "result", "result": _INNER})

# Doctor deliberately warns when `kind:` is absent from .kb/config.yaml
# (role-aware init, spec 2026-07-13) — every pre-role .kb upgrades into
# exactly that state, so legacy fixtures MUST see this warning. The gate
# tolerates this one warning and no other.
KIND_WARNING = "repo kind is not recorded"


@pytest.fixture
def strip_kind_warning():
    """Remove the expected kind warning from doctor output so the strict
    'not a single [warning]' assertions keep guarding everything else."""

    def _strip(stdout: str) -> str:
        return "\n".join(
            line for line in stdout.splitlines() if KIND_WARNING not in line
        )

    return _strip


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
        # RAISE, do not skip. A green CI job that collected 0 tests is the most
        # dangerous failure mode a release gate has — it gives a false sense of
        # safety.
        raise RuntimeError(
            "KB_VENV is not set. The e2e/regression tiers run against the "
            "INSTALLED WHEEL, never against the source tree. Use: ./scripts/gate.sh"
        )
    venv = Path(raw)
    if not (venv / "bin" / "kb").exists():
        raise RuntimeError(
            f"KB_VENV={venv} has no bin/kb — was the wheel installed into it?"
        )
    return Artifact(venv=venv)


@pytest.fixture
def kb_run(artifact: Artifact):
    """Invoke the real kb binary through subprocess."""

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
    """A shell script named `claude` put at the front of PATH. center_kb/llm.py
    uses shutil.which("claude") to probe for the runner, so it only has to be on
    PATH."""
    bindir = tmp_path_factory.mktemp("stub-bin")
    script = bindir / "claude"
    script.write_text(
        f"#!/bin/sh\ncat > /dev/null\necho '{CLAUDE_ENVELOPE}'\n", encoding="utf-8"
    )
    script.chmod(0o755)
    return {"PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}"}


@pytest.fixture
def bare_hub(tmp_path: Path, run_git) -> Path:
    """A bare git repo hub. MUST be bare: `kb publish --direct` pushes into the
    hub's main, and git refuses to push into the currently checked-out branch of
    an ordinary repo."""
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
    """Ask for a free port instead of hardcoding 8321 — avoids collisions when
    running in parallel."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ---- KB seed (fixture generated by scripts/gen_e2e_fixture.py — see Task 3) ----
# The constant + fixture live here (the shared conftest) instead of in
# test_journey.py, so that the `published_repo` fixture (Task 5) can use them
# without cross-importing between test modules.
SEED_FIXTURE = Path(__file__).parent / "fixtures" / "pending-kb"


@pytest.fixture
def seed_kb():
    """Drop a KB in the 'just finished ingest' state into the repo, and point
    config.yaml at the hub."""

    def _seed(repo: Path, hub: Path) -> Path:
        kb = repo / ".kb"
        for src in SEED_FIXTURE.rglob("*"):
            if src.is_file():
                dest = kb / src.relative_to(SEED_FIXTURE)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
        # kind: child — seeded repos model an authoring repo that publishes
        # to the hub; without it doctor warns "repo kind is not recorded".
        (kb / "config.yaml").write_text(
            f'hub: "{hub}"\nrepo_id: "e2e-repo"\nkind: "child"\n', encoding="utf-8"
        )
        return kb

    return _seed


@pytest.fixture
def published_repo(
    tmp_path: Path, kb_run, seed_kb, stub_claude, bare_hub: Path, run_git
) -> dict:
    """A repo that has gone all the way: init → seed → summarize → build →
    publish to the hub.

    Returns {"repo", "kb", "hub"}. This is the state that every read command
    (query, get, context, resolve, doctor) needs — because since v0.9 they only
    read from the hub. Shared here (not in test_journey.py) because Task 6
    (tests-gate/e2e/test_server.py) needs this state too.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    run_git(repo, "init", "-b", "main")
    kb_run("init", "--kind", "child", cwd=repo)
    kb = seed_kb(repo, bare_hub)
    kb_run("summarize", "--llm", "claude", "--kb-dir", str(kb),
           cwd=repo, env=stub_claude)
    kb_run("build", "--kb-dir", str(kb), cwd=repo)
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "kb v1")
    kb_run("publish", "--direct", "--hub", str(bare_hub), "--repo-id", "e2e-repo",
           "--kb-dir", str(kb), cwd=repo)
    return {"repo": repo, "kb": kb, "hub": bare_hub}


def _mcp_stdio_params(artifact: Artifact, kb: Path, hub: Path, repo: Path):
    """Build StdioServerParameters for `python -m center_kb.mcp` in the
    ARTIFACT venv (never the runner venv) — there is no `kb serve` command,
    this is exactly the CMD the Dockerfile runs. Factored out so
    mcp_stdio_params (Task 6, bound to published_repo) and
    published_kb_mcp_params (Task 9, bound to published_kb) share one
    invocation shape instead of drifting apart.

    `mcp` (client SDK) is a RUNNER dependency (requirements-gate.txt) —
    importing it here does not violate "no importing center_kb".
    """
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=str(artifact.python),
        args=["-m", "center_kb.mcp", "--kb", str(kb), "--hub", str(hub)],
        cwd=str(repo),
        env={**os.environ},
    )


@pytest.fixture
def mcp_stdio_params(artifact: Artifact, published_repo: dict):
    """StdioServerParameters pointing at `python -m center_kb.mcp` in the
    ARTIFACT venv (not the runner venv) — there is no `kb serve` command, the
    server runs exactly as the Dockerfile's CMD does. Shared here (not in
    test_server.py) so that Task 9/10 can reuse it via tests-gate/conftest.py
    without cross-importing between test modules.
    """
    return _mcp_stdio_params(
        artifact, published_repo["kb"], published_repo["hub"], published_repo["repo"]
    )


# ---- Regression fixtures (Task 8): .kb/ exactly as it existed at an old tag ----

LEGACY_TAGS = ["v0.7.0", "v0.8.0", "v0.9.0"]

# tests-gate/conftest.py → one level up is the repo root.
REPO_ROOT = Path(__file__).parent.parent


def _materialize_kb_at_tag(tag: str, dest_repo: Path, tmp_path: Path) -> Path:
    """Unpack .kb/ exactly as it existed at a git tag, into an empty repo.

    Requires `fetch-depth: 0` on CI for the tag to exist."""
    archive = tmp_path / f"{tag}.tar"
    subprocess.run(
        ["git", "archive", "--format=tar", "-o", str(archive), tag, ".kb"],
        cwd=REPO_ROOT, check=True, capture_output=True,
    )
    subprocess.run(["tar", "-xf", str(archive)], cwd=dest_repo, check=True)
    kb = dest_repo / ".kb"
    assert (kb / "index.yaml").exists(), f"{tag} has no .kb/index.yaml"
    return kb


@pytest.fixture(params=LEGACY_TAGS, ids=LEGACY_TAGS)
def legacy_kb(request, tmp_path: Path, run_git, bare_hub) -> dict:
    """Materialize .kb/ as it existed at an old tag, inside a git repo pointed at
    the hub.

    Reproduces exactly what a user does after `pip install -U`: they have an old
    .kb/ in their repo, and run the NEW version against it."""
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


# ---- Golden baseline (Task 9): one fixed, already-published v0.9.0 baseline ----


@pytest.fixture
def published_kb(tmp_path: Path, run_git, kb_run, bare_hub) -> dict:
    """A v0.9.0 KB (taken from git history) published to the hub — the frozen
    baseline for every golden. Does not use legacy_kb because that one is
    parametrized over 3 tags; goldens need exactly ONE fixed baseline."""
    repo = tmp_path / "golden-repo"
    repo.mkdir()
    kb = _materialize_kb_at_tag("v0.9.0", repo, tmp_path)  # Task 8

    (kb / "config.yaml").write_text(
        f'hub: "{bare_hub}"\nrepo_id: "golden"\n', encoding="utf-8"
    )
    run_git(repo, "init", "-b", "main")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "golden kb")
    kb_run("publish", "--direct", "--hub", str(bare_hub), "--repo-id", "golden",
           "--kb-dir", str(kb), cwd=repo)
    return {"repo": repo, "kb": kb, "hub": bare_hub}


@pytest.fixture
def published_kb_mcp_params(artifact: Artifact, published_kb: dict):
    """StdioServerParameters bound to published_kb (Task 9's frozen v0.9.0
    baseline) instead of published_repo — same shape as mcp_stdio_params
    (Task 6), built via the shared _mcp_stdio_params helper so the two
    fixtures can't silently drift apart."""
    return _mcp_stdio_params(
        artifact, published_kb["kb"], published_kb["hub"], published_kb["repo"]
    )
