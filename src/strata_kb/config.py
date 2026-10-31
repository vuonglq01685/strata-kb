"""config — the `.kb/config.yaml` model and hub resolution.

`KBConfig` is the parsed file (hub, repo id, repo kind, intake URL, asset
store, languages, code-ingest settings); `load_config()` returns defaults when
the file is absent. `require_hub()` and `effective_repo_id()` fold the CLI or
environment value over the file, and `require_hub()` raises `HubConfigError`
when neither names a hub.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from strata_kb import models
from strata_kb.errors import KbError

CONFIG_NAME = "config.yaml"

HUB_GUIDE = (
    "no hub configured — add `hub: <url|path>` to .kb/config.yaml "
    "(or pass --hub / set STRATA_KB_HUB)"
)


class HubConfigError(KbError):
    """The hub is mandatory (federation is the only read source) but not
    configured. Every raise site's caller already converts it to a one-line
    CLI message -- joins the KbError family."""


class AssetStoreConfig(BaseModel):
    """Object-store settings for image assets. Credentials never
    live here — boto3's standard chain (env / instance role) supplies them."""

    mode: Literal["none", "s3"] = "none"
    bucket: str = ""
    region: str = ""
    endpoint: str = ""  # S3-compatible endpoint (MinIO, R2); empty = AWS
    prefix: str = "assets/"


class CodeIngestConfig(BaseModel):
    """`code_ingest:` — the one ingest configuration local runs and CI share.
    `db` stays explicit-only, exactly like `--db`:
    a stray test fixture must never become published knowledge."""

    db: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class AutoConfig(BaseModel):
    """`auto:` — the full-auto mode switch and its poll intervals (seconds).
    `hotfix_base` empty = the repo's default branch."""

    enabled: bool = False
    qa_interval: int = 300
    idle_interval: int = 600
    hotfix_base: str = ""
    claim_heartbeat: int = 900  # seconds between claim heartbeats while a task runs


class L3FixConfig(BaseModel):
    """`l3_fix:` — the AI structure fix of L3 switch (default off)."""

    enabled: bool = False


class KBConfig(BaseModel):
    hub: str = ""
    repo_id: str = ""
    kind: Literal["", "hub", "child", "ba", "dev"] = ""
    intake: str = ""  # intake service base URL — child publishes via OIDC CI
    asset_store: AssetStoreConfig = Field(default_factory=AssetStoreConfig)
    langs: list[str] = Field(default_factory=list)
    code_ingest: CodeIngestConfig = Field(default_factory=CodeIngestConfig)
    auto: AutoConfig = Field(default_factory=AutoConfig)
    l3_fix: L3FixConfig = Field(default_factory=L3FixConfig)


def load_config(kb_dir: Path) -> KBConfig:
    path = kb_dir / CONFIG_NAME
    if not path.exists():
        return KBConfig()
    return models.load_yaml_model(path, KBConfig)


def require_hub(cli_value: str, kb_dir: Path) -> str:
    """cli_value has env folded in already (typer envvar / mcp parse_args fold
    STRATA_KB_HUB themselves).
    """
    hub = cli_value or load_config(kb_dir).hub
    if not hub:
        raise HubConfigError(HUB_GUIDE)
    return hub


def effective_repo_id(cli_value: str, kb_dir: Path) -> str | None:
    return cli_value or load_config(kb_dir).repo_id or None


_NEXT_TOP_KEY = re.compile(r"^[^\s#]", re.MULTILINE)
_ENABLED_LINE = re.compile(
    r"^([ \t]+)enabled:[ \t]*[^\s#]*([ \t]+#.*)?[ \t]*$", re.MULTILINE
)


def set_block_enabled(config_path: Path, block: str, on: bool) -> None:
    """Flip `<block>.enabled` in the config file by text edit, so operator
    comments and other keys survive (same append-only style as
    `initcmd._record_kind`). `block` is a top-level `KBConfig` field."""
    flag = "true" if on else "false"
    text = config_path.read_text(encoding="utf-8") if config_path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    head = re.search(rf"^{re.escape(block)}:[ \t]*(#.*)?$", text, re.MULTILINE)
    if head is None:
        if re.search(rf"^{re.escape(block)}:", text, re.MULTILINE):
            raise ValueError(f"`{block}:` must be a block mapping to be switched")
        out = text + f"{block}:\n  enabled: {flag}\n"
    else:
        nxt = _NEXT_TOP_KEY.search(text, head.end() + 1)
        end = nxt.start() if nxt else len(text)
        body = text[head.end() : end]
        if _ENABLED_LINE.search(body):
            body = _ENABLED_LINE.sub(rf"\1enabled: {flag}\2", body, count=1)
        else:
            body = f"\n  enabled: {flag}" + body
        out = text[: head.end()] + body + text[end:]
    parsed = yaml.safe_load(out) or {}
    if getattr(KBConfig.model_validate(parsed), block).enabled is not on:
        raise ValueError(
            f"could not set {block}.enabled in {config_path} -- edit it by hand"
        )
    config_path.write_text(out, encoding="utf-8", newline="\n")
