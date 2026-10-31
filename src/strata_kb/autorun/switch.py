"""switch — the `auto:` block in `.kb/config.yaml`: flip it, warn, report.

`set_enabled` edits text, not the parsed model, so operator comments and
other keys survive (same append-only style as `initcmd._record_kind`).
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from strata_kb import cloud, gitio, hubapi
from strata_kb.autorun import state as autostate
from strata_kb.autorun.lock import running_pid
from strata_kb.config import (
    HubConfigError,
    load_config,
    require_hub,
    set_block_enabled,
)
from strata_kb.errors import KbError
from strata_kb.federation import RegistryError, load_registry
from strata_kb.hub import resolve_hub
from strata_kb.models import Registry

ADMIN_WARNING = (
    "Auto mode merges pull requests as admin, with no review. "
    "Turn it on only for a repo where that is acceptable."
)


def set_enabled(config_path: Path, on: bool) -> None:
    set_block_enabled(config_path, "auto", on)


def registry_or_reason(kb_dir: Path, hub: str) -> tuple[Registry | None, str]:
    """The hub's registry, or why it could not be read. Never exits or prints."""
    try:
        handle = resolve_hub(require_hub(hub, kb_dir))
        if handle is None:
            return None, "hub unreachable and not cached"
        return load_registry(handle.federation_dir), ""
    except (
        HubConfigError,
        RegistryError,
        gitio.GitError,
        yaml.YAMLError,
        ValidationError,
        ValueError,
        OSError,
    ) as exc:
        return None, gitio.redact_url(" ".join(str(exc).split()))


def cloud_entry_or_reason(repo_id: str) -> tuple[dict | None, str]:
    """Cloud: `repo_id`'s registry facts from the hub's API, else why not.
    `(None, "")` = the hub does not list it."""
    try:
        return hubapi.from_env().registry_entry(repo_id), ""
    except KbError as exc:
        return None, gitio.redact_url(" ".join(str(exc).split()))


def _cloud_warnings(kb_dir: Path) -> list[str]:
    try:
        repo_id = load_config(kb_dir).repo_id
    except (
        OSError,
        ValueError,
        yaml.YAMLError,
    ) as exc:  # ValidationError is a ValueError
        return [
            f"Registry not checked ({' '.join(str(exc).split())}), so a second Dev repo would go unnoticed."
        ]
    facts, reason = cloud_entry_or_reason(repo_id)
    if facts is None:
        reason = reason or f"repo_id '{repo_id}' is not in the hub registry"
        return [
            f"Registry not checked ({reason}), so a second Dev repo would go unnoticed."
        ]
    if facts["dev_repos"] > 1:
        return [
            f"Auto mode supports one Dev repo per hub, "
            f"but the registry lists {facts['dev_repos']}."
        ]
    return []


def warnings_for_on(kb_dir: Path, hub: str) -> list[str]:
    warnings = [ADMIN_WARNING]
    if cloud.is_cloud():
        return warnings + _cloud_warnings(kb_dir)
    registry, reason = registry_or_reason(kb_dir, hub)
    if registry is None:
        warnings.append(
            f"Registry not checked ({reason}), so a second Dev repo would go unnoticed."
        )
        return warnings
    devs = [
        repo
        for repo in registry.repos
        if (entry := registry.resolve(repo)) and entry.kind == "dev"
    ]
    if len(devs) > 1:
        warnings.append(
            f"Auto mode supports one Dev repo per hub, "
            f"but the registry lists {len(devs)}: {', '.join(sorted(devs))}."
        )
    return warnings


def status(kb_dir: Path) -> dict:
    auto = load_config(kb_dir).auto
    state = autostate.load(kb_dir)
    return {
        "enabled": auto.enabled,
        "qa_interval": auto.qa_interval,
        "idle_interval": auto.idle_interval,
        "hotfix_base": auto.hotfix_base,
        "task": state.task,
        "attempts": state.attempts,
        "waiting_on": list(state.waiting_on),
        "stop_reason": state.stop_reason,
        "skipped": list(state.skipped),
        # For /kb-auto: is a loop alive (OS lock probe), and which branch the
        # switch must be pushed to.
        "running": _running_pid(kb_dir),
        "default_branch": _default_branch(kb_dir),
        # For /kb-auto: on Claude Code cloud the switch goes out as an
        # `auto/switch` PR and the session watches the loop with `kb auto wait`.
        "cloud": cloud.is_cloud(),
    }


def _running_pid(kb_dir: Path) -> int | None:
    return running_pid(kb_dir)


def _default_branch(kb_dir: Path) -> str | None:
    try:
        return gitio.default_branch(gitio.git_root(kb_dir.resolve()))
    except (gitio.GitError, OSError, ValueError):
        return None
