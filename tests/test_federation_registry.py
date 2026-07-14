from __future__ import annotations

import pytest

from center_kb import federation, models


def test_missing_file_returns_empty(tmp_path):
    reg = federation.load_registry(tmp_path)
    assert reg.repos == {}


def test_loads_mapping(tmp_path):
    (tmp_path / "registry.yaml").write_text(
        "repos:\n  acme/flight-docs: flight-docs\n", encoding="utf-8"
    )
    reg = federation.load_registry(tmp_path)
    assert reg.repos["acme/flight-docs"] == "flight-docs"


@pytest.mark.parametrize("bad", ["repos: [broken", "repos: 42"])
def test_invalid_yaml_or_schema_raises(tmp_path, bad):
    (tmp_path / "registry.yaml").write_text(bad, encoding="utf-8")
    with pytest.raises(federation.RegistryError):
        federation.load_registry(tmp_path)
