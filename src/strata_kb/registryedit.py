"""Pure edits of federation/registry.yaml and the one commit+push that lands them.

Every edit returns a NEW Registry; none mutates its input. The registry is
the hub's authentication allowlist, so the add rules are stricter than the
load-time rules, but the whole file is only ever re-validated with the
load-time rules (models.Registry) -- an older entry that predates the add
rules must never block an unrelated edit.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from strata_kb import federation, gitio, kinds
from strata_kb.errors import KbError
from strata_kb.models import Registry, RegistryEntry
from strata_kb.pubgate import normalize_repo_id

RegistryChange = Literal["add", "remove", "auto-merge"]

_REL_REGISTRY = f"federation/{federation.REGISTRY_NAME}"


def _claimed_ids(reg: Registry) -> list[str]:
    return [e.repo_id for key in reg.repos if (e := reg.resolve(key)) is not None]


def _validated(repos: dict[str, str | RegistryEntry]) -> Registry:
    try:
        return Registry(repos=repos)
    except ValidationError as exc:
        raise KbError(f"registry is invalid: {exc.errors()[0]['msg']}") from exc


def add_entry(
    reg: Registry,
    repo: str,
    repo_id: str,
    kind: str = "",
    workflow: str = "",
    auto_merge: bool = False,
    existing_dirs: Iterable[str] = (),
) -> Registry:
    """`existing_dirs`: the entry directory names under federation/ on the
    hub, so a repo-id that differs from a removed repo's only in case is
    refused now, not when it first publishes."""
    repo = repo.strip()
    if not repo or any(c.isspace() for c in repo):
        raise KbError("repository must be non-empty with no whitespace (owner/repo)")
    folded = repo.casefold()
    for key in reg.repos:
        if key.casefold() == folded:
            raise KbError(f"repository '{repo}' is already registered as '{key}'")
    claimed = _claimed_ids(reg)
    if repo_id in claimed:
        raise KbError(f"repo-id '{repo_id}' is already claimed by another repository")
    normalize_repo_id(repo_id, [*claimed, *existing_dirs])
    if kind and kind not in kinds.HUB_KINDS:
        raise KbError(f"kind must be one of {list(kinds.HUB_KINDS)} or empty")
    try:
        entry = RegistryEntry(
            repo_id=repo_id,
            workflow=workflow.strip(),
            kind=kind,
            auto_merge=auto_merge,
        )
    except ValidationError as exc:
        raise KbError(f"invalid registry entry: {exc.errors()[0]['msg']}") from exc
    return _validated({**reg.repos, repo: entry})


def remove_entry(reg: Registry, repo: str) -> Registry:
    if repo not in reg.repos:
        raise KbError(f"repository '{repo}' is not in the registry")
    return _validated({k: v for k, v in reg.repos.items() if k != repo})


def set_auto_merge(reg: Registry, repo: str, on: bool) -> Registry:
    entry = reg.resolve(repo)
    if entry is None:
        raise KbError(f"repository '{repo}' is not in the registry")
    return _validated({**reg.repos, repo: entry.model_copy(update={"auto_merge": on})})


def dump_registry(reg: Registry) -> str:
    """YAML for the registry: an entry with only repo_id is the plain string,
    any other is a mapping of just its non-default fields. Dict order is kept."""
    repos: dict[str, Any] = {}
    for key, value in reg.repos.items():
        entry = (
            value if isinstance(value, RegistryEntry) else RegistryEntry(repo_id=value)
        )
        extra = entry.model_dump(exclude_defaults=True, exclude={"repo_id"})
        repos[key] = {"repo_id": entry.repo_id, **extra} if extra else entry.repo_id
    return yaml.safe_dump({"repos": repos}, sort_keys=False, allow_unicode=True)


def parse_registry(text: str) -> Registry:
    """The load-time parse of registry.yaml text, with short user-facing errors."""
    try:
        return Registry.model_validate(yaml.safe_load(text) or {})
    except ValidationError as exc:
        raise KbError(
            f"federation/registry.yaml is invalid: {exc.errors()[0]['msg']}"
        ) from exc
    except yaml.YAMLError as exc:
        raise KbError("federation/registry.yaml is invalid: not valid YAML") from exc


def read_registry(hub_root: Path) -> Registry:
    """The registry as committed on the hub's default branch -- the same base
    `edit_registry` / `commit_registry` commit onto, so what an admin sees is
    what an edit starts from. Never the working tree: a checkout on another
    branch or with an uncommitted hand-edit must not leak into the registry."""
    branch = gitio.default_branch(hub_root)
    proc = gitio._run(hub_root, "show", f"{branch}:{_REL_REGISTRY}")
    return parse_registry(proc.stdout) if proc.returncode == 0 else Registry()


def _commit_on_default_branch(
    hub_root: Path,
    produce: Callable[[Path], str | None],
    message: str,
    push: Callable[[Path, str], None],
) -> bool:
    """Commit what `produce(worktree)` returns as federation/registry.yaml on
    the default branch (None = nothing to change) in a throwaway detached
    worktree and hand it to `push(worktree, branch)`.

    The hub checkout is never touched. Only the registry path is staged, so
    stray files in the worktree (.kb-auth/) cannot ride along.
    """
    # Lazy: intake is a heavy module and may itself import registryedit.
    from strata_kb.intake import _hub_write_lock

    branch = gitio.default_branch(hub_root)
    with tempfile.TemporaryDirectory(prefix="kb-registry-") as tmp:
        work = Path(tmp) / "hub"
        with _hub_write_lock:
            gitio.worktree_prune(hub_root)
            gitio.worktree_add_detached(hub_root, work, branch)
        try:
            text = produce(work)
            if text is None:
                return False
            target = work / _REL_REGISTRY
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
            if not gitio.commit_paths(work, message, [_REL_REGISTRY]):
                return False
            push(work, branch)
            return True
        finally:
            with _hub_write_lock:
                gitio.worktree_remove(hub_root, work)


def edit_registry(
    hub_root: Path,
    edit: Callable[[Registry, Path], Registry],
    message: str,
    push: Callable[[Path, str], None],
) -> bool:
    """Read the registry from the default branch's own worktree, apply
    `edit(registry, federation_dir)` and commit+push the result: the base read
    is the base committed on. False when the edit changes nothing."""

    def produce(work: Path) -> str | None:
        reg_file = work / _REL_REGISTRY
        reg = (
            parse_registry(reg_file.read_text(encoding="utf-8"))
            if reg_file.exists()
            else Registry()
        )
        edited = edit(reg, work / "federation")
        return None if edited == reg else dump_registry(edited)

    return _commit_on_default_branch(hub_root, produce, message, push)


def commit_registry(
    hub_root: Path,
    text: str,
    message: str,
    push: Callable[[Path, str], None],
) -> bool:
    """Commit `text` as federation/registry.yaml on the hub's default branch
    and hand it to `push(worktree, branch)`.

    False (and no push) when `text` is what the branch already holds.
    """
    try:
        Registry.model_validate(yaml.safe_load(text))
    except ValidationError as exc:
        raise KbError(
            f"refusing to write an invalid registry: {exc.errors()[0]['msg']}"
        ) from exc
    except yaml.YAMLError as exc:
        raise KbError("refusing to write an invalid registry: not valid YAML") from exc
    return _commit_on_default_branch(hub_root, lambda _work: text, message, push)
