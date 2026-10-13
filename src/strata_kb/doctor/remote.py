"""`kb doctor` for ba and dev repos over the hub's MCP, with no hub clone.

BA and Dev people usually have no git access to the hub repo, only the
hub's HTTP MCP (`STRATA_KB_HUB_URL` + `STRATA_KB_HTTP_TOKEN`, written by
`kb mcp-setup`). The hub answers the `kb_doctor_hub` tool with what only it
can see -- its snapshot of this repo as a digest, its `<repo_id>-code`
section digests, the registry's kind pin, citation checks -- and the repo
compares that with its own `.kb/` locally. Hub-wide federation checks
(strays, index sync) stay with the hub maintainer's own `kb doctor`.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from strata_kb import config as config_mod
from strata_kb import gitio, kinds
from strata_kb.doctor.checks.context import check_context
from strata_kb.doctor.checks.hub import (
    _ENTRY_SEGMENT_RE,
    _kb_tree_digest,
    duplicate_doc_id_issues,
    published_digest,
    registry_kind_issues,
    snapshot_drift_issues,
    unpublished_issue,
)
from strata_kb.doctor.issues import _CONFIG_READ_ERRORS, Issue, _flatten
from strata_kb.errors import KbError

if TYPE_CHECKING:
    from strata_kb.doctor import DoctorResult
    from strata_kb.hub import HubHandle

TOOL = "kb_doctor_hub"
REMOTE_KINDS = ("child", "ba", "dev")
# The hub's version goes into a pip command: a plain release string only.
_VERSION_RE = re.compile(
    r"[0-9]+(\.[0-9]+)*([a-z]+[0-9]*)?(\.post[0-9]+)?(\.dev[0-9]+)?"
)
# Set on the `kb doctor` that runs after an install, so a failed upgrade
# cannot loop.
UPGRADED_ENV = "STRATA_KB_DOCTOR_UPGRADED"
# `pip install strata-kb==X` in a repo's CI workflows (codeingest.sync's pin).
_PIN_RE = re.compile(r"strata-kb==([^\s\"']+)")
CONNECT_TIMEOUT = 30  # a human is waiting on `kb doctor`
READ_TIMEOUT = 300  # hashing a large hub entry, or a TTL pull, takes a while


class RemoteDoctorError(KbError):
    """The hub's MCP could not answer `kb doctor`."""


def generated_doc(kind: str, repo_id: str) -> str | None:
    """The doc a ba/dev repo regenerates per branch: left out of the
    snapshot compare (dev `-code`, ba `-plan`)."""
    suffix = {"dev": "code", "ba": "plan"}.get(kind)
    return f"{repo_id}-{suffix}" if suffix and repo_id else None


# --- hub side -------------------------------------------------------------


def hub_facts(
    handle: HubHandle,
    *,
    kind: str,
    repo_id: str,
    remote_url: str = "",
    dir_name: str = "",
    kb_context: str | None = None,
) -> dict[str, Any]:
    """What the hub tells a ba/dev repo's `kb doctor`. `repo_id` is the
    repo's configured id ('' = unset: the registry decides, as for `kb
    publish`); its entry is federation/<repo_id or dir_name>. `dir_name` is
    '' when the repo is not a git repo: no registry identity then, as in
    `check_published_kind`. Both come from the client, so the entry name is
    checked before it becomes a path."""
    import strata_kb
    from strata_kb.codeingest import hublag

    if kind not in REMOTE_KINDS:
        return {"error": f"kind must be one of {', '.join(REMOTE_KINDS)}, not '{kind}'"}
    entry_id = repo_id or dir_name
    if entry_id and not _ENTRY_SEGMENT_RE.fullmatch(entry_id):
        return {"error": f"invalid repo_id '{entry_id}'"}
    fed = handle.federation_dir
    entry = fed / entry_id if entry_id else None
    code_doc = generated_doc(kind, entry_id)
    skip = frozenset({code_doc}) if code_doc else frozenset()
    published = entry is not None and entry.is_dir()

    issues: list[Issue] = []
    if dir_name:
        issues += registry_kind_issues(
            handle,
            kinds.hub_kind(kind),
            remote_url=lambda: remote_url,
            repo_id=repo_id or None,
            dir_name=dir_name,
            hub_label="the hub",
        )
    issues += duplicate_doc_id_issues(fed)
    context_stale = False
    if kb_context is not None:
        ctx_issues, results = check_context(kb_context, handle)
        issues += ctx_issues
        context_stale = any(r.status == "stale" for r in results)
    try:
        hub_commit = gitio.head_commit(handle.root)
    except gitio.GitError:
        hub_commit = ""
    return {
        "hub_commit": hub_commit,
        "hub_version": strata_kb.__version__,
        "stale": handle.stale,
        "age_seconds": handle.age_seconds,
        "published": published,
        "snapshot_digest": (
            published_digest(handle, entry, skip) if entry and published else None
        ),
        "code_sections": (
            hublag.hub_code_digests(fed, entry_id)
            if kind == "dev" and entry_id
            else None
        ),
        "issues": [asdict(i) for i in issues],
        "context_stale": context_stale,
    }


