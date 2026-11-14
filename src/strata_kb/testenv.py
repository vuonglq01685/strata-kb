"""testenv — load and validate `.kb/test-env.yaml` (env var NAMES only, never values)."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import typer
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from strata_kb.errors import KbError

ENV_FILE = ".kb/test-env.yaml"

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_USERINFO = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^/\s:@]+:[^/\s@]*@")
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{32,}")


class TestEnvError(KbError):
    __test__ = False


def secret_like(value: str) -> bool:
    """True if `value` holds URL userinfo (`user:pass@`) or a 32+ char token run."""
    return bool(_USERINFO.search(value) or _TOKEN.search(value))


def _env_name(v: str) -> str:
    if not _ENV_NAME.match(v):
        raise ValueError("must be an UPPER_SNAKE env var name")
    return v


def _script(v: str) -> str:
    p = PurePosixPath(v)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("must be a relative path inside the repo")
    return v


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionCheck(_Model):
    url: str
    field: str


class App(_Model):
    repo: str
    url: str = ""
    api_base: str = ""
    version_check: VersionCheck | None = None


class Db(_Model):
    url_env: str
    check: str
    reset: str
    seeds: dict[str, str] = {}

    _v_env = field_validator("url_env")(_env_name)
    _v_scripts = field_validator("check", "reset")(_script)

    @field_validator("seeds")
    @classmethod
    def _v_seeds(cls, v: dict[str, str]) -> dict[str, str]:
        for p in v.values():
            _script(p)
        return v


class Account(_Model):
    user_env: str
    password_env: str

    _v_env = field_validator("user_env", "password_env")(_env_name)


class TestEnv(_Model):
    __test__ = False

    name: str
    apps: list[App]
    db: Db
    accounts: dict[str, Account]
    api_auth: Literal["cookie", "bearer"] = "cookie"
    retries: int = 3
    protected_urls: list[str] = []


def _first_secret(node: Any, path: str = "") -> str | None:
    if isinstance(node, str):
        return path if secret_like(node) else None
    items: list[tuple[str, Any]] = []
    if isinstance(node, dict):
        items = [(f"{path}.{k}" if path else str(k), v) for k, v in node.items()]
    elif isinstance(node, list):
        items = [(f"{path}[{i}]", v) for i, v in enumerate(node)]
    for sub, v in items:
        if hit := _first_secret(v, sub):
            return hit
    return None


def _loc(loc: tuple) -> str:
    out = ""
    for part in loc:
        out += f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
    return out


def load(repo_root: Path) -> TestEnv:
    path = repo_root / ENV_FILE
    if not path.is_file():
        raise TestEnvError(f"{ENV_FILE} not found — run /tester-env-setup to create it")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as exc:
        raise TestEnvError(f"{ENV_FILE} is unreadable: {type(exc).__name__}") from None
    if not isinstance(raw, dict):
        raise TestEnvError(f"{ENV_FILE} must be a mapping")
    if hit := _first_secret(raw):
        raise TestEnvError(
            f"{ENV_FILE}: {hit} looks like a credential — keep env var names here, values in .env"
        )
    try:
        env = TestEnv.model_validate(raw)
    except ValidationError as exc:
        e = exc.errors()[0]
        raise TestEnvError(f"{ENV_FILE}: {_loc(e['loc'])}: {e['msg']}") from None
    root = repo_root.resolve()
    scripts = {"db.check": env.db.check, "db.reset": env.db.reset} | {
        f"db.seeds.{k}": v for k, v in env.db.seeds.items()
    }
    for where, rel in scripts.items():
        if not (root / rel).resolve().is_relative_to(root):
            raise TestEnvError(f"{ENV_FILE}: {where}: script path escapes the repo")
    return env


def check(repo_root: Path) -> int:
    try:
        load(repo_root)
    except TestEnvError as exc:
        typer.secho(str(exc), fg="red", err=True)
        return 1
    typer.echo("test-env: OK")
    return 0
