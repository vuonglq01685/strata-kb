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
