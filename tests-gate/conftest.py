"""Fixtures for tier T3 (e2e against the installed artifact).

INVIOLABLE RULE: this file and every file under tests-gate/e2e/ MUST NOT import
strata_kb. The artifact is only ever touched through subprocess.
"""

from __future__ import annotations

import os

# See tests/conftest.py's identical line: Typer force-enables colored/wrapped
# Rich error rendering under GITHUB_ACTIONS, which can split a CLI flag name
# like "--assistant" across a reset code, breaking plain substring checks on
# `kb`'s stdout/stderr in only CI. kb_run() below builds each subprocess's
# env from a fresh read of os.environ, so setting this here — before any
# `kb` subprocess is ever spawned — is sufficient; no import-order subtlety,
# since this env var only affects the separate `kb` process, not this one.
os.environ.setdefault("_TYPER_FORCE_DISABLE_TERMINAL", "1")

import json
import shutil
import socket
import subprocess
import sys
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
# — see strata_kb/llm.py:32 and :59.
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


# Doctor deliberately warns when a hub entry holds a file `kb publish` would
# never write (F-D6, 5bb6ea8: publish stopped mirroring .kb/config.yaml to
# federation/, a file that carries the hub URL and, on real deployments,
# credentials). A hub PUBLISHED BY AN OLDER strata-kb still has that mirrored
# config.yaml sitting on it, and the new binary is supposed to say so -- this
# is a security nudge, not a defect, so unlike KIND_WARNING its ABSENCE must
# also fail the gate: a test that merely tolerated it would stay green even
# if the sweep silently stopped firing. The warning fires on a hub an OLD
# version wrote (exactly what tests-gate/golden/federation-v0.9.0 is); it does
# not fire on an old .kb a NEW version publishes, since publish itself no
# longer mirrors the file -- test_kb_backcompat's bare_hub is built fresh by
# the new binary and must never see this warning, so it must not use this
# fixture. Pinned on "config.yaml" AND the sentence together (round 2, review-
# waveK-verdict.md MEDIUM-1): the sentence tail alone ("an older version
# mirrored them; ...") does not name which stray triggered it, so a doctor
# that stopped calling out config.yaml specifically -- e.g. a broadened
# is_kb_artifact() that also swallows config.yaml as a legitimate stray, or
# config.yaml quietly re-admitted to publish's own allowlist, undoing F-D6 at
# the source -- could still satisfy a tail-only match while the real
# credential nudge is gone. Not the substring "config.yaml" alone either
# (KIND_WARNING's own message contains that substring too). The gate
# tolerates this one warning, on this one fixture, and no other.
LEGACY_CONFIG_MIRROR_WARNING = (
    "holds file(s) a publish would never write: config.yaml -- an older "
    "version mirrored them; delete them on the hub, and rotate any "
    "credential they contain"
)


@pytest.fixture
def strip_legacy_config_mirror_warning():
    """Assert the legacy config.yaml mirror warning fired, then remove it so
    the strict 'not a single [warning]' assertions keep guarding everything
    else. Only for fixtures whose hub was genuinely published by an older
    strata-kb that still mirrored config.yaml -- its presence is asserted,
    not merely tolerated."""

    def _strip(stdout: str) -> str:
        assert LEGACY_CONFIG_MIRROR_WARNING in stdout, (
            "expected doctor to warn that this hub holds a config.yaml an "
            "older version mirrored, but it did not -- either the sweep in "
            "doctor.py stopped firing, the fixture no longer holds a "
            "legacy-mirrored config.yaml, or the sweep now names files "
            "beyond config.yaml without naming config.yaml itself\n"
            f"--- stdout ---\n{stdout}"
        )
        return "\n".join(
            line
            for line in stdout.splitlines()
            if LEGACY_CONFIG_MIRROR_WARNING not in line
        )

    return _strip


# A federation snapshot published before content_sha256 existed (0.25, doctor.py's
# check_published_digests) has no stored digest to verify against -- doctor warns
# rather than treating an empty digest as tampering. Every golden fixture in this
# suite predates 0.25 by construction, so this warning is expected on all of them
# and, like LEGACY_CONFIG_MIRROR_WARNING, its ABSENCE should also fail the gate:
# a test that merely tolerated it would stay green even if check_published_digests
# stopped firing on unverifiable snapshots entirely.
CONTENT_DIGEST_NOT_VERIFIED_WARNING = "content digest not verified"


@pytest.fixture
def strip_content_digest_not_verified_warning():
    """Assert the "published before 0.25, content digest not verified" warning
    fired for the given repo_id, then remove it so the strict 'not a single
    [warning]' assertions keep guarding everything else."""

    def _strip(stdout: str, repo_id: str) -> str:
        expected = f"federation/{repo_id} was published before 0.25 — content"
        assert expected in stdout, (
            "expected doctor to warn that this old snapshot's content digest "
            "is not verified, but it did not -- either check_published_digests "
            "stopped firing on a snapshot with no stored content_sha256, or "
            "this fixture unexpectedly already carries one\n"
            f"--- stdout ---\n{stdout}"
        )
        return "\n".join(
            line
            for line in stdout.splitlines()
            if CONTENT_DIGEST_NOT_VERIFIED_WARNING not in line
        )

    return _strip


def venv_bin(venv: Path, name: str) -> Path:
    """Path of an installed executable inside a venv, on any OS."""
    if os.name == "nt":
        exe = venv / "Scripts" / f"{name}.exe"
        return exe if exe.exists() else venv / "Scripts" / name
    return venv / "bin" / name


