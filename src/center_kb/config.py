from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from center_kb import models

CONFIG_NAME = "config.yaml"

HUB_GUIDE = (
    "no hub configured — add `hub: <url|path>` to .kb/config.yaml "
    "(or pass --hub / set CENTER_KB_HUB)"
)


class HubConfigError(RuntimeError):
    """The hub is mandatory (federation is the only read source) but not configured."""


class KBConfig(BaseModel):
    hub: str = ""
    repo_id: str = ""


def load_config(kb_dir: Path) -> KBConfig:
    path = kb_dir / CONFIG_NAME
    if not path.exists():
        return KBConfig()
    return models.load_yaml_model(path, KBConfig)


def require_hub(cli_value: str, kb_dir: Path) -> str:
    """cli_value đã gộp env (typer envvar / mcp parse_args tự fold CENTER_KB_HUB)."""
    hub = cli_value or load_config(kb_dir).hub
    if not hub:
        raise HubConfigError(HUB_GUIDE)
    return hub


def effective_repo_id(cli_value: str, kb_dir: Path) -> str | None:
    return cli_value or load_config(kb_dir).repo_id or None