# --- repo side ------------------------------------------------------------


def mcp_target(repo_root: Path) -> tuple[str, str] | None:
    """(hub URL, token) from the environment, else `.env`; None when either
    is missing -- `kb doctor` then falls back to the git hub."""
    from strata_kb import mcpsetup

    url = os.environ.get(mcpsetup.HUB_URL_VAR) or mcpsetup.read_env_value(
        repo_root, mcpsetup.HUB_URL_VAR
    )
    token = os.environ.get(mcpsetup.TOKEN_VAR) or mcpsetup.read_env_value(
        repo_root, mcpsetup.TOKEN_VAR
    )
    if not (url and token):
        return None
    try:
        return mcpsetup.normalize_hub_url(url), token
    except mcpsetup.McpSetupError as exc:
        raise RemoteDoctorError(f"{mcpsetup.HUB_URL_VAR}: {_flatten(exc)}") from exc


def request_args(kb_dir: Path, kind: str, kb_context: str | None) -> dict[str, Any]:
    """The tool arguments: this repo's identity as `kb publish` states it
    (configured id, directory name, origin URL without its credential) and
    the kb-context block to check."""
    try:
        repo_root = gitio.git_root(kb_dir.resolve())
    except gitio.GitError:
        remote, dir_name = "", ""  # no git repo: no registry identity
    else:
        remote = gitio.split_credentials(gitio.remote_url(repo_root))[0]
        dir_name = repo_root.name
    args: dict[str, Any] = {
        "kind": kind,
        "repo_id": config_mod.effective_repo_id("", kb_dir) or "",
        "remote_url": remote,
        "dir_name": dir_name,
    }
    if kb_context is not None:
        args["kb_context"] = kb_context
    return args


async def call_facts(session, args: dict[str, Any]) -> dict[str, Any]:
    """Call the tool on an initialized MCP `ClientSession`."""
    result = await session.call_tool(TOOL, args)
    text = result.content[0].text if result.content else ""
    if result.isError:
        if "Unknown tool" in text:
            raise RemoteDoctorError(
                f"the hub has no {TOOL} tool — upgrade strata-kb on the hub "
                "to 1.22.1 or later"
            )
        raise RemoteDoctorError(
            f"{TOOL} failed on the hub: {_flatten(Exception(text))}"
        )
    try:
        facts = json.loads(text)
    except ValueError:
        raise RemoteDoctorError(
            f"{TOOL} answered: {_flatten(Exception(text))}"
        ) from None
    if "error" in facts:
        raise RemoteDoctorError(f"{TOOL}: {facts['error']}")
    return facts


