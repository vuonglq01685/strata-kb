"""testenv — load and validate `.kb/test-env.yaml` (env var NAMES only, never values)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import typer
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from strata_kb import httpio
from strata_kb.errors import KbError
from strata_kb.mcpsetup import read_env_value

ENV_FILE = ".kb/test-env.yaml"
SCRIPT_TIMEOUT = 600
HTTP_TIMEOUT = 15
_PROD_NAMES = {"production", "prod"}

_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
# `user:pass@` or `:pass@`. A port-shaped run (`host:8443/…`) is not a password,
# unless it is `user:1234@h` or `user:1234/x@h/` (an `@host/` after a one-segment run).
_USERINFO = re.compile(
    r"[A-Za-z][A-Za-z0-9+.\-]*://[^/\s:@]*:"
    r"(?:(?!\d{1,5}(?:[/?#\s]|$))[^\s@]*@|\d{1,5}/[^\s@?#]*@[^\s/@?#]+/)"
)
_SCHEME_ALIAS = {"postgresql": "postgres"}
_DEFAULT_PORTS = {
    "postgres": "5432",
    "mysql": "3306",
    "redis": "6379",
    "mongodb": "27017",
}
_TOKEN = re.compile(r"[A-Za-z0-9_\-]{32,}")


class TestEnvError(KbError):
    __test__ = False

    def __init__(self, *problems: str) -> None:
        super().__init__(problems[0])
        self.problems = problems


def secret_like(value: str) -> bool:
    """True if `value` holds URL userinfo (`user:pass@`) or a 32+ char token run."""
    if _USERINFO.search(value):
        return True
    return any(
        re.search("[A-Za-z]", t) and re.search("[0-9]", t) and not _ENV_NAME.match(t)
        for t in _TOKEN.findall(value)
    )


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


def _secret_paths(node: Any, path: str = "") -> list[str]:
    """Paths (never values) of every credential-shaped string leaf or dict key."""
    if isinstance(node, str):
        return [path] if secret_like(node) else []
    hits: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if secret_like(str(k)):
                hits.append(f"{path or 'top level'} (key)")
                sub = f"{path}.<redacted>" if path else "<redacted>"
            else:
                sub = f"{path}.{k}" if path else str(k)
            hits += _secret_paths(v, sub)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            hits += _secret_paths(v, f"{path}[{i}]")
    return hits


def _loc(loc: tuple) -> str:
    out = ""
    for part in loc:
        out += (
            f"[{part}]" if isinstance(part, int) else (f".{part}" if out else str(part))
        )
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
    if hits := _secret_paths(raw):
        raise TestEnvError(
            *(
                f"{ENV_FILE}: {h} looks like a credential — keep env var names here, values in .env"
                for h in hits
            )
        )
    try:
        env = TestEnv.model_validate(raw)
    except ValidationError as exc:
        raise TestEnvError(
            *(f"{ENV_FILE}: {_loc(e['loc'])}: {e['msg']}" for e in exc.errors())
        ) from None
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
        for problem in exc.problems:
            typer.secho(problem, fg="red", err=True)
        return 1
    typer.echo("test-env: OK")
    return 0


def _field(body: bytes, dotted: str) -> str:
    node: Any = json.loads(body)
    for part in dotted.split("."):
        node = node[part]
    if not isinstance(node, (str, int)) or isinstance(node, bool) or node == "":
        raise ValueError("not a commit value")
    return str(node)


def app_commits(env: TestEnv, http=httpio.request) -> dict[str, str]:
    """repo -> commit for every app with a version_check."""
    out: dict[str, str] = {}
    for app in env.apps:
        vc = app.version_check
        if vc is None:
            continue
        code, body = http("GET", vc.url, {}, None, HTTP_TIMEOUT)
        if not 200 <= code < 300:
            raise TestEnvError(f"{app.repo}: version check {vc.url} answered {code}")
        try:
            out[app.repo] = _field(body, vc.field)
        except (ValueError, KeyError, TypeError):
            raise TestEnvError(
                f"{app.repo}: field {vc.field!r} missing in {vc.url}"
            ) from None
    return out


def _bare_url(url: str) -> str:
    """URL for protected-URL matching: no userinfo, query, whitespace or trailing
    slash; postgres/postgresql alike; the scheme's default port dropped."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        raise TestEnvError("a URL is malformed") from None
    scheme = parts.scheme.lower()
    scheme = _SCHEME_ALIAS.get(scheme, scheme)
    host = parts.netloc.rpartition("@")[2].lower()
    name, _, port = host.rpartition(":")
    if name and port == _DEFAULT_PORTS.get(scheme):
        host = name
    return urllib.parse.urlunsplit((scheme, host, parts.path, "", "")).rstrip("/")


def run_script(repo_root: Path, env: TestEnv, script: str, run=subprocess.run) -> int:
    """Run a DB script with only the DB URL env var added; refuses production."""
    var = env.db.url_env
    if env.name.lower() in _PROD_NAMES:
        raise TestEnvError(
            f"refusing to run {script}: environment is {env.name!r} (production)"
        )
    value = os.environ.get(var) or read_env_value(repo_root, var)
    if not value:
        raise TestEnvError(f"{var} is not set")
    if _bare_url(value) in {_bare_url(u) for u in env.protected_urls}:
        raise TestEnvError(f"refusing to run {script}: {var} points at a protected URL")
    try:
        proc = run(
            ["bash", script],
            cwd=repo_root,
            timeout=SCRIPT_TIMEOUT,
            env={**os.environ, var: value},
        )
    except subprocess.TimeoutExpired:
        raise TestEnvError(f"{script} timed out after {SCRIPT_TIMEOUT}s") from None
    except OSError as exc:
        raise TestEnvError(f"{script} could not run: {type(exc).__name__}") from None
    return proc.returncode


def _script_item(repo_root: Path, env: TestEnv, script: str, run) -> tuple[bool, str]:
    try:
        code = run_script(repo_root, env, script, run)
    except TestEnvError as exc:
        return False, str(exc)
    return code == 0, "ok" if code == 0 else f"exit {code}"


def verify(repo_root: Path, http=httpio.request, run=subprocess.run) -> int:
    try:
        env = load(repo_root)
    except TestEnvError as exc:
        for problem in exc.problems:
            typer.secho(problem, fg="red", err=True)
        return 1
    failed = False

    def line(ok: bool, item: str, reason: str) -> None:
        nonlocal failed
        failed |= not ok
        typer.echo(f"{'ok' if ok else 'FAIL'} {item}: {reason}")

    for app in env.apps:
        for label, url, lo, hi in (
            ("url", app.url, 200, 400),
            ("api_base", app.api_base, 1, 500),
        ):
            if url:
                code, _ = http("GET", url, {}, None, HTTP_TIMEOUT)
                line(lo <= code < hi, f"{app.repo} {label}", str(code))
    scripts = {"db.check": env.db.check, "db.reset": env.db.reset} | {
        f"db.seeds.{k}": v for k, v in env.db.seeds.items()
    }
    for item, script in scripts.items():
        ok, reason = _script_item(repo_root, env, script, run)
        line(ok, item, reason)
    for app in env.apps:
        if app.version_check is None:
            continue
        try:
            line(
                True,
                f"{app.repo} version",
                app_commits(env.model_copy(update={"apps": [app]}), http)[app.repo],
            )
        except TestEnvError as exc:
            line(False, f"{app.repo} version", str(exc))
    return 1 if failed else 0