@dataclass(frozen=True)
class Artifact:
    venv: Path

    @property
    def kb(self) -> Path:
        return venv_bin(self.venv, "kb")

    @property
    def python(self) -> Path:
        return venv_bin(self.venv, "python")


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
    art = Artifact(venv=Path(raw).resolve())
    if not art.kb.exists():
        raise RuntimeError(
            f"KB_VENV={art.venv} has no kb executable ({art.kb}) — "
            "was the wheel installed into it?"
        )
    return art


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
            encoding="utf-8",
            errors="replace",
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
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return proc.stdout.strip()

    return _git


@pytest.fixture
def stub_claude(tmp_path_factory) -> dict[str, str]:
    """A fake `claude` on PATH, runnable on POSIX and Windows. strata_kb/llm.py
    probes with shutil.which("claude") — .cmd resolves via PATHEXT on Windows.
    (Deliberately duplicated from tests/cli_stub.py: tests-gate must stay
    self-contained.)"""
    bindir = tmp_path_factory.mktemp("stub-bin")
    impl = bindir / "claude_impl.py"
    impl.write_text(
        f"import sys\nsys.stdin.read()\nsys.stdout.write({CLAUDE_ENVELOPE!r} + '\\n')\n",
        encoding="utf-8", newline="\n",
    )
    if os.name == "nt":
        (bindir / "claude.cmd").write_text(
            f'@"{sys.executable}" "{impl}" %*\n', encoding="utf-8"
        )
    else:
        script = bindir / "claude"
        script.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n',
            encoding="utf-8", newline="\n",
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
        # .as_posix(): embedding a raw WindowsPath (backslashes) inside a
        # double-quoted YAML scalar makes the YAML scanner treat "\A", "\U" etc
        # as escape sequences and crash when config.yaml is parsed later.
        (kb / "config.yaml").write_text(
            f'hub: "{hub.as_posix()}"\nrepo_id: "e2e-repo"\nkind: "child"\n',
            encoding="utf-8",
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
    """Build StdioServerParameters for `python -m strata_kb.mcp` in the
    ARTIFACT venv (never the runner venv) — there is no `kb serve` command,
    this is exactly the CMD the Dockerfile runs. Factored out so
    mcp_stdio_params (Task 6, bound to published_repo) and
    published_kb_mcp_params (Task 9, bound to published_kb) share one
    invocation shape instead of drifting apart.

    `mcp` (client SDK) is a RUNNER dependency (requirements-gate.txt) —
    importing it here does not violate "no importing strata_kb".
    """
    from mcp import StdioServerParameters

    return StdioServerParameters(
        command=str(artifact.python),
        args=["-m", "strata_kb.mcp", "--kb", str(kb), "--hub", str(hub)],
        cwd=str(repo),
        env={**os.environ},
    )


@pytest.fixture
def mcp_stdio_params(artifact: Artifact, published_repo: dict):
    """StdioServerParameters pointing at `python -m strata_kb.mcp` in the
    ARTIFACT venv (not the runner venv) — there is no `kb serve` command, the
    server runs exactly as the Dockerfile's CMD does. Shared here (not in
    test_server.py) so that Task 9/10 can reuse it via tests-gate/conftest.py
    without cross-importing between test modules.
    """
    return _mcp_stdio_params(
        artifact, published_repo["kb"], published_repo["hub"], published_repo["repo"]
    )


# Frozen synthetic .kb — same layout an old child repo would have committed.
# Not taken from git tags: those tags used to carry copyrighted ARINC/ICAO
# extracts. Schema is the pre-kind, summarized two-doc store.
LEGACY_KB = Path(__file__).parent / "golden" / "kb-legacy"


def _copy_legacy_kb(dest_repo: Path) -> Path:
    kb = dest_repo / ".kb"
    shutil.copytree(LEGACY_KB, kb)
    assert (kb / "index.yaml").exists(), f"{LEGACY_KB} has no index.yaml"
    return kb


@pytest.fixture
def legacy_kb(tmp_path: Path, run_git, bare_hub) -> dict:
    """A pre-kind .kb inside a git repo pointed at the hub.

    Reproduces what a user does after `pip install -U`: they have an old
    .kb/ in their repo, and run the NEW version against it."""
    repo = tmp_path / "legacy-kb"
    repo.mkdir()
    kb = _copy_legacy_kb(repo)

    (kb / "config.yaml").write_text(
        f'hub: "{bare_hub.as_posix()}"\nrepo_id: "legacy"\n', encoding="utf-8"
    )
    run_git(repo, "init", "-b", "main")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "legacy kb")

    return {"tag": "legacy-format", "repo": repo, "kb": kb, "hub": bare_hub}


# ---- Golden baseline: one fixed, already-published synthetic store ----


@pytest.fixture
def published_kb(tmp_path: Path, run_git, kb_run, bare_hub) -> dict:
    """The frozen synthetic KB published to the hub — baseline for every golden."""
    repo = tmp_path / "golden-repo"
    repo.mkdir()
    kb = _copy_legacy_kb(repo)

    (kb / "config.yaml").write_text(
        f'hub: "{bare_hub.as_posix()}"\nrepo_id: "golden"\n', encoding="utf-8"
    )
    run_git(repo, "init", "-b", "main")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-m", "golden kb")
    kb_run("publish", "--direct", "--hub", str(bare_hub), "--repo-id", "golden",
           "--kb-dir", str(kb), cwd=repo)
    return {"repo": repo, "kb": kb, "hub": bare_hub}


@pytest.fixture
def published_kb_mcp_params(artifact: Artifact, published_kb: dict):
    """StdioServerParameters bound to published_kb instead of published_repo —
    same shape as mcp_stdio_params, built via the shared _mcp_stdio_params
    helper so the two fixtures can't silently drift apart."""
    return _mcp_stdio_params(
        artifact, published_kb["kb"], published_kb["hub"], published_kb["repo"]
    )