def fetch_facts(url: str, token: str, args: dict[str, Any]) -> dict[str, Any]:
    """One `kb_doctor_hub` call over the hub's streamable HTTP MCP."""
    import anyio
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    # streamablehttp_client is deprecated in newer 1.x but present in every
    # mcp<2 that has the HTTP transport at all (>=1.8); its successor is not.
    async def _go() -> dict[str, Any]:
        async with (
            streamablehttp_client(
                f"{url}/mcp",
                headers={"Authorization": f"Bearer {token}"},
                timeout=CONNECT_TIMEOUT,
                sse_read_timeout=READ_TIMEOUT,
            ) as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            return await call_facts(session, args)

    try:
        return anyio.run(_go)
    except Exception as exc:  # noqa: BLE001 -- anyio wraps transport errors in groups
        leaf = _leaf(exc)
        if isinstance(leaf, RemoteDoctorError):
            raise leaf from None
        # httpx repeats the URL in its errors: redact the whole message.
        raise RemoteDoctorError(
            gitio.redact_url(
                f"could not reach the hub's MCP at {url}/mcp: "
                f"{_flatten(Exception(leaf))}"
            )
        ) from None


def _leaf(exc: BaseException) -> BaseException:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def run(kb_dir: Path, facts: dict[str, Any], hub_label: str) -> DoctorResult:
    """`doctor.run` for a ba/dev repo, its hub side taken from `facts`."""
    from strata_kb import publish
    from strata_kb.codeingest import hublag
    from strata_kb.doctor import (
        DoctorResult,
        check_dev_sync,
        check_usage_hooks,
        check_usage_log,
        local_issues,
    )
    from strata_kb.doctor.checks.dev import lag_issues

    commit = facts.get("hub_commit") or "?"
    issues = [Issue("info", f"hub checked over MCP at {hub_label} (hub HEAD {commit})")]
    issues += local_issues(kb_dir, None)
    try:
        kind = config_mod.load_config(kb_dir).kind
    except (*_CONFIG_READ_ERRORS, OSError) as exc:
        issues.append(
            Issue("error", f"could not read .kb/config.yaml: {_flatten(exc)}")
        )
        return DoctorResult(issues=issues, stale=False)
    repo_id = repo_id_for(kb_dir)
    issues += version_issues(_git_root(kb_dir), facts.get("hub_version"))
    if kind in ("ba", "dev"):
        issues += check_usage_log(kb_dir)
        issues += check_usage_hooks(kb_dir.resolve().parent)

    hub_stale = bool(facts.get("stale"))
    if hub_stale:
        age = facts.get("age_seconds")
        age_text = f"~{age:.0f}s" if age else "unknown"
        issues.append(
            Issue("warning", f"hub cache is stale (pull failed, age {age_text})")
        )
    code_doc = generated_doc(kind, repo_id or "")
    if not repo_id:
        pass  # no id and no git repo: nothing on the hub to compare, as in doctor.run
    elif not facts.get("published"):
        issues.append(unpublished_issue(repo_id))
    else:
        skip = frozenset({code_doc}) if code_doc else frozenset()
        issues += snapshot_drift_issues(
            _kb_tree_digest(kb_dir.resolve(), exclude_docs=skip),
            facts.get("snapshot_digest") or "",
            repo_id,
            code_doc,
        )
    issues.append(Issue("info", publish.kind_line(kind)))
    # Only the fields this client knows: a newer hub may send more.
    issues += [
        Issue(i["level"], i["message"], i.get("code", ""))
        for i in facts.get("issues", [])
    ]
    if kind == "dev":
        repo_root = kb_dir.resolve().parent
        issues += check_dev_sync(kb_dir, repo_root, repo_id)
        if repo_id:
            report = hublag.check_against(
                repo_root, kb_dir, repo_id, facts.get("code_sections")
            )
            issues += lag_issues(report, repo_id)
    return DoctorResult(
        issues=issues, stale=hub_stale or bool(facts.get("context_stale"))
    )


def repo_id_for(kb_dir: Path) -> str | None:
    """The repo id `doctor.run` uses: config's, else the git root's name,
    else None."""
    repo_id = config_mod.effective_repo_id("", kb_dir)
    if repo_id:
        return repo_id
    try:
        return gitio.git_root(kb_dir.resolve()).name
    except gitio.GitError:
        return None


def _git_root(kb_dir: Path) -> Path | None:
    try:
        return gitio.git_root(kb_dir.resolve())
    except gitio.GitError:
        return None


def version_issues(repo_root: Path | None, hub_version: str | None) -> list[Issue]:
    """Every repo on a hub runs the hub's strata-kb: the installed package
    and each `strata-kb==X` pin in the repo's CI workflows."""
    import strata_kb

    if not hub_version:
        return []
    issues: list[Issue] = []
    if strata_kb.__version__ != hub_version:
        issues.append(
            Issue(
                "error",
                f"strata-kb {strata_kb.__version__} is installed but the hub runs "
                f"{hub_version} — every repo on a hub uses the hub's version: "
                f"pip install strata-kb=={hub_version}",
            )
        )
    workflows = repo_root / ".github" / "workflows" if repo_root else None
    if workflows is None or not workflows.is_dir():
        return issues
    for wf in sorted(workflows.glob("*.y*ml")):
        try:
            pins = sorted(set(_PIN_RE.findall(wf.read_text(encoding="utf-8"))))
        except (OSError, UnicodeDecodeError):
            continue
        issues += [
            Issue(
                "error",
                f".github/workflows/{wf.name} pins strata-kb=={pin} but the hub "
                f"runs {hub_version} — change the pin to strata-kb=={hub_version}",
            )
            for pin in pins
            if pin != hub_version
        ]
    return issues


def install_version(version: str) -> str | None:
    """Install strata-kb==`version` into this interpreter: pip, else uv (a
    uv-made venv has no pip). None on success, else the last error."""
    if not _VERSION_RE.fullmatch(version):
        return f"the hub reported an invalid version '{version}'"
    # shortcut: installs the base package only; extras ([ingest], [embed])
    # keep their installed deps -- upgrade those by hand if a release needs it.
    spec = f"strata-kb=={version}"
    commands = [[sys.executable, "-m", "pip", "install", "--quiet", spec]]
    uv = shutil.which("uv")
    if uv:
        commands.append(
            [uv, "pip", "install", "--quiet", "--python", sys.executable, spec]
        )
    error = ""
    for cmd in commands:
        # argv list, no shell; the version was matched against _VERSION_RE above.
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode == 0:
            return None
        error = _flatten(
            Exception(proc.stderr or proc.stdout or f"exit {proc.returncode}")
        )
    return error


def fix_pins(repo_root: Path | None, hub_version: str) -> list[str]:
    """Rewrite each `strata-kb==X` pin in the repo's CI workflows to the hub's
    version -- that string only, nothing else in the file. Returns what changed."""
    workflows = repo_root / ".github" / "workflows" if repo_root else None
    if (
        workflows is None
        or not workflows.is_dir()
        or not _VERSION_RE.fullmatch(hub_version)
    ):
        return []
    changed: list[str] = []
    for wf in sorted(workflows.glob("*.y*ml")):
        try:
            text = wf.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        old = sorted({p for p in _PIN_RE.findall(text) if p != hub_version})
        if not old:
            continue
        new_text = _PIN_RE.sub(f"strata-kb=={hub_version}", text)
        try:
            wf.write_text(new_text, encoding="utf-8", newline="\n")
        except OSError:
            continue
        changed.append(
            f".github/workflows/{wf.name}: strata-kb=={', '.join(old)} → {hub_version}"
        )
    return changed
