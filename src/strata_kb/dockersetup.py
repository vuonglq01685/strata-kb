from __future__ import annotations

import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path

from strata_kb.config import load_config
from strata_kb.errors import KbError

TOKEN_VAR = "STRATA_KB_HTTP_TOKEN"  # noqa: S105 -- this is the env var's name, not a credential value
_DEFAULT_ENV = f"{TOKEN_VAR}=change-me\n"


def set_env_line(text: str, var: str, value: str) -> str:
    """Return `text` with `var=value` set — replacing the first existing
    assignment, appending when there is none. Every other line survives, so
    a `.env` that already carries docker-compose variables keeps them.

    The replacement is passed as a function so a backslash in `value` is
    literal, not a regex escape.
    """
    line = f"{var}={value}"
    pattern = re.compile(rf"^{re.escape(var)}=.*$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(lambda _match: line, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + line + "\n"


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
    content = set_env_line(base, TOKEN_VAR, secrets.token_hex(24))
    env_path.write_text(content, encoding="utf-8", newline="\n")
    return SetupReport(
        env_created=env_created, gitignore_updated=ensure_gitignored(repo_root)
    )


def repo_kind(repo_root: Path) -> str:
    """Return the recorded repo kind ('hub' | 'child' | 'ba' | 'dev').

    Raises only when the kind is missing or unrecognised. It used to raise
    for `ba`/`dev` too, reporting "not recorded" about a kind that *is*
    recorded — each caller asserts the kinds it supports instead.
    """
    kind = load_config(repo_root / ".kb").kind
    if kind not in ("hub", "child", "ba", "dev"):
        raise DockerSetupError(
            "repo kind is not recorded — run `kb init` first "
            "(it records kind: hub|child|ba|dev in .kb/config.yaml)"
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
    kind = repo_kind(repo_root)
    if kind != "hub":
        raise DockerSetupError(
            f"this repo is kind: {kind} — kb docker-setup's .env/token step "
            "prepares the MAIN hub (the repo that hosts federation/ and the "
            "shared MCP/Web service)"
        )


def ensure_gitignored(repo_root: Path) -> bool:
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
