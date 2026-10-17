from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from strata_kb.autorun import trust


def test_trust_creates_file(tmp_path: Path):
    config = tmp_path / ".claude.json"
    a = tmp_path / "a"

    trust.trust_dirs([a], config)

    data = json.loads(config.read_text(encoding="utf-8"))
    assert data == {"projects": {str(a.resolve()): {"hasTrustDialogAccepted": True}}}


def test_trust_fills_an_existing_empty_file(tmp_path: Path):
    config = tmp_path / ".claude.json"
    config.write_text("", encoding="utf-8")
    a = tmp_path / "a"

    trust.trust_dirs([a], config)

    data = json.loads(config.read_text(encoding="utf-8"))
    assert data == {"projects": {str(a.resolve()): {"hasTrustDialogAccepted": True}}}


def test_trust_keeps_other_keys(tmp_path: Path):
    config = tmp_path / ".claude.json"
    a = tmp_path / "a"
    key = str(a.resolve())
    config.write_text(
        json.dumps({"x": 1, "projects": {"/o": {"k": 2}, key: {"allowedTools": []}}}),
        encoding="utf-8",
    )

    trust.trust_dirs([a], config)

    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["x"] == 1
    assert data["projects"]["/o"] == {"k": 2}
    assert data["projects"][key] == {"allowedTools": [], "hasTrustDialogAccepted": True}


@pytest.mark.parametrize("text", ["{nope", '{"projects": []}', "[]"])
def test_trust_skips_unusable_config(tmp_path: Path, caplog, text):
    config = tmp_path / ".claude.json"
    config.write_text(text, encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        trust.trust_dirs([tmp_path / "a"], config)

    assert config.read_text(encoding="utf-8") == text
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_trust_resolves_relative_paths(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = tmp_path / ".claude.json"

    trust.trust_dirs([Path(".kb/auto/worktrees/qa")], config)

    data = json.loads(config.read_text(encoding="utf-8"))
    assert list(data["projects"]) == [
        str((tmp_path / ".kb/auto/worktrees/qa").resolve())
    ]


def test_trust_leaves_no_temp_files(tmp_path: Path):
    trust.trust_dirs([tmp_path / "a"], tmp_path / ".claude.json")

    assert [p.name for p in tmp_path.iterdir()] == [".claude.json"]
