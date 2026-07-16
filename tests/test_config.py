from pathlib import Path

import pytest

from center_kb.config import (
    HUB_GUIDE,
    HubConfigError,
    KBConfig,
    effective_repo_id,
    load_config,
    require_hub,
)


def _kb(tmp_path: Path, text: str | None = None) -> Path:
    kb = tmp_path / ".kb"
    kb.mkdir(parents=True)
    if text is not None:
        (kb / "config.yaml").write_text(text, encoding="utf-8")
    return kb


def test_load_config_missing_file_returns_defaults(tmp_path):
    assert load_config(_kb(tmp_path)) == KBConfig()


def test_load_config_reads_hub_and_repo_id(tmp_path):
    kb = _kb(tmp_path, "hub: /srv/kb-hub\nrepo_id: my-kb\n")
    cfg = load_config(kb)
    assert cfg.hub == "/srv/kb-hub"
    assert cfg.repo_id == "my-kb"


def test_require_hub_prefers_cli_value(tmp_path):
    kb = _kb(tmp_path, "hub: /from-config\n")
    assert require_hub("/from-flag", kb) == "/from-flag"


def test_require_hub_falls_back_to_config(tmp_path):
    kb = _kb(tmp_path, "hub: /from-config\n")
    assert require_hub("", kb) == "/from-config"


def test_require_hub_raises_with_guide_when_unconfigured(tmp_path):
    with pytest.raises(HubConfigError) as exc:
        require_hub("", _kb(tmp_path))
    assert str(exc.value) == HUB_GUIDE


def test_effective_repo_id_priority_and_none(tmp_path):
    kb = _kb(tmp_path, "repo_id: cfg-id\n")
    assert effective_repo_id("cli-id", kb) == "cli-id"
    assert effective_repo_id("", kb) == "cfg-id"
    assert effective_repo_id("", _kb(tmp_path / "other")) is None


def test_config_kind_defaults_to_empty(tmp_path):
    from center_kb.config import load_config

    assert load_config(tmp_path).kind == ""  # no config.yaml at all
    (tmp_path / "config.yaml").write_text("hub: /h\n", encoding="utf-8")
    assert load_config(tmp_path).kind == ""  # legacy config without kind


def test_config_kind_roundtrip(tmp_path):
    from center_kb.config import load_config

    (tmp_path / "config.yaml").write_text(
        "hub: '.'\nrepo_id: my-repo\nkind: hub\n", encoding="utf-8"
    )
    cfg = load_config(tmp_path)
    assert cfg.kind == "hub"
    assert cfg.hub == "."


def test_config_kind_rejects_unknown_value(tmp_path):
    import pytest
    from pydantic import ValidationError

    from center_kb.config import load_config

    (tmp_path / "config.yaml").write_text("kind: server\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_config(tmp_path)


def test_asset_store_defaults_to_none(tmp_path):
    (tmp_path / "config.yaml").write_text("hub: '.'\n", encoding="utf-8")
    cfg = load_config(tmp_path)
    assert cfg.asset_store.mode == "none"
    assert cfg.asset_store.prefix == "assets/"


def test_asset_store_parses_s3_block(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "hub: '.'\n"
        "asset_store:\n"
        "  mode: s3\n"
        "  bucket: kb-assets\n"
        "  region: ap-southeast-1\n"
        "  endpoint: https://minio.local:9000\n",
        encoding="utf-8",
    )
    store_cfg = load_config(tmp_path).asset_store
    assert store_cfg.mode == "s3"
    assert store_cfg.bucket == "kb-assets"
    assert store_cfg.region == "ap-southeast-1"
    assert store_cfg.endpoint == "https://minio.local:9000"
    assert store_cfg.prefix == "assets/"


def test_asset_store_rejects_unknown_mode(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "asset_store:\n  mode: ftp\n", encoding="utf-8"
    )
    with pytest.raises(Exception):
        load_config(tmp_path)
