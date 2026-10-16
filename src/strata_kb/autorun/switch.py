"""switch — the `auto:` block in `.kb/config.yaml`: flip it, warn, report.

`set_enabled` edits text, not the parsed model, so operator comments and
other keys survive (same append-only style as `initcmd._record_kind`).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import ValidationError

from strata_kb import gitio
from strata_kb.autorun import state as autostate
from strata_kb.config import HubConfigError, KBConfig, load_config, require_hub
from strata_kb.federation import RegistryError, load_registry
from strata_kb.hub import resolve_hub
from strata_kb.models import Registry

_AUTO_LINE = re.compile(r"^auto:[ \t]*(#.*)?$", re.MULTILINE)
_AUTO_ANY = re.compile(r"^auto:", re.MULTILINE)
_NEXT_TOP_KEY = re.compile(r"^[^\s#]", re.MULTILINE)
_ENABLED_LINE = re.compile(
    r"^([ \t]+)enabled:[ \t]*[^\s#]*([ \t]+#.*)?[ \t]*$", re.MULTILINE
)

ADMIN_WARNING = (
    "Auto mode merges pull requests as admin, with no review. "
    "Turn it on only for a repo where that is acceptable."
)


def set_enabled(config_path: Path, on: bool) -> None:
    flag = "true" if on else "false"
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    head = _AUTO_LINE.search(text)
    if head is None:
        if _AUTO_ANY.search(text):
            raise ValueError("`auto:` must be a block mapping to be switched")
        out = text + f"auto:\n  enabled: {flag}\n"
    else:
        nxt = _NEXT_TOP_KEY.search(text, head.end() + 1)
        end = nxt.start() if nxt else len(text)
        block = text[head.end() : end]
        if _ENABLED_LINE.search(block):
            block = _ENABLED_LINE.sub(rf"\1enabled: {flag}\2", block, count=1)
        else:
            block = f"\n  enabled: {flag}" + block
        out = text[: head.end()] + block + text[end:]
    parsed = yaml.safe_load(out) or {}
    if KBConfig.model_validate(parsed).auto.enabled is not on:
        raise ValueError(
            f"could not set auto.enabled in {config_path} -- edit it by hand"
        )
    config_path.write_text(out, encoding="utf-8", newline="\n")


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


def warnings_for_on(kb_dir: Path, hub: str) -> list[str]:
    warnings = [ADMIN_WARNING]
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
    }
