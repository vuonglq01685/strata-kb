from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from center_kb import models
from center_kb.errors import KbError

CONFIG_NAME = "config.yaml"

HUB_GUIDE = (
    "no hub configured — add `hub: <url|path>` to .kb/config.yaml "
    "(or pass --hub / set CENTER_KB_HUB)"
)


class HubConfigError(KbError):
    """The hub is mandatory (federation is the only read source) but not
    configured. Every raise site's caller already converts it to a one-line
    CLI message -- joins the KbError family (Wave G fix round 2, item 7)."""


class AssetStoreConfig(BaseModel):
    """Object-store settings for image assets (spec B). Credentials never
    live here — boto3's standard chain (env / instance role) supplies them."""

    mode: Literal["none", "s3"] = "none"
    bucket: str = ""
    region: str = ""
    endpoint: str = ""  # S3-compatible endpoint (MinIO, R2); empty = AWS
    prefix: str = "assets/"


class KBConfig(BaseModel):
    hub: str = ""
    repo_id: str = ""
    kind: Literal["", "hub", "child", "ba", "dev"] = ""
    intake: str = ""  # intake service base URL — child publishes via OIDC CI
    asset_store: AssetStoreConfig = Field(default_factory=AssetStoreConfig)
    langs: list[str] = Field(default_factory=list)


def load_config(kb_dir: Path) -> KBConfig:
    path = kb_dir / CONFIG_NAME
    if not path.exists():
        return KBConfig()
    return models.load_yaml_model(path, KBConfig)


def require_hub(cli_value: str, kb_dir: Path) -> str:
    """cli_value has env folded in already (typer envvar / mcp parse_args fold
    CENTER_KB_HUB themselves).
    """
    hub = cli_value or load_config(kb_dir).hub
    if not hub:
        raise HubConfigError(HUB_GUIDE)
    return hub


def effective_repo_id(cli_value: str, kb_dir: Path) -> str | None:
    return cli_value or load_config(kb_dir).repo_id or None
