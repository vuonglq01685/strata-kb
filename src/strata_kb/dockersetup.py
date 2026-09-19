from __future__ import annotations

import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path

from center_kb.config import load_config
from center_kb.errors import KbError

TOKEN_VAR = "CENTER_KB_HTTP_TOKEN"  # noqa: S105 -- this is the env var's name, not a credential value
_TOKEN_LINE = re.compile(rf"^{TOKEN_VAR}=.*$", re.MULTILINE)
_DEFAULT_ENV = f"{TOKEN_VAR}=change-me\n"


class DockerSetupError(KbError):
    """Setup cannot proceed (wrong repo kind, missing prerequisites). Every
    CLI call site already converts it to a one-line message -- joins the
    KbError family (Wave G fix round 2, item 7); EnvExistsError below
    inherits the membership."""


class EnvExistsError(DockerSetupError):
    """.env already exists — the caller must opt into regenerating the token."""


@dataclass
class SetupReport:
    env_created: bool
    gitignore_updated: bool


def run_setup(repo_root: Path, regenerate: bool = False) -> SetupReport:
    """Prepare the hub for Docker HTTP serving: .env + a fresh random token.

    The token is written to .env only — callers must not echo it.
    """
    _require_hub_kind(repo_root)
    env_path = repo_root / ".env"
    env_created = not env_path.exists()
    if not env_created and not regenerate:
        raise EnvExistsError(
            "found existing .env — re-run with --force to regenerate the token"
        )
    if env_created:
        example = repo_root / ".env.example"
        base = (
            example.read_text(encoding="utf-8") if example.exists() else _DEFAULT_ENV
        )
    else:
        base = env_path.read_text(encoding="utf-8")
    line = f"{TOKEN_VAR}={secrets.token_hex(24)}"
    if _TOKEN_LINE.search(base):
        content = _TOKEN_LINE.sub(lambda _match: line, base, count=1)
    else:
        if base and not base.endswith("\n"):
            base += "\n"
        content = base + line + "\n"
    env_path.write_text(content, encoding="utf-8", newline="\n")
    return SetupReport(
        env_created=env_created, gitignore_updated=_ensure_gitignored(repo_root)
    )


def repo_kind(repo_root: Path) -> str:
    """Return the recorded repo kind ('hub' | 'child'); raise when unset."""
    kind = load_config(repo_root / ".kb").kind
    if kind not in ("hub", "child"):
        raise DockerSetupError(
            "repo kind is not recorded — run `kb init` first "
            "(it records kind: hub|child in .kb/config.yaml)"
        )
    return kind


def docker_ready() -> bool:
    """True when the Docker CLI exists and the daemon answers `docker info`."""
    try:
        return (
            subprocess.run(["docker", "info"], capture_output=True, timeout=30)
            .returncode
            == 0
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def compose_up(repo_root: Path) -> int:
    """`docker compose up -d` in the repo root; output streams to the console."""
    return subprocess.run(["docker", "compose", "up", "-d"], cwd=repo_root).returncode


def compose_pull(repo_root: Path) -> int:
    """`docker compose pull` in the repo root; output streams to the console."""
    return subprocess.run(["docker", "compose", "pull"], cwd=repo_root).returncode


def _require_hub_kind(repo_root: Path) -> None:
    if repo_kind(repo_root) == "child":
        raise DockerSetupError(
            "this repo is a child — kb docker-setup prepares the MAIN hub "
            "(the repo that hosts federation/ and the shared MCP/Web service)"
        )


def _ensure_gitignored(repo_root: Path) -> bool:
    """Make sure .env never lands in git; returns True when .gitignore changed."""
    gitignore = repo_root / ".gitignore"
    lines = (
        gitignore.read_text(encoding="utf-8").splitlines()
        if gitignore.exists()
        else []
    )
    if any(line.strip() in (".env", "/.env") for line in lines):
        return False
    lines.append(".env")
    gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return True
